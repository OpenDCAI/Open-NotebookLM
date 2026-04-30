import json

from src.refiner.qwen_recipe_refiner import QwenRecipeRefiner


class DummyRecipeRefineClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, messages, temperature=0.7, response_format=None):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        return self.response


class SequencedRecipeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.7, response_format=None):
        self.calls.append({"messages": messages, "temperature": temperature, "response_format": response_format})
        if self.responses:
            return self.responses.pop(0)
        return "{}"


def _deck_ir():
    return {
        "title": "Deck",
        "theme": {},
        "slides": [_slide_ir()],
    }


def _slide_ir():
    return {
        "slide_id": "slide_01",
        "type": "content",
        "title": "Title",
        "core_message": "Core",
        "blocks": [{"kind": "summary", "content": "Body"}],
        "points": ["A: 72", "B: 64"],
        "visuals": [{"intent": "visual"}],
    }


def test_qwen_recipe_refiner_rewrites_recipe_from_feedback_and_applies_harness():
    response = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "two_column"},
            "regions": [
                {"id": "body", "role": "content", "rect": [0.08, 0.22, 0.55, 0.6]},
                {"id": "visual", "role": "visual", "rect": [0.12, 0.25, 0.55, 0.58]},
            ],
            "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
            "compositions": [{"type": "visual", "region": "visual", "source": "visuals[0]", "variant": "captioned_visual"}],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        }
    )
    client = DummyRecipeRefineClient(response)
    refiner = QwenRecipeRefiner(client)

    recipe = refiner.refine_slide_recipe(
        _deck_ir(),
        _slide_ir(),
        {},
        current_recipe={"version": "qwen_recipe_v1", "regions": []},
        feedback={"score": 5.0, "feedback": "visual overlaps body"},
    )

    assert client.calls[0]["response_format"] == "json"
    assert recipe["compositions"][0]["variant"] == "captioned_visual"
    assert recipe["constraints"]["harness_adjustments"]


def test_qwen_recipe_refiner_prompt_includes_structured_audit_repair_actions():
    refiner = QwenRecipeRefiner(DummyRecipeRefineClient("{}"))
    prompt = refiner._build_recipe_refine_prompt(
        _deck_ir(),
        _slide_ir(),
        {},
        current_recipe={
            "version": "qwen_recipe_v1",
            "layout": {"kind": "title_body"},
            "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
            "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
            "compositions": [],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        },
        feedback={
            "score": 5.0,
            "feedback": "audit failed",
            "duplicate_text_warnings": [{"slide": 1, "text": "重复事实句", "severity": "fail"}],
            "image_aspect_distortions": [{"slide": 1, "distortion": 0.4}],
        },
    )
    payload = json.loads(prompt)

    assert "duplicate_text_warnings" in payload["feedback"]
    assert any("remove duplicate render nodes" in rule for rule in payload["recipe_adjustment_policy"])
    assert any("image aspect" in rule for rule in payload["recipe_adjustment_policy"])


def test_qwen_recipe_refiner_renders_refined_deck(tmp_path):
    client = DummyRecipeRefineClient("{}")
    refiner = QwenRecipeRefiner(client)

    result = refiner.refine_deck(
        _deck_ir(),
        {},
        str(tmp_path),
        initial_recipes=[
            {
                "version": "qwen_recipe_v1",
                "layout": {"kind": "two_column"},
                "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
                "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
                "compositions": [],
                "primitives": [],
                "emphasis": [],
                "constraints": {"no_new_claims": True},
            }
        ],
    )

    assert result["final_pptx"].endswith("refined_final.pptx")
    assert result["recipes"][0]["constraints"]["harness_adjustments"] == []


def test_qwen_recipe_refiner_stops_when_vlm_score_reaches_threshold(tmp_path):
    client = SequencedRecipeClient([])
    refiner = QwenRecipeRefiner(client, max_iterations=3, threshold=8.0)
    refiner._evaluate_rendered_slide = lambda *args, **kwargs: {
        "score": 8.4,
        "feedback": "good enough",
        "strengths": ["clear"],
    }

    result = refiner.refine_deck(
        _deck_ir(),
        {},
        str(tmp_path),
        initial_recipes=[
            {
                "version": "qwen_recipe_v1",
                "layout": {"kind": "two_column"},
                "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
                "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
                "compositions": [],
                "primitives": [],
                "emphasis": [],
                "constraints": {"no_new_claims": True},
            }
        ],
    )

    assert result["react_history"][0]["iterations"] == 1
    assert result["react_history"][0]["complete"] is True
    assert client.calls == []


