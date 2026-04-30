from src.refiner.react_refiner import ReactRefiner
from pathlib import Path
import json


def test_normalize_evaluation_feedback_handles_skipped_vlm_payload():
    raw_feedback = {
        "overall_score": 0,
        "issues": [
            {
                "category": "code_execution",
                "severity": "critical",
                "description": "PPTX generation failed - code has execution errors",
                "suggestion": "Fix code syntax and runtime errors to generate valid PPTX",
            }
        ],
        "strengths": [],
        "needs_refinement": True,
        "skipped_vlm": True,
    }

    normalized = ReactRefiner._normalize_evaluation_feedback(raw_feedback)

    assert normalized["score"] == 0.0
    assert "PPTX generation failed" in normalized["feedback"]
    assert normalized["strengths"] == []
    assert normalized["overall_score"] == 0
    assert normalized["skipped_vlm"] is True


def test_find_latest_successful_slide_artifacts_prefers_round_slide_pair(tmp_path):
    refine_root = tmp_path / "refine"
    slide_dir = refine_root / "round_01" / "slide_02"
    slide_dir.mkdir(parents=True)
    (slide_dir / "slide_02.py").write_text("def build_slide_02(prs, deck_ir, slide_ir, materials):\n    return slide\n", encoding="utf-8")
    (slide_dir / "slide_02.pptx").write_bytes(b"pptx")

    code_path, pptx_path, round_num = ReactRefiner._find_latest_successful_slide_artifacts(
        refine_root,
        "slide_02",
        iterations=1,
    )

    assert code_path == slide_dir / "slide_02.py"
    assert pptx_path == slide_dir / "slide_02.pptx"
    assert round_num == 1


def test_find_latest_successful_slide_artifacts_falls_back_to_validation_pair(tmp_path):
    refine_root = tmp_path / "refine"
    validation_dir = refine_root / "round_01" / "validation" / "slide_06"
    validation_dir.mkdir(parents=True)
    (validation_dir / "attempt_02.py").write_text("def build_slide_06(prs, deck_ir, slide_ir, materials):\n    return slide\n", encoding="utf-8")
    (validation_dir / "attempt_02.pptx").write_bytes(b"pptx")

    code_path, pptx_path, round_num = ReactRefiner._find_latest_successful_slide_artifacts(
        refine_root,
        "slide_06",
        iterations=1,
    )

    assert code_path == validation_dir / "attempt_02.py"
    assert pptx_path == validation_dir / "attempt_02.pptx"
    assert round_num == 1


def test_find_latest_successful_slide_artifacts_skips_incomplete_validation_attempt(tmp_path):
    refine_root = tmp_path / "refine"
    broken_validation = refine_root / "round_01" / "validation" / "slide_06"
    broken_validation.mkdir(parents=True)
    (broken_validation / "attempt_01.py").write_text("def build_slide_06(prs, deck_ir, slide_ir, materials):\n    return slide\n", encoding="utf-8")

    fallback_dir = refine_root / "round_00" / "slide_06"
    fallback_dir.mkdir(parents=True)
    (fallback_dir / "slide_06.py").write_text("def build_slide_06(prs, deck_ir, slide_ir, materials):\n    return slide\n", encoding="utf-8")
    (fallback_dir / "slide_06.pptx").write_bytes(b"pptx")

    code_path, pptx_path, round_num = ReactRefiner._find_latest_successful_slide_artifacts(
        refine_root,
        "slide_06",
        iterations=1,
    )

    assert code_path == fallback_dir / "slide_06.py"
    assert pptx_path == fallback_dir / "slide_06.pptx"
    assert round_num == 0


def test_extract_json_salvages_first_complete_object_with_trailing_json_like_garbage():
    response = """
    {
      "slide_id": "slide_01",
      "ir_modifications": {
        "title": "Updated title"
      },
      "tool_calls": []
    }
    {
      "extra": "ignore this trailing object"
    }
    """

    parsed = ReactRefiner._extract_json(response, source="IR refinement")

    assert parsed["slide_id"] == "slide_01"
    assert parsed["ir_modifications"]["title"] == "Updated title"


def test_load_previous_feedback_falls_back_to_checkpoint_history(tmp_path):
    refine_root = tmp_path / "refine"
    checkpoint_root = refine_root / "checkpoints"
    checkpoint_root.mkdir(parents=True)

    slide_ir = {"slide_id": "slide_02"}
    checkpoint_path = checkpoint_root / "slide_02.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "slide_id": "slide_02",
                "complete": False,
                "history": [
                    {
                        "iteration": 1,
                        "score": 6.4,
                        "feedback": "Need better alignment",
                        "strengths": ["Readable title"],
                    }
                ],
                "slide_ir": slide_ir,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    feedback = ReactRefiner._load_previous_feedback(
        prev_round_dir=refine_root / "round_01",
        checkpoint_root=checkpoint_root,
        slide_ir=slide_ir,
        round_num=2,
    )

    assert feedback["score"] == 6.4
    assert feedback["feedback"] == "Need better alignment"
    assert feedback["strengths"] == ["Readable title"]


def test_qwen_library_react_harness_preserves_bound_visuals_when_plan_clears_them():
    refiner = ReactRefiner.__new__(ReactRefiner)
    refiner.library_react_skill = "qwen_v1"
    slide_ir = {
        "slide_id": "slide_01",
        "visuals": [
            {
                "slot_id": "supporting_visual",
                "selected_candidate": {"asset_id": "asset_01", "path": "/tmp/a.png"},
            }
        ],
    }
    action_plan = {
        "ir_modifications": {"visuals": []},
        "tool_calls": [],
    }

    sanitized = refiner._sanitize_refinement_action_plan(action_plan, slide_ir, mode="library")

    assert "visuals" not in sanitized["ir_modifications"]


def test_qwen_library_react_harness_keeps_visual_replacement_when_collect_material_exists():
    refiner = ReactRefiner.__new__(ReactRefiner)
    refiner.library_react_skill = "qwen_v1"
    slide_ir = {
        "slide_id": "slide_01",
        "visuals": [
            {
                "slot_id": "supporting_visual",
                "selected_candidate": {"asset_id": "asset_01", "path": "/tmp/a.png"},
            }
        ],
    }
    action_plan = {
        "ir_modifications": {"visuals": []},
        "tool_calls": [{"tool": "collect_material", "params": {"replace_visual_id": "supporting_visual"}}],
    }

    sanitized = refiner._sanitize_refinement_action_plan(action_plan, slide_ir, mode="library")

    assert sanitized["ir_modifications"]["visuals"] == []
