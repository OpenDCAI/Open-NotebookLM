/**
 * GraphRAG 知识库前端 API 封装。
 *
 * 数据流：调用 ``/api/v1/graphrag-kb/*`` → FastAPI ``graphrag_kb`` 路由 → ``wa_graphrag_kb`` → ``wf_graphrag_kb``。
 * ``fetchGraphragChunkSnippet`` 用于侧栏打开来源时，按 chunk_id 拉取 ``input/*.txt`` 内嵌段正文，供 NotebookView 在 Markdown 中高亮。
 */
import { apiFetch, GRAPHRAG_KB_BASE } from '../config/api';
import type {
  IndexRequest,
  IndexResponse,
  QueryRequest,
  QueryResponse,
  MergeRequest,
  MergeResponse,
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

export interface ChunkSnippetResponse {
  text: string;
  source_stem: string;
  found: boolean;
}

/** 从 GraphRAG workspace ``input/*.txt`` 中解析 ``[chunk:id]`` 对应正文（用于阅读器高亮，非整篇 MinerU MD） */
export async function fetchGraphragChunkSnippet(
  workspaceDir: string,
  chunkId: string
): Promise<ChunkSnippetResponse> {
  const res = await apiFetch(`${GRAPHRAG_KB_BASE}/chunk-snippet`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_dir: workspaceDir, chunk_id: chunkId }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json() as Promise<ChunkSnippetResponse>;
}
