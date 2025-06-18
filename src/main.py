"""Test the LSP-only extraction approach with universal LSP client."""

import sys
import logging
import asyncio
from pathlib import Path
from extraction.lsp_extractor import LSPExtractor

# Configure logging for better debugging
logging.basicConfig(
    level=logging.INFO,  # Changed from DEBUG to reduce noise
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Disable verbose logs from asyncio and other libraries
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)

async def main():
    """Main async function for testing LSP extraction."""
    # Initialize the extractor with universal LSP client
    extractor = LSPExtractor(
        enable_semantic=True,
        enable_folding=True,
        enable_enhancement=True,
        auto_install=True
    )
    
    try:
        # Get project path from command line or use current directory
        if len(sys.argv) > 1:
            project_root = sys.argv[1]
        else:
            project_root = "."
        
        project_root = str(Path(project_root).resolve())
        print(f"🔍 Analyzing project: {project_root}")
        
        # 1. Extract complete project
        project = await extractor.extract_project(project_root)
        
        if project:
            print(f"\n=== Project Analysis Results ===")
            print(f"📁 Project: {project.name}")
            print(f"📂 Root: {project.root}")
            print(f"🔤 Languages: {', '.join(project.langs)}")
            print(f"📄 Files found: {len(project.files)}")
            
            # Show statistics
            total_symbols = sum(len(f.symbols) for f in project.files)
            print(f"🔍 Total symbols: {total_symbols}")
            
            # Group symbols by type
            symbol_counts = {}
            for file_model in project.files:
                for symbol in file_model.symbols:
                    symbol_type = symbol.symbol_kind
                    symbol_counts[symbol_type] = symbol_counts.get(symbol_type, 0) + 1
            
            if symbol_counts:
                print(f"📊 Symbol breakdown:")
                for symbol_type, count in sorted(symbol_counts.items()):
                    print(f"   - {symbol_type}: {count}")
            
            # Show detailed file info (limited to first 5 files for readability)
            print(f"\n=== File Details (showing first 5) ===")
            for i, file_model in enumerate(project.files[:5]):
                rel_path = file_model.get_relative_path() if hasattr(file_model, 'get_relative_path') else file_model.path
                print(f"📄 {rel_path} ({file_model.language})")
                print(f"   └─ {len(file_model.symbols)} symbols")

                # Show all symbols per file
                for j, symbol in enumerate(file_model.symbols):
                    range_info = ""
                    if hasattr(symbol, 'range') and symbol.range:
                        if hasattr(symbol.range, 'start') and hasattr(symbol.range, 'end'):
                            range_info = f" [{symbol.range.start.line}:{symbol.range.start.character}-{symbol.range.end.line}:{symbol.range.end.character}]"
                    
                    semantic_info = ""
                    if hasattr(symbol, 'semantic_info') and symbol.semantic_info:
                        semantic_info = f" (semantic: {len(symbol.semantic_info)} items)"
                    
                    print(f"      • {symbol.name} ({symbol.symbol_kind}){range_info}{semantic_info}")

            
            if len(project.files) > 5:
                print(f"   ... and {len(project.files) - 5} more files")
            
            
        else:
            print("❌ No project extracted")
            return False
            
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up LSP connections
        await extractor.cleanup()
    
    return True

def test_lsp_only_extraction():
    """Synchronous wrapper for LSP extraction test."""
    try:
        # Run the async main function
        result = asyncio.run(main())
        
        if result:
            print(f"\n🎉 Test completed successfully!")
        else:
            print(f"\n💥 Test failed!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print(f"\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def test_specific_features():
    """Test specific LSP features individually."""
    async def run_feature_tests():
        extractor = LSPExtractor(auto_install=True)
        
        try:
            project_root = sys.argv[1] if len(sys.argv) > 1 else "."
            project_root = str(Path(project_root).resolve())
            
            print(f"🧪 Testing LSP features on: {project_root}")
            
            # Test 1: Basic project discovery  
            print(f"\n1️⃣  Testing project discovery...")
            languages = extractor._discover_files_and_languages(project_root)
            print(f"   Detected languages: {languages}")
            
            # Test 2: LSP server availability
            print(f"\n2️⃣  Testing LSP server availability...")
            for lang in languages:
                available = extractor._check_lsp_server_available(lang)
                status = "✅ Available" if available else "❌ Not available"
                print(f"   {lang}: {status}")
            
            # Test 3: Full extraction
            print(f"\n3️⃣  Testing full extraction...")
            project = await extractor.extract_project_async(project_root)
            
            if project:
                print(f"   ✅ Extraction successful")
                print(f"   📄 Files: {len(project.files)}")
                total_symbols = sum(len(f.symbols) for f in project.files)
                print(f"   🔍 Symbols: {total_symbols}")
            else:
                print(f"   ❌ Extraction failed")
            
        except Exception as e:
            print(f"💥 Feature test error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await extractor.cleanup()
    
    asyncio.run(run_feature_tests())

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "--test-features":
        test_specific_features()
    else:
        test_lsp_only_extraction()