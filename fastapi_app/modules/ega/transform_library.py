"""
Transformation library for EGA TCS.
"""
from __future__ import annotations

import itertools
import re
from datetime import datetime
from typing import Callable, Dict, List


def _to_str(v) -> str:
    if v is None:
        return ""
    return str(v)


def _is_numeric(v: str) -> bool:
    try:
        float(v)
        return True
    except Exception:
        return False


def _date_normalize(v: str) -> str:
    s = (v or "").strip()
    if not s:
        return s
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime("%Y-%m-%d")
        except Exception:
            continue
    return s


ATOMIC_TRANSFORMS: Dict[str, Callable[[str], str]] = {
    "identity": lambda v: _to_str(v),
    "lowercase": lambda v: _to_str(v).lower(),
    "uppercase": lambda v: _to_str(v).upper(),
    "strip": lambda v: _to_str(v).strip(),
    "strip_whitespace": lambda v: re.sub(r"\s+", "", _to_str(v)),
    "remove_punct": lambda v: re.sub(r"[^\w\s]", "", _to_str(v)),
    "extract_digits": lambda v: "".join(re.findall(r"\d+", _to_str(v))) or _to_str(v),
    "remove_leading_zeros": lambda v: str(int(v)) if str(v).isdigit() else _to_str(v),
    "strip_prefix": lambda v: re.sub(r"^[A-Za-z]+[-_]", "", _to_str(v)),
    "date_normalize": lambda v: _date_normalize(_to_str(v)),
    "extract_currency": lambda v: re.sub(r"[$€£,]", "", _to_str(v)).strip(),
    "cast_int": lambda v: str(int(float(v))) if _is_numeric(_to_str(v)) else _to_str(v),
}


# SQL expression template where "{expr}" is replaced by current expression.
SQL_TRANSFORMS: Dict[str, str] = {
    "identity": "CAST({expr} AS VARCHAR)",
    "lowercase": "lower(CAST({expr} AS VARCHAR))",
    "uppercase": "upper(CAST({expr} AS VARCHAR))",
    "strip": "trim(CAST({expr} AS VARCHAR))",
    "strip_whitespace": "regexp_replace(CAST({expr} AS VARCHAR), '\\\\s+', '', 'g')",
    "remove_punct": "regexp_replace(CAST({expr} AS VARCHAR), '[^0-9A-Za-z_ ]', '', 'g')",
    "extract_digits": "COALESCE(regexp_replace(CAST({expr} AS VARCHAR), '[^0-9]', '', 'g'), '')",
    "remove_leading_zeros": "regexp_replace(CAST({expr} AS VARCHAR), '^0+', '')",
    "strip_prefix": "regexp_replace(CAST({expr} AS VARCHAR), '^[A-Za-z]+[-_]', '')",
    "date_normalize": "strftime(try_strptime(CAST({expr} AS VARCHAR), '%Y-%m-%d'), '%Y-%m-%d')",
    "extract_currency": "trim(regexp_replace(CAST({expr} AS VARCHAR), '[$€£,]', '', 'g'))",
    "cast_int": "CAST(try_cast(CAST({expr} AS VARCHAR) AS DOUBLE) AS BIGINT)",
}


SQL_BINARY_TRANSFORMS: Dict[str, str] = {
    "concat_space": "CONCAT(CAST({expr1} AS VARCHAR), ' ', CAST({expr2} AS VARCHAR))",
    "concat_comma": "CONCAT(CAST({expr1} AS VARCHAR), ', ', CAST({expr2} AS VARCHAR))",
    "concat_dash": "CONCAT(CAST({expr1} AS VARCHAR), '-', CAST({expr2} AS VARCHAR))",
    "concat_empty": "CONCAT(CAST({expr1} AS VARCHAR), CAST({expr2} AS VARCHAR))",
}


def build_sql_expr(chain_steps: List[str], base_expr: str) -> str:
    expr = base_expr
    for step in chain_steps:
        template = SQL_TRANSFORMS.get(step)
        if not template:
            continue
        expr = template.format(expr=expr)
    return expr


def build_binary_sql_expr(op: str, expr1: str, expr2: str) -> str:
    template = SQL_BINARY_TRANSFORMS.get(op)
    if not template:
        return expr1
    return template.format(expr1=expr1, expr2=expr2)


def apply_chain(chain_steps: List[str], value: str) -> str:
    out = _to_str(value)
    for step in chain_steps:
        fn = ATOMIC_TRANSFORMS.get(step)
        if fn is None:
            continue
        out = fn(out)
    return out


def generate_transform_chains(max_two_step: int = 80) -> Dict[str, List[str]]:
    chains: Dict[str, List[str]] = {}
    atoms = list(ATOMIC_TRANSFORMS.keys())

    for a in atoms:
        chains[a] = [a]

    two_step = 0
    for a, b in itertools.product(atoms, atoms):
        if a == b:
            continue
        name = f"{a}_then_{b}"
        chains[name] = [a, b]
        two_step += 1
        if two_step >= max_two_step:
            break

    chains["extract_digits_remove_zeros_cast"] = ["extract_digits", "remove_leading_zeros", "cast_int"]
    chains["strip_prefix_extract_digits_cast"] = ["strip_prefix", "extract_digits", "cast_int"]
    return chains

