import asyncio
import os
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

async def test_pylsp_semantic():
    """Test PYLSP specifically for semantic tokens."""
    
    logger = MultilspyLogger()
    config = MultilspyConfig.from_dict({
        "code_language": "python",
        "language_server": "pylsp"  # Force PYLSP
    })
    
    repository_root = os.path.abspath(".")
    
    lsp = LanguageServer.create(
        config=config,
        logger=logger,
        repository_root_path=repository_root
    )
    
    async with lsp.start_server():
        print("✅ PYLSP started!")
        
        methods = [m for m in dir(lsp) if 'semantic' in m.lower()]
        print(f"🎯 Semantic methods in PYLSP: {methods}")
        
        # Test si ça marche vraiment
        if methods:
            print("🧪 Testing semantic tokens on real file...")
            # Créer un fichier test
            with open("temp_test.py", "w") as f:
                f.write("def hello(): return 'world'")
            
            try:
                result = await getattr(lsp, methods[0])("temp_test.py")
                print(f"✅ Semantic tokens work! Result type: {type(result)}")
            except Exception as e:
                print(f"❌ Semantic tokens failed: {e}")
            finally:
                os.remove("temp_test.py")

if __name__ == "__main__":
    asyncio.run(test_pylsp_semantic())