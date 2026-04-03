"""
LangGraph SQLBot Agent - Core intelligent agent.

Refactored: logic split into backend/agents/pipeline/ modules.
This file is now a slim entry point (~120 lines instead of 1350).

Modules:
- pipeline/state.py: AgentState, OutputMode, DataFormat
- pipeline/config.py: PipelineConfig
- pipeline/graph.py: LangGraph graph construction
- pipeline/nodes/: Individual node implementations
- prompts/: Prompt building
"""
import asyncio
import logging
import os
import yaml
from typing import Optional, Dict, List
from datetime import datetime
from pathlib import Path

from fastapi_app.agents.pipeline.state import AgentState, OutputMode, DataFormat, build_initial_state
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.agents.pipeline.graph import build_graph
if os.getenv("SQLBOT_EMBEDDED_MINIMAL", "").strip().lower() in {"1", "true", "yes", "on"}:
    from fastapi_app.agents.tools.embedded_registry import get_all_tools
else:
    from fastapi_app.agents.tools.registry import get_all_tools
from fastapi_app.core.config import settings
from fastapi_app.core.llm_factory import LLMFactory, LLMConfig

# Initialize RAG services (side effects: registers examples)
from fastapi_app.modules.rag.few_shot import init_standard_examples  # noqa: F401

logger = logging.getLogger(__name__)

USE_QUERY_IMPROVEMENTS = getattr(settings, "USE_QUERY_IMPROVEMENTS", True)


