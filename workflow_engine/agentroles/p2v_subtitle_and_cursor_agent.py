"""p2v_subtitle_and_cursor — paper2video 字幕 + cursor 描述（VLM）。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from workflow_engine.state import MainState
from workflow_engine.toolkits.tool_manager import ToolManager
from workflow_engine.logger import get_logger
from workflow_engine.agentroles.cores.base_agent import BaseAgent
from workflow_engine.agentroles.cores.registry import register

log = get_logger(__name__)


@register("p2v_subtitle_and_cursor")
class P2vSubtitleAndCursor(BaseAgent):
    """为每张幻灯片生成配音字幕，并规划光标移动提示（配合讲解逻辑）"""

    @classmethod
    def create(cls, tool_manager: Optional[ToolManager] = None, **kwargs):
        return cls(tool_manager=tool_manager, **kwargs)

    @property
    def role_name(self) -> str:  # noqa: D401
        return "p2v_subtitle_and_cursor"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_p2v_subtitle_and_cursor"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_p2v_subtitle_and_cursor"

    def get_task_prompt_params(self, pre_tool_results: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "language": pre_tool_results.get("video_language", "English"),
        }

    def get_default_pre_tool_results(self) -> Dict[str, Any]:
        return {}

    def update_state_result(
        self,
        state: MainState,
        result: Dict[str, Any],
        pre_tool_results: Dict[str, Any],
    ):
        subtitle_and_cursor_info = result.get("subtitle_and_cursor", "")
        log.info("获取了单张 slide 的 Subtitle and Cursor 信息（前 80 字）: %s", str(subtitle_and_cursor_info)[:80])
        state.subtitle_and_cursor.append(subtitle_and_cursor_info)
        super().update_state_result(state, result, pre_tool_results)
