"""Configuration helpers for PresentAgent."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _llm_api_base_default() -> str:
    if _env_flag("PRESENT_AGENT_USE_LOCAL_LLM"):
        return os.getenv("PRESENT_AGENT_LOCAL_LLM_API_BASE", "http://127.0.0.1:18081/v1")
    return os.getenv("PRESENT_AGENT_LLM_API_BASE", "http://123.129.219.111:3000/v1")


def _llm_model_default() -> str:
    if _env_flag("PRESENT_AGENT_USE_LOCAL_LLM"):
        return os.getenv(
            "PRESENT_AGENT_LOCAL_LLM_MODEL",
            "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
        )
    return os.getenv("PRESENT_AGENT_LLM_MODEL", "claude-sonnet-4-6")


def _llm_backend_default() -> str:
    return "local" if _env_flag("PRESENT_AGENT_USE_LOCAL_LLM") else "remote"


def _local_llm_api_base_default() -> str:
    return os.getenv("PRESENT_AGENT_LOCAL_LLM_API_BASE", "http://127.0.0.1:18081/v1")


def _local_llm_model_default() -> str:
    return os.getenv(
        "PRESENT_AGENT_LOCAL_LLM_MODEL",
        "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
    )


class Config(BaseModel):
    llm_backend: str = Field(default_factory=_llm_backend_default)
    model_profile: str = Field(
        default_factory=lambda: os.getenv("PRESENT_AGENT_MODEL_PROFILE", "general")
    )

    # LLM Configuration
    llm_api_key: str = Field(
        default_factory=lambda: os.getenv(
            "PRESENT_AGENT_LLM_API_KEY",
            "sk-h9C1dTnJqjtRyvlcsU1IViCH99X15jnRrH1NVWqzUnjDhvzv",
        )
    )
    llm_api_base: str = Field(
        default_factory=_llm_api_base_default
    )
    llm_model: str = Field(
        default_factory=_llm_model_default
    )
    local_llm_api_base: str = Field(
        default_factory=_local_llm_api_base_default
    )
    local_llm_model: str = Field(
        default_factory=_local_llm_model_default
    )
    llm_max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_LLM_MAX_TOKENS", "0"))
    )

    # VLM Configuration
    vlm_api_key: str = Field(
        default_factory=lambda: os.getenv(
            "PRESENT_AGENT_VLM_API_KEY",
            "sk-h9C1dTnJqjtRyvlcsU1IViCH99X15jnRrH1NVWqzUnjDhvzv",
        )
    )
    vlm_api_base: str = Field(
        default_factory=lambda: os.getenv("PRESENT_AGENT_VLM_API_BASE", "http://123.129.219.111:3000/v1")
    )
    vlm_model: str = Field(
        default_factory=lambda: os.getenv("PRESENT_AGENT_VLM_MODEL", "qwen3-vl-235b-a22b-instruct")
    )

    # Image Generation Configuration
    image_api_key: str = Field(
        default_factory=lambda: os.getenv(
            "PRESENT_AGENT_IMAGE_API_KEY",
            "sk-lfyeC3JVAh83BdWFpof7BBeJTyjCoIfg7bMSYeqyCHD8D02t",
        )
    )
    image_api_base: str = Field(
        default_factory=lambda: os.getenv("PRESENT_AGENT_IMAGE_API_BASE", "http://123.129.219.111:3000/v1")
    )
    image_generation_model: str = Field(
        default_factory=lambda: os.getenv(
            "PRESENT_AGENT_IMAGE_MODEL",
            "gemini-3.1-flash-image-preview",
        )
    )

    max_iterations: int = Field(default_factory=lambda: int(os.getenv("PRESENT_AGENT_MAX_ITERATIONS", "3")))
    planner_max_workers: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_PLANNER_MAX_WORKERS", "4"))
    )
    coder_max_workers: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_CODER_MAX_WORKERS", "1"))
    )
    vlm_max_workers: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_VLM_MAX_WORKERS", "4"))
    )
    longdoc_chunk_char_limit: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_LONGDOC_CHUNK_CHAR_LIMIT", "6000"))
    )
    longdoc_overlap_chars: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_LONGDOC_OVERLAP_CHARS", "400"))
    )
    output_dir: str = Field(default_factory=lambda: os.getenv("PRESENT_AGENT_OUTPUT_DIR", "outputs"))
    mineru_api_token: str = Field(
        default_factory=lambda: os.getenv(
            "MINERU_API_TOKEN",
            "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIyNDEwMDAyNiIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3MzgxODY1OSwiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiIiwib3BlbklkIjpudWxsLCJ1dWlkIjoiZWE0MDE3OWYtYzkwNS00MTA2LThjNDYtOTMyYWU2Y2ZiMTc5IiwiZW1haWwiOiIiLCJleHAiOjE4MDUzNTQ2NTl9.n4HG5FzsV2m-OYWHT16pN7a5h6Qi51LBeafgzy34I0_rVJRdDxtIRzF-Lfvec-izL3owqU2Ntjc4UW_UmuRmQA",
        )
    )
    mineru_api_base: str = Field(default_factory=lambda: os.getenv("MINERU_API_BASE", "https://mineru.net/api/v4"))
    mineru_model_version: str = Field(default_factory=lambda: os.getenv("MINERU_MODEL_VERSION", "vlm"))
    mineru_poll_interval: float = Field(
        default_factory=lambda: float(os.getenv("MINERU_POLL_INTERVAL", "5"))
    )
    mineru_parse_timeout: int = Field(default_factory=lambda: int(os.getenv("MINERU_PARSE_TIMEOUT", "1800")))

    # Language and Complexity Configuration
    language_mode: str = Field(
        default_factory=lambda: os.getenv("PRESENT_AGENT_LANGUAGE_MODE", "english")
    )
    complexity_level: str = Field(
        default_factory=lambda: os.getenv("PRESENT_AGENT_COMPLEXITY_LEVEL", "balanced")
    )
    max_slides: int = Field(
        default_factory=lambda: int(os.getenv("PRESENT_AGENT_MAX_SLIDES", "0"))
    )