class SQLBotAgent:
    """SQLBot Agent - LangGraph-based data analysis agent."""

    def __init__(self, verbose: bool = False, llm_config: Optional[LLMConfig] = None):
        self.verbose = verbose or settings.LANGGRAPH_VERBOSE

        # Create LLM instance
        if llm_config:
            self.llm = LLMFactory.create_llm(llm_config)
        else:
            self.llm = LLMFactory.from_settings()

        self.tools = get_all_tools()
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # Load SQL rules
        self.sql_rules = self._load_sql_rules()

        # Build pipeline config
        embedded_minimal = os.getenv("SQLBOT_EMBEDDED_MINIMAL", "").strip().lower() in {"1", "true", "yes", "on"}
        self.config = PipelineConfig(
            llm=self.llm,
            llm_with_tools=self.llm_with_tools,
            tools=self.tools,
            sql_rules=self.sql_rules,
            verbose=self.verbose,
            use_query_improvements=(False if embedded_minimal else USE_QUERY_IMPROVEMENTS),
            rag_enable_terminology=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_TERMINOLOGY", True)),
            rag_enable_few_shot=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_FEW_SHOT", True)),
            rag_enable_query_rewrite=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_QUERY_REWRITE", False)),
            rag_enable_value_retriever=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_VALUE_RETRIEVER", False)),
            rag_enable_analysis_cot=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_ANALYSIS_COT", False)),
            rag_enable_vector_terminology=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_VECTOR_TERMINOLOGY", False)),
            rag_enable_vector_few_shot=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_VECTOR_FEW_SHOT", False)),
            rag_enable_schema_relationship_hints=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_SCHEMA_RELATIONSHIP_HINTS", True)),
            rag_enable_sql_pattern_hints=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_SQL_PATTERN_HINTS", True)),
            rag_enable_column_ranker=(False if embedded_minimal else getattr(settings, "RAG_ENABLE_COLUMN_RANKER", False)),
            schema_enable_semantic_filtering=(False if embedded_minimal else getattr(settings, "SCHEMA_ENABLE_SEMANTIC_FILTERING", False)),
            schema_enable_value_linking=(False if embedded_minimal else getattr(settings, "SCHEMA_ENABLE_VALUE_LINKING", False)),
            ega_enabled=(False if embedded_minimal else getattr(settings, "EGA_ENABLED", False)),
            ega_rollout_mode=getattr(settings, "EGA_ROLLOUT_MODE", "dual_track"),
            ega_optimization_target=getattr(settings, "EGA_OPTIMIZATION_TARGET", "accuracy"),
            ega_supported_types=getattr(settings, "EGA_SUPPORTED_TYPES", "csv,excel,sqlite"),
            ega_profile_sample_rows=getattr(settings, "EGA_PROFILE_SAMPLE_ROWS", 100),
            ega_max_iterations=getattr(settings, "EGA_MAX_ITERATIONS", 3),
            ega_lambda1=getattr(settings, "EGA_LAMBDA1", 0.3),
            ega_lambda2=getattr(settings, "EGA_LAMBDA2", 0.5),
        )

        # Build and compile graph
        self.graph = build_graph(self.config)
        self.runnable = self.graph.compile()

    def _load_sql_rules(self) -> Dict[str, str]:
        """Load SQL generation rules from YAML."""
        try:
            rules_file = Path(__file__).parent.parent / "templates" / "sql_rules.yaml"
            if not rules_file.exists():
                logger.warning(f"SQL rules file not found: {rules_file}")
                return {}
            with open(rules_file, "r", encoding="utf-8") as f:
                rules = yaml.safe_load(f)
            logger.info("SQL rules loaded successfully")
            return rules
        except Exception as e:
            logger.error(f"Error loading SQL rules: {e}")
            return {}

    async def run(
        self,
        datasource_id: int,
        question: str,
        max_retries: int = 3,
        output_mode: OutputMode = OutputMode.QA,
        data_format: DataFormat = DataFormat.JSON,
        conversation_context: Optional[Dict] = None,
        selected_datasource_ids: Optional[List[int]] = None,
        execution_strategy: Optional[str] = None,
    ) -> dict:
        """Run the agent and return results.

        Args:
            conversation_context: Optional previous turn context dict with keys:
                - previous_question: str
                - previous_sql: str
                - previous_summary: str (optional)
            selected_datasource_ids: Optional list of datasource ids for cross-source
                query. When len > 1, cross_source_mode is set and agent may use
                get_cross_source_schema / execute_cross_source_sql.
            execution_strategy: Optional execution mode hint ("auto" / "ega" / "legacy").
        """
        try:
            initial_state = build_initial_state(
                question=question,
                datasource_id=datasource_id,
                max_retries=max_retries,
                output_mode=output_mode.value,
                data_format=data_format.value,
                conversation_context=conversation_context,
                selected_datasource_ids=selected_datasource_ids,
                execution_strategy=execution_strategy,
            )

            final_state = await asyncio.to_thread(
                self.runnable.invoke,
                initial_state,
                {"recursion_limit": int(getattr(settings, "AGENT_RECURSION_LIMIT", 120))},
            )

            logger.info(
                f"Agent run completed. query_result_data: {final_state.get('query_result_data') is not None}, "
                f"export_data: {final_state.get('export_data') is not None}"
            )

            mode = output_mode.value
            if mode == OutputMode.DATA.value:
                has_export_data = final_state.get("export_data") is not None
                has_query_result = final_state.get("query_result_data") is not None
                success = has_export_data and has_query_result

                if not success:
                    logger.warning(
                        f"Agent run [DATA Mode] - Missing export_data ({has_export_data}) "
                        f"or query_result ({has_query_result})"
                    )

                return {
                    "success": success,
                    "question": question,
                    "sql_history": final_state.get("sql_history", []),
                    "error": final_state.get("error") or (
                        "No query result" if not has_query_result else "No export data"
                    ),
                    "last_sql": final_state.get("last_sql"),
                    "export_data": final_state.get("export_data") or {
                        "format": output_mode.value, "data": [], "columns": [], "row_count": 0,
                    },
                }

            return {
                "success": (
                    final_state.get("error") is None
                    and not (
                        final_state.get("last_sql") is not None
                        and final_state.get("query_result_data") is None
                    )
                ),
                "question": question,
                "thinking": final_state.get("thinking"),
                "final_answer": final_state.get("final_answer"),
                "sql_history": final_state.get("sql_history", []),
                "last_sql": final_state.get("last_sql"),
                "error": final_state.get("error"),
                "query_result_data": final_state.get("query_result_data"),
                "export_data": final_state.get("export_data"),
            }

        except Exception as e:
            logger.error(f"Agent run error: {e}")
            return {
                "success": False,
                "question": question,
                "error": str(e),
                "sql_history": [],
            }
        finally:
            # Cleanup unified engine if it was used for cross-source queries
            from fastapi_app.agents.tools.cross_source_tools import close_unified_engine
            close_unified_engine()

    def stream(self, datasource_id: int, question: str, max_retries: int = 3):
        """Stream agent execution events."""
        initial_state = build_initial_state(
            question=question,
            datasource_id=datasource_id,
            max_retries=max_retries,
        )

        try:
            for event in self.runnable.stream(
                initial_state,
                {"recursion_limit": int(getattr(settings, "AGENT_RECURSION_LIMIT", 120))},
            ):
                node_name = list(event.keys())[0]
                node_output = event[node_name]

                if self.verbose:
                    logger.info(f"Stream event: {node_name}")

                event_data = {
                    "step": node_name,
                    "timestamp": datetime.now().isoformat(),
                    "data": node_output,
                }

                if "sql_history" in node_output and node_output.get("sql_history"):
                    event_data["sql_info"] = {
                        "history_count": len(node_output["sql_history"]),
                        "last_sql": node_output.get("last_sql"),
                        "last_error": node_output.get("last_sql_error"),
                        "retry_count": node_output.get("error_count", 0),
                    }

                yield event_data

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield {
                "step": "error",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            }
