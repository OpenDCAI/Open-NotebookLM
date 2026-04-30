from src.coder.pptx_coder import PPTXCoder


class DummyClient:
    model_profile = "general"

    def chat(self, messages, temperature=0.2, max_tokens=None):
        return "def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None"


class QwenDummyClient(DummyClient):
    model_profile = "qwen"


def test_library_prompt_mentions_scaffold_and_helper_priority():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
    )

    assert "scaffold" in prompt.lower()
    assert "helper" in prompt.lower()


def test_library_import_block_includes_prompted_scaffolds():
    imports = PPTXCoder._build_import_block("library")

    assert "render_title_body_visual_scaffold" in imports
    assert "render_comparison_scaffold" in imports
    assert "render_metric_focus_scaffold" in imports
    assert "render_chart_focus_scaffold" in imports


def test_library_import_block_includes_prompted_semantic_helpers():
    imports = PPTXCoder._build_import_block("library")

    assert "add_takeaway_block" in imports
    assert "add_metric_pair_block" in imports
    assert "add_visual_with_caption_block" in imports
    assert "compose_metrics_with_summary" in imports
    assert "compose_visual_with_observations" in imports


def test_library_prompt_requires_scaffold_first_generation():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {"slide_id": "slide_01", "title": "Title", "layout": {}, "blocks": [], "visuals": []},
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "first" in prompt.lower() or "先" in prompt
    assert "scaffold" in prompt.lower()


def test_library_prompt_discourages_low_level_python_pptx_usage():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {"slide_id": "slide_01", "title": "Title", "layout": {}, "blocks": [], "visuals": []},
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "low-level" in prompt.lower() or "底层" in prompt.lower()


def test_library_repair_prompt_mentions_preserve_structure():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="RuntimeError: boom",
        is_fragment_retry=False,
    )

    assert "preserve" in prompt.lower() or "保留" in prompt


def test_library_repair_prompt_mentions_local_fix_preference():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="FileNotFoundError: missing image",
        is_fragment_retry=False,
    )

    assert "local" in prompt.lower() or "局部" in prompt


def test_library_repair_prompt_mentions_helper_or_scaffold_priority():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="AttributeError: layout failed",
        is_fragment_retry=False,
    )

    assert "helper" in prompt.lower() or "scaffold" in prompt.lower()


def test_library_static_check_rejects_main_layout_low_level_code():
    coder = PPTXCoder(DummyClient())
    error = coder._library_static_check(
        """
def build_slide_01(prs, deck_ir, slide_ir, materials):
    slide = add_blank_slide(prs)
    slide.shapes.add_textbox(0, 0, 100, 100)
    slide.shapes.add_shape(1, 0, 0, 100, 100)
    return slide
""",
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
    )

    assert error is not None
    assert "scaffold" in error.lower() or "helper" in error.lower()


def test_library_repair_prompt_classifies_asset_errors():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="FileNotFoundError: missing image asset",
        is_fragment_retry=False,
    )

    assert "asset" in prompt.lower()


def test_library_repair_prompt_classifies_library_constraint_errors():
    coder = PPTXCoder(DummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="LibraryStaticCheckError: library mode should use scaffold/helper first",
        is_fragment_retry=False,
    )

    assert "constraint" in prompt.lower() or "library" in prompt.lower()


def test_qwen_profile_library_prompt_does_not_enable_removed_combo_policy():
    coder = PPTXCoder(QwenDummyClient())
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "scaffold-only" not in prompt.lower()
    assert "manual-only" not in prompt.lower()
    assert "qwen library reliability policy" not in prompt.lower()


def test_qwen_profile_library_prompt_does_not_enable_removed_ir_field_policy():
    coder = PPTXCoder(QwenDummyClient())
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "do not invent fields like" not in prompt.lower()
    assert "qwen library reliability policy" not in prompt.lower()


def test_qwen_profile_library_prompt_does_not_enable_removed_scaffold_harness():
    coder = PPTXCoder(QwenDummyClient())
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {
            "slide_id": "slide_01",
            "title": "Title",
            "type": "content",
            "layout": {
                "name": "two_column",
                "slots": [
                    {"slot_id": "body", "slot_role": "body"},
                    {"slot_id": "supporting_visual", "slot_role": "supporting_visual"},
                ],
            },
            "blocks": [{"kind": "summary", "slot_id": "body", "content": "Summary"}],
            "visuals": [{"slot_id": "supporting_visual"}],
        },
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "recommended scaffold start" not in prompt.lower()


