"""
Value Linking - 单元格/取值召回（参考 JoyAgent ES 检索能力）

实现用户问题中的取值与库内实际数据的匹配，提升 WHERE 条件准确性。
- ES 模式：使用 Elasticsearch 全文检索 cell 值（与 JoyAgent 一致）
- 本地回退：从数据源采样低基数列取值，用 BM25/关键词做召回，合并到 Schema 的列举例中
"""
from __future__ import annotations

import os
import re
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# 可选 ES 客户端
_es_client = None


def _get_es_client():
    global _es_client
    if _es_client is not None:
        return _es_client
    host = os.getenv("VALUE_LINKING_ES_HOST") or os.getenv("TR_ES_CONFIGS_HOST")
    if not host:
        return None
    try:
        from elasticsearch import Elasticsearch
        port = os.getenv("VALUE_LINKING_ES_PORT") or os.getenv("TR_ES_CONFIGS_PORT", "9200")
        scheme = os.getenv("VALUE_LINKING_ES_SCHEME", "http")
        user = os.getenv("VALUE_LINKING_ES_USER") or os.getenv("TR_ES_CONFIGS_USER")
        password = os.getenv("VALUE_LINKING_ES_PASSWORD") or os.getenv("TR_ES_CONFIGS_PASSWORD")
        url = f"{scheme}://{host}:{port}"
        if user and password:
            _es_client = Elasticsearch([url], basic_auth=(user, password))
        else:
            _es_client = Elasticsearch([url])
        return _es_client
    except Exception as e:
        logger.warning(f"Value linking ES client init failed: {e}")
        return None


