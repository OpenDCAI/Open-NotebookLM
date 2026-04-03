"""
Core contracts for EGA modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExpectedSignature:
    role: str
    expected_type: str
    expected_cardinality: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "expected_type": self.expected_type,
            "expected_cardinality": self.expected_cardinality,
            "description": self.description,
        }


@dataclass
class ColumnFingerprint:
    table: str
    column: str
    metrics: Dict[str, float]
    sample_size: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "metrics": dict(self.metrics),
            "sample_size": self.sample_size,
        }


@dataclass
class CandidateMatch:
    role: str
    table: str
    column: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "table": self.table,
            "column": self.column,
            "score": self.score,
        }


@dataclass
class TransformScore:
    chain_name: str
    overlap: float
    competition: float
    degeneracy: float
    reward: float
    transformed_distinct: int
    right_distinct: int
    intersection_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_name": self.chain_name,
            "overlap": self.overlap,
            "competition": self.competition,
            "degeneracy": self.degeneracy,
            "reward": self.reward,
            "transformed_distinct": self.transformed_distinct,
            "right_distinct": self.right_distinct,
            "intersection_count": self.intersection_count,
        }


@dataclass
class AlignmentEdge:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    best_transform: str
    score: Dict[str, Any]
    canonical_alias: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "left_table": self.left_table,
            "left_column": self.left_column,
            "right_table": self.right_table,
            "right_column": self.right_column,
            "best_transform": self.best_transform,
            "score": dict(self.score),
            "canonical_alias": self.canonical_alias,
        }


@dataclass
class EGAContext:
    signatures: List[Dict[str, Any]] = field(default_factory=list)
    fingerprints: List[Dict[str, Any]] = field(default_factory=list)
    candidate_columns: List[Dict[str, Any]] = field(default_factory=list)
    relevant_tables: List[str] = field(default_factory=list)
    alignment_graph: List[Dict[str, Any]] = field(default_factory=list)
    clean_views: Dict[str, Any] = field(default_factory=dict)
    filtered_schema: str = ""
    clean_view_schema: str = ""
    prompt_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signatures": list(self.signatures),
            "fingerprints": list(self.fingerprints),
            "candidate_columns": list(self.candidate_columns),
            "relevant_tables": list(self.relevant_tables),
            "alignment_graph": list(self.alignment_graph),
            "clean_views": dict(self.clean_views),
            "filtered_schema": self.filtered_schema,
            "clean_view_schema": self.clean_view_schema,
            "prompt_hint": self.prompt_hint,
        }
