from fastapi import APIRouter
from fastapi_app.providers import tts_provider

router = APIRouter(prefix="/tts", tags=["TTS"])


@router.get("/voices")
async def get_voices():
    """获取当前 TTS Provider 支持的音色列表"""
    return {"voices": tts_provider.get_voices()}
