"""
LangGraph graph builder - constructs the agent execution graph.
"""
import logging

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.agents.pipeline.nodes.routing import routing_node, should_route
from fastapi_app.agents.pipeline.nodes.understanding import query_understanding_node
from fastapi_app.agents.pipeline.nodes.retrieval import retrieve_knowledge_node
from fastapi_app.agents.pipeline.nodes.generation import agent_node, should_continue
from fastapi_app.agents.pipeline.nodes.tool_processing import process_tool_output_node
from fastapi_app.agents.pipeline.nodes.validation import validate_sql_aliases_node
from fastapi_app.agents.pipeline.nodes.ega_prepare import ega_prepare_node, should_run_ega_prepare
from fastapi_app.agents.pipeline.nodes.spec_verification import spec_verification_node
from fastapi_app.agents.pipeline.nodes.ega_retry_router import ega_retry_router_node, should_ega_retry_route
from fastapi_app.agents.pipeline.nodes.export import export_data_node
from fastapi_app.agents.pipeline.nodes.finish import finish_node

logger = logging.getLogger(__name__)


def build_graph(config: PipelineConfig) -> StateGraph:
    """
    Build the LangGraph execution graph.

    Graph structure (with Router integration):

    START → routing → [conditional]
        ├─ fast → agent (skip RAG)
        ├─ standard → query_understanding → retrieve_knowledge → agent
        └─ full → query_understanding → retrieve_knowledge → agent

    agent → [conditional]
        ├─ continue → tools → process_tool_output → validate_sql_aliases → [conditional]
        │                                                                     ├─ retry → agent
        │                                                                     └─ continue → agent
        ├─ export_data → data_export → END
        ├─ finish → END
        └─ error → finish → END
    """
    graph = StateGraph(AgentState)

    # Create node wrappers that bind config
    def _routing(state):
        return routing_node(state, config)

    def _understanding(state):
        return query_understanding_node(state, config)

    def _retrieval(state):
        return retrieve_knowledge_node(state, config)

    def _ega_prepare(state):
        return ega_prepare_node(state, config)

    def _agent(state):
        return agent_node(state, config)

    def _process_tool_output(state):
        return process_tool_output_node(state, config)

    def _validate(state):
        return validate_sql_aliases_node(state, config)

    def _spec_verification(state):
        return spec_verification_node(state, config)

    def _ega_retry_router(state):
        return ega_retry_router_node(state, config)

    def _finish(state):
        return finish_node(state, config)

    def _export(state):
        return export_data_node(state, config)

    def _should_continue(state):
        return should_continue(state, config)

    def _should_ega_prepare(state):
        return should_run_ega_prepare(state, config)

    def _should_ega_retry_route(state):
        return should_ega_retry_route(state, config)

    def _should_route(state):
        return should_route(state, config)

    def _should_route_entry(state):
        # Hard split: EGA-capable cross-source requests should enter EGA lane
        # immediately and bypass legacy retrieval path.
        if _should_ega_prepare(state) == "ega_prepare":
            return "ega"
        return _should_route(state)

    def _after_tool_processing(state):
        # EGA lane skips legacy SQL alias validation and uses spec verification
        # as the result-level gate.
        if bool(state.get("ega_enabled_for_turn")):
            return "ega_spec"
        return "legacy_validate"

    def _after_understanding(state):
        return _should_ega_prepare(state)

    # Add all nodes
    graph.add_node("routing", _routing)

    if config.use_query_improvements:
        graph.add_node("query_understanding", _understanding)

    graph.add_node("retrieve_knowledge", _retrieval)
    graph.add_node("ega_prepare", _ega_prepare)
    graph.add_node("agent", _agent)
    graph.add_node("tools", ToolNode(config.tools))
    graph.add_node("process_tool_output", _process_tool_output)
    graph.add_node("validate_sql_aliases", _validate)
    graph.add_node("spec_verification", _spec_verification)
    graph.add_node("ega_retry_router", _ega_retry_router)
    graph.add_node("finish", _finish)
    graph.add_node("data_export", _export)

    # Entry point: routing
    graph.set_entry_point("routing")

    # Routing conditional edges
    if config.use_query_improvements:
        graph.add_conditional_edges(
            "routing",
            _should_route_entry,
            {
                "fast": "agent",  # Skip RAG for simple queries
                "standard": "query_understanding",
                "full": "query_understanding",
                "ega": "query_understanding",
            },
        )
        graph.add_conditional_edges(
            "query_understanding",
            _after_understanding,
            {
                "ega_prepare": "ega_prepare",
                "skip": "retrieve_knowledge",
            },
        )
    else:
        graph.add_conditional_edges(
            "routing",
            _should_route_entry,
            {
                "fast": "agent",
                "standard": "retrieve_knowledge",
                "full": "retrieve_knowledge",
                "ega": "ega_prepare",
            },
        )

    graph.add_edge("retrieve_knowledge", "agent")
    graph.add_edge("ega_prepare", "agent")

    # Agent conditional edges
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {
            "continue": "tools",
            "finish": "finish",
            "export_data": "data_export",
            "error": "finish",
        },
    )

    # Tool execution pipeline
    graph.add_edge("tools", "process_tool_output")
    graph.add_conditional_edges(
        "process_tool_output",
        _after_tool_processing,
        {
            "ega_spec": "spec_verification",
            "legacy_validate": "validate_sql_aliases",
        },
    )
    graph.add_edge("validate_sql_aliases", "agent")
    graph.add_edge("spec_verification", "ega_retry_router")
    graph.add_conditional_edges(
        "ega_retry_router",
        _should_ega_retry_route,
        {
            "ega_prepare": "ega_prepare",
            "agent": "agent",
            "finish": "finish",
        },
    )

    # Terminal edges
    graph.add_edge("finish", END)
    graph.add_edge("data_export", END)

    return graph
