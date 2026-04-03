"""
LLM 列级精排器

P1 优化：大表列过滤
- 当表有超过 20 列时启用
- 使用 LLM 精选相关列
- 减少 Token 消耗和噪声
- 提升 SQL 生成准确率

参考 JoyAgent 的列级检索策略
"""

import re
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    """列信息"""
    name: str
    data_type: str
    comment: Optional[str] = None
    sample_values: List[Any] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    nullable: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.data_type,
            "comment": self.comment,
            "sample_values": self.sample_values[:3] if self.sample_values else None,
            "is_pk": self.is_primary_key,
            "is_fk": self.is_foreign_key,
        }
    
    def to_brief(self) -> str:
        """简洁描述"""
        desc = f"{self.name} ({self.data_type})"
        if self.comment:
            desc += f" - {self.comment}"
        return desc


class ColumnRanker:
    """
    LLM 列级精排器
    
    设计理念：
    1. 对于大表（>20列），先用规则快速筛选
    2. 然后用 LLM 精排，选出最相关的列
    3. 减少噪声，提升 SQL 准确率
    
    用法：
    ```python
    ranker = ColumnRanker(llm)
    
    # 精排列
    relevant_columns = await ranker.rank_columns(
        question="查询各城市的总销售额",
        table_name="sales",
        columns=[...],  # 原始列列表
        top_k=10
    )
    ```
    """
    
    # 需要 LLM 精排的列数阈值
    COLUMN_THRESHOLD = 20
    
    # 规则筛选关键词
    METRIC_PATTERNS = [
        r'amount|price|total|sum|count|qty|quantity|num|number',
        r'金额|价格|总|数量|数目',
    ]
    
    DIMENSION_PATTERNS = [
        r'_id$|_code$|_name$|_type$|category|group|class',
        r'id$|名称|类型|分类|类别',
    ]
    
    TIME_PATTERNS = [
        r'date|time|year|month|day|created|updated|_at$',
        r'日期|时间|年|月|日',
    ]
    
    # 通常不需要的列
    EXCLUDE_PATTERNS = [
        r'^(created|updated|deleted)_(at|by|time)$',
        r'^(is_deleted|is_active|version|revision)$',
        r'^(row_id|_id|uuid)$',
    ]
    
    def __init__(self, llm=None, use_llm: bool = True):
        """
        初始化
        
        Args:
            llm: LangChain LLM 实例
            use_llm: 是否使用 LLM 精排（否则只用规则）
        """
        self._llm = llm
        self.use_llm = use_llm
    
    def set_llm(self, llm):
        """设置 LLM"""
        self._llm = llm
    
    def _rule_based_filter(self, 
                           question: str,
                           columns: List[Dict[str, Any]],
                           top_k: int = 15) -> List[Dict[str, Any]]:
        """
        规则基础的列过滤
        
        策略：
        1. 主键/外键必选
        2. 根据问题关键词匹配
        3. 时间、维度、指标列优先
        4. 排除元数据列
        """
        question_lower = question.lower()
        
        scored_columns = []
        for col in columns:
            col_name = col.get("name", "").lower()
            col_comment = (col.get("comment") or "").lower()
            col_type = (col.get("type") or "").lower()
            
            score = 0.0
            reasons = []
            
            # 1. 主键/外键加分
            if col.get("is_pk") or col.get("is_primary_key"):
                score += 3.0
                reasons.append("PK")
            if col.get("is_fk") or col.get("is_foreign_key"):
                score += 2.0
                reasons.append("FK")
            
            # 2. 排除元数据列
            should_exclude = False
            for pattern in self.EXCLUDE_PATTERNS:
                if re.search(pattern, col_name, re.I):
                    should_exclude = True
                    break
            
            if should_exclude:
                score -= 5.0
                reasons.append("metadata")
            
            # 3. 问题中直接提到的列名
            if col_name in question_lower or (col_comment and col_comment in question_lower):
                score += 5.0
                reasons.append("direct_match")
            
            # 4. 部分匹配
            col_words = re.split(r'[_\s]', col_name)
            for word in col_words:
                if len(word) > 2 and word in question_lower:
                    score += 2.0
                    reasons.append(f"partial:{word}")
            
            # 5. 指标列（数值类型 + 指标关键词）
            is_numeric = any(t in col_type for t in ['int', 'float', 'decimal', 'numeric', 'double'])
            for pattern in self.METRIC_PATTERNS:
                if re.search(pattern, col_name + ' ' + col_comment, re.I):
                    score += 2.0 if is_numeric else 1.0
                    reasons.append("metric")
                    break
            
            # 6. 维度列
            for pattern in self.DIMENSION_PATTERNS:
                if re.search(pattern, col_name, re.I):
                    score += 1.5
                    reasons.append("dimension")
                    break
            
            # 7. 时间列
            for pattern in self.TIME_PATTERNS:
                if re.search(pattern, col_name, re.I):
                    # 只有问题涉及时间才加分
                    time_keywords = ['年', '月', '日', '时间', '日期', 'year', 'month', 'date', 'time', '最近', '去年', '今年']
                    if any(kw in question_lower for kw in time_keywords):
                        score += 2.5
                        reasons.append("time_relevant")
                    else:
                        score += 0.5
                        reasons.append("time")
                    break
            
            scored_columns.append({
                **col,
                "_score": score,
                "_reasons": reasons
            })
        
        # 按分数排序
        scored_columns.sort(key=lambda x: x["_score"], reverse=True)
        
        # 返回 top_k
        result = []
        for col in scored_columns[:top_k]:
            # 移除内部字段
            clean_col = {k: v for k, v in col.items() if not k.startswith("_")}
            result.append(clean_col)
        
        logger.info(f"Rule-based filter: {len(columns)} -> {len(result)} columns")
        return result
    
    async def rank_columns(self,
                           question: str,
                           table_name: str,
                           columns: List[Dict[str, Any]],
                           top_k: int = 10) -> List[Dict[str, Any]]:
        """
        精排列（异步）
        
        Args:
            question: 用户问题
            table_name: 表名
            columns: 列信息列表
            top_k: 返回列数
            
        Returns:
            精选后的列列表
        """
        # 列数少于阈值，直接返回
        if len(columns) < self.COLUMN_THRESHOLD:
            logger.info(f"Table {table_name} has {len(columns)} columns, skip ranking")
            return columns
        
        # 1. 规则预筛选（减少 LLM 输入）
        pre_filtered = self._rule_based_filter(question, columns, top_k=min(30, len(columns)))
        
        # 2. 不使用 LLM 或 LLM 不可用，返回规则结果
        if not self.use_llm or not self._llm:
            return pre_filtered[:top_k]
        
        # 3. LLM 精排
        try:
            llm_result = await self._llm_rank(question, table_name, pre_filtered, top_k)
            if llm_result:
                return llm_result
        except Exception as e:
            logger.warning(f"LLM ranking failed: {e}, fallback to rule-based")
        
        return pre_filtered[:top_k]
    
    def rank_columns_sync(self,
                          question: str,
                          table_name: str,
                          columns: List[Dict[str, Any]],
                          top_k: int = 10) -> List[Dict[str, Any]]:
        """
        精排列（同步版本）
        """
        if len(columns) < self.COLUMN_THRESHOLD:
            return columns
        
        pre_filtered = self._rule_based_filter(question, columns, top_k=min(30, len(columns)))
        
        if not self.use_llm or not self._llm:
            return pre_filtered[:top_k]
        
        try:
            llm_result = self._llm_rank_sync(question, table_name, pre_filtered, top_k)
            if llm_result:
                return llm_result
        except Exception as e:
            logger.warning(f"LLM ranking failed: {e}")
        
        return pre_filtered[:top_k]
    
    async def _llm_rank(self,
                        question: str,
                        table_name: str,
                        columns: List[Dict[str, Any]],
                        top_k: int) -> Optional[List[Dict[str, Any]]]:
        """LLM 精排（异步）"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._llm_rank_sync(question, table_name, columns, top_k)
        )
    
    def _llm_rank_sync(self,
                       question: str,
                       table_name: str,
                       columns: List[Dict[str, Any]],
                       top_k: int) -> Optional[List[Dict[str, Any]]]:
        """LLM 精排（同步）"""
        # 构建列描述
        col_descriptions = []
        for i, col in enumerate(columns):
            desc = f"{i+1}. {col.get('name', '')} ({col.get('type', '')})"
            if col.get('comment'):
                desc += f" - {col['comment']}"
            col_descriptions.append(desc)
        
        prompt = f"""分析用户问题，从以下列中选择生成SQL最需要的{top_k}个列。

