"""Python language definitions adapted from Blarify's approach."""

from typing import Dict, Set, Optional, List
from tree_sitter import Parser, Node
from tree_sitter_language_pack import get_parser
import logging

from ..language_definitions import LanguageDefinitions
from ...models import FileModel, SymbolModel, LSPPosition, LSPRange

logger = logging.getLogger(__name__)

class PythonDefinitions(LanguageDefinitions):
    """Python-specific language definitions."""
    
    @staticmethod
    def get_language_name() -> str:
        return "python"
    
    @staticmethod
    def get_parsers_for_extensions() -> Dict[str, Parser]:
        """Get Python parser for .py files."""
        try:
            parser = get_parser("python")
            return {
                ".py": parser,
                ".pyw": parser,
            }
        except Exception as e:
            logger.error(f"Failed to create Python parser: {e}")
            return {}
    
    @staticmethod
    def should_create_node(node: Node) -> bool:
        """Determine if a Python node should create a symbol."""
        return LanguageDefinitions._should_create_node_base_implementation(
            node, ["class_definition", "function_definition", "async_function_definition", "enum_definition"]
        )
        
    @staticmethod
    def get_identifier_node(node: Node) -> Optional[Node]:
        """Get identifier node from Python definition."""
        return LanguageDefinitions._get_identifier_node_base_implementation(node)
    
    @staticmethod
    def get_body_node(node: Node) -> Optional[Node]:
        """Get body node from Python definition."""
        return LanguageDefinitions._get_body_node_base_implementation(node)
    
    @staticmethod
    def get_node_type_mappings() -> Dict[str, str]:
        """Get Python node type to symbol kind mappings."""
        return {
            "class_definition": "class",
            "function_definition": "function", 
            "async_function_definition": "async_function",
        }
    
    @staticmethod
    def get_import_node_types() -> Set[str]:
        """Get Python import node types."""
        return {"import_statement", "import_from_statement"}
    
    @staticmethod
    def get_language_file_extensions() -> Set[str]:
        """Get Python file extensions."""
        return {".py", ".pyw"}
    
    @staticmethod
    def extract_imports_from_node(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract import symbols from Python import nodes."""
        if node.type == "import_statement":
            return PythonDefinitions._extract_regular_imports(node, source_code, file_model)
        elif node.type == "import_from_statement":
            return PythonDefinitions._extract_from_imports(node, source_code, file_model)
        return []
    
    @staticmethod
    def _extract_regular_imports(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract from 'import module [as alias]' statements."""
        imports = []
        
        for child in node.children:
            if child.type == "dotted_name":
                # import package.module -> get 'module'
                module_path = LanguageDefinitions._extract_node_text(child, source_code)
                symbol_name = module_path.split('.')[-1]
                symbol = PythonDefinitions._create_import_symbol(
                    node, child, symbol_name, source_code, file_model
                )
                imports.append(symbol)
                
            elif child.type == "identifier":
                # import module -> get 'module'
                symbol_name = LanguageDefinitions._extract_node_text(child, source_code)
                symbol = PythonDefinitions._create_import_symbol(
                    node, child, symbol_name, source_code, file_model
                )
                imports.append(symbol)
                
            elif child.type == "aliased_import":
                # import module as alias -> get 'alias'
                alias_symbol = PythonDefinitions._extract_aliased_import(
                    child, source_code, file_model, node
                )
                if alias_symbol:
                    imports.append(alias_symbol)
        
        return imports
    
    @staticmethod
    def _extract_from_imports(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract from 'from module import item [as alias]' statements."""
        imports = []
        
        # Strategy: collect all identifiers that appear after the "import" keyword
        # This handles: from module import item, from module import item1, item2, etc.
        
        # Find the position of the "import" keyword
        import_position = None
        for child in node.children:
            child_text = LanguageDefinitions._extract_node_text(child, source_code).strip()
            if child_text == "import":
                import_position = child.end_byte
                break
        
        if import_position is None:
            logger.warning("Could not find 'import' keyword in from_import statement")
            return imports
        
        # Collect all relevant nodes that come after "import"
        def collect_imported_items(n: Node) -> List[SymbolModel]:
            items = []
            
            # Only process nodes that start after the import keyword
            if n.start_byte <= import_position:
                # Check children recursively
                for child in n.children:
                    items.extend(collect_imported_items(child))
                return items
            
            # Process nodes that come after "import"
            if n.type == "identifier":
                # Direct identifier: from module import item
                name = LanguageDefinitions._extract_node_text(n, source_code)
                symbol = PythonDefinitions._create_import_symbol(
                    node, n, name, source_code, file_model
                )
                items.append(symbol)
                
            elif n.type == "aliased_import":
                # Aliased import: from module import item as alias
                alias_symbol = PythonDefinitions._extract_aliased_import(
                    n, source_code, file_model, node
                )
                if alias_symbol:
                    items.append(alias_symbol)
                    
            elif n.type == "import_list":
                # Import list: from module import item1, item2, item3
                for child in n.children:
                    items.extend(collect_imported_items(child))
                    
            elif n.type == "wildcard_import":
                # Wildcard: from module import *
                symbol = PythonDefinitions._create_import_symbol(
                    node, n, "*", source_code, file_model
                )
                items.append(symbol)
            else:
                # Check children for nested structures
                for child in n.children:
                    items.extend(collect_imported_items(child))
            
            return items
        
        imports = collect_imported_items(node)
        
        logger.debug(f"Extracted {len(imports)} items from from_import: {[imp.name for imp in imports]}")
        return imports
    
    @staticmethod
    def _extract_aliased_import(aliased_node: Node, source_code: str, 
                               file_model: FileModel, import_node: Node) -> Optional[SymbolModel]:
        """Extract alias from 'item as alias'."""
        identifiers = []
        
        for child in aliased_node.children:
            if child.type == "identifier":
                text = LanguageDefinitions._extract_node_text(child, source_code)
                # Skip the "as" keyword
                if text != "as":
                    identifiers.append((child, text))
        
        if len(identifiers) >= 2:
            # Last identifier is the alias
            alias_node, alias_name = identifiers[-1]
            return PythonDefinitions._create_import_symbol(
                import_node, alias_node, alias_name, source_code, file_model
            )
        elif len(identifiers) == 1:
            # Only one identifier found, use it
            name_node, name = identifiers[0]
            return PythonDefinitions._create_import_symbol(
                import_node, name_node, name, source_code, file_model
            )
        
        return None
    
    @staticmethod
    def _create_import_symbol(import_node: Node, name_node: Node, name: str, 
                             source_code: str, file_model: FileModel) -> SymbolModel:
        """Create import symbol."""
        return SymbolModel(
            name=name,
            symbol_kind="import",
            file_object=file_model,
            range=PythonDefinitions._node_to_range(import_node),
            selectionRange=PythonDefinitions._node_to_range(name_node),
            source_code=LanguageDefinitions._extract_node_text(import_node, source_code),
        )
    
    @staticmethod
    def _node_to_range(node: Node) -> LSPRange:
        """Convert node to LSP range."""
        return LSPRange(
            start=LSPPosition(line=node.start_point[0], character=node.start_point[1]),
            end=LSPPosition(line=node.end_point[0], character=node.end_point[1])
        )

    @staticmethod
    def _extract_docstring(node: Node, source_code: str) -> Optional[str]:
        """Extract docstring from a Python node."""
        # Python docstrings are typically the first string literal in a function/class body
        if node.type in ["function_definition", "class_definition"]:
            # Find the body (suite in Python)
            suite_node = PythonDefinitions._find_child_by_type(node, "suite")
            if not suite_node:
                return None
            
            # Look for the first statement in the suite
            for child in suite_node.children:
                if child.type == "expression_statement":
                    # Check if it's a string literal
                    string_node = PythonDefinitions._find_child_by_type(child, "string")
                    if string_node:
                        docstring_text = PythonDefinitions._extract_node_text(string_node, source_code)
                        return PythonDefinitions._clean_python_docstring(docstring_text)
                elif child.type not in ["comment", "newline"]:
                    # If we hit a non-comment, non-newline statement, stop looking
                    break
        
        return None
    
    @staticmethod
    def _clean_python_docstring(raw_docstring: str) -> str:
        """Clean Python docstring."""
        cleaned = raw_docstring.strip()
        
        # Remove Python string prefixes (r, u, f, etc.)
        import re
        cleaned = re.sub(r'^[ruf]*["\']', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'["\']$', '', cleaned)
        
        # Handle triple quotes
        if cleaned.startswith('""') and cleaned.endswith('""'):
            cleaned = cleaned[2:-2]
        elif cleaned.startswith("''") and cleaned.endswith("''"):
            cleaned = cleaned[2:-2]
        
        return cleaned.strip()