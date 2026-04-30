"""Geometry audit for rendered Qwen recipe PPTX files."""

from __future__ import annotations

import math
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation


def audit_pptx(path: str | Path) -> dict[str, Any]:
    """Inspect rendered PPTX geometry for common qwen_lib display failures."""

    prs = Presentation(str(path))
    report: dict[str, Any] = {
        "status": "pass",
        "slide_count": len(prs.slides),
        "text_overlaps": [],
        "text_box_overflows": [],
        "out_of_bounds": [],
        "empty_text_boxes": [],
        "image_aspect_distortions": [],
        "picture_text_overlaps": [],
        "table_cell_overflows": [],
        "duplicate_text_warnings": [],
    }
    slide_width = int(prs.slide_width)
    slide_height = int(prs.slide_height)

    for slide_index, slide in enumerate(prs.slides, start=1):
        text_shapes: list[dict[str, Any]] = []
        picture_shapes: list[dict[str, Any]] = []
        for shape_index, shape in enumerate(slide.shapes):
            bounds = _shape_bounds(shape)
            if _is_out_of_bounds(bounds, slide_width, slide_height):
                report["out_of_bounds"].append(
                    {
                        "slide": slide_index,
                        "shape": shape_index,
                        "bounds": _bounds_inches(bounds),
                    }
                )
            distortion = _picture_aspect_distortion(shape)
            if distortion is not None and distortion["distortion"] > 0.08:
                report["image_aspect_distortions"].append(
                    {
                        "slide": slide_index,
                        "shape": shape_index,
                        **distortion,
                    }
                )
            if distortion is not None:
                picture_shapes.append(
                    {
                        "slide": slide_index,
                        "shape": shape_index,
                        "bounds": bounds,
                    }
                )
            if getattr(shape, "has_table", False):
                report["table_cell_overflows"].extend(
                    _table_cell_overflows(shape, slide_index, shape_index)
                )

            text = ""
            if getattr(shape, "has_text_frame", False):
                text = str(shape.text_frame.text or "").strip()
                if text:
                    overflow = _text_box_overflow(shape, bounds, text)
                    if overflow is not None:
                        report["text_box_overflows"].append(
                            {
                                "slide": slide_index,
                                "shape": shape_index,
                                "text": text[:80],
                                **overflow,
                            }
                        )
                    text_shapes.append(
                        {
                            "slide": slide_index,
                            "shape": shape_index,
                            "bounds": bounds,
                            "text": text[:80],
                        }
                    )
                elif shape.width > 0 and shape.height > 0:
                    report["empty_text_boxes"].append({"slide": slide_index, "shape": shape_index})

        for first_index, first in enumerate(text_shapes):
            for second in text_shapes[first_index + 1 :]:
                if _rects_overlap(first["bounds"], second["bounds"], gap=0):
                    report["text_overlaps"].append(
                        {
                            "slide": slide_index,
                            "shapes": [first["shape"], second["shape"]],
                            "texts": [first["text"], second["text"]],
                        }
                    )
                duplicate = _duplicate_text_warning(first["text"], second["text"])
                if duplicate:
                    report["duplicate_text_warnings"].append(
                        {
                            "slide": slide_index,
                            "shapes": [first["shape"], second["shape"]],
                            "text": duplicate,
                            "severity": "fail",
                        }
                    )
        for picture in picture_shapes:
            for text_shape in text_shapes:
                if _rects_overlap(picture["bounds"], text_shape["bounds"], gap=0):
                    report["picture_text_overlaps"].append(
                        {
                            "slide": slide_index,
                            "picture": picture["shape"],
                            "text_shape": text_shape["shape"],
                            "text": text_shape["text"],
                        }
                    )

    if (
        report["text_overlaps"]
        or report["text_box_overflows"]
        or report["out_of_bounds"]
        or report["image_aspect_distortions"]
        or report["picture_text_overlaps"]
        or report["table_cell_overflows"]
        or any(
        warning.get("severity") == "fail" for warning in report["duplicate_text_warnings"]
        )
    ):
        report["status"] = "fail"
    return report


def _shape_bounds(shape) -> tuple[int, int, int, int]:
    return (int(shape.left), int(shape.top), int(shape.width), int(shape.height))


def _is_out_of_bounds(bounds: tuple[int, int, int, int], slide_width: int, slide_height: int) -> bool:
    left, top, width, height = bounds
    return left < 0 or top < 0 or left + width > slide_width or top + height > slide_height


def _rects_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int], *, gap: int) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return not (
        ax + aw + gap <= bx
        or bx + bw + gap <= ax
        or ay + ah + gap <= by
        or by + bh + gap <= ay
    )


def _bounds_inches(bounds: tuple[int, int, int, int]) -> list[float]:
    return [round(value / 914400, 3) for value in bounds]


def _picture_aspect_distortion(shape) -> dict[str, float] | None:
    if not hasattr(shape, "image"):
        return None
    try:
        with Image.open(BytesIO(shape.image.blob)) as image:
            native_width, native_height = image.size
    except Exception:
        return None
    if native_width <= 0 or native_height <= 0 or int(shape.height) <= 0:
        return None
    native_aspect = float(native_width) / float(native_height)
    displayed_aspect = float(shape.width) / float(shape.height)
    if native_aspect <= 0 or displayed_aspect <= 0:
        return None
    return {
        "native_aspect": round(native_aspect, 3),
        "displayed_aspect": round(displayed_aspect, 3),
        "distortion": round(abs(math.log(native_aspect / displayed_aspect)), 3),
    }


