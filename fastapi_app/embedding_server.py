"""
本地 Embedding 服务：加载 Octen/Octen-Embedding-0.6B，提供 OpenAI 兼容的 POST /v1/embeddings。
可单独启动：uvicorn fastapi_app.embedding_server:app --host 127.0.0.1 --port 17997
或由主后端在 USE_LOCAL_EMBEDDING=1 时自动拉起。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import List, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

EMBEDDING_MODEL_NAME = "Octen-Embedding-0.6B"
HF_MODEL_ID = "Octen/Octen-Embedding-0.6B"


def _get_embedder():
    """懒加载，首次请求时下载并加载模型。"""
    if _get_embedder._model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "请安装 sentence-transformers: pip install sentence-transformers"
            )
        _get_embedder._model = SentenceTransformer(HF_MODEL_ID)
    return _get_embedder._model


_get_embedder._model = None


class EmbeddingRequest(BaseModel):
    model: str = Field(default=EMBEDDING_MODEL_NAME, description="模型名，可忽略")
    input: Union[str, List[str]] = Field(..., description="单条文本或文本列表")


class EmbeddingItem(BaseModel):
    object: str = "embedding"
    embedding: List[float]
    index: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingItem]
    model: str = EMBEDDING_MODEL_NAME
    usage: dict = Field(default_factory=lambda: {"prompt_tokens": 0, "total_tokens": 0})


def _ensure_model_loaded():
    """启动时检查：已缓存则 log 提示，未缓存则下载并加载。"""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=HF_MODEL_ID, local_files_only=True)
        print(f"[embedding_server] 模型已缓存，正在加载 {HF_MODEL_ID} ...")
    except Exception:
        print(f"[embedding_server] 模型未缓存，正在下载并加载 {HF_MODEL_ID}（首次较慢）...")
    _get_embedder()
    print(f"[embedding_server] {EMBEDDING_MODEL_NAME} 已就绪。")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时检查/下载并加载模型，不再依赖远程 embedding
    try:
        _ensure_model_loaded()
    except Exception as e:
        print(f"[embedding_server] 加载失败: {e}")
        raise
    yield
    if _get_embedder._model is not None:
        try:
            del _get_embedder._model
            _get_embedder._model = None
        except Exception:
            pass


app = FastAPI(
    title="Local Embedding (Octen-Embedding-0.6B)",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def embeddings(req: EmbeddingRequest):
    """OpenAI 兼容的 embedding 接口。"""
    if isinstance(req.input, str):
        texts = [req.input]
    else:
        texts = list(req.input)
    if not texts:
        raise HTTPException(status_code=400, detail="input 不能为空")

    # 限制单次 batch 大小，避免 OOM
    max_batch = int(os.getenv("EMBEDDING_MAX_BATCH", "32"))
    if len(texts) > max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多 {max_batch} 条，当前 {len(texts)} 条",
        )

    try:
        model = _get_embedder()
        # 换行可能影响效果，与 VectorStoreManager 行为一致
        texts_clean = [t.replace("\n", " ").strip() or " " for t in texts]
        emb = model.encode(
            texts_clean,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if emb.ndim == 1:
        emb = emb.reshape(1, -1)
    data = [
        EmbeddingItem(embedding=emb[i].tolist(), index=i)
        for i in range(len(texts))
    ]
    return EmbeddingResponse(data=data)


@app.get("/health")
async def health():
    return {"status": "ok", "model": EMBEDDING_MODEL_NAME}
