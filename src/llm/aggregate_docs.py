from pathlib import Path
from .json_to_format import OutputFormat

def aggregate_docs(docs_root: Path, output_file: Path, format: OutputFormat = OutputFormat.MARKDOWN):
    """
    Aggregate all documentation files in docs_root into a single file.
    """
    doc_files = sorted(docs_root.rglob(f"*{format.ext}"))
    with open(output_file, "w", encoding="utf-8") as out:
        out.write(f"# Project Documentation\n\n")
        out.write("## Table of Contents\n\n")
        for doc_file in doc_files:
            rel = doc_file.relative_to(docs_root)
            out.write(f"- [{rel.stem}](#{rel.stem.replace(' ', '-').lower()})\n")
        out.write("\n---\n\n")
        for doc_file in doc_files:
            with open(doc_file, "r", encoding="utf-8") as f:
                out.write(f.read())
                out.write("\n\n---\n\n")