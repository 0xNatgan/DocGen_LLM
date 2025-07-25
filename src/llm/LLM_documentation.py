import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from .llm_client import LLMClient, LLMMessage
from src.extraction.models import FileModel, SymbolModel, FolderModel
from src.logging.logging import get_logger
import sys
import itertools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = get_logger(__name__)

async def document_projects(llm: Optional[LLMClient], project: FolderModel, output_save: Path) -> bool:
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
                model="qwen3:1.7b",
                max_tokens=2000,
                temperature=0.3,
            )
        
        await llm.initialize()
        logger.info("✅ LLM client initialized successfully")
        
        # Create documentation structure
        docs_root = create_docs_structure(project, base_docs_dir=str(output_save) if output_save else "docs")
        
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
        
        # Process each symbol
        for i, ordered_symbol in enumerate(ordered_symbols, 1):
            logger.info(f"📊 Progress: {i}/{total_symbols} symbols")
            logger.info(f"🎯 Current symbol: {ordered_symbol.name} ({ordered_symbol.symbol_kind})")

            try:
                # Check if source code exists before documenting
                doc = await document_symbol(llm, ordered_symbol)
                
                if not doc.strip():
                    logger.warning(f"Empty documentation generated for {ordered_symbol.name}")
                    error_count += 1
                    continue

                doc += "\n\n Places where this symbol is used:\n"

                for calling_symbol in getattr(ordered_symbol, 'calling_symbols', []):
                    calling_symbol_file_path = get_symbol_file_path(calling_symbol, docs_root, project_root)
                    doc += f"[{calling_symbol.name}]({calling_symbol_file_path})\n"


                doc += f"\n\n Called symbols in this {ordered_symbol.name}:\n"
                for called_symbol in getattr(ordered_symbol, 'called_symbols', []):
                    called_symbol_file_path = get_symbol_file_path(called_symbol, docs_root, project_root)
                    doc += f"[{called_symbol.name}]({called_symbol_file_path})\n"

                symbol_file_path = get_symbol_file_path(ordered_symbol, docs_root, project_root)
                # Save main documentation
                with open(symbol_file_path, "w", encoding='utf-8') as f:
                    f.write(doc)
                                
                success_count += 1
                logger.info(f"✅ Successfully documented: {ordered_symbol.name}")
                logger.info(f"📁 Saved to: {symbol_file_path}")
                
            except Exception as e:
                # Improved error logging
                import traceback
                logger.error(f"Error documenting symbol {ordered_symbol.name}: {e}\n{traceback.format_exc()}")
                logger.error(f"❌ Failed to document {ordered_symbol.name}: {e}")

        # Generate summary report
        await generate_summary_report(docs_root, success_count, error_count, total_symbols)
        
        logger.info(f"\n🎉 Documentation generation complete!")
        logger.info(f"✅ Successfully documented: {success_count} symbols")
        logger.info(f"❌ Failed to document: {error_count} symbols")
        logger.info(f"📁 Documentation saved to: {docs_root}")
        
        return error_count == 0
            
    except Exception as e:
        logger.error(f"❌ Critical error in documentation generation: {e}")
        return False
        
    finally:
        if llm:
            try:
                await llm.shutdown()
                logger.info("LLM client shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down LLM: {e}")

def simple_basic_documentation(llm: LLMClient, symbol: SymbolModel) -> str:
    """
    Generate simple documentation for a symbol.
    
    Args:
        symbol: The symbol to document
        llm: The LLM client for generating documentation

    Returns:
        Simple documentation string
    """
    if not symbol:
        return "No symbol provided for documentation."

    if llm:
        # Use LLM to generate documentation
        doc = generate_simple_doc(llm, symbol)
        return doc

    return f"{symbol.symbol_kind} `{symbol.name}`: {symbol.documentation or 'No documentation available.'}"

