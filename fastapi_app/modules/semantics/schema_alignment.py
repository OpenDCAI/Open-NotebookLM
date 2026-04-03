"""Lightweight schema alignment (Schema Alignment layer).

Goal: provide deterministic, low-cost hints that map "messy" columns to common
semantic fields (canonical roles), so the SQL generator is less brittle to
schema drift.

This is intentionally heuristic-based (no LLM) and meant to be:
- Fast
- Safe
- Good enough to bootstrap correctness for common analytics tasks
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _looks_like_date(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return bool(_DATE_RE.match(s) or _DATETIME_RE.match(s))


def _looks_like_number(v: Any) -> bool:
    if v is None:
        return False
    try:
        float(str(v).replace(",", "").strip())
        return True
    except Exception:
        return False


def _score_name(col: str, patterns: Tuple[str, ...]) -> float:
    c = _norm(col)
    score = 0.0
    for p in patterns:
        if p in c:
            score += 2.0
    # token bonus
    for p in patterns:
        if c == p:
            score += 2.0
    return score


def _score_samples(samples: List[Any], kind: str) -> float:
    if not samples:
        return 0.0
    hits = 0
    total = 0
    for v in samples[:10]:
        total += 1
        if kind == "date" and _looks_like_date(v):
            hits += 1
        if kind == "number" and _looks_like_number(v):
            hits += 1
        if kind == "id":
            s = str(v).strip()
            if s and any(ch.isdigit() for ch in s) and len(s) <= 32:
                hits += 1
    if total == 0:
        return 0.0
    return (hits / total) * 2.0


@dataclass
class MappingCandidate:
    column: str
    score: float
    reasons: List[str]


def infer_schema_alignment(tables: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """
    Infer per-table semantic mappings.

    Args:
        tables: list of TableSchema.to_dict() like payloads.
        query: the user question/keywords (used as a weak prior).
    """
    q = _norm(query)
    q_has_customer = any(k in q for k in ("customer", "客户", "用户", "会员"))
    q_has_product = any(k in q for k in ("product", "商品", "产品", "sku"))
    q_has_order = any(k in q for k in ("order", "订单", "下单"))

    roles = {
        "order_id": ("order_id", "订单id", "订单号", "order_no", "order number", "订单编号"),
        "customer_id": ("customer_id", "cust_id", "client_id", "buyer_id", "客户id", "用户id", "会员id"),
        "product_id": ("product_id", "sku_id", "item_id", "商品id", "产品id"),
        "amount": ("amount", "total_amount", "sales", "revenue", "gmv", "成交额", "销售额", "金额", "收入"),
        "quantity": ("quantity", "qty", "units", "count", "数量", "销量"),
        "date": ("date", "dt", "time", "created_at", "order_date", "日期", "时间", "下单时间", "订单日期"),
        "city": ("city", "城市"),
        "region": ("region", "area", "地区", "区域", "省", "province"),
        "name": ("name", "customer_name", "客户名", "姓名", "产品名", "商品名", "product_name"),
    }

    result: Dict[str, Any] = {"query": query, "tables": {}}

    for t in tables or []:
        tname = t.get("name") or ""
        cols = t.get("columns") or []
        if not tname or not isinstance(cols, list):
            continue

        col_infos: List[Tuple[str, str, List[Any]]] = []
        for c in cols:
            if not isinstance(c, dict):
                continue
            cn = c.get("name") or ""
            ctype = _norm(str(c.get("data_type") or c.get("type") or ""))
            samples = c.get("sample_values") or []
            if cn:
                col_infos.append((cn, ctype, samples if isinstance(samples, list) else []))

        table_map: Dict[str, Any] = {"mappings": [], "ambiguous": []}

        for role, patterns in roles.items():
            candidates: List[MappingCandidate] = []
            for cn, ctype, samples in col_infos:
                reasons: List[str] = []
                score = 0.0

                s_name = _score_name(cn, tuple(_norm(p) for p in patterns))
                if s_name:
                    score += s_name
                    reasons.append("name_match")

                if role in ("date",) and (ctype in ("date", "datetime", "timestamp", "time")):
                    score += 1.5
                    reasons.append("type_date")
                if role in ("amount", "quantity") and (ctype in ("integer", "bigint", "float", "double", "decimal")):
                    score += 1.0
                    reasons.append("type_numeric")
                if role.endswith("_id") and ("id" in _norm(cn) or ctype in ("integer", "bigint", "varchar", "text")):
                    score += 0.5

                # sample-based boosts
                if role == "date":
                    score += _score_samples(samples, "date")
                elif role in ("amount", "quantity"):
                    score += _score_samples(samples, "number")
                elif role.endswith("_id"):
                    score += _score_samples(samples, "id")

                # weak query priors
                if role.startswith("customer") and q_has_customer:
                    score += 0.5
                if role.startswith("product") and q_has_product:
                    score += 0.5
                if role.startswith("order") and q_has_order:
                    score += 0.5

                if score > 0.0:
                    candidates.append(MappingCandidate(column=cn, score=score, reasons=reasons))

            if not candidates:
                continue

            candidates.sort(key=lambda x: x.score, reverse=True)
            top1 = candidates[0]
            top2 = candidates[1] if len(candidates) > 1 else None
            margin = (top1.score - top2.score) if top2 else top1.score

            mapping = {
                "canonical": role,
                "column": top1.column,
                "confidence": round(min(0.99, max(0.0, top1.score / 8.0)), 2),
                "margin": round(margin, 2),
                "top_candidates": [
                    {"column": c.column, "score": round(c.score, 2)} for c in candidates[:3]
                ],
            }
            table_map["mappings"].append(mapping)
            if top2 and margin < 1.0:
                table_map["ambiguous"].append(mapping)

        result["tables"][tname] = table_map

    return result

