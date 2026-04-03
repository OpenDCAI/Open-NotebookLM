from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from .analysis_tools import analyze_columns, detect_trends, generate_summary
from .catalog_tools import list_datasources
from .cross_source_tools import (
    close_unified_engine,
    execute_cross_source_sql,
    get_cross_source_schema,
    prepare_cross_source_ega,
)
from .discovery_tools import discover_and_register_datasources, get_catalog_snapshot
from .schema_tools import get_datasource_schema, get_table_sample
from .sql_tools import execute_sql, query_data, validate_sql


def get_all_tools() -> List[BaseTool]:
    return [
        list_datasources,
        discover_and_register_datasources,
        get_catalog_snapshot,
        get_datasource_schema,
        execute_sql,
        validate_sql,
        get_table_sample,
        query_data,
        analyze_columns,
        detect_trends,
        generate_summary,
        get_cross_source_schema,
        execute_cross_source_sql,
        prepare_cross_source_ega,
    ]


def get_tools() -> List[BaseTool]:
    return get_all_tools()


__all__ = [
    "get_all_tools",
    "get_tools",
    "close_unified_engine",
]
