"""基于 LLM 的推理子图裁剪：从完整关系边列表中选出「支撑答案所需」的最小子集，并输出 CoT。

【数据流】
    输入：来自 ``querier._induce_subgraph`` 的边列表（可能很长）、用户问题、GraphRAG 草稿答案。
    处理：将边编号为 0..N-1 写入 prompt，要求模型输出 ``keep_indices``、``analysis``（链式思考）、``max_hops``。
    输出：``SubgraphPruneResult`` — 保留的边列表、展示用 CoT 文本、跳数估计。

【调用关系】
    ``wf_graphrag_kb._action_query`` 在 ``GRAPHRAG_SUBGRAPH_PRUNE_ENABLED`` 为真且子图非空时调用；
    裁剪后的边写回 ``result.reasoning_subgraph``，CoT 写入 ``reasoning_subgraph_cot`` 供前端展示。

【失败策略】
    LLM 解析失败或索引非法时，回退为截断后的边列表并附带错误说明，避免查询整体失败。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from workflow_engine.logger import get_logger

log = get_logger(__name__)

_SUBGRAPH_PRUNE_SYSTEM = """You are a knowledge-graph analyst.

You will receive:
1. A user question (Q)
2. A draft answer (A) produced by GraphRAG retrieval + generation
3. A numbered list of directed edges: (source) --[relation]--> (target)

Your tasks:
- In the JSON field "analysis", write a clear chain-of-thought: which edges are
  strictly necessary to justify A for Q, and why. Discuss **hops**: when you
  connect entities along these edges, what is the longest shortest-path length
  (in edges) among pairs of entities that matter for the answer? Name approximate
  hop counts (e.g. "entity X to Y is 2 hops via ...").
- In "keep_indices", list the 0-based indices of edges to KEEP. Prefer a SMALL
  minimal set (typically 3–15 edges) that still supports the answer. Indices
  MUST refer only to edges in the provided numbered list (0 to N-1).
- In "max_hops", give a single integer: your estimate of the maximum hop count
  among important entity pairs in the kept subgraph (0 if a single edge or none).

Output ONLY valid JSON (no markdown code fences):
{
  "analysis": "<chain-of-thought in English or Chinese>",
  "keep_indices": [<int>, ...],
  "max_hops": <int>
}

If the edge list is empty, return {"analysis":"(no edges)","keep_indices":[],"max_hops":0}.
"""


@dataclass
class SubgraphPruneResult:
    """Result of LLM-based subgraph pruning: kept edges, CoT text, and estimated max hops."""

    edges: List[Dict[str, Any]]
    cot: str
    max_hops: int = 0


def _call_llm(
    model: str,
    api_base: str,
    api_key: str,
    system: str,
    user: str,
    *,
    max_tokens: int = 2048,
) -> str:
    """OpenAI-compatible chat call used by the pruner."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package required for subgraph pruner") from exc

    client = OpenAI(api_key=api_key or "none", base_url=api_base)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.1,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """Strip optional markdown fences from LLM output and parse as JSON."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def prune_reasoning_subgraph_llm(
    question: str,
    answer: str,
    edges: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    max_edges_input: int = 80,
) -> SubgraphPruneResult:
    """Return pruned edges and CoT; falls back to a truncated copy of the input edges on failure."""
    from fastapi_app.config.settings import settings as cfg

    model = model or cfg.GRAPHRAG_LLM_MODEL
    api_base = (api_base or cfg.DEFAULT_LLM_API_URL).rstrip("/")
    api_key = api_key or os.getenv("DF_API_KEY", "")

    if not edges:
        return SubgraphPruneResult(edges=[], cot="")

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
        raw = _call_llm(
            model,
            api_base,
            api_key,
            _SUBGRAPH_PRUNE_SYSTEM,
            user_msg,
            max_tokens=2048,
        )
        parsed = _parse_json_object(raw)
    except Exception as exc:
        log.warning("[SubgraphPruner] LLM prune failed: %s", exc)
        return SubgraphPruneResult(
            edges=sl[: min(12, len(sl))],
            cot=f"(automatic fallback: prune failed: {exc})",
            max_hops=0,
        )

    analysis = str(parsed.get("analysis", "") or "")
    max_hops = int(parsed.get("max_hops", 0) or 0)
    cot_display = analysis
    if max_hops > 0 and "**max_hops" not in analysis:
        cot_display = f"{analysis}\n\n**max_hops (estimate):** {max_hops}"
    idx_raw = parsed.get("keep_indices")
    if not isinstance(idx_raw, list):
        return SubgraphPruneResult(
            edges=sl[: min(12, len(sl))],
            cot=cot_display or "(invalid keep_indices; truncated)",
            max_hops=max_hops,
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
        return SubgraphPruneResult(
            edges=sl[: min(12, len(sl))],
            cot=cot_display or "(empty keep_indices; truncated)",
            max_hops=max_hops,
        )

    return SubgraphPruneResult(edges=kept, cot=cot_display, max_hops=max_hops)
