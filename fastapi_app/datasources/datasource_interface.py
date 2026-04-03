"""
统一数据源抽象接口

核心设计原则（参考SQLBot精华）：
1. 数据源类型无关 - 所有数据源（SQL/CSV/API）统一接口
2. Schema标准化 - 统一的表/列结构描述
3. 查询语言抽象 - 支持SQL或其他查询DSL
4. 元数据完整性 - 包含类型、注释、统计信息
5. 连接管理 - 连接池、超时、重试机制
6. 错误处理统一 - 标准化异常体系

参考SQLBot的优秀设计：
- apps/db/constant.py: DB枚举设计（类型+前缀+连接方式）
- apps/db/db.py: 统一的exec_sql接口
- apps/db/engine.py: 连接配置和引擎管理
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


# ==================== 数据类型定义 ====================

class DataSourceType(Enum):
    """
    数据源类型枚举
    参考SQLBot的DB枚举设计，但更简化和可扩展
    """
    # SQL数据库
    POSTGRESQL = ("postgresql", "PostgreSQL", '"', '"', "sql")
    MYSQL = ("mysql", "MySQL", "`", "`", "sql")
    SQLITE = ("sqlite", "SQLite", '"', '"', "sql")
    CLICKHOUSE = ("clickhouse", "ClickHouse", '"', '"', "sql")
    ORACLE = ("oracle", "Oracle", '"', '"', "sql")
    SQLSERVER = ("sqlserver", "Microsoft SQL Server", "[", "]", "sql")

    # 文件数据源
    CSV = ("csv", "CSV File", '"', '"', "file")
    EXCEL = ("excel", "Excel File", '"', '"', "file")
    PARQUET = ("parquet", "Parquet File", '"', '"', "file")
    JSON = ("json", "JSON File", '"', '"', "file")

    # API数据源
    REST_API = ("rest_api", "REST API", "", "", "api")
    GRAPHQL = ("graphql", "GraphQL API", "", "", "api")

    # 未来扩展：文档/搜索引擎
    ELASTICSEARCH = ("elasticsearch", "Elasticsearch", '"', '"', "search")

    def __init__(self, code: str, display_name: str,
                 identifier_quote_left: str, identifier_quote_right: str,
                 category: str):
        self.code = code
        self.display_name = display_name
        self.identifier_quote_left = identifier_quote_left  # 标识符左引号
        self.identifier_quote_right = identifier_quote_right  # 标识符右引号
        self.category = category  # sql/file/api/search

    def quote_identifier(self, identifier: str) -> str:
        """给表名/列名加引号（处理特殊字符/关键字）"""
        return f"{self.identifier_quote_left}{identifier}{self.identifier_quote_right}"

    @classmethod
    def from_code(cls, code: str) -> 'DataSourceType':
        """根据代码获取枚举"""
        for ds_type in cls:
            if ds_type.code == code.lower():
                return ds_type
        raise ValueError(f"Unknown datasource type: {code}")


class ColumnType(Enum):
    """
    列数据类型枚举（标准化）
    参考SQLBot对不同数据库类型的统一处理
    """
    # 数值类型
    INTEGER = "integer"
    BIGINT = "bigint"
    FLOAT = "float"
    DOUBLE = "double"
    DECIMAL = "decimal"

    # 字符串类型
    VARCHAR = "varchar"
    TEXT = "text"
    CHAR = "char"

    # 日期时间类型
    DATE = "date"
    DATETIME = "datetime"
    TIMESTAMP = "timestamp"
    TIME = "time"

    # 布尔类型
    BOOLEAN = "boolean"

    # JSON类型
    JSON = "json"
    JSONB = "jsonb"

    # 其他
    BLOB = "blob"
    UNKNOWN = "unknown"

    @classmethod
    def from_native_type(cls, native_type: str, datasource_type: DataSourceType) -> 'ColumnType':
        """
        从原生类型转换为标准类型
        参考SQLBot处理不同数据库类型差异的方式
        """
        native_lower = native_type.lower()

        # 整数类型映射
        if any(t in native_lower for t in ['int', 'integer', 'serial', 'int64']):
            if 'big' in native_lower:
                return cls.BIGINT
            return cls.INTEGER

        # 浮点类型映射
        if any(t in native_lower for t in ['float', 'real', 'double', 'numeric']):
            if 'decimal' in native_lower or 'numeric' in native_lower:
                return cls.DECIMAL
            if 'double' in native_lower:
                return cls.DOUBLE
            return cls.FLOAT

        # 字符串类型映射
        if any(t in native_lower for t in ['char', 'varchar', 'text', 'string', 'object']):
            if 'text' in native_lower or len(native_lower) > 20:
                return cls.TEXT
            return cls.VARCHAR

        # 日期时间类型映射
        if 'date' in native_lower:
            if 'time' in native_lower:
                return cls.DATETIME
            return cls.DATE
        if 'timestamp' in native_lower:
            return cls.TIMESTAMP
        if 'time' in native_lower:
            return cls.TIME

        # 布尔类型
        if any(t in native_lower for t in ['bool', 'boolean']):
            return cls.BOOLEAN

        # JSON类型
        if 'json' in native_lower:
            if 'jsonb' in native_lower:
                return cls.JSONB
            return cls.JSON

        # 二进制类型
        if any(t in native_lower for t in ['blob', 'binary', 'bytea']):
            return cls.BLOB

        return cls.UNKNOWN


@dataclass
class ColumnSchema:
    """
    列Schema定义
    参考SQLBot的CoreField模型，但更简化和通用
    """
    name: str  # 列名
    data_type: ColumnType  # 标准化类型
    native_type: str  # 原生类型（如MySQL的VARCHAR(255)）

    # 约束和属性
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False

    # 业务属性（参考SQLBot的custom_comment）
    comment: Optional[str] = None  # 原始注释
    display_name: Optional[str] = None  # 展示名称（业务名称）
    description: Optional[str] = None  # 详细描述

    # 统计信息（用于Schema检索和LLM理解）
    sample_values: List[Any] = field(default_factory=list)  # 示例值
    distinct_count: Optional[int] = None  # 唯一值数量
    null_count: Optional[int] = None  # 空值数量

    # 数值统计（仅数值类型）
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    avg_value: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        # 转换 sample_values 为字符串以避免日期序列化问题
        sample_values = [str(v) if v is not None else None for v in (self.sample_values[:3] if self.sample_values else [])]

        return {
            "name": self.name,
            "data_type": self.data_type.value,
            "native_type": self.native_type,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
            "unique": self.unique,
            "comment": self.comment,
            "display_name": self.display_name or self.name,
            "description": self.description,
            "sample_values": sample_values,
            "distinct_count": self.distinct_count,
            "null_count": self.null_count,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "avg_value": self.avg_value,
        }

    def to_llm_description(self) -> str:
        """
        生成适合LLM理解的描述
        参考SQLBot的M-Schema格式
        """
        desc_parts = [f'"{self.name}" ({self.data_type.value})']

        if self.display_name and self.display_name != self.name:
            desc_parts.append(f"[{self.display_name}]")

        if self.description:
            desc_parts.append(f"- {self.description}")
        elif self.comment:
            desc_parts.append(f"- {self.comment}")

        if self.sample_values:
            examples = ', '.join(str(v) for v in self.sample_values[:3])
            desc_parts.append(f"(例: {examples})")

        if self.primary_key:
            desc_parts.append("[主键]")

        return ' '.join(desc_parts)


@dataclass
class TableSchema:
    """
    表Schema定义
    参考SQLBot的CoreTable模型
    """
    name: str  # 表名
    columns: List[ColumnSchema]  # 列列表

    # 业务属性
    display_name: Optional[str] = None  # 展示名称
    comment: Optional[str] = None  # 表注释
    description: Optional[str] = None  # 详细描述

    # 统计信息
    row_count: Optional[int] = None  # 行数
    size_bytes: Optional[int] = None  # 大小（字节）

    # 索引信息（可选）
    indexes: List[str] = field(default_factory=list)

    # 关系信息（可选，用于JOIN提示）
    foreign_keys: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "comment": self.comment,
            "description": self.description,
            "row_count": self.row_count,
            "columns": [col.to_dict() for col in self.columns],
            "indexes": self.indexes,
            "foreign_keys": self.foreign_keys,
        }

    def to_llm_description(self) -> str:
        """
        生成适合LLM理解的描述（M-Schema格式）
        参考SQLBot的table schema格式
        """
        lines = [f"表: {self.name}"]

        if self.display_name and self.display_name != self.name:
            lines.append(f"  业务名称: {self.display_name}")

        if self.description:
            lines.append(f"  描述: {self.description}")
        elif self.comment:
            lines.append(f"  描述: {self.comment}")

        if self.row_count:
            lines.append(f"  行数: {self.row_count:,}")

        lines.append("  列:")
        for col in self.columns:
            lines.append(f"    - {col.to_llm_description()}")

        return '\n'.join(lines)

    def get_column(self, name: str) -> Optional[ColumnSchema]:
        """根据列名获取列Schema"""
        for col in self.columns:
            if col.name.lower() == name.lower():
                return col
        return None


@dataclass
class DataSourceMetadata:
    """
    数据源元数据
    参考SQLBot的CoreDatasource模型
    """
    id: str  # 数据源唯一ID
    name: str  # 数据源名称
    type: DataSourceType  # 数据源类型

    # 连接信息（实现类负责加密存储）
    connection_config: Dict[str, Any]  # 连接配置（敏感信息）

    # 业务属性
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # 状态
    status: str = "active"  # active/inactive/error
    last_sync_time: Optional[datetime] = None

    # 统计信息
    table_count: Optional[int] = None
    total_size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不包含敏感信息）"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.code,
            "type_display": self.type.display_name,
            "description": self.description,
            "tags": self.tags,
            "status": self.status,
            "last_sync_time": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "table_count": self.table_count,
            "total_size_bytes": self.total_size_bytes,
        }


@dataclass
class QueryResult:
    """
    查询结果
    统一的查询结果格式
    """
    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)  # 结果数据
    columns: List[str] = field(default_factory=list)  # 列名列表
    row_count: int = 0  # 返回行数
    execution_time_ms: float = 0.0  # 执行时间（毫秒）
    error_message: Optional[str] = None  # 错误信息

    # 额外信息
    query_text: Optional[str] = None  # 原始查询文本
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "columns": self.columns,
            "row_count": self.row_count,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "query_text": self.query_text,
            "metadata": self.metadata,
        }


# ==================== 核心接口 ====================

class DataSourceInterface(ABC):
    """
    统一数据源接口

    设计原则：
    1. 接口最小化 - 只定义必须的方法
    2. 类型安全 - 使用明确的类型定义
    3. 异常统一 - 使用标准异常类
    4. 可测试性 - 便于Mock和单元测试
    5. 可扩展性 - 预留扩展点

    参考SQLBot的优秀实践：
    - check_connection: 连接检查
    - get_tables/get_fields: Schema获取
    - exec_sql: 统一查询接口
    """

    def __init__(self, metadata: DataSourceMetadata):
        self.metadata = metadata
        self._connected = False

    # ========== 连接管理 ==========

    @abstractmethod
    def connect(self) -> bool:
        """
        建立连接
        参考SQLBot的check_connection设计

        Returns:
            bool: 连接是否成功
        """
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        测试连接
        参考SQLBot的check_status

        Returns:
            bool: 连接是否可用
        """
        pass

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    # ========== Schema获取 ==========

    @abstractmethod
    def get_tables(self) -> List[TableSchema]:
        """
        获取所有表的Schema
        参考SQLBot的get_tables

        Returns:
            List[TableSchema]: 表Schema列表
        """
        pass

    @abstractmethod
    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """
        获取单个表的Schema
        参考SQLBot的get_table_schema

        Args:
            table_name: 表名

        Returns:
            Optional[TableSchema]: 表Schema，不存在返回None
        """
        pass

    def get_all_schemas_text(self, format: str = "llm") -> str:
        """
        获取所有Schema的文本描述
        用于传递给LLM或保存

        Args:
            format: 格式类型 ("llm", "json", "markdown")

        Returns:
            str: Schema文本
        """
        tables = self.get_tables()

        if format == "llm":
            # M-Schema格式（参考SQLBot）
            return "\n\n".join(table.to_llm_description() for table in tables)
        elif format == "json":
            import json
            return json.dumps([t.to_dict() for t in tables], ensure_ascii=False, indent=2, default=str)
        elif format == "markdown":
            lines = [f"# {self.metadata.name}\n"]
            for table in tables:
                lines.append(f"## {table.name}\n")
                lines.append(f"{table.description or table.comment or ''}\n")
                lines.append("| 列名 | 类型 | 描述 |")
                lines.append("|------|------|------|")
                for col in table.columns:
                    desc = col.description or col.comment or ""
                    lines.append(f"| {col.name} | {col.data_type.value} | {desc} |")
                lines.append("")
            return '\n'.join(lines)
        else:
            raise ValueError(f"Unsupported format: {format}")

    # ========== 数据查询 ==========

    @abstractmethod
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """
        执行查询
        参考SQLBot的exec_sql设计

        Args:
            query: 查询语句（SQL或其他DSL）
            params: 查询参数（用于参数化查询，防止注入）
            limit: 结果限制（强制限制，防止OOM）

        Returns:
            QueryResult: 查询结果
        """
        pass

    def get_sample_data(self, table_name: str, limit: int = 10) -> QueryResult:
        """
        获取表的样本数据
        参考SQLBot的preview功能

        Args:
            table_name: 表名
            limit: 样本数量

        Returns:
            QueryResult: 样本数据
        """
        # 默认实现（子类可覆盖优化）
        query = self._build_sample_query(table_name, limit)
        return self.execute_query(query, limit=limit)

    @abstractmethod
    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """
        构建样本数据查询语句
        不同数据源有不同的实现
        """
        pass

    # ========== 数据统计 ==========

    def get_table_row_count(self, table_name: str) -> int:
        """
        获取表行数

        Args:
            table_name: 表名

        Returns:
            int: 行数
        """
        # 默认实现（子类可覆盖优化）
        query = self._build_count_query(table_name)
        result = self.execute_query(query)
        if result.success and result.data:
            return result.data[0].get('count', 0)
        return 0

    @abstractmethod
    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询语句"""
        pass

    # ========== 辅助方法 ==========

    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.metadata.id} name={self.metadata.name} type={self.metadata.type.code}>"


# ==================== 异常定义 ====================

class DataSourceException(Exception):
    """数据源基础异常"""
    pass


class ConnectionException(DataSourceException):
    """连接异常"""
    pass


class QueryException(DataSourceException):
    """查询异常"""
    pass


class SchemaException(DataSourceException):
    """Schema异常"""
    pass


class ConfigurationException(DataSourceException):
    """配置异常"""
    pass
