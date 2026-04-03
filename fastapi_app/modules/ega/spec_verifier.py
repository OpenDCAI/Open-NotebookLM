"""
Deliverable spec extraction and verification.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _extract_json_object(text: str) -> Dict[str, Any] | None:
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _infer_min_row_count(question: str) -> int | None:
    q = str(question or "")
    patterns = [
        r"\btop\s*(\d+)\b",
        r"\breturn\s+(\d+)\s+rows?\b",
        r"\blimit\s+(\d+)\b",
        r"\b(\d+)\s*rows?\b",
        r"\b前\s*(\d+)\b",
        r"\b(\d+)\s*行\b",
    ]
    values: List[int] = []
    for p in patterns:
        for m in re.finditer(p, q, flags=re.I):
            try:
                values.append(int(m.group(1)))
            except Exception:
                continue
    return max(values) if values else None


def _sanitize_required_columns(question: str, columns: List[str]) -> List[str]:
    q = str(question or "")
    where_cols = {
        c.lower()
        for c in re.findall(r"\bwhere\s+([A-Za-z_][A-Za-z0-9_]*)\b", q, flags=re.I)
    }
    cleaned: List[str] = []
    for c in columns:
        s = str(c or "").strip()
        if not s:
            continue
        # Avoid forcing filter-only fields as output columns.
        if s.lower() in where_cols:
            continue
        cleaned.append(s)
    return list(dict.fromkeys(cleaned))


def extract_deliverable_spec(
    question: str,
    llm: Any = None,
    output_mode: str | None = None,
    data_format: str | None = None,
) -> Dict[str, Any]:
    inferred_min_rows = _infer_min_row_count(question)

    if llm is not None:
        prompt = (
            "Extract deliverable spec as strict JSON object with keys:\n"
            "required_columns(list[str]), require_non_empty(bool), min_row_count(int|null), "
            "numeric_ranges(dict), output_format(str).\n"
            "If unknown, use empty list/object and conservative defaults.\n"
            f"question: {question}\n"
        )
        try:
            resp = llm.invoke(prompt)
            content = getattr(resp, "content", "")
            obj = _extract_json_object(content if isinstance(content, str) else str(content))
            if isinstance(obj, dict):
                min_rows = _coerce_int(obj.get("min_row_count"))
                if inferred_min_rows is not None and (min_rows is None or min_rows < inferred_min_rows):
                    min_rows = inferred_min_rows
                required_columns = _sanitize_required_columns(question, list(obj.get("required_columns") or []))
                return {
                    "required_columns": required_columns,
                    "require_non_empty": bool(obj.get("require_non_empty", True)),
                    "min_row_count": min_rows,
                    "numeric_ranges": dict(obj.get("numeric_ranges") or {}),
                    "output_format": str(obj.get("output_format") or data_format or "json"),
                    "source": "llm",
                }
        except Exception:
            pass

    required_columns: List[str] = []
    q = str(question or "")
    by_match = re.search(r"\bby\s+([A-Za-z_][A-Za-z0-9_]*)", q, re.I)
    if by_match:
        required_columns.append(by_match.group(1))
    if any(k in q.lower() for k in ("total", "sum", "sales", "amount", "revenue")):
        required_columns.append("total_amount")

    return {
        "required_columns": _sanitize_required_columns(q, required_columns),
        "require_non_empty": True,
        "min_row_count": inferred_min_rows,
        "numeric_ranges": {},
        "output_format": str(data_format or "json"),
        "source": "heuristic",
    }


def verify_result(result: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    columns = [str(c) for c in (result.get("columns") or [])]
    row_count = int(result.get("row_count") or 0)
    data = result.get("data") or []
    issues: List[Dict[str, Any]] = []

    required = [str(x) for x in (spec.get("required_columns") or []) if str(x).strip()]
    if required:
        lower_cols = {c.lower() for c in columns}
        missing = [c for c in required if c.lower() not in lower_cols]
        if missing:
            issues.append({"type": "missing_required_columns", "missing": missing})

    if bool(spec.get("require_non_empty", True)) and (row_count <= 0 or not data):
        issues.append({"type": "empty_result", "detail": "row_count is zero"})

    min_rows = _coerce_int(spec.get("min_row_count"))
    if min_rows is not None and row_count < min_rows:
        issues.append({"type": "too_few_rows", "expected": min_rows, "actual": row_count})

    numeric_ranges = spec.get("numeric_ranges") or {}
    if isinstance(numeric_ranges, dict):
        for c, bounds in numeric_ranges.items():
            if not isinstance(bounds, dict):
                continue
            lo = bounds.get("min")
            hi = bounds.get("max")
            if c not in columns:
                continue
            for row in data[:100]:
                if not isinstance(row, dict):
                    continue
                v = row.get(c)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if lo is not None and fv < float(lo):
                    issues.append({"type": "numeric_range", "column": c, "value": fv, "bound": lo, "op": "min"})
                    break
                if hi is not None and fv > float(hi):
                    issues.append({"type": "numeric_range", "column": c, "value": fv, "bound": hi, "op": "max"})
                    break

    ok = len(issues) == 0
    msg = "Spec verification passed" if ok else f"Spec verification failed: {issues[0]}"
    return {
        "status": "completed",
        "ok": ok,
        "message": msg,
        "issues": issues,
        "required_columns": required,
        "row_count": row_count,
    }

