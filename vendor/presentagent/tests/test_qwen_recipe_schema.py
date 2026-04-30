import json

from src.coder.qwen_recipe_schema import (
    apply_recipe_harness,
    build_default_recipe,
    parse_qwen_recipe_response,
    validate_recipe,
)


def test_parse_qwen_recipe_response_wraps_layout_body_fragment():
    raw = """
      "layout": {"type": "two_column", "density": "spacious"},
      "regions": [{"id": "left", "role": "content", "rect": [0.06, 0.22, 0.42, 0.58]}],
      "elements": [{"type": "summary_panel", "region": "left", "source": "blocks[0].content", "variant": "summary_panel"}],
      "compositions": [],
      "primitives": [],
      "emphasis": [],
      "constraints": {"no_new_claims": true}
    }
    """

    recipe = parse_qwen_recipe_response(raw, slide_ir={"slide_id": "slide_05"})

    assert recipe["version"] == "qwen_recipe_v1"
    assert recipe["layout"]["kind"] == "two_column"
    assert recipe["regions"][0]["rect"] == [0.06, 0.22, 0.42, 0.58]


def test_parse_qwen_recipe_response_wraps_layout_value_fragment():
    raw = """
    {
      "kind": "two_column"
    },
    "regions": [{"id": "body", "role": "content", "rect": [0.08, 0.2, 0.5, 0.6]}],
    "elements": [{"type": "summary_panel", "region": "body", "source": "blocks[0].content", "variant": "summary_panel"}],
    "compositions": [{"region": "body", "source": "points", "variant": "concept_diagram"}],
    "primitives": [{"type": "divider", "placement": "between_columns"}],
    "emphasis": {"primary_focus": "body"},
    "constraints": {"no_new_claims": true}
    }
    """

    recipe = parse_qwen_recipe_response(
        raw,
        slide_ir={"slide_id": "slide_05", "type": "content", "blocks": [{"content": "A"}]},
    )

    assert recipe["layout"]["kind"] == "two_column"
    assert recipe["regions"][0]["id"] == "body"
    assert recipe["elements"][0]["source"] == "blocks[0].content"
    assert recipe["compositions"][0]["variant"] == "concept_diagram"
    assert recipe["primitives"] == [{"type": "divider", "region": "", "style": "primary"}]


def test_parse_qwen_recipe_response_accepts_regions_nested_under_layout():
    raw = """
    {
      "layout": {
        "kind": "two_column",
        "regions": [
          {"id": "body_region", "role": "primary_content", "rect": [0.05, 0.2, 0.45, 0.75]},
          {"id": "visual_region", "role": "supporting_visual", "rect": [0.55, 0.2, 0.4, 0.75]}
        ]
      },
      "elements": [{"type": "summary_panel", "region": "body_region", "source": "blocks[0].content", "variant": "summary_panel"}],
      "compositions": [{"region": "visual_region", "source": "visuals[0]", "variant": "concept_diagram"}],
      "primitives": [],
      "emphasis": [],
      "constraints": {"no_new_claims": true}
    }
    """

    recipe = parse_qwen_recipe_response(
        raw,
        slide_ir={"type": "content", "blocks": [{"content": "A"}], "visuals": [{}]},
    )

    assert [region["id"] for region in recipe["regions"]] == ["body_region", "visual_region"]
    assert recipe["elements"][0]["region"] == "body_region"


def test_parse_qwen_recipe_response_normalizes_aliases_and_filters_payload():
    raw = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"type": "two_column", "split_ratio": 0.6},
            "regions": [{"id": "title_region", "rect": [0.05, 0.05, 1.5, 0.12]}],
            "elements": [
                {
                    "id": "el_title",
                    "variant": "headline",
                    "source": "slide.title",
                    "rect": [0.05, 0.05, 0.9, 0.12],
                    "text": "model copied title",
                    "style": {"font_size": "large"},
                }
            ],
            "compositions": [],
            "primitives": [{"type": "background", "color": "#FFFFFF"}],
            "emphasis": [{"element_id": "el_title", "level": "primary", "method": "font_weight"}],
            "constraints": {"no_new_claims": True},
        },
        ensure_ascii=False,
    )

    recipe = parse_qwen_recipe_response(raw, slide_ir={"slide_id": "slide_05"})

    assert recipe["layout"]["kind"] == "two_column"
    assert recipe["regions"][0]["rect"] == [0.05, 0.05, 0.95, 0.12]
    assert recipe["elements"][0] == {
        "type": "text",
        "region": "title_region",
        "source": "slide.title",
        "variant": "headline",
    }
    assert recipe["primitives"] == []
    assert recipe["emphasis"] == [{"target": "el_title", "style": "primary_font_weight"}]


