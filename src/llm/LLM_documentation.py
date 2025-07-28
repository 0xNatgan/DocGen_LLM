import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from .llm_client import LLMClient, LLMMessage
from .json_to_format import OutputFormat, convert_doc , FORMAT_TO_FUNC
from src.extraction.models import FileModel, SymbolModel, FolderModel
from src.logging.logging import get_logger
import sys
import itertools
import re
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = get_logger(__name__)

async def document_projects(
        llm: Optional[LLMClient],
        project: FolderModel,
        output_save: Path,
        context: Optional[Path],
        output_format: Optional[OutputFormat] = OutputFormat.MARKDOWN,
        max_retries: int = 2
        ) -> bool:
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
        
        if context is not None:
            with open(Path(context), "r", encoding='utf-8') as context_file:
                context_text = context_file.read()
        else:
            context_text = None
        

        # Sort symbols by dependency count (simplest first)
        ordered_symbols = sorted(symbols, key=lambda s: len(getattr(s, 'called_symbols', [])))
        total_symbols = len(ordered_symbols)
        
        logger.info(f"🚀 Starting documentation generation for {total_symbols} symbols...")
        
        # Process each symbol
        for i, ordered_symbol in enumerate(ordered_symbols, 1):
            logger.info(f"📊 Progress: {i}/{total_symbols} symbols")
            logger.info(f"🎯 Current symbol: {ordered_symbol.name} ({ordered_symbol.symbol_kind})")

            try:
                json_doc = await safe_document_symbol_json(
                    llm,
                    symbol=ordered_symbol,
                    project_context=context_text if context_text else None,
                    show_cli_progress=True,
                    max_retries=max_retries
                )
                json_doc['name'] = ordered_symbol.name
                json_doc['kind'] = ordered_symbol.symbol_kind
                json_doc['language'] = ordered_symbol.file_object.language if ordered_symbol.file_object else 'unknown'

                json_doc['parent_symbol'] = {
                    "name": ordered_symbol.parent_symbol.name,
                    "kind": ordered_symbol.parent_symbol.symbol_kind,
                    "path": get_relative_doc_link(ordered_symbol.parent_symbol, docs_root=docs_root, output_format=output_format)
                } if ordered_symbol.parent_symbol else None
                json_doc['places_used'] = [
                    {
                        "name": calling_symbol.name,
                        "kind": calling_symbol.symbol_kind,
                        "path": get_relative_doc_link(calling_symbol, output_format.ext)
                    }
                    for calling_symbol in getattr(ordered_symbol, 'calling_symbols', [])
                ]
                json_doc['called_symbols'] = [
                    {
                        "name": called_symbol.name,
                        "kind": called_symbol.symbol_kind,
                        "path": get_relative_doc_link(called_symbol, output_format.ext)
                    }
                    for called_symbol in getattr(ordered_symbol, 'called_symbols', [])
                ]

                documentation = convert_doc(doc=json_doc, format=output_format)

                if not documentation.strip():
                    logger.warning(f"Empty documentation generated for {ordered_symbol.name}")
                    error_count += 1
                    continue

                symbol_file_path = get_symbol_file_path(ordered_symbol, docs_root, project_root)
                try:
                    with open(symbol_file_path, "w", encoding='utf-8') as f:
                        f.write(documentation)
                    success_count += 1
                    logger.info(f"📁 Saved to: {symbol_file_path}")
                except Exception as e:
                    logger.error(f"Error saving documentation for {ordered_symbol.name}: {e}")
                    error_count += 1

            except Exception as e:
                import traceback
                logger.error(f"Error documenting symbol {ordered_symbol.name}: {e}\n{traceback.format_exc()}")
                logger.error(f"❌ Failed to document {ordered_symbol.name}: {e}")
                error_count += 1

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
        return response


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
        
        template_path = Path(__file__).parent / "llm_template.json"
        with open(template_path, "r", encoding="utf-8") as f:
            llm_template = json.load(f).get("docstring_instruction", {}).get(symbol.file_object.language, None) if symbol.file_object else None


        if llm_template is None:
            llm_template = """One-line summary.

                    Detailed description.

                    Args:
                        param1 (type): Description.
                        param2 (type): Description.

                    Returns:
                        type: Description.

                    Raises:
                        ExceptionType: Description.
                    """
        
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
                ```{language}
                    # The following should be a code-ready documentation comment for this {symbol.symbol_kind},
                    # in the correct style for {language} (e.g., Python docstring, Javadoc, XML, etc).
                    # Only output the comment block, not the function/class signature or code.
                    # DO NOT include any examples or additional text.
                    
                    {llm_template}

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
                    - "Existing docstring": {existing_docstring if existing_docstring else 'None'}
                    - "Called symbols": {called_symbols_info if called_symbols_info else 'None'}

                    {project_context_str}
                    Generate documentation following the exact format requirements above.
                    """
                )
        ]
        full_response = ""
        chunk_count = 0
        spinner = itertools.cycle(["( ●    )",
			"(  ●   )",
			"(   ●  )",
			"(    ● )",
			"(     ●)",
			"(    ● )",
			"(   ●  )",
			"(  ●   )",
			"( ●    )",
			"(●     )"])

        
        
        async for chunk in llm.chat_stream(messages):
            full_response += chunk
            chunk_count += 1

            if show_cli_progress:
                sys.stdout.write(f"\rGenerating documentation {next(spinner)}")
                sys.stdout.flush()
                await asyncio.sleep(0.1)

        if show_cli_progress:
            sys.stdout.write('\r' + ' ' * 80 + '\r')
            sys.stdout.flush()
        # Fix: Check the final response, not individual chunks
        if not full_response.strip():
            logger.warning(f"Empty response received for symbol: {symbol.name}")
            raise Exception(f"Empty response received for symbol: {symbol.name}")

        # Remove <think>...</think> block if present
        full_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL)
        logger.info(f"📄 Generated {len(full_response)} characters for {symbol.name}")
        return full_response
        
    except Exception as e:
        logger.error(f"Error documenting symbol {symbol.name}: {e}")
        raise Exception(f"Failed to document {symbol.name}: {e}")  # Re-raise properly

async def document_symbol_json(
    llm: LLMClient,
    symbol: SymbolModel,
    project_context: Optional[str] = None,
    show_cli_progress: bool = True
    ) -> dict:
    """
    Generate documentation for a single symbol using a JSON schema for output.

    Args:
        llm: Initialized LLM client
        symbol: Symbol to document

    Returns:
        Generated documentation as a dict with structured fields

    Raises:
        Exception: If documentation generation fails
    """
    import json

    try:
        # Gather context information safely
        called_symbols_info = []
        if hasattr(symbol, 'called_symbols') and symbol.called_symbols:
            called_symbols_info = [
                getattr(sym, 'docstring', getattr(sym, 'name', '')) for sym in symbol.called_symbols
            ]

        llm_template = None
        template_path = Path(__file__).parent / "llm_template.json"
        with open(template_path, "r", encoding="utf-8") as f:
            llm_template = json.load(f).get("docstring_instruction", {}).get(symbol.file_object.language, None) if symbol.file_object else None
        if llm_template is None:
            llm_template = """One-line summary.

                    Detailed description.

                    Args:
                        param1 (type): Description.
                        param2 (type): Description.

                    Returns:
                        type: Description.

                    Raises:
                        ExceptionType: Description.
                    """
        # Get existing docstring if available
        existing_docstring = getattr(symbol, 'docstring', None) or getattr(symbol, 'existing_symbol_docstring', None)

        # Determine programming language
        language = "python"
        if hasattr(symbol, 'file_object') and hasattr(symbol.file_object, 'language'):
            language = symbol.file_object.language

        # Prepare project context string
        project_context_str = f"\nProject Context:\n{project_context}\n" if project_context else ""

        # JSON schema for the documentation
        doc_schema = {
            "summary": "string (1-2 lines)",
            "description": "string (4-5 lines)",
            "parameters": [
                {
                    "name": "string",
                    "type": "string",
                    "description": "string"
                }
            ],
            "returns": {
                "type": "string",
                "description": "string"
            },
            "raises": [
                {
                    "type": "string",
                    "description": "string"
                }
            ],
            "examples": [
                "string"
            ],
            "docstring": f"string (the code-ready docstring, only the comment block, not the function/class signature or code) take exemple on this (do not include any examples): {llm_template}"
        }

        # Build messages for LLM
        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"You are an expert technical documentation writer specializing in {language} code documentation.\n"
                    f"Your task is to generate documentation for the following symbol as a single JSON object "
                    f"with these fields: {json.dumps(doc_schema, indent=2)}\n"
                    f"All fields must be present. Do not include any text outside the JSON object and make sure the output is a valid JSON OBJECT.\n"
                    f"For the 'docstring' field, output only the code-ready documentation comment (e.g., Python docstring, Javadoc, XML, etc), "
                    f"not the function/class signature or code."
                )
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Document this {language} {symbol.symbol_kind}:\n"
                    f"Symbol Information:\n"
                    f"- Name: {symbol.name}\n"
                    f"- Type: {symbol.symbol_kind}\n"
                    f"- Language: {language}\n\n"
                    f" - Parent symbol : {symbol.parent_symbol.symbol_kind} {symbol.parent_symbol.name}\n" if symbol.parent_symbol else ""
                    f"Source Code:\n"
                    f"{extract_symbol_source_code(symbol)}\n\n"
                    f"Context Information:\n"
                    f"- Existing docstring: {existing_docstring if existing_docstring else 'None'}\n"
                    f"- Called symbols: {called_symbols_info if called_symbols_info else 'None'}\n"
                    f"{project_context_str}\n"
                    f"Generate documentation as a single JSON object following the schema above."
                )
            )
        ]

        full_response = ""
        chunk_count = 0
        spinner = itertools.cycle([
            "( ●    )", "(  ●   )", "(   ●  )", "(    ● )", "(     ●)",
            "(    ● )", "(   ●  )", "(  ●   )", "( ●    )", "(●     )"
        ])

        async for chunk in llm.chat_stream(messages):
            full_response += chunk
            chunk_count += 1
            if show_cli_progress:
                sys.stdout.write(f"\rGenerating documentation {next(spinner)}")
                sys.stdout.flush()
                await asyncio.sleep(0.1)

        if show_cli_progress:
            sys.stdout.write('\r' + ' ' * 80 + '\r')
            sys.stdout.flush()

        # Remove <think>...</think> block if present
        full_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL)
        # Parse the JSON output
        try:
            doc_json = json.loads(full_response)
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON output for {symbol.name}: {e}\nRaw output:\n{full_response}")
            raise Exception(f"Failed to parse LLM JSON output for {symbol.name}: {e}")

        logger.info(f"📄 Generated JSON documentation for {symbol.name}")
        return doc_json

    except Exception as e:
        logger.error(f"Error documenting symbol {symbol.name}: {e}")
        raise Exception(f"Failed to document {symbol.name}: {e}")

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

def get_relative_doc_link(symbol: SymbolModel, docs_root: Path, project_root: Path = None, ext: str = ".md") -> str:
    """
    Get the relative documentation link for a symbol, starting from the docs root.
    """
    doc_path = get_symbol_file_path(symbol, docs_root, project_root)
    # Change extension if needed
    if ext and doc_path.suffix != ext:
        doc_path = doc_path.with_suffix(ext)
    # Make path relative to docs_root
    try:
        rel_path = doc_path.relative_to(docs_root)
    except ValueError:
        rel_path = doc_path.name  # fallback: just filename
    return str(rel_path)

def extract_symbol_source_code(symbol: SymbolModel) -> str:
    """
    Extract the source code for a symbol from its file using its range.
    Returns the code as a string, or an empty string if not found.
    """
    # Get file path
    file_path = None
    if hasattr(symbol, 'file_object') and symbol.file_object and hasattr(symbol.file_object, 'path'):
        file_path = symbol.file_object.path

    if not file_path or not hasattr(symbol, 'range') or not symbol.range:
        logger.warning(f"Cannot extract source code for symbol {getattr(symbol, 'name', '')}: missing file path or range.")
        return ''

    # Get project root if available
    project_root = getattr(symbol.file_object, 'project_root', None) if hasattr(symbol, 'file_object') else None

    # Build absolute path robustly
    file_path_obj = Path(file_path)
    if file_path_obj.is_absolute():
        abs_path = str(file_path_obj)
    elif project_root:
        abs_path = str(Path(project_root) / file_path_obj)
    else:
        abs_path = str(file_path_obj)

    try:
        with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        # Extract range information
        start = getattr(symbol.range, 'start', None)
        end = getattr(symbol.range, 'end', None)
        
        if not start or not end:
            logger.warning(f"Symbol range missing start or end for {getattr(symbol, 'name', '')}")
            return ''
        
        start_line = getattr(start, 'line', None)
        start_character = getattr(start, 'character', 0)
        end_line = getattr(end, 'line', None)
        end_character = getattr(end, 'character', 0)
        
        if start_line is None or end_line is None:
            logger.warning(f"Symbol range start/end missing line for {getattr(symbol, 'name', '')}")
            return ''
        
        # Validate line range
        if start_line < 0 or end_line < 0 or start_line >= len(lines) or end_line >= len(lines):
            logger.warning(f"Invalid line range for symbol {getattr(symbol, 'name', '')}: {start_line}-{end_line}, file has {len(lines)} lines")
            return ''
        
        if start_line > end_line:
            logger.warning(f"Start line {start_line} is greater than end line {end_line} for symbol {getattr(symbol, 'name', '')}")
            return ''
        
        # Extract code lines
        code_lines = lines[start_line:end_line + 1]
        
        if not code_lines:
            return ''
        
        # Adjust first and last line by character offset
        if start_line == end_line:
            # Single-line symbol
            line = code_lines[0]
            if start_character < len(line) and end_character <= len(line):
                code_lines[0] = line[start_character:end_character]
            else:
                logger.warning(f"Character range out of bounds for symbol {getattr(symbol, 'name', '')}")
                code_lines[0] = line[start_character:] if start_character < len(line) else ''
        else:
            # Multi-line symbol
            first_line = code_lines[0]
            last_line = code_lines[-1]
            
            # Adjust first line
            if start_character < len(first_line):
                code_lines[0] = first_line[start_character:]
            else:
                code_lines[0] = ''
            
            # Adjust last line
            if end_character <= len(last_line):
                code_lines[-1] = last_line[:end_character]
            # If end_character is beyond line length, keep the whole line
        
        return ''.join(code_lines)
        
    except FileNotFoundError:
        logger.error(f"File not found: {abs_path}")
        return ''
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

def json_doc_to_markdown(doc: dict, symbol) -> str:
    """
    Convert a documentation dictionary (from LLM JSON output) to a Markdown documentation page.

    Args:
        doc: The documentation dictionary from the LLM.
        symbol_name: Optional symbol name for the header.
        symbol_kind: Optional symbol kind for the header.
        language: Programming language for code blocks.

    Returns:
        Markdown string.
    """
    language = symbol.file_object.language if hasattr(symbol, 'file_object') and symbol.file_object else "python"
    # Header
    header = f"## {symbol.symbol_kind or ''} `{symbol.name or ''}`\n\n"

    # Summary
    summary = f"**Summary**: {doc.get('summary', '').strip()}\n\n"

    # Description
    description = f"**Description**: {doc.get('description', '').strip()}\n\n"

    # Parameters
    params_md = ""
    parameters = doc.get("parameters", [])
    if parameters:
        params_md = "**Parameters**:\n"
        for param in parameters:
            pname = param.get("name", "")
            ptype = param.get("type", "")
            pdesc = param.get("description", "")
            params_md += f"- `{pname} ({ptype})`: {pdesc}\n"
        params_md += "\n"
    else:
        params_md = "**Parameters**: None\n\n"

    # Returns
    returns = doc.get("returns", {})
    returns_md = ""
    if returns and (returns.get("type") or returns.get("description")):
        returns_md = f"**Returns**: {returns.get('description', '')} ({returns.get('type', '')})\n\n"

    # Raises
    raises_md = ""
    raises = doc.get("raises", [])
    if raises:
        raises_md = "**Raises/Throws**:\n"
        for exc in raises:
            etype = exc.get("type", "")
            edesc = exc.get("description", "")
            raises_md += f"- `{etype}`: {edesc}\n"
        raises_md += "\n"
    else:
        raises_md = "**Raises/Throws**: None\n\n"

    # Examples
    examples = doc.get("examples", [])
    examples_md = ""
    if examples:
        examples_md = f"**Examples**:\n```{language}\n"
        for ex in examples:
            examples_md += f"{ex}"
        examples_md += "\n```\n\n"

    # Docstring
    docstring = doc.get("docstring", "").strip()
    docstring_md = f"**Docstring**:\n```{language}\n{docstring}\n```\n"

    parent_symbol = doc.get("parent_symbol", {})
    if parent_symbol:
        parent_name = parent_symbol.get("name", "")
        parent_kind = parent_symbol.get("kind", "")
        parent_path = parent_symbol.get("path", "")
        parent = f"\n**Parent Symbol**: {parent_kind} `{parent_name} at {parent_path}`\n"
    else:
        parent = ""

    places_used_json = doc.get("places_used", [])

    if places_used_json:
        places_used = "\n\n## Places where this symbol is used:\n"
        for ref in places_used_json:
            places_used += f"- [{ref['name']}]({ref['path']})\n"
    else:
        places_used = "\n\n## Places where this symbol is used:\nNone\n"

    # Called symbols
    called_symbols_json = doc.get("called_symbols", [])
    if called_symbols_json:
        called_symbols = f"\n\n## Called symbols in this {doc.get('kind', '')}:\n"
        for ref in called_symbols_json:
            called_symbols += f"- [{ref['name']}]({ref['path']})\n"
    else:
        called_symbols = f"\n\n## Called symbols in this {doc.get('kind', '')}:\nNone\n"

    # Combine all sections
    markdown = (
        header +
        summary +
        description +
        params_md +
        returns_md +
        raises_md +
        examples_md +
        docstring_md +
        parent +
        places_used +
        called_symbols
    )

    return markdown

