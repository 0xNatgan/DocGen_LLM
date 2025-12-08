import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from .llm_client import LLMClient, LLMMessage
from .json_to_format import OutputFormat, convert_doc , FORMAT_TO_FUNC
from src.logging.logging import get_logger
from src.storage.database_call import DatabaseCall
import sys
import itertools
import re
import os
import time

# Configure logging
logging.basicConfig(level=logging.INFO) 
logger = get_logger(__name__)

# Main function to document all symbols in a project and save to DB
async def document_projects(
        llm: Optional[LLMClient],
        project: Path,
        output_save: Path,
        db: DatabaseCall,
        context: Optional[Path],
        output_format: Optional[OutputFormat] = OutputFormat.MARKDOWN,
        max_retries: int = 2
        ) -> bool:
    """
    Document all symbols in the given project folder using the provided LLM client.
    Args:
        llm (Optional[LLMClient]): The LLM client to use for documentation.
        project (FolderModel): The root folder of the project to document.
        output_save (Path): The root path to save documentation files.
        context (Optional[Path]): Optional path to a context file to provide additional information.
        db (Optional[DatabaseCall]): Optional database connection to save documentation.
        output_format (Optional[OutputFormat]): The format to save documentation files.
        max_retries (int): Maximum number of retries for documenting a symbol.
    Returns:
        bool: True if documentation was successful, False otherwise.
    """
    if not llm:
        logger.error("LLM client is not provided.")
        return False
    #initialize context text
    if context and context.exists():
        with open(context, "r", encoding='utf-8') as f:
            context_text = f.read()
    else:
        context_text = None
    
    file = {"root_path": str(project), "rel_path": None, "language": None}

    for _ in range(0, db.get_number_of_symbols_with_no_documentation()):
        symbol = db.get_next_symbol_to_document()
        print("========== Next symbol to document ===========")
        print(symbol)
        if not symbol:
            logger.info("No more symbols to document.")
            break
        else:
            symbol_info = db.get_all_info_on_symbol(symbol)
        try:

            json_doc = await safe_document_symbol_json(
                llm,
                symbol_info=symbol_info,
                project_root=project,
                project_context=context_text if context_text else None,
                show_cli_progress=True,
                max_retries=max_retries
            )
            # add summary + full JSON doc to DB
            db.add_summary_to_symbol(symbol, json_doc.get('summary', '') or '')
            db.add_documentation_to_symbol(symbol, json_doc)
            print(db.get_documentation_for_symbol(symbol))  # to verify saving worked
            logger.info(f"Saved documentation for symbol {symbol_info.get('name', 'unknown')} to DB (id: {symbol})")
        except Exception as e:
            logger.error(f"Failed to document symbol {symbol_info.get('name', 'unknown')} (id: {symbol}): {e}")
            continue
    logger.debug("Completed documenting all symbols.")
    return True

