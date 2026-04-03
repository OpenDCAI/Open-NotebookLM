"""
EGA-aware retry router.
"""
from __future__ import annotations

import logging
from typing import Dict, Any

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


def _infer_stage_from_error(error_message: str) -> str:
    if not error_message:
        return "unknown"
    try:
        from fastapi_app.agents.prompts.error_classifier import classify_error, ErrorType

        c = classify_error(error_message)
        if c.error_type in {ErrorType.TABLE_NOT_FOUND}:
            return "discovery"
        if c.error_type in {ErrorType.COLUMN_NOT_FOUND}:
            return "schema_alignment"
        if c.error_type in {ErrorType.EMPTY_RESULT}:
            return "instance_alignment"
        if c.error_type in {ErrorType.QUESTION_MISMATCH}:
            return "question_mismatch"
        if c.error_type in {ErrorType.SYNTAX_ERROR}:
            return "sql_syntax"
        if c.error_type in {ErrorType.TYPE_MISMATCH, ErrorType.AMBIGUOUS_COLUMN}:
            return "instance_alignment"
    except Exception:
        pass
    return "unknown"


def should_ega_retry_route(state: AgentState, config: PipelineConfig) -> str:
    _ = config
    ir = state.get("intermediate_results") or {}
    route = str(ir.get("_ega_retry_route") or "finish")
    if route == "ega_prepare":
        return "ega_prepare"
    if route == "agent":
        return "agent"
    return "finish"


def ega_retry_router_node(state: AgentState, config: PipelineConfig) -> Dict[str, Any]:
    last_sql_error = str(state.get("last_sql_error") or "")
    existing_ir = dict(state.get("intermediate_results") or {})
    ega_enabled = bool(state.get("ega_enabled_for_turn"))
    if not last_sql_error:
        existing_ir["_ega_retry_route"] = "finish"
        return {"intermediate_results": existing_ir}

    stage = str(state.get("failure_stage") or "").strip() or _infer_stage_from_error(last_sql_error)
    attempts = int(state.get("ega_attempts", 0))
    max_iterations = max(1, int(getattr(config, "ega_max_iterations", 3)))

    # EGA-side structural failures should retry from EGA prepare.
    prepare_retry_stages = {
        "discovery",
        "schema_alignment",
        "instance_alignment",
        "profiling_failure",
        "alignment_failure",
    }
    # SQL composition failures should retry only NL2SQL generation.
    agent_retry_stages = {
        "sql_syntax",
        "sql_generation_failure",
        "question_mismatch",
        "spec_alias",
        "spec_verification",
        "spec_value_range",
        "spec_format",
    }

    if ega_enabled and stage in prepare_retry_stages and attempts < max_iterations:
        logger.info(f"EGA retry router: stage={stage}, attempts={attempts}/{max_iterations}, route=ega_prepare")
        existing_ir["_ega_retry_route"] = "ega_prepare"
        return {
            "intermediate_results": existing_ir,
            "ega_attempts": attempts + 1,
            "failure_stage": stage,
        }

    if ega_enabled and stage in agent_retry_stages and attempts < max_iterations:
        existing_ir["_ega_retry_route"] = "agent"
        return {
            "intermediate_results": existing_ir,
            "ega_attempts": attempts + 1,
            "failure_stage": stage,
        }

    if ega_enabled and attempts >= max_iterations:
        # Exhausted EGA retries: stop retry storm and finish with current error.
        existing_ir["_ega_retry_route"] = "finish"
        return {
            "intermediate_results": existing_ir,
            "failure_stage": stage,
            "ega_enabled_for_turn": False,
            "ega_context": None,
        }

    # Legacy / unknown failure fallback.
    if stage in agent_retry_stages:
        existing_ir["_ega_retry_route"] = "agent"
    else:
        existing_ir["_ega_retry_route"] = "finish"
    return {
        "intermediate_results": existing_ir,
        "failure_stage": stage,
    }
