"""
OpenAI-compatible ChatModel implementation without langchain-openai.

Why:
- This repo previously depended on `langchain-openai`, but the installed
  version can drift and break with `langchain-core` (ImportError at import time).
- The agent pipeline only needs a small subset of the ChatModel API:
  - `.invoke([...messages...])`
  - `.bind_tools([...tools...])` to enable tool calling

This module provides a minimal, stable implementation backed by the official
`openai` python client.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Union

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
try:
    from langchain_core.pydantic_v1 import Field
except ModuleNotFoundError:
    from pydantic import Field
from langchain_core.utils.function_calling import convert_to_openai_tool

logger = logging.getLogger(__name__)


def _build_http_client(timeout: int) -> httpx.Client:
    """
    Embedded SQLBot should not inherit host/system proxy settings by default.
    The desktop environment may route localhost/OpenAI-compatible traffic
    through a proxy and cause opaque connection failures.
    """
    return httpx.Client(timeout=timeout, trust_env=False)


def _to_openai_messages(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, ToolMessage):
            # OpenAI expects tool messages to include tool_call_id.
            payload = {"role": "tool", "content": m.content}
            tool_call_id = getattr(m, "tool_call_id", None) or m.additional_kwargs.get("tool_call_id")
            if tool_call_id:
                payload["tool_call_id"] = tool_call_id
            out.append(payload)
        elif isinstance(m, AIMessage):
            payload: Dict[str, Any] = {"role": "assistant", "content": m.content or ""}
            # Preserve tool calls if present (for iterative tool use loops).
            if getattr(m, "tool_calls", None):
                tool_calls = []
                for tc in m.tool_calls:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    tool_calls.append(
                        {
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args or {}, ensure_ascii=False),
                            },
                        }
                    )
                payload["tool_calls"] = tool_calls
            out.append(payload)
        else:
            # Fallback: treat unknown message types as user content.
            out.append({"role": "user", "content": getattr(m, "content", str(m))})
    return out


def _parse_tool_calls(msg: Any) -> List[Dict[str, Any]]:
    tool_calls = []
    raw = getattr(msg, "tool_calls", None) or []
    for tc in raw:
        try:
            tc_id = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else None)
            fn = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None) or {}
            name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
            args_str = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else None) or "{}"
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
            except Exception:
                args = {}
            if name:
                tool_calls.append({"id": tc_id or "", "name": name, "args": args})
        except Exception:
            continue
    return tool_calls


class OpenAICompatChatModel(BaseChatModel):
    """
    Minimal OpenAI-compatible chat model (tool-calling aware), implemented with the
    official `openai` client and `langchain-core`'s BaseChatModel (pydantic v1).
    """

    model: str
    api_key: str
    base_url: Optional[str] = None
    temperature: float = 0.0
    timeout: int = 60
    max_tokens: Optional[int] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)
    bound_tools: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "openai_compat"

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], BaseTool]],
        **kwargs: Any,
    ) -> "OpenAICompatChatModel":
        converted: List[Dict[str, Any]] = []
        for t in tools:
            if isinstance(t, dict):
                converted.append(t)
            else:
                try:
                    converted.append(convert_to_openai_tool(t))
                except Exception as e:
                    logger.warning(f"Tool conversion failed for {t}: {e}")
        # Avoid pydantic BaseModel.copy(): it respects Field(exclude=True) on BaseLanguageModel
        # and can drop critical inherited fields like `callbacks`.
        data = dict(self.__dict__)
        data["bound_tools"] = converted
        return self.__class__(**data)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        from openai import OpenAI

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client_kwargs["http_client"] = _build_http_client(self.timeout)
        client = OpenAI(**client_kwargs)

        req: Dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "temperature": self.temperature,
        }
        if self.bound_tools:
            req["tools"] = list(self.bound_tools)
            req["tool_choice"] = "auto"
        if self.max_tokens is not None:
            req["max_tokens"] = self.max_tokens
        if stop:
            req["stop"] = stop
        if self.extra_params:
            req.update(self.extra_params)
        req.update(kwargs)

        resp = client.chat.completions.create(**req, timeout=self.timeout)
        choice = resp.choices[0]
        msg = choice.message
        content = getattr(msg, "content", "") or ""

        tool_calls = _parse_tool_calls(msg)

        usage = getattr(resp, "usage", None)
        token_usage = None
        if usage is not None:
            token_usage = {
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }

        # NOTE: In some langchain-core versions, AIMessage.tool_calls is a list field
        # and does not accept None (pydantic v1). Use an empty list when absent.
        ai = AIMessage(
            content=content,
            tool_calls=tool_calls,
            response_metadata={"token_usage": token_usage} if token_usage else {},
        )

        gen = ChatGeneration(message=ai, generation_info={"finish_reason": choice.finish_reason})
        return ChatResult(generations=[gen])


class AzureOpenAICompatChatModel(OpenAICompatChatModel):
    azure_endpoint: Optional[str] = None
    api_version: Optional[str] = None

    @property
    def _llm_type(self) -> str:
        return "azure_openai_compat"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        from openai import AzureOpenAI

        endpoint = self.azure_endpoint or self.base_url
        if not endpoint:
            raise ValueError("Azure OpenAI requires azure_endpoint/base_url")

        api_version = (
            self.api_version
            or (self.extra_params or {}).get("api_version")
            or os.getenv("AZURE_OPENAI_API_VERSION")
        )
        if not api_version:
            raise ValueError("Azure OpenAI requires api_version (set AZURE_OPENAI_API_VERSION or extra_params.api_version)")

        client = AzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            http_client=_build_http_client(self.timeout),
        )

        req: Dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "temperature": self.temperature,
        }
        if self.bound_tools:
            req["tools"] = list(self.bound_tools)
            req["tool_choice"] = "auto"
        if self.max_tokens is not None:
            req["max_tokens"] = self.max_tokens
        if stop:
            req["stop"] = stop
        if self.extra_params:
            req.update(self.extra_params)
        req.update(kwargs)

        resp = client.chat.completions.create(**req, timeout=self.timeout)
        choice = resp.choices[0]
        msg = choice.message
        content = getattr(msg, "content", "") or ""
        tool_calls = _parse_tool_calls(msg)

        usage = getattr(resp, "usage", None)
        token_usage = None
        if usage is not None:
            token_usage = {
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }

        ai = AIMessage(
            content=content,
            tool_calls=tool_calls,
            response_metadata={"token_usage": token_usage} if token_usage else {},
        )

        gen = ChatGeneration(message=ai, generation_info={"finish_reason": choice.finish_reason})
        return ChatResult(generations=[gen])
