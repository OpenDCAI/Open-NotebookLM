from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from fastapi_app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["Search"])
search_service = SearchService()


class SearchRequest(BaseModel):
    query: str
    max_results: int = 10


@router.post("/")
async def search(req: SearchRequest) -> Dict[str, List[Dict[str, Any]]]:
    """搜索接口"""
    try:
        results = await search_service.search(req.query, req.max_results)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
