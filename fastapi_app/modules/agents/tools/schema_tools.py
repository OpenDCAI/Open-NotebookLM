"""
Schema工具 - 获取数据源结构信息

参考JoyAgent的工具设计：每个工具独立文件
- Value Linking：召回与问题相关的列取值，丰富列举例（例: v1, v2）
"""
from langchain_core.tools import tool
from typing import Optional, List
import json
import logging

from .datasource_manager import get_datasource_handler
from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from fastapi_app.modules.rag.schema_embedding import schema_embedding_service
except Exception:
    schema_embedding_service = None

try:
    from fastapi_app.modules.rag.value_linking import value_linking_service
except Exception:
    value_linking_service = None


@tool
def get_datasource_schema(datasource_id: int, format: str = "llm", query: Optional[str] = None) -> str:
    """
    获取数据源的schema信息
    
    改进（参考SQLBot的get_table_schema）：
    1. 使用统一的DataSourceInterface
    2. 支持多种格式输出（LLM/JSON/Markdown）
    3. 包含列统计信息和样本值
    4. 支持多表数据源
    5. **支持语义检索过滤**：当表很多时，提供 `query` 参数只获取相关表

    Args:
        datasource_id: 数据源ID
        format: 输出格式 - "llm"(适合LLM理解), "json"(结构化), "markdown"(文档)
        query: (可选) 用户问题或关键词，用于语义检索最相关的表。如果为None，则返回所有表。

    Returns:
        Schema信息字符串
        
    对于LLM格式，输出类似：
    表: sales
      描述: 销售数据表
      行数: 10,234
      列:
        - "id" (integer) [主键] (例: 1, 2, 3)
        - "product_name" (varchar) [产品名称] (例: iPhone, MacBook, iPad)
        - "amount" (decimal) [销售额] - 范围: 100.0 ~ 50000.0, 平均: 5234.56
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({
            "error": f"数据源 {datasource_id} 未找到。请先上传数据文件。"
        }, ensure_ascii=False)

    try:
        table_filter = None
        if query and getattr(settings, "SCHEMA_ENABLE_SEMANTIC_FILTERING", False) and schema_embedding_service is not None:
            # 使用 RAG 检索相关表
            logger.info(f"Retrieving schema with query: {query}")
            related_tables = schema_embedding_service.retrieve_related_tables(
                datasource_id, query, top_k=5
            )
            if related_tables:
                table_filter = related_tables
                logger.info(f"Filtered tables: {table_filter}")
            else:
                logger.info("No related tables found, returning all tables.")

        # Value Linking：召回与问题相关的列取值（参考 JoyAgent ES 检索）
        if query and not getattr(settings, "SCHEMA_ENABLE_SEMANTIC_FILTERING", False):
            # Cheap lexical fallback: best-effort filter without RAG indexes.
            try:
                tables = datasource.get_tables() if hasattr(datasource, "get_tables") else []
                q = str(query).lower()
                keywords = [k for k in q.replace(",", " ").replace("，", " ").split() if k]
                scored = []
                for t in tables:
                    name = getattr(t, "name", str(t))
                    name_l = str(name).lower()
                    score = 0
                    for kw in keywords:
                        if kw and kw in name_l:
                            score += 2
                    if hasattr(datasource, "get_table_schema"):
                        try:
                            ts = datasource.get_table_schema(name)
                            if ts and hasattr(ts, "columns"):
                                cols = [getattr(c, "name", str(c)).lower() for c in (ts.columns or [])]
                                for kw in keywords:
                                    if any(kw in c for c in cols):
                                        score += 1
                        except Exception:
                            pass
                    if score > 0:
                        scored.append((score, name))
                scored.sort(key=lambda x: x[0], reverse=True)
                table_filter = [n for _, n in scored[:5]] if scored else None
            except Exception:
                table_filter = None

        cell_map = {}
        if query and table_filter and getattr(settings, "SCHEMA_ENABLE_VALUE_LINKING", False) and value_linking_service is not None:
            try:
                tables_for_cells = [t if isinstance(t, str) else getattr(t, "name", str(t)) for t in table_filter]
                cell_map = value_linking_service.retrieve_cells(
                    query, tables_for_cells, datasource_id=datasource_id, top_k=value_linking_service.LOCAL_TOP_K
                )
            except Exception as e:
                logger.debug(f"Value linking in get_datasource_schema: {e}")

        def _table_description_with_value_hints(t_schema, col_value_hints: dict) -> str:
            """生成带 Value Linking 列举例的表描述"""
            lines = [f"表: {t_schema.name}"]
            if t_schema.display_name and t_schema.display_name != t_schema.name:
                lines.append(f"  业务名称: {t_schema.display_name}")
            if t_schema.description or t_schema.comment:
                lines.append(f"  描述: {t_schema.description or t_schema.comment}")
            if t_schema.row_count is not None:
                lines.append(f"  行数: {t_schema.row_count:,}")
            lines.append("  列:")
            for col in t_schema.columns:
                line = f"    - {col.to_llm_description()}"
                key = f"{t_schema.name}.{col.name}"
                if key in col_value_hints and col_value_hints[key]:
                    examples = ", ".join(str(v) for v in col_value_hints[key][:5])
                    if "(例:" not in line:
                        line += f" (例: {examples})"
                lines.append(line)
            return "\n".join(lines)

        # Build structured schema (always include "tables" for downstream JOIN hint discovery).
        try:
            all_tables = datasource.get_tables() if hasattr(datasource, "get_tables") else []
            all_table_names = [getattr(t, "name", str(t)) for t in (all_tables or [])]
        except Exception:
            all_table_names = []

        table_names = list(table_filter or all_table_names)

        table_schemas = []
        tables_struct = []
        for t_name in table_names:
            try:
                t_schema = datasource.get_table_schema(t_name) if hasattr(datasource, "get_table_schema") else None
            except Exception:
                t_schema = None
            if not t_schema:
                continue

            table_schemas.append(t_schema)

            # Convert to structured dict and enrich FK info onto columns (for schema_relationships).
            t_dict = t_schema.to_dict()
            fk_map = {}
            for fk in (t_dict.get("foreign_keys") or []):
                constrained = fk.get("constrained_columns") or []
                referred_table = fk.get("referred_table")
                referred_cols = fk.get("referred_columns") or []
                if not referred_table or not constrained:
                    continue
                for idx, col_name in enumerate(constrained):
                    ref_col = None
                    if idx < len(referred_cols):
                        ref_col = referred_cols[idx]
                    elif referred_cols:
                        ref_col = referred_cols[0]
                    if ref_col:
                        fk_map[str(col_name)] = f"{referred_table}.{ref_col}"

            for col in (t_dict.get("columns") or []):
                cn = col.get("name")
                if cn and cn in fk_map:
                    col["foreign_key"] = fk_map[cn]

            tables_struct.append(t_dict)

        # LLM-friendly schema text (always available)
        llm_parts: List[str] = []
        for t_schema in table_schemas:
            if cell_map:
                llm_parts.append(_table_description_with_value_hints(t_schema, cell_map))
            else:
                llm_parts.append(t_schema.to_llm_description())
        schema_text_llm = "\n\n".join(llm_parts) if llm_parts else datasource.get_all_schemas_text(format="llm")

        schema_field = schema_text_llm
        if format == "json":
            schema_field = json.dumps(tables_struct, ensure_ascii=False, indent=2, default=str)
        elif format == "markdown":
            schema_field = schema_text_llm

        schema_alignment = None
        if query and tables_struct:
            try:
                from fastapi_app.modules.semantics.schema_alignment import infer_schema_alignment

                schema_alignment = infer_schema_alignment(tables_struct, query=str(query))
            except Exception as e:
                logger.debug(f"Schema alignment inference failed: {e}")

        return json.dumps(
            {
                "schema": schema_field,
                "schema_text": schema_text_llm,
                "tables": tables_struct,
                "schema_alignment": schema_alignment,
                "format": format,
                "filtered_by_query": query if table_filter else None,
                "table_count": len(tables_struct),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
            
    except Exception as e:
        logger.error(f"Failed to get schema: {e}")
        return json.dumps({
            "error": f"获取Schema失败: {str(e)}"
        }, ensure_ascii=False)


@tool
def get_table_sample(datasource_id: int, table_name: str, limit: int = 10) -> str:
    """
    获取表的样本数据
    
    快速查看表内容，用于理解数据结构
    
    Args:
        datasource_id: 数据源ID
        table_name: 表名
        limit: 样本行数（默认10）
    
    Returns:
        样本数据JSON字符串
    """
    datasource = get_datasource_handler(datasource_id)
    
    if not datasource:
        return json.dumps({
            "success": False,
            "error_message": f"数据源 {datasource_id} 未找到"
        })
    
    try:
        result = datasource.get_sample_data(table_name, limit=limit)
        
        return json.dumps({
            "success": result.success,
            "table_name": table_name,
            "data": result.data,
            "columns": result.columns,
            "row_count": result.row_count,
        }, ensure_ascii=False, indent=2, default=str)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error_message": str(e)
        })