def test_qwen_recipe_refiner_refines_until_vlm_threshold_or_max_iterations(tmp_path):
    refined_response = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "two_column"},
            "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
            "elements": [{"type": "block", "region": "body", "source": "slide.core_message", "variant": "insight_panel"}],
            "compositions": [],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        }
    )
    client = SequencedRecipeClient([refined_response, refined_response])
    scores = iter([5.5, 7.0, 8.2])
    refiner = QwenRecipeRefiner(client, max_iterations=3, threshold=8.0)
    refiner._evaluate_rendered_slide = lambda *args, **kwargs: {
        "score": next(scores),
        "feedback": "improve hierarchy",
        "strengths": [],
    }

    result = refiner.refine_deck(
        _deck_ir(),
        {},
        str(tmp_path),
        initial_recipes=[
            {
                "version": "qwen_recipe_v1",
                "layout": {"kind": "two_column"},
                "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
                "elements": [{"type": "block", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
                "compositions": [],
                "primitives": [],
                "emphasis": [],
                "constraints": {"no_new_claims": True},
            }
        ],
    )

    assert result["react_history"][0]["iterations"] == 3
    assert result["react_history"][0]["complete"] is True
    assert len(client.calls) == 2


def test_qwen_recipe_refiner_prompt_converts_vlm_feedback_to_recipe_only_constraints():
    refiner = QwenRecipeRefiner(DummyRecipeRefineClient("{}"))
    prompt = refiner._build_recipe_refine_prompt(
        _deck_ir(),
        _slide_ir(),
        {},
        current_recipe={"version": "qwen_recipe_v1", "regions": []},
        feedback={
            "score": 6.2,
            "feedback": "update IR, add images, increase gutter, align card top edges",
        },
    )
    payload = json.loads(prompt)

    assert "recipe_adjustment_policy" in payload
    policy = " ".join(payload["recipe_adjustment_policy"])
    assert "Do not modify slide IR" in policy
    assert "Do not invent materials" in policy
    assert "alignment" in policy
    assert "spacing" in policy
    assert "structure_fidelity" in payload


def test_qwen_recipe_refiner_rejects_recipe_that_drops_existing_body_sources():
    response = json.dumps(
        {
            "version": "qwen_recipe_v1",
            "layout": {"kind": "title_body"},
            "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
            "elements": [{"type": "block", "region": "body", "source": "slide.core_message", "variant": "summary_panel"}],
            "compositions": [],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        }
    )
    client = DummyRecipeRefineClient(response)
    refiner = QwenRecipeRefiner(client)
    current_recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
        "elements": [{"type": "block", "region": "body", "source": "points", "variant": "compact_bullets"}],
        "compositions": [{"type": "evidence", "region": "body", "source": "points", "variant": "evidence_cards"}],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    recipe = refiner.refine_slide_recipe(
        _deck_ir(),
        _slide_ir(),
        {},
        current_recipe=current_recipe,
        feedback={"score": 6.0, "feedback": "improve spacing"},
    )

    sources = {item.get("source") for item in recipe["elements"] + recipe["compositions"]}
    assert "points" in sources
    assert "content_preservation:rejected_dropped_sources" in recipe["constraints"]["harness_adjustments"]


def test_qwen_recipe_refiner_preserves_current_recipe_when_model_returns_unparseable_fragment():
    client = DummyRecipeRefineClient(
        '{"kind":"two_column","density":"dense","style":{"tone":"neutral"},"palette":{"background_color":"#F7F4EE"}'
    )
    refiner = QwenRecipeRefiner(client)
    current_recipe = {
        "version": "qwen_recipe_v1",
        "layout": {"kind": "title_body"},
        "regions": [{"id": "body", "role": "content", "rect": [0.06, 0.22, 0.88, 0.58]}],
        "elements": [{"type": "block", "region": "body", "source": "points", "variant": "compact_bullets"}],
        "compositions": [],
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }

    recipe = refiner.refine_slide_recipe(
        _deck_ir(),
        _slide_ir(),
        {},
        current_recipe=current_recipe,
        feedback={"score": 6.0, "feedback": "increase density"},
    )

    assert recipe["elements"][0]["source"] == "points"
    assert "react_refine_parse_failed" in recipe["constraints"]["harness_adjustments"]
