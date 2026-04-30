from src.planner.ir_schema import ContentChunk
from src.planner.longdoc_planner import LongDocPlanner


class DummyStep1Client:
    def __init__(self, responses, model_profile="general"):
        self.responses = list(responses)
        self.calls = []
        self.model_profile = model_profile

    def chat(self, messages, temperature=0.0, response_format=None):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        return self.responses.pop(0)


def test_extract_json_uses_first_complete_object_when_model_appends_extra_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planner = LongDocPlanner(client=None)
    response = (
        '{"chunk_id": "chunk_01", "slide_briefs": [{"brief_id": "b1"}]}\n'
        '{"analysis": "extra trailing object"}'
    )

    parsed = planner._extract_json(response)

    assert parsed == {"chunk_id": "chunk_01", "slide_briefs": [{"brief_id": "b1"}]}


def test_extract_json_wraps_single_brief_object_into_slide_briefs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planner = LongDocPlanner(client=None)
    response = '{"brief_id": "chunk_02_brief_01", "core_message": "Message", "content_points": ["P1"]}'

    parsed = planner._normalize_chunk_plan_payload(planner._extract_json(response), "chunk_02")

    assert parsed["slide_briefs"] == [
        {"brief_id": "chunk_02_brief_01", "core_message": "Message", "content_points": ["P1"]}
    ]


def test_parse_chunk_plan_response_collects_multiple_brief_objects_without_wrapper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planner = LongDocPlanner(client=None)
    response = """
{
  "brief_id": "chunk_02_brief_01",
  "core_message": "Message 1",
  "content_points": ["P1"]
},
{
  "brief_id": "chunk_02_brief_02",
  "core_message": "Message 2",
  "content_points": ["P2"]
}
"""

    parsed = planner._parse_chunk_plan_response(response, "chunk_02")

    assert [brief["brief_id"] for brief in parsed["slide_briefs"]] == [
        "chunk_02_brief_01",
        "chunk_02_brief_02",
    ]


def test_parse_chunk_plan_response_salvages_complete_briefs_from_truncated_wrapper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planner = LongDocPlanner(client=None)
    response = """
{
  "chunk_id": "chunk_02",
  "slide_briefs": [
    {
      "brief_id": "chunk_02_brief_01",
      "core_message": "Message 1",
      "content_points": ["P1"]
    },
    {
      "brief_id": "chunk_02_brief_02",
      "core_message": "Message 2",
      "content_points": ["P2"]
    },
    {
      "brief_id": "chunk_02_brief_03",
      "core_message": "Message 3",
      "content_points": ["P3"]
    },
    {
      "brief_id": "chunk_02_brief_04",
      "core_message": "Message 4",
      "content_points": ["P4"],
      "source_excerpt":
"""

    parsed = planner._parse_chunk_plan_response(response, "chunk_02")

    assert [brief["brief_id"] for brief in parsed["slide_briefs"]] == [
        "chunk_02_brief_01",
        "chunk_02_brief_02",
        "chunk_02_brief_03",
    ]


def test_parse_chunk_plan_response_repairs_unescaped_quotes_inside_string_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planner = LongDocPlanner(client=None)
    response = """
{
  "chunk_id": "chunk_02",
  "slide_briefs": [
    {
      "brief_id": "chunk_02_brief_01",
      "title": "个体意识觉醒与疗愈文化驱动自我关怀",
      "core_message": "个体本真性伦理兴起、自我疗愈技术普及、认知升级三股文化思潮共同赋予"爱你老己"正当性，使自我关怀从私人行为转变为集体文化实践。",
      "source_chunk_ids": ["chunk_02"],
      "source_headings": ["3. 个体意识与疗愈文化推进自我和解"]
    },
    {
      "brief_id": "chunk_02_brief_02",
      "title": "社交媒体放大"爱你老己"话语狂欢",
      "core_message": "社交媒体通过符号轻量化编码推动"爱你老己"进入公共话语空间。",
      "source_chunk_ids": ["chunk_02"],
      "source_headings": ["4. 社交媒体驱动"爱你老己"话语狂欢"]
    }
  ]
}
"""

    parsed = planner._parse_chunk_plan_response(response, "chunk_02")

    assert [brief["brief_id"] for brief in parsed["slide_briefs"]] == [
        "chunk_02_brief_01",
        "chunk_02_brief_02",
    ]
    assert parsed["slide_briefs"][0]["core_message"].count('"') == 2
    assert parsed["slide_briefs"][1]["title"] == '社交媒体放大"爱你老己"话语狂欢'


def test_normalize_slide_briefs_derives_source_excerpt_from_chunk_text():
    raw_briefs = [
        {
            "brief_id": "brief_01",
            "slide_id": "slide_01",
            "section_id": "section_01",
            "title": "Friendly self-relationship",
            "core_message": "Students rebuild a friendly self-relationship through 'love your old self'.",
            "content_points": ["The phrase became a viral symbol of self-care among college students."],
            "source_chunk_ids": ["chunk_01"],
            "source_headings": ["Section"],
        }
    ]
    chunks = [
        ContentChunk(
            chunk_id="chunk_01",
            ordinal=1,
            heading_path=["Section"],
            section_title="Section",
            start_offset=0,
            end_offset=120,
            char_count=120,
            overlap_from_previous=0,
            text=(
                "The phrase became a viral symbol of self-care among college students. "
                "Students rebuild a friendly self-relationship through love your old self."
            ),
        )
    ]

    normalized = LongDocPlanner._normalize_slide_briefs(raw_briefs, chunks)

    assert normalized[0]["source_excerpt"]
    assert "self-care among college students" in normalized[0]["source_excerpt"]


