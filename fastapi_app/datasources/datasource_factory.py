"""
数据源工厂和注册中心

核心功能：
1. 数据源类型注册 - 动态注册新数据源类型
2. 工厂方法 - 根据类型创建数据源实例
3. 数据源管理 - 缓存、连接池、生命周期管理
4. 配置验证 - 确保配置正确

设计模式：
- 工厂模式：create_datasource
- 单例模式：DataSourceRegistry
- 策略模式：不同数据源不同策略

参考SQLBot：
- apps/db/constant.py: DB枚举注册
- apps/datasource/crud/datasource.py: create_ds, get_ds
"""

from typing import Dict, Type, Optional, List
import logging
from threading import Lock

from fastapi_app.core.datasource_interface import (
    DataSourceInterface,
    DataSourceMetadata,
    DataSourceType,
    ConfigurationException,
)
from fastapi_app.adapters.csv_datasource import CSVDataSource
from fastapi_app.adapters.sql_datasource import SQLDataSource
from fastapi_app.adapters.excel_datasource import ExcelDataSource
from fastapi_app.adapters.clickhouse_datasource import ClickHouseDataSource
from fastapi_app.adapters.oracle_datasource import OracleDataSource
from fastapi_app.adapters.elasticsearch_datasource import ElasticsearchDataSource

logger = logging.getLogger(__name__)


