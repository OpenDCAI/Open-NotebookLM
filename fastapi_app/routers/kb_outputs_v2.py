from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from fastapi_app.services.output_v2_service import OutputV2Service

router = APIRouter(prefix="/kb/outputs", tags=["Knowledge Base Outputs V2"])
service = OutputV2Service()


class OutlineRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    document_id: str
    target_type: str
    title: str = ""
    prompt: str = ""
    page_count: int = 8
    guidance_item_ids: Optional[List[str]] = None
    source_paths: Optional[List[str]] = None
    source_names: Optional[List[str]] = None
    bound_document_ids: Optional[List[str]] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    enable_images: Optional[bool] = None
    flashcard_config: Optional[Dict[str, Any]] = None


class SaveOutlineRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    title: Optional[str] = None
    prompt: Optional[str] = None
    outline: List[Dict[str, Any]]
    pipeline_stage: Optional[str] = None
    enable_images: Optional[bool] = None


class SaveEditablePptIRRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    deck_ir: Dict[str, Any]


class OnlyOfficeCallbackRequest(BaseModel):
    status: Optional[int] = None
    url: Optional[str] = None
    key: Optional[str] = None
    users: Optional[List[str]] = None
    actions: Optional[List[Dict[str, Any]]] = None


class RefineOutlineRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    feedback: str
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class GenerateOutputRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    editable_ppt_options: Optional[Dict[str, Any]] = None


class RegeneratePptPageRequest(GenerateOutputRequest):
    prompt: str


class SelectPptPageVersionRequest(GenerateOutputRequest):
    pass


def _effective_user(user_id: str, email: Optional[str]) -> str:
    return (email or user_id or "local").strip() or "local"


@router.get("")
async def list_outputs(
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
) -> Dict[str, Any]:
    items = service.list_outputs(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user(user_id, email),
    )
    return {"success": True, "outputs": items}


@router.get("/{output_id}")
async def get_output(
    output_id: str,
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
) -> Dict[str, Any]:
    item = service.get_output(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user(user_id, email),
        output_id=output_id,
    )
    return {"success": True, "output": item}


@router.post("/outline")
async def create_outline(request: OutlineRequest) -> Dict[str, Any]:
    item = await service.create_outline(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        document_id=request.document_id,
        target_type=request.target_type,
        title=request.title,
        prompt=request.prompt,
        page_count=request.page_count,
        guidance_item_ids=request.guidance_item_ids,
        source_paths=request.source_paths,
        source_names=request.source_names,
        bound_document_ids=request.bound_document_ids,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
        enable_images=request.enable_images,
        flashcard_config=request.flashcard_config,
    )
    return {"success": True, "output": item}


@router.put("/{output_id}/outline")
async def save_outline(output_id: str, request: SaveOutlineRequest) -> Dict[str, Any]:
    item = service.save_outline(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
        title=request.title,
        prompt=request.prompt,
        outline=request.outline,
        pipeline_stage=request.pipeline_stage,
        enable_images=request.enable_images,
    )
    return {"success": True, "output": item}


@router.put("/{output_id}/editable-ir")
async def save_editable_ppt_ir(output_id: str, request: SaveEditablePptIRRequest) -> Dict[str, Any]:
    item = service.save_editable_ppt_ir(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
        deck_ir=request.deck_ir,
    )
    return {"success": True, "output": item}


@router.get("/{output_id}/onlyoffice/config")
async def get_onlyoffice_config(
    output_id: str,
    request: Request,
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
    browser_base_url: str = Query(""),
    editor_session_id: str = Query(""),
) -> Dict[str, Any]:
    payload = service.get_onlyoffice_config(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user(user_id, email),
        output_id=output_id,
        request_base_url=str(request.base_url).rstrip("/"),
        browser_base_url=browser_base_url,
        editor_session_id=editor_session_id,
    )
    return {"success": True, **payload}


@router.api_route("/{output_id}/onlyoffice/download/{document_key}.pptx", methods=["GET", "HEAD"])
async def download_onlyoffice_document(
    output_id: str,
    document_key: str,
    request: Request,
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
    document_base_url: str = Query(""),
    editor_session_id: str = Query(""),
) -> FileResponse:
    return service.get_onlyoffice_document_response(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user(user_id, email),
        output_id=output_id,
        document_key=document_key,
        document_base_url=document_base_url,
        editor_session_id=editor_session_id,
        method=request.method,
    )


@router.post("/{output_id}/onlyoffice/callback")
async def handle_onlyoffice_callback(
    output_id: str,
    request: OnlyOfficeCallbackRequest,
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
    document_base_url: str = Query(""),
    editor_session_id: str = Query(""),
) -> Dict[str, int]:
    return service.handle_onlyoffice_callback(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user(user_id, email),
        output_id=output_id,
        payload=request.model_dump(exclude_none=True),
        document_base_url=document_base_url,
        editor_session_id=editor_session_id,
    )


@router.post("/{output_id}/outline-refine")
async def refine_outline(output_id: str, request: RefineOutlineRequest) -> Dict[str, Any]:
    item = await service.refine_outline(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        email=(request.email or request.user_id or "local").strip() or "local",
        output_id=output_id,
        feedback=request.feedback,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
    )
    return {"success": True, "output": item}


@router.post("/{output_id}/generate")
async def generate_output(output_id: str, request: GenerateOutputRequest) -> Dict[str, Any]:
    item = await service.generate_output(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        email=(request.email or request.user_id or "local").strip() or "local",
        output_id=output_id,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
        editable_ppt_options=request.editable_ppt_options,
    )
    return {"success": True, "output": item}


@router.post("/{output_id}/pages/{page_index}/regenerate")
async def regenerate_ppt_page(
    output_id: str,
    page_index: int,
    request: RegeneratePptPageRequest,
) -> Dict[str, Any]:
    item = await service.regenerate_ppt_page(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        email=(request.email or request.user_id or "local").strip() or "local",
        output_id=output_id,
        page_index=page_index,
        prompt=request.prompt,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
    )
    return {"success": True, "output": item}


@router.post("/{output_id}/pages/{page_index}/confirm")
async def confirm_ppt_page(
    output_id: str,
    page_index: int,
    request: GenerateOutputRequest,
) -> Dict[str, Any]:
    item = service.confirm_ppt_page(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
        page_index=page_index,
    )
    return {"success": True, "output": item}


@router.post("/{output_id}/pages/{page_index}/versions/{version_id}/select")
async def select_ppt_page_version(
    output_id: str,
    page_index: int,
    version_id: str,
    request: SelectPptPageVersionRequest,
) -> Dict[str, Any]:
    item = service.select_ppt_page_version(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
        page_index=page_index,
        version_id=version_id,
    )
    return {"success": True, "output": item}


@router.post("/{output_id}/import-source")
async def import_output_to_source(output_id: str, request: GenerateOutputRequest) -> Dict[str, Any]:
    result = await service.import_output_to_source(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
    )
    return result
