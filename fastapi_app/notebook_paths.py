"""
Notebook-centric path manager.

All path construction for the new directory layout lives here:

    outputs/{user_id}/{safe_title}_{notebook_id}/
    ├── sources/{source_stem}/original/
    │                         /mineru/
    │                         /markdown/
    ├── vector_store/
    ├── ppt/{timestamp}/
    ├── video/{timestamp}/
    ├── mindmap/{timestamp}/
    ├── podcast/{timestamp}/
    └── drawio/{timestamp}/
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

from workflow_engine.utils import get_project_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_user_id(user_id: Optional[str], max_len: int = 64) -> str:
    """
    Turn a user_id (often an email like 'user@example.com') into a
    filesystem-safe directory name.

    Handles special characters that may appear in emails:
    - @ -> _at_
    - Whitespace -> _
    - Slashes, backslashes -> _
    - Other unsafe characters -> removed

    Examples:
        '765973346@qq.com' -> '765973346_at_qq.com'
        'user+tag@example.com' -> 'user_tag_at_example.com'
    """
    user_id = (user_id or "").strip()
    if not user_id:
        return "local"

    # Normalize unicode
    user_id = unicodedata.normalize("NFC", user_id)

    # Replace @ with _at_ to preserve email structure readability
    user_id = user_id.replace("@", "_at_")

    # Replace slashes and backslashes
    user_id = user_id.replace("/", "_").replace("\\", "_")

    # Replace whitespace runs with underscore
    user_id = re.sub(r"\s+", "_", user_id)

    # Keep only safe chars: word chars (a-z, A-Z, 0-9, _), hyphen, dot
    # Note: We keep dots for email domains like 'qq.com'
    user_id = re.sub(r"[^\w\-.]", "_", user_id, flags=re.ASCII)

    # Collapse multiple underscores
    user_id = re.sub(r"_+", "_", user_id)

    # Strip leading/trailing special chars
    user_id = user_id.strip("_.- ")

    if not user_id:
        return "local"

    return user_id[:max_len]


def _sanitize_dir_name(title: str, max_len: int = 60) -> str:
    """
    Turn an arbitrary notebook title into a filesystem-safe directory component.
    Keeps CJK characters, ASCII alphanumerics, hyphens and underscores.
    """
    title = (title or "").strip()
    if not title:
        return "untitled"
    # Normalize unicode (NFC keeps composed CJK intact)
    title = unicodedata.normalize("NFC", title)
    # Replace whitespace runs with a single underscore
    title = re.sub(r"\s+", "_", title)
    # Keep only safe chars: word chars (includes CJK \w with re.UNICODE), hyphen, dot
    title = re.sub(r"[^\w\-]", "", title, flags=re.UNICODE)
    title = title.strip("_.- ")
    if not title:
        return "untitled"
    return title[:max_len]


def resolve_notebook_title(
    notebook_id: str,
    user_id: Optional[str] = None,
) -> str:
    """
    Look up the notebook title from local JSON.
    Returns the title string, or empty string if not found.
    """
    root = get_project_root()
    safe_uid = _sanitize_user_id(user_id)
    local_path = root / "outputs" / safe_uid / "_notebooks.json"
    if local_path.exists():
        try:
            data = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for nb in data:
                    if nb.get("id") == notebook_id:
                        return nb.get("name") or nb.get("title") or ""
        except Exception:
            pass
    return ""


# ---------------------------------------------------------------------------
# NotebookPaths
# ---------------------------------------------------------------------------

class NotebookPaths:
    """Centralised path builder for one notebook."""

    def __init__(
        self,
        notebook_id: str,
        notebook_title: str = "",
        user_id: Optional[str] = None,
        project_root: Optional[Path] = None,
    ):
        self._notebook_id = notebook_id
        self._user_id = user_id or "local"
        self._project_root = project_root or get_project_root()

        # Resolve title if not provided
        title = (notebook_title or "").strip()
        if not title:
            title = resolve_notebook_title(notebook_id, user_id)
        self._title = title
        self._resolved_root: Optional[Path] = None  # lazy cache for fallback

    # -- core names ----------------------------------------------------------

    @property
    def notebook_dir_name(self) -> str:
        """'{safe_title}_{id}' — the top-level directory name."""
        safe = _sanitize_dir_name(self._title)
        safe_id = self._notebook_id.replace("/", "_").replace("\\", "_")[:128]
        return f"{safe}_{safe_id}"

    # -- absolute paths ------------------------------------------------------

    @property
    def root(self) -> Path:
        """outputs/{user_id}/{title}_{id}/ — with fallback scan for existing dirs."""
        if self._resolved_root is not None:
            return self._resolved_root

        safe_uid = _sanitize_user_id(self._user_id)
        candidate = self._project_root / "outputs" / safe_uid / self.notebook_dir_name
        if candidate.exists():
            self._resolved_root = candidate
            return candidate

        # Fallback: scan outputs/{user_id}/ or outputs/ for any dir ending with _{notebook_id}
        self._resolved_root = self._find_existing_root() or candidate
        return self._resolved_root

    def _find_existing_root(self) -> Optional[Path]:
        """Scan outputs/{user_id}/ and outputs/ for a directory whose name ends with _{notebook_id}."""
        safe_id = self._notebook_id.replace("/", "_").replace("\\", "_")[:128]
        suffix = f"_{safe_id}"
        outputs_dir = self._project_root / "outputs"
        if not outputs_dir.exists():
            return None

        # First try user-specific directory
        safe_uid = _sanitize_user_id(self._user_id)
        user_dir = outputs_dir / safe_uid
        if user_dir.exists():
            try:
                for d in user_dir.iterdir():
                    if d.is_dir() and d.name.endswith(suffix):
                        return d
            except Exception:
                pass

        # Fallback: scan ALL user directories under outputs/ for the notebook
        # This handles cases where user_id changed (e.g., UUID -> email)
        try:
            for user_candidate in outputs_dir.iterdir():
                if not user_candidate.is_dir() or user_candidate == user_dir:
                    continue
                for d in user_candidate.iterdir():
                    if d.is_dir() and d.name.endswith(suffix):
                        return d
        except Exception:
            pass
        return None

    @property
    def sources_dir(self) -> Path:
        """outputs/{title}_{id}/sources/"""
        return self.root / "sources"

    def source_dir(self, filename: str) -> Path:
        """sources/{stem}/"""
        stem = Path(filename).stem
        return self.sources_dir / stem

    def source_original_dir(self, filename: str) -> Path:
        """sources/{stem}/original/"""
        return self.source_dir(filename) / "original"

    def source_mineru_dir(self, filename: str) -> Path:
        """sources/{stem}/mineru/"""
        return self.source_dir(filename) / "mineru"

    def source_markdown_dir(self, filename: str) -> Path:
        """sources/{stem}/markdown/"""
        return self.source_dir(filename) / "markdown"

    def source_sam3_dir(self, filename: str) -> Path:
        """sources/{stem}/sam3/"""
        return self.source_dir(filename) / "sam3"

    @property
    def vector_store_dir(self) -> Path:
        """outputs/{title}_{id}/vector_store/"""
        return self.root / "vector_store"

    def feature_output_dir(self, feature: str, ts: Optional[int] = None) -> Path:
        """outputs/{title}_{id}/{feature}/{ts}/"""
        ts = ts or int(time.time())
        return self.root / feature / str(ts)


# ---------------------------------------------------------------------------
# Convenience entry-point
# ---------------------------------------------------------------------------

def get_notebook_paths(
    notebook_id: str,
    notebook_title: str = "",
    user_id: Optional[str] = None,
) -> NotebookPaths:
    """One-liner to obtain a NotebookPaths instance."""
    return NotebookPaths(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=user_id,
    )
