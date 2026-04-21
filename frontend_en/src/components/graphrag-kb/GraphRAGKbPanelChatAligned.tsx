/**
 * English GraphRAG KB panel aligned with frontend_zh flow:
 * - index
 * - chat with deferred postprocess
 * - split postprocess: subgraph/judge and Wikidata
 * - merge
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Loader2, Copy, ChevronDown, ChevronRight, Network, Send } from 'lucide-react';
import { getApiSettings } from '../../services/apiSettingsService';
import {
  indexGraphragKb,
  mergeGraphragKb,
  chatGraphragKb,
  chatGraphragKbPostprocess,
  defaultGraphragModel,
  refineGraphragContextRefine,
} from '../../services/graphragKbService';
import type { ChatMessage, ChatResponse, GraphragWorkspacePersist } from '../../types/graphragKb';
import { MermaidPreview } from '../knowledge-base/tools/MermaidPreview';
import { injectMultipleGraphragHighlightsInMarkdown } from '../../utils/graphragMarkdownHighlight';
import {
  extractChunkIdFromText,
  stripGraphragContextNoise,
} from '../../utils/stripGraphragContextNoise';

function getWorkspaceStorageKey(userId: string, notebookId: string) {
  return `graphrag_workspace_${userId}_${notebookId}`;
}

function sanitizeMermaidLabel(s: string, max = 48): string {
  return s.replace(/["[\]#]/g, ' ').slice(0, max).trim() || '?';
}

export function reasoningSubgraphToMermaid(edges: Array<Record<string, unknown>>, maxEdges = 36): string | null {
  if (!edges.length) return null;
  const slice = edges.slice(0, maxEdges);
  const idFor = (() => {
    const m = new Map<string, string>();
    let n = 0;
    return (raw: string) => {
      const k = raw || `_${n}`;
      if (!m.has(k)) m.set(k, `N${n++}`);
      return m.get(k)!;
    };
  })();
  const lines: string[] = [
    '%%{init: {"flowchart": {"htmlLabels": true, "wrappingWidth": 250}} }%%',
    'graph TD',
  ];
  for (let i = 0; i < slice.length; i++) {
    const e = slice[i];
    const src = String(e.source ?? e.src ?? e.from ?? e.head ?? `s${i}`);
    const tgt = String(e.target ?? e.tgt ?? e.to ?? e.tail ?? `t${i}`);
    const rel = String(e.relation ?? e.relationship ?? e.label ?? e.predicate ?? '');
    const sid = idFor(src);
    const tid = idFor(tgt);
    const sl = sanitizeMermaidLabel(src, 40);
    const tl = sanitizeMermaidLabel(tgt, 40);
    const rl = sanitizeMermaidLabel(rel, 60);
    lines.push(`  ${sid}["${sl}"] -->|"${rl}"| ${tid}["${tl}"]`);
  }
  return lines.join('\n');
}

interface ContextChunk {
  chunkId: string;
  text: string;
  nTokens?: number;
  sourceStem?: string;
}

function extractTopChunk(
  contextData: Record<string, unknown>,
  highlightHints: Array<Record<string, unknown>>,
): ContextChunk | null {
  const textUnits =
    (contextData['sources'] as Array<Record<string, unknown>> | undefined) ??
    (contextData['text_units'] as Array<Record<string, unknown>> | undefined);
  if (!textUnits || !Array.isArray(textUnits) || textUnits.length === 0) return null;

  const first = textUnits[0];
  const rawText = String(first['text'] ?? first['content'] ?? '');
  if (!rawText.trim()) return null;

  const docIds = first['document_ids'];
  const sourceStemFromUnit = Array.isArray(docIds) && docIds.length > 0 ? String(docIds[0]) : '';
  const sourceStemFromHint = highlightHints.length > 0 ? String(highlightHints[0]['source_stem'] ?? '') : '';

  const embedded = extractChunkIdFromText(rawText);
  const idField = String(first['id'] ?? first['chunk_id'] ?? '').trim();
  const chunkId = embedded || idField;

  return {
    chunkId,
    text: rawText,
    nTokens: first['n_tokens'] != null ? Number(first['n_tokens']) : undefined,
    sourceStem: sourceStemFromUnit || sourceStemFromHint || undefined,
  };
}

const STR = {
  zh: {
    headerTitle: 'GraphRAG 知识库',
    headerSub: '分块（MinerU）+ GraphRAG 建索引与检索',
    apiWarn: '请先在设置中配置 API URL 与 API Key',
    noNotebook: '缺少笔记本 ID',
    indexBtn: '构建索引',
    indexing: '索引构建中…',
    indexOk: '索引构建完成',
    forceReindex: '强制重建',
    parsePdfs: '解析 PDF（MinerU）',
    summary: '上次索引摘要',
    chunks: '分块数',
    workspace: '工作区目录',
    copy: '复制',
    copied: '已复制',
    modelLabel: 'LLM 模型名',
    copyFailed: '复制失败',
    mergeTitle: '合并工作区',
    mergeA: 'workspace_dir A',
    mergeB: 'workspace_dir B',
    dedupe: '去重合并',
    mergeBtn: '合并并重建索引',
    merging: '合并中…',
    mergeOk: '合并完成',
    chatPlaceholder: '向知识库提问…',
    send: '发送',
    searchMethodLabel: '检索策略',
    wikidataEnrich: 'Wikidata 参考（附在答案后）',
    clearChat: '清空对话',
    emptyReady: '索引已就绪，开始提问吧',
    emptyNoIndex: '请先完成索引构建',
    contextRefTitle: '上下文参考',
    subgraph: '推理子图',
    subgraphRaw: '推理全图（未裁剪版）',
    noSubgraph: '无子图数据',
    subgraphCot: '最小子图推理（CoT / 跳数）',
    mermaidTitle: '子图（Mermaid）',
    judge: 'Judge 分数',
    postprocessSubgraphPending: '正在裁剪子图…',
    postprocessWikidataPending: '正在补充 Wikidata 参考…',
  },
  en: {
    headerTitle: 'GraphRAG Knowledge Base',
    headerSub: 'Chunking (MinerU) + GraphRAG index & query',
    apiWarn: 'Configure API URL and API Key in Settings first',
    noNotebook: 'Notebook ID is missing',
    indexBtn: 'Build index',
    indexing: 'Indexing…',
    indexOk: 'Index completed',
    forceReindex: 'Force reindex',
    parsePdfs: 'Parse PDFs (MinerU)',
    summary: 'Last index summary',
    chunks: 'Chunks',
    workspace: 'Workspace directory',
    copy: 'Copy',
    copied: 'Copied',
    modelLabel: 'LLM model',
    copyFailed: 'Copy failed',
    mergeTitle: 'Merge workspaces',
    mergeA: 'workspace_dir A',
    mergeB: 'workspace_dir B',
    dedupe: 'Deduplicate when merging',
    mergeBtn: 'Merge and re-index',
    merging: 'Merging…',
    mergeOk: 'Merge completed',
    chatPlaceholder: 'Ask the knowledge base…',
    send: 'Send',
    searchMethodLabel: 'Search method',
    wikidataEnrich: 'Wikidata supplement (after answer)',
    clearChat: 'Clear chat',
    emptyReady: 'Index ready. Start asking questions.',
    emptyNoIndex: 'Build the index first.',
    contextRefTitle: 'Context Reference',
    subgraph: 'Reasoning subgraph',
    subgraphRaw: 'Full reasoning graph (unpruned)',
    noSubgraph: 'No subgraph',
    subgraphCot: 'Minimal subgraph reasoning (CoT / hops)',
    mermaidTitle: 'Subgraph (Mermaid)',
    judge: 'Judge score',
    postprocessSubgraphPending: 'Pruning subgraph…',
    postprocessWikidataPending: 'Enriching Wikidata supplement…',
  },
} as const;

function ContextRefHtml({
  topChunk,
  subgraph,
  userId,
  colorIdx,
  locale,
}: {
  topChunk: ContextChunk;
  subgraph: Array<Record<string, unknown>>;
  userId: string | null;
  colorIdx: number;
  locale: 'zh' | 'en';
}) {
  const basePlain = useMemo(() => stripGraphragContextNoise(topChunk.text), [topChunk.text]);
  const [html, setHtml] = useState<string>(basePlain);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setHtml(basePlain);
    if (!subgraph?.length) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const st = getApiSettings(userId);
        const out = await refineGraphragContextRefine(
          topChunk.text,
          subgraph,
          st?.apiKey?.trim() || '',
          st?.apiUrl?.trim() || '',
          defaultGraphragModel(),
        );
        if (cancelled) return;
        const body = (out.cleaned_text || '').trim() || basePlain;
        const snips = (out.supporting_snippets || []).map((s) => s.trim()).filter(Boolean);
        if (snips.length) {
          setHtml(injectMultipleGraphragHighlightsInMarkdown(body, snips, { baseColorIndex: colorIdx }));
        } else {
          setHtml(body);
        }
      } catch {
        if (!cancelled) setHtml(basePlain);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [topChunk.chunkId, subgraph, basePlain, userId, colorIdx, topChunk.text]);

  return (
    <div className="space-y-1">
      {loading ? (
        <div className="text-[11px] text-amber-700/90">
          {locale === 'zh' ? '正在清洗正文并选取支撑句…' : 'Cleaning passage and selecting evidence…'}
        </div>
      ) : null}
      <div
        className="text-xs text-ios-gray-800 leading-relaxed whitespace-pre-wrap break-words max-h-48 overflow-y-auto"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

interface AssistantMetaProps {
  meta: NonNullable<ChatMessage['meta']>;
  locale: 'zh' | 'en';
  L: typeof STR['zh'];
  userId: string | null;
  subgraphPending: boolean;
}

function AssistantMeta({ meta, locale, L, userId, subgraphPending }: AssistantMetaProps) {
  const topChunk = useMemo(() => {
    if (!meta.context_data) return null;
    return extractTopChunk(
      meta.context_data as Record<string, unknown>,
      (meta.highlight_hints ?? []) as Array<Record<string, unknown>>,
    );
  }, [meta.context_data, meta.highlight_hints]);

  const mermaidCode = useMemo(() => {
    if (!meta.reasoning_subgraph?.length) return null;
    return reasoningSubgraphToMermaid(meta.reasoning_subgraph as Array<Record<string, unknown>>);
  }, [meta.reasoning_subgraph]);

  const subgraphRows = (meta.reasoning_subgraph ?? []) as Array<Record<string, unknown>>;
  const judgePct = Math.round(Math.max(0, Math.min(1, meta.judge_score ?? 0)) * 100);
  const [subgraphOpen, setSubgraphOpen] = useState(false);

  return (
    <div className="mt-3 space-y-3">
      {meta.intent?.use_graphrag === false && (
        <div className="inline-flex items-center gap-1 text-[11px] text-ios-gray-400 bg-ios-gray-50 rounded px-2 py-0.5">
          {locale === 'zh' ? '直接回答（无检索）' : 'Direct answer (no retrieval)'}
        </div>
      )}
      {meta.intent?.use_graphrag === true && meta.rewritten_query && (
        <div className="text-[11px] text-ios-gray-400">
          <span className="font-medium">{locale === 'zh' ? '检索问题：' : 'Retrieval query: '}</span>
          {meta.rewritten_query}
        </div>
      )}

      {topChunk && (
        <div className="rounded-xl bg-amber-50 border border-amber-100 p-3 space-y-1.5">
          <div className="text-xs font-semibold text-amber-800">{L.contextRefTitle}</div>
          {topChunk.sourceStem && (
            <div className="flex items-center gap-2 text-xs text-amber-700">
              <code className="bg-amber-100/60 px-1.5 py-0.5 rounded text-[11px]">{topChunk.sourceStem}</code>
              {topChunk.nTokens != null && (
                <span className="text-amber-500">{topChunk.nTokens} tokens</span>
              )}
            </div>
          )}
          <ContextRefHtml
            topChunk={topChunk}
            subgraph={subgraphRows}
            userId={userId}
            colorIdx={0}
            locale={locale}
          />
        </div>
      )}

      {mermaidCode && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setSubgraphOpen(!subgraphOpen)}
            className="flex items-center gap-1 text-xs font-semibold text-ios-gray-700"
          >
            {subgraphOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {subgraphPending ? L.subgraphRaw : L.subgraph}
          </button>
          {subgraphOpen && (
            <>
              <div className="bg-slate-900 rounded-xl p-2">
                <MermaidPreview mermaidCode={mermaidCode} title={L.mermaidTitle} />
              </div>
              {meta.reasoning_subgraph_cot ? (
                <details className="text-xs rounded-lg border border-ios-gray-100 bg-ios-gray-50/60 p-3">
                  <summary className="cursor-pointer font-medium text-ios-gray-700 select-none">{L.subgraphCot}</summary>
                  <div className="mt-2 text-ios-gray-800 whitespace-pre-wrap break-words">
                    <ReactMarkdown>{meta.reasoning_subgraph_cot}</ReactMarkdown>
                  </div>
                </details>
              ) : null}
            </>
          )}
        </div>
      )}

      {judgePct > 0 && (
        <div className="rounded-xl bg-sky-50 border border-sky-100 px-3 py-2 text-xs">
          <div className="font-medium text-sky-900">{L.judge}: {judgePct}%</div>
          {meta.judge_rationale ? (
            <div className="text-sky-800 mt-0.5 opacity-90">{meta.judge_rationale}</div>
          ) : null}
        </div>
      )}
    </div>
  );
}

export type GraphragOpenSourcePayload = {
  sourceStem: string;
  pageIndex: number;
  chunkId?: string;
  workspaceDir?: string;
};

export interface GraphRAGKbPanelProps {
  notebook: { id?: string; title?: string; name?: string };
  userId: string | null;
  email: string;
  locale?: 'zh' | 'en';
  showToast: (message: string, type?: 'success' | 'error' | 'warning') => void;
  onOpenGraphragSource?: (payload: GraphragOpenSourcePayload) => void | Promise<void>;
}

export function GraphRAGKbPanel({
  notebook,
  userId,
  email,
  locale = 'en',
  showToast,
}: GraphRAGKbPanelProps) {
  const L = STR[locale];
  const notebookId = notebook?.id || '';
  const notebookTitle = notebook?.title || notebook?.name || '';

  const [persist, setPersist] = useState<GraphragWorkspacePersist | null>(null);
  const [forceReindex, setForceReindex] = useState(false);
  const [parsePdfs, setParsePdfs] = useState(true);
  const [indexLoading, setIndexLoading] = useState(false);
  const [modelName, setModelName] = useState(defaultGraphragModel());

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [searchMethod, setSearchMethod] = useState<'auto' | 'local' | 'global'>('auto');
  const [wikidataEnrich, setWikidataEnrich] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const v = localStorage.getItem('graphrag_wikidata_enrich');
      if (v !== null) setWikidataEnrich(v === '1' || v === 'true');
    } catch {
      // keep default
    }
  }, []);

  const [mergeA, setMergeA] = useState('');
  const [mergeB, setMergeB] = useState('');
  const [mergeDedupe, setMergeDedupe] = useState(false);
  const [mergeLoading, setMergeLoading] = useState(false);

  const storageKey = useMemo(() => {
    const uid = userId || 'global';
    if (!notebookId) return null;
    return getWorkspaceStorageKey(uid, notebookId);
  }, [userId, notebookId]);

  const loadPersist = useCallback(() => {
    if (!storageKey) { setPersist(null); return; }
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) { setPersist(null); return; }
      const p = JSON.parse(raw) as GraphragWorkspacePersist;
      if (p?.workspace_dir) setPersist(p); else setPersist(null);
    } catch { setPersist(null); }
  }, [storageKey]);

  useEffect(() => { loadPersist(); }, [loadPersist]);
  useEffect(() => { if (persist?.workspace_dir) setMergeA((a) => (a ? a : persist.workspace_dir)); }, [persist?.workspace_dir]);

  const llmBody = useCallback(() => {
    const settings = getApiSettings(userId);
    const api_url = settings?.apiUrl?.trim() || '';
    const api_key = settings?.apiKey?.trim() || '';
    const model = modelName.trim() || defaultGraphragModel();
    return { api_url, api_key, model };
  }, [userId, modelName]);

  const copyText = async (text: string, okMsg?: string) => {
    try { await navigator.clipboard.writeText(text); showToast(okMsg || L.copied, 'success'); }
    catch { showToast(L.copyFailed, 'error'); }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, chatLoading]);

  const handleIndex = async () => {
    if (!notebookId) { showToast(L.noNotebook, 'warning'); return; }
    const { api_url, api_key, model } = llmBody();
    if (!api_url || !api_key) { showToast(L.apiWarn, 'warning'); return; }
    setIndexLoading(true);
    try {
      const res = await indexGraphragKb({
        notebook_id: notebookId, notebook_title: notebookTitle, email: email || '',
        api_url, api_key, model,
        source_stems: null, workspace_dir: persist?.workspace_dir || '',
        force_reindex: forceReindex, parse_pdfs: parsePdfs, skip_kggen: true,
      });
      const next: GraphragWorkspacePersist = { workspace_dir: res.workspace_dir, updatedAt: Date.now(), num_chunks: res.num_chunks };
      if (storageKey) localStorage.setItem(storageKey, JSON.stringify(next));
      setPersist(next);
      showToast(L.indexOk, 'success');
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    } finally { setIndexLoading(false); }
  };

  const handleChat = async () => {
    const userInput = inputValue.trim();
    if (!userInput || chatLoading) return;
    if (!persist?.workspace_dir) {
      showToast(locale === 'zh' ? '请先完成索引构建' : 'Build the index first', 'warning');
      return;
    }
    const { api_url, api_key, model } = llmBody();
    if (!api_url || !api_key) { showToast(L.apiWarn, 'warning'); return; }

    const history = messages.map((m) => ({
      role: m.role,
      content: m.content,
      ...(m.meta ? { meta: { ...m.meta } } : {}),
    }));
    const userMsg: ChatMessage = { id: `u_${Date.now()}`, role: 'user', content: userInput };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setChatLoading(true);

    try {
      const resp: ChatResponse = await chatGraphragKb({
        notebook_id: notebookId, notebook_title: notebookTitle, email: email || '',
        query: userInput, history, search_method: searchMethod,
        workspace_dir: persist.workspace_dir, api_url, api_key, model,
        wikidata_enrich: wikidataEnrich,
        defer_postprocess: true,
      });
      const assistantId = `a_${Date.now()}`;
      const assistantMsg: ChatMessage = {
        id: assistantId, role: 'assistant', content: resp.answer,
        meta: {
          intent: resp.intent,
          rewritten_query: resp.rewritten_query,
          graphrag_raw_answer: resp.graphrag_raw_answer || '',
          context_data: resp.context_data,
          reasoning_subgraph: resp.reasoning_subgraph,
          reasoning_subgraph_cot: resp.reasoning_subgraph_cot,
          judge_score: resp.judge_score,
          judge_rationale: resp.judge_rationale,
          source_chunks: resp.source_chunks,
          highlight_hints: resp.highlight_hints,
        },
        postprocessPending: !!resp.postprocess_pending,
        postprocessSubgraphPending: !!resp.postprocess_pending,
        postprocessWikidataPending: !!resp.postprocess_pending && wikidataEnrich,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      if (resp.postprocess_pending) {
        chatGraphragKbPostprocess({
          query: resp.rewritten_query || userInput,
          answer: resp.graphrag_raw_answer || '',
          reasoning_subgraph: (resp.reasoning_subgraph || []) as Array<Record<string, unknown>>,
          api_url,
          api_key,
          model,
          wikidata_enrich: wikidataEnrich,
          mode: 'subgraph',
        })
          .then((pp) => {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId || m.role !== 'assistant') return m;
              return {
                ...m,
                postprocessSubgraphPending: false,
                postprocessPending: !!m.postprocessWikidataPending,
                meta: {
                  ...(m.meta || {}),
                  reasoning_subgraph: pp.reasoning_subgraph,
                  reasoning_subgraph_cot: pp.reasoning_subgraph_cot,
                  judge_score: pp.judge_score,
                  judge_rationale: pp.judge_rationale,
                },
              };
            }));
          })
          .catch((e) => {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId || m.role !== 'assistant') return m;
              return {
                ...m,
                postprocessSubgraphPending: false,
                postprocessPending: !!m.postprocessWikidataPending,
                meta: {
                  ...(m.meta || {}),
                  judge_rationale: String(e),
                },
              };
            }));
          });

        if (wikidataEnrich) {
          chatGraphragKbPostprocess({
            query: resp.rewritten_query || userInput,
            answer: resp.graphrag_raw_answer || '',
            reasoning_subgraph: (resp.reasoning_subgraph || []) as Array<Record<string, unknown>>,
            api_url,
            api_key,
            model,
            wikidata_enrich: true,
            mode: 'wikidata',
          })
            .then((pp) => {
              setMessages((prev) => prev.map((m) => {
                if (m.id !== assistantId || m.role !== 'assistant') return m;
                const appendix = (pp.wikidata_appendix || '').trim();
                const base = m.content || '';
                const nextContent = appendix ? `${base}\n\n${appendix}` : base;
                return {
                  ...m,
                  content: nextContent,
                  postprocessWikidataPending: false,
                  postprocessPending: !!m.postprocessSubgraphPending,
                };
              }));
            })
            .catch(() => {
              setMessages((prev) => prev.map((m) => {
                if (m.id !== assistantId || m.role !== 'assistant') return m;
                return {
                  ...m,
                  postprocessWikidataPending: false,
                  postprocessPending: !!m.postprocessSubgraphPending,
                };
              }));
            });
        }
      }
    } catch (err) {
      showToast(String(err), 'error');
      setMessages((prev) => prev.slice(0, -1));
      setInputValue(userInput);
    } finally { setChatLoading(false); }
  };

  const handleMerge = async () => {
    if (!notebookId) { showToast(L.noNotebook, 'warning'); return; }
    const a = mergeA.trim(); const b = mergeB.trim();
    if (!a || !b) { showToast(locale === 'zh' ? '请填写两个 workspace 路径' : 'Enter both workspace paths', 'warning'); return; }
    const { api_url, api_key, model } = llmBody();
    if (!api_url || !api_key) { showToast(L.apiWarn, 'warning'); return; }
    setMergeLoading(true);
    try {
      const res = await mergeGraphragKb({
        notebook_id: notebookId, notebook_title: notebookTitle, email: email || '',
        api_url, api_key, model, workspace_dir_a: a, workspace_dir_b: b, dedupe: mergeDedupe,
      });
      const next: GraphragWorkspacePersist = { workspace_dir: res.merged_workspace_dir, updatedAt: Date.now(), num_chunks: res.num_chunks };
      if (storageKey) localStorage.setItem(storageKey, JSON.stringify(next));
      setPersist(next);
      setMergeA(res.merged_workspace_dir);
      showToast(L.mergeOk, 'success');
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    } finally { setMergeLoading(false); }
  };

  return (
    <main className="flex-1 flex flex-col relative bg-white min-w-[300px] overflow-hidden">
      <div className="flex items-center gap-2 px-6 py-3 border-b border-ios-gray-100 shrink-0">
        <Network className="text-cyan-600" size={20} />
        <div>
          <div className="text-sm font-medium text-ios-gray-900">{L.headerTitle}</div>
          <div className="text-xs text-ios-gray-400">{L.headerSub}</div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-[960px] w-full mx-auto">
        <section className="rounded-2xl border border-ios-gray-100 bg-ios-gray-50/40 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-ios-gray-800">{L.indexBtn}</h3>
          <div className="flex flex-wrap gap-4 items-center text-sm">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={forceReindex} onChange={(e) => setForceReindex(e.target.checked)} />
              {L.forceReindex}
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={parsePdfs} onChange={(e) => setParsePdfs(e.target.checked)} />
              {L.parsePdfs}
            </label>
          </div>
          <div>
            <label className="block text-xs font-medium text-ios-gray-500 mb-1">{L.modelLabel}</label>
            <input
              value={modelName} onChange={(e) => setModelName(e.target.value)}
              className="w-full max-w-md px-3 py-2 border border-ios-gray-200 rounded-lg text-sm"
              placeholder={defaultGraphragModel()}
            />
          </div>
          <button
            type="button" disabled={indexLoading || !notebookId} onClick={handleIndex}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-ios bg-slate-900 text-white text-sm font-medium disabled:opacity-50"
          >
            {indexLoading ? <Loader2 size={16} className="animate-spin" /> : null}
            {indexLoading ? L.indexing : L.indexBtn}
          </button>

          {persist && (
            <div className="mt-4 rounded-xl border border-ios-gray-200 bg-white p-3 text-xs space-y-2">
              <div className="font-medium text-ios-gray-700">{L.summary}</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-ios-gray-600">
                <span>{L.chunks}: <b>{persist.num_chunks ?? '—'}</b></span>
              </div>
              <div className="flex items-start gap-2 break-all">
                <span className="shrink-0 text-ios-gray-500">{L.workspace}:</span>
                <code className="flex-1 text-[11px] bg-ios-gray-50 p-2 rounded">{persist.workspace_dir}</code>
                <button type="button" onClick={() => copyText(persist.workspace_dir)} className="shrink-0 p-1.5 rounded border border-ios-gray-200 hover:bg-ios-gray-50" title={L.copy}>
                  <Copy size={14} />
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-ios-gray-100 overflow-hidden">
          <div className="flex items-center gap-3 px-4 py-2 border-b border-ios-gray-100 bg-ios-gray-50/40 text-xs">
            <span className="text-ios-gray-500">{L.searchMethodLabel}</span>
            <select
              value={searchMethod} onChange={(e) => setSearchMethod(e.target.value as typeof searchMethod)}
              className="px-2 py-1 border border-ios-gray-200 rounded text-xs"
            >
              <option value="auto">Auto</option>
              <option value="local">Local</option>
              <option value="global">Global</option>
            </select>
            <label className="flex items-center gap-1.5 cursor-pointer shrink-0">
              <input
                type="checkbox"
                checked={wikidataEnrich}
                onChange={(e) => {
                  const c = e.target.checked;
                  setWikidataEnrich(c);
                  try {
                    localStorage.setItem('graphrag_wikidata_enrich', c ? '1' : '0');
                  } catch {
                    // ignore
                  }
                }}
              />
              <span className="text-ios-gray-600">{L.wikidataEnrich}</span>
            </label>
            <button
              type="button" onClick={() => setMessages([])}
              className="ml-auto text-ios-gray-400 hover:text-ios-gray-600 text-[11px]"
            >
              {L.clearChat}
            </button>
          </div>

          <div className="min-h-[min(520px,55vh)] max-h-[min(960px,78vh)] overflow-y-auto px-4 py-4 space-y-4">
            {messages.length === 0 && (
              <div className="text-center text-xs text-ios-gray-400 py-12">
                {persist?.workspace_dir ? L.emptyReady : L.emptyNoIndex}
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm ${
                  msg.role === 'user'
                    ? 'bg-primary text-white rounded-br-sm'
                    : 'bg-ios-gray-50 text-ios-gray-900 rounded-bl-sm border border-ios-gray-100'
                }`}>
                  {msg.role === 'user' ? (
                    <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                  ) : (
                    <div>
                      <div className="prose prose-sm max-w-none">
                        <ReactMarkdown>{msg.content || '—'}</ReactMarkdown>
                      </div>
                      {msg.meta && (
                        <AssistantMeta
                          meta={msg.meta}
                          locale={locale}
                          L={L}
                          userId={userId}
                          subgraphPending={!!msg.postprocessSubgraphPending}
                        />
                      )}
                      {msg.postprocessSubgraphPending ? (
                        <div className="mt-2 text-[11px] text-amber-700/90 flex items-center gap-1">
                          <Loader2 size={12} className="animate-spin" />
                          {L.postprocessSubgraphPending}
                        </div>
                      ) : null}
                      {msg.postprocessWikidataPending ? (
                        <div className="mt-1 text-[11px] text-amber-700/90 flex items-center gap-1">
                          <Loader2 size={12} className="animate-spin" />
                          {L.postprocessWikidataPending}
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="flex justify-start">
                <div className="bg-ios-gray-50 border border-ios-gray-100 rounded-2xl rounded-bl-sm px-4 py-3">
                  <Loader2 size={16} className="animate-spin text-ios-gray-400" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-ios-gray-100 px-4 py-3 flex gap-2 items-end">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChat(); } }}
              rows={3} placeholder={L.chatPlaceholder}
              className="flex-1 px-3 py-2 border border-ios-gray-200 rounded-xl text-sm resize-none"
            />
            <button
              type="button" disabled={chatLoading || !inputValue.trim()} onClick={handleChat}
              className="px-4 py-2 rounded-xl bg-primary text-white text-sm font-medium disabled:opacity-50 shrink-0"
            >
              {chatLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
        </section>

        <section className="rounded-2xl border border-dashed border-ios-gray-200 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-ios-gray-800">{L.mergeTitle}</h3>
          <div>
            <label className="block text-xs text-ios-gray-500 mb-1">{L.mergeA}</label>
            <textarea value={mergeA} onChange={(e) => setMergeA(e.target.value)} rows={2}
              className="w-full px-3 py-2 border border-ios-gray-200 rounded-lg text-xs font-mono" />
          </div>
          <div>
            <label className="block text-xs text-ios-gray-500 mb-1">{L.mergeB}</label>
            <textarea value={mergeB} onChange={(e) => setMergeB(e.target.value)} rows={2}
              className="w-full px-3 py-2 border border-ios-gray-200 rounded-lg text-xs font-mono" />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={mergeDedupe} onChange={(e) => setMergeDedupe(e.target.checked)} />
            {L.dedupe}
          </label>
          <button
            type="button" disabled={mergeLoading} onClick={handleMerge}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-ios border border-ios-gray-300 text-sm font-medium disabled:opacity-50"
          >
            {mergeLoading ? <Loader2 size={16} className="animate-spin" /> : null}
            {mergeLoading ? L.merging : L.mergeBtn}
          </button>
        </section>
      </div>
    </main>
  );
}

