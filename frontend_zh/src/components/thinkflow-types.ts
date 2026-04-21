import type { ReactNode } from 'react';

export type Notebook = {
  id: string;
  title?: string;
  name?: string;
};

export type CitationReference = {
  fileName?: string;
  filePath?: string;
  preview?: string;
  chunkIndex?: number | null;
  sourceNumber?: string;
};

export type PushDestinationType = 'summary' | 'document' | 'guidance';

export type ThinkFlowMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  pushed?: boolean;
  capturedTargets?: PushDestinationType[];
  fileAnalyses?: any[];
  sourceMapping?: Record<string, string>;
  sourcePreviewMapping?: Record<string, string>;
  sourceReferenceMapping?: Record<string, CitationReference>;
};

export type DocumentSourceRef = {
  name?: string;
  title?: string;
  source?: string;
  source_type?: string;
  message_id?: string;
  message_role?: string;
  message_time?: string;
  selection_text?: string;
  source_file_names?: string[];
};

export type DocumentPushTrace = {
  id: string;
  mode?: string;
  title?: string;
  prompt?: string;
  created_at: string;
  updated_at?: string;
  line_start: number;
  line_end: number;
  text_preview?: string;
  block_text?: string;
  source_refs?: DocumentSourceRef[];
};

export type ThinkFlowDocument = {
  id: string;
  title: string;
  content?: string;
  created_at: string;
  updated_at: string;
  version_count?: number;
  status_tokens?: Record<string, number>;
  push_traces?: DocumentPushTrace[];
};

export type ThinkFlowVersion = {
  id: string;
  reason?: string;
  created_at: string;
  preview?: string;
  status_tokens?: Record<string, number>;
};

export type OutlineSection = {
  id: string;
  pageNum?: number;
  title: string;
  summary?: string;
  bullets?: string[];
  layout_description?: string;
  key_points?: string[];
  asset_ref?: string | null;
  ppt_img_path?: string;
  generated_img_path?: string;
};

export type WorkspaceItemType = 'summary' | 'guidance';
export type PanelGuideKey = 'summary' | 'doc' | 'guidance';
export type ThinkFlowLeftTab = 'materials' | 'outputs';
export type ThinkFlowRightMode = 'summary' | 'doc' | 'guidance' | 'outline';
export type WorkspaceMode = 'normal' | 'output_focus' | 'output_immersive';
export type ChatMode = 'chat' | 'table-analysis';
export type PptPipelineStage = 'outline_ready' | 'pages_ready' | 'generated';

export type ConversationHistoryMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
};

export type ThinkFlowWorkspaceItem = {
  id: string;
  type: WorkspaceItemType;
  title: string;
  content?: string;
  source_refs?: DocumentSourceRef[];
  capture_count?: number;
  created_at: string;
  updated_at: string;
};

export type OutputType = 'ppt' | 'report' | 'mindmap' | 'podcast' | 'flashcard' | 'quiz';

export type PptPageReview = {
  page_index: number;
  page_num?: number;
  confirmed: boolean;
  confirmed_at?: string;
  updated_at?: string;
};

export type PptPageVersion = {
  id: string;
  page_index: number;
  page_num?: number;
  title?: string;
  source?: string;
  prompt?: string;
  preview_path?: string;
  selected?: boolean;
  created_at: string;
};

export type ThinkFlowOutput = {
  id: string;
  document_id: string;
  title: string;
  target_type: OutputType;
  status: string;
  pipeline_stage?: string;
  prompt?: string;
  page_count?: number;
  outline?: OutlineSection[];
  result?: Record<string, any>;
  guidance_item_ids?: string[];
  guidance_snapshot_text?: string;
  source_paths?: string[];
  source_names?: string[];
  bound_document_ids?: string[];
  bound_document_titles?: string[];
  result_path?: string;
  enable_images?: boolean;
  page_reviews?: PptPageReview[];
  page_versions?: PptPageVersion[];
  created_at: string;
  updated_at: string;
};

