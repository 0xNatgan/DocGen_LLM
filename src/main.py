from .extraction import file_extractor
from .extraction.lsp_extractor import LSP_Extractor
from .llm import LLM_documentation
import logging
import argparse
import json
import asyncio
from .llm.LLM_documentation import *

async def main():
    logging.info("Starting the extraction process...")
    extractor = file_extractor.ProjectExtractor()
    # Extract with reference analysis
    root_folder = await extractor.extract_folder(project_path)
    lsp_extractor = LSP_Extractor(root_folder)
    await lsp_extractor.run_extraction()

    logging.info(f"Extraction completed for project: {root_folder.name}")

    # Step: Generate documentation using LLM
    # This will create docs and docstring files in the docs/ folder
    documentation_success = await LLM_documentation.document_projects(None, root_folder)
    if documentation_success:
        logging.info(f"Documentation generated successfully for project: {root_folder.name}")
    else:
        logging.warning(f"Documentation generation failed for project: {root_folder.name}")

    folder_dict = root_folder.to_dict()

    output_file = f"{root_folder.name}_structure.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(folder_dict, f, indent=2, ensure_ascii=False)

    logging.info(f"Project structure saved to {output_file}")
    # logging.info(f"Root folder structure: {json.dumps(folder_dict, indent=2)}")




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract project structure")
    parser.add_argument("project_path", type=str, help="Path to the project folder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    project_path = args.project_path
    asyncio.run(main())
