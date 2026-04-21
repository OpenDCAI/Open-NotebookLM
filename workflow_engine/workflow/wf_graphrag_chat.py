"""GraphRAG 对话工作流（注册名 ``"graphrag_chat"``）。

【图结构】::

    _start_ → _chat_ → END

``_chat_`` 执行意图+改写（一次 LLM）→ GraphRAG 检索 → 可选子图裁剪与 Judge（一次 LLM）→ 综合回答，
将完整结果写入 ``state.agent_results["chat"]``。

【数据流边界】
    本模块不处理 HTTP；FastAPI 经 ``wa_graphrag_kb.run_chat`` 构造 ``GraphRAGChatState``
    后 ``run_workflow("graphrag_chat", state)``。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.logger import get_logger
from workflow_engine.state import MainRequest, MainState
from workflow_engine.workflow.registry import register

log = get_logger(__name__)

MAX_HISTORY_TURNS = 8


# ---------------------------------------------------------------------------
# Request / State
# ---------------------------------------------------------------------------

@dataclass
class GraphRAGChatRequest(MainRequest):
    """Multi-turn chat request for GraphRAG conversational workflow."""
    query: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)
    search_method: str = "auto"  # "auto" | "local" | "global"
    notebook_id: str = ""
    notebook_title: str = ""
    email: str = ""
    workspace_dir: str = ""
    # None = follow settings.GRAPHRAG_WIKIDATA_ENRICH_ENABLED; False = skip Wikidata tail
    wikidata_enrich: Optional[bool] = None
    # True: return main answer first; prune/judge/wikidata will be done by a follow-up request.
    defer_postprocess: bool = False


@dataclass
class GraphRAGChatState(MainState):
    """Workflow state for GraphRAG chat."""
    request: GraphRAGChatRequest = field(default_factory=GraphRAGChatRequest)
    intent: Dict[str, Any] = field(default_factory=dict)
    rewritten_query: str = ""
    graphrag_raw_answer: str = ""
    context_data: Dict[str, Any] = field(default_factory=dict)
    reasoning_subgraph: List[Dict[str, Any]] = field(default_factory=list)
    reasoning_subgraph_cot: str = ""
    source_chunks: List[str] = field(default_factory=list)
    highlight_hints: List[Dict[str, Any]] = field(default_factory=list)
    judge_score: float = 0.0
    judge_rationale: str = ""
    answer: str = ""


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_INTENT_REWRITE_SYSTEM = """You route chat for a GraphRAG knowledge base.
Respond ONLY with valid JSON (no markdown) with exactly these keys:
- "use_graphrag": boolean — true for factual questions about document content, entities, or KB knowledge; false for greetings, pure chitchat, or questions fully answerable from conversation history alone.
- "reason": one short sentence explaining the choice.
- "rewritten": string — if use_graphrag is true, rewrite the user's latest message into a standalone question (resolve pronouns and references using history). If use_graphrag is false, set "rewritten" to the latest user message or a minimal paraphrase."""

_INTENT_REWRITE_USER = """Conversation history (most recent last):
{history}

Recent retrieval memory:
{retrieval_memory}

Latest user question: {query}"""

_DIRECT_SYSTEM = """You are a helpful assistant for a document knowledge-base application.
Answer the user's question based on the conversation history and your general knowledge.
Be concise and helpful. Respond in the same language as the user's question."""

_DIRECT_USER = """Conversation history:
{history}

User: {query}
Assistant:"""

_SYNTHESIS_SYSTEM = """You are a helpful assistant for a document knowledge-base application.
You are given the GraphRAG retrieval result and conversation history.
Write a clear, helpful answer. Respond in the same language as the user's question.
Do NOT include: internal scoring, subgraph dumps, any literal substring "[chunk:" or "[Data:",
hex chunk ids, or citation markers copied from the retrieval text."""

_SYNTHESIS_USER = """Conversation history:
{history}

User question: {query}

GraphRAG retrieval result:
{graphrag_answer}

Write the final answer, integrating the above evidence with any relevant context from history:"""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

async def _llm_json(api_url: str, api_key: str, model: str, system: str, user: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key or "none", base_url=api_url.rstrip("/"))
    resp = await client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "{}").strip()


async def _llm_text(api_url: str, api_key: str, model: str, system: str, user: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key or "none", base_url=api_url.rstrip("/"))
    resp = await client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


_RE_USER_LEAK_CHUNK = re.compile(r"\[chunk:[a-f0-9]+\]", re.IGNORECASE)
_RE_USER_LEAK_DATA = re.compile(r"\s*\[Data:[^\]]+\]", re.IGNORECASE)


