"""
Routing node - integrates RouterAgent for FAST/STANDARD/FULL path selection.
Also detects cross-source query intent and runs clarification detection.
"""
import logging
from typing import Dict, Any, Optional, List

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


_CROSS_SOURCE_KEYWORDS = [
    "跨数据源", "跨库", "跨源", "联合查询", "合并数据源",
    "多个数据源", "所有数据源", "不同数据源",
    "cross source", "cross database", "multiple datasources",
    "join different", "combine data",
]


def _detect_cross_source_intent(question: str) -> bool:
    q_lower = question.lower()
    return any(kw in q_lower for kw in _CROSS_SOURCE_KEYWORDS)


def _infer_cross_source_from_registered_tables(question: str, current_datasource_id: Optional[int]) -> bool:
    """
    Infer cross-source requirement by comparing the question intent with registered datasource tables.

    Heuristic:
    - If question mentions a concept (客户/产品/促销/员工等)
    - And another datasource has a matching table name (customers/products/promotions/...)
    - And the current datasource does NOT have such a table
    Then enable cross-source mode.
    """
    try:
        from fastapi_app.agents.tools.datasource_manager import get_all_datasource_ids, get_datasource_handler

        ds_ids = get_all_datasource_ids()
        if len(ds_ids) <= 1:
            return False

        q = question or ""
        q_lower = q.lower()

        concept_to_table_markers = [
            (("客户", "customer"), ("customer", "customers")),
            (("产品", "product"), ("product", "products")),
            (("促销", "promotion", "discount"), ("promotion", "promotions", "discount")),
            (("员工", "employee"), ("employee", "employees", "performance")),
        ]

        current_tables: List[str] = []
        if current_datasource_id is not None:
            cur = get_datasource_handler(current_datasource_id)
            if cur and hasattr(cur, "get_tables"):
                current_tables = [getattr(t, "name", str(t)).lower() for t in (cur.get_tables() or [])]

        for concept_keywords, table_markers in concept_to_table_markers:
            if not any(k in q_lower for k in (ck.lower() for ck in concept_keywords)):
                continue

            current_has = any(any(m in t for m in table_markers) for t in current_tables)
            if current_has:
                continue

            # Any other datasource has the target table markers -> cross-source
            for ds_id in ds_ids:
                if current_datasource_id is not None and ds_id == current_datasource_id:
                    continue
                ds = get_datasource_handler(ds_id)
                if not ds or not hasattr(ds, "get_tables"):
                    continue
                tables = [getattr(t, "name", str(t)).lower() for t in (ds.get_tables() or [])]
                if any(any(m in t for m in table_markers) for t in tables):
                    return True

        return False
    except Exception:
        return False


def _detect_clarification(question: str, need_clarification: bool) -> Optional[Dict[str, Any]]:
    """
    Run ClarificationAgent when router signals need_clarification.

    Returns clarification info dict or None.
    The result is stored in state for the API layer to surface to the user.
    """
    from fastapi_app.core.config import settings
    if not getattr(settings, "USE_CLARIFICATION", False) or not need_clarification:
        return None

    try:
        from fastapi_app.agents.clarification_agent import clarification_agent

        result = clarification_agent.detect(question)
        if result and result.has_ambiguity:
            logger.info(
                f"Clarification detected: {len(result.ambiguities)} ambiguities, "
                f"question: {result.question.text if result.question else 'N/A'}"
            )
            return {
                "has_ambiguity": True,
                "ambiguities": [a.to_dict() for a in result.ambiguities],
                "question": result.question.to_dict() if result.question else None,
            }
    except Exception as e:
        logger.warning(f"Clarification detection failed: {e}")

    return None


def _is_ultra_simple_query(question: str) -> bool:
    """Fast heuristic for ultra-simple queries that can skip RAG entirely."""
    import re
    q = question.strip()

    # Pattern 1: "查询/显示 X表 前N条" or "X表的所有数据"
    if re.match(r'^(查询|显示|看|给我)\s*\w+表?\s*(的)?(所有|全部)?数据?$', q, re.IGNORECASE):
        return True
    if re.match(r'^\w+表?\s*(的)?(前|后)?\s*\d+\s*条?$', q, re.IGNORECASE):
        return True

    # Pattern 2: "统计X数量" (single table, no JOIN)
    if re.match(r'^统计\s*\w+\s*(的)?(数量|总数|个数)$', q, re.IGNORECASE):
        return True

    # Pattern 3: Simple English patterns
    if re.match(r'^(select|show|display)\s+\*?\s+from\s+\w+(\s+limit\s+\d+)?$', q, re.IGNORECASE):
        return True

    return False


