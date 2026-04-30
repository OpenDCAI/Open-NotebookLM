"""Two-stage LLM slide planner."""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import md5
from typing import Any, Dict, Iterable

from ..llm.client import LLMClient
from .ir_schema import (
    AcquisitionPlan,
    ContentBlock,
    DeckIR,
    IRMetadata,
    DeckTheme,
    LongDocProfile,
    LayoutSlot,
    LayoutSpec,
    MaterialCandidate,
    MaterialRequest,
    SourceEvidence,
    SlideBriefDeck,
    SlideBlueprint,
    SlideIR,
    StorySection,
    Storyline,
    VisualBinding,
)


AUTO_SPLIT_TARGET_THRESHOLD = 9


class SlidePlanner:
    ALLOWED_LAYOUTS = [
        "hero",
        "title_only",
        "section_divider",
        "two_column",
        "three_column",
        "comparison",
        "metric_focus",
        "timeline",
        "process_flow",
        "quadrant",
        "image_focus",
        "quote_callout",
        "table_focus",
        "chart_focus",
        "closing",
    ]
    ALLOWED_BLOCK_KINDS = [
        "headline",
        "summary",
        "bullet_list",
        "metric_strip",
        "process",
        "comparison",
        "quote",
        "callout",
    ]
    ALLOWED_SLOT_ROLES = [
        "title",
        "subtitle",
        "body",
        "supporting_body",
        "hero_visual",
        "supporting_visual",
        "metrics",
        "callout",
        "footer",
    ]
    ALLOWED_VISUAL_TYPES = [
        "figure",
        "diagram",
        "chart",
        "icon_cluster",
        "photo",
        "interface",
        "table",
        "text_only",
    ]

    def __init__(
        self,
        client: LLMClient,
        *,
        max_workers: int = 4,
        language_mode: str = "english",
        complexity_level: str = "balanced",
        slide_ir_strategy: str = "auto",
        target_slide_count: int | None = None,
        auto_split_threshold: int = AUTO_SPLIT_TARGET_THRESHOLD,
    ):
        self.client = client
        self.max_workers = max_workers
        self.language_mode = language_mode.lower()
        self.complexity_level = complexity_level.lower()
        self.slide_ir_strategy = str(slide_ir_strategy or "auto").strip().lower()
        self.target_slide_count = target_slide_count if target_slide_count and target_slide_count > 0 else None
        self.auto_split_threshold = max(int(auto_split_threshold or AUTO_SPLIT_TARGET_THRESHOLD), 1)

    def plan_deck(
        self,
        markdown: str,
        materials: Dict[str, Any],
        slide_briefs: Dict[str, Any] | None = None,
        progress_callback=None,
        slide_callback=None,
        existing_slides: Dict[str, Dict[str, Any]] | None = None,
        existing_deck_stage: Dict[str, Any] | None = None,
        deck_stage_callback=None,
    ) -> Dict[str, Any]:
        """Generate deck IR, optionally grounding on deck-scoped slide_briefs.

        Note: materials parameter is kept for compatibility but planner should not
        access materials.assets to ensure fair material selection in step3.
        """
        # Pass empty materials dict to avoid planner seeing available assets
        if existing_deck_stage is not None:
            deck_stage = existing_deck_stage
        else:
            deck_stage = self.plan_deck_structure(markdown, {}, slide_briefs=slide_briefs)
            if deck_stage_callback is not None:
                deck_stage_callback(deck_stage)
        deck_id = self._build_deck_id(deck_stage["title"], markdown)
        brief_map = self._build_slide_brief_map(slide_briefs or {})
        existing_slides = existing_slides or {}
        total_slides = len(deck_stage["deck_outline"])
        normalized_slides: dict[int, dict[str, Any]] = {}
        material_requests_by_index: dict[int, list[dict[str, Any]]] = {}

        def store_slide(index: int, blueprint: dict[str, Any], slide_stage: dict[str, Any], reused: bool = False) -> None:
            raw_requests = slide_stage.get("material_requests", [])
            slide_requests = self._normalize_material_requests(raw_requests)
            slide = self._normalize_slide(
                slide=slide_stage,
                index=index + 1,
                deck_id=deck_id,
                asset_index=deck_stage["source_asset_index"],
                request_ids={request["request_id"] for request in slide_requests},
                blueprint=blueprint,
            )
            normalized_slides[index] = slide
            material_requests_by_index[index] = slide_requests
            if slide_callback is not None:
                slide_callback(slide, slide_requests, index + 1, total_slides)
            if progress_callback is not None and reused:
                progress_callback(len(normalized_slides), total_slides, f"{slide.get('slide_id', blueprint.get('slide_id', 'slide'))} reuse")

        pending_blueprints: list[tuple[int, dict[str, Any]]] = []
        for index, blueprint in enumerate(deck_stage["deck_outline"]):
            existing_slide = existing_slides.get(blueprint.get("slide_id", ""))
            if existing_slide is not None:
                store_slide(index, blueprint, existing_slide, reused=True)
            else:
                pending_blueprints.append((index, blueprint))

        if pending_blueprints:
            max_workers = min(max(self.max_workers, 1), len(pending_blueprints))
            if max_workers <= 1:
                for index, blueprint in pending_blueprints:
                    slide_stage = self.plan_slide(
                        deck_stage,
                        blueprint,
                        slide_brief=self._lookup_brief_for_blueprint(brief_map, blueprint),
                    )
                    store_slide(index, blueprint, slide_stage, reused=False)
                    if progress_callback is not None:
                        progress_callback(len(normalized_slides), total_slides, blueprint.get("slide_id", f"slide_{index + 1:02d}"))
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_map = {
                        executor.submit(
                            self.plan_slide,
                            deck_stage,
                            blueprint,
                            self._lookup_brief_for_blueprint(brief_map, blueprint),
                        ): (index, blueprint)
                        for index, blueprint in pending_blueprints
                    }
                    for future in as_completed(future_map):
                        index, blueprint = future_map[future]
                        slide_stage = future.result()
                        store_slide(index, blueprint, slide_stage, reused=False)
                        if progress_callback is not None:
                            progress_callback(len(normalized_slides), total_slides, blueprint.get("slide_id", f"slide_{index + 1:02d}"))

        slides = [normalized_slides[index] for index in range(total_slides) if index in normalized_slides]
        material_requests: list[dict[str, Any]] = []
        for index in range(total_slides):
            material_requests.extend(material_requests_by_index.get(index, []))

        slide_manifest = [
            {
                "slide_id": slide["slide_id"],
                "slide_number": slide["slide_number"],
                "title": slide["title"],
                "type": slide["type"],
                "layout_name": slide["layout"]["name"],
            }
            for slide in slides
        ]
        deck_data = {
            "metadata": self._model_dump(
                IRMetadata(schema_name="presentagent.deck_ir", deck_id=deck_id, stage="planned")
            ),
            "title": deck_stage["title"],
            "subtitle": deck_stage.get("subtitle", ""),
            "storyline": deck_stage["storyline"],
            "theme": deck_stage["theme"],
            "longdoc_profile": deck_stage.get("longdoc_profile", {}),
            "deck_outline": deck_stage["deck_outline"],
            "material_requests": material_requests,
            "slides": slides,
            "slide_manifest": slide_manifest,
            "planner_notes": deck_stage.get("planner_notes", []),
            "source_asset_index": deck_stage["source_asset_index"],
        }
        deck_ir = DeckIR(**deck_data)
        return self._model_dump(deck_ir)

    def plan_deck_structure(
        self,
        markdown: str,
        materials: Dict[str, Any],
        slide_briefs: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        base_prompt = self._build_deck_prompt(markdown, slide_briefs=slide_briefs)
        last_error: Exception | None = None
        for attempt in range(2):
            prompt = base_prompt
            if attempt > 0:
                prompt += "\n\nYour previous output was not valid JSON. Return one strictly valid JSON object with no extra explanation."
            try:
                response = self.client.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.2,
                    response_format="json",
                )
                raw_deck = self._extract_json_with_repair(response, repair_context="deck planning")
                return self._normalize_deck_structure(raw_deck, materials, slide_briefs=slide_briefs)
            except RuntimeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("Deck planning failed without an explicit error.")

    def plan_slide(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        strategy = self._resolve_slide_ir_strategy(deck_stage, slide_brief=slide_brief)
        if strategy == "single":
            return self._plan_slide_single_pass(deck_stage, blueprint, slide_brief=slide_brief)
        return self._plan_slide_split_pass(deck_stage, blueprint, slide_brief=slide_brief)

    def _plan_slide_single_pass(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        prompt = self._build_slide_single_pass_prompt(deck_stage, blueprint, slide_brief=slide_brief)
        last_error: Exception | None = None
        for attempt in range(2):
            candidate_prompt = prompt
            if attempt > 0:
                candidate_prompt += "\n\nYour previous output was not valid JSON. Return one strictly valid JSON object with no extra explanation."
            try:
                response = self.client.chat(
                    [{"role": "user", "content": candidate_prompt}],
                    temperature=0.2,
                    response_format="json",
                )
                if self._model_profile() == "qwen":
                    response = self._repair_qwen_slide_fragment_response(response, blueprint)
                raw_slide = self._extract_json_with_repair(
                    response,
                    repair_context=f"slide planning {blueprint.get('slide_id', '')}",
                )
                slide = self._hydrate_slide_defaults(raw_slide, blueprint)
                if self._model_profile() == "qwen" and self._needs_qwen_visual_followup(slide):
                    visual_plan = self._plan_slide_visuals(deck_stage, blueprint, slide, slide_brief=slide_brief)
                    if visual_plan.get("visuals") or visual_plan.get("material_requests"):
                        slide = self._merge_slide_content_and_visual_plan(
                            slide,
                            visual_plan,
                            deck_stage=deck_stage,
                            blueprint=blueprint,
                        )
                if self._model_profile() != "qwen":
                    self._ensure_visual_plan_fallback(
                        slide,
                        deck_stage=deck_stage,
                        blueprint=blueprint,
                    )
                return slide
            except RuntimeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Slide planning failed for {blueprint.get('slide_id', '')}.")

    def _plan_slide_split_pass(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        content_prompt = self._build_slide_content_prompt(deck_stage, blueprint, slide_brief=slide_brief)
        last_error: Exception | None = None
        for attempt in range(2):
            prompt = content_prompt
            if attempt > 0:
                prompt += "\n\nYour previous output was not valid JSON. Return one strictly valid JSON object with no extra explanation."
            try:
                response = self.client.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.2,
                    response_format="json",
                )
                if self._model_profile() == "qwen":
                    response = self._repair_qwen_slide_fragment_response(response, blueprint)
                raw_slide = self._extract_json_with_repair(
                    response,
                    repair_context=f"slide planning {blueprint.get('slide_id', '')}",
                )
                content_slide = self._hydrate_slide_defaults(raw_slide, blueprint)
                visual_plan = self._plan_slide_visuals(deck_stage, blueprint, content_slide, slide_brief=slide_brief)
                merged_slide = self._merge_slide_content_and_visual_plan(
                    content_slide,
                    visual_plan,
                    deck_stage=deck_stage,
                    blueprint=blueprint,
                )
                return merged_slide
            except RuntimeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Slide planning failed for {blueprint.get('slide_id', '')}.")

    def _resolve_slide_ir_strategy(
        self,
        deck_stage: Dict[str, Any] | None = None,
        *,
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        if self.slide_ir_strategy in {"single", "split"}:
            return self.slide_ir_strategy
        target_slide_count = self._resolve_target_slide_count(deck_stage, slide_brief=slide_brief)
        if target_slide_count is not None and target_slide_count <= self.auto_split_threshold:
            return "single"
        return "split"

    def _resolve_target_slide_count(
        self,
        deck_stage: Dict[str, Any] | None = None,
        *,
        slide_brief: Dict[str, Any] | None = None,
    ) -> int | None:
        for candidate in (
            self.target_slide_count,
            (deck_stage or {}).get("longdoc_profile", {}).get("target_slide_count"),
            (slide_brief or {}).get("target_slide_count"),
        ):
            try:
                value = int(candidate or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return None

    @staticmethod
    def _hydrate_slide_defaults(raw_slide: Dict[str, Any], blueprint: Dict[str, Any]) -> Dict[str, Any]:
        slide = dict(raw_slide)
        slide.setdefault("slide_id", blueprint["slide_id"])
        slide.setdefault("type", blueprint["type"])
        slide.setdefault("section_id", blueprint["section_id"])
        slide.setdefault("section_title", blueprint.get("section_title", ""))
        slide.setdefault("title", blueprint["title"])
        slide.setdefault("core_message", blueprint["core_message"])
        slide.setdefault("objective", blueprint.get("objective", ""))
        slide.setdefault("brief_id", blueprint.get("brief_id", ""))
        slide.setdefault("source_chunk_ids", blueprint.get("source_chunk_ids", []))
        return slide

    def _build_deck_prompt(
        self,
        markdown: str,
        slide_briefs: Dict[str, Any] | None = None,
    ) -> str:
        slide_briefs = slide_briefs or {}
        brief_payload = {
            "title_hint": slide_briefs.get("title_hint", ""),
            "subtitle_hint": slide_briefs.get("subtitle_hint", ""),
            "storyline_hint": slide_briefs.get("storyline_hint", {}),
            "longdoc_profile": slide_briefs.get("longdoc_profile", {}),
            "planner_notes": slide_briefs.get("planner_notes", []),
            "slide_briefs": slide_briefs.get("slide_briefs", []),
        }

        language_instruction = self._get_language_instruction()
        complexity_instruction = self._get_complexity_instruction()
        target_slide_count = int((slide_briefs.get("longdoc_profile") or {}).get("target_slide_count") or 0)
        if target_slide_count > 0:
            slide_cap_instruction_cn = f"7. 将 `deck_outline` 视为硬性页数上限，总页数不得超过 {target_slide_count} 张；如有冗余内容必须合并。"
            slide_cap_instruction_en = f"7. Treat `deck_outline` as a hard slide cap: do not exceed {target_slide_count} slides; merge redundant material when needed."
        else:
            slide_cap_instruction_cn = ""
            slide_cap_instruction_en = ""

        if self.language_mode == "chinese" and slide_briefs.get("slide_briefs"):
            return f"""你是一位顶级演示文稿总监。你的任务是生成正式的 Deck IR。不要重新进行长文档分解。

任务：
1. 输入已包含演示文稿级的 `slide_briefs` 中间层。
2. 将这些摘要转换为正式的演示文稿级 IR：`title`、`subtitle`、`storyline`、`theme` 和 `deck_outline`。
3. `deck_outline` 是每张幻灯片的蓝图，而非完整的幻灯片 IR。
4. 不要在此生成 `material_requests`。那属于每张幻灯片的 IR 生成。
5. 尽可能保留每个摘要的核心结论、章节结构和推荐布局。
6. 仅使用允许的布局标签。不要创造新的布局名称。
{slide_cap_instruction_cn}
{language_instruction}
{complexity_instruction}

slide_briefs:
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:9000]}

仅返回 JSON，格式如下：
{{
  "title": "演示文稿标题",
  "subtitle": "演示文稿副标题",
  "storyline": {{
    "topic": "主题",
    "audience": "受众",
    "presentation_goal": "演示目标",
    "tone": "语气",
    "sections": [
      {{"id": "section_01", "title": "章节名称", "objective": "章节目标"}}
    ]
  }},
  "theme": {{
    "name": "视觉风格名称",
    "primary_color": "#134E8E",
    "secondary_color": "#C00707",
    "accent_color": "#FFB33F",
    "background_color": "#F7F4EE",
    "text_color": "#1F2937",
    "font_family": "Aptos",
    "density": "balanced",
    "style_guardrails": ["设计准则 1", "设计准则 2"]
  }},
  "deck_outline": [
    {{
      "slide_id": "slide_01",
      "brief_id": "brief_01",
      "type": "title",
      "section_id": "section_01",
      "section_title": "开场",
      "title": "幻灯片标题",
      "core_message": "这张幻灯片的核心结论",
      "objective": "幻灯片目标",
      "visual_intent": "幻灯片所需的视觉感觉和视觉对象",
      "recommended_layouts": ["hero", "image_focus"],
      "source_chunk_ids": ["chunk_01"],
      "source_headings": ["引言"],
      "source_excerpt": "支持这张幻灯片的源摘录"
    }}
  ],
  "planner_notes": ["全局叙事或设计备注"]
}}"""

        if slide_briefs.get("slide_briefs"):
            return f"""You are a top-tier presentation director. Your task here is to produce the formal Deck IR only. Do not redo long-document decomposition.

Tasks:
1. The input already includes the deck-level `slide_briefs` intermediate layer.
2. Convert those briefs into a formal deck-level IR: `title`, `subtitle`, `storyline`, `theme`, and `deck_outline`.
3. `deck_outline` is a per-slide blueprint, not full slide IR.
4. Do not generate `material_requests` here. That belongs to per-slide slide IR generation.
5. Preserve each brief's core conclusion, section structure, and recommended layouts as much as possible.
6. Use only the allowed layout labels. Do not invent new layout names.
{slide_cap_instruction_en}
{language_instruction}
{complexity_instruction}

slide_briefs:
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:9000]}

Return JSON only, in this format:
{{
  "title": "Deck title",
  "subtitle": "Deck subtitle",
  "storyline": {{
    "topic": "Topic",
    "audience": "Audience",
    "presentation_goal": "Presentation goal",
    "tone": "Tone",
    "sections": [
      {{"id": "section_01", "title": "Section name", "objective": "Section objective"}}
    ]
  }},
  "theme": {{
    "name": "Visual style name",
    "primary_color": "#134E8E",
    "secondary_color": "#C00707",
    "accent_color": "#FFB33F",
    "background_color": "#F7F4EE",
    "text_color": "#1F2937",
    "font_family": "Aptos",
    "density": "balanced",
    "style_guardrails": ["Guardrail 1", "Guardrail 2"]
  }},
  "deck_outline": [
    {{
      "slide_id": "slide_01",
      "brief_id": "brief_01",
      "type": "title",
      "section_id": "section_01",
      "section_title": "Opening",
      "title": "Slide title",
      "core_message": "The one core conclusion of this slide",
      "objective": "Slide objective",
      "visual_intent": "Desired visual feel and visual objects for the slide",
      "recommended_layouts": ["hero", "image_focus"],
      "source_chunk_ids": ["chunk_01"],
      "source_headings": ["Introduction"],
      "source_excerpt": "Source excerpt supporting this slide"
    }}
  ],
  "planner_notes": ["Global storytelling or design note"]
}}"""

        return f"""You are a top-tier presentation director. Start with deck-level planning rather than generating slide content directly.

Tasks:
1. Output deck IR only, not full slide IR.
2. Decide the topic, audience, presentation goal, section structure, slide count, slide type, slide title, single core message per slide, and overall visual direction.
3. Every slide must have exactly one `core_message`.
4. The deck IR should generalize to any topic, not just a fixed paper template.
{language_instruction}
{complexity_instruction}

Input content:
{markdown[:5500]}

Return JSON only, in this format:
{{
  "title": "Deck title",
  "subtitle": "Deck subtitle",
  "storyline": {{
    "topic": "Topic",
    "audience": "Audience",
    "presentation_goal": "Presentation goal",
    "tone": "Tone",
    "sections": [
      {{"id": "section_01", "title": "Section name", "objective": "Section objective"}}
    ]
  }},
  "theme": {{
    "name": "Visual style name",
    "primary_color": "#134E8E",
    "secondary_color": "#C00707",
    "accent_color": "#FFB33F",
    "background_color": "#F7F4EE",
    "text_color": "#1F2937",
    "font_family": "Aptos",
    "density": "balanced",
    "style_guardrails": ["Guardrail 1", "Guardrail 2"]
  }},
  "deck_outline": [
    {{
      "slide_id": "slide_01",
      "type": "title",
      "section_id": "section_01",
      "section_title": "Opening",
      "title": "Slide title",
      "core_message": "The one core conclusion of this slide",
      "objective": "Slide objective"
    }}
  ],
  "planner_notes": ["Global storytelling or design note"]
}}

Allowed layout candidates:
{", ".join(self.ALLOWED_LAYOUTS)}
"""

    def _build_qwen_slide_single_pass_prompt(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        brief_payload = slide_brief or {}
        language_rule = "所有自然语言字段必须使用中文。" if self.language_mode == "chinese" else "All natural-language fields must be in English."
        complexity_rule = self._get_complexity_instruction()
        return f"""你是 PresentAgent 的 Qwen slide IR planner。只返回一个完整 JSON 对象，不要继续示例，不要输出片段。

硬性格式：
- 第一个字符必须是 {{，最后一个字符必须是 }}。
- 顶层第一个字段必须是 "slide_id"。
- 必须包含这些顶层字段：
  slide_id,type,section_id,section_title,title,subtitle,core_message,objective,brief_id,source_chunk_ids,source_evidence,layout,blocks,points,visuals,material_requests,design_notes,speaker_notes
- 不要把 source_evidence 内部对象、visuals 内部对象或 material_requests 内部对象当作顶层输出。
- 只输出 JSON，无 markdown，无解释。

当前 slide blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

当前 slide_brief:
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:2200]}

Deck theme:
{json.dumps(deck_stage.get("theme", {}), ensure_ascii=False, indent=2)[:1200]}

生成规则：
1. layout 使用语义 slot，并至少包含 title/body；如果需要图片或图示，加入 supporting_visual 或 hero_visual slot。
2. blocks 必须使用 canonical 字段：block_id, kind, label, slot_id, content, items。不要用 type 代替 kind。
3. source_evidence 必须使用 canonical 字段：evidence_id, source_chunk_ids, source_headings, source_excerpt, rationale。
4. visuals 必须使用 canonical 字段：slot_id, asset_role, target_area, intent, use_request_id。
5. material_requests 必须使用 canonical 字段：request_id, asset_type, title, caption, purpose, target_slide_id, preferred_layout_slot。不要用 type 或 description 代替 asset_type/caption/purpose。
6. Step2 不做素材匹配，不要输出任何已有素材绑定字段。若需要图片、概念图、图表或示意图，必须输出 use_request_id，并生成匹配的 material_requests[0].request_id。
7. material_requests 是给 Step3 统一补齐素材用的；不要因为没有现有素材而返回空。
8. layout 中的 x_ratio/y_ratio/w_ratio/h_ratio 是 0-1 相对值，不是 EMU 或像素。
9. {complexity_rule}
{language_rule}

返回完整 JSON 对象。"""

    def _build_qwen_slide_content_prompt(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        brief_payload = slide_brief or {}
        language_rule = "所有自然语言字段必须使用中文。" if self.language_mode == "chinese" else "All natural-language fields must be in English."
        complexity_rule = self._get_complexity_instruction()
        return f"""你是 PresentAgent 的 Qwen slide content planner。只返回一个完整 JSON 对象，不要输出片段。

硬性格式：
- 第一个字符必须是 {{，最后一个字符必须是 }}。
- 顶层第一个字段必须是 "slide_id"。
- 必须包含这些顶层字段：
  slide_id,type,section_id,section_title,title,subtitle,core_message,objective,brief_id,source_chunk_ids,source_evidence,layout,blocks,points,design_notes,speaker_notes
- 本轮不要输出 visuals 或 material_requests；视觉规划会单独补齐。
- 只输出 JSON，无 markdown，无解释。

当前 slide blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

当前 slide_brief:
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:2200]}

Deck theme:
{json.dumps(deck_stage.get("theme", {}), ensure_ascii=False, indent=2)[:1200]}

生成规则：
1. layout 使用语义 slot，并至少包含 title/body；若本页需要图片或图示，必须预留 supporting_visual 或 hero_visual slot。
2. blocks 必须使用 canonical 字段：block_id, kind, label, slot_id, content, items。不要用 type 代替 kind。
3. source_evidence 必须使用 canonical 字段：evidence_id, source_chunk_ids, source_headings, source_excerpt, rationale。
4. points 根据复杂度给出短要点；qwen simple/balanced 通常 2-5 个，qwen true complex 可到 5-6 个。
5. layout 中的 x_ratio/y_ratio/w_ratio/h_ratio 是 0-1 相对值，不是 EMU 或像素。
6. {complexity_rule}
{language_rule}

返回完整 JSON 对象。"""

    def _build_qwen_slide_visual_prompt(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        content_slide: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        visual_slots = [
            slot
            for slot in (content_slide.get("layout", {}).get("slots", []) or [])
            if self._is_explicit_visual_slot(slot)
        ]
        preferred_slot = visual_slots[0].get("slot_id", "supporting_visual") if visual_slots else "supporting_visual"
        language_rule = "所有自然语言字段必须使用中文。" if self.language_mode == "chinese" else "All natural-language fields must be in English."
        return f"""你是 PresentAgent 的 Qwen visual/material planner。只返回一个完整 JSON 对象。

硬性格式：
- 第一个字符必须是 {{，最后一个字符必须是 }}。
- 顶层只能有两个字段："visuals" 和 "material_requests"。
- 顶层第一个字段必须是 "visuals"；不要从 visuals 数组内部对象开始输出。
- 只输出 JSON，无 markdown，无解释。

当前 slide blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

当前 content slide:
{json.dumps(content_slide, ensure_ascii=False, indent=2)[:4200]}

生成规则：
1. 如果 content slide 没有视觉 slot，返回 {{"visuals":[],"material_requests":[]}}。
2. Step2 不做素材匹配，不要输出任何已有素材绑定字段。需要视觉时，visuals[*] 必须使用 canonical 字段：slot_id, asset_role, target_area, intent, use_request_id。
3. material_requests[*] 必须使用 canonical 字段：request_id, asset_type, title, caption, purpose, target_slide_id, preferred_layout_slot。不要用 type 或 description 代替 asset_type/caption/purpose。
4. 只要需要图片、概念图、图表或示意图，就生成一个 material_requests，并在 visuals[0].use_request_id 使用相同 request_id。
5. material_requests 是给 Step3 统一补齐素材用的；不要做素材匹配。
6. preferred_layout_slot 使用 "{preferred_slot}"，target_slide_id 使用 "{blueprint.get("slide_id", "slide_01")}"。
7. 视觉描述要足够具体，便于后续检索或生成图片。
{language_rule}

返回完整 JSON 对象。"""

    def _build_slide_content_prompt(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        if self._model_profile() == "qwen":
            return self._build_qwen_slide_content_prompt(deck_stage, blueprint, slide_brief=slide_brief)

        deck_constraints = {
            "title": deck_stage["title"],
            "subtitle": deck_stage.get("subtitle", ""),
            "storyline": deck_stage["storyline"],
            "theme": deck_stage["theme"],
            "planner_notes": deck_stage.get("planner_notes", []),
            "deck_outline": deck_stage["deck_outline"],
        }
        brief_payload = slide_brief or {}
        brief_excerpt = brief_payload.get("source_excerpt", "")
        if not brief_excerpt and brief_payload.get("source_chunk_ids"):
            brief_excerpt = "\n".join(brief_payload.get("content_points", []))

        language_instruction = self._get_language_instruction()
        complexity_instruction = self._get_complexity_instruction()

        if self.language_mode == "chinese":
            return f"""你是一位顶级演示文稿幻灯片规划师。

**关键要求：你的输出必须是有效的 JSON，使用英文双引号 (") 而不是中文引号。**

为恰好一张幻灯片生成幻灯片 IR。

你必须遵循 Deck IR 约束：
{json.dumps(deck_constraints, ensure_ascii=False, indent=2)[:4500]}

当前幻灯片蓝图：
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

当前幻灯片摘要：
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:2500]}

此幻灯片最相关的支持摘录：
{brief_excerpt[:1800]}

要求：

## 布局设计（自然语言）
1. `layout.name`：自然地描述布局概念。使用标准名称如 "hero"、"two_column"、"comparison" 或创建描述性名称如 "left_text_right_visual"、"metric_dashboard"。编码人员将解释你的意图。
2. `layout.slots[*].slot_role`：描述语义目的如 "title"、"body"、"hero_visual"、"supporting_visual"、"metrics"、"callout"。清楚地说明内容放在哪里。
3. `blocks[*].kind`：描述内容类型如 "headline"、"bullet_list"、"metric_strip"、"process"、"comparison"、"quote"。选择最能传达信息的类型。

## 内容块
4. 完整指定 `layout`、`blocks`、`design_notes` 和 `speaker_notes`。
5. 对于流程/因果关系/架构/方法步骤，优先使用结构化块：`process`、`comparison`、`metric_strip`。
6. `points`：包含 2-5 个简洁的要点（兼容层用于回退渲染）。

## 视觉规划
7. 本轮不要生成 `visuals` 或 `material_requests`。视觉与素材规划会在下一轮单独完成。
8. 但你必须在 `layout.slots` 中清楚保留需要视觉的槽位，例如 `supporting_visual`、`hero_visual`、`metrics` 等。

## 输出约束
11. 仅输出此幻灯片的内容骨架 IR。无 Deck 级字段。
12. `layout` 指定相对区域/插槽，不是精确像素坐标（编码人员处理）。
13. 包含 `source_evidence`，其中包含 `source_chunk_ids`、`source_headings`、`source_excerpt` 和将幻灯片链接到源的理由。
{language_instruction}

**输出必须是有效的 JSON，所有字符串值使用英文双引号 (")。**

输出 JSON：
{{
  "slide_id": "{blueprint["slide_id"]}",
  "type": "{blueprint["type"]}",
  "section_id": "{blueprint["section_id"]}",
  "section_title": "{blueprint.get("section_title", "")}",
  "title": "{blueprint["title"]}",
  "subtitle": "可选副标题",
  "core_message": "{blueprint["core_message"]}",
  "objective": "{blueprint.get("objective", "")}",
  "brief_id": "{blueprint.get("brief_id", "")}",
  "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
  "source_evidence": [
    {{
      "evidence_id": "{blueprint["slide_id"]}_evidence_01",
      "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
      "source_headings": {json.dumps(blueprint.get("source_headings", []), ensure_ascii=False)},
      "source_excerpt": {json.dumps(blueprint.get("source_excerpt", ""), ensure_ascii=False)},
      "rationale": "解释幻灯片结论如何得到源摘录的支持"
    }}
  ],
  "layout": {{
    "name": "two_column",
    "variant": "default",
    "rationale": "为什么这个布局合适",
    "grid": "12-column",
    "emphasis": "headline",
    "density": "balanced",
    "vary_from_previous": true,
    "render_policy": "semantic_slots",
    "slots": [
      {{
        "slot_id": "body",
        "slot_role": "body",
        "anchor": "left",
        "x_ratio": 0.06,
        "y_ratio": 0.23,
        "w_ratio": 0.42,
        "h_ratio": 0.62,
        "content_types": ["summary", "bullet_list"]
      }}
    ]
  }},
  "blocks": [
    {{"block_id": "{blueprint["slide_id"]}_block_01", "kind": "summary", "label": "summary", "slot_id": "body", "content": "单句摘要", "items": []}},
    {{"block_id": "{blueprint["slide_id"]}_block_02", "kind": "bullet_list", "label": "key_points", "slot_id": "body", "content": "", "items": ["要点 1", "要点 2"]}}
  ],
  "points": ["要点 1", "要点 2"],
  "design_notes": ["设计备注"],
  "speaker_notes": "演讲者提示"
}}

注意：你有完全的创意自由。编码人员将解释你的设计意图并用 python-pptx 代码实现它。
"""

        return f"""You are a top-tier presentation slide planner. Generate slide IR for exactly one slide.

You must follow the deck IR constraints:
{json.dumps(deck_constraints, ensure_ascii=False, indent=2)[:4500]}

Current slide blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

Current slide_brief:
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:2500]}

Most relevant supporting excerpt for this slide:
{brief_excerpt[:1800]}

Requirements:

## Layout Design (Natural Language)
1. `layout.name`: Describe the layout concept naturally. Use standard names like "hero", "two_column", "comparison" OR create descriptive names like "left_text_right_visual", "metric_dashboard". The coder will interpret your intent.
2. `layout.slots[*].slot_role`: Describe semantic purpose like "title", "body", "hero_visual", "supporting_visual", "metrics", "callout". Be clear about what content goes where.
3. `blocks[*].kind`: Describe content type like "headline", "bullet_list", "metric_strip", "process", "comparison", "quote". Choose what best communicates the message.

## Content Blocks
4. Fully specify `layout`, `blocks`, `design_notes`, and `speaker_notes`.
5. For process/causality/architecture/method steps, prefer structured blocks: `process`, `comparison`, `metric_strip`.
6. `points`: Include 2-5 concise bullet points (compatibility layer for fallback rendering).

## Visual Planning
7. In this pass, do NOT generate `visuals` or `material_requests`. Visual/material planning will be handled in a separate follow-up pass.
8. You must still preserve visual intent by keeping appropriate semantic slots in `layout.slots`, such as `supporting_visual`, `hero_visual`, or `metrics`.

## Output Constraints
11. Output only THIS slide's content skeleton IR. No deck-level fields.
12. `layout` specifies relative regions/slots, NOT exact pixel coordinates (coder handles that).
13. Include `source_evidence` with `source_chunk_ids`, `source_headings`, `source_excerpt`, and rationale linking slide to source.
14. All natural-language fields must be in English.

**Important: JSON Format Requirements**
- All string values must use English double quotes (") not Chinese quotes (" or ")
- Do not use multiple consecutive double quotes in JSON
- Ensure output is valid JSON that can be parsed directly with json.loads()

Output JSON:
{{
  "slide_id": "{blueprint["slide_id"]}",
  "type": "{blueprint["type"]}",
  "section_id": "{blueprint["section_id"]}",
  "section_title": "{blueprint.get("section_title", "")}",
  "title": "{blueprint["title"]}",
  "subtitle": "Optional subtitle",
  "core_message": "{blueprint["core_message"]}",
  "objective": "{blueprint.get("objective", "")}",
  "brief_id": "{blueprint.get("brief_id", "")}",
  "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
  "source_evidence": [
    {{
      "evidence_id": "{blueprint["slide_id"]}_evidence_01",
      "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
      "source_headings": {json.dumps(blueprint.get("source_headings", []), ensure_ascii=False)},
      "source_excerpt": {json.dumps(blueprint.get("source_excerpt", ""), ensure_ascii=False)},
      "rationale": "Explain how the slide conclusion is supported by the source excerpt"
    }}
  ],
  "layout": {{
    "name": "two_column",
    "variant": "default",
    "rationale": "Why this layout is appropriate",
    "grid": "12-column",
    "emphasis": "headline",
    "density": "balanced",
    "vary_from_previous": true,
    "render_policy": "semantic_slots",
    "slots": [
      {{
        "slot_id": "body",
        "slot_role": "body",
        "anchor": "left",
        "x_ratio": 0.06,
        "y_ratio": 0.23,
        "w_ratio": 0.42,
        "h_ratio": 0.62,
        "content_types": ["summary", "bullet_list"]
      }}
    ]
  }},
  "blocks": [
    {{"block_id": "{blueprint["slide_id"]}_block_01", "kind": "summary", "label": "summary", "slot_id": "body", "content": "One-sentence summary", "items": []}},
    {{"block_id": "{blueprint["slide_id"]}_block_02", "kind": "bullet_list", "label": "key_points", "slot_id": "body", "content": "", "items": ["Point 1", "Point 2"]}}
  ],
  "points": ["Point 1", "Point 2"],
  "design_notes": ["Design note"],
  "speaker_notes": "Presenter cue"
}}

Note: You have full creative freedom. The coder will interpret your design intent and implement it with python-pptx code.
"""

    def _build_slide_single_pass_prompt(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        if self._model_profile() == "qwen":
            return self._build_qwen_slide_single_pass_prompt(deck_stage, blueprint, slide_brief=slide_brief)

        deck_constraints = {
            "title": deck_stage["title"],
            "subtitle": deck_stage.get("subtitle", ""),
            "storyline": deck_stage["storyline"],
            "theme": deck_stage["theme"],
            "planner_notes": deck_stage.get("planner_notes", []),
            "deck_outline": deck_stage["deck_outline"],
        }
        brief_payload = slide_brief or {}
        brief_excerpt = brief_payload.get("source_excerpt", "")
        if not brief_excerpt and brief_payload.get("source_chunk_ids"):
            brief_excerpt = "\n".join(brief_payload.get("content_points", []))

        language_instruction = self._get_language_instruction()
        complexity_instruction = self._get_complexity_instruction()

        if self.language_mode == "chinese":
            return f"""你是一位顶级演示文稿幻灯片规划师。

**关键要求：你的输出必须是有效的 JSON，使用英文双引号 (")。**

为恰好一张幻灯片一次性生成完整 slide IR，包括内容骨架、视觉绑定和素材请求。

你必须遵循 Deck IR 约束：
{json.dumps(deck_constraints, ensure_ascii=False, indent=2)[:4500]}

当前幻灯片蓝图：
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

当前幻灯片摘要：
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:2500]}

此幻灯片最相关的支持摘录：
{brief_excerpt[:1800]}

要求：
1. 完整输出 `layout`、`blocks`、`design_notes`、`speaker_notes`、`visuals`、`material_requests`。
2. 如果布局需要视觉，优先复用现有 self 素材；若无法明确复用，再生成最少量的 `material_requests`。
3. `layout.slots[*].slot_role` 要清楚表达语义，如 `title`、`body`、`supporting_visual`、`hero_visual`、`metrics`、`callout`。
4. 对流程/因果/架构/方法步骤，优先使用结构化块：`process`、`comparison`、`metric_strip`。
5. `points` 根据复杂度包含简洁要点；qwen simple/balanced 通常 2-5 个，qwen true complex 可到 5-6 个，兼容回退渲染。
6. `layout` 只描述相对区域，不写像素坐标。
7. 包含 `source_evidence`，说明该页如何由源内容支撑。
{language_instruction}
{complexity_instruction}

输出 JSON：
{{
  "slide_id": "{blueprint["slide_id"]}",
  "type": "{blueprint["type"]}",
  "section_id": "{blueprint["section_id"]}",
  "section_title": "{blueprint.get("section_title", "")}",
  "title": "{blueprint["title"]}",
  "subtitle": "可选副标题",
  "core_message": "{blueprint["core_message"]}",
  "objective": "{blueprint.get("objective", "")}",
  "brief_id": "{blueprint.get("brief_id", "")}",
  "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
  "source_evidence": [
    {{
      "evidence_id": "{blueprint["slide_id"]}_evidence_01",
      "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
      "source_headings": {json.dumps(blueprint.get("source_headings", []), ensure_ascii=False)},
      "source_excerpt": {json.dumps(blueprint.get("source_excerpt", ""), ensure_ascii=False)},
      "rationale": "解释幻灯片结论如何得到源摘录的支持"
    }}
  ],
  "layout": {{
    "name": "two_column",
    "variant": "default",
    "rationale": "为什么这个布局合适",
    "grid": "12-column",
    "emphasis": "headline",
    "density": "balanced",
    "vary_from_previous": true,
    "render_policy": "semantic_slots",
    "slots": [
      {{
        "slot_id": "body",
        "slot_role": "body",
        "anchor": "left",
        "x_ratio": 0.06,
        "y_ratio": 0.23,
        "w_ratio": 0.42,
        "h_ratio": 0.62,
        "content_types": ["summary", "bullet_list"]
      }},
      {{
        "slot_id": "supporting_visual",
        "slot_role": "supporting_visual",
        "anchor": "right",
        "x_ratio": 0.54,
        "y_ratio": 0.23,
        "w_ratio": 0.38,
        "h_ratio": 0.56,
        "content_types": ["image", "chart", "table"]
      }}
    ]
  }},
  "blocks": [
    {{"block_id": "{blueprint["slide_id"]}_block_01", "kind": "summary", "label": "summary", "slot_id": "body", "content": "单句摘要", "items": []}},
    {{"block_id": "{blueprint["slide_id"]}_block_02", "kind": "bullet_list", "label": "key_points", "slot_id": "body", "content": "", "items": ["要点 1", "要点 2"]}}
  ],
  "points": ["要点 1", "要点 2"],
  "visuals": [
    {{
      "slot_id": "supporting_visual",
      "asset_role": "supporting_visual",
      "target_area": "right",
      "intent": "视觉意图",
      "use_existing_asset_id": "self:0.jpg"
    }}
  ],
  "material_requests": [
    {{
      "request_id": "{blueprint["slide_id"]}_image_01",
      "asset_type": "image",
      "title": "素材标题",
      "caption": "图像描述",
      "purpose": "此图像服务的沟通目的",
      "target_slide_id": "{blueprint["slide_id"]}",
      "preferred_layout_slot": "supporting_visual"
    }}
  ],
  "design_notes": ["设计备注"],
  "speaker_notes": "演讲者提示"
}}
"""

        return f"""You are a top-tier presentation slide planner. Generate the full IR for exactly one slide in a single pass.

You must follow the deck IR constraints:
{json.dumps(deck_constraints, ensure_ascii=False, indent=2)[:4500]}

Current slide blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

Current slide_brief:
{json.dumps(brief_payload, ensure_ascii=False, indent=2)[:2500]}

Most relevant supporting excerpt for this slide:
{brief_excerpt[:1800]}

Requirements:
1. Fully specify `layout`, `blocks`, `design_notes`, `speaker_notes`, `visuals`, and `material_requests`.
2. If the slide needs a visual, prefer reusing an obvious existing self asset; only create minimal `material_requests` when reuse is not appropriate.
3. `layout.slots[*].slot_role` must clearly express semantic purpose such as `title`, `body`, `supporting_visual`, `hero_visual`, `metrics`, and `callout`.
4. For process/causality/architecture/method steps, prefer structured blocks: `process`, `comparison`, and `metric_strip`.
5. `points` should include 2-5 concise bullet points for fallback rendering.
6. `layout` should describe relative regions only, not pixel coordinates.
7. Include `source_evidence` showing how the slide is grounded in the source.
{language_instruction}
{complexity_instruction}

Output JSON:
{{
  "slide_id": "{blueprint["slide_id"]}",
  "type": "{blueprint["type"]}",
  "section_id": "{blueprint["section_id"]}",
  "section_title": "{blueprint.get("section_title", "")}",
  "title": "{blueprint["title"]}",
  "subtitle": "Optional subtitle",
  "core_message": "{blueprint["core_message"]}",
  "objective": "{blueprint.get("objective", "")}",
  "brief_id": "{blueprint.get("brief_id", "")}",
  "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
  "source_evidence": [
    {{
      "evidence_id": "{blueprint["slide_id"]}_evidence_01",
      "source_chunk_ids": {json.dumps(blueprint.get("source_chunk_ids", []), ensure_ascii=False)},
      "source_headings": {json.dumps(blueprint.get("source_headings", []), ensure_ascii=False)},
      "source_excerpt": {json.dumps(blueprint.get("source_excerpt", ""), ensure_ascii=False)},
      "rationale": "Explain how the slide conclusion is supported by the source excerpt"
    }}
  ],
  "layout": {{
    "name": "two_column",
    "variant": "default",
    "rationale": "Why this layout is appropriate",
    "grid": "12-column",
    "emphasis": "headline",
    "density": "balanced",
    "vary_from_previous": true,
    "render_policy": "semantic_slots",
    "slots": [
      {{
        "slot_id": "body",
        "slot_role": "body",
        "anchor": "left",
        "x_ratio": 0.06,
        "y_ratio": 0.23,
        "w_ratio": 0.42,
        "h_ratio": 0.62,
        "content_types": ["summary", "bullet_list"]
      }},
      {{
        "slot_id": "supporting_visual",
        "slot_role": "supporting_visual",
        "anchor": "right",
        "x_ratio": 0.54,
        "y_ratio": 0.23,
        "w_ratio": 0.38,
        "h_ratio": 0.56,
        "content_types": ["image", "chart", "table"]
      }}
    ]
  }},
  "blocks": [
    {{"block_id": "{blueprint["slide_id"]}_block_01", "kind": "summary", "label": "summary", "slot_id": "body", "content": "One-sentence summary", "items": []}},
    {{"block_id": "{blueprint["slide_id"]}_block_02", "kind": "bullet_list", "label": "key_points", "slot_id": "body", "content": "", "items": ["Point 1", "Point 2"]}}
  ],
  "points": ["Point 1", "Point 2"],
  "visuals": [
    {{
      "slot_id": "supporting_visual",
      "asset_role": "supporting_visual",
      "target_area": "right",
      "intent": "visual intent",
      "use_existing_asset_id": "self:0.jpg"
    }}
  ],
  "material_requests": [
    {{
      "request_id": "{blueprint["slide_id"]}_image_01",
      "asset_type": "image",
      "title": "Asset title",
      "caption": "Image description",
      "purpose": "Communication purpose served by the image",
      "target_slide_id": "{blueprint["slide_id"]}",
      "preferred_layout_slot": "supporting_visual"
    }}
  ],
  "design_notes": ["Design note"],
  "speaker_notes": "Presenter cue"
}}
"""

    def _build_slide_visual_prompt(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        content_slide: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> str:
        if self._model_profile() == "qwen":
            return self._build_qwen_slide_visual_prompt(deck_stage, blueprint, content_slide, slide_brief=slide_brief)

        brief_payload = slide_brief or {}
        visual_slots = [
            slot
            for slot in (content_slide.get("layout", {}).get("slots", []) or [])
            if str(slot.get("slot_role", "")).strip() in {"hero_visual", "supporting_visual", "metrics"}
        ]
        asset_lines = self._format_asset_lines(
            deck_stage.get("source_asset_index", {}).values(),
            {},
            limit=12,
        )

        if self.language_mode == "chinese":
            return f"""你正在为单张幻灯片补充视觉与素材规划，只输出很小的一段 JSON。

当前幻灯片蓝图：
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

当前内容骨架：
{json.dumps(content_slide, ensure_ascii=False, indent=2)[:5000]}

可用现有素材（如果适合，优先复用）：
{asset_lines}

要求：
1. 只输出 `visuals` 与 `material_requests`。
2. 如果已有 self 素材明显适合，优先在 `visuals[*].use_existing_asset_id` 中直接绑定。
3. 如果没有合适现有素材，再输出最少量的 `material_requests`。
4. 若布局没有视觉槽位，可返回空列表。
5. 不要输出其它字段。

输出 JSON：
{{
  "visuals": [
    {{
      "slot_id": "supporting_visual",
      "asset_role": "supporting_visual",
      "target_area": "right",
      "intent": "视觉意图",
      "use_existing_asset_id": "self:0.jpg"
    }}
  ],
  "material_requests": [
    {{
      "request_id": "{blueprint["slide_id"]}_image_01",
      "asset_type": "image",
      "title": "资产标题",
      "caption": "图像描述",
      "purpose": "此图像服务的沟通目的",
      "target_slide_id": "{blueprint["slide_id"]}",
      "preferred_layout_slot": "{visual_slots[0]['slot_id'] if visual_slots else 'supporting_visual'}"
    }}
  ]
}}"""

        return f"""You are generating only the visual/material plan for one slide. Return a very small JSON object.

Current slide blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

Current content skeleton:
{json.dumps(content_slide, ensure_ascii=False, indent=2)[:5000]}

Available existing assets (prefer reuse when clearly suitable):
{asset_lines}

Requirements:
1. Output only `visuals` and `material_requests`.
2. If an existing self asset is clearly suitable, prefer binding it via `visuals[*].use_existing_asset_id`.
3. Only create `material_requests` when reuse is not appropriate.
4. If the layout has no visual slots, empty lists are allowed.
5. Do not output any other fields.

Output JSON:
{{
  "visuals": [
    {{
      "slot_id": "supporting_visual",
      "asset_role": "supporting_visual",
      "target_area": "right",
      "intent": "visual intent",
      "use_existing_asset_id": "self:0.jpg"
    }}
  ],
  "material_requests": [
    {{
      "request_id": "{blueprint["slide_id"]}_image_01",
      "asset_type": "image",
      "title": "Asset title",
      "caption": "Image description",
      "purpose": "Communication purpose served by the image",
      "target_slide_id": "{blueprint["slide_id"]}",
      "preferred_layout_slot": "{visual_slots[0]['slot_id'] if visual_slots else 'supporting_visual'}"
    }}
  ]
}}"""

    def _plan_slide_visuals(
        self,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
        content_slide: Dict[str, Any],
        slide_brief: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        prompt = self._build_slide_visual_prompt(deck_stage, blueprint, content_slide, slide_brief=slide_brief)
        last_error: Exception | None = None
        for attempt in range(2):
            candidate_prompt = prompt
            if attempt > 0:
                candidate_prompt += "\n\nReturn one strictly valid JSON object containing only visuals and material_requests."
            try:
                response = self.client.chat(
                    [{"role": "user", "content": candidate_prompt}],
                    temperature=0.1,
                    response_format="json",
                )
                if self._model_profile() == "qwen":
                    response = self._repair_qwen_visual_fragment_response(response)
                raw_visual_plan = self._extract_json_with_repair(
                    response,
                    repair_context=f"slide visual planning {blueprint.get('slide_id', '')}",
                )
                visual_plan = {
                    "visuals": raw_visual_plan.get("visuals", []) or [],
                    "material_requests": raw_visual_plan.get("material_requests", []) or [],
                }
                return visual_plan
            except RuntimeError as exc:
                last_error = exc

        empty_plan = {"visuals": [], "material_requests": []}
        return empty_plan

    @staticmethod
    def _explicit_visual_slots(slide: Dict[str, Any]) -> list[Dict[str, Any]]:
        slots = slide.get("layout", {}).get("slots", []) or []
        return [slot for slot in slots if SlidePlanner._is_explicit_visual_slot(slot)]

    @staticmethod
    def _is_explicit_visual_slot(slot: Dict[str, Any]) -> bool:
        visual_terms = {
            "hero_visual",
            "supporting_visual",
            "metrics",
            "visual",
            "image",
            "figure",
            "diagram",
            "chart",
            "photo",
            "illustration",
        }
        for key in ("slot_role", "slot_id", "name"):
            value = str(slot.get(key, "")).strip().lower()
            if value in visual_terms or any(term in value for term in visual_terms):
                return True
        return False

    def _merge_slide_content_and_visual_plan(
        self,
        content_slide: Dict[str, Any],
        visual_plan: Dict[str, Any],
        *,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(content_slide)
        merged["visuals"] = visual_plan.get("visuals", []) or []
        merged["material_requests"] = visual_plan.get("material_requests", []) or []
        if self._model_profile() != "qwen":
            self._ensure_visual_plan_fallback(
                merged,
                deck_stage=deck_stage,
                blueprint=blueprint,
            )
        return merged

    def _needs_qwen_visual_followup(self, slide: Dict[str, Any]) -> bool:
        if self._has_unmatched_visual_requests(slide):
            return True
        if slide.get("visuals"):
            return False
        return bool(self._explicit_visual_slots(slide))

    @staticmethod
    def _has_unmatched_visual_requests(slide: Dict[str, Any]) -> bool:
        material_requests = slide.get("material_requests")
        request_ids: set[str] = set()
        if isinstance(material_requests, list):
            request_ids = {
                str(request.get("request_id"))
                for request in material_requests
                if isinstance(request, dict) and request.get("request_id")
            }
        visuals = slide.get("visuals")
        if not isinstance(visuals, list):
            return False
        for visual in visuals:
            if not isinstance(visual, dict):
                continue
            request_id = visual.get("use_request_id")
            if request_id and str(request_id) not in request_ids:
                return True
        return False

    def _ensure_visual_plan_fallback(
        self,
        slide: Dict[str, Any],
        *,
        deck_stage: Dict[str, Any],
        blueprint: Dict[str, Any],
    ) -> None:
        if slide.get("visuals"):
            return

        slots = slide.get("layout", {}).get("slots", []) or []
        visual_slots = [
            slot for slot in slots
            if str(slot.get("slot_role", "")).strip() in {"hero_visual", "supporting_visual"}
        ]
        if not visual_slots:
            return

        slot_id = visual_slots[0].get("slot_id", "supporting_visual")
        asset_index = deck_stage.get("source_asset_index", {}) or {}
        preferred_asset_id = self._pick_existing_visual_asset_id(asset_index, blueprint=blueprint, slide=slide)
        if preferred_asset_id:
            slide["visuals"] = [
                {
                    "slot_id": slot_id,
                    "asset_role": visual_slots[0].get("slot_role", "supporting_visual"),
                    "target_area": "right",
                    "intent": blueprint.get("visual_intent", ""),
                    "use_existing_asset_id": preferred_asset_id,
                }
            ]
            slide.setdefault("material_requests", [])
            return

        request_id = f"{slide.get('slide_id', blueprint.get('slide_id', 'slide'))}_image_01"
        slide["visuals"] = [
            {
                "slot_id": slot_id,
                "asset_role": visual_slots[0].get("slot_role", "supporting_visual"),
                "target_area": "right",
                "intent": blueprint.get("visual_intent", ""),
                "use_request_id": request_id,
            }
        ]
        slide["material_requests"] = slide.get("material_requests", []) or [
            {
                "request_id": request_id,
                "asset_type": "image",
                "title": slide.get("title") or blueprint.get("title") or "Supporting visual",
                "caption": blueprint.get("visual_intent") or slide.get("core_message") or "Supporting visual",
                "purpose": slide.get("objective") or blueprint.get("objective") or "Support the slide's core message",
                "target_slide_id": slide.get("slide_id") or blueprint.get("slide_id", "slide_01"),
                "preferred_layout_slot": slot_id,
                "need_count": 1,
                "size_preference": "large",
                "orientation_preference": "landscape",
                "aspect_ratio_hint": "around 16:9",
                "style_keywords": ["clean", "editorial"],
                "minimum_vlm_score": 0.72,
            }
        ]

    @staticmethod
    def _pick_existing_visual_asset_id(
        asset_index: Dict[str, Dict[str, Any]],
        *,
        blueprint: Dict[str, Any],
        slide: Dict[str, Any],
    ) -> str | None:
        image_assets = [
            asset for asset in asset_index.values()
            if asset.get("asset_kind") == "image" or asset.get("category") == "self"
        ]
        if not image_assets:
            return None
        if len(image_assets) == 1:
            return image_assets[0].get("asset_id")

        text = " ".join(
            [
                str(blueprint.get("title", "")),
                str(blueprint.get("core_message", "")),
                str(slide.get("title", "")),
                str(slide.get("core_message", "")),
            ]
        ).lower()
        workflow_tokens = ("workflow", "pipeline", "process", "step", "architecture", "system")
        if any(token in text for token in workflow_tokens):
            for asset in image_assets:
                asset_id = str(asset.get("asset_id", ""))
                path = str(asset.get("path", "")).lower()
                if any(key in asset_id.lower() or key in path for key in ("5", "workflow", "pipeline", "process", "arch")):
                    return asset.get("asset_id")

        return image_assets[0].get("asset_id")

    def _model_profile(self) -> str:
        return getattr(self.client, "model_profile", "general")

    @staticmethod
    def _repair_qwen_slide_fragment_response(response: str, blueprint: Dict[str, Any]) -> str:
        stripped = str(response or "").lstrip()
        if not stripped.startswith("{"):
            return response
        if re.match(r'\{\s*"slide_id"\s*:', stripped):
            return response
        layout_index = stripped.find('"layout"')
        if layout_index == -1:
            return response
        if '"source_evidence"' in stripped[:layout_index]:
            return response

        root_fields = {
            "slide_id": blueprint.get("slide_id", "slide_01"),
            "type": blueprint.get("type", "content"),
            "section_id": blueprint.get("section_id", ""),
            "section_title": blueprint.get("section_title", ""),
            "title": blueprint.get("title", ""),
            "subtitle": "",
            "core_message": blueprint.get("core_message", ""),
            "objective": blueprint.get("objective", ""),
            "brief_id": blueprint.get("brief_id", ""),
            "source_chunk_ids": blueprint.get("source_chunk_ids", []),
        }
        prefix = "{\n"
        for key, value in root_fields.items():
            prefix += f'  "{key}": {json.dumps(value, ensure_ascii=False)},\n'
        prefix += '  "source_evidence": [\n'
        return prefix + stripped

    @staticmethod
    def _repair_qwen_visual_fragment_response(response: str) -> str:
        stripped = str(response or "").lstrip()
        if not stripped.startswith("{"):
            return response
        if re.match(r'\{\s*"visuals"\s*:', stripped):
            return response
        if '"material_requests"' not in stripped:
            return response
        return '{"visuals": [\n' + stripped

    @staticmethod
    def _extract_json(
        response: str,
        repair_context: str = "",
    ) -> Dict[str, Any]:
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", response)
        if fenced_match:
            response = fenced_match.group(1)
        else:
            json_start = response.find("{")
            if json_start == -1:
                raise RuntimeError(f"Planner did not return JSON: {response[:200]}")
            response = SlidePlanner._slice_first_json_object(response[json_start:])

        try:
            response = response.lstrip("\ufeff").strip()
            response = response.replace('"""', '"')
            return json.loads(response)
        except json.JSONDecodeError as exc:
            repaired = SlidePlanner._balance_json_text(response)
            repaired = re.sub(r',(?=\s*[}\]])', '', repaired)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                raise RuntimeError(f"JSON parsing failed: {exc}\nResponse snippet: {response[:400]}") from exc

    def _extract_json_with_repair(
        self,
        response: str,
        repair_context: str = "",
    ) -> Dict[str, Any]:
        try:
            return self._extract_json(response, repair_context=repair_context)
        except RuntimeError as exc:
            repair_prompt = f"""Repair this model response into one valid JSON object.

Context: {repair_context or "unknown"}

Rules:
- Return JSON only.
- Preserve the original semantics as much as possible.
- Fix quoting, trailing commas, truncated fences, and invalid escaping.

Invalid response:
{response[:6000]}

Parser error:
{str(exc)[:1200]}
"""
            repaired = self.client.chat(
                [{"role": "user", "content": repair_prompt}],
                temperature=0.0,
                response_format="json",
            )
            return self._extract_json(repaired, repair_context=repair_context)

    @staticmethod
    def _slice_first_json_object(text: str) -> str:
        stack: list[str] = []
        in_string = False
        escape = False

        for index, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch in '}]':
                if not stack or ch != stack[-1]:
                    break
                stack.pop()
                if not stack:
                    return text[: index + 1]

        return text

    @staticmethod
    def _balance_json_text(text: str) -> str:
        stack: list[str] = []
        in_string = False
        escape = False

        for ch in text:
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch in '}]' and stack and ch == stack[-1]:
                stack.pop()

        balanced = text
        if in_string:
            balanced += '"'
        if stack:
            balanced += ''.join(reversed(stack))
        return balanced

    def _normalize_deck_structure(
        self,
        raw_deck: Dict[str, Any],
        materials: Dict[str, Any],
        slide_briefs: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        asset_index = self._build_asset_index(materials)
        slide_briefs = slide_briefs or {}
        storyline_seed = raw_deck.get("storyline", {}) or slide_briefs.get("storyline_hint", {})
        storyline = self._normalize_storyline(storyline_seed)
        theme = self._normalize_theme(raw_deck.get("theme", {}))
        deck_outline = self._normalize_deck_outline(raw_deck, storyline, slide_briefs=slide_briefs)

        return {
            "title": raw_deck.get("title")
            or raw_deck.get("deck_title")
            or slide_briefs.get("title_hint")
            or "Untitled Deck",
            "subtitle": raw_deck.get("subtitle", "") or slide_briefs.get("subtitle_hint", ""),
            "storyline": storyline,
            "theme": theme,
            "longdoc_profile": slide_briefs.get("longdoc_profile", self._model_dump(LongDocProfile())),
            "deck_outline": deck_outline,
            "planner_notes": self._normalize_string_list(raw_deck.get("planner_notes", []))
            or self._normalize_string_list(slide_briefs.get("planner_notes", [])),
            "source_asset_index": asset_index,
        }

    def _normalize_deck_outline(
        self,
        raw_deck: Dict[str, Any],
        storyline: Dict[str, Any],
        slide_briefs: Dict[str, Any] | None = None,
    ) -> list[Dict[str, Any]]:
        slide_briefs = slide_briefs or {}
        brief_map = {brief.get("slide_id") or brief.get("brief_id"): brief for brief in slide_briefs.get("slide_briefs", [])}
        raw_outline = raw_deck.get("deck_outline") or raw_deck.get("slides") or []
        if not raw_outline and slide_briefs.get("slide_briefs"):
            raw_outline = slide_briefs.get("slide_briefs", [])
        section_map = {section["id"]: section for section in storyline.get("sections", [])}
        outline = []
        for index, slide in enumerate(raw_outline, start=1):
            section_id = slide.get("section_id") or self._infer_section_id(index, section_map)
            brief = brief_map.get(slide.get("slide_id")) or brief_map.get(slide.get("brief_id"))
            slide_type = self._normalize_slide_type(slide.get("type"), index=index)
            outline.append(
                self._model_dump(
                    SlideBlueprint(
                        slide_id=slide.get("slide_id") or f"slide_{index:02d}",
                        type=slide_type,
                        section_id=section_id,
                        section_title=slide.get("section_title")
                        or section_map.get(section_id, {}).get("title", ""),
                        title=slide.get("title") or slide.get("headline") or slide.get("core_message") or f"Slide {index}",
                        core_message=slide.get("core_message") or slide.get("title") or f"Slide {index}",
                        objective=slide.get("objective", ""),
                        brief_id=slide.get("brief_id")
                        or (brief.get("brief_id") if isinstance(brief, dict) else "")
                        or f"brief_{index:02d}",
                        source_chunk_ids=self._normalize_string_list(
                            slide.get("source_chunk_ids", [])
                            or (brief.get("source_chunk_ids", []) if isinstance(brief, dict) else [])
                        ),
                        source_headings=self._normalize_string_list(
                            slide.get("source_headings", [])
                            or (brief.get("source_headings", []) if isinstance(brief, dict) else [])
                        ),
                        source_excerpt=slide.get("source_excerpt", "")
                        or (brief.get("source_excerpt", "") if isinstance(brief, dict) else ""),
                    )
                )
            )
        target_slide_count = int((slide_briefs.get("longdoc_profile") or {}).get("target_slide_count") or 0)
        return self._cap_outline_to_target(outline, target_slide_count)

    @staticmethod
    def _cap_outline_to_target(
        outline: list[Dict[str, Any]],
        target_slide_count: int,
    ) -> list[Dict[str, Any]]:
        if target_slide_count <= 0 or len(outline) <= target_slide_count:
            return outline
        if target_slide_count == 1:
            return outline[:1]

        capped = outline[:target_slide_count]
        last_slide = outline[-1]
        last_type = str(last_slide.get("type", "")).strip().lower().replace("-", "_")
        if last_type == "closing":
            capped = outline[: target_slide_count - 1] + [last_slide]

        deduped: list[Dict[str, Any]] = []
        seen_slide_ids: set[str] = set()
        for slide in capped:
            slide_id = str(slide.get("slide_id", "")).strip()
            if slide_id and slide_id in seen_slide_ids:
                continue
            if slide_id:
                seen_slide_ids.add(slide_id)
            deduped.append(slide)
        return deduped[:target_slide_count]

    def _normalize_storyline(self, raw_storyline: Dict[str, Any]) -> Dict[str, Any]:
        sections = []
        for index, section in enumerate(raw_storyline.get("sections", []), start=1):
            section_id = section.get("id") or f"section_{index:02d}"
            sections.append(
                self._model_dump(
                    StorySection(
                        id=section_id,
                        title=section.get("title") or f"Section {index}",
                        objective=section.get("objective") or "",
                    )
                )
            )

        return self._model_dump(
            Storyline(
                topic=raw_storyline.get("topic", ""),
                audience=raw_storyline.get("audience", "general"),
                presentation_goal=raw_storyline.get("presentation_goal", ""),
                tone=raw_storyline.get("tone", "analytical"),
                sections=[StorySection(**section) for section in sections],
            )
        )

    def _normalize_theme(self, raw_theme: Dict[str, Any]) -> Dict[str, Any]:
        theme = DeckTheme(
            name=raw_theme.get("name", "editorial"),
            primary_color=raw_theme.get("primary_color", "#134E8E"),
            secondary_color=raw_theme.get("secondary_color", "#C00707"),
            accent_color=raw_theme.get("accent_color", "#FFB33F"),
            background_color=raw_theme.get("background_color", "#F7F4EE"),
            text_color=raw_theme.get("text_color", "#1F2937"),
            font_family=raw_theme.get("font_family", "Aptos"),
            density=self._normalize_density(raw_theme.get("density", "balanced")),
            style_guardrails=self._normalize_string_list(raw_theme.get("style_guardrails", []))
            or DeckTheme().style_guardrails,
        )
        return self._model_dump(theme)

    def _normalize_material_requests(self, requests: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        normalized_requests = []
        for index, request in enumerate(requests, start=1):
            if self._model_profile() == "qwen":
                request = self._normalize_qwen_material_request_aliases(request)
            asset_type = self._normalize_material_asset_type(request.get("asset_type", "image"))
            acquisition_defaults = self._default_acquisition_plan(asset_type)
            raw_plan = request.get("acquisition_plan", {})
            plan = AcquisitionPlan(
                source_options=raw_plan.get("source_options", acquisition_defaults["source_options"]),
                candidate_count=raw_plan.get("candidate_count", 2),
                descriptor_model=raw_plan.get("descriptor_model", "gpt-5.4"),
                selection_method=raw_plan.get(
                    "selection_method",
                    acquisition_defaults["selection_method"],
                ),
                fallback=raw_plan.get("fallback", acquisition_defaults["fallback"]),
            )
            normalized_requests.append(
                self._model_dump(
                    MaterialRequest(
                        request_id=request.get("request_id") or f"request_{asset_type}_{index:02d}",
                        asset_type=asset_type,
                        title=request.get("title") or request.get("caption") or f"{asset_type} request {index}",
                        caption=request.get("caption") or request.get("title") or "",
                        purpose=request.get("purpose", ""),
                        target_slide_id=request.get("target_slide_id") or f"slide_{index:02d}",
                        preferred_layout_slot=request.get("preferred_layout_slot", "supporting_visual"),
                        need_count=max(1, int(request.get("need_count", 1))),
                        size_preference=request.get("size_preference", "medium"),
                        orientation_preference=self._normalize_orientation_preference(
                            request.get("orientation_preference", "any")
                        ),
                        aspect_ratio_hint=request.get("aspect_ratio_hint", "any"),
                        style_keywords=self._normalize_string_list(request.get("style_keywords", [])),
                        minimum_vlm_score=float(request.get("minimum_vlm_score", 0.7)),
                        acquisition_plan=plan,
                    )
                )
            )
        return normalized_requests

    @staticmethod
    def _normalize_qwen_material_request_aliases(request: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(request)
        if not normalized.get("asset_type") and normalized.get("type"):
            normalized["asset_type"] = normalized.get("type")
        if not normalized.get("caption") and normalized.get("description"):
            normalized["caption"] = normalized.get("description")
        if not normalized.get("purpose") and normalized.get("description"):
            normalized["purpose"] = normalized.get("description")
        if not normalized.get("title") and normalized.get("description"):
            normalized["title"] = normalized.get("description")
        return normalized

    @staticmethod
    def _normalize_material_asset_type(value: Any) -> str:
        normalized = str(value or "image").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"icon", "icons", "symbol", "glyph", "logo", "pictogram"}:
            return "icon"
        if normalized in {
            "image",
            "images",
            "photo",
            "figure",
            "fig",
            "diagram",
            "illustration",
            "chart",
            "graph",
            "plot",
            "visual",
            "infographic",
            "screenshot",
            "interface",
        }:
            return "image"
        return "image"

    @staticmethod
    def _normalize_orientation_preference(value: Any) -> str:
        normalized = str(value or "any").strip().lower()
        normalized = (
            normalized.replace("-", "_")
            .replace(" ", "_")
            .replace(":", "_")
            .replace("/", "_")
        )
        alias_map = {
            "auto": "any",
            "automatic": "any",
            "default": "any",
            "either": "any",
            "flexible": "any",
            "no_preference": "any",
            "none": "any",
            "horizontal": "landscape",
            "horiz": "landscape",
            "wide": "landscape",
            "wide_format": "landscape",
            "widescreen": "landscape",
            "widescreen_16_9": "landscape",
            "16_9": "landscape",
            "4_3": "landscape",
            "vertical": "portrait",
            "vert": "portrait",
            "tall": "portrait",
            "upright": "portrait",
            "9_16": "portrait",
            "3_4": "portrait",
            "quadratic": "square",
            "box": "square",
            "1_1": "square",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized in {"any", "landscape", "portrait", "square"}:
            return normalized
        if any(token in normalized for token in ("landscape", "horizontal", "wide", "widescreen")):
            return "landscape"
        if any(token in normalized for token in ("portrait", "vertical", "tall", "upright")):
            return "portrait"
        if any(token in normalized for token in ("square", "quadratic", "1_1")):
            return "square"
        return "any"

    def _normalize_slide(
        self,
        slide: Dict[str, Any],
        index: int,
        deck_id: str,
        asset_index: Dict[str, Dict[str, Any]],
        request_ids: set[str],
        blueprint: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        blueprint = blueprint or {}
        slide_id = slide.get("slide_id") or f"slide_{index:02d}"
        slide_type = self._normalize_slide_type(slide.get("type"), index=index)
        title = (
            slide.get("title")
            or slide.get("headline")
            or blueprint.get("title")
            or slide.get("core_message")
            or f"Slide {index}"
        )
        subtitle = slide.get("subtitle", "")
        core_message = slide.get("core_message") or blueprint.get("core_message") or title
        objective = slide.get("objective") or blueprint.get("objective", "")
        layout = self._normalize_layout(slide.get("layout", {}), index, slide_type)
        points = self._extract_points(slide)
        blocks = self._normalize_blocks(slide, points)
        visuals = self._normalize_visuals(slide, slide_id, asset_index, request_ids)
        selected_asset_id, selected_asset_path = self._resolve_selected_asset(slide, visuals, asset_index)

        slide_model = SlideIR(
            metadata=IRMetadata(
                schema_name="presentagent.slide_ir",
                deck_id=deck_id,
                slide_id=slide_id,
                stage="planned",
            ),
            deck_id=deck_id,
            slide_id=slide_id,
            slide_number=index,
            type=slide_type,
            section_id=slide.get("section_id") or blueprint.get("section_id") or f"section_{index:02d}",
            section_title=slide.get("section_title") or blueprint.get("section_title", ""),
            title=title,
            subtitle=subtitle,
            core_message=core_message,
            objective=objective,
            brief_id=slide.get("brief_id") or blueprint.get("brief_id", ""),
            source_chunk_ids=self._normalize_string_list(
                slide.get("source_chunk_ids", []) or blueprint.get("source_chunk_ids", [])
            ),
            source_evidence=[
                SourceEvidence(**evidence)
                for evidence in self._normalize_source_evidence(slide, blueprint, slide_id)
            ],
            layout=LayoutSpec(**layout),
            blocks=[ContentBlock(**block) for block in blocks],
            points=points,
            visuals=[VisualBinding(**visual) for visual in visuals],
            design_notes=self._normalize_string_list(slide.get("design_notes", [])),
            speaker_notes=slide.get("speaker_notes", ""),
            selected_asset_path=selected_asset_path,
            selected_asset_id=selected_asset_id,
        )
        return self._model_dump(slide_model)

    def _normalize_source_evidence(
        self,
        slide: Dict[str, Any],
        blueprint: Dict[str, Any],
        slide_id: str,
    ) -> list[Dict[str, Any]]:
        raw_evidence = slide.get("source_evidence", [])
        normalized: list[Dict[str, Any]] = []
        for index, evidence in enumerate(raw_evidence, start=1):
            # Skip if evidence is not a dict (e.g., if it's a string)
            if not isinstance(evidence, dict):
                continue
            if self._model_profile() == "qwen":
                evidence = self._normalize_qwen_source_evidence_aliases(evidence)
            normalized.append(
                self._model_dump(
                    SourceEvidence(
                        evidence_id=evidence.get("evidence_id") or f"{slide_id}_evidence_{index:02d}",
                        source_chunk_ids=self._normalize_string_list(evidence.get("source_chunk_ids", [])),
                        source_headings=self._normalize_string_list(evidence.get("source_headings", [])),
                        source_excerpt=evidence.get("source_excerpt", ""),
                        rationale=evidence.get("rationale", ""),
                    )
                )
            )
        if normalized:
            return normalized

        source_chunk_ids = self._normalize_string_list(
            slide.get("source_chunk_ids", []) or blueprint.get("source_chunk_ids", [])
        )
        source_headings = self._normalize_string_list(
            slide.get("source_headings", []) or blueprint.get("source_headings", [])
        )
        source_excerpt = slide.get("source_excerpt", "") or blueprint.get("source_excerpt", "")
        rationale = slide.get("core_message") or blueprint.get("core_message", "")
        if not source_chunk_ids and not source_headings and not source_excerpt:
            return []
        return [
            self._model_dump(
                SourceEvidence(
                    evidence_id=f"{slide_id}_evidence_01",
                    source_chunk_ids=source_chunk_ids,
                    source_headings=source_headings,
                    source_excerpt=source_excerpt,
                    rationale=rationale,
                )
            )
        ]

    @staticmethod
    def _normalize_qwen_source_evidence_aliases(evidence: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(evidence)
        if not normalized.get("source_chunk_ids") and normalized.get("chunk_id"):
            normalized["source_chunk_ids"] = [normalized.get("chunk_id")]
        if not normalized.get("source_headings") and normalized.get("heading"):
            normalized["source_headings"] = [normalized.get("heading")]
        if not normalized.get("source_excerpt") and normalized.get("excerpt"):
            normalized["source_excerpt"] = normalized.get("excerpt")
        return normalized

    def _plan_slides(
        self,
        deck_stage: Dict[str, Any],
        brief_map: Dict[str, Dict[str, Any]],
        progress_callback=None,
    ) -> list[Dict[str, Any]]:
        blueprints = deck_stage.get("deck_outline", [])
        if not blueprints:
            return []

        if min(self.max_workers, len(blueprints)) <= 1:
            results = []
            for index, blueprint in enumerate(blueprints, start=1):
                results.append(
                    self.plan_slide(
                        deck_stage,
                        blueprint,
                        slide_brief=self._lookup_brief_for_blueprint(brief_map, blueprint),
                    )
                )
                if progress_callback is not None:
                    progress_callback(index, len(blueprints), blueprint.get("slide_id", f"slide_{index:02d}"))
            return results

        results: dict[int, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(blueprints))) as executor:
            future_map = {
                executor.submit(
                    self.plan_slide,
                    deck_stage,
                    blueprint,
                    self._lookup_brief_for_blueprint(brief_map, blueprint),
                ): index
                for index, blueprint in enumerate(blueprints)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                results[index] = future.result()
                if progress_callback is not None:
                    progress_callback(
                        len(results),
                        len(blueprints),
                        blueprints[index].get("slide_id", f"slide_{index + 1:02d}"),
                    )
        return [results[index] for index in range(len(blueprints))]

    @staticmethod
    def _build_slide_brief_map(slide_briefs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        brief_map: Dict[str, Dict[str, Any]] = {}
        for brief in slide_briefs.get("slide_briefs", []):
            slide_id = brief.get("slide_id")
            brief_id = brief.get("brief_id")
            if slide_id:
                brief_map[slide_id] = brief
            if brief_id:
                brief_map[brief_id] = brief
        return brief_map

    @staticmethod
    def _lookup_brief_for_blueprint(
        brief_map: Dict[str, Dict[str, Any]],
        blueprint: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        return brief_map.get(blueprint.get("slide_id", "")) or brief_map.get(blueprint.get("brief_id", ""))

    def _normalize_layout(self, raw_layout: Any, index: int, slide_type: str) -> Dict[str, Any]:
        if isinstance(raw_layout, str):
            raw_layout = {"name": raw_layout}
        layout_name = raw_layout.get("name") or ("hero" if index == 1 else "two_column")
        if layout_name not in self.ALLOWED_LAYOUTS:
            layout_name = "two_column"
        raw_slots = raw_layout.get("slots") or self._default_layout_slots(layout_name, slide_type)
        slots = [
            LayoutSlot(
                slot_id=slot.get("slot_id", f"{layout_name}_slot_{slot_index:02d}"),
                slot_role=self._normalize_slot_role(slot.get("slot_role", "body")),
                anchor=self._normalize_slot_anchor(slot.get("anchor", "center")),
                x_ratio=slot.get("x_ratio", 0.0),
                y_ratio=slot.get("y_ratio", 0.0),
                w_ratio=slot.get("w_ratio", 1.0),
                h_ratio=slot.get("h_ratio", 1.0),
                content_types=self._normalize_string_list(slot.get("content_types", [])),
            )
            for slot_index, slot in enumerate(raw_slots, start=1)
        ]
        return self._model_dump(
            LayoutSpec(
                name=layout_name,
                variant=raw_layout.get("variant", "default"),
                rationale=raw_layout.get("rationale", ""),
                grid=raw_layout.get("grid", "12-column"),
                emphasis=raw_layout.get("emphasis", "headline"),
                density=self._normalize_density(raw_layout.get("density", "balanced")),
                vary_from_previous=raw_layout.get("vary_from_previous", True),
                render_policy=raw_layout.get("render_policy", "semantic_slots"),
                slots=slots,
            )
        )

    @staticmethod
    def _normalize_density(value: Any) -> str:
        normalized = str(value or "balanced").strip().lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "airy": "airy",
            "airy_layout": "airy",
            "light": "airy",
            "loose": "airy",
            "open": "airy",
            "spacious": "airy",
            "balanced": "balanced",
            "medium": "balanced",
            "normal": "balanced",
            "standard": "balanced",
            "dense": "dense",
            "compact": "dense",
            "tight": "dense",
            "heavy": "dense",
            "packed": "dense",
        }
        return mapping.get(normalized, "balanced")

    def _normalize_blocks(self, slide: Dict[str, Any], points: list[str]) -> list[Dict[str, Any]]:
        raw_blocks = slide.get("blocks", [])
        normalized_blocks: list[Dict[str, Any]] = []
        for block_index, block in enumerate(raw_blocks, start=1):
            block_kind = block.get("kind") or (
                block.get("type") if self._model_profile() == "qwen" else None
            ) or "bullet_list"
            normalized_blocks.append(
                self._model_dump(
                    ContentBlock(
                        block_id=block.get("block_id") or f"{slide.get('slide_id', 'slide')}_block_{block_index:02d}",
                        kind=self._normalize_block_kind(block_kind),
                        label=block.get("label", ""),
                        slot_id=block.get("slot_id") or self._default_slot_for_block_kind(block_kind),
                        emphasis=block.get("emphasis", "primary"),
                        content=block.get("content", ""),
                        items=self._normalize_string_list(block.get("items", [])),
                    )
                )
            )
        if not normalized_blocks:
            summary = slide.get("summary") or slide.get("core_message") or slide.get("title", "")
            if summary:
                normalized_blocks.append(
                    self._model_dump(
                        ContentBlock(
                            block_id=f"{slide.get('slide_id', 'slide')}_block_01",
                            kind="summary",
                            label="summary",
                            slot_id="body",
                            content=summary,
                            items=[],
                        )
                    )
                )
            if points:
                normalized_blocks.append(
                    self._model_dump(
                        ContentBlock(
                            block_id=f"{slide.get('slide_id', 'slide')}_block_02",
                            kind="bullet_list",
                            label="key_points",
                            slot_id="body",
                            content="",
                            items=points,
                        )
                    )
                )
        return normalized_blocks

    def _normalize_visuals(
        self,
        slide: Dict[str, Any],
        slide_id: str,
        asset_index: Dict[str, Dict[str, Any]],
        request_ids: set[str],
    ) -> list[Dict[str, Any]]:
        raw_visuals = slide.get("visuals", [])
        if not raw_visuals and slide.get("selected_asset_id"):
            raw_visuals = [
                {
                    "slot_id": f"{slide_id}_visual_01",
                    "asset_role": "supporting_visual",
                    "target_area": "right",
                    "use_existing_asset_id": slide["selected_asset_id"],
                }
            ]
        if not raw_visuals and slide.get("image_index") is not None:
            asset_id = self._asset_id_from_image_index(slide["image_index"], asset_index)
            if asset_id:
                raw_visuals = [
                    {
                        "slot_id": f"{slide_id}_visual_01",
                        "asset_role": "supporting_visual",
                        "target_area": "right",
                        "use_existing_asset_id": asset_id,
                    }
                ]

        visuals = []
        for visual_index, visual in enumerate(raw_visuals, start=1):
            selected_candidate = visual.get("selected_candidate")
            normalized_candidate = None
            if isinstance(selected_candidate, dict):
                normalized_candidate = self._model_dump(
                    MaterialCandidate(
                        asset_id=selected_candidate.get("asset_id"),
                        path=selected_candidate.get("path"),
                        source=selected_candidate.get("source", "unknown"),
                        category=selected_candidate.get("category", ""),
                        asset_kind=selected_candidate.get("asset_kind", ""),
                        caption=selected_candidate.get("caption", ""),
                        description=selected_candidate.get("description", ""),
                        why_selected=selected_candidate.get("why_selected", ""),
                        vlm_score=selected_candidate.get("vlm_score"),
                        content_score=selected_candidate.get("content_score"),
                        geometry_score=selected_candidate.get("geometry_score"),
                        width_px=selected_candidate.get("width_px"),
                        height_px=selected_candidate.get("height_px"),
                        aspect_ratio=selected_candidate.get("aspect_ratio"),
                        orientation=selected_candidate.get("orientation", ""),
                        file_size_bytes=selected_candidate.get("file_size_bytes"),
                    )
                )

            existing_asset_id = visual.get("use_existing_asset_id")
            if existing_asset_id and existing_asset_id not in asset_index:
                existing_asset_id = None

            request_id = visual.get("use_request_id")
            if request_id and request_id not in request_ids:
                request_id = None

            visuals.append(
                self._model_dump(
                    VisualBinding(
                        slot_id=visual.get("slot_id") or f"{slide_id}_visual_{visual_index:02d}",
                        asset_role=visual.get("asset_role", "supporting_visual"),
                        target_area=visual.get("target_area", "right"),
                        intent=self._normalize_visual_intent(visual),
                        use_existing_asset_id=existing_asset_id,
                        use_request_id=request_id,
                        selected_candidate=MaterialCandidate(**normalized_candidate)
                        if normalized_candidate
                        else None,
                    )
                )
            )
        return visuals

    def _normalize_visual_intent(self, visual: Dict[str, Any]) -> str:
        if visual.get("intent"):
            return visual.get("intent", "")
        if self._model_profile() == "qwen":
            return visual.get("description") or visual.get("alt_text", "")
        return ""

    def _resolve_selected_asset(
        self,
        slide: Dict[str, Any],
        visuals: list[Dict[str, Any]],
        asset_index: Dict[str, Dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        selected_asset_id = slide.get("selected_asset_id")
        if selected_asset_id and selected_asset_id in asset_index:
            return selected_asset_id, asset_index[selected_asset_id]["path"]

        for visual in visuals:
            asset_id = visual.get("use_existing_asset_id")
            if asset_id and asset_id in asset_index:
                return asset_id, asset_index[asset_id]["path"]
            candidate = visual.get("selected_candidate")
            if candidate and candidate.get("path"):
                return candidate.get("asset_id"), candidate["path"]

        if slide.get("selected_asset_path"):
            return slide.get("selected_asset_id"), slide["selected_asset_path"]
        return None, None

    def _extract_points(self, slide: Dict[str, Any]) -> list[str]:
        points = self._normalize_string_list(slide.get("points", []))
        if points:
            return points[:5]

        content = slide.get("content", {})
        for key in ("key_points", "supporting_points", "evidence", "takeaways", "items"):
            extracted = self._normalize_string_list(content.get(key, []))
            if extracted:
                return extracted[:5]

        blocks = slide.get("blocks", [])
        extracted_points = []
        for block in blocks:
            extracted_points.extend(self._normalize_string_list(block.get("items", [])))
            if len(extracted_points) >= 5:
                return extracted_points[:5]
        if extracted_points:
            return extracted_points[:5]

        fallback = []
        if slide.get("core_message"):
            fallback.append(slide["core_message"])
        if slide.get("summary"):
            fallback.append(slide["summary"])
        return fallback[:5]

    @staticmethod
    def _default_acquisition_plan(asset_type: str) -> Dict[str, Any]:
        return {
            "source_options": ["paper2any"],
            "selection_method": "VLM semantic and geometry scoring with validation loop",
            "fallback": "If generation fails after retries, fall back to text-only layout",
        }

    @staticmethod
    def _format_asset_lines(
        assets: Iterable[Dict[str, Any]],
        descriptions: Dict[str, str],
        limit: int,
    ) -> str:
        lines = []
        for asset in list(assets)[:limit]:
            description = descriptions.get(asset["path"], asset.get("description", ""))[:180]
            orientation = asset.get("orientation", "unknown")
            width_px = asset.get("width_px")
            height_px = asset.get("height_px")
            aspect_ratio = asset.get("aspect_ratio")
            geometry = f"{width_px}x{height_px}" if width_px and height_px else "unknown"
            lines.append(
                f'- {asset["asset_id"]} | {asset["category"]} | {asset["path"]} | '
                f'orientation={orientation} | size={geometry} | aspect_ratio={aspect_ratio or "unknown"} | '
                f'{description or "No description"}'
            )
        return "\n".join(lines) if lines else "None"

    @staticmethod
    def _normalize_string_list(values: Any) -> list[str]:
        if not values:
            return []
        if isinstance(values, str):
            values = [values]
        normalized = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, dict):
                text = ""
                for key in ("text", "content", "label", "value", "title"):
                    candidate = value.get(key)
                    if candidate is not None and str(candidate).strip():
                        text = str(candidate).strip()
                        break
                if not text:
                    text = " ".join(
                        str(candidate).strip()
                        for key, candidate in value.items()
                        if key not in {"item_id", "id", "icon_hint"} and str(candidate).strip()
                    )
            else:
                text = str(value).strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _build_asset_index(materials: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        existing_index = materials.get("asset_index", {})
        if existing_index:
            return existing_index

        asset_index: Dict[str, Dict[str, Any]] = {}
        for asset_number, asset in enumerate(materials.get("assets", []), start=1):
            category = asset.get("category", "asset")
            relative_path = asset.get("relative_path") or asset.get("path") or str(asset_number)
            normalized_relative_path = str(relative_path).replace("\\", "/")
            asset_id = asset.get("asset_id") or f"{category}:{normalized_relative_path}"
            normalized_asset = dict(asset)
            normalized_asset["asset_id"] = asset_id
            asset_index[asset_id] = normalized_asset

        for image_index, image_path in enumerate(materials.get("images", [])):
            asset_id = f"legacy_image:{image_index}"
            asset_index.setdefault(
                asset_id,
                {
                    "asset_id": asset_id,
                    "path": image_path,
                    "relative_path": image_path,
                    "category": "self",
                    "asset_kind": "image",
                },
            )
        return asset_index

    @staticmethod
    def _asset_id_from_image_index(image_index: int, asset_index: Dict[str, Dict[str, Any]]) -> str | None:
        if image_index is None:
            return None
        legacy_asset_id = f"legacy_image:{image_index}"
        if legacy_asset_id in asset_index:
            return legacy_asset_id
        image_assets = [asset for asset in asset_index.values() if asset.get("asset_kind") == "image"]
        if 0 <= image_index < len(image_assets):
            return image_assets[image_index]["asset_id"]
        return None

    @staticmethod
    def _infer_section_id(index: int, section_map: Dict[str, Dict[str, Any]]) -> str:
        if not section_map:
            return f"section_{index:02d}"
        section_ids = list(section_map.keys())
        return section_ids[min(index - 1, len(section_ids) - 1)]

    @staticmethod
    def _build_deck_id(title: str, markdown: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
        digest = md5(markdown[:500].encode("utf-8")).hexdigest()[:8]
        return f"{normalized or 'deck'}-{digest}"

    @staticmethod
    def _default_slot_for_block_kind(kind: str) -> str:
        slot_map = {
            "headline": "title",
            "summary": "body",
            "bullet_list": "body",
            "metric_strip": "metrics",
            "process": "body",
            "comparison": "body",
            "quote": "callout",
            "callout": "callout",
        }
        return slot_map.get(kind, "body")

    @staticmethod
    def _default_layout_slots(layout_name: str, slide_type: str) -> list[Dict[str, Any]]:
        templates: dict[str, list[Dict[str, Any]]] = {
            "hero": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.07, "w_ratio": 0.5, "h_ratio": 0.14, "content_types": ["headline"]},
                {"slot_id": "subtitle", "slot_role": "subtitle", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.19, "w_ratio": 0.42, "h_ratio": 0.09, "content_types": ["subtitle"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "left", "x_ratio": 0.06, "y_ratio": 0.31, "w_ratio": 0.4, "h_ratio": 0.45, "content_types": ["summary", "bullet_list", "callout"]},
                {"slot_id": "hero_visual", "slot_role": "hero_visual", "anchor": "right", "x_ratio": 0.52, "y_ratio": 0.12, "w_ratio": 0.42, "h_ratio": 0.68, "content_types": ["image", "figure"]},
            ],
            "section_divider": [
                {"slot_id": "title", "slot_role": "title", "anchor": "center", "x_ratio": 0.1, "y_ratio": 0.24, "w_ratio": 0.8, "h_ratio": 0.18, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.2, "y_ratio": 0.46, "w_ratio": 0.6, "h_ratio": 0.16, "content_types": ["summary"]},
            ],
            "two_column": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "left", "x_ratio": 0.06, "y_ratio": 0.23, "w_ratio": 0.42, "h_ratio": 0.62, "content_types": ["summary", "bullet_list", "process", "comparison"]},
                {"slot_id": "supporting_visual", "slot_role": "supporting_visual", "anchor": "right", "x_ratio": 0.54, "y_ratio": 0.23, "w_ratio": 0.38, "h_ratio": 0.56, "content_types": ["image", "chart", "table"]},
                {"slot_id": "callout", "slot_role": "callout", "anchor": "bottom_right", "x_ratio": 0.54, "y_ratio": 0.82, "w_ratio": 0.38, "h_ratio": 0.1, "content_types": ["callout", "quote"]},
            ],
            "three_column": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.06, "y_ratio": 0.24, "w_ratio": 0.88, "h_ratio": 0.58, "content_types": ["comparison", "bullet_list"]},
            ],
            "comparison": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.08, "y_ratio": 0.24, "w_ratio": 0.84, "h_ratio": 0.58, "content_types": ["comparison"]},
                {"slot_id": "callout", "slot_role": "callout", "anchor": "bottom", "x_ratio": 0.08, "y_ratio": 0.84, "w_ratio": 0.84, "h_ratio": 0.08, "content_types": ["summary", "callout"]},
            ],
            "metric_focus": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "metrics", "slot_role": "metrics", "anchor": "center", "x_ratio": 0.06, "y_ratio": 0.25, "w_ratio": 0.88, "h_ratio": 0.28, "content_types": ["metric_strip"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "bottom", "x_ratio": 0.1, "y_ratio": 0.58, "w_ratio": 0.8, "h_ratio": 0.22, "content_types": ["summary", "bullet_list"]},
            ],
            "timeline": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.08, "y_ratio": 0.28, "w_ratio": 0.84, "h_ratio": 0.4, "content_types": ["process"]},
                {"slot_id": "callout", "slot_role": "callout", "anchor": "bottom", "x_ratio": 0.1, "y_ratio": 0.75, "w_ratio": 0.8, "h_ratio": 0.12, "content_types": ["summary"]},
            ],
            "process_flow": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.08, "y_ratio": 0.24, "w_ratio": 0.84, "h_ratio": 0.42, "content_types": ["process"]},
                {"slot_id": "supporting_body", "slot_role": "supporting_body", "anchor": "bottom", "x_ratio": 0.1, "y_ratio": 0.7, "w_ratio": 0.8, "h_ratio": 0.16, "content_types": ["summary", "bullet_list"]},
            ],
            "image_focus": [
                {"slot_id": "hero_visual", "slot_role": "hero_visual", "anchor": "full", "x_ratio": 0.0, "y_ratio": 0.0, "w_ratio": 1.0, "h_ratio": 1.0, "content_types": ["image"]},
                {"slot_id": "title", "slot_role": "title", "anchor": "bottom_left", "x_ratio": 0.06, "y_ratio": 0.68, "w_ratio": 0.5, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "bottom_left", "x_ratio": 0.06, "y_ratio": 0.81, "w_ratio": 0.45, "h_ratio": 0.1, "content_types": ["summary", "callout"]},
            ],
            "quote_callout": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.08, "y_ratio": 0.1, "w_ratio": 0.8, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "callout", "slot_role": "callout", "anchor": "center", "x_ratio": 0.12, "y_ratio": 0.28, "w_ratio": 0.76, "h_ratio": 0.34, "content_types": ["quote", "callout"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "bottom", "x_ratio": 0.16, "y_ratio": 0.68, "w_ratio": 0.68, "h_ratio": 0.16, "content_types": ["summary"]},
            ],
            "table_focus": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.08, "y_ratio": 0.24, "w_ratio": 0.84, "h_ratio": 0.56, "content_types": ["table", "comparison"]},
            ],
            "chart_focus": [
                {"slot_id": "title", "slot_role": "title", "anchor": "top_left", "x_ratio": 0.06, "y_ratio": 0.06, "w_ratio": 0.88, "h_ratio": 0.12, "content_types": ["headline"]},
                {"slot_id": "supporting_visual", "slot_role": "supporting_visual", "anchor": "center", "x_ratio": 0.1, "y_ratio": 0.22, "w_ratio": 0.8, "h_ratio": 0.5, "content_types": ["chart"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "bottom", "x_ratio": 0.12, "y_ratio": 0.76, "w_ratio": 0.76, "h_ratio": 0.12, "content_types": ["summary", "bullet_list"]},
            ],
            "closing": [
                {"slot_id": "title", "slot_role": "title", "anchor": "center", "x_ratio": 0.1, "y_ratio": 0.22, "w_ratio": 0.8, "h_ratio": 0.14, "content_types": ["headline"]},
                {"slot_id": "body", "slot_role": "body", "anchor": "center", "x_ratio": 0.18, "y_ratio": 0.42, "w_ratio": 0.64, "h_ratio": 0.18, "content_types": ["summary", "bullet_list"]},
                {"slot_id": "callout", "slot_role": "callout", "anchor": "bottom", "x_ratio": 0.28, "y_ratio": 0.72, "w_ratio": 0.44, "h_ratio": 0.1, "content_types": ["callout"]},
            ],
        }
        if slide_type == "section":
            return templates["section_divider"]
        return templates.get(layout_name, templates["two_column"])

    @staticmethod
    def _normalize_slide_type(raw_type: Any, *, index: int = 1) -> str:
        normalized = str(raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "cover": "title",
            "opening": "title",
            "opening_slide": "title",
            "intro": "title",
            "introduction": "title",
            "lead": "title",
            "section_divider": "section",
            "divider": "section",
            "body": "content",
            "main": "content",
            "summary": "closing",
            "takeaway": "closing",
            "takeaways": "closing",
            "ending": "closing",
            "end": "closing",
            "outro": "closing",
            "conclusion": "closing",
            "concluding": "closing",
            "thankyou": "closing",
            "thank_you": "closing",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized in {"title", "section", "content", "closing"}:
            return normalized
        return "title" if index == 1 else "content"

    @staticmethod
    def _normalize_slot_role(raw_role: Any) -> str:
        normalized = str(raw_role or "").strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "heading": "title",
            "headline": "title",
            "subheading": "subtitle",
            "sub_title": "subtitle",
            "text": "body",
            "content": "body",
            "main_body": "body",
            "secondary_body": "supporting_body",
            "support_body": "supporting_body",
            "visual": "supporting_visual",
            "image": "supporting_visual",
            "figure": "supporting_visual",
            "graphic": "supporting_visual",
            "diagram": "supporting_visual",
            "chart": "supporting_visual",
            "illustration": "supporting_visual",
            "background_visual": "hero_visual",
            "background_image": "hero_visual",
            "full_bleed_visual": "hero_visual",
            "hero_image": "hero_visual",
            "metric": "metrics",
            "stats": "metrics",
            "annotation": "callout",
            "caption": "footer",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized in {
            "title",
            "subtitle",
            "body",
            "supporting_body",
            "hero_visual",
            "supporting_visual",
            "metrics",
            "callout",
            "footer",
        }:
            return normalized
        return "body"

    @staticmethod
    def _normalize_slot_anchor(raw_anchor: Any) -> str:
        normalized = str(raw_anchor or "").strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "full_bleed": "full",
            "middle": "center",
            "upper_left": "top_left",
            "upper_right": "top_right",
            "lower_left": "bottom_left",
            "lower_right": "bottom_right",
            "top_center": "top",
            "bottom_center": "bottom",
            "left_center": "left",
            "right_center": "right",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized in {
            "full",
            "top",
            "bottom",
            "left",
            "right",
            "center",
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
        }:
            return normalized
        return "center"

    @staticmethod
    def _normalize_block_kind(raw_kind: Any) -> str:
        normalized = str(raw_kind or "").strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "title": "headline",
            "heading": "headline",
            "subheading": "summary",
            "subtitle": "summary",
            "text": "summary",
            "paragraph": "summary",
            "bullets": "bullet_list",
            "bullet_points": "bullet_list",
            "list": "bullet_list",
            "key_points": "bullet_list",
            "metrics": "metric_strip",
            "stats": "metric_strip",
            "timeline": "process",
            "flow": "process",
            "workflow": "process",
            "steps": "process",
            "compare": "comparison",
            "table": "comparison",
            "quotation": "quote",
            "highlight": "callout",
            "note": "callout",
            "annotation": "callout",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized in {
            "headline",
            "summary",
            "bullet_list",
            "metric_strip",
            "process",
            "comparison",
            "quote",
            "callout",
        }:
            return normalized
        return "bullet_list"

    def _get_language_instruction(self) -> str:
        """Get language-specific instruction based on language_mode."""
        if self.language_mode == "chinese":
            return "所有自然语言字段必须使用中文。"
        else:
            return "All natural-language fields must be in English by default."

    def _get_complexity_instruction(self) -> str:
        """Get complexity-specific instruction based on complexity_level."""
        if self._model_profile() == "qwen":
            if self.complexity_level == "simple":
                return "qwen simple：对应旧 balanced 档；每页3-4个内容点，使用清晰的 title/body/visual 结构，视觉元素适度。"
            if self.complexity_level == "complex":
                return (
                    "qwen true complex：每页5-6个信息原子，layout.density 优先使用 dense；"
                    "必须至少选择一种结构关系：evidence、mechanism、comparison、process、metrics、takeaway；"
                    "如果本页有关键视觉素材，采用 visual-led：大图承载主要结构，文本只保留2-3个解释/证据/takeaway区域；"
                    "无关键视觉时采用 text-led，再规划4-6个语义区域。保持 source_evidence 可追溯，避免新增事实。"
                )
            return "qwen balanced：对应旧 complex 档；每页4-5个内容点，支持更复杂的结构化布局和视觉元素。"
        if self.complexity_level == "simple":
            return "设计风格：简洁明了，每张幻灯片内容点不超过3个，布局简单清晰。"
        elif self.complexity_level == "complex":
            return "设计风格：详细深入，每张幻灯片可包含4-5个内容点，支持复杂的布局和视觉元素。"
        else:  # balanced
            return "设计风格：平衡适中，每张幻灯片包含3-4个内容点，布局和视觉元素适度。"

    @staticmethod
    def _model_dump(model: Any) -> Dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