def generate_simple_doc(llm: LLMClient, symbol: SymbolModel) -> str:
    """
    Generate documentation for a symbol using the LLM.
    
    Args:
        symbol: The symbol to document
        llm: The LLM client for generating documentation
        
    Returns:
        Generated documentation string
    """
    if not llm:
        return "No LLM client provided for documentation generation."

    try:
        messages = [
            LLMMessage(
                role="system",
                content=f"You are an expert technical documentation writer. Document this {symbol.symbol_kind}.\n"
                        f"Follow these guidelines:\n"
                        f"- Use clear, concise language\n"
                        f"- Include a summary, description, parameters, return values\n"
                        f"- Keep the documentation in a length adapted to the symbol's complexity and code length\n"
                        f"- Adapt the documentation to fit in the surrounding code context as docstring\n"
            ),
            LLMMessage(
                role="user",
                content=f"Document the {symbol.symbol_kind} `{symbol.name}` with the following details:\n"
                        f"File: {symbol.file_object.path if symbol.file_object else 'unknown'}\n"
                        f"Language: {symbol.file_object.language if symbol.file_object else 'unknown'}\n"
                        f"Existing docstring: {symbol.docstring or 'None'}\n"
                        f"Source code:\n```{extract_symbol_source_code(symbol) if symbol.selectionRange else 'unknown'}\n```"
            )
        ]
        
        response = asyncio.run(llm.chat(messages))
        return response.strip()
        
    except Exception as e:
        logger.error(f"Error generating documentation for {symbol.name}: {e}")
        return f"Error generating documentation for {symbol.name}: {e}"
      
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
            docs_path.mkdir(parents=True, exist_ok=True)
            
            # Create project-specific subdirectory
            project_docs = docs_path / project.name
            project_docs.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Created documentation structure at: {project_docs}")
            return project_docs
            
        except Exception as e:
            logger.error(f"Error creating docs structure: {e}")
            raise e

async def document_symbol(llm: LLMClient, symbol: SymbolModel, project_context: Optional[str] = None, show_cli_progress: bool = True) -> str:
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
                getattr(sym, 'docstring', getattr(sym, 'name', '')) for sym in symbol.called_symbols
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
        
        # Prepare project context string for f-string injection
        project_context_str = f"\n**Project Context**:\n{project_context}\n" if project_context else ""
        
        # Build messages for LLM
        messages = [
            LLMMessage(
                role="system",
                content=f"""You are an expert technical documentation writer specializing in {language} code documentation.

    Your task is to generate comprehensive, consistent documentation following these strict guidelines:

    ## IMPORTANT:
- Do NOT include any statements about your own reasoning, process, or thinking.
- Do NOT mention that you are an AI, model, or assistant.
- Only output the documentation in the required format, with no extra commentary.

    ## OUTPUT FORMAT REQUIREMENTS:
    1. **Use structured Markdown** with clear sections
    2. **Include a code-ready docstring**
    3. **Follow {language} documentation conventions**
    4. **Be concise but complete**

    ## REQUIRED SECTIONS (in this exact order):
    1. **Summary**: One to two line description of purpose
    2. **Description**: Detailed explanation (4-5 lines)
    3. **Parameters**: If applicable, list all parameters with types
    4. **Returns**: If applicable, describe return value and type
    5. **Raises/Throws**: If applicable, list possible exceptions
    6. **Examples**: Practical usage examples
    7. **Docstring**: Code-ready docstring for insertion

    ## DOCSTRING REQUIREMENTS:
    - Use the language and conventions of the symbol
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
    ## {symbol.symbol_kind} `{symbol.name}`

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
    {extract_symbol_source_code(symbol)}
    ```

    **Context Information:**
    - "Called symbols": {called_symbols_info if called_symbols_info else 'None'}
    - "File imports": {file_imports if file_imports else 'None'}
    - "Existing docstring": {existing_docstring if existing_docstring else 'None'}

    {project_context_str}
    Generate documentation following the exact format requirements above.
    """
            )
        ]
        print(symbol.symbol_kind)
        print(extract_symbol_source_code(symbol))
        logger.info(f"📄 Generating documentation for {symbol.symbol_kind} `{symbol.name}`...\n  Instruction length: {len(messages[1].content)} characters")
        full_response = ""
        chunk_count = 0
        spinner = itertools.cycle(['|', '/', '-', '\\'])
        
        async for chunk in llm.chat_stream(messages):
            full_response += chunk
            chunk_count += 1

            if show_cli_progress:
                sys.stdout.write(f"\rGenerating documentation {next(spinner)}")
                sys.stdout.flush()

        if show_cli_progress:
            sys.stdout.flush()
        
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

