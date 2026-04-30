"""Compact skill profiles for library-mode react refinement."""

from __future__ import annotations


def build_library_react_skill_prompt(profile: str) -> str:
    normalized = str(profile or "none").strip().lower()
    if normalized in {"", "none"}:
        return ""
    if normalized == "qwen_v1":
        return """
Library react skill profile: qwen_v1
- Keep the existing page structure unless feedback demands a layout change.
- Prefer editing existing `layout`, `blocks`, `visuals`, and `design_notes` over rewriting the whole slide.
- Preserve real asset bindings by default; replace visuals only when feedback says the current visual is wrong or missing.
- Do not fall back to placeholder or conceptual fake visuals when a real asset already exists.
- Make the smallest IR diff that can plausibly improve the next codegen round.
- Return only changed fields inside `ir_modifications`.
- Do not copy the full slide IR back into the response.
- Do not return unchanged `title`, `subtitle`, or `core_message`.
- Do not resend the full `layout.slots` array unless feedback explicitly requires slot-level changes.
- Keep the response compact; prefer partial field updates over full-object rewrites.
- Keep `tool_calls` minimal and use `[]` when no tool is needed.
""".strip()
    return ""
