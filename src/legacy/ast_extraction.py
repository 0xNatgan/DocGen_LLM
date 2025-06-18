""" AST Extraction Module using Tree-sitter and storing in SQL database."""

from ..extract_imports import *
import json
import tree_sitter_languages
from tree_sitter import Language, Parser, Node
from ..extraction_utils import excluded, _ext_to_lang
from ..models import ProjectModel, FileModel, SymbolModel
from .lsp_enhancer import LSPEnhancer

logger = logging.getLogger(__name__)

class ASTExtractor:
    """ Extract AST from source code files using Tree-sitter and tree-sitter languages."""

    def __init__(self, config_path: str = None, db_path: str = None, use_lsp: bool = True):
        """ Initialize the ASTExtractor with configuration and database path."""
        self.config = self._load_language_config(config_path)
        # self.db = DatabaseService(db_path)  # Uncomment when ready
        self.languages = {}
        self.parsers = {}  # Changed from self.parser to self.parsers for consistency
        self.project = None
        self.use_lsp = use_lsp
        self.lsp_enhancer = LSPEnhancer() if use_lsp else None
        # Don't initialize parsers here - wait for project discovery

    def _load_language_config(self, config_path: str = None) -> Dict[str, Any]:
        """Load language configuration from JSON file."""
        if config_path is None:
            config_path = Path(__file__).parent / "extract_config/languages_config.json"
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading language config: {e}")
            return {"languages": {}, "default_config": {}}

    def extract_project(self, project_root: str) -> ProjectModel:
        """Extract project with enhanced symbol cross-references."""
        # Convert to absolute path and validate
        project_root = str(Path(project_root).resolve())
        project_name = Path(project_root).name
        
        if not Path(project_root).exists() or not Path(project_root).is_dir():
            logger.error(f"Project root '{project_root}' must be a valid directory.")
            return None
        
        self.project = ProjectModel(name=project_name, root=project_root)
        
        detected_languages = set()
        
        for file_path in Path(project_root).rglob('*'):
            if file_path.is_file():
                if not self.project.ignore_file(str(file_path)):
                    file_extension = file_path.suffix.lstrip('.')
                    lang = _ext_to_lang(file_extension)
                    
                    if lang and lang in self.config.get("languages", {}):
                        detected_languages.add(lang)
                        file_model = FileModel(path=str(file_path), language=lang)
                        self.project.files.append(file_model)
                        if lang not in self.project.langs:
                            self.project.langs.append(lang)
                        logger.debug(f"Added file: {file_path} (language: {lang})")
                    else:
                        logger.debug(f"Unsupported file extension '{file_extension}' for {file_path}. Skipping.")
                else:
                    logger.debug(f"File {file_path} is excluded by gitignore rules.")
        
        if not self.project.files:
            logger.warning(f"No supported files found in project {project_name}.")
            return None
        
        logger.info(f"Detected languages: {detected_languages}")
        self._initialize_parsers_for_languages(detected_languages)
        
        # Phase 3: Extraction du contenu et parsing Tree-sitter
        self.extract_files_content()
        self._extract_symbols()
        
        # Phase 4: Enhancement with LSP
        if self.use_lsp and self.lsp_enhancer:
            logger.info("Enhancing symbols with LSP information...")
            
            # Initialize LSP with project (this builds the indexes)
            self.lsp_enhancer.initialize_for_project(self.project)
            
            # Enhance each file
            for file_model in self.project.files:
                if file_model.symbols:
                    self.lsp_enhancer.enhance_symbols(file_model)
        
        return self.project

    def _initialize_parsers_for_languages(self, languages: set):
        """Initialize parsers only for detected languages."""
        logger.info(f"Initializing parsers for languages: {languages}")
        
        for lang in languages:
            if lang in self.parsers:
                continue  # Already initialized
                
            try:
                # Get the tree-sitter language name from config
                lang_config = self.config["languages"][lang]
                ts_name = lang_config.get("tree_sitter_name", lang)
                
                # Initialize language and parser
                language = tree_sitter_languages.get_language(ts_name)
                parser = tree_sitter_languages.get_parser(ts_name)
                
                self.languages[lang] = language
                self.parsers[lang] = parser
                
                logger.debug(f"Successfully initialized parser for {lang}")
                
            except Exception as e:
                logger.error(f"Error initializing parser for {lang}: {e}")
                # Remove files with this language since we can't parse them
                self.project.files = [
                    f for f in self.project.files 
                    if f.language != lang
                ]

    def extract_files_content(self) -> None:
        """Extract content from files in the project."""
        logger.info(f"Reading content from {len(self.project.files)} files...")
        
        for file_model in self.project.files:
            try:
                with open(file_model.path, 'r', encoding='utf-8') as f:
                    content = f.read()
                file_model.content = content
                logger.debug(f"Read {len(content)} characters from {file_model.path}")
                
            except Exception as e:
                logger.error(f"Error reading file {file_model.path}: {e}")
                file_model.content = ""

    def _extract_symbols(self) -> None:
        """Extract symbols from all files using appropriate parsers."""
        logger.info("Extracting symbols from files...")
        
        for file_model in self.project.files:
            if not file_model.content:
                continue
                
            lang = file_model.language
            if lang not in self.parsers:
                logger.warning(f"No parser available for language {lang} in file {file_model.path}")
                continue
            
            try:
                symbols = self._parse_file_symbols(file_model)
                file_model.symbols = symbols
                logger.debug(f"Extracted {len(symbols)} symbols from {file_model.path}")
                
            except Exception as e:
                logger.error(f"Error extracting symbols from {file_model.path}: {e}")

    def _parse_file_symbols(self, file_model: FileModel) -> List[SymbolModel]:
        """Parse symbols using Tree-sitter with object references for parent-child relationships."""
        parser = self.parsers[file_model.language]
        tree = parser.parse(file_model.content.encode('utf-8'))
        
        symbols = []
        lang_config = self.config["languages"][file_model.language]
        
        def traverse_node(node: Node, parent_symbol: SymbolModel = None):
            current_symbol = None
            
            # Extract classes
            if self._is_class_node(node, lang_config):
                current_symbol = self._extract_class_symbol(node, file_model, lang_config, parent_symbol)
                if current_symbol:
                    symbols.append(current_symbol)
                    file_model.add_symbol(current_symbol)
                    # Parse methods within class - pass class symbol as parent
                    for child in node.children:
                        traverse_node(child, current_symbol)
            
            # Extract functions/methods
            elif self._is_function_node(node, lang_config):
                current_symbol = self._extract_function_symbol(node, file_model, lang_config, parent_symbol)
                if current_symbol:
                    symbols.append(current_symbol)
                    file_model.add_symbol(current_symbol)
            
            # Extract interfaces
            elif self._is_interface_node(node, lang_config):
                current_symbol = self._extract_interface_symbol(node, file_model, lang_config, parent_symbol)
                if current_symbol:
                    symbols.append(current_symbol)
                    file_model.add_symbol(current_symbol)
                    # Parse methods within interface
                    for child in node.children:
                        traverse_node(child, current_symbol)
            
            # Recursively traverse other nodes (only if we didn't handle them above)
            else:
                for child in node.children:
                    traverse_node(child, parent_symbol)
        
        traverse_node(tree.root_node)
        return symbols

    def _is_function_node(self, node: Node, lang_config: Dict) -> bool:
        """Check if node represents a function."""
        func_types = lang_config.get("node_types", {}).get("function", [])
        if isinstance(func_types, str):
            func_types = [func_types]
        elif func_types is None:
            func_types = []
        
        # Also check for constructor node types
        constructor_types = lang_config.get("node_types", {}).get("constructor", [])
        if isinstance(constructor_types, str):
            constructor_types = [constructor_types]
        elif constructor_types is None:
            constructor_types = []
        
        all_func_types = func_types + constructor_types
        return node.type in all_func_types

    def _is_class_node(self, node: Node, lang_config: Dict) -> bool:
        """Check if node represents a class."""
        class_types = lang_config.get("node_types", {}).get("class", [])
        if isinstance(class_types, str):
            class_types = [class_types]
        elif class_types is None:
            return False  # No class support for this language
        return node.type in class_types

    def _is_interface_node(self, node: Node, lang_config: Dict) -> bool:
        """Check if node represents an interface."""
        interface_types = lang_config.get("node_types", {}).get("interface", [])
        if isinstance(interface_types, str):
            interface_types = [interface_types]
        elif interface_types is None:
            return False  # No interface support for this language
        return node.type in interface_types

    def _extract_function_symbol(self, node: Node, file_model: FileModel, 
                            lang_config: Dict, parent_symbol: SymbolModel = None) -> SymbolModel:
        """Extract function/method symbol information."""
        name_field = lang_config.get("fields", {}).get("name", "name")
        name_node = node.child_by_field_name(name_field)
        name = name_node.text.decode('utf-8') if name_node else 'unknown'
        
        # Determine symbol type based on context
        if parent_symbol and parent_symbol.symbol_type == 'class':
            # Check if it's a constructor
            if (self._is_constructor(node, name, lang_config) or 
                self._is_constructor_by_context(node, name, parent_symbol, lang_config)):
                symbol_type = 'constructor'
            else:
                symbol_type = 'method'
        else:
            symbol_type = 'function'
        
        symbol = SymbolModel(
            name=name,
            symbol_type=symbol_type,
            file_path=file_model.path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1
        )
        
        # Set parent-child relationships
        if parent_symbol:
            symbol.parent_symbol = parent_symbol
            parent_symbol.child_symbols.append(symbol)
        
        return symbol

    def _extract_class_symbol(self, node: Node, file_model: FileModel, 
                            lang_config: Dict, parent_symbol: SymbolModel = None) -> SymbolModel:  # Added parent_symbol parameter
        """Extract class symbol information."""
        name_field = lang_config.get("fields", {}).get("name", "name")
        name_node = node.child_by_field_name(name_field)
        name = name_node.text.decode('utf-8') if name_node else 'unknown'
        
        return SymbolModel(
            name=name,
            symbol_type='class',
            file_path=file_model.path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_symbol=parent_symbol
        )

    def _extract_interface_symbol(self, node: Node, file_model: FileModel, 
                             lang_config: Dict, parent_symbol: SymbolModel = None) -> SymbolModel:
        """Extract interface symbol information."""
        name_field = lang_config.get("fields", {}).get("name", "name")
        name_node = node.child_by_field_name(name_field)
        name = name_node.text.decode('utf-8') if name_node else 'unknown'
        
        return SymbolModel(
            name=name,
            symbol_type='interface',
            file_path=file_model.path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_symbol=parent_symbol
        )

    def _is_constructor(self, node: Node, name: str, lang_config: Dict) -> bool:
        """Check if function is a constructor."""
        # Get constructor names from config for the specific language
        constructor_names = lang_config.get("constructor_names", [])
        
        # Default constructor names by language if not in config
        default_constructors = {
            "python": ["__init__"],
            "java": ["constructor"],  # In Java, constructor name = class name
            "javascript": ["constructor"],
            "typescript": ["constructor"],
            "cpp": ["constructor"],  # In C++, constructor name = class name
            "csharp": ["constructor"],  # In C#, constructor name = class name
            "swift": ["init"],
            "kotlin": ["constructor", "init"]
        }

        if not constructor_names:
            lang_name = lang_config.get("name", "")
            constructor_names = default_constructors.get(lang_name, ["__init__", "constructor"])
        
        return name in constructor_names
    
    def _is_constructor_by_context(self, node: Node, name: str, parent_symbol: SymbolModel, lang_config: Dict) -> bool:
        """Check if function is a constructor based on context (name matches class name)."""
        if not parent_symbol or parent_symbol.symbol_type != 'class':
            return False
        
        # In many languages, constructor name = class name
        return name == parent_symbol.name

    def get_project_stats(self) -> Dict[str, int]:
        """Get project statistics."""
        if not self.project:
            return {}
        
        stats = {
            'files': len(self.project.files),
            'total_symbols': 0,
            'functions': 0,
            'classes': 0,
            'methods': 0,
            'interfaces': 0,
            'constructors': 0
        }
        
        all_symbols = self.project.get_all_symbols()
        stats['total_symbols'] = len(all_symbols)
        
        for symbol in all_symbols:
            if symbol.symbol_type == 'function':
                stats['functions'] += 1
            elif symbol.symbol_type == 'class':
                stats['classes'] += 1
            elif symbol.symbol_type == 'method':
                stats['methods'] += 1
            elif symbol.symbol_type == 'interface':
                stats['interfaces'] += 1
            elif symbol.symbol_type == 'constructor':
                stats['constructors'] += 1
        
        return stats

    def _enhance_with_lsp(self) -> None:
        """Enhance all symbols with LSP information."""
        for file_model in self.project.files:
            if file_model.symbols:  # Only process files with symbols
                logger.debug(f"Enhancing {len(file_model.symbols)} symbols in {file_model.path}")
                self.lsp_enhancer.enhance_symbols(file_model)

    def cleanup(self) -> None:
        """Clean up resources."""
        if self.lsp_enhancer:
            self.lsp_enhancer.cleanup()

    def _create_file_model(self, file_path: str, language: str) -> FileModel:
        """Create a file model for a given file path."""
        content = self._read_file_content(file_path)
        if content:
            # Pass project root for relative path calculation
            project_root = self.project.root if self.project else None
            return FileModel(file_path, language, content, project_root)
        return None