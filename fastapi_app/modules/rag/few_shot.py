"""
Few-shot 学习服务 - 增强版

P2 优化：示例查询学习
- 动态示例检索
- 数据源级别示例
- 自动学习成功案例
- 示例质量评分
- SQL 模式分类

参考 SQLBot 的 Few-shot 设计
"""

import re
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

from langchain_core.documents import Document
from .vector_store import vector_store_manager
from .storage import rag_dir

logger = logging.getLogger(__name__)


@dataclass
class FewShotExample:
    """Few-shot 示例"""
    question: str                       # 问题
    sql: str                            # SQL
    description: str = ""               # 描述/解释
    pattern: str = "general"            # SQL 模式
    difficulty: str = "medium"          # 难度: easy, medium, hard
    datasource_id: Optional[int] = None # 数据源 ID
    tables_used: List[str] = field(default_factory=list)  # 使用的表
    success_count: int = 0              # 成功使用次数
    fail_count: int = 0                 # 失败次数
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "sql": self.sql,
            "description": self.description,
            "pattern": self.pattern,
            "difficulty": self.difficulty,
            "datasource_id": self.datasource_id,
            "tables_used": self.tables_used,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
        }
    
    @property
    def quality_score(self) -> float:
        """质量分数（基于成功/失败率）"""
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.5  # 默认中等
        return self.success_count / total
    
    def to_prompt_format(self, include_description: bool = True) -> str:
        """转为 Prompt 格式"""
        result = f"问题: {self.question}\nSQL:\n```sql\n{self.sql}\n```"
        if include_description and self.description:
            result += f"\n说明: {self.description}"
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FewShotExample":
        return cls(
            question=data["question"],
            sql=data["sql"],
            description=data.get("description", ""),
            pattern=data.get("pattern", "general"),
            difficulty=data.get("difficulty", "medium"),
            datasource_id=data.get("datasource_id"),
            tables_used=data.get("tables_used", []),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
        )


