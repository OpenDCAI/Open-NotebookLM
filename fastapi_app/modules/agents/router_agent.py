"""
Router Agent - 智能路由系统

核心设计（参考agent设计_v3_最终版.md）：
1. 快速路径(70%) - 简单查询，3-5秒，$0.005
2. 标准路径(25%) - 中等复杂度，8-12秒，$0.03
3. 完整路径(5%) - 复杂查询，20-30秒，$0.15

路由判断依据：
- 问题复杂度（关键词、句子结构）
- 涉及表数量预估
- 是否需要多表JOIN
- 是否需要复杂聚合
- 是否有歧义需要澄清
"""

import re
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from fastapi_app.core.config import settings
from fastapi_app.core.llm_factory import LLMFactory, LLMConfig

logger = logging.getLogger(__name__)


class QueryComplexity(str, Enum):
    """查询复杂度级别"""
    SIMPLE = "simple"      # 简单查询：单表，简单条件
    MEDIUM = "medium"      # 中等查询：多表JOIN，聚合函数
    COMPLEX = "complex"    # 复杂查询：复杂子查询，多层聚合，窗口函数


class RoutingPath(str, Enum):
    """路由路径"""
    FAST = "fast"          # 快速路径：跳过完整Schema检索
    STANDARD = "standard"  # 标准路径：常规流程
    FULL = "full"          # 完整路径：多候选生成+选择


@dataclass
class RoutingDecision:
    """路由决策结果"""
    path: RoutingPath
    complexity: QueryComplexity
    confidence: float  # 置信度 0-1
    reasoning: str     # 决策原因
    
    # 路径参数
    skip_full_schema_retrieval: bool = False
    use_multi_candidate: bool = False
    max_retrieval_tables: int = 5
    need_clarification: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path.value,
            "complexity": self.complexity.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "skip_full_schema_retrieval": self.skip_full_schema_retrieval,
            "use_multi_candidate": self.use_multi_candidate,
            "max_retrieval_tables": self.max_retrieval_tables,
            "need_clarification": self.need_clarification,
        }