#LLM CALL : Generate documentation for a single symbol using JSON schema for output 
async def document_symbol_json(
    llm: LLMClient,
    symbol_info: dict,
    project_root: Path,
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
        called_symbols_info = symbol_info.get("called_symbols_json", None)
        called_symbol_text = ""
        if called_symbols_info != []:
            for called_symbol in called_symbols_info:
                called_symbol_text += f"- {called_symbol['kind']} {called_symbol['name']}",
                f" summary : {called_symbol.get('summary', 'None')}" if called_symbol.get('summary') != None else f" docstring : {called_symbols_info.get('docstring', 'None')}\n" if called_symbols_info else ""
                                  
        file_path = symbol_info.get("file_path", None)
        if not file_path:
            raise Exception(f"File path not found for symbol {symbol_info.get('name')}")
        file_path = Path(project_root) / file_path

        called_symbol_text = called_symbols_info

        # Get existing docstring if available
        existing_docstring = symbol_info.get("docstring", None)

        # Determine programming language
        language = symbol_info.get("language_name", "unknown")

        # Prepare project context string
        project_context_str = f"\nProject Context:\n{project_context}\n" if project_context else ""

        # JSON schema for the documentation
        doc_schema = {
            "summary": "string (1-2 lines)",
            "description": "string (5-8 lines)",
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
            "Extended Explications": "string"
        }

        # Build messages for LLM
        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"You are an expert technical documentation writer specializing in {language} code documentation.\n"
                    f"Your task is to generate documentation for the following symbol as a single JSON object. "
                    f"All fields must be present. Do not include any text outside the JSON object and make sure the output is a valid JSON OBJECT.\n"
                    f"Follow these strict guidelines:\n"
                    f"- Use clear, concise language\n"
                    f"- Include a summary, description, parameters, return values as type and examples of call or use of this {symbol_info.get("kind")}\n"
                    f"- For the `examples` field, return a list of code snippets of usage of this {symbol_info.get("kind")} with call, and as comment process and output. Each line should be put in a different string of the list.\n"
                    f"- 'parameters' elements should be name: the name of the parameter, type: the type of the parameter, description: a brief description of the parameter.\n"
                    f"- If necessary and applicable, include a section for Extended Explications\n"
                    f"- Include all relevant information from the context\n"
                    f"- IMPORTANT: Ensure the JSON is properly formatted\n"
                )
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Document this {language} {symbol_info.get("kind")}:\n"
                    f"Symbol Information:\n"
                    f"- Name: {symbol_info.get("name")}\n"
                    f"- Type: {symbol_info.get("kind")}\n"
                    f"- Language: {language}\n\n"
                    f" - Parent symbol : {symbol_info.get("parent_kind")} {symbol_info.get("parent_name")}\n" if symbol_info.get("parent_name") else ""
                    f"Source Code:\n"
                    f"{extract_symbol_source_code(symbol_info.get("range"), file_path)}\n\n"
                    f"Context Information:\n"
                    f"- Existing docstring: {existing_docstring if existing_docstring else 'None'}\n"
                    f"- Called symbols: {called_symbols_info if called_symbols_info else 'None'}\n"
                    f"{project_context_str}\n"
                    f"Generate documentation as a single JSON object following the schema above."
                )
            ),
            LLMMessage(
                role="assistant",
                content=f"Expected output format: {json.dumps(doc_schema, indent=2)}\n"
            )
        ]

        start = time.time()
        full_response = ""
        full_response = await stream_with_timeout(llm, messages, timeout=500, show_cli_progress=show_cli_progress)

        # Remove <think>...</think> block if present (some Ollama thinking model include the thinking part (might change with args to query in the future))
        full_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL)
        # Parse the JSON output
        try:
            doc_json = json.loads(full_response)
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON output for {symbol_info.get("name")}: {e}\nRaw output:\n{full_response}")
            raise Exception(f"Failed to parse LLM JSON output for {symbol_info.get("name")}: {e}")

        logger.info(f"📄 Generated JSON documentation for {symbol_info.get("name")} in {time.time() - start} seconds")
        return doc_json 

    except Exception as e:
        logger.error(f"❌ Failed to document {symbol_info.get("name")}: {e}")
        
        raise Exception(f"Failed to document {symbol_info.get("name")}: {e}")

#Verify that the result is proper JSON and not broken.
async def safe_document_symbol_json(llm, symbol_info, project_root, project_context=None, show_cli_progress=True, max_retries=2):
    """
    Try to get valid JSON documentation from the LLM, retrying if necessary.
    """
    for attempt in range(max_retries):
        try:
            json_doc = await document_symbol_json(llm, symbol_info, project_root, project_context, show_cli_progress)
            # Test if doc is a dict (parsed JSON)
            if isinstance(json_doc, dict):
                try:
                    json_doc = normalize_json_doc(json_doc)
                    return json_doc
                except Exception as e:
                    logger.error(f"Error normalizing JSON doc: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {symbol_info["name"]}: {e}")
    # If all attempts fail, raise
    raise Exception(f"Failed to get valid JSON documentation for {symbol_info["name"]} after {max_retries} attempts. \n output was: {json_doc if 'json_doc' in locals() else 'No JSON output'}")
      
#Doc Generation from JSON (will be deleted/moved later)     
async def generate_docs_from_db(db: DatabaseCall, docs_root: Path, output_format: OutputFormat, project_root: Optional[Path] = None):
    """
    Recreate project documentation files from saved documentation JSON stored in DB.
    """
    documented = db.get_documented_symbols()
    for rec in documented:
        symbol_id = rec["id"]
        json_doc = rec["documentation"]
        # Try to recover the symbol object to compute the mirrored directory path
        try:
            symbol_models = db.make_model_from_db(symbol_id)
            symbol_obj = symbol_models[0] if symbol_models else None
        except Exception:
            symbol_obj = None

        if not json_doc:
            logger.warning(f"No documentation JSON for symbol id {symbol_id}")
            continue
        # Optionally recompute relative paths for nav links using the symbol_obj when needed
        # For now, leave JSON fields as-is and convert
        doc_text = convert_doc(doc=json_doc, format=output_format)
        # Determine path; if a symbol_obj exists, use existing method; otherwise fall back
        if symbol_obj:
            out_file = get_symbol_file_path(symbol_obj, docs_root, project_root)
        else:
            # fallback: use name in JSON doc
            safe_name = "".join(c for c in json_doc.get('name', f"symbol_{symbol_id}") if c.isalnum() or c in '._-').rstrip()
            out_file = docs_root / f"{safe_name}.md"

        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding='utf-8') as f:
                f.write(doc_text)
            logger.info(f"Saved doc from DB for symbol id {symbol_id} -> {out_file}")
        except Exception as e:
            logger.error(f"Failed to save doc for symbol id {symbol_id}: {e}")

