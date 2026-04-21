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
    # 查询侧默认用较快聊天模型；索引抽取亦走同一 default_chat_model（见 settings.yaml）
    GRAPHRAG_LLM_MODEL: str = "deepseek-v3.2"
    GRAPHRAG_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # True 且 USE_LOCAL_EMBEDDING=1 时，查询/索引写入的 embedding 指向本地 vLLM（须与向量维度一致；从 OpenAI 维度过来的库需重建索引）
    GRAPHRAG_USE_LOCAL_EMBEDDING_RUNTIME: bool = True
    GRAPHRAG_OUTPUT_DIR: str = "outputs/graphrag_kb"  # workspace root, layout: {dir}/{email}/{nb_id}/
    GRAPHRAG_CMD: str = ""                          # graphrag CLI path; auto-detected from PATH if empty
    GRAPHRAG_CHUNK_SIZE: int = 384                  # chars per chunk; also written to settings.yaml chunks.size
    GRAPHRAG_CHUNK_OVERLAP: int = 48
    # 写入 prompt，偏短输出可缩短 local_search 生成时间
    GRAPHRAG_RESPONSE_TYPE: str = "At most 4 bullet points; be concise."
    GRAPHRAG_COMMUNITY_LEVEL: int = 1               # 低于 2 通常更快，社区上下文更少
    GRAPHRAG_LOCAL_SEARCH_CONTEXT_MAX_TOKENS: int = 12000  # 低于 24000 可加快检索上下文组装与生成
    GRAPHRAG_SUBGRAPH_PRUNE_ENABLED: bool = True    # run LLM subgraph pruning after each query
    GRAPHRAG_SUBGRAPH_PRUNE_MODEL: str = "deepseek-v3.2"  # 仅单独裁剪路径使用
    GRAPHRAG_SUBGRAPH_PRUNE_MAX_EDGES_INPUT: int = 28   # 裁剪+Judge 合并路径：输入边数上限（越小越快）
    GRAPHRAG_SUBGRAPH_PRUNE_MAX_TOKENS: int = 512      # 单独裁剪 LLM 输出上限（若仍启用旧路径）
    # 裁剪与 Judge 合并为一次 LLM（graphrag_chat / graphrag_kb query）
    GRAPHRAG_PRUNE_JUDGE_MODEL: Optional[str] = None   # 为空则用 JUDGE_MODEL
    GRAPHRAG_PRUNE_JUDGE_MAX_TOKENS: int = 768        # 合并调用输出上限（含 analysis + judge JSON）
    GRAPHRAG_MAX_HIGHLIGHT_HINTS: int = 10          # max highlight_hints returned (0 = unlimited)
    # 子图实体名 → Wikidata 搜索 → 在 GraphRAG query/chat 答案末尾附加简短参考（需出网）
    GRAPHRAG_WIKIDATA_ENRICH_ENABLED: bool = True
    GRAPHRAG_WIKIDATA_LANG: str = "zh"              # wbsearchentities + 标签/描述优先语言
    GRAPHRAG_WIKIDATA_MAX_ENTITIES: int = 8         # 最多解析的不重复实体数
    # HTTPS 读超时（秒）；弱网可再加大或通过 HTTP 代理访问 wikidata.org
    GRAPHRAG_WIKIDATA_TIMEOUT_SEC: float = 45.0
    GRAPHRAG_WIKIDATA_CONNECT_TIMEOUT_SEC: float = 10.0
    # 对 Read timeout / 连接错误额外重试次数（每次递增短暂退避）
    GRAPHRAG_WIKIDATA_HTTP_RETRIES: int = 2
    GRAPHRAG_WIKIDATA_API_URL: str = "https://www.wikidata.org/w/api.php"

    # ── KGGen (optional triple extraction, disabled by default) ───────────────
    KGGEN_MODEL: str = "deepseek-v3.2"
    KGGEN_PER_CHUNK: bool = True                    # True = per-chunk calls; False = full-text single call
    KGGEN_LOG_CHUNK_INTERVAL: int = 10              # log every N chunks (0 = first/last only)

    # ── Judge (answer confidence scoring) ─────────────────────────────────────
    JUDGE_MODEL: str = "deepseek-v3.2"              # 单独 Judge；合并路径默认同此模型
    JUDGE_MAX_TOKENS: int = 256                     # 弱化：更短 judge 输出

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global configuration instance
settings = AppSettings()
