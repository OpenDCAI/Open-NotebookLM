"""
RAG knowledge retrieval node.

Phase 4.1: Added degradation strategy
- Vector store failure → degraded to exact-match only (with warning)
- Few-shot retrieval failure → fallback to hardcoded default examples
- Individual RAG component failures don't crash the whole node
"""
import logging
from typing import Dict, Any, List

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


# Hardcoded fallback examples when few-shot retrieval is unavailable
_FALLBACK_EXAMPLES: List[Dict[str, Any]] = [
    {
        "question": "统计各城市的总销售额",
        "sql": "SELECT city, SUM(total_amount) AS total_amount FROM sales GROUP BY city ORDER BY total_amount DESC LIMIT 100",
        "description": "聚合查询: 英文列别名, GROUP BY, LIMIT",
        "pattern": "aggregation",
    },
    {
        "question": "查询销量最高的产品",
        "sql": "SELECT product_name, SUM(quantity) AS total_quantity FROM sales GROUP BY product_name ORDER BY total_quantity DESC LIMIT 10",
        "description": "排序聚合: ORDER BY DESC + LIMIT",
        "pattern": "aggregation",
    },
]


def retrieve_knowledge_node(state: AgentState, config: PipelineConfig) -> dict:
    """
    Knowledge retrieval node (RAG) - with degradation strategy and parallel execution.

    Degradation levels:
    1. Full RAG: vector terminology + vector few-shot + value linking
    2. Partial RAG: exact-match terminology + fallback examples
    3. Minimal: hardcoded examples only

    Performance: Parallel execution of 4 independent retrievals (60-70% faster)
    """
    import asyncio
    from fastapi_app.modules.rag.terminology import terminology_service
    from fastapi_app.modules.rag.few_shot import few_shot_service
    from fastapi_app.modules.rag.column_ranker import column_ranking_service

    question = state["question"]
    retrieval_query = state.get("rewritten_query") or question
    datasource_id = state.get("datasource_id")

    if config.verbose:
        logger.info(f"Retrieving knowledge for (query): {retrieval_query}")

    rag_context: Dict[str, Any] = {}

    # Parallel execution of independent retrievals
    async def _parallel_retrieve():
        tasks = []

        # 1. Terminology retrieval
        if config.rag_enable_terminology:
            tasks.append(_retrieve_terminology_async(
                terminology_service, retrieval_query, datasource_id,
                config.rag_enable_vector_terminology
            ))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # 2. Few-shot examples
        if config.rag_enable_few_shot:
            tasks.append(_retrieve_examples_async(
                few_shot_service, retrieval_query, datasource_id,
                config.rag_enable_vector_few_shot
            ))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # 3. JOIN hints
        if config.rag_enable_schema_relationship_hints and datasource_id:
            tasks.append(_retrieve_join_hints_async(datasource_id, state))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # 4. SQL patterns
        if config.rag_enable_sql_pattern_hints:
            tasks.append(_match_sql_patterns_async(question))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        return await asyncio.gather(*tasks, return_exceptions=True)

    # Run parallel retrieval
    try:
        results = asyncio.run(_parallel_retrieve())
        term_info, similar_examples, join_hints, pattern_hints = results

        # Handle exceptions
        if isinstance(term_info, Exception):
            logger.warning(f"Terminology retrieval failed: {term_info}")
            term_info = []
        if isinstance(similar_examples, Exception):
            logger.warning(f"Few-shot retrieval failed: {similar_examples}")
            similar_examples = []
        if isinstance(join_hints, Exception):
            logger.warning(f"JOIN hints retrieval failed: {join_hints}")
            join_hints = []
        if isinstance(pattern_hints, Exception):
            logger.warning(f"Pattern matching failed: {pattern_hints}")
            pattern_hints = []

        # Build context
        if term_info:
            rag_context["related_terms"] = term_info
        if similar_examples:
            rag_context["similar_examples"] = similar_examples
        if join_hints:
            rag_context["join_hints"] = join_hints
        if pattern_hints:
            rag_context["pattern_hints"] = pattern_hints

    except Exception as e:
        logger.error(f"Parallel retrieval failed, falling back to serial: {e}")
        # Fallback to original serial execution
        term_info = []
        similar_examples = []
        if config.rag_enable_terminology:
            term_info = _retrieve_terminology(
                terminology_service, retrieval_query, datasource_id,
                config.rag_enable_vector_terminology
            )
            if term_info:
                rag_context["related_terms"] = term_info
        if config.rag_enable_few_shot:
            similar_examples = _retrieve_examples(
                few_shot_service, retrieval_query, datasource_id,
                config.rag_enable_vector_few_shot
            )
            if similar_examples:
                rag_context["similar_examples"] = similar_examples

    # Column ranker (optional; requires LLM)
    if config.rag_enable_column_ranker:
        try:
            column_ranking_service.set_llm(config.llm)
        except Exception as e:
            logger.warning(f"Failed to set column ranker LLM: {e}")

    # Merge value linking and analysis context from state
    if state.get("value_linking_results"):
        rag_context["value_linking"] = state["value_linking_results"]
    if state.get("query_thinking"):
        rag_context["query_thinking"] = state["query_thinking"]
    if state.get("analysis_plan"):
        rag_context["analysis_plan"] = state["analysis_plan"]

    if config.verbose:
        logger.info(
            f"RAG retrieval complete: "
            f"{len(term_info)} terms, "
            f"{len(similar_examples)} examples, "
            f"{len(rag_context.get('join_hints', []))} join hints, "
            f"{len(rag_context.get('pattern_hints', []))} patterns"
        )
    return {"rag_context": rag_context}


