""" Enhanced models for LSP analysis with semantic tokens and folding ranges. """

import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import json

class SymbolKind(Enum):
    """LSP Symbol kinds enum."""
    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26

class DocumentationPriority(Enum):
    """Documentation priority levels."""
    CRITICAL = 10  # Public classes, main functions
    HIGH = 8       # Public methods, important functions
    MEDIUM = 5     # Protected methods, utilities
    LOW = 3        # Private methods, internals
    SKIP = 0       # Imports, generated code

@dataclass
class LSPPosition:
    """LSP position model."""
    line: int
    character: int
    
    def to_dict(self) -> Dict[str, int]:
        return {"line": self.line, "character": self.character}
    
    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> 'LSPPosition':
        return cls(line=data["line"], character=data["character"])

@dataclass
class LSPRange:
    """Enhanced LSP range model."""
    start: LSPPosition
    end: LSPPosition
    
    def to_dict(self) -> Dict[str, Dict[str, int]]:
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, int]]) -> 'LSPRange':
        return cls(
            start=LSPPosition.from_dict(data["start"]),
            end=LSPPosition.from_dict(data["end"])
        )
    
    def contains_line(self, line: int) -> bool:
        """Check if range contains a specific line."""
        return self.start.line <= line <= self.end.line
    
    def line_count(self) -> int:
        """Get number of lines in range."""
        return self.end.line - self.start.line + 1
    
    def is_in_range(self, LSPRange: 'LSPRange') -> bool:
        """Check if this range is fully contained within another range."""
        return (self.start.line >= LSPRange.start.line and
                self.end.line <= LSPRange.end.line and
                self.start.character >= LSPRange.start.character and
                self.end.character <= LSPRange.end.character)

@dataclass
class SemanticToken:
    """Semantic token from LSP."""
    line: int
    character: int
    length: int
    token_type: str
    modifiers: List[str] = field(default_factory=list)
    
    def is_constructor(self) -> bool:
        """Check if token represents a constructor."""
        return "constructor" in self.modifiers or self.token_type == "constructor"
    
    def is_import(self) -> bool:
        """Check if token is from an import/library."""
        return "defaultLibrary" in self.modifiers
    
    def is_definition(self) -> bool:
        """Check if token is a definition."""
        return "definition" in self.modifiers or "declaration" in self.modifiers
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "character": self.character,
            "length": self.length,
            "token_type": self.token_type,
            "modifiers": self.modifiers
        }

@dataclass
class FoldingRange:
    """Folding range from LSP."""
    start_line: int
    end_line: int
    kind: str = "region"  # "imports", "comment", "region"
    collapsed_text: str = ""
    
    # Enhanced properties
    is_import_block: bool = False
    is_documentable: bool = True
    contains_symbols: List[str] = field(default_factory=list)
    
    def line_count(self) -> int:
        """Get number of lines in folding range."""
        return self.end_line - self.start_line + 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "kind": self.kind,
            "collapsed_text": self.collapsed_text,
            "is_import_block": self.is_import_block,
            "is_documentable": self.is_documentable,
            "contains_symbols": self.contains_symbols
        }

@dataclass
class ImportInfo:
    """Information about an import statement."""
    line: int
    module: str
    items: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    is_local: bool = False
    import_type: str = "import"  # "import", "from_import", "require", etc.
    raw_line: str = ""
    
    # Resolution info
    resolved_path: Optional[str] = None
    is_external_library: bool = False
    library_name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "module": self.module,
            "items": self.items,
            "alias": self.alias,
            "is_local": self.is_local,
            "import_type": self.import_type,
            "raw_line": self.raw_line,
            "resolved_path": self.resolved_path,
            "is_external_library": self.is_external_library,
            "library_name": self.library_name
        }

@dataclass
class EnhancementInfo:
    """LSP enhancement information (hover, definition, etc.)."""
    hover_text: Optional[str] = None
    definition_location: Optional[str] = None
    type_definition: Optional[str] = None
    references: List[Dict[str, Any]] = field(default_factory=list)
    signature_help: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "hover_text": self.hover_text,
            "definition_location": self.definition_location,
            "type_definition": self.type_definition,
            "references": self.references,
            "signature_help": self.signature_help
        }

