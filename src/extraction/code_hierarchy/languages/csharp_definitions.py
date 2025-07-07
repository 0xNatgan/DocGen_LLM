"""C# language definitions adapted from Python definitions approach."""

from typing import Dict, Set, Optional, List
from tree_sitter import Parser, Node
from tree_sitter_language_pack import get_parser
import logging

from ..language_definitions import LanguageDefinitions
from ...models import FileModel, SymbolModel, LSPPosition, LSPRange

logger = logging.getLogger(__name__)

class CSharpDefinitions(LanguageDefinitions):
    """C#-specific language definitions."""
    
    @staticmethod
    def get_language_name() -> str:
        return "csharp"
    
    @staticmethod
    def get_parsers_for_extensions() -> Dict[str, Parser]:
        """Get C# parser for .cs files."""
        try:
            parser = get_parser("csharp")
            return {
                ".cs": parser,
            }
        except Exception as e:
            logger.error(f"Failed to create C# parser: {e}")
            return {}
    
    @staticmethod
    def should_create_node(node: Node) -> bool:
        """Determine if a C# node should create a symbol."""
        return LanguageDefinitions._should_create_node_base_implementation(
            node, [
                "class_declaration", 
                "interface_declaration",
                "struct_declaration",
                "enum_declaration",
                "method_declaration",
                "constructor_declaration",
                "destructor_declaration",
                "property_declaration",
                "event_declaration",
                "field_declaration",
                "namespace_declaration",
                "delegate_declaration",
                "record_declaration"
            ]
        )
        
    @staticmethod
    def get_identifier_node(node: Node) -> Optional[Node]:
        """Get identifier node from C# definition."""
        return LanguageDefinitions._get_identifier_node_base_implementation(node)
    
    @staticmethod
    def get_body_node(node: Node) -> Optional[Node]:
        """Get body node from C# definition."""
        # C# uses "block" or "declaration_list" for bodies
        for child in node.children:
            if child.type in ["block", "declaration_list", "accessor_list"]:
                return child
        return None
    
    @staticmethod
    def get_node_type_mappings() -> Dict[str, str]:
        """Get C# node type to symbol kind mappings."""
        return {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "struct_declaration": "struct",
            "enum_declaration": "enum",
            "method_declaration": "method",
            "constructor_declaration": "constructor",
            "destructor_declaration": "constructor",
            "property_declaration": "property",
            "event_declaration": "event",
            "field_declaration": "field",
            "namespace_declaration": "namespace",
            "delegate_declaration": "delegate",
            "record_declaration": "record"
        }
    
    @staticmethod
    def get_import_node_types() -> Set[str]:
        """Get C# import node types."""
        return {"using_directive", "extern_alias_directive", "global_using_directive"}
    
    @staticmethod
    def get_language_file_extensions() -> Set[str]:
        """Get C# file extensions."""
        return {".cs"}
    
    @staticmethod
    def extract_imports_from_node(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract import symbols from C# using/extern nodes."""
        if node.type == "using_directive":
            return CSharpDefinitions._extract_using_directives(node, source_code, file_model)
        elif node.type == "extern_alias_directive":
            return CSharpDefinitions._extract_extern_alias(node, source_code, file_model)
        elif node.type == "global_using_directive":
            return CSharpDefinitions._extract_global_using(node, source_code, file_model)
        return []
    
    @staticmethod
    def _extract_using_directives(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract from 'using System;' or 'using System.Collections.Generic;' statements."""
        imports = []
        
        for child in node.children:
            if child.type == "qualified_name":
                # using System.Collections.Generic;
                full_name = LanguageDefinitions._extract_node_text(child, source_code)
                symbol_name = full_name.split('.')[-1]  # Get last part as symbol name
                symbol = CSharpDefinitions._create_import_symbol(
                    node, child, symbol_name, source_code, file_model
                )
                imports.append(symbol)
                
            elif child.type == "identifier":
                # using System;
                symbol_name = LanguageDefinitions._extract_node_text(child, source_code)
                symbol = CSharpDefinitions._create_import_symbol(
                    node, child, symbol_name, source_code, file_model
                )
                imports.append(symbol)
                
            elif child.type == "alias_qualified_name":
                # using alias = System.Collections.Generic;
                alias_symbol = CSharpDefinitions._extract_alias_qualified_name(
                    child, source_code, file_model, node
                )
                if alias_symbol:
                    imports.append(alias_symbol)
        
        return imports
    
    @staticmethod
    def _extract_extern_alias(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract from 'extern alias MyAlias;' statements."""
        imports = []
        
        for child in node.children:
            if child.type == "identifier":
                # Skip the "extern" and "alias" keywords
                child_text = LanguageDefinitions._extract_node_text(child, source_code)
                if child_text not in ["extern", "alias"]:
                    symbol = CSharpDefinitions._create_import_symbol(
                        node, child, child_text, source_code, file_model
                    )
                    imports.append(symbol)
        
        return imports
    
    @staticmethod
    def _extract_global_using(node: Node, source_code: str, file_model: FileModel) -> List[SymbolModel]:
        """Extract from 'global using System;' statements."""
        imports = []
        
        for child in node.children:
            if child.type == "qualified_name":
                full_name = LanguageDefinitions._extract_node_text(child, source_code)
                symbol_name = full_name.split('.')[-1]
                symbol = CSharpDefinitions._create_import_symbol(
                    node, child, symbol_name, source_code, file_model
                )
                imports.append(symbol)
                
            elif child.type == "identifier":
                child_text = LanguageDefinitions._extract_node_text(child, source_code)
                # Skip keywords
                if child_text not in ["global", "using"]:
                    symbol = CSharpDefinitions._create_import_symbol(
                        node, child, child_text, source_code, file_model
                    )
                    imports.append(symbol)
        
        return imports
    
    @staticmethod
    def _extract_alias_qualified_name(alias_node: Node, source_code: str, 
                                     file_model: FileModel, import_node: Node) -> Optional[SymbolModel]:
        """Extract alias from 'alias = Namespace.Type'."""
        identifiers = []
        
        for child in alias_node.children:
            if child.type == "identifier":
                text = LanguageDefinitions._extract_node_text(child, source_code)
                identifiers.append((child, text))
        
        if identifiers:
            # First identifier is typically the alias
            alias_node_ref, alias_name = identifiers[0]
            return CSharpDefinitions._create_import_symbol(
                import_node, alias_node_ref, alias_name, source_code, file_model
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
            range=CSharpDefinitions._node_to_range(import_node),
            selectionRange=CSharpDefinitions._node_to_range(name_node),
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
    def extract_docstring(node: Node, source_code: str) -> Optional[str]:
        """Extract documentation from a C# node, prioritizing XML comments."""
        # C# uses XML documentation comments /// or /** */
        docstring = CSharpDefinitions._extract_xml_documentation(node, source_code)
        if docstring:
            return docstring
        
        # Fallback for regular comments above the node
        return CSharpDefinitions._extract_preceding_comments(node, source_code)
    
    @staticmethod
    def _extract_xml_documentation(node: Node, source_code: str) -> Optional[str]:
        """Extract XML documentation comments (/// <summary>...</summary> or /** ... */)."""
        doc_comments = []
        lines = source_code.split('\n')
        node_start_line = node.start_point[0]
        
        # Search backwards from the node for comment blocks
        for i in range(node_start_line - 1, -1, -1):
            if i >= len(lines):
                continue
            
            line = lines[i].strip()
            
            if line.startswith('///'):
                doc_comments.insert(0, line[3:].strip())
            elif line.endswith('*/'):
                # Found the end of a /** ... */ block, now find the start
                block_content = []
                for j in range(i, -1, -1):
                    block_line = lines[j].strip()
                    cleaned_line = block_line.replace('/**', '').replace('*/', '').strip()
                    if cleaned_line.startswith('*'):
                        cleaned_line = cleaned_line[1:].strip()
                    
                    block_content.insert(0, cleaned_line)
                    if lines[j].strip().startswith('/**'):
                        doc_comments = block_content
                        # Move outer loop cursor to avoid re-parsing
                        i = j
                        break
            elif line == '':
                continue # Skip empty lines between code and comments
            else:
                # Reached a non-comment line, stop searching
                break
        
        if doc_comments:
            return CSharpDefinitions._clean_csharp_docstring('\n'.join(filter(None, doc_comments)))
        
        return None

    @staticmethod
    def _extract_preceding_comments(node: Node, source_code: str) -> Optional[str]:
        """Extract regular comments preceding the node."""
        lines = source_code.split('\n')
        node_start_line = node.start_point[0]
        
        comments = []
        
        # Search backwards for // comments
        for i in range(node_start_line - 1, -1, -1):
            if i < len(lines):
                line = lines[i].strip()
                if line.startswith('//'):
                    comment_text = line[2:].strip()
                    comments.insert(0, comment_text)
                elif line == '':
                    continue
                else:
                    break
        
        if comments:
            return '\n'.join(comments)
        
        return None
    
    @staticmethod
    def _clean_csharp_docstring(raw_docstring: str) -> str:
        """Clean C# docstring by removing XML tags and formatting."""
        import re
        
        # Remove all XML tags (e.g., <summary>, <param name="...">, </summary>)
        cleaned = re.sub(r'</?[^>]+>', '', raw_docstring)
        
        # Consolidate whitespace and remove leading/trailing space on each line
        lines = [line.strip() for line in cleaned.split('\n')]
        
        # Join lines, then replace multiple spaces with a single space
        cleaned = re.sub(r'\s+', ' ', ' '.join(lines))
        
        return cleaned.strip()

    @staticmethod
    def _find_child_by_type(node: Node, target_type: str) -> Optional[Node]:
        """Find first child node of a specific type."""
        for child in node.children:
            if child.type == target_type:
                return child
        return None
    
    @staticmethod
    def _extract_node_text(node: Node, source_code: str) -> str:
        """Extract text from a tree-sitter node."""
        return source_code[node.start_byte:node.end_byte]