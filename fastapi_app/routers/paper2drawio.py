"""
Paper2Drawio API：AI 驱动 DrawIO 图表生成。
供 Notebook LM Studio 功能卡片调用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel

from dataflow_agent.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/paper2drawio", tags=["paper2drawio"])


class ChatRequest(BaseModel):
    """对话编辑请求"""
    current_xml: str = ""
    message: str = ""
    chat_history: List[Dict[str, str]] = []
    chat_api_url: str = ""
    api_key: str = ""
    model: str = "deepseek-v3.2"


class ExportRequest(BaseModel):
    """导出请求"""
    xml_content: str = ""
    format: str = "drawio"
    filename: str = "diagram"


@router.post("/generate")
async def generate_diagram(
    request: Request,
    chat_api_url: str = Form(""),
    api_key: str = Form(""),
    model: Optional[str] = Form(None),
    enable_vlm_validation: Optional[bool] = Form(False),
    vlm_model: Optional[str] = Form(None),
    vlm_validation_max_retries: int = Form(3),
    input_type: str = Form("TEXT"),
    diagram_type: str = Form("auto"),
    diagram_style: str = Form("default"),
    language: str = Form("zh"),
    email: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
):
    """生成 DrawIO 图表。支持 Form（含 file）或仅 text_content。"""
    from fastapi_app.services.paper2drawio_service import Paper2DrawioService

    try:
        from fastapi_app.config import settings as app_settings
        default_model = getattr(app_settings, "PAPER2DRAWIO_DEFAULT_MODEL", "deepseek-v3.2")
        vlm_model_default = getattr(app_settings, "PAPER2DRAWIO_VLM_MODEL", "deepseek-v3.2")
    except Exception:
        default_model = "deepseek-v3.2"
        vlm_model_default = "deepseek-v3.2"

    service = Paper2DrawioService()
    return await service.generate_diagram(
        request=request,
        chat_api_url=chat_api_url or "",
        api_key=api_key or "",
        model=model or default_model,
        enable_vlm_validation=bool(enable_vlm_validation),
        vlm_model=vlm_model or vlm_model_default,
        vlm_validation_max_retries=vlm_validation_max_retries,
        input_type=input_type,
        diagram_type=diagram_type,
        diagram_style=diagram_style,
        language=language,
        email=email,
        file=file,
        text_content=text_content or "",
    )


@router.post("/chat")
async def chat_edit_diagram(request: Request, body: ChatRequest):
    """对话式编辑图表"""
    from fastapi_app.services.paper2drawio_service import Paper2DrawioService

    service = Paper2DrawioService()
    return await service.chat_edit(
        request=request,
        current_xml=body.current_xml,
        message=body.message,
        chat_history=body.chat_history,
        chat_api_url=body.chat_api_url,
        api_key=body.api_key,
        model=body.model,
    )


@router.post("/export")
async def export_diagram(request: Request, body: ExportRequest):
    """导出图表为指定格式"""
    from fastapi_app.services.paper2drawio_service import Paper2DrawioService

    service = Paper2DrawioService()
    return await service.export_diagram(
        request=request,
        xml_content=body.xml_content,
        format=body.format,
        filename=body.filename,
    )
