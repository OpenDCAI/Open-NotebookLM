"""Safe renderer for Qwen recipe-based PPT generation."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import pptx_library as lib
from .qwen_recipe_schema import build_default_recipe, normalize_recipe, validate_recipe


SOURCE_RE = re.compile(r"^(blocks|visuals)\[(\d+)\](?:\.(content|items))?$")


class QwenRecipeRenderer:
    """Render a normalized Qwen recipe without exposing python-pptx APIs to Qwen."""

    def __init__(self, *, slide_width: float = 13.33, slide_height: float = 7.5) -> None:
        self.slide_width = slide_width
        self.slide_height = slide_height

    def render_deck(
        self,
        deck_ir: dict[str, Any],
        materials: dict[str, Any],
        recipes: list[dict[str, Any]],
        output_path: str,
        *,
        artifact_dir: str | None = None,
    ) -> str:
        prs = lib.create_presentation(width=self.slide_width, height=self.slide_height)
        slides = list(deck_ir.get("slides", []) or [])
        for index, slide_ir in enumerate(slides):
            recipe = recipes[index] if index < len(recipes) else build_default_recipe(slide_ir)
            recipe = self._safe_recipe(recipe, slide_ir)
            slide = lib.add_blank_slide(prs)
            self._render_slide(slide, deck_ir, slide_ir, materials, recipe)
            if artifact_dir:
                self._write_recipe_artifact(artifact_dir, slide_ir, recipe, index)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        prs.save(output_path)
        return output_path

    def render_single_slide(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        recipe: dict[str, Any],
        *,
        output_path: str,
        artifact_dir: str | None = None,
    ) -> str:
        single_deck = {**deck_ir, "slides": [slide_ir]}
        return self.render_deck(single_deck, materials, [recipe], output_path, artifact_dir=artifact_dir)

    def _render_slide(
        self,
        slide,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        recipe: dict[str, Any],
    ) -> None:
        theme = self._theme(deck_ir, recipe)
        lib.set_background_color(slide, theme.get("background_color", "#F7F4EE"))
        regions = self._region_rects(recipe)

        for primitive in recipe.get("primitives", []):
            self._render_primitive(slide, primitive, regions, theme)
        for item_type, item, rect in self._layout_render_items(recipe, regions, slide_ir):
            scoped_regions = {str(item.get("region") or ""): rect}
            if item_type == "element":
                self._render_element(slide, slide_ir, item, scoped_regions, theme)
            else:
                self._render_composition(slide, slide_ir, materials, item, scoped_regions, theme)

    def _render_element(
        self,
        slide,
        slide_ir: dict[str, Any],
        element: dict[str, Any],
        regions: dict[str, tuple[float, float, float, float]],
        theme: dict[str, Any],
    ) -> Any:
        rect = regions.get(element.get("region"))
        if rect is None:
            return None
        variant = str(element.get("variant") or "summary_panel")
        source = str(element.get("source") or "")
        if variant == "headline":
            text = self._resolve_text(slide_ir, source)
            return lib.add_textbox(
                slide,
                text,
                left=rect[0],
                top=rect[1],
                width=rect[2],
                height=rect[3],
                font_size=34,
                color=theme.get("primary_color", "#134E8E"),
                bold=True,
                font_name=theme.get("title_font_family", theme.get("font_family", "Aptos")),
                fit=True,
                min_font_size=22,
            )
        if variant == "subtitle":
            text = self._resolve_text(slide_ir, source)
            return lib.add_textbox(
                slide,
                text,
                left=rect[0],
                top=rect[1],
                width=rect[2],
                height=rect[3],
                font_size=16,
                color=theme.get("muted_text_color", "#374151"),
                font_name=theme.get("font_family", "Aptos"),
                fit=True,
                min_font_size=12,
            )
        if variant in {"kicker", "section_label"}:
            text = self._resolve_text(slide_ir, source)
            left, top, width, height = self._inset(rect, 0.02)
            banner_height = min(height, 0.42)
            text, font_size = self._fit_text_to_box(
                text,
                max(width - 0.16, 0.2),
                max(banner_height - 0.04, 0.16),
                20,
                12,
                margin=0.0,
            )
            lib.add_shape(
                slide,
                "RECTANGLE",
                left,
                top,
                width,
                banner_height,
                fill_color=theme.get("accent_color", "#FFB33F"),
                line_color=theme.get("accent_color", "#FFB33F"),
            )
            return lib.add_textbox(
                slide,
                text,
                left + 0.08,
                top + 0.02,
                max(width - 0.16, 0.2),
                max(banner_height - 0.04, 0.16),
                font_size=font_size,
                color="#FFFFFF",
                bold=True,
                font_name=theme.get("font_family", "Aptos"),
                margin=0.0,
            )
        if variant == "evidence_footer":
            return lib.add_evidence_footer_block(
                slide,
                self._resolve_items(slide_ir, source) or [self._resolve_text(slide_ir, source)],
                self._inset(rect, 0.01),
                theme,
            )
        if variant in {"insight_panel", "definition_panel"}:
            text = self._resolve_text(slide_ir, source)
            if not text:
                text = "\n".join(self._resolve_items(slide_ir, source))
            return self._render_takeaway_safe(
                slide,
                text,
                self._inset(rect, 0.035),
                theme,
                preferred_font_size=15,
                min_font_size=11,
            )
        if variant == "takeaway":
            text = self._resolve_text(slide_ir, source)
            if not text:
                text = "\n".join(self._resolve_items(slide_ir, source))
            return self._render_takeaway_safe(slide, text, self._inset(rect, 0.035), theme)
        if variant == "compact_bullets":
            return self._render_compact_bullets_safe(slide, self._resolve_items(slide_ir, source), self._inset(rect, 0.03), theme)
        block = self._resolve_block(slide_ir, source, variant)
        if block:
            return lib.render_block_in_slot(slide, block, self._inset(rect, 0.03), theme)
        text = self._resolve_text(slide_ir, source)
        if text:
            return lib.add_textbox(
                slide,
                text,
                *self._inset(rect, 0.03),
                font_size=16,
                color=theme.get("text_color", "#1F2937"),
                font_name=theme.get("font_family", "Aptos"),
            )
        return None

    def _render_composition(
        self,
        slide,
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        composition: dict[str, Any],
        regions: dict[str, tuple[float, float, float, float]],
        theme: dict[str, Any],
    ) -> Any:
        rect = regions.get(composition.get("region"))
        if rect is None:
            return None
        variant = str(composition.get("variant") or "")
        source = str(composition.get("source") or "")
        if variant in {"image_or_placeholder", "rendered_visual"}:
            visual = self._resolve_visual(slide_ir, source)
            return lib.render_visual_in_slot(slide, slide_ir, materials, visual, rect, theme)
        if variant == "captioned_visual":
            visual = self._resolve_visual(slide_ir, source)
            caption = self._visual_display_caption(visual)
            return lib.add_visual_with_caption_block(
                slide,
                lib.safe_resolve_asset_path(materials, slide_ir, visual) if visual else None,
                caption,
                self._inset(rect, 0.035),
                theme,
            )
        if variant == "image_caption_overlay":
            visual = self._resolve_visual(slide_ir, source)
            caption = self._visual_display_caption(visual)
            return self._render_image_caption_overlay(slide, slide_ir, materials, visual, rect, theme, caption=caption)
        if variant == "quote_wall":
            return lib.render_block_in_slot(
                slide,
                {"kind": "quote", "content": self._resolve_text(slide_ir, source)},
                self._inset(rect, 0.04),
                theme,
            )
        if variant == "metrics_strip":
            if rect[3] < 1.25:
                return None
            metrics = []
            for index, item in enumerate(self._resolve_items(slide_ir, source)[:3]):
                label, value = self._parse_metric_item(item)
                metrics.append(
                    {
                        "label": label.strip() or f"Metric {index + 1}",
                        "value": value.strip() or item,
                    }
                )
            return lib.add_metric_pair_block(metrics=metrics, slide=slide, slot_rect=self._inset(rect, 0.04), theme=theme)
        if variant == "table_matrix":
            return lib.add_table(slide, self._items_to_table_rows(self._resolve_items(slide_ir, source)), *self._inset(rect, 0.04))
        if variant == "chart_takeaway":
            if rect[3] < 1.45:
                return None
            categories, values = self._items_to_chart_data(self._resolve_items(slide_ir, source))
            takeaway = self._resolve_block_content(slide_ir, source) or str(slide_ir.get("core_message") or "Key takeaway")
            return self._render_chart_takeaway_safe(slide, categories, values, takeaway, self._inset(rect, 0.04), theme)
        if variant == "visual_observations":
            visual = self._resolve_visual(slide_ir, source)
            observations = self._resolve_items(slide_ir, "points")
            caption = self._visual_display_caption(visual)
            return lib.compose_visual_with_observations(
                slide,
                lib.safe_resolve_asset_path(materials, slide_ir, visual) if visual else None,
                observations,
                self._inset(rect, 0.04),
                theme,
                caption=caption,
            )
        if variant == "callout_stack":
            return self._render_callout_stack(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "statement_ladder":
            return self._render_statement_ladder(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "before_after_bridge":
            return self._render_before_after_bridge(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "numbered_cards":
            return self._render_numbered_cards(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "cluster_map":
            return self._render_cluster_map(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "framework_grid":
            return self._render_framework_grid(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "problem_solution":
            return self._render_problem_solution(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "cycle_loop":
            return self._render_cycle_loop(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "pyramid":
            return self._render_tapered_stack(slide, self._resolve_items(slide_ir, source), rect, theme, inverted=False)
        if variant == "funnel":
            return self._render_tapered_stack(slide, self._resolve_items(slide_ir, source), rect, theme, inverted=True)
        if variant == "evidence_cards":
            return self._render_evidence_cards(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "dense_text_columns":
            return self._render_dense_text_columns(slide, self._resolve_items(slide_ir, source), rect, theme)
        if variant == "visual_compare":
            return self._render_visual_compare(slide, slide_ir, materials, rect, theme)
        if variant in {"timeline", "process_diagram"}:
            return self._render_process_flow_safe(slide, self._resolve_items(slide_ir, source), self._inset(rect, 0.04), theme)
        if variant == "comparison_matrix":
            items = self._resolve_items(slide_ir, source)[:4]
            headers = [item.split(":", 1)[0].strip() or f"Item {idx + 1}" for idx, item in enumerate(items)]
            columns = [[item.split(":", 1)[1].strip() if ":" in item else item] for item in items]
            return lib.add_comparison_columns(slide, headers or ["A", "B"], columns or [[""], [""]], *self._inset(rect, 0.04))
        if variant == "card_grid":
            return self._render_card_grid(slide, self._resolve_items(slide_ir, source), rect, theme)
        return self._render_concept_panel(slide, self._resolve_items(slide_ir, source), rect, theme, label=variant or "concept")

    def _render_callout_stack(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        if not items:
            return []
        left, top, width, height = self._inset(rect, 0.04)
        gap = min(0.1, max(height * 0.06, 0.035))
        min_item_height = 0.42
        count = min(len(items), 4, max(1, int((height + gap) / (min_item_height + gap))))
        item_height = max((height - gap * (count - 1)) / count, 0.24)
        shapes = []
        for index, item in enumerate(items[:count]):
            shapes.append(self._render_takeaway_safe(slide, item, (left, top + index * (item_height + gap), width, item_height), theme, preferred_font_size=14, min_font_size=11))
        return shapes

    def _render_process_flow_safe(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        steps = [str(item).strip() for item in items[:5] if str(item).strip()]
        if not steps:
            return []
        left, top, width, height = rect
        gap = 0.12
        step_width = max(width / max(len(steps), 1), 0.4)
        box_width = max(step_width - gap, 0.55)
        box_height = max(height - 0.18, 0.28)
        shapes = []
        center_y = top + height / 2
        for index, step in enumerate(steps):
            box_left = left + index * step_width
            box_top = top + 0.08
            shapes.append(
                lib.add_shape(
                    slide,
                    "ROUNDED_RECTANGLE",
                    box_left,
                    box_top,
                    box_width,
                    box_height,
                    fill_color=theme.get("surface_alt_fill", "#EFF6FF"),
                    line_color=theme.get("primary_color", "#134E8E"),
                )
            )
            text, font_size = self._fit_text_to_box(step, max(box_width - 0.2, 0.2), max(box_height - 0.14, 0.16), 12, 9, margin=0.02)
            shapes.append(
                lib.add_textbox(
                    slide,
                    text,
                    box_left + 0.1,
                    box_top + 0.07,
                    max(box_width - 0.2, 0.2),
                    max(box_height - 0.14, 0.16),
                    font_size=font_size,
                    color=theme.get("text_color", "#1F2937"),
                    bold=True,
                    font_name=theme.get("font_family", "Aptos"),
                    margin=0.02,
                )
            )
            if index < len(steps) - 1:
                shapes.append(
                    lib.add_connector(
                        slide,
                        "STRAIGHT",
                        box_left + box_width,
                        center_y,
                        box_left + step_width - 0.03,
                        center_y,
                        color=theme.get("accent_color", "#FFB33F"),
                    )
                )
        return shapes

    def _render_takeaway_safe(
        self,
        slide,
        text: str,
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
        *,
        preferred_font_size: int = 16,
        min_font_size: int = 11,
    ) -> Any:
        left, top, width, height = rect
        if height < 0.18 or width < 0.8:
            return None
        lib.add_panel(
            slide,
            left,
            top,
            width,
            height,
            fill_color=theme.get("takeaway_fill", "#EFF6FF"),
            line_color=theme.get("primary_color", "#134E8E"),
            line_width=1.3,
        )
        text_left = left + min(0.18, width * 0.08)
        text_top = top + min(0.12, height * 0.18)
        text_width = max(width - 2 * (text_left - left), 0.2)
        text_height = max(height - 2 * (text_top - top), 0.16)
        fitted, font_size = self._fit_text_to_box(text, text_width, text_height, preferred_font_size, min_font_size, margin=0.04)
        if not fitted:
            return None
        return lib.add_textbox(
            slide,
            fitted,
            text_left,
            text_top,
            text_width,
            text_height,
            font_size=font_size,
            color=theme.get("primary_color", "#134E8E"),
            bold=True,
            font_name=theme.get("font_family", "Aptos"),
            margin=0.04,
        )

    def _render_chart_takeaway_safe(
        self,
        slide,
        categories: list[str],
        values: list[float],
        takeaway: str,
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> dict[str, Any]:
        left, top, width, height = rect
        takeaway_height = min(0.85, max(height * 0.22, 0.55))
        chart_height = max(height - takeaway_height - 0.18, 0.5)
        try:
            chart = lib.add_bar_chart(slide, categories, "value", values, left, top, width, chart_height)
        except Exception:
            chart = lib.safe_placeholder_panel(slide, (left, top, width, chart_height), label="chart unavailable", theme=theme)
        takeaway_shape = self._render_takeaway_safe(
            slide,
            takeaway,
            (left, top + chart_height + 0.18, width, takeaway_height),
            theme,
            preferred_font_size=15,
            min_font_size=12,
        )
        return {"chart": chart, "takeaway": takeaway_shape}

    def _render_statement_ladder(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = items[:4] or ["Step"]
        gap = 0.08
        item_height = max((height - gap * (len(items) - 1)) / len(items), 0.28)
        shapes = []
        for index, item in enumerate(items):
            step_left = left + min(index * 0.22, width * 0.18)
            step_width = max(width - (step_left - left), 1.0)
            step_top = top + index * (item_height + gap)
            shapes.append(lib.add_panel(slide, step_left, step_top, step_width, item_height, fill_color="#FFFFFF", line_color=theme.get("primary_color", "#134E8E")))
            shapes.append(
                lib.add_textbox(
                    slide,
                    item,
                    step_left + 0.15,
                    step_top + 0.06,
                    max(step_width - 0.3, 0.2),
                    max(item_height - 0.12, 0.2),
                    font_size=14,
                    color=theme.get("text_color", "#1F2937"),
                    bold=index == len(items) - 1,
                    font_name=theme.get("font_family", "Aptos"),
                    fit=True,
                )
            )
        return shapes

    def _render_before_after_bridge(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        labels = (items + ["Before", "Bridge", "After"])[:3]
        gap = 0.22
        card_width = max((width - 2 * gap) / 3, 0.8)
        shapes = []
        for index, item in enumerate(labels):
            card_left = left + index * (card_width + gap)
            shapes.append(lib.add_panel(slide, card_left, top, card_width, height, fill_color="#F8FAFC", line_color=theme.get("primary_color", "#134E8E")))
            shapes.append(
                lib.add_textbox(
                    slide,
                    item,
                    card_left + 0.12,
                    top + 0.1,
                    max(card_width - 0.24, 0.2),
                    max(height - 0.2, 0.2),
                    font_size=13,
                    color=theme.get("text_color", "#1F2937"),
                    bold=index == 2,
                    font_name=theme.get("font_family", "Aptos"),
                    fit=True,
                )
            )
            if index < 2:
                y = top + height / 2
                shapes.append(lib.add_connector(slide, "STRAIGHT", card_left + card_width + 0.04, y, card_left + card_width + gap - 0.04, y, color=theme.get("accent_color", "#FFB33F")))
        return shapes

    def _render_numbered_cards(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = items[:4] or ["Point"]
        gap = 0.14
        card_width = max((width - gap * (len(items) - 1)) / len(items), 0.8)
        shapes = []
        for index, item in enumerate(items):
            card_left = left + index * (card_width + gap)
            compact_label = card_width < 1.45 or height < 1.15
            shapes.append(
                lib.add_panel(
                    slide,
                    card_left,
                    top,
                    card_width,
                    height,
                    fill_color=theme.get("surface_fill", "#FFFFFF"),
                    line_color=theme.get("border_color", "#D1D5DB"),
                    line_width=float(theme.get("panel_line_width", 1.0) or 1.0),
                )
            )
            shapes.append(lib.add_shape(slide, "OVAL", card_left + 0.12, top + 0.12, 0.32, 0.32, fill_color=theme.get("accent_color", "#FFB33F"), line_color=theme.get("accent_color", "#FFB33F")))
            shapes.append(
                lib.add_textbox(
                    slide,
                    str(index + 1),
                    card_left + 0.12,
                    top + 0.14,
                    0.32,
                    0.22,
                    font_size=10,
                    color="#FFFFFF",
                    bold=True,
                    align="center",
                    margin=0.0,
                    font_name=theme.get("font_family", "Aptos"),
                )
            )
            text_width = max(card_width - 0.24, 0.2)
            text_top_offset = 0.46 if compact_label else 0.5
            text_height = max(height - (text_top_offset + 0.08), 0.2)
            fitted_item, fitted_size = self._fit_text_to_box(
                item,
                text_width,
                text_height,
                12 if compact_label else 14,
                10 if compact_label else int(theme.get("min_card_body_font_size", 13) or 13),
                margin=0.02 if compact_label else 0.04,
            )
            shapes.append(
                lib.add_textbox(
                    slide,
                    fitted_item,
                    card_left + 0.12,
                    top + text_top_offset,
                    text_width,
                    text_height,
                    font_size=fitted_size,
                    color=theme.get("text_color", "#1F2937"),
                    font_name=theme.get("font_family", "Aptos"),
                    margin=0.02 if compact_label else 0.04,
                )
            )
        return shapes

    def _render_compact_bullets_safe(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> Any:
        text = " ".join(f"• {item}" for item in items if str(item).strip())
        if not text:
            return None
        fitted, font_size = self._fit_text_to_box(
            text,
            rect[2],
            rect[3],
            16,
            max(int(theme.get("min_bullet_font_size", 13) or 13), 11),
            margin=0.06,
        )
        return lib.add_textbox(
            slide,
            fitted,
            rect[0],
            rect[1],
            rect[2],
            rect[3],
            font_size=font_size,
            color=theme.get("text_color", "#1F2937"),
            font_name=theme.get("font_family", "Aptos"),
            margin=0.06,
        )

    def _render_cluster_map(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        center_text = items[0] if items else "Core"
        satellite_items = items[1:5] or items[:1]
        node_w = min(max(width * 0.34, 1.3), width)
        node_h = min(max(height * 0.34, 0.55), height)
        center_left = left + (width - node_w) / 2
        center_top = top + (height - node_h) / 2
        shapes = [lib.add_takeaway_block(slide, center_text, (center_left, center_top, node_w, node_h), theme)]
        positions = [
            (left, top),
            (left + width - node_w, top),
            (left, top + height - node_h),
            (left + width - node_w, top + height - node_h),
        ]
        for item, (x, y) in zip(satellite_items, positions):
            shapes.append(lib.add_panel(slide, x, y, node_w, node_h, fill_color="#FFFFFF", line_color="#D1D5DB"))
            shapes.append(
                lib.add_textbox(
                    slide,
                    item,
                    x + 0.1,
                    y + 0.08,
                    max(node_w - 0.2, 0.2),
                    max(node_h - 0.16, 0.2),
                    font_size=11,
                    color=theme.get("text_color", "#1F2937"),
                    font_name=theme.get("font_family", "Aptos"),
                    fit=True,
                )
            )
            shapes.append(lib.add_connector(slide, "STRAIGHT", x + node_w / 2, y + node_h / 2, center_left + node_w / 2, center_top + node_h / 2, color=theme.get("accent_color", "#FFB33F")))
        return shapes

    def _render_image_caption_overlay(
        self,
        slide,
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        visual: dict[str, Any] | None,
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
        *,
        caption: str,
    ) -> dict[str, Any]:
        left, top, width, height = self._inset(rect, 0.035)
        asset_path = lib.safe_resolve_asset_path(materials, slide_ir, visual) if visual else None
        image = lib.safe_add_picture(slide, asset_path, left, top, width, height) if asset_path else None
        if image is None:
            image = lib.safe_placeholder_panel(slide, (left, top, width, height), label=caption or "visual", theme=theme)
        if not caption:
            return {"image": image}
        caption_h = min(0.55, max(height * 0.18, 0.28))
        panel = lib.add_panel(slide, left, top + height - caption_h, width, caption_h, fill_color=theme.get("overlay_fill", "#111827"), line_color=theme.get("overlay_fill", "#111827"), radius_shape="RECTANGLE")
        caption_shape = lib.add_textbox(
            slide,
            caption,
            left + 0.16,
            top + height - caption_h + 0.06,
            max(width - 0.32, 0.2),
            max(caption_h - 0.12, 0.2),
            font_size=11,
            color="#FFFFFF",
            font_name=theme.get("font_family", "Aptos"),
            fit=True,
        )
        return {"image": image, "overlay": panel, "caption": caption_shape}

    def _render_framework_grid(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = items[:4] or ["Framework"]
        rows = 2 if len(items) > 2 else 1
        cols = 2 if len(items) > 1 else 1
        gap = 0.12
        cell_w = max((width - gap * (cols - 1)) / cols, 0.8)
        cell_h = max((height - gap * (rows - 1)) / rows, 0.35)
        shapes = []
        for index, item in enumerate(items):
            row = index // cols
            col = index % cols
            x = left + col * (cell_w + gap)
            y = top + row * (cell_h + gap)
            shapes.append(lib.add_panel(slide, x, y, cell_w, cell_h, fill_color="#FFFFFF", line_color=theme.get("primary_color", "#134E8E")))
            shapes.append(
                lib.add_textbox(
                    slide,
                    item,
                    x + 0.12,
                    y + 0.08,
                    max(cell_w - 0.24, 0.2),
                    max(cell_h - 0.16, 0.2),
                    font_size=12,
                    color=theme.get("text_color", "#1F2937"),
                    font_name=theme.get("font_family", "Aptos"),
                    fit=True,
                )
            )
        return shapes

    def _render_problem_solution(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        problem = items[0] if items else "Problem"
        solution = items[-1] if len(items) > 1 else problem
        gap = 0.34
        card_w = max((width - gap) / 2, 0.8)
        shapes = []
        for index, (label, text) in enumerate((("Problem", problem), ("Solution", solution))):
            x = left + index * (card_w + gap)
            fill = "#F8FAFC" if index == 0 else "#EFF6FF"
            shapes.append(lib.add_panel(slide, x, top, card_w, height, fill_color=fill, line_color=theme.get("primary_color", "#134E8E")))
            shapes.append(lib.add_textbox(slide, label, x + 0.14, top + 0.12, max(card_w - 0.28, 0.2), 0.26, font_size=11, color=theme.get("primary_color", "#134E8E"), bold=True, font_name=theme.get("font_family", "Aptos"), fit=True))
            shapes.append(lib.add_textbox(slide, text, x + 0.14, top + 0.45, max(card_w - 0.28, 0.2), max(height - 0.58, 0.2), font_size=13, color=theme.get("text_color", "#1F2937"), font_name=theme.get("font_family", "Aptos"), fit=True))
        y = top + height / 2
        shapes.append(lib.add_connector(slide, "STRAIGHT", left + card_w + 0.06, y, left + card_w + gap - 0.06, y, color=theme.get("accent_color", "#FFB33F")))
        return shapes

    def _render_cycle_loop(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = items[:4] or ["Cycle"]
        node_w = min(max(width * 0.42, 1.0), width)
        node_h = min(max(height * 0.28, 0.42), height)
        positions = [
            (left, top),
            (left + width - node_w, top),
            (left + width - node_w, top + height - node_h),
            (left, top + height - node_h),
        ]
        shapes = []
        centers = []
        for item, (x, y) in zip(items, positions):
            shapes.append(lib.add_panel(slide, x, y, node_w, node_h, fill_color="#FFFFFF", line_color=theme.get("primary_color", "#134E8E")))
            shapes.append(lib.add_textbox(slide, item, x + 0.1, y + 0.07, max(node_w - 0.2, 0.2), max(node_h - 0.14, 0.2), font_size=11, color=theme.get("text_color", "#1F2937"), font_name=theme.get("font_family", "Aptos"), fit=True))
            centers.append((x + node_w / 2, y + node_h / 2))
        for index, (x1, y1) in enumerate(centers):
            x2, y2 = centers[(index + 1) % len(centers)]
            shapes.append(lib.add_connector(slide, "STRAIGHT", x1, y1, x2, y2, color=theme.get("accent_color", "#FFB33F")))
        return shapes

    def _render_tapered_stack(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
        *,
        inverted: bool,
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = items[:4] or ["Layer"]
        gap = 0.06
        layer_h = max((height - gap * (len(items) - 1)) / len(items), 0.24)
        shapes = []
        for index, item in enumerate(items):
            ratio_index = index if inverted else len(items) - 1 - index
            layer_w = max(width * (0.55 + 0.45 * (ratio_index + 1) / len(items)), 0.7)
            x = left + (width - layer_w) / 2
            y = top + index * (layer_h + gap)
            fill = "#EFF6FF" if not inverted else "#FFF7ED"
            shapes.append(lib.add_shape(slide, "RECTANGLE", x, y, layer_w, layer_h, fill_color=fill, line_color=theme.get("primary_color", "#134E8E")))
            shapes.append(lib.add_textbox(slide, item, x + 0.12, y + 0.05, max(layer_w - 0.24, 0.2), max(layer_h - 0.1, 0.2), font_size=11, color=theme.get("text_color", "#1F2937"), bold=index == 0, font_name=theme.get("font_family", "Aptos"), fit=True))
        return shapes

    def _render_evidence_cards(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = [str(item).strip() for item in items[:4] if str(item).strip()]
        if not items:
            return []
        gap = 0.14
        card_w = max((width - gap * (len(items) - 1)) / len(items), 0.8)
        shapes = []
        for index, item in enumerate(items):
            x = left + index * (card_w + gap)
            label, body = self._split_label_value(item)
            shapes.append(
                lib.add_panel(
                    slide,
                    x,
                    top,
                    card_w,
                    height,
                    fill_color=theme.get("surface_alt_fill", "#F9FAFB"),
                    line_color=theme.get("border_color", "#D1D5DB"),
                    line_width=float(theme.get("panel_line_width", 1.0) or 1.0),
                )
            )
            if label:
                label_text, label_size = self._fit_text_to_box(label, max(card_w - 0.24, 0.2), 0.34, 14, 12, margin=0.03)
                shapes.append(lib.add_textbox(slide, label_text, x + 0.12, top + 0.1, max(card_w - 0.24, 0.2), 0.34, font_size=label_size, color=theme.get("primary_color", "#134E8E"), bold=True, font_name=theme.get("font_family", "Aptos"), margin=0.03))
                body_top = top + 0.48
                body_height = max(height - 0.62, 0.2)
            else:
                body_top = top + 0.14
                body_height = max(height - 0.28, 0.2)
            body_text, body_size = self._fit_text_to_box(body, max(card_w - 0.24, 0.2), body_height, 14, 13, margin=0.04)
            shapes.append(lib.add_textbox(slide, body_text, x + 0.12, body_top, max(card_w - 0.24, 0.2), body_height, font_size=body_size, color=theme.get("text_color", "#1F2937"), font_name=theme.get("font_family", "Aptos"), margin=0.04))
        return shapes

    def _render_dense_text_columns(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        items = items or ["Text"]
        cols = 2 if len(items) > 1 else 1
        gap = 0.18
        col_w = max((width - gap * (cols - 1)) / cols, 0.8)
        shapes = []
        for col in range(cols):
            col_items = items[col::cols]
            text = "\n".join(f"• {item}" for item in col_items)
            x = left + col * (col_w + gap)
            fitted_text, fitted_size = self._fit_text_to_box(
                text,
                col_w,
                height,
                14,
                max(int(theme.get("min_bullet_font_size", 13) or 13), 11),
                margin=0.06,
            )
            shapes.append(
                lib.add_textbox(
                    slide,
                    fitted_text,
                    x,
                    top,
                    col_w,
                    height,
                    font_size=fitted_size,
                    color=theme.get("text_color", "#1F2937"),
                    font_name=theme.get("font_family", "Aptos"),
                    margin=0.06,
                )
            )
        return shapes

    def _render_visual_compare(
        self,
        slide,
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        left, top, width, height = self._inset(rect, 0.035)
        visuals = [item for item in slide_ir.get("visuals", []) if isinstance(item, dict)]
        if not visuals:
            visuals = [{"caption": "Before"}, {"caption": "After"}]
        if len(visuals) == 1:
            visuals = [visuals[0], visuals[0]]
        gap = 0.16
        panel_w = max((width - gap) / 2, 0.8)
        shapes = []
        for index, visual in enumerate(visuals[:2]):
            x = left + index * (panel_w + gap)
            caption = self._visual_display_caption(visual) or ("Before" if index == 0 else "After")
            result = lib.add_visual_with_caption_block(
                slide,
                lib.safe_resolve_asset_path(materials, slide_ir, visual),
                caption,
                (x, top, panel_w, height),
                theme,
            )
            shapes.extend(result.values() if isinstance(result, dict) else [result])
        return shapes

    def _render_primitive(
        self,
        slide,
        primitive: dict[str, Any],
        regions: dict[str, tuple[float, float, float, float]],
        theme: dict[str, Any],
    ) -> Any:
        primitive_type = str(primitive.get("type") or "")
        rect = regions.get(primitive.get("region"))
        if rect is None:
            return None
        accent = theme.get("accent_color", "#FFB33F")
        if primitive_type == "divider":
            left, top, width, _height = rect
            divider_top = min(top + rect[3] + 0.03, self.slide_height - 0.04)
            return lib.add_shape(slide, "RECTANGLE", left, divider_top, width, 0.03, fill_color=accent, line_color=accent)
        if primitive_type == "arrow":
            left, top, width, height = rect
            center_y = top + height / 2
            return lib.add_connector(slide, "STRAIGHT", left, center_y, left + width, center_y, color=accent)
        if primitive_type == "accent_bar":
            left, top, _width, height = rect
            bar_left = max(left - 0.08, 0.0)
            return lib.add_shape(slide, "RECTANGLE", bar_left, top, 0.04, height, fill_color=accent, line_color=accent)
        if primitive_type == "badge":
            return lib.add_banner(
                slide,
                str(primitive.get("text") or ""),
                *self._inset(rect, 0.02),
                fill_color=accent,
                font_name=theme.get("font_family", "Aptos"),
            )
        return None

    def _render_card_grid(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
    ) -> list[Any]:
        if not items:
            return []
        left, top, width, height = self._inset(rect, 0.04)
        count = min(len(items), 4)
        gap = 0.16
        card_width = max((width - gap * (count - 1)) / count, 0.8)
        shapes = []
        for index, item in enumerate(items[:count]):
            card_rect = (left + index * (card_width + gap), top, card_width, height)
            shapes.append(lib.add_takeaway_block(slide, item, card_rect, theme))
        return shapes

    def _render_concept_panel(
        self,
        slide,
        items: list[str],
        rect: tuple[float, float, float, float],
        theme: dict[str, Any],
        *,
        label: str,
    ) -> Any:
        text = "\n".join(items[:4]) if items else label.replace("_", " ")
        return lib.add_highlight_block(slide, text, self._inset(rect, 0.04), theme)

    def _safe_recipe(self, recipe: dict[str, Any], slide_ir: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_recipe(deepcopy(recipe), slide_ir=slide_ir)
        if validate_recipe(normalized, slide_ir=slide_ir):
            return build_default_recipe(slide_ir)
        return normalized

    def _region_rects(self, recipe: dict[str, Any]) -> dict[str, tuple[float, float, float, float]]:
        rects = {}
        for region in recipe.get("regions", []):
            ratio = list(region.get("rect") or [0.06, 0.22, 0.88, 0.58])[:4]
            while len(ratio) < 4:
                ratio.append(0.1)
            x, y, w, h = [float(value) for value in ratio]
            rects[str(region["id"])] = (
                self.slide_width * x,
                self.slide_height * y,
                self.slide_width * w,
                self.slide_height * h,
            )
        return rects

    def _layout_render_items(
        self,
        recipe: dict[str, Any],
        regions: dict[str, tuple[float, float, float, float]],
        slide_ir: dict[str, Any],
    ) -> list[tuple[str, dict[str, Any], tuple[float, float, float, float]]]:
        groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        ordered_regions: list[str] = []
        for item_type, items in (
            ("element", recipe.get("elements", [])),
            ("composition", recipe.get("compositions", [])),
        ):
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                region_id = str(item.get("region") or "")
                if region_id not in regions:
                    continue
                if region_id not in groups:
                    groups[region_id] = []
                    ordered_regions.append(region_id)
                groups[region_id].append((item_type, item))

        laid_out: list[tuple[str, dict[str, Any], tuple[float, float, float, float]]] = []
        for region_id in ordered_regions:
            base_rect = regions[region_id]
            items = groups[region_id]
            for item_type, item, rect in self._stack_items_in_region(items, base_rect, slide_ir):
                laid_out.append((item_type, item, rect))
        return laid_out

    def _stack_items_in_region(
        self,
        items: list[tuple[str, dict[str, Any]]],
        rect: tuple[float, float, float, float],
        slide_ir: dict[str, Any],
    ) -> list[tuple[str, dict[str, Any], tuple[float, float, float, float]]]:
        if len(items) <= 1:
            return [(items[0][0], items[0][1], rect)] if items else []
        left, top, width, height = rect
        gap = min(0.08, max(height * 0.035, 0.025))
        available_height = max(height - gap * (len(items) - 1), 0.2)
        weights = [self._item_layout_weight(item_type, item, slide_ir) for item_type, item in items]
        total_weight = sum(weights) or float(len(items))
        heights = [available_height * weight / total_weight for weight in weights]

        min_heights = [self._item_min_height(item_type, item, height, slide_ir) for item_type, item in items]
        heights = [max(value, minimum) for value, minimum in zip(heights, min_heights)]
        total_height = sum(heights)
        if total_height > available_height:
            scale = available_height / total_height
            heights = [max(value * scale, 0.18) for value in heights]
            total_height = sum(heights)
            if total_height > available_height:
                scale = available_height / total_height
                heights = [value * scale for value in heights]

        cursor = top
        laid_out = []
        for (item_type, item), item_height in zip(items, heights):
            laid_out.append((item_type, item, (left, cursor, width, max(item_height, 0.12))))
            cursor += item_height + gap
        return laid_out

    def _item_layout_weight(self, item_type: str, item: dict[str, Any], slide_ir: dict[str, Any]) -> float:
        variant = str(item.get("variant") or "")
        if item_type == "composition":
            if variant in {"image_or_placeholder", "captioned_visual", "visual_observations", "chart_takeaway"}:
                return 2.4
            if variant in {"table_matrix", "comparison_matrix", "timeline", "process_diagram"}:
                return 2.0
            if variant in {"statement_ladder", "before_after_bridge", "numbered_cards", "cluster_map"}:
                return 2.2
            if variant in {"framework_grid", "problem_solution", "cycle_loop", "pyramid", "funnel", "evidence_cards", "dense_text_columns", "visual_compare"}:
                return 2.2
            return 1.5
        if variant == "headline":
            return 1.4
        if variant in {"subtitle", "kicker", "section_label", "evidence_footer"}:
            return 0.75
        if variant in {"compact_bullets", "metric_cards"}:
            return 1.4 + min(len(self._resolve_items(slide_ir, str(item.get("source") or ""))) * 0.35, 2.4)
        text = self._resolve_text(slide_ir, str(item.get("source") or ""))
        return 1.2 + min(len(text) / 80.0, 1.0)

    def _item_min_height(self, item_type: str, item: dict[str, Any], region_height: float, slide_ir: dict[str, Any]) -> float:
        variant = str(item.get("variant") or "")
        if variant == "headline":
            return min(0.55, region_height * 0.55)
        if variant in {"subtitle", "kicker", "section_label", "evidence_footer"}:
            return min(0.34, region_height * 0.38)
        if variant == "compact_bullets":
            item_count = len(self._resolve_items(slide_ir, str(item.get("source") or "")))
            return min(max(0.42 + item_count * 0.22, 0.55), region_height * 0.72)
        if item_type == "composition":
            return min(1.0, region_height * 0.5)
        return min(0.55, region_height * 0.45)

    def _resolve_text(self, slide_ir: dict[str, Any], source: str) -> str:
        if source == "slide.title":
            return str(slide_ir.get("title") or "")
        if source == "slide.subtitle":
            return str(slide_ir.get("subtitle") or "")
        if source == "slide.core_message":
            return str(slide_ir.get("core_message") or "")
        if source == "points":
            return "\n".join(self._resolve_items(slide_ir, source))
        match = SOURCE_RE.match(source)
        if not match or match.group(1) != "blocks":
            return ""
        block = self._get_indexed(slide_ir.get("blocks", []), int(match.group(2)))
        field = match.group(3)
        if field == "items":
            return "\n".join(self._item_text(item) for item in block.get("items", []))
        if field == "content":
            return str(block.get("content") or "")
        return str(block.get("content") or " ".join(str(item) for item in block.get("items", [])))

    def _resolve_items(self, slide_ir: dict[str, Any], source: str) -> list[str]:
        if source == "points":
            points = slide_ir.get("points") or []
            if points:
                return [self._item_text(item) for item in points if self._item_text(item).strip()]
            items = []
            for block in slide_ir.get("blocks", []):
                items.extend(self._item_text(item) for item in block.get("items", []) if self._item_text(item).strip())
                if block.get("content"):
                    items.append(str(block["content"]))
            if slide_ir.get("core_message"):
                items.insert(0, str(slide_ir["core_message"]))
            return items
        match = SOURCE_RE.match(source)
        if match and match.group(1) == "blocks" and match.group(3) is None:
            block = self._get_indexed(slide_ir.get("blocks", []), int(match.group(2)))
            items = [self._item_text(item) for item in block.get("items", []) if self._item_text(item).strip()]
            if items:
                return items
            if block.get("content"):
                return [str(block["content"])]
        text = self._resolve_text(slide_ir, source)
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _resolve_block_content(self, slide_ir: dict[str, Any], source: str) -> str:
        match = SOURCE_RE.match(source)
        if not match or match.group(1) != "blocks":
            return ""
        block = self._get_indexed(slide_ir.get("blocks", []), int(match.group(2)))
        return str(block.get("content") or "").strip()

    def _resolve_block(self, slide_ir: dict[str, Any], source: str, variant: str) -> dict[str, Any] | None:
        match = SOURCE_RE.match(source)
        if not match or match.group(1) != "blocks":
            if source in {"slide.core_message", "points"}:
                return {"kind": self._kind_for_variant(variant), "content": self._resolve_text(slide_ir, source), "items": self._resolve_items(slide_ir, source)}
            return None
        block = deepcopy(self._get_indexed(slide_ir.get("blocks", []), int(match.group(2))))
        field = match.group(3)
        if field == "content":
            block = {"kind": "summary", "content": str(block.get("content") or "")}
        elif field == "items":
            block = {"kind": "bullet_list", "items": [self._item_text(item) for item in block.get("items", [])]}
        block["kind"] = self._kind_for_variant(variant, fallback=str(block.get("kind") or "summary"))
        return block

    @staticmethod
    def _item_text(item: Any) -> str:
        if isinstance(item, dict):
            for key in ("text", "content", "label", "value", "title"):
                value = item.get(key)
                if value is not None and str(value).strip():
                    return str(value)
            return " ".join(str(value) for value in item.values() if str(value).strip())
        return str(item)

    def _items_to_table_rows(self, items: list[str]) -> list[list[str]]:
        pipe_rows = [
            [part.strip() for part in str(item).split("|") if part.strip()]
            for item in items[:6]
            if "|" in str(item)
        ]
        if pipe_rows and len(pipe_rows) == len(items[: len(pipe_rows)]):
            max_cols = max(len(row) for row in pipe_rows)
            if max_cols >= 2:
                return [row + [""] * (max_cols - len(row)) for row in pipe_rows]
        rows = [["Item", "Detail"]]
        for index, item in enumerate(items[:5], start=1):
            left, sep, right = item.partition(":")
            if not sep:
                left, sep, right = item.partition("->")
            rows.append([left.strip() or f"Item {index}", right.strip() if sep else item])
        if len(rows) == 1:
            rows.append(["Item", ""])
        return rows

    def _items_to_chart_data(self, items: list[str]) -> tuple[list[str], list[float]]:
        categories: list[str] = []
        values: list[float] = []
        for index, item in enumerate(items[:5], start=1):
            match = re.search(r"(-?\d+(?:\.\d+)?)", item)
            label = re.split(r"[:：=]", item, maxsplit=1)[0].strip() or f"Item {index}"
            categories.append(label[:18])
            values.append(float(match.group(1)) if match else float(index))
        if not categories:
            return ["A"], [1.0]
        return categories, values

    def _parse_metric_item(self, item: str) -> tuple[str, str]:
        cleaned = re.sub(r"#[0-9A-Fa-f]{6}\b", "", str(item or "")).strip()
        label, sep, value = cleaned.partition(":")
        if not sep:
            label, sep, value = cleaned.partition("：")
        if sep:
            return label.strip(), value.strip()
        matches = list(re.finditer(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)\s*%?", cleaned))
        metric_match = next((match for match in matches if "%" in match.group(0)), None)
        if metric_match is None and matches:
            metric_match = matches[-1] if len(matches) > 1 else matches[0]
        if metric_match:
            metric = metric_match.group(0).strip()
            label = cleaned[: metric_match.start()].strip(" ，,;；:-")
            if not label:
                label = cleaned[metric_match.end() :].strip(" ，,;；:-")
            return label or "Metric", metric
        return cleaned, cleaned

    @staticmethod
    def _split_label_value(item: str) -> tuple[str, str]:
        for separator in (":", "：", "->"):
            left, sep, right = item.partition(separator)
            if sep and left.strip() and right.strip():
                return left.strip(), right.strip()
        return "", item

    def _resolve_visual(self, slide_ir: dict[str, Any], source: str) -> dict[str, Any] | None:
        match = SOURCE_RE.match(source)
        if match and match.group(1) == "visuals":
            return self._get_indexed(slide_ir.get("visuals", []), int(match.group(2))) or None
        visuals = slide_ir.get("visuals", [])
        return visuals[0] if visuals else None

    def _visual_display_caption(self, visual: dict[str, Any] | None) -> str:
        if not isinstance(visual, dict):
            return ""
        for key in ("display_caption", "visible_caption", "short_caption", "caption"):
            text = str(visual.get(key) or "").strip()
            if text and self._is_short_display_caption(text):
                return text
        return ""

    @staticmethod
    def _is_short_display_caption(text: str) -> bool:
        weighted = sum(1.0 if ord(char) > 127 else 0.55 for char in text)
        return weighted <= 28

    def _fit_text_to_box(
        self,
        text: str,
        width: float,
        height: float,
        preferred_font_size: int,
        min_font_size: int,
        *,
        margin: float = 0.04,
    ) -> tuple[str, int]:
        normalized = self._normalize_display_text(text)
        if not normalized:
            return "", min_font_size
        usable_width = max(width - 2 * margin, 0.12)
        usable_height = max(height - 2 * margin, 0.08)
        min_required_height = min_font_size * 1.18 / 72.0 + 2 * margin
        if height < min_required_height:
            return "", min_font_size
        best_truncated: tuple[str, int, float] | None = None
        for size in range(max(preferred_font_size, min_font_size), min_font_size - 1, -1):
            line_height = size * 1.18 / 72.0
            max_lines = int(usable_height / line_height)
            if max_lines < 1:
                continue
            if self._estimated_wrapped_line_count(normalized, usable_width, size) <= max_lines:
                return normalized, size
            chars_per_line = max(int(usable_width * 6.0 * 12.0 / max(size, 1)), 4)
            capacity = max(chars_per_line * max_lines * 0.92, 3.0)
            fitted = self._truncate_to_weight(normalized, capacity)
            if self._estimated_wrapped_line_count(fitted, usable_width, size) <= max_lines:
                score = self._text_weight(fitted.removesuffix("..."))
                if best_truncated is None or score > best_truncated[2]:
                    best_truncated = (fitted, size, score)
        if best_truncated is not None:
            return best_truncated[0], best_truncated[1]
        line_height = min_font_size * 1.18 / 72.0
        max_lines = max(int(usable_height / line_height), 1)
        chars_per_line = max(int(usable_width * 6.0 * 12.0 / max(min_font_size, 1)), 4)
        fitted = self._truncate_to_weight(normalized, max(chars_per_line * max_lines * 0.86, 3.0))
        if height < min_required_height:
            return "", min_font_size
        return fitted, min_font_size

    @staticmethod
    def _normalize_display_text(text: str) -> str:
        return " ".join(str(text or "").replace("\v", " ").split())

    @staticmethod
    def _text_weight(text: str) -> float:
        return sum(1.0 if ord(char) > 127 else 0.56 for char in str(text or ""))

    def _truncate_to_weight(self, text: str, max_weight: float) -> str:
        text = str(text or "").strip()
        if self._text_weight(text) <= max_weight:
            return text
        suffix = "..."
        budget = max(max_weight - self._text_weight(suffix), 1.0)
        total = 0.0
        kept: list[str] = []
        for char in text:
            weight = 1.0 if ord(char) > 127 else 0.56
            if total + weight > budget:
                break
            kept.append(char)
            total += weight
        return "".join(kept).rstrip(" ,;:，；：-") + suffix

    def _estimated_wrapped_line_count(self, text: str, usable_width: float, font_size: int) -> int:
        if not text:
            return 1
        chars_per_line = max(int(usable_width * 6.0 * 12.0 / max(font_size, 1)), 4)
        lines = 0
        for raw_line in str(text).splitlines() or [""]:
            lines += max(1, math.ceil(self._text_weight(raw_line.strip()) / chars_per_line))
        return max(lines, 1)

    def _get_indexed(self, values: Any, index: int) -> dict[str, Any]:
        if isinstance(values, list) and 0 <= index < len(values) and isinstance(values[index], dict):
            return values[index]
        return {}

    def _kind_for_variant(self, variant: str, *, fallback: str = "summary") -> str:
        mapping = {
            "summary_panel": "summary",
            "compact_bullets": "bullet_list",
            "quote_card": "quote",
            "metric_cards": "metric_strip",
            "takeaway": "callout",
            "evidence_footer": "summary",
            "insight_panel": "callout",
            "definition_panel": "summary",
        }
        return mapping.get(variant, fallback)

    def _inset(self, rect: tuple[float, float, float, float], pad: float) -> tuple[float, float, float, float]:
        left, top, width, height = rect
        h_pad = min(pad, width / 8)
        v_pad = min(pad, height / 8)
        return (left + h_pad, top + v_pad, max(width - 2 * h_pad, 0.2), max(height - 2 * v_pad, 0.2))

    def _theme(self, deck_ir: dict[str, Any], recipe: dict[str, Any] | None = None) -> dict[str, Any]:
        theme = dict(deck_ir.get("theme") or {})
        layout = dict((recipe or {}).get("layout") or {})
        palette = layout.get("palette")
        if isinstance(palette, dict):
            theme.update(self._safe_palette(palette))
        theme.setdefault("background_color", "#F7F4EE")
        theme.setdefault("primary_color", "#134E8E")
        theme.setdefault("secondary_color", "#C00707")
        theme.setdefault("accent_color", "#FFB33F")
        theme.setdefault("text_color", "#1F2937")
        theme.setdefault("surface_fill", "#FFFFFF")
        theme.setdefault("surface_alt_fill", "#F9FAFB")
        theme.setdefault("muted_fill", "#F8FAFC")
        theme.setdefault("border_color", theme.get("primary_color", "#134E8E"))
        theme.setdefault("strong_band_fill", theme.get("text_color", "#1F2937"))
        theme.setdefault("takeaway_fill", theme.get("surface_alt_fill", "#EFF6FF"))
        theme.setdefault("footer_fill", theme.get("surface_alt_fill", "#F9FAFB"))
        theme.setdefault("panel_line_width", 1.4 if str(layout.get("density") or "").lower() == "dense" else 1.0)
        theme.setdefault("font_family", "Aptos")
        theme["font_family"] = self._safe_qwen_font_family(theme.get("font_family"))
        theme["title_font_family"] = self._safe_qwen_title_font_family(theme.get("font_family"))
        theme["fit_text"] = True
        theme["min_body_font_size"] = 15
        theme["min_bullet_font_size"] = 13
        theme["min_card_body_font_size"] = 13
        theme["caption_font_size"] = 12
        theme["footer_font_size"] = 11
        return theme

    def _safe_palette(self, palette: dict[str, Any]) -> dict[str, str]:
        allowed = {
            "background_color",
            "primary_color",
            "secondary_color",
            "accent_color",
            "text_color",
            "surface_fill",
            "surface_alt_fill",
            "muted_fill",
            "border_color",
            "strong_band_fill",
            "takeaway_fill",
            "footer_fill",
        }
        result: dict[str, str] = {}
        for key, value in palette.items():
            color = str(value or "").strip()
            if str(key) in allowed and self._is_hex_color(color):
                result[str(key)] = color.upper()
        if "background_color" in result and "text_color" in result:
            if self._contrast_ratio(result["background_color"], result["text_color"]) < 4.5:
                result["text_color"] = self._project_text_color_for_contrast(
                    result["text_color"],
                    result["background_color"],
                    min_ratio=4.5,
                )
        return result

    @staticmethod
    def _is_hex_color(value: str) -> bool:
        return bool(re.match(r"^#[0-9A-Fa-f]{6}$", value))

    @staticmethod
    def _contrast_ratio(color_a: str, color_b: str) -> float:
        def luminance(color: str) -> float:
            raw = color.lstrip("#")
            channels = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
            adjusted = [
                channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

        lighter = max(luminance(color_a), luminance(color_b))
        darker = min(luminance(color_a), luminance(color_b))
        return (lighter + 0.05) / (darker + 0.05)

    def _project_text_color_for_contrast(self, text_color: str, background_color: str, *, min_ratio: float) -> str:
        if self._contrast_ratio(text_color, background_color) >= min_ratio:
            return text_color.upper()
        raw = text_color.lstrip("#")
        channels = [int(raw[i : i + 2], 16) for i in (0, 2, 4)]
        candidates: list[tuple[float, int, str]] = []
        for direction in (-1, 1):
            for step in range(1, 256):
                projected = [
                    max(0, min(255, channel + direction * step))
                    for channel in channels
                ]
                if projected == channels:
                    continue
                color = "#" + "".join(f"{channel:02X}" for channel in projected)
                contrast = self._contrast_ratio(color, background_color)
                if contrast >= min_ratio:
                    candidates.append((contrast, step, color))
                    break
        if candidates:
            return min(candidates, key=lambda item: (item[1], item[0]))[2]
        return "#111111" if self._contrast_ratio("#111111", background_color) >= min_ratio else "#FFFFFF"

    def _safe_qwen_font_family(self, font_family: Any) -> str:
        requested = str(font_family or "").strip()
        if not requested or requested in {"Aptos", "Aptos Display", "Calibri"}:
            return "Noto Sans CJK SC"
        safe_fonts = {
            "Arial",
            "Inter",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "Microsoft YaHei",
            "SimHei",
        }
        if requested in safe_fonts:
            return requested
        return "Noto Sans CJK SC"

    def _safe_qwen_title_font_family(self, font_family: Any) -> str:
        requested = self._safe_qwen_font_family(font_family)
        if requested in {"Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "SimHei"}:
            return requested
        return f"{requested} Display"

    def _write_recipe_artifact(
        self,
        artifact_dir: str,
        slide_ir: dict[str, Any],
        recipe: dict[str, Any],
        index: int,
    ) -> None:
        directory = Path(artifact_dir)
        directory.mkdir(parents=True, exist_ok=True)
        slide_id = slide_ir.get("slide_id") or f"slide_{index + 1:02d}"
        path = directory / f"{slide_id}.recipe.json"
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
