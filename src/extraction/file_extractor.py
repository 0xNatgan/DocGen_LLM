import json
import os
from pathlib import Path
from ..logging.logging import get_logger
from typing import List, Dict, Optional
from .models import FolderModel, FileModel

logger = get_logger(__name__)

class ProjectExtractor:
    def __init__(self):
        self.root_folder: Optional[FolderModel] = None
        self.config = self._get_config()

    def _get_config(self) -> Dict:
        """Load configuration for file extensions and languages."""
        open_config_path = Path(__file__).parent / 'extract_config/lsp_configs.json'
        if not open_config_path.exists():
            logger.error(f"Configuration file not found at {open_config_path}")
            return {}
        try:
            with open(open_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}

    async def extract_folder(self, folder_root: str) -> FolderModel:
        """Extract folder structure and files from the given root folder."""
        folder_root = str(Path(folder_root).resolve())
        folder_name = Path(folder_root).name
        
        if not Path(folder_root).exists() or not Path(folder_root).is_dir():
            logger.error(f"Folder root '{folder_root}' must be a valid directory.")
            return None

        self.root_folder = FolderModel(name=folder_name, root=folder_root)
        
        # Discover files, folders, and languages
        detected_languages = self._discover_files_and_folders(folder_root)
        
        if not detected_languages:
            logger.warning("No supported files found.")
            return self.root_folder

        logger.info(f"Detected languages: {detected_languages}")
        
        logger.info("🔍 Starting reference analysis...")
        
        return self.root_folder

    def _discover_files_and_folders(self, folder_root: str) -> List[str]:
        """Discover files and organize them into folder structure."""
        detected_languages = set()
        folder_map = {folder_root: self.root_folder}  # Maps folder path to FolderModel
        
        for file_path in Path(folder_root).rglob('*'):
            if file_path.is_file() and not self.root_folder.ignore_file(str(file_path)):
                file_extension = file_path.suffix.lower()
                
                # Find language for this extension
                for lang, config in self.config["languages"].items():
                    if file_extension in config["extensions"]:
                        detected_languages.add(lang)
                        
                        file_model = FileModel(
                            path=os.path.relpath(str(file_path), folder_root), 
                            language=lang,
                            project_root=folder_root  # Still useful for relative paths
                        )
                        # Organize into folder structure
                        self._organize_file_into_folders(file_model, folder_map, folder_root)
                            
                        logger.debug(f"Added file: {file_path} (language: {lang})")

                        break

        return list(detected_languages)

    def _organize_file_into_folders(self, file_model: FileModel, folder_map: Dict[str, FolderModel], root_path: str):
        """Organize a file into the appropriate folder structure."""
        file_path = Path(file_model.path)
        current_path = Path(root_path) / file_path.parent

        # Create folder hierarchy if it doesn't exist
        folders_to_create = []
        temp_path = current_path
        
        while str(temp_path) != root_path and str(temp_path) not in folder_map:
            folders_to_create.append(temp_path)
            temp_path = temp_path.parent
            
        # Create folders from parent to child
        folders_to_create.reverse()
        
        for folder_path in folders_to_create:
            folder_path_str = str(folder_path)
            if folder_path_str not in folder_map:
                folder_model = FolderModel(
                    name=folder_path.name,
                    root=folder_path_str
                )
                
                # Find parent folder and add as subfolder
                parent_path_str = str(folder_path.parent)
                if parent_path_str in folder_map:
                    folder_map[parent_path_str].add_subfolder(folder_model)
                
                folder_map[folder_path_str] = folder_model
                logger.debug(f"Created folder: {folder_path}")
        
        # Add file to its immediate parent folder
        parent_folder_path = str(current_path)
        if parent_folder_path in folder_map:
            folder_map[parent_folder_path].add_file(file_model)
            logger.debug(f"Added file {file_model.path} to folder {parent_folder_path}")

    def get_folder_by_path(self, folder_path: str) -> Optional[FolderModel]:
        """Get a folder by its path."""
        if self.root_folder.root == folder_path:
            return self.root_folder
        
        # Search in subfolders recursively
        def search_subfolders(folder: FolderModel) -> Optional[FolderModel]:
            for subfolder in folder.subfolders:
                if subfolder.root == folder_path:
                    return subfolder
                result = search_subfolders(subfolder)
                if result:
                    return result
            return None
        
        return search_subfolders(self.root_folder)

    def get_folders_by_language(self, language: str) -> List[FolderModel]:
        """Get all folders that contain files of a specific language."""
        matching_folders = []
        
        def check_folder(folder: FolderModel):
            if language in folder.get_all_languages():
                matching_folders.append(folder)
            for subfolder in folder.subfolders:
                check_folder(subfolder)
        
        check_folder(self.root_folder)
        return matching_folders

    def generate_folder_tree(self) -> Dict:
        """Generate a tree representation of the folder structure."""
        if not self.root_folder:
            return {}
            
        def build_tree_node(folder: FolderModel) -> Dict:
            return {
                "name": folder.name,
                "path": folder.root,
                "languages": folder.langs,
                "file_count": len(folder.files),
                "files": [{"name": Path(f.path).name, "language": f.language} for f in folder.files],
                "subfolders": [build_tree_node(subfolder) for subfolder in folder.subfolders]
            }
            
        return build_tree_node(self.root_folder)

    def to_dict(self) -> Dict:
        """Convert the project structure to a dictionary."""
        if not self.root_folder:
            return {}
        return {
            "name": self.root_folder.name,
            "root": self.root_folder.root,
            "languages": list(self.root_folder.get_all_languages()),
            "folders": [folder.to_dict() for folder in self.root_folder.subfolders],
            "files": [file.to_dict() for file in self.root_folder.files]
        }