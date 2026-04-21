/**
 * GraphRAG 知识库前端 API 封装。
 *
 * 数据流：调用 ``/api/v1/graphrag-kb/*`` → FastAPI ``graphrag_kb`` 路由 → ``wa_graphrag_kb`` → ``wf_graphrag_kb``。
 * ``refineGraphragContextRefine`` 用于侧栏「上下文参考」：首条 unit + 子图 → 清洗正文与支撑句高亮。
 * ``fetchGraphragChunkSnippet`` 仍供阅读器等按 chunk_id 拉取 ``input/*.txt`` 段正文。
 */
import { apiFetch, GRAPHRAG_KB_BASE } from '../config/api';
import type {
  IndexRequest,
  IndexResponse,
  QueryRequest,
  QueryResponse,
  MergeRequest,
  MergeResponse,
  ChatRequest,
  ChatResponse,
  ChatPostprocessRequest,
  ChatPostprocessResponse,
  ContextRefineResponse,
} from '../types/graphragKb';

const DEFAULT_LLM_MODEL = 'deepseek-v3.2';

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const d = body?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((x: { msg?: string }) => x?.msg || String(x)).join('; ');
    return body?.message || `HTTP ${res.status}`;
  } catch {
    const t = await res.text();
    return t || `HTTP ${res.status}`;
  }
}

export function defaultGraphragModel(): string {
  return DEFAULT_LLM_MODEL;
}

export async function indexGraphragKb(body: IndexRequest): Promise<IndexResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<IndexResponse>;
}

export async function queryGraphragKb(body: QueryRequest): Promise<QueryResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<QueryResponse>;
}

export async function mergeGraphragKb(body: MergeRequest): Promise<MergeResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<MergeResponse>;
}

export async function chatGraphragKb(body: ChatRequest): Promise<ChatResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<ChatResponse>;
}

export async function chatGraphragKbPostprocess(
  body: ChatPostprocessRequest,
): Promise<ChatPostprocessResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/chat-postprocess`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<ChatPostprocessResponse>;
}

export interface ChunkSnippetResponse {
  text: string;
  source_stem: string;
  found: boolean;
  /** Verbatim sentence/phrase extracted by LLM that best matches the reasoning triples. */
  highlighted_sentence?: string;
}

/** 从 GraphRAG workspace ``input/*.txt`` 中解析 ``[chunk:id]`` 对应正文（用于阅读器高亮，非整篇 MinerU MD）。
 *  可选传入 triples（reasoning_subgraph）让后端调 LLM 精确定位最相关的原句；
 *  apiKey / apiUrl 需与查询时使用的凭证一致，否则 LLM 调用会返回 401。
 */
export async function fetchGraphragChunkSnippet(
  workspaceDir: string,
  chunkId: string,
  triples?: Array<Record<string, unknown>>,
  apiKey?: string,
  apiUrl?: string,
  /** Same text as the context-reference box (stripped); LLM uses this instead of raw input block. */
  passageForLlm?: string,
): Promise<ChunkSnippetResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/chunk-snippet`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace_dir: workspaceDir,
      chunk_id: chunkId,
      api_key: apiKey || '',
      api_url: apiUrl || '',
      ...(triples && triples.length > 0 ? { triples } : {}),
      ...(passageForLlm != null && passageForLlm.trim() !== ''
        ? { passage_for_llm: passageForLlm }
        : {}),
    }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<ChunkSnippetResponse>;
}

/** 首条检索 unit 原文 + reasoning_subgraph → 清洗正文 + 支撑句（侧栏上下文参考高亮） */
export async function refineGraphragContextRefine(
  unitText: string,
  subgraph: Array<Record<string, unknown>>,
  apiKey: string,
  apiUrl: string,
  model?: string,
): Promise<ContextRefineResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/context-refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      unit_text: unitText,
      subgraph,
      api_key: apiKey || '',
      api_url: apiUrl || '',
      model: (model || '').trim() || DEFAULT_LLM_MODEL,
    }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<ContextRefineResponse>;
}
