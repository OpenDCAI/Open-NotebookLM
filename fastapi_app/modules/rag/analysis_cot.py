"""
CodeAgent 式自主数据分析 + CoT（Chain of Thought）

参考 CodeActAgent / CodeAgent：通过显式推理步骤（CoT）规划分析任务，
再调用分析工具（analyze_columns, detect_trends, get_table_sample, execute_sql, generate_summary），
实现「下一代智能取数」中的自主分析能力。

流程：
1. 输入：用户问题 + 可用表结构（+ 可选样本）
2. CoT：LLM 输出「分析思路」与「分析计划」（步骤、表、列、指标）
3. 执行：根据计划调用工具（或生成 SQL），汇总结果
4. 输出：结构化分析结论 + 自然语言总结
"""

import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AnalysisStep:
    """单步分析计划"""
    step_id: int
    action: str  # e.g. "analyze_columns", "detect_trends", "get_table_sample", "execute_sql"
    reason: str
    table_name: Optional[str] = None
    columns: Optional[List[str]] = None
    time_column: Optional[str] = None
    value_column: Optional[str] = None
    sql: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisCoTResult:
    """CoT 分析结果"""
    thinking: str
    steps: List[AnalysisStep]
    summary_intent: str
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thinking": self.thinking,
            "steps": [
                {
                    "step_id": s.step_id,
                    "action": s.action,
                    "reason": s.reason,
                    "table_name": s.table_name,
                    "columns": s.columns,
                    "time_column": s.time_column,
                    "value_column": s.value_column,
                    "sql": s.sql,
                    "extra": s.extra,
                }
                for s in self.steps
            ],
            "summary_intent": self.summary_intent,
        }


# CoT 分析系统提示（引导 LLM 做步骤化推理）
ANALYSIS_COT_SYSTEM = """你是一个数据分析专家。用户会提出一个分析类问题，并给出可用的表结构信息。

请按「链式思考」完成：
1. 思考：理解用户想要什么分析（趋势、分布、对比、汇总等），需要哪些表、列、指标。
2. 分析计划：列出具体步骤，每步对应一个可执行动作。
3. 可用动作类型：
   - analyze_columns: 分析指定列的统计（表名、列列表）
   - detect_trends: 时间序列趋势（表名、时间列、数值列）
   - get_table_sample: 查看表样本（表名）
   - execute_sql: 自定义 SQL 查询（仅当必要且上述动作无法满足时）

请严格按以下 JSON 格式输出（不要其他内容）：
{
  "thinking": "你的推理过程：用户意图、需要哪些数据、先做什么后做什么",
  "summary_intent": "用一句话概括本次分析意图",
  "steps": [
    {
      "step_id": 1,
      "action": "analyze_columns|detect_trends|get_table_sample|execute_sql",
      "reason": "为什么做这一步",
      "table_name": "表名",
      "columns": ["列1", "列2"],
      "time_column": "时间列名（仅 detect_trends）",
      "value_column": "数值列名（仅 detect_trends）",
      "sql": "SELECT ...（仅 execute_sql）"
    }
  ]
}
"""


class AnalysisCoTService:
    """
    自主数据分析 CoT 服务

    用法：
    ```python
    result = service.plan_analysis(question, schema_text, llm=llm)
    # result.thinking, result.steps -> 交给执行器调用 analyze_columns / detect_trends 等
    ```
    """

    def __init__(self, llm=None):
        self._llm = llm

    def set_llm(self, llm) -> None:
        self._llm = llm

    def plan_analysis(self,
                      question: str,
                      schema_text: str,
                      llm=None,
                      max_steps: int = 5) -> AnalysisCoTResult:
        """
        根据用户问题与表结构，用 CoT 生成分析计划（thinking + steps）。
        """
        question = (question or "").strip()
        schema_text = (schema_text or "").strip()
        model = llm or self._llm
        if not model:
            return AnalysisCoTResult(
                thinking="未配置 LLM，无法生成分析计划",
                steps=[],
                summary_intent=question,
            )

        from langchain_core.messages import HumanMessage, SystemMessage
        user_content = f"用户问题：{question}\n\n可用表结构：\n{schema_text[:4000]}"
        try:
            if hasattr(model, "invoke"):
                resp = model.invoke([
                    SystemMessage(content=ANALYSIS_COT_SYSTEM),
                    HumanMessage(content=user_content),
                ])
                text = resp.content if hasattr(resp, "content") else str(resp)
            else:
                text = str(model([ANALYSIS_COT_SYSTEM, user_content]))
        except Exception as e:
            logger.warning(f"Analysis CoT LLM failed: {e}")
            return AnalysisCoTResult(
                thinking=f"规划失败: {e}",
                steps=[],
                summary_intent=question,
                raw_response="",
            )

        return self._parse_cot_response(text, question)

    def _parse_cot_response(self, text: str, fallback_intent: str) -> AnalysisCoTResult:
        text = text.strip()
        thinking = ""
        summary_intent = fallback_intent
        steps = []
        raw = text

        # 提取 JSON
        try:
            start = text.find("{")
            if start >= 0:
                depth = 0
                end = -1
                for i in range(start, len(text)):
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > start:
                    obj = json.loads(text[start:end])
                    thinking = obj.get("thinking") or ""
                    summary_intent = (obj.get("summary_intent") or "").strip() or fallback_intent
                    for s in (obj.get("steps") or [])[:10]:
                        if not isinstance(s, dict):
                            continue
                        step = AnalysisStep(
                            step_id=int(s.get("step_id", len(steps) + 1)),
                            action=(s.get("action") or "").strip().lower(),
                            reason=(s.get("reason") or "").strip(),
                            table_name=s.get("table_name"),
                            columns=s.get("columns") if isinstance(s.get("columns"), list) else None,
                            time_column=s.get("time_column"),
                            value_column=s.get("value_column"),
                            sql=s.get("sql"),
                            extra={k: v for k, v in s.items() if k not in (
                                "step_id", "action", "reason", "table_name", "columns",
                                "time_column", "value_column", "sql")},
                        )
                        if step.action in ("analyze_columns", "detect_trends", "get_table_sample", "execute_sql"):
                            steps.append(step)
        except Exception as e:
            logger.warning(f"Parse analysis CoT JSON failed: {e}")

        return AnalysisCoTResult(
            thinking=thinking,
            steps=steps,
            summary_intent=summary_intent,
            raw_response=raw,
        )


# 全局分析 CoT 服务
analysis_cot_service = AnalysisCoTService()
