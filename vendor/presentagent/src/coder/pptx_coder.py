"""LLM-driven PPT code generation."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import md5
from pathlib import Path
from typing import Any, Dict

from ..llm.client import LLMClient
from ..refiner.ir_projection import project_coder_view
from .library_skill_profiles import (
    build_library_generation_repair_hint,
    build_library_generation_skill_prompt,
)


class PPTXCoder:
    def __init__(
        self,
        client: LLMClient,
        *,
        max_workers: int = 1,
        max_attempts: int = 3,
        mode: str = "direct",
        library_generation_skill: str = "none",
    ):
        self.client = client
        self.max_workers = max_workers
        self.max_attempts = max_attempts
        self.mode = mode  # "direct" or "library"
        self.library_generation_skill = str(library_generation_skill or "none").strip() or "none"

    def generate_and_render(
        self,
        ir: Dict[str, Any],
        materials: Dict[str, Any],
        output_path: str,
        mode: str = "library",
        save_code_path: str | None = None,
        artifact_dir: str | None = None,
        progress_callback=None,
    ) -> str:
        code = self.generate_code(
            ir,
            materials,
            mode=mode,
            progress_callback=progress_callback,
            artifact_dir=artifact_dir,
        )
        if save_code_path:
            Path(save_code_path).write_text(code, encoding="utf-8")

        # Regenerate build_deck.py with correct output path
        if artifact_dir:
            slide_functions_by_index: dict[int, str] = {}
            for index, slide_ir in enumerate(ir.get("slides", []), start=1):
                slide_id = slide_ir.get("slide_id", f"slide_{index:02d}")
                slide_path = Path(artifact_dir) / "slides" / f"{slide_id}.py"
                if slide_path.exists():
                    slide_function = slide_path.read_text(encoding="utf-8")
                    slide_functions_by_index[index] = slide_function

            slide_functions = [slide_functions_by_index[i] for i in range(1, len(ir.get("slides", [])) + 1) if i in slide_functions_by_index]
            final_code = self._build_final_script(ir, materials, slide_functions, mode, output_path=output_path)
            self._persist_deck_script(artifact_dir, final_code)

        if progress_callback is not None:
            progress_callback("execute", 1, 1, f"execute build_deck.py -> {output_path}")

        # Execute build_deck.py to generate PPTX
        if artifact_dir:
            build_deck_path = Path(artifact_dir) / "build_deck.py"
            if build_deck_path.exists():
                build_deck_code = build_deck_path.read_text(encoding="utf-8")
                success = self.execute_code(build_deck_code, output_path, script_path=str(build_deck_path))
                if not success:
                    raise RuntimeError("build_deck.py execution failed")
            else:
                raise RuntimeError(f"build_deck.py not found at {build_deck_path}")
        else:
            raise RuntimeError("artifact_dir required for PPTX generation")

        return code

    def generate_slide_script(
        self,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        index: int,
        mode: str = "library",
        artifact_dir: str | None = None,
        progress_callback=None,
    ) -> str:
        slide_function = self.generate_slide_code_with_feedback(
            deck_ir,
            slide_ir,
            materials,
            index=index,
            mode=mode,
            artifact_dir=artifact_dir,
        )
        if progress_callback is not None:
            progress_callback("codegen", index, 1, slide_ir.get("slide_id", f"slide_{index:02d}"))
        single_deck = dict(deck_ir)
        single_deck["slides"] = [slide_ir]
        # Detect if we're in React round environment
        for_react_round = artifact_dir and ("refine" in str(artifact_dir) and "round_" in str(artifact_dir))
        code = self._build_script(single_deck, materials, [slide_function], mode, artifact_dir=artifact_dir, for_react_round=for_react_round)
        if artifact_dir:
            self._persist_deck_script(artifact_dir, code, file_name=f"{slide_ir.get('slide_id', f'slide_{index:02d}')}.deck.py")
        return code

    def render_single_slide(
        self,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        output_path: str,
        *,
        index: int,
        mode: str = "library",
        save_code_path: str | None = None,
        artifact_dir: str | None = None,
        progress_callback=None,
    ) -> str:
        code = self.generate_slide_script(
            deck_ir,
            slide_ir,
            materials,
            index=index,
            mode=mode,
            artifact_dir=artifact_dir,
            progress_callback=progress_callback,
        )
        if save_code_path:
            Path(save_code_path).write_text(code, encoding="utf-8")
        if progress_callback is not None:
            progress_callback("execute", 1, 1, slide_ir.get("slide_id", f"slide_{index:02d}"))
        success = self.execute_code(code, output_path, script_path=save_code_path)
        if not success:
            raise RuntimeError("Generated single-slide PPT code execution failed.")
        return code

    def generate_code(
        self,
        ir: Dict[str, Any],
        materials: Dict[str, Any],
        mode: str = "library",
        artifact_dir: str | None = None,
        progress_callback=None,
    ) -> str:
        total_slides = len(ir.get("slides", []))
        slide_functions_by_index: dict[int, str] = {}
        pending: list[tuple[int, Dict[str, Any], str | None]] = []

        for index, slide_ir in enumerate(ir.get("slides", []), start=1):
            seed_function = self._load_existing_slide_function(
                artifact_dir,
                slide_ir,
                function_name=f"build_slide_{index:02d}",
            )
            pending.append((index, slide_ir, seed_function))

        max_workers = min(max(self.max_workers, 1), len(pending)) if pending else 1
        if max_workers <= 1:
            for index, slide_ir, seed_function in pending:
                slide_function = self.generate_slide_code_with_feedback(
                    ir,
                    slide_ir,
                    materials,
                    index=index,
                    mode=mode,
                    artifact_dir=artifact_dir,
                    seed_code=seed_function,
                )
                slide_functions_by_index[index] = slide_function
                if progress_callback is not None:
                    progress_callback("codegen", len(slide_functions_by_index), max(total_slides, 1), slide_ir.get("slide_id", f"slide_{index:02d}"))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(
                        self.generate_slide_code_with_feedback,
                        ir,
                        slide_ir,
                        materials,
                        index,
                        mode,
                        artifact_dir,
                        seed_function,
                    ): (index, slide_ir)
                    for index, slide_ir, seed_function in pending
                }
                for future in as_completed(future_map):
                    index, slide_ir = future_map[future]
                    slide_function = future.result()
                    slide_functions_by_index[index] = slide_function
                    if progress_callback is not None:
                        progress_callback("codegen", len(slide_functions_by_index), max(total_slides, 1), slide_ir.get("slide_id", f"slide_{index:02d}"))

        slide_functions = [slide_functions_by_index[index] for index in range(1, total_slides + 1) if index in slide_functions_by_index]
        code = self._build_script(ir, materials, slide_functions, mode, artifact_dir=artifact_dir)
        if artifact_dir:
            # Save assembled script for reference/debugging (not executed - final PPTX is assembled from validated slides)
            final_code = self._build_final_script(ir, materials, slide_functions, mode)
            self._persist_deck_script(artifact_dir, final_code)
        return code

    def generate_slide_code(
        self,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        index: int,
        mode: str = "library",
    ) -> str:
        function_name = f"build_slide_{index:02d}"
        prompt = self._build_slide_prompt(deck_ir, slide_ir, materials, function_name, mode)
        code = self.client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return self._clean_code_block(code, function_name)

    def generate_slide_code_with_feedback(
        self,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        index: int,
        mode: str = "library",
        artifact_dir: str | None = None,
        seed_code: str | None = None,
    ) -> str:
        function_name = f"build_slide_{index:02d}"
        slide_id = slide_ir.get("slide_id", f"slide_{index:02d}")
        cached = self._load_cached_validated_slide_function(
            artifact_dir=artifact_dir,
            slide_ir=slide_ir,
            function_name=function_name,
            mode=mode,
        )
        if cached is not None:
            print(f"[{slide_id}] Using cached validated code")
            return cached
        previous_code = self._clean_code_block(seed_code, function_name) if seed_code else None
        last_error = ""
        fragment_error_reset = False  # Track if we've already reset due to fragment error
        is_fragment_retry = False  # Track if current attempt is after fragment error
        attempt = 1

        while attempt <= self.max_attempts:
            try:
                if previous_code is None:
                    print(f"[{slide_id}] Attempt {attempt}/{self.max_attempts}: Generating code...")
                    candidate_code = self.generate_slide_code(deck_ir, slide_ir, materials, index=index, mode=mode)
                elif attempt == 1 and seed_code is not None:
                    print(f"[{slide_id}] Attempt {attempt}/{self.max_attempts}: Using seed code")
                    candidate_code = previous_code
                else:
                    print(f"[{slide_id}] Attempt {attempt}/{self.max_attempts}: Repairing code (error: {last_error[:80]}...)")
                    repair_prompt = self._build_slide_repair_prompt(
                        deck_ir=deck_ir,
                        slide_ir=slide_ir,
                        materials=materials,
                        function_name=function_name,
                        mode=mode,
                        previous_code=previous_code,
                        error_message=last_error,
                        is_fragment_retry=is_fragment_retry,
                    )
                    repaired = self.client.chat(
                        [{"role": "user", "content": repair_prompt}],
                        temperature=0.2,
                    )
                    candidate_code = self._clean_code_block(repaired, function_name)
                    is_fragment_retry = False  # Reset flag after use
            except RuntimeError as e:
                # Handle "function fragment" error
                if "did not return the expected function" in str(e) and not fragment_error_reset:
                    print(f"[{slide_id}] Code fragment error detected, resetting attempts with context preserved...")
                    fragment_error_reset = True
                    is_fragment_retry = True  # Mark next attempt as fragment retry
                    # Keep previous_code and last_error for context
                    attempt = 1  # Reset to attempt 1
                    continue
                else:
                    # Re-raise if not fragment error or already reset once
                    raise

            print(f"[{slide_id}] Validating code...")
            validation = self._validate_slide_function(
                deck_ir=deck_ir,
                slide_ir=slide_ir,
                materials=materials,
                slide_function=candidate_code,
                index=index,
                mode=mode,
                artifact_dir=artifact_dir,
                attempt=attempt,
            )
            if validation["success"]:
                print(f"[{slide_id}] SUCCESS: PPTX generated at {validation['output_path']}")
                if artifact_dir:
                    self._persist_slide_function(artifact_dir, slide_ir, candidate_code)
                    self._persist_slide_cache_metadata(
                        artifact_dir, slide_ir, mode=mode, validated=True, pptx_path=validation["output_path"]
                    )
                return candidate_code

            print(f"[{slide_id}] FAILED: {validation['error']}")
            previous_code = candidate_code
            last_error = validation["error"]
            attempt += 1  # Increment attempt counter

        # All attempts failed - terminate process
        slide_id = slide_ir.get("slide_id", f"slide_{index:02d}")
        error_msg = f"Slide code validation failed for {slide_id} after {self.max_attempts} attempts: {last_error}"
        print(f"[{slide_id}] {error_msg}")
        print(f"[{slide_id}] Terminating process due to repeated code generation failures.")
        raise SystemExit(error_msg)

    @staticmethod
    def _assemble_pptx_from_slides(validation_dir: Path | None, output_path: str, total_slides: int) -> None:
        """Assemble final PPTX from validated slide files."""
        from copy import deepcopy
        from pptx import Presentation

        if not validation_dir:
            raise RuntimeError("artifact_dir required for PPTX assembly")

        prs = Presentation()

        for i in range(1, total_slides + 1):
            slide_id = f"slide_{i:02d}"
            slide_dir = validation_dir / slide_id

            if not slide_dir.exists():
                raise RuntimeError(f"Slide directory not found: {slide_dir}")

            # Find the latest attempt PPTX file
            attempt_files = sorted(slide_dir.glob("attempt_*.pptx"))
            if not attempt_files:
                raise RuntimeError(f"No attempt PPTX found in: {slide_dir}")

            slide_pptx_path = attempt_files[-1]  # Get the latest attempt

            source_prs = Presentation(str(slide_pptx_path))
            if not source_prs.slides:
                continue

            source_slide = source_prs.slides[0]
            blank_layout = prs.slide_layouts[6]
            new_slide = prs.slides.add_slide(blank_layout)

            # Copy all shapes from source slide
            for shape in source_slide.shapes:
                el = shape.element
                newel = deepcopy(el)
                new_slide.shapes._spTree.insert_element_before(newel, 'p:extLst')

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        prs.save(output_path)

    def execute_code(self, code: str, output_path: str, script_path: str | None = None) -> bool:
        success, error = self.execute_code_with_error(code, output_path, script_path=script_path)
        if not success:
            print(f"Execution error: {error}")
        return success

    @staticmethod
    def execute_code_with_error(code: str, output_path: str, script_path: str | None = None) -> tuple[bool, str]:
        import sys
        original_stdout = sys.stdout
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            exec_globals = {"output_path": output_path}
            if script_path:
                exec_globals["__file__"] = script_path
            exec(code, exec_globals)
            return True, ""
        except (ModuleNotFoundError, ImportError) as exc:
            return False, f"ImportError: {exc}. Use only allowed imports: pptx, pptx.util, pptx.dml.color, pptx.enum.text, pptx.enum.chart, pptx.enum.shapes, pptx.chart.data."
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            sys.stdout = original_stdout

    def _build_final_script(
        self,
        deck_ir: Dict[str, Any],
        materials: Dict[str, Any],
        slide_functions: list[str],
        mode: str,
        output_path: str | None = None,
    ) -> str:
        """Build final script for build_deck.py with correct path resolution."""
        imports = self._build_import_block(mode)
        function_names = [self._extract_function_name(slide_function) for slide_function in slide_functions]

        body_lines = []
        if mode == "direct":
            body_lines.extend(["    prs.slide_width = Inches(13.33)", "    prs.slide_height = Inches(7.5)"])

        # Load data from files - correct path for build_deck.py location (code/generated/)
        body_lines.insert(0, "    from pathlib import Path")
        body_lines.insert(1, "    script_dir = Path(__file__).parent")
        body_lines.insert(2, "    doc_dir = script_dir.parent.parent")  # Up 2 levels to outputs/2025.acl-demo.7/
        body_lines.insert(3, "    deck_ir = json.loads((doc_dir / 'ir' / 'final' / 'final_ir.json').read_text(encoding='utf-8'))")
        body_lines.insert(4, "    materials = json.loads((doc_dir / 'materials' / 'material_manifest.json').read_text(encoding='utf-8'))")
        body_lines.insert(5, "")

        for idx, name in enumerate(function_names):
            body_lines.append(f"    slide_ir = deck_ir['slides'][{idx}]")
            body_lines.append(f"    {name}(prs, deck_ir, slide_ir, materials)")

        if not body_lines:
            body_lines = ["    pass"]
        orchestrator = "\n".join(body_lines)
        slide_functions_code = "\n\n".join(slide_functions)

        # Generate output_path line
        if output_path:
            # Extract filename from output_path and use doc_dir
            output_filename = Path(output_path).name
            output_line = f'output_path = str(doc_dir / "{output_filename}")'
        else:
            output_line = 'output_path = str(doc_dir / "output.pptx")'

        return f"""# -*- coding: utf-8 -*-
