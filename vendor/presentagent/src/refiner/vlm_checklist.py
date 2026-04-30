"""Industrial-grade VLM evaluation checklist for slide quality assessment."""

VLM_EVALUATION_CHECKLIST = """
# Slide Quality Evaluation Checklist

Evaluate the slide screenshot against the IR specification across 6 dimensions:

## 1. Structure (Layout / Geometry) - Auto-detectable
- [ ] **Alignment**: Elements properly aligned (left/right/center, baseline consistency)
- [ ] **Spacing**: Consistent margins, padding, line spacing
- [ ] **Overlap**: No text covering images, no element occlusion
- [ ] **Layout Structure**: Clear reading path (Z/F pattern), proper grouping, visual hierarchy

## 2. Visual Design (Aesthetics)
- [ ] **Typography**: Clear font size hierarchy (title vs body), max 2 font families, readable line length
- [ ] **Color**: Sufficient contrast, consistent palette, appropriate emphasis color usage
- [ ] **Visual Hierarchy**: Clear "first look" element, key information highlighted
- [ ] **Whitespace**: Balanced density, even distribution, no overcrowding

## 3. Image Quality & Integration
- [ ] **Image Quality**: Adequate resolution, no blur/compression artifacts, no distortion
- [ ] **Image Integration**: Consistent style, proper alignment with text, appropriate size
- [ ] **Image Layout**: Correct position in reading flow, proper text-image relationship

## 4. Information Expression (Content Design)
- [ ] **Information Density**: Appropriate text amount (no wall of text, no emptiness)
- [ ] **Structured Expression**: Proper use of bullets/hierarchy, logical order
- [ ] **Emphasis**: Key conclusions highlighted (bold/color)

## 5. Consistency
- [ ] **Style Consistency**: Unified fonts, colors, icon styles
- [ ] **Layout Consistency**: Consistent positioning across similar slide types

## 6. Content Alignment (vs IR)
- [ ] **Title Match**: Slide title matches IR specification
- [ ] **Core Message**: Visual presentation supports the core message
- [ ] **Source Evidence**: Content grounded in source evidence (no hallucination)

---

**Scoring Guide** (Total: 0-10):
- **Structure (0-3)**: Layout geometry correctness - CRITICAL for professional appearance
  - Alignment precision (1.0)
  - Spacing consistency (1.0)
  - No overlap/occlusion (0.5)
  - Layout structure clarity (0.5)
- Visual Design (0-2): Aesthetic quality
- Image Integration (0-2): Visual element quality
- Information Expression (0-2): Content clarity
- Consistency (0-0.5): Cross-element uniformity
- Content Alignment (0-0.5): IR compliance and no hallucination

**Total Score**: 0-10
**Threshold**: 8.0 for acceptance

**Note**: Structure dimension has higher weight (3 points) because layout precision is the foundation of professional slides. Even minor alignment or spacing issues are unacceptable.
"""


def build_vlm_evaluation_prompt(
    vlm_view: dict,
    screenshot_base64: str,
    iteration: int = 0
) -> str:
    """Build VLM evaluation prompt with checklist + IR view + screenshot.

    Args:
        vlm_view: Output from project_vlm_view()
        screenshot_base64: Base64-encoded PNG screenshot
        iteration: Current ReAct iteration (0 for initial)

    Returns:
        Complete VLM prompt
    """
    import json

    history_context = ""
    if vlm_view.get("history"):
        history_context = f"""
## Previous Iteration Feedback (Round {vlm_view['history']['iteration']})
{json.dumps(vlm_view['history']['previous_feedback'], ensure_ascii=False, indent=2)}

**Focus**: Check if previous issues were addressed.
"""

    prompt = f"""You are a professional slide design evaluator. Evaluate this slide screenshot against the IR specification.

{VLM_EVALUATION_CHECKLIST}

{history_context}

## Deck Context
Title: {vlm_view['deck'].get('title', 'N/A')}
Theme: {vlm_view['deck']['theme'].get('name', 'N/A')}
Primary Color: {vlm_view['deck']['theme'].get('primary_color', 'N/A')}
Background: {vlm_view['deck']['theme'].get('background_color', 'N/A')}
Density: {vlm_view['deck']['theme'].get('density', 'N/A')}

Style Guardrails:
{chr(10).join(f"- {g}" for g in vlm_view['deck']['theme'].get('style_guardrails', []))}

## Slide IR Specification
Slide ID: {vlm_view['slide'].get('slide_id', 'N/A')}
Title: {vlm_view['slide'].get('title', 'N/A')}
Core Message: {vlm_view['slide'].get('core_message', 'N/A')}

Layout: {vlm_view['slide']['layout'].get('name', 'N/A')} (density: {vlm_view['slide']['layout'].get('density', 'N/A')}, emphasis: {vlm_view['slide']['layout'].get('emphasis', 'N/A')})

Content Blocks:
{json.dumps(vlm_view['slide'].get('blocks', []), ensure_ascii=False, indent=2)[:800]}

Source Evidence (must be grounded):
{json.dumps(vlm_view['slide'].get('source_evidence', []), ensure_ascii=False, indent=2)[:600]}

---

**Output JSON**:
{{
  "score": <float 0-10>,
  "dimension_scores": {{
    "structure": <0-3>,
    "visual_design": <0-2>,
    "image_integration": <0-2>,
    "information_expression": <0-2>,
    "consistency": <0-0.5>,
    "content_alignment": <0-0.5>
  }},
  "feedback": "<Specific, actionable feedback for IR modification. Focus on what needs to change in the IR (layout, blocks, visuals), not code-level fixes. Prioritize structure issues (alignment, spacing, overlap).>",
  "strengths": ["<strength 1>", "<strength 2>"]
}}

**Important**:
- Feedback should be IR-level (e.g., "Increase title slot height ratio from 0.12 to 0.15"), not code-level
- Be specific about which IR fields need adjustment
- If iteration > 0, note whether previous issues were resolved
"""

    return prompt
