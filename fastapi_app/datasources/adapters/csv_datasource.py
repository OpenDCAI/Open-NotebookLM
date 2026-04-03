"""
CSV数据源适配器（基于DuckDB）

核心设计：
1. 使用DuckDB作为SQL查询引擎 - 比Pandas更强大，支持完整SQL语法
2. CSV文件被注册为虚拟表 - 可以像操作数据库一样查询CSV
3. 支持多文件JOIN - DuckDB原生支持
4. 类型推断 - 自动检测列类型
5. 高性能 - DuckDB针对OLAP优化

优势对比：
- SQLBot: CSV -> PostgreSQL临时表（需要导入，占用磁盘）
- 我们: CSV -> DuckDB内存表（零导入，内存查询）
- Pandas: 受限的query语法，不支持复杂SQL
- DuckDB: 完整SQL支持，还比Pandas快

参考资料：
- DuckDB文档: https://duckdb.org/docs/data/csv
- SQLBot的Excel处理: apps/db/engine.py
"""

import duckdb
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import time
import re

from fastapi_app.core.datasource_interface import (
    DataSourceInterface,
    DataSourceMetadata,
    DataSourceType,
    TableSchema,
    ColumnSchema,
    ColumnType,
    QueryResult,
    ConnectionException,
    QueryException,
    SchemaException,
)

logger = logging.getLogger(__name__)