import json

{imports}

{slide_functions_code}

def build_presentation(output_path):
    prs = {self._presentation_constructor(mode)}
{orchestrator}
    prs.save(output_path)


# Output path relative to script location
from pathlib import Path as _Path
doc_dir = _Path(__file__).parent.parent.parent
{output_line}
build_presentation(output_path)
"""

    def _build_script(
        self,
        deck_ir: Dict[str, Any],
        materials: Dict[str, Any],
        slide_functions: list[str],
        mode: str,
        artifact_dir: str | None = None,
        for_react_round: bool = False,
        slide_index_offset: int = 0,
    ) -> str:
        imports = self._build_import_block(mode)
        function_names = [self._extract_function_name(slide_function) for slide_function in slide_functions]

        # Generate slide functions
        body_lines = []
        if mode == "direct":
            body_lines.extend(
                [
                    "    prs.slide_width = Inches(13.33)",
                    "    prs.slide_height = Inches(7.5)",
                ]
            )

        # Load data from files
        body_lines.insert(0, f"    from pathlib import Path")
        body_lines.insert(1, f"    script_dir = Path(__file__).parent")
        if for_react_round:
            # React round: script in refine/round_XX/validation/slide_XX/
            # Read IR from refine/round_XX/ir/final/final_ir.json
            # Read materials from outputs/xxx/materials/material_manifest.json
            body_lines.insert(2, f"    round_dir = script_dir.parent.parent")
            body_lines.insert(3, f"    output_root = round_dir.parent.parent")
            body_lines.insert(4, f"    deck_ir = json.loads((round_dir / 'ir' / 'final' / 'final_ir.json').read_text(encoding='utf-8'))")
            body_lines.insert(5, f"    materials = json.loads((output_root / 'materials' / 'material_manifest.json').read_text(encoding='utf-8'))")
            body_lines.insert(6, "")
        else:
            # Step 4: script in code/generated/validation/slide_XX/
            body_lines.insert(2, f"    doc_dir = script_dir.parent.parent.parent.parent")
            body_lines.insert(3, f"    deck_ir = json.loads((doc_dir / 'ir' / 'final' / 'final_ir.json').read_text(encoding='utf-8'))")
            body_lines.insert(4, f"    materials = json.loads((doc_dir / 'materials' / 'material_manifest.json').read_text(encoding='utf-8'))")
            body_lines.insert(5, "")

        # Call slide functions with loaded data
        for idx, name in enumerate(function_names):
            body_lines.append(f"    slide_ir = deck_ir['slides'][{idx + slide_index_offset}]")
            body_lines.append(f"    {name}(prs, deck_ir, slide_ir, materials)")

        if not body_lines:
            body_lines = ["    pass"]
        orchestrator = "\n".join(body_lines)

        # Include slide function definitions
        slide_functions_code = "\n\n".join(slide_functions)

        return f"""# -*- coding: utf-8 -*-
