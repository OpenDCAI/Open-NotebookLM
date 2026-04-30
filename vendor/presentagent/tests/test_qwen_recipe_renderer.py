from pathlib import Path

from pptx import Presentation
from PIL import Image

from src.coder.qwen_recipe_audit import audit_pptx
from src.coder.qwen_recipe_renderer import QwenRecipeRenderer
from src.coder.qwen_recipe_schema import build_default_recipe


def _deck_ir():
    return {
        "title": "Deck",
        "theme": {
            "background_color": "#F7F4EE",
            "primary_color": "#134E8E",
            "accent_color": "#FFB33F",
            "text_color": "#1F2937",
            "font_family": "Aptos",
        },
    }


def _slide_ir():
    return {
        "slide_id": "slide_05",
        "type": "content",
        "title": "疗愈文化普及与认知升级",
        "core_message": "自我关怀应从额外享受升维为应得权利。",
        "layout": {"name": "two_column"},
        "blocks": [
            {"kind": "summary", "content": "自我关怀应从「额外享受」升维为「应得权利」。"},
            {
                "kind": "bullet_list",
                "items": [
                    "提供冥想/正念工具 -> 可及性支持",
                    "打破优绩枷锁 -> 认知重构",
                    "建立常态化机制 -> 范式转变",
                ],
            },
        ],
        "visuals": [{"description": "Upward arrow for cognitive upgrade"}],
    }


def test_qwen_recipe_renderer_creates_pptx_from_default_recipe(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "slide.pptx"

    recipe = build_default_recipe(_slide_ir())
    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    assert output_path.exists()
    prs = Presentation(str(output_path))
    assert len(prs.slides) == 1
    assert len(prs.slides[0].shapes) >= 4


def test_qwen_recipe_renderer_writes_recipe_artifacts(tmp_path):
    renderer = QwenRecipeRenderer()
    artifact_dir = tmp_path / "recipe"

    recipe = build_default_recipe(_slide_ir())
    pptx_path = renderer.render_single_slide(
        _deck_ir(),
        _slide_ir(),
        {},
        recipe,
        output_path=str(tmp_path / "single.pptx"),
        artifact_dir=str(artifact_dir),
    )

    assert Path(pptx_path).exists()
    assert (artifact_dir / "slide_05.recipe.json").exists()


def test_qwen_recipe_renderer_handles_expanded_safe_variants(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "expanded.pptx"
    slide_ir = _slide_ir()
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "process_flow"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.06, 0.04, 0.88, 0.14]},
            {"id": "body", "role": "content", "rect": [0.06, 0.22, 0.42, 0.58]},
            {"id": "visual", "role": "visual", "rect": [0.54, 0.22, 0.4, 0.58]},
            {"id": "footer", "role": "footer", "rect": [0.06, 0.88, 0.88, 0.06]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "kicker"},
            {"type": "block", "region": "footer", "source": "blocks[0].content", "variant": "evidence_footer"},
        ],
        "compositions": [
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "captioned_visual"},
            {"type": "quote", "region": "body", "source": "slide.core_message", "variant": "quote_wall"},
        ],
        "primitives": [{"type": "arrow", "region": "body"}],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    assert len(prs.slides) == 1
    assert len(prs.slides[0].shapes) >= 5


