from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import fitz
from fastapi import HTTPException

from fastapi_app.kb_records import get_source_records
from fastapi_app.notebook_paths import _sanitize_user_id, get_notebook_paths
from fastapi_app.utils import _from_outputs_url
from workflow_engine.logger import get_logger
from workflow_engine.toolkits.research_tools import fetch_page_text
from workflow_engine.utils import get_project_root

log = get_logger(__name__)

LINK_SOURCES_FILENAME = "link_sources.json"
DEFAULT_USER_ID = "local"
DEFAULT_EMAIL = "local"


class SourceService:
    """Read notebook sources and preview source content."""

    def _legacy_vector_manifest_path(self, email: str, notebook_id: Optional[str]) -> Path:
        root = get_project_root()
        safe_email = _sanitize_user_id(email) if email else "default"
        safe_nb = (notebook_id or "_shared").replace("/", "_").replace("\\", "_")[:128]
        return root / "outputs" / "kb_data" / safe_email / safe_nb / "vector_store" / "knowledge_manifest.json"

    def _legacy_notebook_dir(self, email: str, notebook_id: Optional[str]) -> Path:
        root = get_project_root()
        safe_email = _sanitize_user_id(email) if email else "default"
        base = root / "outputs" / "kb_data" / safe_email
        if notebook_id:
            return base / notebook_id.replace("/", "_").replace("\\", "_")[:128]
        return base / "_shared"

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

    def _resolve_local_path(self, path_or_url: str) -> Path:
        if not path_or_url:
            raise HTTPException(status_code=400, detail="Empty file path")
        raw = _from_outputs_url(path_or_url)
        path = Path(raw)
        if not path.is_absolute():
            path = (get_project_root() / path).resolve()
        elif not path.exists():
            raw_stripped = unquote(raw.lstrip("/"))
            if raw_stripped:
                project_path = (get_project_root() / raw_stripped).resolve()
                if project_path.exists():
                    path = project_path
        return path

    def _pdf_to_markdown(self, local_path: str) -> str:
        text_parts: List[str] = []
        try:
            doc = fitz.open(local_path)
            for page_index in range(len(doc)):
                page = doc[page_index]
                for block in page.get_text("blocks"):
                    if len(block) >= 5 and block[4].strip():
                        text_parts.append(block[4].strip())
            doc.close()
        except Exception as exc:
            log.warning("_pdf_to_markdown failed for %s: %s", local_path, exc)
            return ""
        return "\n\n".join(text_parts)

    def _manifest_path_for_storage_path(self, storage_path: str) -> Optional[Path]:
        raw = _from_outputs_url((storage_path or "").strip())
        path = Path(raw)
        if not path.is_absolute():
            path = (get_project_root() / raw).resolve()

        # New notebook-centric layout:
        # outputs/{user}/{notebook}/sources/{source}/original/file -> outputs/{user}/{notebook}/vector_store/knowledge_manifest.json
        parts = path.parts
        if "sources" in parts:
            try:
                idx = parts.index("sources")
                notebook_root = Path(*parts[:idx])
                manifest_path = notebook_root / "vector_store" / "knowledge_manifest.json"
                if manifest_path.exists():
                    return manifest_path
            except Exception:
                pass

        parts = path.parts
        if "kb_data" not in parts:
            return None
        idx = parts.index("kb_data")
        if idx + 2 >= len(parts):
            return None
        email = parts[idx + 1]
        notebook_id = parts[idx + 2]
        root = get_project_root()
        safe_nb = (notebook_id or "_shared").replace("/", "_").replace("\\", "_")[:128]
        manifest_path = root / "outputs" / "kb_data" / email / safe_nb / "vector_store" / "knowledge_manifest.json"
        return manifest_path if manifest_path.exists() else None

    def _resolve_entry_local_path(self, entry: Dict[str, Any]) -> Optional[Path]:
        for candidate in (
            entry.get("file_path"),
            entry.get("storage_path"),
            entry.get("static_url"),
            entry.get("url"),
        ):
            value = str(candidate or "").strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")) and "/outputs/" not in value:
                continue
            try:
                path = self._resolve_local_path(value)
            except Exception:
                continue
            if path.exists():
                return path.resolve()
        return None

    def _normalize_vector_record(self, file_record: Dict[str, Any]) -> Dict[str, Any]:
        status = str(file_record.get("status") or "").strip().lower()
        error = str(file_record.get("error") or "").strip() or None
        chunks_count = int(file_record.get("chunks_count") or 0)
        media_desc_count = int(file_record.get("media_desc_count") or 0)
        ready = status == "embedded" or (
            status not in {"failed", "deleted"}
            and (chunks_count > 0 or media_desc_count > 0)
        )

        if status == "deleted":
            normalized_status = "deleted"
        elif ready:
            normalized_status = "embedded"
        elif status in {"processing", "pending", "embedding"}:
            normalized_status = "pending"
        elif status == "failed" or error:
            normalized_status = "failed"
        else:
            normalized_status = "not_embedded"

        return {
            "kb_file_id": file_record.get("id"),
            "vector_status": normalized_status,
            "vector_ready": ready,
            "vector_error": error,
            "vector_chunks_count": chunks_count,
            "vector_media_desc_count": media_desc_count,
        }

    def _load_vector_status_map(
        self,
        *,
        notebook_id: Optional[str],
        email: Optional[str],
        notebook_title: Optional[str],
    ) -> Dict[str, Dict[str, Any]]:
        if not notebook_id:
            return {}

        manifest_candidates: List[Path] = []
        try:
            manifest_candidates.append(
                get_notebook_paths(notebook_id, notebook_title or "", email).vector_store_dir / "knowledge_manifest.json"
            )
        except Exception:
            pass

        if email:
            manifest_candidates.append(self._legacy_vector_manifest_path(email, notebook_id))

        for manifest_path in manifest_candidates:
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("Failed to read vector manifest %s: %s", manifest_path, exc)
                continue

            status_map: Dict[str, Dict[str, Any]] = {}
            for file_record in manifest.get("files") or []:
                original_path = str(file_record.get("original_path") or "").strip()
                if not original_path:
                    continue
                try:
                    resolved = str(Path(original_path).resolve())
                except Exception:
                    continue
                status_map[resolved] = self._normalize_vector_record(file_record)
            return status_map

        return {}

    def list_notebook_files(
        self,
        *,
        user_id: Optional[str] = None,
        notebook_id: Optional[str] = None,
        email: Optional[str] = None,
        notebook_title: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        uid = (user_id or "").strip() or DEFAULT_USER_ID
        em = (email or "").strip() or DEFAULT_EMAIL
        if not notebook_id:
            return []

        files: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        seen_names: set[str] = set()
        records = get_source_records(user_email=em, notebook_id=notebook_id)
        project_root = get_project_root()

        def normalize_key(name: str = "", url: str = "", file_type: str = "") -> str:
            normalized_url = (url or "").strip().rstrip("/")
            if normalized_url:
                return f"url:{normalized_url}"
            return f"{(file_type or '').strip().lower()}::{(name or '').strip()}"

        def append_file(entry: Dict[str, Any]) -> None:
            key = normalize_key(
                name=str(entry.get("name") or ""),
                url=str(entry.get("static_url") or entry.get("url") or ""),
                file_type=str(entry.get("file_type") or entry.get("source_type") or ""),
            )
            if key in seen_keys:
                return
            seen_keys.add(key)
            name = str(entry.get("name") or "").strip()
            if name:
                seen_names.add(name)
            files.append(entry)

        for record in records:
            append_file({
                "id": f"file-{record['file_name']}-{int(record.get('created_at', 0))}",
                "name": record["file_name"],
                "url": record["static_url"],
                "static_url": record["static_url"],
                "file_size": record.get("file_size", 0),
                "file_type": record.get("file_type", ""),
            })

        try:
            paths = get_notebook_paths(notebook_id, notebook_title or "", em or uid)
            if paths.sources_dir.exists():
                for src_dir in sorted(paths.sources_dir.iterdir()):
                    if not src_dir.is_dir():
                        continue
                    orig_dir = src_dir / "original"
                    if not orig_dir.exists():
                        continue
                    for source_file in orig_dir.iterdir():
                        if not source_file.is_file():
                            continue
                        rel = source_file.relative_to(project_root)
                        static_url = "/" + rel.as_posix()
                        stat = source_file.stat()
                        append_file({
                            "id": f"file-{source_file.name}-{stat.st_mtime_ns}",
                            "name": source_file.name,
                            "url": static_url,
                            "static_url": static_url,
                            "file_size": stat.st_size,
                            "file_type": (source_file.suffix or "").lower() or "application/octet-stream",
                        })
        except Exception as exc:
            log.warning("[list_notebook_files] new layout read failed: %s", exc)

        notebook_dir = self._legacy_notebook_dir(em, notebook_id)
        link_static_urls: set[str] = set()
        try:
            if notebook_dir.exists():
                link_sources = self._load_legacy_link_sources(notebook_dir)
                for item in link_sources:
                    static_url = item.get("static_url") or ""
                    if static_url:
                        link_static_urls.add(static_url.rstrip("/"))

                for source_file in notebook_dir.iterdir():
                    if not source_file.is_file():
                        continue
                    if source_file.name == LINK_SOURCES_FILENAME:
                        continue
                    if source_file.name in seen_names:
                        continue
                    rel = source_file.relative_to(project_root)
                    static_url = "/" + rel.as_posix().replace("@", "%40")
                    if static_url.rstrip("/") in link_static_urls:
                        continue
                    stat = source_file.stat()
                    append_file({
                        "id": f"file-{source_file.name}-{stat.st_mtime_ns}",
                        "name": source_file.name,
                        "url": static_url,
                        "static_url": static_url,
                        "file_size": stat.st_size,
                        "file_type": (source_file.suffix or "").lower() or "application/octet-stream",
                    })

                for index, item in enumerate(link_sources):
                    link_id = item.get("id") or f"link-{index}-{hash(item.get('link', '')) % 10**8}"
                    static_url = item.get("static_url") or ""
                    link_url = item.get("link") or ""
                    url = static_url or link_url
                    append_file({
                        "id": link_id,
                        "name": (item.get("title") or item.get("link") or "Link")[:200],
                        "url": url,
                        "static_url": url,
                        "file_size": 0,
                        "file_type": "link",
                        "source_type": "link",
                        "snippet": item.get("snippet") or "",
                    })
        except Exception as exc:
            log.warning("list_notebook_files legacy read failed: %s", exc)

        vector_status_map = self._load_vector_status_map(
            notebook_id=notebook_id,
            email=em,
            notebook_title=notebook_title,
        )
        for entry in files:
            local_path = self._resolve_entry_local_path(entry)
            vector_info = vector_status_map.get(str(local_path)) if local_path else None
            entry.update({
                "kb_file_id": vector_info.get("kb_file_id") if vector_info else None,
                "vector_status": vector_info.get("vector_status") if vector_info else "not_embedded",
                "vector_ready": bool(vector_info.get("vector_ready")) if vector_info else False,
                "vector_error": vector_info.get("vector_error") if vector_info else None,
                "vector_chunks_count": vector_info.get("vector_chunks_count", 0) if vector_info else 0,
                "vector_media_desc_count": vector_info.get("vector_media_desc_count", 0) if vector_info else 0,
            })

        files.sort(key=lambda item: (item.get("file_type") == "link", item.get("name", "")))
        return files

    def get_source_display_content(self, path: str) -> Dict[str, Any]:
        if not path or not path.strip():
            return {"content": None, "from_mineru": False}

        abs_path = self._resolve_local_path(path.strip())
        if not abs_path.exists() or not abs_path.is_file():
            return {"content": None, "from_mineru": False}

        manifest_path = self._manifest_path_for_storage_path(path)
        if not manifest_path:
            return {"content": None, "from_mineru": False}

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {"content": None, "from_mineru": False}

        for file_record in manifest.get("files") or []:
            original_path = (file_record.get("original_path") or "").strip()
            if not original_path:
                continue
            if Path(original_path).resolve() != abs_path.resolve():
                continue
            md_path = file_record.get("processed_md_path")
            if md_path and Path(md_path).exists():
                try:
                    content = Path(md_path).read_text(encoding="utf-8", errors="replace")
                    return {"content": content, "from_mineru": True}
                except Exception:
                    pass
            break

        return {"content": None, "from_mineru": False}

    def parse_local_file(self, path_or_url: str) -> Dict[str, Any]:
        if not path_or_url or not path_or_url.strip():
            raise HTTPException(status_code=400, detail="path_or_url is required")

        path = self._resolve_local_path(path_or_url.strip())
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        suffix = (path.suffix or "").lower()
        if suffix == ".pdf":
            content = self._pdf_to_markdown(str(path))
            return {
                "success": True,
                "content": content or "[PDF 无文本或解析失败]",
                "format": "markdown",
            }
        if suffix in (".md", ".txt", ".markdown"):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                return {
                    "success": True,
                    "content": content,
                    "format": "markdown" if suffix == ".md" else "text",
                }
            except Exception as exc:
                log.warning("parse_local_file read text failed: %s", exc)
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        raise HTTPException(
            status_code=400,
            detail="Unsupported file type for preview (only .pdf, .md, .txt)",
        )

    def fetch_page_content(self, url: str) -> Dict[str, Any]:
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            raise HTTPException(status_code=400, detail="Invalid url")
        try:
            content = fetch_page_text(url, max_chars=50000)
            return {"success": True, "content": content}
        except Exception as exc:
            log.warning("fetch_page_content failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
