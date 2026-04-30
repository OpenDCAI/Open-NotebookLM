from src.coder import pptx_library as lib
from PIL import Image


def _make_image(path, size=(1600, 900)):
    Image.new("RGB", size, color=(30, 80, 120)).save(path)
    return path


def test_resolve_asset_path_prefers_slide_selected_asset_path():
    materials = {"asset_index": {}}
    slide_ir = {
        "selected_asset_path": "/tmp/direct.png",
        "visuals": [{"use_existing_asset_id": "asset_1"}],
    }

    result = lib.resolve_asset_path(materials, slide_ir)

    assert result == "/tmp/direct.png"


def test_resolve_asset_path_reads_asset_index_dict_path():
    materials = {"asset_index": {"asset_1": {"path": "/tmp/a.png"}}}
    slide_ir = {"visuals": [{"use_existing_asset_id": "asset_1"}]}

    assert lib.resolve_asset_path(materials, slide_ir) == "/tmp/a.png"


def test_normalize_asset_path_accepts_string_and_dict():
    assert lib._normalize_asset_path("/tmp/a.png") == "/tmp/a.png"
    assert lib._normalize_asset_path({"path": "/tmp/b.png"}) == "/tmp/b.png"


def test_fit_image_contain_preserves_aspect_in_wide_slot(tmp_path):
    image = _make_image(tmp_path / "wide.png", (1600, 900))

    left, top, width, height = lib.fit_image_rect(str(image), 1.0, 1.0, 10.0, 2.0, mode="contain")

    assert round(width / height, 3) == round(1600 / 900, 3)
    assert round(left, 2) == 4.22
    assert round(top, 2) == 1.0
    assert round(height, 2) == 2.0


def test_fit_image_contain_preserves_aspect_in_tall_slot(tmp_path):
    image = _make_image(tmp_path / "wide.png", (1600, 900))

    left, top, width, height = lib.fit_image_rect(str(image), 1.0, 1.0, 3.0, 5.0, mode="contain")

    assert round(width / height, 3) == round(1600 / 900, 3)
    assert round(left, 2) == 1.0
    assert round(top, 2) == 2.66
    assert round(width, 2) == 3.0


def test_safe_resolve_asset_path_returns_none_for_invalid_asset():
    materials = {"asset_index": {"asset_1": {"missing": "/tmp/a.png"}}}
    slide_ir = {"visuals": [{"use_existing_asset_id": "asset_1"}]}

    assert hasattr(lib, "safe_resolve_asset_path")
    assert lib.safe_resolve_asset_path(materials, slide_ir) is None


def test_safe_placeholder_panel_adds_fallback_shapes():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "safe_placeholder_panel")
    shape = lib.safe_placeholder_panel(slide, (1.0, 1.0, 3.0, 2.0), label="missing figure")

    assert shape is not None
    assert len(slide.shapes) >= 2


def test_add_shape_accepts_none_line_color():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    shape = lib.add_shape(
        slide,
        "RECTANGLE",
        left=0.5,
        top=0.5,
        width=1.0,
        height=0.5,
        fill_color="#134E8E",
        line_color=None,
    )

    assert shape is not None
    assert len(slide.shapes) == 1


def test_add_shape_accepts_none_fill_color():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    shape = lib.add_shape(
        slide,
        "OVAL",
        left=0.5,
        top=0.5,
        width=1.0,
        height=1.0,
        fill_color=None,
        line_color="#C00707",
    )

    assert shape is not None
    assert len(slide.shapes) == 1


def test_render_visual_in_slot_uses_placeholder_when_asset_missing():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    materials = {"asset_index": {"asset_1": {"path": "/tmp/not-found.png"}}}
    slide_ir = {"visuals": [{"use_existing_asset_id": "asset_1", "intent": "figure unavailable"}]}

    result = lib.render_visual_in_slot(
        slide,
        slide_ir,
        materials,
        slide_ir["visuals"][0],
        (1.0, 1.0, 3.0, 2.0),
        {"primary_color": "#134E8E", "text_color": "#1F2937"},
    )

    assert result is not None
    assert len(slide.shapes) >= 2


