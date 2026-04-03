from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from fastapi_app.config import settings
from fastapi_app.services.embedded_sqlbot import EmbeddedSQLBotAdapter


class ExternalSQLBotAdapter:
    """Thin HTTP adapter for an external SQLBot service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        llm_api_base: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or settings.SQLBOT_BASE_URL).rstrip("/")
        self.api_key = (api_key or settings.SQLBOT_API_KEY or "").strip()
        self._trust_env = not self._is_local_base_url(self.base_url)

    @staticmethod
    def _is_local_base_url(base_url: str) -> bool:
        hostname = (urlparse(base_url).hostname or "").strip().lower()
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, trust_env=self._trust_env)

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["X-SQLBOT-KEY"] = self.api_key
        return headers

    async def register_csv(self, file_path: str) -> Dict[str, Any]:
        path = Path(file_path)
        async with self._client(timeout=60.0) as client:
            with path.open("rb") as handle:
                files = {
                    "file": (path.name, handle, "text/csv"),
                }
                resp = await client.post(
                    f"{self.base_url}/api/upload/csv",
                    files=files,
                    headers=self._headers(),
                )
        resp.raise_for_status()
        return resp.json()

    async def get_preview(self, datasource_id: int, rows: int = 10) -> Dict[str, Any]:
        async with self._client(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/api/upload/datasource/{datasource_id}/preview",
                params={"rows": rows},
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def start_chat(self, datasource_id: int, chat_title: str = "") -> Dict[str, Any]:
        payload = {
            "datasource_id": datasource_id,
            "chat_title": chat_title,
        }
        async with self._client(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat/start",
                json=payload,
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def send_message(
        self,
        chat_id: int,
        datasource_id: int,
        question: str,
        *,
        selected_datasource_ids: Optional[list[int]] = None,
        execution_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "datasource_id": datasource_id,
            "question": question,
        }
        if selected_datasource_ids:
            payload["selected_datasource_ids"] = selected_datasource_ids
        if execution_strategy:
            payload["execution_strategy"] = execution_strategy

        async with self._client(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat/message/{chat_id}",
                json=payload,
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def extract_data(self, chat_id: int, question: str, fmt: str = "json") -> Dict[str, Any]:
        payload = {
            "question": question,
            "format": fmt,
        }
        async with self._client(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat/extract/{chat_id}",
                json=payload,
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def download_data(self, chat_id: int, question: str, fmt: str = "csv"):
        async with self._client(timeout=120.0) as client:
            resp = await client.get(
                f"{self.base_url}/api/chat/extract/{chat_id}/download",
                params={"question": question, "format": fmt},
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp


class SQLBotAdapter:
    """Facade adapter that switches between external and embedded SQLBot modes."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        llm_api_base: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> None:
        mode = (settings.SQLBOT_MODE or "external").strip().lower()
        if mode == "embedded":
            self._impl = EmbeddedSQLBotAdapter(
                api_key=api_key,
                llm_api_base=llm_api_base,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
            )
        else:
            self._impl = ExternalSQLBotAdapter(
                base_url=base_url,
                api_key=api_key,
                llm_api_base=llm_api_base,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
            )

    async def register_csv(self, file_path: str) -> Dict[str, Any]:
        return await self._impl.register_csv(file_path)

    async def get_preview(self, datasource_id: int, rows: int = 10) -> Dict[str, Any]:
        return await self._impl.get_preview(datasource_id, rows=rows)

    async def start_chat(self, datasource_id: int, chat_title: str = "") -> Dict[str, Any]:
        return await self._impl.start_chat(datasource_id=datasource_id, chat_title=chat_title)

    async def send_message(
        self,
        chat_id: int,
        datasource_id: int,
        question: str,
        *,
        selected_datasource_ids: Optional[list[int]] = None,
        execution_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._impl.send_message(
            chat_id,
            datasource_id,
            question,
            selected_datasource_ids=selected_datasource_ids,
            execution_strategy=execution_strategy,
        )

    async def extract_data(self, chat_id: int, question: str, fmt: str = "json") -> Dict[str, Any]:
        return await self._impl.extract_data(chat_id, question, fmt=fmt)

    async def download_data(self, chat_id: int, question: str, fmt: str = "csv"):
        return await self._impl.download_data(chat_id, question, fmt=fmt)
