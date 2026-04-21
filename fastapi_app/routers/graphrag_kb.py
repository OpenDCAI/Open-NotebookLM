"""GraphRAG 知识库 HTTP 路由（前缀在 ``main`` 中与 ``/api/v1`` 拼接）。

【端点与数据流】
    POST ``/graphrag-kb/index``  → ``wa_graphrag_kb.run_index`` → 建索引 → ``IndexResponse``
    POST ``/graphrag-kb/query``   → ``run_query`` → 检索 + Judge（+ 子图 CoT）→ ``QueryResponse``
    POST ``/graphrag-kb/merge``  → ``run_merge`` → 合并两 workspace → ``MergeResponse``
    POST ``/graphrag-kb/chunk-snippet`` → 按 ``chunk_id`` 从 ``input/*.txt`` 取块；可选 ``passage_for_llm`` 与 UI 文段对齐后做抽句高亮
    POST ``/graphrag-kb/context-refine`` → 首条 text_unit 原文 + ``reasoning_subgraph`` → LLM 清洗噪声并返回 ``cleaned_text`` + ``supporting_snippets``

【安全】
    ``_safe_workspace_dir`` 将路径解析到项目根目录下，防止目录穿越。

【说明】
    请求体携带与其它路由一致的 LLM 凭证；前端不直连 ``workflow_engine``，仅调本路由。
"""
from __future__ import annotations

import json
import re
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fastapi_app.config import settings
from fastapi_app.workflow_adapters.wa_graphrag_kb import run_index, run_query, run_merge, run_chat
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


def _reanchor_graphrag_workspace_to_root(resolved_abs: Path, root: Path) -> Optional[Path]:
    """If *resolved_abs* points at another clone (browser localStorage) but shares
    ``outputs/graphrag_kb/<tail>`` with this repo, map to ``root / outputs/graphrag_kb/<tail>``.

    Returns a path under *root* only if that directory exists; otherwise ``None``.
    """
    parts = resolved_abs.parts
    for i in range(len(parts) - 1):
        if parts[i] == "outputs" and parts[i + 1] == "graphrag_kb":
            tail = Path(*parts[i:])
            candidate = (root / tail).resolve()
            if not candidate.is_dir():
                return None
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                return None
    return None


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
        return p
    except ValueError as exc:
        alt = _reanchor_graphrag_workspace_to_root(p, root)
        if alt is not None:
            return alt
        raise HTTPException(status_code=400, detail="workspace_dir must be under project root") from exc

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
    # None: use server GRAPHRAG_WIKIDATA_ENRICH_ENABLED; False: skip Wikidata appendix
    wikidata_enrich: Optional[bool] = None


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


class ChatRequest(_LLMBase):
    notebook_id: str
    notebook_title: str = ""
    email: str = ""
    query: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    search_method: str = Field(default="auto", pattern="^(auto|local|global)$")
    workspace_dir: str = ""
    wikidata_enrich: Optional[bool] = None
    defer_postprocess: bool = False


class ChatResponse(BaseModel):
    answer: str
    intent: Dict[str, Any] = Field(default_factory=dict)
    rewritten_query: str = ""
    context_data: Dict[str, Any] = Field(default_factory=dict)
    reasoning_subgraph: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_subgraph_cot: str = ""
    source_chunks: List[str] = Field(default_factory=list)
    highlight_hints: List[Dict[str, Any]] = Field(default_factory=list)
    judge_score: float = 0.0
    judge_rationale: str = ""
    postprocess_pending: bool = False
    graphrag_raw_answer: str = ""


class ChatPostprocessRequest(_LLMBase):
    query: str
    answer: str = ""
    reasoning_subgraph: List[Dict[str, Any]] = Field(default_factory=list)
    wikidata_enrich: Optional[bool] = None
    mode: str = Field(default="subgraph", pattern="^(all|subgraph|wikidata)$")


class ChatPostprocessResponse(BaseModel):
    reasoning_subgraph: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_subgraph_cot: str = ""
    judge_score: float = 0.0
    judge_rationale: str = ""
    wikidata_appendix: str = ""
    subgraph_done: bool = False
    wikidata_done: bool = False
    done: bool = True


