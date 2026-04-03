"""
Error classifier for targeted SQL error correction.

Phase 3.2: Classifies SQL errors into categories and generates
targeted correction prompts instead of generic retry messages.

Categories:
- TABLE_NOT_FOUND: Table doesn't exist → suggest re-fetching schema
- COLUMN_NOT_FOUND: Column doesn't exist → check schema for correct names
- SYNTAX_ERROR: SQL syntax issues → direct syntax fix
- GROUP_BY_ERROR: GROUP BY mismatch → fix aggregation
- TYPE_MISMATCH: Data type errors → cast or adjust
- TIMEOUT: Query too slow → suggest simplification
- AMBIGUOUS_COLUMN: Column name ambiguous across tables → qualify with table alias
- EMPTY_RESULT: Query returned 0 rows or all-NULL columns → check WHERE/JOIN
- QUESTION_MISMATCH: SQL doesn't align with question intent → fix ORDER BY/filter/GROUP BY
- UNKNOWN: Unclassified → generic correction
"""
import re
from enum import Enum
from typing import Optional
from dataclasses import dataclass


class ErrorType(str, Enum):
    TABLE_NOT_FOUND = "table_not_found"
    COLUMN_NOT_FOUND = "column_not_found"
    SYNTAX_ERROR = "syntax_error"
    GROUP_BY_ERROR = "group_by_error"
    TYPE_MISMATCH = "type_mismatch"
    TIMEOUT = "timeout"
    AMBIGUOUS_COLUMN = "ambiguous_column"
    EMPTY_RESULT = "empty_result"
    QUESTION_MISMATCH = "question_mismatch"
    UNKNOWN = "unknown"


# Pattern → ErrorType mapping (order matters: first match wins)
_ERROR_PATTERNS = [
    # Table not found
    (re.compile(r"(table|relation)\s+['\"]?\w+['\"]?\s+(does not exist|not found|doesn't exist)", re.I), ErrorType.TABLE_NOT_FOUND),
    (re.compile(r"(Catalog Error|no such table|unknown table|Table .+ not found)", re.I), ErrorType.TABLE_NOT_FOUND),
    (re.compile(r"表\s*\S+\s*(不存在|未找到)", re.I), ErrorType.TABLE_NOT_FOUND),

    # Column not found
    (re.compile(r"(column|field)\s+['\"]?\w+['\"]?\s+(does not exist|not found|cannot be resolved)", re.I), ErrorType.COLUMN_NOT_FOUND),
    (re.compile(r"(Binder Error|Referenced column|unknown column|no such column)", re.I), ErrorType.COLUMN_NOT_FOUND),
    (re.compile(r"列\s*\S+\s*(不存在|未找到)", re.I), ErrorType.COLUMN_NOT_FOUND),

    # GROUP BY error
    (re.compile(r"(must appear in the GROUP BY|not in GROUP BY|aggregate|group by)", re.I), ErrorType.GROUP_BY_ERROR),
    (re.compile(r"(non-aggregated|select list.*not in.*group)", re.I), ErrorType.GROUP_BY_ERROR),

    # Type mismatch
    (re.compile(r"(type mismatch|cannot cast|conversion failed|invalid input syntax for type)", re.I), ErrorType.TYPE_MISMATCH),
    (re.compile(r"(Conversion Error|could not convert|incompatible types)", re.I), ErrorType.TYPE_MISMATCH),

    # Ambiguous column
    (re.compile(r"(ambiguous column|ambiguous reference|column reference .* is ambiguous)", re.I), ErrorType.AMBIGUOUS_COLUMN),

    # Timeout
    (re.compile(r"(timeout|timed out|exceeded.*time|query.*cancel)", re.I), ErrorType.TIMEOUT),

    # Empty / NULL-like result
    (re.compile(r"(0 rows|empty result|all-NULL|all NULL|返回0条|全为NULL)", re.I), ErrorType.EMPTY_RESULT),

    # Question/intent mismatch
    (re.compile(r"(top \d+|ORDER BY|year.*not.*included|问题.*未.*对齐|未包含.*年份|同比分组缺失)", re.I), ErrorType.QUESTION_MISMATCH),

    # Syntax error (broad - keep near end)
    (re.compile(r"(syntax error|Parser Error|parse error|unexpected token|near \")", re.I), ErrorType.SYNTAX_ERROR),
    (re.compile(r"(SQL compilation error|invalid SQL|malformed)", re.I), ErrorType.SYNTAX_ERROR),
]


@dataclass
class ClassifiedError:
    error_type: ErrorType
    original_message: str
    extracted_entity: Optional[str] = None  # e.g., the bad table/column name


def classify_error(error_message: str) -> ClassifiedError:
    """Classify a SQL error message into a specific error type."""
    for pattern, error_type in _ERROR_PATTERNS:
        if pattern.search(error_message):
            entity = _extract_entity(error_message, error_type)
            return ClassifiedError(
                error_type=error_type,
                original_message=error_message,
                extracted_entity=entity,
            )
    return ClassifiedError(
        error_type=ErrorType.UNKNOWN,
        original_message=error_message,
    )


def infer_failure_stage(error_message: str) -> str:
    """
    Infer high-level failure stage used by EGA retry router.

    Stages:
    - discovery
    - schema_alignment
    - instance_alignment
    - sql_syntax
    - question_mismatch
    - spec_alias
    - unknown
    """
    msg = str(error_message or "")
    c = classify_error(msg)

    if c.error_type == ErrorType.TABLE_NOT_FOUND:
        return "discovery"
    if c.error_type == ErrorType.COLUMN_NOT_FOUND:
        return "schema_alignment"
    if c.error_type in {ErrorType.TYPE_MISMATCH, ErrorType.AMBIGUOUS_COLUMN, ErrorType.EMPTY_RESULT}:
        return "instance_alignment"
    if c.error_type == ErrorType.SYNTAX_ERROR:
        return "sql_syntax"
    if c.error_type == ErrorType.QUESTION_MISMATCH:
        return "question_mismatch"

    # Common validation-time messages.
    low = msg.lower()
    if "limit" in low and "missing" in low:
        return "sql_syntax"
    if "empty result" in low or "0 rows" in low or "all-null" in low:
        return "instance_alignment"
    if "column aliases" in low or "alias" in low:
        return "spec_alias"
    return "unknown"


def _extract_entity(error_message: str, error_type: ErrorType) -> Optional[str]:
    """Try to extract the problematic entity name from the error."""
    if error_type == ErrorType.TABLE_NOT_FOUND:
        m = re.search(r"(?:table|relation)\s+['\"]?(\w+)['\"]?", error_message, re.I)
        if m:
            return m.group(1)
    elif error_type == ErrorType.COLUMN_NOT_FOUND:
        m = re.search(r"(?:column|field)\s+['\"]?(\w+)['\"]?", error_message, re.I)
        if m:
            return m.group(1)
    elif error_type == ErrorType.AMBIGUOUS_COLUMN:
        m = re.search(r"(?:column)\s+['\"]?(\w+)['\"]?", error_message, re.I)
        if m:
            return m.group(1)
    return None
