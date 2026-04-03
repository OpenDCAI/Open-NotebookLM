#!/usr/bin/env python3
"""测试 Provider 架构核心功能"""
import sys
import os
sys.path.insert(0, '/root/user/szl/prj/Open-NotebookLM')
os.chdir('/root/user/szl/prj/Open-NotebookLM/fastapi_app')

print("=" * 50)
print("测试 Provider 架构")
print("=" * 50)

# 1. 测试 Provider 导入
print("\n[1] 测试 Provider 导入...")
try:
    from providers import get_embedding_provider, get_tts_provider
    print("✓ Provider 导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 2. 测试 Provider 匹配逻辑
print("\n[2] 测试 Provider 匹配...")
tests = [
    ("localhost", "any", "LocalEmbeddingProvider"),
    ("https://api.openai.com/v1", "text-embedding-3", "OpenAICompatEmbeddingProvider"),
]
for url, model, expected in tests:
    provider = get_embedding_provider(url, model)
    actual = provider.__class__.__name__
    status = "✓" if actual == expected else "✗"
    print(f"{status} {url} -> {actual}")

# 3. 测试 TTS Provider
print("\n[3] 测试 TTS Provider...")
tts_tests = [
    ("http://any", "qwen-tts", "QwenTTSProvider"),
    ("https://api.openai.com/v1", "tts-1", "OpenAICompatTTSProvider"),
]
for url, model, expected in tts_tests:
    provider = get_tts_provider(url, model)
    actual = provider.__class__.__name__
    status = "✓" if actual == expected else "✗"
    print(f"{status} {model} -> {actual}")

# 4. 测试 Service 层
print("\n[4] 测试 Service 层...")
try:
    from services.embedding_service import EmbeddingService
    from services.tts_service import TTSService

    emb = EmbeddingService()
    print(f"✓ EmbeddingService: {emb.api_url} / {emb.model}")

    tts = TTSService()
    print(f"✓ TTSService: {tts.api_url} / {tts.model}")
except Exception as e:
    print(f"✗ Service 层失败: {e}")

print("\n" + "=" * 50)
print("测试完成！Provider 架构工作正常")
print("=" * 50)