async def safe_document_symbol_json(llm, symbol, project_context=None, show_cli_progress=True, max_retries=2):
    """
    Try to get valid JSON documentation from the LLM, retrying if necessary.
    """
    for attempt in range(max_retries):
        try:
            json_doc = await document_symbol_json(llm, symbol, project_context, show_cli_progress)
            # Test if doc is a dict (parsed JSON)
            if isinstance(json_doc, dict):
                try:
                    json_doc = normalize_json_doc(json_doc)
                    return json_doc
                except Exception as e:
                    logger.error(f"Error normalizing JSON doc: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {symbol.name}: {e}")
    # If all attempts fail, raise
    raise Exception(f"Failed to get valid JSON documentation for {symbol.name} after {max_retries} attempts.")

def normalize_json_doc(json_doc: dict) -> dict:
    """
    Normalize the LLM JSON output so all fields have the expected types.
    """
    try:
        # Normalize 'returns'
        returns = json_doc.get("returns")
        if isinstance(returns, str):
            json_doc["returns"] = {"type": "", "description": returns}
        elif returns is None or not isinstance(returns, dict):
            json_doc["returns"] = {"type": "", "description": ""}

        # Normalize 'parameters'
        parameters = json_doc.get("parameters")
        if not isinstance(parameters, list):
            json_doc["parameters"] = []

        # Normalize 'raises'
        raises = json_doc.get("raises")
        if not isinstance(raises, list):
            json_doc["raises"] = []

        # Normalize 'examples'
        examples = json_doc.get("examples")
        if not isinstance(examples, list):
            json_doc["examples"] = []

        # Normalize 'parent_symbol'
        parent_symbol = json_doc.get("parent_symbol")
        if parent_symbol is None:
            json_doc["parent_symbol"] = {}

        # Normalize 'places_used'
        places_used = json_doc.get("places_used")
        if not isinstance(places_used, list):
            json_doc["places_used"] = []

        # Normalize 'called_symbols'
        called_symbols = json_doc.get("called_symbols")
        if not isinstance(called_symbols, list):
            json_doc["called_symbols"] = []
        return json_doc
    except Exception as e:
        logger.error(f"Error normalizing JSON doc: {e}")
        raise e
