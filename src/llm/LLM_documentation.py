import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple, List
from .llm_client import LLMClient, LLMMessage
from src.extraction.models import FileModel, SymbolModel, FolderModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_docstring_from_response(response: str) -> Tuple[str, str]:
    """ Extract docstring and clean documentation from LLM response.
    Args:
        response: Raw LLM response containing documentation and docstring
    Returns:
        Tuple of (clean_documentation, extracted_docstring)
    """
    try:
        # Extract docstring between $$$ markers
        docstring_pattern = r'\$\$\$(.*?)\$\$\$'
        docstring_match = re.search(docstring_pattern, response, re.DOTALL)
        
        docstring = ""
        if docstring_match:
            docstring = docstring_match.group(1).strip()
            # Remove the docstring section from the main response
            clean_response = re.sub(docstring_pattern, '', response, flags=re.DOTALL)
        else:
            clean_response = response
            logger.warning("No docstring markers found in response")
        
        return clean_response.strip(), docstring
        
    except Exception as e:
        logger.error(f"Error extracting docstring: {e}")
        return response, ''

def create_docs_structure(project: FolderModel, base_docs_dir: str = "docs") -> Path:
    """
    Create documentation folder structure mirroring the project structure.
    
    Args:
        project: The project folder model
        base_docs_dir: Base directory for documentation
        
    Returns:
        Path to the created docs directory
    """
    docs_path = Path(base_docs_dir+ "/" + project.name + "_documentation")

    try:
        # Create base docs directory
        docs_path.mkdir(exist_ok=True)
        
        # Create project-specific subdirectory
        project_docs = docs_path / project.name
        project_docs.mkdir(exist_ok=True)
        
        logger.info(f"Created documentation structure at: {project_docs}")
        return project_docs
        
    except Exception as e:
        logger.error(f"Error creating docs structure: {e}")

def get_symbol_file_path(symbol: SymbolModel, docs_root: Path, project_root: Path = None) -> Path:
    """
    Get the file path for a symbol's documentation following project architecture.
    
    Args:
        symbol: The symbol to document
        docs_root: Root documentation directory
        project_root: Root of the original project (for relative path calculation)
        
    Returns:
        Path where the symbol's documentation should be saved
    """
    try:
        if hasattr(symbol, 'file_object') and symbol.file_object and symbol.file_object.path:
            original_file_path = Path(symbol.file_object.path)
            
            # If we have project root, calculate relative path properly
            if project_root:
                try:
                    relative_file_path = original_file_path.relative_to(project_root)
                    # Get directory and filename
                    relative_dir = relative_file_path.parent
                    file_name = relative_file_path.stem
                    
                    # Create mirrored structure
                    if str(relative_dir) != '.':
                        symbol_dir = docs_root / relative_dir / file_name
                    else:
                        symbol_dir = docs_root / file_name
                except ValueError:
                    # Fallback if relative_to fails
                    symbol_dir = docs_root / original_file_path.stem
            else:
                # Simple approach without project root
                symbol_dir = docs_root / original_file_path.stem
        else:
            # Fallback for symbols without file info
            symbol_dir = docs_root / "unknown"
        
        # Create the directory
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        # Create safe filename for the symbol
        safe_name = "".join(c for c in symbol.name if c.isalnum() or c in '._-').rstrip()
        filename = f"{safe_name}.md"
        
        return symbol_dir / filename
        
    except Exception as e:
        logger.error(f"Error determining file path for {symbol.name}: {e}")
        safe_name = "".join(c for c in symbol.name if c.isalnum() or c in '._-').rstrip()
        return docs_root / f"{safe_name}.md"

