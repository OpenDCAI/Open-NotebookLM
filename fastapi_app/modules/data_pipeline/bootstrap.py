"""
Datasource bootstrap pipeline.

Goal: make RAG modules "real" by automatically building indexes and injecting
useful per-datasource knowledge when a datasource is registered/uploaded.

This intentionally degrades gracefully:
- If vector embeddings are unavailable, we still build BM25/value indexes and
  lexical few-shot / terminology stores.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi_app.core.datasource_interface import (
    ColumnSchema,
    DataSourceInterface,
    DataSourceType,
    TableSchema,
)

logger = logging.getLogger(__name__)


NUMERIC_TYPES = {"integer", "bigint", "float", "double", "decimal"}
DATE_TYPES = {"date", "datetime", "timestamp", "time"}


def _safe_type(col: ColumnSchema) -> str:
    try:
        return (getattr(col, "data_type", None).value or "").lower()
    except Exception:
        return str(getattr(col, "data_type", "")).lower()


def _quote(ds_type: DataSourceType, identifier: str) -> str:
    try:
        return ds_type.quote_identifier(identifier)
    except Exception:
        # default SQL-identifier quoting
        return f'"{identifier}"'


def _as_table_payload(
    table: TableSchema, sample_per_column: int = 25
) -> Dict[str, Any]:
    columns: List[Dict[str, Any]] = []
    sample_values_map: Dict[str, List[Any]] = {}

    for col in (table.columns or []):
        col_type = _safe_type(col)
        samples = list((col.sample_values or [])[:sample_per_column])
        if samples:
            sample_values_map[col.name] = samples[:5]

        columns.append(
            {
                "name": col.name,
                "type": col_type,
                "comment": col.description or col.comment or "",
                "sample_values": samples,
            }
        )

    return {
        "table_name": table.name,
        "comment": table.description or table.comment or "",
        "columns": columns,
        "sample_values": sample_values_map,
        "row_count": table.row_count,
    }


def build_index_tables(
    datasource: DataSourceInterface,
    table_names: Optional[Sequence[str]] = None,
    sample_per_column: int = 25,
) -> List[Dict[str, Any]]:
    tables = datasource.get_tables() or []
    if table_names:
        wanted = {t.lower() for t in table_names}
        tables = [t for t in tables if (t.name or "").lower() in wanted]
    return [_as_table_payload(t, sample_per_column=sample_per_column) for t in tables]


def _pick_main_table(index_tables: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not index_tables:
        return None
    # Prefer the largest table if row_count exists; else first.
    def _rc(t: Dict[str, Any]) -> int:
        try:
            return int(t.get("row_count") or 0)
        except Exception:
            return 0

    return sorted(index_tables, key=_rc, reverse=True)[0]


def _find_column(
    table: Dict[str, Any],
    name_patterns: Sequence[str],
    type_allow: Optional[set[str]] = None,
) -> Optional[str]:
    cols = table.get("columns", []) or []
    for col in cols:
        name = (col.get("name") or "").lower()
        ctype = (col.get("type") or "").lower()
        if type_allow and ctype not in type_allow:
            continue
        if any(p in name for p in name_patterns):
            return col.get("name")
    return None


def infer_common_columns(index_tables: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    main = _pick_main_table(index_tables) or {}
    return {
        "table": main.get("table_name") if main else None,
        # CSV/Excel often load dates as VARCHAR; don't require DATE_TYPES here.
        "date": _find_column(
            main,
            ["date", "dt", "day", "time", "created_at", "order_date", "日期", "时间", "下单时间", "订单日期"],
            None,
        ),
        # Be permissive on types: name patterns are strong enough for bootstrap.
        "amount": _find_column(
            main,
            ["amount", "total_amount", "sales", "revenue", "gmv", "income", "金额", "销售额", "成交额", "营收", "收入"],
            None,
        ),
        "quantity": _find_column(
            main,
            ["quantity", "qty", "count", "units", "销量", "销售数量", "数量", "件数"],
            None,
        ),
        "city": _find_column(main, ["city", "城市", "province", "region", "area", "地区", "区域", "省", "市"], None),
        "product": _find_column(main, ["product", "sku", "item", "商品", "产品", "产品名称", "商品名称", "品名"], None),
        "remark": _find_column(main, ["remark", "note", "comment", "备注"], None),
        "source": _find_column(main, ["source", "channel", "来源"], None),
    }


def _bootstrap_terminology(
    datasource_id: int,
    ds_type: DataSourceType,
    roles: Dict[str, Optional[str]],
    terminology_service: Any,
) -> int:
    """
    Create datasource-specific overrides for builtin terms with placeholders
    like {date_col} / {amount_col}.
    """
    date_col = roles.get("date")
    amount_col = roles.get("amount")
    if not date_col and not amount_col:
        return 0

    created = 0
    for entry in getattr(terminology_service, "BUILTIN_TERMS", []) or []:
        sql = getattr(entry, "sql_expression", None)
        if not sql or ("{date_col}" not in sql and "{amount_col}" not in sql):
            continue

        if "{date_col}" in sql and date_col:
            sql = sql.replace("{date_col}", _quote(ds_type, date_col))
        if "{amount_col}" in sql and amount_col:
            sql = sql.replace("{amount_col}", _quote(ds_type, amount_col))

        try:
            terminology_service.add_term(
                term=entry.term,
                definition=entry.definition,
                synonyms=list(entry.synonyms or []),
                abbreviations=list(entry.abbreviations or []),
                sql_expression=sql,
                category=entry.category,
                datasource_id=datasource_id,
            )
            created += 1
        except Exception as e:
            logger.debug(f"Terminology bootstrap failed for {entry.term}: {e}")

    return created


def _bootstrap_few_shot(
    datasource_id: int,
    ds_type: DataSourceType,
    roles: Dict[str, Optional[str]],
    few_shot_service: Any,
) -> int:
    """Add a small set of datasource-specific few-shot examples derived from schema."""
    table = roles.get("table")
    if not table:
        return 0

    qt = _quote(ds_type, table)
    examples: List[Tuple[str, str, str]] = []

    city = roles.get("city")
    amount = roles.get("amount")
    date = roles.get("date")
    product = roles.get("product")
    quantity = roles.get("quantity")

    if city and amount:
        q_city = _quote(ds_type, city)
        q_amt = _quote(ds_type, amount)
        examples.append(
            (
                "统计各城市的销售额，按销售额从高到低排序，取前10名",
                f"""SELECT
  {q_city} AS city,
  SUM({q_amt}) AS total_amount
