"""
Spec verification node for EGA path.
"""
from __future__ import annotations

import logging
from typing import Dict, Any

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


def _stage_from_spec_issue(issues: list[dict]) -> str:
    if not issues:
        return "spec_verification"
    t = str((issues[0] or {}).get("type") or "")
    if t == "missing_required_columns":
        return "spec_alias"
    if t == "empty_result":
        return "instance_alignment"
    if t == "numeric_range":
        return "spec_value_range"
    if t == "format_mismatch":
        return "spec_format"
    if t == "too_few_rows":
        return "instance_alignment"
    return "spec_verification"


def spec_verification_node(state: AgentState, config: PipelineConfig) -> Dict[str, Any]:
    if not state.get("ega_enabled_for_turn"):
        return {"spec_verification_result": {"status": "skipped", "reason": "ega_disabled_for_turn"}}

    query_result = state.get("query_result_data")
    if not isinstance(query_result, dict):
        return {"spec_verification_result": {"status": "skipped", "reason": "no_query_result"}}

    try:
        from fastapi_app.modules.ega.spec_verifier import extract_deliverable_spec, verify_result

        spec = state.get("deliverable_spec")
        if not isinstance(spec, dict):
            spec = extract_deliverable_spec(
                question=state.get("question", ""),
                llm=config.llm,
                output_mode=state.get("output_mode"),
                data_format=state.get("data_format"),
            )

        verification = verify_result(query_result, spec or {})
        if verification.get("ok"):
            update: Dict[str, Any] = {
                "deliverable_spec": spec,
                "spec_verification_result": verification,
                "spec_verification_attempts": 0,
            }
            # Memory write-back: only persist successful EGA alignments.
            try:
                ds_ids = [int(x) for x in (state.get("selected_datasource_ids") or []) if str(x).strip()]
                ega_context = state.get("ega_context") or {}
                if ds_ids and isinstance(ega_context, dict) and ega_context.get("alignment_graph"):
                    from fastapi_app.agents.tools.cross_source_tools import _get_or_create_engine
                    from fastapi_app.modules.ega.orchestrator import write_success_memory

                    engine = _get_or_create_engine(ds_ids)
                    written = int(write_success_memory(engine, ega_context))
                    update["spec_verification_result"] = {
                        **verification,
                        "memory_writeback": {
                            "enabled": True,
                            "entries_written": written,
                        },
                    }
            except Exception as e:
                logger.debug(f"EGA memory write-back skipped: {e}")

            return update

        issues = verification.get("issues") or []
        msg = verification.get("message") or "Spec verification failed"
        issue_types = {str((x or {}).get("type") or "") for x in issues if isinstance(x, dict)}

        spec_attempts = int(state.get("spec_verification_attempts", 0))
        max_spec_attempts = max(1, min(3, int(getattr(config, "ega_max_iterations", 3))))

        # Critical deliverable issues should trigger directed retry, but cap
        # attempts to avoid retry storms.
        blocking_types = {"empty_result", "too_few_rows"}
        if not issue_types & blocking_types:
            return {
                "deliverable_spec": spec,
                "spec_verification_result": {
                    **verification,
                    "status": "warning",
                    "blocking": False,
                },
                "failure_stage": _stage_from_spec_issue(issues),
                "spec_verification_attempts": spec_attempts,
            }

        next_attempts = spec_attempts + 1
        if next_attempts >= max_spec_attempts:
            return {
                "deliverable_spec": spec,
                "spec_verification_result": {
                    **verification,
                    "status": "warning",
                    "blocking": False,
                    "message": f"{msg} (spec retry exhausted: {next_attempts}/{max_spec_attempts})",
                },
                "failure_stage": _stage_from_spec_issue(issues),
                "spec_verification_attempts": next_attempts,
            }

        return {
            "deliverable_spec": spec,
            "spec_verification_result": verification,
            "last_sql_error": msg,
            "error_count": state.get("error_count", 0) + 1,
            "query_result_data": None,
            "failure_stage": _stage_from_spec_issue(issues),
            "spec_verification_attempts": next_attempts,
        }
    except Exception as e:
        logger.warning(f"Spec verification failed unexpectedly: {e}")
        return {
            "spec_verification_result": {
                "status": "error",
                "ok": False,
                "message": str(e),
                "issues": [{"type": "verifier_exception", "detail": str(e)}],
            }
        }
