"""
Extensional profiling for EGA discovery and schema alignment.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

from .contracts import ExpectedSignature, ColumnFingerprint, CandidateMatch

logger = logging.getLogger(__name__)


def _safe_float(x: float) -> float:
    if x is None or math.isnan(x) or math.isinf(x):
        return 0.0
    return float(x)


def _is_date_like(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return False
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            datetime.strptime(s, fmt)
            return True
        except Exception:
            continue
    return False


def _is_number(v: str) -> bool:
    try:
        float((v or "").replace(",", ""))
        return True
    except Exception:
        return False


def derive_expected_signatures(question: str, llm: Any) -> List[Dict[str, Any]]:
    if llm is not None:
        prompt = (
            "You are extracting expected data roles for heterogeneous retrieval.\n"
            "Return strict JSON array only. each object keys: "
            "role, expected_type, expected_cardinality, description.\n"
            f"question: {question}"
        )
        try:
            resp = llm.invoke(prompt)
            content = getattr(resp, "content", "")
            text = content if isinstance(content, str) else str(content)
            arr = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
            out = []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                out.append(
                    ExpectedSignature(
                        role=str(it.get("role") or "unknown"),
                        expected_type=str(it.get("expected_type") or "string"),
                        expected_cardinality=str(it.get("expected_cardinality") or "unknown"),
                        description=str(it.get("description") or ""),
                    ).to_dict()
                )
            if out:
                return out
        except Exception as e:
            logger.debug(f"derive_expected_signatures fallback: {e}")

    q = (question or "").lower()
    signatures = [
        ExpectedSignature(
            role="entity_id",
            expected_type="high_cardinality_integer_or_string",
            expected_cardinality="high",
            description="primary/foreign key for joins",
        ),
    ]
    if any(k in q for k in ("name", "名称", "姓名", "singer", "artist", "customer")):
        signatures.append(
            ExpectedSignature(
                role="entity_name",
                expected_type="medium_cardinality_string",
                expected_cardinality="medium",
                description="dimension name for grouping/output",
            )
        )
    if any(k in q for k in ("sum", "total", "sales", "amount", "revenue", "gmv", "总", "销售", "金额")):
        signatures.append(
            ExpectedSignature(
                role="measure",
                expected_type="non_negative_numeric",
                expected_cardinality="high",
                description="metric column for aggregation",
            )
        )
    if any(k in q for k in ("date", "month", "year", "时间", "日期")):
        signatures.append(
            ExpectedSignature(
                role="date",
                expected_type="date_or_datetime_like",
                expected_cardinality="high",
                description="time column for filtering/trends",
            )
        )
    return [s.to_dict() for s in signatures]


def build_column_fingerprints(engine, datasource_ids: List[int], sample_rows: int = 100) -> List[Dict[str, Any]]:
    _ = datasource_ids  # engine already scoped to selected datasources.
    rows_n = max(20, int(sample_rows or 100))
    fps: List[Dict[str, Any]] = []

    for reg in engine.get_registered_tables():
        table = reg.unified_table_name
        for col in list(reg.columns or [])[:200]:
            vals = engine.sample_column_values(table, col, limit=rows_n)
            total = len(vals)
            if total == 0:
                continue

            normalized = [("" if v is None else str(v).strip()) for v in vals]
            non_null = [v for v in normalized if v != ""]
            n = len(non_null)
            if n == 0:
                continue

            numbers = [v for v in non_null if _is_number(v)]
            lens = [len(v) for v in non_null]
            freq = Counter(non_null)
            unique = len(freq)
            top_counts = sorted(freq.values(), reverse=True)
            singleton = sum(1 for c in freq.values() if c == 1)
            digits_unique = len({re.sub(r"[^0-9]", "", v) for v in non_null})

            numeric_ratio = len(numbers) / n
            alpha_ratio = sum(1 for v in non_null if v.isalpha()) / n
            mixed_ratio = sum(1 for v in non_null if any(c.isalpha() for c in v) and any(c.isdigit() for c in v)) / n
            has_special_ratio = sum(1 for v in non_null if re.search(r"[^0-9A-Za-z]", v)) / n
            date_parsable_ratio = sum(1 for v in non_null if _is_date_like(v)) / n
            null_ratio = 1.0 - (n / total)

            cardinality_ratio = unique / n
            top1_freq = (top_counts[0] / n) if top_counts else 0.0
            top5_coverage = (sum(top_counts[:5]) / n) if top_counts else 0.0
            singleton_ratio = singleton / n

            mean_length = sum(lens) / n
            std_length = math.sqrt(sum((x - mean_length) ** 2 for x in lens) / n) if n > 1 else 0.0

            nums = [float(v.replace(",", "")) for v in numbers]
            if nums:
                mean_value = sum(nums) / len(nums)
                std_value = math.sqrt(sum((x - mean_value) ** 2 for x in nums) / len(nums)) if len(nums) > 1 else 0.0
            else:
                mean_value = 0.0
                std_value = 0.0

            metrics = {
                "numeric_ratio": _safe_float(numeric_ratio),
                "alpha_ratio": _safe_float(alpha_ratio),
                "mixed_ratio": _safe_float(mixed_ratio),
                "has_special_ratio": _safe_float(has_special_ratio),
                "date_parsable_ratio": _safe_float(date_parsable_ratio),
                "null_ratio": _safe_float(null_ratio),
                "cardinality_ratio": _safe_float(cardinality_ratio),
                "top1_freq": _safe_float(top1_freq),
                "top5_coverage": _safe_float(top5_coverage),
                "singleton_ratio": _safe_float(singleton_ratio),
                "mean_length": _safe_float(mean_length),
                "std_length": _safe_float(std_length),
                "mean_value": _safe_float(mean_value),
                "std_value": _safe_float(std_value),
                "all_digits": _safe_float(sum(1 for v in non_null if v.isdigit()) / n),
                "has_prefix_pattern": _safe_float(sum(1 for v in non_null if re.match(r"^[A-Za-z]{1,8}[-_]\d+", v)) / n),
                "has_date_sep": _safe_float(sum(1 for v in non_null if ("/" in v or "-" in v)) / n),
                "has_currency": _safe_float(sum(1 for v in non_null if re.search(r"[$€£]", v)) / n),
                "uniform_length": 1.0 if len(set(lens)) == 1 else 0.0,
                "extractable_digits": _safe_float((digits_unique / unique) if unique > 0 else 0.0),
            }
            fps.append(ColumnFingerprint(table=table, column=col, metrics=metrics, sample_size=total).to_dict())

    return fps


def score_role_compatibility(signature: Dict[str, Any], fingerprint: Dict[str, Any]) -> float:
    role = str(signature.get("role") or "").lower()
    m = (fingerprint.get("metrics") or {})

    score = 0.0
    if role == "entity_id":
        score += 0.45 * float(m.get("cardinality_ratio", 0.0))
        score += 0.15 * float(m.get("extractable_digits", 0.0))
        score += 0.10 * float(m.get("mixed_ratio", 0.0))
        score += 0.15 * (1.0 - float(m.get("top1_freq", 0.0)))
        score += 0.15 * (1.0 - float(m.get("null_ratio", 0.0)))
    elif role == "entity_name":
        score += 0.30 * float(m.get("alpha_ratio", 0.0))
        score += 0.20 * (1.0 - float(m.get("all_digits", 0.0)))
        score += 0.20 * (1.0 - float(m.get("top1_freq", 0.0)))
        score += 0.20 * float(m.get("cardinality_ratio", 0.0))
        score += 0.10 * (1.0 - float(m.get("null_ratio", 0.0)))
    elif role == "measure":
        score += 0.45 * float(m.get("numeric_ratio", 0.0))
        score += 0.20 * float(m.get("cardinality_ratio", 0.0))
        score += 0.20 * (1.0 - float(m.get("null_ratio", 0.0)))
        score += 0.15 * (1.0 - float(m.get("has_prefix_pattern", 0.0)))
    elif role == "date":
        score += 0.65 * float(m.get("date_parsable_ratio", 0.0))
        score += 0.10 * float(m.get("has_date_sep", 0.0))
        score += 0.10 * (1.0 - float(m.get("null_ratio", 0.0)))
        score += 0.15 * (1.0 - float(m.get("top1_freq", 0.0)))
    else:
        score = 0.1
    return max(0.0, min(1.0, score))


def filter_candidates(
    signatures: List[Dict[str, Any]],
    fingerprints: List[Dict[str, Any]],
    threshold: float = 0.52,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sig in signatures:
        for fp in fingerprints:
            s = score_role_compatibility(sig, fp)
            if s < float(threshold):
                continue
            out.append(
                CandidateMatch(
                    role=str(sig.get("role") or "unknown"),
                    table=str(fp.get("table") or ""),
                    column=str(fp.get("column") or ""),
                    score=round(float(s), 4),
                ).to_dict()
            )
    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return out


# ---------------------------------------------------------------------------
# C_trap: Top-K most confusable columns per candidate target column
# ---------------------------------------------------------------------------

_FP_KEYS: tuple[str, ...] = (
    "numeric_ratio", "alpha_ratio", "mixed_ratio", "has_special_ratio",
    "date_parsable_ratio", "null_ratio", "cardinality_ratio", "top1_freq",
    "top5_coverage", "singleton_ratio", "mean_length", "std_length",
    "mean_value", "std_value", "all_digits", "has_prefix_pattern",
    "has_date_sep", "has_currency", "uniform_length", "extractable_digits",
)


def _fp_vec(fp: Dict[str, Any]) -> List[float]:
    m = (fp or {}).get("metrics") or {}
    return [float(m.get(k, 0.0) or 0.0) for k in _FP_KEYS]


def _cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def build_trap_columns(
    fingerprints: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    top_k: int = 4,
) -> Dict[str, List[Dict[str, Any]]]:
    """For each candidate target column, find Top-K most similar non-target columns."""
    fp_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    for fp in fingerprints or []:
        t = str(fp.get("table") or "")
        c = str(fp.get("column") or "")
        if t and c:
            fp_index[(t, c)] = fp

    cand_keys = {(str(c.get("table")), str(c.get("column"))) for c in candidates}
    trap: Dict[str, List[Dict[str, Any]]] = {}

    for cand in candidates:
        ct = str(cand.get("table") or "")
        cc = str(cand.get("column") or "")
        key = f"{ct}.{cc}"
        target_fp = fp_index.get((ct, cc))
        if not target_fp:
            continue
        tv = _fp_vec(target_fp)

        scored = []
        for (ft, fc), fp in fp_index.items():
            if (ft, fc) == (ct, cc):
                continue
            if (ft, fc) in cand_keys and ft == ct:
                continue  # skip same-table candidates (not confusable across sources)
            sim = _cosine_sim(tv, _fp_vec(fp))
            scored.append({"table": ft, "column": fc, "similarity": round(sim, 4)})

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        trap[key] = scored[:top_k]

    return trap

