import os
import re
import wave
import base64
import io
import asyncio
from typing import Optional, List
import httpx
from workflow_engine.logger import get_logger
from workflow_engine.toolkits.multimodaltool.providers import get_provider
from workflow_engine.toolkits.multimodaltool.req_img import _post_raw
from workflow_engine.toolkits.multimodaltool.utils import detect_provider, Provider
from fastapi_app.config import settings

log = get_logger(__name__)

_RETRYABLE_TTS_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

# 全局模型缓存
_qwen_native_model = None

_GEMINI_TTS_MODEL_FALLBACKS = {
    "gemini-2.5-flash-tts": "gemini-2.5-pro-preview-tts",
}

_GEMINI_TTS_VOICES = {
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Aoede",
    "Enceladus",
    "Iapetus",
    "Algieba",
    "Despina",
    "Algenib",
    "Rasalgethi",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
    "Orus",
    "Orbit",
    "Trochilidae",
    "Zephyr",
}

_QWEN_TTS_VOICES = {
    "Cherry",
    "Chelsie",
}


def _normalize_api_tts_model(model: str) -> str:
    normalized = (model or "").strip()
    fallback = _GEMINI_TTS_MODEL_FALLBACKS.get(normalized.lower())
    if fallback:
        log.warning(f"[TTS] 模型 {normalized} 当前不可用，自动切换为 {fallback}")
        return fallback
    return normalized


def _normalize_api_tts_voice(model: str, voice_name: str) -> str:
    normalized_model = (model or "").lower()
    normalized_voice = (voice_name or "").strip()
    if "qwen" in normalized_model and "tts" in normalized_model:
        if normalized_voice in _QWEN_TTS_VOICES:
            return normalized_voice
        if normalized_voice:
            log.warning(f"[TTS] Qwen TTS 不支持音色 {normalized_voice}，自动切换为 Cherry")
        return "Cherry"
    if "gemini" in normalized_model and "tts" in normalized_model:
        if normalized_voice in _GEMINI_TTS_VOICES:
            return normalized_voice
        if normalized_voice:
            log.warning(f"[TTS] Gemini TTS 不支持音色 {normalized_voice}，自动切换为 Puck")
        return "Puck"
    return normalized_voice


def _setting_or_env(name: str, default: Optional[str] = None) -> Optional[str]:
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip() != "":
        return env_value
    setting_value = getattr(settings, name, None)
    if setting_value is None or setting_value == "":
        return default
    return str(setting_value)


def _resolve_tts_api_config(
    api_url: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
) -> tuple[str, str, str]:
    resolved_api_url = str(_setting_or_env("TTS_API_URL", "") or "").strip() or str(api_url or "").strip()
    resolved_api_key = str(_setting_or_env("TTS_API_KEY", "") or "").strip() or str(api_key or "").strip()
    resolved_model = str(_setting_or_env("TTS_MODEL", "") or "").strip() or str(model or "").strip()

    if not resolved_api_url:
        raise ValueError("Missing TTS api_url")
    if not resolved_api_key:
        raise ValueError("Missing TTS api_key")
    if not resolved_model:
        raise ValueError("Missing TTS model")
    return resolved_api_url, resolved_api_key, resolved_model


