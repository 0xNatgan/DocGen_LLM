""" Models for the extraction app. """

from .extraction_utils import build_gitignore, excluded
import tempfile 
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from ..logging.logging import get_logger

logger = get_logger(__name__)


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

    def contains(self, other_range: 'LSPRange') -> bool:
        """Check if this range contains another range."""
        # Check if other_range is completely within this range
        return (self.start.line < other_range.start.line or 
                (self.start.line == other_range.start.line and self.start.character <= other_range.start.character)) and \
               (self.end.line > other_range.end.line or 
                (self.end.line == other_range.end.line and self.end.character >= other_range.end.character))
    
    def contains_position(self, line: int, character: int) -> bool:
        """Check if this range contains a specific position."""
        return (self.start.line < line or 
                (self.start.line == line and self.start.character <= character)) and \
               (self.end.line > line or 
                (self.end.line == line and self.end.character >= character))

    def is_inside(self, range: 'LSPRange') -> bool:
        """Check if a range is inside this range."""
        return (self.start.line < range.start.line < self.end.line) or \
               (self.start.line == range.start.line and self.start.character <= range.start.character) or \
               (self.end.line == range.end.line and range.end.character <= self.end.character)

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
class SymbolModel:
    """Model for a symbol in the source code."""
    name: str
    symbol_kind: str # e.g., 'function', 'class', 'method',
    file_object: 'FileModel'
    range: Optional['LSPRange'] = None   # LSP range format: {"start": {"line": int, "character": int}, "end": {"line": int, "character": int}}
    selectionRange: Optional['LSPRange'] = None  # LSP selection range format: {"start": {"line": int, "character": int}, "end": {"line": int, "character": int}}
    parent_symbol: Optional['SymbolModel'] = None
    child_symbols: List['SymbolModel'] = field(default_factory=list)
    calling_symbols: List['SymbolModel'] = field(default_factory=list)  # Symbols that call this one
    called_symbols: List['SymbolModel'] = field(default_factory=list)  # Symbols that are called by this one
    
    existing_symbol_docstring: Optional[str] = None
    docstring: Optional[str] = None  # Add this field for extracted docstrings
    generated_documentation: Optional[Dict[str, Any]] = field(default_factory=dict)

    def set_generated_documentation(self, doc_data: Dict[str, Any]):
        """Set generated documentation data."""
        self.generated_documentation = doc_data

    def linking_call_symbols(self, target_symbol: 'SymbolModel'):
        """Add a reference to another symbol (this symbol uses target_symbol).
            The target symbol is calling the self symbol"""
        if target_symbol != self and target_symbol not in self.calling_symbols and self not in target_symbol.called_symbols:
            self.calling_symbols.append(target_symbol)
            target_symbol.called_symbols.append(self)
            logger.debug(f"Linked calling symbol: {self.name} -> {target_symbol.name}")

    def get_parent_name(self) -> Optional[str]:
        """Get parent symbol name if exists."""
        return self.parent_symbol.name if self.parent_symbol else None

    def to_dict(self):
        """Convert to dict representation."""
        return {
            "name": self.name,
            "symbol_kind": self.symbol_kind,
            "file_path": self.file_object.path,
            "parent_symbol": self.get_parent_name(),
            "child_symbols": [child.name for child in self.child_symbols],
            "generated_documentation": self.generated_documentation,
            "nb called symbols": len(self.called_symbols),
            "called symbols" : [symbol.name for symbol in self.called_symbols],
            "nb calling symbols": len(self.calling_symbols),
            "source code": self.source_code,
            "docstring": self.docstring,
            "selectionRange": self.selectionRange.to_dict() if self.selectionRange else None,
        }
    
    @staticmethod
    def create_range(range: dict[str, int]) -> LSPRange:
        """Create a position object for this symbol."""
        start_range = range.get('start', {})
        end_range = range.get('end', {})
        start = LSPPosition(line=start_range.get('line', 0), character=start_range.get('character', 0))
        end = LSPPosition(line=end_range.get('line', 0), character=end_range.get('character', 0))
        return LSPRange(start=start, end=end)

@dataclass
class FileModel:
    """Model for a file in the source code."""
    
    path: str
    language: str
    symbols: List[SymbolModel] = field(default_factory=list)
    project_root: Optional[str] = None  # Added for relative path calculation

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

    def get_root_symbols(self) -> List[SymbolModel]:
        """Get symbols that have no parent (top-level symbols)."""
        return [s for s in self.symbols if s.parent_symbol is None]

    def to_dict(self):
        return {
            "path": self.path,
            "language": self.language,
            "total_symbols": len(self.symbols),
            "root_symbols_count": len(self.get_root_symbols()),
            "symbols": [symbol.to_dict() for symbol in self.symbols],
        }

    def find_symbol_within_range(self, ref_range: LSPRange) -> Optional[SymbolModel]:
        """Find the symbol that contains the given reference range."""
        containing_symbols = []
        
        # Find all symbols that contain this reference position
        for symbol in self.symbols:
            if symbol.range and symbol.range.contains(ref_range):
                containing_symbols.append(symbol)
        
        if not containing_symbols:
            return None
        
        # If multiple symbols contain the range, find the most specific one
        # (the one with the smallest range - likely a method inside a class)
        if len(containing_symbols) > 1:
            # Sort by range size (smaller ranges are more specific)
            containing_symbols.sort(key=lambda s: (
                s.range.end.line - s.range.start.line,
                s.range.end.character - s.range.start.character
            ))
            
            # Return the most specific (smallest) symbol
            return containing_symbols[0]
        
        return containing_symbols[0]

    def remove_symbol(self, symbol: SymbolModel):
        """Remove a symbol from the file model."""
        if symbol in self.symbols:
            self.symbols.remove(symbol)
        else:
            logger.warning(f"Symbol {symbol.name} not found in file {self.path}")   

