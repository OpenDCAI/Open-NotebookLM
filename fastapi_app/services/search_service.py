from typing import List, Dict, Any
from fastapi import HTTPException
from fastapi_app.providers import search_provider
from fastapi_app.config.settings import settings
from workflow_engine.logger import get_logger

log = get_logger(__name__)

# 各 provider 对应的 key 字段
_PROVIDER_KEY_MAP = {
    "serper": lambda: settings.SERPER_API_KEY,
    "serpapi": lambda: settings.SERPAPI_KEY,
    "bocha": lambda: settings.BOCHA_API_KEY,
}


class SearchService:
    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        provider_name = settings.SEARCH_PROVIDER.lower()
        key_getter = _PROVIDER_KEY_MAP.get(provider_name)
        api_key = key_getter() if key_getter else None

        if not api_key:
            raise HTTPException(
                status_code=503,
                detail=f"Search API key not configured for provider '{provider_name}'"
            )
        try:
            results = await search_provider.search(query, api_key, max_results)
            log.info(f"Search [{provider_name}]: query={query!r}, results={len(results)}")
            return results
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Search failed [{provider_name}]: {e}")
            raise HTTPException(status_code=500, detail=f"Search failed: {e}")