class CSVDataSource(DataSourceInterface):
    """
    CSV文件数据源（基于DuckDB）

    使用方式：
    ```python
    # 单文件（DuckDB会自动检测编码和分隔符）
    metadata = DataSourceMetadata(
        id="csv_sales",
        name="销售数据",
        type=DataSourceType.CSV,
        connection_config={
            "file_path": "/path/to/sales.csv",
            # "delimiter": ",",  # 可选，不指定会自动检测
            "has_header": True,  # 可选，默认True
            "auto_detect": True,  # 可选，自动检测编码、分隔符等
        }
    )
    ds = CSVDataSource(metadata)
    ds.connect()
    result = ds.execute_query("SELECT * FROM sales WHERE amount > 1000")

    # 多文件（用于JOIN）
    metadata = DataSourceMetadata(
        id="csv_multi",
        name="多表数据",
        type=DataSourceType.CSV,
        connection_config={
            "files": [
                {"path": "/path/to/orders.csv", "table_name": "orders"},
                {"path": "/path/to/customers.csv", "table_name": "customers"},
            ],
            "auto_detect": True,  # DuckDB自动检测编码、分隔符等
        }
    )
    ds = CSVDataSource(metadata)
    ds.connect()
    result = ds.execute_query('''
        SELECT o.*, c.customer_name
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
    ''')
    ```
    """

    def __init__(self, metadata: DataSourceMetadata):
        super().__init__(metadata)
        self.conn: Optional[duckdb.DuckDBPyConnection] = None
        self._tables_cache: Dict[str, TableSchema] = {}

    def connect(self) -> bool:
        """
        建立DuckDB连接并注册CSV文件
        """
        try:
            # 创建内存数据库连接
            self.conn = duckdb.connect(':memory:')

            # 注册CSV文件
            self._register_csv_files()

            self._connected = True
            logger.info(f"Successfully connected to CSV datasource: {self.metadata.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect CSV datasource: {e}")
            raise ConnectionException(f"CSV连接失败: {str(e)}")

    def disconnect(self):
        """断开连接"""
        if self.conn:
            try:
                self.conn.close()
                self._connected = False
                logger.info(f"Disconnected from CSV datasource: {self.metadata.name}")
            except Exception as e:
                logger.warning(f"Error disconnecting CSV datasource: {e}")

    def test_connection(self) -> bool:
        """测试连接"""
        if not self.conn:
            return False
        try:
            # 简单查询测试
            self.conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def _register_csv_files(self):
        """
        注册CSV文件为DuckDB表

        DuckDB特性：
        1. read_csv_auto() - 自动检测分隔符、类型、编码
        2. 支持压缩文件（.gz, .zip）
        3. 支持通配符（*.csv）
        4. 支持远程文件（http://...）
        """
        config = self.metadata.connection_config

        # 模式1: 单文件
        if "file_path" in config:
            file_path = Path(config["file_path"])
            if not file_path.exists():
                raise FileNotFoundError(f"CSV文件不存在: {file_path}")

            # 表名默认为文件名（不含扩展名）
            table_name = config.get("table_name", file_path.stem)

            # 构建读取选项
            read_options = self._build_read_options(config)

            # 注册为表
            self._register_single_csv(file_path, table_name, read_options)

        # 模式2: 多文件
        elif "files" in config:
            for file_config in config["files"]:
                file_path = Path(file_config["path"])
                if not file_path.exists():
                    logger.warning(f"CSV文件不存在，跳过: {file_path}")
                    continue

                table_name = file_config.get("table_name", file_path.stem)
                read_options = self._build_read_options({**config, **file_config})
                self._register_single_csv(file_path, table_name, read_options)

        else:
            raise ValueError("connection_config必须包含file_path或files")

    def _build_read_options(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建CSV读取选项

        DuckDB read_csv_auto参数（注意：不支持encoding，会自动检测）：
        - delim/sep: 分隔符
        - header: 是否有表头
        - null_padding: 填充缺失列
        - ignore_errors: 忽略解析错误
        - dateformat: 日期格式
        - auto_detect: 自动检测（默认true）
        """
        options = {}

        # 分隔符（如果不指定，DuckDB会自动检测）
        if "delimiter" in config:
            options["delim"] = config["delimiter"]
        elif "sep" in config:
            options["delim"] = config["sep"]

        # 表头
        if "has_header" in config:
            options["header"] = config["has_header"]

        # 日期格式
        if "date_format" in config:
            options["dateformat"] = config["date_format"]

        # 其他选项
        options["null_padding"] = config.get("null_padding", True)
        options["ignore_errors"] = config.get("ignore_errors", False)
        # DuckDB 1.5 在包含 quoted new lines 的 CSV 上，parallel + null_padding 会报错。
        # 这里默认关闭并行扫描，优先保证通用 CSV 能稳定导入。
        options["parallel"] = config.get("parallel", False)
        
        # 自动检测（包括编码、分隔符等）
        options["auto_detect"] = config.get("auto_detect", True)

        return options

    def _clean_table_name(self, name: str) -> str:
        """Normalize CSV-derived table names into DuckDB-safe identifiers."""
        cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", (name or "").strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if cleaned and cleaned[0].isdigit():
            cleaned = f"table_{cleaned}"
        return cleaned or "csv_data"

    def _quote_identifier(self, name: str) -> str:
        return f'"{str(name).replace(chr(34), chr(34) * 2)}"'

    def _register_single_csv(self, file_path: Path, table_name: str, options: Dict[str, Any]):
        """
        注册单个CSV文件

        DuckDB的read_csv_auto非常智能：
        1. 自动检测类型（比Pandas准确）
        2. 自动处理引号、转义
        3. 自动检测编码（如果未指定）
        """
        try:
            safe_table_name = self._clean_table_name(table_name)
            if safe_table_name != table_name:
                logger.info("Normalized CSV table name from '%s' to '%s'", table_name, safe_table_name)

            # 构建SQL（CREATE TABLE AS SELECT）
            option_str = ", ".join(f"{k}={repr(v)}" for k, v in options.items())
            escaped_path = str(file_path).replace("'", "''")
            sql = f"""
                CREATE TABLE {self._quote_identifier(safe_table_name)} AS
                SELECT * FROM read_csv_auto('{escaped_path}', {option_str})
            """

            self.conn.execute(sql)
            logger.info(f"Registered CSV as table '{safe_table_name}': {file_path}")

        except Exception as e:
            logger.error(f"Failed to register CSV {file_path}: {e}")
            raise SchemaException(f"CSV注册失败: {str(e)}")

    # ========== Schema获取 ==========

    def get_tables(self) -> List[TableSchema]:
        """
        获取所有表的Schema

        DuckDB信息查询：
        - information_schema.tables: 表元数据
        - information_schema.columns: 列元数据
        - table_info(table_name): 快速获取表信息
        """
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")

        try:
            # 查询所有表
            result = self.conn.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                AND table_type = 'BASE TABLE'
            """).fetchall()

            tables = []
            for (table_name,) in result:
                schema = self.get_table_schema(table_name)
                if schema:
                    tables.append(schema)
                    # 缓存
                    self._tables_cache[table_name] = schema

            return tables

        except Exception as e:
            logger.error(f"Failed to get tables: {e}")
            raise SchemaException(f"获取表列表失败: {str(e)}")

    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """
        获取单个表的Schema

        使用DuckDB的DESCRIBE或table_info()
        """
        # 检查缓存
        if table_name in self._tables_cache:
            return self._tables_cache[table_name]

        if not self.is_connected:
            raise ConnectionException("未连接到数据源")

        try:
            # 使用DESCRIBE获取列信息
            columns_result = self.conn.execute(f"DESCRIBE {self._quote_identifier(table_name)}").fetchall()

            columns = []
            for row in columns_result:
                col_name = row[0]
                col_type_native = row[1]
                col_nullable = row[2] == 'YES' if len(row) > 2 else True

                # 转换为标准类型
                col_type = ColumnType.from_native_type(col_type_native, DataSourceType.CSV)

                # 获取样本值和统计信息
                sample_values = self._get_column_samples(table_name, col_name)
                stats = self._get_column_stats(table_name, col_name, col_type)

                column = ColumnSchema(
                    name=col_name,
                    data_type=col_type,
                    native_type=col_type_native,
                    nullable=col_nullable,
                    sample_values=sample_values,
                    **stats
                )
                columns.append(column)

            # 获取行数
            row_count = self.get_table_row_count(table_name)

            table_schema = TableSchema(
                name=table_name,
                columns=columns,
                row_count=row_count,
                comment=f"CSV文件: {self.metadata.connection_config.get('file_path', 'multiple files')}",
            )

            # 缓存
            self._tables_cache[table_name] = table_schema

            return table_schema

        except Exception as e:
            logger.error(f"Failed to get schema for table {table_name}: {e}")
            return None

    def _get_column_samples(self, table_name: str, column_name: str, limit: int = 5) -> List[Any]:
        """获取列的样本值（去重）"""
        try:
            result = self.conn.execute(f"""
                SELECT DISTINCT "{column_name}"
                FROM {self._quote_identifier(table_name)}
                WHERE "{column_name}" IS NOT NULL
                LIMIT {limit}
            """).fetchall()
            return [row[0] for row in result]
        except Exception:
            return []

    def _get_column_stats(self, table_name: str, column_name: str, col_type: ColumnType) -> Dict[str, Any]:
        """获取列的统计信息"""
        stats = {}

        try:
            # 基础统计
            result = self.conn.execute(f"""
                SELECT
                    COUNT(DISTINCT "{column_name}") as distinct_count,
                    COUNT(*) - COUNT("{column_name}") as null_count
                FROM {self._quote_identifier(table_name)}
            """).fetchone()

            stats["distinct_count"] = result[0]
            stats["null_count"] = result[1]

            # 数值统计
            if col_type in [ColumnType.INTEGER, ColumnType.BIGINT, ColumnType.FLOAT,
                          ColumnType.DOUBLE, ColumnType.DECIMAL]:
                num_result = self.conn.execute(f"""
                    SELECT
                        MIN("{column_name}") as min_val,
                        MAX("{column_name}") as max_val,
                        AVG("{column_name}") as avg_val
                    FROM {self._quote_identifier(table_name)}
                    WHERE "{column_name}" IS NOT NULL
                """).fetchone()

                if num_result:
                    stats["min_value"] = float(num_result[0]) if num_result[0] is not None else None
                    stats["max_value"] = float(num_result[1]) if num_result[1] is not None else None
                    stats["avg_value"] = float(num_result[2]) if num_result[2] is not None else None

        except Exception as e:
            logger.warning(f"Failed to get stats for {table_name}.{column_name}: {e}")

        return stats

    # ========== 查询执行 ==========

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """
        执行SQL查询

        DuckDB优势：
        1. 支持完整的SQL语法（JOIN, GROUP BY, 窗口函数等）
        2. 比Pandas快10-100倍
        3. 支持参数化查询（防止SQL注入）
        4. 支持查询缓存
        """
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")

        start_time = time.time()

        try:
            # 添加LIMIT限制（安全措施）
            if limit and "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"

            # 执行查询
            if params:
                # 参数化查询
                result = self.conn.execute(query, params).fetchall()
                columns = [desc[0] for desc in self.conn.description]
            else:
                result = self.conn.execute(query).fetchall()
                columns = [desc[0] for desc in self.conn.description]

            # 转换为字典列表
            data = [dict(zip(columns, row)) for row in result]

            execution_time = (time.time() - start_time) * 1000  # 毫秒

            return QueryResult(
                success=True,
                data=data,
                columns=columns,
                row_count=len(data),
                execution_time_ms=execution_time,
                query_text=query,
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Query execution failed: {e}\nQuery: {query}")

            return QueryResult(
                success=False,
                error_message=str(e),
                execution_time_ms=execution_time,
                query_text=query,
            )

    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """构建样本数据查询"""
        return f'SELECT * FROM {self._quote_identifier(table_name)} LIMIT {limit}'

    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询"""
        return f'SELECT COUNT(*) as count FROM {self._quote_identifier(table_name)}'

    # ========== 扩展功能 ==========

    def export_to_parquet(self, table_name: str, output_path: Path):
        """
        导出表为Parquet格式

        DuckDB原生支持Parquet导出，比CSV更高效
        """
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")

        try:
            self.conn.execute(f"""
                COPY {self._quote_identifier(table_name)} TO '{output_path}' (FORMAT PARQUET)
            """)
            logger.info(f"Exported {table_name} to {output_path}")
        except Exception as e:
            logger.error(f"Failed to export to Parquet: {e}")
            raise QueryException(f"导出Parquet失败: {str(e)}")

    def analyze_table(self, table_name: str) -> Dict[str, Any]:
        """
        分析表（类似ANALYZE命令）

        返回详细的统计信息，用于查询优化
        """
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")

        try:
            # DuckDB的summarize函数
            result = self.conn.execute(f"SUMMARIZE {self._quote_identifier(table_name)}").fetchall()

            analysis = {
                "table_name": table_name,
                "columns": []
            }

            for row in result:
                col_info = {
                    "column_name": row[0],
                    "column_type": row[1],
                    "min": row[2],
                    "max": row[3],
                    "unique_count": row[4] if len(row) > 4 else None,
                    "null_count": row[5] if len(row) > 5 else None,
                }
                analysis["columns"].append(col_info)

            return analysis

        except Exception as e:
            logger.error(f"Failed to analyze table {table_name}: {e}")
            raise QueryException(f"表分析失败: {str(e)}")
