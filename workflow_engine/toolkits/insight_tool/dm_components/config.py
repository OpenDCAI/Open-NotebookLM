# config.py
"""
Configuration file for the Insight Multi-Agent Framework.

This file contains all configurable parameters for:
- LLM settings
- Data processing
- Output control
- Logging
"""
import os

# =============================================================================
# LLM 基础配置
# =============================================================================
MODEL_NAME = "gpt-4o"
TEMPERATURE = 0.0
N_RETRIES = 4

# =============================================================================
# 分析流程配置
# =============================================================================
BRANCH_DEPTH = 2  # 单源分析的深度探索层数
MAX_QUESTIONS = 2  # 每次迭代的最大问题数

# =============================================================================
# 输出目录配置
# =============================================================================
BASE_SAVEDIR = "/mnt/DataFlow/qry/DataCrossBench-Exp-Results/DataCross"

# =============================================================================
# 背景信息处理配置 (NEW)
# =============================================================================
# 文本文件超过此字符数阈值时，将自动进行摘要提取
TEXT_SUMMARY_THRESHOLD = 2000

# 图片分类使用的模型 (需要支持视觉能力)
IMAGE_CLASSIFICATION_MODEL = "gpt-4o"

# =============================================================================
# 输出控制配置 (NEW)
# =============================================================================
# 默认输出模式: "concise" (简洁模式) 或 "detailed" (详细模式)
# - concise: 精简输出，适合快速查看结果
# - detailed: 完整输出，包含detailed_appendix，适合benchmark对比
DEFAULT_OUTPUT_MODE = "concise"

# =============================================================================
# 评分机制配置 (NEW)
# =============================================================================
# 混合评分权重
SCORING_WEIGHTS = {
    "objective": 0.4,   # 客观指标 (数据质量、丰富度、时间维度)
    "semantic": 0.3,    # 语义相关性 (关键词匹配)
    "llm": 0.3          # LLM主观评分
}

# 优先级阈值
PRIORITY_THRESHOLDS = {
    "high": 7.0,    # 分数 >= 7 为 High 优先级
    "medium": 4.0   # 分数 >= 4 为 Medium 优先级, 否则为 Low
}

# =============================================================================
# 批注流程配置 (NEW)
# =============================================================================
# 批注输入限制 (防止token溢出)
ANNOTATION_MAX_SUMMARY_LENGTH = 1000
ANNOTATION_MAX_INSIGHTS_COUNT = 3
ANNOTATION_N_RETRIES = 2

# =============================================================================
# LangGraph 相关
# =============================================================================
from langgraph.graph import StateGraph, END

# =============================================================================
# 类型提示
# =============================================================================
from typing import List, Dict, Any, TypedDict, Optional

# =============================================================================
# 日志配置 - 使用 Open-NotebookLM 的 logger
# =============================================================================
import sys
import os
# 添加 workflow_engine 到路径以便导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))
from workflow_engine.logger import get_logger
logger = get_logger(__name__)


# =============================================================================
# 辅助函数
# =============================================================================
def get_config_dict() -> Dict[str, Any]:
    """
    获取所有配置项的字典形式，便于传递和记录。
    
    Returns:
        包含所有配置项的字典
    """
    return {
        "model_name": MODEL_NAME,
        "temperature": TEMPERATURE,
        "n_retries": N_RETRIES,
        "branch_depth": BRANCH_DEPTH,
        "max_questions": MAX_QUESTIONS,
        "base_savedir": BASE_SAVEDIR,
        "text_summary_threshold": TEXT_SUMMARY_THRESHOLD,
        "image_classification_model": IMAGE_CLASSIFICATION_MODEL,
        "default_output_mode": DEFAULT_OUTPUT_MODE,
        "scoring_weights": SCORING_WEIGHTS,
        "priority_thresholds": PRIORITY_THRESHOLDS,
        "annotation_config": {
            "max_summary_length": ANNOTATION_MAX_SUMMARY_LENGTH,
            "max_insights_count": ANNOTATION_MAX_INSIGHTS_COUNT,
            "n_retries": ANNOTATION_N_RETRIES
        }
    }