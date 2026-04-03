"""
多候选SQL生成器

核心设计（参考CHASE-SQL架构）：
1. 多策略生成 - 三种不同的SQL生成策略
   - Direct Translation: 直接翻译
   - Divide-and-Conquer CoT: 分解问题，逐步推理
   - Synthetic Few-shot: 基于相似案例生成
   
2. 候选多样性 - 每种策略生成多个候选
   - 默认: 3策略 x 2候选 = 6个候选SQL

3. Selection Agent - 成对比较选择最佳SQL
   - 二元分类器进行成对比较
   - 投票机制确定最终选择
"""

import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from fastapi_app.core.llm_factory import LLMFactory, LLMConfig
from fastapi_app.modules.rag.few_shot import few_shot_service

logger = logging.getLogger(__name__)


class GenerationStrategy(str, Enum):
    """SQL生成策略"""
    DIRECT = "direct"           # 直接翻译
    DIVIDE_CONQUER = "divide_conquer"  # 分解推理
    FEW_SHOT = "few_shot"       # Few-shot示例


@dataclass
class SQLCandidate:
    """SQL候选"""
    sql: str
    strategy: GenerationStrategy
    confidence: float = 0.0
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "strategy": self.strategy.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
        }


@dataclass
class SelectionResult:
    """选择结果"""
    selected_sql: str
    selected_candidate: SQLCandidate
    all_candidates: List[SQLCandidate]
    selection_scores: Dict[str, float]  # sql -> score
    selection_reasoning: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_sql": self.selected_sql,
            "selected_candidate": self.selected_candidate.to_dict(),
            "all_candidates": [c.to_dict() for c in self.all_candidates],
            "selection_scores": self.selection_scores,
            "selection_reasoning": self.selection_reasoning,
        }


