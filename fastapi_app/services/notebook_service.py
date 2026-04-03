from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from fastapi_app.notebook_paths import _sanitize_user_id, get_notebook_paths
from workflow_engine.logger import get_logger
from workflow_engine.utils import get_project_root

log = get_logger(__name__)

LINK_SOURCES_FILENAME = "link_sources.json"
DEFAULT_USER_ID = "local"
DEFAULT_EMAIL = "local"


class NotebookService:
    """Manage notebook metadata stored in local JSON files."""

    def _legacy_notebook_dir(self, email: str, notebook_id: Optional[str]) -> Path:
        root = get_project_root()
        safe_email = _sanitize_user_id(email) if email else "default"
        base = root / "outputs" / "kb_data" / safe_email
        if notebook_id:
            return base / notebook_id.replace("/", "_").replace("\\", "_")[:128]
        return base / "_shared"

    def _notebooks_local_path(self, user_id: str) -> Path:
        root = get_project_root()
        safe_id = _sanitize_user_id(user_id)
        base = root / "outputs" / safe_id
        base.mkdir(parents=True, exist_ok=True)
        return base / "_notebooks.json"

    def _load_legacy_link_sources(self, notebook_dir: Path) -> List[Dict[str, Any]]:
        path = notebook_dir / LINK_SOURCES_FILENAME
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def list_local(self, user_id: str) -> List[Dict[str, Any]]:
        path = self._notebooks_local_path(user_id)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception as exc:
            log.warning("list_local read failed: %s", exc)
            return []

    def create_local(self, user_id: str, name: str, description: str = "") -> Dict[str, Any]:
        path = self._notebooks_local_path(user_id)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        notebook_id = f"local_{int(time.time() * 1000)}_{os.urandom(4).hex()}"
        new_notebook = {
            "id": notebook_id,
            "name": name,
            "description": description or "",
            "created_at": now,
            "updated_at": now,
        }
        notebooks = self.list_local(user_id)
        notebooks.insert(0, new_notebook)
        try:
            path.write_text(
                json.dumps(notebooks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("create_local write failed: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to save notebook locally") from exc
        return new_notebook

    def list_notebooks(self, email: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        dir_id = (email or "").strip() or (user_id or "").strip() or DEFAULT_USER_ID
        email_for_legacy = (email or "").strip() or DEFAULT_EMAIL
        rows = self.list_local(dir_id)

        for row in rows:
            notebook_id = row.get("id")
            if not notebook_id:
                row.setdefault("sources", 0)
                continue

            count = 0

            try:
                paths = get_notebook_paths(notebook_id, row.get("name", ""), dir_id)
                if paths.sources_dir.exists():
                    count += sum(
                        1
                        for child in paths.sources_dir.iterdir()
                        if child.is_dir() and (child / "original").exists()
                    )
            except Exception:
                pass

            legacy_dir = self._legacy_notebook_dir(email_for_legacy, notebook_id)
            try:
                if legacy_dir.exists():
                    file_count = sum(
                        1
                        for child in legacy_dir.iterdir()
                        if child.is_file() and child.name != LINK_SOURCES_FILENAME
                    )
                    link_count = len(self._load_legacy_link_sources(legacy_dir))
                    count = max(count, file_count + link_count)
            except Exception:
                pass

            row["sources"] = count

        return rows

    def create_notebook(
        self,
        *,
        name: str,
        user_id: str,
        description: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        dir_id = (email or "").strip() or user_id
        notebook = self.create_local(dir_id, name, description or "")

        if notebook.get("id"):
            try:
                paths = get_notebook_paths(notebook["id"], name, dir_id)
                paths.sources_dir.mkdir(parents=True, exist_ok=True)
                log.info("[create_notebook] created dir: %s", paths.root)
            except Exception as exc:
                log.warning("[create_notebook] dir creation failed: %s", exc)

        return notebook
