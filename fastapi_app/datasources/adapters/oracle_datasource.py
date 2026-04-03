"""
Oracle数据源适配器

支持特性：
1. 双模式连接 - Thick模式（需要Oracle Client）和Thin模式（纯Python）
2. SID和Service Name两种连接方式
3. Oracle特有数据类型支持（NUMBER, CLOB, BLOB等）
4. 大对象处理

参考SQLBot实现：
- oracledb.init_oracle_client() for thick mode
- service_name vs SID mode selection
"""

import os
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import time

try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except ImportError:
    ORACLEDB_AVAILABLE = False

from sqlalchemy import create_engine, text, inspect, MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool
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

# Oracle Client初始化状态
_oracle_client_initialized = False
_oracle_client_mode = "thin"  # thin or thick


def init_oracle_client(lib_dir: Optional[str] = None):
    """
    初始化Oracle Client（Thick模式）
    
    参考SQLBot的初始化逻辑：
    - 如果找到Oracle Client路径，使用Thick模式
    - 否则使用Thin模式（oracledb默认）
    """
    global _oracle_client_initialized, _oracle_client_mode
    
    if _oracle_client_initialized:
        return _oracle_client_mode
    
    if not ORACLEDB_AVAILABLE:
        logger.warning("oracledb package not installed, Oracle support disabled")
        return None
    
    # 尝试从环境变量获取Oracle Client路径
    if not lib_dir:
        lib_dir = os.environ.get("ORACLE_CLIENT_PATH")
    
    if lib_dir and os.path.exists(lib_dir):
        try:
            oracledb.init_oracle_client(lib_dir=lib_dir)
            _oracle_client_mode = "thick"
            logger.info(f"Oracle Client initialized in THICK mode: {lib_dir}")
        except Exception as e:
            logger.warning(f"Failed to init Oracle Client, using THIN mode: {e}")
            _oracle_client_mode = "thin"
    else:
        logger.info("Oracle Client path not found, using THIN mode")
        _oracle_client_mode = "thin"
    
    _oracle_client_initialized = True
    return _oracle_client_mode


