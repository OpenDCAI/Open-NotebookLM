"""
ApiYi Embedding Provider 独立测试
运行: python providers/apiyi_embedding.py
"""
from fastapi_app.providers.base import EmbeddingProvider
from typing import List
import httpx
import asyncio
import logging

log = logging.getLogger(__name__)


class ApiYiEmbeddingProvider(EmbeddingProvider):
    """ApiYi Embedding Provider - text-embedding-3-small"""

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
                    resp = await client.post(
                        f"{api_url.rstrip('/')}/embeddings",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"input": texts, "model": model}
                    )
                    resp.raise_for_status()
                    return [item["embedding"] for item in resp.json()["data"]]
            except Exception as e:
                if attempt == self.max_retries - 1:
                    log.error(f"ApiYi Embedding failed: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)


if __name__ == "__main__":
    async def test():
        provider = ApiYiEmbeddingProvider()
        api_url = "https://api.apiyi.com/v1"
        api_key = "sk-IU27kBNHcenZqp2O97A4D30f32194cE2B16a07Cb8fC9B0A6"
        model = "text-embedding-3-small"
        texts = ["Hello world", "Test embedding"]

        print("测试 ApiYi Embedding...")
        embeddings = await provider.embed(texts, api_url, api_key, model)
        print(f"✓ 成功! 返回 {len(embeddings)} 个向量，维度: {len(embeddings[0])}")

    asyncio.run(test())
