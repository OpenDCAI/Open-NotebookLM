"""
Thin wrapper around DM InsightEntry for Open-NotebookLM integration.
Handles API key passing and result formatting.
"""
from pathlib import Path
from typing import Dict, Any, Optional
import sys
import os

# Add insight_tool directory to path so dm_components can be imported as a package
_insight_tool_path = os.path.dirname(os.path.abspath(__file__))
if _insight_tool_path not in sys.path:
    sys.path.insert(0, _insight_tool_path)

from workflow_engine.logger import get_logger

log = get_logger(__name__)


class InsightToolkit:
    """Wrapper for DM insight discovery functionality."""

    def __init__(self,
                 model_name: str = "deepseek-v3.2",
                 api_key: str = "",
                 base_url: str = "",
                 base_savedir: str = "./outputs/insights",
                 temperature: float = 0.1):
        """
        Initialize with explicit API credentials.

        Args:
            model_name: LLM model name
            api_key: API key for LLM
            base_url: Base URL for LLM API
            base_savedir: Output directory
            temperature: LLM temperature
        """
        from dm_components.insight_entry import InsightEntry

        self.api_key = api_key
        self.base_url = base_url

        # Initialize DM InsightEntry
        self.insight_entry = InsightEntry(
            model_name=model_name,
            base_savedir=base_savedir,
            temperature=temperature,
            n_retries=1,
            branch_depth=1,
            max_questions=1,
            default_output_mode="concise",
            api_key=api_key,
            base_url=base_url
        )

        log.info(f"InsightToolkit initialized: model={model_name}")

    def analyze_folder(self,
                      data_folder: str,
                      output_mode: str = "concise") -> Dict[str, Any]:
        """
        Analyze all datasets in a folder.

        Args:
            data_folder: Path to folder with data files
            output_mode: "concise" or "detailed"

        Returns:
            {
                "synthesized_insights": List[str],
                "raw_insights": List[str],
                "summary": str,
                "detailed_appendix": Dict
            }
        """
        log.info(f"Analyzing folder: {data_folder}")

        try:
            result = self.insight_entry.analyze_folder(
                data_folder=data_folder,
                use_meta_goal=True,
                output_mode=output_mode,
                include_background=True
            )

            log.info(f"Analysis complete: {len(result.get('synthesized_insights', []))} insights")
            return result

        except Exception as e:
            log.error(f"Analysis failed: {e}", exc_info=True)
            return {
                "synthesized_insights": [],
                "raw_insights": [],
                "summary": f"Analysis failed: {str(e)}",
                "detailed_appendix": {}
            }
