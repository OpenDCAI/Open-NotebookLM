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
  Play,
  Plus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
  Video,
  X,
} from 'lucide-react';

import { apiFetch } from '../config/api';
import { useAuthStore } from '../stores/authStore';
import type { KnowledgeFile } from '../types';
import { ThinkFlowAddSourceModal } from './ThinkFlowAddSourceModal';
import { ThinkFlowCenterPanel } from './ThinkFlowCenterPanel';
import { ThinkFlowFlashcardStudy } from './ThinkFlowFlashcardStudy';
import { ThinkFlowLeftSidebar } from './ThinkFlowLeftSidebar';
import { MermaidPreview } from './MermaidPreview';
import { ThinkFlowOutputContextModal } from './ThinkFlowOutputContextModal';
import { ThinkFlowQuizStudy } from './ThinkFlowQuizStudy';
import { ThinkFlowTopBar } from './ThinkFlowTopBar';
import { ThinkFlowRightPanel } from './ThinkFlowRightPanel';
import type { ChatMode } from './thinkflow-types';
import type { NotebookContext } from './TableAnalysisPanel';

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
  script_text?: string;
};

type WorkspaceItemType = 'summary' | 'guidance';
type PanelGuideKey = 'summary' | 'doc' | 'guidance';
type WorkspaceMode = 'normal' | 'output_focus' | 'output_immersive';
type PptPipelineStage = 'outline_ready' | 'pages_ready' | 'generated' | 'pending';

type ConversationHistoryMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
};

type ThinkFlowWorkspaceItem = {
  id: string;
  type: WorkspaceItemType;
  title: string;
  content?: string;
  source_refs?: DocumentSourceRef[];
  capture_count?: number;
  created_at: string;
  updated_at: string;
};

type OutputType = 'ppt' | 'video' | 'report' | 'mindmap' | 'podcast' | 'flashcard' | 'quiz';

type Paper2VideoConfig = {
  language: string;
  avatar_mode: 'none' | 'system' | 'custom';
  avatar_id: string;
  avatar_upload_token?: string;
};

type Paper2VideoPresetItem = {
  id: string;
  label: string;
  preview_url?: string;
  tts_model?: string;
};

type Paper2VideoOptionsPayload = {
  avatars: Paper2VideoPresetItem[];
  voices: Paper2VideoPresetItem[];
  tts_models: string[];
  languages: Array<{ id: string; label: string }>;
  defaults: Paper2VideoConfig;
  cosyvoice_voice_list_url: string;
};

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
  result?: Record<string, any>;
  guidance_item_ids?: string[];
  guidance_snapshot_text?: string;
  source_paths?: string[];
  source_names?: string[];
  bound_document_ids?: string[];
  bound_document_titles?: string[];
  result_path?: string;
  enable_images?: boolean;
  language?: string;
  paper2video_config?: Paper2VideoConfig;
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
  storyboardTarget: 'ppt' | 'video';
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
  videoConfig?: Paper2VideoConfig;
  paper2videoOptions?: Paper2VideoOptionsPayload | null;
  customAvatarFile?: File | null;
  customAvatarPreviewUrl?: string;
  submitting?: boolean;
};

type DirectOutputIntent = {
  targetType: Exclude<OutputType, 'ppt' | 'video'>;
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
  { type: 'video', label: '视频', icon: <Video size={14} /> },
  { type: 'report', label: '报告', icon: <FileText size={14} /> },
  { type: 'mindmap', label: '导图', icon: <Brain size={14} /> },
  { type: 'podcast', label: '播客', icon: <Mic2 size={14} /> },
  { type: 'flashcard', label: '卡片', icon: <BookOpen size={14} /> },
  { type: 'quiz', label: '测验', icon: <BarChart3 size={14} /> },
];

function isStoryboardOutputType(type: OutputType | string | undefined | null): type is 'ppt' | 'video' {
  return type === 'ppt' || type === 'video';
}

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
    case 'video':
      return '🎬';
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

function buildDefaultVideoConfig(options?: Paper2VideoOptionsPayload | null): Paper2VideoConfig {
  const defaults = options?.defaults;
  return {
    language: defaults?.language || 'zh',
    avatar_mode: defaults?.avatar_mode || 'none',
    avatar_id: defaults?.avatar_id || options?.avatars?.[0]?.id || 'avatar1',
    avatar_upload_token: '',
  };
}

async function fetchPaper2videoPresetBlobUrl(previewUrl: string): Promise<string> {
  const response = await apiFetch(previewUrl);
  if (!response.ok) {
    throw new Error('试听资源加载失败');
  }
  return URL.createObjectURL(await response.blob());
}

async function loadPaper2videoPresetPreviewUrls(options: Paper2VideoOptionsPayload): Promise<Record<string, string>> {
  const urls: Record<string, string> = {};
  const tasks: Array<Promise<void>> = [];
  const queue = options.avatars.map((avatar) => ({
    kind: 'avatar' as const,
    id: avatar.id,
    preview_url: avatar.preview_url,
  }));
  for (const item of queue) {
    if (!item.preview_url) continue;
    tasks.push(
      (async () => {
        try {
          urls[`${item.kind}:${item.id}`] = await fetchPaper2videoPresetBlobUrl(item.preview_url!);
        } catch {
          /* ignore preview failures */
        }
      })(),
    );
  }
  await Promise.all(tasks);
  return urls;
}

function paper2videoPayloadFromConfig(config: Paper2VideoConfig) {
  return {
    language: config.language,
    avatar_mode: config.avatar_mode,
    avatar_id: config.avatar_mode === 'system' ? config.avatar_id : undefined,
    avatar_upload_token: config.avatar_mode === 'custom' ? config.avatar_upload_token || undefined : undefined,
  };
}

function normalizePptStage(output: ThinkFlowOutput | null): PptPipelineStage {
  if (!output) return 'outline_ready';
  if (output.target_type === 'video' && (output.pipeline_stage === 'pending' || output.status === 'pending')) {
    return 'outline_ready';
  }
  if (output.pipeline_stage === 'pending' || output.status === 'pending') return 'pending';
  if (output.pipeline_stage === 'generated' || output.status === 'generated') return 'generated';
  if (output.pipeline_stage === 'pages_ready') return 'pages_ready';
  return 'outline_ready';
}

function getStoryboardStageLabel(targetType: OutputType, stage: PptPipelineStage) {
  const isVideo = targetType === 'video';
  if (stage === 'pending') {
    return isVideo ? '视频（旧版排队）' : '等待中';
  }
  switch (stage) {
    case 'outline_ready':
      return isVideo ? '分镜与来源' : '大纲确认';
    case 'pages_ready':
      return isVideo ? '口播稿与分镜确认' : '逐页生成确认';
    case 'generated':
      return '生成结果';
    default:
      return isVideo ? '视频' : 'PPT';
  }
}

