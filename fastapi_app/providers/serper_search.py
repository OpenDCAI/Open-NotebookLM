import httpx
from typing import List, Dict, Any
from fastapi_app.providers.base import SearchProvider
from workflow_engine.logger import get_logger

log = get_logger(__name__)


class SerperSearchProvider(SearchProvider):
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def search(self, query: str, api_key: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """使用 Serper API 搜索"""
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "num": max_results
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("organic", [])[:max_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                log.info(f"Serper search: query={query}, results={len(results)}")
                return results

        except Exception as e:
            log.error(f"Serper search failed: {e}")
            raise