用户问题: {question}

表名: {table_name}

可选列:
{chr(10).join(col_descriptions)}

请返回JSON格式的列名数组，按相关性从高到低排序。只返回JSON，不要其他内容。
格式: ["col1", "col2", ...]"""

        try:
            response = self._llm.invoke([
                SystemMessage(content="你是SQL专家，擅长分析问题并选择相关的数据库列。只返回JSON数组。"),
                HumanMessage(content=prompt)
            ])
            
            content = response.content.strip()
            
            # 提取 JSON 数组
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                selected_names = json.loads(json_match.group())
                
                # 根据 LLM 选择重新排序
                name_to_col = {col.get("name", ""): col for col in columns}
                result = []
                for name in selected_names:
                    if name in name_to_col:
                        result.append(name_to_col[name])
                
                logger.info(f"LLM selected {len(result)} columns for table {table_name}")
                return result if result else None
                
        except Exception as e:
            logger.warning(f"LLM column ranking error: {e}")
        
        return None
    
    def filter_schema_columns(self,
                               question: str,
                               tables: List[Dict[str, Any]],
                               column_limit: int = 15) -> List[Dict[str, Any]]:
        """
        过滤多表 Schema 的列
        
        用于在将 Schema 传给 LLM 前精简列信息
        
        Args:
            question: 用户问题
            tables: 表列表，每个包含 columns 字段
            column_limit: 每表最大列数
            
        Returns:
            精简后的表列表
        """
        result = []
        
        for table in tables:
            table_name = table.get("table_name", table.get("name", ""))
            columns = table.get("columns", [])
            
            if len(columns) >= self.COLUMN_THRESHOLD:
                # 需要过滤 (>=20列时启用)
                filtered_cols = self._rule_based_filter(question, columns, column_limit)
                result.append({
                    **table,
                    "columns": filtered_cols,
                    "_original_column_count": len(columns),
                    "_filtered": True
                })
            else:
                result.append(table)
        
        return result


class ColumnRankingService:
    """
    列精排服务（带缓存）
    
    全局服务，支持：
    - LLM 实例管理
    - 结果缓存
    - 统计信息
    """
    
    def __init__(self):
        self._ranker = ColumnRanker(llm=None, use_llm=True)
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "llm_calls": 0,
            "rule_only_calls": 0,
        }
    
    def set_llm(self, llm):
        """设置 LLM 实例"""
        self._ranker.set_llm(llm)
    
    def _cache_key(self, question: str, table_name: str, column_count: int) -> str:
        """生成缓存键"""
        import hashlib
        content = f"{question}:{table_name}:{column_count}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def rank_columns(self,
                     question: str,
                     table_name: str,
                     columns: List[Dict[str, Any]],
                     top_k: int = 10,
                     use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        精排列（同步，带缓存）
        """
        self._stats["total_requests"] += 1
        
        # 检查缓存
        if use_cache:
            cache_key = self._cache_key(question, table_name, len(columns))
            if cache_key in self._cache:
                self._stats["cache_hits"] += 1
                return self._cache[cache_key]
        
        # 执行精排
        result = self._ranker.rank_columns_sync(question, table_name, columns, top_k)
        
        # 更新统计
        if self._ranker._llm and len(columns) >= ColumnRanker.COLUMN_THRESHOLD:
            self._stats["llm_calls"] += 1
        else:
            self._stats["rule_only_calls"] += 1
        
        # 缓存结果
        if use_cache:
            self._cache[cache_key] = result
        
        return result
    
    def filter_schema(self,
                      question: str,
                      tables: List[Dict[str, Any]],
                      column_limit: int = 15) -> List[Dict[str, Any]]:
        """过滤 Schema 列"""
        return self._ranker.filter_schema_columns(question, tables, column_limit)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        return {
            **self._stats,
            "cache_size": len(self._cache),
            "cache_hit_rate": (
                self._stats["cache_hits"] / self._stats["total_requests"]
                if self._stats["total_requests"] > 0 else 0
            )
        }
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


# 全局服务实例
column_ranking_service = ColumnRankingService()

