"""Pure LSP-based extraction without Tree-sitter dependency."""

import logging
import json
import asyncio
import subprocess
import sys
import os
import traceback
from typing import Dict, List, Optional, Any
from pathlib import Path
from .lsp_client.universal_lsp_client import LSPClient

from .models import *

logger = logging.getLogger(__name__)


class LSPExtractor:
    """Extract symbols using LSP servers."""
    
    def __init__(self, config_path: str = None, auto_install: bool = None, 
                 enable_semantic: bool = True, enable_folding: bool = True, 
                 enable_enhancement: bool = True):
        self.config_path = config_path or Path(__file__).parent / "extract_config/lsp_config.json"
        self.config = self._load_config()
        
        # Use config default if not specified   
        self.auto_install = auto_install if auto_install is not None else self.config.get("default_settings", {}).get("auto_install", True)
        self.timeout = self.config.get("default_settings", {}).get("timeout", 300)
        self.enhancement_settings = self.config.get("default_settings", {}).get("symbol_enhancement", {})
        
        # Features enablement
        self.enable_semantic = enable_semantic
        self.enable_folding = enable_folding
        self.enable_enhancement = enable_enhancement


        self.project: Optional[ProjectModel] = None
        self.language_servers: Dict[str, LSPClient] = {}

        # Future implementation:
        # self.file_hashes: Dict[str, str] = {}  # For incremental updates
        # self.last_analysis: Dict[str, float] = {}  # Track last analysis time per file
        # self.last_file_log_analysis: Dict[str, str] = {}  # Track last file log analysis by it's commit log
        self.wanted_kinds = self._load_wanted_kinds()

    def _load_wanted_kinds(self) -> List[int]:
        """Load WantedKind configuration once."""
        try:
            # Assuming the config is in the same directory structure
            config_path = Path(__file__).parent / "extract_config/LSP_kind.json"
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                wanted_kinds = config.get("WantedKind", [])
                logger.debug(f"Loaded WantedKind filter: {wanted_kinds}")
                return wanted_kinds
        except Exception as e:
            logger.warning(f"Error loading WantedKind config: {e}")
            return [5, 6, 7, 8, 9, 10, 11, 12, 14, 23, 24, 25] # Default to common symbol kinds if config fails
        
    def _load_config(self) -> Dict[str, Any]:
        """Load LSP-only configuration from JSON file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Loaded LSP configuration from {self.config_path}")
                return config
        except Exception as e:
            logger.error(f"Error loading LSP config from {self.config_path}: {e}")
            logger.error("Please ensure the configuration file exists and is valid JSON")
            sys.exit(1)

    async def extract_project(self, project_root: str) -> ProjectModel:
        """Extract project using LSP approach."""
        project_root = str(Path(project_root).resolve())
        project_name = Path(project_root).name
        
        if not Path(project_root).exists() or not Path(project_root).is_dir():
            logger.error(f"Project root '{project_root}' must be a valid directory.")
            return None

        self.project = ProjectModel(name=project_name, root=project_root)
        
        # Phase 1: Discover files and languages
        detected_languages = self._discover_files_and_languages(project_root)
        
        if not detected_languages:
            logger.warning("No supported files found.")
            return self.project

        logger.info(f"Detected languages: {detected_languages}")
        
        # Phase 2: Check and install LSP servers
        available_languages = self._check_and_install_lsp_servers(detected_languages)
        
        if not available_languages:
            logger.warning("No LSP servers available. Returning project with files but no symbols.")
            return self.project

        # Phase 3: Initialize LSP servers and extract symbols   
        for lang in available_languages:
            logger.info(f"Initializing LSP server for {lang}")
            lsp_config = self.config["languages"][lang]["lsp_server"]
            lsp = LSPClient(lsp_config)
            self.language_servers[lang] = lsp  
            # Start the LSP server
            logger.info(f"Starting LSP server for {lang} with command: {lsp_config['command']}")

            await asyncio.wait_for(
                lsp.start_server(workspace_root=project_root), 
                timeout=30.0  # 30 second timeout
            )
            logger.info(f"Started LSP server for {lang}: {lsp_config['command']}")
        # Phase 4: Extract symbols from each file

        for file in self.project.files:
            lsp = self.language_servers.get(file.language)
            await self._extract_file_information(file, lsp, file.language)
        


        await self.cleanup()  # Ensure LSP servers are cleaned up
        return self.project
    
    def _discover_files_and_languages(self, project_root: str) -> List[str]:
        """Discover files and determine supported languages."""
        detected_languages = set()
        
        for file_path in Path(project_root).rglob('*'):
            if file_path.is_file() and not self.project.ignore_file(str(file_path)):
                file_extension = file_path.suffix.lower()
                
                # Find language for this extension
                for lang, config in self.config["languages"].items():
                    if file_extension in config["extensions"]:
                        detected_languages.add(lang)
                        
                        # Read file content
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            
                            file_model = FileModel(
                                path=str(file_path), 
                                language=lang,
                                project_root=project_root
                            )
                            self.project.files.append(file_model)
                            
                            if lang not in self.project.langs:
                                self.project.langs.append(lang)
                                
                            logger.debug(f"Added file: {file_path} (language: {lang})")
                            
                        except Exception as e:
                            logger.warning(f"Error reading {file_path}: {e}")
                        break
    
        return list(detected_languages)

    # ================ LSP SERVER ================
    # Might refacto this to LSPUtils or similar utility class in the future

    def _check_and_install_lsp_servers(self, languages: List[str]) -> List[str]:
        """Check LSP server availability and offer installation."""
        available_languages = []
        
        for lang in languages:
            if self._check_lsp_server_available(lang):
                available_languages.append(lang)
            elif self.auto_install and self._offer_install_lsp_server(lang):
                if self._check_lsp_server_available(lang):
                    available_languages.append(lang)
                else:
                    logger.warning(f"Installation of {lang} LSP server failed")
            else:
                logger.warning(f"LSP server for {lang} not available, skipping")
        
        return available_languages

    def _check_lsp_server_available(self, language: str) -> bool:
        """Check if LSP server is available for a language."""
        if language not in self.config["languages"]:
            logger.warning(f"No configuration found for language: {language}")
            return False
            
        lsp_config = self.config['languages'][language]['lsp_server']
        check_cmd = lsp_config.get('check_command', [lsp_config['command'], '--version'])
        
        try:
            result = subprocess.run(check_cmd, capture_output=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _offer_install_lsp_server(self, language: str) -> bool:
        """Offer to install LSP server for a language."""
        if language not in self.config["languages"]:
            return False
            
        lsp_config = self.config["languages"][language]["lsp_server"]
        install_cmd = lsp_config["install_command"]
        description = lsp_config.get("description", f"{language} LSP server")
        
        print(f"\n🔧 {description} is not installed.")
        print(f"Installation command: {install_cmd}")
        
        if self.auto_install:
            response = input(f"Install {language} LSP server? (Y/n): ").strip().lower()
            if response in ['', 'y', 'yes']:
                return self._install_lsp_server(language)
        
        return False

    def _install_lsp_server(self, language: str) -> bool:
        """Install LSP server for a language."""
        lsp_config = self.config["languages"][language]["lsp_server"]
        install_cmd = lsp_config["install_command"]
        
        print(f"🔄 Installing {language} LSP server...")
        
        try:
            # Handle bash -c commands specifically
            if install_cmd.startswith("bash -c"):
                # Extract the bash command from the quotes
                import shlex
                cmd_parts = shlex.split(install_cmd)
                result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=self.timeout, shell=False)
            
            # Handle other commands
            elif install_cmd.startswith(("pip ", "npm ", "go ", "rustup ")):
                cmd_parts = install_cmd.split()
                result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=self.timeout)
            
            # Handle direct shell commands
            else:
                result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=self.timeout, shell=True)
            
            if result.returncode == 0:
                print(f"✅ {language} LSP server installed successfully")
                return True
            else:
                print(f"❌ Installation failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Installation error: {e}")
            return False

    # ================ FILE EXTRACTION ================

    async def _extract_file_information(self, file_model: FileModel, lsp: LSPClient, language: str) -> ProjectModel:
        """Extract symbols from a file using LSP document symbols."""
        try:
            logger.info(f"Extracting symbols from {file_model.path} ({language})")
            rel_path = file_model.get_relative_path()
            logger.info(f"Requesting symbols for: {rel_path}")
            
            await lsp.did_open_file(file_model.path, language)
            await asyncio.sleep(1)
            # ================ FOLDING RANGES ================
            # Get document folding ranges if enabled
            await self._extract_ranges(file_model, lsp, language)

            # ================ SYMBOLS EXTRACTION ================
            # Get document symbols from LSP
            await self._extract_file_symbols(file_model, lsp, language)
            
            await self._import_symbols_sorting(file_model, lsp)
            # ================ SEMANTIC TOKENS EXTRACTION ================
            # Get semantic tokens if enabled
            # if self.enable_semantic:
            #     semantic_tokens = await self._extract_semantic_tokens(file_model, lsp, language)
            #     self._enrich_symbols_with_semantic_tokens(file_model, semantic_tokens)
        
            # ================ Elements sorting and Symbols ehancements ================
            # Enhance symbols with detailed information
            # if self.enhancement_settings.get("get_hover", True):
            #     for symbol in symbols:
            #         await self._enhance_symbol_with_detailed_info(symbol, file_model, lsp, rel_path, language)
            # else:
            #     logger.warning(f"No symbols returned for {rel_path}")
                    
        except Exception as e:
            logger.error(f"Error extracting symbols from {file_model.path}: {e}")
            import traceback
            traceback.print_exc()

    # ================ ELEMENT EXTRACTION ================

    async def _extract_ranges(self, file_model: FileModel, lsp: LSPClient, language: str) -> None:
        """Extract FoldingRanges from a file."""
        try:
            rel_path = file_model.get_relative_path()
            logger.info(f"Requesting folding ranges for: {rel_path}")
            
            # Get folding ranges from LSP
            absolute_path = os.path.join(file_model.project_root, rel_path)
            folding_ranges = await lsp.get_folding_ranges(absolute_path)
            logger.info(f"LSP returned: {type(folding_ranges)} with data: {folding_ranges}")
            
            if folding_ranges:
                for folding_range in folding_ranges:
                    # Convert LSP folding range to our model
                    start = LSPPosition(folding_range['startLine'], folding_range['startCharacter'])
                    end = LSPPosition(folding_range['endLine'], folding_range['endCharacter'])
                    fold_range = LSPRange(start, end)
                    folding_range_model = FoldingRange(
                        range=fold_range,
                        kind=folding_range.get('kind', None)
                    )
                    file_model.folding_ranges.append(folding_range_model)
                logger.info(f"📄 Extracted {len(folding_ranges)} folding ranges from {file_model.path}")
            else:
                logger.warning(f"No folding ranges returned for {rel_path}")
                    
        except Exception as e:
            logger.error(f"Error extracting folding ranges from {file_model.path}: {e}")
            traceback.print_exc()

    async def _extract_file_symbols(self, file_model: FileModel, lsp: LSPClient, language: str) -> None:
        """Extract symbols from a file using LSP document symbols."""
        try:
            rel_path = file_model.get_relative_path()
            logger.info(f"Requesting symbols for: {rel_path}")

            absolute_path = os.path.join(file_model.project_root, rel_path)
            symbols_result = await lsp.get_document_symbols(absolute_path, self.wanted_kinds)
            logger.info(f"LSP returned: {type(symbols_result)} with data: {symbols_result}")
            
            if symbols_result:
                symbols = self._process_lsp_symbols(symbols_result, file_model, language)
                file_model.symbols = symbols
                logger.info(f"📄 Extracted {len(symbols)} symbols from {file_model.path}")
                    
        except Exception as e:
            logger.error(f"Error extracting symbols from {file_model.path}: {e}")
            import traceback
            traceback.print_exc()

    async def _extract_semantic_tokens(self, file_model: FileModel, lsp: LSPClient, language: str) -> List[Dict]:
        """Extract semantic tokens from a file using LSP."""
        try:
            rel_path = file_model.get_relative_path()
            logger.info(f"Requesting semantic tokens for: {rel_path}")
            
            # Get semantic tokens from LSP
            absolute_path = os.path.join(file_model.project_root, rel_path)
            semantic_tokens = await lsp.get_semantic_tokens_full(absolute_path)
            logger.info(f"LSP returned: {type(semantic_tokens)} with data: {semantic_tokens}")
            
            if semantic_tokens:
                decoded_tokens = self._decode_semantic_tokens(semantic_tokens)
                logger.info(f"📄 Extracted {len(decoded_tokens)} semantic tokens from {file_model.path}")
                return decoded_tokens                
            else:
                logger.warning(f"No semantic tokens returned for {rel_path}")
                    
        except Exception as e:
            logger.error(f"Error extracting semantic tokens from {file_model.path}: {e}")
            import traceback
            traceback.print_exc()

        return None  # Return None if no tokens extracted
    
    async def _extract_semantic_tokens_by_ranges(self, file_model: FileModel, lsp: LSPClient, range: LSPRange) -> List[Dict]:
        """Extract semantic tokens by ranges for large files."""
        try:
            rel_path = file_model.get_relative_path()
            logger.info(f"Requesting semantic tokens by range for: {rel_path}")
            
            # Get semantic tokens by range from LSP
            absolute_path = os.path.join(file_model.project_root, rel_path)
            semantic_tokens = await lsp.request_semantic_tokens_range(absolute_path, range.to_dict())
            logger.info(f"LSP returned: {type(semantic_tokens)} with data: {semantic_tokens}")
            
            if semantic_tokens:
                decoded_tokens = self._decode_semantic_tokens(semantic_tokens)
                logger.info(f"📄 Extracted {len(decoded_tokens)} semantic tokens by range from {file_model.path}")
                return decoded_tokens
            else:
                logger.warning(f"No semantic tokens returned for {rel_path} in range {range}")
                    
        except Exception as e:
            logger.error(f"Error extracting semantic tokens by range from {file_model.path}: {e}")
            import traceback
            traceback.print_exc()

        return None

    # ================  ELEMENT TREATMENT ================

    # Use the folding range to sort and process import symbols
    async def _import_symbols_sorting(self, file_model: FileModel, lsp: LSPClient) -> None:
        """Sort and process import symbols in a file."""
        if not file_model.folding_ranges or not file_model.symbols:
            return
        
        # Pre-filter import folding ranges
        import_ranges = [fr for fr in file_model.folding_ranges if fr.kind == 'import']
        if not import_ranges:
            return
        
        import_symbols = []
        
        # For each symbol, check if it's inside any import range
        for symbol in file_model.symbols:
            for import_range in import_ranges:
                if symbol.range.is_inside(import_range.range):
                    symbol.is_import = True
                    
                    # Batch LSP calls or make them optional
                    locationLink = None
                    if self.enhancement_settings.get("resolve_import_definitions", False):
                        try:
                            locationLink = await lsp.request_definition(
                                file_model.get_relative_path(), 
                                symbol.range.start.line, 
                                symbol.range.start.character
                            )
                        except Exception as e:
                            logger.debug(f"Failed to get definition for import {symbol.name}: {e}")
                    
                    import_model = ImportModel(
                        symbolModel=symbol,
                        definitionLocationLink=locationLink
                    )
                    import_symbols.append(import_model)
                    logger.debug(f"Found import symbol: {symbol.name}")
                    break  # Stop checking other ranges once we find a match
        
        file_model.imports = import_symbols

    # Manage the processing of symbols from LSP to objects
    def _process_lsp_symbols(self, symbols_result: Any, file_model: FileModel, language: str) -> List[SymbolModel]:
        """Process LSP symbols result into SymbolModel objects."""
        symbols = []
        # Handle multilspy tuple/list structure
        if isinstance(symbols_result, tuple) and len(symbols_result) > 0:
            actual_symbols = symbols_result[0] if isinstance(symbols_result[0], list) else []
        elif isinstance(symbols_result, list):
            actual_symbols = symbols_result
        else:
            logger.warning(f"Unexpected symbols result type: {type(symbols_result)}. Expected list or tuple.")
            actual_symbols = []


        for lsp_symbol in actual_symbols:
            if not isinstance(lsp_symbol, dict):
                logger.warning(f"Skipping non-dict LSP symbol: {lsp_symbol}")
                continue
            
            symbol = self._convert_lsp_symbol_to_model(lsp_symbol, file_model, language)
            if symbol:
                symbols.append(symbol)
                
                # Process children (methods in classes, etc.)
                children = lsp_symbol.get('children', [])
                for child_lsp_symbol in children:
                    child_symbol = self._convert_lsp_symbol_to_model(child_lsp_symbol, file_model, language, symbol)
                    if child_symbol:
                        symbols.append(child_symbol)
                        symbol.child_symbols.append(child_symbol)
        print(f"Extracted {len(symbols)} symbols from {file_model.path} ({language})")
        return symbols

    # Convert a single LSP symbol to SymbolModel
    def _convert_lsp_symbol_to_model(self, lsp_symbol: Dict, file_model: FileModel, language: str,
                                   parent_symbol: SymbolModel = None) -> Optional[SymbolModel]:
        """Convert LSP symbol to SymbolModel."""
        try:
            name = lsp_symbol.get('name', 'unknown')
            kind = lsp_symbol.get('kind', 0)
            
            # Get position information
            lsp_range = json_to_range(lsp_symbol.get('range', {}))
            selection_range = json_to_range(lsp_symbol.get('selectionRange', {}))
            
            # Get detail information
            detail = lsp_symbol.get('detail', '')
            
            symbol = SymbolModel(
                name=name,
                symbol_kind=self._map_lsp_kind_to_type(kind),
                file_object=file_model,
                range=lsp_range,
                selectionRange=selection_range,
                parent_symbol=parent_symbol,
                signature=detail if detail else {}
            )            
            return symbol
            
        except Exception as e:
            logger.error(f"Error converting LSP symbol: {e}")
            return None

    def _map_lsp_kind_to_type(self, kind: int) -> str:
        """Map LSP SymbolKind to our symbol types."""
        # LSP SymbolKind mapping
        # read LSP_kind from LSP_kind.json
        try:
            with open(Path(__file__).parent / "extract_config/LSP_kind.json", 'r', encoding='utf-8') as f:
                kind_mapping = json.load(f)
                return kind_mapping["SymbolKind"].get(str(kind), 'unknown')
        except Exception as e:
            logger.error(f"Error loading LSP kind mapping: {e}")
            return 'unknown'

    # =============== SYMBOL ENHANCEMENT ================

    def _decode_semantic_tokens(self, semantic_tokens: Dict) -> List[Dict]:
        """Decode LSP semantic tokens into readable format."""
        if not semantic_tokens or 'data' not in semantic_tokens:
            return []
        
        tokens_data = semantic_tokens['data']
        legend = semantic_tokens.get('legend', {})
        token_types = legend.get('tokenTypes', [])
        token_modifiers = legend.get('tokenModifiers', [])
        
        decoded = []
        current_line = 0
        current_char = 0
        
        # Semantic tokens are encoded in a delta format
        for i in range(0, len(tokens_data), 5):
            if i + 4 >= len(tokens_data):
                break
                
            delta_line = tokens_data[i]
            delta_start = tokens_data[i + 1]
            length = tokens_data[i + 2]
            token_type_idx = tokens_data[i + 3]
            token_modifiers_bitset = tokens_data[i + 4]
            
            # Calculate absolute position
            if delta_line > 0:
                current_line += delta_line
                current_char = delta_start
            else:
                current_char += delta_start
            
            # Decode type and modifiers
            token_type = token_types[token_type_idx] if token_type_idx < len(token_types) else 'unknown'
            
            modifiers = []
            for mod_idx in range(len(token_modifiers)):
                if token_modifiers_bitset & (1 << mod_idx):
                    modifiers.append(token_modifiers[mod_idx])
            
            decoded.append({
                "line": current_line,
                "character": current_char,
                "length": length,
                "type": token_type,
                "modifiers": modifiers,
                "text_range": {
                    "start": {"line": current_line, "character": current_char},
                    "end": {"line": current_line, "character": current_char + length}
                }
            })
        
        return decoded
    
    def _enrich_symbols_with_semantic_tokens(self, file_model: FileModel, semantic_tokens: List[Dict]) -> None:
        """Enrich symbols with semantic tokens."""
        if not semantic_tokens or not file_model.symbols:
            return
        
        # Create a mapping of positions to tokens
        token_map = {}
        for token in semantic_tokens:
            start = (token['text_range']['start']['line'], token['text_range']['start']['character'])
            end = (token['text_range']['end']['line'], token['text_range']['end']['character'])
            token_map[(start, end)] = token
        
        # Enrich each symbol with semantic tokens
        for symbol in file_model.symbols:
            if symbol.range and symbol.range.start and symbol.range.end:
                start = (symbol.range.start.line, symbol.range.start.character)
                end = (symbol.range.end.line, symbol.range.end.character)
                
                # Find matching tokens
                for (token_start, token_end), token in token_map.items():
                    if start >= token_start and end <= token_end:
                        symbol.semantic_info['semantic_tokens'] = token
                        break

    # ================ ASYNC EXTRACTION (MAIN PART) ================

    async def cleanup(self):
        """Clean up resources."""
        # LSP servers are automatically cleaned up with async context managers
        logger.info("Cleaning up LSP server")
        for lang, lsp in self.language_servers.items():
            try:
                await lsp.shutdown()
                logger.info(f"✅ LSP server for {lang} shut down successfully")
            except Exception as e:
                logger.error(f"Error shutting down LSP server for {lang}: {e}")
        logger.info("LSP extraction completed")

    def get_project_stats(self) -> Dict[str, int]:
        """Get project statistics."""
        if not self.project:
            return {}
        
        nb_symbols = 0
        for file_model in self.project.files:
            for symbol in file_model.symbols:
                if symbol.symbol_kind in ['function', 'method', 'constructor', 'class']:
                    print(f"Symbol: {symbol.name} ({symbol.symbol_kind}) in {file_model.path}")
            nb_symbols += len(file_model.symbols) 
        
        print(f"Total symbols extracted: {nb_symbols}")
        print(f"Total files analyzed: {len(self.project.files)}")

    def match_semantic_tokens_to_symbols(self, file_model: FileModel, semantic_tokens: List[Dict]) -> None:
        """Match semantic tokens to symbols in the file model."""
        if not semantic_tokens or not file_model.symbols:
            logger.debug(f"No semantic tokens or symbols to match in {file_model.path}")
            return 
        
        for token in semantic_tokens:
            if 'text_range' not in token:
                logger.debug(f"Skipping token without text_range: {token}")
                continue
            
            token_start = LSPPosition(token['text_range']['start']['line'], token['text_range']['start']['character'])
            token_end = LSPPosition(token['text_range']['end']['line'], token['text_range']['end']['character'])
            token_range = LSPRange(token_start, token_end)
            
            for symbol in file_model.symbols:
                if not symbol.selectionRange:
                    logger.debug(f"Skipping symbol without selectionRange: {symbol.name}")
                    continue
                
                if symbol.selectionRange.is_inside(token_range) and symbol.name == token.get('name'):
                    symbol.semantic_info = {}
                    symbol.semantic_info['type'] = token.get('type', [])
                    symbol.semantic_info['modifiers'] = token.get('modifiers', [])
                    logger.debug(f"Matched token {token} to symbol {symbol.name}")
                    symbol.should_document() 
                    break
        
        logger.info(f"Matched {len(semantic_tokens)} semantic tokens to {len(file_model.symbols)} symbols in {file_model.path}")


    # 🆕 NOUVELLE MÉTHODE: Obtenir les statistiques enrichies
    def get_enhanced_project_stats(self) -> Dict[str, Any]:
        """Get enhanced project statistics with semantic analysis."""
        if not self.project:
            return {}
        
        stats = {
            "files_total": len(self.project.files),
            "languages": list(set(f.language for f in self.project.files)),
            "symbols_by_type": {},
            "constructors_found": 0,
            "external_symbols": 0,
            "documentable_symbols": 0,
            "semantic_tokens_total": 0
        }
        
        for file_model in self.project.files:
            # Compter les semantic tokens
            if hasattr(file_model, 'semantic_tokens'):
                stats["semantic_tokens_total"] += len(file_model.semantic_tokens)
            
            for symbol in file_model.symbols:
                # Compter par type
                symbol_type = symbol.symbol_kind
                if symbol_type not in stats["symbols_by_type"]:
                    stats["symbols_by_type"][symbol_type] = 0
                stats["symbols_by_type"][symbol_type] += 1
                
                # Analyser les infos sémantiques
                if hasattr(symbol, 'semantic_info'):
                    if symbol.semantic_info.get('is_constructor', False):
                        stats["constructors_found"] += 1
                    
                    if symbol.semantic_info.get('is_external_library', False):
                        stats["external_symbols"] += 1
                    
                    if symbol.semantic_info.get('should_document', False):
                        stats["documentable_symbols"] += 1
        
        return stats
    



    def _process_hover_info(self, symbol: SymbolModel, hover_result: Dict, language: str):
        """Process hover information to extract clean signature."""
        try:
            contents = hover_result.get('contents', {})
            
            if isinstance(contents, dict):
                hover_text = contents.get('value', str(contents))
            elif isinstance(contents, str):
                hover_text = contents
            elif isinstance(contents, list) and contents:
                # Some LSP servers return a list of content blocks
                hover_text = '\n'.join(str(item.get('value', item)) if isinstance(item, dict) else str(item) 
                                      for item in contents)
            else:
                hover_text = str(contents)
            
            symbol.signature['hover_text'] = hover_text
                    
        except Exception as e:
            logger.debug(f"Error processing hover info: {e}")   

    async def _extract_semantic_tokens_full(self, file_model: FileModel, lsp: LSPClient, 
                                       rel_path: str, language: str):
        """Extract semantic tokens from file using full document request."""
        try:
            logger.info(f"Requesting semantic tokens for: {rel_path}")
            
            # Tenter d'abord l'extraction complète du fichier
            semantic_result = await lsp.request_semantic_tokens_full(rel_path)
            
            if semantic_result:
                # Décoder les tokens
                decoded_tokens = self._decode_semantic_tokens(semantic_result)
                
                # Stocker dans le modèle (vous devrez ajouter ce champ à FileModel)
                if not hasattr(file_model, 'semantic_tokens'):
                    file_model.semantic_tokens = []
                file_model.semantic_tokens = decoded_tokens
                
                logger.info(f"✅ Extracted {len(decoded_tokens)} semantic tokens from {rel_path}")
                
                # Analyser les constructeurs
                constructors = self._find_constructors_in_semantic_tokens(decoded_tokens)
                if constructors:
                    logger.info(f"🔧 Found {len(constructors)} constructors via semantic tokens")
                
                # Enrichir les symboles avec les semantic tokens
                self._enrich_symbols_with_semantic_tokens(file_model, decoded_tokens)
                
            else:
                logger.debug(f"No semantic tokens returned for {rel_path}")
                
        except Exception as e:
            logger.debug(f"Semantic tokens extraction failed for {rel_path}: {e}")
            # Fallback: essayer l'extraction par ranges pour gros fichiers
            if hasattr(file_model, 'content') and file_model.content:
                line_count = len(file_model.content.split('\n'))
                if line_count > 1000:  # Gros fichier
                    await self._extract_semantic_tokens_by_ranges(file_model, lsp, rel_path, language)

    async def _extract_semantic_tokens_by_ranges(self, file_model: FileModel, lsp: LSPClient, 
                                           rel_path: str, language: str):
        """Fallback: Extract semantic tokens by ranges for large files."""
        try:
            if not hasattr(file_model, 'content') or not file_model.content:
                return
                
            lines = file_model.content.split('\n')
            total_lines = len(lines)
            chunk_size = 500
            all_tokens = []
            
            logger.info(f"Large file detected ({total_lines} lines), extracting by chunks...")
            
            for start_line in range(0, total_lines, chunk_size):
                end_line = min(start_line + chunk_size, total_lines - 1)
                
                try:
                    # Créer un range pour ce chunk
                    range_dict = {
                        "start": {"line": start_line, "character": 0},
                        "end": {"line": end_line, "character": len(lines[end_line]) if end_line < len(lines) else 0}
                    }
                    
                    semantic_result = await lsp.request_semantic_tokens_range(rel_path, range_dict)
                    
                    if semantic_result:
                        chunk_tokens = self._decode_semantic_tokens(semantic_result)
                        all_tokens.extend(chunk_tokens)
                        
                except Exception as chunk_e:
                    logger.debug(f"Chunk {start_line}-{end_line} failed: {chunk_e}")
                    continue
            
            if all_tokens:
                if not hasattr(file_model, 'semantic_tokens'):
                    file_model.semantic_tokens = []
                file_model.semantic_tokens = all_tokens
                logger.info(f"✅ Extracted {len(all_tokens)} semantic tokens by ranges from {rel_path}")
                
                # Enrichir les symboles
                self._enrich_symbols_with_semantic_tokens(file_model, all_tokens)
            
        except Exception as e:
            logger.debug(f"Range-based semantic tokens extraction failed: {e}")
