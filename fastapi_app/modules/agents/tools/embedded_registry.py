from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from .cross_source_tools import (
    execute_cross_source_sql,
    get_cross_source_schema,
)
from .schema_tools import get_datasource_schema, get_table_sample
from .sql_tools import execute_sql, query_data, validate_sql


def get_all_tools() -> List[BaseTool]:
    return [
        get_datasource_schema,
        execute_sql,
        validate_sql,
        get_table_sample,
        query_data,
        get_cross_source_schema,
        execute_cross_source_sql,
    ]


def get_tools() -> List[BaseTool]:
    return get_all_tools()
