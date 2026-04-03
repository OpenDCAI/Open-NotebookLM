"""System prompt builder for SQL generation.

Produces an XML-tagged system prompt with path-based trimming.
Paths: FAST / STANDARD / FULL.

Sections:
- <ROLE>
- <DATASOURCE>
- <SAFETY>
- <PREVIOUS_CONTEXT> (optional)
- <WORKFLOW>
- <RULES>
- <TERMINOLOGY> (STANDARD/FULL)
- <EXAMPLES> (STANDARD/FULL)
- <PATTERN_HINTS> (STANDARD/FULL, optional)
- <JOIN_HINTS> (STANDARD/FULL, optional)
- <VALUE_LINKING> (FULL)
- <ANALYSIS> (FULL)
- <CROSS_SOURCE> (when active)
- <EGA_SCHEMA> (when EGA active)
"""

from __future__ import annotations

from typing import Dict, Any, Optional

PATH_FAST = "fast"
PATH_STANDARD = "standard"
PATH_FULL = "full"


def build_system_prompt(
    datasource_id: int,
    rag_context: Optional[Dict[str, Any]] = None,
    sql_rules: Optional[Dict[str, str]] = None,
    cross_source_mode: bool = False,
    routing_path: str = PATH_STANDARD,
    conversation_context: Optional[Dict[str, Any]] = None,
    available_datasources: Optional[list] = None,
    ega_context: Optional[Dict[str, Any]] = None,
    question: Optional[str] = None,
) -> str:
    rag_context = rag_context or {}
    sql_rules = sql_rules or {}

    sections: list[str] = []
    sections.append(_role())
    sections.append(_datasource(datasource_id))
    sections.append(_safety())

    if conversation_context:
        prev = _previous_context(conversation_context)
        if prev:
            sections.append(prev)

    sections.append(
        _workflow(
            datasource_id=datasource_id,
            routing_path=routing_path,
            cross_source_mode=cross_source_mode,
            available_datasources=available_datasources,
        )
    )
    sections.append(_rules(sql_rules, routing_path))

    if routing_path in (PATH_STANDARD, PATH_FULL):
        term = _terminology(rag_context)
        if term:
            sections.append(term)

        ex = _examples(rag_context)
        if ex:
            sections.append(ex)

        ph = _pattern_hints(rag_context)
        if ph:
            sections.append(ph)

        jh = _join_hints(rag_context)
        if jh:
            sections.append(jh)

    if routing_path == PATH_FULL:
        vl = _value_linking(rag_context)
        if vl:
            sections.append(vl)

        an = _analysis(rag_context)
        if an:
            sections.append(an)

    if cross_source_mode:
        sections.append(_cross_source(available_datasources))

    sections.append(
        _action_directive(
            datasource_id=datasource_id,
            routing_path=routing_path,
            cross_source_mode=cross_source_mode,
            available_datasources=available_datasources,
        )
    )
    return "\n".join(s for s in sections if s)


def _role() -> str:
    return """<ROLE>
你是数据查询专家。你需要根据用户问题生成 SQL，并通过工具执行查询，最后用自然语言总结结果。
</ROLE>"""


def _datasource(datasource_id: int) -> str:
    return f"""<DATASOURCE>
数据源ID: {datasource_id}
所有需要 datasource_id 的工具调用必须使用 datasource_id={datasource_id}
</DATASOURCE>"""


def _safety() -> str:
    return """<SAFETY>
强约束：
- 禁止生成 INSERT/UPDATE/DELETE/DROP/TRUNCATE 等 DML/DDL
- 列别名必须是英文
- 不要编造不存在的表名/列名
- 只选择用户要求的列，不要额外添加列
</SAFETY>"""