def test_library_generation_skill_prompt_is_opt_in_for_qwen_v1():
    coder = PPTXCoder(QwenDummyClient(), library_generation_skill="qwen_v1")
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "library generation skill profile: qwen_v1" in prompt.lower()
    assert "read `layout.slots` before choosing helpers" in prompt.lower()
    assert "do not replace a real asset with a conceptual fake visual" in prompt.lower()


def test_library_generation_skill_not_included_by_default():
    coder = PPTXCoder(QwenDummyClient())
    prompt = coder._build_slide_prompt(
        {"title": "Deck", "theme": {}},
        {"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        {"asset_index": {}},
        "build_slide_01",
        "library",
    )

    assert "library generation skill profile: qwen_v1" not in prompt.lower()


def test_qwen_library_generation_skill_uses_compact_prompt_slide_payload():
    coder = PPTXCoder(QwenDummyClient(), library_generation_skill="qwen_v1")
    payload = coder._build_prompt_slide_payload(
        {
            "slide_id": "slide_01",
            "title": "Title",
            "subtitle": "Subtitle",
            "core_message": "Core",
            "layout": {
                "name": "two_column",
                "slots": [{"slot_id": "body", "slot_role": "body"}],
            },
            "blocks": [
                {"kind": "summary", "content": "A" * 400},
                {"kind": "bullet_list", "items": ["p1", "p2", "p3", "p4", "p5", "p6"]},
            ],
            "points": ["x1", "x2", "x3", "x4", "x5"],
            "visuals": [{"slot_id": "supporting_visual", "selected_candidate": {"asset_id": "asset_01"}}],
            "source_evidence": [{"source_excerpt": "should not be included"}],
        },
        mode="library",
    )

    assert "source_evidence" not in payload
    assert len(payload["blocks"]) == 2
    assert len(payload["points"]) == 4
    assert len(payload["blocks"][0]["content"]) < 250


def test_qwen_library_generation_skill_repair_prompt_adds_rgbcolor_fix_rule():
    coder = PPTXCoder(QwenDummyClient(), library_generation_skill="qwen_v1")
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="ValueError: assigned value must be type RGBColor",
        is_fragment_retry=False,
    )

    assert "rgbcolor" in prompt.lower()
    assert "use `rgbcolor(" in prompt.lower() or "use rgbcolor(" in prompt.lower()


def test_qwen_library_generation_skill_repair_prompt_adds_syntax_convergence_rule():
    coder = PPTXCoder(QwenDummyClient(), library_generation_skill="qwen_v1")
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="SyntaxError: '(' was never closed",
        is_fragment_retry=False,
    )

    assert "syntaxerror" in prompt.lower()
    assert "simplify the last edited block" in prompt.lower()


def test_qwen_library_static_check_rejects_double_slide_scaffold_pattern():
    coder = PPTXCoder(QwenDummyClient())
    error = coder._library_static_check(
        """
def build_slide_01(prs, deck_ir, slide_ir, materials):
    slide = add_blank_slide(prs)
    render_title_body_visual_scaffold(prs, deck_ir, slide_ir, materials)
    return slide
""",
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        model_profile="qwen",
    )

    assert error is not None
    assert "add_blank_slide" in error
    assert "render_" in error


