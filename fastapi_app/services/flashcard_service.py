"""
闪卡生成服务
从知识库文档中提取关键概念并生成闪卡
"""
import json
import re
import time
import httpx
from typing import List, Dict, Any
from pathlib import Path

from dataflow_agent.logger import get_logger
from fastapi_app.schemas import Flashcard

log = get_logger(__name__)


async def generate_flashcards_with_llm(
    text_content: str,
    api_url: str,
    api_key: str,
    model: str,
    language: str,
    card_count: int,
) -> List[Flashcard]:
    """
    使用 LLM 从文本内容生成闪卡

    Args:
        text_content: 文档文本内容
        api_url: LLM API 地址
        api_key: API 密钥
        model: 模型名称
        language: 语言（zh/en）
        card_count: 生成闪卡数量

    Returns:
        闪卡列表
    """
    # 限制文本长度，避免超出 token 限制
    max_chars = 10000
    if len(text_content) > max_chars:
        text_content = text_content[:max_chars] + "..."

    # 构建 Prompt
    prompt = _build_flashcard_prompt(text_content, language, card_count)

    log.info(f"[flashcard_service] 开始调用 LLM 生成闪卡，模型: {model}, 数量: {card_count}")

    try:
        # 确保 API URL 包含完整路径
        if not api_url.endswith('/chat/completions'):
            if api_url.endswith('/'):
                api_url = api_url + 'chat/completions'
            else:
                api_url = api_url + '/chat/completions'

        # 调用 LLM API
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(api_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

        # 解析 LLM 返回的内容
        content = result["choices"][0]["message"]["content"]
        flashcards = _parse_flashcards_from_llm_response(content, card_count)

        log.info(f"[flashcard_service] 成功生成 {len(flashcards)} 张闪卡")
        return flashcards

    except Exception as e:
        log.error(f"[flashcard_service] LLM 调用失败: {e}")
        raise Exception(f"生成闪卡失败: {str(e)}")


def _build_flashcard_prompt(text_content: str, language: str, card_count: int) -> str:
    """构建生成闪卡的 Prompt"""
    lang_name = "中文" if language == "zh" else "English"

    prompt = f"""你是一个专业的教育内容专家，擅长从学习材料中提取关键知识点并制作闪卡。

请从以下内容中提取 {card_count} 个最重要的知识点，并为每个知识点生成一张闪卡。

要求：
1. 问题要清晰、具体，便于记忆和理解
2. 答案要准确、简洁（100字以内）
3. 优先选择核心概念、定义、重要事实、关键术语
4. 问题和答案使用{lang_name}
5. 可以包含不同类型的问题（概念解释、填空、问答等）

内容：
{text_content}

请以 JSON 数组格式返回，每个闪卡包含以下字段：
- question: 问题内容
- answer: 答案内容
- type: 类型（qa/concept/fill_blank）
- source_excerpt: 相关原文摘录（可选，最多100字）

示例格式：
[
  {{
    "question": "什么是机器学习？",
    "answer": "机器学习是人工智能的一个分支，通过算法让计算机从数据中学习规律。",
    "type": "qa",
    "source_excerpt": "机器学习（Machine Learning）是..."
  }}
]

请直接返回 JSON 数组，不要添加其他说明文字。"""

    return prompt


def _parse_flashcards_from_llm_response(content: str, card_count: int) -> List[Flashcard]:
    """
    解析 LLM 返回的闪卡数据

    Args:
        content: LLM 返回的文本内容
        card_count: 期望的闪卡数量

    Returns:
        闪卡列表
    """
    try:
        # 提取 JSON（处理可能的 markdown 代码块）
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            flashcards_data = json.loads(json_match.group())
        else:
            flashcards_data = json.loads(content)

        # 转换为 Flashcard 对象
        flashcards = []
        for i, card_data in enumerate(flashcards_data[:card_count]):
            question = card_data.get("question", "").strip()
            answer = card_data.get("answer", "").strip()

            if not question or not answer:
                continue

            flashcards.append(Flashcard(
                id=f"card_{int(time.time())}_{i}",
                question=question,
                answer=answer,
                type=card_data.get("type", "qa"),
                source_excerpt=card_data.get("source_excerpt", "")[:200] if card_data.get("source_excerpt") else None,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ))

        return flashcards

    except Exception as e:
        log.error(f"[flashcard_service] 解析 LLM 响应失败: {e}")
        raise Exception(f"解析闪卡数据失败: {str(e)}")
