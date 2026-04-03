"""
SQL数据库数据源适配器

支持的数据库：
- PostgreSQL
- MySQL
- SQLite
- ClickHouse
- Oracle
- SQL Server

核心设计：
1. 使用SQLAlchemy作为统一接口 - 屏蔽数据库差异
2. 连接池管理 - 高性能和资源复用
3. 超时控制 - 防止慢查询阻塞
4. 参数化查询 - 防止SQL注入
5. 连接测试 - 健康检查

参考SQLBot的优秀实践：
- apps/db/db.py: get_engine, exec_sql
- apps/db/constant.py: DB枚举（引号处理）
- apps/datasource/crud/datasource.py: check_connection

优化点：
- SQLBot为每个数据库硬编码了逻辑，我们用SQLAlchemy统一
- SQLBot的check_connection在每次查询前都调用，我们缓存连接状态
- SQLBot混合使用SQLAlchemy和原生驱动，我们统一用SQLAlchemy
"""

import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import time

from sqlalchemy import (
    create_engine, text, inspect, MetaData, Table, Column,
    Integer, String, Float, Boolean, Date, DateTime, Text, BigInteger
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool, NullPool, StaticPool
from sqlalchemy.exc import SQLAlchemyError, OperationalError

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
    ConfigurationException,
)

logger = logging.getLogger(__name__)


