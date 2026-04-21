/**
 * GraphRAG KB 前后端 JSON 契约（与 ``fastapi_app/routers/graphrag_kb.py`` 一致，字段 snake_case）。
 *
 * - Index*：建索引请求/响应（workspace_dir、分块数、可选 KGGen 统计）。
 * - Query*：查询响应含 answer、context_data、推理子图、source_chunks、highlight_hints、Judge、子图 CoT。
 * - Merge*：两工作区合并后的路径与 chunk 数。
 * - GraphragWorkspacePersist：前端 localStorage 持久化的上次索引摘要。
 */

export interface IndexRequest {
  notebook_id: string;
  notebook_title?: string;
  email?: string;
  api_url: string;
  api_key: string;
  model: string;
  source_stems?: string[] | null;
  workspace_dir?: string;
  force_reindex?: boolean;
  parse_pdfs?: boolean;
  /** Default true: server skips KGGen; set false only for internal experiments. */
  skip_kggen?: boolean;
}

export interface IndexResponse {
  workspace_dir: string;
  num_chunks: number;
  kg_entities: number;
  kg_relations: number;
}

export interface QueryRequest {
  notebook_id: string;
  notebook_title?: string;
  email?: string;
  api_url: string;
  api_key: string;
  model: string;
  question: string;
  search_method: 'local' | 'global';
  workspace_dir: string;
  wikidata_enrich?: boolean | null;
}

export interface QueryResponse {
  answer: string;
  context_data: Record<string, unknown>;
  reasoning_subgraph: Array<Record<string, unknown>>;
  source_chunks: string[];
  highlight_hints: Array<Record<string, unknown>>;
  judge_score: number;
  judge_rationale: string;
  /** LLM chain-of-thought for minimal subgraph selection (hop analysis) */
  reasoning_subgraph_cot?: string;
}

export interface MergeRequest {
  notebook_id?: string;
  notebook_title?: string;
  email?: string;
  api_url: string;
  api_key: string;
  model: string;
  workspace_dir_a: string;
  workspace_dir_b: string;
  dedupe?: boolean;
}

export interface MergeResponse {
  merged_workspace_dir: string;
  num_chunks: number;
}

export interface GraphragWorkspacePersist {
  workspace_dir: string;
  updatedAt: number;
  num_chunks?: number;
}

// ── Chat types ───────────────────────────────────────────────────────────────

export interface ChatRequest {
  notebook_id: string;
  notebook_title?: string;
  email?: string;
  query: string;
  history: Array<{ role: 'user' | 'assistant'; content: string; meta?: Record<string, unknown> }>;
  search_method?: 'auto' | 'local' | 'global';
  workspace_dir?: string;
  api_url?: string;
  api_key?: string;
  model?: string;
  /** false = do not append Wikidata tail; omitted = follow server default */
  wikidata_enrich?: boolean | null;
  /** true = return main answer first and postprocess later */
  defer_postprocess?: boolean;
}

export interface ChatResponse {
  answer: string;
  intent: { use_graphrag?: boolean; reason?: string };
  rewritten_query: string;
  context_data: Record<string, unknown>;
  reasoning_subgraph: Array<Record<string, unknown>>;
  reasoning_subgraph_cot: string;
  source_chunks: string[];
  highlight_hints: Array<Record<string, unknown>>;
  judge_score: number;
  judge_rationale: string;
  postprocess_pending?: boolean;
  graphrag_raw_answer?: string;
}

export interface ChatPostprocessRequest {
  query: string;
  answer: string;
  reasoning_subgraph: Array<Record<string, unknown>>;
  api_url?: string;
  api_key?: string;
  model?: string;
  wikidata_enrich?: boolean | null;
  mode?: 'all' | 'subgraph' | 'wikidata';
}

export interface ChatPostprocessResponse {
  reasoning_subgraph: Array<Record<string, unknown>>;
  reasoning_subgraph_cot: string;
  judge_score: number;
  judge_rationale: string;
  wikidata_appendix: string;
  subgraph_done: boolean;
  wikidata_done: boolean;
  done: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  meta?: Pick<
    ChatResponse,
    'intent' | 'rewritten_query' | 'context_data' | 'reasoning_subgraph' |
    'reasoning_subgraph_cot' | 'judge_score' | 'judge_rationale' |
    'graphrag_raw_answer' |
    'source_chunks' | 'highlight_hints'
  >;
  postprocessPending?: boolean;
  postprocessSubgraphPending?: boolean;
  postprocessWikidataPending?: boolean;
}

export interface ContextRefineResponse {
  cleaned_text: string;
  supporting_snippets: string[];
}