def _workflow(
    datasource_id: int,
    routing_path: str,
    cross_source_mode: bool = False,
    available_datasources: Optional[list] = None,
) -> str:
    if cross_source_mode:
        ds_ids = []
        if isinstance(available_datasources, list):
            for d in available_datasources:
                if isinstance(d, dict) and "id" in d:
                    ds_ids.append(str(d["id"]))
        ids_hint = "[" + ", ".join(ds_ids) + "]" if ds_ids else "[...]"
        return f"""<WORKFLOW>
步骤1: 明确输出列清单（严格按用户要求，不多不少）
步骤2: 获取跨源统一 Schema：get_cross_source_schema(datasource_ids={ids_hint})
步骤3: 使用统一表名 ds{{datasource_id}}_{{table_name}} 写 SQL
步骤4: 执行 SQL：execute_cross_source_sql(datasource_ids={ids_hint}, sql="<SQL>")
步骤5: 校验列名/别名/行数与问题一致
步骤6: 用自然语言总结 + 给出表格数据
</WORKFLOW>"""

    if routing_path == PATH_FAST:
        return f"""<WORKFLOW>
1) get_datasource_schema(datasource_id={datasource_id}, query="<关键词>")
2) execute_sql(datasource_id={datasource_id}, sql="<SQL>")
3) 返回结果
</WORKFLOW>"""

    return f"""<WORKFLOW>
步骤1: 明确输出列清单（严格按用户要求，不多不少）
步骤2: 获取 Schema：get_datasource_schema(datasource_id={datasource_id}, query="<关键词>")
步骤3: 写 SQL（仅选择步骤1的列，必要时 WHERE/GROUP BY/ORDER BY/LIMIT）
步骤4: 执行 SQL：execute_sql(datasource_id={datasource_id}, sql="<SQL>")
步骤5: 校验列名/别名/行数与问题一致
步骤6: 用自然语言总结 + 给出表格数据
</WORKFLOW>"""


def _rules(sql_rules: Dict[str, str], routing_path: str) -> str:
    parts = ["<RULES>"]

    for key in ("critical_rules", "column_name_rules", "select_only_required_columns"):
        v = (sql_rules.get(key) or "").strip()
        if v:
            parts.append(v)

    if routing_path in (PATH_STANDARD, PATH_FULL):
        for key in ("where_clause_rules", "process_validation"):
            v = (sql_rules.get(key) or "").strip()
            if v:
                parts.append(v)

    parts.append("</RULES>")
    return "\n\n".join(parts)


def _terminology(rag_context: Dict[str, Any]) -> Optional[str]:
    terms = rag_context.get("related_terms")
    if not terms:
        return None
    items = "\n".join(f"- {t}" for t in terms)
    return f"""<TERMINOLOGY>
业务术语（生成 SQL 时必须参考）：
{items}
</TERMINOLOGY>"""


def _examples(rag_context: Dict[str, Any]) -> Optional[str]:
    examples = rag_context.get("similar_examples")
    if not examples:
        return None

    parts = ["<EXAMPLES>", "参考以下示例的 SQL 结构："]
    for i, ex in enumerate(examples, 1):
        q = ex.get("question", "")
        s = ex.get("sql", "")
        parts.append(f"示例{i}:\n  问题: {q}\n  SQL: {s}")
    parts.append("</EXAMPLES>")
    return "\n".join(parts)


def _pattern_hints(rag_context: Dict[str, Any]) -> Optional[str]:
    hints = rag_context.get("pattern_hints")
    if not hints:
        return None
    text = "\n".join(hints)
    return f"""<PATTERN_HINTS>
可能适用的分析 SQL 模式：
{text}
</PATTERN_HINTS>"""


def _join_hints(rag_context: Dict[str, Any]) -> Optional[str]:
    hints = rag_context.get("join_hints")
    if not hints:
        return None
    text = "\n".join(f"- {h}" for h in hints)
    return f"""<JOIN_HINTS>
可参考的 JOIN 关系：
{text}
</JOIN_HINTS>"""


def _value_linking(rag_context: Dict[str, Any]) -> Optional[str]:
    vl = rag_context.get("value_linking")
    if not vl:
        return None

    lines = []
    for v in vl[:15]:
        t = v.get("table_name")
        c = v.get("column_name")
        val = v.get("value_str", v.get("value"))
        if t and c:
            lines.append(f"- {t}.{c} ≈ {val}")
    if not lines:
        return None

    return "<VALUE_LINKING>\n" + "可能相关的取值提示：\n" + "\n".join(lines) + "\n</VALUE_LINKING>"


def _analysis(rag_context: Dict[str, Any]) -> Optional[str]:
    parts = []

    qt = rag_context.get("query_thinking")
    if isinstance(qt, str) and qt.strip():
        parts.append(f"理解: {qt.strip()[:800]}")

    ap = rag_context.get("analysis_plan")
    if ap and isinstance(ap, dict):
        summary = ap.get("summary_intent", "")
        thinking = ap.get("thinking", "")
        steps = ap.get("steps", [])
        if summary or thinking or steps:
            step_lines = []
            for s in (steps or [])[:5]:
                step_lines.append(f"- {s.get('action','')}: {s.get('reason','')}")
            parts.append(
                "分析计划:\n"
                + (f"意图: {summary}\n" if summary else "")
                + (f"思路: {str(thinking)[:300]}\n" if thinking else "")
                + ("步骤:\n" + "\n".join(step_lines) if step_lines else "")
            )

    if not parts:
        return None
    return "<ANALYSIS>\n" + "\n\n".join(parts) + "\n</ANALYSIS>"


