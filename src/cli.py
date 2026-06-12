from pathlib import Path
import click
import asyncio
import logging
import sys
from src.extraction import file_extractor
from src.extraction.lsp_extractor import LSP_Extractor
from src.llm import LLM_documentation_db
from src.logging.logging import get_logger
from src.llm.llm_client import LLMClient
from src.storage.database import from_obj_to_sql
from src.storage.database_call import DatabaseCall

logger = get_logger(__name__)


@click.group()
def cli():
    """AI Project Documentation CLI."""


@cli.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option(
    "--no-docker", "-nd", "use_docker",
    flag_value=False, default=True,
    help="Run LSP servers locally instead of in Docker (may need to adapt server in config file).",
)
@click.option(
    "--no-references", "-nr", "no_references",
    is_flag=True, default=False,
    help="Skip call-graph reference extraction (faster, but LLM gets less context).",
)
@click.option(
    "--output-docs", "-od", "output_docs",
    type=click.Path(), default=None,
    help="Output directory to save generated documentation files.",
)
@click.option(
    "--debug", "-d", is_flag=True, default=False,
    help="Enable debug logging.",
)
@click.option(
    "--provider", "-p",
    type=click.Choice(["ollama", "openai", "anthropic"]),
    default="ollama", show_default=True,
)
@click.option(
    "--model", "-m", type=str, default=None,
    help="Model to use for documentation generation.",
)
@click.option(
    "--project-context", "-c", "project_context",
    type=click.Path(exists=True, file_okay=True, dir_okay=False), default=None,
    help="Text file containing context for the project to be documented.",
)
def run(project_path, use_docker, no_references, output_docs, debug, provider, model, project_context):
    """Create documentation for the given project."""
    log_level = logging.DEBUG if debug else logging.INFO

    # Reconfigure root logger (allow --debug to take effect)
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    get_logger(level=log_level)
    logger.setLevel(log_level)

    # ── Resolve LLM model ─────────────────────────────────────────────────────
    if provider == "ollama" and not model:
        models = LLMClient.get_ollama_models()
        if not models:
            click.echo("No Ollama models found or Ollama server not running.")
            sys.exit(1)
        click.echo("Available Ollama models:")
        for idx, m in enumerate(models, 1):
            click.echo(f"  {idx}: {m.split(' ', 1)[1]}")
        choice = click.prompt(
            "Select Ollama model by number",
            type=click.IntRange(1, len(models)),
        )
        selected_model = models[choice - 1].split(" ", 1)[1]
        llm_model = ("ollama", selected_model)
    else:
        if not model:
            click.echo("--model is required for non-Ollama providers.")
            sys.exit(1)
        llm_model = (provider, model)

    # ── Resolve database path ─────────────────────────────────────────────────
    db_name = Path(project_path).name
    db_file = Path(f"{db_name}.db")
    project_path_resolved = str(Path(project_path).resolve())

    run_extraction = True  # default: always run full pipeline

    if db_file.exists():
        # Check if the DB already contains data for this exact project
        with DatabaseCall(db_path=str(db_file)) as probe:
            try:
                existing_id = probe.project_exists(db_name, project_path_resolved)
            except Exception:
                existing_id = None

        if existing_id is not None:
            logger.warning(
                f"Database '{db_file}' already contains project '{db_name}'. "
                "Updating existing records."
            )
            run_extraction = True  # update in-place
        else:
            # DB exists but for a different project — create a new DB with a unique name
            import time as _time
            db_file = Path(f"{db_name}_{int(_time.time())}.db")
            logger.info(f"Different project detected — creating new database '{db_file}'.")

    # ── Run async pipeline ────────────────────────────────────────────────────
    asyncio.run(_full(
        project_path=project_path_resolved,
        use_docker=use_docker,
        no_references=no_references,
        output_docs=output_docs,
        llm_model=llm_model,
        project_context=project_context,
        db_file=db_file,
    ))


async def _full(
    project_path: str,
    use_docker: bool,
    no_references: bool,
    output_docs,
    llm_model,
    project_context,
    db_file: Path,
):
    """Full async extraction + documentation pipeline."""
    # Step 1 – File & folder extraction
    logging.debug("Starting file extraction for %s", project_path)
    extractor = file_extractor.ProjectExtractor()
    root_folder = await extractor.extract_folder(project_path)

    # Step 2 – LSP symbol + reference extraction
    lsp_extractor = LSP_Extractor(root_folder, use_docker=use_docker, no_references=no_references)
    await lsp_extractor.run_extraction()

    # Step 3 – Persist to database
    with DatabaseCall(db_path=str(db_file)) as db:
        db.init_db()
        from_obj_to_sql(root_folder, db=str(db_file))

        # Step 4 – LLM documentation
        llm = LLMClient(
            provider=llm_model[0],
            model=llm_model[1],
            max_tokens=2000,
            temperature=0.3,
            timeout=600,
        )
        initialized = await llm.initialize()
        if not initialized:
            logger.error("Failed to initialize LLM client. Please check if the LLM provider (e.g. Ollama) is running and accessible.")
            click.echo("❌ Documentation failed: LLM client could not be initialized.")
            return

        project_root = Path(root_folder.root)

        documentation_success = await LLM_documentation_db.document_projects(
            llm=llm,
            project=project_root,
            output_save=output_docs if output_docs else None,
            db=db,
            context=Path(project_context) if project_context else None,
        )

    if documentation_success:
        click.echo(f"✅ Full pipeline completed for project: {root_folder.name}")
    else:
        click.echo(f"❌ Documentation failed for project: {root_folder.name}")

if __name__ == '__main__':
    cli()