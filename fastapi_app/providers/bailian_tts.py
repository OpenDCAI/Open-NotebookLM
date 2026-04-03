"""
阿里云百炼 TTS Provider
运行: python -m providers.bailian_tts
"""
from fastapi_app.providers.base import TTSProvider
from typing import Optional, List, Dict
import httpx
import asyncio
import logging

log = logging.getLogger(__name__)


class BaiLianTTSProvider(TTSProvider):
    """阿里云百炼 TTS Provider"""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def get_voices(self) -> List[Dict[str, str]]:
        """返回支持的音色列表"""
        return [
            {"id": "zhixiaobai", "name": "知小白（女声）"},
            {"id": "zhichu", "name": "知楚（男声）"},
            {"id": "zhimiao", "name": "知妙（女声）"},
            {"id": "zhiyan", "name": "知燕（女声）"},
            {"id": "zhiyuan", "name": "知渊（男声）"},
        ]

    async def synthesize(self, text: str, api_url: str, api_key: str, model: str, voice: Optional[str] = None) -> bytes:
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{api_url.rstrip('/')}/services/aigc/multimodal-generation/generation",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": model, "input": {"text": text}, "parameters": {"voice": voice or "Cherry"}}
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    audio_url = result["output"]["audio"]["url"]
                    audio_resp = await client.get(audio_url)
                    return audio_resp.content
            except Exception as e:
                if attempt == self.max_retries - 1:
                    log.error(f"BaiLian TTS failed: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)


if __name__ == "__main__":
    async def test():
        provider = BaiLianTTSProvider()
        print(f"✓ 支持的音色: {len(provider.get_voices())} 个")

        api_url = "https://dashscope.aliyuncs.com/api/v1"
        api_key = "sk-4a290ed8704047b3870b04cbff040d98"
        model = "qwen3-tts-flash"
        text = "你好，这是百炼语音合成测试"

        print(f"测试百炼 TTS (qwen3-tts-flash)...")
        audio = await provider.synthesize(text, api_url, api_key, model, "Cherry")
        print(f"✓ 成功! 音频大小: {len(audio)} bytes")

    asyncio.run(test())
