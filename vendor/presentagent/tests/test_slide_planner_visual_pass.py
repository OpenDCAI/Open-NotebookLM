from src.planner.slide_planner import SlidePlanner


class SequencedClient:
    def __init__(self, responses, model_profile="general"):
        self._responses = list(responses)
        self.model_profile = model_profile

    def chat(self, *_args, **_kwargs):
        if not self._responses:
            raise AssertionError("unexpected extra chat call")
        return self._responses.pop(0)


def _deck_stage():
    return {
        "title": "Deck",
        "subtitle": "",
        "storyline": {
            "topic": "Topic",
            "audience": "Audience",
            "presentation_goal": "Goal",
            "tone": "analytical",
            "sections": [{"id": "section_01", "title": "Section", "objective": "Objective"}],
        },
        "theme": {
            "name": "editorial",
            "primary_color": "#134E8E",
            "secondary_color": "#C00707",
            "accent_color": "#FFB33F",
            "background_color": "#F7F4EE",
            "text_color": "#1F2937",
            "font_family": "Aptos",
            "density": "balanced",
            "style_guardrails": [],
        },
        "planner_notes": [],
        "source_asset_index": {
            "self:0.jpg": {
                "asset_id": "self:0.jpg",
                "path": "/tmp/self0.jpg",
                "relative_path": "images/self/0.jpg",
                "category": "self",
                "asset_kind": "image",
            }
        },
        "deck_outline": [
            {
                "slide_id": "slide_01",
                "type": "content",
                "section_id": "section_01",
                "section_title": "Section",
                "title": "Title",
                "core_message": "Core message",
                "objective": "Objective",
                "brief_id": "brief_01",
                "source_chunk_ids": ["chunk_01"],
                "source_headings": ["Heading"],
                "source_excerpt": "Excerpt",
            }
        ],
    }


def _blueprint():
    return _deck_stage()["deck_outline"][0]


def test_plan_slide_merges_visual_pass_into_content_pass():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"]
            }
            """,
            """
            {
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Supporting figure",
                  "caption": "A supporting figure for the slide",
                  "purpose": "Support the core message",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ]
    )
    planner = SlidePlanner(client=client, max_workers=1)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert len(slide["visuals"]) == 1
    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert len(slide["material_requests"]) == 1
    assert slide["material_requests"][0]["request_id"] == "slide_01_image_01"


def test_plan_slide_uses_single_pass_when_strategy_single():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"],
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Supporting figure",
                  "caption": "A supporting figure for the slide",
                  "purpose": "Support the core message",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ]
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="single", target_slide_count=6)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert slide["material_requests"][0]["request_id"] == "slide_01_image_01"
    assert client._responses == []


