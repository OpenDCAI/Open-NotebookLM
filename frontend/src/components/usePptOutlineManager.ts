import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch } from '../config/api';
import type { KnowledgeFile } from '../types';
import { diffPptOutline } from './pptOutlineDiff';
import { mergeOutlineWithManualEdits, formatConflictToast } from './pptOutlineMerge';
import { formatThinkFlowTime } from './thinkflow-document-utils';
import type { ManualEditLog } from './thinkflow-types';

// ─── Types (mirrored from ThinkFlowWorkspace) ────────────────────────────────

type OutputType = 'ppt' | 'report' | 'mindmap' | 'podcast' | 'flashcard' | 'quiz';
type PptPipelineStage = 'outline_ready' | 'pages_ready' | 'generated';
type WorkspaceMode = 'normal' | 'output_focus' | 'output_immersive';

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

type PptOutputInfo = {
  type?: string;
  title?: string;
  page_count?: number;
  audience?: string;
  source_names?: string[];
  bound_document_titles?: string[];
  stage_label?: string;
};

type PptStyleInfo = {
  preset?: string;
  label?: string;
  tone?: string;
  visual_style?: string;
  audience_assumption?: string;
  supplement_prompt?: string[];
};

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
  draft_output_info?: PptOutputInfo;
  draft_style_info?: PptStyleInfo;
  draft_global_directives?: OutlineDirective[];
  intent_summary?: OutlineIntentSummary;
  summary?: string;
  has_pending_changes?: boolean;
  change_summary?: string;
  created_at?: string;
  updated_at?: string;
  applied_at?: string;
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
  outline_chat_draft_output_info?: PptOutputInfo;
  outline_chat_draft_style_info?: PptStyleInfo;
  outline_chat_draft_global_directives?: OutlineDirective[];
  outline_chat_has_pending_changes?: boolean;
  output_info?: PptOutputInfo;
  style_info?: PptStyleInfo;
  page_reviews?: PptPageReview[];
  page_versions?: PptPageVersion[];
  created_at: string;
  updated_at: string;
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

type PptOutputCreationPending = {
  title: string;
  content: string;
  startedAt: string;
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

type ThinkFlowMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  pushed?: boolean;
  capturedTargets?: any[];
  fileAnalyses?: any[];
  sourceMapping?: Record<string, string>;
  sourcePreviewMapping?: Record<string, string>;
  sourceReferenceMapping?: Record<string, any>;
  meta?: Record<string, any>;
};

type ThinkFlowWorkspaceItem = {
  id: string;
  type: 'summary' | 'guidance';
  title: string;
  content?: string;
  source_refs?: any[];
  capture_count?: number;
  created_at: string;
  updated_at: string;
};

type ThinkFlowDocument = {
  id: string;
  title: string;
  content?: string;
  created_at: string;
  updated_at: string;
  version_count?: number;
  status_tokens?: Record<string, number>;
  push_traces?: any[];
};

// ─── Standalone helper functions ─────────────────────────────────────────────

export function normalizePptStage(output: ThinkFlowOutput | null): PptPipelineStage {
  if (!output) return 'outline_ready';
  if (output.pipeline_stage === 'generated' || output.status === 'generated') return 'generated';
  if (output.pipeline_stage === 'pages_ready') return 'pages_ready';
  return 'outline_ready';
}

export function getPptStageLabel(stage: PptPipelineStage) {
  switch (stage) {
    case 'outline_ready':
      return '大纲确认';
    case 'pages_ready':
      return '逐页生成确认';
    case 'generated':
      return '生成结果';
    default:
      return 'PPT';
  }
}

