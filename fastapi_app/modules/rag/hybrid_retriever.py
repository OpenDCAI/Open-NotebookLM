"""
混合检索器 - BM25 + 向量检索融合

核心设计（参考JoyAgent和CHASE-SQL）：
1. 双路检索 - 同时使用BM25和向量检索
2. 分数融合 - 可配置权重的加权融合
3. 异步并发 - 并行执行两种检索
4. 热度衰减 - 考虑表的使用频率

融合算法：
final_score = α * vector_score + β * bm25_score + γ * heat_score

默认权重：α=0.6, β=0.3, γ=0.1
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi_app.modules.rag.bm25_retriever import bm25_retriever as global_bm25_retriever, BM25Retriever
from fastapi_app.modules.rag.schema_embedding import SchemaEmbeddingService, schema_embedding_service

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果"""
    table_name: str
    vector_score: float = 0.0
    bm25_score: float = 0.0
    heat_score: float = 0.0
    final_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "vector_score": self.vector_score,
            "bm25_score": self.bm25_score,
            "heat_score": self.heat_score,
            "final_score": self.final_score,
        }


class HybridRetriever:
    """
    混合检索器
    
    结合BM25和向量检索的优势：
    - 向量检索：语义相似性，理解同义词和概念
    - BM25检索：精确匹配，关键词召回
    - 热度因子：优先召回常用表
    
    用法：
    ```python
    retriever = HybridRetriever()
    
    # 索引表结构（会同时索引到BM25和向量存储）
    retriever.index_tables(datasource_id=1, tables=[...])
    
    # 混合检索
    results = await retriever.retrieve(
        datasource_id=1,
        query="查询用户订单金额",
        top_k=5
    )
    ```
    """
    
    def __init__(self,
                 vector_weight: float = 0.6,
                 bm25_weight: float = 0.3,
                 heat_weight: float = 0.1,
                 bm25_retriever: Optional[BM25Retriever] = None,
                 schema_service: Optional[SchemaEmbeddingService] = None):
        """
        初始化混合检索器
        
        Args:
            vector_weight: 向量检索权重（默认0.6）
            bm25_weight: BM25检索权重（默认0.3）
            heat_weight: 热度权重（默认0.1）
            bm25_retriever: BM25检索器实例
            schema_service: Schema嵌入服务实例
        """
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.heat_weight = heat_weight
        
        # 确保权重和为1
        total_weight = vector_weight + bm25_weight + heat_weight
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"Weights sum to {total_weight}, normalizing...")
            self.vector_weight /= total_weight
            self.bm25_weight /= total_weight
            self.heat_weight /= total_weight
        
        # 使用全局实例或传入的实例
        self._bm25 = bm25_retriever or global_bm25_retriever
        self._schema_service = schema_service or schema_embedding_service
        
        # 热度统计
        self._heat_stats: Dict[int, Dict[str, Dict[str, Any]]] = {}  # datasource_id -> table_name -> stats
        
        # 线程池（用于并发检索）
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    def index_tables(self, datasource_id: int, tables: List[Dict[str, Any]]):
        """
        索引表结构（同时索引到BM25和向量存储）
        
        Args:
            datasource_id: 数据源ID
            tables: 表信息列表
        """
        # 1. 索引到BM25
        self._bm25.index_tables(datasource_id, tables)
        
        # 2. 索引到向量存储
        self._schema_service.index_tables(datasource_id, tables)
        
        # 3. 初始化热度统计
        if datasource_id not in self._heat_stats:
            self._heat_stats[datasource_id] = {}
        
        for table in tables:
            table_name = table.get("table_name", table.get("name", ""))
            if table_name not in self._heat_stats[datasource_id]:
                self._heat_stats[datasource_id][table_name] = {
                    "access_count": 0,
                    "last_access_time": None,
                }
        
        logger.info(f"Hybrid indexed {len(tables)} tables for datasource {datasource_id}")
    
    async def retrieve(self,
                       datasource_id: int,
                       query: str,
                       top_k: int = 5,
                       include_scores: bool = False) -> List[Dict[str, Any]]:
        """
        混合检索（异步）
        
        Args:
            datasource_id: 数据源ID
            query: 查询文本
            top_k: 返回结果数量
            include_scores: 是否包含详细分数
            
        Returns:
            检索结果列表
        """
        # 并发执行两种检索
        loop = asyncio.get_event_loop()
        
        # 使用线程池执行同步方法
        vector_task = loop.run_in_executor(
            self._executor,
            self._vector_retrieve,
            datasource_id, query, top_k * 2  # 检索更多以便融合
        )
        
        bm25_task = loop.run_in_executor(
            self._executor,
            self._bm25_retrieve,
            datasource_id, query, top_k * 2
        )
        
        # 等待两个任务完成
        vector_results, bm25_results = await asyncio.gather(vector_task, bm25_task)
        
        # 融合结果
        fused_results = self._fuse_results(
            datasource_id, vector_results, bm25_results, top_k
        )
        
        # 格式化输出
        if include_scores:
            return [r.to_dict() for r in fused_results]
        else:
            return [{"table_name": r.table_name} for r in fused_results]
    
    def retrieve_sync(self,
                      datasource_id: int,
                      query: str,
                      top_k: int = 5,
                      include_scores: bool = False) -> List[Dict[str, Any]]:
        """
        混合检索（同步版本）
        
        适用于不在异步上下文中的调用
        """
        # 执行两种检索
        vector_results = self._vector_retrieve(datasource_id, query, top_k * 2)
        bm25_results = self._bm25_retrieve(datasource_id, query, top_k * 2)
        
        # 融合结果
        fused_results = self._fuse_results(
            datasource_id, vector_results, bm25_results, top_k
        )
        
        # 格式化输出
        if include_scores:
            return [r.to_dict() for r in fused_results]
        else:
            return [{"table_name": r.table_name} for r in fused_results]
    
    def _vector_retrieve(self, 
                         datasource_id: int, 
                         query: str, 
                         top_k: int) -> List[Tuple[str, float]]:
        """向量检索"""
        try:
            tables = self._schema_service.retrieve_related_tables(
                datasource_id, query, top_k
            )
            # 向量检索返回的是表名列表，没有分数
            # 我们假设按顺序排列，分数递减
            results = []
            for i, table_name in enumerate(tables):
                # 模拟分数（排名越靠前分数越高）
                score = 1.0 - (i / max(len(tables), 1)) * 0.5
                results.append((table_name, score))
            return results
        except Exception as e:
            logger.error(f"Vector retrieval error: {e}")
            return []
    
    def _bm25_retrieve(self,
                       datasource_id: int,
                       query: str,
                       top_k: int) -> List[Tuple[str, float]]:
        """BM25检索"""
        try:
            results = self._bm25.retrieve(
                datasource_id, query, top_k, include_scores=True
            )
            return [(r["table_name"], r.get("score", 0.0)) for r in results]
        except Exception as e:
            logger.error(f"BM25 retrieval error: {e}")
            return []
    
    def _fuse_results(self,
                      datasource_id: int,
                      vector_results: List[Tuple[str, float]],
                      bm25_results: List[Tuple[str, float]],
                      top_k: int) -> List[RetrievalResult]:
        """
        融合检索结果
        
        融合策略：
        1. 归一化各路检索分数到[0,1]
        2. 加权求和
        3. 按最终分数排序
        """
        # 收集所有表名
        all_tables = set()
        for table_name, _ in vector_results:
            all_tables.add(table_name)
        for table_name, _ in bm25_results:
            all_tables.add(table_name)
        
        if not all_tables:
            return []
        
        # 转换为字典方便查找
        vector_scores = dict(vector_results)
        bm25_scores = dict(bm25_results)
        
        # 归一化分数
        vector_scores = self._normalize_scores(vector_scores)
        bm25_scores = self._normalize_scores(bm25_scores)
        
        # 计算融合分数
        results = []
        for table_name in all_tables:
            v_score = vector_scores.get(table_name, 0.0)
            b_score = bm25_scores.get(table_name, 0.0)
            h_score = self._get_heat_score(datasource_id, table_name)
            
            final_score = (
                self.vector_weight * v_score +
                self.bm25_weight * b_score +
                self.heat_weight * h_score
            )
            
            result = RetrievalResult(
                table_name=table_name,
                vector_score=v_score,
                bm25_score=b_score,
                heat_score=h_score,
                final_score=final_score,
            )
            results.append(result)
        
        # 按最终分数排序
        results.sort(key=lambda x: x.final_score, reverse=True)
        
        # 返回top_k
        return results[:top_k]
    
    def _normalize_scores(self, scores: Dict[str, float]) -> Dict[str, float]:
        """归一化分数到[0,1]"""
        if not scores:
            return {}
        
        max_score = max(scores.values())
        min_score = min(scores.values())
        
        if max_score == min_score:
            return {k: 1.0 for k in scores}
        
        return {
            k: (v - min_score) / (max_score - min_score)
            for k, v in scores.items()
        }
    
    def _get_heat_score(self, datasource_id: int, table_name: str) -> float:
        """获取热度分数"""
        if datasource_id not in self._heat_stats:
            return 0.5  # 默认中等热度
        
        if table_name not in self._heat_stats[datasource_id]:
            return 0.5
        
        stats = self._heat_stats[datasource_id][table_name]
        access_count = stats.get("access_count", 0)
        last_access = stats.get("last_access_time")
        
        # 基于访问次数的热度（使用log平滑）
        import math
        count_score = min(math.log1p(access_count) / 5, 1.0)  # 上限为1
        
        # 基于最近访问时间的热度
        if last_access:
            days_since = (datetime.now() - last_access).days
            recency_score = max(0, 1 - days_since / 30)  # 30天内衰减
        else:
            recency_score = 0.0
        
        # 综合热度
        heat = 0.6 * count_score + 0.4 * recency_score
        return heat
    
    def update_access_stats(self, datasource_id: int, table_name: str):
        """更新表的访问统计"""
        if datasource_id not in self._heat_stats:
            self._heat_stats[datasource_id] = {}
        
        if table_name not in self._heat_stats[datasource_id]:
            self._heat_stats[datasource_id][table_name] = {
                "access_count": 0,
                "last_access_time": None,
            }
        
        self._heat_stats[datasource_id][table_name]["access_count"] += 1
        self._heat_stats[datasource_id][table_name]["last_access_time"] = datetime.now()
        
        # 同时更新BM25检索器的热度
        self._bm25.update_access_stats(datasource_id, table_name)
    
    def set_weights(self, 
                    vector_weight: float = None,
                    bm25_weight: float = None,
                    heat_weight: float = None):
        """动态调整权重"""
        if vector_weight is not None:
            self.vector_weight = vector_weight
        if bm25_weight is not None:
            self.bm25_weight = bm25_weight
        if heat_weight is not None:
            self.heat_weight = heat_weight
        
        # 归一化
        total = self.vector_weight + self.bm25_weight + self.heat_weight
        self.vector_weight /= total
        self.bm25_weight /= total
        self.heat_weight /= total
        
        logger.info(f"Updated weights: vector={self.vector_weight:.2f}, "
                   f"bm25={self.bm25_weight:.2f}, heat={self.heat_weight:.2f}")
    
    def get_retrieval_stats(self) -> Dict[str, Any]:
        """获取检索统计信息"""
        return {
            "weights": {
                "vector": self.vector_weight,
                "bm25": self.bm25_weight,
                "heat": self.heat_weight,
            },
            "bm25_stats": self._bm25.get_stats() if hasattr(self._bm25, 'get_stats') else {},
            "heat_stats_count": sum(len(tables) for tables in self._heat_stats.values()),
        }


# 全局混合检索器实例
hybrid_retriever = HybridRetriever()



