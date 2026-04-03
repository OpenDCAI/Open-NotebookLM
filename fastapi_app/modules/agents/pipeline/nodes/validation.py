"""
SQL validation node - multi-checkpoint validation system.

Checkpoints:
  2. Data limit (LIMIT/TOP/aggregation)
  3. SQL syntax (SELECT-only, brackets, dangerous keywords)
  4. English column aliases
  5. Standardized column names (warning only)
  6. Result quality (empty result, all-NULL columns)
  7. Question-SQL alignment (top-N, year filter, GROUP BY)
"""
import re
import logging
from typing import Dict, Any, Tuple, List, Optional

from fastapi_app.agents.pipeline.state import AgentState
from fastapi_app.agents.pipeline.config import PipelineConfig
from fastapi_app.agents.prompts.error_classifier import infer_failure_stage

logger = logging.getLogger(__name__)


def _validate_data_limit_checkpoint(sql: str) -> Tuple[bool, str]:
    """Checkpoint 2: Validate LIMIT clause exists (or TOP or aggregation)."""
    # Main rule: Check for LIMIT + number
    limit_pattern = r'\bLIMIT\s+\d+'
    if re.search(limit_pattern, sql, re.IGNORECASE):
        return True, ""

    # MSSQL TOP syntax
    top_pattern = r'\bTOP\s+\d+'
    if re.search(top_pattern, sql, re.IGNORECASE):
        return True, ""

    # Aggregation function exceptions (no LIMIT needed)
    agg_patterns = [
        r'^\s*SELECT\s+COUNT\s*\(',      # COUNT(*) or COUNT(col)
        r'^\s*SELECT\s+MAX\s*\(',        # MAX
        r'^\s*SELECT\s+MIN\s*\(',        # MIN
        r'^\s*SELECT\s+SUM\s*\(',        # SUM
        r'^\s*SELECT\s+AVG\s*\(',        # AVG
        r'^\s*SELECT\s+EXISTS\s*\(',     # EXISTS
    ]
    for pattern in agg_patterns:
        if re.match(pattern, sql, re.IGNORECASE):
            return True, ""

    return False, "SQL中缺少LIMIT子句。为了防止数据量过大，所有SELECT都必须包含LIMIT限制。\n请添加'LIMIT 1000'或其他合适的限制。"


def _validate_sql_syntax_checkpoint(sql: str) -> Tuple[bool, str]:
    """Checkpoint 3: Validate basic SQL syntax."""
    sql_stripped = sql.strip()

    if not re.match(r'^\s*SELECT\s+', sql_stripped, re.IGNORECASE):
        return False, "SQL必须以SELECT开头（禁止INSERT/UPDATE/DELETE）"

    open_parens = sql.count('(')
    close_parens = sql.count(')')
    if open_parens != close_parens:
        return False, f"SQL括号不匹配：{open_parens}个左括号，{close_parens}个右括号"

    single_quotes = len(re.findall(r"(?<!\\)'", sql))
    if single_quotes % 2 != 0:
        return False, "SQL单引号不匹配"

    dangerous_keywords = [r'\bDROP\b', r'\bTRUNCATE\b', r'\bDELETE\b', r'\bUPDATE\b', r'\bINSERT\b', r'\bALTER\b']
    for keyword in dangerous_keywords:
        if re.search(keyword, sql, re.IGNORECASE):
            return False, f"禁止使用{keyword.replace(chr(92), '').strip('b')}操作"

    if not re.search(r'\bFROM\b', sql, re.IGNORECASE):
        return False, "SQL缺少FROM子句"

    return True, ""


