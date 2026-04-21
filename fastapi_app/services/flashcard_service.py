"""
闪卡生成服务
从知识库文档中提取关键概念并生成闪卡
"""
import json
import re
import time
import httpx
from typing import List, Dict, Any, Optional

from workflow_engine.logger import get_logger
from fastapi_app.schemas import Flashcard, FlashcardCitation

log = get_logger(__name__)


async def generate_flashcards_with_llm(
    text_content: str,
    api_url: str,
    api_key: str,
    model: str,
    language: str,
    card_count: int,
    difficulty_level: Optional[str] = None,
    topic: Optional[str] = None,
    test_focus: Optional[str] = None,
    citation_sources: Optional[List[Dict[str, Any]]] = None,
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
    prompt = _build_flashcard_prompt(
        text_content=text_content,
        language=language,
        card_count=card_count,
        difficulty_level=difficulty_level,
        topic=topic,
        test_focus=test_focus,
        citation_sources=citation_sources or [],
    )

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
        flashcards = _parse_flashcards_from_llm_response(
            content=content,
            card_count=card_count,
            citation_sources=citation_sources or [],
        )

        log.info(f"[flashcard_service] 成功生成 {len(flashcards)} 张闪卡")
        return flashcards

    except Exception as e:
        log.error(f"[flashcard_service] LLM 调用失败: {e}")
        raise Exception(f"生成闪卡失败: {str(e)}")


def _build_flashcard_prompt(
    *,
    text_content: str,
    language: str,
    card_count: int,
    difficulty_level: Optional[str],
    topic: Optional[str],
    test_focus: Optional[str],
    citation_sources: List[Dict[str, Any]],
) -> str:
    """构建生成闪卡的 Prompt"""
    lang_name = "中文" if language == "zh" else "English"
    difficulty_label = {
        "basic": "基础",
        "intermediate": "进阶",
        "advanced": "挑战",
    }.get(str(difficulty_level or "").strip(), "未指定")
    source_lines = [
        f"[{index}] {source.get('file_name') or source.get('file_path') or f'来源 {index}'}"
        for index, source in enumerate(citation_sources, start=1)
    ]

    prompt = f"""你是一个专业的教育内容专家，擅长从学习材料中提取关键知识点并制作闪卡。

请从以下内容中提取 {card_count} 个最重要的知识点，并为每个知识点生成一张闪卡。

要求：
1. 问题要清晰、具体，便于记忆和理解
2. 答案要准确、简洁（100字以内）
3. 优先选择核心概念、定义、重要事实、关键术语
4. 问题和答案使用{lang_name}
5. 可以包含不同类型的问题（概念解释、填空、问答等）
6. 如果答案引用了来源，必须在答案中保留 [1]、[2] 这种编号，可多个并列如 [1][2]
7. citations 字段必须是结构化引用列表，source_number 要和答案中的编号一致
8. 如果未给出可用来源，不要凭空编造 citations

生成条件：
- 难度等级：{difficulty_label}
- 主题：{topic or "未指定"}
- 测试内容：{test_focus or "未指定"}

可用来源列表：
{chr(10).join(source_lines) if source_lines else "未提供独立来源列表"}

内容：
{text_content}

请以 JSON 数组格式返回，每个闪卡包含以下字段：
- question: 问题内容
- answer: 答案内容
- type: 类型（qa/concept/fill_blank）
- source_excerpt: 相关原文摘录（可选，最多100字）
- citations: 引用数组（可选），每项包含：
  - source_number: 来源编号整数
  - preview: 对应来源的简短预览（可选，最多120字）

示例格式：
[
  {{
    "question": "什么是机器学习？",
    "answer": "机器学习是人工智能的一个分支，通过算法让计算机从数据中学习规律。[1]",
    "type": "qa",
    "source_excerpt": "机器学习（Machine Learning）是...",
    "citations": [
      {{
        "source_number": 1,
        "preview": "机器学习（Machine Learning）是..."
      }}
    ]
  }}
]

请直接返回 JSON 数组，不要添加其他说明文字。"""

    return prompt


def _try_parse_json_array(json_str: str):
    """尝试解析 JSON 数组，失败时逐步回退到最后一个完整对象"""
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    brace_depth = 0
    in_string = False
    escape = False
    candidates = []
    for i, ch in enumerate(json_str):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0:
                candidates.append(i)

    for pos in reversed(candidates):
        attempt = json_str[:pos + 1] + ']'
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError("No valid JSON array found", json_str, 0)


def _build_flashcard_citations(
    card_data: Dict[str, Any],
    citation_sources: List[Dict[str, Any]],
    fallback_preview: Optional[str],
) -> List[FlashcardCitation]:
    raw_citations = card_data.get("citations")
    citations: List[FlashcardCitation] = []
    if isinstance(raw_citations, list):
        for item in raw_citations:
            if not isinstance(item, dict):
                continue
            source_number = item.get("source_number")
            try:
                source_number_int = int(source_number)
            except (TypeError, ValueError):
                continue
            source_meta = citation_sources[source_number_int - 1] if 0 < source_number_int <= len(citation_sources) else {}
            citations.append(
                FlashcardCitation(
                    source_number=source_number_int,
                    file_name=str(item.get("file_name") or source_meta.get("file_name") or "") or None,
                    file_path=str(item.get("file_path") or source_meta.get("file_path") or "") or None,
                    preview=str(item.get("preview") or fallback_preview or source_meta.get("preview") or "")[:240] or None,
                    chunk_index=item.get("chunk_index"),
                )
            )

    if citations:
        deduped: Dict[int, FlashcardCitation] = {}
        for citation in citations:
            deduped[citation.source_number] = citation
        return [deduped[number] for number in sorted(deduped)]

    answer = str(card_data.get("answer") or "")
    source_numbers = []
    for match in re.findall(r"\[(\d+)\]", answer):
        try:
            source_numbers.append(int(match))
        except ValueError:
            continue
    deduped_numbers = sorted(set(number for number in source_numbers if number > 0))
    fallback_citations: List[FlashcardCitation] = []
    for source_number in deduped_numbers:
        source_meta = citation_sources[source_number - 1] if source_number <= len(citation_sources) else {}
        fallback_citations.append(
            FlashcardCitation(
                source_number=source_number,
                file_name=str(source_meta.get("file_name") or "") or None,
                file_path=str(source_meta.get("file_path") or "") or None,
                preview=str(fallback_preview or source_meta.get("preview") or "")[:240] or None,
                chunk_index=source_meta.get("chunk_index"),
            )
        )
    return fallback_citations


def _parse_flashcards_from_llm_response(
    content: str,
    card_count: int,
    citation_sources: List[Dict[str, Any]],
) -> List[Flashcard]:
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
        json_match = re.search(r'```(?:json)?\s*(\[[\s\S]*)', content)
        if json_match:
            json_str = json_match.group(1)
            json_str = re.sub(r'\s*```\s*$', '', json_str)
        else:
            # fallback: 找 [ 开头的内容
            idx = content.find('[')
            json_str = content[idx:] if idx >= 0 else content.strip()

        flashcards_data = _try_parse_json_array(json_str)

        # 转换为 Flashcard 对象
        flashcards = []
        for i, card_data in enumerate(flashcards_data[:card_count]):
            question = card_data.get("question", "").strip()
            answer = card_data.get("answer", "").strip()

            if not question or not answer:
                continue

            source_excerpt = card_data.get("source_excerpt", "")[:200] if card_data.get("source_excerpt") else None
            citations = _build_flashcard_citations(
                card_data=card_data,
                citation_sources=citation_sources,
                fallback_preview=source_excerpt,
            )
            primary_citation = citations[0] if citations else None

            flashcards.append(
                Flashcard(
                    id=f"card_{int(time.time())}_{i}",
                    question=question,
                    answer=answer,
                    type=card_data.get("type", "qa"),
                    difficulty=card_data.get("difficulty"),
                    source_file=primary_citation.file_name if primary_citation and primary_citation.file_name else card_data.get("source_file"),
                    source_excerpt=source_excerpt,
                    tags=[str(tag) for tag in card_data.get("tags", [])] if isinstance(card_data.get("tags"), list) else [],
                    citations=citations,
                    created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
            )

        return flashcards

    except Exception as e:
        log.error(f"[flashcard_service] 解析 LLM 响应失败: {e}")
        raise Exception(f"解析闪卡数据失败: {str(e)}")