def test_validate_recipe_rejects_missing_body_content_for_content_slide():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "title", "role": "title", "rect": [0.06, 0.04, 0.88, 0.14]}],
        "elements": [{"type": "text", "region": "title", "source": "slide.title", "variant": "headline"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    errors = validate_recipe(recipe, slide_ir={"type": "content"})

    assert any("body content" in error for error in errors)


def test_build_default_recipe_uses_ir_slots_and_blocks():
    slide_ir = {
        "slide_id": "slide_05",
        "type": "content",
        "title": "Title",
        "layout": {
            "name": "two_column",
            "slots": [
                {"slot_id": "title", "x_ratio": 0.06, "y_ratio": 0.04, "w_ratio": 0.88, "h_ratio": 0.14},
                {"slot_id": "body", "x_ratio": 0.06, "y_ratio": 0.22, "w_ratio": 0.42, "h_ratio": 0.58},
                {"slot_id": "supporting_visual", "x_ratio": 0.54, "y_ratio": 0.22, "w_ratio": 0.4, "h_ratio": 0.58},
            ],
        },
        "blocks": [{"kind": "summary", "content": "A"}, {"kind": "bullet_list", "items": ["B"]}],
        "visuals": [{"slot_id": "supporting_visual"}],
    }

    recipe = build_default_recipe(slide_ir)

    assert recipe["layout"]["kind"] == "two_column"
    assert [region["id"] for region in recipe["regions"]] == ["title", "body", "supporting_visual"]
    assert recipe["elements"][1]["source"] == "blocks[0]"
    assert recipe["elements"][2]["source"] == "blocks[1]"
    assert recipe["compositions"][0]["source"] == "visuals[0]"


def test_apply_recipe_harness_repacks_overlapping_regions():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.06, 0.04, 0.88, 0.14]},
            {"id": "body", "role": "content", "rect": [0.08, 0.22, 0.55, 0.6]},
            {"id": "visual", "role": "visual", "rect": [0.12, 0.26, 0.55, 0.58]},
        ],
        "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
        "compositions": [{"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "image_or_placeholder"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(recipe, slide_ir={"type": "content"})
    body = next(region for region in adjusted["regions"] if region["id"] == "body")["rect"]
    visual = next(region for region in adjusted["regions"] if region["id"] == "visual")["rect"]

    assert body[0] + body[2] <= visual[0] or visual[0] + visual[2] <= body[0]
    assert adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_expands_tiny_structural_composition_regions():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "header", "role": "header", "rect": [0.06, 0.2, 0.88, 0.24]},
            {"id": "evidence", "role": "body", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "header", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "evidence", "source": "points", "variant": "evidence_footer"},
        ],
        "compositions": [
            {"type": "evidence_cards", "region": "evidence", "source": "points", "variant": "evidence_cards"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(recipe, slide_ir={"type": "content", "points": ["Claim", "Evidence"]})
    evidence = next(region for region in adjusted["regions"] if region["id"] == "evidence")["rect"]

    assert evidence[3] >= 0.24
    assert evidence[1] + evidence[3] <= 0.98
    assert "min_region_size:evidence" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_expands_tiny_typography_regions_before_font_shrinking():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.06]},
            {"id": "body", "role": "content", "rect": [0.06, 0.18, 0.88, 0.24]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "body", "source": "blocks[0].items", "variant": "compact_bullets"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={"type": "content", "blocks": [{"items": ["A", "B", "C", "D", "E", "F"]}]},
    )
    title = next(region for region in adjusted["regions"] if region["id"] == "title")["rect"]
    body = next(region for region in adjusted["regions"] if region["id"] == "body")["rect"]

    assert title[3] >= 0.12
    assert body[3] >= 0.34
    assert "min_region_size:title" in adjusted["constraints"]["harness_adjustments"]
    assert "min_region_size:body" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_expands_text_regions_by_estimated_capacity():
    long_title = "这是一个较长的研究型页面标题，用来验证安全渲染器会优先给标题增加可用高度而不是直接把字号压小"
    dense_items = [
        "需要展开说明的关键点包含较长中文句子，用来触发确定性的文本容量估算"
        for _ in range(8)
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.07]},
            {"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.26]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "body", "source": "blocks[0].items", "variant": "compact_bullets"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": long_title,
            "blocks": [{"kind": "bullet_list", "items": dense_items}],
        },
    )
    title = next(region for region in adjusted["regions"] if region["id"] == "title")["rect"]
    body = next(region for region in adjusted["regions"] if region["id"] == "body")["rect"]

    assert title[3] >= 0.18
    assert body[3] >= 0.42
    assert "text_capacity:title" in adjusted["constraints"]["harness_adjustments"]
    assert "text_capacity:body" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_infers_visual_compare_composition_from_intent_region():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [
            {"id": "header", "role": "header", "rect": [0.05, 0.05, 0.9, 0.15]},
            {"id": "visual_compare_region", "role": "visual_compare", "rect": [0.05, 0.22, 0.9, 0.55]},
        ],
        "elements": [{"type": "text", "region": "header", "source": "slide.title", "variant": "headline"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={"type": "content", "visuals": [{"caption": "Before"}, {"caption": "After"}]},
    )

    assert adjusted["compositions"] == [
        {
            "type": "visual_compare",
            "region": "visual_compare_region",
            "source": "visuals[0]",
            "variant": "visual_compare",
        }
    ]
    assert "inferred_visual_compare:visual_compare_region" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_coerces_visual_source_to_renderable_visual_variant():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [
            {"id": "body", "role": "content", "rect": [0.05, 0.2, 0.42, 0.65]},
            {"id": "right_visual", "role": "visual", "rect": [0.5, 0.2, 0.45, 0.65]},
        ],
        "elements": [{"type": "block", "region": "body", "source": "blocks[0].items", "variant": "compact_bullets"}],
        "compositions": [
            {"type": "process_diagram", "region": "right_visual", "source": "visuals[0]", "variant": "process_diagram"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={"type": "content", "blocks": [{"items": ["A"]}], "visuals": [{"use_request_id": "req_01"}]},
    )

    composition = adjusted["compositions"][0]
    assert composition["source"] == "visuals[0]"
    assert composition["variant"] == "rendered_visual"
    assert composition["type"] == "visual"
    assert "visual_source_variant:right_visual" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_adds_missing_visual_composition_when_slide_has_visuals():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [
            {"id": "body", "role": "content", "rect": [0.05, 0.2, 0.42, 0.65]},
            {"id": "right_visual", "role": "visual", "rect": [0.5, 0.2, 0.45, 0.65]},
        ],
        "elements": [{"type": "block", "region": "body", "source": "blocks[0].items", "variant": "compact_bullets"}],
        "compositions": [{"type": "cards", "region": "body", "source": "points", "variant": "dense_text_columns"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={"type": "content", "blocks": [{"items": ["A"]}], "visuals": [{"use_request_id": "req_01"}]},
    )

    assert any(
        item.get("source") == "visuals[0]" and item.get("variant") == "rendered_visual"
        for item in adjusted["compositions"]
    )
    assert "inferred_visual_render:right_visual" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_creates_visual_led_region_when_qwen_omits_planned_visual():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.16]},
            {"id": "left_top", "role": "body", "rect": [0.06, 0.22, 0.42, 0.22]},
            {"id": "right_top", "role": "body", "rect": [0.52, 0.22, 0.42, 0.22]},
            {"id": "left_bottom", "role": "body", "rect": [0.06, 0.48, 0.42, 0.22]},
            {"id": "right_bottom", "role": "body", "rect": [0.52, 0.48, 0.42, 0.22]},
            {"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "left_top", "source": "blocks[0].items", "variant": "compact_bullets"},
            {"type": "block", "region": "right_top", "source": "blocks[1].items", "variant": "compact_bullets"},
            {"type": "block", "region": "left_bottom", "source": "blocks[2].items", "variant": "compact_bullets"},
            {"type": "block", "region": "right_bottom", "source": "blocks[3].items", "variant": "compact_bullets"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "Visual-led slide",
            "blocks": [{"items": ["A", "B"]} for _ in range(4)],
            "visuals": [{"selected_candidate": {"path": "diagram.png"}}],
        },
    )

    visual_items = [
        item for item in adjusted["compositions"]
        if item.get("source") == "visuals[0]" and item.get("variant") == "rendered_visual"
    ]
    assert len(visual_items) == 1
    visual_region = next(region for region in adjusted["regions"] if region["id"] == visual_items[0]["region"])
    assert visual_region["role"] == "visual"
    assert visual_region["rect"][2] * visual_region["rect"][3] >= 0.16
    body_regions = [
        region for region in adjusted["regions"]
        if region["id"] != "title" and region["id"] != "footer" and region["id"] != visual_region["id"]
    ]
    assert len(body_regions) <= 3
    assert "inferred_visual_region:qwen_visual" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_drops_long_takeaway_from_footer_region():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]}],
        "elements": [
            {"type": "text", "region": "footer", "source": "slide.core_message", "variant": "takeaway"}
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "core_message": "这是一段明显超过页脚容量的长 takeaway 文本，应该被丢弃而不是挤在很矮的 footer 里造成溢出。",
        },
    )

    assert adjusted["elements"] == []
    assert "drop_footer_takeaway:footer" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_drops_long_evidence_footer_region():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]}],
        "elements": [
            {"type": "text", "region": "footer", "source": "slide.core_message", "variant": "evidence_footer"}
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "core_message": "这是一段明显超过页脚容量的证据说明，不能继续渲染在 0.045 高度的页脚区域里。",
        },
    )

    assert adjusted["elements"] == []
    assert "drop_footer_evidence_footer:footer" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_drops_table_matrix_from_tiny_footer_region():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "footer", "role": "evidence", "rect": [0.06, 0.9, 0.88, 0.045]}],
        "elements": [],
        "compositions": [
            {"type": "table", "region": "footer", "source": "blocks[0].items", "variant": "table_matrix"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "blocks": [
                {
                    "items": [
                        "Stella 1.5B v5：nDCG@10 = 0.769 ✦ 胜出",
                        "评估维度：MTEB 基准 + 专家人工判断（双轨）",
                    ]
                }
            ],
        },
    )

    assert adjusted["compositions"] == []
    assert "drop_footer_table_matrix:footer" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_drops_long_evidence_footer_before_repack_compresses_it():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.08]}],
        "elements": [
            {"type": "text", "region": "footer", "source": "slide.core_message", "variant": "evidence_footer"}
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "core_message": "50位气候领域专家评估显示整体正向反馈占64%，Sonnet 3.5综合最优，负面反馈集中于三类，后续还有多个工具改进方向。",
        },
    )

    assert adjusted["elements"] == []
    assert "drop_footer_evidence_footer:footer" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_does_not_treat_roadmap_text_region_as_visual_source_region():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.13]},
            {"id": "roadmap", "role": "body_right", "rect": [0.52, 0.19, 0.42, 0.14]},
            {"id": "visual", "role": "body_right_lower", "rect": [0.52, 0.37, 0.42, 0.14]},
            {"id": "left_a", "role": "body_left", "rect": [0.06, 0.19, 0.42, 0.14]},
            {"id": "left_b", "role": "body_left_lower", "rect": [0.06, 0.37, 0.42, 0.14]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "left_a", "source": "blocks[0].items", "variant": "compact_bullets"},
            {"type": "block", "region": "left_b", "source": "blocks[1].items", "variant": "compact_bullets"},
        ],
        "compositions": [
            {"type": "process", "region": "roadmap", "source": "blocks[2].items", "variant": "process_diagram"},
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "captioned_visual"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "Roadmap",
            "blocks": [{"items": ["A", "B"]} for _ in range(3)],
            "visuals": [{"selected_candidate": {"path": "roadmap.png"}}],
        },
    )

    regions = {region["id"]: region["rect"] for region in adjusted["regions"]}
    assert not _test_rects_overlap(regions["roadmap"], regions["visual"])


