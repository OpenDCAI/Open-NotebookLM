"""Apply feedback to slide IR."""

from __future__ import annotations

from typing import Any, Dict

from .feedback_mechanism import ElementFeedback, FeedbackType, ModifyType, SlideFeedback


class FeedbackApplier:
    """Apply feedback to slide IR."""

    @staticmethod
    def apply_feedback(slide_ir: Dict[str, Any], feedback: SlideFeedback) -> Dict[str, Any]:
        """Apply all feedbacks to slide IR."""
        result = dict(slide_ir)

        for fb in feedback.feedbacks:
            if fb.operation == FeedbackType.ADD:
                FeedbackApplier._apply_add(result, fb)
            elif fb.operation == FeedbackType.MODIFY:
                FeedbackApplier._apply_modify(result, fb)
            elif fb.operation == FeedbackType.DELETE:
                FeedbackApplier._apply_delete(result, fb)

        return result

    @staticmethod
    def _apply_add(slide_ir: Dict[str, Any], feedback: ElementFeedback) -> None:
        """Add new element to slide IR."""
        if "blocks" not in slide_ir:
            slide_ir["blocks"] = []

        new_block = {
            "block_id": feedback.element_id,
            "kind": feedback.element_type.value,
            "content": feedback.content,
            "position": feedback.position,
            "style": feedback.style or {},
        }
        slide_ir["blocks"].append(new_block)

    @staticmethod
    def _apply_modify(slide_ir: Dict[str, Any], feedback: ElementFeedback) -> None:
        """Modify existing element in slide IR.

        Two types of modifications:
        - PROPERTY: adjust position, size, style of existing element
        - CONTENT: change element content (requires material collection for images)
        """
        blocks = slide_ir.get("blocks", [])
        for block in blocks:
            if block.get("block_id") == feedback.element_id:
                if feedback.modify_type == ModifyType.PROPERTY:
                    # Property modification: adjust position, size, style
                    if feedback.position:
                        block["position"] = feedback.position
                    if feedback.style:
                        block["style"] = feedback.style
                elif feedback.modify_type == ModifyType.CONTENT:
                    # Content modification: update content and mark for material collection
                    if feedback.content:
                        block["content"] = feedback.content
                    block["requires_material_collection"] = True

                # Store modification metadata
                if feedback.reason:
                    block["modification_reason"] = feedback.reason
                if feedback.source_evidence:
                    block["source_evidence"] = feedback.source_evidence
                break

    @staticmethod
    def _apply_delete(slide_ir: Dict[str, Any], feedback: ElementFeedback) -> None:
        """Delete element from slide IR."""
        blocks = slide_ir.get("blocks", [])
        slide_ir["blocks"] = [
            b for b in blocks if b.get("block_id") != feedback.element_id
        ]
