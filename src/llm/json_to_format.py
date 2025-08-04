from enum import Enum
import json
from typing import Callable, Dict

# --- Define your output formats ---
class OutputFormat(Enum):
    MARKDOWN = ("markdown", ".md")
    HTML = ("html", ".html")
    RST = ("rst", ".rst")
    JSON = ("json", ".json")

    @property
    def ext(self):
        return self.value[1]

    @property
    def name_str(self):
        return self.value[0]

def json_doc_to_markdown(doc: dict) -> str:
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
    language = doc.get("language", "unknown")
    # Header
    header = f"# {doc.get('kind', '')} `{doc.get('name', '')}`\n\n"

    # Summary
    summary = f"**Summary**: {doc.get('summary', '').strip()}\n\n"

    # Description
    description = f"**Description**: {doc.get('description', '').strip()}\n\n"

    # Parameters
    params_md = ""
    parameters = doc.get("parameters", [])
    if parameters:
        params_md = "**Parameters**:\n\n"
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
            examples_md += f"{ex}\n"
        examples_md += "```\n\n"

    extended_description = doc.get("extended_description", "")
    if extended_description:
        docstring_md = f"**Complete description**:\n{extended_description}\n\n"
    else:
        docstring_md = ""

    parent_symbol = doc.get("parent_symbol", {})
    if parent_symbol:
        parent_name = parent_symbol.get("name", "")
        parent_kind = parent_symbol.get("kind", "")
        parent_path = parent_symbol.get("path", "")
        parent = f"\n**Parent Symbol**:\n {parent_kind} `{parent_name} at {parent_path}`\n"
    else:
        parent = ""

    places_used_json = doc.get("places_used", [])

    if places_used_json:
        places_used = "\n**Places where this symbol is used:**\n\n"
        for ref in places_used_json:
            places_used += f"- [{ref['name']}]({ref['path']})\n"
    else:
        places_used = "\n**Places where this symbol is used:**\n\nNone\n"

    # Called symbols
    called_symbols_json = doc.get("called_symbols", [])
    if called_symbols_json:
        called_symbols = f"\n**Called symbols in this {doc.get('kind', '')}:**\n\n"
        for ref in called_symbols_json:
            called_symbols += f"- [{ref['name']}]({ref['path']})\n"
    else:
        called_symbols = f"\n**Called symbols in this {doc.get('kind', '')}:**\n\nNone\n"

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
    
def json_doc_to_html(doc: dict) -> str:
    """
    Convert a documentation dictionary (from LLM JSON output) to an HTML documentation page.

    Args:
        doc: The documentation dictionary from the LLM.

    Returns:
        HTML string.
    """
    # Header
    symbol_kind = doc.get("kind", "")
    symbol_name = doc.get("name", "")
    header = f"<h2>{symbol_kind} <code>{symbol_name}</code></h2>\n"

    # Summary
    summary = f"<strong>Summary:</strong> {doc.get('summary', '').strip()}<br><br>\n"

    # Description
    description = f"<strong>Description:</strong> {doc.get('description', '').strip()}<br><br>\n"

    # Parameters
    parameters = doc.get("parameters", [])
    if parameters:
        params_html = "<strong>Parameters:</strong><ul>\n"
        for param in parameters:
            pname = param.get("name", "")
            ptype = param.get("type", "")
            pdesc = param.get("description", "")
            params_html += f"<li><code>{pname} ({ptype})</code>: {pdesc}</li>\n"
        params_html += '</ul>\n'
    else:
        params_html = "<strong>Parameters:</strong> None<br><br>\n"

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        returns_html = f"<strong>Returns:</strong> {returns.get('description', '')} (<code>{returns.get('type', '')}</code>)<br><br>\n"
    else:
        returns_html = ""

    # Raises
    raises = doc.get("raises", [])
    if raises:
        raises_html = "<strong>Raises/Throws:</strong><ul>\n"
        for exc in raises:
            etype = exc.get("type", "")
            edesc = exc.get("description", "")
            raises_html += f"<li><code>{etype}</code>: {edesc}</li>\n"
        raises_html += '</ul>\n'
    else:
        raises_html = "<strong>Raises/Throws:</strong> None<br><br>\n"

    # Examples
    examples = doc.get("examples", [])
    language = doc.get("language", "python")
    if examples:
        examples_html = f"<strong>Examples:</strong><pre><code class=\"language-{language}\">\n"
        for ex in examples:
            examples_html += f"{ex}\n"
        examples_html += "</code></pre>\n"
    else:
        examples_html = ""

    # Docstring
    docstring = doc.get("docstring", "").strip()
    docstring_html = f"<strong>Docstring:</strong><pre><code class=\"language-{language}\">{docstring}</code></pre>\n"

    # Parent symbol
    parent_symbol = doc.get("parent_symbol", {})
    if parent_symbol:
        parent_name = parent_symbol.get("name", "")
        parent_kind = parent_symbol.get("kind", "")
        parent_path = parent_symbol.get("path", "")
        parent_html = f"<br><strong>Parent Symbol:</strong> {parent_kind} <code>{parent_name} at {parent_path}</code><br>\n"
    else:
        parent_html = ""

    # Places used
    places_used_json = doc.get("places_used", [])
    if places_used_json:
        places_used_html = "<h3>Places where this symbol is used:</h3><ul>\n"
        for ref in places_used_json:
            places_used_html += f"<li><a href=\"{ref['path']}\">{ref['name']}</a></li>\n"
        places_used_html += "</ul>\n"
    else:
        places_used_html = "<h3>Places where this symbol is used:</h3>None<br>\n"

    # Called symbols
    called_symbols_json = doc.get("called_symbols", [])
    if called_symbols_json:
        called_symbols_html = f"<h3>Called symbols in this {doc.get('kind', '')}:</h3><ul>\n"
        for ref in called_symbols_json:
            called_symbols_html += f"<li><a href=\"{ref['path']}\">{ref['name']}</a></li>\n"
        called_symbols_html += "</ul>\n"
    else:
        called_symbols_html = f"<h3>Called symbols in this {doc.get('kind', '')}:</h3>None<br>\n"

    # Combine all sections
    html = (
        header +
        summary +
        description +
        params_html +
        returns_html +
        raises_html +
        examples_html +
        docstring_html +
        parent_html +
        places_used_html +
        called_symbols_html
    )

    return html  

