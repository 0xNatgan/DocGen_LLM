# DocGen_LLM

[![Open source Multi-AI Agent orchestration framework](logo.svg)](https://github.com/0xNatgan/DocGen_LLM)

## AI-powered Project Documentation Generator

`DocGen_LLM` is a command-line tool that automates the extraction and generation of high-quality documentation for code projects. It leverages Language Server Protocol (LSP) servers and Large Language Models (LLMs) to analyze source code, extract structure and symbols, and generate detailed, context-aware documentation in Markdown and other formats.
Thanks to the use of LSP servers the tool is language agnostic and capable of exploiting languages servers trough docker or in local environments.


This project was made during an internship at [gertrude](https://gertrude.com) and still does have some issue and bugs that will maybe be resolved feel free to add your own contributions.

---

## Features

- **Multi-language Support:** Python, JavaScript, TypeScript, Java, Go, Rust, C++, C#, Fortran, TCL - supports any language with an LSP server.
- **LSP Integration:** Uses language servers for accurate symbol and reference extraction - runs locally by default.
- **LLM-powered Documentation:** Generates summaries, docstrings, and detailed documentation using local or online LLMs (e.g., Ollama, OpenAI, Anthropic).
- **Easy Setup:** Works with locally installed LSP servers - no Docker required (though Docker is optionally supported).
- **Customizable Output:** Save documentation as Markdown files, JSON, or plain text.
- **Project Context Awareness:** Incorporate project-specific context for more relevant documentation.
- **CLI Interface:** Easy-to-use command-line interface with multiple commands and options.


## Installation

### Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/) for dependency management
- LSP servers for languages you want to document (see below)

### Setup

1. Clone the repository and install dependencies:

```sh
git clone https://github.com/0xNatgan/DocGen_LLM
cd DocGen_LLM
poetry install
```

2. Install LSP servers for your target languages:

**Python:**
```sh
npm install -g pyright
```

**JavaScript/TypeScript:**
```sh
npm install -g typescript-language-server typescript
```

**Go:**
```sh
go install golang.org/x/tools/gopls@latest
```

**Rust:**
```sh
rustup component add rust-analyzer
```

**C/C++:**
```sh
# Ubuntu/Debian
apt install clangd-12
# macOS
brew install llvm
```

**C#:**
```sh
dotnet tool install -g csharp-ls
```

**Fortran:**
```sh
pip install fortls
```

**Java:**
```sh
npm install -g jdtls
```

### Optional: Docker Support

If you prefer to run LSP servers in Docker containers (for isolation), you can build Docker images:

```sh
# Example for TCL LSP
docker build --no-cache -f tcl.Dockerfile -t tcl-lsp:latest .
```

Then use the `--use-docker` flag when running the tool.

---

### Usage

```sh
poetry run docgen run <project_path> [OPTIONS]
```

**Options:**
- `--use-docker, -d` &nbsp;&nbsp;&nbsp;&nbsp;Run LSP servers in Docker containers (optional, requires Docker images)
- `--output-docs, -od PATH` &nbsp;&nbsp;&nbsp;&nbsp;Directory to save generated documentation
- `--debug` &nbsp;&nbsp;&nbsp;&nbsp;Enable debug logging
- `--provider, -p` &nbsp;&nbsp;&nbsp;&nbsp;LLM provider: ollama, openai, or anthropic (default: ollama)
- `--model, -m TEXT` &nbsp;&nbsp;&nbsp;&nbsp;LLM model to use
- `--project-context, -c FILE` &nbsp;&nbsp;&nbsp;&nbsp;Path to a file with project context

**Example:**

```sh
# Basic usage (runs locally, no Docker needed)
poetry run docgen run ./my-project --output-docs ./docs

# With specific LLM model
poetry run docgen run ./my-project -p ollama -m qwen2.5-coder:7b -od ./docs

# Using Docker for LSP servers (optional)
poetry run docgen run ./my-project --use-docker -od ./docs

# With project context for better documentation
poetry run docgen run ./my-project -c project-context.txt -od ./docs
```

---

## How It Works

1. **File Extraction**: Scans your project directory and identifies files by language
2. **LSP Analysis**: Connects to language servers to extract symbols, definitions, and references
3. **Documentation Generation**: Uses LLMs to generate human-readable documentation
4. **Output**: Saves documentation in your preferred format (Markdown, JSON, etc.)

### LSP Server Detection

The tool automatically detects which languages are in your project and attempts to start the appropriate LSP servers. If a server is not installed, you'll see a helpful message with installation instructions.

**Standalone Mode (Default):**
- Runs LSP servers as local processes
- Faster startup, lower overhead
- Requires LSP servers to be installed on your system

**Docker Mode (Optional):**
- Runs LSP servers in containers
- Provides isolation and consistent environments
- Requires Docker images to be built first

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