def test_plan_slide_adds_visual_fallback_when_visual_slot_exists_but_model_omits_visuals():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"]
            }
            """,
            """
            {
              "visuals": [],
              "material_requests": []
            }
            """,
        ]
    )
    planner = SlidePlanner(client=client, max_workers=1)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert len(slide["visuals"]) == 1
    assert slide["visuals"][0]["slot_id"] == "supporting_visual"
    assert slide["visuals"][0]["use_existing_asset_id"] == "self:0.jpg"
    assert slide["material_requests"] == []


def test_plan_slide_qwen_uses_model_visual_pass_when_single_pass_keeps_visual_slot_only():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"]
            }
            """,
            """
            {
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Model planned visual",
                  "caption": "Model planned caption",
                  "purpose": "Model planned purpose",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ],
        model_profile="qwen",
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=8)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert len(slide["visuals"]) == 1
    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert slide["material_requests"][0]["title"] == "Model planned visual"
    assert client._responses == []


def test_plan_slide_qwen_treats_visual_slot_id_as_visual_followup_signal():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title"},
                  {"slot_id": "body"},
                  {"slot_id": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"]
            }
            """,
            """
            {
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "conceptual_diagram",
                  "title": "Model planned slot-id visual",
                  "caption": "Model planned caption",
                  "purpose": "Model planned purpose",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ],
        model_profile="qwen",
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=8)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert slide["material_requests"][0]["title"] == "Model planned slot-id visual"
    assert client._responses == []


def test_qwen_fragment_repair_wraps_slide_and_visual_tails():
    slide_tail = """
    {
      "chunk_id": "chunk_01",
      "heading": "Heading",
      "excerpt": "Evidence"
    }
  ],
  "layout": {"name": "two_column", "slots": [{"slot_id": "supporting_visual", "slot_role": "supporting_visual"}]},
  "blocks": [{"type": "summary", "slot_id": "body", "content": "Summary"}],
  "points": ["Point"],
  "visuals": [{"slot_id": "supporting_visual", "use_request_id": "req_01", "alt_text": "Alt"}],
  "material_requests": [{"request_id": "req_01", "type": "image", "description": "Diagram"}],
  "design_notes": "note",
  "speaker_notes": "notes"
}
"""
    repaired_slide = SlidePlanner._repair_qwen_slide_fragment_response(slide_tail, _blueprint())
    parsed_slide = SlidePlanner._extract_json(repaired_slide)

    assert parsed_slide["slide_id"] == "slide_01"
    assert len(parsed_slide["source_evidence"]) == 1
    assert parsed_slide["material_requests"][0]["request_id"] == "req_01"

    visual_tail = """
    {
      "slot_id": "supporting_visual",
      "use_request_id": "req_01",
      "alt_text": "Alt"
    }
  ],
  "material_requests": [{"request_id": "req_01", "type": "image", "description": "Diagram"}]
}
"""
    repaired_visual = SlidePlanner._repair_qwen_visual_fragment_response(visual_tail)
    parsed_visual = SlidePlanner._extract_json(repaired_visual)

    assert parsed_visual["visuals"][0]["use_request_id"] == "req_01"
    assert parsed_visual["material_requests"][0]["request_id"] == "req_01"


def test_qwen_alias_normalization_is_profile_scoped():
    qwen_planner = SlidePlanner(SequencedClient([], model_profile="qwen"))
    general_planner = SlidePlanner(SequencedClient([], model_profile="general"))

    qwen_request = qwen_planner._normalize_material_requests(
        [{"request_id": "req_01", "type": "image", "description": "Diagram"}]
    )[0]
    general_request = general_planner._normalize_material_requests(
        [{"request_id": "req_01", "type": "image", "description": "Diagram"}]
    )[0]

    assert qwen_request["caption"] == "Diagram"
    assert qwen_request["purpose"] == "Diagram"
    assert general_request["caption"] == ""
    assert general_request["purpose"] == ""

    qwen_blocks = qwen_planner._normalize_blocks(
        {"slide_id": "slide_01", "blocks": [{"type": "summary", "content": "Summary"}]},
        [],
    )
    general_blocks = general_planner._normalize_blocks(
        {"slide_id": "slide_01", "blocks": [{"type": "summary", "content": "Summary"}]},
        [],
    )

    assert qwen_blocks[0]["kind"] == "summary"
    assert general_blocks[0]["kind"] == "bullet_list"

    qwen_evidence = qwen_planner._normalize_source_evidence(
        {"source_evidence": [{"chunk_id": "chunk_01", "heading": "Heading", "excerpt": "Evidence"}]},
        _blueprint(),
        "slide_01",
    )[0]
    general_evidence = general_planner._normalize_source_evidence(
        {"source_evidence": [{"chunk_id": "chunk_01", "heading": "Heading", "excerpt": "Evidence"}]},
        _blueprint(),
        "slide_01",
    )[0]

    assert qwen_evidence["source_chunk_ids"] == ["chunk_01"]
    assert qwen_evidence["source_headings"] == ["Heading"]
    assert qwen_evidence["source_excerpt"] == "Evidence"
    assert general_evidence["source_chunk_ids"] == []
    assert general_evidence["source_headings"] == []
    assert general_evidence["source_excerpt"] == ""


def test_qwen_single_pass_missing_material_request_uses_model_visual_pass():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"],
              "visuals": [
                {"slot_id": "supporting_visual", "asset_role": "supporting_visual", "target_area": "right", "use_request_id": "slide_01_image_01"}
              ]
            }
            """,
            """
            {
              "visuals": [
                {"slot_id": "supporting_visual", "asset_role": "supporting_visual", "target_area": "right", "use_request_id": "slide_01_image_01"}
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Model generated visual",
                  "caption": "Model generated caption",
                  "purpose": "Model generated purpose",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ],
        model_profile="qwen",
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=8)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["material_requests"][0]["request_id"] == "slide_01_image_01"
    assert slide["material_requests"][0]["title"] == "Model generated visual"
    assert client._responses == []


def test_qwen_prompts_do_not_ask_step2_to_reuse_self_assets():
    planner = SlidePlanner(client=SequencedClient([], model_profile="qwen"), max_workers=1)
    content_slide = {
        "slide_id": "slide_01",
        "layout": {
            "slots": [
                {"slot_id": "supporting_visual", "slot_role": "supporting_visual"},
            ]
        },
    }

    single_prompt = planner._build_slide_single_pass_prompt(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})
    visual_prompt = planner._build_slide_visual_prompt(_deck_stage(), _blueprint(), content_slide, slide_brief={"brief_id": "brief_01"})

    assert "use_existing_asset_id" not in single_prompt
    assert "use_existing_asset_id" not in visual_prompt
    assert "self 素材" not in single_prompt
    assert "self 素材" not in visual_prompt
    assert "Step3" in single_prompt
    assert "Step3" in visual_prompt


def test_qwen_complexity_tiers_are_profile_specific_in_slide_prompts():
    simple = SlidePlanner(SequencedClient([], model_profile="qwen"), complexity_level="simple")
    balanced = SlidePlanner(SequencedClient([], model_profile="qwen"), complexity_level="balanced")
    complex_planner = SlidePlanner(SequencedClient([], model_profile="qwen"), complexity_level="complex")
    general = SlidePlanner(SequencedClient([], model_profile="general"), complexity_level="complex")

    assert "qwen simple" in simple._get_complexity_instruction()
    assert "qwen balanced" in balanced._get_complexity_instruction()
    assert "true complex" in complex_planner._get_complexity_instruction()
    assert "5-6" in complex_planner._get_complexity_instruction()
    assert "visual-led" in complex_planner._get_complexity_instruction()
    assert "true complex" not in general._get_complexity_instruction()

    prompt = complex_planner._build_qwen_slide_content_prompt(
        _deck_stage(),
        _blueprint(),
        slide_brief={"brief_id": "brief_01", "content_points": ["A", "B", "C", "D", "E"]},
    )

    assert "true complex" in prompt
    assert "5-6" in prompt
    assert "visual-led" in prompt
    assert "evidence" in prompt
    assert "use_existing_asset_id" not in prompt


def test_plan_slide_auto_strategy_switches_to_split_for_large_target():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"]
            }
            """,
            """
            {
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Supporting figure",
                  "caption": "A supporting figure for the slide",
                  "purpose": "Support the core message",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ]
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=12)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert client._responses == []


def test_plan_slide_auto_strategy_keeps_single_pass_for_qwen_small_target():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"],
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Supporting figure",
                  "caption": "A supporting figure for the slide",
                  "purpose": "Support the core message",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ],
        model_profile="qwen",
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=8)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert client._responses == []


def test_plan_slide_general_profile_keeps_single_pass_for_small_target():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"],
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Supporting figure",
                  "caption": "A supporting figure for the slide",
                  "purpose": "Support the core message",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ],
        model_profile="general",
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=8)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert client._responses == []


def test_plan_slide_auto_strategy_keeps_single_pass_for_general_small_target():
    client = SequencedClient(
        [
            """
            {
              "slide_id": "slide_01",
              "title": "Title",
              "core_message": "Core message",
              "source_evidence": [],
              "layout": {
                "name": "two_column",
                "slots": [
                  {"slot_id": "title", "slot_role": "title"},
                  {"slot_id": "body", "slot_role": "body"},
                  {"slot_id": "supporting_visual", "slot_role": "supporting_visual"}
                ]
              },
              "blocks": [
                {"block_id": "slide_01_block_01", "kind": "summary", "slot_id": "body", "content": "Summary", "items": []}
              ],
              "points": ["Point 1"],
              "visuals": [
                {
                  "slot_id": "supporting_visual",
                  "asset_role": "supporting_visual",
                  "target_area": "right",
                  "use_request_id": "slide_01_image_01"
                }
              ],
              "material_requests": [
                {
                  "request_id": "slide_01_image_01",
                  "asset_type": "image",
                  "title": "Supporting figure",
                  "caption": "A supporting figure for the slide",
                  "purpose": "Support the core message",
                  "target_slide_id": "slide_01",
                  "preferred_layout_slot": "supporting_visual"
                }
              ]
            }
            """,
        ]
    )
    planner = SlidePlanner(client=client, max_workers=1, slide_ir_strategy="auto", target_slide_count=8)

    slide = planner.plan_slide(_deck_stage(), _blueprint(), slide_brief={"brief_id": "brief_01"})

    assert slide["visuals"][0]["use_request_id"] == "slide_01_image_01"
    assert client._responses == []