async def document_elements_first_pass(llm: Optional[LLMClient], project: FolderModel) -> bool:
    """
    Generate documentation for all symbols in the project.
    
    Args:
        llm: Pre-configured LLM client, or None to create default
        project: Project folder model containing all symbols
        
    Returns:
        bool: True if documentation generation completed successfully
    """
    success_count = 0
    error_count = 0
    
    try:
        # Initialize LLM client
        if llm is None:
            logger.info("Creating new LLM client for Ollama")
            llm = LLMClient(
                provider="ollama", 
                model="openhermes",
                max_tokens=2000,
                temperature=0.6,
            )
        
        await llm.initialize()
        logger.info("✅ LLM client initialized successfully")
        
        # Create documentation structure
        docs_root = create_docs_structure(project)
        
        # Get project root for relative path calculation
        project_root = Path(project.root) if hasattr(project, 'root') else None
        
        # Get all symbols
        symbols = project.get_all_symbols()
        
        if not symbols:
            logger.warning("No symbols found in project")
            return True
        
        # Sort symbols by dependency count (simplest first)
        ordered_symbols = sorted(symbols, key=lambda s: len(getattr(s, 'called_symbols', [])))
        total_symbols = len(ordered_symbols)
        
        logger.info(f"🚀 Starting documentation generation for {total_symbols} symbols...")
        print(f"🚀 Starting documentation generation for {total_symbols} symbols...")
        
        # Process each symbol
        for i, ordered_symbol in enumerate(ordered_symbols, 1):
            print(f"\n📊 Progress: {i}/{total_symbols} symbols")
            print(f"🎯 Current symbol: {ordered_symbol.name} ({ordered_symbol.symbol_kind})")
            
            try:
                # Check if source code exists before documenting
                if not ordered_symbol.source_code:
                    raise ValueError("Source code is missing, cannot generate documentation.")

                doc = await document_symbol(llm, ordered_symbol)
                
                if not doc.strip():
                    logger.warning(f"Empty documentation generated for {ordered_symbol.name}")
                    error_count += 1
                    continue
                
                # Extract docstring and clean documentation
                clean_doc, extracted_docstring = extract_docstring_from_response(doc)
                
                # Store in symbol object
                ordered_symbol.documentation = clean_doc
                ordered_symbol.generated_docstring = extracted_docstring
                
                # Save to files with project architecture structure
                symbol_file_path = get_symbol_file_path(ordered_symbol, docs_root, project_root)
                
                # Save main documentation
                with open(symbol_file_path, "w", encoding='utf-8') as f:
                    f.write(clean_doc)
                
                # Save docstring separately if extracted
                if extracted_docstring:
                    docstring_path = symbol_file_path.with_suffix('.docstring.txt')
                    with open(docstring_path, "w", encoding='utf-8') as f:
                        f.write(extracted_docstring)
                
                success_count += 1
                logger.info(f"✅ Successfully documented: {ordered_symbol.name}")
                print(f"✅ Successfully documented: {ordered_symbol.name}")
                print(f"📁 Saved to: {symbol_file_path}")
                
            except Exception as e:
                # Improved error logging
                import traceback
                logger.error(f"Error documenting symbol {ordered_symbol.name}: {e}\n{traceback.format_exc()}")
                print(f"❌ Failed to document {ordered_symbol.name}: {e}")
    
        # Generate summary report
        await generate_summary_report(docs_root, success_count, error_count, total_symbols)
        
        print(f"\n🎉 Documentation generation complete!")
        print(f"✅ Successfully documented: {success_count} symbols")
        print(f"❌ Failed to document: {error_count} symbols")
        print(f"📁 Documentation saved to: {docs_root}")
        
        return error_count == 0
            
    except Exception as e:
        logger.error(f"Critical error in documentation generation: {e}")
        print(f"❌ Critical error: {e}")
        return False
        
    finally:
        if llm:
            try:
                await llm.shutdown()
                logger.info("LLM client shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down LLM: {e}")

