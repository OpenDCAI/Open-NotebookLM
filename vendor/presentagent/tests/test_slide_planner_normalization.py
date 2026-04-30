from src.planner.slide_planner import SlidePlanner


def test_normalize_string_list_extracts_text_from_dict_items():
    items = [
        {"item_id": "itm_02_02", "text": "缺乏针对农业专家的深度定制", "icon_hint": "warning"},
        {"label": "专为农业专家设计", "icon_hint": "user-check"},
    ]

    normalized = SlidePlanner._normalize_string_list(items)

    assert normalized == ["缺乏针对农业专家的深度定制", "专为农业专家设计"]
    assert "item_id" not in "\n".join(normalized)
    assert "icon_hint" not in "\n".join(normalized)


def test_extract_json_uses_first_complete_object_when_model_appends_extra_json():
    response = '{"title": "Deck", "deck_outline": []}\n{"analysis": "extra trailing object"}'

    parsed = SlidePlanner._extract_json(response, repair_context="deck planning")

    assert parsed == {"title": "Deck", "deck_outline": []}


def test_material_request_orientation_preference_normalizes_common_aliases():
    planner = SlidePlanner(client=None)

    requests = planner._normalize_material_requests(
        [
            {
                "request_id": "req_01",
                "asset_type": "image",
                "title": "Example 1",
                "caption": "Example caption 1",
                "purpose": "Support slide 1",
                "target_slide_id": "slide_01",
                "orientation_preference": "horizontal",
            },
            {
                "request_id": "req_02",
                "asset_type": "image",
                "title": "Example 2",
                "caption": "Example caption 2",
                "purpose": "Support slide 2",
                "target_slide_id": "slide_02",
                "orientation_preference": "vertical",
            },
            {
                "request_id": "req_03",
                "asset_type": "image",
                "title": "Example 3",
                "caption": "Example caption 3",
                "purpose": "Support slide 3",
                "target_slide_id": "slide_03",
                "orientation_preference": "wide",
            },
            {
                "request_id": "req_04",
                "asset_type": "image",
                "title": "Example 4",
                "caption": "Example caption 4",
                "purpose": "Support slide 4",
                "target_slide_id": "slide_04",
                "orientation_preference": "widescreen 16:9",
            },
            {
                "request_id": "req_05",
                "asset_type": "image",
                "title": "Example 5",
                "caption": "Example caption 5",
                "purpose": "Support slide 5",
                "target_slide_id": "slide_05",
                "orientation_preference": "upright figure",
            },
            {
                "request_id": "req_06",
                "asset_type": "image",
                "title": "Example 6",
                "caption": "Example caption 6",
                "purpose": "Support slide 6",
                "target_slide_id": "slide_06",
                "orientation_preference": "1:1",
            },
            {
                "request_id": "req_07",
                "asset_type": "image",
                "title": "Example 7",
                "caption": "Example caption 7",
                "purpose": "Support slide 7",
                "target_slide_id": "slide_07",
                "orientation_preference": "no preference",
            },
            {
                "request_id": "req_08",
                "asset_type": "image",
                "title": "Example 8",
                "caption": "Example caption 8",
                "purpose": "Support slide 8",
                "target_slide_id": "slide_08",
                "orientation_preference": "poster-like schematic",
            },
        ]
    )

    assert requests[0]["orientation_preference"] == "landscape"
    assert requests[1]["orientation_preference"] == "portrait"
    assert requests[2]["orientation_preference"] == "landscape"
    assert requests[3]["orientation_preference"] == "landscape"
    assert requests[4]["orientation_preference"] == "portrait"
    assert requests[5]["orientation_preference"] == "square"
    assert requests[6]["orientation_preference"] == "any"
    assert requests[7]["orientation_preference"] == "any"
