"""Custom Strategies for Table Processing Workflow.

This module provides custom execution strategies that extend the base
ExecutionStrategy class. These strategies are designed specifically for
table processing tasks.

Import this module to auto-register the custom strategies:
    from workflow_engine.workflow.wf_table_strategy import TableReActStrategy, TableReactConfig

"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, List, TYPE_CHECKING

from workflow_engine.logger import get_logger
from workflow_engine.agentroles.cores.strategies import ExecutionStrategy, StrategyFactory
from workflow_engine.table_agent_utils import (
    safe_exec_code,
    parse_react_output,
    observation_to_message,
    truncate_for_log,
)

if TYPE_CHECKING:
    from workflow_engine.agentroles.cores.base_agent import BaseAgent
    from workflow_engine.state import MainState

log = get_logger(__name__)


# ==================== 自定义配置类 ====================

@dataclass
class TableReactConfig:
    """
    Table ReAct 模式配置 - 专门用于表格处理任务

    这种模式结合了 ReAct 推理框架和表格处理能力：
    - 通过 Python 代码执行 ACTION
    - 代码直接操作输入表格文件
    - 支持轨迹追踪和执行时间统计

    Example:
        >>> config = TableReactConfig(
        ...     model_name="gpt-4",
        ...     max_retries=5,
        ...     temperature=0.1
        ... )
    """
    # 策略模式名称
    mode: str = "table_react"

    # 核心参数
    model_name: Optional[str] = None
    chat_api_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 65536

    # 工具相关
    tool_mode: str = "auto"
    tool_manager: Optional[Any] = None

    # 解析器相关
    parser_type: str = "json"
    parser_config: Optional[Dict[str, Any]] = None

    # 消息历史
    ignore_history: bool = True
    message_history: Optional[Any] = None

    # TableReAct 特有配置
    max_retries: int = 3
    validators: Optional[List[Any]] = None


# ==================== 自定义策略 ====================

class TableReActStrategy(ExecutionStrategy):
    """
    Table ReAct Strategy - 基于 ReAct 框架的表格处理策略

    与普通 ReactStrategy 不同，本策略专注于表格处理任务：
    - 通过 Python 代码执行 ACTION
    - 代码直接操作输入表格文件
    - 支持轨迹追踪和执行时间统计
    - 返回标准化的结果格式 {answer, react_trace, execution_time}

    流程:
        THINK → ACTION(代码) → OBSERVE → ... → ANSWER
    """

    def __init__(self, agent: "BaseAgent", config: TableReactConfig):
        self.agent = agent
        self.config = config
        # 从 config 中同步属性到 agent
        if config.model_name:
            self.agent.model_name = config.model_name
        if config.temperature is not None:
            self.agent.temperature = config.temperature
        if config.max_tokens:
            self.agent.max_tokens = config.max_tokens
        if config.parser_type:
            self.agent.parser_type = config.parser_type
        if config.chat_api_url:
            self.agent.chat_api_url = config.chat_api_url

    async def execute(self, state: "MainState", **kwargs) -> Dict[str, Any]:
        log.info(f"[TableReActStrategy] 执行 {self.agent.role_name}，最大重试: {self.config.max_retries}")

        pre_tool_results = await self.agent.execute_pre_tools(state)
        return await self._process_table_react_mode(state, pre_tool_results)

    async def _process_table_react_mode(
        self,
        state: "MainState",
        pre_tool_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Table ReAct 模式处理

        循环调用 LLM，执行 THINK → ACTION(代码) → OBSERVE 的模式，
        直到获得最终结果或达到最大步骤限制。

        Args:
            state: 当前状态对象
            pre_tool_results: 前置工具执行结果

        Returns:
            Dict[str, Any]: 包含数据分析结果或错误信息的字典
        """
        log.info("🔍🔍 开始 TableReAct 模式处理")

        messages = self.agent.build_messages(state, pre_tool_results)
        react_trace = []
        execution_time = 0.0

        for step in range(1, self.config.max_retries + 1):
            log.info(f"➡️ ReAct Step {step}/{self.config.max_retries}")

            llm = self.agent.create_llm(state, bind_post_tools=False)
            response = await llm.ainvoke(messages)

            # 记录 token 使用
            self._track_token_usage(state, messages, response)

            raw_output = response.content.strip()
            log.debug(f"Raw LLM Output:\n{raw_output}")

            # 添加到消息历史
            messages.append({"role": "assistant", "content": raw_output})

            # 解析 LLM 输出
            parsed = parse_react_output(raw_output)

            # 记录 THINK 步骤
            for tb in parsed["thinks"]:
                react_trace.append({"step": len(react_trace) + 1, "type": "think", "content": tb})
                log.info(f"💭 THINK: {tb}")

            # 检查是否有最终答案
            if parsed["answer_obj"] is not None:
                answer = parsed["answer_obj"]
                log.info("🎯 最终答案已生成！")
                break

            # 执行 ACTION 步骤（Python 代码）
            code = parsed["action_code"]
            if not code:
                obs = {"status": "error", "stderr": "未解析到 ACTION 或 ANSWER."}
            else:
                log.debug(f"🔧 执行代码 ({len(code)} chars)")
                log.debug(f"Code Content:\n{code}")
                obs = self._execute_table_code(state, code)
                execution_time += obs.get("exec_time_sec", 0.0)

            # 记录 OBSERVATION 步骤
            react_trace.append({
                "step": len(react_trace) + 1,
                "type": "observation",
                "content": json.dumps(obs, ensure_ascii=False)
            })
            status_icon = "✅" if obs.get("status") == "success" else "❌"
            log.info(f"{status_icon} OBS: {truncate_for_log(obs.get('stdout', obs.get('stderr', '')))}")

            # 添加观察结果到消息
            messages.append({
                "role": "user",
                "content": observation_to_message(obs) + "你的代码必须是完全自包含的，可以独立执行。不要依赖之前的上下文或代码片段。"
            })

        else:
            answer = {"error": "max_steps_reached"}

        return {
            "answer": answer,
            "react_trace": react_trace,
            "execution_time": execution_time,
        }

    def _execute_table_code(self, state: "MainState", code: str) -> Dict[str, Any]:
        """
        执行表格处理代码

        Args:
            state: 当前状态对象
            code: 要执行的 Python 代码

        Returns:
            Dict[str, Any]: 执行结果 {status, stdout/stderr, exec_time_sec}
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            script_path = Path(tmp_dir) / "react_step.py"
            script_path.write_text(code, encoding="utf-8")

            try:
                stdout, exec_time = safe_exec_code(
                    py_path=script_path,
                    output_path=str(Path(tmp_dir) / "output"),
                    input_path=state.get("raw_table_paths", []),
                )
                return {
                    "status": "success",
                    "stdout": stdout,
                    "exec_time_sec": round(exec_time, 2)
                }
            except Exception as e:
                log.error(f"💥 代码执行失败: {e}")
                return {"status": "error", "stderr": str(e)}

    def _track_token_usage(
        self,
        state: "MainState",
        messages: list,
        response: Any
    ) -> None:
        """记录 token 使用情况"""
        try:
            from workflow_engine.llm.text import extract_token_usage_from_response
            token_usage = extract_token_usage_from_response(response)
            if token_usage:
                log.info(f"Token 使用: {token_usage}")

            if hasattr(state, "llm_tracker") and state.llm_tracker:
                state.llm_tracker(
                    model=self.agent.model_name,
                    messages=[{"role": msg.get("role", ""), "content": msg.get("content", "")} for msg in messages],
                    response=response,
                    token_usage=token_usage,
                    temperature=self.agent.temperature
                )
        except Exception as e:
            log.debug(f"Token 追踪失败: {e}")


# ===== 注册自定义策略到工厂 =====
StrategyFactory.register("table_react", TableReActStrategy)
log.info("✓ TableReActStrategy 已自动注册")


def create_table_react_agent(name: str, model_name: str, max_retries: int = 3, **kwargs):
    """
    创建使用 TableReActStrategy 的 Agent

    这种策略专门用于表格处理任务，通过 Python 代码执行 ACTION。

    Args:
        name: Agent 名称
        model_name: 模型名称
        max_retries: 最大重试次数
        **kwargs: 其他配置参数

    Returns:
        Agent 实例
    """
    from workflow_engine.agentroles import create_agent

    config = TableReactConfig(
        model_name=model_name,
        max_retries=max_retries,
        temperature=kwargs.get("temperature", 0.1),
        max_tokens=kwargs.get("max_tokens", 20480),
        parser_type=kwargs.get("parser_type", "json"),
        chat_api_url=kwargs.get("chat_api_url"),
        tool_mode=kwargs.get("tool_mode", "auto"),
        ignore_history=kwargs.get("ignore_history", True),
    )
    return create_agent(name, config=config)


if __name__ == "__main__":
    print("已注册的策略:", list(StrategyFactory._strategies.keys()))
