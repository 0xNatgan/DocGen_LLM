"""Factory for creating language extractors using definitions."""

from typing import Optional, Dict, Type, List
import logging

from .language_extractor import LanguageExtractor
from .language_definitions import LanguageDefinitions
from .languages.python_definitions import PythonDefinitions
from .languages.csharp_definitions import CSharpDefinitions

logger = logging.getLogger(__name__)

class ExtractorFactory:
    """Factory for creating language-specific extractors."""
    
    _language_definitions: Dict[str, Type[LanguageDefinitions]] = {
        "python": PythonDefinitions,
        "csharp": CSharpDefinitions,
        # Add more languages here:
        # "javascript": JavaScriptDefinitions,
        # "typescript": TypeScriptDefinitions,
    }
    
    _extractors: Dict[str, LanguageExtractor] = {}
    
    @classmethod
    def get_extractor(cls, language: str) -> Optional[LanguageExtractor]:
        """Get extractor for specified language."""
        if language not in cls._language_definitions:
            logger.warning(f"No definitions available for language: {language}")
            return None
        
        # Use singleton pattern
        if language not in cls._extractors:
            try:
                definitions_class = cls._language_definitions[language]
                cls._extractors[language] = LanguageExtractor(definitions_class)
                logger.info(f"Created extractor for {language}")
            except Exception as e:
                logger.error(f"Failed to create extractor for {language}: {e}")
                return None
        
        return cls._extractors[language]
    
    @classmethod
    def get_supported_languages(cls) -> List[str]:
        """Get list of supported languages."""
        return list(cls._language_definitions.keys())