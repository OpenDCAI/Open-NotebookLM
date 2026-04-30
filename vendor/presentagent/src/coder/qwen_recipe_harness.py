"""Harness helpers for observing Qwen recipe behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .qwen_recipe_coder import QwenRecipeCoder


def run_recipe_harness(
    client,
    deck_ir: dict[str, Any],
    slide_ir: dict[str, Any],
    materials: dict[str, Any],
    output_dir: str,
    *,
    render: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    coder = QwenRecipeCoder(client)
    recipe = coder.generate_slide_recipe(deck_ir, slide_ir, materials, index=1, artifact_dir=str(output))
    result: dict[str, Any] = {
        "slide_id": slide_ir.get("slide_id", "slide_01"),
        "recipe": recipe,
        "harness_adjustments": recipe.get("constraints", {}).get("harness_adjustments", []),
        "rendered_pptx": "",
        "render_audit": {},
    }

    if render:
        from .qwen_recipe_renderer import QwenRecipeRenderer

        pptx_path = output / f"{result['slide_id']}.pptx"
        renderer = QwenRecipeRenderer()
        renderer.render_single_slide(
            deck_ir,
            slide_ir,
            materials,
            recipe,
            output_path=str(pptx_path),
            artifact_dir=str(output / "rendered_recipes"),
        )
        result["rendered_pptx"] = str(pptx_path)
        from .qwen_recipe_audit import audit_pptx

        result["render_audit"] = audit_pptx(pptx_path)

    (output / "harness_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_slide(ir_or_slide: dict[str, Any], *, slide_id: str = "", slide_index: int = 1) -> tuple[dict[str, Any], dict[str, Any]]:
    if "slides" not in ir_or_slide:
        return {"title": "", "theme": {}, "slides": [ir_or_slide]}, ir_or_slide
    deck_ir = ir_or_slide
    slides = list(deck_ir.get("slides", []) or [])
    if slide_id:
        for slide in slides:
            if str(slide.get("slide_id", "")) == slide_id:
                return deck_ir, slide
        raise ValueError(f"slide_id not found: {slide_id}")
    if not slides:
        raise ValueError("deck IR contains no slides")
    index = max(1, slide_index) - 1
    if index >= len(slides):
        raise ValueError(f"slide_index out of range: {slide_index}")
    return deck_ir, slides[index]
