from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

from fastapi_app.services.notebook_service import NotebookService
from workflow_engine.logger import get_logger

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])
log = get_logger(__name__)
notebook_service = NotebookService()


@router.get("/notebooks")
async def list_notebooks(
    email: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    rows = notebook_service.list_notebooks(email=email, user_id=user_id)
    return {"success": True, "notebooks": rows}


@router.post("/notebooks")
async def create_notebook(
    name: str = Body(..., embed=True),
    description: Optional[str] = Body(None, embed=True),
    user_id: str = Body(..., embed=True),
    email: Optional[str] = Body(None, embed=True),
) -> Dict[str, Any]:
    try:
        notebook = notebook_service.create_notebook(
            name=name,
            description=description,
            user_id=user_id,
            email=email,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("create_notebook failed: %s", exc)
        return {"success": False, "message": str(exc)}

    return {"success": True, "notebook": notebook}