@dataclass
class EnhancedSymbolModel:
    """Enhanced symbol model with semantic and folding information."""
    
    # Core properties
    name: str
    symbol_kind: str  # Keep string for flexibility
    lsp_kind: Optional[SymbolKind] = None
    file_path: str = ""
    
    # LSP positioning
    range: Optional[LSPRange] = None
    selection_range: Optional[LSPRange] = None
    
    # Hierarchy
    parent_symbol: Optional['EnhancedSymbolModel'] = None
    child_symbols: List['EnhancedSymbolModel'] = field(default_factory=list)
    
    # Source code and documentation
    source_code: Optional[str] = None
    existing_docstring: Optional[str] = None
    
    # LSP enhancements
    semantic_tokens: List[SemanticToken] = field(default_factory=list)
    enhancement_info: Optional[EnhancementInfo] = None
    folding_range: Optional[FoldingRange] = None
    
    # Documentation metadata
    documentation_priority: DocumentationPriority = DocumentationPriority.MEDIUM
    suggested_template: str = "generic"
    should_document: bool = True
    documentation_strategy: str = "standard"
    
    # References and relationships
    references_to: List['EnhancedSymbolModel'] = field(default_factory=list)
    referenced_by: List['EnhancedSymbolModel'] = field(default_factory=list)
    
    # Generated content
    generated_documentation: Optional[Dict[str, Any]] = field(default_factory=dict)
    
    def get_full_name(self) -> str:
        """Get fully qualified symbol name."""
        if self.parent_symbol:
            return f"{self.parent_symbol.get_full_name()}.{self.name}"
        return self.name
    
    def is_constructor(self) -> bool:
        """Check if symbol is a constructor."""
        return (self.symbol_kind == "constructor" or 
                self.lsp_kind == SymbolKind.CONSTRUCTOR or
                any(token.is_constructor() for token in self.semantic_tokens))
    
    def is_public(self) -> bool:
        """Check if symbol is public (heuristic)."""
        return not self.name.startswith('_')
    
    def is_private(self) -> bool:
        """Check if symbol is private."""
        return self.name.startswith('__')
    
    def is_protected(self) -> bool:
        """Check if symbol is protected."""
        return self.name.startswith('_') and not self.name.startswith('__')
    
    def calculate_documentation_priority(self) -> DocumentationPriority:
        """Calculate documentation priority based on symbol characteristics."""
        
        # Skip imports and internal symbols
        if any(token.is_import() for token in self.semantic_tokens):
            return DocumentationPriority.SKIP
        
        # Critical: Public classes and main functions
        if self.symbol_kind in ["class", "interface"] and self.is_public():
            return DocumentationPriority.CRITICAL
        
        # High: Public methods and functions
        if self.symbol_kind in ["function", "method"] and self.is_public():
            return DocumentationPriority.HIGH
        
        # Medium: Protected or constructors
        if self.is_protected() or self.is_constructor():
            return DocumentationPriority.MEDIUM
        
        # Low: Private but still documentable
        if self.is_private() and self.symbol_kind in ["class", "function", "method"]:
            return DocumentationPriority.LOW
        
        return DocumentationPriority.MEDIUM
    
    def suggest_documentation_template(self) -> str:
        """Suggest appropriate documentation template."""
        
        if self.is_constructor():
            return "constructor_template"
        
        templates = {
            "class": "class_template",
            "interface": "interface_template",
            "function": "function_template",
            "method": "method_template",
            "enum": "enum_template",
            "constant": "constant_template"
        }
        
        return templates.get(self.symbol_kind, "generic_template")
    
    def add_semantic_token(self, token: SemanticToken):
        """Add a semantic token to this symbol."""
        self.semantic_tokens.append(token)
    
    def add_reference_to(self, target_symbol: 'EnhancedSymbolModel'):
        """Add reference to another symbol."""
        if target_symbol not in self.references_to:
            self.references_to.append(target_symbol)
        
        if self not in target_symbol.referenced_by:
            target_symbol.referenced_by.append(self)
    
    def to_dict(self, include_relationships: bool = False) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        
        result = {
            "name": self.name,
            "symbol_kind": self.symbol_kind,
            "lsp_kind": self.lsp_kind.value if self.lsp_kind else None,
            "file_path": self.file_path,
            "range": self.range.to_dict() if self.range else None,
            "selection_range": self.selection_range.to_dict() if self.selection_range else None,
            "parent_name": self.parent_symbol.name if self.parent_symbol else None,
            "child_count": len(self.child_symbols),
            "source_code": self.source_code,
            "existing_docstring": self.existing_docstring,
            "documentation_priority": self.documentation_priority.value,
            "suggested_template": self.suggested_template,
            "should_document": self.should_document,
            "is_constructor": self.is_constructor(),
            "is_public": self.is_public(),
            "semantic_tokens_count": len(self.semantic_tokens),
            "enhancement_info": self.enhancement_info.to_dict() if self.enhancement_info else None,
            "folding_range": self.folding_range.to_dict() if self.folding_range else None,
            "generated_documentation": self.generated_documentation
        }
        
        if include_relationships:
            result.update({
                "child_symbols": [child.name for child in self.child_symbols],
                "references_to": [ref.name for ref in self.references_to],
                "referenced_by": [ref.name for ref in self.referenced_by]
            })
        
        return result

