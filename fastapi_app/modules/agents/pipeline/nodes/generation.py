"""
Agent/LLM generation node - invokes LLM to generate SQL.
"""
import logging
import re
from typing import Dict, Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from fastapi_app.agents.pipeline.state import AgentState, OutputMode
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.core.config import settings
from fastapi_app.services.log_service import AgentLogService

logger = logging.getLogger(__name__)


def _extract_sql_from_text(text: str) -> str:
    s = str(text or "")
    # Prefer fenced SQL block.
    m = re.search(r"```sql\s*(.*?)```", s, flags=re.I | re.S)
    if m:
        sql = str(m.group(1) or "").strip()
        if sql:
            return sql
    # Fallback: first SELECT ... (greedy until end).
    m = re.search(r"(?is)\bselect\b.+", s)
    if m:
        sql = str(m.group(0) or "").strip()
        sql = re.sub(r"\s+$", "", sql)
        # Trim trailing markdown fences if any.
        sql = sql.split("```")[0].strip()
        return sql
    return ""


def agent_node(state: AgentState, config: PipelineConfig) -> dict:
    """
    Agent node - invoke LLM for reasoning.

    Logic:
    1. If first call, build system prompt
    2. If SQL error and retries remain, build correction prompt
    3. If SQL verified and result ready, skip LLM
    4. If max retries exceeded, return error
    """
    from fastapi_app.agents.prompts.builder import build_system_prompt
    from fastapi_app.agents.prompts.correction import build_correction_prompt

    messages = state["messages"]
    error_count = state.get("error_count", 0)
    max_retries = state.get("max_retries", 3)
    last_sql_error = state.get("last_sql_error")
    rag_context = state.get("rag_context", {})
    query_result_data = state.get("query_result_data")
    routing_decision = state.get("routing_decision") or {}
    routing_path = routing_decision.get("path", "standard")
    cross_source_mode = bool(state.get("cross_source_mode", False))

    # Check: SQL verified and result ready - skip LLM
    if query_result_data and not last_sql_error and error_count == 0:
        if config.verbose:
            logger.info("Agent Node [SQL Verified] - Results ready, skipping LLM invoke")
        # Avoid returning a pure no-op update (some LangGraph versions treat empty
        # list updates as "write nothing" and raise InvalidUpdateError).
        return {"thinking": state.get("thinking") or ""}

    # FULL path: use multi-candidate generation if available (only when schema is loaded)
    if len(messages) == 1 and isinstance(messages[0], HumanMessage):
        has_schema = bool(state.get("schema_cache"))
        if (
            routing_path == "full"
            and routing_decision.get("use_multi_candidate", False)
            and has_schema
            and not cross_source_mode
        ):
            multi_result = _try_multi_candidate(state, config, rag_context)
            if multi_result is not None:
                return multi_result

    # Always prepend system prompt for every LLM invoke (first call + correction).
    # We keep it out of the persistent state messages to avoid inflating the message
    # history, but ensure every invocation has the same guardrails and tool workflow.
    system_prompt = build_system_prompt(
        datasource_id=state["datasource_id"],
        rag_context=rag_context,
        sql_rules=config.sql_rules,
        cross_source_mode=cross_source_mode,
        routing_path=routing_path,
        conversation_context=state.get("conversation_context"),
        available_datasources=state.get("available_datasources"),
        ega_context=state.get("ega_context"),
        question=state.get("question", ""),
    )
    invoke_messages = [SystemMessage(content=system_prompt)] + list(messages)
    if config.verbose and len(messages) == 1 and isinstance(messages[0], HumanMessage):
        logger.info("Agent Node [First Call] - Creating system prompt")

    if last_sql_error and error_count < max_retries:
        # Enhancement 5: Check if FAST path should escalate to STANDARD
        current_path = routing_decision.get("path", "standard")
        escalated = False

        if current_path == "fast" and error_count >= max_retries - 1:
            try:
                from fastapi_app.modules.routing_feedback import routing_feedback_tracker
                question = state.get("question", "")
                if routing_feedback_tracker.should_escalate_to_standard(question, error_count, max_retries):
                    logger.info(
                        f"Agent Node [Path Escalation] - "
                        f"Upgrading FAST→STANDARD due to historical failure pattern"
                    )
                    escalated = True
            except Exception as e:
                logger.warning(f"Path escalation check failed: {e}")

        if escalated:
            # Return escalation signal to update routing and reset
            return {
                "routing_decision": {**routing_decision, "path": "standard"},
                "error_count": 0,
                "max_retries": 3,
                "messages": list(messages),
            }

        # SQL execution failed, attempt correction
        last_sql = state.get("last_sql", "")
        datasource_id = state.get("datasource_id")
        correction_prompt = build_correction_prompt(
            datasource_id,
            last_sql,
            last_sql_error,
            cross_source_mode=cross_source_mode,
            selected_datasource_ids=state.get("selected_datasource_ids"),
            failure_stage=state.get("failure_stage"),
        )
        invoke_messages = list(invoke_messages) + [HumanMessage(content=correction_prompt)]
        if config.verbose:
            logger.info(f"Agent Node [SQL Correction] - Attempt {error_count + 1}/{max_retries}")
    else:
        if error_count >= max_retries:
            if config.verbose:
                logger.warning(f"Agent Node [Max Retries] - Exceeded max retries ({max_retries})")
            return {
                "messages": [],
                "error": f"Exceeded maximum retry attempts ({max_retries})",
                "error_count": error_count,
            }

    try:
        if config.verbose:
            logger.info(f"Agent Node [LLM Invoke] - Messages count: {len(invoke_messages)}, Error count: {error_count}")

        chat_id = hash(state.get("question", ""))
        log = AgentLogService.start_log(
            chat_id=chat_id,
            operation="generate_sql" if error_count == 0 else "correct_sql",
            input_messages=[
                {"type": getattr(m, "type", "unknown"), "content": getattr(m, "content", str(m))[:500]}
                for m in invoke_messages[-3:]
            ],
            step_index=error_count,
        )

        response = config.llm_with_tools.invoke(invoke_messages)

        # Extract token usage
        token_usage = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_usage = response.usage_metadata
        elif hasattr(response, "response_metadata"):
            token_usage = response.response_metadata.get("token_usage")

        # Extract tool calls (with EGA fallback when model returns plain text only).
        has_tool_calls = hasattr(response, "tool_calls") and response.tool_calls
        if cross_source_mode and bool(state.get("ega_enabled_for_turn")) and not has_tool_calls:
            ds_ids = [int(x) for x in (state.get("selected_datasource_ids") or []) if str(x).strip()]
            sql_candidate = _extract_sql_from_text(getattr(response, "content", ""))
            if ds_ids and sql_candidate:
                response = AIMessage(
                    content="Auto-converted SQL text into execute_cross_source_sql tool call.",
                    tool_calls=[
                        {
                            "name": "execute_cross_source_sql",
                            "args": {"datasource_ids": ds_ids, "sql": sql_candidate, "limit": 1000},
                            "id": "auto_exec_cross_source_sql",
                        }
                    ],
                )
                has_tool_calls = True
            elif ds_ids:
                # Force a schema tool call so the loop continues instead of silent finish.
                response = AIMessage(
                    content="Auto-fallback to cross-source schema tool call (EGA mode).",
                    tool_calls=[
                        {
                            "name": "get_cross_source_schema",
                            "args": {
                                "datasource_ids": ds_ids,
                                "strategy": "ega",
                                "query": str(state.get("question") or "")[:300],
                            },
                            "id": "auto_get_cross_source_schema",
                        }
                    ],
                )
                has_tool_calls = True

        tool_calls = None
        if has_tool_calls:
            tool_calls = [
                {
                    "name": tc.get("name", getattr(tc, "name", "")),
                    "args": tc.get("args", getattr(tc, "args", {})),
                }
                for tc in response.tool_calls
            ]

        AgentLogService.end_log(
            log=log,
            output_message=response.content[:1000] if response.content else None,
            thinking_content=getattr(response, "reasoning_content", None),
            tool_calls=tool_calls,
            token_usage=token_usage,
            model_name=settings.OPENAI_MODEL,
            success=True,
        )

        if config.verbose:
            logger.info(f"Agent Node [LLM Response] - Has tool_calls: {has_tool_calls}, Content length: {len(response.content) if response.content else 0}")
            if token_usage:
                logger.info(f"Agent Node [Token Usage] - {token_usage}")

        return {
            "messages": [response],
            "thinking": getattr(response, "content", ""),
        }
    except Exception as e:
        logger.error(f"Agent Node [LLM Error]: {e}", exc_info=True)
        if "log" in locals():
            AgentLogService.end_log(log=log, success=False, error_message=str(e))
        return {
            "messages": [],
            "error": str(e),
            "error_count": error_count + 1,
        }


