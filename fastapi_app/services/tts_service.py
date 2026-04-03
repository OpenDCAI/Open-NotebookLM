from typing import Optional
from fastapi_app.providers import tts_provider
from fastapi_app.config.settings import settings


class TTSService:
    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        return await tts_provider.synthesize(
            text,
            settings.TTS_API_URL,
            settings.TTS_API_KEY,
            settings.TTS_MODEL,
            voice
        )
