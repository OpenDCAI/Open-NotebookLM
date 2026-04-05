from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from fastapi_app.utils import _from_outputs_url, _to_outputs_url
from workflow_engine.state import TableProcessingRequest, TableProcessingState
from workflow_engine.workflow import run_workflow


class TableProcessingService:
    """独立的 Table Processing 服务：不再复用 DataExtractService 的 session/message。"""

    async def process_table(
        self,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        datasources: List[Dict[str, Any]],
        instruction: str,
        output_format: str = "csv",
        title: str = "",
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = "gpt-4o",
    ) -> Dict[str, Any]:
        if not instruction or not instruction.strip():
            raise HTTPException(status_code=400, detail="instruction is required")

        # datasources 来自前端：[{name,url},...]
        csv_paths: List[str] = []
        for ds in datasources or []:
            url = (ds.get("url") or "").strip()
            if not url:
                continue
            resolved = _from_outputs_url(url)
            if resolved and isinstance(resolved, str):
                csv_paths.append(resolved)

        if not csv_paths:
            raise HTTPException(status_code=400, detail="datasources 不能为空/无可用 url")

        # workflow_engine 会在内部把结果整理成 content/sql/columns/rows/row_count
        req = TableProcessingRequest(
            datasources=csv_paths,
            instruction=instruction,
            output_format=output_format,
            title=title or "智能表格处理",
            api_key=api_key,
            chat_api_url=api_url,
            model=model or "gpt-4o",
            notebook_id=notebook_id,
        )
        state = TableProcessingState(request=req)

        result_state = await run_workflow("table_processing_api", state)

        if isinstance(result_state, dict):
            content = str(result_state.get("content") or "")
            sql = str(result_state.get("sql") or "")
            columns = result_state.get("columns") or []
            rows = result_state.get("rows") or []
            row_count = int(result_state.get("row_count") or 0)
            error = str(result_state.get("error") or "")
            result_path = str(result_state.get("result_path") or "")
        else:
            content = str(getattr(result_state, "content", "") or "")
            sql = str(getattr(result_state, "sql", "") or "")
            columns = getattr(result_state, "columns", []) or []
            rows = getattr(result_state, "rows", []) or []
            row_count = int(getattr(result_state, "row_count", 0) or 0)
            error = str(getattr(result_state, "error", "") or "")
            result_path = str(getattr(result_state, "result_path", "") or "")

        # 转换 result_path 为可下载的 URL
        processed_file_url = ""
        if result_path:
            # 查找 result_path 目录下的 CSV 文件
            result_dir = Path(result_path)
            if result_dir.exists():
                for f in result_dir.rglob("*.csv"):
                    if f.is_file():
                        processed_file_url = _to_outputs_url(str(f))
                        break

        if error:
            # error 由 workflow 层填充时，前端展示会走 content（通常为失败提示）
            return {
                "success": False,
                "content": content or "处理失败，请稍后重试。",
                "sql": sql or "",
                "columns": columns,
                "rows": rows,
                "row_count": row_count,
                "error": error,
                "processed_file_url": processed_file_url,
            }

        return {
            "success": True,
            "content": content,
            "sql": sql or "",
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "processed_file_url": processed_file_url,
        }
