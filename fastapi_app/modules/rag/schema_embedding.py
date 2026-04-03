"""
Schema Embedding Service - 增强版

P0 优化：预计算 Embedding
- 连接数据源时自动索引
- 支持增量更新
- 缓存机制避免重复计算
- 异步批量处理

参考 SQLBot 的 Embedding 预计算策略
"""

import logging
import hashlib
import json
import asyncio
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from langchain_core.documents import Document
from .vector_store import vector_store_manager

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingCache:
    """Embedding 缓存条目"""
    table_name: str
    content_hash: str  # 内容哈希，用于检测变化
    indexed_at: datetime
    datasource_id: int


class SchemaEmbeddingService:
    """
    增强版 Schema Embedding 服务
    
    特性：
    1. 预计算：连接时自动索引
    2. 增量更新：只更新变化的表
    3. 批量处理：并行计算 Embedding
    4. 缓存管理：避免重复计算
    """
    
    def __init__(self, batch_size: int = 10, max_workers: int = 4):
        self.vector_store = vector_store_manager.get_vector_store("table_schema")
        self.batch_size = batch_size
        self.max_workers = max_workers
        
        # 缓存：datasource_id -> {table_name: EmbeddingCache}
        self._cache: Dict[int, Dict[str, EmbeddingCache]] = {}
        
        # 索引状态
        self._indexed_datasources: Set[int] = set()
        
        # 线程池
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        
    def _compute_content_hash(self, table: Dict[str, Any]) -> str:
        """计算表内容的哈希值（用于检测变化）"""
        # 规范化表结构
        normalized = {
            "table_name": table.get("table_name", ""),
            "comment": table.get("comment", ""),
            "columns": sorted(
                [
                    {
                        "name": c.get("name", ""),
                        "type": c.get("type", ""),
                        "comment": c.get("comment", "")
                    }
                    for c in table.get("columns", [])
                ],
                key=lambda x: x["name"]
            )
        }
        content = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode()).hexdigest()
    
    def _build_rich_content(self, table: Dict[str, Any]) -> str:
        """
        构建富文本 Embedding 内容
        
        增强：包含更多语义信息
        """
        table_name = table.get("table_name", "")
        table_comment = table.get("comment", "")
        
        parts = []
        
        # 表级信息
        parts.append(f"Table: {table_name}")
        if table_comment:
            parts.append(f"Description: {table_comment}")
        
        # 列级信息（详细）
        columns_desc = []
        for col in table.get("columns", []):
            col_name = col.get("name", "")
            col_type = col.get("type", "")
            col_comment = col.get("comment", "")
            
            col_str = f"{col_name} ({col_type})"
            if col_comment:
                col_str += f" - {col_comment}"
            columns_desc.append(col_str)
        
        if columns_desc:
            parts.append(f"Columns: {'; '.join(columns_desc)}")
        
        # 样本值（如果有）
        sample_values = table.get("sample_values", {})
        if sample_values:
            sample_strs = [f"{k}: {v}" for k, v in list(sample_values.items())[:5]]
            parts.append(f"Sample values: {', '.join(sample_strs)}")
        
        return " | ".join(parts)
    
    def is_indexed(self, datasource_id: int) -> bool:
        """检查数据源是否已索引"""
        return datasource_id in self._indexed_datasources
    
    def get_index_stats(self, datasource_id: int) -> Dict[str, Any]:
        """获取索引统计信息"""
        if datasource_id not in self._cache:
            return {"indexed": False, "table_count": 0}
        
        cache = self._cache[datasource_id]
        return {
            "indexed": True,
            "table_count": len(cache),
            "tables": list(cache.keys()),
            "indexed_at": min(
                (c.indexed_at for c in cache.values()),
                default=None
            )
        }
    
    def index_tables(self, datasource_id: int, tables: List[Dict[str, Any]], 
                     force_reindex: bool = False) -> Dict[str, Any]:
        """
        索引表结构（同步版本，带增量更新）
        
        Args:
            datasource_id: 数据源ID
            tables: 表信息列表
            force_reindex: 是否强制重建索引
            
        Returns:
            索引结果统计
        """
        stats = {
            "total": len(tables),
            "new": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0
        }

        if not self.vector_store:
            logger.warning(
                f"SchemaEmbeddingService: vector store unavailable; skip embedding index (datasource={datasource_id})"
            )
            stats["errors"] = len(tables)
            return stats
        
        # 初始化缓存
        if datasource_id not in self._cache:
            self._cache[datasource_id] = {}
        
        cache = self._cache[datasource_id]
        documents_to_add = []
        
        for table in tables:
            table_name = table.get("table_name", table.get("name", ""))
            if not table_name:
                stats["errors"] += 1
                continue
            
            # 计算内容哈希
            content_hash = self._compute_content_hash(table)
            
            # 检查是否需要更新
            if not force_reindex and table_name in cache:
                if cache[table_name].content_hash == content_hash:
                    stats["skipped"] += 1
                    continue
                else:
                    stats["updated"] += 1
            else:
                stats["new"] += 1
            
            # 构建文档
            page_content = self._build_rich_content(table)
            metadata = {
                "datasource_id": datasource_id,
                "table_name": table_name,
                "content_hash": content_hash,
                "indexed_at": datetime.now().isoformat(),
                "column_count": len(table.get("columns", [])),
            }
            
            documents_to_add.append(Document(
                page_content=page_content,
                metadata=metadata
            ))
            
            # 更新缓存
            cache[table_name] = EmbeddingCache(
                table_name=table_name,
                content_hash=content_hash,
                indexed_at=datetime.now(),
                datasource_id=datasource_id
            )
        
        # 批量添加文档
        if documents_to_add:
            try:
                # 分批处理
                for i in range(0, len(documents_to_add), self.batch_size):
                    batch = documents_to_add[i:i + self.batch_size]
                    self.vector_store.add_documents(batch)
                    
                logger.info(f"Indexed {len(documents_to_add)} tables for datasource {datasource_id}")
            except Exception as e:
                logger.error(f"Error indexing tables: {e}")
                stats["errors"] += len(documents_to_add)
        
        self._indexed_datasources.add(datasource_id)
        
        return stats
    
    async def index_tables_async(self, datasource_id: int, 
                                  tables: List[Dict[str, Any]],
                                  force_reindex: bool = False) -> Dict[str, Any]:
        """
        异步索引表结构（P0 优化核心）
        
        使用线程池并行计算 Embedding
        """
        loop = asyncio.get_event_loop()
        
        # 在线程池中执行同步索引
        result = await loop.run_in_executor(
            self._executor,
            lambda: self.index_tables(datasource_id, tables, force_reindex)
        )
        
        return result
    
    def precompute_embeddings(self, datasource_id: int, 
                               tables: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        预计算 Embedding（数据源连接时调用）
        
        这是 P0 优化的入口点：
        - 在数据源连接成功后立即调用
        - 返回索引统计信息
        - 支持进度回调
        """
        logger.info(f"Precomputing embeddings for datasource {datasource_id} ({len(tables)} tables)")
        
        start_time = datetime.now()
        stats = self.index_tables(datasource_id, tables, force_reindex=False)
        elapsed = (datetime.now() - start_time).total_seconds()
        
        stats["elapsed_seconds"] = elapsed
        stats["tables_per_second"] = len(tables) / elapsed if elapsed > 0 else 0
        
        logger.info(f"Precompute completed: {stats}")
        return stats
    
    def retrieve_related_tables(self, datasource_id: int, question: str,
                                 top_k: int = 5) -> List[str]:
        """
        检索相关表 (增强版: 向量检索 + 关键词匹配)

        Returns:
            List[str]: 相关表名列表
        """
        if not self.vector_store:
            # Degraded retrieval: BM25 + keyword mapping
            try:
                from fastapi_app.modules.rag.bm25_retriever import bm25_retriever

                bm25_tables = [
                    r.get("table_name")
                    for r in bm25_retriever.retrieve(datasource_id, question, top_k=top_k)
                    if r.get("table_name")
                ]
            except Exception:
                bm25_tables = []

            keyword_tables = self._keyword_match_tables(datasource_id, question)
            unique: List[str] = []
            for t in bm25_tables:
                if t not in unique:
                    unique.append(t)
            for t in keyword_tables:
                if t not in unique:
                    unique.append(t)
            return unique[:top_k]

        try:
            # 1. 向量检索
            filter_dict = {"datasource_id": datasource_id}

            docs = self.vector_store.similarity_search(
                question,
                k=top_k * 2,  # 多检索一些用于融合
                filter=filter_dict
            )

            vector_tables = [doc.metadata["table_name"] for doc in docs]

            # 2. 关键词匹配补充 (解决中文语义偏差问题)
            keyword_tables = self._keyword_match_tables(datasource_id, question)

            # 3. 融合: 向量结果优先, 关键词结果补充
            unique_tables = []
            for t in vector_tables:
                if t not in unique_tables:
                    unique_tables.append(t)
            for t in keyword_tables:
                if t not in unique_tables:
                    unique_tables.append(t)

            result = unique_tables[:top_k]
            logger.info(f"Retrieved tables for '{question}': {result}")
            return result

        except Exception as e:
            logger.error(f"Error retrieving tables: {e}")
            return []

    def _keyword_match_tables(self, datasource_id: int, question: str) -> List[str]:
        """
        关键词匹配表 (补充向量检索的不足)

        中文关键词 → 英文列名/表名 映射
        """
        # 关键词映射表
        KEYWORD_TABLE_MAP = {
            # 商品/产品
            "商品": ["products", "order_items", "sales_analytics"],
            "产品": ["products", "order_items", "sales_analytics"],
            "品牌": ["products", "sales_analytics"],
            "分类": ["categories", "products"],
            "SKU": ["products"],
            # 库存
            "库存": ["products", "inventory_logs"],
            "stock": ["products", "inventory_logs"],
            "入库": ["inventory_logs"],
            "出库": ["inventory_logs"],
            # 订单
            "订单": ["orders", "order_items"],
            "销售": ["orders", "sales_analytics", "order_items"],
            "销量": ["orders", "order_items", "sales_analytics"],
            "销售额": ["orders", "sales_analytics"],
            # 客户
            "客户": ["customers", "orders"],
            "用户": ["customers"],
            "VIP": ["customers"],
            "来源": ["customers"],
            # 促销
            "促销": ["promotions"],
            "活动": ["promotions"],
            "优惠": ["promotions", "orders"],
            "折扣": ["promotions", "orders"],
            # 评价
            "评价": ["reviews"],
            "评分": ["reviews"],
            "评论": ["reviews"],
            # 供应商
            "供应商": ["suppliers", "products"],
            "供货": ["suppliers"],
            # 利润
            "利润": ["sales_analytics"],
            "成本": ["products", "sales_analytics"],
            "毛利": ["sales_analytics"],
        }

        question_lower = question.lower()
        matched_tables = []

        for keyword, tables in KEYWORD_TABLE_MAP.items():
            if keyword in question_lower:
                for t in tables:
                    if t not in matched_tables:
                        matched_tables.append(t)

        return matched_tables
    
    def retrieve_with_scores(self, datasource_id: int, question: str,
                              top_k: int = 5) -> List[Dict[str, Any]]:
        """
        检索相关表（带相似度分数）
        
        用于混合检索的分数融合
        """
        if not self.vector_store:
            # Best-effort degraded: keyword match only.
            tables = self._keyword_match_tables(datasource_id, question)[:top_k]
            return [{"table_name": t, "score": 0.0, "content": ""} for t in tables]

        try:
            filter_dict = {"datasource_id": datasource_id}
            
            # 使用 similarity_search_with_score
            results = self.vector_store.similarity_search_with_score(
                question,
                k=top_k,
                filter=filter_dict
            )
            
            return [
                {
                    "table_name": doc.metadata["table_name"],
                    "score": 1.0 / (1.0 + score),  # 转换距离为相似度
                    "content": doc.page_content
                }
                for doc, score in results
            ]
            
        except Exception as e:
            logger.error(f"Error retrieving with scores: {e}")
            return []
    
    def clear_index(self, datasource_id: Optional[int] = None):
        """清除索引"""
        if datasource_id is not None:
            if datasource_id in self._cache:
                del self._cache[datasource_id]
            self._indexed_datasources.discard(datasource_id)
            logger.info(f"Cleared index for datasource {datasource_id}")
        else:
            self._cache.clear()
            self._indexed_datasources.clear()
            logger.info("Cleared all indexes")


# 全局实例
schema_embedding_service = SchemaEmbeddingService()
