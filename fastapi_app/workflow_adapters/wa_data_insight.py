"""
Data Insight Workflow Adapter
Mandatory isolation layer between Service and Workflow.
"""
from __future__ import annotations
from typing import Dict, Any
from workflow_engine.state import DataInsightState, DataInsightRequest
from workflow_engine.workflow.registry import RuntimeRegistry
from workflow_engine.logger import get_logger

log = get_logger(__name__)


class DataInsightAdapter:
    """
    Adapter for data insight workflow.
    Converts API request dict to workflow state and executes workflow.
    """

    async def execute(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute data insight workflow.

        Args:
            request_data: Dict with keys:
                - file_ids: List[str]
                - model: str
                - api_key: str
                - chat_api_url: str
                - output_mode: str
                - analysis_goal: Optional[str]
                - language: str
                - email: Optional[str]

        Returns:
            Dict with keys:
                - status: "success" | "error"
                - synthesized_insights: List[str]
                - raw_insights: List[str]
                - summary: str
                - detailed_appendix: Dict (if detailed mode)
                - result_path: str
                - error: str (if error)
        """
        try:
            # Build workflow request
            wf_request = DataInsightRequest(
                file_ids=request_data.get("file_ids", []),
                output_mode=request_data.get("output_mode", "concise"),
                analysis_goal=request_data.get("analysis_goal"),
                model=request_data.get("model", "deepseek-v3.2"),
                api_key=request_data.get("api_key", ""),
                chat_api_url=request_data.get("chat_api_url", ""),
                language=request_data.get("language", "en")
            )

            # Add email if provided
            if request_data.get("email"):
                wf_request.email = request_data["email"]

            # Build workflow state
            state = DataInsightState(request=wf_request)

            # Execute workflow
            log.info("Executing data_insight workflow")
            factory = RuntimeRegistry.get("data_insight")
            builder = factory()
            graph = builder.build()

            result_state = await graph.ainvoke(state)

            # Handle both dict and dataclass returns
            if isinstance(result_state, dict):
                # Result is a dict
                synthesized_insights = result_state.get("synthesized_insights", [])
                raw_insights = result_state.get("raw_insights", [])
                summary = result_state.get("summary", "")
                detailed_appendix = result_state.get("detailed_appendix", {})
                result_path = result_state.get("result_path", "")
            else:
                # Result is a DataInsightState object
                synthesized_insights = result_state.synthesized_insights
                raw_insights = result_state.raw_insights
                summary = result_state.summary
                detailed_appendix = result_state.detailed_appendix
                result_path = result_state.result_path

            # Format response
            return {
                "status": "success",
                "synthesized_insights": synthesized_insights,
                "raw_insights": raw_insights,
                "summary": summary,
                "detailed_appendix": detailed_appendix,
                "result_path": result_path
            }

        except Exception as e:
            log.error(f"Adapter execution failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "synthesized_insights": [],
                "raw_insights": [],
                "summary": f"Analysis failed: {str(e)}",
                "detailed_appendix": {},
                "result_path": ""
            }
