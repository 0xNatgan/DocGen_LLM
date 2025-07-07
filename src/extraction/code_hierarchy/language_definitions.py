"""Base language definitions class adapted from Blarify's approach."""

from abc import ABC, abstractmethod
from typing import Dict, Set, Optional, List
from tree_sitter import Parser, Node
import logging

from ..models import FileModel, SymbolModel

logger = logging.getLogger(__name__)

class LanguageDefinitions(ABC):
    """Base class for language-specific definitions and parsing rules."""
    
    @staticmethod
    @abstractmethod
    def get_language_name() -> str:
        """Get the name of the language."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_parsers_for_extensions() -> Dict[str, Parser]:
        """Get parsers mapped to file extensions."""
        pass
    
    @staticmethod
    @abstractmethod
    def should_create_node(node: Node) -> bool:
        """Determine if a tree-sitter node should create a symbol."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_identifier_node(node: Node) -> Optional[Node]:
        """Get the identifier node from a definition node."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_body_node(node: Node) -> Optional[Node]:
        """Get the body node from a definition node."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_node_type_mappings() -> Dict[str, str]:
        """Get mapping from tree-sitter node types to symbol kinds."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_import_node_types() -> Set[str]:
        """Get set of tree-sitter node types that represent imports."""
        pass
    
    @staticmethod
    @abstractmethod
    def get_language_file_extensions() -> Set[str]:
        """Get set of file extensions for this language."""
        pass
    
    @staticmethod
    @abstractmethod
    def extract_imports_from_node(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract import symbols from an import node."""
        pass
    
    # Base implementations that can be used by subclasses
    @staticmethod
    def _should_create_node_base_implementation(node: Node, node_types: List[str]) -> bool:
        """Base implementation for should_create_node."""
        return node.type in node_types
    
    @staticmethod
    def _get_identifier_node_base_implementation(node: Node) -> Optional[Node]:
        """Base implementation to find identifier node."""
        for child in node.children:
            if child.type == "identifier":
                return child
        return None
    
    @staticmethod
    def _get_body_node_base_implementation(node: Node) -> Optional[Node]:
        """Base implementation to find body node."""
        for child in node.children:
            if child.type in ["block", "suite", "compound_statement"]:
                return child
        return None
    
    @staticmethod
    def extract_docstring(node: Node, source_code: str) -> Optional[str]:
        """Extract docstring from a node."""
        # Try direct docstring child first
        docstring_node = LanguageDefinitions._find_child_by_type(node, "docstring")
        if docstring_node:
            return LanguageDefinitions._extract_node_text(docstring_node, source_code)
        
        # For Python, check for string expression as first statement in body
        if node.type in ["function_definition", "class_definition"]:
            # Get the body node (suite in Python)
            body_node = LanguageDefinitions._get_body_node_base_implementation(node)
            if body_node and body_node.children:
                # Look for first non-whitespace child
                for child in body_node.children:
                    if child.type == "expression_statement":
                        # Check if it contains a string
                        string_node = LanguageDefinitions._find_child_by_type(child, "string")
                        if string_node:
                            docstring_text = LanguageDefinitions._extract_node_text(string_node, source_code)
                            return LanguageDefinitions._clean_docstring(docstring_text)
                    elif child.type not in ["comment", "newline", "\n"]:
                        # Stop at first real code statement
                        break
    
        return None

    @staticmethod
    def _clean_docstring(raw_docstring: str) -> str:
        """Clean up extracted docstring by removing quotes and excess whitespace."""
        cleaned = raw_docstring.strip()
        
        # Remove Python-style quotes
        if cleaned.startswith('"""') and cleaned.endswith('"""'):
            cleaned = cleaned[3:-3]
        elif cleaned.startswith("'''") and cleaned.endswith("'''"):
            cleaned = cleaned[3:-3]
        elif cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1]
        elif cleaned.startswith("'") and cleaned.endswith("'"):
            cleaned = cleaned[1:-1]
        
        return cleaned.strip()

    @staticmethod
    def _extract_node_text(node: Node, source_code: str) -> str:
        """Extract text from a tree-sitter node."""
        return source_code[node.start_byte:node.end_byte]

    @staticmethod
    def _find_child_by_type(node: Node, target_type: str) -> Optional[Node]:
        """Find first child node of a specific type."""
        for child in node.children:
            if child.type == target_type:
                return child
        return None
    
    @staticmethod
    def _find_children_by_type(node: Node, child_type: str) -> List[Node]:

        """Find all children of specified type."""
        return [child for child in node.children if child.type == child_type]