import json

{imports}

{slide_functions_code}

def build_presentation(output_path):
    prs = {self._presentation_constructor(mode)}
{orchestrator}
    prs.save(output_path)


build_presentation(output_path)
"""

    @staticmethod
    def _build_evidence_comment(slide_ir: Dict[str, Any]) -> str:
        """Build source evidence comment for slide code."""
        evidence_list = slide_ir.get("source_evidence", [])
        if not evidence_list:
            return "# No source evidence"

        lines = ["# SOURCE EVIDENCE - All content modifications must be grounded in these sources:"]
        for i, evidence in enumerate(evidence_list[:3], 1):  # Limit to 3 for brevity
            excerpt = evidence.get("source_excerpt", "")[:150]
            lines.append(f"# {i}. {excerpt}...")

        return "\n".join(lines)

    @staticmethod
    def _extract_function_name(slide_function: str) -> str:
        match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", slide_function)
        if not match:
            raise RuntimeError(f"Unable to extract function name from slide function: {slide_function[:120]}")
        return match.group(1)

    @staticmethod
    def _persist_slide_function(artifact_dir: str, slide_ir: Dict[str, Any], slide_function: str) -> None:
        slides_dir = Path(artifact_dir) / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)
        slide_id = slide_ir.get("slide_id", "slide")
        (slides_dir / f"{slide_id}.py").write_text(slide_function, encoding="utf-8")

    @staticmethod
    def _slide_signature(slide_ir: Dict[str, Any], mode: str) -> str:
        payload = json.dumps({"slide_ir": slide_ir, "mode": mode}, ensure_ascii=False, sort_keys=True)
        return md5(payload.encode("utf-8")).hexdigest()

    def _load_cached_validated_slide_function(
        self,
        *,
        artifact_dir: str | None,
        slide_ir: Dict[str, Any],
        function_name: str,
        mode: str,
    ) -> str | None:
        if not artifact_dir:
            return None
        metadata = self._load_slide_cache_metadata(artifact_dir, slide_ir)
        if not metadata:
            return None
        if not metadata.get("validated"):
            return None
        if metadata.get("signature") != self._slide_signature(slide_ir, mode):
            return None
        return self._load_existing_slide_function(artifact_dir, slide_ir, function_name=function_name)

    @staticmethod
    def _slide_cache_metadata_path(artifact_dir: str, slide_ir: Dict[str, Any]) -> Path:
        slide_id = slide_ir.get("slide_id", "slide")
        return Path(artifact_dir) / "cache" / f"{slide_id}.json"

    def _load_slide_cache_metadata(self, artifact_dir: str, slide_ir: Dict[str, Any]) -> dict[str, Any] | None:
        metadata_path = self._slide_cache_metadata_path(artifact_dir, slide_ir)
        if not metadata_path.exists():
            return None
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _persist_slide_cache_metadata(
        self,
        artifact_dir: str,
        slide_ir: Dict[str, Any],
        *,
        mode: str,
        validated: bool,
        pptx_path: str | None = None,
    ) -> None:
        metadata_path = self._slide_cache_metadata_path(artifact_dir, slide_ir)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "slide_id": slide_ir.get("slide_id", "slide"),
            "signature": self._slide_signature(slide_ir, mode),
            "validated": validated,
        }
        if pptx_path:
            metadata["pptx_path"] = pptx_path
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _load_existing_slide_function(
        artifact_dir: str | None,
        slide_ir: Dict[str, Any],
        function_name: str,
    ) -> str | None:
        if not artifact_dir:
            return None
        slide_id = slide_ir.get("slide_id", "slide")
        slide_path = Path(artifact_dir) / "slides" / f"{slide_id}.py"
        if not slide_path.exists():
            return None
        code = slide_path.read_text(encoding="utf-8")
        cleaned = PPTXCoder._clean_code_block(code, function_name)
        return cleaned

    @staticmethod
    def _persist_deck_script(artifact_dir: str, code: str, file_name: str = "build_deck.py") -> None:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / file_name).write_text(code, encoding="utf-8")

    @staticmethod
    def _build_import_block(mode: str) -> str:
        if mode == "direct":
            return """import json
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt
"""
        return """import json