#Normalize JSON doc fields to expected types
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
        else:
            for param in parameters:
                if isinstance(param, str):
                    # If it's a string, convert to dict with empty type and description
                    json_doc["parameters"] = [{"name": param, "type": "", "description": ""}]
                elif not isinstance(param, dict):
                    # If it's not a dict, reset to empty list
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

#Extract source code for a symbol using its range information
def extract_symbol_source_code(range: dict, file_path) -> str:
    """
    Extract the source code for a symbol from its file using its range.
    Returns the code as a string, or an empty string if not found.

    Note: file_path must be a Path or string pointing to the file containing the symbol.
    """
    # Normalize file_path to Path
    try:
        file_path = Path(file_path)
    except Exception:
        return ''

    # If the provided path is relative, resolve to absolute where possible
    try:
        if not file_path.is_absolute():
            file_path = file_path.resolve()
    except Exception:
        # leave as-is if resolve fails
        pass

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return ''
    except Exception as e:
        logger.error(f"Error opening file {file_path}: {e}")
        return ''

    # Expect LSP-like range dict: {'start': {'line': n, 'character': m}, 'end': {...}}
    if not range or not isinstance(range, dict):
        # no range -> return full file
        return ''.join(lines)

    start = range.get('start') or {}
    end = range.get('end') or {}

    # Lines can be None; default to file bounds
    start_line = start.get('line')
    end_line = end.get('line')

    # If lines are missing, return full file
    if start_line is None or end_line is None:
        return ''.join(lines)

    # Ensure integers and handle 0/1-based ambiguity: assume 0-based if either 0 present
    try:
        s_line = int(start_line)
        e_line = int(end_line)
    except Exception:
        return ''.join(lines)

    # If values look 1-based (min >= 1) convert to 0-based
    if s_line >= 1 and e_line >= 1 and s_line <= e_line:
        s_idx = max(s_line - 1, 0)
        e_idx = max(e_line - 1, s_idx)
    else:
        s_idx = max(s_line, 0)
        e_idx = max(e_line, s_idx)

    # Clip to available lines
    s_idx = min(s_idx, len(lines) - 1) if lines else 0
    e_idx = min(e_idx, len(lines) - 1) if lines else 0

    code_lines = lines[s_idx:e_idx + 1]
    if not code_lines:
        return ''

    # Adjust by characters if provided
    start_char = start.get('character', 0) or 0
    end_char = end.get('character', None)

    try:
        if s_idx == e_idx:
            line = code_lines[0]
            if end_char is None:
                code_lines[0] = line[start_char:]
            else:
                code_lines[0] = line[start_char:end_char]
        else:
            # first line slice
            if start_char and start_char < len(code_lines[0]):
                code_lines[0] = code_lines[0][start_char:]
            # last line slice
            if end_char is not None and end_char <= len(code_lines[-1]):
                code_lines[-1] = code_lines[-1][:end_char]
    except Exception:
        # If slicing fails, just return the raw lines
        pass

    return ''.join(code_lines)
    
# Async function to stream LLM responses with timeout and CLI progress display
async def stream_with_timeout(llm, messages, timeout=500, show_cli_progress=True):
    """Stream LLM responses with a timeout and optional CLI progress display."""
    start_time = time.time()
    full_response = ""
    spinner = itertools.cycle([
        "( ●    )", "(  ●   )", "(   ●  )", "(    ● )", "(     ●)",
        "(    ● )", "(   ●  )", "(  ●   )", "( ●    )", "(●     )"
    ])
    # Extract system, user, assistant from messages
    system_prompt = None
    user_prompt = None
    assistant_prompt = None
    for msg in messages:
        if msg.role == "system":
            system_prompt = msg.content
        elif msg.role == "user":
            user_prompt = msg.content
        elif msg.role == "assistant":
            assistant_prompt = msg.content

    async def run_llm():
        nonlocal full_response
        response = await llm.generate(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            assistant_prompt=assistant_prompt
        )
        full_response += response
        logger.info(f"LLM response generated: {len(full_response)} characters")
        logger.info(f"LLM response :\n{full_response} ")

    llm_task = asyncio.create_task(run_llm())

    try:
        while not llm_task.done():
            if show_cli_progress:
                elapsed = int(time.time() - start_time)
                sys.stdout.write(
                    f"\rGenerating documentation {next(spinner)} | Elapsed: {elapsed // 60:02d}:{elapsed % 60:02d}"
                )
                sys.stdout.flush()
            await asyncio.sleep(0.1)
        await asyncio.wait_for(llm_task, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("LLM streaming timed out after {} seconds".format(timeout))
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
        raise Exception(f"LLM streaming timed out after {timeout} seconds")
    if show_cli_progress:
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
    return full_response