def test_apply_recipe_harness_promotes_existing_visual_source_region_to_readable_side_panel():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.13]},
            {"id": "tech_stack", "role": "body_left", "rect": [0.06, 0.19, 0.42, 0.14]},
            {"id": "roadmap", "role": "body_right", "rect": [0.52, 0.19, 0.42, 0.14]},
            {"id": "limitations", "role": "body_left_lower", "rect": [0.06, 0.37, 0.42, 0.14]},
            {"id": "visual_panel", "role": "body_right_lower", "rect": [0.52, 0.37, 0.42, 0.14]},
            {"id": "takeaway", "role": "takeaway", "rect": [0.06, 0.55, 0.42, 0.14]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "limitations", "source": "blocks[3]", "variant": "insight_panel"},
            {"type": "text", "region": "takeaway", "source": "slide.core_message", "variant": "takeaway"},
        ],
        "compositions": [
            {"type": "cards", "region": "tech_stack", "source": "blocks[1].items", "variant": "numbered_cards"},
            {"type": "process", "region": "roadmap", "source": "blocks[2].items", "variant": "process_diagram"},
            {"type": "visual", "region": "visual_panel", "source": "visuals[0]", "variant": "captioned_visual"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "Roadmap",
            "core_message": "Summary",
            "blocks": [{"items": ["A", "B"]} for _ in range(4)],
            "visuals": [{"selected_candidate": {"path": "roadmap.png"}}],
        },
    )

    visual = next(region for region in adjusted["regions"] if region["id"] == "visual_panel")
    assert visual["role"] == "visual"
    assert visual["rect"][2] * visual["rect"][3] >= 0.16
    assert "visual_prominence:visual_panel" in adjusted["constraints"]["harness_adjustments"]
    for region in adjusted["regions"]:
        if region["id"] != "visual_panel":
            assert not _test_rects_overlap(visual["rect"], region["rect"])


