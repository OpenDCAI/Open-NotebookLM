"""
Pipeline configuration - shared context for all nodes.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool


@dataclass
class PipelineConfig:
    """Shared configuration passed to all pipeline nodes."""
    llm: BaseChatModel
    llm_with_tools: BaseChatModel
    tools: List[BaseTool]
    sql_rules: Dict[str, str] = field(default_factory=dict)
    verbose: bool = False
    use_query_improvements: bool = True

    # RAG / query-improvement submodules
    rag_enable_terminology: bool = True
    rag_enable_few_shot: bool = True
    rag_enable_query_rewrite: bool = False
    rag_enable_value_retriever: bool = False
    rag_enable_analysis_cot: bool = False
    rag_enable_vector_terminology: bool = False
    rag_enable_vector_few_shot: bool = False
    rag_enable_schema_relationship_hints: bool = True
    rag_enable_sql_pattern_hints: bool = True
    rag_enable_column_ranker: bool = False

    # Schema tool behaviors
    schema_enable_semantic_filtering: bool = False
    schema_enable_value_linking: bool = False

    # EGA controls
    ega_enabled: bool = False
    ega_rollout_mode: str = "dual_track"
    ega_optimization_target: str = "accuracy"
    ega_supported_types: str = "csv,excel,sqlite"
    ega_profile_sample_rows: int = 100
    ega_max_iterations: int = 3
    ega_lambda1: float = 0.3
    ega_lambda2: float = 0.5
