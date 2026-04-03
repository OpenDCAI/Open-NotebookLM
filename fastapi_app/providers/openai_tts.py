from fastapi_app.providers.base import TTSProvider
from typing import Optional
import httpx
import asyncio
import logging

log = logging.getLogger(__name__)


class OpenAITTSProvider(TTSProvider):
    """OpenAI 兼容 TTS 接口"""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def synthesize(self, text: str, api_url: str, api_key: str, model: str, voice: Optional[str] = None) -> bytes:
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    headers = {"Content-Type": "application/json"}
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"
                    resp = await client.post(f"{api_url.rstrip('/')}/audio/speech", headers=headers, json={"input": text, "model": model, "voice": voice or "alloy"})
                    resp.raise_for_status()
                    return resp.content
            except Exception as e:
                if attempt == self.max_retries - 1:
                    log.error(f"TTS failed: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)
