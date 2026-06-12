import requests
from pathlib import Path
from ..logging.logging import get_logger
import json
import os
import pathspec
import tempfile
import time

logger = get_logger(__name__)

_GITIGNORE_CACHE_DIR = Path.home() / ".docgen" / "gitignore_cache"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _ext_to_lang(ext: str, config_path: str = None) -> str:
    """Convert file extension to language name using the JSON config."""
    if config_path is None:
        config_path = Path(__file__).parent / "extract_config/lsp_configs.json"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Error loading language config: {e}")
        return None

    if ext.startswith("."):
        ext = ext[1:]

    for lang, lang_config in config.get("languages", {}).items():
        if lang == "default_config":
            continue
        if ext in lang_config.get("extensions", []):
            return lang
    return None


def detect_primary_language(root: str) -> str:
    """Detect the primary language of a project by counting file extensions."""
    language_counts = {}

    basic_excluded_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vscode",
    }
    basic_excluded_exts = {"log", "md", "txt", "pdf", "png", "jpg", "gif", "zip", "tar", "gz", "exe", "dll"}

    for file_path in Path(root).rglob("*"):
        if file_path.is_file():
            if any(excluded_dir in file_path.parts for excluded_dir in basic_excluded_dirs):
                continue
            ext = file_path.suffix.lstrip(".")
            if ext and ext not in basic_excluded_exts:
                lang = _ext_to_lang(ext)
                if lang:
                    language_counts[lang] = language_counts.get(lang, 0) + 1

    if language_counts:
        return max(language_counts, key=language_counts.get)
    return None


def _get_github_gitignore_name(language: str) -> str:
    """Get GitHub gitignore template name for a language."""
    mapping_path = Path(__file__).parent / "extract_config/github_gitignore_mapping.json"
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        return mapping.get("language_to_github", {}).get(language)
    except Exception as e:
        logger.warning(f"Could not load GitHub gitignore mapping: {e}")
        return None


def _fetch_github_gitignore(github_name: str) -> str:
    """Fetch a GitHub gitignore template, using a local disk cache with a 7-day TTL.

    Falls back to a stale cache when offline. Returns an empty string if nothing
    is available.
    """
    _GITIGNORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _GITIGNORE_CACHE_DIR / f"{github_name}.gitignore"

    # Return cached version if fresh enough
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < _CACHE_TTL_SECONDS:
            logger.debug(f"Using cached gitignore for {github_name} (age {age:.0f}s)")
            return cache_file.read_text(encoding="utf-8")

    # Fetch from GitHub
    try:
        response = requests.get(
            f"https://raw.githubusercontent.com/github/gitignore/main/{github_name}.gitignore",
            timeout=10,
        )
        if response.status_code == 200:
            logger.info(f"Fetched {github_name}.gitignore from GitHub")
            cache_file.write_text(response.text, encoding="utf-8")
            return response.text
        else:
            logger.warning(f"Could not fetch {github_name}.gitignore (status: {response.status_code})")
    except Exception as e:
        logger.warning(f"Error fetching {github_name}.gitignore (offline?): {e}")

    # Return stale cache if available, otherwise empty string
    if cache_file.exists():
        logger.warning(f"Returning stale cached gitignore for {github_name}")
        return cache_file.read_text(encoding="utf-8")
    return ""


def _add_default_exclusions(temp_file):
    """Add default exclusions from excluded_files.json."""
    try:
        config_path = Path(__file__).parent / "extract_config/excluded_files.json"
        with open(config_path, "r", encoding="utf-8") as f:
            excluded_config = json.load(f)

        temp_file.write("# ========================================\n")
        temp_file.write("# DEFAULT EXCLUSIONS\n")
        temp_file.write("# ========================================\n")

        for ignore_dir in excluded_config.get("ignore_dirs", []):
            temp_file.write(f"{ignore_dir}/\n")
        for pattern in excluded_config.get("ignore_patterns", []):
            temp_file.write(f"{pattern}\n")
        for ext in excluded_config.get("ignored_extensions", []):
            temp_file.write(f"*.{ext}\n")

        temp_file.write("\n")

    except Exception as e:
        logger.warning(f"Could not load default exclusions: {e}")
        essentials = [".git/", "__pycache__/", "*.pyc", "node_modules/", ".venv/", "*.log", ".DS_Store"]
        for pattern in essentials:
            temp_file.write(pattern + "\n")
        temp_file.write("\n")


def excluded(file_path: str, temp_gitignore: str) -> bool:
    """Check if the file path is excluded by gitignore rules."""
    if not temp_gitignore or not os.path.exists(temp_gitignore):
        return False
    try:
        with open(temp_gitignore, "r", encoding="utf-8") as f:
            gitignore_content = f.read()
        spec = pathspec.PathSpec.from_lines("gitwildmatch", gitignore_content.splitlines())
        return spec.match_file(file_path)
    except Exception as e:
        logger.error(f"Error checking excluded files: {e}")
        return False


def build_gitignore(root: str) -> tempfile.NamedTemporaryFile:
    """Create a unified gitignore combining default exclusions, the project's .gitignore,
    and a (cached) language-specific GitHub template."""
    primary_language = detect_primary_language(root)
    logger.info(f"Detected primary language: {primary_language}")

    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"{Path(root).name}_unified_",
        suffix=".gitignore",
        delete=False,
        mode="w",
        encoding="utf-8",
    )

    # 1. Default exclusions
    _add_default_exclusions(temp_file)

    # 2. Project .gitignore
    project_gitignore = Path(root) / ".gitignore"
    if project_gitignore.exists():
        temp_file.write("# ========================================\n")
        temp_file.write("# PROJECT .GITIGNORE\n")
        temp_file.write("# ========================================\n")
        try:
            with open(project_gitignore, "r", encoding="utf-8") as f:
                temp_file.write(f.read())
                temp_file.write("\n")
            logger.info("Added project .gitignore")
        except Exception as e:
            logger.warning(f"Could not read project .gitignore: {e}")

    # 3. GitHub template (disk-cached, works offline after first fetch)
    if primary_language:
        github_name = _get_github_gitignore_name(primary_language)
        if github_name:
            temp_file.write("# ========================================\n")
            temp_file.write(f"# {github_name.upper()} GITHUB TEMPLATE\n")
            temp_file.write("# ========================================\n")
            github_content = _fetch_github_gitignore(github_name)
            if github_content:
                temp_file.write(github_content)
                if not github_content.endswith("\n"):
                    temp_file.write("\n")

    temp_file.close()
    logger.info(f"Created unified gitignore: {temp_file.name}")
    return temp_file


def normalize_path(path) -> str:
    """Return a normalized, absolute, POSIX-style path for cross-platform matching."""
    return Path(path).resolve().as_posix()
