"""
Finish node - extract final answer from messages.
"""
import logging

from langchain_core.messages import AIMessage

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


def finish_node(state: AgentState, config: PipelineConfig) -> dict:
    """Extract final answer from the last AI message."""
    from fastapi_app.modules.routing_feedback import routing_feedback_tracker
    from fastapi_app.agents.prompts.error_classifier import classify_error

    messages = state["messages"]
    final_answer = None

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) or (isinstance(msg, dict) and msg.get("role") == "assistant"):
            content = msg.content if isinstance(msg, AIMessage) else msg.get("content", "")
            if content and not hasattr(msg, "tool_calls"):
                final_answer = content
                break

    if not final_answer and len(messages) > 0:
        last_msg = messages[-1]
        final_answer = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    # Enhancement 5: Record routing outcome for adaptive learning.
    # This is metrics/logging and should not affect determinism, so record even when
    # the learning loop is frozen for eval.
    try:
        question = state.get("question", "")
        routing_decision = state.get("routing_decision", {})
        path = routing_decision.get("path", "standard")
        query_result_data = state.get("query_result_data")
        last_sql_error = state.get("last_sql_error")
        error_count = state.get("error_count", 0)

        # Determine success: has valid query result and no error
        success = bool(query_result_data) and not last_sql_error

        # Classify error if failed
        error_type = None
        if not success and last_sql_error:
            error_type = classify_error(last_sql_error).error_type.value

        routing_feedback_tracker.record_outcome(
            path=path,
            question=question,
            success=success,
            error_type=error_type,
            sql_attempts=error_count + 1,
        )

        if config.verbose:
            logger.info(
                f"Finish node [Routing Feedback] - "
                f"path={path}, success={success}, error_type={error_type}, attempts={error_count + 1}"
            )
    except Exception as e:
        logger.warning(f"Routing feedback recording failed: {e}")

    return {"final_answer": final_answer or "无法生成答案"}
