"""Resolve IR material requests into concrete asset selections."""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .image_generator import ImageGenerator
from .material_collector import MaterialCollector
from .vlm_descriptor import VLMDescriptor


class MaterialResolver:
    SOURCE_TO_CATEGORY = {
        "paper2any": "paper2any",
    }

    def __init__(
        self,
        descriptor: VLMDescriptor | None = None,
        image_generator: ImageGenerator | None = None,
        collector: MaterialCollector | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.image_generator = image_generator
        self.collector = collector or MaterialCollector(descriptor)

    def resolve(self, materials: dict[str, Any], ir: dict[str, Any], progress_callback=None) -> dict[str, Any]:
        requests = ir.get("material_requests", [])
        if not requests:
            return {"materials": materials, "ir": ir, "resolved_requests": [], "resolution_path": ""}

        if self.descriptor is None:
            raise RuntimeError("MaterialResolver requires a VLM descriptor for strict material scoring.")

        document_dir = Path(materials["document_dir"])
        resolution_path = Path(materials["materials_dir"]) / "material_resolution.json"
        existing_resolutions = self._load_existing_resolutions(resolution_path)
        used_asset_ids = {
            slide.get("selected_asset_id")
            for slide in ir.get("slides", [])
            if slide.get("selected_asset_id")
        }
        used_asset_ids = {asset_id for asset_id in used_asset_ids if asset_id}

        resolved_requests: list[dict[str, Any]] = [None] * len(requests)
        total_requests = len(requests)
        max_workers = 1  # 串行处理，避免服务器断开连接

        def _resolve_wrapper(idx: int, request: dict) -> tuple[int, dict, dict]:
            cached = existing_resolutions.get(request.get("request_id", ""))
            if self._is_reusable_resolution(cached):
                return idx, cached, {}
            else:
                mat, res = self._resolve_single_request(materials, request, used_asset_ids, document_dir)
                return idx, res, mat

        if max_workers == 1:
            for index, request in enumerate(requests, start=1):
                idx, resolution, mat_update = _resolve_wrapper(index - 1, request)
                if mat_update:
                    materials.update(mat_update)
                resolved_requests[idx] = resolution
                selected = resolution.get("resolved_candidate")
                if selected and selected.get("asset_id"):
                    used_asset_ids.add(selected["asset_id"])
                self._bind_request_to_slide(ir, request, selected)
                self._write_resolution_checkpoint(resolution_path, [r for r in resolved_requests if r])
                if progress_callback is not None:
                    cached = existing_resolutions.get(request.get("request_id", ""))
                    detail = request.get("request_id", f"request_{index:02d}")
                    if self._is_reusable_resolution(cached):
                        detail = f"{detail} reuse"
                    progress_callback(index, total_requests, detail)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(_resolve_wrapper, idx, req): idx for idx, req in enumerate(requests)}
                completed = 0
                for future in as_completed(future_map):
                    idx, resolution, mat_update = future.result()
                    if mat_update:
                        materials.update(mat_update)
                    resolved_requests[idx] = resolution
                    request = requests[idx]
                    selected = resolution.get("resolved_candidate")
                    if selected and selected.get("asset_id"):
                        used_asset_ids.add(selected["asset_id"])
                    self._bind_request_to_slide(ir, request, selected)
                    completed += 1
                    self._write_resolution_checkpoint(resolution_path, [r for r in resolved_requests if r])
                    if progress_callback is not None:
                        cached = existing_resolutions.get(request.get("request_id", ""))
                        detail = request.get("request_id", f"request_{idx+1:02d}")
                        if self._is_reusable_resolution(cached):
                            detail = f"{detail} reuse"
                        progress_callback(completed, total_requests, detail)

        resolved_requests = [r for r in resolved_requests if r]

        resolution_doc = {
            "summary": {
                "request_count": len(resolved_requests),
                "resolved_count": sum(1 for item in resolved_requests if item.get("resolution_status") == "resolved"),
                "unresolved_count": sum(1 for item in resolved_requests if item.get("resolution_status") != "resolved"),
            },
            "requests": resolved_requests,
        }
        resolution_path.write_text(json.dumps(resolution_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "materials": materials,
            "ir": ir,
            "resolved_requests": resolved_requests,
            "resolution_path": str(resolution_path),
        }

    def _resolve_single_request(
        self,
        materials: dict[str, Any],
        request: dict[str, Any],
        used_asset_ids: set[str],
        document_dir: Path,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        # Auto-fill source_options if not provided by planner
        if not request.get("acquisition_plan"):
            request["acquisition_plan"] = {}
        if not request["acquisition_plan"].get("source_options"):
            request["acquisition_plan"]["source_options"] = ["paper2any"]

        threshold = float(request.get("minimum_vlm_score", 0.7))
        attempt_log: list[dict[str, Any]] = []
        candidate_pool: list[dict[str, Any]] = []

        self_candidates = self._score_existing_assets(
            materials,
            request,
            allowed_categories={"self"},
            used_asset_ids=used_asset_ids,
        )
        candidate_pool.extend(self_candidates)
        best_self = self_candidates[0] if self_candidates else None
        if best_self and best_self.get("vlm_score", 0.0) >= threshold:
            return materials, self._build_resolution_record(
                request,
                "resolved",
                best_self,
                attempt_log,
                candidate_pool,
                matched_from="self",
            )

        # Serial generation for paper2any with single integrated prompt
        runtime_contexts: dict[str, dict[str, Any]] = {}
        for source in request.get("acquisition_plan", {}).get("source_options", []):
            source_attempts = self._source_attempt_inputs(request, source)
            for attempt_index, attempt_input in enumerate(source_attempts, start=1):
                generated_paths = []
                validation_failed = False
                attempt_recorded = False
                try:
                    generated_paths = self._acquire_from_source(
                        request,
                        source,
                        attempt_input,
                        document_dir,
                    )
                except RuntimeError as e:
                    # 验证失败，尝试收集生成的图片文件
                    validation_failed = True
                    paper2any_dir = document_dir / "images" / "paper2any"
                    if paper2any_dir.exists():
                        # 查找该attempt生成的文件
                        for file in sorted(paper2any_dir.glob(f"*_attempt{attempt_index}.png")):
                            if request.get("request_id", "") in file.name:
                                generated_paths.append(str(file))
                    attempt_log.append(
                        {
                            "source": source,
                            "attempt": attempt_index,
                            "input": attempt_input,
                            "generated_paths": generated_paths,
                            "top_candidate": None,
                            "status": "validation_failed",
                            "error": str(e),
                        }
                    )
                    attempt_recorded = True
                except Exception as e:
                    attempt_log.append(
                        {
                            "source": source,
                            "attempt": attempt_index,
                            "input": attempt_input,
                            "generated_paths": [],
                            "top_candidate": None,
                            "status": "generation_failed",
                            "error": f"{type(e).__name__}: {e}",
                        }
                    )
                    attempt_recorded = True

                if generated_paths:
                    runtime_contexts.update(
                        {
                            path: self._request_context(request, source=source, attempt=attempt_index)
                            for path in generated_paths
                        }
                    )
                    materials = self.collector.collect_with_context(
                        str(document_dir),
                        markdown_text=materials.get("markdown"),
                        asset_request_contexts=runtime_contexts,
                    )
                    scored_candidates = self._score_existing_assets(
                        materials,
                        request,
                        allowed_categories={self.SOURCE_TO_CATEGORY.get(source, source)},
                        used_asset_ids=used_asset_ids,
                        only_request_bound=True,
                    )
                    candidate_pool.extend(scored_candidates)
                    best_candidate = scored_candidates[0] if scored_candidates else None

                    if not validation_failed:
                        attempt_log.append(
                            {
                                "source": source,
                                "attempt": attempt_index,
                                "input": attempt_input,
                                "generated_paths": generated_paths,
                                "top_candidate": self._compact_candidate(best_candidate),
                                "status": "resolved" if best_candidate and best_candidate.get("vlm_score", 0.0) >= threshold else "retry",
                            }
                        )
                        if best_candidate and best_candidate.get("vlm_score", 0.0) >= threshold:
                            return materials, self._build_resolution_record(
                                request,
                                "resolved",
                                best_candidate,
                                attempt_log,
                                candidate_pool,
                                matched_from=source,
                            )
                    else:
                        # 验证失败但仍然添加到候选池
                        attempt_log[-1]["top_candidate"] = self._compact_candidate(best_candidate)
                else:
                    if not attempt_recorded:
                        attempt_log.append(
                            {
                                "source": source,
                                "attempt": attempt_index,
                                "input": attempt_input,
                                "generated_paths": [],
                                "top_candidate": None,
                                "status": "no_result",
                            }
                        )

        # If no candidate meets threshold, select the best one anyway
        best_overall = candidate_pool[0] if candidate_pool else None
        status = "resolved" if best_overall else "unresolved"
        matched_from = best_overall.get("category", "none") if best_overall else "none"

        return materials, self._build_resolution_record(
            request,
            status,
            best_overall,
            attempt_log,
            candidate_pool,
            matched_from=matched_from,
        )

    def _score_existing_assets(
        self,
        materials: dict[str, Any],
        request: dict[str, Any],
        *,
        allowed_categories: set[str],
        used_asset_ids: set[str],
        only_request_bound: bool = False,
    ) -> list[dict[str, Any]]:
        descriptions = materials.get("descriptions", {})
        markdown_text = materials.get("markdown", "")
        scored_candidates: list[dict[str, Any]] = []
        for asset in materials.get("assets", []):
            if asset.get("category") not in allowed_categories:
                continue
            if request.get("asset_type") == "icon" and asset.get("asset_kind") != "icon":
                continue
            if request.get("asset_type") == "image" and asset.get("asset_kind") != "image":
                continue
            if only_request_bound:
                context = asset.get("request_context", {}) or {}
                if context.get("request_id") != request.get("request_id"):
                    continue
            description = descriptions.get(asset["path"], asset.get("description", ""))

            # Use embedding for self images, VLM for others
            if asset.get("category") == "self":
                scored = self.descriptor.score_candidate_with_embedding(
                    request,
                    asset,
                    description,
                )
            else:
                scored = self.descriptor.score_candidate(
                    request,
                    asset,
                    description,
                    markdown_text=markdown_text,
                )

            # Penalize already used images (unless icon-suitable)
            if asset.get("asset_id") in used_asset_ids:
                if not asset.get("is_icon_suitable", False):
                    scored["vlm_score"] = scored.get("vlm_score", 0.0) * 0.3
                    scored["why_selected"] = scored.get("why_selected", "") + " [WARNING: Already used in other slides]"

            scored_candidates.append(scored)
        scored_candidates.sort(key=lambda item: item.get("vlm_score", 0.0), reverse=True)
        return scored_candidates

    def _acquire_from_source(
        self,
        request: dict[str, Any],
        source: str,
        attempt_input: str,
        document_dir: Path,
    ) -> list[str]:
        if source == "paper2any":
            return self._generate_with_paper2any(request, attempt_input, document_dir)
        return []

    def _parallel_acquire_from_sources(
        self,
        request: dict[str, Any],
        document_dir: Path,
        max_workers: int = 3,
    ) -> dict[str, dict[str, Any]]:
        """Parallel generation for paper2any sources."""
        runtime_contexts: dict[str, dict[str, Any]] = {}

        # Collect all generation tasks
        tasks = []
        for source in request.get("acquisition_plan", {}).get("source_options", []):
            source_attempts = self._source_attempt_inputs(request, source)
            for attempt_index, attempt_input in enumerate(source_attempts, start=1):
                tasks.append((source, attempt_index, attempt_input))

        if not tasks:
            return runtime_contexts

        # Execute in parallel
        with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as executor:
            future_to_task = {
                executor.submit(
                    self._acquire_from_source,
                    request,
                    source,
                    attempt_input,
                    document_dir,
                ): (source, attempt_index)
                for source, attempt_index, attempt_input in tasks
            }

            for future in as_completed(future_to_task):
                source, attempt_index = future_to_task[future]
                try:
                    generated_paths = future.result()
                    if generated_paths:
                        runtime_contexts.update({
                            path: self._request_context(request, source=source, attempt=attempt_index)
                            for path in generated_paths
                        })
                except Exception as e:
                    print(f"Generation failed for {source} attempt {attempt_index}: {e}")

        return runtime_contexts

    def _generate_with_paper2any(
        self,
        request: dict[str, Any],
        prompt: str,
        document_dir: Path,
        max_retries: int = 2,
    ) -> list[str]:
        """Generate image with paper2any and validate quality with retry loop."""
        if self.image_generator is None:
            return []

        request_id = request.get("request_id", "request_image")
        asset_type = request.get("asset_type", "image")
        aspect_ratio = self._normalize_aspect_ratio(request.get("aspect_ratio_hint", "any"))
        threshold = float(request.get("minimum_vlm_score", 0.6))

        paper2any_dir = document_dir / "images" / "paper2any"
        paper2any_dir.mkdir(parents=True, exist_ok=True)

        current_prompt = prompt
        for attempt in range(1, max_retries + 1):
            output_path = paper2any_dir / f"{request_id}_{self._slug(current_prompt)[:24]}_attempt{attempt}.png"

            asyncio.run(
                self.image_generator.generate_image(
                    current_prompt,
                    str(output_path),
                    asset_type=asset_type,
                    aspect_ratio=aspect_ratio,
                )
            )

            if not output_path.exists():
                raise RuntimeError(f"Image generation failed: output not created at {output_path}")

            validation = self._validate_generated_image(str(output_path), request)
            print(f"[DEBUG] validation for {request_id} attempt {attempt}: score={validation.get('overall_score')}, issues={validation.get('issues')}")

            if validation.get("overall_score", 0.0) >= threshold:
                return [str(output_path)]

            if attempt < max_retries:
                current_prompt = self._refine_prompt_for_retry(prompt, attempt + 1, validation)

        raise RuntimeError(
            f"Generated image validation failed after {max_retries} attempts: score {validation.get('overall_score', 0.0)} < {threshold}. Issues: {validation.get('issues', [])}"
        )

    def _search_web(self, request: dict[str, Any], query: str) -> list[str]:
        if self.image_collector is None:
            return []
        count = max(1, int(request.get("acquisition_plan", {}).get("candidate_count", 3)))
        return self.image_collector.search_images(query, count=count)

    def _search_icons(self, query: str) -> list[str]:
        if self.icon_collector is None:
            return []
        return self.icon_collector.search_icons([query])

    def _bind_request_to_slide(
        self,
        ir: dict[str, Any],
        request: dict[str, Any],
        selected: dict[str, Any] | None,
    ) -> None:
        for slide in ir.get("slides", []):
            if slide.get("slide_id") != request.get("target_slide_id"):
                continue
            for visual in slide.get("visuals", []):
                if visual.get("use_request_id") != request.get("request_id"):
                    continue
                visual["selected_candidate"] = selected
                if selected and selected.get("asset_id"):
                    visual["use_existing_asset_id"] = selected["asset_id"]
            if selected and selected.get("path"):
                slide["selected_asset_path"] = selected["path"]
                slide["selected_asset_id"] = selected.get("asset_id")

    def _build_resolution_record(
        self,
        request: dict[str, Any],
        status: str,
        selected: dict[str, Any] | None,
        attempt_log: list[dict[str, Any]],
        candidate_pool: list[dict[str, Any]],
        *,
        matched_from: str,
    ) -> dict[str, Any]:
        return {
            "request_id": request.get("request_id", ""),
            "asset_type": request.get("asset_type", ""),
            "title": request.get("title", ""),
            "caption": request.get("caption", ""),
            "purpose": request.get("purpose", ""),
            "target_slide_id": request.get("target_slide_id", ""),
            "minimum_vlm_score": request.get("minimum_vlm_score", 0.7),
            "resolution_status": status,
            "matched_from": matched_from,
            "resolved_candidate": selected,
            "attempts": attempt_log,
            "candidate_pool": [self._compact_candidate(candidate) for candidate in candidate_pool[:20]],
        }

    @staticmethod
    def _compact_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
        if candidate is None:
            return None
        return {
            "asset_id": candidate.get("asset_id"),
            "path": candidate.get("path"),
            "category": candidate.get("category"),
            "vlm_score": candidate.get("vlm_score"),
            "content_score": candidate.get("content_score"),
            "geometry_score": candidate.get("geometry_score"),
            "why_selected": candidate.get("why_selected", ""),
        }

    @staticmethod
    def _request_context(request: dict[str, Any], *, source: str, attempt: int) -> dict[str, Any]:
        return {
            "request_id": request.get("request_id", ""),
            "caption": request.get("caption", ""),
            "title": request.get("title", ""),
            "purpose": request.get("purpose", ""),
            "asset_type": request.get("asset_type", ""),
            "target_slide_id": request.get("target_slide_id", ""),
            "source": source,
            "attempt": attempt,
        }

    def _source_attempt_inputs(self, request: dict[str, Any], source: str) -> list[str]:
        if source == "paper2any":
            return self._paper2any_attempt_prompts(request)
        return []

    def _paper2any_attempt_prompts(self, request: dict[str, Any]) -> list[str]:
        base = request.get("caption") or request.get("title") or request.get("purpose") or "presentation visual"
        purpose = request.get("purpose", "")
        style = ", ".join(request.get("style_keywords", []))
        aspect = request.get("aspect_ratio_hint", "any")

        # Single integrated prompt with all requirements
        integrated_prompt = f"{base}\n要求：更适合PPT，信息清晰，构图简洁，避免杂乱背景，突出单一主体或单一关系。\n用途：{purpose}\n风格：{style}\n比例偏好：{aspect}"
        return [integrated_prompt]

    @staticmethod
    def _load_existing_resolutions(resolution_path: Path) -> dict[str, dict[str, Any]]:
        if not resolution_path.exists():
            return {}
        try:
            data = json.loads(resolution_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        requests = data.get("requests", [])
        return {
            item.get("request_id", ""): item
            for item in requests
            if item.get("request_id")
        }

    @staticmethod
    def _is_reusable_resolution(record: dict[str, Any] | None) -> bool:
        if not record:
            return False
        selected = record.get("resolved_candidate") or {}
        candidate_path = selected.get("path")
        return (
            record.get("resolution_status") == "resolved"
            and bool(selected.get("asset_id"))
            and bool(candidate_path)
            and Path(candidate_path).exists()
        )

    @staticmethod
    def _write_resolution_checkpoint(resolution_path: Path, resolved_requests: list[dict[str, Any]]) -> None:
        resolution_doc = {
            "summary": {
                "request_count": len(resolved_requests),
                "resolved_count": sum(1 for item in resolved_requests if item.get("resolution_status") == "resolved"),
                "unresolved_count": sum(1 for item in resolved_requests if item.get("resolution_status") != "resolved"),
            },
            "requests": resolved_requests,
        }
        resolution_path.write_text(json.dumps(resolution_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_aspect_ratio(value: str) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"\d+:\d+", text):
            return text
        if "square" in text.lower():
            return "1:1"
        if "portrait" in text.lower() or "tall" in text.lower():
            return "3:4"
        return "16:9"

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token for token in re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", text.lower()) if len(token) > 1]

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_") or "asset"

    def _validate_generated_image(
        self,
        image_path: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate generated image using VLM 5-dimension scoring."""
        if self.descriptor is None:
            return {"pass": True, "overall_score": 1.0, "issues": []}

        return self.descriptor.validate_image(image_path, request)

    @staticmethod
    def _refine_prompt_for_retry(
        original_prompt: str,
        attempt: int,
        validation_result: dict[str, Any],
    ) -> str:
        """Refine prompt based on validation failure reasons."""
        issues = validation_result.get("issues", [])
        refinements = []

        if validation_result.get("clarity", 1.0) < 0.7:
            refinements.append("Ensure high resolution and sharp details")

        if validation_result.get("aspect_ratio_fit", 1.0) < 0.7:
            refinements.append("Strictly follow aspect ratio requirement")

        if validation_result.get("aesthetics", 1.0) < 0.7:
            refinements.append("Use clean, professional visual style")

        if validation_result.get("information_density", 1.0) < 0.6:
            refinements.append("Simplify composition, focus on single subject")

        if refinements:
            return f"{original_prompt}\n\nIMPORTANT refinements for retry {attempt}:\n" + "\n".join(
                f"- {r}" for r in refinements
            )
        return original_prompt
