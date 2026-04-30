"""Schema helpers for Qwen recipe-based PPT rendering."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from typing import Any


RECIPE_VERSION = "qwen_recipe_v1"

ALLOWED_LAYOUT_KINDS = {
    "title_body",
    "two_column",
    "comparison",
    "metric_focus",
    "process_flow",
    "quote_focus",
    "visual_focus",
}
ALLOWED_ELEMENT_VARIANTS = {
    "headline",
    "subtitle",
    "kicker",
    "section_label",
    "insight_panel",
    "definition_panel",
    "summary_panel",
    "compact_bullets",
    "quote_card",
    "metric_cards",
    "takeaway",
    "evidence_footer",
}
ALLOWED_COMPOSITION_VARIANTS = {
    "card_grid",
    "comparison_matrix",
    "timeline",
    "process_diagram",
    "concept_diagram",
    "icon_metaphor",
    "image_or_placeholder",
    "captioned_visual",
    "quote_wall",
    "metrics_strip",
    "table_matrix",
    "chart_takeaway",
    "visual_observations",
    "callout_stack",
    "statement_ladder",
    "before_after_bridge",
    "numbered_cards",
    "cluster_map",
    "image_caption_overlay",
    "framework_grid",
    "problem_solution",
    "cycle_loop",
    "pyramid",
    "funnel",
    "evidence_cards",
    "dense_text_columns",
    "visual_compare",
    "rendered_visual",
}
VISUAL_SOURCE_COMPOSITION_VARIANTS = {
    "image_or_placeholder",
    "captioned_visual",
    "image_caption_overlay",
    "visual_compare",
    "visual_observations",
    "rendered_visual",
}
ALLOWED_PRIMITIVE_TYPES = {"divider", "badge", "arrow", "accent_bar"}
ALLOWED_SOURCES = {
    "slide.title",
    "slide.subtitle",
    "slide.core_message",
    "points",
}
SOURCE_PATTERN = re.compile(r"^(blocks|visuals)\[(\d+)\](?:\.(content|items))?$")
ALLOWED_PALETTE_KEYS = {
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
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class QwenRecipeError(ValueError):
    """Raised when a Qwen recipe cannot be parsed or normalized."""


def parse_qwen_recipe_response(raw: str, *, slide_ir: dict[str, Any]) -> dict[str, Any]:
    """Parse and normalize a raw Qwen recipe response.

    The local Qwen JSON mode can return either a full object or an object body
    fragment. This function accepts both and returns the normalized contract.
    """

    data = _loads_recipe_json(raw)
    if "layout" in data and "version" not in data:
        data["version"] = RECIPE_VERSION
    normalized = normalize_recipe(data, slide_ir=slide_ir)
    errors = validate_recipe(normalized, slide_ir=slide_ir)
    if errors:
        raise QwenRecipeError("; ".join(errors))
    return normalized


def normalize_recipe(recipe: dict[str, Any], *, slide_ir: dict[str, Any]) -> dict[str, Any]:
    layout_payload = recipe.get("layout") if isinstance(recipe.get("layout"), dict) else {}
    region_payload = recipe.get("regions")
    if not isinstance(region_payload, list) and isinstance(layout_payload.get("regions"), list):
        region_payload = layout_payload.get("regions")
    normalized: dict[str, Any] = {
        "version": RECIPE_VERSION,
        "layout": _normalize_layout(recipe.get("layout"), slide_ir=slide_ir),
        "regions": _normalize_regions(region_payload),
        "elements": [],
        "compositions": [],
        "primitives": [],
        "emphasis": _normalize_emphasis(recipe.get("emphasis")),
        "constraints": _normalize_constraints(recipe.get("constraints")),
    }
    normalized["elements"] = _normalize_elements(recipe.get("elements"), normalized["regions"])
    normalized["compositions"] = _normalize_compositions(recipe.get("compositions"))
    normalized["primitives"] = _normalize_primitives(recipe.get("primitives"))
    return apply_recipe_harness(normalized, slide_ir=slide_ir)


def apply_recipe_harness(recipe: dict[str, Any], *, slide_ir: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply deterministic recipe safety repairs after model generation.

    This keeps Qwen expressive while preventing common display failures such as
    overlapping regions, out-of-bounds rectangles, and tiny unusable slots.
    """

    adjusted = deepcopy(recipe)
    regions = adjusted.get("regions", [])
    if not isinstance(regions, list):
        adjusted["regions"] = []
        regions = []

    adjustments: list[str] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        before = list(region.get("rect") or [])
        region["rect"] = _normalize_rect(region.get("rect"))
        if region["rect"] != before:
            adjustments.append(f"clamped:{region.get('id', '')}")

    adjustments.extend(_drop_footer_overloads(adjusted, regions, slide_ir=slide_ir))
    adjustments.extend(_infer_missing_structural_compositions(adjusted, regions, slide_ir=slide_ir))
    adjustments.extend(_apply_visual_source_requirements(adjusted, regions, slide_ir=slide_ir))
    adjustments.extend(_apply_visual_prominence_requirements(adjusted, regions))
    adjustments.extend(_apply_single_item_variant_requirements(adjusted, slide_ir=slide_ir))
    adjustments.extend(_apply_duplicate_source_suppression(adjusted))
    adjustments.extend(_apply_variant_region_requirements(adjusted, regions))
    adjustments.extend(_apply_text_capacity_region_requirements(adjusted, regions, slide_ir=slide_ir))
    adjustments.extend(_apply_title_stack_requirements(regions))

    if _has_region_overlaps(regions):
        solved = _solve_region_constraints(regions)
        adjustments.append("constraint_projection" if solved else "constraint_projection_fallback_grid")
        adjustments.extend(_apply_title_stack_requirements(regions))

    constraints = adjusted.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {"no_new_claims": True}
    constraints.setdefault("no_new_claims", True)
    constraints["harness_adjustments"] = adjustments
    adjusted["constraints"] = constraints
    for region in regions:
        if isinstance(region, dict):
            region.pop("_harness_min_size", None)
    return adjusted


