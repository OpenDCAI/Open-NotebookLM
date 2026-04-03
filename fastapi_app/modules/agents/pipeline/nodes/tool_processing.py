"""
Tool output processing node.
"""
import json
import logging
from typing import Dict, Any

from langchain_core.messages import AIMessage, ToolMessage

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)


def process_tool_output_node(state: AgentState, config: PipelineConfig) -> dict:
    """
    Process tool output node (P3 enhanced: integrated auto-learning).
    """
    from fastapi_app.modules.rag.few_shot import few_shot_service

    messages = state["messages"]
    sql_history = state.get("sql_history", [])
    error_count = state.get("error_count", 0)
    question = state.get("question", "")
    datasource_id = state.get("datasource_id")
    cross_source_mode = bool(state.get("cross_source_mode"))
    ega_mode = bool(state.get("ega_enabled_for_turn"))
    existing_ir = dict(state.get("intermediate_results") or {})
    had_sql_execution = False
    max_non_sql_rounds = max(3, int(state.get("max_retries", 3) or 3) + 2)

    # Scan all tool messages from this step
    tool_messages = []
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            tool_messages.append(msg)
        elif isinstance(msg, AIMessage):
            break

    if not tool_messages:
        # LangGraph may treat an empty messages update as a no-op and raise an
        # "Must write to at least one of [...]" error. Always write something.
        existing_ir["_non_sql_tool_rounds"] = int(existing_ir.get("_non_sql_tool_rounds", 0)) + 1
        payload: Dict[str, Any] = {
            "intermediate_results": {
                **existing_ir,
                "_tool_processing": {"status": "no_tool_messages"},
            }
        }
        if existing_ir["_non_sql_tool_rounds"] >= max_non_sql_rounds:
            next_error_count = int(state.get("error_count", 0)) + 1
            payload["last_sql_error"] = (
                "Tool loop detected: no executable tool output. "
                "Generate and execute a concrete SELECT SQL now."
            )
            payload["error_count"] = next_error_count
            payload["failure_stage"] = "discovery"
            max_retries = int(state.get("max_retries", 3) or 3)
            if next_error_count >= max_retries:
                payload["error"] = f"Exceeded maximum retry attempts ({max_retries})"
        return payload

    update_dict: Dict[str, Any] = {}

    for tool_msg in tool_messages:
        try:
            content = tool_msg.content
            if isinstance(content, str):
                try:
                    result = json.loads(content)
                except Exception:
                    result = {"content": content}
            else:
                result = content

            if isinstance(result, dict):
                # Capture schema into state (Phase 1.2)
                # get_datasource_schema returns {"schema": "...", ...} (not "tables"),
                # so we cache the whole payload to enable later prompt reuse.
                tool_name = getattr(tool_msg, "name", "")
                if tool_name == "get_datasource_schema" and "schema" in result:
                    update_dict["schema_cache"] = result

                # Check for SQL execution result
                if "success" in result and ("sql" in result or "query_text" in result):
                    if cross_source_mode and tool_name == "execute_sql":
                        executed_sql = result.get("query_text") or result.get("sql") or ""
                        sql_history.append(
                            {
                                "sql": executed_sql,
                                "success": False,
                                "error": "cross_source_wrong_tool_execute_sql",
                                "attempt": error_count + 1,
                            }
                        )
                        update_dict.update(
                            {
                                "sql_history": sql_history,
                                "last_sql": executed_sql,
                                "last_sql_error": (
                                    "Cross-source mode requires execute_cross_source_sql(datasource_ids=[...], sql='...'). "
                                    "Do not use execute_sql."
                                ),
                                "error_count": error_count + 1,
                                "failure_stage": "sql_generation_failure",
                                "query_result_data": None,
                            }
                        )
                        continue
                    had_sql_execution = True
                    executed_sql = result.get("query_text") or result.get("sql") or ""

                    sql_entry = {
                        "sql": executed_sql,
                        "success": result.get("success", False),
                        "error": result.get("error_message"),
                        "attempt": error_count + 1,
                    }
                    sql_history.append(sql_entry)

                    if not result.get("success"):
                        if config.verbose:
                            logger.warning(f"SQL execution failed: {result.get('error_message')}")
                        err_msg = str(result.get("error_message") or "")
                        try:
                            from fastapi_app.agents.prompts.error_classifier import infer_failure_stage
                            failure_stage = infer_failure_stage(err_msg)
                        except Exception:
                            failure_stage = "unknown"
                        update_dict.update({
                            "sql_history": sql_history,
                            "last_sql": executed_sql,
                            "last_sql_error": result.get("error_message"),
                            "error_count": error_count + 1,
                            "failure_stage": failure_stage,
                        })
                    else:
                        # Success - save result data
                        query_data = {
                            "data": result.get("data", []),
                            "columns": result.get("columns", []),
                            "row_count": result.get("row_count", 0),
                            "sql": executed_sql,
                        }

                        update_dict.update({
                            "sql_history": sql_history,
                            "last_sql": executed_sql,
                            "last_sql_error": None,
                            # Keep current retry counter until validation confirms success.
                            # This avoids infinite retry loops where validation keeps failing
                            # but execute step repeatedly resets error_count to 0.
                            "error_count": state.get("error_count", 0),
                            "query_result_data": query_data,
                            "failure_stage": None,
                        })

                        if (not ega_mode) and getattr(settings, "LEARNING_ENABLE", True):
                            # P3: Auto-learn from successful SQL
                            try:
                                execution_time_ms = result.get("execution_time_ms", 0)
                                row_count = result.get("row_count", 0)
                                few_shot_service.learn_from_success(
                                    question=question,
                                    sql=executed_sql,
                                    datasource_id=datasource_id,
                                    execution_time_ms=execution_time_ms,
                                    row_count=row_count,
                                    quality_threshold=0.7,
                                    similarity_threshold=0.85,
                                )
                            except Exception as e:
                                logger.warning(f"Auto-learning failed: {e}")

                            # Enhancement 3: Learn JOIN relationships from successful SQL
                            if "JOIN" in executed_sql.upper() and datasource_id is not None:
                                try:
                                    from fastapi_app.modules.rag.schema_relationships import schema_relationship_service
                                    schema_relationship_service.learn_from_sql(datasource_id, executed_sql)
                                except Exception as e:
                                    logger.warning(f"JOIN relationship learning failed: {e}")

                # Enhancement 3: Discover relationships from schema metadata (only when structured tables exist)
                if (not ega_mode) and tool_name == "get_datasource_schema" and "tables" in result and isinstance(result.get("tables"), list):
                    if datasource_id is not None:
                        try:
                            from fastapi_app.modules.rag.schema_relationships import schema_relationship_service
                            schema_relationship_service.discover_from_schema(datasource_id, result)
                        except Exception as e:
                            logger.warning(f"Schema relationship discovery failed: {e}")

        except Exception as e:
            logger.error(f"Error processing tool output: {e}")

    if had_sql_execution:
        existing_ir["_non_sql_tool_rounds"] = 0
    else:
        if ega_mode and not update_dict.get("last_sql_error"):
            next_error_count = int(state.get("error_count", 0)) + 1
            update_dict["last_sql_error"] = (
                "EGA mode requires a concrete SQL execution via execute_cross_source_sql. "
                "Current step did not execute SQL."
            )
            update_dict["error_count"] = next_error_count
            update_dict["failure_stage"] = "sql_generation_failure"
            max_retries = int(state.get("max_retries", 3) or 3)
            if next_error_count >= max_retries:
                update_dict["error"] = f"Exceeded maximum retry attempts ({max_retries})"

        existing_ir["_non_sql_tool_rounds"] = int(existing_ir.get("_non_sql_tool_rounds", 0)) + 1
        # Guard against loops where the model keeps calling schema/discovery tools
        # without ever executing SQL.
        if existing_ir["_non_sql_tool_rounds"] >= max_non_sql_rounds:
            next_error_count = int(state.get("error_count", 0)) + 1
            update_dict["last_sql_error"] = (
                "Tool loop detected: too many schema/preparation calls without SQL execution. "
                "Call execute_sql/execute_cross_source_sql with a concrete SELECT now."
            )
            update_dict["error_count"] = next_error_count
            update_dict["failure_stage"] = "discovery"
            if next_error_count >= int(state.get("max_retries", 3) or 3):
                update_dict["error"] = f"Exceeded maximum retry attempts ({int(state.get('max_retries', 3) or 3)})"
        elif state.get("last_sql_error"):
            # If we are already in correction mode but the model keeps avoiding SQL execution,
            # count this as another failed retry to guarantee termination.
            next_error_count = int(state.get("error_count", 0)) + 1
            update_dict["error_count"] = next_error_count
            if not state.get("failure_stage"):
                try:
                    from fastapi_app.agents.prompts.error_classifier import infer_failure_stage
                    update_dict["failure_stage"] = infer_failure_stage(str(state.get("last_sql_error") or ""))
                except Exception:
                    update_dict["failure_stage"] = "unknown"
            max_retries = int(state.get("max_retries", 3) or 3)
            if next_error_count >= max_retries:
                update_dict["error"] = f"Exceeded maximum retry attempts ({max_retries})"

    update_dict["intermediate_results"] = {
        **existing_ir,
        "_tool_processing": {
            "status": "sql_executed" if had_sql_execution else "no_sql_execution",
            "tool_count": len(tool_messages),
            "tool_names": [getattr(m, "name", "") for m in tool_messages][:10],
        },
    }

    if not had_sql_execution and not state.get("last_sql_error") and not update_dict.get("last_sql_error"):
        # Keep previous behavior of signaling a no-op step, but now with loop counters.
        update_dict["intermediate_results"]["_tool_processing"]["status"] = "no_state_updates"

    return update_dict