# ============ Utility Functions ============

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

def extract_symbol_source_code(symbol: SymbolModel) -> str:
    """
    Extract the source code for a symbol from its file using its range.
    Returns the code as a string, or an empty string if not found.
    """
    file_path = None
    if hasattr(symbol, 'file_object') and symbol.file_object and hasattr(symbol.file_object, 'path'):
        file_path = symbol.file_object.path
    if not file_path or not symbol.range:
        logger.warning(f"Cannot extract source code for symbol {getattr(symbol, 'name', '')}: missing file path or range.")
        return ''
    abs_path = str(Path(symbol.file_object.project_root) / file_path)
    try:
        with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        start = symbol.range.start
        end = symbol.range.end
        # Extract lines from start.line to end.line (inclusive)
        code_lines = lines[start.line:end.line+1]
        # Adjust first and last line by character offset
        if code_lines:
            code_lines[0] = code_lines[0][start.character:]
            code_lines[-1] = code_lines[-1][:end.character]
        return ''.join(code_lines)
    except Exception as e:
        logger.error(f"Error extracting source code for symbol {getattr(symbol, 'name', '')}: {e}")
        return ''

# def template_selection(symbol: SymbolModel) -> str:
    # """
    # Apply a template to a SymbolModel to generate documentation.
    
    # Args:
    #     symbol: The symbol to document
    #     template: The template string with placeholders
        
    # Returns:
    #     Formatted documentation string
    # """
    # try:
    #     return template.format(
    #         name=symbol.name,
    #         kind=symbol.symbol_kind,
    #         docstring=symbol.documentation or "",
    #         file_path=symbol.file_object.path if symbol.file_object else "unknown",
    #         language=symbol.file_object.language if symbol.file_object else "unknown"
    #     )
    # except Exception as e:
    #     logger.error(f"Error applying template for {symbol.name}: {e}")
    #     return ""

def add_references_to_doc(symbol: SymbolModel, doc: str) -> str:
    """
    Add references to the generated documentation.
    
    Args:
        symbol: The symbol being documented
        doc: The generated documentation string
        
    Returns:
        Updated documentation string with references section
    """
    if not hasattr(symbol, 'called_symbols') or not symbol.called_symbols:
        return doc  # No references to add
    
    references = "\n\n## References\n"
    for ref in symbol.called_symbols:
        references += f"- {ref.name} ({ref.symbol_kind})\n"
    
    return doc + references

def extract_file_tree(project: FolderModel) -> List[Tuple[str, str]]:
    """
    Extract the file tree structure of the project.
    
    Args:
        project: The project folder model
        
    Returns:
        The three structure of the project.
    """
    file_tree = []
    
    def traverse_folder(folder: FolderModel, prefix: str = ""):
        for subfolder in folder.subfolders:
            file_tree.append(subfolder.name + "/")
            traverse_folder(subfolder, prefix + "  ")
        for file_model in folder.files:
            file_tree.append(Path(file_model.path).name)

    traverse_folder(project)
    return file_tree

def extract_surronding_file_tree(file_model: FileModel) -> List[str]:
    """
    Extract the surrounding file tree structure for a given file.
    
    Args:
        file_model: The file model to extract the tree for
        
    Returns:
        List of surrounding files in the same directory
    """
    if not file_model or not file_model.path:
        return []

    try:
        parent_dir = Path(file_model.path).parent
        return [f.name for f in parent_dir.iterdir() if f.is_file()]
    except Exception as e:
        logger.error(f"Error extracting surrounding file tree for {file_model.path}: {e}")
        return []