def test_qwen_recipe_renderer_handles_library_growth_variants(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "growth.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = ["Reach: 72", "Trust: 64", "Action: 51"]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [
            {"id": "body", "role": "content", "rect": [0.06, 0.2, 0.42, 0.62]},
            {"id": "visual", "role": "visual", "rect": [0.54, 0.2, 0.4, 0.62]},
            {"id": "lower", "role": "content", "rect": [0.06, 0.84, 0.88, 0.1]},
        ],
        "elements": [{"type": "block", "region": "lower", "source": "slide.core_message", "variant": "takeaway"}],
        "compositions": [
            {"type": "table", "region": "body", "source": "points", "variant": "table_matrix"},
            {"type": "chart", "region": "visual", "source": "points", "variant": "chart_takeaway"},
            {"type": "callouts", "region": "body", "source": "points", "variant": "callout_stack"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    assert len(prs.slides) == 1
    assert len(prs.slides[0].shapes) >= 6


def test_qwen_recipe_renderer_stacks_multiple_items_in_one_region(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "stacked.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "title_region", "role": "header", "rect": [0.05, 0.05, 0.9, 0.18]}],
        "elements": [
            {"type": "text", "region": "title_region", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "title_region", "source": "slide.core_message", "variant": "subtitle"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    text_shapes = [
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
        and shape.text_frame.text in {_slide_ir()["title"], _slide_ir()["core_message"]}
    ]
    tops = sorted(shape.top for shape in text_shapes)
    assert len(tops) == 2
    assert tops[1] > tops[0]


def test_qwen_recipe_renderer_uses_text_from_dict_items(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "dict_items.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"][1]["items"] = [
        {"item_id": "i1", "text": "第一条"},
        {"item_id": "i2", "text": "第二条"},
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.62]}],
        "elements": [{"type": "block", "region": "body", "source": "blocks[1].items", "variant": "compact_bullets"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "第一条" in rendered_text
    assert "item_id" not in rendered_text


def test_qwen_recipe_renderer_allocates_more_height_to_dense_bullets(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "dense_bullets.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"][1]["items"] = [
        {"item_id": f"i{index}", "text": f"需要展开说明的关键点 {index}"}
        for index in range(1, 7)
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.62]}],
        "elements": [
            {"type": "block", "region": "body", "source": "blocks[0].content", "variant": "summary_panel"},
            {"type": "block", "region": "body", "source": "blocks[1].items", "variant": "compact_bullets"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    summary_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
        and "额外享受" in shape.text_frame.text
        and "关键点" not in shape.text_frame.text
    )
    bullet_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "关键点" in shape.text_frame.text
    )
    assert bullet_shape.height > summary_shape.height * 1.8


def test_qwen_recipe_renderer_keeps_dense_bullet_font_readable(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "readable_dense_bullets.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"][1]["items"] = [
        {"item_id": f"i{index}", "text": f"需要展开说明的关键点 {index}"}
        for index in range(1, 7)
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.62]}],
        "elements": [{"type": "block", "region": "body", "source": "blocks[1].items", "variant": "compact_bullets"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    bullet_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "关键点" in shape.text_frame.text
    )
    font_sizes = [paragraph.font.size.pt for paragraph in bullet_shape.text_frame.paragraphs]
    assert min(font_sizes) >= 13


def test_qwen_recipe_renderer_expands_long_headline_before_font_shrinking(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "fit_headline.pptx"
    slide_ir = _slide_ir()
    slide_ir["title"] = "这是一个非常长的研究型页面标题，用来验证安全渲染器会主动降低字号避免文本溢出"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.08]},
            {"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.5]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    title_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "非常长" in shape.text_frame.text
    )
    assert 28 <= title_shape.text_frame.paragraphs[0].font.size.pt <= 34


def test_qwen_recipe_renderer_uses_stronger_default_typography_hierarchy(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "typography_hierarchy.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.16]},
            {"id": "body", "role": "content", "rect": [0.06, 0.24, 0.88, 0.58]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    title_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and _slide_ir()["title"] in shape.text_frame.text
    )
    body_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and _slide_ir()["core_message"] in shape.text_frame.text
    )
    assert title_shape.text_frame.paragraphs[0].font.size.pt >= 32
    assert body_shape.text_frame.paragraphs[0].font.size.pt >= 17


def test_qwen_recipe_renderer_expands_long_text_before_shrinking_type(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "text_capacity_typography.pptx"
    slide_ir = _slide_ir()
    slide_ir["title"] = "这是一个较长的研究型页面标题，用来验证安全渲染器会优先给标题增加可用高度而不是直接把字号压小"
    slide_ir["blocks"] = [
        {
            "kind": "summary",
            "content": (
                "这段正文需要保持可读字号，同时包含足够多的信息来触发容量估算。"
                "harness 应该先扩展或重排文本区域，再由渲染器做小幅字号适配。"
            )
            * 3,
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.07]},
            {"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.16]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "body", "source": "blocks[0].content", "variant": "summary_panel"},
        ],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    title_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "较长的研究型页面标题" in shape.text_frame.text
    )
    body_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "触发容量估算" in shape.text_frame.text
    )
    assert title_shape.text_frame.paragraphs[0].font.size.pt >= 28
    assert body_shape.text_frame.paragraphs[0].font.size.pt >= 15
    assert title_shape.height > int(0.07 * renderer.slide_height * 914400)
    assert body_shape.height > int(0.16 * renderer.slide_height * 914400)


