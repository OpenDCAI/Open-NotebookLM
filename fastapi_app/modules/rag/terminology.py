"""
术语表系统 - 增强版

P1 优化：业务术语映射
- 支持数据源级别的术语定义
- 同义词和缩写映射
- 自动学习常用术语
- 快速精确匹配 + 语义检索

参考 SQLBot 的术语表设计
"""

import re
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

from langchain_core.documents import Document
from .vector_store import vector_store_manager
from .storage import rag_dir

logger = logging.getLogger(__name__)


@dataclass
class TermEntry:
    """术语条目"""
    term: str                           # 标准术语
    definition: str                     # 定义/解释
    synonyms: List[str] = field(default_factory=list)      # 同义词
    abbreviations: List[str] = field(default_factory=list)  # 缩写
    column_mappings: Dict[str, str] = field(default_factory=dict)  # 列映射 {表名: 列名}
    sql_expression: Optional[str] = None  # SQL 表达式（如 SUM(amount) / COUNT(*)）
    category: str = "general"           # 类别：metric, dimension, filter, general
    datasource_id: Optional[int] = None # 数据源ID（None表示全局）
    usage_count: int = 0                # 使用次数
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "term": self.term,
            "definition": self.definition,
            "synonyms": self.synonyms,
            "abbreviations": self.abbreviations,
            "column_mappings": self.column_mappings,
            "sql_expression": self.sql_expression,
            "category": self.category,
            "datasource_id": self.datasource_id,
            "usage_count": self.usage_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TermEntry":
        return cls(
            term=data["term"],
            definition=data.get("definition", ""),
            synonyms=data.get("synonyms", []),
            abbreviations=data.get("abbreviations", []),
            column_mappings=data.get("column_mappings", {}),
            sql_expression=data.get("sql_expression"),
            category=data.get("category", "general"),
            datasource_id=data.get("datasource_id"),
            usage_count=data.get("usage_count", 0),
        )


