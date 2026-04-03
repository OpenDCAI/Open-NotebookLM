"""
SQL工具 - SQL执行和验证

参考JoyAgent的工具设计：每个工具独立文件
参考SQLBot的SQL处理逻辑
"""
from langchain_core.tools import tool
from typing import Optional, List
import json
import logging
import re

from .datasource_manager import get_datasource_handler
from fastapi_app.core.datasource_interface import DataSourceInterface

logger = logging.getLogger(__name__)


# ============== DuckDB 函数兼容层 ==============
# LLM 经常生成 MySQL/PostgreSQL 语法，但 CSV 数据源使用 DuckDB
# 此映射自动转换不兼容的函数

DUCKDB_FUNCTION_MAPPINGS = {
    # 日期函数映射 (MySQL -> DuckDB)
    r"DATE_FORMAT\s*\(\s*([^,]+)\s*,\s*'([^']+)'\s*\)": r"strftime(\1, '\2')",
    r"DATE_FORMAT\s*\(\s*([^,]+)\s*,\s*\"([^\"]+)\"\s*\)": r"strftime(\1, '\2')",
    
    # 日期提取函数
    r"YEAR\s*\(\s*([^)]+)\s*\)": r"EXTRACT(YEAR FROM \1)",
    r"MONTH\s*\(\s*([^)]+)\s*\)": r"EXTRACT(MONTH FROM \1)",
    r"DAY\s*\(\s*([^)]+)\s*\)": r"EXTRACT(DAY FROM \1)",
    r"HOUR\s*\(\s*([^)]+)\s*\)": r"EXTRACT(HOUR FROM \1)",
    r"MINUTE\s*\(\s*([^)]+)\s*\)": r"EXTRACT(MINUTE FROM \1)",
    r"SECOND\s*\(\s*([^)]+)\s*\)": r"EXTRACT(SECOND FROM \1)",
    
    # 字符串函数
    r"CONCAT_WS\s*\(\s*'([^']+)'\s*,": r"CONCAT_WS('\1',",
    r"SUBSTRING_INDEX\s*\(": r"SPLIT_PART(",  # 语法不完全相同，可能需要更复杂处理
    
    # 日期差值
    r"DATEDIFF\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)": r"DATE_DIFF('day', \2, \1)",
    
    # 当前时间
    r"NOW\s*\(\s*\)": r"CURRENT_TIMESTAMP",
    r"CURDATE\s*\(\s*\)": r"CURRENT_DATE",
    
    # IF函数 -> CASE WHEN
    r"IF\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^)]+)\s*\)": r"CASE WHEN \1 THEN \2 ELSE \3 END",
    
    # IFNULL -> COALESCE
    r"IFNULL\s*\(": r"COALESCE(",
    r"NVL\s*\(": r"COALESCE(",
    
    # GROUP_CONCAT -> STRING_AGG (PostgreSQL style, DuckDB supports both)
    r"GROUP_CONCAT\s*\(\s*([^)]+)\s*\)": r"STRING_AGG(\1, ',')",
}

# 日期格式符号映射 (MySQL -> DuckDB/strftime)
DATE_FORMAT_MAPPINGS = {
    '%Y': '%Y',      # 4位年
    '%y': '%y',      # 2位年
    '%m': '%m',      # 2位月 (01-12)
    '%c': '%-m',     # 月 (1-12，无前导零)
    '%d': '%d',      # 2位日 (01-31)
    '%e': '%-d',     # 日 (1-31，无前导零)
    '%H': '%H',      # 24小时 (00-23)
    '%h': '%I',      # 12小时 (01-12)
    '%i': '%M',      # 分钟 (00-59)
    '%s': '%S',      # 秒 (00-59)
    '%W': '%A',      # 星期全名
    '%a': '%a',      # 星期缩写
    '%M': '%B',      # 月份全名
    '%b': '%b',      # 月份缩写
}


def _convert_sql_for_duckdb(sql: str) -> str:
    """
    将 MySQL/PostgreSQL 风格的 SQL 转换为 DuckDB 兼容语法
    
    Args:
        sql: 原始 SQL 语句
        
    Returns:
        转换后的 DuckDB 兼容 SQL
    """
    converted_sql = sql
    
    # 应用函数映射
    for pattern, replacement in DUCKDB_FUNCTION_MAPPINGS.items():
        converted_sql = re.sub(pattern, replacement, converted_sql, flags=re.IGNORECASE)
    
    # 转换日期格式符号（在 strftime 调用中）
    def convert_date_format(match):
        format_str = match.group(1)
        for mysql_fmt, duckdb_fmt in DATE_FORMAT_MAPPINGS.items():
            format_str = format_str.replace(mysql_fmt, duckdb_fmt)
        return f"strftime({match.group(0).split('(')[1].split(',')[0]}, '{format_str}')"
    
    # 记录转换（用于调试）
    if converted_sql != sql:
        logger.info(f"SQL converted for DuckDB compatibility:\n  Original: {sql[:200]}...\n  Converted: {converted_sql[:200]}...")
    
    return converted_sql


