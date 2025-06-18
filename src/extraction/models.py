""" Models for the extraction app. """

from .extract_imports import *
from .extraction_utils import build_gitignore, excluded
import tempfile 
import pathspec
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

@dataclass
class LSPPosition:
    """Model for a position in the source code."""
    line: int
    character: int

    def to_dict(self) -> Dict[str, int]:
        """Convert to dict representation."""
        return {
            "line": self.line,
            "character": self.character
        }

@dataclass
class LSPRange:
    """Model for a range in the source code."""
    start: LSPPosition
    end: LSPPosition

    def is_inside(self, position: LSPPosition) -> bool:
        """Check if a position is inside this range."""
        return (self.start.line < position.line < self.end.line) or \
               (self.start.line == position.line and self.start.character <= position.character) or \
               (self.end.line == position.line and position.character <= self.end.character)

    def to_dict(self) -> Dict[str, Dict[str, int]]:
        """Convert to dict representation."""
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict()
        }
    
def json_to_range(range: dict) -> LSPRange :
    """Convert a JSON range to LSPRange format."""
    if not range or 'start' not in range or 'end' not in range:
        return None
    
    start = LSPPosition(
        line=range['start'].get('line'),
        character=range['start'].get('character')
    )
    
    end = LSPPosition(
        line=range['end'].get('line'),
        character=range['end'].get('character')
    )
    return LSPRange(start=start, end=end)

