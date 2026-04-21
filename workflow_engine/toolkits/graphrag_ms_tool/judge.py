"""GraphRAG 答案置信度 Judge（独立 LLM 打分）。

【输入】
    用户问题（question）、GraphRAG 生成的答案（answer）、
    推理子图边列表（reasoning_subgraph，由 ``querier._induce_subgraph`` 等得到，最多 50 条写入 prompt）。

【输出】
    ``JudgeResult``：``score`` ∈ [0,1]、``rationale`` 及可选三维 0–10 分（相关性 / 图支持 / 无过度推断）。

【评分维度】（计划 §4.4，固定 rubric）
    1. 相关性 — 是否答在问题上；
    2. 图支持 — 子图证据是否支撑结论；
    3. 无过度推断 — 是否超出证据范围。

【数据流】
    ``wf_graphrag_kb._action_query`` 在查询（及可选子图裁剪）之后调用；
    配置来自 ``settings.JUDGE_MODEL`` 与 ``DEFAULT_LLM_API_URL``。
    LLM 失败时返回 score=0.0 并记录 warning，不抛异常，便于接口仍返回部分结果。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from workflow_engine.logger import get_logger

log = get_logger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
You are a rigorous evidence quality judge. Given a user question, a
knowledge-graph reasoning subgraph (as a list of edges), and a candidate
answer, score the answer on three criteria:

1. Relevance (0-10): Does the answer address the question?
2. Graph support (0-10): Is the answer supported by the provided subgraph?
3. No over-reach (0-10): Does the answer avoid making claims beyond the evidence?

Output ONLY valid JSON:
{
  "relevance": <int 0-10>,
  "graph_support": <int 0-10>,
  "no_over_reach": <int 0-10>,
  "score": <float 0-1, average of the three divided by 10>,
  "rationale": "<1-2 sentences>"
}
"""


@dataclass
class JudgeResult:
    score: float           # 综合分 0.0–1.0
    rationale: str = ""
    relevance: int = 0
    graph_support: int = 0
    no_over_reach: int = 0


def judge_confidence(
    question: str,
    answer: str,
    reasoning_subgraph: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
) -> JudgeResult:
    """Score the answer against the question and subgraph via LLM; returns a low-score placeholder on error."""
    from fastapi_app.config.settings import settings as cfg

    model = model or cfg.JUDGE_MODEL
    api_base = api_base or cfg.DEFAULT_LLM_API_URL.rstrip("/")
    api_key = api_key or os.getenv("DF_API_KEY", "")
    max_out = int(getattr(cfg, "JUDGE_MAX_TOKENS", 256) or 256)

    # Compress the subgraph to a readable triple list (truncated to 50 edges)
    edge_lines = [
        f"  ({e.get('source', '?')}) --[{e.get('relation', '?')}]--> ({e.get('target', '?')})"
        for e in reasoning_subgraph[:24]
    ]
    subgraph_text = "\n".join(edge_lines) if edge_lines else "  (no subgraph available)"

    user_msg = (
        f"## Question\n{question}\n\n"
        f"## Reasoning Subgraph\n{subgraph_text}\n\n"
        f"## Answer\n{answer}\n"
    )

    try:
        raw = _call_llm(model, api_base, api_key, _JUDGE_SYSTEM_PROMPT, user_msg, max_tokens=max_out)
        return _parse_judge_response(raw)
    except Exception as exc:
        log.warning("[Judge] LLM call failed: %s", exc)
        return JudgeResult(score=0.0, rationale=f"Judge error: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_llm(
    model: str,
    api_base: str,
    api_key: str,
    system: str,
    user: str,
    *,
    max_tokens: int = 256,
) -> str:
    """OpenAI-compatible chat call for the judge model."""
    import time as _time
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package required for Judge module") from exc

    client = OpenAI(api_key=api_key or "none", base_url=api_base)
    t0 = _time.perf_counter()
    log.info("[TIMING][D] judge._call_llm START | model=%s | prompt_len=%d", model, len(user))
    _kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    try:
        response = client.chat.completions.create(**_kwargs, response_format={"type": "json_object"})
    except Exception as exc:
        log.debug("[Judge] response_format json_object unsupported or rejected: %s", exc)
        response = client.chat.completions.create(**_kwargs)
    content = response.choices[0].message.content or ""
    t1 = _time.perf_counter()
    log.info("[TIMING][D] judge._call_llm DONE | model=%s | elapsed=%.3fs | response_len=%d", model, t1 - t0, len(content))
    return content


def _strip_after_thinking_block(text: str) -> str:
    """Drop content before common ``</...thinking...>`` closers so JSON can be found."""
    lower = text.lower()
    for tag in (
        "</redacted_thinking>",
        "`</redacted_thinking>`",
        "</think>",
        "`</redacted_thinking>`",
    ):
        tl = tag.lower()
        i = lower.rfind(tl)
        if i != -1:
            return text[i + len(tag) :].strip()
    return text


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Parse the first balanced ``{...}`` substring as JSON (handles thinking / prose prefixes)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        start = text.find("{", start + 1)
                        break
        else:
            break
    return None


def _parse_judge_response(raw: str) -> JudgeResult:
    """Strip markdown fences, parse JSON, and normalise score to [0, 1]."""
    raw = _strip_after_thinking_block(raw.strip())
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = _extract_first_json_object(raw)
        if parsed is None:
            raise

    rel = int(parsed.get("relevance", 0))
    gs = int(parsed.get("graph_support", 0))
    nor = int(parsed.get("no_over_reach", 0))
    score = float(parsed.get("score", (rel + gs + nor) / 30.0))
    rationale = str(parsed.get("rationale", ""))

    return JudgeResult(
        score=min(1.0, max(0.0, score)),
        rationale=rationale,
        relevance=rel,
        graph_support=gs,
        no_over_reach=nor,
    )
