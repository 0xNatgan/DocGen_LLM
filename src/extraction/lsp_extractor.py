import json
from typing import Any, Dict, List, Optional
from ..logging.logging import get_logger
from .models import FolderModel, SymbolModel, FileModel, json_to_range
from .lsp_client.abstract_client import BaseLSPClient
from .lsp_client.docker_lsp_client import DockerLSPClient
from .lsp_client.standalone_lsp_client import LSPClient
from pathlib import Path

logger = get_logger(__name__)

class LSP_Extractor:
    def __init__(self, project: FolderModel, useDocker: bool = True):
        self.project = project
        self.useDocker = useDocker
        self.config = self._retrieve_config()
        self.servers: Dict[str, BaseLSPClient] = {}
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
        if self.useDocker:
            self.servers[language] = DockerLSPClient(server_config)
        else:
            self.servers[language] = LSPClient(server_config)

    async def _start_server(self, language: str):
        """Start the LSP server for the specified language."""
        logger.debug(f"Starting LSP server for language: {language}")
        server = self.servers.get(language)
        
        if not server:
            logger.error(f"No LSP server found for language: {language}")
            return
        
        if not server.is_running:
            if await server.start_server(self.project.root):
                logger.info(f"LSP server for {language} started successfully.")
            else:
                logger.error(f"Failed to start LSP server for {language}. Look into the logs for more details.")
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

    async def _is_definition(self, symbol: SymbolModel, server: BaseLSPClient) -> bool:
        """Check if a symbol is a definition."""
        logger.debug(f"Checking if symbol is a definition: {symbol}")
        # Logic to check if symbol is a definition goes here
        definition_result = None
        if not server:
            logger.error(f"No LSP server found for language: {symbol.file.language}")
            return False

        lsp_path = self.get_lsp_path(symbol.file_object)
        definition_result = await server.get_definition(file_path=lsp_path,
                                                        line=symbol.selectionRange.start.line,
                                                        character=symbol.selectionRange.start.character)  
    
        if definition_result is None:
            logger.warning(f"No definition found for symbol: {symbol.name}")
            return False

        if isinstance(definition_result, dict) and 'selectionRange' in definition_result:
            def_range = json_to_range(definition_result['selectionRange'])
            if symbol.selectionRange and def_range == symbol.selectionRange:
                logger.debug(f"Symbol {symbol.name} is a definition.")
                return True
            
        if isinstance(definition_result, list) and len(definition_result) > 0:
            for def_item in definition_result:
                if isinstance(def_item, dict) and 'selectionRange' in def_item:
                    def_range = json_to_range(def_item['selectionRange'])
                    if symbol.selectionRange and def_range == symbol.selectionRange:
                        logger.debug(f"Symbol {symbol.name} is a definition.")
                        return True
        
        logger.debug(f"Symbol {symbol.name} is not a definition.")
        return False                    

    # ========== Extraction methods =========

    async def extract_and_filter_symbols(self):
        """Extract symbols from the project using LSP and filter them by only keeping the definitions."""
        logger.info("Starting LSP symbols extraction")
        for file in self.project.get_all_files():
            try:
                symbols = await self._extract_symbols(file)
                self._process_lsp_symbols(symbols, file)
                for model_symbol in file.symbols:
                    server = self._select_server(model_symbol.file_object.language)
                    if not await self._is_definition(model_symbol, server=server):
                        # file.remove_symbol(model_symbol)
                        logger.debug(f"Removed non-definition symbol: {model_symbol.name} from {file.path} @ {model_symbol.selectionRange}")
                logger.info(f"Extracted {len(file.symbols)} symbols from {file.path}")
            except Exception as e:
                logger.error(f"Error extracting symbols from {file.path}: {e}")
        logger.info("LSP symbol extraction completed")

    async def extract_references(self):
        logger.info("Starting LSP reference extraction")
        # Reference extraction logic goes here
        for file in self.project.get_all_files():
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
        logger.info("LSP reference extraction completed")

    # ========== Process returned elements =========

    def _process_lsp_symbols(self, symbols_result: Any, file_model: FileModel) -> List[SymbolModel]:
        symbols = []

        def process_symbol(lsp_symbol, parent_symbol: SymbolModel = None):
            if not isinstance(lsp_symbol, dict):
                logger.warning(f"Skipping non-dict LSP symbol: {lsp_symbol}")
                return
            symbol = self._convert_lsp_symbol_to_model(lsp_symbol, file_model, file_model.language, parent_symbol)
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
        file_model.symbols = symbols

        return symbols

    def _convert_lsp_symbol_to_model(self, lsp_symbol: Dict[str, Any], file_model: FileModel, language: str,
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
            if self.useDocker and fp:
                fp = fp.replace("/workspace/", "")
            if fp and Path(fp).is_absolute() and hasattr(self.project, "root"):
                try:
                    fp = str(Path(fp).relative_to(self.project.root))
                except ValueError:
                    pass  # If not under root, keep as is
            temp_file = self.project.find_from_file_path(fp)
            if not temp_file:
                logger.warning(f"❌ No file found for reference: {fp}")
                continue
            logger.debug(f"Found reference in file: {fp} for symbol: {symbol.name}")


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
        """Convert a URI to a file path."""
        if not uri:
            return None
        if uri.startswith('file://'):
            return uri[7:]
        return uri
    
    def _select_server(self, language: str) -> Optional[BaseLSPClient]:
        """Select the appropriate LSP server based on the language."""
        server = self.servers.get(language)
        if server is None or server == {}:
            logger.warning(f"No LSP server found for language: {language}")
        return server

    def get_lsp_path(self, file: FileModel) -> str:
        """Return the correct file path for LSP requests (Docker or standalone)."""
        abs_path = str(Path(self.project.root) / file.path)
        if self.useDocker:
            return "/workspace/" + file.path.replace("\\", "/")
        else:
            return abs_path
    # ========== Extraction =========

    async def run_extraction(self):
        """Run the full extraction process."""
        logger.info("Starting LSP extraction process")
        for language in self.project.get_all_languages():
            self.add_server(language)
            await self._start_server(language)

        await self.extract_and_filter_symbols()
        await self.extract_references()
        for server in self.servers.values():
            await server.shutdown()
        logger.info("All LSP servers shut down successfully")
        logger.info("LSP extraction process completed")

    # ========== SQLite Export =========
    def export_to_sqlite(self, db_path: str):
        """Export all symbols and references to a SQLite database."""
        import sqlite3
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        # Create tables
        c.execute('''CREATE TABLE IF NOT EXISTS symbols (
            symbol_id INTEGER PRIMARY KEY,
            name TEXT,
            kind INTEGER,
            file_path TEXT,
            start_line INTEGER,
            start_char INTEGER,
            end_line INTEGER,
            end_char INTEGER,
            docstring TEXT,
            source_code TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol_id INTEGER,
            ref_file_path TEXT,
            ref_start_line INTEGER,
            ref_start_char INTEGER,
            ref_end_line INTEGER,
            ref_end_char INTEGER,
            FOREIGN KEY(symbol_id) REFERENCES symbols(symbol_id)
        )''')
        # Insert symbols
        for file in self.project.get_all_files():
            try:
                with open(str(Path(self.project.root) / file.path), 'r', encoding='utf-8', errors='ignore') as f:
                    source_code = f.read()
            except Exception:
                source_code = ''
            for symbol in file.symbols:
                symbol_id = id(symbol)
                c.execute('''INSERT OR REPLACE INTO symbols (symbol_id, name, kind, file_path, start_line, start_char, end_line, end_char, docstring, source_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                    symbol_id,
                    symbol.name,
                    symbol.symbol_kind,
                    file.path,
                    getattr(symbol.selectionRange, 'start', None) and symbol.selectionRange.start.line,
                    getattr(symbol.selectionRange, 'start', None) and symbol.selectionRange.start.character,
                    getattr(symbol.selectionRange, 'end', None) and symbol.selectionRange.end.line,
                    getattr(symbol.selectionRange, 'end', None) and symbol.selectionRange.end.character,
                    symbol.docstring if symbol.docstring else '',
                    source_code
                ))
        # Insert references
        for file in self.project.get_all_files():
            for symbol in file.symbols:
                symbol_id = id(symbol)
                for ref_symbol in getattr(symbol, 'child_symbols', []):
                    ref_file = getattr(ref_symbol, 'file_object', None)
                    ref_range = getattr(ref_symbol, 'selectionRange', None)
                    c.execute('''INSERT INTO references (symbol_id, ref_file_path, ref_start_line, ref_start_char, ref_end_line, ref_end_char) VALUES (?, ?, ?, ?, ?, ?)''', (
                        symbol_id,
                        ref_file.path if ref_file else '',
                        getattr(ref_range, 'start', None) and ref_range.start.line,
                        getattr(ref_range, 'start', None) and ref_range.start.character,
                        getattr(ref_range, 'end', None) and ref_range.end.line,
                        getattr(ref_range, 'end', None) and ref_range.end.character
                    ))
        conn.commit()
        conn.close()
        logger.info(f"Exported symbols and references to SQLite database at {db_path}")