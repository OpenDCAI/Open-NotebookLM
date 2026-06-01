"""p2v_refine_subtitle_and_cursor — 在用户编辑长句后切句并补充 cursor。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from workflow_engine.state import MainState
from workflow_engine.toolkits.tool_manager import ToolManager
from workflow_engine.logger import get_logger
from workflow_engine.agentroles.cores.base_agent import BaseAgent
from workflow_engine.agentroles.cores.registry import register

log = get_logger(__name__)


def parse_subtitle_and_cursor_result(result: Dict[str, Any]) -> Optional[str]:
    """从 LLM 返回中解析 refine_subtitle_and_cursor 字符串。"""
    if not result:
        return None
    value = result.get("refine_subtitle_and_cursor")
    if isinstance(value, str):
        return value
    if value is not None:
        return None
    raw = result.get("raw")
    if not isinstance(raw, str):
        return None
    raw_text = raw.strip()
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            value = parsed.get("refine_subtitle_and_cursor")
            if isinstance(value, str):
                return value
    except json.JSONDecodeError:
        pass
    match = re.search(
        r'"refine_subtitle_and_cursor"\s*:\s*"(.*?)"\s*}',
        raw_text,
        re.DOTALL,
    )
    if match:
        return match.group(1)
    return None


@register("p2v_refine_subtitle_and_cursor")
class P2vRefineSubtitleAndCursor(BaseAgent):
    """对每页脚本切句并生成 cursor 描述。"""

    @classmethod
    def create(cls, tool_manager: Optional[ToolManager] = None, **kwargs):
        return cls(tool_manager=tool_manager, **kwargs)

    @property
    def role_name(self) -> str:  # noqa: D401
        return "p2v_refine_subtitle_and_cursor"

    @property
    def system_prompt_template_name(self) -> str:
        return "system_prompt_for_p2v_refine_subtitle_and_cursor"

    @property
    def task_prompt_template_name(self) -> str:
        return "task_prompt_for_p2v_refine_subtitle_and_cursor"

    def get_task_prompt_params(self, pre_tool_results: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "sentence": pre_tool_results.get("tmp_sentence", ""),
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
        subtitle_and_cursor_info = parse_subtitle_and_cursor_result(result)
        if subtitle_and_cursor_info is not None:
            log.info(
                "获取了单张 slide 的 Refine Subtitle and Cursor（前 80 字）: %s",
                subtitle_and_cursor_info[:80],
            )
            state.subtitle_and_cursor.append(subtitle_and_cursor_info)
        else:
            log.warning("LLM 返回格式不符合 refine_subtitle_and_cursor，未写入 state")
        super().update_state_result(state, result, pre_tool_results)
