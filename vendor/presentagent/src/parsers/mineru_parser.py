"""PresentAgent step 1 parser built on top of the official MinerU API."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.parsers.mineru_client import MinerUClient


class MinerUParser:
    """Normalizes MinerU output into PresentAgent's step 1 layout."""

    def __init__(
        self,
        output_dir: str = "outputs",
        api_token: str | None = None,
        api_base: str = "https://mineru.net/api/v4",
        model_version: str = "vlm",
        poll_interval: float = 5.0,
        timeout: int = 1800,
        client: MinerUClient | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or MinerUClient(
            api_token=api_token or "",
            api_base=api_base,
            model_version=model_version,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    def parse(self, pdf_source: str) -> dict[str, Any]:
        """Parse a local PDF or remote PDF URL and return normalized artifacts."""
        pdf_name = self._resolve_pdf_name(pdf_source)
        target_dir = self.output_dir / pdf_name
        raw_dir = target_dir / "_mineru_raw"
        images_dir = target_dir / "images" / "self"
        markdown_dir = target_dir / "markdown"
        markdown_path = markdown_dir / "full.md"

        target_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
        markdown_dir.mkdir(parents=True, exist_ok=True)

        client_result = self.client.parse_pdf(pdf_source, str(raw_dir))
        extract_dir = Path(client_result["extract_dir"])

        full_md_path = self._find_single_file(extract_dir, {"full.md"})
        content_list_path = self._find_content_list_file(extract_dir)
        asset_source_dir = full_md_path.parent / "images"
        if not asset_source_dir.exists():
            found_dir = self._find_images_dir(extract_dir)
            if found_dir:
                asset_source_dir = found_dir
            else:
                # No images in PDF, create empty directory
                asset_source_dir.mkdir(parents=True, exist_ok=True)

        copied_assets, asset_mapping = self._copy_assets(asset_source_dir, images_dir)
        markdown_text = full_md_path.read_text(encoding="utf-8")
        markdown_text = self._rewrite_markdown_image_paths(markdown_text, asset_mapping)
        markdown_path.write_text(markdown_text, encoding="utf-8")

        selected_images = self._select_figure_images(content_list_path, images_dir, copied_assets, asset_mapping)

        return {
            "markdown": markdown_text,
            "markdown_path": str(markdown_path),
            "images": [str(path) for path in selected_images],
            "images_dir": str(images_dir),
            "image_mapping": asset_mapping,
            "output_dir": str(target_dir),
            "raw_output_dir": str(raw_dir),
            **client_result,
        }

    def _copy_assets(self, source_dir: Path, target_dir: Path) -> tuple[list[Path], dict[str, str]]:
        copied_paths: list[Path] = []
        asset_mapping: dict[str, str] = {}
        if not source_dir.exists():
            return copied_paths, asset_mapping

        image_index = 0
        for file_path in sorted(source_dir.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(source_dir)
            normalized_relative = str(relative_path).replace("\\", "/")
            destination = target_dir / f"{image_index}{file_path.suffix.lower()}"
            shutil.copy2(file_path, destination)
            copied_paths.append(destination)
            asset_mapping[normalized_relative] = destination.name
            image_index += 1

        return copied_paths, asset_mapping

    def _select_figure_images(
        self,
        content_list_path: Path | None,
        images_dir: Path,
        copied_assets: list[Path],
        asset_mapping: dict[str, str],
    ) -> list[Path]:
        if content_list_path is None:
            return copied_assets

        try:
            content_list = json.loads(content_list_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return copied_assets

        selected: list[Path] = []
        for entry in content_list if isinstance(content_list, list) else []:
            if entry.get("type") != "image":
                continue
            img_path = entry.get("img_path")
            if not img_path:
                continue
            normalized = str(img_path).lstrip("./")
            if normalized.startswith("images/"):
                normalized = normalized[len("images/") :]
            remapped_name = asset_mapping.get(normalized)
            if not remapped_name:
                continue
            candidate = images_dir / remapped_name
            if candidate.exists():
                selected.append(candidate)

        return selected or copied_assets

    @staticmethod
    def _rewrite_markdown_image_paths(markdown_text: str, asset_mapping: dict[str, str]) -> str:
        for original_relative, new_name in sorted(asset_mapping.items(), key=lambda item: len(item[0]), reverse=True):
            escaped_original = re.escape(original_relative)
            markdown_text = re.sub(
                rf"\]\((?:\./)?images/{escaped_original}\)",
                f"](images/self/{new_name})",
                markdown_text,
            )
            markdown_text = re.sub(
                rf'src="(?:\./)?images/{escaped_original}"',
                f'src="images/self/{new_name}"',
                markdown_text,
            )
            markdown_text = re.sub(
                rf"src='(?:\./)?images/{escaped_original}'",
                f"src='images/self/{new_name}'",
                markdown_text,
            )
        return markdown_text

    @staticmethod
    def _resolve_pdf_name(pdf_source: str) -> str:
        parsed = urlparse(pdf_source)
        if parsed.scheme in {"http", "https"} and parsed.path:
            return Path(parsed.path).stem or "document"
        return Path(pdf_source).stem

    @staticmethod
    def _find_single_file(root_dir: Path, file_names: set[str]) -> Path:
        for path in sorted(root_dir.rglob("*")):
            if path.is_file() and path.name in file_names:
                return path
        raise FileNotFoundError(f"Could not find any of {sorted(file_names)} under {root_dir}")

    @staticmethod
    def _find_content_list_file(root_dir: Path) -> Path | None:
        for path in sorted(root_dir.rglob("*content_list.json")):
            if path.is_file():
                return path
        return None

    @staticmethod
    def _find_images_dir(root_dir: Path) -> Path | None:
        """Find images directory, return None if not found."""
        for path in sorted(root_dir.rglob("images")):
            if path.is_dir():
                return path
        return None
