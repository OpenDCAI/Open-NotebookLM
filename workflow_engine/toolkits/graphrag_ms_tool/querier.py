"""GraphRAG 查询封装：本地/全局检索 + 证据打包（与计划 §3.3 / §4.3 契约一致）。

【QueryResult 字段含义】
    answer               模型生成的自然语言回答（已去掉末尾 ``[Data:…]`` 引用尾标）
    context_data         GraphRAG ``SearchResult.context_data`` 序列化后的表（实体、关系、text_units 等）
    reasoning_subgraph   从 ``relationships``（或兼容键）归纳出的边列表，供 Judge 与子图裁剪
    source_chunks        从证据文本中正则提取的 ``[chunk:十六进制]`` → chunk_id 列表（去重保序）
    highlight_hints      每个 chunk_id 经 ``chunk_meta.json`` 映射得到的 ``{chunk_id, source_stem, page_index, bbox?}``

【执行路径】
    优先 ``graphrag.api.local_search`` / ``global_search``（与 CLI 同源配置）；
    失败则回退 ``graphrag query`` 子进程。**CLI 回退时只有 answer**，其余证据字段为空。

【数据流】
    索引阶段写入的 ``[chunk:ID]`` 会出现在检索上下文的 text_units 文本中 →
    ``_extract_source_chunks`` 收集 ID → ``_build_highlight_hints`` 查 meta → 前端「文档定位」。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_engine.logger import get_logger
from workflow_engine.toolkits.graphrag_ms_tool.indexer import (
    GraphRAGWorkspace,
    _patch_settings_yaml,
)

log = get_logger(__name__)


def _strip_graphrag_data_citation_suffix(answer: str) -> str:
    """去掉 GraphRAG 默认拼在回答末尾的 ``[Data: Entities (…); Relationships (…); …]`` 内部引用标记。"""
    if not (answer and answer.strip()):
        return answer
    return re.sub(r"(?:\s*\[Data:[^\]]+\])+\s*$", "", answer.strip())


def _coalesce_ctx(ctx: Dict[str, Any], *keys: str) -> Any:
    """返回 ``ctx`` 中按 *keys* 顺序第一个非 ``None`` 的值。

    注意：不能用 ``a or b`` 合并 DataFrame，pandas 在布尔上下文会抛错，故显式遍历键名。
    """
    for k in keys:
        v = ctx.get(k)
        if v is not None:
            return v
    return None


@dataclass
class QueryResult:
    """Structured result of a single GraphRAG query.

    answer: cleaned response text (GraphRAG [Data:...] citation suffix stripped).
    context_data: serialised tables from SearchResult (entities, relationships, sources).
    reasoning_subgraph: edge list [{source, target, relation, weight}] for visualisation.
    source_chunks: chunk_ids extracted from context text_units, deduplicated in order.
    highlight_hints: [{chunk_id, source_stem, page_index, bbox?}] from chunk_meta.json.
    """

    answer: str
    context_data: Dict[str, Any] = field(default_factory=dict)
    reasoning_subgraph: List[Dict[str, Any]] = field(default_factory=list)
    source_chunks: List[str] = field(default_factory=list)
    highlight_hints: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 对外 API：local / global 查询入口
# ---------------------------------------------------------------------------

def query_local(
    workspace: GraphRAGWorkspace,
    question: str,
    *,
    llm_model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    graphrag_cmd: Optional[str] = None,
) -> QueryResult:
    """Local search: answer around the most relevant entity/community subgraph.

    Best for factual, entity-specific questions. Falls back to CLI if Python API fails
    (CLI returns answer only; context_data and highlight_hints will be empty).
    """
    return _run_query(
        workspace, question, method="local",
        llm_model=llm_model, api_base=api_base, api_key=api_key,
        graphrag_cmd=graphrag_cmd,
    )


def query_global(
    workspace: GraphRAGWorkspace,
    question: str,
    *,
    llm_model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    graphrag_cmd: Optional[str] = None,
) -> QueryResult:
    """Global search: summarise across all community reports.

    Best for thematic / overview questions. source_chunks and highlight_hints are
    typically empty because global search does not return text_units.
    """
    return _run_query(
        workspace, question, method="global",
        llm_model=llm_model, api_base=api_base, api_key=api_key,
        graphrag_cmd=graphrag_cmd,
    )


# ---------------------------------------------------------------------------
# 内部实现：Python API / CLI、结果解析与子图/chunk 归纳
# ---------------------------------------------------------------------------

def _run_query(
    workspace: GraphRAGWorkspace,
    question: str,
    method: str,
    *,
    llm_model: Optional[str],
    api_base: Optional[str],
    api_key: Optional[str],
    graphrag_cmd: Optional[str],
) -> QueryResult:
    from fastapi_app.config.settings import settings as cfg

    llm_model = llm_model or cfg.GRAPHRAG_LLM_MODEL
    api_base = api_base or cfg.DEFAULT_LLM_API_URL.rstrip("/")
    api_key = api_key or os.getenv("DF_API_KEY", "")

    # Try Python API first
    try:
        return _query_via_python_api(
            workspace, question, method, llm_model, api_base, api_key
        )
    except Exception as exc:
        log.warning(
            "[GraphRAGQuerier] Python API query failed (%s); falling back to CLI: %s",
            method, exc,
        )

    # Fall back to CLI
    return _query_via_cli(workspace, question, method, graphrag_cmd, cfg)


def _query_via_python_api(
    workspace: GraphRAGWorkspace,
    question: str,
    method: str,
    llm_model: str,
    api_base: str,
    api_key: str,
) -> QueryResult:
    """经 GraphRAG **2.7.x** 的 ``graphrag.api`` 异步检索（与 ``graphrag query`` CLI 同源配置与输出）。

    会先 ``_patch_settings_yaml`` 刷新密钥与模型，再 ``load_config`` + ``local_search``/``global_search``，
    最后 ``_parse_search_result`` 打包证据。
    """
    import asyncio
    from types import SimpleNamespace

    try:
        from graphrag.config.load_config import load_config
        from graphrag import api as graphrag_api
        from graphrag.cli.query import _resolve_output_files
    except ImportError as exc:
        raise ImportError(
            "graphrag 2.7.x is required for the Python query path. "
            "Install: pip install graphrag==2.7.2"
        ) from exc

    from fastapi_app.config.settings import settings as cfg

    if not workspace.settings_path.is_file():
        raise FileNotFoundError(f"Missing GraphRAG settings: {workspace.settings_path}")

    # Refresh credentials in workspace yaml so query uses the current request keys.
    _patch_settings_yaml(
        workspace.settings_path,
        api_key=api_key,
        api_base=api_base,
        llm_model=llm_model,
        embedding_model=cfg.GRAPHRAG_EMBEDDING_MODEL,
        chunk_size=int(cfg.GRAPHRAG_CHUNK_SIZE),
        chunk_overlap=int(cfg.GRAPHRAG_CHUNK_OVERLAP),
    )

    # graphrag 3.x: load_config(root_dir, cli_overrides=...); 2.7.x accepts config_filepath=
    _lc_sig = inspect.signature(load_config)
    _lc_kw: Dict[str, Any] = {"cli_overrides": {}}
    if "config_filepath" in _lc_sig.parameters:
        _lc_kw["config_filepath"] = None
    config = load_config(workspace.root.resolve(), **_lc_kw)

    community_level = 2
    response_type = str(cfg.GRAPHRAG_RESPONSE_TYPE or "Single Paragraph").strip() or "Single Paragraph"

    if method == "local":
        df = _resolve_output_files(
            config=config,
            output_list=[
                "communities",
                "community_reports",
                "text_units",
                "relationships",
                "entities",
            ],
            optional_list=["covariates"],
        )
        if df.get("multi-index"):
            raise RuntimeError("Multi-index GraphRAG workspaces are not supported by this adapter.")
        response, context_data = asyncio.run(
            graphrag_api.local_search(
                config=config,
                entities=df["entities"],
                communities=df["communities"],
                community_reports=df["community_reports"],
                text_units=df["text_units"],
                relationships=df["relationships"],
                covariates=df.get("covariates"),
                community_level=community_level,
                response_type=response_type,
                query=question,
                verbose=False,
            )
        )
    elif method == "global":
        df = _resolve_output_files(
            config=config,
            output_list=["entities", "communities", "community_reports"],
            optional_list=[],
        )
        if df.get("multi-index"):
            raise RuntimeError("Multi-index GraphRAG workspaces are not supported by this adapter.")
        response, context_data = asyncio.run(
            graphrag_api.global_search(
                config=config,
                entities=df["entities"],
                communities=df["communities"],
                community_reports=df["community_reports"],
                community_level=community_level,
                dynamic_community_selection=False,
                response_type=response_type,
                query=question,
                verbose=False,
            )
        )
    else:
        raise ValueError(f"Unknown search method: {method}")

    if not isinstance(context_data, dict):
        context_data = {}

    wrapped = SimpleNamespace(response=response or "", context_data=context_data)
    return _parse_search_result(wrapped, workspace)


def _query_via_cli(
    workspace: GraphRAGWorkspace,
    question: str,
    method: str,
    graphrag_cmd: Optional[str],
    cfg: Any,
) -> QueryResult:
    """CLI 回退：仅解析标准输出为 ``answer``，无 ``context_data``，故子图/chunk 均为空。"""
    cmd = (
        graphrag_cmd
        or cfg.GRAPHRAG_CMD.strip()
        or shutil.which("graphrag")
    )
    if not cmd:
        raise RuntimeError(
            "graphrag CLI not found. Install graphrag or set GRAPHRAG_CMD."
        )

    proc = subprocess.run(
        [cmd, "query", "--root", str(workspace.root), "--method", method, "--query", question],
        capture_output=True,
        text=True,
        check=False,
    )
    answer = proc.stdout.strip() or proc.stderr.strip()
    answer = _strip_graphrag_data_citation_suffix(answer)
    log.info("[GraphRAGQuerier] CLI answer (%s): %s …", method, answer[:120])
    return QueryResult(answer=answer)


def _parse_search_result(result: Any, workspace: GraphRAGWorkspace) -> QueryResult:
    """将 GraphRAG API 返回的 ``response`` + ``context_data`` 转为本项目的 ``QueryResult``。

    步骤：清洗 answer → DataFrame 转可 JSON 的 list → 归纳子图 → 提取 chunk → 查 meta 生成高亮提示。
    """
    answer = _strip_graphrag_data_citation_suffix(getattr(result, "response", "") or "")
    ctx: Dict[str, Any] = getattr(result, "context_data", {}) or {}

    # Serialise DataFrames → dicts for JSON transport
    ctx_serialised: Dict[str, Any] = {}
    for key, val in ctx.items():
        try:
            import pandas as pd
            if isinstance(val, pd.DataFrame):
                ctx_serialised[key] = json.loads(val.to_json(orient="records", force_ascii=False))
            else:
                ctx_serialised[key] = val
        except Exception:
            ctx_serialised[key] = str(val)

    # Reasoning subgraph: induce from entities + relationships tables
    reasoning_subgraph = _induce_subgraph(ctx)

    # Source chunks: extract chunk_ids from text_units Sources table
    source_chunks = _extract_source_chunks(ctx, workspace)

    # Highlight hints: map chunk_ids back to page/bbox via chunk_meta
    highlight_hints = _build_highlight_hints(source_chunks, workspace)

    return QueryResult(
        answer=answer,
        context_data=ctx_serialised,
        reasoning_subgraph=reasoning_subgraph,
        source_chunks=source_chunks,
        highlight_hints=highlight_hints,
    )


def _induce_subgraph(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 ``context_data`` 的 ``relationships``（或 ``relations``）表中归纳有向边列表。

    兼容 DataFrame 与已序列化的 ``list[dict]``；边字段统一为 source/target/relation/weight。
    """
    edges: List[Dict[str, Any]] = []
    try:
        import pandas as pd
        rels = _coalesce_ctx(ctx, "relationships", "relations")
        if rels is None:
            return edges
        # GraphRAG Python API typically returns DataFrames, but some adapters / JSON
        # serialisation paths may already convert them to list[dict]. Support both.
        if isinstance(rels, pd.DataFrame):
            rows = rels.to_dict(orient="records")
        elif isinstance(rels, list):
            rows = [r for r in rels if isinstance(r, dict)]
        else:
            rows = []

        for row in rows:
            src = row.get("source") or row.get("source_id") or row.get("head") or row.get("from")
            tgt = row.get("target") or row.get("target_id") or row.get("tail") or row.get("to")
            rel = (
                row.get("description")
                or row.get("relationship")
                or row.get("relation")
                or row.get("predicate")
                or row.get("label")
                or ""
            )
            w = row.get("weight", 1.0)
            try:
                w_f = float(w)  # may be str in JSON payloads
            except Exception:
                w_f = 1.0
            edges.append(
                {
                    "source": str(src or ""),
                    "target": str(tgt or ""),
                    "relation": str(rel or ""),
                    "weight": w_f,
                }
            )
    except Exception as exc:
        log.debug("[GraphRAGQuerier] subgraph induction failed: %s", exc)
    return edges