class ChunkSnippetRequest(BaseModel):
    """Resolve *chunk_id* to raw text inside GraphRAG ``input/<stem>.txt`` markers."""

    workspace_dir: str = Field(..., description="GraphRAG workspace root (contains chunk_meta.json + input/)")
    chunk_id: str = Field(..., min_length=8, description="Hex chunk id from chunk_meta / query")
    # LLM credentials forwarded from the frontend (same key/url used by query/index).
    api_key: str = ""
    api_url: str = ""
    # Optional: pass reasoning_subgraph triples so the backend can ask an LLM to pick
    # the exact sentence from the chunk that best expresses one of these relationships.
    triples: Optional[List[Dict[str, Any]]] = None
    # Optional: same passage as shown in UI (e.g. stripped text_units[0].text). When set,
    # LLM extraction uses this instead of the raw ``input/*.txt`` block so highlights align with the box.
    passage_for_llm: Optional[str] = Field(
        default=None,
        max_length=120_000,
        description="Context passage for highlight LLM; must be substring-compatible with indexed chunk",
    )


class ChunkSnippetResponse(BaseModel):
    text: str = ""
    source_stem: str = ""
    found: bool = False
    # LLM-extracted verbatim sentence from the chunk that best matches the triples.
    # Empty string if triples were not provided or LLM extraction failed.
    highlighted_sentence: str = ""


class ContextRefineRequest(BaseModel):
    """First retrieval text unit + reasoning subgraph → LLM cleans noise + picks supporting quotes."""

    unit_text: str = Field(..., max_length=150_000, description="Raw text from context_data first Sources row")
    subgraph: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="reasoning_subgraph edges: source/target/relation",
    )
    api_key: str = ""
    api_url: str = ""
    model: str = Field(default_factory=lambda: settings.GRAPHRAG_LLM_MODEL)