def should_continue(state: AgentState, config: PipelineConfig) -> str:
    """
    Determine whether the agent should continue execution.

    Returns edge label: "continue", "finish", "export_data", or "error".
    """
    if state.get("error"):
        logger.warning(f"_should_continue [Error] - {state.get('error')}")
        return "error"

    mode = state.get("output_mode") or OutputMode.QA.value
    error_count = state.get("error_count", 0)
    max_retries = state.get("max_retries", 3)
    has_query_result = state.get("query_result_data") is not None
    last_sql_error = state.get("last_sql_error")

    # Important: if result is already valid, stop even when the latest persisted
    # assistant message still contains historical tool_calls.
    if has_query_result and not last_sql_error and error_count == 0:
        if mode == OutputMode.DATA.value:
            logger.info("_should_continue [Ready Result] - DATA mode, returning 'export_data'")
            return "export_data"
        logger.info("_should_continue [Ready Result] - QA mode, returning 'finish'")
        return "finish"

    messages = state["messages"]
    if not messages:
        logger.error("_should_continue [No Messages] - messages list is empty")
        return "error"

    last_message = messages[-1]
    has_tool_calls = hasattr(last_message, "tool_calls") and last_message.tool_calls
    if has_tool_calls:
        logger.info(f"_should_continue [Tool Calls] - Detected {len(last_message.tool_calls)} calls, returning 'continue'")
        return "continue"

    # Check if there is pending SQL to execute (from multi-candidate)
    last_sql = state.get("last_sql")
    if last_sql and not has_query_result:
        logger.info(f"_should_continue [Pending SQL] - SQL generated but not executed, returning 'continue'")
        return "continue"

    logger.info(f"_should_continue [State Check] - mode={mode}, has_query_result={has_query_result}, error_count={error_count}/{max_retries}")

    if mode == OutputMode.DATA.value:
        if has_query_result:
            logger.info("_should_continue [DATA Mode] - Has query result, returning 'export_data'")
            return "export_data"
        if error_count < max_retries:
            logger.warning(f"_should_continue [DATA Mode] - No query result, error_count={error_count}")
            return "finish"
        logger.error(f"_should_continue [DATA Mode] - No query result after {max_retries} attempts")
        return "finish"

    return "finish"


