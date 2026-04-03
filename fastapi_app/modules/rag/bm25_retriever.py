"""
BM25检索器

实现基于BM25算法的文本检索，用于Schema检索的混合方案。

核心设计：
1. BM25算法 - 基于词频的经典检索算法
2. 中文分词支持 - 使用jieba分词
3. 热度衰减 - 考虑表的使用频率
4. 与向量检索融合 - 混合检索方案

参考：
- JoyAgent的retrieve_schemas_concurrent实现
- CHASE-SQL的多路检索策略
"""

import re
import math
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 尝试导入jieba分词，如果不可用则使用简单分词
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    logger.info("jieba not available, using simple tokenization")

# 尝试导入rank_bm25
try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    logger.warning("rank_bm25 not available, BM25 retrieval will use fallback implementation")


@dataclass
class TableDocument:
    """表文档（用于BM25索引）"""
    table_name: str
    content: str  # 用于检索的文本内容
    tokens: List[str] = field(default_factory=list)  # 分词后的token
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 热度信息
    access_count: int = 0  # 访问次数
    last_access_time: Optional[datetime] = None  # 最后访问时间
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "content": self.content,
            "metadata": self.metadata,
            "access_count": self.access_count,
            "last_access_time": self.last_access_time.isoformat() if self.last_access_time else None,
        }


