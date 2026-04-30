from src.refiner.react_refiner import SlideRenderer
from src.refiner.react_refiner import ReactRefiner
from src.refiner.ir_refinement_prompt import build_ir_refinement_prompt
from src.coder.pptx_coder import PPTXCoder
from src.refiner.skill_system import SkillRegistry


class DummyClient:
    model_profile = "general"

    def chat(self, messages, temperature=0.2, max_tokens=None):
        return "def build_slide_01(prs, deck_ir, slide_ir, materials):\n    return None"


class DummyCoder:
    def generate_slide_code_with_feedback(self, deck_ir, slide_ir, materials, index, mode, artifact_dir=None):
        raise RuntimeError(mode)


def test_slide_renderer_passes_library_mode_into_coder(tmp_path):
    renderer = SlideRenderer(DummyCoder())
    try:
        renderer.render(
            deck_ir={"theme": {}},
            slide_ir={"slide_id": "slide_01"},
            materials={},
            output_dir=str(tmp_path),
            slide_index=1,
            mode="library",
            skip_screenshot=True,
        )
    except RuntimeError as exc:
        assert str(exc) == "library"


class RecordingCoder:
    def __init__(self):
        self.calls = []

    def generate_slide_code_with_feedback(self, deck_ir, slide_ir, materials, index, mode, artifact_dir=None):
        self.calls.append({"index": index, "mode": mode, "artifact_dir": artifact_dir})
        raise RuntimeError("stop")


def test_refiner_keeps_library_mode_for_render_rounds(tmp_path):
    coder = RecordingCoder()
    renderer = SlideRenderer(coder)
    try:
        renderer.render(
            deck_ir={"theme": {}},
            slide_ir={"slide_id": "slide_01"},
            materials={},
            output_dir=str(tmp_path),
            slide_index=1,
            mode="library",
            skip_screenshot=True,
        )
    except RuntimeError:
        pass

    assert coder.calls[0]["mode"] == "library"


def test_refiner_writes_round_metadata_with_mode(tmp_path):
    coder = RecordingCoder()
    renderer = SlideRenderer(coder)
    try:
        renderer.render(
            deck_ir={"theme": {}},
            slide_ir={"slide_id": "slide_01"},
            materials={},
            output_dir=str(tmp_path),
            slide_index=1,
            mode="library",
            skip_screenshot=True,
        )
    except RuntimeError:
        pass

    metadata_path = tmp_path / "codegen" / "render_context.json"
    assert metadata_path.exists()
    content = metadata_path.read_text(encoding="utf-8")
    assert '"mode": "library"' in content


def test_build_refined_deck_script_uses_library_imports_for_library_mode():
    refiner = ReactRefiner.__new__(ReactRefiner)
    refiner.coder = PPTXCoder(DummyClient())

    script = refiner._build_refined_deck_script(
        deck_ir={"slides": [{"slide_id": "slide_01"}]},
        materials={},
        slide_functions=[
            "def build_slide_01(prs, deck_ir, slide_ir, materials):\n"
            "    slide = render_slide_scaffold(prs, deck_ir, slide_ir, materials)\n"
            "    return slide\n"
        ],
        output_path="refined_final.pptx",
        mode="library",
    )

    assert "render_slide_scaffold" in script
    assert "from src.coder.pptx_library import (" in script


def test_library_react_skill_prompt_is_opt_in_for_qwen_v1():
    prompt = build_ir_refinement_prompt(
        editable_view={
            "slide_id": "slide_01",
            "title": "Title",
            "layout": {"name": "two_column"},
            "blocks": [],
            "visuals": [],
            "design_notes": [],
        },
        vlm_feedback={"score": 6.5, "feedback": "visual is weak", "strengths": []},
        history={},
        available_tools=[],
        mode="library",
        library_react_skill="qwen_v1",
    )

    assert "library react skill profile: qwen_v1" in prompt.lower()
    assert "keep the existing page structure unless feedback demands a layout change" in prompt.lower()
    assert "do not fall back to placeholder" in prompt.lower()
    assert "return only changed fields inside `ir_modifications`" in prompt.lower()
    assert '"rationale"' not in prompt.lower()


def test_library_react_skill_not_included_by_default():
    prompt = build_ir_refinement_prompt(
        editable_view={
            "slide_id": "slide_01",
            "title": "Title",
            "layout": {"name": "two_column"},
            "blocks": [],
            "visuals": [],
            "design_notes": [],
        },
        vlm_feedback={"score": 6.5, "feedback": "visual is weak", "strengths": []},
        history={},
        available_tools=[],
        mode="library",
    )

    assert "library react skill profile: qwen_v1" not in prompt.lower()


