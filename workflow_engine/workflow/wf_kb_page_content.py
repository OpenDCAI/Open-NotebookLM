from __future__ import annotations

import os
import time
import json
from pathlib import Path
from typing import List, Dict, Any
import re

from workflow_engine.state import Paper2FigureState
from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.workflow.registry import register
import asyncio
from workflow_engine.agentroles import create_react_agent, create_simple_agent
from workflow_engine.logger import get_logger
from workflow_engine.utils import get_project_root

from workflow_engine.toolkits.multimodaltool.mineru_tool import run_mineru_pdf_extract_http, _shrink_markdown
from workflow_engine.toolkits.multimodaltool.req_understanding import call_image_understanding_async

log = get_logger(__name__)

try:
    from workflow_engine.agentroles.cores.registry import AgentRegistry
except Exception:  # pragma: no cover - test stubs may not expose package layout
    AgentRegistry = None


def _ensure_result_path(state: Paper2FigureState) -> str:
    raw = getattr(state, "result_path", None)
    if raw:
        return raw

    root = get_project_root()
    ts = int(time.time())
    base_dir = (root / "outputs" / "kb_page_content" / str(ts)).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    state.result_path = str(base_dir)
    return state.result_path


def _abs_path(p: str) -> str:
    if not p:
        return ""
    try:
        return str(Path(p).expanduser().resolve())
    except Exception:
        return p


_POSITIONAL_ASSET_KEYS = (
    "asset_ref",
    "asset",
    "assetRef",
    "asset_type",
    "asset_refs",
    "table_img_path",
    "table_png_path",
    "source_img_path",
    "reference_image_path",
    "img_path",
    "image_path",
    "path",
    "ppt_img_path",
)


