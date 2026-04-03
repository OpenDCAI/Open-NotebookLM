"""
Routing feedback and adaptive learning service.

Enhancement 5: Tracks routing decision outcomes and learns from historical results
to improve future routing decisions and enable path escalation (FAST→STANDARD).

Zero additional LLM cost - all adjustments are based on historical success/failure rates.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class RoutingOutcome:
    """Record of a routing decision and its result."""
    path: str  # "fast", "standard", "full"
    question_keywords: Tuple[str, ...]  # Normalized question keywords
    success: bool
    error_type: Optional[str] = None  # e.g., "table_not_found", "syntax_error"
    execution_time_ms: Optional[int] = None
    sql_attempts: int = 1


class RoutingFeedbackTracker:
    """
    Tracks routing outcomes and provides adaptive weighting.

    Records historical results per (path, keywords) combination,
    enabling data-driven routing improvements.
    """

    def __init__(self):
        # {(path, keywords_tuple): [RoutingOutcome, ...]}
        self._outcomes: Dict[Tuple[str, Tuple], list] = defaultdict(list)

    def record_outcome(
        self,
        path: str,
        question: str,
        success: bool,
        error_type: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
        sql_attempts: int = 1,
    ):
        """
        Record a routing decision outcome.

        Args:
            path: The routing path that was taken ("fast", "standard", "full")
            question: The user question (will be normalized to keywords)
            success: Whether the routing succeeded
            error_type: If failed, the error classification
            execution_time_ms: Query execution time in milliseconds
            sql_attempts: Number of SQL generation/execution attempts needed
        """
        keywords = self._extract_keywords(question)
        key = (path, keywords)

        outcome = RoutingOutcome(
            path=path,
            question_keywords=keywords,
            success=success,
            error_type=error_type,
            execution_time_ms=execution_time_ms,
            sql_attempts=sql_attempts,
        )
        self._outcomes[key].append(outcome)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Routing outcome recorded: path={path}, keywords={keywords}, "
                f"success={success}, error={error_type}"
            )

    def get_success_rate(self, path: str, question: str) -> float:
        """
        Get historical success rate for a path + question combination.

        Returns:
            Float between 0.0 and 1.0. Returns 0.5 if insufficient data.
        """
        keywords = self._extract_keywords(question)
        key = (path, keywords)
        outcomes = self._outcomes.get(key, [])

        if len(outcomes) < 2:
            return 0.5  # Insufficient data - neutral default

        successes = sum(1 for o in outcomes if o.success)
        return successes / len(outcomes)

    def get_path_adjustments(self, question: str) -> Dict[str, float]:
        """
        Get weight adjustments for all paths based on historical success rates.

        Returns:
            Dict like {"fast": -0.15, "standard": +0.1, "full": +0.05}
            Adjustments are relative (can be added to base scores).
        """
        keywords = self._extract_keywords(question)
        adjustments = {}

        for path in ["fast", "standard", "full"]:
            success_rate = self.get_success_rate(path, question)
            # Lower success rate → negative adjustment
            # Higher success rate → positive adjustment
            # Base: 0.5 success rate = 0 adjustment
            adjustment = (success_rate - 0.5) * 0.3  # Scale factor of 0.3
            adjustments[path] = adjustment

        return adjustments

    def should_escalate_to_standard(
        self,
        question: str,
        error_count: int,
        max_retries: int,
    ) -> bool:
        """
        Check if FAST path should escalate to STANDARD based on history.

        Returns True if:
        1. FAST path has <30% historical success rate for this question type
        2. Error count has reached max_retries
        """
        fast_success_rate = self.get_success_rate("fast", question)

        # Escalate if FAST has poor historical rate and we've hit max retries
        should_escalate = fast_success_rate < 0.3 and error_count >= max_retries

        if should_escalate:
            logger.info(
                f"Escalation triggered: FAST path success rate={fast_success_rate:.2f} "
                f"is low, escalating to STANDARD (error_count={error_count}/{max_retries})"
            )

        return should_escalate

    def get_stats(self, path: str) -> Dict:
        """Get aggregated statistics for a path."""
        outcomes = [o for outcomes_list in self._outcomes.values() for o in outcomes_list if o.path == path]

        if not outcomes:
            return {"path": path, "total": 0}

        successes = sum(1 for o in outcomes if o.success)
        avg_time = sum(o.execution_time_ms for o in outcomes if o.execution_time_ms) / len(outcomes) if outcomes else 0
        avg_attempts = sum(o.sql_attempts for o in outcomes) / len(outcomes)

        return {
            "path": path,
            "total": len(outcomes),
            "success_count": successes,
            "success_rate": successes / len(outcomes),
            "avg_execution_time_ms": avg_time,
            "avg_sql_attempts": avg_attempts,
            "error_types": dict(self._count_error_types([o for o in outcomes if not o.success])),
        }

    def _extract_keywords(self, question: str) -> Tuple[str, ...]:
        """Extract and normalize keywords from question."""
        # Very simple: split by space and take non-trivial words
        words = question.lower().split()
        # Filter out very short words and common stopwords
        keywords = tuple(sorted(set(
            w for w in words
            if len(w) > 2 and w not in {"and", "the", "for", "from", "with", "that", "this"}
        )))
        return keywords or ("generic",)

    def _count_error_types(self, failures: list) -> Dict[str, int]:
        """Count error types from failed outcomes."""
        counts = defaultdict(int)
        for outcome in failures:
            if outcome.error_type:
                counts[outcome.error_type] += 1
        return dict(counts)

    def clear(self):
        """Clear all recorded outcomes."""
        self._outcomes.clear()


# Singleton instance
routing_feedback_tracker = RoutingFeedbackTracker()