function getPptPreviewImages(output: ThinkFlowOutput | null): string[] {
  if (!output) return [];
  const outlineImages = (output.outline || [])
    .map((item) => item.generated_img_path || item.ppt_img_path || '')
    .filter(Boolean);
  if (outlineImages.length > 0) return outlineImages;
  const resultPagecontent = Array.isArray(output.result?.pagecontent) ? output.result?.pagecontent : [];
  return resultPagecontent
    .map((item: any) => item?.generated_img_path || item?.ppt_img_path || '')
    .filter(Boolean);
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

function buildDocumentSections(content: string, traces: DocumentPushTrace[]) {
  const lines = String(content || '').split('\n');
  const headingStarts: number[] = [];
  lines.forEach((line, index) => {
    if (/^##\s+/.test(line.trim())) headingStarts.push(index);
  });

  if (headingStarts.length === 0) {
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
    content: string;
    lineStart: number;
    lineEnd: number;
    traces: DocumentPushTrace[];
  }> = [];

  const firstHeading = headingStarts[0];
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

  headingStarts.forEach((start, index) => {
    const nextStart = headingStarts[index + 1] ?? lines.length;
    const chunk = lines.slice(start, nextStart).join('\n').trim();
    if (!chunk) return;
    const lineStart = start + 1;
    const lineEnd = nextStart;
    sections.push({
      id: `section_${lineStart}`,
      content: chunk,
      lineStart,
      lineEnd,
      traces: traces.filter((trace) => trace.line_start <= lineEnd && trace.line_end >= lineStart),
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
  const [documentTitle, setDocumentTitle] = useState('');
  const [documentContent, setDocumentContent] = useState('');
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

  const [outputs, setOutputs] = useState<ThinkFlowOutput[]>([]);
  const [activeOutputId, setActiveOutputId] = useState('');
  const [outlineSaving, setOutlineSaving] = useState(false);
  const [generatingOutline, setGeneratingOutline] = useState<OutputType | null>(null);
  const [generatingOutput, setGeneratingOutput] = useState(false);
  const [pptOutlineFeedback, setPptOutlineFeedback] = useState('');
  const [pptRefiningOutline, setPptRefiningOutline] = useState(false);
  const [activePptSlideIndex, setActivePptSlideIndex] = useState<number>(0);
  const [pptOutlineReadonlyOpen, setPptOutlineReadonlyOpen] = useState(false);
  /** 视频成片阶段：主预览区在「成片」与「分镜图」之间切换 */
  const [videoPreviewTab, setVideoPreviewTab] = useState<'final' | 'slides'>('final');
  const [pptPagePrompt, setPptPagePrompt] = useState('');
  const [pptPageBusyAction, setPptPageBusyAction] = useState<'regenerate' | 'confirm' | 'select_version' | ''>('');
  const [pptPageStatus, setPptPageStatus] = useState('');
  const [outputContexts, setOutputContexts] = useState<Record<string, OutputContextState>>({});
  const [pptSourceLockIntent, setPptSourceLockIntent] = useState<PptSourceLockIntent | null>(null);
  const [paper2videoPresetPreviewUrls, setPaper2videoPresetPreviewUrls] = useState<Record<string, string>>({});
  const [directOutputIntent, setDirectOutputIntent] = useState<DirectOutputIntent | null>(null);

  const [chatMessages, setChatMessages] = useState<ThinkFlowMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '请先围绕左侧已选素材提问。对话是主线，你可以按需把某个回答、某组问答或多轮内容沉淀成摘要、整理进文档，或者加入产出指导。',
      time: new Date().toLocaleTimeString(),
    },
  ]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [boundDocIds, setBoundDocIds] = useState<string[]>([]);
  const [selectedMessageIds, setSelectedMessageIds] = useState<string[]>([]);
  const [multiSelectPrompt, setMultiSelectPrompt] = useState('');
  const [globalError, setGlobalErrorRaw] = useState('');
  const [captureFeedback, setCaptureFeedback] = useState('');

  // ── Toast system ──────────────────────────────────────────────────────────
  type ToastKind = 'error' | 'success' | 'info';
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
  const [pushSubmitting, setPushSubmitting] = useState(false);
  const [pushStatusText, setPushStatusText] = useState('');
  const [pushError, setPushError] = useState('');
  const [conversationId, setConversationId] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyMessages, setHistoryMessages] = useState<ConversationHistoryMessage[]>([]);

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

  const summaryItems = useMemo(
    () => workspaceItems.filter((item) => item.type === 'summary'),
    [workspaceItems],
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

  const activeOutput = useMemo(
    () => outputs.find((item) => item.id === activeOutputId) || null,
    [activeOutputId, outputs],
  );
  const activePptStage = useMemo(() => normalizePptStage(activeOutput), [activeOutput]);
  const activePptPreviewImages = useMemo(() => getPptPreviewImages(activeOutput), [activeOutput]);
  const activePptSlide = useMemo(() => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type)) return null;
    const slides = activeOutput.outline || [];
    if (slides.length === 0) return null;
    const safeIndex = Math.min(Math.max(activePptSlideIndex, 0), slides.length - 1);
    return { slide: slides[safeIndex], index: safeIndex };
  }, [activeOutput, activePptSlideIndex]);
  const activePptPageReviews = useMemo<PptPageReview[]>(() => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type)) return [];
    const existing = Array.isArray(activeOutput.page_reviews) ? activeOutput.page_reviews : [];
    if (existing.length > 0) return existing;
    return (activeOutput.outline || []).map((item, index) => ({
      page_index: index,
      page_num: item.pageNum || index + 1,
      confirmed: false,
    }));
  }, [activeOutput]);
  const activePptConfirmedCount = useMemo(
    () => activePptPageReviews.filter((item) => item.confirmed).length,
    [activePptPageReviews],
  );
  const activePptCurrentReview = useMemo(() => {
    if (!activePptSlide) return null;
    return activePptPageReviews.find((item) => item.page_index === activePptSlide.index) || null;
  }, [activePptPageReviews, activePptSlide]);
  const activePptPageVersions = useMemo<PptPageVersion[]>(() => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type) || !activePptSlide) return [];
    const versions = Array.isArray(activeOutput.page_versions) ? activeOutput.page_versions : [];
    return versions
      .filter((item) => item.page_index === activePptSlide.index)
      .sort((left, right) => {
        if (Boolean(left.selected) !== Boolean(right.selected)) {
          return left.selected ? -1 : 1;
        }
        return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
      });
  }, [activeOutput, activePptSlide]);
  const activePptCurrentPreview = useMemo(() => {
    if (!activePptSlide) return '';
    return (
      activePptSlide.slide.generated_img_path ||
      activePptSlide.slide.ppt_img_path ||
      activePptPreviewImages[activePptSlide.index] ||
      ''
    );
  }, [activePptPreviewImages, activePptSlide]);

  const withAssetVersion = (url: string, seed?: string) => {
    const cleanUrl = String(url || '').trim();
    if (!cleanUrl) return '';
    const separator = cleanUrl.includes('?') ? '&' : '?';
    return `${cleanUrl}${separator}v=${encodeURIComponent(seed || activeOutput?.updated_at || '')}`;
  };

  useEffect(() => {
    if (activeOutput?.target_type === 'video' && activeOutput?.result?.video_mp4_path) {
      setVideoPreviewTab('final');
    }
  }, [activeOutput?.id, activeOutput?.result?.video_mp4_path, activeOutput?.target_type]);

  const renderVideoMp4Player = (mp4Path: string) => {
    const src = withAssetVersion(mp4Path, activeOutput?.updated_at || activeOutput?.id);
    if (!src) return null;
    return (
      <div className="thinkflow-video-player-wrap">
        <video
          key={src}
          className="thinkflow-video-player"
          controls
          playsInline
          preload="metadata"
          src={src}
        >
          您的浏览器不支持视频播放，请使用下方按钮下载 MP4。
        </video>
      </div>
    );
  };

  const renderVideoMp4Actions = (mp4Path: string, size: 'lg' | 'sm' = 'lg') => {
    const href = withAssetVersion(mp4Path, activeOutput?.updated_at || activeOutput?.id);
    if (!href) return null;
    return (
      <div className={`thinkflow-video-actions ${size === 'sm' ? 'is-compact' : ''}`}>
        <a href={href} download className="thinkflow-video-btn thinkflow-video-btn-primary">
          <Download size={size === 'lg' ? 18 : 15} />
          下载 MP4
        </a>
        <a href={href} target="_blank" rel="noreferrer" className="thinkflow-video-btn thinkflow-video-btn-secondary">
          <ExternalLink size={size === 'lg' ? 16 : 14} />
          新标签页打开
        </a>
      </div>
    );
  };

  const documentSections = useMemo(
    () => buildDocumentSections(documentContent, activeDocument?.push_traces || []),
    [activeDocument?.push_traces, documentContent],
  );

  const selectedFilePaths = useMemo(() => {
    const chosen = files.filter((file) => selectedIds.has(file.id)).map((file) => resolveFileUrl(file));
    if (chosen.length > 0) return chosen.filter(Boolean);
    return files.map((file) => resolveFileUrl(file)).filter(Boolean);
  }, [files, selectedIds]);
  const selectedSourceNames = useMemo(() => {
    const chosen = files.filter((file) => selectedIds.has(file.id)).map((file) => file.name || '未命名来源');
    if (chosen.length > 0) return chosen;
    return files.map((file) => file.name || '未命名来源');
  }, [files, selectedIds]);

  const selectedSourceIds = useMemo(() => Array.from(selectedIds).sort(), [selectedIds]);
  const activeOutputContext = useMemo(
    () => {
      if (!activeOutputId) return null;
      const output = outputs.find((item) => item.id === activeOutputId) || null;
      if (!output || isStoryboardOutputType(output.target_type)) return null;
      return outputContexts[activeOutputId] || null;
    },
    [activeOutputId, outputContexts, outputs],
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

  const ensureOutputContext = (output: ThinkFlowOutput) => {
    if (!output?.id || isStoryboardOutputType(output.target_type)) return;
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
      setSelectedIds((previous) => {
        if (previous.size > 0) return previous;
        return new Set(nextFiles.slice(0, 3).map((file) => file.id));
      });
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
    setVersions(versionData.versions || []);
      setDocuments((previous) =>
      previous.map((item) => (item.id === documentId ? { ...item, ...detailData.document } : item)),
    );
    return detailData.document;
  };

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
        setVersions([]);
        setEditMode(false);
        setShowVersionPanel(false);
      }
      setBoundDocIds((previous) => previous.filter((id) => items.some((item) => item.id === id)));
      setPushPopover((previous) => ({
        ...previous,
        targetDocId:
          previous.targetDocId === '__new__'
            ? '__new__'
            : previous.targetDocId && items.some((item) => item.id === previous.targetDocId)
              ? previous.targetDocId
              : items[0]?.id || '__new__',
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

      const nextSummaryId =
        preferredId && items.some((item) => item.id === preferredId && item.type === 'summary')
          ? preferredId
          : activeSummaryId && items.some((item) => item.id === activeSummaryId && item.type === 'summary')
            ? activeSummaryId
            : items.find((item) => item.type === 'summary')?.id || '';

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

  const refreshOutputs = async (preferredId?: string) => {
    try {
      const response = await apiFetch(`/api/v1/kb/outputs?${notebookQuery}`);
      const data = await parseJson<{ outputs: ThinkFlowOutput[] }>(response);
      const items = data.outputs || [];
      setOutputs(items);
      const targetId = preferredId || activeOutputId;
      if (targetId && items.some((item) => item.id === targetId)) {
        setActiveOutputId(targetId);
      } else if (items[0]) {
        setActiveOutputId(items[0].id);
      } else {
        setActiveOutputId('');
      }
    } catch (error: any) {
      setGlobalError(error?.message || '加载产出失败');
    }
  };

  // ─── 表格分析：选中 dataset 文件时自动注册 datasource + 开启会话 ────────────
  useEffect(() => {
    if (!activeDataset) return;
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
  }, [activeDataset]);

  useEffect(() => {
    void (async () => {
      setGlobalError('');
      await Promise.all([refreshFiles(), refreshOutputs()]);
      await refreshWorkspaceItems();
      await refreshDocuments();
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
    if (!pptPageStatus) return;
    if (pptPageBusyAction) return;
    const timer = window.setTimeout(() => setPptPageStatus(''), 2400);
    return () => window.clearTimeout(timer);
  }, [pptPageBusyAction, pptPageStatus]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_GUIDE_STORAGE_KEY, JSON.stringify(panelGuideVisibility));
  }, [panelGuideVisibility]);

  useEffect(() => {
    if (!activeOutput) return;
    setIsOutputHeaderCollapsed(false);
    ensureOutputContext(activeOutput);
  }, [activeOutput]);

  const handleOutputWorkspaceScroll = useCallback((scrollTop: number) => {
    setIsOutputHeaderCollapsed((previous) => {
      if (!previous && scrollTop > 24) return true;
      if (previous && scrollTop <= 4) return false;
      return previous;
    });
  }, []);

  useEffect(() => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type)) return;
    const slideCount = activeOutput.outline?.length || 0;
    if (slideCount === 0) {
      setActivePptSlideIndex(0);
      return;
    }
    setActivePptSlideIndex((previous) => Math.min(Math.max(previous, 0), slideCount - 1));
  }, [activeOutput?.id, activeOutput?.outline, activeOutput?.target_type]);

  useEffect(() => {
    setPptPagePrompt('');
  }, [activeOutput?.id, activePptSlideIndex]);

  useEffect(() => {
    setPptOutlineReadonlyOpen(false);
  }, [activeOutput?.id, activePptStage]);

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

  const ensureConversationId = async () => {
    if (conversationId) return conversationId;
    try {
      const response = await apiFetch('/api/v1/kb/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: effectiveUser?.email || effectiveUser?.id || 'local',
          user_id: effectiveUser?.id || 'local',
          notebook_id: notebook.id,
        }),
      });
      const data = await parseJson<{ conversation_id?: string }>(response);
      const nextId = String(data?.conversation_id || '').trim();
      if (nextId) {
        setConversationId(nextId);
        return nextId;
      }
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
    setHistoryOpen(true);
    setHistoryLoading(true);
    try {
      const targetConversationId = await ensureConversationId();
      if (!targetConversationId) {
        setHistoryMessages(
          chatMessages
            .filter((item) => item.id !== 'welcome' && item.content.trim())
            .map((item) => ({
              id: item.id,
              role: item.role,
              content: item.content,
              created_at: item.time,
            })),
        );
        return;
      }
      const response = await apiFetch(`/api/v1/kb/conversations/${targetConversationId}/messages`);
      const data = await parseJson<{ messages?: ConversationHistoryMessage[] }>(response);
      const rows = Array.isArray(data?.messages) ? data.messages : [];
      if (rows.length > 0) {
        setHistoryMessages(
          rows.map((item, index) => ({
            id: item.id || `history_${index}`,
            role: item.role === 'assistant' ? 'assistant' : 'user',
            content: item.content || '',
            created_at: item.created_at,
          })),
        );
      } else {
        setHistoryMessages(
          chatMessages
            .filter((item) => item.id !== 'welcome' && item.content.trim())
            .map((item) => ({
              id: item.id,
              role: item.role,
              content: item.content,
              created_at: item.time,
            })),
        );
      }
    } catch (error: any) {
      setGlobalError(error?.message || '加载历史对话失败');
      setHistoryMessages(
        chatMessages
          .filter((item) => item.id !== 'welcome' && item.content.trim())
          .map((item) => ({
            id: item.id,
            role: item.role,
            content: item.content,
            created_at: item.time,
          })),
      );
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleNewConversation = () => {
    setConversationId('');
    setChatMessages([
      {
        id: 'welcome',
        role: 'assistant',
        content: '请先围绕左侧已选素材提问。对话是主线，你可以按需把某个回答、某组问答或多轮内容沉淀成摘要、整理进文档，或者加入产出指导。',
        time: new Date().toLocaleTimeString(),
      },
    ]);
    setChatInput('');
    setSelectedMessageIds([]);
    setMultiSelectPrompt('');
    setBoundDocIds([]);
  };

  const enterOutputWorkspace = (mode: WorkspaceMode = 'output_focus') => {
    setRightPanelOpen(true);
    setRightMode('outline');
    setWorkspaceMode(mode);
  };

  const exitOutputWorkspace = () => {
    setPptSourceLockIntent(null);
    setDirectOutputIntent(null);
    setWorkspaceMode('normal');
    setRightMode('doc');
    setRightPanelOpen(true);
  };

  const resolveOutputCreationInputs = async (
    targetType: OutputType,
    options?: {
      titleOverride?: string;
      documentIdOverride?: string;
      guidanceItemIdsOverride?: string[];
      boundDocumentIdsOverride?: string[];
      sourceIdsOverride?: string[];
      sourcePathsOverride?: string[];
      sourceNamesOverride?: string[];
    },
  ) => {
    const overrideGuidanceIds = options?.guidanceItemIdsOverride;
    const overrideBoundDocIds = options?.boundDocumentIdsOverride;
    const overrideSourceIds = options?.sourceIdsOverride;
    const overrideSourcePaths = options?.sourcePathsOverride;
    const overrideSourceNames = options?.sourceNamesOverride;
    const resolvedGuidanceIds = overrideGuidanceIds ? [...overrideGuidanceIds] : [...selectedGuidanceIds];
    const resolvedBoundDocIds = overrideBoundDocIds ? [...overrideBoundDocIds] : [...boundDocIds];
    const resolvedSourceIds =
      overrideSourceIds && overrideSourceIds.length > 0
        ? [...overrideSourceIds]
        : selectedSourceIds.length > 0
          ? [...selectedSourceIds]
          : files.map((file) => file.id);
    const resolvedSourceEntries =
      resolvedSourceIds.length > 0
        ? files.filter((file) => resolvedSourceIds.includes(file.id))
        : files;
    const resolvedSourcePaths =
      overrideSourcePaths && overrideSourcePaths.length > 0
        ? [...overrideSourcePaths]
        : resolvedSourceEntries.map((file) => resolveFileUrl(file)).filter(Boolean);
    const resolvedSourceNames =
      overrideSourceNames && overrideSourceNames.length > 0
        ? [...overrideSourceNames]
        : resolvedSourceEntries.map((file) => file.name || '未命名来源');

    let outputDocumentId =
      options?.documentIdOverride ??
      activeDocumentId ??
      (isStoryboardOutputType(targetType) ? activeOutput?.document_id || '' : '');
    let outputDocumentTitle = documentTitle || activeDocument?.title || '文档';
    let outputDocumentContent = documentContent;
    if (outputDocumentId && outputDocumentId !== activeDocumentId) {
      const ensuredDocument = await ensureDocumentContent(outputDocumentId);
      if (ensuredDocument) {
        outputDocumentTitle = ensuredDocument.title || outputDocumentTitle;
        outputDocumentContent = ensuredDocument.content || outputDocumentContent;
      }
    }
    if (isStoryboardOutputType(targetType) && (!outputDocumentTitle || outputDocumentTitle === '文档')) {
      outputDocumentTitle = resolvedSourceNames[0] || notebookTitle || (targetType === 'video' ? '视频' : 'PPT');
    }
    if (!isStoryboardOutputType(targetType) && !String(outputDocumentContent || '').trim()) {
      outputDocumentId = '';
      outputDocumentTitle = resolvedSourceNames[0] || notebookTitle || outputLabel(targetType);
      outputDocumentContent = '';
    }
    if (
      resolvedSourcePaths.length === 0 &&
      !String(outputDocumentContent || '').trim() &&
      resolvedBoundDocIds.length === 0 &&
      resolvedGuidanceIds.length === 0
    ) {
      throw new Error('请先选择至少一个来源，或选择一份梳理文档 / 参考文档 / 产出指导。');
    }

    const resolvedGuidanceTitles = guidanceItems
      .filter((item) => resolvedGuidanceIds.includes(item.id))
      .map((item) => item.title || '未命名产出指导');
    const resolvedBoundDocTitles = documents
      .filter((item) => resolvedBoundDocIds.includes(item.id))
      .map((item) => item.title || '未命名参考文档');
    const outputTitle =
      options?.titleOverride ||
      `${outputDocumentTitle || '文档'} · ${outputButtons.find((item) => item.type === targetType)?.label || targetType}`;

    return {
      outputDocumentId,
      outputDocumentTitle,
      outputDocumentContent,
      resolvedGuidanceIds,
      resolvedGuidanceTitles,
      resolvedBoundDocIds,
      resolvedBoundDocTitles,
      resolvedSourceIds,
      resolvedSourcePaths,
      resolvedSourceNames,
      outputTitle,
    };
  };

  const openPptSourceLockIntent = async (storyboardTarget: 'ppt' | 'video' = 'ppt') => {
    setGlobalError('');
    setPptSourceLockIntent({
      storyboardTarget,
      outputDocumentId: '',
      outputDocumentTitle: documentTitle || activeDocument?.title || '梳理文档',
      outputTitle: `${documentTitle || activeDocument?.title || notebookTitle || '文档'} · ${outputLabel(storyboardTarget)}`,
      guidanceItemIds: [],
      guidanceTitles: [],
      boundDocumentIds: [],
      boundDocumentTitles: [],
      sourcePaths: [],
      sourceNames: [],
      loading: true,
      errorMessage: '',
      videoConfig: buildDefaultVideoConfig(),
      paper2videoOptions: null,
      customAvatarFile: null,
      customAvatarPreviewUrl: '',
    });
    try {
      const resolved = await resolveOutputCreationInputs(storyboardTarget);
      let paper2videoOptions: Paper2VideoOptionsPayload | null = null;
      let videoConfig = buildDefaultVideoConfig();
      if (storyboardTarget === 'video') {
        const optionsResponse = await apiFetch('/api/v1/kb/outputs/paper2video/options');
        const optionsData = await parseJson<Paper2VideoOptionsPayload & { success?: boolean }>(optionsResponse);
        paper2videoOptions = optionsData;
        videoConfig = buildDefaultVideoConfig(optionsData);
        const previewUrls = await loadPaper2videoPresetPreviewUrls(optionsData);
        setPaper2videoPresetPreviewUrls((previous) => {
          Object.values(previous).forEach((url) => URL.revokeObjectURL(url));
          return previewUrls;
        });
      }
      setPptSourceLockIntent((current) =>
        current
          ? {
              ...current,
              outputDocumentId: resolved.outputDocumentId,
              outputDocumentTitle: resolved.outputDocumentTitle,
              outputTitle: resolved.outputTitle,
              guidanceItemIds: resolved.resolvedGuidanceIds,
              guidanceTitles: resolved.resolvedGuidanceTitles,
              boundDocumentIds: resolved.resolvedBoundDocIds,
              boundDocumentTitles: resolved.resolvedBoundDocTitles,
              sourcePaths: resolved.resolvedSourcePaths,
              sourceNames: resolved.resolvedSourceNames,
              paper2videoOptions,
              videoConfig,
              loading: false,
              errorMessage: '',
            }
          : current,
      );
    } catch (error: any) {
      const message = error?.message || '无法确认本次来源';
      setGlobalError(message);
      setPptSourceLockIntent((current) =>
        current
          ? {
              ...current,
              loading: false,
              errorMessage: message,
            }
          : current,
      );
    }
  };

  const switchVideoLockToPptFlow = useCallback(() => {
    setPptSourceLockIntent((current) => {
      if (!current || current.storyboardTarget !== 'video') return current;
      if (current.customAvatarPreviewUrl) {
        URL.revokeObjectURL(current.customAvatarPreviewUrl);
      }
      const docTitle =
        current.outputDocumentTitle ||
        documentTitle ||
        activeDocument?.title ||
        notebookTitle ||
        '文档';
      return {
        ...current,
        storyboardTarget: 'ppt',
        outputTitle: `${docTitle} · PPT`,
        videoConfig: undefined,
        paper2videoOptions: null,
        customAvatarFile: null,
        customAvatarPreviewUrl: '',
      };
    });
  }, [activeDocument?.title, documentTitle, notebookTitle]);

  const confirmPptSourceLockIntent = async () => {
    if (
      !pptSourceLockIntent ||
      pptSourceLockIntent.loading ||
      pptSourceLockIntent.submitting ||
      pptSourceLockIntent.errorMessage
    ) {
      return;
    }
    const intent = pptSourceLockIntent;
    setPptSourceLockIntent((current) => (current ? { ...current, submitting: true } : current));
    try {
      let videoConfig = intent.videoConfig;
      if (intent.storyboardTarget === 'video' && videoConfig) {
        if (videoConfig.avatar_mode === 'custom') {
          if (!intent.customAvatarFile && !videoConfig.avatar_upload_token) {
            throw new Error('请上传自定义数字人图片，或选择系统数字人 / 不使用数字人。');
          }
          if (intent.customAvatarFile) {
            const formData = new FormData();
            formData.append('file', intent.customAvatarFile);
            const uploadResponse = await apiFetch(`/api/v1/kb/outputs/paper2video/upload-avatar?${notebookQuery}`, {
              method: 'POST',
              body: formData,
            });
            const uploadData = await parseJson<{ upload_token?: string }>(uploadResponse);
            videoConfig = {
              ...videoConfig,
              avatar_upload_token: String(uploadData.upload_token || '').trim(),
            };
          }
        }
      }
      setPptSourceLockIntent(null);
      if (intent.customAvatarPreviewUrl) {
        URL.revokeObjectURL(intent.customAvatarPreviewUrl);
      }
      await createOutline(intent.storyboardTarget, {
        titleOverride: intent.outputTitle,
        documentIdOverride: intent.outputDocumentId,
        guidanceItemIdsOverride: intent.guidanceItemIds,
        boundDocumentIdsOverride: intent.boundDocumentIds,
        sourcePathsOverride: intent.sourcePaths,
        sourceNamesOverride: intent.sourceNames,
        videoConfig: intent.storyboardTarget === 'video' ? videoConfig : undefined,
      });
    } catch (error: any) {
      setGlobalError(error?.message || '无法创建视频产出');
      setPptSourceLockIntent((current) => (current ? { ...current, submitting: false } : current));
    }
  };

  const openDirectOutputIntent = async (targetType: Exclude<OutputType, 'ppt' | 'video'>) => {
    setGlobalError('');
    setDirectOutputIntent({
      targetType,
      outputDocumentId: '',
      outputDocumentTitle: documentTitle || activeDocument?.title || selectedSourceNames[0] || '基于当前来源直接生成',
      outputTitle: `${documentTitle || activeDocument?.title || selectedSourceNames[0] || notebookTitle || '来源'} · ${outputLabel(targetType)}`,
      guidanceItemIds: [],
      guidanceTitles: [],
      boundDocumentIds: [],
      boundDocumentTitles: [],
      sourceIds: [],
      sourcePaths: [],
      sourceNames: [],
      loading: true,
      errorMessage: '',
    });
    try {
      const resolved = await resolveOutputCreationInputs(targetType);
      setDirectOutputIntent((current) =>
        current && current.targetType === targetType
          ? {
              ...current,
              outputDocumentId: resolved.outputDocumentId,
              outputDocumentTitle: resolved.outputDocumentTitle,
              outputTitle: resolved.outputTitle,
              guidanceItemIds: resolved.resolvedGuidanceIds,
              guidanceTitles: resolved.resolvedGuidanceTitles,
              boundDocumentIds: resolved.resolvedBoundDocIds,
              boundDocumentTitles: resolved.resolvedBoundDocTitles,
              sourceIds: resolved.resolvedSourceIds,
              sourcePaths: resolved.resolvedSourcePaths,
              sourceNames: resolved.resolvedSourceNames,
              loading: false,
              errorMessage: '',
            }
          : current,
      );
    } catch (error: any) {
      const message = error?.message || '无法确认本次产出来源';
      setGlobalError(message);
      setDirectOutputIntent((current) =>
        current && current.targetType === targetType
          ? {
              ...current,
              loading: false,
              errorMessage: message,
            }
          : current,
      );
    }
  };

  const confirmDirectOutputIntent = async () => {
    if (!directOutputIntent || directOutputIntent.loading || directOutputIntent.errorMessage) return;
    const intent = directOutputIntent;
    setDirectOutputIntent(null);
    await createOutline(intent.targetType, {
      autoGenerate: true,
      titleOverride: intent.outputTitle,
      documentIdOverride: intent.outputDocumentId,
      guidanceItemIdsOverride: intent.guidanceItemIds,
      boundDocumentIdsOverride: intent.boundDocumentIds,
      sourceIdsOverride: intent.sourceIds,
      sourcePathsOverride: intent.sourcePaths,
      sourceNamesOverride: intent.sourceNames,
    });
  };

  const openExistingOutput = async (output: ThinkFlowOutput) => {
    setPptSourceLockIntent(null);
    setDirectOutputIntent(null);
    setPptOutlineFeedback('');
    setActivePptSlideIndex(0);
    setActiveOutputId(output.id);
    setLeftTab('outputs');
    ensureOutputContext(output);
    enterOutputWorkspace(isStoryboardOutputType(output.target_type) ? 'output_focus' : 'output_immersive');
    if (output.document_id) {
      setActiveDocumentId(output.document_id);
      try {
        await loadDocumentDetail(output.document_id);
      } catch {}
    }
  };

  const toggleSource = (fileId: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });

    // 当选中 dataset（CSV/Excel）时，自动激活表格分析模式
    const selected = files.find((f) => f.id === fileId);
    if (selected?.type === 'dataset') {
      setActiveDataset(selected);
      setChatMode('table-analysis');
      setDataSessionId(null); // 重置，等待新会话
    }
  };

  const toggleBoundDoc = (documentId: string) => {
    setBoundDocIds((previous) => {
      if (previous.includes(documentId)) return previous.filter((id) => id !== documentId);
      return [...previous, documentId];
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
    </div>
  );

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
    preferredDestination = 'summary',
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
    setRightMode(preferredDestination === 'document' ? 'doc' : preferredDestination);
    setSelectionToolbar((previous) => ({ ...previous, show: false }));
    setPushPopover({
      show: true,
      x: nextX,
      y: nextY,
      preset,
      destinationType: preferredDestination,
      targetDocId: activeDocumentId || documents[0]?.id || '__new__',
      targetItemId:
        preferredDestination === 'summary'
          ? activeSummaryId || summaryItems[0]?.id || '__new__'
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
      preferredDestination: 'summary',
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
      preferredDestination: 'guidance',
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
      preferredDestination: 'summary',
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
      preferredDestination: 'summary',
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

  const renderDocumentSection = (section: ReturnType<typeof buildDocumentSections>[number]) => {
    const shouldHighlight = section.traces.some((trace) => trace.id === highlightedTraceId);
    return (
      <section
        key={section.id}
        className={`thinkflow-doc-section ${shouldHighlight ? 'is-highlighted' : ''}`}
        data-section-id={section.id}
        data-trace-ids={section.traces.map((trace) => trace.id).join(',')}
      >
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

  const createDocument = async (title?: string) => {
    try {
      const nextTitle = (title || '').trim() || `梳理摘要 ${documents.length + 1}`;
      const response = await apiFetch('/api/v1/kb/documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          title: nextTitle,
          content: '',
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

  const executePush = async () => {
    if (pushSubmitting) return;
    const {
      preset,
      destinationType,
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
    setPushStatusText(describePushAction(destinationType, mode));
    try {
      const resolvedTitle = await resolvePushTitle({
        destinationType,
        sourceContent,
        prompt,
        manualTitle: newTitle,
      });
      setPushStatusText(describePushAction(destinationType, mode));
      const selectedFiles = files.filter((file) => selectedIds.has(file.id)).slice(0, 3);
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
        if (docId === '__new__') {
          const createdId = await createDocument(resolvedTitle);
          if (!createdId) return;
          docId = createdId;
          docTitle = resolvedTitle;
        }
        const response = await apiFetch(`/api/v1/kb/documents/${docId}/push`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebookTitle,
            user_id: effectiveUser?.id || 'local',
            email: effectiveUser?.email || '',
            mode,
            title: resolvedTitle || '对话沉淀',
            prompt,
            text_items: [sourceContent],
            source_refs: sourceRefs,
          }),
        });
        const data = await parseJson<{ document: ThinkFlowDocument; trace?: DocumentPushTrace }>(response);
        setActiveDocumentId(docId);
        setRightPanelOpen(true);
        setRightMode('doc');
        if (data.trace?.id) setHighlightedTraceId(data.trace.id);
        await refreshDocuments(docId);
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

  const handleSendMessage = async () => {
    const query = chatInput.trim();
    if (!query || chatLoading) return;
    setChatLoading(true);
    setGlobalError('');

    const userMessage: ThinkFlowMessage = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: query,
      time: new Date().toLocaleTimeString(),
    };
    const assistantMessage: ThinkFlowMessage = {
      id: `assistant_${Date.now()}`,
      role: 'assistant',
      content: '',
      time: new Date().toLocaleTimeString(),
    };

    setChatMessages((previous) => [...previous, userMessage, assistantMessage]);
    setChatInput('');

    try {
      const boundDocs = await Promise.all(boundDocIds.map((id) => ensureDocumentContent(id)));
      const validDocs = boundDocs.filter(Boolean) as ThinkFlowDocument[];
      const docContext = validDocs
        .map((doc) => `参考文档《${doc.title}》:\n${String(doc.content || '').slice(0, 2400)}`)
        .join('\n\n');
      const finalQuery = docContext
        ? `${docContext}\n\n用户问题：${query}\n\n要求：优先围绕上述梳理文档与当前素材回答。`
        : query;

      const response = await apiFetch('/api/v1/kb/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: selectedFilePaths,
          query: finalQuery,
          history: chatMessages
            .filter((item) => item.id !== 'welcome')
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

  const createOutline = async (
    targetType: OutputType,
    options?: {
      autoGenerate?: boolean;
      titleOverride?: string;
      documentIdOverride?: string;
      guidanceItemIdsOverride?: string[];
      boundDocumentIdsOverride?: string[];
      sourceIdsOverride?: string[];
      sourcePathsOverride?: string[];
      sourceNamesOverride?: string[];
      videoConfig?: Paper2VideoConfig;
    },
  ) => {
    setGlobalError('');
    setGeneratingOutline(targetType);
    setActiveOutputId('');
    setPptOutlineFeedback('');
    setActivePptSlideIndex(0);
    setLeftTab('outputs');
    setRightMode('outline');
    enterOutputWorkspace(isStoryboardOutputType(targetType) ? 'output_focus' : 'output_immersive');
    try {
      const {
        outputDocumentId,
        resolvedGuidanceIds,
        resolvedBoundDocIds,
        resolvedSourceIds,
        resolvedSourcePaths,
        outputTitle,
        resolvedSourceNames,
      } = await resolveOutputCreationInputs(targetType, options);
      const outlinePayload = {
        notebook_id: notebook.id,
        notebook_title: notebookTitle,
        user_id: effectiveUser?.id || 'local',
        email: effectiveUser?.email || '',
        document_id: outputDocumentId,
        target_type: targetType,
        title: outputTitle,
        prompt: '',
        page_count: isStoryboardOutputType(targetType) ? 10 : 6,
        guidance_item_ids: resolvedGuidanceIds,
        source_paths: resolvedSourcePaths,
        source_names: resolvedSourceNames,
        bound_document_ids: resolvedBoundDocIds,
        enable_images: isStoryboardOutputType(targetType) ? true : undefined,
        ...(targetType === 'video' && options?.videoConfig
          ? paper2videoPayloadFromConfig(options.videoConfig)
          : {}),
      };
      console.info('[ThinkFlow] createOutline payload', outlinePayload);
      const response = await apiFetch('/api/v1/kb/outputs/outline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(outlinePayload),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      const nextOutput = data.output;
      setPptOutlineFeedback('');
      setActivePptSlideIndex(0);
      setRightMode('outline');
      setLeftTab('outputs');
      setOutputs((previous) => {
        const existingIndex = previous.findIndex((item) => item.id === nextOutput.id);
        if (existingIndex >= 0) {
          const nextItems = [...previous];
          nextItems[existingIndex] = nextOutput;
          return nextItems;
        }
        return [nextOutput, ...previous];
      });
      setActiveOutputId(nextOutput.id);
      if (!isStoryboardOutputType(targetType)) {
        setOutputContexts((previous) => ({
          ...previous,
          [nextOutput.id]: {
            snapshot: buildOutputContextSnapshot({
              outputId: nextOutput.id,
              targetType,
              documentId: outputDocumentId,
              guidanceItemIds: resolvedGuidanceIds,
              selectedSourceIds: resolvedSourceIds,
              boundDocumentIds: resolvedBoundDocIds,
            }),
            isStale: false,
            staleReason: '',
          },
        }));
      }
      void refreshOutputs(nextOutput.id);
      // 视频成片走 paper2video/*，勿调用 /generate（对 video 几乎无效果）
      if (options?.autoGenerate && targetType !== 'video') {
        await generateOutputById(nextOutput.id);
      }
    } catch (error: any) {
      setGlobalError(error?.message || '生成大纲失败');
    } finally {
      setGeneratingOutline(null);
    }
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

  const saveOutline = async (options?: { pipelineStage?: string; enableImages?: boolean }): Promise<boolean> => {
    if (!activeOutputId || !activeOutput) return false;
    setOutlineSaving(true);
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/outline`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          title: activeOutput.title,
          prompt: activeOutput.prompt || '',
          outline: activeOutput.outline || [],
          pipeline_stage: options?.pipelineStage,
          enable_images:
            typeof options?.enableImages === 'boolean'
              ? options.enableImages
              : activeOutput.enable_images,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      return true;
    } catch (error: any) {
      setGlobalError(error?.message || '保存大纲失败');
      return false;
    } finally {
      setOutlineSaving(false);
    }
  };

  const confirmPptOutline = async () => {
    await saveOutline({ pipelineStage: 'pages_ready' });
  };

  const runPaper2videoSubtitle = async () => {
    if (!activeOutputId || !activeOutput || activeOutput.target_type !== 'video') return;
    const saved = await saveOutline();
    if (!saved) return;
    setGeneratingOutput(true);
    try {
      const p2vConfig = activeOutput.paper2video_config;
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/paper2video/run-subtitle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          ...(p2vConfig ? paper2videoPayloadFromConfig(p2vConfig) : {}),
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      setActivePptSlideIndex(0);
      await refreshOutputs(activeOutputId);
    } catch (error: any) {
      setGlobalError(error?.message || '生成逐镜口播稿失败');
    } finally {
      setGeneratingOutput(false);
    }
  };

  const runPaper2videoContinue = async () => {
    if (!activeOutputId || !activeOutput || activeOutput.target_type !== 'video') return;
    const outlineLen = (activeOutput.outline || []).length;
    if (!outlineLen) {
      setGlobalError('分镜大纲为空，无法合成视频。');
      return;
    }
    if (activePptConfirmedCount < outlineLen) {
      setGlobalError('请先逐镜确认口播稿，再合成视频。');
      return;
    }
    const saved = await saveOutline();
    if (!saved) return;
    setGeneratingOutput(true);
    try {
      const p2vConfig = activeOutput.paper2video_config;
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/paper2video/continue-after-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          ...(p2vConfig ? paper2videoPayloadFromConfig(p2vConfig) : {}),
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      await refreshOutputs(activeOutputId);
    } catch (error: any) {
      setGlobalError(error?.message || '合成视频失败');
    } finally {
      setGeneratingOutput(false);
    }
  };

  const refinePptOutline = async () => {
    if (!activeOutputId || !activeOutput || !isStoryboardOutputType(activeOutput.target_type)) return;
    const feedback = String(pptOutlineFeedback || '').trim();
    if (!feedback) {
      setGlobalError('请先输入你想让 AI 修改大纲的要求。');
      return;
    }
    setPptRefiningOutline(true);
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/outline-refine`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          feedback,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      setPptOutlineFeedback('');
    } catch (error: any) {
      setGlobalError(error?.message || 'AI 修改大纲失败');
    } finally {
      setPptRefiningOutline(false);
    }
  };

  const regenerateActivePptPage = async () => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type) || !activePptSlide) return;
    const prompt = String(pptPagePrompt || '').trim();
    if (!prompt) {
      setGlobalError('请先输入你想修改当前页的要求。');
      return;
    }
    if (!activePptCurrentPreview && activeOutput.target_type === 'ppt') {
      setGlobalError('请先生成一版页面草稿，再改单页。');
      return;
    }
    if (activeOutput.target_type === 'video') {
      setGlobalError('视频分镜暂不支持「按提示重做当前页」。请直接编辑口播稿并保存，再确认当前镜。');
      return;
    }
    setPptPageBusyAction('regenerate');
    setPptPageStatus(`第 ${activePptSlide.index + 1} 页正在按提示重做...`);
    console.info('[ThinkFlow] regeneratePptPage:start', {
      outputId: activeOutput.id,
      pageIndex: activePptSlide.index,
      prompt,
    });
    try {
      const regenPath = `/api/v1/kb/outputs/${activeOutput.id}/pages/${activePptSlide.index}/regenerate`;
      const response = await apiFetch(regenPath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          prompt,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      setPptPagePrompt('');
      console.info('[ThinkFlow] regeneratePptPage:success', {
        outputId: data.output.id,
        pageIndex: activePptSlide.index,
        updatedAt: data.output.updated_at,
      });
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页已重新生成，可在预览图下方切换历史版本`);
    } catch (error: any) {
      console.error('[ThinkFlow] regeneratePptPage:error', {
        outputId: activeOutput.id,
        pageIndex: activePptSlide.index,
        error: error?.message || String(error || ''),
      });
      setGlobalError(error?.message || '当前页重生成失败');
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页重生成失败`);
    } finally {
      setPptPageBusyAction('');
    }
  };

  const selectActivePptPageVersion = async (versionId: string) => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type) || !activePptSlide || !versionId) return;
    setPptPageBusyAction('select_version');
    setPptPageStatus(`第 ${activePptSlide.index + 1} 页正在切换历史版本...`);
    console.info('[ThinkFlow] selectPptPageVersion:start', {
      outputId: activeOutput.id,
      pageIndex: activePptSlide.index,
      versionId,
    });
    try {
      const selPath =
        activeOutput.target_type === 'video'
          ? `/api/v1/kb/outputs/${activeOutput.id}/scenes/${activePptSlide.index}/versions/${versionId}/select`
          : `/api/v1/kb/outputs/${activeOutput.id}/pages/${activePptSlide.index}/versions/${versionId}/select`;
      const response = await apiFetch(selPath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页已切换到所选历史版本`);
      console.info('[ThinkFlow] selectPptPageVersion:success', {
        outputId: data.output.id,
        pageIndex: activePptSlide.index,
        versionId,
      });
    } catch (error: any) {
      console.error('[ThinkFlow] selectPptPageVersion:error', {
        outputId: activeOutput.id,
        pageIndex: activePptSlide.index,
        versionId,
        error: error?.message || String(error || ''),
      });
      setGlobalError(error?.message || '切换历史版本失败');
      setPptPageStatus(`第 ${activePptSlide.index + 1} 页切换历史版本失败`);
    } finally {
      setPptPageBusyAction('');
    }
  };

  const confirmActivePptPage = async () => {
    if (!activeOutput || !isStoryboardOutputType(activeOutput.target_type) || !activePptSlide) return;
    if (!activePptCurrentPreview && activeOutput.target_type === 'ppt') {
      setGlobalError('当前页还没有生成结果，无法确认。');
      return;
    }
    setPptPageBusyAction('confirm');
    try {
      const confirmPath =
        activeOutput.target_type === 'video'
          ? `/api/v1/kb/outputs/${activeOutput.id}/scenes/${activePptSlide.index}/confirm`
          : `/api/v1/kb/outputs/${activeOutput.id}/pages/${activePptSlide.index}/confirm`;
      const response = await apiFetch(confirmPath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      const outlineLen = (data.output.outline || []).length;
      const reviews = Array.isArray(data.output.page_reviews) ? data.output.page_reviews : [];
      const confirmedCount = reviews.filter((item) => item.confirmed).length;
      const videoAllDone =
        data.output.target_type === 'video' && outlineLen > 0 && confirmedCount >= outlineLen;
      if (data.output.pipeline_stage !== 'generated') {
        setActivePptSlideIndex((previous) => {
          const maxIndex = (data.output.outline || []).length - 1;
          return Math.min(previous + 1, Math.max(maxIndex, 0));
        });
        setPptPageStatus(
          videoAllDone
            ? '当前镜已确认。全部分镜已确认，请点击上方或底部的「合成视频」。'
            : `第 ${activePptSlide.index + 1} 页已确认`,
        );
      } else {
        setPptPageStatus('全部页面已确认，已进入结果页');
      }
    } catch (error: any) {
      setGlobalError(error?.message || '确认当前页失败');
    } finally {
      setPptPageBusyAction('');
    }
  };

  const generateOutputById = async (outputId: string) => {
    if (!outputId) return;
    setGeneratingOutput(true);
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${outputId}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      await parseJson<{ output: ThinkFlowOutput }>(response);
      await refreshOutputs(outputId);
      setOutputContexts((previous) => {
        const current = previous[outputId];
        if (!current) return previous;
        return {
          ...previous,
          [outputId]: {
            ...current,
            isStale: false,
            staleReason: '',
          },
        };
      });
    } catch (error: any) {
      setGlobalError(error?.message || '生成产出失败');
    } finally {
      setGeneratingOutput(false);
    }
  };

  const generateOutput = async () => {
    if (!activeOutputId) return;
    if (isStoryboardOutputType(activeOutput?.target_type) && activePptStage === 'outline_ready') {
      if (activeOutput?.target_type === 'video') {
        await runPaper2videoSubtitle();
        return;
      }
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
      await parseJson(response);
      await refreshFiles();
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
    if (isStoryboardOutputType(activeOutput.target_type)) {
      const deck = activeOutput.target_type;
      const unit = deck === 'video' ? '镜' : '页';
      const pageLabel = deck === 'video' ? '分镜' : '页面';
      const brand = deck === 'video' ? '视频' : 'PPT';
      const previewImages = activePptPreviewImages;
      const selectedSlide = activePptSlide?.slide;
      const selectedIndex = activePptSlide?.index ?? 0;
      const selectedImage = activePptCurrentPreview;
      const canDownloadDeck = activePptStage === 'generated';
      const videoMp4Path = deck === 'video' && canDownloadDeck ? String(result.video_mp4_path || '').trim() : '';
      const showVideoFinalPreview = Boolean(videoMp4Path);
      return (
        <div className="thinkflow-output-preview thinkflow-ppt-viewer">
          {previewImages.length > 0 && selectedSlide ? (
            <>
              <div className="thinkflow-ppt-viewer-stage">
                <div className="thinkflow-ppt-viewer-toolbar">
                  <div className="thinkflow-ppt-viewer-toolbar-copy">
                    {showVideoFinalPreview && videoPreviewTab === 'final' ? (
                      <>
                        <span className="thinkflow-ppt-outline-summary-index">视频成片</span>
                        <strong>预览与下载</strong>
                      </>
                    ) : (
                      <>
                        <span className="thinkflow-ppt-outline-summary-index">第 {selectedSlide.pageNum || selectedIndex + 1} {unit}</span>
                        <strong>{selectedSlide.title || `${pageLabel} ${selectedIndex + 1}`}</strong>
                      </>
                    )}
                  </div>
                  <div className="thinkflow-ppt-viewer-links">
                    {canDownloadDeck && deck === 'ppt' && result.ppt_pdf_path ? (
                      <a href={result.ppt_pdf_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                        <ExternalLink size={14} />
                        打开 PDF
                      </a>
                    ) : null}
                    {canDownloadDeck && deck === 'ppt' && result.ppt_pptx_path ? (
                      <a href={result.ppt_pptx_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                        <Download size={14} />
                        下载 PPTX
                      </a>
                    ) : null}
                    {showVideoFinalPreview ? renderVideoMp4Actions(videoMp4Path, 'sm') : null}
                  </div>
                </div>
                {showVideoFinalPreview ? (
                  <div className="thinkflow-video-preview-tabs" role="tablist" aria-label="视频预览模式">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={videoPreviewTab === 'final'}
                      className={`thinkflow-video-preview-tab ${videoPreviewTab === 'final' ? 'is-active' : ''}`}
                      onClick={() => setVideoPreviewTab('final')}
                    >
                      <Play size={15} />
                      成片预览
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={videoPreviewTab === 'slides'}
                      className={`thinkflow-video-preview-tab ${videoPreviewTab === 'slides' ? 'is-active' : ''}`}
                      onClick={() => setVideoPreviewTab('slides')}
                    >
                      <LayoutGrid size={15} />
                      分镜图
                    </button>
                  </div>
                ) : null}
                <div className={`thinkflow-ppt-viewer-frame ${showVideoFinalPreview && videoPreviewTab === 'final' ? 'has-video' : ''}`}>
                  {showVideoFinalPreview && videoPreviewTab === 'final' ? (
                    renderVideoMp4Player(videoMp4Path)
                  ) : selectedImage ? (
                    <img src={withAssetVersion(selectedImage, `${activeOutput.updated_at}_${selectedIndex}`)} alt={`${brand} 第 ${selectedIndex + 1} ${unit}`} />
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
                              alt={`第 ${selectedIndex + 1} ${unit}历史版本 ${index + 1}`}
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
                        <img src={withAssetVersion(image, `${activeOutput.updated_at}_${index}`)} alt={`${brand} 第 ${index + 1} ${unit}`} />
                      </div>
                      <div className="thinkflow-ppt-filmstrip-meta">
                        <span>第 {index + 1} {unit}</span>
                        {review?.confirmed ? <strong>已确认</strong> : <em>待核对</em>}
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          ) : canDownloadDeck && deck === 'ppt' && result.ppt_pdf_path ? (
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
            <div className="thinkflow-empty">确认逐镜/逐页生成后，这里会显示预览与下载入口。</div>
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
        <div className="thinkflow-output-preview">
          <MermaidPreview mermaidCode={String(result.mermaid_code)} title="导图预览" />
        </div>
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
    if (!activeOutput || isStoryboardOutputType(activeOutput.target_type)) return null;
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

  const renderOutputWorkspaceHeader = () => {
    if (!activeOutput) return null;
    const snapshot = activeOutputContext?.snapshot;
    const isDeckOutput = isStoryboardOutputType(activeOutput.target_type);
    const deckLabel = activeOutput.target_type === 'video' ? '视频' : 'PPT';
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
      activeOutput.title.replace(/\s*·\s*(PPT|视频)$/u, '') ||
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
    const sourceCount = isDeckOutput ? pptSourceNames.length : nonPptSourceNames.length;
    const boundDocCount = isDeckOutput ? pptReferenceDocTitles.length : nonPptBoundDocTitles.length;
    const guidanceCount = isDeckOutput ? pptGuidanceTitles.length : nonPptGuidanceTitles.length;
    const collapsedPills = isDeckOutput
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
                : activeOutput.target_type === 'video'
                  ? '视频会先基于来源生成分镜大纲，确认后再进入逐镜生成。来源仍是主输入，梳理文档和产出指导只作为增强上下文。'
                  : '非 PPT / 视频产出会直接基于确认时的来源快照生成结果。这个结果版本不会在当前会话里动态改来源；需要新范围时请重新生成一版。'}
            </p>
          </div>

          {isDeckOutput ? (
            <>
              <div className="thinkflow-output-source-lock-card">
                <div className="thinkflow-output-source-lock-copy">
                  <strong>本次 {deckLabel} 来源已锁定</strong>
                  <p>当前会话只使用创建时确认的来源、梳理文档和产出指导。后续可重开新一轮 {deckLabel}，但不会在当前会话里动态改来源。</p>
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

  const renderPptStageRail = () => {
    const target = activeOutput?.target_type || 'ppt';
    const steps: Array<{ key: PptPipelineStage; label: string }> = [
      { key: 'outline_ready', label: getStoryboardStageLabel(target, 'outline_ready') },
      { key: 'pages_ready', label: getStoryboardStageLabel(target, 'pages_ready') },
      { key: 'generated', label: getStoryboardStageLabel(target, 'generated') },
    ];
    const currentIndex = steps.findIndex((step) => step.key === activePptStage);
    return (
      <div className="thinkflow-ppt-stage-rail">
        {steps.map((step, index) => (
          <div
            key={step.key}
            className={`thinkflow-ppt-stage-pill ${activePptStage === step.key ? 'is-active' : ''} ${index < currentIndex ? 'is-complete' : ''}`}
          >
            <span>{index + 1}</span>
            <strong>{step.label}</strong>
          </div>
        ))}
      </div>
    );
  };

  const renderPptOutlineWorkspace = () => {
    if (!activeOutput) return null;
    const slides = activeOutput.outline || [];
    const selectedSlide = activePptSlide?.slide || null;
    const selectedSlideIndex = activePptSlide?.index ?? 0;
    const isVideoDeck = activeOutput.target_type === 'video';
    return (
      <>
        {renderPptStageRail()}
        <div className="thinkflow-ppt-stage-header">
          <div className="thinkflow-ppt-stage-copy">
            <h4>{getStoryboardStageLabel(activeOutput.target_type, activePptStage)}</h4>
            <p>
              {isVideoDeck
                ? '先检查分镜标题与要点是否与 PDF 页面对齐，可随时「保存大纲」。准备好后点击「从 PDF 生成逐镜口播稿」，系统会结合每一页生成口播文本并进入「口播稿与分镜确认」阶段。'
                : '这一步先确认整套页级大纲。先看单页预览，再改局部内容；需要整体调结构时，再用 AI 修改。'}
            </p>
          </div>
          <div className="thinkflow-ppt-stage-actions">
            <button type="button" className="thinkflow-doc-action-btn" onClick={() => setRightMode('doc')}>
              返回文档
            </button>
            <button type="button" className="thinkflow-doc-action-btn is-active" onClick={() => void saveOutline()} disabled={outlineSaving}>
              {outlineSaving ? '保存中...' : '保存大纲'}
            </button>
            <button
              type="button"
              className="thinkflow-generate-btn"
              onClick={() => void (isVideoDeck ? runPaper2videoSubtitle() : confirmPptOutline())}
              disabled={outlineSaving || generatingOutput}
            >
              {generatingOutput
                ? isVideoDeck
                  ? '口播稿生成中...'
                  : '处理中...'
                : isVideoDeck
                  ? '从 PDF 生成逐镜口播稿'
                  : '确认大纲，进入逐页生成'}
            </button>
          </div>
        </div>
        <div className="thinkflow-ppt-refine-panel">
          <textarea
            className="thinkflow-outline-textarea"
            value={pptOutlineFeedback}
            onChange={(event) => setPptOutlineFeedback(event.target.value)}
            placeholder="例如：把前两页更聚焦问题背景，弱化实验细节，把结论页提前一页。"
            rows={3}
          />
          <div className="thinkflow-ppt-refine-actions">
            <button type="button" className="thinkflow-doc-action-btn" onClick={() => setPptOutlineFeedback('')}>
              清空
            </button>
            <button type="button" className="thinkflow-doc-action-btn is-active" onClick={() => void refinePptOutline()} disabled={pptRefiningOutline}>
              {pptRefiningOutline ? 'AI 调整中...' : '提示词 AI 修改'}
            </button>
          </div>
        </div>
        <div className="thinkflow-ppt-outline-canvas">
          {selectedSlide ? (
            <div className="thinkflow-ppt-focus-shell">
              <article className="thinkflow-ppt-focus-preview">
                <div className="thinkflow-ppt-focus-preview-top">
                  <span className="thinkflow-ppt-outline-summary-index">第 {selectedSlide.pageNum || selectedSlideIndex + 1} 页</span>
                  <span className="thinkflow-ppt-focus-preview-label">当前页预览</span>
                </div>
                <div className="thinkflow-ppt-focus-slide">
                  <div className="thinkflow-ppt-focus-slide-head">
                    <h4>{selectedSlide.title || `页面 ${selectedSlideIndex + 1}`}</h4>
                    <p>{selectedSlide.layout_description || '这页还没有填写布局说明。'}</p>
                  </div>
                  {(selectedSlide.key_points || selectedSlide.bullets || []).length > 0 ? (
                    <ul className="thinkflow-ppt-focus-points">
                      {(selectedSlide.key_points || selectedSlide.bullets || []).map((point, pointIndex) => (
                        <li key={`${selectedSlide.id || selectedSlideIndex}_${pointIndex}`}>{point}</li>
                      ))}
                    </ul>
                  ) : (
                    <div className="thinkflow-ppt-outline-card-empty">这页还没有要点。</div>
                  )}
                  {selectedSlide.asset_ref ? <div className="thinkflow-ppt-outline-card-asset">素材：{selectedSlide.asset_ref}</div> : null}
                </div>
              </article>
              <div className="thinkflow-ppt-slide-editor">
                <div className="thinkflow-ppt-slide-editor-head">
                  <div>
                    <span className="thinkflow-output-workspace-kicker">单页编辑</span>
                    <h4>正在编辑第 {selectedSlide.pageNum || selectedSlideIndex + 1} 页</h4>
                  </div>
                </div>
                <input
                  className="thinkflow-outline-input"
                  value={selectedSlide.title || ''}
                  onChange={(event) => updateOutlineSection(selectedSlideIndex, { title: event.target.value })}
                  placeholder="页面标题"
                />
                <textarea
                  className="thinkflow-outline-textarea"
                  value={selectedSlide.layout_description || ''}
                  onChange={(event) =>
                    updateOutlineSection(selectedSlideIndex, {
                      layout_description: event.target.value,
                      summary: event.target.value,
                    })
                  }
                  placeholder="这一页的布局描述 / 页面角色"
                  rows={3}
                />
                <textarea
                  className="thinkflow-outline-textarea"
                  value={(selectedSlide.key_points || selectedSlide.bullets || []).join('\n')}
                  onChange={(event) =>
                    updateOutlineSection(selectedSlideIndex, {
                      key_points: event.target.value.split('\n').map((text) => text.trim()).filter(Boolean),
                      bullets: event.target.value.split('\n').map((text) => text.trim()).filter(Boolean),
                    })
                  }
                  placeholder="每行一个要点"
                  rows={7}
                />
                <input
                  className="thinkflow-outline-input"
                  value={selectedSlide.asset_ref || ''}
                  onChange={(event) => updateOutlineSection(selectedSlideIndex, { asset_ref: event.target.value || null })}
                  placeholder="可选：来源素材引用（asset_ref）"
                />
              </div>
            </div>
          ) : null}
          <div className="thinkflow-ppt-outline-strip">
            {slides.map((item, index) => (
              <button
                key={item.id || `${activeOutput.id}_${index}`}
                type="button"
                className={`thinkflow-ppt-outline-card ${selectedSlideIndex === index ? 'is-active' : ''}`}
                onClick={() => setActivePptSlideIndex(index)}
              >
                <div className="thinkflow-ppt-outline-card-top">
                  <span className="thinkflow-ppt-outline-summary-index">第 {item.pageNum || index + 1} 页</span>
                  <span className="thinkflow-ppt-outline-card-cta">{selectedSlideIndex === index ? '编辑中' : '查看'}</span>
                </div>
                <h4>{item.title || `页面 ${index + 1}`}</h4>
                {item.layout_description ? <p>{item.layout_description}</p> : null}
                {(item.key_points || item.bullets || []).length > 0 ? (
                  <ul>
                    {(item.key_points || item.bullets || []).slice(0, 3).map((point, pointIndex) => (
                      <li key={`${item.id || index}_${pointIndex}`}>{point}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="thinkflow-ppt-outline-card-empty">这页还没有要点。</div>
                )}
              </button>
            ))}
            {isVideoDeck ? null : (
              <button type="button" className="thinkflow-outline-add-btn thinkflow-ppt-outline-add-card" onClick={addPptOutlineSection}>
                + 添加页面
              </button>
            )}
          </div>
        </div>
        <div className="thinkflow-outline-footer">
          <div className="thinkflow-outline-actions">
            <button type="button" className="thinkflow-doc-action-btn" onClick={() => setRightMode('doc')}>
              返回文档
            </button>
            <button type="button" className="thinkflow-doc-action-btn is-active" onClick={() => void saveOutline()} disabled={outlineSaving}>
              {outlineSaving ? '保存中...' : '保存大纲'}
            </button>
            <button
              type="button"
              className="thinkflow-generate-btn"
              onClick={() => void (isVideoDeck ? runPaper2videoSubtitle() : confirmPptOutline())}
              disabled={outlineSaving || generatingOutput}
            >
              {generatingOutput
                ? isVideoDeck
                  ? '口播稿生成中...'
                  : '处理中...'
                : isVideoDeck
                  ? '从 PDF 生成逐镜口播稿'
                  : '确认大纲，进入逐页生成'}
            </button>
          </div>
        </div>
      </>
    );
  };

  const renderPptLockedOutlinePreview = () => {
    if (!activeOutput || !pptOutlineReadonlyOpen) return null;
    const slides = activeOutput.outline || [];
    return (
      <div className="thinkflow-ppt-locked-outline">
        <div className="thinkflow-ppt-locked-outline-head">
          <div>
            <span className="thinkflow-output-workspace-kicker">已确认大纲</span>
            <h4>当前大纲只读</h4>
          </div>
          <button type="button" className="thinkflow-doc-action-btn" onClick={() => setPptOutlineReadonlyOpen(false)}>
            收起
          </button>
        </div>
        <div className="thinkflow-ppt-outline-summary-list">
          {slides.map((item, index) => (
            <article key={item.id || `${activeOutput.id}_${index}`} className="thinkflow-ppt-outline-summary-card">
              <span className="thinkflow-ppt-outline-summary-index">第 {item.pageNum || index + 1} 页</span>
              <h4>{item.title || `页面 ${index + 1}`}</h4>
              {item.layout_description ? <p>{item.layout_description}</p> : null}
              {(item.key_points || item.bullets || []).length > 0 ? (
                <ul>
                  {(item.key_points || item.bullets || []).slice(0, 4).map((point, pointIndex) => (
                    <li key={`${item.id || index}_${pointIndex}`}>{point}</li>
                  ))}
                </ul>
              ) : (
                <div className="thinkflow-ppt-outline-card-empty">这页还没有要点。</div>
              )}
            </article>
          ))}
        </div>
      </div>
    );
  };

  const renderPptGenerationReview = () => {
    if (!activeOutput) return null;
    const hasDraftPages = activePptPreviewImages.length > 0;
    const totalSlides = (activeOutput.outline || []).length || activeOutput.page_count || 0;
    const currentPageNumber = activePptSlide?.slide.pageNum || (activePptSlide?.index ?? 0) + 1;
    const isVideoDeck = activeOutput.target_type === 'video';
    const allVideoScenesConfirmed = isVideoDeck && totalSlides > 0 && activePptConfirmedCount >= totalSlides;
    return (
      <>
        {renderPptStageRail()}
        <div className="thinkflow-ppt-stage-header">
          <div className="thinkflow-ppt-stage-copy">
            <h4>{getStoryboardStageLabel(activeOutput.target_type, activePptStage)}</h4>
            <p>
              {isVideoDeck
                ? '逐镜查看 PDF 页预览与口播稿，可直接编辑文本并「保存讲稿」。每一镜确认通过后，再点击「合成视频」进入 refine、TTS 与成片流程。'
                : '大纲已经确认完成。先生成每页结果，再逐页核对、改单页并确认通过；这一步不再支持改大纲。'}
            </p>
          </div>
          <div className="thinkflow-ppt-stage-actions">
            <button
              type="button"
              className="thinkflow-doc-action-btn"
              onClick={() => setPptOutlineReadonlyOpen((previous) => !previous)}
            >
              {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
            </button>
            {isVideoDeck ? (
              <>
                <button
                  type="button"
                  className="thinkflow-doc-action-btn is-active"
                  onClick={() => void saveOutline()}
                  disabled={outlineSaving || generatingOutput}
                >
                  {outlineSaving ? '保存中...' : '保存讲稿'}
                </button>
                <button
                  type="button"
                  className="thinkflow-generate-btn"
                  onClick={() => void runPaper2videoContinue()}
                  disabled={generatingOutput || !allVideoScenesConfirmed}
                >
                  {generatingOutput ? '成片生成中...' : '合成视频'}
                </button>
              </>
            ) : (
              <button type="button" className="thinkflow-generate-btn" onClick={() => void generateOutputById(activeOutput.id)} disabled={generatingOutput}>
                {generatingOutput ? '生成页面结果中...' : hasDraftPages ? '重新生成每页结果' : '生成每页结果'}
              </button>
            )}
          </div>
        </div>
        {renderPptLockedOutlinePreview()}
        <div className="thinkflow-ppt-generation-review">
          <div className="thinkflow-ppt-generation-card">
            <span className="thinkflow-ppt-generation-label">{isVideoDeck ? '分镜数量' : '页面规模'}</span>
            <strong>{totalSlides} 页</strong>
          </div>
          <div className="thinkflow-ppt-generation-card">
            <span className="thinkflow-ppt-generation-label">确认进度</span>
            <strong>
              {activePptConfirmedCount} / {totalSlides}
            </strong>
          </div>
          <div className="thinkflow-ppt-generation-toggle is-readonly">
            <span>{activeOutput.enable_images !== false ? '已开启' : '已关闭'}</span>
            <strong>来源素材与自动插图 / 生图</strong>
          </div>
          <div className="thinkflow-ppt-generation-note">
            {isVideoDeck
              ? '口播稿通过「保存讲稿」写入服务端。全部分镜确认后，「合成视频」才会调用 continue-after-edit（refine + TTS + 成片）。'
              : '该配置已在确认大纲时锁定。若需修改，请新建一份新的 PPT 产出。'}
          </div>
          {pptPageStatus ? <div className="thinkflow-ppt-page-toast">{pptPageStatus}</div> : null}
        </div>
        {hasDraftPages ? (
          <div className="thinkflow-ppt-review-shell">
            <div className="thinkflow-ppt-review-main">
              {renderOutputPreview()}
              <div className="thinkflow-ppt-review-actions">
                {isVideoDeck ? (
                  <>
                    <div className="thinkflow-ppt-review-copy">
                      <span className="thinkflow-output-workspace-kicker">口播稿</span>
                      <h4>第 {currentPageNumber} 镜</h4>
                      <p>可直接编辑下方口播稿，并通过上方或底部的「保存讲稿」写入服务端；确认本镜内容后点击「确认当前镜」。</p>
                    </div>
                    <textarea
                      className="thinkflow-outline-textarea"
                      value={String(activePptSlide?.slide?.script_text ?? '')}
                      onChange={(event) => {
                        if (!activePptSlide) return;
                        updateOutlineSection(activePptSlide.index, { script_text: event.target.value });
                      }}
                      placeholder="本镜口播内容（可在 subtitle 结果基础上润色）"
                      rows={10}
                    />
                  </>
                ) : (
                  <>
                    <div className="thinkflow-ppt-review-copy">
                      <span className="thinkflow-output-workspace-kicker">单页修改</span>
                      <h4>第 {currentPageNumber} 页核对与改单页</h4>
                      <p>这一页如果不对，就直接补一句修改要求，让模型只重做当前页。重做完成后会进入当前页历史版本，你可以切回旧版本再确认。</p>
                    </div>
                    <textarea
                      className="thinkflow-outline-textarea"
                      value={pptPagePrompt}
                      onChange={(event) => setPptPagePrompt(event.target.value)}
                      placeholder="例如：这页不要讲方法细节，改成问题背景 + 核心结论；配图换成更简洁的结构图。"
                      rows={3}
                    />
                  </>
                )}
                <div className="thinkflow-ppt-review-btn-row">
                  <button
                    type="button"
                    className="thinkflow-doc-action-btn"
                    onClick={() => setActivePptSlideIndex((previous) => Math.max(previous - 1, 0))}
                    disabled={(activePptSlide?.index ?? 0) === 0 || pptPageBusyAction !== '' || generatingOutput}
                  >
                    <ChevronLeft size={14} />
                    上一页
                  </button>
                  <button
                    type="button"
                    className="thinkflow-doc-action-btn"
                    onClick={() =>
                      setActivePptSlideIndex((previous) =>
                        Math.min(previous + 1, Math.max((activeOutput.outline || []).length - 1, 0)),
                      )
                    }
                    disabled={
                      (activePptSlide?.index ?? 0) >= Math.max((activeOutput.outline || []).length - 1, 0) ||
                      pptPageBusyAction !== '' ||
                      generatingOutput
                    }
                  >
                    下一页
                    <ArrowRight size={14} />
                  </button>
                  {isVideoDeck ? null : (
                    <button
                      type="button"
                      className="thinkflow-doc-action-btn is-active"
                      onClick={() => void regenerateActivePptPage()}
                      disabled={!pptPagePrompt.trim() || pptPageBusyAction !== '' || generatingOutput}
                    >
                      <RefreshCw size={14} className={pptPageBusyAction === 'regenerate' ? 'is-spinning' : ''} />
                      {pptPageBusyAction === 'regenerate' ? '当前页重生成中...' : '按提示重做当前页'}
                    </button>
                  )}
                  <button
                    type="button"
                    className="thinkflow-generate-btn"
                    onClick={() => void confirmActivePptPage()}
                    disabled={
                      (!activePptCurrentPreview && activeOutput.target_type === 'ppt') ||
                      pptPageBusyAction !== '' ||
                      generatingOutput
                    }
                  >
                    <CheckCircle2 size={14} />
                    {pptPageBusyAction === 'confirm'
                      ? '确认中...'
                      : (activePptSlide?.index ?? 0) >= Math.max((activeOutput.outline || []).length - 1, 0)
                        ? isVideoDeck
                          ? '确认当前镜并完成'
                          : '确认当前页并完成'
                        : isVideoDeck
                          ? '确认当前镜并继续'
                          : '确认当前页并继续'}
                  </button>
                </div>
                <div className="thinkflow-ppt-inline-feedback">
                  {!isVideoDeck && pptPageBusyAction === 'regenerate' ? '正在调用后端重做当前页，请稍候...' : null}
                  {!isVideoDeck && pptPageBusyAction === 'select_version' ? '正在切换历史版本，请稍候...' : null}
                  {!isVideoDeck && !pptPageBusyAction && activePptPageVersions.length > 0
                    ? `当前页已有 ${activePptPageVersions.length} 个历史版本，可在预览图下方直接切换。`
                    : null}
                </div>
                {activePptCurrentReview?.confirmed ? (
                  <div className="thinkflow-ppt-page-toast is-confirmed">
                    {isVideoDeck ? '当前镜已确认，可继续浏览其它分镜。' : '当前页已经确认通过，你也可以继续重做。'}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : (
          <div className="thinkflow-ppt-draft-empty">
            <div className="thinkflow-empty">
              {isVideoDeck
                ? '还没有分镜预览图。请返回「分镜与来源」步骤并成功运行「从 PDF 生成逐镜口播稿」，或检查后端是否已将 slide 预览写入 video_pipeline。'
                : '这一步还没有页面草稿。先生成一版整套页图，再逐页查看、改单页、确认通过。'}
            </div>
            <div className="thinkflow-ppt-outline-summary-list">
              {(activeOutput.outline || []).map((item, index) => (
                <article key={item.id || `${activeOutput.id}_${index}`} className="thinkflow-ppt-outline-summary-card">
                  <span className="thinkflow-ppt-outline-summary-index">第 {index + 1} 页</span>
                  <h4>{item.title || `页面 ${index + 1}`}</h4>
                  {item.layout_description ? <p>{item.layout_description}</p> : null}
                  {(item.key_points || item.bullets || []).length > 0 ? (
                    <ul>
                      {(item.key_points || item.bullets || []).slice(0, 4).map((point, pointIndex) => (
                        <li key={`${item.id || index}_${pointIndex}`}>{point}</li>
                      ))}
                    </ul>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        )}
        <div className="thinkflow-outline-footer">
          <div className="thinkflow-outline-actions">
            {isVideoDeck ? (
              <>
                <button
                  type="button"
                  className="thinkflow-doc-action-btn"
                  onClick={() => setPptOutlineReadonlyOpen((previous) => !previous)}
                >
                  {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
                </button>
                <button
                  type="button"
                  className="thinkflow-doc-action-btn is-active"
                  onClick={() => void saveOutline()}
                  disabled={outlineSaving || generatingOutput}
                >
                  {outlineSaving ? '保存中...' : '保存讲稿'}
                </button>
                <button
                  type="button"
                  className="thinkflow-generate-btn"
                  onClick={() => void runPaper2videoContinue()}
                  disabled={generatingOutput || !allVideoScenesConfirmed}
                >
                  {generatingOutput ? '成片生成中...' : '合成视频'}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="thinkflow-doc-action-btn"
                  onClick={() => setPptOutlineReadonlyOpen((previous) => !previous)}
                >
                  {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
                </button>
                <button type="button" className="thinkflow-generate-btn" onClick={() => void generateOutputById(activeOutput.id)} disabled={generatingOutput}>
                  {generatingOutput ? '生成页面结果中...' : hasDraftPages ? '重新生成每页结果' : '生成每页结果'}
                </button>
              </>
            )}
          </div>
        </div>
      </>
    );
  };

  const renderPptGeneratedResult = () => {
    if (!activeOutput) return null;
    return (
      <>
        {renderPptStageRail()}
        <div className="thinkflow-ppt-stage-header">
          <div className="thinkflow-ppt-stage-copy">
            <h4>{getStoryboardStageLabel(activeOutput.target_type, activePptStage)}</h4>
            <p>
              {activeOutput.target_type === 'video'
                ? '成片已就绪。可在此预览分镜、播放或下载 MP4，也可将来源回流到素材。若需重跑，请新建一条视频产出。'
                : '全部页面都已确认通过，当前 PPT 产出状态已经确定。这里主要用于预览、下载和回流来源。'}
            </p>
          </div>
          <div className="thinkflow-ppt-stage-actions">
            <button
              type="button"
              className="thinkflow-doc-action-btn"
              onClick={() => setPptOutlineReadonlyOpen((previous) => !previous)}
            >
              {pptOutlineReadonlyOpen ? '收起已确认大纲' : '查看已确认大纲'}
            </button>
            <button type="button" className="thinkflow-doc-action-btn" onClick={() => void importOutputToSource()}>
              回流来源
            </button>
          </div>
        </div>
        {renderPptLockedOutlinePreview()}
        <div className="thinkflow-outline-footer">
          <div className="thinkflow-outline-preview">{renderOutputPreview()}</div>
          {activeOutput.result?.download_url ||
          activeOutput.result?.ppt_pdf_path ||
          activeOutput.result?.ppt_pptx_path ||
          activeOutput.result?.video_mp4_path ? (
            <div className="thinkflow-ppt-download-row">
              {activeOutput.target_type === 'video' && activeOutput.result?.video_mp4_path ? (
                <div className="thinkflow-video-result-bar">
                  <div className="thinkflow-video-result-bar-copy">
                    <Video size={20} />
                    <div>
                      <strong>视频成片</strong>
                      <span>可在上方主区域切换「成片预览 / 分镜图」</span>
                    </div>
                  </div>
                  {renderVideoMp4Actions(activeOutput.result.video_mp4_path, 'lg')}
                </div>
              ) : null}
              {activeOutput.result?.ppt_pdf_path ? (
                <a href={activeOutput.result.ppt_pdf_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                  <Download size={14} />
                  打开 PDF
                </a>
              ) : null}
              {activeOutput.result?.ppt_pptx_path ? (
                <a href={activeOutput.result.ppt_pptx_path} target="_blank" rel="noreferrer" className="thinkflow-download-link">
                  <Download size={14} />
                  下载 PPTX
                </a>
              ) : null}
            </div>
          ) : null}
        </div>
      </>
    );
  };

  const renderPptWorkspace = () => {
    if (!activeOutput) return null;
    if (activeOutput.target_type === 'video' && activePptStage === 'pending') {
      return (
        <>
          {renderPptStageRail()}
          <div className="thinkflow-ppt-stage-header">
            <div className="thinkflow-ppt-stage-copy">
              <h4>{getStoryboardStageLabel('video', 'pending')}</h4>
              <p>
                该产出仍处于旧版「排队」状态。可点击下方按钮尝试从 PDF 生成逐镜口播稿；若仍失败，请新建一条视频产出，或请管理员检查 paper2video 工作流与 LLM 配置。
              </p>
            </div>
          </div>
          <div className="thinkflow-outline-footer">
            <div className="thinkflow-outline-preview">{renderOutputPreview()}</div>
            <div className="thinkflow-outline-actions">
              <button type="button" className="thinkflow-generate-btn" onClick={() => void runPaper2videoSubtitle()} disabled={generatingOutput}>
                {generatingOutput ? '口播稿生成中...' : '从 PDF 生成逐镜口播稿'}
              </button>
            </div>
          </div>
        </>
      );
    }
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
        title: '摘要区说明',
        description: '这里用来沉淀你已经确认的理解、结论和待追问点，适合把单条回答、本轮问答或多轮讨论整理成 AI 笔记。',
        capabilities: '可继续编辑、补充和改名，适合作为阅读记录与后续追问线索。',
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
    summaryItems: summaryItems.map((item) => ({ id: item.id, title: item.title })),
    activeSummaryId,
    activeSummary: activeSummary ? { id: activeSummary.id, title: activeSummary.title } : null,
    summaryTitle,
    summaryContent,
    summaryEditMode,
    workspaceSaving,
    panelGuide: renderPanelGuide('summary'),
    onSelectSummary: async (id: string) => {
      setRightMode('summary');
      await loadWorkspaceItemDetail(id);
    },
    onCreateSummary: () => createWorkspaceItem('summary'),
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
    activeDocument: activeDocument ? { id: activeDocument.id, title: activeDocument.title } : null,
    documentTitle,
    documentContent,
    editMode,
    showVersionPanel,
    versions,
    panelGuide: renderPanelGuide('doc'),
    documentSections,
    renderDocumentSection,
    docBodyRef,
    guidanceItems: guidanceItems.map((item) => ({ id: item.id, title: item.title })),
    selectedGuidanceIds,
    outputButtons,
    generatingOutline,
    documentSaving,
    onSelectDocument: async (id: string) => {
      setActiveDocumentId(id);
      setRightMode('doc');
      await loadDocumentDetail(id);
    },
    onCreateDocument: createDocument,
    onToggleDocumentEdit: () => setEditMode((previous) => !previous),
    onToggleVersionPanel: () => setShowVersionPanel((previous) => !previous),
    onDeleteDocument: deleteDocument,
    onDocumentTitleChange: setDocumentTitle,
    onDocumentContentChange: setDocumentContent,
    onRestoreVersion: restoreVersion,
    onToggleGuidanceSelection: toggleGuidanceSelection,
    onOutputAction: (type: string) => {
      if (type === 'ppt') {
        return openPptSourceLockIntent('ppt');
      }
      if (type === 'video') {
        return openPptSourceLockIntent('video');
      }
      return openDirectOutputIntent(type as Exclude<OutputType, 'ppt' | 'video'>);
    },
    onSaveDocument: saveDocument,
  };

  const outputPanelProps = {
    activeOutput: activeOutput ? { target_type: activeOutput.target_type } : null,
    generatingOutline,
    generatingOutlineLabel: outputButtons.find((item) => item.type === generatingOutline)?.label || '产出',
    outputWorkspaceHeader: renderOutputWorkspaceHeader(),
    storyboardWorkspace: renderPptWorkspace(),
    directOutputWorkspace: renderDirectOutputWorkspace(),
    isOutputHeaderCollapsed,
    onOutputWorkspaceScroll: handleOutputWorkspaceScroll,
  };

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
          onLeftTabChange={setLeftTab}
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
          conversationList={[]}
          activeConversationId={conversationId}
          onSelectConversation={setConversationId}
          onNewConversation={handleNewConversation}
        />

        <ThinkFlowCenterPanel
          activeOutput={activeOutput}
          boundDocIds={boundDocIds}
          chatInput={chatInput}
          chatLoading={chatLoading}
          chatMessages={chatMessages}
          chatScrollRef={chatScrollRef}
          documents={documents}
          focusedMessageId={focusedMessageId}
          handleChatSelectionMouseUp={handleChatSelectionMouseUp}
          handleSelectionCopy={handleSelectionCopy}
          handleSelectionPush={handleSelectionPush}
          handleSendMessage={handleSendMessage}
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
          <div
            className={`thinkflow-output-context-modal thinkflow-output-lock-modal${
              pptSourceLockIntent.storyboardTarget === 'video' ? ' thinkflow-p2v-lock-modal' : ''
            }`}
          >
            <div className="thinkflow-output-context-modal-header">
              <div>
                <h3>确认本次 {pptSourceLockIntent.storyboardTarget === 'video' ? '视频' : 'PPT'} 来源</h3>
                <p>
                  这一步会锁定本轮 {pptSourceLockIntent.storyboardTarget === 'video' ? '视频' : 'PPT'}{' '}
                  的来源范围。确认后，当前会话内不再提供“更新来源”的入口。
                </p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setPptSourceLockIntent(null)}>
                关闭
              </button>
            </div>

            <div className="thinkflow-output-context-modal-body">
              {pptSourceLockIntent.storyboardTarget === 'video' ? (
                <div className="thinkflow-p2v-prerequisite-banner" role="note">
                  <p>
                    当前生成视频预期的输入是 <strong>.pptx</strong> 文件，或{' '}
                    <strong>PDF 格式的 PPT 内容</strong>（每页为幻灯片页面，而非整篇论文正文）。
                    若你目前只有完整文档/论文类素材，请先走「生成 PPT」流程，再基于 PPT 生成视频。
                  </p>
                  <button
                    type="button"
                    className="thinkflow-p2v-prerequisite-btn"
                    disabled={pptSourceLockIntent.loading || pptSourceLockIntent.submitting}
                    onClick={switchVideoLockToPptFlow}
                  >
                    生成 PPT
                  </button>
                </div>
              ) : null}
              {pptSourceLockIntent.loading ? (
                <div className="thinkflow-empty">
                  正在整理这次 {pptSourceLockIntent.storyboardTarget === 'video' ? '视频' : 'PPT'} 的来源快照...
                </div>
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

                  {pptSourceLockIntent.storyboardTarget === 'video' && pptSourceLockIntent.videoConfig ? (
                    <section className="thinkflow-output-context-group thinkflow-p2v-config-section">
                      <div className="thinkflow-output-context-group-title">视频配置</div>
                      <p className="thinkflow-p2v-config-note">
                        启用数字人约增加 5–10 分钟。
                      </p>

                      <label className="thinkflow-p2v-field">
                        <span>语言</span>
                        <select
                          value={pptSourceLockIntent.videoConfig.language}
                          onChange={(event) =>
                            setPptSourceLockIntent((current) =>
                              current && current.videoConfig
                                ? {
                                    ...current,
                                    videoConfig: { ...current.videoConfig, language: event.target.value },
                                  }
                                : current,
                            )
                          }
                        >
                          {(pptSourceLockIntent.paper2videoOptions?.languages || [
                            { id: 'zh', label: '中文' },
                            { id: 'en', label: 'English' },
                          ]).map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      <div className="thinkflow-p2v-field">
                        <span>数字人</span>
                        <div className="thinkflow-p2v-segmented">
                          {[
                            { id: 'none', label: '不需要数字人' },
                            { id: 'system', label: '系统数字人' },
                            { id: 'custom', label: '上传自己的' },
                          ].map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              className={
                                pptSourceLockIntent.videoConfig?.avatar_mode === item.id ? 'active' : ''
                              }
                              onClick={() =>
                                setPptSourceLockIntent((current) =>
                                  current && current.videoConfig
                                    ? {
                                        ...current,
                                        videoConfig: {
                                          ...current.videoConfig,
                                          avatar_mode: item.id as Paper2VideoConfig['avatar_mode'],
                                        },
                                      }
                                    : current,
                                )
                              }
                            >
                              {item.label}
                            </button>
                          ))}
                        </div>
                      </div>

                      {pptSourceLockIntent.videoConfig.avatar_mode === 'system' ? (
                        <div className="thinkflow-p2v-avatar-grid">
                          {(pptSourceLockIntent.paper2videoOptions?.avatars || []).map((avatar) => (
                            <button
                              key={avatar.id}
                              type="button"
                              className={`thinkflow-p2v-avatar-card${
                                pptSourceLockIntent.videoConfig?.avatar_id === avatar.id ? ' selected' : ''
                              }`}
                              onClick={() =>
                                setPptSourceLockIntent((current) =>
                                  current && current.videoConfig
                                    ? {
                                        ...current,
                                        videoConfig: { ...current.videoConfig, avatar_id: avatar.id },
                                      }
                                    : current,
                                )
                              }
                            >
                              <img
                                src={paper2videoPresetPreviewUrls[`avatar:${avatar.id}`] || ''}
                                alt={avatar.label}
                              />
                              <span>{avatar.label}</span>
                            </button>
                          ))}
                        </div>
                      ) : null}

                      {pptSourceLockIntent.videoConfig.avatar_mode === 'custom' ? (
                        <label className="thinkflow-p2v-upload-drop">
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            onChange={(event) => {
                              const file = event.target.files?.[0] || null;
                              setPptSourceLockIntent((current) => {
                                if (!current) return current;
                                if (current.customAvatarPreviewUrl) {
                                  URL.revokeObjectURL(current.customAvatarPreviewUrl);
                                }
                                return {
                                  ...current,
                                  customAvatarFile: file,
                                  customAvatarPreviewUrl: file ? URL.createObjectURL(file) : '',
                                  videoConfig: current.videoConfig
                                    ? { ...current.videoConfig, avatar_upload_token: '' }
                                    : current.videoConfig,
                                };
                              });
                            }}
                          />
                          <span>选择 JPG / PNG 人脸图片</span>
                          {pptSourceLockIntent.customAvatarPreviewUrl ? (
                            <img src={pptSourceLockIntent.customAvatarPreviewUrl} alt="自定义数字人预览" />
                          ) : null}
                        </label>
                      ) : null}

                    </section>
                  ) : null}
                </>
              )}
            </div>

            <div className="thinkflow-output-context-modal-footer">
              <span className="thinkflow-output-context-hint">
                {pptSourceLockIntent.loading
                  ? '正在整理来源，请稍候。'
                  : pptSourceLockIntent.errorMessage
                    ? '来源解析失败，请关闭后重试。'
                    : `当前正在编辑的梳理文档也会在这里一并锁定。确认后将直接进入 ${
                        pptSourceLockIntent.storyboardTarget === 'video' ? '视频分镜大纲' : 'PPT 大纲'
                      } 阶段。`}
              </span>
              <div className="thinkflow-output-context-actions">
                <button type="button" className="thinkflow-doc-action-btn" onClick={() => setPptSourceLockIntent(null)}>
                  取消
                </button>
                <button
                  type="button"
                  className="thinkflow-generate-btn"
                  onClick={() => void confirmPptSourceLockIntent()}
                  disabled={
                    pptSourceLockIntent.loading ||
                    pptSourceLockIntent.submitting ||
                    Boolean(pptSourceLockIntent.errorMessage)
                  }
                >
                  {pptSourceLockIntent.loading
                    ? '整理来源中...'
                    : pptSourceLockIntent.submitting
                      ? '正在提交...'
                      : '确认并生成大纲'}
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
                      {buildPptReferenceDocumentTitles(
                        directOutputIntent.outputDocumentTitle,
                        directOutputIntent.boundDocumentTitles,
                      ).length > 0 ? (
                        buildPptReferenceDocumentTitles(
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
                <h3>沉淀到工作区</h3>
                <p>把当前对话整理到右侧工作区，后续可以继续复用。</p>
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
                <div className="thinkflow-push-label">沉淀目标</div>
                <div className="thinkflow-push-destinations">
                  {[
                    { value: 'summary', label: '摘要', desc: '沉淀关键理解与结论' },
                    { value: 'document', label: '文档', desc: '整理成持续演进的主文档' },
                    { value: 'guidance', label: '产出指导', desc: '作为后续输出的重要约束和方向' },
                  ].map((item) => (
                    <label
                      key={item.value}
                      className={`thinkflow-push-mode ${pushPopover.destinationType === item.value ? 'is-active' : ''}`}
                    >
                      <input
                        type="radio"
                        checked={pushPopover.destinationType === item.value}
                        disabled={pushSubmitting}
                        onChange={() =>
                          setPushPopover((previous) => ({
                            ...previous,
                            destinationType: item.value as PushDestinationType,
                            targetItemId:
                              item.value === 'summary'
                                ? activeSummaryId || summaryItems[0]?.id || '__new__'
                                : item.value === 'guidance'
                                  ? activeGuidanceId || guidanceItems[0]?.id || '__new__'
                                  : previous.targetItemId,
                          }))
                        }
                      />
                      <div>
                        <div className="thinkflow-push-mode-title">{item.label}</div>
                        <div className="thinkflow-push-mode-desc">{item.desc}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {pushPopover.destinationType === 'document' ? (
                <div className="thinkflow-push-field">
                  <div className="thinkflow-push-label">目标文档</div>
                  <select
                    className="thinkflow-push-select"
                    value={pushPopover.targetDocId}
                    disabled={pushSubmitting}
                    onChange={(event) => setPushPopover((previous) => ({ ...previous, targetDocId: event.target.value }))}
                  >
                    {documents.map((doc) => (
                      <option key={doc.id} value={doc.id}>
                        {doc.title}
                      </option>
                    ))}
                    <option value="__new__">+ 新建文档</option>
                  </select>
                </div>
              ) : (
                <div className="thinkflow-push-field">
                  <div className="thinkflow-push-label">目标{pushPopover.destinationType === 'summary' ? '摘要' : '产出指导'}</div>
                  <select
                    className="thinkflow-push-select"
                    value={pushPopover.targetItemId || '__new__'}
                    disabled={pushSubmitting}
                    onChange={(event) => setPushPopover((previous) => ({ ...previous, targetItemId: event.target.value }))}
                  >
                    {(pushPopover.destinationType === 'summary' ? summaryItems : guidanceItems).map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.title}
                      </option>
                    ))}
                    <option value="__new__">+ 新建{pushPopover.destinationType === 'summary' ? '摘要' : '产出指导'}</option>
                  </select>
                </div>
              )}

              {(pushPopover.destinationType === 'document' ? pushPopover.targetDocId === '__new__' : (pushPopover.targetItemId || '__new__') === '__new__') ? (
                <div className="thinkflow-push-field">
                  <div className="thinkflow-push-label">命名方式</div>
                  <div className="thinkflow-push-title-modes">
                    <label className={`thinkflow-push-mode ${pushPopover.titleMode === 'ai' ? 'is-active' : ''}`}>
                      <input
                        type="radio"
                        checked={pushPopover.titleMode === 'ai'}
                        disabled={pushSubmitting}
                        onChange={() => setPushPopover((previous) => ({ ...previous, titleMode: 'ai', newTitle: '' }))}
                      />
                      <div>
                        <div className="thinkflow-push-mode-title">AI 命名</div>
                        <div className="thinkflow-push-mode-desc">自动生成一个简洁可读的标题</div>
                      </div>
                    </label>
                    <label className={`thinkflow-push-mode ${pushPopover.titleMode === 'manual' ? 'is-active' : ''}`}>
                      <input
                        type="radio"
                        checked={pushPopover.titleMode === 'manual'}
                        disabled={pushSubmitting}
                        onChange={() =>
                          setPushPopover((previous) => ({
                            ...previous,
                            titleMode: 'manual',
                            newTitle: previous.newTitle || inferDocumentTitle(previous.sourceContent, previous.prompt),
                          }))
                        }
                      />
                      <div>
                        <div className="thinkflow-push-mode-title">手动填写</div>
                        <div className="thinkflow-push-mode-desc">你可以直接定标题，不填时也会回退为 AI 命名</div>
                      </div>
                    </label>
                  </div>
                  {pushPopover.titleMode === 'manual' ? (
                    <>
                      <div className="thinkflow-push-label">新建名称</div>
                      <input
                        className="thinkflow-outline-input"
                        value={pushPopover.newTitle}
                        disabled={pushSubmitting}
                        onChange={(event) => setPushPopover((previous) => ({ ...previous, newTitle: event.target.value }))}
                        placeholder="可手动填写；留空则仍会回退为 AI 命名"
                      />
                    </>
                  ) : (
                    <div className="thinkflow-push-title-hint">当前将由 AI 自动命名，你确认沉淀后会直接生成。</div>
                  )}
                </div>
              ) : null}

              {pushPopover.destinationType === 'document' ? (
                <div className="thinkflow-push-field">
                  <div className="thinkflow-push-label">处理方式</div>
                  <div className="thinkflow-push-modes">
                    {[
                      { value: 'append', label: '直接追加', desc: '原文放入文档末尾' },
                      { value: 'organize', label: 'AI整理后追加', desc: '整理成当前提纲', recommended: true },
                      { value: 'merge', label: 'AI融合到已有内容', desc: '融入现有段落' },
                    ].map((item) => (
                      <label key={item.value} className={`thinkflow-push-mode ${pushPopover.mode === item.value ? 'is-active' : ''}`}>
                        <input
                          type="radio"
                          checked={pushPopover.mode === item.value}
                          disabled={pushSubmitting}
                          onChange={() => setPushPopover((previous) => ({ ...previous, mode: item.value as PushMode }))}
                        />
                        <div>
                          <div className="thinkflow-push-mode-title">
                            {item.label}
                            {item.recommended ? <span className="thinkflow-push-recommended">推荐</span> : null}
                          </div>
                          <div className="thinkflow-push-mode-desc">{item.desc}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="thinkflow-push-field">
                <div className="thinkflow-push-label">补充指示（可选）</div>
                <textarea
                  className="thinkflow-push-textarea"
                  value={pushPopover.prompt}
                  disabled={pushSubmitting}
                  onChange={(event) => setPushPopover((previous) => ({ ...previous, prompt: event.target.value }))}
                  placeholder={
                    pushPopover.destinationType === 'guidance'
                      ? '如：这是给 PPT 的指导，强调业务价值、避免学术化表达'
                      : pushPopover.destinationType === 'summary'
                        ? '如：提炼关键结论，保留仍待确认的问题'
                        : '如：提炼核心数据；标注 [待确认]；转成当前提纲'
                  }
                />
              </div>

              <div className="thinkflow-push-field">
                <div className="thinkflow-push-label">本次沉淀来源</div>
                <div className="thinkflow-push-preview">
                  {pushPopover.sourceEntries.map((entry) => (
                    <span key={`${entry.messageId}_${entry.kind}`} className="thinkflow-push-preview-chip">
                      {entry.kind === 'qa' ? 'QA' : entry.kind === 'multi' ? '多轮' : entry.role === 'assistant' ? 'AI' : '你'} · {entry.time}
                    </span>
                  ))}
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
                {pushSubmitting ? '处理中...' : '确认沉淀'}
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
                <p>这里展示当前笔记本下已记录的对话内容。</p>
              </div>
              <button type="button" className="thinkflow-push-close" onClick={() => setHistoryOpen(false)}>
                关闭
              </button>
            </div>
            <div className="thinkflow-history-body">
              {historyLoading ? <div className="thinkflow-empty">正在加载历史对话...</div> : null}
              {!historyLoading && historyMessages.length === 0 ? <div className="thinkflow-empty">当前还没有可查看的历史对话。</div> : null}
              {!historyLoading && historyMessages.length > 0 ? (
                <div className="thinkflow-history-list">
                  {historyMessages.map((item) => (
                    <article key={item.id} className={`thinkflow-history-item is-${item.role}`}>
                      <div className="thinkflow-history-meta">
                        <strong>{item.role === 'assistant' ? 'AI' : '你'}</strong>
                        {item.created_at ? <span>{item.created_at}</span> : null}
                      </div>
                      <div className="thinkflow-history-content">
                        <ReactMarkdown>{item.content}</ReactMarkdown>
                      </div>
                    </article>
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
