"""
Virtual clean view materialization for EGA.
"""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Dict, List, Optional

from .transform_library import build_sql_expr


def _quote_ident(s: str) -> str:
    return '"' + str(s).replace('"', '""') + '"'


def _is_date_like_column(col: str) -> bool:
    n = str(col or "").strip().lower()
    return (
        "date" in n
        or n.endswith("_dt")
        or n.endswith("_time")
        or n.endswith("time")
    )


def _is_id_like_column(col: str) -> bool:
    n = str(col or "").strip().lower()
    if not n:
        return False
    if n.endswith("_name") or n == "name":
        return False
    if n == "id" or n.endswith("_id") or n.endswith("id"):
        return True
    if n.endswith("_key") or n.endswith("key"):
        return True
    if re.search(r"(^|_)(sid|cid|uid|gid|pk|fk)(_|$)", n):
        return True
    if "cust" in n and any(k in n for k in ("id", "key", "ref", "code", "dirty")):
        return True
    if n.endswith("_code") or n.endswith("code"):
        return True
    return False


def _canonical_id_expr_sql(quoted_expr: str) -> str:
    # Canonicalize dirty textual/numeric IDs into comparable VARCHAR keys.
    return (
        "CASE "
        f"WHEN regexp_extract(CAST({quoted_expr} AS VARCHAR), '[0-9]+') <> '' "
        f"THEN CAST(CAST(regexp_extract(CAST({quoted_expr} AS VARCHAR), '[0-9]+') AS BIGINT) AS VARCHAR) "
        f"ELSE regexp_replace(lower(trim(CAST({quoted_expr} AS VARCHAR))), '[^0-9a-z]', '', 'g') "
        "END"
    )


def materialize_clean_views(
    engine,
    alignment_graph: List[Dict[str, Any]],
    relevant_tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    transforms_by_table: Dict[str, Dict[str, Dict[str, str]]] = defaultdict(dict)
    for edge in alignment_graph or []:
        left_table = str(edge.get("left_table") or "")
        left_col = str(edge.get("left_column") or "")
        chain = str(edge.get("best_transform") or "")
        if left_table and left_col and chain:
            transforms_by_table[left_table][left_col] = {
                "chain_name": chain,
                "alias": str(edge.get("canonical_alias") or f"{left_col}__ega_norm"),
            }

    clean_views: Dict[str, Any] = {}
    relevant_set = {str(t) for t in (relevant_tables or []) if str(t)}
    for reg in engine.get_registered_tables():
        table = reg.unified_table_name
        if relevant_set and table not in relevant_set:
            continue
        columns = list(reg.columns or [])
        view_name = f"ega_v_{table}"

        select_exprs: List[str] = []
        for c in columns:
            quoted = _quote_ident(c)
            if _is_date_like_column(c):
                # Convert common dirty date formats into timestamp so EXTRACT/YEAR works.
                parsed = (
                    f"COALESCE("
                    f"TRY_STRPTIME(CAST({quoted} AS VARCHAR), '%Y-%m-%d'), "
                    f"TRY_STRPTIME(CAST({quoted} AS VARCHAR), '%Y/%m/%d'), "
                    f"TRY_STRPTIME(CAST({quoted} AS VARCHAR), '%Y-%m-%d %H:%M:%S')"
                    f")"
                )
                select_exprs.append(f"{parsed} AS {quoted}")
            else:
                select_exprs.append(f"{quoted}")

        norm_map: Dict[str, str] = {}
        existing_aliases: set[str] = set()
        table_rules = transforms_by_table.get(table) or {}
        for col, rule in table_rules.items():
            chain_name = rule.get("chain_name")
            alias = rule.get("alias")
            chain_steps = []
            if chain_name:
                chain_steps = chain_name.split("_then_")
                if chain_name == "extract_digits_remove_zeros_cast":
                    chain_steps = ["extract_digits", "remove_leading_zeros", "cast_int"]
                elif chain_name == "strip_prefix_extract_digits_cast":
                    chain_steps = ["strip_prefix", "extract_digits", "cast_int"]

            expr = build_sql_expr(chain_steps, _quote_ident(col)) if chain_steps else _quote_ident(col)
            if alias:
                if str(alias).endswith("__ega_norm"):
                    # Keep normalized keys as VARCHAR to avoid implicit cast errors in JOIN.
                    expr = f"CAST({expr} AS VARCHAR)"
                select_exprs.append(f"{expr} AS {_quote_ident(alias)}")
                norm_map[col] = alias
                existing_aliases.add(str(alias))

        # Ensure all id-like columns have stable normalized aliases, even if TCS
        # did not explicitly assign a transform rule for that table/column.
        for c in columns:
            if not _is_id_like_column(c):
                continue
            alias = f"{c}__ega_norm"
            if alias in existing_aliases:
                continue
            quoted = _quote_ident(c)
            select_exprs.append(f"{_canonical_id_expr_sql(quoted)} AS {_quote_ident(alias)}")
            norm_map.setdefault(c, alias)
            existing_aliases.add(alias)

        sql = (
            f"CREATE OR REPLACE VIEW {_quote_ident(view_name)} AS "
            f"SELECT {', '.join(select_exprs)} FROM {_quote_ident(table)}"
        )
        engine.conn.execute(sql)

        clean_views[table] = {
            "view": view_name,
            "normalized_columns": norm_map,
            "columns": columns,
        }
        for src_col, dst_col in norm_map.items():
            engine.cache_ega_column_mapping(table, src_col, {"view": view_name, "target_column": dst_col})

    return clean_views