class BM25Retriever:
    """
    BM25检索器
    
    用法：
    ```python
    retriever = BM25Retriever()
    
    # 索引表结构
    retriever.index_tables(datasource_id=1, tables=[
        {"table_name": "users", "comment": "用户表", "columns": [...]},
        {"table_name": "orders", "comment": "订单表", "columns": [...]},
    ])
    
    # 检索相关表
    results = retriever.retrieve(
        datasource_id=1, 
        query="查询用户的订单信息", 
        top_k=5
    )
    ```
    """
    
    def __init__(self, 
                 k1: float = 1.5, 
                 b: float = 0.75,
                 use_heat_decay: bool = True,
                 heat_decay_days: int = 7):
        """
        初始化BM25检索器
        
        Args:
            k1: BM25的k1参数，控制词频饱和度（默认1.5）
            b: BM25的b参数，控制文档长度归一化（默认0.75）
            use_heat_decay: 是否使用热度衰减
            heat_decay_days: 热度衰减周期（天）
        """
        self.k1 = k1
        self.b = b
        self.use_heat_decay = use_heat_decay
        self.heat_decay_days = heat_decay_days
        
        # 每个数据源的索引
        self._indexes: Dict[int, Dict[str, Any]] = {}  # datasource_id -> index data
        
        # 停用词表
        self._stopwords = self._load_stopwords()
        
    def _load_stopwords(self) -> set:
        """加载停用词表"""
        # 常用停用词
        chinese_stopwords = {
            '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
            '这', '他', '那', '中', '大', '来', '可以', '多', '个', '时', '里', '能', '下',
            '以', '所有', '与', '从', '或', '对', '但', '让', '被', '给', '通过', '及', '等',
            '查询', '统计', '计算', '获取', '显示', '列出', '找出', '返回',
        }
        english_stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
            'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'select', 'from',
            'where', 'get', 'show', 'list', 'find', 'query',
        }
        return chinese_stopwords | english_stopwords
    
    def _tokenize(self, text: str) -> List[str]:
        """
        分词
        
        支持中英文混合分词
        """
        if not text:
            return []
        
        text = text.lower()
        
        # 使用jieba分词（如果可用）
        if JIEBA_AVAILABLE:
            # 中文分词
            tokens = list(jieba.cut(text))
        else:
            # 简单分词：按空格和标点分割
            tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', text)
        
        # 过滤停用词和短词
        tokens = [
            t.strip() for t in tokens 
            if t.strip() and len(t.strip()) > 1 and t.strip() not in self._stopwords
        ]
        
        return tokens
    
    def _build_table_content(self, table: Dict[str, Any]) -> str:
        """
        构建表的检索文本
        
        包含：表名、表注释、列名、列注释、样本值
        """
        parts = []
        
        # 表名
        table_name = table.get("table_name", "")
        parts.append(table_name)
        
        # 表注释
        if table.get("comment"):
            parts.append(table["comment"])
        
        # 表描述
        if table.get("description"):
            parts.append(table["description"])
        
        # 列信息
        for col in table.get("columns", []):
            col_name = col.get("name", "") if isinstance(col, dict) else str(col)
            parts.append(col_name)
            
            if isinstance(col, dict):
                if col.get("comment"):
                    parts.append(col["comment"])
                if col.get("description"):
                    parts.append(col["description"])
                # 样本值（有助于值匹配）
                for sample in col.get("sample_values", [])[:3]:
                    parts.append(str(sample))
        
        return " ".join(parts)
    
    def index_tables(self, datasource_id: int, tables: List[Dict[str, Any]]):
        """
        索引表结构
        
        Args:
            datasource_id: 数据源ID
            tables: 表信息列表
        """
        documents = []
        
        for table in tables:
            table_name = table.get("table_name", table.get("name", ""))
            content = self._build_table_content(table)
            tokens = self._tokenize(content)
            
            doc = TableDocument(
                table_name=table_name,
                content=content,
                tokens=tokens,
                metadata={
                    "datasource_id": datasource_id,
                    "column_count": len(table.get("columns", [])),
                    "raw_info": table,
                }
            )
            documents.append(doc)
        
        # 构建BM25索引
        if BM25_AVAILABLE and documents:
            corpus = [doc.tokens for doc in documents]
            bm25 = BM25Okapi(corpus, k1=self.k1, b=self.b)
            
            self._indexes[datasource_id] = {
                "bm25": bm25,
                "documents": documents,
                "corpus": corpus,
            }
        else:
            # 使用简单的TF-IDF回退实现
            self._indexes[datasource_id] = {
                "bm25": None,
                "documents": documents,
                "corpus": [doc.tokens for doc in documents],
            }
        
        logger.info(f"BM25 indexed {len(documents)} tables for datasource {datasource_id}")
    
    def retrieve(self, 
                 datasource_id: int, 
                 query: str, 
                 top_k: int = 5,
                 include_scores: bool = False) -> List[Dict[str, Any]]:
        """
        检索相关表
        
        Args:
            datasource_id: 数据源ID
            query: 查询文本
            top_k: 返回结果数量
            include_scores: 是否包含分数
            
        Returns:
            检索结果列表，每项包含 table_name 和可选的 score
        """
        if datasource_id not in self._indexes:
            logger.warning(f"No BM25 index for datasource {datasource_id}")
            return []
        
        index_data = self._indexes[datasource_id]
        documents = index_data["documents"]
        
        if not documents:
            return []
        
        # 分词
        query_tokens = self._tokenize(query)
        
        if not query_tokens:
            # 如果没有有效token，返回空
            return []
        
        # 计算分数
        if BM25_AVAILABLE and index_data["bm25"]:
            scores = index_data["bm25"].get_scores(query_tokens)
        else:
            # 简单TF-IDF回退
            scores = self._simple_tfidf_scores(query_tokens, index_data["corpus"])
        
        # 应用热度衰减
        if self.use_heat_decay:
            scores = self._apply_heat_decay(scores, documents)
        
        # 排序并获取top_k
        scored_docs = list(zip(documents, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for doc, score in scored_docs[:top_k]:
            result = {"table_name": doc.table_name}
            if include_scores:
                result["score"] = float(score)
            results.append(result)
        
        logger.info(f"BM25 retrieved {len(results)} tables for query: '{query[:50]}...'")
        return results
    
    def _simple_tfidf_scores(self, query_tokens: List[str], corpus: List[List[str]]) -> List[float]:
        """简单的TF-IDF实现（BM25不可用时的回退）"""
        # 计算IDF
        doc_count = len(corpus)
        idf = {}
        for tokens in corpus:
            for token in set(tokens):
                idf[token] = idf.get(token, 0) + 1
        
        for token in idf:
            idf[token] = math.log((doc_count + 1) / (idf[token] + 1))
        
        # 计算每个文档的分数
        scores = []
        for doc_tokens in corpus:
            score = 0.0
            doc_len = len(doc_tokens)
            
            # 计算TF
            tf = defaultdict(int)
            for token in doc_tokens:
                tf[token] += 1
            
            # 计算分数
            for qtoken in query_tokens:
                if qtoken in tf:
                    token_tf = tf[qtoken] / (doc_len + 1)
                    token_idf = idf.get(qtoken, 0)
                    score += token_tf * token_idf
            
            scores.append(score)
        
        return scores
    
    def _apply_heat_decay(self, scores: List[float], documents: List[TableDocument]) -> List[float]:
        """应用热度衰减"""
        now = datetime.now()
        decay_threshold = timedelta(days=self.heat_decay_days)
        
        adjusted_scores = []
        for score, doc in zip(scores, documents):
            # 热度因子（基于访问次数）
            heat_factor = 1.0 + math.log1p(doc.access_count) * 0.1
            
            # 时间衰减（最近访问的权重更高）
            if doc.last_access_time:
                time_diff = now - doc.last_access_time
                if time_diff < decay_threshold:
                    recency_factor = 1.0 + (1 - time_diff.days / self.heat_decay_days) * 0.2
                else:
                    recency_factor = 1.0
            else:
                recency_factor = 1.0
            
            adjusted_score = score * heat_factor * recency_factor
            adjusted_scores.append(adjusted_score)
        
        return adjusted_scores
    
    def update_access_stats(self, datasource_id: int, table_name: str):
        """更新表的访问统计（用于热度计算）"""
        if datasource_id not in self._indexes:
            return
        
        documents = self._indexes[datasource_id]["documents"]
        for doc in documents:
            if doc.table_name == table_name:
                doc.access_count += 1
                doc.last_access_time = datetime.now()
                break
    
    def clear_index(self, datasource_id: Optional[int] = None):
        """清除索引"""
        if datasource_id is not None:
            if datasource_id in self._indexes:
                del self._indexes[datasource_id]
                logger.info(f"Cleared BM25 index for datasource {datasource_id}")
        else:
            self._indexes.clear()
            logger.info("Cleared all BM25 indexes")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "indexed_datasources": len(self._indexes),
            "datasources": {}
        }
        
        for ds_id, index_data in self._indexes.items():
            stats["datasources"][ds_id] = {
                "table_count": len(index_data["documents"]),
                "bm25_available": index_data["bm25"] is not None,
            }
        
        return stats


# 全局BM25检索器实例
bm25_retriever = BM25Retriever()