class ContextRefineResponse(BaseModel):
    cleaned_text: str = ""
    supporting_snippets: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _extract_sentence_for_triples(
    chunk_text: str,
    triples: List[Dict[str, Any]],
    *,
    api_key: str = "",
    api_url: str = "",
) -> str:
    """Ask the configured LLM to pick the verbatim sentence from *chunk_text* that best
    expresses one of the given triples. *chunk_text* may be the indexed ``input/*.txt``
    block or the UI passage (e.g. stripped ``text_units`` row) for alignment with highlights.
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
        import os
        resolved_key = api_key.strip() or os.getenv("DF_API_KEY", "") or "none"
        api_base = (api_url.strip() or settings.DEFAULT_LLM_API_URL).rstrip("/")
        client = OpenAI(api_key=resolved_key, base_url=api_base)
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


def _refine_context_unit_with_llm(
    unit_text: str,
    subgraph: List[Dict[str, Any]],
    *,
    api_key: str,
    api_url: str,
    model: str,
) -> tuple[str, List[str]]:
    """Return (cleaned_text, supporting_snippets) from raw first-unit text + subgraph edges."""
    raw = (unit_text or "").strip()
    if not raw:
        return "", []
    if not subgraph:
        return raw, []

    edge_lines: List[str] = []
    for i, e in enumerate(subgraph[:80], start=1):
        if not isinstance(e, dict):
            continue
        s = str(e.get("source") or "").strip()
        t = str(e.get("target") or "").strip()
        r = str(e.get("relation") or "").strip()
        if not (s and t):
            continue
        edge_lines.append(f"{i}. ({s}) -[{r}]-> ({t})")
    if not edge_lines:
        return raw, []

    system = (
        "You clean noisy document excerpts and select supporting quotes for a knowledge-graph subgraph.\n"
        "Return ONLY valid JSON with keys: cleaned_text (string), supporting_snippets (array of strings).\n"
        "Rules:\n"
        "- cleaned_text: remove footers, URLs, page numbers, repeated headers, [chunk:...] / [Data:...] lines, "
        "and other boilerplate. Preserve the substantive prose in reading order. Do not invent content.\n"
        "- supporting_snippets: 1–6 short verbatim quotes from cleaned_text (exact substrings) that best "
        "support the given subgraph edges (entities/relations). Each snippet should be one sentence or clause; "
        "prefer distinct non-overlapping snippets.\n"
        "- If nothing in the passage supports the subgraph, use an empty supporting_snippets array.\n"
        "- Output JSON only, no markdown fences."
    )
    user_msg = "raw_passage:\n" + raw[:120_000] + "\n\nsubgraph_edges:\n" + "\n".join(edge_lines)

    try:
        from openai import OpenAI
        import os

        resolved_key = api_key.strip() or os.getenv("DF_API_KEY", "") or "none"
        api_base = (api_url.strip() or settings.DEFAULT_LLM_API_URL).rstrip("/")
        client = OpenAI(api_key=resolved_key, base_url=api_base)
        mdl = (model or "").strip() or settings.GRAPHRAG_LLM_MODEL
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        try:
            comp = client.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"},
            )
        except Exception:
            comp = client.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=0.1,
                max_tokens=8192,
            )
        choice = (comp.choices[0].message.content or "").strip()
        if choice.startswith("```"):
            choice = re.sub(r"^```(?:json)?\s*", "", choice, flags=re.I)
            choice = re.sub(r"\s*```\s*$", "", choice).strip()
        try:
            data = json.loads(choice)
        except json.JSONDecodeError:
            i, j = choice.find("{"), choice.rfind("}")
            if i < 0 or j <= i:
                return raw, []
            try:
                data = json.loads(choice[i : j + 1])
            except json.JSONDecodeError:
                return raw, []
        if not isinstance(data, dict):
            return raw, []
        cleaned = str(data.get("cleaned_text") or "").strip()
        snips_raw = data.get("supporting_snippets")
        snips: List[str] = []
        if isinstance(snips_raw, list):
            for x in snips_raw[:12]:
                if isinstance(x, str) and x.strip():
                    snips.append(x.strip())
        if not cleaned:
            cleaned = raw
        validated: List[str] = []
        for s in snips:
            if s in cleaned:
                validated.append(s)
                continue
            s2 = " ".join(s.split())
            if s2 in cleaned:
                validated.append(s2)
        return cleaned, validated[:6]
    except Exception as exc:
        log.warning("[ContextRefine] LLM refine failed: %s", exc)
        return raw, []


@router.post("/chat", response_model=ChatResponse, summary="GraphRAG conversational chat with intent detection")
async def chat_endpoint(req: ChatRequest):
    """Multi-turn GraphRAG chat with intent detection, query rewriting, and answer synthesis."""
    try:
        result = await run_chat(
            notebook_id=req.notebook_id,
            notebook_title=req.notebook_title,
            email=req.email,
            api_url=req.api_url,
            api_key=req.api_key,
            model=req.model,
            query=req.query,
            history=req.history,
            search_method=req.search_method,
            workspace_dir=req.workspace_dir,
            wikidata_enrich=req.wikidata_enrich,
            defer_postprocess=req.defer_postprocess,
        )
        return ChatResponse(
            answer=result.get("answer", ""),
            intent=result.get("intent", {}),
            rewritten_query=result.get("rewritten_query", ""),
            context_data=result.get("context_data", {}),
            reasoning_subgraph=result.get("reasoning_subgraph", []),
            reasoning_subgraph_cot=result.get("reasoning_subgraph_cot", ""),
            source_chunks=result.get("source_chunks", []),
            highlight_hints=result.get("highlight_hints", []),
            judge_score=float(result.get("judge_score", 0.0)),
            judge_rationale=result.get("judge_rationale", ""),
            postprocess_pending=bool(result.get("postprocess_pending", False)),
            graphrag_raw_answer=result.get("graphrag_raw_answer", ""),
        )
    except Exception as exc:
        log.exception("[Router] /graphrag-kb/chat error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/chat-postprocess", response_model=ChatPostprocessResponse, summary="Postprocess chat metadata (prune/judge/wikidata)")
async def chat_postprocess_endpoint(req: ChatPostprocessRequest) -> ChatPostprocessResponse:
    """Run prune+judge and Wikidata appendix after main answer has been shown."""
    from workflow_engine.toolkits.graphrag_ms_tool.judge import judge_confidence
    from workflow_engine.toolkits.graphrag_ms_tool.prune_judge_combined import (
        prune_and_judge_combined_llm,
    )
    from workflow_engine.toolkits.wikidata_subgraph_enrich import (
        format_wikidata_supplement_for_subgraph,
    )

    cfg = settings
    edges = [e for e in (req.reasoning_subgraph or []) if isinstance(e, dict)]
    if not edges:
        return ChatPostprocessResponse(done=True)

    wd_flag = req.wikidata_enrich
    wd_on = (
        bool(getattr(cfg, "GRAPHRAG_WIKIDATA_ENRICH_ENABLED", True))
        if wd_flag is None
        else bool(wd_flag)
    )

    api_base = req.api_url.rstrip("/")
    api_key = req.api_key
    question = req.query
    answer = req.answer

    async def _wikidata_task() -> str:
        if not wd_on or req.mode == "subgraph":
            return ""
        return await asyncio.to_thread(
            format_wikidata_supplement_for_subgraph,
            edges,
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

    async def _judge_task() -> tuple[List[Dict[str, Any]], str, float, str]:
        if req.mode == "wikidata":
            return edges, "", 0.0, ""
        if bool(getattr(cfg, "GRAPHRAG_SUBGRAPH_PRUNE_ENABLED", True)) and edges:
            pj = await asyncio.to_thread(
                prune_and_judge_combined_llm,
                question,
                answer,
                edges,
                api_base=api_base,
                api_key=api_key,
                max_edges_input=int(getattr(cfg, "GRAPHRAG_SUBGRAPH_PRUNE_MAX_EDGES_INPUT", 28) or 28),
                max_tokens=int(getattr(cfg, "GRAPHRAG_PRUNE_JUDGE_MAX_TOKENS", 768) or 768),
            )
            return pj.edges, pj.cot, float(pj.judge.score), str(pj.judge.rationale or "")
        j = await asyncio.to_thread(
            judge_confidence,
            question,
            answer,
            edges,
            api_base=api_base,
            api_key=api_key,
        )
        return edges, "", float(j.score), str(j.rationale or "")

    try:
        judge_pack, wd_extra = await asyncio.gather(_judge_task(), _wikidata_task())
        out_edges, out_cot, out_score, out_rationale = judge_pack
        subgraph_done = req.mode in ("all", "subgraph")
        wikidata_done = req.mode in ("all", "wikidata")
        return ChatPostprocessResponse(
            reasoning_subgraph=out_edges,
            reasoning_subgraph_cot=out_cot,
            judge_score=out_score,
            judge_rationale=out_rationale,
            wikidata_appendix=wd_extra,
            subgraph_done=subgraph_done,
            wikidata_done=wikidata_done,
            done=True,
        )
    except Exception as exc:
        log.warning("[Router] /graphrag-kb/chat-postprocess failed: %s", exc)
        return ChatPostprocessResponse(
            reasoning_subgraph=edges,
            reasoning_subgraph_cot="",
            judge_score=0.0,
            judge_rationale=f"后处理失败：{exc}",
            wikidata_appendix="",
            subgraph_done=req.mode in ("all", "subgraph"),
            wikidata_done=req.mode in ("all", "wikidata"),
            done=True,
        )


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
    passage = (req.passage_for_llm or "").strip()
    llm_context = passage if passage else block
    highlighted_sentence = ""
    if req.triples:
        highlighted_sentence = _extract_sentence_for_triples(
            llm_context, req.triples, api_key=req.api_key, api_url=req.api_url
        )
        log.debug(
            "[ChunkSnippet] chunk=%s  hl_len=%d  hl=%r",
            req.chunk_id[:8],
            len(highlighted_sentence),
            highlighted_sentence[:80] if highlighted_sentence else "",
        )
    return ChunkSnippetResponse(text=block, source_stem=stem, found=True, highlighted_sentence=highlighted_sentence)


@router.post("/context-refine", response_model=ContextRefineResponse, summary="Clean first unit + supporting snippets from subgraph")
async def context_refine_endpoint(req: ContextRefineRequest) -> ContextRefineResponse:
    """Side panel: raw first text_unit + reasoning_subgraph → cleaned body + verbatim supporting quotes."""
    cleaned, snips = _refine_context_unit_with_llm(
        req.unit_text,
        req.subgraph,
        api_key=req.api_key,
        api_url=req.api_url,
        model=req.model,
    )
    return ContextRefineResponse(cleaned_text=cleaned, supporting_snippets=snips)


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
            wikidata_enrich=req.wikidata_enrich,
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