class RouterAgent:
    """
    智能路由Agent
    
    功能：
    1. 分析查询复杂度
    2. 选择最优路径
    3. 配置路径参数
    
    用法：
    ```python
    router = RouterAgent()
    decision = router.route(
        question="查询2024年销售额最高的城市",
        schema_summary={"table_count": 10, "tables": ["sales", "cities", ...]}
    )
    
    if decision.path == RoutingPath.FAST:
        # 使用快速路径
        pass
    elif decision.path == RoutingPath.STANDARD:
        # 使用标准路径
        pass
    else:
        # 使用完整路径
        pass
    ```
    """
    
    # 复杂度关键词
    SIMPLE_KEYWORDS = {
        '查询', '显示', '列出', '获取', '查看', '多少', '几个',
        'select', 'show', 'list', 'get', 'count', 'how many',
    }
    
    MEDIUM_KEYWORDS = {
        '统计', '汇总', '分组', '排名', '前几', 'top', '每个', '各个',
        '最大', '最小', '平均', '总计', '合计',
        'group', 'sum', 'avg', 'max', 'min', 'total', 'aggregate',
        '按照', '根据', 'by', '时间段', '范围',
    }
    
    COMPLEX_KEYWORDS = {
        '对比', '比较', '同比', '环比', '增长率', '占比', '趋势',
        '关联', '关系', '层级', '递归', '窗口', '累计',
        '子查询', '嵌套', '多条件', '复杂',
        'compare', 'trend', 'ratio', 'percent', 'window', 'recursive',
        'versus', 'vs', 'correlation',
    }
    
    # 歧义关键词（可能需要澄清）
    AMBIGUOUS_KEYWORDS = {
        '销售', '收入', '业绩', '数据', '情况', '信息', '详情',
        'sales', 'revenue', 'data', 'info', 'details',
    }
    
    def __init__(self, 
                 use_llm: bool = False,
                 llm_config: Optional[LLMConfig] = None):
        """
        初始化路由Agent
        
        Args:
            use_llm: 是否使用LLM进行复杂度判断（更准确但更慢）
            llm_config: LLM配置（use_llm=True时使用）
        """
        self.use_llm = use_llm
        self._llm = None
        
        if use_llm:
            if llm_config:
                self._llm = LLMFactory.create_llm(llm_config)
            else:
                # 使用小模型进行路由
                self._llm = LLMFactory.from_settings()
    
    def route(self,
              question: str,
              schema_summary: Optional[Dict[str, Any]] = None,
              history_context: Optional[List[str]] = None) -> RoutingDecision:
        """
        执行路由决策
        
        Args:
            question: 用户问题
            schema_summary: Schema摘要信息（可选）
            history_context: 历史对话上下文（可选）
            
        Returns:
            RoutingDecision: 路由决策
        """
        # 1. 规则基础的快速判断
        rule_based_result = self._rule_based_classify(question)
        
        # 2. 如果规则判断置信度高，直接返回
        if rule_based_result[1] >= 0.8:
            complexity, confidence, reasoning = rule_based_result
            return self._build_decision(complexity, confidence, reasoning)
        
        # 3. 如果启用LLM且规则判断不确定，使用LLM
        if self.use_llm and self._llm and rule_based_result[1] < 0.6:
            llm_result = self._llm_classify(question, schema_summary)
            if llm_result:
                return llm_result
        
        # 4. 使用规则判断结果
        complexity, confidence, reasoning = rule_based_result
        return self._build_decision(complexity, confidence, reasoning)
    
    def _rule_based_classify(self, question: str) -> Tuple[QueryComplexity, float, str]:
        """
        基于规则的复杂度分类
        
        Returns:
            (复杂度, 置信度, 原因)
        """
        question_lower = question.lower()
        
        # 计算各类关键词命中数
        simple_hits = sum(1 for kw in self.SIMPLE_KEYWORDS if kw in question_lower)
        medium_hits = sum(1 for kw in self.MEDIUM_KEYWORDS if kw in question_lower)
        complex_hits = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in question_lower)
        
        # 检查问题长度
        question_length = len(question)
        
        # 检查是否有多个条件（AND/OR）
        has_multi_conditions = bool(re.search(r'(并且|而且|或者|和|与|and|or|,|，)', question_lower))
        
        # 检查是否有时间范围
        has_time_range = bool(re.search(
            r'(\d{4}年|\d{1,2}月|今年|去年|本月|上月|最近|过去|从.*到|between)',
            question_lower
        ))
        
        # 检查是否可能涉及多表
        multi_entity_patterns = [
            r'(.*的.*的)',  # 嵌套"的"
            r'(每个|各个|各.*的)',  # 分组暗示
            r'(和|与|以及).*关系',  # 关联关系
        ]
        has_multi_entity = any(re.search(p, question) for p in multi_entity_patterns)
        
        # 综合判断
        complexity_score = (
            simple_hits * -1 +
            medium_hits * 1 +
            complex_hits * 2 +
            (1 if has_multi_conditions else 0) +
            (0.5 if has_time_range else 0) +
            (1 if has_multi_entity else 0) +
            (0.5 if question_length > 50 else 0) +
            (1 if question_length > 100 else 0)
        )
        
        # 确定复杂度
        if complexity_score <= 0:
            complexity = QueryComplexity.SIMPLE
            confidence = min(0.9, 0.7 + abs(complexity_score) * 0.1)
            reasoning = f"简单查询：关键词匹配(简单:{simple_hits})"
        elif complexity_score <= 2:
            complexity = QueryComplexity.MEDIUM
            confidence = 0.6 + min(0.3, complexity_score * 0.1)
            reasoning = f"中等查询：关键词匹配(中等:{medium_hits})，多条件:{has_multi_conditions}，时间范围:{has_time_range}"
        else:
            complexity = QueryComplexity.COMPLEX
            confidence = min(0.9, 0.6 + complex_hits * 0.1)
            reasoning = f"复杂查询：关键词匹配(复杂:{complex_hits})，多实体:{has_multi_entity}，问题长度:{question_length}"
        
        return complexity, confidence, reasoning
    
    def _llm_classify(self, 
                      question: str,
                      schema_summary: Optional[Dict[str, Any]] = None) -> Optional[RoutingDecision]:
        """使用LLM进行复杂度分类"""
        try:
            schema_info = ""
            if schema_summary:
                table_count = schema_summary.get("table_count", 0)
                tables = schema_summary.get("tables", [])[:10]
                schema_info = f"\n数据源包含{table_count}个表，部分表名：{', '.join(tables)}"
            
            prompt = f"""分析以下数据查询问题的复杂度，返回JSON格式结果。

问题：{question}
{schema_info}

分析维度：
1. 是否涉及单表还是多表
2. 是否需要聚合函数
3. 是否需要子查询
4. 是否有复杂的时间范围或条件
5. 是否有歧义需要澄清

返回格式（只返回JSON，不要其他内容）：
{{"complexity": "simple|medium|complex", "confidence": 0.0-1.0, "reasoning": "原因", "need_clarification": true|false}}"""

            response = self._llm.invoke([
                SystemMessage(content="你是SQL查询复杂度分析专家。只返回JSON格式结果。"),
                HumanMessage(content=prompt)
            ])
            
            # 解析响应
            import json
            content = response.content.strip()
            # 尝试提取JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                
                complexity = QueryComplexity(result.get("complexity", "medium"))
                confidence = float(result.get("confidence", 0.7))
                reasoning = result.get("reasoning", "LLM分析")
                need_clarification = result.get("need_clarification", False)
                
                decision = self._build_decision(complexity, confidence, reasoning)
                decision.need_clarification = need_clarification
                return decision
                
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")
        
        return None
    
    def _build_decision(self,
                        complexity: QueryComplexity,
                        confidence: float,
                        reasoning: str) -> RoutingDecision:
        """构建路由决策"""
        # 根据复杂度确定路径和参数
        if complexity == QueryComplexity.SIMPLE:
            return RoutingDecision(
                path=RoutingPath.FAST,
                complexity=complexity,
                confidence=confidence,
                reasoning=reasoning,
                skip_full_schema_retrieval=True,
                use_multi_candidate=False,
                max_retrieval_tables=3,
                need_clarification=False,
            )
        elif complexity == QueryComplexity.MEDIUM:
            return RoutingDecision(
                path=RoutingPath.STANDARD,
                complexity=complexity,
                confidence=confidence,
                reasoning=reasoning,
                skip_full_schema_retrieval=False,
                use_multi_candidate=False,
                max_retrieval_tables=5,
                need_clarification=False,
            )
        else:  # COMPLEX
            return RoutingDecision(
                path=RoutingPath.FULL,
                complexity=complexity,
                confidence=confidence,
                reasoning=reasoning,
                skip_full_schema_retrieval=False,
                use_multi_candidate=True,
                max_retrieval_tables=10,
                need_clarification=self._check_need_clarification(reasoning),
            )
    
    def _check_need_clarification(self, question: str) -> bool:
        """检查是否需要澄清"""
        question_lower = question.lower()
        
        # 检查歧义关键词
        ambiguous_count = sum(1 for kw in self.AMBIGUOUS_KEYWORDS if kw in question_lower)
        
        # 如果歧义词多且问题短，可能需要澄清
        if ambiguous_count >= 2 and len(question) < 30:
            return True
        
        # 检查是否缺少关键信息（如时间范围）
        has_aggregate = any(kw in question_lower for kw in ['统计', '汇总', '总', 'sum', 'total'])
        has_time = bool(re.search(r'(\d{4}|今年|去年|本月|最近)', question_lower))
        
        if has_aggregate and not has_time:
            return True
        
        return False
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """获取路由统计信息"""
        return {
            "use_llm": self.use_llm,
            "llm_available": self._llm is not None,
            "simple_keywords_count": len(self.SIMPLE_KEYWORDS),
            "medium_keywords_count": len(self.MEDIUM_KEYWORDS),
            "complex_keywords_count": len(self.COMPLEX_KEYWORDS),
        }


