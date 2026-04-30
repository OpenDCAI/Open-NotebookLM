#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

try:
    from fastapi import FastAPI, HTTPException
except ModuleNotFoundError:
    FastAPI = None

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


DEFAULT_PROJECT_ROOT = str(Path(__file__).resolve().parent)
DEFAULT_MODEL_DIR = (
    f"{DEFAULT_PROJECT_ROOT}/models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled"
)
DEFAULT_VISIBLE_GPUS = "0,1,2,3"


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _parse_visible_gpus(value: str) -> list[int]:
    cleaned = [part.strip() for part in value.split(",") if part.strip()]
    if not cleaned:
        return [0]
    return [int(part) for part in cleaned]


def _remap_visible_gpus_for_process(visible_gpus: list[int], cuda_visible_devices: str) -> list[int]:
    cleaned = [part.strip() for part in cuda_visible_devices.split(",") if part.strip()]
    if not cleaned:
        return visible_gpus
    mapping = {int(device): index for index, device in enumerate(int(part) for part in cleaned)}
    return [mapping.get(gpu, gpu) for gpu in visible_gpus]


PROJECT_ROOT = os.environ.get("LOCAL_QWEN35_C500_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)
MODEL_DIR = os.environ.get("LOCAL_QWEN35_C500_MODEL_DIR", DEFAULT_MODEL_DIR)
MODEL_NAME = os.environ.get(
    "LOCAL_QWEN35_C500_MODEL_NAME",
    "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
)
DEFAULT_JSON_MAX_NEW_TOKENS_CAP = _env_int("LOCAL_QWEN35_C500_DEFAULT_JSON_MAX_NEW_TOKENS", 2048)
DEFAULT_TEXT_MAX_NEW_TOKENS_CAP = _env_int("LOCAL_QWEN35_C500_DEFAULT_TEXT_MAX_NEW_TOKENS", 4096)
DEFAULT_JSON_MAX_TIME_SECONDS = float(os.environ.get("LOCAL_QWEN35_C500_DEFAULT_JSON_MAX_TIME_SECONDS", "120"))
DEFAULT_TEXT_MAX_TIME_SECONDS = float(os.environ.get("LOCAL_QWEN35_C500_DEFAULT_TEXT_MAX_TIME_SECONDS", "240"))
MAX_NEW_TOKENS = _env_int("LOCAL_QWEN35_C500_MAX_NEW_TOKENS", 0)
GPU_MEMORY_GIB = _env_int("LOCAL_QWEN35_C500_GPU_MEMORY_GIB", 20)
CPU_MEMORY_GIB = _env_int("LOCAL_QWEN35_C500_CPU_MEMORY_GIB", 160)
VISIBLE_GPUS = _parse_visible_gpus(
    os.environ.get("LOCAL_QWEN35_C500_VISIBLE_GPUS", DEFAULT_VISIBLE_GPUS)
)
PROCESS_VISIBLE_GPUS = _remap_visible_gpus_for_process(
    VISIBLE_GPUS,
    os.environ.get("CUDA_VISIBLE_DEVICES", ""),
)
GPU_INDEX = _env_int("LOCAL_QWEN35_C500_GPU_INDEX", VISIBLE_GPUS[0])
PREFER_GPU_ONLY = os.environ.get("LOCAL_QWEN35_C500_PREFER_GPU_ONLY", "0") != "0"
REASONING_MODE = os.environ.get("LOCAL_QWEN35_C500_REASONING_MODE", "default").strip().lower()
RETURN_FINAL_ONLY = os.environ.get("LOCAL_QWEN35_C500_RETURN_FINAL_ONLY", "1") != "0"
ATTN_IMPLEMENTATION = os.environ.get("LOCAL_QWEN35_C500_ATTN_IMPLEMENTATION", "").strip() or None


class ChatMessage(BaseModel):
    role: str
    content: Any

    model_config = ConfigDict(extra="allow")


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = 0.2
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


if FastAPI is not None:
    app = FastAPI(title="PresentAgent Local Qwen3.5 C500 Server")
else:
    app = None
_lock = threading.Lock()
_runtime: dict[str, Any] = {}


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content or "")


