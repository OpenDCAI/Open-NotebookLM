import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronLeft,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  History,
  LayoutGrid,
  Mic2,
  PanelRightOpen,
  Plus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

import { apiFetch } from '../config/api';
import { useAuthStore } from '../stores/authStore';
import type { KnowledgeFile } from '../types';
import { ThinkFlowAddSourceModal } from './ThinkFlowAddSourceModal';
import { ThinkFlowCenterPanel } from './ThinkFlowCenterPanel';
import { ThinkFlowFlashcardStudy } from './ThinkFlowFlashcardStudy';
import { ThinkFlowLeftSidebar } from './ThinkFlowLeftSidebar';
import { ThinkFlowMindmapPreview } from './ThinkFlowMindmapPreview';
import { ThinkFlowOutputContextModal } from './ThinkFlowOutputContextModal';
import { ThinkFlowQuizStudy } from './ThinkFlowQuizStudy';
import { ThinkFlowTopBar } from './ThinkFlowTopBar';
import { ThinkFlowRightPanel } from './ThinkFlowRightPanel';
import { PptOutlinePanel, PptLockedOutlinePreview } from './PptOutlinePanel';
import { PptPageReviewPanel, PptGeneratedResultPanel } from './PptPageReviewPanel';
import {
  diffPptGlobalDirectives,
  diffPptOutline,
  getPptDirectiveDiffKindLabel,
  getPptOutlineDiffKindLabel,
} from './pptOutlineDiff';
import {
  buildPushSourceSummary,
  canUsePushTransform,
  coercePushTransform,
  detectMarkdownModuleHeadingLevel,
  formatThinkFlowDateTime,
  formatThinkFlowTime,
  getDefaultPushTarget,
  normalizeFocusState,
  parseMarkdownSections,
  type StructuredPushTargetType,
  type StructuredPushTransform,
  type ThinkFlowFocusState,
} from './thinkflow-document-utils';
import type { ChatMode } from './thinkflow-types';
import { splitSummaryCards } from './summaryCards';
import type { NotebookContext } from './TableAnalysisPanel';
import { usePptPageReviewManager } from './usePptPageReviewManager';
import { useConversationSourceRefs, type ConversationSourceRef } from './useConversationSourceRefs';
import {
  usePptOutlineManager,
  normalizePptStage,
  getPptStageLabel,
  getPptPreviewImages,
  buildOutlineSummaryFallback,
  getOutlineChatSessions,
  getActiveOutlineChatSession,
  getArchivedOutlineChatSessions,
  getVisiblePptOutline,
  getAppliedOutlineGlobalDirectives,
  getDraftOutlineGlobalDirectives,
  hasPendingOutlineDraft,
  buildOutlineChatMessages,
} from './usePptOutlineManager';

import './ThinkFlowWorkspace.css';

const DEFAULT_USER = { id: 'local', email: '' };
const PANEL_GUIDE_STORAGE_KEY = 'thinkflow_panel_guides_v1';

type Notebook = {
  id: string;
  title?: string;
  name?: string;
};

type ThinkFlowMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  time: string;
  pushed?: boolean;
  capturedTargets?: PushDestinationType[];
  fileAnalyses?: any[];
  sourceMapping?: Record<string, string>;
  sourcePreviewMapping?: Record<string, string>;
  sourceReferenceMapping?: Record<string, CitationReference>;
  meta?: Record<string, any>;
};

type OutlineDirective = {
  id: string;
  scope?: 'global' | 'slide';
  type?: string;
  label: string;
  instruction?: string;
  action?: 'set' | 'remove';
  value?: string;
  page_num?: number | null;
};

type OutlineIntentSummary = {
  mode?: 'global' | 'slide' | 'mixed' | 'none';
  global_directives?: OutlineDirective[];
  slide_targets?: { page_num: number; instruction: string }[];
};

type CitationReference = {
  fileName?: string;
  filePath?: string;
  preview?: string;
  chunkIndex?: number | null;
};

type ThinkFlowDocument = {
  id: string;
  title: string;
  content?: string;
  created_at: string;
  updated_at: string;
  document_type?: 'summary_doc' | 'output_doc';
  focus_state?: ThinkFlowFocusState;
  stash_items?: DocumentStashItem[];
  change_logs?: DocumentChangeLog[];
  metadata?: Record<string, any>;
  version_count?: number;
  status_tokens?: Record<string, number>;
  push_traces?: DocumentPushTrace[];
};

type DocumentSourceRef = {
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

type DocumentPushTrace = {
  id: string;
  mode?: string;
  transform?: StructuredPushTransform;
  target?: Record<string, any>;
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

type DocumentStashItem = {
  id: string;
  content: string;
  source_refs?: DocumentSourceRef[];
  created_at: string;
  updated_at?: string;
};

type DocumentChangeLog = {
  id: string;
  timestamp: string;
  doc_id: string;
  type: string;
  summary: string;
  related_conv?: string | null;
  metadata?: Record<string, any>;
};

type ThinkFlowVersion = {
  id: string;
  reason?: string;
  created_at: string;
  preview?: string;
  status_tokens?: Record<string, number>;
};

type OutlineSection = {
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

type WorkspaceItemType = 'summary' | 'guidance';
type PanelGuideKey = 'summary' | 'doc' | 'guidance';
type WorkspaceMode = 'normal' | 'output_focus' | 'output_immersive';
type PptPipelineStage = 'outline_ready' | 'pages_ready' | 'generated';

type ConversationHistoryMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
};

type OutlineChatSession = {
  id: string;
  status?: 'active' | 'applied' | 'archived';
  messages?: ConversationHistoryMessage[];
  draft_outline?: OutlineSection[];
  draft_global_directives?: OutlineDirective[];
  intent_summary?: OutlineIntentSummary;
  summary?: string;
  has_pending_changes?: boolean;
  change_summary?: string;
  created_at?: string;
  updated_at?: string;
  applied_at?: string;
};

type ConversationListItem = {
  id: string;
  title: string;
  notebook_id?: string;
  created_at?: string;
  updated_at?: string;
};

type ThinkFlowWorkspaceItem = {
  id: string;
  type: WorkspaceItemType;
  summary_kind?: 'item' | 'all';
  title: string;
  content?: string;
  source_refs?: DocumentSourceRef[];
  source_summary_item_ids?: string[];
  capture_count?: number;
  created_at: string;
  updated_at: string;
};

type OutputType = 'ppt' | 'report' | 'mindmap' | 'podcast' | 'flashcard' | 'quiz';

type ThinkFlowOutput = {
  id: string;
  document_id: string;
  title: string;
  target_type: OutputType;
  status: string;
  pipeline_stage?: string;
  prompt?: string;
  page_count?: number;
  outline?: OutlineSection[];
  outline_global_directives?: OutlineDirective[];
  result?: Record<string, any>;
  guidance_item_ids?: string[];
  guidance_snapshot_text?: string;
  source_paths?: string[];
  source_names?: string[];
  bound_document_ids?: string[];
  bound_document_titles?: string[];
  result_path?: string;
  enable_images?: boolean;
  outline_chat_history?: ConversationHistoryMessage[];
  outline_chat_sessions?: OutlineChatSession[];
  outline_chat_active_session_id?: string;
  outline_chat_draft_outline?: OutlineSection[];
  outline_chat_draft_global_directives?: OutlineDirective[];
  outline_chat_has_pending_changes?: boolean;
  page_reviews?: PptPageReview[];
  page_versions?: PptPageVersion[];
  created_at: string;
  updated_at: string;
};

type FlashcardItem = {
  id?: string;
  question?: string;
  answer?: string;
  type?: string;
  difficulty?: string | null;
  source_file?: string | null;
  source_excerpt?: string | null;
  tags?: string[];
  created_at?: string | null;
};

type QuizOptionItem = {
  label?: string;
  text?: string;
};

type QuizQuestionItem = {
  id?: string;
  question?: string;
  options?: QuizOptionItem[];
  correct_answer?: string;
  explanation?: string;
  source_excerpt?: string | null;
  difficulty?: string | null;
  category?: string | null;
};

type PptPageReview = {
  page_index: number;
  page_num?: number;
  confirmed: boolean;
  confirmed_at?: string;
  updated_at?: string;
};

type PptPageVersion = {
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

type OutputContextSnapshot = {
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

type OutputContextState = {
  snapshot: OutputContextSnapshot;
  isStale: boolean;
  staleReason: string;
  ignoredDraftSignature?: string;
};

type PptSourceLockIntent = {
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

type DirectOutputIntent = {
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

type PushMode = 'append' | 'organize' | 'merge';
type PushDestinationType = 'summary' | 'document' | 'guidance';
type PushTitleMode = 'ai' | 'manual';

type PushSourceEntry = {
  messageId: string;
  role: 'user' | 'assistant';
  time: string;
  selectionText: string;
  kind: 'message' | 'selection' | 'qa' | 'multi';
};

type PushPreset = 'default' | 'qa';

type PushPopoverState = {
  show: boolean;
  x: number;
  y: number;
  preset: PushPreset;
  destinationType: PushDestinationType;
  targetType: StructuredPushTargetType;
  targetSectionId: string;
  newSectionTitle: string;
  transform: StructuredPushTransform;
  targetDocId: string;
  targetItemId: string;
  newTitle: string;
  titleMode: PushTitleMode;
  mode: PushMode;
  prompt: string;
  sourceContent: string;
  sourceEntries: PushSourceEntry[];
};

type SelectionToolbarState = {
  show: boolean;
  x: number;
  y: number;
  messageId: string;
  content: string;
};

type ParsedWorkspaceSection = {
  id: string;
  title: string;
  bullets: string[];
  paragraphs: string[];
  meta: string[];
};

const outputButtons: Array<{
  type: OutputType;
  label: string;
  icon: React.ReactNode;
}> = [
  { type: 'ppt', label: 'PPT', icon: <LayoutGrid size={14} /> },
  { type: 'report', label: '报告', icon: <FileText size={14} /> },
  { type: 'mindmap', label: '导图', icon: <Brain size={14} /> },
  { type: 'podcast', label: '播客', icon: <Mic2 size={14} /> },
  { type: 'flashcard', label: '卡片', icon: <BookOpen size={14} /> },
  { type: 'quiz', label: '测验', icon: <BarChart3 size={14} /> },
];

function getNotebookTitle(notebook: Notebook): string {
  return notebook?.title || notebook?.name || '未命名笔记本';
}

function resolveFileUrl(file: any): string {
  return file?.static_url || file?.url || file?.storage_path || '';
}

function guessFileType(name: string): KnowledgeFile['type'] {
  const lower = name.toLowerCase();
  if (lower.endsWith('.csv') || lower.endsWith('.xlsx')) return 'dataset';
  if (lower.match(/\.(png|jpg|jpeg|gif|webp)$/)) return 'image';
  if (lower.match(/\.(mp3|wav|m4a)$/)) return 'audio';
  if (lower.match(/\.(mp4|mov)$/)) return 'video';
  if (lower.startsWith('http')) return 'link';
  return 'doc';
}

function fileEmoji(type: KnowledgeFile['type']) {
  switch (type) {
    case 'dataset':
      return '📊';
    case 'image':
      return '🖼️';
    case 'audio':
      return '🎧';
    case 'video':
      return '🎬';
    case 'link':
      return '🔗';
    default:
      return '📄';
  }
}

function outputEmoji(type: OutputType) {
  switch (type) {
    case 'ppt':
      return '📊';
    case 'report':
      return '📝';
    case 'mindmap':
      return '🧠';
    case 'podcast':
      return '🎙️';
    case 'flashcard':
      return '🃏';
    case 'quiz':
      return '✅';
    default:
      return '📦';
  }
}

function outputLabel(type: OutputType) {
  return outputButtons.find((item) => item.type === type)?.label || type;
}

function buildConversationHistoryPayload(messages: ThinkFlowMessage[]): ConversationHistoryMessage[] {
  return messages
    .filter((item) => item.id !== 'welcome')
    .filter((item) => item.role === 'user' || item.role === 'assistant')
    .slice(-12)
    .map((item, index) => ({
      id: item.id || `conversation_${index}`,
      role: item.role === 'user' ? 'user' : 'assistant',
      content: String(item.content || '').trim(),
      created_at: undefined,
    }))
    .filter((item) => item.content);
}

function workspaceItemLabel(type: WorkspaceItemType) {
  return type === 'summary' ? '摘要' : '产出指导';
}

function workspaceItemEmoji(type: WorkspaceItemType) {
  return type === 'summary' ? '🗂️' : '🎯';
}

function describePushAction(destinationType: PushDestinationType, mode: PushMode) {
  if (destinationType === 'document') {
    if (mode === 'merge') return '正在调用 AI 融合进文档...';
    if (mode === 'organize') return '正在调用 AI 整理并写入文档...';
    return '正在追加到文档...';
  }
  return destinationType === 'guidance' ? '正在生成产出指导...' : '正在生成摘要...';
}

function parseWorkspaceMarkdown(content: string): ParsedWorkspaceSection[] {
  const trimmed = String(content || '').trim();
  if (!trimmed) return [];

  const lines = trimmed.split('\n');
  const sections: ParsedWorkspaceSection[] = [];
  let current: ParsedWorkspaceSection | null = null;

  const ensureCurrent = (fallbackTitle = '内容') => {
    if (!current) {
      current = {
        id: `section_${sections.length}`,
        title: fallbackTitle,
        bullets: [],
        paragraphs: [],
        meta: [],
      };
      sections.push(current);
    }
    return current;
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    const headingMatch = line.match(/^##+\s+(.*)$/);
    if (headingMatch) {
      current = {
        id: `section_${sections.length}`,
        title: headingMatch[1].trim() || `内容 ${sections.length + 1}`,
        bullets: [],
        paragraphs: [],
        meta: [],
      };
      sections.push(current);
      continue;
    }

    if (line.startsWith('>')) {
      ensureCurrent('概览').meta.push(line.replace(/^>\s?/, '').trim());
      continue;
    }

    const bulletMatch = line.match(/^[-*]\s+(.*)$/);
    if (bulletMatch) {
      ensureCurrent('要点').bullets.push(bulletMatch[1].trim());
      continue;
    }

    ensureCurrent('概览').paragraphs.push(line);
  }

  return sections;
}

async function parseJson<T>(response: Response): Promise<T> {
  const raw = await response.text();
  let data: any = null;

  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      if (!response.ok) {
        throw new Error(raw.trim() || `Request failed: ${response.status}`);
      }
      throw new Error(`Invalid JSON response: ${raw.slice(0, 160)}`);
    }
  }

  if (!response.ok || data?.success === false) {
    const detail = typeof data?.detail === 'string' ? data.detail.trim() : '';
    const message = typeof data?.message === 'string' ? data.message.trim() : '';
    const nestedErrorMessage =
      typeof data?.error?.message === 'string'
        ? data.error.message.trim()
        : '';
    const fallback =
      raw.trim() ||
      response.statusText ||
      `Request failed: ${response.status}`;
    throw new Error(detail || message || nestedErrorMessage || fallback);
  }
  return data as T;
}

function inferDocumentTitle(sourceContent: string, prompt?: string): string {
  const base = String(prompt || '').trim() || String(sourceContent || '').trim();
  const firstLine = base.split('\n').find((line) => line.trim()) || '';
  const compact = firstLine
    .replace(/^#+\s*/, '')
    .replace(/^[-*]\s*/, '')
    .replace(/[。？！；;:：].*$/, '')
    .trim();
  return compact.slice(0, 18) || '梳理摘要';
}

function getCitationMeta(message: ThinkFlowMessage, sourceNumber: string) {
  const reference = message.sourceReferenceMapping?.[sourceNumber];
  const title = reference?.fileName || message.sourceMapping?.[sourceNumber] || '';
  const preview = reference?.preview || message.sourcePreviewMapping?.[sourceNumber] || '';
  return { reference, title, preview };
}

function splitTextWithCitations(text: string): Array<{ type: 'text' | 'citation'; value: string }> {
  const pattern = /\[(\d{1,3})\]/g;
  const parts: Array<{ type: 'text' | 'citation'; value: string }> = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }
    parts.push({ type: 'citation', value: match[1] });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) });
  }

  return parts.length > 0 ? parts : [{ type: 'text', value: text }];
}

const DOC_STATUS_BADGES: Record<string, string> = {
  '[待确认]': '❓ 待确认',
  '[待补充]': '📝 待补充',
  '[仅大纲]': '📋 仅大纲',
};

const DOC_STATUS_CLASSNAMES: Record<string, string> = {
  '[待确认]': 'pending-confirm',
  '[待补充]': 'pending-fill',
  '[仅大纲]': 'outline-only',
};

function splitTextWithStatusTokens(text: string): Array<{ type: 'text' | 'status'; value: string }> {
  const pattern = /(\[待确认\]|\[待补充\]|\[仅大纲\])/g;
  const parts: Array<{ type: 'text' | 'status'; value: string }> = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }
    parts.push({ type: 'status', value: match[1] });
    lastIndex = match.index + match[1].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) });
  }

  return parts.length > 0 ? parts : [{ type: 'text', value: text }];
}

function buildDocumentSections(content: string, traces: DocumentPushTrace[], headingLevel = 2) {
  const lines = String(content || '').split('\n');
  const parsedSections = parseMarkdownSections(content, headingLevel);

  if (parsedSections.length === 0) {
    const trimmed = content.trim();
    return trimmed
      ? [
          {
            id: 'section_0',
            content: trimmed,
            lineStart: 1,
            lineEnd: lines.length,
            traces: traces.filter((trace) => trace.line_start <= lines.length && trace.line_end >= 1),
          },
        ]
      : [];
  }

  const sections: Array<{
    id: string;
    heading?: string;
    content: string;
    lineStart: number;
    lineEnd: number;
    traces: DocumentPushTrace[];
  }> = [];

  const firstHeading = parsedSections[0].lineStart - 1;
  if (firstHeading > 0) {
    const preamble = lines.slice(0, firstHeading).join('\n').trim();
    if (preamble) {
      sections.push({
        id: 'section_preamble',
        content: preamble,
        lineStart: 1,
        lineEnd: firstHeading,
        traces: traces.filter((trace) => trace.line_start <= firstHeading && trace.line_end >= 1),
      });
    }
  }

  parsedSections.forEach((section) => {
    sections.push({
      id: section.id,
      heading: section.heading,
      content: section.content,
      lineStart: section.lineStart,
      lineEnd: section.lineEnd,
      traces: traces.filter((trace) => trace.line_start <= section.lineEnd && trace.line_end >= section.lineStart),
    });
  });

  return sections;
}