def test_render_visual_in_slot_accepts_none_visual_and_uses_placeholder():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    result = lib.render_visual_in_slot(
        slide,
        {"visuals": []},
        {"asset_index": {}},
        None,
        (1.0, 1.0, 3.0, 2.0),
        {"primary_color": "#134E8E", "text_color": "#1F2937"},
    )

    assert result is not None
    assert len(slide.shapes) >= 2


def test_add_takeaway_block_returns_shape():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "add_takeaway_block")
    shape = lib.add_takeaway_block(
        slide,
        "Key takeaway",
        (0.8, 5.8, 11.2, 0.8),
        {"primary_color": "#134E8E", "text_color": "#1F2937"},
    )

    assert shape is not None
    assert len(slide.shapes) >= 2


def test_add_metric_pair_block_handles_two_metrics():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "add_metric_pair_block")
    result = lib.add_metric_pair_block(
        slide,
        [{"label": "Acc", "value": "92%"}, {"label": "F1", "value": "0.88"}],
        (0.8, 1.5, 6.0, 1.6),
        {"accent_color": "#C00707", "text_color": "#1F2937"},
    )

    assert result is not None
    assert len(slide.shapes) >= 6


def test_add_visual_with_caption_block_falls_back_for_missing_image():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "add_visual_with_caption_block")
    result = lib.add_visual_with_caption_block(
        slide,
        "/tmp/not-found.png",
        "Figure caption",
        (0.8, 1.2, 5.5, 4.0),
        {"primary_color": "#134E8E", "text_color": "#1F2937"},
    )

    assert result is not None
    assert len(slide.shapes) >= 3


def test_add_evidence_footer_block_and_highlight_block_return_shapes():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "add_highlight_block")
    assert hasattr(lib, "add_evidence_footer_block")
    highlight = lib.add_highlight_block(
        slide,
        "Important result",
        (0.8, 1.0, 5.0, 1.0),
        {"accent_color": "#FFB33F", "text_color": "#1F2937"},
    )
    footer = lib.add_evidence_footer_block(
        slide,
        ["Dataset A", "Ablation B"],
        (0.8, 6.8, 11.5, 0.45),
        {"text_color": "#4B5563"},
    )

    assert highlight is not None
    assert footer is not None


def test_composite_blocks_return_shapes():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    theme = {"primary_color": "#134E8E", "accent_color": "#C00707", "text_color": "#1F2937"}

    assert hasattr(lib, "compose_visual_with_observations")
    assert hasattr(lib, "compose_metrics_with_summary")
    visual_result = lib.compose_visual_with_observations(
        slide,
        "/tmp/not-found.png",
        ["Observation one", "Observation two"],
        (0.8, 1.1, 7.0, 4.2),
        theme,
        caption="Missing visual",
    )
    metric_result = lib.compose_metrics_with_summary(
        slide,
        [{"label": "Acc", "value": "92%"}, {"label": "F1", "value": "0.88"}],
        "Metrics improve after refinement.",
        (8.0, 1.1, 4.5, 4.2),
        theme,
    )

    assert visual_result is not None
    assert metric_result is not None


def test_compose_chart_with_takeaway_uses_placeholder_chart_area():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "compose_chart_with_takeaway")
    result = lib.compose_chart_with_takeaway(
        slide,
        ["A", "B"],
        "Score",
        [0.7, 0.9],
        "B performs better.",
        (0.8, 1.0, 7.2, 4.4),
        {"primary_color": "#134E8E", "accent_color": "#C00707", "text_color": "#1F2937"},
    )

    assert result is not None


