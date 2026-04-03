"""
Information Bottleneck Synthesis (IBS) — improved TCS with 4-term reward,
SoftOverlap annealing, greedy search + backtracking, and binary concat.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from .contracts import TransformScore
from .transform_library import (
    generate_transform_chains,
    build_sql_expr,
    build_binary_sql_expr,
    ATOMIC_TRANSFORMS,
    SQL_BINARY_TRANSFORMS,
)


def _quote_ident(s: str) -> str:
    return '"' + str(s).replace('"', '""') + '"'


def _distinct_values(engine, table: str, expr: str, limit: int = 1200) -> List[str]:
    sql = (
        f"SELECT DISTINCT CAST({expr} AS VARCHAR) AS val FROM {_quote_ident(table)} "
        "WHERE "
        f"{expr} IS NOT NULL AND CAST({expr} AS VARCHAR) <> '' "
        f"LIMIT {int(limit)}"
    )
    rows = engine.conn.execute(sql).fetchall()
    out: List[str] = []
    for (v,) in rows:
        if v is None:
            continue
        sv = str(v).strip()
        if sv:
            out.append(sv)
    return out


# ---------------------------------------------------------------------------
# SoftOverlap with annealing
# ---------------------------------------------------------------------------

def _hard_overlap(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    inter = set_a & set_b
    denom = max(1, min(len(set_a), len(set_b)))
    return len(inter) / denom


def _norm_edit_dist(a: str, b: str) -> float:
    """Normalized Levenshtein distance in [0, 1].  O(min(m,n)) space."""
    if a == b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 1.0
    # Ensure la <= lb for space efficiency
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    prev = list(range(la + 1))
    for j in range(1, lb + 1):
        curr = [j] + [0] * la
        for i in range(1, la + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[i] = min(curr[i - 1] + 1, prev[i] + 1, prev[i - 1] + cost)
        prev = curr
    return prev[la] / max(la, lb)


def _soft_overlap(set_a: set, set_b: set, k: float) -> float:
    """SoftOverlap: exact matches count 1.0, near-misses use exp(-k * norm_edit_dist).

    When k >= 50, falls back to hard overlap for speed.
    Uses normalized Levenshtein distance (not char-Jaccard) for correctness.
    """
    if not set_a or not set_b:
        return 0.0
    if k >= 50.0:
        return _hard_overlap(set_a, set_b)

    exact = set_a & set_b
    hard_count = float(len(exact))

    left_unmatched = list(set_a - exact)
    right_unmatched = list(set_b - exact)

    if not left_unmatched or not right_unmatched:
        denom = max(1, min(len(set_a), len(set_b)))
        return hard_count / denom

    # Cap the pairwise comparisons to avoid O(n*m) blowup on large sets
    MAX_LEFT = 80
    MAX_RIGHT = 80
    if len(left_unmatched) > MAX_LEFT:
        left_unmatched = left_unmatched[:MAX_LEFT]
    if len(right_unmatched) > MAX_RIGHT:
        right_unmatched = right_unmatched[:MAX_RIGHT]

    soft_sum = 0.0
    for v in left_unmatched:
        best_sim = 0.0
        for u in right_unmatched:
            dist = _norm_edit_dist(v, u)
            sim = math.exp(-k * dist)
            if sim > best_sim:
                best_sim = sim
            if best_sim > 0.95:
                break
        soft_sum += best_sim

    denom = max(1, min(len(set_a), len(set_b)))
    return (hard_count + soft_sum) / denom


# ---------------------------------------------------------------------------
# 4-term reward
# ---------------------------------------------------------------------------

def _normalized_entropy(unique_count: int, total_count: int) -> float:
    """log(unique) / log(total). Returns 1.0 when no collapse, 0.0 when full collapse."""
    if unique_count <= 1 or total_count <= 1:
        return 0.0
    return math.log(unique_count) / math.log(total_count)


def _compute_reward(
    left_set: set,
    right_set: set,
    trap_columns_sets: List[set],
    k: float,
    raw_left_total: int,
    chain_length: int,
    lambda1: float,
    lambda2: float,
    lambda3: float,
) -> Tuple[float, float, float, float, float]:
    """Compute 4-term reward. Returns (reward, match, disc, entropy_pen, len_pen)."""
    # Term 1: SoftOverlap (match), with hard-overlap floor guard.
    # When hard_overlap is 0, cap the soft score to avoid inflated rewards
    # from short target strings (e.g. "1","2") that have moderate Levenshtein
    # similarity to any long string.
    hard_ov = _hard_overlap(left_set, right_set)
    match = _soft_overlap(left_set, right_set, k)
    if hard_ov == 0.0:
        match = min(match, 0.15)

    # Term 2: Discriminability (local competition against C_trap)
    disc = 0.0
    for trap_set in trap_columns_sets:
        if not trap_set:
            continue
        c = _soft_overlap(left_set, trap_set, k)
        if c > disc:
            disc = c

    # Term 3: Entropy preservation (clamped to [0,1] — transforms that increase
    # cardinality beyond raw should not be rewarded via negative penalty)
    h_norm = _normalized_entropy(len(left_set), max(1, raw_left_total))
    entropy_pen = max(0.0, min(1.0, 1.0 - h_norm))

    # Term 4: Length penalty
    len_pen = float(chain_length)

    reward = match - lambda1 * disc - lambda2 * entropy_pen - lambda3 * len_pen
    return reward, match, disc, entropy_pen, len_pen


# ---------------------------------------------------------------------------
# Greedy search with backtracking
# ---------------------------------------------------------------------------

def _greedy_search(
    engine,
    left_table: str,
    left_col: str,
    right_set: set,
    trap_sets: List[set],
    raw_left_total: int,
    *,
    same_table_columns: List[str] | None = None,
    lambda1: float = 0.3,
    lambda2: float = 0.15,
    lambda3: float = 0.02,
    k_0: float = 1.5,
    alpha: float = 0.35,
    tau_lock: float = 0.80,
    max_steps: int = 5,
    backtrack_patience: int = 2,
    sample_limit: int = 1200,
) -> Dict[str, Any]:
    """Greedy search over transform operators with SoftOverlap annealing."""
    distinct_cache: Dict[Tuple[str, str, int], set] = {}

    def _ds(table: str, expr: str) -> set:
        key = (str(table), str(expr), int(sample_limit))
        cached = distinct_cache.get(key)
        if cached is not None:
            return cached
        vals = set(_distinct_values(engine, table, expr, limit=sample_limit))
        distinct_cache[key] = vals
        return vals

    atoms = list(ATOMIC_TRANSFORMS.keys())
    quoted_left = _quote_ident(left_col)

    best_overall_reward = -999.0
    best_overall: Dict[str, Any] | None = None

    # Also evaluate identity (no transform)
    identity_set = _ds(left_table, quoted_left)
    if identity_set:
        k_init = k_0
        r, m, d, ep, lp = _compute_reward(
            identity_set, right_set, trap_sets, k_init,
            raw_left_total, 0, lambda1, lambda2, lambda3,
        )
        hard_ov = _hard_overlap(identity_set, right_set)
        best_overall_reward = r
        best_overall = {
            "chain_name": "identity", "steps": ["identity"],
            "reward": r, "overlap": hard_ov, "match_soft": m,
            "competition": d, "entropy_penalty": ep,
            "transformed_distinct": len(identity_set),
            "right_distinct": len(right_set),
            "intersection_count": len(identity_set & right_set),
        }

    # Greedy search
    current_steps: List[str] = []
    current_expr = quoted_left
    step_reward = best_overall_reward
    checkpoints: List[Tuple[List[str], str, float]] = []
    no_improve = 0

    for t in range(max_steps):
        k_t = k_0 * math.exp(alpha * t)

        candidates: List[Tuple[str, List[str], str, set, float, float]] = []

        # Try all unary operators
        for op in atoms:
            trial_steps = current_steps + [op]
            trial_expr = build_sql_expr(trial_steps, quoted_left)
            trial_set = _ds(left_table, trial_expr)
            if not trial_set:
                continue
            r, m, d, ep, lp = _compute_reward(
                trial_set, right_set, trap_sets, k_t,
                raw_left_total, len(trial_steps), lambda1, lambda2, lambda3,
            )
            hard_ov = _hard_overlap(trial_set, right_set)
            candidates.append((op, trial_steps, trial_expr, trial_set, r, hard_ov))

        # Try binary concat (same-table columns only, only at step 0)
        if t == 0 and same_table_columns:
            for other_col in same_table_columns[:8]:
                if other_col == left_col:
                    continue
                for bop in SQL_BINARY_TRANSFORMS:
                    trial_expr = build_binary_sql_expr(bop, quoted_left, _quote_ident(other_col))
                    trial_set = _ds(left_table, trial_expr)
                    if not trial_set:
                        continue
                    trial_steps_b = [f"{bop}({left_col},{other_col})"]
                    r, m, d, ep, lp = _compute_reward(
                        trial_set, right_set, trap_sets, k_t,
                        raw_left_total, 1, lambda1, lambda2, lambda3,
                    )
                    hard_ov = _hard_overlap(trial_set, right_set)
                    candidates.append((trial_steps_b[0], trial_steps_b, trial_expr, trial_set, r, hard_ov))

        if not candidates:
            break

        candidates.sort(key=lambda x: x[4], reverse=True)
        top_op, top_steps, top_expr, top_set, top_r, top_hard = candidates[0]

        # τ_lock check
        so_val = _soft_overlap(top_set, right_set, k_t)
        if so_val >= tau_lock:
            if top_hard >= 0.45:
                best_overall = {
                    "chain_name": "_then_".join(top_steps),
                    "steps": top_steps,
                    "reward": top_r, "overlap": top_hard, "match_soft": so_val,
                    "competition": 0.0, "entropy_penalty": 0.0,
                    "transformed_distinct": len(top_set),
                    "right_distinct": len(right_set),
                    "intersection_count": len(top_set & right_set),
                }
                best_overall_reward = top_r
                break

        if top_r > step_reward:
            step_reward = top_r
            current_steps = top_steps
            current_expr = top_expr
            no_improve = 0
            checkpoints.append((current_steps[:], current_expr, step_reward))
            # Update best overall
            if top_r > best_overall_reward:
                best_overall_reward = top_r
                best_overall = {
                    "chain_name": "_then_".join(top_steps),
                    "steps": top_steps,
                    "reward": top_r, "overlap": top_hard, "match_soft": so_val,
                    "competition": 0.0, "entropy_penalty": 0.0,
                    "transformed_distinct": len(top_set),
                    "right_distinct": len(right_set),
                    "intersection_count": len(top_set & right_set),
                }
        else:
            no_improve += 1
            if no_improve >= backtrack_patience:
                if checkpoints:
                    current_steps, current_expr, step_reward = checkpoints.pop()
                    no_improve = 0
                else:
                    break

    return {"best": best_overall, "search_type": "greedy"}


# ---------------------------------------------------------------------------
# Public API — backward-compatible evaluate_pair
# ---------------------------------------------------------------------------

def evaluate_pair(
    engine,
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
    *,
    lambda1: float = 0.3,
    lambda2: float = 0.15,
    lambda3: float = 0.02,
    competitor_columns: List[Tuple[str, str]] | None = None,
    trap_columns: List[Tuple[str, str]] | None = None,
    chain_library: Dict[str, List[str]] | None = None,
    same_table_columns: List[str] | None = None,
    sample_limit: int = 1200,
    use_greedy: bool = True,
) -> Dict[str, Any]:
    """Evaluate a candidate column pair and find the best transform chain.

    When *chain_library* is a single-entry dict (memory fast-path), runs only
    that chain with hard overlap — no greedy search overhead.
    """
    distinct_cache: Dict[Tuple[str, str, int], set] = {}

    def _ds(table: str, expr: str) -> set:
        key = (str(table), str(expr), int(sample_limit))
        cached = distinct_cache.get(key)
        if cached is not None:
            return cached
        vals = set(_distinct_values(engine, table, expr, limit=sample_limit))
        distinct_cache[key] = vals
        return vals

    right_set = _ds(right_table, _quote_ident(right_col))
    if not right_set:
        return {"best": None, "scores": []}

    raw_left = _ds(left_table, _quote_ident(left_col))
    raw_left_total = max(1, len(raw_left))

    # Build trap column sets (prefer explicit trap_columns, fall back to competitors)
    trap_sources = trap_columns or competitor_columns or []
    trap_sets: List[set] = []
    for t, c in trap_sources[:5]:
        ts = _ds(t, _quote_ident(c))
        if ts:
            trap_sets.append(ts)

    # Fast path: single-chain evaluation (memory hit verification)
    if chain_library and len(chain_library) == 1:
        chain_name, steps = next(iter(chain_library.items()))
        left_expr = build_sql_expr(steps, _quote_ident(left_col))
        left_set = _ds(left_table, left_expr)
        if not left_set:
            return {"best": None, "scores": []}
        hard_ov = _hard_overlap(left_set, right_set)
        r, _m, d, ep, _lp = _compute_reward(
            left_set, right_set, trap_sets, 50.0,
            raw_left_total, len(steps), lambda1, lambda2, lambda3,
        )
        ts = TransformScore(
            chain_name=chain_name, overlap=hard_ov,
            competition=d, degeneracy=ep, reward=r,
            transformed_distinct=len(left_set),
            right_distinct=len(right_set),
            intersection_count=len(left_set & right_set),
        )
        return {"best": ts.to_dict(), "scores": [ts.to_dict()]}

    # Greedy search path (with chain-library fallback when greedy finds no overlap)
    if use_greedy:
        result = _greedy_search(
            engine, left_table, left_col, right_set, trap_sets,
            raw_left_total,
            same_table_columns=same_table_columns,
            lambda1=lambda1, lambda2=lambda2, lambda3=lambda3,
            sample_limit=sample_limit,
        )
        greedy_best = result.get("best")
        greedy_overlap = float((greedy_best or {}).get("overlap", 0.0))

        # If greedy found positive overlap, use it directly
        if greedy_best and greedy_overlap > 0.0:
            ts = TransformScore(
                chain_name=str(greedy_best.get("chain_name", "identity")),
                overlap=greedy_overlap,
                competition=float(greedy_best.get("competition", 0.0)),
                degeneracy=float(greedy_best.get("entropy_penalty", 0.0)),
                reward=float(greedy_best.get("reward", 0.0)),
                transformed_distinct=int(greedy_best.get("transformed_distinct", 0)),
                right_distinct=int(greedy_best.get("right_distinct", 0)),
                intersection_count=int(greedy_best.get("intersection_count", 0)),
            )
            return {"best": ts.to_dict(), "scores": [ts.to_dict()]}

        # Greedy found no hard overlap — fallback to pre-defined multi-step
        # chains that greedy's horizon can't discover (e.g. extract_digits →
        # remove_leading_zeros which needs 2 steps to show any overlap).
        fallback_chains = chain_library or generate_transform_chains()
        fb_best: Dict[str, Any] | None = None
        fb_best_reward = -999.0
        for cn, steps in fallback_chains.items():
            left_expr = build_sql_expr(steps, _quote_ident(left_col))
            left_set = _ds(left_table, left_expr)
            if not left_set:
                continue
            hard_ov = _hard_overlap(left_set, right_set)
            if hard_ov <= 0.0:
                continue  # only consider chains with actual overlap
            r, _m, d, ep, _lp = _compute_reward(
                left_set, right_set, trap_sets, 50.0,
                raw_left_total, len(steps), lambda1, lambda2, lambda3,
            )
            if r > fb_best_reward:
                fb_best_reward = r
                fb_best = {
                    "chain_name": cn, "overlap": hard_ov,
                    "competition": d, "degeneracy": ep, "reward": r,
                    "transformed_distinct": len(left_set),
                    "right_distinct": len(right_set),
                    "intersection_count": len(left_set & right_set),
                }

        # Pick the better of greedy vs fallback
        final = fb_best or greedy_best
        if final:
            ts = TransformScore(
                chain_name=str(final.get("chain_name", "identity")),
                overlap=float(final.get("overlap", 0.0)),
                competition=float(final.get("competition", 0.0)),
                degeneracy=float(final.get("degeneracy", 0.0)),
                reward=float(final.get("reward", 0.0)),
                transformed_distinct=int(final.get("transformed_distinct", 0)),
                right_distinct=int(final.get("right_distinct", 0)),
                intersection_count=int(final.get("intersection_count", 0)),
            )
            return {"best": ts.to_dict(), "scores": [ts.to_dict()]}
        return {"best": None, "scores": []}

    # Fallback: brute-force enumeration (legacy path)
    chains = chain_library or generate_transform_chains()
    scores: List[Dict[str, Any]] = []
    for chain_name, steps in chains.items():
        left_expr = build_sql_expr(steps, _quote_ident(left_col))
        left_set = _ds(left_table, left_expr)
        if not left_set:
            continue
        hard_ov = _hard_overlap(left_set, right_set)
        r, _m, d, ep, _lp = _compute_reward(
            left_set, right_set, trap_sets, 50.0,
            raw_left_total, len(steps), lambda1, lambda2, lambda3,
        )
        ts = TransformScore(
            chain_name=chain_name, overlap=hard_ov,
            competition=d, degeneracy=ep, reward=r,
            transformed_distinct=len(left_set),
            right_distinct=len(right_set),
            intersection_count=len(left_set & right_set),
        )
        scores.append(ts.to_dict())

    scores.sort(key=lambda x: x.get("reward", -1.0), reverse=True)
    return {"best": (scores[0] if scores else None), "scores": scores[:30]}