class SQLDataSource(DataSourceInterface):
    """
    SQL数据库数据源

    连接配置示例：
    ```python
    # PostgreSQL
    metadata = DataSourceMetadata(
        id="pg_main",
        name="主数据库",
        type=DataSourceType.POSTGRESQL,
        connection_config={
            "host": "localhost",
            "port": 5432,
            "database": "mydb",
            "username": "user",
            "password": "pass",
            "schema": "public",  # 可选
            "timeout": 30,  # 可选，默认30秒
            "pool_size": 5,  # 可选，连接池大小
            "pool_recycle": 3600,  # 可选，连接回收时间（秒）
            "extra_params": "sslmode=require",  # 可选，额外JDBC参数
        }
    )

    # MySQL
    metadata = DataSourceMetadata(
        id="mysql_main",
        name="MySQL数据库",
        type=DataSourceType.MYSQL,
        connection_config={
            "host": "localhost",
            "port": 3306,
            "database": "mydb",
            "username": "root",
            "password": "password",
            "charset": "utf8mb4",  # 推荐
            "timeout": 30,
        }
    )

    # SQLite
    metadata = DataSourceMetadata(
        id="sqlite_local",
        name="本地SQLite",
        type=DataSourceType.SQLITE,
        connection_config={
            "database_path": "/path/to/database.db",
        }
    )
    ```

    使用示例：
    ```python
    ds = SQLDataSource(metadata)
    with ds:  # 自动连接和断开
        # 获取表列表
        tables = ds.get_tables()

        # 查询数据
        result = ds.execute_query(
            "SELECT * FROM users WHERE age > :age",
            params={"age": 18},
            limit=100
        )

        # 获取样本数据
        sample = ds.get_sample_data("users", limit=10)
    ```
    """

    def __init__(self, metadata: DataSourceMetadata):
        super().__init__(metadata)
        self.engine: Optional[Engine] = None
        self._inspector = None  # SQLAlchemy Inspector
        self._metadata_obj = None  # SQLAlchemy MetaData
        self._tables_cache: Dict[str, TableSchema] = {}

    def connect(self) -> bool:
        """
        建立数据库连接

        参考SQLBot的get_engine设计，但改进：
        1. 统一使用SQLAlchemy，不混用原生驱动
        2. 连接池配置更合理
        3. 超时控制更完善
        """
        try:
            # 构建连接URL
            db_url = self._build_connection_url()

            # 连接参数
            connect_args = self._build_connect_args()

            # 连接池配置（参考SQLBot的pool_timeout）
            # SQLite 文件库：使用 NullPool（避免线程/锁问题，且不传 pool_*）
            # SQLite 内存库（:memory:）：必须复用同一连接，否则每次 connect 都是新库
            config = self.metadata.connection_config
            if self.metadata.type == DataSourceType.SQLITE:
                db_path = config.get("database_path", ":memory:")
                if db_path == ":memory:":
                    poolclass = StaticPool
                    connect_args.setdefault("check_same_thread", False)
                else:
                    poolclass = NullPool
            else:
                poolclass = QueuePool

            engine_kwargs = dict(
                connect_args=connect_args,
                echo=False,  # 不打印SQL（生产环境）
                poolclass=poolclass,
            )
            if poolclass == QueuePool:
                engine_kwargs["pool_size"] = config.get("pool_size", 5)
                engine_kwargs["pool_recycle"] = config.get("pool_recycle", 3600)
                engine_kwargs["pool_timeout"] = config.get("timeout", 30)
                engine_kwargs["pool_pre_ping"] = True
            # NullPool 不接受 pool_* 参数，不添加

            self.engine = create_engine(db_url, **engine_kwargs)

            # 测试连接
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            # 创建Inspector（用于Schema查询）
            self._inspector = inspect(self.engine)

            # 创建MetaData对象
            self._metadata_obj = MetaData()

            self._connected = True
            logger.info(f"Successfully connected to SQL datasource: {self.metadata.name} ({self.metadata.type.code})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to SQL datasource {self.metadata.name}: {e}")
            raise ConnectionException(f"数据库连接失败: {str(e)}")

    def disconnect(self):
        """断开连接"""
        if self.engine:
            try:
                self.engine.dispose()
                self._connected = False
                self._inspector = None
                self._metadata_obj = None
                logger.info(f"Disconnected from SQL datasource: {self.metadata.name}")
            except Exception as e:
                logger.warning(f"Error disconnecting SQL datasource: {e}")

    def test_connection(self) -> bool:
        """
        测试连接
        参考SQLBot的check_connection
        """
        if not self.engine:
            return False

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def _build_connection_url(self) -> str:
        """
        构建数据库连接URL

        参考SQLBot的get_uri_from_config，但简化：
        - 使用SQLAlchemy的URL格式
        - 自动处理特殊字符（urllib.parse.quote）
        - 支持SQLite相对路径
        """
        config = self.metadata.connection_config
        ds_type = self.metadata.type

        # SQLite特殊处理
        if ds_type == DataSourceType.SQLITE:
            db_path = config.get("database_path", ":memory:")
            readonly = str(config.get("readonly", "")).strip().lower() in {"1", "true", "yes", "on"}
            if readonly and db_path != ":memory:":
                # Use SQLite URI mode to open in read-only to avoid creating journals on restricted filesystems.
                # SQLAlchemy expects: sqlite:///file:path?mode=ro&uri=true
                p = Path(db_path).expanduser()
                try:
                    p = p.resolve()
                except Exception:
                    pass
                uri_path = urllib.parse.quote(p.as_posix())
                return f"sqlite:///file:{uri_path}?mode=ro&uri=true"

            return f"sqlite:///{db_path}"

        # 其他数据库通用格式
        host = config.get("host", "localhost")
        port = config.get("port", self._get_default_port())
        database = config.get("database")
        username = config.get("username")
        password = config.get("password")

        if not database:
            raise ConfigurationException("Missing required config: database")
        if not username:
            raise ConfigurationException("Missing required config: username")

        # URL编码（处理特殊字符）
        username_encoded = urllib.parse.quote(username)
        password_encoded = urllib.parse.quote(password or "")
        database_encoded = urllib.parse.quote(database)

        # 构建基础URL
        if ds_type == DataSourceType.POSTGRESQL:
            url = f"postgresql+psycopg2://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        elif ds_type == DataSourceType.MYSQL:
            url = f"mysql+pymysql://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        elif ds_type == DataSourceType.ORACLE:
            # Oracle支持SID和Service Name两种模式
            mode = config.get("mode", "sid")  # sid or service_name
            if mode == "service_name":
                url = f"oracle+oracledb://{username_encoded}:{password_encoded}@{host}:{port}?service_name={database_encoded}"
            else:
                url = f"oracle+oracledb://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        elif ds_type == DataSourceType.SQLSERVER:
            url = f"mssql+pymssql://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        elif ds_type == DataSourceType.CLICKHOUSE:
            url = f"clickhouse+http://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        else:
            raise ConfigurationException(f"Unsupported database type: {ds_type.code}")

        # 添加额外参数（参考SQLBot的extraJdbc）
        extra_params = config.get("extra_params", "")
        if extra_params:
            separator = "&" if "?" in url else "?"
            url += f"{separator}{extra_params}"

        return url

    def _build_connect_args(self) -> Dict[str, Any]:
        """
        构建连接参数

        参考SQLBot对不同数据库的特殊处理
        """
        config = self.metadata.connection_config
        ds_type = self.metadata.type
        connect_args = {}

        timeout = config.get("timeout", 30)

        # PostgreSQL
        if ds_type == DataSourceType.POSTGRESQL:
            connect_args["connect_timeout"] = timeout
            # Schema设置（参考SQLBot的search_path）
            schema = config.get("schema", "public")
            if schema and schema != "public":
                connect_args["options"] = f"-c search_path={schema}"

        # MySQL
        elif ds_type == DataSourceType.MYSQL:
            connect_args["connect_timeout"] = timeout
            # 字符集（推荐utf8mb4）
            charset = config.get("charset", "utf8mb4")
            connect_args["charset"] = charset

        # SQLite
        elif ds_type == DataSourceType.SQLITE:
            # SQLite没有连接超时，但可以设置busy_timeout
            connect_args["timeout"] = timeout

        # ClickHouse
        elif ds_type == DataSourceType.CLICKHOUSE:
            connect_args["connect_timeout"] = timeout

        return connect_args

    def _get_default_port(self) -> int:
        """获取默认端口"""
        port_map = {
            DataSourceType.POSTGRESQL: 5432,
            DataSourceType.MYSQL: 3306,
            DataSourceType.ORACLE: 1521,
            DataSourceType.SQLSERVER: 1433,
            DataSourceType.CLICKHOUSE: 8123,
        }
        return port_map.get(self.metadata.type, 5432)

    # ========== Schema获取 ==========

    def get_tables(self) -> List[TableSchema]:
        """
        获取所有表的Schema

        使用SQLAlchemy Inspector，比SQLBot的方式更简洁
        """
        if not self.is_connected or not self._inspector:
            raise ConnectionException("未连接到数据源")

        try:
            # 获取schema（PostgreSQL等支持多schema）
            config = self.metadata.connection_config
            schema = config.get("schema")

            # 获取表名列表
            table_names = self._inspector.get_table_names(schema=schema)

            tables = []
            for table_name in table_names:
                table_schema = self.get_table_schema(table_name)
                if table_schema:
                    tables.append(table_schema)
                    # 缓存
                    self._tables_cache[table_name] = table_schema

            return tables

        except Exception as e:
            logger.error(f"Failed to get tables: {e}")
            raise SchemaException(f"获取表列表失败: {str(e)}")

    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """
        获取单个表的Schema

        使用Inspector API，自动处理跨数据库差异
        """
        # 检查缓存
        if table_name in self._tables_cache:
            return self._tables_cache[table_name]

        if not self.is_connected or not self._inspector:
            raise ConnectionException("未连接到数据源")

        try:
            config = self.metadata.connection_config
            schema = config.get("schema")

            # 检查表是否存在
            if not self._inspector.has_table(table_name, schema=schema):
                logger.warning(f"Table not found: {table_name}")
                return None

            # 获取列信息
            columns_info = self._inspector.get_columns(table_name, schema=schema)
            columns = []

            for col_info in columns_info:
                col_name = col_info["name"]
                col_type_native = str(col_info["type"])
                col_nullable = col_info.get("nullable", True)

                # 转换为标准类型
                col_type = ColumnType.from_native_type(col_type_native, self.metadata.type)

                # 获取样本值和统计（可选，用于RAG）
                sample_values = self._get_column_samples(table_name, col_name, schema)
                stats = self._get_column_stats(table_name, col_name, col_type, schema)

                column = ColumnSchema(
                    name=col_name,
                    data_type=col_type,
                    native_type=col_type_native,
                    nullable=col_nullable,
                    comment=col_info.get("comment"),  # 表注释（如果数据库支持）
                    sample_values=sample_values,
                    **stats
                )
                columns.append(column)

            # 获取主键信息
            pk_constraint = self._inspector.get_pk_constraint(table_name, schema=schema)
            pk_columns = pk_constraint.get("constrained_columns", [])
            for col in columns:
                if col.name in pk_columns:
                    col.primary_key = True

            # 获取唯一约束（可选）
            # unique_constraints = self._inspector.get_unique_constraints(table_name, schema=schema)

            # 获取外键（可选，用于JOIN推荐）
            foreign_keys = self._inspector.get_foreign_keys(table_name, schema=schema)
            fk_list = []
            for fk in foreign_keys:
                fk_list.append({
                    "constrained_columns": fk.get("constrained_columns"),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns"),
                })

            # 获取表注释（如果支持）
            table_comment = None
            try:
                table_comment = self._inspector.get_table_comment(table_name, schema=schema)
                table_comment = table_comment.get("text") if table_comment else None
            except NotImplementedError:
                pass  # 某些数据库不支持表注释

            # 获取行数（可选）
            row_count = self.get_table_row_count(table_name)

            table_schema = TableSchema(
                name=table_name,
                columns=columns,
                comment=table_comment,
                row_count=row_count,
                foreign_keys=fk_list,
            )

            # 缓存
            self._tables_cache[table_name] = table_schema

            return table_schema

        except Exception as e:
            logger.error(f"Failed to get schema for table {table_name}: {e}")
            return None

    def _get_column_samples(self, table_name: str, column_name: str,
                           schema: Optional[str] = None, limit: int = 5) -> List[Any]:
        """获取列的样本值（用于LLM理解数据）"""
        try:
            # 使用引号包裹标识符（处理关键字和特殊字符）
            quoted_table = self.metadata.type.quote_identifier(table_name)
            quoted_column = self.metadata.type.quote_identifier(column_name)

            query = f"""
                SELECT DISTINCT {quoted_column}
                FROM {quoted_table}
                WHERE {quoted_column} IS NOT NULL
                LIMIT {limit}
            """

            result = self.execute_query(query, limit=limit)
            if result.success and result.data:
                return [row[column_name] for row in result.data]
            return []
        except Exception:
            return []

    def _get_column_stats(self, table_name: str, column_name: str,
                         col_type: ColumnType, schema: Optional[str] = None) -> Dict[str, Any]:
        """获取列的统计信息"""
        stats = {}

        try:
            quoted_table = self.metadata.type.quote_identifier(table_name)
            quoted_column = self.metadata.type.quote_identifier(column_name)

            # 基础统计
            query = f"""
                SELECT
                    COUNT(DISTINCT {quoted_column}) as distinct_count,
                    COUNT(*) - COUNT({quoted_column}) as null_count
                FROM {quoted_table}
            """
            result = self.execute_query(query)
            if result.success and result.data:
                stats["distinct_count"] = result.data[0].get("distinct_count", 0)
                stats["null_count"] = result.data[0].get("null_count", 0)

            # 数值统计
            if col_type in [ColumnType.INTEGER, ColumnType.BIGINT, ColumnType.FLOAT,
                          ColumnType.DOUBLE, ColumnType.DECIMAL]:
                query = f"""
                    SELECT
                        MIN({quoted_column}) as min_val,
                        MAX({quoted_column}) as max_val,
                        AVG({quoted_column}) as avg_val
                    FROM {quoted_table}
                    WHERE {quoted_column} IS NOT NULL
                """
                result = self.execute_query(query)
                if result.success and result.data:
                    data = result.data[0]
                    stats["min_value"] = float(data["min_val"]) if data.get("min_val") is not None else None
                    stats["max_value"] = float(data["max_val"]) if data.get("max_val") is not None else None
                    stats["avg_value"] = float(data["avg_val"]) if data.get("avg_val") is not None else None

        except Exception as e:
            logger.warning(f"Failed to get stats for {table_name}.{column_name}: {e}")

        return stats

    # ========== 查询执行 ==========

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """
        执行SQL查询

        参考SQLBot的exec_sql，但改进：
        1. 统一使用参数化查询（防止注入）
        2. 更好的错误处理
        3. 执行时间统计
        """
        if not self.is_connected or not self.engine:
            raise ConnectionException("未连接到数据源")

        start_time = time.time()

        try:
            # 添加LIMIT限制（安全措施，参考SQLBot的GENERATE_SQL_QUERY_LIMIT）
            if limit and "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"

            # 使用事务上下文，确保 DDL/DML 在需要时能提交（尤其是 SQLite）
            with self.engine.begin() as conn:
                # 执行查询
                if params:
                    result = conn.execute(text(query), params)
                else:
                    result = conn.execute(text(query))

                # DDL / DML 语句可能不返回 rows（result.returns_rows=False）
                if getattr(result, "returns_rows", False):
                    columns = list(result.keys())
                    rows = result.fetchall()
                    data = [dict(zip(columns, row)) for row in rows]
                else:
                    columns = []
                    data = []

            execution_time = (time.time() - start_time) * 1000  # 毫秒

            return QueryResult(
                success=True,
                data=data,
                columns=columns,
                row_count=len(data),
                execution_time_ms=execution_time,
                query_text=query,
            )

        except OperationalError as e:
            # 连接错误
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Query operational error: {e}\nQuery: {query}")

            return QueryResult(
                success=False,
                error_message=f"数据库操作错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=query,
            )

        except SQLAlchemyError as e:
            # SQL错误
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Query SQL error: {e}\nQuery: {query}")

            return QueryResult(
                success=False,
                error_message=f"SQL执行错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=query,
            )

        except Exception as e:
            # 其他错误
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Query unexpected error: {e}\nQuery: {query}")

            return QueryResult(
                success=False,
                error_message=f"未知错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=query,
            )

    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """构建样本数据查询（处理数据库差异）"""
        quoted_table = self.metadata.type.quote_identifier(table_name)

        # SQL Server使用TOP语法
        if self.metadata.type == DataSourceType.SQLSERVER:
            return f'SELECT TOP {limit} * FROM {quoted_table}'
        # Oracle使用ROWNUM
        elif self.metadata.type == DataSourceType.ORACLE:
            return f'SELECT * FROM {quoted_table} WHERE ROWNUM <= {limit}'
        # 其他数据库使用LIMIT
        else:
            return f'SELECT * FROM {quoted_table} LIMIT {limit}'

    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询"""
        quoted_table = self.metadata.type.quote_identifier(table_name)
        return f'SELECT COUNT(*) as count FROM {quoted_table}'