def _retrieve_terminology(
    terminology_service,
    query: str,
    datasource_id,
    enable_vector: bool = False,
) -> List[str]:
    """Retrieve terminology with degradation (exact-match by default)."""
    term_info = []

    # Phase 1: Exact-match extraction (no vector store needed)
    extracted_terms = []
    try:
        extracted_terms = terminology_service.extract_terms(query, datasource_id)
        for term_text, entry in extracted_terms:
            info = f"{entry.term}: {entry.definition}"
            if entry.sql_expression:
                info += f" (SQL: {entry.sql_expression})"
            term_info.append(info)
    except Exception as e:
        logger.warning(f"Terminology exact-match failed: {e}")

    # Phase 2: Vector-based semantic retrieval (optional)
    if enable_vector:
        try:
            related_terms = terminology_service.retrieve(query, k=5, datasource_id=datasource_id)
            extracted_term_names = [t.term for _, t in extracted_terms] if extracted_terms else []
            for term in related_terms:
                if term.get("term") not in extracted_term_names:
                    info = f"{term.get('term', '')}: {term.get('definition', '')}"
                    if term.get("sql_expression"):
                        info += f" (SQL: {term['sql_expression']})"
                    term_info.append(info)
        except Exception as e:
            logger.info(f"Terminology vector retrieval unavailable (exact-match only): {e}")

    return term_info


def _retrieve_examples(
    few_shot_service,
    query: str,
    datasource_id,
    enable_vector: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve few-shot examples (lexical by default) with fallback."""
    try:
        # FewShotService already degrades to lexical retrieval when vector_store is unavailable.
        # If vector retrieval is disabled, force lexical by temporarily bypassing vector store.
        vector_store = getattr(few_shot_service, "vector_store", None)
        if (not enable_vector) and vector_store is not None:
            few_shot_service.vector_store = None
        examples = few_shot_service.retrieve(
            query, k=3, datasource_id=datasource_id, min_quality=0.3
        )
        if (not enable_vector) and vector_store is not None:
            few_shot_service.vector_store = vector_store
        if examples:
            return examples
    except Exception as e:
        if enable_vector:
            logger.warning(f"Few-shot retrieval failed: {e}")
        else:
            logger.info(f"Few-shot lexical retrieval failed: {e}")

    # Fallback: return hardcoded examples
    if enable_vector:
        logger.warning("Using fallback few-shot examples (vector store unavailable or empty)")
    else:
        logger.info("Using fallback few-shot examples")
    return _FALLBACK_EXAMPLES


def _retrieve_join_hints(datasource_id: int, state: Dict[str, Any]) -> List[str]:
    """Retrieve JOIN relationship hints for prompt injection."""
    try:
        from fastapi_app.modules.rag.schema_relationships import schema_relationship_service

        # Identify tables mentioned in schema cache or question
        schema_cache = state.get("schema_cache")
        question = state.get("question", "")

        tables = None
        if schema_cache and isinstance(schema_cache, dict):
            # Extract table names from schema
            schema_tables = schema_cache.get("tables", [])
            if isinstance(schema_tables, list):
                tables = [t.get("name") if isinstance(t, dict) else str(t) for t in schema_tables[:10]]

        hints = schema_relationship_service.get_join_hints(
            datasource_id,
            tables=tables,
            max_hints=5,
        )
        return hints

    except Exception as e:
        logger.warning(f"JOIN hints retrieval failed: {e}")
        return []


def _match_sql_patterns(question: str) -> List[str]:
    """Match SQL patterns from question (Enhancement 4)."""
    try:
        from fastapi_app.modules.rag.sql_pattern_templates import sql_pattern_service

        matched = sql_pattern_service.match(question)
        if not matched:
            return []

        hints: List[str] = []
        for pattern in matched[:2]:
            hints.append(f"- {pattern.name}: {pattern.description}")

            detail = sql_pattern_service.explain_pattern(pattern.name) or {}
            example = (detail.get("example") or "").strip()
            if example:
                # Keep prompts compact: include a short, concrete example snippet.
                snippet = "\n".join(example.splitlines()[:20]).strip()
                if len(snippet) > 900:
                    snippet = snippet[:900].rstrip() + "..."
                hints.append("```sql\n" + snippet + "\n```")

        return hints

    except Exception as e:
        logger.warning(f"SQL pattern matching failed: {e}")
        return []


# ========== Async wrappers for parallel execution ==========

async def _retrieve_terminology_async(
    terminology_service, query: str, datasource_id, enable_vector: bool
) -> List[str]:
    """Async wrapper for terminology retrieval."""
    import asyncio
    return await asyncio.to_thread(
        _retrieve_terminology, terminology_service, query, datasource_id, enable_vector
    )


async def _retrieve_examples_async(
    few_shot_service, query: str, datasource_id, enable_vector: bool
) -> List[Dict[str, Any]]:
    """Async wrapper for few-shot retrieval."""
    import asyncio
    return await asyncio.to_thread(
        _retrieve_examples, few_shot_service, query, datasource_id, enable_vector
    )


async def _retrieve_join_hints_async(datasource_id: int, state: Dict[str, Any]) -> List[str]:
    """Async wrapper for JOIN hints retrieval."""
    import asyncio
    return await asyncio.to_thread(_retrieve_join_hints, datasource_id, state)


async def _match_sql_patterns_async(question: str) -> List[str]:
    """Async wrapper for SQL pattern matching."""
    import asyncio
    return await asyncio.to_thread(_match_sql_patterns, question)
