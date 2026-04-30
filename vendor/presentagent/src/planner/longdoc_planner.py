"""Long-document planning workflow that produces deck-level slide briefs."""

from __future__ import annotations

import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import md5
from pathlib import Path
from typing import Any

from ..llm.client import LLMClient
from .ir_schema import ContentChunk, IRMetadata, LongDocProfile, SlideBrief, SlideBriefDeck, StorySection, Storyline


class LongDocPlanner:
    """Plan long markdown documents into a deck-scoped slide_briefs container."""

    def __init__(
        self,
        client: LLMClient,
        *,
        chunk_char_limit: int = 6000,
        overlap_chars: int = 400,
        max_workers: int = 4,
        language_mode: str = "english",
        complexity_level: str = "balanced",
    ) -> None:
        self.client = client
        self.chunk_char_limit = chunk_char_limit
        self.overlap_chars = overlap_chars
        self.max_workers = max_workers
        self.language_mode = language_mode.lower()
        self.complexity_level = complexity_level.lower()

    def build_slide_briefs(
        self,
        markdown: str,
        target_slide_count: int | None = None,
        progress_callback=None,
    ) -> dict[str, Any]:
        profile = self._build_profile(markdown, target_slide_count=target_slide_count)
        chunks = self._chunk_markdown(markdown, profile)
        profile.chunk_count = len(chunks)
        chunk_budgets = self._allocate_chunk_budgets(chunks, profile.target_slide_count)
        chunk_outputs = self._plan_chunks(
            chunks,
            chunk_budgets,
            markdown,
            progress_callback=progress_callback,
        )

        # Collect all briefs from chunks
        all_briefs = []
        for chunk in chunk_outputs:
            all_briefs.extend(chunk.get("slide_briefs", []))

        # Get deck metadata and brief organization from LLM
        reconciled = self._reconcile_briefs(
            chunk_outputs,
            profile,
            markdown,
            progress_callback=progress_callback,
        )

        merged_briefs = []
        for brief in all_briefs:
            brief_id = brief.get("brief_id")
            metadata = next(
                (
                    item
                    for item in reconciled.get("brief_metadata", [])
                    if item.get("brief_id") == brief_id
                ),
                {},
            )
            merged = {**brief, **metadata}
            merged_briefs.append(merged)

        storyline_hint = self._normalize_storyline(reconciled.get("storyline_hint", {}))
        slide_briefs = self._normalize_slide_briefs(merged_briefs, chunks)
        title_hint = reconciled.get("title_hint", "") or self._first_heading(markdown) or "Untitled Deck"
        subtitle_hint = reconciled.get("subtitle_hint", "")

        deck = SlideBriefDeck(
            metadata=IRMetadata(
                schema_name="presentagent.slide_briefs",
                deck_id=self._build_deck_id(title_hint, markdown),
                stage="planned",
            ),
            title_hint=title_hint,
            subtitle_hint=subtitle_hint,
            storyline_hint=Storyline(**storyline_hint),
            longdoc_profile=profile,
            chunks=[ContentChunk(**self._model_dump(chunk)) for chunk in chunks],
            slide_briefs=[SlideBrief(**brief) for brief in slide_briefs],
            planner_notes=self._normalize_string_list(reconciled.get("planner_notes", [])),
        )
        return self._model_dump(deck)

    def _build_profile(self, markdown: str, target_slide_count: int | None = None) -> LongDocProfile:
        markdown_chars = len(markdown)
        heading_count = len(re.findall(r"(?m)^#{1,3}\s+", markdown))
        section_count = len(re.findall(r"(?m)^#{1,2}\s+", markdown))
        estimated_source_pages = max(1, math.ceil(markdown_chars / 2800))
        base_slide_count = max(6, math.ceil(markdown_chars / 2200))
        heading_bonus = min(6, max(section_count - 2, 0))
        computed_target_slide_count = min(24, max(base_slide_count, estimated_source_pages // 2 + 4, 6 + heading_bonus))
        requested_target_slide_count = target_slide_count if target_slide_count and target_slide_count > 0 else None
        final_target_slide_count = (
            min(computed_target_slide_count, requested_target_slide_count)
            if requested_target_slide_count is not None
            else computed_target_slide_count
        )
        is_long_document = markdown_chars > 9000 or section_count >= 6 or estimated_source_pages >= 10

        notes = [
            f"Estimated {estimated_source_pages} source pages from markdown length.",
            "Budget slides before formal IR generation.",
            "Chunk by heading structure plus character limit with light overlap.",
        ]
        if requested_target_slide_count is not None:
            notes.append(f"Target slide count capped to {final_target_slide_count} before chunk planning.")
        return LongDocProfile(
            is_long_document=is_long_document,
            markdown_chars=markdown_chars,
            heading_count=heading_count,
            section_count=section_count,
            estimated_source_pages=estimated_source_pages,
            target_slide_count=final_target_slide_count,
            chunk_count=1,
            chunk_strategy="heading_plus_chars",
            chunk_char_limit=self.chunk_char_limit,
            overlap_chars=self.overlap_chars,
            notes=notes,
        )

    def _chunk_markdown(self, markdown: str, profile: LongDocProfile) -> list[ContentChunk]:
        segments = self._split_into_segments(markdown)
        if not segments:
            return [
                ContentChunk(
                    chunk_id="chunk_01",
                    ordinal=1,
                    heading_path=[],
                    section_title="Document",
                    start_offset=0,
                    end_offset=len(markdown),
                    char_count=len(markdown),
                    overlap_from_previous=0,
                    text=markdown,
                )
            ]

        raw_chunks: list[dict[str, Any]] = []
        current_segments: list[dict[str, Any]] = []
        current_chars = 0

        for segment in segments:
            segment_len = len(segment["text"])
            if segment_len > self.chunk_char_limit:
                if current_segments:
                    raw_chunks.append(self._build_raw_chunk(current_segments))
                    current_segments = []
                    current_chars = 0
                split_segments = self._split_large_segment(segment)
                for split_segment in split_segments:
                    if len(split_segment["text"]) >= self.chunk_char_limit:
                        raw_chunks.append(self._build_raw_chunk([split_segment]))
                    else:
                        current_segments = [split_segment]
                        current_chars = len(split_segment["text"])
                continue

            if current_segments and current_chars + segment_len > self.chunk_char_limit:
                raw_chunks.append(self._build_raw_chunk(current_segments))
                current_segments = [segment]
                current_chars = segment_len
            else:
                current_segments.append(segment)
                current_chars += segment_len

        if current_segments:
            raw_chunks.append(self._build_raw_chunk(current_segments))

        chunks: list[ContentChunk] = []
        previous_body = ""
        for index, chunk in enumerate(raw_chunks, start=1):
            overlap = previous_body[-self.overlap_chars :] if previous_body and self.overlap_chars > 0 else ""
            planning_text = overlap + chunk["text"]
            chunk_model = ContentChunk(
                chunk_id=f"chunk_{index:02d}",
                ordinal=index,
                heading_path=chunk["heading_path"],
                section_title=chunk["section_title"],
                start_offset=chunk["start_offset"],
                end_offset=chunk["end_offset"],
                char_count=len(planning_text),
                overlap_from_previous=len(overlap),
                text=planning_text,
            )
            chunks.append(chunk_model)
            previous_body = chunk["text"]
        return chunks

    def _plan_chunks(
        self,
        chunks: list[ContentChunk],
        chunk_budgets: list[int],
        markdown: str,
        progress_callback=None,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        max_workers = min(max(self.max_workers, 1), len(chunks))
        if max_workers == 1:
            results = []
            for index, (chunk, budget) in enumerate(zip(chunks, chunk_budgets), start=1):
                results.append(self._plan_single_chunk(chunk, budget, markdown))
                if progress_callback is not None:
                    progress_callback(index, len(chunks) + 1, f"chunk {chunk.chunk_id}")
            return results

        results: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._plan_single_chunk, chunk, budget, markdown): idx
                for idx, (chunk, budget) in enumerate(zip(chunks, chunk_budgets))
            }
            for future in as_completed(future_map):
                index = future_map[future]
                results[index] = future.result()
                if progress_callback is not None:
                    progress_callback(len(results), len(chunks) + 1, f"chunk {chunks[index].chunk_id}")
        return [results[index] for index in range(len(chunks))]

    def _plan_single_chunk(
        self,
        chunk: ContentChunk,
        chunk_budget: int,
        markdown: str,
    ) -> dict[str, Any]:
        base_prompt = self._build_chunk_prompt(chunk, chunk_budget, markdown)
        last_error: Exception | None = None
        target_briefs = self._step1_target_briefs(chunk_budget)
        minimum_briefs = max(1, math.ceil(target_briefs * 0.6))
        retry_suffixes = [
            "",
            (
                "\n\nYour previous output was not strictly valid JSON. Return one compact JSON object only. "
                "Start with `{` and end with `}`. Do not include markdown fences, explanations, or decorative punctuation."
            ),
            (
                f"\n\nCritical retry: you returned too few slide briefs for the assigned budget. "
                f"Return at least {minimum_briefs} distinct `slide_briefs` entries unless the chunk truly contains less than {minimum_briefs} non-overlapping ideas. "
                "Return a MINIMAL JSON object only. "
                "Produce exactly this skeleton schema and keep all strings short. "
                "Each brief must include exactly 1 short `title` and 1 short `core_message`."
            ),
        ]
        for attempt, retry_suffix in enumerate(retry_suffixes):
            prompt = base_prompt
            if retry_suffix:
                prompt += retry_suffix
            response = self.client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format="json",
            )
            try:
                parsed = self._parse_chunk_plan_response(response, chunk.chunk_id)
                brief_count = len(parsed.get("slide_briefs", []) or [])
                if brief_count < minimum_briefs and attempt < len(retry_suffixes) - 1:
                    last_error = RuntimeError(
                        f"Too few slide briefs for {chunk.chunk_id}: expected at least {minimum_briefs}, got {brief_count}"
                    )
                    continue
                parsed["slide_briefs"] = self._enrich_chunk_briefs(chunk, parsed.get("slide_briefs", []))
                return parsed
            except RuntimeError as exc:
                last_error = exc
        raise RuntimeError(f"Chunk slide_briefs planning failed for {chunk.chunk_id}: {last_error}")

    def _enrich_chunk_briefs(self, chunk: ContentChunk, slide_briefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not slide_briefs:
            return []

        point_limit = self._step1_content_point_limit()
        excerpt_limit = self._step1_excerpt_char_limit()
        detail_prompt = self._build_chunk_detail_prompt(
            chunk,
            slide_briefs,
            point_limit=point_limit,
            excerpt_limit=excerpt_limit,
        )

        detail_map: dict[str, dict[str, Any]] = {}
        try:
            response = self.client.chat(
                [{"role": "user", "content": detail_prompt}],
                temperature=0.0,
                response_format="json",
            )
            detail_map = self._parse_chunk_detail_response(response)
        except RuntimeError:
            detail_map = {}

        enriched: list[dict[str, Any]] = []
        for brief in slide_briefs:
            detail = detail_map.get(brief.get("brief_id", ""), {})
            content_points = self._normalize_content_points(
                detail.get("content_points", []),
                point_limit=point_limit,
            )
            if not content_points:
                content_points = self._fallback_content_points(brief, point_limit=point_limit)

            source_excerpt = str(detail.get("source_excerpt", "")).strip()
            if len(source_excerpt) > excerpt_limit:
                source_excerpt = source_excerpt[: excerpt_limit - 3].rstrip() + "..."

            enriched.append(
                {
                    **brief,
                    "content_points": content_points,
                    "source_excerpt": source_excerpt,
                }
            )

        return enriched

    def _reconcile_briefs(
        self,
        chunk_outputs: list[dict[str, Any]],
        profile: LongDocProfile,
        markdown: str,
        progress_callback=None,
    ) -> dict[str, Any]:
        """Generate deck-level metadata and brief organization."""
        # Collect all briefs
        all_briefs = []
        for chunk in chunk_outputs:
            all_briefs.extend(chunk.get("slide_briefs", []))

        # Call LLM to generate metadata and brief organization
        prompt = self._build_reconcile_prompt(all_briefs, profile, markdown)
        response = self.client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format="json",
        )

        try:
            result = self._extract_json(response)
            if progress_callback is not None:
                progress_callback(profile.chunk_count + 1, profile.chunk_count + 1, "reconcile briefs")
            return result
        except RuntimeError as exc:
            raise RuntimeError(f"Slide brief reconciliation failed: {exc}")


    def _build_chunk_prompt(
        self,
        chunk: ContentChunk,
        chunk_budget: int,
        markdown: str,
    ) -> str:
        target_briefs = self._step1_target_briefs(chunk_budget)
        section_hint = " > ".join(chunk.heading_path) if chunk.heading_path else chunk.section_title or "Document"

        # Language instruction
        language_instruction = self._get_language_instruction()

        # Complexity instruction
        complexity_instruction = self._get_complexity_instruction()
        slide_cap_instruction = (
            f"8. 严格服从本块页数预算，优先生成 {target_briefs} 条摘要；如内容相近必须合并，不能为了凑页数过度拆分。"
            if self.language_mode == "chinese"
            else f"8. Treat the chunk budget as a hard cap: aim for {target_briefs} briefs and merge adjacent ideas instead of oversplitting."
        )
        if self._model_profile() == "qwen":
            slide_cap_instruction += (
                "\n9. Qwen本地模式下必须优先合并相近观点，宁可少一条，也不要输出边界模糊或过长的摘要。"
                if self.language_mode == "chinese"
                else "\n9. In qwen mode, aggressively merge adjacent ideas; it is better to return fewer, cleaner briefs than borderline duplicates."
            )
        elif self._model_profile() == "claude":
            slide_cap_instruction += (
                "\n9. Claude模式下优先保持 JSON 结构稳定：宁可略少，也不要把多个相近观点拆成边界模糊的摘要。"
                if self.language_mode == "chinese"
                else "\n9. In claude mode, prioritize JSON stability over granularity: it is better to return slightly fewer, cleaner briefs than borderline splits."
            )

        if self.language_mode == "chinese":
            return f"""你是一个长文档演示文稿规划师。从这个文档块中提取内容摘要。

目标：
1. 输入是长文档中的一个 markdown 块。
2. 输出一批内容摘要骨架，每个摘要代表一张幻灯片的核心内容。
3. 每个摘要骨架必须包含恰好一个 `title` 和一个 `core_message`（核心信息）。
4. 在这批中优先生成 {target_briefs} 个摘要骨架。
5. 每个摘要骨架必须保留可追溯的证据字段：`source_chunk_ids`、`source_headings`。
{language_instruction}
{complexity_instruction}
{slide_cap_instruction}

块元数据：
- chunk_id: {chunk.chunk_id}
- heading_path: {section_hint}
- overlap_from_previous: {chunk.overlap_from_previous}

	文档级摘要：
	{markdown[:1400]}

	当前块内容：
	{chunk.text[:3600]}

仅返回 JSON，格式如下：
{{
  "chunk_id": "{chunk.chunk_id}",
  "slide_briefs": [
    {{
      "brief_id": "{chunk.chunk_id}_brief_01",
      "title": "简短标题",
      "core_message": "这张幻灯片的核心信息",
      "source_chunk_ids": ["{chunk.chunk_id}"],
      "source_headings": {json.dumps(chunk.heading_path, ensure_ascii=False)}
    }}
  ]
}}"""
        else:
            return f"""You are a long-document presentation planner. Extract content briefs from this chunk.

Goals:
1. The input is one markdown chunk from a long document.
2. Output one batch of brief skeletons, where each brief represents one slide's core content.
3. Every brief skeleton must contain exactly one short `title` and one short `core_message`.
4. Generate about {target_briefs} brief skeletons in this batch.
5. Every brief skeleton must keep traceable evidence fields: `source_chunk_ids`, `source_headings`.
{language_instruction}
{complexity_instruction}
{slide_cap_instruction}

Chunk metadata:
- chunk_id: {chunk.chunk_id}
- heading_path: {section_hint}
- overlap_from_previous: {chunk.overlap_from_previous}

Document-level summary:
{markdown[:1400]}

Current chunk content:
{chunk.text[:3600]}

Return JSON only, in this format:
{{
  "chunk_id": "{chunk.chunk_id}",
  "slide_briefs": [
    {{
      "brief_id": "{chunk.chunk_id}_brief_01",
      "title": "Short title",
      "core_message": "The one core message of this slide",
      "source_chunk_ids": ["{chunk.chunk_id}"],
      "source_headings": {json.dumps(chunk.heading_path, ensure_ascii=False)}
    }}
  ]
}}"""

    def _build_chunk_detail_prompt(
        self,
        chunk: ContentChunk,
        slide_briefs: list[dict[str, Any]],
        *,
        point_limit: int,
        excerpt_limit: int,
    ) -> str:
        if self.language_mode == "chinese":
            return f"""你正在补全一组演示文稿摘要骨架。

目标：
1. 对下面每个 brief_id 补全简短 `content_points` 和简短 `source_excerpt`。
2. 每个 brief 最多返回 {point_limit} 条 `content_points`，每条必须尽量短。
3. 每个 `source_excerpt` 必须尽量短，不超过 {excerpt_limit} 个字符。
4. 不要重复 `title` 或 `core_message` 原句，不要写成长段摘要。
5. 只返回与输入 brief_id 一一对应的结果，不要新增 brief。
6. 若不确定，优先返回更短的字符串；字段缺失时返回空数组或空字符串。

摘要骨架：
{json.dumps(slide_briefs, ensure_ascii=False, indent=2)}

原始块内容：
{chunk.text[:2200]}

仅返回 JSON：
{{
  "brief_details": [
    {{
      "brief_id": "{slide_briefs[0].get('brief_id', f'{chunk.chunk_id}_brief_01')}",
      "content_points": ["要点 1", "要点 2"],
      "source_excerpt": "最相关的短摘录"
    }}
  ]
}}"""

        return f"""You are filling in a batch of presentation brief skeletons.

Goals:
1. For each brief_id below, return short `content_points` and a short `source_excerpt`.
2. Return at most {point_limit} content points per brief, each kept short.
3. Keep every `source_excerpt` within {excerpt_limit} characters.
4. Do not repeat the `title` or `core_message` verbatim and do not add extra briefs.
5. If unsure, prefer shorter strings; use empty arrays or empty strings instead of explanatory text.

Brief skeletons:
{json.dumps(slide_briefs, ensure_ascii=False, indent=2)}

Source chunk:
{chunk.text[:2200]}

Return JSON only:
{{
  "brief_details": [
    {{
      "brief_id": "{slide_briefs[0].get('brief_id', f'{chunk.chunk_id}_brief_01')}",
      "content_points": ["Point 1", "Point 2"],
      "source_excerpt": "Most relevant short excerpt"
    }}
  ]
}}"""

    def _build_reconcile_prompt(
        self,
        all_briefs: list[dict[str, Any]],
        profile: LongDocProfile,
        markdown: str,
    ) -> str:
        serialized_briefs = json.dumps(all_briefs, ensure_ascii=False, indent=2)

        language_instruction = self._get_language_instruction()
        complexity_instruction = self._get_complexity_instruction()
        cap_instruction = (
            f"硬性约束：最终 `brief_metadata` 数量不得超过 {profile.target_slide_count} 条；如果摘要过多，必须合并相近主题。"
            if self.language_mode == "chinese"
            else f"Hard cap: return no more than {profile.target_slide_count} `brief_metadata` entries; merge overlapping briefs when needed."
        )

        if self.language_mode == "chinese":
            return f"""你是一个演示文稿规划师。根据内容摘要，生成演示文稿结构和元数据。

输入：来自文档的 {len(all_briefs)} 个内容摘要。

任务：
1. 将摘要组织成逻辑章节
2. 为每个摘要分配章节并确定幻灯片类型（标题/内容/结尾）
3. 生成幻灯片标题和目标
4. 创建演示文稿级元数据
{language_instruction}
{complexity_instruction}

目标幻灯片数量：{profile.target_slide_count}
{cap_instruction}

内容摘要：
{serialized_briefs[:8000]}

返回 JSON：
{{
  "title_hint": "演示文稿标题",
  "subtitle_hint": "演示文稿副标题",
  "storyline_hint": {{
    "topic": "主题",
    "audience": "目标受众",
    "presentation_goal": "演示目标",
    "tone": "语气",
    "sections": [
      {{"id": "section_01", "title": "章节标题", "objective": "章节目标"}}
    ]
  }},
  "planner_notes": ["备注 1"],
  "brief_metadata": [
    {{
      "brief_id": "chunk_01_brief_01",
      "type": "title",
      "section_id": "section_01",
      "section_title": "开场",
      "title": "幻灯片标题",
      "objective": "幻灯片目标"
    }}
  ]
}}"""
        else:
            return f"""You are a deck planner. Given content briefs, generate deck structure and metadata.

Input: {len(all_briefs)} content briefs from a document.

Tasks:
1. Organize briefs into logical sections
2. Assign each brief to a section and determine slide type (title/content/closing)
3. Generate slide titles and objectives
4. Create deck-level metadata
{language_instruction}
{complexity_instruction}

Target slide count: {profile.target_slide_count}
{cap_instruction}

Content briefs:
{serialized_briefs[:8000]}

Return JSON:
{{
  "title_hint": "Deck title",
  "subtitle_hint": "Deck subtitle",
  "storyline_hint": {{
    "topic": "Main topic",
    "audience": "Target audience",
    "presentation_goal": "Goal",
    "tone": "Tone",
    "sections": [
      {{"id": "section_01", "title": "Section title", "objective": "Section objective"}}
    ]
  }},
  "planner_notes": ["Note 1"],
  "brief_metadata": [
    {{
      "brief_id": "chunk_01_brief_01",
      "type": "title",
      "section_id": "section_01",
      "section_title": "Opening",
      "title": "Slide title",
      "objective": "Slide objective"
    }}
  ]
}}"""


    @staticmethod
    def _split_into_segments(markdown: str) -> list[dict[str, Any]]:
        lines = markdown.splitlines(keepends=True)
        if not lines:
            return []

        heading_path: list[str] = []
        buffer: list[str] = []
        segments: list[dict[str, Any]] = []
        char_cursor = 0

        def flush_buffer(current_heading_path: list[str], start_offset: int, end_offset: int) -> None:
            text = "".join(buffer).strip()
            if not text:
                return
            section_title = current_heading_path[-1] if current_heading_path else "Document"
            segments.append(
                {
                    "heading_path": list(current_heading_path),
                    "section_title": section_title,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "text": text,
                }
            )

        current_start = 0
        for line in lines:
            heading_match = re.match(r"^(#{1,3})\s+(.*)$", line.strip())
            if heading_match and buffer:
                flush_buffer(heading_path, current_start, char_cursor)
                buffer = []
                current_start = char_cursor

            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_path = heading_path[: level - 1] + [title]

            if not buffer:
                current_start = char_cursor
            buffer.append(line)
            char_cursor += len(line)

        if buffer:
            flush_buffer(heading_path, current_start, char_cursor)
        return segments

    def _split_large_segment(self, segment: dict[str, Any]) -> list[dict[str, Any]]:
        paragraphs = re.split(r"\n\s*\n", segment["text"])
        chunks: list[dict[str, Any]] = []
        current_parts: list[str] = []
        current_chars = 0
        start_offset = segment["start_offset"]
        running_offset = segment["start_offset"]

        def flush_parts(parts: list[str], part_start: int, part_end: int) -> None:
            text = "\n\n".join(parts).strip()
            if not text:
                return
            chunks.append(
                {
                    "heading_path": list(segment["heading_path"]),
                    "section_title": segment["section_title"],
                    "start_offset": part_start,
                    "end_offset": part_end,
                    "text": text,
                }
            )

        for paragraph in paragraphs:
            paragraph_text = paragraph.strip()
            if not paragraph_text:
                continue
            paragraph_len = len(paragraph_text) + 2
            if current_parts and current_chars + paragraph_len > self.chunk_char_limit:
                flush_parts(current_parts, start_offset, running_offset)
                current_parts = [paragraph_text]
                start_offset = running_offset
                current_chars = paragraph_len
            else:
                current_parts.append(paragraph_text)
                current_chars += paragraph_len
            running_offset += paragraph_len

        if current_parts:
            flush_parts(current_parts, start_offset, running_offset)
        return chunks or [segment]

    @staticmethod
    def _build_raw_chunk(segments: list[dict[str, Any]]) -> dict[str, Any]:
        text = "\n\n".join(segment["text"] for segment in segments).strip()
        heading_path = segments[0]["heading_path"] if segments else []
        section_title = segments[0]["section_title"] if segments else "Document"
        return {
            "heading_path": heading_path,
            "section_title": section_title,
            "start_offset": segments[0]["start_offset"] if segments else 0,
            "end_offset": segments[-1]["end_offset"] if segments else 0,
            "text": text,
        }

    @staticmethod
    def _allocate_chunk_budgets(chunks: list[ContentChunk], target_slide_count: int) -> list[int]:
        if not chunks:
            return []
        weights = [max(chunk.char_count - chunk.overlap_from_previous, 1) for chunk in chunks]
        total_weight = sum(weights)
        budgets = [max(1, round(target_slide_count * weight / total_weight)) for weight in weights]

        while sum(budgets) < target_slide_count:
            index = max(range(len(budgets)), key=lambda idx: weights[idx] / budgets[idx])
            budgets[index] += 1
        while sum(budgets) > target_slide_count:
            candidates = [idx for idx, budget in enumerate(budgets) if budget > 1]
            if not candidates:
                break
            index = min(candidates, key=lambda idx: weights[idx] / budgets[idx])
            budgets[index] -= 1
        return budgets

    @staticmethod
    def _normalize_slide_briefs(raw_briefs: list[dict[str, Any]], chunks: list[ContentChunk]) -> list[dict[str, Any]]:
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
        normalized: list[dict[str, Any]] = []
        for index, brief in enumerate(raw_briefs, start=1):
            source_chunk_ids = LongDocPlanner._normalize_string_list(brief.get("source_chunk_ids", []))
            section_id = brief.get("section_id") or f"section_{index:02d}"
            section_title = brief.get("section_title", "")
            source_headings = LongDocPlanner._normalize_string_list(brief.get("source_headings", []))
            if not source_headings and source_chunk_ids:
                for chunk_id in source_chunk_ids:
                    chunk = chunk_map.get(chunk_id)
                    if chunk:
                        source_headings.extend(chunk.heading_path)
            source_excerpt = brief.get("source_excerpt", "")
            if not source_excerpt:
                source_excerpt = LongDocPlanner._derive_source_excerpt(
                    brief,
                    [chunk_map[chunk_id] for chunk_id in source_chunk_ids if chunk_id in chunk_map],
                )
            slide_type = LongDocPlanner._normalize_slide_type(brief.get("type"), index=index)
            normalized.append(
                LongDocPlanner._model_dump(
                    SlideBrief(
                        brief_id=brief.get("brief_id") or f"brief_{index:02d}",
                        slide_id=brief.get("slide_id") or f"slide_{index:02d}",
                        type=slide_type,
                        section_id=section_id,
                        section_title=section_title,
                        title=brief.get("title") or brief.get("core_message") or f"Slide {index}",
                        core_message=brief.get("core_message") or brief.get("title") or f"Slide {index}",
                        objective=brief.get("objective", ""),
                        content_points=LongDocPlanner._normalize_string_list(brief.get("content_points", [])),
                        visual_intent=brief.get("visual_intent", ""),
                        suggested_visual_kind=brief.get("suggested_visual_kind", ""),
                        recommended_layouts=LongDocPlanner._normalize_string_list(
                            brief.get("recommended_layouts", [])
                        ),
                        source_chunk_ids=source_chunk_ids,
                        source_headings=source_headings,
                        source_excerpt=source_excerpt,
                        priority=int(brief.get("priority", 50)),
                    )
                )
            )
        return normalized

    def _step1_content_point_limit(self) -> int:
        profile = self._model_profile()
        if profile == "qwen":
            if self.complexity_level == "complex":
                return 6
            if self.complexity_level == "balanced":
                return 4
            return 3
        if profile == "claude":
            return 3
        return 4

    def _step1_excerpt_char_limit(self) -> int:
        profile = self._model_profile()
        if profile == "qwen":
            if self.complexity_level == "complex":
                return 220
            if self.complexity_level == "balanced":
                return 140
            return 90
        if profile == "claude":
            return 80
        return 140

    def _step1_target_briefs(self, chunk_budget: int) -> int:
        target = max(1, chunk_budget)
        profile = self._model_profile()
        if profile == "qwen":
            if self.complexity_level == "complex":
                return min(target, 4)
            return min(target, 3)
        if profile == "claude":
            return min(target, 2)
        return target

    def _model_profile(self) -> str:
        return getattr(self.client, "model_profile", "general")

    @staticmethod
    def _normalize_content_points(raw_points: list[str], *, point_limit: int) -> list[str]:
        normalized = LongDocPlanner._normalize_string_list(raw_points)
        compact: list[str] = []
        for point in normalized:
            shortened = point.strip().replace("\n", " ")
            if len(shortened) > 120:
                shortened = shortened[:117].rstrip() + "..."
            if shortened:
                compact.append(shortened)
            if len(compact) >= point_limit:
                break
        return compact

    @staticmethod
    def _fallback_content_points(brief: dict[str, Any], *, point_limit: int) -> list[str]:
        candidates = LongDocPlanner._normalize_string_list(brief.get("content_points", []))
        if not candidates:
            core = str(brief.get("core_message", "")).strip()
            candidates = [core] if core else []
        return LongDocPlanner._normalize_content_points(candidates, point_limit=point_limit)

    def _parse_chunk_detail_response(self, response: str) -> dict[str, dict[str, Any]]:
        parsed = self._extract_json(response)
        details = parsed.get("brief_details", [])
        detail_map: dict[str, dict[str, Any]] = {}
        if not isinstance(details, list):
            return detail_map
        for item in details:
            if not isinstance(item, dict):
                continue
            brief_id = str(item.get("brief_id", "")).strip()
            if not brief_id:
                continue
            detail_map[brief_id] = item
        return detail_map

    @staticmethod
    def _derive_source_excerpt(brief: dict[str, Any], chunks: list[ContentChunk]) -> str:
        if not chunks:
            return ""

        search_terms = [
            str(brief.get("core_message", "")).strip(),
            *LongDocPlanner._normalize_string_list(brief.get("content_points", [])),
            str(brief.get("title", "")).strip(),
        ]
        search_terms = [term for term in search_terms if len(term) >= 8]

        for chunk in chunks:
            excerpt = LongDocPlanner._match_excerpt_from_chunk(chunk.text, search_terms)
            if excerpt:
                return excerpt

        fallback = " ".join(chunks[0].text.split())
        return fallback[:220].strip()

    @staticmethod
    def _match_excerpt_from_chunk(chunk_text: str, search_terms: list[str]) -> str:
        compact_text = " ".join(chunk_text.split())
        lowered_text = compact_text.lower()
        for term in search_terms:
            normalized_term = " ".join(term.split())
            if not normalized_term:
                continue
            needle = normalized_term.lower().replace("'", "").replace('"', "")
            haystack = lowered_text.replace("'", "").replace('"', "")
            index = haystack.find(needle)
            if index == -1:
                continue
            start = max(0, index - 40)
            end = min(len(compact_text), index + len(normalized_term) + 120)
            return compact_text[start:end].strip()
        return ""

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
    def _normalize_storyline(raw_storyline: dict[str, Any]) -> dict[str, Any]:
        sections = []
        for index, section in enumerate(raw_storyline.get("sections", []), start=1):
            sections.append(
                StorySection(
                    id=section.get("id") or f"section_{index:02d}",
                    title=section.get("title") or f"Section {index}",
                    objective=section.get("objective", ""),
                )
            )
        storyline = Storyline(
            topic=raw_storyline.get("topic", ""),
            audience=raw_storyline.get("audience", "general"),
            presentation_goal=raw_storyline.get("presentation_goal", ""),
            tone=raw_storyline.get("tone", "analytical"),
            sections=sections,
        )
        return LongDocPlanner._model_dump(storyline)

    @staticmethod
    def _normalize_chunk_plan_payload(payload: dict[str, Any], chunk_id: str) -> dict[str, Any]:
        if isinstance(payload.get("slide_briefs"), list):
            return payload

        if payload.get("brief_id") or payload.get("core_message"):
            return {
                "chunk_id": payload.get("chunk_id") or chunk_id,
                "slide_briefs": [payload],
            }

        return payload

    def _parse_chunk_plan_response(self, response: str, chunk_id: str) -> dict[str, Any]:
        briefs = self._extract_multiple_brief_objects(response)
        if len(briefs) > 1:
            return {
                "chunk_id": chunk_id,
                "slide_briefs": briefs,
            }

        parsed = self._normalize_chunk_plan_payload(self._extract_json(response), chunk_id)
        brief_count = len(parsed.get("slide_briefs", []) or [])
        if brief_count > 0:
            parsed["chunk_id"] = parsed.get("chunk_id") or chunk_id
            return parsed

        if briefs:
            return {
                "chunk_id": chunk_id,
                "slide_briefs": briefs,
            }

        parsed["chunk_id"] = parsed.get("chunk_id") or chunk_id
        return parsed

    def _extract_multiple_brief_objects(self, response: str) -> list[dict[str, Any]]:
        payload = response.lstrip("\ufeff").strip()
        cursor = 0
        briefs: list[dict[str, Any]] = []

        while cursor < len(payload):
            next_start = payload.find("{", cursor)
            if next_start == -1:
                break
            candidate = self._slice_first_json_object(payload[next_start:])
            if not candidate:
                cursor = next_start + 1
                continue
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                # The outer wrapper may be truncated while inner brief objects are still complete.
                # Advance one character and keep scanning for the next object boundary.
                cursor = next_start + 1
                continue
            if isinstance(parsed, dict) and (parsed.get("brief_id") or parsed.get("core_message")):
                briefs.append(parsed)
            cursor = next_start + len(candidate)

        return briefs

    def _extract_json(self, response: str) -> dict[str, Any]:
        raw_debug_path = Path("debug_llm_response.txt")
        raw_debug_path.write_text(response, encoding="utf-8")
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", response)
        if fenced_match:
            response = fenced_match.group(1)
        else:
            json_start = response.find("{")
            if json_start == -1:
                raise RuntimeError(
                    f"LongDocPlanner did not return JSON: {response[:200]}; raw response saved to {raw_debug_path}"
                )
            response = self._slice_first_json_object(response[json_start:])

        try:
            response = response.lstrip("\ufeff").strip()
            response = response.replace('"""', '"')
            return json.loads(response)
        except json.JSONDecodeError as exc:
            debug_path = Path("debug_llm_response.json")
            debug_path.write_text(response, encoding="utf-8")

            fixed = response
            fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
            fixed = re.sub(r':\s*"([^"]*)\n([^"]*)"', r': "\1\\n\2"', fixed)
            fixed = self._repair_unescaped_inner_quotes(fixed)
            fixed = self._balance_json_text(fixed)
            fixed = re.sub(r',(?=\s*[}\]])', '', fixed)

            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                raise RuntimeError(f"LongDocPlanner JSON parse failed: {exc}; response saved to {debug_path}") from exc

    @staticmethod
    def _repair_unescaped_inner_quotes(text: str) -> str:
        chars = list(text)
        repaired: list[str] = []
        in_string = False
        escape = False

        for index, ch in enumerate(chars):
            if not in_string:
                repaired.append(ch)
                if ch == '"':
                    in_string = True
                    escape = False
                continue

            if escape:
                repaired.append(ch)
                escape = False
                continue

            if ch == "\\":
                repaired.append(ch)
                escape = True
                continue

            if ch == '"':
                next_char = ""
                for candidate in chars[index + 1 :]:
                    if not candidate.isspace():
                        next_char = candidate
                        break
                if next_char and next_char not in {",", "}", "]", ":"}:
                    repaired.append('\\"')
                    continue
                repaired.append(ch)
                in_string = False
                continue

            repaired.append(ch)

        return "".join(repaired)

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

    @staticmethod
    def _normalize_string_list(values: Any) -> list[str]:
        if not values:
            return []
        if isinstance(values, str):
            values = [values]
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _first_heading(markdown: str) -> str:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    @staticmethod
    def _build_deck_id(title: str, markdown: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
        digest = md5(markdown[:500].encode("utf-8")).hexdigest()[:8]
        return f"{normalized or 'deck'}-{digest}"

    def _get_language_instruction(self) -> str:
        """Get language-specific instruction based on language_mode."""
        if self.language_mode == "chinese":
            return "6. 所有自然语言字段必须使用中文。"
        else:
            return "6. All natural-language fields must be in English by default."

    def _get_complexity_instruction(self) -> str:
        """Get complexity-specific instruction based on complexity_level."""
        if self._model_profile() == "qwen":
            if self.complexity_level == "simple":
                return "7. qwen simple：对应旧 balanced 档；每张幻灯片保留3-4个关键内容点，视觉元素适度，优先稳定清晰。"
            if self.complexity_level == "complex":
                return (
                    "7. qwen true complex：每张幻灯片提炼5-6个信息原子，优先保留证据、机制、对比、流程、指标和takeaway；"
                    "允许 dense 信息结构，但不要堆长段文本；有关键视觉素材时采用 visual-led，大图承载主要结构，"
                    "文本只保留2-3个解释/证据/takeaway区域；无关键视觉时采用 text-led。"
                )
            return "7. qwen balanced：对应旧 complex 档；每张幻灯片保留4-5个内容点，支持结构化布局和较复杂的视觉呈现。"
        if self.complexity_level == "simple":
            return "7. 设计风格：简洁明了，每张幻灯片内容点不超过3个，避免复杂的视觉元素。"
        elif self.complexity_level == "complex":
            return "7. 设计风格：详细深入，每张幻灯片可包含4-5个内容点，支持复杂的视觉呈现。"
        else:  # balanced
            return "7. 设计风格：平衡适中，每张幻灯片包含3-4个内容点，视觉元素适度。"

    @staticmethod
    def _model_dump(model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()