def test_parse_qwen_recipe_response_accepts_expanded_safe_variants():
    raw = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "process_flow"},
            "regions": [
                {"id": "title", "role": "title", "rect": [0.06, 0.04, 0.88, 0.14]},
                {"id": "body", "role": "content", "rect": [0.06, 0.22, 0.5, 0.6]},
                {"id": "visual", "role": "visual", "rect": [0.6, 0.22, 0.34, 0.6]},
                {"id": "footer", "role": "footer", "rect": [0.06, 0.88, 0.88, 0.06]},
            ],
            "elements": [
                {"type": "kicker", "region": "title", "source": "slide.subtitle", "variant": "kicker"},
                {"type": "evidence_footer", "region": "footer", "source": "blocks[0].content", "variant": "evidence_footer"},
            ],
            "compositions": [
                {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "captioned_visual"},
                {"type": "quote", "region": "body", "source": "slide.core_message", "variant": "quote_wall"},
            ],
            "primitives": [{"type": "arrow", "region": "body"}],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        },
        ensure_ascii=False,
    )

    recipe = parse_qwen_recipe_response(
        raw,
        slide_ir={"type": "content", "blocks": [{"content": "Evidence"}], "core_message": "Core"},
    )

    assert recipe["elements"][0]["variant"] == "kicker"
    assert recipe["elements"][1]["variant"] == "evidence_footer"
    assert recipe["compositions"][0]["variant"] == "captioned_visual"
    assert recipe["compositions"][1]["variant"] == "quote_wall"