def _text_box_overflow(shape, bounds: tuple[int, int, int, int], text: str) -> dict[str, float] | None:
    left, top, width, height = bounds
    del left, top
    width_inches = width / 914400
    height_inches = height / 914400
    font_size = _shape_max_font_size(shape) or 14.0
    margin_left = _emu_to_inches(getattr(shape.text_frame, "margin_left", 0))
    margin_right = _emu_to_inches(getattr(shape.text_frame, "margin_right", 0))
    margin_top = _emu_to_inches(getattr(shape.text_frame, "margin_top", 0))
    margin_bottom = _emu_to_inches(getattr(shape.text_frame, "margin_bottom", 0))
    usable_width = max(width_inches - margin_left - margin_right, 0.2)
    required_lines = _estimate_wrapped_line_count(text, usable_width, font_size)
    required_height = required_lines * font_size * 1.18 / 72.0 + margin_top + margin_bottom
    if required_height <= height_inches * 1.08:
        return None
    return {
        "box_height": round(height_inches, 3),
        "estimated_required_height": round(required_height, 3),
        "font_size": round(font_size, 1),
    }


def _shape_max_font_size(shape) -> float | None:
    sizes = []
    try:
        for paragraph in shape.text_frame.paragraphs:
            if paragraph.font.size is not None:
                sizes.append(paragraph.font.size.pt)
            for run in paragraph.runs:
                if run.font.size is not None:
                    sizes.append(run.font.size.pt)
    except Exception:
        return None
    return max(sizes) if sizes else None


def _table_cell_overflows(shape, slide_index: int, shape_index: int) -> list[dict[str, Any]]:
    overflows: list[dict[str, Any]] = []
    try:
        table = shape.table
        row_count = len(table.rows)
        col_count = len(table.columns)
        if row_count <= 0 or col_count <= 0:
            return []
        column_widths = [column.width / 914400 for column in table.columns]
        row_heights = [row.height / 914400 for row in table.rows]
        for row_index, row in enumerate(table.rows):
            for col_index, cell in enumerate(row.cells):
                text = str(cell.text_frame.text or "").strip()
                if not text:
                    continue
                font_size = _cell_max_font_size(cell) or 11.0
                usable_width = max(column_widths[col_index] - 0.12, 0.2)
                usable_height = max(row_heights[row_index] - 0.08, 0.04)
                required_lines = _estimate_wrapped_line_count(text, usable_width, font_size)
                required_height = required_lines * font_size * 1.12 / 72.0
                if required_height > usable_height * 1.08:
                    overflows.append(
                        {
                            "slide": slide_index,
                            "shape": shape_index,
                            "row": row_index,
                            "col": col_index,
                            "text": text[:80],
                            "cell_height": round(row_heights[row_index], 3),
                            "estimated_required_height": round(required_height, 3),
                            "font_size": round(font_size, 1),
                        }
                    )
    except Exception:
        return overflows
    return overflows


def _cell_max_font_size(cell) -> float | None:
    sizes = []
    try:
        for paragraph in cell.text_frame.paragraphs:
            if paragraph.font.size is not None:
                sizes.append(paragraph.font.size.pt)
            for run in paragraph.runs:
                if run.font.size is not None:
                    sizes.append(run.font.size.pt)
    except Exception:
        return None
    return max(sizes) if sizes else None


def _emu_to_inches(value: Any) -> float:
    try:
        return float(value) / 914400.0
    except Exception:
        return 0.0


def _estimate_wrapped_line_count(text: str, usable_width: float, font_size: float) -> int:
    if not text:
        return 1
    chars_per_line = max(int(usable_width * 6.0 * 12.0 / max(font_size, 1.0)), 4)
    lines = 0
    for raw_line in str(text).splitlines() or [""]:
        weighted = 0.0
        for char in raw_line.strip():
            weighted += 1.0 if ord(char) > 127 else 0.56
        lines += max(1, math.ceil(weighted / chars_per_line))
    return max(lines, 1)


def _duplicate_text_warning(first: str, second: str) -> str | None:
    first_norm = _normalize_visible_text(first)
    second_norm = _normalize_visible_text(second)
    if len(first_norm) < 18 or len(second_norm) < 18:
        return None
    if first_norm in second_norm:
        return first_norm[:80]
    if second_norm in first_norm:
        return second_norm[:80]
    common = _longest_common_substring(first_norm, second_norm)
    if len(common) >= 24 and _is_substantive_duplicate(common):
        return common[:80]
    return None


def _normalize_visible_text(text: str) -> str:
    return "".join(str(text or "").split())


def _is_substantive_duplicate(text: str) -> bool:
    if len(text) < 24:
        return False
    has_digit = any(char.isdigit() for char in text)
    has_cjk = any(ord(char) > 127 for char in text)
    word_count = len(re.findall(r"[A-Za-z]+", text))
    if has_digit or has_cjk:
        return True
    return word_count >= 5


def _longest_common_substring(first: str, second: str) -> str:
    if len(first) > len(second):
        first, second = second, first
    best = ""
    previous = [0] * (len(second) + 1)
    for i, first_char in enumerate(first, start=1):
        current = [0] * (len(second) + 1)
        for j, second_char in enumerate(second, start=1):
            if first_char == second_char:
                current[j] = previous[j - 1] + 1
                if current[j] > len(best):
                    best = first[i - current[j] : i]
        previous = current
    return best