export function getPptPreviewImages(output: ThinkFlowOutput | null): string[] {
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

export function buildOutlineSummaryFallback(outline: OutlineSection[]) {
  if (!outline.length) {
    return '我先总结一下当前大纲思路：这份 PPT 还没有形成明确页面。你可以先说想强调的结构、重点或表达方式，我会先整理成候选改动。';
  }
  const titles = outline.map((item, index) => item.title || `第 ${index + 1} 页`);
  const parts = [`我先总结一下当前大纲思路：这版 PPT 目前共 ${titles.length} 页。`];
  if (titles.length === 1) {
    parts.push(`当前主要围绕「${titles[0]}」展开。`);
  } else {
    parts.push(`开场从「${titles[0]}」切入。`);
    if (titles.length > 2) {
      parts.push(`中段重点覆盖「${titles.slice(1, -1).slice(0, 3).join('」「')}」。`);
    }
    parts.push(`最后收束到「${titles[titles.length - 1]}」。`);
  }
  parts.push('你可以继续说想怎么改产出信息、风格、结构、页序或单页重点，我会先整理成候选修改，是否应用由你决定。');
  return parts.join('');
}

export function getOutlineChatSessions(output: ThinkFlowOutput | null): OutlineChatSession[] {
  if (!output) return [];
  const sessions = Array.isArray(output.outline_chat_sessions) ? output.outline_chat_sessions : [];
  if (sessions.length > 0) return sessions;
  const fallbackOutline = Array.isArray(output.outline) ? output.outline : [];
  const fallbackHistory = Array.isArray(output.outline_chat_history) ? output.outline_chat_history : [];
  return [
    {
      id: 'outline_chat_fallback',
      status: 'active',
      messages:
        fallbackHistory.length > 0
          ? fallbackHistory
          : [
              {
                id: 'ppt_outline_summary',
                role: 'assistant',
                content: buildOutlineSummaryFallback(fallbackOutline),
                created_at: new Date().toISOString(),
              },
            ],
      draft_outline: fallbackOutline,
      has_pending_changes: false,
    },
  ];
}

export function getActiveOutlineChatSession(output: ThinkFlowOutput | null): OutlineChatSession | null {
  const sessions = getOutlineChatSessions(output);
  if (!sessions.length) return null;
  const activeSessionId = String(output?.outline_chat_active_session_id || '').trim();
  const byId = sessions.find((session) => session.id === activeSessionId);
  if (byId) return byId;
  return sessions.find((session) => session.status === 'active') || sessions[sessions.length - 1] || null;
}

export function getArchivedOutlineChatSessions(output: ThinkFlowOutput | null): OutlineChatSession[] {
  const active = getActiveOutlineChatSession(output);
  return getOutlineChatSessions(output).filter((session) => session.id !== active?.id);
}

export function getVisiblePptOutline(output: ThinkFlowOutput | null): OutlineSection[] {
  const activeSession = getActiveOutlineChatSession(output);
  if (Array.isArray(activeSession?.draft_outline) && activeSession!.draft_outline!.length > 0) {
    return activeSession!.draft_outline!;
  }
  if (Array.isArray(output?.outline)) return output!.outline!;
  return [];
}

function normalizeStyleText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean).join('；');
  }
  return String(value || '').trim();
}

function getAppliedPptStyleInfo(output: ThinkFlowOutput | null): PptStyleInfo {
  return output?.style_info || {};
}

function getDraftPptStyleInfo(output: ThinkFlowOutput | null): PptStyleInfo {
  const activeSession = getActiveOutlineChatSession(output);
  if (activeSession?.draft_style_info) return activeSession.draft_style_info;
  if (output?.outline_chat_draft_style_info) return output.outline_chat_draft_style_info;
  return getAppliedPptStyleInfo(output);
}

function buildPptStyleInfoDiff(applied: PptStyleInfo, draft: PptStyleInfo) {
  const fields: Array<{ field: keyof PptStyleInfo; label: string }> = [
    { field: 'label', label: '风格类型' },
    { field: 'tone', label: '表达语气' },
    { field: 'visual_style', label: '视觉倾向' },
    { field: 'audience_assumption', label: '受众假设' },
    { field: 'supplement_prompt', label: '补充要求' },
  ];
  const entries = fields
    .map(({ field, label }) => {
      const before = normalizeStyleText(applied?.[field]);
      const after = normalizeStyleText(draft?.[field]);
      return before === after
        ? null
        : {
            field,
            label,
            before: before || '未设置',
            after: after || '未设置',
          };
    })
    .filter(Boolean);
  return { totalCount: entries.length, entries };
}

export function getAppliedOutlineGlobalDirectives(_output: ThinkFlowOutput | null): OutlineDirective[] {
  return [];
}

export function getDraftOutlineGlobalDirectives(_output: ThinkFlowOutput | null): OutlineDirective[] {
  return [];
}

export function hasPendingOutlineDraft(output: ThinkFlowOutput | null): boolean {
  if (!output) return false;
  if (typeof output.outline_chat_has_pending_changes === 'boolean') {
    return output.outline_chat_has_pending_changes;
  }
  const activeSession = getActiveOutlineChatSession(output);
  return Boolean(activeSession?.has_pending_changes);
}

function formatChatTime(value?: string) {
  return formatThinkFlowTime(value || new Date());
}

