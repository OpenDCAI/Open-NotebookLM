"""Compact skill profiles for library-mode code generation."""

from __future__ import annotations


def build_library_generation_skill_prompt(profile: str) -> str:
    normalized = str(profile or "none").strip().lower()
    if normalized in {"", "none"}:
        return ""
    if normalized == "qwen_v1":
        return """
Library generation skill profile: qwen_v1
- Read `layout.slots` before choosing helpers; pick one scaffold that matches the dominant structure.
- Keep one helper chain: scaffold first, then body blocks, then local polish. Do not rebuild the whole page twice.
- Render body content from real IR fields only: `blocks`, `points`, `core_message`, `visuals`, `selected_asset_path`.
- If a real asset exists, render it in the intended slot; do not replace a real asset with a conceptual fake visual.
- If no real asset exists, keep the visual area simple and support the page with content rather than inventing decorative diagrams.
""".strip()
    return ""


def build_library_generation_repair_hint(profile: str, error_message: str) -> str:
    normalized = str(profile or "none").strip().lower()
    if normalized != "qwen_v1":
        return ""
    error_lower = str(error_message or "").lower()
    if "rgbcolor" in error_lower:
        return """
Qwen generation harness repair hint:
- This is an RGBColor typing failure. Use `RGBColor(...)` for rgb assignments and do not assign plain tuples or ints to `.rgb`.
""".strip()
    if "syntaxerror" in error_lower or "was never closed" in error_lower:
        return """
Qwen generation harness repair hint:
- This is a SyntaxError. Simplify the last edited block, close every bracket explicitly, and avoid adding new nested structures in this repair.
""".strip()
    return ""
