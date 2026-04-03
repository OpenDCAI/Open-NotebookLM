"""
EGA preparation node.

Builds task-driven cross-source context:
- Extensional profiling
- TCS alignment
- Virtual clean views metadata
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.agents.tools.datasource_manager import get_datasource_handler

logger = logging.getLogger(__name__)


def _parse_supported_types(raw: str) -> set[str]:
    return {x.strip().lower() for x in (raw or "").split(",") if x.strip()}


def _is_supported_ds(ds_id: int, supported_types: set[str]) -> bool:
    ds = get_datasource_handler(ds_id)
    if ds is None:
        return False
    code = getattr(getattr(ds, "metadata", None), "type", None)
    ds_code = getattr(code, "code", "")
    return str(ds_code).lower() in supported_types


def _should_enable_ega(state: AgentState, config: PipelineConfig) -> bool:
    if not getattr(config, "ega_enabled", False):
        return False

    strategy = str(state.get("execution_strategy") or "").strip().lower()
    if strategy and strategy not in {"ega", "auto"}:
        return False

    if not bool(state.get("cross_source_mode")):
        return False
    ds_ids = state.get("selected_datasource_ids") or []
    if len(ds_ids) < 2:
        return False

    supported = _parse_supported_types(getattr(config, "ega_supported_types", "csv,excel,sqlite"))
    return all(_is_supported_ds(int(i), supported) for i in ds_ids)


def should_run_ega_prepare(state: AgentState, config: PipelineConfig) -> str:
    return "ega_prepare" if _should_enable_ega(state, config) else "skip"


def ega_prepare_node(state: AgentState, config: PipelineConfig) -> Dict[str, Any]:
    ds_ids: List[int] = [int(x) for x in (state.get("selected_datasource_ids") or [])]
    if not ds_ids:
        return {"ega_enabled_for_turn": False}

    if not _should_enable_ega(state, config):
        return {"ega_enabled_for_turn": False}

    deep_probe = str(state.get("failure_stage") or "") in {"instance_alignment", "discovery", "schema_alignment"}

    try:
        from fastapi_app.agents.tools.cross_source_tools import _get_or_create_engine
        from fastapi_app.modules.ega.orchestrator import prepare_ega_context

        engine = _get_or_create_engine(ds_ids)
        ega_ctx = prepare_ega_context(
            engine=engine,
            datasource_ids=ds_ids,
            question=state.get("question", ""),
            llm=config.llm,
            sample_rows=max(20, int(getattr(config, "ega_profile_sample_rows", 100))),
            optimization_target=str(getattr(config, "ega_optimization_target", "accuracy")),
            lambda1=float(getattr(config, "ega_lambda1", 0.3)),
            lambda2=float(getattr(config, "ega_lambda2", 0.5)),
            deep_probe=deep_probe,
        )

        trace = list(state.get("ega_trace") or [])
        trace.append(
            {
                "event": "ega_prepare",
                "deep_probe": deep_probe,
                "candidate_tables": len((ega_ctx.get("relevant_tables") or [])),
                "clean_views": len((ega_ctx.get("clean_views") or {})),
            }
        )

        rag_context = dict(state.get("rag_context") or {})
        rag_context["ega_hint"] = ega_ctx.get("prompt_hint")
        rag_context["ega_clean_views"] = ega_ctx.get("clean_views") or {}
        rag_context["ega_clean_view_schema"] = ega_ctx.get("clean_view_schema") or ""

        return {
            "ega_enabled_for_turn": True,
            "ega_context": ega_ctx,
            "ega_trace": trace,
            "failure_stage": None,
            "rag_context": rag_context,
            "schema_cache": {
                "schema": ega_ctx.get("clean_view_schema") or ega_ctx.get("filtered_schema") or "",
                "strategy": "ega_runtime",
                "is_clean_view_schema": True,
            },
        }
    except Exception as e:
        logger.warning(f"EGA prepare failed, fallback to legacy path: {e}")
        trace = list(state.get("ega_trace") or [])
        trace.append({"event": "ega_prepare_failed", "error": str(e)})
        return {
            "ega_enabled_for_turn": False,
            "ega_trace": trace,
        }