def _try_multi_candidate(state: AgentState, config: PipelineConfig, rag_context: dict):
    """
    Attempt multi-candidate SQL generation for FULL path.

    Returns state update dict if successful, None to fall back to normal generation.
    """
    try:
        from fastapi_app.agents.multi_candidate_generator import multi_candidate_generator

        question = state["question"]
        datasource_id = state["datasource_id"]

        # Get schema context for multi-candidate
        schema_text = ""
        if state.get("schema_cache"):
            schema_text = str(state["schema_cache"])

        # Get few-shot examples from RAG context
        examples = rag_context.get("similar_examples", [])

        result = multi_candidate_generator.generate_and_select(
            question=question,
            schema_text=schema_text,
            examples=examples,
        )

        if result and result.selected_sql:
            logger.info(
                f"Multi-candidate [FULL] - Selected SQL via {result.selected_strategy}, "
                f"confidence={result.confidence:.2f}, candidates={result.total_candidates}"
            )
            from langchain_core.messages import AIMessage
            ai_msg = AIMessage(
                content=f"基于多候选分析，最优SQL:\n```sql\n{result.selected_sql}\n```\n"
                        f"策略: {result.selected_strategy}, 置信度: {result.confidence:.2f}"
            )
            return {
                "messages": [ai_msg],
                "thinking": f"Multi-candidate: {result.total_candidates} candidates, "
                           f"selected via {result.selected_strategy}",
                "last_sql": result.selected_sql,
            }

    except Exception as e:
        logger.warning(f"Multi-candidate generation failed, falling back to standard: {e}")

    return None
