"""
Deep Research 报告：先用 search 拿到结果，再塞给 LLM 生成长报告。
LLM 需在首行输出标题，用于来源命名（前缀 [report] 由调用方加）。
"""
from __future__ import annotations

import re
from typing import Tuple

import httpx

from dataflow_agent.logger import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = """You are a Deep Research Assistant. You will be given a research topic and a set of web search results (title, link, snippet for each). Your task is to write one comprehensive, structured research report in the specified language.

Requirements:
1. The FIRST line of your response MUST be exactly: Title: <short title in the specified language, no more than 40 characters, no newline>
2. Then a blank line, then the full report body.
3. Use the search results as sources and evidence; cite or summarize them where relevant.
4. Organize with clear sections (e.g. Introduction, Key Points, Analysis, Conclusion).
5. Be thorough and objective. No other meta-commentary."""

USER_PROMPT_TEMPLATE = """[Topic]:
{topic}

[Language]: {language}

[Web search results]:
{search_context}

Please write a detailed research report. The first line must be: Title: <short title in the specified language>. Then a blank line, then the full report content."""


def _parse_title_and_content(raw: str, topic: str) -> Tuple[str, str]:
    """从 LLM 输出解析首行 Title: xxx 与正文；若无则用 topic 作为标题。"""
    raw = (raw or "").strip()
    if not raw:
        return (topic[:40] or "Deep Research Report", "")
    first_line, _, rest = raw.partition("\n")
    m = re.match(r"^Title:\s*(.+)$", first_line.strip(), re.IGNORECASE)
    if m:
        title = m.group(1).strip()[:40]
        content = rest.lstrip("\n")
        return (title or topic[:40], content)
    return (topic[:40] or "Deep Research Report", raw)


def generate_report_from_search(
    topic: str,
    search_context: str,
    *,
    api_url: str,
    api_key: str,
    model: str = "deepseek-v3.2",
    language: str = "zh",
) -> Tuple[str, str]:
    """
    根据 topic 和 search_context 调用 LLM 生成一篇长报告。
    返回 (报告标题, 报告正文)；标题用于来源命名（调用方加 [report] 前缀）。
    """
    url = api_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    user_content = USER_PROMPT_TEMPLATE.format(
        topic=topic,
        language=language,
        search_context=search_context or "(无搜索结果，请基于主题发挥)",
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.7,
        "max_tokens": 16000,
    }
    log.info(
        "[deep_research_report] LLM 输入: model=%s, url=%s, topic=%r, search_context_len=%s, user_content_preview=%s",
        model,
        url,
        topic[:100],
        len(search_context or ""),
        (user_content[:500] + "..." if len(user_content) > 500 else user_content),
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("[deep_research_report] LLM call failed: %s", e)
        raise
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(data.get("error", "No choices in response"))
    raw = (choices[0].get("message") or {}).get("content") or ""
    raw = raw.strip()
    title, content = _parse_title_and_content(raw, topic)
    log.info(
        "[deep_research_report] LLM 输出: title=%r, report_len=%s, preview=%s",
        title,
        len(content),
        (content[:400] + "..." if len(content) > 400 else content),
    )
    return (title, content)