def _strip_leakage_for_user_answer(text: str) -> str:
    """Remove GraphRAG citation tails and chunk id markers from text shown to the user."""
    if not (text and text.strip()):
        return text
    t = _RE_USER_LEAK_DATA.sub("", text)
    t = _RE_USER_LEAK_CHUNK.sub("", t)
    return re.sub(r"[ \t]+\n", "\n", t).strip()


def _format_history(history: List[Dict[str, Any]]) -> str:
    if not history:
        return "(no prior conversation)"
    recent = history[-MAX_HISTORY_TURNS * 2:]
    lines = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines)


def _norm_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _format_retrieval_memory(history: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for msg in reversed(history[-MAX_HISTORY_TURNS * 2 :]):
        if msg.get("role") != "assistant":
            continue
        meta = msg.get("meta")
        if not isinstance(meta, dict):
            continue
        intent = meta.get("intent")
        use_gr = False
        if isinstance(intent, dict):
            use_gr = bool(intent.get("use_graphrag", False))
        if not use_gr:
            continue
        rq = str(meta.get("rewritten_query") or "").strip()
        score = meta.get("judge_score")
        if rq:
            rows.append(f"- rewritten_query={rq!r}, judge_score={score!r}")
        if len(rows) >= 3:
            break
    return "\n".join(rows) if rows else "(none)"


def _pick_cached_graphrag_result(
    history: List[Dict[str, Any]], rewritten_query: str
) -> Optional[Dict[str, Any]]:
    target = _norm_query(rewritten_query)
    if not target:
        return None
    for msg in reversed(history):
        if msg.get("role") != "assistant":
            continue
        meta = msg.get("meta")
        if not isinstance(meta, dict):
            continue
        rq = _norm_query(str(meta.get("rewritten_query") or ""))
        raw_answer = str(meta.get("graphrag_raw_answer") or "").strip()
        if rq != target or not raw_answer:
            continue
        return {
            "answer": raw_answer,
            "context_data": meta.get("context_data") if isinstance(meta.get("context_data"), dict) else {},
            "reasoning_subgraph": meta.get("reasoning_subgraph") if isinstance(meta.get("reasoning_subgraph"), list) else [],
            "source_chunks": meta.get("source_chunks") if isinstance(meta.get("source_chunks"), list) else [],
            "highlight_hints": meta.get("highlight_hints") if isinstance(meta.get("highlight_hints"), list) else [],
        }
    return None


# ---------------------------------------------------------------------------
# Chat node
# ---------------------------------------------------------------------------

async def _chat_node(state: GraphRAGChatState) -> GraphRAGChatState:
    import asyncio
    import time as _time
    from workflow_engine.toolkits.graphrag_ms_tool.indexer import GraphRAGWorkspace
    from workflow_engine.toolkits.graphrag_ms_tool.querier import query_local, query_global
    from workflow_engine.toolkits.graphrag_ms_tool.judge import JudgeResult, judge_confidence
    from workflow_engine.toolkits.graphrag_ms_tool.prune_judge_combined import prune_and_judge_combined_llm
    from fastapi_app.config.settings import settings as cfg

    req = state.request
    api_url = req.chat_api_url.rstrip("/")
    api_key = req.api_key
    model = req.model
    history_str = _format_history(req.history)
    retrieval_memory = _format_retrieval_memory(req.history)

    t_total_start = _time.perf_counter()
    # ── Step 1: Intent + query rewrite (single LLM call) ─────────────────────
    t0 = _time.perf_counter()
    rewritten = req.query
    try:
        intent_raw = await _llm_json(
            api_url, api_key, model,
            _INTENT_REWRITE_SYSTEM,
            _INTENT_REWRITE_USER.format(
                history=history_str,
                retrieval_memory=retrieval_memory,
                query=req.query,
            ),
        )
        data = json.loads(intent_raw)
        intent = {
            "use_graphrag": bool(data.get("use_graphrag", True)),
            "reason": str(data.get("reason", "") or ""),
        }
        rw = str(data.get("rewritten", "") or "").strip()
        if rw:
            rewritten = rw
    except Exception as e:
        log.warning("[GraphRAGChat] intent+rewrite failed: %s; defaulting to GraphRAG + raw query", e)
        intent = {"use_graphrag": True, "reason": "fallback"}
    state.intent = intent
    use_graphrag = bool(intent.get("use_graphrag", True))
    t1 = _time.perf_counter()
    log.info("[TIMING][Chat] intent+rewrite | %.3fs | use_graphrag=%s", t1 - t0, use_graphrag)

    if not use_graphrag:
        # ── Step 2a: Direct answer (no GraphRAG) ────────────────────────────
        answer = await _llm_text(
            api_url, api_key, model,
            _DIRECT_SYSTEM,
            _DIRECT_USER.format(history=history_str, query=req.query),
        )
        t2 = _time.perf_counter()
        log.info("[TIMING][Chat] direct answer | %.3fs | TOTAL=%.3fs", t2 - t1, t2 - t_total_start)
        state.answer = answer
        state.agent_results["chat"] = {
            "answer": answer,
            "intent": intent,
            "rewritten_query": "",
            "context_data": {},
            "reasoning_subgraph": [],
            "reasoning_subgraph_cot": "",
            "source_chunks": [],
            "highlight_hints": [],
            "judge_score": 0.0,
            "judge_rationale": "",
            "postprocess_pending": False,
            "graphrag_raw_answer": "",
        }
        return state

    state.rewritten_query = rewritten
    log.info("[TIMING][Chat] rewritten_query (from intent step) | %r", rewritten[:120])

    # ── Step 2: GraphRAG search + optional prune+judge (single LLM when prune on) ─
    workspace_dir = req.workspace_dir
    ws = GraphRAGWorkspace(root=Path(workspace_dir).resolve())

    if not (workspace_dir or "").strip():
        state.temp_data["errors"] = ["GraphRAG workspace 未设置：请先在当前笔记本完成「构建索引」。"]
        return state
    if not ws.root.is_dir() or not ws.settings_path.is_file():
        state.temp_data["errors"] = [
            "GraphRAG 工作区无效：目录不存在或缺少 settings.yaml（常见于浏览器缓存了其他电脑或旧项目的路径）。"
            f"当前路径：{ws.root}。请在当前环境重新执行「构建索引」或清空该笔记本的 GraphRAG 缓存后重建。"
        ]
        log.warning("[GraphRAGChat] invalid workspace root_is_dir=%s settings_exists=%s", ws.root.is_dir(), ws.settings_path.is_file())
        return state

    search_method = req.search_method if req.search_method in ("local", "global") else "local"
    search_fn = query_global if search_method == "global" else query_local

    cached = _pick_cached_graphrag_result(req.history, rewritten)
    if cached is not None:
        class _CachedResult:
            def __init__(self, payload: Dict[str, Any]):
                self.answer = str(payload.get("answer") or "")
                self.context_data = payload.get("context_data") or {}
                self.reasoning_subgraph = payload.get("reasoning_subgraph") or []
                self.source_chunks = payload.get("source_chunks") or []
                self.highlight_hints = payload.get("highlight_hints") or []

        result = _CachedResult(cached)
        log.info(
            "[TIMING][Chat] graphrag search skipped (cache hit) | rewritten=%r | answer_len=%d | edges=%d",
            rewritten[:80],
            len(result.answer),
            len(result.reasoning_subgraph),
        )
    else:
        t4 = _time.perf_counter()
        try:
            result = await asyncio.to_thread(search_fn, ws, rewritten, api_base=api_url, api_key=api_key)
        except Exception as exc:
            log.warning("[GraphRAGChat] search failed: %s", exc)
            state.temp_data["errors"] = [f"GraphRAG 检索失败：{exc}"]
            return state
        t5 = _time.perf_counter()
        log.info("[TIMING][Chat] graphrag search | %.3fs | answer_len=%d", t5 - t4, len(result.answer or ""))

    reasoning_subgraph_cot = ""
    judge = None
    if not req.defer_postprocess:
        t_p0 = _time.perf_counter()
        if cfg.GRAPHRAG_SUBGRAPH_PRUNE_ENABLED and result.reasoning_subgraph:
            pj = await asyncio.to_thread(
                prune_and_judge_combined_llm,
                rewritten,
                result.answer,
                result.reasoning_subgraph,
                api_base=api_url,
                api_key=api_key,
                max_edges_input=int(cfg.GRAPHRAG_SUBGRAPH_PRUNE_MAX_EDGES_INPUT),
                max_tokens=int(getattr(cfg, "GRAPHRAG_PRUNE_JUDGE_MAX_TOKENS", 768) or 768),
            )
            result.reasoning_subgraph = pj.edges
            reasoning_subgraph_cot = pj.cot
            judge = pj.judge
            t_p1 = _time.perf_counter()
            log.info(
                "[TIMING][Chat] prune+judge combined | %.3fs | score=%.3f",
                t_p1 - t_p0,
                judge.score,
            )

        t6 = _time.perf_counter()
        if judge is None:
            judge = await asyncio.to_thread(
                judge_confidence, rewritten, result.answer, result.reasoning_subgraph,
                api_base=api_url, api_key=api_key,
            )
        t7 = _time.perf_counter()
        log.info("[TIMING][Chat] judge path | %.3fs | score=%.3f", t7 - t6, judge.score)
    else:
        judge = JudgeResult(
            score=0.0,
            rationale="后处理进行中：正在生成子图、置信度与 Wikidata 参考…",
        )
        log.info("[TIMING][Chat] defer_postprocess=True | skip prune/judge in main response")

    state.graphrag_raw_answer = result.answer
    state.context_data = result.context_data
    state.reasoning_subgraph = result.reasoning_subgraph
    state.reasoning_subgraph_cot = reasoning_subgraph_cot
    state.source_chunks = result.source_chunks
    state.highlight_hints = result.highlight_hints
    state.judge_score = judge.score
    state.judge_rationale = judge.rationale

    # ── Step 4: Synthesis ────────────────────────────────────────────────────
    t8 = _time.perf_counter()
    answer = await _llm_text(
        api_url, api_key, model,
        _SYNTHESIS_SYSTEM,
        _SYNTHESIS_USER.format(
            history=history_str,
            query=req.query,
            graphrag_answer=result.answer,
        ),
    )
    t9 = _time.perf_counter()
    log.info("[TIMING][Chat] synthesis | %.3fs | TOTAL=%.3fs", t9 - t8, t9 - t_total_start)

    answer = _strip_leakage_for_user_answer(answer)
    if not req.defer_postprocess:
        wd_flag = req.wikidata_enrich
        wd_on = (
            bool(getattr(cfg, "GRAPHRAG_WIKIDATA_ENRICH_ENABLED", True))
            if wd_flag is None
            else bool(wd_flag)
        )
        if wd_on and result.reasoning_subgraph:
            try:
                from workflow_engine.toolkits.wikidata_subgraph_enrich import (
                    format_wikidata_supplement_for_subgraph,
                )

                extra = await asyncio.to_thread(
                    format_wikidata_supplement_for_subgraph,
                    result.reasoning_subgraph,
                    lang=str(getattr(cfg, "GRAPHRAG_WIKIDATA_LANG", "zh") or "zh"),
                    max_entities=int(getattr(cfg, "GRAPHRAG_WIKIDATA_MAX_ENTITIES", 8) or 8),
                    connect_timeout=float(
                        getattr(cfg, "GRAPHRAG_WIKIDATA_CONNECT_TIMEOUT_SEC", 10.0) or 10.0
                    ),
                    read_timeout=float(getattr(cfg, "GRAPHRAG_WIKIDATA_TIMEOUT_SEC", 45.0) or 45.0),
                    http_retries=int(getattr(cfg, "GRAPHRAG_WIKIDATA_HTTP_RETRIES", 2) or 2),
                    api_url=str(
                        getattr(
                            cfg,
                            "GRAPHRAG_WIKIDATA_API_URL",
                            "https://www.wikidata.org/w/api.php",
                        )
                        or "https://www.wikidata.org/w/api.php"
                    ),
                    emit_failure_hint=True,
                )
                if extra:
                    answer = answer.rstrip() + "\n\n" + extra
            except Exception as exc:
                log.warning("[GraphRAGChat] Wikidata enrich failed: %s", exc)

    state.answer = answer
    state.agent_results["chat"] = {
        "answer": answer,
        "intent": intent,
        "rewritten_query": rewritten,
        "context_data": result.context_data,
        "reasoning_subgraph": result.reasoning_subgraph,
        "reasoning_subgraph_cot": reasoning_subgraph_cot,
        "source_chunks": result.source_chunks,
        "highlight_hints": result.highlight_hints,
        "judge_score": judge.score,
        "judge_rationale": judge.rationale,
        "postprocess_pending": bool(req.defer_postprocess and bool(result.reasoning_subgraph)),
        "graphrag_raw_answer": result.answer,
    }
    return state


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

@register("graphrag_chat")
def create_graphrag_chat_graph() -> GenericGraphBuilder:
    """Register workflow nodes/edges and return a ``GenericGraphBuilder``."""

    async def _start_(state: GraphRAGChatState) -> GraphRAGChatState:
        return state

    builder = GenericGraphBuilder(state_model=GraphRAGChatState, entry_point="_start_")
    builder.add_nodes({"_start_": _start_, "_chat_": _chat_node})
    builder.add_edges([("_start_", "_chat_")])
    return builder