from src.coder.pptx_library import (
    add_evidence_footer_block,
    add_highlight_block,
    add_metric_pair_block,
    add_banner,
    add_bar_chart,
    add_blank_slide,
    add_bullet_list,
    add_comparison_columns,
    add_connector,
    add_icon,
    add_metric_card,
    add_picture,
    add_process_flow,
    add_shape,
    add_subtitle_box,
    add_table,
    add_takeaway_block,
    add_textbox,
    add_title_box,
    add_visual_with_caption_block,
    add_panel,
    apply_three_column_layout,
    apply_two_column_layout,
    append_takeaway_block,
    compose_chart_with_takeaway,
    compose_metrics_with_summary,
    compose_visual_with_observations,
    create_presentation,
    emphasize_takeaway_block,
    rebalance_visual_text_ratio,
    render_block_in_slot,
    render_chart_focus_scaffold,
    render_comparison_scaffold,
    render_metric_focus_scaffold,
    render_slide_scaffold,
    render_title_body_scaffold,
    render_title_body_visual_scaffold,
    render_visual_in_slot,
    resolve_asset_path,
    resolve_layout_slots,
    replace_visual_block,
    safe_placeholder_panel,
    safe_resolve_asset_path,
    set_background_color,
    tighten_text_spacing,
)
"""

    @staticmethod
    def _presentation_constructor(mode: str) -> str:
        if mode == "direct":
            return "Presentation()"
        return "create_presentation()"

    def _build_slide_prompt(
        self,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        function_name: str,
        mode: str,
    ) -> str:
        asset_lines = self._format_asset_lines(materials)
        helper_reference = self._library_reference() if mode == "library" else self._direct_reference()
        slide_prompt_payload = self._build_prompt_slide_payload(slide_ir, mode=mode)
        library_strategy = ""
        if mode == "library":
            library_strategy = """
Library-first generation policy:
- First choose a semantic scaffold helper that matches the slide intent, such as `render_title_body_visual_scaffold`, `render_comparison_scaffold`, `render_metric_focus_scaffold`, or `render_chart_focus_scaffold`.
- Then fill slots with semantic block helpers like `add_takeaway_block`, `add_metric_pair_block`, `add_visual_with_caption_block`, `compose_metrics_with_summary`, or `compose_visual_with_observations`.
- Use local refine helpers last for small improvements only.
- Avoid low-level python-pptx shape construction unless the library helpers are genuinely insufficient for a small local adjustment.
- If a scaffold helper can express the page structure, use the scaffold helper first instead of manually rebuilding the whole page with coordinates.
"""
        qwen_library_policy = ""
        library_generation_skill = ""
        if mode == "library":
            skill_prompt = build_library_generation_skill_prompt(self.library_generation_skill)
            if skill_prompt:
                library_generation_skill = f"\n{skill_prompt}\n"
        return f"""⚠️ CRITICAL: You MUST return a COMPLETE function from `def {function_name}(...)` to the final `return` statement. Do NOT return code fragments, single lines, or partial snippets. ⚠️

You are a top-tier PowerPoint coding agent. Generate executable Python function code for exactly one slide, using the deck IR constraints and the current slide IR.

Hard constraints:
1. Work on only this single slide.
2. The function name must be `{function_name}`.
3. The function signature must be `def {function_name}(prs, deck_ir, slide_ir, materials):`
4. Return exactly one complete Python function definition. Do not include explanations or markdown fences.
5. The function must create the slide and fully render the current page.
6. The slide IR uses natural language descriptions for layout and content types. Interpret the design intent rather than expecting fixed enum values:
   - layout.name may be descriptive (e.g., "two_column", "asymmetric layout with left emphasis", "hero with sidebar")
   - blocks[*].kind may be descriptive (e.g., "bullet_list", "detailed comparison table", "metric showcase")
   - layout.slots[*].slot_role may be descriptive (e.g., "title", "body", "hero_visual", "comparison_area")
   - Implement the design based on your understanding of the natural language description.
7. If `slide_ir.selected_asset_path` is available, use it first. Otherwise resolve assets from `visuals[*].selected_candidate.path` or `use_existing_asset_id` via `materials["asset_index"]`.
8. Produce polished, well-aligned visual output with deliberate whitespace. Avoid generic template-looking slides.
9. The returned code must execute as-is.
10. In `library` mode, prefer semantic layout helpers and relative slot rendering. Use precise coordinates mainly in `direct` mode.
11. ENCODING: Use pathlib.Path for all file path operations. Never hardcode path prefixes like "outputs\\2025.acl-demo.7\\". Use Path objects to construct paths safely.
12. ASSET PATHS: When accessing materials["asset_index"], handle both dict and string values. Extract the "path" field if it's a dict.

Default language policy:
- All comments, labels, and any generated user-facing text should be English unless the slide IR explicitly requires another language.

CRITICAL REQUIREMENTS:
- Use pathlib.Path for all file path operations
- When accessing asset paths from materials["asset_index"], check if value is dict and extract "path" field
- Never hardcode path prefixes; use Path objects for safe path construction
- Ensure all file operations use os.path.exists() with proper path handling

