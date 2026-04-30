import json

from src.coder.qwen_recipe_harness import run_recipe_harness


class DummyClient:
    def chat(self, messages, temperature=0.7, response_format=None):
        return json.dumps(
            {
                "layout": {"type": "two_column"},
                "regions": [{"id": "body", "role": "content", "rect": [0.08, 0.24, 0.84, 0.5]}],
                "elements": [{"type": "summary_panel", "region": "body", "source": "blocks[0]", "variant": "summary_panel"}],
                "compositions": [],
                "primitives": [],
                "emphasis": [],
                "constraints": {"no_new_claims": True},
            }
        )


def test_run_recipe_harness_writes_observable_recipe_files(tmp_path):
    slide_ir = {
        "slide_id": "slide_01",
        "type": "content",
        "title": "Title",
        "blocks": [{"kind": "summary", "content": "A"}],
        "visuals": [],
    }

    result = run_recipe_harness(DummyClient(), {}, slide_ir, {}, str(tmp_path), render=False)

    assert result["recipe"]["layout"]["kind"] == "two_column"
    assert result["harness_adjustments"] == result["recipe"]["constraints"]["harness_adjustments"]
    assert (tmp_path / "recipes" / "slide_01.raw.txt").exists()
    assert (tmp_path / "recipes" / "slide_01.recipe.json").exists()
    assert (tmp_path / "harness_result.json").exists()


def test_run_recipe_harness_records_render_audit_when_rendering(tmp_path):
    slide_ir = {
        "slide_id": "slide_01",
        "type": "content",
        "title": "Title",
        "blocks": [{"kind": "summary", "content": "A"}],
        "visuals": [],
    }

    result = run_recipe_harness(DummyClient(), {}, slide_ir, {}, str(tmp_path), render=True)

    assert result["rendered_pptx"]
    assert result["render_audit"]["status"] == "pass"
    assert result["render_audit"]["text_overlaps"] == []
