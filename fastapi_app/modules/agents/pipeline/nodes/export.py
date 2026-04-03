"""
Data export node.
"""
import json
import logging
from typing import Any

from fastapi_app.agents.pipeline.state import AgentState, DataFormat
from fastapi_app.agents.pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


def export_data_node(state: AgentState, config: PipelineConfig) -> dict:
    """Format query results for export."""
    data_format = state.get("data_format") or DataFormat.JSON.value
    result = state.get("query_result_data") or {}

    if not result or not result.get("data"):
        return {"export_data": {"format": data_format, "data": "[]", "columns": [], "row_count": 0}}

    data = result.get("data") or []
    columns = result.get("columns") or []

    if data_format == DataFormat.DICT.value:
        return {"export_data": {"format": data_format, "data": data, "columns": columns, "row_count": len(data)}}

    if data_format == DataFormat.JSON.value:
        return {
            "export_data": {
                "format": "json",
                "data": json.dumps(data, ensure_ascii=False, default=str),
                "columns": columns,
                "row_count": len(data),
            }
        }

    if data_format == DataFormat.MARKDOWN.value:
        return {"export_data": _to_markdown(data, columns)}

    if data_format == DataFormat.CSV.value:
        return {"export_data": _to_csv(data, columns)}

    return {"export_data": {"format": data_format, "row_count": len(data)}}


def _to_markdown(data: list, columns: list) -> dict:
    """Convert data to markdown table format."""
    def _clean_col(col: str) -> str:
        return col.lstrip("\ufeff") if isinstance(col, str) else str(col)

    def _escape_cell(text: str) -> str:
        return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def _to_cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    if not data:
        return {"format": "markdown", "data": "", "columns": columns, "row_count": 0}

    if columns:
        final_columns = [_clean_col(c) for c in columns]
    else:
        final_columns = [_clean_col(k) for k in list(data[0].keys())]

    header = "| " + " | ".join(_escape_cell(c) for c in final_columns) + " |"
    separator = "| " + " | ".join("---" for _ in final_columns) + " |"
    rows = []
    for row_dict in data:
        row_cells = []
        for col in final_columns:
            value = row_dict.get(col)
            if value is None and isinstance(col, str):
                value = row_dict.get("\ufeff" + col)
            row_cells.append(_escape_cell(_to_cell(value)))
        rows.append("| " + " | ".join(row_cells) + " |")

    table = "\n".join([header, separator] + rows)
    return {"format": "markdown", "data": table, "columns": final_columns, "row_count": len(data)}


def _to_csv(data: list, columns: list) -> dict:
    """Convert data to CSV format."""
    from fastapi_app.utils.csv_export import CSVExportConfig, CSVEncoding, CSVGenerator

    csv_config = CSVExportConfig(encoding=CSVEncoding.UTF8_BOM)
    generator = CSVGenerator(csv_config)
    content = generator.generate_full(data, columns)
    return {"format": "csv", "data": content, "columns": columns, "row_count": len(data)}
