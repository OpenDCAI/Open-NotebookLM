import json

from src.coder.qwen_recipe_coder import QwenRecipeCoder


class DummyRecipeClient:
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


def _slide_ir():
    return {
        "slide_id": "slide_05",
        "type": "content",
        "title": "Title",
        "core_message": "Core",
        "layout": {"name": "two_column"},
        "blocks": [{"kind": "summary", "content": "A"}],
        "visuals": [{"description": "visual"}],
    }


def test_generate_slide_recipe_uses_json_mode_and_writes_artifacts(tmp_path):
    response = json.dumps(
        {
            "layout": {"type": "two_column"},
            "regions": [{"id": "body", "role": "content", "rect": [0.1, 0.2, 0.6, 0.5]}],
            "elements": [{"type": "summary_panel", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
            "compositions": [],
            "primitives": [],
            "emphasis": [],
            "constraints": {"no_new_claims": True},
        }
    )
    client = DummyRecipeClient(response)
    coder = QwenRecipeCoder(client)

    recipe = coder.generate_slide_recipe({}, _slide_ir(), {}, index=5, artifact_dir=str(tmp_path))

    assert client.calls[0]["response_format"] == "json"
    assert "Do not write Python" in client.calls[0]["messages"][0]["content"]
    assert recipe["layout"]["kind"] == "two_column"
    assert (tmp_path / "recipes" / "slide_05.raw.txt").exists()
    assert (tmp_path / "recipes" / "slide_05.recipe.json").exists()


def test_generate_slide_recipe_falls_back_to_default_on_invalid_response(tmp_path):
    client = DummyRecipeClient('{"layout": {"type": "two_column"}, "regions": []}')
    coder = QwenRecipeCoder(client)

    recipe = coder.generate_slide_recipe({}, _slide_ir(), {}, index=5, artifact_dir=str(tmp_path))

    assert recipe["elements"][0]["source"] == "slide.title"
    assert any(item["source"] == "blocks[0]" for item in recipe["elements"])
    assert (tmp_path / "recipes" / "slide_05.error.txt").exists()


def test_recipe_schema_prompt_mentions_expanded_safe_variants():
    coder = QwenRecipeCoder(DummyRecipeClient("{}"))
    schema_text = coder._recipe_schema_text()

    assert "captioned_visual" in schema_text
    assert "quote_wall" in schema_text
    assert "metrics_strip" in schema_text
    assert "table_matrix" in schema_text
    assert "chart_takeaway" in schema_text
    assert "visual_observations" in schema_text
    assert "callout_stack" in schema_text
    assert "before_after_bridge" in schema_text
    assert "statement_ladder" in schema_text
    assert "kicker" in schema_text


def test_recipe_prompt_includes_compact_design_hints():
    coder = QwenRecipeCoder(DummyRecipeClient("{}"))
    messages = coder._build_messages({"title": "Deck"}, _slide_ir(), {})
    payload = json.loads(messages[1]["content"])

    assert "design_hints" in payload
    assert "before_after_bridge" in payload["design_hints"]
    assert "Do not write Python" in messages[0]["content"]


def test_recipe_prompt_includes_compact_variant_selection_rules_and_examples():
    coder = QwenRecipeCoder(DummyRecipeClient("{}"))
    messages = coder._build_messages({"title": "Deck"}, _slide_ir(), {})
    payload = json.loads(messages[1]["content"])

    assert "variant_selection" in payload
    assert "dense_text_columns" in payload["variant_selection"]
    assert "visual_compare" in payload["variant_selection"]
    assert "pyramid" in payload["variant_selection"]
    assert "funnel" in payload["variant_selection"]
    assert "evidence_cards" in payload["variant_selection"]
    assert "prefer a single visual_compare" in payload["variant_selection"]
    assert "few_shot_intents" in payload
    assert len(payload["few_shot_intents"]) <= 5
    assert any("dense_text_columns" in example for example in payload["few_shot_intents"])
    assert any("visual_compare" in example for example in payload["few_shot_intents"])


def test_recipe_prompt_uses_true_complex_policy_only_when_requested():
    balanced = QwenRecipeCoder(DummyRecipeClient("{}"), complexity_level="balanced")
    complex_coder = QwenRecipeCoder(DummyRecipeClient("{}"), complexity_level="complex")

    balanced_payload = json.loads(balanced._build_messages({"title": "Deck"}, _slide_ir(), {})[1]["content"])
    complex_payload = json.loads(complex_coder._build_messages({"title": "Deck"}, _slide_ir(), {})[1]["content"])

    assert "qwen balanced" in balanced_payload["complexity_policy"]
    assert "true complex" not in balanced_payload["complexity_policy"]
    assert "true complex" in complex_payload["complexity_policy"]
    assert "4-6 regions" in complex_payload["complexity_policy"]
    assert "source_evidence" in complex_payload["complexity_policy"]
    assert "visual-led" in complex_payload["complexity_policy"]
    assert "2-3 text regions" in complex_payload["complexity_policy"]


def test_recipe_prompt_tells_qwen_to_budget_visual_led_pages():
    coder = QwenRecipeCoder(DummyRecipeClient("{}"), complexity_level="complex")
    slide_ir = _slide_ir()
    slide_ir["visuals"] = [{"asset_role": "process_diagram", "selected_candidate": {"path": "diagram.png"}}]

    payload = json.loads(coder._build_messages({"title": "Deck"}, slide_ir, {})[1]["content"])

    assert "layout_strategy_policy" in payload
    assert "visual-led" in payload["layout_strategy_policy"]
    assert "Do not pair a large rendered_visual with four or more dense text regions" in payload["layout_strategy_policy"]
    assert "text-led" in payload["layout_strategy_policy"]


def test_recipe_prompt_allows_model_planned_palette_without_fixed_color_slots():
    coder = QwenRecipeCoder(DummyRecipeClient("{}"), complexity_level="complex")

    payload = json.loads(coder._build_messages({"title": "Deck"}, _slide_ir(), {})[1]["content"])

    assert "style_palette_policy" in payload
    assert "model may plan" in payload["style_palette_policy"]
    assert "warm" in payload["style_palette_policy"]
    assert "cool" in payload["style_palette_policy"]
    assert "fixed color" in payload["style_palette_policy"]
