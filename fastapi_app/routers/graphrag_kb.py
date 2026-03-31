"""GraphRAG 知识库 HTTP 路由（前缀在 ``main`` 中与 ``/api/v1`` 拼接）。

【端点与数据流】
    POST ``/graphrag-kb/index``  → ``wa_graphrag_kb.run_index`` → 建索引 → ``IndexResponse``
    POST ``/graphrag-kb/query``   → ``run_query`` → 检索 + Judge（+ 子图 CoT）→ ``QueryResponse``
    POST ``/graphrag-kb/merge``  → ``run_merge`` → 合并两 workspace → ``MergeResponse``
    POST ``/graphrag-kb/chunk-snippet`` → 按 ``chunk_id`` 从 workspace ``input/*.txt`` 抽取 ``[chunk:…]`` 块正文（供前端阅读器高亮）

【安全】
    ``_safe_workspace_dir`` 将路径解析到项目根目录下，防止目录穿越。

【说明】
    请求体携带与其它路由一致的 LLM 凭证；前端不直连 ``workflow_engine``，仅调本路由。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fastapi_app.config import settings
from fastapi_app.workflow_adapters.wa_graphrag_kb import run_index, run_query, run_merge
from workflow_engine.logger import get_logger
from workflow_engine.utils import get_project_root

log = get_logger(__name__)

# 匹配 GraphRAG input 文件中每个 chunk 段的起始行（后跟该段正文直至下一 chunk 或 EOF）
_CHUNK_HEAD = re.compile(r"\[chunk:([a-f0-9]+)\]\s*\n", re.IGNORECASE)


def _extract_chunk_block_from_input_text(text: str, chunk_id: str) -> str:
    """在整份 ``input/<stem>.txt`` 文本中，定位 ``[chunk:目标id]`` 之后到下一 ``[chunk:`` 之前的正文。"""
    want = chunk_id.strip().lower()
    matches = list(_CHUNK_HEAD.finditer(text))
    for i, m in enumerate(matches):
        if m.group(1).lower() != want:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        return text[start:end].strip()
    return ""


def _safe_workspace_dir(raw: str) -> Path:
    """将 *raw* 解析为项目根目录下的绝对路径；越界则抛 ``HTTPException(400)``。"""
    root = get_project_root().resolve()
    p = Path(raw.strip())
    if not p.is_absolute():
        p = (root / p).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="workspace_dir must be under project root") from exc
    return p

router = APIRouter(prefix="/graphrag-kb", tags=["GraphRAG KB"])

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class _LLMBase(BaseModel):
    api_url: str = Field(default_factory=lambda: settings.DEFAULT_LLM_API_URL)
    api_key: str = ""
    model: str = Field(default_factory=lambda: settings.GRAPHRAG_LLM_MODEL)


class IndexRequest(_LLMBase):
    notebook_id: str
    notebook_title: str = ""
    email: str = ""
    source_stems: Optional[List[str]] = None
    workspace_dir: str = ""
    force_reindex: bool = False
    # Run MinerU on un-parsed PDFs before chunk extraction.
    # Set to False if MinerU was already triggered via /kb/upload.
    parse_pdfs: bool = True
    # Default True: do not run KGGen (user-facing path is GraphRAG-only).
    skip_kggen: bool = True


class IndexResponse(BaseModel):
    workspace_dir: str
    num_chunks: int
    kg_entities: int
    kg_relations: int


class QueryRequest(_LLMBase):
    notebook_id: str
    notebook_title: str = ""
    email: str = ""
    question: str
    search_method: str = Field(default="local", pattern="^(local|global)$")
    workspace_dir: str = ""


class QueryResponse(BaseModel):
    answer: str
    context_data: Dict[str, Any] = Field(default_factory=dict)
    reasoning_subgraph: List[Dict[str, Any]] = Field(default_factory=list)
    source_chunks: List[str] = Field(default_factory=list)
    highlight_hints: List[Dict[str, Any]] = Field(default_factory=list)
    judge_score: float = 0.0
    judge_rationale: str = ""
    reasoning_subgraph_cot: str = ""


class MergeRequest(_LLMBase):
    notebook_id: str = ""
    notebook_title: str = ""
    email: str = ""
    workspace_dir_a: str
    workspace_dir_b: str
    dedupe: bool = False


class MergeResponse(BaseModel):
    merged_workspace_dir: str
    num_chunks: int


class ChunkSnippetRequest(BaseModel):
    """Resolve *chunk_id* to raw text inside GraphRAG ``input/<stem>.txt`` markers."""

    workspace_dir: str = Field(..., description="GraphRAG workspace root (contains chunk_meta.json + input/)")
    chunk_id: str = Field(..., min_length=8, description="Hex chunk id from chunk_meta / query")
    # Optional: pass reasoning_subgraph triples so the backend can ask an LLM to pick
    # the exact sentence from the chunk that best expresses one of these relationships.
    triples: Optional[List[Dict[str, Any]]] = None


class ChunkSnippetResponse(BaseModel):
    text: str = ""
    source_stem: str = ""
    found: bool = False
    # LLM-extracted verbatim sentence from the chunk that best matches the triples.
    # Empty string if triples were not provided or LLM extraction failed.
    highlighted_sentence: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _extract_sentence_for_triples(
    chunk_text: str,
    triples: List[Dict[str, Any]],
) -> str:
    """Ask the configured LLM to pick the verbatim sentence from chunk_text that best
    expresses one of the given knowledge-graph triples.  Returns empty string on failure.
    """
    if not chunk_text.strip() or not triples:
        return ""
    try:
        from openai import OpenAI
    except ImportError:
        log.debug("[ChunkSnippet] openai not installed; skipping sentence extraction")
        return ""

    triple_lines = "\n".join(
        f"  ({t.get('source', '?')}) --[{t.get('relation', '?')}]--> ({t.get('target', '?')})"
        for t in triples[:20]
    )
    system_prompt = (
        "You are a precise text extraction assistant. "
        "Return ONLY the verbatim sentence or short phrase from the provided chunk "
        "that best expresses one of the given relationships. "
        "Do NOT paraphrase, add explanation, or include any other text."
    )
    user_msg = (
        f"Knowledge graph relationships:\n{triple_lines}\n\n"
        f"Chunk text:\n{chunk_text}\n\n"
        "Extract the EXACT sentence or phrase from the chunk that best matches "
        "one of the relationships above. Return only that text."
    )
    try:
        api_base = settings.DEFAULT_LLM_API_URL.rstrip("/")
        import os
        api_key = os.getenv("DF_API_KEY", "") or "none"
        client = OpenAI(api_key=api_key, base_url=api_base)
        resp = client.chat.completions.create(
            model=settings.GRAPHRAG_LLM_MODEL,
            max_tokens=256,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
        )
        sentence = (resp.choices[0].message.content or "").strip()
        # Sanity check: LLM must return something that actually appears in the chunk
        if sentence and sentence in chunk_text:
            return sentence
        log.debug("[ChunkSnippet] LLM sentence not found verbatim in chunk; discarding")
        return ""
    except Exception as exc:
        log.warning("[ChunkSnippet] LLM extraction failed: %s", exc)
        return ""


@router.post("/chunk-snippet", response_model=ChunkSnippetResponse, summary="Extract [chunk:…] text from GraphRAG input")
async def chunk_snippet_endpoint(req: ChunkSnippetRequest) -> ChunkSnippetResponse:
    """Used by the notebook reader to show the exact indexed chunk, not the full MinerU MD."""
    ws = _safe_workspace_dir(req.workspace_dir)
    meta_path = ws / "chunk_meta.json"
    if not meta_path.is_file():
        return ChunkSnippetResponse()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return ChunkSnippetResponse()
    cid = req.chunk_id.strip().lower()
    entry = meta.get(req.chunk_id.strip()) or meta.get(cid)
    if not isinstance(entry, dict):
        return ChunkSnippetResponse()
    stem = str(entry.get("source_stem") or "").strip()
    if not stem:
        return ChunkSnippetResponse()
    txt_path = ws / "input" / f"{stem}.txt"
    if not txt_path.is_file():
        return ChunkSnippetResponse(source_stem=stem, found=False)
    try:
        raw = txt_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ChunkSnippetResponse(source_stem=stem, found=False)
    block = _extract_chunk_block_from_input_text(raw, cid)
    if not block:
        return ChunkSnippetResponse(source_stem=stem, found=False)
    highlighted_sentence = ""
    if req.triples:
        highlighted_sentence = _extract_sentence_for_triples(block, req.triples)
    return ChunkSnippetResponse(text=block, source_stem=stem, found=True, highlighted_sentence=highlighted_sentence)


# ---------------------------------------------------------------------------
# Index / query / merge
# ---------------------------------------------------------------------------

@router.post("/index", response_model=IndexResponse, summary="Build GraphRAG index from notebook sources")
async def index_endpoint(req: IndexRequest):
    """Chunk notebook sources and run GraphRAG index (KGGen off by default).

    Requires that sources have already been imported into the notebook
    (via the ``/kb`` upload endpoint) so that MinerU output exists.
    """
    try:
        result = await run_index(
            notebook_id=req.notebook_id,
            notebook_title=req.notebook_title,
            email=req.email,
            api_url=req.api_url,
            api_key=req.api_key,
            model=req.model,
            source_stems=req.source_stems,
            workspace_dir=req.workspace_dir,
            force_reindex=req.force_reindex,
            parse_pdfs=req.parse_pdfs,
            skip_kggen=req.skip_kggen,
        )
        return IndexResponse(
            workspace_dir=result.get("workspace_dir", ""),
            num_chunks=result.get("num_chunks", 0),
            kg_entities=result.get("kg_entities", 0),
            kg_relations=result.get("kg_relations", 0),
        )
    except Exception as exc:
        log.exception("[Router] /graphrag-kb/index error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/query", response_model=QueryResponse, summary="Query GraphRAG index with Judge scoring")
async def query_endpoint(req: QueryRequest):
    """Run a local or global GraphRAG search and return a structured result.

    Returns:
    - ``answer``            — model answer text
    - ``context_data``      — serialised evidence tables (entities, relations, sources…)
    - ``reasoning_subgraph`` — edge list induced from context_data
    - ``source_chunks``     — chunk_ids that contributed to the answer
    - ``highlight_hints``   — page/bbox hints for PDF highlighting
    - ``judge_score``       — confidence score in [0.0, 1.0]
    - ``judge_rationale``   — one-sentence judge explanation
    - ``reasoning_subgraph_cot`` — LLM chain-of-thought for minimal subgraph (hop analysis)
    """
    try:
        result = await run_query(
            notebook_id=req.notebook_id,
            notebook_title=req.notebook_title,
            email=req.email,
            api_url=req.api_url,
            api_key=req.api_key,
            model=req.model,
            question=req.question,
            search_method=req.search_method,
            workspace_dir=req.workspace_dir,
        )
        return QueryResponse(
            answer=result.get("answer", ""),
            context_data=result.get("context_data", {}),
            reasoning_subgraph=result.get("reasoning_subgraph", []),
            source_chunks=result.get("source_chunks", []),
            highlight_hints=result.get("highlight_hints", []),
            judge_score=float(result.get("judge_score", 0.0)),
            judge_rationale=result.get("judge_rationale", ""),
            reasoning_subgraph_cot=result.get("reasoning_subgraph_cot", ""),
        )
    except Exception as exc:
        log.exception("[Router] /graphrag-kb/query error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/merge", response_model=MergeResponse, summary="Merge two GraphRAG KG workspaces")
async def merge_endpoint(req: MergeRequest):
    """Merge two GraphRAG workspaces using KGGen aggregate and re-index.

    Both ``workspace_dir_a`` and ``workspace_dir_b`` must be absolute paths to
    valid, previously indexed workspaces.  The merged workspace is written to
    ``{workspace_dir_a}_merged/``.
    """
    try:
        result = await run_merge(
            notebook_id=req.notebook_id,
            notebook_title=req.notebook_title,
            email=req.email,
            api_url=req.api_url,
            api_key=req.api_key,
            model=req.model,
            workspace_dir_a=req.workspace_dir_a,
            workspace_dir_b=req.workspace_dir_b,
            dedupe=req.dedupe,
        )
        return MergeResponse(
            merged_workspace_dir=result.get("merged_workspace_dir", ""),
            num_chunks=result.get("num_chunks", 0),
        )
    except Exception as exc:
        log.exception("[Router] /graphrag-kb/merge error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
