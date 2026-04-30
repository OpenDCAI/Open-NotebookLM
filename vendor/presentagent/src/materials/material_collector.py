"""Step 2 material set collector for PresentAgent."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency in some test envs
    Image = None

from .vlm_descriptor import VLMDescriptor


class MaterialCollector:
    """Collects local assets and builds a normalized material manifest."""

    SUPPORTED_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".gif",
        ".svg",
    }

    def __init__(self, descriptor: VLMDescriptor | None = None) -> None:
        self.descriptor = descriptor

    def collect(self, document_dir: str, markdown_text: str | None = None) -> dict[str, Any]:
        return self.collect_with_context(
            document_dir,
            markdown_text=markdown_text,
            asset_request_contexts=None,
            progress_callback=None,
        )

    def collect_with_context(
        self,
        document_dir: str,
        markdown_text: str | None = None,
        asset_request_contexts: dict[str, dict[str, Any]] | None = None,
        progress_callback=None,
    ) -> dict[str, Any]:
        doc_dir = Path(document_dir)
        if not doc_dir.exists():
            raise FileNotFoundError(f"Document directory not found: {doc_dir}")

        layout = self._ensure_layout(doc_dir)
        markdown_path, normalized_markdown = self._ensure_markdown(
            doc_dir=doc_dir,
            markdown_dir=layout["markdown_dir"],
            markdown_text=markdown_text,
        )

        assets = self._scan_assets(layout["scan_dirs"])
        merged_request_contexts = self._merge_asset_request_contexts(
            doc_dir,
            assets,
            asset_request_contexts or {},
        )
        descriptions, description_records = self._describe_assets(
            assets,
            normalized_markdown,
            merged_request_contexts,
            progress_callback=progress_callback,
        )
        for asset in assets:
            asset["description"] = descriptions.get(asset["path"], "")
            asset["description_record"] = description_records.get(asset["path"], {})
            asset["request_context"] = merged_request_contexts.get(asset["path"], {})
        asset_index = {asset["asset_id"]: asset for asset in assets}
        assets_by_category = self._group_assets_by_category(assets)
        asset_catalog = self._build_asset_catalog(assets, description_records)

        manifest = {
            "document_dir": str(doc_dir),
            "markdown_path": str(markdown_path),
            "markdown_preview": normalized_markdown[:4000],
            "images": [
                asset["path"]
                for asset in assets
                if asset["asset_kind"] == "image"
            ],
            "assets": assets,
            "asset_index": asset_index,
            "assets_by_category": assets_by_category,
            "asset_request_contexts": merged_request_contexts,
            "asset_catalog": asset_catalog,
        }

        manifest_path = layout["materials_dir"] / "material_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        descriptions_path = layout["materials_dir"] / "asset_descriptions.json"
        descriptions_path.write_text(
            json.dumps(descriptions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        asset_catalog_path = layout["materials_dir"] / "asset_catalog.json"
        asset_catalog_path.write_text(
            json.dumps(asset_catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        request_contexts_path = layout["materials_dir"] / "asset_request_contexts.json"
        request_contexts_path.write_text(
            json.dumps(merged_request_contexts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "markdown": normalized_markdown,
            "markdown_path": str(markdown_path),
            "images": manifest["images"],
            "assets": assets,
            "asset_index": asset_index,
            "assets_by_category": assets_by_category,
            "descriptions": descriptions,
            "description_records": description_records,
            "asset_catalog": asset_catalog,
            "asset_request_contexts": merged_request_contexts,
            "manifest_path": str(manifest_path),
            "descriptions_path": str(descriptions_path),
            "asset_catalog_path": str(asset_catalog_path),
            "request_contexts_path": str(request_contexts_path),
            "document_dir": str(doc_dir),
            "materials_dir": str(layout["materials_dir"]),
        }

    def _ensure_layout(self, doc_dir: Path) -> dict[str, Any]:
        markdown_dir = doc_dir / "markdown"
        images_root = doc_dir / "images"
        materials_dir = doc_dir / "materials"

        category_dirs = {
            "self": images_root / "self",
            "paper2any": images_root / "paper2any",
        }

        for path in [markdown_dir, materials_dir, *category_dirs.values()]:
            path.mkdir(parents=True, exist_ok=True)

        scan_dirs: dict[str, Path] = dict(category_dirs)

        return {
            "markdown_dir": markdown_dir,
            "materials_dir": materials_dir,
            "scan_dirs": scan_dirs,
        }

    def _ensure_markdown(
        self,
        doc_dir: Path,
        markdown_dir: Path,
        markdown_text: str | None,
    ) -> tuple[Path, str]:
        markdown_path = markdown_dir / "full.md"

        if markdown_text is None:
            root_markdown = doc_dir / "full.md"
            if root_markdown.exists():
                markdown_text = root_markdown.read_text(encoding="utf-8")
            elif markdown_path.exists():
                markdown_text = markdown_path.read_text(encoding="utf-8")
            else:
                raise FileNotFoundError(f"No markdown found under {doc_dir}")

        markdown_path.write_text(markdown_text, encoding="utf-8")

        # Remove root markdown after copying to markdown/
        root_markdown_path = doc_dir / "full.md"
        if root_markdown_path.exists() and root_markdown_path != markdown_path:
            root_markdown_path.unlink()

        return markdown_path, markdown_text

    def _scan_assets(self, category_dirs: dict[str, Path]) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        for category, directory in category_dirs.items():
            if not directory.exists():
                continue

            normalized_category = "icons" if category.startswith("icons") else category
            asset_kind = "icon" if normalized_category == "icons" else "image"
            for file_path in sorted(directory.rglob("*")):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                    continue
                resolved = str(file_path.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                relative_path = str(file_path.relative_to(directory)).replace("\\", "/")
                assets.append(
                    {
                        "asset_id": f"{normalized_category}:{relative_path}",
                        "path": str(file_path),
                        "relative_path": relative_path,
                        "category": normalized_category,
                        "asset_kind": asset_kind,
                        "extension": file_path.suffix.lower(),
                        **self._build_asset_file_metadata(file_path),
                    }
                )

        return assets

    def _describe_assets(
        self,
        assets: list[dict[str, Any]],
        markdown_text: str,
        asset_request_contexts: dict[str, dict[str, Any]],
        progress_callback=None,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        if self.descriptor is None or not assets:
            return {}, {}

        return self.descriptor.describe_assets_with_metadata(
            assets,
            markdown_text=markdown_text,
            asset_request_contexts=asset_request_contexts,
            progress_callback=progress_callback,
        )

    def _merge_asset_request_contexts(
        self,
        doc_dir: Path,
        assets: list[dict[str, Any]],
        runtime_contexts: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        merged_contexts: dict[str, dict[str, Any]] = {}
        materials_dir = doc_dir / "materials"

        persisted_contexts_path = materials_dir / "asset_request_contexts.json"
        if persisted_contexts_path.exists():
            try:
                persisted_contexts = json.loads(persisted_contexts_path.read_text(encoding="utf-8"))
                if isinstance(persisted_contexts, dict):
                    for path, context in persisted_contexts.items():
                        if isinstance(context, dict):
                            merged_contexts[path] = context
            except json.JSONDecodeError:
                pass

        resolution_path = materials_dir / "material_resolution.json"
        if resolution_path.exists():
            try:
                resolution_doc = json.loads(resolution_path.read_text(encoding="utf-8"))
                resolutions = resolution_doc.get("requests", resolution_doc) if isinstance(resolution_doc, dict) else resolution_doc
                for resolution in resolutions:
                    if not isinstance(resolution, dict):
                        continue
                    candidate = resolution.get("resolved_candidate") or {}
                    path = candidate.get("path")
                    if not path:
                        continue
                    merged_contexts[path] = {
                        "request_id": resolution.get("request_id", ""),
                        "caption": resolution.get("caption", ""),
                        "title": resolution.get("title", ""),
                        "purpose": resolution.get("purpose", ""),
                        "asset_type": resolution.get("asset_type", ""),
                        "target_slide_id": resolution.get("target_slide_id", ""),
                    }
            except json.JSONDecodeError:
                pass

        for path, context in runtime_contexts.items():
            merged_contexts[path] = context

        asset_paths = {asset["path"] for asset in assets}
        return {path: context for path, context in merged_contexts.items() if path in asset_paths}

    @staticmethod
    def _group_assets_by_category(assets: list[dict[str, Any]]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for asset in assets:
            grouped.setdefault(asset["category"], []).append(asset["asset_id"])
        return grouped


    @staticmethod
    def _build_asset_catalog(
        assets: list[dict[str, Any]],
        description_records: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for asset in assets:
            record = description_records.get(asset["path"], {})

            # Determine if asset is icon-suitable (can be reused)
            is_icon_suitable = MaterialCollector._is_icon_like(asset)

            catalog.append(
                {
                    "asset_id": asset["asset_id"],
                    "path": asset["path"],
                    "relative_path": asset.get("relative_path", ""),
                    "category": asset.get("category", ""),
                    "asset_kind": asset.get("asset_kind", ""),
                    "extension": asset.get("extension", ""),
                    "file_size_bytes": asset.get("file_size_bytes"),
                    "width_px": asset.get("width_px"),
                    "height_px": asset.get("height_px"),
                    "aspect_ratio": asset.get("aspect_ratio"),
                    "orientation": asset.get("orientation", "unknown"),
                    "caption": record.get("caption", ""),
                    "description": record.get("description", asset.get("description", "")),
                    "content_summary": record.get("content_summary", ""),
                    "recommended_usage": record.get("recommended_usage", ""),
                    "semantic_keywords": record.get("semantic_keywords", []),
                    "visual_type": record.get("visual_type", ""),
                    "quality_notes": record.get("quality_notes", ""),
                    "request_context": asset.get("request_context", {}),
                    "use_count": 0,
                    "used_in_slides": [],
                    "is_icon_suitable": is_icon_suitable,
                }
            )
        return catalog

    @staticmethod
    def _is_icon_like(asset: dict[str, Any]) -> bool:
        """Determine if asset is suitable for repeated use (icon characteristics)."""
        width = asset.get("width_px", 0)
        height = asset.get("height_px", 0)

        # Small size (< 200px on longest side)
        if width > 0 and height > 0 and max(width, height) < 200:
            return True

        # Icon category or filename contains icon keywords
        category = asset.get("category", "").lower()
        path = asset.get("path", "").lower()
        icon_keywords = ["icon", "logo", "symbol", "glyph", "pictogram"]

        if category == "icons" or any(kw in path for kw in icon_keywords):
            return True

        return False

    @staticmethod
    def _build_asset_file_metadata(file_path: Path) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "file_size_bytes": None,
            "width_px": None,
            "height_px": None,
            "aspect_ratio": None,
            "orientation": "unknown",
        }
        try:
            metadata["file_size_bytes"] = file_path.stat().st_size
        except OSError:
            pass

        if Image is not None:
            try:
                with Image.open(file_path) as image:
                    width, height = image.size
                metadata["width_px"] = int(width)
                metadata["height_px"] = int(height)
                if width > 0 and height > 0:
                    metadata["aspect_ratio"] = round(width / height, 4)
                    if width > height:
                        metadata["orientation"] = "landscape"
                    elif width < height:
                        metadata["orientation"] = "portrait"
                    else:
                        metadata["orientation"] = "square"
            except Exception:
                pass

        return metadata
