import asyncio
import json
import urllib.parse
from typing import Any, Dict, List, Optional
from ..logging.logging import get_logger
from .models import FolderModel, SymbolModel, FileModel, json_to_range
from .lsp_client import LSPClient
from src.extraction.extraction_utils import normalize_path
from pathlib import Path
import os
import itertools
import sys
import time

logger = get_logger(__name__)

class LSP_Extractor:
    def __init__(self, project: FolderModel, use_docker: bool = True):
        self.project = project
        self.use_docker = use_docker
        self.config = self._retrieve_config()
        self.servers: Dict[str, LSPClient] = {}
        self.opened_files = set()

    def _retrieve_config(self):
        """Retrieve config for LSP servers commands."""
        config_path = Path(__file__).parent / 'extract_config/lsp_configs.json'
        if not config_path.exists():
            logger.error(f"Config file not found at {config_path}")
            return {}
        with open(config_path, 'r', encoding='utf-8') as file:
            config = json.load(file)
        return config


    # ========== LSP Server Management ========= 
    def add_server(self, language: str):
        """Add a new LSP server to the list."""
        logger.debug(f"Adding LSP server for : {language}")
        server_config = self.config["languages"].get(language).get("lsp_server")
        if not server_config:
            logger.error(f"No LSP server configuration found for language: {language}")
            return
        logger.debug(f"Server configuration: {server_config.get('command', 'No command specified')}")
        self.servers[language] = LSPClient(server_config, use_docker=self.use_docker)

    async def _start_server(self, language: str):
        """Start the LSP server for the specified language."""
        logger.debug(f"Starting LSP server for language: {language}")
        server = self.servers.get(language)
        
        if not server:
            logger.error(f"No LSP server found for language: {language}")
            return
        
        if not server.is_running:
            await server.start_server(self.project.root)
            if not server.is_running:
                logger.error(f"Failed to start LSP server for {language}. Look into the logs for more details. Try -d for debug mode.")
                self.servers.pop(language, None)
        else:
            logger.info(f"LSP server for {language} is already running.")
 
    async def _extract_symbols(self, file: FileModel):
        """Query symbols from the LSP server."""
        logger.debug(f"Querying symbols for file: {file.path}")

        symbols_result = None
        server = self._select_server(file.language)
        if not server:
            logger.error(f"No LSP server found for language: {file.language}")
            return []
        abs_path = str(Path(self.project.root) / file.path)
        lsp_path = self.get_lsp_path(file)
        
        if lsp_path not in self.opened_files:
            if await server.did_open_file(abs_path):
                self.opened_files.add(lsp_path)
                logger.debug(f"File {lsp_path} opened successfully in LSP server.")
            else:
                logger.error(f"Failed to open file {lsp_path} in LSP server.")
                return []
        symbols_result = await server.get_document_symbols(lsp_path, symbol_kind_list=self.config.get("symbol_kind", []))
        return symbols_result

    async def _find_references(self, symbol: SymbolModel):
        """Find references for a specific symbol in the project."""
        # Logic to find references goes here
        references_result = None
        server = self._select_server(symbol.file_object.language)
        if not server:
            logger.error(f"No LSP server found for language: {symbol.file_object.language}")
            return []
        lsp_path = self.get_lsp_path(symbol.file_object)
        if not lsp_path:
            logger.error(f"File path for symbol {symbol.name} is not valid: {symbol.file_object.path}")
            return []
        references_result = await server.get_references(file_path=lsp_path,
                                                       line=symbol.selectionRange.start.line,
                                                       character=symbol.selectionRange.start.character,
                                                       include_declaration=False)
        return references_result

    async def _is_definition(self, symbol: SymbolModel, server: LSPClient) -> bool:
        """Check if a symbol is a definition."""
        logger.debug(f"Checking if symbol is a definition: {symbol}")
        # Logic to check if symbol is a definition goes here
        definition_result = None
        if not server:
            logger.error(f"No LSP server found for language: {symbol.file_object.language}")
            return False

        lsp_path = self.get_lsp_path(symbol.file_object)
        definition_result = await server.get_definition(file_path=lsp_path,
                                                        line=symbol.selectionRange.start.line,
                                                        character=symbol.selectionRange.start.character)  
    
        if definition_result is None:
            logger.warning(f"No definition found for symbol: {symbol.name}")
            return False

        if isinstance(definition_result, dict) and 'range' in definition_result:
            def_range = json_to_range(definition_result['range'])
            if symbol.selectionRange and def_range == symbol.selectionRange:
                logger.debug(f"Symbol {symbol.name} is a definition.")
                return True
            
        if isinstance(definition_result, list) and len(definition_result) > 0:
            for def_item in definition_result:
                if isinstance(def_item, dict) and 'range' in def_item:
                    def_range = json_to_range(def_item['range'])
                    if symbol.selectionRange and def_range == symbol.selectionRange:
                        logger.debug(f"Symbol {symbol.name} is a definition.")
                        return True

        logger.debug(f"Symbol {symbol.name} is not a definition. @ {symbol.selectionRange} difference: {definition_result}")
        return False

    # ========== Extraction methods =========

    async def extract_and_filter_symbols(self, files: Optional[List[FileModel]] = None):
        """Extract symbols from the project using LSP and filter them by only keeping the definitions."""
        logger.info("Starting LSP symbols extraction")
        for file in files:
            try:
                symbols = await self._extract_symbols(file)
                self._process_lsp_symbols(symbols, file)
                for model_symbol in list(file.symbols):
                    server = self._select_server(model_symbol.file_object.language)
                    if not await self._is_definition(model_symbol, server=server):
                        file.remove_symbol(model_symbol)
                        logger.debug(f"Removed definition symbol: {model_symbol.name} from {file.path} @ {model_symbol.selectionRange}")
                logger.info(f"Extracted {len(file.symbols)} symbols from {file.path}")
            except Exception as e:
                logger.error(f"Error extracting symbols from {file.path}: {e}")
        logger.info("LSP symbol extraction completed")

    async def extract_references(self, files: Optional[List[FileModel]] = None):
        logger.info("🔗 Starting LSP reference extraction")
        if files is None:
            files = self.project.get_all_files()
        total_symbols = sum(len(file.symbols) for file in files)
        processed = 0
        spinner = itertools.cycle(["( ●    )", "(  ●   )", "(   ●  )", "(    ● )", "(     ●)", "(    ● )", "(   ●  )", "(  ●   )", "( ●    )", "(●     )"])
        start_time = time.time()
        for file in files:
            for symbol in file.symbols:
                try:
                    if not symbol.selectionRange:
                        logger.warning(f"Symbol {symbol.name} in {file.path} has no selection range, skipping reference extraction.")
                        continue
                    references = await self._find_references(symbol)
                    if references:
                        self._match_reference_to_symbol(references, symbol)
                        logger.debug(f"Found {len(references)} references for symbol: {symbol.name} in {file.path}")
                except Exception as e:
                    logger.error(f"Error finding references for symbol {symbol.name} in {file.path}: {e}")
                    continue
                processed += 1
                # Print spinner and progress
                elapsed = int(time.time() - start_time)
                sys.stdout.write(
                    f"\rExtracting references {next(spinner)} | {processed}/{total_symbols} symbols | Elapsed: {elapsed // 60:02d}:{elapsed % 60:02d}"
                )
                sys.stdout.flush()
                await asyncio.sleep(0.05)
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
        logger.info("🔗 LSP reference extraction completed")

    # ========== Process returned elements =========

    def _process_lsp_symbols(self, symbols_result: Any, file_model: FileModel) -> List[SymbolModel]:
        symbols = []

        def process_symbol(lsp_symbol, parent_symbol: SymbolModel = None):
            if not isinstance(lsp_symbol, dict):
                logger.warning(f"Skipping non-dict LSP symbol: {lsp_symbol}")
                return
            symbol = self._convert_lsp_symbol_to_model(lsp_symbol, file_model, parent_symbol)
            if symbol:
                symbols.append(symbol)
                if parent_symbol:
                    parent_symbol.child_symbols.append(symbol)
                children = lsp_symbol.get('children', [])
                for child_lsp_symbol in children:
                    process_symbol(child_lsp_symbol, symbol)
            return symbol

        if isinstance(symbols_result, tuple) and len(symbols_result) > 0:
            actual_symbols = symbols_result[0] if isinstance(symbols_result[0], list) else []
        elif isinstance(symbols_result, list):
            actual_symbols = symbols_result
        else:
            logger.warning(f"Unexpected symbols result type: {type(symbols_result)}. Expected list or tuple.")
            actual_symbols = []

        for lsp_symbol in actual_symbols:
            process_symbol(lsp_symbol)

        return symbols

    def _convert_lsp_symbol_to_model(self, lsp_symbol: Dict[str, Any], file_model: FileModel,
                                   parent_symbol: SymbolModel = None) -> Optional[SymbolModel]:
        """Convert LSP symbol to SymbolModel."""
        try:
            try:
                name = lsp_symbol.get('name', 'unknown')
            except Exception as e:
                logger.error(f"Error retrieving name from LSP symbol: {e}")
                name = 'unknown'
            try:
                kind = lsp_symbol.get('kind', 0)
                kind = self.config.get('kind_to_types', {}).get(str(kind), kind)  # Map LSP kind to internal kind
            except Exception as e:
                logger.error(f"Error retrieving kind from LSP symbol: {e}")
                kind = 0

            # Get position information
            try:
                symbol_range = SymbolModel.create_range(lsp_symbol.get('range', {}))
                symbol_selection_range = SymbolModel.create_range(lsp_symbol.get('selectionRange', {}))
            except Exception as e:
                logger.error(f"Error creating range from LSP symbol: {e}")

            # Get detail information
            documentation = lsp_symbol.get('documentation', '')
            if documentation == '':
                documentation = lsp_symbol.get('detail', '')
            
            symbol = SymbolModel(
                name=name,
                symbol_kind=kind,
                file_object=file_model,
                range=symbol_range,
                selectionRange=symbol_selection_range,
                parent_symbol=parent_symbol,
                docstring=documentation,
            )
            file_model.add_symbol(symbol)
            return symbol
            
        except Exception as e:
            logger.error(f"Error converting LSP symbol: {e}")
            return None

    def _match_reference_to_symbol(self, references: List[Dict[str, Any]], symbol: SymbolModel):
        """Match a reference to a symbol in the list."""
        if not isinstance(references, list):
            logger.warning(f"Expected references to be a list, got {type(references)}")
            return
        symb_cpt = 0
        for ref in references:
            fp = ref.get("uri")
            fp = self._uri_to_path(fp) if fp else None
            # Map /workspace/ or C:/workspace/ to real project root
            if fp:
                norm_root = normalize_path(self.project.root)
                fp_norm = fp.replace("\\", "/")
                if fp_norm.lower().startswith("c:/workspace/"):
                    rel_path = fp_norm[len("c:/workspace/"):]
                    fp = os.path.normpath(os.path.join(norm_root, rel_path))
                elif fp_norm.startswith("/workspace/"):
                    rel_path = fp_norm[len("/workspace/"):]
                    fp = os.path.normpath(os.path.join(norm_root, rel_path))
                else:
                    fp = normalize_path(fp)
                # Optionally, make relative to project root for matching
                try:
                    fp_rel = str(Path(fp).relative_to(norm_root))
                except ValueError:
                    fp_rel = fp
            else:
                fp_rel = None

            temp_file = self.project.find_from_file_path(fp_rel)
            if not temp_file:
                logger.warning(f"❌ No file found for reference: {fp_rel}")
                continue
            logger.debug(f"Found reference in file: {fp_rel} for symbol: {symbol.name}")

            if temp_file:
                range = json_to_range(ref.get("range", {}))
                temp_symbol = temp_file.find_symbol_within_range(range)
                if temp_symbol:
                    if not (temp_symbol in symbol.child_symbols):
                        symbol.linking_call_symbols(temp_symbol)
                        symb_cpt += 1

        logger.debug(f"✅ Found {symb_cpt} references for {symbol.name} in {len(references)} references")

    # ========== utils =========

    def _uri_to_path(self, uri: str) -> Optional[str]:
        """Convert a URI to a normalized absolute file path."""
        if not uri:
            return None
        if uri.startswith('file://'):
            path = uri[7:]
            path = urllib.parse.unquote(path)
            # Remove leading slash on Windows if present (file:///C:/...)
            if os.name == "nt" and path.startswith("/") and len(path) > 3 and path[2] == ":":
                path = path[1:]
            return os.path.normpath(path)
        return os.path.normpath(urllib.parse.unquote(uri))
    
    def _select_server(self, language: str) -> Optional[LSPClient]:
        """Select the appropriate LSP server based on the language."""
        server = self.servers.get(language)
        if server is None or server == {}:
            logger.warning(f"No LSP server found for language: {language}")
        return server

    def get_lsp_path(self, file: FileModel) -> str:
        """Return the correct file path for LSP requests (Docker or standalone)."""
        abs_path = str(Path(self.project.root) / file.path)
        if self.use_docker:
            return "/workspace/" + file.path.replace("\\", "/")
        else:
            # Only join if not already absolute
            if os.path.isabs(file.path):
                return file.path
            return abs_path
        
    # ========== Extraction =========

    async def run_extraction(self):
        """Run the full extraction process."""
        logger.info("Starting LSP extraction process")
        for language in self.project.get_all_languages():
            self.add_server(language)

        if not self.servers:
            logger.error("No LSP servers available. Cannot proceed with extraction.")
            return

        for language, language_files in self.sort_files_by_language().items():
            await self._start_server(language)

            await self.extract_and_filter_symbols(language_files)
            # await self.extract_references(language_files)
            server = self._select_server(language)
            if server and server.is_running:
                logger.info(f"🛑 Shutting down LSP server for {language}")
                await server.shutdown()

            
        logger.info(f"LSP extraction completed retrieved {len(self.project.get_all_symbols())} symbols")

    def sort_files_by_language(self) -> Dict[str, List[FileModel]]:
        """Sort files by their language."""
        sorted_files = {}
        for file in self.project.get_all_files():
            if file.language not in sorted_files:
                sorted_files[file.language] = []
            sorted_files[file.language].append(file)
        return sorted_files
        