class MultiCandidateGenerator:
    """
    多候选SQL生成器
    
    用法：
    ```python
    generator = MultiCandidateGenerator()
    
    candidates = await generator.generate(
        question="统计2024年各城市销售额",
        schema_info={"tables": [...], ...},
        strategies=[GenerationStrategy.DIRECT, GenerationStrategy.DIVIDE_CONQUER],
        candidates_per_strategy=2
    )
    ```
    """
    
    # 生成策略的Prompt模板
    DIRECT_PROMPT = """你是SQL专家。请直接将用户问题翻译为SQL查询。

【数据库Schema】
{schema_info}

【用户问题】
{question}

【要求】
1. 直接生成SQL，不需要解释
2. 确保SQL语法正确
3. 使用标准SQL语法
4. 所有列别名使用英文

请只返回SQL语句，不要其他内容。
"""

    DIVIDE_CONQUER_PROMPT = """你是SQL专家。请使用分解推理的方法生成SQL。

【数据库Schema】
{schema_info}

【用户问题】
{question}

【分解推理步骤】
1. 分析问题：这个问题要查询什么？
2. 识别涉及的表：需要哪些表？
3. 确定筛选条件：WHERE子句需要什么？
4. 确定聚合方式：需要GROUP BY吗？需要什么聚合函数？
5. 确定排序和限制：需要ORDER BY和LIMIT吗？
6. 组合成完整SQL

请按照上述步骤思考，然后在最后一行给出最终的SQL语句。
格式：
SQL: <你的SQL语句>
"""

    FEW_SHOT_PROMPT = """你是SQL专家。请参考以下相似案例生成SQL。

【数据库Schema】
{schema_info}

【相似案例】
{examples}

【用户问题】
{question}

【要求】
1. 参考相似案例的SQL结构
2. 根据当前问题调整SQL
3. 确保SQL语法正确
4. 所有列别名使用英文

请只返回SQL语句，不要其他内容。
"""

    def __init__(self, 
                 llm: Optional[BaseChatModel] = None,
                 llm_config: Optional[LLMConfig] = None):
        """
        初始化生成器
        
        Args:
            llm: LLM实例
            llm_config: LLM配置
        """
        self._llm = llm
        if not self._llm:
            if llm_config:
                self._llm = LLMFactory.create_llm(llm_config)
            else:
                self._llm = LLMFactory.from_settings()
        
        self._executor = ThreadPoolExecutor(max_workers=6)
    
    async def generate(self,
                       question: str,
                       schema_info: str,
                       strategies: Optional[List[GenerationStrategy]] = None,
                       candidates_per_strategy: int = 2,
                       few_shot_examples: Optional[List[Dict]] = None) -> List[SQLCandidate]:
        """
        生成多个SQL候选
        
        Args:
            question: 用户问题
            schema_info: 数据库Schema信息
            strategies: 使用的生成策略列表（默认全部）
            candidates_per_strategy: 每种策略生成的候选数
            few_shot_examples: Few-shot示例（可选）
            
        Returns:
            SQL候选列表
        """
        if strategies is None:
            strategies = [
                GenerationStrategy.DIRECT,
                GenerationStrategy.DIVIDE_CONQUER,
                GenerationStrategy.FEW_SHOT,
            ]
        
        # 获取Few-shot示例
        if few_shot_examples is None and GenerationStrategy.FEW_SHOT in strategies:
            try:
                few_shot_examples = few_shot_service.retrieve(question)
            except:
                few_shot_examples = []
        
        # 并发生成
        all_candidates = []
        
        tasks = []
        for strategy in strategies:
            for i in range(candidates_per_strategy):
                tasks.append(
                    self._generate_single(
                        question, schema_info, strategy, 
                        few_shot_examples, i
                    )
                )
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, SQLCandidate):
                all_candidates.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"Generation failed: {result}")
        
        logger.info(f"Generated {len(all_candidates)} SQL candidates")
        return all_candidates
    
    async def _generate_single(self,
                                question: str,
                                schema_info: str,
                                strategy: GenerationStrategy,
                                few_shot_examples: Optional[List[Dict]],
                                attempt: int) -> SQLCandidate:
        """生成单个候选"""
        try:
            # 构建Prompt
            if strategy == GenerationStrategy.DIRECT:
                prompt = self.DIRECT_PROMPT.format(
                    schema_info=schema_info,
                    question=question
                )
            elif strategy == GenerationStrategy.DIVIDE_CONQUER:
                prompt = self.DIVIDE_CONQUER_PROMPT.format(
                    schema_info=schema_info,
                    question=question
                )
            elif strategy == GenerationStrategy.FEW_SHOT:
                examples_str = self._format_examples(few_shot_examples)
                prompt = self.FEW_SHOT_PROMPT.format(
                    schema_info=schema_info,
                    examples=examples_str,
                    question=question
                )
            else:
                prompt = self.DIRECT_PROMPT.format(
                    schema_info=schema_info,
                    question=question
                )
            
            # 调用LLM
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self._executor,
                lambda: self._llm.invoke([HumanMessage(content=prompt)])
            )
            
            # 解析SQL
            sql = self._extract_sql(response.content, strategy)
            reasoning = response.content if strategy == GenerationStrategy.DIVIDE_CONQUER else ""
            
            return SQLCandidate(
                sql=sql,
                strategy=strategy,
                confidence=0.5 + attempt * 0.1,  # 基础置信度
                reasoning=reasoning,
                metadata={"attempt": attempt}
            )
            
        except Exception as e:
            logger.error(f"Generation error ({strategy}): {e}")
            raise
    
    def _format_examples(self, examples: Optional[List[Dict]]) -> str:
        """格式化Few-shot示例"""
        if not examples:
            return "无相似案例"
        
        formatted = []
        for i, ex in enumerate(examples[:3], 1):
            formatted.append(f"""
案例{i}:
问题: {ex.get('question', '')}
SQL: {ex.get('sql', '')}
""")
        return "\n".join(formatted)
    
    def _extract_sql(self, content: str, strategy: GenerationStrategy) -> str:
        """从LLM响应中提取SQL"""
        content = content.strip()
        
        # 尝试提取SQL代码块
        sql_match = re.search(r'```sql\s*(.*?)\s*```', content, re.DOTALL | re.IGNORECASE)
        if sql_match:
            return sql_match.group(1).strip()
        
        # 尝试提取一般代码块
        code_match = re.search(r'```\s*(.*?)\s*```', content, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        
        # 对于分解推理策略，查找"SQL:"标记
        if strategy == GenerationStrategy.DIVIDE_CONQUER:
            sql_line = re.search(r'SQL:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
            if sql_line:
                return sql_line.group(1).strip()
        
        # 尝试找到SELECT语句
        select_match = re.search(r'(SELECT\s+.+)', content, re.DOTALL | re.IGNORECASE)
        if select_match:
            sql = select_match.group(1)
            # 清理可能的尾部解释
            sql = re.split(r'\n\s*\n', sql)[0]
            return sql.strip()
        
        # 返回整个内容
        return content


class SelectionAgent:
    """
    Selection Agent - SQL候选选择器
    
    使用成对比较的方式选择最佳SQL：
    1. 将候选两两比较
    2. 每次比较产生一个胜者
    3. 统计每个候选的胜出次数
    4. 选择胜出次数最多的候选
    
    参考CHASE-SQL的Pairwise Binary Classifier设计
    """
    
    COMPARISON_PROMPT = """你是SQL质量评估专家。请比较以下两个SQL查询，选择更好的一个。

【用户问题】
{question}

【数据库Schema】
{schema_info}

【SQL候选A】
{sql_a}

【SQL候选B】
{sql_b}

【评估标准】
1. 正确性：是否正确回答了问题
2. 完整性：是否包含所有必要的条件
3. 效率：查询是否高效
4. 规范性：SQL风格是否规范

请选择更好的SQL，只返回 "A" 或 "B"，不要其他内容。
"""

    def __init__(self,
                 llm: Optional[BaseChatModel] = None,
                 llm_config: Optional[LLMConfig] = None):
        """初始化选择器"""
        self._llm = llm
        if not self._llm:
            if llm_config:
                self._llm = LLMFactory.create_llm(llm_config)
            else:
                self._llm = LLMFactory.from_settings()
        
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    async def select_best(self,
                          candidates: List[SQLCandidate],
                          question: str,
                          schema_info: str) -> SelectionResult:
        """
        选择最佳SQL候选
        
        Args:
            candidates: SQL候选列表
            question: 用户问题
            schema_info: 数据库Schema信息
            
        Returns:
            SelectionResult: 选择结果
        """
        if not candidates:
            raise ValueError("No candidates to select from")
        
        if len(candidates) == 1:
            return SelectionResult(
                selected_sql=candidates[0].sql,
                selected_candidate=candidates[0],
                all_candidates=candidates,
                selection_scores={candidates[0].sql: 1.0},
                selection_reasoning="Only one candidate",
            )
        
        # 去重（基于SQL文本）
        unique_candidates = self._deduplicate(candidates)
        
        if len(unique_candidates) == 1:
            return SelectionResult(
                selected_sql=unique_candidates[0].sql,
                selected_candidate=unique_candidates[0],
                all_candidates=candidates,
                selection_scores={unique_candidates[0].sql: 1.0},
                selection_reasoning="All candidates are identical",
            )
        
        # 成对比较
        wins = {c.sql: 0 for c in unique_candidates}
        comparisons = []
        
        for i in range(len(unique_candidates)):
            for j in range(i + 1, len(unique_candidates)):
                comparisons.append((unique_candidates[i], unique_candidates[j]))
        
        # 并发执行比较
        tasks = [
            self._compare_pair(a, b, question, schema_info)
            for a, b in comparisons
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for (a, b), result in zip(comparisons, results):
            if isinstance(result, str):
                if result == "A":
                    wins[a.sql] += 1
                elif result == "B":
                    wins[b.sql] += 1
                else:
                    # 平局，两边各加0.5
                    wins[a.sql] += 0.5
                    wins[b.sql] += 0.5
        
        # 选择胜出次数最多的
        total_comparisons = len(comparisons)
        scores = {sql: w / total_comparisons for sql, w in wins.items()}
        
        best_sql = max(wins, key=wins.get)
        best_candidate = next(c for c in unique_candidates if c.sql == best_sql)
        
        return SelectionResult(
            selected_sql=best_sql,
            selected_candidate=best_candidate,
            all_candidates=candidates,
            selection_scores=scores,
            selection_reasoning=f"Selected based on {total_comparisons} pairwise comparisons. "
                              f"Winner score: {scores[best_sql]:.2f}",
        )
    
    async def _compare_pair(self,
                            candidate_a: SQLCandidate,
                            candidate_b: SQLCandidate,
                            question: str,
                            schema_info: str) -> str:
        """比较两个候选"""
        try:
            prompt = self.COMPARISON_PROMPT.format(
                question=question,
                schema_info=schema_info,
                sql_a=candidate_a.sql,
                sql_b=candidate_b.sql,
            )
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self._executor,
                lambda: self._llm.invoke([HumanMessage(content=prompt)])
            )
            
            content = response.content.strip().upper()
            
            if "A" in content and "B" not in content:
                return "A"
            elif "B" in content and "A" not in content:
                return "B"
            else:
                # 无法确定，返回平局
                return "TIE"
                
        except Exception as e:
            logger.warning(f"Comparison failed: {e}")
            return "TIE"
    
    def _deduplicate(self, candidates: List[SQLCandidate]) -> List[SQLCandidate]:
        """去除重复的SQL候选"""
        seen = set()
        unique = []
        
        for c in candidates:
            # 归一化SQL进行比较
            normalized = self._normalize_sql(c.sql)
            if normalized not in seen:
                seen.add(normalized)
                unique.append(c)
        
        return unique
    
    def _normalize_sql(self, sql: str) -> str:
        """归一化SQL（用于比较）"""
        # 转小写
        sql = sql.lower()
        # 移除多余空格
        sql = re.sub(r'\s+', ' ', sql)
        # 移除末尾分号
        sql = sql.rstrip(';')
        return sql.strip()


class MultiCandidateSQLGenerator:
    """
    完整的多候选SQL生成流程
    
    结合生成器和选择器，提供端到端的SQL生成
    """
    
    def __init__(self,
                 generator: Optional[MultiCandidateGenerator] = None,
                 selector: Optional[SelectionAgent] = None,
                 llm_config: Optional[LLMConfig] = None):
        """初始化"""
        self.generator = generator or MultiCandidateGenerator(llm_config=llm_config)
        self.selector = selector or SelectionAgent(llm_config=llm_config)
    
    async def generate_and_select(self,
                                   question: str,
                                   schema_info: str,
                                   strategies: Optional[List[GenerationStrategy]] = None,
                                   candidates_per_strategy: int = 2) -> SelectionResult:
        """
        生成并选择最佳SQL
        
        Args:
            question: 用户问题
            schema_info: 数据库Schema信息
            strategies: 使用的生成策略
            candidates_per_strategy: 每种策略的候选数
            
        Returns:
            SelectionResult: 选择结果
        """
        # 1. 生成候选
        candidates = await self.generator.generate(
            question=question,
            schema_info=schema_info,
            strategies=strategies,
            candidates_per_strategy=candidates_per_strategy,
        )
        
        if not candidates:
            raise ValueError("Failed to generate any SQL candidates")
        
        # 2. 选择最佳
        result = await self.selector.select_best(
            candidates=candidates,
            question=question,
            schema_info=schema_info,
        )
        
        logger.info(f"Selected SQL from {len(candidates)} candidates: {result.selected_sql[:100]}...")
        return result


# 全局实例
multi_candidate_generator = MultiCandidateSQLGenerator()




