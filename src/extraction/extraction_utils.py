import requests
import logging
import os
from pathlib import Path
import json
import pathspec
import tempfile

logger = logging.getLogger(__name__)

def _ext_to_lang(ext: str, config_path: str = None) -> str:
    """Convert file extension to language name using the JSON config."""
    if config_path is None:
        config_path = Path(__file__).parent / "extract_config/languages_config.json"
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Error loading language config: {e}")
        return None

    if ext.startswith('.'):
        ext = ext[1:]
        
    for lang, lang_config in config.get("languages", {}).items():
        if lang == "default_config":  # Skip default config
            continue
        if ext in lang_config.get("extensions", []):
            return lang
    return None

def detect_primary_language(root: str) -> str:
    """Detect the primary language of a project by counting file extensions."""
    language_counts = {}
    
    # Basic exclusions for language detection
    basic_excluded_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', '.idea', '.vscode'}
    basic_excluded_exts = {'log', 'md', 'txt', 'pdf', 'png', 'jpg', 'gif', 'zip', 'tar', 'gz', 'exe', 'dll'}
    
    for file_path in Path(root).rglob('*'):
        if file_path.is_file():
            # Quick exclusion check
            if any(excluded_dir in file_path.parts for excluded_dir in basic_excluded_dirs):
                continue
                
            ext = file_path.suffix.lstrip('.')
            if ext and ext not in basic_excluded_exts:
                lang = _ext_to_lang(ext)
                if lang:
                    language_counts[lang] = language_counts.get(lang, 0) + 1
    
    # Return most common language
    if language_counts:
        return max(language_counts, key=language_counts.get)
    return None

def _get_github_gitignore_name(language: str) -> str:
    """Get GitHub gitignore template name for a language."""
    mapping_path = Path(__file__).parent / "extract_config/github_gitignore_mapping.json"
    
    try:
        with open(mapping_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        return mapping.get("language_to_github", {}).get(language)
    except Exception as e:
        logger.warning(f"Could not load GitHub gitignore mapping: {e}")
        return None

def _add_default_exclusions(temp_file):
    """Add default exclusions from excluded_files.json."""
    try:
        config_path = Path(__file__).parent / "extract_config/excluded_files.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            excluded_config = json.load(f)
        
        temp_file.write("# ========================================\n")
        temp_file.write("# DEFAULT EXCLUSIONS\n")
        temp_file.write("# ========================================\n")
        
        # Add ignored directories
        for ignore_dir in excluded_config.get("ignore_dirs", []):
            temp_file.write(f"{ignore_dir}/\n")
        
        # Add ignored patterns
        for pattern in excluded_config.get("ignore_patterns", []):
            temp_file.write(f"{pattern}\n")
        
        # Add ignored extensions
        for ext in excluded_config.get("ignored_extensions", []):
            temp_file.write(f"*.{ext}\n")
        
        temp_file.write("\n")
        
    except Exception as e:
        logger.warning(f"Could not load default exclusions: {e}")
        # Fallback essentials
        essentials = [".git/", "__pycache__/", "*.pyc", "node_modules/", ".venv/", "*.log", ".DS_Store"]
        for pattern in essentials:
            temp_file.write(pattern + '\n')
        temp_file.write("\n")

def excluded(file_path: str, temp_gitignore: str) -> bool:
    """Check if the file path is excluded by gitignore rules."""
    if not temp_gitignore or not os.path.exists(temp_gitignore):
        return False
        
    try:
        with open(temp_gitignore, 'r', encoding='utf-8') as f:
            gitignore_content = f.read()
        spec = pathspec.PathSpec.from_lines('gitwildmatch', gitignore_content.splitlines())
        return spec.match_file(file_path)
    except Exception as e:
        logger.error(f"Error checking excluded files: {e}")
        return False

def build_gitignore(root: str) -> tempfile.NamedTemporaryFile: 
    """Create unified gitignore: default exclusions + project .gitignore + GitHub template."""
    primary_language = detect_primary_language(root)
    logger.info(f"Detected primary language: {primary_language}")
    
    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"{Path(root).name}_unified_", 
        suffix=".gitignore", 
        delete=False, 
        mode='w', 
        encoding='utf-8'
    )

    # 1. Add default exclusions
    _add_default_exclusions(temp_file)
    
    # 2. Add existing project .gitignore if it exists
    project_gitignore = Path(root) / ".gitignore"
    if project_gitignore.exists():
        temp_file.write("# ========================================\n")
        temp_file.write("# PROJECT .GITIGNORE\n")
        temp_file.write("# ========================================\n")
        try:
            with open(project_gitignore, 'r', encoding='utf-8') as f:
                temp_file.write(f.read())
                temp_file.write("\n")
            logger.info(f"Added project .gitignore")
        except Exception as e:
            logger.warning(f"Could not read project .gitignore: {e}")
    
    # 3. Try to fetch GitHub template
    if primary_language:
        github_name = _get_github_gitignore_name(primary_language)
        if github_name:
            temp_file.write("# ========================================\n")
            temp_file.write(f"# {github_name.upper()} GITHUB TEMPLATE\n")
            temp_file.write("# ========================================\n")
            
            try:
                response = requests.get(
                    f"https://raw.githubusercontent.com/github/gitignore/main/{github_name}.gitignore",
                    timeout=10
                )
                if response.status_code == 200:
                    logger.info(f"Fetched {github_name}.gitignore from GitHub")
                    temp_file.write(response.text)
                    if not response.text.endswith('\n'):
                        temp_file.write('\n')
                else:
                    logger.warning(f"Could not fetch {github_name}.gitignore (status: {response.status_code})")
            except Exception as e:
                logger.warning(f"Error fetching {github_name}.gitignore: {e}")
    
    temp_file.close()
    logger.info(f"Created unified gitignore: {temp_file.name}")
    return temp_file

def normalize_path(path):
    """Return a normalized, absolute, POSIX-style path for cross-platform matching."""
    return Path(path).resolve().as_posix()

