import json
from pathlib import Path

import cli


def _write_planned_ir(tmp_path: Path, ir: dict) -> Path:
    document_dir = tmp_path / "doc"
    planned_dir = document_dir / "ir" / "planned"
    planned_dir.mkdir(parents=True)
    (planned_dir / "final_ir.json").write_text(json.dumps(ir), encoding="utf-8")
    return document_dir


def test_load_existing_ir_rejects_partial_planned_bundle_with_missing_outline_slides(tmp_path):
    document_dir = _write_planned_ir(
        tmp_path,
        {
            "slides": [{"slide_id": "slide_01"}],
            "deck_outline": [{"slide_id": "slide_01"}, {"slide_id": "slide_02"}],
            "material_requests": [{"request_id": "req_01"}],
        },
    )

    assert cli._load_existing_ir(document_dir, stage="planned") is None


def test_load_existing_ir_rejects_partial_planned_bundle_below_target_budget(tmp_path):
    document_dir = _write_planned_ir(
        tmp_path,
        {
            "slides": [{"slide_id": f"slide_{index:02d}"} for index in range(1, 7)],
            "deck_outline": [{"slide_id": f"slide_{index:02d}"} for index in range(1, 7)],
            "longdoc_profile": {"target_slide_count": 17},
            "material_requests": [{"request_id": "req_01"}],
        },
    )

    assert cli._load_existing_ir(document_dir, stage="planned") is None


def test_load_existing_ir_accepts_complete_planned_bundle(tmp_path):
    document_dir = _write_planned_ir(
        tmp_path,
        {
            "slides": [{"slide_id": "slide_01"}, {"slide_id": "slide_02"}],
            "deck_outline": [{"slide_id": "slide_01"}, {"slide_id": "slide_02"}],
            "longdoc_profile": {"target_slide_count": 2},
            "material_requests": [{"request_id": "req_01"}],
        },
    )

    assert cli._load_existing_ir(document_dir, stage="planned") is not None


def test_load_existing_deck_stage_rejects_stage_below_target_budget(tmp_path):
    document_dir = tmp_path / "doc"
    planned_dir = document_dir / "ir" / "planned"
    planned_dir.mkdir(parents=True)
    (planned_dir / "deck_stage.json").write_text(
        json.dumps(
            {
                "title": "Partial deck stage",
                "storyline": {"sections": []},
                "theme": {},
                "deck_outline": [{"slide_id": f"slide_{index:02d}"} for index in range(1, 7)],
                "longdoc_profile": {"target_slide_count": 17},
            }
        ),
        encoding="utf-8",
    )

    assert cli._load_existing_deck_stage(document_dir) is None


def test_load_existing_deck_stage_accepts_complete_stage(tmp_path):
    document_dir = tmp_path / "doc"
    planned_dir = document_dir / "ir" / "planned"
    planned_dir.mkdir(parents=True)
    deck_stage = {
        "title": "Complete deck stage",
        "storyline": {"sections": []},
        "theme": {},
        "deck_outline": [{"slide_id": f"slide_{index:02d}"} for index in range(1, 4)],
        "longdoc_profile": {"target_slide_count": 3},
    }
    (planned_dir / "deck_stage.json").write_text(json.dumps(deck_stage), encoding="utf-8")

    assert cli._load_existing_deck_stage(document_dir) == deck_stage
