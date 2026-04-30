from src.coder.qwen_recipe_probe_suite import build_probe_deck, summarize_probe_results


def test_build_probe_deck_covers_multiple_layout_intents():
    deck = build_probe_deck()

    layouts = {slide["layout"]["name"] for slide in deck["slides"]}
    slide_ids = {slide["slide_id"] for slide in deck["slides"]}
    assert len(deck["slides"]) >= 11
    assert {"quote_focus", "process_flow", "comparison", "metric_focus", "visual_focus"}.issubset(layouts)
    assert {
        "probe_dense_text",
        "probe_visual_compare",
        "probe_pyramid",
        "probe_funnel",
        "probe_evidence_cards",
    }.issubset(slide_ids)


def test_summarize_probe_results_flags_low_layout_diversity():
    results = [
        {
            "slide_id": f"slide_{index}",
            "recipe": {
                "layout": {"kind": "two_column"},
                "elements": [{"variant": "summary_panel"}],
                "compositions": [{"variant": "image_or_placeholder"}],
            },
            "render_audit": {"status": "pass"},
        }
        for index in range(4)
    ]

    summary = summarize_probe_results(results)

    assert summary["two_column_ratio"] == 1.0
    assert "layout_diversity_low_two_column_dominant" in summary["red_flags"]


def test_summarize_probe_results_counts_variants_and_audit_failures():
    summary = summarize_probe_results(
        [
            {
                "slide_id": "a",
                "recipe": {
                    "layout": {"kind": "process_flow"},
                    "elements": [{"variant": "headline"}],
                    "compositions": [{"variant": "cycle_loop"}, {"variant": "framework_grid"}],
                },
                "render_audit": {"status": "pass"},
            },
            {
                "slide_id": "b",
                "recipe": {
                    "layout": {"kind": "metric_focus"},
                    "elements": [{"variant": "metric_cards"}],
                    "compositions": [{"variant": "chart_takeaway"}],
                },
                "render_audit": {"status": "fail"},
            },
        ]
    )

    assert summary["layout_counts"]["process_flow"] == 1
    assert summary["composition_variant_counts"]["cycle_loop"] == 1
    assert summary["audit_status_counts"]["fail"] == 1
    assert summary["failed_slides"] == ["b"]
