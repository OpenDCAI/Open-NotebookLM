"""
Application Settings - Three-tier Configuration System

This module provides a centralized configuration system with three layers:
1. Base Models: Fundamental model name definitions
2. Workflow-level: Default models for each workflow
3. Role-level: Fine-grained model assignments for specific roles

All settings can be overridden via environment variables in .env file.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class AppSettings(BaseSettings):
    """
    Application configuration using three-tier architecture:
    Base Models + Workflow-level + Role-level

    Environment variables can override any setting by using the same name.
    Example: export PAPER2PPT_DEFAULT_MODEL=deepseek-v3.2
    """

    # ============================================
    # Layer 1: Base Model Definitions
    # ============================================
    # 默认 LLM（文本模型）统一为 deepseek-v3.2，可通过环境变量覆盖
    DEFAULT_LLM_MODEL: str = "deepseek-v3.2"
    MODEL_GPT_4O: str = "deepseek-v3.2"
    MODEL_GPT_5_1: str = "deepseek-v3.2"
    MODEL_CLAUDE_HAIKU: str = "claude-haiku-4-5-20251001"
    MODEL_GEMINI_PRO_IMAGE: str = "gemini-3-pro-image-preview"
    MODEL_GEMINI_FLASH_IMAGE: str = "gemini-2.5-flash-image"
    MODEL_GEMINI_FLASH: str = "gemini-2.5-flash"
    MODEL_QWEN_VL_OCR: str = "qwen-vl-ocr-2025-11-20"

    # API Configuration
    DEFAULT_LLM_API_URL: str = "http://123.129.219.111:3000/v1/"

    # ============================================
    # Layer 2: Workflow-level Default Models
    # ============================================
    # Paper2PPT Workflow
    PAPER2PPT_DEFAULT_MODEL: str = "deepseek-v3.2"
    PAPER2PPT_DEFAULT_IMAGE_MODEL: str = "gemini-3-pro-image-preview"

    # PDF2PPT Workflow
    PDF2PPT_DEFAULT_MODEL: str = "deepseek-v3.2"
    PDF2PPT_DEFAULT_IMAGE_MODEL: str = "gemini-2.5-flash-image"

    # Paper2Figure Workflow
    PAPER2FIGURE_DEFAULT_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_DEFAULT_IMAGE_MODEL: str = "gemini-3-pro-image-preview"

    # Paper2Video Workflow
    PAPER2VIDEO_DEFAULT_MODEL: str = "deepseek-v3.2"

    # Paper2Drawio Workflow
    PAPER2DRAWIO_DEFAULT_MODEL: str = "deepseek-v3.2"
    PAPER2DRAWIO_VLM_MODEL: str = "deepseek-v3.2"
    PAPER2DRAWIO_ENABLE_VLM_VALIDATION: bool = False

    # Knowledge Base
    KB_EMBEDDING_MODEL: str = "gemini-2.5-flash"
    KB_CHAT_MODEL: str = "deepseek-v3.2"

    # Fast Research (web search for 引入)
    SERPER_API_KEY: Optional[str] = None

    # ============================================
    # Layer 3: Role-level Model Configuration
    # ============================================
    # Paper2PPT role-specific models
    PAPER2PPT_OUTLINE_MODEL: str = "deepseek-v3.2"           # Outline generation
    PAPER2PPT_CONTENT_MODEL: str = "deepseek-v3.2"           # Content generation
    PAPER2PPT_IMAGE_GEN_MODEL: str = "gemini-3-pro-image-preview"  # Image generation
    PAPER2PPT_VLM_MODEL: str = "qwen-vl-ocr-2025-11-20"  # VLM vision understanding
    PAPER2PPT_CHART_MODEL: str = "deepseek-v3.2"              # Chart generation
    PAPER2PPT_DESC_MODEL: str = "deepseek-v3.2"              # Figure description
    PAPER2PPT_TECHNICAL_MODEL: str = "deepseek-v3.2"  # Technical details

    # Paper2Figure role-specific models
    PAPER2FIGURE_TEXT_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_IMAGE_MODEL: str = "gemini-3-pro-image-preview"
    PAPER2FIGURE_VLM_MODEL: str = "qwen-vl-ocr-2025-11-20"
    PAPER2FIGURE_CHART_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_DESC_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_REF_IMG_DESC_MODEL: str = "deepseek-v3.2"
    PAPER2FIGURE_TECHNICAL_MODEL: str = "deepseek-v3.2"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global configuration instance
settings = AppSettings()
