/**
 * GraphRAG 知识库侧栏 UI：索引构建、Local/Global 查询、推理子图展示、文档定位卡片、合并工作区。
 *
 * 数据流：用户操作 → ``graphragKbService`` → 后端管线 → ``queryResult`` 状态；
 * 「在知识库中打开」通过 ``onOpenGraphragSource`` 回调把 sourceStem、chunkId、workspaceDir 交给 NotebookView，联动阅读器与高亮。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Loader2, Copy, Download, ChevronDown, ChevronRight, Network, ExternalLink } from 'lucide-react';
import { getApiSettings } from '../../services/apiSettingsService';
import {
  indexGraphragKb,
  queryGraphragKb,
  mergeGraphragKb,
  defaultGraphragModel,
} from '../../services/graphragKbService';
import type { QueryResponse, GraphragWorkspacePersist } from '../../types/graphragKb';
import { MermaidPreview } from '../knowledge-base/tools/MermaidPreview';

const KNOWN_HINT_KEYS = ['page', 'page_num', 'bbox', 'sentence', 'text', 'chunk_id', 'source', 'file', 'file_name'];

/** 与阅读器联动时传入的载荷（source_stem 对应知识库里的文件名 stem） */
export type GraphragOpenSourcePayload = {
  sourceStem: string;
  pageIndex: number;
  chunkId?: string;
  /** 当前笔记本 GraphRAG 工作区根目录，用于拉取 ``[chunk:…]`` 原文高亮 */
  workspaceDir?: string;
};

function _parsePageIndex(v: unknown): number | undefined {
  if (typeof v === 'number' && !Number.isNaN(v)) return v;
  if (typeof v === 'string') {
    const n = parseInt(v, 10);
    return Number.isNaN(n) ? undefined : n;
  }
  return undefined;
}

function getWorkspaceStorageKey(userId: string, notebookId: string) {
  return `graphrag_workspace_${userId}_${notebookId}`;
}