class OracleDataSource(DataSourceInterface):
    """
    Oracle数据源适配器
    
    连接配置示例：
    ```python
    # SID模式
    metadata = DataSourceMetadata(
        id="oracle_prod",
        name="生产数据库",
        type=DataSourceType.ORACLE,
        connection_config={
            "host": "localhost",
            "port": 1521,
            "database": "ORCL",  # SID
            "username": "system",
            "password": "oracle",
            "mode": "sid",  # sid或service_name
            "schema": "HR",  # 可选，指定默认Schema
            "timeout": 30,
            "pool_size": 5,
            "oracle_client_path": "/opt/oracle/instantclient",  # 可选
        }
    )
    
    # Service Name模式
    metadata = DataSourceMetadata(
        id="oracle_prod",
        name="生产数据库",
        type=DataSourceType.ORACLE,
        connection_config={
            "host": "localhost",
            "port": 1521,
            "database": "orcl.example.com",  # Service Name
            "username": "system",
            "password": "oracle",
            "mode": "service_name",
            "timeout": 30,
        }
    )
    ```
    """
    
    def __init__(self, metadata: DataSourceMetadata):
        super().__init__(metadata)
        self.engine: Optional[Engine] = None
        self._inspector = None
        self._metadata_obj = None
        self._tables_cache: Dict[str, TableSchema] = {}
        self._client_mode = None
        
    def connect(self) -> bool:
        """建立Oracle连接"""
        if not ORACLEDB_AVAILABLE:
            raise ConfigurationException("oracledb package not installed. Install with: pip install oracledb")
        
        try:
            # 初始化Oracle Client
            config = self.metadata.connection_config
            oracle_client_path = config.get("oracle_client_path")
            self._client_mode = init_oracle_client(oracle_client_path)
            
            # 构建连接URL
            db_url = self._build_connection_url()
            connect_args = self._build_connect_args()
            
            pool_size = config.get("pool_size", 5)
            timeout = config.get("timeout", 30)
            
            self.engine = create_engine(
                db_url,
                connect_args=connect_args,
                pool_size=pool_size,
                pool_timeout=timeout,
                pool_pre_ping=True,
                echo=False,
                poolclass=QueuePool,
            )
            
            # 测试连接
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM DUAL"))
            
            # 创建Inspector
            self._inspector = inspect(self.engine)
            self._metadata_obj = MetaData()
            
            self._connected = True
            logger.info(f"Successfully connected to Oracle ({self._client_mode} mode): {self.metadata.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Oracle {self.metadata.name}: {e}")
            raise ConnectionException(f"Oracle连接失败: {str(e)}")
    
    def disconnect(self):
        """断开连接"""
        if self.engine:
            try:
                self.engine.dispose()
                self._connected = False
                self._inspector = None
                self._metadata_obj = None
                logger.info(f"Disconnected from Oracle: {self.metadata.name}")
            except Exception as e:
                logger.warning(f"Error disconnecting Oracle: {e}")
    
    def test_connection(self) -> bool:
        """测试连接"""
        if not self.engine:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM DUAL"))
            return True
        except Exception as e:
            logger.error(f"Oracle connection test failed: {e}")
            return False
    
    def _build_connection_url(self) -> str:
        """
        构建Oracle连接URL
        
        支持两种模式：
        1. SID模式：oracle+oracledb://user:pass@host:port/SID
        2. Service Name模式：oracle+oracledb://user:pass@host:port?service_name=name
        """
        config = self.metadata.connection_config
        
        host = config.get("host", "localhost")
        port = config.get("port", 1521)
        database = config.get("database")
        username = config.get("username")
        password = config.get("password", "")
        mode = config.get("mode", "sid")
        
        if not database:
            raise ConfigurationException("Missing required config: database (SID or Service Name)")
        if not username:
            raise ConfigurationException("Missing required config: username")
        
        # URL编码
        username_encoded = urllib.parse.quote(username)
        password_encoded = urllib.parse.quote(password)
        database_encoded = urllib.parse.quote(database)
        
        # 根据模式构建URL
        if mode == "service_name":
            url = f"oracle+oracledb://{username_encoded}:{password_encoded}@{host}:{port}?service_name={database_encoded}"
        else:
            # SID模式（默认）
            url = f"oracle+oracledb://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        
        # 添加额外参数
        extra_params = config.get("extra_params", "")
        if extra_params:
            separator = "&" if "?" in url else "?"
            url += f"{separator}{extra_params}"
        
        return url
    
    def _build_connect_args(self) -> Dict[str, Any]:
        """构建连接参数"""
        config = self.metadata.connection_config
        connect_args = {}
        
        # Oracle特有参数
        # 设置默认Schema
        schema = config.get("schema")
        if schema:
            connect_args["current_schema"] = schema
        
        return connect_args
    
    # ========== Schema获取 ==========
    
    def get_tables(self) -> List[TableSchema]:
        """获取所有表"""
        if not self.is_connected or not self._inspector:
            raise ConnectionException("未连接到数据源")
        
        try:
            config = self.metadata.connection_config
            schema = config.get("schema")
            
            # 如果指定了Schema，只获取该Schema的表
            # 否则获取用户可见的所有表
            if schema:
                table_names = self._inspector.get_table_names(schema=schema)
            else:
                # 获取当前用户的表
                query = """
                    SELECT table_name 
                    FROM user_tables 
                    ORDER BY table_name
                """
                result = self.execute_query(query)
                table_names = [row.get("table_name") for row in result.data] if result.success else []
            
            tables = []
            for table_name in table_names:
                table_schema = self.get_table_schema(table_name)
                if table_schema:
                    tables.append(table_schema)
                    self._tables_cache[table_name] = table_schema
            
            return tables
            
        except Exception as e:
            logger.error(f"Failed to get Oracle tables: {e}")
            raise SchemaException(f"获取表列表失败: {str(e)}")
    
    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """获取单个表的Schema"""
        if table_name in self._tables_cache:
            return self._tables_cache[table_name]
        
        if not self.is_connected or not self._inspector:
            raise ConnectionException("未连接到数据源")
        
        try:
            config = self.metadata.connection_config
            schema = config.get("schema")
            
            # 检查表是否存在
            if not self._inspector.has_table(table_name, schema=schema):
                # 尝试大写（Oracle默认大写）
                table_name_upper = table_name.upper()
                if not self._inspector.has_table(table_name_upper, schema=schema):
                    return None
                table_name = table_name_upper
            
            # 获取列信息
            columns_info = self._inspector.get_columns(table_name, schema=schema)
            columns = []
            
            for col_info in columns_info:
                col_name = col_info["name"]
                col_type_native = str(col_info["type"])
                col_nullable = col_info.get("nullable", True)
                
                col_type = ColumnType.from_native_type(col_type_native, DataSourceType.ORACLE)
                
                # 获取样本值和统计
                sample_values = self._get_column_samples(table_name, col_name, schema)
                stats = self._get_column_stats(table_name, col_name, col_type, schema)
                
                column = ColumnSchema(
                    name=col_name,
                    data_type=col_type,
                    native_type=col_type_native,
                    nullable=col_nullable,
                    comment=col_info.get("comment"),
                    sample_values=sample_values,
                    **stats
                )
                columns.append(column)
            
            # 获取主键
            pk_constraint = self._inspector.get_pk_constraint(table_name, schema=schema)
            pk_columns = pk_constraint.get("constrained_columns", []) if pk_constraint else []
            for col in columns:
                if col.name in pk_columns:
                    col.primary_key = True
            
            # 获取外键
            foreign_keys = self._inspector.get_foreign_keys(table_name, schema=schema)
            fk_list = []
            for fk in foreign_keys:
                fk_list.append({
                    "constrained_columns": fk.get("constrained_columns"),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns"),
                })
            
            # 获取表注释
            table_comment = None
            try:
                table_comment_result = self._inspector.get_table_comment(table_name, schema=schema)
                table_comment = table_comment_result.get("text") if table_comment_result else None
            except:
                pass
            
            # 获取行数（近似）
            row_count = self.get_table_row_count(table_name)
            
            table_schema = TableSchema(
                name=table_name,
                columns=columns,
                comment=table_comment,
                row_count=row_count,
                foreign_keys=fk_list,
            )
            
            self._tables_cache[table_name] = table_schema
            return table_schema
            
        except Exception as e:
            logger.error(f"Failed to get schema for Oracle table {table_name}: {e}")
            return None
    
    def _get_column_samples(self, table_name: str, column_name: str,
                           schema: Optional[str] = None, limit: int = 5) -> List[Any]:
        """获取列的样本值"""
        try:
            # Oracle使用双引号包裹标识符
            quoted_table = f'"{table_name}"'
            quoted_column = f'"{column_name}"'
            
            query = f"""
                SELECT DISTINCT {quoted_column}
                FROM {quoted_table}
                WHERE {quoted_column} IS NOT NULL
                  AND ROWNUM <= {limit}
            """
            
            result = self.execute_query(query, limit=limit)
            if result.success and result.data:
                return [row.get(column_name) for row in result.data]
            return []
        except Exception:
            return []
    
    def _get_column_stats(self, table_name: str, column_name: str,
                         col_type: ColumnType, schema: Optional[str] = None) -> Dict[str, Any]:
        """获取列的统计信息"""
        stats = {}
        
        try:
            quoted_table = f'"{table_name}"'
            quoted_column = f'"{column_name}"'
            
            # 基础统计
            query = f"""
                SELECT
                    COUNT(DISTINCT {quoted_column}) as distinct_count,
                    SUM(CASE WHEN {quoted_column} IS NULL THEN 1 ELSE 0 END) as null_count
                FROM {quoted_table}
            """
            result = self.execute_query(query)
            if result.success and result.data:
                stats["distinct_count"] = result.data[0].get("distinct_count", 0)
                stats["null_count"] = result.data[0].get("null_count", 0)
            
            # 数值统计
            if col_type in [ColumnType.INTEGER, ColumnType.BIGINT, ColumnType.FLOAT,
                          ColumnType.DOUBLE, ColumnType.DECIMAL]:
                num_query = f"""
                    SELECT
                        MIN({quoted_column}) as min_val,
                        MAX({quoted_column}) as max_val,
                        AVG({quoted_column}) as avg_val
                    FROM {quoted_table}
                    WHERE {quoted_column} IS NOT NULL
                """
                num_result = self.execute_query(num_query)
                if num_result.success and num_result.data:
                    data = num_result.data[0]
                    stats["min_value"] = float(data["min_val"]) if data.get("min_val") is not None else None
                    stats["max_value"] = float(data["max_val"]) if data.get("max_val") is not None else None
                    stats["avg_value"] = float(data["avg_val"]) if data.get("avg_val") is not None else None
                    
        except Exception as e:
            logger.warning(f"Failed to get stats for Oracle {table_name}.{column_name}: {e}")
        
        return stats
    
    # ========== 查询执行 ==========
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """执行SQL查询"""
        if not self.is_connected or not self.engine:
            raise ConnectionException("未连接到数据源")
        
        start_time = time.time()
        
        try:
            # Oracle使用ROWNUM限制行数
            if limit and "ROWNUM" not in query.upper() and "FETCH" not in query.upper():
                # 包装查询以添加ROWNUM限制
                query = f"SELECT * FROM ({query.rstrip(';')}) WHERE ROWNUM <= {limit}"
            
            with self.engine.connect() as conn:
                if params:
                    result = conn.execute(text(query), params)
                else:
                    result = conn.execute(text(query))
                
                columns = list(result.keys())
                rows = result.fetchall()
                data = [dict(zip(columns, row)) for row in rows]
            
            execution_time = (time.time() - start_time) * 1000
            
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
            logger.error(f"Oracle query error: {e}\nQuery: {query}")
            
            return QueryResult(
                success=False,
                error_message=f"Oracle查询错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=query,
            )
    
    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """构建样本数据查询"""
        return f'SELECT * FROM "{table_name}" WHERE ROWNUM <= {limit}'
    
    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询"""
        return f'SELECT COUNT(*) as count FROM "{table_name}"'
    
    # ========== Oracle特有功能 ==========
    
    def get_all_schemas(self) -> List[str]:
        """获取所有Schema（用户）"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        query = """
            SELECT username 
            FROM all_users 
            ORDER BY username
        """
        result = self.execute_query(query)
        if result.success:
            return [row.get("username") for row in result.data]
        return []
    
    def get_tablespaces(self) -> List[Dict[str, Any]]:
        """获取表空间信息"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        query = """
            SELECT 
                tablespace_name,
                status,
                contents,
                extent_management
            FROM user_tablespaces
            ORDER BY tablespace_name
        """
        result = self.execute_query(query)
        if result.success:
            return result.data
        return []
    
    @property
    def client_mode(self) -> str:
        """获取当前Oracle客户端模式（thin/thick）"""
        return self._client_mode or "unknown"