def routing_node(state: AgentState, config: PipelineConfig) -> dict:
    """
    Route queries to FAST/STANDARD/FULL paths based on complexity.

    Integrations:
    - Ultra-fast pattern matching for trivial queries (NEW)
    - RouterAgent: FAST/STANDARD/FULL classification
    - Cross-source detection: keyword heuristic
    - ClarificationAgent: ambiguity detection (when router signals need_clarification)
    """
    from fastapi_app.agents.router_agent import router_agent, RoutingPath

    question = state["question"]
    datasource_id = state.get("datasource_id")

    # Ultra-fast path: skip RouterAgent for trivial queries
    if _is_ultra_simple_query(question):
        if config.verbose:
            logger.info(f"Ultra-simple query detected, using FAST path without RouterAgent")
        return {
            "routing_decision": {
                "path": "fast",
                "complexity": "simple",
                "confidence": 1.0,
                "reasoning": "Ultra-simple query pattern matched",
                "skip_full_schema_retrieval": True,
                "use_multi_candidate": False,
                "max_retrieval_tables": 1,
                "need_clarification": False,
            },
            "cross_source_mode": False,
            "available_datasources": None,
            "selected_datasource_ids": None,
        }

    # Cross-source can be explicitly enabled by the caller (UI/API) via selected_datasource_ids,
    # or inferred via keyword heuristics.
    selected_ids: Optional[List[int]] = state.get("selected_datasource_ids")
    cross_source = (
        bool(state.get("cross_source_mode"))
        or _detect_cross_source_intent(question)
        or _infer_cross_source_from_registered_tables(question, datasource_id)
    )

    available_datasources = None
    if selected_ids and len(selected_ids) > 1:
        available_datasources = [{"id": ds_id, "current": ds_id == datasource_id} for ds_id in selected_ids]
        cross_source = True
    elif cross_source:
        from fastapi_app.agents.tools.datasource_manager import get_all_datasource_ids
        all_ids = get_all_datasource_ids()
        if len(all_ids) > 1:
            available_datasources = [{"id": ds_id, "current": ds_id == datasource_id} for ds_id in all_ids]
            selected_ids = list(all_ids)
        else:
            cross_source = False

    try:
        decision = router_agent.route(question)
        routing_dict = decision.to_dict()

        # Run clarification detection if router signals it
        clarification = _detect_clarification(
            question, decision.need_clarification
        )
        if clarification:
            routing_dict["clarification"] = clarification

        if config.verbose:
            logger.info(
                f"Routing decision: path={decision.path.value}, "
                f"complexity={decision.complexity.value}, "
                f"confidence={decision.confidence:.2f}, "
                f"cross_source={cross_source}, "
                f"clarification={'yes' if clarification else 'no'}"
            )

        return {
            "routing_decision": routing_dict,
            "cross_source_mode": cross_source,
            "available_datasources": available_datasources,
            "selected_datasource_ids": selected_ids if cross_source and selected_ids else None,
        }
    except Exception as e:
        logger.warning(f"Routing failed, defaulting to STANDARD: {e}")
        return {
            "routing_decision": {
                "path": "standard",
                "complexity": "medium",
                "confidence": 0.5,
                "reasoning": f"Routing failed: {e}, defaulting to standard",
                "skip_full_schema_retrieval": False,
                "use_multi_candidate": False,
                "max_retrieval_tables": 5,
                "need_clarification": False,
            },
            "cross_source_mode": cross_source,
            "available_datasources": available_datasources,
            "selected_datasource_ids": selected_ids if cross_source and selected_ids else None,
        }


def should_route(state: AgentState, config: PipelineConfig) -> str:
    """
    Determine which path to take based on routing decision.

    Returns: "fast", "standard", or "full".
    """
    routing = state.get("routing_decision", {})
    path = routing.get("path", "standard")

    if path == "fast":
        return "fast"
    elif path == "full":
        return "full"
    else:
        return "standard"
