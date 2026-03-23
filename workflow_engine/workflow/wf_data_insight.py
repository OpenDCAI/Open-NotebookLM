"""
Data Insight Discovery Workflow
Integrates DM insight framework for multi-dataset analysis.
"""
from __future__ import annotations
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Any

from workflow_engine.workflow.registry import register
from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.logger import get_logger
from workflow_engine.state import DataInsightState
from workflow_engine.utils import get_project_root

log = get_logger(__name__)


@register("data_insight")
def create_data_insight_graph() -> GenericGraphBuilder:
    """
    Workflow for multi-dataset insight discovery using DM framework.

    Steps:
    1. Initialize paths and validate inputs
    2. Prepare data folder (copy uploaded files)
    3. Run DM insight analysis
    """
    builder = GenericGraphBuilder(state_model=DataInsightState, entry_point="_start_")

    def _start_(state: DataInsightState) -> DataInsightState:
        """Initialize paths and validate inputs."""
        if not state.request.file_ids:
            state.request.file_ids = []

        # Create output directory
        if not state.result_path:
            project_root = get_project_root()
            ts = int(time.time())
            email = getattr(state.request, 'email', None) or 'default'
            output_dir = project_root / "outputs" / "data_insights" / email / f"{ts}_insight"
            output_dir.mkdir(parents=True, exist_ok=True)
            state.result_path = str(output_dir)
            log.info(f"Output directory: {state.result_path}")

        return state

    async def prepare_data_node(state: DataInsightState) -> DataInsightState:
        """Copy uploaded files to analysis folder."""
        if not state.request.file_ids:
            log.warning("No files provided for analysis")
            return state

        # Create data folder
        data_folder = Path(state.result_path) / "data"
        data_folder.mkdir(exist_ok=True)

        # Copy files
        for file_path in state.request.file_ids:
            src = Path(file_path)
            if src.exists():
                dst = data_folder / src.name
                shutil.copy2(src, dst)
                log.info(f"Copied {src.name} to analysis folder")

        # Create meta-info.json if custom goal provided
        if state.request.analysis_goal:
            import json
            meta_path = Path(state.result_path) / "meta-info.json"
            meta_path.write_text(json.dumps({
                "goal": state.request.analysis_goal
            }, ensure_ascii=False, indent=2))

        return state

    async def analyze_node(state: DataInsightState) -> DataInsightState:
        """Run DM insight analysis."""
        from workflow_engine.toolkits.insight_tool.insight_wrapper import InsightToolkit

        data_folder = Path(state.result_path) / "data"

        try:
            # Initialize toolkit with API credentials
            toolkit = InsightToolkit(
                model_name=state.request.model,
                api_key=state.request.api_key,
                base_url=state.request.chat_api_url,
                base_savedir=state.result_path,
                temperature=0.1
            )

            # Run analysis
            result = toolkit.analyze_folder(
                data_folder=str(data_folder),
                output_mode=state.request.output_mode
            )

            # Extract results
            state.synthesized_insights = result.get("synthesized_insights", [])
            state.raw_insights = result.get("raw_insights", [])
            state.summary = result.get("summary", "")
            state.detailed_appendix = result.get("detailed_appendix", {})

            log.info(f"Analysis complete: {len(state.synthesized_insights)} insights")

        except Exception as e:
            log.error(f"Insight analysis failed: {e}", exc_info=True)
            state.summary = f"Analysis failed: {str(e)}"

        return state

    # Build graph
    nodes = {
        "_start_": _start_,
        "prepare_data": prepare_data_node,
        "analyze": analyze_node,
        "_end_": lambda s: s
    }

    edges = [
        ("_start_", "prepare_data"),
        ("prepare_data", "analyze"),
        ("analyze", "_end_")
    ]

    builder.add_nodes(nodes).add_edges(edges)
    return builder
