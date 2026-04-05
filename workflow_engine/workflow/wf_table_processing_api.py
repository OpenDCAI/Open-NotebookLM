"""
Table Processing API - REST API endpoint for table processing functionality.

This module provides an API for processing tabular data using the table processing workflow.
It can be called from external services to process CSV files with natural language instructions.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.logger import get_logger
from workflow_engine.state import TableProcessingRequest, TableProcessingState
from workflow_engine.workflow.registry import register
from workflow_engine.utils import get_project_root
from workflow_engine.llm_callers.text import TextLLMCaller
from workflow_engine.table_agent_utils import profile_multiple_csvs, load_config

log = get_logger(__name__)


def _workspace_root() -> Path:
    """
    Open-NotebookLM-test 位于 /data/lw/notebook/Open-NotebookLM-test
    workspace root 为 /data/lw
    """
    project_root = get_project_root()
    return project_root.parents[2]


def _processing_workflow_root() -> Path:
    return _workspace_root() / "Processing_workflow"


def _default_operator_json_path() -> str:
    """
    默认 operator json：优先 Processing_workflow，其次 tableAgent。
    """
    candidates = [
        _processing_workflow_root() / "table_agent" / "utils" / "operators" / "Operators.json",
        _workspace_root() / "tableAgent" / "table_agent" / "utils" / "operators" / "Operators.json",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return str(candidates[0])


def _read_csv_sample(csv_path: str, max_rows: int = 20) -> Tuple[List[str], List[Dict[str, Any]], int]:
    """
    读取生成后的第一个 csv，并返回（列名、前 N 行记录、行数）。
    为了避免大文件一次性读全，行数使用简单计数（可能较慢但比全量 DataFrame 更稳）。
    """
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    row_count = 0

    with open(csv_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        columns = [str(c) for c in (reader.fieldnames or [])]
        for idx, row in enumerate(reader):
            if idx < max_rows:
                rows.append(row)
            row_count += 1

    return columns, rows, int(row_count)


@register("table_processing_api")
def create_table_processing_api_graph() -> GenericGraphBuilder:
    builder = GenericGraphBuilder(state_model=TableProcessingState, entry_point="_start_")

    def _start_(state: TableProcessingState) -> TableProcessingState:
        state.content = ""
        state.sql = ""
        state.columns = []
        state.rows = []
        state.row_count = 0
        state.error = ""
        return state

    def _route(_: TableProcessingState) -> str:
        return "run_table_agent"

    async def run_table_agent(state: TableProcessingState) -> TableProcessingState:
        try:
            if not state.request.datasources:
                state.error = "datasources is empty"
                return state

            raw_paths: List[str] = [str(p).strip() for p in state.request.datasources if str(p).strip()]
            if not raw_paths:
                state.error = "No valid datasource paths"
                return state

            project_root = get_project_root()
            base_out_dir = project_root / "outputs" / "table_processing"
            ts = int(time.time())
            # 使用 notebook_id 和 timestamp 生成唯一目录
            notebook_id = getattr(state.request, 'notebook_id', 'default') or 'default'
            out_dir = base_out_dir / f"{notebook_id}_{ts}"
            out_dir.mkdir(parents=True, exist_ok=True)
            state.result_path = str(out_dir)

            # 加载配置
            cfg_path = _processing_workflow_root() / "main" / "config.yaml"
            cfg = load_config(str(cfg_path)) if cfg_path.exists() else {}
            operator_json_path = (
                state.request.operator_json_path
                or (cfg.get("paths", {}) or {}).get("operator_json_path")
                or _default_operator_json_path()
            )
            try:
                if operator_json_path:
                    operator_json_path = str((cfg_path.parent / operator_json_path).resolve())
            except Exception:
                operator_json_path = str(operator_json_path or "")

            # 1) profiling
            log.info(f"[table_processing_api] profiling multiple csv: {raw_paths}")
            data_profiling = profile_multiple_csvs(raw_paths, str(out_dir))

            # 2) 设置 TableProcessingState 字段（统一后的 State）
            # 注意：task_objective 已经在 __post_init__ 中与 request.instruction 对齐
            state.task_objective = state.request.instruction  # 确保同步
            state.score_threshold = 0.0
            state.task_type = state.request.task_type or "TableCleaning-DataImputation"
            state.data_profiling = data_profiling
            state.raw_table_paths = raw_paths
            state.score_func_path = ""
            state.gt_table_path = ""
            state.profiling_trace_summary = ""
            state.summarizing_trace_summary = ""
            state.score = -1.0
            state.valid = True
            state.attempts = 0
            state.is_dag = False
            state.error_logs = []
            state.execution_time = 0.0
            state.score_rule = ""
            state.debug_attempts = 0
            state.task_name = state.request.title or "table_processing"
            state.operator_json_path = operator_json_path
            state.current_best_score_and_code = (0.0, "")

            # 3) 初始化 LLM tracker
            llm_tracker = TextLLMCaller(
                state,
                model_name=state.request.model or "deepseek-v3.2",
                temperature=0.3,
                max_tokens=10000,
            )
            state.llm_tracker = llm_tracker

            # 4) 执行 workflow（使用统一的 TableProcessingState）
            log.info("[table_processing_api] running table_processing_workflow...")
            # 延迟导入，避免循环导入问题
            from workflow_engine.workflow import run_workflow
            final_state = await run_workflow("table_processing_workflow", state)

            # 5) 提取结果
            summary = ""
            best_code = ""
            processed_files = []

            if isinstance(final_state, dict):
                summary = str(final_state.get("summary") or "")
                processed_files = final_state.get("processed_file_paths") or []
                cur_best = final_state.get("current_best_score_and_code") or (0.0, "")
                if isinstance(cur_best, (list, tuple)) and len(cur_best) >= 2:
                    best_code = str(cur_best[1] or "")
            else:
                summary = str(getattr(final_state, "summary", "") or "")
                processed_files = getattr(final_state, "processed_file_paths", []) or []
                cur_best = getattr(final_state, "current_best_score_and_code", (0.0, ""))
                if isinstance(cur_best, (list, tuple)) and len(cur_best) >= 2:
                    best_code = str(cur_best[1] or "")

            state.content = summary or (best_code[:2000] if best_code else "表格处理已完成，但未返回可展示的摘要。")
            state.sql = best_code or ""

            # 6) 读取第一个 csv 输出作为预览，并保存 result_path 供下载
            csv_path = None
            for f in processed_files:
                p = str(f)
                if p.lower().endswith(".csv") and Path(p).exists():
                    csv_path = p
                    break

            if csv_path:
                columns, rows, row_count = _read_csv_sample(csv_path, max_rows=20)
                state.columns = columns
                state.rows = rows
                state.row_count = row_count
            else:
                # 如果没有 CSV 文件，仍然保存 result_path 用于调试
                state.columns = []
                state.rows = []
                state.row_count = 0

            return state

        except Exception as e:
            log.error(f"[table_processing_api] failed: {e}")
            state.error = str(e)
            state.content = "处理失败，请稍后重试。"
            state.sql = traceback.format_exc()
            return state

    nodes = {
        "_start_": _start_,
        "run_table_agent": run_table_agent,
        "_end_": lambda s: s,
    }
    edges = [
        ("run_table_agent", "_end_"),
    ]
    builder.add_nodes(nodes).add_edges(edges).add_conditional_edge("_start_", _route)
    return builder