class FewShotService:
    """
    增强版 Few-shot 服务
    
    特性：
    1. 语义检索：向量相似度匹配问题
    2. 模式匹配：根据 SQL 模式分类
    3. 数据源隔离：每个数据源独立示例
    4. 质量评估：基于使用效果的质量分
    5. 自动学习：从成功查询中学习
    """
    
    # SQL 模式分类
    PATTERNS = {
        "simple_select": {
            "keywords": ["select", "from", "where"],
            "description": "简单查询",
            "example_sql": "SELECT * FROM table WHERE condition"
        },
        "aggregation": {
            "keywords": ["sum", "count", "avg", "max", "min", "group by"],
            "description": "聚合统计",
            "example_sql": "SELECT col, SUM(val) FROM table GROUP BY col"
        },
        "join": {
            "keywords": ["join", "left join", "right join", "inner join"],
            "description": "多表关联",
            "example_sql": "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id"
        },
        "subquery": {
            "keywords": ["select", "from", "(select"],
            "description": "子查询",
            "example_sql": "SELECT * FROM (SELECT ...) AS sub"
        },
        "window": {
            "keywords": ["over", "partition by", "row_number", "rank", "dense_rank"],
            "description": "窗口函数",
            "example_sql": "SELECT ROW_NUMBER() OVER (PARTITION BY col ORDER BY val)"
        },
        "cte": {
            "keywords": ["with", "as ("],
            "description": "公共表表达式",
            "example_sql": "WITH cte AS (SELECT ...) SELECT * FROM cte"
        },
    }
    
    def __init__(self, persist_path: Optional[str] = None):
        self.vector_store = vector_store_manager.get_vector_store("few_shot_examples")
        
        # 示例存储
        self._examples: Dict[str, FewShotExample] = {}  # id -> example
        
        # 数据源级别索引
        self._datasource_examples: Dict[int, List[str]] = defaultdict(list)  # ds_id -> [example_ids]
        
        # 模式级别索引
        self._pattern_examples: Dict[str, List[str]] = defaultdict(list)  # pattern -> [example_ids]
        
        # 持久化路径(avoid CWD ambiguity)
        self.persist_path = Path(persist_path) if persist_path else rag_dir("few_shot_data")
        
        # 加载数据
        self._load_from_disk()
    
    def _generate_id(self, question: str) -> str:
        """生成示例 ID"""
        import hashlib
        return hashlib.md5(question.encode()).hexdigest()[:12]
    
    def _classify_pattern(self, sql: str) -> str:
        """分类 SQL 模式"""
        sql_lower = sql.lower()
        
        # 按优先级检查
        if "with " in sql_lower and " as (" in sql_lower:
            return "cte"
        if " over " in sql_lower or " over(" in sql_lower:
            return "window"
        if "(select " in sql_lower:
            return "subquery"
        if " join " in sql_lower:
            return "join"
        if any(kw in sql_lower for kw in ["sum(", "count(", "avg(", "max(", "min(", "group by"]):
            return "aggregation"
        
        return "simple_select"
    
    def _extract_tables(self, sql: str) -> List[str]:
        """从 SQL 中提取表名"""
        # 简单实现：匹配 FROM/JOIN 后的标识符
        tables = []
        
        # 匹配 FROM table
        from_matches = re.findall(r'\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql, re.I)
        tables.extend(from_matches)
        
        # 匹配 JOIN table
        join_matches = re.findall(r'\bjoin\s+([a-zA-Z_][a-zA-Z0-9_]*)', sql, re.I)
        tables.extend(join_matches)
        
        return list(set(tables))
    
    def _load_from_disk(self):
        """从磁盘加载"""
        try:
            if self.persist_path.exists():
                data_file = self.persist_path / "examples.json"
                if data_file.exists():
                    with open(data_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    for example_data in data.get("examples", []):
                        example = FewShotExample.from_dict(example_data)
                        example_id = self._generate_id(example.question)
                        self._examples[example_id] = example
                        
                        if example.datasource_id:
                            self._datasource_examples[example.datasource_id].append(example_id)
                        
                        self._pattern_examples[example.pattern].append(example_id)
                    
                    logger.info(f"Loaded {len(self._examples)} few-shot examples")
        except Exception as e:
            logger.warning(f"Failed to load few-shot examples: {e}")
    
    def _save_to_disk(self):
        """保存到磁盘"""
        try:
            self.persist_path.mkdir(parents=True, exist_ok=True)
            data_file = self.persist_path / "examples.json"
            
            data = {
                "examples": [ex.to_dict() for ex in self._examples.values()]
            }
            
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.warning(f"Failed to save few-shot examples: {e}")
    
    def add_example(self, 
                    question: str, 
                    sql: str, 
                    description: str = "",
                    datasource_id: int = None,
                    difficulty: str = "medium") -> str:
        """
        添加示例
        
        Returns:
            示例 ID
        """
        example_id = self._generate_id(question)
        
        # 自动分类
        pattern = self._classify_pattern(sql)
        tables = self._extract_tables(sql)
        
        example = FewShotExample(
            question=question,
            sql=sql,
            description=description,
            pattern=pattern,
            difficulty=difficulty,
            datasource_id=datasource_id,
            tables_used=tables
        )
        
        self._examples[example_id] = example
        
        # 更新索引
        if datasource_id:
            self._datasource_examples[datasource_id].append(example_id)
        self._pattern_examples[pattern].append(example_id)
        
        # 添加到向量存储
        metadata = {
            "example_id": example_id,
            "sql": sql,
            "pattern": pattern,
            "datasource_id": datasource_id or -1,
            "tables": ",".join(tables),
            "full_content": example.to_prompt_format()
        }
        
        doc = Document(page_content=question, metadata=metadata)
        if self.vector_store:
            self.vector_store.add_documents([doc])
        
        # 持久化
        self._save_to_disk()
        
        logger.info(f"Added example: {question[:50]}... (pattern={pattern})")
        return example_id

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
        self,
        question: str,
        k: int = 3,
        datasource_id: int = None,
        pattern_filter: str = None,
        min_quality: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Degraded few-shot retrieval when vector store is unavailable."""
        q_tokens = set(self._tokenize_for_match(question))
        if not q_tokens:
            return []

        candidates: List[FewShotExample] = []
        for ex in self._examples.values():
            if ex.quality_score < min_quality:
                continue
            if pattern_filter and ex.pattern != pattern_filter:
                continue
            if datasource_id and ex.datasource_id is not None and ex.datasource_id != datasource_id:
                continue
            candidates.append(ex)

        scored: List[Tuple[float, FewShotExample]] = []
        for ex in candidates:
            ex_tokens = set(self._tokenize_for_match(ex.question))
            if not ex_tokens:
                continue
            inter = len(q_tokens & ex_tokens)
            union = len(q_tokens | ex_tokens) or 1
            score = inter / union
            if datasource_id and ex.datasource_id == datasource_id:
                score += 0.05
            score += (ex.quality_score - 0.5) * 0.05
            scored.append((score, ex))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[Dict[str, Any]] = []
        for score, ex in scored[: k * 2]:
            results.append(
                {
                    "question": ex.question,
                    "sql": ex.sql,
                    "description": ex.description,
                    "pattern": ex.pattern,
                    "quality_score": ex.quality_score,
                    "full_content": ex.to_prompt_format(),
                    "tables_used": ex.tables_used,
                    "lexical_score": float(score),
                }
            )
            if len(results) >= k:
                break
        return results
    
    def retrieve(self, 
                 question: str, 
                 k: int = 3,
                 datasource_id: int = None,
                 pattern_filter: str = None,
                 min_quality: float = 0.3) -> List[Dict[str, Any]]:
        """
        检索相关示例
        
        Args:
            question: 用户问题
            k: 返回数量
            datasource_id: 数据源 ID（可选）
            pattern_filter: SQL 模式过滤（可选）
            min_quality: 最小质量分数
            
        Returns:
            示例列表
        """
        if not self.vector_store:
            return self._lexical_retrieve(
                question=question,
                k=k,
                datasource_id=datasource_id,
                pattern_filter=pattern_filter,
                min_quality=min_quality,
            )

        try:
            # 向量检索
            docs = self.vector_store.similarity_search(question, k=k * 2)  # 多检索一些用于过滤
            
            results = []
            for doc in docs:
                example_id = doc.metadata.get("example_id")
                if not example_id or example_id not in self._examples:
                    continue
                
                example = self._examples[example_id]
                
                # 质量过滤
                if example.quality_score < min_quality:
                    continue
                
                # 数据源过滤 (修复: datasource_id=None的示例视为通用示例)
                if datasource_id and example.datasource_id is not None:
                    # 只有明确绑定数据源的示例才过滤
                    if example.datasource_id != datasource_id:
                        continue
                # datasource_id=None的示例适用于所有数据源
                
                # 模式过滤
                if pattern_filter and example.pattern != pattern_filter:
                    continue
                
                results.append({
                    "question": example.question,
                    "sql": example.sql,
                    "description": example.description,
                    "pattern": example.pattern,
                    "quality_score": example.quality_score,
                    "full_content": doc.metadata.get("full_content", ""),
                    "tables_used": example.tables_used,
                })
                
                if len(results) >= k:
                    break
            
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving examples: {e}")
            return []
    
    def retrieve_by_pattern(self, pattern: str, k: int = 3) -> List[FewShotExample]:
        """按模式检索示例"""
        example_ids = self._pattern_examples.get(pattern, [])
        examples = [self._examples[eid] for eid in example_ids if eid in self._examples]
        
        # 按质量排序
        examples.sort(key=lambda x: x.quality_score, reverse=True)
        
        return examples[:k]
    
    def get_examples_for_prompt(self, 
                                 question: str,
                                 k: int = 3,
                                 datasource_id: int = None) -> str:
        """
        获取用于 Prompt 的示例文本
        
        格式化为可直接插入 Prompt 的文本
        """
        examples = self.retrieve(question, k=k, datasource_id=datasource_id)
        
        if not examples:
            return ""
        
        parts = ["以下是一些类似查询的示例，请参考它们的 SQL 写法：\n"]
        
        for i, ex in enumerate(examples, 1):
            parts.append(f"示例 {i}:")
            parts.append(f"问题: {ex['question']}")
            parts.append(f"SQL:\n```sql\n{ex['sql']}\n```")
            if ex.get('description'):
                parts.append(f"说明: {ex['description']}")
            parts.append("")
        
        return "\n".join(parts)
    
    def record_success(self, question: str):
        """记录成功使用"""
        example_id = self._generate_id(question)
        if example_id in self._examples:
            self._examples[example_id].success_count += 1
            self._save_to_disk()
    
    def record_failure(self, question: str):
        """记录失败使用"""
        example_id = self._generate_id(question)
        if example_id in self._examples:
            self._examples[example_id].fail_count += 1
            self._save_to_disk()
    
    def learn_from_success(self,
                            question: str,
                            sql: str,
                            datasource_id: int = None,
                            execution_time_ms: float = 0,
                            row_count: int = 0,
                            quality_threshold: float = 0.7,
                            similarity_threshold: float = 0.85):
        """
        从成功查询中自动学习 (P3增强版)

        智能判断是否值得学习:
        1. 质量评分: 基于SQL复杂度、执行效率、结果合理性
        2. 相似度检测: 避免重复添加相似示例
        3. 自动分类: 识别SQL模式
        4. 时间衰减: 考虑示例的新鲜度

        Args:
            question: 用户问题
            sql: 执行成功的SQL
            datasource_id: 数据源ID
            execution_time_ms: 执行时间(毫秒)
            row_count: 返回行数
            quality_threshold: 质量阈值(0-1), 低于此值不学习
            similarity_threshold: 相似度阈值(0-1), 超过此值认为重复
        """
        try:
            # 1. 计算质量分数
            quality = self._calculate_query_quality(
                sql, execution_time_ms, row_count
            )

            if quality < quality_threshold:
                logger.debug(f"Query quality too low ({quality:.2f} < {quality_threshold}), skip learning")
                return

            # 2. 检查是否已存在相似示例
            existing = self.retrieve(
                question,
                k=3,
                datasource_id=datasource_id,
                min_quality=0  # 包括所有示例
            )

            if existing:
                # 计算语义相似度
                max_similarity = self._calculate_similarity(question, existing[0]["question"])

                if max_similarity > similarity_threshold:
                    # 非常相似，更新现有示例
                    example_id = self._generate_id(existing[0]["question"])
                    if example_id in self._examples:
                        self._examples[example_id].success_count += 1
                        self._save_to_disk()
                        logger.info(f"Updated existing example success count: {existing[0]['question'][:30]}...")
                    return

            # 3. 新示例，自动添加
            pattern = self._classify_pattern(sql)
            difficulty = self._estimate_difficulty(sql)

            description = self._generate_description(sql, pattern, quality)

            example_id = self.add_example(
                question=question,
                sql=sql,
                description=description,
                datasource_id=datasource_id,
                difficulty=difficulty
            )

            # 初始化质量分数
            if example_id in self._examples:
                self._examples[example_id].success_count = 1
                self._save_to_disk()

            logger.info(f"✓ Learned new example (quality={quality:.2f}, pattern={pattern}): {question[:40]}...")

        except Exception as e:
            logger.error(f"Error in learn_from_success: {e}")

    def _calculate_query_quality(self, sql: str, execution_time_ms: float, row_count: int) -> float:
        """
        计算查询质量分数 (0-1)

        考虑因素:
        1. SQL复杂度 (30%): JOIN/窗口函数/CTE等高级特性
        2. 执行效率 (30%): 执行时间合理性
        3. 结果合理性 (30%): 返回行数合理性
        4. 语法规范 (10%): 是否有LIMIT等
        """
        score = 0.0

        sql_lower = sql.lower()

        # 1. SQL复杂度评分 (0-0.3)
        complexity_score = 0.0
        if " join " in sql_lower:
            complexity_score += 0.1
        if any(kw in sql_lower for kw in ["over", "partition by", "row_number"]):
            complexity_score += 0.1  # 窗口函数
        if "with " in sql_lower and " as (" in sql_lower:
            complexity_score += 0.1  # CTE
        if any(kw in sql_lower for kw in ["sum(", "count(", "avg(", "group by"]):
            complexity_score += 0.05  # 聚合
        if "having" in sql_lower:
            complexity_score += 0.05

        complexity_score = min(complexity_score, 0.3)
        score += complexity_score

        # 2. 执行效率评分 (0-0.3)
        if execution_time_ms > 0:
            if execution_time_ms < 100:
                efficiency_score = 0.3  # 极快
            elif execution_time_ms < 500:
                efficiency_score = 0.25  # 快
            elif execution_time_ms < 2000:
                efficiency_score = 0.2  # 正常
            elif execution_time_ms < 5000:
                efficiency_score = 0.1  # 慢
            else:
                efficiency_score = 0.05  # 很慢
        else:
            efficiency_score = 0.2  # 默认中等

        score += efficiency_score

        # 3. 结果合理性评分 (0-0.3)
        if row_count > 0:
            if 1 <= row_count <= 1000:
                result_score = 0.3  # 合理范围
            elif row_count < 1:
                result_score = 0.1  # 空结果
            elif row_count <= 10000:
                result_score = 0.2  # 较多
            else:
                result_score = 0.1  # 过多
        else:
            result_score = 0.15  # 未知

        score += result_score

        # 4. 语法规范评分 (0-0.1)
        syntax_score = 0.0
        if "limit" in sql_lower:
            syntax_score += 0.05
        if not any(kw in sql_lower for kw in ["select *", "select\n*", "select\t*"]):
            syntax_score += 0.05  # 不使用SELECT *

        score += syntax_score

        return min(score, 1.0)

    def _calculate_similarity(self, question1: str, question2: str) -> float:
        """
        计算两个问题的相似度 (0-1)

        简单实现: 基于词重叠率
        TODO: 可以用向量相似度替代
        """
        import re

        # 分词
        tokens1 = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', question1.lower()))
        tokens2 = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', question2.lower()))

        # 停用词
        stopwords = {'的', '了', '是', '在', '我', '有', '和', '查询', '统计', '显示'}
        tokens1 = tokens1 - stopwords
        tokens2 = tokens2 - stopwords

        if not tokens1 or not tokens2:
            return 0.0

        # Jaccard相似度
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0

    def _estimate_difficulty(self, sql: str) -> str:
        """
        估计SQL难度
        """
        sql_lower = sql.lower()

        # 复杂特征计数
        complex_features = 0

        if " join " in sql_lower:
            complex_features += 1
        if any(kw in sql_lower for kw in ["over", "partition by"]):
            complex_features += 2  # 窗口函数权重高
        if "with " in sql_lower:
            complex_features += 1
        if "(select " in sql_lower:
            complex_features += 1  # 子查询
        if "having" in sql_lower:
            complex_features += 1

        if complex_features >= 3:
            return "hard"
        elif complex_features >= 1:
            return "medium"
        else:
            return "easy"

    def _generate_description(self, sql: str, pattern: str, quality: float) -> str:
        """
        自动生成描述
        """
        pattern_desc = self.PATTERNS.get(pattern, {}).get("description", "查询")
        quality_desc = "高质量" if quality > 0.8 else "标准"

        return f"自动学习: {pattern_desc}, {quality_desc}示例 (质量分={quality:.2f})"
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        pattern_counts = defaultdict(int)
        quality_sum = 0.0
        
        for example in self._examples.values():
            pattern_counts[example.pattern] += 1
            quality_sum += example.quality_score
        
        return {
            "total_examples": len(self._examples),
            "by_pattern": dict(pattern_counts),
            "by_datasource": {
                ds_id: len(ids) 
                for ds_id, ids in self._datasource_examples.items()
            },
            "avg_quality": quality_sum / len(self._examples) if self._examples else 0,
            "patterns_available": list(self.PATTERNS.keys()),
        }


# 全局实例
few_shot_service = FewShotService()


def init_standard_examples():
    """
    初始化标准 Few-shot 示例
    
    这些示例覆盖常见 SQL 模式，并强调英文列别名规范
    """
    logger.info("Initializing standard Few-shot examples...")
    
    # 示例 1: 城市聚合统计（英文列别名）
    few_shot_service.add_example(
        question="统计2024年各城市的总销售额，按金额从高到低排序，取前5名",
        sql="""SELECT
    city,
    SUM(total_amount) AS total_amount
FROM sales_benchmark
WHERE EXTRACT(YEAR FROM date) = 2024
GROUP BY city
ORDER BY total_amount DESC
LIMIT 5""",
        description="城市级聚合: 使用英文别名 total_amount 而非'总销售额'。聚合函数必须有别名。",
        difficulty="medium"
    )
    
    # 示例 2: 产品销量聚合
    few_shot_service.add_example(
        question="找出销量最高的产品名称和销量",
        sql="""SELECT
    product_name,
    SUM(quantity) AS total_quantity
FROM sales_benchmark
GROUP BY product_name
ORDER BY total_quantity DESC
LIMIT 10""",
        description="产品聚合: 使用 SUM 汇总销量，使用英文别名 total_quantity。",
        difficulty="easy"
    )
    
    # 示例 3: 条件过滤
    few_shot_service.add_example(
        question="列出所有备注中包含'加急'或'包装'的订单",
        sql="""SELECT *
FROM sales_benchmark
WHERE remark LIKE '%加急%' OR remark LIKE '%包装%'
LIMIT 1000""",
        description="备注过滤: 使用 OR 条件查找匹配行。LIKE 用于模糊匹配。必须包含 LIMIT 限制。",
        difficulty="easy"
    )
    
    # 示例 4: NULL 处理
    few_shot_service.add_example(
        question="统计各客户来源的订单数量，包含来源为空的",
        sql="""SELECT
    COALESCE(source, 'empty') AS source,
    COUNT(*) AS order_count
FROM sales_benchmark
GROUP BY source
ORDER BY order_count DESC
LIMIT 1000""",
        description="NULL处理: 使用 COALESCE 将 NULL 转换为 'empty'。列别名使用英文。",
        difficulty="medium"
    )
    
    # 示例 5: 多表 JOIN
    few_shot_service.add_example(
        question="查询每个客户的订单总金额和订单数",
        sql="""SELECT
    c.customer_name,
    COUNT(o.order_id) AS order_count,
    SUM(o.amount) AS total_amount
FROM customers c
LEFT JOIN orders o ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.customer_name
ORDER BY total_amount DESC
LIMIT 100""",
        description="多表JOIN: LEFT JOIN 保证所有客户都会显示。GROUP BY 包含非聚合列。",
        difficulty="medium"
    )
    
    # 示例 6: 时间范围
    few_shot_service.add_example(
        question="查询最近7天的订单统计",
        sql="""SELECT
    DATE(created_at) AS order_date,
    COUNT(*) AS order_count,
    SUM(amount) AS total_amount
FROM orders
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY order_date DESC""",
        description="时间范围: 使用 INTERVAL 进行日期计算。按日期分组统计。",
        difficulty="medium"
    )
    
    # 示例 7: 子查询
    few_shot_service.add_example(
        question="找出销售额高于平均值的城市",
        sql="""SELECT
    city,
    SUM(amount) AS city_sales
FROM sales
GROUP BY city
HAVING SUM(amount) > (
    SELECT AVG(total_sales)
    FROM (
        SELECT SUM(amount) AS total_sales
        FROM sales
        GROUP BY city
    ) AS city_totals
)
ORDER BY city_sales DESC""",
        description="子查询: 使用子查询计算平均值，HAVING 进行过滤。",
        difficulty="hard"
    )
    
    # 示例 8: 窗口函数
    few_shot_service.add_example(
        question="按城市计算每个订单金额占该城市总额的百分比",
        sql="""SELECT
    city,
    order_id,
    amount,
    SUM(amount) OVER (PARTITION BY city) AS city_total,
    ROUND(amount * 100.0 / SUM(amount) OVER (PARTITION BY city), 2) AS percentage
FROM orders
ORDER BY city, percentage DESC""",
        description="窗口函数: OVER (PARTITION BY) 计算分组聚合但不减少行数。",
        difficulty="hard"
    )
    
    logger.info("Standard Few-shot examples initialized successfully")
