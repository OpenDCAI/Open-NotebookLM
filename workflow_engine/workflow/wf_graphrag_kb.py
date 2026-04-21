"""GraphRAG 知识库管线工作流（注册名 ``"graphrag_kb"``）。

【图结构】（单节点派发，便于维护）::

    _start_ → _dispatch_ → END

``_dispatch_`` 读取 ``state.request.action``，分别路由到：
    ``index``  → ``_action_index``   （MinerU 可选 → 分块 → 可选 KGGen → GraphRAG 建索引）
    ``query``  → ``_action_query``   （本地/全局检索 → 可选子图剪枝+Judge 合并 LLM）
    ``merge``  → ``_action_merge``   （两工作区 chunk 合并 → 强制重索引）

【数据流边界】
    本模块**不处理 HTTP**；FastAPI 经 ``wa_graphrag_kb`` 构造 ``GraphRAGKBState`` 后 ``run_workflow``。
    成功结果写入 ``state.agent_results``；异常写入 ``state.temp_data["errors"]``。
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


# ---------------------------------------------------------------------------
# Request / State  (dataclasses matching project convention)
# ---------------------------------------------------------------------------

@dataclass
class GraphRAGKBRequest(MainRequest):
    """Single-action request for the GraphRAG KB pipeline (index / query / merge)."""

    # ── 动作选择 ────────────────────────────────────────────────────────────────
    # index   源文件分块 →（可选 KGGen）→ GraphRAG 建索引
    # query   在已有 workspace 上做 local/global 检索
    # merge   合并两个 workspace 并重新索引
    action: str = "index"

    # ── Index / Query shared ──────────────────────────────────────────────────
    notebook_id: str = ""
    notebook_title: str = ""
    email: str = ""
    workspace_dir: str = ""          # override default workspace path

    # ── Index ─────────────────────────────────────────────────────────────────
    source_stems: List[str] = field(default_factory=list)
    force_reindex: bool = False
    # When True, run MinerU on any PDF that has not been parsed yet before
    # chunk extraction.  Skips PDFs that already have a mineru/ directory.
    parse_pdfs: bool = True
    # When False, run optional KGGen triple extraction (not used by GraphRAG index).
    # Default True: user-facing index path is MinerU/chunks → GraphRAG only.
    skip_kggen: bool = True

    # ── Query ─────────────────────────────────────────────────────────────────
    question: str = ""
    search_method: str = "local"     # "local" | "global"

    # ── Merge ─────────────────────────────────────────────────────────────────
    workspace_dir_b: str = ""
    dedupe: bool = False

    # ── Query (optional) ──────────────────────────────────────────────────────
    # None = follow settings.GRAPHRAG_WIKIDATA_ENRICH_ENABLED
    wikidata_enrich: Optional[bool] = None


@dataclass
class GraphRAGKBState(MainState):
    """Workflow state; ``agent_results`` accumulates action outputs."""

    request: GraphRAGKBRequest = field(default_factory=GraphRAGKBRequest)


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

@register("graphrag_kb")
def create_graphrag_kb_graph() -> GenericGraphBuilder:
    """Register workflow nodes/edges and return a ``GenericGraphBuilder``."""

    builder = GenericGraphBuilder(state_model=GraphRAGKBState, entry_point="_start_")

    async def _start_(state: GraphRAGKBState) -> GraphRAGKBState:
        return state

    async def _dispatch_(state: GraphRAGKBState) -> GraphRAGKBState:
        action = (state.request.action or "").strip().lower()
        try:
            if action == "index":
                await _action_index(state)
            elif action == "query":
                await _action_query(state)
            elif action == "merge":
                await _action_merge(state)
            else:
                state.temp_data["errors"] = [f"Unknown action: {action!r}"]
        except Exception as exc:
            log.exception("[GraphRAGKB] Workflow error (action=%s): %s", action, exc)
            state.temp_data["errors"] = [str(exc)]
        return state

    nodes = {"_start_": _start_, "_dispatch_": _dispatch_}
    edges = [("_start_", "_dispatch_")]

    builder.add_nodes(nodes).add_edges(edges)
    return builder


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

async def _action_index(state: GraphRAGKBState) -> None:
    """MinerU (opt) → chunk extraction → KGGen (opt) → ``build_index``; writes ``agent_results["index"]``."""
    import asyncio
    from fastapi_app.notebook_paths import get_notebook_paths
    from fastapi_app.source_manager import SourceManager
    from fastapi_app.config.settings import settings as cfg
    from workflow_engine.toolkits.graphrag_ms_tool.indexer import build_index

    req = state.request
    nb_paths = get_notebook_paths(req.notebook_id, req.notebook_title, req.email)
    manager = SourceManager(nb_paths)

    # Step 0 — collect sources and (optionally) trigger MinerU for unparsed PDFs
    sources = manager.list_sources()
    if req.source_stems:
        sources = [s for s in sources if s.stem in req.source_stems]

    if req.parse_pdfs:
        await _ensure_mineru_parsed(manager, nb_paths, sources, req.force_reindex)

    # Step 1 — collect structured chunks from all (or selected) sources

    all_chunks: List[Dict[str, Any]] = []
    n_src = len(sources)
    for si, src in enumerate(sources, start=1):
        chunks = manager.get_chunks_with_meta(
            src.stem,
            chunk_size=cfg.GRAPHRAG_CHUNK_SIZE,
            chunk_overlap=cfg.GRAPHRAG_CHUNK_OVERLAP,
        )
        all_chunks.extend(chunks)
        log.info(
            "[GraphRAGKB] Step1 source=%s → %d chunks (%d/%d sources)",
            src.stem,
            len(chunks),
            si,
            n_src,
        )

    if not all_chunks:
        raise ValueError(
            "No text chunks found. Ensure sources have been imported into the notebook first."
        )
    log.info("[GraphRAGKB] Step1 done: %d total chunks", len(all_chunks))

    # Step 2 — optional KGGen (not fed into GraphRAG; default off for user-facing index)
    kg_result: Optional[Dict[str, Any]] = None
    if not req.skip_kggen:
        from workflow_engine.toolkits.kggen_tool.kg_extractor import extract_kg_from_chunks

        try:
            kg_llm_model = req.model or cfg.GRAPHRAG_LLM_MODEL or cfg.KGGEN_MODEL
            log.info(
                "[GraphRAGKB] Step2 KGGen starting: %d chunks, per_chunk=%s, log_interval=%s",
                len(all_chunks),
                cfg.KGGEN_PER_CHUNK,
                getattr(cfg, "KGGEN_LOG_CHUNK_INTERVAL", 10),
            )
            kg_result = await asyncio.to_thread(
                extract_kg_from_chunks,
                all_chunks,
                model=kg_llm_model,
                api_base=req.chat_api_url.rstrip("/"),
                api_key=req.api_key,
            )
            log.info(
                "[GraphRAGKB] KGGen → %d entities, %d relations",
                len(kg_result.get("entities", [])),
                len(kg_result.get("relations", [])),
            )
        except Exception as exc:
            log.warning("[GraphRAGKB] KGGen extraction skipped: %s", exc)
    else:
        log.debug("[GraphRAGKB] KGGen skipped (skip_kggen=True)")

    # Step 3 — GraphRAG workspace + indexing
    workspace_dir = req.workspace_dir or _default_workspace_dir(req)
    log.info("[GraphRAGKB] Step3 GraphRAG index → %s", workspace_dir)
    ws = await asyncio.to_thread(
        build_index,
        all_chunks,
        workspace_dir,
        llm_model=req.model or cfg.GRAPHRAG_LLM_MODEL,
        embedding_model=cfg.GRAPHRAG_EMBEDDING_MODEL,
        api_base=req.chat_api_url.rstrip("/"),
        api_key=req.api_key,
        force_reindex=req.force_reindex,
    )

    state.agent_results["index"] = {
        "workspace_dir": str(ws.root),
        "num_chunks": len(all_chunks),
        "kg_entities": len(kg_result.get("entities", [])) if kg_result else 0,
        "kg_relations": len(kg_result.get("relations", [])) if kg_result else 0,
    }


async def _action_query(state: GraphRAGKBState) -> None:
    """GraphRAG query → optional prune+Judge（单次 LLM）或单独 Judge；写入 ``agent_results["query"]``。"""
    import asyncio
    import time as _time
    from fastapi_app.config.settings import settings as cfg
    from workflow_engine.toolkits.graphrag_ms_tool.indexer import GraphRAGWorkspace
    from workflow_engine.toolkits.graphrag_ms_tool.querier import query_local, query_global
    from workflow_engine.toolkits.graphrag_ms_tool.judge import judge_confidence
    from workflow_engine.toolkits.graphrag_ms_tool.prune_judge_combined import (
        prune_and_judge_combined_llm,
    )

    req = state.request
    workspace_dir = req.workspace_dir or _default_workspace_dir(req)
    ws = GraphRAGWorkspace(root=Path(workspace_dir).resolve())

    search_fn = query_local if req.search_method == "local" else query_global

    t_a0 = _time.perf_counter()
    log.info(
        "[TIMING][A] _action_query START | method=%s | question=%r",
        req.search_method, req.question[:80],
    )

    t_b0 = _time.perf_counter()
    result = await asyncio.to_thread(
        search_fn,
        ws,
        req.question,
        api_base=req.chat_api_url.rstrip("/"),
        api_key=req.api_key,
    )
    t_b1 = _time.perf_counter()
    log.info(
        "[TIMING][A→B] search(%s) done | elapsed=%.3fs | answer_len=%d | subgraph_edges=%d",
        req.search_method, t_b1 - t_b0, len(result.answer or ""), len(result.reasoning_subgraph),
    )

    reasoning_subgraph_cot = ""
    judge = None
    did_prune_judge_combined = False
    t_c0 = t_b1
    if cfg.GRAPHRAG_SUBGRAPH_PRUNE_ENABLED and result.reasoning_subgraph:
        did_prune_judge_combined = True
        t_c0 = _time.perf_counter()
        log.info(
            "[TIMING][A→CJ] prune_judge_combined START | edges_in=%d",
            len(result.reasoning_subgraph),
        )
        pj = await asyncio.to_thread(
            prune_and_judge_combined_llm,
            req.question,
            result.answer,
            result.reasoning_subgraph,
            api_base=req.chat_api_url.rstrip("/"),
            api_key=req.api_key,
            max_edges_input=int(cfg.GRAPHRAG_SUBGRAPH_PRUNE_MAX_EDGES_INPUT),
            max_tokens=int(getattr(cfg, "GRAPHRAG_PRUNE_JUDGE_MAX_TOKENS", 768) or 768),
        )
        result.reasoning_subgraph = pj.edges
        reasoning_subgraph_cot = pj.cot
        judge = pj.judge
        t_c1 = _time.perf_counter()
        log.info(
            "[TIMING][A→CJ] prune_judge_combined done | elapsed=%.3fs | edges_out=%d | score=%.3f",
            t_c1 - t_c0,
            len(pj.edges),
            judge.score,
        )
    else:
        t_c1 = t_b1
        log.info("[TIMING][A→CJ] prune_judge SKIPPED (disabled or no edges)")

    t_d0 = _time.perf_counter()
    if judge is None:
        judge = await asyncio.to_thread(
            judge_confidence,
            req.question,
            result.answer,
            result.reasoning_subgraph,
            api_base=req.chat_api_url.rstrip("/"),
            api_key=req.api_key,
        )
    t_d1 = _time.perf_counter()
    log.info("[TIMING][A→D] judge path done | elapsed=%.3fs | score=%.3f", t_d1 - t_d0, judge.score)

    post_search_llm = (t_c1 - t_c0) if did_prune_judge_combined else (t_d1 - t_d0)
    t_a1 = _time.perf_counter()
    log.info(
        "[TIMING][A] _action_query SUMMARY | search=%.3fs | post_search_llm=%.3fs | TOTAL=%.3fs",
        t_b1 - t_b0,
        post_search_llm,
        t_a1 - t_a0,
    )

    query_answer = result.answer or ""
    wd_flag = state.request.wikidata_enrich
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
                query_answer = query_answer.rstrip() + "\n\n" + extra
        except Exception as exc:
            log.warning("[GraphRAGKB] Wikidata enrich failed: %s", exc)

    state.agent_results["query"] = {
        "answer": query_answer,
        "context_data": result.context_data,
        "reasoning_subgraph": result.reasoning_subgraph,
        "reasoning_subgraph_cot": reasoning_subgraph_cot,
        "source_chunks": result.source_chunks,
        "highlight_hints": result.highlight_hints,
        "judge_score": judge.score,
        "judge_rationale": judge.rationale,
    }


async def _action_merge(state: GraphRAGKBState) -> None:
    """Reconstruct chunks from two workspaces, re-index into ``{ws_a}_merged``; writes ``agent_results["merge"]``."""
    import asyncio
    from fastapi_app.config.settings import settings as cfg
    from workflow_engine.toolkits.graphrag_ms_tool.indexer import GraphRAGWorkspace, build_index

    req = state.request
    ws_a = GraphRAGWorkspace(root=Path(req.workspace_dir).resolve())
    ws_b = GraphRAGWorkspace(root=Path(req.workspace_dir_b).resolve())

    all_chunks: List[Dict[str, Any]] = []
    _chunk_pattern = re.compile(r"\[chunk:([a-f0-9]+)\]\n")

    for ws in (ws_a, ws_b):
        meta = ws.load_chunk_meta()
        for txt in ws.input_dir.glob("*.txt"):
            stem = txt.stem
            text = txt.read_text(encoding="utf-8")
            # Reconstruct chunks from embedded [chunk:ID] markers
            parts = _chunk_pattern.split(text)
            # parts = ['', cid1, text1, cid2, text2, ...]
            i = 1
            while i + 1 < len(parts):
                cid = parts[i].strip()
                chunk_text = parts[i + 1].strip()
                m = meta.get(cid, {})
                all_chunks.append(
                    {
                        "chunk_id": cid,
                        "text": chunk_text,
                        "page_index": m.get("page_index", -1),
                        "order": m.get("order", -1),
                        "bbox": m.get("bbox"),
                        "source_stem": m.get("source_stem", stem),
                    }
                )
                i += 2

    if not all_chunks:
        raise ValueError("No chunks found in either workspace.")

    merged_dir = str(ws_a.root) + "_merged"
    ws_merged = await asyncio.to_thread(
        build_index,
        all_chunks,
        merged_dir,
        llm_model=req.model or cfg.GRAPHRAG_LLM_MODEL,
        embedding_model=cfg.GRAPHRAG_EMBEDDING_MODEL,
        api_base=req.chat_api_url.rstrip("/"),
        api_key=req.api_key,
        force_reindex=True,
    )

    state.agent_results["merge"] = {
        "merged_workspace_dir": str(ws_merged.root),
        "num_chunks": len(all_chunks),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_mineru_parsed(manager: Any, nb_paths: Any, sources: list, force: bool) -> None:
    """Run MinerU on PDF sources that have not been parsed yet.

    Skips sources that already have a ``mineru/`` directory (unless *force*
    is True, which re-runs MinerU and regenerates the unified markdown).

    Non-PDF sources are silently skipped.
    """
    import asyncio

    for src in sources:
        if src.file_type != "pdf":
            continue

        already_parsed = manager.get_mineru_root(src.stem) is not None
        if already_parsed and not force:
            log.info("[GraphRAGKB] MinerU already done for %s — skipping", src.stem)
            continue

        orig = manager.get_original_path(src.stem)
        if not orig or not orig.exists():
            log.warning("[GraphRAGKB] Original PDF not found for %s — skipping MinerU", src.stem)
            continue

        mineru_dir = nb_paths.source_mineru_dir(orig.name)
        mineru_dir.mkdir(parents=True, exist_ok=True)
        log.info("[GraphRAGKB] Running MinerU on %s …", orig.name)
        try:
            await manager._run_mineru(orig, mineru_dir)
        except Exception as exc:
            log.warning("[GraphRAGKB] MinerU failed for %s: %s", orig.name, exc)
            continue

        # Regenerate unified markdown now that MinerU output exists
        md_text = manager._generate_markdown(orig, ".pdf", mineru_dir)
        if md_text:
            md_dir = nb_paths.source_markdown_dir(orig.name)
            md_dir.mkdir(parents=True, exist_ok=True)
            (md_dir / f"{src.stem}.md").write_text(md_text, encoding="utf-8")
        log.info("[GraphRAGKB] MinerU + markdown done for %s", orig.name)


def _default_workspace_dir(req: GraphRAGKBRequest) -> str:
    """Build default workspace path from ``GRAPHRAG_OUTPUT_DIR`` / sanitized email / notebook id."""
    from workflow_engine.utils import get_project_root
    from fastapi_app.config.settings import settings as cfg
    from fastapi_app.notebook_paths import _sanitize_user_id

    root = get_project_root()
    safe_email = _sanitize_user_id(req.email) if req.email else "local"
    nb_id = (req.notebook_id or "default").replace("/", "_")[:64]
    return str(root / cfg.GRAPHRAG_OUTPUT_DIR / safe_email / nb_id)