Coding mode: {mode}

{library_strategy}

{qwen_library_policy}

{library_generation_skill}

Available API / constraints:
{helper_reference}

Deck IR:
{json.dumps({k: v for k, v in deck_ir.items() if k != "slides"}, ensure_ascii=False, indent=2)[:4500]}

Current slide IR:
{json.dumps(slide_prompt_payload, ensure_ascii=False, indent=2)[:3500]}

Available asset index:
{asset_lines}
"""

    def _build_slide_repair_prompt(
        self,
        *,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        function_name: str,
        mode: str,
        previous_code: str,
        error_message: str,
        is_fragment_retry: bool = False,
    ) -> str:
        asset_lines = self._format_asset_lines(materials)
        helper_reference = self._library_reference() if mode == "library" else self._direct_reference()
        error_lower = error_message.lower()
        repair_policy = ""
        if mode == "library":
            skill_prompt = build_library_generation_skill_prompt(self.library_generation_skill)
            if skill_prompt:
                repair_policy += f"\n{skill_prompt}\n"
            repair_hint = build_library_generation_repair_hint(self.library_generation_skill, error_message)
            if repair_hint:
                repair_policy += f"\n{repair_hint}\n"
            if "filenotfounderror" in error_lower or "asset" in error_lower or "image" in error_lower:
                repair_policy += """
Library repair policy for asset errors:
- Treat this as an asset resolution problem first.
- Preserve the existing scaffold and page structure.
- Prefer `safe_resolve_asset_path`, `render_visual_in_slot`, `replace_visual_block`, or `safe_placeholder_panel` instead of rebuilding the slide.
- Apply the smallest local fix that keeps the intended content visible.
"""
            elif "librarystaticcheckerror" in error_lower or "scaffold/helper" in error_lower or "constraint" in error_lower:
                repair_policy += """
Library repair policy for library constraint errors:
- Preserve the intended slide structure, but rewrite the function so it follows scaffold-first and helper-first generation.
- Replace main-layout low-level python-pptx code with scaffold helpers or semantic block helpers.
- Keep low-level coordinate edits only for small local adjustments after scaffold/helper placement.
"""
            elif "attributeerror" in error_lower or "layout" in error_lower:
                repair_policy += """
Library repair policy for layout errors:
- Preserve the page intent and repair the structure locally.
- Prefer scaffold helpers, `resolve_layout_slots`, and semantic block helpers before changing coordinates directly.
"""
            else:
                repair_policy += """
Library repair policy:
- Preserve the slide structure and visual intent.
- Prefer local fixes over full-page rewrites.
- Keep scaffold-first and helper-first generation in the repaired result.
"""

        # Add special emphasis for fragment error retry
        fragment_warning = ""
        if is_fragment_retry:
            fragment_warning = f"""
⚠️ CRITICAL WARNING - CODE FRAGMENT ERROR DETECTED ⚠️

Your previous response returned ONLY A CODE FRAGMENT instead of a complete function.
This is UNACCEPTABLE and will cause the system to fail.

YOU MUST:
1. Return the ENTIRE function from `def {function_name}(prs, deck_ir, slide_ir, materials):` to the final `return slide`
2. Include ALL function body code, not just a single line or expression
3. Do NOT return partial code, expressions, or fragments like "overlay.fill.fore_color.theme_color = None"
4. The response must be a COMPLETE, EXECUTABLE Python function

If you return another fragment, the process will terminate with an error.

"""

        return f"""{fragment_warning}You are fixing a previously generated PowerPoint slide function.

Your goal:
- Return a corrected executable version of `{function_name}`.
- Fix the execution error while preserving the intended slide content and slide IR structure.

CRITICAL: You MUST return the COMPLETE function definition from `def` to the final `return` statement. Do NOT return partial code snippets, expressions, or fragments.

Hard constraints:
1. Return exactly one complete Python function definition named `{function_name}`.
2. Keep the signature exactly `def {function_name}(prs, deck_ir, slide_ir, materials):`
3. The function must start with `def {function_name}(` and end with a `return` statement.
4. Do not return explanations, markdown, or partial snippets.
5. Preserve the slide's intended visual structure unless the failing code requires a local simplification.
6. Keep all comments and generated user-facing text in English by default.
7. ENCODING: Use pathlib.Path for all file path operations. Never hardcode path prefixes.
8. ASSET PATHS: When accessing materials["asset_index"], handle both dict and string values. Extract the "path" field if it's a dict.
9. Handle None values: Check if objects are None before accessing their attributes or iterating over them.
10. CRITICAL: In this environment, `LineFormat` has NO `.fore_color` attribute. Use `shape.line.color.rgb = RGBColor(...)` for borders.
11. CRITICAL: In this environment, `_Paragraph` has NO `.bullet` attribute. Do NOT access `para.bullet.*`; instead prefix bullet text directly like `para.text = "• " + item` or use separate paragraphs without bullet styling.

Previous execution error:
{error_message}

{repair_policy}

Available API / constraints:
{helper_reference}

Deck IR:
{json.dumps({k: v for k, v in deck_ir.items() if k != "slides"}, ensure_ascii=False, indent=2)[:3500]}

Current slide IR:
{json.dumps(slide_ir, ensure_ascii=False, indent=2)[:3000]}

Available asset index:
{asset_lines}

Previous code:
{previous_code}
"""

    def _build_prompt_slide_payload(self, slide_ir: Dict[str, Any], *, mode: str) -> Dict[str, Any]:
        if mode != "library" or self.library_generation_skill != "qwen_v1":
            return slide_ir

        payload = {
            "slide_id": slide_ir.get("slide_id"),
            "type": slide_ir.get("type"),
            "title": slide_ir.get("title"),
            "subtitle": slide_ir.get("subtitle", ""),
            "core_message": slide_ir.get("core_message", ""),
            "layout": slide_ir.get("layout", {}),
            "blocks": [],
            "points": [str(item) for item in (slide_ir.get("points") or [])[:4]],
            "visuals": [],
            "design_notes": [str(item) for item in (slide_ir.get("design_notes") or [])[:4]],
            "selected_asset_path": slide_ir.get("selected_asset_path"),
        }

        for block in (slide_ir.get("blocks") or [])[:4]:
            compact_block = {
                "kind": block.get("kind"),
                "slot_id": block.get("slot_id"),
            }
            content = str(block.get("content", "") or "").strip()
            if content:
                compact_block["content"] = content[:220]
            items = [str(item).strip() for item in (block.get("items") or []) if str(item).strip()]
            if items:
                compact_block["items"] = items[:4]
            payload["blocks"].append(compact_block)

        for visual in (slide_ir.get("visuals") or [])[:2]:
            selected = visual.get("selected_candidate") or {}
            payload["visuals"].append(
                {
                    "slot_id": visual.get("slot_id"),
                    "asset_role": visual.get("asset_role"),
                    "intent": visual.get("intent", ""),
                    "selected_asset_id": selected.get("asset_id"),
                    "has_selected_asset": bool(selected.get("asset_id") or selected.get("path") or slide_ir.get("selected_asset_path")),
                }
            )

        return payload

    def _build_qwen_library_generation_harness(self, slide_ir: Dict[str, Any]) -> str:
        recommended_scaffold = self._recommended_qwen_library_scaffold(slide_ir)
        return f"""
