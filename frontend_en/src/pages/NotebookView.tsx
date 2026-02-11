import React, { useState, useEffect } from 'react';
import {
  ChevronLeft, Plus, Share2, Settings, MessageSquare,
  BarChart2, Zap, AudioLines, Video, FileText,
  Filter, MoreVertical, Search, Image as ImageIcon, FileStack, Sparkles,
  Mic2, Video as VideoIcon, BrainCircuit, Send, Bot, User, Loader2, Upload, X,
  Globe, Link2, Cloud, ChevronRight, LayoutGrid, Download, BookOpen, Brain
} from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { supabase, isSupabaseConfigured } from '../lib/supabase';
import { apiFetch } from '../config/api';
import { getApiSettings } from '../services/apiSettingsService';
import type { KnowledgeFile, ChatMessage, ToolType } from '../types';
import ReactMarkdown from 'react-markdown';
import { MermaidPreview } from '../components/knowledge-base/tools/MermaidPreview';
import { SettingsModal } from '../components/SettingsModal';
import DrawioInlineEditor from '../components/DrawioInlineEditor';
import { FlashcardGenerator } from '../components/flashcards/FlashcardGenerator';
import { FlashcardViewer } from '../components/flashcards/FlashcardViewer';
import { QuizGenerator } from '../components/quiz/QuizGenerator';
import { QuizContainer } from '../components/quiz/QuizContainer';
import katex from 'katex';
import 'katex/dist/katex.min.css';

// 不做用户管理时使用，数据从 outputs 取
const DEFAULT_USER = { id: 'default', email: 'default' };

