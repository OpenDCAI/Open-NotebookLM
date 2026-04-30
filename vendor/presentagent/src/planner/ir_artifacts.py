"""Persist deck IR and per-slide IR as JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class IRArtifactWriter:
    def load_existing_slide_docs(
        self,
        output_dir: str,
        stage: str = "planned",
    ) -> dict[str, dict[str, Any]]:
        slides_dir = Path(output_dir) / "ir" / stage / "slides"
        if not slides_dir.exists():
            return {}
        slide_docs: dict[str, dict[str, Any]] = {}
        for slide_path in sorted(slides_dir.glob("slide_*.json")):
            try:
                slide_doc = json.loads(slide_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            slide_id = slide_doc.get("slide_id") or slide_path.stem
            slide_docs[slide_id] = slide_doc
        return slide_docs

    def write_slide_briefs(
        self,
        slide_briefs: dict[str, Any],
        output_dir: str,
        stage: str = "planned",
    ) -> str:
        root = Path(output_dir) / "ir" / stage
        root.mkdir(parents=True, exist_ok=True)
        slide_briefs_path = root / "slide_briefs.json"
        slide_briefs_path.write_text(
            json.dumps(slide_briefs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(slide_briefs_path)

    def write_deck_stage(
        self,
        deck_stage: dict[str, Any],
        output_dir: str,
        stage: str = "planned",
    ) -> str:
        root = Path(output_dir) / "ir" / stage
        root.mkdir(parents=True, exist_ok=True)
        deck_stage_path = root / "deck_stage.json"
        deck_stage_path.write_text(
            json.dumps(deck_stage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(deck_stage_path)

    def write_single_slide(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        output_dir: str,
        *,
        stage: str = "planned",
        slide_number: int = 1,
        material_requests: list[dict[str, Any]] | None = None,
    ) -> str:
        root = Path(output_dir) / "ir" / stage
        slides_dir = root / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)
        slide_id = slide_ir.get("slide_id", f"slide_{slide_number:02d}")
        slide_doc = self._build_slide_document(deck_ir, slide_ir, stage=stage, slide_number=slide_number)
        if material_requests is not None:
            slide_doc["material_requests"] = material_requests
        slide_path = slides_dir / f"{slide_id}.json"
        slide_path.write_text(json.dumps(slide_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(slide_path)

    def write(
        self,
        ir: dict[str, Any],
        output_dir: str,
        stage: str = "planned",
        slide_briefs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = Path(output_dir) / "ir" / stage
        slides_dir = root / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        deck_id = ir.get("metadata", {}).get("deck_id", "")
        slide_entries: list[dict[str, Any]] = []
        slide_paths: dict[str, str] = {}

        for index, slide in enumerate(ir.get("slides", []), start=1):
            slide_id = slide.get("slide_id", f"slide_{index:02d}")
            slide_doc = self._build_slide_document(ir, slide, stage=stage, slide_number=index)
            slide_path = slides_dir / f"{slide_id}.json"
            slide_path.write_text(json.dumps(slide_doc, ensure_ascii=False, indent=2), encoding="utf-8")
            slide_paths[slide_id] = str(slide_path)
            slide_entries.append(
                {
                    "slide_id": slide_id,
                    "slide_number": index,
                    "title": slide.get("title", ""),
                    "type": slide.get("type", "content"),
                    "layout_name": slide.get("layout", {}).get("name", ""),
                    "path": str(slide_path),
                }
            )

        deck_doc = self._build_deck_document(ir, stage=stage, deck_id=deck_id, slide_entries=slide_entries)
        deck_path = root / "deck_ir.json"
        deck_path.write_text(json.dumps(deck_doc, ensure_ascii=False, indent=2), encoding="utf-8")

        bundle_path = root / "final_ir.json"
        bundle_doc = dict(ir)
        bundle_doc["slide_manifest"] = slide_entries
        bundle_doc["metadata"] = self._with_stage(ir.get("metadata", {}), stage=stage, deck_id=deck_id)
        bundle_path.write_text(json.dumps(bundle_doc, ensure_ascii=False, indent=2), encoding="utf-8")

        evidence_path = str(root / "slide_evidence.json")
        evidence_doc = self._build_evidence_document(ir, stage=stage, deck_id=deck_id)
        Path(evidence_path).write_text(
            json.dumps(evidence_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        slide_briefs_path = ""
        if slide_briefs:
            slide_briefs_doc = dict(slide_briefs)
            slide_briefs_doc["metadata"] = self._with_stage(
                slide_briefs.get("metadata", {}),
                stage=stage,
                deck_id=slide_briefs.get("metadata", {}).get("deck_id", deck_id),
            )
            slide_briefs_path = str(root / "slide_briefs.json")
            Path(slide_briefs_path).write_text(
                json.dumps(slide_briefs_doc, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return {
            "deck_path": str(deck_path),
            "bundle_path": str(bundle_path),
            "slides_dir": str(slides_dir),
            "slide_paths": slide_paths,
            "slide_briefs_path": slide_briefs_path,
            "evidence_path": evidence_path,
        }

    def _build_deck_document(
        self,
        ir: dict[str, Any],
        *,
        stage: str,
        deck_id: str,
        slide_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "metadata": self._with_stage(ir.get("metadata", {}), stage=stage, deck_id=deck_id),
            "title": ir.get("title", ""),
            "subtitle": ir.get("subtitle", ""),
            "storyline": ir.get("storyline", {}),
            "theme": ir.get("theme", {}),
            "longdoc_profile": ir.get("longdoc_profile", {}),
            "deck_outline": ir.get("deck_outline", []),
            "material_requests": ir.get("material_requests", []),
            "slide_manifest": slide_entries,
            "planner_notes": ir.get("planner_notes", []),
            "source_asset_index": ir.get("source_asset_index", {}),
        }

    def _build_evidence_document(
        self,
        ir: dict[str, Any],
        *,
        stage: str,
        deck_id: str,
    ) -> dict[str, Any]:
        slides = []
        for index, slide in enumerate(ir.get("slides", []), start=1):
            slides.append(
                {
                    "slide_id": slide.get("slide_id", f"slide_{index:02d}"),
                    "slide_number": slide.get("slide_number", index),
                    "title": slide.get("title", ""),
                    "core_message": slide.get("core_message", ""),
                    "brief_id": slide.get("brief_id", ""),
                    "source_chunk_ids": slide.get("source_chunk_ids", []),
                    "source_evidence": slide.get("source_evidence", []),
                }
            )
        return {
            "metadata": {
                "schema_name": "presentagent.slide_evidence",
                "schema_version": ir.get("metadata", {}).get("schema_version", "1.0"),
                "deck_id": deck_id,
                "stage": stage,
            },
            "title": ir.get("title", ""),
            "slides": slides,
        }

    def _build_slide_document(
        self,
        deck_ir: dict[str, Any],
        slide_ir: dict[str, Any],
        *,
        stage: str,
        slide_number: int,
    ) -> dict[str, Any]:
        slide_id = slide_ir.get("slide_id", f"slide_{slide_number:02d}")
        deck_id = deck_ir.get("metadata", {}).get("deck_id", slide_ir.get("deck_id", ""))
        slide_doc = dict(slide_ir)
        slide_doc["metadata"] = self._with_stage(
            slide_ir.get("metadata", {}),
            stage=stage,
            deck_id=deck_id,
            slide_id=slide_id,
        )
        slide_doc["deck_id"] = deck_id
        slide_doc["slide_number"] = slide_ir.get("slide_number", slide_number)
        slide_doc["deck_context"] = {
            "title": deck_ir.get("title", ""),
            "subtitle": deck_ir.get("subtitle", ""),
            "theme": deck_ir.get("theme", {}),
            "storyline": deck_ir.get("storyline", {}),
            "planner_notes": deck_ir.get("planner_notes", []),
        }
        return slide_doc

    @staticmethod
    def _with_stage(
        metadata: dict[str, Any],
        *,
        stage: str,
        deck_id: str,
        slide_id: str = "",
    ) -> dict[str, Any]:
        merged = dict(metadata)
        merged["stage"] = stage
        if deck_id:
            merged["deck_id"] = deck_id
        if slide_id:
            merged["slide_id"] = slide_id
        return merged