class ValueLinkingService:
    """
    取值召回服务：将用户问题中的词与表中实际取值关联，供 SQL WHERE 使用。
    支持 ES 检索（与 JoyAgent 一致）与本地采样+BM25 回退。
    """

    ES_INDEX = os.getenv("VALUE_LINKING_ES_INDEX", "table_cells")
    LOCAL_TOP_K = 50
    MAX_VALUES_PER_COLUMN = 10

    def __init__(self):
        self._local_index: Dict[int, List[Dict[str, Any]]] = {}  # datasource_id -> [{table, column, value, search_text}, ...]
        self._bm25_index: Dict[int, Any] = {}  # datasource_id -> BM25Okapi (lazy)

    def index_cells_from_datasource(
        self,
        datasource_id: int,
        datasource: Any,
        table_names: Optional[List[str]] = None,
        sample_per_column: int = 20,
    ) -> int:
        """
        从数据源采样低基数列的取值，构建本地 cell 索引（用于无 ES 时的回退）。
        datasource 需实现 get_tables() / get_table_schema() / execute_query()。
        """
        try:
            tables = getattr(datasource, "get_tables", lambda: [])()
            if table_names:
                tables = [t for t in tables if (getattr(t, "name", t) if not isinstance(t, str) else t) in table_names]
            cells: List[Dict[str, Any]] = []
            for tbl in tables:
                tname = getattr(tbl, "name", str(tbl)) if not isinstance(tbl, str) else str(tbl)
                schema = datasource.get_table_schema(tname) if hasattr(datasource, "get_table_schema") else None
                if not schema or not getattr(schema, "columns", None):
                    continue
                for col in schema.columns:
                    cname = getattr(col, "name", "")
                    dtype = (getattr(col, "data_type", None) or getattr(col, "native_type", "") or "").lower()
                    if "int" in dtype or "float" in dtype or "decimal" in dtype or "date" in dtype:
                        continue
                    try:
                        safe_t = re.sub(r"[^a-zA-Z0-9_]", "", tname)
                        safe_c = re.sub(r"[^a-zA-Z0-9_]", "", cname)
                        if not safe_t or not safe_c:
                            continue
                        sql = f'SELECT DISTINCT "{cname}" FROM "{tname}" WHERE "{cname}" IS NOT NULL LIMIT {sample_per_column}'
                        result = datasource.execute_query(sql)
                        if not result or not result.success:
                            continue
                        data = getattr(result, "data", result) if hasattr(result, "data") else (result if isinstance(result, list) else [])
                        col_name_in_row = cname
                        for row in (data or [])[:sample_per_column]:
                            if isinstance(row, dict):
                                val = row.get(col_name_in_row) or row.get(cname)
                            else:
                                val = row[0] if row else None
                            if val is None or str(val).strip() == "":
                                continue
                            vstr = str(val).strip()
                            search_text = f"{tname} {cname} {vstr}"
                            cells.append({
                                "table": tname,
                                "column": cname,
                                "value": vstr,
                                "search_text": search_text,
                            })
                    except Exception as e:
                        logger.debug(f"Value linking sample {tname}.{cname}: {e}")
            self._local_index[datasource_id] = cells
            self._bm25_index.pop(datasource_id, None)
            logger.info(f"Value linking indexed {len(cells)} cells for datasource {datasource_id}")
            return len(cells)
        except Exception as e:
            logger.warning(f"Value linking index_cells_from_datasource failed: {e}")
            return 0

    def retrieve_cells(
        self,
        query: str,
        table_list: List[str],
        datasource_id: Optional[int] = None,
        top_k: int = 50,
    ) -> Dict[str, List[str]]:
        """
        根据用户问题 query 召回与表/列相关的取值。
        返回: { "table.column": ["value1", "value2", ...], ... }
        """
        if not query or not table_list:
            return {}

        es = _get_es_client()
        if es and self.ES_INDEX:
            return self._retrieve_cells_es(es, query, table_list, top_k)

        if datasource_id is not None and datasource_id in self._local_index:
            return self._retrieve_cells_local(datasource_id, query, table_list, top_k)

        return {}

    def _retrieve_cells_es(
        self,
        es: Any,
        query: str,
        table_list: List[str],
        top_k: int,
    ) -> Dict[str, List[str]]:
        """ES 全文检索（与 JoyAgent 一致：match value/searchText，filter by modelCode/tableName）"""
        try:
            body = {
                "size": top_k,
                "query": {
                    "bool": {
                        "must": [{"match": {"value": {"query": query}}}]
                        if hasattr(es, "search") else [{"match": {"searchText": {"query": query}}}],
                        "filter": [{"terms": {"modelCode": table_list}}]
                        if table_list else [],
                    }
                },
                "sort": [{"_score": {"order": "desc"}}],
            }
            if "modelCode" not in str(body):
                body["query"]["bool"]["filter"] = [{"terms": {"tableName": table_list}}]
            resp = es.search(index=self.ES_INDEX, body=body)
            hits = (resp or {}).get("hits", {}).get("hits", [])
            cell_map: Dict[str, List[str]] = {}
            for h in hits:
                src = h.get("_source", {})
                table = src.get("tableName") or src.get("modelCode") or src.get("table", "")
                col = src.get("columnName") or src.get("column", "")
                val = src.get("cellValue") or src.get("value", "")
                if not table or not col or not val:
                    continue
                key = f"{table}.{col}"
                if key not in cell_map:
                    cell_map[key] = []
                if val not in cell_map[key]:
                    cell_map[key].append(val)
            return cell_map
        except Exception as e:
            logger.warning(f"Value linking ES retrieve failed: {e}")
            return {}

    def _retrieve_cells_local(
        self,
        datasource_id: int,
        query: str,
        table_list: List[str],
        top_k: int,
    ) -> Dict[str, List[str]]:
        """本地 BM25 召回"""
        try:
            from rank_bm25 import BM25Okapi
            cells = self._local_index.get(datasource_id, [])
            if not cells:
                return {}
            if datasource_id not in self._bm25_index:
                tokenized = [self._tokenize(c["search_text"]) for c in cells]
                self._bm25_index[datasource_id] = BM25Okapi(tokenized)
            bm25 = self._bm25_index[datasource_id]
            q_tokens = self._tokenize(query)
            scores = bm25.get_scores(q_tokens)
            indices = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
            cell_map: Dict[str, List[str]] = {}
            for i in indices:
                if scores[i] <= 0:
                    continue
                c = cells[i]
                t, col, val = c["table"], c["column"], c["value"]
                if table_list and t not in table_list:
                    continue
                key = f"{t}.{col}"
                if key not in cell_map:
                    cell_map[key] = []
                if val not in cell_map[key]:
                    cell_map[key].append(val)
                if len(cell_map[key]) >= self.MAX_VALUES_PER_COLUMN:
                    pass
            return cell_map
        except ImportError:
            cell_map = {}
            for c in self._local_index.get(datasource_id, []):
                if table_list and c.get("table") not in table_list:
                    continue
                if query in c.get("search_text", "") or query in c.get("value", ""):
                    key = f"{c['table']}.{c['column']}"
                    if key not in cell_map:
                        cell_map[key] = []
                    if c["value"] not in cell_map[key]:
                        cell_map[key].append(c["value"])
            return cell_map
        except Exception as e:
            logger.warning(f"Value linking local retrieve failed: {e}")
            return {}

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        try:
            import jieba
            return list(jieba.cut_for_search(text or ""))
        except Exception:
            return re.findall(r"\w+", (text or ""))


# 单例
value_linking_service = ValueLinkingService()
