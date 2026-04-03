"""
ApiYi TTS Provider 独立测试
运行: python providers/apiyi_tts.py
"""
from fastapi_app.providers.base import TTSProvider
from typing import Optional
import httpx
import asyncio
import logging

log = logging.getLogger(__name__)


class ApiYiTTSProvider(TTSProvider):
    """ApiYi TTS Provider - gemini-2.5-flash-tts"""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def synthesize(self, text: str, api_url: str, api_key: str, model: str, voice: Optional[str] = None) -> bytes:
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{api_url.rstrip('/')}/audio/speech",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"input": text, "model": model, "voice": voice or "alloy"}
                    )
                    resp.raise_for_status()
                    return resp.content
            except Exception as e:
                if attempt == self.max_retries - 1:
                    log.error(f"ApiYi TTS failed: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)


if __name__ == "__main__":
    async def test():
        provider = ApiYiTTSProvider()
        api_url = "https://api.apiyi.com/v1"
        api_key = "sk-IU27kBNHcenZqp2O97A4D30f32194cE2B16a07Cb8fC9B0A6"
        model = "gemini-2.5-flash-tts"
        text = "Hello world"

        print("测试 ApiYi TTS (gemini-2.5-flash-tts)...")
        audio = await provider.synthesize(text, api_url, api_key, model)
        print(f"✓ 成功! 音频大小: {len(audio)} bytes")

    asyncio.run(test())
