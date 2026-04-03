"""
Clarification Agent - 交互追问Agent

核心功能：
1. 歧义检测 - 识别问题中的模糊表达
2. 信息缺失检测 - 识别缺少的关键信息（时间范围、维度等）
3. 追问生成 - 生成精准的追问问题
4. 上下文整合 - 将用户回答整合到原问题中

设计原则：
- 最多追问1轮，避免过度打扰用户
- 追问问题要精准、具体
- 提供选项供用户选择（减少用户输入成本）

示例场景：
- 用户："看下销售" → 追问"您是想查询销售额还是销量？"
- 用户："统计订单" → 追问"请问需要统计哪个时间段的订单？"
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from fastapi_app.core.llm_factory import LLMFactory, LLMConfig

logger = logging.getLogger(__name__)


class AmbiguityType(str, Enum):
    """歧义类型"""
    METRIC_AMBIGUOUS = "metric_ambiguous"      # 指标歧义（销售额vs销量）
    TIME_MISSING = "time_missing"              # 时间缺失
    DIMENSION_UNCLEAR = "dimension_unclear"    # 维度不明确
    ENTITY_AMBIGUOUS = "entity_ambiguous"      # 实体歧义（哪个产品/客户）
    SCOPE_UNCLEAR = "scope_unclear"            # 范围不明确
    AGGREGATION_UNCLEAR = "aggregation_unclear"  # 聚合方式不明确


@dataclass
class Ambiguity:
    """歧义信息"""
    ambiguity_type: AmbiguityType
    description: str
    suggestions: List[str]  # 建议选项
    priority: int = 0       # 优先级（数字越小优先级越高）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.ambiguity_type.value,
            "description": self.description,
            "suggestions": self.suggestions,
            "priority": self.priority,
        }


@dataclass
class ClarificationQuestion:
    """追问问题"""
    question: str
    options: List[str]
    ambiguity: Ambiguity
    allow_custom_input: bool = True  # 是否允许用户自定义输入
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "options": self.options,
            "ambiguity": self.ambiguity.to_dict(),
            "allow_custom_input": self.allow_custom_input,
        }


@dataclass
class ClarificationResult:
    """澄清结果"""
    need_clarification: bool
    clarification_question: Optional[ClarificationQuestion] = None
    refined_question: Optional[str] = None  # 整合用户回答后的问题
    all_ambiguities: List[Ambiguity] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "need_clarification": self.need_clarification,
            "clarification_question": self.clarification_question.to_dict() if self.clarification_question else None,
            "refined_question": self.refined_question,
            "all_ambiguities": [a.to_dict() for a in self.all_ambiguities],
        }


class ClarificationAgent:
    """
    交互追问Agent
    
    用法：
    ```python
    agent = ClarificationAgent()
    
    # 检查是否需要澄清
    result = agent.check_ambiguity(
        question="看下销售",
        schema_info={"tables": [...]}
    )
    
    if result.need_clarification:
        # 向用户展示追问
        print(result.clarification_question.question)
        print("选项:", result.clarification_question.options)
        
        # 获取用户回答后整合
        user_answer = "销售额"
        refined = agent.integrate_answer(
            original_question="看下销售",
            clarification=result.clarification_question,
            user_answer=user_answer
        )
        # refined = "查询销售额"
    ```
    """
    
    # 常见歧义模式
    METRIC_AMBIGUOUS_PATTERNS = {
        r'销售|收入': {
            'description': '销售指标不明确',
            'suggestions': ['销售额（金额）', '销量（数量）', '订单数'],
        },
        r'业绩|绩效': {
            'description': '业绩指标不明确',
            'suggestions': ['销售业绩', '完成率', '环比增长'],
        },
        r'用户|客户': {
            'description': '用户指标不明确',
            'suggestions': ['用户数', '新增用户', '活跃用户'],
        },
        r'订单': {
            'description': '订单指标不明确',
            'suggestions': ['订单数', '订单金额', '平均订单金额'],
        },
    }
    
    # 时间相关模式
    TIME_PATTERNS = [
        r'\d{4}年', r'\d{1,2}月', r'今年', r'去年', r'本月', r'上月',
        r'最近\d+天', r'过去\d+', r'从.*到', r'Q[1-4]', r'第[一二三四]季度',
    ]
    
    # 需要时间范围的聚合词
    AGGREGATION_KEYWORDS = [
        '统计', '汇总', '合计', '总计', '分析', '趋势', '对比', '比较',
        '平均', '总', '累计', '环比', '同比',
    ]
    
    def __init__(self,
                 use_llm: bool = False,
                 llm_config: Optional[LLMConfig] = None,
                 max_clarifications: int = 1):
        """
        初始化澄清Agent
        
        Args:
            use_llm: 是否使用LLM进行复杂歧义检测
            llm_config: LLM配置
            max_clarifications: 最大追问次数
        """
        self.use_llm = use_llm
        self.max_clarifications = max_clarifications
        self._llm = None
        
        if use_llm:
            if llm_config:
                self._llm = LLMFactory.create_llm(llm_config)
            else:
                self._llm = LLMFactory.from_settings()
    
    def check_ambiguity(self,
                        question: str,
                        schema_info: Optional[Dict[str, Any]] = None,
                        dgp_config: Optional[Dict[str, Any]] = None) -> ClarificationResult:
        """
        检查问题中的歧义
        
        Args:
            question: 用户问题
            schema_info: Schema信息（可选）
            dgp_config: 数据治理配置（可选，包含指标定义等）
            
        Returns:
            ClarificationResult: 澄清检测结果
        """
        ambiguities = []
        
        # 1. 检测指标歧义
        metric_ambiguity = self._check_metric_ambiguity(question)
        if metric_ambiguity:
            ambiguities.append(metric_ambiguity)
        
        # 2. 检测时间缺失
        time_ambiguity = self._check_time_missing(question)
        if time_ambiguity:
            ambiguities.append(time_ambiguity)
        
        # 3. 检测维度不明确
        dimension_ambiguity = self._check_dimension_unclear(question, schema_info)
        if dimension_ambiguity:
            ambiguities.append(dimension_ambiguity)
        
        # 4. 检测范围不明确
        scope_ambiguity = self._check_scope_unclear(question)
        if scope_ambiguity:
            ambiguities.append(scope_ambiguity)
        
        # 5. 如果启用LLM，进行更深入的检测
        if self.use_llm and self._llm and not ambiguities:
            llm_ambiguities = self._llm_check_ambiguity(question, schema_info)
            ambiguities.extend(llm_ambiguities)
        
        # 如果没有歧义，返回无需澄清
        if not ambiguities:
            return ClarificationResult(
                need_clarification=False,
                all_ambiguities=[],
            )
        
        # 按优先级排序，选择最重要的歧义进行追问
        ambiguities.sort(key=lambda x: x.priority)
        top_ambiguity = ambiguities[0]
        
        # 生成追问问题
        clarification_q = self._generate_clarification_question(top_ambiguity, question)
        
        return ClarificationResult(
            need_clarification=True,
            clarification_question=clarification_q,
            all_ambiguities=ambiguities,
        )
    
    def _check_metric_ambiguity(self, question: str) -> Optional[Ambiguity]:
        """检测指标歧义"""
        for pattern, info in self.METRIC_AMBIGUOUS_PATTERNS.items():
            if re.search(pattern, question):
                # 检查是否已经明确了指标
                clarified_patterns = [
                    r'销售额', r'销量', r'订单数', r'用户数', r'金额', r'数量',
                    r'业绩.*额', r'完成率', r'增长率',
                ]
                if any(re.search(p, question) for p in clarified_patterns):
                    continue
                
                return Ambiguity(
                    ambiguity_type=AmbiguityType.METRIC_AMBIGUOUS,
                    description=info['description'],
                    suggestions=info['suggestions'],
                    priority=0,  # 最高优先级
                )
        
        return None
    
    def _check_time_missing(self, question: str) -> Optional[Ambiguity]:
        """检测时间缺失"""
        # 检查是否有聚合关键词
        has_aggregation = any(kw in question for kw in self.AGGREGATION_KEYWORDS)
        
        if not has_aggregation:
            return None
        
        # 检查是否已经有时间信息
        has_time = any(re.search(p, question) for p in self.TIME_PATTERNS)
        
        if has_time:
            return None
        
        # 生成时间建议
        import datetime
        current_year = datetime.datetime.now().year
        current_month = datetime.datetime.now().month
        
        suggestions = [
            f'{current_year}年',
            f'{current_year}年{current_month}月',
            '最近30天',
            '最近7天',
            f'{current_year-1}年全年',
        ]
        
        return Ambiguity(
            ambiguity_type=AmbiguityType.TIME_MISSING,
            description='缺少时间范围，无法确定统计周期',
            suggestions=suggestions,
            priority=1,
        )
    
    def _check_dimension_unclear(self, 
                                  question: str,
                                  schema_info: Optional[Dict[str, Any]]) -> Optional[Ambiguity]:
        """检测维度不明确"""
        # 检查是否有"每个"、"各"等分组暗示
        group_patterns = [r'每个', r'各', r'按', r'分.*统计']
        has_group_hint = any(re.search(p, question) for p in group_patterns)
        
        if not has_group_hint:
            return None
        
        # 检查是否已经明确了维度
        dimension_patterns = [
            r'按(城市|省份|区域|地区)', r'按(产品|商品|类别|分类)',
            r'按(客户|用户|会员)', r'按(时间|日期|月份|季度|年)',
            r'每个(城市|省份|产品|客户|用户|月|天)',
        ]
        has_dimension = any(re.search(p, question) for p in dimension_patterns)
        
        if has_dimension:
            return None
        
        # 从Schema中推断可能的维度
        suggestions = ['按城市', '按产品类别', '按月份', '按客户']
        
        if schema_info and 'tables' in schema_info:
            # 从表结构中提取可能的维度列
            dimension_columns = []
            for table in schema_info.get('tables', []):
                for col in table.get('columns', []):
                    col_name = col.get('name', '') if isinstance(col, dict) else str(col)
                    if any(kw in col_name.lower() for kw in ['city', 'region', 'category', 'type', 'name']):
                        dimension_columns.append(col_name)
            
            if dimension_columns:
                suggestions = [f'按{col}' for col in dimension_columns[:4]]
        
        return Ambiguity(
            ambiguity_type=AmbiguityType.DIMENSION_UNCLEAR,
            description='分组维度不明确',
            suggestions=suggestions,
            priority=2,
        )
    
    def _check_scope_unclear(self, question: str) -> Optional[Ambiguity]:
        """检测范围不明确"""
        # 检查是否使用了泛化词
        vague_patterns = [
            (r'数据', '数据范围不明确'),
            (r'情况', '查询范围不明确'),
            (r'信息', '信息范围不明确'),
            (r'详情', '详情内容不明确'),
        ]
        
        for pattern, desc in vague_patterns:
            if re.search(pattern, question) and len(question) < 15:
                return Ambiguity(
                    ambiguity_type=AmbiguityType.SCOPE_UNCLEAR,
                    description=desc,
                    suggestions=['具体字段列表', '汇总统计', '明细数据', '趋势分析'],
                    priority=3,
                )
        
        return None
    
    def _llm_check_ambiguity(self,
                              question: str,
                              schema_info: Optional[Dict[str, Any]]) -> List[Ambiguity]:
        """使用LLM检测歧义"""
        try:
            schema_str = ""
            if schema_info:
                tables = schema_info.get('tables', [])
                schema_str = f"\n数据源包含表：{', '.join(t.get('name', '') for t in tables[:5])}"
            
            prompt = f"""分析以下数据查询问题，识别其中的歧义或缺失信息。

