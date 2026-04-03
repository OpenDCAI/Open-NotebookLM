"""
数据源适配器模块

包含各种数据源的具体实现:
- SQLDataSource: PostgreSQL, MySQL, SQLite, SQL Server通用适配器
- CSVDataSource: CSV文件适配器（基于DuckDB）
- ExcelDataSource: Excel文件适配器（基于DuckDB）
- ClickHouseDataSource: ClickHouse数据仓库适配器
- OracleDataSource: Oracle数据库适配器（支持thick/thin模式）
- ElasticsearchDataSource: Elasticsearch搜索引擎适配器
"""

from .csv_datasource import CSVDataSource
from .sql_datasource import SQLDataSource
from .excel_datasource import ExcelDataSource
from .clickhouse_datasource import ClickHouseDataSource
from .oracle_datasource import OracleDataSource
from .elasticsearch_datasource import ElasticsearchDataSource

__all__ = [
    'CSVDataSource',
    'SQLDataSource', 
    'ExcelDataSource',
    'ClickHouseDataSource',
    'OracleDataSource',
    'ElasticsearchDataSource',
]
