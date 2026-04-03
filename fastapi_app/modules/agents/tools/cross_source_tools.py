"""Cross-source tools - unified schema and SQL execution.

Provides two LangChain tools:
- get_cross_source_schema(datasource_ids): returns unified DuckDB schema + table mapping + join suggestions
- execute_cross_source_sql(datasource_ids, sql, limit): executes SQL against the unified engine
- prepare_cross_source_ega(datasource_ids, query, mode, deep_probe): run EGA preparation and return filtered schema/clean views

Unified table naming: ds{datasource_id}_{original_table_name}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional, List

from langchain_core.tools import tool

from .datasource_manager import get_datasource_handler, get_all_datasource_ids
from fastapi_app.core.unified_engine import UnifiedQueryEngine
from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)

_unified_engine: Optional[UnifiedQueryEngine] = None


def _looks_id_like_column(col: str) -> bool:
    c = str(col or "").lower()
    if not c:
        return False
    if c.endswith("_name") or c == "name":
        return False
    return (
        c == "id"
        or c.endswith("_id")
        or c.endswith("id")
        or c.endswith("_key")
        or c.endswith("key")
        or c.endswith("_code")
        or c.endswith("code")
        or bool(re.search(r"(^|_)(sid|cid|uid|gid|pk|fk)(_|$)", c))
        or ("cust" in c and any(k in c for k in ("id", "key", "ref", "code", "dirty")))
        or "sid" in c
        or c.endswith("__norm")
    )


def _canonical_id_expr(expr: str) -> str:
    return (
        "CASE "
        f"WHEN regexp_extract(CAST({expr} AS VARCHAR), '[0-9]+') <> '' "
        f"THEN CAST(CAST(regexp_extract(CAST({expr} AS VARCHAR), '[0-9]+') AS BIGINT) AS VARCHAR) "
        f"ELSE regexp_replace(lower(trim(CAST({expr} AS VARCHAR))), '[^0-9a-z]', '', 'g') "
        "END"
    )


def _rewrite_extract_year(sql: str) -> str:
    pattern = re.compile(r"EXTRACT\s*\(\s*YEAR\s+FROM\s+([^)]+?)\s*\)", flags=re.IGNORECASE)

    def _rep(m: re.Match) -> str:
        expr = m.group(1).strip()
        parsed = (
            f"COALESCE("
            f"TRY_STRPTIME(CAST({expr} AS VARCHAR), '%Y-%m-%d'), "
            f"TRY_STRPTIME(CAST({expr} AS VARCHAR), '%Y/%m/%d'), "
            f"TRY_STRPTIME(CAST({expr} AS VARCHAR), '%Y-%m-%d %H:%M:%S')"
            f")"
        )
        return f"EXTRACT(YEAR FROM {parsed})"

    return pattern.sub(_rep, sql)


def _rewrite_join_equalities(sql: str) -> str:
    # Normalize common id-like join conditions:
    #   a.sid_dirty = b.singer_id  -> canonical(a.sid_dirty) = canonical(b.singer_id)
    eq_pattern = re.compile(
        r"(\b[\w]+\.([\w]+)\b)\s*=\s*(\b[\w]+\.([\w]+)\b)",
        flags=re.IGNORECASE,
    )

    def _rep(m: re.Match) -> str:
        left_expr, left_col = m.group(1), m.group(2)
        right_expr, right_col = m.group(3), m.group(4)
        if not (_looks_id_like_column(left_col) or _looks_id_like_column(right_col)):
            return m.group(0)
        return f"{_canonical_id_expr(left_expr)} = {_canonical_id_expr(right_expr)}"

    return eq_pattern.sub(_rep, sql)


def _rewrite_ega_suffix(sql: str) -> str:
    # Keep __ega_norm when querying clean views (ega_v_*), because those views
    # materialize EGA-normalized columns using the __ega_norm suffix.
    low = str(sql or "").lower()
    if "ega_v_" in low:
        return str(sql or "")
    return re.sub(r"__ega_norm\b", "__norm", str(sql or ""))


def _rewrite_with_clean_views(sql: str, engine: UnifiedQueryEngine) -> str:
    out = str(sql or "")
    try:
        existing_names = {
            str(row[0]).lower()
            for row in engine.conn.execute("SHOW TABLES").fetchall()
            if row and row[0]
        }
    except Exception:
        existing_names = set()

    for reg in engine.get_registered_tables():
        base = str(reg.unified_table_name)
        view = f"ega_v_{base}"
        if view.lower() not in existing_names:
            continue
        out = re.sub(rf"\b{re.escape(base)}__norm\b", view, out)
        out = re.sub(rf"\b{re.escape(base)}\b", view, out)
    return out


def _extract_alias_map(sql: str) -> tuple[dict[str, str], dict[str, str]]:
    alias_to_table: dict[str, str] = {}
    table_to_alias: dict[str, str] = {}
    token = re.compile(
        r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?",
        flags=re.IGNORECASE,
    )
    stop = {"ON", "USING", "WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "LEFT", "RIGHT", "FULL", "INNER", "OUTER"}
    for m in token.finditer(sql or ""):
        table = str(m.group(1) or "")
        alias = str(m.group(2) or "")
        if not table:
            continue
        if alias and alias.upper() not in stop:
            alias_to_table[alias] = table
            table_to_alias.setdefault(table, alias)
        else:
            alias_to_table.setdefault(table, table)
            table_to_alias.setdefault(table, table)
    return alias_to_table, table_to_alias


def _get_table_columns(engine: UnifiedQueryEngine, table_name: str, cache: dict[str, set[str]]) -> set[str]:
    key = str(table_name or "")
    if key in cache:
        return cache[key]

    cols: set[str] = set()
    for reg in engine.get_registered_tables():
        if str(reg.unified_table_name).lower() == key.lower():
            cols = {str(c).lower() for c in (reg.columns or [])}
            break
    if not cols:
        try:
            rows = engine.conn.execute(f'PRAGMA table_info("{key}")').fetchall()
            cols = {str(r[1]).lower() for r in rows if isinstance(r, (tuple, list)) and len(r) > 1}
        except Exception:
            cols = set()
    cache[key] = cols
    return cols


def _rewrite_table_qualifiers(sql: str, engine: UnifiedQueryEngine) -> str:
    out = str(sql or "")
    for reg in engine.get_registered_tables():
        base = str(reg.unified_table_name)
        norm = f"{base}__norm"
        clean = f"ega_v_{base}"
        if re.search(rf"\b{re.escape(clean)}\b", out):
            out = re.sub(rf"\b{re.escape(base)}\.", f"{clean}.", out)
        if re.search(rf"\b{re.escape(norm)}\b", out):
            out = re.sub(rf"\b{re.escape(base)}\.", f"{norm}.", out)

    _, table_to_alias = _extract_alias_map(out)
    for table, alias in table_to_alias.items():
        if alias and alias != table:
            out = re.sub(rf"\b{re.escape(table)}\.", f"{alias}.", out)
    return out


def _rewrite_misbound_column_refs(sql: str, engine: UnifiedQueryEngine) -> str:
    out = str(sql or "")
    alias_to_table, _ = _extract_alias_map(out)
    if not alias_to_table:
        return out

    col_cache: dict[str, set[str]] = {}
    refs = re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", out)
    for alias, col in refs:
        table = alias_to_table.get(alias)
        if not table:
            continue
        col_l = str(col).lower()
        current_cols = _get_table_columns(engine, table, col_cache)
        if col_l in current_cols:
            continue

        candidates: list[str] = []
        for other_alias, other_table in alias_to_table.items():
            if other_alias == alias:
                continue
            other_cols = _get_table_columns(engine, other_table, col_cache)
            if col_l in other_cols:
                candidates.append(other_alias)
        if len(candidates) == 1:
            out = re.sub(
                rf"\b{re.escape(alias)}\.{re.escape(col)}\b",
                f"{candidates[0]}.{col}",
                out,
            )
    return out


def _rewrite_to_normalized_columns(sql: str, engine: UnifiedQueryEngine) -> str:
    out = str(sql or "")
    alias_to_table, _ = _extract_alias_map(out)
    if not alias_to_table:
        return out

    col_cache: dict[str, set[str]] = {}
    refs = re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", out)
    for alias, col in refs:
        if col.endswith("__norm") or col.endswith("__ega_norm"):
            continue
        if not _looks_id_like_column(col):
            continue
        table = alias_to_table.get(alias)
        if not table:
            continue
        cols = _get_table_columns(engine, table, col_cache)
        ega_norm = f"{col}__ega_norm".lower()
        norm = f"{col}__norm".lower()
        target = None
        if ega_norm in cols:
            target = f"{col}__ega_norm"
        elif norm in cols:
            target = f"{col}__norm"
        if target:
            out = re.sub(
                rf"\b{re.escape(alias)}\.{re.escape(col)}\b",
                f"{alias}.{target}",
                out,
            )
    return out


def _rewrite_not_in_subquery(sql: str) -> str:
    pattern = re.compile(
        r"(\b[\w]+\.(\w+)\b)\s+NOT\s+IN\s*\(\s*SELECT\s+(\b[\w]+(?:\.(\w+))?\b)\s+FROM",
        flags=re.IGNORECASE,
    )

    def _rep(m: re.Match) -> str:
        left_expr = str(m.group(1) or "")
        left_col = str(m.group(2) or "")
        right_expr = str(m.group(3) or "")
        right_col = str(m.group(4) or right_expr.split(".")[-1] or "")
        if not (_looks_id_like_column(left_col) or _looks_id_like_column(right_col)):
            return m.group(0)
        left_norm = _canonical_id_expr(left_expr)
        right_norm = _canonical_id_expr(right_expr)
        return f"{left_norm} NOT IN (SELECT {right_norm} FROM"

    return pattern.sub(_rep, sql)


def _rewrite_in_subquery(sql: str) -> str:
    pattern = re.compile(
        r"(\b[\w]+\.(\w+)\b)\s+IN\s*\(\s*SELECT\s+(\b[\w]+(?:\.(\w+))?\b)\s+FROM",
        flags=re.IGNORECASE,
    )

    def _rep(m: re.Match) -> str:
        left_expr = str(m.group(1) or "")
        left_col = str(m.group(2) or "")
        right_expr = str(m.group(3) or "")
        right_col = str(m.group(4) or right_expr.split(".")[-1] or "")
        if not (_looks_id_like_column(left_col) or _looks_id_like_column(right_col)):
            return m.group(0)
        left_norm = _canonical_id_expr(left_expr)
        right_norm = _canonical_id_expr(right_expr)
        return f"{left_norm} IN (SELECT {right_norm} FROM"

    return pattern.sub(_rep, sql)


def _build_sql_rewrite_candidates(sql: str, engine: UnifiedQueryEngine) -> List[tuple[str, str]]:
    candidates: List[tuple[str, str]] = []
    raw = str(sql or "").strip()
    prefer_rewrite_first = ("ega_v_" in raw.lower()) or bool(engine.get_ega_column_mappings())
    if raw and not prefer_rewrite_first:
        candidates.append(("original", raw))

    s1 = _rewrite_ega_suffix(raw)
    s1 = _rewrite_with_clean_views(s1, engine)
    s1 = _rewrite_table_qualifiers(s1, engine)
    s1 = _rewrite_misbound_column_refs(s1, engine)
    s1 = _rewrite_to_normalized_columns(s1, engine)
    s1 = _rewrite_extract_year(s1)
    s1 = _rewrite_join_equalities(s1)
    s1 = _rewrite_not_in_subquery(s1)
    s1 = _rewrite_in_subquery(s1)
    if s1 and s1 != raw:
        candidates.append(("ega_rewrite_v1", s1))
    elif s1 and s1 == raw and raw and prefer_rewrite_first:
        candidates.append(("ega_rewrite_v1", s1))

    # Fallback: if __norm columns still fail, try dropping suffix to base column names.
    s2 = re.sub(r"\b([A-Za-z_]\w*)__norm\b", r"\1", s1)
    s2 = _rewrite_table_qualifiers(s2, engine)
    s2 = _rewrite_misbound_column_refs(s2, engine)
    s2 = _rewrite_to_normalized_columns(s2, engine)
    s2 = _rewrite_join_equalities(s2)
    s2 = _rewrite_not_in_subquery(s2)
    s2 = _rewrite_in_subquery(s2)
    if s2 and all(s2 != q for _, q in candidates):
        candidates.append(("ega_rewrite_v2_drop_norm_suffix", s2))
    if raw and prefer_rewrite_first and all(raw != q for _, q in candidates):
        candidates.append(("original", raw))
    return candidates


def _get_or_create_engine(datasource_ids: List[int], max_rows: Optional[int] = None) -> UnifiedQueryEngine:
    """Create (or reuse) a UnifiedQueryEngine with the specified datasources registered."""
    global _unified_engine

    if max_rows is None:
        max_rows = getattr(settings, "UNIFIED_ENGINE_MAX_IMPORT_ROWS", 100_000)
    if isinstance(max_rows, int) and max_rows <= 0:
        max_rows = None

    if _unified_engine is not None:
        existing_ds = _unified_engine._registered_datasources
        if all(ds_id in existing_ds for ds_id in datasource_ids):
            return _unified_engine
        _unified_engine.close()
        _unified_engine = None

    engine = UnifiedQueryEngine()
    for ds_id in datasource_ids:
        ds = get_datasource_handler(ds_id)
        if ds is None:
            logger.warning(f"Datasource {ds_id} not found; skip registration")
            continue
        engine.register_datasource(ds_id, ds, max_rows=max_rows)

    _unified_engine = engine
    return engine


def close_unified_engine() -> None:
    """Close the global unified engine (call on session end)."""
    global _unified_engine
    if _unified_engine is not None:
        _unified_engine.close()
        _unified_engine = None


def _build_clean_view_schema_text(engine: UnifiedQueryEngine) -> str:
    lines = ["=== EGA Clean View Schema ==="]
    has_any = False
    for reg in engine.get_registered_tables():
        base = str(reg.unified_table_name)
        view = f"ega_v_{base}"
        try:
            cols = engine.conn.execute(f'PRAGMA table_info("{view}")').fetchall()
        except Exception:
            continue
        if not cols:
            continue
        has_any = True
        lines.append(f"view {view}")
        for c in cols[:160]:
            lines.append(f"  - {c[1]}")
    return "\n".join(lines) if has_any else ""


@tool
def get_cross_source_schema(
    datasource_ids: List[int],
    query: Optional[str] = None,
    strategy: str = "legacy",
) -> str:
    """Get unified schema for multiple datasources (DuckDB), including join suggestions."""

    if not datasource_ids:
        return json.dumps({"error": "Please provide at least one datasource_id"}, ensure_ascii=False)

    missing = [ds_id for ds_id in datasource_ids if get_datasource_handler(ds_id) is None]
    if missing:
        return json.dumps(
            {
                "error": f"Missing datasources: {missing}",
                "available_datasource_ids": get_all_datasource_ids(),
            },
            ensure_ascii=False,
        )

    try:
        max_rows = getattr(settings, "UNIFIED_ENGINE_MAX_IMPORT_ROWS", 100_000)
        engine = _get_or_create_engine(datasource_ids, max_rows=None if (isinstance(max_rows, int) and max_rows <= 0) else max_rows)
        schema_text = engine.get_unified_schema_text()
        registered = engine.get_registered_tables()

        table_mapping = {
            reg.unified_table_name: {
                "datasource_id": reg.datasource_id,
                "original_table": reg.original_table_name,
                "type": reg.datasource_type,
                "row_count": reg.row_count,
                "columns": reg.columns,
            }
            for reg in registered
        }

        payload = {
            "schema": schema_text,
            "table_mapping": table_mapping,
            "join_suggestions": engine.infer_join_suggestions(max_suggestions=12),
            "alignment_views": engine.get_alignment_views(),
            "ega_column_mappings": engine.get_ega_column_mappings(),
            "max_import_rows": max_rows,
            "datasource_count": len(datasource_ids),
            "table_count": len(registered),
            "usage_hint": (
                "Use unified table names like ds1_orders, ds2_customers in SQL. "
                "You can JOIN tables across different datasources directly. "
                "Prefer join_suggestions when choosing join keys."
            ),
        }

        if str(strategy or "legacy").lower() == "ega" and query:
            try:
                from fastapi_app.modules.ega.orchestrator import prepare_ega_context

                ega_context = prepare_ega_context(
                    engine=engine,
                    datasource_ids=datasource_ids,
                    question=query,
                    llm=None,
                    sample_rows=100,
                    optimization_target="accuracy",
                    lambda1=0.3,
                    lambda2=0.5,
                    deep_probe=False,
                )
                payload["ega_context"] = ega_context
                payload["schema"] = (
                    ega_context.get("clean_view_schema")
                    or ega_context.get("filtered_schema")
                    or payload["schema"]
                )
            except Exception as e:
                payload["ega_error"] = str(e)
        elif str(strategy or "legacy").lower() == "ega":
            clean_schema = _build_clean_view_schema_text(engine)
            if clean_schema:
                payload["schema"] = clean_schema

        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        logger.error(f"Failed to get cross-source schema: {e}")
        return json.dumps({"error": f"Failed to get cross-source schema: {str(e)}"}, ensure_ascii=False)


@tool
def execute_cross_source_sql(datasource_ids: List[int], sql: str, limit: int = 1000) -> str:
    """Execute cross-source SQL using DuckDB unified engine."""

    if not datasource_ids:
        return json.dumps({"success": False, "error_message": "Please provide datasource_ids"}, ensure_ascii=False)

    missing = [ds_id for ds_id in datasource_ids if get_datasource_handler(ds_id) is None]
    if missing:
        return json.dumps({"success": False, "error_message": f"Missing datasources: {missing}"}, ensure_ascii=False)

    limit = min(int(limit or 1000), 10000)

    try:
        engine = _get_or_create_engine(datasource_ids)

        attempts = _build_sql_rewrite_candidates(sql, engine)
        result = None
        used_strategy = "original"
        attempt_errors = []
        best_success = None
        for strategy, attempt_sql in attempts:
            result = engine.execute_query(attempt_sql, limit=limit)
            if result.success:
                # Prefer non-empty successful results; keep best empty-success
                # as fallback to avoid locking onto a brittle first-success candidate.
                if int(result.row_count or 0) > 0:
                    used_strategy = strategy
                    best_success = (strategy, result)
                    break
                if best_success is None or int(result.row_count or 0) > int(best_success[1].row_count or 0):
                    best_success = (strategy, result)
                used_strategy = strategy
                continue
            attempt_errors.append({"strategy": strategy, "error": result.error_message})
            used_strategy = strategy

        if best_success is not None:
            used_strategy, result = best_success
        assert result is not None
        return json.dumps(
            {
                "success": result.success,
                "query_text": result.query_text or sql,
                "data": result.data,
                "columns": result.columns,
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
                "error_message": result.error_message,
                "rewrite_strategy": used_strategy,
                "attempt_errors": attempt_errors,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    except Exception as e:
        logger.error(f"Cross-source SQL execution error: {e}\nSQL: {sql}")
        return json.dumps(
            {"success": False, "error_message": f"Cross-source SQL execution failed: {str(e)}", "query_text": sql},
            ensure_ascii=False,
        )


@tool
def prepare_cross_source_ega(
    datasource_ids: List[int],
    query: str,
    mode: str = "accurate",
    deep_probe: bool = False,
) -> str:
    """Prepare EGA context (profiling + alignment + clean views) for cross-source SQL."""
    if not datasource_ids:
        return json.dumps({"success": False, "error": "Please provide at least one datasource_id"}, ensure_ascii=False)
    if not query:
        return json.dumps({"success": False, "error": "query is required"}, ensure_ascii=False)

    missing = [ds_id for ds_id in datasource_ids if get_datasource_handler(ds_id) is None]
    if missing:
        return json.dumps({"success": False, "error": f"Missing datasources: {missing}"}, ensure_ascii=False)

    try:
        from fastapi_app.modules.ega.orchestrator import prepare_ega_context

        engine = _get_or_create_engine(datasource_ids)
        ega_context = prepare_ega_context(
            engine=engine,
            datasource_ids=datasource_ids,
            question=query,
            llm=None,
            sample_rows=100,
            optimization_target=("accuracy" if str(mode).lower().startswith("acc") else "balanced"),
            lambda1=0.3,
            lambda2=0.5,
            deep_probe=bool(deep_probe),
        )
        return json.dumps(
            {
                "success": True,
                "query": query,
                "mode": mode,
                "deep_probe": bool(deep_probe),
                "relevant_tables": ega_context.get("relevant_tables") or [],
                "candidate_columns": ega_context.get("candidate_columns") or [],
                "filtered_schema": ega_context.get("filtered_schema") or "",
                "clean_views": ega_context.get("clean_views") or {},
                "alignment_graph": ega_context.get("alignment_graph") or [],
                "prompt_hint": ega_context.get("prompt_hint") or "",
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    except Exception as e:
        logger.error(f"prepare_cross_source_ega failed: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