@dataclass
class FolderModel:
    """Model for a folder containing multiple files and subfolders."""
    name: str
    root: str
    files: List[FileModel] = field(default_factory=list)
    subfolders: List['FolderModel'] = field(default_factory=list)
    parent_folder: Optional['FolderModel'] = None
    langs: List[str] = field(default_factory=list)
    description: Optional[str] = None
    gitignore: Optional[tempfile.NamedTemporaryFile] = field(default_factory=lambda: None)

    def __post_init__(self):
        """Post-initialization to set up the folder model."""
        if not self.root:
            raise ValueError("Folder root cannot be empty.")
        self.root = str(Path(self.root).resolve())
        # Note: Don't create gitignore here - it will be created when needed
        # by calling ensure_gitignore() method when we're sure this is the project root

    def _add_gitignore(self, root: str) -> tempfile.NamedTemporaryFile: 
        """Add .gitignore file to the folder model."""
        return build_gitignore(root)

    def ensure_gitignore(self):
        """Ensure gitignore is created for this folder (should only be called on project root)."""
        if not self.gitignore:
            self.gitignore = self._add_gitignore(self.root)

    def is_project_root(self) -> bool:
        """Check if this folder is the project root."""
        return self.parent_folder is None

    def cleanup(self):
        """Clean up temporary files created by this folder model."""
        if self.gitignore:
            try:
                import os
                if os.path.exists(self.gitignore.name):
                    os.unlink(self.gitignore.name)
                self.gitignore = None
                logger.debug(f"Cleaned up temporary gitignore for {self.name}")
            except Exception as e:
                logger.warning(f"Failed to cleanup gitignore for {self.name}: {e}")

    def add_file(self, file_model: FileModel):
        """Add a file to the folder model."""
        root_folder = self.get_root_folder()
        if not root_folder.ignore_file(file_model.path):
            self.files.append(file_model)
            if file_model.language not in self.langs:
                self.langs.append(file_model.language)

    def add_subfolder(self, folder_model: 'FolderModel'):
        """Add a subfolder to this folder."""
        if not folder_model.root.startswith(self.root):
            raise ValueError(f"Subfolder root {folder_model.root} is not within the folder root {self.root}.")
        folder_model.parent_folder = self
        self.subfolders.append(folder_model)

    def get_root_folder(self) -> 'FolderModel':
        """Get the root folder (project root)."""
        current = self
        while current.parent_folder is not None:
            current = current.parent_folder
        return current

    def ignore_file(self, file_path: str) -> bool:
        """Check if the file path should be excluded."""
        root_folder = self.get_root_folder()
        if not root_folder.gitignore:
            return False
        return excluded(file_path, root_folder.gitignore.name)

    def get_all_files(self) -> List[FileModel]:
        """Get all files in this folder and subfolders recursively."""
        all_files = self.files.copy()
        for subfolder in self.subfolders:
            all_files.extend(subfolder.get_all_files())
        return all_files

    def get_all_subfolders(self) -> List['FolderModel']:
        """Get all subfolders recursively."""
        all_subfolders = self.subfolders.copy()
        for subfolder in self.subfolders:
            all_subfolders.extend(subfolder.get_all_subfolders())
        return all_subfolders
    
    def get_all_languages(self) -> List[str]:
        """Get all languages used in this folder and subfolders."""
        all_langs = set(self.langs)
        for subfolder in self.subfolders:
            all_langs.update(subfolder.get_all_languages())
        return list(all_langs)

    def get_all_symbols(self) -> List[SymbolModel]:
        """Get all symbols in this folder and subfolders recursively."""
        all_symbols = []
        for file_model in self.get_all_files():
            all_symbols.extend(file_model.symbols)
        for subfolder in self.subfolders:
            all_symbols.extend(subfolder.get_all_symbols())
        return all_symbols

    def to_dict(self):
        return {
            "name": self.name,
            "root": self.root,
            "files": [file.to_dict() for file in self.files],
            "subfolders": [subfolder.to_dict() for subfolder in self.subfolders],
            "langs": self.langs,
            "is_root": self.parent_folder is None
        }   

    def find_from_file_path(self, file_path: str) -> Optional['FileModel']:
        """Find a FileModel by its file path."""
        if not file_path:
            return None
        
        # Use the existing method to get all files, then search
        all_files = self.get_all_files()
        
        # Normalize paths for comparison
        search_path = str(Path(file_path).resolve())
        
        for file_model in all_files:
            if str(Path(file_model.path).resolve()) == search_path:
                return file_model
        
        return None

