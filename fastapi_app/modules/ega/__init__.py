"""EGA modules."""

from .orchestrator import prepare_ega_context
from .extensional_profiling import (
    derive_expected_signatures,
    build_column_fingerprints,
    score_role_compatibility,
    filter_candidates,
)
from .tcs import evaluate_pair
from .clean_view import materialize_clean_views
from .spec_verifier import extract_deliverable_spec, verify_result

__all__ = [
    "prepare_ega_context",
    "derive_expected_signatures",
    "build_column_fingerprints",
    "score_role_compatibility",
    "filter_candidates",
    "evaluate_pair",
    "materialize_clean_views",
    "extract_deliverable_spec",
    "verify_result",
]

