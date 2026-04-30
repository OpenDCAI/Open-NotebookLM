"""IR refinement prompt builder for LLM-based IR modification."""

import json
from typing import Any, Dict, Optional

from .library_react_skill_profiles import build_library_react_skill_prompt


def build_ir_refinement_prompt(
    editable_view: Dict[str, Any],
    vlm_feedback: Dict[str, Any],
    history: Optional[Dict[str, Any]] = None,
    available_tools: Optional[list[Dict[str, str]]] = None,
    mode: str = "direct",
    library_react_skill: str = "none",
) -> str:
    """Build prompt for LLM to refine slide IR based on VLM feedback.

    Args:
        editable_view: Output from project_editable_ir_view()
        vlm_feedback: VLM evaluation result with score, feedback, strengths
        history: Previous refinement history

    Returns:
        Complete prompt for IR refinement
    """
    history = history or {}
    available_tools = available_tools or []

    history_context = ""
    if history.get("previous_feedback"):
        history_context = f"""
## Previous Refinement History
Iteration: {history.get('iteration', 0)}
Previous Feedback:
{json.dumps(history['previous_feedback'], ensure_ascii=False, indent=2)[:800]}

**Important**: Avoid reverting changes that were already made.
"""

    tools_context = ""
    if available_tools:
        tools_context = "\n## Available Tools\n"
        for tool in available_tools:
            tools_context += f"- **{tool['name']}**: {tool['description']}\n"
    mode_guidance = ""
    if mode == "library":
        skill_prompt = build_library_react_skill_prompt(library_react_skill)
        mode_guidance = """
Library-mode guidance:
- Refine the full editable IR; do not collapse the slide into a summary-only plan.
- Preserve existing visuals and asset bindings unless the feedback says the current visual is clearly wrong or missing.
- Prefer editing existing `layout`, `blocks`, `visuals`, and `design_notes` over inventing a brand-new structure.
- If the slide needs a different visual, use `collect_material`; do not replace a real asset with a placeholder or conceptual fake visual unless the feedback explicitly calls for text-only treatment.
"""
        if skill_prompt:
            mode_guidance += f"\n{skill_prompt}\n"

    compact_qwen_schema = mode == "library" and library_react_skill == "qwen_v1"
    if compact_qwen_schema:
        output_schema = f"""{{
  "ir_modifications": {{
    "slide_id": "{editable_view.get('slide_id')}",
    "layout": {{...}},
    "blocks": [...],
    "visuals": [...],
    "design_notes": [...]
  }},
  "tool_calls": [
    {{
      "tool": "collect_material",
      "params": {{
        "material_request": {{
          "request_id": "slide_XX_image_YY",
          "asset_type": "image",
          "caption": "Short description",
          "purpose": "Why this visual is needed",
          "target_slide_id": "{editable_view.get('slide_id')}",
          "size_preference": "large",
          "orientation_preference": "landscape",
          "minimum_vlm_score": 0.75
        }},
        "replace_visual_id": "slide_XX_visual_YY"
      }}
    }}
  ]
}}"""
    else:
        output_schema = f"""{{
  "ir_modifications": {{
    "slide_id": "{editable_view.get('slide_id')}",
    "title": "...",
    "subtitle": "...",
    "core_message": "...",
    "layout": {{...}},
    "blocks": [...],
    "visuals": [...],
    "design_notes": [...]
  }},
  "tool_calls": [
    {{
      "tool": "collect_material",
      "params": {{
        "material_request": {{
          "request_id": "slide_XX_image_YY",
          "asset_type": "image",
          "caption": "Detailed description",
          "purpose": "Why this visual is needed",
          "target_slide_id": "{editable_view.get('slide_id')}",
          "size_preference": "large",
          "orientation_preference": "landscape",
          "minimum_vlm_score": 0.75
        }},
        "replace_visual_id": "slide_XX_visual_YY"
      }}
    }}
  ],
  "rationale": "Brief explanation of changes"
}}"""

    prompt = f"""You are an IR refinement agent. Modify the slide IR and optionally call tools based on VLM evaluation feedback.

{history_context}
{tools_context}

## Current VLM Evaluation
Score: {vlm_feedback.get('score', 0)}/10
Dimension Scores: {json.dumps(vlm_feedback.get('dimension_scores', {}), ensure_ascii=False)}

Feedback:
{vlm_feedback.get('feedback', 'No specific feedback')}

Strengths:
{json.dumps(vlm_feedback.get('strengths', []), ensure_ascii=False)}

## Current Slide IR (Editable View)
{json.dumps(editable_view, ensure_ascii=False, indent=2)}

---

**Your Task**: Generate an action plan to address VLM feedback. You can:

1. **Modify IR directly** (always available):
   - Adjust layout (name, density, slots)
   - Modify content blocks
   - Update visuals

2. **Call tools** (if available):
   - Use "collect_material" when current visual is inappropriate

{mode_guidance}

**Output JSON**:
{output_schema}

**Guidelines**:
- Make targeted changes based on feedback
- Only call tools when necessary (e.g., visual is truly inappropriate)
- If no tools needed, set "tool_calls": []
"""

    if compact_qwen_schema:
        prompt += """
- For qwen_v1, keep the JSON small and patch-like.
- Omit unchanged `title`, `subtitle`, and `core_message`.
- Omit unchanged `layout.slots`; only include slot entries if a slot itself must change.
- Prefer modifying a few block fields over rewriting every block.
"""

    return prompt
