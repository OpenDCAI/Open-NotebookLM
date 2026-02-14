"""
完整集成阿里 DeepResearch 到 Open-NotebookLM
使用内部 deep_research 模块
"""
import os
import json
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path

from dataflow_agent.logger import get_logger
from fastapi_app.deep_research.react_agent import MultiTurnReactAgent
from qwen_agent.llm.schema import Message

log = get_logger(__name__)


class DeepResearchIntegration:
    """完整集成阿里 DeepResearch"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        max_iterations: Optional[int] = None,
        serper_key: Optional[str] = None,
        jina_keys: Optional[str] = None,
        dashscope_key: Optional[str] = None,
        sandbox_endpoints: Optional[str] = None,
    ):
        # 配置参数（优先使用传入参数，其次使用环境变量）
        self.model_name = model_name or os.getenv("DEEP_RESEARCH_MODEL", "qwen-plus")
        self.api_base = api_base or os.getenv("DEEP_RESEARCH_API_BASE", "http://127.0.0.1:6001")
        self.api_key = api_key or os.getenv("DEEP_RESEARCH_API_KEY", "EMPTY")
        self.max_iterations = max_iterations or int(os.getenv("DEEP_RESEARCH_MAX_ITERATIONS", "50"))

        # 工具配置（优先使用传入参数，其次使用环境变量）
        self.serper_key = serper_key or os.getenv("SERPER_KEY_ID", os.getenv("SERPER_API_KEY", ""))
        self.jina_keys = jina_keys or os.getenv("JINA_API_KEYS", "")
        self.dashscope_key = dashscope_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.sandbox_endpoints = sandbox_endpoints or os.getenv("SANDBOX_FUSION_ENDPOINT", "")

        # 调试日志
        log.info(f"[DeepResearchIntegration] 初始化配置:")
        log.info(f"  - model_name: {self.model_name}")
        log.info(f"  - api_base: {self.api_base}")
        log.info(f"  - serper_key: {'***' if self.serper_key else 'None'} (length: {len(self.serper_key) if self.serper_key else 0})")
        log.info(f"  - jina_keys: {'***' if self.jina_keys else 'None'}")
        log.info(f"  - max_iterations: {self.max_iterations}")

    async def run_research(
        self,
        query: str,
        max_iterations: Optional[int] = None,
        temperature: float = 0.85,
        presence_penalty: float = 1.1,
    ) -> Dict[str, Any]:
        """
        运行完整的 DeepResearch 推理

        Args:
            query: 研究问题
            max_iterations: 最大迭代次数
            temperature: 采样温度
            presence_penalty: 存在惩罚

        Returns:
            {
                "success": bool,
                "query": str,
                "answer": str,
                "messages": List[Dict],
                "sources": List[Dict],
                "termination": str,
                "iterations": int
            }
        """
        log.info(f"[DeepResearch] 开始研究: {query}")

        try:
            # 检查必要的配置
            if not self.serper_key:
                raise ValueError("SERPER_KEY_ID 或 SERPER_API_KEY 未配置")

            # ⚠️ 重要：在创建 Agent 之前设置环境变量
            # 因为工具在模块加载时读取环境变量
            import os
            os.environ["SERPER_KEY_ID"] = self.serper_key
            if self.jina_keys:
                os.environ["JINA_API_KEYS"] = self.jina_keys
            if self.dashscope_key:
                os.environ["DASHSCOPE_API_KEY"] = self.dashscope_key

            # 配置 LLM
            llm_config = {
                "model": self.model_name,
                "api_base": self.api_base,
                "api_key": self.api_key,
                "generate_cfg": {
                    "temperature": temperature,
                    "top_p": 0.95,
                    "presence_penalty": presence_penalty,
                    "max_tokens": 10000,
                }
            }

            # 创建 Agent
            agent = MultiTurnReactAgent(llm=llm_config)

            # 设置最大迭代次数
            max_iter = max_iterations or self.max_iterations

            # 运行推理（在线程池中运行，避免阻塞）
            result = await asyncio.to_thread(
                self._run_agent_sync,
                agent,
                query,
                max_iter
            )

            log.info(f"[DeepResearch] 完成研究，迭代次数: {result['iterations']}")

            return result

        except ImportError as e:
            log.error(f"[DeepResearch] 导入失败: {e}")
            return {
                "success": False,
                "query": query,
                "answer": "",
                "messages": [],
                "sources": [],
                "error": f"DeepResearch 模块导入失败: {str(e)}",
                "termination": "import_error"
            }
        except Exception as e:
            log.error(f"[DeepResearch] 执行失败: {e}")
            return {
                "success": False,
                "query": query,
                "answer": "",
                "messages": [],
                "sources": [],
                "error": str(e),
                "termination": "error"
            }

    def _run_agent_sync(self, agent, query, max_iterations):
        """同步运行 Agent（在线程池中调用）"""
        try:
            # 构造 data 参数，符合原始 _run 方法的要求
            # 传递完整的 API base URL 而不是端口号
            data = {
                "item": {
                    "question": query,
                    "answer": ""  # 我们不知道答案，留空
                },
                "planning_port": self.api_base  # 传递完整的 API base URL
            }

            log.info(f"[DeepResearch] 调用 Agent，API base: {self.api_base}, model: {self.model_name}")

            # 调用 Agent 的 _run 方法
            result = agent._run(
                data=data,
                model=self.model_name
            )

            # 解析结果
            messages = result.get("messages", [])
            answer = result.get("prediction", "")
            termination = result.get("termination", "unknown")

            # 提取来源
            sources = self._extract_sources_from_messages(messages)

            return {
                "success": True,
                "query": query,
                "answer": answer,
                "messages": messages,
                "sources": sources,
                "termination": termination,
                "iterations": len([m for m in messages if m.get("role") == "assistant"])
            }

        except Exception as e:
            log.error(f"[DeepResearch] Agent 运行失败: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _extract_answer(self, messages: List) -> str:
        """从消息列表中提取最终答案"""
        for msg in reversed(messages):
            content = str(msg.content) if hasattr(msg, 'content') else str(msg)

            # 查找 <answer> 标签
            if "<answer>" in content and "</answer>" in content:
                import re
                match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL)
                if match:
                    return match.group(1).strip()

            # 如果没有 answer 标签，返回最后一条 assistant 消息
            if hasattr(msg, 'role') and msg.role == "assistant":
                # 移除 think 标签
                import re
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
                content = re.sub(r'<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL)
                return content.strip()

        return "未生成答案"

    def _extract_sources(self, messages: List) -> List[Dict]:
        """从消息中提取引用的来源（兼容 Message 对象）"""
        sources = []
        seen_urls = set()

        for msg in messages:
            content = str(msg.content) if hasattr(msg, 'content') else str(msg)

            # 提取 tool_response 中的 URL
            if "<tool_response>" in content:
                import re
                # 提取所有 URL
                urls = re.findall(r'https?://[^\s<>"\']+', content)
                for url in urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        sources.append({
                            "url": url,
                            "type": "web_search"
                        })

        return sources

    def _extract_sources_from_messages(self, messages: List[Dict]) -> List[Dict]:
        """从消息字典列表中提取引用的来源"""
        sources = []
        seen_urls = set()

        for msg in messages:
            content = msg.get("content", "")

            # 提取 tool_response 中的 URL
            if "<tool_response>" in content:
                import re
                # 提取所有 URL
                urls = re.findall(r'https?://[^\s<>"\']+', content)
                for url in urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        sources.append({
                            "url": url,
                            "type": "web_search"
                        })

        return sources

    def _determine_termination(self, messages: List, max_iterations: int) -> str:
        """判断终止原因"""
        if not messages:
            return "no_messages"

        last_msg = messages[-1]
        content = str(last_msg.content) if hasattr(last_msg, 'content') else str(last_msg)

        if "<answer>" in content and "</answer>" in content:
            return "answer"

        assistant_count = len([m for m in messages if hasattr(m, 'role') and m.role == "assistant"])
        if assistant_count >= max_iterations:
            return "max_iterations"

        return "unknown"

    def _message_to_dict(self, msg) -> Dict:
        """将 Message 对象转换为字典"""
        if hasattr(msg, 'role') and hasattr(msg, 'content'):
            return {
                "role": msg.role,
                "content": msg.content
            }
        else:
            return {
                "role": "unknown",
                "content": str(msg)
            }

    def format_result_as_markdown(self, result: Dict[str, Any]) -> str:
        """将研究结果格式化为 Markdown"""
        md_lines = [
            f"# Deep Research: {result['query']}",
            "",
            "## Research Answer",
            "",
            result.get("answer", "No answer generated."),
            "",
        ]

        # 添加来源
        sources = result.get("sources", [])
        if sources:
            md_lines.extend([
                "## Sources",
                "",
            ])
            for i, source in enumerate(sources, 1):
                url = source.get("url", "")
                md_lines.append(f"{i}. [{url}]({url})")
            md_lines.append("")

        # 添加元数据
        md_lines.extend([
            "---",
            "",
            "**Metadata:**",
            f"- Termination: {result.get('termination', 'unknown')}",
            f"- Iterations: {result.get('iterations', 0)}",
            f"- Total messages: {len(result.get('messages', []))}",
            "",
        ])

        return "\n".join(md_lines)

    async def check_dependencies(self) -> Dict[str, bool]:
        """检查依赖是否满足"""
        checks = {
            "serper_key": bool(self.serper_key),
            "jina_keys": bool(self.jina_keys),
            "qwen_agent": False,
        }

        try:
            import qwen_agent
            checks["qwen_agent"] = True
        except ImportError:
            pass

        return checks

    def get_config_info(self) -> Dict[str, Any]:
        """获取配置信息"""
        return {
            "model": self.model_name,
            "api_base": self.api_base,
            "max_iterations": self.max_iterations,
            "serper_configured": bool(self.serper_key),
            "jina_configured": bool(self.jina_keys),
            "dashscope_configured": bool(self.dashscope_key),
            "sandbox_configured": bool(self.sandbox_endpoints),
        }
