"""
Query understanding node - optional query rewrite / value retrieval / analysis plan.

Default behavior is "minimal": no extra LLM calls, just pass the original question
through as rewritten_query. This keeps the agent stable and easier to evaluate.
"""
import logging
from typing import Dict, Any

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.agents.pipeline.nodes.ega_prepare import should_run_ega_prepare

logger = logging.getLogger(__name__)


def query_understanding_node(state: AgentState, config: PipelineConfig) -> dict:
    """Optional improvements before retrieval/SQL generation."""

    question = state["question"]
    datasource_id = state.get("datasource_id")
    conversation_context = state.get("conversation_context")

    update: Dict[str, Any] = {
        "rewritten_query": question,
        "query_thinking": None,
        "value_linking_results": None,
        "analysis_plan": None,
    }
    ega_lite_mode = should_run_ega_prepare(state, config) == "ega_prepare"

    effective_question = question
    if conversation_context:
        prev_q = conversation_context.get("previous_question", "")
        prev_sql = conversation_context.get("previous_sql", "")
        if prev_q and prev_sql:
            effective_question = (
                f"[上一轮查询]\n问题: {prev_q}\n"
                f"SQL: {prev_sql}\n"
                f"[当前问题] {question}"
            )

    if config.rag_enable_query_rewrite:
        try:
            from fastapi_app.modules.rag.query_rewrite import query_rewrite_service, RewriteResult

            query_rewrite_service.set_llm(config.llm)
            rewrite_result = query_rewrite_service.rewrite_with_thinking(
                effective_question, datasource_id=datasource_id, llm=config.llm
            )
            if isinstance(rewrite_result, RewriteResult):
                update["rewritten_query"] = rewrite_result.rewritten_query or question
                update["query_thinking"] = rewrite_result.thinking
        except Exception as e:
            logger.warning(f"Query rewrite failed (fallback to original question): {e}")
            update["rewritten_query"] = question

    # EGA lane keeps understanding lightweight: no value-linking/analysis here.
    if config.rag_enable_value_retriever and not ega_lite_mode:
        try:
            from fastapi_app.modules.rag.value_retriever import value_retriever

            value_linking = value_retriever.retrieve(
                datasource_id=datasource_id,
                query=update["rewritten_query"] or question,
                top_k=10,
                include_scores=True,
            )
            if value_linking:
                update["value_linking_results"] = value_linking
        except Exception as e:
            logger.warning(f"Value retriever failed: {e}")

    if config.rag_enable_analysis_cot and not ega_lite_mode:
        analysis_keywords = ("分析", "趋势", "统计", "汇总", "对比", "分布", "总结", "洞察")
        if any(k in (question or "") for k in analysis_keywords):
            try:
                from fastapi_app.modules.rag.analysis_cot import analysis_cot_service, AnalysisCoTResult
                from fastapi_app.agents.tools.datasource_manager import get_datasource_handler

                ds = get_datasource_handler(datasource_id)
                schema_text = ""
                if ds and hasattr(ds, "get_tables"):
                    parts = []
                    for t in (ds.get_tables() or [])[:15]:
                        name = getattr(t, "name", str(t))
                        parts.append(f"table {name}")
                        if hasattr(ds, "get_table_schema"):
                            schema = ds.get_table_schema(name)
                            if schema and hasattr(schema, "columns"):
                                for c in (schema.columns or [])[:20]:
                                    cn = getattr(c, "name", str(c))
                                    parts.append(f"  col {cn}")
                    schema_text = "\n".join(parts)[:4000]

                if schema_text:
                    analysis_cot_service.set_llm(config.llm)
                    cot_result = analysis_cot_service.plan_analysis(
                        question, schema_text, llm=config.llm
                    )
                    if isinstance(cot_result, AnalysisCoTResult) and cot_result.steps:
                        update["analysis_plan"] = cot_result.to_dict()
            except Exception as e:
                logger.warning(f"Analysis CoT failed: {e}")

    return update
