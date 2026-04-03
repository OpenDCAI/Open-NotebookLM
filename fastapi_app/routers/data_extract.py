from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from fastapi_app.services.data_extract_service import DataExtractService

router = APIRouter(prefix="/data-extract", tags=["Data Extract"])


class RegisterDatasourceRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    file_path: str
    display_name: Optional[str] = None


class DataExtractLLMConfigMixin(BaseModel):
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class StartSessionRequest(DataExtractLLMConfigMixin):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    datasource_id: int
    selected_datasource_ids: Optional[List[int]] = None
    title: str = ""


class SendMessageRequest(DataExtractLLMConfigMixin):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    question: str
    result_format: str = Field(default="json", pattern="^(json|csv|markdown|dict)$")
    execution_strategy: Optional[str] = None
    selected_datasource_ids: Optional[List[int]] = None
    selected_artifact_ids: Optional[List[str]] = None


class ImportArtifactRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None


def _effective_user_id(user_id: str, email: Optional[str]) -> str:
    return (email or user_id or "local").strip() or "local"


def _build_service(
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> DataExtractService:
    from fastapi_app.services.wa_data_extract import SQLBotAdapter

    adapter = SQLBotAdapter(
        llm_api_base=api_url,
        llm_api_key=api_key,
        llm_model=model,
    )
    return DataExtractService(adapter=adapter)


@router.get("/datasources")
async def list_datasources(
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
) -> Dict[str, Any]:
    service = DataExtractService()
    items = await service.list_datasources(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user_id(user_id, email),
    )
    return {"success": True, "datasources": items}


@router.post("/datasources/register")
async def register_datasource(request: RegisterDatasourceRequest) -> Dict[str, Any]:
    service = DataExtractService()
    record = await service.register_datasource(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user_id(request.user_id, request.email),
        file_path=request.file_path,
        display_name=request.display_name,
    )
    return {"success": True, "datasource": record}


@router.get("/sessions")
async def list_sessions(
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
) -> Dict[str, Any]:
    service = DataExtractService()
    items = await service.list_sessions(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user_id(user_id, email),
    )
    return {"success": True, "sessions": items}


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
) -> Dict[str, Any]:
    service = DataExtractService()
    detail = await service.get_session_detail(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user_id(user_id, email),
        session_id=session_id,
    )
    return {"success": True, **detail}


@router.post("/sessions/start")
async def start_session(request: StartSessionRequest) -> Dict[str, Any]:
    service = _build_service(request.api_url, request.api_key, request.model)
    session = await service.start_session(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user_id(request.user_id, request.email),
        datasource_id=request.datasource_id,
        selected_datasource_ids=request.selected_datasource_ids,
        title=request.title,
    )
    return {"success": True, "session": session}


@router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, request: SendMessageRequest) -> Dict[str, Any]:
    service = _build_service(request.api_url, request.api_key, request.model)
    result = await service.send_message(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user_id(request.user_id, request.email),
        session_id=session_id,
        question=request.question,
        result_format=request.result_format,
        execution_strategy=request.execution_strategy,
        selected_datasource_ids=request.selected_datasource_ids,
        selected_artifact_ids=request.selected_artifact_ids,
    )
    result["export_url"] = (
        f"/api/v1/data-extract/sessions/{session_id}/export"
        f"?notebook_id={quote(request.notebook_id)}"
        f"&notebook_title={quote(request.notebook_title)}"
        f"&user_id={quote(request.user_id)}"
        f"&email={quote(request.email or '')}"
        f"&question={quote(request.question)}"
        f"&format=csv"
    )
    return result


@router.get("/artifacts")
async def list_artifacts(
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
) -> Dict[str, Any]:
    service = DataExtractService()
    items = await service.list_artifacts(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        user_id=_effective_user_id(user_id, email),
    )
    return {"success": True, "artifacts": items}


@router.post("/artifacts/{artifact_id}/import-source")
async def import_artifact_to_source(
    artifact_id: str,
    request: ImportArtifactRequest,
) -> Dict[str, Any]:
    service = DataExtractService()
    result = await service.import_artifact_to_source(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user_id(request.user_id, request.email),
        artifact_id=artifact_id,
    )
    return result


@router.get("/sessions/{session_id}/export")
async def export_data(
    session_id: str,
    notebook_id: str = Query(...),
    notebook_title: str = Query(""),
    user_id: str = Query("local"),
    email: Optional[str] = Query(None),
    question: str = Query(...),
    format: str = Query("csv"),
) -> Response:
    service = DataExtractService()
    try:
        data = await service.export_data(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=_effective_user_id(user_id, email),
            session_id=session_id,
            question=question,
            fmt=format,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(
        content=data["content"],
        media_type=data["content_type"],
        headers={"Content-Disposition": data["content_disposition"]},
    )