@dataclass
class FoldingRange:
    """Model for a folding range in the source code."""
    range : LSPRange
    kind: Optional[str] = None

    is_import_block: bool = kind == "import"  # Indicates if this range is an import block

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict representation."""
        return {
            "start": self.range.start.to_dict(),
            "end": self.range.end.to_dict(),
            "kind": self.kind,
            "is_import_block": self.is_import_block
        }

@dataclass
class SymbolModel:
    """Model for a symbol in the source code."""
    name: str
    symbol_kind: str # e.g., 'function', 'class', 'method',
    file_object: Optional['FileModel'] = None
    file_path: str = ""
    range: Optional['LSPRange'] = None   # LSP range format: {"start": {"line": int, "character": int}, "end": {"line": int, "character": int}}
    selectionRange: Optional['LSPRange'] = None  # LSP selection range format: {"start": {"line": int, "character": int}, "end": {"line": int, "character": int}}
    parent_symbol: Optional['SymbolModel'] = None
    child_symbols: List['SymbolModel'] = field(default_factory=list)
    referencing_symbols: List['SymbolModel'] = field(default_factory=list)
    signature: Dict[str, Any] = field(default_factory=dict)  # Function signature or class definition
    semantic_info: Dict[str, Any] = field(default_factory=dict)  # Semantic analysis information
    is_import: bool = False  # Indicates if this symbol is an import
    documentable: bool = False  # Indicates if this symbol can be documented

    existing_symbol_doc: Optional[str] = None
    source_code: Optional[str] = None
    generated_documentation: Optional[Dict[str, Any]] = field(default_factory=dict)

    def set_generated_documentation(self, doc_data: Dict[str, Any]):
        """Set generated documentation data."""
        self.generated_documentation = doc_data

    def should_document(self) -> bool:
        """Check if this symbol can be documented."""
        self.documentable =(self.symbol_kind in ['function', 'class', 'method', 'property', 'constructor', 'interface', 'struct', 'event'] and 
                self.semantic_info.get("tokenType") in ['function', 'class', 'method', 'property', 'constructor', 'interface', 'struct', 'event'] and 
                self.semantic_info.get("tokenModifiers") not in ['deprecated', "defaultLibrary", "documentation"] and 
                self.is_import is False)
    
    def add_reference_to(self, target_symbol: 'SymbolModel'):
        """Add a reference to another symbol (this symbol uses target_symbol)."""
        if target_symbol not in self.referencing_symbols:
            self.referencing_symbols.append(target_symbol)
         
    def get_parent_name(self) -> Optional[str]:
        """Get parent symbol name if exists."""
        return self.parent_symbol.name if self.parent_symbol else None
    
    def get_full_name(self) -> str:
        """Get fully qualified name."""
        if self.parent_symbol:
            return f"{self.parent_symbol.get_full_name()}.{self.name}"
        return self.name

    def to_dict(self):
        """Convert to dict representation."""
        return {
            "name": self.name,
            "symbol_kind": self.symbol_kind,
            "file_path": self.file_path,
            "parent_symbol": self.get_parent_name(),
            "source_code": self.source_code,
            "existing_symbol_doc": self.existing_symbol_doc,
            "generated_documentation": self.generated_documentation
        }
    
    def to_dict_with_children(self):
        """Convert to dict including children information."""
        result = self.to_dict()
        result["children"] = [child.to_dict() for child in self.children]
        return result

    def is_constructor_semantic(self) -> bool:
        """Check if symbol is a constructor based on semantic analysis."""
        return self.semantic_info.get('is_constructor', False) or self.symbol_kind == 'constructor'
    
    def is_import_semantic(self) -> bool:
        """Check if symbol was detected as import via semantic analysis."""
        return self.semantic_info.get('is_import', False)

@dataclass
class ImportModel:
    """Model for an import statement in the source code."""
    symbolModel : SymbolModel  # Reference to the symbol model of this import (class,function, etc.)a
    definitionLocationLink: Optional[str] = None  # Location link to the definition of the import if from project

@dataclass
class FileModel:
    """Model for a file in the source code."""
    
    path: str
    language: str
    symbols: List[SymbolModel] = field(default_factory=list)
    project_root: Optional[str] = None  # Added for relative path calculation
    imports: List[ImportModel] = field(default_factory=list)
    folding_ranges: List[FoldingRange] = field(default_factory=list)  # Ranges for import blocks

    def get_relative_path(self) -> str:
        """Get relative path for LSP operations and display."""
        if self.project_root:
            try:
                return str(Path(self.path).relative_to(Path(self.project_root)))
            except ValueError:
                return self.path
        return self.path
    
    def add_symbol(self, symbol: SymbolModel):
        """Add a symbol to the file model."""
        if symbol.file_object is None:
            symbol.file_object = self
        elif symbol.file_object.path != self.path:
            raise ValueError(f"Symbol {symbol.name} already belongs to another file: {symbol.file_object.path}")
        
        self.symbols.append(symbol)
        self.index_symbol(symbol)
    
    def get_symbols_by_type(self, symbol_type: str) -> List[SymbolModel]:
        """Get all symbols of a specific type in this file."""
        return [s for s in self.symbols if s.symbol_kind == symbol_type]


    def get_root_symbols(self) -> List[SymbolModel]:
        """Get symbols that have no parent (top-level symbols)."""
        return [s for s in self.symbols if s.parent_symbol is None]
    
    def get_symbols_by_type(self, symbol_type: str) -> List[SymbolModel]:
        """Get all symbols of a specific type."""
        return [s for s in self.symbols if s.symbol_type == symbol_type]
    
    def is_form_import(self, symbol: SymbolModel) -> tuple[bool, Optional[str]]:
        """Check if the symbol is from this file import statement.
        
        Returns:
            definition_location_link
        """
        for import_model in self.imports:
            if import_model.symbolModel.name == symbol.name:
                return import_model.definitionLocationLink
        return None

    def to_dict(self):
        return {
            "path": self.path,
            "language": self.language,
            "total_symbols": len(self.symbols),
            "root_symbols_count": len(self.get_root_symbols()),
            "symbols": [symbol.to_dict() for symbol in self.symbols]
        }
    

@dataclass
class ProjectModel:
    """Model for a project containing multiple files and their symbols."""
    
    name: str
    root: str
    files: List[FileModel] = field(default_factory=list)
    langs: List[str] = field(default_factory=list)
    gitignore: Optional[tempfile.NamedTemporaryFile] = field(default_factory=lambda: None)

    def __post_init__(self):
        """Post-initialization to set up the project model."""
        if not self.root:
            raise ValueError("Project root cannot be empty.")
        self.root = Path(self.root).resolve()
        self.gitignore = self._add_gitignore(self.root)
        if not self.gitignore:
            raise ValueError("Failed to create .gitignore file for the project.")
    
    
    def add_file(self, file_model: FileModel):  # Fixed parameter name
        """Add a file to the project model."""
        file_path = file_model.path
        if not file_path.startswith(self.root):
            raise ValueError(f"File path {file_path} is not within the project root {self.root}.")
        if not self.ignore_file(file_path):
            self.files.append(file_model)
            if file_model.language not in self.langs:
                self.langs.append(file_model.language)
        else:
            print(f"File {file_path} is ignored based on .gitignore rules.")

    def _add_gitignore(self, root: str) -> tempfile.NamedTemporaryFile: 
        """Add .gitignore file to the project model."""
        return build_gitignore(root)
    

    def to_dict(self):
        return {
            "name": self.name,
            "root": self.root,
            "files": [file.to_dict() for file in self.files],
            "langs": self.langs,
            "gitignore": self.gitignore.name if self.gitignore else None
        }

    
    def ignore_file(self, file_path: str) -> bool:
        """Check if the file path should be excluded."""
        if not self.gitignore:
            return False  # Don't exclude if no gitignore
        return excluded(file_path, self.gitignore.name)