@dataclass
class EnhancedFileModel:
    """Enhanced file model with semantic and folding information."""
    
    path: str
    language: str
    project_root: Optional[str] = None
    
    # Content and metadata
    content: Optional[str] = None
    content_hash: Optional[str] = None
    size_bytes: int = 0
    line_count: int = 0
    
    # Symbols and structure
    symbols: List[EnhancedSymbolModel] = field(default_factory=list)
    
    # LSP enhancements
    semantic_tokens: List[SemanticToken] = field(default_factory=list)
    folding_ranges: List[FoldingRange] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    
    # Analysis metadata
    analysis_timestamp: Optional[str] = None
    lsp_server_used: Optional[str] = None
    enhancement_applied: bool = False
    
    def get_relative_path(self) -> str:
        """Get relative path for LSP operations."""
        if self.project_root:
            try:
                return str(Path(self.path).relative_to(Path(self.project_root)))
            except ValueError:
                return self.path
        return self.path
    
    def add_symbol(self, symbol: EnhancedSymbolModel):
        """Add symbol to file and set file path."""
        symbol.file_path = self.path
        self.symbols.append(symbol)
    
    def get_symbols_by_kind(self, kind: str) -> List[EnhancedSymbolModel]:
        """Get symbols by kind."""
        return [s for s in self.symbols if s.symbol_kind == kind]
    
    def get_documentable_symbols(self, min_priority: DocumentationPriority = DocumentationPriority.LOW) -> List[EnhancedSymbolModel]:
        """Get symbols that should be documented."""
        return [
            s for s in self.symbols 
            if s.should_document and s.documentation_priority.value >= min_priority.value
        ]
    
    def get_import_blocks(self) -> List[FoldingRange]:
        """Get folding ranges that are import blocks."""
        return [fr for fr in self.folding_ranges if fr.is_import_block]
    
    def get_local_imports(self) -> List[ImportInfo]:
        """Get imports that are local to the project."""
        return [imp for imp in self.imports if imp.is_local]
    
    def get_external_imports(self) -> List[ImportInfo]:
        """Get imports that are external libraries."""
        return [imp for imp in self.imports if not imp.is_local]
    
    def calculate_complexity_score(self) -> int:
        """Calculate file complexity score."""
        score = 0
        score += len(self.symbols) * 1
        score += len([s for s in self.symbols if s.symbol_kind == "class"]) * 3
        score += len([s for s in self.symbols if s.symbol_kind == "function"]) * 2
        score += len(self.child_symbols_recursive()) * 1
        return score
    
    def child_symbols_recursive(self) -> List[EnhancedSymbolModel]:
        """Get all child symbols recursively."""
        all_children = []
        for symbol in self.symbols:
            all_children.extend(self._get_children_recursive(symbol))
        return all_children
    
    def _get_children_recursive(self, symbol: EnhancedSymbolModel) -> List[EnhancedSymbolModel]:
        """Recursively get all children of a symbol."""
        children = symbol.child_symbols[:]
        for child in symbol.child_symbols:
            children.extend(self._get_children_recursive(child))
        return children
    
    def to_dict(self, include_symbols: bool = True, include_content: bool = False) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        
        result = {
            "path": self.path,
            "relative_path": self.get_relative_path(),
            "language": self.language,
            "size_bytes": self.size_bytes,
            "line_count": self.line_count,
            "symbols_count": len(self.symbols),
            "semantic_tokens_count": len(self.semantic_tokens),
            "folding_ranges_count": len(self.folding_ranges),
            "imports_count": len(self.imports),
            "local_imports_count": len(self.get_local_imports()),
            "external_imports_count": len(self.get_external_imports()),
            "documentable_symbols_count": len(self.get_documentable_symbols()),
            "complexity_score": self.calculate_complexity_score(),
            "analysis_timestamp": self.analysis_timestamp,
            "lsp_server_used": self.lsp_server_used,
            "enhancement_applied": self.enhancement_applied
        }
        
        if include_symbols:
            result["symbols"] = [symbol.to_dict() for symbol in self.symbols]
            result["imports"] = [imp.to_dict() for imp in self.imports]
            result["folding_ranges"] = [fr.to_dict() for fr in self.folding_ranges]
        
        if include_content:
            result["content"] = self.content
            result["semantic_tokens"] = [token.to_dict() for token in self.semantic_tokens]
        
        return result

