"""Generic language extractor using language definitions."""

from typing import Optional, List
from tree_sitter import Node
from pathlib import Path  # Add this import
import logging

from .language_definitions import LanguageDefinitions
from ..models import FileModel, SymbolModel, LSPPosition, LSPRange

logger = logging.getLogger(__name__)

class LanguageExtractor:
    """Generic extractor that uses language-specific definitions."""
    
    def __init__(self, language_definitions: LanguageDefinitions):
        self.definitions = language_definitions
        self.language_name = language_definitions.get_language_name()
        self.parsers = language_definitions.get_parsers_for_extensions()
    
    def extract_symbols_from_file(self, file_model: FileModel) -> FileModel:
        """Extract symbols from file using language definitions."""
        # Fix: Convert string path to Path object to get suffix
        file_path = Path(file_model.path) if isinstance(file_model.path, str) else file_model.path
        file_extension = file_path.suffix.lower()
        
        parser = self.parsers.get(file_extension)
        
        if not parser:
            logger.warning(f"No parser available for extension {file_extension}")
            return file_model
        
        try:
            source_code = file_model.get_source_code()
            if not source_code:
                return file_model
            
            tree = parser.parse(bytes(source_code, 'utf8'))
            
            # Extract symbols
            symbols = self._extract_symbols(tree.root_node, source_code, file_model)
            for symbol in symbols:
                file_model.add_symbol(symbol)
            
            # Extract imports
            imports = self._extract_imports(tree.root_node, source_code, file_model)
            file_model.imports = imports
            
            logger.debug(f"Extracted {len(symbols)} symbols and {len(imports)} imports from {file_model.path}")
            return file_model
            
        except Exception as e:
            logger.error(f"Error extracting from {file_model.path}: {e}")
            return file_model
    
    def _extract_symbols(self, root_node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract symbols using language definitions."""
        symbols = []
        node_type_mappings = self.definitions.get_node_type_mappings()
        
        def traverse(node: Node, parent_symbol: Optional[SymbolModel] = None):
            # Check if we should create a symbol for this node
            if self.definitions.should_create_node(node):
                symbol = self._create_symbol_from_node(
                    node, source_code, file_model, parent_symbol, node_type_mappings
                )
                if symbol:
                    symbols.append(symbol)
                    
                    # Look for nested symbols in the body
                    body_node = self.definitions.get_body_node(node)
                    if body_node:
                        for child in body_node.children:
                            traverse(child, symbol)
                    return
            
            # Continue traversing children
            for child in node.children:
                traverse(child, parent_symbol)
        
        traverse(root_node)
        return symbols
    
    def _extract_imports(self, root_node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract imports using language definitions."""
        imports = []
        import_node_types = self.definitions.get_import_node_types()
        
        def traverse_imports(node: Node):
            if node.type in import_node_types:
                extracted = self.definitions.extract_imports_from_node(node, source_code, file_model)
                imports.extend(extracted)
            
            for child in node.children:
                traverse_imports(child)
        
        traverse_imports(root_node)
        return imports
    
    def _create_symbol_from_node(self, node: Node, source_code: str, file_model: FileModel,
                                parent_symbol: Optional[SymbolModel], node_type_mappings: dict) -> Optional[SymbolModel]:
        """Create symbol from node using language definitions."""
        # Get symbol kind from mappings
        symbol_kind = node_type_mappings.get(node.type, "unknown")
        
        # Get identifier
        identifier_node = self.definitions.get_identifier_node(node)
        if not identifier_node:
            return None
        
        name = source_code[identifier_node.start_byte:identifier_node.end_byte]
        
        # Adjust symbol kind based on context (e.g., method vs function)
        if symbol_kind == "function" and parent_symbol and parent_symbol.symbol_kind == "class":
            symbol_kind = "method"
        
        # Extract docstring using language definitions
        docstring = None
        try:
            docstring = self.definitions.extract_docstring(node, source_code)
        except Exception as e:
            logger.debug(f"Error extracting docstring for {name}: {e}")
        
        symbol = SymbolModel(
            name=name,
            symbol_kind=symbol_kind,
            file_object=file_model,
            range=self._node_to_range(node),
            selectionRange=self._node_to_range(identifier_node),
            parent_symbol=parent_symbol,
            source_code=source_code[node.start_byte:node.end_byte]
        )
        
        # Set the extracted docstring
        if docstring:
            symbol.docstring = docstring
            symbol.existing_symbol_docstring = docstring
        
        # Add to parent if exists
        if parent_symbol:
            parent_symbol.child_symbols.append(symbol)
        
        return symbol
    
    def _node_to_range(self, node: Node) -> LSPRange:
        """Convert node to LSP range."""
        return LSPRange(
            start=LSPPosition(line=node.start_point[0], character=node.start_point[1]),
            end=LSPPosition(line=node.end_point[0], character=node.end_point[1])
        )