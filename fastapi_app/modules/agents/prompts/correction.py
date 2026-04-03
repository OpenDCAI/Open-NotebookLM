"""
Correction prompt builder for SQL error recovery.
"""
from __future__ import annotations

from typing import List, Optional

from .error_classifier import classify_error, ErrorType


def build_correction_prompt(
    datasource_id: int,
    failed_sql: str,
    error_message: str,
    *,
    cross_source_mode: bool = False,
    selected_datasource_ids: Optional[List[int]] = None,
    failure_stage: Optional[str] = None,
) -> str:
    classified = classify_error(error_message)
    error_type = classified.error_type
    entity = classified.extracted_entity

    datasource_ids: List[int] = []
    if cross_source_mode and isinstance(selected_datasource_ids, list) and selected_datasource_ids:
        for x in selected_datasource_ids:
            try:
                datasource_ids.append(int(x))
            except Exception:
                continue
    if not datasource_ids:
        datasource_ids = [datasource_id]

    guidance = _ERROR_GUIDANCE.get(error_type, _GENERIC_GUIDANCE)
    if callable(guidance):
        try:
            specific_instructions = guidance(
                datasource_id,
                entity,
                cross_source_mode=cross_source_mode,
                datasource_ids=datasource_ids,
            )
        except TypeError:
            specific_instructions = guidance(datasource_id, entity)
    else:
        specific_instructions = guidance

    stage_instructions = ""
    if str(failure_stage or "") == "instance_alignment" and cross_source_mode and len(datasource_ids) > 1:
        stage_instructions = (
            "\n[Stage-aware alignment recovery]\n"
            f"- Call prepare_cross_source_ega(datasource_ids={datasource_ids}, query=\"original user question\", deep_probe=true).\n"
            "- Rebuild SQL on clean_views / filtered_schema and execute again.\n"
        )

    ds_constraint_line = (
        f"- datasource_ids={datasource_ids}"
        if cross_source_mode and len(datasource_ids) > 1
        else f"- datasource_id={datasource_id}"
    )
    exec_line = (
        f'Execute with execute_cross_source_sql(datasource_ids={datasource_ids}, sql="...")'
        if cross_source_mode and len(datasource_ids) > 1
        else f'Execute with execute_sql(datasource_id={datasource_id}, sql="...")'
    )

    extra_constraints = ""
    if cross_source_mode and len(datasource_ids) > 1:
        extra_constraints = (
            "- You are in cross-source mode; use unified table names ds{datasource_id}_... (e.g. ds1_orders, ds2_customers).\n"
            "- First call get_cross_source_schema(datasource_ids=[...]) if names/columns are uncertain.\n"
            "- If schema returns alignment_views, only use explicitly listed view names; do NOT invent {table}__norm.\n"
            "- If clean_views (ega_v_*) exist, try them first; if they fail, fallback to alignment_views or ds* tables.\n"
        )

    return f"""<CORRECTION>
SQL execution failed. Fix it with targeted steps.
<ERROR_INFO>
error_type: {error_type.value}
error_message: {error_message}
{f'entity: {entity}' if entity else ''}
</ERROR_INFO>

<FAILED_SQL>
{failed_sql}
</FAILED_SQL>

<FIX_STRATEGY>
{specific_instructions}{stage_instructions}
</FIX_STRATEGY>

<CONSTRAINTS>
{ds_constraint_line}
- Column aliases must be English.
- Keep SELECT-only safety.
- Include LIMIT unless pure scalar aggregation.
{extra_constraints}- {exec_line}
</CONSTRAINTS>
</CORRECTION>"""


def _table_not_found_guidance(
    datasource_id: int,
    entity: str = None,
    *,
    cross_source_mode: bool = False,
    datasource_ids: Optional[List[int]] = None,
) -> str:
    entity_hint = f"'{entity}' " if entity else ""
    if cross_source_mode and datasource_ids and len(datasource_ids) > 1:
        return (
            f"Table {entity_hint}was not found.\n"
            f"1. Call get_cross_source_schema(datasource_ids={datasource_ids}) to fetch the unified schema.\n"
            "2. Replace table names with ds{datasource_id}_* unified names.\n"
            "3. Use join_suggestions and only explicitly listed alignment/clean views."
        )
    return (
        f"Table {entity_hint}was not found.\n"
        f"1. Call get_datasource_schema(datasource_id={datasource_id}).\n"
        "2. Replace with existing table names."
    )


def _column_not_found_guidance(
    datasource_id: int,
    entity: str = None,
    *,
    cross_source_mode: bool = False,
    datasource_ids: Optional[List[int]] = None,
) -> str:
    entity_hint = f"'{entity}' " if entity else ""
    if cross_source_mode and datasource_ids and len(datasource_ids) > 1:
        return (
            f"Column {entity_hint}was not found.\n"
            f"1. Call get_cross_source_schema(datasource_ids={datasource_ids}).\n"
            "2. Fix column/table alias references.\n"
            "3. Prefer join_suggestions when selecting join keys."
        )
    return (
        f"Column {entity_hint}was not found.\n"
        f"1. Call get_datasource_schema(datasource_id={datasource_id}).\n"
        "2. Use exact existing column names."
    )


def _group_by_guidance(datasource_id: int, entity: str = None) -> str:
    _ = (datasource_id, entity)
    return (
        "GROUP BY mismatch.\n"
        "1. Put all non-aggregated SELECT columns in GROUP BY.\n"
        "2. Or aggregate them explicitly."
    )


def _type_mismatch_guidance(datasource_id: int, entity: str = None) -> str:
    _ = (datasource_id, entity)
    return (
        "Type mismatch.\n"
        "1. Align comparison literal types.\n"
        "2. Add CAST/try_cast where needed."
    )


def _ambiguous_column_guidance(datasource_id: int, entity: str = None) -> str:
    _ = datasource_id
    entity_hint = f"'{entity}' " if entity else ""
    return (
        f"Ambiguous column {entity_hint}reference.\n"
        "1. Qualify all columns with table aliases.\n"
        "2. Ensure join aliases are consistent."
    )


def _syntax_guidance(datasource_id: int, entity: str = None) -> str:
    _ = (datasource_id, entity)
    return (
        "Syntax error.\n"
        "1. Fix SQL keywords/commas/parentheses.\n"
        "2. Keep SQL simple and valid DuckDB syntax."
    )


def _timeout_guidance(datasource_id: int, entity: str = None) -> str:
    _ = (datasource_id, entity)
    return (
        "Query timeout.\n"
        "1. Reduce scanned rows and complexity.\n"
        "2. Add tighter filters or simpler joins."
    )


_GENERIC_GUIDANCE = (
    "Unknown error.\n"
    "1. Re-check schema and SQL.\n"
    "2. Repair the failing clause and retry."
)


_ERROR_GUIDANCE = {
    ErrorType.TABLE_NOT_FOUND: _table_not_found_guidance,
    ErrorType.COLUMN_NOT_FOUND: _column_not_found_guidance,
    ErrorType.GROUP_BY_ERROR: _group_by_guidance,
    ErrorType.TYPE_MISMATCH: _type_mismatch_guidance,
    ErrorType.AMBIGUOUS_COLUMN: _ambiguous_column_guidance,
    ErrorType.SYNTAX_ERROR: _syntax_guidance,
    ErrorType.TIMEOUT: _timeout_guidance,
    ErrorType.UNKNOWN: _GENERIC_GUIDANCE,
}
