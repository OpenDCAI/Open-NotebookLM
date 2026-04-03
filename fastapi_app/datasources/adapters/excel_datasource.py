"""
Excel数据源适配器（基于DuckDB）

支持特性：
1. xlsx/xls格式支持 - 使用DuckDB的Excel扩展
2. 多Sheet支持 - 每个Sheet作为独立表
3. 类型自动推断 - DuckDB智能类型检测
4. SQL查询 - 完整SQL语法支持

核心优势（相比SQLBot将Excel导入PostgreSQL）：
- 零导入延迟 - 直接查询Excel文件
- 内存高效 - DuckDB优化的内存管理
- 无需外部数据库 - 纯Python实现
"""

import duckdb
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import time

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


class ExcelDataSource(DataSourceInterface):
    """
    Excel文件数据源（基于DuckDB）
    
    使用方式：
    ```python
    # 单文件（自动读取所有Sheet）
    metadata = DataSourceMetadata(
        id="excel_sales",
        name="销售报表",
        type=DataSourceType.EXCEL,
        connection_config={
            "file_path": "/path/to/sales.xlsx",
            "sheet_name": None,  # None表示所有Sheet，或指定Sheet名称
            "header_row": 0,  # 表头行号（0-based）
            "skip_rows": 0,  # 跳过的行数
        }
    )
    ds = ExcelDataSource(metadata)
    ds.connect()
    result = ds.execute_query("SELECT * FROM Sheet1 WHERE amount > 1000")
    
    # 多Sheet作为多表
    # Sheet1, Sheet2 自动注册为表名
    result = ds.execute_query('''
        SELECT a.*, b.category_name
        FROM Sheet1 a
        JOIN Sheet2 b ON a.category_id = b.id
    ''')
    ```
    """
    
    def __init__(self, metadata: DataSourceMetadata):
        super().__init__(metadata)
        self.conn: Optional[duckdb.DuckDBPyConnection] = None
        self._tables_cache: Dict[str, TableSchema] = {}
        self._sheet_names: List[str] = []
        
    def connect(self) -> bool:
        """建立DuckDB连接并注册Excel文件"""
        try:
            # 创建内存数据库连接
            self.conn = duckdb.connect(':memory:')
            
            # 安装并加载spatial扩展（用于Excel支持）
            # DuckDB 0.9+原生支持Excel
            try:
                self.conn.execute("INSTALL spatial")
                self.conn.execute("LOAD spatial")
            except:
                pass  # 如果已安装则忽略错误
            
            # 注册Excel文件
            self._register_excel_file()
            
            self._connected = True
            logger.info(f"Successfully connected to Excel datasource: {self.metadata.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect Excel datasource: {e}")
            raise ConnectionException(f"Excel连接失败: {str(e)}")
    
    def disconnect(self):
        """断开连接"""
        if self.conn:
            try:
                self.conn.close()
                self._connected = False
                logger.info(f"Disconnected from Excel datasource: {self.metadata.name}")
            except Exception as e:
                logger.warning(f"Error disconnecting Excel datasource: {e}")
    
    def test_connection(self) -> bool:
        """测试连接"""
        if not self.conn:
            return False
        try:
            self.conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False
    
    def _register_excel_file(self):
        """注册Excel文件为DuckDB表"""
        config = self.metadata.connection_config
        file_path = Path(config.get("file_path"))
        
        if not file_path.exists():
            raise FileNotFoundError(f"Excel文件不存在: {file_path}")
        
        # 获取配置
        specified_sheet = config.get("sheet_name")
        header_row = config.get("header_row", 0)
        skip_rows = config.get("skip_rows", 0)
        
        try:
            # 方法1: 使用DuckDB的st_read读取Excel（需要spatial扩展）
            # 方法2: 使用pandas读取后创建表
            import pandas as pd
            
            # 读取Excel获取所有Sheet名称
            excel_file = pd.ExcelFile(file_path)
            sheet_names = excel_file.sheet_names
            
            # 如果指定了特定Sheet，只注册该Sheet
            if specified_sheet:
                if specified_sheet not in sheet_names:
                    raise SchemaException(f"Sheet '{specified_sheet}' 不存在于Excel文件中")
                sheets_to_register = [specified_sheet]
            else:
                sheets_to_register = sheet_names
            
            self._sheet_names = sheets_to_register
            
            # 注册每个Sheet为表
            for sheet_name in sheets_to_register:
                df = pd.read_excel(
                    file_path,
                    sheet_name=sheet_name,
                    header=header_row,
                    skiprows=skip_rows if header_row == 0 else None,
                )
                
                # 清理列名（移除空格和特殊字符）
                df.columns = [self._clean_column_name(col) for col in df.columns]
                
                # 创建表名（清理Sheet名称）
                table_name = self._clean_table_name(sheet_name)
                
                # 注册为DuckDB表
                self.conn.register(table_name, df)
                
                # 创建永久表（以便后续查询）
                self.conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM {table_name}")
                
                logger.info(f"Registered Excel sheet '{sheet_name}' as table '{table_name}'")
                
        except ImportError:
            # 如果没有pandas，尝试使用DuckDB的原生方法
            logger.warning("pandas not available, trying DuckDB native Excel reading")
            self._register_excel_native(file_path, specified_sheet)
    
    def _register_excel_native(self, file_path: Path, sheet_name: Optional[str] = None):
        """使用DuckDB原生方法读取Excel（需要spatial扩展）"""
        try:
            # DuckDB的st_read可以读取Excel
            table_name = sheet_name or file_path.stem
            table_name = self._clean_table_name(table_name)
            
            sql = f"""
                CREATE TABLE {table_name} AS 
                SELECT * FROM st_read('{file_path}')
            """
            self.conn.execute(sql)
            
            self._sheet_names = [table_name]
            logger.info(f"Registered Excel file as table '{table_name}' using DuckDB native method")
            
        except Exception as e:
            raise SchemaException(f"无法读取Excel文件: {str(e)}. 请安装pandas: pip install pandas openpyxl")
    
    def _clean_column_name(self, col_name: Any) -> str:
        """清理列名"""
        if col_name is None or (isinstance(col_name, float) and str(col_name) == 'nan'):
            return "unnamed"
        
        col_str = str(col_name).strip()
        
        # 替换特殊字符
        col_str = col_str.replace(" ", "_").replace("-", "_").replace(".", "_")
        col_str = ''.join(c if c.isalnum() or c == '_' else '_' for c in col_str)
        
        # 确保不以数字开头
        if col_str and col_str[0].isdigit():
            col_str = "col_" + col_str
        
        return col_str or "unnamed"
    
    def _clean_table_name(self, name: str) -> str:
        """清理表名"""
        # 替换特殊字符
        name = name.replace(" ", "_").replace("-", "_").replace(".", "_")
        name = ''.join(c if c.isalnum() or c == '_' else '_' for c in name)
        
        # 确保不以数字开头
        if name and name[0].isdigit():
            name = "sheet_" + name
        
        return name or "sheet"
    
    # ========== Schema获取 ==========
    
    def get_tables(self) -> List[TableSchema]:
        """获取所有表（Sheet）的Schema"""
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
                    self._tables_cache[table_name] = schema
            
            return tables
            
        except Exception as e:
            logger.error(f"Failed to get Excel tables: {e}")
            raise SchemaException(f"获取表列表失败: {str(e)}")
    
    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """获取单个表（Sheet）的Schema"""
        if table_name in self._tables_cache:
            return self._tables_cache[table_name]
        
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            # 使用DESCRIBE获取列信息
            columns_result = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
            
            columns = []
            for row in columns_result:
                col_name = row[0]
                col_type_native = row[1]
                col_nullable = row[2] == 'YES' if len(row) > 2 else True
                
                col_type = ColumnType.from_native_type(col_type_native, DataSourceType.EXCEL)
                
                # 获取样本值和统计
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
            
            # 获取原始Sheet名称
            config = self.metadata.connection_config
            file_path = config.get("file_path", "")
            
            table_schema = TableSchema(
                name=table_name,
                columns=columns,
                row_count=row_count,
                comment=f"Excel Sheet from: {file_path}",
            )
            
            self._tables_cache[table_name] = table_schema
            return table_schema
            
        except Exception as e:
            logger.error(f"Failed to get schema for Excel table {table_name}: {e}")
            return None
    
    def _get_column_samples(self, table_name: str, column_name: str, limit: int = 5) -> List[Any]:
        """获取列的样本值"""
        try:
            result = self.conn.execute(f"""
                SELECT DISTINCT "{column_name}"
                FROM {table_name}
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
                FROM {table_name}
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
                    FROM {table_name}
                    WHERE "{column_name}" IS NOT NULL
                """).fetchone()
                
                if num_result:
                    stats["min_value"] = float(num_result[0]) if num_result[0] is not None else None
                    stats["max_value"] = float(num_result[1]) if num_result[1] is not None else None
                    stats["avg_value"] = float(num_result[2]) if num_result[2] is not None else None
                    
        except Exception as e:
            logger.warning(f"Failed to get stats for Excel {table_name}.{column_name}: {e}")
        
        return stats
    
    # ========== 查询执行 ==========
    
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                     limit: Optional[int] = None) -> QueryResult:
        """执行SQL查询"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        start_time = time.time()
        
        try:
            # 添加LIMIT限制
            if limit and "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"
            
            # 执行查询
            if params:
                result = self.conn.execute(query, params).fetchall()
                columns = [desc[0] for desc in self.conn.description]
            else:
                result = self.conn.execute(query).fetchall()
                columns = [desc[0] for desc in self.conn.description]
            
            # 转换为字典列表
            data = [dict(zip(columns, row)) for row in result]
            
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
            logger.error(f"Excel query execution failed: {e}\nQuery: {query}")
            
            return QueryResult(
                success=False,
                error_message=str(e),
                execution_time_ms=execution_time,
                query_text=query,
            )
    
    def _build_sample_query(self, table_name: str, limit: int) -> str:
        """构建样本数据查询"""
        return f'SELECT * FROM {table_name} LIMIT {limit}'
    
    def _build_count_query(self, table_name: str) -> str:
        """构建计数查询"""
        return f'SELECT COUNT(*) as count FROM {table_name}'
    
    # ========== Excel特有功能 ==========
    
    def get_sheet_names(self) -> List[str]:
        """获取所有Sheet名称"""
        return self._sheet_names.copy()
    
    def export_to_csv(self, table_name: str, output_path: Path):
        """导出表为CSV"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            self.conn.execute(f"""
                COPY {table_name} TO '{output_path}' (HEADER, DELIMITER ',')
            """)
            logger.info(f"Exported {table_name} to {output_path}")
        except Exception as e:
            logger.error(f"Failed to export to CSV: {e}")
            raise QueryException(f"导出CSV失败: {str(e)}")
    
    def export_to_parquet(self, table_name: str, output_path: Path):
        """导出表为Parquet"""
        if not self.is_connected:
            raise ConnectionException("未连接到数据源")
        
        try:
            self.conn.execute(f"""
                COPY {table_name} TO '{output_path}' (FORMAT PARQUET)
            """)
            logger.info(f"Exported {table_name} to {output_path}")
        except Exception as e:
            logger.error(f"Failed to export to Parquet: {e}")
            raise QueryException(f"导出Parquet失败: {str(e)}")




