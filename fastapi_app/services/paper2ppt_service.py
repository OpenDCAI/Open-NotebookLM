"""
paper2ppt 业务 Service 层（满血版：分步 page-content / generate / outline-refine）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request, UploadFile

from fastapi_app.schemas import (
    FullPipelineRequest,
    OutlineRefineRequest,
    PageContentRequest,
    PPTGenerationRequest,
)
from fastapi_app.utils import _from_outputs_url, _to_outputs_url
from fastapi_app.workflow_adapters.wa_paper2ppt import (
    run_paper2page_content_refine_wf_api,
    run_paper2page_content_wf_api,
    run_paper2ppt_full_pipeline,
    run_paper2ppt_wf_api,
)
from dataflow_agent.logger import get_logger
from dataflow_agent.utils import get_project_root

log = get_logger(__name__)

PROJECT_ROOT = get_project_root()
BASE_OUTPUT_DIR = (PROJECT_ROOT / "outputs").resolve()


class Paper2PPTService:
    """paper2ppt 业务编排：page-content / generate / outline-refine / full-pipeline。"""

    async def get_page_content(
        self,
        req: PageContentRequest,
        file: UploadFile | None,
        reference_img: UploadFile | None,
        request: Request | None,
    ) -> Dict[str, Any]:
        """只跑 pagecontent（paper2page_content 工作流）。"""
        run_dir = self._create_timestamp_run_dir(req.email)
        input_dir = run_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        reference_img_path = await self._save_reference_image(input_dir, reference_img)

        pdf_as_slides = str(getattr(req, "pdf_as_slides", "false")).lower() in ("true", "1", "yes")
        wf_input_type, wf_input_content = await self._prepare_input_for_pagecontent(
            input_dir=input_dir,
            input_type=req.input_type,
            file=file,
            text=req.text,
            pdf_as_slides=pdf_as_slides,
        )

        from fastapi_app.schemas import Paper2PPTRequest

        use_long_paper_bool = str(req.use_long_paper).lower() in ("true", "1", "yes")

        p2ppt_req = Paper2PPTRequest(
            language=req.language,
            chat_api_url=req.chat_api_url,
            chat_api_key=req.api_key,
            api_key=req.api_key,
            model=req.model,
            gen_fig_model="",
            input_type=wf_input_type,
            input_content=wf_input_content,
            style=req.style,
            ref_img=str(reference_img_path) if reference_img_path else "",
            email=req.email or "",
            page_count=req.page_count,
            use_long_paper=use_long_paper_bool,
            render_dpi=getattr(req, "render_dpi", None),
        )

        resp_model = await run_paper2page_content_wf_api(p2ppt_req, result_path=run_dir)

        resp_dict = resp_model.model_dump()
        if request is not None:
            resp_dict["pagecontent"] = self._convert_pagecontent_paths_to_urls(
                resp_dict.get("pagecontent", []), request
            )
            resp_dict["all_output_files"] = self._collect_output_files_as_urls(resp_model.result_path, request)
        else:
            resp_dict["all_output_files"] = []

        return resp_dict

    async def refine_outline(
        self,
        req: OutlineRefineRequest,
        request: Request | None,
    ) -> Dict[str, Any]:
        """根据反馈修订 outline，不重新解析输入。"""
        if not req.outline_feedback.strip():
            raise HTTPException(status_code=400, detail="outline_feedback is required")

        pc = self._parse_pagecontent_json(req.pagecontent)
        if not pc:
            raise HTTPException(status_code=400, detail="pagecontent is required")

        from fastapi_app.schemas import Paper2PPTRequest

        p2ppt_req = Paper2PPTRequest(
            language=req.language,
            chat_api_url=req.chat_api_url,
            chat_api_key=req.api_key,
            api_key=req.api_key,
            model=req.model,
            gen_fig_model="",
            input_type="TEXT",
            input_content="",
            style="",
            email=req.email or "",
            page_count=len(pc),
        )

        result_root: Path | None = None
        if req.result_path:
            base_dir = Path(req.result_path)
            if not base_dir.is_absolute():
                base_dir = PROJECT_ROOT / base_dir
            result_root = base_dir.resolve()

        resp_model = await run_paper2page_content_refine_wf_api(
            p2ppt_req,
            pagecontent=pc,
            outline_feedback=req.outline_feedback,
            result_path=result_root,
        )

        resp_dict = resp_model.model_dump()
        if request is not None:
            resp_dict["pagecontent"] = self._convert_pagecontent_paths_to_urls(
                resp_dict.get("pagecontent", []), request
            )
            resp_dict["all_output_files"] = self._collect_output_files_as_urls(resp_model.result_path, request)
        else:
            resp_dict["all_output_files"] = []

        return resp_dict

    async def generate_ppt(
        self,
        req: PPTGenerationRequest,
        reference_img: UploadFile | None,
        request: Request | None,
    ) -> Dict[str, Any]:
        """只跑 PPT 生成/编辑（paper2ppt 工作流）。"""
        base_dir = Path(req.result_path)
        if not base_dir.is_absolute():
            base_dir = PROJECT_ROOT / base_dir
        base_dir = base_dir.resolve()

        if not base_dir.exists():
            raise HTTPException(status_code=400, detail=f"result_path not exists: {base_dir}")

        reference_img_path = await self._ensure_reference_image(base_dir, reference_img)

        pc: List[Dict[str, Any]] = []
        if req.pagecontent is not None:
            pc = self._parse_pagecontent_json(req.pagecontent)
            for item in pc:
                for key in ["ppt_img_path", "asset_ref", "generated_img_path"]:
                    if key in item and item[key]:
                        item[key] = _from_outputs_url(item[key])

        get_down_bool = str(req.get_down).lower() in ("true", "1", "yes")
        all_edited_down_bool = str(req.all_edited_down).lower() in ("true", "1", "yes")

        if get_down_bool:
            if req.page_id is None:
                raise HTTPException(status_code=400, detail="page_id is required when get_down=true")
            if not (req.edit_prompt or "").strip():
                raise HTTPException(status_code=400, detail="edit_prompt is required when get_down=true")
        else:
            if not pc:
                raise HTTPException(status_code=400, detail="pagecontent is required when get_down=false")

        from fastapi_app.schemas import Paper2PPTRequest

        p2ppt_req = Paper2PPTRequest(
            language=req.language,
            chat_api_url=req.chat_api_url,
            chat_api_key=req.api_key,
            api_key=req.api_key,
            model=req.model,
            gen_fig_model=req.img_gen_model_name,
            input_type="PDF",
            input_content="",
            aspect_ratio=req.aspect_ratio,
            style=req.style,
            ref_img=str(reference_img_path) if reference_img_path else "",
            email=req.email or "",
            all_edited_down=all_edited_down_bool,
            image_resolution=(req.image_resolution or "2K"),
        )

        resp_model = await run_paper2ppt_wf_api(
            p2ppt_req,
            pagecontent=pc,
            result_path=str(base_dir),
            get_down=get_down_bool,
            edit_page_num=req.page_id,
            edit_page_prompt=req.edit_prompt,
        )

        resp_dict = resp_model.model_dump()
        if request is not None:
            if resp_dict.get("ppt_pdf_path"):
                resp_dict["ppt_pdf_path"] = _to_outputs_url(resp_dict["ppt_pdf_path"], request)
            if resp_dict.get("ppt_pptx_path"):
                resp_dict["ppt_pptx_path"] = _to_outputs_url(resp_dict["ppt_pptx_path"], request)
            resp_dict["pagecontent"] = self._convert_pagecontent_paths_to_urls(
                resp_dict.get("pagecontent", []), request
            )
            resp_dict["all_output_files"] = self._collect_output_files_as_urls(resp_model.result_path, request)
        else:
            resp_dict["all_output_files"] = []

        return resp_dict

    async def run_full_pipeline(
        self,
        req: FullPipelineRequest,
        file: UploadFile | None,
        request: Request | None,
    ) -> Dict[str, Any]:
        """full pipeline：一次性跑完 pagecontent + ppt。"""
        run_dir = self._create_timestamp_run_dir(req.email)
        input_dir = run_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        wf_input_type, wf_input_content = await self._prepare_input_for_full(
            input_dir=input_dir,
            input_type=req.input_type,
            file=file,
            text=req.text,
        )

        from fastapi_app.schemas import Paper2PPTRequest

        p2ppt_req = Paper2PPTRequest(
            language=req.language,
            chat_api_url=req.chat_api_url,
            chat_api_key=req.api_key,
            api_key=req.api_key,
            model=req.model,
            gen_fig_model=req.img_gen_model_name,
            input_type=wf_input_type,
            input_content=wf_input_content,
            aspect_ratio=req.aspect_ratio,
            style=req.style,
            email=req.email or "",
            use_long_paper=str(req.use_long_paper).lower() in ("true", "1", "yes"),
        )

        resp_model = await run_paper2ppt_full_pipeline(p2ppt_req)

        resp_dict = resp_model.model_dump()
        if request is not None:
            if resp_dict.get("ppt_pdf_path"):
                resp_dict["ppt_pdf_path"] = _to_outputs_url(resp_dict["ppt_pdf_path"], request)
            if resp_dict.get("ppt_pptx_path"):
                resp_dict["ppt_pptx_path"] = _to_outputs_url(resp_dict["ppt_pptx_path"], request)
            resp_dict["pagecontent"] = self._convert_pagecontent_paths_to_urls(
                resp_dict.get("pagecontent", []), request
            )
            resp_dict["all_output_files"] = self._collect_output_files_as_urls(resp_model.result_path, request)
        else:
            resp_dict["all_output_files"] = []

        return resp_dict

    def _create_timestamp_run_dir(self, email: Optional[str]) -> Path:
        import time
        ts = int(time.time())
        code = email or "default"
        run_dir = PROJECT_ROOT / "outputs" / code / "paper2ppt" / str(ts)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _convert_pagecontent_paths_to_urls(
        self,
        pagecontent: List[Dict[str, Any]],
        request: Request,
    ) -> List[Dict[str, Any]]:
        if not pagecontent:
            return pagecontent
        keys = {
            "ppt_img_path", "generated_img_path", "img_path", "image_path",
            "path", "source_img_path", "reference_image_path", "asset_ref",
        }
        for item in pagecontent:
            if not isinstance(item, dict):
                continue
            for key in keys:
                value = item.get(key)
                if not value or not isinstance(value, str):
                    continue
                if value.startswith("http") or value.startswith("/outputs/"):
                    continue
                if os.path.isabs(value) or "/outputs/" in value or value.startswith("outputs/"):
                    item[key] = _to_outputs_url(value, request)
        return pagecontent

    async def _save_reference_image(self, input_dir: Path, reference_img: UploadFile | None) -> Optional[Path]:
        if reference_img is None:
            return None
        ref_ext = Path(reference_img.filename or "").suffix or ".png"
        p = (input_dir / f"reference{ref_ext}").resolve()
        p.write_bytes(await reference_img.read())
        return p

    async def _ensure_reference_image(self, base_dir: Path, reference_img: UploadFile | None) -> Optional[Path]:
        input_dir = base_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        if reference_img is not None:
            ref_ext = Path(reference_img.filename or "").suffix or ".png"
            p = (input_dir / f"ppt_ref_style{ref_ext}").resolve()
            p.write_bytes(await reference_img.read())
            return p
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            c = input_dir / f"reference{ext}"
            if c.exists():
                return c
        return None

    async def _prepare_input_for_pagecontent(
        self,
        input_dir: Path,
        input_type: str,
        file: UploadFile | None,
        text: Optional[str],
        pdf_as_slides: bool,
    ) -> tuple[str, str]:
        norm = input_type.lower().strip()
        if norm == "pdf":
            if file is None:
                raise HTTPException(status_code=400, detail="file is required when input_type is 'pdf'")
            p = (input_dir / "input.pdf").resolve()
            p.write_bytes(await file.read())
            return ("PPT", str(p)) if pdf_as_slides else ("PDF", str(p))
        if norm in ("ppt", "pptx"):
            if file is None:
                raise HTTPException(status_code=400, detail="file is required when input_type is 'pptx'")
            p = (input_dir / "input.pptx").resolve()
            p.write_bytes(await file.read())
            return "PPT", str(p)
        if norm == "text":
            if not text:
                raise HTTPException(status_code=400, detail="text is required when input_type is 'text'")
            (input_dir / "input.txt").resolve().write_text(text, encoding="utf-8")
            return "TEXT", text
        if norm == "topic":
            if not text:
                raise HTTPException(status_code=400, detail="text (topic) is required when input_type is 'topic'")
            (input_dir / "input_topic.txt").resolve().write_text(text, encoding="utf-8")
            return "TOPIC", text
        raise HTTPException(status_code=400, detail="invalid input_type")

    async def _prepare_input_for_full(
        self,
        input_dir: Path,
        input_type: str,
        file: UploadFile | None,
        text: Optional[str],
    ) -> tuple[str, str]:
        norm = input_type.lower().strip()
        if norm == "pdf":
            if file is None:
                raise HTTPException(status_code=400, detail="file is required when input_type is 'pdf'")
            p = (input_dir / "input.pdf").resolve()
            p.write_bytes(await file.read())
            return "PDF", str(p)
        if norm in ("ppt", "pptx"):
            if file is None:
                raise HTTPException(status_code=400, detail="file is required when input_type is 'pptx'")
            p = (input_dir / "input.pptx").resolve()
            p.write_bytes(await file.read())
            return "PPT", str(p)
        if norm == "text":
            if not text:
                raise HTTPException(status_code=400, detail="text is required when input_type is 'text'")
            (input_dir / "input.txt").resolve().write_text(text, encoding="utf-8")
            return "TEXT", text
        raise HTTPException(status_code=400, detail="invalid input_type")

    def _collect_output_files_as_urls(self, result_path: str, request: Request) -> List[str]:
        if not result_path:
            return []
        root = Path(result_path)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        if not root.exists():
            return []
        urls = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".pdf", ".pptx", ".png"}:
                urls.append(_to_outputs_url(str(p), request))
        return urls

    def _parse_pagecontent_json(self, pagecontent_json: str) -> List[Dict[str, Any]]:
        import json
        try:
            obj = json.loads(pagecontent_json)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid pagecontent json: {e}") from e
        if not isinstance(obj, list):
            raise HTTPException(status_code=400, detail="pagecontent must be a JSON list")
        for i, it in enumerate(obj):
            if not isinstance(it, dict):
                raise HTTPException(status_code=400, detail=f"pagecontent[{i}] must be an object")
        return obj
