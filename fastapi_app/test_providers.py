"""
Test Provider Architecture
"""
import asyncio
from fastapi_app.services.embedding_service import EmbeddingService
from fastapi_app.services.tts_service import TTSService


async def test_embedding_service():
    """Test EmbeddingService with Provider pattern"""
    service = EmbeddingService()
    print(f"Embedding Provider: {service.api_url} / {service.model}")

    # Test embed_texts
    texts = ["Hello world", "Test embedding"]
    embeddings = await service.embed_texts(texts)
    print(f"Generated {len(embeddings)} embeddings")

    # Test embed_query
    query_embedding = await service.embed_query("Test query")
    print(f"Query embedding dimension: {len(query_embedding)}")


async def test_tts_service():
    """Test TTSService with Provider pattern"""
    service = TTSService()
    print(f"TTS Provider: {service.api_url} / {service.model}")

    # Test synthesize
    audio = await service.synthesize("Hello world")
    print(f"Generated audio: {len(audio)} bytes")


if __name__ == "__main__":
    print("Testing Provider Architecture...")
    asyncio.run(test_embedding_service())
    asyncio.run(test_tts_service())
    print("Tests completed!")
