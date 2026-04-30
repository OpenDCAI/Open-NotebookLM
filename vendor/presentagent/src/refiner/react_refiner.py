"""Single-slide refinement loop with graceful screenshot fallback."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from threading import Lock

from ..coder.pptx_coder import PPTXCoder
from ..llm.client import LLMClient
from .ir_projection import (
    project_vlm_view,
    project_editable_ir_view,
    merge_refined_ir_view,
)
from .vlm_checklist import build_vlm_evaluation_prompt
from .ir_refinement_prompt import build_ir_refinement_prompt
from .skill_system import SkillRegistry


# Global lock for PowerPoint COM (not thread-safe)
_powerpoint_lock = Lock()


class SlideRenderer:
    def __init__(self, coder: PPTXCoder, command_runner=None) -> None:
        self.coder = coder
        self.command_runner = command_runner or subprocess.run

    def detect_tools(self) -> dict[str, str | None]:
        office = shutil.which("soffice") or shutil.which("libreoffice")
        return {
            "aspose": "1" if self._has_aspose_slides() else None,
            "powerpoint": "1" if self._has_powerpoint_com() else None,
            "office": office,
            "pdftoppm": shutil.which("pdftoppm"),
            "pdftocairo": shutil.which("pdftocairo"),
        }

    def detect_backend(self) -> str:
        tools = self.detect_tools()
        if tools["aspose"]:
            return "aspose_pdf_png"
        # Prioritize LibreOffice over PowerPoint COM (more stable for parallel processing)
        if tools["office"] and tools["pdftoppm"]:
            return "pptx_pdf_png:pdftoppm"
        if tools["office"] and tools["pdftocairo"]:
            return "pptx_pdf_png:pdftocairo"
        if tools["powerpoint"] and tools["pdftoppm"]:
            return "powerpoint_pdf_png:pdftoppm"
        if tools["powerpoint"] and tools["pdftocairo"]:
            return "powerpoint_pdf_png:pdftocairo"
        if tools["office"]:
            return "pptx_pdf_only"
        return "code_only"

    def render(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        output_dir: str,
        *,
        slide_index: int,
        mode: str,
        skip_screenshot: bool = False,
    ) -> dict[str, Any]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        slide_id = slide_ir.get("slide_id", f"slide_{slide_index:02d}")
        pptx_path = root / f"{slide_id}.pptx"
        code_path = root / f"{slide_id}.py"
        artifact_dir = str(root / "codegen")
        self._write_render_context(
            artifact_dir,
            {
                "slide_id": slide_id,
                "slide_index": slide_index,
                "mode": mode,
                "artifact_dir": artifact_dir,
                "library_mode": mode == "library",
            },
        )

        # Use Step 4's validation approach: generate, validate, use validated PPTX
        code = self.coder.generate_slide_code_with_feedback(
            deck_ir,
            slide_ir,
            materials,
            index=slide_index,
            mode=mode,
            artifact_dir=artifact_dir,
        )

        # Save code for reference
        Path(code_path).write_text(code, encoding="utf-8")

        # Find and use the validated PPTX from validation directory
        validation_dir = Path(artifact_dir) / "validation" / slide_id
        attempt_files = sorted(validation_dir.glob("attempt_*.pptx")) if validation_dir.exists() else []

        if attempt_files:
            # Use the latest validated PPTX
            import shutil
            shutil.copy(str(attempt_files[-1]), str(pptx_path))
        else:
            raise RuntimeError(f"No validated PPTX found for {slide_id}")

        backend = self.detect_backend()
        if not skip_screenshot and backend in ("code_only", "pptx_pdf_only"):
            tools = self.detect_tools()
            raise RuntimeError(
                f"ReAct refiner requires screenshot generation. Current backend: {backend}. "
                f"Detected tools: aspose={tools['aspose']}, office={tools['office']}, "
                f"pdftoppm={tools['pdftoppm']}, pdftocairo={tools['pdftocairo']}. "
                f"Please install: LibreOffice/soffice + pdftoppm/pdftocairo, or aspose.slides"
            )

        pdf_path = None
        screenshot_path = None

        if not skip_screenshot:
            if backend == "aspose_pdf_png":
                pdf_path, screenshot_path = self._render_with_aspose(str(pptx_path), root, slide_id)
            elif backend.startswith("powerpoint_pdf_png:"):
                print(f"    [{slide_id}]   → Converting PPTX to PDF with PowerPoint COM...")
                pdf_path = self._convert_pptx_to_pdf_with_powerpoint(str(pptx_path), root)
                if pdf_path:
                    print(f"    [{slide_id}]   ✓ PDF: {pdf_path}")
                    print(f"    [{slide_id}]   → Converting PDF to PNG...")
                    screenshot_path = self._convert_pdf_to_png(pdf_path, root, slide_id, backend)
                    if screenshot_path:
                        print(f"    [{slide_id}]   ✓ PNG: {screenshot_path}")
                    else:
                        print(f"    [{slide_id}]   ✗ PNG conversion failed")
                else:
                    print(f"    [{slide_id}]   ✗ PDF conversion failed")
            elif backend.startswith("pptx_pdf_png:"):
                pdf_path = self._convert_pptx_to_pdf(str(pptx_path), root)
                if pdf_path:
                    screenshot_path = self._convert_pdf_to_png(pdf_path, root, slide_id, backend)

            if not screenshot_path:
                raise RuntimeError(f"Failed to generate screenshot. Backend: {backend}, PDF: {pdf_path}")

        return {
            "backend": backend,
            "pptx_path": str(pptx_path),
            "pdf_path": pdf_path,
            "code_path": str(code_path),
            "code": code,
            "screenshot_path": screenshot_path,
        }

    @staticmethod
    def _write_render_context(artifact_dir: str, payload: dict[str, Any]) -> None:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "render_context.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _render_with_aspose(self, pptx_path: str, output_dir: Path, slide_id: str) -> tuple[str | None, str | None]:
        slides = self._load_aspose_slides()
        if slides is None:
            return None, None

        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{Path(pptx_path).stem}.pdf"
        screenshot_path = output_dir / f"{slide_id}.png"
        try:
            with slides.Presentation(pptx_path) as presentation:
                presentation.save(str(pdf_path), slides.export.SaveFormat.PDF)
                with presentation.slides[0].get_image() as image:
                    image.save(str(screenshot_path), slides.ImageFormat.PNG)
        except Exception:
            return None, None
        return (
            str(pdf_path) if pdf_path.exists() else None,
            str(screenshot_path) if screenshot_path.exists() else None,
        )

    def _convert_pptx_to_pdf(self, pptx_path: str, output_dir: Path) -> str | None:
        office = self.detect_tools()["office"]
        if not office:
            return None

        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.command_runner(
                [
                    office,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(pdf_dir),
                    pptx_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None
        pdf_path = pdf_dir / f"{Path(pptx_path).stem}.pdf"
        return str(pdf_path) if pdf_path.exists() else None

    def _convert_pptx_to_pdf_with_powerpoint(self, pptx_path: str, output_dir: Path) -> str | None:
        """Convert PPTX to PDF using PowerPoint COM (Windows only)"""
        if not self._has_powerpoint_com():
            return None

        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{Path(pptx_path).stem}.pdf"

        # Retry up to 2 times
        max_retries = 2
        for attempt in range(max_retries + 1):
            # Use lock to prevent concurrent PowerPoint COM access
            with _powerpoint_lock:
                try:
                    import win32com.client
                    import pythoncom
                    import os

                    # Initialize COM for this thread
                    pythoncom.CoInitialize()

                    try:
                        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
                        # Don't set Visible = 0, it causes errors

                        pptx_abs = os.path.abspath(pptx_path)
                        pdf_abs = os.path.abspath(str(pdf_path))

                        presentation = powerpoint.Presentations.Open(pptx_abs, WithWindow=False)
                        presentation.SaveAs(pdf_abs, 32)  # 32 = ppSaveAsPDF
                        presentation.Close()
                        powerpoint.Quit()

                        if pdf_path.exists():
                            return str(pdf_path)

                        # PDF not created, retry
                        if attempt < max_retries:
                            print(f"    PowerPoint COM: PDF not created, retrying ({attempt + 1}/{max_retries})...")
                            continue
                        return None

                    finally:
                        # Uninitialize COM
                        pythoncom.CoUninitialize()

                except Exception as e:
                    if attempt < max_retries:
                        print(f"    PowerPoint COM failed (attempt {attempt + 1}/{max_retries + 1}): {type(e).__name__}")
                        continue
                    else:
                        print(f"    PowerPoint COM conversion failed after {max_retries + 1} attempts: {type(e).__name__}: {e}")
                        return None

        return None

    def _convert_pdf_to_png(
        self,
        pdf_path: str,
        output_dir: Path,
        slide_id: str,
        backend: str,
    ) -> str | None:
        screenshot_base = output_dir / slide_id
        try:
            if backend.endswith("pdftoppm"):
                pdftoppm = self.detect_tools()["pdftoppm"]
                if not pdftoppm:
                    return None
                self.command_runner(
                    [
                        pdftoppm,
                        "-f",
                        "1",
                        "-singlefile",
                        "-png",
                        str(pdf_path),
                        str(screenshot_base),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            else:
                pdftocairo = self.detect_tools()["pdftocairo"]
                if not pdftocairo:
                    return None
                self.command_runner(
                    [
                        pdftocairo,
                        "-png",
                        "-f",
                        "1",
                        "-singlefile",
                        str(pdf_path),
                        str(screenshot_base),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
        except subprocess.CalledProcessError:
            return None
        screenshot_path = f"{screenshot_base}.png"
        return screenshot_path if Path(screenshot_path).exists() else None

    @staticmethod
    def _has_aspose_slides() -> bool:
        try:
            return importlib.util.find_spec("aspose.slides") is not None
        except (ModuleNotFoundError, ImportError):
            return False

    @staticmethod
    def _has_powerpoint_com() -> bool:
        """Check if PowerPoint COM is available (Windows only)"""
        try:
            import platform
            if platform.system() != "Windows":
                return False
            import win32com.client
            return True
        except (ImportError, Exception):
            return False

    @staticmethod
    def _load_aspose_slides():
        if not SlideRenderer._has_aspose_slides():
            return None
        return importlib.import_module("aspose.slides")


class ReactRefiner:
    def __init__(
        self,
        llm_client: LLMClient,
        vlm_client: LLMClient | None = None,
        coder: PPTXCoder | None = None,
        renderer: SlideRenderer | None = None,
        material_resolver = None,
        max_iterations: int = 3,
        threshold: float = 7.0,
        max_workers: int = 4,
        library_react_skill: str = "none",
    ) -> None:
        self.llm_client = llm_client
        self.vlm_client = vlm_client or llm_client
        self.coder = coder
        self.renderer = renderer or (SlideRenderer(coder) if coder else None)
        self.material_resolver = material_resolver
        self.max_iterations = max_iterations
        self.threshold = threshold
        self.max_workers = max_workers
        self.library_react_skill = str(library_react_skill or "none").strip() or "none"

    @staticmethod
    def _normalize_evaluation_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
        if "score" in feedback and "feedback" in feedback:
            normalized = dict(feedback)
            normalized.setdefault("strengths", [])
            return normalized

        normalized = dict(feedback)
        raw_score = normalized.get("overall_score", normalized.get("score", 0.0))
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0

        issue_summaries: list[str] = []
        for issue in normalized.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            description = str(issue.get("description", "")).strip()
            suggestion = str(issue.get("suggestion", "")).strip()
            summary = description
            if suggestion:
                summary = f"{summary} Suggestion: {suggestion}" if summary else f"Suggestion: {suggestion}"
            if summary:
                issue_summaries.append(summary)

        feedback_text = normalized.get("feedback")
        if not feedback_text:
            if issue_summaries:
                feedback_text = " | ".join(issue_summaries)
            elif normalized.get("skipped_vlm"):
                feedback_text = "VLM evaluation skipped"
            else:
                feedback_text = "No evaluation feedback"

        normalized["score"] = score
        normalized["feedback"] = str(feedback_text)
        normalized.setdefault("strengths", [])
        return normalized


    def refine_deck(
        self,
        deck_ir: dict[str, Any],
        materials: dict[str, Any],
        output_dir: str,
        *,
        mode: str = "direct",
        progress_callback=None,
    ) -> dict[str, Any]:
        total_slides = len(deck_ir.get("slides", []))
        current_slides = [json.loads(json.dumps(slide_ir, ensure_ascii=False)) for slide_ir in deck_ir.get("slides", [])]
        per_slide_history: list[list[dict[str, Any]]] = [[] for _ in current_slides]
        active_indices = list(range(len(current_slides)))
        checkpoint_root = Path(output_dir) / "refine" / "checkpoints"
        checkpoint_root.mkdir(parents=True, exist_ok=True)

        # Load checkpoints or infer from existing refine directories
        slides_need_round0 = []
        slides_can_reuse = {}  # slide_pos -> artifacts
        for index, slide_ir in enumerate(current_slides):
            checkpoint = self._load_slide_checkpoint(checkpoint_root, slide_ir)
            if checkpoint:
                current_slides[index] = checkpoint.get("slide_ir", slide_ir)
                per_slide_history[index] = checkpoint.get("history", [])

                # Check if can reuse artifacts (signature match)
                current_sig = self._slide_signature(slide_ir, mode)
                checkpoint_sig = checkpoint.get("signature")
                artifacts = checkpoint.get("artifacts")

                if checkpoint_sig == current_sig and artifacts:
                    # Signature matches, can reuse artifacts
                    slides_can_reuse[index] = artifacts
                    print(f"  [slide_{index + 1:02d}] Reusing artifacts (signature match)")

                if checkpoint.get("complete"):
                    active_indices.remove(index)
            else:
                # Fallback: infer progress from existing refine directories
                inferred = self._infer_slide_progress(output_dir, slide_ir, deck_ir, index)
                if inferred:
                    per_slide_history[index] = inferred["history"]
                    if inferred.get("complete"):
                        active_indices.remove(index)
                else:
                    # No history found, need to run round 0
                    slides_need_round0.append(index)

        # Round 0: Only evaluate slides without existing round 0 data
        if slides_need_round0:
            # Copy original IR to round_00 for validation scripts
            round_00_dir = Path(output_dir) / "refine" / "round_00"
            round_00_ir_dir = round_00_dir / "ir" / "final"
            round_00_ir_dir.mkdir(parents=True, exist_ok=True)
            original_ir_path = Path(output_dir) / "ir" / "final" / "final_ir.json"
            if original_ir_path.exists():
                import shutil
                shutil.copy2(original_ir_path, round_00_ir_dir / "final_ir.json")
                print(f"  [Round 0] Copied original IR to {round_00_ir_dir / 'final_ir.json'}")

            print(f"\n[React Round 0] Evaluating {len(slides_need_round0)} initial slides...")
            round_results = self._evaluate_initial_pptx(
                deck_ir,
                current_slides,
                output_dir,
                active_indices=slides_need_round0,
            )
            for slide_pos in slides_need_round0:
                result = round_results[slide_pos]
                slide_id = current_slides[slide_pos].get("slide_id", f"slide_{slide_pos + 1:02d}")
                print(f"  [{slide_id}] Score: {result['evaluation']['score']:.1f} | {result['evaluation']['feedback'][:80]}...")
                per_slide_history[slide_pos].append({"iteration": 0, **result["evaluation"], **result["render"]})
                if progress_callback is not None:
                    progress_callback(
                        slide_pos + 1,
                        self.max_iterations * max(total_slides, 1),
                        f"round 0/{self.max_iterations} slide {slide_pos + 1}/{total_slides} score {result['evaluation']['score']}",
                    )

        # Filter out slides that already meet threshold after round 0
        active_indices = [
            slide_pos for slide_pos in active_indices
            if per_slide_history[slide_pos] and per_slide_history[slide_pos][-1]["score"] < self.threshold
        ]

        # Determine starting round based on existing history
        start_round = 1
        for slide_pos in active_indices:
            if per_slide_history[slide_pos]:
                last_iteration = per_slide_history[slide_pos][-1].get("iteration", 0)
                start_round = max(start_round, last_iteration + 1)

        for step in range(start_round, self.max_iterations + 1):
            if not active_indices:
                break

            print(f"\n[React Round {step}] Refining {len(active_indices)} slides...")
            is_last_round = (step == self.max_iterations)
            refine_round_dir = Path(output_dir) / "refine" / f"round_{step:02d}"
            refine_round_dir.mkdir(parents=True, exist_ok=True)

            # Save current deck_ir to round directory (not overwriting ir/final/)
            # Validation scripts will read from refine/round_XX/ir/final/final_ir.json
            round_ir_dir = refine_round_dir / "ir" / "final"
            round_ir_dir.mkdir(parents=True, exist_ok=True)
            round_deck_ir = dict(deck_ir)
            round_deck_ir["slides"] = current_slides
            (round_ir_dir / "final_ir.json").write_text(
                json.dumps(round_deck_ir, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            # Check for existing artifacts in this round (resume support)
            round_results = {}
            remaining_indices = []
            for slide_pos in active_indices:
                slide_ir = current_slides[slide_pos]
                slide_id = slide_ir.get("slide_id", f"slide_{slide_pos + 1:02d}")
                slide_round_dir = refine_round_dir / slide_id

                # Check if this slide already has complete artifacts
                pptx_file = slide_round_dir / f"{slide_id}.pptx"
                feedback_file = slide_round_dir / "feedback.json"
                png_file = slide_round_dir / f"{slide_id}.png"

                if pptx_file.exists() and feedback_file.exists():
                    # Load existing artifacts
                    try:
                        feedback = self._normalize_evaluation_feedback(
                            json.loads(feedback_file.read_text(encoding="utf-8"))
                        )
                        render = {
                            "backend": "reused_from_round",
                            "pptx_path": str(pptx_file),
                            "pdf_path": str(slide_round_dir / "pdf" / f"{slide_id}.pdf") if (slide_round_dir / "pdf" / f"{slide_id}.pdf").exists() else None,
                            "code_path": str(slide_round_dir / f"{slide_id}.py") if (slide_round_dir / f"{slide_id}.py").exists() else "",
                            "code": "",
                            "screenshot_path": str(png_file) if png_file.exists() else None,
                        }
                        round_results[slide_pos] = {"render": render, "evaluation": feedback}
                        print(f"  [{slide_id}] Reusing artifacts from round {step} (already completed)")
                    except Exception as e:
                        print(f"  [{slide_id}] Failed to load existing artifacts: {e}, will regenerate")
                        remaining_indices.append(slide_pos)
                else:
                    remaining_indices.append(slide_pos)

            # Only process slides that don't have artifacts yet
            if remaining_indices:
                new_results, materials = self._refine_code_round_parallel(
                    deck_ir,
                    current_slides,
                    materials,
                    output_dir,
                    active_indices=remaining_indices,
                    round_num=step,
                    skip_evaluation=is_last_round,
                    mode=mode,
                    reusable_artifacts=slides_can_reuse,
                )
                # Merge new results with reused results
                round_results.update(new_results)

            next_active_indices: list[int] = []
            for slide_pos in active_indices:
                result = round_results[slide_pos]
                slide_id = current_slides[slide_pos].get("slide_id", f"slide_{slide_pos + 1:02d}")
                score = result["evaluation"]["score"]
                feedback_preview = result["evaluation"]["feedback"][:60]
                print(f"  [{slide_id}] Score: {score:.1f} | {feedback_preview}...")
                per_slide_history[slide_pos].append({"iteration": step, **result["evaluation"], **result["render"]})
                if progress_callback is not None:
                    completed = min((step - 1) * total_slides + slide_pos + 1, self.max_iterations * max(total_slides, 1))
                    progress_callback(
                        completed,
                        self.max_iterations * max(total_slides, 1),
                        f"round {step}/{self.max_iterations} slide {slide_pos + 1}/{total_slides} score {result['evaluation']['score']}",
                    )
                if result["evaluation"]["score"] >= self.threshold:
                    artifacts = {
                        "pptx_path": result["render"].get("pptx_path"),
                        "pdf_path": result["render"].get("pdf_path"),
                        "png_path": result["render"].get("screenshot_path"),
                        "code_path": result["render"].get("code_path"),
                    }
                    self._persist_slide_checkpoint(
                        checkpoint_root,
                        current_slides[slide_pos],
                        per_slide_history[slide_pos],
                        complete=True,
                        mode=mode,
                        artifacts=artifacts,
                    )
                    continue
                # Continue to next round for refinement
                artifacts = {
                    "pptx_path": result["render"].get("pptx_path"),
                    "pdf_path": result["render"].get("pdf_path"),
                    "png_path": result["render"].get("screenshot_path"),
                    "code_path": result["render"].get("code_path"),
                }
                self._persist_slide_checkpoint(
                    checkpoint_root,
                    current_slides[slide_pos],
                    per_slide_history[slide_pos],
                    complete=step >= self.max_iterations,
                    mode=mode,
                    artifacts=artifacts,
                )
                next_active_indices.append(slide_pos)
            active_indices = next_active_indices

        slides = []
        history = []
        for index, slide_ir in enumerate(current_slides, start=1):
            metadata = dict(slide_ir.get("metadata", {}))
            metadata["stage"] = "refined"
            slide_ir["metadata"] = metadata
            slides.append(slide_ir)
            slide_history = per_slide_history[index - 1]
            history.append(
                {
                    "slide_id": slide_ir.get("slide_id", f"slide_{index:02d}"),
                    "iterations": len(slide_history),
                    "final_score": slide_history[-1]["score"] if slide_history else None,
                }
            )
        refined_deck = dict(deck_ir)
        refined_deck["slides"] = slides
        metadata = dict(refined_deck.get("metadata", {}))
        metadata["stage"] = "refined"
        refined_deck["metadata"] = metadata
        refined_deck["refinement_history"] = history

        # Save refined deck IR
        refined_ir_dir = Path(output_dir) / "ir" / "refined"
        refined_ir_dir.mkdir(parents=True, exist_ok=True)

        # Save deck_ir.json (deck-level info only, without slides array)
        deck_only = {k: v for k, v in refined_deck.items() if k != "slides"}
        (refined_ir_dir / "deck_ir.json").write_text(
            json.dumps(deck_only, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Save final_ir.json (complete: deck + all refined slides)
        (refined_ir_dir / "final_ir.json").write_text(
            json.dumps(refined_deck, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Save individual slide IRs
        refined_slides_dir = refined_ir_dir / "slides"
        refined_slides_dir.mkdir(parents=True, exist_ok=True)
        for slide_ir in current_slides:
            slide_id = slide_ir.get("slide_id", "slide")
            (refined_slides_dir / f"{slide_id}.json").write_text(
                json.dumps(slide_ir, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        # Save updated materials manifest
        materials_dir = Path(output_dir) / "materials"
        materials_dir.mkdir(parents=True, exist_ok=True)
        (materials_dir / "refined_manifest.json").write_text(
            json.dumps(materials, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Assemble final PPTX from refined slides
        print(f"\n[React] Assembling final PPTX from refined slides...")
        final_pptx_path = self._assemble_refined_deck(output_dir, current_slides, history, mode=mode)
        print(f"[React] Final PPTX saved: {final_pptx_path}")

        return {"ir": refined_deck, "history": history, "final_pptx": final_pptx_path}

    def _refine_code_round_parallel(
        self,
        deck_ir: dict[str, Any],
        current_slides: list[dict[str, Any]],
        materials: dict[str, Any],
        output_dir: str,
        *,
        active_indices: list[int],
        round_num: int,
        skip_evaluation: bool = False,
        mode: str = "direct",
        reusable_artifacts: dict[int, dict[str, str]] | None = None,
    ) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
        """Refine IR based on previous round VLM feedback. Returns (results, updated_materials)."""
        results: dict[int, dict[str, Any]] = {}
        prev_round_dir = Path(output_dir) / "refine" / f"round_{round_num - 1:02d}"
        curr_round_dir = Path(output_dir) / "refine" / f"round_{round_num:02d}"
        checkpoint_root = Path(output_dir) / "refine" / "checkpoints"
        reusable_artifacts = reusable_artifacts or {}

        # Parallel processing structure (like step4)
        max_workers = self.max_workers
        max_workers = min(max(max_workers, 1), len(active_indices)) if active_indices else 1

        if max_workers <= 1:
            # Serial processing
            for slide_pos in active_indices:
                try:
                    slide_ir = current_slides[slide_pos]
                    slide_id = slide_ir.get("slide_id", f"slide_{slide_pos + 1:02d}")

                    # Check if can reuse artifacts
                    artifacts = reusable_artifacts.get(slide_pos)
                    if artifacts and Path(artifacts.get("pptx_path", "")).exists():
                        print(f"    [{slide_id}] Reusing artifacts from previous round (signature match)")
                        import shutil

                        curr_slide_dir = curr_round_dir / slide_id
                        curr_slide_dir.mkdir(parents=True, exist_ok=True)

                        # Copy artifacts
                        shutil.copy2(artifacts["pptx_path"], curr_slide_dir / f"{slide_id}.pptx")
                        if artifacts.get("pdf_path"):
                            pdf_dir = curr_slide_dir / "pdf"
                            pdf_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(artifacts["pdf_path"], pdf_dir / f"{slide_id}.pdf")
                        if artifacts.get("png_path"):
                            shutil.copy2(artifacts["png_path"], curr_slide_dir / f"{slide_id}.png")
                        if artifacts.get("code_path"):
                            shutil.copy2(artifacts["code_path"], curr_slide_dir / f"{slide_id}.py")

                        # Reuse evaluation
                        evaluation = {"score": 10.0, "feedback": "Reused from cache (no changes)", "strengths": ["Unchanged"]}
                        render = {
                            "backend": f"reused_round_{round_num}",
                            "pptx_path": str(curr_slide_dir / f"{slide_id}.pptx"),
                            "pdf_path": artifacts.get("pdf_path"),
                            "code_path": str(curr_slide_dir / f"{slide_id}.py"),
                            "code": "",
                            "screenshot_path": artifacts.get("png_path"),
                        }
                        results[slide_pos] = {"render": render, "evaluation": evaluation}
                        continue

                    print(f"    [{slide_id}] Loading feedback from round {round_num - 1}...")

                    prev_slide_dir = prev_round_dir / slide_id
                    curr_slide_dir = curr_round_dir / slide_id
                    curr_slide_dir.mkdir(parents=True, exist_ok=True)

                    # Load previous feedback
                    prev_feedback = self._load_previous_feedback(
                        prev_round_dir=prev_round_dir,
                        checkpoint_root=checkpoint_root,
                        slide_ir=slide_ir,
                        round_num=round_num,
                    )

                    # Build history
                    history = {
                        "iteration": round_num,
                        "previous_feedback": [prev_feedback]
                    }

                    # LLM refines IR
                    print(f"    [{slide_id}] LLM refining IR based on feedback...")
                    refined_ir, updated_materials, refinement_issues = self._refine_slide_ir_with_llm(
                        deck_ir,
                        slide_ir,
                        prev_feedback,
                        materials,
                        history,
                        mode=mode,
                    )

                    # Add refinement issues to feedback
                    if refinement_issues:
                        prev_feedback["refinement_issues"] = refinement_issues
                        print(f"    [{slide_id}] Warning: {len(refinement_issues)} refinement issues")

                    # Update current_slides and materials
                    current_slides[slide_pos] = refined_ir
                    materials = updated_materials

                    # Save refined IR
                    slide_ir_file = curr_slide_dir / "slide_ir.json"
                    slide_ir_file.write_text(json.dumps(refined_ir, ensure_ascii=False, indent=2), encoding="utf-8")

                    if mode == "library":
                        print(f"    [{slide_id}] Regenerating library slide from refined IR...")
                    else:
                        print(f"    [{slide_id}] Generating code with validation loop...")
                    render, evaluation = self._render_and_evaluate_refined_slide(
                        deck_ir,
                        refined_ir,
                        materials,
                        curr_slide_dir,
                        curr_round_dir,
                        slide_pos,
                        round_num,
                        history,
                        mode=mode,
                        skip_evaluation=skip_evaluation,
                    )
                    if not skip_evaluation and render.get("screenshot_path"):
                        print(f"    [{slide_id}] VLM score: {evaluation['score']:.1f}")

                    results[slide_pos] = {"render": render, "evaluation": evaluation}

                except Exception as e:
                    import traceback
                    error_msg = f"{type(e).__name__}: {e}"
                    print(f"    [{slide_id}] ✗ ERROR: {error_msg}")
                    print(f"    [{slide_id}] Traceback:\n{traceback.format_exc()}")
                    # Record failure so we don't get KeyError later
                    results[slide_pos] = {
                        "render": {
                            "backend": "failed",
                            "pptx_path": "",
                            "pdf_path": None,
                            "code_path": "",
                            "code": "",
                            "screenshot_path": None,
                        },
                        "evaluation": {
                            "score": 0.0,
                            "feedback": f"Processing failed: {error_msg}",
                            "strengths": [],
                        }
                    }
        else:
            # Parallel processing
            def process_single_slide(slide_pos):
                """Process a single slide and return (slide_pos, result, updated_materials_or_none)"""
                try:
                    slide_ir = current_slides[slide_pos]
                    slide_id = slide_ir.get("slide_id", f"slide_{slide_pos + 1:02d}")

                    # Check if can reuse artifacts
                    artifacts = reusable_artifacts.get(slide_pos)
                    if artifacts and Path(artifacts.get("pptx_path", "")).exists():
                        print(f"    [{slide_id}] Reusing artifacts from previous round (signature match)")
                        import shutil

                        curr_slide_dir = curr_round_dir / slide_id
                        curr_slide_dir.mkdir(parents=True, exist_ok=True)

                        # Copy artifacts
                        shutil.copy2(artifacts["pptx_path"], curr_slide_dir / f"{slide_id}.pptx")
                        if artifacts.get("pdf_path"):
                            pdf_dir = curr_slide_dir / "pdf"
                            pdf_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(artifacts["pdf_path"], pdf_dir / f"{slide_id}.pdf")
                        if artifacts.get("png_path"):
                            shutil.copy2(artifacts["png_path"], curr_slide_dir / f"{slide_id}.png")
                        if artifacts.get("code_path"):
                            shutil.copy2(artifacts["code_path"], curr_slide_dir / f"{slide_id}.py")

                        # Reuse evaluation
                        evaluation = {"score": 10.0, "feedback": "Reused from cache (no changes)", "strengths": ["Unchanged"]}
                        render = {
                            "backend": f"reused_round_{round_num}",
                            "pptx_path": str(curr_slide_dir / f"{slide_id}.pptx"),
                            "pdf_path": artifacts.get("pdf_path"),
                            "code_path": str(curr_slide_dir / f"{slide_id}.py"),
                            "code": "",
                            "screenshot_path": artifacts.get("png_path"),
                        }
                        return (slide_pos, {"render": render, "evaluation": evaluation}, None)

                    print(f"    [{slide_id}] Loading feedback from round {round_num - 1}...")

                    prev_slide_dir = prev_round_dir / slide_id
                    curr_slide_dir = curr_round_dir / slide_id
                    curr_slide_dir.mkdir(parents=True, exist_ok=True)

                    # Load previous feedback
                    prev_feedback = self._load_previous_feedback(
                        prev_round_dir=prev_round_dir,
                        checkpoint_root=checkpoint_root,
                        slide_ir=slide_ir,
                        round_num=round_num,
                    )

                    # Build history
                    history = {
                        "iteration": round_num,
                        "previous_feedback": [prev_feedback]
                    }

                    # LLM refines IR
                    print(f"    [{slide_id}] LLM refining IR based on feedback...")
                    refined_ir, updated_materials, refinement_issues = self._refine_slide_ir_with_llm(
                        deck_ir,
                        slide_ir,
                        prev_feedback,
                        materials,
                        history,
                        mode=mode,
                    )

                    # Add refinement issues to feedback
                    if refinement_issues:
                        prev_feedback["refinement_issues"] = refinement_issues
                        print(f"    [{slide_id}] Warning: {len(refinement_issues)} refinement issues")

                    # Save refined IR
                    slide_ir_file = curr_slide_dir / "slide_ir.json"
                    slide_ir_file.write_text(json.dumps(refined_ir, ensure_ascii=False, indent=2), encoding="utf-8")

                    if mode == "library":
                        print(f"    [{slide_id}] Regenerating library slide from refined IR...")
                    else:
                        print(f"    [{slide_id}] Generating code with validation loop...")
                    render, evaluation = self._render_and_evaluate_refined_slide(
                        deck_ir,
                        refined_ir,
                        materials,
                        curr_slide_dir,
                        curr_round_dir,
                        slide_pos,
                        round_num,
                        history,
                        mode=mode,
                        skip_evaluation=skip_evaluation,
                    )
                    if not skip_evaluation and render.get("screenshot_path"):
                        print(f"    [{slide_id}] VLM score: {evaluation['score']:.1f}")

                    return (slide_pos, {"render": render, "evaluation": evaluation}, (slide_pos, refined_ir, updated_materials))

                except Exception as e:
                    import traceback
                    error_msg = f"{type(e).__name__}: {e}"
                    slide_id = current_slides[slide_pos].get("slide_id", f"slide_{slide_pos + 1:02d}")
                    print(f"    [{slide_id}] ✗ ERROR: {error_msg}")
                    print(f"    [{slide_id}] Traceback:\n{traceback.format_exc()}")
                    return (slide_pos, {
                        "render": {
                            "backend": "failed",
                            "pptx_path": "",
                            "pdf_path": None,
                            "code_path": "",
                            "code": "",
                            "screenshot_path": None,
                        },
                        "evaluation": {
                            "score": 0.0,
                            "feedback": f"Processing failed: {error_msg}",
                            "strengths": [],
                        }
                    }, None)

            # Submit all tasks
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_single_slide, slide_pos): slide_pos for slide_pos in active_indices}

                for future in as_completed(futures):
                    slide_pos, result, update_info = future.result()
                    results[slide_pos] = result

                    # Update current_slides and materials if needed
                    if update_info:
                        pos, refined_ir, updated_materials = update_info
                        current_slides[pos] = refined_ir
                        materials = updated_materials

        return results, materials


    def _evaluate_initial_pptx(
        self,
        deck_ir: dict[str, Any],
        current_slides: list[dict[str, Any]],
        output_dir: str,
        *,
        active_indices: list[int],
    ) -> dict[int, dict[str, Any]]:
        """Round 0: Copy validation artifacts to refine_00 and evaluate."""
        import shutil
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Find validation directory
        validation_dir = Path(output_dir) / "code" / "generated" / "validation"
        if not validation_dir.exists():
            raise RuntimeError(f"Validation directory not found: {validation_dir}")

        # Create round_00 directory
        round_00_dir = Path(output_dir) / "refine" / "round_00"
        round_00_dir.mkdir(parents=True, exist_ok=True)

        results: dict[int, dict[str, Any]] = {}

        # Determine parallelism
        max_workers = self.max_workers
        max_workers = min(max(max_workers, 1), len(active_indices)) if active_indices else 1

        def process_single_slide(slide_pos):
            """Process a single slide in round 0."""
            slide_ir = current_slides[slide_pos]
            slide_id = slide_ir.get("slide_id", f"slide_{slide_pos + 1:02d}")

            # Create slide directory in round_00
            slide_refine_dir = round_00_dir / slide_id
            slide_refine_dir.mkdir(parents=True, exist_ok=True)

            # Find validation artifacts (use latest attempt)
            slide_validation_dir = validation_dir / slide_id
            if not slide_validation_dir.exists():
                raise RuntimeError(f"Validation dir not found for {slide_id}: {slide_validation_dir}")

            validation_pptx_files = sorted(slide_validation_dir.glob("attempt_*.pptx"))
            validation_py_files = sorted(slide_validation_dir.glob("attempt_*.py"))

            if not validation_pptx_files or not validation_py_files:
                raise RuntimeError(f"No validation artifacts found for {slide_id}")

            # Copy latest PPTX and code
            source_pptx = validation_pptx_files[-1]
            source_code = validation_py_files[-1]
            target_pptx = slide_refine_dir / f"{slide_id}.pptx"
            target_code = slide_refine_dir / f"{slide_id}.py"

            shutil.copy2(source_pptx, target_pptx)
            shutil.copy2(source_code, target_code)

            # Convert to PDF and PNG
            backend = self.renderer.detect_backend()
            print(f"  [{slide_id}] Converting PPTX to screenshot (backend: {backend})...")
            pdf_path = None
            screenshot_path = None

            if backend.startswith("powerpoint_pdf_png:"):
                print(f"  [{slide_id}]   → Converting PPTX to PDF with PowerPoint COM...")
                pdf_path = self.renderer._convert_pptx_to_pdf_with_powerpoint(str(target_pptx), slide_refine_dir)
                if pdf_path:
                    print(f"  [{slide_id}]   ✓ PDF: {pdf_path}")
                    print(f"  [{slide_id}]   → Converting PDF to PNG...")
                    screenshot_path = self.renderer._convert_pdf_to_png(pdf_path, slide_refine_dir, slide_id, backend)
                    if screenshot_path:
                        print(f"  [{slide_id}]   ✓ PNG: {screenshot_path}")
                    else:
                        print(f"  [{slide_id}]   ✗ PNG conversion failed")
                else:
                    print(f"  [{slide_id}]   ✗ PDF conversion failed")
            elif backend.startswith("pptx_pdf_png:"):
                print(f"  [{slide_id}]   → Converting PPTX to PDF...")
                pdf_path = self.renderer._convert_pptx_to_pdf(str(target_pptx), slide_refine_dir)
                if pdf_path:
                    print(f"  [{slide_id}]   ✓ PDF: {pdf_path}")
                    print(f"  [{slide_id}]   → Converting PDF to PNG...")
                    screenshot_path = self.renderer._convert_pdf_to_png(pdf_path, slide_refine_dir, slide_id, backend)
                    if screenshot_path:
                        print(f"  [{slide_id}]   ✓ PNG: {screenshot_path}")
                    else:
                        print(f"  [{slide_id}]   ✗ PNG conversion failed")
                else:
                    print(f"  [{slide_id}]   ✗ PDF conversion failed")

            if not screenshot_path:
                print(f"  [{slide_id}]   ⚠ Screenshot generation failed, skipping VLM evaluation")
                # Create a fallback evaluation indicating code generation failure
                evaluation = {
                    "overall_score": 0,
                    "issues": [
                        {
                            "category": "code_execution",
                            "severity": "critical",
                            "description": "PPTX generation failed - code has execution errors",
                            "suggestion": "Fix code syntax and runtime errors to generate valid PPTX"
                        }
                    ],
                    "strengths": [],
                    "needs_refinement": True,
                    "skipped_vlm": True  # Flag to indicate VLM was skipped
                }
                code_content = target_code.read_text(encoding="utf-8") if target_code.exists() else ""
            else:
                # Read code for VLM
                code_content = target_code.read_text(encoding="utf-8")

                # VLM evaluation (round 0, no history)
                evaluation = self._evaluate_with_vlm_and_code(
                    deck_ir,
                    slide_ir,
                    screenshot_path,
                    code_content,
                    history=None
                )

            evaluation = self._normalize_evaluation_feedback(evaluation)

            # Save feedback
            feedback_file = slide_refine_dir / "feedback.json"
            import json
            feedback_file.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")

            # Save slide IR (initial, unmodified)
            slide_ir_file = slide_refine_dir / "slide_ir.json"
            slide_ir_file.write_text(json.dumps(slide_ir, ensure_ascii=False, indent=2), encoding="utf-8")

            render = {
                "backend": f"{backend}_round_0",
                "pptx_path": str(target_pptx),
                "pdf_path": pdf_path,
                "code_path": str(target_code),
                "code": code_content,
                "screenshot_path": screenshot_path,
            }

            return (slide_pos, {"render": render, "evaluation": evaluation})

        # Execute serial or parallel
        if max_workers <= 1:
            # Serial processing
            for slide_pos in active_indices:
                pos, result = process_single_slide(slide_pos)
                results[pos] = result
        else:
            # Parallel processing
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_single_slide, slide_pos): slide_pos for slide_pos in active_indices}
                for future in as_completed(futures):
                    pos, result = future.result()
                    results[pos] = result

        return results

    @staticmethod
    def _slide_signature(slide_ir: dict[str, Any], mode: str) -> str:
        """Calculate signature for slide IR to detect changes."""
        from hashlib import md5
        payload = json.dumps({"slide_ir": slide_ir, "mode": mode}, ensure_ascii=False, sort_keys=True)
        return md5(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _slide_checkpoint_path(checkpoint_root: Path, slide_ir: dict[str, Any]) -> Path:
        slide_id = slide_ir.get("slide_id", "slide")
        return checkpoint_root / f"{slide_id}.json"

    def _load_slide_checkpoint(self, checkpoint_root: Path, slide_ir: dict[str, Any]) -> dict[str, Any] | None:
        checkpoint_path = self._slide_checkpoint_path(checkpoint_root, slide_ir)
        if not checkpoint_path.exists():
            return None
        try:
            return json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _persist_slide_checkpoint(
        self,
        checkpoint_root: Path,
        slide_ir: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        complete: bool,
        mode: str = "direct",
        artifacts: dict[str, str] | None = None,
    ) -> None:
        checkpoint_path = self._slide_checkpoint_path(checkpoint_root, slide_ir)
        checkpoint_data = {
            "slide_id": slide_ir.get("slide_id", "slide"),
            "signature": self._slide_signature(slide_ir, mode),
            "complete": complete,
            "history": history,
            "slide_ir": slide_ir,
        }
        if artifacts:
            checkpoint_data["artifacts"] = artifacts
        checkpoint_path.write_text(
            json.dumps(checkpoint_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


    def _infer_slide_progress(
        self,
        output_dir: str,
        slide_ir: dict[str, Any],
        deck_ir: dict[str, Any],
        slide_index: int,
    ) -> dict[str, Any] | None:
        """Infer slide progress from existing refine directories."""
        slide_id = slide_ir.get("slide_id", f"slide_{slide_index + 1:02d}")
        refine_root = Path(output_dir) / "refine"

        if not refine_root.exists():
            return None

        history = []
        last_round = -1

        # Check which rounds exist
        for round_num in range(self.max_iterations + 1):
            round_dir = refine_root / f"round_{round_num:02d}" / slide_id
            feedback_file = round_dir / "feedback.json"

            if not feedback_file.exists():
                break

            try:
                feedback_data = json.loads(feedback_file.read_text(encoding="utf-8"))
                history.append({
                    "iteration": round_num,
                    "score": feedback_data.get("score", 0.0),
                    "feedback": feedback_data.get("feedback", ""),
                    "strengths": feedback_data.get("strengths", []),
                })
                last_round = round_num
            except (json.JSONDecodeError, FileNotFoundError):
                break

        if not history:
            return None

        # Check if last round met threshold
        last_score = history[-1]["score"]
        complete = last_score >= self.threshold or last_round >= self.max_iterations

        return {"history": history, "complete": complete}

    def _render_and_evaluate_refined_slide(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        materials: dict[str, Any],
        curr_slide_dir: Path,
        curr_round_dir: Path,
        slide_pos: int,
        round_num: int,
        history: dict[str, Any],
        *,
        mode: str,
        skip_evaluation: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        slide_id = slide_ir.get("slide_id", f"slide_{slide_pos + 1:02d}")
        artifact_dir = str(curr_round_dir)
        code = self.coder.generate_slide_code_with_feedback(
            deck_ir,
            slide_ir,
            materials,
            index=slide_pos + 1,
            mode=mode,
            artifact_dir=artifact_dir,
        )

        validation_dir = Path(artifact_dir) / "validation" / slide_id
        validated_pptx_files = sorted(validation_dir.glob("attempt_*.pptx"))
        if not validated_pptx_files:
            raise RuntimeError(f"No validated PPTX found for {slide_id}")

        shutil.copy2(validated_pptx_files[-1], curr_slide_dir / f"{slide_id}.pptx")
        (curr_slide_dir / f"{slide_id}.py").write_text(code, encoding="utf-8")

        pdf_path = None
        screenshot_path = None
        if not skip_evaluation:
            backend = self.renderer.detect_backend()
            curr_pptx_file = curr_slide_dir / f"{slide_id}.pptx"
            if backend.startswith("powerpoint_pdf_png:"):
                pdf_path = self.renderer._convert_pptx_to_pdf_with_powerpoint(str(curr_pptx_file), curr_slide_dir)
                if pdf_path:
                    screenshot_path = self.renderer._convert_pdf_to_png(pdf_path, curr_slide_dir, slide_id, backend)
            elif backend.startswith("pptx_pdf_png:"):
                pdf_path = self.renderer._convert_pptx_to_pdf(str(curr_pptx_file), curr_slide_dir)
                if pdf_path:
                    screenshot_path = self.renderer._convert_pdf_to_png(pdf_path, curr_slide_dir, slide_id, backend)
            elif backend == "aspose_pdf_png":
                pdf_path, screenshot_path = self.renderer._render_with_aspose(
                    str(curr_pptx_file),
                    curr_slide_dir,
                    slide_id,
                )

        render = {
            "backend": f"ir_refine_round_{round_num}:{mode}",
            "pptx_path": str(curr_slide_dir / f"{slide_id}.pptx"),
            "pdf_path": pdf_path,
            "code_path": str(curr_slide_dir / f"{slide_id}.py"),
            "code": code,
            "screenshot_path": screenshot_path,
        }

        evaluation = {"score": 0.0, "feedback": "Final round - no evaluation", "strengths": []}
        if not skip_evaluation:
            screenshot_path = render.get("screenshot_path")
            if screenshot_path:
                evaluation = self._evaluate_with_vlm_and_code(
                    deck_ir,
                    slide_ir,
                    screenshot_path,
                    render.get("code", ""),
                    history,
                )
                feedback_file = curr_slide_dir / "feedback.json"
                feedback_file.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                print(f"    [{slide_id}] ✗ Screenshot generation failed, skipping VLM evaluation")

        return render, evaluation

    def _evaluate_with_vlm_and_code(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        screenshot_path: str,
        code_content: str,
        history: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """VLM evaluates screenshot using industrial checklist + IR view."""
        with open(screenshot_path, "rb") as f:
            image_url = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

        # Project VLM view
        vlm_view = project_vlm_view(deck_ir, slide_ir, history)

        # Build prompt with checklist
        prompt = build_vlm_evaluation_prompt(
            vlm_view,
            image_url,
            iteration=history.get("iteration", 0) if history else 0
        )

        # Retry VLM call up to 3 times with sleep
        import time
        max_retries = 2  # 0, 1, 2 = 3 attempts total
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = self.vlm_client.chat_with_image(prompt, image_url)
                return self._parse_evaluation_response(response, source="VLM evaluation")
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    sleep_time = 2 * (attempt + 1)  # 2s, 4s
                    print(f"    VLM evaluation failed (attempt {attempt + 1}/{max_retries + 1}): {type(e).__name__}, retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                    continue
                else:
                    # Final failure - terminate process
                    error_msg = f"VLM evaluation failed after {max_retries + 1} attempts: {type(e).__name__}: {e}"
                    print(f"    {error_msg}")
                    print(f"    Terminating process due to repeated VLM failures.")
                    raise SystemExit(error_msg) from e


    def _refine_slide_ir_with_llm(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        vlm_feedback: dict[str, Any],
        materials: dict[str, Any],
        history: dict[str, Any] | None = None,
        *,
        mode: str = "direct",
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Use LLM to refine slide IR based on VLM feedback.

        Returns:
            (refined_slide_ir, updated_materials, refinement_issues)
        """
        history = history or {}
        refinement_issues = []

        # 1. Project editable IR view
        editable_view = project_editable_ir_view(slide_ir)

        # 2. Get available tools
        available_tools = SkillRegistry.list_skills()

        # 3. LLM generates action plan (IR modifications + tool calls)
        prompt = build_ir_refinement_prompt(
            editable_view,
            vlm_feedback,
            history,
            available_tools,
            mode=mode,
            library_react_skill=self.library_react_skill,
        )
        response = self.llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format="json",
        )

        # 4. Parse action plan
        try:
            action_plan = self._extract_json(response, source="IR refinement")
        except RuntimeError as exc:
            if not self._should_retry_qwen_library_refinement(mode):
                raise
            repaired_response = self._repair_qwen_library_refinement_json(
                response,
                slide_ir=slide_ir,
                error=exc,
            )
            action_plan = self._extract_json(repaired_response, source="IR refinement repair")
        action_plan = self._sanitize_refinement_action_plan(action_plan, slide_ir, mode=mode)

        # 5. Apply IR modifications
        ir_modifications = action_plan.get("ir_modifications", {})
        refined_ir = merge_refined_ir_view(slide_ir, ir_modifications)

        # 6. Execute tool calls
        tool_calls = action_plan.get("tool_calls", [])
        if tool_calls:
            refined_ir, materials, issues = self._execute_tool_calls(
                refined_ir,
                slide_ir,  # ← pass original for rollback
                tool_calls,
                materials,
                deck_ir
            )
            refinement_issues.extend(issues)

        return refined_ir, materials, refinement_issues

    def _sanitize_refinement_action_plan(
        self,
        action_plan: dict[str, Any],
        slide_ir: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        normalized = dict(action_plan or {})
        if self._looks_like_top_level_slide_patch(normalized):
            normalized = {
                "ir_modifications": normalized,
                "tool_calls": [],
            }
        ir_modifications = normalized.get("ir_modifications")
        normalized["ir_modifications"] = dict(ir_modifications) if isinstance(ir_modifications, dict) else {}
        tool_calls = normalized.get("tool_calls")
        normalized["tool_calls"] = tool_calls if isinstance(tool_calls, list) else []

        if mode != "library" or self._model_profile() != "qwen":
            return normalized

        original_visuals = slide_ir.get("visuals") or []
        has_bound_visual = any(
            (visual.get("selected_candidate") or {}).get("asset_id")
            or (visual.get("selected_candidate") or {}).get("path")
            or slide_ir.get("selected_asset_path")
            for visual in original_visuals
        )
        clears_visuals = normalized["ir_modifications"].get("visuals") == []
        has_collect_material = any(call.get("tool") == "collect_material" for call in normalized["tool_calls"])

        if has_bound_visual and clears_visuals and not has_collect_material:
            normalized["ir_modifications"].pop("visuals", None)

        return normalized

    def _should_retry_qwen_library_refinement(self, mode: str) -> bool:
        return mode == "library" and self._model_profile() == "qwen"

    def _repair_qwen_library_refinement_json(
        self,
        raw_response: str,
        *,
        slide_ir: dict[str, Any],
        error: Exception,
    ) -> str:
        repair_prompt = f"""You are repairing malformed JSON from a slide IR refinement step.

Target slide: {slide_ir.get("slide_id", "slide")}
Previous parse error: {error}

Rules:
- Return one JSON object only.
- Preserve the original meaning; fix syntax only.
- If the input is a top-level slide patch, keep it as a top-level slide patch.
- Do not add explanations, markdown, or comments.
- Use double-quoted JSON strings and valid commas/brackets.

Malformed JSON to repair:
{raw_response}
"""
        return self.llm_client.chat(
            [{"role": "user", "content": repair_prompt}],
            temperature=0.0,
            response_format="json",
        )

    def _model_profile(self) -> str:
        llm_client = getattr(self, "llm_client", None)
        fallback_skill = getattr(self, "library_react_skill", "none")
        model_profile = getattr(llm_client, "model_profile", None)
        if model_profile is None and fallback_skill == "qwen_v1":
            model_profile = "qwen"
        return str(model_profile or "general").strip().lower() or "general"

    @staticmethod
    def _looks_like_top_level_slide_patch(action_plan: dict[str, Any]) -> bool:
        if not isinstance(action_plan, dict):
            return False
        if "ir_modifications" in action_plan or "tool_calls" in action_plan:
            return False
        slide_patch_keys = {
            "slide_id",
            "title",
            "subtitle",
            "core_message",
            "layout",
            "blocks",
            "visuals",
            "design_notes",
        }
        return bool(slide_patch_keys & set(action_plan.keys()))

    def _execute_tool_calls(
        self,
        slide_ir: dict[str, Any],
        original_ir: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        materials: dict[str, Any],
        deck_ir: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Execute tool calls from LLM action plan.

        Returns:
            (updated_slide_ir, updated_materials, refinement_issues)
        """
        from pathlib import Path

        document_dir = materials.get("document_dir", ".")
        used_asset_ids = set()
        refinement_issues = []
        tool_execution_failed = False

        for tool_call in tool_calls:
            tool_name = tool_call.get("tool")
            params = tool_call.get("params", {})

            # Get skill from registry
            skill = SkillRegistry.get(tool_name)
            if not skill:
                refinement_issues.append({
                    "type": "unknown_tool",
                    "tool": tool_name,
                    "message": f"Unknown tool '{tool_name}'"
                })
                tool_execution_failed = True
                continue

            # Execute skill
            if tool_name == "collect_material":
                try:
                    result = skill.execute(
                        material_request=params.get("material_request"),
                        materials=materials,
                        document_dir=document_dir,
                        used_asset_ids=used_asset_ids,
                    )

                    if result["success"]:
                        materials = result["updated_materials"]
                        selected_candidate = result["selected_candidate"]

                        # Update visual binding
                        replace_visual_id = params.get("replace_visual_id")
                        if replace_visual_id and selected_candidate:
                            binding_success = self._update_visual_binding(
                                slide_ir,
                                replace_visual_id,
                                selected_candidate
                            )
                            if not binding_success:
                                refinement_issues.append({
                                    "type": "visual_binding_failed",
                                    "visual_id": replace_visual_id,
                                    "message": f"visual_id '{replace_visual_id}' not found in slide_ir"
                                })
                                tool_execution_failed = True
                            elif selected_candidate.get("asset_id"):
                                used_asset_ids.add(selected_candidate["asset_id"])
                    else:
                        refinement_issues.append({
                            "type": "material_collection_failed",
                            "request_id": params.get("material_request", {}).get("request_id"),
                            "message": result.get("error", "Material collection failed")
                        })
                        tool_execution_failed = True
                except Exception as e:
                    refinement_issues.append({
                        "type": "tool_execution_error",
                        "tool": tool_name,
                        "message": str(e)
                    })
                    tool_execution_failed = True

        # If any tool failed, rollback all IR modifications
        if tool_execution_failed:
            print(f"[WARN] Tool execution failed, rolling back IR modifications")
            slide_ir = original_ir

        return slide_ir, materials, refinement_issues

    def _update_visual_binding(
        self,
        slide_ir: dict[str, Any],
        visual_id: str,
        new_candidate: dict[str, Any],
    ) -> bool:
        """Update visual binding with new material candidate.

        Returns:
            True if binding succeeded, False if visual_id not found
        """
        visuals = slide_ir.get("visuals", [])

        for visual in visuals:
            if visual.get("slot_id") == visual_id:
                visual["selected_candidate"] = new_candidate
                return True

        # visual_id not found
        available_slots = [v.get("slot_id") for v in visuals]
        print(f"[WARN] visual_id '{visual_id}' not found. Available: {available_slots}")
        return False

    def _parse_evaluation_response(self, response: str, source: str) -> dict[str, Any]:
        data = self._extract_json(response, source=source)
        if not isinstance(data, dict):
            raise RuntimeError(f"{source} did not return a JSON object.")
        missing = [key for key in ("score", "feedback", "strengths") if key not in data]
        if missing:
            raise RuntimeError(f"{source} JSON missing required fields: {', '.join(missing)}")
        try:
            data["score"] = float(data["score"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{source} score is not numeric: {data.get('score')!r}") from exc
        if not isinstance(data["feedback"], str):
            data["feedback"] = str(data["feedback"]) if data["feedback"] is not None else ""
        if not isinstance(data["strengths"], list):
            data["strengths"] = [] if data["strengths"] is None else [data["strengths"]]
        return data

    @staticmethod
    def _load_previous_feedback(
        prev_round_dir: Path,
        checkpoint_root: Path,
        slide_ir: dict[str, Any],
        round_num: int,
    ) -> dict[str, Any]:
        slide_id = slide_ir.get("slide_id", "slide")
        refine_root = prev_round_dir.parent

        for candidate_round in range(round_num - 1, -1, -1):
            feedback_file = refine_root / f"round_{candidate_round:02d}" / slide_id / "feedback.json"
            if not feedback_file.exists():
                continue
            try:
                return ReactRefiner._normalize_evaluation_feedback(
                    json.loads(feedback_file.read_text(encoding="utf-8"))
                )
            except json.JSONDecodeError:
                continue

        checkpoint_path = checkpoint_root / f"{slide_id}.json"
        if checkpoint_path.exists():
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                checkpoint = None
            if isinstance(checkpoint, dict):
                history = checkpoint.get("history") or []
                for entry in reversed(history):
                    if entry.get("iteration", -1) >= round_num:
                        continue
                    if "feedback" not in entry and "overall_score" not in entry and "score" not in entry:
                        continue
                    return ReactRefiner._normalize_evaluation_feedback(entry)

        raise RuntimeError(f"Missing feedback before round {round_num} for {slide_id}")

    @staticmethod
    def _extract_json(response: str, source: str) -> dict[str, Any]:
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", response)
        if fenced_match:
            response = fenced_match.group(1)
        else:
            start = response.find("{")
            if start == -1:
                raise RuntimeError(f"{source} did not return JSON: {response[:400]}")
            response = ReactRefiner._slice_first_json_object(response[start:])
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(response)
            return obj
        except json.JSONDecodeError as exc:
            repaired = ReactRefiner._balance_json_text(response)
            repaired = re.sub(r",(?=\s*[}\]])", "", repaired)
            try:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(repaired)
                return obj
            except json.JSONDecodeError:
                raise RuntimeError(f"{source} JSON parsing failed: {exc}\nResponse snippet: {response[:400]}") from exc

    @staticmethod
    def _slice_first_json_object(text: str) -> str:
        stack: list[str] = []
        in_string = False
        escape = False

        for index, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]":
                if not stack or ch != stack[-1]:
                    break
                stack.pop()
                if not stack:
                    return text[: index + 1]

        return text

    @staticmethod
    def _balance_json_text(text: str) -> str:
        stack: list[str] = []
        in_string = False
        escape = False

        for ch in text:
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]" and stack and ch == stack[-1]:
                stack.pop()

        balanced = text
        if in_string:
            balanced += '"'
        if stack:
            balanced += "".join(reversed(stack))
        return balanced

    @staticmethod
    def _fix_code_paths(code: str, script_dir: Path, output_dir: str) -> str:
        """Fix paths in generated code for refine round location.

        Code in refine/round_XX/slide_XX/ needs to go up 3 levels to output_dir.
        The coder generates code assuming validation/ location (4 levels up).
        Replace 4-level parent chain with 3-level for refine location.
        """
        # Replace: script_dir.parent.parent.parent.parent
        # With:    script_dir.parent.parent.parent
        code = code.replace(
            "script_dir.parent.parent.parent.parent",
            "script_dir.parent.parent.parent"
        )
        return code

    def _assemble_refined_deck(
        self,
        output_dir: str,
        current_slides: list[dict[str, Any]],
        history: list[dict[str, Any]],
        *,
        mode: str = "direct",
    ) -> str:
        """Assemble final PPTX from refined slides."""
        refine_root = Path(output_dir) / "refine"
        final_path = Path(output_dir) / "refined_final.pptx"
        code_refined_dir = Path(output_dir) / "code" / "refined"
        code_refined_dir.mkdir(parents=True, exist_ok=True)
        slides_dir = code_refined_dir / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        print(f"[React] Collecting slide functions from refined rounds...")

        # Collect slide functions (same as Step 4 logic)
        slide_functions_by_index: dict[int, str] = {}
        for index, (slide_ir, slide_history) in enumerate(zip(current_slides, history), start=1):
            slide_id = slide_ir.get("slide_id", f"slide_{index:02d}")
            iterations = slide_history.get("iterations", 0)

            source_code, _source_pptx, round_num = self._find_latest_successful_slide_artifacts(
                refine_root,
                slide_id,
                iterations=iterations,
            )

            # Read and store slide function
            code_content = source_code.read_text(encoding="utf-8")
            function_name = self.coder._extract_function_name(code_content)
            code_content = self.coder._clean_code_block(code_content, function_name)

            # Remove orchestrator code if present (from Round 0 slides)
            orchestrator_start = code_content.find("\ndef build_presentation(")
            if orchestrator_start != -1:
                code_content = code_content[:orchestrator_start].rstrip()

            slide_functions_by_index[index] = code_content

            # Copy to slides directory
            import shutil
            shutil.copy2(source_code, slides_dir / f"{slide_id}.py")
            print(f"[React]   Copied {slide_id}.py from round_{round_num:02d}")

        # Build slide_functions list in order
        slide_functions = [slide_functions_by_index[i] for i in range(1, len(current_slides) + 1) if i in slide_functions_by_index]

        # Load complete deck IR from ir/refined/final_ir.json
        print(f"[React] Loading refined deck IR...")
        refined_ir_path = Path(output_dir) / "ir" / "refined" / "final_ir.json"
        if not refined_ir_path.exists():
            raise RuntimeError(f"Refined IR not found: {refined_ir_path}")
        deck_ir = json.loads(refined_ir_path.read_text(encoding="utf-8"))

        # Load materials
        print(f"[React] Loading materials manifest...")
        materials_path = Path(output_dir) / "materials" / "material_manifest.json"
        materials = json.loads(materials_path.read_text(encoding="utf-8"))

        # Generate build_deck.py with custom IR path
        print(f"[React] Generating build_deck.py...")
        final_code = self._build_refined_deck_script(
            deck_ir,
            materials,
            slide_functions,
            output_path=str(final_path),
            mode=mode,
        )

        # Save build_deck.py
        build_deck_path = code_refined_dir / "build_deck.py"
        build_deck_path.write_text(final_code, encoding="utf-8")
        print(f"[React] Saved build_deck.py: {build_deck_path}")

        # Execute build_deck.py
        print(f"[React] Executing build_deck.py...")
        build_deck_code = build_deck_path.read_text(encoding="utf-8")
        success = self.coder.execute_code(build_deck_code, str(final_path), script_path=str(build_deck_path))
        if not success:
            raise RuntimeError("Failed to generate refined PPTX from build_deck.py")

        return str(final_path)

    @staticmethod
    def _find_latest_successful_slide_artifacts(
        refine_root: Path,
        slide_id: str,
        *,
        iterations: int,
    ) -> tuple[Path, Path, int]:
        for round_num in range(iterations, -1, -1):
            slide_dir = refine_root / f"round_{round_num:02d}" / slide_id
            slide_code = slide_dir / f"{slide_id}.py"
            slide_pptx = slide_dir / f"{slide_id}.pptx"
            if slide_code.exists() and slide_pptx.exists():
                return slide_code, slide_pptx, round_num

            validation_dir = refine_root / f"round_{round_num:02d}" / "validation" / slide_id
            if validation_dir.exists():
                attempt_indices: list[int] = []
                for attempt_path in validation_dir.glob("attempt_*.py"):
                    stem = attempt_path.stem
                    try:
                        attempt_indices.append(int(stem.split("_")[-1]))
                    except ValueError:
                        continue
                for attempt_num in sorted(attempt_indices, reverse=True):
                    attempt_code = validation_dir / f"attempt_{attempt_num:02d}.py"
                    attempt_pptx = validation_dir / f"attempt_{attempt_num:02d}.pptx"
                    if attempt_code.exists() and attempt_pptx.exists():
                        return attempt_code, attempt_pptx, round_num

        raise RuntimeError(f"No successful code/pptx artifact pair found for {slide_id} in refine rounds")

    def _build_refined_deck_script(
        self,
        deck_ir: dict[str, Any],
        materials: dict[str, Any],
        slide_functions: list[str],
        output_path: str,
        mode: str = "direct",
    ) -> str:
        """Build build_deck.py script for refined deck (reads from ir/refined/)."""
        # Extract function names
        function_names = []
        for slide_function in slide_functions:
            match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", slide_function)
            if match:
                function_names.append(match.group(1))

        imports = self.coder._build_import_block(mode)

        # Build orchestrator
        body_lines = []
        if mode == "direct":
            body_lines.extend([
                "    prs.slide_width = Inches(13.33)",
                "    prs.slide_height = Inches(7.5)",
            ])
        body_lines.extend(
            [
                "",
                "    deck_ir = json.loads((doc_dir / 'ir' / 'refined' / 'final_ir.json').read_text(encoding='utf-8'))",
                "    materials = json.loads((doc_dir / 'materials' / 'material_manifest.json').read_text(encoding='utf-8'))",
                "",
            ]
        )

        for idx, name in enumerate(function_names):
            body_lines.append(f"    slide_ir = deck_ir['slides'][{idx}]")
            body_lines.append(f"    {name}(prs, deck_ir, slide_ir, materials)")

        orchestrator = "\n".join(body_lines)
        slide_functions_code = "\n\n".join(slide_functions)

        # Output path
        output_filename = Path(output_path).name

        return f"""# -*- coding: utf-8 -*-
import json
from pathlib import Path

{imports}

{slide_functions_code}

# Calculate paths relative to script location
script_dir = Path(__file__).parent
doc_dir = script_dir.parent.parent

def build_presentation(output_path):
    prs = {self.coder._presentation_constructor(mode)}
{orchestrator}
    prs.save(output_path)


# Output path
output_path = str(doc_dir / "{output_filename}")
build_presentation(output_path)
"""