FROM {qt}
GROUP BY {q_city}
ORDER BY total_amount DESC
LIMIT 10""",
                "城市聚合 + SUM + ORDER BY DESC + LIMIT，列别名使用英文。",
            )
        )

    if product and quantity:
        q_prod = _quote(ds_type, product)
        q_qty = _quote(ds_type, quantity)
        examples.append(
            (
                "找出销量最高的产品，返回产品名称和总销量，取前10名",
                f"""SELECT
  {q_prod} AS product_name,
  SUM({q_qty}) AS total_quantity
FROM {qt}
GROUP BY {q_prod}
ORDER BY total_quantity DESC
LIMIT 10""",
                "产品聚合 + SUM(数量) + 排序，列别名使用英文。",
            )
        )

    if date and amount:
        q_date = _quote(ds_type, date)
        q_amt = _quote(ds_type, amount)
        examples.append(
            (
                "按月份统计销售额趋势",
                f"""SELECT
  DATE_TRUNC('month', {q_date}) AS month,
  SUM({q_amt}) AS total_amount
FROM {qt}
GROUP BY DATE_TRUNC('month', {q_date})
ORDER BY month ASC
LIMIT 1000""",
                "时间趋势：DATE_TRUNC('month', date) 分组，ORDER BY 时间升序。",
            )
        )

    created = 0
    for q, sql, desc in examples[:4]:
        try:
            few_shot_service.add_example(
                question=q,
                sql=sql,
                description=desc,
                datasource_id=datasource_id,
                difficulty="easy",
            )
            created += 1
        except Exception as e:
            logger.debug(f"Few-shot bootstrap failed: {e}")

    return created


@dataclass
class BootstrapResult:
    datasource_id: int
    table_count: int
    terminology_terms_added: int = 0
    few_shot_examples_added: int = 0
    bm25_indexed: bool = False
    value_indexed: bool = False
    schema_embedding_indexed: bool = False
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def bootstrap_datasource(
    datasource_id: int,
    datasource: DataSourceInterface,
    *,
    sample_per_column: int = 25,
    enable_value_linking_cells: bool = False,
    terminology_service: Any = None,
    few_shot_service: Any = None,
) -> BootstrapResult:
    """
    Build all retrieval indexes for a datasource and inject minimal useful RAG data.

    This is safe to call multiple times (idempotent-ish).
    """
    from fastapi_app.modules.rag.bm25_retriever import bm25_retriever
    from fastapi_app.modules.rag.hybrid_retriever import hybrid_retriever
    from fastapi_app.modules.rag.schema_embedding import schema_embedding_service
    from fastapi_app.modules.rag.value_retriever import value_retriever
    from fastapi_app.modules.rag.value_linking import value_linking_service
    from fastapi_app.modules.rag.terminology import terminology_service as global_terms
    from fastapi_app.modules.rag.few_shot import few_shot_service as global_few_shot

    terminology_service = terminology_service or global_terms
    few_shot_service = few_shot_service or global_few_shot

    try:
        ds_type = getattr(datasource, "metadata", None).type  # type: ignore[attr-defined]
        if not isinstance(ds_type, DataSourceType):
            ds_type = DataSourceType.CSV
    except Exception:
        ds_type = DataSourceType.CSV

    index_tables = build_index_tables(datasource, sample_per_column=sample_per_column)
    result = BootstrapResult(datasource_id=datasource_id, table_count=len(index_tables))

    if not index_tables:
        result.errors.append("no_tables")
        return result

    roles = infer_common_columns(index_tables)

    # 1) Build BM25 + (optional) schema embeddings via hybrid retriever
    try:
        hybrid_retriever.index_tables(datasource_id, index_tables)
        result.bm25_indexed = True
        # schema embedding index_tables is called inside hybrid retriever; check best-effort
        result.schema_embedding_indexed = schema_embedding_service.is_indexed(datasource_id)
    except Exception as e:
        result.errors.append(f"hybrid_index_failed:{e}")

    # 2) Build value index (value_retriever)
    try:
        value_retriever.index_tables(datasource_id, index_tables)
        result.value_indexed = True
    except Exception as e:
        result.errors.append(f"value_index_failed:{e}")

    # 3) Optional: build local cell index for schema tool value hints
    if enable_value_linking_cells:
        try:
            value_linking_service.index_cells_from_datasource(
                datasource_id=datasource_id,
                datasource=datasource,
                sample_per_column=min(20, sample_per_column),
            )
        except Exception as e:
            result.errors.append(f"value_linking_cells_failed:{e}")

    # 4) Inject datasource-specific terminology overrides
    try:
        result.terminology_terms_added = _bootstrap_terminology(
            datasource_id=datasource_id,
            ds_type=ds_type,
            roles=roles,
            terminology_service=terminology_service,
        )
    except Exception as e:
        result.errors.append(f"terminology_bootstrap_failed:{e}")

    # 5) Inject datasource-specific few-shot examples
    try:
        result.few_shot_examples_added = _bootstrap_few_shot(
            datasource_id=datasource_id,
            ds_type=ds_type,
            roles=roles,
            few_shot_service=few_shot_service,
        )
    except Exception as e:
        result.errors.append(f"few_shot_bootstrap_failed:{e}")

    logger.info(
        "Bootstrap datasource done: id=%s tables=%s bm25=%s value=%s term+%s fewshot+%s errors=%s",
        datasource_id,
        result.table_count,
        result.bm25_indexed,
        result.value_indexed,
        result.terminology_terms_added,
        result.few_shot_examples_added,
        len(result.errors),
    )
    return result