Recommended scaffold start:
- Start from `{recommended_scaffold}` for the main page structure, then add only small local enhancements.

Reliable content extraction harness:
- `blocks = slide_ir.get("blocks", [])`
- `points = slide_ir.get("points", [])`
- `core_message = slide_ir.get("core_message", "")`
- `visuals = slide_ir.get("visuals", [])`
- `slots = resolve_layout_slots(slide_ir)`

Reliable rendering order:
- If `blocks` is non-empty, render at least one body block from `blocks` before any decorative polish.
- Else if `points` is non-empty, render `points` as the visible body content.
- Else render `core_message` as a visible body summary so the slide is never title-only.
- If a visual slot or `visuals` exists, preserve the visual area and render it with `render_visual_in_slot(...)` or keep the scaffold-rendered visual result.
- Do not replace the whole scaffold with a second low-level page rebuild.
""".strip()

    def _build_qwen_library_repair_harness(self, slide_ir: Dict[str, Any], error_message: str) -> str:
        error_lower = str(error_message or "").lower()
        recommended_scaffold = self._recommended_qwen_library_scaffold(slide_ir)
        base = f"""
Qwen repair harness:
- Recommended scaffold start: `{recommended_scaffold}`
- Keep one main layout path only; do not keep the old low-level main-layout construction if you switch to scaffold-first.
- Re-read the canonical IR fields before editing:
  - `blocks = slide_ir.get("blocks", [])`
  - `points = slide_ir.get("points", [])`
  - `core_message = slide_ir.get("core_message", "")`
  - `visuals = slide_ir.get("visuals", [])`
  - `slots = resolve_layout_slots(slide_ir)`
""".strip()
        if "body content source" in error_lower:
            return base + """

Targeted repair for missing body content:
- Restore body content first, then do aesthetic cleanup.
- If `blocks` is non-empty, render at least one visible body block from `blocks`.
- Else if `points` is non-empty, render `points` as bullets or a short body list.
- Else render `core_message` as a visible body summary.
- Keep any visual slot intact, but do not spend this repair on decorative extras until body content is visible.
""".rstrip()
        if "scaffold/helper first" in error_lower or "low-level python-pptx" in error_lower:
            return base + """

Targeted repair for scaffold-first failure:
- Rewrite the function around one scaffold instead of patching the old low-level layout piecemeal.
- Use the recommended scaffold start for the main structure.
- After the scaffold call, add only small helper-based enhancements.
- Do not keep the old low-level main-layout construction alongside the scaffold path.
""".rstrip()
        return base

    @staticmethod
    def _recommended_qwen_library_scaffold(slide_ir: Dict[str, Any]) -> str:
        layout_name = str(slide_ir.get("layout", {}).get("name", "") or "").lower()
        slots = slide_ir.get("layout", {}).get("slots", []) or []
        slot_roles = {str(slot.get("slot_role", "")).strip().lower() for slot in slots}
        has_visual = bool(slide_ir.get("visuals")) or bool({"hero_visual", "supporting_visual"} & slot_roles)
        if layout_name == "comparison":
            return "render_comparison_scaffold(prs, deck_ir, slide_ir, materials)"
        if layout_name == "metric_focus":
            return "render_metric_focus_scaffold(prs, deck_ir, slide_ir, materials)"
        if layout_name == "chart_focus":
            return "render_chart_focus_scaffold(prs, deck_ir, slide_ir, materials)"
        if has_visual:
            return "render_title_body_visual_scaffold(prs, deck_ir, slide_ir, materials)"
        if str(slide_ir.get("type", "content") or "content").lower() == "content":
            return "render_title_body_scaffold(prs, deck_ir, slide_ir, materials)"
        return "render_slide_scaffold(prs, deck_ir, slide_ir, materials)"

    def _validate_slide_function(
        self,
        *,
        deck_ir: Dict[str, Any],
        slide_ir: Dict[str, Any],
        materials: Dict[str, Any],
        slide_function: str,
        index: int,
        mode: str,
        artifact_dir: str | None,
        attempt: int,
    ) -> dict[str, Any]:
        if mode == "library":
            static_error = self._library_static_check(
                slide_function,
                slide_ir=slide_ir,
                model_profile=self._model_profile(),
            )
            if static_error:
                return {
                    "success": False,
                    "error": f"LibraryStaticCheckError: {static_error}",
                    "output_path": "",
                }
        # Build minimal deck_ir for validation (keep theme but remove large metadata)
        single_deck = {
            "title": deck_ir.get("title", ""),
            "theme": deck_ir.get("theme", {}),
            "slides": [slide_ir]
        }
        slide_id = slide_ir.get("slide_id", f"slide_{index:02d}")
        validation_dir = Path(artifact_dir) / "validation" / slide_id if artifact_dir else None
        # Detect if we're in React round environment
        for_react_round = artifact_dir and ("refine" in str(artifact_dir) and "round_" in str(artifact_dir))
        script = self._build_script(single_deck, materials, [slide_function], mode, artifact_dir=validation_dir, for_react_round=for_react_round, slide_index_offset=index - 1)
        output_path = (
            str(validation_dir / f"attempt_{attempt:02d}.pptx")
            if validation_dir
            else str(Path("/tmp") / f"{slide_id}_attempt_{attempt:02d}.pptx")
        )
        if validation_dir:
            validation_dir.mkdir(parents=True, exist_ok=True)
            script_path = str(validation_dir / f"attempt_{attempt:02d}.py")
            (validation_dir / f"attempt_{attempt:02d}.py").write_text(script, encoding="utf-8")
        else:
            script_path = None
        success, error = self.execute_code_with_error(script, output_path, script_path=script_path)

        # Check PPTX file exists and has content
        if success:
            pptx_path = Path(output_path)
            if not pptx_path.exists() or pptx_path.stat().st_size == 0:
                success = False
                error = "PPTX file not created or is empty"

        return {"success": success, "error": error, "output_path": output_path}

    @staticmethod
    def _format_asset_lines(materials: Dict[str, Any]) -> str:
        lines = []
        descriptions = materials.get("descriptions", {})
        for asset_id, asset in list(materials.get("asset_index", {}).items())[:20]:
            description = descriptions.get(asset.get("path", ""), "")[:120]
            lines.append(f"- {asset_id}: {asset.get('path', '')} | {description}")
        return "\n".join(lines) if lines else "None"

    @staticmethod
    def _library_static_check(code: str, *, slide_ir: Dict[str, Any], model_profile: str = "general") -> str | None:
        normalized = code.lower()
        layout_name = str(slide_ir.get("layout", {}).get("name", "two_column") or "two_column").lower()
        scaffold_names = (
            "render_slide_scaffold",
            "render_title_body_scaffold",
            "render_title_body_visual_scaffold",
            "render_comparison_scaffold",
            "render_metric_focus_scaffold",
            "render_chart_focus_scaffold",
        )
        helper_names = (
            "render_block_in_slot",
            "render_visual_in_slot",
            "add_takeaway_block",
            "add_highlight_block",
            "add_metric_pair_block",
            "add_visual_with_caption_block",
            "compose_chart_with_takeaway",
            "compose_visual_with_observations",
            "compose_metrics_with_summary",
            "append_takeaway_block",
            "replace_visual_block",
        )
        uses_scaffold = any(name in normalized for name in scaffold_names)
        uses_helper = any(name in normalized for name in helper_names)
        uses_add_blank_slide = "add_blank_slide(prs)" in normalized
        low_level_ops = (
            "slide.shapes.add_textbox",
            "slide.shapes.add_shape",
            "slide.shapes.add_picture",
            "slide.shapes.add_table",
            "slide.shapes.add_chart",
        )
        low_level_count = sum(normalized.count(pattern) for pattern in low_level_ops)
        simple_layouts = {"two_column", "comparison", "metric_focus", "chart_focus", "section_divider", "hero", "image_focus", "closing"}
        if layout_name in simple_layouts and low_level_count >= 2 and not (uses_scaffold or uses_helper):
            return "library mode should use scaffold/helper first for the main layout before low-level python-pptx calls"
        if str(model_profile or "general").lower() == "qwen":
            if uses_add_blank_slide and uses_scaffold:
                return "Qwen library mode forbids mixing `add_blank_slide(prs)` with any `render_*scaffold(...)` helper in the same slide function"
            invented_fields = (
                'slide_ir.get("summary"',
                "slide_ir.get('summary'",
                'slide_ir["summary"]',
                "slide_ir['summary']",
                'slide_ir.get("bullet_points"',
                "slide_ir.get('bullet_points'",
                'slide_ir["bullet_points"]',
                "slide_ir['bullet_points']",
                'slide_ir.get("visual_path"',
                "slide_ir.get('visual_path'",
                'slide_ir["visual_path"]',
                "slide_ir['visual_path']",
                'slide_ir.get("body_text"',
                "slide_ir.get('body_text'",
                'slide_ir["body_text"]',
                "slide_ir['body_text']",
            )
            if any(field in normalized for field in invented_fields):
                return "Qwen library mode must use the real slide IR schema instead of invented shortcut fields such as summary/bullet_points/visual_path/body_text"
            if ".delete()" in normalized:
                return "Qwen library mode may not call shape.delete(); rebuild or overwrite content without using unsupported deletion APIs"
            slide_type = str(slide_ir.get("type", "content") or "content").lower()
            if slide_type not in {"title", "cover", "closing", "section_divider"}:
                body_sources = (
                    'slide_ir.get("blocks"',
                    "slide_ir.get('blocks'",
                    'slide_ir["blocks"]',
                    "slide_ir['blocks']",
                    'slide_ir.get("points"',
                    "slide_ir.get('points'",
                    'slide_ir["points"]',
                    "slide_ir['points']",
                    'slide_ir.get("core_message"',
                    "slide_ir.get('core_message'",
                    'slide_ir["core_message"]',
                    "slide_ir['core_message']",
                )
                if not any(source in normalized for source in body_sources):
                    return "Qwen library mode content slides must render at least one body content source from `blocks`, `points`, or `core_message`"
        return None

    def _model_profile(self) -> str:
        return getattr(self.client, "model_profile", "general")

    @staticmethod
    def _library_reference() -> str:
        return """Module-level imports already provided — DO NOT re-import anything.
