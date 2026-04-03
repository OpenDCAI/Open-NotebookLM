"""
Agent State definition and enums.

Refactored from sqlbot_agent.py - cleaned up unused fields.
"""
from typing import TypedDict, List, Optional, Any, Annotated, Dict
from enum import Enum

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class OutputMode(str, Enum):
    QA = "qa"
    DATA = "data"
    CHART = "chart"


class DataFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    CSV = "csv"
    DICT = "dict"


class AgentState(TypedDict):
    """
    Agent state - cleaned up version.

    Changes from original:
    - Removed unused sql_messages, chart_messages, analysis_messages
    - Added schema_cache for Schema persistence
    - Added routing_decision for Router integration
    """
    messages: Annotated[List[BaseMessage], add_messages]
    datasource_id: int
    question: str

    # Message history limit (default 6, prevents token overflow)
    max_message_history: int

    # Thinking and answer
    thinking: Optional[str]
    final_answer: Optional[str]

    # SQL tracking
    sql_history: Optional[List[Dict[str, Any]]]
    last_sql: Optional[str]
    last_sql_error: Optional[str]

    # Error handling
    error_count: int
    max_retries: int
    error: Optional[str]
    validation_attempts: int

    # Intermediate results
    intermediate_results: Optional[Dict[str, Any]]

    # Schema cache (Phase 1.2: persist schema from tool calls)
    schema_cache: Optional[Dict[str, Any]]

    # RAG context
    rag_context: Optional[Dict[str, Any]]

    # Query rewrite + Thinking (JoyAgent style)
    rewritten_query: Optional[str]
    query_thinking: Optional[str]
    value_linking_results: Optional[List[Dict[str, Any]]]
    analysis_plan: Optional[Dict[str, Any]]

    # Query result data
    query_result_data: Optional[Dict[str, Any]]
    output_mode: Optional[str]
    data_format: Optional[str]
    export_data: Optional[Dict[str, Any]]

    # Routing decision (Phase 1.3: Router integration)
    routing_decision: Optional[Dict[str, Any]]

    # Cross-source query support (Phase 2)
    available_datasources: Optional[List[Dict[str, Any]]]
    selected_datasource_ids: Optional[List[int]]
    cross_source_mode: Optional[bool]
    execution_strategy: Optional[str]

    # Conversation context carryover (Enhancement 2)
    conversation_context: Optional[Dict[str, Any]]

    # EGA state
    ega_context: Optional[Dict[str, Any]]
    ega_trace: Optional[List[Dict[str, Any]]]
    ega_attempts: int
    failure_stage: Optional[str]
    deliverable_spec: Optional[Dict[str, Any]]
    spec_verification_result: Optional[Dict[str, Any]]
    spec_verification_attempts: int
    ega_enabled_for_turn: Optional[bool]


def build_initial_state(
    question: str,
    datasource_id: int,
    max_retries: int = 3,
    output_mode: str = OutputMode.QA.value,
    data_format: str = DataFormat.JSON.value,
    conversation_context: Optional[Dict[str, Any]] = None,
    selected_datasource_ids: Optional[List[int]] = None,
    execution_strategy: Optional[str] = None,
) -> AgentState:
    """Build a clean initial state for the agent."""
    from langchain_core.messages import HumanMessage

    cross_source = (
        selected_datasource_ids is not None
        and len(selected_datasource_ids) > 1
    )
    available_datasources = None
    if selected_datasource_ids:
        available_datasources = [
            {"id": ds_id, "current": ds_id == datasource_id}
            for ds_id in selected_datasource_ids
        ]

    return {
        "messages": [HumanMessage(content=question)],
        "datasource_id": datasource_id,
        "question": question,
        "max_message_history": 6,
        "thinking": None,
        "final_answer": None,
        "error": None,
        "sql_history": [],
        "last_sql": None,
        "last_sql_error": None,
        "error_count": 0,
        "max_retries": max_retries,
        "validation_attempts": 0,
        "intermediate_results": {},
        "schema_cache": None,
        "rag_context": {},
        "rewritten_query": None,
        "query_thinking": None,
        "value_linking_results": None,
        "analysis_plan": None,
        "query_result_data": None,
        "output_mode": output_mode,
        "data_format": data_format,
        "export_data": None,
        "routing_decision": None,
        "available_datasources": available_datasources,
        "selected_datasource_ids": selected_datasource_ids if cross_source else None,
        "cross_source_mode": cross_source,
        "execution_strategy": execution_strategy,
        "conversation_context": conversation_context,
        "ega_context": None,
        "ega_trace": [],
        "ega_attempts": 0,
        "failure_stage": None,
        "deliverable_spec": None,
        "spec_verification_result": None,
        "spec_verification_attempts": 0,
        "ega_enabled_for_turn": None,
    }
