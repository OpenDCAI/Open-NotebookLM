"""
应用配置管理
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置"""

    # 基础配置
    APP_NAME: str = "LangGraph SQLBot"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool | str = Field(default=False, env="DEBUG")

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = Field(default=True, env="RELOAD")

    # LLM配置（支持多种模型类型）
    LLM_TYPE: str = Field(default="openai", env="LLM_TYPE")  # openai, ollama, tongyi, azure, zhipu, deepseek
    LLM_TEMPERATURE: float = Field(default=0.0, env="LLM_TEMPERATURE")
    
    # OpenAI配置（也用于OpenAI兼容的API）
    # Also accept DF_* envs (some deployments provide OpenAI-compatible endpoints via these names).
    OPENAI_API_KEY: str = Field(default="", env=("OPENAI_API_KEY", "DF_API_KEY"))
    OPENAI_MODEL: str = Field(default="gpt-4", env=("OPENAI_MODEL", "DF_MODEL"))
    OPENAI_API_BASE: Optional[str] = Field(default=None, env=("OPENAI_API_BASE", "DF_API_URL"))
    
    # Ollama配置（本地模型）
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")
    OLLAMA_MODEL: str = Field(default="llama3", env="OLLAMA_MODEL")

    # 数据库配置
    DATABASE_URL: str = Field(
        default="sqlite:///./test.db",
        env="DATABASE_URL"
    )

    # CSV配置
    CSV_UPLOAD_DIR: Path = Path("./uploads/csv")
    CSV_MAX_SIZE: int = 100 * 1024 * 1024  # 100MB
    CSV_PREVIEW_ROWS: int = 10

    # 认证配置
    SECRET_KEY: str = Field(default="embedded-sqlbot-secret", env="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FILE: Optional[Path] = None

    # CORS 配置 (Phase 4.3: 白名单化)
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:8000",
        env="CORS_ORIGINS",
        description="Comma-separated allowed CORS origins. Set to '*' for development."
    )

    # Optional API-key protection for external integrations (e.g., Open-NotebookLM adapter calls).
    # When unset/empty, all requests are allowed (backwards compatible).
    SQLBOT_API_KEY: Optional[str] = Field(
        default=None,
        env="SQLBOT_API_KEY",
        description="If set, clients must send header X-SQLBOT-KEY matching this value."
    )

    # LangGraph配置
    LANGGRAPH_VERBOSE: bool = Field(default=False, env="LANGGRAPH_VERBOSE")
    AGENT_RECURSION_LIMIT: int = Field(default=120, env="AGENT_RECURSION_LIMIT")
    MAX_ITERATIONS: int = 10
    # 改进开关：Query 改写 + Value Linking + 分析 CoT（检验时可设为 False 做「未改」对比）
    USE_QUERY_IMPROVEMENTS: bool = Field(default=True, env="USE_QUERY_IMPROVEMENTS")
    # 追问开关：歧义时是否弹出追问（设为 False 则直接尝试执行，不打断用户）
    USE_CLARIFICATION: bool = Field(default=False, env="USE_CLARIFICATION")

    # RAG / Query Improvements toggles (default: minimal & stable)
    # Keep USE_QUERY_IMPROVEMENTS controlling the graph structure; flags below
    # decide whether data-dependent / expensive submodules actually run.
    RAG_ENABLE_TERMINOLOGY: bool = Field(default=True, env="RAG_ENABLE_TERMINOLOGY")
    RAG_ENABLE_FEW_SHOT: bool = Field(default=True, env="RAG_ENABLE_FEW_SHOT")
    RAG_ENABLE_QUERY_REWRITE: bool = Field(default=False, env="RAG_ENABLE_QUERY_REWRITE")
    RAG_ENABLE_VALUE_RETRIEVER: bool = Field(default=False, env="RAG_ENABLE_VALUE_RETRIEVER")
    RAG_ENABLE_ANALYSIS_COT: bool = Field(default=False, env="RAG_ENABLE_ANALYSIS_COT")

    # Vector-store dependent retrievals (when False, degrade to lexical/exact-match).
    RAG_ENABLE_VECTOR_TERMINOLOGY: bool = Field(default=False, env="RAG_ENABLE_VECTOR_TERMINOLOGY")
    RAG_ENABLE_VECTOR_FEW_SHOT: bool = Field(default=False, env="RAG_ENABLE_VECTOR_FEW_SHOT")

    # Prompt hint injections (cheap heuristics; can be turned off if noisy).
    RAG_ENABLE_SCHEMA_RELATIONSHIP_HINTS: bool = Field(default=True, env="RAG_ENABLE_SCHEMA_RELATIONSHIP_HINTS")
    RAG_ENABLE_SQL_PATTERN_HINTS: bool = Field(default=True, env="RAG_ENABLE_SQL_PATTERN_HINTS")
    RAG_ENABLE_COLUMN_RANKER: bool = Field(default=False, env="RAG_ENABLE_COLUMN_RANKER")

    # Schema tool behaviors (often empty without bootstrap pipeline).
    SCHEMA_ENABLE_SEMANTIC_FILTERING: bool = Field(default=False, env="SCHEMA_ENABLE_SEMANTIC_FILTERING")
    SCHEMA_ENABLE_VALUE_LINKING: bool = Field(default=False, env="SCHEMA_ENABLE_VALUE_LINKING")

    # Cross-source (UnifiedQueryEngine) safety/performance knobs.
    # Applies to SQL-like datasources imported into DuckDB via SELECT * ... LIMIT max_rows.
    # Set to 0 (or negative) to disable truncation (benchmark/accuracy mode).
    UNIFIED_ENGINE_MAX_IMPORT_ROWS: int = Field(default=100_000, env="UNIFIED_ENGINE_MAX_IMPORT_ROWS")

    # Learning loop controls (few-shot learning, relationship learning, routing feedback).
    # For benchmark/eval, set SQLBOT_FREEZE_LEARNING=1 to keep runs reproducible.
    LEARNING_ENABLE: bool = Field(default=True, env="LEARNING_ENABLE")

    # EGA (Execution-Grounded Alignment) toggles and budgets.
    EGA_ENABLED: bool = Field(default=False, env="EGA_ENABLED")
    EGA_ROLLOUT_MODE: str = Field(default="dual_track", env="EGA_ROLLOUT_MODE")
    EGA_OPTIMIZATION_TARGET: str = Field(default="accuracy", env="EGA_OPTIMIZATION_TARGET")
    EGA_SUPPORTED_TYPES: str = Field(default="csv,excel,sqlite", env="EGA_SUPPORTED_TYPES")
    EGA_PROFILE_SAMPLE_ROWS: int = Field(default=100, env="EGA_PROFILE_SAMPLE_ROWS")
    EGA_MAX_ITERATIONS: int = Field(default=3, env="EGA_MAX_ITERATIONS")
    EGA_LAMBDA1: float = Field(default=0.3, env="EGA_LAMBDA1")
    EGA_LAMBDA2: float = Field(default=0.5, env="EGA_LAMBDA2")

    def __init__(self, **data):
        super().__init__(**data)
        # Embedded mode should tolerate broad parent-process envs such as
        # DEBUG=release coming from unrelated launchers.
        if isinstance(self.DEBUG, str):
            debug_value = self.DEBUG.strip().lower()
            self.DEBUG = debug_value in {"1", "true", "yes", "on", "debug"}

        # Allow DF_* envs to override OpenAI-compatible settings at runtime.
        # This makes it possible to switch providers without editing an existing .env
        # that already defines OPENAI_* variables.
        def _strip_wrappers(value: str) -> str:
            v = (value or "").strip()
            # Users sometimes paste keys like "<sk-...>".
            if len(v) >= 2 and v.startswith("<") and v.endswith(">"):
                v = v[1:-1].strip()
            return v

        df_key = os.getenv("DF_API_KEY")
        if df_key and df_key.strip():
            self.OPENAI_API_KEY = _strip_wrappers(df_key)

        df_url = os.getenv("DF_API_URL")
        if df_url and df_url.strip():
            self.OPENAI_API_BASE = _strip_wrappers(df_url)

        df_model = os.getenv("DF_MODEL")
        if df_model and df_model.strip():
            self.OPENAI_MODEL = _strip_wrappers(df_model)

        freeze = os.getenv("SQLBOT_FREEZE_LEARNING", "").strip().lower()
        if freeze in {"1", "true", "yes", "on"}:
            self.LEARNING_ENABLE = False

        # Normalize OpenAI-compatible base_url:
        # - If user provides a full endpoint like ".../v1/chat/completions", trim to ".../v1"
        # - If user provides ".../v1/anything", trim to ".../v1"
        base = (self.OPENAI_API_BASE or "").strip()
        if base:
            base = base.rstrip("/")
            if base.endswith("/chat/completions"):
                base = base[: -len("/chat/completions")]
            if "/v1/" in base:
                base = base.split("/v1/")[0] + "/v1"
            self.OPENAI_API_BASE = base
        # 创建上传目录
        self.CSV_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局配置实例
settings = Settings()
