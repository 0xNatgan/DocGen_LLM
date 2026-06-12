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
    """
    if not llm:
        logger.error("LLM client is not provided.")
        return False
    
    # Initialize context text
    if context and context.exists():
        with open(context, "r", encoding='utf-8') as f:
            context_text = f.read()
    else:
        context_text = None
    
    # Get total count
    total_symbols = db.get_number_of_symbols_with_no_documentation()
    logger.info(f"🚀 Starting documentation of {total_symbols} symbols...")
    print(f"\n{'='*60}")
    print(f"Total symbols to document: {total_symbols}")
    print(f"{'='*60}\n")
    
    documented_count = 0
    failed_count = 0
    total_time_start = time.time()

    while True:
        symbol = db.get_next_symbol_to_document()
        
        if not symbol:
            logger.info("✅ No more symbols to document.")
            break
        
        # Extract id from dict or use int directly
        if isinstance(symbol, dict):
            symbol_id = symbol.get("id") or symbol.get("symbol_id")
            calls = symbol.get("calls", 0)
        else:
            symbol_id = symbol
            calls = 0
        
        if not symbol_id:
            logger.warning(f"Invalid symbol returned: {symbol}")
            continue
            
        symbol_info = db.get_all_info_on_symbol(symbol_id)
        
        if not symbol_info:
            logger.warning(f"No symbol info found for id {symbol_id}")
            continue
        
        symbol_name = symbol_info.get('name', 'unknown')
        progress = f"[{documented_count + failed_count + 1}/{total_symbols}]"
        
        symbol_start_time = time.time()
        print(f"{progress} 📝 Processing: {symbol_name} (calls: {calls})...")
        logger.info(f"{progress} Processing symbol: {symbol_name} (id: {symbol_id}, calls: {calls})")
            
        try:
            json_doc = await safe_document_symbol_json(
                llm,
                symbol_info=symbol_info,
                project_root=project,
                project_context=context_text if context_text else None,
                show_cli_progress=True,
                max_retries=max_retries
            )
            
            # Add summary to DB
            try:
                summary = json_doc.get('summary', '')
                db.add_summary_to_symbol(symbol_id, summary)
                logger.debug(f"Added summary for {symbol_name}")
            except Exception as e:
                logger.error(f"Failed to add summary for {symbol_name}: {e}")
            
            # Add full documentation to DB
            try:
                db.add_documentation_to_symbol(symbol_id, json_doc)
                symbol_elapsed = time.time() - symbol_start_time
                print(f"✅ {symbol_name} documented successfully ({symbol_elapsed:.2f}s)")
                logger.info(f"✅ Saved documentation for {symbol_name} to DB (id: {symbol_id}) in {symbol_elapsed:.2f}s")
                documented_count += 1
            except Exception as e:
                symbol_elapsed = time.time() - symbol_start_time
                logger.error(f"Failed to add documentation for {symbol_name}: {e}")
                failed_count += 1
                
        except Exception as e:
            symbol_elapsed = time.time() - symbol_start_time
            print(f"❌ {symbol_name} failed ({symbol_elapsed:.2f}s): {str(e)[:60]}...")
            logger.error(f"Failed to document {symbol_name} (id: {symbol_id}) after {symbol_elapsed:.2f}s: {e}")
            failed_count += 1
            continue

    # Summary
    total_elapsed = time.time() - total_time_start
    avg_time_per_symbol = total_elapsed / (documented_count + failed_count) if (documented_count + failed_count) > 0 else 0
    print(f"\n{'='*60}")
    print(f"📊 Documentation complete!")
    print(f"   ✅ Successful: {documented_count}")
    print(f"   ❌ Failed: {failed_count}")
    print(f"   📈 Total: {documented_count + failed_count}/{total_symbols}")
    print(f"   ⏱️  Total time: {total_elapsed:.2f}s ({total_elapsed//60:.0f}m {total_elapsed%60:.0f}s)")
    print(f"   ⚡ Average per symbol: {avg_time_per_symbol:.2f}s")
    print(f"{'='*60}\n")
    
    logger.info(f"Documented {documented_count}/{total_symbols} symbols successfully ({failed_count} failed) in {total_elapsed:.2f}s")
    
    # Generate file-level summaries from DB
    if output_save:
        logger.info(f"Generating file documentation summaries...")
        await document_files_from_db(llm=llm, db=db)
        
        # Actually generate the Markdown files from the DB
        logger.info(f"Exporting documented symbols to {output_save}...")
        output_save.mkdir(parents=True, exist_ok=True)
        documented = db.get_documented_symbols()
        for rec in documented:
            json_doc = rec["documentation"]
            if not json_doc:
                continue
            
            doc_text = convert_doc(doc=json_doc, format=output_format)
            
            # Simple fallback path for now
            safe_name = "".join(c for c in json_doc.get('name', f"symbol_{rec['id']}") if c.isalnum() or c in '._-').rstrip()
            out_file = output_save / f"{safe_name}.md"
            
            try:
                with open(out_file, "w", encoding='utf-8') as f:
                    f.write(doc_text)
            except Exception as e:
                logger.error(f"Failed to save doc for symbol id {rec['id']}: {e}")
                
        logger.info(f"✅ Successfully exported documentation to {output_save}")
    
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
        if called_symbols_info:
            for called_symbol in called_symbols_info:
                name = called_symbol.get('name', '')
                kind = called_symbol.get('kind', '')
                summary = called_symbol.get('summary') or called_symbol.get('docstring') or 'None'
                called_symbol_text += f"- {kind} {name}: {summary}\n"

        # called_symbol_text is now set; also keep the raw list for the prompt
        file_path = symbol_info.get("file_path", None)
        if not file_path:
            raise Exception(f"File path not found for symbol {symbol_info.get('name')}")
        file_path = Path(project_root) / file_path

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
            "Extended Explications": "string",
            "tags": ["string"]  
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
                    f"- tags sould include between 2 and 4 relevant tags for this symbol revelant means what the symbol is about and its main characteristics. Do not push over 4 tags and don't include tags if not needed\n"
                    f"- If necessary and applicable, include a section for Extended Explications\n"
                    f"- Include all relevant information from the context\n"
                    f"- IMPORTANT: Ensure the JSON is properly formatted. Do not include any escape characters that might render the JSON invalid (e.g. unescaped quotes or backslashes).\\n"
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
                    f" - Parent symbol : {symbol_info.get('parent_kind')} {symbol_info.get('parent_name')}\n" if symbol_info.get('parent_name') else ""
                    f"Source Code:\n"
                    f"{extract_symbol_source_code(symbol_info.get('range'), file_path)}\n\n"
                    f"Context Information:\n"
                    f"- Existing docstring: {existing_docstring if existing_docstring else 'None'}\n"
                    f"- Called symbols:\n{called_symbol_text if called_symbol_text else 'None'}\n"
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
        full_response = await stream_with_timeout(llm, messages, timeout=2300, show_cli_progress=show_cli_progress)

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
    """Try to get valid JSON documentation from the LLM, retrying if necessary."""
    symbol_name = symbol_info.get("name", "unknown")
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"  Attempt {attempt + 1}/{max_retries} for {symbol_name}")
            json_doc = await document_symbol_json(llm, symbol_info, project_root, project_context, show_cli_progress)
            
            if isinstance(json_doc, dict):
                json_doc = normalize_json_doc(json_doc)
                logger.debug(f"  ✓ Valid JSON received for {symbol_name}")
                return json_doc
        except Exception as e:
            logger.warning(f"  ✗ Attempt {attempt+1} failed for {symbol_name}: {str(e)[:60]}...")
    
    raise Exception(f"Failed to get valid JSON documentation for {symbol_name} after {max_retries} attempts")
      

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

        # Normalize 'tags'
        tags = json_doc.get("tags")
        if not isinstance(tags, list):
            json_doc["tags"] = []
        else:
            json_doc["tags"] = [str(tag) for tag in tags]

        # Normalize 'raises'
        raises = json_doc.get("raises")
        if not isinstance(raises, list):
            json_doc["raises"] = []

        # Normalize 'examples'
        examples = json_doc.get("examples")
        if not isinstance(examples, list):
            json_doc["examples"] = [] 
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
async def stream_with_timeout(llm, messages, timeout=2300, show_cli_progress=True):
    """Stream LLM responses with a timeout and real-time progress display."""
    start_time = time.time()
    full_response = ""
    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    
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
        try:
            response = await llm.generate(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                assistant_prompt=assistant_prompt
            )
            full_response = response
            logger.info(f"LLM response generated: {len(full_response)} characters")
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            raise

    llm_task = asyncio.create_task(run_llm())
    progress_interval = 0.5  # Update every 0.5 seconds
    last_progress_update = time.time()

    try:
        while not llm_task.done():
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Update progress display
            if current_time - last_progress_update >= progress_interval:
                spinner_char = next(spinner)
                minutes = int(elapsed) // 60
                seconds = int(elapsed) % 60
                time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
                
                if show_cli_progress:
                    sys.stdout.write(f"\r{spinner_char} Generating documentation... ({time_str})")
                    sys.stdout.flush()
                
                last_progress_update = current_time
            
            # Check if timeout exceeded
            if elapsed > timeout:
                llm_task.cancel()
                logger.error(f"LLM streaming timed out after {timeout} seconds")
                sys.stdout.write('\r' + ' ' * 80 + '\r')
                sys.stdout.flush()
                raise Exception(f"LLM streaming timed out after {timeout} seconds")
            
            await asyncio.sleep(0.1)  # Small sleep to prevent busy waiting

        # Wait for final result
        await llm_task

    except asyncio.CancelledError:
        logger.error("LLM task was cancelled")
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
        raise Exception("LLM task was cancelled")
    except Exception as e:
        llm_task.cancel()
        logger.error(f"LLM task failed: {e}")
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
        raise
    finally:
        if show_cli_progress:
            sys.stdout.write('\r' + ' ' * 80 + '\r')
            sys.stdout.flush()

    if not full_response:
        raise Exception("LLM returned empty response")
    
    return full_response

async def document_files_from_db(llm: "LLMClient", db: "DatabaseCall") -> None:
    """
    Generate a short documentation summary for each fully-documented file and
    store it in the database.

    A file is eligible when *all* its symbols have been documented (so every
    summary is available to build the file-level description).

    Args:
        llm: Initialised LLM client (used to generate the file description).
        db:  Database connection.
    """
    for file_row in db.get_undocumented_files():
        file_id = file_row[0]
        file_path = file_row[1]
        symbol_ids = db.get_symbols_in_file(file_id)

        if not symbol_ids:
            logger.info(f"No symbols in file {file_path}, skipping file documentation.")
            continue

        doc_text = "Content of the file:\n"
        for sym_id in symbol_ids:
            summary = db.get_symbol_summary(sym_id)
            doc_text += f"- {summary.get('kind')} {summary.get('name')}: {summary.get('summary')}\n"

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are an expert technical documentation writer specialising in code documentation.\n"
                    "Your task is to generate a short documentation for the following file based on the"
                    " documented symbols it contains.\n"
                    "The documentation should be 5-12 lines summarising what the file does, including a"
                    " brief mention of each function.\n"
                    "Use clear, concise language. The user will provide a summary of each symbol in the file."
                ),
            ),
            LLMMessage(role="user", content=doc_text),
        ]

        try:
            start = time.time()
            file_doc = await stream_with_timeout(llm, messages, timeout=600, show_cli_progress=True)
            elapsed = time.time() - start
            logger.info(f"📄 Generated documentation for file {file_path} in {elapsed:.2f}s")
            db.add_file_documentation(file_id, file_doc)
            logger.info(f"Saved file documentation for {file_path} (id: {file_id})")
        except Exception as e:
            logger.error(f"❌ Failed to document file {file_path}: {e}")
            continue