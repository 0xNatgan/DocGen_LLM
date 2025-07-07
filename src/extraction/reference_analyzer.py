"""Reference and definition analyzer using LSP servers."""

import asyncio
import json
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from .lsp_client.universal_lsp_client import LSPClient
from .models import FileModel, SymbolModel, FolderModel, LSPPosition, LSPRange, SymbolReference

logger = logging.getLogger(__name__)



class ReferenceAnalyzer:
    """Analyzes symbol references and definitions using LSP."""
    
    def __init__(self):
        self.lsp_configs = self._load_lsp_configs()
        self.active_clients: Dict[str, LSPClient] = {}
    
    def _load_lsp_configs(self) -> Dict[str, Dict]:
        """Load LSP-only configuration from JSON file."""
        try:
            with open(Path(__file__).parent / "extract_config/lsp_configs.json", 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Loaded LSP configuration from {Path(__file__).parent / 'extract_config/lsp_configs.json'}")
                return config.get("languages", {})
        except Exception as e:
            logger.error(f"Error loading LSP config from {Path(__file__).parent / 'extract_config/lsp_configs.json'}: {e}")
            logger.error("Please ensure the configuration file exists and is valid JSON")
            sys.exit(1)

    async def analyze_project_references(self, root_folder: FolderModel):
        """Analyze references for all symbols in the project."""
        # Start LSP servers for each language
        languages = root_folder.langs
        clients_started = await self._start_lsp_servers(languages, str(root_folder.root))
        
        if not clients_started:
            logger.warning("No LSP servers could be started")
            return

        try:
            # Collect all symbols from all files
            all_symbols = self._collect_all_symbols(root_folder)
            logger.info(f"Analyzing references for {len(all_symbols)} symbols")
            

            symb_cpt = 0
            
            for symbol in all_symbols:
                # For other symbols, find their references
                references = await self._find_symbol_references(symbol)
                for ref in references:
                    fp = ref.get("uri")

                    fp = self._uri_to_path(fp) if fp else None
                    temp_file = root_folder.find_from_file_path(fp)
                    logging.info(f"Found reference in file: {fp} for symbol: {symbol.name}")


                    if temp_file:
                        logging.info(f"✅ Temp file found: {temp_file.path}")
                        posStart = LSPPosition(**ref.get("range", {}).get("start", {}))
                        posEnd = LSPPosition(**ref.get("range", {}).get("end", {}))
                        range = LSPRange(start=posStart, end=posEnd)
                        temp_symbol = temp_file.find_symbol_within_range(range)
                        if temp_symbol:
                            symbol.linking_call_symbols(temp_symbol)
                            symb_cpt += 1

            logger.info(f"✅ Found {symb_cpt} references for {len(all_symbols)} symbols")

        except Exception as e:
            logger.error(f"❌ Error analyzing project references: {e}")
            logger.error("Please check if the LSP servers are correctly configured and running")
            return

        finally:
            # Cleanup LSP servers
            await self._shutdown_lsp_servers()
    
    async def _start_lsp_servers(self, languages: List[str], workspace_root: str) -> bool:
        """Start LSP servers for required languages."""
        success_count = 0
        
        for language in languages:
            if language in self.lsp_configs:
                config = self.lsp_configs[language].get("lsp_server", {})
                client = LSPClient(config)
                
                if await client.start_server(workspace_root):
                    self.active_clients[language] = client
                    success_count += 1
                    logger.info(f"✅ Started LSP server for {language}")
                else:
                    logger.warning(f"❌ Failed to start LSP server for {language}")
        
        return success_count > 0
    
    def _collect_all_symbols(self, folder: FolderModel) -> List[SymbolModel]:
        """Collect all symbols from all files in the project."""
        symbols = []
        
        def collect_from_folder(f: FolderModel):
            for file_model in f.files:
                symbols.extend(file_model.symbols)
            
            for subfolder in f.subfolders:
                collect_from_folder(subfolder)
        
        collect_from_folder(folder)
        return symbols
    
    async def _find_symbol_references(self, symbol: SymbolModel) -> List[SymbolReference]:
        """Find all references to a symbol using LSP."""
        
        # Get the appropriate LSP client
        file_path = symbol.file_object.path
        language = symbol.file_object.language
        client = self.active_clients.get(language)
        
        if not client:
            return []
        
        try:
            # Open the file with LSP
            await client.did_open_file(str(file_path), language)
            
            # Find references at the symbol's position
            references_data = await client.get_references(
                str(file_path),
                symbol.selectionRange.start.line,
                symbol.selectionRange.start.character
            )
            print("==========================================")
            print(references_data)
            print("==========================================")


            if not references_data:
                return []
            
            return references_data
        except Exception as e:
            logger.error(f"Error finding references for {symbol.name}: {e}")
            return []
    
    def _uri_to_path(self, uri: str) -> str:
        """Convert file URI to local path."""
        if uri.startswith("file://"):
            return uri[7:]  # Remove 'file://' prefix
        return uri
    
    async def _shutdown_lsp_servers(self):
        """Shutdown all active LSP servers."""
        for language, client in self.active_clients.items():
            try:
                await client.shutdown()
                logger.info(f"✅ Shutdown LSP server for {language}")
            except Exception as e:
                logger.error(f"Error shutting down {language} LSP server: {e}")
        
        self.active_clients.clear()