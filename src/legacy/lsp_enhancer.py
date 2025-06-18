"""LSP-based enhancement for symbols discovered by Tree-sitter."""

import logging
import json
import re
import asyncio
from typing import Dict, List, Optional, Any
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from pathlib import Path

from ..models import SymbolModel, FileModel, ProjectModel

logger = logging.getLogger(__name__)


class LSPEnhancer:
    """Enhance Tree-sitter discovered symbols with LSP information."""
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or Path(__file__).parent / "extract_config/languages_config.json"
        self.config = self._load_config()
        self.language_servers: Dict[str, LanguageServer] = {}
        self.logger = MultilspyLogger()
        self.project: Optional[ProjectModel] = None  # Store project reference
    
    def _load_config(self) -> Dict[str, Any]:
        """Load language configuration including LSP settings."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading language config: {e}")
            return {"languages": {}}
    
    def get_supported_languages(self) -> List[str]:
        """Get list of languages with LSP support enabled."""
        supported = []
        for lang, config in self.config.get("languages", {}).items():
            if lang == "default_config":
                continue
            lsp_config = config.get("lsp_config", {})
            if lsp_config.get("enabled", False):
                supported.append(lang)
        return supported
    
    def initialize_for_project(self, project: ProjectModel) -> None:
        """Initialize LSP servers and store project reference for symbol lookup."""
        self.project = project
        supported_langs = [lang for lang in project.langs if self._is_lsp_supported(lang)]
        logger.info(f"Initializing LSP servers for supported languages: {supported_langs}")
        
        # Build symbol indexes for fast lookup
        self._build_symbol_indexes()
        
        # Run async initialization
        asyncio.run(self._async_initialize_for_project(supported_langs, project.root))
    
    def _build_symbol_indexes(self):
        """Build symbol indexes in the project for fast position-based lookup."""
        if not self.project:
            return
            
        logger.info("Building symbol indexes for LSP resolution...")
        for file_model in self.project.files:
            for symbol in file_model.symbols:
                self.project.index_symbol(symbol)
        
        logger.info(f"Indexed {len(self.project._symbol_by_position)} symbols by position")
    
    async def _async_initialize_for_project(self, supported_langs: List[str], workspace_root: str) -> None:
        """Async initialization of LSP servers."""
        for lang in supported_langs:
            try:
                await self._initialize_language_server(lang, workspace_root)
            except Exception as e:
                logger.warning(f"Failed to initialize LSP for {lang}: {e}")
    
    def _is_lsp_supported(self, language: str) -> bool:
        """Check if LSP is supported and enabled for a language."""
        lang_config = self.config.get("languages", {}).get(language, {})
        lsp_config = lang_config.get("lsp_config", {})
        return lsp_config.get("enabled", False)
    
    async def _initialize_language_server(self, language: str, workspace_root: str) -> None:
        """Initialize a language server for a specific language using multilspy approach."""
        lang_config = self.config["languages"][language]
        lsp_config = lang_config["lsp_config"]
        
        try:
            # Create a MultilspyConfig instance for the language
            config = MultilspyConfig.from_dict({"code_language": language})
            
            lsp = LanguageServer.create(
                config=config,
                logger=self.logger,
                repository_root_path=workspace_root
            )
            
            # Set the LSP server's configuration
            logger.info(f"Starting {language} language server...")
            
            self.language_servers[language] = lsp
            
            logger.info(f"Prepared LSP server for {language}")
            
        except Exception as e:
            logger.error(f"Failed to prepare LSP server for {language}: {e}")
            install_cmd = lsp_config.get('install_command', 'Unknown installation')
            logger.info(f"To install {language} LSP server: {install_cmd}")
    
    def enhance_symbols(self, file_model: FileModel) -> None:
        """Enhance symbols in a file with LSP information."""
        lang = file_model.language
        if lang not in self.language_servers:
            logger.debug(f"No LSP server available for {lang}")
            return
        
        # Run async enhancement
        asyncio.run(self._async_enhance_symbols(file_model))
    
    async def _async_enhance_symbols(self, file_model: FileModel) -> None:
        """Async enhance symbols in a file with LSP information."""
        lang = file_model.language
        lsp = self.language_servers[lang]
        
        try:
            # Use the server within its proper context
            async with lsp.start_server():
                # Get relative path for LSP
                rel_path = file_model.get_relative_path()
                
                # Enhance each symbol with LSP data
                for symbol in file_model.symbols:
                    await self._enhance_symbol_with_lsp(symbol, file_model, lsp, lang, rel_path)
                
        except Exception as e:
            logger.error(f"Error enhancing symbols for {file_model.path}: {e}")
    
    async def _enhance_symbol_with_lsp(self, symbol: SymbolModel, file_model: FileModel, 
                                     lsp: LanguageServer, language: str, rel_path: str) -> None:
        """Enhance a single symbol with LSP information and resolve references."""
        try:
            # Get position for the symbol name
            symbol_position = self._get_symbol_name_position(symbol, file_model.content, language)
            
            if symbol_position:
                line = symbol_position['line']
                character = symbol_position['character']
                
                # Get hover information
                hover_info = await self._get_hover_info(lsp, rel_path, line, character, language)
                if hover_info:
                    symbol.signature.update(hover_info)
                    symbol.lsp_signature = hover_info.get('signature_from_hover')
                
                # Get references and resolve them to actual symbols
                references = await self._get_references(lsp, rel_path, line, character)
                if references:
                    self._resolve_and_link_references(symbol, references, file_model.path)
                        
        except Exception as e:
            logger.debug(f"Error enhancing symbol {symbol.name}: {e}")
    
    def _resolve_and_link_references(self, source_symbol: SymbolModel, 
                                   lsp_references: List[Dict], source_file: str) -> None:
        """Resolve LSP references to actual SymbolModel objects and create links."""
        if not self.project:
            return
            
        resolved_count = 0
        
        for ref in lsp_references:
            try:
                # Extract file path and position from LSP reference
                ref_uri = ref.get('uri', '')
                ref_range = ref.get('range', {})
                ref_start = ref_range.get('start', {})
                ref_line = ref_start.get('line', -1) + 1  # Convert to 1-based
                
                # Convert URI to file path
                ref_file_path = self._uri_to_file_path(ref_uri)
                
                # Skip self-references (definition)
                if ref_file_path == source_file and abs(ref_line - source_symbol.line_start) <= 1:
                    continue
                
                # Find the symbol at this position
                target_symbol = self.project.find_symbol_at_position(ref_file_path, ref_line)
                
                if target_symbol and target_symbol != source_symbol:
                    # Create bidirectional reference
                    source_symbol.add_reference_to(target_symbol)
                    resolved_count += 1
                    logger.debug(f"Linked {source_symbol.name} -> {target_symbol.name}")
                
            except Exception as e:
                logger.debug(f"Error resolving reference: {e}")
        
        if resolved_count > 0:
            source_symbol.references_count = resolved_count
            logger.debug(f"Resolved {resolved_count} references for {source_symbol.name}")
    
    def _uri_to_file_path(self, uri: str) -> str:
        """Convert LSP URI to file path."""
        if uri.startswith('file://'):
            return uri[7:]  # Remove 'file://' prefix
        return uri
    
    def get_installation_instructions(self) -> Dict[str, str]:
        """Get LSP server installation instructions for all supported languages."""
        instructions = {}
        for lang, config in self.config.get("languages", {}).items():
            if lang == "default_config":
                continue
            lsp_config = config.get("lsp_config", {})
            if lsp_config.get("enabled", False):
                instructions[lang] = lsp_config.get("install_command", "No installation info available")
        return instructions
    
    def cleanup(self) -> None:
        """Clean up LSP servers."""
        # Run async cleanup
        asyncio.run(self._async_cleanup())
    
    async def _async_cleanup(self) -> None:
        """Async cleanup of LSP servers."""
        for lang, lsp in self.language_servers.items():
            try:
                await lsp.shutdown()
                logger.debug(f"Shut down LSP server for {lang}")
            except Exception as e:
                logger.warning(f"Error shutting down LSP server for {lang}: {e}")
        
        self.language_servers.clear()