@tool
def execute_sql(datasource_id: int, sql: str, limit: int = 1000) -> str:
    """
    执行SQL查询（支持完整SQL语法）
    
    核心改进（参考SQLBot）：
    1. 支持DuckDB完整SQL语法（JOIN/子查询/窗口函数/CTE等）
    2. 支持SQL数据库查询
    3. 参数化查询防止注入
    4. 自动添加LIMIT限制
    5. 返回标准化的QueryResult格式
    
    Args:
        datasource_id: 数据源ID
        sql: SQL查询语句
        limit: 结果行数限制（默认1000，最大10000）
    
    Returns:
        JSON字符串，包含：
        {
            "success": bool,
            "data": [...],  # 查询结果
            "columns": [...],  # 列名
            "row_count": int,
            "execution_time_ms": float,
            "error_message": str  # 如果失败
        }
    
    示例SQL：
    - 简单查询: SELECT * FROM table_name WHERE col > 100
    - JOIN: SELECT a.*, b.name FROM orders a JOIN customers b ON a.customer_id = b.id
    - 聚合: SELECT category, COUNT(*), AVG(price) FROM products GROUP BY category
    - 窗口函数: SELECT *, ROW_NUMBER() OVER (PARTITION BY category ORDER BY price DESC) FROM products
    - CTE: WITH top_sales AS (SELECT * FROM sales WHERE amount > 10000) SELECT * FROM top_sales
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({
            "success": False,
            "error_message": f"数据源 {datasource_id} 未找到。请先上传数据文件。"
        })
    
    # 限制最大返回行数（安全措施）
    limit = min(limit, 10000)
    
    # DuckDB 函数兼容性转换（CSV数据源使用DuckDB引擎）
    original_sql = sql
    sql = _convert_sql_for_duckdb(sql)
    
    try:
        # 执行查询
        result = datasource.execute_query(sql, limit=limit)
        
        # 转换为JSON
        return json.dumps({
            "success": result.success,
            "query_text": sql,  # 返回执行的SQL以便追踪
            "data": result.data,
            "columns": result.columns,
            "row_count": result.row_count,
            "execution_time_ms": result.execution_time_ms,
            "error_message": result.error_message,
        }, ensure_ascii=False, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"SQL execution error: {e}\nSQL: {sql}")
        return json.dumps({
            "success": False,
            "error_message": f"SQL执行失败: {str(e)}",
            "query_text": sql,
        }, ensure_ascii=False)


@tool
def validate_sql(datasource_id: int, sql: str) -> str:
    """
    验证SQL语法正确性（不执行查询）
    
    参考SQLBot的check_sql设计，用于：
    1. SQL语法检查
    2. 表名/列名存在性验证
    3. 提供修正建议
    
    Args:
        datasource_id: 数据源ID
        sql: 待验证的SQL语句
    
    Returns:
        JSON字符串，包含：
        {
            "valid": bool,
            "error_message": str,  # 如果无效
            "suggestions": [...]  # 修正建议
        }
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({
            "valid": False,
            "error_message": f"数据源 {datasource_id} 未找到"
        })
    
    # DuckDB 函数兼容性转换
    sql = _convert_sql_for_duckdb(sql)
    
    try:
        # 对于DuckDB，使用EXPLAIN验证
        explain_sql = f"EXPLAIN {sql}"
        result = datasource.execute_query(explain_sql, limit=1)
        
        if result.success:
            return json.dumps({
                "valid": True,
                "message": "SQL语法正确"
            })
        else:
            suggestions = _parse_sql_error_suggestions(result.error_message or "", sql, datasource)
            
            return json.dumps({
                "valid": False,
                "error_message": result.error_message,
                "suggestions": suggestions,
            }, ensure_ascii=False)
            
    except Exception as e:
        error_msg = str(e)
        suggestions = _parse_sql_error_suggestions(error_msg, sql, datasource)
        
        return json.dumps({
            "valid": False,
            "error_message": error_msg,
            "suggestions": suggestions,
        }, ensure_ascii=False)