async def _call_openai_compatible_tts(
    *,
    api_url: str,
    api_key: str,
    model: str,
    text: str,
    voice_name: str,
    timeout: int,
    response_format: str = "wav",
    **kwargs,
) -> bytes:
    url = f"{api_url.rstrip('/')}/audio/speech"
    payload = {
        "model": model,
        "input": text,
        "voice": voice_name,
        "response_format": response_format,
    }
    language = kwargs.get("language")
    if language:
        payload["language"] = language
    instructions = kwargs.get("instructions")
    if instructions:
        payload["instructions"] = instructions

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    log.info(f"[TTS] OpenAI-compatible POST {url}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), http2=False) as client:
        resp = await client.post(url, headers=headers, json=payload)
        log.info(f"[TTS] openai-compatible status={resp.status_code}")
        resp.raise_for_status()
        return resp.content


async def _call_dashscope_qwen_tts(
    *,
    api_url: str,
    api_key: str,
    model: str,
    text: str,
    voice_name: str,
    timeout: int,
    **kwargs,
) -> bytes:
    base = api_url.rstrip("/")
    url = f"{base}/services/aigc/multimodal-generation/generation"
    lang_input = kwargs.get("language") or ""
    lang_map = {
        "zh": "Chinese",
        "en": "English",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "pt": "Portuguese",
        "ru": "Russian",
        "es": "Spanish",
    }
    language_type = lang_map.get(str(lang_input), str(lang_input) or "Auto")
    payload = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice_name,
            "language_type": language_type,
        },
    }
    instructions = kwargs.get("instructions")
    if instructions and "instruct" in model.lower():
        payload["parameters"] = {
            "instructions": instructions,
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    max_attempts = max(1, int(kwargs.get("max_attempts") or 1))
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), http2=False) as client:
        for attempt in range(1, max_attempts + 1):
            log.info(f"[TTS] DashScope Qwen TTS POST {url} attempt={attempt}/{max_attempts}")
            resp = await client.post(url, headers=headers, json=payload)
            log.info(f"[TTS] dashscope status={resp.status_code}")
            if resp.status_code >= 400:
                log.error(f"[TTS] dashscope body={resp.text[:1000]}")
            if resp.status_code in _RETRYABLE_TTS_STATUS_CODES and attempt < max_attempts:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(2 ** attempt, 20)
                except (TypeError, ValueError):
                    delay = min(2 ** attempt, 20)
                log.warning(
                    "[TTS] DashScope temporary error status=%s, retrying in %.1fs",
                    resp.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            break
        data = resp.json()
        audio = (data.get("output") or {}).get("audio") or {}
        audio_b64 = audio.get("data")
        if audio_b64:
            return base64.b64decode(audio_b64)
        audio_url = audio.get("url")
        if not audio_url:
            raise RuntimeError(f"DashScope TTS missing audio url: {str(data)[:400]}")
        audio_resp = await client.get(audio_url)
        audio_resp.raise_for_status()
        return audio_resp.content

def split_tts_text(content: str, limit: int) -> List[str]:
    if limit is None or limit <= 0:
        return [content]
    if len(content) <= limit:
        return [content]
    # Normalize whitespace
    content = content.replace("\r", "")
    parts: List[str] = []
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [content.strip()]

    sentence_splitter = re.compile(r"(?<=[。！？.!?;；])\s+")
    for para in paragraphs:
        if len(para) <= limit:
            parts.append(para)
            continue
        sentences = [s.strip() for s in sentence_splitter.split(para) if s.strip()]
        if not sentences:
            sentences = [para]
        buf = ""
        for sent in sentences:
            if not buf:
                buf = sent
                continue
            if len(buf) + 1 + len(sent) <= limit:
                buf = f"{buf} {sent}"
            else:
                parts.append(buf)
                buf = sent
        if buf:
            parts.append(buf)

    # Hard split if any chunk is still too large
    final_parts: List[str] = []
    for p in parts:
        if len(p) <= limit:
            final_parts.append(p)
        else:
            for i in range(0, len(p), limit):
                final_parts.append(p[i:i + limit])
    return final_parts


def _read_wav_frames(audio_bytes: bytes) -> Optional[tuple[int, int, int, bytes]]:
    if len(audio_bytes) < 12 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        return None

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            return (
                wav_file.getnchannels(),
                wav_file.getsampwidth(),
                wav_file.getframerate(),
                wav_file.readframes(wav_file.getnframes()),
            )
    except wave.Error:
        return None


def save_audio_chunks_to_wav(
    audio_chunks: List[bytes],
    save_path: str,
    default_channels: int = 1,
    default_sampwidth: int = 2,
    default_framerate: int = 24000,
) -> str:
    if not audio_chunks:
        raise ValueError("No audio chunks to save")

    log.info(f"[TTS] 保存音频: {len(audio_chunks)} 个chunks")
    for idx, chunk in enumerate(audio_chunks):
        log.info(f"[TTS] Chunk {idx+1}: {len(chunk)} bytes")

    wav_chunks: List[bytes] = []
    wav_params: Optional[tuple[int, int, int]] = None
    all_chunks_are_wav = True

    for idx, chunk in enumerate(audio_chunks, start=1):
        wav_payload = _read_wav_frames(chunk)
        if wav_payload is None:
            log.warning(f"[TTS] Chunk {idx} 无法解析为WAV格式")
            all_chunks_are_wav = False
            continue

        channels, sampwidth, framerate, frames = wav_payload
        current_params = (channels, sampwidth, framerate)
        if wav_params is None:
            wav_params = current_params
            log.info(f"[TTS] WAV参数: channels={channels}, sampwidth={sampwidth}, framerate={framerate}")
        elif wav_params != current_params:
            raise ValueError(
                f"Inconsistent WAV params across chunks: expected {wav_params}, got {current_params} at chunk {idx}"
            )
        wav_chunks.append(frames)
        log.info(f"[TTS] Chunk {idx} 解析成功，音频帧: {len(frames)} bytes")

    with wave.open(save_path, "wb") as wav_file:
        if wav_chunks and wav_params is not None:
            wav_file.setnchannels(wav_params[0])
            wav_file.setsampwidth(wav_params[1])
            wav_file.setframerate(wav_params[2])
            wav_file.writeframes(b"".join(wav_chunks))
        else:
            wav_file.setnchannels(default_channels)
            wav_file.setsampwidth(default_sampwidth)
            wav_file.setframerate(default_framerate)
            wav_file.writeframes(b"".join(audio_chunks))

    return save_path

async def generate_speech_bytes_async(
    text: str,
    api_url: str,
    api_key: str,
    model: str = "gemini-2.5-pro-preview-tts",
    voice_name: str = "Kore",
    timeout: int = 120,
    **kwargs,
) -> bytes:
    # 优先使用本地 TTS
    use_local = str(_setting_or_env("USE_LOCAL_TTS", "0") or "0").strip().lower() in ("1", "true", "yes")
    tts_engine = str(_setting_or_env("TTS_ENGINE", "qwen") or "qwen").strip().lower()
    log.info(f"[TTS] USE_LOCAL_TTS={use_local}, TTS_ENGINE={tts_engine}")

    if use_local:
        try:
            if tts_engine == "qwen":
                local_tts_api_url = str(_setting_or_env("LOCAL_TTS_API_URL", "http://127.0.0.1:26211/v1") or "http://127.0.0.1:26211/v1").rstrip("/")
                local_tts_model = str(_setting_or_env("LOCAL_TTS_MODEL", model or "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice") or (model or "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"))
                has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
                lang_input = kwargs.get("language") or ("Chinese" if has_chinese else "English")
                # Map language codes to vLLM-Omni expected format
                lang_map = {"zh": "Chinese", "en": "English", "fr": "French", "de": "German",
                           "it": "Italian", "ja": "Japanese", "ko": "Korean", "pt": "Portuguese",
                           "ru": "Russian", "es": "Spanish"}
                language = lang_map.get(lang_input, lang_input)
                instructions = kwargs.get("instructions") or (
                    "用自然、亲切的播客主播语气讲述，语速适中，富有感染力"
                    if has_chinese else
                    "Speak in a natural, friendly podcast host tone with moderate pace and engaging delivery"
                )
                payload = {
                    "model": local_tts_model,
                    "input": text,
                    "voice": voice_name,
                    "response_format": kwargs.get("response_format", "wav"),
                    "language": language,
                    "instructions": instructions,
                }
                headers = {"Content-Type": "application/json"}
                local_api_key = str(_setting_or_env("LOCAL_TTS_API_KEY", "") or "").strip()
                if local_api_key:
                    headers["Authorization"] = f"Bearer {local_api_key}"
                log.info(f"[TTS] 使用本地 Qwen3-TTS vLLM-Omni: {local_tts_api_url}/audio/speech")
                async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), http2=False) as client:
                    resp = await client.post(
                        f"{local_tts_api_url}/audio/speech",
                        headers=headers,
                        json=payload,
                    )
                    log.info(f"[TTS] local status={resp.status_code}")
                    resp.raise_for_status()
                    audio_data = resp.content
                    log.info(f"[TTS] Qwen返回音频数据大小: {len(audio_data)} bytes")
                    log.info(f"[TTS] Content-Type: {resp.headers.get('content-type', 'unknown')}")
                    if len(audio_data) < 500:
                        log.warning(f"[TTS] 音频数据过小，可能有问题。前200字节: {audio_data[:200]}")
                        try:
                            import json
                            error_json = json.loads(audio_data)
                            log.error(f"[TTS] vLLM返回JSON错误: {error_json}")
                            raise ValueError(f"vLLM-Omni返回错误: {error_json}")
                        except json.JSONDecodeError:
                            pass
                    return audio_data
            elif tts_engine == "qwen-native":
                # 直接使用qwen-tts包加载模型，不通过vLLM
                import torch
                import io
                import soundfile as sf
                from qwen_tts import Qwen3TTSModel

                log.info(f"[TTS] 使用原生 Qwen3-TTS（非 vLLM）")

                # 获取模型配置
                local_tts_model = str(_setting_or_env("LOCAL_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice") or "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
                tts_cuda = str(_setting_or_env("LOCAL_TTS_CUDA_VISIBLE_DEVICES", "0") or "0")

                # 语言和指令
                has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
                lang_input = kwargs.get("language") or ("Chinese" if has_chinese else "English")
                lang_map = {"zh": "Chinese", "en": "English", "fr": "French", "de": "German",
                           "it": "Italian", "ja": "Japanese", "ko": "Korean", "pt": "Portuguese",
                           "ru": "Russian", "es": "Spanish"}
                language = lang_map.get(lang_input, lang_input)
                instructions = kwargs.get("instructions") or (
                    "用自然、亲切的播客主播语气讲述，语速适中，富有感染力"
                    if has_chinese else
                    "Speak in a natural, friendly podcast host tone with moderate pace and engaging delivery"
                )

                # 加载模型（全局缓存）
                global _qwen_native_model
                if _qwen_native_model is None:
                    log.info(f"[TTS] 加载模型 {local_tts_model} 到 cuda:{tts_cuda}")
                    _qwen_native_model = Qwen3TTSModel.from_pretrained(
                        local_tts_model,
                        device_map=f"cuda:{tts_cuda}",
                        dtype=torch.bfloat16,
                    )

                # 生成音频
                wavs, sr = _qwen_native_model.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=voice_name,
                    instruct=instructions,
                )

                # 转换为WAV bytes
                buffer = io.BytesIO()
                sf.write(buffer, wavs[0], sr, format='WAV')
                audio_bytes = buffer.getvalue()
                log.info(f"[TTS] 原生Qwen生成音频: {len(audio_bytes)} bytes")
                return audio_bytes
            elif tts_engine == "firered":
                import sys
                from pathlib import Path
                sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "fastapi_app"))
                from fireredtts_manager import generate_speech, is_available
                log.info(f"[TTS] 使用本地 FireRedTTS2（非 vLLM）")
                if is_available():
                    import asyncio
                    # FireRedTTS requires [S1]/[S2] speaker tags
                    formatted_text = f"[S1]{text}"
                    audio_bytes = await asyncio.to_thread(generate_speech, formatted_text, voice_name)
                    return audio_bytes
            else:
                log.warning(f"[TTS] 未知引擎 {tts_engine}，回退到 API")
                raise ValueError(f"Unknown TTS engine: {tts_engine}")
        except Exception as e:
            log.warning(f"[TTS] 本地 TTS 失败: {type(e).__name__}: {str(e) or repr(e)}，回退到 API")

    # 回退到 API-based TTS
    api_url, api_key, model = _resolve_tts_api_config(api_url, api_key, model)
    api_tts_model = _normalize_api_tts_model(model)
    api_tts_voice = _normalize_api_tts_voice(api_tts_model, voice_name)

    if "dashscope.aliyuncs.com" in api_url and "qwen" in api_tts_model.lower() and "tts" in api_tts_model.lower():
        return await _call_dashscope_qwen_tts(
            api_url=api_url,
            api_key=api_key,
            model=api_tts_model,
            text=text,
            voice_name=api_tts_voice,
            timeout=timeout,
            **kwargs,
        )

    provider_type = detect_provider(api_url)
    if provider_type in (Provider.OTHER, Provider.LOCAL_123) and "tts" in api_tts_model.lower():
        return await _call_openai_compatible_tts(
            api_url=api_url,
            api_key=api_key,
            model=api_tts_model,
            text=text,
            voice_name=api_tts_voice,
            timeout=timeout,
            response_format=kwargs.get("response_format", "wav"),
            **kwargs,
        )

    provider = get_provider(api_url, api_tts_model)
    log.info(f"TTS using Provider: {provider.__class__.__name__}")

    try:
        url, payload, is_stream = provider.build_tts_request(
            api_url=api_url,
            model=api_tts_model,
            text=text,
            voice_name=api_tts_voice,
            **kwargs
        )
    except NotImplementedError:
        log.error(f"Provider {provider.__class__.__name__} does not support TTS")
        raise

    resp_data = await _post_raw(url, api_key, payload, timeout)
    try:
        audio_bytes = provider.parse_tts_response(resp_data)
    except Exception as e:
        log.error(f"Failed to parse TTS response: {e}")
        log.error(f"Response: {resp_data}")
        raise
    return audio_bytes