class DataSourceRegistry:
    """
    数据源注册中心（单例）

    功能：
    1. 注册数据源类型 -> 实现类的映射
    2. 提供工厂方法创建数据源
    3. 管理数据源实例缓存
    4. 验证配置完整性

    使用方式：
    ```python
    # 注册自定义数据源
    DataSourceRegistry.register(DataSourceType.CUSTOM, CustomDataSource)

    # 创建数据源
    ds = DataSourceRegistry.create_datasource(metadata)

    # 获取已缓存的数据源
    ds = DataSourceRegistry.get_datasource("datasource_id")
    ```
    """

    # 类型 -> 实现类 映射
    _registry: Dict[DataSourceType, Type[DataSourceInterface]] = {}

    # 数据源实例缓存 (id -> instance)
    _cache: Dict[str, DataSourceInterface] = {}

    # 线程锁（保证线程安全）
    _lock = Lock()

    # 初始化标志
    _initialized = False

    @classmethod
    def initialize(cls):
        """
        初始化注册中心

        注册内置数据源类型
        """
        if cls._initialized:
            return

        with cls._lock:
            if cls._initialized:  # 双重检查
                return

            # 注册SQL数据库
            cls._registry[DataSourceType.POSTGRESQL] = SQLDataSource
            cls._registry[DataSourceType.MYSQL] = SQLDataSource
            cls._registry[DataSourceType.SQLITE] = SQLDataSource
            cls._registry[DataSourceType.SQLSERVER] = SQLDataSource
            
            # 注册专用数据库适配器
            cls._registry[DataSourceType.CLICKHOUSE] = ClickHouseDataSource
            cls._registry[DataSourceType.ORACLE] = OracleDataSource

            # 注册文件数据源
            cls._registry[DataSourceType.CSV] = CSVDataSource
            cls._registry[DataSourceType.EXCEL] = ExcelDataSource
            cls._registry[DataSourceType.PARQUET] = CSVDataSource
            
            # 注册搜索引擎数据源
            cls._registry[DataSourceType.ELASTICSEARCH] = ElasticsearchDataSource

            cls._initialized = True
            logger.info(f"DataSourceRegistry initialized with {len(cls._registry)} types")

    @classmethod
    def register(cls, ds_type: DataSourceType, ds_class: Type[DataSourceInterface]):
        """
        注册数据源类型

        Args:
            ds_type: 数据源类型
            ds_class: 数据源实现类（必须继承DataSourceInterface）

        Raises:
            ValueError: 如果类型已注册或类不符合要求
        """
        if not issubclass(ds_class, DataSourceInterface):
            raise ValueError(f"{ds_class} must be subclass of DataSourceInterface")

        with cls._lock:
            if ds_type in cls._registry:
                logger.warning(f"Overwriting existing registration for {ds_type.code}")

            cls._registry[ds_type] = ds_class
            logger.info(f"Registered datasource type: {ds_type.code} -> {ds_class.__name__}")

    @classmethod
    def unregister(cls, ds_type: DataSourceType):
        """取消注册数据源类型"""
        with cls._lock:
            if ds_type in cls._registry:
                del cls._registry[ds_type]
                logger.info(f"Unregistered datasource type: {ds_type.code}")

    @classmethod
    def get_registered_types(cls) -> List[DataSourceType]:
        """获取所有已注册的数据源类型"""
        return list(cls._registry.keys())

    @classmethod
    def is_type_supported(cls, ds_type: DataSourceType) -> bool:
        """检查数据源类型是否被支持"""
        return ds_type in cls._registry

    # ========== 工厂方法 ==========

    @classmethod
    def create_datasource(cls, metadata: DataSourceMetadata,
                         auto_connect: bool = False,
                         use_cache: bool = True) -> DataSourceInterface:
        """
        创建数据源实例（工厂方法）

        Args:
            metadata: 数据源元数据
            auto_connect: 是否自动连接
            use_cache: 是否使用缓存（如果已存在相同ID的实例，直接返回）

        Returns:
            DataSourceInterface: 数据源实例

        Raises:
            ConfigurationException: 配置错误
            ConnectionException: 连接失败（当auto_connect=True时）
        """
        cls.initialize()

        # 验证配置
        cls._validate_metadata(metadata)

        # 检查缓存
        if use_cache and metadata.id in cls._cache:
            logger.info(f"Using cached datasource: {metadata.id}")
            return cls._cache[metadata.id]

        # 获取对应的实现类
        ds_type = metadata.type
        if ds_type not in cls._registry:
            raise ConfigurationException(
                f"Unsupported datasource type: {ds_type.code}. "
                f"Supported types: {[t.code for t in cls._registry.keys()]}"
            )

        ds_class = cls._registry[ds_type]

        # 创建实例
        try:
            instance = ds_class(metadata)
            logger.info(f"Created datasource instance: {metadata.name} ({ds_type.code})")

            # 自动连接
            if auto_connect:
                instance.connect()

            # 缓存
            if use_cache:
                with cls._lock:
                    cls._cache[metadata.id] = instance

            return instance

        except Exception as e:
            logger.error(f"Failed to create datasource: {e}")
            raise

    @classmethod
    def create_datasource_from_config(cls, config: Dict) -> DataSourceInterface:
        """
        从配置字典创建数据源

        Args:
            config: 配置字典，包含：
                - id: 数据源ID
                - name: 数据源名称
                - type: 数据源类型（字符串）
                - connection_config: 连接配置
                - description: 描述（可选）
                - tags: 标签（可选）

        Returns:
            DataSourceInterface: 数据源实例
        """
        # 解析类型
        type_code = config.get("type", "").lower()
        try:
            ds_type = DataSourceType.from_code(type_code)
        except ValueError:
            raise ConfigurationException(f"Invalid datasource type: {type_code}")

        # 构建元数据
        metadata = DataSourceMetadata(
            id=config.get("id"),
            name=config.get("name"),
            type=ds_type,
            connection_config=config.get("connection_config", {}),
            description=config.get("description"),
            tags=config.get("tags", []),
        )

        return cls.create_datasource(metadata)

    # ========== 缓存管理 ==========

    @classmethod
    def get_datasource(cls, datasource_id: str) -> Optional[DataSourceInterface]:
        """
        从缓存获取数据源实例

        Args:
            datasource_id: 数据源ID

        Returns:
            Optional[DataSourceInterface]: 数据源实例，如果不存在返回None
        """
        return cls._cache.get(datasource_id)

    @classmethod
    def remove_datasource(cls, datasource_id: str) -> bool:
        """
        从缓存移除数据源

        Args:
            datasource_id: 数据源ID

        Returns:
            bool: 是否成功移除
        """
        with cls._lock:
            if datasource_id in cls._cache:
                # 断开连接
                ds = cls._cache[datasource_id]
                try:
                    ds.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting datasource {datasource_id}: {e}")

                del cls._cache[datasource_id]
                logger.info(f"Removed datasource from cache: {datasource_id}")
                return True
            return False

    @classmethod
    def clear_cache(cls):
        """清空缓存（断开所有连接）"""
        with cls._lock:
            for ds_id, ds in list(cls._cache.items()):
                try:
                    ds.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting datasource {ds_id}: {e}")

            cls._cache.clear()
            logger.info("Cleared datasource cache")

    @classmethod
    def get_cached_datasource_ids(cls) -> List[str]:
        """获取所有缓存的数据源ID"""
        return list(cls._cache.keys())

    # ========== 配置验证 ==========

    @classmethod
    def _validate_metadata(cls, metadata: DataSourceMetadata):
        """
        验证数据源元数据

        Raises:
            ConfigurationException: 配置不完整或错误
        """
        if not metadata.id:
            raise ConfigurationException("Datasource ID is required")

        if not metadata.name:
            raise ConfigurationException("Datasource name is required")

        if not metadata.type:
            raise ConfigurationException("Datasource type is required")

        if not metadata.connection_config:
            raise ConfigurationException("Connection config is required")

        # 类型特定验证
        cls._validate_connection_config(metadata.type, metadata.connection_config)

    @classmethod
    def _validate_connection_config(cls, ds_type: DataSourceType, config: Dict):
        """
        验证连接配置

        不同数据源类型有不同的必需字段
        """
        # SQL数据库
        if ds_type.category == "sql" and ds_type != DataSourceType.SQLITE:
            required_fields = ["host", "port", "database", "username"]
            for field in required_fields:
                if field not in config:
                    raise ConfigurationException(f"Missing required config for {ds_type.code}: {field}")

        # SQLite
        elif ds_type == DataSourceType.SQLITE:
            if "database_path" not in config:
                raise ConfigurationException("Missing required config for SQLite: database_path")

        # CSV/Excel
        elif ds_type in [DataSourceType.CSV, DataSourceType.EXCEL, DataSourceType.PARQUET]:
            if "file_path" not in config and "files" not in config:
                raise ConfigurationException(f"Missing required config for {ds_type.code}: file_path or files")

    # ========== 辅助方法 ==========

    @classmethod
    def test_all_connections(cls) -> Dict[str, bool]:
        """
        测试所有缓存数据源的连接

        Returns:
            Dict[str, bool]: 数据源ID -> 连接状态
        """
        results = {}
        for ds_id, ds in cls._cache.items():
            try:
                results[ds_id] = ds.test_connection()
            except Exception as e:
                logger.error(f"Connection test failed for {ds_id}: {e}")
                results[ds_id] = False

        return results

    @classmethod
    def get_stats(cls) -> Dict:
        """
        获取注册中心统计信息

        Returns:
            Dict: 统计信息
        """
        return {
            "registered_types": len(cls._registry),
            "cached_datasources": len(cls._cache),
            "types": [t.code for t in cls._registry.keys()],
            "cached_ids": list(cls._cache.keys()),
        }

    @classmethod
    def __repr__(cls):
        return f"<DataSourceRegistry types={len(cls._registry)} cached={len(cls._cache)}>"


# ========== 便捷函数 ==========

def create_datasource(metadata: DataSourceMetadata, auto_connect: bool = False) -> DataSourceInterface:
    """
    便捷函数：创建数据源

    这是对DataSourceRegistry.create_datasource的封装
    """
    return DataSourceRegistry.create_datasource(metadata, auto_connect=auto_connect)


def get_datasource(datasource_id: str) -> Optional[DataSourceInterface]:
    """
    便捷函数：获取缓存的数据源
    """
    return DataSourceRegistry.get_datasource(datasource_id)


# 自动初始化
DataSourceRegistry.initialize()