def test_render_title_body_scaffold_returns_slide_with_slots():
    prs = lib.create_presentation()

    assert hasattr(lib, "render_title_body_scaffold")
    slide = lib.render_title_body_scaffold(
        prs,
        {"theme": {"background_color": "#F7F4EE", "primary_color": "#134E8E", "font_family": "Aptos"}},
        {"title": "Title", "layout": {"name": "section_divider"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
    )

    assert slide is not None
    assert len(slide.shapes) >= 1


def test_render_title_body_visual_scaffold_returns_slide():
    prs = lib.create_presentation()

    assert hasattr(lib, "render_title_body_visual_scaffold")
    slide = lib.render_title_body_visual_scaffold(
        prs,
        {"theme": {"background_color": "#F7F4EE", "primary_color": "#134E8E", "font_family": "Aptos"}},
        {"title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
    )

    assert slide is not None
    assert len(slide.shapes) >= 1


def test_render_comparison_and_metric_scaffolds_return_slides():
    theme = {"theme": {"background_color": "#F7F4EE", "primary_color": "#134E8E", "accent_color": "#C00707"}}

    assert hasattr(lib, "render_comparison_scaffold")
    comparison = lib.render_comparison_scaffold(
        lib.create_presentation(),
        theme,
        {"title": "Compare", "layout": {"name": "comparison"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
    )

    assert hasattr(lib, "render_metric_focus_scaffold")
    metric = lib.render_metric_focus_scaffold(
        lib.create_presentation(),
        theme,
        {"title": "Metrics", "layout": {"name": "metric_focus"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
    )

    assert comparison is not None
    assert metric is not None


def test_render_chart_focus_scaffold_returns_slide():
    prs = lib.create_presentation()

    assert hasattr(lib, "render_chart_focus_scaffold")
    slide = lib.render_chart_focus_scaffold(
        prs,
        {"theme": {"background_color": "#F7F4EE", "primary_color": "#134E8E"}},
        {"title": "Chart", "layout": {"name": "chart_focus"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
    )

    assert slide is not None


def test_render_slide_scaffold_dispatches_named_scaffold():
    prs = lib.create_presentation()
    slide = lib.render_slide_scaffold(
        prs,
        {"theme": {"background_color": "#F7F4EE", "primary_color": "#134E8E"}},
        {
            "title": "Metrics",
            "layout": {"name": "metric_focus"},
            "blocks": [{"kind": "metric_strip", "items": ["Acc: 92%", "F1: 0.88"], "slot_id": "metrics"}],
            "visuals": [],
        },
        {"asset_index": {}},
    )

    assert slide is not None
    assert len(slide.shapes) >= 3


def test_append_takeaway_block_adds_takeaway_shape():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "append_takeaway_block")
    result = lib.append_takeaway_block(
        slide,
        "New takeaway",
        (0.8, 6.0, 11.0, 0.7),
        {"primary_color": "#134E8E"},
    )

    assert result is not None


def test_emphasize_takeaway_block_returns_shape():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    target = lib.add_takeaway_block(slide, "Important", (0.8, 5.8, 11.2, 0.8), {"primary_color": "#134E8E"})

    assert hasattr(lib, "emphasize_takeaway_block")
    result = lib.emphasize_takeaway_block(target, {"accent_color": "#C00707"})

    assert result is target


def test_replace_visual_block_returns_new_visual_shape():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)

    assert hasattr(lib, "replace_visual_block")
    result = lib.replace_visual_block(
        slide,
        "/tmp/not-found.png",
        (1.0, 1.0, 4.5, 3.0),
        {"primary_color": "#134E8E", "text_color": "#1F2937"},
        caption="Replaced visual",
    )

    assert result is not None


def test_tighten_text_spacing_returns_shape():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    box = slide.shapes.add_textbox(0, 0, 1000000, 1000000)
    box.text_frame.text = "Line 1\nLine 2"

    assert hasattr(lib, "tighten_text_spacing")
    result = lib.tighten_text_spacing(box, level="compact")

    assert result is box


def test_rebalance_visual_text_ratio_returns_summary_of_shapes():
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    text_box = lib.add_textbox(slide, "Summary", 0.8, 1.0, 4.0, 1.0)
    visual = lib.safe_placeholder_panel(slide, (5.2, 1.0, 4.5, 3.0), label="visual")

    assert hasattr(lib, "rebalance_visual_text_ratio")
    result = lib.rebalance_visual_text_ratio(text_box, visual, ratio="visual_heavy")

    assert result is not None
