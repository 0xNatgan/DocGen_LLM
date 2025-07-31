from typing import Dict, Any

def json_to_docstring(doc: Dict[str, Any], language: str) -> str:
    """
    Convert LLM JSON doc to a documentation comment in the specified programming language.
    """
    match language.lower():
        case "python":
            return json_to_python_docstring(doc)
        case "java":
            return json_to_java_docstring(doc) # noqa: E99
        case "csharp":
            return json_to_csharp_docstring(doc)
        case "javascript":
            return json_to_js_docstring(doc)
        case "xml":
            return json_to_xml_docstring(doc)
        case "tcl":
            return json_to_tcl_docstring(doc)
        case "ruby":
            return json_to_ruby_docstring(doc)
        case "c":
            return json_to_c_docstring(doc)
        case "cpp":
            return json_to_c_docstring(doc)  # C++ can use similar style to C
        case "go":
            return json_to_go_docstring(doc)
        case "default":
            return default_json_to_docstring(doc)


def json_to_python_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a Python docstring (Google style).
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(summary)
        lines.append("")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(description)
        lines.append("")

    # Parameters
    parameters = doc.get("parameters", [])
    if parameters:
        lines.append("Args:")
        for param in parameters:
            pname = param.get("name", "")
            ptype = param.get("type", "")
            pdesc = param.get("description", "")
            lines.append(f"    {pname} ({ptype}): {pdesc}")
        lines.append("")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append("Returns:")
        lines.append(f"    {returns.get('type', '')}: {returns.get('description', '')}")
        lines.append("")

    # Raises
    raises = doc.get("raises", [])
    if raises:
        lines.append("Raises:")
        for exc in raises:
            etype = exc.get("type", "")
            edesc = exc.get("description", "")
            lines.append(f"    {etype}: {edesc}")
        lines.append("")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append("Examples:")
        for ex in examples:
            lines.append(f"    {ex}")
        lines.append("")

    # Join all lines into a docstring
    docstring = '"""' + "\n".join(lines).rstrip() + '\n"""'
    return docstring

def json_to_java_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a JavaDoc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"/**\n * {summary}\n *")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f" * {description}")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f" * @param {pname} {pdesc} ({ptype})")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f" * @return {returns.get('description', '')} ({returns.get('type', '')})")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f" * @throws {etype} {edesc}")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append(" * @example")
        for ex in examples:
            lines.append(f" *     {ex}")

    lines.append(" */")
    
    return "\n".join(lines)

def json_to_csharp_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a C# XML doc comment.
    """
    lines = []

    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"/// <summary>\n/// {summary}\n/// </summary>")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f"/// <remarks>\n/// {description}\n/// </remarks>")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f"/// <param name=\"{pname}\" type=\"{ptype}\">{pdesc}</param>")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f"/// <returns type=\"{returns.get('type', '')}\">{returns.get('description', '')}</returns>")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f"/// <exception type=\"{etype}\">{edesc}</exception>")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append("/// <example>")
        for ex in examples:
            lines.append(f"///     {ex}")
        lines.append("/// </example>")

    return "\n".join(lines)

def json_to_js_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a JSDoc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"/**\n * {summary}\n *")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f" * {description}")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f" * @param {pname} {pdesc} ({ptype})")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f" * @return {returns.get('description', '')} ({returns.get('type', '')})")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f" * @throws {etype} {edesc}")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append(" * @example")
        for ex in examples:
            lines.append(f" *     {ex}")

    lines.append(" */")

    return "\n".join(lines)

def json_to_xml_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to an XML doc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"<summary>{summary}</summary>")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f"<description>{description}</description>")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f"<param name=\"{pname}\" type=\"{ptype}\">{pdesc}</param>")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f"<returns type=\"{returns.get('type', '')}\">{returns.get('description', '')}</returns>")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f"<exception type=\"{etype}\">{edesc}</exception>")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append("<example>")
        for ex in examples:
            lines.append(f"  <code>{ex}</code>")
        lines.append("</example>")

    return "\n".join(lines)

def json_to_tcl_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a Tcl doc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"# {summary}")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f"# {description}")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f"# @param {pname} {ptype} - {pdesc}")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f"# @return {returns.get('type', '')} - {returns.get('description', '')}")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f"# @throws {etype} - {edesc}")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append("# @example")
        for ex in examples:
            lines.append(f"#   {ex}")

    return "\n".join(lines)

def json_to_ruby_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a Ruby doc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"# {summary}")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f"# {description}")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f"# @param {pname} [{ptype}] - {pdesc}")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f"# @return [{returns.get('type', '')}] - {returns.get('description', '')}")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f"# @raise {etype} - {edesc}")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append("# @example")
        for ex in examples:
            lines.append(f"#   {ex}")

    return "\n".join(lines)

def json_to_c_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a C doc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"/* {summary}")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f" * {description}")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f" * @param {pname} {ptype} - {pdesc}")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f" * @return {returns.get('type', '')} - {returns.get('description', '')}")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f" * @throws {etype} - {edesc}")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append(" * @example")
        for ex in examples:
            lines.append(f" *   {ex}")

    lines.append(" */")

    return "\n".join(lines)

def json_to_go_docstring(doc: Dict[str, Any]) -> str:
    """
    Convert LLM JSON doc to a Go doc comment.
    """
    lines = []
    # Summary
    summary = doc.get("summary", "").strip()
    if summary:
        lines.append(f"// {summary}")

    # Description
    description = doc.get("description", "").strip()
    if description:
        lines.append(f"// {description}")

    # Parameters
    parameters = doc.get("parameters", [])
    for param in parameters:
        pname = param.get("name", "")
        ptype = param.get("type", "")
        pdesc = param.get("description", "")
        lines.append(f"// @param {pname} {ptype} - {pdesc}")

    # Returns
    returns = doc.get("returns", {})
    if returns and (returns.get("type") or returns.get("description")):
        lines.append(f"// @return {returns.get('type', '')} - {returns.get('description', '')}")

    # Raises
    raises = doc.get("raises", [])
    for exc in raises:
        etype = exc.get("type", "")
        edesc = exc.get("description", "")
        lines.append(f"// @throws {etype} - {edesc}")

    # Examples
    examples = doc.get("examples", [])
    if examples:
        lines.append("// @example")
        for ex in examples:
            lines.append(f"//   {ex}")

    return "\n".join(lines)

def default_json_to_docstring(doc: Dict[str, Any]) -> str:
    """
    Fallback function for converting LLM JSON doc to a docstring.
    Uses line comment at the start of each line.
    """
    lines = []
    for key, value in doc.items():
        if isinstance(value, list):
            value = ", ".join(map(str, value))
        lines.append(f"# {key}: {value}")
    return "\n".join(lines)
    