function sanitizeMermaidLabel(s: string, max = 48): string {
  return s.replace(/["[\]#]/g, ' ').slice(0, max).trim() || '?';
}

/** 将 reasoning_subgraph 转为 Mermaid graph LR（边数上限避免卡顿） */
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
  const lines: string[] = ['graph LR'];
  for (let i = 0; i < slice.length; i++) {
    const e = slice[i];
    const src = String(e.source ?? e.src ?? e.from ?? e.head ?? `s${i}`);
    const tgt = String(e.target ?? e.tgt ?? e.to ?? e.tail ?? `t${i}`);
    const rel = String(e.relation ?? e.relationship ?? e.label ?? e.predicate ?? '');
    const sid = idFor(src);
    const tid = idFor(tgt);
    const sl = sanitizeMermaidLabel(src);
    const tl = sanitizeMermaidLabel(tgt);
    const rl = sanitizeMermaidLabel(rel, 24);
    lines.push(`  ${sid}["${sl}"] -->|"${rl}"| ${tid}["${tl}"]`);
  }
  return lines.join('\n');
}

const STR = {
  zh: {
    headerTitle: 'GraphRAG 知识库',
    headerSub: '分块（MinerU）+ GraphRAG 建索引与检索（用户路径不含 KGGen）',
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
    queryQ: '问题',
    queryPlaceholder: '输入要问的问题…',
    searchLocal: 'Local',
    searchGlobal: 'Global',
    queryBtn: '查询',
    querying: '查询中…',
    answer: '回答',
    judge: 'Judge 分数',
    rationale: '说明',
    subgraph: '推理子图',
    viewTable: '表格',
    viewMermaid: 'Mermaid',
    viewJson: 'JSON',
    noSubgraph: '无子图数据',
    subgraphCot: '最小子图推理（CoT / 跳数）',
    hintDoc: '文档',
    hintPage: '页码',
    hintBbox: '区域框',
    openInKb: '在知识库中打开',
    hints: '文档定位',
    context: 'context_data（体积可能较大）',
    downloadJson: '下载 JSON',
    copyJson: '复制 JSON',
    mergeTitle: '合并工作区',
    mergeA: 'workspace_dir A',
    mergeB: 'workspace_dir B',
    dedupe: '去重合并',
    mergeBtn: '合并并重建索引',
    merging: '合并中…',
    mergeOk: '合并完成',
    modelLabel: 'LLM 模型名',
    mermaidTitle: '子图（Mermaid）',
    copyFailed: '复制失败',
  },
  en: {
    headerTitle: 'GraphRAG Knowledge Base',
    headerSub: 'Chunking (MinerU) + GraphRAG index & query (no KGGen on the default path)',
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
    queryQ: 'Question',
    queryPlaceholder: 'Ask a question…',
    searchLocal: 'Local',
    searchGlobal: 'Global',
    queryBtn: 'Query',
    querying: 'Querying…',
    answer: 'Answer',
    judge: 'Judge score',
    rationale: 'Rationale',
    subgraph: 'Reasoning subgraph',
    viewTable: 'Table',
    viewMermaid: 'Mermaid',
    viewJson: 'JSON',
    noSubgraph: 'No subgraph',
    subgraphCot: 'Minimal subgraph reasoning (CoT / hops)',
    hintDoc: 'Document',
    hintPage: 'Page',
    hintBbox: 'BBox',
    openInKb: 'Open in knowledge base',
    hints: 'Source location',
    context: 'context_data (may be large)',
    downloadJson: 'Download JSON',
    copyJson: 'Copy JSON',
    mergeTitle: 'Merge workspaces',
    mergeA: 'workspace_dir A',
    mergeB: 'workspace_dir B',
    dedupe: 'Deduplicate when merging',
    mergeBtn: 'Merge and re-index',
    merging: 'Merging…',
    mergeOk: 'Merge completed',
    modelLabel: 'LLM model',
    mermaidTitle: 'Subgraph (Mermaid)',
    copyFailed: 'Copy failed',
  },
} as const;

export interface GraphRAGKbPanelProps {
  notebook: { id?: string; title?: string; name?: string };
  userId: string | null;
  email: string;
  locale?: 'zh' | 'en';
  showToast: (message: string, type?: 'success' | 'error' | 'warning') => void;
  /** 在笔记本侧栏打开对应来源并展示 MinerU 解析内容（按 stem 匹配文件名） */
  onOpenGraphragSource?: (payload: GraphragOpenSourcePayload) => void | Promise<void>;
}

export function GraphRAGKbPanel({
  notebook,
  userId,
  email,
  locale = 'zh',
  showToast,
  onOpenGraphragSource,
}: GraphRAGKbPanelProps) {
  const L = STR[locale];
  const notebookId = notebook?.id || '';
  const notebookTitle = notebook?.title || notebook?.name || '';

  const [persist, setPersist] = useState<GraphragWorkspacePersist | null>(null);
  const [forceReindex, setForceReindex] = useState(false);
  const [parsePdfs, setParsePdfs] = useState(true);
  const [indexLoading, setIndexLoading] = useState(false);
  const [modelName, setModelName] = useState(defaultGraphragModel());

  const [question, setQuestion] = useState('');
  const [searchMethod, setSearchMethod] = useState<'local' | 'global'>('local');
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [subView, setSubView] = useState<'table' | 'mermaid' | 'json'>('table');
  const [contextOpen, setContextOpen] = useState(false);

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
    if (!storageKey) {
      setPersist(null);
      return;
    }
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) {
        setPersist(null);
        return;
      }
      const p = JSON.parse(raw) as GraphragWorkspacePersist;
      if (p?.workspace_dir) setPersist(p);
      else setPersist(null);
    } catch {
      setPersist(null);
    }
  }, [storageKey]);

  useEffect(() => {
    loadPersist();
  }, [loadPersist]);

  useEffect(() => {
    if (persist?.workspace_dir) {
      setMergeA((a) => (a ? a : persist.workspace_dir));
    }
  }, [persist?.workspace_dir]);

  const llmBody = useCallback(() => {
    const settings = getApiSettings(userId);
    const api_url = settings?.apiUrl?.trim() || '';
    const api_key = settings?.apiKey?.trim() || '';
    const model = modelName.trim() || defaultGraphragModel();
    return { api_url, api_key, model };
  }, [userId, modelName]);

  const copyText = async (text: string, okMsg?: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(okMsg || L.copied, 'success');
    } catch {
      showToast(L.copyFailed, 'error');
    }
  };

  const handleIndex = async () => {
    if (!notebookId) {
      showToast(L.noNotebook, 'warning');
      return;
    }
    const { api_url, api_key, model } = llmBody();
    if (!api_url || !api_key) {
      showToast(L.apiWarn, 'warning');
      return;
    }
    setIndexLoading(true);
    try {
      const res = await indexGraphragKb({
        notebook_id: notebookId,
        notebook_title: notebookTitle,
        email: email || '',
        api_url,
        api_key,
        model,
        source_stems: null,
        workspace_dir: persist?.workspace_dir || '',
        force_reindex: forceReindex,
        parse_pdfs: parsePdfs,
        skip_kggen: true,
      });
      const next: GraphragWorkspacePersist = {
        workspace_dir: res.workspace_dir,
        updatedAt: Date.now(),
        num_chunks: res.num_chunks,
      };
      if (storageKey) {
        localStorage.setItem(storageKey, JSON.stringify(next));
      }
      setPersist(next);
      showToast(L.indexOk, 'success');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(msg, 'error');
    } finally {
      setIndexLoading(false);
    }
  };

  const handleQuery = async () => {
    if (!notebookId) {
      showToast(L.noNotebook, 'warning');
      return;
    }
    const ws = persist?.workspace_dir?.trim();
    if (!ws) {
      showToast(locale === 'zh' ? '请先构建索引或确认已持久化 workspace_dir' : 'Build index first or set workspace_dir', 'warning');
      return;
    }
    const q = question.trim();
    if (!q) {
      showToast(locale === 'zh' ? '请输入问题' : 'Enter a question', 'warning');
      return;
    }
    const { api_url, api_key, model } = llmBody();
    if (!api_url || !api_key) {
      showToast(L.apiWarn, 'warning');
      return;
    }
    setQueryLoading(true);
    setQueryResult(null);
    try {
      const res = await queryGraphragKb({
        notebook_id: notebookId,
        notebook_title: notebookTitle,
        email: email || '',
        api_url,
        api_key,
        model,
        question: q,
        search_method: searchMethod,
        workspace_dir: ws,
      });
      setQueryResult(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(msg, 'error');
    } finally {
      setQueryLoading(false);
    }
  };

  const handleMerge = async () => {
    if (!notebookId) {
      showToast(L.noNotebook, 'warning');
      return;
    }
    const a = mergeA.trim();
    const b = mergeB.trim();
    if (!a || !b) {
      showToast(locale === 'zh' ? '请填写两个 workspace 路径' : 'Enter both workspace paths', 'warning');
      return;
    }
    const { api_url, api_key, model } = llmBody();
    if (!api_url || !api_key) {
      showToast(L.apiWarn, 'warning');
      return;
    }
    setMergeLoading(true);
    try {
      const res = await mergeGraphragKb({
        notebook_id: notebookId,
        notebook_title: notebookTitle,
        email: email || '',
        api_url,
        api_key,
        model,
        workspace_dir_a: a,
        workspace_dir_b: b,
        dedupe: mergeDedupe,
      });
      const next: GraphragWorkspacePersist = {
        workspace_dir: res.merged_workspace_dir,
        updatedAt: Date.now(),
        num_chunks: res.num_chunks,
      };
      if (storageKey) localStorage.setItem(storageKey, JSON.stringify(next));
      setPersist(next);
      setMergeA(res.merged_workspace_dir);
      showToast(L.mergeOk, 'success');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(msg, 'error');
    } finally {
      setMergeLoading(false);
    }
  };

  const mermaidCode = useMemo(() => {
    if (!queryResult?.reasoning_subgraph?.length) return null;
    return reasoningSubgraphToMermaid(queryResult.reasoning_subgraph);
  }, [queryResult?.reasoning_subgraph]);

  const contextJson = useMemo(() => {
    if (!queryResult?.context_data) return '';
    try {
      return JSON.stringify(queryResult.context_data, null, 2);
    } catch {
      return '{}';
    }
  }, [queryResult?.context_data]);

  const downloadContext = () => {
    const blob = new Blob([contextJson], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `graphrag_context_${notebookId || 'nb'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const judgePct = queryResult ? Math.round(Math.max(0, Math.min(1, queryResult.judge_score)) * 100) : 0;

  return (
    <main className="flex-1 flex flex-col relative bg-white min-w-[300px] overflow-hidden">
      <div className="flex items-center gap-2 px-6 py-3 border-b border-ios-gray-100 shrink-0">
        <Network className="text-cyan-600" size={20} />
        <div>
          <div className="text-sm font-medium text-ios-gray-900">{L.headerTitle}</div>
          <div className="text-xs text-ios-gray-400">{L.headerSub}</div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-8 max-w-[960px] w-full mx-auto">
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
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              className="w-full max-w-md px-3 py-2 border border-ios-gray-200 rounded-lg text-sm"
              placeholder={defaultGraphragModel()}
            />
          </div>
          <button
            type="button"
            disabled={indexLoading || !notebookId}
            onClick={handleIndex}
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
                <button
                  type="button"
                  onClick={() => copyText(persist.workspace_dir)}
                  className="shrink-0 p-1.5 rounded border border-ios-gray-200 hover:bg-ios-gray-50"
                  title={L.copy}
                >
                  <Copy size={14} />
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-ios-gray-100 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-ios-gray-800">{L.queryBtn}</h3>
          <div>
            <label className="block text-xs font-medium text-ios-gray-500 mb-1">{L.queryQ}</label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
              placeholder={L.queryPlaceholder}
              className="w-full px-3 py-2 border border-ios-gray-200 rounded-lg text-sm"
            />
          </div>
          <div className="flex flex-wrap gap-3 items-center">
            <span className="text-xs text-ios-gray-500">search_method</span>
            <select
              value={searchMethod}
              onChange={(e) => setSearchMethod(e.target.value as 'local' | 'global')}
              className="px-3 py-2 border border-ios-gray-200 rounded-lg text-sm"
            >
              <option value="local">{L.searchLocal}</option>
              <option value="global">{L.searchGlobal}</option>
            </select>
            <button
              type="button"
              disabled={queryLoading}
              onClick={handleQuery}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-ios bg-primary text-white text-sm font-medium disabled:opacity-50"
            >
              {queryLoading ? <Loader2 size={16} className="animate-spin" /> : null}
              {queryLoading ? L.querying : L.queryBtn}
            </button>
          </div>
        </section>

        {queryResult && (
          <>
            <section className="rounded-2xl border border-ios-gray-100 p-4 space-y-2">
              <h3 className="text-sm font-semibold text-ios-gray-800">{L.answer}</h3>
              <div className="prose prose-sm max-w-none text-ios-gray-800">
                <ReactMarkdown>{queryResult.answer || '—'}</ReactMarkdown>
              </div>
              <div className="rounded-xl bg-sky-50 border border-sky-100 px-3 py-2 text-sm">
                <div className="font-medium text-sky-900">{L.judge}: {judgePct}%</div>
                {queryResult.judge_rationale ? (
                  <div className="text-xs text-sky-800 mt-1 opacity-90">{queryResult.judge_rationale}</div>
                ) : null}
              </div>
            </section>

            <section className="rounded-2xl border border-ios-gray-100 p-4 space-y-3">
              <h3 className="text-sm font-semibold text-ios-gray-800">{L.subgraph}</h3>
              <div className="flex gap-2 text-xs">
                {(['table', 'mermaid', 'json'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setSubView(v)}
                    className={`px-3 py-1.5 rounded-lg border ${subView === v ? 'border-primary bg-primary/10' : 'border-ios-gray-200'}`}
                  >
                    {v === 'table' ? L.viewTable : v === 'mermaid' ? L.viewMermaid : L.viewJson}
                  </button>
                ))}
              </div>
              {subView === 'table' && (
                <div className="overflow-x-auto rounded-lg border border-ios-gray-200">
                  {queryResult.reasoning_subgraph?.length ? (
                    <table className="min-w-full text-xs">
                      <thead className="bg-ios-gray-100">
                        <tr>
                          {['source', 'target', 'relation', 'weight'].map((col) => (
                            <th key={col} className="px-2 py-2 text-left font-medium capitalize">{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {queryResult.reasoning_subgraph.map((row, i) => (
                          <tr key={i} className="border-t border-ios-gray-100">
                            <td className="px-2 py-1.5">{String(row.source ?? row.src ?? row.from ?? '')}</td>
                            <td className="px-2 py-1.5">{String(row.target ?? row.tgt ?? row.to ?? '')}</td>
                            <td className="px-2 py-1.5">{String(row.relation ?? row.relationship ?? row.label ?? '')}</td>
                            <td className="px-2 py-1.5">{row.weight != null ? String(row.weight) : ''}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="p-4 text-sm text-ios-gray-500">{L.noSubgraph}</div>
                  )}
                </div>
              )}
              {subView === 'mermaid' && (
                <div className="bg-slate-900 rounded-xl p-2">
                  {mermaidCode ? (
                    <MermaidPreview mermaidCode={mermaidCode} title={L.mermaidTitle} />
                  ) : (
                    <div className="text-sm text-gray-400 p-4">{L.noSubgraph}</div>
                  )}
                </div>
              )}
              {subView === 'json' && (
                <pre className="text-xs bg-ios-gray-50 border border-ios-gray-200 rounded-lg p-3 max-h-80 overflow-auto whitespace-pre-wrap">
                  {JSON.stringify(queryResult.reasoning_subgraph, null, 2)}
                </pre>
              )}
              {queryResult.reasoning_subgraph_cot ? (
                <details className="text-xs rounded-lg border border-ios-gray-100 bg-ios-gray-50/60 p-3 mt-2">
                  <summary className="cursor-pointer font-medium text-ios-gray-700 select-none">
                    {L.subgraphCot}
                  </summary>
                  <div className="mt-2 text-ios-gray-800 whitespace-pre-wrap break-words">
                    <ReactMarkdown>{queryResult.reasoning_subgraph_cot}</ReactMarkdown>
                  </div>
                </details>
              ) : null}
            </section>

            <section className="rounded-2xl border border-ios-gray-100 p-4 space-y-2">
              <h3 className="text-sm font-semibold text-ios-gray-800">{L.hints}</h3>
              <div className="space-y-2">
                {(queryResult.highlight_hints || []).map((hint, i) => {
                  const stem = hint.source_stem != null ? String(hint.source_stem).trim() : '';
                  const pi = _parsePageIndex(hint.page_index);
                  const cid = hint.chunk_id != null ? String(hint.chunk_id) : '';
                  const bbox = hint.bbox;
                  const hasStructured = stem || pi != null || bbox != null;
                  return (
                    <div key={i} className="rounded-lg border border-ios-gray-100 bg-ios-gray-50/80 p-2.5 text-xs space-y-1.5">
                      {hasStructured ? (
                        <>
                          <div className="flex gap-2 flex-wrap">
                            <span className="text-ios-gray-500 shrink-0">{L.hintDoc}</span>
                            <span className="break-all font-medium">{stem || '—'}</span>
                          </div>
                          <div className="flex gap-2">
                            <span className="text-ios-gray-500 shrink-0">{L.hintPage}</span>
                            <span>
                              {pi != null && pi >= 0
                                ? locale === 'zh'
                                  ? `第 ${pi + 1} 页`
                                  : `Page ${pi + 1}`
                                : '—'}
                            </span>
                          </div>
                          {bbox != null && String(bbox) !== '' ? (
                            <div className="flex gap-2 break-all">
                              <span className="text-ios-gray-500 shrink-0">{L.hintBbox}</span>
                              <span className="font-mono text-[11px]">
                                {typeof bbox === 'object' ? JSON.stringify(bbox) : String(bbox)}
                              </span>
                            </div>
                          ) : null}
                          {onOpenGraphragSource && stem ? (
                            <button
                              type="button"
                              onClick={() =>
                                onOpenGraphragSource({
                                  sourceStem: stem,
                                  pageIndex: pi ?? -1,
                                  chunkId: cid || undefined,
                                  workspaceDir: persist?.workspace_dir,
                                })
                              }
                              className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline pt-1"
                            >
                              <ExternalLink size={12} />
                              {L.openInKb}
                            </button>
                          ) : null}
                        </>
                      ) : (
                        <>
                          {KNOWN_HINT_KEYS.filter((k) => hint[k] != null && hint[k] !== '').map((k) => (
                            <div key={k} className="flex gap-2 break-all">
                              <span className="text-ios-gray-500 shrink-0">{k}:</span>
                              <span>{typeof hint[k] === 'object' ? JSON.stringify(hint[k]) : String(hint[k])}</span>
                            </div>
                          ))}
                          {KNOWN_HINT_KEYS.every((k) => hint[k] == null || hint[k] === '') && (
                            <pre className="whitespace-pre-wrap">{JSON.stringify(hint, null, 2)}</pre>
                          )}
                        </>
                      )}
                    </div>
                  );
                })}
                {!(queryResult.highlight_hints || []).length && (
                  <div className="text-xs text-ios-gray-400">—</div>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-ios-gray-100 p-4">
              <button
                type="button"
                onClick={() => setContextOpen(!contextOpen)}
                className="flex items-center gap-2 text-sm font-semibold text-ios-gray-800 w-full text-left"
              >
                {contextOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                {L.context}
              </button>
              {contextOpen && (
                <div className="mt-3 space-y-2">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={downloadContext}
                      className="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg border border-ios-gray-200 hover:bg-ios-gray-50"
                    >
                      <Download size={14} /> {L.downloadJson}
                    </button>
                    <button
                      type="button"
                      onClick={() => copyText(contextJson)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg border border-ios-gray-200 hover:bg-ios-gray-50"
                    >
                      <Copy size={14} /> {L.copyJson}
                    </button>
                  </div>
                  <pre className="text-[11px] bg-ios-gray-50 border border-ios-gray-200 rounded-lg p-3 max-h-64 overflow-auto whitespace-pre-wrap">
                    {contextJson.slice(0, 120_000)}
                    {contextJson.length > 120_000 ? '\n…' : ''}
                  </pre>
                </div>
              )}
            </section>
          </>
        )}

        <section className="rounded-2xl border border-dashed border-ios-gray-200 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-ios-gray-800">{L.mergeTitle}</h3>
          <div>
            <label className="block text-xs text-ios-gray-500 mb-1">{L.mergeA}</label>
            <textarea
              value={mergeA}
              onChange={(e) => setMergeA(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 border border-ios-gray-200 rounded-lg text-xs font-mono"
            />
          </div>
          <div>
            <label className="block text-xs text-ios-gray-500 mb-1">{L.mergeB}</label>
            <textarea
              value={mergeB}
              onChange={(e) => setMergeB(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 border border-ios-gray-200 rounded-lg text-xs font-mono"
            />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={mergeDedupe} onChange={(e) => setMergeDedupe(e.target.checked)} />
            {L.dedupe}
          </label>
          <button
            type="button"
            disabled={mergeLoading}
            onClick={handleMerge}
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
