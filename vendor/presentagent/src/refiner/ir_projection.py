"""Task-conditioned IR projection for ReAct refinement.

View = f(IR, Task, History)
"""

from typing import Any, Dict, Optional


def project_vlm_view(
    deck_ir: Dict[str, Any],
    slide_ir: Dict[str, Any],
    history: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """VLM评估视图：判断"视觉呈现是否符合IR意图"

    Focus: 结构、视觉设计、信息表达、一致性

    Args:
        deck_ir: Full deck IR
        slide_ir: Full slide IR
        history: ReAct iteration history (None for round 0)
            {
                "iteration": int,
                "previous_feedback": list[dict]
            }

    Returns:
        Minimal view for VLM evaluation
    """
    history = history or {}

    vlm_deck = {
        "title": deck_ir.get("title", ""),
        "theme": {
            "name": deck_ir["theme"].get("name", ""),
            "primary_color": deck_ir["theme"].get("primary_color", ""),
            "secondary_color": deck_ir["theme"].get("secondary_color", ""),
            "background_color": deck_ir["theme"].get("background_color", ""),
            "text_color": deck_ir["theme"].get("text_color", ""),
            "density": deck_ir["theme"].get("density", ""),
            "style_guardrails": deck_ir["theme"].get("style_guardrails", [])
        } if deck_ir.get("theme") else {}
    }

    vlm_slide = {
        "slide_id": slide_ir.get("slide_id"),
        "title": slide_ir.get("title"),
        "core_message": slide_ir.get("core_message"),
        "source_evidence": [
            {"source_excerpt": ev.get("source_excerpt", "")[:150]}
            for ev in slide_ir.get("source_evidence", [])[:3]
        ],
        "layout": {
            "name": slide_ir["layout"].get("name", ""),
            "density": slide_ir["layout"].get("density", ""),
            "emphasis": slide_ir["layout"].get("emphasis", "")
        } if slide_ir.get("layout") else {},
        "blocks": [
            {
                "kind": b.get("kind"),
                "content": b.get("content", ""),
                "items": b.get("items", [])
            }
            for b in slide_ir.get("blocks", [])
        ],
        "visuals": [
            {
                "asset_role": v.get("asset_role"),
                "target_area": v.get("target_area", "")
            }
            for v in slide_ir.get("visuals", [])
        ]
    }

    result = {
        "deck": vlm_deck,
        "slide": vlm_slide
    }

    if history and history.get("previous_feedback"):
        result["history"] = {
            "iteration": history.get("iteration", 0),
            "previous_feedback": history["previous_feedback"]
        }

    return result


def project_editable_ir_view(slide_ir: Dict[str, Any]) -> Dict[str, Any]:
    """IR-Refiner可编辑视图：只包含可修改的字段

    Editable fields:
    - title, subtitle, core_message
    - layout (name, density, emphasis, slots)
    - blocks (kind, content, items, slot_id, emphasis)
    - visuals (slot_id, asset_role, target_area)
    - design_notes

    Read-only (excluded):
    - metadata, deck_id, slide_number, type, section_id
    - brief_id, source_chunk_ids, source_evidence
    - speaker_notes, selected_asset_path/id
    """
    return {
        "slide_id": slide_ir.get("slide_id"),
        "title": slide_ir.get("title"),
        "subtitle": slide_ir.get("subtitle", ""),
        "core_message": slide_ir.get("core_message"),
        "layout": slide_ir.get("layout"),
        "blocks": slide_ir.get("blocks", []),
        "visuals": slide_ir.get("visuals", []),
        "design_notes": slide_ir.get("design_notes", [])
    }


def merge_refined_ir_view(
    original_ir: Dict[str, Any],
    refined_view: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge refined view back to original IR, preserving read-only fields"""
    merged = dict(original_ir)

    # Update editable fields
    editable_fields = [
        "title", "subtitle", "core_message",
        "layout", "blocks", "visuals", "design_notes"
    ]

    for field in editable_fields:
        if field in refined_view:
            merged[field] = refined_view[field]

    return merged


def project_coder_view(
    deck_ir: Dict[str, Any],
    slide_ir: Dict[str, Any],
    materials: Dict[str, Any]
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Coder代码生成视图：生成python-pptx代码所需的完整信息

    Returns:
        (coder_deck, coder_slide, coder_materials)
    """
    # Deck view: title + theme
    coder_deck = {
        "title": deck_ir.get("title", ""),
        "theme": deck_ir.get("theme", {})
    }

    # Slide view: 完整布局和内容信息
    coder_slide = {
        "slide_id": slide_ir.get("slide_id"),
        "slide_number": slide_ir.get("slide_number"),
        "type": slide_ir.get("type"),
        "title": slide_ir.get("title"),
        "subtitle": slide_ir.get("subtitle", ""),
        "core_message": slide_ir.get("core_message"),
        "layout": slide_ir.get("layout"),
        "blocks": slide_ir.get("blocks", []),
        "points": slide_ir.get("points", []),
        "visuals": slide_ir.get("visuals", []),
        "design_notes": slide_ir.get("design_notes", []),
        "source_evidence": [
            {"source_excerpt": ev.get("source_excerpt", "")}
            for ev in slide_ir.get("source_evidence", [])
        ]
    }

    # Materials view: 仅当前slide使用的资产
    used_asset_ids = set()
    for visual in slide_ir.get("visuals", []):
        candidate = visual.get("selected_candidate")
        if candidate and candidate.get("asset_id"):
            used_asset_ids.add(candidate["asset_id"])

    asset_index = materials.get("asset_index", {})
    filtered_assets = {}
    for asset_id in used_asset_ids:
        if asset_id in asset_index:
            asset = asset_index[asset_id]
            filtered_assets[asset_id] = {
                "path": asset.get("path"),
                "description": asset.get("description", ""),
                "width_px": asset.get("width_px"),
                "height_px": asset.get("height_px"),
                "aspect_ratio": asset.get("aspect_ratio"),
                "orientation": asset.get("orientation", "")
            }

    coder_materials = {
        "asset_index": filtered_assets,
        "document_dir": materials.get("document_dir", "")
    }

    return coder_deck, coder_slide, coder_materials
