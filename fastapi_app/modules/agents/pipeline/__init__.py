"""
Pipeline module - SQLBot Agent's LangGraph pipeline components.

Refactored from sqlbot_agent.py (1350 lines) into modular components:
- state.py: AgentState definition and enums
- config.py: PipelineConfig shared across nodes
- graph.py: LangGraph graph construction
- nodes/: Individual node implementations
"""
from .state import AgentState, OutputMode, DataFormat
from .config import PipelineConfig

__all__ = ["AgentState", "OutputMode", "DataFormat", "PipelineConfig"]