CRITICAL: `slide_ir`, `deck_ir`, `materials` are plain Python dicts. Access fields with `slide_ir.get("key")` or `slide_ir["key"]`. NEVER use dot notation like `slide_ir.title` or `slide_ir.layout`.
You may directly use these helpers:
- `slide = add_blank_slide(prs)`
- `set_background_color(slide, \"#F7F4EE\")`
- `slots = resolve_layout_slots(slide_ir)` returns `dict[str, tuple[left, top, width, height]]`; it is not an object API. It first uses `slide_ir["layout"]["slots"]`, then falls back to built-in templates
- `render_slide_scaffold(prs, deck_ir, slide_ir, materials)` can render the slide using semantic slots, after which you may add small enhancements
- `render_title_body_scaffold(prs, deck_ir, slide_ir, materials)`
- `render_title_body_visual_scaffold(prs, deck_ir, slide_ir, materials)`
- `render_comparison_scaffold(prs, deck_ir, slide_ir, materials)`
- `render_metric_focus_scaffold(prs, deck_ir, slide_ir, materials)`
- `render_chart_focus_scaffold(prs, deck_ir, slide_ir, materials)`
- `render_block_in_slot(slide, block, slot_rect, theme, font_name=None)` renders `summary / bullet_list / metric_strip / process / comparison / quote / callout` automatically from `block.kind`
- `resolve_asset_path(materials, slide_ir, visual=None)` resolves the asset path from `selected_asset_path`, `selected_candidate`, or `asset_index`
- `safe_resolve_asset_path(materials, slide_ir, visual=None)` resolves assets safely and returns `None` on bad assets
- `render_visual_in_slot(slide, slide_ir, materials, visual, slot_rect, theme)` renders an image or placeholder panel into a slot
- `safe_placeholder_panel(slide, slot_rect, label=\"visual unavailable\", theme=None)` creates a placeholder panel for missing visuals
- `add_title_box(slide, text, left=0.6, top=0.35, width=12.1, height=0.9, font_size=28, color=\"#134E8E\")`
- `add_subtitle_box(slide, text, ...)`
- `add_textbox(slide, text, left, top, width, height, font_size=20, color=\"#1F2937\", bold=False, align=\"left\", fill_color=None, font_name=\"Aptos\")`
- `add_bullet_list(slide, items, left, top, width, height, font_size=18, color=\"#1F2937\")`
- `add_picture(slide, image_path, left, top, width, height)`
- `add_icon(slide, image_path, left, top, size=0.35)`
- `add_shape(slide, \"RECTANGLE\"|\"ROUNDED_RECTANGLE\"|\"OVAL\", left, top, width, height, fill_color=\"#FFFFFF\", line_color=\"#D1D5DB\")`
- `add_panel(slide, left, top, width, height, fill_color=\"#FFFFFF\", line_color=\"#D1D5DB\", radius_shape=\"ROUNDED_RECTANGLE\")`
- `add_connector(slide, \"STRAIGHT\", x1, y1, x2, y2, color=\"#9CA3AF\")`
- `add_banner(slide, text, left, top, width, height, fill_color=\"#134E8E\", text_color=\"#FFFFFF\")`
- `add_metric_card(slide, label, value, left, top, width, height, accent_color=\"#C00707\")`
- `add_process_flow(slide, steps, left, top, width, height, accent_color=\"#134E8E\")`
- `add_comparison_columns(slide, headers, columns, left, top, width, height)`
- `add_table(slide, rows, left, top, width, height)`
- `add_bar_chart(slide, categories, series_name, values, left, top, width, height)`
- `add_takeaway_block(slide, text, slot_rect, theme=None)`
- `add_highlight_block(slide, text, slot_rect, theme=None)`
- `add_metric_pair_block(slide, metrics, slot_rect, theme=None)`
- `add_visual_with_caption_block(slide, image_path, caption, slot_rect, theme=None)`
- `add_evidence_footer_block(slide, evidence_items, slot_rect, theme=None)`
- `compose_chart_with_takeaway(slide, categories, series_name, values, takeaway, slot_rect, theme=None)`
- `compose_visual_with_observations(slide, image_path, observations, slot_rect, theme=None, caption=\"\")`
- `compose_metrics_with_summary(slide, metrics, summary, slot_rect, theme=None)`
- `append_takeaway_block(slide, text, slot_rect, theme=None)`
- `emphasize_takeaway_block(shape, theme=None)`
- `replace_visual_block(slide, image_path, slot_rect, theme=None, caption=\"\")`
- `tighten_text_spacing(shape, level=\"compact\")`
- `rebalance_visual_text_ratio(text_shape, visual_shape, ratio=\"balanced\")`
- `apply_two_column_layout(slide, title, body_items, image_path=None)`
- `apply_three_column_layout(slide, title, columns, headers)`
Library mode policy:
- Prefer scaffold-first, helper-first generation.
- Avoid low-level python-pptx shape construction for the main layout when a scaffold or semantic helper exists.
- Use low-level coordinates only for small local adjustments after scaffold and helper placement.
Only use small coordinate-level tweaks when the semantic helpers are insufficient. All coordinates are in inches."""

    @staticmethod
    def _direct_reference() -> str:
        return """Module-level imports already provided at top of script — DO NOT re-import anything. The following are already imported and available: `Presentation` (pptx), `CategoryChartData` (pptx.chart.data), `RGBColor` (pptx.dml.color), `XL_CHART_TYPE` (pptx.enum.chart), `MSO_AUTO_SHAPE_TYPE`, `MSO_CONNECTOR` (pptx.enum.shapes), `MSO_ANCHOR`, `PP_ALIGN` (pptx.enum.text), `Inches`, `Pt` (pptx.util). Do NOT import from pptx.shared, pptx.enum.anchor, or any other pptx submodule.