def _preserve_positional_asset_fields(
    original_pagecontent: List[Dict[str, Any]],
    refined_pagecontent: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not original_pagecontent or not refined_pagecontent:
        return refined_pagecontent

    for idx, refined_item in enumerate(refined_pagecontent):
        if idx >= len(original_pagecontent):
            break
        original_item = original_pagecontent[idx]
        if not isinstance(original_item, dict) or not isinstance(refined_item, dict):
            continue
        for key in _POSITIONAL_ASSET_KEYS:
            original_value = original_item.get(key)
            refined_value = refined_item.get(key)
            if original_value and not refined_value:
                refined_item[key] = original_value
    return refined_pagecontent


def _extract_markdown_image_paths(markdown_text: str, mineru_root: str) -> List[str]:
    if not markdown_text or not mineru_root:
        return []

    refs: List[str] = []
    refs.extend(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text))
    refs.extend(re.findall(r"""<img[^>]+src=["']([^"']+)["']""", markdown_text))

    image_paths: List[str] = []
    seen: set[str] = set()
    for rel in refs:
        rel = str(rel or "").strip()
        if not rel:
            continue
        img_path = Path(mineru_root) / rel
        if not img_path.exists():
            continue
        resolved = str(img_path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        image_paths.append(resolved)
    return image_paths


def _backfill_pagecontent_asset_refs(
    pagecontent: List[Dict[str, Any]],
    image_paths: List[str],
) -> List[Dict[str, Any]]:
    if not pagecontent or not image_paths:
        return pagecontent

    result: List[Dict[str, Any]] = []
    next_image_idx = 0
    for item in pagecontent:
        next_item = dict(item) if isinstance(item, dict) else item
        if isinstance(next_item, dict) and not next_item.get("asset_ref"):
            if next_image_idx < len(image_paths):
                next_item["asset_ref"] = image_paths[next_image_idx]
                next_image_idx += 1
        result.append(next_item)
    return result


def _normalize_pagecontent_items(pagecontent: Any) -> List[Dict[str, Any]]:
    if not pagecontent:
        return []
    if isinstance(pagecontent, list):
        return [item for item in pagecontent if isinstance(item, dict)]
    if isinstance(pagecontent, dict):
        return [pagecontent]
    return []


def _has_registered_agent(name: str) -> bool:
    if AgentRegistry is None:
        return False
    try:
        AgentRegistry.get(name)
        return True
    except KeyError:
        return False


@register("kb_page_content")
def create_kb_page_content_graph() -> GenericGraphBuilder:  # noqa: N802
    """
    KB 专用 pagecontent 生成流程：
    - 继承 paper2page_content 逻辑
    - 支持将用户选择的图片/描述作为独立 pagecontent 追加
    """
    builder = GenericGraphBuilder(state_model=Paper2FigureState, entry_point="_start_")

    @builder.pre_tool("minueru_output", "kb_outline_agent")
    def _get_mineru_markdown(state: Paper2FigureState):
        return (getattr(state, "kb_multi_source_text", "") or "").strip() or (state.minueru_output or "")

    @builder.pre_tool("retrieval_text", "kb_outline_agent")
    def _get_retrieval_text(state: Paper2FigureState):
        return getattr(state, "kb_retrieval_text", "") or ""

    @builder.pre_tool("query", "kb_outline_agent")
    def _get_query(state: Paper2FigureState):
        return getattr(state, "kb_query", "") or ""

    @builder.pre_tool("outline_feedback", "outline_refine_agent")
    def _get_outline_feedback(state: Paper2FigureState):
        return state.outline_feedback or ""

    @builder.pre_tool("minueru_output", "outline_refine_agent")
    def _get_mineru_markdown_for_refine(state: Paper2FigureState):
        return state.minueru_output or ""

    @builder.pre_tool("text_content", "outline_refine_agent")
    def _get_text_content_for_refine(state: Paper2FigureState):
        return state.text_content or ""

    @builder.pre_tool("pagecontent", "outline_refine_agent")
    def _get_pagecontent_for_refine(state: Paper2FigureState):
        return json.dumps(state.pagecontent or [], ensure_ascii=False)

    @builder.pre_tool("pagecontent_raw", "outline_refine_agent")
    def _get_pagecontent_raw_for_refine(state: Paper2FigureState):
        return state.pagecontent or []

    @builder.pre_tool("image_items_json", "image_filter_agent")
    def _get_image_items_json_for_filter(state: Paper2FigureState):
        return json.dumps(getattr(state, "image_items", []) or [], ensure_ascii=False)

    @builder.pre_tool("query", "image_filter_agent")
    def _get_query_for_filter(state: Paper2FigureState):
        return getattr(state, "kb_query", "") or ""

    @builder.pre_tool("pagecontent_json", "kb_image_insert_agent")
    def _get_pagecontent_json_for_insert(state: Paper2FigureState):
        return json.dumps(state.pagecontent or [], ensure_ascii=False)

    @builder.pre_tool("image_items_json", "kb_image_insert_agent")
    def _get_image_items_json_for_insert(state: Paper2FigureState):
        return json.dumps(getattr(state, "filtered_image_items", []) or [], ensure_ascii=False)

    def _start_(state: Paper2FigureState) -> Paper2FigureState:
        _ensure_result_path(state)
        state.minueru_output = state.minueru_output or ""
        state.text_content = state.text_content or ""
        state.pagecontent = state.pagecontent or []
        state.outline_feedback = state.outline_feedback or ""
        state.image_items = getattr(state, "image_items", []) or []
        state.filtered_image_items = getattr(state, "filtered_image_items", []) or []
        return state

    async def parse_pdf_pages(state: Paper2FigureState) -> Paper2FigureState:
        paper_pdf_path = Path(_abs_path(state.paper_file))
        if not paper_pdf_path.exists():
            log.error(f"[kb_page_content] PDF 文件不存在: {paper_pdf_path}")
            state.minueru_output = ""
            return state

        result_root = Path(_ensure_result_path(state))
        result_root.mkdir(parents=True, exist_ok=True)

        pdf_stem = paper_pdf_path.stem
        paper_dir = result_root / pdf_stem
        auto_dir = paper_dir / "auto"

        if not auto_dir.exists():
            try:
                mineru_port = int(getattr(state, "mineru_port", 8010) or 8010)
                await run_mineru_pdf_extract_http(
                    str(paper_pdf_path),
                    str(result_root),
                    port=mineru_port,
                )
            except Exception as e:
                log.error(f"[kb_page_content] run_mineru_pdf_extract_http 失败: {e}")
                state.minueru_output = ""
                return state

        auto_dir = (result_root / pdf_stem / "auto").resolve()
        markdown_path = auto_dir / f"{pdf_stem}.md"
        if not markdown_path.exists():
            log.error(f"[kb_page_content] Markdown 文件不存在: {markdown_path}")
            state.minueru_output = ""
            return state

        try:
            md = markdown_path.read_text(encoding="utf-8")
        except Exception as e:
            log.error(f"[kb_page_content] 读取 markdown 失败: {markdown_path}, err={e}")
            md = ""

        state.minueru_output = _shrink_markdown(md, max_h1=8, max_chars=30_000)
        state.mineru_root = str(auto_dir)
        log.info("[kb_page_content] parse_pdf_pages 完成，minueru_output 长度=%s 字符，将作为 LLM 大纲输入", len(state.minueru_output or ""))
        return state

    async def prepare_text_input(state: Paper2FigureState) -> Paper2FigureState:
        if not state.text_content:
            state.text_content = getattr(state.request, "target", "") or ""
        # TEXT 路径下 outline_agent 从 minueru_output 读内容，同步过去
        if (state.text_content or "").strip() and not (getattr(state, "minueru_output") or "").strip():
            state.minueru_output = state.text_content
        log.info("[kb_page_content] prepare_text_input 完成，minueru_output 长度=%s 字符，将作为 LLM 大纲输入", len(state.minueru_output or ""))
        return state

    async def ppt_to_images(state: Paper2FigureState) -> Paper2FigureState:
        ppt_path = Path(_abs_path(state.paper_file))
        if not ppt_path.exists():
            log.error(f"[kb_page_content] PPT 文件不存在: {ppt_path}")
            state.pagecontent = []
            return state

        output_dir = Path(_ensure_result_path(state)) / "ppt_images"
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = output_dir / f"{ppt_path.stem}.pdf"
        if not pdf_path.exists():
            cmd = (
                f'soffice --headless --convert-to pdf --outdir "{output_dir}" "{ppt_path}"'
            )
            ret = os.system(cmd)
            if ret != 0:
                log.error(
                    f"[kb_page_content] soffice 转 pdf 失败(ret={ret}). cmd={cmd}"
                )
                state.pagecontent = []
                return state

        if not pdf_path.exists():
            log.error(f"[kb_page_content] soffice 转出的 pdf 不存在: {pdf_path}")
            state.pagecontent = []
            return state

        try:
            from pdf2image import convert_from_path
        except Exception as e:
            log.error(f"[kb_page_content] 缺少 pdf2image 依赖: {e}")
            state.pagecontent = []
            return state

        try:
            slide_imgs = convert_from_path(str(pdf_path))
        except Exception as e:
            log.error(f"[kb_page_content] pdf2image 转换失败: {e}")
            state.pagecontent = []
            return state

        page_items: List[Dict[str, Any]] = []
        for i, img in enumerate(slide_imgs):
            img_path = output_dir / f"slide_{i:03d}.png"
            try:
                img.save(img_path, "PNG")
            except Exception as e:
                log.error(f"[kb_page_content] 保存 slide png 失败: {img_path}, err={e}")
                continue
            page_items.append({"ppt_img_path": str(img_path.resolve())})

        state.pagecontent = page_items
        return state

    async def outline_agent(state: Paper2FigureState) -> Paper2FigureState:
        inp_len = len(state.minueru_output or "") + len(getattr(state, "kb_retrieval_text", "") or "")
        log.info("[kb_page_content] 开始生成 outline：调用 LLM (kb_outline_agent)，目标页数=%s，输入内容总长=%s 字符", getattr(state.request, "page_count", 10), inp_len)
        agent = create_react_agent(
            name="kb_outline_agent",
            temperature=0.1,
            max_retries=5,
            parser_type="json",
        )
        state = await agent.execute(state=state)
        state.pagecontent = _normalize_pagecontent_items(state.pagecontent)
        n = len(state.pagecontent or [])
        first_title = state.pagecontent[0].get("title", "") if state.pagecontent else ""
        log.info("[kb_page_content] 大纲已由 LLM 生成，共 %s 页，首页标题=%s，进入后续生图流程", n, first_title)
        return state

    async def outline_refine_agent(state: Paper2FigureState) -> Paper2FigureState:
        original_pagecontent = [
            dict(item) if isinstance(item, dict) else item
            for item in (state.pagecontent or [])
        ]
        agent = create_react_agent(
            name="outline_refine_agent",
            parser_type="json",
            max_retries=5
        )
        state = await agent.execute(state=state)
        state.pagecontent = _normalize_pagecontent_items(state.pagecontent)
        state.pagecontent = _preserve_positional_asset_fields(
            original_pagecontent,
            state.pagecontent or [],
        )
        return state

    async def deep_research_agent(state: Paper2FigureState) -> Paper2FigureState:
        log.info("[kb_page_content] Entering deep_research_agent...")
        agent = create_simple_agent(
            name="deep_research_agent",
            temperature=0.7,
            parser_type="text",
        )
        state = await agent.execute(state=state)
        return state

    async def extract_md_images(state: Paper2FigureState) -> Paper2FigureState:
        mineru_root = getattr(state, "mineru_root", "") or ""
        image_paths: List[str] = []
        if mineru_root:
            try:
                md_files = list(Path(mineru_root).glob("*.md"))
                if md_files:
                    md_text = md_files[0].read_text(encoding="utf-8")
                else:
                    md_text = ""
            except Exception as e:
                log.error(f"[kb_page_content] 读取 md 失败: {e}")
                md_text = ""

            if md_text:
                image_paths = _extract_markdown_image_paths(md_text, mineru_root)

        state.kb_md_images = list(dict.fromkeys(image_paths))
        state.pagecontent = _backfill_pagecontent_asset_refs(
            state.pagecontent or [],
            state.kb_md_images,
        )
        return state

    async def caption_images(state: Paper2FigureState) -> Paper2FigureState:
        user_images = getattr(state, "kb_user_images", []) or []
        md_images = getattr(state, "kb_md_images", []) or []
        items: List[Dict[str, Any]] = []

        for p in md_images:
            items.append({"path": p, "caption": "", "source": "mineru"})

        for item in user_images:
            path = item.get("path") or item.get("url") or ""
            if not path:
                continue
            caption = item.get("description") or item.get("caption") or ""
            items.append({"path": path, "caption": caption, "source": "user"})

        # 去重（path）
        unique = {}
        for it in items:
            unique[it["path"]] = it
        items = list(unique.values())

        # 并行补全 caption
        async def _caption_one(it: Dict[str, Any]) -> Dict[str, Any]:
            if it.get("caption"):
                return it
            try:
                desc = await call_image_understanding_async(
                    model=getattr(state.request, "vlm_model", "gemini-2.5-flash"),
                    messages=[{"role": "user", "content": "Please provide a concise caption for this image for PPT slide selection."}],
                    api_url=state.request.chat_api_url,
                    api_key=state.request.chat_api_key or state.request.api_key,
                    image_path=it.get("path")
                )
                it["caption"] = desc.strip()
            except Exception as e:
                log.error(f"[kb_page_content] caption failed: {e}")
            return it

        tasks = [ _caption_one(it) for it in items ]
        if tasks:
            items = await asyncio.gather(*tasks)

        state.image_items = items
        return state

    async def filter_images_agent(state: Paper2FigureState) -> Paper2FigureState:
        query = (getattr(state, "kb_query", "") or "").strip()
        if not state.image_items:
            state.filtered_image_items = []
            return state
        if not query:
            state.filtered_image_items = list(state.image_items)
            return state
        if not _has_registered_agent("image_filter_agent"):
            log.warning("[kb_page_content] image_filter_agent 未注册，跳过图片筛选。")
            state.filtered_image_items = list(state.image_items)
            return state

        agent = create_react_agent(
            name="image_filter_agent",
            temperature=0.1,
            max_retries=3,
            parser_type="json",
        )
        state = await agent.execute(state=state)
        if not getattr(state, "filtered_image_items", None):
            state.filtered_image_items = list(state.image_items)
        return state

    async def insert_images_agent(state: Paper2FigureState) -> Paper2FigureState:
        if not getattr(state, "filtered_image_items", None):
            return state
        if not _has_registered_agent("kb_image_insert_agent"):
            log.warning("[kb_page_content] kb_image_insert_agent 未注册，跳过图片插入。")
            return state
        agent = create_react_agent(
            name="kb_image_insert_agent",
            temperature=0.2,
            max_retries=3,
            parser_type="json",
        )
        state = await agent.execute(state=state)
        return state
    def _route_input(state: Paper2FigureState) -> str:
        feedback = (state.outline_feedback or "").strip()
        if feedback and state.pagecontent:
            return "outline_refine_agent"
        t = getattr(state.request, "input_type", None) or getattr(state, "input_type", None) or ""
        t = str(t).upper().strip()
        if t == "PDF":
            return "parse_pdf_pages"
        if t == "TEXT":
            return "prepare_text_input"
        if t == "TOPIC":
            return "deep_research_agent"
        if t in ["PPT", "PPTX"]:
            return "ppt_to_images"
        log.error(f"[kb_page_content] Invalid input_type: {t}")
        return "_end_"

    nodes = {
        "_start_": _start_,
        "parse_pdf_pages": parse_pdf_pages,
        "prepare_text_input": prepare_text_input,
        "ppt_to_images": ppt_to_images,
        "deep_research_agent": deep_research_agent,
        "outline_agent": outline_agent,
        "outline_refine_agent": outline_refine_agent,
        "extract_md_images": extract_md_images,
        "caption_images": caption_images,
        "filter_images_agent": filter_images_agent,
        "insert_images_agent": insert_images_agent,
        "_end_": lambda state: state,
    }

    edges = [
        ("parse_pdf_pages", "outline_agent"),
        ("prepare_text_input", "outline_agent"),
        ("deep_research_agent", "outline_agent"),
        ("ppt_to_images", "extract_md_images"),
        ("outline_refine_agent", "extract_md_images"),
        ("outline_agent", "extract_md_images"),
        ("extract_md_images", "caption_images"),
        ("caption_images", "filter_images_agent"),
        ("filter_images_agent", "insert_images_agent"),
        ("insert_images_agent", "_end_"),
    ]

    # 节点名与 agent role 不一致时，必须用 role_mapping 让 pre_tool 注册到 agent 的 role 下，否则来源内容不会注入 prompt
    role_mapping = {
        "outline_agent": "kb_outline_agent",
        "filter_images_agent": "image_filter_agent",
        "insert_images_agent": "kb_image_insert_agent",
    }
    builder.add_nodes(nodes, role_mapping=role_mapping).add_edges(edges).add_conditional_edge("_start_", _route_input)
    return builder
