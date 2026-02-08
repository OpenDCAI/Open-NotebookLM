"""
Paper2PPT 满血 API：分步 page-content / generate / outline-refine / 版本历史。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from fastapi_app.schemas import ErrorResponse, FullPipelineRequest, OutlineRefineRequest, PageContentRequest, PPTGenerationRequest
from fastapi_app.services.paper2ppt_service import Paper2PPTService
from dataflow_agent.utils.version_manager import ImageVersionManager
from fastapi_app.utils import _to_outputs_url

router = APIRouter(tags=["paper2ppt"])


def get_service() -> Paper2PPTService:
    return Paper2PPTService()


@router.post(
    "/paper2ppt/page-content",
    response_model=Dict[str, Any],
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def paper2ppt_pagecontent(
    request: Request,
    chat_api_url: str = Form(...),
    api_key: str = Form(...),
    email: Optional[str] = Form(None),
    input_type: str = Form(...),
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    model: str = Form("deepseek-v3.2"),
    language: str = Form("zh"),
    style: str = Form(""),
    reference_img: Optional[UploadFile] = File(None),
    gen_fig_model: str = Form(...),
    page_count: int = Form(5),
    use_long_paper: str = Form("false"),
    pdf_as_slides: str = Form("false"),
    render_dpi: Optional[int] = Form(None),
    service: Paper2PPTService = Depends(get_service),
):
    """只跑 paper2page_content，返回 pagecontent + result_path。"""
    req = PageContentRequest(
        chat_api_url=chat_api_url,
        api_key=api_key,
        email=email,
        input_type=input_type,
        text=text,
        model=model,
        language=language,
        style=style,
        gen_fig_model=gen_fig_model,
        page_count=page_count,
        use_long_paper=use_long_paper,
        pdf_as_slides=pdf_as_slides,
        render_dpi=render_dpi,
    )
    return await service.get_page_content(req=req, file=file, reference_img=reference_img, request=request)


@router.post(
    "/paper2ppt/generate",
    response_model=Dict[str, Any],
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def paper2ppt_generate(
    request: Request,
    img_gen_model_name: str = Form(...),
    chat_api_url: str = Form(...),
    api_key: str = Form(...),
    email: Optional[str] = Form(None),
    style: str = Form(""),
    reference_img: Optional[UploadFile] = File(None),
    aspect_ratio: str = Form("16:9"),
    language: str = Form("zh"),
    model: str = Form("deepseek-v3.2"),
    image_resolution: Optional[str] = Form(None),
    get_down: str = Form("false"),
    all_edited_down: str = Form("false"),
    result_path: str = Form(...),
    pagecontent: Optional[str] = Form(None),
    page_id: Optional[int] = Form(None),
    edit_prompt: Optional[str] = Form(None),
    service: Paper2PPTService = Depends(get_service),
):
    """只跑 paper2ppt：get_down=false 生成模式，get_down=true 编辑单页。"""
    req = PPTGenerationRequest(
        img_gen_model_name=img_gen_model_name,
        chat_api_url=chat_api_url,
        api_key=api_key,
        email=email,
        style=style,
        aspect_ratio=aspect_ratio,
        language=language,
        model=model,
        get_down=get_down,
        all_edited_down=all_edited_down,
        result_path=result_path,
        pagecontent=pagecontent,
        page_id=page_id,
        edit_prompt=edit_prompt,
        image_resolution=image_resolution,
    )
    return await service.generate_ppt(req=req, reference_img=reference_img, request=request)


@router.post(
    "/paper2ppt/outline-refine",
    response_model=Dict[str, Any],
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def paper2ppt_outline_refine(
    request: Request,
    outline_feedback: str = Form(...),
    pagecontent: str = Form(...),
    chat_api_url: str = Form(...),
    api_key: str = Form(...),
    email: Optional[str] = Form(None),
    model: str = Form("deepseek-v3.2"),
    language: str = Form("zh"),
    result_path: Optional[str] = Form(None),
    service: Paper2PPTService = Depends(get_service),
):
    """根据反馈修订 outline，不重新解析输入。"""
    req = OutlineRefineRequest(
        chat_api_url=chat_api_url,
        api_key=api_key,
        email=email,
        model=model,
        language=language,
        result_path=result_path,
        outline_feedback=outline_feedback,
        pagecontent=pagecontent,
    )
    return await service.refine_outline(req=req, request=request)


@router.post(
    "/paper2ppt/full",
    response_model=Dict[str, Any],
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def paper2ppt_full(
    request: Request,
    img_gen_model_name: str = Form(...),
    chat_api_url: str = Form(...),
    api_key: str = Form(...),
    email: Optional[str] = Form(None),
    input_type: str = Form(...),
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    language: str = Form("zh"),
    aspect_ratio: str = Form("16:9"),
    style: str = Form(""),
    model: str = Form("deepseek-v3.2"),
    use_long_paper: str = Form("false"),
    service: Paper2PPTService = Depends(get_service),
):
    """一次性跑完 pagecontent + paper2ppt（满血 one-shot）。"""
    req = FullPipelineRequest(
        img_gen_model_name=img_gen_model_name,
        chat_api_url=chat_api_url,
        api_key=api_key,
        email=email,
        input_type=input_type,
        text=text,
        language=language,
        aspect_ratio=aspect_ratio,
        style=style,
        model=model,
        use_long_paper=use_long_paper,
    )
    return await service.run_full_pipeline(req=req, file=file, request=request)


@router.get(
    "/paper2ppt/version-history/{encoded_path}/{page_id}",
    response_model=Dict[str, Any],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def get_version_history(
    encoded_path: str,
    page_id: int,
    request: Request,
):
    """获取指定页面的版本历史。"""
    try:
        decoded_path = base64.b64decode(encoded_path).decode("utf-8")
        img_dir = Path(decoded_path) / "ppt_pages"
        if not img_dir.exists():
            raise HTTPException(status_code=404, detail="图片目录不存在")
        history = ImageVersionManager.get_version_history(img_dir, page_id)
        for item in history:
            item["imageUrl"] = _to_outputs_url(item["image_path"], request)
        return {"success": True, "versions": history}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/paper2ppt/revert-version",
    response_model=Dict[str, Any],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def revert_to_version(
    request: Request,
    result_path: str = Form(...),
    page_id: int = Form(...),
    target_version: int = Form(...),
):
    """将页面恢复到指定版本。"""
    try:
        img_dir = Path(result_path) / "ppt_pages"
        if not img_dir.exists():
            raise HTTPException(status_code=404, detail="图片目录不存在")
        reverted_path = ImageVersionManager.revert_to_version(img_dir, page_id, target_version)
        if not reverted_path:
            raise HTTPException(status_code=404, detail="指定版本不存在")
        image_url = _to_outputs_url(reverted_path, request)
        return {"success": True, "currentImageUrl": image_url, "revertedToVersion": target_version}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
