import asyncio
import os
from multilspy import LanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

async def test_server_capabilities(server_name):
    """Test capabilities for a specific LSP server."""
    
    print(f"\n{'='*50}")
    print(f"🔍 Testing {server_name.upper()} LSP Server")
    print(f"{'='*50}")
    
    try:
        logger = MultilspyLogger()
        
        # 🎯 CHANGEMENT: Spécifier le serveur LSP
        config = MultilspyConfig.from_dict({
            "code_language": "python",
            "language_server": server_name  # Spécifier le serveur
        })
        
        repository_root = os.path.abspath(".")
        print(f"Repository root: {repository_root}")
        
        lsp = LanguageServer.create(
            config=config,
            logger=logger,
            repository_root_path=repository_root
        )
        
        async with lsp.start_server():
            print(f"✅ {server_name} LSP server started successfully!")
            
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
                'request_definition',
                'request_semantic_tokens_full',
                'request_semantic_tokens_range'
            ]
            
            print(f"\n✅ Standard methods availability:")
            for method in standard_methods:
                available = method in methods
                status = '✅' if available else '❌'
                print(f"  - {method}: {status}")
            
            return {
                'server': server_name,
                'methods_count': len(methods),
                'has_semantic_tokens': bool(semantic_methods),
                'has_folding_ranges': bool(folding_methods),
                'all_methods': methods
            }
            
    except Exception as e:
        print(f"❌ Failed to start {server_name}: {e}")
        return {
            'server': server_name,
            'error': str(e),
            'methods_count': 0,
            'has_semantic_tokens': False,
            'has_folding_ranges': False
        }

async def test_all_servers():
    """Test all available Python LSP servers."""
    
    # Serveurs à tester
    servers_to_test = [
        "jedi",      # Par défaut
        "pylsp",     # Python LSP Server
        "pyright",   # Microsoft Pyright  
        "rope"       # Rope LSP
    ]
    
    results = []
    
    for server in servers_to_test:
        result = await test_server_capabilities(server)
        results.append(result)
        
        # Petite pause entre les tests
        await asyncio.sleep(1)
    
    # Résumé comparatif
    print(f"\n{'='*60}")
    print(f"📊 COMPARATIVE SUMMARY")
    print(f"{'='*60}")
    
    print(f"{'Server':<12} {'Methods':<8} {'Semantic':<9} {'Folding':<8} {'Status'}")
    print(f"{'-'*12} {'-'*8} {'-'*9} {'-'*8} {'-'*10}")
    
    for result in results:
        if 'error' in result:
            print(f"{result['server']:<12} {'N/A':<8} {'N/A':<9} {'N/A':<8} ❌ Error")
        else:
            semantic = '✅' if result['has_semantic_tokens'] else '❌'
            folding = '✅' if result['has_folding_ranges'] else '❌'
            print(f"{result['server']:<12} {result['methods_count']:<8} {semantic:<9} {folding:<8} ✅ OK")
    
    # Recommandation
    best_servers = [r for r in results if not 'error' in r and r['has_semantic_tokens']]
    if best_servers:
        best = max(best_servers, key=lambda x: x['methods_count'])
        print(f"\n🏆 RECOMMENDED: {best['server']} ({best['methods_count']} methods)")
    
    return results

if __name__ == "__main__":
    asyncio.run(test_all_servers())