class TerminologyService:
    """
    增强版术语表服务
    
    特性：
    1. 精确匹配：快速查找已知术语
    2. 语义检索：向量相似度匹配
    3. 数据源隔离：每个数据源可有独立术语
    4. 自动学习：记录常用术语组合
    5. SQL 表达式：复杂指标的 SQL 定义
    """
    
    # 预置通用术语
    BUILTIN_TERMS = [
        # 时间维度
        TermEntry(
            term="今年",
            definition="当前年份",
            synonyms=["本年度", "当年"],
            sql_expression="EXTRACT(YEAR FROM {date_col}) = EXTRACT(YEAR FROM CURRENT_DATE)",
            category="filter"
        ),
        TermEntry(
            term="去年",
            definition="上一年份",
            synonyms=["上年", "上一年"],
            sql_expression="EXTRACT(YEAR FROM {date_col}) = EXTRACT(YEAR FROM CURRENT_DATE) - 1",
            category="filter"
        ),
        TermEntry(
            term="本月",
            definition="当前月份",
            synonyms=["这个月", "当月"],
            sql_expression="EXTRACT(YEAR FROM {date_col}) = EXTRACT(YEAR FROM CURRENT_DATE) AND EXTRACT(MONTH FROM {date_col}) = EXTRACT(MONTH FROM CURRENT_DATE)",
            category="filter"
        ),
        TermEntry(
            term="上月",
            definition="上一个月份",
            synonyms=["上个月", "前一个月"],
            sql_expression="EXTRACT(YEAR FROM {date_col}) = EXTRACT(YEAR FROM CURRENT_DATE - INTERVAL '1 month') AND EXTRACT(MONTH FROM {date_col}) = EXTRACT(MONTH FROM CURRENT_DATE - INTERVAL '1 month')",
            category="filter"
        ),
        
        # 常用指标
        TermEntry(
            term="销售额",
            definition="销售金额总和",
            synonyms=["销售金额", "营业额", "收入", "GMV"],
            abbreviations=["GMV"],
            sql_expression="SUM({amount_col})",
            category="metric"
        ),
        TermEntry(
            term="订单量",
            definition="订单数量",
            synonyms=["订单数", "订单总数", "单量"],
            sql_expression="COUNT(*)",
            category="metric"
        ),
        TermEntry(
            term="客单价",
            definition="平均每单金额",
            synonyms=["平均订单金额", "单均价"],
            sql_expression="AVG({amount_col})",
            category="metric"
        ),
        TermEntry(
            term="同比",
            definition="与去年同期比较",
            synonyms=["年同比", "YoY"],
            abbreviations=["YoY"],
            category="metric"
        ),
        TermEntry(
            term="环比",
            definition="与上期比较",
            synonyms=["月环比", "MoM"],
            abbreviations=["MoM"],
            category="metric"
        ),
        
        # 排序相关
        TermEntry(
            term="最高",
            definition="按降序排列取第一",
            synonyms=["最大", "第一", "TOP1"],
            sql_expression="ORDER BY {col} DESC LIMIT 1",
            category="filter"
        ),
        TermEntry(
            term="最低",
            definition="按升序排列取第一",
            synonyms=["最小", "最少"],
            sql_expression="ORDER BY {col} ASC LIMIT 1",
            category="filter"
        ),
        TermEntry(
            term="前N",
            definition="排名前N的记录",
            synonyms=["TOP", "前几名"],
            sql_expression="ORDER BY {col} DESC LIMIT {n}",
            category="filter"
        ),
    ]
    
    def __init__(self, persist_path: Optional[str] = None):
        self.vector_store = vector_store_manager.get_vector_store("terminology")
        
        # 精确匹配索引：{term/synonym/abbreviation: TermEntry}
        self._exact_index: Dict[str, TermEntry] = {}
        
        # 数据源级别术语：{datasource_id: {term: TermEntry}}
        self._datasource_terms: Dict[int, Dict[str, TermEntry]] = {}
        
        # 全局术语
        self._global_terms: Dict[str, TermEntry] = {}
        
        # 持久化路径(avoid CWD ambiguity)
        self.persist_path = Path(persist_path) if persist_path else rag_dir("terminology_data")
        
        # 初始化内置术语
        self._init_builtin_terms()
        
        # 加载持久化数据
        self._load_from_disk()
    
    def _init_builtin_terms(self):
        """初始化内置术语"""
        for term_entry in self.BUILTIN_TERMS:
            self._add_to_index(term_entry)
            self._global_terms[term_entry.term] = term_entry
    
    def _add_to_index(self, entry: TermEntry):
        """添加到精确匹配索引"""
        # 主术语
        self._exact_index[entry.term.lower()] = entry
        
        # 同义词
        for syn in entry.synonyms:
            self._exact_index[syn.lower()] = entry
        
        # 缩写
        for abbr in entry.abbreviations:
            self._exact_index[abbr.lower()] = entry
    
    def _load_from_disk(self):
        """从磁盘加载术语"""
        try:
            if self.persist_path.exists():
                data_file = self.persist_path / "terms.json"
                if data_file.exists():
                    with open(data_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    for term_data in data.get("global", []):
                        entry = TermEntry.from_dict(term_data)
                        self._global_terms[entry.term] = entry
                        self._add_to_index(entry)
                    
                    for ds_id, terms in data.get("datasource", {}).items():
                        ds_id = int(ds_id)
                        self._datasource_terms[ds_id] = {}
                        for term_data in terms:
                            entry = TermEntry.from_dict(term_data)
                            self._datasource_terms[ds_id][entry.term] = entry
                            self._add_to_index(entry)
                    
                    logger.info(f"Loaded {len(self._exact_index)} terms from disk")
        except Exception as e:
            logger.warning(f"Failed to load terminology: {e}")
    
    def _save_to_disk(self):
        """保存术语到磁盘"""
        try:
            self.persist_path.mkdir(parents=True, exist_ok=True)
            data_file = self.persist_path / "terms.json"
            
            data = {
                "global": [t.to_dict() for t in self._global_terms.values() 
                          if t not in self.BUILTIN_TERMS],
                "datasource": {
                    str(ds_id): [t.to_dict() for t in terms.values()]
                    for ds_id, terms in self._datasource_terms.items()
                }
            }
            
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.warning(f"Failed to save terminology: {e}")
    
    def add_term(self, 
                 term: str,
                 definition: str,
                 synonyms: List[str] = None,
                 abbreviations: List[str] = None,
                 column_mappings: Dict[str, str] = None,
                 sql_expression: str = None,
                 category: str = "general",
                 datasource_id: int = None) -> TermEntry:
        """
        添加术语
        
        Args:
            term: 标准术语名
            definition: 定义
            synonyms: 同义词列表
            abbreviations: 缩写列表
            column_mappings: 列映射 {表名: 列名}
            sql_expression: SQL 表达式
            category: 类别 (metric/dimension/filter/general)
            datasource_id: 数据源ID (None表示全局)
        """
        entry = TermEntry(
            term=term,
            definition=definition,
            synonyms=synonyms or [],
            abbreviations=abbreviations or [],
            column_mappings=column_mappings or {},
            sql_expression=sql_expression,
            category=category,
            datasource_id=datasource_id
        )
        
        # 添加到索引
        self._add_to_index(entry)
        
        # 添加到对应存储
        if datasource_id is not None:
            if datasource_id not in self._datasource_terms:
                self._datasource_terms[datasource_id] = {}
            self._datasource_terms[datasource_id][term] = entry
        else:
            self._global_terms[term] = entry
        
        # 添加到向量存储（用于语义检索）
        content = f"{term}: {definition}"
        if synonyms:
            content += f" (同义词: {', '.join(synonyms)})"
        if abbreviations:
            content += f" (缩写: {', '.join(abbreviations)})"
        
        metadata = entry.to_dict()
        doc = Document(page_content=content, metadata=metadata)
        if self.vector_store:
            self.vector_store.add_documents([doc])
        
        # 持久化
        self._save_to_disk()
        
        logger.info(f"Added term: {term}")
        return entry
    
    def lookup(self, text: str, datasource_id: int = None) -> Optional[TermEntry]:
        """
        精确查找术语
        
        优先顺序：数据源术语 > 全局术语 > 内置术语
        """
        text_lower = text.lower().strip()
        
        # 1. 数据源级别
        if datasource_id and datasource_id in self._datasource_terms:
            for term, entry in self._datasource_terms[datasource_id].items():
                if term.lower() == text_lower:
                    entry.usage_count += 1
                    return entry
                if text_lower in [s.lower() for s in entry.synonyms]:
                    entry.usage_count += 1
                    return entry
                if text_lower in [a.lower() for a in entry.abbreviations]:
                    entry.usage_count += 1
                    return entry
        
        # 2. 精确索引
        if text_lower in self._exact_index:
            entry = self._exact_index[text_lower]
            entry.usage_count += 1
            return entry
        
        return None
    
    def extract_terms(self, question: str, datasource_id: int = None) -> List[Tuple[str, TermEntry]]:
        """
        从问题中提取术语
        
        Returns:
            List of (matched_text, TermEntry) tuples
        """
        found_terms = []
        question_lower = question.lower()
        
        # 按术语长度降序排列（优先匹配长术语）
        all_terms = list(self._exact_index.items())
        all_terms.sort(key=lambda x: len(x[0]), reverse=True)
        
        for term_text, entry in all_terms:
            # Datasource-scoped terms should not leak into other datasources.
            if (
                entry.datasource_id is not None
                and datasource_id is not None
                and entry.datasource_id != datasource_id
            ):
                continue
            if term_text in question_lower:
                # 检查是否已经被更长的术语覆盖
                already_matched = False
                for matched_text, _ in found_terms:
                    if term_text in matched_text.lower():
                        already_matched = True
                        break
                
                if not already_matched:
                    found_terms.append((term_text, entry))
                    entry.usage_count += 1
        
        return found_terms
    
    def expand_question(self, question: str, datasource_id: int = None) -> str:
        """
        扩展问题（添加术语定义）
        
        用于增强 LLM 理解
        """
        terms = self.extract_terms(question, datasource_id)
        
        if not terms:
            return question
        
        expansions = []
        for matched_text, entry in terms:
            expansion = f"{entry.term}"
            if entry.sql_expression:
                expansion += f" (SQL: {entry.sql_expression})"
            elif entry.definition:
                expansion += f" ({entry.definition})"
            expansions.append(expansion)
        
        expanded = f"{question}\n\n术语说明：{'; '.join(expansions)}"
        return expanded

    def _tokenize_for_match(self, text: str) -> List[str]:
        """Lightweight lexical tokenizer for degraded retrieval (no embeddings)."""
        if not text:
            return []
        text = str(text).lower()
        try:
            import jieba  # type: ignore

            tokens = [t.strip() for t in jieba.cut_for_search(text) if t.strip()]
        except Exception:
            tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", text)
        return [t for t in tokens if len(t) >= 2]

    def _lexical_retrieve(
        self, question: str, k: int = 3, datasource_id: int = None
    ) -> List[Dict[str, Any]]:
        """Degraded terminology retrieval when vector store is unavailable."""
        q_tokens = set(self._tokenize_for_match(question))
        if not q_tokens:
            return []

        entries: List[TermEntry] = []
        seen = set()

        # datasource terms first
        if datasource_id is not None and datasource_id in self._datasource_terms:
            for e in self._datasource_terms[datasource_id].values():
                if id(e) not in seen:
                    entries.append(e)
                    seen.add(id(e))

        # global terms
        for e in self._global_terms.values():
            if id(e) not in seen:
                entries.append(e)
                seen.add(id(e))

        scored: List[Tuple[float, TermEntry]] = []
        for e in entries:
            parts = [e.term, e.definition] + (e.synonyms or []) + (e.abbreviations or [])
            e_tokens = set(self._tokenize_for_match(" ".join([p for p in parts if p])))
            if not e_tokens:
                continue
            inter = len(q_tokens & e_tokens)
            union = len(q_tokens | e_tokens) or 1
            score = inter / union
            if datasource_id is not None and e.datasource_id == datasource_id:
                score += 0.05
            scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[Dict[str, Any]] = []
        for score, e in scored[: k * 3]:
            if score <= 0:
                continue
            results.append(
                {
                    "term": e.term,
                    "definition": e.definition,
                    "synonyms": e.synonyms,
                    "sql_expression": e.sql_expression,
                    "category": e.category,
                    "content": f"{e.term}: {e.definition}",
                    "lexical_score": float(score),
                }
            )
            if len(results) >= k:
                break
        return results
    
    def retrieve(self, question: str, k: int = 3, 
                 datasource_id: int = None) -> List[Dict[str, Any]]:
        """
        语义检索相关术语
        """
        if not self.vector_store:
            return self._lexical_retrieve(question=question, k=k, datasource_id=datasource_id)
        try:
            docs = self.vector_store.similarity_search(question, k=k)
            
            results = []
            for doc in docs:
                result = {
                    "term": doc.metadata.get("term", ""),
                    "definition": doc.metadata.get("definition", ""),
                    "synonyms": doc.metadata.get("synonyms", []),
                    "sql_expression": doc.metadata.get("sql_expression"),
                    "category": doc.metadata.get("category", "general"),
                    "content": doc.page_content
                }
                
                # 过滤数据源
                term_ds_id = doc.metadata.get("datasource_id")
                if datasource_id is not None and term_ds_id is not None:
                    if term_ds_id != datasource_id:
                        continue
                
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving terminologies: {e}")
            return []

    def get_sql_hint(self, term_text: str, datasource_id: int = None) -> Optional[str]:
        """
        获取术语的 SQL 提示
        """
        entry = self.lookup(term_text, datasource_id)
        if entry and entry.sql_expression:
            return entry.sql_expression
        return None
    
    def auto_learn_from_query(self, question: str, sql: str, 
                               datasource_id: int = None):
        """
        从成功的查询中自动学习术语模式
        
        TODO: 实现 NER + 模式提取
        """
        # 这是一个占位实现，实际需要更复杂的 NLP 分析
        pass
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_terms": len(self._exact_index),
            "global_terms": len(self._global_terms),
            "datasource_terms": {
                ds_id: len(terms) 
                for ds_id, terms in self._datasource_terms.items()
            },
            "builtin_terms": len(self.BUILTIN_TERMS),
            "top_used": sorted(
                [(t.term, t.usage_count) for t in self._global_terms.values()],
                key=lambda x: x[1],
                reverse=True
            )[:10]
        }
    
    # 兼容旧接口
    def add_terminology(self, term: str, definition: str, 
                        synonyms: List[str] = None):
        """兼容旧接口"""
        return self.add_term(term, definition, synonyms=synonyms)


# 全局实例
terminology_service = TerminologyService()
