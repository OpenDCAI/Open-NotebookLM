"""Qwen recipe coder.

This mode asks Qwen for a constrained rendering recipe and keeps all python-pptx
operations inside local renderer/library code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .qwen_recipe_schema import QwenRecipeError, build_default_recipe, parse_qwen_recipe_response


class QwenRecipeCoder:
    def __init__(
        self,
        client,
        *,
        max_workers: int = 1,
        max_attempts: int = 1,
        complexity_level: str = "balanced",
    ) -> None:
        self.client = client
        self.max_workers = max(1, int(max_workers or 1))
        self.max_attempts = max(1, int(max_attempts or 1))
        self.complexity_level = str(complexity_level or "balanced").strip().lower()

    def generate_and_render(
        self,
        ir: dict[str, Any],
        materials: dict[str, Any],
        output_path: str,
        mode: str = "qwen_lib",
        save_code_path: str | None = None,
        artifact_dir: str | None = None,
        progress_callback=None,
    ) -> str:
        recipes = []
        slides = list(ir.get("slides", []) or [])
        for index, slide_ir in enumerate(slides, start=1):
            recipe = self.generate_slide_recipe(
                ir,
                slide_ir,
                materials,
                index=index,
                artifact_dir=artifact_dir,
            )
            recipes.append(recipe)
            if progress_callback is not None:
                progress_callback("codegen", index, len(slides), slide_ir.get("slide_id", f"slide_{index:02d}"))

        payload = {"mode": "qwen_recipe", "version": "qwen_recipe_v1", "recipes": recipes}
        if save_code_path:
            Path(save_code_path).parent.mkdir(parents=True, exist_ok=True)
            Path(save_code_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if progress_callback is not None:
            progress_callback("execute", 1, 1, f"render recipe -> {output_path}")
        from .qwen_recipe_renderer import QwenRecipeRenderer

        renderer = QwenRecipeRenderer()
        renderer.render_deck(ir, materials, recipes, output_path, artifact_dir=str(Path(artifact_dir) / "rendered_recipes") if artifact_dir else None)
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def render_single_slide(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        output_path: str,
        *,
        index: int,
        mode: str = "qwen_lib",
        save_code_path: str | None = None,
        artifact_dir: str | None = None,
        progress_callback=None,
    ) -> str:
        recipe = self.generate_slide_recipe(deck_ir, slide_ir, materials, index=index, artifact_dir=artifact_dir)
        payload = {"mode": "qwen_recipe", "version": "qwen_recipe_v1", "recipes": [recipe]}
        if save_code_path:
            Path(save_code_path).parent.mkdir(parents=True, exist_ok=True)
            Path(save_code_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if progress_callback is not None:
            progress_callback("execute", 1, 1, slide_ir.get("slide_id", f"slide_{index:02d}"))
        from .qwen_recipe_renderer import QwenRecipeRenderer

        renderer = QwenRecipeRenderer()
        renderer.render_single_slide(
            deck_ir,
            slide_ir,
            materials,
            recipe,
            output_path=output_path,
            artifact_dir=str(Path(artifact_dir) / "rendered_recipes") if artifact_dir else None,
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def generate_slide_recipe(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        *,
        index: int,
        artifact_dir: str | None = None,
    ) -> dict[str, Any]:
        slide_id = str(slide_ir.get("slide_id") or f"slide_{index:02d}")
        prompt_messages = self._build_messages(deck_ir, slide_ir, materials)
        raw = ""
        last_error: Exception | None = None
        for _attempt in range(self.max_attempts):
            try:
                raw = self.client.chat(prompt_messages, temperature=0.25, response_format="json")
                recipe = parse_qwen_recipe_response(raw, slide_ir=slide_ir)
                self._write_artifacts(artifact_dir, slide_id, raw=raw, recipe=recipe)
                return recipe
            except Exception as exc:
                last_error = exc
        recipe = build_default_recipe(slide_ir)
        self._write_artifacts(artifact_dir, slide_id, raw=raw, recipe=recipe, error=last_error)
        return recipe

    def _build_messages(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
    ) -> list[dict[str, str]]:
        system = (
            "You design one PPT slide as JSON recipe only. Do not write Python. "
            "Do not use python-pptx, EMU, Inches, RGBColor, coordinates in pixels, or raw text not present in IR. "
            "Use ratio rect [x,y,w,h] in 0..1. Output a single JSON object."
        )
        user = {
            "task": "Create a safe recipe for this slide.",
            "schema": self._recipe_schema_text(),
            "complexity_policy": self._complexity_policy_text(),
            "layout_strategy_policy": self._layout_strategy_policy_text(slide_ir),
            "style_palette_policy": self._style_palette_policy_text(),
            "design_hints": self._design_hints_text(),
            "variant_selection": self._variant_selection_text(),
            "few_shot_intents": self._few_shot_intents(),
            "deck": {
                "title": deck_ir.get("title", ""),
                "theme": deck_ir.get("theme", {}),
            },
            "slide": self._project_slide(slide_ir),
            "available_materials": self._project_materials(materials, slide_ir),
        }
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))},
        ]

    def _recipe_schema_text(self) -> str:
        return (
            "Required keys: version, layout, regions, elements, compositions, primitives, emphasis, constraints. "
            "version='qwen_recipe_v1'. layout.kind one of title_body,two_column,comparison,metric_focus,"
            "process_flow,quote_focus,visual_focus. regions use id, role, rect. "
            "layout may include style as a short object and palette with hex colors for background_color, "
            "primary_color, secondary_color, accent_color, text_color, surface_fill, surface_alt_fill, "
            "muted_fill, border_color, strong_band_fill, takeaway_fill, footer_fill. "
            "elements use type, region, source, variant. Allowed sources: slide.title, slide.subtitle, "
            "slide.core_message, points, blocks[i], blocks[i].content, blocks[i].items. "
            "Element variants: headline,subtitle,kicker,section_label,summary_panel,compact_bullets,quote_card,metric_cards,"
            "takeaway,evidence_footer,insight_panel,definition_panel. compositions use region, source, variant; source may be visuals[i] "
            "or points/blocks[i]. Variants: card_grid,comparison_matrix,timeline,process_diagram,"
            "concept_diagram,icon_metaphor,image_or_placeholder,captioned_visual,quote_wall,metrics_strip. "
            "Additional safe variants: table_matrix,chart_takeaway,visual_observations,callout_stack,"
            "statement_ladder,before_after_bridge,numbered_cards,cluster_map,image_caption_overlay,"
            "framework_grid,problem_solution,cycle_loop,pyramid,funnel,evidence_cards,dense_text_columns,visual_compare. "
            "Use rendered_visual when the slide has a Step2/Step3 visual asset and the recipe should place that asset as an image. "
            "primitives: divider,badge,arrow,accent_bar. "
            "Never include text/items/style/fill/line/font/colors; renderer resolves content and theme."
        )

    def _design_hints_text(self) -> str:
        region_hint = (
            "For true complex slides, prefer 4-6 regions when the IR has enough content; otherwise keep 2-4 regions. "
            if self.complexity_level == "complex"
            else "Choose 2-4 regions. "
        )
        return (
            f"{region_hint}It is OK to put multiple items in one region; renderer stacks them safely. "
            "Use before_after_bridge or statement_ladder for transformation/path stories; numbered_cards or "
            "callout_stack/dense_text_columns for dense lists; framework_grid for 2x2 concepts; "
            "problem_solution for contrast; cycle_loop for repeated mechanisms; pyramid/funnel for hierarchy; "
            "visual_observations/image_caption_overlay/visual_compare when a visual slot exists; "
            "rendered_visual means render an existing/generated visual asset; process_diagram means draw a flow from points/blocks text. "
            "chart_takeaway/table_matrix for numeric points. Do not force visuals if the slide did not plan one."
        )

    def _complexity_policy_text(self) -> str:
        if self.complexity_level == "simple":
            return (
                "qwen simple: this maps to the former balanced mode. Prefer stable title/body/visual structure, "
                "3-4 concise content atoms, and moderate visual richness."
            )
        if self.complexity_level == "complex":
            return (
                "qwen true complex: push information architecture richer while staying renderable. Prefer 4-6 regions, "
                "at least two composition variants when the IR supports them, and at least one evidence/mechanism/"
                "comparison/process/metrics/takeaway structure. Use only allowed sources; source_evidence is not a "
                "renderable source unless it has been converted into blocks/points. Avoid rendering the same source twice. "
                "When the slide has a planned visual, choose a visual-led composition with one large rendered_visual and "
                "only 2-3 text regions; do not also keep 4-6 dense text regions."
            )
        return (
            "qwen balanced: this maps to the former complex mode. Prefer 4-5 content atoms, structured layouts, "
            "and one clear visual or structural composition without overloading the slide."
        )

    def _layout_strategy_policy_text(self, slide_ir: dict[str, Any]) -> str:
        has_visual = bool(slide_ir.get("visuals"))
        if self.complexity_level == "complex" and has_visual:
            return (
                "Use visual-led strategy when a generated or selected visual is important: allocate one large "
                "rendered_visual/captioned_visual region, then add only 2-3 text regions for interpretation, evidence, "
                "or takeaway. Do not pair a large rendered_visual with four or more dense text regions. "
                "Use text-led strategy only when there is no essential visual: then prefer structured text, metrics, "
                "evidence cards, or process/comparison compositions."
            )
        return (
            "Choose visual-led when a visual carries the argument, and text-led when the slide is primarily claims, "
            "evidence, or metrics. Keep the number of regions consistent with available space."
        )

    def _style_palette_policy_text(self) -> str:
        return (
            "The model may plan warm, cool, neutral, or high-contrast visual tone through layout.style and "
            "layout.palette. Do not assign a fixed color to a fixed region type; use colors to express hierarchy, "
            "contrast, grouping, and reading flow. Palette values must be #RRGGBB hex. The harness will validate "
            "contrast, derive safe surface/border/band tokens, and correct unsafe colors."
        )

    def _variant_selection_text(self) -> str:
        return (
            "Select by intent, not by template. dense list -> dense_text_columns or numbered_cards; "
            "before/after or two planned visual slots -> prefer a single visual_compare region, not two separate pictures; "
            "transformation without visuals -> before_after_bridge; "
            "ranked hierarchy -> pyramid; narrowing/filtering pipeline -> funnel; "
            "claims with support/source/evidence -> evidence_cards; 4-quadrant concepts -> framework_grid; "
            "looping mechanism -> cycle_loop; metrics -> metrics_strip/chart_takeaway/table_matrix. "
            "If source is visuals[i], choose rendered_visual/captioned_visual/image_caption_overlay/visual_compare, not process_diagram."
        )

    def _few_shot_intents(self) -> list[str]:
        return [
            "6+ short operational bullets, no visual: title_body + dense_text_columns + takeaway.",
            "Two visuals or before/after captions: visual_focus + visual_compare + insight_panel.",
            "Layered priority or maturity levels: metric_focus/title_body + pyramid + summary_panel.",
            "Input narrows to outcome or adoption funnel: process_flow + funnel + evidence_footer.",
            "Evidence-backed claims: comparison/title_body + evidence_cards + compact_bullets.",
        ]

    def _project_slide(self, slide_ir: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "slide_id",
            "type",
            "title",
            "subtitle",
            "core_message",
            "layout",
            "points",
            "blocks",
            "visuals",
            "feedback",
        )
        projected = {key: slide_ir.get(key) for key in keys if key in slide_ir}
        blocks = []
        for block in projected.get("blocks", []) or []:
            if isinstance(block, dict):
                blocks.append(
                    {
                        key: block.get(key)
                        for key in ("kind", "slot_id", "content", "items", "label", "value")
                        if key in block
                    }
                )
        projected["blocks"] = blocks
        visuals = []
        for visual in projected.get("visuals", []) or []:
            if isinstance(visual, dict):
                visuals.append(
                    {
                        key: visual.get(key)
                        for key in ("slot_id", "description", "intent", "asset_role", "caption")
                        if key in visual
                    }
                )
        projected["visuals"] = visuals
        return projected

    def _project_materials(self, materials: dict[str, Any], slide_ir: dict[str, Any]) -> dict[str, Any]:
        return {
            "has_selected_asset": bool(slide_ir.get("selected_asset_path")),
            "asset_count": len(materials.get("assets", []) or []),
        }

    def _write_artifacts(
        self,
        artifact_dir: str | None,
        slide_id: str,
        *,
        raw: str,
        recipe: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        if not artifact_dir:
            return
        directory = Path(artifact_dir) / "recipes"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{slide_id}.raw.txt").write_text(str(raw or ""), encoding="utf-8")
        (directory / f"{slide_id}.recipe.json").write_text(
            json.dumps(recipe, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if error is not None:
            message = str(error)
            if isinstance(error, QwenRecipeError):
                message = f"QwenRecipeError: {message}"
            (directory / f"{slide_id}.error.txt").write_text(message, encoding="utf-8")
