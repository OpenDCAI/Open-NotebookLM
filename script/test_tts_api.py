#!/usr/bin/env python3
"""
独立测试 TTS API（gemini-2.5-pro-preview-tts）是否可用。
用法:
  export API_KEY="sk-your-key"
  python script/test_tts_api.py

  或直接传 key（仅本地测试，勿提交）:
  python script/test_tts_api.py "sk-xxx"

  尝试其他 TTS 模型（若 apiyi 文档中有）:
  python script/test_tts_api.py "sk-xxx" "gemini-2.0-flash-tts"
"""
import base64
import json
import os
import sys
import urllib.request
import urllib.error

# 与 dataflow_agent/toolkits/multimodaltool/providers.py ApiYiGeminiProvider.build_tts_request 一致
API_BASE = "https://api.apiyi.com"
MODEL = "gemini-2.5-pro-preview-tts"
VOICE = "Kore"
TEST_TEXT = "你好，这是一段 TTS 测试。"


def get_api_key():
    if len(sys.argv) > 1 and sys.argv[1].startswith("sk-"):
        return sys.argv[1].strip()
    return os.environ.get("API_KEY", "").strip()


def get_model():
    if len(sys.argv) > 2:
        return sys.argv[2].strip()
    return os.environ.get("TTS_MODEL", MODEL)


def main():
    api_key = get_api_key()
    if not api_key:
        print("请设置环境变量 API_KEY 或通过第一个参数传入 key")
        print("例: API_KEY=sk-xxx python script/test_tts_api.py")
        sys.exit(1)
    model = get_model()

    url = f"{API_BASE}/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": TEST_TEXT}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": VOICE}
                }
            },
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    print(f"POST {url}")
    print(f"model={model}, voice={VOICE}, text={TEST_TEXT!r}")
    print("-" * 50)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"HTTP {e.code}: {e.reason}")
        print(f"Body: {body}")
        try:
            err = json.loads(body)
            print(f"解析: {json.dumps(err, ensure_ascii=False, indent=2)}")
            if err.get("error", {}).get("code") == "model_not_found":
                print("\n说明: 当前 API 服务商未开放该 TTS 模型。请查阅 apiyi 文档确认支持的 TTS 模型名，")
                print("  用第二个参数重试，例: python script/test_tts_api.py <key> <模型名>")
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"请求异常: {e}")
        sys.exit(1)

    if "error" in data:
        print("API 返回 error:")
        print(json.dumps(data["error"], ensure_ascii=False, indent=2))
        sys.exit(1)

    candidates = data.get("candidates", [])
    if not candidates:
        print("响应无 candidates:", json.dumps(data, ensure_ascii=False)[:500])
        sys.exit(1)

    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    if not parts:
        print("candidates[0].content 无 parts:", json.dumps(content, ensure_ascii=False)[:300])
        sys.exit(1)

    inline = parts[0].get("inlineData", {})
    b64 = inline.get("data")
    if not b64:
        print("parts[0] 无 inlineData.data")
        sys.exit(1)

    audio_bytes = base64.b64decode(b64)
    out_path = os.path.join(os.path.dirname(__file__), "..", "test_tts_out.wav")
    # Gemini TTS 返回为 PCM 16bit 24kHz mono，补 WAV 头便于播放
    n_frames = len(audio_bytes) // 2
    import wave
    with wave.open(out_path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(audio_bytes)
    print(f"成功: 收到 {len(audio_bytes)} 字节 PCM，已写入 WAV {out_path}")
    print("TTS 接口可用。")


if __name__ == "__main__":
    main()
