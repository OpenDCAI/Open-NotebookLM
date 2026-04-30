"""Recipe-native React refinement for qwen_lib mode."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.coder.qwen_recipe_audit import audit_pptx
from src.coder.qwen_recipe_renderer import QwenRecipeRenderer
from src.coder.qwen_recipe_schema import QwenRecipeError, build_default_recipe, normalize_recipe, parse_qwen_recipe_response
from src.refiner.ir_projection import project_vlm_view
from src.refiner.react_refiner import ReactRefiner, SlideRenderer
from src.refiner.vlm_checklist import build_vlm_evaluation_prompt


class QwenRecipeRefiner:
    """Refine Qwen rendering recipes without exposing python-pptx codegen."""

    def __init__(
        self,
        llm_client,
        *,
        vlm_client=None,
        renderer=None,
        max_iterations: int = 1,
        threshold: float = 8.0,
    ) -> None:
        self.llm_client = llm_client
        self.vlm_client = vlm_client
        self.renderer = renderer or SlideRenderer(coder=None)
        self.max_iterations = max(1, int(max_iterations or 1))
        self.threshold = float(threshold)

    def refine_slide_recipe(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        *,
        current_recipe: dict[str, Any],
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = self._build_recipe_refine_prompt(deck_ir, slide_ir, materials, current_recipe, feedback)
        raw = self.llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format="json",
        )
        try:
            candidate = parse_qwen_recipe_response(raw, slide_ir=slide_ir)
        except QwenRecipeError:
            preserved = normalize_recipe(deepcopy(current_recipe), slide_ir=slide_ir)
            constraints = preserved.setdefault("constraints", {"no_new_claims": True})
            adjustments = list(constraints.get("harness_adjustments", []) or [])
            adjustments.append("react_refine_parse_failed")
            constraints["harness_adjustments"] = adjustments
            return preserved
        if self._drops_existing_body_sources(current_recipe, candidate):
            preserved = normalize_recipe(deepcopy(current_recipe), slide_ir=slide_ir)
            constraints = preserved.setdefault("constraints", {"no_new_claims": True})
            adjustments = list(constraints.get("harness_adjustments", []) or [])
            adjustments.append("content_preservation:rejected_dropped_sources")
            constraints["harness_adjustments"] = adjustments
            return preserved
        return candidate

    def refine_deck(
        self,
        deck_ir: dict[str, Any],
        materials: dict[str, Any],
        output_dir: str,
        *,
        mode: str = "qwen_lib",
        initial_recipes: list[dict[str, Any]] | None = None,
        progress_callback=None,
    ) -> dict[str, Any]:
        output_root = Path(output_dir)
        recipe_dir = output_root / "refine" / "qwen_recipe"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        slides = list(deck_ir.get("slides", []) or [])
        recipes = self._load_or_default_recipes(output_root, slides, initial_recipes)
        normalized_recipes = [
            normalize_recipe(deepcopy(recipes[index] if index < len(recipes) else build_default_recipe(slide_ir)), slide_ir=slide_ir)
            for index, slide_ir in enumerate(slides)
        ]
        react_history: list[dict[str, Any]] = []

        for index, slide_ir in enumerate(slides):
            recipe = recipes[index] if index < len(recipes) else build_default_recipe(slide_ir)
            normalized = normalize_recipe(deepcopy(recipe), slide_ir=slide_ir)
            slide_id = slide_ir.get("slide_id", f"slide_{index + 1:02d}")
            history: list[dict[str, Any]] = []
            for iteration in range(1, self.max_iterations + 1):
                round_dir = recipe_dir / f"round_{iteration:02d}" / str(slide_id)
                round_dir.mkdir(parents=True, exist_ok=True)
                pptx_path = round_dir / f"{slide_id}.pptx"
                renderer = QwenRecipeRenderer()
                renderer.render_single_slide(
                    deck_ir,
                    slide_ir,
                    materials,
                    normalized,
                    output_path=str(pptx_path),
                    artifact_dir=str(round_dir / "rendered_recipes"),
                )
                render_audit = audit_pptx(pptx_path)
                feedback = self._evaluate_rendered_slide(
                    deck_ir,
                    slide_ir,
                    str(pptx_path),
                    round_dir,
                    iteration=iteration,
                    history={"iteration": iteration, "previous_feedback": history},
                    render_audit=render_audit,
                )
                feedback["render_audit"] = render_audit
                (round_dir / "feedback.json").write_text(
                    json.dumps(feedback, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (round_dir / f"{slide_id}.recipe.json").write_text(
                    json.dumps(normalized, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                history.append(
                    {
                        "iteration": iteration,
                        "score": feedback.get("score", 0.0),
                        "feedback": feedback.get("feedback", ""),
                        "strengths": feedback.get("strengths", []),
                    }
                )
                if progress_callback is not None:
                    progress_callback(index + 1, max(len(slides), 1), f"qwen recipe react {slide_id} round {iteration}")
                if float(feedback.get("score", 0.0)) >= self.threshold:
                    break
                if iteration >= self.max_iterations:
                    break
                normalized = self.refine_slide_recipe(
                    deck_ir,
                    slide_ir,
                    materials,
                    current_recipe=normalized,
                    feedback=feedback,
                )
            normalized_recipes[index] = normalized
            (recipe_dir / f"{slide_id}.recipe.json").write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            react_history.append(
                {
                    "slide_id": slide_id,
                    "iterations": len(history),
                    "complete": bool(history and float(history[-1].get("score", 0.0)) >= self.threshold),
                    "history": history,
                }
            )

        final_pptx = output_root / "refined_final.pptx"
        renderer = QwenRecipeRenderer()
        renderer.render_deck(
            deck_ir,
            materials,
            normalized_recipes,
            str(final_pptx),
            artifact_dir=str(recipe_dir / "rendered_recipes"),
        )
        (recipe_dir / "react_history.json").write_text(
            json.dumps(react_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ir": deck_ir, "recipes": normalized_recipes, "final_pptx": str(final_pptx), "react_history": react_history}

    def _evaluate_rendered_slide(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        pptx_path: str,
        round_dir: Path,
        *,
        iteration: int,
        history: dict[str, Any],
        render_audit: dict[str, Any],
    ) -> dict[str, Any]:
        if render_audit.get("status") != "pass":
            return {
                "score": 0.0,
                "feedback": f"Local render audit failed: {json.dumps(render_audit, ensure_ascii=False)}",
                "strengths": [],
                "source": "render_audit",
            }
        if self.vlm_client is None:
            return {
                "score": self.threshold,
                "feedback": "Local render audit passed; VLM client unavailable.",
                "strengths": ["No text overlaps or out-of-bounds shapes detected."],
                "source": "render_audit",
            }

        screenshot_path = self._render_screenshot(pptx_path, round_dir, str(slide_ir.get("slide_id", "slide")))
        if not screenshot_path:
            return {
                "score": 0.0,
                "feedback": "Screenshot generation failed before VLM evaluation.",
                "strengths": [],
                "source": "screenshot",
            }

        with open(screenshot_path, "rb") as handle:
            image_url = f"data:image/png;base64,{base64.b64encode(handle.read()).decode()}"
        prompt = build_vlm_evaluation_prompt(
            project_vlm_view(deck_ir, slide_ir, history),
            image_url,
            iteration=iteration,
        )
        response = self.vlm_client.chat_with_image(prompt, image_url)
        return self._parse_evaluation_response(response)

    def _render_screenshot(self, pptx_path: str, round_dir: Path, slide_id: str) -> str | None:
        backend = self.renderer.detect_backend()
        if backend == "aspose_pdf_png":
            _pdf_path, screenshot_path = self.renderer._render_with_aspose(pptx_path, round_dir, slide_id)
            return screenshot_path
        if backend.startswith("pptx_pdf_png:"):
            pdf_path = self.renderer._convert_pptx_to_pdf(pptx_path, round_dir)
            return self.renderer._convert_pdf_to_png(pdf_path, round_dir, slide_id, backend) if pdf_path else None
        if backend.startswith("powerpoint_pdf_png:"):
            pdf_path = self.renderer._convert_pptx_to_pdf_with_powerpoint(pptx_path, round_dir)
            return self.renderer._convert_pdf_to_png(pdf_path, round_dir, slide_id, backend) if pdf_path else None
        return None

    def _parse_evaluation_response(self, response: str) -> dict[str, Any]:
        data = ReactRefiner._extract_json(response, source="Qwen recipe VLM evaluation")
        score = float(data.get("score", 0.0))
        feedback = data.get("feedback", "")
        strengths = data.get("strengths", [])
        return {
            **data,
            "score": score,
            "feedback": str(feedback) if feedback is not None else "",
            "strengths": strengths if isinstance(strengths, list) else [strengths],
            "source": "vlm",
        }

    def _load_or_default_recipes(
        self,
        output_root: Path,
        slides: list[dict[str, Any]],
        initial_recipes: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if initial_recipes is not None:
            return [deepcopy(recipe) for recipe in initial_recipes]
        generated_dir = output_root / "code" / "generated" / "recipes"
        recipes = []
        for index, slide_ir in enumerate(slides):
            slide_id = slide_ir.get("slide_id", f"slide_{index + 1:02d}")
            path = generated_dir / f"{slide_id}.recipe.json"
            if path.exists():
                try:
                    recipes.append(json.loads(path.read_text(encoding="utf-8")))
                    continue
                except json.JSONDecodeError:
                    pass
            recipes.append(build_default_recipe(slide_ir))
        return recipes

    def _build_recipe_refine_prompt(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        current_recipe: dict[str, Any],
        feedback: dict[str, Any],
    ) -> str:
        payload = {
            "task": "Revise this qwen_recipe_v1 recipe to address feedback. Return one complete recipe JSON object only.",
            "rules": [
                "Do not write Python.",
                "Do not use python-pptx, EMU, Inches, pixels, or raw coordinates outside ratio rect [x,y,w,h].",
                "Use only safe variants already present in qwen_recipe_v1.",
                "Do not add claims or text not present in slide IR.",
                "Prefer minimal changes; geometry harness will resolve small overlaps after your output.",
            ],
            "recipe_adjustment_policy": [
                "Do not modify slide IR, material_requests, visuals, blocks, points, or source evidence.",
                "Do not invent materials, image paths, icons, captions, claims, labels, or evidence.",
                "If feedback asks to update IR or add images, translate only the layout part into recipe regions/compositions; keep missing-material issues unresolved.",
                "For spacing feedback, adjust only region rects, reduce competing elements, or choose a safer composition variant.",
                "For alignment feedback, use one shared region for a grid/compare composition, equal card widths, and consistent top edges.",
                "For hierarchy feedback, adjust region allocation and safe element variants such as headline, subtitle, takeaway, insight_panel.",
                "For duplicate_text_warnings, remove duplicate render nodes, change one duplicate node to a complementary source, or consolidate the repeated source into one richer composition.",
                "For image aspect warnings, preserve the existing visual source and switch to rendered_visual/captioned_visual/visual_compare with a normal visual region; do not stretch image assets.",
                "Preserve all visible content from slide IR; never drop source items to make layout easier.",
            ],
            "structure_fidelity": {
                "evidence_cards": "Render claim/evidence items from points or blocks as cards without template labels or new facts.",
                "visual_compare": "Use visual_compare only when visuals are already planned; do not invent image assets.",
                "dense_text_columns": "Use for dense lists and keep every source item visible when possible.",
            },
            "deck": {"title": deck_ir.get("title", ""), "theme": deck_ir.get("theme", {})},
            "slide": {
                key: slide_ir.get(key)
                for key in ("slide_id", "type", "title", "subtitle", "core_message", "layout", "points", "blocks", "visuals")
                if key in slide_ir
            },
            "materials": {
                "has_selected_asset": bool(slide_ir.get("selected_asset_path")),
                "asset_count": len(materials.get("assets", []) or []),
            },
            "feedback": feedback,
            "current_recipe": current_recipe,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _drops_existing_body_sources(current_recipe: dict[str, Any], candidate_recipe: dict[str, Any]) -> bool:
        current_sources = QwenRecipeRefiner._body_sources(current_recipe)
        if not current_sources:
            return False
        candidate_sources = QwenRecipeRefiner._body_sources(candidate_recipe)
        return not current_sources.issubset(candidate_sources)

    @staticmethod
    def _body_sources(recipe: dict[str, Any]) -> set[str]:
        sources: set[str] = set()
        for item in list(recipe.get("elements", []) or []) + list(recipe.get("compositions", []) or []):
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            if source == "points" or source.startswith("blocks["):
                sources.add(source)
        return sources