const ThinkFlowWorkspace = ({ notebook, onBack }: { notebook: Notebook; onBack: () => void }) => {
  const { user } = useAuthStore();
  const effectiveUser = user || DEFAULT_USER;
  const notebookTitle = getNotebookTitle(notebook);

  const [leftTab, setLeftTab] = useState<'conversations' | 'materials' | 'outputs'>('materials');
  const [rightMode, setRightMode] = useState<'summary' | 'doc' | 'guidance' | 'outline'>('doc');
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('normal');
  const [isOutputHeaderCollapsed, setIsOutputHeaderCollapsed] = useState(false);
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showAddSourceModal, setShowAddSourceModal] = useState(false);

  // ─── 表格分析模式状态 ──────────────────────────────────────────────────────
  const [chatMode, setChatMode] = useState<ChatMode>('chat');
  const [activeDataset, setActiveDataset] = useState<KnowledgeFile | null>(null);
  const [dataSessionId, setDataSessionId] = useState<string | null>(null);
  // ref 防重注册：fileId → datasource_id (int)，不触发重渲染
  const registeredDatasourceIds = useRef<Record<string, number>>({});

  const [documents, setDocuments] = useState<ThinkFlowDocument[]>([]);
  const [activeDocumentId, setActiveDocumentId] = useState('');
  const [conversationActiveDocumentId, setConversationActiveDocumentId] = useState('');
  const [documentTitle, setDocumentTitle] = useState('');
  const [documentContent, setDocumentContent] = useState('');
  const [documentFocusState, setDocumentFocusState] = useState<ThinkFlowFocusState>(() => normalizeFocusState());
  const [documentStashItems, setDocumentStashItems] = useState<DocumentStashItem[]>([]);
  const [documentChangeLogs, setDocumentChangeLogs] = useState<DocumentChangeLog[]>([]);
  const [documentSaving, setDocumentSaving] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [showVersionPanel, setShowVersionPanel] = useState(false);
  const [versions, setVersions] = useState<ThinkFlowVersion[]>([]);
  const [workspaceItems, setWorkspaceItems] = useState<ThinkFlowWorkspaceItem[]>([]);
  const [activeSummaryId, setActiveSummaryId] = useState('');
  const [activeGuidanceId, setActiveGuidanceId] = useState('');
  const [summaryTitle, setSummaryTitle] = useState('');
  const [summaryContent, setSummaryContent] = useState('');
  const [guidanceTitle, setGuidanceTitle] = useState('');
  const [guidanceContent, setGuidanceContent] = useState('');
  const [summaryEditMode, setSummaryEditMode] = useState(false);
  const [workspaceSaving, setWorkspaceSaving] = useState<WorkspaceItemType | null>(null);
  const [rebuildingAllSummary, setRebuildingAllSummary] = useState(false);
  const [selectedGuidanceIds, setSelectedGuidanceIds] = useState<string[]>([]);
  const [panelGuideVisibility, setPanelGuideVisibility] = useState<Record<PanelGuideKey, boolean>>(() => {
    if (typeof window === 'undefined') {
      return { summary: true, doc: true, guidance: true };
    }
    try {
      const stored = window.localStorage.getItem(PANEL_GUIDE_STORAGE_KEY);
      if (!stored) return { summary: true, doc: true, guidance: true };
      const parsed = JSON.parse(stored);
      return {
        summary: parsed?.summary !== false,
        doc: parsed?.doc !== false,
        guidance: parsed?.guidance !== false,
      };
    } catch {
      return { summary: true, doc: true, guidance: true };
    }
  });

  const welcomeMessages = useMemo<ThinkFlowMessage[]>(
    () => [
      {
        id: 'welcome',
        role: 'assistant',
        content: '请先围绕左侧已选素材提问。对话是主线，你可以按需把某个回答、某组问答或多轮内容沉淀成摘要、整理进文档，或者加入产出指导。',
        time: formatThinkFlowTime(new Date()),
      },
    ],
    [],
  );
  const [chatMessages, setChatMessages] = useState<ThinkFlowMessage[]>(welcomeMessages);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [boundDocIds, setBoundDocIds] = useState<string[]>([]);
  const {
    conversationSourceRefs,
    setConversationSourceRefs,
    clearConversationSourceRefs,
  } = useConversationSourceRefs();
  const [selectedMessageIds, setSelectedMessageIds] = useState<string[]>([]);
  const [multiSelectPrompt, setMultiSelectPrompt] = useState('');
  const [globalError, setGlobalErrorRaw] = useState('');
  const [captureFeedback, setCaptureFeedback] = useState('');

  // ── Toast system ──────────────────────────────────────────────────────────
  type ToastKind = 'error' | 'success' | 'info' | 'warning';
  const [toasts, setToasts] = useState<Array<{ id: number; kind: ToastKind; message: string }>>([]);
  const toastIdRef = useRef(0);

  const pushToast = useCallback((message: string, kind: ToastKind = 'info', duration = 4000) => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), duration);
  }, []);

  // Keep setGlobalError as a compat wrapper → routes to toast
  const setGlobalError = useCallback((msg: string) => {
    setGlobalErrorRaw(msg); // keep existing logic that clears on success
    if (msg) pushToast(msg, 'error', 5000);
  }, [pushToast]);
  // ─────────────────────────────────────────────────────────────────────────

  // ─── Refs for late-defined deps passed to usePptOutlineManager ───────────
  const enterOutputWorkspaceRef = useRef<(mode?: WorkspaceMode) => void>(() => {});
  const buildOutputContextSnapshotRef = useRef<(params: {
    outputId: string;
    targetType: OutputType;
    documentId?: string;
    guidanceItemIds?: string[];
    selectedSourceIds?: string[];
    boundDocumentIds?: string[];
  }) => OutputContextSnapshot>(() => ({} as OutputContextSnapshot));
  const ensureDocumentContentRef = useRef<(documentId: string) => Promise<ThinkFlowDocument | null>>(async () => null);
  const loadDocumentDetailRef = useRef<(documentId: string) => Promise<ThinkFlowDocument>>(async () => ({} as ThinkFlowDocument));
  // ─────────────────────────────────────────────────────────────────────────

  const [pushSubmitting, setPushSubmitting] = useState(false);
  const [pushStatusText, setPushStatusText] = useState('');
  const [pushError, setPushError] = useState('');
  const [conversationId, setConversationId] = useState('');
  const [conversationList, setConversationList] = useState<ConversationListItem[]>([]);
  const [conversationListLoading, setConversationListLoading] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyConversations, setHistoryConversations] = useState<ConversationListItem[]>([]);

  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false);
  const [sourcePreviewFile, setSourcePreviewFile] = useState<KnowledgeFile | null>(null);
  const [sourcePreviewContent, setSourcePreviewContent] = useState('');
  const [sourcePreviewLoading, setSourcePreviewLoading] = useState(false);

  const [pushPopover, setPushPopover] = useState<PushPopoverState>({
    show: false,
    x: 0,
    y: 0,
    preset: 'default',
    destinationType: 'summary',
    targetType: 'document_end',
    targetSectionId: '',
    newSectionTitle: '',
    transform: 'ai_append',
    targetDocId: '',
    targetItemId: '',
    newTitle: '',
    titleMode: 'ai',
    mode: 'organize',
    prompt: '',
    sourceContent: '',
    sourceEntries: [],
  });
  const [selectionToolbar, setSelectionToolbar] = useState<SelectionToolbarState>({
    show: false,
    x: 0,
    y: 0,
    messageId: '',
    content: '',
  });
  const [highlightedTraceId, setHighlightedTraceId] = useState('');
  const [focusedMessageId, setFocusedMessageId] = useState('');
  const [focusedSelectionText, setFocusedSelectionText] = useState('');
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const docBodyRef = useRef<HTMLDivElement | null>(null);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const layoutRef = useRef<HTMLDivElement | null>(null);

  const notebookQuery = useMemo(() => {
    const query = new URLSearchParams({
      notebook_id: notebook.id,
      notebook_title: notebookTitle,
      user_id: effectiveUser?.id || 'local',
      email: effectiveUser?.email || '',
    });
    return query.toString();
  }, [effectiveUser?.email, effectiveUser?.id, notebook.id, notebookTitle]);

  const activeDocument = useMemo(
    () => documents.find((item) => item.id === activeDocumentId) || null,
    [activeDocumentId, documents],
  );
  const conversationActiveDocument = useMemo(
    () => documents.find((item) => item.id === conversationActiveDocumentId) || null,
    [conversationActiveDocumentId, documents],
  );

  const summaryItems = useMemo(
    () => workspaceItems.filter((item) => item.type === 'summary'),
    [workspaceItems],
  );
  const { itemSummaries: itemSummaryItems, allSummary } = useMemo(
    () => splitSummaryCards(summaryItems),
    [summaryItems],
  );

  const guidanceItems = useMemo(
    () => workspaceItems.filter((item) => item.type === 'guidance'),
    [workspaceItems],
  );

  const activeSummary = useMemo(
    () => summaryItems.find((item) => item.id === activeSummaryId) || null,
    [activeSummaryId, summaryItems],
  );

  const activeGuidance = useMemo(
    () => guidanceItems.find((item) => item.id === activeGuidanceId) || null,
    [activeGuidanceId, guidanceItems],
  );

  const withAssetVersion = (url: string, seed?: string) => {
    const cleanUrl = String(url || '').trim();
    if (!cleanUrl) return '';
    const separator = cleanUrl.includes('?') ? '&' : '?';
    return `${cleanUrl}${separator}v=${encodeURIComponent(seed || activeOutput?.updated_at || '')}`;
  };

  const documentSections = useMemo(
    () => buildDocumentSections(
      documentContent,
      activeDocument?.push_traces || [],
      activeDocument?.document_type === 'output_doc' ? detectMarkdownModuleHeadingLevel(documentContent) : 2,
    ),
    [activeDocument?.document_type, activeDocument?.push_traces, documentContent],
  );

  const selectedFilePaths = useMemo(() => {
    const materialRefs = conversationSourceRefs.filter((ref) => ref.type === 'material');
    return materialRefs
      .map((ref) => ref.path || resolveFileUrl(files.find((file) => file.id === ref.id) || {}))
      .filter(Boolean);
  }, [conversationSourceRefs, files]);
  const selectedSourceNames = useMemo(() => {
    const names = conversationSourceRefs
      .filter((ref) => ref.type === 'material')
      .map((ref) => ref.title || files.find((file) => file.id === ref.id)?.name || '未命名来源');
    return names;
  }, [conversationSourceRefs, files]);

  const selectedSourceIds = useMemo(
    () => conversationSourceRefs.filter((ref) => ref.type === 'material').map((ref) => ref.id).sort(),
    [conversationSourceRefs],
  );

  // ─── PPT Outline Manager Hook ─────────────────────────────────────────────
  const {
    outputs,
    setOutputs,
    activeOutputId,
    setActiveOutputId,
    outlineSaving,
    setOutlineSaving,
    generatingOutline,
    setGeneratingOutline,
    generatingOutput,
    setGeneratingOutput,
    activePptSlideIndex,
    setActivePptSlideIndex,
    pptOutlineReadonlyOpen,
    setPptOutlineReadonlyOpen,
    pptOutlinePendingMessages,
    setPptOutlinePendingMessages,
    outputContexts,
    setOutputContexts,
    pptSourceLockIntent,
    setPptSourceLockIntent,
    directOutputIntent,
    setDirectOutputIntent,
    activeOutput,
    activePptStage,
    activePptOutline,
    activePptDraftPending,
    activeOutlineChatSession,
    archivedOutlineChatSessions,
    activePptGlobalDirectives,
    activePptPreviewImages,
    activePptSlide,
    isPptOutlineChatStage,
    pptOutlineChatMessages,
    activeOutputContext,
    refreshOutputs,
    handleOutputWorkspaceScroll,
    resolveOutputCreationInputs,
    openPptSourceLockIntent,
    confirmPptSourceLockIntent,
    openDirectOutputIntent,
    confirmDirectOutputIntent,
    openExistingOutput,
    handlePptOutlineChatMessage,
    applyPptOutlineDraft,
    createOutline,
    saveOutline,
    confirmPptOutline,
    generateOutputById,
  } = usePptOutlineManager({
    notebook,
    notebookTitle,
    effectiveUser,
    pushToast,
    setGlobalError,
    chatMessages,
    setChatMessages,
    setChatInput,
    setChatLoading,
    buildConversationHistoryPayload,
    selectedGuidanceIds,
    guidanceItems,
    documents,
    files,
    selectedSourceIds,
    boundDocIds,
    activeDocumentId,
    documentTitle,
    documentContent,
    activeDocument,
    notebookQuery,
    selectedSourceNames,
    setLeftTab,
    setRightMode,
    enterOutputWorkspace: (mode) => enterOutputWorkspaceRef.current(mode),
    buildOutputContextSnapshot: (params) => buildOutputContextSnapshotRef.current(params),
    ensureDocumentContent: (id) => ensureDocumentContentRef.current(id),
    setIsOutputHeaderCollapsed,
    loadDocumentDetail: (id) => loadDocumentDetailRef.current(id),
  });
  // ─────────────────────────────────────────────────────────────────────────

  // ─── PPT Page Review Manager Hook ────────────────────────────────────────
  const {
    pptPagePrompt,
    setPptPagePrompt,
    pptPageBusyAction,
    pptPageStatus,
    activePptPageReviews,
    activePptConfirmedCount,
    activePptCurrentReview,
    activePptPageVersions,
    activePptCurrentPreview,
    regenerateActivePptPage,
    selectActivePptPageVersion,
    confirmActivePptPage,
    revertToOutlineStage,
    pageReviewFilter,
    setPageReviewFilter,
    pageReviewChatContext,
  } = usePptPageReviewManager({
    activeOutput,
    activePptSlideIndex,
    activePptSlide,
    activePptOutline,
    activePptPreviewImages,
    setOutputs,
    setActivePptSlideIndex,
    pushToast,
    setGlobalError,
    refreshOutputs,
    notebook,
    notebookTitle,
    effectiveUser,
    generatingOutput,
  });
  // ─────────────────────────────────────────────────────────────────────────

  const visibleChatMessages = useMemo(
    () => (isPptOutlineChatStage ? [...pptOutlineChatMessages, ...pptOutlinePendingMessages] : chatMessages),
    [chatMessages, isPptOutlineChatStage, pptOutlineChatMessages, pptOutlinePendingMessages],
  );

  const buildOutputContextSnapshot = ({
    outputId,
    targetType,
    documentId,
    guidanceItemIds,
    selectedSourceIds: selectedSourceIdsOverride,
    boundDocumentIds: boundDocumentIdsOverride,
  }: {
    outputId: string;
    targetType: OutputType;
    documentId?: string;
    guidanceItemIds?: string[];
    selectedSourceIds?: string[];
    boundDocumentIds?: string[];
  }): OutputContextSnapshot => {
    const resolvedDocumentId = documentId || activeDocumentId || '';
    const resolvedGuidanceIds = guidanceItemIds ? [...guidanceItemIds] : [...selectedGuidanceIds];
    const documentEntry = documents.find((item) => item.id === resolvedDocumentId);
    const resolvedBoundDocumentIds =
      boundDocumentIdsOverride && boundDocumentIdsOverride.length > 0
        ? [...boundDocumentIdsOverride]
        : [...boundDocIds];
    const boundEntries = documents.filter((item) => resolvedBoundDocumentIds.includes(item.id));
    const resolvedSourceIds =
      selectedSourceIdsOverride && selectedSourceIdsOverride.length > 0
        ? [...selectedSourceIdsOverride]
        : selectedSourceIds.length > 0
          ? [...selectedSourceIds]
          : files.map((file) => file.id);
    const sourceEntries = files.filter((file) => resolvedSourceIds.includes(file.id));
    const guidanceEntries = guidanceItems.filter((item) => resolvedGuidanceIds.includes(item.id));
    return {
      outputId,
      targetType,
      documentId: resolvedDocumentId,
      documentTitle: documentEntry?.title || documentTitle || '未命名文档',
      selectedSourceIds: resolvedSourceIds,
      sourceNames: sourceEntries.map((item) => item.name),
      boundDocumentIds: resolvedBoundDocumentIds,
      boundDocumentTitles: boundEntries.map((item) => item.title),
      guidanceItemIds: [...resolvedGuidanceIds].sort(),
      guidanceTitles: guidanceEntries.map((item) => item.title),
      capturedAt: new Date().toISOString(),
    };
  };
  buildOutputContextSnapshotRef.current = buildOutputContextSnapshot;

  const ensureOutputContext = (output: ThinkFlowOutput) => {
    if (!output?.id || output.target_type === 'ppt') return;
    setOutputContexts((previous) => {
      if (previous[output.id]) return previous;
      const sourceIdsFromOutput = files
        .filter((file) => {
          const fileUrl = resolveFileUrl(file);
          return (
            (output.source_paths || []).includes(fileUrl) ||
            (output.source_names || []).includes(file.name || '')
          );
        })
        .map((file) => file.id);
      return {
        ...previous,
        [output.id]: {
          snapshot: buildOutputContextSnapshot({
            outputId: output.id,
            targetType: output.target_type,
            documentId: output.document_id,
            guidanceItemIds: output.guidance_item_ids || [],
            selectedSourceIds: sourceIdsFromOutput,
            boundDocumentIds: output.bound_document_ids || [],
          }),
          isStale: false,
          staleReason: '',
        },
      };
    });
  };

  const refreshFiles = async () => {
    setLoadingFiles(true);
    try {
      const response = await apiFetch(`/api/v1/kb/files?${notebookQuery}`);
      const data = await parseJson<{ files: any[] }>(response);
      const nextFiles: KnowledgeFile[] = (data.files || []).map((file) => ({
        id: file.id || resolveFileUrl(file) || file.name,
        name: file.name || '未命名素材',
        type: guessFileType(file.name || ''),
        url: resolveFileUrl(file),
        size: file.file_size ? `${Math.max(1, Math.round(Number(file.file_size) / 1024))}KB` : undefined,
        uploadTime: file.created_at || '',
        isEmbedded: Boolean(file.vector_ready),
        kbFileId: file.kb_file_id,
        vectorStatus: file.vector_status,
        vectorReady: file.vector_ready,
        vectorError: file.vector_error,
      }));
      setFiles(nextFiles);
      setSelectedIds((previous) => new Set([...previous].filter((id) => nextFiles.some((file) => file.id === id))));
    } catch (error: any) {
      setGlobalError(error?.message || '加载素材失败');
    } finally {
      setLoadingFiles(false);
    }
  };

  const loadDocumentDetail = async (documentId: string) => {
    const [detailResponse, versionResponse] = await Promise.all([
      apiFetch(`/api/v1/kb/documents/${documentId}?${notebookQuery}`),
      apiFetch(`/api/v1/kb/documents/${documentId}/versions?${notebookQuery}`),
    ]);
    const detailData = await parseJson<{ document: ThinkFlowDocument }>(detailResponse);
    const versionData = await parseJson<{ versions: ThinkFlowVersion[] }>(versionResponse);
    setDocumentTitle(detailData.document.title || '');
    setDocumentContent(detailData.document.content || '');
    setDocumentFocusState(normalizeFocusState(detailData.document.focus_state));
    setDocumentStashItems(detailData.document.stash_items || []);
    setDocumentChangeLogs(detailData.document.change_logs || []);
    setVersions(versionData.versions || []);
      setDocuments((previous) =>
      previous.map((item) => (item.id === documentId ? { ...item, ...detailData.document } : item)),
    );
    return detailData.document;
  };
  loadDocumentDetailRef.current = loadDocumentDetail;

  const refreshDocuments = async (preferredId?: string) => {
    try {
      const response = await apiFetch(`/api/v1/kb/documents?${notebookQuery}`);
      const data = await parseJson<{ documents: ThinkFlowDocument[] }>(response);
      const items = data.documents || [];
      setDocuments(items);
      const targetId = preferredId || (activeDocumentId && items.some((item) => item.id === activeDocumentId) ? activeDocumentId : '') || '';
      if (targetId) {
        setActiveDocumentId(targetId);
        await loadDocumentDetail(targetId);
      } else {
        setActiveDocumentId('');
        setDocumentTitle('');
        setDocumentContent('');
        setDocumentFocusState(normalizeFocusState());
        setDocumentStashItems([]);
        setDocumentChangeLogs([]);
        setVersions([]);
        setEditMode(false);
        setShowVersionPanel(false);
      }
      setBoundDocIds((previous) => previous.filter((id) => items.some((item) => item.id === id)));
      setConversationActiveDocumentId((previous) => (previous && items.some((item) => item.id === previous) ? previous : targetId || ''));
      setPushPopover((previous) => ({
        ...previous,
        targetDocId: previous.targetDocId && items.some((item) => item.id === previous.targetDocId)
          ? previous.targetDocId
          : targetId || items[0]?.id || '',
      }));
    } catch (error: any) {
      setGlobalError(error?.message || '加载文档失败');
    }
  };

  const loadWorkspaceItemDetail = async (itemId: string) => {
    const response = await apiFetch(`/api/v1/kb/workspace-items/${itemId}?${notebookQuery}`);
    const data = await parseJson<{ item: ThinkFlowWorkspaceItem }>(response);
    const nextItem = data.item;
    setWorkspaceItems((previous) => previous.map((item) => (item.id === itemId ? { ...item, ...nextItem } : item)));
    if (nextItem.type === 'summary') {
      setSummaryTitle(nextItem.title || '');
      setSummaryContent(nextItem.content || '');
      setSummaryEditMode(false);
      setActiveSummaryId(itemId);
    } else {
      setGuidanceTitle(nextItem.title || '');
      setGuidanceContent(nextItem.content || '');
      setActiveGuidanceId(itemId);
    }
    return nextItem;
  };

  const refreshWorkspaceItems = async (preferredId?: string) => {
    try {
      const response = await apiFetch(`/api/v1/kb/workspace-items?${notebookQuery}`);
      const data = await parseJson<{ items: ThinkFlowWorkspaceItem[] }>(response);
      const items = data.items || [];
      setWorkspaceItems(items);
      const loadedSummaryItems = items.filter((item) => item.type === 'summary');
      const loadedAllSummary = loadedSummaryItems.find((item) => item.summary_kind === 'all') || null;

      const nextSummaryId =
        preferredId && items.some((item) => item.id === preferredId && item.type === 'summary')
          ? preferredId
          : activeSummaryId && items.some((item) => item.id === activeSummaryId && item.type === 'summary')
            ? activeSummaryId
            : loadedAllSummary?.id || loadedSummaryItems[0]?.id || '';

      const nextGuidanceId =
        preferredId && items.some((item) => item.id === preferredId && item.type === 'guidance')
          ? preferredId
          : activeGuidanceId && items.some((item) => item.id === activeGuidanceId && item.type === 'guidance')
            ? activeGuidanceId
            : items.find((item) => item.type === 'guidance')?.id || '';

      if (nextSummaryId) {
        await loadWorkspaceItemDetail(nextSummaryId);
      } else {
        setActiveSummaryId('');
        setSummaryTitle('');
        setSummaryContent('');
      }

      if (nextGuidanceId) {
        await loadWorkspaceItemDetail(nextGuidanceId);
      } else {
        setActiveGuidanceId('');
        setGuidanceTitle('');
        setGuidanceContent('');
      }

      setSelectedGuidanceIds((previous) => {
        const valid = previous.filter((id) => items.some((item) => item.id === id && item.type === 'guidance'));
        if (valid.length > 0) return valid;
        return nextGuidanceId ? [nextGuidanceId] : [];
      });

      setPushPopover((previous) => ({
        ...previous,
        targetItemId:
          previous.targetItemId === '__new__'
            ? '__new__'
            : previous.targetItemId && items.some((item) => item.id === previous.targetItemId)
              ? previous.targetItemId
              : items.find((item) => item.type === previous.destinationType)?.id || '__new__',
      }));
    } catch (error: any) {
      setGlobalError(error?.message || '加载工作区失败');
    }
  };

  // ─── 表格分析：选中 dataset 文件时自动注册 datasource + 开启会话 ────────────
  useEffect(() => {
    if (!activeDataset || dataSessionId) return;
    // 已注册过则跳过，ref 防重，不触发重渲染
    if (registeredDatasourceIds.current[activeDataset.id] !== undefined) {
      // 仅重新开启会话（同一文件重新选中时）
      const datasourceId = registeredDatasourceIds.current[activeDataset.id];
      const startSession = async () => {
        try {
          const sessResp = await apiFetch('/api/v1/data-extract/sessions/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              notebook_id: notebook.id,
              notebook_title: notebookTitle,
              user_id: effectiveUser?.id || 'local',
              email: effectiveUser?.email || '',
              datasource_id: datasourceId,
            }),
          });
          const sessData = await parseJson<{ session: { id: string } }>(sessResp);
          setDataSessionId(sessData.session.id);
        } catch (err) {
          console.error('[TableAnalysis] session start failed', err);
        }
      };
      void startSession();
      return;
    }

    const initDataset = async () => {
      try {
        // 1. 注册 datasource（file.url = static_url，后端 _from_outputs_url 自动转本地路径）
        const regResp = await apiFetch('/api/v1/data-extract/datasources/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebookTitle,
            user_id: effectiveUser?.id || 'local',
            email: effectiveUser?.email || '',
            file_path: activeDataset.url,
            display_name: activeDataset.name,
          }),
        });
        const regData = await parseJson<{ datasource: { datasource_id: number } }>(regResp);
        const datasourceId = regData.datasource.datasource_id;
        registeredDatasourceIds.current[activeDataset.id] = datasourceId;

        // 2. 开启会话
        const sessResp = await apiFetch('/api/v1/data-extract/sessions/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebookTitle,
            user_id: effectiveUser?.id || 'local',
            email: effectiveUser?.email || '',
            datasource_id: datasourceId,
          }),
        });
        const sessData = await parseJson<{ session: { id: string } }>(sessResp);
        setDataSessionId(sessData.session.id);
      } catch (err) {
        console.error('[TableAnalysis] init failed', err);
      }
    };
    void initDataset();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDataset, dataSessionId]);

  useEffect(() => {
    void (async () => {
      setGlobalError('');
      setConversationId('');
      setChatMessages(welcomeMessages);
      setConversationList([]);
      clearConversationSourceRefs();
      setSelectedIds(new Set());
      setBoundDocIds([]);
      setDocuments([]);
      setActiveDocumentId('');
      setConversationActiveDocumentId('');
      setDocumentTitle('');
      setDocumentContent('');
      setDocumentFocusState(normalizeFocusState());
      setDocumentStashItems([]);
      setDocumentChangeLogs([]);
      setVersions([]);
      setWorkspaceItems([]);
      setActiveSummaryId('');
      setActiveGuidanceId('');
      setSummaryTitle('');
      setSummaryContent('');
      setGuidanceTitle('');
      setGuidanceContent('');
      setPushPopover((previous) => ({
        ...previous,
        show: false,
        targetDocId: '',
        targetSectionId: '',
        targetItemId: '',
      }));
      const [conversations] = await Promise.all([
        refreshConversationList(),
        refreshFiles(),
        refreshOutputs(),
      ]);
      await refreshWorkspaceItems();
      await refreshDocuments();
      const latestConversation = (conversations || [])[0];
      if (latestConversation?.id) {
        setConversationId(latestConversation.id);
        await loadConversationMessages(latestConversation.id);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebook.id]);

  useEffect(() => {
    if (!focusedMessageId) return;
    const timer = window.setTimeout(() => {
      setFocusedMessageId('');
      setFocusedSelectionText('');
    }, 2400);
    return () => window.clearTimeout(timer);
  }, [focusedMessageId]);

  useEffect(() => {
    if (!highlightedTraceId) return;
    const timer = window.setTimeout(() => setHighlightedTraceId(''), 3200);
    return () => window.clearTimeout(timer);
  }, [highlightedTraceId]);

  useEffect(() => {
    if (!captureFeedback) return;
    pushToast(captureFeedback, 'success', 2500);
    const timer = window.setTimeout(() => setCaptureFeedback(''), 2200);
    return () => window.clearTimeout(timer);
  }, [captureFeedback, pushToast]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_GUIDE_STORAGE_KEY, JSON.stringify(panelGuideVisibility));
  }, [panelGuideVisibility]);

  useEffect(() => {
    if (!activeOutput) return;
    setIsOutputHeaderCollapsed(false);
    ensureOutputContext(activeOutput);
  }, [activeOutput]);

  useEffect(() => {
    if (!activeOutput || activeOutput.target_type !== 'ppt') return;
    const slideCount = activePptOutline.length || 0;
    if (slideCount === 0) {
      setActivePptSlideIndex(0);
      return;
    }
    setActivePptSlideIndex((previous) => Math.min(Math.max(previous, 0), slideCount - 1));
  }, [activeOutput?.id, activeOutput?.target_type, activePptOutline]);

  useEffect(() => {
    setPptPagePrompt('');
  }, [activeOutput?.id, activePptSlideIndex]);

  useEffect(() => {
    setPptOutlineReadonlyOpen(false);
  }, [activeOutput?.id, activePptStage]);

  useEffect(() => {
    if (isPptOutlineChatStage) return;
    setPptOutlinePendingMessages([]);
  }, [isPptOutlineChatStage]);

  useEffect(() => {
    if (!highlightedTraceId || !docBodyRef.current) return;
    const target = docBodyRef.current.querySelector(`[data-trace-ids*="${highlightedTraceId}"]`);
    if (target instanceof HTMLElement) {
      target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [documentSections, highlightedTraceId]);

  useEffect(() => {
    const clearSelectionToolbar = () => {
      setSelectionToolbar((previous) => (previous.show ? { ...previous, show: false } : previous));
    };
    document.addEventListener('selectionchange', clearSelectionToolbar);
    return () => document.removeEventListener('selectionchange', clearSelectionToolbar);
  }, []);

  const ensureDocumentContent = async (documentId: string): Promise<ThinkFlowDocument | null> => {
    const existing = documents.find((item) => item.id === documentId);
    if (existing?.content) return existing;
    try {
      return await loadDocumentDetail(documentId);
    } catch {
      return existing || null;
    }
  };
  ensureDocumentContentRef.current = ensureDocumentContent;

  const persistConversationWorkspaceState = async ({
    targetConversationId = conversationId,
    sourceRefs = conversationSourceRefs,
    activeDocId = conversationActiveDocumentId,
  }: {
    targetConversationId?: string;
    sourceRefs?: ConversationSourceRef[];
    activeDocId?: string;
  }) => {
    if (!targetConversationId) return null;
    const response = await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/workspace-state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notebook_id: notebook.id,
        notebook_title: notebookTitle,
        user_id: effectiveUser?.id || 'local',
        email: effectiveUser?.email || '',
        source_refs: sourceRefs,
        active_document_id: activeDocId || '',
      }),
    });
    const data = await parseJson<{ state: { source_refs?: ConversationSourceRef[]; active_document_id?: string } }>(response);
    const refs = data.state.source_refs || [];
    setConversationSourceRefs(refs);
    setSelectedIds(new Set(refs.filter((ref) => ref.type === 'material').map((ref) => ref.id)));
    setBoundDocIds(refs.filter((ref) => ref.type === 'document' || ref.type === 'output_document').map((ref) => ref.id));
    setConversationActiveDocumentId(data.state.active_document_id || '');
    return data.state;
  };

  const loadConversationWorkspaceState = async (targetConversationId: string) => {
    if (!targetConversationId) return null;
    try {
      const response = await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/workspace-state?${notebookQuery}`);
      const data = await parseJson<{ state: { source_refs?: ConversationSourceRef[]; active_document_id?: string } }>(response);
      const refs = data.state.source_refs || [];
      const storedActiveId = String(data.state.active_document_id || '').trim();
      const fallbackActiveId =
        storedActiveId ||
        activeDocumentId ||
        documents[0]?.id ||
        '';
      setConversationSourceRefs(refs);
      setConversationActiveDocumentId(fallbackActiveId);
      setSelectedIds(new Set(refs.filter((ref) => ref.type === 'material').map((ref) => ref.id)));
      setBoundDocIds(refs.filter((ref) => ref.type === 'document' || ref.type === 'output_document').map((ref) => ref.id));
      if (!storedActiveId && fallbackActiveId) {
        void persistConversationWorkspaceState({
          targetConversationId,
          sourceRefs: refs,
          activeDocId: fallbackActiveId,
        }).catch(() => {});
      }
      return { source_refs: refs, active_document_id: fallbackActiveId };
    } catch (error: any) {
      setConversationSourceRefs([]);
      setBoundDocIds([]);
      setConversationActiveDocumentId(activeDocumentId || documents[0]?.id || '');
      setGlobalError(error?.message || '加载对话工作区状态失败');
      return null;
    }
  };

  const loadConversationMessages = async (targetConversationId: string) => {
    setConversationId(targetConversationId);
    const response = await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/messages`);
    const data = await parseJson<{ messages?: ConversationHistoryMessage[] }>(response);
    const rows = Array.isArray(data?.messages) ? data.messages : [];
    setChatMessages(
      rows.length > 0
        ? rows.map((item, index) => ({
            id: item.id || `history_${index}`,
            role: item.role === 'assistant' ? 'assistant' : 'user',
            content: item.content || '',
            time: formatThinkFlowTime(item.created_at),
          }))
        : welcomeMessages,
    );
    await loadConversationWorkspaceState(targetConversationId);
  };

  const refreshConversationList = async () => {
    setConversationListLoading(true);
    try {
      const params = new URLSearchParams({
        email: effectiveUser?.email || effectiveUser?.id || 'local',
        user_id: effectiveUser?.id || 'local',
        notebook_id: notebook.id,
      });
      const response = await apiFetch(`/api/v1/kb/conversations?${params.toString()}`);
      const data = await parseJson<{ conversations?: ConversationListItem[] }>(response);
      const rows = Array.isArray(data?.conversations) ? data.conversations : [];
      setConversationList(rows);
      return rows;
    } catch {
      setConversationList([]);
      return [] as ConversationListItem[];
    } finally {
      setConversationListLoading(false);
    }
  };

  const createConversation = async () => {
    const response = await apiFetch('/api/v1/kb/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: effectiveUser?.email || effectiveUser?.id || 'local',
        user_id: effectiveUser?.id || 'local',
        notebook_id: notebook.id,
      }),
    });
    const data = await parseJson<{ conversation_id?: string; conversation?: ConversationListItem }>(response);
    const nextId = String(data?.conversation_id || '').trim();
    if (!nextId) {
      throw new Error('创建新对话失败');
    }
    await refreshConversationList();
    setConversationId(nextId);
    setChatMessages(welcomeMessages);
    setChatInput('');
    setSelectedMessageIds([]);
    setMultiSelectPrompt('');
    setBoundDocIds([]);
    clearConversationSourceRefs();
    const nextActiveDocId = activeDocumentId || documents[0]?.id || '';
    setConversationActiveDocumentId(nextActiveDocId);
    await persistConversationWorkspaceState({
      targetConversationId: nextId,
      sourceRefs: [],
      activeDocId: nextActiveDocId,
    });
    return nextId;
  };

  const ensureConversationId = async () => {
    if (conversationId) return conversationId;
    try {
      return await createConversation();
    } catch {}
    return '';
  };

  const appendConversationMessages = async (messages: Array<{ role: 'user' | 'assistant'; content: string }>) => {
    const rows = messages.map((item) => ({ role: item.role, content: String(item.content || '').trim() })).filter((item) => item.content);
    if (rows.length === 0) return;
    const targetConversationId = await ensureConversationId();
    if (!targetConversationId) return;
    try {
      await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: rows }),
      });
      await refreshConversationList();
    } catch {}
  };

  const handlePreviewSource = async (file: KnowledgeFile) => {
    setSourcePreviewFile(file);
    setSourcePreviewOpen(true);
    setSourcePreviewContent('');
    setSourcePreviewLoading(true);
    try {
      const response = await apiFetch('/api/v1/kb/get-source-display-content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          user_id: effectiveUser?.id || 'local',
          path: file.url || file.id,
          email: effectiveUser?.email || '',
        }),
      });
      const data = await parseJson<{ content?: string }>(response);
      setSourcePreviewContent(data?.content || '（无内容）');
    } catch (error: any) {
      setSourcePreviewContent(`加载失败: ${error?.message || '未知错误'}`);
    } finally {
      setSourcePreviewLoading(false);
    }
  };

  const handleDeleteSource = async (file: KnowledgeFile) => {
    // 乐观删除：先从前端列表移除，再异步调后端
    setFiles((prev) => prev.filter((f) => f.id !== file.id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.delete(file.id);
      return next;
    });
    // 如果删的是当前激活的 dataset，退出表格分析模式
    if (activeDataset?.id === file.id) {
      setActiveDataset(null);
      setChatMode('chat');
      setDataSessionId(null);
    }

    try {
      await apiFetch('/api/v1/kb/delete-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          file_path: file.url || file.id,
        }),
      });
    } catch (error: any) {
      // 删除失败，恢复列表
      setGlobalError(error?.message || '删除来源失败');
      await refreshFiles();
    }
  };

  const handleReEmbedSource = async (file: KnowledgeFile) => {
    try {
      await apiFetch('/api/v1/kb/reembed-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          file_path: file.url || file.id,
        }),
      });
      await refreshFiles();
    } catch {
      pushToast('入库失败，请稍后重试', 'error', 4000);
    }
  };

  const openHistoryPanel = async () => {
    setLeftTab('conversations');
    setHistoryLoading(true);
    try {
      const rows = await refreshConversationList();
      setHistoryConversations(rows);
    } catch (error: any) {
      setGlobalError(error?.message || '加载历史对话失败');
      setHistoryConversations(conversationList);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleNewConversation = () => {
    void createConversation().catch((error: any) => {
      setGlobalError(error?.message || '创建新对话失败');
    });
  };

  const enterOutputWorkspace = (mode: WorkspaceMode = 'output_focus') => {
    setRightPanelOpen(true);
    setRightMode('outline');
    setWorkspaceMode(mode);
  };
  enterOutputWorkspaceRef.current = enterOutputWorkspace;

  const exitOutputWorkspace = () => {
    setPptSourceLockIntent(null);
    setDirectOutputIntent(null);
    setWorkspaceMode('normal');
    setRightMode('doc');
    setRightPanelOpen(true);
  };

  const toggleSource = (fileId: string) => {
    // 当选中 dataset（CSV/Excel）时，自动激活表格分析模式
    const selected = files.find((f) => f.id === fileId);
    if (!selected) return;
    const nextRefs = conversationSourceRefs.some((ref) => ref.type === 'material' && ref.id === fileId)
      ? conversationSourceRefs.filter((ref) => !(ref.type === 'material' && ref.id === fileId))
      : [
          ...conversationSourceRefs,
          {
            id: selected.id,
            type: 'material' as const,
            title: selected.name || '未命名素材',
            path: resolveFileUrl(selected),
          },
        ];
    setConversationSourceRefs(nextRefs);
    setSelectedIds(new Set(nextRefs.filter((ref) => ref.type === 'material').map((ref) => ref.id)));
    void persistConversationWorkspaceState({ sourceRefs: nextRefs }).catch((error: any) => {
      setGlobalError(error?.message || '更新对话来源失败');
    });
    if (selected?.type === 'dataset') {
      setActiveDataset(selected);
      setChatMode('table-analysis');
      if (selected.id !== activeDataset?.id) {
        setDataSessionId(null); // 切到新的 dataset 时，重置并准备新会话
      }
    }
  };

  const setConversationActiveDocument = async (documentId: string) => {
    const previousTitle = conversationActiveDocument?.title || '未设置';
    const nextDoc = documents.find((item) => item.id === documentId);
    if (!nextDoc) return;
    setConversationActiveDocumentId(documentId);
    await persistConversationWorkspaceState({ activeDocId: documentId });
    setChatMessages((previous) => [
      ...previous,
      {
        id: `system_active_doc_${Date.now()}`,
        role: 'system',
        content: `切换活跃文档：${previousTitle} → ${nextDoc.title || '未命名文档'}`,
        time: formatThinkFlowTime(new Date()),
        meta: { type: 'stage_change' },
      },
    ]);
  };

  const toggleBoundDoc = (documentId: string) => {
    const document = documents.find((item) => item.id === documentId);
    if (!document) return;
    const sourceType = document.document_type === 'output_doc' ? 'output_document' : 'document';
    const exists = conversationSourceRefs.some((ref) => ref.id === documentId && (ref.type === 'document' || ref.type === 'output_document'));
    const nextRefs = exists
      ? conversationSourceRefs.filter((ref) => !(ref.id === documentId && (ref.type === 'document' || ref.type === 'output_document')))
      : [
          ...conversationSourceRefs,
          {
            id: document.id,
            type: sourceType,
            title: document.title || '未命名文档',
          },
        ];
    setConversationSourceRefs(nextRefs);
    setBoundDocIds(nextRefs.filter((ref) => ref.type === 'document' || ref.type === 'output_document').map((ref) => ref.id));
    void persistConversationWorkspaceState({ sourceRefs: nextRefs }).catch((error: any) => {
      setGlobalError(error?.message || '更新对话参考文档失败');
    });
    setRightPanelOpen(true);
    setActiveDocumentId(documentId);
    void loadDocumentDetail(documentId);
  };

  const focusSourceByReference = (reference?: CitationReference, fallbackName?: string) => {
    const candidateNames = [
      reference?.fileName,
      fallbackName,
      reference?.filePath ? reference.filePath.split('/').pop() : '',
    ]
      .map((item) => String(item || '').trim())
      .filter(Boolean);

    const target = files.find((file) =>
      candidateNames.some((name) => file.name === name || resolveFileUrl(file).includes(name)),
    );

    if (!target) return;

    setLeftTab('materials');
    setSelectedIds((previous) => {
      if (previous.has(target.id)) return previous;
      const next = new Set(previous);
      next.add(target.id);
      return next;
    });
  };

  const renderSourceTooltip = (title: string, preview: string, reference?: CitationReference) => {
    if (!title && !preview) return null;
    return (
      <span className="thinkflow-source-tooltip" role="tooltip">
        {title ? <span className="thinkflow-source-tooltip-title">{title}</span> : null}
        {preview ? <span className="thinkflow-source-tooltip-preview">{preview}</span> : null}
        {reference?.chunkIndex !== undefined && reference?.chunkIndex !== null ? (
          <span className="thinkflow-source-tooltip-meta">Chunk #{Number(reference.chunkIndex) + 1}</span>
        ) : null}
      </span>
    );
  };

  const renderTextWithCitations = (text: string, message: ThinkFlowMessage) =>
    splitTextWithCitations(text).map((part, index) => {
      if (part.type === 'text') return <React.Fragment key={`text_${index}`}>{part.value}</React.Fragment>;

      const { reference, title, preview } = getCitationMeta(message, part.value);
      const hasMeta = Boolean(title || preview);
      return (
        <button
          key={`cite_${part.value}_${index}`}
          type="button"
          className={`thinkflow-citation ${hasMeta ? 'has-tooltip' : ''}`}
          onClick={() => focusSourceByReference(reference, title)}
        >
          [{part.value}]
          {renderSourceTooltip(title, preview, reference)}
        </button>
      );
    });

  const renderMessageTextDecorations = (text: string, message: ThinkFlowMessage) => {
    const highlightText = message.id === focusedMessageId ? focusedSelectionText.trim() : '';
    if (!highlightText) return renderTextWithCitations(text, message);
    const focusIndex = text.indexOf(highlightText);
    if (focusIndex < 0) return renderTextWithCitations(text, message);

    const before = text.slice(0, focusIndex);
    const selected = text.slice(focusIndex, focusIndex + highlightText.length);
    const after = text.slice(focusIndex + highlightText.length);

    return (
      <>
        {renderTextWithCitations(before, message)}
        <mark className="thinkflow-message-focus-mark">{renderTextWithCitations(selected, message)}</mark>
        {renderTextWithCitations(after, message)}
      </>
    );
  };

  const injectCitationsIntoNode = (node: React.ReactNode, message: ThinkFlowMessage): React.ReactNode => {
    if (typeof node === 'string') return renderMessageTextDecorations(node, message);
    if (Array.isArray(node)) {
      return node.map((child, index) => <React.Fragment key={index}>{injectCitationsIntoNode(child, message)}</React.Fragment>);
    }
    if (!React.isValidElement(node)) return node;

    const element = node as React.ReactElement<{ children?: React.ReactNode }>;
    const typeName = typeof element.type === 'string' ? element.type : '';
    if (typeName === 'code' || typeName === 'pre') return element;

    return React.cloneElement(
      element,
      element.props,
      injectCitationsIntoNode(element.props.children, message),
    );
  };

  const renderMessageMarkdown = (message: ThinkFlowMessage) => (
    <div className={`thinkflow-message-markdown ${message.role === 'assistant' ? 'is-assistant' : 'is-user'}`}>
      <ReactMarkdown
        components={{
          h1: ({ children, ...props }: any) => <h1 {...props}>{injectCitationsIntoNode(children, message)}</h1>,
          h2: ({ children, ...props }: any) => <h2 {...props}>{injectCitationsIntoNode(children, message)}</h2>,
          h3: ({ children, ...props }: any) => <h3 {...props}>{injectCitationsIntoNode(children, message)}</h3>,
          h4: ({ children, ...props }: any) => <h4 {...props}>{injectCitationsIntoNode(children, message)}</h4>,
          h5: ({ children, ...props }: any) => <h5 {...props}>{injectCitationsIntoNode(children, message)}</h5>,
          h6: ({ children, ...props }: any) => <h6 {...props}>{injectCitationsIntoNode(children, message)}</h6>,
          p: ({ children, ...props }: any) => <p {...props}>{injectCitationsIntoNode(children, message)}</p>,
          li: ({ children, ...props }: any) => <li {...props}>{injectCitationsIntoNode(children, message)}</li>,
          blockquote: ({ children, ...props }: any) => (
            <blockquote {...props}>{injectCitationsIntoNode(children, message)}</blockquote>
          ),
          strong: ({ children, ...props }: any) => <strong {...props}>{injectCitationsIntoNode(children, message)}</strong>,
          em: ({ children, ...props }: any) => <em {...props}>{injectCitationsIntoNode(children, message)}</em>,
          a: ({ children, ...props }: any) => (
            <a {...props} target="_blank" rel="noreferrer">
              {injectCitationsIntoNode(children, message)}
            </a>
          ),
        }}
      >
        {message.content}
      </ReactMarkdown>
      {message.meta?.type === 'ppt_outline_draft' ? (
        <div className="thinkflow-inline-outline-card" data-testid="ppt-outline-inline-card">
          <div className="thinkflow-inline-outline-card-head">
            <div>
              <span className="thinkflow-output-workspace-kicker">候选修改</span>
              <h4>候选改动对比</h4>
            </div>
            <div className="thinkflow-inline-outline-card-actions">
              <button type="button" className="thinkflow-generate-btn" onClick={() => void applyPptOutlineDraft()} disabled={outlineSaving}>
                {outlineSaving ? '推送中...' : '推送这版'}
              </button>
            </div>
          </div>
          {message.meta.changeSummary ? (
            <div className="thinkflow-inline-outline-card-summary">{message.meta.changeSummary}</div>
          ) : null}
          {(message.meta.intentSummary?.mode && message.meta.intentSummary.mode !== 'none') ? (
            <div className="thinkflow-inline-outline-card-intent">
              <strong>本轮意图：</strong>
              <span>
                {message.meta.intentSummary.mode === 'mixed'
                  ? '全局规则 + 页级修改'
                  : message.meta.intentSummary.mode === 'global'
                    ? '全局规则'
                    : '页级修改'}
              </span>
            </div>
          ) : null}
          <div className="thinkflow-inline-outline-rule-block">
            <div className="thinkflow-inline-outline-rule-title">当前生效规则</div>
            <div className="thinkflow-inline-outline-rule-list">
              {(message.meta.appliedDirectives || []).length > 0 ? (
                (message.meta.appliedDirectives || []).map((directive: OutlineDirective) => (
                  <span key={`applied_${directive.id}`} className="thinkflow-inline-outline-chip">
                    {directive.label}
                  </span>
                ))
              ) : (
                <span className="thinkflow-inline-outline-empty">当前还没有全局规则。</span>
              )}
            </div>
          </div>
          {(message.meta.directiveDiff?.totalCount || 0) > 0 ? (
            <div className="thinkflow-inline-outline-rule-block">
              <div className="thinkflow-inline-outline-rule-title">规则改动</div>
              <div className="thinkflow-inline-outline-rule-list">
                {message.meta.directiveDiff.entries.map((entry: any) => (
                  <div key={entry.key} className={`thinkflow-inline-outline-diff-line is-${entry.kind}`}>
                    <span>{getPptDirectiveDiffKindLabel(entry.kind)}</span>
                    <strong>{entry.label}</strong>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {(message.meta.outlineDiff?.totalCount || 0) > 0 ? (
            <div className="thinkflow-inline-outline-rule-list">
              {message.meta.outlineDiff.modifiedCount > 0 ? (
                <span className="thinkflow-inline-outline-chip">
                  {`修改 ${message.meta.outlineDiff.modifiedCount} 页`}
                </span>
              ) : null}
              {message.meta.outlineDiff.addedCount > 0 ? (
                <span className="thinkflow-inline-outline-chip">
                  {`新增 ${message.meta.outlineDiff.addedCount} 页`}
                </span>
              ) : null}
              {message.meta.outlineDiff.removedCount > 0 ? (
                <span className="thinkflow-inline-outline-chip">
                  {`删除 ${message.meta.outlineDiff.removedCount} 页`}
                </span>
              ) : null}
            </div>
          ) : null}
          {(message.meta.outlineDiff?.totalCount || 0) > 0 ? (
            <div className="thinkflow-inline-outline-diff-list">
              {message.meta.outlineDiff.entries.map((entry: any) => (
                <article key={entry.key} className={`thinkflow-inline-outline-diff-item is-${entry.kind}`}>
                  <div className="thinkflow-inline-outline-diff-item-head">
                    <span>{getPptOutlineDiffKindLabel(entry.kind)}</span>
                    <strong>第 {entry.pageNum} 页</strong>
                    <span>{entry.title}</span>
                  </div>
                  {entry.detailLines?.length > 0 ? (
                    <ul>
                      {entry.detailLines.map((line: string) => (
                        <li key={`${entry.key}_${line}`}>{line}</li>
                      ))}
                    </ul>
                  ) : null}
                </article>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  const renderOutlineChatTopPanel = () => {
    if (!isPptOutlineChatStage) return null;
    return (
      <div className="thinkflow-outline-chat-top-panel">
        <div className="thinkflow-outline-chat-top-head">
          <span className="thinkflow-output-workspace-kicker">当前生效规则</span>
          <strong>这轮大纲修改会先在对话里生成候选稿，再由你决定是否推送。</strong>
        </div>
        <div className="thinkflow-inline-outline-rule-list">
          {activePptGlobalDirectives.length > 0 ? (
            activePptGlobalDirectives.map((directive) => (
              <span key={`top_${directive.id}`} className="thinkflow-inline-outline-chip">
                {directive.label}
              </span>
            ))
          ) : (
            <span className="thinkflow-inline-outline-empty">当前还没有全局规则，直接在下面说即可，例如“所有页标题使用黑色”。</span>
          )}
        </div>
      </div>
    );
  };

  const renderSourceReferences = (message: ThinkFlowMessage) => {
    const entries = Object.entries(message.sourceMapping || {}).sort((a, b) => Number(a[0]) - Number(b[0]));
    if (entries.length === 0) return null;

    return (
      <div className="thinkflow-source-strip">
        <div className="thinkflow-source-strip-label">检索来源</div>
        <div className="thinkflow-source-strip-list">
          {entries.map(([sourceNumber, sourceName]) => {
            const { reference, title, preview } = getCitationMeta(message, sourceNumber);
            return (
              <button
                key={sourceNumber}
                type="button"
                className="thinkflow-source-chip"
                onClick={() => focusSourceByReference(reference, sourceName)}
              >
                <span className="thinkflow-source-chip-index">[{sourceNumber}]</span>
                <span className="thinkflow-source-chip-name">{sourceName}</span>
                {renderSourceTooltip(title || sourceName, preview, reference)}
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  const openPushPopoverForContent = ({
    content,
    rect,
    sourceEntries,
    preferredDestination = 'document',
    prompt = '',
    preset = 'default',
  }: {
    content: string;
    rect: DOMRect | Pick<DOMRect, 'left' | 'right' | 'top'>;
    sourceEntries: PushSourceEntry[];
    preferredDestination?: PushDestinationType;
    prompt?: string;
    preset?: PushPreset;
  }) => {
    const trimmed = String(content || '').trim();
    if (!trimmed) return;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const margin = viewportWidth <= 1120 ? 10 : 16;
    const popoverWidth = Math.min(viewportWidth - margin * 2, viewportWidth <= 1120 ? 420 : 360);
    const popoverHeight = Math.min(viewportHeight - margin * 2, viewportWidth <= 1120 ? 520 : 620);
    const preferredX = rect.right + 12;
    const fallbackX = rect.left - popoverWidth - 12;
    const nextX = Math.min(
      Math.max(margin, preferredX + popoverWidth > viewportWidth - margin ? fallbackX : preferredX),
      viewportWidth - popoverWidth - margin,
    );
    const nextY = Math.min(
      Math.max(margin, rect.top - 14),
      viewportHeight - popoverHeight - margin,
    );
    setRightPanelOpen(true);
    setRightMode('doc');
    setSelectionToolbar((previous) => ({ ...previous, show: false }));
    const defaultTargetType = getDefaultPushTarget(documentFocusState);
    const defaultTargetDocId = conversationActiveDocumentId || activeDocumentId || documents[0]?.id || '';
    if (preferredDestination === 'document' && !defaultTargetDocId) {
      setGlobalError('请先在右侧选择或创建一份活跃文档，再推送到文档。');
      return;
    }
    setPushPopover({
      show: true,
      x: nextX,
      y: nextY,
      preset,
      destinationType: preferredDestination,
      targetType: defaultTargetType,
      targetSectionId: documentFocusState.section_ids[0] || documentSections[0]?.id || '',
      newSectionTitle: '',
      transform: 'ai_append',
      targetDocId: defaultTargetDocId,
      targetItemId:
        preferredDestination === 'summary'
          ? (activeSummary?.summary_kind === 'item' ? activeSummaryId : '') || itemSummaryItems[0]?.id || '__new__'
          : preferredDestination === 'guidance'
            ? activeGuidanceId || guidanceItems[0]?.id || '__new__'
            : '',
      newTitle: '',
      titleMode: 'ai',
      mode: 'organize',
      prompt,
      sourceContent: trimmed,
      sourceEntries,
    });
    setPushSubmitting(false);
    setPushStatusText('');
    setPushError('');
  };

  const openPushPopover = (message: ThinkFlowMessage, event: React.MouseEvent<HTMLButtonElement>) => {
    openPushPopoverForContent({
      content: message.content,
      rect: event.currentTarget.getBoundingClientRect(),
      sourceEntries: [
        {
          messageId: message.id,
          role: message.role,
          time: message.time,
          selectionText: message.content,
          kind: 'message',
        },
      ],
      preferredDestination: 'document',
      preset: 'default',
    });
  };

  const openQAPushPopover = (message: ThinkFlowMessage, event: React.MouseEvent<HTMLButtonElement>) => {
    const currentIndex = chatMessages.findIndex((item) => item.id === message.id);
    const qaEntries: PushSourceEntry[] = [];
    const parts: string[] = [];
    const previousMessage = currentIndex > 0 ? chatMessages[currentIndex - 1] : null;
    const nextMessage = currentIndex >= 0 ? chatMessages[currentIndex + 1] : null;

    const questionMessage =
      message.role === 'user'
        ? message
        : previousMessage?.role === 'user'
          ? previousMessage
          : null;
    const answerMessage =
      message.role === 'assistant'
        ? message
        : nextMessage?.role === 'assistant'
          ? nextMessage
          : null;

    if (!questionMessage || !answerMessage) {
      setGlobalError('“本轮沉淀”需要一组完整的问答，只有问题或只有回答时不能直接使用。');
      return;
    }

    qaEntries.push({
      messageId: questionMessage.id,
      role: questionMessage.role,
      time: questionMessage.time,
      selectionText: questionMessage.content,
      kind: 'qa',
    });
    parts.push(`用户问题：\n${questionMessage.content}`);

    qaEntries.push({
      messageId: answerMessage.id,
      role: answerMessage.role,
      time: answerMessage.time,
      selectionText: answerMessage.content,
      kind: 'qa',
    });
    parts.push(`AI回答：\n${answerMessage.content}`);

    openPushPopoverForContent({
      content: parts.join('\n\n'),
      rect: event.currentTarget.getBoundingClientRect(),
      sourceEntries: qaEntries,
      preferredDestination: 'document',
      prompt: '提炼这一轮问答的核心结论、关键依据与待确认点。',
      preset: 'qa',
    });
  };

  const handleChatSelectionMouseUp = () => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      setSelectionToolbar((previous) => ({ ...previous, show: false }));
      return;
    }

    const selectedText = selection.toString().trim();
    if (!selectedText) {
      setSelectionToolbar((previous) => ({ ...previous, show: false }));
      return;
    }

    const range = selection.getRangeAt(0);
    const startElement = range.startContainer.parentElement;
    const endElement = range.endContainer.parentElement;
    const startMessage = startElement?.closest('[data-message-id]') as HTMLElement | null;
    const endMessage = endElement?.closest('[data-message-id]') as HTMLElement | null;
    if (!startMessage || !endMessage || startMessage.dataset.messageId !== endMessage.dataset.messageId) {
      setSelectionToolbar((previous) => ({ ...previous, show: false }));
      return;
    }

    const messageId = startMessage.dataset.messageId || '';
    const rect = range.getBoundingClientRect();
    if (!messageId || !rect.width) {
      setSelectionToolbar((previous) => ({ ...previous, show: false }));
      return;
    }

    setSelectionToolbar({
      show: true,
      x: rect.left + rect.width / 2,
      y: Math.max(rect.top - 12, 80),
      messageId,
      content: selectedText,
    });
  };

  const handleSelectionCopy = async () => {
    if (!selectionToolbar.content) return;
    try {
      await navigator.clipboard.writeText(selectionToolbar.content);
      window.getSelection()?.removeAllRanges();
      setSelectionToolbar((previous) => ({ ...previous, show: false }));
    } catch (error: any) {
      setGlobalError(error?.message || '复制失败');
    }
  };

  const handleSelectionPush = () => {
    const message = chatMessages.find((item) => item.id === selectionToolbar.messageId);
    if (!message || !selectionToolbar.content) return;
    window.getSelection()?.removeAllRanges();
    const rect = {
      left: selectionToolbar.x,
      right: selectionToolbar.x,
      top: selectionToolbar.y,
    } as Pick<DOMRect, 'left' | 'right' | 'top'>;
    openPushPopoverForContent({
      content: selectionToolbar.content,
      rect,
      sourceEntries: [
        {
          messageId: message.id,
          role: message.role,
          time: message.time,
          selectionText: selectionToolbar.content,
          kind: 'selection',
        },
      ],
      preferredDestination: 'document',
    });
  };

  const openMultiMessagePush = (anchor: HTMLElement | null) => {
    const selectedMessages = chatMessages.filter((item) => selectedMessageIds.includes(item.id));
    if (selectedMessages.length === 0) return;
    const content = selectedMessages
      .map((item) => `${item.role === 'assistant' ? 'AI' : '你'}：\n${item.content}`)
      .join('\n\n');
    const sourceEntries = selectedMessages.map((item) => ({
      messageId: item.id,
      role: item.role,
      time: item.time,
      selectionText: item.content,
      kind: 'multi' as const,
    }));
    const rect = anchor?.getBoundingClientRect() || ({ left: window.innerWidth / 2, right: window.innerWidth / 2, top: window.innerHeight - 220 } as Pick<
      DOMRect,
      'left' | 'right' | 'top'
    >);
    openPushPopoverForContent({
      content,
      rect,
      sourceEntries,
      preferredDestination: 'document',
      prompt: multiSelectPrompt,
      preset: 'default',
    });
  };

  const renderDocumentTextWithBadges = (node: React.ReactNode): React.ReactNode => {
    if (typeof node === 'string') {
      return splitTextWithStatusTokens(node).map((part, index) =>
        part.type === 'text' ? (
          <React.Fragment key={`doc_text_${index}`}>{part.value}</React.Fragment>
        ) : (
          <span key={`doc_status_${part.value}_${index}`} className={`thinkflow-doc-badge is-${DOC_STATUS_CLASSNAMES[part.value] || 'default'}`}>
            {DOC_STATUS_BADGES[part.value] || part.value}
          </span>
        ),
      );
    }
    if (Array.isArray(node)) {
      return node.map((child, index) => <React.Fragment key={index}>{renderDocumentTextWithBadges(child)}</React.Fragment>);
    }
    if (!React.isValidElement(node)) return node;
    const element = node as React.ReactElement<{ children?: React.ReactNode }>;
    const typeName = typeof element.type === 'string' ? element.type : '';
    if (typeName === 'code' || typeName === 'pre') return element;
    return React.cloneElement(
      element,
      element.props,
      renderDocumentTextWithBadges(element.props.children),
    );
  };

  const jumpToChatMessage = (trace: DocumentPushTrace) => {
    const primarySource = (trace.source_refs || []).find((item) => item.message_id);
    const messageId = primarySource?.message_id;
    if (!messageId) return;
    const target = messageRefs.current[messageId];
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setFocusedMessageId(messageId);
    setFocusedSelectionText(primarySource?.selection_text || '');
  };

  const renderTraceSummary = (trace: DocumentPushTrace) => {
    const primarySource = (trace.source_refs || []).find((item) => item.message_id) || trace.source_refs?.[0];
    const fileNames = (primarySource?.source_file_names || []).filter(Boolean).slice(0, 3);
    const sourceRole = primarySource?.message_role === 'user' ? '你' : primarySource?.message_role === 'assistant' ? 'AI' : '对话';
    const timeLabel = primarySource?.message_time || '';
    const preview = primarySource?.selection_text || trace.text_preview || '';
    return (
      <button key={trace.id} type="button" className="thinkflow-doc-trace" onClick={() => jumpToChatMessage(trace)}>
        <span className="thinkflow-doc-trace-title">
          来源 · {sourceRole}
          {timeLabel ? ` · ${timeLabel}` : ''}
        </span>
        {fileNames.length > 0 ? <span className="thinkflow-doc-trace-files">{fileNames.join(' / ')}</span> : null}
        {preview ? <span className="thinkflow-doc-trace-preview">{preview.slice(0, 180)}</span> : null}
      </button>
    );
  };

  const updateDisplayedDocumentFocus = async (nextFocus: ThinkFlowFocusState) => {
    if (!activeDocumentId) return;
    setDocumentFocusState(nextFocus);
    try {
      const response = await apiFetch(`/api/v1/kb/documents/${activeDocumentId}/focus`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          focus_state: nextFocus,
        }),
      });
      const data = await parseJson<{ focus_state: ThinkFlowFocusState }>(response);
      setDocumentFocusState(normalizeFocusState(data.focus_state));
      setDocuments((previous) =>
        previous.map((item) => (item.id === activeDocumentId ? { ...item, focus_state: normalizeFocusState(data.focus_state) } : item)),
      );
    } catch (error: any) {
      setGlobalError(error?.message || '更新文档焦点失败');
      await loadDocumentDetail(activeDocumentId);
    }
  };

  const toggleSectionFocus = (sectionId: string, heading?: string) => {
    const current = normalizeFocusState(documentFocusState);
    const isSelected = current.type === 'sections' && current.section_ids.includes(sectionId);
    const nextIds = isSelected
      ? current.section_ids.filter((id) => id !== sectionId)
      : current.type === 'sections'
        ? [...current.section_ids, sectionId]
        : [sectionId];
    const selectedHeadings = documentSections
      .filter((section) => nextIds.includes(section.id))
      .map((section) => section.heading || heading || '章节');
    const focusLabel = activeDocument?.document_type === 'output_doc' ? '确认模块' : '焦点';
    const description = nextIds.length === 0
      ? `${focusLabel}：全文`
      : `${focusLabel}：${selectedHeadings.map((item) => `§ ${item}`).join(' + ')}`;
    void updateDisplayedDocumentFocus(
      normalizeFocusState({
        type: nextIds.length > 0 ? 'sections' : 'full',
        section_ids: nextIds,
        stash_item_ids: [],
        description,
      }),
    );
  };

  const renderDocumentSection = (section: ReturnType<typeof buildDocumentSections>[number]) => {
    const shouldHighlight = section.traces.some((trace) => trace.id === highlightedTraceId);
    const isFocused = documentFocusState.type === 'sections' && documentFocusState.section_ids.includes(section.id);
    const isOutputDocument = activeDocument?.document_type === 'output_doc';
    const moduleActionLabel = isFocused ? '已确认并入此模块' : '确认下次并入修改此模块';
    const activateDocumentSection = () => {
      toggleSectionFocus(section.id, section.heading);
    };
    const handleDocumentSectionClick = (event: React.MouseEvent<HTMLElement>) => {
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest('button, a, input, textarea, select')) return;
      activateDocumentSection();
    };
    const handleDocumentSectionKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      activateDocumentSection();
    };
    return (
      <section
        key={section.id}
        className={`thinkflow-doc-section ${isOutputDocument ? 'is-output-module' : ''} ${shouldHighlight ? 'is-highlighted' : ''} ${isFocused ? 'is-focused' : ''}`}
        data-section-id={section.id}
        data-trace-ids={section.traces.map((trace) => trace.id).join(',')}
        role="button"
        tabIndex={0}
        onClick={handleDocumentSectionClick}
        onKeyDown={handleDocumentSectionKeyDown}
      >
        {isOutputDocument ? (
          <button
            type="button"
            className="thinkflow-doc-module-confirm"
            onClick={(event) => {
              event.stopPropagation();
              toggleSectionFocus(section.id, section.heading);
            }}
          >
            {moduleActionLabel}
          </button>
        ) : null}
        <div className="thinkflow-doc-render">
          <ReactMarkdown
            components={{
              h1: ({ children, ...props }: any) => <h1 {...props}>{renderDocumentTextWithBadges(children)}</h1>,
              h2: ({ children, ...props }: any) => <h2 {...props}>{renderDocumentTextWithBadges(children)}</h2>,
              h3: ({ children, ...props }: any) => <h3 {...props}>{renderDocumentTextWithBadges(children)}</h3>,
              h4: ({ children, ...props }: any) => <h4 {...props}>{renderDocumentTextWithBadges(children)}</h4>,
              h5: ({ children, ...props }: any) => <h5 {...props}>{renderDocumentTextWithBadges(children)}</h5>,
              h6: ({ children, ...props }: any) => <h6 {...props}>{renderDocumentTextWithBadges(children)}</h6>,
              p: ({ children, ...props }: any) => <p {...props}>{renderDocumentTextWithBadges(children)}</p>,
              li: ({ children, ...props }: any) => <li {...props}>{renderDocumentTextWithBadges(children)}</li>,
              blockquote: ({ children, ...props }: any) => <blockquote {...props}>{renderDocumentTextWithBadges(children)}</blockquote>,
              strong: ({ children, ...props }: any) => <strong {...props}>{renderDocumentTextWithBadges(children)}</strong>,
              em: ({ children, ...props }: any) => <em {...props}>{renderDocumentTextWithBadges(children)}</em>,
              a: ({ children, ...props }: any) => (
                <a {...props} target="_blank" rel="noreferrer">
                  {renderDocumentTextWithBadges(children)}
                </a>
              ),
            }}
          >
            {section.content}
          </ReactMarkdown>
        </div>
        {section.traces.length > 0 ? (
          <div className="thinkflow-doc-traces">
            <div className="thinkflow-doc-traces-label">关联对话</div>
            {section.traces.map(renderTraceSummary)}
          </div>
        ) : null}
      </section>
    );
  };

  const createWorkspaceItem = async (itemType: WorkspaceItemType, title?: string) => {
    try {
      const nextTitle = (title || '').trim() || `${workspaceItemLabel(itemType)} ${workspaceItems.filter((item) => item.type === itemType).length + 1}`;
      const response = await apiFetch('/api/v1/kb/workspace-items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          item_type: itemType,
          title: nextTitle,
          content: '',
        }),
      });
      const data = await parseJson<{ item: ThinkFlowWorkspaceItem }>(response);
      await refreshWorkspaceItems(data.item.id);
      return data.item.id;
    } catch (error: any) {
      setGlobalError(error?.message || `创建${workspaceItemLabel(itemType)}失败`);
      return '';
    }
  };

  const saveWorkspaceItem = async (itemType: WorkspaceItemType) => {
    const activeId = itemType === 'summary' ? activeSummaryId : activeGuidanceId;
    const title = itemType === 'summary' ? summaryTitle : guidanceTitle;
    const content = itemType === 'summary' ? summaryContent : guidanceContent;
    if (!activeId) return;
    setWorkspaceSaving(itemType);
    try {
      const response = await apiFetch(`/api/v1/kb/workspace-items/${activeId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          title,
          content,
        }),
      });
      const data = await parseJson<{ item: ThinkFlowWorkspaceItem }>(response);
      setWorkspaceItems((previous) => previous.map((item) => (item.id === data.item.id ? data.item : item)));
      await refreshWorkspaceItems(activeId);
    } catch (error: any) {
      setGlobalError(error?.message || `保存${workspaceItemLabel(itemType)}失败`);
    } finally {
      setWorkspaceSaving(null);
    }
  };

  const rebuildAllSummary = async () => {
    if (itemSummaryItems.length === 0) {
      setGlobalError('请先从对话中生成 item summary。');
      return;
    }
    setRebuildingAllSummary(true);
    try {
      const response = await apiFetch('/api/v1/kb/workspace-items/summary/all/rebuild', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          title: 'All Summary',
        }),
      });
      const data = await parseJson<{ item: ThinkFlowWorkspaceItem }>(response);
      await refreshWorkspaceItems(data.item.id);
      setRightMode('summary');
      setCaptureFeedback('已根据所有 item summary 重新生成总 Summary');
    } catch (error: any) {
      setGlobalError(error?.message || '重算总 Summary 失败');
    } finally {
      setRebuildingAllSummary(false);
    }
  };

  const deleteWorkspaceItem = async (itemType: WorkspaceItemType, itemId: string) => {
    const label = workspaceItemLabel(itemType);
    if (!itemId) return;
    if (!window.confirm(`确认删除这个${label}吗？删除后无法恢复。`)) return;
    try {
      const response = await apiFetch(`/api/v1/kb/workspace-items/${itemId}?${notebookQuery}`, {
        method: 'DELETE',
      });
      await parseJson(response);
      await refreshWorkspaceItems();
      setCaptureFeedback(`已删除${label}`);
    } catch (error: any) {
      setGlobalError(error?.message || `删除${label}失败`);
    }
  };

  const toggleGuidanceSelection = (itemId: string) => {
    setSelectedGuidanceIds((previous) => {
      if (previous.includes(itemId)) return previous.filter((id) => id !== itemId);
      return [...previous, itemId];
    });
  };

  const toggleMessageSelection = (messageId: string) => {
    setSelectedMessageIds((previous) => {
      if (previous.includes(messageId)) return previous.filter((id) => id !== messageId);
      return [...previous, messageId];
    });
  };

  const clearSelectedMessages = () => {
    setSelectedMessageIds([]);
    setMultiSelectPrompt('');
  };

  const createDocument = async (
    title?: string,
    options?: { documentType?: 'summary_doc' | 'output_doc'; metadata?: Record<string, any>; content?: string },
  ) => {
    try {
      const isOutputDoc = options?.documentType === 'output_doc';
      const nextTitle = (title || '').trim() || (isOutputDoc ? `PPT 产出文档 ${documents.length + 1}` : `梳理摘要 ${documents.length + 1}`);
      const response = await apiFetch('/api/v1/kb/documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          title: nextTitle,
          content: options?.content ?? '',
          document_type: options?.documentType || 'summary_doc',
          metadata: options?.metadata || {},
        }),
      });
      const data = await parseJson<{ document: ThinkFlowDocument }>(response);
      setEditMode(false);
      setShowVersionPanel(false);
      await refreshDocuments(data.document.id);
      return data.document.id;
    } catch (error: any) {
      setGlobalError(error?.message || '创建文档失败');
      return '';
    }
  };

  const createOutputDocument = async (params?: {
    title?: string;
    sourceRefs?: Array<{ id: string; type: 'document' | 'output_document'; title: string; metadata?: Record<string, any> }>;
  }) => {
    const sourceRefs = [
      ...(params?.sourceRefs || conversationSourceRefs),
      ...(activeDocumentId
      && !(params?.sourceRefs || []).some((ref) => ref.id === activeDocumentId)
        ? [{
            id: activeDocumentId,
            type: activeDocument?.document_type === 'output_doc' ? 'output_document' : 'document',
            title: activeDocument?.title || documentTitle || '当前文档',
            metadata: { range: 'body' },
          } as ConversationSourceRef]
        : []),
    ];
    const id = await createDocument(params?.title || 'PPT 产出文档', {
      documentType: 'output_doc',
      metadata: {
        output_type: 'ppt',
        source_refs: sourceRefs,
        audience: '',
        style: '',
        goal: '',
      },
      content: '# PPT 产出文档\n\n## 产出目标\n\n[待补充]\n\n## 大纲方向\n\n[待补充]',
    });
    if (id) {
      await setConversationActiveDocument(id);
      setRightMode('doc');
      setCaptureFeedback('已创建 PPT 产出文档，可继续编辑后进入 PPT 工作台。');
    }
  };

  const updateDocumentContent = async ({
    documentId,
    title,
    content,
  }: {
    documentId: string;
    title: string;
    content: string;
  }) => {
    const response = await apiFetch(`/api/v1/kb/documents/${documentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notebook_id: notebook.id,
        notebook_title: notebookTitle,
        user_id: effectiveUser?.id || 'local',
        email: effectiveUser?.email || '',
        title,
        content,
      }),
    });
    return parseJson<{ document: ThinkFlowDocument }>(response);
  };

  const saveDocument = async () => {
    if (!activeDocumentId) return;
    setDocumentSaving(true);
    try {
      const data = await updateDocumentContent({
        documentId: activeDocumentId,
        title: documentTitle,
        content: documentContent,
      });
      setDocuments((previous) =>
        previous.map((item) => (item.id === data.document.id ? { ...item, ...data.document, content: documentContent } : item)),
      );
      await refreshDocuments(activeDocumentId);
    } catch (error: any) {
      setGlobalError(error?.message || '保存文档失败');
    } finally {
      setDocumentSaving(false);
    }
  };

  const deleteDocument = async (documentId: string) => {
    if (!documentId) return;
    if (!window.confirm('确认删除这份梳理文档吗？删除后无法恢复。')) return;
    try {
      const response = await apiFetch(`/api/v1/kb/documents/${documentId}?${notebookQuery}`, {
        method: 'DELETE',
      });
      await parseJson(response);
      await refreshDocuments();
      setCaptureFeedback('已删除梳理文档');
    } catch (error: any) {
      setGlobalError(error?.message || '删除文档失败');
    }
  };

  const ensurePushTargetDocument = async (documentId: string): Promise<ThinkFlowDocument | null> => {
    if (!documentId || documentId === '__new__') return null;
    const localDocument = documents.find((doc) => doc.id === documentId);
    if (localDocument) return localDocument;
    try {
      const document = await loadDocumentDetail(documentId);
      setDocuments((previous) => {
        if (previous.some((item) => item.id === document.id)) return previous;
        return [document, ...previous];
      });
      return document;
    } catch (error: any) {
      await refreshDocuments();
      throw new Error(
        `当前对话的活跃文档不在此笔记本中。当前笔记本：${notebookTitle} (${notebook.id})。请在右侧切换活跃文档后再推送。`,
      );
    }
  };

  const executePush = async () => {
    if (pushSubmitting) return;
    const {
      preset,
      destinationType,
      targetType,
      targetSectionId,
      newSectionTitle,
      transform,
      targetDocId,
      targetItemId,
      newTitle,
      mode,
      prompt,
      sourceContent,
      sourceEntries,
    } = pushPopover;
    if (!sourceContent.trim()) {
      setPushError('没有可沉淀的内容。');
      return;
    }
    setPushError('');
    setPushSubmitting(true);
    setPushStatusText(destinationType === 'document' ? '整理推送内容中...' : describePushAction(destinationType, mode));
    try {
      const requiresGeneratedTitle = destinationType !== 'document';
      const resolvedTitle = requiresGeneratedTitle
        ? await resolvePushTitle({
          destinationType,
          sourceContent,
          prompt,
          manualTitle: newTitle,
        })
        : (String(newTitle || '').trim() || inferDocumentTitle(sourceContent, prompt) || '对话沉淀');
      setPushStatusText(destinationType === 'document' ? '写入文档中...' : describePushAction(destinationType, mode));
      const selectedFiles = conversationSourceRefs
        .filter((ref) => ref.type === 'material')
        .map((ref) => files.find((file) => file.id === ref.id) || null)
        .filter(Boolean)
        .slice(0, 3) as KnowledgeFile[];
      const sourceRefs = [
        ...sourceEntries.map((entry) => ({
          source_type: entry.kind,
          message_id: entry.messageId,
          message_role: entry.role,
          message_time: entry.time,
          selection_text: entry.selectionText,
          source_file_names: selectedFiles.map((file) => file.name),
        })),
        ...selectedFiles.map((file) => ({ name: file.name, source: 'file' })),
      ];

      if (destinationType === 'document') {
        let docId = targetDocId;
        let docTitle = documents.find((doc) => doc.id === targetDocId)?.title || resolvedTitle;
        if (!docId) {
          throw new Error('请先在右侧选择或创建一份活跃文档，再推送到文档。');
        }
        const verifiedDocument = await ensurePushTargetDocument(docId);
        docTitle = verifiedDocument?.title || docTitle;
        const normalizedTransform = coercePushTransform(targetType, transform);
        const structuredTarget =
          targetType === 'focus'
            ? { type: 'focus' }
            : targetType === 'section'
              ? { type: 'section', section_id: targetSectionId }
              : targetType === 'new_section'
                ? { type: 'new_section', heading: newSectionTitle || resolvedTitle || '新增章节' }
                : targetType === 'stash'
                  ? { type: 'stash' }
                  : { type: 'document_end' };
        const response = await apiFetch(`/api/v1/kb/documents/${docId}/push`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebookTitle,
            user_id: effectiveUser?.id || 'local',
            email: effectiveUser?.email || '',
            mode: normalizedTransform === 'raw_append' ? 'append' : normalizedTransform === 'ai_merge' ? 'merge' : 'organize',
            title: resolvedTitle || '对话沉淀',
            prompt,
            text_items: [sourceContent],
            source_refs: sourceRefs,
            target: structuredTarget,
            transform: normalizedTransform,
            related_conv: conversationId || undefined,
          }),
        });
        const data = await parseJson<{ document: ThinkFlowDocument; trace?: DocumentPushTrace; stash_item?: DocumentStashItem }>(response);
        setActiveDocumentId(docId);
        setConversationActiveDocumentId(docId);
        setRightPanelOpen(true);
        setRightMode('doc');
        if (data.trace?.id) setHighlightedTraceId(data.trace.id);
        if (data.trace?.target?.section_id) {
          setDocumentFocusState(
            normalizeFocusState({
              type: 'sections',
              section_ids: [String(data.trace.target.section_id)],
              stash_item_ids: [],
              description: `焦点：${data.trace.target.heading || '推送目标章节'}`,
            }),
          );
        } else if (data.trace?.target?.type === 'stash' && data.stash_item?.id) {
          setDocumentFocusState(
            normalizeFocusState({
              type: 'stash_item',
              section_ids: [],
              stash_item_ids: [data.stash_item.id],
              description: '焦点：暂存区第 1 条',
            }),
          );
        }
        await refreshDocuments(docId);
        void persistConversationWorkspaceState({ activeDocId: docId }).catch(() => {});
        setPushPopover((previous) => ({ ...previous, show: false }));
        setCaptureFeedback(`已整理进文档《${docTitle}》`);
      } else {
        let itemId = targetItemId;
        if (itemId === '__new__' || !itemId) {
          itemId = undefined;
        }
        const generatedDraft = await generateWorkspaceDraft({
          itemType: destinationType,
          sourceContent,
          prompt:
            preset === 'qa' && destinationType === 'summary'
              ? prompt || '提炼这一轮问答的核心结论、关键依据与待确认点。'
              : prompt,
        });
        const response = await apiFetch('/api/v1/kb/workspace-items/capture', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebookTitle,
            user_id: effectiveUser?.id || 'local',
            email: effectiveUser?.email || '',
            item_type: destinationType,
            item_id: itemId,
            title: resolvedTitle,
            prompt: '',
            text_items: [generatedDraft],
            source_refs: sourceRefs,
          }),
        });
        const data = await parseJson<{ item: ThinkFlowWorkspaceItem }>(response);
        setRightPanelOpen(true);
        setRightMode(destinationType);
        await refreshWorkspaceItems(data.item.id);
        setPushPopover((previous) => ({ ...previous, show: false }));
        setCaptureFeedback(`已沉淀到${destinationType === 'summary' ? '摘要' : '产出指导'}《${data.item.title}》`);
      }

      setSelectionToolbar((previous) => ({ ...previous, show: false }));
      window.getSelection()?.removeAllRanges();
      setChatMessages((previous) =>
        previous.map((item) =>
          sourceEntries.some((entry) => entry.messageId === item.id)
            ? {
                ...item,
                pushed: true,
                capturedTargets: Array.from(new Set([...(item.capturedTargets || []), destinationType])),
              }
            : item,
        ),
      );
      clearSelectedMessages();
    } catch (error: any) {
      const message = error?.message || '沉淀到工作区失败';
      setPushError(message);
      setGlobalError(message);
    } finally {
      setPushSubmitting(false);
      setPushStatusText('');
    }
  };

  const restoreVersion = async (versionId: string) => {
    if (!activeDocumentId) return;
    try {
      const response = await apiFetch(`/api/v1/kb/documents/${activeDocumentId}/restore/${versionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      await parseJson(response);
      await refreshDocuments(activeDocumentId);
    } catch (error: any) {
      setGlobalError(error?.message || '恢复版本失败');
    }
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const inputFiles = event.target.files;
    if (!inputFiles || inputFiles.length === 0) return;
    setUploading(true);
    try {
      for (const file of Array.from(inputFiles)) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('email', effectiveUser?.email || 'local');
        formData.append('user_id', effectiveUser?.id || 'local');
        formData.append('notebook_id', notebook.id);
        formData.append('notebook_title', notebookTitle);
        const response = await apiFetch('/api/v1/kb/upload', {
          method: 'POST',
          body: formData,
        });
        await parseJson(response);
      }
      await refreshFiles();
    } catch (error: any) {
      setGlobalError(error?.message || '上传素材失败');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  const handleNotebookChatMessage = async (query: string) => {
    setChatLoading(true);
    setGlobalError('');

    const userMessage: ThinkFlowMessage = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: query,
      time: formatThinkFlowTime(new Date()),
    };
    const assistantMessage: ThinkFlowMessage = {
      id: `assistant_${Date.now()}`,
      role: 'assistant',
      content: '',
      time: formatThinkFlowTime(new Date()),
    };

    setChatMessages((previous) => [...previous, userMessage, assistantMessage]);
    setChatInput('');

    try {
      const targetConversationId = await ensureConversationId();
      const contextResponse = targetConversationId
        ? await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/chat-context`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              notebook_id: notebook.id,
              notebook_title: notebookTitle,
              user_id: effectiveUser?.id || 'local',
              email: effectiveUser?.email || '',
              user_message: query,
              history: buildConversationHistoryPayload(chatMessages),
            }),
          })
        : null;
      const contextData = contextResponse
        ? await parseJson<{ context?: { context_text?: string } }>(contextResponse)
        : null;
      const finalQuery = contextData?.context?.context_text || query;

      const response = await apiFetch('/api/v1/kb/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: selectedFilePaths,
          query: finalQuery,
          history: chatMessages
            .filter((item) => item.id !== 'welcome')
            .filter((item) => item.role === 'user' || item.role === 'assistant')
            .map((item) => ({ role: item.role, content: item.content })),
          email: effectiveUser?.email || '',
          user_id: effectiveUser?.id || 'local',
          notebook_id: notebook.id,
        }),
      });

      if (!response.body) throw new Error('流式响应为空');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullAnswer = '';
      let fileAnalyses: ThinkFlowMessage['fileAnalyses'];
      let sourceMapping: ThinkFlowMessage['sourceMapping'];
      let sourcePreviewMapping: ThinkFlowMessage['sourcePreviewMapping'];
      let sourceReferenceMapping: ThinkFlowMessage['sourceReferenceMapping'];

      const syncAssistantMessage = (nextContent = fullAnswer) => {
        setChatMessages((previous) =>
          previous.map((item) =>
            item.id === assistantMessage.id
              ? {
                  ...item,
                  content: nextContent,
                  fileAnalyses,
                  sourceMapping,
                  sourcePreviewMapping,
                  sourceReferenceMapping,
                }
              : item,
          ),
        );
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          const payload = JSON.parse(trimmed);
          if (payload.type === 'meta') {
            fileAnalyses = payload.file_analyses || undefined;
            sourceMapping = payload.source_mapping || undefined;
            sourcePreviewMapping = payload.source_preview_mapping || undefined;
            sourceReferenceMapping = payload.source_reference_mapping || undefined;
            syncAssistantMessage();
          } else if (payload.type === 'delta') {
            fullAnswer += payload.delta || '';
            syncAssistantMessage();
          } else if (payload.type === 'done') {
            fullAnswer = payload.answer || fullAnswer;
            syncAssistantMessage();
          } else if (payload.type === 'error') {
            throw new Error(payload.message || '对话失败');
          }
        }
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        const payload = JSON.parse(buffer.trim());
        if (payload.type === 'meta') {
          fileAnalyses = payload.file_analyses || undefined;
          sourceMapping = payload.source_mapping || undefined;
          sourcePreviewMapping = payload.source_preview_mapping || undefined;
          sourceReferenceMapping = payload.source_reference_mapping || undefined;
          syncAssistantMessage();
        } else if (payload.type === 'delta') {
          fullAnswer += payload.delta || '';
          syncAssistantMessage();
        } else if (payload.type === 'done') {
          fullAnswer = payload.answer || fullAnswer;
          syncAssistantMessage();
        } else if (payload.type === 'error') {
          throw new Error(payload.message || '对话失败');
        }
      }
      await appendConversationMessages([
        { role: 'user', content: query },
        { role: 'assistant', content: fullAnswer },
      ]);
      if (targetConversationId) {
        await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/mark-sent`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebookTitle,
            user_id: effectiveUser?.id || 'local',
            email: effectiveUser?.email || '',
          }),
        });
        void loadConversationWorkspaceState(targetConversationId);
      }
    } catch (error: any) {
      setGlobalError(error?.message || '发送消息失败');
      setChatMessages((previous) =>
        previous.map((item) =>
          item.id === assistantMessage.id ? { ...item, content: `请求失败：${error?.message || '未知错误'}` } : item,
        ),
      );
    } finally {
      setChatLoading(false);
    }
  };

  const handleSendMessage = async () => {
    const query = chatInput.trim();
    if (!query || chatLoading) return;
    if (isPptOutlineChatStage) {
      await handlePptOutlineChatMessage(query);
      return;
    }
    await handleNotebookChatMessage(query);
  };

  const updateOutlineSection = (index: number, patch: Partial<OutlineSection>) => {
    setOutputs((previous) =>
      previous.map((item) => {
        if (item.id !== activeOutputId) return item;
        const nextOutline = [...(item.outline || [])];
        nextOutline[index] = { ...nextOutline[index], ...patch };
        return { ...item, outline: nextOutline };
      }),
    );
  };

  const addPptOutlineSection = () => {
    if (!activeOutputId) return;
    const nextIndex = (activeOutput?.outline || []).length;
    setOutputs((previous) =>
      previous.map((item) => {
        if (item.id !== activeOutputId) return item;
        return {
          ...item,
          outline: [
            ...(item.outline || []),
            {
              id: `slide_${Date.now()}`,
              title: '新页面',
              layout_description: '',
              key_points: [],
              asset_ref: null,
              summary: '',
              bullets: [],
            },
          ],
        };
      }),
    );
    setActivePptSlideIndex(nextIndex);
  };

  const generateWorkspaceDraft = async ({
    itemType,
    sourceContent,
    prompt,
  }: {
    itemType: WorkspaceItemType;
    sourceContent: string;
    prompt: string;
  }) => {
    const sourceText = String(sourceContent || '').trim();
    if (!sourceText) return '';

    const instruction =
      itemType === 'summary'
        ? [
            '你是 ThinkFlow 的 AI 笔记整理器。',
            '请根据给定来源与对话片段，输出一份简洁、可继续编辑的 markdown 摘要。',
            '不要直接复制原始问答，要先归纳。',
            'Markdown 层级规则：最大标题只能使用二级标题 ##；不要输出一级标题 #；主要模块必须用 ##，不要把主要模块写成 ###。',
            '必须包含这些二级标题：',
            '## 这段在说什么',
            '## 当前结论',
            '## 关键依据',
            '## 待确认 / 可追问',
            '每一节尽量简洁，优先 bullet。不要输出额外解释。',
          ].join('\n')
        : [
            '你是 ThinkFlow 的产出指导生成器。',
            '请根据给定来源与对话片段，输出一份高权重、只读的 markdown 产出指导。',
            '这份内容将直接进入后续 PPT / 报告 / 其他产出的核心上下文。',
            '不要复述原始问答，要输出明确要求。',
            'Markdown 层级规则：最大标题只能使用二级标题 ##；不要输出一级标题 #；主要模块必须用 ##，不要把主要模块写成 ###。',
            '必须包含这些二级标题：',
            '## 产出目标',
            '## 必须覆盖',
            '## 重点强调',
            '## 需要避免',
            '## 表达风格',
            '## 关键依据',
            '每一节尽量简洁、明确、可执行。不要输出额外解释。',
          ].join('\n');

    const query = [
      instruction,
      prompt ? `\n补充要求：\n${prompt}` : '',
      '\n待整理内容：',
      sourceText,
    ]
      .filter(Boolean)
      .join('\n\n');

    try {
      const response = await apiFetch('/api/v1/kb/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: selectedFilePaths,
          query,
          history: [],
          email: effectiveUser?.email || '',
          notebook_id: notebook.id,
        }),
      });
      const data = await parseJson<{ answer?: string }>(response);
      return String(data.answer || '').trim() || sourceText;
    } catch {
      return sourceText;
    }
  };

  const generateCaptureTitle = async ({
    destinationType,
    sourceContent,
    prompt,
  }: {
    destinationType: PushDestinationType;
    sourceContent: string;
    prompt: string;
  }) => {
    const sourceText = String(sourceContent || '').trim();
    if (!sourceText) return inferDocumentTitle(sourceContent, prompt);

    const targetLabel =
      destinationType === 'document' ? '梳理文档片段' : destinationType === 'guidance' ? '产出指导' : '摘要';

    const query = [
      '你是 ThinkFlow 的命名助手。',
      `请为这次${targetLabel}生成一个简洁自然的中文标题。`,
      '要求：',
      '1. 只输出标题本身，不要引号，不要解释。',
      '2. 不超过 12 个汉字或 24 个字符。',
      '3. 语义明确，适合展示在工作区卡片或文档片段标题里。',
      prompt ? `补充要求：${prompt}` : '',
      '待命名内容：',
      sourceText,
    ]
      .filter(Boolean)
      .join('\n\n');

    try {
      const response = await apiFetch('/api/v1/kb/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: selectedFilePaths,
          query,
          history: [],
          email: effectiveUser?.email || '',
          notebook_id: notebook.id,
        }),
      });
      const data = await parseJson<{ answer?: string }>(response);
      const rawTitle =
        String(data.answer || '')
          .trim()
          .split('\n')
          .find((line) => line.trim()) || '';
      const normalized = rawTitle.replace(/^["'“”‘’#\-\s]+|["'“”‘’\s]+$/g, '').trim();
      return normalized.slice(0, 24) || inferDocumentTitle(sourceContent, prompt);
    } catch {
      return inferDocumentTitle(sourceContent, prompt);
    }
  };

  const resolvePushTitle = async ({
    destinationType,
    sourceContent,
    prompt,
    manualTitle,
  }: {
    destinationType: PushDestinationType;
    sourceContent: string;
    prompt: string;
    manualTitle: string;
  }) => {
    const cleanedManualTitle = String(manualTitle || '').trim();
    if (cleanedManualTitle) return cleanedManualTitle;
    setPushStatusText('正在为这次沉淀生成标题...');
    return generateCaptureTitle({ destinationType, sourceContent, prompt });
  };

  const generateOutput = async () => {
    if (!activeOutputId) return;
    if (activeOutput?.target_type === 'ppt' && activePptStage === 'outline_ready') {
      await confirmPptOutline();
      return;
    }
    await generateOutputById(activeOutputId);
  };

  const rebuildActiveOutput = async (autoGenerate = false) => {
    if (!activeOutput) return;
    const snapshot = activeOutputContext?.snapshot;
    const snapshotSourceEntries =
      snapshot?.selectedSourceIds?.length
        ? files.filter((file) => snapshot.selectedSourceIds.includes(file.id))
        : [];
    const fallbackSourceEntries =
      (activeOutput.source_paths || []).map((path, index) => ({
        url: path,
        name: activeOutput.source_names?.[index] || `来源 ${index + 1}`,
      }));
    await createOutline(activeOutput.target_type, {
      autoGenerate,
      titleOverride: activeOutput.title,
      documentIdOverride: snapshot?.documentId || activeOutput.document_id,
      guidanceItemIdsOverride:
        snapshot?.guidanceItemIds?.length
          ? snapshot.guidanceItemIds
          : activeOutput.guidance_item_ids || [],
      sourceIdsOverride:
        snapshot?.selectedSourceIds?.length
          ? snapshot.selectedSourceIds
          : files
              .filter((file) => (activeOutput.source_names || []).includes(file.name || ''))
              .map((file) => file.id),
      boundDocumentIdsOverride:
        snapshot?.boundDocumentIds?.length
          ? snapshot.boundDocumentIds
          : activeOutput.bound_document_ids || [],
      sourcePathsOverride:
        snapshotSourceEntries.length > 0
          ? snapshotSourceEntries.map((file) => resolveFileUrl(file))
          : fallbackSourceEntries.map((item) => item.url),
      sourceNamesOverride:
        snapshotSourceEntries.length > 0
          ? snapshotSourceEntries.map((file) => file.name || '未命名来源')
          : fallbackSourceEntries.map((item) => item.name),
    });
  };

  const importOutputToSource = async () => {
    if (!activeOutputId) return;
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/import-source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      const result = await parseJson(response);
      await refreshFiles();
      const sourceName = result?.source_path ? String(result.source_path).split('/').pop() : '';
      pushToast(sourceName ? `已导入为来源素材：${sourceName}` : '已导入为来源素材', 'success');
    } catch (error: any) {
      setGlobalError(error?.message || '回流来源失败');
    }
  };

  const renderOutputPreview = () => {
    if (!activeOutput) {
      return <div className="thinkflow-empty">点击右侧产出按钮后，这里会显示当前生成结果。</div>;
    }
    const result = activeOutput.result || {};
    const flashcards = getFlashcardsFromResult(result);
    const quizQuestions = getQuizQuestionsFromResult(result);
    if (activeOutput.target_type === 'ppt') {
      const previewImages = activePptPreviewImages;
      const selectedSlide = activePptSlide?.slide;
      const selectedIndex = activePptSlide?.index ?? 0;
      const selectedImage = activePptCurrentPreview;
      const canDownloadPpt = activePptStage === 'generated';
      return (
        <div className="thinkflow-output-preview thinkflow-ppt-viewer">
          {previewImages.length > 0 && selectedSlide ? (
            <>
              <div className="thinkflow-ppt-viewer-stage">
                <div className="thinkflow-ppt-viewer-toolbar">
                  <div className="thinkflow-ppt-viewer-toolbar-copy">
                    <span className="thinkflow-ppt-outline-summary-index">第 {selectedSlide.pageNum || selectedIndex + 1} 页</span>
                    <strong>{selectedSlide.title || `页面 ${selectedIndex + 1}`}</strong>
                  </div>
                  <div className="thinkflow-ppt-viewer-links">
                    {canDownloadPpt && result.ppt_pdf_path ? (
                      <a href={result.ppt_pdf_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                        <ExternalLink size={14} />
                        打开 PDF
                      </a>
                    ) : null}
                    {canDownloadPpt && result.ppt_pptx_path ? (
                      <a href={result.ppt_pptx_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                        <Download size={14} />
                        下载 PPTX
                      </a>
                    ) : null}
                  </div>
                </div>
                <div className="thinkflow-ppt-viewer-frame">
                  {selectedImage ? (
                    <img src={withAssetVersion(selectedImage, `${activeOutput.updated_at}_${selectedIndex}`)} alt={`PPT 第 ${selectedIndex + 1} 页`} />
                  ) : (
                    <div className="thinkflow-empty">这一页还没有图像预览。</div>
                  )}
                </div>
                {activePptPageVersions.length > 0 ? (
                  <div className="thinkflow-ppt-history-strip">
                    {activePptPageVersions.map((version, index) => (
                      <button
                        key={version.id}
                        type="button"
                        className={`thinkflow-ppt-history-card ${version.selected ? 'is-selected' : ''}`}
                        onClick={() => {
                          if (version.selected) return;
                          void selectActivePptPageVersion(version.id);
                        }}
                        disabled={pptPageBusyAction !== '' || generatingOutput}
                        title={version.prompt || (version.source === 'initial' ? '初始草稿' : '历史版本')}
                      >
                        <div className="thinkflow-ppt-history-thumb">
                          {version.preview_path ? (
                            <img
                              src={withAssetVersion(version.preview_path, `${version.created_at}_${version.id}`)}
                              alt={`第 ${selectedIndex + 1} 页历史版本 ${index + 1}`}
                            />
                          ) : (
                            <div className="thinkflow-empty">暂无缩略图</div>
                          )}
                        </div>
                        <div className="thinkflow-ppt-history-meta">
                          <strong>{version.source === 'initial' ? '初始稿' : `版本 ${activePptPageVersions.length - index}`}</strong>
                          <span>{version.selected ? '当前' : '点击切换'}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : null}
                <div className="thinkflow-ppt-viewer-caption">
                  <p>{selectedSlide.layout_description || '当前页暂时没有布局描述。'}</p>
                </div>
              </div>
              <div className="thinkflow-ppt-filmstrip">
                {previewImages.map((image, index) => {
                  const review = activePptPageReviews.find((item) => item.page_index === index);
                  return (
                    <button
                      key={`${image}_${index}`}
                      type="button"
                      className={`thinkflow-ppt-filmstrip-card ${selectedIndex === index ? 'is-active' : ''}`}
                      onClick={() => setActivePptSlideIndex(index)}
                    >
                      <div className="thinkflow-ppt-filmstrip-thumb">
                        <img src={withAssetVersion(image, `${activeOutput.updated_at}_${index}`)} alt={`PPT 第 ${index + 1} 页`} />
                      </div>
                      <div className="thinkflow-ppt-filmstrip-meta">
                        <span>第 {index + 1} 页</span>
                        {review?.confirmed ? <strong>已确认</strong> : <em>待核对</em>}
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          ) : canDownloadPpt && result.ppt_pdf_path ? (
            <div className="thinkflow-pdf-embed-shell">
              <div className="thinkflow-pdf-embed-toolbar">
                <strong>{activeOutput.title}</strong>
                <a href={result.ppt_pdf_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                  <ExternalLink size={14} />
                  新开查看 PDF
                </a>
              </div>
              <iframe src={result.ppt_pdf_path} title={activeOutput.title} />
            </div>
          ) : (
            <div className="thinkflow-empty">确认逐页生成后，这里会显示页面预览与下载入口。</div>
          )}
        </div>
      );
    }
    if (activeOutput.target_type === 'report' && result.preview_markdown) {
      return (
        <div className="thinkflow-output-preview">
          <div className="thinkflow-markdown">
            <ReactMarkdown>{String(result.preview_markdown)}</ReactMarkdown>
          </div>
        </div>
      );
    }
    if (result.pdf_path || result.previewUrl || result.preview_url) {
      return (
        <div className="thinkflow-output-preview">
          <iframe src={result.pdf_path || result.previewUrl || result.preview_url} title={activeOutput.title} />
        </div>
      );
    }
    if (result.audio_path) {
      return (
        <div className="thinkflow-output-preview">
          <audio controls src={result.audio_path} />
        </div>
      );
    }
    if (result.mermaid_code) {
      return (
        <ThinkFlowMindmapPreview
          activeOutput={activeOutput}
          files={files}
          conversationSourceRefs={conversationSourceRefs}
          resolveFileUrl={resolveFileUrl}
          setConversationSourceRefs={setConversationSourceRefs}
          setSelectedIds={setSelectedIds}
          persistConversationWorkspaceState={({ sourceRefs }) => persistConversationWorkspaceState({ sourceRefs })}
          setCaptureFeedback={setCaptureFeedback}
          setGlobalError={setGlobalError}
          setChatInput={setChatInput}
        />
      );
    }
    if (activeOutput.target_type === 'flashcard' && flashcards.length > 0) return renderFlashcardPreview(flashcards);
    if (activeOutput.target_type === 'quiz' && quizQuestions.length > 0) return renderQuizPreview(quizQuestions);
    if (flashcards.length > 0) return renderFlashcardPreview(flashcards);
    if (quizQuestions.length > 0) return renderQuizPreview(quizQuestions);
    if (generatingOutput || generatingOutline === activeOutput.target_type) {
      return <div className="thinkflow-empty">正在生成 {outputLabel(activeOutput.target_type)}，结果出来后会直接显示在这里。</div>;
    }
    return <div className="thinkflow-empty">当前结果还未生成，请重新生成一版。</div>;
  };

  const renderDirectOutputWorkspace = () => {
    if (!activeOutput || activeOutput.target_type === 'ppt') return null;
    const result = activeOutput.result || {};
    const downloadUrl = result.download_url || result.pdf_path || result.previewUrl || result.preview_url || result.audio_path || '';
    return (
      <div className="thinkflow-output-workspace-body thinkflow-direct-output-workspace">
        <div className="thinkflow-direct-output-actions">
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => setRightMode('doc')}>
            返回文档
          </button>
          <button
            type="button"
            className="thinkflow-generate-btn"
            onClick={() => void rebuildActiveOutput(true)}
            disabled={generatingOutline !== null || generatingOutput}
          >
            <RefreshCw size={14} />
            {generatingOutput ? '生成中...' : '重新生成一版'}
          </button>
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => void importOutputToSource()}>
            回流来源
          </button>
          {downloadUrl ? (
            <a href={downloadUrl} target="_blank" rel="noreferrer" className="thinkflow-download-link">
              <ExternalLink size={14} />
              打开结果
            </a>
          ) : null}
        </div>
        <div className="thinkflow-direct-output-canvas">{renderOutputPreview()}</div>
      </div>
    );
  };

  const renderSummaryCards = (content: string) => {
    const sections = parseWorkspaceMarkdown(content);
    if (sections.length === 0) {
      return <div className="thinkflow-empty">摘要会根据来源和当前对话自动整理成 AI 笔记卡。</div>;
    }
    return (
      <div className="thinkflow-note-board">
        {sections.map((section) => (
          <article key={section.id} className="thinkflow-note-card">
            <div className="thinkflow-note-card-head">
              <span className="thinkflow-note-card-kicker">AI 笔记</span>
              <h4>{section.title}</h4>
            </div>
            {section.meta.length > 0 ? (
              <div className="thinkflow-note-meta">
                {section.meta.map((item, index) => (
                  <span key={`${section.id}_meta_${index}`} className="thinkflow-note-meta-chip">
                    {item}
                  </span>
                ))}
              </div>
            ) : null}
            {section.paragraphs.length > 0 ? (
              <div className="thinkflow-note-copy">
                {section.paragraphs.map((item, index) => (
                  <p key={`${section.id}_p_${index}`}>{item}</p>
                ))}
              </div>
            ) : null}
            {section.bullets.length > 0 ? (
              <ul className="thinkflow-note-list">
                {section.bullets.map((item, index) => (
                  <li key={`${section.id}_bullet_${index}`}>{item}</li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>
    );
  };

  const renderGuidanceBrief = (content: string) => {
    const sections = parseWorkspaceMarkdown(content);
    if (sections.length === 0) {
      return <div className="thinkflow-empty">产出指导会从你确认过的对话中提炼成只读 brief。</div>;
    }
    return (
      <div className="thinkflow-guidance-brief">
        <div className="thinkflow-guidance-hero">
          <span className="thinkflow-guidance-lock">只读高权重</span>
          <p>这份指导会作为后续大纲与正式生成的强约束上下文，不允许直接手改。</p>
        </div>
        <div className="thinkflow-guidance-grid">
          {sections.map((section) => (
            <section key={section.id} className="thinkflow-guidance-card">
              <h4>{section.title}</h4>
              {section.paragraphs.length > 0 ? (
                <div className="thinkflow-guidance-copy">
                  {section.paragraphs.map((item, index) => (
                    <p key={`${section.id}_p_${index}`}>{item}</p>
                  ))}
                </div>
              ) : null}
              {section.bullets.length > 0 ? (
                <ul className="thinkflow-guidance-list">
                  {section.bullets.map((item, index) => (
                    <li key={`${section.id}_bullet_${index}`}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          ))}
        </div>
      </div>
    );
  };

  const buildPptReferenceDocumentTitles = (primaryTitle: string, boundTitles: string[]) => {
    const titles = [primaryTitle, ...boundTitles].map((item) => String(item || '').trim()).filter(Boolean);
    return Array.from(new Set(titles));
  };

  const buildDirectOutputDocumentTitles = (documentId: string, primaryTitle: string, boundTitles: string[]) => {
    const titles = [
      documentId ? primaryTitle : '',
      ...boundTitles,
    ]
      .map((item) => String(item || '').trim())
      .filter(Boolean);
    return Array.from(new Set(titles));
  };

  const renderOutputWorkspaceHeader = () => {
    if (!activeOutput) return null;
    const snapshot = activeOutputContext?.snapshot;
    const isPptOutput = activeOutput.target_type === 'ppt';
    const nonPptDocumentTitle =
      snapshot?.documentTitle ||
      documents.find((item) => item.id === activeOutput.document_id)?.title ||
      activeOutput.title;
    const nonPptSourceNames =
      snapshot?.sourceNames?.length
        ? snapshot.sourceNames
        : activeOutput.source_names || [];
    const nonPptBoundDocTitles =
      snapshot?.boundDocumentTitles?.length
        ? snapshot.boundDocumentTitles
        : (activeOutput.bound_document_titles || []).length > 0
          ? activeOutput.bound_document_titles || []
          : documents
              .filter((item) => (activeOutput.bound_document_ids || []).includes(item.id))
              .map((item) => item.title || '未命名参考文档');
    const nonPptGuidanceTitles =
      snapshot?.guidanceTitles?.length
        ? snapshot.guidanceTitles
        : guidanceItems
            .filter((item) => (activeOutput.guidance_item_ids || []).includes(item.id))
            .map((item) => item.title || '未命名产出指导');
    const pptDocumentTitle =
      documents.find((item) => item.id === activeOutput.document_id)?.title ||
      activeOutput.title.replace(/\s*·\s*PPT$/u, '') ||
      '未设置';
    const pptSourceNames = activeOutput.source_names || [];
    const pptBoundDocTitles =
      (activeOutput.bound_document_titles || []).length > 0
        ? activeOutput.bound_document_titles || []
        : documents
            .filter((item) => (activeOutput.bound_document_ids || []).includes(item.id))
            .map((item) => item.title || '未命名参考文档');
    const pptGuidanceTitles = guidanceItems
      .filter((item) => (activeOutput.guidance_item_ids || []).includes(item.id))
      .map((item) => item.title || '未命名产出指导');
    const pptReferenceDocTitles = buildPptReferenceDocumentTitles(pptDocumentTitle, pptBoundDocTitles);
    const sourceCount = isPptOutput ? pptSourceNames.length : nonPptSourceNames.length;
    const boundDocCount = isPptOutput ? pptReferenceDocTitles.length : nonPptBoundDocTitles.length;
    const guidanceCount = isPptOutput ? pptGuidanceTitles.length : nonPptGuidanceTitles.length;
    const collapsedPills = isPptOutput
      ? [
          `来源 ${sourceCount}`,
          `梳理文档 / 参考文档 ${boundDocCount}`,
          `产出指导 ${guidanceCount}`,
        ]
      : [
          `来源 ${sourceCount}`,
          `参考文档 ${boundDocCount}`,
          `产出指导 ${guidanceCount}`,
        ];

    return (
      <div
        className={`thinkflow-output-workspace-header ${isOutputHeaderCollapsed ? 'is-collapsed' : 'is-expanded'}`}
        data-testid="output-workspace-header"
      >
        <div className="thinkflow-output-workspace-rail" data-testid="output-workspace-header-rail">
          <div className="thinkflow-output-workspace-top">
            <div className="thinkflow-output-workspace-copy">
              <span className="thinkflow-output-workspace-kicker">
                {workspaceMode === 'output_immersive' ? '沉浸编辑' : '产出工作台'}
              </span>
              <h3>
                {outputEmoji(activeOutput.target_type)} {activeOutput.title}
              </h3>
            </div>
            <div className="thinkflow-output-workspace-actions">
              <button
                type="button"
                className="thinkflow-doc-action-btn"
                onClick={() => setWorkspaceMode((previous) => (previous === 'output_immersive' ? 'output_focus' : 'output_immersive'))}
              >
                {workspaceMode === 'output_immersive' ? '退出沉浸' : '沉浸编辑'}
              </button>
              <button type="button" className="thinkflow-doc-action-btn" onClick={exitOutputWorkspace}>
                返回对话
              </button>
            </div>
          </div>
          <div className="thinkflow-output-context-strip is-rail">
            {collapsedPills.map((item) => (
              <span key={item} className="thinkflow-output-context-pill">
                {item}
              </span>
            ))}
          </div>
        </div>

        <div
          className="thinkflow-output-workspace-details"
          data-testid="output-workspace-header-details"
          aria-hidden={isOutputHeaderCollapsed}
        >
          <div className="thinkflow-output-workspace-description">
            <p>
              {activeOutput.target_type === 'ppt'
                ? 'PPT 会先基于来源生成大纲，确认后再进入逐页生成。来源仍是主输入，梳理文档和产出指导只作为增强上下文。'
                : '非 PPT 产出会直接基于确认时的来源快照生成结果。这个结果版本不会在当前会话里动态改来源；需要新范围时请重新生成一版。'}
            </p>
          </div>

          {isPptOutput ? (
            <>
              <div className="thinkflow-output-source-lock-card">
                <div className="thinkflow-output-source-lock-copy">
                  <strong>本次 PPT 来源已锁定</strong>
                  <p>当前会话只使用创建时确认的来源、梳理文档和产出指导。后续可重开新一轮 PPT，但不会在当前会话里动态改来源。</p>
                </div>
                <div className="thinkflow-output-source-lock-grid">
                  <div className="thinkflow-output-source-lock-section">
                    <span>来源文件</span>
                    <div className="thinkflow-output-source-lock-tags">
                      {pptSourceNames.length > 0 ? pptSourceNames.map((item) => <em key={item}>{item}</em>) : <em>未选择</em>}
                    </div>
                  </div>
                  <div className="thinkflow-output-source-lock-section">
                    <span>梳理文档 / 参考文档</span>
                    <div className="thinkflow-output-source-lock-tags">
                      {pptReferenceDocTitles.length > 0 ? pptReferenceDocTitles.map((item) => <em key={item}>{item}</em>) : <em>未选择</em>}
                    </div>
                  </div>
                  <div className="thinkflow-output-source-lock-section">
                    <span>产出指导</span>
                    <div className="thinkflow-output-source-lock-tags">
                      {pptGuidanceTitles.length > 0 ? pptGuidanceTitles.map((item) => <em key={item}>{item}</em>) : <em>未选择</em>}
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="thinkflow-output-source-lock-card">
                <div className="thinkflow-output-source-lock-copy">
                  <strong>本次产出来源已锁定</strong>
                  <p>当前结果版本只使用创建时确认的来源、梳理文档和产出指导。若你想换一套输入范围，请重新生成一版结果。</p>
                </div>
                <div className="thinkflow-output-source-lock-grid">
                  <div className="thinkflow-output-source-lock-section">
                    <span>来源文件</span>
                    <div className="thinkflow-output-source-lock-tags">
                      {nonPptSourceNames.length > 0 ? nonPptSourceNames.map((item) => <em key={item}>{item}</em>) : <em>未选择</em>}
                    </div>
                  </div>
                  <div className="thinkflow-output-source-lock-section">
                    <span>梳理文档 / 参考文档</span>
                    <div className="thinkflow-output-source-lock-tags">
                      {nonPptBoundDocTitles.length > 0 ? nonPptBoundDocTitles.map((item) => <em key={item}>{item}</em>) : <em>未选择</em>}
                    </div>
                  </div>
                  <div className="thinkflow-output-source-lock-section">
                    <span>产出指导</span>
                    <div className="thinkflow-output-source-lock-tags">
                      {nonPptGuidanceTitles.length > 0 ? nonPptGuidanceTitles.map((item) => <em key={item}>{item}</em>) : <em>未选择</em>}
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  };

  const renderPptOutlineWorkspace = () => {
    if (!activeOutput) return null;
    return (
      <PptOutlinePanel
        activeOutput={activeOutput}
        activePptOutline={activePptOutline}
        activePptSlide={activePptSlide}
        activePptStage={activePptStage}
        activePptDraftPending={activePptDraftPending}
        archivedOutlineChatSessions={archivedOutlineChatSessions}
        outlineSaving={outlineSaving}
        generatingOutput={generatingOutput}
        draftOutline={activeOutput.outline_chat_draft_outline}
        onSetRightMode={setRightMode}
        onSaveOutline={saveOutline}
        onConfirmPptOutline={confirmPptOutline}
        onUpdateOutlineSection={updateOutlineSection}
        onSetActivePptSlideIndex={setActivePptSlideIndex}
        onAddPptOutlineSection={addPptOutlineSection}
      />
    );
  };

  const renderPptGenerationReview = () => {
    if (!activeOutput) return null;
    return (
      <PptPageReviewPanel
        activeOutput={activeOutput}
        activePptStage={activePptStage}
        activePptPreviewImages={activePptPreviewImages}
        activePptSlide={activePptSlide}
        activePptConfirmedCount={activePptConfirmedCount}
        activePptPageVersions={activePptPageVersions}
        activePptCurrentPreview={activePptCurrentPreview}
        activePptCurrentReview={activePptCurrentReview}
        pptOutlineReadonlyOpen={pptOutlineReadonlyOpen}
        pptPagePrompt={pptPagePrompt}
        pptPageBusyAction={pptPageBusyAction}
        pptPageStatus={pptPageStatus}
        generatingOutput={generatingOutput}
        onSetPptOutlineReadonlyOpen={setPptOutlineReadonlyOpen}
        onSetPptPagePrompt={setPptPagePrompt}
        onSetActivePptSlideIndex={setActivePptSlideIndex}
        onGenerateOutputById={generateOutputById}
        onRegenerateActivePptPage={regenerateActivePptPage}
        onConfirmActivePptPage={confirmActivePptPage}
        renderOutputPreview={renderOutputPreview}
        onRevert={revertToOutlineStage}
        onGenerate={() => void generateOutputById(activeOutput.id)}
        allConfirmed={activePptConfirmedCount === (activeOutput.outline || []).length && (activeOutput.outline || []).length > 0}
      />
    );
  };

  const renderPptGeneratedResult = () => {
    if (!activeOutput) return null;
    return (
      <PptGeneratedResultPanel
        activeOutput={activeOutput}
        activePptStage={activePptStage}
        pptOutlineReadonlyOpen={pptOutlineReadonlyOpen}
        onSetPptOutlineReadonlyOpen={setPptOutlineReadonlyOpen}
        onImportOutputToSource={importOutputToSource}
        renderOutputPreview={renderOutputPreview}
      />
    );
  };

  const renderPptWorkspace = () => {
    if (!activeOutput) return null;
    if (activePptStage === 'generated') return renderPptGeneratedResult();
    if (activePptStage === 'pages_ready') return renderPptGenerationReview();
    return renderPptOutlineWorkspace();
  };

  const tryParseStructuredArray = (value: unknown): Record<string, any>[] | null => {
    if (Array.isArray(value)) {
      return value.filter((item) => item && typeof item === 'object') as Record<string, any>[];
    }
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    const candidates = [
      trimmed,
      trimmed.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/u, '').trim(),
    ];
    const arrayMatch = trimmed.match(/\[[\s\S]*\]/u);
    if (arrayMatch) candidates.push(arrayMatch[0]);
    for (const candidate of candidates) {
      if (!candidate) continue;
      try {
        const parsed = JSON.parse(candidate);
        if (Array.isArray(parsed)) {
          return parsed.filter((item) => item && typeof item === 'object') as Record<string, any>[];
        }
      } catch {
        continue;
      }
    }
    return null;
  };

  const getFlashcardsFromResult = (result: Record<string, any>): FlashcardItem[] => {
    const parsed =
      tryParseStructuredArray(result.flashcards) ||
      tryParseStructuredArray(result.cards) ||
      tryParseStructuredArray(result.content) ||
      tryParseStructuredArray(result.preview_markdown);
    if (!parsed) return [];
    return parsed.map((item, index) => ({
      id: String(item.id || `card_${index}`),
      question: String(item.question || item.front || '').trim(),
      answer: String(item.answer || item.back || '').trim(),
      type: String(item.type || 'qa').trim(),
      difficulty: item.difficulty ? String(item.difficulty) : null,
      source_file: item.source_file ? String(item.source_file) : null,
      source_excerpt: item.source_excerpt ? String(item.source_excerpt) : null,
      tags: Array.isArray(item.tags) ? item.tags.map((tag) => String(tag)) : [],
      created_at: item.created_at ? String(item.created_at) : null,
    }));
  };

  const getQuizQuestionsFromResult = (result: Record<string, any>): QuizQuestionItem[] => {
    const parsed =
      tryParseStructuredArray(result.questions) ||
      tryParseStructuredArray(result.quiz) ||
      tryParseStructuredArray(result.content) ||
      tryParseStructuredArray(result.preview_markdown);
    if (!parsed) return [];
    return parsed.map((item, index) => ({
      id: String(item.id || `question_${index}`),
      question: String(item.question || '').trim(),
      options: Array.isArray(item.options)
        ? item.options.map((option: any, optionIndex: number) => ({
            label: String(option?.label || String.fromCharCode(65 + optionIndex)),
            text: String(option?.text || ''),
          }))
        : [],
      correct_answer: item.correct_answer ? String(item.correct_answer) : '',
      explanation: item.explanation ? String(item.explanation) : '',
      source_excerpt: item.source_excerpt ? String(item.source_excerpt) : null,
      difficulty: item.difficulty ? String(item.difficulty) : null,
      category: item.category ? String(item.category) : null,
    }));
  };

  const renderFlashcardPreview = (cards: FlashcardItem[]) => {
    if (cards.length === 0) return null;
    return (
      <div className="thinkflow-output-preview thinkflow-flashcard-preview">
        <ThinkFlowFlashcardStudy cards={cards} />
      </div>
    );
  };

  const renderQuizPreview = (questions: QuizQuestionItem[]) => {
    if (questions.length === 0) return null;
    return (
      <div className="thinkflow-output-preview thinkflow-flashcard-preview">
        <ThinkFlowQuizStudy questions={questions} />
      </div>
    );
  };

  const renderPanelGuide = (panel: PanelGuideKey) => {
    if (!panelGuideVisibility[panel]) return null;
    const config: Record<PanelGuideKey, { title: string; description: string; capabilities: string }> = {
      summary: {
        title: 'Summary 卡片说明',
        description: '这里维护多张 item summary 卡片，以及一张由所有 item summary 重新总结出来的总 Summary。',
        capabilities: '第一版只从你主动选择的对话内容生成 item summary；总 Summary 只在你点击重算时更新。',
      },
      doc: {
        title: '梳理文档说明',
        description: '这里是后续 PPT、报告和导图的主输入区，用来持续累积你确认过的正文内容，而不是临时聊天副本。',
        capabilities: '可追加、AI 整理、AI 融合，也可以手动编辑全文并回看历史版本。',
      },
      guidance: {
        title: '产出指导说明',
        description: '这里用来沉淀高权重的 brief，告诉后续产出必须强调什么、避免什么、采用什么口径。',
        capabilities: '它会参与大纲与正式生成，建议从关键问答中提炼，不直接手动编辑。',
      },
    };
    const item = config[panel];
    return (
      <div className="thinkflow-panel-guide">
        <div className="thinkflow-panel-guide-copy">
          <strong>{item.title}</strong>
          <p>{item.description}</p>
          <span>{item.capabilities}</span>
        </div>
        <button
          type="button"
          className="thinkflow-panel-guide-close"
          onClick={() => setPanelGuideVisibility((previous) => ({ ...previous, [panel]: false }))}
          aria-label={`关闭${item.title}`}
          title="关闭说明"
        >
          <X size={14} />
        </button>
      </div>
    );
  };

  const isOutputWorkspace = workspaceMode !== 'normal';
  // Only hide left sidebar for PPT (output_focus); keep it for non-PPT (output_immersive)
  const hideLeftSidebar = workspaceMode === 'output_focus';
  const layoutClassName = [
    'thinkflow-layout',
    !rightPanelOpen ? 'is-right-collapsed' : '',
    workspaceMode === 'output_focus' ? 'is-output-focus' : '',
    workspaceMode === 'output_immersive' ? 'is-output-immersive' : '',
  ]
    .filter(Boolean)
    .join(' ');
  const layoutStyle =
    workspaceMode === 'output_immersive'
      ? {
          // Non-PPT: left sidebar + chat (compressed but visible) + 45vw output panel
          display: 'grid',
          gridTemplateColumns: '280px minmax(0, 1fr) 45vw',
          width: '100%',
          minWidth: 'unset' as const,
          minHeight: 'calc(100dvh - 48px)',
          height: 'calc(100dvh - 48px)',
        }
      : workspaceMode === 'output_focus'
        ? {
            display: 'grid',
            gridTemplateColumns: '0px minmax(280px, 30%) minmax(620px, 70%)',
            width: 'max(100%, 1320px)',
            minWidth: 1320,
            minHeight: 'calc(100dvh - 48px)',
            height: 'calc(100dvh - 48px)',
          }
        : {
            display: 'grid',
            gridTemplateColumns: rightPanelOpen ? '280px minmax(0, 1fr) 392px' : '280px minmax(0, 1fr)',
            width: rightPanelOpen ? 'max(100%, 1220px)' : 'max(100%, 960px)',
            minWidth: rightPanelOpen ? 1220 : 960,
            minHeight: 'calc(100dvh - 48px)',
            height: 'calc(100dvh - 48px)',
          };

  const summaryPanelProps = {
    summaryItems: itemSummaryItems.map((item) => ({ id: item.id, title: item.title, summary_kind: item.summary_kind })),
    allSummary: allSummary ? { id: allSummary.id, title: allSummary.title, summary_kind: allSummary.summary_kind } : null,
    activeSummaryId,
    activeSummary: activeSummary ? { id: activeSummary.id, title: activeSummary.title, summary_kind: activeSummary.summary_kind } : null,
    summaryTitle,
    summaryContent,
    summaryEditMode,
    workspaceSaving,
    rebuildingAllSummary,
    panelGuide: renderPanelGuide('summary'),
    onSelectSummary: async (id: string) => {
      setRightMode('summary');
      await loadWorkspaceItemDetail(id);
    },
    onCreateSummary: () => createWorkspaceItem('summary'),
    onRebuildAllSummary: rebuildAllSummary,
    onToggleSummaryEdit: () => setSummaryEditMode((previous) => !previous),
    onDeleteSummary: (id: string) => deleteWorkspaceItem('summary', id),
    onSummaryTitleChange: setSummaryTitle,
    onSummaryContentChange: setSummaryContent,
    onSaveSummary: () => saveWorkspaceItem('summary'),
  };

  const guidancePanelProps = {
    guidanceItems: guidanceItems.map((item) => ({ id: item.id, title: item.title })),
    activeGuidanceId,
    activeGuidance: activeGuidance ? { id: activeGuidance.id, title: activeGuidance.title } : null,
    guidanceTitle,
    guidanceContent,
    panelGuide: renderPanelGuide('guidance'),
    onSelectGuidance: async (id: string) => {
      setRightMode('guidance');
      await loadWorkspaceItemDetail(id);
    },
    onCreateGuidance: () => createWorkspaceItem('guidance'),
    onDeleteGuidance: (id: string) => deleteWorkspaceItem('guidance', id),
  };

  const documentPanelProps = {
    documents: documents.map((doc) => ({ id: doc.id, title: doc.title })),
    activeDocumentId,
    activeDocument: activeDocument ? { id: activeDocument.id, title: activeDocument.title, document_type: activeDocument.document_type } : null,
    documentTitle,
    documentContent,
    editMode,
    showVersionPanel,
    versions,
    panelGuide: renderPanelGuide('doc'),
    documentSections,
    renderDocumentSection,
    docBodyRef,
    focusState: documentFocusState,
    stashItems: documentStashItems,
    changeLogs: documentChangeLogs,
    conversationActiveDocumentId,
    conversationActiveDocument: conversationActiveDocument
      ? { id: conversationActiveDocument.id, title: conversationActiveDocument.title }
      : null,
    guidanceItems: guidanceItems.map((item) => ({ id: item.id, title: item.title })),
    selectedGuidanceIds,
    outputButtons,
    generatingOutline,
    documentSaving,
    onSelectDocument: async (id: string) => {
      setActiveDocumentId(id);
      setRightMode('doc');
      await loadDocumentDetail(id);
      await setConversationActiveDocument(id);
    },
    onActivateDisplayedDocument: () => activeDocumentId ? setConversationActiveDocument(activeDocumentId) : Promise.resolve(),
    onClearFocus: () => updateDisplayedDocumentFocus(normalizeFocusState()),
    onCreateDocument: async () => { await createDocument(); },
    onCreateOutputDocument: createOutputDocument,
    onToggleDocumentEdit: () => setEditMode((previous) => !previous),
    onToggleVersionPanel: () => setShowVersionPanel((previous) => !previous),
    onDeleteDocument: deleteDocument,
    onDocumentTitleChange: setDocumentTitle,
    onDocumentContentChange: setDocumentContent,
    onRestoreVersion: restoreVersion,
    onToggleGuidanceSelection: toggleGuidanceSelection,
    onOutputAction: (type: string) => {
      if (type === 'ppt') {
        return openPptSourceLockIntent();
      }
      return openDirectOutputIntent(type as Exclude<OutputType, 'ppt'>);
    },
    onSaveDocument: saveDocument,
  };

  const outputPanelProps = {
    activeOutput: activeOutput ? { target_type: activeOutput.target_type } : null,
    generatingOutline,
    generatingOutlineLabel: outputButtons.find((item) => item.type === generatingOutline)?.label || '产出',
    outputWorkspaceHeader: renderOutputWorkspaceHeader(),
    pptWorkspace: renderPptWorkspace(),
    directOutputWorkspace: renderDirectOutputWorkspace(),
    isOutputHeaderCollapsed,
    onOutputWorkspaceScroll: handleOutputWorkspaceScroll,
  };

  const pushSourceSummary = buildPushSourceSummary(pushPopover.sourceEntries);

  return (
    <div className="thinkflow-root">
      <ThinkFlowTopBar notebookTitle={notebookTitle} onBack={onBack} onOpenHistory={openHistoryPanel} />

      {/* ── Toast stack ─────────────────────────────────────────────── */}
      {toasts.length > 0 && (
        <div className="thinkflow-toast-stack">
          {toasts.map((toast) => (
            <div key={toast.id} className={`thinkflow-toast thinkflow-toast-${toast.kind}`}>
              <span className="thinkflow-toast-msg">{toast.message}</span>
              <button
                type="button"
                className="thinkflow-toast-close"
                onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
              >
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div
        ref={layoutRef}
        className={layoutClassName}
        style={layoutStyle}
      >
        <ThinkFlowLeftSidebar
          activeOutputId={activeOutputId}
          files={files}
          getFileEmoji={fileEmoji}
          getOutputEmoji={outputEmoji}
          isOutputWorkspace={hideLeftSidebar}
          leftTab={leftTab}
          loadingFiles={loadingFiles}
          onLeftTabChange={(tab) => {
            setLeftTab(tab);
            if (tab === 'conversations') void refreshConversationList();
          }}
          onOpenOutput={openExistingOutput}
          onPreviewSource={handlePreviewSource}
          onDeleteSource={(file) => void handleDeleteSource(file)}
          onRefreshFiles={refreshFiles}
          onToggleSource={toggleSource}
          outputs={outputs}
          selectedIds={selectedIds}
          uploading={uploading}
          onUpload={handleUpload}
          onAddSource={() => setShowAddSourceModal(true)}
          onReEmbedSource={handleReEmbedSource}
          conversationList={conversationList}
          activeConversationId={conversationId}
          onSelectConversation={(id) => void loadConversationMessages(id)}
          onNewConversation={handleNewConversation}
        />

        <ThinkFlowCenterPanel
          activeOutput={activeOutput}
          boundDocIds={boundDocIds}
          chatTitle={isPptOutlineChatStage ? '📋 PPT 大纲讨论' : undefined}
          chatInput={chatInput}
          chatLoading={chatLoading}
          chatMessages={visibleChatMessages}
          chatPlaceholder={
            isPptOutlineChatStage
              ? '先说你想怎么调整这份 PPT，例如“整体更偏业务汇报，弱化技术细节”'
              : undefined
          }
          chatTopPanel={renderOutlineChatTopPanel()}
          chatScrollRef={chatScrollRef}
          documents={documents}
          focusedMessageId={focusedMessageId}
          handleChatSelectionMouseUp={handleChatSelectionMouseUp}
          handleSelectionCopy={handleSelectionCopy}
          handleSelectionPush={handleSelectionPush}
          handleSendMessage={handleSendMessage}
          isOutlineChatMode={isPptOutlineChatStage}
          messageRefs={messageRefs}
          multiSelectPrompt={multiSelectPrompt}
          openMultiMessagePush={openMultiMessagePush}
          openPushPopover={openPushPopover}
          openQAPushPopover={openQAPushPopover}
          openRightPanelForActiveOutput={() => {
            setRightPanelOpen(true);
            setRightMode(activeOutput ? 'outline' : 'doc');
          }}
          openRightPanelForDocument={() => {
            setRightPanelOpen(true);
            setRightMode('doc');
          }}
          clearSelectedMessages={clearSelectedMessages}
          renderMessageMarkdown={renderMessageMarkdown}
          rightPanelOpen={rightPanelOpen}
          selectedMessageIds={selectedMessageIds}
          selectionToolbar={selectionToolbar}
          setChatInput={setChatInput}
          setMultiSelectPrompt={setMultiSelectPrompt}
          toggleBoundDoc={toggleBoundDoc}
          toggleMessageSelection={toggleMessageSelection}
          workspaceMode={workspaceMode}
          onOpenHistory={openHistoryPanel}
          onNewConversation={handleNewConversation}
          chatMode={chatMode}
          onChatModeChange={setChatMode}
          activeDataset={activeDataset}
          dataSessionId={dataSessionId}
          notebookContext={{
            notebookId: notebook.id,
            notebookTitle,
            userId: effectiveUser?.id || 'local',
            userEmail: effectiveUser?.email || '',
          }}
        />

        {rightPanelOpen ? (
          <ThinkFlowRightPanel
            activeDocument={activeDocument}
            activeGuidance={activeGuidance}
            activeOutput={activeOutput}
            activeSummary={activeSummary}
            generatingOutline={generatingOutline}
            onClose={() => setRightPanelOpen(false)}
            onExitOutputWorkspace={exitOutputWorkspace}
            outputButtons={outputButtons}
            rightMode={rightMode}
            setRightMode={setRightMode}
            summaryPanelProps={summaryPanelProps}
            guidancePanelProps={guidancePanelProps}
            documentPanelProps={documentPanelProps}
            outputPanelProps={outputPanelProps}
            workspaceMode={workspaceMode}
          />
        ) : null}
      </div>

      {pptSourceLockIntent ? (
        <>
          <div className="thinkflow-popover-overlay" onClick={() => setPptSourceLockIntent(null)} />
          <div className="thinkflow-output-context-modal thinkflow-output-lock-modal">
            <div className="thinkflow-output-context-modal-header">
              <div>
                <h3>确认本次 PPT 来源</h3>
                <p>这一步会锁定本轮 PPT 的来源范围。确认后，当前 PPT 会话内不再提供“更新来源”的入口。</p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setPptSourceLockIntent(null)}>
                关闭
              </button>
            </div>

            <div className="thinkflow-output-context-modal-body">
              {pptSourceLockIntent.loading ? (
                <div className="thinkflow-empty">正在整理这次 PPT 的来源快照...</div>
              ) : pptSourceLockIntent.errorMessage ? (
                <div className="thinkflow-empty">{pptSourceLockIntent.errorMessage}</div>
              ) : (
                <>
                  <section className="thinkflow-output-context-group">
                    <div className="thinkflow-output-context-group-title">来源文件</div>
                    <div className="thinkflow-output-lock-list">
                      {pptSourceLockIntent.sourceNames.length > 0 ? (
                        pptSourceLockIntent.sourceNames.map((item) => (
                          <div key={item} className="thinkflow-output-lock-item">
                            {item}
                          </div>
                        ))
                      ) : (
                        <div className="thinkflow-empty">未选择来源文件</div>
                      )}
                    </div>
                  </section>

                  <section className="thinkflow-output-context-group">
                    <div className="thinkflow-output-context-group-title">梳理文档 / 参考文档</div>
                    <div className="thinkflow-output-lock-list">
                      {buildPptReferenceDocumentTitles(
                        pptSourceLockIntent.outputDocumentTitle,
                        pptSourceLockIntent.boundDocumentTitles,
                      ).length > 0 ? (
                        buildPptReferenceDocumentTitles(
                          pptSourceLockIntent.outputDocumentTitle,
                          pptSourceLockIntent.boundDocumentTitles,
                        ).map((item) => (
                          <div key={item} className="thinkflow-output-lock-item">
                            {item}
                          </div>
                        ))
                      ) : (
                        <div className="thinkflow-empty">未选择梳理文档</div>
                      )}
                    </div>
                  </section>

                  <section className="thinkflow-output-context-group">
                    <div className="thinkflow-output-context-group-title">产出指导</div>
                    <div className="thinkflow-output-lock-list">
                      {pptSourceLockIntent.guidanceTitles.length > 0 ? (
                        pptSourceLockIntent.guidanceTitles.map((item) => (
                          <div key={item} className="thinkflow-output-lock-item">
                            {item}
                          </div>
                        ))
                      ) : (
                        <div className="thinkflow-empty">未选择产出指导</div>
                      )}
                    </div>
                  </section>
                </>
              )}
            </div>

            <div className="thinkflow-output-context-modal-footer">
              <span className="thinkflow-output-context-hint">
                {pptSourceLockIntent.loading
                  ? '正在整理来源，请稍候。'
                  : pptSourceLockIntent.errorMessage
                    ? '来源解析失败，请关闭后重试。'
                    : '当前正在编辑的梳理文档也会在这里一并锁定。确认后将直接进入 PPT 大纲阶段。'}
              </span>
              <div className="thinkflow-output-context-actions">
                <button type="button" className="thinkflow-doc-action-btn" onClick={() => setPptSourceLockIntent(null)}>
                  取消
                </button>
                <button
                  type="button"
                  className="thinkflow-generate-btn"
                  onClick={() => void confirmPptSourceLockIntent()}
                  disabled={pptSourceLockIntent.loading || Boolean(pptSourceLockIntent.errorMessage)}
                >
                  {pptSourceLockIntent.loading ? '整理来源中...' : '确认并生成大纲'}
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}

      {directOutputIntent ? (
        <>
          <div className="thinkflow-popover-overlay" onClick={() => setDirectOutputIntent(null)} />
          <div className="thinkflow-output-context-modal thinkflow-output-lock-modal">
            <div className="thinkflow-output-context-modal-header">
              <div>
                <h3>确认本次{outputLabel(directOutputIntent.targetType)}来源</h3>
                <p>确认后会直接开始生成，并锁定这一版结果的来源快照。之后若要换输入范围，请重新生成一版。</p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setDirectOutputIntent(null)}>
                关闭
              </button>
            </div>

            <div className="thinkflow-output-context-modal-body">
              {directOutputIntent.loading ? (
                <div className="thinkflow-empty">正在整理这次{outputLabel(directOutputIntent.targetType)}的来源快照...</div>
              ) : directOutputIntent.errorMessage ? (
                <div className="thinkflow-empty">{directOutputIntent.errorMessage}</div>
              ) : (
                <>
                  <section className="thinkflow-output-context-group">
                    <div className="thinkflow-output-context-group-title">来源文件</div>
                    <div className="thinkflow-output-lock-list">
                      {directOutputIntent.sourceNames.length === 0 ? <div className="thinkflow-empty">未选择来源文件</div> : null}
                      {directOutputIntent.sourceNames.map((name) => (
                        <div key={name} className="thinkflow-output-lock-item">
                          {name}
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="thinkflow-output-context-group">
                    <div className="thinkflow-output-context-group-title">梳理文档 / 参考文档</div>
                    <div className="thinkflow-output-lock-list">
                      {buildDirectOutputDocumentTitles(
                        directOutputIntent.outputDocumentId,
                        directOutputIntent.outputDocumentTitle,
                        directOutputIntent.boundDocumentTitles,
                      ).length > 0 ? (
                        buildDirectOutputDocumentTitles(
                          directOutputIntent.outputDocumentId,
                          directOutputIntent.outputDocumentTitle,
                          directOutputIntent.boundDocumentTitles,
                        ).map((item) => (
                          <div key={item} className="thinkflow-output-lock-item">
                            {item}
                          </div>
                        ))
                      ) : (
                        <div className="thinkflow-empty">未选择梳理文档</div>
                      )}
                    </div>
                  </section>

                  <section className="thinkflow-output-context-group">
                    <div className="thinkflow-output-context-group-title">产出指导</div>
                    <div className="thinkflow-output-lock-list">
                      {directOutputIntent.guidanceTitles.length > 0 ? (
                        directOutputIntent.guidanceTitles.map((title) => (
                          <div key={title} className="thinkflow-output-lock-item">
                            {title}
                          </div>
                        ))
                      ) : (
                        <div className="thinkflow-empty">未选择产出指导</div>
                      )}
                    </div>
                  </section>
                </>
              )}
            </div>

            <div className="thinkflow-output-context-modal-footer">
              <span className="thinkflow-output-context-hint">
                {directOutputIntent.loading
                  ? '正在整理来源，请稍候。'
                  : directOutputIntent.errorMessage
                    ? '来源解析失败，请关闭后重试。'
                    : directOutputIntent.outputDocumentId
                      ? '当前正在编辑的梳理文档也会在这里一并锁定。确认后将直接开始生成结果。'
                      : '当前没有选择梳理文档，本次会直接基于来源和可选参考生成结果。'}
              </span>
              <div className="thinkflow-output-context-actions">
                <button type="button" className="thinkflow-doc-action-btn" onClick={() => setDirectOutputIntent(null)}>
                  取消
                </button>
                <button
                  type="button"
                  className="thinkflow-generate-btn"
                  onClick={() => void confirmDirectOutputIntent()}
                  disabled={directOutputIntent.loading || Boolean(directOutputIntent.errorMessage)}
                >
                  {directOutputIntent.loading ? '整理来源中...' : '确认并开始生成'}
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}

      {pushPopover.show ? (
        <>
          <div
            className="thinkflow-popover-overlay"
            onClick={() => {
              if (pushSubmitting) return;
              setPushPopover((previous) => ({ ...previous, show: false }));
            }}
          />
          <div
            className="thinkflow-push-popover"
            style={{
              left: pushPopover.x,
              top: pushPopover.y,
            }}
          >
            <div className="thinkflow-push-header">
              <div>
                <h3>推送到文档</h3>
                <p>AI 只会通过这次显式推送修改文档。</p>
              </div>
              <button
                type="button"
                className="thinkflow-push-close"
                disabled={pushSubmitting}
                onClick={() => setPushPopover((previous) => ({ ...previous, show: false }))}
              >
                关闭
              </button>
            </div>
            {pushSubmitting ? <div className="thinkflow-push-status is-pending">{pushStatusText || '正在处理中...'}</div> : null}
            {pushError ? <div className="thinkflow-push-status is-error">{pushError}</div> : null}
            <div className="thinkflow-push-body">
              <div className="thinkflow-push-field">
                <div className="thinkflow-push-label">目标位置</div>
                <select
                  className="thinkflow-push-select"
                  value={pushPopover.targetType}
                  disabled={pushSubmitting}
                  onChange={(event) => {
                    const targetType = event.target.value as StructuredPushTargetType;
                    setPushPopover((previous) => ({
                      ...previous,
                      targetType,
                      transform: coercePushTransform(targetType, previous.transform),
                    }));
                  }}
                >
                  {getDefaultPushTarget(documentFocusState) === 'focus' ? <option value="focus">当前焦点：{documentFocusState.description}</option> : null}
                  {documentSections.map((section) => (
                    <option key={section.id} value="section">
                      章节：{section.heading || section.id}
                    </option>
                  ))}
                  <option value="new_section">+ 新建章节</option>
                  <option value="stash">暂存区</option>
                  <option value="document_end">文档末尾</option>
                </select>
                {pushPopover.targetType === 'section' ? (
                  <select
                    className="thinkflow-push-select"
                    value={pushPopover.targetSectionId}
                    disabled={pushSubmitting}
                    onChange={(event) => setPushPopover((previous) => ({ ...previous, targetSectionId: event.target.value }))}
                  >
                    {documentSections.map((section) => (
                      <option key={section.id} value={section.id}>
                        {section.heading || section.id}
                      </option>
                    ))}
                  </select>
                ) : null}
                {pushPopover.targetType === 'new_section' ? (
                  <input
                    className="thinkflow-outline-input"
                    value={pushPopover.newSectionTitle}
                    disabled={pushSubmitting}
                    onChange={(event) => setPushPopover((previous) => ({ ...previous, newSectionTitle: event.target.value }))}
                    placeholder="新章节标题"
                  />
                ) : null}
              </div>

              <div className="thinkflow-push-field">
                <div className="thinkflow-push-label">处理方式</div>
                <div className="thinkflow-push-modes">
                  {[
                    { value: 'ai_append', label: '整理后追加', desc: '推荐：先归纳再写入目标位置' },
                    { value: 'raw_append', label: '原文追加', desc: '不改写来源内容，直接放入目标' },
                    { value: 'ai_merge', label: '融合到此章节', desc: '只适合当前焦点或现有章节' },
                  ].map((item) => {
                    const disabled = !canUsePushTransform(pushPopover.targetType, item.value as StructuredPushTransform);
                    return (
                      <label key={item.value} className={`thinkflow-push-mode ${pushPopover.transform === item.value ? 'is-active' : ''} ${disabled ? 'is-disabled' : ''}`}>
                        <input
                          type="radio"
                          checked={pushPopover.transform === item.value}
                          disabled={pushSubmitting || disabled}
                          onChange={() => setPushPopover((previous) => ({ ...previous, transform: item.value as StructuredPushTransform }))}
                        />
                        <div>
                          <div className="thinkflow-push-mode-title">{item.label}</div>
                          <div className="thinkflow-push-mode-desc">{item.desc}</div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div className="thinkflow-push-field">
                <div className="thinkflow-push-label">补充指示（可选）</div>
                <textarea
                  className="thinkflow-push-textarea"
                  value={pushPopover.prompt}
                  disabled={pushSubmitting}
                  onChange={(event) => setPushPopover((previous) => ({ ...previous, prompt: event.target.value }))}
                  placeholder={pushPopover.transform === 'raw_append' ? '原文追加不需要指令' : '如：提炼核心数据；标注 [待确认]；转成当前提纲'}
                />
              </div>

              <div className="thinkflow-push-field">
                <div className="thinkflow-push-label">本次沉淀来源</div>
                <div className="thinkflow-push-preview">
                  <span className="thinkflow-push-preview-chip">{pushSourceSummary.label}</span>
                  <p>{pushPopover.sourceContent.slice(0, 220)}</p>
                </div>
              </div>
            </div>

            <div className="thinkflow-push-actions">
              <button
                type="button"
                className="thinkflow-doc-action-btn"
                disabled={pushSubmitting}
                onClick={() => setPushPopover((previous) => ({ ...previous, show: false }))}
              >
                取消
              </button>
              <button type="button" className="thinkflow-generate-btn" onClick={() => void executePush()} disabled={pushSubmitting}>
                {pushSubmitting ? '处理中...' : '推送 ⟩'}
              </button>
            </div>
          </div>
        </>
      ) : null}

      {historyOpen ? (
        <>
          <div className="thinkflow-popover-overlay" onClick={() => setHistoryOpen(false)} />
          <div className="thinkflow-history-modal">
            <div className="thinkflow-history-header">
              <div>
                <h3>历史对话</h3>
                <p>这里展示当前笔记本下已记录的会话。</p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setHistoryOpen(false)}>
                关闭
              </button>
            </div>
            <div className="thinkflow-history-body">
              {historyLoading ? <div className="thinkflow-empty">正在加载历史对话...</div> : null}
              {!historyLoading && historyConversations.length === 0 ? <div className="thinkflow-empty">当前还没有可查看的历史对话。</div> : null}
              {!historyLoading && historyConversations.length > 0 ? (
                <div className="thinkflow-history-list">
                  {historyConversations.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`thinkflow-history-item ${item.id === conversationId ? 'is-active' : ''}`}
                      onClick={() => {
                        void (async () => {
                          setConversationId(item.id);
                          await loadConversationMessages(item.id);
                          setHistoryOpen(false);
                        })();
                      }}
                    >
                      <div className="thinkflow-history-meta">
                        <strong>{item.title || '新对话'}</strong>
                        {item.updated_at || item.created_at ? <span>{formatThinkFlowDateTime(item.updated_at || item.created_at)}</span> : null}
                      </div>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </>
      ) : null}

      {sourcePreviewOpen ? (
        <>
          <div className="thinkflow-popover-overlay" onClick={() => setSourcePreviewOpen(false)} />
          <div className="thinkflow-source-preview-modal">
            <div className="thinkflow-source-preview-header">
              <div>
                <h3>来源预览</h3>
                <p>{sourcePreviewFile?.name || ''}</p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setSourcePreviewOpen(false)}>
                关闭
              </button>
            </div>
            <div className="thinkflow-source-preview-body">
              {sourcePreviewLoading ? <div className="thinkflow-empty">正在加载来源内容...</div> : null}
              {!sourcePreviewLoading ? (
                <div className="thinkflow-source-preview-content">
                  <ReactMarkdown>{sourcePreviewContent}</ReactMarkdown>
                </div>
              ) : null}
            </div>
          </div>
        </>
      ) : null}

      <ThinkFlowAddSourceModal
        email={effectiveUser.email || ''}
        notebookId={notebook.id}
        notebookTitle={notebookTitle}
        onClose={() => setShowAddSourceModal(false)}
        onSourceAdded={() => void refreshFiles()}
        open={showAddSourceModal}
        userId={effectiveUser.id}
      />
    </div>
  );
};

export default ThinkFlowWorkspace;
