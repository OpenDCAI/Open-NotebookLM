"""
异步并发检索器

核心设计（参考JoyAgent的retrieve_schemas_concurrent）：
1. 异步并发 - 使用asyncio并发执行多个检索任务
2. 信号量控制 - 限制最大并发数（默认10）
3. 超时控制 - 单个任务超时自动取消
4. 错误容忍 - 部分失败不影响整体结果

性能目标：
- 响应速度提升50%+
- 支持10并发检索
- 单任务30秒超时
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable, TypeVar, Coroutine
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from functools import partial

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class RetrievalTask:
    """检索任务"""
    task_id: str
    datasource_id: int
    query: str
    task_type: str  # "vector", "bm25", "hybrid"
    priority: int = 0  # 优先级（数字越小优先级越高）
    
    def __hash__(self):
        return hash(self.task_id)


@dataclass
class RetrievalTaskResult:
    """检索任务结果"""
    task_id: str
    success: bool
    results: List[Dict[str, Any]]
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "results": self.results,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }


class AsyncRetriever:
    """
    异步并发检索器
    
    用法：
    ```python
    retriever = AsyncRetriever(max_concurrent=10, timeout_seconds=30)
    
    # 并发执行多个检索任务
    tasks = [
        RetrievalTask(task_id="1", datasource_id=1, query="用户订单", task_type="hybrid"),
        RetrievalTask(task_id="2", datasource_id=2, query="产品销售", task_type="hybrid"),
    ]
    
    results = await retriever.retrieve_concurrent(tasks)
    ```
    """
    
    def __init__(self,
                 max_concurrent: int = 10,
                 timeout_seconds: float = 30.0,
                 thread_pool_size: int = 4):
        """
        初始化异步检索器
        
        Args:
            max_concurrent: 最大并发数
            timeout_seconds: 单个任务超时时间（秒）
            thread_pool_size: 线程池大小（用于执行同步操作）
        """
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._executor = ThreadPoolExecutor(max_workers=thread_pool_size)
        
        # 统计信息
        self._stats = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "timeout_tasks": 0,
            "total_time_ms": 0.0,
        }
    
    async def retrieve_concurrent(self,
                                   tasks: List[RetrievalTask],
                                   retrieval_func: Callable) -> List[RetrievalTaskResult]:
        """
        并发执行多个检索任务
        
        Args:
            tasks: 检索任务列表
            retrieval_func: 检索函数，签名为 (datasource_id, query, top_k) -> List[Dict]
            
        Returns:
            检索结果列表
        """
        if not tasks:
            return []
        
        # 创建信号量
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # 按优先级排序
        sorted_tasks = sorted(tasks, key=lambda t: t.priority)
        
        # 创建异步任务
        async_tasks = [
            self._execute_with_semaphore(task, retrieval_func)
            for task in sorted_tasks
        ]
        
        # 并发执行
        start_time = datetime.now()
        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        total_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # 处理结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # 任务失败
                final_results.append(RetrievalTaskResult(
                    task_id=sorted_tasks[i].task_id,
                    success=False,
                    results=[],
                    error=str(result),
                ))
                self._stats["failed_tasks"] += 1
            elif isinstance(result, RetrievalTaskResult):
                final_results.append(result)
                if result.success:
                    self._stats["successful_tasks"] += 1
                else:
                    self._stats["failed_tasks"] += 1
            else:
                # 未知结果类型
                final_results.append(RetrievalTaskResult(
                    task_id=sorted_tasks[i].task_id,
                    success=False,
                    results=[],
                    error="Unknown result type",
                ))
        
        self._stats["total_tasks"] += len(tasks)
        self._stats["total_time_ms"] += total_time
        
        logger.info(f"Concurrent retrieval completed: {len(tasks)} tasks in {total_time:.2f}ms")
        return final_results
    
    async def _execute_with_semaphore(self,
                                       task: RetrievalTask,
                                       retrieval_func: Callable) -> RetrievalTaskResult:
        """使用信号量限制并发执行任务"""
        async with self._semaphore:
            return await self._execute_task(task, retrieval_func)
    
    async def _execute_task(self,
                            task: RetrievalTask,
                            retrieval_func: Callable) -> RetrievalTaskResult:
        """执行单个检索任务（带超时控制）"""
        start_time = datetime.now()
        
        try:
            # 使用asyncio.wait_for实现超时控制
            result = await asyncio.wait_for(
                self._run_retrieval(task, retrieval_func),
                timeout=self.timeout_seconds
            )
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return RetrievalTaskResult(
                task_id=task.task_id,
                success=True,
                results=result,
                execution_time_ms=execution_time,
            )
            
        except asyncio.TimeoutError:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            self._stats["timeout_tasks"] += 1
            logger.warning(f"Task {task.task_id} timeout after {self.timeout_seconds}s")
            
            return RetrievalTaskResult(
                task_id=task.task_id,
                success=False,
                results=[],
                error=f"Timeout after {self.timeout_seconds}s",
                execution_time_ms=execution_time,
            )
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            logger.error(f"Task {task.task_id} failed: {e}")
            
            return RetrievalTaskResult(
                task_id=task.task_id,
                success=False,
                results=[],
                error=str(e),
                execution_time_ms=execution_time,
            )
    
    async def _run_retrieval(self,
                             task: RetrievalTask,
                             retrieval_func: Callable) -> List[Dict[str, Any]]:
        """运行检索函数（在线程池中执行同步函数）"""
        loop = asyncio.get_event_loop()
        
        # 使用线程池执行同步检索函数
        func = partial(retrieval_func, task.datasource_id, task.query)
        result = await loop.run_in_executor(self._executor, func)
        
        return result if result else []
    
    async def retrieve_schemas_concurrent(self,
                                           queries: List[Dict[str, Any]],
                                           retrieval_func: Callable,
                                           top_k: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """
        并发检索多个Schema查询（JoyAgent风格接口）
        
        Args:
            queries: 查询列表，每项包含 {"datasource_id": int, "query": str}
            retrieval_func: 检索函数
            top_k: 每个查询返回的结果数
            
        Returns:
            查询ID -> 结果列表的映射
        """
        tasks = [
            RetrievalTask(
                task_id=str(i),
                datasource_id=q["datasource_id"],
                query=q["query"],
                task_type="schema",
                priority=q.get("priority", 0),
            )
            for i, q in enumerate(queries)
        ]
        
        # 包装检索函数以支持top_k
        def wrapped_func(ds_id: int, query: str) -> List[Dict]:
            return retrieval_func(ds_id, query, top_k)
        
        results = await self.retrieve_concurrent(tasks, wrapped_func)
        
        # 转换为字典格式
        return {
            r.task_id: r.results
            for r in results
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        avg_time = (
            self._stats["total_time_ms"] / self._stats["total_tasks"]
            if self._stats["total_tasks"] > 0
            else 0.0
        )
        
        return {
            "max_concurrent": self.max_concurrent,
            "timeout_seconds": self.timeout_seconds,
            "total_tasks": self._stats["total_tasks"],
            "successful_tasks": self._stats["successful_tasks"],
            "failed_tasks": self._stats["failed_tasks"],
            "timeout_tasks": self._stats["timeout_tasks"],
            "average_time_ms": avg_time,
            "success_rate": (
                self._stats["successful_tasks"] / self._stats["total_tasks"]
                if self._stats["total_tasks"] > 0
                else 0.0
            ),
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "timeout_tasks": 0,
            "total_time_ms": 0.0,
        }


class BatchSchemaRetriever:
    """
    批量Schema检索器
    
    优化的Schema检索，支持：
    1. 批量查询
    2. 结果缓存
    3. 增量更新
    """
    
    def __init__(self,
                 async_retriever: Optional[AsyncRetriever] = None,
                 cache_ttl_seconds: int = 300):
        """
        初始化批量检索器
        
        Args:
            async_retriever: 异步检索器实例
            cache_ttl_seconds: 缓存过期时间（秒）
        """
        self.async_retriever = async_retriever or AsyncRetriever()
        self.cache_ttl_seconds = cache_ttl_seconds
        
        # 简单的内存缓存
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def _get_cache_key(self, datasource_id: int, query: str) -> str:
        """生成缓存键"""
        import hashlib
        content = f"{datasource_id}:{query}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cached(self, datasource_id: int, query: str) -> Optional[List[Dict[str, Any]]]:
        """获取缓存结果"""
        cache_key = self._get_cache_key(datasource_id, query)
        
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            # 检查是否过期
            cached_time = cached.get("timestamp")
            if cached_time:
                age = (datetime.now() - cached_time).total_seconds()
                if age < self.cache_ttl_seconds:
                    return cached.get("results")
            
            # 已过期，删除
            del self._cache[cache_key]
        
        return None
    
    def _set_cached(self, datasource_id: int, query: str, results: List[Dict[str, Any]]):
        """设置缓存"""
        cache_key = self._get_cache_key(datasource_id, query)
        self._cache[cache_key] = {
            "results": results,
            "timestamp": datetime.now(),
        }
    
    async def retrieve_batch(self,
                             queries: List[Dict[str, Any]],
                             retrieval_func: Callable,
                             use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        批量检索
        
        Args:
            queries: 查询列表 [{"datasource_id": int, "query": str}, ...]
            retrieval_func: 检索函数
            use_cache: 是否使用缓存
            
        Returns:
            结果列表（与queries顺序对应）
        """
        results = [None] * len(queries)
        pending_queries = []
        pending_indices = []
        
        # 1. 检查缓存
        if use_cache:
            for i, q in enumerate(queries):
                cached = self._get_cached(q["datasource_id"], q["query"])
                if cached is not None:
                    results[i] = cached
                else:
                    pending_queries.append(q)
                    pending_indices.append(i)
        else:
            pending_queries = queries
            pending_indices = list(range(len(queries)))
        
        # 2. 并发检索未命中缓存的查询
        if pending_queries:
            batch_results = await self.async_retriever.retrieve_schemas_concurrent(
                pending_queries, retrieval_func
            )
            
            for i, idx in enumerate(pending_indices):
                result = batch_results.get(str(i), [])
                results[idx] = result
                
                # 更新缓存
                if use_cache:
                    self._set_cached(
                        pending_queries[i]["datasource_id"],
                        pending_queries[i]["query"],
                        result
                    )
        
        return results
    
    def clear_cache(self, datasource_id: Optional[int] = None):
        """清除缓存"""
        if datasource_id is not None:
            # 清除指定数据源的缓存
            keys_to_delete = [
                k for k in self._cache.keys()
                if k.startswith(f"{datasource_id}:")
            ]
            for k in keys_to_delete:
                del self._cache[k]
        else:
            # 清除所有缓存
            self._cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "cache_size": len(self._cache),
            "cache_ttl_seconds": self.cache_ttl_seconds,
        }


# 全局异步检索器实例
async_retriever = AsyncRetriever(max_concurrent=10, timeout_seconds=30)
batch_schema_retriever = BatchSchemaRetriever(async_retriever)




