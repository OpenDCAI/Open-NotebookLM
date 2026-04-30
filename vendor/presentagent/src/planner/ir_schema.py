"""Structured IR models for PresentAgent planning."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

IR_SCHEMA_VERSION = "1.0"


class IRMetadata(BaseModel):
    schema_name: str
    schema_version: str = IR_SCHEMA_VERSION
    deck_id: str = ""
    slide_id: str = ""
    stage: Literal["planned", "resolved", "refined"] = "planned"
    source_type: Literal["pdf", "markdown", "other"] = "pdf"


class DeckTheme(BaseModel):
    name: str = "editorial"
    primary_color: str = "#134E8E"
    secondary_color: str = "#C00707"
    accent_color: str = "#FFB33F"
    background_color: str = "#F7F4EE"
    text_color: str = "#1F2937"
    font_family: str = "Aptos"
    density: Literal["airy", "balanced", "dense"] = "balanced"
    style_guardrails: List[str] = Field(
        default_factory=lambda: [
            "Use a visible grid and consistent spacing.",
            "Avoid gradients, shadows, and overly saturated colors.",
            "Emphasize one conclusion per slide with strong contrast.",
            "Do not repeat the same layout on adjacent slides.",
        ]
    )


class StorySection(BaseModel):
    id: str
    title: str
    objective: str


class Storyline(BaseModel):
    topic: str = ""
    audience: str = "general"
    presentation_goal: str = ""
    tone: str = "analytical"
    sections: List[StorySection] = Field(default_factory=list)


class LongDocProfile(BaseModel):
    is_long_document: bool = False
    markdown_chars: int = 0
    heading_count: int = 0
    section_count: int = 0
    estimated_source_pages: int = 1
    target_slide_count: int = 8
    chunk_count: int = 1
    chunk_strategy: str = "heading_plus_chars"
    chunk_char_limit: int = 6000
    overlap_chars: int = 400
    notes: List[str] = Field(default_factory=list)


class ContentChunk(BaseModel):
    chunk_id: str
    ordinal: int = 1
    heading_path: List[str] = Field(default_factory=list)
    section_title: str = ""
    start_offset: int = 0
    end_offset: int = 0
    char_count: int = 0
    overlap_from_previous: int = 0
    text: str = ""


class SlideBrief(BaseModel):
    brief_id: str
    slide_id: str = ""
    type: Literal["title", "section", "content", "closing"] = "content"
    section_id: str
    section_title: str = ""
    title: str
    core_message: str
    objective: str = ""
    content_points: List[str] = Field(default_factory=list)
    source_chunk_ids: List[str] = Field(default_factory=list)
    source_headings: List[str] = Field(default_factory=list)
    source_excerpt: str = ""
    dedupe_key: str = ""
    priority: int = 50
    presenter_notes: str = ""


class SourceEvidence(BaseModel):
    evidence_id: str = ""
    source_chunk_ids: List[str] = Field(default_factory=list)
    source_headings: List[str] = Field(default_factory=list)
    source_excerpt: str = ""
    rationale: str = ""


class SlideBriefDeck(BaseModel):
    metadata: IRMetadata = Field(
        default_factory=lambda: IRMetadata(schema_name="presentagent.slide_briefs")
    )
    title_hint: str = ""
    subtitle_hint: str = ""
    storyline_hint: Storyline = Field(default_factory=Storyline)
    longdoc_profile: LongDocProfile = Field(default_factory=LongDocProfile)
    chunks: List[ContentChunk] = Field(default_factory=list)
    slide_briefs: List[SlideBrief] = Field(default_factory=list)
    planner_notes: List[str] = Field(default_factory=list)


class SlideBlueprint(BaseModel):
    slide_id: str
    type: Literal["title", "section", "content", "closing"] = "content"
    section_id: str
    section_title: str = ""
    title: str
    core_message: str
    objective: str = ""
    brief_id: str = ""
    source_chunk_ids: List[str] = Field(default_factory=list)
    source_headings: List[str] = Field(default_factory=list)
    source_excerpt: str = ""


class LayoutSpec(BaseModel):
    name: str = "two_column"
    variant: str = "default"
    rationale: str = ""
    grid: str = "12-column"
    emphasis: str = "headline"
    density: Literal["airy", "balanced", "dense"] = "balanced"
    vary_from_previous: bool = True
    render_policy: Literal["semantic_slots", "direct_coordinates"] = "semantic_slots"
    slots: List["LayoutSlot"] = Field(default_factory=list)


class LayoutSlot(BaseModel):
    slot_id: str
    slot_role: Literal[
        "title",
        "subtitle",
        "body",
        "supporting_body",
        "hero_visual",
        "supporting_visual",
        "metrics",
        "callout",
        "footer",
    ] = "body"
    anchor: Literal[
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
    ] = "center"
    x_ratio: float = 0.0
    y_ratio: float = 0.0
    w_ratio: float = 1.0
    h_ratio: float = 1.0
    content_types: List[str] = Field(default_factory=list)


class ContentBlock(BaseModel):
    block_id: str = ""
    kind: Literal[
        "headline",
        "summary",
        "bullet_list",
        "metric_strip",
        "process",
        "comparison",
        "quote",
        "callout",
    ] = "bullet_list"
    label: str = ""
    slot_id: str = "body"
    emphasis: Literal["primary", "secondary", "supporting"] = "primary"
    content: str = ""
    items: List[str] = Field(default_factory=list)


class MaterialCandidate(BaseModel):
    asset_id: Optional[str] = None
    path: Optional[str] = None
    source: str
    category: str = ""
    asset_kind: str = ""
    caption: str = ""
    description: str = ""
    why_selected: str = ""
    vlm_score: Optional[float] = None
    content_score: Optional[float] = None
    geometry_score: Optional[float] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    aspect_ratio: Optional[float] = None
    orientation: str = ""
    file_size_bytes: Optional[int] = None


class AcquisitionPlan(BaseModel):
    source_options: List[str] = Field(default_factory=list)
    candidate_count: int = 2
    descriptor_model: str = "gpt-5.4"
    selection_method: str = ""
    fallback: str = ""


class MaterialRequest(BaseModel):
    request_id: str
    asset_type: Literal["image", "icon"]
    title: str
    caption: str
    purpose: str
    target_slide_id: str
    preferred_layout_slot: str = "supporting_visual"
    need_count: int = 1
    size_preference: Literal["small", "medium", "large", "hero"] = "medium"
    orientation_preference: Literal["any", "landscape", "portrait", "square"] = "any"
    aspect_ratio_hint: str = "any"
    style_keywords: List[str] = Field(default_factory=list)
    minimum_vlm_score: float = 0.7
    acquisition_plan: AcquisitionPlan


class VisualBinding(BaseModel):
    slot_id: str
    asset_role: str
    target_area: str = "right"
    intent: str = ""
    use_existing_asset_id: Optional[str] = None
    use_request_id: Optional[str] = None
    selected_candidate: Optional[MaterialCandidate] = None


class SlideIR(BaseModel):
    metadata: IRMetadata = Field(
        default_factory=lambda: IRMetadata(schema_name="presentagent.slide_ir")
    )
    deck_id: str = ""
    slide_id: str
    slide_number: int = 1
    type: Literal["title", "section", "content", "closing"] = "content"
    section_id: str
    section_title: str = ""
    title: str
    subtitle: str = ""
    core_message: str
    objective: str = ""
    brief_id: str = ""
    source_chunk_ids: List[str] = Field(default_factory=list)
    source_evidence: List[SourceEvidence] = Field(default_factory=list)
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    blocks: List[ContentBlock] = Field(default_factory=list)
    points: List[str] = Field(default_factory=list)
    visuals: List[VisualBinding] = Field(default_factory=list)
    design_notes: List[str] = Field(default_factory=list)
    speaker_notes: str = ""
    selected_asset_path: Optional[str] = None
    selected_asset_id: Optional[str] = None


class DeckIR(BaseModel):
    metadata: IRMetadata = Field(
        default_factory=lambda: IRMetadata(schema_name="presentagent.deck_ir")
    )
    title: str
    subtitle: str = ""
    storyline: Storyline = Field(default_factory=Storyline)
    theme: DeckTheme = Field(default_factory=DeckTheme)
    longdoc_profile: LongDocProfile = Field(default_factory=LongDocProfile)
    deck_outline: List[SlideBlueprint] = Field(default_factory=list)
    material_requests: List[MaterialRequest] = Field(default_factory=list)
    slides: List[SlideIR] = Field(default_factory=list)
    slide_manifest: List[Dict[str, Any]] = Field(default_factory=list)
    planner_notes: List[str] = Field(default_factory=list)
    source_asset_index: Dict[str, Dict] = Field(default_factory=dict)
