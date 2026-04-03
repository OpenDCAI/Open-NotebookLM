import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List
from fastapi_app.providers import embedding_provider
from fastapi_app.config.settings import settings


class EmbeddingService:
    async def embed(self, texts: List[str]) -> List[List[float]]:
        return await embedding_provider.embed(
            texts,
            settings.EMBEDDING_API_URL,
            settings.EMBEDDING_API_KEY,
            settings.EMBEDDING_MODEL
        )

    def embed_sync(self, texts: List[str]) -> List[List[float]]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed(texts))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(self.embed(texts)))
            return future.result()
