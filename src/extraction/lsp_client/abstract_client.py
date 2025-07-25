from abc import ABC, abstractmethod
from typing import Any, List, Optional, Dict
from src.logging.logging import get_logger

logger = get_logger(__name__)

class BaseLSPClient(ABC):
    """
    Abstract base class for Language Server Protocol clients.
    Defines the interface for both standalone and Docker-based LSP clients.
    """

    @abstractmethod
    async def start_server(self, workspace_root: str) -> bool:
        """
        Start the LSP server process for the given workspace.
        Returns True if the server started successfully, False otherwise.
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """
        Gracefully shut down the LSP server process and clean up resources.
        """
        pass

    @abstractmethod
    async def get_document_symbols(self, file_path: str, symbol_kind_list: Optional[List[int]] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Request document symbols for the given file path.
        Optionally filter by symbol kinds.
        Returns a list of symbol dicts or None on error.
        """
        pass

    @abstractmethod
    async def did_open_file(self, file_path: str) -> bool:
        """
        Notify the LSP server that a file has been opened.
        This is necessary for the server to provide accurate responses.
        """
        pass

    @abstractmethod
    async def get_references(self, file_path: str, line: int, character: int, include_declaration: bool = False) -> Optional[List[Dict[str, Any]]]:
        """
        Request references for a symbol at the given file, line, and character.
        Returns a list of reference dicts or None on error.
        """
        pass

    @abstractmethod
    async def get_definition(self, file_path: str, line: int, character: int, include_declaration: bool = True) -> Optional[List[Dict[str, Any]]]:
        """
        Request definition(s) for a symbol at the given file, line, and character.
        Returns a list of definition dicts or None on error.
        """
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """
        Returns True if the LSP server process is running, False otherwise.
        """
        pass