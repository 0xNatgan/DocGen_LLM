"""
Legacy entry point — the main CLI is now `src/cli.py` (docgen run <project_path>).
This file is kept for direct script invocation during development.
"""
from .extraction import file_extractor
from .extraction.lsp_extractor import LSP_Extractor
from .llm import LLM_documentation_db
from .llm.llm_client import LLMClient
from .storage.database import from_obj_to_sql
from .storage.database_call import DatabaseCall
from .logging.logging import get_logger
import logging
import argparse
import json
import asyncio
from pathlib import Path

logger = get_logger(__name__)


async def main(project_path: str):
    logger.info("Starting the extraction process...")
    extractor = file_extractor.ProjectExtractor()
    root_folder = await extractor.extract_folder(project_path)
    lsp_extractor = LSP_Extractor(root_folder)
    await lsp_extractor.run_extraction()

    logger.info(f"Extraction completed for project: {root_folder.name}")

    # Persist to database
    db_name = Path(project_path).name
    db_file = Path(f"{db_name}.db")
    with DatabaseCall(db_path=str(db_file)) as db:
        db.init_db()
        from_obj_to_sql(root_folder, db=str(db_file))

        llm = LLMClient(provider="ollama", model="openhermes", max_tokens=2000, temperature=0.3, timeout=600)
        await llm.initialize()

        documentation_success = await LLM_documentation_db.document_projects(
            llm=llm,
            project=Path(root_folder.root),
            output_save=None,
            db=db,
            context=None,
        )

    if documentation_success:
        logger.info(f"Documentation generated successfully for project: {root_folder.name}")
    else:
        logger.warning(f"Documentation generation failed for project: {root_folder.name}")

    folder_dict = root_folder.to_dict()
    output_file = f"{root_folder.name}_structure.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(folder_dict, f, indent=2, ensure_ascii=False)
    logger.info(f"Project structure saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract project structure")
    parser.add_argument("project_path", type=str, help="Path to the project folder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(args.project_path))
