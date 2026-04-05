from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fitz import log
from pydantic import BaseModel, Field

from fastapi_app.services.table_processing_service import TableProcessingService
from workflow_engine.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/table-processing", tags=["Table Processing"])

class DataSourceRef(BaseModel):
    name: str
    url: str


class TableProcessingRequest(BaseModel):
    notebook_id: str
    notebook_title: str = ""
    user_id: str = "local"
    email: Optional[str] = None
    datasources: List[DataSourceRef]
    instruction: str
    output_format: str = Field(default="csv", pattern="^(json|csv|markdown|dict)$")
    title: str = ""
    # 用户指定的 API 配置
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    model: Optional[str] = "gpt-4o"


def _effective_user_id(user_id: str, email: Optional[str]) -> str:
    return (email or user_id or "local").strip() or "local"


@router.post("/process")
async def process_table(request: TableProcessingRequest) -> Dict[str, Any]:
    svc = TableProcessingService()
    result = await svc.process_table(
        notebook_id=request.notebook_id,
        notebook_title=request.notebook_title,
        user_id=_effective_user_id(request.user_id, request.email),
        datasources=[ds.model_dump() for ds in request.datasources],
        instruction=request.instruction,
        output_format=request.output_format,
        title=request.title,
        api_key=request.api_key,
        api_url=request.api_url,
        model=request.model,
    )
    logger.info("datasources: %s", request.datasources)
    return {"success": True, **result}
