"""GraphRAG KB 管线的工作流适配层。

【职责】
    在 FastAPI 路由（Pydantic 请求体）与 ``wf_graphrag_kb``（``GraphRAGKBState`` 数据类）之间做转换，
    统一调用 ``run_workflow("graphrag_kb", state)``，再从 ``agent_results`` / ``temp_data.errors`` 取结果。

【数据流】
    ``run_index`` / ``run_query`` / ``run_merge`` → 组装 ``GraphRAGKBRequest.action`` →
    ``GraphRAGKBState`` → LangGraph 执行 → 成功则返回对应 ``agent_results`` 字典；失败则 ``RuntimeError``（携带首条错误信息）。

【约定】
    与 ``wa_paper2ppt.py`` 类似：``_workflow_outcome`` 兼容 LangGraph 返回 dataclass 或 dict。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from workflow_engine.logger import get_logger
from workflow_engine.workflow import run_workflow
from workflow_engine.workflow.wf_graphrag_kb import GraphRAGKBRequest, GraphRAGKBState
from workflow_engine.workflow.wf_graphrag_chat import GraphRAGChatRequest, GraphRAGChatState

log = get_logger(__name__)


def _workflow_outcome(state: Any) -> Tuple[Dict[str, Any], Optional[list]]:
    """统一解析工作流终态：得到 ``(agent_results, errors)``，兼容 dict 与 dataclass 两种返回形式。"""
    if isinstance(state, dict):
        td = state.get("temp_data")
        td = td if isinstance(td, dict) else {}
        errors = td.get("errors")
        ar = state.get("agent_results")
        ar = ar if isinstance(ar, dict) else {}
        return ar, errors
    td = getattr(state, "temp_data", None)
    td = td if isinstance(td, dict) else {}
    errors = td.get("errors")
    ar = getattr(state, "agent_results", None)
    ar = ar if isinstance(ar, dict) else {}
    return ar, errors


# ---------------------------------------------------------------------------
# Public adapter functions (called by routers)
# ---------------------------------------------------------------------------

async def run_index(
    *,
    notebook_id: str,
    notebook_title: str,
    email: str,
    api_url: str,
    api_key: str,
    model: str,
    source_stems: Optional[List[str]] = None,
    workspace_dir: str = "",
    force_reindex: bool = False,
    parse_pdfs: bool = True,
    skip_kggen: bool = True,
) -> Dict[str, Any]:
    """Run indexing workflow; returns ``agent_results["index"]`` dict on success."""
    req = GraphRAGKBRequest(
        action="index",
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        email=email,
        chat_api_url=api_url,
        api_key=api_key,
        model=model,
        source_stems=source_stems or [],
        workspace_dir=workspace_dir,
        force_reindex=force_reindex,
        parse_pdfs=parse_pdfs,
        skip_kggen=skip_kggen,
    )
    state = GraphRAGKBState(request=req)
    state = await run_workflow("graphrag_kb", state)

    agent_results, errors = _workflow_outcome(state)
    if errors:
        raise RuntimeError(f"Indexing failed: {errors[0]}")

    return agent_results.get("index", {})


async def run_query(
    *,
    notebook_id: str,
    notebook_title: str,
    email: str,
    api_url: str,
    api_key: str,
    model: str,
    question: str,
    search_method: str = "local",
    workspace_dir: str = "",
    wikidata_enrich: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run query workflow; returns ``agent_results["query"]`` dict on success."""
    req = GraphRAGKBRequest(
        action="query",
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        email=email,
        chat_api_url=api_url,
        api_key=api_key,
        model=model,
        question=question,
        search_method=search_method,
        workspace_dir=workspace_dir,
        wikidata_enrich=wikidata_enrich,
    )
    state = GraphRAGKBState(request=req)
    state = await run_workflow("graphrag_kb", state)

    agent_results, errors = _workflow_outcome(state)
    if errors:
        raise RuntimeError(f"Query failed: {errors[0]}")

    return agent_results.get("query", {})


async def run_merge(
    *,
    notebook_id: str,
    notebook_title: str,
    email: str,
    api_url: str,
    api_key: str,
    model: str,
    workspace_dir_a: str,
    workspace_dir_b: str,
    dedupe: bool = False,
) -> Dict[str, Any]:
    """Merge two GraphRAG workspaces and re-index; returns ``agent_results["merge"]``."""
    req = GraphRAGKBRequest(
        action="merge",
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        email=email,
        chat_api_url=api_url,
        api_key=api_key,
        model=model,
        workspace_dir=workspace_dir_a,
        workspace_dir_b=workspace_dir_b,
        dedupe=dedupe,
    )
    state = GraphRAGKBState(request=req)
    state = await run_workflow("graphrag_kb", state)

    agent_results, errors = _workflow_outcome(state)
    if errors:
        raise RuntimeError(f"Merge failed: {errors[0]}")

    return agent_results.get("merge", {})


async def run_chat(
    *,
    notebook_id: str,
    notebook_title: str = "",
    email: str = "",
    api_url: str,
    api_key: str,
    model: str,
    query: str,
    history: List[Dict[str, str]],
    search_method: str = "auto",
    workspace_dir: str = "",
    wikidata_enrich: Optional[bool] = None,
    defer_postprocess: bool = False,
) -> Dict[str, Any]:
    """Run GraphRAG conversational chat; returns ``agent_results["chat"]`` dict."""
    req = GraphRAGChatRequest(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        email=email,
        chat_api_url=api_url,
        api_key=api_key,
        model=model,
        query=query,
        history=history,
        search_method=search_method,
        workspace_dir=workspace_dir,
        wikidata_enrich=wikidata_enrich,
        defer_postprocess=defer_postprocess,
    )
    state = GraphRAGChatState(request=req)
    state = await run_workflow("graphrag_chat", state)

    agent_results, errors = _workflow_outcome(state)
    if errors:
        raise RuntimeError(f"GraphRAG chat failed: {errors[0]}")

    return agent_results.get("chat", {})
