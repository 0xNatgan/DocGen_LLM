# test_multilspy_capabilities.py
import asyncio
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

async def test_semantic_tokens():
    """Test semantic tokens support in multilspy."""
    
    logger = MultilspyLogger()
    config = MultilspyConfig.from_dict({"code_language": "python"})
    lsp = LanguageServer.create(
        config=config,
        logger=logger,
        repository_root_path="legacy/testmultils.py",
    )
    
    async with lsp.start_server():
        print("LSP server started")
        
        # Tester les méthodes disponibles
        methods = [m for m in dir(lsp) if m.startswith('request_')]
        print(f"Available methods: {methods}")
        
        # Chercher semantic tokens
        semantic_methods = [m for m in methods if 'semantic' in m.lower()]
        print(f"Semantic methods: {semantic_methods}")
        
        # Tester sur un fichier Python simple
        try:
            if 'request_semantic_tokens_full' in methods:
                result = await lsp.request_semantic_tokens_full("test.py")
                print(f"Semantic tokens result: {type(result)}")
            else:
                print("❌ request_semantic_tokens_full not available")
        except Exception as e:
            print(f"Semantic tokens failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_semantic_tokens())