from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from fastapi_app.config.settings import settings
from fastapi_app.utils import _from_outputs_url, _to_outputs_url
from workflow_engine.utils import get_project_root


class EditablePPTService:
    """ThinkFlow wrapper around the editable PPT CLI."""

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"}

    def __init__(
        self,
        *,
        presentagent_root: Optional[Path] = None,
        project_root: Optional[Path] = None,
        python_bin: Optional[str] = None,
    ) -> None:
        self.project_root = project_root or get_project_root()
        configured_root = str(presentagent_root or settings.PRESENT_AGENT_ROOT or "").strip()
        self.presentagent_root = Path(configured_root) if configured_root else self.project_root / "vendor" / "presentagent"
        self.python_bin = python_bin or settings.PRESENT_AGENT_PYTHON

    def normalize_request(
        self,
        *,
        model_profile: Optional[str],
        coder_mode: Optional[str],
        language: Optional[str],
        complexity: Optional[str],
        target_slides: Optional[int],
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        profile = (model_profile or "general").strip().lower()
        mode = (coder_mode or "library").strip().lower()
        lang = (language or "chinese").strip().lower()
        level = (complexity or "balanced").strip().lower()
        slides = int(target_slides or 0)

        if profile not in {"general", "claude", "qwen"}:
            raise HTTPException(status_code=400, detail="model_profile must be general, claude, or qwen")
        if mode not in {"direct", "library"}:
            raise HTTPException(status_code=400, detail="coder_mode must be direct or library")
        if lang not in {"english", "chinese"}:
            raise HTTPException(status_code=400, detail="language must be english or chinese")
        if level not in {"simple", "balanced", "complex"}:
            raise HTTPException(status_code=400, detail="complexity must be simple, balanced, or complex")

        return {
            "model_profile": profile,
            "coder_mode": mode,
            "language": lang,
            "complexity": level,
            "target_slides": max(0, slides),
            "api_url": (api_url or "").strip(),
            "api_key": (api_key or "").strip(),
            "model": (model or "").strip(),
        }

    def resolve_input_path(
        self,
        *,
        source_paths: List[str],
        document_content: str,
        output_dir: Path,
    ) -> str:
        for raw in source_paths:
            value = str(raw or "").strip()
            if not value:
                continue
            if value.startswith(("http://", "https://")) and value.lower().split("?", 1)[0].endswith(".pdf"):
                return value
            local = Path(_from_outputs_url(value))
            if local.exists() and local.is_file() and local.suffix.lower() == ".pdf":
                return str(local.resolve())

        if str(document_content or "").strip():
            context_path = output_dir / "editable_ppt_input.md"
            context_path.parent.mkdir(parents=True, exist_ok=True)
            context_path.write_text(document_content, encoding="utf-8")

        raise HTTPException(
            status_code=400,
            detail="Editable PPT v1 requires at least one PDF source",
        )

    def build_context_markdown(
        self,
        *,
        item: Dict[str, Any],
        document: Dict[str, Any],
        guidance_text: str,
    ) -> str:
        lines = [f"# {item.get('title') or document.get('title') or '可编辑PPT'}", ""]
        if str(guidance_text or "").strip():
            lines.extend(["## 产出指导", "", str(guidance_text).strip(), ""])
        if str(document.get("content") or "").strip():
            lines.extend(["## 梳理文档", "", str(document.get("content") or "").strip(), ""])
        source_names = [str(name or "").strip() for name in item.get("source_names") or [] if str(name or "").strip()]
        if source_names:
            lines.extend(["## 来源文件", ""])
            lines.extend(f"- {name}" for name in source_names)
        return "\n".join(lines).strip()

    def run_from_output(
        self,
        *,
        item: Dict[str, Any],
        document: Dict[str, Any],
        guidance_text: str,
        output_dir: Path,
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged_options = dict((item.get("result") or {}).get("editable_ppt_options") or {})
        merged_options.update(options or {})
        context_text = self.build_context_markdown(item=item, document=document, guidance_text=guidance_text)
        input_path = self.resolve_input_path(
            source_paths=item.get("source_paths") or [],
            document_content=context_text,
            output_dir=output_dir,
        )
        resume_output_dir = self.prepare_resume_output_dir(
            input_path=input_path,
            output_dir=output_dir,
        )
        return self.run_presentagent(
            input_path=input_path,
            output_dir=output_dir,
            title=str(item.get("title") or "editable_ppt"),
            model_profile=merged_options.get("model_profile") or "general",
            coder_mode=merged_options.get("coder_mode") or "library",
            language=merged_options.get("language") or "chinese",
            complexity=merged_options.get("complexity") or "balanced",
            target_slides=int(merged_options.get("target_slides") or item.get("page_count") or 0),
            api_url=api_url,
            api_key=api_key,
            model=model,
            resume_output_dir=resume_output_dir,
        )

    def run_presentagent(
        self,
        *,
        input_path: str,
        output_dir: Path,
        title: str,
        model_profile: Optional[str],
        coder_mode: Optional[str],
        language: Optional[str],
        complexity: Optional[str],
        target_slides: Optional[int],
        api_url: Optional[str],
        api_key: Optional[str],
        model: Optional[str],
        resume_output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        normalized = self.normalize_request(
            model_profile=model_profile,
            coder_mode=coder_mode,
            language=language,
            complexity=complexity,
            target_slides=target_slides,
            api_url=api_url,
            api_key=api_key,
            model=model,
        )
        if not (self.presentagent_root / "cli.py").exists():
            raise HTTPException(status_code=500, detail="Editable PPT runtime is not available")

        output_dir.mkdir(parents=True, exist_ok=True)
        run_root = output_dir / "editable_ppt_run"
        final_pptx = output_dir / "editable.pptx"
        log_path = output_dir / "editable_ppt.log"
        command = self._build_command(
            input_path=input_path,
            output_path=final_pptx,
            options=normalized,
            resume_output_dir=resume_output_dir,
        )
        env = self._build_env(run_root=run_root, options=normalized)

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.presentagent_root),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=int(settings.THINKFLOW_EDITABLE_PPT_TIMEOUT_SECONDS),
                check=True,
            )
            log_path.write_text(completed.stdout or "", encoding="utf-8")
        except subprocess.CalledProcessError as exc:
            log_path.write_text(exc.stdout or "", encoding="utf-8")
            raise HTTPException(status_code=500, detail=f"Editable PPT generation failed; see {log_path}") from exc
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(exc.stdout or "", encoding="utf-8")
            raise HTTPException(status_code=504, detail=f"Editable PPT generation timed out; see {log_path}") from exc

        onlyoffice_normalized = self._normalize_pptx_for_onlyoffice(final_pptx, log_path=log_path)
        result = self.discover_artifacts(output_dir=output_dir, run_root=run_root)
        result["editable_ppt_options"] = normalized
        result["log_path"] = str(log_path)
        result["log_url"] = _to_outputs_url(str(log_path))
        result["download_url"] = result.get("pptx_url", "")
        result["onlyoffice_normalized"] = onlyoffice_normalized
        return result

    def _normalize_pptx_for_onlyoffice(self, pptx_path: Path, *, log_path: Path) -> bool:
        converter = shutil.which("libreoffice") or shutil.which("soffice")
        if not converter:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\n[thinkflow] LibreOffice not found; skipped PPTX normalization.\n")
            return False
        if not pptx_path.exists():
            return False

        with tempfile.TemporaryDirectory(prefix="thinkflow-pptx-normalize-") as temp_dir:
            out_dir = Path(temp_dir)
            command = [
                converter,
                "--headless",
                "--convert-to",
                "pptx",
                "--outdir",
                str(out_dir),
                str(pptx_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=180,
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n[thinkflow] PPTX normalization failed:\n")
                    handle.write(exc.stdout or "")
                raise HTTPException(status_code=500, detail=f"Editable PPT normalization failed; see {log_path}") from exc
            except subprocess.TimeoutExpired as exc:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n[thinkflow] PPTX normalization timed out:\n")
                    handle.write(str(exc.stdout or ""))
                raise HTTPException(status_code=504, detail=f"Editable PPT normalization timed out; see {log_path}") from exc

            normalized_path = out_dir / pptx_path.name
            if not normalized_path.exists() or normalized_path.stat().st_size <= 0:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n[thinkflow] PPTX normalization produced no output.\n")
                    handle.write(completed.stdout or "")
                raise HTTPException(status_code=500, detail=f"Editable PPT normalization produced no output; see {log_path}")
            shutil.copy2(normalized_path, pptx_path)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\n[thinkflow] PPTX normalized for online editing:\n")
                handle.write(completed.stdout or "")
            return True

    def _build_command(
        self,
        *,
        input_path: str,
        output_path: Path,
        options: Dict[str, Any],
        resume_output_dir: Optional[Path] = None,
    ) -> List[str]:
        command = [
            self.python_bin,
            "cli.py",
            input_path,
            "--output",
            str(output_path),
            "--coder-mode",
            options["coder_mode"],
            "--model-profile",
            options["model_profile"],
            "--language",
            options["language"],
            "--complexity",
            options["complexity"],
        ]
        if resume_output_dir:
            command.extend(["--resume-output-dir", str(resume_output_dir)])
        if int(options.get("target_slides") or 0) > 0:
            command.extend(["--target-slides", str(int(options["target_slides"]))])
        if options["model_profile"] == "qwen":
            command.extend(["--llm-backend", "local"])
        else:
            command.extend(["--llm-backend", "remote"])
        api_url = str(options.get("api_url") or "").strip()
        model = str(options.get("model") or "").strip()
        if api_url and options["model_profile"] != "qwen":
            command.extend(["--local-llm-api-base", api_url])
        if model and options["model_profile"] != "qwen":
            command.extend(["--local-llm-model", model])
        return command

    def _build_env(self, *, run_root: Path, options: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        env["PRESENT_AGENT_OUTPUT_DIR"] = str(run_root)
        env["PRESENT_AGENT_MODEL_PROFILE"] = options["model_profile"]

        thinkflow_llm_key = str(settings.LLM_API_KEY or "").strip()
        thinkflow_llm_base = str(settings.LLM_API_URL or "").strip()
        thinkflow_llm_model = str(settings.LLM_MODEL or "").strip()
        thinkflow_vlm_model = str(settings.PAPER2PPT_VLM_MODEL or "").strip()
        thinkflow_image_key = str(settings.IMAGE_GEN_API_KEY or "").strip()
        thinkflow_image_base = str(settings.IMAGE_GEN_API_URL or "").strip()
        thinkflow_image_model = str(settings.IMAGE_GEN_MODEL or "").strip()

        present_llm_key = str(env.get("PRESENT_AGENT_LLM_API_KEY") or settings.PRESENT_AGENT_LLM_API_KEY or "").strip()
        present_llm_base = str(env.get("PRESENT_AGENT_LLM_API_BASE") or settings.PRESENT_AGENT_LLM_API_BASE or "").strip()
        present_llm_model = str(env.get("PRESENT_AGENT_LLM_MODEL") or settings.PRESENT_AGENT_LLM_MODEL or "").strip()
        present_vlm_key = str(env.get("PRESENT_AGENT_VLM_API_KEY") or settings.PRESENT_AGENT_VLM_API_KEY or present_llm_key).strip()
        present_vlm_base = str(env.get("PRESENT_AGENT_VLM_API_BASE") or settings.PRESENT_AGENT_VLM_API_BASE or present_llm_base).strip()
        present_vlm_model = str(env.get("PRESENT_AGENT_VLM_MODEL") or settings.PRESENT_AGENT_VLM_MODEL or thinkflow_vlm_model).strip()
        present_image_key = str(env.get("PRESENT_AGENT_IMAGE_API_KEY") or settings.PRESENT_AGENT_IMAGE_API_KEY or "").strip()
        present_image_base = str(env.get("PRESENT_AGENT_IMAGE_API_BASE") or settings.PRESENT_AGENT_IMAGE_API_BASE or "").strip()
        present_image_model = str(env.get("PRESENT_AGENT_IMAGE_MODEL") or settings.PRESENT_AGENT_IMAGE_MODEL or "").strip()

        if options["model_profile"] != "qwen":
            env["PRESENT_AGENT_LLM_API_KEY"] = present_llm_key or str(options.get("api_key") or "").strip() or thinkflow_llm_key
            if present_llm_key:
                env["PRESENT_AGENT_LLM_API_BASE"] = present_llm_base
                env["PRESENT_AGENT_LLM_MODEL"] = present_llm_model
            else:
                env["PRESENT_AGENT_LLM_API_BASE"] = str(options.get("api_url") or "").strip() or thinkflow_llm_base
                env["PRESENT_AGENT_LLM_MODEL"] = str(options.get("model") or "").strip() or thinkflow_llm_model

        env["PRESENT_AGENT_VLM_API_KEY"] = present_vlm_key or thinkflow_llm_key
        if present_vlm_key:
            env["PRESENT_AGENT_VLM_API_BASE"] = present_vlm_base
            env["PRESENT_AGENT_VLM_MODEL"] = present_vlm_model
        else:
            env["PRESENT_AGENT_VLM_API_BASE"] = thinkflow_llm_base
            env["PRESENT_AGENT_VLM_MODEL"] = present_vlm_model or thinkflow_vlm_model

        env["PRESENT_AGENT_IMAGE_API_KEY"] = present_image_key or thinkflow_image_key or thinkflow_llm_key
        if present_image_key:
            env["PRESENT_AGENT_IMAGE_API_BASE"] = present_image_base
            env["PRESENT_AGENT_IMAGE_MODEL"] = present_image_model
        else:
            env["PRESENT_AGENT_IMAGE_API_BASE"] = thinkflow_image_base or thinkflow_llm_base
            env["PRESENT_AGENT_IMAGE_MODEL"] = thinkflow_image_model or present_image_model

        if options["model_profile"] == "qwen":
            env["PRESENT_AGENT_USE_LOCAL_LLM"] = "1"
            env.setdefault("PRESENT_AGENT_LOCAL_LLM_API_BASE", settings.PRESENT_AGENT_LOCAL_LLM_API_BASE)
            env.setdefault("PRESENT_AGENT_LOCAL_LLM_MODEL", settings.PRESENT_AGENT_LOCAL_LLM_MODEL)
        return env

    def prepare_resume_output_dir(self, *, input_path: str, output_dir: Path) -> Optional[Path]:
        if str(input_path).startswith(("http://", "https://")):
            return None
        pdf_path = Path(input_path)
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            return None

        source_dir = self._find_source_dir_for_pdf(pdf_path)
        if not source_dir:
            return None
        markdown_path = self._find_existing_source_markdown(source_dir=source_dir, pdf_path=pdf_path)
        if not markdown_path:
            return None

        resume_dir = output_dir / "editable_ppt_resume" / pdf_path.stem
        markdown_dir = resume_dir / "markdown"
        images_dir = resume_dir / "images" / "self"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        copied_names = self._copy_existing_source_images(source_dir=source_dir, images_dir=images_dir)
        markdown_text = markdown_path.read_text(encoding="utf-8")
        markdown_text = self._rewrite_markdown_image_paths(markdown_text, copied_names)
        (markdown_dir / "full.md").write_text(markdown_text, encoding="utf-8")
        return resume_dir

    def _find_source_dir_for_pdf(self, pdf_path: Path) -> Optional[Path]:
        if pdf_path.parent.name == "original" and pdf_path.parent.parent.exists():
            return pdf_path.parent.parent
        for parent in pdf_path.parents:
            if parent.name == "sources":
                candidate = pdf_path.parent
                while candidate.parent != parent and candidate != candidate.parent:
                    candidate = candidate.parent
                return candidate if candidate.exists() else None
        return None

    def _find_existing_source_markdown(self, *, source_dir: Path, pdf_path: Path) -> Optional[Path]:
        candidates = [
            source_dir / "markdown" / f"{pdf_path.stem}.md",
            source_dir / "mineru" / source_dir.name / f"{source_dir.name}.md",
            source_dir / "mineru" / pdf_path.stem / f"{pdf_path.stem}.md",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        for base in [source_dir / "markdown", source_dir / "mineru"]:
            if not base.exists():
                continue
            markdown_files = sorted(path for path in base.rglob("*.md") if path.is_file())
            if markdown_files:
                return markdown_files[0]
        return None

    def _copy_existing_source_images(self, *, source_dir: Path, images_dir: Path) -> set[str]:
        copied_names: set[str] = set()
        image_dirs = self._find_existing_source_image_dirs(source_dir)
        for image_dir in image_dirs:
            for source_path in sorted(image_dir.rglob("*")):
                if not source_path.is_file() or source_path.suffix.lower() not in self.IMAGE_EXTENSIONS:
                    continue
                target_name = self._unique_image_name(source_path.name, copied_names)
                shutil.copy2(source_path, images_dir / target_name)
                copied_names.add(target_name)
        return copied_names

    def _find_existing_source_image_dirs(self, source_dir: Path) -> List[Path]:
        candidates: List[Path] = []
        mineru_dir = source_dir / "mineru"
        for name in [source_dir.name]:
            candidates.extend(
                [
                    mineru_dir / name / "auto" / "images",
                    mineru_dir / name / "auto" / "_pages",
                ]
            )
        if mineru_dir.exists():
            for child in sorted(mineru_dir.iterdir()):
                if not child.is_dir():
                    continue
                candidates.extend([child / "auto" / "images", child / "auto" / "_pages"])
        existing: List[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve() if candidate.exists() else candidate
            if candidate.exists() and candidate.is_dir() and resolved not in seen:
                existing.append(candidate)
                seen.add(resolved)
        return existing

    def _unique_image_name(self, original_name: str, used_names: set[str]) -> str:
        if original_name not in used_names:
            return original_name
        stem = Path(original_name).stem
        suffix = Path(original_name).suffix
        index = 1
        while True:
            candidate = f"{stem}_{index}{suffix}"
            if candidate not in used_names:
                return candidate
            index += 1

    def _rewrite_markdown_image_paths(self, markdown_text: str, copied_names: set[str]) -> str:
        if not copied_names:
            return markdown_text
        for image_name in sorted(copied_names, key=len, reverse=True):
            escaped_name = re.escape(image_name)
            markdown_text = re.sub(
                rf"\]\((?:\./)?(?:auto/)?(?:images|_pages)/{escaped_name}\)",
                f"](images/self/{image_name})",
                markdown_text,
            )
            markdown_text = re.sub(
                rf'src="(?:\./)?(?:auto/)?(?:images|_pages)/{escaped_name}"',
                f'src="images/self/{image_name}"',
                markdown_text,
            )
        return markdown_text

    def discover_artifacts(self, *, output_dir: Path, run_root: Path) -> Dict[str, Any]:
        pptx_path = output_dir / "editable.pptx"
        if not pptx_path.exists():
            raise HTTPException(status_code=500, detail=f"Editable PPT generation did not produce PPTX: {pptx_path}")

        search_roots = [run_root, output_dir / "editable_ppt_resume"]
        refined_ir = self._find_first_in_roots(search_roots, ["ir/refined/final_ir.json"])
        final_ir = self._find_first_in_roots(search_roots, ["ir/final/final_ir.json"])
        planned_ir = self._find_first_in_roots(search_roots, ["ir/planned/final_ir.json"])
        deck_ir_path = refined_ir or final_ir or planned_ir
        deck_ir = self._read_json(deck_ir_path) if deck_ir_path else {}
        slide_ir_paths = self._find_slide_irs_in_roots(
            search_roots,
            [
                "ir/refined/slides",
                "ir/final/slides",
                "ir/planned/slides",
            ],
        )
        slide_irs = [self._read_json(path) for path in slide_ir_paths]
        slide_irs = [slide for slide in slide_irs if slide]
        if isinstance(deck_ir, dict) and slide_irs and not isinstance(deck_ir.get("slides"), list):
            deck_ir = dict(deck_ir)
            deck_ir["slides"] = slide_irs
        token_usage = self._find_first_in_roots(search_roots, ["token_usage.json"])
        slide_count = len(slide_irs)
        if not slide_count and isinstance(deck_ir, dict):
            slide_count = len(deck_ir.get("slides") or [])

        return {
            "pptx_path": str(pptx_path),
            "pptx_url": _to_outputs_url(str(pptx_path)),
            "deck_ir_path": str(deck_ir_path) if deck_ir_path else "",
            "deck_ir_url": _to_outputs_url(str(deck_ir_path)) if deck_ir_path else "",
            "final_ir_path": str(final_ir) if final_ir else "",
            "final_ir_url": _to_outputs_url(str(final_ir)) if final_ir else "",
            "planned_ir_path": str(planned_ir) if planned_ir else "",
            "planned_ir_url": _to_outputs_url(str(planned_ir)) if planned_ir else "",
            "slide_ir_paths": [str(path) for path in slide_ir_paths],
            "slide_ir_urls": [_to_outputs_url(str(path)) for path in slide_ir_paths],
            "slide_irs": slide_irs,
            "token_usage_path": str(token_usage) if token_usage else "",
            "token_usage_url": _to_outputs_url(str(token_usage)) if token_usage else "",
            "run_root": str(run_root),
            "deck_ir": deck_ir,
            "slide_count": slide_count,
        }

    def _find_first_in_roots(self, roots: List[Path], relative_candidates: List[str]) -> Optional[Path]:
        for root in roots:
            found = self._find_first(root, relative_candidates)
            if found:
                return found
        return None

    def _find_slide_irs_in_roots(self, roots: List[Path], relative_dirs: List[str]) -> List[Path]:
        for root in roots:
            for child in sorted(root.iterdir()) if root.exists() else []:
                if not child.is_dir():
                    continue
                for rel in relative_dirs:
                    slides_dir = child / rel
                    if slides_dir.exists() and slides_dir.is_dir():
                        paths = sorted(slides_dir.glob("slide_*.json"))
                        if paths:
                            return paths
        return []

    def _find_first(self, root: Path, relative_candidates: List[str]) -> Optional[Path]:
        for child in sorted(root.iterdir()) if root.exists() else []:
            if not child.is_dir():
                continue
            for rel in relative_candidates:
                candidate = child / rel
                if candidate.exists() and candidate.is_file():
                    return candidate
        for rel in relative_candidates:
            candidate = root / rel
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _read_json(self, path: Optional[Path]) -> Dict[str, Any]:
        if not path:
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
