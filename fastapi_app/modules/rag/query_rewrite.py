"""
Query 改写 + Thinking 三阶段管道

参考 JoyAgent 的复杂查询处理：通过「理解 -> 改写 -> 检索」提升复杂查询准确率。

三阶段：
1. Query Understanding / Thinking：理解意图、实体、歧义
2. Query Rewrite：扩展同义词、关键词、结构化改写，便于检索
3. Retrieval：使用改写后的 query 做 Schema/Value 检索

本模块提供：
- query_rewrite_service.rewrite_with_thinking(question, datasource_id?, llm?) 
  -> {thinking, rewritten_query, entities}
- 可选 LLM；无 LLM 时使用规则扩展（分词 + 同义词表）
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False


@dataclass
class RewriteResult:
    """改写结果"""
    thinking: Optional[str] = None
    rewritten_query: str = ""
    entities: List[str] = field(default_factory=list)
    intent: Optional[str] = None
    used_llm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thinking": self.thinking,
            "rewritten_query": self.rewritten_query,
            "entities": self.entities,
            "intent": self.intent,
            "used_llm": self.used_llm,
        }


# 简单同义词/扩展词表（可后续从术语表或配置加载）
QUERY_EXPAND_MAP = {
    "金额": ["金额", "价钱", "价格", "收入", "销售额", "amount", "price", "revenue", "sales"],
    "订单": ["订单", "order", "订购"],
    "用户": ["用户", "客户", "customer", "user"],
    "时间": ["时间", "日期", "date", "time", "年", "月", "日"],
    "数量": ["数量", "个数", "count", "quantity", "num"],
    "地区": ["地区", "区域", "城市", "省", "region", "city", "area"],
    "北京": ["北京", "北京市"],
    "上海": ["上海", "上海市"],
    "广东": ["广东", "广东省"],
    "分析": ["分析", "统计", "汇总", "趋势", "对比", "analyze", "summary", "trend"],
}


class QueryRewriteService:
    """
    Query 改写服务（三阶段管道入口）

    用法：
    ```python
    result = service.rewrite_with_thinking("查一下北京的订单金额", datasource_id=1)
    # result.thinking, result.rewritten_query, result.entities
    # 检索时使用 result.rewritten_query 或原 question
    ```
    """

    def __init__(self, use_llm: bool = True, llm=None):
        self.use_llm = use_llm
        self._llm = llm

    def set_llm(self, llm) -> None:
        self._llm = llm

    def rewrite_with_thinking(self,
                              question: str,
                              datasource_id: Optional[int] = None,
                              llm=None) -> RewriteResult:
        """
        三阶段：Thinking（可选 LLM）+ Query Rewrite -> 返回改写结果。

        若启用 LLM 且可用，则调用 LLM 得到 thinking + rewritten_query + entities；
        否则使用规则扩展得到 rewritten_query。
        """
        question = (question or "").strip()
        if not question:
            return RewriteResult(rewritten_query="", entities=[])

        model = llm or self._llm
        if self.use_llm and model:
            return self._rewrite_with_llm(question, datasource_id, model)
        return self._rewrite_rule_based(question)

    def _rewrite_with_llm(self, question: str, datasource_id: Optional[int], llm) -> RewriteResult:
        """使用 LLM 做 query understanding + rewrite"""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            system = (
                "你是一个查询理解与改写助手。根据用户自然语言问题，完成：\n"
                "1. 简要思考：意图、关键实体（表/列/取值）、是否有歧义。\n"
                "2. 输出一段简短的「思考」说明。\n"
                "3. 输出「改写后的查询」：保留原意，补充同义词或关键词，便于在表结构、列名、列值中检索。"
                "只输出以下 JSON，不要其他内容：\n"
                '{"thinking": "思考内容", "rewritten_query": "改写后的查询文本", "entities": ["实体1", "实体2"]}'
            )
            msg = HumanMessage(content=f"用户问题：{question}")
            if hasattr(llm, "invoke"):
                resp = llm.invoke([SystemMessage(content=system), msg])
                text = resp.content if hasattr(resp, "content") else str(resp)
            else:
                text = str(llm([system, msg]))
            return self._parse_llm_rewrite_response(text, question)
        except Exception as e:
            logger.warning(f"Query rewrite LLM failed: {e}, fallback to rule-based")
            return self._rewrite_rule_based(question)

    def _parse_llm_rewrite_response(self, text: str, fallback_query: str) -> RewriteResult:
        import json
        text = text.strip()
        # 尝试提取 JSON 块
        for start in ("{", "```json", "```"):
            if start in text:
                idx = text.find(start)
                if start == "```json":
                    idx = text.find("{", idx)
                if idx >= 0:
                    try:
                        end = text.rfind("}") + 1
                        if end > idx:
                            obj = json.loads(text[idx:end])
                            thinking = obj.get("thinking") or ""
                            rewritten = (obj.get("rewritten_query") or "").strip() or fallback_query
                            entities = obj.get("entities") or []
                            if isinstance(entities, list):
                                entities = [str(e) for e in entities]
                            return RewriteResult(
                                thinking=thinking,
                                rewritten_query=rewritten,
                                entities=entities,
                                intent=obj.get("intent"),
                                used_llm=True,
                            )
                    except Exception:
                        pass
        return RewriteResult(
            thinking=None,
            rewritten_query=fallback_query,
            entities=[],
            used_llm=False,
        )

    def _rewrite_rule_based(self, question: str) -> RewriteResult:
        """规则式改写：分词 + 同义词扩展"""
        expanded = []
        if JIEBA_AVAILABLE:
            tokens = list(jieba.cut(question))
        else:
            tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', question)
        seen = set()
        for t in tokens:
            t = t.strip()
            if not t or len(t) < 2:
                continue
            if t not in seen:
                seen.add(t)
                expanded.append(t)
            for key, synonyms in QUERY_EXPAND_MAP.items():
                if key in t or t in synonyms:
                    for s in synonyms:
                        if s not in seen:
                            seen.add(s)
                            expanded.append(s)
        rewritten_query = " ".join(expanded) if expanded else question
        return RewriteResult(
            thinking=None,
            rewritten_query=rewritten_query,
            entities=expanded[:15],
            used_llm=False,
        )


# 全局 Query 改写服务
query_rewrite_service = QueryRewriteService(use_llm=True)