async def generate_speech_and_save_async(
    text: str,
    save_path: str,
    api_url: str,
    api_key: str,
    model: str = "gemini-2.5-pro-preview-tts",
    voice_name: str = "Kore", #Aoede, Charon, Fenrir, Kore, Puck, Orbit, Orus, Trochilidae, Zephyr
    timeout: int = 120,
    max_chars: int = 1500,
    **kwargs,
) -> str:
    """
    生成语音并保存为WAV文件
    """
    chunks = split_tts_text(text, max_chars)
    log.info(f"TTS split into {len(chunks)} chunk(s) with max_chars={max_chars}")

    audio_chunks: List[bytes] = []
    for idx, chunk in enumerate(chunks, start=1):
        try:
            audio_bytes = await generate_speech_bytes_async(
                text=chunk,
                api_url=api_url,
                api_key=api_key,
                model=model,
                voice_name=voice_name,
                timeout=timeout,
                **kwargs
            )
        except Exception as e:
            log.error(f"Failed to generate speech (chunk {idx}/{len(chunks)}): {e}")
            raise
        audio_chunks.append(audio_bytes)

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    save_audio_chunks_to_wav(audio_chunks, save_path)

    log.info(f"Audio saved to {save_path}")
    return save_path

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    
    async def _test():
        url = os.getenv("DF_API_URL", "https://api.apiyi.com/v1")
        key = os.getenv("DF_API_KEY", "")
        model = os.getenv("DF_TTS_MODEL", "gemini-2.5-pro-preview-tts")
        
        print(f"Testing TTS with URL: {url}, Model: {model}")
        try:
            path = await generate_speech_and_save_async(
                "是的！MCP的设计非常智能，特别是它的动态工具生成机制。开发者可以通过MCP为每个工具动态生成一个Python异步函数，直接调用这些工具就像调用普通函数一样。",
                "test_tts.wav",
                url, key, model
            )
            print(f"Success: {path}")
        except Exception as e:
            print(f"Error: {e}")
            
    asyncio.run(_test())
