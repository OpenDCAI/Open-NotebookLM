"""
Value Linking - 列值检索（ES 式能力）

参考 JoyAgent 的 ES 检索：对列的实际取值建立索引，支持「用户问法 -> 表.列.值」的链接，
用于 WHERE 条件中的值匹配（如「北京」-> city='北京'）。

核心设计：
1. 从表结构的 sample_values 及可选样本数据构建 (table, column, value) 文档
2. BM25 检索：用户 query 与 value/列名/表名 匹配，返回 (table_name, column_name, value, score)
3. 与 Schema 检索互补：Schema 召回表/列，Value Linking 召回具体取值
"""

import re
import math
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False


@dataclass
class ValueDocument:
    """列值文档（用于 BM25 索引）"""
    table_name: str
    column_name: str
    value: Any  # 原始值
    value_str: str  # 用于检索的字符串
    content: str  # 表名 + 列名 + 值，用于分词检索
    tokens: List[str] = field(default_factory=list)

    def to_linking(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "column_name": self.column_name,
            "value": self.value,
            "value_str": self.value_str,
        }


class ValueRetriever:
    """
    列值检索器（Value Linking，ES 式能力）

    用法：
    ```python
    retriever = ValueRetriever()
    retriever.index_tables(datasource_id=1, tables=[...])  # 与 hybrid 共用同一 tables
    results = retriever.retrieve(datasource_id=1, query="北京 上海", top_k=10)
    # -> [{"table_name": "city_dim", "column_name": "city_name", "value": "北京", "score": 0.8}, ...]
    ```
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._indexes: Dict[int, Dict[str, Any]] = {}  # datasource_id -> {bm25, documents, corpus}
        self._stopwords = self._load_stopwords()

    def _load_stopwords(self) -> set:
        stop = {
            '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
            '这', '他', '那', '中', '大', '来', '可以', '多', '个', '时', '里', '能', '下',
            '查询', '统计', '显示', '列出', '找出', '返回', 'get', 'show', 'list', 'find',
        }
        return stop

    def _tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        text = str(text).lower().strip()
        if JIEBA_AVAILABLE:
            tokens = list(jieba.cut(text))
        else:
            tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', text)
        return [t.strip() for t in tokens if t.strip() and len(t.strip()) >= 1 and t.strip() not in self._stopwords]

    def _build_value_documents(self, tables: List[Dict[str, Any]]) -> List[ValueDocument]:
        """从 tables 的 columns.sample_values 和 table.sample_values 构建列值文档"""
        documents = []
        seen = set()  # (table_name, column_name, value_str) 去重

        for table in tables:
            table_name = table.get("table_name", table.get("name", ""))

            # 表级 sample_values（部分数据源提供）
            table_samples = table.get("sample_values", {})
            if isinstance(table_samples, dict):
                for col_name, vals in table_samples.items():
                    if isinstance(vals, list):
                        for v in vals[:20]:
                            self._add_value_doc(documents, seen, table_name, col_name, v)
                    else:
                        self._add_value_doc(documents, seen, table_name, col_name, vals)

            for col in table.get("columns", []):
                col_name = col.get("name", "") if isinstance(col, dict) else str(col)
                if not col_name:
                    continue
                samples = col.get("sample_values", []) if isinstance(col, dict) else []
                if not samples and isinstance(col, dict) and col.get("comment"):
                    # 无样本时用列注释参与检索
                    self._add_value_doc(documents, seen, table_name, col_name, col.get("comment", ""))
                for v in samples[:25]:
                    self._add_value_doc(documents, seen, table_name, col_name, v)

        return documents

    def _add_value_doc(self, documents: List[ValueDocument], seen: set,
                       table_name: str, column_name: str, value: Any) -> None:
        value_str = str(value).strip() if value is not None else ""
        if not value_str or len(value_str) > 200:
            return
        key = (table_name, column_name, value_str[:100])
        if key in seen:
            return
        seen.add(key)
        content = f"{table_name} {column_name} {value_str}"
        tokens = self._tokenize(content)
        if not tokens:
            return
        documents.append(ValueDocument(
            table_name=table_name,
            column_name=column_name,
            value=value,
            value_str=value_str,
            content=content,
            tokens=tokens,
        ))

    def index_tables(self, datasource_id: int, tables: List[Dict[str, Any]]) -> None:
        """索引列值，与 hybrid_retriever 共用同一 tables 结构"""
        documents = self._build_value_documents(tables)
        if not documents:
            self._indexes[datasource_id] = {"bm25": None, "documents": [], "corpus": []}
            logger.info(f"ValueRetriever: no value docs for datasource {datasource_id}")
            return

        corpus = [doc.tokens for doc in documents]
        if BM25_AVAILABLE:
            bm25 = BM25Okapi(corpus, k1=self.k1, b=self.b)
            self._indexes[datasource_id] = {"bm25": bm25, "documents": documents, "corpus": corpus}
        else:
            self._indexes[datasource_id] = {"bm25": None, "documents": documents, "corpus": corpus}

        logger.info(f"ValueRetriever indexed {len(documents)} value docs for datasource {datasource_id}")

    def retrieve(self,
                 datasource_id: int,
                 query: str,
                 top_k: int = 10,
                 include_scores: bool = True) -> List[Dict[str, Any]]:
        """
        按用户 query 检索列值，用于 Value Linking。

        Returns:
            [{"table_name", "column_name", "value", "value_str", "score"?}, ...]
        """
        if datasource_id not in self._indexes:
            return []
        index_data = self._indexes[datasource_id]
        documents = index_data["documents"]
        if not documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        if BM25_AVAILABLE and index_data["bm25"]:
            scores = index_data["bm25"].get_scores(query_tokens)
        else:
            scores = self._simple_tfidf_scores(query_tokens, index_data["corpus"])

        scored = list(zip(documents, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for doc, score in scored[:top_k]:
            if score <= 0:
                continue
            item = doc.to_linking()
            if include_scores:
                item["score"] = float(score)
            results.append(item)
        return results

    def _simple_tfidf_scores(self, query_tokens: List[str], corpus: List[List[str]]) -> List[float]:
        doc_count = len(corpus)
        idf = defaultdict(lambda: 0)
        for tokens in corpus:
            for t in set(tokens):
                idf[t] += 1
        for t in idf:
            idf[t] = math.log((doc_count + 1) / (idf[t] + 1))
        scores = []
        for doc_tokens in corpus:
            score = 0.0
            tf = defaultdict(int)
            for t in doc_tokens:
                tf[t] += 1
            for q in query_tokens:
                if q in tf:
                    score += (tf[q] / (len(doc_tokens) + 1)) * idf.get(q, 0)
            scores.append(score)
        return scores

    def clear_index(self, datasource_id: int) -> None:
        if datasource_id in self._indexes:
            del self._indexes[datasource_id]
            logger.info(f"ValueRetriever cleared index for datasource {datasource_id}")


# 全局列值检索器实例（与 hybrid 共用 index_tables 的 tables，需在 index 时同时调用）
value_retriever = ValueRetriever()
