"""
ClickHouse数据源适配器

支持特性：
1. HTTP协议连接 - 使用clickhouse-driver或HTTP API
2. 分布式表支持 - 自动识别分布式表
3. 大数据量优化 - 流式读取、分页查询
4. ClickHouse特有函数支持

参考SQLBot实现：clickhouse+http:// 连接方式
"""

import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import time

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


class ClickHouseDataSource(DataSourceInterface):
    """
    ClickHouse数据源适配器
    
    连接配置示例：
    ```python
    metadata = DataSourceMetadata(
        id="ch_analytics",
        name="分析数据库",
        type=DataSourceType.CLICKHOUSE,
        connection_config={
            "host": "localhost",
            "port": 8123,  # HTTP端口（默认8123），或9000（TCP端口）
            "database": "default",
            "username": "default",
            "password": "",
            "protocol": "http",  # http或native
            "timeout": 60,
            "pool_size": 5,
            "secure": False,  # 是否使用HTTPS
            "verify": True,  # 是否验证SSL证书
            "extra_params": "compress=1",  # 额外参数
        }
    )
    ```
    
    特殊功能：
    - 支持分布式表查询
    - 支持物化视图
    - 支持近似聚合函数（uniq, quantile等）
    """
    
    def __init__(self, metadata: DataSourceMetadata):
        super().__init__(metadata)
        self.engine: Optional[Engine] = None
        self._inspector = None
        self._metadata_obj = None
        self._tables_cache: Dict[str, TableSchema] = {}
        
    def connect(self) -> bool:
        """建立ClickHouse连接"""
        try:
            db_url = self._build_connection_url()
            connect_args = self._build_connect_args()
            
            config = self.metadata.connection_config
            pool_size = config.get("pool_size", 5)
            timeout = config.get("timeout", 60)
            
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
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
            
            # 创建Inspector
            self._inspector = inspect(self.engine)
            self._metadata_obj = MetaData()
            
            self._connected = True
            logger.info(f"Successfully connected to ClickHouse: {self.metadata.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to ClickHouse {self.metadata.name}: {e}")
            raise ConnectionException(f"ClickHouse连接失败: {str(e)}")
    
    def disconnect(self):
        """断开连接"""
        if self.engine:
            try:
                self.engine.dispose()
                self._connected = False
                self._inspector = None
                self._metadata_obj = None
                logger.info(f"Disconnected from ClickHouse: {self.metadata.name}")
            except Exception as e:
                logger.warning(f"Error disconnecting ClickHouse: {e}")
    
    def test_connection(self) -> bool:
        """测试连接"""
        if not self.engine:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"ClickHouse connection test failed: {e}")
            return False
    
    def _build_connection_url(self) -> str:
        """
        构建ClickHouse连接URL
        
        支持两种协议：
        1. HTTP (clickhouse+http://) - 推荐，更稳定
        2. Native (clickhouse+native://) - 更快，但兼容性稍差
        """
        config = self.metadata.connection_config
        
        host = config.get("host", "localhost")
        port = config.get("port", 8123)
        database = config.get("database", "default")
        username = config.get("username", "default")
        password = config.get("password", "")
        protocol = config.get("protocol", "http")
        secure = config.get("secure", False)
        
        # URL编码
        username_encoded = urllib.parse.quote(username)
        password_encoded = urllib.parse.quote(password)
        database_encoded = urllib.parse.quote(database)
        
        # 根据协议构建URL
        if protocol == "native":
            # Native协议（TCP 9000端口）
            url = f"clickhouse+native://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        else:
            # HTTP协议（HTTP 8123端口）- 默认
            scheme = "https" if secure else "http"
            url = f"clickhouse+{scheme}://{username_encoded}:{password_encoded}@{host}:{port}/{database_encoded}"
        
        # 添加额外参数
        extra_params = config.get("extra_params", "")
        if extra_params:
            url += f"?{extra_params}"
        
        return url
    
    def _build_connect_args(self) -> Dict[str, Any]:
        """构建连接参数"""
        config = self.metadata.connection_config
        connect_args = {}
        
        timeout = config.get("timeout", 60)
        connect_args["connect_timeout"] = timeout
        
        # SSL验证
        if config.get("secure"):
            connect_args["verify"] = config.get("verify", True)
        
        return connect_args
    
    # ========== Schema获取 ==========
    
    def get_tables(self) -> List[TableSchema]:
        """获取所有表（包括分布式表和物化视图）"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            config = self.metadata.connection_config
            database = config.get("database", "default")
            
            # ClickHouse系统表查询
            query = f"""
                SELECT 
                    name,
                    engine,
                    comment
                FROM system.tables
                WHERE database = '{database}'
                  AND engine NOT IN ('View')
                ORDER BY name
            """
            
            result = self.execute_query(query)
            
            tables = []
            if result.success and result.data:
                for row in result.data:
                    table_name = row.get("name")
                    table_schema = self.get_table_schema(table_name)
                    if table_schema:
                        tables.append(table_schema)
                        self._tables_cache[table_name] = table_schema
            
            return tables
            
        except Exception as e:
            logger.error(f"Failed to get ClickHouse tables: {e}")
            raise SchemaException(f"获取表列表失败: {str(e)}")
    
    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """获取单个表的Schema"""
        if table_name in self._tables_cache:
            return self._tables_cache[table_name]
        
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            config = self.metadata.connection_config
            database = config.get("database", "default")
            
            # 获取列信息
            columns_query = f"""
                SELECT 
                    name,
                    type,
                    comment,
                    is_in_primary_key
                FROM system.columns
                WHERE database = '{database}'
                  AND table = '{table_name}'
                ORDER BY position
            """
            
            columns_result = self.execute_query(columns_query)
            
            if not columns_result.success or not columns_result.data:
                return None
            
            columns = []
            for col_info in columns_result.data:
                col_name = col_info.get("name")
                col_type_native = col_info.get("type")
                col_comment = col_info.get("comment", "")
                is_pk = col_info.get("is_in_primary_key", 0) == 1
                
                col_type = ColumnType.from_native_type(col_type_native, DataSourceType.CLICKHOUSE)
                
                # 获取样本值
                sample_values = self._get_column_samples(table_name, col_name)
                stats = self._get_column_stats(table_name, col_name, col_type)
                
                column = ColumnSchema(
                    name=col_name,
                    data_type=col_type,
                    native_type=col_type_native,
                    nullable="Nullable" in col_type_native,
                    primary_key=is_pk,
                    comment=col_comment if col_comment else None,
                    sample_values=sample_values,
                    **stats
                )
                columns.append(column)
            
            # 获取表信息
            table_info_query = f"""
                SELECT 
                    engine,
                    total_rows,
                    total_bytes,
                    comment
                FROM system.tables
                WHERE database = '{database}'
                  AND name = '{table_name}'
            """
            
            table_info_result = self.execute_query(table_info_query)
            
            row_count = None
            size_bytes = None
            table_comment = None
            engine = None
            
            if table_info_result.success and table_info_result.data:
                info = table_info_result.data[0]
                engine = info.get("engine")
                row_count = info.get("total_rows")
                size_bytes = info.get("total_bytes")
                table_comment = info.get("comment")
            
            table_schema = TableSchema(
                name=table_name,
                columns=columns,
                comment=table_comment,
                description=f"Engine: {engine}" if engine else None,
                row_count=row_count,
                size_bytes=size_bytes,
            )
            
            self._tables_cache[table_name] = table_schema
            return table_schema
            
        except Exception as e:
            logger.error(f"Failed to get schema for ClickHouse table {table_name}: {e}")
            return None
    
    def _get_column_samples(self, table_name: str, column_name: str, limit: int = 5) -> List[Any]:
        """获取列的样本值"""
        try:
            query = f"""
                SELECT DISTINCT "{column_name}"
                FROM {table_name}
                WHERE "{column_name}" IS NOT NULL
                LIMIT {limit}
            """
            result = self.execute_query(query, limit=limit)
            if result.success and result.data:
                return [row.get(column_name) for row in result.data]
            return []
        except Exception:
            return []
    
    def _get_column_stats(self, table_name: str, column_name: str, col_type: ColumnType) -> Dict[str, Any]:
        """获取列的统计信息"""
        stats = {}
        try:
            # 基础统计
            query = f"""
                SELECT
                    uniq("{column_name}") as distinct_count,
                    countIf("{column_name}" IS NULL) as null_count
                FROM {table_name}
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
                        min("{column_name}") as min_val,
                        max("{column_name}") as max_val,
                        avg("{column_name}") as avg_val
                    FROM {table_name}
                    WHERE "{column_name}" IS NOT NULL
                """
                num_result = self.execute_query(num_query)
                if num_result.success and num_result.data:
                    data = num_result.data[0]
                    stats["min_value"] = float(data["min_val"]) if data.get("min_val") is not None else None
                    stats["max_value"] = float(data["max_val"]) if data.get("max_val") is not None else None
                    stats["avg_value"] = float(data["avg_val"]) if data.get("avg_val") is not None else None
                    
        except Exception as e:
            logger.warning(f"Failed to get stats for ClickHouse {table_name}.{column_name}: {e}")
        
        return stats
    
    # ========== 查询执行 ==========
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """执行SQL查询"""
        if not self.is_connected or not self.engine:
            raise ConnectionException("未连接到数据源")
        
        start_time = time.time()
        
        try:
            # 添加LIMIT限制
            if limit and "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"
            
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
            logger.error(f"ClickHouse query error: {e}\nQuery: {query}")
            
            return QueryResult(
                success=False,
                error_message=f"ClickHouse查询错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=query,
            )
    
    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """构建样本数据查询"""
        return f'SELECT * FROM {table_name} LIMIT {limit}'
    
    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询"""
        return f'SELECT count(*) as count FROM {table_name}'
    
    # ========== ClickHouse特有功能 ==========
    
    def get_table_partitions(self, table_name: str) -> List[Dict[str, Any]]:
        """获取表的分区信息"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        config = self.metadata.connection_config
        database = config.get("database", "default")
        
        query = f"""
            SELECT 
                partition,
                name,
                rows,
                bytes_on_disk,
                modification_time
            FROM system.parts
            WHERE database = '{database}'
              AND table = '{table_name}'
              AND active = 1
            ORDER BY partition
        """
        
        result = self.execute_query(query)
        if result.success:
            return result.data
        return []
    
    def optimize_table(self, table_name: str, partition: Optional[str] = None) -> bool:
        """优化表（合并分区）"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            if partition:
                query = f"OPTIMIZE TABLE {table_name} PARTITION {partition} FINAL"
            else:
                query = f"OPTIMIZE TABLE {table_name} FINAL"
            
            with self.engine.connect() as conn:
                conn.execute(text(query))
            
            logger.info(f"Optimized ClickHouse table: {table_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to optimize ClickHouse table {table_name}: {e}")
            return False