def _ega_schema(ega_context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if not isinstance(ega_context, dict):
        return None
    clean_schema = str(ega_context.get("clean_view_schema") or "").strip()
    clean_views = ega_context.get("clean_views") or {}
    if not clean_schema and not clean_views:
        return None

    lines = ["<EGA_SCHEMA>"]
    lines.append("以下为运行时已准备好的 clean view schema；优先在这些视图上写业务 SQL。")

    if clean_schema:
        lines.append(clean_schema[:8000])
    else:
        for _, info in list(clean_views.items())[:12]:
            view = str((info or {}).get("view") or "")
            if not view:
                continue
            cols = [str(c) for c in ((info or {}).get("columns") or []) if str(c).strip()]
            norm_map = (info or {}).get("normalized_columns") or {}
            norm_cols = [str(v) for v in norm_map.values() if str(v).strip()]
            merged = cols + [c for c in norm_cols if c not in cols]
            lines.append(f"view {view}")
            for c in merged[:120]:
                lines.append(f"  - {c}")

    lines.append("</EGA_SCHEMA>")
    return "\n".join(lines)


def _cross_source(available_datasources: Optional[list] = None) -> str:
    ds_hint = ""
    if isinstance(available_datasources, list) and available_datasources:
        ids = []
        for d in available_datasources[:20]:
            if isinstance(d, dict) and "id" in d:
                ids.append(str(d["id"]) + ("(current)" if d.get("current") else ""))
        if ids:
            ds_hint = "可用数据源ID: " + ", ".join(ids) + "\n"

    return (
        "<CROSS_SOURCE>\n"
        "跨数据源查询已开启。" + ds_hint +
        "1) 先调用 get_cross_source_schema(datasource_ids=[...]) 获取统一 Schema（DuckDB 方言）\n"
        "2) 统一表名: ds{datasource_id}_{original_table_name}（例如 ds1_orders, ds2_customers）\n"
        "2.1) 如果 schema 返回 alignment_views，只能使用其中明确列出的 view 名；"
        "不要自行假设任意 {table}__norm 存在\n"
        "3) 如果 schema 返回 join_suggestions，优先使用其中的连接键\n"
        "4) 调用 execute_cross_source_sql(datasource_ids=[...], sql=\"...\") 执行查询\n"
        "注意: 跨源查询使用 DuckDB SQL。\n"
        "</CROSS_SOURCE>"
    )


def _previous_context(conversation_context: Dict[str, Any]) -> Optional[str]:
    prev_q = conversation_context.get("previous_question", "")
    prev_sql = conversation_context.get("previous_sql", "")
    if not prev_q or not prev_sql:
        return None

    prev_summary = conversation_context.get("previous_summary", "")
    summary_line = f"\n上一轮摘要: {prev_summary[:200]}" if prev_summary else ""

    return f"""<PREVIOUS_CONTEXT>
用户正在追问。优先在上一轮 SQL 基础上修改，而不是从零重写。
上一轮问题: {prev_q}
上一轮SQL:\n{prev_sql}{summary_line}
</PREVIOUS_CONTEXT>"""


def _action_directive(
    datasource_id: int,
    routing_path: str,
    cross_source_mode: bool = False,
    available_datasources: Optional[list] = None,
) -> str:
    if cross_source_mode:
        ds_ids = []
        if isinstance(available_datasources, list):
            for d in available_datasources:
                if isinstance(d, dict) and "id" in d:
                    ds_ids.append(str(d["id"]))
        ids_hint = "[" + ", ".join(ds_ids) + "]" if ds_ids else "[...]"
        return (
            "立即执行：先调用 "
            f"get_cross_source_schema(datasource_ids={ids_hint})，"
            "再使用统一表名写 SQL，并用 execute_cross_source_sql 执行。"
        )
    if routing_path == PATH_FAST:
        return f"立即执行：先 get_datasource_schema(datasource_id={datasource_id})，再生成并执行 SQL。"
    return f"立即执行：先列出输出列清单，再调用 get_datasource_schema(datasource_id={datasource_id})，再生成并执行 SQL。"