def _render_prompt(messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> str:
    normalized_messages = list(messages)
    json_mode = bool(response_format and response_format.get("type") == "json_object")
    if response_format and response_format.get("type") == "json_object":
        json_system = (
            "You are a structured generation assistant. "
            "Return valid JSON only. Do not include markdown fences. "
            "Do not output chain-of-thought or reasoning. "
            "Start immediately with { and return exactly one JSON object."
        )
        if normalized_messages and normalized_messages[0].get("role") == "system":
            normalized_messages[0] = {
                "role": "system",
                "content": json_system + "\n\n" + normalized_messages[0].get("content", ""),
            }
        else:
            normalized_messages.insert(0, {"role": "system", "content": json_system})

    parts: list[str] = []
    for message in normalized_messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role not in {"system", "user", "assistant"}:
            role = "user"
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>\n")
    if REASONING_MODE == "disabled":
        parts.append("<|im_start|>assistant\n{" if json_mode else "<|im_start|>assistant\n")
    else:
        parts.append("<|im_start|>assistant\n{" if json_mode else "<|im_start|>assistant\n<think>\n")
    return "".join(parts)


def _extract_json_text(text: str) -> str:
    fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
    if fenced_match:
        return fenced_match.group(1).strip()
    json_start = text.find("{")
    json_end = text.rfind("}")
    if json_start == -1 or json_end == -1 or json_end < json_start:
        return ""
    return text[json_start : json_end + 1].strip()


def _postprocess_content(content: str, json_mode: bool) -> str:
    raw = content.strip()
    candidate = raw

    if RETURN_FINAL_ONLY:
        if "</think>" in candidate:
            candidate = candidate.split("</think>", 1)[1].strip()
        candidate = re.sub(r"^\s*<think>\s*", "", candidate, flags=re.DOTALL).strip()

    if json_mode:
        json_text = _extract_json_text(candidate) or _extract_json_text(raw)
        if json_text:
            return json_text
        body_only = candidate.lstrip()
        if body_only and not body_only.startswith("{"):
            wrapped = "{" + body_only
            json_text = _extract_json_text(wrapped)
            if json_text:
                return json_text

    return candidate or raw


def _resolve_context_window(cfg: Any, text_cfg: Any) -> int:
    for source in (text_cfg, cfg):
        if source is None:
            continue
        for field in ("max_position_embeddings", "sliding_window", "model_max_length"):
            value = getattr(source, field, None)
            if isinstance(value, int) and value > 0:
                return value
    return 8192


def _resolve_max_new_tokens(
    *,
    prompt_tokens: int,
    context_window: int,
    configured_cap: int,
    request_max_tokens: int | None,
    json_mode: bool,
) -> int:
    available_completion_tokens = context_window - prompt_tokens
    if available_completion_tokens <= 0:
        raise ValueError("Prompt reaches or exceeds the model context window.")

    default_cap = DEFAULT_JSON_MAX_NEW_TOKENS_CAP if json_mode else DEFAULT_TEXT_MAX_NEW_TOKENS_CAP
    configured_limit = configured_cap if configured_cap > 0 else default_cap
    if request_max_tokens is not None and int(request_max_tokens) > 0:
        requested_completion_tokens = int(request_max_tokens)
    else:
        requested_completion_tokens = default_cap

    return max(
        1,
        min(requested_completion_tokens, configured_limit, available_completion_tokens),
    )


def _resolve_max_time_seconds(*, json_mode: bool) -> float:
    return DEFAULT_JSON_MAX_TIME_SECONDS if json_mode else DEFAULT_TEXT_MAX_TIME_SECONDS


def _build_device_map(visible_gpus: list[int], prefer_gpu_only: bool) -> tuple[Any, dict[Any, str] | None, str]:
    if prefer_gpu_only:
        if len(visible_gpus) == 1:
            return {"": visible_gpus[0]}, None, f"cuda:{visible_gpus[0]}"
        return "auto", {gpu: f"{GPU_MEMORY_GIB}GiB" for gpu in visible_gpus}, f"cuda:{visible_gpus[0]}"

    max_memory: dict[Any, str] = {gpu: f"{GPU_MEMORY_GIB}GiB" for gpu in visible_gpus}
    max_memory["cpu"] = f"{CPU_MEMORY_GIB}GiB"
    return "auto", max_memory, f"cuda:{visible_gpus[0]}"


def _load_runtime() -> dict[str, Any]:
    if _runtime:
        return _runtime

    import torch
    from transformers import AutoConfig, AutoTokenizer, Qwen3_5ForConditionalGeneration

    cfg = AutoConfig.from_pretrained(
        MODEL_DIR,
        trust_remote_code=True,
        local_files_only=True,
    )
    if hasattr(cfg, "use_cache"):
        cfg.use_cache = True
    text_cfg = getattr(cfg, "text_config", cfg)
    if hasattr(text_cfg, "use_cache"):
        text_cfg.use_cache = True
    context_window = _resolve_context_window(cfg, text_cfg)
    tokenizer_kwargs = {
        "trust_remote_code": True,
        "local_files_only": True,
    }
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_DIR,
            fix_mistral_regex=True,
            **tokenizer_kwargs,
        )
    except Exception as exc:
        print(f"[local-qwen] tokenizer fix_mistral_regex fallback: {exc}", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, **tokenizer_kwargs)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available for the local Qwen server.")
    device_count = int(torch.cuda.device_count())
    invalid_gpus = [gpu for gpu in PROCESS_VISIBLE_GPUS if gpu < 0 or gpu >= device_count]
    if invalid_gpus:
        raise RuntimeError(
            f"Configured visible GPUs {invalid_gpus} are out of range; available device count is {device_count}."
        )
    primary_gpu = PROCESS_VISIBLE_GPUS[0]
    process_gpu_index = _remap_visible_gpus_for_process(
        [GPU_INDEX],
        os.environ.get("CUDA_VISIBLE_DEVICES", ""),
    )[0]
    if process_gpu_index not in PROCESS_VISIBLE_GPUS:
        raise RuntimeError(
            f"Configured GPU index {GPU_INDEX} is not included in visible GPUs {VISIBLE_GPUS}."
        )
    torch.cuda.set_device(primary_gpu)
    device_map, max_memory, device = _build_device_map(PROCESS_VISIBLE_GPUS, PREFER_GPU_ONLY)
    load_attempts: list[tuple[str, dict[str, Any]]] = []
    if PREFER_GPU_ONLY:
        load_attempts.append(
            (
                "gpu_only",
                {
                    "device_map": device_map,
                },
            )
        )
    load_attempts.append(
        (
            "auto_offload",
            {
                "device_map": device_map if len(VISIBLE_GPUS) > 1 else "auto",
                "max_memory": max_memory,
                "offload_buffers": True,
            },
        )
    )

    model = None
    last_error: Exception | None = None
    for strategy_name, strategy_kwargs in load_attempts:
        try:
            print(f"[local-qwen] loading strategy={strategy_name}", flush=True)
            model_load_kwargs = {
                "config": cfg,
                "dtype": torch.bfloat16,
                "trust_remote_code": True,
                "local_files_only": True,
                "low_cpu_mem_usage": True,
                **strategy_kwargs,
            }
            if ATTN_IMPLEMENTATION:
                model_load_kwargs["attn_implementation"] = ATTN_IMPLEMENTATION
            model = Qwen3_5ForConditionalGeneration.from_pretrained(
                MODEL_DIR,
                **model_load_kwargs,
            )
            break
        except Exception as exc:
            last_error = exc
            print(f"[local-qwen] loading strategy={strategy_name} failed: {exc}", flush=True)
            torch.cuda.empty_cache()
    if model is None:
        raise RuntimeError(f"Failed to load model from {MODEL_DIR}: {last_error}")
    model.eval()
    max_new_tokens_cap = MAX_NEW_TOKENS if MAX_NEW_TOKENS > 0 else DEFAULT_TEXT_MAX_NEW_TOKENS_CAP
    _runtime.update(
        {
            "torch": torch,
            "tokenizer": tokenizer,
            "model": model,
            "context_window": context_window,
            "max_new_tokens_cap": max_new_tokens_cap,
            "gpu_index": primary_gpu,
            "visible_gpus": VISIBLE_GPUS,
            "process_visible_gpus": PROCESS_VISIBLE_GPUS,
            "device": device,
        }
    )
    return _runtime


