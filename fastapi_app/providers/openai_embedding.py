from fastapi_app.providers.base import EmbeddingProvider
from typing import List
import httpx
import asyncio
import logging

log = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容 Embedding 接口"""

    def __init__(self, max_retries: int = 3, batch_size: int = 20):
        self.max_retries = max_retries
        self.batch_size = batch_size

    async def embed(self, texts: List[str], api_url: str, api_key: str, model: str) -> List[List[float]]:
        if not texts:
            return []

        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            embeddings = await self._embed_batch(batch, api_url, api_key, model)
            all_embeddings.extend(embeddings)
        return all_embeddings

    async def _embed_batch(self, texts: List[str], api_url: str, api_key: str, model: str) -> List[List[float]]:
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    headers = {"Content-Type": "application/json"}
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"
                    resp = await client.post(f"{api_url.rstrip('/')}/embeddings", headers=headers, json={"input": texts, "model": model})
                    resp.raise_for_status()
                    return [item["embedding"] for item in resp.json()["data"]]
            except Exception as e:
                if attempt == self.max_retries - 1:
                    log.error(f"Embedding failed: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)
