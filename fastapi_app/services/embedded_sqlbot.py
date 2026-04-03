from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from uuid import uuid4

import requests
from dotenv import dotenv_values

from fastapi_app.config import settings as app_settings

logger = logging.getLogger(__name__)


@dataclass
class EmbeddedDownloadResponse:
    content: bytes
    headers: Dict[str, str]


class EmbeddedSQLBotAdapter:
    """
    In-process SQLBot adapter.

    This adapter mirrors the external HTTP API but executes against the vendored
    `backend` package directly inside Open-NotebookLM.
    """

    _runtime: Optional[SimpleNamespace] = None
    _agent: Any = None
    _agent_lock = asyncio.Lock()
    _llm_timeout = 45

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        llm_api_base: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> None:
        self.api_key = (api_key or app_settings.SQLBOT_API_KEY or "").strip()
        self.llm_api_base = self._normalize_base_url(llm_api_base)
        self.llm_api_key = self._strip_wrapped_value(llm_api_key)
        self.llm_model = self._strip_wrapped_value(llm_model)

    @staticmethod
    def _strip_wrapped_value(value: Optional[str]) -> str:
        text = str(value or "").strip()
        if len(text) >= 2 and text.startswith("<") and text.endswith(">"):
            text = text[1:-1].strip()
        return text

    @classmethod
    def _normalize_base_url(cls, value: Optional[str]) -> str:
        base = cls._strip_wrapped_value(value).rstrip("/")
        if not base:
            return ""
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        if "/v1/" in base:
            base = base.split("/v1/")[0] + "/v1"
        return base

    def _load_local_api_key_fallback(self) -> Dict[str, str]:
        fallback: Dict[str, str] = {}
        """
        Local development fallback:
        try nearby `.env` files so the embedded mode can run in the current
        workspace before SQLBOT_OPENAI_API_KEY is explicitly configured.
        """
        candidate_envs = [
            Path(__file__).resolve().parents[2] / "fastapi_app" / ".env",
            Path(__file__).resolve().parents[3] / ".env",
        ]
        for env_path in candidate_envs:
            if not env_path.exists():
                continue
            try:
                values = dotenv_values(env_path)
            except Exception:
                continue

            api_key = self._strip_wrapped_value(
                values.get("SQLBOT_OPENAI_API_KEY")
                or values.get("OPENAI_API_KEY")
                or values.get("DF_API_KEY")
                or values.get("LLM_API_KEY")
            )
            api_base = self._normalize_base_url(
                values.get("SQLBOT_OPENAI_API_BASE")
                or values.get("OPENAI_API_BASE")
                or values.get("DF_API_URL")
                or values.get("LLM_API_URL")
            )
            model_name = self._strip_wrapped_value(
                values.get("SQLBOT_OPENAI_MODEL")
                or values.get("OPENAI_MODEL")
                or values.get("DF_MODEL")
                or values.get("LLM_MODEL")
            )

            if api_key and not fallback.get("api_key"):
                fallback["api_key"] = api_key
            if api_base and not fallback.get("api_base"):
                fallback["api_base"] = api_base
            if model_name and not fallback.get("model"):
                fallback["model"] = model_name

            if fallback.get("api_key") and fallback.get("api_base"):
                break
        return fallback

    def _resolve_llm_config(self) -> Dict[str, str]:
        fallback = self._load_local_api_key_fallback()
        api_key = (
            self.llm_api_key
            or self._strip_wrapped_value(os.getenv("SQLBOT_OPENAI_API_KEY"))
            or self._strip_wrapped_value(os.getenv("OPENAI_API_KEY"))
            or self._strip_wrapped_value(os.getenv("DF_API_KEY"))
            or self._strip_wrapped_value(os.getenv("LLM_API_KEY"))
            or self._strip_wrapped_value(app_settings.SQLBOT_OPENAI_API_KEY)
            or self._strip_wrapped_value(getattr(app_settings, "LLM_API_KEY", None))
            or fallback.get("api_key", "")
        )
        api_base = (
            self.llm_api_base
            or self._normalize_base_url(os.getenv("SQLBOT_OPENAI_API_BASE"))
            or self._normalize_base_url(os.getenv("OPENAI_API_BASE"))
            or self._normalize_base_url(os.getenv("DF_API_URL"))
            or self._normalize_base_url(os.getenv("LLM_API_URL"))
            or self._normalize_base_url(app_settings.SQLBOT_OPENAI_API_BASE)
            or self._normalize_base_url(getattr(app_settings, "LLM_API_URL", None))
            or fallback.get("api_base", "")
            or self._normalize_base_url(app_settings.DEFAULT_LLM_API_URL)
        )
        model = (
            self.llm_model
            or self._strip_wrapped_value(os.getenv("SQLBOT_OPENAI_MODEL"))
            or self._strip_wrapped_value(os.getenv("OPENAI_MODEL"))
            or self._strip_wrapped_value(os.getenv("DF_MODEL"))
            or self._strip_wrapped_value(os.getenv("LLM_MODEL"))
            or self._strip_wrapped_value(app_settings.SQLBOT_OPENAI_MODEL)
            or self._strip_wrapped_value(getattr(app_settings, "LLM_MODEL", None))
            or fallback.get("model", "")
            or self._strip_wrapped_value(app_settings.KB_CHAT_MODEL)
            or "gpt-4o-mini"
        )
        return {
            "api_key": api_key,
            "api_base": api_base,
            "model": model,
        }

    def _bootstrap_env(self) -> None:
        """
        Provide minimal defaults before the vendored backend settings are imported.
        """
        llm_config = self._resolve_llm_config()
        if llm_config["api_base"] and (self.llm_api_base or not os.getenv("OPENAI_API_BASE")):
            os.environ["OPENAI_API_BASE"] = llm_config["api_base"]
        if llm_config["model"] and (self.llm_model or not os.getenv("OPENAI_MODEL")):
            os.environ["OPENAI_MODEL"] = llm_config["model"]
        if llm_config["api_key"] and (self.llm_api_key or not os.getenv("OPENAI_API_KEY")):
            os.environ["OPENAI_API_KEY"] = llm_config["api_key"]
        os.environ.setdefault("SQLBOT_EMBEDDED_MINIMAL", "1")
        # Embedded mode must tolerate generic host app env values.
        if not os.getenv("DEBUG"):
            os.environ["DEBUG"] = "False"
        if not os.getenv("SECRET_KEY"):
            os.environ["SECRET_KEY"] = "embedded-sqlbot-secret"

    @classmethod
    def _ensure_runtime(cls) -> SimpleNamespace:
        if cls._runtime is not None:
            return cls._runtime

        try:
            from sqlmodel import Session, select

            from fastapi_app.adapters.csv_datasource import CSVDataSource
            from fastapi_app.agents.tools.datasource_manager import (
                get_datasource_handler,
                set_datasource_handler,
            )
            from fastapi_app.core.database import engine, init_db
            from fastapi_app.core.datasource_interface import DataSourceMetadata, DataSourceType
            from fastapi_app.core.config import settings as sqlbot_settings
            from fastapi_app.models.chat_models import Chat, ChatRecord, Datasource
            from fastapi_app.modules.data_pipeline.bootstrap import bootstrap_datasource
            from fastapi_app.utils.csv_export import CSVExportConfig, CSVEncoding, CSVGenerator
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Embedded SQLBot mode requires sqlbot runtime dependencies in the current environment. "
                "Please install Open-NotebookLM requirements including sqlmodel and duckdb."
            ) from exc

        init_db()
        sqlbot_settings.CSV_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        cls._runtime = SimpleNamespace(
            Session=Session,
            select=select,
            engine=engine,
            CSVDataSource=CSVDataSource,
            DataSourceMetadata=DataSourceMetadata,
            DataSourceType=DataSourceType,
            Datasource=Datasource,
            Chat=Chat,
            ChatRecord=ChatRecord,
            set_datasource_handler=set_datasource_handler,
            get_datasource_handler=get_datasource_handler,
            bootstrap_datasource=bootstrap_datasource,
            CSVExportConfig=CSVExportConfig,
            CSVEncoding=CSVEncoding,
            CSVGenerator=CSVGenerator,
            sqlbot_settings=sqlbot_settings,
        )
        return cls._runtime

    async def _get_agent(self):
        self._bootstrap_env()
        self._ensure_runtime()
        if self.__class__._agent is None:
            async with self.__class__._agent_lock:
                if self.__class__._agent is None:
                    from fastapi_app.agents.sqlbot_agent import SQLBotAgent

                    self.__class__._agent = SQLBotAgent(verbose=True)
        return self.__class__._agent

    def _llm_request(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self._bootstrap_env()
        llm_config = self._resolve_llm_config()
        base = llm_config["api_base"].rstrip("/")
        api_key = llm_config["api_key"]
        model = llm_config["model"] or "gpt-4o-mini"
        if not base or not api_key:
            raise RuntimeError("Embedded SQLBot LLM config is incomplete.")

        session = requests.Session()
        session.trust_env = False
        response = session.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,
            },
            timeout=self._llm_timeout,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        raw = (text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()
        try:
            return json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
            raise

    def _build_fetch_prompt(
        self,
        schema_text: str,
        question: str,
        *,
        primary_table_hint: Optional[str] = None,
        multi_source: bool = False,
        previous_question: Optional[str] = None,
        previous_sql: Optional[str] = None,
    ) -> list[dict[str, str]]:
        instructions = [
            "You are a data extraction SQL assistant.",
            "Return ONLY JSON.",
            'JSON format: {"sql":"...","answer":"..."}',
            "Generate one executable SQL query.",
            "If the user asks for counts, use COUNT(*) or COUNT(column) instead of returning raw rows.",
            "If the user asks for top N, use ORDER BY + LIMIT.",
            "Prefer concise SQL and preserve the exact available table/column names.",
            "Do not wrap the JSON in markdown fences.",
        ]
        if primary_table_hint:
            instructions.append(f"Primary datasource/table hint: {primary_table_hint}")
        if multi_source:
            instructions.append("Cross-source mode is enabled. Use the unified table names shown in the schema.")

        user_parts = [
            "Schema:",
            schema_text[:18000],
            "",
            f"User question: {question}",
        ]
        if previous_question and previous_sql:
            user_parts.extend([
                "",
                f"Previous question: {previous_question}",
                f"Previous SQL: {previous_sql}",
            ])

        return [
            {"role": "system", "content": "\n".join(instructions)},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + str(identifier or "").replace('"', '""') + '"'

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"[\s_\-]+", "", (value or "").strip().lower())

    @staticmethod
    def _parse_limit(question: str, default: int = 10) -> int:
        match = re.search(r"(?:top|前|前面|返回|展示|取前)\s*(\d+)", question, re.IGNORECASE)
        if not match:
            match = re.search(r"(\d+)\s*(?:条|行|个)", question)
        if match:
            try:
                return max(1, min(100, int(match.group(1))))
            except Exception:
                return default
        return default

    def _find_matching_column(
        self,
        question: str,
        columns: list[Any],
        *,
        numeric_only: bool = False,
    ):
        numeric_types = {"integer", "bigint", "float", "double", "decimal"}
        normalized_question = self._normalize_text(question)
        candidates = []
        for col in columns:
            col_type = getattr(getattr(col, "data_type", None), "value", "")
            if numeric_only and col_type not in numeric_types:
                continue
            col_name = str(getattr(col, "name", "") or "")
            if not col_name:
                continue
            normalized_col = self._normalize_text(col_name)
            if normalized_col and normalized_col in normalized_question:
                return col
            candidates.append(col)
        return candidates[0] if candidates else None

    def _build_fallback_sql(
        self,
        runtime: SimpleNamespace,
        datasource_id: int,
        question: str,
        *,
        selected_datasource_ids: Optional[list[int]] = None,
    ) -> tuple[str, str]:
        datasource_ids = [int(x) for x in (selected_datasource_ids or []) if int(x) > 0]
        if len(datasource_ids) > 1:
            raise RuntimeError("Multi-datasource querying currently requires a working LLM configuration.")

        datasource = runtime.get_datasource_handler(datasource_id)
        if datasource is None:
            raise FileNotFoundError(f"Datasource not found or not loaded: {datasource_id}")

        tables = datasource.get_tables()
        if not tables:
            raise RuntimeError("No tables found in datasource.")

        table = tables[0]
        table_name = self._quote_identifier(table.name)
        question_text = (question or "").strip()
        normalized_question = self._normalize_text(question_text)
        numeric_col = self._find_matching_column(question_text, table.columns, numeric_only=True)
        any_col = self._find_matching_column(question_text, table.columns, numeric_only=False)

        if any(token in normalized_question for token in ["多少行", "多少条", "总数", "总条数", "总记录", "count", "数量", "几条", "几行"]):
            return f"SELECT COUNT(*) AS total_count FROM {table_name}", "已按总行数统计。"

        if any(token in normalized_question for token in ["平均", "avg", "mean", "均值"]) and numeric_col:
            col_name = self._quote_identifier(numeric_col.name)
            return f"SELECT AVG({col_name}) AS avg_value FROM {table_name}", f"已计算 {numeric_col.name} 的平均值。"

        if any(token in normalized_question for token in ["总和", "求和", "sum", "合计"]) and numeric_col:
            col_name = self._quote_identifier(numeric_col.name)
            return f"SELECT SUM({col_name}) AS sum_value FROM {table_name}", f"已计算 {numeric_col.name} 的总和。"

        if any(token in normalized_question for token in ["最大", "最高", "max"]) and numeric_col:
            col_name = self._quote_identifier(numeric_col.name)
            if any(token in normalized_question for token in ["前", "top", "排序", "排行"]):
                limit = self._parse_limit(question_text, default=10)
                return (
                    f"SELECT * FROM {table_name} ORDER BY {col_name} DESC LIMIT {limit}",
                    f"已按 {numeric_col.name} 降序返回前 {limit} 条。",
                )
            return f"SELECT MAX({col_name}) AS max_value FROM {table_name}", f"已计算 {numeric_col.name} 的最大值。"

        if any(token in normalized_question for token in ["最小", "最低", "min"]) and numeric_col:
            col_name = self._quote_identifier(numeric_col.name)
            if any(token in normalized_question for token in ["前", "top", "排序", "排行"]):
                limit = self._parse_limit(question_text, default=10)
                return (
                    f"SELECT * FROM {table_name} ORDER BY {col_name} ASC LIMIT {limit}",
                    f"已按 {numeric_col.name} 升序返回前 {limit} 条。",
                )
            return f"SELECT MIN({col_name}) AS min_value FROM {table_name}", f"已计算 {numeric_col.name} 的最小值。"

        if any(token in normalized_question for token in ["排序", "排行", "top", "前"]) and (numeric_col or any_col):
            target_col = numeric_col or any_col
            col_name = self._quote_identifier(target_col.name)
            limit = self._parse_limit(question_text, default=10)
            descending = not any(token in normalized_question for token in ["升序", "最小", "最低", "asc"])
            direction = "DESC" if descending else "ASC"
            direction_text = "降序" if descending else "升序"
            return (
                f"SELECT * FROM {table_name} ORDER BY {col_name} {direction} LIMIT {limit}",
                f"已按 {target_col.name} {direction_text}返回前 {limit} 条。",
            )

        limit = self._parse_limit(question_text, default=20)
        return f"SELECT * FROM {table_name} LIMIT {limit}", f"已返回前 {limit} 条数据预览。"

    @staticmethod
    def _summarize_fallback_result(result: Any) -> str:
        if not getattr(result, "success", False):
            return "取数失败。"

        rows = getattr(result, "data", None) or []
        columns = getattr(result, "columns", None) or []
        row_count = int(getattr(result, "row_count", 0) or 0)
        if row_count == 1 and rows and len(columns) == 1:
            value = rows[0].get(columns[0])
            return f"结果为 {value}。"
        return f"已完成取数，返回 {row_count} 行结果。"

    def _build_unified_schema(
        self,
        runtime: SimpleNamespace,
        datasource_ids: list[int],
    ) -> tuple[str, Optional[Any]]:
        from fastapi_app.core.unified_engine import UnifiedQueryEngine

        engine = UnifiedQueryEngine()
        registered_names: list[str] = []
        for datasource_id in datasource_ids:
            handler = runtime.get_datasource_handler(datasource_id)
            if handler is None:
                continue
            registered_names.extend(engine.register_datasource(datasource_id, handler))
        schema_text = engine.get_unified_schema_text()
        if registered_names:
            schema_text += "\n\nUnified tables:\n" + "\n".join(f"- {name}" for name in registered_names)
        return schema_text, engine

    def _execute_embedded_query(
        self,
        runtime: SimpleNamespace,
        datasource_id: int,
        sql: str,
        selected_datasource_ids: Optional[list[int]] = None,
    ) -> tuple[dict[str, Any], Optional[Any]]:
        datasource_ids = [int(x) for x in (selected_datasource_ids or []) if int(x) > 0]
        if len(datasource_ids) > 1:
            schema_text, engine = self._build_unified_schema(runtime, datasource_ids)
            result = engine.execute_query(sql, limit=None)
            return {
                "schema_text": schema_text,
                "result": result,
                "engine": engine,
            }, engine

        datasource = runtime.get_datasource_handler(datasource_id)
        if datasource is None:
            raise FileNotFoundError(f"Datasource not found or not loaded: {datasource_id}")
        schema_text = datasource.get_all_schemas_text(format="llm")
        result = datasource.execute_query(sql, limit=None)
        return {
            "schema_text": schema_text,
            "result": result,
            "engine": None,
        }, None

    async def _run_fetch_workflow(
        self,
        runtime: SimpleNamespace,
        datasource_id: int,
        question: str,
        *,
        selected_datasource_ids: Optional[list[int]] = None,
        conversation_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        datasource_ids = [int(x) for x in (selected_datasource_ids or []) if int(x) > 0]
        datasource_ids = datasource_ids or [datasource_id]

        schema_text: str
        primary_hint = None
        engine = None
        if len(datasource_ids) > 1:
            schema_text, engine = self._build_unified_schema(runtime, datasource_ids)
        else:
            datasource = runtime.get_datasource_handler(datasource_id)
            if datasource is None:
                raise FileNotFoundError(f"Datasource not found or not loaded: {datasource_id}")
            schema_text = datasource.get_all_schemas_text(format="llm")
            tables = datasource.get_tables()
            if tables:
                primary_hint = tables[0].name

        messages = self._build_fetch_prompt(
            schema_text,
            question,
            primary_table_hint=primary_hint,
            multi_source=len(datasource_ids) > 1,
            previous_question=(conversation_context or {}).get("previous_question"),
            previous_sql=(conversation_context or {}).get("previous_sql"),
        )
        try:
            payload = await asyncio.to_thread(self._llm_request, messages)
            content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            parsed = self._extract_json_object(content)
            sql = str(parsed.get("sql") or "").strip()
            answer = str(parsed.get("answer") or "").strip()
            if not sql:
                raise RuntimeError("Embedded SQLBot could not generate SQL.")
        except Exception as exc:
            logger.warning("Embedded SQLBot LLM generation failed, using fallback SQL planner: %s", exc)
            sql, answer = self._build_fallback_sql(
                runtime,
                datasource_id,
                question,
                selected_datasource_ids=datasource_ids,
            )

        exec_payload, maybe_engine = self._execute_embedded_query(
            runtime,
            datasource_id,
            sql,
            selected_datasource_ids=datasource_ids,
        )
        result = exec_payload["result"]
        if maybe_engine is not None:
            maybe_engine.close()

        query_result_data = {
            "data": result.data or [],
            "columns": result.columns or [],
            "row_count": int(result.row_count or 0),
            "sql": sql,
        }
        if not answer:
            answer = self._summarize_fallback_result(result)

        export_data = {
            "format": "data",
            "data": query_result_data["data"],
            "columns": query_result_data["columns"],
            "row_count": query_result_data["row_count"],
        }

        return {
            "success": bool(result.success),
            "final_answer": answer,
            "thinking": None,
            "sql_history": [{"sql": sql, "success": bool(result.success), "error": result.error_message}],
            "last_sql": sql,
            "error": result.error_message,
            "query_result_data": query_result_data if result.success else None,
            "export_data": export_data if result.success else {"format": "data", "data": [], "columns": [], "row_count": 0},
        }

    def _store_csv(self, path: Path, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        if path.parent.resolve() == target_dir.resolve():
            return path

        suffix = path.suffix or ".csv"
        unique_name = f"{path.stem}_{uuid4().hex[:12]}{suffix}"
        dest = target_dir / unique_name
        if path.resolve() != dest.resolve():
            dest.write_bytes(path.read_bytes())
        return dest

    async def register_csv(self, file_path: str) -> Dict[str, Any]:
        runtime = self._ensure_runtime()
        source_path = Path(file_path)
        if not source_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        target_path = self._store_csv(source_path, runtime.sqlbot_settings.CSV_UPLOAD_DIR)

        with runtime.Session(runtime.engine) as session:
            datasource_db = runtime.Datasource(
                name=target_path.stem,
                type="csv",
                file_path=str(target_path),
                config="{}",
            )
            session.add(datasource_db)
            session.commit()
            session.refresh(datasource_db)

        ds_metadata = runtime.DataSourceMetadata(
            id=str(datasource_db.id),
            name=datasource_db.name,
            type=runtime.DataSourceType.CSV,
            connection_config={
                "file_path": str(target_path),
                "has_header": True,
                "auto_detect": True,
            },
        )
        csv_datasource = runtime.CSVDataSource(ds_metadata)
        csv_datasource.connect()

        tables = csv_datasource.get_tables()
        if tables:
            table = tables[0]
            rows = table.row_count or 0
            columns = len(table.columns)
        else:
            rows = 0
            columns = 0

        runtime.set_datasource_handler(datasource_db.id, csv_datasource, bootstrap=False)
        try:
            runtime.bootstrap_datasource(datasource_db.id, csv_datasource)
        except Exception as exc:
            logger.warning("Embedded datasource bootstrap skipped/failed for %s: %s", datasource_db.id, exc)

        preview_result = csv_datasource.get_sample_data(
            tables[0].name if tables else "data",
            limit=runtime.sqlbot_settings.CSV_PREVIEW_ROWS,
        )
        preview = preview_result.data if preview_result.success else []

        return {
            "datasource_id": datasource_db.id,
            "filename": target_path.name,
            "filepath": str(target_path),
            "rows": rows,
            "columns": columns,
            "file_size": target_path.stat().st_size,
            "preview": preview,
        }

    async def get_preview(self, datasource_id: int, rows: int = 10) -> Dict[str, Any]:
        runtime = self._ensure_runtime()
        datasource = runtime.get_datasource_handler(datasource_id)
        if not datasource:
            raise FileNotFoundError(f"Datasource not found or not loaded: {datasource_id}")

        tables = datasource.get_tables()
        if not tables:
            raise ValueError(f"No tables found in datasource {datasource_id}")

        table = tables[0]
        preview_result = datasource.get_sample_data(table.name, limit=rows)
        return {
            "datasource_id": datasource_id,
            "name": table.display_name or table.name,
            "rows": table.row_count,
            "columns": len(table.columns),
            "column_names": [col.name for col in table.columns],
            "column_types": {col.name: col.data_type.value for col in table.columns},
            "sample_data": preview_result.data if preview_result.success else [],
            "column_info": [col.to_dict() for col in table.columns],
        }

    async def start_chat(self, datasource_id: int, chat_title: str = "") -> Dict[str, Any]:
        runtime = self._ensure_runtime()
        with runtime.Session(runtime.engine) as session:
            chat = runtime.Chat(
                datasource_id=datasource_id,
                title=chat_title or "智能取数",
            )
            session.add(chat)
            session.commit()
            session.refresh(chat)
            return {
                "chat_id": chat.id,
                "datasource_id": chat.datasource_id,
                "title": chat.title,
                "created_at": chat.created_at.isoformat(),
            }

    async def send_message(
        self,
        chat_id: int,
        datasource_id: int,
        question: str,
        *,
        selected_datasource_ids: Optional[list[int]] = None,
        execution_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._bootstrap_env()
        runtime = self._ensure_runtime()
        with runtime.Session(runtime.engine) as session:
            chat = session.get(runtime.Chat, chat_id)
            if not chat:
                raise ValueError(f"Chat not found: {chat_id}")

            record = runtime.ChatRecord(
                chat_id=chat_id,
                question=question,
                status="processing",
            )
            session.add(record)
            session.commit()
            session.refresh(record)

            conversation_context = None
            prev_statement = (
                runtime.select(runtime.ChatRecord)
                .where(runtime.ChatRecord.chat_id == chat_id)
                .where(runtime.ChatRecord.status == "completed")
                .where(runtime.ChatRecord.id != record.id)
                .order_by(runtime.ChatRecord.created_at.desc())
            )
            prev_record = session.exec(prev_statement).first()
            if prev_record and prev_record.sql:
                conversation_context = {
                    "previous_question": prev_record.question,
                    "previous_sql": prev_record.sql,
                    "previous_summary": prev_record.result_summary or "",
                }

            start_time = asyncio.get_running_loop().time()
            if os.getenv("SQLBOT_EMBEDDED_MINIMAL", "").strip().lower() in {"1", "true", "yes", "on"}:
                result = await self._run_fetch_workflow(
                    runtime,
                    datasource_id,
                    question,
                    selected_datasource_ids=selected_datasource_ids,
                    conversation_context=conversation_context,
                )
            else:
                agent = await self._get_agent()
                result = await agent.run(
                    datasource_id,
                    question,
                    conversation_context=conversation_context,
                    selected_datasource_ids=selected_datasource_ids,
                    execution_strategy=execution_strategy,
                )
            duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)

            record.thinking = result.get("thinking")
            record.result_summary = result.get("final_answer")
            record.status = "completed" if result.get("success") else "error"
            record.error_message = result.get("error")
            record.completed_at = datetime.utcnow()
            record.duration_ms = duration_ms

            sql_history = result.get("sql_history", [])
            if sql_history:
                for sql_entry in reversed(sql_history):
                    if sql_entry.get("success"):
                        record.sql = sql_entry.get("sql")
                        break

            query_result_data = result.get("query_result_data")
            if query_result_data:
                record.set_result_data(query_result_data)

            session.add(record)
            chat.updated_at = datetime.utcnow()
            session.add(chat)
            session.commit()

            return {
                "chat_id": chat_id,
                "record_id": record.id,
                "message": {
                    "role": "assistant",
                    "content": result.get("final_answer", "无法生成答案"),
                    "timestamp": datetime.utcnow().isoformat(),
                },
                "status": record.status,
                "error": result.get("error"),
            }

    async def extract_data(self, chat_id: int, question: str, fmt: str = "json") -> Dict[str, Any]:
        self._bootstrap_env()
        runtime = self._ensure_runtime()
        with runtime.Session(runtime.engine) as session:
            chat = session.get(runtime.Chat, chat_id)
            if not chat:
                raise ValueError(f"Chat not found: {chat_id}")

            statement = (
                runtime.select(runtime.ChatRecord)
                .where(runtime.ChatRecord.chat_id == chat_id)
                .where(runtime.ChatRecord.question == question)
                .where(runtime.ChatRecord.status == "completed")
                .order_by(runtime.ChatRecord.created_at.desc())
            )
            cached_record = session.exec(statement).first()
            if cached_record and cached_record.result_data:
                cached_data = cached_record.get_result_data()
                if cached_data and cached_data.get("data"):
                    return {
                        "success": True,
                        "sql": cached_record.sql,
                        "data": {
                            "format": fmt,
                            "data": cached_data.get("data", []),
                            "columns": cached_data.get("columns", []),
                            "row_count": cached_data.get("row_count", 0),
                        },
                        "format": fmt,
                    }

            if os.getenv("SQLBOT_EMBEDDED_MINIMAL", "").strip().lower() in {"1", "true", "yes", "on"}:
                result = await self._run_fetch_workflow(runtime, chat.datasource_id, question)
            else:
                agent = await self._get_agent()
                from fastapi_app.agents.sqlbot_agent import DataFormat, OutputMode

                dfmt = (
                    DataFormat.JSON if fmt == "json"
                    else DataFormat.MARKDOWN if fmt == "markdown"
                    else DataFormat.CSV if fmt == "csv"
                    else DataFormat.DICT
                )
                result = await agent.run(
                    chat.datasource_id,
                    question,
                    output_mode=OutputMode.DATA,
                    data_format=dfmt,
                )
            return {
                "success": result.get("success", False),
                "sql": result.get("last_sql"),
                "data": result.get("export_data"),
                "format": fmt,
            }

    async def download_data(self, chat_id: int, question: str, fmt: str = "csv") -> EmbeddedDownloadResponse:
        self._bootstrap_env()
        runtime = self._ensure_runtime()
        with runtime.Session(runtime.engine) as session:
            chat = session.get(runtime.Chat, chat_id)
            if not chat:
                raise ValueError(f"Chat not found: {chat_id}")

            statement = (
                runtime.select(runtime.ChatRecord)
                .where(runtime.ChatRecord.chat_id == chat_id)
                .where(runtime.ChatRecord.question == question)
                .where(runtime.ChatRecord.status == "completed")
                .order_by(runtime.ChatRecord.created_at.desc())
            )
            cached_record = session.exec(statement).first()
            export_data = None
            if cached_record and cached_record.result_data:
                cached_data = cached_record.get_result_data()
                if cached_data and cached_data.get("data"):
                    data = cached_data.get("data", [])
                    columns = cached_data.get("columns", [])
                    if fmt.lower() == "csv":
                        csv_config = runtime.CSVExportConfig(encoding=runtime.CSVEncoding.UTF8_BOM)
                        generator = runtime.CSVGenerator(csv_config)
                        content = generator.generate_full(data, columns)
                        export_data = {"format": "csv", "content": content}
                    else:
                        export_data = {"format": "json", "data": data, "columns": columns}

            if export_data is None:
                if os.getenv("SQLBOT_EMBEDDED_MINIMAL", "").strip().lower() in {"1", "true", "yes", "on"}:
                    result = await self._run_fetch_workflow(runtime, chat.datasource_id, question)
                else:
                    agent = await self._get_agent()
                    from fastapi_app.agents.sqlbot_agent import DataFormat, OutputMode

                    result = await agent.run(
                        chat.datasource_id,
                        question,
                        output_mode=OutputMode.DATA,
                        data_format=DataFormat.CSV if fmt.lower() == "csv" else DataFormat.JSON,
                    )
                export_data = result.get("export_data") or {}

            title = chat.title or "export"
            ascii_title = "".join(c for c in title if c.isascii() and (c.isalnum() or c in (" ", "-", "_"))).strip()[:30] or "export"
            if fmt.lower() == "csv":
                content = str(export_data.get("content", "")).encode("utf-8")
                filename = f"{ascii_title}.csv"
                cd = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{urllib.parse.quote(title + ".csv")}'
                return EmbeddedDownloadResponse(
                    content=content,
                    headers={
                        "content-type": "text/csv; charset=utf-8",
                        "content-disposition": cd,
                    },
                )

            content = json.dumps(export_data, ensure_ascii=False, default=str).encode("utf-8")
            return EmbeddedDownloadResponse(
                content=content,
                headers={
                    "content-type": "application/json",
                    "content-disposition": f'attachment; filename="{ascii_title}.json"',
                },
            )