class RoutingPathExecutor:
    """
    路由路径执行器
    
    根据路由决策配置Agent的执行参数
    """
    
    @staticmethod
    def configure_agent_params(decision: RoutingDecision) -> Dict[str, Any]:
        """
        根据路由决策配置Agent参数
        
        Returns:
            Agent配置参数字典
        """
        if decision.path == RoutingPath.FAST:
            return {
                "max_retries": 2,
                "schema_retrieval_top_k": 3,
                "skip_detailed_schema": True,
                "use_simple_prompt": True,
                "enable_multi_candidate": False,
                "timeout_seconds": 15,
            }
        elif decision.path == RoutingPath.STANDARD:
            return {
                "max_retries": 3,
                "schema_retrieval_top_k": 5,
                "skip_detailed_schema": False,
                "use_simple_prompt": False,
                "enable_multi_candidate": False,
                "timeout_seconds": 30,
            }
        else:  # FULL
            return {
                "max_retries": 4,
                "schema_retrieval_top_k": 10,
                "skip_detailed_schema": False,
                "use_simple_prompt": False,
                "enable_multi_candidate": True,
                "candidate_count": 3,
                "timeout_seconds": 60,
            }


# 全局路由Agent实例
router_agent = RouterAgent(use_llm=False)  # 默认使用规则路由（更快）