CRITICAL: `slide_ir`, `deck_ir`, `materials` are plain Python dicts. Access fields with `slide_ir.get("key")` or `slide_ir["key"]`. NEVER use dot notation like `slide_ir.title`.
You must directly use python-pptx:
- `slide = prs.slides.add_slide(prs.slide_layouts[6])`
- `prs.slide_width = Inches(13.33)` and `prs.slide_height = Inches(7.5)` are already handled outside
- You may use `slide.shapes.add_textbox(...)`, `slide.shapes.add_picture(...)`, `slide.shapes.add_shape(...)`, `slide.shapes.add_table(...)`, `slide.shapes.add_chart(...)`
- CRITICAL: `add_shape()` signature is `add_shape(autoshape_type_id, left, top, width, height)` - ONLY 5 parameters. Set colors AFTER creation: ALWAYS call `shape.fill.solid()` BEFORE `shape.fill.fore_color.rgb = RGBColor(...)`
- CRITICAL: `LineFormat` has NO `.fore_color` attribute in this environment. Use `shape.line.color.rgb = RGBColor(...)` for borders.
- CRITICAL: `_Paragraph` has NO `paragraph_format` attribute. Use `para.left_indent`, `para.space_before`, `para.space_after` directly on the paragraph object.
- CRITICAL: `_Paragraph` has NO `.bullet` attribute in this environment. Never use `para.bullet.*`. If you need bullets, prefix the text manually like `para.text = "• " + item`.
- CRITICAL: DO NOT use internal APIs like `._p`, `.get_or_add_pPr()`, `.get_or_add_buChar()`.
- You may use `RGBColor`, `Pt`, `Inches`, `MSO_AUTO_SHAPE_TYPE`, `MSO_CONNECTOR`, `PP_ALIGN`, `MSO_ANCHOR`, `XL_CHART_TYPE`, `CategoryChartData`
In direct mode you must handle text, color, shapes, tables, charts, and alignment yourself."""

    @staticmethod
    def _clean_code_block(code: str, function_name: str) -> str:
        code = PPTXCoder._extract_code_payload(code)
        code = code.strip()
        if not code.startswith(f"def {function_name}"):
            match = re.search(rf"def\s+{re.escape(function_name)}\s*\(", code)
            if match:
                code = code[match.start():].lstrip()
        if not code.startswith(f"def {function_name}"):
            raise RuntimeError(f"Coder did not return the expected function {function_name}: {code[:200]}")
        lines = code.splitlines()
        collected: list[str] = []
        for index, line in enumerate(lines):
            if index == 0:
                collected.append(line)
                continue
            if line.strip() == "":
                collected.append(line)
                continue
            if not line.startswith((" ", "\t")):
                break
            collected.append(line)
        cleaned = "\n".join(collected).rstrip()
        cleaned = PPTXCoder._trim_trailing_syntax_fragments(cleaned)
        return PPTXCoder._normalize_common_codegen_typos(cleaned)

    @staticmethod
    def _extract_code_payload(code: str) -> str:
        if "```" not in code:
            return code
        match = re.search(r"```(?:python)?\s*([\s\S]*?)```", code)
        if match:
            return match.group(1)
        open_match = re.search(r"```(?:python)?\s*([\s\S]*)", code)
        if open_match:
            return open_match.group(1)
        return code

    @staticmethod
    def _trim_trailing_syntax_fragments(code: str) -> str:
        lines = code.splitlines()
        while len(lines) > 1:
            candidate = "\n".join(lines).rstrip()
            try:
                compile(candidate, "<generated-slide-code>", "exec")
                return candidate
            except SyntaxError as exc:
                if exc.lineno == len(lines):
                    lines.pop()
                    continue
                return candidate
        return "\n".join(lines).rstrip()

    @staticmethod
    def _normalize_common_codegen_typos(code: str) -> str:
        code = re.sub(
            r"\bfrom\s+pptx\.dml\.color\s+import\s+RgbColor\b",
            "from pptx.dml.color import RGBColor",
            code,
        )
        return re.sub(r"\bRgbColor\(", "RGBColor(", code)
