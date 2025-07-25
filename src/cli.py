from pathlib import Path
import click
import asyncio
import logging
import json
from src.extraction import file_extractor
from src.extraction.lsp_extractor import LSP_Extractor
from src.llm import LLM_documentation

@click.group()
def cli():
    """AI Project Documentation CLI."""
    logging.basicConfig(level=logging.INFO)

@cli.command()
@click.argument('project_path', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('output_file', '-o', type=click.Path(exists=True, file_okay=True, dir_okay=True), default=None, help="Output file to save the project structure as JSON.")
def extract(project_path, output_file):
    """Extract project structure (file and folders only)and save as JSON."""
    async def _extract():
        extractor = file_extractor.ProjectExtractor()
        root_folder = await extractor.extract_folder(project_path)
        folder_dict = root_folder.to_dict()
        if output_file is None:
            output_file = f"{root_folder.name}_structure.json"
        else:
            if output_file.exists():
                click.confirm(f"{output_file} already exists. Overwrite?", abort=True)
            else:
                click.echo(f"Saving to {output_file}")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(folder_dict, f, indent=2, ensure_ascii=False)
        click.echo(f"Project structure saved to {output_file}")
    asyncio.run(_extract())


@cli.command()
@click.argument('project_path', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('use_docker', '-u', is_flag=True, default=False, help="Run with Docker (for local LSP clients).")
@click.option('output_file', '-oj', type=click.Path(), default=None, help="Output file to save the project structure as JSON.")
@click.option('output_docs', '-doc', type=click.Path(), default=None, help="Output directory to save generated documentation files.")
@click.option('debug', '-d', is_flag=True, default=False, help="Enable debug logging.")
@click.option('llm_model', '-m', type=str, default="ollama qwen3:1.7b", help="LLM model to use for documentation generation.")
@click.option('project_context', '-c', type=click.Path(exists=True, file_okay=True, dir_okay=False), default=None, help="Context for the project to be documented.")
def run(project_path, use_docker, llm_model,output_file, output_docs, debug, project_context):
    """Extract and document the project (full pipeline)."""
    async def _full():
        if debug:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)
        extractor = file_extractor.ProjectExtractor()
        root_folder = await extractor.extract_folder(project_path)
        lsp_extractor = LSP_Extractor(root_folder, useDocker=use_docker)
        await lsp_extractor.run_extraction()
        if llm_model:
            llm = LLM_documentation.LLMClient(
                provider=llm_model.split(' ')[0],  # Extract provider from model string
                model=llm_model.split(' ')[1] if ' ' in llm_model else llm_model,
                max_tokens=2000,
                temperature=0.3,  # Adjusted temperature for better results
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

if __name__ == "__main__":
    cli()