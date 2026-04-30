from src.coder import pptx_library as lib


SLIDE_WIDTH = 13.33
SLIDE_HEIGHT = 7.5


def _rect_overlap(a, b) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    overlap_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    overlap_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    return overlap_w * overlap_h


def test_key_layout_slots_stay_within_slide_bounds():
    for layout_name in ["section_divider", "two_column", "comparison", "metric_focus", "chart_focus"]:
        slide_ir = {"layout": {"name": layout_name}}
        slots = lib.resolve_layout_slots(slide_ir, slide_width=SLIDE_WIDTH, slide_height=SLIDE_HEIGHT)
        assert slots, layout_name
        for slot_id, (left, top, width, height) in slots.items():
            assert left >= 0, (layout_name, slot_id)
            assert top >= 0, (layout_name, slot_id)
            assert width > 0, (layout_name, slot_id)
            assert height > 0, (layout_name, slot_id)
            assert left + width <= SLIDE_WIDTH + 1e-6, (layout_name, slot_id)
            assert top + height <= SLIDE_HEIGHT + 1e-6, (layout_name, slot_id)


def test_key_layout_primary_slots_do_not_overlap():
    cases = {
        "section_divider": [("title", "body")],
        "two_column": [("title", "body"), ("body", "supporting_visual"), ("supporting_visual", "callout")],
        "comparison": [("title", "body"), ("body", "callout")],
        "metric_focus": [("title", "metrics"), ("metrics", "body")],
        "chart_focus": [("title", "supporting_visual"), ("supporting_visual", "body")],
    }
    for layout_name, pairs in cases.items():
        slide_ir = {"layout": {"name": layout_name}}
        slots = lib.resolve_layout_slots(slide_ir, slide_width=SLIDE_WIDTH, slide_height=SLIDE_HEIGHT)
        for left_slot, right_slot in pairs:
            assert _rect_overlap(slots[left_slot], slots[right_slot]) == 0.0, (layout_name, left_slot, right_slot)


def test_render_slide_scaffold_handles_key_layouts_without_crashing():
    deck_ir = {
        "theme": {
            "background_color": "#F7F4EE",
            "primary_color": "#134E8E",
            "accent_color": "#C00707",
            "text_color": "#1F2937",
            "font_family": "Aptos",
        }
    }
    materials = {"asset_index": {}}
    slide_specs = [
        {
            "title": "Section",
            "layout": {"name": "section_divider"},
            "blocks": [{"kind": "summary", "slot_id": "body", "content": "Divider summary", "items": []}],
            "visuals": [],
        },
        {
            "title": "Compare",
            "layout": {"name": "comparison"},
            "blocks": [{"kind": "comparison", "slot_id": "body", "items": ["A: Better speed", "B: Better quality"]}],
            "visuals": [],
        },
        {
            "title": "Metrics",
            "layout": {"name": "metric_focus"},
            "blocks": [
                {"kind": "metric_strip", "slot_id": "metrics", "items": ["Acc: 92%", "F1: 0.88"]},
                {"kind": "summary", "slot_id": "body", "content": "Metrics improve after refinement", "items": []},
            ],
            "visuals": [],
        },
        {
            "title": "Chart",
            "layout": {"name": "chart_focus"},
            "blocks": [{"kind": "summary", "slot_id": "body", "content": "Chart takeaway", "items": []}],
            "visuals": [{"slot_id": "supporting_visual", "asset_role": "supporting_visual", "intent": "chart"}],
        },
    ]

    for slide_ir in slide_specs:
        prs = lib.create_presentation()
        slide = lib.render_slide_scaffold(prs, deck_ir, slide_ir, materials)
        assert slide is not None
        assert len(slide.shapes) >= 1
