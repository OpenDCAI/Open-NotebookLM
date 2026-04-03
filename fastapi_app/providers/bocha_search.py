import httpx
from typing import List, Dict, Any
from fastapi_app.providers.base import SearchProvider
from workflow_engine.logger import get_logger

log = get_logger(__name__)


class BochaSearchProvider(SearchProvider):
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def search(self, query: str, api_key: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """使用博查 API 搜索"""
        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "count": max_results,
            "freshness": "noLimit",
            "summary": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in (data.get("data", {}).get("webPages", {}).get("value", []))[:max_results]:
                    results.append({
                        "title": item.get("name", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                    })

                log.info(f"Bocha search: query={query!r}, results={len(results)}")
                return results

        except Exception as e:
            log.error(f"Bocha search failed: {e}")
            raise
