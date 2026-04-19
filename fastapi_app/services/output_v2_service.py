from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException
import httpx

from fastapi_app.config import settings
from fastapi_app.notebook_paths import get_notebook_paths
from fastapi_app.source_manager import SourceManager
from fastapi_app.utils import _from_outputs_url, _to_outputs_url

log = logging.getLogger(__name__)


class OutputV2Service:
    SUPPORTED_TYPES = {"ppt", "report", "mindmap", "podcast", "flashcard", "quiz"}
    PPT_STAGE_OUTLINE = "outline_ready"
    PPT_STAGE_PAGES = "pages_ready"
    PPT_STAGE_GENERATED = "generated"

    def _build_ppt_context_payload(
        self,
        *,
        outline: List[Dict[str, Any]],
        raw_pagecontent: List[Dict[str, Any]],
        mineru_root: str,
        query: str,
        source_paths: List[str],
        source_names: List[str],
        page_count: int,
        enable_images: bool,
    ) -> Dict[str, Any]:
        return {
            "outline": self._normalize_ppt_outline(outline),
            "raw_pagecontent": raw_pagecontent or [],
            "mineru_root": str(mineru_root or "").strip(),
            "source_paths": source_paths,
            "source_names": source_names,
            "query": query,
            "page_count": page_count,
            "enable_images": enable_images,
        }

    def _resolve_mineru_content_dir(self, root: Optional[Path]) -> str:
        if root is None or not root.exists():
            return ""
        for sub in ("auto", "hybrid_auto"):
            candidate = root / sub
            if candidate.is_dir() and list(candidate.glob("*.md")):
                return str(candidate.resolve())
        if root.is_dir() and list(root.glob("*.md")):
            return str(root.resolve())
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            for sub in ("auto", "hybrid_auto"):
                candidate = child / sub
                if candidate.is_dir() and list(candidate.glob("*.md")):
                    return str(candidate.resolve())
            if list(child.glob("*.md")):
                return str(child.resolve())
        return ""

    def _base_dir(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        """Return the canonical outputs directory.

        The workspace migration (``ensure_workspace_migrated``) may have moved
        ``outputs_v2/`` into ``workspace/outputs/``.  When that has happened we
        must read/write from the migrated location.  If *both* locations exist
        (post-migration writes created a new ``outputs_v2/``), we merge the
        orphaned items back into the workspace location once.
        """
        notebook_root = get_notebook_paths(notebook_id, notebook_title, user_id).root
        workspace_dir = notebook_root / "workspace" / "outputs"
        legacy_dir = notebook_root / "outputs_v2"

        # Fast path: workspace location exists (migration happened)
        if workspace_dir.exists():
            self._merge_orphaned_legacy_items(legacy_dir, workspace_dir)
            return workspace_dir

        # No migration yet – use legacy location
        return legacy_dir

    # ------------------------------------------------------------------
    # One-time merge of orphaned outputs_v2 items after workspace migration
    # ------------------------------------------------------------------
    def _merge_orphaned_legacy_items(self, legacy_dir: Path, workspace_dir: Path) -> None:
        """Merge any items created in the old ``outputs_v2/`` dir after the
        workspace migration moved data to ``workspace/outputs/``.

        This can happen when ``OutputV2Service`` was still writing to the old
        path while the rest of the workspace code already migrated.  The merge
        is idempotent: once done a marker file prevents repeat work.
        """
        legacy_manifest = legacy_dir / "items.json"
        if not legacy_manifest.exists():
            return

        merge_marker = legacy_dir / ".merged_to_workspace"
        if merge_marker.exists():
            return

        try:
            legacy_items = self._read_manifest(legacy_manifest)
            if not legacy_items:
                # Empty manifest — just mark as done
                merge_marker.write_text("merged", encoding="utf-8")
                return

            workspace_manifest = workspace_dir / "items.json"
            workspace_items = self._read_manifest(workspace_manifest)
            existing_ids = {item.get("id") for item in workspace_items}

            merged_count = 0
            for item in legacy_items:
                if item.get("id") in existing_ids:
                    continue
                workspace_items.append(item)
                existing_ids.add(item.get("id"))
                merged_count += 1

                # Move the item subdirectory if it exists
                item_id = item.get("id", "")
                if item_id:
                    src_item_dir = legacy_dir / item_id
                    dst_item_dir = workspace_dir / item_id
                    if src_item_dir.exists() and src_item_dir.is_dir() and not dst_item_dir.exists():
                        shutil.move(str(src_item_dir), str(dst_item_dir))

            if merged_count > 0:
                self._write_manifest(workspace_manifest, workspace_items)
                log.info(
                    "[outputs_v2] merged %d orphaned items from legacy outputs_v2 into workspace/outputs",
                    merged_count,
                )

            merge_marker.write_text("merged", encoding="utf-8")
        except Exception as exc:
            log.warning(
                "[outputs_v2] failed to merge orphaned legacy items: %s", exc,
            )

    def _manifest_path(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / "items.json"

    def _item_dir(self, notebook_id: str, notebook_title: str, user_id: str, output_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / output_id

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_manifest(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_manifest(self, path: Path, data: List[Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _find_output(self, manifest: List[Dict[str, Any]], output_id: str) -> tuple[int, Dict[str, Any]]:
        for index, item in enumerate(manifest):
            if item.get("id") == output_id:
                return index, item
        raise HTTPException(status_code=404, detail="Output not found")

    def _slug(self, text: str, fallback: str) -> str:
        value = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", (text or "").strip())
        value = re.sub(r"_+", "_", value).strip("_.- ")
        return value or fallback

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _has_explicit_llm_config(self, api_url: Optional[str], api_key: Optional[str]) -> bool:
        return bool(str(api_url or "").strip() and str(api_key or "").strip())

    def _extract_upstream_error_message(self, exc: httpx.HTTPStatusError) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return ""
        try:
            payload = response.json()
        except Exception:
            payload = None

        if isinstance(payload, dict):
            message = str(((payload.get("error") or {}).get("message")) or "").strip()
            if message:
                return message
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        try:
            text = response.text.strip()
        except Exception:
            text = ""
        return text

    async def _run_with_backend_llm_fallback(
        self,
        *,
        label: str,
        api_url: Optional[str],
        api_key: Optional[str],
        operation,
    ):
        from fastapi_app.routers.kb import _require_llm_config

        initial_api_url, initial_api_key = _require_llm_config(api_url, api_key)
        try:
            return await operation(initial_api_url, initial_api_key)
        except Exception as exc:
            if not self._has_explicit_llm_config(api_url, api_key):
                raise

            explicit_url = str(api_url or "").strip()
            explicit_key = str(api_key or "").strip()
            backend_api_url, backend_api_key = _require_llm_config(None, None)
            if explicit_url == backend_api_url and explicit_key == backend_api_key:
                raise

            log.warning(
                "[outputs_v2] %s failed with explicit LLM config, retrying with backend env config. "
                "explicit_api_url=%s backend_api_url=%s error_type=%s error=%s",
                label,
                explicit_url,
                backend_api_url,
                type(exc).__name__,
                exc,
            )
            return await operation(backend_api_url, backend_api_key)

    def _load_document(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        document_id: str,
    ) -> Dict[str, Any]:
        from fastapi_app.services.document_service import DocumentService

        return DocumentService().get_document(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            document_id=document_id,
        )

    def _maybe_load_document(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        document_id: str,
    ) -> Dict[str, Any]:
        if not document_id:
            return {"id": "", "title": "", "content": ""}
        return self._load_document(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            document_id=document_id,
        )

    def _load_guidance_items(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        guidance_item_ids: List[str],
    ) -> List[Dict[str, Any]]:
        if not guidance_item_ids:
            return []
        from fastapi_app.services.thinkflow_workspace_service import ThinkFlowWorkspaceService

        service = ThinkFlowWorkspaceService()
        items: List[Dict[str, Any]] = []
        for item_id in guidance_item_ids:
            if not item_id:
                continue
            item = service.get_item(
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                user_id=user_id,
                item_id=item_id,
            )
            if item.get("type") == "guidance":
                items.append(item)
        return items

    def _load_bound_documents(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        bound_document_ids: List[str],
    ) -> List[Dict[str, Any]]:
        documents: List[Dict[str, Any]] = []
        for document_id in bound_document_ids or []:
            if not document_id:
                continue
            try:
                documents.append(
                    self._load_document(
                        notebook_id=notebook_id,
                        notebook_title=notebook_title,
                        user_id=user_id,
                        document_id=document_id,
                    )
                )
            except HTTPException:
                continue
        return documents

    def _build_guidance_snapshot_text(self, guidance_items: List[Dict[str, Any]]) -> str:
        return "\n\n".join(
            f"## {item.get('title') or '产出指导'}\n\n{str(item.get('content') or '').strip()}".strip()
            for item in guidance_items
            if str(item.get("content") or "").strip()
        ).strip()

    def _extract_headings(self, content: str) -> List[str]:
        items: List[str] = []
        for line in (content or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                items.append(re.sub(r"^#+\s*", "", stripped).strip())
        return [item for item in items if item]

    def _fallback_outline(self, *, target_type: str, title: str, content: str, page_count: int) -> List[Dict[str, Any]]:
        headings = self._extract_headings(content)
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", content or "") if item.strip()]
        sections = headings[:page_count]
        if not sections:
            for idx, paragraph in enumerate(paragraphs[:page_count], start=1):
                first_line = paragraph.splitlines()[0][:28].strip()
                sections.append(first_line or f"章节 {idx}")
        if not sections:
            sections = ["背景与目标", "核心信息", "关键结论", "后续动作"][:page_count]
        outline: List[Dict[str, Any]] = []
        for idx, heading in enumerate(sections, start=1):
            snippet = paragraphs[idx - 1] if idx - 1 < len(paragraphs) else content[:300]
            bullets = [segment.strip(" -") for segment in re.split(r"[。；;\n]+", snippet) if segment.strip()]
            outline.append({
                "id": f"outline_{idx}",
                "title": heading,
                "summary": bullets[0] if bullets else heading,
                "bullets": bullets[:4] or [heading],
                "target_type": target_type,
            })
        return outline

    # ------------------------------------------------------------------
    # Legacy output scanning
    # ------------------------------------------------------------------

    _LEGACY_SCAN_CONFIG: Dict[str, Dict[str, Any]] = {
        "flashcard": {
            "data_file": "flashcards.json",
            "result_keys": {"flashcards"},
        },
        "quiz": {
            "data_file": "quiz.json",
            "result_keys": {"questions"},
        },
        "podcast": {
            "audio_exts": {".wav", ".mp3", ".m4a"},
            "script_file": "script.txt",
        },
        "mindmap": {
            "file_exts": {".mmd", ".mermaid", ".html", ".svg", ".png"},
        },
        "ppt": {
            "file_exts": {".pdf", ".pptx"},
        },
    }

    def _scan_legacy_outputs(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        v2_ids: set[str],
    ) -> List[Dict[str, Any]]:
        """Scan legacy feature directories and return v2-compatible items.

        Legacy outputs live in ``{notebook_root}/{feature}/{timestamp}/``.
        They are **not** registered in the v2 manifest.  This method converts
        them into read-only v2-shaped dicts so the frontend can display them.
        """
        notebook_root = get_notebook_paths(notebook_id, notebook_title, user_id).root
        if not notebook_root.exists():
            return []

        legacy_items: List[Dict[str, Any]] = []

        for feature, config in self._LEGACY_SCAN_CONFIG.items():
            feature_dir = notebook_root / feature
            if not feature_dir.exists():
                continue

            for ts_dir in feature_dir.iterdir():
                if not ts_dir.is_dir():
                    continue

                legacy_id = f"legacy_{feature}_{ts_dir.name}"
                if legacy_id in v2_ids:
                    continue

                try:
                    ts_int = int(ts_dir.name)
                    created_at = datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat()
                except (ValueError, OSError):
                    created_at = ""

                item = self._build_legacy_item(
                    feature=feature,
                    config=config,
                    ts_dir=ts_dir,
                    legacy_id=legacy_id,
                    created_at=created_at,
                    notebook_id=notebook_id,
                )
                if item is not None:
                    legacy_items.append(item)

        return legacy_items

    def _build_legacy_item(
        self,
        *,
        feature: str,
        config: Dict[str, Any],
        ts_dir: Path,
        legacy_id: str,
        created_at: str,
        notebook_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Build a single v2-compatible item dict from a legacy timestamp dir."""
        result: Dict[str, Any] = {}
        title = ""

        if feature in ("flashcard", "quiz"):
            data_file = ts_dir / config["data_file"]
            if not data_file.exists():
                return None
            try:
                data = json.loads(data_file.read_text(encoding="utf-8"))
            except Exception:
                return None
            title = str(data.get("title") or data.get("id") or f"{feature}_{ts_dir.name}")
            result = {"data_path": _to_outputs_url(str(data_file))}
            for key in config.get("result_keys", set()):
                if key in data:
                    result[key] = data[key]
            result["total_count"] = data.get("total_count", 0)
            result["source_files"] = data.get("source_files", [])
            result["download_url"] = _to_outputs_url(str(data_file))
            # Preserve created_at from data if available
            created_at = data.get("created_at") or created_at

        elif feature == "podcast":
            audio_file = None
            for child in ts_dir.iterdir():
                if child.suffix.lower() in config["audio_exts"]:
                    audio_file = child
                    break
            script_file = ts_dir / config["script_file"]
            if audio_file is None and not script_file.exists():
                return None
            title = f"播客_{ts_dir.name}"
            if audio_file is not None:
                result["audio_path"] = _to_outputs_url(str(audio_file))
                result["download_url"] = result["audio_path"]
            if script_file.exists():
                result["script_path"] = _to_outputs_url(str(script_file))
                if "download_url" not in result:
                    result["download_url"] = result["script_path"]

        elif feature == "mindmap":
            found_file = None
            for child in ts_dir.iterdir():
                if child.suffix.lower() in config["file_exts"]:
                    found_file = child
                    break
            if found_file is None:
                # Empty mindmap dir — skip
                return None
            title = f"思维导图_{ts_dir.name}"
            result["mindmap_path"] = _to_outputs_url(str(found_file))
            result["download_url"] = result["mindmap_path"]

        elif feature == "ppt":
            pdf_path = ts_dir / "paper2ppt.pdf"
            pptx_path = ts_dir / "paper2ppt_editable.pptx"
            if not pdf_path.exists() and not pptx_path.exists():
                # Check for any matching file
                found = False
                for child in ts_dir.iterdir():
                    if child.suffix.lower() in config["file_exts"]:
                        result["download_url"] = _to_outputs_url(str(child))
                        found = True
                        break
                if not found:
                    return None
            else:
                if pdf_path.exists():
                    result["ppt_pdf_path"] = _to_outputs_url(str(pdf_path))
                    result["download_url"] = result["ppt_pdf_path"]
                if pptx_path.exists():
                    result["ppt_pptx_path"] = _to_outputs_url(str(pptx_path))
                    if "download_url" not in result:
                        result["download_url"] = result["ppt_pptx_path"]
            title = f"PPT_{ts_dir.name}"
            # Scan for page images
            pages_dir = ts_dir / "ppt_pages"
            if pages_dir.exists():
                result["result_path"] = str(ts_dir)
        else:
            return None

        return {
            "id": legacy_id,
            "document_id": "",
            "title": title,
            "target_type": feature,
            "prompt": "",
            "status": "generated",
            "pipeline_stage": "generated",
            "outline": [],
            "page_reviews": [],
            "page_versions": [],
            "page_count": 0,
            "guidance_item_ids": [],
            "source_paths": [],
            "source_names": [],
            "bound_document_ids": [],
            "enable_images": False,
            "created_at": created_at,
            "updated_at": created_at,
            "result": result,
            "result_path": str(ts_dir),
            "legacy": True,
        }

    # ------------------------------------------------------------------

    def list_outputs(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        base_dir = self._base_dir(notebook_id, notebook_title, user_id)
        items = self._read_manifest(manifest_path)
        changed = False
        hydrated_items: List[Dict[str, Any]] = []
        for item in items:
            next_item, item_changed = self._hydrate_ppt_item_from_disk(item, base_dir)
            hydrated_items.append(next_item)
            changed = changed or item_changed
        if changed:
            self._write_manifest(manifest_path, hydrated_items)

        # Merge legacy outputs that are not in the v2 manifest
        v2_ids = {str(item.get("id") or "") for item in hydrated_items}
        try:
            legacy_items = self._scan_legacy_outputs(
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                user_id=user_id,
                v2_ids=v2_ids,
            )
        except Exception as exc:
            log.warning(
                "[outputs_v2] legacy output scan failed notebook_id=%s error=%s",
                notebook_id,
                exc,
            )
            legacy_items = []

        all_items = hydrated_items + legacy_items
        return sorted(all_items, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def get_output(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        output_id: str,
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        base_dir = self._base_dir(notebook_id, notebook_title, user_id)

        # Try manifest first
        for index, item in enumerate(manifest):
            if item.get("id") == output_id:
                next_item, changed = self._hydrate_ppt_item_from_disk(item, base_dir)
                if changed:
                    manifest[index] = next_item
                    self._write_manifest(manifest_path, manifest)
                return next_item

        # Fallback: check legacy outputs for items with "legacy_" prefix
        if output_id.startswith("legacy_"):
            v2_ids = {str(item.get("id") or "") for item in manifest}
            legacy_items = self._scan_legacy_outputs(
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                user_id=user_id,
                v2_ids=v2_ids,
            )
            for legacy_item in legacy_items:
                if legacy_item.get("id") == output_id:
                    return legacy_item

        raise HTTPException(status_code=404, detail="Output not found")

    def _truncate_text(self, text: str, max_chars: int) -> str:
        cleaned = str(text or "").strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip() + "\n\n[内容已截断]"

    def _normalize_source_names(self, source_paths: List[str], source_names: List[str]) -> List[str]:
        names = [str(name or "").strip() for name in source_names]
        while len(names) < len(source_paths):
            names.append(Path(source_paths[len(names)]).name)
        return names[: len(source_paths)]

    def _build_ppt_context_query(
        self,
        *,
        prompt: str,
        source_names: List[str],
        document: Dict[str, Any],
        bound_documents: List[Dict[str, Any]],
        guidance_text: str,
    ) -> str:
        sections: List[str] = ["[任务说明]", "请生成真正可用于 PPT 的页级大纲。"]
        if source_names:
            source_lines = [f"- 来源{i + 1}: {name}" for i, name in enumerate(source_names)]
            sections.extend(["", "[原始来源清单]", "\n".join(source_lines)])
        cleaned_prompt = str(prompt or "").strip()
        if cleaned_prompt:
            sections.extend(["", "[用户本次产出目标]", cleaned_prompt])
        sections.extend(
            [
                "",
                "[优先级规则]",
                "1. 原始来源内容是第一优先级，必须以它为准。",
                "2. 梳理文档和参考文档只能帮助组织结构、补充上下文，不能覆盖来源事实。",
                "3. 产出指导用于匹配重点、风格和讲述顺序，但不能引入来源中不存在的事实。",
            ]
        )
        if str(guidance_text or "").strip():
            sections.extend(["", "[产出指导]", self._truncate_text(guidance_text, 4000)])
        if str(document.get('content') or "").strip():
            sections.extend(["", "[梳理文档]", self._truncate_text(str(document.get('content') or ''), 6000)])
        if bound_documents:
            bound_parts: List[str] = []
            for doc in bound_documents[:4]:
                text = self._truncate_text(str(doc.get("content") or ""), 2400)
                if not text:
                    continue
                bound_parts.append(f"## {doc.get('title') or '参考文档'}\n{text}")
            if bound_parts:
                sections.extend(["", "[补充参考文档]", "\n\n".join(bound_parts)])
        sections.extend(
            [
                "",
                "[输出目标]",
                "请写成 PPT 页面大纲，而不是文档章节标题。",
                "每页都要像真实 slide：有页面标题、布局方式、3-5 个适合上屏的关键点。",
                "尽量让内容组织匹配产出指导的要求，但事实必须服从原始来源。",
            ]
        )
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def _build_ppt_fallback_text(
        self,
        *,
        document: Dict[str, Any],
        bound_documents: List[Dict[str, Any]],
        guidance_text: str,
    ) -> str:
        parts: List[str] = []
        if str(document.get("content") or "").strip():
            parts.append(f"主文档：\n{self._truncate_text(str(document.get('content') or ''), 8000)}")
        for doc in bound_documents[:4]:
            content = self._truncate_text(str(doc.get("content") or ""), 3000)
            if not content:
                continue
            parts.append(f"参考文档 {doc.get('title') or '未命名'}：\n{content}")
        if str(guidance_text or "").strip():
            parts.append(f"产出指导：\n{self._truncate_text(guidance_text, 4000)}")
        return "\n\n".join(parts).strip()

    def _normalize_key_points(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item or "").strip() for item in value if str(item or "").strip()]
        if isinstance(value, str):
            return [line.strip(" -") for line in value.splitlines() if line.strip()]
        return []

    def _normalize_ppt_outline_item(self, item: Dict[str, Any], index: int) -> Dict[str, Any]:
        key_points = self._normalize_key_points(item.get("key_points") or item.get("bullets") or [])
        layout_description = str(item.get("layout_description") or item.get("summary") or "").strip()
        normalized = {
            "id": item.get("id") or f"slide_{index + 1}",
            "pageNum": int(item.get("pageNum") or index + 1),
            "title": str(item.get("title") or f"第 {index + 1} 页").strip(),
            "layout_description": layout_description,
            "key_points": key_points,
            "asset_ref": item.get("asset_ref"),
            "summary": str(item.get("summary") or layout_description).strip(),
            "bullets": key_points,
        }
        for key in (
            "ppt_img_path",
            "generated_img_path",
            "img_path",
            "image_path",
            "path",
            "source_img_path",
            "reference_image_path",
        ):
            if item.get(key):
                normalized[key] = item.get(key)
        return normalized

    def _normalize_ppt_outline(self, outline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self._normalize_ppt_outline_item(item or {}, index) for index, item in enumerate(outline or [])]

    def _attach_ppt_page_images_from_disk(
        self,
        outline: List[Dict[str, Any]],
        *,
        pipeline_dir: Optional[Path],
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_ppt_outline(outline)
        if pipeline_dir is None:
            return normalized
        pages_dir = pipeline_dir / "ppt_pages"
        if not pages_dir.exists():
            return normalized

        for index, slide in enumerate(normalized):
            candidates = [
                pages_dir / f"page_{index:03d}.png",
                pages_dir / f"page_{index + 1:03d}.png",
            ]
            image_path = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.exists() and self._is_valid_image_file(candidate)
                ),
                None,
            )
            if image_path is not None:
                slide["generated_img_path"] = _to_outputs_url(str(image_path))
        return normalized

    def _remap_legacy_pipeline_dir(self, pipeline_dir: Optional[Path], base_dir: Path) -> Optional[Path]:
        """Remap a stale outputs_v2/{out_id}/ppt_pipeline path to workspace/outputs/{out_id}/ppt_pipeline.

        After workspace migration the physical files live under workspace/outputs/ but older
        manifest entries still carry the pre-migration outputs_v2/ absolute path.  When that
        path does not exist on disk we try to find the equivalent directory under the current
        canonical base_dir (workspace/outputs/).
        """
        if pipeline_dir is None:
            return None
        if pipeline_dir.exists():
            return pipeline_dir
        # Try to re-anchor: extract the out_* segment and rebuild under base_dir
        parts = pipeline_dir.parts
        for i, part in enumerate(parts):
            if part.startswith("out_"):
                # Rebuild: base_dir / out_* / rest...
                tail = Path(*parts[i:])
                candidate = base_dir / tail
                if candidate.exists():
                    log.info(
                        "[outputs_v2] remapped legacy pipeline_dir %s → %s",
                        pipeline_dir,
                        candidate,
                    )
                    return candidate
                break
        return pipeline_dir

    def _hydrate_ppt_item_from_disk(
        self, item: Dict[str, Any], base_dir: Optional[Path] = None
    ) -> tuple[Dict[str, Any], bool]:
        if item.get("target_type") != "ppt":
            return item, False

        changed = False
        pipeline_dir_raw = str(item.get("result_path") or item.get("result", {}).get("result_path") or "").strip()
        pipeline_dir = Path(pipeline_dir_raw) if pipeline_dir_raw else None
        # Remap stale outputs_v2 paths that were not updated after workspace migration
        if base_dir is not None:
            pipeline_dir = self._remap_legacy_pipeline_dir(pipeline_dir, base_dir)
        output_dir = pipeline_dir.parent if pipeline_dir is not None else None

        outline = self._normalize_ppt_outline(item.get("outline") or [])
        hydrated_outline = self._attach_ppt_page_images_from_disk(outline, pipeline_dir=pipeline_dir)

        page_versions, versions_changed = self._upgrade_legacy_ppt_page_versions(
            item.get("page_versions") or [],
            output_dir=output_dir,
            pipeline_dir=pipeline_dir,
        )
        if versions_changed:
            item["page_versions"] = page_versions
            changed = True

        page_versions = self._normalize_ppt_page_versions(item.get("page_versions") or [])
        if page_versions != (item.get("page_versions") or []):
            item["page_versions"] = page_versions
            changed = True

        selected_outline = self._apply_selected_ppt_page_versions(hydrated_outline, page_versions)
        if selected_outline != (item.get("outline") or []):
            item["outline"] = selected_outline
            changed = True

        result = item.get("result")
        if isinstance(result, dict):
            result_outline = self._normalize_ppt_outline(result.get("pagecontent") or selected_outline)
            hydrated_result_outline = self._attach_ppt_page_images_from_disk(result_outline, pipeline_dir=pipeline_dir)
            selected_result_outline = self._apply_selected_ppt_page_versions(hydrated_result_outline, page_versions)
            if selected_result_outline != (result.get("pagecontent") or []):
                result["pagecontent"] = selected_result_outline
                changed = True

            if pipeline_dir is not None:
                pdf_path = pipeline_dir / "paper2ppt.pdf"
                pptx_path = pipeline_dir / "paper2ppt_editable.pptx"
                if pdf_path.exists():
                    pdf_url = _to_outputs_url(str(pdf_path))
                    if result.get("ppt_pdf_path") != pdf_url:
                        result["ppt_pdf_path"] = pdf_url
                        changed = True
                    if not str(result.get("download_url") or "").strip():
                        result["download_url"] = pdf_url
                        changed = True
                if pptx_path.exists():
                    pptx_url = _to_outputs_url(str(pptx_path))
                    if result.get("ppt_pptx_path") != pptx_url:
                        result["ppt_pptx_path"] = pptx_url
                        changed = True

        return item, changed

    def _read_json_file(self, path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _discover_legacy_ppt_page_version_candidates(
        self,
        *,
        pipeline_dir: Optional[Path],
        page_index: int,
    ) -> List[Dict[str, Any]]:
        if pipeline_dir is None:
            return []
        pages_dir = pipeline_dir / "ppt_pages"
        if not pages_dir.exists():
            return []

        candidates: List[Dict[str, Any]] = []
        for image_path in sorted(pages_dir.glob(f"page_{page_index:03d}_v*.png")):
            meta = self._read_json_file(image_path.with_suffix(".json"))
            version_raw = meta.get("version")
            if version_raw is None:
                match = re.search(r"_v(\d+)$", image_path.stem)
                version_raw = int(match.group(1)) if match else 0
            try:
                version_num = int(version_raw)
            except Exception:
                version_num = 0
            try:
                timestamp = int(meta.get("timestamp") or 0)
            except Exception:
                timestamp = 0
            candidates.append(
                {
                    "prompt": str(meta.get("prompt") or "").strip(),
                    "preview_path": _to_outputs_url(str(image_path)),
                    "version_num": version_num,
                    "timestamp": timestamp,
                }
            )

        return sorted(
            candidates,
            key=lambda item: (
                int(item.get("timestamp") or 0),
                int(item.get("version_num") or 0),
                str(item.get("preview_path") or ""),
            ),
        )

    def _is_mutable_ppt_page_preview_path(self, preview_path: str, *, page_index: int) -> bool:
        value = str(preview_path or "").strip()
        if not value:
            return False
        return value.endswith(f"/ppt_pipeline/ppt_pages/page_{page_index:03d}.png")

    def _set_page_version_preview_path(
        self,
        item: Dict[str, Any],
        *,
        preview_path: str,
    ) -> Dict[str, Any]:
        next_item = dict(item)
        next_item["preview_path"] = preview_path
        snapshot = next_item.get("slide_snapshot")
        if isinstance(snapshot, dict):
            next_snapshot = dict(snapshot)
            next_snapshot["generated_img_path"] = preview_path
            next_snapshot["ppt_img_path"] = preview_path
            next_item["slide_snapshot"] = next_snapshot
        return next_item

    def _upgrade_legacy_ppt_page_versions(
        self,
        page_versions: Optional[List[Dict[str, Any]]],
        *,
        output_dir: Optional[Path],
        pipeline_dir: Optional[Path],
    ) -> tuple[List[Dict[str, Any]], bool]:
        if not page_versions:
            return [], False

        grouped: Dict[int, List[Dict[str, Any]]] = {}
        ordered: List[Dict[str, Any]] = []
        for raw in page_versions or []:
            if not isinstance(raw, dict):
                continue
            current = dict(raw)
            ordered.append(current)
            try:
                page_index = int(current.get("page_index", -1))
            except Exception:
                page_index = -1
            grouped.setdefault(page_index, []).append(current)

        replacements: Dict[str, Dict[str, Any]] = {}
        changed = False
        for page_index, entries in grouped.items():
            if page_index < 0:
                continue
            needs_upgrade = any(
                self._is_mutable_ppt_page_preview_path(str(entry.get("preview_path") or ""), page_index=page_index)
                for entry in entries
            )
            if not needs_upgrade:
                continue

            candidates = self._discover_legacy_ppt_page_version_candidates(
                pipeline_dir=pipeline_dir,
                page_index=page_index,
            )
            if not candidates:
                continue

            remaining = list(candidates)
            sorted_entries = sorted(entries, key=lambda entry: str(entry.get("created_at") or ""))

            for entry in sorted_entries:
                prompt = str(entry.get("prompt") or "").strip()
                if not prompt:
                    continue
                match_index = next(
                    (
                        idx
                        for idx, candidate in enumerate(remaining)
                        if str(candidate.get("prompt") or "").strip() == prompt
                    ),
                    -1,
                )
                if match_index < 0:
                    continue
                candidate = remaining.pop(match_index)
                frozen_path = self._freeze_ppt_page_version_asset(
                    str(candidate.get("preview_path") or ""),
                    output_dir=output_dir,
                    page_index=page_index,
                    version_id=str(entry.get("id") or f"pv_{uuid4().hex[:12]}"),
                )
                replacements[str(entry.get("id") or "")] = self._set_page_version_preview_path(
                    entry,
                    preview_path=frozen_path or str(candidate.get("preview_path") or ""),
                )
                changed = True

            if not remaining:
                continue

            unmatched_entries = [
                entry
                for entry in sorted_entries
                if str(entry.get("id") or "") not in replacements
            ]
            for entry, candidate in zip(unmatched_entries, remaining):
                frozen_path = self._freeze_ppt_page_version_asset(
                    str(candidate.get("preview_path") or ""),
                    output_dir=output_dir,
                    page_index=page_index,
                    version_id=str(entry.get("id") or f"pv_{uuid4().hex[:12]}"),
                )
                replacements[str(entry.get("id") or "")] = self._set_page_version_preview_path(
                    entry,
                    preview_path=frozen_path or str(candidate.get("preview_path") or ""),
                )
                changed = True

        if not changed:
            return ordered, False

        upgraded: List[Dict[str, Any]] = []
        for item in ordered:
            version_id = str(item.get("id") or "")
            upgraded.append(replacements.get(version_id, item))
        return upgraded, True

    def _strip_ppt_generated_assets(self, outline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized = self._normalize_ppt_outline(outline)
        for item in sanitized:
            for key in (
                "ppt_img_path",
                "generated_img_path",
                "img_path",
                "image_path",
                "path",
                "source_img_path",
                "reference_image_path",
            ):
                item.pop(key, None)
        return sanitized

    def _build_ppt_page_reviews(
        self,
        outline: List[Dict[str, Any]],
        existing: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        existing_map: Dict[int, Dict[str, Any]] = {}
        for review in existing or []:
            try:
                review_index = int(review.get("page_index"))
            except Exception:
                continue
            existing_map[review_index] = review

        reviews: List[Dict[str, Any]] = []
        now = self._now()
        for index, slide in enumerate(self._normalize_ppt_outline(outline)):
            current = existing_map.get(index) or {}
            confirmed = bool(current.get("confirmed", False))
            reviews.append(
                {
                    "page_index": index,
                    "page_num": int(slide.get("pageNum") or index + 1),
                    "confirmed": confirmed,
                    "confirmed_at": current.get("confirmed_at") if confirmed else "",
                    "updated_at": current.get("updated_at") or now,
                }
            )
        return reviews

    def _set_ppt_page_confirmed(
        self,
        page_reviews: List[Dict[str, Any]],
        *,
        page_index: int,
        confirmed: bool,
    ) -> List[Dict[str, Any]]:
        now = self._now()
        next_reviews: List[Dict[str, Any]] = []
        for review in page_reviews:
            review_index_raw = review.get("page_index", -1)
            try:
                review_index = int(review_index_raw)
            except Exception:
                review_index = -1
            if review_index != page_index:
                next_reviews.append(review)
                continue
            next_reviews.append(
                {
                    **review,
                    "confirmed": confirmed,
                    "confirmed_at": now if confirmed else "",
                    "updated_at": now,
                }
            )
        return next_reviews

    def _build_ppt_page_versions(
        self,
        outline: List[Dict[str, Any]],
        *,
        source: str,
        prompt: str = "",
        page_index: Optional[int] = None,
        output_dir: Optional[Path] = None,
        existing: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        now = self._now()
        next_versions: List[Dict[str, Any]] = []
        if existing:
            next_versions.extend([dict(item) for item in existing if isinstance(item, dict)])

        normalized = self._normalize_ppt_outline(outline)
        for index, slide in enumerate(normalized):
            if page_index is not None and index != page_index:
                continue
            preview_path = str(slide.get("generated_img_path") or slide.get("ppt_img_path") or "").strip()
            if not preview_path:
                continue
            version_id = f"pv_{uuid4().hex[:12]}"
            frozen_preview_path = self._freeze_ppt_page_version_asset(
                preview_path,
                output_dir=output_dir,
                page_index=index,
                version_id=version_id,
            )
            snapshot = dict(slide)
            if frozen_preview_path:
                snapshot["generated_img_path"] = frozen_preview_path
                snapshot["ppt_img_path"] = frozen_preview_path
            next_versions = [
                {
                    **item,
                    "selected": False,
                }
                if int(item.get("page_index", -1)) == index
                else item
                for item in next_versions
            ]
            next_versions.append(
                {
                    "id": version_id,
                    "page_index": index,
                    "page_num": int(slide.get("pageNum") or index + 1),
                    "title": str(slide.get("title") or f"页面 {index + 1}").strip(),
                    "source": source,
                    "prompt": str(prompt or "").strip(),
                    "preview_path": frozen_preview_path or preview_path,
                    "selected": True,
                    "created_at": now,
                    "slide_snapshot": snapshot,
                }
            )
        return next_versions

    def _freeze_ppt_page_version_asset(
        self,
        preview_path: str,
        *,
        output_dir: Optional[Path],
        page_index: int,
        version_id: str,
    ) -> str:
        source_value = str(preview_path or "").strip()
        if not source_value or output_dir is None:
            return source_value
        try:
            source_path = Path(_from_outputs_url(source_value))
            if not source_path.exists() or not source_path.is_file():
                return source_value
            target_dir = output_dir / "page_versions" / f"page_{page_index:03d}"
            target_dir.mkdir(parents=True, exist_ok=True)
            suffix = source_path.suffix or ".png"
            target_path = target_dir / f"{version_id}{suffix}"
            shutil.copy2(source_path, target_path)
            return _to_outputs_url(str(target_path))
        except Exception as exc:
            log.warning(
                "[outputs_v2] freeze ppt page version asset failed page_index=%s version_id=%s error=%s",
                page_index,
                version_id,
                exc,
            )
            return source_value

    def _normalize_ppt_page_versions(self, page_versions: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        ordered: List[Dict[str, Any]] = []
        for item in page_versions or []:
            if not isinstance(item, dict):
                continue
            current = dict(item)
            try:
                page_index = int(current.get("page_index", -1))
            except Exception:
                page_index = -1
            grouped.setdefault(page_index, []).append(current)
            ordered.append(current)

        selected_ids: Dict[int, str] = {}
        for page_index, entries in grouped.items():
            if page_index < 0:
                continue
            explicit = [entry for entry in entries if bool(entry.get("selected"))]
            pool = explicit or entries
            winner = max(pool, key=lambda entry: str(entry.get("created_at") or ""))
            selected_ids[page_index] = str(winner.get("id") or "")

        normalized: List[Dict[str, Any]] = []
        for item in ordered:
            try:
                page_index = int(item.get("page_index", -1))
            except Exception:
                page_index = -1
            item["selected"] = bool(str(item.get("id") or "") and selected_ids.get(page_index) == str(item.get("id") or ""))
            normalized.append(item)
        return normalized

    def _apply_selected_ppt_page_versions(
        self,
        outline: List[Dict[str, Any]],
        page_versions: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_ppt_outline(outline)
        selected_map: Dict[int, Dict[str, Any]] = {}
        for item in page_versions or []:
            if not bool(item.get("selected")):
                continue
            try:
                page_index = int(item.get("page_index"))
            except Exception:
                continue
            selected_map[page_index] = item

        if not selected_map:
            return normalized

        next_outline: List[Dict[str, Any]] = []
        for index, slide in enumerate(normalized):
            version = selected_map.get(index)
            if not version:
                next_outline.append(slide)
                continue
            snapshot = version.get("slide_snapshot")
            if isinstance(snapshot, dict):
                next_outline.append(self._normalize_ppt_outline_item(snapshot, index))
                continue
            preview_path = str(version.get("preview_path") or "").strip()
            if preview_path:
                next_outline.append({**slide, "generated_img_path": preview_path})
            else:
                next_outline.append(slide)
        return next_outline

    def _select_ppt_page_version(
        self,
        page_versions: Optional[List[Dict[str, Any]]],
        *,
        page_index: int,
        version_id: str,
    ) -> List[Dict[str, Any]]:
        found = False
        next_versions: List[Dict[str, Any]] = []
        for item in page_versions or []:
            if not isinstance(item, dict):
                continue
            try:
                current_index = int(item.get("page_index"))
            except Exception:
                current_index = -1
            if current_index != page_index:
                next_versions.append(dict(item))
                continue
            current = dict(item)
            current["selected"] = current.get("id") == version_id
            if current["selected"]:
                found = True
            next_versions.append(current)
        if not found:
            raise HTTPException(status_code=404, detail="PPT page version not found")
        return next_versions

    def _all_ppt_pages_confirmed(self, page_reviews: List[Dict[str, Any]]) -> bool:
        return bool(page_reviews) and all(bool(item.get("confirmed")) for item in page_reviews)

    def _reset_ppt_generation_state(self, item: Dict[str, Any]) -> Dict[str, Any]:
        cleaned_outline = self._strip_ppt_generated_assets(item.get("outline") or [])
        item["outline"] = cleaned_outline
        item["page_reviews"] = self._build_ppt_page_reviews(cleaned_outline, [])
        item["page_versions"] = []
        item["result"] = {}
        return item

    def _prepare_ppt_outline_for_generation(self, outline: List[Dict[str, Any]], enable_images: bool) -> List[Dict[str, Any]]:
        prepared = self._normalize_ppt_outline(outline)
        if enable_images:
            return prepared
        for item in prepared:
            item["asset_ref"] = None
        return prepared

    def _is_valid_image_file(self, path: Path) -> bool:
        try:
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
            return True
        except Exception:
            return False

    def _build_partial_ppt_result_from_disk(
        self,
        *,
        item: Dict[str, Any],
        error: Exception,
    ) -> Optional[Dict[str, Any]]:
        result_path = str(item.get("result_path") or "").strip()
        if not result_path:
            return None
        pipeline_dir = Path(result_path)
        pages_dir = pipeline_dir / "ppt_pages"
        if not pages_dir.exists():
            return None

        outline = self._attach_ppt_page_images_from_disk(
            item.get("outline") or [],
            pipeline_dir=pipeline_dir,
        )
        any_valid = any(
            str(slide.get("generated_img_path") or slide.get("ppt_img_path") or "").strip()
            for slide in outline
        )

        if not any_valid:
            return None

        partial_result: Dict[str, Any] = {
            "success": False,
            "partial": True,
            "partial_failure": f"{type(error).__name__}: {error}",
            "pagecontent": outline,
            "download_url": "",
        }
        pdf_path = pipeline_dir / "paper2ppt.pdf"
        pptx_path = pipeline_dir / "paper2ppt_editable.pptx"
        if pdf_path.exists():
            partial_result["ppt_pdf_path"] = _to_outputs_url(str(pdf_path))
            partial_result["download_url"] = partial_result["ppt_pdf_path"]
        if pptx_path.exists():
            partial_result["ppt_pptx_path"] = _to_outputs_url(str(pptx_path))
            partial_result["download_url"] = partial_result.get("download_url") or partial_result["ppt_pptx_path"]
        return partial_result

    def _urlize_payload_paths(self, value: Any, key: str = "") -> Any:
        from fastapi_app.utils import _from_outputs_url

        if isinstance(value, dict):
            return {k: self._urlize_payload_paths(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._urlize_payload_paths(item, key) for item in value]
        if not isinstance(value, str):
            return value
        if key == "result_path":
            return value
        raw = _from_outputs_url(value)
        candidate = Path(raw)
        if not candidate.is_absolute():
            try:
                candidate = candidate.resolve()
            except Exception:
                return value
        if candidate.exists() and candidate.is_file():
            return _to_outputs_url(str(candidate))
        return value

    async def _create_ppt_outline_payload(
        self,
        *,
        output_dir: Path,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        email: str,
        page_count: int,
        source_paths: List[str],
        source_names: List[str],
        document: Dict[str, Any],
        bound_documents: List[Dict[str, Any]],
        guidance_text: str,
        prompt: str,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
        enable_images: bool,
    ) -> Dict[str, Any]:
        from fastapi_app.routers.kb import (
            IMAGE_EXTENSIONS,
            _convert_to_pdf,
            _extract_text_from_files,
            _merge_pdfs,
            _read_mineru_md_if_cached,
            _require_llm_config,
            _require_workflow_available,
            _resolve_link_to_local_md,
            _resolve_local_path,
            _reuse_mineru_cache,
        )
        from fastapi_app.schemas import Paper2PPTRequest
        from fastapi_app.services.wa_paper2ppt import _init_state_from_request
        from workflow_engine.toolkits.research_tools import fetch_page_text
        from workflow_engine.workflow import run_workflow

        _require_workflow_available("kb_page_content", feature_label="PPT 大纲生成")
        api_url, api_key = _require_llm_config(api_url, api_key)

        input_paths = [str(path or "").strip() for path in source_paths or [] if str(path or "").strip()]
        url_sources: List[str] = []
        path_sources: List[Path] = []
        seen_resolved: set[str] = set()
        for raw_path in input_paths:
            if raw_path.startswith("http://") or raw_path.startswith("https://"):
                url_sources.append(raw_path)
                continue
            local_path = _resolve_local_path(raw_path)
            if not local_path.exists():
                raise HTTPException(status_code=404, detail=f"File not found: {raw_path}")
            ext = local_path.suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                continue
            if ext in {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".md", ".markdown"}:
                key = str(local_path.resolve())
                if key not in seen_resolved:
                    seen_resolved.add(key)
                    path_sources.append(local_path)
                continue
            raise HTTPException(status_code=400, detail=f"Unsupported file type for PPT: {local_path.name}")

        pipeline_dir = output_dir / "ppt_pipeline"
        pipeline_dir.mkdir(parents=True, exist_ok=True)

        md_exts = {".md", ".markdown"}
        pdf_like_exts = {".pdf", ".pptx", ".ppt", ".docx", ".doc"}
        use_text_input = bool(url_sources) or any(path.suffix.lower() in md_exts for path in path_sources)
        combined_text = ""
        local_file_path: Optional[Path] = None
        pdf_paths_for_outline: List[Path] = []

        if input_paths:
            if use_text_input:
                text_parts: List[str] = []
                for path_value in input_paths:
                    if path_value.startswith("http://") or path_value.startswith("https://"):
                        content = None
                        local_md = _resolve_link_to_local_md(email, notebook_id, path_value)
                        if local_md is not None and local_md.exists():
                            try:
                                content = local_md.read_text(encoding="utf-8", errors="replace")
                            except Exception:
                                content = None
                        if not (content or "").strip():
                            try:
                                content = fetch_page_text(path_value, max_chars=100000)
                            except Exception:
                                content = None
                        if (content or "").strip():
                            text_parts.append(f"来源{text_parts.__len__() + 1}:\n{content.strip()}")
                        continue

                    local_path = _resolve_local_path(path_value)
                    if not local_path.exists():
                        continue
                    ext = local_path.suffix.lower()
                    content = ""
                    try:
                        if ext in md_exts:
                            content = local_path.read_text(encoding="utf-8")
                        elif ext == ".pdf":
                            content = _read_mineru_md_if_cached(local_path, email, notebook_id, notebook_title=notebook_title) or _extract_text_from_files([str(local_path)])
                        elif ext in pdf_like_exts:
                            content = _extract_text_from_files([str(local_path)])
                    except Exception:
                        content = ""
                    if content.strip():
                        text_parts.append(f"来源{text_parts.__len__() + 1}:\n{content.strip()}")
                combined_text = "\n\n".join(text_parts).strip()
            else:
                local_pdf_paths: List[Path] = []
                convert_dir = pipeline_dir / "input"
                convert_dir.mkdir(parents=True, exist_ok=True)
                for path in path_sources:
                    ext = path.suffix.lower()
                    if ext == ".pdf":
                        local_pdf_paths.append(path)
                    elif ext in {".pptx", ".ppt", ".docx", ".doc"}:
                        local_pdf_paths.append(_convert_to_pdf(path, convert_dir))
                pdf_paths_for_outline = local_pdf_paths
                if len(local_pdf_paths) > 1:
                    local_file_path = _merge_pdfs(local_pdf_paths, convert_dir / "merged.pdf")
                elif local_pdf_paths:
                    local_file_path = local_pdf_paths[0]

        if not input_paths or (use_text_input and not combined_text):
            fallback_text = self._build_ppt_fallback_text(
                document=document,
                bound_documents=bound_documents,
                guidance_text=guidance_text,
            )
            if fallback_text:
                use_text_input = True
                combined_text = fallback_text

        if not use_text_input and local_file_path is None:
            raise HTTPException(status_code=400, detail="PPT 生成需要至少一个来源，或可用的梳理文档内容。")

        ppt_req = Paper2PPTRequest(
            input_type="TEXT" if use_text_input else "PDF",
            input_content=combined_text if use_text_input else str(local_file_path),
            email=email,
            chat_api_url=api_url,
            chat_api_key=api_key,
            api_key=api_key,
            style="modern",
            language="zh",
            page_count=page_count,
            model=model or settings.PAPER2PPT_OUTLINE_MODEL,
            gen_fig_model=settings.PAPER2PPT_IMAGE_GEN_MODEL,
            aspect_ratio="16:9",
            use_long_paper=False,
        )
        state_pc = _init_state_from_request(ppt_req, result_path=pipeline_dir)
        state_pc.kb_query = self._build_ppt_context_query(
            prompt=prompt,
            source_names=source_names,
            document=document,
            bound_documents=bound_documents,
            guidance_text=guidance_text,
        )
        if not use_text_input and pdf_paths_for_outline:
            _reuse_mineru_cache(pdf_paths_for_outline, pipeline_dir, email, notebook_id, notebook_title=notebook_title)
            if len(pdf_paths_for_outline) > 1:
                multi_parts: List[str] = []
                for index, pdf_path in enumerate(pdf_paths_for_outline, start=1):
                    part = _read_mineru_md_if_cached(pdf_path, email, notebook_id, notebook_title=notebook_title)
                    if not part:
                        part = _extract_text_from_files([str(pdf_path)])
                    if part.strip():
                        multi_parts.append(f"来源{index}:\n{part}")
                if multi_parts:
                    state_pc.kb_multi_source_text = "\n\n".join(multi_parts)

        state_pc_result = await run_workflow("kb_page_content", state_pc)
        if isinstance(state_pc_result, dict):
            for key, value in state_pc_result.items():
                setattr(state_pc, key, value)
        else:
            state_pc = state_pc_result
        outline = self._normalize_ppt_outline(getattr(state_pc, "pagecontent", []) or [])
        if not enable_images:
            outline = self._prepare_ppt_outline_for_generation(outline, enable_images=False)
        if not outline:
            raise HTTPException(status_code=500, detail="PPT 大纲生成结果为空，请检查来源或重试。")

        mineru_root = self._resolve_mineru_content_dir(Path(str(getattr(state_pc, "mineru_root", "") or "").strip())) \
            if str(getattr(state_pc, "mineru_root", "") or "").strip() else ""

        self._write_json(
            pipeline_dir / "context.json",
            self._build_ppt_context_payload(
                outline=outline,
                raw_pagecontent=getattr(state_pc, "pagecontent", []) or [],
                mineru_root=mineru_root,
                query=state_pc.kb_query,
                source_paths=source_paths,
                source_names=source_names,
                page_count=page_count,
                enable_images=enable_images,
            ),
        )
        return {
            "outline": outline,
            "result_path": str(pipeline_dir),
            "query": state_pc.kb_query,
        }

    async def create_outline(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        document_id: str,
        target_type: str,
        title: str,
        prompt: str,
        page_count: int,
        guidance_item_ids: Optional[List[str]] = None,
        source_paths: Optional[List[str]] = None,
        source_names: Optional[List[str]] = None,
        bound_document_ids: Optional[List[str]] = None,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        enable_images: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if target_type not in self.SUPPORTED_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported output type")

        if target_type != "ppt" and not document_id:
            raise HTTPException(status_code=400, detail="document_id is required")

        document = self._maybe_load_document(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            document_id=document_id,
        )
        guidance_items = self._load_guidance_items(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            guidance_item_ids=guidance_item_ids or [],
        )
        bound_documents = self._load_bound_documents(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            bound_document_ids=bound_document_ids or [],
        )
        guidance_snapshot_text = self._build_guidance_snapshot_text(guidance_items)
        output_id = f"out_{uuid4().hex[:12]}"
        now = self._now()
        normalized_page_count = max(1, min(page_count, 20))
        normalized_source_paths = [str(path or "").strip() for path in source_paths or [] if str(path or "").strip()]
        normalized_source_names = self._normalize_source_names(normalized_source_paths, source_names or [])
        normalized_enable_images = True if enable_images is None else bool(enable_images)

        output_dir = self._item_dir(notebook_id, notebook_title, user_id, output_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        document_md = output_dir / "source_document.md"
        if str(document.get("content") or "").strip():
            document_md.write_text(document.get("content") or "", encoding="utf-8")

        if target_type == "ppt":
            ppt_payload = await self._run_with_backend_llm_fallback(
                label="create_outline:ppt",
                api_url=api_url,
                api_key=api_key,
                operation=lambda resolved_api_url, resolved_api_key: self._create_ppt_outline_payload(
                    output_dir=output_dir,
                    notebook_id=notebook_id,
                    notebook_title=notebook_title,
                    user_id=user_id,
                    email=user_id,
                    page_count=normalized_page_count,
                    source_paths=normalized_source_paths,
                    source_names=normalized_source_names,
                    document=document,
                    bound_documents=bound_documents,
                    guidance_text=guidance_snapshot_text,
                    prompt=prompt,
                    api_url=resolved_api_url,
                    api_key=resolved_api_key,
                    model=model,
                    enable_images=normalized_enable_images,
                ),
            )
            outline = ppt_payload["outline"]
            stage = self.PPT_STAGE_OUTLINE
            result_payload: Dict[str, Any] = {}
            result_path = str(ppt_payload["result_path"])
        else:
            outline = self._fallback_outline(
                target_type=target_type,
                title=title or document.get("title") or target_type,
                content="\n\n".join(
                    [
                        str(document.get("content") or "").strip(),
                        guidance_snapshot_text,
                    ]
                ).strip(),
                page_count=normalized_page_count,
            )
            stage = "outlined"
            result_payload = {}
            result_path = ""

        self._write_json(output_dir / "outline.json", {"outline": outline})
        item = {
            "id": output_id,
            "document_id": document_id,
            "title": (title or "").strip() or f"{document.get('title') or '文档'}_{target_type}",
            "target_type": target_type,
            "prompt": prompt,
            "status": stage,
            "pipeline_stage": stage,
            "outline": outline,
            "page_reviews": self._build_ppt_page_reviews(outline, []) if target_type == "ppt" else [],
            "page_versions": [],
            "page_count": normalized_page_count,
            "guidance_item_ids": guidance_item_ids or [],
            "guidance_snapshot_text": guidance_snapshot_text,
            "source_paths": normalized_source_paths,
            "source_names": normalized_source_names,
            "bound_document_ids": bound_document_ids or [],
            "bound_document_titles": [doc.get("title") or "参考文档" for doc in bound_documents],
            "enable_images": normalized_enable_images,
            "created_at": now,
            "updated_at": now,
            "result": result_payload,
            "result_path": result_path,
            "source_document_path": str(document_md) if document_md.exists() else "",
        }
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        manifest.append(item)
        self._write_manifest(manifest_path, manifest)
        return item

    def save_outline(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        output_id: str,
        title: Optional[str],
        prompt: Optional[str],
        outline: List[Dict[str, Any]],
        pipeline_stage: Optional[str] = None,
        enable_images: Optional[bool] = None,
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        index, item = self._find_output(manifest, output_id)
        next_outline = self._normalize_ppt_outline(outline) if item.get("target_type") == "ppt" else outline
        should_reset_ppt_state = False
        if item.get("target_type") == "ppt":
            current_outline = self._normalize_ppt_outline(item.get("outline") or [])
            outline_changed = json.dumps(current_outline, ensure_ascii=False, sort_keys=True) != json.dumps(
                next_outline,
                ensure_ascii=False,
                sort_keys=True,
            )
            prompt_changed = prompt is not None and str(prompt) != str(item.get("prompt") or "")
            enable_images_changed = enable_images is not None and bool(enable_images) != bool(item.get("enable_images", True))
            current_stage = str(item.get("pipeline_stage") or item.get("status") or self.PPT_STAGE_OUTLINE)
            outline_locked = current_stage in {self.PPT_STAGE_PAGES, self.PPT_STAGE_GENERATED}
            if outline_locked:
                if outline_changed or prompt_changed or enable_images_changed:
                    raise HTTPException(status_code=400, detail="PPT 大纲已确认，当前阶段不支持再修改大纲或生成配置")
                if pipeline_stage and pipeline_stage != current_stage:
                    raise HTTPException(status_code=400, detail="PPT 已进入后续阶段，不支持回退到大纲编辑或切换当前状态")
            should_reset_ppt_state = outline_changed or prompt_changed or enable_images_changed or pipeline_stage == self.PPT_STAGE_OUTLINE
        item["outline"] = next_outline
        if title is not None:
            item["title"] = (title or "").strip() or item.get("title") or "未命名产出"
        if prompt is not None:
            item["prompt"] = prompt
        if pipeline_stage:
            item["pipeline_stage"] = pipeline_stage
            item["status"] = pipeline_stage
        if enable_images is not None:
            item["enable_images"] = bool(enable_images)
        if item.get("target_type") == "ppt":
            if should_reset_ppt_state:
                item = self._reset_ppt_generation_state(item)
                item["pipeline_stage"] = pipeline_stage or self.PPT_STAGE_OUTLINE
                item["status"] = item["pipeline_stage"]
            else:
                item["page_reviews"] = self._build_ppt_page_reviews(next_outline, item.get("page_reviews") or [])
        item["updated_at"] = self._now()
        self._write_json(
            self._item_dir(notebook_id, notebook_title, user_id, output_id) / "outline.json",
            {"outline": item["outline"]},
        )
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        return item

    async def refine_outline(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        email: str,
        output_id: str,
        feedback: str,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        index, item = self._find_output(manifest, output_id)
        if item.get("target_type") != "ppt":
            raise HTTPException(status_code=400, detail="Only PPT outputs support outline refine")
        if not str(feedback or "").strip():
            raise HTTPException(status_code=400, detail="feedback is required")

        from fastapi_app.schemas import OutlineRefineRequest
        from fastapi_app.services.paper2ppt_service import Paper2PPTService

        result_path = str(item.get("result_path") or "").strip()
        if not result_path:
            raise HTTPException(status_code=400, detail="Missing result_path for PPT outline refine")

        service = Paper2PPTService()
        payload = await self._run_with_backend_llm_fallback(
            label="refine_outline:ppt",
            api_url=api_url,
            api_key=api_key,
            operation=lambda resolved_api_url, resolved_api_key: service.refine_outline(
                OutlineRefineRequest(
                    chat_api_url=resolved_api_url or "",
                    api_key=resolved_api_key or "",
                    email=email,
                    model=model or settings.PAPER2PPT_OUTLINE_MODEL,
                    language="zh",
                    result_path=result_path,
                    outline_feedback=str(feedback or "").strip(),
                    pagecontent=json.dumps(item.get("outline") or [], ensure_ascii=False),
                ),
                None,
            ),
        )
        next_outline = self._normalize_ppt_outline(payload.get("pagecontent") or [])
        if not bool(item.get("enable_images", True)):
            next_outline = self._prepare_ppt_outline_for_generation(next_outline, enable_images=False)
        item["outline"] = next_outline
        item["page_reviews"] = self._build_ppt_page_reviews(next_outline, [])
        item["result"] = {}
        item["pipeline_stage"] = self.PPT_STAGE_OUTLINE
        item["status"] = self.PPT_STAGE_OUTLINE
        item["updated_at"] = self._now()
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        self._write_json(
            self._item_dir(notebook_id, notebook_title, user_id, output_id) / "outline.json",
            {"outline": next_outline},
        )
        return item

    def _build_generation_markdown(self, item: Dict[str, Any], document: Dict[str, Any], guidance_text: str = "") -> str:
        lines = [f"# {item.get('title') or document.get('title') or '文档产出'}", ""]
        prompt = str(item.get("prompt") or "").strip()
        if prompt:
            lines.extend(["## 生成意图", "", prompt, ""])
        cleaned_guidance = str(guidance_text or item.get("guidance_snapshot_text") or "").strip()
        if cleaned_guidance:
            lines.extend(["## 产出指导", "", cleaned_guidance, ""])
        lines.extend(["## 产出大纲", ""])
        for section in item.get("outline") or []:
            lines.append(f"### {section.get('title') or '章节'}")
            summary = str(section.get("summary") or "").strip()
            if summary:
                lines.append("")
                lines.append(summary)
            bullets = [str(value or "").strip() for value in section.get("bullets") or [] if str(value or "").strip()]
            if bullets:
                lines.append("")
                for bullet in bullets:
                    lines.append(f"- {bullet}")
            lines.append("")
        lines.extend(["## 原始文档", "", document.get("content") or ""])
        return "\n".join(lines).strip()

    async def _generate_report(
        self,
        *,
        output_dir: Path,
        item: Dict[str, Any],
        document: Dict[str, Any],
        guidance_text: str = "",
    ) -> Dict[str, Any]:
        from fastapi_app.routers.kb import _text_to_pdf

        lines = [f"# {item.get('title') or document.get('title') or '分析报告'}", ""]
        cleaned_guidance = str(guidance_text or item.get("guidance_snapshot_text") or "").strip()
        if cleaned_guidance:
            lines.extend(["## 产出指导", "", cleaned_guidance, ""])
        for section in item.get("outline") or []:
            lines.append(f"## {section.get('title') or '章节'}")
            lines.append("")
            summary = str(section.get("summary") or "").strip()
            if summary:
                lines.append(summary)
                lines.append("")
            for bullet in section.get("bullets") or []:
                bullet_text = str(bullet or "").strip()
                if bullet_text:
                    lines.append(f"- {bullet_text}")
            lines.append("")
        lines.extend(["---", "", document.get("content") or ""])
        report_md = output_dir / "report.md"
        report_md.write_text("\n".join(lines).strip(), encoding="utf-8")
        report_pdf = output_dir / "report.pdf"
        _text_to_pdf(report_md.read_text(encoding="utf-8"), str(report_pdf))
        return {
            "markdown_path": _to_outputs_url(str(report_md)),
            "pdf_path": _to_outputs_url(str(report_pdf)),
            "download_url": _to_outputs_url(str(report_pdf)),
            "preview_markdown": report_md.read_text(encoding="utf-8"),
        }

    async def _generate_via_existing_endpoint(
        self,
        *,
        target_type: str,
        output_dir: Path,
        md_path: Path,
        email: str,
        user_id: str,
        notebook_id: str,
        notebook_title: str,
        prompt: str,
        page_count: int,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        from fastapi_app.routers.kb import (
            generate_flashcards,
            generate_mindmap_from_kb,
            generate_podcast_from_kb,
            generate_quiz,
        )

        payload_model = model or settings.KB_CHAT_MODEL
        if target_type == "mindmap":
            return await generate_mindmap_from_kb(
                file_paths=[str(md_path)],
                user_id=user_id,
                email=email,
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                api_url=api_url,
                api_key=api_key,
                model=payload_model,
            )
        if target_type == "podcast":
            return await generate_podcast_from_kb(
                file_paths=[str(md_path)],
                user_id=user_id,
                email=email,
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                api_url=api_url,
                api_key=api_key,
                model=payload_model,
                tts_model=settings.TTS_MODEL,
                voice_name="Cherry",
                voice_name_b="Chelsie",
                podcast_mode="monologue",
                language="zh",
            )
        if target_type == "flashcard":
            return await generate_flashcards(
                file_paths=[str(md_path)],
                email=email,
                user_id=user_id,
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                api_url=api_url,
                api_key=api_key,
                model=payload_model,
                card_count=page_count,
            )
        if target_type == "quiz":
            return await generate_quiz(
                file_paths=[str(md_path)],
                email=email,
                user_id=user_id,
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                api_url=api_url,
                api_key=api_key,
                model=payload_model,
                question_count=page_count,
            )
        raise HTTPException(status_code=400, detail="Unsupported output type")

    async def _generate_ppt_output(
        self,
        *,
        item: Dict[str, Any],
        email: str,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        from fastapi_app.schemas import PPTGenerationRequest
        from fastapi_app.services.paper2ppt_service import Paper2PPTService

        result_path = str(item.get("result_path") or "").strip()
        if not result_path:
            raise HTTPException(status_code=400, detail="Missing result_path for PPT generation")

        outline = self._prepare_ppt_outline_for_generation(
            item.get("outline") or [],
            enable_images=bool(item.get("enable_images", True)),
        )
        service = Paper2PPTService()
        try:
            payload = await self._run_with_backend_llm_fallback(
                label="generate_output:ppt",
                api_url=api_url,
                api_key=api_key,
                operation=lambda resolved_api_url, resolved_api_key: service.generate_ppt(
                    PPTGenerationRequest(
                        img_gen_model_name=settings.IMAGE_GEN_MODEL or settings.PAPER2PPT_IMAGE_GEN_MODEL,
                        chat_api_url=resolved_api_url or "",
                        api_key=resolved_api_key or "",
                        email=email,
                        style="modern",
                        aspect_ratio="16:9",
                        language="zh",
                        model=model or settings.PAPER2PPT_DEFAULT_MODEL,
                        get_down="false",
                        all_edited_down="false",
                        result_path=result_path,
                        pagecontent=json.dumps(outline, ensure_ascii=False),
                    ),
                    None,
                    None,
                ),
            )
        except Exception as exc:
            partial_result = self._build_partial_ppt_result_from_disk(item=item, error=exc)
            if partial_result is None:
                raise
            log.warning(
                "[outputs_v2] PPT full export failed, falling back to partial page previews. "
                "output_id=%s error_type=%s error=%s",
                item.get("id"),
                type(exc).__name__,
                exc,
            )
            return partial_result
        result = self._urlize_payload_paths(payload)
        result["download_url"] = result.get("ppt_pdf_path") or result.get("ppt_pptx_path") or ""
        return result

    async def generate_output(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        email: str,
        output_id: str,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        index, item = self._find_output(manifest, output_id)
        document = self._maybe_load_document(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            document_id=str(item.get("document_id") or ""),
        )
        guidance_items = self._load_guidance_items(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            guidance_item_ids=item.get("guidance_item_ids") or [],
        )
        guidance_text = self._build_guidance_snapshot_text(guidance_items)
        item["guidance_snapshot_text"] = guidance_text
        output_dir = self._item_dir(notebook_id, notebook_title, user_id, output_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        if item["target_type"] == "ppt":
            result = await self._generate_ppt_output(
                item=item,
                email=email,
                api_url=api_url,
                api_key=api_key,
                model=model,
            )
            next_outline = self._attach_ppt_page_images_from_disk(
                result.get("pagecontent") or item.get("outline") or [],
                pipeline_dir=Path(str(result.get("result_path") or item.get("result_path") or "").strip())
                if str(result.get("result_path") or item.get("result_path") or "").strip()
                else None,
            )
            if isinstance(result, dict):
                result["pagecontent"] = next_outline
            item["outline"] = next_outline
            item["page_reviews"] = self._build_ppt_page_reviews(next_outline, [])
            item["page_versions"] = self._build_ppt_page_versions(
                next_outline,
                source="initial",
                output_dir=output_dir,
            )
            item["pipeline_stage"] = self.PPT_STAGE_PAGES
            item["status"] = self.PPT_STAGE_PAGES
        elif item["target_type"] == "report":
            result = await self._generate_report(output_dir=output_dir, item=item, document=document, guidance_text=guidance_text)
            item["status"] = "generated"
        else:
            generated_md = output_dir / "generation_input.md"
            generated_md.write_text(self._build_generation_markdown(item, document, guidance_text), encoding="utf-8")
            result = await self._run_with_backend_llm_fallback(
                label=f"generate_output:{item['target_type']}",
                api_url=api_url,
                api_key=api_key,
                operation=lambda resolved_api_url, resolved_api_key: self._generate_via_existing_endpoint(
                    target_type=item["target_type"],
                    output_dir=output_dir,
                    md_path=generated_md,
                    email=email,
                    user_id=user_id,
                    notebook_id=notebook_id,
                    notebook_title=notebook_title,
                    prompt=str(item.get("prompt") or ""),
                    page_count=int(item.get("page_count") or 8),
                    api_url=resolved_api_url,
                    api_key=resolved_api_key,
                    model=model,
                ),
            )
            item["status"] = "generated"

        item["result"] = result
        item["updated_at"] = self._now()
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        self._write_json(output_dir / "result.json", result if isinstance(result, dict) else {"result": result})
        return item

    async def regenerate_ppt_page(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        email: str,
        output_id: str,
        page_index: int,
        prompt: str,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        base_dir = self._base_dir(notebook_id, notebook_title, user_id)
        index, item = self._find_output(manifest, output_id)
        item, item_changed = self._hydrate_ppt_item_from_disk(item, base_dir)
        if item_changed:
            manifest[index] = item
            self._write_manifest(manifest_path, manifest)
        if item.get("target_type") != "ppt":
            raise HTTPException(status_code=400, detail="Only PPT outputs support page regenerate")
        outline = self._normalize_ppt_outline(item.get("outline") or [])
        if page_index < 0 or page_index >= len(outline):
            raise HTTPException(status_code=400, detail="Invalid PPT page index")
        if not str(prompt or "").strip():
            raise HTTPException(status_code=400, detail="prompt is required")

        result_path = str(item.get("result_path") or "").strip()
        if not result_path:
            raise HTTPException(status_code=400, detail="Missing result_path for PPT page regenerate")
        output_dir = self._item_dir(notebook_id, notebook_title, user_id, output_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        if not any(str(slide.get("generated_img_path") or slide.get("ppt_img_path") or "").strip() for slide in outline):
            raise HTTPException(status_code=400, detail="请先生成一版页面草稿，再逐页修改")

        from fastapi_app.schemas import PPTGenerationRequest
        from fastapi_app.services.paper2ppt_service import Paper2PPTService
        from fastapi_app.routers.kb import _require_llm_config

        service = Paper2PPTService()
        resolved_api_url, resolved_api_key = _require_llm_config(api_url, api_key)
        log.info(
            "[outputs_v2] regenerate_ppt_page start output_id=%s page_index=%s prompt=%s",
            output_id,
            page_index,
            str(prompt or "").strip(),
        )
        try:
            payload = await service.generate_ppt(
                PPTGenerationRequest(
                    img_gen_model_name=settings.IMAGE_GEN_MODEL or settings.PAPER2PPT_IMAGE_GEN_MODEL,
                    chat_api_url=resolved_api_url or "",
                    api_key=resolved_api_key or "",
                    email=email,
                    style="modern",
                    aspect_ratio="16:9",
                    language="zh",
                    model=model or settings.PAPER2PPT_DEFAULT_MODEL,
                    get_down="true",
                    all_edited_down="false",
                    result_path=result_path,
                    pagecontent=json.dumps(
                        self._prepare_ppt_outline_for_generation(
                            outline,
                            enable_images=bool(item.get("enable_images", True)),
                        ),
                        ensure_ascii=False,
                    ),
                    page_id=page_index,
                    edit_prompt=str(prompt or "").strip(),
                ),
                None,
                None,
            )
        except httpx.HTTPStatusError as exc:
            status_code = getattr(exc.response, "status_code", None)
            upstream_message = self._extract_upstream_error_message(exc)
            if status_code == 429:
                detail = "单页重生成暂时被上游生图服务限流，请稍后重试"
                if upstream_message:
                    detail = f"{detail}。上游返回：{upstream_message}"
                raise HTTPException(status_code=503, detail=detail) from exc
            if status_code == 503:
                detail = "单页重生成失败：当前生图渠道不可用，请稍后重试"
                if upstream_message:
                    detail = f"单页重生成失败：{upstream_message}"
                raise HTTPException(status_code=503, detail=detail) from exc
            detail = f"单页重生成失败：上游生图服务返回 {status_code or '异常'}"
            if upstream_message:
                detail = f"{detail}。上游返回：{upstream_message}"
            raise HTTPException(status_code=502, detail=detail) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=f"单页重生成失败：找不到当前页底图。{exc}") from exc
        result = self._urlize_payload_paths(payload)
        result["download_url"] = result.get("ppt_pdf_path") or result.get("ppt_pptx_path") or ""

        next_outline = self._attach_ppt_page_images_from_disk(
            result.get("pagecontent") or outline,
            pipeline_dir=Path(str(result.get("result_path") or result_path).strip()) if str(result.get("result_path") or result_path).strip() else None,
        )
        if isinstance(result, dict):
            result["pagecontent"] = next_outline
        page_reviews = self._build_ppt_page_reviews(next_outline, item.get("page_reviews") or [])
        page_reviews = self._set_ppt_page_confirmed(page_reviews, page_index=page_index, confirmed=False)
        page_versions = self._build_ppt_page_versions(
            next_outline,
            source="regenerate",
            prompt=str(prompt or "").strip(),
            page_index=page_index,
            output_dir=output_dir,
            existing=item.get("page_versions") or [],
        )

        item["outline"] = next_outline
        item["page_reviews"] = page_reviews
        item["page_versions"] = page_versions
        item["result"] = result
        item["pipeline_stage"] = self.PPT_STAGE_PAGES
        item["status"] = self.PPT_STAGE_PAGES
        item["updated_at"] = self._now()
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        self._write_json(output_dir / "outline.json", {"outline": next_outline})
        self._write_json(output_dir / "result.json", result if isinstance(result, dict) else {"result": result})
        log.info("[outputs_v2] regenerate_ppt_page done output_id=%s page_index=%s", output_id, page_index)
        return item

    def confirm_ppt_page(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        output_id: str,
        page_index: int,
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        base_dir = self._base_dir(notebook_id, notebook_title, user_id)
        index, item = self._find_output(manifest, output_id)
        item, item_changed = self._hydrate_ppt_item_from_disk(item, base_dir)
        if item_changed:
            manifest[index] = item
            self._write_manifest(manifest_path, manifest)
        if item.get("target_type") != "ppt":
            raise HTTPException(status_code=400, detail="Only PPT outputs support page confirm")
        outline = self._normalize_ppt_outline(item.get("outline") or [])
        if page_index < 0 or page_index >= len(outline):
            raise HTTPException(status_code=400, detail="Invalid PPT page index")
        preview_path = str(
            outline[page_index].get("generated_img_path")
            or outline[page_index].get("ppt_img_path")
            or ""
        ).strip()
        if not preview_path:
            raise HTTPException(status_code=400, detail="当前页还没有生成结果，无法确认")

        page_reviews = self._build_ppt_page_reviews(outline, item.get("page_reviews") or [])
        page_reviews = self._set_ppt_page_confirmed(page_reviews, page_index=page_index, confirmed=True)
        item["page_reviews"] = page_reviews
        item["pipeline_stage"] = self.PPT_STAGE_GENERATED if self._all_ppt_pages_confirmed(page_reviews) else self.PPT_STAGE_PAGES
        item["status"] = item["pipeline_stage"]
        item["updated_at"] = self._now()
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        return item

    def select_ppt_page_version(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        output_id: str,
        page_index: int,
        version_id: str,
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        base_dir = self._base_dir(notebook_id, notebook_title, user_id)
        index, item = self._find_output(manifest, output_id)
        item, item_changed = self._hydrate_ppt_item_from_disk(item, base_dir)
        if item_changed:
            manifest[index] = item
            self._write_manifest(manifest_path, manifest)
        if item.get("target_type") != "ppt":
            raise HTTPException(status_code=400, detail="Only PPT outputs support page version select")

        outline = self._normalize_ppt_outline(item.get("outline") or [])
        if page_index < 0 or page_index >= len(outline):
            raise HTTPException(status_code=400, detail="Invalid PPT page index")

        page_versions = self._select_ppt_page_version(
            item.get("page_versions") or [],
            page_index=page_index,
            version_id=version_id,
        )
        next_outline = self._apply_selected_ppt_page_versions(outline, page_versions)
        page_reviews = self._build_ppt_page_reviews(next_outline, item.get("page_reviews") or [])
        page_reviews = self._set_ppt_page_confirmed(page_reviews, page_index=page_index, confirmed=False)

        item["outline"] = next_outline
        item["page_versions"] = page_versions
        item["page_reviews"] = page_reviews
        item["pipeline_stage"] = self.PPT_STAGE_PAGES
        item["status"] = self.PPT_STAGE_PAGES
        item["updated_at"] = self._now()
        if isinstance(item.get("result"), dict):
            item["result"]["pagecontent"] = next_outline
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        output_dir = self._item_dir(notebook_id, notebook_title, user_id, output_id)
        self._write_json(output_dir / "outline.json", {"outline": next_outline})
        if isinstance(item.get("result"), dict):
            self._write_json(output_dir / "result.json", item["result"])
        log.info(
            "[outputs_v2] select_ppt_page_version output_id=%s page_index=%s version_id=%s",
            output_id,
            page_index,
            version_id,
        )
        return item

    async def import_output_to_source(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        output_id: str,
    ) -> Dict[str, Any]:
        manifest_path = self._manifest_path(notebook_id, notebook_title, user_id)
        manifest = self._read_manifest(manifest_path)
        index, item = self._find_output(manifest, output_id)
        result = item.get("result") or {}
        candidate_paths: List[str] = []
        for key in (
            "markdown_path",
            "pdf_path",
            "pptx_path",
            "ppt_pdf_path",
            "ppt_pptx_path",
            "mindmap_path",
            "audio_path",
            "result_path",
            "download_url",
        ):
            value = str(result.get(key) or "").strip()
            if value:
                candidate_paths.append(value)
        local_file: Optional[Path] = None
        for value in candidate_paths:
            maybe_path = Path(value)
            if not maybe_path.is_absolute():
                from fastapi_app.utils import _from_outputs_url

                maybe_path = Path(_from_outputs_url(value))
            if maybe_path.exists() and maybe_path.is_file():
                local_file = maybe_path
                break
        if local_file is None:
            raise HTTPException(status_code=400, detail="No generated file can be imported as source")
        paths = get_notebook_paths(notebook_id, notebook_title, user_id)
        manager = SourceManager(paths)
        source_info = await manager.import_file(local_file, local_file.name)
        item["imported_source_path"] = str(source_info.original_path)
        item["imported_source_url"] = _to_outputs_url(str(source_info.original_path))
        item["updated_at"] = self._now()
        manifest[index] = item
        self._write_manifest(manifest_path, manifest)
        return {
            "success": True,
            "source_path": str(source_info.original_path),
            "source_url": _to_outputs_url(str(source_info.original_path)),
        }
