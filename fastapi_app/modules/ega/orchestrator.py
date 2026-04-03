"""
EGA orchestration.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from .contracts import EGAContext, AlignmentEdge
from .extensional_profiling import derive_expected_signatures, build_column_fingerprints, filter_candidates, build_trap_columns
from .tcs import evaluate_pair
from .clean_view import materialize_clean_views
from .transform_library import generate_transform_chains


def _build_cache_key(
    datasource_ids: List[int],
    question: str,
    sample_rows: int,
    optimization_target: str,
    lambda1: float,
    lambda2: float,
    deep_probe: bool,
) -> tuple:
    ds_key = tuple(sorted(int(x) for x in (datasource_ids or [])))
    q_key = str(question or "").strip().lower()
    return (
        ds_key,
        q_key,
        int(sample_rows),
        str(optimization_target or "accuracy").strip().lower(),
        round(float(lambda1), 4),
        round(float(lambda2), 4),
        bool(deep_probe),
    )


def _build_filtered_schema_text(engine, relevant_tables: List[str], candidates: List[Dict[str, Any]]) -> str:
    by_table = defaultdict(set)
    for c in candidates:
        by_table[str(c.get("table"))].add(str(c.get("column")))

    lines = ["=== EGA Filtered Schema ==="]
    for reg in engine.get_registered_tables():
        table = reg.unified_table_name
        if table not in relevant_tables:
            continue
        lines.append(f"table {table}")
        cols = list(reg.columns or [])
        pick = by_table.get(table) or set(cols)
        for col in cols:
            if col in pick:
                lines.append(f"  - {col}")
    return "\n".join(lines)


def _build_clean_view_schema_text(clean_views: Dict[str, Any]) -> str:
    lines = ["=== EGA Clean View Schema ==="]
    for base, info in (clean_views or {}).items():
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
    return "\n".join(lines)


def _pair_candidates(
    candidates: List[Dict[str, Any]],
    fingerprints: List[Dict[str, Any]] | None = None,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Pair entity_id candidates across tables, prioritising FK→PK patterns.

    FK indicators: mixed_ratio, has_prefix_pattern (e.g. "S-0001")
    PK indicators: numeric_ratio, high cardinality
    Pairs where left looks like a dirty FK and right looks like a clean PK
    are scored higher so they appear within the pair_budget.
    """
    ids = [c for c in candidates if str(c.get("role")) == "entity_id"]

    # Build fingerprint lookup for priority scoring
    fp_idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for fp in (fingerprints or []):
        t = str(fp.get("table") or "")
        c = str(fp.get("column") or "")
        if t and c:
            fp_idx[(t, c)] = (fp.get("metrics") or {})

    def _fk_score(m: Dict[str, Any]) -> float:
        """Higher = more likely a dirty FK column."""
        return (float(m.get("mixed_ratio", 0)) * 0.4
                + float(m.get("has_prefix_pattern", 0)) * 0.4
                + float(m.get("has_special_ratio", 0)) * 0.2)

    def _pk_score(m: Dict[str, Any]) -> float:
        """Higher = more likely a clean PK column."""
        return (float(m.get("numeric_ratio", 0)) * 0.4
                + float(m.get("cardinality_ratio", 0)) * 0.4
                + (1.0 - float(m.get("null_ratio", 0))) * 0.2)

    out: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if a.get("table") == b.get("table"):
                continue
            ma = fp_idx.get((str(a.get("table")), str(a.get("column")))) or {}
            mb = fp_idx.get((str(b.get("table")), str(b.get("column")))) or {}
            # Try both directions, pick the better FK→PK assignment
            score_ab = _fk_score(ma) + _pk_score(mb)
            score_ba = _fk_score(mb) + _pk_score(ma)
            priority = max(score_ab, score_ba)
            if score_ba > score_ab:
                out.append((priority, b, a))
            else:
                out.append((priority, a, b))

    out.sort(key=lambda x: x[0], reverse=True)
    return [(a, b) for _, a, b in out]


_FP_KEYS: Tuple[str, ...] = (
    "numeric_ratio",
    "alpha_ratio",
    "mixed_ratio",
    "has_special_ratio",
    "date_parsable_ratio",
    "null_ratio",
    "cardinality_ratio",
    "top1_freq",
    "top5_coverage",
    "singleton_ratio",
    "mean_length",
    "std_length",
    "mean_value",
    "std_value",
    "all_digits",
    "has_prefix_pattern",
    "has_date_sep",
    "has_currency",
    "uniform_length",
    "extractable_digits",
)


