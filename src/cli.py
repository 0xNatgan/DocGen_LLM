from pathlib import Path
import click
import asyncio
import logging
import json
import sys
from src.extraction import file_extractor
from src.extraction.lsp_extractor import LSP_Extractor
from src.llm import LLM_documentation
from src.logging.logging import get_logger
from src.llm.llm_client import LLMClient

logger = get_logger(__name__)

@click.group()
def cli():
    """AI Project Documentation CLI."""

@cli.command()
@click.argument('project_path', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('use_docker', '-u', is_flag=True, default=False, help="Run with Docker (for local LSP clients).")
@click.option('output_docs', '-doc', type=click.Path(), default=None, help="Output directory to save generated documentation files.")
@click.option('debug', '-d', is_flag=True, default=False, help="Enable debug logging.")
@click.option('--provider', '-p', type=click.Choice(['ollama', 'openai', 'anthropic']), default='ollama', show_default=True)
@click.option('--model', '-m', type=str, default=None, help="Model to use for documentation generation.")
@click.option('project_context', '-c', type=click.Path(exists=True, file_okay=True, dir_okay=False), default=None, help="Context for the project to be documented.")
def run(project_path, use_docker, output_docs, debug, provider, model, project_context):
    """Extract and document the project (full pipeline)."""
    log_level = logging.DEBUG if debug else logging.INFO

    # Remove all handlers associated with the root logger object (to allow reconfiguration)
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Set your custom loggers' level
    get_logger(level=log_level)
    logger.setLevel(log_level)

    async def _full():
        llm = None
        if provider == "ollama" and not model:
            models = LLMClient.get_ollama_models()
            if not models:
                click.echo("No Ollama models found or Ollama server not running.")
                sys.exit(1)
            # Show numbered list
            click.echo("Available Ollama models:")
            for idx, m in enumerate(models, 1):
                # Show only the model name, not the "ollama " prefix
                click.echo(f"{idx}: {m.split(' ', 1)[1]}")
            # Prompt for number
            choice = click.prompt(
                "Select Ollama model by number",
                type=click.IntRange(1, len(models))
            )
            selected_model = models[choice - 1].split(' ', 1)[1]
            llm_model = ("ollama", selected_model)
        else:
            if not model:
                click.echo("Model is required.")
                sys.exit(1)
            llm_model = (provider, model) if model else (provider, None)
        logging.debug("Starting full pipeline for project extraction and documentation. with debug mode: %s", debug)
        extractor = file_extractor.ProjectExtractor()
        root_folder = await extractor.extract_folder(project_path)
        lsp_extractor = LSP_Extractor(root_folder, use_docker=use_docker)
        await lsp_extractor.run_extraction()
        
        if llm_model:
            llm = LLM_documentation.LLMClient(
                provider=llm_model[0],
                model=llm_model[1] if llm_model[1] else None,
                max_tokens=2000,
                temperature=0.3,
            )
            await llm.initialize()
        documentation_success = await LLM_documentation.document_projects(
            llm=llm if llm else None,
            project=root_folder,
            output_save=output_docs if output_docs else None,
            context=project_context if project_context else None
        )
        if documentation_success:
            click.echo(f"Full pipeline completed for project: {root_folder.name}")
        else:
            click.echo(f"Documentation failed for project: {root_folder.name}")
    asyncio.run(_full())
