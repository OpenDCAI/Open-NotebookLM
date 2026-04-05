"""Table Agent agents - agents for table processing workflow.

This module defines agents used in the table processing workflow:
- intent_understanding: Parse user intent into task type and operation
- data_profiling: Profile input tables using ReAct mode
- decompositer: Decompose complex tasks
- generator: Generate Python code for table operations
- debugger: Debug failed code
- summarizer: Summarize results using ReAct mode
"""
from typing import Optional

from workflow_engine.toolkits.tool_manager import ToolManager, get_tool_manager
from workflow_engine.agentroles.cores.base_agent import BaseAgent
from workflow_engine.agentroles.cores.registry import register


@register("intent_understanding")
class IntentUnderstandingAgent(BaseAgent):
    """Agent for parsing user intent into structured task specifications."""

    def __init__(self, tool_manager: Optional[ToolManager] = None, **kwargs):
        super().__init__(tool_manager=tool_manager, **kwargs)
        if self.tool_manager is None:
            self.tool_manager = get_tool_manager()

    @property
    def role_name(self) -> str:
        return "intent_understanding"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_intent_understanding"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_intent_understanding"


@register("data_profiling")
class DataProfilingAgent(BaseAgent):
    """Agent for profiling input tables using ReAct mode."""

    def __init__(self, tool_manager: Optional[ToolManager] = None, **kwargs):
        super().__init__(tool_manager=tool_manager, **kwargs)
        if self.tool_manager is None:
            self.tool_manager = get_tool_manager()

    @property
    def role_name(self) -> str:
        return "data_profiling"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_data_profiling"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_data_profiling"


@register("decompositer")
class DecompositerAgent(BaseAgent):
    """Agent for decomposing complex tasks into sub-tasks."""

    def __init__(self, tool_manager: Optional[ToolManager] = None, **kwargs):
        super().__init__(tool_manager=tool_manager, **kwargs)
        if self.tool_manager is None:
            self.tool_manager = get_tool_manager()

    @property
    def role_name(self) -> str:
        return "decompositer"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_decompositer"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_decompositer"


@register("generator")
class GeneratorAgent(BaseAgent):
    """Agent for generating Python code for table operations."""

    def __init__(self, tool_manager: Optional[ToolManager] = None, **kwargs):
        super().__init__(tool_manager=tool_manager, **kwargs)
        if self.tool_manager is None:
            self.tool_manager = get_tool_manager()

    @property
    def role_name(self) -> str:
        return "generator"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_generator"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_generator"


@register("debugger")
class DebuggerAgent(BaseAgent):
    """Agent for debugging failed code."""

    def __init__(self, tool_manager: Optional[ToolManager] = None, **kwargs):
        super().__init__(tool_manager=tool_manager, **kwargs)
        if self.tool_manager is None:
            self.tool_manager = get_tool_manager()

    @property
    def role_name(self) -> str:
        return "debugger"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_debugger"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_debugger"


@register("summarizer")
class SummarizerAgent(BaseAgent):
    """Agent for summarizing results using ReAct mode."""

    def __init__(self, tool_manager: Optional[ToolManager] = None, **kwargs):
        super().__init__(tool_manager=tool_manager, **kwargs)
        if self.tool_manager is None:
            self.tool_manager = get_tool_manager()

    @property
    def role_name(self) -> str:
        return "summarizer"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_summarizer"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_summarizer"