def json_doc_to_rst(doc: dict) -> str:
    """
    Convert a documentation dictionary (from LLM JSON output) to a reStructuredText documentation page.

    Args:
        doc: The documentation dictionary from the LLM.

    Returns:
        RST string.
    """
    symbol_kind = doc.get("kind", "")
    symbol_name = doc.get("name", "")
    header = f"{symbol_kind} ``{symbol_name}``\n{'=' * (len(symbol_kind) + len(symbol_name) + 3)}\n\n"

    summary = f"**Summary:** {doc.get('summary', '').strip()}\n\n"
    description = f"**Description:** {doc.get('description', '').strip()}\n\n"

    # Parameters
    parameters = doc.get("parameters", [])
    if parameters:
        params_rst = "**Parameters:**\n\n"
        for param in parameters:
            pname = param.get("name", "")
            ptype = param.get("type", "")
            pdesc = param.get("description", "")
            params_rst += f"- ``{pname} ({ptype})``: {pdesc}\n"
        params_rst += "\n"
    else:
        params_rst = "**Parameters:** None\n\n"

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        returns_rst = f"**Returns:** {returns.get('description', '')} (``{returns.get('type', '')}``)\n\n"
    else:
        returns_rst = ""

    # Raises
    raises = doc.get("raises", [])
    if raises:
        raises_rst = "**Raises/Throws:**\n\n"
        for exc in raises:
            etype = exc.get("type", "")
            edesc = exc.get("description", "")
            raises_rst += f"- ``{etype}``: {edesc}\n"
        raises_rst += "\n"
    else:
        raises_rst = "**Raises/Throws:** None\n\n"

    # Examples
    examples = doc.get("examples", [])
    language = doc.get("language", "python")
    if examples:
        examples_rst = f"**Examples:**\n\n.. code-block:: {language}\n\n"
        for ex in examples:
            examples_rst += f"    {ex}\n"
        examples_rst += "\n"
    else:
        examples_rst = ""

    # Docstring
    docstring = doc.get("docstring", "").strip()
    docstring_rst = f"**Docstring:**\n\n.. code-block:: {language}\n\n"
    for line in docstring.splitlines():
        docstring_rst += f"    {line}\n"
    docstring_rst += "\n"

    # Parent symbol
    parent_symbol = doc.get("parent_symbol", {})
    if parent_symbol:
        parent_name = parent_symbol.get("name", "")
        parent_kind = parent_symbol.get("kind", "")
        parent_path = parent_symbol.get("path", "")
        parent_rst = f"\n**Parent Symbol:** {parent_kind} ``{parent_name} at {parent_path}``\n"
    else:
        parent_rst = ""

    # Places used
    places_used_json = doc.get("places_used", [])
    if places_used_json:
        places_used_rst = "\nPlaces where this symbol is used:\n\n"
        for ref in places_used_json:
            places_used_rst += f"- `{ref['name']} <{ref['path']}>`_\n"
    else:
        places_used_rst = "\nPlaces where this symbol is used:\nNone\n"

    # Called symbols
    called_symbols_json = doc.get("called_symbols", [])
    if called_symbols_json:
        called_symbols_rst = f"\nCalled symbols in this {doc.get('kind', '')}:\n\n"
        for ref in called_symbols_json:
            called_symbols_rst += f"- `{ref['name']} <{ref['path']}>`_\n"
    else:
        called_symbols_rst = f"\nCalled symbols in this {doc.get('kind', '')}:\nNone\n"

    # Combine all sections
    rst = (
        header +
        summary +
        description +
        params_rst +
        returns_rst +
        raises_rst +
        examples_rst +
        docstring_rst +
        parent_rst +
        places_used_rst +
        called_symbols_rst
    )

    return rst

def json_doc_to_json(doc: dict) -> str:
    # Just pretty-print JSON
    return json.dumps(doc, indent=2)

FORMAT_TO_FUNC = {
    OutputFormat.MARKDOWN: json_doc_to_markdown,
    OutputFormat.HTML: json_doc_to_html,
    OutputFormat.RST: json_doc_to_rst,
    OutputFormat.JSON: json_doc_to_json,
}

def convert_doc(doc: dict, format: OutputFormat = OutputFormat.MARKDOWN) -> str:
    """
    Convert a documentation dictionary to the specified format.
    
    Args:
        doc: The documentation dictionary from the LLM.
        format: The desired output format (default is Markdown).

    Returns:
        The documentation in the specified format as a string.
    """
    func = FORMAT_TO_FUNC.get(format)
    if not func:
        raise ValueError(f"Unsupported format: {format}")
    return func(doc)