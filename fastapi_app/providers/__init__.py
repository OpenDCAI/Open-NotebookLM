"""
Provider 统一导出接口
根据环境变量自动选择 Search Provider，无需改代码切换。
"""
from fastapi_app.providers.apiyi_embedding import ApiYiEmbeddingProvider
from fastapi_app.providers.apiyi_tts import ApiYiTTSProvider
from fastapi_app.providers.serper_search import SerperSearchProvider
from fastapi_app.providers.serpapi_search import SerpApiSearchProvider
from fastapi_app.providers.bocha_search import BochaSearchProvider
from fastapi_app.config.settings import settings
from workflow_engine.logger import get_logger

log = get_logger(__name__)

# Embedding & TTS
embedding_provider = ApiYiEmbeddingProvider(max_retries=3, batch_size=20)
tts_provider = ApiYiTTSProvider(max_retries=3)

# Search: 由 SEARCH_PROVIDER env 决定
_SEARCH_PROVIDERS = {
    "serper": SerperSearchProvider,
    "serpapi": SerpApiSearchProvider,
    "bocha": BochaSearchProvider,
}

_provider_name = settings.SEARCH_PROVIDER.lower()
if _provider_name not in _SEARCH_PROVIDERS:
    log.warning(f"Unknown SEARCH_PROVIDER={_provider_name!r}, falling back to 'serper'")
    _provider_name = "serper"

search_provider = _SEARCH_PROVIDERS[_provider_name](timeout=30)
log.info(f"Search provider: {_provider_name}")