def test_parse_qwen_recipe_response_accepts_library_growth_variants():
    raw = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "visual_focus"},
            "regions": [
                {"id": "body", "role": "content", "rect": [0.06, 0.2, 0.42, 0.62]},
                {"id": "visual", "role": "visual", "rect": [0.54, 0.2, 0.4, 0.62]},
            ],
            "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "takeaway"}],
            "compositions": [
                {"type": "table", "region": "body", "source": "points", "variant": "table_matrix"},
                {"type": "chart", "region": "visual", "source": "points", "variant": "chart_takeaway"},
                {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "visual_observations"},
                {"type": "callouts", "region": "body", "source": "points", "variant": "callout_stack"},
            ],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        },
        ensure_ascii=False,
    )

    recipe = parse_qwen_recipe_response(
        raw,
        slide_ir={"type": "content", "blocks": [{"content": "A"}], "points": ["A: 1", "B: 2"], "visuals": [{}]},
    )

    assert [item["variant"] for item in recipe["compositions"]] == [
        "table_matrix",
        "chart_takeaway",
        "visual_observations",
        "callout_stack",
    ]


def test_parse_qwen_recipe_response_accepts_advanced_safe_variants():
    raw = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "process_flow"},
            "regions": [
                {"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.62]},
            ],
            "elements": [
                {"type": "block", "region": "body", "source": "slide.core_message", "variant": "insight_panel"},
                {"type": "block", "region": "body", "source": "blocks[0].content", "variant": "definition_panel"},
            ],
            "compositions": [
                {"type": "ladder", "region": "body", "source": "points", "variant": "statement_ladder"},
                {"type": "bridge", "region": "body", "source": "points", "variant": "before_after_bridge"},
                {"type": "cards", "region": "body", "source": "points", "variant": "numbered_cards"},
                {"type": "map", "region": "body", "source": "points", "variant": "cluster_map"},
                {"type": "visual", "region": "body", "source": "visuals[0]", "variant": "image_caption_overlay"},
            ],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        },
        ensure_ascii=False,
    )

    recipe = parse_qwen_recipe_response(
        raw,
        slide_ir={
            "type": "content",
            "blocks": [{"content": "A"}],
            "points": ["Before: A", "After: B"],
            "visuals": [{}],
            "core_message": "Core",
        },
    )

    assert [item["variant"] for item in recipe["elements"]] == ["insight_panel", "definition_panel"]
    assert [item["variant"] for item in recipe["compositions"]] == [
        "statement_ladder",
        "before_after_bridge",
        "numbered_cards",
        "cluster_map",
        "image_caption_overlay",
    ]


def test_parse_qwen_recipe_response_accepts_structure_safe_variants():
    raw = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "process_flow"},
            "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.18, 0.88, 0.68]}],
            "elements": [{"type": "block", "region": "body", "source": "blocks[0].content", "variant": "summary_panel"}],
            "compositions": [
                {"type": "framework", "region": "body", "source": "points", "variant": "framework_grid"},
                {"type": "problem_solution", "region": "body", "source": "points", "variant": "problem_solution"},
                {"type": "cycle", "region": "body", "source": "points", "variant": "cycle_loop"},
                {"type": "pyramid", "region": "body", "source": "points", "variant": "pyramid"},
                {"type": "funnel", "region": "body", "source": "points", "variant": "funnel"},
                {"type": "evidence", "region": "body", "source": "points", "variant": "evidence_cards"},
                {"type": "columns", "region": "body", "source": "blocks[1].items", "variant": "dense_text_columns"},
                {"type": "visual", "region": "body", "source": "visuals[0]", "variant": "visual_compare"},
            ],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        },
        ensure_ascii=False,
    )

    recipe = parse_qwen_recipe_response(
        raw,
        slide_ir={
            "type": "content",
            "blocks": [{"content": "A"}, {"items": ["B", "C"]}],
            "points": ["A", "B", "C", "D"],
            "visuals": [{}, {}],
        },
    )

    assert [item["variant"] for item in recipe["compositions"]] == [
        "framework_grid",
        "problem_solution",
        "cycle_loop",
        "pyramid",
        "funnel",
        "evidence_cards",
        "dense_text_columns",
        "visual_compare",
    ]


