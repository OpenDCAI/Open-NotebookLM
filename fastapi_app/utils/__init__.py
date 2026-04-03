from pathlib import Path
from workflow_engine.utils import get_project_root

PROJECT_ROOT = get_project_root()


def _to_outputs_url(abs_path: str, base_url: str = "") -> str:
    """Convert absolute file path to /outputs URL."""
    try:
        rel = Path(abs_path).relative_to(PROJECT_ROOT)
        return f"{base_url}/{rel.as_posix()}"
    except ValueError:
        return abs_path


def _from_outputs_url(url: str) -> str:
    """Convert /outputs URL to absolute file path."""
    if url.startswith("http"):
        url = url.split("/outputs/", 1)[-1]
    return str(PROJECT_ROOT / url)