export function buildOutlineChatMessages(output: ThinkFlowOutput | null): ThinkFlowMessage[] {
  const activeSession = getActiveOutlineChatSession(output);
  const history = Array.isArray(activeSession?.messages)
    ? activeSession?.messages
    : Array.isArray(output?.outline_chat_history)
      ? output?.outline_chat_history
      : [];
  if (history.length === 0) {
    return [
      {
        id: 'ppt_outline_welcome',
        role: 'assistant',
        content: buildOutlineSummaryFallback(getVisiblePptOutline(output)),
        time: formatThinkFlowTime(new Date()),
      },
    ];
  }
  const appliedOutline = Array.isArray(output?.outline) ? output!.outline! : [];
  const draftOutline = getVisiblePptOutline(output);
  const outlineDiff = diffPptOutline(appliedOutline, draftOutline);
  const styleDiff = buildPptStyleInfoDiff(getAppliedPptStyleInfo(output), getDraftPptStyleInfo(output));
  const hasPendingChanges = hasPendingOutlineDraft(output);
  const lastAssistantIndex = history.reduce((latest, item, index) => (item.role === 'assistant' ? index : latest), -1);

  return history.map((item, index) => ({
    id: item.id || `outline_chat_${index}`,
    role: item.role === 'user' ? 'user' : 'assistant',
    content: item.content || '',
    time: formatChatTime(item.created_at),
    meta:
      hasPendingChanges && index === lastAssistantIndex && item.role === 'assistant'
        ? {
            type: 'ppt_outline_draft',
            outlineDiff,
            styleDiff,
            intentSummary: activeSession?.intent_summary || { mode: 'none', global_directives: [], slide_targets: [] },
            changeSummary: String(activeSession?.change_summary || '').trim(),
          }
        : undefined,
  }));
}

