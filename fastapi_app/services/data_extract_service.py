from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import HTTPException

from fastapi_app.notebook_paths import get_notebook_paths
from fastapi_app.config import settings as app_settings
from fastapi_app.source_manager import SourceManager
from fastapi_app.utils import _from_outputs_url, _to_outputs_url
from fastapi_app.services.wa_data_extract import SQLBotAdapter
from workflow_engine.utils import get_project_root


class DataExtractService:
    """Notebook-scoped datasource/session/artifact manager for SQLBot integration."""

    SUPPORTED_SUFFIXES = {".csv"}
    REUSABLE_ARTIFACT_TYPES = {"csv"}
    PREVIEW_ROWS = 20
    TEXT_PREVIEW_CHARS = 4000

    def __init__(self, adapter: Optional[SQLBotAdapter] = None) -> None:
        self.adapter = adapter or SQLBotAdapter()

    def _base_dir(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return get_notebook_paths(notebook_id, notebook_title, user_id).root / "data_extract"

    def _datasources_path(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / "datasources.json"

    def _sessions_path(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / "sessions.json"

    def _messages_dir(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / "messages"

    def _messages_path(self, notebook_id: str, notebook_title: str, user_id: str, session_id: str) -> Path:
        return self._messages_dir(notebook_id, notebook_title, user_id) / f"{session_id}.json"

    def _artifacts_dir(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / "artifacts"

    def _artifacts_path(self, notebook_id: str, notebook_title: str, user_id: str) -> Path:
        return self._base_dir(notebook_id, notebook_title, user_id) / "artifacts.json"

    def _read_json(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_json(self, path: Path, data: List[Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _is_embedded_mode(self) -> bool:
        return str(getattr(app_settings, "SQLBOT_MODE", "external")).strip().lower() == "embedded"

    def _raise_sqlbot_error(self, action: str, exc: httpx.HTTPError) -> None:
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            detail = (response.text or response.reason_phrase or "").strip()
            detail = detail[:300] if detail else response.reason_phrase
            raise HTTPException(
                status_code=502,
                detail=f"SQLBot {action} failed ({response.status_code}): {detail}",
            ) from exc

        raise HTTPException(
            status_code=502,
            detail=f"SQLBot {action} unavailable: {exc}",
        ) from exc

    def _resolve_local_path(self, file_path: str) -> Path:
        local = Path(_from_outputs_url(file_path))
        if not local.is_absolute():
            local = local.resolve()
        if not local.exists() or not local.is_file():
            raise HTTPException(status_code=404, detail="Datasource file not found")
        if local.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise HTTPException(status_code=400, detail="Only CSV datasource registration is supported for now")
        return local

    def _dedupe_ints(self, values: Optional[List[int]]) -> List[int]:
        seen: set[int] = set()
        result: List[int] = []
        for value in values or []:
            try:
                item = int(value)
            except Exception:
                continue
            if item <= 0 or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _dedupe_strings(self, values: Optional[List[str]]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for value in values or []:
            item = str(value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _slugify(self, text: str, max_len: int = 48) -> str:
        raw = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", (text or "").strip())
        raw = re.sub(r"_+", "_", raw).strip("_.- ")
        return (raw or "artifact")[:max_len]

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _find_session(
        self,
        sessions: List[Dict[str, Any]],
        session_id: str,
    ) -> tuple[int, Dict[str, Any]]:
        for idx, session in enumerate(sessions):
            if session.get("id") == session_id:
                return idx, session
        raise HTTPException(status_code=404, detail="Session not found")

    def _find_artifact(
        self,
        artifacts: List[Dict[str, Any]],
        artifact_id: str,
    ) -> tuple[int, Dict[str, Any]]:
        for idx, artifact in enumerate(artifacts):
            if artifact.get("id") == artifact_id:
                return idx, artifact
        raise HTTPException(status_code=404, detail="Artifact not found")

    def _sort_items(self, items: List[Dict[str, Any]], key: str, reverse: bool = True) -> List[Dict[str, Any]]:
        return sorted(items, key=lambda item: str(item.get(key) or ""), reverse=reverse)

    def _build_datasource_snapshot(
        self,
        datasource_ids: List[int],
        datasources: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_id = {int(item.get("datasource_id", -1)): item for item in datasources if item.get("datasource_id") is not None}
        snapshot: List[Dict[str, Any]] = []
        for datasource_id in datasource_ids:
            item = by_id.get(datasource_id)
            if not item:
                snapshot.append({
                    "datasource_id": datasource_id,
                    "display_name": f"Datasource {datasource_id}",
                    "name": f"Datasource {datasource_id}",
                })
                continue
            snapshot.append({
                "datasource_id": datasource_id,
                "id": item.get("id"),
                "display_name": item.get("display_name") or item.get("name"),
                "name": item.get("name"),
                "file_path": item.get("file_path"),
                "file_type": item.get("file_type"),
                "rows": item.get("rows"),
                "columns": item.get("columns"),
            })
        return snapshot

    def _public_session(
        self,
        session: Dict[str, Any],
        turn_count: int = 0,
        artifact_count: int = 0,
    ) -> Dict[str, Any]:
        primary_datasource_id = int(
            session.get("primary_datasource_id")
            or session.get("datasource_id")
            or 0
        )
        selected_datasource_ids = self._dedupe_ints(
            session.get("selected_datasource_ids") or [primary_datasource_id]
        )
        return {
            **session,
            "primary_datasource_id": primary_datasource_id,
            "selected_datasource_ids": selected_datasource_ids,
            "turn_count": turn_count,
            "artifact_count": artifact_count,
            "datasource_snapshot": session.get("datasource_snapshot") or [],
        }

    async def _ensure_embedded_datasource_record(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        datasource_record: Dict[str, Any],
        manifest: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self._is_embedded_mode():
            return datasource_record

        datasource_id = int(datasource_record.get("datasource_id", 0) or 0)
        if datasource_id > 0:
            try:
                await self.adapter.get_preview(datasource_id, rows=1)
                return datasource_record
            except Exception:
                pass

        local_path = str(datasource_record.get("local_path") or datasource_record.get("file_path") or "").strip()
        if not local_path:
            raise HTTPException(status_code=404, detail="Datasource file path missing")

        local_file = self._resolve_local_path(local_path)
        upload_result = await self.adapter.register_csv(str(local_file))
        new_datasource_id = int(upload_result["datasource_id"])
        preview = await self.adapter.get_preview(new_datasource_id)

        datasource_record["datasource_id"] = new_datasource_id
        datasource_record["preview"] = preview
        datasource_record["rows"] = upload_result.get("rows", datasource_record.get("rows", 0))
        datasource_record["columns"] = upload_result.get("columns", datasource_record.get("columns", 0))
        datasource_record["updated_at"] = self._now()

        for idx, item in enumerate(manifest):
            if item.get("id") == datasource_record.get("id"):
                manifest[idx] = datasource_record
                break
        self._write_json(self._datasources_path(notebook_id, notebook_title, user_id), manifest)
        return datasource_record

    async def _ensure_selected_datasource_ids(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        datasource_ids: List[int],
    ) -> tuple[List[int], List[Dict[str, Any]]]:
        manifest_path = self._datasources_path(notebook_id, notebook_title, user_id)
        manifest = self._read_json(manifest_path)
        if not datasource_ids:
            return [], manifest

        resolved: List[int] = []
        for datasource_id in datasource_ids:
            record = next((item for item in manifest if int(item.get("datasource_id", -1)) == datasource_id), None)
            if not record:
                record = next((item for item in manifest if int(item.get("datasource_id", 0) or 0) == datasource_id), None)
            if not record:
                continue
            record = await self._ensure_embedded_datasource_record(
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                user_id=user_id,
                datasource_record=record,
                manifest=manifest,
            )
            resolved.append(int(record["datasource_id"]))
        return self._dedupe_ints(resolved), manifest

    async def list_datasources(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        return self._read_json(self._datasources_path(notebook_id, notebook_title, user_id))

    async def register_datasource(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        file_path: str,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        local_path = self._resolve_local_path(file_path)
        manifest_path = self._datasources_path(notebook_id, notebook_title, user_id)
        current = self._read_json(manifest_path)

        for item in current:
            if item.get("local_path") == str(local_path):
                return item

        try:
            upload_result = await self.adapter.register_csv(str(local_path))
            datasource_id = int(upload_result["datasource_id"])
            preview = await self.adapter.get_preview(datasource_id)
        except httpx.HTTPError as exc:
            self._raise_sqlbot_error("datasource registration", exc)

        record = {
            "id": uuid4().hex,
            "datasource_id": datasource_id,
            "name": local_path.name,
            "display_name": display_name or local_path.stem,
            "file_path": file_path,
            "local_path": str(local_path),
            "file_type": local_path.suffix.lower(),
            "rows": upload_result.get("rows", 0),
            "columns": upload_result.get("columns", 0),
            "preview": preview,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        current.append(record)
        self._write_json(manifest_path, current)
        return record

    async def list_sessions(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        sessions = self._read_json(self._sessions_path(notebook_id, notebook_title, user_id))
        artifacts = self._read_json(self._artifacts_path(notebook_id, notebook_title, user_id))
        public: List[Dict[str, Any]] = []
        for session in sessions:
            session_id = str(session.get("id") or "")
            turns = self._read_json(self._messages_path(notebook_id, notebook_title, user_id, session_id))
            session_artifacts = [item for item in artifacts if item.get("session_id") == session_id]
            public.append(self._public_session(session, len(turns), len(session_artifacts)))
        return self._sort_items(public, "updated_at", reverse=True)

    async def get_session_detail(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        sessions = self._read_json(self._sessions_path(notebook_id, notebook_title, user_id))
        _, session = self._find_session(sessions, session_id)
        turns = self._sort_items(
            self._read_json(self._messages_path(notebook_id, notebook_title, user_id, session_id)),
            "created_at",
            reverse=False,
        )
        artifacts = [
            item
            for item in self._read_json(self._artifacts_path(notebook_id, notebook_title, user_id))
            if item.get("session_id") == session_id
        ]
        artifacts = self._sort_items(artifacts, "created_at", reverse=True)
        return {
            "session": self._public_session(session, len(turns), len(artifacts)),
            "turns": turns,
            "artifacts": artifacts,
        }

    async def start_session(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        datasource_id: int,
        title: str = "",
        selected_datasource_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        requested_ids = self._dedupe_ints([int(datasource_id), *(selected_datasource_ids or [])])
        resolved_selected_ids, datasources = await self._ensure_selected_datasource_ids(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            datasource_ids=requested_ids,
        )
        if not resolved_selected_ids:
            raise HTTPException(status_code=404, detail="Datasource is not registered for this notebook")

        primary_datasource_id = resolved_selected_ids[0]
        ds = next((item for item in datasources if int(item.get("datasource_id", -1)) == primary_datasource_id), None)
        if not ds:
            raise HTTPException(status_code=404, detail="Datasource is not registered for this notebook")

        try:
            upstream = await self.adapter.start_chat(datasource_id=primary_datasource_id, chat_title=title)
        except httpx.HTTPError as exc:
            self._raise_sqlbot_error("session start", exc)

        sessions_path = self._sessions_path(notebook_id, notebook_title, user_id)
        sessions = self._read_json(sessions_path)
        datasource_snapshot = self._build_datasource_snapshot(resolved_selected_ids, datasources)
        now = self._now()
        record = {
            "id": uuid4().hex,
            "chat_id": int(upstream["chat_id"]),
            "datasource_id": primary_datasource_id,
            "primary_datasource_id": primary_datasource_id,
            "selected_datasource_ids": resolved_selected_ids,
            "datasource_snapshot": datasource_snapshot,
            "title": title or ds.get("display_name") or ds.get("name") or "智能取数",
            "created_at": now,
            "updated_at": now,
        }
        sessions.append(record)
        self._write_json(sessions_path, sessions)
        return self._public_session(record)

    async def _ensure_artifact_datasources(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        artifact_ids: List[str],
    ) -> List[int]:
        if not artifact_ids:
            return []

        artifact_path = self._artifacts_path(notebook_id, notebook_title, user_id)
        artifacts = self._read_json(artifact_path)
        datasource_ids: List[int] = []
        updated = False
        for artifact_id in artifact_ids:
            idx, artifact = self._find_artifact(artifacts, artifact_id)
            if artifact.get("type") not in self.REUSABLE_ARTIFACT_TYPES:
                continue
            existing_datasource_id = int(artifact.get("datasource_id") or 0)
            if existing_datasource_id > 0:
                datasource_ids.append(existing_datasource_id)
                continue

            file_url = str(artifact.get("file_url") or artifact.get("file_path") or "").strip()
            if not file_url:
                continue
            record = await self.register_datasource(
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                user_id=user_id,
                file_path=file_url,
                display_name=artifact.get("title") or artifact.get("question"),
            )
            datasource_id = int(record["datasource_id"])
            artifacts[idx]["datasource_id"] = datasource_id
            artifacts[idx]["updated_at"] = self._now()
            datasource_ids.append(datasource_id)
            updated = True

        if updated:
            self._write_json(artifact_path, artifacts)
        return self._dedupe_ints(datasource_ids)

    async def _persist_artifact(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        session: Dict[str, Any],
        turn_id: str,
        question: str,
        answer_text: str,
        sql_text: Optional[str],
        data_block: Dict[str, Any],
        input_artifact_ids: List[str],
        input_datasource_ids: List[int],
    ) -> Optional[Dict[str, Any]]:
        artifacts_path = self._artifacts_path(notebook_id, notebook_title, user_id)
        artifacts = self._read_json(artifacts_path)
        artifact_dir = self._artifacts_dir(notebook_id, notebook_title, user_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        row_count = int(data_block.get("row_count", 0) or 0)
        columns = list(data_block.get("columns", []) or [])
        preview_rows = list(data_block.get("data", []) or [])[: self.PREVIEW_ROWS]
        artifact_type: Optional[str] = None
        file_path: Optional[Path] = None
        file_url = ""
        preview_text = ""

        if row_count > 0 or columns:
            try:
                response = await self.adapter.download_data(
                    int(session["chat_id"]),
                    question,
                    fmt="csv",
                )
            except httpx.HTTPError as exc:
                self._raise_sqlbot_error("artifact export", exc)

            file_name = f"{self._timestamp()}_{self._slugify(question)}.csv"
            file_path = artifact_dir / file_name
            file_path.write_bytes(response.content)
            file_url = _to_outputs_url(str(file_path))
            artifact_type = "csv"
        elif answer_text.strip():
            file_name = f"{self._timestamp()}_{self._slugify(question)}.md"
            file_path = artifact_dir / file_name
            lines = [f"# {question}", "", answer_text.strip()]
            if sql_text:
                lines.extend(["", "```sql", sql_text.strip(), "```"])
            file_path.write_text("\n".join(lines), encoding="utf-8")
            file_url = _to_outputs_url(str(file_path))
            artifact_type = "text"
            preview_text = answer_text.strip()[: self.TEXT_PREVIEW_CHARS]
        else:
            return None

        now = self._now()
        artifact = {
            "id": uuid4().hex,
            "session_id": session["id"],
            "turn_id": turn_id,
            "type": artifact_type,
            "title": question[:120],
            "question": question,
            "answer_summary": answer_text.strip()[: self.TEXT_PREVIEW_CHARS],
            "sql": sql_text or "",
            "file_name": file_path.name if file_path else "",
            "file_path": str(file_path) if file_path else "",
            "file_url": file_url,
            "columns": columns,
            "row_count": row_count,
            "preview_rows": preview_rows,
            "preview_text": preview_text,
            "primary_datasource_id": int(session.get("primary_datasource_id") or session.get("datasource_id") or 0),
            "selected_datasource_ids": self._dedupe_ints(input_datasource_ids),
            "source_artifact_ids": self._dedupe_strings(input_artifact_ids),
            "imported_to_sources": False,
            "reusable_as_input": artifact_type in self.REUSABLE_ARTIFACT_TYPES,
            "created_at": now,
            "updated_at": now,
        }
        artifacts.append(artifact)
        self._write_json(artifacts_path, artifacts)
        return artifact

    async def send_message(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        session_id: str,
        question: str,
        result_format: str = "json",
        execution_strategy: Optional[str] = None,
        selected_datasource_ids: Optional[List[int]] = None,
        selected_artifact_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        sessions_path = self._sessions_path(notebook_id, notebook_title, user_id)
        sessions = self._read_json(sessions_path)
        session_idx, session = self._find_session(sessions, session_id)

        input_artifact_ids = self._dedupe_strings(selected_artifact_ids)
        artifact_datasource_ids = await self._ensure_artifact_datasources(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            artifact_ids=input_artifact_ids,
        )
        selected_datasource_ids, datasources = await self._ensure_selected_datasource_ids(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            datasource_ids=self._dedupe_ints(selected_datasource_ids or []),
        )
        session_selected_ids = self._dedupe_ints(
            session.get("selected_datasource_ids")
            or [int(session.get("primary_datasource_id") or session.get("datasource_id") or 0)]
        )
        input_datasource_ids = self._dedupe_ints([
            int(session.get("primary_datasource_id") or session.get("datasource_id") or 0),
            *session_selected_ids,
            *(selected_datasource_ids or []),
            *artifact_datasource_ids,
        ])
        primary_datasource_id = int(session.get("primary_datasource_id") or session.get("datasource_id") or 0)

        try:
            upstream_message = await self.adapter.send_message(
                int(session["chat_id"]),
                primary_datasource_id,
                question,
                selected_datasource_ids=input_datasource_ids if len(input_datasource_ids) > 1 else None,
                execution_strategy=execution_strategy,
            )
            extract_result = await self.adapter.extract_data(
                int(session["chat_id"]),
                question,
                fmt=result_format,
            )
        except httpx.HTTPError as exc:
            self._raise_sqlbot_error("query execution", exc)

        raw_answer = ((upstream_message.get("message") or {}).get("content") or "").strip()
        answer_text = raw_answer
        data_block = extract_result.get("data") or {}
        sql_text = extract_result.get("sql")
        if raw_answer.startswith("{"):
            try:
                parsed_answer = json.loads(raw_answer)
                sql_text = sql_text or parsed_answer.get("query_text")
                answer_text = parsed_answer.get("final_answer") or f"已完成取数，返回 {data_block.get('row_count', 0)} 行结果。"
            except Exception:
                answer_text = f"已完成取数，返回 {data_block.get('row_count', 0)} 行结果。"

        turn_id = uuid4().hex
        artifact = await self._persist_artifact(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            session=session,
            turn_id=turn_id,
            question=question,
            answer_text=answer_text,
            sql_text=sql_text,
            data_block=data_block,
            input_artifact_ids=input_artifact_ids,
            input_datasource_ids=input_datasource_ids,
        )

        turns_path = self._messages_path(notebook_id, notebook_title, user_id, session_id)
        turns = self._read_json(turns_path)
        turn_record = {
            "id": turn_id,
            "session_id": session_id,
            "question": question,
            "answer": answer_text,
            "sql": sql_text or "",
            "status": upstream_message.get("status"),
            "success": bool(extract_result.get("success", False) and upstream_message.get("status") != "error"),
            "error": upstream_message.get("error"),
            "row_count": int(data_block.get("row_count", 0) or 0),
            "columns": list(data_block.get("columns", []) or []),
            "preview_rows": list(data_block.get("data", []) or [])[: self.PREVIEW_ROWS],
            "preview_text": answer_text[: self.TEXT_PREVIEW_CHARS],
            "file_url": artifact.get("file_url") if artifact else "",
            "input_artifact_ids": input_artifact_ids,
            "input_datasource_ids": input_datasource_ids,
            "artifact_id": artifact.get("id") if artifact else None,
            "artifact_type": artifact.get("type") if artifact else None,
            "created_at": self._now(),
        }
        turns.append(turn_record)
        self._write_json(turns_path, turns)

        datasources = await self.list_datasources(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
        )
        sessions[session_idx]["updated_at"] = self._now()
        sessions[session_idx]["selected_datasource_ids"] = input_datasource_ids
        sessions[session_idx]["datasource_snapshot"] = self._build_datasource_snapshot(input_datasource_ids, datasources)
        sessions[session_idx]["last_turn_summary"] = answer_text[:280]
        self._write_json(sessions_path, sessions)

        export_url = (
            f"/api/v1/data-extract/sessions/{session_id}/export"
            f"?notebook_id={notebook_id}&question={question}&format=csv"
        ).replace(" ", "%20")

        return {
            "success": extract_result.get("success", False) and upstream_message.get("status") != "error",
            "session_id": session_id,
            "chat_id": session["chat_id"],
            "datasource_id": primary_datasource_id,
            "primary_datasource_id": primary_datasource_id,
            "selected_datasource_ids": input_datasource_ids,
            "answer": answer_text,
            "status": upstream_message.get("status"),
            "sql": sql_text,
            "format": extract_result.get("format", result_format),
            "columns": data_block.get("columns", []),
            "rows": data_block.get("data", []),
            "row_count": data_block.get("row_count", 0),
            "artifact": artifact,
            "turn": turn_record,
            "export_url": export_url,
            "error": upstream_message.get("error"),
        }

    async def list_artifacts(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        return self._sort_items(
            self._read_json(self._artifacts_path(notebook_id, notebook_title, user_id)),
            "created_at",
            reverse=True,
        )

    async def import_artifact_to_source(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        artifact_id: str,
    ) -> Dict[str, Any]:
        artifact_path = self._artifacts_path(notebook_id, notebook_title, user_id)
        artifacts = self._read_json(artifact_path)
        artifact_idx, artifact = self._find_artifact(artifacts, artifact_id)

        if artifact.get("imported_to_sources") and artifact.get("imported_source_static_url"):
            return {
                "success": True,
                "artifact": artifacts[artifact_idx],
                "source": {
                    "name": artifact.get("imported_source_name") or artifact.get("file_name") or artifact.get("title"),
                    "static_url": artifact.get("imported_source_static_url"),
                },
            }

        paths = get_notebook_paths(notebook_id, notebook_title, user_id)
        mgr = SourceManager(paths)
        local_file_path = str(artifact.get("file_path") or artifact.get("file_url") or "")
        source_name = ""
        source_static_url = ""

        if artifact.get("type") == "csv":
            local_path = self._resolve_local_path(local_file_path)
            source_info = await mgr.import_file(local_path, local_path.name)
            source_name = source_info.original_path.name
            rel = source_info.original_path.relative_to(get_project_root())
            source_static_url = "/" + rel.as_posix()
        else:
            preview_text = str(artifact.get("preview_text") or artifact.get("answer_summary") or "").strip()
            if not preview_text and local_file_path:
                local_path = Path(_from_outputs_url(local_file_path))
                if local_path.exists():
                    preview_text = local_path.read_text(encoding="utf-8", errors="replace")
            if not preview_text:
                raise HTTPException(status_code=400, detail="Artifact has no importable content")
            source_info = await mgr.import_text(preview_text, artifact.get("title") or artifact.get("question") or "取数产出")
            source_name = source_info.original_path.name
            rel = source_info.original_path.relative_to(get_project_root())
            source_static_url = "/" + rel.as_posix()

        artifacts[artifact_idx]["imported_to_sources"] = True
        artifacts[artifact_idx]["imported_source_name"] = source_name
        artifacts[artifact_idx]["imported_source_static_url"] = source_static_url
        artifacts[artifact_idx]["updated_at"] = self._now()
        self._write_json(artifact_path, artifacts)

        return {
            "success": True,
            "artifact": artifacts[artifact_idx],
            "source": {
                "name": source_name,
                "static_url": source_static_url,
            },
        }

    async def export_data(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        session_id: str,
        question: str,
        fmt: str = "csv",
    ) -> Dict[str, Any]:
        sessions = self._read_json(self._sessions_path(notebook_id, notebook_title, user_id))
        _, session = self._find_session(sessions, session_id)

        try:
            response = await self.adapter.download_data(
                int(session["chat_id"]),
                question,
                fmt=fmt,
            )
        except httpx.HTTPError as exc:
            self._raise_sqlbot_error("export", exc)

        return {
            "content": response.content,
            "content_type": response.headers.get("content-type", "text/csv; charset=utf-8"),
            "content_disposition": response.headers.get("content-disposition", f'attachment; filename="export.{fmt}"'),
        }