def test_build_chunk_prompt_uses_brief_skeleton_without_source_excerpt():
    planner = LongDocPlanner(client=None)
    chunk = ContentChunk(
        chunk_id="chunk_01",
        ordinal=1,
        heading_path=["Section"],
        section_title="Section",
        start_offset=0,
        end_offset=100,
        char_count=100,
        overlap_from_previous=0,
        text="Chunk text",
    )

    prompt = planner._build_chunk_prompt(chunk, chunk_budget=2, markdown="Doc summary")

    assert "source_excerpt" not in prompt
    assert "content_points" not in prompt
    assert "title" in prompt
    assert "core_message" in prompt


def test_plan_single_chunk_uses_two_stage_generation_with_chunk_details():
    client = DummyStep1Client(
        [
            """
{
  "chunk_id": "chunk_01",
  "slide_briefs": [
    {
      "brief_id": "chunk_01_brief_01",
      "title": "Title 1",
      "core_message": "Core 1",
      "source_chunk_ids": ["chunk_01"],
      "source_headings": ["Section"]
    },
    {
      "brief_id": "chunk_01_brief_02",
      "title": "Title 2",
      "core_message": "Core 2",
      "source_chunk_ids": ["chunk_01"],
      "source_headings": ["Section"]
    }
  ]
}
""",
            """
{
  "brief_details": [
    {
      "brief_id": "chunk_01_brief_01",
      "content_points": ["Point 1", "Point 2", "Point 3"],
      "source_excerpt": "Excerpt 1"
    },
    {
      "brief_id": "chunk_01_brief_02",
      "content_points": ["Point A", "Point B"],
      "source_excerpt": "Excerpt 2"
    }
  ]
}
""",
        ]
    )
    planner = LongDocPlanner(client=client)
    chunk = ContentChunk(
        chunk_id="chunk_01",
        ordinal=1,
        heading_path=["Section"],
        section_title="Section",
        start_offset=0,
        end_offset=100,
        char_count=100,
        overlap_from_previous=0,
        text="Chunk text",
    )

    parsed = planner._plan_single_chunk(chunk, chunk_budget=2, markdown="Doc summary")

    assert len(client.calls) == 2
    assert [brief["content_points"] for brief in parsed["slide_briefs"]] == [
        ["Point 1", "Point 2", "Point 3"],
        ["Point A", "Point B"],
    ]
    assert [brief["source_excerpt"] for brief in parsed["slide_briefs"]] == [
        "Excerpt 1",
        "Excerpt 2",
    ]


def test_step1_content_point_limit_uses_provider_specific_caps():
    general_client = DummyStep1Client([], model_profile="general")
    qwen_client = DummyStep1Client([], model_profile="qwen")
    claude_client = DummyStep1Client([], model_profile="claude")

    general_planner = LongDocPlanner(client=general_client)
    qwen_planner = LongDocPlanner(client=qwen_client)
    claude_planner = LongDocPlanner(client=claude_client)

    assert general_planner._step1_content_point_limit() == 4
    assert qwen_planner._step1_content_point_limit() == 4
    assert claude_planner._step1_content_point_limit() == 3


def test_qwen_complexity_tiers_remap_existing_modes_and_add_true_complex():
    qwen_client = DummyStep1Client([], model_profile="qwen")

    simple = LongDocPlanner(client=qwen_client, complexity_level="simple")
    balanced = LongDocPlanner(client=qwen_client, complexity_level="balanced")
    complex_planner = LongDocPlanner(client=qwen_client, complexity_level="complex")

    assert simple._step1_content_point_limit() == 3
    assert simple._step1_excerpt_char_limit() == 90
    assert "qwen simple" in simple._get_complexity_instruction()

    assert balanced._step1_content_point_limit() == 4
    assert balanced._step1_excerpt_char_limit() == 140
    assert "qwen balanced" in balanced._get_complexity_instruction()

    assert complex_planner._step1_content_point_limit() == 6
    assert complex_planner._step1_excerpt_char_limit() == 220
    assert "true complex" in complex_planner._get_complexity_instruction()
    assert "visual-led" in complex_planner._get_complexity_instruction()


def test_step1_claude_profile_uses_stricter_excerpt_and_brief_caps():
    claude_client = DummyStep1Client([], model_profile="claude")
    general_client = DummyStep1Client([], model_profile="general")

    claude_planner = LongDocPlanner(client=claude_client)
    general_planner = LongDocPlanner(client=general_client)

    assert claude_planner._step1_excerpt_char_limit() == 80
    assert general_planner._step1_excerpt_char_limit() == 140
    assert claude_planner._step1_target_briefs(4) == 2
    assert general_planner._step1_target_briefs(4) == 4


def test_build_chunk_prompt_mentions_claude_stability_rule():
    planner = LongDocPlanner(client=DummyStep1Client([], model_profile="claude"), language_mode="english")
    chunk = ContentChunk(
        chunk_id="chunk_01",
        ordinal=1,
        heading_path=["Section"],
        section_title="Section",
        start_offset=0,
        end_offset=100,
        char_count=100,
        overlap_from_previous=0,
        text="Chunk text",
    )

    prompt = planner._build_chunk_prompt(chunk, chunk_budget=4, markdown="Doc summary")

    assert "prioritize JSON stability" in prompt
    assert "slightly fewer, cleaner briefs" in prompt
