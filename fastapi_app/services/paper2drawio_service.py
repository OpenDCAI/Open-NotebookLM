"""
Paper2Drawio Service：AI 驱动 DrawIO 图表生成。
与 dataflow_agent.workflow.wf_paper2drawio 配合使用。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Request, UploadFile

from dataflow_agent.state import Paper2DrawioState, Paper2DrawioRequest
from dataflow_agent.toolkits.drawio_tools import wrap_xml, extract_cells
from dataflow_agent.logger import get_logger
from dataflow_agent.utils import get_project_root

log = get_logger(__name__)

try:
    from fastapi_app.config import settings
except ImportError:
    settings = None

task_semaphore = asyncio.Semaphore(2)


def _get_setting(name: str, default: Any) -> Any:
    if settings is None:
        return default
    return getattr(settings, name, default)


class Paper2DrawioService:
    """Paper2Drawio 业务服务"""

    def _create_run_dir(self, prefix: str, email: Optional[str]) -> Path:
        ts = int(time.time())
        root = get_project_root()
        run_dir = root / "outputs" / prefix / str(ts)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "input").mkdir(exist_ok=True)
        return run_dir

    async def generate_diagram(
        self,
        chat_api_url: str,
        api_key: str,
        model: str,
        enable_vlm_validation: bool,
        vlm_model: Optional[str],
        vlm_validation_max_retries: Optional[int],
        input_type: str,
        diagram_type: str,
        diagram_style: str,
        language: str,
        email: Optional[str],
        file: Optional[UploadFile],
        text_content: Optional[str],
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        run_dir = self._create_run_dir("paper2drawio", email)
        input_dir = run_dir / "input"

        paper_file = ""
        if input_type == "PDF" and file:
            pdf_path = input_dir / (file.filename or "input.pdf")
            content = await file.read()
            pdf_path.write_bytes(content)
            paper_file = str(pdf_path)

        state = Paper2DrawioState(
            request=Paper2DrawioRequest(
                language=language,
                chat_api_url=chat_api_url,
                api_key=api_key,
                model=model or _get_setting("PAPER2DRAWIO_DEFAULT_MODEL", "deepseek-v3.2"),
                enable_vlm_validation=bool(enable_vlm_validation),
                vlm_model=(vlm_model or _get_setting("PAPER2DRAWIO_VLM_MODEL", "deepseek-v3.2")),
                vlm_validation_max_retries=vlm_validation_max_retries or 3,
                input_type=input_type,
                diagram_type=diagram_type,
                diagram_style=diagram_style,
            ),
            paper_file=paper_file,
            text_content=text_content or "",
            result_path=str(run_dir),
        )

        from dataflow_agent.workflow.registry import RuntimeRegistry

        try:
            async with task_semaphore:
                factory = RuntimeRegistry.get("paper2drawio")
                builder = factory()
                graph = builder.build()
                final_state = await graph.ainvoke(state)

            raw_xml = final_state.get("drawio_xml", "") if isinstance(final_state, dict) else (getattr(final_state, "drawio_xml", "") or "")
            output_path = final_state.get("output_xml_path", "") if isinstance(final_state, dict) else (getattr(final_state, "output_xml_path", "") or "")

            xml_content = wrap_xml(raw_xml) if raw_xml else ""

            return {
                "success": bool(xml_content),
                "xml_content": xml_content,
                "file_path": output_path,
                "error": None if xml_content else "Failed to generate diagram",
            }
        except Exception as e:
            log.exception("paper2drawio generate_diagram failed: %s", e)
            return {
                "success": False,
                "xml_content": "",
                "file_path": "",
                "error": str(e),
            }

    async def chat_edit(
        self,
        current_xml: str,
        message: str,
        chat_history: List[Dict[str, str]],
        chat_api_url: str,
        api_key: str,
        model: str,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        current_cells = (
            extract_cells(current_xml)
            if ("<mxfile" in current_xml or "<diagram" in current_xml)
            else current_xml
        )
        state = Paper2DrawioState(
            request=Paper2DrawioRequest(
                chat_api_url=chat_api_url,
                api_key=api_key,
                model=model,
                input_type="TEXT",
                edit_instruction=message,
                chat_history=chat_history,
            ),
            drawio_xml=current_cells,
            text_content=message,
        )

        from dataflow_agent.workflow.registry import RuntimeRegistry

        try:
            async with task_semaphore:
                factory = RuntimeRegistry.get("paper2drawio")
                builder = factory()
                graph = builder.build()
                final_state = await graph.ainvoke(state)

            raw_xml = final_state.get("drawio_xml", "") if isinstance(final_state, dict) else (getattr(final_state, "drawio_xml", "") or "")
            xml_content = wrap_xml(raw_xml) if raw_xml else ""
            return {
                "success": bool(xml_content),
                "xml_content": xml_content,
                "message": "Diagram updated" if xml_content else "",
                "error": None if xml_content else "Failed to update diagram",
            }
        except Exception as e:
            log.exception("paper2drawio chat_edit failed: %s", e)
            return {
                "success": False,
                "xml_content": current_xml,
                "message": "",
                "error": str(e),
            }

    async def export_diagram(
        self,
        xml_content: str = "",
        format: str = "drawio",
        filename: str = "diagram",
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """导出图表为 .drawio 或其它格式"""
        run_dir = self._create_run_dir("paper2drawio_export", None)
        if format == "drawio":
            output_path = run_dir / f"{filename}.drawio"
        else:
            output_path = run_dir / f"{filename}.{format}"
        full_xml = (
            xml_content if "<mxfile" in xml_content else wrap_xml(xml_content)
        )
        output_path.write_text(full_xml, encoding="utf-8")
        return {
            "success": True,
            "file_path": str(output_path),
        }
