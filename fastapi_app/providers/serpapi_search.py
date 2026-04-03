import httpx
from typing import List, Dict, Any
from fastapi_app.providers.base import SearchProvider
from workflow_engine.logger import get_logger

log = get_logger(__name__)


class SerpApiSearchProvider(SearchProvider):
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def search(self, query: str, api_key: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """使用 SerpAPI 搜索（支持 Google / Baidu）"""
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": api_key,
            "num": max_results,
            "engine": "google",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("organic_results", [])[:max_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                log.info(f"SerpAPI search: query={query!r}, results={len(results)}")
                return results

        except Exception as e:
            log.error(f"SerpAPI search failed: {e}")
            raise
