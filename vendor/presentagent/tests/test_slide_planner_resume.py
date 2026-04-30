from pathlib import Path

from src.planner.ir_artifacts import IRArtifactWriter
from src.planner.slide_planner import SlidePlanner


class _UnexpectedDeckPlanningClient:
    def chat(self, *_args, **_kwargs):
        raise AssertionError("deck planning should be skipped when deck_stage is supplied")


def _slide_stage(slide_id: str) -> dict:
    return {
        "slide_id": slide_id,
        "type": "content",
        "section_id": "section_01",
        "section_title": "Section",
        "title": f"Title {slide_id}",
        "core_message": f"Message {slide_id}",
        "objective": "Explain the point",
        "layout": {
            "name": "two_column",
            "slots": [
                {
                    "slot_id": "body",
                    "slot_role": "body",
                    "anchor": "left",
                    "content_types": ["summary"],
                }
            ],
        },
        "blocks": [
            {
                "block_id": f"{slide_id}_block_01",
                "kind": "summary",
                "slot_id": "body",
                "content": f"Summary {slide_id}",
            }
        ],
        "points": [f"Point {slide_id}"],
        "visuals": [],
        "material_requests": [],
    }


def test_plan_deck_reuses_supplied_deck_stage_and_existing_slide_docs(tmp_path: Path):
    deck_stage = {
        "title": "Checkpointed Deck",
        "subtitle": "",
        "storyline": {
            "topic": "Topic",
            "audience": "Audience",
            "presentation_goal": "Goal",
            "tone": "Tone",
            "sections": [{"id": "section_01", "title": "Section", "objective": "Objective"}],
        },
        "theme": {"name": "editorial"},
        "longdoc_profile": {"target_slide_count": 1},
        "deck_outline": [
            {
                "slide_id": "slide_01",
                "type": "content",
                "section_id": "section_01",
                "section_title": "Section",
                "title": "Title slide_01",
                "core_message": "Message slide_01",
            }
        ],
        "planner_notes": [],
        "source_asset_index": {},
    }
    writer = IRArtifactWriter()
    writer.write_single_slide(
        {"metadata": {"deck_id": "deck"}, "title": "Checkpointed Deck"},
        _slide_stage("slide_01"),
        str(tmp_path),
        stage="planned",
        slide_number=1,
        material_requests=[],
    )

    planner = SlidePlanner(client=_UnexpectedDeckPlanningClient(), max_workers=1)
    ir = planner.plan_deck(
        "markdown",
        {},
        slide_briefs={},
        existing_deck_stage=deck_stage,
        existing_slides=writer.load_existing_slide_docs(str(tmp_path), stage="planned"),
    )

    assert ir["title"] == "Checkpointed Deck"
    assert [slide["slide_id"] for slide in ir["slides"]] == ["slide_01"]
