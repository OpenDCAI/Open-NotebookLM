"""
Application Settings

Model configurations are used as Pydantic defaults in schemas.py.
Frontend typically overrides these values, but they're kept for API compatibility.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class AppSettings(BaseSettings):
    """Application configuration with environment variable support."""

    # API Configuration
    DEFAULT_LLM_API_URL: str = "http://123.129.219.111:3000/v1/"

    # Model defaults (used in schemas.py, typically overridden by frontend)
    MODEL_GPT_4O: str = "deepseek-v3.2"
    PAPER2VIDEO_DEFAULT_MODEL: str = "deepseek-v3.2"

    # Paper2PPT models
    PAPER2PPT_DEFAULT_MODEL: str = "deepseek-v3.2"
    PAPER2PPT_OUTLINE_MODEL: str = "deepseek-v3.2"
    PAPER2PPT_CONTENT_MODEL: str = "deepseek-v3.2"
    PAPER2PPT_IMAGE_GEN_MODEL: str = "gemini-3-pro-image-preview"
    PAPER2PPT_VLM_MODEL: str = "qwen-vl-ocr-2025-11-20"
    PAPER2PPT_CHART_MODEL: str = "deepseek-v3.2"
    PAPER2PPT_DESC_MODEL: str = "deepseek-v3.2"
    PAPER2PPT_TECHNICAL_MODEL: str = "deepseek-v3.2"

    # Paper2Figure models
    PAPER2FIGURE_TEXT_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_IMAGE_MODEL: str = "gemini-3-pro-image-preview"
    PAPER2FIGURE_VLM_MODEL: str = "qwen-vl-ocr-2025-11-20"
    PAPER2FIGURE_CHART_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_DESC_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_REF_IMG_DESC_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_TECHNICAL_MODEL: str = "deepseek-v3.2"

    # Knowledge Base
    KB_CHAT_MODEL: str = "deepseek-v3.2"
    SQLBOT_OPENAI_API_KEY: Optional[str] = None
    SQLBOT_OPENAI_API_BASE: Optional[str] = None
    SQLBOT_OPENAI_MODEL: Optional[str] = None

    # Intelligent data extraction bridge
    SQLBOT_MODE: str = "embedded"
    SQLBOT_BASE_URL: str = "http://127.0.0.1:8000"
    SQLBOT_API_KEY: Optional[str] = None

    # Search API
    SERPER_API_KEY: Optional[str] = None

    # Supabase
    SUPABASE_URL: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # TTS
    USE_LOCAL_TTS: int = 0
    TTS_ENGINE: str = "qwen"
    TTS_IDLE_TIMEOUT: int = 300
    LOCAL_TTS_MODEL: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    LOCAL_TTS_PORT: int = 26211
    LOCAL_TTS_CMD: str = "vllm-omni"
    LOCAL_TTS_CUDA_VISIBLE_DEVICES: Optional[str] = None
    LOCAL_TTS_GPU_MEMORY_UTILIZATION: float = 0.3

    # Local Embedding
    USE_LOCAL_EMBEDDING: int = 1
    LOCAL_EMBEDDING_MODEL: str = "Octen/Octen-Embedding-0.6B"
    LOCAL_EMBEDDING_PORT: int = 26210
    LOCAL_EMBEDDING_CMD: str = "vllm"
    LOCAL_EMBEDDING_CUDA_VISIBLE_DEVICES: Optional[str] = None
    LOCAL_EMBEDDING_GPU_MEMORY_UTILIZATION: float = 0.3

    # ── GraphRAG ──────────────────────────────────────────────────────────────
    GRAPHRAG_LLM_MODEL: str = "gpt-5"              # chat model for entity/community extraction
    GRAPHRAG_EMBEDDING_MODEL: str = "text-embedding-3-small"
    GRAPHRAG_OUTPUT_DIR: str = "outputs/graphrag_kb"  # workspace root, layout: {dir}/{email}/{nb_id}/
    GRAPHRAG_CMD: str = ""                          # graphrag CLI path; auto-detected from PATH if empty
    GRAPHRAG_CHUNK_SIZE: int = 512                  # chars per chunk; also written to settings.yaml chunks.size
    GRAPHRAG_CHUNK_OVERLAP: int = 64
    GRAPHRAG_RESPONSE_TYPE: str = "Single Paragraph"  # passed to local/global_search response_type
    GRAPHRAG_SUBGRAPH_PRUNE_ENABLED: bool = True    # run LLM subgraph pruning after each query
    GRAPHRAG_SUBGRAPH_PRUNE_MAX_EDGES_INPUT: int = 80  # truncate input to pruner to this many edges
    GRAPHRAG_MAX_HIGHLIGHT_HINTS: int = 10          # max highlight_hints returned (0 = unlimited)

    # ── KGGen (optional triple extraction, disabled by default) ───────────────
    KGGEN_MODEL: str = "deepseek-v3.2"
    KGGEN_PER_CHUNK: bool = True                    # True = per-chunk calls; False = full-text single call
    KGGEN_LOG_CHUNK_INTERVAL: int = 10              # log every N chunks (0 = first/last only)

    # ── Judge (answer confidence scoring) ─────────────────────────────────────
    JUDGE_MODEL: str = "gpt-5"                      # returns judge_score [0,1] and judge_rationale

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global configuration instance
settings = AppSettings()