@dataclass
class EnhancedProjectModel:
    """Enhanced project model with comprehensive LSP analysis."""
    
    name: str
    root: str
    files: List[EnhancedFileModel] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    
    # Analysis metadata
    analysis_timestamp: Optional[str] = None
    lsp_servers_used: Dict[str, str] = field(default_factory=dict)  # language -> server_version
    total_analysis_time: Optional[float] = None
    
    # Project-wide data
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)  # file -> dependencies
    symbol_index: Dict[str, List[str]] = field(default_factory=dict)      # symbol_name -> file_paths
    
    # Configuration
    gitignore: Optional[tempfile.NamedTemporaryFile] = None
    
    def __post_init__(self):
        """Post-initialization setup."""
        self.root = str(Path(self.root).resolve())
        # Build gitignore if needed
        
    def add_file(self, file_model: EnhancedFileModel):
        """Add file to project."""
        file_model.project_root = self.root
        self.files.append(file_model)
        
        if file_model.language not in self.languages:
            self.languages.append(file_model.language)
        
        # Update symbol index
        for symbol in file_model.symbols:
            if symbol.name not in self.symbol_index:
                self.symbol_index[symbol.name] = []
            if file_model.path not in self.symbol_index[symbol.name]:
                self.symbol_index[symbol.name].append(file_model.path)
    
    def get_files_by_language(self, language: str) -> List[EnhancedFileModel]:
        """Get files for specific language."""
        return [f for f in self.files if f.language == language]
    
    def get_all_symbols(self) -> List[EnhancedSymbolModel]:
        """Get all symbols across all files."""
        symbols = []
        for file_model in self.files:
            symbols.extend(file_model.symbols)
        return symbols
    
    def get_documentable_symbols(self, min_priority: DocumentationPriority = DocumentationPriority.LOW) -> List[EnhancedSymbolModel]:
        """Get all documentable symbols across project."""
        symbols = []
        for file_model in self.files:
            symbols.extend(file_model.get_documentable_symbols(min_priority))
        return symbols
    
    def get_symbol_by_name(self, name: str) -> List[EnhancedSymbolModel]:
        """Find symbols by name across project."""
        symbols = []
        for file_model in self.files:
            symbols.extend([s for s in file_model.symbols if s.name == name])
        return symbols
    
    def calculate_project_stats(self) -> Dict[str, Any]:
        """Calculate comprehensive project statistics."""
        
        all_symbols = self.get_all_symbols()
        
        stats = {
            "files_count": len(self.files),
            "languages": self.languages,
            "languages_count": len(self.languages),
            "total_symbols": len(all_symbols),
            "symbols_by_kind": {},
            "symbols_by_language": {},
            "documentable_symbols": len(self.get_documentable_symbols()),
            "total_imports": sum(len(f.imports) for f in self.files),
            "local_imports": sum(len(f.get_local_imports()) for f in self.files),
            "external_imports": sum(len(f.get_external_imports()) for f in self.files),
            "total_lines": sum(f.line_count for f in self.files),
            "total_size_bytes": sum(f.size_bytes for f in self.files),
            "average_complexity": sum(f.calculate_complexity_score() for f in self.files) / len(self.files) if self.files else 0,
            "lsp_servers_used": self.lsp_servers_used,
            "analysis_timestamp": self.analysis_timestamp
        }
        
        # Count symbols by kind
        for symbol in all_symbols:
            kind = symbol.symbol_kind
            if kind not in stats["symbols_by_kind"]:
                stats["symbols_by_kind"][kind] = 0
            stats["symbols_by_kind"][kind] += 1
        
        # Count symbols by language
        for file_model in self.files:
            lang = file_model.language
            if lang not in stats["symbols_by_language"]:
                stats["symbols_by_language"][lang] = 0
            stats["symbols_by_language"][lang] += len(file_model.symbols)
        
        return stats
    
    def to_dict(self, include_files: bool = True, include_detailed_stats: bool = True) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        
        result = {
            "name": self.name,
            "root": self.root,
            "languages": self.languages,
            "files_count": len(self.files),
            "analysis_timestamp": self.analysis_timestamp,
            "total_analysis_time": self.total_analysis_time
        }
        
        if include_detailed_stats:
            result["stats"] = self.calculate_project_stats()
        
        if include_files:
            result["files"] = [f.to_dict(include_symbols=True) for f in self.files]
        
        return result