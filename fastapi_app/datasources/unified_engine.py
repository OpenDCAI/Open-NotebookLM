"""
DuckDB 统一查询引擎 - 跨数据源联邦查询

核心设计：
1. 将所有异构数据源注册为 DuckDB 虚拟表
2. 通过单一 DuckDB 实例实现跨源 SQL JOIN
3. 按数据源类型选择最优注册策略：
   - CSV/Parquet: read_csv_auto() 原生注册（最高效）
   - Excel: pandas 中转后注册
   - SQL 数据库: 通过适配器查询后注册（DataFrame 中转，跨平台兼容）
4. 表命名: ds{datasource_id}_{table_name} 避免冲突

使用场景：
    engine = UnifiedQueryEngine()
    engine.register_datasource(1, csv_ds)
    engine.register_datasource(2, pg_ds)
    result = engine.execute_query('''
        SELECT a.*, b.customer_name
        FROM ds1_orders a
        JOIN ds2_customers b ON a.customer_id = b.id
    ''')
    engine.close()
"""

import duckdb
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi_app.core.datasource_interface import (
    DataSourceInterface,
    DataSourceType,
    QueryResult,
    TableSchema,
    ColumnSchema,
    ColumnType,
)

logger = logging.getLogger(__name__)

# Maximum rows to import from SQL databases into DuckDB (safety limit)
DEFAULT_MAX_IMPORT_ROWS = 100_000


@dataclass
class RegisteredTable:
    """Metadata for a table registered in the unified engine."""
    datasource_id: int
    original_table_name: str
    unified_table_name: str  # The name in the unified DuckDB
    datasource_type: str
    row_count: Optional[int] = None
    columns: List[str] = field(default_factory=list)