if app is not None:
    @app.on_event("startup")
    def _startup() -> None:
        _load_runtime()


    @app.get("/health")
    def health() -> dict[str, Any]:
        runtime = _load_runtime()
        torch = runtime["torch"]
        gpu_index = int(runtime["gpu_index"])
        free_mem, total_mem = torch.cuda.mem_get_info(gpu_index)
        return {
            "ok": True,
            "model": MODEL_NAME,
            "model_dir": MODEL_DIR,
            "context_window": runtime["context_window"],
            "max_new_tokens_cap": runtime["max_new_tokens_cap"],
            "gpu_index": gpu_index,
            "visible_gpus": runtime["visible_gpus"],
            "gpu": torch.cuda.get_device_name(gpu_index),
            "gpu_free_gib": round(free_mem / 1024**3, 2),
            "gpu_total_gib": round(total_mem / 1024**3, 2),
        }


    @app.get("/v1/models")
    def list_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": MODEL_NAME,
                    "object": "model",
                    "owned_by": "local",
                }
            ],
        }


    @app.post("/v1/chat/completions")
    def chat_completions(request: ChatCompletionRequest) -> dict[str, Any]:
        runtime = _load_runtime()
        torch = runtime["torch"]
        tokenizer = runtime["tokenizer"]
        model = runtime["model"]
        device = runtime["device"]
        context_window = int(runtime["context_window"])
        configured_cap = int(runtime["max_new_tokens_cap"])
        json_mode = bool(request.response_format and request.response_format.get("type") == "json_object")
        temperature = 0.0 if request.temperature is None else float(request.temperature)
        if json_mode:
            temperature = 0.0
        do_sample = temperature > 0.0

        messages = []
        for message in request.messages:
            messages.append(
                {
                    "role": message.role,
                    "content": _normalize_content(message.content),
                }
            )

        prompt = _render_prompt(messages, request.response_format)

        with _lock, torch.inference_mode():
            inputs = tokenizer(prompt, return_tensors="pt").to(device)
            prompt_tokens = int(inputs["input_ids"].shape[-1])
            if context_window - prompt_tokens <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Prompt uses {prompt_tokens} tokens, which reaches or exceeds "
                        f"the model context window ({context_window})."
                    ),
                )
            max_new_tokens = _resolve_max_new_tokens(
                prompt_tokens=prompt_tokens,
                context_window=context_window,
                configured_cap=configured_cap,
                request_max_tokens=request.max_tokens,
                json_mode=json_mode,
            )
            print(
                (
                    f"[local-qwen] prompt_tokens={prompt_tokens} "
                    f"max_new_tokens={max_new_tokens} json_mode={json_mode} "
                    f"temperature={temperature} reasoning_mode={REASONING_MODE}"
                ),
                flush=True,
            )
            eos_token_ids: list[int] = []
            if tokenizer.eos_token_id is not None:
                eos_token_ids.append(int(tokenizer.eos_token_id))
            im_end_token_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
            if isinstance(im_end_token_id, int) and im_end_token_id >= 0 and im_end_token_id not in eos_token_ids:
                eos_token_ids.append(im_end_token_id)
            generate_kwargs = {
                **inputs,
                "max_new_tokens": max_new_tokens,
                "max_time": _resolve_max_time_seconds(json_mode=json_mode),
                "do_sample": do_sample,
                "use_cache": True,
                "pad_token_id": tokenizer.eos_token_id,
            }
            if eos_token_ids:
                generate_kwargs["eos_token_id"] = eos_token_ids if len(eos_token_ids) > 1 else eos_token_ids[0]
            if json_mode:
                generate_kwargs["repetition_penalty"] = 1.05
                generate_kwargs["renormalize_logits"] = True
            if do_sample:
                generate_kwargs["temperature"] = max(temperature, 1e-5)
            generated = model.generate(**generate_kwargs)
            generated_ids = generated[0][inputs["input_ids"].shape[-1] :]
            completion_tokens = int(generated_ids.shape[-1])
            decoded = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            content = _postprocess_content(decoded, json_mode=json_mode)
            preview = re.sub(r"\s+", " ", content[:160])
            print(
                f"[local-qwen] completion_tokens={completion_tokens} preview={preview!r}",
                flush=True,
            )
            torch.cuda.empty_cache()

        return {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


def main() -> None:
    if FastAPI is None:
        raise RuntimeError("Missing fastapi dependency. Install fastapi and uvicorn in the project environment first.")
    import uvicorn

    host = os.environ.get("LOCAL_QWEN35_C500_HOST", "127.0.0.1")
    port = int(os.environ.get("LOCAL_QWEN35_C500_PORT", "18081"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
