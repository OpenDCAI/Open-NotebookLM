"""
分析工具 - 数据分析和统计

参考JoyAgent的工具设计：每个工具独立文件
"""
from langchain_core.tools import tool
from typing import Optional
import json
import logging

from .datasource_manager import get_datasource_handler

logger = logging.getLogger(__name__)


@tool
def analyze_columns(datasource_id: int, columns: list, table_name: Optional[str] = None) -> str:
    """
    分析指定列的统计信息
    
    改进（使用SQL聚合）：
    1. 更快速（使用DuckDB的聚合引擎）
    2. 支持大数据集
    3. 统一使用SQL接口

    Args:
        datasource_id: 数据源ID
        columns: 要分析的列名列表
        table_name: 表名（可选，默认使用第一个表）

    Returns:
        统计信息的JSON字符串
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({"error": f"数据源 {datasource_id} 未找到"})

    try:
        # 获取表名
        if not table_name:
            tables = datasource.get_tables()
            if not tables:
                return json.dumps({"error": "数据源中没有表"})
            table_name = tables[0].name
        
        # 获取表Schema以确定列类型
        table_schema = datasource.get_table_schema(table_name)
        if not table_schema:
            return json.dumps({"error": f"表 {table_name} 不存在"})
        
        analysis = {}
        
        for col in columns:
            col_schema = table_schema.get_column(col)
            if not col_schema:
                analysis[col] = {"error": f"列 {col} 不存在"}
                continue
            
            # 基础统计（所有列）
            sql = f"""
                SELECT
                    COUNT(*) as total_count,
                    COUNT("{col}") as non_null_count,
                    COUNT(*) - COUNT("{col}") as null_count,
                    COUNT(DISTINCT "{col}") as unique_count
                FROM "{table_name}"
            """
            result = datasource.execute_query(sql)
            
            if not result.success or not result.data:
                analysis[col] = {"error": result.error_message}
                continue
            
            stats = result.data[0]
            col_analysis = {
                "name": col,
                "dtype": col_schema.data_type.value,
                "total_count": stats["total_count"],
                "non_null_count": stats["non_null_count"],
                "null_count": stats["null_count"],
                "unique_count": stats["unique_count"],
            }
            
            # 数值统计
            if col_schema.data_type.value in ['integer', 'bigint', 'float', 'double', 'decimal']:
                sql = f"""
                    SELECT
                        MIN("{col}") as min_val,
                        MAX("{col}") as max_val,
                        AVG("{col}") as avg_val,
                        MEDIAN("{col}") as median_val,
                        STDDEV("{col}") as std_val
                    FROM "{table_name}"
                    WHERE "{col}" IS NOT NULL
                """
                result = datasource.execute_query(sql)
                if result.success and result.data:
                    num_stats = result.data[0]
                    col_analysis.update({
                        "min": num_stats["min_val"],
                        "max": num_stats["max_val"],
                        "mean": num_stats["avg_val"],
                        "median": num_stats["median_val"],
                        "std": num_stats["std_val"],
                    })
            
            # 分类统计（唯一值<20时）
            if stats["unique_count"] < 20:
                sql = f"""
                    SELECT "{col}", COUNT(*) as count
                    FROM "{table_name}"
                    WHERE "{col}" IS NOT NULL
                    GROUP BY "{col}"
                    ORDER BY count DESC
                    LIMIT 20
                """
                result = datasource.execute_query(sql)
                if result.success and result.data:
                    col_analysis["value_counts"] = {
                        row[col]: row["count"] for row in result.data
                    }
            
            analysis[col] = col_analysis

        return json.dumps(analysis, ensure_ascii=False, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return json.dumps({"error": str(e)})


@tool
def detect_trends(datasource_id: int, time_column: str, value_column: str, 
                  table_name: Optional[str] = None) -> str:
    """
    检测时间序列的趋势
    
    改进（使用SQL窗口函数）：
    1. 更高效的趋势计算
    2. 支持大数据集
    3. 可选的移动平均

    Args:
        datasource_id: 数据源ID
        time_column: 时间列名
        value_column: 数值列名
        table_name: 表名（可选）

    Returns:
        趋势分析结果的JSON字符串
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({"error": f"数据源 {datasource_id} 未找到"})

    try:
        # 获取表名
        if not table_name:
            tables = datasource.get_tables()
            if not tables:
                return json.dumps({"error": "数据源中没有表"})
            table_name = tables[0].name
        
        # 使用SQL进行趋势分析
        sql = f"""
        WITH ordered_data AS (
            SELECT 
                "{time_column}",
                "{value_column}",
                ROW_NUMBER() OVER (ORDER BY "{time_column}") as row_num,
                COUNT(*) OVER () as total_rows
            FROM "{table_name}"
            WHERE "{time_column}" IS NOT NULL AND "{value_column}" IS NOT NULL
            ORDER BY "{time_column}"
        ),
        first_last AS (
            SELECT
                MAX(CASE WHEN row_num = 1 THEN "{value_column}" END) as first_value,
                MAX(CASE WHEN row_num = total_rows THEN "{value_column}" END) as last_value,
                MIN("{value_column}") as min_value,
                MAX("{value_column}") as max_value,
                AVG("{value_column}") as avg_value
            FROM ordered_data
        )
        SELECT
            first_value,
            last_value,
            min_value,
            max_value,
            avg_value,
            CASE 
                WHEN last_value > first_value THEN '上升'
                WHEN last_value < first_value THEN '下降'
                ELSE '平稳'
            END as trend,
            ((last_value - first_value) / NULLIF(first_value, 0) * 100) as change_rate
        FROM first_last
        """
        
        result = datasource.execute_query(sql)
        
        if not result.success or not result.data:
            return json.dumps({"error": result.error_message or "趋势分析失败"})
        
        data = result.data[0]
        
        return json.dumps({
            "trend": data["trend"],
            "change_rate": f"{data['change_rate']:.2f}%" if data['change_rate'] is not None else "N/A",
            "start_value": float(data["first_value"]) if data["first_value"] is not None else None,
            "end_value": float(data["last_value"]) if data["last_value"] is not None else None,
            "min": float(data["min_value"]) if data["min_value"] is not None else None,
            "max": float(data["max_value"]) if data["max_value"] is not None else None,
            "average": float(data["avg_value"]) if data["avg_value"] is not None else None,
        }, ensure_ascii=False, default=str)
        
    except Exception as e:
        logger.error(f"Trend detection error: {e}")
        return json.dumps({"error": str(e)})


@tool
def generate_summary(datasource_id: int, query_result: str) -> str:
    """
    生成查询结果的自然语言总结

    Args:
        datasource_id: 数据源ID
        query_result: 查询结果的JSON字符串

    Returns:
        自然语言总结
    """
    try:
        results = json.loads(query_result)
        if isinstance(results, list):
            summary = f"查询返回了 {len(results)} 条记录。"
            if len(results) > 0:
                summary += f"第一条记录为：{results[0]}"
        else:
            summary = str(results)
        return summary
    except Exception as e:
        return f"无法生成总结：{str(e)}"