def validate_recipe(recipe: dict[str, Any], *, slide_ir: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if recipe.get("version") != RECIPE_VERSION:
        errors.append("recipe version must be qwen_recipe_v1")
    region_ids = {region.get("id") for region in recipe.get("regions", [])}
    if not region_ids:
        errors.append("recipe must define at least one region")

    for element in recipe.get("elements", []):
        if element.get("region") not in region_ids:
            errors.append(f"element references unknown region: {element.get('region')}")
        if not _is_allowed_source(element.get("source", "")):
            errors.append(f"element source is not allowed: {element.get('source')}")

    for composition in recipe.get("compositions", []):
        if composition.get("region") not in region_ids:
            errors.append(f"composition references unknown region: {composition.get('region')}")
        source = composition.get("source", "")
        if source and not _is_allowed_source(source):
            errors.append(f"composition source is not allowed: {source}")

    slide_type_value = slide_ir.get("type")
    slide_type = str(slide_type_value or "").lower()
    if slide_type_value is not None and slide_type not in {"title", "cover", "closing", "section_divider"}:
        body_sources = ("blocks[", "points", "slide.core_message")
        has_body = any(
            any(str(item.get("source", "")).startswith(prefix) for prefix in body_sources)
            for item in recipe.get("elements", []) + recipe.get("compositions", [])
        )
        adjustments = (recipe.get("constraints") or {}).get("harness_adjustments") or []
        footer_overload_dropped = any(str(item).startswith("drop_footer_") for item in adjustments)
        if not has_body and not footer_overload_dropped:
            errors.append("content slides must render body content from blocks, points, or slide.core_message")
    return errors


def build_default_recipe(slide_ir: dict[str, Any]) -> dict[str, Any]:
    layout = slide_ir.get("layout", {}) or {}
    layout_kind = str(layout.get("name") or "two_column")
    regions = _regions_from_ir_slots(slide_ir)
    if not regions:
        regions = [
            {"id": "title", "role": "title", "rect": [0.06, 0.04, 0.88, 0.14]},
            {"id": "body", "role": "content", "rect": [0.06, 0.22, 0.42, 0.58]},
            {"id": "supporting_visual", "role": "visual", "rect": [0.54, 0.22, 0.4, 0.58]},
        ]

    body_region = _first_region_id(regions, roles={"content", "body"}, fallback="body")
    title_region = _first_region_id(regions, roles={"title"}, fallback=regions[0]["id"])
    visual_region = _first_region_id(regions, roles={"visual"}, fallback="")

    elements: list[dict[str, Any]] = [
        {"type": "text", "region": title_region, "source": "slide.title", "variant": "headline"}
    ]
    for index, block in enumerate(slide_ir.get("blocks", [])[:4]):
        variant = _variant_for_block(block)
        elements.append({"type": "block", "region": block.get("slot_id") or body_region, "source": f"blocks[{index}]", "variant": variant})
    if not slide_ir.get("blocks") and slide_ir.get("core_message"):
        elements.append({"type": "text", "region": body_region, "source": "slide.core_message", "variant": "summary_panel"})

    compositions: list[dict[str, Any]] = []
    if visual_region and slide_ir.get("visuals"):
        compositions.append(
            {"type": "visual", "region": visual_region, "source": "visuals[0]", "variant": "image_or_placeholder"}
        )
    elif visual_region and str(layout_kind).lower() in {"two_column", "visual_focus"}:
        compositions.append(
            {"type": "concept_diagram", "region": visual_region, "source": "points", "variant": "concept_diagram"}
        )

    return {
        "version": RECIPE_VERSION,
        "layout": {
            "kind": layout_kind if layout_kind in ALLOWED_LAYOUT_KINDS else "two_column",
            "density": layout.get("density", "balanced"),
            "style": "academic_clean",
            "reading_order": [region["id"] for region in regions],
        },
        "regions": regions,
        "elements": elements,
        "compositions": compositions,
        "primitives": [],
        "emphasis": [],
        "constraints": {"no_new_claims": True},
    }


def _loads_recipe_json(raw: str) -> dict[str, Any]:
    text = _extract_json_text(raw)
    candidates = [text]
    stripped = text.strip()
    if not stripped.startswith("{"):
        candidates.append("{" + stripped)
    if stripped.startswith("{") and '"regions"' in stripped and re.match(r'^\{\s*"(kind|type|name)"\s*:', stripped):
        candidates.append('{"layout":' + stripped)
    if stripped.startswith('"layout"'):
        candidates.append('{"version":"qwen_recipe_v1",' + stripped)
    if '"layout"' in stripped and not stripped.startswith("{"):
        candidates.append("{" + stripped.rstrip().rstrip("}"))

    for candidate in candidates:
        for repaired in _candidate_repairs(candidate):
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    raise QwenRecipeError(f"Unable to parse qwen recipe JSON: {raw[:240]}")


def _extract_json_text(raw: str) -> str:
    text = str(raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    prefix = text[:start].strip() if start > 0 else ""
    if start > 0 and not prefix.startswith('"'):
        text = text[start:]
    return text


def _candidate_repairs(candidate: str) -> list[str]:
    text = re.sub(r",(?=\s*[}\]])", "", candidate.strip())
    repairs = [text]
    if text.count("{") > text.count("}"):
        repairs.append(text + ("}" * (text.count("{") - text.count("}"))))
    if text.count("[") > text.count("]"):
        repairs.append(text + ("]" * (text.count("[") - text.count("]"))))
    return repairs


def _normalize_layout(layout: Any, *, slide_ir: dict[str, Any]) -> dict[str, Any]:
    layout = deepcopy(layout) if isinstance(layout, dict) else {}
    kind = str(layout.get("kind") or layout.get("type") or layout.get("name") or slide_ir.get("layout", {}).get("name") or "two_column")
    if kind not in ALLOWED_LAYOUT_KINDS:
        kind = "two_column"
    style = layout.get("style") or "academic_clean"
    if isinstance(style, dict):
        normalized_style: str | dict[str, str] = {
            str(key): str(value)
            for key, value in style.items()
            if str(key).strip() and str(value).strip()
        }
    else:
        normalized_style = str(style)
    return {
        "kind": kind,
        "density": str(layout.get("density") or slide_ir.get("layout", {}).get("density") or "balanced"),
        "style": normalized_style,
        "palette": _normalize_palette(layout.get("palette")),
        "reading_order": [str(item) for item in layout.get("reading_order", []) if str(item).strip()],
    }


def _normalize_palette(palette: Any) -> dict[str, str]:
    if not isinstance(palette, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in palette.items():
        normalized_key = str(key or "").strip()
        normalized_value = str(value or "").strip()
        if normalized_key in ALLOWED_PALETTE_KEYS and HEX_COLOR_RE.match(normalized_value):
            result[normalized_key] = normalized_value.upper()
    return result


def _normalize_regions(regions: Any) -> list[dict[str, Any]]:
    result = []
    if not isinstance(regions, list):
        return result
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("id") or region.get("slot") or f"region_{index + 1}").strip()
        if not region_id:
            continue
        result.append(
            {
                "id": region_id,
                "role": str(region.get("role") or "content"),
                "rect": _normalize_rect(region.get("rect")),
            }
        )
    return result


def _normalize_elements(elements: Any, regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    region_ids = {region["id"] for region in regions}
    default_region = regions[0]["id"] if regions else "body"
    result = []
    if not isinstance(elements, list):
        return result
    for item in elements:
        if not isinstance(item, dict):
            continue
        variant = str(item.get("variant") or item.get("type") or "summary_panel")
        if variant not in ALLOWED_ELEMENT_VARIANTS:
            variant = _coerce_element_variant(variant)
        source = str(item.get("source") or "").strip()
        if not _is_allowed_source(source):
            continue
        region = str(item.get("region") or item.get("slot") or default_region)
        if region not in region_ids:
            region = default_region
        result.append(
            {
                "type": _element_type_for_variant(variant),
                "region": region,
                "source": source,
                "variant": variant,
            }
        )
    return result


def _normalize_compositions(compositions: Any) -> list[dict[str, Any]]:
    result = []
    if not isinstance(compositions, list):
        return result
    for item in compositions:
        if not isinstance(item, dict):
            continue
        variant = str(item.get("variant") or item.get("type") or "")
        if variant not in ALLOWED_COMPOSITION_VARIANTS:
            continue
        source = str(item.get("source") or "")
        if source and not _is_allowed_source(source):
            continue
        result.append(
            {
                "type": str(item.get("type") or variant),
                "region": str(item.get("region") or ""),
                "source": source,
                "variant": variant,
            }
        )
    return result


def _normalize_primitives(primitives: Any) -> list[dict[str, Any]]:
    result = []
    if not isinstance(primitives, list):
        return result
    for item in primitives:
        if not isinstance(item, dict):
            continue
        primitive_type = str(item.get("type") or "")
        if primitive_type not in ALLOWED_PRIMITIVE_TYPES:
            continue
        normalized = {
            "type": primitive_type,
            "region": item.get("region", ""),
            "style": str(item.get("style") or item.get("variant") or "primary"),
        }
        if "text" in item:
            normalized["text"] = str(item.get("text") or "")
        result.append(normalized)
    return result


def _normalize_emphasis(emphasis: Any) -> list[dict[str, str]]:
    result = []
    if not isinstance(emphasis, list):
        return result
    for item in emphasis:
        if not isinstance(item, dict):
            continue
        if item.get("text"):
            result.append({"text": str(item.get("text")), "style": str(item.get("style") or "accent_bold")})
        elif item.get("element_id"):
            style_bits = [str(item.get("level") or "primary"), str(item.get("method") or "emphasis")]
            result.append({"target": str(item.get("element_id")), "style": "_".join(style_bits)})
    return result


def _normalize_constraints(constraints: Any) -> dict[str, Any]:
    result = {"no_new_claims": True}
    if isinstance(constraints, dict):
        result.update({str(key): value for key, value in constraints.items() if isinstance(key, str)})
    return result


def _normalize_rect(rect: Any) -> list[float]:
    values = list(rect)[:4] if isinstance(rect, (list, tuple)) else [0.06, 0.22, 0.88, 0.58]
    while len(values) < 4:
        values.append(0.1)
    x, y, w, h = [max(0.0, min(float(value), 1.0)) for value in values]
    w = max(0.02, min(w, 1.0 - x))
    h = max(0.02, min(h, 1.0 - y))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def _has_region_overlaps(regions: list[dict[str, Any]]) -> bool:
    valid = [region for region in regions if isinstance(region, dict)]
    for index, region in enumerate(valid):
        for other in valid[index + 1:]:
            if _rects_overlap(region.get("rect", []), other.get("rect", [])):
                return True
    return False


def _rects_overlap(first: Any, second: Any, *, gap: float = 0.012) -> bool:
    if not isinstance(first, list) or not isinstance(second, list) or len(first) < 4 or len(second) < 4:
        return False
    ax, ay, aw, ah = [float(value) for value in first[:4]]
    bx, by, bw, bh = [float(value) for value in second[:4]]
    return not (
        ax + aw + gap <= bx
        or bx + bw + gap <= ax
        or ay + ah + gap <= by
        or by + bh + gap <= ay
    )


def _solve_region_constraints(regions: list[dict[str, Any]], *, gap: float = 0.012) -> bool:
    valid = [region for region in regions if isinstance(region, dict)]
    if len(valid) < 2:
        return True

    for region in valid:
        region["rect"] = _project_region_rect(region, region.get("rect", []))

    for _iteration in range(80):
        overlaps = [
            (first, second)
            for index, first in enumerate(valid)
            for second in valid[index + 1:]
            if _rects_overlap(first.get("rect", []), second.get("rect", []), gap=gap)
        ]
        if not overlaps:
            return True
        for first, second in overlaps:
            _separate_region_pair(first, second, gap=gap)

    if _has_region_overlaps(valid):
        _repack_overlapping_regions(valid)
        return False
    return True


def _project_region_rect(region: dict[str, Any], rect: Any) -> list[float]:
    x, y, w, h = _normalize_rect(rect)
    min_w, min_h = _minimum_region_size(region)
    w = min(max(w, min_w), 0.94)
    h = min(max(h, min_h), 0.9)
    x = min(max(x, 0.02), 0.98 - w)
    y = min(max(y, 0.02), 0.98 - h)
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def _infer_missing_structural_compositions(
    recipe: dict[str, Any],
    regions: list[dict[str, Any]],
    *,
    slide_ir: dict[str, Any] | None,
) -> list[str]:
    if len((slide_ir or {}).get("visuals", []) or []) < 2:
        return []
    compositions = recipe.get("compositions")
    if not isinstance(compositions, list):
        compositions = []
        recipe["compositions"] = compositions
    if any(isinstance(item, dict) and item.get("variant") == "visual_compare" for item in compositions):
        return []
    for region in regions:
        text = f"{region.get('id', '')} {region.get('role', '')}".lower()
        if "visual_compare" not in text:
            continue
        region_id = str(region.get("id") or "")
        if not region_id:
            continue
        compositions.append(
            {
                "type": "visual_compare",
                "region": region_id,
                "source": "visuals[0]",
                "variant": "visual_compare",
            }
        )
        return [f"inferred_visual_compare:{region_id}"]
    return []


def _apply_visual_source_requirements(
    recipe: dict[str, Any],
    regions: list[dict[str, Any]],
    *,
    slide_ir: dict[str, Any] | None,
) -> list[str]:
    visuals = (slide_ir or {}).get("visuals", []) or []
    if not visuals:
        return []
    compositions = recipe.get("compositions")
    if not isinstance(compositions, list):
        compositions = []
        recipe["compositions"] = compositions
    adjustments: list[str] = []
    has_visual_source = False
    for item in compositions:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        if not source.startswith("visuals["):
            continue
        has_visual_source = True
        variant = str(item.get("variant") or "")
        if variant not in VISUAL_SOURCE_COMPOSITION_VARIANTS:
            item["type"] = "visual"
            item["variant"] = "rendered_visual"
            adjustments.append(f"visual_source_variant:{item.get('region', '')}")

    if has_visual_source:
        return adjustments
    visual_region = _first_visual_region(regions)
    if not visual_region and _has_displayable_visual(visuals):
        visual_region = _create_visual_led_region(recipe, regions)
        if visual_region:
            adjustments.append(f"inferred_visual_region:{visual_region.get('id', '')}")
            compositions = recipe.get("compositions")
            if not isinstance(compositions, list):
                compositions = []
                recipe["compositions"] = compositions
    if not visual_region:
        return adjustments
    compositions.append(
        {
            "type": "visual",
            "region": str(visual_region.get("id") or ""),
            "source": "visuals[0]",
            "variant": "rendered_visual",
        }
    )
    adjustments.append(f"inferred_visual_render:{visual_region.get('id', '')}")
    return adjustments


def _has_displayable_visual(visuals: list[Any]) -> bool:
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        candidate = visual.get("selected_candidate") or visual.get("resolved_candidate")
        if isinstance(candidate, dict) and str(candidate.get("path") or candidate.get("relative_path") or "").strip():
            return True
        if str(visual.get("path") or visual.get("image_path") or "").strip():
            return True
    return False


def _apply_visual_prominence_requirements(recipe: dict[str, Any], regions: list[dict[str, Any]]) -> list[str]:
    region_map = {
        str(region.get("id")): region
        for region in regions
        if isinstance(region, dict) and str(region.get("id") or "").strip()
    }
    adjustments: list[str] = []
    for item in recipe.get("compositions", []) or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        variant = str(item.get("variant") or "")
        if not source.startswith("visuals[") or variant not in VISUAL_SOURCE_COMPOSITION_VARIANTS:
            continue
        region_id = str(item.get("region") or "")
        region = region_map.get(region_id)
        if not region or _region_kind(region) in {"title", "footer"}:
            continue
        before_rect = list(region.get("rect") or [])
        before_role = str(region.get("role") or "")
        region["role"] = "visual"
        _set_harness_min_size(region, 0.42, 0.38)
        region["rect"] = _ensure_min_rect(region.get("rect"), min_w=0.42, min_h=0.38)
        if region["rect"] != before_rect or before_role != "visual":
            adjustments.append(f"visual_prominence:{region_id}")
    return adjustments


def _drop_footer_overloads(
    recipe: dict[str, Any],
    regions: list[dict[str, Any]],
    *,
    slide_ir: dict[str, Any] | None,
) -> list[str]:
    if not slide_ir:
        return []
    region_map = {
        str(region.get("id")): region
        for region in regions
        if isinstance(region, dict) and str(region.get("id") or "").strip()
    }
    adjustments: list[str] = []
    for key in ("elements", "compositions"):
        items = recipe.get(key)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            if not isinstance(item, dict):
                continue
            region = region_map.get(str(item.get("region") or ""))
            variant = str(item.get("variant") or "")
            if region and _region_kind(region) == "footer" and _footer_item_overloads(region, variant, str(item.get("source") or ""), slide_ir):
                adjustments.append(f"drop_footer_{variant}:{region.get('id', '')}")
                continue
            kept.append(item)
        recipe[key] = kept
    return adjustments


def _footer_item_overloads(region: dict[str, Any], variant: str, source: str, slide_ir: dict[str, Any]) -> bool:
    if variant not in {"takeaway", "evidence_footer", "summary_panel", "insight_panel", "definition_panel", "compact_bullets", "dense_text_columns", "table_matrix"}:
        return False
    rect = _normalize_rect(region.get("rect"))
    if rect[3] > 0.09:
        return False
    units = _text_units_for_source(slide_ir, source)
    weighted = sum(_text_weight(text) for text in units)
    return weighted > 24


def _create_visual_led_region(recipe: dict[str, Any], regions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not regions:
        return None
    visual_id = "qwen_visual"
    if any(isinstance(region, dict) and region.get("id") == visual_id for region in regions):
        return next(region for region in regions if isinstance(region, dict) and region.get("id") == visual_id)

    body_regions = [
        region
        for region in regions
        if isinstance(region, dict) and _region_kind(region) == "content"
    ]
    if len(body_regions) >= 4:
        drop_region = body_regions[-1]
        _remove_region_and_items(recipe, regions, str(drop_region.get("id") or ""))
    body_regions = [
        region
        for region in regions
        if isinstance(region, dict) and _region_kind(region) == "content"
    ]
    if body_regions:
        anchor = max(body_regions, key=lambda region: float((region.get("rect") or [0, 0, 0, 0])[2]) * float((region.get("rect") or [0, 0, 0, 0])[3]))
        anchor_rect = _normalize_rect(anchor.get("rect"))
        visual_left = 0.06 if anchor_rect[0] < 0.5 else 0.52
        visual_top = max(0.2, anchor_rect[1])
    else:
        visual_left = 0.06
        visual_top = 0.22
    visual_region = {
        "id": visual_id,
        "role": "visual",
        "rect": [visual_left, visual_top, 0.42, 0.38],
    }
    regions.append(visual_region)
    recipe["regions"] = regions
    return visual_region


def _remove_region_and_items(recipe: dict[str, Any], regions: list[dict[str, Any]], region_id: str) -> None:
    if not region_id:
        return
    regions[:] = [
        region
        for region in regions
        if not (isinstance(region, dict) and str(region.get("id") or "") == region_id)
    ]
    for key in ("elements", "compositions", "primitives"):
        items = recipe.get(key)
        if isinstance(items, list):
            recipe[key] = [
                item
                for item in items
                if not (isinstance(item, dict) and str(item.get("region") or "") == region_id)
            ]


def _first_visual_region(regions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for region in regions:
        if not isinstance(region, dict):
            continue
        text = f"{region.get('role', '')} {region.get('id', '')}".lower()
        if "visual" in text or "image" in text or "figure" in text:
            return region
    return None


def _apply_single_item_variant_requirements(
    recipe: dict[str, Any],
    *,
    slide_ir: dict[str, Any] | None,
) -> list[str]:
    if not slide_ir:
        return []
    elements = recipe.get("elements")
    compositions = recipe.get("compositions")
    if not isinstance(elements, list) or not isinstance(compositions, list):
        return []
    adjustments: list[str] = []
    kept_compositions: list[dict[str, Any]] = []
    for item in compositions:
        if not isinstance(item, dict):
            continue
        variant = str(item.get("variant") or "")
        source = str(item.get("source") or "")
        units = _text_units_for_source(slide_ir, source)
        if source.startswith("visuals["):
            kept_compositions.append(item)
            continue
        if variant == "numbered_cards" and len(units) < 2:
            elements.append(
                {
                    "type": "text",
                    "region": str(item.get("region") or ""),
                    "source": source,
                    "variant": "takeaway",
                }
            )
            adjustments.append("single_item_variant:numbered_cards")
            continue
        kept_compositions.append(item)
    recipe["compositions"] = kept_compositions
    return adjustments


def _apply_duplicate_source_suppression(recipe: dict[str, Any]) -> list[str]:
    adjustments: list[str] = []
    for key in ("elements", "compositions"):
        if not isinstance(recipe.get(key), list):
            recipe[key] = []
    nodes: list[tuple[str, int, dict[str, Any]]] = []
    for collection in ("elements", "compositions"):
        for index, item in enumerate(recipe.get(collection, []) or []):
            if isinstance(item, dict):
                nodes.append((collection, index, item))

    remove: set[tuple[str, int]] = set()
    grouped: dict[tuple[str, str], list[tuple[str, int, dict[str, Any]]]] = {}
    for node in nodes:
        item = node[2]
        region = str(item.get("region") or "")
        family = _source_family(str(item.get("source") or ""))
        if region and (family.startswith("blocks[") or family.startswith("visuals[")):
            grouped.setdefault((region, family), []).append(node)

    for (_region, family), family_nodes in grouped.items():
        if len(family_nodes) < 2:
            continue
        winner = max(family_nodes, key=lambda node: _render_node_priority(node[2], node[0]))
        for node in family_nodes:
            if node is not winner:
                remove.add((node[0], node[1]))
        adjustments.append(f"duplicate_source:{family}")

    for key in ("elements", "compositions"):
        recipe[key] = [
            item
            for index, item in enumerate(recipe.get(key, []) or [])
            if (key, index) not in remove
        ]
    return adjustments


def _source_family(source: str) -> str:
    match = SOURCE_PATTERN.match(source)
    if match and match.group(1) in {"blocks", "visuals"}:
        return f"{match.group(1)}[{match.group(2)}]"
    return source


def _render_node_priority(item: dict[str, Any], collection: str) -> int:
    variant = str(item.get("variant") or "")
    priorities = {
        "metric_dashboard": 130,
        "issue_matrix": 125,
        "comparison_scorecard": 120,
        "architecture_map": 120,
        "workflow_ribbon": 115,
        "evidence_cards": 105,
        "numbered_cards": 100,
        "dense_text_columns": 90,
        "rendered_visual": 88,
        "captioned_visual": 86,
        "image_caption_overlay": 84,
        "compact_bullets": 70,
        "takeaway": 65,
        "summary_panel": 60,
        "section_label": 40,
    }
    base = priorities.get(variant, 55)
    if collection == "compositions":
        base += 10
    source = str(item.get("source") or "")
    if SOURCE_PATTERN.match(source) and "." not in source:
        base += 5
    return base


def _apply_variant_region_requirements(recipe: dict[str, Any], regions: list[dict[str, Any]]) -> list[str]:
    region_map = {
        str(region.get("id")): region
        for region in regions
        if isinstance(region, dict) and str(region.get("id") or "").strip()
    }
    requirements: dict[str, tuple[float, float]] = {}
    for item in list(recipe.get("elements", []) or []) + list(recipe.get("compositions", []) or []):
        if not isinstance(item, dict):
            continue
        region_id = str(item.get("region") or "")
        region = region_map.get(region_id)
        variant = str(item.get("variant") or "")
        if variant == "takeaway" and region and _region_kind(region) == "footer":
            continue
        min_size = _minimum_size_for_variant(variant)
        if not region_id or min_size is None:
            continue
        current = requirements.get(region_id, (0.0, 0.0))
        requirements[region_id] = (max(current[0], min_size[0]), max(current[1], min_size[1]))

    adjustments: list[str] = []
    for region_id, min_size in requirements.items():
        region = region_map.get(region_id)
        if not region:
            continue
        before = list(region.get("rect") or [])
        _set_harness_min_size(region, min_size[0], min_size[1])
        region["rect"] = _ensure_min_rect(region.get("rect"), min_w=min_size[0], min_h=min_size[1])
        if region["rect"] != before:
            adjustments.append(f"min_region_size:{region_id}")
    return adjustments


def _apply_text_capacity_region_requirements(
    recipe: dict[str, Any],
    regions: list[dict[str, Any]],
    *,
    slide_ir: dict[str, Any] | None,
) -> list[str]:
    if not slide_ir:
        return []
    region_map = {
        str(region.get("id")): region
        for region in regions
        if isinstance(region, dict) and str(region.get("id") or "").strip()
    }
    requirements: dict[str, tuple[float, float]] = {}
    for item in list(recipe.get("elements", []) or []) + list(recipe.get("compositions", []) or []):
        if not isinstance(item, dict):
            continue
        region_id = str(item.get("region") or "")
        region = region_map.get(region_id)
        if not region:
            continue
        variant = str(item.get("variant") or "")
        if variant == "takeaway" and _region_kind(region) == "footer":
            continue
        source = str(item.get("source") or "")
        min_size = _minimum_text_capacity_for_item(variant, source, region.get("rect"), slide_ir)
        if min_size is None:
            continue
        current = requirements.get(region_id, (0.0, 0.0))
        requirements[region_id] = (max(current[0], min_size[0]), max(current[1], min_size[1]))

    adjustments: list[str] = []
    for region_id, min_size in requirements.items():
        region = region_map.get(region_id)
        if not region:
            continue
        before = list(region.get("rect") or [])
        _set_harness_min_size(region, min_size[0], min_size[1])
        region["rect"] = _ensure_min_rect(region.get("rect"), min_w=min_size[0], min_h=min_size[1])
        if region["rect"] != before:
            adjustments.append(f"text_capacity:{region_id}")
    return adjustments


def _apply_title_stack_requirements(regions: list[dict[str, Any]], *, gap: float = 0.012) -> list[str]:
    title_regions = [
        region
        for region in regions
        if isinstance(region, dict) and _is_primary_title_region(region)
    ]
    subtitle_regions = [
        region
        for region in regions
        if isinstance(region, dict) and _is_subtitle_region(region)
    ]
    if not title_regions or not subtitle_regions:
        return []
    title_bottom = max(float(region["rect"][1]) + float(region["rect"][3]) for region in title_regions)
    adjustments: list[str] = []
    for region in sorted(subtitle_regions, key=lambda item: float(item["rect"][1])):
        rect = list(region.get("rect") or [])
        if len(rect) < 4:
            continue
        target_y = title_bottom + gap
        if float(rect[1]) < target_y:
            rect[1] = min(target_y, max(0.02, 0.98 - float(rect[3])))
            region["rect"] = _project_region_rect(region, rect)
            adjustments.append(f"title_stack:{region.get('id', '')}")
        title_bottom = max(title_bottom, float(region["rect"][1]) + float(region["rect"][3]))
    return adjustments


def _is_primary_title_region(region: dict[str, Any]) -> bool:
    text = f"{region.get('role', '')} {region.get('id', '')}".lower()
    return ("title" in text or "headline" in text) and "subtitle" not in text and "kicker" not in text


def _is_subtitle_region(region: dict[str, Any]) -> bool:
    text = f"{region.get('role', '')} {region.get('id', '')}".lower()
    return "subtitle" in text or "kicker" in text


def _minimum_text_capacity_for_item(
    variant: str,
    source: str,
    rect: Any,
    slide_ir: dict[str, Any],
) -> tuple[float, float] | None:
    text_units = _text_units_for_source(slide_ir, source)
    if not text_units:
        return None
    x, _y, width_ratio, _height_ratio = _normalize_rect(rect)
    del x
    min_size = _minimum_size_for_variant(variant) or (0.18, 0.12)
    if variant == "headline":
        return max(min_size[0], 0.46), _estimated_text_height_ratio(
            [" ".join(text_units)],
            width_ratio,
            font_size=34,
            margin_inches=0.12,
            padding_inches=0.32,
            min_ratio=min_size[1],
            max_ratio=0.28,
        )
    if variant in {"subtitle", "kicker", "section_label"}:
        return max(min_size[0], 0.32), _estimated_text_height_ratio(
            [" ".join(text_units)],
            width_ratio,
            font_size=16,
            margin_inches=0.1,
            padding_inches=0.22,
            min_ratio=min_size[1],
            max_ratio=0.16,
        )
    if variant in {"summary_panel", "insight_panel", "definition_panel", "takeaway", "quote_card"}:
        return max(min_size[0], 0.34), _estimated_text_height_ratio(
            text_units,
            width_ratio,
            font_size=18 if variant == "quote_card" else 17,
            margin_inches=0.18,
            padding_inches=0.34,
            min_ratio=min_size[1],
            max_ratio=0.42,
        )
    if variant == "compact_bullets":
        return max(min_size[0], 0.38), _estimated_text_height_ratio(
            text_units,
            width_ratio,
            font_size=16,
            margin_inches=0.12,
            padding_inches=0.58,
            line_spacing=1.45,
            min_ratio=min_size[1],
            max_ratio=0.62,
        )
    if variant in {"evidence_cards", "dense_text_columns"}:
        column_count = min(max(len(text_units), 1), 4) if variant == "evidence_cards" else min(max(len(text_units), 1), 2)
        column_width_ratio = max((width_ratio - 0.02 * (column_count - 1)) / column_count, 0.16)
        max_lines = max(
            _estimate_wrapped_line_count(text, column_width_ratio * 13.33 - 0.24, 14)
            for text in text_units
        )
        height_inches = max_lines * 14 * 1.35 / 72.0 + 0.72
        min_height = 0.3 if variant == "dense_text_columns" else min_size[1]
        return max(min_size[0], 0.42), min(max(height_inches / 7.5, min_height), 0.48)
    if variant == "numbered_cards":
        card_count = min(max(len(text_units), 1), 4)
        card_width_ratio = max((width_ratio - 0.012 * (card_count - 1)) / card_count, 0.14)
        max_lines = max(
            _estimate_wrapped_line_count(text, card_width_ratio * 13.33 - 0.24, 14)
            for text in text_units
        )
        height_inches = max_lines * 14 * 1.25 / 72.0 + 0.86
        return max(min_size[0], 0.42), min(max(height_inches / 7.5, 0.3), 0.46)
    return None


def _estimated_text_height_ratio(
    text_units: list[str],
    width_ratio: float,
    *,
    font_size: int,
    margin_inches: float,
    padding_inches: float,
    min_ratio: float,
    max_ratio: float,
    line_spacing: float = 1.22,
) -> float:
    usable_width = max(width_ratio * 13.33 - 2 * margin_inches, 0.4)
    lines = sum(_estimate_wrapped_line_count(text, usable_width, font_size) for text in text_units)
    height_inches = lines * font_size * line_spacing / 72.0 + padding_inches
    return min(max(height_inches / 7.5, min_ratio), max_ratio)


def _estimate_wrapped_line_count(text: str, usable_width: float, font_size: int) -> int:
    if not text:
        return 1
    chars_per_line = max(int(usable_width * 6.0 * 12.0 / max(font_size, 1)), 4)
    lines = 0
    for raw_line in str(text).splitlines() or [""]:
        weighted = 0.0
        for char in raw_line.strip():
            weighted += 1.0 if ord(char) > 127 else 0.56
        lines += max(1, math.ceil(weighted / chars_per_line))
    return max(lines, 1)


def _text_weight(text: str) -> float:
    return sum(1.0 if ord(char) > 127 else 0.56 for char in str(text or ""))


def _text_units_for_source(slide_ir: dict[str, Any], source: str) -> list[str]:
    if source == "slide.title":
        return _clean_text_units([slide_ir.get("title")])
    if source == "slide.subtitle":
        return _clean_text_units([slide_ir.get("subtitle")])
    if source == "slide.core_message":
        return _clean_text_units([slide_ir.get("core_message")])
    if source == "points":
        points = _clean_text_units(slide_ir.get("points") or [])
        if points:
            return points
        fallback: list[Any] = []
        for block in slide_ir.get("blocks", []) or []:
            fallback.extend(block.get("items", []) or [])
            if block.get("content"):
                fallback.append(block.get("content"))
        if slide_ir.get("core_message"):
            fallback.insert(0, slide_ir.get("core_message"))
        return _clean_text_units(fallback)
    match = SOURCE_PATTERN.match(source)
    if not match or match.group(1) != "blocks":
        return []
    blocks = slide_ir.get("blocks", []) or []
    index = int(match.group(2))
    if not (0 <= index < len(blocks)) or not isinstance(blocks[index], dict):
        return []
    block = blocks[index]
    field = match.group(3)
    if field == "items":
        return _clean_text_units(block.get("items") or [])
    if field == "content":
        return _clean_text_units([block.get("content")])
    values: list[Any] = []
    if block.get("content"):
        values.append(block.get("content"))
    values.extend(block.get("items") or [])
    return _clean_text_units(values)


def _clean_text_units(values: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(values, list):
        values = [values]
    for value in values:
        text = _item_text(value)
        if text:
            result.append(text)
    return result


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("text", "content", "label", "value", "title"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return " ".join(str(value).strip() for value in item.values() if str(value).strip())
    return str(item or "").strip()


def _set_harness_min_size(region: dict[str, Any], min_w: float, min_h: float) -> None:
    current = region.get("_harness_min_size")
    if not isinstance(current, list) or len(current) < 2:
        current = [0.0, 0.0]
    region["_harness_min_size"] = [max(float(current[0]), min_w), max(float(current[1]), min_h)]


def _minimum_size_for_variant(variant: str) -> tuple[float, float] | None:
    if variant == "headline":
        return 0.46, 0.12
    if variant in {"subtitle", "kicker", "section_label"}:
        return 0.32, 0.08
    if variant in {"summary_panel", "insight_panel", "definition_panel", "takeaway"}:
        return 0.34, 0.16
    if variant in {"compact_bullets", "metric_cards"}:
        return 0.38, 0.34
    if variant == "numbered_cards":
        return 0.42, 0.24
    if variant == "evidence_footer":
        return 0.42, 0.08
    if variant in {"evidence_cards", "dense_text_columns", "framework_grid"}:
        return 0.42, 0.24
    if variant in {"pyramid", "funnel", "cycle_loop", "problem_solution"}:
        return 0.26, 0.24
    if variant in {"visual_compare", "visual_observations", "rendered_visual"}:
        return 0.42, 0.32
    if variant in {"table_matrix", "chart_takeaway", "metrics_strip"}:
        return 0.32, 0.18
    if variant in {"compact_bullets", "metric_cards", "quote_card"}:
        return 0.24, 0.12
    return None


def _ensure_min_rect(rect: Any, *, min_w: float, min_h: float) -> list[float]:
    x, y, w, h = _normalize_rect(rect)
    w = min(max(w, min_w), 0.96)
    h = min(max(h, min_h), 0.94)
    x = min(max(x, 0.02), 1.0 - w)
    y = min(max(y, 0.02), 0.98 - h)
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def _minimum_region_size(region: dict[str, Any]) -> tuple[float, float]:
    kind = _region_kind(region)
    if kind == "title":
        base = (0.28, 0.07)
    elif kind == "footer":
        base = (0.32, 0.04)
    elif "visual" in f"{region.get('role', '')} {region.get('id', '')}".lower():
        base = (0.18, 0.16)
    else:
        base = (0.18, 0.12)
    harness_min = region.get("_harness_min_size")
    if isinstance(harness_min, list) and len(harness_min) >= 2:
        return max(base[0], float(harness_min[0])), max(base[1], float(harness_min[1]))
    return base


def _region_weight(region: dict[str, Any]) -> float:
    kind = _region_kind(region)
    if kind == "title":
        return 8.0
    if kind == "footer":
        return 5.0
    if "visual" in f"{region.get('role', '')} {region.get('id', '')}".lower():
        return 1.2
    return 1.6


def _separate_region_pair(first: dict[str, Any], second: dict[str, Any], *, gap: float) -> None:
    ax, ay, aw, ah = [float(value) for value in first["rect"][:4]]
    bx, by, bw, bh = [float(value) for value in second["rect"][:4]]
    acx = ax + aw / 2
    bcx = bx + bw / 2
    acy = ay + ah / 2
    bcy = by + bh / 2

    x_push = (aw + bw) / 2 + gap - abs(acx - bcx)
    y_push = (ah + bh) / 2 + gap - abs(acy - bcy)
    if x_push <= 0 or y_push <= 0:
        return

    use_x = _axis_displacement_cost(first, second, x_push, axis="x") <= _axis_displacement_cost(first, second, y_push, axis="y")
    direction = -1.0
    if use_x:
        if acx > bcx:
            direction = 1.0
        _move_regions_apart(first, second, x_push, direction=direction, axis="x")
    else:
        if acy > bcy:
            direction = 1.0
        _move_regions_apart(first, second, y_push, direction=direction, axis="y")


def _axis_displacement_cost(first: dict[str, Any], second: dict[str, Any], push: float, *, axis: str) -> float:
    first_share, second_share = _movement_shares(first, second)
    first_room = _movement_room(first, axis=axis)
    second_room = _movement_room(second, axis=axis)
    overflow = max(first_share * push - first_room, 0.0) + max(second_share * push - second_room, 0.0)
    return push * push + overflow * 100.0


def _movement_shares(first: dict[str, Any], second: dict[str, Any]) -> tuple[float, float]:
    first_weight = _region_weight(first)
    second_weight = _region_weight(second)
    total = first_weight + second_weight
    return second_weight / total, first_weight / total


def _movement_room(region: dict[str, Any], *, axis: str) -> float:
    x, y, w, h = [float(value) for value in region["rect"][:4]]
    if axis == "x":
        return max(x - 0.02, 0.0) + max(0.98 - (x + w), 0.0)
    return max(y - 0.02, 0.0) + max(0.98 - (y + h), 0.0)


def _move_regions_apart(first: dict[str, Any], second: dict[str, Any], push: float, *, direction: float, axis: str) -> None:
    first_share, second_share = _movement_shares(first, second)
    first_rect = list(first["rect"])
    second_rect = list(second["rect"])
    offset = 0 if axis == "x" else 1
    first_rect[offset] += direction * first_share * push
    second_rect[offset] -= direction * second_share * push
    first["rect"] = _project_region_rect(first, first_rect)
    second["rect"] = _project_region_rect(second, second_rect)


def _repack_overlapping_regions(regions: list[dict[str, Any]]) -> None:
    title_regions = [region for region in regions if _region_kind(region) == "title"]
    footer_regions = [region for region in regions if _region_kind(region) == "footer"]
    candidate_visual_regions = [
        region
        for region in regions
        if _region_kind(region) not in {"title", "footer"} and _is_visual_region(region)
    ]
    non_footer_content_regions = [
        region
        for region in regions
        if _region_kind(region) not in {"title", "footer"}
    ]
    use_visual_band = bool(candidate_visual_regions and len(non_footer_content_regions) - len(candidate_visual_regions) >= 2)
    visual_regions = candidate_visual_regions if use_visual_band else []
    content_regions = [
        region
        for region in non_footer_content_regions
        if region not in visual_regions
    ]

    content_top = 0.2
    if title_regions:
        content_top = min(
            max(region["rect"][1] + region["rect"][3] + 0.04 for region in title_regions),
            0.32,
        )
    content_bottom = 0.9
    if footer_regions:
        content_bottom = max(
            min(region["rect"][1] - 0.03 for region in footer_regions),
            content_top + 0.2,
        )
    available_height = max(content_bottom - content_top, 0.24)

    visual_band_height = 0.0
    if use_visual_band:
        visual_anchor = visual_regions[0]
        original_x = float((visual_anchor.get("rect") or [0.06])[0])
        visual_left = 0.06 if original_x < 0.5 else 0.52
        text_left = 0.52 if visual_left < 0.5 else 0.06
        visual_top = content_top
        footer_reserved = 0.075 if footer_regions else 0.0
        max_visual_height = max(0.9 - footer_reserved - visual_top, 0.38)
        visual_height = min(max(available_height * 0.74, 0.38), max_visual_height, 0.56)
        visual_width = 0.42
        for region in visual_regions:
            region["rect"] = [
                round(visual_left, 4),
                round(visual_top, 4),
                round(visual_width, 4),
                round(visual_height, 4),
            ]
        content_left = text_left
        content_width = 0.42
        # Text in the opposite column does not geometrically conflict with the
        # side visual. Let it use the full readable column down to the footer;
        # clipping it to the visual bottom creates thin unreadable bands.
        content_bottom = 0.9
        available_height = max(content_bottom - content_top, 0.18)
    else:
        content_left = 0.06
        content_width = 0.88

    if not content_regions:
        return
    count = len(content_regions)
    columns = 1 if use_visual_band or count == 1 else 2
    rows = (count + columns - 1) // columns
    gap = 0.04
    cell_width = max((content_width - gap * (columns - 1)) / columns, 0.18)
    min_cell_height = 0.08 if use_visual_band else 0.14
    cell_height = max((available_height - gap * (rows - 1)) / rows, min_cell_height)
    for index, region in enumerate(content_regions):
        row = index // columns
        column = index % columns
        region["rect"] = [
            round(content_left + column * (cell_width + gap), 4),
            round(content_top + row * (cell_height + gap), 4),
            round(cell_width, 4),
            round(cell_height, 4),
        ]

    for index, region in enumerate(footer_regions):
        footer_y = 0.9 + index * 0.055
        if use_visual_band:
            visual_bottom = max(float(region_item["rect"][1]) + float(region_item["rect"][3]) for region_item in visual_regions)
            footer_y = max(visual_bottom + 0.02 + index * 0.055, footer_y)
            footer_y = min(footer_y, 0.955)
        region["rect"] = [
            0.06,
            round(footer_y, 4),
            0.88,
            round(min(0.045, max(0.98 - footer_y, 0.02)), 4),
        ]


def _region_kind(region: dict[str, Any]) -> str:
    text = f"{region.get('role', '')} {region.get('id', '')}".lower()
    if "title" in text or "headline" in text:
        return "title"
    if "footer" in text or "evidence" in text or "source" in text:
        return "footer"
    return "content"


def _is_visual_region(region: dict[str, Any]) -> bool:
    role = str(region.get("role", "")).lower()
    region_id = str(region.get("id", "")).lower()
    if any(token in role for token in ("body", "text", "content", "footer", "title")):
        return False
    text = f"{role} {region_id}"
    return "visual" in text or "image" in text or "figure" in text or "chart" in text or "benchmark" in text


def _regions_from_ir_slots(slide_ir: dict[str, Any]) -> list[dict[str, Any]]:
    slots = slide_ir.get("layout", {}).get("slots", []) or []
    regions = []
    for slot in slots:
        slot_id = str(slot.get("slot_id") or "").strip()
        if not slot_id:
            continue
        role = str(slot.get("slot_role") or ("visual" if "visual" in slot_id else slot_id))
        regions.append(
            {
                "id": slot_id,
                "role": role,
                "rect": _normalize_rect(
                    [
                        slot.get("x_ratio", 0.06),
                        slot.get("y_ratio", 0.22),
                        slot.get("w_ratio", 0.88),
                        slot.get("h_ratio", 0.58),
                    ]
                ),
            }
        )
    return regions


def _variant_for_block(block: dict[str, Any]) -> str:
    kind = str(block.get("kind") or "")
    if kind == "summary":
        return "summary_panel"
    if kind == "bullet_list":
        return "compact_bullets"
    if kind == "quote":
        return "quote_card"
    if kind == "metric_strip":
        return "metric_cards"
    return "summary_panel"


def _coerce_element_variant(variant: str) -> str:
    if variant in {"text", "title", "headline"}:
        return "headline"
    if variant in {"kicker", "eyebrow", "section_label", "section"}:
        return "kicker" if variant in {"kicker", "eyebrow"} else "section_label"
    if "bullet" in variant:
        return "compact_bullets"
    if "footer" in variant or "evidence" in variant:
        return "evidence_footer"
    if "insight" in variant:
        return "insight_panel"
    if "definition" in variant:
        return "definition_panel"
    if "summary" in variant:
        return "summary_panel"
    return "summary_panel"


def _element_type_for_variant(variant: str) -> str:
    if variant in {"headline", "subtitle", "kicker", "section_label"}:
        return "text"
    return "block"


def _is_allowed_source(source: str) -> bool:
    return source in ALLOWED_SOURCES or SOURCE_PATTERN.match(source) is not None


def _first_region_id(regions: list[dict[str, Any]], *, roles: set[str], fallback: str) -> str:
    lowered = {role.lower() for role in roles}
    for region in regions:
        if str(region.get("role", "")).lower() in lowered or str(region.get("id", "")).lower() in lowered:
            return str(region["id"])
    return fallback
