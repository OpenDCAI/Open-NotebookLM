import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronLeft, Plus, Share2, Settings, MessageSquare,
  BarChart2, Zap, AudioLines, Video, FileText,
  Filter, MoreVertical, Search, Image as ImageIcon, FileStack, Sparkles,
  Mic2, Video as VideoIcon, BrainCircuit, Send, Bot, User, Loader2, Upload, X,
  Globe, Link2, Cloud, ChevronRight, LayoutGrid, Download, BookOpen, Brain
} from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { apiFetch } from '../config/api';
import { getApiSettings } from '../services/apiSettingsService';
import { fetchWithCache, invalidateCacheByPrefix } from '../services/clientCache';
import type { KnowledgeFile, ChatMessage, ToolType } from '../types';
import ReactMarkdown from 'react-markdown';
import { MermaidPreview } from '../components/knowledge-base/tools/MermaidPreview';
import { SettingsModal } from '../components/SettingsModal';
import DrawioInlineEditor from '../components/DrawioInlineEditor';
import { FlashcardViewer } from '../components/flashcards/FlashcardViewer';
import { QuizContainer } from '../components/quiz/QuizContainer';
import { NotionEditor } from '../components/notes/NotionEditor';
import { useToast } from '../hooks/useToast';
import katex from 'katex';
import 'katex/dist/katex.min.css';

// 不做用户管理时使用，数据从 outputs 取
const DEFAULT_USER = { id: 'default', email: 'default' };

type DataExtractDatasource = {
  id: string;
  datasource_id: number;
  name: string;
  display_name: string;
  file_path: string;
  local_path: string;
  file_type: string;
  rows?: number;
  columns?: number;
  preview?: {
    column_names?: string[];
    sample_data?: Record<string, any>[];
  };
};

type DataExtractMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  turnId?: string;
  artifactId?: string;
  sql?: string;
  columns?: string[];
  rows?: Record<string, any>[];
  rowCount?: number;
  exportUrl?: string;
  error?: string | null;
};

type TableProcessingMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  sql?: string;
  columns?: string[];
  rows?: Record<string, any>[];
  rowCount?: number;
  exportUrl?: string;
  error?: string | null;
};

type DataExtractArtifact = {
  id: string;
  session_id: string;
  turn_id?: string | null;
  type: 'csv' | 'text';
  title: string;
  question?: string;
  answer_summary?: string;
  sql?: string;
  file_name?: string;
  file_url?: string;
  columns?: string[];
  row_count?: number;
  preview_rows?: Record<string, any>[];
  preview_text?: string;
  selected_datasource_ids?: number[];
  imported_to_sources?: boolean;
  imported_source_static_url?: string;
  reusable_as_input?: boolean;
  created_at: string;
};

type DataExtractTurn = {
  id: string;
  question: string;
  answer: string;
  sql?: string;
  row_count?: number;
  columns?: string[];
  preview_rows?: Record<string, any>[];
  preview_text?: string;
  file_url?: string;
  success?: boolean;
  error?: string | null;
  artifact_id?: string | null;
  created_at: string;
};

type DataExtractSessionSummary = {
  id: string;
  title: string;
  primary_datasource_id: number;
  selected_datasource_ids: number[];
  datasource_snapshot?: Array<{
    datasource_id: number;
    display_name?: string;
    name?: string;
    file_path?: string;
    file_type?: string;
    rows?: number;
    columns?: number;
  }>;
  turn_count?: number;
  artifact_count?: number;
  created_at: string;
  updated_at: string;
};

type PendingSourceItem = {
  id: string;
  name: string;
  sourceType: 'upload';
  status: 'processing' | 'error';
  message?: string;
};

type CitationReference = {
  fileName: string;
  filePath?: string;
  preview?: string;
  chunkIndex?: number | null;
  sourceNumber?: string;
};

type CitationTooltipState = {
  title: string;
  preview: string;
  x: number;
  y: number;
};

type SourceDetailCacheEntry = {
  content: string;
  format: 'text' | 'markdown';
};

const FILE_LIST_CACHE_TTL_MS = 2 * 60 * 1000;
const SOURCE_DETAIL_CACHE_TTL_MS = 15 * 60 * 1000;

const createDataExtractWelcomeMessage = (): DataExtractMessage => ({
  id: 'data-extract-welcome',
  role: 'assistant',
  content: '选择 CSV 数据源后，可以直接用自然语言提问。我会返回结论、SQL、结果表，并把可复用产出放到下方的小 Tab 里。',
  time: new Date().toLocaleTimeString(),
});

