from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

from fastapi_app.services.source_service import SourceService

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])
source_service = SourceService()


@router.get("/files")
async def list_notebook_files(
    user_id: Optional[str] = None,
    notebook_id: Optional[str] = None,
    email: Optional[str] = None,
    notebook_title: Optional[str] = None,
) -> Dict[str, Any]:
    files = source_service.list_notebook_files(
        user_id=user_id,
        notebook_id=notebook_id,
        email=email,
        notebook_title=notebook_title,
    )
    return {"success": True, "files": files}


@router.post("/get-source-display-content")
async def get_source_display_content(
    path: str = Body(..., embed=True),
    notebook_id: Optional[str] = Body(None, embed=True),
    email: Optional[str] = Body(None, embed=True),
) -> Dict[str, Any]:
    del notebook_id, email
    return source_service.get_source_display_content(path)


@router.post("/parse-local-file")
async def parse_local_file(path_or_url: str = Body(..., embed=True)) -> Dict[str, Any]:
    return source_service.parse_local_file(path_or_url)


@router.post("/fetch-page-content")
async def fetch_page_content(url: str = Body(..., embed=True)) -> Dict[str, Any]:
    return source_service.fetch_page_content(url)
