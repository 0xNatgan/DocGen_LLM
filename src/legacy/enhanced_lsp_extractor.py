import json
import asyncio
import subprocess
import logging
import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from pathlib import Path

from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

from .enhanced_models import (
    EnhancedProjectModel, EnhancedFileModel, EnhancedSymbolModel,
    LSPPosition, LSPRange, SemanticToken, FoldingRange, ImportInfo,
    EnhancementInfo, SymbolKind, DocumentationPriority
)

logger = logging.getLogger(__name__)

class EnhancedLSPExtractor:
    """Enhanced LSP extractor with support for complete and incremental analysis."""
    
    def __init__(self, config_path: str = None, auto_install: bool = None, 
                 enable_semantic: bool = True, enable_folding: bool = True, 
                 enable_enhancement: bool = True):
        
        # Configuration
        self.config_path = config_path or Path(__file__).parent.parent / "config/lsp_config.json"
        self.config = self._load_config()
        self.timeout = self.config.get("default_settings", {}).get("timeout", 300)
        self.auto_install = auto_install if auto_install is not None else self.config.get("default_settings", {}).get("auto_install", True)
        
        # Features enablement
        self.enable_semantic = enable_semantic
        self.enable_folding = enable_folding
        self.enable_enhancement = enable_enhancement
        
        # LSP setup
        self.logger = MultilspyLogger()
        
        # Project state
        self.project: Optional[EnhancedProjectModel] = None
        self.active_lsp_servers: Dict[str, LanguageServer] = {}
        
        # Cache for incremental updates
        self.file_hashes: Dict[str, str] = {}  # file_path -> content_hash
        self.last_analysis: Dict[str, datetime] = {}  # file_path -> timestamp
    
    def _load_config(self) -> Dict[str, Any]:
        """Load LSP configuration."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Loaded LSP configuration from {self.config_path}")
                return config
        except Exception as e:
            logger.error(f"Error loading LSP config from {self.config_path}: {e}")
            raise
    
    # ================ COMPLETE PROJECT EXTRACTION ================
    
    async def extract_project_complete(self, project_root: str, 
                                     languages: List[str] = None) -> EnhancedProjectModel:
        """Complete project extraction with all LSP features."""
        
        start_time = datetime.now()
        project_root = str(Path(project_root).resolve())
        project_name = Path(project_root).name
        
        if not Path(project_root).exists() or not Path(project_root).is_dir():
            raise ValueError(f"Project root '{project_root}' must be a valid directory.")
        
        logger.info(f"🚀 Starting complete LSP extraction for project: {project_name}")
        
        # Initialize project
        self.project = EnhancedProjectModel(
            name=project_name,
            root=project_root,
            analysis_timestamp=start_time.isoformat()
        )
        
        try:
            # Phase 1: Discover files and languages
            logger.info("📁 Discovering files and languages...")
            discovered = await self._discover_files_and_languages(project_root, languages)
            self.project.languages = discovered["languages"]
            
            if not discovered["languages"]:
                logger.warning("No supported files found")
                return self.project
            
            logger.info(f"Found languages: {discovered['languages']}")
            
            # Phase 2: Setup LSP servers
            logger.info("🔧 Setting up LSP servers...")
            available_languages = await self._setup_lsp_servers(discovered["languages"])
            
            if not available_languages:
                logger.warning("No LSP servers available")
                return self.project
            
            logger.info(f"Available LSP servers: {available_languages}")
            
            # Phase 3: Extract symbols for each language
            for language in available_languages:
                logger.info(f"🔍 Extracting symbols for {language}...")
                
                language_files = discovered["files_by_language"].get(language, [])
                await self._extract_language_complete(language, language_files, project_root)
            
            # Phase 4: Build cross-references and dependency graph
            logger.info("🔗 Building cross-references...")
            await self._build_cross_references()
            
            # Calculate final timing
            end_time = datetime.now()
            self.project.total_analysis_time = (end_time - start_time).total_seconds()
            
            logger.info(f"✅ Complete extraction finished in {self.project.total_analysis_time:.2f}s")
            logger.info(f"   📊 Stats: {len(self.project.files)} files, {len(self.project.get_all_symbols())} symbols")
            
        except Exception as e:
            logger.error(f"❌ Complete extraction failed: {e}")
            raise
        
        finally:
            # Cleanup LSP servers
            await self._cleanup_lsp_servers()
        
        return self.project
    
    async def _extract_language_complete(self, language: str, language_files: List[Dict], 
                                       project_root: str):
        """Extract all files for a specific language."""
        
        config = MultilspyConfig.from_dict({"code_language": language})
        lsp = LanguageServer.create(
            config=config,
            logger=self.logger,
            repository_root_path=project_root
        )
        
        async with lsp.start_server():
            logger.info(f"✅ {language} LSP server started")
            self.project.lsp_servers_used[language] = lsp.__class__.__name__
            
            for file_info in language_files:
                try:
                    file_model = await self._extract_file_complete(file_info, lsp, language)
                    self.project.add_file(file_model)
                    
                    # Update cache
                    self.file_hashes[file_model.path] = file_model.content_hash
                    self.last_analysis[file_model.path] = datetime.now()
                    
                    logger.debug(f"✅ Extracted {file_model.path} ({len(file_model.symbols)} symbols)")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to extract {file_info['path']}: {e}")
    
    async def _extract_file_complete(self, file_info: Dict, lsp: LanguageServer, 
                                   language: str) -> EnhancedFileModel:
        """Complete extraction of a single file."""
        
        file_path = file_info["path"]
        
        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Cannot read file {file_path}: {e}")
            content = ""
        
        # Create file model
        file_model = EnhancedFileModel(
            path=file_path,
            language=language,
            content=content,
            content_hash=hashlib.md5(content.encode()).hexdigest(),
            size_bytes=len(content.encode()),
            line_count=len(content.split('\n')),
            analysis_timestamp=datetime.now().isoformat(),
            lsp_server_used=lsp.__class__.__name__,
            enhancement_applied=self.enable_enhancement
        )
        
        rel_path = file_model.get_relative_path()
        
        try:
            # Extract symbols
            await self._extract_symbols_from_file(file_model, lsp, rel_path)
            
            # Extract semantic tokens
            if self.enable_semantic:
                await self._extract_semantic_tokens_from_file(file_model, lsp, rel_path)
            
            # Extract folding ranges
            if self.enable_folding:
                await self._extract_folding_ranges_from_file(file_model, lsp, rel_path)
            
            # Extract imports
            await self._extract_imports_from_file(file_model, content)
            
            # Apply enhancements
            if self.enable_enhancement:
                await self._apply_enhancements_to_file(file_model, lsp, rel_path)
            
            # Post-process: link semantic tokens to symbols, calculate priorities
            self._post_process_file(file_model)
            
        except Exception as e:
            logger.error(f"Error during file extraction {file_path}: {e}")
        
        return file_model
    
    # ================ INCREMENTAL EXTRACTION ================
    
    async def extract_file_incremental(self, file_path: str, 
                                     target_symbols: List[str] = None) -> Optional[EnhancedFileModel]:
        """Incremental extraction of a single file or specific symbols."""
        
        file_path = str(Path(file_path).resolve())
        
        if not self.project:
            logger.error("No project loaded. Use extract_project_complete first.")
            return None
        
        logger.info(f"🔄 Incremental extraction for: {file_path}")
        
        # Check if file needs update
        if not await self._file_needs_update(file_path):
            logger.info(f"⏭️  File {file_path} is up to date")
            return self._get_existing_file_model(file_path)
        
        # Determine language
        language = self._detect_file_language(file_path)
        if not language:
            logger.warning(f"Cannot determine language for {file_path}")
            return None
        
        # Setup LSP server if needed
        if language not in self.active_lsp_servers:
            await self._setup_single_lsp_server(language)
        
        if language not in self.active_lsp_servers:
            logger.error(f"LSP server for {language} not available")
            return None
        
        lsp = self.active_lsp_servers[language]
        
        try:
            # Create file info
            file_info = {"path": file_path}
            
            # Extract complete file or specific symbols
            if target_symbols:
                file_model = await self._extract_symbols_incremental(
                    file_info, lsp, language, target_symbols
                )
            else:
                file_model = await self._extract_file_complete(file_info, lsp, language)
            
            # Update project
            self._update_project_with_file(file_model)
            
            # Update cache
            self.file_hashes[file_model.path] = file_model.content_hash
            self.last_analysis[file_model.path] = datetime.now()
            
            logger.info(f"✅ Incremental extraction completed for {file_path}")
            return file_model
            
        except Exception as e:
            logger.error(f"❌ Incremental extraction failed for {file_path}: {e}")
            return None
    
    async def extract_symbol_incremental(self, file_path: str, symbol_name: str, 
                                       symbol_line: int = None) -> Optional[EnhancedSymbolModel]:
        """Extract or update a specific symbol."""
        
        file_path = str(Path(file_path).resolve())
        
        logger.info(f"🎯 Incremental symbol extraction: {symbol_name} in {file_path}")
        
        # Get or extract file
        file_model = await self.extract_file_incremental(file_path)
        if not file_model:
            return None
        
        # Find the symbol
        target_symbol = None
        for symbol in file_model.symbols:
            if symbol.name == symbol_name:
                if symbol_line is None or (symbol.range and symbol.range.contains_line(symbol_line)):
                    target_symbol = symbol
                    break
        
        if not target_symbol:
            logger.warning(f"Symbol {symbol_name} not found in {file_path}")
            return None
        
        # Re-enhance the symbol if needed
        if self.enable_enhancement:
            language = file_model.language
            if language in self.active_lsp_servers:
                lsp = self.active_lsp_servers[language]
                rel_path = file_model.get_relative_path()
                await self._enhance_symbol(target_symbol, lsp, rel_path)
        
        logger.info(f"✅ Symbol {symbol_name} updated")
        return target_symbol
    
    async def _extract_symbols_incremental(self, file_info: Dict, lsp: LanguageServer, 
                                         language: str, target_symbols: List[str]) -> EnhancedFileModel:
        """Extract only specific symbols from a file."""
        
        # First get complete file model
        file_model = await self._extract_file_complete(file_info, lsp, language)
        
        # Filter symbols if specific targets are requested
        if target_symbols:
            filtered_symbols = []
            for symbol in file_model.symbols:
                if symbol.name in target_symbols:
                    filtered_symbols.append(symbol)
                elif symbol.get_full_name() in target_symbols:
                    filtered_symbols.append(symbol)
            
            file_model.symbols = filtered_symbols
            logger.info(f"Filtered to {len(filtered_symbols)} target symbols")
        
        return file_model
    
    # ================ SYMBOL EXTRACTION ================
    
    async def _extract_symbols_from_file(self, file_model: EnhancedFileModel, 
                                       lsp: LanguageServer, rel_path: str):
        """Extract document symbols from file."""
        
        try:
            symbols_result = await lsp.request_document_symbols(rel_path)
            
            if symbols_result:
                # Process LSP symbols
                processed_symbols = self._process_lsp_symbols(symbols_result, file_model)
                
                # Add to file model
                
                for symbol in processed_symbols:
                    file_model.add_symbol(symbol)
                
                logger.debug(f"Extracted {len(processed_symbols)} symbols from {rel_path}")
            
        except Exception as e:
            logger.debug(f"Symbol extraction failed for {rel_path}: {e}")
    
    def _process_lsp_symbols(self, symbols_result: Any, file_model: EnhancedFileModel) -> List[EnhancedSymbolModel]:
        """Process LSP symbols result into EnhancedSymbolModel objects."""
        
        symbols = []
        
        # Handle multilspy response format
        if isinstance(symbols_result, tuple) and len(symbols_result) > 0:
            actual_symbols = symbols_result[0] if isinstance(symbols_result[0], list) else []
        elif isinstance(symbols_result, list):
            actual_symbols = symbols_result
        else:
            actual_symbols = []
        
        # Process each symbol
        for lsp_symbol in actual_symbols:
            if not isinstance(lsp_symbol, dict):
                continue
            
            symbol = self._create_symbol_from_lsp(lsp_symbol, file_model)
            if symbol:
                symbols.append(symbol)
                
                # Process children recursively
                children = lsp_symbol.get('children', [])
                child_symbols = self._process_child_symbols(children, file_model, symbol)
                symbols.extend(child_symbols)
        
        return symbols
    
    def _create_symbol_from_lsp(self, lsp_symbol: Dict, file_model: EnhancedFileModel, 
                              parent: EnhancedSymbolModel = None) -> Optional[EnhancedSymbolModel]:
        """Create EnhancedSymbolModel from LSP symbol data."""
        
        try:
            name = lsp_symbol.get('name', 'unknown')
            lsp_kind = lsp_symbol.get('kind', 1)
            
            # Create ranges
            lsp_range = None
            if 'range' in lsp_symbol:
                lsp_range = LSPRange.from_dict(lsp_symbol['range'])
            
            selection_range = None
            if 'selectionRange' in lsp_symbol:
                selection_range = LSPRange.from_dict(lsp_symbol['selectionRange'])
            
            # Map LSP kind to string
            symbol_kind = self._map_lsp_kind_to_string(lsp_kind)
            
            # Create symbol
            symbol = EnhancedSymbolModel(
                name=name,
                symbol_kind=symbol_kind,
                lsp_kind=SymbolKind(lsp_kind) if lsp_kind <= 26 else None,
                file_path=file_model.path,
                range=lsp_range,
                selection_range=selection_range,
                parent_symbol=parent
            )
            
            # Extract source code if range is available
            if lsp_range and file_model.content:
                symbol.source_code = self._extract_source_code(
                    file_model.content, lsp_range
                )
                
                # Extract existing docstring
                symbol.existing_docstring = self._extract_existing_docstring(
                    file_model.content, lsp_range, file_model.language
                )
            
            # Set documentation metadata
            symbol.documentation_priority = symbol.calculate_documentation_priority()
            symbol.suggested_template = symbol.suggest_documentation_template()
            
            return symbol
            
        except Exception as e:
            logger.debug(f"Error creating symbol from LSP data: {e}")
            return None
    
    def _process_child_symbols(self, children: List[Dict], file_model: EnhancedFileModel, 
                             parent: EnhancedSymbolModel) -> List[EnhancedSymbolModel]:
        """Process child symbols recursively."""
        
        child_symbols = []
        
        for child_lsp_symbol in children:
            child_symbol = self._create_symbol_from_lsp(child_lsp_symbol, file_model, parent)
            if child_symbol:
                parent.child_symbols.append(child_symbol)
                child_symbols.append(child_symbol)
                
                # Process grandchildren
                grandchildren = child_lsp_symbol.get('children', [])
                if grandchildren:
                    grandchild_symbols = self._process_child_symbols(grandchildren, file_model, child_symbol)
                    child_symbols.extend(grandchild_symbols)
        
        return child_symbols
    
    # ================ SEMANTIC TOKENS EXTRACTION ================
    
    async def _extract_semantic_tokens_from_file(self, file_model: EnhancedFileModel, 
                                               lsp: LanguageServer, rel_path: str):
        """Extract semantic tokens from file."""
        
        try:
            semantic_result = await lsp.request_semantic_tokens_full(rel_path)
            
            if semantic_result:
                decoded_tokens = self._decode_semantic_tokens(semantic_result)
                file_model.semantic_tokens = decoded_tokens
                
                logger.debug(f"Extracted {len(decoded_tokens)} semantic tokens from {rel_path}")
            
        except Exception as e:
            logger.debug(f"Semantic tokens extraction failed for {rel_path}: {e}")
    
    def _decode_semantic_tokens(self, semantic_tokens: Dict) -> List[SemanticToken]:
        """Decode LSP semantic tokens into SemanticToken objects."""
        
        if not semantic_tokens or 'data' not in semantic_tokens:
            return []
        
        tokens_data = semantic_tokens['data']
        legend = semantic_tokens.get('legend', {})
        token_types = legend.get('tokenTypes', [])
        token_modifiers = legend.get('tokenModifiers', [])
        
        decoded = []
        current_line = 0
        current_char = 0
        
        for i in range(0, len(tokens_data), 5):
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
            
            semantic_token = SemanticToken(
                line=current_line,
                character=current_char,
                length=length,
                token_type=token_type,
                modifiers=modifiers
            )
            
            decoded.append(semantic_token)
        
        return decoded
    
    # ================ FOLDING RANGES EXTRACTION ================
    
    async def _extract_folding_ranges_from_file(self, file_model: EnhancedFileModel, 
                                              lsp: LanguageServer, rel_path: str):
        """Extract folding ranges from file."""
        
        try:
            folding_result = await lsp.request_folding_ranges(rel_path)
            
            if folding_result:
                processed_ranges = self._process_folding_ranges(folding_result, file_model)
                file_model.folding_ranges = processed_ranges
                
                logger.debug(f"Extracted {len(processed_ranges)} folding ranges from {rel_path}")
            
        except Exception as e:
            logger.debug(f"Folding ranges extraction failed for {rel_path}: {e}")
    
    def _process_folding_ranges(self, folding_ranges: List[Dict], 
                              file_model: EnhancedFileModel) -> List[FoldingRange]:
        """Process LSP folding ranges into FoldingRange objects."""
        
        processed = []
        
        for fold_range in folding_ranges:
            start_line = fold_range.get("startLine", 0)
            end_line = fold_range.get("endLine", 0)
            kind = fold_range.get("kind", "region")
            
            # Analyze content to determine if it's an import block
            is_import_block = self._is_import_folding_range(
                start_line, end_line, file_model.content, file_model.language
            )
            
            # Determine if documentable
            is_documentable = kind in ["class", "function", "method"] or \
                            (kind == "region" and not is_import_block)
            
            # Find symbols in this range
            contains_symbols = []
            for symbol in file_model.symbols:
                if (symbol.range and 
                    symbol.range.start.line >= start_line and 
                    symbol.range.end.line <= end_line):
                    contains_symbols.append(symbol.name)
            
            folding_range = FoldingRange(
                start_line=start_line,
                end_line=end_line,
                kind=kind,
                collapsed_text=fold_range.get("collapsedText", ""),
                is_import_block=is_import_block,
                is_documentable=is_documentable,
                contains_symbols=contains_symbols
            )
            
            processed.append(folding_range)
        
        return processed
    
    def _is_import_folding_range(self, start_line: int, end_line: int, 
                               content: str, language: str) -> bool:
        """Determine if a folding range contains imports."""
        
        if not content:
            return False
        
        lines = content.split('\n')
        range_lines = lines[start_line:end_line + 1]
        
        if not range_lines:
            return False
        
        # Language-specific import patterns
        import_patterns = {
            "python": [r'^\s*from\s+', r'^\s*import\s+'],
            "javascript": [r'^\s*import\s+', r'^\s*const\s+.*=\s*require'],
            "typescript": [r'^\s*import\s+', r'^\s*const\s+.*=\s*require'],
            "java": [r'^\s*import\s+'],
            "rust": [r'^\s*use\s+']
        }
        
        patterns = import_patterns.get(language, [r'^\s*import\s+', r'^\s*from\s+'])
        
        import_count = 0
        non_empty_lines = [l for l in range_lines if l.strip()]
        
        for line in non_empty_lines:
            if any(re.match(pattern, line) for pattern in patterns):
                import_count += 1
        
        return len(non_empty_lines) > 0 and (import_count / len(non_empty_lines)) > 0.7
    
    # ================ IMPORTS EXTRACTION ================
    
    async def _extract_imports_from_file(self, file_model: EnhancedFileModel, content: str):
        """Extract import information from file content."""
        
        try:
            imports = self._parse_imports_from_content(content, file_model.language)
            file_model.imports = imports
            
            logger.debug(f"Extracted {len(imports)} imports from {file_model.path}")
            
        except Exception as e:
            logger.debug(f"Import extraction failed for {file_model.path}: {e}")
    
    def _parse_imports_from_content(self, content: str, language: str) -> List[ImportInfo]:
        """Parse imports from file content."""
        
        imports = []
        
        if language == "python":
            imports.extend(self._parse_python_imports(content))
        elif language in ["javascript", "typescript"]:
            imports.extend(self._parse_js_imports(content))
        elif language == "java":
            imports.extend(self._parse_java_imports(content))
        elif language == "rust":
            imports.extend(self._parse_rust_imports(content))
        
        return imports
    
    def _parse_python_imports(self, content: str) -> List[ImportInfo]:
        """Parse Python imports."""
        
        imports = []
        
        # Patterns for Python imports
        patterns = [
            (r'^from\s+([^\s]+)\s+import\s+(.+)$', "from_import"),
            (r'^import\s+([^\s#]+)(?:\s+as\s+([^\s#]+))?', "import")
        ]
        
        for line_num, line in enumerate(content.split('\n')):
            line = line.strip()
            
            for pattern, import_type in patterns:
                match = re.match(pattern, line)
                if match:
                    if import_type == "from_import":
                        module = match.group(1)
                        items_str = match.group(2)
                        items = [item.strip() for item in items_str.split(',')]
                        alias = None
                    else:  # regular import
                        module = match.group(1)
                        items = [module]
                        alias = match.group(2) if match.group(2) else None
                    
                    import_info = ImportInfo(
                        line=line_num + 1,
                        module=module,
                        items=items,
                        alias=alias,
                        is_local=self._is_local_import(module),
                        import_type=import_type,
                        raw_line=line
                    )
                    
                    imports.append(import_info)
                    break
        
        return imports
    
    def _parse_js_imports(self, content: str) -> List[ImportInfo]:
        """Parse JavaScript/TypeScript imports."""
        
        imports = []
        
        # Basic patterns for JS/TS imports
        patterns = [
            (r'^import\s+([^\'\"]+)\s+from\s+[\'\"](.*?)[\'\"]', "import"),
            (r'^const\s+([^=]+)=\s*require\([\'\"](.*?)[\'\"]', "require")
        ]
        
        for line_num, line in enumerate(content.split('\n')):
            line = line.strip()
            
            for pattern, import_type in patterns:
                match = re.match(pattern, line)
                if match:
                    items_str = match.group(1).strip()
                    module = match.group(2)
                    
                    # Parse items (simplified)
                    items = [item.strip() for item in items_str.split(',')]
                    
                    import_info = ImportInfo(
                        line=line_num + 1,
                        module=module,
                        items=items,
                        is_local=self._is_local_import(module),
                        import_type=import_type,
                        raw_line=line
                    )
                    
                    imports.append(import_info)
                    break
        
        return imports
    
    def _parse_java_imports(self, content: str) -> List[ImportInfo]:
        """Parse Java imports."""
        
        imports = []
        
        pattern = r'^import\s+(?:static\s+)?([^;]+);'
        
        for line_num, line in enumerate(content.split('\n')):
            line = line.strip()
            match = re.match(pattern, line)
            
            if match:
                module = match.group(1).strip()
                items = [module.split('.')[-1]]  # Get class name
                
                import_info = ImportInfo(
                    line=line_num + 1,
                    module=module,
                    items=items,
                    is_local=self._is_local_import(module),
                    import_type="import",
                    raw_line=line
                )
                
                imports.append(import_info)
        
        return imports
    
    def _parse_rust_imports(self, content: str) -> List[ImportInfo]:
        """Parse Rust use statements."""
        
        imports = []
        
        pattern = r'^use\s+([^;]+);'
        
        for line_num, line in enumerate(content.split('\n')):
            line = line.strip()
            match = re.match(pattern, line)
            
            if match:
                use_path = match.group(1).strip()
                
                # Parse use path (simplified)
                if '::' in use_path:
                    parts = use_path.split('::')
                    module = '::'.join(parts[:-1])
                    items = [parts[-1]]
                else:
                    module = use_path
                    items = [module]
                
                import_info = ImportInfo(
                    line=line_num + 1,
                    module=module,
                    items=items,
                    is_local=self._is_local_import(module),
                    import_type="use",
                    raw_line=line
                )
                
                imports.append(import_info)
        
        return imports
    
    def _is_local_import(self, module_name: str) -> bool:
        """Determine if an import is local to the project."""
        
        # Relative imports
        if module_name.startswith('.'):
            return True
        
        # Check against common external libraries
        external_patterns = [
            'std::', 'numpy', 'pandas', 'requests', 'flask', 'django',
            'react', 'lodash', 'express', 'axios',
            'java.', 'javax.', 'org.apache', 'com.google'
        ]
        
        for pattern in external_patterns:
            if module_name.startswith(pattern):
                return False
        
        # If we have a project, check if module exists locally
        if self.project:
            # Simple heuristic: check if any file contains this module
            for file_model in self.project.files:
                file_name = Path(file_model.path).stem
                if module_name.endswith(file_name) or file_name in module_name:
                    return True
        
        return False
    
    # ================ ENHANCEMENTS ================
    
    async def _apply_enhancements_to_file(self, file_model: EnhancedFileModel, 
                                        lsp: LanguageServer, rel_path: str):
        """Apply LSP enhancements (hover, definition, etc.) to all symbols in file."""
        
        for symbol in file_model.symbols:
            await self._enhance_symbol(symbol, lsp, rel_path)
    
    async def _enhance_symbol(self, symbol: EnhancedSymbolModel, 
                            lsp: LanguageServer, rel_path: str):
        """Enhance a single symbol with LSP information."""
        
        if not symbol.range:
            return
        
        line = symbol.range.start.line
        character = symbol.range.start.character
        
        enhancement = EnhancementInfo()
        
        try:
            # Hover information
            hover_result = await lsp.request_hover(rel_path, line, character)
            if hover_result:
                enhancement.hover_text = self._process_hover_info(hover_result)
            
            # Definition information
            definition_result = await lsp.request_definition(rel_path, line, character)
            if definition_result:
                enhancement.definition_location = str(definition_result)
            
            # Type definition
            type_definition = await lsp.request_type_definition(rel_path, line, character)
            if type_definition:
                enhancement.type_definition = str(type_definition)
            
            # References (limited to avoid performance issues)
            references_result = await lsp.request_references(rel_path, line, character)
            if references_result:
                enhancement.references = references_result[:10]  # Limit to 10
            
            symbol.enhancement_info = enhancement
            
        except Exception as e:
            logger.debug(f"Enhancement failed for {symbol.name}: {e}")
    
    def _process_hover_info(self, hover_result: Dict) -> str:
        """Process LSP hover information."""
        
        try:
            contents = hover_result.get('contents', {})
            
            if isinstance(contents, dict):
                return contents.get('value', str(contents))
            elif isinstance(contents, str):
                return contents
            elif isinstance(contents, list) and contents:
                return '\n'.join(
                    str(item.get('value', item)) if isinstance(item, dict) else str(item) 
                    for item in contents
                )
            else:
                return str(contents)
                
        except Exception as e:
            logger.debug(f"Error processing hover info: {e}")
            return ""
    
    # ================ POST-PROCESSING ================
    
    def _post_process_file(self, file_model: EnhancedFileModel):
        """Post-process file: link semantic tokens to symbols, etc."""
        
        # Link semantic tokens to symbols
        self._link_semantic_tokens_to_symbols(file_model)
        
        # Associate folding ranges with symbols
        self._associate_folding_ranges_with_symbols(file_model)
        
        # Update documentation priorities based on semantic info
        self._update_documentation_priorities(file_model)
    
    def _link_semantic_tokens_to_symbols(self, file_model: EnhancedFileModel):
        """Link semantic tokens to their corresponding symbols."""
        
        for symbol in file_model.symbols:
            if not symbol.range:
                continue
            
            symbol_line = symbol.range.start.line
            symbol_char = symbol.range.start.character
            
            # Find semantic tokens near this symbol
            for token in file_model.semantic_tokens:
                if (token.line == symbol_line and 
                    abs(token.character - symbol_char) <= 10):  # Tolerance
                    symbol.add_semantic_token(token)
    
    def _associate_folding_ranges_with_symbols(self, file_model: EnhancedFileModel):
        """Associate folding ranges with symbols."""
        
        for symbol in file_model.symbols:
            if not symbol.range:
                continue
            
            # Find folding range that contains this symbol
            for folding_range in file_model.folding_ranges:
                if (folding_range.start_line <= symbol.range.start.line and
                    folding_range.end_line >= symbol.range.end.line):
                    symbol.folding_range = folding_range
                    break
    
    def _update_documentation_priorities(self, file_model: EnhancedFileModel):
        """Update documentation priorities based on semantic information."""
        
        for symbol in file_model.symbols:
            # Recalculate priority with semantic info
            symbol.documentation_priority = symbol.calculate_documentation_priority()
            
            # Skip symbols in import blocks
            if (symbol.folding_range and symbol.folding_range.is_import_block):
                symbol.should_document = False
                symbol.documentation_priority = DocumentationPriority.SKIP
    
    # ================ CROSS-REFERENCES ================
    
    async def _build_cross_references(self):
        """Build cross-references and dependency graph for the project."""
        
        if not self.project:
            return
        
        logger.info("Building cross-references...")
        
        # Build symbol index
        for file_model in self.project.files:
            for symbol in file_model.symbols:
                if symbol.name not in self.project.symbol_index:
                    self.project.symbol_index[symbol.name] = []
                if file_model.path not in self.project.symbol_index[symbol.name]:
                    self.project.symbol_index[symbol.name].append(file_model.path)
        
        # Build dependency graph from imports
        for file_model in self.project.files:
            dependencies = []
            
            for import_info in file_model.imports:
                if import_info.is_local:
                    # Try to resolve local import to actual file
                    resolved_path = self._resolve_local_import(import_info.module, file_model.path)
                    if resolved_path:
                        dependencies.append(resolved_path)
                        import_info.resolved_path = resolved_path
            
            self.project.dependency_graph[file_model.path] = dependencies
    
    def _resolve_local_import(self, module_name: str, current_file: str) -> Optional[str]:
        """Resolve local import to actual file path."""
        
        if not self.project:
            return None
        
        current_dir = Path(current_file).parent
        project_root = Path(self.project.root)
        
        # Common resolution patterns
        possible_paths = []
        
        if module_name.startswith('.'):
            # Relative import
            relative_path = module_name.lstrip('.')
            possible_paths.append(current_dir / f"{relative_path}.py")
            possible_paths.append(current_dir / relative_path / "__init__.py")
        else:
            # Absolute import from project root
            module_path = module_name.replace('.', '/')
            possible_paths.append(project_root / f"{module_path}.py")
            possible_paths.append(project_root / module_path / "__init__.py")
            possible_paths.append(project_root / "src" / f"{module_path}.py")
            possible_paths.append(project_root / "src" / module_path / "__init__.py")
        
        # Check which paths exist in our project
        for path in possible_paths:
            str_path = str(path)
            for file_model in self.project.files:
                if file_model.path == str_path:
                    return str_path
        
        return None
    
    # ================ UTILITIES ================
    
    async def _file_needs_update(self, file_path: str) -> bool:
        """Check if a file needs to be re-analyzed."""
        
        if file_path not in self.file_hashes:
            return True
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                current_content = f.read()
            
            current_hash = hashlib.md5(current_content.encode()).hexdigest()
            return current_hash != self.file_hashes[file_path]
            
        except Exception as e:
            logger.debug(f"Error checking file {file_path}: {e}")
            return True
    
    def _get_existing_file_model(self, file_path: str) -> Optional[EnhancedFileModel]:
        """Get existing file model from project."""
        
        if not self.project:
            return None
        
        for file_model in self.project.files:
            if file_model.path == file_path:
                return file_model
        
        return None
    
    def _update_project_with_file(self, file_model: EnhancedFileModel):
        """Update project with new/updated file model."""
        
        if not self.project:
            return
        
        # Remove existing file model if present
        self.project.files = [f for f in self.project.files if f.path != file_model.path]
        
        # Add updated file model
        self.project.add_file(file_model)
    
    def _detect_file_language(self, file_path: str) -> Optional[str]:
        """Detect language for a file."""
        
        extension = Path(file_path).suffix.lower()
        
        for language, config in self.config["languages"].items():
            if extension in config["extensions"]:
                return language
        
        return None
    
    async def _setup_single_lsp_server(self, language: str):
        """Setup a single LSP server for incremental operations."""
        
        if not self._check_lsp_server_available(language):
            if self.auto_install:
                success = await self._install_lsp_server(language)
                if not success:
                    return
            else:
                return
        
        try:
            config = MultilspyConfig.from_dict({"code_language": language})
            lsp = LanguageServer.create(
                config=config,
                logger=self.logger,
                repository_root_path=self.project.root if self.project else "."
            )
            
            await lsp.start_server()
            self.active_lsp_servers[language] = lsp
            logger.info(f"✅ {language} LSP server started for incremental operations")
            
        except Exception as e:
            logger.error(f"Failed to start {language} LSP server: {e}")
    
    async def _cleanup_lsp_servers(self):
        """Cleanup all active LSP servers."""
        
        for language, lsp in self.active_lsp_servers.items():
            try:
                await lsp.stop_server()
                logger.debug(f"Stopped {language} LSP server")
            except Exception as e:
                logger.debug(f"Error stopping {language} LSP server: {e}")
        
        self.active_lsp_servers.clear()
    
    def _extract_source_code(self, content: str, lsp_range: LSPRange) -> str:
        """Extract source code for a symbol from file content."""
        
        try:
            lines = content.split('\n')
            start_line = lsp_range.start.line
            end_line = lsp_range.end.line
            
            if start_line == end_line:
                # Single line
                line = lines[start_line]
                start_char = lsp_range.start.character
                end_char = lsp_range.end.character
                return line[start_char:end_char]
            else:
                # Multiple lines
                result_lines = []
                
                # First line
                first_line = lines[start_line]
                result_lines.append(first_line[lsp_range.start.character:])
                
                # Middle lines
                for i in range(start_line + 1, end_line):
                    result_lines.append(lines[i])
                
                # Last line
                if end_line < len(lines):
                    last_line = lines[end_line]
                    result_lines.append(last_line[:lsp_range.end.character])
                
                return '\n'.join(result_lines)
                
        except Exception as e:
            logger.debug(f"Error extracting source code: {e}")
            return ""
    
    def _extract_existing_docstring(self, content: str, lsp_range: LSPRange, 
                                  language: str) -> Optional[str]:
        """Extract existing docstring for a symbol."""
        
        try:
            lines = content.split('\n')
            symbol_start = lsp_range.start.line
            
            # Look for docstring after symbol definition
            for i in range(symbol_start + 1, min(symbol_start + 5, len(lines))):
                line = lines[i].strip()
                
                if language == "python":
                    if line.startswith('"""') or line.startswith("'''"):
                        # Multi-line docstring
                        quote = '"""' if line.startswith('"""') else "'''"
                        docstring_lines = [line[3:]]  # Remove opening quotes
                        
                        for j in range(i + 1, len(lines)):
                            doc_line = lines[j]
                            if quote in doc_line:
                                # End of docstring
                                end_idx = doc_line.find(quote)
                                docstring_lines.append(doc_line[:end_idx])
                                break
                            else:
                                docstring_lines.append(doc_line)
                        
                        return '\n'.join(docstring_lines).strip()
                
                elif language in ["javascript", "typescript"]:
                    if line.startswith('/**'):
                        # JSDoc comment
                        docstring_lines = [line[3:]]  # Remove /**
                        
                        for j in range(i + 1, len(lines)):
                            doc_line = lines[j].strip()
                            if doc_line.endswith('*/'):
                                docstring_lines.append(doc_line[:-2])  # Remove */
                                break
                            elif doc_line.startswith('*'):
                                docstring_lines.append(doc_line[1:].strip())
                            else:
                                docstring_lines.append(doc_line)
                        
                        return '\n'.join(docstring_lines).strip()
        
        except Exception as e:
            logger.debug(f"Error extracting docstring: {e}")
        
        return None
    
    # ================ LSP SERVER MANAGEMENT ================
    # (Votre code existant pour _discover_files_and_languages, _setup_lsp_servers, 
    #  _check_lsp_server_available, _install_lsp_server, etc.)
    
    async def _discover_files_and_languages(self, project_root: str, 
                                          target_languages: List[str] = None) -> Dict[str, Any]:
        """Discover files and languages in project."""
        # Votre implémentation existante adaptée
        pass
    
    async def _setup_lsp_servers(self, languages: List[str]) -> List[str]:
        """Setup LSP servers for languages."""
        # Votre implémentation existante adaptée
        pass
    
    def _check_lsp_server_available(self, language: str) -> bool:
        """Check if LSP server is available."""
        # Votre implémentation existante
        pass
    
    async def _install_lsp_server(self, language: str) -> bool:
        """Install LSP server."""
        # Votre implémentation existante adaptée
        pass
    
    def _map_lsp_kind_to_string(self, kind: int) -> str:
        """Map LSP SymbolKind to string."""
        # Votre implémentation existante
        pass

    # ================ PUBLIC API ================
    
    def get_project_data(self) -> Optional[Dict[str, Any]]:
        """Get complete project data as dictionary."""
        return self.project.to_dict() if self.project else None
    
    def get_documentable_symbols(self, min_priority: DocumentationPriority = DocumentationPriority.LOW) -> List[EnhancedSymbolModel]:
        """Get all documentable symbols."""
        return self.project.get_documentable_symbols(min_priority) if self.project else []
    
    def get_file_by_path(self, file_path: str) -> Optional[EnhancedFileModel]:
        """Get file model by path."""
        return self._get_existing_file_model(file_path)
    
    def get_symbol_by_name(self, symbol_name: str) -> List[EnhancedSymbolModel]:
        """Get symbols by name."""
        return self.project.get_symbol_by_name(symbol_name) if self.project else []