def test_qwen_library_static_check_rejects_invented_schema_fields():
    coder = PPTXCoder(QwenDummyClient())
    error = coder._library_static_check(
        """
def build_slide_01(prs, deck_ir, slide_ir, materials):
    slide = add_blank_slide(prs)
    summary_text = slide_ir.get("summary", "")
    bullet_points = slide_ir.get("bullet_points", [])
    visual_path = slide_ir.get("visual_path")
    return slide
""",
        slide_ir={"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        model_profile="qwen",
    )

    assert error is not None
    assert "schema" in error.lower() or "field" in error.lower()


def test_qwen_library_static_check_requires_body_content_source_for_content_slide():
    coder = PPTXCoder(QwenDummyClient())
    error = coder._library_static_check(
        """
def build_slide_01(prs, deck_ir, slide_ir, materials):
    slide = add_blank_slide(prs)
    title = slide_ir.get("title", "")
    add_title_box(slide, title, 0, 0, 1, 1)
    return slide
""",
        slide_ir={"slide_id": "slide_01", "title": "Title", "type": "content", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        model_profile="qwen",
    )

    assert error is not None
    assert "body" in error.lower() or "content source" in error.lower()


def test_qwen_profile_library_repair_prompt_does_not_enable_removed_body_harness():
    coder = PPTXCoder(QwenDummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={
            "slide_id": "slide_01",
            "title": "Title",
            "type": "content",
            "layout": {
                "name": "two_column",
                "slots": [
                    {"slot_id": "body", "slot_role": "body"},
                    {"slot_id": "supporting_visual", "slot_role": "supporting_visual"},
                ],
            },
            "blocks": [{"kind": "summary", "slot_id": "body", "content": "Summary"}],
            "points": ["Point 1"],
            "visuals": [{"slot_id": "supporting_visual"}],
        },
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="LibraryStaticCheckError: Qwen library mode content slides must render at least one body content source from `blocks`, `points`, or `core_message`",
        is_fragment_retry=False,
    )

    assert "restore body content first" not in prompt.lower()
    assert "qwen repair harness" not in prompt.lower()


def test_qwen_profile_library_repair_prompt_does_not_enable_removed_scaffold_harness():
    coder = PPTXCoder(QwenDummyClient())
    prompt = coder._build_slide_repair_prompt(
        deck_ir={"title": "Deck", "theme": {}},
        slide_ir={
            "slide_id": "slide_01",
            "title": "Title",
            "type": "content",
            "layout": {"name": "two_column", "slots": [{"slot_id": "body", "slot_role": "body"}]},
            "blocks": [{"kind": "summary", "slot_id": "body", "content": "Summary"}],
            "visuals": [],
        },
        materials={"asset_index": {}},
        function_name="build_slide_01",
        mode="library",
        previous_code="def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None",
        error_message="LibraryStaticCheckError: library mode should use scaffold/helper first for the main layout before low-level python-pptx calls",
        is_fragment_retry=False,
    )

    assert "rewrite the function around one scaffold" not in prompt.lower()
    assert "recommended scaffold start" not in prompt.lower()
    assert "qwen repair harness" not in prompt.lower()


def test_qwen_library_static_check_rejects_shape_delete_calls():
    coder = PPTXCoder(QwenDummyClient())
    error = coder._library_static_check(
        """
def build_slide_01(prs, deck_ir, slide_ir, materials):
    slide = render_slide_scaffold(prs, deck_ir, slide_ir, materials)
    for shape in slide.shapes:
        shape.delete()
    return slide
""",
        slide_ir={"slide_id": "slide_01", "title": "Title", "type": "content", "layout": {"name": "two_column"}, "blocks": [], "visuals": []},
        model_profile="qwen",
    )

    assert error is not None
    assert "delete" in error.lower()


def test_clean_code_block_strips_trailing_non_function_text():
    raw = """```python
def build_slide_06(prs, deck_ir, slide_ir, materials):
    slide = render_slide_scaffold(prs, deck_ir, slide_ir, materials)
    return slide

I am now explaining my design choices in prose.
```"""

    cleaned = PPTXCoder._clean_code_block(raw, "build_slide_06")

    assert cleaned.strip().endswith("return slide")
    assert "design choices" not in cleaned


def test_clean_code_block_salvages_unclosed_fence_and_fragment():
    raw = """```python
def build_slide_02(prs, deck_ir, slide_ir, materials):
    from pptx.util import Inches, Pt
    title = slide_ir.get("title", "")
    fr"""

    cleaned = PPTXCoder._clean_code_block(raw, "build_slide_02")

    assert cleaned.startswith("def build_slide_02(")
    assert "```" not in cleaned
    assert "title = slide_ir.get" in cleaned


def test_clean_code_block_normalizes_rgbcolor_import_typo():
    raw = """
def build_slide_02(prs, deck_ir, slide_ir, materials):
    from pptx.dml.color import RgbColor
    return RgbColor(255, 255, 255)
"""

    cleaned = PPTXCoder._clean_code_block(raw, "build_slide_02")

    assert "from pptx.dml.color import RGBColor" in cleaned
    assert "RgbColor" not in cleaned
