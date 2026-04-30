"""Slide element feedback mechanism supporting ADD/MODIFY/DELETE operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List


class FeedbackType(Enum):
    """Feedback operation types."""
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


class ElementType(Enum):
    """Element types on slide."""
    TEXT = "text"
    IMAGE = "image"
    SHAPE = "shape"
    CHART = "chart"


class ModifyType(Enum):
    """Types of MODIFY operations."""
    CONTENT = "content"  # Requires material collection (e.g., change image)
    PROPERTY = "property"  # Adjust existing element (e.g., position, size, style)


@dataclass
class ElementFeedback:
    """Feedback for a single element."""
    operation: FeedbackType
    element_type: ElementType
    element_id: str

    # For ADD/MODIFY
    content: str | None = None
    position: Dict[str, float] | None = None
    style: Dict[str, Any] | None = None

    # For MODIFY/DELETE
    reason: str | None = None
    source_evidence: List[str] | None = None

    # For MODIFY: distinguish between content change (needs material collection) vs property adjustment
    modify_type: ModifyType | None = None

    def validate(self) -> tuple[bool, str]:
        """Validate feedback constraints."""
        if self.operation in (FeedbackType.MODIFY, FeedbackType.DELETE):
            if not self.reason:
                return False, "MODIFY/DELETE operations require reason"
            if self.operation == FeedbackType.MODIFY:
                if not self.modify_type:
                    return False, "MODIFY operations must specify modify_type (CONTENT or PROPERTY)"
                if self.modify_type == ModifyType.CONTENT and not self.source_evidence:
                    return False, "MODIFY CONTENT operations must reference source evidence"

        if self.operation == FeedbackType.ADD:
            if not self.content:
                return False, "ADD operations require content"
            if not self.position:
                return False, "ADD operations require position"

        return True, ""


class SlideFeedback:
    """Feedback for a slide."""

    def __init__(self, slide_id: str):
        self.slide_id = slide_id
        self.feedbacks: List[ElementFeedback] = []

    def add_feedback(self, feedback: ElementFeedback) -> bool:
        """Add feedback with validation."""
        valid, error = feedback.validate()
        if not valid:
            return False
        self.feedbacks.append(feedback)
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "slide_id": self.slide_id,
            "feedbacks": [
                {
                    "operation": f.operation.value,
                    "element_type": f.element_type.value,
                    "element_id": f.element_id,
                    "content": f.content,
                    "position": f.position,
                    "style": f.style,
                    "reason": f.reason,
                    "source_evidence": f.source_evidence,
                    "modify_type": f.modify_type.value if f.modify_type else None,
                }
                for f in self.feedbacks
            ]
        }