const NotebookView = ({ notebook, onBack }: { notebook: any, onBack: () => void }) => {
  const { user } = useAuthStore();
  const effectiveUser = user || DEFAULT_USER;
  const { showToast, ToastContainer } = useToast();
  const [activeTool, setActiveTool] = useState<ToolType>('chat');
  
  // Files management
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pendingSources, setPendingSources] = useState<PendingSourceItem[]>([]);
  
  // Chat state
  const WELCOME_MSG: ChatMessage = {
    id: 'welcome',
    role: 'assistant',
    content: '欢迎使用 OpenNotebookLM！我是你的智能知识库助手。\n\n在左侧上传文档，然后与我对话来探索、总结和生成洞察 —— 支持播客、思维导图、PPT、闪卡、测验等多种输出形式。',
    time: new Date().toLocaleTimeString()
  };
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([WELCOME_MSG]);
  const chatPersistSkippedRef = React.useRef(false);
  const conversationIdRef = React.useRef<string | null>(null);
  const [inputMsg, setInputMsg] = useState('');
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [dataExtractDatasources, setDataExtractDatasources] = useState<DataExtractDatasource[]>([]);
  const [dataExtractDatasourceId, setDataExtractDatasourceId] = useState<string>('');
  const [dataExtractSessionId, setDataExtractSessionId] = useState<string | null>(null);
  const [dataExtractSessions, setDataExtractSessions] = useState<DataExtractSessionSummary[]>([]);
  const [dataExtractArtifacts, setDataExtractArtifacts] = useState<DataExtractArtifact[]>([]);
  const [dataExtractSelectedArtifactIds, setDataExtractSelectedArtifactIds] = useState<Set<string>>(new Set());
  const [dataExtractPreviewArtifact, setDataExtractPreviewArtifact] = useState<DataExtractArtifact | null>(null);
  const [dataExtractSubView, setDataExtractSubView] = useState<'current' | 'history'>('current');
  const [dataExtractHistoryLoading, setDataExtractHistoryLoading] = useState(false);
  const [dataExtractInput, setDataExtractInput] = useState('');
  const [dataExtractMessages, setDataExtractMessages] = useState<DataExtractMessage[]>([
    createDataExtractWelcomeMessage(),
  ]);
  const [dataExtractLoading, setDataExtractLoading] = useState(false);
  const [dataExtractSyncing, setDataExtractSyncing] = useState(false);

  // Table processing states
  const [tableProcessingInput, setTableProcessingInput] = useState('');
  const [tableProcessingMessages, setTableProcessingMessages] = useState<TableProcessingMessage[]>([
    { id: 'table-processing-welcome', role: 'assistant', content: '选择 CSV 数据源后，输入自然语言指令进行智能处理。', time: new Date().toLocaleTimeString() }
  ]);
  const [tableProcessingResult, setTableProcessingResult] = useState<any>(null);
  const [tableProcessingLoading, setTableProcessingLoading] = useState(false);
  const [tableProcessingFormat, setTableProcessingFormat] = useState<'json' | 'csv' | 'markdown' | 'dict'>('csv');
  const [tableProcessingSubView, setTableProcessingSubView] = useState<'current' | 'history'>('current');
  const [tableProcessingSessions, setTableProcessingSessions] = useState<Array<{id:string; title:string; updated_at:string; instruction:string;}>>([]);

  const [chatLoadingStage, setChatLoadingStage] = useState('思考中...');

  // 对话历史：本地持久化
  type ConversationItem = { id: string; title: string; messages: ChatMessage[]; updatedAt: number };
  const getConversationsKey = () => {
    const uid = effectiveUser?.id || effectiveUser?.email || '';
    if (!uid || !notebook?.id) return null;
    return `kb_conversations_${uid}_${notebook.id}`;
  };
  const loadConversationHistory = (): ConversationItem[] => {
    const key = getConversationsKey();
    if (!key) return [];
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch {
      return [];
    }
  };
  const saveConversationHistory = (list: ConversationItem[]) => {
    const key = getConversationsKey();
    if (!key) return;
    try {
      localStorage.setItem(key, JSON.stringify(list));
    } catch (_) {}
  };
  const [conversationHistory, setConversationHistory] = useState<ConversationItem[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [chatSubView, setChatSubView] = useState<'current' | 'history'>('current');
  useEffect(() => {
    setConversationHistory(loadConversationHistory());
  }, [notebook?.id, effectiveUser?.id]);
  
  // Tool outputs
  const [toolOutput, setToolOutput] = useState<any>(null);
  const [toolLoading, setToolLoading] = useState(false);
  const [outputFeed, setOutputFeed] = useState<Array<{
    id: string;
    type: 'ppt' | 'mindmap' | 'podcast' | 'drawio' | 'flashcard' | 'quiz' | 'note';
    title: string;
    sources: string;
    url?: string;
    /** PPT 专用：PDF 预览地址，用于内嵌展示；url 为 PPTX 下载 */
    previewUrl?: string;
    createdAt: string;
    mermaidCode?: string;
    setId?: string;
  }>>([]);
  const [editingNote, setEditingNote] = useState<{ title: string; blocks: any[] } | null>(null);

  // Settings modal
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  // Output preview
  const [previewOutput, setPreviewOutput] = useState<{
    id: string;
    type: 'ppt' | 'mindmap' | 'podcast' | 'drawio' | 'flashcard' | 'quiz' | 'note';
    title: string;
    sources: string;
    url?: string;
    previewUrl?: string;
    createdAt: string;
    mermaidCode?: string;
    setId?: string;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  /** DrawIO 预览：从 url 拉取后的 xml，用于在弹窗内嵌编辑 */
  const [previewDrawioXml, setPreviewDrawioXml] = useState<string | null>(null);
  const [retrievalError, setRetrievalError] = useState('');
  const [retrievalModel, setRetrievalModel] = useState('text-embedding-3-large');
  const [vectorFiles, setVectorFiles] = useState<any[]>([]);
  const [vectorLoading, setVectorLoading] = useState(false);
  const [vectorError, setVectorError] = useState('');
  const [vectorActionLoading, setVectorActionLoading] = useState<Record<string, boolean>>({});
  const [vectorStatusByPath, setVectorStatusByPath] = useState<Record<string, string>>({});

  // Fast Research 引入：搜索 + top10 作为来源
  const [fastResearchQuery, setFastResearchQuery] = useState('');
  const [fastResearchLoading, setFastResearchLoading] = useState(false);
  const [fastResearchSources, setFastResearchSources] = useState<Array<{ title: string; link: string; snippet: string }>>([]);
  const [fastResearchSelected, setFastResearchSelected] = useState<Set<number>>(new Set());
  const [fastResearchError, setFastResearchError] = useState('');
  const [importingSources, setImportingSources] = useState(false);
  const [fileUploading, setFileUploading] = useState(false);
  // Deep Research 报告生成
  const [deepResearchTopic, setDeepResearchTopic] = useState('');
  const [deepResearchLoading, setDeepResearchLoading] = useState(false);
  const [deepResearchError, setDeepResearchError] = useState('');
  /** Deep Research 成功后的简要提示，在弹框内展示，不弹 alert */
  const [deepResearchSuccess, setDeepResearchSuccess] = useState<{ topic: string; pdfUrl?: string } | null>(null);
  const [showIntroduceModal, setShowIntroduceModal] = useState(false);
  const [introduceOption, setIntroduceOption] = useState<'search' | 'deepresearch'>('search');
  // 引入：网站 URL / 直接输入
  const [introduceUrl, setIntroduceUrl] = useState('');
  const [introduceUrlLoading, setIntroduceUrlLoading] = useState(false);
  const [introduceUrlError, setIntroduceUrlError] = useState('');
  const [introduceUrlSuccess, setIntroduceUrlSuccess] = useState('');
  const [introduceText, setIntroduceText] = useState('');
  const [introduceTextLoading, setIntroduceTextLoading] = useState(false);
  const [introduceTextError, setIntroduceTextError] = useState('');
  const [introduceTextSuccess, setIntroduceTextSuccess] = useState('');
  const processingUploadCount = pendingSources.filter(
    item => item.sourceType === 'upload' && item.status === 'processing'
  ).length;
  const sourceListCount = files.length + pendingSources.length;

  // 来源详情：点击某项后翻转显示解析内容（PDF 等解析为 markdown 展示）
  const [sourceDetailView, setSourceDetailView] = useState<KnowledgeFile | null>(null);
  const [sourceDetailContent, setSourceDetailContent] = useState('');
  const [sourceDetailFormat, setSourceDetailFormat] = useState<'text' | 'markdown'>('text');
  const [sourceDetailLoading, setSourceDetailLoading] = useState(false);
  const [sourceDetailCitationFocus, setSourceDetailCitationFocus] = useState<CitationReference | null>(null);
  const sourceDetailCitationRef = React.useRef<HTMLDivElement | null>(null);
  const [hoveredCitation, setHoveredCitation] = useState<CitationTooltipState | null>(null);

  // Cache refs to avoid redundant API calls
  const lastFetchedNotebookIdForSources = React.useRef<string | null>(null);
  const lastFetchedNotebookIdForOutputs = React.useRef<string | null>(null);

  // Flashcard state
  const [flashcards, setFlashcards] = useState<any[]>([]);
  const [showFlashcardViewer, setShowFlashcardViewer] = useState(false);
  const [flashcardSetId, setFlashcardSetId] = useState<string>('');

  // Quiz state
  const [quizQuestions, setQuizQuestions] = useState<any[]>([]);
  const [showQuizContainer, setShowQuizContainer] = useState(false);
  const [quizId, setQuizId] = useState<string>('');

  // Loading state for saved flashcard/quiz sets
  const [loadingSetId, setLoadingSetId] = useState<string | null>(null);

  // 三栏可拖拽宽度（左 / 右，中间 flex 自适应）
  const [leftPanelWidth, setLeftPanelWidth] = useState(256);
  const [rightPanelWidth, setRightPanelWidth] = useState(320);
  const [resizing, setResizing] = useState<'left' | 'right' | null>(null);
  const resizeRef = React.useRef<{ startX: number; startLeft: number; startRight: number } | null>(null);
  React.useEffect(() => {
    if (resizing === null) return;
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    const onMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      const { startX, startLeft, startRight } = resizeRef.current;
      const delta = e.clientX - startX;
      if (resizing === 'left') {
        setLeftPanelWidth(Math.min(480, Math.max(160, startLeft + delta)));
      } else {
        setRightPanelWidth(Math.min(600, Math.max(200, startRight - delta)));
      }
    };
    const onUp = () => {
      setResizing(null);
      resizeRef.current = null;
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [resizing]);

  // Studio tools
  const dataExtractTool = { icon: <BarChart2 className="text-emerald-500" />, label: '智能取数', id: 'data_extract' as ToolType };
  const tableProcessingTool = { icon: <Filter className="text-indigo-500" />, label: '智能处理', id: 'table_processing' as ToolType };
  const studioTools: Array<{icon: React.ReactNode, label: string, id: ToolType}> = [
    dataExtractTool,
    tableProcessingTool,
    { icon: <ImageIcon className="text-orange-500" />, label: 'PPT生成', id: 'ppt' },
    { icon: <BrainCircuit className="text-purple-500" />, label: '思维导图', id: 'mindmap' },
    // DrawIO 图表功能暂时隐藏，后续修复
    // { icon: <LayoutGrid className="text-teal-500" />, label: 'DrawIO 图表', id: 'drawio' },
    { icon: <BookOpen className="text-indigo-500" />, label: '闪卡', id: 'flashcard' },
    { icon: <Brain className="text-blue-500" />, label: '测验', id: 'quiz' },
    { icon: <Mic2 className="text-red-500" />, label: '知识播客', id: 'podcast' },
    { icon: <FileText className="text-green-500" />, label: '笔记', id: 'note' },
    // 视频讲解暂未开放
    // { icon: <VideoIcon className="text-blue-600" />, label: '视频讲解', id: 'video' },
  ];

  // Studio：每个功能卡片各自配置，点卡片上的「…」翻转进该卡片的设置
  type StudioToolId = 'data_extract' | 'table_processing' | 'ppt' | 'mindmap' | 'drawio' | 'flashcard' | 'quiz' | 'podcast' | 'video' | 'note';
  const [studioPanelView, setStudioPanelView] = useState<'tools' | 'settings'>('tools');
  const [studioSettingsTool, setStudioSettingsTool] = useState<StudioToolId | null>(null);
  const STORAGE_STUDIO_CONFIG = `kb_studio_config_${effectiveUser?.id || 'default'}`;
  const defaultByTool: Record<StudioToolId, Record<string, string>> = {
    data_extract: { resultFormat: 'json', executionStrategy: 'auto' },
    table_processing: { resultFormat: 'csv', llmModel: 'gpt-4o' },
    ppt: { llmModel: 'deepseek-v3.2', genFigModel: 'gemini-2.5-flash-image', stylePreset: 'modern', stylePrompt: '', language: 'zh', page_count: '10' },
    mindmap: { llmModel: 'deepseek-v3.2', mindmapStyle: 'default' },
    drawio: { llmModel: 'deepseek-v3.2', diagramType: 'auto', diagramStyle: 'default', language: 'zh' },
    flashcard: { llmModel: 'deepseek-v3.2', language: 'zh', cardCount: '20' },
    quiz: { llmModel: 'deepseek-v3.2', language: 'zh', questionCount: '10' },
    podcast: { llmModel: 'deepseek-v3.2', ttsType: 'qwen-tts-local', ttsModel: 'qwen-tts', voiceName: 'vivian', podcastMode: 'monologue', podcastLanguage: 'zh' },
    video: { llmModel: 'deepseek-v3.2' },
    note: {},
  };
  const [studioConfigByTool, setStudioConfigByTool] = useState<Record<StudioToolId, Record<string, string>>>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_STUDIO_CONFIG);
      if (raw) {
        const parsed = JSON.parse(raw) as Record<string, Record<string, string>>;
        const next = { ...defaultByTool };
        (Object.keys(defaultByTool) as StudioToolId[]).forEach((id) => {
          if (parsed[id] && typeof parsed[id] === 'object') next[id] = { ...defaultByTool[id], ...parsed[id] };
        });
        return next;
      }
    } catch (_) {}
    return { ...defaultByTool };
  });
  const getStudioConfig = (tool: StudioToolId) => studioConfigByTool[tool] || defaultByTool[tool];
  const setStudioConfigForTool = (tool: StudioToolId, patch: Record<string, string>) => {
    setStudioConfigByTool((prev) => {
      const next = { ...prev, [tool]: { ...(prev[tool] || defaultByTool[tool]), ...patch } };
      try {
        localStorage.setItem(STORAGE_STUDIO_CONFIG, JSON.stringify(next));
      } catch (_) {}
      return next;
    });
  };

  // 是否已配置 API（用于鲁棒提醒）
  const apiConfigured = (() => {
    const settings = getApiSettings(effectiveUser?.id || null);
    const url = settings?.apiUrl?.trim();
    const key = settings?.apiKey?.trim();
    return !!(url && key);
  })();

  const getOutputStorageKey = () => {
    const uid = effectiveUser?.id || effectiveUser?.email || '';
    if (!uid) return null;
    if (notebook?.id) return `kb_output_feed_${uid}_${notebook.id}`;
    return `kb_output_feed_${uid}`;
  };

  /** 产出列表是否已完成首次加载（避免刷新时用空数组覆盖 localStorage） */
  const hasLoadedOutputsRef = React.useRef(false);

  // 持久化当前对话到历史（仅在有除 welcome 外的消息时）
  const persistCurrentConversation = (messages: ChatMessage[]) => {
    const list = messages.filter(m => m.id !== 'welcome');
    if (list.length === 0) return;
    const title = (list.find(m => m.role === 'user')?.content || '新对话').slice(0, 30);
    const id = currentConversationId || `conv_${Date.now()}`;
    setCurrentConversationId(id);
    setConversationHistory(prev => {
      const rest = prev.filter(c => c.id !== id);
      const next = [{ id, title, messages, updatedAt: Date.now() }, ...rest];
      saveConversationHistory(next);
      return next;
    });
  };

  const handleNewConversation = () => {
    const list = chatMessages.filter(m => m.id !== 'welcome');
    if (list.length > 0) {
      persistCurrentConversation(chatMessages);
    }
    setCurrentConversationId(null);
    setChatMessages([WELCOME_MSG]);
    setChatSubView('current');
  };

  const handleShowHistory = () => setChatSubView('history');

  const handleRestoreConversation = (item: ConversationItem) => {
    setChatMessages(item.messages);
    setCurrentConversationId(item.id);
    setChatSubView('current');
  };

  const loadLocalOutputFeed = () => {
    const key = getOutputStorageKey();
    if (!key) return [];
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const saveLocalOutputFeed = (items: typeof outputFeed) => {
    const key = getOutputStorageKey();
    if (!key) return;
    localStorage.setItem(key, JSON.stringify(items));
  };

  const inferOutputType = (urlOrName?: string): 'ppt' | 'mindmap' | 'podcast' | 'drawio' | 'flashcard' | 'quiz' => {
    const value = (urlOrName || '').toLowerCase();
    if (value.endsWith('.wav') || value.endsWith('.mp3') || value.endsWith('.m4a')) return 'podcast';
    if (value.endsWith('.mmd') || value.endsWith('.mermaid')) return 'mindmap';
    if (value.endsWith('.drawio')) return 'drawio';
    return 'ppt';
  };

  const getOutputTitle = (type: 'ppt' | 'mindmap' | 'podcast' | 'drawio' | 'flashcard' | 'quiz' | 'note') => {
    if (type === 'mindmap') return '思维导图';
    if (type === 'podcast') return '播客生成';
    if (type === 'drawio') return 'DrawIO 图表';
    if (type === 'flashcard') return '闪卡';
    if (type === 'quiz') return '测验';
    if (type === 'note') return '笔记';
    return 'PPT 生成';
  };

  const handleLoadSavedSet = async (item: typeof outputFeed[number]) => {
    if (!item.setId) {
      showToast('加载失败：该条目没有保存的集合 ID，可能是在持久化功能添加之前创建的。', 'error');
      return;
    }
    setLoadingSetId(item.id);
    try {
      const endpoint = item.type === 'flashcard'
        ? `/api/v1/kb/get-flashcard-set?notebook_id=${encodeURIComponent(notebook.id)}&set_id=${encodeURIComponent(item.setId)}`
        : `/api/v1/kb/get-quiz-set?notebook_id=${encodeURIComponent(notebook.id)}&set_id=${encodeURIComponent(item.setId)}`;
      const res = await apiFetch(endpoint);
      const data = await res.json();
      if (!data.success) throw new Error(data.detail || '加载失败');
      if (item.type === 'flashcard') {
        setFlashcards(data.flashcards || []);
        setFlashcardSetId(data.id || '');
        setShowFlashcardViewer(true);
      } else {
        setQuizQuestions(data.questions || []);
        setQuizId(data.id || '');
        setShowQuizContainer(true);
      }
    } catch (err) {
      console.error('Load saved set error:', err);
      showToast('加载失败，数据可能已被删除。', 'error');
    } finally {
      setLoadingSetId(null);
    }
  };

  const mergeOutputFeeds = (remote: typeof outputFeed, local: typeof outputFeed) => {
    const map = new Map<string, typeof outputFeed[number]>();
    const add = (item: typeof outputFeed[number]) => {
      const key = item.url || item.id;
      if (!key) return;
      const prev = map.get(key);
      if (!prev) {
        map.set(key, item);
        return;
      }
      map.set(key, {
        ...item,
        mermaidCode: prev.mermaidCode || item.mermaidCode,
        setId: prev.setId || item.setId,
      });
    };
    remote.forEach(add);
    local.forEach(add);
    return Array.from(map.values()).sort((a, b) => {
      const aTime = Date.parse(a.createdAt || '') || 0;
      const bTime = Date.parse(b.createdAt || '') || 0;
      return bTime - aTime;
    });
  };

  const fetchOutputHistory = async () => {
    if (!effectiveUser?.email && !effectiveUser?.id) return [];
    const results: typeof outputFeed = [];
    try {
      const params = new URLSearchParams({ email: effectiveUser.email || effectiveUser.id });
      if (notebook?.id) params.set('notebook_id', notebook.id);
      const nbTitle = notebook?.title || notebook?.name || '';
      if (nbTitle) params.set('notebook_title', nbTitle);
      const res = await apiFetch(`/api/v1/kb/outputs?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        console.log('[fetchOutputHistory] Got data from /api/v1/kb/outputs:', data);
        if (data?.success && Array.isArray(data.files)) {
          console.log('[fetchOutputHistory] Processing', data.files.length, 'files');
          for (const item of data.files) {
            const url = item.download_url || item.url || '';
            const type = (item.output_type as 'ppt' | 'mindmap' | 'podcast' | 'drawio' | 'flashcard' | 'quiz') || inferOutputType(item.file_name || url);
            const output = {
              id: item.id || url || `output_${Date.now()}`,
              type,
              title: getOutputTitle(type),
              sources: '历史产出',
              url,
              createdAt: item.created_at ? new Date(item.created_at).toLocaleString() : new Date().toLocaleString(),
              mermaidCode: undefined
            };
            console.log('[fetchOutputHistory] Adding output:', output);
            results.push(output);
          }
        }
      }
    } catch (err) {
      console.error('Failed to load output history:', err);
    }

    // 从专用端点获取闪卡和测验历史
    if (notebook?.id) {
      const nbTitle = notebook?.title || notebook?.name || '';
      const fcParams = new URLSearchParams({ notebook_id: notebook.id, notebook_title: nbTitle });
      const qzParams = new URLSearchParams({ notebook_id: notebook.id, notebook_title: nbTitle });
      const [fcRes, qzRes] = await Promise.all([
        apiFetch(`/api/v1/kb/list-flashcard-sets?${fcParams.toString()}`).catch(() => null),
        apiFetch(`/api/v1/kb/list-quiz-sets?${qzParams.toString()}`).catch(() => null),
      ]);
      if (fcRes?.ok) {
        const fcData = await fcRes.json().catch(() => null);
        if (fcData?.success && Array.isArray(fcData.sets)) {
          for (const s of fcData.sets) {
            results.push({
              id: s.id || `flashcard_${s.set_id}`,
              type: 'flashcard',
              title: getOutputTitle('flashcard'),
              sources: Array.isArray(s.source_files) ? s.source_files.map((f: string) => f.split('/').pop() || f).join(', ') : '历史产出',
              url: '',
              createdAt: s.created_at ? new Date(s.created_at).toLocaleString() : new Date().toLocaleString(),
              setId: s.set_id,
            });
          }
        }
      }
      if (qzRes?.ok) {
        const qzData = await qzRes.json().catch(() => null);
        if (qzData?.success && Array.isArray(qzData.sets)) {
          for (const s of qzData.sets) {
            results.push({
              id: s.id || `quiz_${s.set_id}`,
              type: 'quiz',
              title: getOutputTitle('quiz'),
              sources: Array.isArray(s.source_files) ? s.source_files.map((f: string) => f.split('/').pop() || f).join(', ') : '历史产出',
              url: '',
              createdAt: s.created_at ? new Date(s.created_at).toLocaleString() : new Date().toLocaleString(),
              setId: s.set_id,
            });
          }
        }
      }
    }

    console.log('[fetchOutputHistory] Returning results:', results.length, 'items', results);
    return results;
  };

  const getChatStorageKey = () => {
    if (effectiveUser?.id) return `kb_chat_${effectiveUser.id}`;
    if (effectiveUser?.email) return `kb_chat_${effectiveUser.email}`;
    return 'kb_chat_anonymous';
  };

  const fetchVectorList = async () => {
    const em = effectiveUser?.email || effectiveUser?.id;
    if (!em) return;
    setVectorLoading(true);
    setVectorError('');
    try {
      const params = new URLSearchParams({ email: em });
      if (notebook?.id) params.set('notebook_id', notebook.id);
      const res = await apiFetch(`/api/v1/kb/list?${params.toString()}`);
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || '向量列表获取失败');
      }
      const data = await res.json();
      const files = Array.isArray(data?.files) ? data.files : [];
      const filtered = files.filter((item: any) => item?.status !== 'deleted');
      setVectorFiles(filtered);
      const statusMap: Record<string, string> = {};
      filtered.forEach((item: any) => {
        if (item?.original_path) {
          const key = getOutputsPath(item.original_path);
          // 出现在向量列表里即视为已入库（后端 manifest 可能无 status 字段）
          statusMap[key] = item.status || 'embedded';
        }
      });
      setVectorStatusByPath(statusMap);
    } catch (err: any) {
      setVectorError(err?.message || '向量列表获取失败');
      setVectorFiles([]);
      setVectorStatusByPath({});
    } finally {
      setVectorLoading(false);
    }
  };

  // Force refresh sources list (reset cache)
  const refreshVectorList = async () => {
    lastFetchedNotebookIdForSources.current = null;
    await fetchVectorList();
  };

  // Force refresh outputs list (reset cache)
  const refreshOutputHistory = async () => {
    lastFetchedNotebookIdForOutputs.current = null;
    hasLoadedOutputsRef.current = false;
    const local = loadLocalOutputFeed();
    const remote = await fetchOutputHistory();
    console.log('[refreshOutputHistory] local:', local.length, 'remote:', remote.length);
    const merged = mergeOutputFeeds(remote, local);
    console.log('[refreshOutputHistory] merged:', merged.length, merged);
    setOutputFeed(merged);
    hasLoadedOutputsRef.current = true;
  };

  const getFileNameFromPath = (path?: string) => {
    if (!path) return '';
    const parts = path.split('/');
    return parts[parts.length - 1] || path;
  };

  const getOutputsPath = (originalPath?: string) => {
    if (!originalPath) return '';
    const idx = originalPath.indexOf('/outputs/');
    if (idx >= 0) {
      return originalPath.slice(idx);
    }
    return originalPath;
  };

  const markEmbedded = async (file?: KnowledgeFile, storagePath?: string) => {
    const storageKey = `kb_files_${effectiveUser?.id || 'dev'}`;
    const stored = localStorage.getItem(storageKey);
    const existingFiles = stored ? JSON.parse(stored) : [];
    const updated = existingFiles.map((f: KnowledgeFile) => {
      if (file?.id && f.id === file.id) {
        return { ...f, isEmbedded: true };
      }
      if (storagePath && f.url === storagePath) {
        return { ...f, isEmbedded: true };
      }
      return f;
    });
    localStorage.setItem(storageKey, JSON.stringify(updated));
  };

  const handleReembedVector = async (item: any) => {
    const key = item.id || item.original_path;
    if (!key) return;
    setVectorActionLoading(prev => ({ ...prev, [key]: true }));
    try {
      const settings = getApiSettings(effectiveUser?.id || null);
      let apiUrl = settings?.apiUrl?.trim() || '';
      const apiKey = settings?.apiKey?.trim() || '';
      if (!apiUrl || !apiKey) {
        const msg = '请先在设置中配置 API URL 和 API Key';
        setVectorError(msg);
        showToast(msg, 'warning');
        return;
      }
      if (!apiUrl.includes('/embeddings')) {
        apiUrl = `${apiUrl.replace(/\/$/, '')}/embeddings`;
      }
      const filePath = getOutputsPath(item.original_path);
      if (!filePath) {
        setVectorError('无法获取文件路径');
        return;
      }
      const body: Record<string, unknown> = {
        files: [{ path: filePath, description: '' }],
        api_url: apiUrl,
        api_key: apiKey,
        model_name: retrievalModel
      };
      if (effectiveUser?.email || effectiveUser?.id) body.email = effectiveUser.email || effectiveUser.id;
      if (notebook?.id) body.notebook_id = notebook.id;
      if (notebook?.title || notebook?.name) body.notebook_title = notebook?.title || notebook?.name || '';
      const res = await apiFetch('/api/v1/kb/embedding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        let msg = '重新入库失败';
        try {
          const body = await res.json();
          msg = body?.detail || body?.message || msg;
        } catch {
          msg = await res.text() || msg;
        }
        if (res.status === 401 || (typeof msg === 'string' && msg.includes('401'))) {
          msg = 'API 认证失败（401），请到设置中检查 API Key 是否正确。';
        }
        throw new Error(msg);
      }
      await res.json();
      await refreshVectorList();
      await fetchFiles();
    } catch (err: any) {
      setVectorError(err?.message || '重新入库失败');
    } finally {
      setVectorActionLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  const handleDeleteVector = async (item: any) => {
    const key = item.id || item.original_path;
    if (!key) return;
    if (!confirm('确认删除该向量吗？删除后检索将不再返回该文件内容。')) {
      return;
    }
    setVectorActionLoading(prev => ({ ...prev, [key]: true }));
    try {
      const res = await apiFetch('/api/v1/kb/delete-vector', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: item.id,
          email: effectiveUser?.email || effectiveUser?.id || undefined,
          notebook_id: notebook?.id || undefined
        })
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || '删除向量失败');
      }
      await res.json();
      await refreshVectorList();
    } catch (err: any) {
      setVectorError(err?.message || '删除向量失败');
    } finally {
      setVectorActionLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  // Fetch files from outputs when notebook changes（不做用户管理，数据从 outputs 取）
  useEffect(() => {
    if (notebook?.id) fetchFiles();
  }, [effectiveUser?.id, notebook?.id]);

  useEffect(() => {
    const currentNotebookId = notebook?.id || null;
    if ((effectiveUser?.email || effectiveUser?.id) && lastFetchedNotebookIdForSources.current !== currentNotebookId) {
      lastFetchedNotebookIdForSources.current = currentNotebookId;
      fetchVectorList();
    }
  }, [effectiveUser?.email, effectiveUser?.id, notebook?.id]);

  // Load chat: from API when notebook is set, else from localStorage
  useEffect(() => {
    if (!effectiveUser?.id && !effectiveUser?.email) return;

    const loadFromApi = async () => {
      try {
        const createRes = await apiFetch('/api/v1/kb/conversations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: effectiveUser?.email || effectiveUser?.id || '',
            user_id: effectiveUser?.id || null,
            notebook_id: notebook?.id || null,
          }),
        });
        const createData = await createRes.json();
        const cid = createData?.conversation_id;
        if (!cid) {
          chatPersistSkippedRef.current = true;
          return;
        }
        conversationIdRef.current = cid;
        const msgRes = await apiFetch(`/api/v1/kb/conversations/${cid}/messages`);
        const msgData = await msgRes.json();
        const list = msgData?.messages || [];
        if (list.length > 0) {
          const msgs: ChatMessage[] = [
            { id: 'welcome', role: 'assistant', content: '你好！我是你的知识库助手。请上传文件或在左侧来源区域选择文件，然后在此处进行提问。', time: '' },
            ...list.map((m: any, i: number) => ({
              id: m.id || `msg_${i}`,
              role: m.role as 'user' | 'assistant',
              content: m.content,
              time: m.created_at ? new Date(m.created_at).toLocaleTimeString() : '',
            })),
          ];
          setChatMessages(msgs);
        }
      } catch (e) {
        console.error('Load conversation failed:', e);
      }
      chatPersistSkippedRef.current = true;
    };

    const loadFromStorage = () => {
      const key = getChatStorageKey();
      if (!key) return;
      const raw = localStorage.getItem(key);
      if (!raw) return;
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) setChatMessages(parsed);
      } catch { /* ignore */ }
    };

    if (notebook?.id) {
      loadFromApi();
    } else {
      loadFromStorage();
    }
  }, [effectiveUser?.id, effectiveUser?.email, notebook?.id]);

  // Persist chat to localStorage when not using API (no notebook)
  useEffect(() => {
    if (!chatPersistSkippedRef.current) return;
    if (conversationIdRef.current) return;
    const key = getChatStorageKey();
    if (!key) return;
    localStorage.setItem(key, JSON.stringify(chatMessages));
  }, [chatMessages]);

  // Load output history (server + local)
  useEffect(() => {
    console.log('[useEffect outputs] Triggered, notebook?.id:', notebook?.id, 'effectiveUser:', effectiveUser?.id);
    const currentNotebookId = notebook?.id || null;
    if (lastFetchedNotebookIdForOutputs.current === currentNotebookId && hasLoadedOutputsRef.current) {
      console.log('[useEffect outputs] Skip, already fetched for this notebook');
      return; // Skip if already fetched for this notebook
    }
    console.log('[useEffect outputs] Will fetch outputs');
    hasLoadedOutputsRef.current = false;
    let canceled = false;
    const loadOutputs = async () => {
      try {
        const local = loadLocalOutputFeed();
        const remote = await fetchOutputHistory();
        console.log('[loadOutputs] local:', local.length, 'remote:', remote.length);
        console.log('[loadOutputs] canceled:', canceled);
        if (canceled) {
          console.log('[loadOutputs] Canceled, returning early');
          return;
        }
        const merged = mergeOutputFeeds(remote, local);
        console.log('[loadOutputs] merged:', merged.length, merged);
        setOutputFeed(merged);
        lastFetchedNotebookIdForOutputs.current = currentNotebookId;
        hasLoadedOutputsRef.current = true;
      } catch (error) {
        console.error('[loadOutputs] Error:', error);
      }
    };
    loadOutputs();
    return () => {
      canceled = true;
    };
  }, [effectiveUser?.id, effectiveUser?.email, notebook?.id]);

  // Persist output feed locally (仅在首次加载完成后写入，避免刷新时用 [] 覆盖)
  useEffect(() => {
    if (!hasLoadedOutputsRef.current) return;
    saveLocalOutputFeed(outputFeed);
  }, [outputFeed, effectiveUser?.id, effectiveUser?.email, notebook?.id]);

  // Lazy-load mindmap content for preview
  useEffect(() => {
    if (!previewOutput || previewOutput.type !== 'mindmap' || previewOutput.mermaidCode || !previewOutput.url) {
      setPreviewLoading(false);
      return;
    }
    let canceled = false;
    const loadMermaid = async () => {
      const url = previewOutput.url;
      if (!url) return;
      try {
        setPreviewLoading(true);
        const res = await fetch(url);
        if (!res.ok) throw new Error('读取思维导图失败');
        const text = await res.text();
        if (!canceled) {
          setPreviewOutput(prev => prev ? { ...prev, mermaidCode: text } : prev);
        }
      } catch (err) {
        console.error('Load mindmap failed:', err);
      } finally {
        if (!canceled) setPreviewLoading(false);
      }
    };
    loadMermaid();
    return () => {
      canceled = true;
    };
  }, [previewOutput?.id, previewOutput?.type, previewOutput?.url, previewOutput?.mermaidCode]);

  // DrawIO 预览：从 url 拉取 xml 以在弹窗内嵌编辑
  useEffect(() => {
    if (!previewOutput || previewOutput.type !== 'drawio' || !previewOutput.url) {
      setPreviewDrawioXml(null);
      return;
    }
    let canceled = false;
    setPreviewDrawioXml(null);
    setPreviewLoading(true);
    fetch(previewOutput.url)
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error('Failed to load'))))
      .then((xml) => {
        if (!canceled && xml && xml.includes('<mxfile')) setPreviewDrawioXml(xml);
      })
      .catch(() => {})
      .finally(() => {
        if (!canceled) setPreviewLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, [previewOutput?.id, previewOutput?.type, previewOutput?.url]);

  // 本地笔记本 id 形如 local_xxx，不能作为 Supabase kb_id（UUID）
  const isLocalNotebookId = (id: string) => typeof id === 'string' && id.startsWith('local_');
  // 每个笔记本独立来源：Supabase 用 kb_id；本地用 localStorage key 带 notebookId
  const getFilesStorageKey = () => {
    const uid = effectiveUser?.id || 'default';
    if (notebook?.id) return `kb_files_${uid}_${notebook.id}`;
    return `kb_files_${uid}`;
  };

  const cacheScopeUser = effectiveUser?.id || effectiveUser?.email || 'anonymous';
  const cacheScopeNotebook = notebook?.id || 'no-notebook';
  const encodeCachePart = (value?: string) => encodeURIComponent(value || '');
  const getFilesCacheKey = () => `notebook-files:${encodeCachePart(cacheScopeUser)}:${encodeCachePart(cacheScopeNotebook)}`;
  const getSourceDetailCacheKey = (file: KnowledgeFile) => (
    `source-detail:${encodeCachePart(cacheScopeUser)}:${encodeCachePart(cacheScopeNotebook)}:${encodeCachePart(file.type)}:${encodeCachePart(file.url || file.name)}`
  );
  const invalidateNotebookSourceCaches = () => {
    invalidateCacheByPrefix(`notebook-files:${encodeCachePart(cacheScopeUser)}:${encodeCachePart(cacheScopeNotebook)}`);
    invalidateCacheByPrefix(`source-detail:${encodeCachePart(cacheScopeUser)}:${encodeCachePart(cacheScopeNotebook)}`);
  };

  const fetchFiles = async () => {
    try {
      const mappedFiles = notebook?.id
        ? await fetchWithCache<KnowledgeFile[]>(
            getFilesCacheKey(),
            FILE_LIST_CACHE_TTL_MS,
            async () => {
              const params = new URLSearchParams({
                user_id: effectiveUser.id,
                notebook_id: notebook.id,
                email: effectiveUser.email || effectiveUser.id,
              });
              const res = await apiFetch(`/api/v1/kb/files?${params.toString()}`);
              if (!res.ok) throw new Error('来源列表获取失败');
              const data = await res.json();
              const list = Array.isArray(data?.files) ? data.files : [];
              return list.map((row: any) => ({
                id: row.id || `file-${row.name}`,
                name: row.name,
                type: mapFileType(row.file_type || row.name?.split('.').pop() || ''),
                size: formatSize(row.file_size || 0),
                uploadTime: '',
                isEmbedded: false,
                desc: '',
                url: row.url || row.static_url,
              }));
            },
            { useStaleOnError: true }
          )
        : [];
      setFiles(mappedFiles);
      setSelectedIds(new Set(mappedFiles.map(f => f.id)));
    } catch (err) {
      console.error('Failed to fetch files:', err);
    }
  };

  const mapFileType = (mimeOrExt: string): 'doc' | 'image' | 'video' | 'link' | 'audio' | 'dataset' => {
    if (!mimeOrExt) return 'doc';
    const lower = mimeOrExt.toLowerCase();
    if (lower.includes('csv') || lower.includes('excel') || lower.endsWith('.xlsx') || lower.endsWith('.xls') || lower.endsWith('.db') || lower.endsWith('.sqlite')) return 'dataset';
    if (mimeOrExt.includes('image')) return 'image';
    if (mimeOrExt.includes('video')) return 'video';
    if (mimeOrExt.includes('pdf')) return 'doc';
    if (mimeOrExt === 'link') return 'link';
    return 'doc';
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const isCsvDataExtractFile = (file: KnowledgeFile) => {
    const candidate = `${file.url || ''} ${file.name || ''}`.toLowerCase();
    return candidate.includes('.csv') || candidate.includes('text/csv');
  };

  const selectedCsvFiles = files.filter(
    f => selectedIds.has(f.id) && f.type === 'dataset' && isCsvDataExtractFile(f) && Boolean(f.url)
  );
  const selectedCsvFileUrls = new Set(
    selectedCsvFiles
      .map(file => file.url)
      .filter((url): url is string => Boolean(url))
  );
  const selectedDataExtractDatasources = dataExtractDatasources.filter(ds => selectedCsvFileUrls.has(ds.file_path));
  const activeDataExtractDatasources = selectedCsvFiles.length > 0
    ? selectedDataExtractDatasources
    : dataExtractDatasources;
  const activeDataExtractDatasourceIds = activeDataExtractDatasources.map(ds => ds.datasource_id);
  const activeDataExtractDatasourceKey = activeDataExtractDatasourceIds.join(',');
  const unsyncedSelectedDatasetCount = Math.max(0, selectedCsvFiles.length - selectedDataExtractDatasources.length);
  const selectedDataExtractArtifacts = dataExtractArtifacts.filter(artifact => dataExtractSelectedArtifactIds.has(artifact.id));

  const getDataExtractRequestBase = () => ({
    notebook_id: notebook.id,
    notebook_title: notebook?.title || notebook?.name || '',
    user_id: effectiveUser.id || 'default',
    email: effectiveUser.email || effectiveUser.id || 'default',
  });

  const getDataExtractLLMConfig = () => {
    const settings = getApiSettings(effectiveUser?.id || null);
    return {
      api_url: settings?.apiUrl?.trim() || undefined,
      api_key: settings?.apiKey?.trim() || undefined,
    };
  };

  const mapTurnsToDataExtractMessages = (
    turns: DataExtractTurn[],
    artifacts: DataExtractArtifact[] = [],
  ): DataExtractMessage[] => {
    if (!Array.isArray(turns) || turns.length === 0) {
      return [createDataExtractWelcomeMessage()];
    }
    const artifactById = new Map<string, DataExtractArtifact>();
    artifacts.forEach((artifact) => {
      artifactById.set(artifact.id, artifact);
    });
    return turns.flatMap((turn) => {
      const timeText = turn.created_at ? new Date(turn.created_at).toLocaleTimeString() : new Date().toLocaleTimeString();
      const linkedArtifact = turn.artifact_id ? artifactById.get(turn.artifact_id) : undefined;
      const previewRows = Array.isArray(turn.preview_rows) && turn.preview_rows.length > 0
        ? turn.preview_rows
        : Array.isArray(linkedArtifact?.preview_rows) ? linkedArtifact?.preview_rows : [];
      const previewText = turn.preview_text || linkedArtifact?.preview_text || linkedArtifact?.answer_summary || '';
      return [
        {
          id: `de-user-${turn.id}`,
          role: 'user',
          content: turn.question,
          time: timeText,
          turnId: turn.id,
          artifactId: turn.artifact_id || undefined,
        },
        {
          id: `de-assistant-${turn.id}`,
          role: 'assistant',
          content: turn.answer || previewText || '未返回结果',
          time: timeText,
          turnId: turn.id,
          artifactId: turn.artifact_id || undefined,
          sql: turn.sql || '',
          columns: Array.isArray(turn.columns) ? turn.columns : [],
          rows: Array.isArray(previewRows) ? previewRows : [],
          rowCount: typeof turn.row_count === 'number' ? turn.row_count : 0,
          exportUrl: turn.file_url || linkedArtifact?.file_url || '',
          error: turn.error || null,
        },
      ];
    });
  };

  const resetDataExtractWorkspace = (clearSession = true) => {
    if (clearSession) setDataExtractSessionId(null);
    setDataExtractMessages([createDataExtractWelcomeMessage()]);
    setDataExtractArtifacts([]);
    setDataExtractSelectedArtifactIds(new Set());
    setDataExtractPreviewArtifact(null);
    setDataExtractSubView('current');
  };

  const fetchDataExtractDatasources = async () => {
    if (!notebook?.id) return [];
    try {
      const params = new URLSearchParams({
        notebook_id: notebook.id,
        notebook_title: notebook?.title || notebook?.name || '',
        user_id: effectiveUser.id || 'default',
        email: effectiveUser.email || effectiveUser.id || 'default',
      });
      const res = await apiFetch(`/api/v1/data-extract/datasources?${params.toString()}`);
      if (!res.ok) throw new Error('Failed to load datasources');
      const data = await res.json();
      const list = Array.isArray(data?.datasources) ? data.datasources : [];
      setDataExtractDatasources(list);
      return list;
    } catch (err) {
      console.error('Failed to fetch data extract datasources:', err);
      return [];
    }
  };

  const fetchDataExtractSessions = async () => {
    if (!notebook?.id) return;
    try {
      const params = new URLSearchParams(getDataExtractRequestBase());
      const res = await apiFetch(`/api/v1/data-extract/sessions?${params.toString()}`);
      if (!res.ok) throw new Error('Failed to load data extract sessions');
      const data = await res.json();
      const list = Array.isArray(data?.sessions) ? data.sessions : [];
      setDataExtractSessions(list);
    } catch (err) {
      console.error('Failed to fetch data extract sessions:', err);
    }
  };

  const loadDataExtractSession = async (sessionId: string) => {
    if (!notebook?.id || !sessionId) return;
    setDataExtractHistoryLoading(true);
    try {
      const params = new URLSearchParams(getDataExtractRequestBase());
      const res = await apiFetch(`/api/v1/data-extract/sessions/${sessionId}?${params.toString()}`);
      if (!res.ok) throw new Error('Failed to load data extract session');
      const data = await res.json();
      const session = data?.session as DataExtractSessionSummary | undefined;
      const turns = Array.isArray(data?.turns) ? data.turns as DataExtractTurn[] : [];
      const artifacts = Array.isArray(data?.artifacts) ? data.artifacts as DataExtractArtifact[] : [];
      setDataExtractSessionId(session?.id || sessionId);
      if (session?.primary_datasource_id) {
        setDataExtractDatasourceId(String(session.primary_datasource_id));
      }
      setDataExtractMessages(mapTurnsToDataExtractMessages(turns, artifacts));
      setDataExtractArtifacts(artifacts);
      setDataExtractSelectedArtifactIds(new Set());
      setDataExtractPreviewArtifact(null);
      setDataExtractSubView('current');
      await fetchDataExtractSessions();
    } catch (err) {
      console.error('Failed to load data extract session detail:', err);
      alert('加载历史取数会话失败，请稍后重试');
    } finally {
      setDataExtractHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (notebook?.id) {
      fetchDataExtractDatasources();
      fetchDataExtractSessions();
    } else {
      setDataExtractDatasources([]);
      setDataExtractSessions([]);
      resetDataExtractWorkspace();
    }
  }, [effectiveUser?.id, effectiveUser?.email, notebook?.id]);

  useEffect(() => {
    setDataExtractDatasourceId(prev => {
      if (prev && activeDataExtractDatasources.some(item => String(item.datasource_id) === prev)) return prev;
      return activeDataExtractDatasources[0] ? String(activeDataExtractDatasources[0].datasource_id) : '';
    });
  }, [activeDataExtractDatasourceKey]);

  useEffect(() => {
    resetDataExtractWorkspace();
  }, [activeDataExtractDatasourceKey, notebook?.id]);

  const handleSyncDataExtractSources = async () => {
    if (!notebook?.id) {
      alert('请先创建或选择一个笔记本');
      return;
    }
    if (selectedCsvFiles.length === 0) {
      alert('请先在左侧勾选至少一个 CSV 数据文件');
      return;
    }

    setDataExtractSyncing(true);
    try {
      for (const file of selectedCsvFiles) {
        if (!file.url) {
          throw new Error(`数据文件缺少可访问路径: ${file.name}`);
        }
        const res = await apiFetch('/api/v1/data-extract/datasources/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            notebook_id: notebook.id,
            notebook_title: notebook?.title || notebook?.name || '',
            user_id: effectiveUser.id || 'default',
            email: effectiveUser.email || effectiveUser.id || 'default',
            file_path: file.url,
            display_name: file.name.replace(/\.[^.]+$/, ''),
          }),
        });
        if (!res.ok) {
          const detail = await res.text();
          throw new Error(detail || `同步失败: ${file.name}`);
        }
      }
      await fetchDataExtractDatasources();
      await fetchDataExtractSessions();
      alert('数据源已同步到智能取数模块');
    } catch (err) {
      console.error('Failed to sync data extract datasources:', err);
      alert('数据源同步失败，请重试');
    } finally {
      setDataExtractSyncing(false);
    }
  };

  const ensureDataExtractSession = async (): Promise<string> => {
    if (dataExtractSessionId) return dataExtractSessionId;
    const primaryDatasourceId = dataExtractDatasourceId || (
      activeDataExtractDatasources[0] ? String(activeDataExtractDatasources[0].datasource_id) : ''
    );
    if (!primaryDatasourceId) throw new Error('No datasource selected');

    const res = await apiFetch('/api/v1/data-extract/sessions/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...getDataExtractRequestBase(),
        ...getDataExtractLLMConfig(),
        datasource_id: Number(primaryDatasourceId),
        selected_datasource_ids: activeDataExtractDatasourceIds.length > 1 ? activeDataExtractDatasourceIds : undefined,
        title: `智能取数 - ${new Date().toLocaleString()}`,
      }),
    });
    if (!res.ok) throw new Error('Failed to start session');
    const data = await res.json();
    const sessionId = data?.session?.id;
    if (!sessionId) throw new Error('Session id missing');
    setDataExtractSessionId(sessionId);
    await fetchDataExtractSessions();
    return sessionId;
  };

  const handleDataExtractExport = async (exportUrl?: string) => {
    if (!exportUrl) return;
    try {
      const res = await apiFetch(exportUrl);
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = 'data_extract_export.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      console.error('Export failed:', err);
      alert('导出失败，请重试');
    }
  };

  const handleToggleDataExtractArtifact = (artifactId: string) => {
    setDataExtractSelectedArtifactIds(prev => {
      const next = new Set(prev);
      if (next.has(artifactId)) next.delete(artifactId);
      else next.add(artifactId);
      return next;
    });
  };

  const handleImportDataExtractArtifact = async (artifact: DataExtractArtifact) => {
    if (!notebook?.id) return;
    try {
      const res = await apiFetch(`/api/v1/data-extract/artifacts/${artifact.id}/import-source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(getDataExtractRequestBase()),
      });
      if (!res.ok) throw new Error('Import artifact failed');
      await fetchFiles();
      await fetchDataExtractDatasources();
      await fetchDataExtractSessions();
      if (dataExtractSessionId) await loadDataExtractSession(dataExtractSessionId);
      alert('产出文件已导入到来源');
    } catch (err) {
      console.error('Failed to import data extract artifact:', err);
      alert('导入来源失败，请稍后重试');
    }
  };

  const handleNewDataExtractSession = () => {
    resetDataExtractWorkspace();
    setDataExtractInput('');
  };

  const handleSendDataExtractMessage = async () => {
    if (!dataExtractInput.trim()) return;
    if (!notebook?.id) {
      alert('请先创建或选择一个笔记本');
      return;
    }
    if (!dataExtractSessionId && activeDataExtractDatasourceIds.length === 0) {
      if (selectedCsvFiles.length > 0) {
        showToast('正在同步选中的 CSV 数据源，请稍候...', 'success');
        await handleSyncDataExtractSources();

        const refreshedDatasources = await fetchDataExtractDatasources();
        const selectedCsvFileUrlsSet = new Set(selectedCsvFiles.map(f => f.url).filter((url): url is string => Boolean(url)));
        const refreshedActive = selectedCsvFileUrlsSet.size > 0
          ? refreshedDatasources.filter((ds: DataExtractDatasource) => selectedCsvFileUrlsSet.has(ds.file_path))
          : refreshedDatasources;

        if (refreshedActive.length === 0) {
          alert('同步成功后未检测到数据源，请稍后刷新或检查后再试。');
          return;
        }
      } else {
        alert('请先同步并选择一个数据源');
        return;
      }
    }

    const userMsg: DataExtractMessage = {
      id: `de-user-${Date.now()}`,
      role: 'user',
      content: dataExtractInput,
      time: new Date().toLocaleTimeString(),
    };
    setDataExtractMessages(prev => [...prev, userMsg]);
    setDataExtractInput('');
    setDataExtractLoading(true);

    try {
      const sessionId = await ensureDataExtractSession();
      const cfg = getStudioConfig('data_extract');
      const res = await apiFetch(`/api/v1/data-extract/sessions/${sessionId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...getDataExtractRequestBase(),
          ...getDataExtractLLMConfig(),
          question: userMsg.content,
          result_format: cfg.resultFormat || 'json',
          execution_strategy: cfg.executionStrategy || 'auto',
          selected_datasource_ids: activeDataExtractDatasourceIds.length > 1 ? activeDataExtractDatasourceIds : undefined,
          selected_artifact_ids: dataExtractSelectedArtifactIds.size > 0 ? Array.from(dataExtractSelectedArtifactIds) : undefined,
        }),
      });
      if (!res.ok) throw new Error('Data extract request failed');
      await loadDataExtractSession(sessionId);
      return;
      const data = await res.json();

      const botMsg: DataExtractMessage = {
        id: `de-assistant-${Date.now()}`,
        role: 'assistant',
        content: data.answer || '未返回结果',
        time: new Date().toLocaleTimeString(),
        sql: data.sql || '',
        columns: Array.isArray(data.columns) ? data.columns : [],
        rows: Array.isArray(data.rows) ? data.rows : [],
        rowCount: typeof data.row_count === 'number' ? data.row_count : 0,
        exportUrl: data.export_url || '',
        error: data.error || null,
      };
      setDataExtractMessages(prev => [...prev, botMsg]);
    } catch (err) {
      console.error('Data extract error:', err);
      setDataExtractMessages(prev => [
        ...prev,
        {
          id: `de-error-${Date.now()}`,
          role: 'assistant',
          content: '智能取数执行失败，请检查数据源或稍后重试。',
          time: new Date().toLocaleTimeString(),
          error: 'request_failed',
        },
      ]);
    } finally {
      setDataExtractLoading(false);
    }
  };

  const handleTableProcessing = async () => {
    if (!notebook?.id) {
      alert('请先创建或选择一个笔记本');
      return;
    }
    if (!tableProcessingInput.trim()) {
      alert('请先输入处理指令');
      return;
    }
    if (selectedCsvFiles.length === 0) {
      alert('请先选择至少一个 CSV 数据源');
      return;
    }

    const userMessage: TableProcessingMessage = {
      id: `table-processing-user-${Date.now()}`,
      role: 'user',
      content: tableProcessingInput,
      time: new Date().toLocaleTimeString(),
    };
    setTableProcessingMessages(prev => [...prev, userMessage]);

    setTableProcessingLoading(true);
    setTableProcessingResult(null);

    // 获取 API 配置
    const settings = getApiSettings(effectiveUser?.id || null);
    const apiUrl = settings?.apiUrl?.trim() || '';
    const apiKey = settings?.apiKey?.trim() || '';

    try {
      const tableConfig = getStudioConfig('table_processing');
      const res = await apiFetch('/api/v1/table-processing/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          notebook_title: notebook?.title || notebook?.name || '',
          user_id: effectiveUser.id || 'default',
          email: effectiveUser.email || effectiveUser.id || 'default',
          datasources: selectedCsvFiles.map(f => ({ name: f.name, url: f.url! })),
          instruction: tableProcessingInput,
          output_format: tableProcessingFormat,
          title: '智能表格处理',
          api_key: apiKey || undefined,
          api_url: apiUrl || undefined,
          model: tableConfig.llmModel || 'gpt-4o',
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || 'Table processing failed');
      }
      const data = await res.json();
      setTableProcessingResult(data);

      // 成功时固定返回"处理成功！"，失败时显示错误信息
      const assistantContent = data?.success === false
        ? (data?.content || data?.error || '处理失败，请稍后重试')
        : '处理成功！';

      const assistantMessage: TableProcessingMessage = {
        id: `table-processing-assistant-${Date.now()}`,
        role: 'assistant',
        content: assistantContent,
        time: new Date().toLocaleTimeString(),
        sql: typeof data?.sql === 'string' ? data.sql : undefined,
        columns: Array.isArray(data?.columns) ? data.columns : undefined,
        rows: Array.isArray(data?.rows) ? data.rows : undefined,
        rowCount: typeof data?.row_count === 'number'
          ? data.row_count
          : typeof data?.rowCount === 'number'
            ? data.rowCount
            : undefined,
        exportUrl: typeof data?.processed_file_url === 'string' ? data.processed_file_url : undefined,
      };
      setTableProcessingMessages(prev => [...prev, assistantMessage]);

      setTableProcessingSessions(prev => [
        {
          id: `${Date.now()}`,
          title: `智能处理 ${new Date().toLocaleString()}`,
          updated_at: new Date().toISOString(),
          instruction: tableProcessingInput,
        },
        ...prev,
      ]);
      setTableProcessingSubView('current');
      showToast('表格处理完成', 'success');
    } catch (error) {
      console.error('Table processing error:', error);
      const errMsg = (error as any)?.message || String(error);
      setTableProcessingMessages(prev => [...prev, {
        id: `table-processing-assistant-error-${Date.now()}`,
        role: 'assistant',
        content: `处理失败：${errMsg}`,
        time: new Date().toLocaleTimeString(),
      }]);
      showToast('表格处理失败，请检查日志', 'error');
    } finally {
      setTableProcessingLoading(false);
      setTableProcessingInput('');
    }
  };

  const handleNewTableProcessingSession = () => {
    setTableProcessingSubView('current');
    setTableProcessingInput('');
    setTableProcessingMessages([
      { id: 'table-processing-welcome', role: 'assistant', content: '选择 CSV 数据源后，输入自然语言指令进行智能处理。', time: new Date().toLocaleTimeString() }
    ]);
    setTableProcessingResult(null);
  };

  const handleShowTableProcessingHistory = () => {
    setTableProcessingSubView('history');
  };

  const handleToggleSelect = (id: string) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    setSelectedIds(newSet);
  };

  const upsertFileInList = (file: KnowledgeFile) => {
    setFiles(prev => [
      file,
      ...prev.filter(existing => {
        if (file.id && existing.id === file.id) return false;
        if (file.url && existing.url === file.url) return false;
        return true;
      }),
    ]);
    setSelectedIds(prev => new Set([...prev, file.id]));
  };

  const removePendingSource = (pendingId: string) => {
    setPendingSources(prev => prev.filter(item => item.id !== pendingId));
  };

  const markPendingSourceError = (pendingId: string, message: string) => {
    setPendingSources(prev => prev.map(item => (
      item.id === pendingId
        ? { ...item, status: 'error', message }
        : item
    )));
  };

  /** PDF / .md 等可解析为正文并预览 */
  const isPreviewableDoc = (f: KnowledgeFile) => {
    const name = (f.name || '').toLowerCase();
    const url = (f.url || '').toLowerCase();
    return (name.endsWith('.pdf') || name.endsWith('.md')) || (url.endsWith('.pdf') || url.endsWith('.md'));
  };

  const normalizeCitationPath = (value?: string) => {
    if (!value) return '';
    const normalized = value.replace(/\\/g, '/');
    const outputsIdx = normalized.indexOf('/outputs/');
    return outputsIdx >= 0 ? normalized.slice(outputsIdx) : normalized;
  };

  const findFileForCitation = (ref: CitationReference) => {
    const targetPath = normalizeCitationPath(ref.filePath);
    return files.find((file) => {
      const filePath = normalizeCitationPath(file.url);
      if (targetPath && filePath && targetPath === filePath) return true;
      return file.name === ref.fileName;
    }) || null;
  };

  const openSourceDetail = async (file: KnowledgeFile, citationFocus?: CitationReference | null) => {
    setSourceDetailView(file);
    setSourceDetailContent('');
    setSourceDetailFormat('text');
    setSourceDetailLoading(false);
    setSourceDetailCitationFocus(citationFocus ?? null);
    if (file.type === 'link' && file.url && (file.url.startsWith('http://') || file.url.startsWith('https://'))) {
      setSourceDetailLoading(true);
      try {
        const detail = await fetchWithCache<SourceDetailCacheEntry>(
          getSourceDetailCacheKey(file),
          SOURCE_DETAIL_CACHE_TTL_MS,
          async () => {
            const res = await apiFetch('/api/v1/kb/fetch-page-content', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url: file.url })
            });
            if (!res.ok) {
              return { content: '[抓取失败]', format: 'text' };
            }
            const data = await res.json();
            return { content: data?.content ?? '[无内容]', format: 'text' };
          },
          { useStaleOnError: true }
        );
        setSourceDetailContent(detail.content);
        setSourceDetailFormat(detail.format);
      } catch {
        setSourceDetailContent('[请求失败]');
        setSourceDetailFormat('text');
      } finally {
        setSourceDetailLoading(false);
      }
    } else if (isPreviewableDoc(file) && file.url && (file.url.startsWith('/outputs/') || file.url.startsWith('/'))) {
      setSourceDetailLoading(true);
      try {
        const detail = await fetchWithCache<SourceDetailCacheEntry>(
          getSourceDetailCacheKey(file),
          SOURCE_DETAIL_CACHE_TTL_MS,
          async () => {
            const displayRes = await apiFetch('/api/v1/kb/get-source-display-content', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: file.url })
            });
            if (displayRes.ok) {
              const displayData = await displayRes.json();
              if (displayData?.from_mineru && displayData?.content != null) {
                return { content: displayData.content, format: 'markdown' };
              }
            }
            const res = await apiFetch('/api/v1/kb/parse-local-file', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path_or_url: file.url })
            });
            if (!res.ok) {
              return { content: '[解析失败]', format: 'text' };
            }
            const data = await res.json();
            return {
              content: data?.content ?? '[无内容]',
              format: (data?.format === 'markdown' ? 'markdown' : 'text') as 'text' | 'markdown',
            };
          },
          { useStaleOnError: true }
        );
        setSourceDetailContent(detail.content);
        setSourceDetailFormat(detail.format);
      } catch {
        setSourceDetailContent('[请求失败]');
        setSourceDetailFormat('text');
      } finally {
        setSourceDetailLoading(false);
      }
    } else if (file.url && (file.url.startsWith('http') || file.url.startsWith('/'))) {
      setSourceDetailContent(`[文件预览] ${file.name}\n\n可在新标签页打开: ${file.url}`);
    } else {
      setSourceDetailContent(`[暂无解析预览] ${file.name}`);
    }
  };

  const handleCitationClick = async (
    citationNumber: string,
    sourceReferenceMapping?: Record<string, CitationReference>
  ) => {
    const ref = sourceReferenceMapping?.[citationNumber];
    if (!ref) return;
    const targetFile = findFileForCitation(ref);
    if (!targetFile) return;
    setSelectedIds(prev => {
      if (prev.has(targetFile.id)) return prev;
      const next = new Set(prev);
      next.add(targetFile.id);
      return next;
    });
    await openSourceDetail(targetFile, { ...ref, sourceNumber: citationNumber });
  };

  React.useEffect(() => {
    if (!sourceDetailCitationFocus || sourceDetailLoading) return;
    const timer = window.setTimeout(() => {
      sourceDetailCitationRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [sourceDetailCitationFocus, sourceDetailLoading, sourceDetailContent]);

  const runFastResearch = async () => {
    if (!fastResearchQuery.trim()) return;
    const settings = getApiSettings(effectiveUser?.id || null);
    const searchProvider = (settings?.searchProvider as 'serper' | 'serpapi' | 'bocha') || 'serper';
    const searchEngine = (settings?.searchEngine as 'google' | 'baidu') || 'google';
    const searchApiKey = settings?.searchApiKey?.trim() ?? '';
    if ((searchProvider === 'serpapi' || searchProvider === 'bocha') && !searchApiKey) {
      setFastResearchError('请先在右上角「设置」中配置搜索 API Key');
      return;
    }
    setFastResearchLoading(true);
    setFastResearchError('');
    setFastResearchSources([]);
    setFastResearchSelected(new Set());
    try {
      const body: Record<string, unknown> = {
        query: fastResearchQuery.trim(),
        top_k: 10,
        search_provider: searchProvider,
        search_engine: searchEngine,
      };
      body.search_api_key = searchApiKey;
      const res = await apiFetch('/api/v1/kb/fast-research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || 'Fast Research 请求失败');
      }
      const data = await res.json();
      const sources = data?.sources || [];
      setFastResearchSources(sources);
      setFastResearchSelected(new Set(sources.map((_: any, i: number) => i)));
    } catch (err: any) {
      setFastResearchError(err?.message || '搜索失败');
    } finally {
      setFastResearchLoading(false);
    }
  };

  const importFastResearchSources = async () => {
    const items = Array.from(fastResearchSelected)
      .map(i => fastResearchSources[i])
      .filter(Boolean)
      .map(({ title, link, snippet }) => ({ title, link, snippet }));
    if (items.length === 0) return;
    if (!notebook?.id || !effectiveUser?.email) {
      showToast('请先选择笔记本并登录', 'warning');
      return;
    }
    setImportingSources(true);
    try {
      const res = await apiFetch('/api/v1/kb/import-link-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          email: effectiveUser.email || effectiveUser.id,
          user_id: effectiveUser.id,
          notebook_title: notebook?.title || notebook?.name || '',
          items
        })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || '导入失败');
      }
      const data = await res.json();
      invalidateNotebookSourceCaches();
      await fetchFiles();
      await refreshVectorList();
      setFastResearchSources([]);
      setFastResearchSelected(new Set());
      const embeddedMsg = data?.embedded ? `，已向量化 ${data.embedded} 个` : '';
      showToast(`已导入 ${data?.imported ?? items.length} 个来源${embeddedMsg}`, 'success');
    } catch (err: any) {
      showToast(err?.message || '导入失败', 'error');
    } finally {
      setImportingSources(false);
    }
  };

  const handleImportUrlAsSource = async () => {
    const url = introduceUrl.trim();
    if (!url) {
      setIntroduceUrlError('请输入网页 URL');
      return;
    }
    if (!notebook?.id || !effectiveUser?.email) {
      setIntroduceUrlError('请先选择笔记本');
      return;
    }
    setIntroduceUrlError('');
    setIntroduceUrlLoading(true);
    try {
      const res = await apiFetch('/api/v1/kb/import-url-as-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          email: effectiveUser.email || effectiveUser.id,
          user_id: effectiveUser.id,
          notebook_title: notebook?.title || notebook?.name || '',
          url,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || '抓取失败');
      }
      const data = await res.json();
      const newFile: KnowledgeFile = {
        id: data.id || `file-${data.filename}`,
        name: data.filename,
        type: 'doc',
        size: typeof data.file_size === 'number' ? formatSize(data.file_size) : '',
        uploadTime: '',
        isEmbedded: false,
        desc: '',
        url: data.static_url || '',
      };
      setFiles(prev => [newFile, ...prev.filter(f => f.id !== newFile.id)]);
      setSelectedIds(prev => new Set([...prev, newFile.id]));
      invalidateNotebookSourceCaches();
      await fetchFiles();
      setIntroduceUrl('');
      setIntroduceUrlSuccess('已抓取并加入来源');
      setTimeout(() => setIntroduceUrlSuccess(''), 3000);
    } catch (err: any) {
      setIntroduceUrlError(err?.message || '抓取失败');
    } finally {
      setIntroduceUrlLoading(false);
    }
  };

  const handleAddTextSource = async () => {
    const content = introduceText.trim();
    if (!content) {
      setIntroduceTextError('请输入或粘贴文字');
      return;
    }
    if (!notebook?.id || !effectiveUser?.email) {
      setIntroduceTextError('请先选择笔记本');
      return;
    }
    setIntroduceTextError('');
    setIntroduceTextLoading(true);
    try {
      const res = await apiFetch('/api/v1/kb/add-text-source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notebook_id: notebook.id,
          email: effectiveUser.email || effectiveUser.id,
          user_id: effectiveUser.id,
          notebook_title: notebook?.title || notebook?.name || '',
          title: '直接输入',
          content,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || '添加失败');
      }
      const data = await res.json();
      const newFile: KnowledgeFile = {
        id: data.id || `file-${data.filename}`,
        name: data.filename,
        type: 'doc',
        size: typeof data.file_size === 'number' ? formatSize(data.file_size) : '',
        uploadTime: '',
        isEmbedded: false,
        desc: '',
        url: data.static_url || '',
      };
      setFiles(prev => [newFile, ...prev.filter(f => f.id !== newFile.id)]);
      setSelectedIds(prev => new Set([...prev, newFile.id]));
      invalidateNotebookSourceCaches();
      await fetchFiles();
      setIntroduceText('');
      setIntroduceTextSuccess('已添加为来源');
      setTimeout(() => setIntroduceTextSuccess(''), 3000);
    } catch (err: any) {
      setIntroduceTextError(err?.message || '添加失败');
    } finally {
      setIntroduceTextLoading(false);
    }
  };

  const runDeepResearchReport = async () => {
    if (!deepResearchTopic.trim()) return;
    const settings = getApiSettings(effectiveUser?.id || null);
    const apiUrl = settings?.apiUrl?.trim() || '';
    const apiKey = settings?.apiKey?.trim() || '';
    const searchProvider = (settings?.searchProvider as 'serper' | 'serpapi' | 'bocha') || 'serper';
    const searchEngine = (settings?.searchEngine as 'google' | 'baidu') || 'google';
    const searchApiKey = settings?.searchApiKey?.trim() ?? '';
    if (!apiUrl || !apiKey) {
      setDeepResearchError('请先在设置中配置 API');
      return;
    }
    if (!searchApiKey) {
      setDeepResearchError('请先在设置中配置搜索 API Key');
      return;
    }
    if (!notebook?.id || !effectiveUser?.email) {
      setDeepResearchError('请先选择笔记本');
      return;
    }
    setDeepResearchLoading(true);
    setDeepResearchError('');
    try {
      const res = await apiFetch('/api/v1/kb/generate-deep-research-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: deepResearchTopic.trim(),
          user_id: effectiveUser.id,
          email: effectiveUser.email || effectiveUser.id,
          notebook_id: notebook.id,
          notebook_title: notebook?.title || notebook?.name || '',
          api_url: apiUrl,
          api_key: apiKey,
          language: 'zh',
          add_as_source: true,
          search_provider: searchProvider,
          search_api_key: searchApiKey,
          search_engine: searchEngine,
          search_top_k: 10
        })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || '生成报告失败');
      }
      const data = await res.json();
      if (data.added_as_source && data.added_file) {
        const row = data.added_file;
        const newFile: KnowledgeFile = {
          id: row.id || `file-${row.name}`,
          name: row.name,
          type: 'doc',
          size: typeof row.file_size === 'number' ? formatSize(row.file_size) : '',
          uploadTime: '',
          isEmbedded: false,
          desc: '',
          url: row.url || row.static_url || '',
        };
        setFiles(prev => [newFile, ...prev.filter(f => f.id !== newFile.id)]);
        setSelectedIds(prev => new Set([...prev, newFile.id]));
      }
      invalidateNotebookSourceCaches();
      await fetchFiles();
      setDeepResearchTopic('');
      setDeepResearchSuccess({
        topic: deepResearchTopic.trim(),
        pdfUrl: data?.pdf_url || data?.report_url,
      });
    } catch (err: any) {
      setDeepResearchError(err?.message || '生成失败');
    } finally {
      setDeepResearchLoading(false);
    }
  };

  const getPptDownloadUrl = (data: any) => {
    let url = data?.pptx_path || data?.pdf_path || data?.ppt_url;
    if (!url && data?.result_path && typeof data.result_path === 'string') {
      const idx = data.result_path.indexOf('/outputs/');
      if (idx !== -1) {
        const base = data.result_path.slice(idx).replace(/\/$/, '');
        url = `${base}/paper2ppt.pdf`;
      }
    }
    return url;
  };

  const uploadFiles = async (
    inputFiles: FileList | File[],
    options?: { closeModalOnQueue?: boolean }
  ) => {
    const uploadQueue = Array.from(inputFiles || []);
    if (!uploadQueue.length) return;
    if (!notebook?.id) {
      showToast('请先选择或创建一个笔记本再上传文件', 'warning');
      return;
    }

    const queuedSources: PendingSourceItem[] = uploadQueue.map((file, index) => ({
      id: `pending-upload-${Date.now()}-${index}-${file.name}`,
      name: file.name,
      sourceType: 'upload',
      status: 'processing',
    }));

    setPendingSources(prev => [...queuedSources, ...prev]);
    if (options?.closeModalOnQueue) {
      setShowIntroduceModal(false);
    }
    setFileUploading(true);
    showToast(
      uploadQueue.length > 1
        ? `已添加 ${uploadQueue.length} 个文件，正在处理`
        : `已添加 ${uploadQueue[0].name}，正在处理`,
      'success'
    );

    let successCount = 0;
    let failureCount = 0;
    let embeddedCount = 0;

    try {
      for (let i = 0; i < uploadQueue.length; i += 1) {
        const file = uploadQueue[i];
        const pendingItem = queuedSources[i];
        const formData = new FormData();
        formData.append('file', file);
        formData.append('email', effectiveUser.email || effectiveUser.id || 'default');
        formData.append('user_id', effectiveUser.id || 'default');
        formData.append('notebook_id', notebook.id);
        formData.append('notebook_title', notebook?.title || notebook?.name || '');

        try {
          const res = await apiFetch('/api/v1/kb/upload', {
            method: 'POST',
            body: formData
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data?.detail || data?.message || `上传 ${file.name} 失败`);
          }

          const newFile: KnowledgeFile = {
            id: data.id || data.storage_path || `file-${data.filename || file.name}`,
            name: data.filename || file.name,
            type: mapFileType(data.file_type || file.type || file.name.split('.').pop() || ''),
            size: typeof data.file_size === 'number' ? formatSize(data.file_size) : formatSize(file.size || 0),
            uploadTime: '',
            isEmbedded: !!data.embedded,
            desc: '',
            url: data.static_url || '',
          };

          removePendingSource(pendingItem.id);
          upsertFileInList(newFile);
          successCount += 1;
          if (data.embedded) embeddedCount += 1;
        } catch (err: any) {
          const msg = err?.message || `上传 ${file.name} 失败`;
          console.error('Upload error:', err);
          markPendingSourceError(pendingItem.id, msg);
          setRetrievalError(msg);
          failureCount += 1;
        }
      }

      if (successCount > 0) {
        invalidateNotebookSourceCaches();
        await fetchFiles();
        await refreshVectorList();
        if (failureCount === 0) {
          showToast(
            embeddedCount === successCount
              ? `已完成 ${successCount} 个来源导入并入库`
              : `已完成 ${successCount} 个来源导入`,
            'success'
          );
        } else {
          showToast(`已完成 ${successCount} 个来源导入，${failureCount} 个失败`, 'warning');
        }
      } else if (failureCount > 0) {
        showToast(`上传失败：${failureCount} 个文件未处理成功`, 'error');
      }
    } finally {
      setFileUploading(false);
    }
  };

  // Chat handler
  const handleSendMessage = async () => {
    if (!inputMsg.trim()) return;
    
    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: inputMsg,
      time: new Date().toLocaleTimeString()
    };
    
    setChatMessages(prev => [...prev, userMsg]);
    setInputMsg('');
    setIsChatLoading(true);
    setChatLoadingStage('正在准备来源...');

    try {
      if (selectedIds.size === 0) {
        const botMsg: ChatMessage = {
          id: Date.now().toString(),
          role: 'assistant',
          content: '请先在左侧来源列表中勾选至少一个文件，我才能基于这些资料回答您的问题。',
          time: new Date().toLocaleTimeString()
        };
        setChatMessages(prev => [...prev, botMsg]);
        persistCurrentConversation([...chatMessages, userMsg, botMsg]);
        setIsChatLoading(false);
        return;
      }

      const selectedFiles = files
        .filter(f => selectedIds.has(f.id))
        .map(f => f.url)
        .filter(Boolean);
      
      const history = chatMessages.filter(m => m.id !== 'welcome').map(m => ({
        role: m.role,
        content: m.content
      }));

      const settings = getApiSettings(effectiveUser?.id || null);
      const assistantMessageId = (Date.now() + 1).toString();
      const assistantTime = new Date().toLocaleTimeString();
      let streamedContent = '';
      let streamedDetails: ChatMessage['details'] | undefined;
      let streamedSourceMapping: ChatMessage['sourceMapping'] | undefined;
      let streamedSourcePreviewMapping: ChatMessage['sourcePreviewMapping'] | undefined;
      let streamedSourceReferenceMapping: ChatMessage['sourceReferenceMapping'] | undefined;

      const syncAssistantMessage = () => {
        setChatMessages(prev => prev.map(msg => (
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: streamedContent,
                details: streamedDetails,
                sourceMapping: streamedSourceMapping,
                sourcePreviewMapping: streamedSourcePreviewMapping,
                sourceReferenceMapping: streamedSourceReferenceMapping,
              }
            : msg
        )));
      };

      setChatMessages(prev => [...prev, {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        time: assistantTime,
      }]);

      const res = await apiFetch('/api/v1/kb/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          files: selectedFiles,
          query: userMsg.content,
          history: history,
          email: effectiveUser?.email || effectiveUser?.id || undefined,
          notebook_id: notebook?.id || undefined,
          api_url: settings?.apiUrl?.trim() || undefined,
          api_key: settings?.apiKey?.trim() || undefined
        })
      });

      if (!res.ok) throw new Error("Chat request failed");
      if (!res.body) throw new Error("Chat stream not available");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processEvent = (rawLine: string) => {
        const line = rawLine.trim();
        if (!line) return;
        const event = JSON.parse(line);
        if (event.type === 'meta') {
          streamedDetails = event.file_analyses || undefined;
          streamedSourceMapping = event.source_mapping || undefined;
          streamedSourcePreviewMapping = event.source_preview_mapping || undefined;
          streamedSourceReferenceMapping = event.source_reference_mapping || undefined;
          syncAssistantMessage();
          return;
        }
        if (event.type === 'stage') {
          setChatLoadingStage(event.message || '思考中...');
          return;
        }
        if (event.type === 'delta') {
          if (!streamedContent) setChatLoadingStage('正在生成回答...');
          streamedContent += event.delta || '';
          syncAssistantMessage();
          return;
        }
        if (event.type === 'done') {
          if (typeof event.answer === 'string' && event.answer.length >= streamedContent.length) {
            streamedContent = event.answer;
            syncAssistantMessage();
          }
          return;
        }
        if (event.type === 'error') {
          throw new Error(event.message || 'Chat stream failed');
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          processEvent(line);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) processEvent(buffer);

      const botMsg: ChatMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: streamedContent || "抱歉，我无法回答这个问题。",
        time: assistantTime,
        details: streamedDetails,
        sourceMapping: streamedSourceMapping,
        sourcePreviewMapping: streamedSourcePreviewMapping,
        sourceReferenceMapping: streamedSourceReferenceMapping
      };
      setChatMessages(prev => prev.map(msg => msg.id === assistantMessageId ? botMsg : msg));
      persistCurrentConversation([...chatMessages, userMsg, botMsg]);

      const cid = conversationIdRef.current;
      if (cid) {
        apiFetch(`/api/v1/kb/conversations/${cid}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: [
              { role: 'user', content: userMsg.content },
              { role: 'assistant', content: botMsg.content },
            ],
          }),
        }).catch(() => {});
      }
    } catch (err) {
      console.error("Chat error:", err);
      const errorContent = err instanceof Error ? err.message : "发生错误，请稍后重试。";
      const errorMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: errorContent || "发生错误，请稍后重试。",
        time: new Date().toLocaleTimeString()
      };
      setChatMessages(prev => {
        const emptyAssistant = prev.find(msg => msg.role === 'assistant' && !msg.content.trim());
        if (!emptyAssistant) return [...prev, errorMsg];
        return prev.map(msg => msg.id === emptyAssistant.id ? errorMsg : msg);
      });
      persistCurrentConversation([...chatMessages, userMsg, errorMsg]);
    } finally {
      setIsChatLoading(false);
      setChatLoadingStage('思考中...');
    }
  };

  // Tool handlers (PPT, Mindmap, etc.)
  const handleToolGenerate = async (tool: ToolType) => {
    if (selectedIds.size === 0) {
      showToast('请先选择至少一个文件', 'warning');
      return;
    }

    setToolLoading(true);
    setToolOutput(null);

    try {
      const selectedFiles = files.filter(f => selectedIds.has(f.id));
      const selectedFileUrls = selectedFiles.map(f => f.url).filter(Boolean) as string[];
      const selectedNames = selectedFiles.map(f => f.name).filter(Boolean);

      const settings = getApiSettings(user?.id || null);
      const apiUrl = settings?.apiUrl?.trim() || '';
      const apiKey = settings?.apiKey?.trim() || '';
      if (!apiUrl || !apiKey) {
        showToast('请先在设置中配置 API URL 和 API Key', 'warning');
        setToolLoading(false);
        return;
      }

      let endpoint = '';
      const baseBody: any = {
        user_id: effectiveUser?.id || 'default',
        email: effectiveUser?.email || effectiveUser?.id || 'default',
        notebook_id: notebook?.id || undefined,
        notebook_title: notebook?.title || notebook?.name || '',
        api_url: apiUrl,
        api_key: apiKey
      };

      switch (tool) {
        case 'table_processing':
          setActiveTool('table_processing');
          setToolLoading(false);
          return;
        case 'mindmap':
          endpoint = '/api/v1/kb/generate-mindmap';
          break;
        case 'ppt':
          endpoint = '/api/v1/kb/generate-ppt';
          break;
        case 'podcast':
          endpoint = '/api/v1/kb/generate-podcast';
          break;
        case 'drawio':
          endpoint = '/api/v1/kb/generate-drawio';
          break;
        case 'flashcard':
          endpoint = '/api/v1/kb/generate-flashcards';
          break;
        case 'quiz':
          endpoint = '/api/v1/kb/generate-quiz';
          break;
        default:
          throw new Error('Unsupported tool');
      }

      let bodyData: any = { ...baseBody };
      if (tool === 'ppt') {
        const docFiles = selectedFiles.filter(f => f.type === 'doc');
        const linkFiles = selectedFiles.filter(f => f.type === 'link');
        const imageFiles = selectedFiles.filter(f => f.type === 'image');
        const validDocFiles = docFiles.filter(f => {
          const name = (f.name || '').toLowerCase();
          return name.endsWith('.pdf') || name.endsWith('.pptx') || name.endsWith('.ppt') || name.endsWith('.docx') || name.endsWith('.doc') || name.endsWith('.md');
        });
        const validSources = [...validDocFiles, ...linkFiles];
        if (validSources.length === 0) {
          showToast('请至少选择 1 个文档或网页来源进行生成（支持 PDF/PPTX/DOCX/MD 或网页引入）。', 'warning');
          setToolLoading(false);
          return;
        }
        const docPaths = validSources.map(f => f.url).filter(Boolean) as string[];
        if (docPaths.length !== validSources.length) {
          showToast('无法获取文档/网页路径，请重试。', 'error');
          setToolLoading(false);
          return;
        }
        const imageItems = imageFiles
          .map(f => ({ path: f.url, description: f.desc || '' }))
          .filter(item => Boolean(item.path));

        const getStyleDescription = (preset: string): string => {
          const styles: Record<string, string> = {
            modern: '现代简约风格，使用干净的线条和充足的留白',
            business: '商务专业风格，稳重大气，适合企业演示',
            academic: '学术报告风格，清晰的层次结构，适合论文汇报',
            creative: '创意设计风格，活泼生动，色彩丰富',
          };
          return styles[preset] || styles.modern;
        };
        const cfg = getStudioConfig('ppt');
        const styleText = (cfg.stylePrompt || '').trim()
          ? cfg.stylePrompt.trim()
          : getStyleDescription(cfg.stylePreset || 'modern');

        bodyData = {
          ...baseBody,
          file_paths: docPaths,
          image_items: imageItems,
          query: '',
          need_embedding: false,
          style: styleText,
          language: cfg.language || 'zh',
          page_count: Math.max(1, Math.min(50, parseInt(String(cfg.page_count || '10'), 10) || 10)),
          model: cfg.llmModel || 'deepseek-v3.2',
          gen_fig_model: cfg.genFigModel || 'gemini-2.5-flash-image'
        };
      } else if (tool === 'podcast') {
        const cfg = getStudioConfig('podcast');
        bodyData = {
          ...baseBody,
          file_paths: selectedFileUrls,
          model: cfg.llmModel || 'deepseek-v3.2',
          tts_model: cfg.ttsModel || 'qwen-tts',
          voice_name: cfg.voiceName || 'vivian',
          voice_name_b: cfg.voiceNameB || 'uncle_fu',
          podcast_mode: cfg.podcastMode || 'monologue',
          language: cfg.podcastLanguage || 'zh'
        };
      } else if (tool === 'mindmap') {
        const cfg = getStudioConfig('mindmap');
        bodyData = {
          ...baseBody,
          file_paths: selectedFileUrls,
          model: cfg.llmModel || 'deepseek-v3.2',
          mindmap_style: cfg.mindmapStyle || 'default',
        };
      } else if (tool === 'drawio') {
        const cfg = getStudioConfig('drawio');
        bodyData = {
          ...baseBody,
          file_paths: selectedFileUrls,
          model: cfg.llmModel || 'deepseek-v3.2',
          diagram_type: cfg.diagramType || 'auto',
          diagram_style: cfg.diagramStyle || 'default',
          language: cfg.language || 'zh',
        };
      } else if (tool === 'flashcard') {
        const cfg = getStudioConfig('flashcard');
        bodyData = {
          ...baseBody,
          file_paths: selectedFileUrls,
          model: cfg.llmModel || 'deepseek-v3.2',
          language: cfg.language || 'zh',
          card_count: Math.max(5, Math.min(50, parseInt(String(cfg.cardCount || '20'), 10) || 20)),
        };
      } else if (tool === 'quiz') {
        const cfg = getStudioConfig('quiz');
        bodyData = {
          ...baseBody,
          file_paths: selectedFileUrls,
          model: cfg.llmModel || 'deepseek-v3.2',
          language: cfg.language || 'zh',
          question_count: Math.max(5, Math.min(30, parseInt(String(cfg.questionCount || '10'), 10) || 10)),
        };
      } else {
        bodyData = {
          ...baseBody,
          file_paths: selectedFileUrls
        };
      }

      const res = await apiFetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(bodyData)
      });

      if (!res.ok) throw new Error('Generation failed');

      const data = await res.json();
      setToolOutput(data);
      
      // 保存到产出信息流
      const now = new Date().toLocaleString();
      if (tool === 'ppt') {
        const pdfUrl = data?.pdf_path;
        const pptxUrl = data?.pptx_path || data?.ppt_url;
        const downloadUrl = data?.download_url || pptxUrl || pdfUrl;
        setOutputFeed(prev => [
          {
            id: data.output_file_id || `ppt_${Date.now()}`,
            type: 'ppt',
            title: 'PPT 生成',
            sources: selectedNames.length ? selectedNames.join('、') : `来源 ${selectedIds.size}`,
            url: downloadUrl,
            previewUrl: pdfUrl,
            createdAt: now,
          },
          ...prev,
        ]);
      } else       if (tool === 'mindmap') {
        const url = data.mindmap_path || data.result_path;
        const mermaidCode = data.mermaid_code || data.mindmap_code || '';
        const outputItem = {
          id: data.output_file_id || `mindmap_${Date.now()}`,
          type: 'mindmap' as const,
          title: '思维导图',
          sources: selectedNames.length ? selectedNames.join('、') : `来源 ${selectedIds.size}`,
          url,
          createdAt: now,
          mermaidCode
        };
        setOutputFeed(prev => [outputItem, ...prev]);
        // 同时在工具输出区域显示
        setToolOutput({ ...data, mermaid_code: mermaidCode });
      } else if (tool === 'podcast') {
        const url = data.audio_path || data.audio_url;
        setOutputFeed(prev => [
          {
            id: data.output_file_id || `podcast_${Date.now()}`,
            type: 'podcast',
            title: '播客生成',
            sources: selectedNames.length ? selectedNames.join('、') : `来源 ${selectedIds.size}`,
            url,
            createdAt: now,
          },
          ...prev,
        ]);
      } else if (tool === 'drawio') {
        const url = data.file_path;
        setOutputFeed(prev => [
          {
            id: data.output_file_id || `drawio_${Date.now()}`,
            type: 'drawio',
            title: 'DrawIO 图表',
            sources: selectedNames.length ? selectedNames.join('、') : `来源 ${selectedIds.size}`,
            url,
            createdAt: now,
          },
          ...prev,
        ]);
      } else if (tool === 'flashcard') {
        setFlashcards(data.flashcards || []);
        setFlashcardSetId(data.flashcard_set_id || '');
        if (data.flashcards?.length) setShowFlashcardViewer(true);
        const fcSetId = (data.flashcard_set_id || '').replace('flashcard_', '');
        setOutputFeed(prev => [
          {
            id: data.flashcard_set_id || `flashcard_${Date.now()}`,
            type: 'flashcard',
            title: '闪卡',
            sources: selectedNames.length ? selectedNames.join('、') : `来源 ${selectedIds.size}`,
            url: '',
            createdAt: now,
            setId: fcSetId || String(Date.now()),
          },
          ...prev,
        ]);
      } else if (tool === 'quiz') {
        setQuizQuestions(data.questions || []);
        setQuizId(data.quiz_id || '');
        if (data.questions?.length) setShowQuizContainer(true);
        const qzSetId = (data.quiz_id || '').replace('quiz_', '');
        setOutputFeed(prev => [
          {
            id: data.quiz_id || `quiz_${Date.now()}`,
            type: 'quiz',
            title: '测验',
            sources: selectedNames.length ? selectedNames.join('、') : `来源 ${selectedIds.size}`,
            url: '',
            createdAt: now,
            setId: qzSetId || String(Date.now()),
          },
          ...prev,
        ]);
      }

    } catch (err) {
      console.error('Tool generation error:', err);
      showToast('生成失败，请重试', 'error');
    } finally {
      setToolLoading(false);
    }
  };

  const escapeHtml = (text: string) =>
    text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

  const renderKatex = (tex: string, displayMode: boolean) => {
    try {
      return katex.renderToString(tex, { displayMode, throwOnError: false });
    } catch {
      return `<code>${escapeHtml(tex)}</code>`;
    }
  };

  const renderTooltipText = (text: string) => {
    if (!text) return '';
    const mathSlots: string[] = [];
    let processed = text;
    // 处理 \(...\) 行内公式
    processed = processed.replace(/\\\((.+?)\\\)/g, (_m, tex) => {
      mathSlots.push(renderKatex(tex, false));
      return `\x00MATH${mathSlots.length - 1}\x00`;
    });
    // 处理 \[...\] 块级公式
    processed = processed.replace(/\\\[(.+?)\\\]/g, (_m, tex) => {
      mathSlots.push(renderKatex(tex, true));
      return `\x00MATH${mathSlots.length - 1}\x00`;
    });
    // 转义HTML
    processed = escapeHtml(processed);
    // 还原公式
    processed = processed.replace(/\x00MATH(\d+)\x00/g, (_m, idx) => mathSlots[Number(idx)]);
    return processed;
  };

  const renderInline = (
    text: string,
    sourceMapping?: Record<string, string>,
    sourcePreviewMapping?: Record<string, string>,
    sourceReferenceMapping?: Record<string, CitationReference>
  ) => {
    // 1) 先提取行内公式，支持 $...$ 和 \(...\) 格式
    const mathSlots: string[] = [];
    let protected_ = text
      .replace(/\\\((.+?)\\\)/g, (_m, tex) => {
        mathSlots.push(renderKatex(tex, false));
        return `\x00MATH${mathSlots.length - 1}\x00`;
      })
      .replace(/\$([^$\n]+?)\$/g, (_m, tex) => {
        mathSlots.push(renderKatex(tex, false));
        return `\x00MATH${mathSlots.length - 1}\x00`;
      });
    // 2) 正常 escapeHtml + markdown 处理
    let html = escapeHtml(protected_);
    html = html.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 rounded bg-gray-100 text-gray-800 font-mono text-xs">$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer" class="text-blue-600 hover:text-blue-500 underline">$1</a>');
    // Highlight numbered citation markers [1], [2], etc. with hover tooltip showing file name + chunk preview
    html = html.replace(/\[(\d{1,2})\]/g, (_match, num) => {
      const hasSource = sourceReferenceMapping?.[num] || sourceMapping?.[num];
      return `<sup class="cite-ref" data-cite="${num}"${hasSource ? ' data-source-tooltip="1"' : ''} style="background-color:#dbeafe;color:#1d4ed8;padding:1px 5px;border-radius:4px;font-size:0.75em;font-weight:600;margin:0 1px;cursor:pointer;position:relative;">[${num}]</sup>`;
    });
    // 3) 还原公式占位符
    html = html.replace(/\x00MATH(\d+)\x00/g, (_m, idx) => mathSlots[Number(idx)]);
    return html;
  };

  const renderMarkdownToHtml = (
    content: string,
    sourceMapping?: Record<string, string>,
    sourcePreviewMapping?: Record<string, string>,
    sourceReferenceMapping?: Record<string, CitationReference>
  ) => {
    if (!content) return '';
    // 先提取块级公式，支持 $$...$$ 和 \[...\] 格式
    const blockMathSlots: string[] = [];
    let processed = content
      .replace(/\\\[([\s\S]+?)\\\]/g, (_m, tex) => {
        blockMathSlots.push(`<div class="my-3 overflow-x-auto text-center">${renderKatex(tex.trim(), true)}</div>`);
        return `\n%%BLOCKMATH${blockMathSlots.length - 1}%%\n`;
      })
      .replace(/\$\$([\s\S]+?)\$\$/g, (_m, tex) => {
        blockMathSlots.push(`<div class="my-3 overflow-x-auto text-center">${renderKatex(tex.trim(), true)}</div>`);
        return `\n%%BLOCKMATH${blockMathSlots.length - 1}%%\n`;
      });
    const codeBlockRegex = /```([a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let html = '';
    let match: RegExpExecArray | null;

    const processTextBlock = (block: string) => {
      const lines = block.split('\n');
      let blockHtml = '';
      let inUl = false;
      let inOl = false;

      const closeLists = () => {
        if (inUl) {
          blockHtml += '</ul>';
          inUl = false;
        }
        if (inOl) {
          blockHtml += '</ol>';
          inOl = false;
        }
      };

      for (const line of lines) {
        const trimmed = line.trim();

        const headingMatch = /^(#{1,6})\s+(.+)$/.exec(trimmed);
        if (headingMatch) {
          closeLists();
          const level = headingMatch[1].length;
          const headingText = renderInline(headingMatch[2], sourceMapping, sourcePreviewMapping, sourceReferenceMapping);
          blockHtml += `<h${level} class="font-semibold text-gray-900 mt-3 mb-2">${headingText}</h${level}>`;
          continue;
        }

        if (/^[-*]\s+/.test(trimmed)) {
          if (!inUl) {
            closeLists();
            blockHtml += '<ul class="list-disc pl-5 space-y-1">';
            inUl = true;
          }
          blockHtml += `<li>${renderInline(trimmed.replace(/^[-*]\s+/, ''), sourceMapping, sourcePreviewMapping, sourceReferenceMapping)}</li>`;
          continue;
        }

        if (/^\d+\.\s+/.test(trimmed)) {
          if (!inOl) {
            closeLists();
            blockHtml += '<ol class="list-decimal pl-5 space-y-1">';
            inOl = true;
          }
          blockHtml += `<li>${renderInline(trimmed.replace(/^\d+\.\s+/, ''), sourceMapping, sourcePreviewMapping, sourceReferenceMapping)}</li>`;
          continue;
        }

        if (!trimmed) {
          closeLists();
          blockHtml += '<div class="h-2"></div>';
          continue;
        }

        closeLists();
        blockHtml += `<p class="my-1">${renderInline(line, sourceMapping, sourcePreviewMapping, sourceReferenceMapping)}</p>`;
      }

      closeLists();
      return blockHtml;
    };

    while ((match = codeBlockRegex.exec(processed)) !== null) {
      const before = processed.slice(lastIndex, match.index);
      html += processTextBlock(before);
      const code = escapeHtml(match[2].replace(/\s+$/, ''));
      html += `<pre class="bg-gray-100 border border-gray-200 rounded-lg p-3 my-2 overflow-x-auto text-xs"><code class="text-gray-800 font-mono whitespace-pre">${code}</code></pre>`;
      lastIndex = match.index + match[0].length;
    }

    html += processTextBlock(processed.slice(lastIndex));
    // 还原块级公式占位符
    html = html.replace(/%%BLOCKMATH(\d+)%%/g, (_m, idx) => blockMathSlots[Number(idx)]);
    return html;
  };

  const MarkdownContent = ({
    content,
    sourceMapping,
    sourcePreviewMapping,
    sourceReferenceMapping,
  }: {
    content: string;
    sourceMapping?: Record<string, string>;
    sourcePreviewMapping?: Record<string, string>;
    sourceReferenceMapping?: Record<string, CitationReference>;
  }) => (
    <div
      className="text-sm leading-relaxed text-gray-700"
      onClick={(event) => {
        const target = event.target as HTMLElement | null;
        const citeEl = target?.closest('.cite-ref[data-cite]') as HTMLElement | null;
        if (!citeEl) return;
        const citationNumber = citeEl.dataset.cite;
        if (!citationNumber) return;
        event.preventDefault();
        event.stopPropagation();
        void handleCitationClick(citationNumber, sourceReferenceMapping);
      }}
      onMouseMove={(event) => {
        const target = event.target as HTMLElement | null;
        const citeEl = target?.closest('.cite-ref[data-cite]') as HTMLElement | null;
        if (!citeEl) {
          if (hoveredCitation) setHoveredCitation(null);
          return;
        }
        const citationNumber = citeEl.dataset.cite;
        if (!citationNumber) {
          if (hoveredCitation) setHoveredCitation(null);
          return;
        }
        const ref = sourceReferenceMapping?.[citationNumber];
        const title = ref?.fileName || sourceMapping?.[citationNumber] || '';
        const preview = ref?.preview || sourcePreviewMapping?.[citationNumber] || '';
        if (!title && !preview) {
          if (hoveredCitation) setHoveredCitation(null);
          return;
        }
        setHoveredCitation({
          title,
          preview,
          x: event.clientX,
          y: event.clientY - 18,
        });
      }}
      onMouseLeave={() => setHoveredCitation(null)}
      onMouseOver={(event) => {
        const target = event.target as HTMLElement | null;
        const citeEl = target?.closest('.cite-ref[data-cite]') as HTMLElement | null;
        if (!citeEl) {
          setHoveredCitation(null);
          return;
        }
        const citationNumber = citeEl.dataset.cite;
        if (!citationNumber) {
          setHoveredCitation(null);
          return;
        }
        const ref = sourceReferenceMapping?.[citationNumber];
        const title = ref?.fileName || sourceMapping?.[citationNumber] || '';
        const preview = ref?.preview || sourcePreviewMapping?.[citationNumber] || '';
        if (!title && !preview) {
          setHoveredCitation(null);
          return;
        }
        const rect = citeEl.getBoundingClientRect();
        setHoveredCitation({
          title,
          preview,
          x: rect.left + rect.width / 2,
          y: rect.top - 12,
        });
      }}
      dangerouslySetInnerHTML={{ __html: renderMarkdownToHtml(content, sourceMapping, sourcePreviewMapping, sourceReferenceMapping) }}
    />
  );

  /** 将可能带后端的完整 URL 转为同源路径，避免跨域 fetch/打开导致失败或崩溃 */
  const getSameOriginUrl = (url?: string) => {
    if (!url || typeof url !== 'string') return '';
    const trimmed = url.trim();
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
      try {
        const u = new URL(trimmed);
        return u.pathname + u.search;
      } catch {
        return trimmed;
      }
    }
    return trimmed;
  };

  const tooltipViewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280;
  const tooltipLeft = hoveredCitation
    ? Math.min(Math.max(hoveredCitation.x, 220), tooltipViewportWidth - 220)
    : 220;

  return (
    <>
      {ToastContainer}
      <div className="h-screen flex flex-col bg-[#f8f9fa] overflow-hidden">
      {/* Citation tooltip styles */}
      <style>{`
        .cite-ref[data-source-tooltip] {
          transition: background-color 0.15s ease;
        }
        .cite-ref[data-source-tooltip]:hover {
          background-color: #bfdbfe !important;
        }
        @keyframes citeTooltipIn {
          from { opacity: 0; transform: translateX(-50%) translateY(4px); }
          to   { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
      `}</style>
      {hoveredCitation && (
        <div
          className="fixed z-[80] pointer-events-none"
          style={{
            left: `${tooltipLeft}px`,
            top: `${Math.max(hoveredCitation.y, 24)}px`,
            transform: 'translate(-50%, -100%)',
          }}
        >
          <div
            className="w-[min(640px,calc(100vw-32px))] rounded-xl px-4 py-3 text-left shadow-[0_12px_30px_rgba(15,23,42,0.36)]"
            style={{
              backgroundColor: '#0f172a',
              border: '1px solid #334155',
            }}
          >
            <div
              className="rounded-lg px-3 py-2 text-[13px] font-bold leading-snug break-words"
              style={{
                backgroundColor: '#1e293b',
                color: '#ffffff',
              }}
            >
              {hoveredCitation.title}
            </div>
            {hoveredCitation.preview && (
              <div
                className="mt-3 pt-3"
                style={{
                  borderTop: '1px solid #334155',
                }}
              >
                <div
                  className="max-h-[70vh] overflow-y-auto pr-2 text-[14px] leading-6 whitespace-pre-wrap break-words"
                  style={{
                    color: '#e2e8f0',
                    opacity: 1,
                    scrollbarWidth: 'thin',
                    scrollbarColor: '#475569 #1e293b',
                  }}
                  dangerouslySetInnerHTML={{ __html: renderTooltipText(hoveredCitation.preview) }}
                />
              </div>
            )}
          </div>
          <div className="mx-auto h-0 w-0 border-x-[6px] border-t-[7px] border-x-transparent" style={{ borderTopColor: '#0f172a' }} />
        </div>
      )}
      {/* Header */}
      <header className="h-14 glass border-b border-white/30 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-4">
          <motion.button whileTap={{ scale: 0.9 }} onClick={onBack} className="p-2 hover:bg-white/50 rounded-ios text-ios-gray-600 transition-colors">
            <ChevronLeft size={20} />
          </motion.button>
          <img src="/logo_small.png" alt="Logo" className="h-8 w-auto object-contain" />
          <h1 className="font-medium text-ios-gray-900 truncate max-w-[300px]">
            {notebook?.title || 'Semantic Rewards for Low-Resource Language Alignment'}
          </h1>
        </div>

        <div className="flex items-center gap-2">
          {/* 右上方添加笔记 - 暂未使用，先注释
          <button className="flex items-center gap-1.5 px-3 py-1.5 bg-black text-white rounded-full text-sm font-medium hover:bg-gray-800 transition-colors">
            <Plus size={16} />
            创建笔记本
          </button>
          */}
          {/* 右侧上方分析和分享 - 暂未使用，先注释
          <button className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-full text-sm font-medium transition-colors">
            <BarChart2 size={16} />
            分析
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-full text-sm font-medium transition-colors">
            <Share2 size={16} />
            分享
          </button>
          */}
          <motion.button
            whileTap={{ scale: 0.9 }}
            onClick={() => setShowSettingsModal(true)}
            className="p-2 hover:bg-white/50 rounded-ios transition-colors"
            title="API 设置"
          >
            <Settings size={20} className="text-ios-gray-500" />
          </motion.button>
          <div className="h-4 w-[1px] bg-ios-gray-200 mx-1"></div>
          <div className="text-xs font-medium bg-ios-gray-100 px-2 py-0.5 rounded-ios text-ios-gray-500 uppercase tracking-tight">PRO</div>
          <div className="w-8 h-8 bg-gradient-to-br from-primary to-blue-600 rounded-full flex items-center justify-center text-white ml-2 text-xs font-bold shadow-ios-sm">
            {(effectiveUser?.email || effectiveUser?.id || 'U').charAt(0).toUpperCase()}
          </div>
        </div>
      </header>

      {/* Main Content Area: 三栏可拖拽调整宽度 */}
      <div className="flex-1 flex overflow-hidden min-w-0">
        {/* Left Sidebar: Sources */}
        <aside
          className="bg-ios-gray-50 border-r border-ios-gray-100/60 flex flex-col p-4 shrink-0 overflow-hidden"
          style={{ width: leftPanelWidth, minWidth: 160, maxWidth: 480 }}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-ios-gray-700">来源 ({sourceListCount})</h2>
            <button className="p-1 hover:bg-ios-gray-200 rounded-ios">
              <MoreVertical size={16} />
            </button>
          </div>
          
          <div className="mb-4">
            <motion.button
              whileTap={{ scale: 0.95 }}
              type="button"
              onClick={() => setShowIntroduceModal(true)}
              className={`w-full flex items-center justify-center gap-2 py-3.5 px-4 border rounded-2xl text-sm font-semibold transition-all ${
                fileUploading
                  ? 'border-blue-200 bg-blue-50 text-blue-700 shadow-ios-sm'
                  : 'border-ios-gray-200 bg-white text-ios-gray-700 hover:shadow-ios-sm hover:bg-ios-gray-50'
              }`}
            >
              {fileUploading ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
              {fileUploading ? '添加来源中...' : '添加来源'}
            </motion.button>
            <p className="mt-2 px-1 text-xs text-ios-gray-500">
              {processingUploadCount > 0
                ? `正在处理 ${processingUploadCount} 个文件，完成后会自动加入来源列表`
                : '上传文件、网页或粘贴文本到当前笔记本'}
            </p>
          </div>

          {retrievalError && (
            <div className="mb-3 px-3 py-2.5 bg-red-50 border border-red-100 rounded-lg space-y-1.5">
              <p className="text-xs text-red-700 line-clamp-2">{retrievalError}</p>
              <div className="flex items-center gap-2 flex-wrap">
                {(retrievalError.includes('API') || retrievalError.includes('配置') || retrievalError.includes('生成向量失败')) && (
                  <button
                    type="button"
                    onClick={() => { setRetrievalError(''); setShowSettingsModal(true); }}
                    className="text-xs font-medium text-red-600 hover:text-red-800 underline"
                  >
                    去设置
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setRetrievalError('')}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  关闭
                </button>
              </div>
            </div>
          )}

          {!sourceDetailView ? (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-ios-gray-500 uppercase tracking-wider">
                  {selectedIds.size > 0 ? `已选 ${selectedIds.size} 个` : '全部来源'}
                </span>
                <input
                  type="checkbox"
                  className="rounded-full text-primary accent-primary"
                  checked={selectedIds.size === files.length && files.length > 0}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedIds(new Set(files.map(f => f.id)));
                    } else {
                      setSelectedIds(new Set());
                    }
                  }}
                />
              </div>

              <div className="flex-1 overflow-y-auto min-h-0">
                {sourceListCount === 0 ? (
                  <div className="text-center py-8 text-ios-gray-400 text-sm">
                    暂无来源，请添加
                  </div>
                ) : (
                  <>
                    {pendingSources.map((item, itemIdx) => (
                      <motion.div
                        key={item.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: itemIdx * 0.03, type: 'spring', stiffness: 300, damping: 25 }}
                        className={`flex items-center gap-3 p-3 border rounded-ios-xl mb-2 transition-all ${
                          item.status === 'error'
                            ? 'bg-red-50 border-red-200'
                            : 'bg-white border-blue-100 shadow-[0_8px_24px_rgba(59,130,246,0.08)]'
                        }`}
                      >
                        <div className={`w-8 h-8 rounded-ios flex items-center justify-center shrink-0 ${
                          item.status === 'error'
                            ? 'bg-red-100 text-red-600'
                            : 'bg-blue-50 text-blue-600'
                        }`}>
                          {item.status === 'error'
                            ? <X size={16} />
                            : <Loader2 size={16} className="animate-spin" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-xs text-ios-gray-700 line-clamp-2 leading-tight">
                            {item.name}
                          </div>
                          <div className="mt-1 flex items-center gap-2">
                            <span className={`text-[10px] px-2 py-0.5 rounded-full ${
                              item.status === 'error'
                                ? 'bg-red-100 text-red-700'
                                : 'bg-blue-50 text-blue-700'
                            }`}>
                              {item.status === 'error' ? '处理失败' : '处理中'}
                            </span>
                            {item.message && (
                              <span className="text-[10px] text-red-600 truncate" title={item.message}>
                                {item.message}
                              </span>
                            )}
                          </div>
                        </div>
                        {item.status === 'error' && (
                          <button
                            type="button"
                            onClick={() => removePendingSource(item.id)}
                            className="text-xs text-red-600 hover:text-red-800 shrink-0"
                          >
                            移除
                          </button>
                        )}
                      </motion.div>
                    ))}

                    {files.map((file, fileIdx) => (
                      <motion.div
                        key={file.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: (pendingSources.length + fileIdx) * 0.03, type: 'spring', stiffness: 300, damping: 25 }}
                        className="flex items-center gap-3 p-3 bg-white border border-ios-gray-100 rounded-ios-xl mb-2 hover:shadow-ios-sm transition-all cursor-pointer"
                        onClick={() => openSourceDetail(file)}
                      >
                        <div className="w-8 h-8 bg-gradient-to-br from-primary/15 to-blue-100 rounded-ios flex items-center justify-center shrink-0">
                          <span className="text-xs font-bold text-primary">{pendingSources.length + fileIdx + 1}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-xs text-ios-gray-700 line-clamp-2 leading-tight">
                            {file.name}
                          </div>
                          <div className="mt-1 flex items-center gap-2">
                            {(file.isEmbedded || file.kbFileId || vectorStatusByPath[getOutputsPath(file.url)] === 'embedded' || vectorFiles.some((v: any) => getOutputsPath(v?.original_path) === getOutputsPath(file.url))) && (
                              <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-50 text-green-600">
                                已入库
                              </span>
                            )}
                          </div>
                        </div>
                        <input
                          type="checkbox"
                          className="rounded-full text-primary accent-primary"
                          checked={selectedIds.has(file.id)}
                          onChange={() => {
                            setSelectedIds(prev => {
                              const next = new Set(prev);
                              if (next.has(file.id)) next.delete(file.id);
                              else next.add(file.id);
                              return next;
                            });
                          }}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </motion.div>
                    ))}
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col min-h-0">
              <button
                type="button"
                onClick={() => { setSourceDetailView(null); setSourceDetailCitationFocus(null); }}
                className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 mb-2"
              >
                <ChevronLeft size={18} />
                返回
              </button>
              <div className="text-xs font-medium text-gray-700 truncate mb-1" title={sourceDetailView.name}>
                {sourceDetailView.name}
              </div>
              {sourceDetailView.url && (
                <a
                  href={sourceDetailView.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-600 hover:underline mb-2 block truncate"
                >
                  可在新标签页打开
                </a>
              )}
              <div className="flex-1 min-h-0 overflow-y-auto bg-white border border-gray-200 rounded-xl p-3">
                {sourceDetailCitationFocus && (
                  <div
                    ref={sourceDetailCitationRef}
                    className="mb-3 rounded-xl border border-blue-200 bg-blue-50/80 px-3 py-2.5 shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">
                        引用 [{sourceDetailCitationFocus.sourceNumber}]
                      </span>
                      {typeof sourceDetailCitationFocus.chunkIndex === 'number' && (
                        <span className="text-[11px] text-blue-600">
                          Chunk #{sourceDetailCitationFocus.chunkIndex + 1}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs font-semibold text-slate-800">
                      {sourceDetailCitationFocus.fileName}
                    </p>
                    {sourceDetailCitationFocus.preview && (
                      <p className="mt-1 text-xs leading-relaxed text-slate-700">
                        {sourceDetailCitationFocus.preview}
                      </p>
                    )}
                  </div>
                )}
                {sourceDetailLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 size={24} className="animate-spin text-blue-500" />
                    <span className="ml-2 text-sm text-gray-500">解析中…</span>
                  </div>
                ) : sourceDetailFormat === 'markdown' && sourceDetailContent ? (
                  <div className="prose prose-sm max-w-none text-gray-700 prose-p:text-xs prose-headings:text-sm prose-pre:text-xs">
                    <ReactMarkdown>{sourceDetailContent}</ReactMarkdown>
                  </div>
                ) : (
                  <pre className="whitespace-pre-wrap text-xs text-gray-700 font-sans leading-relaxed break-words">
                    {sourceDetailContent || '[无内容]'}
                  </pre>
                )}
              </div>
            </div>
          )}
        </aside>

        {/* 左-中 拖拽条 */}
        <div
          role="separator"
          aria-orientation="vertical"
          className="w-1 shrink-0 bg-ios-gray-100/60 hover:bg-primary/40 active:bg-primary cursor-col-resize transition-colors flex items-center justify-center group"
          onMouseDown={(e) => {
            e.preventDefault();
            setResizing('left');
            resizeRef.current = { startX: e.clientX, startLeft: leftPanelWidth, startRight: rightPanelWidth };
          }}
        >
          <span className="w-0.5 h-8 bg-ios-gray-300 group-hover:bg-primary rounded-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
        </div>

        {/* Center: Chat/Content Area */}
        {activeTool === 'note' ? (
          <div className="flex-1 flex overflow-hidden">
            <NotionEditor
              onClose={() => {
                setActiveTool('chat');
                setEditingNote(null);
              }}
              notebook={notebook}
              user={effectiveUser}
              files={files}
              onSaved={() => {
                setEditingNote(null);
                setTimeout(() => fetchFiles(), 1000);
              }}
              initialTitle={editingNote?.title}
              initialBlocks={editingNote?.blocks}
            />
          </div>
        ) : activeTool === 'table_processing' ? (
          <main className="flex-1 flex flex-col relative bg-white min-w-[300px] overflow-hidden">
            <div className="flex items-center justify-between px-6 py-3 border-b border-ios-gray-100 shrink-0">
              <div>
                <span className="text-sm font-medium text-ios-gray-900">智能处理</span>
                <p className="text-xs text-ios-gray-400 mt-1">根据自然语言处理选中表格并返回结果</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleNewTableProcessingSession}
                  className="px-3 py-1.5 text-sm font-medium rounded-ios border border-ios-gray-200 text-ios-gray-700 hover:bg-ios-gray-50"
                >
                  新建对话
                </button>
                <button
                  type="button"
                  onClick={handleShowTableProcessingHistory}
                  className="px-3 py-1.5 text-sm font-medium rounded-ios border border-ios-gray-200 text-ios-gray-700 hover:bg-ios-gray-50"
                >
                  对话历史
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-8">
              {tableProcessingSubView === 'history' ? (
                <div className="max-w-[900px] mx-auto w-full">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-gray-500">智能处理历史</h3>
                    <button
                      type="button"
                      onClick={() => setTableProcessingSubView('current')}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      返回当前
                    </button>
                  </div>
                  {tableProcessingSessions.length === 0 ? (
                    <div className="rounded-2xl border border-ios-gray-100 bg-white px-4 py-6 text-sm text-ios-gray-400">暂无历史记录</div>
                  ) : (
                    <ul className="space-y-2">
                      {tableProcessingSessions.map(session => (
                        <li key={session.id}>
                          <button
                            type="button"
                            onClick={() => {
                              setTableProcessingSubView('current');
                              setTableProcessingInput(session.instruction);
                              setTableProcessingResult(null);
                            }}
                            className="w-full text-left rounded-2xl border border-ios-gray-100 bg-white px-4 py-3 hover:border-blue-300 hover:bg-blue-50/40 transition-colors"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <div className="text-sm font-medium text-ios-gray-900">{session.title}</div>
                                <div className="mt-1 text-xs text-ios-gray-500">{new Date(session.updated_at).toLocaleString()}</div>
                              </div>
                              <span className="text-xs text-ios-gray-400">指令：{session.instruction}</span>
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <div className="max-w-[900px] mx-auto space-y-4">
                  {selectedCsvFiles.length > 0 && (
                    <div className="mb-4 p-3 bg-green-100 border border-green-300 rounded-lg">
                      <p className="text-green-800 font-semibold">已选 CSV 文件:</p>
                      <ul className="list-disc list-inside mt-2">
                        {selectedCsvFiles.map((file, index) => (
                          <li key={index} className="text-green-700">{file.name}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="space-y-3">
                    {tableProcessingMessages.map(msg => (
                      <div
                        key={msg.id}
                        className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
                      >
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 shadow-ios-sm ${msg.role === 'assistant' ? 'bg-gradient-to-br from-indigo-100 to-indigo-200 text-indigo-700' : 'bg-gradient-to-br from-ios-gray-200 to-ios-gray-300 text-ios-gray-600'}`}>
                          {msg.role === 'assistant' ? <Bot size={16} /> : <User size={16} />}
                        </div>
                        <div className={`max-w-[90%] px-4 py-3 text-sm leading-relaxed shadow-ios-sm ${msg.role === 'assistant' ? 'bg-ios-gray-50 text-ios-gray-700 rounded-2xl rounded-tr-md' : 'bg-blue-600 text-white rounded-2xl rounded-tl-md'}`}>
                          <div>{msg.content}</div>
                          {msg.sql && (
                            <pre className="mt-2 overflow-x-auto rounded-xl bg-slate-950 px-3 py-3 text-xs text-slate-100">{msg.sql}</pre>
                          )}
                          {msg.role === 'assistant' && msg.rows && msg.rows.length > 0 && (
                            <div className="mt-3">
                              <div className="overflow-x-auto rounded-lg border border-ios-gray-200">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="bg-ios-gray-100">
                                      {msg.columns?.map((col, i) => (
                                        <th key={i} className="px-3 py-2 text-left font-medium text-ios-gray-700 whitespace-nowrap">{col}</th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {msg.rows.slice(0, 10).map((row, rowIdx) => (
                                      <tr key={rowIdx} className="border-t border-ios-gray-100 hover:bg-ios-gray-50">
                                        {msg.columns?.map((col, colIdx) => (
                                          <td key={colIdx} className="px-3 py-2 text-ios-gray-600 whitespace-nowrap">{String(row?.[col] ?? '')}</td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              {msg.rows.length > 10 && (
                                <p className="mt-1 text-xs text-ios-gray-400">显示前 10 行</p>
                              )}
                            </div>
                          )}
                          {msg.role === 'assistant' && msg.exportUrl && (
                            <div className="mt-3 flex items-center gap-3">
                              <button
                                type="button"
                                onClick={() => handleDataExtractExport(msg.exportUrl)}
                                className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-700 hover:text-indigo-800"
                              >
                                <Download size={14} />
                                导出 CSV
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            {tableProcessingSubView === 'current' && (
              <div className="px-6 pb-6 shrink-0">
                <div className="max-w-[900px] mx-auto relative">
                  <div className="glass rounded-ios-xl border border-white/30 shadow-ios-sm">
                    <input
                      type="text"
                      value={tableProcessingInput}
                      onChange={e => setTableProcessingInput(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleTableProcessing()}
                      placeholder={selectedCsvFiles.length > 0 ? '输入表格处理指令，例如：按城市分组并求销售总额前 20' : '请先选择 CSV 数据源'}
                      disabled={selectedCsvFiles.length === 0}
                      className="w-full bg-transparent rounded-ios-xl py-4 pl-6 pr-24 text-lg focus:outline-none disabled:opacity-50"
                    />
                    <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
                      <motion.button
                        whileTap={{ scale: 0.88 }}
                        onClick={handleTableProcessing}
                        disabled={!tableProcessingInput.trim() || tableProcessingLoading || selectedCsvFiles.length === 0}
                        className="p-2 bg-indigo-600 text-white rounded-full hover:bg-indigo-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-ios-sm"
                      >
                        {tableProcessingLoading ? '执行中...' : '发送'}
                      </motion.button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </main>
        ) : activeTool === 'data_extract' ? (
          <main className="flex-1 flex flex-col relative bg-white min-w-[300px] overflow-hidden">
            <div className="flex items-center justify-between px-6 py-3 border-b border-ios-gray-100 shrink-0">
              <div>
                <span className="text-sm font-medium text-ios-gray-900">智能取数</span>
                <p className="text-xs text-ios-gray-400 mt-1">面向结构化数据的自然语言取数与导出</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleSyncDataExtractSources}
                  disabled={dataExtractSyncing || selectedCsvFiles.length === 0}
                  className="px-3 py-1.5 text-sm font-medium rounded-ios border border-ios-gray-200 text-ios-gray-700 hover:bg-ios-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {dataExtractSyncing ? '同步中...' : '同步选中 CSV'}
                </button>
                <button
                  type="button"
                  onClick={handleNewDataExtractSession}
                  className="px-3 py-1.5 text-sm font-medium rounded-ios border border-ios-gray-200 text-ios-gray-700 hover:bg-ios-gray-50"
                >
                  {'\u65b0\u5efa\u4f1a\u8bdd'}
                </button>
                <button
                  type="button"
                  onClick={() => setDataExtractSubView(prev => prev === 'history' ? 'current' : 'history')}
                  className="px-3 py-1.5 text-sm font-medium rounded-ios border border-ios-gray-200 text-ios-gray-700 hover:bg-ios-gray-50"
                >
                  {dataExtractSubView === 'history'
                    ? '\u8fd4\u56de\u5f53\u524d\u4f1a\u8bdd'
                    : '\u53d6\u6570\u5386\u53f2'}
                </button>
                <select
                  value={dataExtractDatasourceId}
                  onChange={(e) => {
                    setDataExtractDatasourceId(e.target.value);
                    resetDataExtractWorkspace();
                  }}
                  className="px-3 py-1.5 text-sm rounded-ios border border-ios-gray-200 text-ios-gray-700 min-w-[220px]"
                >
                  <option value="">选择数据源</option>
                  {activeDataExtractDatasources.map(ds => (
                    <option key={ds.id} value={String(ds.datasource_id)}>
                      {ds.display_name || ds.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-8">
              <div className="max-w-[900px] mx-auto w-full space-y-4">
                {dataExtractSubView === 'history' && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold text-gray-500">取数会话历史</h3>
                      <button
                        type="button"
                        onClick={() => setDataExtractSubView('current')}
                        className="text-sm text-blue-600 hover:underline"
                      >
                        返回当前会话
                      </button>
                    </div>
                    {dataExtractHistoryLoading ? (
                      <div className="rounded-2xl border border-ios-gray-100 bg-white px-4 py-6 text-sm text-ios-gray-400">
                        正在加载历史会话...
                      </div>
                    ) : dataExtractSessions.length === 0 ? (
                      <div className="rounded-2xl border border-ios-gray-100 bg-white px-4 py-6 text-sm text-ios-gray-400">
                        暂无取数历史
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {dataExtractSessions.map(session => (
                          <button
                            key={session.id}
                            type="button"
                            onClick={() => loadDataExtractSession(session.id)}
                            className="w-full text-left rounded-2xl border border-ios-gray-100 bg-white px-4 py-4 hover:border-emerald-200 hover:bg-emerald-50/40 transition-colors"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <div className="text-sm font-medium text-ios-gray-900">{session.title}</div>
                                <div className="mt-1 text-xs text-ios-gray-500">
                                  {new Date(session.updated_at).toLocaleString()} · {session.turn_count || 0} 轮问答 · {session.artifact_count || 0} 个产出
                                </div>
                              </div>
                              <div className="text-xs text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full">
                                主数据源 {session.primary_datasource_id}
                              </div>
                            </div>
                            {!!session.datasource_snapshot?.length && (
                              <div className="mt-2 flex flex-wrap gap-2">
                                {session.datasource_snapshot.map(ds => (
                                  <span key={`${session.id}-${ds.datasource_id}`} className="text-[11px] px-2.5 py-1 rounded-full bg-ios-gray-100 text-ios-gray-600">
                                    {ds.display_name || ds.name || `Datasource ${ds.datasource_id}`}
                                  </span>
                                ))}
                              </div>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {dataExtractSubView === 'current' && (
                  <>
                <div className="rounded-2xl border border-emerald-100 bg-emerald-50/60 px-4 py-3 text-sm text-emerald-800">
                  已选 CSV 文件 {selectedCsvFiles.length} 个，当前联动数据源 {activeDataExtractDatasources.length} 个，已注册数据源 {dataExtractDatasources.length} 个。
                </div>
                {activeDataExtractDatasourceIds.length > 1 && (
                  <div className="rounded-2xl border border-sky-100 bg-sky-50/80 px-4 py-3 text-sm text-sky-800">
                    当前会把 {activeDataExtractDatasourceIds.length} 个已选数据源一起发给 SQLBot 做联合分析，下拉框仅用于指定主数据源。
                  </div>
                )}
                {unsyncedSelectedDatasetCount > 0 && (
                  <div className="rounded-2xl border border-amber-100 bg-amber-50/80 px-4 py-3 text-sm text-amber-800">
                    有 {unsyncedSelectedDatasetCount} 个已选 CSV 还没同步到智能取数模块，当前不会参与联合分析。
                  </div>
                )}
                {selectedDataExtractArtifacts.length > 0 && (
                  <div className="rounded-2xl border border-emerald-100 bg-emerald-50/60 px-4 py-3 text-sm text-emerald-800">
                    本轮已附带 {selectedDataExtractArtifacts.length} 个历史产出作为输入。
                  </div>
                )}
                {dataExtractArtifacts.length > 0 && (
                  <div className="rounded-2xl border border-ios-gray-100 bg-white p-4 shadow-ios-sm">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-semibold text-ios-gray-700">历史产出</h3>
                      <span className="text-xs text-ios-gray-400">最近 {dataExtractArtifacts.length} 条</span>
                    </div>
                    <div className="flex gap-3 overflow-x-auto pb-1">
                      {dataExtractArtifacts.map((artifact) => (
                        <div
                          key={artifact.id}
                          className={`min-w-[240px] max-w-[280px] rounded-2xl border px-4 py-3 transition-colors ${
                            dataExtractSelectedArtifactIds.has(artifact.id)
                              ? 'border-emerald-300 bg-emerald-50/70'
                              : 'border-ios-gray-100 bg-ios-gray-50'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <div className="text-sm font-medium text-ios-gray-900 line-clamp-2">{artifact.title}</div>
                              <div className="mt-1 text-xs text-ios-gray-400">
                                {artifact.type === 'csv' ? `${artifact.row_count || 0} 行结果` : '文本说明'}
                              </div>
                            </div>
                            {artifact.reusable_as_input && (
                              <input
                                type="checkbox"
                                className="rounded-full text-emerald-600 accent-emerald-600 mt-0.5"
                                checked={dataExtractSelectedArtifactIds.has(artifact.id)}
                                onChange={() => handleToggleDataExtractArtifact(artifact.id)}
                              />
                            )}
                          </div>
                          <div className="mt-3 flex items-center gap-2 flex-wrap">
                            <button
                              type="button"
                              onClick={() => setDataExtractPreviewArtifact(artifact)}
                              className="text-xs px-2.5 py-1 rounded-full bg-white border border-ios-gray-200 text-ios-gray-700 hover:bg-ios-gray-50"
                            >
                              预览
                            </button>
                            <button
                              type="button"
                              onClick={() => handleImportDataExtractArtifact(artifact)}
                              className="text-xs px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                            >
                              {artifact.imported_to_sources ? '已导入来源' : '导入来源'}
                            </button>
                            {artifact.file_url && (
                              <a
                                href={artifact.file_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100"
                              >
                                打开文件
                              </a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {dataExtractPreviewArtifact && (
                  <div className="rounded-2xl border border-ios-gray-100 bg-white p-4 shadow-ios-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-ios-gray-900">{dataExtractPreviewArtifact.title}</h3>
                        <p className="text-xs text-ios-gray-400 mt-1">
                          {new Date(dataExtractPreviewArtifact.created_at).toLocaleString()} · {dataExtractPreviewArtifact.type === 'csv' ? 'CSV 结果' : '文本说明'}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setDataExtractPreviewArtifact(null)}
                        className="text-xs text-ios-gray-400 hover:text-ios-gray-600"
                      >
                        关闭
                      </button>
                    </div>
                    {dataExtractPreviewArtifact.sql && (
                      <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-950 px-3 py-3 text-xs text-slate-100">{dataExtractPreviewArtifact.sql}</pre>
                    )}
                    {dataExtractPreviewArtifact.type === 'csv' ? (
                      <div className="mt-3 overflow-x-auto rounded-xl border border-ios-gray-200">
                        <table className="min-w-full text-xs">
                          <thead className="bg-ios-gray-100">
                            <tr>
                              {(dataExtractPreviewArtifact.columns || []).map(col => (
                                <th key={col} className="px-3 py-2 text-left font-medium text-ios-gray-700">{col}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {(dataExtractPreviewArtifact.preview_rows || []).map((row, rowIdx) => (
                              <tr key={`${dataExtractPreviewArtifact.id}-${rowIdx}`} className="border-t border-ios-gray-100">
                                {(dataExtractPreviewArtifact.columns || []).map(col => (
                                  <td key={`${rowIdx}-${col}`} className="px-3 py-2 text-ios-gray-600 whitespace-nowrap">
                                    {String(row?.[col] ?? '')}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="mt-3 whitespace-pre-wrap text-sm text-ios-gray-700 leading-relaxed">
                        {dataExtractPreviewArtifact.preview_text || dataExtractPreviewArtifact.answer_summary || '暂无预览内容'}
                      </div>
                    )}
                  </div>
                )}
                {dataExtractMessages.map(msg => (
                  <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 shadow-ios-sm ${
                      msg.role === 'assistant' ? 'bg-gradient-to-br from-emerald-100 to-emerald-200 text-emerald-700' : 'bg-gradient-to-br from-ios-gray-200 to-ios-gray-300 text-ios-gray-600'
                    }`}>
                      {msg.role === 'assistant' ? <BarChart2 size={16} /> : <User size={16} />}
                    </div>
                    <div className={`max-w-[90%] px-4 py-3 text-sm leading-relaxed shadow-ios-sm ${
                      msg.role === 'assistant' ? 'bg-ios-gray-50 text-ios-gray-700 rounded-2xl rounded-tl-md' : 'bg-primary text-white rounded-2xl rounded-tr-md'
                    }`}>
                      <div>{msg.content}</div>
                      {msg.sql && (
                        <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-950 px-3 py-3 text-xs text-slate-100">{msg.sql}</pre>
                      )}
                      {msg.columns && msg.columns.length > 0 && (
                        <div className="mt-3 overflow-x-auto rounded-xl border border-ios-gray-200">
                          <table className="min-w-full text-xs">
                            <thead className="bg-ios-gray-100">
                              <tr>
                                {msg.columns.map(col => (
                                  <th key={col} className="px-3 py-2 text-left font-medium text-ios-gray-700">{col}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {(msg.rows || []).slice(0, 20).map((row, rowIdx) => (
                                <tr key={rowIdx} className="border-t border-ios-gray-100">
                                  {msg.columns?.map(col => (
                                    <td key={`${rowIdx}-${col}`} className="px-3 py-2 text-ios-gray-600 whitespace-nowrap">
                                      {String(row?.[col] ?? '')}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {msg.role === 'assistant' && (
                        <div className="mt-3 flex items-center gap-3">
                          {typeof msg.rowCount === 'number' && msg.rowCount > 0 && (
                            <span className="text-xs text-ios-gray-400">共 {msg.rowCount} 行，当前展示前 20 行</span>
                          )}
                          {msg.exportUrl && (
                            <button
                              type="button"
                              onClick={() => handleDataExtractExport(msg.exportUrl)}
                              className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 hover:text-emerald-800"
                            >
                              <Download size={14} />
                              导出 CSV
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {dataExtractLoading && (
                  <div className="flex gap-3 animate-pulse">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-100 to-emerald-200 text-emerald-700 flex items-center justify-center shadow-ios-sm">
                      <BarChart2 size={16} />
                    </div>
                    <div className="bg-ios-gray-50 rounded-2xl rounded-tl-md px-4 py-3 text-sm flex items-center gap-2 text-ios-gray-500 shadow-ios-sm">
                      <Loader2 size={14} className="animate-spin" /> 正在分析数据...
                    </div>
                  </div>
                )}
                  </>
                )}
              </div>
            </div>

            {dataExtractSubView === 'current' && (
            <div className="px-6 pb-6 shrink-0">
              <div className="max-w-[900px] mx-auto space-y-2">
                {selectedCsvFiles.length > 0 && (
                  <div className="rounded-2xl border border-blue-100 bg-blue-50/80 p-3 text-sm text-blue-800">
                    已选 CSV 文件 {selectedCsvFiles.length} 个：{selectedCsvFiles.map(f => f.name).slice(0, 3).join('，')}{selectedCsvFiles.length > 3 ? ` 等 ${selectedCsvFiles.length} 个` : ''}。
                    {activeDataExtractDatasources.length === 0 && ' 请先点击“同步选中 CSV”完成注册后即可发送问题。'}
                  </div>
                )}
                <div className="relative">
                  <div className="glass rounded-ios-xl border border-white/30 shadow-ios-sm">
                    <input
                      type="text"
                      value={dataExtractInput}
                      onChange={e => setDataExtractInput(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleSendDataExtractMessage()}
                      placeholder={selectedCsvFiles.length > 0 ? '选中 CSV 后可输入问题：例如统计各城市销售额前 10 名' : '请先同步并选择一个数据源'}
                      disabled={selectedCsvFiles.length === 0 && !dataExtractSessionId}
                      className="w-full bg-transparent rounded-ios-xl py-4 pl-6 pr-24 focus:outline-none text-lg disabled:opacity-50"
                    />
                    <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
                      <span className="text-xs text-ios-gray-400 font-medium">
                        {activeDataExtractDatasourceIds.length > 1 ? `联合 ${activeDataExtractDatasourceIds.length} 个数据源` : `${dataExtractDatasources.length} 个数据源`}
                      </span>
                      <motion.button
                        whileTap={{ scale: 0.88 }}
                        onClick={handleSendDataExtractMessage}
                        disabled={!dataExtractInput.trim() || dataExtractLoading || (selectedCsvFiles.length === 0 && !dataExtractSessionId)}
                        className="p-2 bg-emerald-600 text-white rounded-full hover:bg-emerald-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-ios-sm"
                      >
                        <Send size={20} />
                      </motion.button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            )}
          </main>
        ) : (
        <main className="flex-1 flex flex-col relative bg-white min-w-[300px] overflow-hidden">
          <div className="flex items-center justify-between px-6 py-3 border-b border-ios-gray-100 shrink-0">
            <span className="text-sm font-medium text-ios-gray-900">对话</span>
            <div className="flex items-center gap-2">
              <motion.button
                whileTap={{ scale: 0.95 }}
                type="button"
                onClick={handleNewConversation}
                className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-ios-gray-100 rounded-ios text-sm font-medium text-ios-gray-700 transition-colors"
              >
                <Plus size={16} />
                新的对话
              </motion.button>
              <motion.button
                whileTap={{ scale: 0.95 }}
                type="button"
                onClick={handleShowHistory}
                className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-ios-gray-100 rounded-ios text-sm font-medium text-ios-gray-700 transition-colors"
              >
                <MessageSquare size={16} />
                对话历史
              </motion.button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-8">
            {chatSubView === 'history' && (
              <div className="max-w-[800px] mx-auto w-full">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-500">对话历史（点击可回滚到该对话）</h3>
                  <button
                    type="button"
                    onClick={() => setChatSubView('current')}
                    className="text-sm text-blue-600 hover:underline"
                  >
                    返回当前对话
                  </button>
                </div>
                <ul className="space-y-2">
                  {conversationHistory.length === 0 ? (
                    <li className="text-sm text-gray-400 py-4">暂无历史对话</li>
                  ) : (
                    conversationHistory.map(item => (
                      <li key={item.id}>
                        <button
                          type="button"
                          onClick={() => handleRestoreConversation(item)}
                          className="w-full text-left px-4 py-3 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50/50 transition-colors"
                        >
                          <span className="text-sm font-medium text-gray-800 line-clamp-1">{item.title}</span>
                          <span className="text-xs text-gray-400 mt-1 block">
                            {new Date(item.updatedAt).toLocaleString()} · {item.messages.length} 条消息
                          </span>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            )}
            {chatSubView === 'current' && (
              <div className="max-w-[800px] mx-auto w-full space-y-4">
                {chatMessages.length <= 1 && chatMessages[0]?.id === 'welcome' && (
                  <div className="flex flex-col items-center pt-6 pb-2">
                    <img src="/logo_banner.jpg" alt="OpenNotebookLM" className="h-16 w-auto object-contain rounded-xl" />
                  </div>
                )}
                {chatMessages.map(msg => (
                  <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 shadow-ios-sm ${
                      msg.role === 'assistant' ? 'bg-gradient-to-br from-blue-100 to-blue-200 text-primary' : 'bg-gradient-to-br from-ios-gray-200 to-ios-gray-300 text-ios-gray-600'
                    }`}>
                      {msg.role === 'assistant' ? <Bot size={16} /> : <User size={16} />}
                    </div>
                    <div className={`max-w-[85%] px-4 py-3 text-sm leading-relaxed shadow-ios-sm ${
                      msg.role === 'assistant' ? 'bg-ios-gray-50 text-ios-gray-700 rounded-2xl rounded-tl-md' : 'bg-primary text-white rounded-2xl rounded-tr-md'
                    }`}>
                      {msg.role === 'assistant' ? (
                        <MarkdownContent
                          content={msg.content}
                          sourceMapping={msg.sourceMapping}
                          sourcePreviewMapping={msg.sourcePreviewMapping}
                          sourceReferenceMapping={msg.sourceReferenceMapping}
                        />
                      ) : (
                        <span>{msg.content}</span>
                      )}
                    </div>
                  </div>
                ))}
                {isChatLoading && (
                  <div className="flex gap-3 animate-pulse">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-100 to-blue-200 text-primary flex items-center justify-center shadow-ios-sm">
                      <Bot size={16} />
                    </div>
                    <div className="bg-ios-gray-50 rounded-2xl rounded-tl-md px-4 py-3 text-sm flex items-center gap-2 text-ios-gray-500 shadow-ios-sm">
                      <Loader2 size={14} className="animate-spin" /> {chatLoadingStage}
                    </div>
                  </div>
                )}
              </div>
            )}

          </div>

          {chatSubView === 'current' && (
            <div className="px-6 pb-6 shrink-0">
              <div className="max-w-[800px] mx-auto relative">
                <div className="glass rounded-ios-xl border border-slate-200/85 bg-white/82 shadow-[0_14px_32px_rgba(15,23,42,0.08)] transition-all duration-200 focus-within:border-primary/70 focus-within:bg-white focus-within:shadow-[0_0_0_4px_rgba(59,130,246,0.12),0_18px_40px_rgba(37,99,235,0.16)]">
                  <input
                    type="text"
                    value={inputMsg}
                    onChange={e => setInputMsg(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
                    placeholder={selectedIds.size > 0 ? "开始输入..." : "请先选择文件..."}
                    disabled={selectedIds.size === 0}
                    className="w-full bg-transparent rounded-ios-xl py-4 pl-6 pr-24 text-lg text-slate-800 placeholder:text-slate-400 focus:outline-none disabled:opacity-50"
                  />
                  <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
                    <span className="text-xs text-slate-500 font-medium">{selectedIds.size} 个来源</span>
                    <motion.button
                      whileTap={{ scale: 0.88 }}
                      onClick={handleSendMessage}
                      disabled={!inputMsg.trim() || isChatLoading || selectedIds.size === 0}
                      className="p-2 bg-primary text-white rounded-full hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-ios-sm"
                    >
                      <Send size={20} />
                    </motion.button>
                  </div>
                </div>
              </div>
              <p className="text-center text-[10px] text-ios-gray-400 mt-4">
                NotebookLM 提供的内容未必准确，因此请仔细核查回答内容。
              </p>
            </div>
          )}
        </main>
        )}

        {/* 中-右 拖拽条 */}
        {activeTool !== 'note' && (
        <>
        <div
          role="separator"
          aria-orientation="vertical"
          className="w-1 shrink-0 bg-ios-gray-100/60 hover:bg-primary/40 active:bg-primary cursor-col-resize transition-colors flex items-center justify-center group"
          onMouseDown={(e) => {
            e.preventDefault();
            setResizing('right');
            resizeRef.current = { startX: e.clientX, startLeft: leftPanelWidth, startRight: rightPanelWidth };
          }}
        >
          <span className="w-0.5 h-8 bg-ios-gray-300 group-hover:bg-primary rounded-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
        </div>

        {/* Right Sidebar: Studio 功能卡片，每卡片「…」翻转进该卡片设置 */}
        <aside
          className="border-l border-ios-gray-100/60 flex flex-col bg-white overflow-hidden shrink-0"
          style={{ width: rightPanelWidth, minWidth: 200, maxWidth: 600 }}
        >
          <div className="h-14 border-b border-ios-gray-100 flex items-center px-4 shrink-0">
            <h2 className="font-semibold text-ios-gray-700">Studio</h2>
          </div>

          {studioPanelView === 'settings' && studioSettingsTool ? (
            <div className="flex-1 overflow-y-auto p-4 flex flex-col">
              <button
                type="button"
                onClick={() => { setStudioPanelView('tools'); setStudioSettingsTool(null); }}
                className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 mb-4"
              >
                <ChevronLeft size={18} />
                返回
              </button>
              <h3 className="text-sm font-semibold text-gray-800 mb-3">
                {studioSettingsTool === 'data_extract' && '智能取数'}
                {studioSettingsTool === 'table_processing' && '智能处理'}
                {studioSettingsTool === 'ppt' && 'PPT 生成'}
                {studioSettingsTool === 'mindmap' && '思维导图'}
                {studioSettingsTool === 'drawio' && 'DrawIO 图表'}
                {studioSettingsTool === 'podcast' && '知识播客'}
                {studioSettingsTool === 'flashcard' && '闪卡'}
                {studioSettingsTool === 'quiz' && '测验'}
                {/* {studioSettingsTool === 'video' && '视频讲解'} */}
              </h3>
              <div className="space-y-4">
                {studioSettingsTool === 'data_extract' && (() => {
                  const c = getStudioConfig('data_extract');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">结果格式</label>
                        <select value={c.resultFormat || 'json'} onChange={(e) => setStudioConfigForTool('data_extract', { resultFormat: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="json">JSON</option>
                          <option value="markdown">Markdown</option>
                          <option value="csv">CSV</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">执行策略</label>
                        <select value={c.executionStrategy || 'auto'} onChange={(e) => setStudioConfigForTool('data_extract', { executionStrategy: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="auto">自动</option>
                          <option value="legacy">legacy</option>
                          <option value="ega">ega</option>
                        </select>
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'table_processing' && (() => {
                  const c = getStudioConfig('table_processing');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || 'gpt-4o'} onChange={(e) => setStudioConfigForTool('table_processing', { llmModel: e.target.value })} placeholder="gpt-4o" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'ppt' && (() => {
                  const c = getStudioConfig('ppt');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">语言</label>
                        <select value={c.language || 'zh'} onChange={(e) => setStudioConfigForTool('ppt', { language: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">中文</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">生成页数</label>
                        <input
                          type="number"
                          min={1}
                          max={50}
                          value={c.page_count ?? '10'}
                          onChange={(e) => {
                            const v = e.target.value.replace(/\D/g, '');
                            if (v === '') {
                              setStudioConfigForTool('ppt', { page_count: '' });
                              return;
                            }
                            const n = parseInt(v, 10);
                            if (!Number.isNaN(n)) setStudioConfigForTool('ppt', { page_count: String(Math.max(1, Math.min(50, n))) });
                          }}
                          onBlur={(e) => {
                            const v = (e.target.value || '10').trim();
                            const n = parseInt(v, 10);
                            if (Number.isNaN(n) || n < 1 || n > 50) setStudioConfigForTool('ppt', { page_count: '10' });
                          }}
                          placeholder="1–50"
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                        />
                        <p className="text-xs text-gray-400 mt-0.5">1–50 页，整数</p>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('ppt', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">生图模型 (VLM)</label>
                        <select value={c.genFigModel || 'gemini-2.5-flash-image'} onChange={(e) => setStudioConfigForTool('ppt', { genFigModel: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="gemini-2.5-flash-image">2.5 Pro</option>
                          <option value="gemini-3-pro-image-preview">3.0 Pro</option>
                          <option value="nano-banana-2">Nano Banana 2</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">风格预设</label>
                        <select value={c.stylePreset || 'modern'} onChange={(e) => setStudioConfigForTool('ppt', { stylePreset: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="modern">现代简约</option>
                          <option value="business">商务专业</option>
                          <option value="academic">学术报告</option>
                          <option value="creative">创意设计</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">风格化 Prompt（可选）</label>
                        <textarea value={c.stylePrompt || ''} onChange={(e) => setStudioConfigForTool('ppt', { stylePrompt: e.target.value })} placeholder="留空用预设" rows={2} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 resize-none" />
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'mindmap' && (() => {
                  const c = getStudioConfig('mindmap');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('mindmap', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">思维导图风格</label>
                        <select value={c.mindmapStyle || 'default'} onChange={(e) => setStudioConfigForTool('mindmap', { mindmapStyle: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="default">默认</option>
                        </select>
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'drawio' && (() => {
                  const c = getStudioConfig('drawio');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('drawio', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">图表类型</label>
                        <select value={c.diagramType || 'auto'} onChange={(e) => setStudioConfigForTool('drawio', { diagramType: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="auto">自动</option>
                          <option value="flowchart">流程图</option>
                          <option value="architecture">架构图</option>
                          <option value="sequence">时序图</option>
                          <option value="mindmap">思维导图</option>
                          <option value="er">ER 图</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">图表风格</label>
                        <select value={c.diagramStyle || 'default'} onChange={(e) => setStudioConfigForTool('drawio', { diagramStyle: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="default">默认</option>
                          <option value="minimal">简约</option>
                          <option value="sketch">手绘</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">语言</label>
                        <select value={c.language || 'zh'} onChange={(e) => setStudioConfigForTool('drawio', { language: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">中文</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'podcast' && (() => {
                  const c = getStudioConfig('podcast');
                  const ttsType = c.ttsType || 'qwen-tts-local';
                  const isQwen = ttsType === 'qwen-tts-local';
                  const isGemini = ttsType === 'gemini-tts-online';
                  const podcastMode = c.podcastMode || 'monologue';

                  const qwenVoices = [
                    { value: 'vivian', label: 'Vivian - 明亮年轻女声' },
                    { value: 'serena', label: 'Serena - 温暖温柔女声' },
                    { value: 'uncle_fu', label: 'Uncle Fu - 成熟低沉男声' },
                    { value: 'dylan', label: 'Dylan - 清晰自然男声' },
                    { value: 'eric', label: 'Eric - 活泼略沙哑男声' },
                    { value: 'ryan', label: 'Ryan - 充满活力男声（英文）' },
                    { value: 'aiden', label: 'Aiden - 阳光清晰男声（英文）' },
                    { value: 'ono_anna', label: 'Ono Anna - 俏皮女声（日文）' },
                    { value: 'sohee', label: 'Sohee - 温暖女声（韩文）' }
                  ];

                  const geminiVoices = [
                    { value: 'Puck', label: 'Puck - Upbeat' },
                    { value: 'Charon', label: 'Charon - Informative' },
                    { value: 'Kore', label: 'Kore - Firm' },
                    { value: 'Fenrir', label: 'Fenrir - Excitable' },
                    { value: 'Aoede', label: 'Aoede - Breezy' },
                    { value: 'Enceladus', label: 'Enceladus - Breathy' },
                    { value: 'Iapetus', label: 'Iapetus - Clear' },
                    { value: 'Algieba', label: 'Algieba - Smooth' },
                    { value: 'Despina', label: 'Despina - Smooth' },
                    { value: 'Algenib', label: 'Algenib - Gravelly' },
                    { value: 'Rasalgethi', label: 'Rasalgethi - Informative' },
                    { value: 'Achernar', label: 'Achernar - Soft' },
                    { value: 'Alnilam', label: 'Alnilam - Firm' },
                    { value: 'Schedar', label: 'Schedar - Even' },
                    { value: 'Gacrux', label: 'Gacrux - Mature' },
                    { value: 'Pulcherrima', label: 'Pulcherrima - Forward' },
                    { value: 'Achird', label: 'Achird - Friendly' },
                    { value: 'Zubenelgenubi', label: 'Zubenelgenubi - Casual' },
                    { value: 'Vindemiatrix', label: 'Vindemiatrix - Gentle' },
                    { value: 'Sadachbia', label: 'Sadachbia - Lively' },
                    { value: 'Sadaltager', label: 'Sadaltager - Knowledgeable' },
                    { value: 'Sulafat', label: 'Sulafat - Warm' }
                  ];

                  const voices = isQwen ? qwenVoices : geminiVoices;
                  const defaultVoice = isQwen ? 'vivian' : 'Puck';
                  const defaultVoiceB = isQwen ? 'uncle_fu' : 'Charon';

                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || 'deepseek-v3.2'} onChange={(e) => setStudioConfigForTool('podcast', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">TTS 类型</label>
                        <select
                          value={ttsType}
                          onChange={(e) => {
                            const newType = e.target.value;
                            const updates: any = { ttsType: newType };
                            if (newType === 'qwen-tts-local') {
                              updates.ttsModel = 'qwen-tts';
                              updates.podcastMode = 'monologue';
                              updates.voiceName = 'vivian';
                            } else {
                              updates.ttsModel = 'gemini-2.5-flash-tts';
                              updates.voiceName = 'Puck';
                              updates.voiceNameB = 'Charon';
                            }
                            setStudioConfigForTool('podcast', updates);
                          }}
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                        >
                          <option value="qwen-tts-local">本地 Qwen TTS（仅单人）</option>
                          <option value="gemini-tts-online">在线 Gemini TTS（需 apiyi 平台）</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">播客模式</label>
                        <select
                          value={podcastMode}
                          onChange={(e) => setStudioConfigForTool('podcast', { podcastMode: e.target.value })}
                          disabled={isQwen}
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
                        >
                          <option value="monologue">单人播客</option>
                          <option value="dialog">双人对话</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          {podcastMode === 'dialog' ? '说话人 A 音色' : '说话人音色'}
                        </label>
                        <select
                          value={c.voiceName || defaultVoice}
                          onChange={(e) => setStudioConfigForTool('podcast', { voiceName: e.target.value })}
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                        >
                          {voices.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
                        </select>
                      </div>
                      {podcastMode === 'dialog' && isGemini && (
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">说话人 B 音色</label>
                          <select
                            value={c.voiceNameB || defaultVoiceB}
                            onChange={(e) => setStudioConfigForTool('podcast', { voiceNameB: e.target.value })}
                            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                          >
                            {voices.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
                          </select>
                        </div>
                      )}
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">播客语言</label>
                        <select value={c.podcastLanguage || 'zh'} onChange={(e) => setStudioConfigForTool('podcast', { podcastLanguage: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">中文</option>
                          <option value="en">English</option>
                        </select>
                      </div>
</>
                  );
                })()}
                {studioSettingsTool === 'flashcard' && (() => {
                  const c = getStudioConfig('flashcard');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">语言</label>
                        <select value={c.language || 'zh'} onChange={(e) => setStudioConfigForTool('flashcard', { language: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">中文</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">卡片数量</label>
                        <input
                          type="number"
                          min={5}
                          max={50}
                          value={c.cardCount ?? '20'}
                          onChange={(e) => {
                            const v = e.target.value.replace(/\D/g, '');
                            if (v === '') { setStudioConfigForTool('flashcard', { cardCount: '' }); return; }
                            const n = parseInt(v, 10);
                            if (!Number.isNaN(n)) setStudioConfigForTool('flashcard', { cardCount: String(Math.max(5, Math.min(50, n))) });
                          }}
                          onBlur={(e) => {
                            const n = parseInt(e.target.value || '20', 10);
                            if (Number.isNaN(n) || n < 5 || n > 50) setStudioConfigForTool('flashcard', { cardCount: '20' });
                          }}
                          placeholder="5–50"
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                        />
                        <p className="text-xs text-gray-400 mt-0.5">5–50 张卡片</p>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('flashcard', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'quiz' && (() => {
                  const c = getStudioConfig('quiz');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">语言</label>
                        <select value={c.language || 'zh'} onChange={(e) => setStudioConfigForTool('quiz', { language: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">中文</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">题目数量</label>
                        <input
                          type="number"
                          min={5}
                          max={30}
                          value={c.questionCount ?? '10'}
                          onChange={(e) => {
                            const v = e.target.value.replace(/\D/g, '');
                            if (v === '') { setStudioConfigForTool('quiz', { questionCount: '' }); return; }
                            const n = parseInt(v, 10);
                            if (!Number.isNaN(n)) setStudioConfigForTool('quiz', { questionCount: String(Math.max(5, Math.min(30, n))) });
                          }}
                          onBlur={(e) => {
                            const n = parseInt(e.target.value || '10', 10);
                            if (Number.isNaN(n) || n < 5 || n > 30) setStudioConfigForTool('quiz', { questionCount: '10' });
                          }}
                          placeholder="5–30"
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500"
                        />
                        <p className="text-xs text-gray-400 mt-0.5">5–30 道题</p>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('quiz', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </>
                  );
                })()}
                {/* 视频讲解暂未开放
                {studioSettingsTool === 'video' && (() => {
                  const c = getStudioConfig('video');
                  return (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">LLM 模型</label>
                      <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('video', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                    </div>
                  );
                })()}
                */}
              </div>
              <button type="button" onClick={() => { setStudioPanelView('tools'); setStudioSettingsTool(null); }} className="mt-4 w-full py-2.5 bg-blue-500 text-white text-sm font-medium rounded-lg hover:bg-blue-600">
                保存并返回
              </button>
            </div>
          ) : (
          <div className="flex-1 overflow-y-auto p-4">
            <div className="grid grid-cols-2 gap-3 mb-4">
              {studioTools.map(tool => (
                <motion.div
                  key={tool.id}
                  whileHover={{ scale: 1.03, y: -2 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setActiveTool(tool.id)}
                  className={`relative p-4 rounded-ios-xl border transition-all cursor-pointer ${
                    activeTool === tool.id ? 'bg-gradient-to-br from-primary/10 to-primary/5 border-primary/30 shadow-ios-sm' : 'bg-ios-gray-50 border-ios-gray-100 hover:border-primary/20 hover:bg-white'
                  }`}
                >
                  <div className={`w-8 h-8 rounded-ios flex items-center justify-center mb-3 ${
                    activeTool === tool.id ? 'bg-primary/15' : 'bg-ios-gray-100'
                  }`}>
                    {tool.icon}
                  </div>
                  <span className="text-sm font-medium text-ios-gray-700">{tool.label}</span>
                  <motion.button
                    whileTap={{ scale: 0.85 }}
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setStudioSettingsTool(tool.id as StudioToolId); setStudioPanelView('settings'); }}
                    className="absolute top-2 right-2 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-ios-gray-200 rounded-ios transition-colors"
                    title="该功能设置"
                  >
                    <MoreVertical size={16} className="text-ios-gray-500" />
                  </motion.button>
                </motion.div>
              ))}
            </div>
            {activeTool !== 'chat' && activeTool !== 'search' && activeTool !== 'data_extract' && activeTool !== 'table_processing' && (
              <motion.button
                whileTap={{ scale: 0.97 }}
                type="button"
                onClick={() => handleToolGenerate(activeTool)}
                disabled={selectedIds.size === 0 || toolLoading}
                className="w-full py-2.5 mb-4 bg-gradient-to-r from-gray-900 to-gray-800 text-white text-sm font-medium rounded-ios-xl hover:from-gray-800 hover:to-gray-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-ios-sm flex items-center justify-center gap-2 transition-all"
              >
                {toolLoading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    生成中…
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    生成
                  </>
                )}
              </motion.button>
            )}

            {/* Tool Output Display */}
            {toolLoading && (
              <div className="bg-blue-50/30 p-4 rounded-2xl border border-blue-100/50 flex flex-col items-center justify-center py-10 gap-4">
                <div className="relative">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                  <Zap size={12} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-blue-500" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-800">正在生成中...</p>
                  <p className="text-xs text-gray-500 mt-1">基于 {selectedIds.size} 个来源</p>
                </div>
              </div>
            )}

            {toolOutput && activeTool === 'mindmap' && toolOutput.mindmap_code && (
              <div className="bg-white border border-gray-200 rounded-xl p-4">
                <MermaidPreview mermaidCode={toolOutput.mindmap_code} title="思维导图" />
              </div>
            )}

            {toolOutput && activeTool === 'ppt' && (
              <div className="bg-green-50/30 p-4 rounded-2xl border border-green-100/50">
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-800 mb-2">PPT 生成完成</p>
                {getPptDownloadUrl(toolOutput) && (
                    <a 
                      href={getPptDownloadUrl(toolOutput)} 
                      target="_blank" 
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 text-sm"
                    >
                      <FileText size={16} />
                      下载 PPT
                    </a>
                  )}
                </div>
              </div>
            )}

            {toolOutput && activeTool === 'podcast' && (
              <div className="bg-purple-50/30 p-4 rounded-2xl border border-purple-100/50">
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-800 mb-2">播客生成完成</p>
                  {(toolOutput.audio_path || toolOutput.audio_url) && (
                    <audio controls className="w-full mt-3" src={toolOutput.audio_path || toolOutput.audio_url} />
                  )}
                </div>
              </div>
            )}

            {toolOutput && activeTool === 'drawio' && toolOutput.xml_content && (
              <div className="bg-teal-50/30 p-4 rounded-2xl border border-teal-100/50">
                <p className="text-sm font-medium text-gray-800">DrawIO 图表已生成，已加入下方产出内容，点击可预览。</p>
                {toolOutput.file_path && (
                  <a
                    href={toolOutput.file_path}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 mt-2 text-sm text-teal-600 hover:text-teal-700"
                  >
                    <FileText size={14} />
                    下载 .drawio
                  </a>
                )}
              </div>
            )}


          {/* Output Feed */}
          {outputFeed.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-ios-gray-700">产出内容</h3>
                <span className="text-xs text-ios-gray-400">最近 {outputFeed.length} 条</span>
              </div>
              <div className="space-y-3">
                {outputFeed.map((item, feedIdx) => (
                  <motion.div
                    key={item.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: feedIdx * 0.05, type: 'spring', stiffness: 300, damping: 25 }}
                    whileHover={{ y: -2, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                    className="bg-white border border-ios-gray-100 rounded-ios-xl p-3 shadow-ios-sm transition-all cursor-pointer"
                    onClick={() => {
                      if (item.type === 'flashcard' || item.type === 'quiz') {
                        handleLoadSavedSet(item);
                      } else {
                        setPreviewOutput(item);
                      }
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-sm font-medium text-ios-gray-900">
                        {item.type === 'flashcard' && <BookOpen size={14} className="text-purple-500" />}
                        {item.type === 'quiz' && <Brain size={14} className="text-orange-500" />}
                        {item.type === 'note' && <FileText size={14} className="text-blue-500" />}
                        {item.title}
                      </div>
                      <div className="text-[10px] text-ios-gray-400">{item.createdAt}</div>
                    </div>
                    <div className="mt-1 text-xs text-ios-gray-500 line-clamp-1">
                      来源：{item.sources}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      {(item.type === 'flashcard' || item.type === 'quiz') ? (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleLoadSavedSet(item);
                          }}
                          disabled={loadingSetId === item.id}
                          className="text-xs px-2.5 py-1 rounded-full bg-purple-50 text-purple-600 hover:bg-purple-100 transition-colors disabled:opacity-50"
                        >
                          {loadingSetId === item.id ? '加载中...' : item.type === 'flashcard' ? '学习' : '做测验'}
                        </button>
                      ) : item.type === 'note' ? (
                        <>
                          <button
                            onClick={async (e) => {
                              e.stopPropagation();
                              try {
                                const res = await fetch(item.url!);
                                const markdown = await res.text();
                                const lines = markdown.split('\n').filter(l => l.trim());
                                const titleLine = lines.find(l => l.startsWith('# '));
                                const title = titleLine ? titleLine.slice(2).trim() : item.title;
                                const contentLines = lines.filter(l => !l.startsWith('# ') && !l.startsWith('!['));
                                const blocks = contentLines.length > 0
                                  ? contentLines.map((line, i) => ({ id: `${i}`, type: 'text' as const, content: line }))
                                  : [{ id: '1', type: 'text' as const, content: '' }];
                                setEditingNote({ title, blocks });
                                setActiveTool('note');
                              } catch (err) {
                                alert('加载笔记失败');
                              }
                            }}
                            className="text-xs px-2.5 py-1 rounded-full bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
                          >
                            编辑
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setOutputFeed(prev => prev.filter(f => f.id !== item.id));
                            }}
                            className="text-xs px-2.5 py-1 rounded-full bg-red-50 text-red-600 hover:bg-red-100 transition-colors"
                          >
                            删除
                          </button>
                        </>
                      ) : item.url ? (
                        <>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setPreviewOutput(item);
                            }}
                            className="text-xs px-2.5 py-1 rounded-full bg-green-50 text-green-600 hover:bg-green-100 transition-colors"
                          >
                            预览
                          </button>
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-xs px-2.5 py-1 rounded-full bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
                          >
                            下载
                          </a>
                        </>
                      ) : (
                        <span className="text-xs text-ios-gray-400">暂无下载链接</span>
                      )}
                    </div>
                  </motion.div>
                ))}
              </div>
            </div>
          )}
          </div>
          )}

          {/* 添加笔记 - 暂未使用，先注释
          <div className="p-4 border-t shrink-0">
            <button className="w-full flex items-center justify-center gap-2 py-3 bg-black text-white rounded-full text-sm font-medium hover:bg-gray-800 transition-colors shadow-lg">
              <Plus size={18} />
              添加笔记
            </button>
          </div>
          */}
        </aside>
        </>
        )}
      </div>

      {/* API 设置弹窗 */}
      <SettingsModal
        open={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />

      {/* 引入弹框：根据以下内容生成音频概览和视频概览 */}
      {showIntroduceModal && (
        <div
          className="fixed inset-0 z-[300] flex items-end sm:items-center justify-center"
          onClick={() => {
            setShowIntroduceModal(false);
            setDeepResearchSuccess(null);
            setIntroduceUrlSuccess('');
            setIntroduceTextSuccess('');
          }}
        >
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 glass-dark"
          />
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className="relative bg-white rounded-t-ios-2xl sm:rounded-ios-2xl shadow-ios-xl border border-ios-gray-100 w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-center pt-3 sm:hidden">
              <div className="w-9 h-1 rounded-full bg-ios-gray-300" />
            </div>
            <div className="flex items-center justify-between px-6 py-4 border-b border-ios-gray-100 shrink-0">
              <h2 className="text-base font-semibold text-ios-gray-900 text-center flex-1">
                添加来源：上传文件、粘贴网址或文本
              </h2>
              <button
                type="button"
                onClick={() => {
                setShowIntroduceModal(false);
                setDeepResearchSuccess(null);
                setIntroduceUrlSuccess('');
                setIntroduceTextSuccess('');
              }}
                className="p-2 hover:bg-ios-gray-100 rounded-ios text-ios-gray-500 hover:text-ios-gray-700 -mr-2"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-5">
              {/* 搜索与 API 统一在「设置」中配置，此处仅展示当前来源并跳转 */}
              {(() => {
                const s = getApiSettings(effectiveUser?.id || null);
                const prov = (s?.searchProvider as string) || 'serper';
                const eng = (s?.searchEngine as string) || 'google';
                const label = prov === 'serper' ? 'Serper (Google)' : prov === 'bocha' ? '博查' : `SerpAPI (${eng === 'baidu' ? '百度' : 'Google'})`;
                return (
                  <div className="flex items-center justify-between gap-2 py-1.5 px-3 rounded-lg bg-gray-50 border border-gray-100">
                    <span className="text-xs text-gray-600">当前搜索来源：{label}</span>
                    <button
                      type="button"
                      onClick={() => { setShowIntroduceModal(false); setShowSettingsModal(true); }}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800"
                    >
                      去设置
                    </button>
                  </div>
                );
              })()}

              {/* 两个选项：Search 引入 | Deep Research */}
              <div className="flex gap-2 p-1 bg-gray-100 rounded-xl">
                <button
                  type="button"
                  onClick={() => setIntroduceOption('search')}
                  className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    introduceOption === 'search' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-800'
                  }`}
                >
                  Search 引入
                </button>
                <button
                  type="button"
                  onClick={() => setIntroduceOption('deepresearch')}
                  className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    introduceOption === 'deepresearch' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-800'
                  }`}
                >
                  Deep Research
                </button>
              </div>

              {introduceOption === 'search' ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 flex items-center gap-2 px-3 py-2.5 border border-gray-200 rounded-xl bg-gray-50/50">
                      <Search size={18} className="text-gray-400 shrink-0" />
                      <input
                        type="text"
                        value={fastResearchQuery}
                        onChange={e => { setFastResearchQuery(e.target.value); setFastResearchError(''); }}
                        placeholder="输入查询，如：强化学习的最新进展"
                        className="flex-1 bg-transparent text-sm outline-none placeholder:text-gray-400"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={runFastResearch}
                      disabled={fastResearchLoading || !fastResearchQuery.trim()}
                      className="p-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 shrink-0"
                    >
                      {fastResearchLoading ? <Loader2 size={20} className="animate-spin" /> : <ChevronRight size={20} />}
                    </button>
                  </div>
                  {fastResearchLoading && <p className="text-xs text-gray-500">正在发现其他来源…</p>}
                  {fastResearchError && <p className="text-xs text-red-500">{fastResearchError}</p>}
                  {fastResearchSources.length > 0 && (
                    <div className="space-y-3 pt-1">
                      <p className="text-sm font-medium text-green-700">Fast Research 已完成！</p>
                      <div className="space-y-2 max-h-[200px] overflow-y-auto">
                        {fastResearchSources.map((s, i) => (
                          <div key={i} className="flex items-start gap-2 p-2.5 bg-gray-50 rounded-lg border border-gray-100">
                            <input
                              type="checkbox"
                              checked={fastResearchSelected.has(i)}
                              onChange={() => {
                                const next = new Set(fastResearchSelected);
                                if (next.has(i)) next.delete(i); else next.add(i);
                                setFastResearchSelected(next);
                              }}
                              className="mt-0.5 rounded text-blue-500"
                            />
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-gray-900 line-clamp-2">{s.title}</div>
                              <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{s.snippet}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="flex items-center gap-3 flex-wrap">
                        <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={fastResearchSelected.size === fastResearchSources.length}
                            onChange={e => setFastResearchSelected(e.target.checked ? new Set(fastResearchSources.map((_, i) => i)) : new Set())}
                            className="rounded text-blue-500"
                          />
                          选择所有来源
                        </label>
                        <button
                          type="button"
                          onClick={importFastResearchSources}
                          disabled={importingSources || fastResearchSelected.size === 0}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                        >
                          {importingSources ? <Loader2 size={14} className="animate-spin" /> : null}
                          + 导入
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  {deepResearchSuccess ? (
                    <div className="rounded-xl bg-green-50 border border-green-200 p-5 text-center space-y-4">
                      <p className="text-sm font-medium text-green-800">
                        《{deepResearchSuccess.topic}》报告已生成，已加入来源。
                      </p>
                      <div className="flex items-center justify-center gap-3 flex-wrap">
                        {deepResearchSuccess.pdfUrl && (
                          <a
                            href={deepResearchSuccess.pdfUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 hover:border-gray-400 transition-colors shadow-sm"
                          >
                            <Download size={16} />
                            下载报告
                          </a>
                        )}
                        <button
                          type="button"
                          onClick={() => { setDeepResearchSuccess(null); setShowIntroduceModal(false); }}
                          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700"
                        >
                          好的
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-sm text-gray-600">根据主题搜索并生成 PDF 报告，自动加入来源。</p>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={deepResearchTopic}
                          onChange={e => { setDeepResearchTopic(e.target.value); setDeepResearchError(''); }}
                          placeholder="输入研究主题，生成报告并加入来源"
                          className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-purple-500"
                        />
                        <button
                          type="button"
                          onClick={runDeepResearchReport}
                          disabled={deepResearchLoading || !deepResearchTopic.trim()}
                          className="px-4 py-2 bg-purple-600 text-white rounded-xl text-sm font-medium hover:bg-purple-700 disabled:opacity-50 shrink-0 flex items-center gap-2"
                        >
                          {deepResearchLoading ? <Loader2 size={16} className="animate-spin" /> : null}
                          生成报告
                        </button>
                      </div>
                      {deepResearchError && <p className="text-xs text-red-500">{deepResearchError}</p>}
                    </>
                  )}
                </div>
              )}

              {/* 三种引入方式：上传文件 / 网站 / 直接输入 */}
              <div className="border-t border-gray-100 pt-5 space-y-4">
                {/* 1. 上传文件：点击即选文件 */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">上传文件</p>
                  <label
                    className={`flex flex-col items-center justify-center gap-3 w-full min-h-[148px] py-5 px-4 rounded-2xl border-2 border-dashed transition-colors ${
                      fileUploading
                        ? 'border-blue-200 bg-blue-50/70 cursor-wait'
                        : 'border-gray-200 bg-gray-50/50 hover:bg-gray-100 cursor-pointer'
                    }`}
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (e.dataTransfer.files?.length) {
                        uploadFiles(e.dataTransfer.files, { closeModalOnQueue: true });
                      }
                    }}
                  >
                    <div className="w-12 h-12 rounded-2xl bg-white border border-gray-200 flex items-center justify-center shadow-sm">
                      {fileUploading ? <Loader2 size={22} className="animate-spin text-blue-600" /> : <Upload size={22} className="text-gray-600" />}
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-semibold text-gray-800">
                        {fileUploading ? '文件处理中，来源列表会实时更新' : '点击选择，或拖入一个或多个文件'}
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        支持一次添加多个文件，上传后会立刻出现在左侧来源列表
                      </p>
                    </div>
                    <input
                      type="file"
                      className="hidden"
                      multiple
                      accept=".pdf,.docx,.pptx,.png,.jpg,.jpeg,.mp4,.md"
                      onChange={(e) => {
                        if (e.target.files?.length) {
                          uploadFiles(e.target.files, { closeModalOnQueue: true });
                          e.target.value = '';
                        }
                      }}
                    />
                  </label>
                  <p className="text-xs text-gray-400 mt-1">PDF、图片、文档、音频等</p>
                </div>

                {/* 2. 网站：输入 URL，抓取网页正文后引入 */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">网站</p>
                  <div className="flex gap-2">
                    <input
                      type="url"
                      value={introduceUrl}
                      onChange={(e) => { setIntroduceUrl(e.target.value); setIntroduceUrlError(''); setIntroduceUrlSuccess(''); }}
                      placeholder="https://..."
                      className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <button
                      type="button"
                      onClick={handleImportUrlAsSource}
                      disabled={introduceUrlLoading || !introduceUrl.trim()}
                      className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 shrink-0 flex items-center gap-2"
                    >
                      {introduceUrlLoading ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />}
                      抓取并引入
                    </button>
                  </div>
                  {introduceUrlError && <p className="text-xs text-red-500 mt-1">{introduceUrlError}</p>}
                  {introduceUrlSuccess && <p className="text-xs text-green-600 mt-1">{introduceUrlSuccess}</p>}
                  <p className="text-xs text-gray-400 mt-1">抓取网页正文（自动去除 HTML 标签）后加入来源</p>
                </div>

                {/* 3. 直接输入：文本框粘贴文字 */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">直接输入</p>
                  <textarea
                    value={introduceText}
                    onChange={(e) => { setIntroduceText(e.target.value); setIntroduceTextError(''); setIntroduceTextSuccess(''); }}
                    placeholder="粘贴或输入文字…"
                    rows={4}
                    className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  />
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-gray-400">将作为 .md 来源加入笔记本</span>
                    <button
                      type="button"
                      onClick={handleAddTextSource}
                      disabled={introduceTextLoading || !introduceText.trim()}
                      className="px-4 py-2 rounded-xl bg-gray-800 text-white text-sm font-medium hover:bg-gray-900 disabled:opacity-50 flex items-center gap-2"
                    >
                      {introduceTextLoading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
                      添加为来源
                    </button>
                  </div>
                  {introduceTextError && <p className="text-xs text-red-500 mt-1">{introduceTextError}</p>}
                  {introduceTextSuccess && <p className="text-xs text-green-600 mt-1">{introduceTextSuccess}</p>}
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      )}

      {/* 产出预览抽屉 */}
      {previewOutput && (
        <div
          className="fixed inset-0 z-[200] flex items-end sm:items-center justify-center"
          onClick={() => setPreviewOutput(null)}
        >
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 glass-dark"
          />
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className={`relative bg-white rounded-t-ios-2xl sm:rounded-ios-2xl shadow-ios-xl border border-ios-gray-100 overflow-hidden flex flex-col ${
              previewOutput.type === 'drawio'
                ? 'w-[95vw] h-[95vh] min-w-[320px] min-h-[360px]'
                : 'w-[90vw] h-[90vh] max-w-[1600px] max-h-[90vh] min-w-[320px] min-h-[360px]'
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-ios-gray-100 bg-white shrink-0">
              <div>
                <h2 className="text-lg font-semibold text-ios-gray-800">{previewOutput.title}</h2>
                <p className="text-xs text-ios-gray-500 mt-1">来源：{previewOutput.sources}</p>
              </div>
              <div className="flex items-center gap-2">
                {previewOutput.url && (
                  <a
                    href={previewOutput.url}
                    target="_blank"
                    rel="noreferrer"
                    className="px-4 py-2 text-sm font-medium text-primary bg-primary/10 hover:bg-primary/20 rounded-ios transition-colors"
                  >
                    下载
                  </a>
                )}
                <motion.button
                  whileTap={{ scale: 0.9 }}
                  onClick={() => setPreviewOutput(null)}
                  className="p-2 hover:bg-ios-gray-100 rounded-ios text-ios-gray-500 hover:text-ios-gray-700 transition-colors"
                >
                  <X size={20} />
                </motion.button>
              </div>
            </div>

            {/* Body：min-h-0 让 flex 子项可收缩，drawio 画布才能拉满 */}
            <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
              {previewOutput.type === 'ppt' && (
                <div className="h-full w-full flex flex-col">
                  {(() => {
                    const pdfUrl = previewOutput.previewUrl || (previewOutput.url?.toLowerCase().endsWith('.pdf') ? previewOutput.url : undefined);
                    const sameOriginPdf = pdfUrl ? getSameOriginUrl(pdfUrl) : '';
                    if (!sameOriginPdf) {
                      return (
                        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-gray-500 p-6">
                          <p>暂无 PDF 预览，请点击下方下载查看。</p>
                          {previewOutput.url && (
                            <a
                              href={getSameOriginUrl(previewOutput.url)}
                              target="_blank"
                              rel="noreferrer"
                              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                            >
                              下载文件
                            </a>
                          )}
                        </div>
                      );
                    }
                    return (
                      <object
                        data={sameOriginPdf}
                        type="application/pdf"
                        className="w-full flex-1 min-h-0"
                      >
                        <div className="flex flex-col items-center justify-center h-full gap-4 text-gray-500">
                          <p>PDF 预览加载失败</p>
                          <a
                            href={sameOriginPdf}
                            target="_blank"
                            rel="noreferrer"
                            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                          >
                            在新标签页打开
                          </a>
                        </div>
                      </object>
                    );
                  })()}
                </div>
              )}

              {previewOutput.type === 'podcast' && previewOutput.url && (
                <div className="flex flex-col items-center justify-center h-full">
                  <div className="w-full max-w-2xl bg-white rounded-xl shadow-lg p-8">
                    <div className="flex items-center gap-4 mb-6">
                      <div className="w-16 h-16 bg-gradient-to-br from-green-400 to-blue-500 rounded-full flex items-center justify-center">
                        <Mic2 className="text-white" size={32} />
                      </div>
                      <div>
                        <h3 className="text-xl font-semibold text-gray-900">知识播客</h3>
                        <p className="text-sm text-gray-500">{previewOutput.createdAt}</p>
                      </div>
                    </div>
                    <audio
                      controls
                      autoPlay
                      className="w-full"
                      src={previewOutput.url}
                    >
                      您的浏览器不支持音频播放
                    </audio>
                    <p className="text-xs text-gray-400 mt-4 text-center">
                      提示：可以下载音频文件到本地播放
                    </p>
                  </div>
                </div>
              )}

              {previewOutput.type === 'mindmap' && previewOutput.mermaidCode && (
                <div className="h-full flex items-center justify-center">
                  <div className="w-full h-full bg-white rounded-xl shadow-lg p-6">
                    <MermaidPreview 
                      mermaidCode={previewOutput.mermaidCode} 
                      title="思维导图预览" 
                    />
                  </div>
                </div>
              )}

              {previewOutput.type === 'drawio' && previewOutput.url && (
                <div className="flex-1 min-h-0 flex flex-col w-full">
                  {previewDrawioXml ? (
                    <div className="relative flex-1 min-h-0 w-full bg-gray-50" style={{ minHeight: 0 }}>
                      <DrawioInlineEditor
                        xmlContent={previewDrawioXml}
                        maximized
                      />
                    </div>
                  ) : previewLoading ? (
                    <div className="flex items-center justify-center flex-1 text-gray-500 text-sm">
                      正在加载图表…
                    </div>
                  ) : (
                    <div className="p-4 text-center">
                      <p className="text-sm text-gray-600 mb-3">无法内嵌加载，请下载后编辑。</p>
                      <a
                        href={previewOutput.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 px-4 py-2 bg-teal-500 text-white rounded-lg hover:bg-teal-600 text-sm"
                      >
                        <FileText size={16} />
                        下载 .drawio 文件
                      </a>
                    </div>
                  )}
                </div>
              )}
              {previewOutput.type === 'note' && previewOutput.url && (
                <div className="flex items-center justify-center h-full text-gray-500">
                  <div className="text-center px-6 py-4">
                    <p className="text-sm font-medium text-gray-700 mb-3">笔记预览将在编辑器打开</p>
                    <a
                      href={previewOutput.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center justify-center px-4 py-2 text-sm font-medium text-primary bg-primary/10 hover:bg-primary/20 rounded-ios transition-colors"
                    >
                      打开笔记文件
                    </a>
                  </div>
                </div>
              )}
              {previewOutput.type === 'mindmap' && !previewOutput.mermaidCode && (
                <div className="flex items-center justify-center h-full text-gray-400">
                  {previewLoading ? '正在加载思维导图内容...' : '暂无预览内容'}
                </div>
              )}

              {!previewOutput.url && !previewOutput.mermaidCode && previewOutput.type !== 'mindmap' && (
                <div className="flex items-center justify-center h-full text-gray-400">
                  暂无预览内容
                </div>
              )}
            </div>
          </motion.div>
        </div>
      )}

      {/* Flashcard Viewer Modal */}
      {showFlashcardViewer && flashcards.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center" onClick={() => setShowFlashcardViewer(false)}>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 glass-dark"
          />
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className="relative bg-white rounded-t-ios-2xl sm:rounded-ios-2xl shadow-ios-xl w-full max-w-2xl max-h-[90vh] overflow-auto"
            onClick={e => e.stopPropagation()}
          >
            <FlashcardViewer
              flashcards={flashcards}
              onClose={() => setShowFlashcardViewer(false)}
            />
          </motion.div>
        </div>
      )}

      {/* Quiz Container Modal */}
      {showQuizContainer && quizQuestions.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center" onClick={() => setShowQuizContainer(false)}>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 glass-dark"
          />
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className="relative bg-white rounded-t-ios-2xl sm:rounded-ios-2xl shadow-ios-xl w-full max-w-3xl max-h-[90vh] overflow-auto"
            onClick={e => e.stopPropagation()}
          >
            <QuizContainer
              questions={quizQuestions}
              onClose={() => setShowQuizContainer(false)}
            />
          </motion.div>
        </div>
      )}
    </div>
    </>
  );
};

export default NotebookView;
