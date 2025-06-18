import asyncio
import os
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

async def test_capabilities():
    """Test multilspy capabilities."""
    
    logger = MultilspyLogger()
    config = MultilspyConfig.from_dict({"code_language": "python"})
    
    # Utiliser le répertoire courant comme root
    repository_root = os.path.abspath(".")
    print(f"Using repository root: {repository_root}")
    
    lsp = LanguageServer.create(
        config=config,
        logger=logger,
        repository_root_path=repository_root
    )
    
    async with lsp.start_server():
        print("✅ LSP server started successfully!")
        
        # Lister toutes les méthodes request_*
        methods = [m for m in dir(lsp) if m.startswith('request_')]
        
        print(f"\n📋 Found {len(methods)} request methods:")
        for method in sorted(methods):
            print(f"  - {method}")
        
        # Rechercher spécifiquement les méthodes qui nous intéressent
        semantic_methods = [m for m in methods if 'semantic' in m.lower()]
        folding_methods = [m for m in methods if 'folding' in m.lower()]
        
        print(f"\n🎯 Semantic token methods: {semantic_methods or 'None found'}")
        print(f"📁 Folding range methods: {folding_methods or 'None found'}")
        
        # Vérifier les méthodes standard
        standard_methods = [
            'request_document_symbols',
            'request_folding_ranges', 
            'request_hover',
            'request_definition'
        ]
        
        print(f"\n✅ Standard methods availability:")
        for method in standard_methods:
            available = method in methods
            print(f"  - {method}: {'✅' if available else '❌'}")

if __name__ == "__main__":
    asyncio.run(test_capabilities())