class UnifiedQueryEngine:
    """
    DuckDB-based unified query engine for cross-datasource queries.

    Registers tables from multiple heterogeneous datasources into a single
    DuckDB in-memory instance, enabling SQL JOINs across CSV + PostgreSQL
    + MySQL + Excel, etc.
    """

    def __init__(self):
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._registered_tables: Dict[str, RegisteredTable] = {}
        self._registered_datasources: set = set()
        # Instance Alignment: normalized views for join keys (per registered table)
        # {unified_table_name: {"view": view_name, "norm_columns": {src_col: norm_col}}}
        self._alignment_views: Dict[str, Dict[str, Any]] = {}
        # EGA mapping cache for clean-view materialization.
        # {base_table: {source_column: {"view": "...", "target_column": "..."}}}
        self._ega_column_mappings: Dict[str, Dict[str, Any]] = {}
        # EGA context cache keyed by query+budget to avoid repeated expensive preparation.
        self._ega_context_cache: Dict[Any, Any] = {}
        self._connect()

    def _connect(self):
        """Create the DuckDB in-memory connection."""
        self._conn = duckdb.connect(":memory:")
        logger.info("UnifiedQueryEngine: DuckDB in-memory connection created")

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._connect()
        return self._conn

    # ========== Registration API ==========

    def register_datasource(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        table_prefix: Optional[str] = None,
        max_rows: Optional[int] = DEFAULT_MAX_IMPORT_ROWS,
        table_names: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Register all (or selected) tables from a datasource into the unified engine.

        Args:
            datasource_id: The datasource identifier
            datasource: The DataSourceInterface instance (must be connected)
            table_prefix: Custom prefix for table names (default: ds{id}_)
            max_rows: Max rows to import from SQL databases (safety limit)
            table_names: Specific tables to register (None = all tables)

        Returns:
            List of unified table names registered
        """
        if datasource_id in self._registered_datasources:
            existing = [
                t.unified_table_name
                for t in self._registered_tables.values()
                if t.datasource_id == datasource_id
            ]
            logger.info(f"Datasource {datasource_id} already registered: {existing}")
            return existing

        prefix = table_prefix or f"ds{datasource_id}_"
        ds_type = datasource.metadata.type

        # Get tables to register
        if table_names:
            tables_to_register = table_names
        else:
            try:
                all_tables = datasource.get_tables()
                tables_to_register = [t.name for t in all_tables]
            except Exception as e:
                logger.error(f"Failed to get tables from datasource {datasource_id}: {e}")
                return []

        registered = []
        for table_name in tables_to_register:
            unified_name = f"{prefix}{table_name}"
            try:
                self._register_single_table(
                    datasource_id=datasource_id,
                    datasource=datasource,
                    table_name=table_name,
                    unified_name=unified_name,
                    ds_type=ds_type,
                    max_rows=max_rows,
                )
                registered.append(unified_name)
                try:
                    self._ensure_norm_view(unified_name)
                except Exception as e:
                    logger.debug(f"Alignment view creation skipped for {unified_name}: {e}")
            except Exception as e:
                logger.error(
                    f"Failed to register table {table_name} from datasource {datasource_id}: {e}"
                )

        self._registered_datasources.add(datasource_id)
        logger.info(
            f"Registered datasource {datasource_id} ({ds_type.code}): "
            f"{len(registered)}/{len(tables_to_register)} tables"
        )
        return registered

    def _register_single_table(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        table_name: str,
        unified_name: str,
        ds_type: DataSourceType,
        max_rows: Optional[int],
    ):
        """Register a single table into the unified DuckDB based on datasource type."""

        if unified_name in self._registered_tables:
            logger.debug(f"Table {unified_name} already registered, skipping")
            return

        if ds_type in (DataSourceType.CSV, DataSourceType.PARQUET):
            self._register_csv_table(datasource_id, datasource, table_name, unified_name)
        elif ds_type == DataSourceType.EXCEL:
            self._register_excel_table(datasource_id, datasource, table_name, unified_name)
        else:
            # SQL databases and others: fetch data via adapter
            self._register_sql_table(datasource_id, datasource, table_name, unified_name, max_rows)

    def _register_csv_table(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        table_name: str,
        unified_name: str,
    ):
        """
        Register a CSV/Parquet table.
        Re-reads the CSV file directly for maximum efficiency.
        """
        config = datasource.metadata.connection_config

        file_path = None
        # Single file mode
        if "file_path" in config:
            file_path = config["file_path"]
        # Multi-file mode: find the matching file
        elif "files" in config:
            for fc in config["files"]:
                fc_name = fc.get("table_name", Path(fc["path"]).stem)
                if fc_name == table_name:
                    file_path = fc["path"]
                    break

        if file_path and Path(file_path).exists():
            # Register directly from CSV file
            sql = f"""
                CREATE TABLE "{unified_name}" AS
                SELECT * FROM read_csv_auto('{file_path}', auto_detect=True)
            """
            self.conn.execute(sql)
            row_count = self.conn.execute(
                f'SELECT COUNT(*) FROM "{unified_name}"'
            ).fetchone()[0]
            columns = [
                desc[0]
                for desc in self.conn.execute(
                    f'DESCRIBE "{unified_name}"'
                ).fetchall()
            ]
        else:
            # Fallback: fetch from datasource's DuckDB
            self._register_via_query(datasource_id, datasource, table_name, unified_name)
            return

        self._registered_tables[unified_name] = RegisteredTable(
            datasource_id=datasource_id,
            original_table_name=table_name,
            unified_table_name=unified_name,
            datasource_type=datasource.metadata.type.code,
            row_count=row_count,
            columns=columns,
        )
        logger.info(f"Registered CSV table: {unified_name} ({row_count} rows)")

    def _register_excel_table(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        table_name: str,
        unified_name: str,
    ):
        """
        Register an Excel table.
        Uses pandas as intermediate to load sheet data into DuckDB.
        """
        try:
            import pandas as pd
        except ImportError:
            logger.warning("pandas not available, falling back to query-based registration")
            self._register_via_query(datasource_id, datasource, table_name, unified_name)
            return

        config = datasource.metadata.connection_config
        file_path = config.get("file_path")

        if file_path and Path(file_path).exists():
            try:
                df = pd.read_excel(file_path, sheet_name=table_name)
                self.conn.execute(
                    f'CREATE TABLE "{unified_name}" AS SELECT * FROM df'
                )
                self._registered_tables[unified_name] = RegisteredTable(
                    datasource_id=datasource_id,
                    original_table_name=table_name,
                    unified_table_name=unified_name,
                    datasource_type="excel",
                    row_count=len(df),
                    columns=list(df.columns),
                )
                logger.info(f"Registered Excel table: {unified_name} ({len(df)} rows)")
                return
            except Exception as e:
                logger.warning(f"Excel direct read failed for {table_name}: {e}")

        # Fallback
        self._register_via_query(datasource_id, datasource, table_name, unified_name)

    def _register_sql_table(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        table_name: str,
        unified_name: str,
        max_rows: Optional[int],
    ):
        """
        Register a SQL database table.
        Fetches data via the adapter and loads into DuckDB via pandas DataFrame.
        """
        self._register_via_query(datasource_id, datasource, table_name, unified_name, max_rows)

    def _register_via_query(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        table_name: str,
        unified_name: str,
        max_rows: Optional[int] = DEFAULT_MAX_IMPORT_ROWS,
    ):
        """
        Generic fallback: fetch data via execute_query() and load into DuckDB.
        Works for any datasource type.
        """
        try:
            import pandas as pd
        except ImportError:
            raise RuntimeError("pandas is required for cross-datasource query support")

        # Fetch data from the datasource
        # max_rows:
        # - None: import full table (benchmark/accuracy mode)
        # - positive int: import at most that many rows (safety/perf)
        effective_limit: Optional[int] = None
        if isinstance(max_rows, int) and max_rows > 0:
            effective_limit = max_rows
        result = datasource.execute_query(f'SELECT * FROM "{table_name}"', limit=effective_limit)

        if not result.success or not result.data:
            logger.warning(
                f"No data fetched from {table_name}: {result.error_message}"
            )
            # Create an empty table with schema
            schema = datasource.get_table_schema(table_name)
            if schema:
                col_defs = ", ".join(
                    f'"{c.name}" VARCHAR' for c in schema.columns
                )
                self.conn.execute(
                    f'CREATE TABLE "{unified_name}" ({col_defs})'
                )
                self._registered_tables[unified_name] = RegisteredTable(
                    datasource_id=datasource_id,
                    original_table_name=table_name,
                    unified_table_name=unified_name,
                    datasource_type=datasource.metadata.type.code,
                    row_count=0,
                    columns=[c.name for c in schema.columns],
                )
            return

        # Convert to DataFrame and register
        df = pd.DataFrame(result.data)
        self.conn.execute(
            f'CREATE TABLE "{unified_name}" AS SELECT * FROM df'
        )

        self._registered_tables[unified_name] = RegisteredTable(
            datasource_id=datasource_id,
            original_table_name=table_name,
            unified_table_name=unified_name,
            datasource_type=datasource.metadata.type.code,
            row_count=len(df),
            columns=list(df.columns),
        )
        logger.info(
            f"Registered table via query: {unified_name} "
            f"({len(df)} rows, {len(df.columns)} cols)"
        )

    # ========== Query Execution ==========

    def execute_query(
        self,
        sql: str,
        limit: Optional[int] = None,
    ) -> QueryResult:
        """
        Execute SQL against the unified engine (all registered tables accessible).

        Args:
            sql: SQL query (reference unified table names like ds1_orders)
            limit: Optional row limit

        Returns:
            QueryResult with standard format
        """
        start_time = time.time()

        try:
            # Add LIMIT if not present
            if limit and "LIMIT" not in sql.upper():
                sql = f"{sql.rstrip(';')} LIMIT {limit}"

            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            data = [dict(zip(columns, row)) for row in result]

            execution_time = (time.time() - start_time) * 1000

            return QueryResult(
                success=True,
                data=data,
                columns=columns,
                row_count=len(data),
                execution_time_ms=execution_time,
                query_text=sql,
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Unified query failed: {e}\nSQL: {sql}")
            return QueryResult(
                success=False,
                error_message=str(e),
                execution_time_ms=execution_time,
                query_text=sql,
            )

    # ========== Schema API ==========

    def get_registered_tables(self) -> List[RegisteredTable]:
        """Get metadata for all registered tables."""
        return list(self._registered_tables.values())

    def get_unified_schema(self) -> List[TableSchema]:
        """Get full schema for all registered tables in the unified engine."""
        schemas = []
        for unified_name, reg in self._registered_tables.items():
            try:
                columns_result = self.conn.execute(
                    f'DESCRIBE "{unified_name}"'
                ).fetchall()

                columns = []
                for row in columns_result:
                    col_name = row[0]
                    col_type_native = row[1]
                    col_type = ColumnType.from_native_type(
                        col_type_native, DataSourceType.CSV  # DuckDB types
                    )
                    columns.append(
                        ColumnSchema(
                            name=col_name,
                            data_type=col_type,
                            native_type=col_type_native,
                        )
                    )

                schemas.append(
                    TableSchema(
                        name=unified_name,
                        columns=columns,
                        row_count=reg.row_count,
                        comment=(
                            f"From datasource {reg.datasource_id} "
                            f"({reg.datasource_type}), "
                            f"original table: {reg.original_table_name}"
                        ),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to get schema for {unified_name}: {e}")

        return schemas

    def get_unified_schema_text(self) -> str:
        """Get LLM-friendly schema text for all registered tables."""
        schemas = self.get_unified_schema()
        if not schemas:
            return "No tables registered in the unified query engine."

        lines = ["=== Cross-Source Unified Schema ===\n"]
        for schema in schemas:
            lines.append(schema.to_llm_description())
            lines.append("")  # blank line between tables

        # Add table mapping info
        lines.append("--- Table Mapping ---")
        for unified_name, reg in self._registered_tables.items():
            lines.append(
                f"  {unified_name} ← datasource#{reg.datasource_id}.{reg.original_table_name} "
                f"({reg.datasource_type})"
            )

        if self._alignment_views:
            lines.append("")
            lines.append("--- Alignment Views (Instance Alignment) ---")
            for base, info in self._alignment_views.items():
                v = info.get("view")
                norm_cols = info.get("norm_columns") or {}
                show = ", ".join(f"{k}->{val}" for k, val in list(norm_cols.items())[:6])
                lines.append(f"  {base} -> {v} ({show})")

        return "\n".join(lines)

    def get_alignment_views(self) -> Dict[str, Any]:
        """Return alignment (normalization) views metadata."""
        return {k: dict(v) for k, v in (self._alignment_views or {}).items()}

    # ========== EGA Utilities ==========

    def sample_column_values(self, table_name: str, column_name: str, limit: int = 100) -> List[Any]:
        """Sample raw values for a given column."""
        rows = self.conn.execute(
            f'SELECT "{column_name}" FROM "{table_name}" LIMIT {int(limit)}'
        ).fetchall()
        return [r[0] for r in rows]

    def sample_distinct_values(self, table_name: str, column_name: str, limit: int = 1200) -> List[str]:
        """Sample distinct non-null/non-empty stringified values for set overlap analysis."""
        rows = self.conn.execute(
            f'SELECT DISTINCT CAST("{column_name}" AS VARCHAR) '
            f'FROM "{table_name}" '
            f'WHERE "{column_name}" IS NOT NULL AND CAST("{column_name}" AS VARCHAR) <> \'\' '
            f'LIMIT {int(limit)}'
        ).fetchall()
        out: List[str] = []
        for (v,) in rows:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                out.append(s)
        return out

    def compute_overlap_stats(
        self,
        left_table: str,
        left_column: str,
        right_table: str,
        right_column: str,
        limit: int = 1200,
    ) -> Dict[str, Any]:
        """Compute overlap stats for two columns."""
        a = set(self.sample_distinct_values(left_table, left_column, limit=limit))
        b = set(self.sample_distinct_values(right_table, right_column, limit=limit))
        inter = a & b
        denom_min = max(1, min(len(a), len(b)))
        denom_union = max(1, len(a | b))
        return {
            "left_count": len(a),
            "right_count": len(b),
            "intersection_count": len(inter),
            "overlap_min": len(inter) / denom_min,
            "jaccard": len(inter) / denom_union,
        }

    def cache_ega_column_mapping(self, base_table: str, source_column: str, mapping: Dict[str, Any]) -> None:
        self._ega_column_mappings.setdefault(base_table, {})[source_column] = dict(mapping or {})

    def get_ega_column_mappings(self) -> Dict[str, Any]:
        return {t: dict(cols) for t, cols in (self._ega_column_mappings or {}).items()}

    # ========== Join Suggestions (Heuristic) ==========

    def infer_join_suggestions(self, max_suggestions: int = 12) -> List[str]:
        """
        Heuristically infer likely join keys across registered tables.

        This is intentionally simple and deterministic (no LLM). It helps cross-source
        queries succeed by giving the model concrete JOIN candidates, especially when
        users ask to combine orders + customers + products across datasources.
        """

        def _norm(s: str) -> str:
            return (s or "").strip().lower()

        def _table_kind(name: str) -> str:
            n = _norm(name)
            if "customer" in n or "clients" in n:
                return "customer"
            if "order" in n:
                return "order"
            if "product" in n or "item" in n:
                return "product"
            if "employee" in n or "staff" in n:
                return "employee"
            if "city" in n or "region" in n or "area" in n:
                return "geo"
            return "other"

        def _preferred_id_cols(cols: List[str]) -> List[str]:
            c = [_norm(x) for x in (cols or [])]
            # Put likely keys first
            score = []
            for col in c:
                s = 0
                if col == "id":
                    s += 5
                if col.endswith("_id"):
                    s += 4
                if col.endswith("id"):
                    s += 2
                if col.endswith("_code") or col.endswith("code"):
                    s += 1
                score.append((s, col))
            score.sort(key=lambda x: x[0], reverse=True)
            return [col for s, col in score if s > 0]

        tables = list(self._registered_tables.values())
        if len(tables) < 2:
            return []

        suggestions: List[str] = []
        seen = set()

        # Prefer joinability-based suggestions (Instance Alignment).
        try:
            suggestions.extend(self._infer_join_suggestions_by_overlap(max_suggestions=max_suggestions))
        except Exception:
            pass

        # Pairwise across different datasources
        for i in range(len(tables)):
            a = tables[i]
            a_kind = _table_kind(a.original_table_name)
            a_cols = [_norm(x) for x in (a.columns or [])]
            a_cols_set = set(a_cols)
            a_pref = _preferred_id_cols(a.columns)

            for j in range(i + 1, len(tables)):
                b = tables[j]
                if a.datasource_id == b.datasource_id:
                    continue
                b_kind = _table_kind(b.original_table_name)
                b_cols = [_norm(x) for x in (b.columns or [])]
                b_cols_set = set(b_cols)
                b_pref = _preferred_id_cols(b.columns)

                # 1) Exact same column names (strongest signal)
                common = list(a_cols_set & b_cols_set)
                common.sort(key=lambda x: (0 if x == "id" else 1, 0 if x.endswith("_id") else 1, x))
                for col in common[:3]:
                    if col in ("id",) or col.endswith("_id") or col.endswith("id"):
                        key = (a.unified_table_name, b.unified_table_name, col, col)
                        if key in seen:
                            continue
                        seen.add(key)
                        suggestions.append(
                            f"{a.unified_table_name}.{col} = {b.unified_table_name}.{col} (same column name)"
                        )
                        if len(suggestions) >= max_suggestions:
                            return suggestions

                # 2) Foreign-key style: xxx_id -> id on the dimension table
                # Example: orders.customer_id -> customers.id
                for fk in a_pref[:6]:
                    if not fk.endswith("_id"):
                        continue
                    entity = fk[: -len("_id")]
                    if entity and (entity in _norm(b.original_table_name) or b_kind == entity):
                        if "id" in b_cols_set:
                            key = (a.unified_table_name, b.unified_table_name, fk, "id")
                            if key in seen:
                                continue
                            seen.add(key)
                            suggestions.append(
                                f"{a.unified_table_name}.{fk} = {b.unified_table_name}.id (fk-style)"
                            )
                            if len(suggestions) >= max_suggestions:
                                return suggestions

                for fk in b_pref[:6]:
                    if not fk.endswith("_id"):
                        continue
                    entity = fk[: -len("_id")]
                    if entity and (entity in _norm(a.original_table_name) or a_kind == entity):
                        if "id" in a_cols_set:
                            key = (b.unified_table_name, a.unified_table_name, fk, "id")
                            if key in seen:
                                continue
                            seen.add(key)
                            suggestions.append(
                                f"{b.unified_table_name}.{fk} = {a.unified_table_name}.id (fk-style)"
                            )
                            if len(suggestions) >= max_suggestions:
                                return suggestions

                # 3) Entity id alignment: customer_id <-> customer_id, product_id <-> id/product_id
                for fk in a_pref[:6]:
                    if fk.endswith("_id") and fk in b_cols_set:
                        key = (a.unified_table_name, b.unified_table_name, fk, fk)
                        if key in seen:
                            continue
                        seen.add(key)
                        suggestions.append(
                            f"{a.unified_table_name}.{fk} = {b.unified_table_name}.{fk} (shared *_id)"
                        )
                        if len(suggestions) >= max_suggestions:
                            return suggestions

        return suggestions[:max_suggestions]

    # ========== Instance Alignment (Normalization Views + Joinability) ==========

    def _ensure_norm_view(self, unified_table_name: str) -> None:
        """Create/refresh a normalized view for id-like columns to improve JOIN success.

        View name: {unified_table_name}__norm
        Normalized columns: {col}__norm for id-like columns.
        """
        reg = self._registered_tables.get(unified_table_name)
        if not reg:
            return

        cols = list(reg.columns or [])
        if not cols:
            return

        def _is_id_like(col: str) -> bool:
            n = (col or "").strip().lower()
            if n == "id":
                return True
            if n.endswith("_id"):
                return True
            if n.endswith("id") and len(n) <= 12:
                return True
            # Common obfuscated/abbreviated key styles: sid, cid, uid, *_key
            if re.search(r"(^|_)(sid|cid|uid|gid|pk|fk|key)(_|$)", n):
                return True
            if "id" in n and len(n) <= 40 and ("key" in n or "dirty" in n):
                return True
            if n.endswith("_code") or n.endswith("code"):
                return True
            return False

        id_cols = [c for c in cols if _is_id_like(c)]
        if not id_cols:
            return

        def _normalized_id_expr(col: str) -> str:
            q = f'"{col}"'
            # Prefer digit canonicalization (S-0001 -> 1) when digits exist,
            # fallback to conservative alnum normalization for textual IDs.
            return (
                f"CASE "
                f"WHEN regexp_extract(CAST({q} AS VARCHAR), '[0-9]+') <> '' "
                f"THEN CAST(CAST(regexp_extract(CAST({q} AS VARCHAR), '[0-9]+') AS BIGINT) AS VARCHAR) "
                f"ELSE regexp_replace(lower(trim(CAST({q} AS VARCHAR))), '[^0-9a-z]', '', 'g') "
                f"END"
            )

        view_name = f"{unified_table_name}__norm"
        select_exprs: List[str] = []
        norm_map: Dict[str, str] = {}

        id_set = set(id_cols[:20])
        for c in cols:
            qc = f'"{c}"'
            if c in id_set:
                norm_col = f"{c}__norm"
                raw_col = f"{c}__raw"
                norm_map[c] = norm_col
                norm_expr = _normalized_id_expr(c)
                # Overwrite id-like base column with canonicalized value to make
                # naive joins more robust; keep original in *__raw.
                select_exprs.append(f"{norm_expr} AS \"{c}\"")
                select_exprs.append(f"{qc} AS \"{raw_col}\"")
                select_exprs.append(f"{norm_expr} AS \"{norm_col}\"")
            else:
                select_exprs.append(qc)

        sql = (
            f'CREATE OR REPLACE VIEW "{view_name}" AS SELECT '
            + ", ".join(select_exprs)
            + f' FROM "{unified_table_name}"'
        )
        self.conn.execute(sql)
        self._alignment_views[unified_table_name] = {"view": view_name, "norm_columns": norm_map}

    def _infer_join_suggestions_by_overlap(self, max_suggestions: int = 12) -> List[str]:
        """Infer join suggestions by value overlap on normalized columns (bounded sampling)."""

        def _sample(view_name: str, col_name: str, limit: int = 1200) -> set[str]:
            try:
                rows = self.conn.execute(
                    f'SELECT DISTINCT "{col_name}" FROM "{view_name}" '
                    f'WHERE "{col_name}" IS NOT NULL AND CAST("{col_name}" AS VARCHAR) <> \'\' '
                    f"LIMIT {int(limit)}"
                ).fetchall()
                out = set()
                for (v,) in rows:
                    if v is None:
                        continue
                    s = str(v).strip()
                    if s:
                        out.add(s)
                return out
            except Exception:
                return set()

        tables = list(self._registered_tables.values())
        if len(tables) < 2 or not self._alignment_views:
            return []

        cache: Dict[tuple, set[str]] = {}
        scored: List[tuple] = []

        for i in range(len(tables)):
            a = tables[i]
            a_info = self._alignment_views.get(a.unified_table_name) or {}
            a_view = a_info.get("view")
            a_norm_cols = list((a_info.get("norm_columns") or {}).values())
            if not a_view or not a_norm_cols:
                continue

            for j in range(i + 1, len(tables)):
                b = tables[j]
                if a.datasource_id == b.datasource_id:
                    continue
                b_info = self._alignment_views.get(b.unified_table_name) or {}
                b_view = b_info.get("view")
                b_norm_cols = list((b_info.get("norm_columns") or {}).values())
                if not b_view or not b_norm_cols:
                    continue

                for a_nc in a_norm_cols[:8]:
                    a_key = (a_view, a_nc)
                    a_vals = cache.get(a_key)
                    if a_vals is None:
                        a_vals = _sample(str(a_view), str(a_nc))
                        cache[a_key] = a_vals
                    if not a_vals:
                        continue

                    for b_nc in b_norm_cols[:8]:
                        b_key = (b_view, b_nc)
                        b_vals = cache.get(b_key)
                        if b_vals is None:
                            b_vals = _sample(str(b_view), str(b_nc))
                            cache[b_key] = b_vals
                        if not b_vals:
                            continue

                        inter = a_vals & b_vals
                        denom = min(len(a_vals), len(b_vals))
                        if denom <= 0:
                            continue
                        overlap = len(inter) / denom
                        if overlap < 0.35 or len(inter) < 3:
                            continue

                        sql = (
                            f"{a_view}.{a_nc} = {b_view}.{b_nc} "
                            f"(value-overlap={overlap:.2f}, sample_intersection={len(inter)})"
                        )
                        scored.append((overlap, len(inter), sql))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        out: List[str] = []
        seen_sql = set()
        for _, __, sql in scored:
            if len(out) >= int(max_suggestions):
                break
            if sql in seen_sql:
                continue
            seen_sql.add(sql)
            out.append(sql)
        return out

    # ========== Lifecycle ==========

    def close(self):
        """Close the unified engine and release resources."""
        if self._conn:
            try:
                self._conn.close()
            except Exception as e:
                logger.warning(f"Error closing unified engine: {e}")
            self._conn = None
            self._registered_tables.clear()
            self._registered_datasources.clear()
            self._alignment_views.clear()
            self._ega_column_mappings.clear()
            self._ega_context_cache.clear()
            logger.info("UnifiedQueryEngine closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self):
        return (
            f"<UnifiedQueryEngine tables={len(self._registered_tables)} "
            f"datasources={len(self._registered_datasources)}>"
        )