const NotebookView = ({ notebook, onBack }: { notebook: any, onBack: () => void }) => {
  const { user } = useAuthStore();
  const effectiveUser = user || DEFAULT_USER;
  const [activeTab, setActiveTab] = useState<'chat' | 'retrieval' | 'sources'>('chat');
  const [activeTool, setActiveTool] = useState<ToolType>('chat');
  
  // Files management
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  
  // Chat state
  const WELCOME_MSG: ChatMessage = {
    id: 'welcome',
    role: 'assistant',
    content: 'Hello! I\'m your knowledge base assistant. Upload files or select sources on the left, then ask your questions here.',
    time: new Date().toLocaleTimeString()
  };
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([WELCOME_MSG]);
  const chatPersistSkippedRef = React.useRef(false);
  const conversationIdRef = React.useRef<string | null>(null);
  const [inputMsg, setInputMsg] = useState('');
  const [isChatLoading, setIsChatLoading] = useState(false);

  // Chat历史：本地持久化
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
    type: 'ppt' | 'mindmap' | 'podcast' | 'drawio';
    title: string;
    sources: string;
    url?: string;
    /** PPT 专用：PDF 预览地址，用于内嵌展示；url 为 PPTX 下载 */
    previewUrl?: string;
    createdAt: string;
    mermaidCode?: string;
  }>>([]);

  // Settings modal
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  // Flashcard state
  const [flashcards, setFlashcards] = useState<any[]>([]);
  const [showFlashcardViewer, setShowFlashcardViewer] = useState(false);
  const [flashcardSetId, setFlashcardSetId] = useState<string>('');

  // Quiz state
  const [quizQuestions, setQuizQuestions] = useState<any[]>([]);
  const [showQuizContainer, setShowQuizContainer] = useState(false);
  const [quizId, setQuizId] = useState<string>('');

  // Output preview
  const [previewOutput, setPreviewOutput] = useState<{
    id: string;
    type: 'ppt' | 'mindmap' | 'podcast' | 'drawio';
    title: string;
    sources: string;
    url?: string;
    previewUrl?: string;
    createdAt: string;
    mermaidCode?: string;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  /** DrawIO 预览：从 url 拉取后的 xml，用于在弹窗内嵌编辑 */
  const [previewDrawioXml, setPreviewDrawioXml] = useState<string | null>(null);
  const [retrievalQuery, setRetrievalQuery] = useState('');
  const [retrievalResults, setRetrievalResults] = useState<any[]>([]);
  const [retrievalLoading, setRetrievalLoading] = useState(false);
  const [retrievalError, setRetrievalError] = useState('');
  const [retrievalTopK, setRetrievalTopK] = useState(5);
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
  const [introduceUploadSuccess, setIntroduceUploadSuccess] = useState('');

  // 来源详情：点击某项后翻转显示解析内容（PDF 等解析为 markdown 展示）
  const [sourceDetailView, setSourceDetailView] = useState<KnowledgeFile | null>(null);
  const [sourceDetailContent, setSourceDetailContent] = useState('');
  const [sourceDetailFormat, setSourceDetailFormat] = useState<'text' | 'markdown'>('text');
  const [sourceDetailLoading, setSourceDetailLoading] = useState(false);

  // Flashcard state
  const [flashcards, setFlashcards] = useState<any[]>([]);
  const [showFlashcardViewer, setShowFlashcardViewer] = useState(false);
  const [flashcardSetId, setFlashcardSetId] = useState<string>('');

  // Quiz state
  const [quizQuestions, setQuizQuestions] = useState<any[]>([]);
  const [showQuizContainer, setShowQuizContainer] = useState(false);
  const [quizId, setQuizId] = useState<string>('');

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
      const delta = e.clientX - resizeRef.current.startX;
      if (resizing === 'left') {
        setLeftPanelWidth(() => Math.min(480, Math.max(160, resizeRef.current!.startLeft + delta)));
      } else {
        setRightPanelWidth(() => Math.min(600, Math.max(200, resizeRef.current!.startRight - delta)));
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
  const studioTools: Array<{icon: React.ReactNode, label: string, id: ToolType}> = [
    { icon: <ImageIcon className="text-orange-500" />, label: 'PPT', id: 'ppt' },
    { icon: <BrainCircuit className="text-purple-500" />, label: 'Mind Map', id: 'mindmap' },
    { icon: <LayoutGrid className="text-teal-500" />, label: 'DrawIO', id: 'drawio' },
    { icon: <BookOpen className="text-indigo-500" />, label: 'Flashcards', id: 'flashcard' },
    { icon: <Brain className="text-blue-500" />, label: 'Quiz', id: 'quiz' },
    { icon: <Mic2 className="text-red-500" />, label: 'Knowledge Podcast', id: 'podcast' },
    { icon: <BookOpen className="text-indigo-500" />, label: 'Flashcards', id: 'flashcard' },
    { icon: <Brain className="text-blue-500" />, label: 'Quiz', id: 'quiz' },
    // Video narration temporarily disabled
    // { icon: <VideoIcon className="text-blue-600" />, label: 'Video narration', id: 'video' },
  ];

  // Studio：每个功能卡片各自配置，点卡片上的「…」翻转进该卡片的设置
  type StudioToolId = 'ppt' | 'mindmap' | 'drawio' | 'podcast' | 'video';
  const [studioPanelView, setStudioPanelView] = useState<'tools' | 'settings'>('tools');
  const [studioSettingsTool, setStudioSettingsTool] = useState<StudioToolId | null>(null);
  const STORAGE_STUDIO_CONFIG = `kb_studio_config_${effectiveUser?.id || 'default'}`;
  const defaultByTool: Record<StudioToolId, Record<string, string>> = {
    ppt: { llmModel: 'deepseek-v3.2', genFigModel: 'gemini-2.5-flash-image', stylePreset: 'modern', stylePrompt: '', language: 'zh', page_count: '10' },
    mindmap: { llmModel: 'deepseek-v3.2', mindmapStyle: 'default' },
    drawio: { llmModel: 'deepseek-v3.2', diagramType: 'auto', diagramStyle: 'default', language: 'zh' },
    podcast: { llmModel: 'deepseek-v3.2', ttsModel: 'gemini-2.5-pro-preview-tts', voiceName: 'Kore', voiceNameB: 'Puck' },
    video: { llmModel: 'deepseek-v3.2' },
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

  // 持久化当前Chat到历史（仅在有除 welcome 外的消息时）
  const persistCurrentConversation = (messages: ChatMessage[]) => {
    const list = messages.filter(m => m.id !== 'welcome');
    if (list.length === 0) return;
    const title = (list.find(m => m.role === 'user')?.content || 'New Chat').slice(0, 30);
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

  const inferOutputType = (urlOrName?: string): 'ppt' | 'mindmap' | 'podcast' | 'drawio' => {
    const value = (urlOrName || '').toLowerCase();
    if (value.endsWith('.wav') || value.endsWith('.mp3') || value.endsWith('.m4a')) return 'podcast';
    if (value.endsWith('.mmd') || value.endsWith('.mermaid')) return 'mindmap';
    if (value.endsWith('.drawio')) return 'drawio';
    return 'ppt';
  };

  const getOutputTitle = (type: 'ppt' | 'mindmap' | 'podcast' | 'drawio') => {
    if (type === 'mindmap') return 'Mind Map';
    if (type === 'podcast') return 'Podcast';
    if (type === 'drawio') return 'DrawIO';
    return 'PPT';
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
        mermaidCode: prev.mermaidCode || item.mermaidCode
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
    try {
      const params = new URLSearchParams({ email: effectiveUser.email || effectiveUser.id });
      if (notebook?.id) params.set('notebook_id', notebook.id);
      const res = await apiFetch(`/api/v1/kb/outputs?${params.toString()}`);
      if (!res.ok) return [];
      const data = await res.json();
      if (!data?.success || !Array.isArray(data.files)) return [];
      return data.files.map((item: any) => {
        const url = item.download_url || item.url || '';
        const type = (item.output_type as 'ppt' | 'mindmap' | 'podcast' | 'drawio') || inferOutputType(item.file_name || url);
        return {
          id: item.id || url || `output_${Date.now()}`,
          type,
          title: getOutputTitle(type),
          sources: 'Past outputs',
          url,
          createdAt: item.created_at ? new Date(item.created_at).toLocaleString() : new Date().toLocaleString(),
          mermaidCode: undefined
        };
      });
    } catch (err) {
      console.error('Failed to load output history:', err);
      return [];
    }
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
        throw new Error(msg || 'Failed to fetch vector list');
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
      setVectorError(err?.message || 'Failed to fetch vector list');
      setVectorFiles([]);
      setVectorStatusByPath({});
    } finally {
      setVectorLoading(false);
    }
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
    if (isSupabaseConfigured()) {
      if (file?.id) {
        await supabase.from('knowledge_base_files').update({ is_embedded: true }).eq('id', file.id);
      } else if (storagePath) {
        await supabase.from('knowledge_base_files').update({ is_embedded: true }).eq('storage_path', storagePath);
      }
    } else {
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
    }
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
        const msg = 'Please configure API URL and API Key in Settings first';
        setVectorError(msg);
        alert(msg);
        return;
      }
      if (!apiUrl.includes('/embeddings')) {
        apiUrl = `${apiUrl.replace(/\/$/, '')}/embeddings`;
      }
      const filePath = getOutputsPath(item.original_path);
      if (!filePath) {
        setVectorError('Could not get file path');
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
        let msg = 'Re-embed failed';
        try {
          const body = await res.json();
          msg = body?.detail || body?.message || msg;
        } catch {
          msg = await res.text() || msg;
        }
        if (res.status === 401 || (typeof msg === 'string' && msg.includes('401'))) {
          msg = 'API auth failed (401). Please check API Key in Settings.';
        }
        throw new Error(msg);
      }
      await res.json();
      await fetchVectorList();
      await fetchFiles();
    } catch (err: any) {
      setVectorError(err?.message || 'Re-embed failed');
    } finally {
      setVectorActionLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  const handleDeleteVector = async (item: any) => {
    const key = item.id || item.original_path;
    if (!key) return;
    if (!confirm('Delete this vector? Retrieval will no longer return this file.')) {
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
        throw new Error(msg || 'Failed to delete vector');
      }
      await res.json();
      await fetchVectorList();
    } catch (err: any) {
      setVectorError(err?.message || 'Failed to delete vector');
    } finally {
      setVectorActionLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  const handleRunRetrieval = async () => {
    if (!retrievalQuery.trim()) {
      setRetrievalError('Please enter a query');
      return;
    }
    if (!user?.email) {
      setRetrievalError('User info missing');
      return;
    }

    const settings = getApiSettings(user?.id || null);
    const apiUrl = settings?.apiUrl?.trim() || '';
    const apiKey = settings?.apiKey?.trim() || '';
    if (!apiUrl || !apiKey) {
      setRetrievalError('Please configure API URL and API Key in Settings first');
      return;
    }

    try {
      const selectedFiles = files.filter(f => selectedIds.has(f.id));
      const fileIds = selectedFiles.map(f => f.kbFileId).filter(Boolean) as string[];

      setRetrievalLoading(true);
      setRetrievalError('');
      const res = await apiFetch('/api/v1/kb/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: retrievalQuery.trim(),
          top_k: retrievalTopK,
          email: effectiveUser?.email || effectiveUser?.id,
          api_url: apiUrl,
          api_key: apiKey,
          model_name: retrievalModel,
          file_ids: fileIds.length > 0 ? fileIds : undefined
        })
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || 'Retrieval failed');
      }
      const data = await res.json();
      setRetrievalResults(Array.isArray(data.results) ? data.results : []);
    } catch (err: any) {
      setRetrievalError(err?.message || 'Retrieval failed');
    } finally {
      setRetrievalLoading(false);
    }
  };

  // Fetch files from outputs when notebook changes（不做用户管理，数据从 outputs 取）
  useEffect(() => {
    if (notebook?.id) fetchFiles();
  }, [effectiveUser?.id, notebook?.id]);

  useEffect(() => {
    if (effectiveUser?.email || effectiveUser?.id) fetchVectorList();
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
            { id: 'welcome', role: 'assistant', content: 'Hello! I\'m your knowledge base assistant. Upload files or select sources on the left, then ask your questions here.', time: '' },
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
    hasLoadedOutputsRef.current = false;
    let canceled = false;
    const loadOutputs = async () => {
      const local = loadLocalOutputFeed();
      const remote = await fetchOutputHistory();
      if (canceled) return;
      const merged = mergeOutputFeeds(remote, local);
      setOutputFeed(merged);
      hasLoadedOutputsRef.current = true;
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
        if (!res.ok) throw new Error('Failed to load mind map');
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

  const fetchFiles = async () => {
    try {
      let mappedFiles: KnowledgeFile[] = [];
      // 数据从 outputs 取：调用后端按磁盘扫描
      if (notebook?.id) {
        const params = new URLSearchParams({
          user_id: effectiveUser.id,
          notebook_id: notebook.id,
          email: effectiveUser.email || effectiveUser.id,
        });
        const res = await apiFetch(`/api/v1/kb/files?${params.toString()}`);
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data?.files) ? data.files : [];
          mappedFiles = list.map((row: any) => ({
            id: row.id || `file-${row.name}`,
            name: row.name,
            type: mapFileType(row.file_type || row.name?.split('.').pop() || ''),
            size: formatSize(row.file_size || 0),
            uploadTime: '',
            isEmbedded: false,
            desc: '',
            url: row.url || row.static_url,
          }));
        }
      }

      setFiles(mappedFiles);
      setSelectedIds(new Set(mappedFiles.map(f => f.id)));
    } catch (err) {
      console.error('Failed to fetch files:', err);
    }
  };

  const mapFileType = (mimeOrExt: string): 'doc' | 'image' | 'video' | 'link' | 'audio' => {
    if (!mimeOrExt) return 'doc';
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

  const handleToggleSelect = (id: string) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    setSelectedIds(newSet);
  };

  /** PDF / .md 等可解析为正文并预览 */
  const isPreviewableDoc = (f: KnowledgeFile) => {
    const name = (f.name || '').toLowerCase();
    const url = (f.url || '').toLowerCase();
    return (name.endsWith('.pdf') || name.endsWith('.md')) || (url.endsWith('.pdf') || url.endsWith('.md'));
  };

  const openSourceDetail = async (file: KnowledgeFile) => {
    setSourceDetailView(file);
    setSourceDetailContent('');
    setSourceDetailFormat('text');
    setSourceDetailLoading(false);
    if (file.type === 'link' && file.url && (file.url.startsWith('http://') || file.url.startsWith('https://'))) {
      setSourceDetailLoading(true);
      try {
        const res = await apiFetch('/api/v1/kb/fetch-page-content', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: file.url })
        });
        if (res.ok) {
          const data = await res.json();
          setSourceDetailContent(data?.content ?? '[No content]');
        } else {
          setSourceDetailContent('[Fetch failed]');
        }
      } catch {
        setSourceDetailContent('[Request failed]');
      } finally {
        setSourceDetailLoading(false);
      }
    } else if (isPreviewableDoc(file) && file.url && (file.url.startsWith('/outputs/') || file.url.startsWith('/'))) {
      setSourceDetailLoading(true);
      try {
        // Prefer MinerU output MD for display; fallback to parse-local-file
        const displayRes = await apiFetch('/api/v1/kb/get-source-display-content', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: file.url })
        });
        if (displayRes.ok) {
          const displayData = await displayRes.json();
          if (displayData?.from_mineru && displayData?.content != null) {
            setSourceDetailContent(displayData.content);
            setSourceDetailFormat('markdown');
            setSourceDetailLoading(false);
            return;
          }
        }
        const res = await apiFetch('/api/v1/kb/parse-local-file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path_or_url: file.url })
        });
        if (res.ok) {
          const data = await res.json();
          setSourceDetailContent(data?.content ?? '[No content]');
          setSourceDetailFormat((data?.format === 'markdown' ? 'markdown' : 'text') as 'text' | 'markdown');
        } else {
          setSourceDetailContent('[Parse failed]');
        }
      } catch {
        setSourceDetailContent('[Request failed]');
      } finally {
        setSourceDetailLoading(false);
      }
    } else if (file.url && (file.url.startsWith('http') || file.url.startsWith('/'))) {
      setSourceDetailContent(`[File preview] ${file.name}\n\nOpen in new tab: ${file.url}`);
    } else {
      setSourceDetailContent(`[No parse preview] ${file.name}`);
    }
  };

  const runFastResearch = async () => {
    if (!fastResearchQuery.trim()) return;
    const settings = getApiSettings(effectiveUser?.id || null);
    const searchProvider = (settings?.searchProvider as 'serper' | 'serpapi' | 'bocha') || 'serper';
    const searchEngine = (settings?.searchEngine as 'google' | 'baidu') || 'google';
    const searchApiKey = settings?.searchApiKey?.trim() ?? '';
    if ((searchProvider === 'serpapi' || searchProvider === 'bocha') && !searchApiKey) {
      setFastResearchError('Please configure Search API Key in Settings (top right) first');
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
      if (searchProvider === 'serpapi' || searchProvider === 'bocha') body.search_api_key = searchApiKey;
      const res = await apiFetch('/api/v1/kb/fast-research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || 'Fast Research request failed');
      }
      const data = await res.json();
      const sources = data?.sources || [];
      setFastResearchSources(sources);
      setFastResearchSelected(new Set(sources.map((_: any, i: number) => i)));
    } catch (err: any) {
      setFastResearchError(err?.message || 'Search failed');
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
      alert('Please select a notebook and sign in first');
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
        throw new Error(data?.detail || data?.message || 'Import failed');
      }
      const data = await res.json();
      await fetchFiles();
      await fetchVectorList();
      setFastResearchSources([]);
      setFastResearchSelected(new Set());
      const embeddedMsg = data?.embedded ? `, ${data.embedded} embedded` : '';
      alert(`Imported ${data?.imported ?? items.length} source(s)${embeddedMsg}`);
    } catch (err: any) {
      alert(err?.message || 'Import failed');
    } finally {
      setImportingSources(false);
    }
  };

  const handleImportUrlAsSource = async () => {
    const url = introduceUrl.trim();
    if (!url) {
      setIntroduceUrlError('Please enter a page URL');
      return;
    }
    if (!notebook?.id || !effectiveUser?.email) {
      setIntroduceUrlError('Please select a notebook first');
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
        throw new Error(data?.detail || data?.message || 'Fetch failed');
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
      await fetchFiles();
      setIntroduceUrl('');
      setIntroduceUrlSuccess('Fetched and added as source');
      setTimeout(() => setIntroduceUrlSuccess(''), 3000);
    } catch (err: any) {
      setIntroduceUrlError(err?.message || 'Fetch failed');
    } finally {
      setIntroduceUrlLoading(false);
    }
  };

  const handleAddTextSource = async () => {
    const content = introduceText.trim();
    if (!content) {
      setIntroduceTextError('Please enter or paste text');
      return;
    }
    if (!notebook?.id || !effectiveUser?.email) {
      setIntroduceTextError('Please select a notebook first');
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
          title: 'Direct input',
          content,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || 'Add failed');
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
      await fetchFiles();
      setIntroduceText('');
      setIntroduceTextSuccess('Added as source');
      setTimeout(() => setIntroduceTextSuccess(''), 3000);
    } catch (err: any) {
      setIntroduceTextError(err?.message || 'Add failed');
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
      setDeepResearchError('Please configure API in Settings first');
      return;
    }
    if ((searchProvider === 'serpapi' || searchProvider === 'bocha') && !searchApiKey) {
      setDeepResearchError('Please configure Search API Key in Settings first');
      return;
    }
    if (!notebook?.id || !effectiveUser?.email) {
      setDeepResearchError('Please select a notebook first');
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
          search_api_key: searchProvider === 'serpapi' || searchProvider === 'bocha' ? searchApiKey : undefined,
          search_engine: searchEngine,
          search_top_k: 10
        })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.message || 'Report generation failed');
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
      await fetchFiles();
      setDeepResearchTopic('');
      setDeepResearchSuccess({
        topic: deepResearchTopic.trim(),
        pdfUrl: data?.pdf_url || data?.report_url,
      });
    } catch (err: any) {
      setDeepResearchError(err?.message || 'Generation failed');
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

  // Upload handler（不做用户管理时用 effectiveUser）；可选 onSuccess 用于引入弹框内反馈
  const handleFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    options?: { onSuccess?: () => void }
  ) => {
    if (!e.target.files) return;
    if (!notebook?.id) {
      alert('Please select or create a notebook before uploading');
      return;
    }
    const file = e.target.files[0];
    const formData = new FormData();
    formData.append('file', file);
    formData.append('email', effectiveUser.email || effectiveUser.id || 'default');
    formData.append('user_id', effectiveUser.id || 'default');
    formData.append('notebook_id', notebook.id);
    formData.append('notebook_title', notebook?.title || notebook?.name || '');

    setFileUploading(true);
    try {
      const res = await apiFetch('/api/v1/kb/upload', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) throw new Error('Upload failed');

      const data = await res.json();
      await fetchFiles();
      await fetchVectorList();
      if (data.embedded) {
        if (options?.onSuccess) options.onSuccess();
        else alert('Uploaded and embedded successfully!');
      } else {
        if (options?.onSuccess) options.onSuccess();
        else alert('Upload succeeded but auto-embedding failed. You can re-embed from Sources.');
      }
    } catch (err: any) {
      console.error('Upload error:', err);
      const msg = err?.message || 'Upload failed, please retry';
      setRetrievalError(msg);
      alert(msg);
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

    try {
      if (selectedIds.size === 0) {
        const botMsg: ChatMessage = {
          id: Date.now().toString(),
          role: 'assistant',
          content: 'Please select at least one source on the left so I can answer based on those materials.',
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

      const res = await apiFetch('/api/v1/kb/chat', {
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

      const data = await res.json();
      
      const botMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.answer || "Sorry, I couldn't answer that.",
        time: new Date().toLocaleTimeString(),
        details: data.file_analyses,
        sourceMapping: data.source_mapping || undefined
      };
      setChatMessages(prev => [...prev, botMsg]);
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
      const errorMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: "An error occurred. Please try again later.",
        time: new Date().toLocaleTimeString()
      };
      setChatMessages(prev => [...prev, errorMsg]);
      persistCurrentConversation([...chatMessages, userMsg, errorMsg]);
    } finally {
      setIsChatLoading(false);
    }
  };

  // Tool handlers (PPT, Mindmap, etc.)
  const handleToolGenerate = async (tool: ToolType) => {
    if (selectedIds.size === 0) {
      alert('Please select at least one file');
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
        alert('Please configure API URL and API Key in Settings first');
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
          alert('Please select at least 1 document or web source (PDF/PPTX/DOCX/MD or web import).');
          setToolLoading(false);
          return;
        }
        const docPaths = validSources.map(f => f.url).filter(Boolean) as string[];
        if (docPaths.length !== validSources.length) {
          alert('Could not get document/web path. Please retry.');
          setToolLoading(false);
          return;
        }
        const imageItems = imageFiles
          .map(f => ({ path: f.url, description: f.desc || '' }))
          .filter(item => Boolean(item.path));

        const getStyleDescription = (preset: string): string => {
          const styles: Record<string, string> = {
            modern: 'Modern minimal, clean lines and whitespace',
            business: 'Business professional, formal',
            academic: 'Academic report, clear structure',
            creative: 'Creative, vivid and colorful',
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
          tts_model: cfg.ttsModel || 'gemini-2.5-pro-preview-tts',
          voice_name: cfg.voiceName || 'Kore',
          voice_name_b: cfg.voiceNameB || 'Puck',
          podcast_mode: 'monologue',
          podcast_length: 'standard',
          language: 'zh'
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
            title: 'PPT',
            sources: selectedNames.length ? selectedNames.join(', ') : `${selectedIds.size} source(s)`,
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
          title: 'Mind Map',
          sources: selectedNames.length ? selectedNames.join(', ') : `${selectedIds.size} source(s)`,
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
            title: 'Podcast',
            sources: selectedNames.length ? selectedNames.join(', ') : `${selectedIds.size} source(s)`,
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
            title: 'DrawIO',
            sources: selectedNames.length ? selectedNames.join(', ') : `${selectedIds.size} source(s)`,
            url,
            createdAt: now,
          },
          ...prev,
        ]);
      }

    } catch (err) {
      console.error('Tool generation error:', err);
      alert('Generation failed. Please retry');
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

  const renderInline = (text: string, sourceMapping?: Record<string, string>) => {
    // 1) 先提取行内公式 $...$ 保护起来，避免 escapeHtml 破坏
    const mathSlots: string[] = [];
    let protected_ = text.replace(/\$([^$\n]+?)\$/g, (_m, tex) => {
      mathSlots.push(renderKatex(tex, false));
      return `\x00MATH${mathSlots.length - 1}\x00`;
    });
    // 2) 正常 escapeHtml + markdown 处理
    let html = escapeHtml(protected_);
    html = html.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 rounded bg-gray-100 text-gray-800 font-mono text-xs">$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer" class="text-blue-600 hover:text-blue-500 underline">$1</a>');
    // Highlight numbered citation markers [1], [2], etc. with hover tooltip showing source name
    html = html.replace(/\[(\d{1,2})\]/g, (_match, num) => {
      const sourceName = sourceMapping?.[num] || '';
      const dataAttr = sourceName ? ` data-source="${escapeHtml(sourceName)}"` : '';
      return `<sup class="cite-ref"${dataAttr} style="background-color:#dbeafe;color:#1d4ed8;padding:1px 5px;border-radius:4px;font-size:0.75em;font-weight:600;margin:0 1px;cursor:pointer;position:relative;">[${num}]</sup>`;
    });
    // 3) 还原公式占位符
    html = html.replace(/\x00MATH(\d+)\x00/g, (_m, idx) => mathSlots[Number(idx)]);
    return html;
  };

  const renderMarkdownToHtml = (content: string, sourceMapping?: Record<string, string>) => {
    if (!content) return '';
    // 先提取 $$...$$ 块级公式，替换为占位符
    const blockMathSlots: string[] = [];
    let processed = content.replace(/\$\$([\s\S]+?)\$\$/g, (_m, tex) => {
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
          const headingText = renderInline(headingMatch[2], sourceMapping);
          blockHtml += `<h${level} class="font-semibold text-gray-900 mt-3 mb-2">${headingText}</h${level}>`;
          continue;
        }

        if (/^[-*]\s+/.test(trimmed)) {
          if (!inUl) {
            closeLists();
            blockHtml += '<ul class="list-disc pl-5 space-y-1">';
            inUl = true;
          }
          blockHtml += `<li>${renderInline(trimmed.replace(/^[-*]\s+/, ''), sourceMapping)}</li>`;
          continue;
        }

        if (/^\d+\.\s+/.test(trimmed)) {
          if (!inOl) {
            closeLists();
            blockHtml += '<ol class="list-decimal pl-5 space-y-1">';
            inOl = true;
          }
          blockHtml += `<li>${renderInline(trimmed.replace(/^\d+\.\s+/, ''), sourceMapping)}</li>`;
          continue;
        }

        if (!trimmed) {
          closeLists();
          blockHtml += '<div class="h-2"></div>';
          continue;
        }

        closeLists();
        blockHtml += `<p class="my-1">${renderInline(line, sourceMapping)}</p>`;
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

  const MarkdownContent = ({ content, sourceMapping }: { content: string; sourceMapping?: Record<string, string> }) => (
    <div
      className="text-sm leading-relaxed text-gray-700"
      dangerouslySetInnerHTML={{ __html: renderMarkdownToHtml(content, sourceMapping) }}
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


  return (
    <div className="h-screen flex flex-col bg-[#f8f9fa] overflow-hidden">
      {/* Citation tooltip styles */}
      <style>{`
        .cite-ref[data-source] {
          transition: background-color 0.15s ease;
        }
        .cite-ref[data-source]:hover {
          background-color: #bfdbfe !important;
        }
        .cite-ref[data-source]:hover::after {
          content: "📄 " attr(data-source);
          position: absolute;
          bottom: calc(100% + 8px);
          left: 50%;
          transform: translateX(-50%);
          background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
          color: #f1f5f9;
          padding: 8px 14px;
          border-radius: 8px;
          font-size: 12px;
          line-height: 1.4;
          font-weight: 500;
          letter-spacing: 0.01em;
          white-space: nowrap;
          z-index: 50;
          pointer-events: none;
          box-shadow: 0 4px 16px rgba(0,0,0,0.18), 0 1px 4px rgba(0,0,0,0.1);
          animation: citeTooltipIn 0.15s ease-out;
        }
        .cite-ref[data-source]:hover::before {
          content: "";
          position: absolute;
          bottom: calc(100% + 2px);
          left: 50%;
          transform: translateX(-50%);
          border: 5px solid transparent;
          border-top-color: #1e293b;
          z-index: 50;
          pointer-events: none;
          animation: citeTooltipIn 0.15s ease-out;
        }
        @keyframes citeTooltipIn {
          from { opacity: 0; transform: translateX(-50%) translateY(4px); }
          to   { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
      `}</style>
      {/* Header */}
      <header className="h-14 bg-white border-b flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="p-2 hover:bg-gray-100 rounded-lg">
            <ChevronLeft size={20} />
          </button>
          <img src="/logo.png" alt="Logo" className="w-6 h-6 object-contain" />
          <h1 className="font-medium text-gray-800 truncate max-w-[300px]">
            {notebook?.title || 'Semantic Rewards for Low-Resource Language Alignment'}
          </h1>
        </div>
        
        <div className="flex items-center gap-2">
          {/* 右上方添加笔记 - 暂未使用，先注释
          <button className="flex items-center gap-1.5 px-3 py-1.5 bg-black text-white rounded-full text-sm font-medium hover:bg-gray-800 transition-colors">
            <Plus size={16} />
            New notebook
          </button>
          */}
          {/* 右侧上方分析和分享 - 暂未使用，先注释
          <button className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-full text-sm font-medium transition-colors">
            <BarChart2 size={16} />
            Analyze
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-full text-sm font-medium transition-colors">
            <Share2 size={16} />
            Share
          </button>
          */}
          <button
            onClick={() => setShowSettingsModal(true)}
            className="p-2 hover:bg-gray-100 rounded-full transition-colors"
            title="API settings"
          >
            <Settings size={20} className="text-gray-600" />
          </button>
          <div className="h-4 w-[1px] bg-gray-200 mx-1"></div>
          <div className="text-xs font-medium bg-gray-100 px-2 py-0.5 rounded text-gray-500 uppercase tracking-tight">PRO</div>
          <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center text-white ml-2 text-xs font-bold">
            {(effectiveUser?.email || effectiveUser?.id || 'U').charAt(0).toUpperCase()}
          </div>
        </div>
      </header>

      {/* Main Content Area: 三栏可拖拽调整宽度 */}
      <div className="flex-1 flex overflow-hidden min-w-0">
        {/* Left Sidebar: Sources */}
        <aside
          className="bg-gray-50 border-r flex flex-col p-4 shrink-0 overflow-hidden"
          style={{ width: leftPanelWidth, minWidth: 160, maxWidth: 480 }}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700">Sources ({files.length})</h2>
            <button className="p-1 hover:bg-gray-200 rounded">
              <MoreVertical size={16} />
            </button>
          </div>
          
          <div className="flex gap-2 mb-4">
            <input
              type="file"
              id="file-upload"
              className="hidden"
              onChange={handleFileUpload}
              disabled={fileUploading}
            />
            <label
              htmlFor="file-upload"
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 bg-white border border-gray-200 rounded-full text-sm font-medium transition-all ${fileUploading ? 'text-gray-400 cursor-not-allowed opacity-60' : 'text-gray-700 hover:shadow-sm cursor-pointer'}`}
            >
              {fileUploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
              {fileUploading ? 'Importing...' : 'Upload files'}
            </label>
            <button
              type="button"
              onClick={() => setShowIntroduceModal(true)}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-white border border-gray-200 rounded-full text-sm font-medium text-gray-700 hover:shadow-sm transition-all hover:bg-gray-50"
            >
              <Search size={16} />
              Add sources
            </button>
          </div>

          {retrievalError && (
            <div className="mb-3 px-3 py-2.5 bg-red-50 border border-red-100 rounded-lg space-y-1.5">
              <p className="text-xs text-red-700 line-clamp-2">{retrievalError}</p>
              <div className="flex items-center gap-2 flex-wrap">
                {(retrievalError.includes('API') || retrievalError.includes('configure') || retrievalError.includes('Failed to generate embeddings')) && (
                  <button
                    type="button"
                    onClick={() => { setRetrievalError(''); setShowSettingsModal(true); }}
                    className="text-xs font-medium text-red-600 hover:text-red-800 underline"
                  >
                    Settings
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setRetrievalError('')}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  Close
                </button>
              </div>
            </div>
          )}

          {!sourceDetailView ? (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                  {selectedIds.size > 0 ? `${selectedIds.size} selected` : 'All sources'}
                </span>
                <input
                  type="checkbox"
                  className="rounded text-blue-500"
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
                {files.length === 0 ? (
                  <div className="text-center py-8 text-gray-400 text-sm">
                    No files. Please upload.
                  </div>
                ) : (
                  files.map((file, fileIdx) => (
                    <div
                      key={file.id}
                      className="flex items-center gap-3 p-3 bg-white border border-gray-100 rounded-xl mb-2 hover:shadow-sm transition-all cursor-pointer"
                      onClick={() => openSourceDetail(file)}
                    >
                      <div className="w-8 h-8 bg-blue-50 rounded flex items-center justify-center shrink-0">
                        <span className="text-xs font-bold text-blue-600">{fileIdx + 1}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-gray-700 line-clamp-2 leading-tight">
                          {file.name}
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          {(file.isEmbedded || file.kbFileId || vectorStatusByPath[getOutputsPath(file.url)] === 'embedded' || vectorFiles.some((v: any) => getOutputsPath(v?.original_path) === getOutputsPath(file.url))) && (
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-50 text-green-600">
                              Indexed
                            </span>
                          )}
                        </div>
                      </div>
                      <input
                        type="checkbox"
                        className="rounded text-blue-500"
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
                    </div>
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col min-h-0">
              <button
                type="button"
                onClick={() => setSourceDetailView(null)}
                className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 mb-2"
              >
                <ChevronLeft size={18} />
                Back
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
                  Open in new tab
                </a>
              )}
              <div className="flex-1 min-h-0 overflow-y-auto bg-white border border-gray-200 rounded-xl p-3">
                {sourceDetailLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 size={24} className="animate-spin text-blue-500" />
                    <span className="ml-2 text-sm text-gray-500">Parsing…</span>
                  </div>
                ) : sourceDetailFormat === 'markdown' && sourceDetailContent ? (
                  <div className="prose prose-sm max-w-none text-gray-700 prose-p:text-xs prose-headings:text-sm prose-pre:text-xs">
                    <ReactMarkdown>{sourceDetailContent}</ReactMarkdown>
                  </div>
                ) : (
                  <pre className="whitespace-pre-wrap text-xs text-gray-700 font-sans leading-relaxed break-words">
                    {sourceDetailContent || '[No content]'}
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
          className="w-1 shrink-0 bg-gray-200 hover:bg-blue-400 active:bg-blue-500 cursor-col-resize transition-colors flex items-center justify-center group"
          onMouseDown={(e) => {
            e.preventDefault();
            setResizing('left');
            resizeRef.current = { startX: e.clientX, startLeft: leftPanelWidth, startRight: rightPanelWidth };
          }}
        >
          <span className="w-0.5 h-8 bg-gray-400 group-hover:bg-blue-500 rounded-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
        </div>

        {/* Center: Chat/Content Area */}
        <main className="flex-1 flex flex-col relative bg-white min-w-[300px] overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
            <div className="flex items-center gap-6">
              <button 
                onClick={() => setActiveTab('chat')}
                className={`text-sm font-semibold pb-1 transition-all ${activeTab === 'chat' ? 'text-gray-800 border-b-2 border-black' : 'text-gray-400 hover:text-gray-600'}`}
              >
                Chat
              </button>
              <button 
                onClick={() => setActiveTab('retrieval')}
                className={`text-sm font-semibold pb-1 transition-all ${activeTab === 'retrieval' ? 'text-gray-800 border-b-2 border-black' : 'text-gray-400 hover:text-gray-600'}`}
              >
                Retrieval
              </button>
              <button 
                onClick={() => setActiveTab('sources')}
                className={`text-sm font-medium pb-1 transition-all ${activeTab === 'sources' ? 'text-gray-800 border-b-2 border-black' : 'text-gray-400 hover:text-gray-600'}`}
              >
                Source management
              </button>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleNewConversation}
                className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-full text-sm font-medium text-gray-700"
              >
                <Plus size={16} />
                New Chat
              </button>
              <button
                type="button"
                onClick={handleShowHistory}
                className="flex items-center gap-1.5 px-3 py-1.5 hover:bg-gray-100 rounded-full text-sm font-medium text-gray-700"
              >
                <MessageSquare size={16} />
                Chat history
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-8">
            {activeTab === 'chat' && chatSubView === 'history' && (
              <div className="max-w-[800px] mx-auto w-full">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-500">Chat history (click to restore)</h3>
                  <button
                    type="button"
                    onClick={() => setChatSubView('current')}
                    className="text-sm text-blue-600 hover:underline"
                  >
                    Back to current Chat
                  </button>
                </div>
                <ul className="space-y-2">
                  {conversationHistory.length === 0 ? (
                    <li className="text-sm text-gray-400 py-4">No chat history yet</li>
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
                            {new Date(item.updatedAt).toLocaleString()} · {item.messages.length}  messages
                          </span>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            )}
            {activeTab === 'chat' && chatSubView === 'current' && (
              <div className="max-w-[800px] mx-auto w-full space-y-4">
                {chatMessages.map(msg => (
                  <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                      msg.role === 'assistant' ? 'bg-blue-100 text-blue-600' : 'bg-gray-200 text-gray-600'
                    }`}>
                      {msg.role === 'assistant' ? <Bot size={16} /> : <User size={16} />}
                    </div>
                    <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      msg.role === 'assistant' ? 'bg-gray-50 text-gray-700' : 'bg-blue-500 text-white'
                    }`}>
                      {msg.role === 'assistant' ? (
                        <MarkdownContent content={msg.content} sourceMapping={msg.sourceMapping} />
                      ) : (
                        <span>{msg.content}</span>
                      )}
                    </div>
                  </div>
                ))}
                {isChatLoading && (
                  <div className="flex gap-3 animate-pulse">
                    <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center">
                      <Bot size={16} />
                    </div>
                    <div className="bg-gray-50 rounded-2xl px-4 py-3 text-sm flex items-center gap-2 text-gray-500">
                      <Loader2 size={14} className="animate-spin" /> Thinking...
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'retrieval' && (
              <div className="max-w-[900px] mx-auto w-full space-y-6">
                {!apiConfigured && (
                  <div className="flex items-center justify-between gap-4 p-4 bg-amber-50 border border-amber-200 rounded-2xl">
                    <p className="text-sm text-amber-800">Configure API URL and API Key in Settings (top right) to use retrieval and embeddings.</p>
                    <button type="button" onClick={() => setShowSettingsModal(true)} className="shrink-0 text-sm font-medium text-amber-700 hover:text-amber-900 underline">Settings</button>
                  </div>
                )}
                {retrievalError && (
                  <div className="flex items-center justify-between gap-4 p-4 bg-red-50 border border-red-100 rounded-2xl">
                    <p className="text-sm text-red-700">{retrievalError}</p>
                    <button type="button" onClick={() => setRetrievalError('')} className="shrink-0 text-sm text-red-500 hover:text-red-700">Close</button>
                  </div>
                )}
                <div className="bg-gray-50 border border-gray-200 rounded-2xl p-6">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
                      <Search size={18} className="text-blue-600" />
                    </div>
                    <div className="flex-1">
                      <h3 className="text-lg font-semibold text-gray-900">Knowledge base retrieval</h3>
                      <p className="text-sm text-gray-500 mt-1">Enter a question to search over embedded sources.</p>
                    </div>
                  </div>
                  <div className="mt-4 space-y-3">
                    <input
                      value={retrievalQuery}
                      onChange={e => setRetrievalQuery(e.target.value)}
                      placeholder="e.g. What is the main contribution of the model?"
                      className="w-full bg-white border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-700 outline-none focus:border-blue-400"
                    />
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <span>TopK</span>
                        <input
                          type="number"
                          min={1}
                          max={20}
                          value={retrievalTopK}
                          onChange={e => setRetrievalTopK(Math.max(1, Number(e.target.value || 1)))}
                          className="w-16 bg-white border border-gray-200 rounded-lg px-2 py-1 text-xs text-gray-700"
                        />
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <span>Embedding Model</span>
                        <input
                          value={retrievalModel}
                          onChange={e => setRetrievalModel(e.target.value)}
                          className="w-56 bg-white border border-gray-200 rounded-lg px-2 py-1 text-xs text-gray-700"
                        />
                      </div>
                      <div className="flex items-center gap-2 ml-auto">
                        <button
                          onClick={handleRunRetrieval}
                          disabled={retrievalLoading}
                          className="px-4 py-2 text-xs rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                        >
                          {retrievalLoading ? 'Searching...' : 'Search'}
                        </button>
                      </div>
                    </div>
                    {retrievalError && (
                      <div className="text-xs text-red-500">{retrievalError}</div>
                    )}
                  </div>
                </div>

                <div className="space-y-3">
                  {retrievalResults.length === 0 && !retrievalLoading && (
                    <div className="text-sm text-gray-400 text-center py-10">
                      No results
                    </div>
                  )}
                  {retrievalResults.map((item, idx) => (
                    <div key={idx} className="bg-white border border-gray-200 rounded-2xl p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-xs text-gray-500">
                          Score:{item.score?.toFixed ? item.score.toFixed(3) : item.score}
                        </div>
                        {item.source_file?.url && (
                          <button
                            type="button"
                            onClick={() => {
                              const u = getSameOriginUrl(item.source_file?.url);
                              if (u) window.open(u, '_blank', 'noopener,noreferrer');
                            }}
                            className="text-xs text-blue-600 hover:text-blue-500 underline cursor-pointer bg-transparent border-0 p-0"
                          >
                            Open source
                          </button>
                        )}
                      </div>
                      <div className="text-sm text-gray-700 whitespace-pre-line">
                        {item.content || '(no content)'}
                      </div>
                      {item.media?.url && (
                        <div className="mt-3">
                          {item.type === 'image' ? (
                            <img src={getSameOriginUrl(item.media.url)} alt="media" className="max-h-64 rounded-lg border" />
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                const u = getSameOriginUrl(item.media?.url);
                                if (u) window.open(u, '_blank', 'noopener,noreferrer');
                              }}
                              className="text-xs text-blue-600 hover:text-blue-500 underline cursor-pointer bg-transparent border-0 p-0"
                            >
                              View media
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activeTab === 'sources' && (
              <div className="max-w-[900px] mx-auto w-full space-y-6">
                <div className="bg-gray-50 border border-gray-200 rounded-2xl p-6">
                  <h3 className="text-lg font-semibold text-gray-900">Vector store files</h3>
                  <p className="text-sm text-gray-500 mt-1">
                    Sources are managed on the left. This list shows embedded files and status.
                  </p>
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      onClick={fetchVectorList}
                      disabled={vectorLoading}
                      className="px-3 py-2 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                    >
                      {vectorLoading ? 'Refreshing...' : 'Refresh'}
                    </button>
                    {vectorError && <span className="text-xs text-red-500">{vectorError}</span>}
                  </div>
                </div>

                {vectorLoading && (
                  <div className="text-sm text-gray-400 text-center py-8">Loading vector list...</div>
                )}

                {!vectorLoading && vectorFiles.length === 0 && (
                  <div className="text-sm text-gray-400 text-center py-10">No vector files</div>
                )}

                <div className="space-y-3">
                  {vectorFiles.map((item, idx) => {
                    const fileName = getFileNameFromPath(item.original_path);
                    const status = item.status || 'unknown';
                    const actionKey = item.id || item.original_path;
                    const isBusy = actionKey ? vectorActionLoading[actionKey] : false;
                    const statusColor =
                      status === 'embedded'
                        ? 'text-green-600 bg-green-50'
                        : status === 'failed'
                        ? 'text-red-600 bg-red-50'
                        : status === 'skipped'
                        ? 'text-gray-600 bg-gray-100'
                        : 'text-blue-600 bg-blue-50';
                    return (
                      <div key={`${item.id || idx}`} className="bg-white border border-gray-200 rounded-2xl p-4">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <FileText size={18} className="text-gray-400" />
                            <div>
                              <div className="text-sm font-medium text-gray-900">{fileName || 'Untitled'}</div>
                              <div className="text-xs text-gray-500 mt-1">
                                Type: {item.file_type || '-'} | chunks: {item.chunks_count ?? 0} | media: {item.media_desc_count ?? 0}
                              </div>
                            </div>
                          </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleReembedVector(item)}
                            disabled={isBusy}
                            className="text-xs px-2 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                          >
                            Re-embed
                          </button>
                          <button
                            onClick={() => handleDeleteVector(item)}
                            disabled={isBusy}
                            className="text-xs px-2 py-1 rounded-lg border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"
                          >
                            Delete vector
                          </button>
                          <span className={`text-xs px-2 py-1 rounded-full ${statusColor}`}>
                            {status}
                          </span>
                        </div>
                        </div>
                        {item.error && (
                          <div className="text-xs text-red-500 mt-3 flex items-center gap-2 flex-wrap">
                            <span>
                              {/401|Unauthorized/i.test(String(item.error))
                                ? 'API auth failed. Check API Key in Settings.'
                                : `Error: ${item.error}`}
                            </span>
                            {(/401|Unauthorized/i.test(String(item.error))) && (
                              <button
                                type="button"
                                onClick={() => setShowSettingsModal(true)}
                                className="text-blue-600 hover:underline"
                              >
                                Settings
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {activeTab === 'chat' && chatSubView === 'current' && (
            <div className="px-6 pb-6 shrink-0">
              <div className="max-w-[800px] mx-auto relative">
                <input 
                  type="text" 
                  value={inputMsg}
                  onChange={e => setInputMsg(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
                  placeholder={selectedIds.size > 0 ? "Type here..." : "Select files first..."} 
                  disabled={selectedIds.size === 0}
                  className="w-full bg-[#f8f9fa] border border-gray-200 rounded-3xl py-4 pl-6 pr-24 focus:outline-none focus:ring-1 focus:ring-blue-500 text-lg disabled:opacity-50"
                />
                <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
                  <span className="text-xs text-gray-400 font-medium">{selectedIds.size} sources</span>
                  <button 
                    onClick={handleSendMessage}
                    disabled={!inputMsg.trim() || isChatLoading || selectedIds.size === 0}
                    className="p-2 bg-blue-500 text-white rounded-full hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Send size={20} />
                  </button>
                </div>
              </div>
              <p className="text-center text-[10px] text-gray-400 mt-4">
                Answers may not be fully accurate. Please verify important content.
              </p>
            </div>
          )}
        </main>

        {/* 中-右 拖拽条 */}
        <div
          role="separator"
          aria-orientation="vertical"
          className="w-1 shrink-0 bg-gray-200 hover:bg-blue-400 active:bg-blue-500 cursor-col-resize transition-colors flex items-center justify-center group"
          onMouseDown={(e) => {
            e.preventDefault();
            setResizing('right');
            resizeRef.current = { startX: e.clientX, startLeft: leftPanelWidth, startRight: rightPanelWidth };
          }}
        >
          <span className="w-0.5 h-8 bg-gray-400 group-hover:bg-blue-500 rounded-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
        </div>

        {/* Right Sidebar: Studio 功能卡片，每卡片「…」翻转进该卡片设置 */}
        <aside
          className="border-l flex flex-col bg-white overflow-hidden shrink-0"
          style={{ width: rightPanelWidth, minWidth: 200, maxWidth: 600 }}
        >
          <div className="h-14 border-b flex items-center px-4 shrink-0">
            <h2 className="font-semibold text-gray-700">Studio</h2>
          </div>

          {studioPanelView === 'settings' && studioSettingsTool ? (
            <div className="flex-1 overflow-y-auto p-4 flex flex-col">
              <button
                type="button"
                onClick={() => { setStudioPanelView('tools'); setStudioSettingsTool(null); }}
                className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 mb-4"
              >
                <ChevronLeft size={18} />
                Back
              </button>
              <h3 className="text-sm font-semibold text-gray-800 mb-3">
                {studioSettingsTool === 'ppt' && 'PPT'}
                {studioSettingsTool === 'mindmap' && 'Mind Map'}
                {studioSettingsTool === 'drawio' && 'DrawIO'}
                {studioSettingsTool === 'podcast' && 'Knowledge Podcast'}
                {/* {studioSettingsTool === 'video' && 'Video narration'} */}
              </h3>
              <div className="space-y-4">
                {studioSettingsTool === 'ppt' && (() => {
                  const c = getStudioConfig('ppt');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Language</label>
                        <select value={c.language || 'zh'} onChange={(e) => setStudioConfigForTool('ppt', { language: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">Chinese</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Slides (pages)</label>
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
                        <p className="text-xs text-gray-400 mt-0.5">1–50 pages, integer</p>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM model</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('ppt', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Image model (VLM)</label>
                        <select value={c.genFigModel || 'gemini-2.5-flash-image'} onChange={(e) => setStudioConfigForTool('ppt', { genFigModel: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="gemini-2.5-flash-image">2.5 Pro</option>
                          <option value="gemini-3-pro-image-preview">3.0 Pro</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Style preset</label>
                        <select value={c.stylePreset || 'modern'} onChange={(e) => setStudioConfigForTool('ppt', { stylePreset: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="modern">Modern</option>
                          <option value="business">Business</option>
                          <option value="academic">Academic</option>
                          <option value="creative">Creative</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Style prompt (optional)</label>
                        <textarea value={c.stylePrompt || ''} onChange={(e) => setStudioConfigForTool('ppt', { stylePrompt: e.target.value })} placeholder="Leave empty for preset" rows={2} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 resize-none" />
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'mindmap' && (() => {
                  const c = getStudioConfig('mindmap');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM model</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('mindmap', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Mind map style</label>
                        <select value={c.mindmapStyle || 'default'} onChange={(e) => setStudioConfigForTool('mindmap', { mindmapStyle: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="default">Default</option>
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
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM model</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('drawio', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Diagram type</label>
                        <select value={c.diagramType || 'auto'} onChange={(e) => setStudioConfigForTool('drawio', { diagramType: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="auto">Auto</option>
                          <option value="flowchart">Flowchart</option>
                          <option value="architecture">Architecture</option>
                          <option value="sequence">Sequence</option>
                          <option value="mindmap">Mind map</option>
                          <option value="er">ER diagram</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Diagram style</label>
                        <select value={c.diagramStyle || 'default'} onChange={(e) => setStudioConfigForTool('drawio', { diagramStyle: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="default">Default</option>
                          <option value="minimal">Minimal</option>
                          <option value="sketch">Sketch</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Language</label>
                        <select value={c.language || 'zh'} onChange={(e) => setStudioConfigForTool('drawio', { language: e.target.value })} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                          <option value="zh">Chinese</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                    </>
                  );
                })()}
                {studioSettingsTool === 'podcast' && (() => {
                  const c = getStudioConfig('podcast');
                  return (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">LLM model</label>
                        <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('podcast', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">TTS model</label>
                        <input type="text" value={c.ttsModel || ''} onChange={(e) => setStudioConfigForTool('podcast', { ttsModel: e.target.value })} placeholder="gemini-2.5-pro-preview-tts" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Voice A</label>
                        <input type="text" value={c.voiceName || ''} onChange={(e) => setStudioConfigForTool('podcast', { voiceName: e.target.value })} placeholder="Kore" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Voice B</label>
                        <input type="text" value={c.voiceNameB || ''} onChange={(e) => setStudioConfigForTool('podcast', { voiceNameB: e.target.value })} placeholder="Puck" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </>
                  );
                })()}
                {/* Video narration temporarily disabled
                {studioSettingsTool === 'video' && (() => {
                  const c = getStudioConfig('video');
                  return (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">LLM model</label>
                      <input type="text" value={c.llmModel || ''} onChange={(e) => setStudioConfigForTool('video', { llmModel: e.target.value })} placeholder="deepseek-v3.2" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500" />
                    </div>
                  );
                })()}
                */}
              </div>
              <button type="button" onClick={() => { setStudioPanelView('tools'); setStudioSettingsTool(null); }} className="mt-4 w-full py-2.5 bg-blue-500 text-white text-sm font-medium rounded-lg hover:bg-blue-600">
                Save & back
              </button>
            </div>
          ) : (
          <div className="flex-1 overflow-y-auto p-4">
            <div className="grid grid-cols-2 gap-3 mb-4">
              {studioTools.map(tool => (
                <div
                  key={tool.id}
                  onClick={() => setActiveTool(tool.id)}
                  className={`relative p-4 rounded-xl border transition-all cursor-pointer ${
                    activeTool === tool.id ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-gray-100 hover:border-blue-200 hover:bg-white'
                  }`}
                >
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-3">
                    {tool.icon}
                  </div>
                  <span className="text-sm font-medium text-gray-700">{tool.label}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setStudioSettingsTool(tool.id as StudioToolId); setStudioPanelView('settings'); }}
                    className="absolute top-2 right-2 min-w-[36px] min-h-[36px] flex items-center justify-center hover:bg-gray-200 rounded-lg transition-colors"
                    title="Tool settings"
                  >
                    <MoreVertical size={16} className="text-gray-500" />
                  </button>
                </div>
              ))}
            </div>
            {activeTool !== 'chat' && activeTool !== 'search' && (
              <button
                type="button"
                onClick={() => handleToolGenerate(activeTool)}
                disabled={selectedIds.size === 0 || toolLoading}
                className="w-full py-2.5 mb-4 bg-black text-white text-sm font-medium rounded-xl hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {toolLoading ? 'Generating…' : 'Generate'}
              </button>
            )}

            {/* Tool Output Display */}
            {toolLoading && (
              <div className="bg-blue-50/30 p-4 rounded-2xl border border-blue-100/50 flex flex-col items-center justify-center py-10 gap-4">
                <div className="relative">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                  <Zap size={12} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-blue-500" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-800">Generating...</p>
                  <p className="text-xs text-gray-500 mt-1">Based on {selectedIds.size} sources</p>
                </div>
              </div>
            )}

            {toolOutput && activeTool === 'mindmap' && toolOutput.mindmap_code && (
              <div className="bg-white border border-gray-200 rounded-xl p-4">
                <MermaidPreview mermaidCode={toolOutput.mindmap_code} title="Mind Map" />
              </div>
            )}

            {toolOutput && activeTool === 'ppt' && (
              <div className="bg-green-50/30 p-4 rounded-2xl border border-green-100/50">
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-800 mb-2">PPT generated</p>
                {getPptDownloadUrl(toolOutput) && (
                    <a 
                      href={getPptDownloadUrl(toolOutput)} 
                      target="_blank" 
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 text-sm"
                    >
                      <FileText size={16} />
                      Download PPT
                    </a>
                  )}
                </div>
              </div>
            )}

            {toolOutput && activeTool === 'podcast' && (
              <div className="bg-purple-50/30 p-4 rounded-2xl border border-purple-100/50">
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-800 mb-2">Podcast generated</p>
                  {(toolOutput.audio_path || toolOutput.audio_url) && (
                    <audio controls className="w-full mt-3" src={toolOutput.audio_path || toolOutput.audio_url} />
                  )}
                </div>
              </div>
            )}

            {toolOutput && activeTool === 'drawio' && toolOutput.xml_content && (
              <div className="bg-teal-50/30 p-4 rounded-2xl border border-teal-100/50">
                <p className="text-sm font-medium text-gray-800">DrawIO diagram generated and added to outputs below. Click to preview.</p>
                {toolOutput.file_path && (
                  <a
                    href={toolOutput.file_path}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 mt-2 text-sm text-teal-600 hover:text-teal-700"
                  >
                    <FileText size={14} />
                    Download .drawio
                  </a>
                )}
              </div>
            )}

            {/* Flashcard Generator */}
            {activeTool === 'flashcard' && !showFlashcardViewer && (
              <FlashcardGenerator
                selectedFiles={files.filter(f => selectedIds.has(f.id)).map(f => f.url || f.name)}
                notebookId={notebook?.id || ''}
                email={effectiveUser.email || ''}
                userId={effectiveUser.id || ''}
                onGenerated={(id: string, cards: any[]) => {
                  setFlashcardSetId(id);
                  setFlashcards(cards);
                  setShowFlashcardViewer(true);
                }}
              />
            )}

            {/* Quiz Generator */}
            {activeTool === 'quiz' && !showQuizContainer && (
              <QuizGenerator
                selectedFiles={files.filter(f => selectedIds.has(f.id)).map(f => f.url || f.name)}
                notebookId={notebook?.id || ''}
                email={effectiveUser.email || ''}
                userId={effectiveUser.id || ''}
                onGenerated={(id: string, questions: any[]) => {
                  setQuizId(id);
                  setQuizQuestions(questions);
                  setShowQuizContainer(true);
                }}
              />
            )}

          {/* Output Feed */}
          {outputFeed.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-700">Outputs</h3>
                <span className="text-xs text-gray-400">Latest {outputFeed.length} items</span>
              </div>
              <div className="space-y-3">
                {outputFeed.map(item => (
                  <div 
                    key={item.id} 
                    className="bg-white border border-gray-200 rounded-xl p-3 hover:shadow-md transition-all cursor-pointer"
                    onClick={() => setPreviewOutput(item)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-medium text-gray-900">{item.title}</div>
                      <div className="text-[10px] text-gray-400">{item.createdAt}</div>
                    </div>
                    <div className="mt-1 text-xs text-gray-500 line-clamp-1">
                      Sources: {item.sources}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      {item.url ? (
                        <>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setPreviewOutput(item);
                            }}
                            className="text-xs px-2.5 py-1 rounded-full bg-green-50 text-green-600 hover:bg-green-100 transition-colors"
                          >
                            Preview
                          </button>
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-xs px-2.5 py-1 rounded-full bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
                          >
                            Download
                          </a>
                        </>
                      ) : (
                        <span className="text-xs text-gray-400">No download link</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          </div>
          )}

          {/* Add note - 暂未使用，先注释
          <div className="p-4 border-t shrink-0">
            <button className="w-full flex items-center justify-center gap-2 py-3 bg-black text-white rounded-full text-sm font-medium hover:bg-gray-800 transition-colors shadow-lg">
              <Plus size={18} />
              Add note
            </button>
          </div>
          */}
        </aside>
      </div>

      {/* API 设置弹窗 */}
      <SettingsModal
        open={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />

      {/* 引入弹框：根据以下内容生成音频概览和视频概览 */}
      {showIntroduceModal && (
        <div
          className="fixed inset-0 z-[300] flex items-center justify-center bg-black/40 p-4"
          onClick={() => {
            setShowIntroduceModal(false);
            setDeepResearchSuccess(null);
            setIntroduceUrlSuccess('');
            setIntroduceTextSuccess('');
            setIntroduceUploadSuccess('');
          }}
        >
          <div
            className="bg-white rounded-2xl shadow-xl border border-gray-200 w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 shrink-0">
              <h2 className="text-base font-semibold text-gray-900 text-center flex-1">
                Add sources: upload, URL, or paste text
              </h2>
              <button
                type="button"
                onClick={() => {
                setShowIntroduceModal(false);
                setDeepResearchSuccess(null);
                setIntroduceUrlSuccess('');
                setIntroduceTextSuccess('');
                setIntroduceUploadSuccess('');
              }}
                className="p-2 hover:bg-gray-100 rounded-lg text-gray-500 hover:text-gray-700 -mr-2"
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
                const label = prov === 'serper' ? 'Serper (Google)' : prov === 'bocha' ? 'Bocha' : `SerpAPI (${eng === 'baidu' ? 'Baidu' : 'Google'})`;
                return (
                  <div className="flex items-center justify-between gap-2 py-1.5 px-3 rounded-lg bg-gray-50 border border-gray-100">
                    <span className="text-xs text-gray-600">Current search provider: {label}</span>
                    <button
                      type="button"
                      onClick={() => { setShowIntroduceModal(false); setShowSettingsModal(true); }}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800"
                    >
                      Settings
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
                  Search & add
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
                        placeholder="Enter query, e.g. latest advances in reinforcement learning"
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
                  {fastResearchLoading && <p className="text-xs text-gray-500">Discovering sources…</p>}
                  {fastResearchError && <p className="text-xs text-red-500">{fastResearchError}</p>}
                  {fastResearchSources.length > 0 && (
                    <div className="space-y-3 pt-1">
                      <p className="text-sm font-medium text-green-700">Fast Research completed!</p>
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
                          Select all sources
                        </label>
                        <button
                          type="button"
                          onClick={importFastResearchSources}
                          disabled={importingSources || fastResearchSelected.size === 0}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                        >
                          {importingSources ? <Loader2 size={14} className="animate-spin" /> : null}
                          + Import
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
                        Report “{deepResearchSuccess.topic}” generated and added to sources.
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
                            Download report
                          </a>
                        )}
                        <button
                          type="button"
                          onClick={() => { setDeepResearchSuccess(null); setShowIntroduceModal(false); }}
                          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700"
                        >
                          OK
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-sm text-gray-600">Search by topic and generate a PDF report, then add to sources.</p>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={deepResearchTopic}
                          onChange={e => { setDeepResearchTopic(e.target.value); setDeepResearchError(''); }}
                          placeholder="Enter research topic to generate report and add to sources"
                          className="flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-purple-500"
                        />
                        <button
                          type="button"
                          onClick={runDeepResearchReport}
                          disabled={deepResearchLoading || !deepResearchTopic.trim()}
                          className="px-4 py-2 bg-purple-600 text-white rounded-xl text-sm font-medium hover:bg-purple-700 disabled:opacity-50 shrink-0 flex items-center gap-2"
                        >
                          {deepResearchLoading ? <Loader2 size={16} className="animate-spin" /> : null}
                          Generate report
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
                  <p className="text-xs font-medium text-gray-600 mb-2">Upload file</p>
                  <label
                    className="flex items-center justify-center gap-2 w-full py-3 px-4 rounded-xl border-2 border-dashed border-gray-200 bg-gray-50/50 hover:bg-gray-100 cursor-pointer transition-colors"
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (e.dataTransfer.files?.length) {
                        handleFileUpload(
                          { target: { files: e.dataTransfer.files } } as any,
                          {
                            onSuccess: () => {
                              setIntroduceUploadSuccess('Uploaded and added to sources');
                              setTimeout(() => { setShowIntroduceModal(false); setIntroduceUploadSuccess(''); }, 2000);
                            }
                          }
                        );
                      }
                    }}
                  >
                    <Upload size={18} className="text-gray-500" />
                    <span className="text-sm font-medium text-gray-700">Click to select or drag and drop files here</span>
                    <input
                      type="file"
                      className="hidden"
                      multiple
                      accept=".pdf,.docx,.pptx,.png,.jpg,.jpeg,.mp4,.md"
                      onChange={(e) => {
                        if (e.target.files?.length) {
                          handleFileUpload(e, {
                            onSuccess: () => {
                              setIntroduceUploadSuccess('Uploaded and added to sources');
                              setTimeout(() => { setShowIntroduceModal(false); setIntroduceUploadSuccess(''); }, 2000);
                            }
                          });
                        }
                      }}
                    />
                  </label>
                  {introduceUploadSuccess && <p className="text-xs text-green-600 mt-1">{introduceUploadSuccess}</p>}
                  <p className="text-xs text-gray-400 mt-1">PDF, images, documents, audio, etc.</p>
                </div>

                {/* 2. 网站：输入 URL，抓取网页正文后引入 */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">Website</p>
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
                      Fetch & add
                    </button>
                  </div>
                  {introduceUrlError && <p className="text-xs text-red-500 mt-1">{introduceUrlError}</p>}
                  {introduceUrlSuccess && <p className="text-xs text-green-600 mt-1">{introduceUrlSuccess}</p>}
                  <p className="text-xs text-gray-400 mt-1">Fetch page content (strip HTML) and add as source</p>
                </div>

                {/* 3. Direct input: paste text */}
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">Direct input</p>
                  <textarea
                    value={introduceText}
                    onChange={(e) => { setIntroduceText(e.target.value); setIntroduceTextError(''); setIntroduceTextSuccess(''); }}
                    placeholder="Paste or type text…"
                    rows={4}
                    className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  />
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-gray-400">Will be added as .md source to notebook</span>
                    <button
                      type="button"
                      onClick={handleAddTextSource}
                      disabled={introduceTextLoading || !introduceText.trim()}
                      className="px-4 py-2 rounded-xl bg-gray-800 text-white text-sm font-medium hover:bg-gray-900 disabled:opacity-50 flex items-center gap-2"
                    >
                      {introduceTextLoading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
                      Add as source
                    </button>
                  </div>
                  {introduceTextError && <p className="text-xs text-red-500 mt-1">{introduceTextError}</p>}
                  {introduceTextSuccess && <p className="text-xs text-green-600 mt-1">{introduceTextSuccess}</p>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 产出预览抽屉 */}
      {previewOutput && (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setPreviewOutput(null)}
        >
          <div
            className={`bg-white rounded-2xl shadow-xl border border-gray-200 overflow-hidden flex flex-col ${
              previewOutput.type === 'drawio'
                ? 'w-[95vw] h-[95vh] min-w-[320px] min-h-[360px]'
                : 'w-[90vw] h-[90vh] max-w-[1600px] max-h-[90vh] min-w-[320px] min-h-[360px]'
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white shrink-0">
              <div>
                <h2 className="text-lg font-semibold text-gray-800">{previewOutput.title}</h2>
                <p className="text-xs text-gray-500 mt-1">Sources: {previewOutput.sources}</p>
              </div>
              <div className="flex items-center gap-2">
                {previewOutput.url && (
                  <a
                    href={previewOutput.url}
                    target="_blank"
                    rel="noreferrer"
                    className="px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
                  >
                    Download
                  </a>
                )}
                <button
                  onClick={() => setPreviewOutput(null)}
                  className="p-2 hover:bg-gray-200 rounded-lg text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <X size={20} />
                </button>
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
                          <p>No PDF preview. Click below to download.</p>
                          {previewOutput.url && (
                            <a
                              href={getSameOriginUrl(previewOutput.url)}
                              target="_blank"
                              rel="noreferrer"
                              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                            >
                              Download file
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
                          <p>PDF preview failed to load</p>
                          <a
                            href={sameOriginPdf}
                            target="_blank"
                            rel="noreferrer"
                            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                          >
                            Open in new tab
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
                        <h3 className="text-xl font-semibold text-gray-900">Knowledge Podcast</h3>
                        <p className="text-sm text-gray-500">{previewOutput.createdAt}</p>
                      </div>
                    </div>
                    <audio
                      controls
                      autoPlay
                      className="w-full"
                      src={previewOutput.url}
                    >
                      Your browser does not support audio playback
                    </audio>
                    <p className="text-xs text-gray-400 mt-4 text-center">
                      You can download the audio file to play locally
                    </p>
                  </div>
                </div>
              )}

              {previewOutput.type === 'mindmap' && previewOutput.mermaidCode && (
                <div className="h-full flex items-center justify-center">
                  <div className="w-full h-full bg-white rounded-xl shadow-lg p-6">
                    <MermaidPreview 
                      mermaidCode={previewOutput.mermaidCode} 
                      title="Mind map preview" 
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
                      Loading diagram…
                    </div>
                  ) : (
                    <div className="p-4 text-center">
                      <p className="text-sm text-gray-600 mb-3">Cannot load inline. Please download to edit.</p>
                      <a
                        href={previewOutput.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 px-4 py-2 bg-teal-500 text-white rounded-lg hover:bg-teal-600 text-sm"
                      >
                        <FileText size={16} />
                        Download .drawio file
                      </a>
                    </div>
                  )}
                </div>
              )}
              {previewOutput.type === 'mindmap' && !previewOutput.mermaidCode && (
                <div className="flex items-center justify-center h-full text-gray-400">
                  {previewLoading ? 'Loading mind map...' : 'No preview'}
                </div>
              )}

              {!previewOutput.url && !previewOutput.mermaidCode && previewOutput.type !== 'mindmap' && (
                <div className="flex items-center justify-center h-full text-gray-400">
                  No preview
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Flashcard Viewer Modal */}
      {showFlashcardViewer && flashcards.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowFlashcardViewer(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
            <FlashcardViewer
              flashcards={flashcards}
              onClose={() => setShowFlashcardViewer(false)}
            />
          </div>
        </div>
      )}

      {/* Quiz Container Modal */}
      {showQuizContainer && quizQuestions.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowQuizContainer(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
            <QuizContainer
              questions={quizQuestions}
              onClose={() => setShowQuizContainer(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default NotebookView;