def test_qwen_recipe_renderer_evidence_cards_use_readable_type_scale(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "evidence_type_scale.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = ["判断: 自我关怀从奖励转为权利", "依据: 工具普及降低实践门槛"]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "evidence", "role": "content", "rect": [0.05, 0.22, 0.9, 0.48]}],
        "elements": [],
        "compositions": [{"type": "evidence", "region": "evidence", "source": "points", "variant": "evidence_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    label_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip() == "判断"
    )
    body_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "自我关怀" in shape.text_frame.text
    )
    assert label_shape.text_frame.paragraphs[0].font.size.pt >= 13
    assert body_shape.text_frame.paragraphs[0].font.size.pt >= 13


def test_qwen_recipe_renderer_uses_readable_footer_type_for_qwen_theme(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "footer_type_scale.pptx"
    slide_ir = _slide_ir()
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "footer", "role": "footer", "rect": [0.06, 0.86, 0.88, 0.08]}],
        "elements": [{"type": "block", "region": "footer", "source": "blocks[0].content", "variant": "evidence_footer"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    footer_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "额外享受" in shape.text_frame.text
    )
    assert footer_shape.text_frame.paragraphs[0].font.size.pt >= 11


def test_qwen_recipe_renderer_handles_advanced_safe_variants(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "advanced.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = ["Before: 额外享受", "Bridge: 文化普及", "After: 应得权利", "Loop: 常态机制"]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "process_flow"},
        "regions": [
            {"id": "top", "role": "content", "rect": [0.06, 0.16, 0.88, 0.28]},
            {"id": "middle", "role": "content", "rect": [0.06, 0.48, 0.88, 0.2]},
            {"id": "bottom", "role": "content", "rect": [0.06, 0.72, 0.88, 0.2]},
        ],
        "elements": [
            {"type": "block", "region": "bottom", "source": "slide.core_message", "variant": "insight_panel"}
        ],
        "compositions": [
            {"type": "ladder", "region": "top", "source": "points", "variant": "statement_ladder"},
            {"type": "bridge", "region": "middle", "source": "points", "variant": "before_after_bridge"},
            {"type": "cards", "region": "bottom", "source": "points", "variant": "numbered_cards"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "额外享受" in rendered_text
    assert "应得权利" in rendered_text
    assert len(prs.slides[0].shapes) >= 10


def test_qwen_recipe_renderer_handles_structure_safe_variants(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "structure_variants.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = ["认知误区: 额外享受", "关键机制: 文化普及", "行动路径: 正念工具", "目标状态: 应得权利"]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "process_flow"},
        "regions": [
            {"id": "framework", "role": "content", "rect": [0.05, 0.12, 0.42, 0.36]},
            {"id": "cycle", "role": "content", "rect": [0.53, 0.12, 0.42, 0.36]},
            {"id": "bottom", "role": "content", "rect": [0.05, 0.54, 0.9, 0.32]},
        ],
        "elements": [],
        "compositions": [
            {"type": "framework", "region": "framework", "source": "points", "variant": "framework_grid"},
            {"type": "cycle", "region": "cycle", "source": "points", "variant": "cycle_loop"},
            {"type": "problem_solution", "region": "bottom", "source": "points", "variant": "problem_solution"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "认知误区" in rendered_text
    assert "应得权利" in rendered_text
    assert len(prs.slides[0].shapes) >= 14


def test_qwen_recipe_renderer_handles_more_structure_safe_variants(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "more_structure_variants.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = ["阶段一: 可及性", "阶段二: 认知重构", "阶段三: 常态机制", "证据: 来源段落支撑"]
    slide_ir["visuals"] = [
        {"intent": "展示升级前状态", "caption": "升级前"},
        {"intent": "展示升级后状态", "caption": "升级后"},
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [
            {"id": "top", "role": "content", "rect": [0.05, 0.1, 0.28, 0.38]},
            {"id": "middle", "role": "content", "rect": [0.36, 0.1, 0.28, 0.38]},
            {"id": "right", "role": "visual", "rect": [0.67, 0.1, 0.28, 0.38]},
            {"id": "bottom", "role": "content", "rect": [0.05, 0.55, 0.9, 0.32]},
        ],
        "elements": [],
        "compositions": [
            {"type": "pyramid", "region": "top", "source": "points", "variant": "pyramid"},
            {"type": "funnel", "region": "middle", "source": "points", "variant": "funnel"},
            {"type": "visual", "region": "right", "source": "visuals[0]", "variant": "visual_compare"},
            {"type": "evidence", "region": "bottom", "source": "points", "variant": "evidence_cards"},
            {"type": "columns", "region": "bottom", "source": "blocks[1].items", "variant": "dense_text_columns"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "阶段一" in rendered_text
    assert "升级前" in rendered_text
    assert "正念工具" in rendered_text
    assert "来源段落支撑" in rendered_text
    assert "Evidence 1" not in rendered_text
    assert len(prs.slides[0].shapes) >= 16


def test_qwen_recipe_renderer_renders_visual_asset_when_model_pairs_visual_source_with_process_variant(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "visual_source_process_variant.pptx"
    image_path = tmp_path / "generated_flow.png"
    Image.new("RGB", (320, 180), color=(30, 90, 160)).save(image_path)
    slide_ir = _slide_ir()
    slide_ir["visuals"] = [
        {
            "slot_id": "supporting_visual",
            "use_request_id": "req_01",
            "selected_candidate": {"path": str(image_path), "asset_id": "paper2any:req_01"},
            "caption": "生成的流程图",
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [
            {"id": "body", "role": "content", "rect": [0.05, 0.2, 0.42, 0.65]},
            {"id": "right_visual", "role": "visual", "rect": [0.5, 0.2, 0.45, 0.65]},
        ],
        "elements": [{"type": "block", "region": "body", "source": "blocks[1].items", "variant": "compact_bullets"}],
        "compositions": [
            {"type": "process_diagram", "region": "right_visual", "source": "visuals[0]", "variant": "process_diagram"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    assert any(shape.shape_type == 13 for shape in prs.slides[0].shapes)


def test_qwen_recipe_renderer_does_not_render_material_prompt_as_visual_caption(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "material_prompt_not_caption.pptx"
    image_path = tmp_path / "generated_hero.png"
    Image.new("RGB", (320, 180), color=(30, 90, 160)).save(image_path)
    slide_ir = _slide_ir()
    material_prompt = "展示一个抽象化的 AI 助手形象与农业场景结合的概念图，体现智能问答与气候适应的主题。"
    slide_ir["visuals"] = [
        {
            "slot_id": "hero_visual",
            "use_request_id": "req_01_hero",
            "selected_candidate": {"path": str(image_path), "asset_id": "paper2any:req_01_hero"},
            "caption": material_prompt,
            "intent": material_prompt,
            "description": material_prompt,
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [
            {"id": "body", "role": "content", "rect": [0.06, 0.2, 0.4, 0.52]},
            {"id": "hero_visual", "role": "visual", "rect": [0.52, 0.2, 0.42, 0.52]},
        ],
        "elements": [{"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"}],
        "compositions": [
            {"type": "visual", "region": "hero_visual", "source": "visuals[0]", "variant": "image_caption_overlay"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert material_prompt not in rendered_text


def test_qwen_recipe_renderer_renders_short_display_caption_overlay(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "short_display_caption.pptx"
    image_path = tmp_path / "generated_arch.png"
    Image.new("RGB", (320, 180), color=(30, 90, 160)).save(image_path)
    slide_ir = _slide_ir()
    slide_ir["visuals"] = [
        {
            "slot_id": "hero_visual",
            "selected_candidate": {"path": str(image_path), "asset_id": "paper2any:req_04"},
            "display_caption": "系统架构图",
            "description": "用于生成面向农业气候问答系统架构的复杂示意图。",
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [
            {"id": "body", "role": "content", "rect": [0.06, 0.2, 0.4, 0.52]},
            {"id": "hero_visual", "role": "visual", "rect": [0.52, 0.2, 0.42, 0.52]},
        ],
        "elements": [{"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"}],
        "compositions": [
            {"type": "visual", "region": "hero_visual", "source": "visuals[0]", "variant": "image_caption_overlay"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "系统架构图" in rendered_text
    assert "复杂示意图" not in rendered_text


def test_qwen_recipe_renderer_preserves_rendered_visual_aspect_ratio(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "aspect_safe_visual.pptx"
    image_path = tmp_path / "wide_visual.png"
    Image.new("RGB", (1600, 900), color=(20, 90, 120)).save(image_path)
    slide_ir = _slide_ir()
    slide_ir["visuals"] = [
        {
            "slot_id": "hero_visual",
            "selected_candidate": {"path": str(image_path), "asset_id": "paper2any:req"},
            "display_caption": "",
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [{"id": "hero_visual", "role": "visual", "rect": [0.05, 0.42, 0.9, 0.16]}],
        "elements": [],
        "compositions": [
            {"type": "visual", "region": "hero_visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    picture = next(shape for shape in prs.slides[0].shapes if shape.shape_type == 13)
    aspect = picture.width / picture.height
    assert abs(aspect - (1600 / 900)) < 0.03


def test_qwen_recipe_renderer_gives_rendered_visual_readable_display_area(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "visual_area_safe.pptx"
    image_path = tmp_path / "wide_visual.png"
    Image.new("RGB", (1600, 900), color=(20, 90, 120)).save(image_path)
    slide_ir = _slide_ir()
    slide_ir["visuals"] = [
        {
            "slot_id": "hero_visual",
            "selected_candidate": {"path": str(image_path), "asset_id": "paper2any:req"},
            "display_caption": "",
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "visual_focus"},
        "regions": [{"id": "hero_visual", "role": "visual", "rect": [0.05, 0.42, 0.9, 0.16]}],
        "elements": [],
        "compositions": [
            {"type": "visual", "region": "hero_visual", "source": "visuals[0]", "variant": "rendered_visual"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    picture = next(shape for shape in prs.slides[0].shapes if shape.shape_type == 13)
    area = (picture.width / 914400) * (picture.height / 914400)
    assert area >= 3.4


def test_qwen_recipe_renderer_truncates_dense_callout_stack_to_fit_boxes(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "callout_stack_capacity.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {
            "items": [
                "Trajectory-conditioned QA retrieval pipeline conditioned on SSP emission trajectories and user constraints",
                "Multi-source agentic fusion orchestrated across CMIP data, peer-reviewed literature, and advisory records",
                "Transparent privacy-safe design with scientific accountability enforced via self-evaluation",
                "Formal assessment roadmap for broader expert reception in a dedicated empirical study",
            ]
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "callouts", "role": "content", "rect": [0.52, 0.26, 0.42, 0.16]}],
        "elements": [],
        "compositions": [
            {"type": "callout_stack", "region": "callouts", "source": "blocks[0].items", "variant": "callout_stack"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    audit = audit_pptx(output_path)
    assert audit["text_box_overflows"] == []


def test_qwen_recipe_renderer_skips_metrics_strip_when_region_is_too_short(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "tiny_metrics_strip.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [{"items": ["三项核心指标以视觉突出方式并排展示: 建立系统信心基线"]}]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "metrics", "role": "metrics_band", "rect": [0.52, 0.18, 0.42, 0.14]}],
        "elements": [],
        "compositions": [{"type": "metrics_strip", "region": "metrics", "source": "blocks[0]", "variant": "metrics_strip"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    assert audit_pptx(output_path)["text_box_overflows"] == []


def test_qwen_recipe_renderer_skips_chart_takeaway_text_when_region_is_too_short(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "tiny_chart_takeaway.pptx"
    slide_ir = _slide_ir()
    slide_ir["core_message"] = "50位气候领域专家评估显示整体正向反馈占64%，负面反馈集中于三类。"
    slide_ir["blocks"] = [{"items": ["农业实践: 41", "措辞生硬: 52", "答案偏泛: 14"]}]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "chart", "role": "body", "rect": [0.52, 0.55, 0.42, 0.14]}],
        "elements": [],
        "compositions": [{"type": "chart", "region": "chart", "source": "blocks[0]", "variant": "chart_takeaway"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    assert audit_pptx(output_path)["text_box_overflows"] == []


def test_qwen_recipe_renderer_fits_dense_insight_panel_in_small_region(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "small_insight_panel.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {
            "content": "系统专为澳大利亚农业设计；跨国扩展需国际专家参与评估，规模与气候差异显著增加验证难度"
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "insight", "role": "body", "rect": [0.06, 0.37, 0.42, 0.08]}],
        "elements": [{"type": "block", "region": "insight", "source": "blocks[0]", "variant": "insight_panel"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    assert audit_pptx(output_path)["text_box_overflows"] == []


def test_qwen_recipe_renderer_fits_insight_panel_after_visual_side_panel_repack(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "visual_side_panel_insight.pptx"
    slide_ir = _slide_ir()
    slide_ir["title"] = "技术基础与未来路线：从当前系统到持续演进"
    slide_ir["core_message"] = "MYCC 构建于成熟技术栈之上，沿五条路线持续迭代。"
    slide_ir["blocks"] = [
        {},
        {"items": ["Agentic RAG", "Stella 1.5B v5", "Claude Sonnet 3.5", "Elasticsearch 混合索引"]},
        {"items": ["开源模型监督微调", "REAL 实体链接增强", "CMIP 气候投影集成", "自评估机制验证"]},
        {"content": "系统专为澳大利亚农业设计；跨国扩展需国际专家参与评估，规模与气候差异显著增加验证难度"},
    ]
    slide_ir["visuals"] = [{"selected_candidate": {"path": "missing-roadmap.png"}}]
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
        ],
        "elements": [
            {"type": "text", "region": "r_title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "r_limitations", "source": "blocks[3]", "variant": "insight_panel"},
            {"type": "text", "region": "r_takeaway", "source": "slide.core_message", "variant": "takeaway"},
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

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    assert audit_pptx(output_path)["text_box_overflows"] == []


def test_qwen_recipe_renderer_skips_tiny_footer_takeaway_instead_of_overflowing(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "tiny_footer_takeaway.pptx"
    slide_ir = _slide_ir()
    slide_ir["core_message"] = (
        "MYCC establishes that trajectory-conditioned multi-source agentic QA is both necessary "
        "and achievable for expert-grade climate advisory with broader empirical validation pending."
    )
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "footer", "role": "footer", "rect": [0.06, 0.9, 0.88, 0.045]}],
        "elements": [{"type": "text", "region": "footer", "source": "slide.core_message", "variant": "takeaway"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    audit = audit_pptx(output_path)
    assert audit["text_box_overflows"] == []
    visible_text = [
        shape.text_frame.text.strip()
        for shape in Presentation(str(output_path)).slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
    ]
    assert visible_text == []


def test_qwen_recipe_renderer_process_diagram_uses_readable_vertical_fallback(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "process_capacity.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {
            "items": [
                "Step 1 — Expert reviews agent response in production UI",
                "Step 2 — Labels sentiment: positive / neutral / negative",
                "Step 3 — Optionally edits response text to provide gold reference",
                "Step 4 — Labels plus edits feed RLHF reward model training",
                "Step 5 — Curated edits used for supervised fine-tuning",
            ]
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "process", "role": "content", "rect": [0.52, 0.48, 0.42, 0.18]}],
        "elements": [],
        "compositions": [
            {"type": "process_diagram", "region": "process", "source": "blocks[0].items", "variant": "process_diagram"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    audit = audit_pptx(output_path)
    assert audit["text_box_overflows"] == []


def test_qwen_recipe_renderer_truncates_numbered_card_body_to_fit(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "numbered_cards_capacity.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = [
        "Backend LLM library core inference and tool dispatch with production-grade session routing",
        "Middleware API server routing and session management around expert-facing climate advisory workflows",
        "Frontend web native app user interface designed for traceable farm advisor interactions",
        "89 My Climate View API endpoints each wrapped as a callable tool for the agent",
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "cards", "role": "content", "rect": [0.06, 0.26, 0.42, 0.18]}],
        "elements": [],
        "compositions": [{"type": "cards", "region": "cards", "source": "points", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    audit = audit_pptx(output_path)
    assert audit["text_box_overflows"] == []


def test_qwen_recipe_renderer_truncates_dense_columns_to_fit(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "dense_columns_capacity.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {
            "items": [
                "Transparency and provenance confirmed by independent expert review with traceable source display",
                "Self-evaluation module impact pending empirical study with broader domain coverage",
                "Entity-linking roadmap closes provenance gaps between text references and source records",
                "Fine-tuning feedback data aligns open-source models with expert expectations",
            ]
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "dense", "role": "content", "rect": [0.06, 0.42, 0.42, 0.16]}],
        "elements": [],
        "compositions": [
            {"type": "dense_text_columns", "region": "dense", "source": "blocks[0].items", "variant": "dense_text_columns"}
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    audit = audit_pptx(output_path)
    assert audit["text_box_overflows"] == []


def test_qwen_recipe_renderer_truncates_compact_bullets_to_fit(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "compact_bullets_capacity.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {
            "items": [
                "Upgrade 1 — Location disambiguation tool maps place names to coordinates for regional specificity",
                "Upgrade 2 — Response tightening reduces verbosity while preserving traceability and scientific caveats",
                "Upgrade 3 — Evaluation routing separates answer quality checks from self-evaluation threshold studies",
            ]
        }
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column", "density": "dense"},
        "regions": [{"id": "bullets", "role": "content", "rect": [0.06, 0.42, 0.42, 0.18]}],
        "elements": [{"type": "block", "region": "bullets", "source": "blocks[0].items", "variant": "compact_bullets"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    from src.coder.qwen_recipe_audit import audit_pptx

    audit = audit_pptx(output_path)
    assert audit["text_box_overflows"] == []


def test_qwen_recipe_renderer_evidence_cards_preserve_four_ir_items_without_template_labels(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "evidence_four_items.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = [
        "判断: 自我关怀从奖励转为权利",
        "依据: 工具普及降低实践门槛",
        "依据: 文化讨论减少羞耻感",
        "依据: 常态机制支撑长期行动",
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "evidence", "role": "content", "rect": [0.05, 0.2, 0.9, 0.55]}],
        "elements": [],
        "compositions": [{"type": "evidence", "region": "evidence", "source": "points", "variant": "evidence_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "常态机制支撑长期行动" in rendered_text
    assert "Evidence 1" not in rendered_text


def test_qwen_recipe_renderer_keeps_number_badges_small_but_body_readable(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "numbered_cards_readable.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = [
        "第一项需要保留足够字号并完整说明核心论点",
        "第二项需要保留足够字号并完整说明证据来源",
        "第三项需要保留足够字号并完整说明系统能力",
        "第四项需要保留足够字号并完整说明用户收益",
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.42, 0.88, 0.22]}],
        "elements": [],
        "compositions": [{"type": "cards", "region": "body", "source": "points", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    badge_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip() == "1"
    )
    body_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "核心论点" in shape.text_frame.text
    )

    assert badge_shape.text_frame.paragraphs[0].font.size.pt == 10
    assert body_shape.text_frame.paragraphs[0].font.size.pt >= 13


def test_qwen_recipe_renderer_maps_unsafe_font_family_to_safe_cjk_sans(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "safe_font_family.pptx"
    deck_ir = _deck_ir()
    deck_ir["theme"]["font_family"] = "Comic Sans MS"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.24, 0.88, 0.5]}],
        "elements": [{"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **deck_ir}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    body_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and _slide_ir()["core_message"] in shape.text_frame.text
    )
    assert body_shape.text_frame.paragraphs[0].font.name == "Noto Sans CJK SC"


def test_qwen_recipe_renderer_maps_default_aptos_to_cjk_sans_for_chinese_text(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "default_cjk_font_family.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "title", "role": "title", "rect": [0.06, 0.08, 0.88, 0.16]}],
        "elements": [{"type": "text", "region": "title", "source": "slide.title", "variant": "headline"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    title_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and _slide_ir()["title"] in shape.text_frame.text
    )
    assert title_shape.text_frame.paragraphs[0].font.name == "Noto Sans CJK SC"


def test_qwen_recipe_renderer_uses_safe_cjk_font_for_section_banner(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "section_banner_cjk_font.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "section", "role": "content", "rect": [0.06, 0.24, 0.5, 0.12]}],
        "elements": [{"type": "text", "region": "section", "source": "slide.core_message", "variant": "section_label"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    banner_text = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and "自我关怀" in shape.text_frame.text
    )
    assert banner_text.text_frame.paragraphs[0].font.name == "Noto Sans CJK SC"


def test_qwen_recipe_renderer_uses_model_planned_palette_with_safety_tokens(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "planned_palette.pptx"
    slide_ir = _slide_ir()
    slide_ir["points"] = [
        "情绪去道德化",
        "自我客体化",
        "自我朋友化",
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {
            "kind": "title_body",
            "density": "dense",
            "style": {"tone": "warm academic", "temperature": "warm"},
            "palette": {
                "background_color": "#FAF8F5",
                "primary_color": "#1E4D7B",
                "secondary_color": "#C75D4A",
                "accent_color": "#E8A845",
                "text_color": "#2C3E50",
                "surface_fill": "#F5F0ED",
                "surface_alt_fill": "#F8F5F0",
                "border_color": "#1E4D7B",
                "strong_band_fill": "#2C3E50",
            },
        },
        "regions": [
            {"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.32]},
            {"id": "footer", "role": "content", "rect": [0.06, 0.72, 0.88, 0.14]},
        ],
        "elements": [{"type": "text", "region": "footer", "source": "slide.core_message", "variant": "takeaway"}],
        "compositions": [{"type": "cards", "region": "body", "source": "points", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    slide = prs.slides[0]
    fill_colors = []
    line_colors = []
    text_colors = []
    for shape in slide.shapes:
        try:
            if shape.fill.fore_color.rgb:
                fill_colors.append(str(shape.fill.fore_color.rgb))
        except Exception:
            pass
        try:
            if shape.line.color.rgb:
                line_colors.append(str(shape.line.color.rgb))
        except Exception:
            pass
        if getattr(shape, "has_text_frame", False):
            for paragraph in shape.text_frame.paragraphs:
                try:
                    if paragraph.font.color.rgb:
                        text_colors.append(str(paragraph.font.color.rgb))
                except Exception:
                    pass

    assert str(slide.background.fill.fore_color.rgb) == "FAF8F5"
    assert "F5F0ED" in fill_colors
    assert "1E4D7B" in line_colors
    assert "2C3E50" in text_colors


def test_qwen_recipe_renderer_projects_low_contrast_text_color_without_fixed_palette(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "projected_palette.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {
            "kind": "title_body",
            "palette": {
                "background_color": "#F8F8F8",
                "text_color": "#F4F4F4",
                "primary_color": "#6A4C93",
                "accent_color": "#D97A3A",
                "surface_fill": "#FFFFFF",
            },
        },
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.2, 0.88, 0.32]}],
        "elements": [{"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    slide = prs.slides[0]
    body_shape = next(
        shape
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False) and _slide_ir()["core_message"] in shape.text_frame.text
    )
    body_color = str(body_shape.text_frame.paragraphs[0].font.color.rgb)

    assert str(slide.background.fill.fore_color.rgb) == "F8F8F8"
    assert body_color != "F4F4F4"
    assert body_color != "1F2937"


def test_qwen_recipe_renderer_skips_primitives_with_unknown_regions(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "unknown_primitives.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.12]},
            {"id": "body", "role": "content", "rect": [0.06, 0.24, 0.88, 0.5]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"},
        ],
        "compositions": [],
        "primitives": [
            {"type": "divider", "region": ""},
            {"type": "accent_bar", "region": "missing"},
        ],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    assert len(prs.slides[0].shapes) == 2


def test_qwen_recipe_renderer_places_divider_outside_title_text_box(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "safe_divider.pptx"
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.05, 0.05, 0.9, 0.12]},
            {"id": "body", "role": "content", "rect": [0.06, 0.24, 0.88, 0.5]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "text", "region": "body", "source": "slide.core_message", "variant": "summary_panel"},
        ],
        "compositions": [],
        "primitives": [{"type": "divider", "region": "title"}],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [_slide_ir()], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    title_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and _slide_ir()["title"] in shape.text_frame.text
    )
    divider_shape = next(
        shape
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and not shape.text_frame.text.strip()
    )
    assert divider_shape.top >= title_shape.top + title_shape.height


def test_qwen_recipe_renderer_does_not_emit_empty_numbered_card_bodies(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "no_empty_numbered_cards.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {},
        {
            "items": [
                "Agentic RAG",
                "Stella 1.5B v5",
                "Claude Sonnet 3.5",
                "Elasticsearch 混合索引",
            ]
        },
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "tech", "role": "content", "rect": [0.06, 0.19, 0.42, 0.0958]}],
        "elements": [],
        "compositions": [{"type": "cards", "region": "tech", "source": "blocks[1].items", "variant": "numbered_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    empty_body_shapes = []
    rendered_text = []
    for shape in prs.slides[0].shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        text = shape.text_frame.text.strip()
        rendered_text.append(text)
        sizes = []
        for paragraph in shape.text_frame.paragraphs:
            if paragraph.font.size:
                sizes.append(paragraph.font.size.pt)
            for run in paragraph.runs:
                if run.font.size:
                    sizes.append(run.font.size.pt)
        if not text and any(size >= 13 for size in sizes):
            empty_body_shapes.append(shape)

    assert not empty_body_shapes
    assert any("Agentic" in text or "Stella" in text or "Claude" in text for text in rendered_text)
    assert all("..." not in text for text in rendered_text if text not in {"1", "2", "3", "4"})


def test_qwen_recipe_renderer_wraps_process_diagram_before_tiny_ellipsis(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "process_without_tiny_ellipsis.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {},
        {},
        {
            "items": [
                "开源模型监督微调",
                "REAL 实体链接增强",
                "CMIP 气候投影集成",
                "自评估机制验证",
                "上下文窗口扩展",
            ]
        },
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [{"id": "roadmap", "role": "content", "rect": [0.06, 0.34, 0.42, 0.145]}],
        "elements": [],
        "compositions": [{"type": "process", "region": "roadmap", "source": "blocks[2].items", "variant": "process_diagram"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = [
        shape.text_frame.text.strip()
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
    ]
    process_labels = [text for text in rendered_text if text not in {_slide_ir()["title"], _slide_ir()["core_message"]}]

    assert process_labels
    assert all(not text.endswith("...") for text in process_labels)


def test_qwen_recipe_renderer_prefers_smaller_font_over_unnecessary_ellipsis():
    renderer = QwenRecipeRenderer()
    text = "MYCC 构建于成熟技术栈之上，沿五条路线持续迭代，将海量气候文献转化为可追溯的专家级问答"

    fitted, font_size = renderer._fit_text_to_box(
        text,
        width=5.17,
        height=0.8,
        preferred_font_size=16,
        min_font_size=13,
        margin=0.04,
    )

    assert fitted == text
    assert font_size <= 16


def test_qwen_recipe_renderer_uses_compact_labels_for_narrow_numbered_cards(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "compact_numbered_cards.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {},
        {
            "items": [
                "Agentic RAG",
                "Stella 1.5B v5",
                "Claude Sonnet 3.5",
                "Elasticsearch 混合索引",
            ]
        },
        {"items": ["开源模型监督微调", "REAL 实体链接增强"]},
        {"content": "系统专为澳大利亚农业设计；跨国扩展需国际专家参与评估。"},
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "two_column"},
        "regions": [
            {"id": "title", "role": "title", "rect": [0.03, 0.02, 0.94, 0.13]},
            {"id": "tech", "role": "body_left", "rect": [0.06, 0.19, 0.42, 0.14]},
            {"id": "roadmap", "role": "body_right", "rect": [0.52, 0.19, 0.42, 0.14]},
            {"id": "limitations", "role": "body_left_lower", "rect": [0.06, 0.37, 0.42, 0.14]},
            {"id": "visual", "role": "body_right_lower", "rect": [0.52, 0.37, 0.42, 0.14]},
            {"id": "takeaway", "role": "takeaway", "rect": [0.06, 0.55, 0.42, 0.14]},
            {"id": "footer", "role": "evidence", "rect": [0.06, 0.9, 0.88, 0.045]},
        ],
        "elements": [
            {"type": "text", "region": "title", "source": "slide.title", "variant": "headline"},
            {"type": "block", "region": "limitations", "source": "blocks[3]", "variant": "insight_panel"},
            {"type": "block", "region": "takeaway", "source": "slide.core_message", "variant": "takeaway"},
        ],
        "compositions": [
            {"type": "cards", "region": "tech", "source": "blocks[1].items", "variant": "numbered_cards"},
            {"type": "process", "region": "roadmap", "source": "blocks[2].items", "variant": "process_diagram"},
            {"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "captioned_visual"},
        ],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = [
        shape.text_frame.text.strip()
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
    ]

    assert "Agentic RAG" in rendered_text
    assert "Elasticsearch 混合索引" in rendered_text
    assert all("..." not in text for text in rendered_text)


def test_qwen_recipe_renderer_resolves_block_items_for_structural_compositions():
    renderer = QwenRecipeRenderer()
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {},
        {
            "content": "三项核心指标以视觉突出方式并排展示，建立系统信心基线",
            "items": [
                "整体正向反馈率: 64%",
                "正负标签中正向占比: 82%",
                "问答对总量: 2180",
            ],
        },
    ]

    assert renderer._resolve_items(slide_ir, "blocks[1]") == [
        "整体正向反馈率: 64%",
        "正负标签中正向占比: 82%",
        "问答对总量: 2180",
    ]


def test_qwen_recipe_renderer_chart_takeaway_uses_source_block_summary(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "chart_takeaway_block_summary.pptx"
    slide_ir = _slide_ir()
    slide_ir["core_message"] = (
        "50位气候领域专家评估显示整体正向反馈占64%。Sonnet 3.5综合最优。"
        "负面反馈集中于三类。已落地改进。2180条问答对分析显示农业实践类问题占比最高。"
    )
    slide_ir["blocks"] = [
        {},
        {},
        {},
        {
            "content": "负面反馈按类别量化分解，定位改进优先级",
            "items": [
                "措辞与呈现问题: 52",
                "地域相关性不足: 15",
                "引用格式问题: 11",
            ],
        },
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "chart_focus"},
        "regions": [{"id": "chart", "role": "content", "rect": [0.52, 0.6867, 0.42, 0.2133]}],
        "elements": [],
        "compositions": [{"type": "chart", "region": "chart", "source": "blocks[3]", "variant": "chart_takeaway"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "负面反馈按类别量化分解" in rendered_text
    assert "2180条问答对" not in rendered_text
    assert audit_pptx(output_path)["text_box_overflows"] == []


def test_qwen_recipe_renderer_metrics_strip_extracts_values_and_drops_color_hints(tmp_path):
    renderer = QwenRecipeRenderer()
    output_path = tmp_path / "metrics_strip_values.pptx"
    slide_ir = _slide_ir()
    slide_ir["blocks"] = [
        {},
        {
            "items": [
                "整体正向反馈率 64% 全部标签中 #134E8E",
                "正负标签中正向占比 82% 排除中性标签后 #134E8E",
            ],
        },
    ]
    recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "metric_focus"},
        "regions": [{"id": "metrics", "role": "content", "rect": [0.08, 0.24, 0.84, 0.24]}],
        "elements": [],
        "compositions": [{"type": "metrics", "region": "metrics", "source": "blocks[1]", "variant": "metrics_strip"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    renderer.render_deck({"slides": [slide_ir], **_deck_ir()}, {}, [recipe], str(output_path))

    prs = Presentation(str(output_path))
    rendered_text = "\n".join(
        shape.text_frame.text
        for shape in prs.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "64%" in rendered_text
    assert "82%" in rendered_text
    assert "#134E8E" not in rendered_text
    assert "整体正向反馈率 64% 全部标签中" not in rendered_text


def test_qwen_recipe_renderer_parses_pipe_table_rows_without_duplicate_cells():
    renderer = QwenRecipeRenderer()
    rows = renderer._items_to_table_rows(
        [
            "维度 | ClimSight | MYCC（My Climate CoPilot）",
            "地点支持 | 单地点 | 多地点",
            "对话轮次 | 单轮 | 多轮",
        ]
    )

    assert rows == [
        ["维度", "ClimSight", "MYCC（My Climate CoPilot）"],
        ["地点支持", "单地点", "多地点"],
        ["对话轮次", "单轮", "多轮"],
    ]
