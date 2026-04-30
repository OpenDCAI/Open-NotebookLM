"""Handle feedback processing and material collection integration."""

from __future__ import annotations

from typing import Any, Dict, List

from .feedback_mechanism import ElementFeedback, FeedbackType, ModifyType, SlideFeedback
from .feedback_applier import FeedbackApplier


class FeedbackHandler:
    """Process feedback and identify material collection requirements."""

    @staticmethod
    def extract_material_collection_tasks(
        slide_ir: Dict[str, Any], feedback: SlideFeedback
    ) -> List[Dict[str, Any]]:
        """Extract tasks requiring material collection from feedback.

        Returns list of tasks with:
        - element_id: ID of element needing material
        - element_type: Type of element (IMAGE, SHAPE, etc.)
        - description: What material is needed
        - source_evidence: Evidence for the material request
        """
        tasks = []
        for fb in feedback.feedbacks:
            if fb.operation == FeedbackType.ADD:
                # ADD operations always need material collection
                tasks.append({
                    "element_id": fb.element_id,
                    "element_type": fb.element_type.value,
                    "operation": "add",
                    "description": fb.content,
                    "source_evidence": fb.source_evidence or [],
                })
            elif (
                fb.operation == FeedbackType.MODIFY
                and fb.modify_type == ModifyType.CONTENT
            ):
                # MODIFY CONTENT operations need material collection
                tasks.append({
                    "element_id": fb.element_id,
                    "element_type": fb.element_type.value,
                    "operation": "modify_content",
                    "description": fb.content,
                    "source_evidence": fb.source_evidence or [],
                })
        return tasks

    @staticmethod
    def apply_feedback_with_materials(
        slide_ir: Dict[str, Any],
        feedback: SlideFeedback,
        materials: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Apply feedback to slide IR, optionally with collected materials.

        Args:
            slide_ir: Original slide IR
            feedback: Feedback to apply
            materials: Collected materials (optional, for ADD/MODIFY CONTENT operations)

        Returns:
            Updated slide IR with feedback applied
        """
        result = FeedbackApplier.apply_feedback(slide_ir, feedback)

        # If materials provided, update blocks with material paths
        if materials:
            blocks = result.get("blocks", [])
            for block in blocks:
                if block.get("requires_material_collection"):
                    element_id = block.get("block_id")
                    if element_id in materials:
                        block["content"] = materials[element_id]
                    del block["requires_material_collection"]

        return result
