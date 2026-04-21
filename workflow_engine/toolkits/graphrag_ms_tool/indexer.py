"""GraphRAG 工作区构建与索引入口（Step 3）。

【职责】
    将 Step1 产出的「带元数据的文本块」写成微软 GraphRAG 2.7.x 所需目录结构，
    并子进程执行 ``graphrag index``，生成 ``output/`` 下的实体、关系、社区等制品。

【数据流】
    输入 ``chunks``：每项含 ``chunk_id``、``text``、``page_index``、``order``、
    ``bbox``、``source_stem``（通常来自 ``SourceManager.get_chunks_with_meta``）。
    → 按 ``source_stem`` 分组写入 ``input/{stem}.txt``，每段前加 ``[chunk:<id>]`` 标记。
    → 并行写入 ``chunk_meta.json``：``chunk_id → {page_index, order, bbox, source_stem}``，
      供查询阶段 ``querier`` 将证据中的 chunk 映射回页码/bbox。
    → 修补 ``settings.yaml``（LLM/Embedding/chunk 参数）后调用 CLI 建索引。

【目录结构】（GraphRAG **2.7.x**）::

    {workspace_dir}/
    ├── prompts/             ← ``graphrag init`` 生成（2.7 必需）
    ├── input/               ← GraphRAG 摄取的纯文本（内嵌 [chunk:…]）
    ├── chunk_meta.json      ← 本项目扩展：chunk 与页码/来源的映射
    ├── settings.yaml        ← 模型、输出、local_search 等
    ├── .env                 ← 可选 GRAPHRAG_API_KEY
    └── output/              ← ``graphrag index`` 产物

依赖：**graphrag==2.7.x**，子进程调用；Python 版本需与该包要求一致。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from workflow_engine.logger import get_logger

log = get_logger(__name__)


def _settings_is_graphrag_v27(settings_path: Path) -> bool:
    """判断 ``settings.yaml`` 是否为 GraphRAG ≥2.5 风格（顶层含 ``models`` 块）。"""
    if not settings_path.is_file():
        return False
    try:
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        return isinstance(data, dict) and "models" in data
    except Exception:
        return False


def _ensure_graphrag_v27_project(root: Path, *, force_init: bool) -> None:
    """在 *root* 下调用官方 ``initialize_project_at``，生成 prompts 与默认 ``settings.yaml``。"""
    settings_path = root / "settings.yaml"
    if not force_init and _settings_is_graphrag_v27(settings_path):
        return
    try:
        from graphrag.cli.initialize import initialize_project_at
    except ImportError as exc:
        raise RuntimeError(
            "graphrag package is required. Install with: pip install graphrag==2.7.2"
        ) from exc
    log.info("[GraphRAGIndexer] Initializing GraphRAG 2.7 project layout at %s", root)
    initialize_project_at(path=root, force=True)


_EMBEDDING_VECTOR_SIZES: Dict[str, int] = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
    "octen/octen-embedding-0.6b": 768,
    "octen-embedding-0.6b": 768,
}
_DEFAULT_VECTOR_SIZE = 1536


def _embedding_vector_size(model: str) -> int:
    """Return the output dimension for a known embedding model; default 1536."""
    return _EMBEDDING_VECTOR_SIZES.get(model.lower().strip(), _DEFAULT_VECTOR_SIZE)


def resolve_graphrag_embedding_for_patch(cfg: Any, embedding_model: str) -> Tuple[str, Optional[str]]:
    """GraphRAG ``default_embedding_model`` 的模型名与可选独立 ``api_base``（本地 vLLM）。"""
    if bool(getattr(cfg, "GRAPHRAG_USE_LOCAL_EMBEDDING_RUNTIME", False)) and int(
        getattr(cfg, "USE_LOCAL_EMBEDDING", 0) or 0
    ) == 1:
        port = int(getattr(cfg, "LOCAL_EMBEDDING_PORT", 26210))
        return (
            str(getattr(cfg, "LOCAL_EMBEDDING_MODEL", "Octen/Octen-Embedding-0.6B")).strip(),
            f"http://127.0.0.1:{port}/v1",
        )
    return (str(embedding_model).strip(), None)


def _patch_settings_yaml(
    settings_path: Path,
    *,
    api_key: str,
    api_base: str,
    llm_model: str,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
    local_search_context_max_tokens: int = 12000,
    embedding_api_base: Optional[str] = None,
) -> None:
    """Inject runtime LLM / embedding / chunk params into settings.yaml and write .env.

    Modifies models.default_chat_model, models.default_embedding_model, chunks.size/overlap,
    and vector_store.default_vector_store.vector_size to match the embedding model dimension.
    Each user must have an independent workspace_dir to avoid concurrent overwrites.
    """
    text = settings_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    # graphrag 2.7 的 settings.yaml 必须有顶层 "models" 块，否则说明版本不对
    if not isinstance(data, dict) or "models" not in data:
        raise RuntimeError("Invalid GraphRAG settings.yaml — expected 'models' block (graphrag 2.7 layout).")

    models = data["models"]
    emb_base = (embedding_api_base or api_base).strip() if (embedding_api_base or api_base) else ""
    for model_id, model_name, entry_base in (
        ("default_chat_model", llm_model, api_base),
        ("default_embedding_model", embedding_model, emb_base),
    ):
        if model_id not in models:
            log.warning("[GraphRAGIndexer] settings missing model id %r; skipping patch for it", model_id)
            continue
        entry = models[model_id]
        if isinstance(entry, dict):
            entry["api_key"] = api_key
            entry["model"] = model_name
            if entry_base:
                entry["api_base"] = entry_base.strip().rstrip("/")

    if "chunks" not in data:
        data["chunks"] = {}
    if isinstance(data["chunks"], dict):
        data["chunks"]["size"] = int(chunk_size)
        data["chunks"]["overlap"] = int(chunk_overlap)

    # Ensure vector_store.vector_size matches the actual embedding dimension so that
    # GraphRAG can open the LanceDB collection during queries (default 3072 causes
    # 'NoneType has no attribute search' when the stored vectors are 1536-dim).
    vec_size = _embedding_vector_size(embedding_model)
    vs = data.setdefault("vector_store", {})
    if isinstance(vs, dict):
        store = vs.setdefault("default_vector_store", {})
        if isinstance(store, dict):
            store["vector_size"] = vec_size

    # 较低值可加快 local_search 上下文组装与生成；过低可能丢证据，可按需调大。
    ls = data.setdefault("local_search", {})
    if isinstance(ls, dict):
        ls["context_window_max_tokens"] = max(2048, int(local_search_context_max_tokens))

    settings_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")

    dotenv = settings_path.parent / ".env"
    dotenv.write_text(f"GRAPHRAG_API_KEY={api_key}\n", encoding="utf-8")


@dataclass
class GraphRAGWorkspace:
    """已就绪的 GraphRAG 工作区根目录句柄。

    属性：
        ``input_dir`` / ``output_dir`` / ``settings_path``：标准子路径；
        ``load_chunk_meta()``：读取索引阶段写入的 ``chunk_meta.json``，供查询侧解析页码与来源。
    """

    root: Path
    chunk_meta_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.chunk_meta_path = self.root / "chunk_meta.json"

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.yaml"

    def load_chunk_meta(self) -> Dict[str, Any]:
        """从磁盘读取 ``chunk_id → 元数据`` 映射；文件不存在则返回空 dict。"""
        if not self.chunk_meta_path.exists():
            return {}
        return json.loads(self.chunk_meta_path.read_text(encoding="utf-8"))


def build_index(
    chunks: List[Dict[str, Any]],
    workspace_dir: str,
    *,
    llm_model: Optional[str] = None,
    embedding_model: Optional[str] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    graphrag_cmd: Optional[str] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    force_reindex: bool = False,
) -> GraphRAGWorkspace:
    """Prepare workspace from chunks and run ``graphrag index`` to build the knowledge graph.

    Writes input/{stem}.txt with embedded [chunk:ID] markers, chunk_meta.json for page/bbox
    lookup, patches settings.yaml, then invokes the CLI. Skips indexing if output already
    exists and force_reindex is False.
    """
    from fastapi_app.config.settings import settings as cfg

    llm_model = llm_model or cfg.GRAPHRAG_LLM_MODEL
    embedding_model = embedding_model or cfg.GRAPHRAG_EMBEDDING_MODEL
    emb_for_yaml, emb_api = resolve_graphrag_embedding_for_patch(cfg, embedding_model)
    api_base = api_base or cfg.DEFAULT_LLM_API_URL.rstrip("/")
    api_key = api_key or os.getenv("DF_API_KEY", "")
    chunk_size = chunk_size or cfg.GRAPHRAG_CHUNK_SIZE
    chunk_overlap = chunk_overlap or cfg.GRAPHRAG_CHUNK_OVERLAP
    graphrag_cmd = (
        graphrag_cmd
        or cfg.GRAPHRAG_CMD.strip()
        or shutil.which("graphrag")
    )
    if not graphrag_cmd:
        raise RuntimeError(
            "graphrag CLI not found. Install with `pip install graphrag==2.7.2` or "
            "set GRAPHRAG_CMD in .env to the executable path."
        )

    ws = GraphRAGWorkspace(root=Path(workspace_dir).resolve())
    ws.root.mkdir(parents=True, exist_ok=True)
    ws.input_dir.mkdir(parents=True, exist_ok=True)

    # ── Step A：确保 GraphRAG 2.7 工程骨架存在（prompts/ + settings.yaml）───
    # graphrag init 会生成 prompts 模板和默认 settings.yaml
    # 已有合法的 2.7 格式 settings.yaml 且不强制重建时跳过，避免覆盖用户自定义配置
    need_init = force_reindex or not _settings_is_graphrag_v27(ws.settings_path)
    _ensure_graphrag_v27_project(ws.root, force_init=need_init)

    # Step B: write input/*.txt with [chunk:ID] markers and chunk_meta.json
    # [chunk:ID] tags are carried through text_units so querier can map them back to page/bbox
    stem_to_chunks: Dict[str, List[Dict[str, Any]]] = {}
    meta: Dict[str, Any] = {}
    for chunk in chunks:
        cid = chunk.get("chunk_id", "")
        stem = chunk.get("source_stem", "unknown")
        text = (chunk.get("text") or "").strip()
        if not text or not cid:
            continue
        stem_to_chunks.setdefault(stem, []).append(chunk)
        meta[cid] = {
            "page_index": chunk.get("page_index", -1),
            "order": chunk.get("order", -1),
            "bbox": chunk.get("bbox"),
            "source_stem": stem,
        }

    # 按来源分文件写入，同一来源的 chunk 按 order 排序保证顺序一致
    for stem, cks in stem_to_chunks.items():
        txt_path = ws.input_dir / f"{stem}.txt"
        lines = []
        for ck in sorted(cks, key=lambda c: c.get("order", 0)):
            # ⚠️ 格式约定：[chunk:十六进制ID]\n文本内容
            lines.append(f"[chunk:{ck['chunk_id']}]\n{ck['text']}")
        txt_path.write_text("\n\n".join(lines), encoding="utf-8")

    ws.chunk_meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Step C: inject API key / model params into settings.yaml
    _patch_settings_yaml(
        ws.settings_path,
        api_key=api_key,
        api_base=api_base,
        llm_model=llm_model,
        embedding_model=emb_for_yaml,
        chunk_size=int(chunk_size),
        chunk_overlap=int(chunk_overlap),
        local_search_context_max_tokens=int(cfg.GRAPHRAG_LOCAL_SEARCH_CONTEXT_MAX_TOKENS),
        embedding_api_base=emb_api,
    )

    # Step D: run graphrag index
    output_dir = ws.output_dir
    if force_reindex and output_dir.exists():
        shutil.rmtree(str(output_dir))

    already_indexed = (output_dir / "entities.parquet").exists()
    if already_indexed and not force_reindex:
        log.info("[GraphRAGIndexer] Skipping indexing — output already exists at %s", output_dir)
        return ws

    log.info("[GraphRAGIndexer] Running graphrag index at %s …", ws.root)
    subprocess.run(
        [graphrag_cmd, "index", "--root", str(ws.root)],
        check=True,
        text=True,
    )
    log.info("[GraphRAGIndexer] Indexing complete.")
    return ws
