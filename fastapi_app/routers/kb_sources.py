from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

from fastapi_app.config.settings import settings
from fastapi_app.services.source_service import SourceService

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])
source_service = SourceService()
log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg"}
VIDEO_EXTS = {".mp4", ".avi", ".mov"}


async def _ocr_image_on_the_fly(file_path: Path) -> Optional[str]:
    """Call VLM API to OCR an image that was uploaded before OCR support was added."""
    try:
        from workflow_engine.toolkits.multimodaltool.req_understanding import (
            call_image_understanding_async,
        )
        api_url = settings.LLM_API_URL
        api_key = settings.LLM_API_KEY
        model = settings.KB_VLM_MODEL or settings.LLM_MODEL
        text = await call_image_understanding_async(
            model=model,
            messages=[{"role": "user", "content": (
                "请识别并完整输出这张图片中的所有文字内容。保留原始格式（包括换行、缩进、表格结构）。"
                "如果图片中没有文字，请详细描述图片内容。只输出结果，不要加任何解释。"
            )}],
            api_url=api_url,
            api_key=api_key,
            image_path=str(file_path),
        )
        return text
    except Exception as exc:
        log.warning("On-the-fly OCR failed for %s: %s", file_path.name, exc)
        return None


async def _transcribe_on_the_fly(file_path: Path) -> Optional[str]:
    """Call LLM audio API to transcribe a media file uploaded before STT support was added."""
    try:
        from workflow_engine.toolkits.ragtool.vector_store_tool import (
            _transcribe_media_audio,
        )
        api_url = settings.LLM_API_URL
        api_key = settings.LLM_API_KEY
        model = settings.KB_VLM_MODEL or settings.LLM_MODEL
        text = await _transcribe_media_audio(file_path, api_url, api_key, model)
        return text if text else None
    except Exception as exc:
        log.warning("On-the-fly transcription failed for %s: %s", file_path.name, exc)
        return None


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
    result = source_service.get_source_display_content(path)
    if result.get("content"):
        return result

    abs_path = source_service._resolve_local_path(path.strip())
    suffix = (abs_path.suffix or "").lower()

    if suffix in IMAGE_EXTS and abs_path.exists():
        text = await _ocr_image_on_the_fly(abs_path)
        if text and text.strip():
            return {"content": f"## OCR 识别文本\n\n{text.strip()}", "from_mineru": False}
        return {"content": f"[{abs_path.name}] 图片已上传（未识别到文字内容）", "from_mineru": False}

    if suffix in (AUDIO_EXTS | VIDEO_EXTS) and abs_path.exists():
        text = await _transcribe_on_the_fly(abs_path)
        if text and text.strip():
            return {"content": f"## 语音转录文本\n\n{text.strip()}", "from_mineru": False}
        return {"content": f"[{abs_path.name}] 媒体文件已上传（未能转录音频内容）", "from_mineru": False}

    return source_service.parse_local_file(path)


@router.post("/parse-local-file")
async def parse_local_file(path_or_url: str = Body(..., embed=True)) -> Dict[str, Any]:
    return source_service.parse_local_file(path_or_url)


@router.post("/fetch-page-content")
async def fetch_page_content(url: str = Body(..., embed=True)) -> Dict[str, Any]:
    return source_service.fetch_page_content(url)