export type FlashcardItem = {
  id?: string;
  question?: string;
  answer?: string;
  type?: string;
  difficulty?: string | null;
  source_file?: string | null;
  source_excerpt?: string | null;
  tags?: string[];
  citations?: Array<{
    source_number?: number;
    file_name?: string | null;
    file_path?: string | null;
    preview?: string | null;
    chunk_index?: number | null;
  }>;
  created_at?: string | null;
};

export type FlashcardGenerationConfig = {
  difficulty_level?: 'basic' | 'intermediate' | 'advanced' | null;
  card_count?: number | null;
  topic?: string | null;
  test_focus?: string | null;
  language?: string | null;
  generated_at?: string | null;
};

export type QuizOptionItem = {
  label?: string;
  text?: string;
};

export type QuizQuestionItem = {
  id?: string;
  question?: string;
  options?: QuizOptionItem[];
  correct_answer?: string;
  explanation?: string;
  source_excerpt?: string | null;
  difficulty?: string | null;
  category?: string | null;
};

export type OutputContextSnapshot = {
  outputId: string;
  targetType: OutputType;
  documentId: string;
  documentTitle: string;
  selectedSourceIds: string[];
  sourceNames: string[];
  boundDocumentIds: string[];
  boundDocumentTitles: string[];
  guidanceItemIds: string[];
  guidanceTitles: string[];
  capturedAt: string;
};

export type OutputContextState = {
  snapshot: OutputContextSnapshot;
  isStale: boolean;
  staleReason: string;
  ignoredDraftSignature?: string;
};

export type PptSourceLockIntent = {
  outputDocumentId: string;
  outputDocumentTitle: string;
  outputTitle: string;
  guidanceItemIds: string[];
  guidanceTitles: string[];
  boundDocumentIds: string[];
  boundDocumentTitles: string[];
  sourcePaths: string[];
  sourceNames: string[];
  loading?: boolean;
  errorMessage?: string;
};

export type DirectOutputIntent = {
  targetType: Exclude<OutputType, 'ppt'>;
  outputDocumentId: string;
  outputDocumentTitle: string;
  outputTitle: string;
  guidanceItemIds: string[];
  guidanceTitles: string[];
  boundDocumentIds: string[];
  boundDocumentTitles: string[];
  sourceIds: string[];
  sourcePaths: string[];
  sourceNames: string[];
  loading?: boolean;
  errorMessage?: string;
};

export type PushMode = 'append' | 'organize' | 'merge';
export type PushTitleMode = 'ai' | 'manual';

export type PushSourceEntry = {
  messageId: string;
  role: 'user' | 'assistant';
  time: string;
  selectionText: string;
  kind: 'message' | 'selection' | 'qa' | 'multi';
};

export type ActivityStatus = {
  tone: 'loading' | 'success';
  text: string;
};

export type PushPreset = 'default' | 'qa';

export type PushPopoverState = {
  show: boolean;
  x: number;
  y: number;
  preset: PushPreset;
  destinationType: PushDestinationType;
  targetDocId: string;
  targetItemId: string;
  newTitle: string;
  titleMode: PushTitleMode;
  mode: PushMode;
  prompt: string;
  sourceContent: string;
  sourceEntries: PushSourceEntry[];
};

export type SelectionToolbarState = {
  show: boolean;
  x: number;
  y: number;
  messageId: string;
  content: string;
};

export type ParsedWorkspaceSection = {
  id: string;
  title: string;
  bullets: string[];
  paragraphs: string[];
  meta: string[];
};

export type ThinkFlowOutputButton = {
  type: OutputType;
  label: string;
  icon: ReactNode;
};

export type ThinkFlowDocumentSection = {
  id: string;
  content: string;
  lineStart: number;
  lineEnd: number;
  traces: DocumentPushTrace[];
};