def _validate_cross_source_mode(sql: str, state: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Cross-source enforcement: when cross_source_mode is enabled and multiple datasources
    are selected, SQL must use unified table names (ds{datasource_id}_*).

    This prevents the agent from silently answering a cross-source question using only
    the current single datasource.
    """
    if not state.get("cross_source_mode"):
        return True, ""

    selected = state.get("selected_datasource_ids") or []
    if not isinstance(selected, list) or len(selected) < 2:
        return True, ""

    # Expect unified table naming from UnifiedQueryEngine registration.
    if not re.search(r"\b(?:ega_v_)?ds\d+_", sql or "", re.IGNORECASE):
        return False, (
            "已进入跨数据源查询模式，但当前 SQL 未使用统一表名（ds{datasource_id}_...）。\n"
            "请按以下步骤修正：\n"
            "1) 调用 get_cross_source_schema(datasource_ids=[...]) 获取统一 Schema\n"
            "2) 使用返回的统一表名（如 ds1_orders, ds2_customers）编写 SQL，并通过 execute_cross_source_sql 执行\n"
        )

    return True, ""


def _validate_result_quality(
    sql: str, query_result_data: Dict[str, Any]
) -> Tuple[bool, str]:
    """Checkpoint 6: Validate result quality (empty result, all-NULL columns).

    Detects two common "silent failure" patterns:
    - 6a: Query returned 0 rows (likely wrong WHERE condition)
    - 6b: Key columns are entirely NULL (likely wrong JOIN)
    """
    row_count = query_result_data.get("row_count", 0)
    data = query_result_data.get("data", [])
    columns = query_result_data.get("columns", [])

    # 6a: Empty result detection
    if row_count == 0 or len(data) == 0:
        return False, (
            "SQL执行成功但返回0条数据。请检查：\n"
            "1. WHERE条件是否过于严格（日期范围、字段值拼写）\n"
            "2. 表名或字段名是否正确\n"
            "3. JOIN条件是否导致无匹配行\n"
            "请放宽条件或检查数据后重试。"
        )

    # 6b: All-NULL column detection (only check when we have enough rows)
    if len(data) >= 2 and columns:
        null_columns = []
        for col in columns:
            all_null = all(
                row.get(col) is None
                for row in data
            )
            if all_null:
                null_columns.append(col)

        if null_columns and len(null_columns) >= len(columns) * 0.5:
            return False, (
                f"查询结果中以下列全部为NULL: {null_columns}。\n"
                f"这通常说明JOIN条件有误或选择了不存在的字段。\n"
                f"请检查JOIN ON条件中的列名是否匹配，并确认目标列确实存在于正确的表中。"
            )

    return True, ""


def _validate_question_alignment(
    sql: str, question: str
) -> Tuple[bool, str]:
    """Checkpoint 7: Validate question-SQL semantic alignment.

    Detects common mismatches between user intent and generated SQL:
    - 7a: "top N / 前N名" without ORDER BY + LIMIT (blocking)
    - 7b: Year mentioned in question but absent from SQL (warning-as-error, first try)
    - 7c: "per / 每个 / 按" without GROUP BY (logged as warning, non-blocking)
    """
    sql_upper = sql.upper()

    # 7a: Top-N intent without ORDER BY
    top_n_patterns = [
        r'前\s*(\d+)\s*名',
        r'前\s*(\d+)',
        r'top\s*(\d+)',
        r'最[高大多]\s*(\d+)',
        r'最[低小少]\s*(\d+)',
    ]
    for pattern in top_n_patterns:
        m = re.search(pattern, question, re.IGNORECASE)
        if m:
            n = m.group(1)
            has_order = bool(re.search(r'\bORDER\s+BY\b', sql_upper))
            has_limit = bool(re.search(r'\bLIMIT\s+' + n, sql_upper)) or bool(
                re.search(r'\bTOP\s+' + n, sql_upper)
            )
            if not has_order:
                return False, (
                    f"用户要求查询'前{n}名/top {n}'，但SQL中缺少ORDER BY子句。\n"
                    f"请添加ORDER BY ... DESC/ASC来确保排序，并使用LIMIT {n}限制结果数量。"
                )
            if not has_limit:
                return False, (
                    f"用户要求查询'前{n}名/top {n}'，SQL有ORDER BY但缺少LIMIT {n}。\n"
                    f"请添加LIMIT {n}以只返回前{n}条结果。"
                )
            break  # Only check first match

    # 7b: Year mentioned in question but absent from SQL
    year_matches = re.findall(r'(20[12]\d)', question)
    if year_matches:
        for year in year_matches:
            if year not in sql:
                return False, (
                    f"用户问题中提到了年份'{year}'，但SQL中未包含对应的年份过滤条件。\n"
                    f"请在WHERE子句中添加相应的日期/年份过滤，例如：\n"
                    f"  WHERE YEAR(date_column) = {year}\n"
                    f"  或 WHERE date_column >= '{year}-01-01' AND date_column < '{int(year)+1}-01-01'"
                )

    # 7d: YoY intent + "per month" intent without month grouping (blocking)
    yoy_keywords = ("同比", "yoy", "year-over-year", "同期对比", "同年对比")
    month_intent_keywords = ("各月", "每月", "按月", "月度", "每个月", "逐月")
    q_lower = (question or "").lower()
    if any(k in q_lower for k in (kw.lower() for kw in yoy_keywords)) and any(
        kw in (question or "") for kw in month_intent_keywords
    ):
        has_group_by = bool(re.search(r"\bGROUP\s+BY\b", sql_upper))
        has_month_grouping = bool(
            re.search(r"\bMONTH\s*\(", sql_upper)
            or re.search(r"\bDATE_TRUNC\s*\(\s*'MONTH'", sql_upper)
            or re.search(r'\bDATE_TRUNC\s*\(\s*"MONTH"', sql_upper)
            or re.search(r"\bSTRFTIME\s*\(", sql_upper)
            or re.search(r"\bEXTRACT\s*\(\s*MONTH\b", sql_upper)
        )
        if not (has_group_by and has_month_grouping):
            return False, (
                "用户问题包含“同比”且明确要求“各月/每月/按月”对比，但SQL未按月分组。\n"
                "请按月聚合并在同一结果里对比 2023 vs 2024（例如按 MONTH(order_date) 或 DATE_TRUNC('month', order_date) 分组），\n"
                "并给出同比增长（百分比或差值）。"
            )

    # 7c: Grouping intent without GROUP BY (warning only, non-blocking)
    group_keywords = [r'每个', r'按(.+?)分', r'各个', r'分别', r'\bper\b', r'\beach\b', r'\bby\b']
    for pattern in group_keywords:
        if re.search(pattern, question, re.IGNORECASE):
            if 'GROUP BY' not in sql_upper:
                logger.warning(
                    f"[Checkpoint 7c WARNING] Question contains grouping keyword "
                    f"'{pattern}' but SQL has no GROUP BY clause"
                )
            break

    return True, ""



ALLOWED_SEMANTIC_ALIASES = {
    "total_sales", "sales_amount", "sales_total", "revenue", "total_revenue",
    "order_count", "cnt", "total_count", "record_count", "num", "number",
    "total_quantity", "total_qty", "qty", "sales_qty",
    "avg_amount", "avg_price", "average_amount", "avg_order_amount",
    "growth_rate", "growth_rate_percent", "percentage", "ratio", "pct",
    "rank", "ranking", "row_num", "row_number",
    "year", "month", "quarter", "week", "day",
    "amount_2024_q4", "amount_2023_q4", "sales_2024", "sales_2023",
}

COLUMN_NAME_WARNINGS = {
    "customer_source": "source",
    "customer_origin": "source",
    "origin": "source",
}


def validate_sql_aliases_node(state: AgentState, config: PipelineConfig) -> dict:
    """
    Validate SQL column aliases (SQLBot multi-checkpoint integration).

    Checkpoints:
    1. Schema validation (optional, needs schema data)
    2. Data limit validation (LIMIT clause)
    3. SQL syntax validation
    4. English column aliases
    5. Standardized column names (warnings only)
    6. Result quality (empty result, all-NULL columns)
    7. Question-SQL alignment (top-N, year filter, GROUP BY)
    """
    last_sql = state.get("last_sql")
    query_result_data = state.get("query_result_data")

    # Fallback: some tool-processing paths may only persist SQL inside query_result_data["sql"].
    if not last_sql and isinstance(query_result_data, dict):
        last_sql = query_result_data.get("sql")

    if not query_result_data or not last_sql:
        # If we have an execution error (no query_result_data), still advance the
        # validation_attempts counter so the retry loop can terminate.
        if state.get("last_sql_error") and not query_result_data:
            msg = str(state.get("last_sql_error") or "")
            return {
                "validation_attempts": state.get("validation_attempts", 0) + 1,
                "failure_stage": infer_failure_stage(msg),
            }
        return {"messages": []}

    validation_attempts = state.get("validation_attempts", 0)

    # Checkpoint 2: Data limit
    has_limit, limit_error = _validate_data_limit_checkpoint(last_sql)
    if not has_limit:
        if config.verbose:
            logger.warning(f"[Checkpoint 2 FAIL] Data limit: {limit_error}")
        return {
            "last_sql_error": limit_error,
            "error_count": state.get("error_count", 0) + 1,
            "validation_attempts": validation_attempts + 1,
            "query_result_data": None,
            "failure_stage": "sql_syntax",
        }

    # Checkpoint 3: SQL syntax
    syntax_valid, syntax_error = _validate_sql_syntax_checkpoint(last_sql)
    if not syntax_valid:
        if config.verbose:
            logger.warning(f"[Checkpoint 3 FAIL] SQL syntax: {syntax_error}")
        return {
            "last_sql_error": syntax_error,
            "error_count": state.get("error_count", 0) + 1,
            "validation_attempts": validation_attempts + 1,
            "query_result_data": None,
            "failure_stage": "sql_syntax",
        }

    # Cross-source enforcement (when enabled)
    cross_ok, cross_error = _validate_cross_source_mode(last_sql, state)
    if not cross_ok:
        if config.verbose:
            logger.warning(f"[CrossSource FAIL] {cross_error}")
        return {
            "last_sql_error": cross_error,
            "error_count": state.get("error_count", 0) + 1,
            "validation_attempts": validation_attempts + 1,
            "query_result_data": None,
            "failure_stage": "discovery",
        }

    columns = query_result_data.get("columns", [])

    # Checkpoint 4: English column aliases
    non_english_columns = [col for col in columns if col and not col.isascii()]
    if non_english_columns:
        error_msg = (
            f"SQL列别名包含非英文字符: {non_english_columns}。\n"
            f"请修正SQL，确保所有列别名都是英文。例如：\n"
            f"- 错误: SELECT city AS 城市, SUM(total_amount) AS 总销售额\n"
            f"- 正确: SELECT city AS city, SUM(total_amount) AS total_amount\n"
            f"必须将所有列别名改为有意义的英文单词！"
        )
        if config.verbose:
            logger.warning(f"SQL alias validation failed: {non_english_columns}")
        return {
            "last_sql_error": error_msg,
            "error_count": state.get("error_count", 0) + 1,
            "validation_attempts": validation_attempts + 1,
            "query_result_data": None,
            "failure_stage": "spec_alias",
        }

    # Checkpoint 5: Column name warnings (non-blocking)
    warning_columns = []
    for col in columns:
        col_lower = col.lower() if isinstance(col, str) else ""
        if col_lower in ALLOWED_SEMANTIC_ALIASES:
            continue
        if col_lower in COLUMN_NAME_WARNINGS:
            warning_columns.append({"current": col, "suggested": COLUMN_NAME_WARNINGS[col_lower]})

    if warning_columns and config.verbose:
        warnings_str = ", ".join([f"{w['current']}→{w['suggested']}" for w in warning_columns])
        logger.warning(f"Column name suggestions (non-blocking): {warnings_str}")

    # Checkpoint 6: Result quality (blocking on first attempt only)
    if validation_attempts < 1:
        quality_ok, quality_error = _validate_result_quality(
            last_sql, query_result_data
        )
        if not quality_ok:
            if config.verbose:
                logger.warning(f"[Checkpoint 6 FAIL] Result quality: {quality_error}")
            return {
                "last_sql_error": quality_error,
                "error_count": state.get("error_count", 0) + 1,
                "validation_attempts": validation_attempts + 1,
                "query_result_data": None,
                "failure_stage": "instance_alignment",
            }

    # Checkpoint 7: Question-SQL alignment (blocking for clear mismatches)
    question = state.get("question", "")
    if question and validation_attempts < 2:
        align_ok, align_error = _validate_question_alignment(last_sql, question)
        if not align_ok:
            if config.verbose:
                logger.warning(f"[Checkpoint 7 FAIL] Question alignment: {align_error}")
            return {
                "last_sql_error": align_error,
                "error_count": state.get("error_count", 0) + 1,
                "validation_attempts": validation_attempts + 1,
                "query_result_data": None,
                "failure_stage": "question_mismatch",
            }

    if config.verbose:
        logger.info(f"SQL alias validation passed: {columns}")

    return {
        "messages": [],
        "failure_stage": None,
        "error_count": 0,
        "validation_attempts": 0,
    }


def should_validate_sql(state: AgentState, config: PipelineConfig) -> str:
    """
    Determine action after SQL validation.

    Returns "retry" or "continue".
    """
    if state.get("last_sql_error"):
        validation_attempts = state.get("validation_attempts", 0)

        if validation_attempts < 2:
            if config.verbose:
                logger.warning(
                    f"SQL validation failed, allowing correction (attempt {validation_attempts + 1}/2): "
                    f"{state.get('last_sql_error', '')[:100]}"
                )
            return "retry"
        else:
            if config.verbose:
                logger.warning(
                    f"SQL validation failed >2 times, accepting current result: "
                    f"{state.get('last_sql_error', '')[:100]}"
                )
            return "continue"

    return "continue"