问题：{question}
{schema_str}

请检查：
1. 指标是否明确（如"销售"可能指销售额或销量）
2. 时间范围是否明确
3. 分组维度是否明确
4. 筛选条件是否完整

如果问题清晰完整，返回：{{"has_ambiguity": false}}
如果有歧义，返回：{{"has_ambiguity": true, "type": "类型", "description": "描述", "suggestions": ["建议1", "建议2"]}}

只返回JSON格式，不要其他内容。"""

            response = self._llm.invoke([HumanMessage(content=prompt)])
            
            import json
            content = response.content.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                
                if result.get('has_ambiguity'):
                    return [Ambiguity(
                        ambiguity_type=AmbiguityType.SCOPE_UNCLEAR,
                        description=result.get('description', 'LLM检测到歧义'),
                        suggestions=result.get('suggestions', []),
                        priority=4,
                    )]
                    
        except Exception as e:
            logger.warning(f"LLM ambiguity check failed: {e}")
        
        return []
    
    def _generate_clarification_question(self,
                                          ambiguity: Ambiguity,
                                          original_question: str) -> ClarificationQuestion:
        """生成追问问题"""
        # 根据歧义类型生成追问
        if ambiguity.ambiguity_type == AmbiguityType.METRIC_AMBIGUOUS:
            ambiguous_term = self._extract_ambiguous_term(original_question)
            question = f'您提到的"{ambiguous_term}"具体是指什么？'
        elif ambiguity.ambiguity_type == AmbiguityType.TIME_MISSING:
            question = "请问您需要查询哪个时间段的数据？"
        elif ambiguity.ambiguity_type == AmbiguityType.DIMENSION_UNCLEAR:
            question = "请问您希望按什么维度进行分组统计？"
        elif ambiguity.ambiguity_type == AmbiguityType.SCOPE_UNCLEAR:
            question = "请问您具体想了解哪方面的信息？"
        else:
            question = f"请您明确一下：{ambiguity.description}"
        
        return ClarificationQuestion(
            question=question,
            options=ambiguity.suggestions,
            ambiguity=ambiguity,
            allow_custom_input=True,
        )
    
    def _extract_ambiguous_term(self, question: str) -> str:
        """提取歧义词"""
        for pattern in self.METRIC_AMBIGUOUS_PATTERNS.keys():
            match = re.search(pattern, question)
            if match:
                return match.group()
        return "这个指标"
    
    def integrate_answer(self,
                         original_question: str,
                         clarification: ClarificationQuestion,
                         user_answer: str) -> str:
        """
        整合用户回答到原问题中
        
        Args:
            original_question: 原始问题
            clarification: 追问信息
            user_answer: 用户回答
            
        Returns:
            str: 整合后的问题
        """
        ambiguity_type = clarification.ambiguity.ambiguity_type
        
        if ambiguity_type == AmbiguityType.METRIC_AMBIGUOUS:
            # 替换模糊指标
            for pattern in self.METRIC_AMBIGUOUS_PATTERNS.keys():
                if re.search(pattern, original_question):
                    return re.sub(pattern, user_answer, original_question)
        
        elif ambiguity_type == AmbiguityType.TIME_MISSING:
            # 添加时间范围
            return f"{user_answer}{original_question}"
        
        elif ambiguity_type == AmbiguityType.DIMENSION_UNCLEAR:
            # 添加分组维度
            return f"{original_question}，{user_answer}"
        
        elif ambiguity_type == AmbiguityType.SCOPE_UNCLEAR:
            # 补充范围
            return f"{original_question}的{user_answer}"
        
        # 默认：直接拼接
        return f"{original_question}（{user_answer}）"
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "use_llm": self.use_llm,
            "max_clarifications": self.max_clarifications,
            "metric_patterns_count": len(self.METRIC_AMBIGUOUS_PATTERNS),
        }


# 全局实例
clarification_agent = ClarificationAgent(use_llm=False)

