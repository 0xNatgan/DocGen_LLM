# DocGen_LLM
[![MIT licensed][mit-badge]][mit-url]

**AI-powered Project Documentation Generator**

---

## Overview

`DocGen_LLM` is a command-line tool that automates the extraction and generation of high-quality documentation for code projects. It leverages Language Server Protocol (LSP) servers and Large Language Models (LLMs) to analyze source code, extract structure and symbols, and generate detailed, context-aware documentation in Markdown and other formats.
Thanks to the use of LSP servers the tool is language agnostic and capable of exploiting languages servers trough docker.


This project was made during an internship at gertrude(saem) and still does have some issue and bugs that will maybe be resolved feel free to add your own contributions.

---

## Features

- **Multi-language Support:** Python, JavaScript, TypeScript, Java, Go, Rust, C++, C#, as long as a language server exists.
- **LSP Integration:** Uses language servers for accurate symbol and reference extraction.
- **LLM-powered Documentation:** Generates summaries, docstrings, and detailed documentation using locals or onlines LLMs (e.g., Ollama, Qwen, Claude).
- **Docker Support:** Is able to run language servers in Docker containers for isolation and reproducibility.
- **Customizable Output:** Save documentation as Markdown files, JSON, or plain text.
- **Project Context Awareness:** Incorporate project-specific context for more relevant documentation.
- **CLI Interface:** Easy-to-use command-line interface with multiple commands and options.

---

## Installation

create docker build with the following command:

```sh
#From the root of the project
#  - Windows
docker build --no-cache -f .\src\docker\tcl.Dockerfile -t tcl-lsp:latest .
#  - Linux
docker build --no-cache -f ./src/docker/tcl.Dockerfile -t tcl-lsp:latest .
```

### Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/) for dependency management

# Needed in some cases:

- Docker (for dockerised LSP servers)
- Node.js to install certains lsp servers in local

### Setup

Clone the repository and install dependencies:

```sh
git clone https://https://github.com/0xNatgan/DocGen_LLM
cd DocGen_LLM
poetry install
```

---

### Usage:

```sh
    Usage: docgen run [OPTIONS] PROJECT_PATH

    Extract and document the project (full pipeline).

    Options:
    -u         Run with Docker (If you don't want to install the server).
    -oj PATH   Output file to save the project structure as JSON.
    -doc PATH  Output directory to save generated documentation files.
    -d         Enable debug logging.
    -m TEXT    LLM model to use for documentation generation.
    -c FILE    Context for the project to be documented.
```

### CLI Commands

```sh
poetry run docgen run <project_path> 

```

#### Full Documentation Pipeline

Extract, analyze, and generate documentation for a project:

```sh
poetry run docgen run <project_path> [OPTIONS]
```

**Options:**
- `-u, --use-docker` &nbsp;&nbsp;&nbsp;&nbsp;Run LSP servers in Docker containers
- `-oj, --output-file` &nbsp;&nbsp;&nbsp;&nbsp;Output file for project structure (JSON)
- `-doc, --output-docs` &nbsp;&nbsp;&nbsp;&nbsp;Directory to save generated documentation
- `-d, --debug` &nbsp;&nbsp;&nbsp;&nbsp;Enable debug logging
- `-m, --llm-model` &nbsp;&nbsp;&nbsp;&nbsp;LLM model to use (default: "ollama qwen3:1.7b")
- `-c, --project-context` &nbsp;&nbsp;&nbsp;&nbsp;Path to a file with project context

**Example:**

```sh
poetry run gen_docai run ./src -doc ./docs/src_documentation -m "ollama qwen3:1.7b"
```

---

## Project Structure

```
src/
  cli.py
  main.py
  extraction/
    file_extractor.py
    ...
  llm/
    LLM_documentation.py
    llm_template.json
  ...
docs/
  <generated documentation>
test-projects/
  <sample projects for testing>
```

---

## Configuration

- **LSP Servers:** Configured in `src/extraction/extract_config/lsp_configs.json` (need some work)
- **LLM Templates:** Customizable docstring templates in `src/llm/llm_template.json`

---

## Extending

- Add new language support by updating `lsp_configs.json` and providing LSP server details.
- Customize docstring and documentation templates in `llm_template.json`.

---


### Run Locally

```sh
poetry shell
python src/cli.py --help
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Contributing

Contributions are welcome! Please open issues or submit pull requests for bug fixes, new features, or improvements.

---

## Acknowledgements

- [Ollama](https://ollama.com/) for LLM integration
- [Pyright](https://github.com/microsoft/pyright) and other LSP servers
- [Click](https://click.palletsprojects.com/) for CLI framework

---

## Contact

For questions or support, open an issue or contact [Natgan](mailto:Natgan@git.com).
