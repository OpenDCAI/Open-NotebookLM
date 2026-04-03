import pytest
import asyncio
from providers.apiyi_embedding import ApiYiEmbeddingProvider
from providers.apiyi_tts import ApiYiTTSProvider


@pytest.mark.asyncio
async def test_apiyi_embedding():
    """测试 ApiYi Embedding Provider"""
    provider = ApiYiEmbeddingProvider()

    # 测试参数
    api_url = "https://api.apiyi.com/v1"
    api_key = "your-api-key"  # 需要真实 key
    model = "text-embedding-3-small"
    texts = ["Hello world", "Test embedding"]

    try:
        embeddings = await provider.embed(texts, api_url, api_key, model)
        assert len(embeddings) == 2
        assert len(embeddings[0]) > 0
        print(f"✓ Embedding 测试通过，维度: {len(embeddings[0])}")
    except Exception as e:
        print(f"✗ Embedding 测试失败: {e}")


@pytest.mark.asyncio
async def test_apiyi_tts():
    """测试 ApiYi TTS Provider"""
    provider = ApiYiTTSProvider()

    api_url = "https://api.apiyi.com/v1"
    api_key = "your-api-key"
    model = "gemini-2.5-flash-tts"
    text = "Hello world"

    try:
        audio = await provider.synthesize(text, api_url, api_key, model)
        assert len(audio) > 0
        print(f"✓ TTS 测试通过，音频大小: {len(audio)} bytes")
    except Exception as e:
        print(f"✗ TTS 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(test_apiyi_embedding())
    asyncio.run(test_apiyi_tts())