def _extract_source_chunks(ctx: Dict[str, Any], workspace: GraphRAGWorkspace) -> List[str]:
    """Extract [chunk:ID] markers from retrieved text_units, deduplicated in context order.

    The markers were embedded by indexer.build_index and preserved through text_units.parquet.
    Returns at most GRAPHRAG_MAX_HIGHLIGHT_HINTS ids (0 = unlimited).
    """
    from fastapi_app.config.settings import settings as cfg

    chunk_ids: List[str] = []
    try:
        import pandas as pd
        sources = _coalesce_ctx(ctx, "sources", "text_units")
        if sources is None:
            return chunk_ids
        if isinstance(sources, pd.DataFrame):
            rows = sources.to_dict(orient="records")
        else:
            rows = sources if isinstance(sources, list) else []
        pattern = re.compile(r"\[chunk:([a-f0-9]+)\]")
        for row in rows:
            text = str(row.get("text") or row.get("content") or "")
            chunk_ids.extend(pattern.findall(text))
        seen: set[str] = set()
        deduped = []
        for cid in chunk_ids:
            if cid not in seen:
                seen.add(cid)
                deduped.append(cid)
        max_n = int(getattr(cfg, "GRAPHRAG_MAX_HIGHLIGHT_HINTS", 10) or 0)
        if max_n > 0 and len(deduped) > max_n:
            deduped = deduped[:max_n]
        return deduped
    except Exception as exc:
        log.debug("[GraphRAGQuerier] source_chunks extraction failed: %s", exc)
    return chunk_ids


def _build_highlight_hints(
    chunk_ids: List[str],
    workspace: GraphRAGWorkspace,
) -> List[Dict[str, Any]]:
    """Map chunk_ids to document location hints by looking up chunk_meta.json.

    Returns [{chunk_id, source_stem, page_index, bbox?}] for the frontend PDF viewer.
    chunk_ids not found in chunk_meta are silently skipped.
    """
    if not chunk_ids:
        return []
    meta = workspace.load_chunk_meta()
    hints = []
    for cid in chunk_ids:
        m = meta.get(cid)
        if not m:
            continue  # chunk_id 在 meta 中找不到时跳过（可能是旧索引遗留）
        hint: Dict[str, Any] = {
            "chunk_id": cid,
            "source_stem": m.get("source_stem", ""),
            "page_index": m.get("page_index", -1),
        }
        bbox = m.get("bbox")
        if bbox:
            hint["bbox"] = bbox
        hints.append(hint)
    return hints
