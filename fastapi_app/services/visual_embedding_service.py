"""
Visual embedding service using Qwen3-VL-Embedding (or any multimodal embedding API).

For images, the OpenAI-compatible request format is:
  POST /v1/embeddings
  {
    "model": "qwen3-vl-embedding",
    "input": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]
  }

For text (cross-modal retrieval against the visual index):
  POST /v1/embeddings
  {
    "model": "qwen3-vl-embedding",
    "input": "text string"
  }

Response follows the standard OpenAI embeddings format:
  {"data": [{"embedding": [...], "index": 0}]}
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List

import httpx

from fastapi_app.config.settings import settings

log = logging.getLogger(__name__)


def _resolve_visual_api_url() -> str:
    return (
        (settings.VISUAL_EMBEDDING_API_URL or "").strip()
        or (settings.EMBEDDING_API_URL or "").strip()
    )


def _resolve_visual_api_key() -> str:
    return (
        (settings.VISUAL_EMBEDDING_API_KEY or "").strip()
        or (settings.EMBEDDING_API_KEY or "").strip()
    )


class VisualEmbeddingService:
    """Calls a multimodal embedding API that accepts both images and text."""

    def __init__(self, max_retries: int = 3, timeout: float = 60.0):
        self.max_retries = max_retries
        self.timeout = timeout

    async def embed_image(self, data_url: str) -> List[float]:
        """Embed a single image supplied as a base64 data URL."""
        api_url = _resolve_visual_api_url()
        api_key = _resolve_visual_api_key()
        model = settings.VISUAL_EMBEDDING_MODEL

        payload = {
            "model": model,
            "input": [{"type": "image_url", "image_url": {"url": data_url}}],
        }
        return await self._call(api_url, api_key, payload)

    async def embed_text(self, text: str) -> List[float]:
        """Embed text using the visual embedding model (for cross-modal retrieval)."""
        api_url = _resolve_visual_api_url()
        api_key = _resolve_visual_api_key()
        model = settings.VISUAL_EMBEDDING_MODEL

        payload = {"model": model, "input": text}
        return await self._call(api_url, api_key, payload)

    async def embed_texts_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts in one API call (OpenAI-compatible batch input)."""
        api_url = _resolve_visual_api_url()
        api_key = _resolve_visual_api_key()
        model = settings.VISUAL_EMBEDDING_MODEL

        payload = {"model": model, "input": texts}
        url = f"{api_url.rstrip('/')}/embeddings"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    items = sorted(data["data"], key=lambda x: x["index"])
                    return [item["embedding"] for item in items]
            except Exception as exc:
                if attempt == self.max_retries - 1:
                    log.error(f"[VisualEmbedding] batch embed failed after {self.max_retries} attempts: {exc}")
                    raise
                await asyncio.sleep(2 ** attempt)
        return []

    def embed_texts_batch_sync(self, texts: List[str]) -> List[List[float]]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed_texts_batch(texts))
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(self.embed_texts_batch(texts))).result()

    async def _call(self, api_url: str, api_key: str, payload: dict) -> List[float]:
        url = f"{api_url.rstrip('/')}/embeddings"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["data"][0]["embedding"]
            except Exception as exc:
                if attempt == self.max_retries - 1:
                    log.error(f"[VisualEmbedding] failed after {self.max_retries} attempts: {exc}")
                    raise
                await asyncio.sleep(2 ** attempt)
        return []

    def embed_image_sync(self, data_url: str) -> List[float]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed_image(data_url))
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(self.embed_image(data_url))).result()

    def embed_text_sync(self, text: str) -> List[float]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed_text(text))
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(self.embed_text(text))).result()
