"""
Quiz 生成服务
从知识库文档中生成单选题测验
"""
import json
import re
import time
import httpx
from typing import List, Dict, Any
from pathlib import Path

from dataflow_agent.logger import get_logger
from fastapi_app.schemas import QuizQuestion, QuizOption

log = get_logger(__name__)


async def generate_quiz_with_llm(
    text_content: str,
    api_url: str,
    api_key: str,
    model: str,
    language: str,
    question_count: int,
) -> List[QuizQuestion]:
    """
    使用 LLM 从文本内容生成 Quiz 题目

    Args:
        text_content: 文档文本内容
        api_url: LLM API 地址
        api_key: API 密钥
        model: 模型名称
        language: 语言（zh/en）
        question_count: 生成题目数量

    Returns:
        Quiz 题目列表
    """
    # 限制文本长度，避免超出 token 限制
    max_chars = 10000
    if len(text_content) > max_chars:
        text_content = text_content[:max_chars] + "..."

    # 构建 Prompt
    prompt = _build_quiz_prompt(text_content, language, question_count)

    log.info(f"[quiz_service] 开始调用 LLM 生成 Quiz，模型: {model}, 数量: {question_count}")

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
        questions = _parse_quiz_from_llm_response(content, question_count)

        log.info(f"[quiz_service] 成功生成 {len(questions)} 道题目")
        return questions

    except Exception as e:
        log.error(f"[quiz_service] LLM 调用失败: {e}")
        raise Exception(f"生成 Quiz 失败: {str(e)}")


def _build_quiz_prompt(text_content: str, language: str, question_count: int) -> str:
    """
    构建生成 Quiz 的 Prompt

    出题原则：
    1. 考察理解和应用，而非简单记忆
    2. 选项设计合理，干扰项有迷惑性
    3. 答案明确，有据可依
    4. 覆盖文档的关键知识点
    """
    if language == "zh":
        prompt = f"""请基于以下文档内容，生成 {question_count} 道高质量的单选题测验题目。

文档内容：
{text_content}

出题要求：
1. 题目类型：单选题，每题必须有且仅有 4 个选项（A、B、C、D）
2. 题目质量：
   - 考察对文档内容的理解和应用，而非简单记忆
   - 题目表述清晰、准确、无歧义
   - 选项设计合理，干扰项要有一定迷惑性
   - 正确答案必须明确且有据可依
3. 难度分布：
   - 简单题（理解）：30%
   - 中等题（应用）：50%
   - 困难题（分析）：20%
4. 答案解释：
   - 必须给出详细的答案解释
   - 解释要引用文档中的具体内容
   - 说明为什么其他选项是错误的

请以 JSON 格式返回，格式如下：
```json
[
  {{
    "id": "q1",
    "question": "题目内容",
    "options": [
      {{"label": "A", "text": "选项A内容"}},
      {{"label": "B", "text": "选项B内容"}},
      {{"label": "C", "text": "选项C内容"}},
      {{"label": "D", "text": "选项D内容"}}
    ],
    "correct_answer": "A",
    "explanation": "详细的答案解释，说明为什么A是正确的，以及为什么其他选项是错误的。",
    "source_excerpt": "文档中相关的原文摘录",
    "difficulty": "medium",
    "category": "application"
  }}
]
```

请确保返回的是有效的 JSON 格式。"""
    else:
        prompt = f"""Based on the following document content, generate {question_count} high-quality multiple-choice quiz questions.

Document Content:
{text_content}

Requirements:
1. Question Type: Multiple choice, each question must have exactly 4 options (A, B, C, D)
2. Quality Standards:
   - Test understanding and application, not just memorization
   - Questions should be clear, precise, and unambiguous
   - Options should be well-designed with plausible distractors
   - Correct answer must be definitive and evidence-based
3. Difficulty Distribution:
   - Easy (comprehension): 30%
   - Medium (application): 50%
   - Hard (analysis): 20%
4. Answer Explanation:
   - Provide detailed explanation for the correct answer
   - Reference specific content from the document
   - Explain why other options are incorrect

Return in JSON format:
```json
[
  {{
    "id": "q1",
    "question": "Question text",
    "options": [
      {{"label": "A", "text": "Option A text"}},
      {{"label": "B", "text": "Option B text"}},
      {{"label": "C", "text": "Option C text"}},
      {{"label": "D", "text": "Option D text"}}
    ],
    "correct_answer": "A",
    "explanation": "Detailed explanation of why A is correct and why other options are incorrect.",
    "source_excerpt": "Relevant excerpt from the document",
    "difficulty": "medium",
    "category": "application"
  }}
]
```

Ensure the response is valid JSON format."""

    return prompt


def _parse_quiz_from_llm_response(content: str, question_count: int) -> List[QuizQuestion]:
    """
    从 LLM 返回的内容中解析 Quiz 题目
    """
    try:
        # 尝试提取 JSON（可能包含在 markdown 代码块中）
        json_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析整个内容
            json_str = content.strip()

        # 尝试修复常见的 JSON 格式问题
        # 1. 移除可能的尾部不完整内容
        if not json_str.endswith(']'):
            # 找到最后一个完整的对象
            last_complete = json_str.rfind('}')
            if last_complete > 0:
                json_str = json_str[:last_complete + 1] + ']'

        # 解析 JSON
        questions_data = json.loads(json_str)

        # 转换为 QuizQuestion 对象
        questions = []
        for i, q_data in enumerate(questions_data[:question_count]):
            # 确保有 4 个选项
            options = []
            for opt in q_data.get("options", [])[:4]:
                options.append(QuizOption(
                    label=opt.get("label", ""),
                    text=opt.get("text", "")
                ))

            # 如果选项不足 4 个，补充空选项
            while len(options) < 4:
                label = chr(65 + len(options))  # A, B, C, D
                options.append(QuizOption(label=label, text=""))

            question = QuizQuestion(
                id=q_data.get("id", f"q{i+1}"),
                question=q_data.get("question", ""),
                options=options,
                correct_answer=q_data.get("correct_answer", "A"),
                explanation=q_data.get("explanation", ""),
                source_excerpt=q_data.get("source_excerpt"),
                difficulty=q_data.get("difficulty", "medium"),
                category=q_data.get("category", "application")
            )
            questions.append(question)

        return questions

    except Exception as e:
        log.error(f"[quiz_service] 解析 Quiz 失败: {e}")
        log.error(f"[quiz_service] LLM 返回内容: {content[:500]}")
        raise Exception(f"解析 Quiz 失败: {str(e)}")