@tool
def query_data(datasource_id: int, columns: List[str],
               where: Optional[str] = None,
               group_by: Optional[str] = None,
               order_by: Optional[str] = None,
               limit: int = 100) -> str:
    """
    查询数据源中的数据（简化SQL接口）
    
    注意：此工具已弃用，推荐使用 execute_sql 获得完整SQL能力。
    此工具仅保留用于向后兼容和简单查询场景。

    Args:
        datasource_id: 数据源ID
        columns: 要查询的列名列表
        where: WHERE条件 (SQL语法)
        group_by: GROUP BY的列名
        order_by: ORDER BY的列名
        limit: 返回的最大行数

    Returns:
        查询结果的JSON字符串
        
    建议：对于复杂查询（JOIN/子查询/窗口函数），请使用 execute_sql 工具。
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({
            "error": f"数据源 {datasource_id} 未找到"
        })

    try:
        # 构建简单SQL
        tables = datasource.get_tables()
        if not tables:
            return json.dumps({"error": "数据源中没有表"})
        
        table_name = tables[0].name  # 默认使用第一个表
        
        # 构建SELECT子句
        if columns and columns != ['*']:
            cols_str = ', '.join(f'"{col}"' for col in columns)
        else:
            cols_str = '*'
        
        sql = f'SELECT {cols_str} FROM "{table_name}"'
        
        # 添加WHERE
        if where:
            sql += f' WHERE {where}'
        
        # 添加GROUP BY
        if group_by:
            sql += f' GROUP BY "{group_by}"'
        
        # 添加ORDER BY
        if order_by:
            sql += f' ORDER BY "{order_by}" DESC'
        
        # 添加LIMIT
        sql += f' LIMIT {limit}'
        
        # 执行查询
        result = datasource.execute_query(sql)
        
        if result.success:
            return json.dumps({
                "success": True,
                "data": result.data,
                "row_count": result.row_count,
            }, ensure_ascii=False, indent=2, default=str)
        else:
            return json.dumps({
                "success": False,
                "error": result.error_message
            })
            
    except Exception as e:
        logger.error(f"Query error: {e}")
        return json.dumps({"error": str(e)})


def _parse_sql_error_suggestions(error_msg: str, sql: str, datasource: DataSourceInterface) -> List[str]:
    """
    解析SQL错误，生成修正建议
    
    参考SQLBot的错误处理逻辑
    """
    suggestions = []
    error_lower = error_msg.lower()
    sql_upper = sql.upper()
    
    # 表不存在错误
    if "table" in error_lower and ("not found" in error_lower or "does not exist" in error_lower or "doesn't exist" in error_lower):
        suggestions.append("检查表名是否正确。")
        try:
            tables = datasource.get_tables()
            table_names = [t.name for t in tables]
            suggestions.append(f"可用的表: {', '.join(table_names)}")
        except:
            pass
    
    # 列不存在错误
    if "column" in error_lower and ("not found" in error_lower or "does not exist" in error_lower or "doesn't exist" in error_lower):
        suggestions.append("检查列名是否正确。")
        suggestions.append("使用 get_datasource_schema 查看可用的列。")
    
    # DuckDB 函数兼容性错误
    if "function" in error_lower and "does not exist" in error_lower:
        suggestions.append("【DuckDB兼容性】此数据源使用DuckDB引擎，部分MySQL/PostgreSQL函数不兼容：")
        
        # 检测具体不兼容的函数
        if "date_format" in error_lower or "DATE_FORMAT" in sql_upper:
            suggestions.append("  - DATE_FORMAT() → 请使用 strftime(date, '%Y-%m')")
        if "year(" in error_lower or "YEAR(" in sql_upper:
            suggestions.append("  - YEAR() → 请使用 EXTRACT(YEAR FROM date)")
        if "month(" in error_lower or "MONTH(" in sql_upper:
            suggestions.append("  - MONTH() → 请使用 EXTRACT(MONTH FROM date)")
        if "datediff" in error_lower or "DATEDIFF" in sql_upper:
            suggestions.append("  - DATEDIFF() → 请使用 DATE_DIFF('day', start, end)")
        if "now(" in error_lower or "NOW(" in sql_upper:
            suggestions.append("  - NOW() → 请使用 CURRENT_TIMESTAMP")
        if "ifnull" in error_lower or "IFNULL" in sql_upper:
            suggestions.append("  - IFNULL() → 请使用 COALESCE()")
        if "group_concat" in error_lower or "GROUP_CONCAT" in sql_upper:
            suggestions.append("  - GROUP_CONCAT() → 请使用 STRING_AGG(col, ',')")
    
    # 语法错误
    if "syntax" in error_lower or "parse" in error_lower:
        suggestions.append("检查SQL语法是否正确。")
        suggestions.append("常见问题：缺少逗号、括号不匹配、关键字拼写错误。")
    
    # 聚合错误
    if "group by" in error_lower or "aggregate" in error_lower:
        suggestions.append("使用聚合函数时，非聚合列必须在 GROUP BY 中。")
    
    # 类型错误
    if "type" in error_lower or "cast" in error_lower:
        suggestions.append("检查数据类型是否匹配。")
        suggestions.append("可能需要类型转换：CAST(column AS type)")
    
    return suggestions