export function resolveNextActiveOutputId(
  currentOutputId: string,
  preferredOutputId: string | undefined,
  outputs: Array<{ id?: string }>,
): string {
  const targetId = preferredOutputId || currentOutputId;
  if (targetId && outputs.some((item) => item.id === targetId)) {
    return targetId;
  }
  return '';
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

const outputButtons: Array<{ type: OutputType; label: string }> = [
  { type: 'ppt', label: 'PPT' },
  { type: 'report', label: '报告' },
  { type: 'mindmap', label: '导图' },
  { type: 'podcast', label: '播客' },
  { type: 'flashcard', label: '卡片' },
  { type: 'quiz', label: '测验' },
];

function outputLabel(type: OutputType) {
  return outputButtons.find((item) => item.type === type)?.label || type;
}

function diffOutlineFields(
  prev: OutlineSection[],
  current: OutlineSection[],
): { page_index: number; field: string }[] {
  const changes: { page_index: number; field: string }[] = [];
  const fields = ['title', 'layout_description', 'key_points', 'asset_ref'] as const;
  const len = Math.max(prev.length, current.length);
  for (let i = 0; i < len; i++) {
    const p = prev[i];
    const c = current[i];
    if (!p || !c) continue;
    for (const f of fields) {
      if (JSON.stringify(p[f] ?? '') !== JSON.stringify(c[f] ?? '')) {
        changes.push({ page_index: i, field: f });
      }
    }
  }
  return changes;
}

function formatEditSummary(changes: { page_index: number; field: string }[]): string {
  const byPage = new Map<number, string[]>();
  const fieldLabels: Record<string, string> = {
    title: '标题', layout_description: '布局', key_points: '要点', asset_ref: '素材',
  };
  for (const c of changes) {
    const arr = byPage.get(c.page_index) ?? [];
    arr.push(fieldLabels[c.field] || c.field);
    byPage.set(c.page_index, arr);
  }
  const parts: string[] = [];
  for (const [idx, fields] of byPage) {
    parts.push(`第${idx + 1}页(${fields.join('、')})`);
  }
  return parts.join('、');
}

function resolveFileUrl(file: any): string {
  return file?.static_url || file?.url || file?.storage_path || '';
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

type Notebook = {
  id: string;
  title?: string;
  name?: string;
};

type EffectiveUser = {
  id: string;
  email: string;
};

export type UsePptOutlineManagerDeps = {
  notebook: Notebook;
  notebookTitle: string;
  effectiveUser: EffectiveUser;
  pushToast: (message: string, kind?: 'error' | 'success' | 'info' | 'warning', duration?: number) => void;
  setGlobalError: (msg: string) => void;
  setChatInput: React.Dispatch<React.SetStateAction<string>>;
  setChatLoading: React.Dispatch<React.SetStateAction<boolean>>;
  selectedGuidanceIds: string[];
  guidanceItems: ThinkFlowWorkspaceItem[];
  documents: ThinkFlowDocument[];
  files: KnowledgeFile[];
  selectedSourceIds: string[];
  boundDocIds: string[];
  activeDocumentId: string;
  documentTitle: string;
  documentContent: string;
  activeDocument: ThinkFlowDocument | null;
  notebookQuery: string;
  selectedSourceNames: string[];
  setLeftTab: React.Dispatch<React.SetStateAction<'conversations' | 'materials' | 'outputs'>>;
  setRightMode: React.Dispatch<React.SetStateAction<'summary' | 'doc' | 'guidance' | 'outline'>>;
  setRightPanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setWorkspaceMode: React.Dispatch<React.SetStateAction<WorkspaceMode>>;
  enterOutputWorkspace: (mode?: WorkspaceMode) => void;
  syncPptOutputDocument?: (output: ThinkFlowOutput) => Promise<void>;
  buildOutputContextSnapshot: (params: {
    outputId: string;
    targetType: OutputType;
    documentId?: string;
    guidanceItemIds?: string[];
    selectedSourceIds?: string[];
    boundDocumentIds?: string[];
  }) => OutputContextSnapshot;
  ensureDocumentContent: (documentId: string) => Promise<ThinkFlowDocument | null>;
  setIsOutputHeaderCollapsed: React.Dispatch<React.SetStateAction<boolean>>;
  loadDocumentDetail: (documentId: string) => Promise<ThinkFlowDocument>;
};

export function usePptOutlineManager(deps: UsePptOutlineManagerDeps) {
  const {
    notebook,
    notebookTitle,
    effectiveUser,
    pushToast,
    setGlobalError,
    setChatInput,
    setChatLoading,
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
    setRightPanelOpen,
    setWorkspaceMode,
    enterOutputWorkspace,
    syncPptOutputDocument,
    buildOutputContextSnapshot,
    ensureDocumentContent,
    setIsOutputHeaderCollapsed,
    loadDocumentDetail,
  } = deps;

  // ─── State ──────────────────────────────────────────────────────────────────
  const [outputs, setOutputs] = useState<ThinkFlowOutput[]>([]);
  const [activeOutputId, setActiveOutputId] = useState('');
  const [outlineSaving, setOutlineSaving] = useState(false);
  const [generatingOutline, setGeneratingOutline] = useState<OutputType | null>(null);
  const [generatingOutput, setGeneratingOutput] = useState(false);
  const [activePptSlideIndex, setActivePptSlideIndex] = useState<number>(0);
  const [pptOutlineReadonlyOpen, setPptOutlineReadonlyOpen] = useState(false);
  const [pptOutlinePendingMessages, setPptOutlinePendingMessages] = useState<ThinkFlowMessage[]>([]);
  const [pptOutputCreationPending, setPptOutputCreationPending] = useState<PptOutputCreationPending | null>(null);
  const [outputContexts, setOutputContexts] = useState<Record<string, OutputContextState>>({});
  const [pptSourceLockIntent, setPptSourceLockIntent] = useState<PptSourceLockIntent | null>(null);
  const [directOutputIntent, setDirectOutputIntent] = useState<DirectOutputIntent | null>(null);
  const [manualEditsBuffer, setManualEditsBuffer] = useState<ManualEditLog[]>([]);
  const lastSavedOutlineRef = useRef<OutlineSection[]>([]);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── Computed values ─────────────────────────────────────────────────────────
  const activeOutput = useMemo(
    () => outputs.find((item) => item.id === activeOutputId) || null,
    [activeOutputId, outputs],
  );
  const activePptStage = useMemo(() => normalizePptStage(activeOutput), [activeOutput]);
  const activePptOutline = useMemo(() => getVisiblePptOutline(activeOutput), [activeOutput]);
  const activePptDraftPending = useMemo(() => hasPendingOutlineDraft(activeOutput), [activeOutput]);
  const activeOutlineChatSession = useMemo(() => getActiveOutlineChatSession(activeOutput), [activeOutput]);
  const archivedOutlineChatSessions = useMemo(() => getArchivedOutlineChatSessions(activeOutput), [activeOutput]);
  const activePptGlobalDirectives = useMemo(() => getAppliedOutlineGlobalDirectives(activeOutput), [activeOutput]);
  const activePptPreviewImages = useMemo(() => getPptPreviewImages(activeOutput), [activeOutput]);
  const activePptSlide = useMemo(() => {
    if (!activeOutput || activeOutput.target_type !== 'ppt') return null;
    const slides = activePptOutline;
    if (slides.length === 0) return null;
    const safeIndex = Math.min(Math.max(activePptSlideIndex, 0), slides.length - 1);
    return { slide: slides[safeIndex], index: safeIndex };
  }, [activeOutput, activePptOutline, activePptSlideIndex]);
  const isPptOutlineChatStage = useMemo(
    () => Boolean(activeOutput?.target_type === 'ppt' && activePptStage === 'outline_ready'),
    [activeOutput?.target_type, activePptStage],
  );
  const pptOutlineChatMessages = useMemo(
    () => buildOutlineChatMessages(isPptOutlineChatStage ? activeOutput : null),
    [activeOutput, isPptOutlineChatStage],
  );
  const activeOutputContext = useMemo(
    () => {
      if (!activeOutputId) return null;
      const output = outputs.find((item) => item.id === activeOutputId) || null;
      if (!output || output.target_type === 'ppt') return null;
      return outputContexts[activeOutputId] || null;
    },
    [activeOutputId, outputContexts, outputs],
  );

  // ─── Functions ───────────────────────────────────────────────────────────────

  const refreshOutputs = useCallback(async (preferredId?: string) => {
    try {
      const response = await apiFetch(`/api/v1/kb/outputs?${notebookQuery}`);
      const data = await parseJson<{ outputs: ThinkFlowOutput[] }>(response);
      const items = data.outputs || [];
      setOutputs(items);
      setActiveOutputId(resolveNextActiveOutputId(activeOutputId, preferredId, items));
    } catch (error: any) {
      setGlobalError(error?.message || '加载产出失败');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebookQuery, activeOutputId, setGlobalError]);

  const handleOutputWorkspaceScroll = useCallback((scrollTop: number) => {
    setIsOutputHeaderCollapsed((previous) => {
      if (!previous && scrollTop > 24) return true;
      if (previous && scrollTop <= 4) return false;
      return previous;
    });
  }, [setIsOutputHeaderCollapsed]);

  const resolveOutputCreationInputs = useCallback(async (
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
      (targetType === 'ppt' ? activeOutput?.document_id || '' : '');
    let outputDocumentTitle = documentTitle || activeDocument?.title || '文档';
    let outputDocumentContent = documentContent;
    if (outputDocumentId && outputDocumentId !== activeDocumentId) {
      const ensuredDocument = await ensureDocumentContent(outputDocumentId);
      if (ensuredDocument) {
        outputDocumentTitle = ensuredDocument.title || outputDocumentTitle;
        outputDocumentContent = ensuredDocument.content || outputDocumentContent;
      }
    }
    if (targetType === 'ppt' && (!outputDocumentTitle || outputDocumentTitle === '文档')) {
      outputDocumentTitle = resolvedSourceNames[0] || notebookTitle || 'PPT';
    }
    if (targetType !== 'ppt' && !String(outputDocumentContent || '').trim()) {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedGuidanceIds, boundDocIds, selectedSourceIds, files,
    activeDocumentId, activeOutput, documentTitle, activeDocument,
    documentContent, notebookTitle, guidanceItems, documents,
    ensureDocumentContent,
  ]);

  const openPptSourceLockIntent = useCallback(async () => {
    setGlobalError('');
    setPptSourceLockIntent({
      outputDocumentId: '',
      outputDocumentTitle: documentTitle || activeDocument?.title || '梳理文档',
      outputTitle: `${documentTitle || activeDocument?.title || notebookTitle || '文档'} · PPT`,
      guidanceItemIds: [],
      guidanceTitles: [],
      boundDocumentIds: [],
      boundDocumentTitles: [],
      sourcePaths: [],
      sourceNames: [],
      loading: true,
      errorMessage: '',
    });
    try {
      const resolved = await resolveOutputCreationInputs('ppt');
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
              loading: false,
              errorMessage: '',
            }
          : current,
      );
    } catch (error: any) {
      const message = error?.message || '无法确认本次 PPT 来源';
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentTitle, activeDocument, notebookTitle, resolveOutputCreationInputs, setGlobalError]);

  const confirmPptSourceLockIntent = useCallback(async () => {
    if (!pptSourceLockIntent || pptSourceLockIntent.loading || pptSourceLockIntent.errorMessage) return;
    const intent = pptSourceLockIntent;
    setPptSourceLockIntent(null);
    setWorkspaceMode('normal');
    setRightMode('doc');
    setRightPanelOpen(true);
    setChatInput('');
    setPptOutlinePendingMessages([]);
    setPptOutputCreationPending({
      title: intent.outputTitle || 'PPT 产出文档',
      startedAt: formatThinkFlowTime(new Date()),
      content: [
        `# ${intent.outputTitle || 'PPT 产出文档'}`,
        '',
        '## 产出信息',
        '',
        '- 产出类型：PPT',
        `- 产出标题：${intent.outputTitle || 'PPT 产出文档'}`,
        '- 生成状态：正在整理来源、参考文档和产出约束...',
        '',
        '## 风格信息',
        '',
        '- 风格类型：正在识别',
        '- 补充提示词：',
        '  - 正在根据已确认的来源和参考文档整理...',
        '',
        '## PPT 大纲',
        '',
        '正在生成页级大纲...',
      ].join('\n'),
    });
    try {
      await createOutline('ppt', {
        titleOverride: intent.outputTitle,
        documentIdOverride: intent.outputDocumentId,
        guidanceItemIdsOverride: intent.guidanceItemIds,
        boundDocumentIdsOverride: intent.boundDocumentIds,
        sourcePathsOverride: intent.sourcePaths,
        sourceNamesOverride: intent.sourceNames,
      });
    } finally {
      setPptOutputCreationPending(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pptSourceLockIntent, setWorkspaceMode, setRightMode, setRightPanelOpen, setChatInput]);

  const openDirectOutputIntent = useCallback(async (targetType: Exclude<OutputType, 'ppt'>) => {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentTitle, activeDocument, selectedSourceNames, notebookTitle, resolveOutputCreationInputs, setGlobalError]);

  const confirmDirectOutputIntent = useCallback(async () => {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directOutputIntent]);

  const openExistingOutput = useCallback(async (output: ThinkFlowOutput) => {
    setPptSourceLockIntent(null);
    setDirectOutputIntent(null);
    setPptOutlinePendingMessages([]);
    setActivePptSlideIndex(0);
    setActiveOutputId(output.id);
    const isPptDraftStage = output.target_type === 'ppt' && normalizePptStage(output) === 'outline_ready';
    if (isPptDraftStage) {
      setWorkspaceMode('normal');
      setRightMode('doc');
      setRightPanelOpen(true);
    } else {
      setLeftTab('outputs');
    }
    setOutputContexts((previous) => {
      if (previous[output.id]) return previous;
      if (!output?.id || output.target_type === 'ppt') return previous;
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
    if (isPptDraftStage) {
      await syncPptOutputDocument?.(output);
    } else {
      enterOutputWorkspace(output.target_type === 'ppt' ? 'output_focus' : 'output_immersive');
    }
    if (output.document_id) {
      try {
        await loadDocumentDetail(output.document_id);
      } catch {}
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setLeftTab, setRightMode, setRightPanelOpen, setWorkspaceMode, enterOutputWorkspace, files, buildOutputContextSnapshot, loadDocumentDetail, syncPptOutputDocument]);

  const handlePptOutlineChatMessage = useCallback(async (query: string) => {
    if (!activeOutputId || !activeOutput || activeOutput.target_type !== 'ppt') return;
    const focusIndex = activePptSlide?.index ?? activePptSlideIndex ?? 0;
    const requestStartedAt = formatThinkFlowTime(new Date());
    const pendingUserMessage: ThinkFlowMessage = {
      id: `ppt_outline_user_${Date.now()}`,
      role: 'user',
      content: query,
      time: requestStartedAt,
    };
    const pendingAssistantMessage: ThinkFlowMessage = {
      id: `ppt_outline_assistant_${Date.now()}`,
      role: 'assistant',
      content: '正在基于来源整理候选大纲...',
      time: requestStartedAt,
    };
    setChatLoading(true);
    setGlobalError('');
    setChatInput('');
    setPptOutlinePendingMessages([pendingUserMessage, pendingAssistantMessage]);
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/outline-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          message: query,
          active_slide_index: focusIndex,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput; assistant_message?: string; applied_slide_index?: number }>(response);
      const nextOutput = data.output;
      const appliedSlideIndex = data.applied_slide_index;
      setOutputs((previous) => previous.map((item) => (item.id === nextOutput.id ? nextOutput : item)));
      if (nextOutput.target_type === 'ppt') {
        await syncPptOutputDocument?.(nextOutput);
      }
      setPptOutlinePendingMessages([]);

      // Auto-navigate to affected slide
      if (typeof appliedSlideIndex === 'number' && appliedSlideIndex >= 0) {
        setActivePptSlideIndex(appliedSlideIndex);
        // Scroll the outline card into view after a short delay for DOM update
        setTimeout(() => {
          const cards = document.querySelectorAll('.thinkflow-ppt-outline-card');
          if (cards[appliedSlideIndex]) {
            cards[appliedSlideIndex].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        }, 100);
      }
    } catch (error: any) {
      setGlobalError(error?.message || '整理 PPT 候选大纲失败');
      setPptOutlinePendingMessages([
        pendingUserMessage,
        {
          ...pendingAssistantMessage,
          content: `请求失败：${error?.message || '未知错误'}`,
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeOutputId, activeOutput, activePptSlide, activePptSlideIndex,
    setChatLoading, setGlobalError, setChatInput,
    notebook.id, notebookTitle, effectiveUser,
    syncPptOutputDocument,
  ]);

  const applyPptOutlineDraft = useCallback(async (): Promise<ThinkFlowOutput | null> => {
    if (!activeOutputId || !activeOutput || activeOutput.target_type !== 'ppt') return null;
    setOutlineSaving(true);
    setGlobalError('');
    try {
      let mergePayload: { merge_strategy?: string; manual_edits_since_draft?: ManualEditLog[] } = {};

      if (manualEditsBuffer.length > 0) {
        const confirmed = lastSavedOutlineRef.current;
        const draft = activeOutput?.outline_chat_draft_outline || [];
        const { conflicts } = mergeOutlineWithManualEdits(confirmed, draft, manualEditsBuffer);

        if (conflicts.length > 0) {
          pushToast(formatConflictToast(conflicts), 'warning');
        }

        mergePayload = {
          merge_strategy: 'smart_merge',
          manual_edits_since_draft: manualEditsBuffer,
        };

        setManualEditsBuffer([]);
      }

      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/outline-chat/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          ...mergePayload,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput; assistant_message?: string }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      await syncPptOutputDocument?.(data.output);
      setPptOutlinePendingMessages([]);
      lastSavedOutlineRef.current = [];  // Will be re-initialized by the useEffect
      if (data.assistant_message) {
        setGlobalError('');
      }
      pushToast(data.assistant_message || '已应用候选修改到产出文档', 'success');
      return data.output;
    } catch (error: any) {
      setGlobalError(error?.message || '推送大纲改动失败');
      return null;
    } finally {
      setOutlineSaving(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOutputId, activeOutput, notebook.id, notebookTitle, effectiveUser, setGlobalError, manualEditsBuffer, pushToast, syncPptOutputDocument]);

  const discardPptOutlineDraft = useCallback(async () => {
    if (!activeOutputId || !activeOutput || activeOutput.target_type !== 'ppt') return;
    setOutlineSaving(true);
    setGlobalError('');
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${activeOutputId}/outline-chat/discard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput; assistant_message?: string }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      await syncPptOutputDocument?.(data.output);
      setPptOutlinePendingMessages([]);
    } catch (error: any) {
      setGlobalError(error?.message || '放弃候选大纲失败');
    } finally {
      setOutlineSaving(false);
    }
  }, [activeOutputId, activeOutput, notebook.id, notebookTitle, effectiveUser, setGlobalError, syncPptOutputDocument]);

  const generateOutputById = useCallback(async (outputId: string) => {
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebook.id, notebookTitle, effectiveUser, refreshOutputs, setGlobalError]);

  const createOutline = useCallback(async (
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
    },
  ) => {
    setGlobalError('');
    setGeneratingOutline(targetType);
    setActiveOutputId('');
    setPptOutlinePendingMessages([]);
    setActivePptSlideIndex(0);
    if (targetType === 'ppt') {
      setWorkspaceMode('normal');
      setRightMode('doc');
      setRightPanelOpen(true);
    } else {
      setLeftTab('outputs');
      setRightMode('outline');
      enterOutputWorkspace('output_immersive');
    }
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
        page_count: targetType === 'ppt' ? 10 : 6,
        guidance_item_ids: resolvedGuidanceIds,
        source_paths: resolvedSourcePaths,
        source_names: resolvedSourceNames,
        bound_document_ids: resolvedBoundDocIds,
        enable_images: targetType === 'ppt' ? true : undefined,
      };
      console.info('[ThinkFlow] createOutline payload', outlinePayload);
      const response = await apiFetch('/api/v1/kb/outputs/outline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(outlinePayload),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      const nextOutput = data.output;
      setActivePptSlideIndex(0);
      setRightMode(targetType === 'ppt' ? 'doc' : 'outline');
      if (targetType !== 'ppt') {
        setLeftTab('outputs');
      }
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
      if (targetType === 'ppt') {
        await syncPptOutputDocument?.(nextOutput);
      }
      if (targetType !== 'ppt') {
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
      if (options?.autoGenerate) {
        await generateOutputById(nextOutput.id);
      }
    } catch (error: any) {
      setGlobalError(error?.message || '生成大纲失败');
    } finally {
      setGeneratingOutline(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    setGlobalError, setLeftTab, setRightMode, enterOutputWorkspace,
    setRightPanelOpen, setWorkspaceMode, syncPptOutputDocument,
    resolveOutputCreationInputs, notebook.id, notebookTitle, effectiveUser,
    buildOutputContextSnapshot, refreshOutputs, generateOutputById,
  ]);

  const saveOutline = useCallback(async (options?: { pipelineStage?: string; enableImages?: boolean; manual_edit_log?: ManualEditLog[] }) => {
    if (!activeOutputId || !activeOutput) return;
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
          manual_edit_log: options?.manual_edit_log,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
    } catch (error: any) {
      setGlobalError(error?.message || '保存大纲失败');
    } finally {
      setOutlineSaving(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOutputId, activeOutput, notebook.id, notebookTitle, effectiveUser, setGlobalError]);

  const confirmPptOutline = useCallback(async () => {
    if (!activeOutputId || !activeOutput || activeOutput.target_type !== 'ppt') return;
    let outputForGeneration = activeOutput;
    if (activePptDraftPending) {
      const appliedOutput = await applyPptOutlineDraft();
      if (!appliedOutput) return;
      outputForGeneration = appliedOutput;
    }
    setOutlineSaving(true);
    try {
      const response = await apiFetch(`/api/v1/kb/outputs/${outputForGeneration.id}/outline`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebookTitle,
          user_id: effectiveUser?.id || 'local',
          email: effectiveUser?.email || '',
          title: outputForGeneration.title,
          prompt: outputForGeneration.prompt || '',
          outline: outputForGeneration.outline || [],
          pipeline_stage: 'pages_ready',
          enable_images: outputForGeneration.enable_images,
        }),
      });
      const data = await parseJson<{ output: ThinkFlowOutput }>(response);
      setOutputs((previous) => previous.map((item) => (item.id === data.output.id ? data.output : item)));
      enterOutputWorkspace('output_focus');
      await generateOutputById(outputForGeneration.id);
    } catch (error: any) {
      setGlobalError(error?.message || '确认生成 PPT 失败');
    } finally {
      setOutlineSaving(false);
    }
  }, [
    activeOutputId, activeOutput, activePptDraftPending, applyPptOutlineDraft,
    notebook.id, notebookTitle, effectiveUser, enterOutputWorkspace,
    generateOutputById, setGlobalError,
  ]);

  const updateOutlineSection = useCallback((index: number, patch: Partial<OutlineSection>) => {
    setOutputs(prev => prev.map(o => {
      if (o.id !== activeOutputId) return o;
      const outline = [...(o.outline || [])];
      if (outline[index]) {
        outline[index] = { ...outline[index], ...patch };
      }
      return { ...o, outline };
    }));

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      const current = activePptOutline.map(s => ({ ...s }));
      const lastSaved = lastSavedOutlineRef.current;
      const changes = diffOutlineFields(lastSaved, current);
      if (changes.length === 0) return;

      const editLog: ManualEditLog = {
        page_index: changes[0].page_index,
        fields: [...new Set(changes.map(c => c.field))] as ManualEditLog['fields'],
        summary: formatEditSummary(changes),
        timestamp: new Date().toISOString(),
      };

      await saveOutline({ manual_edit_log: [editLog] });
      setManualEditsBuffer(prev => [...prev, editLog]);
      lastSavedOutlineRef.current = current;
    }, 500);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOutputId, activePptOutline, saveOutline]);

  useEffect(() => {
    if (activePptOutline.length > 0 && lastSavedOutlineRef.current.length === 0) {
      lastSavedOutlineRef.current = activePptOutline.map(s => ({ ...s }));
    }
  }, [activePptOutline]);

  return {
    // State
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
    pptOutputCreationPending,
    outputContexts,
    setOutputContexts,
    pptSourceLockIntent,
    setPptSourceLockIntent,
    directOutputIntent,
    setDirectOutputIntent,
    // Computed
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
    // Functions
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
    discardPptOutlineDraft,
    createOutline,
    saveOutline,
    confirmPptOutline,
    updateOutlineSection,
    generateOutputById,
    manualEditsBuffer,
    setManualEditsBuffer,
  };
}
