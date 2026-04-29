from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from fastapi_app.services.output_v2_service import OutputV2Service

router = APIRouter(prefix="/kb/outputs", tags=["Knowledge Base Outputs V2"])
service = OutputV2Service()


class OutlineRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    document_id: str = ""
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
    manual_edit_log: Optional[List[Dict[str, Any]]] = None


class RefineOutlineRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    feedback: str
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class OutlineChatRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    message: str
    active_slide_index: Optional[int] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class OutlineChatApplyRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    merge_strategy: Optional[str] = None
    manual_edits_since_draft: Optional[List[Dict[str, Any]]] = None


class GenerateOutputRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class RegeneratePptPageRequest(GenerateOutputRequest):
    prompt: str


class SelectPptPageVersionRequest(GenerateOutputRequest):
    pass


class RevertStageRequest(BaseModel):
    notebook_id: str
    user_id: str = "local"


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
        manual_edit_log=request.manual_edit_log,
    )
    return {"success": True, "output": item}


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


@router.post("/{output_id}/outline-chat")
async def outline_chat(output_id: str, request: OutlineChatRequest) -> Dict[str, Any]:
    output, assistant_message, applied_scope, applied_slide_index, change_summary, intent_summary = await service.outline_chat(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        email=(request.email or request.user_id or "local").strip() or "local",
        output_id=output_id,
        message=request.message,
        active_slide_index=request.active_slide_index,
        conversation_history=request.conversation_history,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
    )
    return {
        "success": True,
        "output": output,
        "assistant_message": assistant_message,
        "applied_scope": applied_scope,
        "applied_slide_index": applied_slide_index,
        "change_summary": change_summary,
        "intent_summary": intent_summary,
    }


@router.post("/{output_id}/outline-chat/apply")
async def apply_outline_chat(output_id: str, request: OutlineChatApplyRequest) -> Dict[str, Any]:
    output, assistant_message = await service.apply_outline_chat(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
    )
    return {
        "success": True,
        "output": output,
        "assistant_message": assistant_message,
    }


@router.post("/{output_id}/outline-chat/discard")
async def discard_outline_chat(output_id: str, request: OutlineChatApplyRequest) -> Dict[str, Any]:
    output, assistant_message = service.discard_outline_chat(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user(request.user_id, request.email),
        output_id=output_id,
    )
    return {
        "success": True,
        "output": output,
        "assistant_message": assistant_message,
    }


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


@router.post("/{output_id}/revert-stage")
async def revert_output_stage(output_id: str, request: RevertStageRequest) -> Dict[str, Any]:
    result = service.revert_to_outline_stage(
        notebook_id=request.notebook_id,
        output_id=output_id,
        user_id=_effective_user(request.user_id, None),
    )
    return result