def test_qwen_library_react_prompt_uses_compact_action_plan_schema():
    prompt = build_ir_refinement_prompt(
        editable_view={
            "slide_id": "slide_02",
            "title": "Title",
            "subtitle": "Subtitle",
            "core_message": "Core",
            "layout": {"name": "two_column", "slots": [{"slot_id": "body", "slot_role": "body"}]},
            "blocks": [{"kind": "summary", "content": "Summary"}],
            "visuals": [],
            "design_notes": ["Note 1"],
        },
        vlm_feedback={"score": 5.5, "feedback": "tighten layout", "strengths": []},
        history={},
        available_tools=[],
        mode="library",
        library_react_skill="qwen_v1",
    )

    assert '"ir_modifications": {' in prompt
    assert '"tool_calls": [' in prompt
    assert "return only changed fields inside `ir_modifications`" in prompt.lower()
    assert "do not copy the full slide ir" in prompt.lower()


def test_qwen_library_react_prompt_discourages_full_layout_rewrites():
    prompt = build_ir_refinement_prompt(
        editable_view={
            "slide_id": "slide_02",
            "title": "Title",
            "subtitle": "Subtitle",
            "core_message": "Core",
            "layout": {"name": "four_quadrant", "slots": [{"slot_id": "quadrant_1"}]},
            "blocks": [{"kind": "card", "content": "Summary"}],
            "visuals": [],
            "design_notes": ["Note 1"],
        },
        vlm_feedback={"score": 5.5, "feedback": "tighten layout", "strengths": []},
        history={},
        available_tools=[],
        mode="library",
        library_react_skill="qwen_v1",
    )

    lowered = prompt.lower()
    assert "do not return unchanged `title`, `subtitle`, or `core_message`" in lowered
    assert "do not resend the full `layout.slots` array" in lowered
    assert "keep the response compact" in lowered


def test_refiner_extract_json_salvages_balanced_object_with_trailing_text():
    data = ReactRefiner._extract_json(
        '{"ir_modifications":{"slide_id":"slide_01","layout":{"name":"two_column"}},"tool_calls":[]} trailing text',
        source="IR refinement",
    )

    assert data["ir_modifications"]["slide_id"] == "slide_01"
    assert data["tool_calls"] == []


def test_refiner_extract_json_salvages_trailing_commas_and_missing_closers():
    data = ReactRefiner._extract_json(
        '{"ir_modifications":{"slide_id":"slide_01","design_notes":["a",],},"tool_calls":[]',
        source="IR refinement",
    )

    assert data["ir_modifications"]["slide_id"] == "slide_01"
    assert data["ir_modifications"]["design_notes"] == ["a"]


def test_qwen_library_react_sanitize_wraps_top_level_slide_patch_into_ir_modifications():
    refiner = ReactRefiner.__new__(ReactRefiner)
    refiner.library_react_skill = "qwen_v1"

    action_plan = {
        "slide_id": "slide_02",
        "title": "Title",
        "layout": {"name": "four_quadrant"},
        "blocks": [{"kind": "summary", "content": "Summary"}],
        "visuals": [],
    }
    slide_ir = {
        "slide_id": "slide_02",
        "visuals": [],
        "selected_asset_path": None,
    }

    normalized = refiner._sanitize_refinement_action_plan(action_plan, slide_ir, mode="library")

    assert "ir_modifications" in normalized
    assert normalized["ir_modifications"]["slide_id"] == "slide_02"
    assert normalized["ir_modifications"]["layout"]["name"] == "four_quadrant"
    assert normalized["tool_calls"] == []


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.2, response_format=None):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        return self.responses.pop(0)


def test_qwen_library_react_repairs_invalid_json_with_second_pass(monkeypatch):
    monkeypatch.setattr(SkillRegistry, "list_skills", staticmethod(lambda: []))

    client = SequenceClient(
        [
            '{"slide_id":"slide_02","layout":{"name":"four_quadrant"}"blocks":[]}',
            '{"slide_id":"slide_02","layout":{"name":"four_quadrant"},"blocks":[]}',
        ]
    )
    refiner = ReactRefiner(client, coder=None, renderer=None, library_react_skill="qwen_v1")

    slide_ir = {
        "slide_id": "slide_02",
        "title": "Old title",
        "subtitle": "",
        "core_message": "Old core",
        "layout": {"name": "two_column"},
        "blocks": [{"block_id": "b1", "kind": "summary", "content": "Old"}],
        "visuals": [],
        "design_notes": [],
    }
    refined_ir, materials, issues = refiner._refine_slide_ir_with_llm(
        deck_ir={"slides": [slide_ir]},
        slide_ir=slide_ir,
        vlm_feedback={"score": 5.0, "feedback": "tighten structure", "strengths": []},
        materials={"document_dir": "."},
        history={"iteration": 1, "previous_feedback": []},
        mode="library",
    )

    assert refined_ir["layout"]["name"] == "four_quadrant"
    assert materials["document_dir"] == "."
    assert issues == []
    assert len(client.calls) == 2
    assert client.calls[0]["response_format"] == "json"
    assert client.calls[1]["response_format"] == "json"
