"""
Elasticsearch数据源适配器

支持特性：
1. REST API连接 - 支持HTTP/HTTPS
2. SQL查询 - 使用Elasticsearch SQL API
3. 索引管理 - 获取索引信息和映射
4. 全文搜索 - 支持DSL查询

参考SQLBot实现：es_engine.py
"""

import json
import urllib.parse
from base64 import b64encode
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import logging
import time

import requests
from requests.auth import HTTPBasicAuth

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

# 可选：尝试导入elasticsearch库
try:
    from elasticsearch import Elasticsearch
    ES_CLIENT_AVAILABLE = True
except ImportError:
    ES_CLIENT_AVAILABLE = False
    logger.info("elasticsearch package not installed, using HTTP API only")


class ElasticsearchDataSource(DataSourceInterface):
    """
    Elasticsearch数据源适配器
    
    连接配置示例：
    ```python
    metadata = DataSourceMetadata(
        id="es_logs",
        name="日志搜索",
        type=DataSourceType.ELASTICSEARCH,
        connection_config={
            "host": "http://localhost:9200",  # 完整URL，包含协议
            "username": "elastic",
            "password": "changeme",
            "timeout": 30,
            "verify_certs": False,  # 是否验证SSL证书
            "ca_certs": "/path/to/ca.crt",  # CA证书路径（可选）
        }
    )
    ```
    
    查询方式：
    1. SQL查询（推荐）- 使用Elasticsearch SQL API
    2. DSL查询 - 直接使用Elasticsearch Query DSL
    """
    
    def __init__(self, metadata: DataSourceMetadata):
        super().__init__(metadata)
        self._es_client: Optional[Any] = None  # Elasticsearch client
        self._http_session: Optional[requests.Session] = None
        self._tables_cache: Dict[str, TableSchema] = {}
        
    def connect(self) -> bool:
        """建立Elasticsearch连接"""
        try:
            config = self.metadata.connection_config
            
            # 初始化HTTP session（用于SQL查询）
            self._http_session = requests.Session()
            self._http_session.verify = config.get("verify_certs", False)
            
            if config.get("ca_certs"):
                self._http_session.verify = config.get("ca_certs")
            
            # 设置认证
            username = config.get("username")
            password = config.get("password", "")
            if username:
                self._http_session.auth = HTTPBasicAuth(username, password)
                self._http_session.headers.update(self._get_auth_headers())
            
            # 尝试初始化Elasticsearch客户端（如果可用）
            if ES_CLIENT_AVAILABLE:
                self._es_client = Elasticsearch(
                    [config.get("host", "http://localhost:9200")],
                    basic_auth=(username, password) if username else None,
                    verify_certs=config.get("verify_certs", False),
                    ca_certs=config.get("ca_certs"),
                    headers=self._get_auth_headers() if username else None,
                )
            
            # 测试连接
            if not self.test_connection():
                raise ConnectionException("Elasticsearch连接测试失败")
            
            self._connected = True
            logger.info(f"Successfully connected to Elasticsearch: {self.metadata.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch {self.metadata.name}: {e}")
            raise ConnectionException(f"Elasticsearch连接失败: {str(e)}")
    
    def disconnect(self):
        """断开连接"""
        try:
            if self._http_session:
                self._http_session.close()
                self._http_session = None
            
            if self._es_client:
                self._es_client.close()
                self._es_client = None
            
            self._connected = False
            logger.info(f"Disconnected from Elasticsearch: {self.metadata.name}")
        except Exception as e:
            logger.warning(f"Error disconnecting Elasticsearch: {e}")
    
    def test_connection(self) -> bool:
        """测试连接"""
        try:
            config = self.metadata.connection_config
            host = config.get("host", "http://localhost:9200")
            
            # 使用HTTP API测试
            response = self._http_session.get(f"{host.rstrip('/')}/_cluster/health")
            if response.status_code == 200:
                return True
            
            # 如果有ES客户端，也尝试ping
            if self._es_client and self._es_client.ping():
                return True
            
            return False
        except Exception as e:
            logger.error(f"Elasticsearch connection test failed: {e}")
            return False
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """获取认证头"""
        config = self.metadata.connection_config
        username = config.get("username", "")
        password = config.get("password", "")
        
        credentials = f"{username}:{password}"
        encoded_credentials = b64encode(credentials.encode()).decode()
        
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded_credentials}"
        }
    
    def _get_base_url(self) -> str:
        """获取基础URL"""
        config = self.metadata.connection_config
        host = config.get("host", "http://localhost:9200")
        return host.rstrip('/')
    
    # ========== Schema获取 ==========
    
    def get_tables(self) -> List[TableSchema]:
        """获取所有索引（作为表）"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            base_url = self._get_base_url()
            
            # 获取所有索引
            response = self._http_session.get(f"{base_url}/_cat/indices?format=json")
            
            if response.status_code != 200:
                raise SchemaException(f"获取索引列表失败: {response.text}")
            
            indices = response.json()
            
            tables = []
            for idx in indices:
                index_name = idx.get("index", "")
                
                # 跳过系统索引（以.开头）
                if index_name.startswith("."):
                    continue
                
                table_schema = self.get_table_schema(index_name)
                if table_schema:
                    # 添加额外的索引信息
                    table_schema.row_count = int(idx.get("docs.count", 0) or 0)
                    size_str = idx.get("store.size", "0b")
                    table_schema.size_bytes = self._parse_size(size_str)
                    
                    tables.append(table_schema)
                    self._tables_cache[index_name] = table_schema
            
            return tables
            
        except Exception as e:
            logger.error(f"Failed to get Elasticsearch indices: {e}")
            raise SchemaException(f"获取索引列表失败: {str(e)}")
    
    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """获取单个索引的Schema（映射）"""
        if table_name in self._tables_cache:
            return self._tables_cache[table_name]
        
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            base_url = self._get_base_url()
            
            # 获取映射
            response = self._http_session.get(f"{base_url}/{table_name}/_mapping")
            
            if response.status_code != 200:
                logger.warning(f"Index not found: {table_name}")
                return None
            
            mapping = response.json()
            mappings = mapping.get(table_name, {}).get("mappings", {})
            properties = mappings.get("properties", {})
            
            # 获取索引描述（从_meta字段）
            index_comment = None
            if mappings.get("_meta"):
                index_comment = mappings.get("_meta", {}).get("description")
            
            columns = []
            for field_name, field_config in properties.items():
                field_type = field_config.get("type")
                field_comment = None
                
                if field_config.get("_meta"):
                    field_comment = field_config.get("_meta", {}).get("description")
                
                # 处理没有显式type的字段（object/nested）
                if not field_type:
                    field_type = "object" if "properties" in field_config else "unknown"
                
                col_type = self._map_es_type(field_type)
                
                column = ColumnSchema(
                    name=field_name,
                    data_type=col_type,
                    native_type=field_type,
                    nullable=True,  # ES字段都可为空
                    comment=field_comment,
                )
                columns.append(column)
            
            table_schema = TableSchema(
                name=table_name,
                columns=columns,
                comment=index_comment,
            )
            
            self._tables_cache[table_name] = table_schema
            return table_schema
            
        except Exception as e:
            logger.error(f"Failed to get schema for Elasticsearch index {table_name}: {e}")
            return None
    
    def _map_es_type(self, es_type: str) -> ColumnType:
        """映射Elasticsearch类型到标准类型"""
        type_mapping = {
            # 数值类型
            "long": ColumnType.BIGINT,
            "integer": ColumnType.INTEGER,
            "short": ColumnType.INTEGER,
            "byte": ColumnType.INTEGER,
            "double": ColumnType.DOUBLE,
            "float": ColumnType.FLOAT,
            "half_float": ColumnType.FLOAT,
            "scaled_float": ColumnType.DECIMAL,
            
            # 字符串类型
            "keyword": ColumnType.VARCHAR,
            "text": ColumnType.TEXT,
            "constant_keyword": ColumnType.VARCHAR,
            "wildcard": ColumnType.TEXT,
            
            # 日期类型
            "date": ColumnType.DATETIME,
            "date_nanos": ColumnType.TIMESTAMP,
            
            # 布尔类型
            "boolean": ColumnType.BOOLEAN,
            
            # 复杂类型
            "object": ColumnType.JSON,
            "nested": ColumnType.JSON,
            "flattened": ColumnType.JSON,
            
            # 地理类型（映射为JSON）
            "geo_point": ColumnType.JSON,
            "geo_shape": ColumnType.JSON,
            
            # 二进制
            "binary": ColumnType.BLOB,
        }
        
        return type_mapping.get(es_type, ColumnType.UNKNOWN)
    
    def _parse_size(self, size_str: str) -> int:
        """解析大小字符串（如'1.5gb'）为字节数"""
        try:
            size_str = size_str.lower().strip()
            multipliers = {
                'b': 1,
                'kb': 1024,
                'mb': 1024 ** 2,
                'gb': 1024 ** 3,
                'tb': 1024 ** 4,
            }
            
            for suffix, multiplier in multipliers.items():
                if size_str.endswith(suffix):
                    number = float(size_str[:-len(suffix)])
                    return int(number * multiplier)
            
            return int(float(size_str))
        except:
            return 0
    
    # ========== 查询执行 ==========
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """
        执行SQL查询
        
        使用Elasticsearch SQL API（_sql端点）
        """
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        start_time = time.time()
        
        try:
            base_url = self._get_base_url()
            
            # 添加LIMIT限制
            if limit and "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"
            
            # 调用SQL API
            sql_url = f"{base_url}/_sql?format=json"
            payload = {"query": query}
            
            if params:
                payload["params"] = list(params.values())
            
            response = self._http_session.post(sql_url, json=payload)
            
            execution_time = (time.time() - start_time) * 1000
            
            if response.status_code != 200:
                error_data = response.json()
                error_msg = json.dumps(error_data) if isinstance(error_data, dict) else str(error_data)
                
                return QueryResult(
                    success=False,
                    error_message=f"Elasticsearch SQL错误: {error_msg}",
                    execution_time_ms=execution_time,
                    query_text=query,
                )
            
            result = response.json()
            
            # 解析结果
            columns_info = result.get("columns", [])
            columns = [col.get("name") for col in columns_info]
            rows = result.get("rows", [])
            
            # 转换为字典列表
            data = [dict(zip(columns, row)) for row in rows]
            
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
            logger.error(f"Elasticsearch query error: {e}\nQuery: {query}")
            
            return QueryResult(
                success=False,
                error_message=f"Elasticsearch查询错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=query,
            )
    
    def execute_dsl_query(self, index: str, query_dsl: Dict[str, Any],
                         size: int = 100) -> QueryResult:
        """
        执行DSL查询（Elasticsearch原生查询语法）
        
        Args:
            index: 索引名称
            query_dsl: Elasticsearch Query DSL
            size: 返回结果数量
        """
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        start_time = time.time()
        
        try:
            base_url = self._get_base_url()
            
            # 添加size限制
            if "size" not in query_dsl:
                query_dsl["size"] = size
            
            response = self._http_session.post(
                f"{base_url}/{index}/_search",
                json=query_dsl
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            if response.status_code != 200:
                return QueryResult(
                    success=False,
                    error_message=f"Elasticsearch DSL错误: {response.text}",
                    execution_time_ms=execution_time,
                    query_text=json.dumps(query_dsl),
                )
            
            result = response.json()
            hits = result.get("hits", {}).get("hits", [])
            
            # 提取_source数据
            data = []
            for hit in hits:
                doc = hit.get("_source", {})
                doc["_id"] = hit.get("_id")
                doc["_score"] = hit.get("_score")
                data.append(doc)
            
            # 获取列名
            columns = list(data[0].keys()) if data else []
            
            return QueryResult(
                success=True,
                data=data,
                columns=columns,
                row_count=len(data),
                execution_time_ms=execution_time,
                query_text=json.dumps(query_dsl),
                metadata={
                    "total": result.get("hits", {}).get("total", {}).get("value", 0),
                    "max_score": result.get("hits", {}).get("max_score"),
                }
            )
            
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Elasticsearch DSL query error: {e}")
            
            return QueryResult(
                success=False,
                error_message=f"Elasticsearch DSL查询错误: {str(e)}",
                execution_time_ms=execution_time,
                query_text=json.dumps(query_dsl),
            )
    
    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """构建样本数据查询"""
        return f'SELECT * FROM "{table_name}" LIMIT {limit}'
    
    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询"""
        return f'SELECT COUNT(*) as count FROM "{table_name}"'
    
    # ========== Elasticsearch特有功能 ==========
    
    def get_cluster_health(self) -> Dict[str, Any]:
        """获取集群健康状态"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        base_url = self._get_base_url()
        response = self._http_session.get(f"{base_url}/_cluster/health")
        
        if response.status_code == 200:
            return response.json()
        return {}
    
    def get_cluster_stats(self) -> Dict[str, Any]:
        """获取集群统计信息"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        base_url = self._get_base_url()
        response = self._http_session.get(f"{base_url}/_cluster/stats")
        
        if response.status_code == 200:
            return response.json()
        return {}
    
    def refresh_index(self, index: str) -> bool:
        """刷新索引"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            base_url = self._get_base_url()
            response = self._http_session.post(f"{base_url}/{index}/_refresh")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to refresh index {index}: {e}")
            return False




