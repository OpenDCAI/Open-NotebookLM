import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from workflow_engine.utils import get_project_root


def _to_outputs_url(abs_path: str, request=None, base_url: str = "") -> str:
    """Convert absolute file path to /outputs URL."""
    if not abs_path:
        return abs_path
    try:
        if isinstance(request, str) and not base_url:
            base_url = request
            request = None
        project_root = get_project_root()
        p = Path(abs_path)
        if not p.is_absolute():
            p = (project_root / p).resolve()
        rel = p.relative_to(project_root / "outputs")
        path_part = rel.as_posix().replace("@", "%40")
        if request is not None and hasattr(request, "base_url"):
            prefix = str(request.base_url).rstrip("/")
            return f"{prefix}/outputs/{path_part}"
        prefix = str(base_url or "").rstrip("/")
        return f"{prefix}/outputs/{path_part}" if prefix else f"/outputs/{path_part}"
    except ValueError:
        if "/outputs/" in abs_path:
            idx = abs_path.index("/outputs/")
            return abs_path[idx:].replace("@", "%40")
        return abs_path


def _from_outputs_url(url: str) -> str:
    """Convert /outputs URL to absolute file path."""
    if not url or not isinstance(url, str):
        return url
    if os.path.isabs(url) and os.path.exists(url):
        return url
    if "/outputs/" not in url and not url.startswith("http"):
        return url
    if "/outputs/" not in url:
        return url

    project_root = get_project_root()
    path_str = urlparse(url).path if url.startswith("http") else url
    rel_path = path_str.split("/outputs/", 1)[1].lstrip("/")
    return str((project_root / "outputs" / unquote(rel_path)).resolve())
