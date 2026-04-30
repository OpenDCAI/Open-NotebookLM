"""VLM asset description helpers."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..llm.client import LLMClient


class VLMDescriptor:
    def __init__(self, client: LLMClient, *, max_workers: int = 4):
        self.client = client
        self.max_workers = max_workers

    def describe_asset(
        self,
        asset_path: str,
        *,
        category: str = "self",
        asset_kind: str = "image",
        markdown_text: str = "",
        request_context: dict | None = None,
    ) -> str:
        record = self.describe_asset_record(
            asset_path,
            category=category,
            asset_kind=asset_kind,
            markdown_text=markdown_text,
            request_context=request_context,
        )
        return record["description"]

    def describe_asset_record(
        self,
        asset_path: str,
        *,
        category: str = "self",
        asset_kind: str = "image",
        markdown_text: str = "",
        request_context: dict | None = None,
    ) -> dict[str, Any]:
        path = Path(asset_path)
        asset_url = self._path_to_data_url(path)
        prompt = self._build_describe_prompt(
            category=category,
            asset_kind=asset_kind,
            markdown_text=markdown_text,
            request_context=request_context or {},
        )
        response = self.client.chat_with_image(prompt, asset_url)
        return self._parse_description_response(
            response,
            asset_path=asset_path,
            category=category,
            asset_kind=asset_kind,
            request_context=request_context or {},
        )

    def describe_assets_with_metadata(
        self,
        assets: list[dict] | list[str],
        markdown_text: str = "",
        asset_request_contexts: dict[str, dict] | None = None,
        progress_callback: callable | None = None,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        descriptions: dict[str, str] = {}
        records: dict[str, dict[str, Any]] = {}
        asset_request_contexts = asset_request_contexts or {}
        normalized_assets = self._normalize_assets(assets)
        if not normalized_assets:
            return descriptions, records

        def _describe(asset: dict[str, Any]) -> dict[str, Any]:
            return self.describe_asset_record(
                asset["path"],
                category=asset.get("category", "self"),
                asset_kind=asset.get("asset_kind", "image"),
                markdown_text=markdown_text,
                request_context=asset_request_contexts.get(asset["path"], {}),
            )

        if min(self.max_workers, len(normalized_assets)) <= 1:
            for asset in normalized_assets:
                asset_path = asset["path"]
                record = _describe(asset)
                records[asset_path] = record
                descriptions[asset_path] = record["description"]
                if progress_callback is not None:
                    progress_callback(len(records), len(normalized_assets), asset_path)
            return descriptions, records

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(normalized_assets))) as executor:
            future_map = {executor.submit(_describe, asset): asset for asset in normalized_assets}
            for future in as_completed(future_map):
                asset = future_map[future]
                asset_path = asset["path"]
                record = future.result()
                records[asset_path] = record
                descriptions[asset_path] = record["description"]
                if progress_callback is not None:
                    progress_callback(len(records), len(normalized_assets), asset_path)
        return descriptions, records

    def describe_assets(
        self,
        assets: list[dict] | list[str],
        markdown_text: str = "",
        asset_request_contexts: dict[str, dict] | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, str]:
        descriptions, _ = self.describe_assets_with_metadata(
            assets,
            markdown_text=markdown_text,
            asset_request_contexts=asset_request_contexts,
            progress_callback=progress_callback,
        )
        return descriptions

    def describe_image(self, image_path: str) -> str:
        return self.describe_asset(image_path)

    def describe_images(self, image_paths: list[str]) -> dict[str, str]:
        return self.describe_assets(image_paths)

    def select_best_candidate(
        self,
        request: dict,
        candidates: list[dict],
        descriptions: dict[str, str],
        markdown_text: str = "",
    ) -> dict | None:
        if not candidates:
            return None
        scored_candidates = [
            self.score_candidate(
                request,
                candidate,
                descriptions.get(candidate["path"], candidate.get("description", "")),
                markdown_text=markdown_text,
            )
            for candidate in candidates
        ]
        scored_candidates.sort(key=lambda item: item.get("vlm_score", 0.0), reverse=True)
        return scored_candidates[0]

    def score_candidate_with_embedding(
        self,
        request: dict,
        candidate: dict,
        candidate_description: str,
    ) -> dict[str, Any]:
        """Score candidate using embedding for semantic match + cached quality scores."""
        print(f"[DEBUG] score_candidate_with_embedding: {candidate.get('path', 'unknown')}")

        # Extract request text
        request_text = f"{request.get('caption', '')} {request.get('purpose', '')}"

        # Calculate semantic match using embedding
        try:
            request_emb = self.client.get_embedding(request_text)
            desc_emb = self.client.get_embedding(candidate_description)

            # Cosine similarity
            import math
            dot_product = sum(a * b for a, b in zip(request_emb, desc_emb))
            norm_a = math.sqrt(sum(a * a for a in request_emb))
            norm_b = math.sqrt(sum(b * b for b in desc_emb))
            semantic_match = dot_product / (norm_a * norm_b) if norm_a and norm_b else 0.0
        except Exception:
            semantic_match = 0.5  # Fallback

        # Get cached quality scores from candidate
        clarity = candidate.get("clarity", 0.7)
        aesthetics = candidate.get("aesthetics", 0.7)
        info_density = candidate.get("information_density", 0.7)

        # Calculate geometry match (aspect ratio, orientation)
        geometry_match = self._calculate_geometry_match(request, candidate)

        # Calculate overall score (weighted average)
        overall = (semantic_match * 0.4 + clarity * 0.2 + aesthetics * 0.2 + info_density * 0.1 + geometry_match * 0.1)

        selected = dict(candidate)
        selected["vlm_score"] = overall
        selected["semantic_match"] = semantic_match
        selected["content_score"] = semantic_match
        selected["geometry_score"] = geometry_match
        selected["why_selected"] = f"Semantic: {semantic_match:.2f}, Quality: {clarity:.2f}/{aesthetics:.2f}/{info_density:.2f}, Geometry: {geometry_match:.2f}"

        return selected

    def score_candidate(
        self,
        request: dict,
        candidate: dict,
        candidate_description: str,
        *,
        markdown_text: str = "",
    ) -> dict[str, Any]:
        print(f"[DEBUG] score_candidate (VLM): {candidate.get('path', 'unknown')}, category={candidate.get('category')}")

        prompt_lines = [
            "You are a PPT visual asset evaluator. Judge whether this candidate matches the slide material request.",
            f"Asset type: {request.get('asset_type', 'image')}",
            f"Slide purpose: {request.get('purpose', '')}",
            f"Target caption: {request.get('caption', '')}",
            f"Requested count: {request.get('need_count', 1)}",
            f"Size preference: {request.get('size_preference', 'medium')}",
            f"Orientation preference: {request.get('orientation_preference', 'any')}",
            f"Aspect-ratio preference: {request.get('aspect_ratio_hint', 'any')}",
            f"Style keywords: {', '.join(request.get('style_keywords', []))}",
            f"Candidate description: {candidate_description}",
            (
                "Candidate metadata: "
                f"width_px={candidate.get('width_px')}, "
                f"height_px={candidate.get('height_px')}, "
                f"aspect_ratio={candidate.get('aspect_ratio')}, "
                f"orientation={candidate.get('orientation')}, "
                f"category={candidate.get('category')}"
            ),
            "Evaluate content match, geometric fit for the slide, and presentation suitability.",
        ]
        if markdown_text:
            prompt_lines.append(f"Source markdown summary:\n{markdown_text[:2500]}")
        prompt_lines.append(
            'Return JSON only, for example {"score": 0.82, "content_score": 0.86, "geometry_score": 0.74, "reason": "..."}'
        )
        try:
            response = self.client.chat_with_image(
                "\n".join(prompt_lines),
                self._path_to_data_url(Path(candidate["path"])),
            )
            parsed = self._extract_json(response)
            selected = dict(candidate)
            selected["why_selected"] = parsed.get("reason", "")
            selected["vlm_score"] = float(parsed.get("score", 0.0))
            selected["content_score"] = float(parsed.get("content_score", selected["vlm_score"]))
            selected["geometry_score"] = float(parsed.get("geometry_score", selected["vlm_score"]))
            return selected
        except Exception as exc:
            raise RuntimeError(
                f"VLM candidate scoring failed for {request.get('request_id', '')} and {candidate.get('path', '')}: {exc}"
            ) from exc

    def _path_to_data_url(self, path: Path) -> str:
        with path.open("rb") as file_obj:
            asset_data = base64.b64encode(file_obj.read()).decode()
        mime_type = self._guess_mime_type(path)
        return f"data:{mime_type};base64,{asset_data}"

    @staticmethod
    def _normalize_assets(assets: list[dict] | list[str]) -> list[dict]:
        normalized_assets: list[dict[str, Any]] = []
        for asset in assets:
            if isinstance(asset, str):
                path = asset
                suffix = Path(path).suffix.lower()
                normalized_assets.append(
                    {
                        "path": path,
                        "category": "paper2any" if suffix == ".svg" else "self",
                        "asset_kind": "icon" if suffix == ".svg" else "image",
                    }
                )
            else:
                normalized_assets.append(asset)
        return normalized_assets

    @staticmethod
    def _build_describe_prompt(
        *,
        category: str,
        asset_kind: str,
        markdown_text: str,
        request_context: dict,
    ) -> str:
        markdown_preview = markdown_text[:2500] if markdown_text else ""
        request_caption = request_context.get("caption") or request_context.get("title") or ""
        request_purpose = request_context.get("purpose", "")
        prefix = "icon" if asset_kind == "icon" else "image"
        if category == "self":
            scenario = (
                "You are building an index of native PDF assets so the planner can select visuals directly. "
                "Focus on what the asset specifically shows, what kind of slide it can support, and whether it is closer to a chart, flow diagram, interface screenshot, illustration, or mixed visual."
            )
        else:
            scenario = (
                f"You are building an index entry for a candidate {prefix} to support planner selection and material comparison. "
                "Focus on whether it matches the current request caption and whether it is suitable for a presentation."
            )
        return (
            f"{scenario}\n"
            f"Asset category: {category}\n"
            f"Asset type: {asset_kind}\n"
            f"Requested {prefix} caption: {request_caption}\n"
            f"Requested usage purpose: {request_purpose}\n"
            f"Source markdown summary:\n{markdown_preview}\n"
            "Return one strictly valid JSON object only, with these fields:\n"
            "{\n"
            '  "caption": "A short English caption of roughly 4 to 12 words",\n'
            '  "content_summary": "1 to 2 English sentences describing what the asset contains and how the information is organized",\n'
            '  "recommended_usage": "What kind of PPT page this asset can support and what visual slot it fits",\n'
            '  "semantic_keywords": ["keyword1", "keyword2", "keyword3"],\n'
            '  "visual_type": "photo | chart | diagram | interface | icon | table | illustration | mixed",\n'
            '  "quality_notes": "Short English note about clarity, crop, density, and readability",\n'
            '  "clarity": 0.9,\n'
            '  "aesthetics": 0.8,\n'
            '  "information_density": 0.85\n'
            "}\n"
            "Rate these dimensions (0.0 to 1.0):\n"
            "- clarity: Is the image clear, sharp, and high resolution?\n"
            "- aesthetics: Is the image visually appealing and professional for presentations?\n"
            "- information_density: Is the image balanced (not too cluttered, not too empty)?\n"
            "Do not output markdown, image links, or code fences."
        )

    @staticmethod
    def _parse_description_response(
        response: str,
        *,
        asset_path: str,
        category: str,
        asset_kind: str,
        request_context: dict,
    ) -> dict[str, Any]:
        payload: dict[str, Any] | None = None
        try:
            payload = VLMDescriptor._extract_json(response)
        except Exception as exc:
            raise RuntimeError(
                f"VLM description did not return valid JSON for {asset_path}: {exc}; response={response[:300]}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"VLM description returned non-object JSON for {asset_path}: {response[:300]}")

        caption = VLMDescriptor._clean_text(payload.get("caption", ""))
        content_summary = VLMDescriptor._clean_text(payload.get("content_summary", ""))
        recommended_usage = VLMDescriptor._clean_text(payload.get("recommended_usage", ""))
        quality_notes = VLMDescriptor._clean_text(payload.get("quality_notes", ""))
        keywords = VLMDescriptor._normalize_keywords(payload.get("semantic_keywords", []))
        visual_type = VLMDescriptor._clean_text(payload.get("visual_type", "")) or (
            "icon" if asset_kind == "icon" else "image"
        )
        if not caption:
            raise RuntimeError(f"VLM description missing caption for {asset_path}: {response[:300]}")
        description_parts = [caption, content_summary, recommended_usage]
        if quality_notes:
            description_parts.append(f"Quality: {quality_notes}")
        description = "; ".join(part for part in description_parts if part)
        return {
            "caption": caption,
            "content_summary": content_summary,
            "recommended_usage": recommended_usage,
            "semantic_keywords": keywords,
            "visual_type": visual_type,
            "quality_notes": quality_notes,
            "description": description,
            "source_context": request_context,
        }

    @staticmethod
    def _clean_text(text: Any) -> str:
        value = str(text or "")
        value = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
        value = re.sub(r"https?://\S+", "", value)
        value = re.sub(r"\s+", " ", value).strip(" \n\t`")
        return value

    @staticmethod
    def _normalize_keywords(values: Any) -> list[str]:
        if isinstance(values, str):
            values = re.split(r"[,，;；/]\s*", values)
        keywords: list[str] = []
        for value in values or []:
            text = VLMDescriptor._clean_text(value)
            if text and text not in keywords:
                keywords.append(text)
        return keywords[:8]

    @staticmethod
    def _extract_json(text: str) -> dict:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("JSON not found in VLM response")
        return json.loads(text[start : end + 1])

    @staticmethod
    def _calculate_geometry_match(request: dict, candidate: dict) -> float:
        """Calculate geometry match score based on aspect ratio, orientation, and resolution."""
        score = 1.0

        # Check aspect ratio preference
        aspect_hint = request.get("aspect_ratio_hint", "any")
        if aspect_hint and aspect_hint != "any":
            candidate_aspect = candidate.get("aspect_ratio", "")
            candidate_orientation = candidate.get("orientation", "")

            if "square" in aspect_hint.lower() or aspect_hint == "1:1":
                if candidate_orientation != "square":
                    score *= 0.7
            elif "portrait" in aspect_hint.lower() or "tall" in aspect_hint.lower():
                if candidate_orientation != "portrait":
                    score *= 0.7
            elif "landscape" in aspect_hint.lower() or aspect_hint == "16:9":
                if candidate_orientation != "landscape":
                    score *= 0.7

        # Check orientation preference
        orientation_pref = request.get("orientation_preference", "any")
        if orientation_pref and orientation_pref != "any":
            candidate_orientation = candidate.get("orientation", "")
            if candidate_orientation != orientation_pref:
                score *= 0.8

        # Check resolution (minimum for PPT display without blur)
        width = candidate.get("width_px", 0)
        height = candidate.get("height_px", 0)
        min_dimension = min(width, height) if width and height else 0

        if min_dimension < 400:  # Too small
            score *= 0.5
        elif min_dimension < 800:  # Acceptable but not ideal
            score *= 0.8

        return score

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        if path.suffix.lower() == ".svg":
            return "image/svg+xml"
        mime_type, _ = mimetypes.guess_type(str(path))
        return mime_type or "image/png"

    def validate_image(
        self,
        image_path: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate generated image quality with 5-dimension scoring.

        Returns:
            {
                "semantic_match": float,
                "clarity": float,
                "aspect_ratio_fit": float,
                "aesthetics": float,
                "information_density": float,
                "overall_score": float,
                "issues": list[str],
                "pass": bool
            }
        """
        print(f"[DEBUG] validate_image (VLM): {image_path}")

        path = Path(image_path)
        image_url = self._path_to_data_url(path)

        prompt = f"""Evaluate this generated image for presentation use.

Request requirements:
- Caption: {request.get('caption', '')}
- Purpose: {request.get('purpose', '')}
- Desired aspect ratio: {request.get('aspect_ratio_hint', 'any')}
- Style keywords: {', '.join(request.get('style_keywords', []))}

Rate the image on these dimensions (0.0 to 1.0):

1. semantic_match: Does the image content match the caption and purpose?
2. clarity: Is the image clear, sharp, and high resolution?
3. aspect_ratio_fit: Does the image proportion match the desired aspect ratio?
4. aesthetics: Is the image visually appealing and professional for presentations?
5. information_density: Is the image balanced (not too cluttered, not too empty)?

Also provide:
- overall_score: Average of all dimensions
- issues: List any specific problems (e.g., "blurry text", "wrong orientation")
- pass: true if overall_score >= 0.7, false otherwise

Return JSON only:
{{
  "semantic_match": 0.85,
  "clarity": 0.9,
  "aspect_ratio_fit": 0.8,
  "aesthetics": 0.75,
  "information_density": 0.8,
  "overall_score": 0.82,
  "issues": [],
  "pass": true
}}"""

        try:
            response = self.client.chat_with_image(prompt, image_url)
            result = self._extract_json(response)
            result.setdefault("pass", result.get("overall_score", 0.0) >= 0.7)
            return result
        except Exception as e:
            return {
                "semantic_match": 0.0,
                "clarity": 0.0,
                "aspect_ratio_fit": 0.0,
                "aesthetics": 0.0,
                "information_density": 0.0,
                "overall_score": 0.0,
                "issues": [f"Validation error: {str(e)}"],
                "pass": False,
            }
