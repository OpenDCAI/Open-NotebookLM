from typing import List, Dict, Any
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from .base import BaseLLMCaller
from workflow_engine.logger import get_logger

log = get_logger(__name__)


class TextLLMCaller(BaseLLMCaller):
    """文本LLM调用器 - 原有实现

    支持通过 summary() 方法获取调用统计信息，
    也支持像函数一样调用：result = await caller(messages)。
    """

    def __init__(self, state, model_name: str = None, temperature: float = 0.0, max_tokens: int = 10000):
        super().__init__(
            state=state,
            model_name=model_name or getattr(state, 'model', None) or state.request.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._input_tokens = 0
        self._output_tokens = 0
        self._completion_time_sec = 0.0
        self._total_cost_usd = 0.0

    async def call(self, messages: List[BaseMessage], bind_post_tools: bool = False) -> AIMessage:
        """调用 LLM"""
        import time
        start_time = time.time()

        log.info(f"TextLLM调用，模型: {self.model_name}")

        llm = ChatOpenAI(
            openai_api_base=self.state.request.chat_api_url,
            openai_api_key=self.state.request.api_key,
            model_name=self.model_name,
            temperature=self.temperature,
        )

        # 绑定工具（如果需要）
        if bind_post_tools and self.tool_manager:
            from langchain_core.tools import Tool
            tools = self.tool_manager.get_post_tools("current_role")
            if tools:
                llm = llm.bind_tools(tools, tool_choice=self.tool_mode)
                log.info(f"为LLM绑定了 {len(tools)} 个工具")

        response = await llm.ainvoke(messages)

        # 统计
        elapsed = time.time() - start_time
        self._completion_time_sec += elapsed
        # 估算 token（简化，实际应该从 response 获取 usage 信息）
        self._input_tokens += self._estimate_tokens(messages)
        self._output_tokens += self._estimate_tokens([response.content]) if hasattr(response, 'content') else 0

        return response

    async def __call__(self, messages) -> AIMessage:
        """支持像函数一样调用"""
        if isinstance(messages, list):
            return await self.call(messages)
        elif isinstance(messages, dict):
            # 支持传入消息字典列表
            converted = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    converted.append({"type": "system", "content": content})
                elif role == "user":
                    converted.append({"type": "user", "content": content})
                elif role == "assistant":
                    converted.append({"type": "ai", "content": content})
            # 使用 LangChain 消息
            from langchain_core.messages import convert_to_messages
            langchain_msgs = convert_to_messages(converted)
            return await self.call(langchain_msgs)
        else:
            raise ValueError(f"Invalid messages type: {type(messages)}")

    def summary(self) -> Dict[str, Any]:
        """返回调用统计摘要"""
        return {
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "completion_time_sec": self._completion_time_sec,
            "total_cost_usd": self._total_cost_usd,
        }

    def _estimate_tokens(self, messages) -> int:
        """简单估算 token 数量"""
        if isinstance(messages, str):
            return len(messages) // 4
        total = 0
        for msg in messages:
            if isinstance(msg, str):
                total += len(msg) // 4
            elif hasattr(msg, 'content'):
                total += len(str(msg.content)) // 4
            elif isinstance(msg, dict):
                total += len(str(msg.get('content', ''))) // 4
        return total