async def document_symbol(llm: LLMClient, symbol: SymbolModel) -> str:
    """
    Generate documentation for a single symbol.
    
    Args:
        llm: Initialized LLM client
        symbol: Symbol to document
        
    Returns:
        Generated documentation as string
        
    Raises:
        Exception: If documentation generation fails
    """
    try:
        # Gather context information safely
        called_symbols_info = []
        if hasattr(symbol, 'called_symbols') and symbol.called_symbols:
            called_symbols_info = [
                getattr(sym, 'name', str(sym)) for sym in symbol.called_symbols
            ]
        
        # Get file imports safely
        file_imports = []
        if hasattr(symbol, 'file_object') and symbol.file_object and hasattr(symbol.file_object, 'imports'):
            file_imports = [
                getattr(imp, 'name', str(imp)) for imp in symbol.file_object.imports
            ]
        
        # Get existing docstring if available
        existing_docstring = getattr(symbol, 'docstring', None) or getattr(symbol, 'existing_symbol_docstring', None)
        
        # Determine programming language
        language = "python"  # Default
        if hasattr(symbol, 'file_object') and hasattr(symbol.file_object, 'language'):
            language = symbol.file_object.language
        
        # Build messages for LLM
        messages = [
            LLMMessage(
                role="system",
                content=f"""You are an expert technical documentation writer specializing in {language} code documentation.

Your task is to generate comprehensive, consistent documentation following these strict guidelines:

## OUTPUT FORMAT REQUIREMENTS:
1. **Use structured Markdown** with clear sections
2. **Include a code-ready docstring** delimited by $$$ markers
3. **Follow {language} documentation conventions**
4. **Be concise but complete**

## REQUIRED SECTIONS (in this exact order):
1. **Summary**: One-line description of purpose
2. **Description**: Detailed explanation (2-3 sentences)
3. **Parameters**: If applicable, list all parameters with types
4. **Returns**: If applicable, describe return value and type
5. **Raises/Throws**: If applicable, list possible exceptions
6. **Examples**: Practical usage examples
7. **Docstring**: Code-ready docstring for insertion

## DOCSTRING REQUIREMENTS:
- Use triple quotes for Python (\"\"\"), JSDoc format for JavaScript, etc.
- Place between $$$ markers for easy extraction
- Follow language-specific conventions
- Include all parameters and return types
- Be suitable for IDE tooltips

## CONSISTENCY RULES:
- Always use the same section headers
- Always include Examples section (even if simple)
- Always provide the docstring section
- Use consistent formatting for parameters (name: type - description)
- Use consistent code block language tags

## Example Format:
```markdown
## {symbol.symbol_kind.title()} `{symbol.name}`

**Summary**: Brief one-line description.

**Description**: Detailed explanation of what this {symbol.symbol_kind} does and how it works.

**Parameters**:
- `param_name (type)`: Description of parameter.

**Returns**: Description of return value and type.

**Raises/Throws**: List any exceptions that may be raised.

**Examples**:
```{language}
# Example usage
example_code_here()
```

**Docstring**:
$$$
\"\"\"Brief description.\"\"\"
$$$
```
"""
            ),
            LLMMessage(
                role="user",
                content=f"""Document this {language} {symbol.symbol_kind}:

**Symbol Information:**
- Name: `{symbol.name}`
- Type: {symbol.symbol_kind}
- Language: {language}

**Source Code:**
```{language}
{getattr(symbol, 'source_code', 'No source code available')}
```

**Context Information:**
- Called symbols: {called_symbols_info if called_symbols_info else 'None'}
- File imports: {file_imports if file_imports else 'None'}
- Existing docstring: {existing_docstring if existing_docstring else 'None'}

Generate documentation following the exact format requirements above.
"""
            )
        ]
        
        # Generate documentation with streaming
        logger.info(f"🔄 Documenting symbol: {symbol.name}")
        
        full_response = ""
        chunk_count = 0
        
        async for chunk in llm.chat_stream(messages):
            full_response += chunk
            chunk_count += 1
            
            # Optional: Show progress for long responses
            if chunk_count % 20 == 0:
                print(".", end="", flush=True)
        
        # Fix: Check the final response, not individual chunks
        if not full_response.strip():
            logger.warning(f"Empty response received for symbol: {symbol.name}")
            raise Exception(f"Empty response received for symbol: {symbol.name}")
        
        logger.info(f"📄 Generated {len(full_response)} characters for {symbol.name}")
        return full_response
        
    except Exception as e:
        logger.error(f"Error documenting symbol {symbol.name}: {e}")
        raise Exception(f"Failed to document {symbol.name}: {e}")  # Re-raise properly

async def generate_summary_report(docs_root: Path, success_count: int, error_count: int, total_count: int):
    """Generate a summary report of the documentation generation process."""
    try:
        summary_file = docs_root / "README.md"
        
        with open(summary_file, "w", encoding='utf-8') as f:
            f.write(f"# Documentation Summary\n\n")
            f.write(f"Generated on: {asyncio.get_event_loop().time()}\n\n")
            f.write(f"## Statistics\n\n")
            f.write(f"- Total symbols: {total_count}\n")
            f.write(f"- Successfully documented: {success_count}\n")
            f.write(f"- Failed to document: {error_count}\n")
            f.write(f"- Success rate: {(success_count/total_count)*100:.1f}%\n\n")
            
            if error_count > 0:
                f.write(f"## Errors\n\n")
                f.write(f"Check the `errors/` directory for detailed error information.\n\n")
            
            f.write(f"## Navigation\n\n")
            f.write(f"Documentation is organized by source file structure. ")
            f.write(f"Each symbol has its own `.md` file with corresponding `.docstring.txt` files.\n")
        
        logger.info(f"Summary report saved to: {summary_file}")
        
    except Exception as e:
        logger.error(f"Error generating summary report: {e}")