def _fp_map(fingerprints: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for fp in fingerprints or []:
        t = str(fp.get("table") or "")
        c = str(fp.get("column") or "")
        if t and c:
            out[(t, c)] = fp
    return out


def _fp_vec(fp: Dict[str, Any]) -> List[float]:
    metrics = (fp or {}).get("metrics") or {}
    return [float(metrics.get(k, 0.0) or 0.0) for k in _FP_KEYS]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _get_memory(engine) -> List[Dict[str, Any]]:
    memory = getattr(engine, "_ega_fp_memory", None)
    if not isinstance(memory, list):
        memory = []
        setattr(engine, "_ega_fp_memory", memory)
    return memory


def _find_memory_transform(
    engine,
    left_fp: Dict[str, Any],
    right_fp: Dict[str, Any],
    *,
    threshold: float = 0.95,
) -> Dict[str, Any] | None:
    memory = _get_memory(engine)
    if not memory:
        return None
    lv = _fp_vec(left_fp)
    rv = _fp_vec(right_fp)
    best: Dict[str, Any] | None = None
    best_sim = -1.0
    for item in memory:
        l2 = list(item.get("left_vec") or [])
        r2 = list(item.get("right_vec") or [])
        if not l2 or not r2:
            continue
        sim_direct = 0.5 * (_cosine(lv, l2) + _cosine(rv, r2))
        sim_swap = 0.5 * (_cosine(lv, r2) + _cosine(rv, l2))
        sim = max(sim_direct, sim_swap)
        if sim > best_sim:
            best_sim = sim
            best = item
    if best is None or best_sim < float(threshold):
        return None
    return {**best, "memory_similarity": float(best_sim)}


def write_success_memory(engine, ega_context: Dict[str, Any]) -> int:
    alignment_graph = list((ega_context or {}).get("alignment_graph") or [])
    fingerprints = list((ega_context or {}).get("fingerprints") or [])
    if not alignment_graph or not fingerprints:
        return 0
    fp_index = _fp_map(fingerprints)
    memory = _get_memory(engine)
    written = 0

    for edge in alignment_graph:
        lt = str(edge.get("left_table") or "")
        lc = str(edge.get("left_column") or "")
        rt = str(edge.get("right_table") or "")
        rc = str(edge.get("right_column") or "")
        transform = str(edge.get("best_transform") or "")
        score = edge.get("score") or {}
        reward = float(score.get("reward", 0.0) or 0.0)
        if not (lt and lc and rt and rc and transform):
            continue
        left_fp = fp_index.get((lt, lc))
        right_fp = fp_index.get((rt, rc))
        if not left_fp or not right_fp:
            continue
        lv = _fp_vec(left_fp)
        rv = _fp_vec(right_fp)
        merged = False
        for item in memory:
            if str(item.get("transform")) != transform:
                continue
            l2 = list(item.get("left_vec") or [])
            r2 = list(item.get("right_vec") or [])
            if not l2 or not r2:
                continue
            sim = 0.5 * (_cosine(lv, l2) + _cosine(rv, r2))
            if sim >= 0.995:
                item["hit_count"] = int(item.get("hit_count", 0)) + 1
                if reward > float(item.get("reward", 0.0) or 0.0):
                    item["reward"] = reward
                merged = True
                break
        if merged:
            written += 1
            continue
        memory.append(
            {
                "transform": transform,
                "left_vec": lv,
                "right_vec": rv,
                "reward": reward,
                "hit_count": 1,
            }
        )
        written += 1

    if len(memory) > 4000:
        del memory[: max(0, len(memory) - 4000)]
    return written


def prepare_ega_context(
    engine,
    datasource_ids: List[int],
    question: str,
    llm: Any,
    sample_rows: int = 100,
    optimization_target: str = "accuracy",
    lambda1: float = 0.3,
    lambda2: float = 0.5,
    deep_probe: bool = False,
) -> Dict[str, Any]:
    cache_key = _build_cache_key(
        datasource_ids=datasource_ids,
        question=question,
        sample_rows=sample_rows,
        optimization_target=optimization_target,
        lambda1=lambda1,
        lambda2=lambda2,
        deep_probe=deep_probe,
    )
    cache = getattr(engine, "_ega_context_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(engine, "_ega_context_cache", cache)
    if cache_key in cache:
        return copy.deepcopy(cache[cache_key])

    signatures = derive_expected_signatures(question, llm=llm)
    fingerprints = build_column_fingerprints(engine, datasource_ids, sample_rows=sample_rows)

    threshold = 0.48 if str(optimization_target).lower() == "accuracy" else 0.60
    if deep_probe:
        threshold = min(threshold, 0.45)
    candidates = filter_candidates(signatures, fingerprints, threshold=threshold)

    relevant_tables = sorted({str(c.get("table")) for c in candidates if c.get("table")})
    filtered_schema = _build_filtered_schema_text(engine, relevant_tables, candidates)

    # Build C_trap: Top-K most confusable columns per candidate
    trap_map = build_trap_columns(fingerprints, candidates, top_k=4)

    # Build same-table column index for binary concat search
    table_columns: Dict[str, List[str]] = defaultdict(list)
    for reg in engine.get_registered_tables():
        table_columns[reg.unified_table_name] = list(reg.columns or [])[:30]

    alignment_edges: List[Dict[str, Any]] = []
    pairs = _pair_candidates(candidates, fingerprints=fingerprints)
    chain_library = generate_transform_chains()
    pair_budget = 24 if str(optimization_target).lower() == "accuracy" else 12
    if deep_probe:
        pair_budget = 36
    fp_index = _fp_map(fingerprints)

    # Adjusted lambda2 for normalized entropy (less aggressive than old degeneracy)
    ib_lambda2 = 0.15
    ib_lambda3 = 0.02

    for a, b in pairs[:pair_budget]:
        left_table, left_col = str(a.get("table")), str(a.get("column"))
        right_table, right_col = str(b.get("table")), str(b.get("column"))

        # Use C_trap for focused competition instead of full candidate list
        trap_key = f"{right_table}.{right_col}"
        trap_cols: List[Tuple[str, str]] = [
            (str(tc.get("table")), str(tc.get("column")))
            for tc in (trap_map.get(trap_key) or [])
        ]
        # Fallback: if no trap columns, use old competitor logic
        if not trap_cols:
            for c in candidates:
                if c.get("table") == right_table and c.get("column") == right_col:
                    continue
                trap_cols.append((str(c.get("table")), str(c.get("column"))))
            trap_cols = trap_cols[:5]

        memory_hit = _find_memory_transform(
            engine,
            fp_index.get((left_table, left_col)) or {},
            fp_index.get((right_table, right_col)) or {},
            threshold=(0.94 if deep_probe else 0.96),
        )
        scored = None
        if memory_hit:
            mem_chain = str(memory_hit.get("transform") or "")
            if mem_chain and mem_chain in chain_library:
                quick = evaluate_pair(
                    engine=engine,
                    left_table=left_table,
                    left_col=left_col,
                    right_table=right_table,
                    right_col=right_col,
                    lambda1=lambda1,
                    lambda2=ib_lambda2,
                    lambda3=ib_lambda3,
                    trap_columns=trap_cols,
                    chain_library={mem_chain: chain_library[mem_chain]},
                )
                quick_best = quick.get("best") or {}
                if float(quick_best.get("overlap", 0.0) or 0.0) >= 0.65:
                    scored = quick
                    if isinstance(scored.get("best"), dict):
                        scored["best"]["from_memory"] = True
                        scored["best"]["memory_similarity"] = float(memory_hit.get("memory_similarity", 0.0) or 0.0)

        if scored is None:
            scored = evaluate_pair(
                engine=engine,
                left_table=left_table,
                left_col=left_col,
                right_table=right_table,
                right_col=right_col,
                lambda1=lambda1,
                lambda2=ib_lambda2,
                lambda3=ib_lambda3,
                trap_columns=trap_cols,
                same_table_columns=table_columns.get(left_table),
            )
        best = scored.get("best")
        if not best:
            continue
        if float(best.get("reward", -1.0)) < 0.25:
            continue

        edge = AlignmentEdge(
            left_table=left_table,
            left_column=left_col,
            right_table=right_table,
            right_column=right_col,
            best_transform=str(best.get("chain_name")),
            score=best,
            canonical_alias=f"{left_col}__ega_norm",
        )
        alignment_edges.append(edge.to_dict())

    clean_views = materialize_clean_views(engine, alignment_edges, relevant_tables=relevant_tables)
    clean_view_schema = _build_clean_view_schema_text(clean_views)
    prompt_hint = (
        "EGA prepared clean views. Prefer querying ega_v_* views and normalized columns. "
        "Use business SQL only on clean views."
    )

    ctx = EGAContext(
        signatures=signatures,
        fingerprints=fingerprints,
        candidate_columns=candidates,
        relevant_tables=relevant_tables,
        alignment_graph=alignment_edges,
        clean_views=clean_views,
        filtered_schema=filtered_schema,
        clean_view_schema=clean_view_schema,
        prompt_hint=prompt_hint,
    )
    payload = ctx.to_dict()
    # Keep the cache bounded to avoid unbounded memory growth in long sessions.
    if len(cache) >= 24:
        oldest = next(iter(cache.keys()))
        cache.pop(oldest, None)
    cache[cache_key] = payload
    return copy.deepcopy(payload)