def test_apply_recipe_harness_expands_numbered_cards_for_body_readability():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.52, 0.88, 0.16]}],
        "elements": [],
        "compositions": [{"type": "cards", "region": "body", "source": "points", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "points": [
                "第一项需要保留足够字号并完整说明核心论点",
                "第二项需要保留足够字号并完整说明证据来源",
                "第三项需要保留足够字号并完整说明系统能力",
                "第四项需要保留足够字号并完整说明用户收益",
            ],
        },
    )

    body = next(region for region in adjusted["regions"] if region["id"] == "body")["rect"]

    assert body[3] >= 0.3
    assert "text_capacity:body" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_removes_redundant_block_sources_in_same_region():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.6]}],
        "elements": [
            {"type": "text", "region": "body", "source": "blocks[1].content", "variant": "section_label"},
            {"type": "block", "region": "body", "source": "blocks[1].items", "variant": "compact_bullets"},
        ],
        "compositions": [{"type": "cards", "region": "body", "source": "blocks[1]", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={"type": "content", "blocks": [{}, {"content": "评估摘要", "items": ["64% 正面标签", "41% 措辞生硬"]}]},
    )

    rendered_sources = [item["source"] for item in adjusted["elements"] + adjusted["compositions"]]
    assert rendered_sources == ["blocks[1]"]
    assert "duplicate_source:blocks[1]" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_removes_redundant_visual_text_when_rendering_same_visual():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "visual", "role": "visual", "rect": [0.52, 0.28, 0.42, 0.24]}],
        "elements": [{"type": "block", "region": "visual", "source": "visuals[0]", "variant": "summary_panel"}],
        "compositions": [
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={"type": "content", "visuals": [{"caption": "Pipeline diagram"}]},
    )

    assert adjusted["elements"] == []
    assert [item["variant"] for item in adjusted["compositions"]] == ["rendered_visual"]
    assert "duplicate_source:visuals[0]" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_expands_rendered_visual_region_for_readable_area():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "visual", "role": "visual", "rect": [0.06, 0.62, 0.42, 0.14]}],
        "elements": [],
        "compositions": [
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(recipe, slide_ir={"type": "content", "visuals": [{"caption": "roadmap"}]})

    visual = next(region for region in adjusted["regions"] if region["id"] == "visual")["rect"]
    assert visual[2] * visual[3] >= 0.061
    assert any(
        adjustment in adjusted["constraints"]["harness_adjustments"]
        for adjustment in ("min_region_size:visual", "visual_prominence:visual")
    )


def test_apply_recipe_harness_preserves_visual_height_after_fallback_repack():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.2]},
            {"id": "a", "role": "body", "rect": [0.06, 0.25, 0.42, 0.2]},
            {"id": "b", "role": "body", "rect": [0.52, 0.25, 0.42, 0.2]},
            {"id": "c", "role": "body", "rect": [0.06, 0.49, 0.42, 0.2]},
            {"id": "d", "role": "body", "rect": [0.52, 0.49, 0.42, 0.2]},
            {"id": "visual", "role": "visual", "rect": [0.06, 0.72, 0.42, 0.14]},
            {"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "a", "source": "blocks[0].items", "variant": "compact_bullets"},
            {"type": "block", "region": "b", "source": "blocks[1].items", "variant": "compact_bullets"},
            {"type": "block", "region": "c", "source": "blocks[2].items", "variant": "compact_bullets"},
            {"type": "block", "region": "d", "source": "blocks[3].items", "variant": "compact_bullets"},
        ],
        "compositions": [
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "Dense slide",
            "blocks": [{"items": ["long item one", "long item two"]} for _ in range(4)],
            "visuals": [{"caption": "benchmark chart"}],
        },
    )

    visual = next(region for region in adjusted["regions"] if region["id"] == "visual")["rect"]
    assert visual[2] >= 0.42
    assert visual[3] >= 0.38
    assert visual[2] * visual[3] >= 0.16
    for region in adjusted["regions"]:
        if region["id"] != "visual":
            assert not _test_rects_overlap(visual, region["rect"])


