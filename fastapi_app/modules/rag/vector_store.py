import logging
import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import requests
try:
    from langchain_chroma import Chroma
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    Chroma = None
# from langchain_openai import OpenAIEmbeddings # Deprecated for this env
try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    HuggingFaceEmbeddings = None
from fastapi_app.core.config import settings
from .storage import rag_dir

logger = logging.getLogger(__name__)


@dataclass
class OpenAICompatibleEmbeddings:
    api_url: str
    model_name: str
    api_key: str = ""
    timeout: float = 30.0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _resolve_model_name(self, force: bool = False) -> str:
        candidate = (self.model_name or "").strip()
        if candidate and not force:
            return candidate

        models_url = self.api_url.rsplit("/embeddings", 1)[0] + "/models"
        session = requests.Session()
        session.trust_env = False
        response = session.get(models_url, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = response.json().get("data") or []
        if not data:
            raise ValueError("No embedding models available from service")
        first_model = str(data[0].get("id") or "").strip()
        if not first_model:
            raise ValueError("Embedding service returned empty model id")
        self.model_name = first_model
        return first_model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        model_name = self._resolve_model_name()
        payload = {
            "model": model_name,
            "input": texts,
        }

        session = requests.Session()
        session.trust_env = False
        response = session.post(
            self.api_url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code == 404:
            refreshed_model_name = self._resolve_model_name(force=True)
            if refreshed_model_name != model_name:
                payload["model"] = refreshed_model_name
                response = session.post(
                    self.api_url,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
        response.raise_for_status()
        data = response.json()
        items = data.get("data") or []
        if not isinstance(items, list) or len(items) != len(texts):
            raise ValueError("Embedding response size mismatch")
        return [item.get("embedding") or [] for item in items]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        result = self._embed([text])
        return result[0] if result else []

class VectorStoreManager:
    _instance = None
    _embeddings = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VectorStoreManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        try:
            embedded_minimal = os.getenv("SQLBOT_EMBEDDED_MINIMAL", "").strip().lower() in {"1", "true", "yes", "on"}

            embedding_api_url = (os.getenv("EMBEDDING_API_URL") or "").strip()
            if not embedding_api_url:
                embedding_port = (os.getenv("LOCAL_EMBEDDING_PORT") or "26210").strip()
                embedding_api_url = f"http://127.0.0.1:{embedding_port}/v1/embeddings"
            if embedding_api_url and "/embeddings" not in embedding_api_url:
                embedding_api_url = embedding_api_url.rstrip("/") + "/embeddings"
            embedding_model = (
                (os.getenv("EMBEDDING_MODEL") or "").strip()
                or (os.getenv("LOCAL_EMBEDDING_MODEL") or "").strip()
                or "Octen/Octen-Embedding-0.6B"
            )
            embedding_api_key = (os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()

            if embedding_api_url:
                try:
                    logger.info(f"Trying OpenAI-compatible embedding service: {embedding_api_url}")
                    embeddings = OpenAICompatibleEmbeddings(
                        api_url=embedding_api_url,
                        model_name=embedding_model,
                        api_key=embedding_api_key,
                    )
                    test_result = embeddings.embed_query("测试")
                    if len(test_result) > 0:
                        self._embeddings = embeddings
                        self.persist_directory = str(rag_dir("chroma_db").absolute())
                        self.model_name = embedding_model
                        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
                        logger.info("✓ Reusing local embedding service for SQLBot vector store")
                        logger.info(f"  - API: {embedding_api_url}")
                        logger.info(f"  - Model: {embedding_model}")
                        return
                except Exception as e:
                    logger.warning(f"✗ Failed to use embedding service {embedding_api_url}: {e}")

            if embedded_minimal:
                logger.info("VectorStoreManager disabled in SQLBOT_EMBEDDED_MINIMAL mode because no reusable embedding service is available")
                self._embeddings = None
                self.persist_directory = None
                self.model_name = None
                return

            if HuggingFaceEmbeddings is None:
                logger.warning("HuggingFaceEmbeddings unavailable - vector store will be disabled")
                self._embeddings = None
                self.persist_directory = None
                self.model_name = None
                return

            # P2优化: 使用中文优化的向量模型
            # 优先级: 中文专用模型 > 多语言模型 > 英文模型(备选)

            model_candidates = [
                # 最佳: 中文专用模型 (推荐)
                {
                    "name": "shibing624/text2vec-base-chinese",
                    "description": "中文专用模型, 768维, 适合中文语义检索"
                },
                # 备选1: 多语言模型
                {
                    "name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                    "description": "多语言模型, 384维, 支持50+语言"
                },
                # 备选2: 原始英文模型
                {
                    "name": "sentence-transformers/all-MiniLM-L6-v2",
                    "description": "英文模型, 384维, 轻量级"
                }
            ]

            model_name = None
            for candidate in model_candidates:
                try:
                    logger.info(f"Trying model: {candidate['name']} - {candidate['description']}")

                    model_kwargs = {'device': 'cpu'}
                    encode_kwargs = {'normalize_embeddings': False}

                    # 尝试初始化模型
                    embeddings = HuggingFaceEmbeddings(
                        model_name=candidate['name'],
                        model_kwargs=model_kwargs,
                        encode_kwargs=encode_kwargs
                    )

                    # 测试模型是否可用
                    test_result = embeddings.embed_query("测试")
                    if len(test_result) > 0:
                        self._embeddings = embeddings
                        model_name = candidate['name']
                        logger.info(f"✓ Successfully loaded model: {model_name}")
                        break

                except Exception as e:
                    logger.warning(f"✗ Failed to load {candidate['name']}: {e}")
                    continue

            if not model_name:
                logger.warning("All embedding models failed to load - vector store will be unavailable")
                self._embeddings = None
                self.persist_directory = None
                self.model_name = None
                return  # Allow initialization to complete without error

            # 持久化目录(avoid CWD ambiguity)
            persist_path = rag_dir("chroma_db")
            try:
                persist_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            persist_directory = str(persist_path.absolute())
            self.persist_directory = persist_directory
            self.model_name = model_name

            logger.info(f"Initialized VectorStoreManager with:")
            logger.info(f"  - Model: {model_name}")
            logger.info(f"  - Persist directory: {persist_directory}")

        except Exception as e:
            logger.error(f"Failed to initialize VectorStoreManager: {e}")
            raise

    def get_vector_store(self, collection_name: str) -> Optional[Chroma]:
        """
        Return a Chroma vector store, or None when embeddings are unavailable.

        NOTE: Constructing Chroma with embedding_function=None will later crash with
        'You must provide an embedding function to compute embeddings'.
        """
        if Chroma is None:
            logger.warning(
                f"Vector store unavailable (collection={collection_name}): langchain_chroma is not installed"
            )
            return None

        if not self._embeddings or not getattr(self, "persist_directory", None):
            logger.warning(
                f"Vector store unavailable (collection={collection_name}): embeddings not initialized"
            )
            return None

        return Chroma(
            collection_name=collection_name,
            embedding_function=self._embeddings,
            persist_directory=self.persist_directory,
        )

# 全局实例
vector_store_manager = VectorStoreManager()
