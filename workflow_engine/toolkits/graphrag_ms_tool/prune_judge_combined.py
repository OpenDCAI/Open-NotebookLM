"""单次 LLM 同时完成推理子图裁剪与答案置信度 Judge（降低延迟）。

当 ``GRAPHRAG_SUBGRAPH_PRUNE_ENABLED`` 且子图非空时使用本模块，替代
``prune_reasoning_subgraph_llm`` + ``judge_confidence`` 两次调用。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from workflow_engine.logger import get_logger

from workflow_engine.toolkits.graphrag_ms_tool.judge import JudgeResult

log = get_logger(__name__)

_COMBINED_SYSTEM = """You are a knowledge-graph analyst and evidence judge in one step.

Input: a user question (Q), a draft answer (A), and a numbered edge list (index 0..N-1).

Tasks (be concise to save tokens):
1) Pick keep_indices: 0-based indices of edges minimally needed to support A for Q (typically 3–12 edges).
2) analysis: brief reasoning (≤120 words) on which edges matter and approximate hop counts between key entities.
3) max_hops: integer estimate for the kept subgraph.
4) Judge A against Q using ONLY the edges you would KEEP (describe mentally before scoring):
   - relevance (0-10), graph_support (0-10), no_over_reach (0-10)
   - score: float 0-1 = average of the three / 10
   - rationale: one short sentence

Output ONLY valid JSON (no markdown):
{
  "analysis": "<string>",
  "keep_indices": [<int>, ...],
  "max_hops": <int>,
  "relevance": <int 0-10>,
  "graph_support": <int 0-10>,
  "no_over_reach": <int 0-10>,
  "score": <float 0-1>,
  "rationale": "<string>"
}

If the edge list is empty, return keep_indices [], max_hops 0, analysis "(no edges)", and low scores with rationale "no graph edges"."""


def _parse_json_loose(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(raw)):
                if raw[i] == "{":
                    depth += 1
                elif raw[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[start : i + 1])
                        except json.JSONDecodeError:
                            start = raw.find("{", start + 1)
                            break
            else:
                break
        raise


def _fallback_edges(sl: List[Dict[str, Any]], err: str) -> tuple[List[Dict[str, Any]], str, int]:
    n = min(12, len(sl))
    return sl[:n], f"(fallback: {err})", 0


@dataclass
class PruneJudgeCombinedResult:
    edges: List[Dict[str, Any]]
    cot: str
    max_hops: int
    judge: JudgeResult


def _call_llm(
    model: str,
    api_base: str,
    api_key: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
) -> str:
    import time as _time
    from openai import OpenAI

    client = OpenAI(api_key=api_key or "none", base_url=api_base)
    t0 = _time.perf_counter()
    log.info(
        "[TIMING][CJ] prune_judge_combined START | model=%s | prompt_len=%d | max_tokens=%d",
        model,
        len(user),
        max_tokens,
    )
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=0.1,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    try:
        response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    except Exception as exc:
        log.debug("[PruneJudge] response_format json_object rejected: %s", exc)
        response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    t1 = _time.perf_counter()
    log.info(
        "[TIMING][CJ] prune_judge_combined DONE | model=%s | elapsed=%.3fs | response_len=%d",
        model,
        t1 - t0,
        len(content),
    )
    return content


def prune_and_judge_combined_llm(
    question: str,
    answer: str,
    edges: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    max_edges_input: int = 28,
    max_tokens: int = 768,
) -> PruneJudgeCombinedResult:
    """One LLM call: prune subgraph + judge; on failure returns truncated edges and a neutral judge."""
    from fastapi_app.config.settings import settings as cfg

    explicit = getattr(cfg, "GRAPHRAG_PRUNE_JUDGE_MODEL", None)
    if explicit and str(explicit).strip():
        model = str(explicit).strip()
    elif model and str(model).strip():
        model = str(model).strip()
    else:
        model = (cfg.JUDGE_MODEL or getattr(cfg, "GRAPHRAG_SUBGRAPH_PRUNE_MODEL", None) or cfg.GRAPHRAG_LLM_MODEL)
    api_base = (api_base or cfg.DEFAULT_LLM_API_URL).rstrip("/")
    api_key = api_key or os.getenv("DF_API_KEY", "")

    if not edges:
        return PruneJudgeCombinedResult(
            edges=[],
            cot="",
            max_hops=0,
            judge=JudgeResult(score=0.0, rationale="no subgraph edges"),
        )

    sl = edges[: max(1, int(max_edges_input))]
    lines = [
        f"{i}: ({e.get('source', '?')}) --[{e.get('relation', '?')}]--> ({e.get('target', '?')})"
        for i, e in enumerate(sl)
    ]
    edge_block = "\n".join(lines)
    user_msg = (
        f"## Question\n{question}\n\n"
        f"## Draft answer\n{answer}\n\n"
        f"## Edges (index 0..{len(sl)-1})\n{edge_block}\n"
    )

    try:
        raw = _call_llm(model, api_base, api_key, _COMBINED_SYSTEM, user_msg, max_tokens=max_tokens)
        parsed = _parse_json_loose(raw)
    except Exception as exc:
        log.warning("[PruneJudge] combined LLM failed: %s", exc)
        fe, cot, mh = _fallback_edges(sl, str(exc))
        return PruneJudgeCombinedResult(
            edges=fe,
            cot=cot,
            max_hops=mh,
            judge=JudgeResult(score=0.5, rationale=f"combined call failed; neutral score: {exc}"),
        )

    analysis = str(parsed.get("analysis", "") or "")
    max_hops = int(parsed.get("max_hops", 0) or 0)
    cot_display = analysis
    if max_hops > 0 and "max_hops" not in analysis.lower():
        cot_display = f"{analysis}\n\n**max_hops (estimate):** {max_hops}"

    rel = int(parsed.get("relevance", 0))
    gs = int(parsed.get("graph_support", 0))
    nor = int(parsed.get("no_over_reach", 0))
    try:
        score = float(parsed.get("score", (rel + gs + nor) / 30.0))
    except (TypeError, ValueError):
        score = 0.5
    rationale = str(parsed.get("rationale", "") or "")

    judge = JudgeResult(
        score=min(1.0, max(0.0, score)),
        rationale=rationale,
        relevance=max(0, min(10, rel)),
        graph_support=max(0, min(10, gs)),
        no_over_reach=max(0, min(10, nor)),
    )

    idx_raw = parsed.get("keep_indices")
    if not isinstance(idx_raw, list):
        fe, cot_e, _ = _fallback_edges(sl, "invalid keep_indices")
        return PruneJudgeCombinedResult(
            edges=fe,
            cot=cot_display or cot_e,
            max_hops=max_hops,
            judge=judge,
        )

    kept: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for x in idx_raw:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i < 0 or i >= len(sl) or i in seen:
            continue
        seen.add(i)
        kept.append(sl[i])

    if not kept:
        fe, _, _ = _fallback_edges(sl, "empty keep_indices")
        return PruneJudgeCombinedResult(
            edges=fe,
            cot=cot_display or "(empty keep_indices; truncated)",
            max_hops=max_hops,
            judge=judge,
        )

    return PruneJudgeCombinedResult(edges=kept, cot=cot_display, max_hops=max_hops, judge=judge)