def test_apply_recipe_harness_places_dense_visual_as_side_panel_not_bottom_band():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.2]},
            {"id": "a", "role": "body", "rect": [0.52, 0.25, 0.42, 0.16]},
            {"id": "b", "role": "body", "rect": [0.52, 0.44, 0.42, 0.16]},
            {"id": "c", "role": "body", "rect": [0.52, 0.63, 0.42, 0.16]},
            {"id": "visual", "role": "visual", "rect": [0.06, 0.55, 0.42, 0.14]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "a", "source": "blocks[0].items", "variant": "compact_bullets"},
            {"type": "block", "region": "b", "source": "blocks[1].items", "variant": "compact_bullets"},
            {"type": "block", "region": "c", "source": "blocks[2].items", "variant": "compact_bullets"},
        ],
        "compositions": [
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "Dense visual slide",
            "blocks": [{"items": ["A", "B"]} for _ in range(3)],
            "visuals": [{"caption": "architecture"}],
        },
    )

    visual = next(region for region in adjusted["regions"] if region["id"] == "visual")["rect"]
    assert visual[0] < 0.12
    assert visual[1] < 0.48
    assert visual[2] >= 0.42
    assert visual[3] >= 0.38

    for region in adjusted["regions"]:
        if region["id"] != "visual":
            assert not _test_rects_overlap(visual, region["rect"])


def test_apply_recipe_harness_drops_low_priority_regions_that_conflict_with_visual_band():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.2]},
            {"id": "main", "role": "body", "rect": [0.06, 0.25, 0.42, 0.24]},
            {"id": "notes", "role": "body", "rect": [0.52, 0.55, 0.42, 0.24]},
            {"id": "visual", "role": "visual", "rect": [0.06, 0.62, 0.42, 0.14]},
            {"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "main", "source": "blocks[0].items", "variant": "compact_bullets"},
            {"type": "block", "region": "notes", "source": "blocks[1].items", "variant": "compact_bullets"},
            {"type": "text", "region": "footer", "source": "slide.core_message", "variant": "takeaway"},
        ],
        "compositions": [
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "Dense slide",
            "core_message": "Footer summary",
            "blocks": [{"items": ["A", "B"]}, {"items": ["C", "D"]}],
            "visuals": [{"caption": "roadmap"}],
        },
    )

    visual = next(region for region in adjusted["regions"] if region["id"] == "visual")
    for region in adjusted["regions"]:
        if region["id"] != "visual":
            assert not _test_rects_overlap(visual["rect"], region["rect"])


def _test_rects_overlap(first, second, gap=0.012):
    ax, ay, aw, ah = [float(value) for value in first[:4]]
    bx, by, bw, bh = [float(value) for value in second[:4]]
    return not (
        ax + aw + gap <= bx
        or bx + bw + gap <= ax
        or ay + ah + gap <= by
        or by + bh + gap <= ay
    )



def test_apply_recipe_harness_stacks_title_and_subtitle_after_capacity_expansion():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "comparison"},
        "regions": [
            {"id": "r_title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.14]},
            {"id": "r_subtitle", "role": "subtitle", "rect": [0.03, 0.15, 0.94, 0.08]},
        ],
        "elements": [
            {"type": "text", "region": "r_title", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "r_subtitle", "source": "slide.subtitle", "variant": "subtitle"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "My Climate CoPilot: Tackling the Climate Information Crisis in Agriculture",
            "subtitle": "An Evidence-Grounded Agentic QA Platform for Farm Advisors",
        },
    )
    regions = {region["id"]: region["rect"] for region in adjusted["regions"]}

    assert regions["r_title"][1] + regions["r_title"][3] + 0.008 <= regions["r_subtitle"][1]
    assert "title_stack:r_subtitle" in adjusted["constraints"]["harness_adjustments"]


def test_apply_recipe_harness_preserves_title_stack_after_global_projection():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "comparison"},
        "regions": [
            {"id": "r_title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.14]},
            {"id": "r_subtitle", "role": "subtitle", "rect": [0.03, 0.15, 0.94, 0.08]},
            {"id": "r_problem", "role": "body_left", "rect": [0.06, 0.22, 0.42, 0.22]},
            {"id": "r_solution", "role": "body_right", "rect": [0.52, 0.22, 0.42, 0.22]},
            {"id": "r_visual", "role": "visual", "rect": [0.06, 0.46, 0.42, 0.22]},
            {"id": "r_takeaway", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "r_title", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "r_subtitle", "source": "slide.subtitle", "variant": "subtitle"},
            {"type": "block", "region": "r_problem", "source": "blocks[2]", "variant": "compact_bullets"},
            {"type": "block", "region": "r_takeaway", "source": "blocks[4]", "variant": "takeaway"},
        ],
        "compositions": [
            {"type": "numbered_cards", "region": "r_solution", "source": "blocks[3]", "variant": "numbered_cards"},
            {"type": "rendered_visual", "region": "r_visual", "source": "visuals[0]", "variant": "rendered_visual"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "content",
            "title": "My Climate CoPilot: Tackling the Climate Information Crisis in Agriculture",
            "subtitle": "An Evidence-Grounded Agentic QA Platform for Farm Advisors",
            "blocks": [
                {},
                {},
                {"items": ["Climate literature doubles", "New climate data generated", "Makes expert QA slow"]},
                {"items": ["MYCC addresses the crisis through five design pillars"]},
                {"content": "MYCC cuts through climate information overload"},
            ],
            "visuals": [{}],
        },
    )
    regions = {region["id"]: region["rect"] for region in adjusted["regions"]}

    assert regions["r_title"][1] + regions["r_title"][3] + 0.008 <= regions["r_subtitle"][1]


def test_apply_recipe_harness_converts_single_item_numbered_cards_to_takeaway():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.32]}],
        "elements": [],
        "compositions": [{"type": "cards", "region": "body", "source": "points", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(recipe, slide_ir={"type": "content", "points": ["唯一核心结论"]})

    assert adjusted["compositions"] == []
    assert adjusted["elements"] == [{"type": "text", "region": "body", "source": "points", "variant": "takeaway"}]
    assert "single_item_variant:numbered_cards" in adjusted["constraints"]["harness_adjustments"]


def test_parse_recipe_preserves_model_planned_palette_without_fixed_region_mapping():
    raw = {
        "version": "qwen_recipe_v1",
        "layout": {
            "kind": "title_body",
            "density": "dense",
            "style": {"tone": "warm technical", "surface": "soft panels"},
            "palette": {
                "background_color": "#FAF8F5",
                "primary_color": "#1E4D7B",
                "secondary_color": "#C75D4A",
                "accent_color": "#E8A845",
                "text_color": "#2C3E50",
                "surface_fill": "#F5F0ED",
                "border_color": "#1E4D7B",
                "unsafe": "red",
            },
        },
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.62]}],
        "elements": [{"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    recipe = parse_qwen_recipe_response(
        json.dumps(raw),
        slide_ir={"slide_id": "slide_01", "type": "content", "core_message": "Core"},
    )

    assert recipe["layout"]["style"]["tone"] == "warm technical"
    assert recipe["layout"]["palette"]["background_color"] == "#FAF8F5"
    assert recipe["layout"]["palette"]["surface_fill"] == "#F5F0ED"
    assert "unsafe" not in recipe["layout"]["palette"]


def test_apply_recipe_harness_visual_side_panel_keeps_text_column_readable():
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [
            {"id": "r_title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.13]},
            {"id": "r_tech_stack", "role": "body_left", "rect": [0.06, 0.19, 0.42, 0.14]},
            {"id": "r_roadmap", "role": "body_right", "rect": [0.52, 0.19, 0.42, 0.14]},
            {"id": "r_limitations", "role": "body_left_lower", "rect": [0.06, 0.37, 0.42, 0.14]},
            {"id": "r_visual", "role": "body_right_lower", "rect": [0.52, 0.37, 0.42, 0.14]},
            {"id": "r_takeaway", "role": "takeaway", "rect": [0.06, 0.55, 0.42, 0.14]},
            {"id": "r_footer", "role": "evidence", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "r_title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "r_limitations", "source": "blocks[3]", "variant": "insight_panel"},
            {"type": "block", "region": "r_takeaway", "source": "slide.core_message", "variant": "takeaway"},
        ],
        "compositions": [
            {"type": "cards", "region": "r_tech_stack", "source": "blocks[1].items", "variant": "numbered_cards"},
            {"type": "process", "region": "r_roadmap", "source": "blocks[2].items", "variant": "process_diagram"},
            {"type": "visual", "region": "r_visual", "source": "visuals[0]", "variant": "captioned_visual"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    adjusted = apply_recipe_harness(
        recipe,
        slide_ir={
            "type": "closing",
            "title": "技术基础与未来路线：从当前系统到持续演进",
            "core_message": "MYCC 构建于成熟技术栈之上，沿五条路线持续迭代。",
            "blocks": [
                {},
                {"items": ["Agentic RAG", "Stella 1.5B v5", "Claude Sonnet 3.5", "Elasticsearch 混合索引"]},
                {"items": ["开源模型监督微调", "REAL 实体链接增强", "CMIP 气候投影集成", "自评估机制验证", "上下文窗口扩展"]},
                {"content": "系统专为澳大利亚农业设计；跨国扩展需国际专家参与评估。"},
            ],
            "visuals": [{"selected_candidate": {"path": "roadmap.png"}}],
        },
    )

    regions = {region["id"]: region["rect"] for region in adjusted["regions"]}

    assert regions["r_visual"][2] * regions["r_visual"][3] >= 0.16
    assert min(
        regions[region_id][3]
        for region_id in ("r_tech_stack", "r_roadmap", "r_limitations", "r_takeaway")
    ) >= 0.14
