import os
import json
import pickle
import shutil
import subprocess
import uuid
import numpy as np
import faiss
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

import fitz  # PyMuPDF，MinerU 失败时回退用
from PIL import Image

# Import existing tools
from workflow_engine.toolkits.multimodaltool.mineru_tool import run_mineru_pdf_extract_http
from workflow_engine.toolkits.multimodaltool.req_videos import call_video_understanding_async
from workflow_engine.toolkits.multimodaltool.req_understanding import call_image_understanding_async
import workflow_engine.utils as utils
from workflow_engine.logger import get_logger
from fastapi_app.services.embedding_service import EmbeddingService

log = get_logger(__name__)


def _chunk_text(text: str, chunk_size: int = 1500, chunk_overlap: int = 150) -> List[str]:
    """
    使用 LangChain RecursiveCharacterTextSplitter 分块；未安装时返回空列表，由调用方回退到简单分块。
    """
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        return []
    if not (text or "").strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", "。", "；", " ", ""],
    )
    chunks = splitter.split_text(text.strip())
    return [c.strip() for c in chunks if len(c.strip()) > 10]

def _image_path_to_data_url(img_path: Path) -> str:
    """Read an image file and return a base64 data URL."""
    import base64
    import mimetypes
    mime = mimetypes.guess_type(str(img_path))[0] or "image/jpeg"
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


async def _transcribe_media_audio(
    file_path: Path,
    api_url: str,
    api_key: str,
    model: str,
) -> str:
    """Extract audio (from video via ffmpeg, or use audio directly) and transcribe via LLM input_audio.

    Returns the transcript text, or empty string on failure.
    """
    import base64
    import subprocess
    import tempfile

    ext = file_path.suffix.lower()
    audio_path = file_path

    # For video files, extract audio to a temp MP3 first
    if ext in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
        tmp_mp3 = Path(tempfile.mktemp(suffix=".mp3"))
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(file_path), "-vn", "-acodec", "libmp3lame", "-y", str(tmp_mp3)],
                check=True, capture_output=True,
            )
            audio_path = tmp_mp3
        except Exception as exc:
            log.warning(f"[Transcribe] ffmpeg audio extraction failed: {exc}")
            return ""

    try:
        audio_b64 = base64.b64encode(audio_path.read_bytes()).decode()
        audio_mime = {
            ".mp3": "mp3", ".wav": "wav", ".m4a": "m4a", ".ogg": "ogg",
        }.get(audio_path.suffix.lower(), "mp3")

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "请完整转录这段音频的所有内容，保留原始语言。只输出转录文字，不要加任何解释或标注。"},
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": f"data:audio/{audio_mime};base64,{audio_b64}",
                        "format": audio_mime,
                    },
                },
            ],
        }]

        import httpx
        url = f"{api_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 16384,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            transcript = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
            log.info(f"[Transcribe] Got {len(transcript)} chars from {file_path.name}")
            return transcript
    except Exception as exc:
        log.error(f"[Transcribe] Failed for {file_path.name}: {exc}")
        return ""
    finally:
        if audio_path != file_path and audio_path.exists():
            try:
                audio_path.unlink()
            except Exception:
                pass


def _default_embedding_api_url() -> str:
    return os.getenv("EMBEDDING_API_URL", "http://123.129.219.111:3000/v1/embeddings")


def _default_embedding_model() -> str:
    return os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")


class VectorStoreManager:
    def __init__(
        self,
        base_dir: str,
        project_name: str = "kb_project",
        embedding_api_url: Optional[str] = None,
        embedding_model: Optional[str] = None,
        api_key: Optional[str] = None,
        multimodal_model: str = "gemini-2.5-flash",
        image_model: str = "gemini-2.5-flash",
        video_model: str = "gemini-2.5-flash",
        mineru_output_base: Optional[str] = None,
    ):
        self.base_dir = Path(base_dir)
        self.mineru_output_base = Path(mineru_output_base) if mineru_output_base else None
        self.project_name = project_name
        self.embedding_service = EmbeddingService()
        self.api_key = api_key or os.getenv("DF_API_KEY")
        self.multimodal_model = multimodal_model
        self.image_model = image_model
        self.video_model = video_model
        if self.image_model == "gemini-2.5-flash" and self.multimodal_model != "gemini-2.5-flash":
             self.image_model = self.multimodal_model
        if self.video_model == "gemini-2.5-flash" and self.multimodal_model != "gemini-2.5-flash":
             self.video_model = self.multimodal_model
        self.multimodal_api_url = os.getenv("DEFAULT_LLM_API_URL", "http://123.129.219.111:3000/v1/")

        # Visual embedding service (Qwen3-VL-Embedding or any multimodal embedding API).
        # Only initialised when VISUAL_EMBEDDING_API_URL is explicitly set; otherwise all
        # omni/visual embedding paths are skipped and we fall back to text-only retrieval.
        try:
            from fastapi_app.services.visual_embedding_service import VisualEmbeddingService
            from fastapi_app.config.settings import settings as _svc_settings
            if (_svc_settings.VISUAL_EMBEDDING_API_URL or "").strip():
                self._visual_embed_svc: Optional[Any] = VisualEmbeddingService()
            else:
                self._visual_embed_svc = None
        except Exception:
            self._visual_embed_svc = None
        
        # Directories
        self.processed_dir = self.base_dir / "processed"
        self.vector_store_dir = self.base_dir / "vector_store"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.vector_store_dir.mkdir(parents=True, exist_ok=True)
        
        # Paths
        self.manifest_path = self.base_dir / "knowledge_manifest.json"
        self.faiss_index_path = self.vector_store_dir / f"{project_name}.index"
        self.faiss_meta_path = self.vector_store_dir / f"{project_name}.meta"
        self.visual_faiss_index_path = self.vector_store_dir / f"{project_name}_visual.index"
        self.visual_faiss_meta_path = self.vector_store_dir / f"{project_name}_visual.meta"
        self.omni_faiss_index_path = self.vector_store_dir / f"{project_name}_omni.index"
        self.omni_faiss_meta_path  = self.vector_store_dir / f"{project_name}_omni.meta"

        # State
        self.manifest = self._load_manifest()
        self.index = None
        self.meta_data = [] # List corresponding to index vectors
        self._visual_index = None
        self._visual_meta_data: list = []
        self._omni_index = None
        self._omni_meta_data: list = []
        self._load_index()

    def _load_manifest(self) -> Dict[str, Any]:
        if self.manifest_path.exists():
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "project_name": self.project_name,
            "base_dir": str(self.base_dir),
            "faiss_index_path": str(self.faiss_index_path),
            "faiss_meta_path": str(self.faiss_meta_path),
            "files": []
        }

    def _load_index(self):
        if self.faiss_index_path.exists() and self.faiss_meta_path.exists():
            log.info(f"Loading existing index from {self.faiss_index_path}")
            self.index = faiss.read_index(str(self.faiss_index_path))
            with open(self.faiss_meta_path, 'rb') as f:
                self.meta_data = pickle.load(f)
        else:
            log.info("Initializing new index")
            self.index = None # Will be initialized on first add
            self.meta_data = []

        if self.visual_faiss_index_path.exists() and self.visual_faiss_meta_path.exists():
            log.info(f"Loading existing visual index from {self.visual_faiss_index_path}")
            self._visual_index = faiss.read_index(str(self.visual_faiss_index_path))
            with open(self.visual_faiss_meta_path, 'rb') as f:
                self._visual_meta_data = pickle.load(f)
        else:
            self._visual_index = None
            self._visual_meta_data = []

        if self.omni_faiss_index_path.exists() and self.omni_faiss_meta_path.exists():
            log.info(f"Loading existing omni index from {self.omni_faiss_index_path}")
            self._omni_index = faiss.read_index(str(self.omni_faiss_index_path))
            with open(self.omni_faiss_meta_path, 'rb') as f:
                self._omni_meta_data = pickle.load(f)
        else:
            self._omni_index = None
            self._omni_meta_data = []

    def save(self):
        """Save Manifest, Index and Meta data to disk."""
        # Save Manifest
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)

        # Save text Index & Meta
        if self.index is not None:
            faiss.write_index(self.index, str(self.faiss_index_path))
            with open(self.faiss_meta_path, 'wb') as f:
                pickle.dump(self.meta_data, f)

        # Save visual Index & Meta
        if self._visual_index is not None:
            faiss.write_index(self._visual_index, str(self.visual_faiss_index_path))
            with open(self.visual_faiss_meta_path, 'wb') as f:
                pickle.dump(self._visual_meta_data, f)

        # Save omni Index & Meta
        if self._omni_index is not None:
            faiss.write_index(self._omni_index, str(self.omni_faiss_index_path))
            with open(self.omni_faiss_meta_path, 'wb') as f:
                pickle.dump(self._omni_meta_data, f)

        log.info(f"Saved vector store to {self.vector_store_dir}")

    def remove_file(self, file_id: str) -> bool:
        """
        Remove all vectors and manifest record for the given file_id.
        Rebuilds the FAISS index without the deleted file's vectors.
        Returns True if the file was found and removed.
        """
        if not file_id:
            return False
        # Indices to keep (meta_data[i].source_file_id != file_id)
        keep_indices = [i for i in range(len(self.meta_data)) if self.meta_data[i].get("source_file_id") != file_id]
        if len(keep_indices) == len(self.meta_data):
            # No vector belonged to this file; still remove from manifest if present
            self.manifest["files"] = [f for f in self.manifest.get("files", []) if f.get("id") != file_id]
            self.save()
            return True
        if self.index is None or self.index.ntotal == 0:
            self.manifest["files"] = [f for f in self.manifest.get("files", []) if f.get("id") != file_id]
            self.save()
            return True
        dim = self.index.d
        # Rebuild index: keep only vectors not belonging to file_id
        batch_size = 256
        new_meta = [self.meta_data[i] for i in keep_indices]
        vectors_list = []
        for i in keep_indices:
            vec = self.index.reconstruct(i)
            vectors_list.append(vec)
        if not vectors_list:
            self.index = None
            self.meta_data = []
            if self.faiss_index_path.exists():
                self.faiss_index_path.unlink()
            if self.faiss_meta_path.exists():
                self.faiss_meta_path.unlink()
        else:
            arr = np.asarray(vectors_list, dtype=np.float32)
            self.index = faiss.IndexFlatIP(dim)
            self.index.add(arr)
            self.meta_data = new_meta
        self.manifest["files"] = [f for f in self.manifest.get("files", []) if f.get("id") != file_id]
        self._rebuild_visual_index_without(file_id)
        self._rebuild_omni_index_without(file_id)
        self.save()
        return True

    def _rebuild_visual_index_without(self, file_id: str) -> None:
        """Rebuild visual index excluding all vectors for the given file_id."""
        keep = [i for i in range(len(self._visual_meta_data)) if self._visual_meta_data[i].get("source_file_id") != file_id]
        if len(keep) == len(self._visual_meta_data):
            return
        if not keep:
            self._visual_index = None
            self._visual_meta_data = []
            if self.visual_faiss_index_path.exists():
                self.visual_faiss_index_path.unlink()
            if self.visual_faiss_meta_path.exists():
                self.visual_faiss_meta_path.unlink()
            return
        if self._visual_index is not None:
            dim = self._visual_index.d
            vecs = [self._visual_index.reconstruct(i) for i in keep]
            arr = np.asarray(vecs, dtype=np.float32)
            self._visual_index = faiss.IndexFlatIP(dim)
            self._visual_index.add(arr)
        self._visual_meta_data = [self._visual_meta_data[i] for i in keep]

    def _rebuild_omni_index_without(self, file_id: str) -> None:
        """Rebuild omni index excluding all vectors for the given file_id."""
        if self._omni_index is None:
            return
        keep = [i for i in range(len(self._omni_meta_data)) if self._omni_meta_data[i].get("source_file_id") != file_id]
        if len(keep) == len(self._omni_meta_data):
            return
        if not keep:
            self._omni_index = None
            self._omni_meta_data = []
            if self.omni_faiss_index_path.exists():
                self.omni_faiss_index_path.unlink()
            if self.omni_faiss_meta_path.exists():
                self.omni_faiss_meta_path.unlink()
            return
        dim = self._omni_index.d
        vecs = [self._omni_index.reconstruct(i) for i in keep]
        arr = np.asarray(vecs, dtype=np.float32)
        self._omni_index = faiss.IndexFlatIP(dim)
        self._omni_index.add(arr)
        self._omni_meta_data = [self._omni_meta_data[i] for i in keep]

    def search(self, query: str, top_k: int = 5, file_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        Search knowledge base.
        
        Args:
            query: Query string.
            top_k: Number of results to return.
            file_ids: List of file IDs to filter by. If None, search all files.
                      Uses post-filtering strategy (retrieve more, then filter).
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        # 1. Embed query
        query_vecs = self._call_embedding_api([query])
        if len(query_vecs) == 0:
            return []
            
        # 2. Determine search k (expand if filtering)
        # If filtering by file_ids, we need to retrieve more candidates
        # because many might belong to other files.
        search_k = top_k
        if file_ids:
            # Simple heuristic: fetch more candidates. 
            # In production, might need to be much larger or use iterative search.
            search_k = max(top_k * 20, 100) 
            
        # Cap at total vectors
        search_k = min(search_k, self.index.ntotal)
            
        # 3. Search Faiss
        # D: distances (scores), I: indices
        D, I = self.index.search(query_vecs, search_k)
        
        # 4. Filter and Format Results
        results = []
        target_file_ids = set(file_ids) if file_ids else None
        
        # I[0] contains indices for the first (and only) query
        for rank, idx in enumerate(I[0]):
            if idx < 0 or idx >= len(self.meta_data):
                continue
                
            meta = self.meta_data[idx]
            
            # Post-filtering
            if target_file_ids and meta.get("source_file_id") not in target_file_ids:
                continue
                
            result_item = {
                "score": float(D[0][rank]),
                "content": meta.get("content"),
                "source_file_id": meta.get("source_file_id"),
                "type": meta.get("type"),
                "metadata": meta
            }
            results.append(result_item)
            
            if len(results) >= top_k:
                break
                
        return results

    def _add_visual_vectors(self, vectors: np.ndarray, meta_list: List[Dict]) -> None:
        """Add vectors and meta to the visual-only FAISS index."""
        if len(vectors) == 0:
            return
        if self._visual_index is None:
            self._visual_index = faiss.IndexFlatIP(vectors.shape[1])
        self._visual_index.add(vectors)
        self._visual_meta_data.extend(meta_list)

    def _add_omni_vectors(self, vectors: np.ndarray, meta_list: List[Dict]) -> None:
        """Add vectors and meta to the unified omni FAISS index."""
        if len(vectors) == 0:
            return
        if self._omni_index is None:
            self._omni_index = faiss.IndexFlatIP(vectors.shape[1])
        self._omni_index.add(vectors)
        self._omni_meta_data.extend(meta_list)

    def search_visual(
        self,
        query_desc: str,
        top_k: int = 5,
        file_ids: Optional[List[str]] = None,
        query_image_data_url: Optional[str] = None,
    ) -> List[Dict]:
        """Search the visual-only index.

        If query_image_data_url is provided, embed it with the visual embedding model
        (Qwen3-VL-Embedding) for true image-to-image search.
        Otherwise fall back to text embedding of query_desc.
        """
        if self._visual_index is None or self._visual_index.ntotal == 0:
            return []

        if query_image_data_url and self._visual_embed_svc is not None:
            query_vecs = self._call_visual_embedding_api(query_image_data_url, is_image=True)
        else:
            query_vecs = self._call_visual_embedding_api(query_desc, is_image=False)

        if len(query_vecs) == 0:
            return []
        query_arr = query_vecs if query_vecs.ndim == 2 else query_vecs.reshape(1, -1)
        search_k = max(top_k * 20, 100) if file_ids else top_k
        search_k = min(search_k, self._visual_index.ntotal)
        D, I = self._visual_index.search(query_arr, search_k)
        results = []
        target_file_ids = set(file_ids) if file_ids else None
        for rank, idx in enumerate(I[0]):
            if idx < 0 or idx >= len(self._visual_meta_data):
                continue
            meta = self._visual_meta_data[idx]
            if target_file_ids and meta.get("source_file_id") not in target_file_ids:
                continue
            results.append({
                "score": float(D[0][rank]),
                "content": meta.get("content"),
                "source_file_id": meta.get("source_file_id"),
                "type": "visual",
                "metadata": meta,
            })
            if len(results) >= top_k:
                break
        return results

    def search_omni(
        self,
        query: str,
        top_k: int = 5,
        file_ids: Optional[List[str]] = None,
        query_image_data_url: Optional[str] = None,
    ) -> List[Dict]:
        """Search the unified omni-embedding index.

        All content (text chunks, PDF-extracted images, media files) lives in the
        same Qwen3-VL-Embedding vector space, so text and image queries work uniformly.
        Returns an empty list if the omni index is not available.
        """
        if self._omni_index is None or self._omni_index.ntotal == 0:
            return []

        if query_image_data_url and self._visual_embed_svc is not None:
            query_vecs = self._call_omni_embedding_api(query_image_data_url, is_image=True)
        else:
            query_vecs = self._call_omni_embedding_api(query, is_image=False)

        if len(query_vecs) == 0:
            return []
        query_arr = query_vecs if query_vecs.ndim == 2 else query_vecs.reshape(1, -1)
        search_k = max(top_k * 20, 100) if file_ids else top_k
        search_k = min(search_k, self._omni_index.ntotal)
        D, I = self._omni_index.search(query_arr, search_k)
        results = []
        target_file_ids = set(file_ids) if file_ids else None
        for rank, idx in enumerate(I[0]):
            if idx < 0 or idx >= len(self._omni_meta_data):
                continue
            meta = self._omni_meta_data[idx]
            if target_file_ids and meta.get("source_file_id") not in target_file_ids:
                continue
            results.append({
                "score": float(D[0][rank]),
                "content": meta.get("content"),
                "source_file_id": meta.get("source_file_id"),
                "type": meta.get("type", "omni"),
                "metadata": meta,
            })
            if len(results) >= top_k:
                break
        return results

    def get_pdf_images(
        self,
        file_ids: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Return all pdf_image and pdf_page entries for the given file IDs.

        Used in VLM mode to always surface extracted PDF images alongside text results,
        regardless of whether their descriptions match the query semantically.
        pdf_image entries (extracted figures) take priority; pdf_page entries (full-page
        renders) fill the remainder up to the limit.
        """
        target_file_ids = set(file_ids) if file_ids else None
        figures = []
        pages = []
        for meta in self.meta_data:
            t = meta.get("type", "")
            if t not in ("pdf_image", "pdf_page"):
                continue
            if target_file_ids and meta.get("source_file_id") not in target_file_ids:
                continue
            entry = {
                "score": 0.0,
                "content": meta.get("content", ""),
                "source_file_id": meta.get("source_file_id"),
                "type": t,
                "metadata": meta,
            }
            if t == "pdf_image":
                figures.append(entry)
            else:
                pages.append(entry)

        # Figures first, then pages; honour the limit
        combined = figures[:limit] + pages[: max(0, limit - len(figures))]
        return combined[:limit]

    def _call_omni_embedding_api(self, content: str, is_image: bool = False) -> np.ndarray:
        """Embed content using the unified Qwen3-VL-Embedding model (omni space).

        Delegates to _call_visual_embedding_api which already handles both modalities.
        """
        return self._call_visual_embedding_api(content, is_image=is_image)

    def _call_omni_embedding_api_batch(self, texts: List[str]) -> np.ndarray:
        """Batch embed texts using the unified VLM embedding model.

        Sends all texts in a single API call for efficiency.
        Falls back to the text embedding model if visual service is unavailable.
        """
        if not texts:
            return np.array([])
        if self._visual_embed_svc is not None:
            try:
                vecs = self._visual_embed_svc.embed_texts_batch_sync(texts)
                arr = np.array(vecs, dtype=np.float32)
                faiss.normalize_L2(arr)
                return arr
            except Exception as exc:
                log.warning(f"[Omni] Batch text embed failed, falling back to text model: {exc}")
        return self._call_embedding_api(texts)

    def _call_visual_embedding_api(self, data_url_or_text: str, is_image: bool = False) -> np.ndarray:
        """Call Qwen3-VL-Embedding API for an image or text, return L2-normalised float32 array."""
        if self._visual_embed_svc is not None:
            try:
                if is_image:
                    vec = self._visual_embed_svc.embed_image_sync(data_url_or_text)
                else:
                    vec = self._visual_embed_svc.embed_text_sync(data_url_or_text)
                arr = np.array([vec], dtype=np.float32)
                faiss.normalize_L2(arr)
                return arr
            except Exception as exc:
                log.warning(f"[VisualEmbedding] failed, falling back to text embedding: {exc}")
        # Fallback: use text embedding (for backward-compat when no visual model is configured)
        text = data_url_or_text if not is_image else "(image)"
        return self._call_embedding_api([text])

    def _call_embedding_api(self, texts: List[str]) -> np.ndarray:
        """调用 Embedding API"""
        if not texts:
            return np.array([])
        texts = [t.replace("\n", " ") for t in texts]
        try:
            embeddings = self.embedding_service.embed_sync(texts)
            return np.array(embeddings, dtype=np.float32)
        except Exception as e:
            log.error(f"Embedding error: {e}")
            raise RuntimeError(f"Failed to embed: {e}")

        arr = np.asarray(vecs, dtype=np.float32)
        if arr.ndim != 2:
            raise RuntimeError(f"Embedding array has invalid shape: {arr.shape}")
        if not np.isfinite(arr).all():
            bad = np.size(arr) - np.isfinite(arr).sum()
            raise RuntimeError(f"Embedding contains non-finite values: {bad} elements")
        if len(arr) > 0:
            try:
                faiss.normalize_L2(arr)
            except Exception as e:
                log.exception(
                    "Faiss normalize_L2 failed: shape=%s dtype=%s min=%s max=%s",
                    getattr(arr, "shape", None),
                    getattr(arr, "dtype", None),
                    float(np.min(arr)) if arr.size else None,
                    float(np.max(arr)) if arr.size else None,
                )
                raise
        return arr

    def _add_vectors(self, vectors: np.ndarray, meta_list: List[Dict]):
        """Add vectors and meta data to index."""
        if len(vectors) == 0:
            return
        if len(meta_list) != vectors.shape[0]:
            raise RuntimeError(
                f"Meta count mismatch: {len(meta_list)} metas vs {vectors.shape[0]} vectors"
            )
            
        if self.index is None:
            dim = vectors.shape[1]
            self.index = faiss.IndexFlatIP(dim)
        else:
            if self.index.d != vectors.shape[1]:
                raise RuntimeError(
                    f"Embedding dim mismatch: index dim {self.index.d} vs vectors dim {vectors.shape[1]}"
                )
            
        try:
            self.index.add(vectors)
        except Exception as e:
            log.exception(
                "Faiss add failed: index dim=%s, vectors shape=%s, dtype=%s",
                getattr(self.index, "d", None),
                getattr(vectors, "shape", None),
                getattr(vectors, "dtype", None),
            )
            raise
        self.meta_data.extend(meta_list)

    async def process_file(self, file_path: str, description: Optional[str] = None) -> str:
        """
        Main entry point to process a file.
        Returns the file ID in the manifest.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_id = str(uuid.uuid4())
        ext = file_path.suffix.lower()
        
        file_record = {
            "id": file_id,
            "original_path": str(file_path),
            "file_type": ext.lstrip('.'),
            "status": "processing",
            "chunks_count": 0,
            "media_desc_count": 0
        }
        
        log.info(f"Processing file: {file_path} (ID: {file_id})")

        try:
            if ext == '.pdf':
                await self._process_pdf(file_path, file_record, file_id)
            elif ext in ['.docx', '.doc']:
                await self._process_word(file_path, file_record, file_id)
            elif ext in ['.pptx', '.ppt']:
                await self._process_ppt(file_path, file_record, file_id)
            elif ext in ['.md', '.markdown', '.txt']:
                await self._process_text(file_path, file_record, file_id)
            elif ext in ['.png', '.jpg', '.jpeg', '.mp4', '.avi', '.mov',
                         '.mp3', '.wav', '.m4a', '.ogg']:
                await self._process_media(file_path, description, file_record, file_id)
            else:
                log.warning(f"Unsupported file type: {ext}")
                file_record["status"] = "skipped"

            if file_record["status"] == "processing":
                 file_record["status"] = "embedded"

        except Exception as e:
            log.exception("Error processing %s", file_path)
            file_record["status"] = "failed"
            err_text = (str(e) or "").strip()
            if not err_text:
                err_text = f"{type(e).__name__}: {repr(e)}"
            file_record["error"] = err_text
            
        # 清理同一路径的旧记录，避免历史 failed 记录干扰本次结果
        self.manifest["files"] = [
            f for f in self.manifest.get("files", [])
            if (f.get("original_path") or "") != str(file_path)
        ]
        self.manifest["files"].append(file_record)
        self.save()
        return file_id

    def _convert_to_pdf(self, input_path: Path, output_dir: Path) -> Path:
        """Convert office document to PDF using LibreOffice."""
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "libreoffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(input_path)
        ]
        
        log.info(f"Converting {input_path} to PDF...")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        pdf_name = input_path.with_suffix('.pdf').name
        pdf_path = output_dir / pdf_name
        if not pdf_path.exists():
            raise RuntimeError(f"PDF conversion failed, expected output: {pdf_path}")
            
        return pdf_path

    def _pdf_to_markdown_fallback(self, file_path: Path, output_subdir: Path) -> Path:
        """MinerU 不可用时的回退：用 PyMuPDF 抽正文并写入单个 .md，返回 md 路径。"""
        stem = file_path.stem
        out_dir = output_subdir / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{stem}.md"
        try:
            doc = fitz.open(file_path)
            parts = []
            for page in doc:
                parts.append(page.get_text())
            doc.close()
            text = "\n\n".join(parts).strip()
            if not text:
                text = "[No text extracted]"
            md_path.write_text(text, encoding="utf-8")
            log.info(f"[MinerU fallback] Wrote PyMuPDF text to {md_path}")
            return md_path
        except Exception as e:
            log.warning(f"[MinerU fallback] PyMuPDF extract failed: {e}")
            md_path.write_text("[PDF extract failed]", encoding="utf-8")
            return md_path

    async def _process_pdf(self, file_path: Path, record: Dict, file_id: str):
        # 1. MinerU Extract：以 pdf_stem 为子目录名，便于跨流程复用缓存
        #    使用 pipeline 后端避免 vLLM 与 MinerU 的版本冲突（ParallelConfig.world_size 等）
        #    目录结构: {mineru_output_base}/{pdf_stem}/auto/*.md
        if self.mineru_output_base:
            output_subdir = self.mineru_output_base
        else:
            output_subdir = self.processed_dir / file_id
        output_subdir.mkdir(parents=True, exist_ok=True)
        record["mineru_output_path"] = str(output_subdir)

        pdf_stem = file_path.stem
        mineru_output_folder = output_subdir / pdf_stem

        # 检测已有 MinerU 缓存：如果 {output_subdir}/{pdf_stem}/auto/*.md 已存在则跳过
        md_file = None
        cached = False
        if mineru_output_folder.exists():
            for sub in ("auto", "hybrid_auto"):
                candidate = mineru_output_folder / sub
                if candidate.is_dir():
                    existing_md = next(candidate.glob("*.md"), None)
                    if existing_md:
                        md_file = existing_md
                        cached = True
                        log.info("[MinerU] 复用已有缓存: %s", md_file)
                        break

        if not cached:
            try:
                await run_mineru_pdf_extract_http(
                    str(file_path),
                    str(output_subdir),
                )
                log.info("[MinerU] 解析完成，输出根目录: %s", output_subdir)
                md_file = next(mineru_output_folder.rglob("*.md"), None)
            except Exception as e:
                log.warning(f"MinerU failed ({file_path.name}), using PyMuPDF fallback: {e}")

        # Initialize parsers dict
        if "parsers" not in record:
            record["parsers"] = {}

        if md_file:
            content_list_file = next(mineru_output_folder.rglob("*_content_list.json"), None)
            record["parsers"]["mineru"] = {
                "md_path": str(md_file),
                "images_dir": str(md_file.parent / "images"),
                "content_list_path": str(content_list_file) if content_list_file else None,
                "output_dir": str(output_subdir),
                "cached": cached
            }
            # Keep legacy fields for backward compatibility
            record["processed_md_path"] = str(md_file)
            record["images_dir"] = str(md_file.parent / "images")

        if not md_file:
            md_file = await asyncio.to_thread(
                self._pdf_to_markdown_fallback,
                file_path,
                output_subdir,
            )
            record["parsers"]["mineru"] = {
                "md_path": str(md_file),
                "images_dir": str(md_file.parent / "images"),
                "output_dir": str(output_subdir),
                "fallback": True
            }
            # Keep legacy fields for backward compatibility
            record["processed_md_path"] = str(md_file)
            record["images_dir"] = str(md_file.parent / "images")

        # 2. Chunking & Embedding (LangChain RecursiveCharacterTextSplitter when available)
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        chunks = _chunk_text(content)
        if not chunks:
            # Fallback: simple paragraph split
            chunks = [c.strip() for c in content.split('\n\n') if c.strip()]
            chunks = [c for c in chunks if len(c) > 10]
        
        if chunks:
            vectors = self._call_embedding_api(chunks)
            meta_list = [
                {
                    "source_file_id": file_id,
                    "type": "text_chunk",
                    "content": chunk,
                    "chunk_index": i
                }
                for i, chunk in enumerate(chunks)
            ]
            self._add_vectors(vectors, meta_list)
            record["chunks_count"] = len(chunks)

            # Also embed text chunks into omni index (unified VLM vector space)
            if self._visual_embed_svc is not None:
                try:
                    omni_vecs = self._call_omni_embedding_api_batch(chunks)
                    self._add_omni_vectors(omni_vecs, meta_list)
                    log.info(f"[Omni] Added {len(chunks)} text chunks to omni index")
                except Exception as exc:
                    log.warning(f"[Omni] Text chunk embed failed, omni index skipped: {exc}")

            # 在 MinerU 输出目录写入 chunks_info.json，便于确认是否做了分块及每块预览
            chunks_info_path = output_subdir / "chunks_info.json"
            try:
                chunks_info = {
                    "chunks_count": len(chunks),
                    "source_file_id": file_id,
                    "chunks": [
                        {"chunk_index": i, "length": len(c), "preview": (c[:300] + "..." if len(c) > 300 else c)}
                        for i, c in enumerate(chunks)
                    ],
                }
                chunks_info_path.write_text(json.dumps(chunks_info, ensure_ascii=False, indent=2), encoding="utf-8")
                record["chunks_info_path"] = str(chunks_info_path)
            except Exception as e:
                log.warning(f"Could not write chunks_info.json: {e}")

        # Phase 1: embed PDF-extracted images into text/visual/omni indices
        images_dir = Path(record.get("images_dir", ""))
        if images_dir.exists():
            image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
            pdf_images = sorted([p for p in images_dir.iterdir() if p.suffix.lower() in image_exts])
            pdf_image_count = 0
            for img_path in pdf_images:
                try:
                    # Generate a semantic description so text search can find this image
                    img_desc = None
                    try:
                        img_desc = await call_image_understanding_async(
                            model=self.image_model,
                            messages=[{"role": "user", "content": "请详细描述这张图片的内容，包括图表类型、主要信息、数据趋势等，用于知识库检索。"}],
                            api_url=self.multimodal_api_url,
                            api_key=self.api_key,
                            image_path=str(img_path),
                        )
                        log.info(f"[PDFImage] Generated description for {img_path.name}: {(img_desc or '')[:80]}")
                    except Exception as exc:
                        log.warning(f"[PDFImage] Description generation failed for {img_path.name}: {exc}")

                    content = img_desc or f"[PDF图片] {img_path.name}"
                    img_meta = {
                        "source_file_id": file_id,
                        "type": "pdf_image",
                        "content": content,
                        "img_path": str(img_path),
                    }

                    # Text index: embed description for semantic text retrieval
                    text_vecs = self._call_embedding_api([content])
                    self._add_vectors(text_vecs, [img_meta])

                    # Visual/omni indices: embed actual image pixels (only when VLM configured)
                    if self._visual_embed_svc is not None:
                        data_url = _image_path_to_data_url(img_path)
                        visual_vecs = self._call_visual_embedding_api(data_url, is_image=True)
                        self._add_visual_vectors(visual_vecs, [img_meta])
                        omni_vecs = self._call_omni_embedding_api(data_url, is_image=True)
                        self._add_omni_vectors(omni_vecs, [img_meta])

                    pdf_image_count += 1
                except Exception as exc:
                    log.warning(f"[PDFImage] Failed to process {img_path.name}: {exc}")
            if pdf_image_count:
                log.info(f"[PDFImage] Processed {pdf_image_count} PDF images")
                record["pdf_image_count"] = pdf_image_count

        # Phase 1b: index _pages/ full-page renders (MinerU always produces these)
        # These are the primary visual source for VLM mode when figures aren't extracted.
        if images_dir.exists():
            pages_dir = images_dir.parent.parent / "_pages"
        else:
            mineru_auto = Path(record.get("processed_md_path", "")).parent
            pages_dir = mineru_auto / "_pages"
        if pages_dir.exists():
            page_imgs = sorted([p for p in pages_dir.iterdir() if p.suffix.lower() == ".png"])
            pdf_page_count = 0
            for img_path in page_imgs:
                # Parse page number from filename (page_0001.png → 1)
                try:
                    page_num = int(img_path.stem.split("_")[-1])
                except ValueError:
                    page_num = 0
                content = f"[PDF第{page_num}页]"
                page_meta = {
                    "source_file_id": file_id,
                    "type": "pdf_page",
                    "content": content,
                    "img_path": str(img_path),
                    "page_num": page_num,
                }
                try:
                    text_vecs = self._call_embedding_api([content])
                    self._add_vectors(text_vecs, [page_meta])
                    pdf_page_count += 1
                except Exception as exc:
                    log.warning(f"[PDFPage] Failed to index {img_path.name}: {exc}")
            if pdf_page_count:
                log.info(f"[PDFPage] Indexed {pdf_page_count} full-page renders")
                record["pdf_page_count"] = pdf_page_count

    async def _process_word(self, file_path: Path, record: Dict, file_id: str):
        # Convert to PDF first
        temp_dir = self.processed_dir / "temp" / file_id
        pdf_path = self._convert_to_pdf(file_path, temp_dir)
        
        # Reuse PDF processing
        await self._process_pdf(pdf_path, record, file_id)
        
        # Cleanup temp PDF
        # shutil.rmtree(temp_dir, ignore_errors=True)

    async def _process_ppt(self, file_path: Path, record: Dict, file_id: str):
        # Same as Word, convert to PDF first
        temp_dir = self.processed_dir / "temp" / file_id
        pdf_path = self._convert_to_pdf(file_path, temp_dir)
        await self._process_pdf(pdf_path, record, file_id)

    async def _process_text(self, file_path: Path, record: Dict, file_id: str):
        """Process plain text / markdown files: read → chunk → embed."""
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            log.warning(f"Empty text file: {file_path}")
            record["status"] = "skipped"
            return

        chunks = _chunk_text(content)
        if not chunks:
            chunks = [c.strip() for c in content.split('\n\n') if c.strip()]
            chunks = [c for c in chunks if len(c) > 10]

        if chunks:
            vectors = self._call_embedding_api(chunks)
            meta_list = [
                {
                    "source_file_id": file_id,
                    "type": "text_chunk",
                    "content": chunk,
                    "chunk_index": i,
                }
                for i, chunk in enumerate(chunks)
            ]
            self._add_vectors(vectors, meta_list)
            record["chunks_count"] = len(chunks)
            # Also embed into omni index (unified VLM vector space)
            if self._visual_embed_svc is not None:
                try:
                    omni_vecs = self._call_omni_embedding_api_batch(chunks)
                    self._add_omni_vectors(omni_vecs, meta_list)
                except Exception as exc:
                    log.warning(f"[Omni] Text chunk omni embed failed: {exc}")
        else:
            log.warning(f"No valid chunks from text file: {file_path}")
            record["status"] = "skipped"

    async def _process_media(self, file_path: Path, description: Optional[str], record: Dict, file_id: str):
        ext = file_path.suffix.lower()
        is_image = ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
        is_video = ext in {'.mp4', '.avi', '.mov'}
        is_audio = ext in {'.mp3', '.wav', '.m4a', '.ogg'}

        desc_text = description
        ocr_text = None
        transcript_text = None

        out_dir = self.processed_dir / file_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Image: generate description + OCR ──
        if is_image:
            if not desc_text:
                try:
                    desc_text = await call_image_understanding_async(
                        model=self.image_model,
                        messages=[{"role": "user", "content": "Please describe this image in detail for knowledge base retrieval."}],
                        api_url=self.multimodal_api_url,
                        api_key=self.api_key,
                        image_path=str(file_path),
                    )
                    log.info(f"[Image] description: {(desc_text or '')[:80]}")
                except Exception as e:
                    log.error(f"[Image] description failed: {e}")

            try:
                ocr_text = await call_image_understanding_async(
                    model=self.image_model,
                    messages=[{"role": "user", "content": (
                        "请识别并完整输出这张图片中的所有文字内容。保留原始格式（包括换行、缩进、表格结构）。"
                        "如果图片中没有文字，返回空字符串。只输出提取的文字，不要加任何解释。"
                    )}],
                    api_url=self.multimodal_api_url,
                    api_key=self.api_key,
                    image_path=str(file_path),
                )
                log.info(f"[OCR] got {len(ocr_text or '')} chars from {file_path.name}")
            except Exception as e:
                log.warning(f"[OCR] failed for {file_path.name}: {e}")

        # ── Video: generate visual description + transcribe audio ──
        elif is_video:
            if not desc_text:
                try:
                    desc_text = await call_video_understanding_async(
                        model=self.video_model,
                        messages=[{"role": "user", "content": "Please analyze this video and provide a detailed description of its content, events, and any text visible, for knowledge base retrieval."}],
                        api_url=self.multimodal_api_url,
                        api_key=self.api_key,
                        video_path=str(file_path),
                    )
                    log.info(f"[Video] description: {(desc_text or '')[:80]}")
                except Exception as e:
                    log.error(f"[Video] description failed: {e}")

            try:
                from fastapi_app.config.settings import settings as _ts
                transcript_text = await _transcribe_media_audio(
                    file_path,
                    api_url=(_ts.LLM_API_URL or "").strip() or self.multimodal_api_url,
                    api_key=(_ts.LLM_API_KEY or "").strip() or self.api_key,
                    model=(_ts.LLM_MODEL or "").strip() or self.video_model,
                )
            except Exception as e:
                log.warning(f"[Transcribe] video audio failed: {e}")

        # ── Audio: transcribe directly ──
        elif is_audio:
            try:
                from fastapi_app.config.settings import settings as _ts
                transcript_text = await _transcribe_media_audio(
                    file_path,
                    api_url=(_ts.LLM_API_URL or "").strip() or self.multimodal_api_url,
                    api_key=(_ts.LLM_API_KEY or "").strip() or self.api_key,
                    model=(_ts.LLM_MODEL or "").strip() or self.image_model,
                )
            except Exception as e:
                log.error(f"[Transcribe] audio failed: {e}")
            if transcript_text:
                desc_text = transcript_text[:500]

        # ── Store description (existing logic, preserved) ──
        if desc_text:
            desc_path = out_dir / "description.txt"
            desc_path.write_text(desc_text, encoding="utf-8")
            record["description_text_path"] = str(desc_path)

            vectors = self._call_embedding_api([desc_text])
            meta_list = [{
                "source_file_id": file_id,
                "type": "media_desc",
                "content": desc_text,
                "path": str(file_path),
            }]
            self._add_vectors(vectors, meta_list)

            if is_image or is_video:
                import base64 as _b64
                import mimetypes as _mt
                try:
                    mime = _mt.guess_type(str(file_path))[0] or "image/jpeg"
                    b64 = _b64.b64encode(file_path.read_bytes()).decode()
                    img_data_url = f"data:{mime};base64,{b64}"
                    visual_vecs = self._call_visual_embedding_api(img_data_url, is_image=True)
                except Exception as exc:
                    log.warning(f"[VisualEmbed] falling back to text-desc embedding for {file_path.name}: {exc}")
                    visual_vecs = vectors
                    img_data_url = None

                self._add_visual_vectors(visual_vecs, [{
                    "source_file_id": file_id,
                    "type": "visual",
                    "content": desc_text,
                    "path": str(file_path),
                }])

                if img_data_url:
                    try:
                        omni_vecs = self._call_omni_embedding_api(img_data_url, is_image=True)
                        self._add_omni_vectors(omni_vecs, [{
                            "source_file_id": file_id,
                            "type": "visual",
                            "content": desc_text,
                            "path": str(file_path),
                        }])
                    except Exception as exc:
                        log.warning(f"[Omni] Media omni embed failed: {exc}")

            record["media_desc_count"] = 1
        else:
            log.warning(f"Skipping media description for {file_path.name} (no description available)")

        # ── OCR text → chunk & embed ──
        if ocr_text and ocr_text.strip():
            ocr_path = out_dir / "ocr_text.txt"
            ocr_path.write_text(ocr_text, encoding="utf-8")
            record["ocr_text_path"] = str(ocr_path)

            chunks = _chunk_text(ocr_text)
            if not chunks:
                chunks = [c.strip() for c in ocr_text.split('\n\n') if c.strip() and len(c.strip()) > 10]
            if chunks:
                vecs = self._call_embedding_api(chunks)
                meta = [
                    {"source_file_id": file_id, "type": "ocr_chunk", "content": c, "chunk_index": i}
                    for i, c in enumerate(chunks)
                ]
                self._add_vectors(vecs, meta)
                if self._visual_embed_svc is not None:
                    try:
                        omni_vecs = self._call_omni_embedding_api_batch(chunks)
                        self._add_omni_vectors(omni_vecs, meta)
                    except Exception as exc:
                        log.warning(f"[Omni] OCR chunk omni embed failed: {exc}")
                record["ocr_chunks_count"] = len(chunks)
                log.info(f"[OCR] embedded {len(chunks)} chunks from {file_path.name}")

        # ── Transcript text → chunk & embed ──
        if transcript_text and transcript_text.strip():
            tx_path = out_dir / "transcript.txt"
            tx_path.write_text(transcript_text, encoding="utf-8")
            record["transcript_path"] = str(tx_path)

            chunks = _chunk_text(transcript_text)
            if not chunks:
                chunks = [c.strip() for c in transcript_text.split('\n\n') if c.strip() and len(c.strip()) > 10]
            if chunks:
                vecs = self._call_embedding_api(chunks)
                meta = [
                    {"source_file_id": file_id, "type": "transcript_chunk", "content": c, "chunk_index": i}
                    for i, c in enumerate(chunks)
                ]
                self._add_vectors(vecs, meta)
                if self._visual_embed_svc is not None:
                    try:
                        omni_vecs = self._call_omni_embedding_api_batch(chunks)
                        self._add_omni_vectors(omni_vecs, meta)
                    except Exception as exc:
                        log.warning(f"[Omni] transcript chunk omni embed failed: {exc}")
                record["transcript_chunks_count"] = len(chunks)
                log.info(f"[Transcribe] embedded {len(chunks)} chunks from {file_path.name}")

async def process_knowledge_base_files(
    file_list: List[Dict[str, str]],
    base_dir: str = "outputs/kb_data/vector_store_project",
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    multimodal_model: Optional[str] = None,
    image_model: Optional[str] = None,
    video_model: Optional[str] = None,
    mineru_output_base: Optional[str] = None,
):
    """
    Helper function to process a list of files.

    Args:
        file_list: List of dicts, each containing 'path' and optional 'description'.
        base_dir: Directory to store the vector store.
        api_url: Custom Embedding API URL.
        api_key: Custom API Key.
        model_name: Custom Model Name.
        multimodal_model: Custom Multimodal Model Name.
        image_model: Custom Image Model Name.
        video_model: Custom Video Model Name.
        mineru_output_base: If set, each PDF/Word/PPT source's MinerU full output is written to
            {mineru_output_base}/{file_id}/ (e.g. outputs/kb_mineru/{email}/{notebook_id}/).
    """
    kwargs = {"base_dir": base_dir}
    if api_url:
        kwargs["embedding_api_url"] = api_url
    if api_key:
        kwargs["api_key"] = api_key
    if model_name:
        kwargs["embedding_model"] = model_name
    if multimodal_model:
        kwargs["multimodal_model"] = multimodal_model
    if image_model:
        kwargs["image_model"] = image_model
    if video_model:
        kwargs["video_model"] = video_model
    if mineru_output_base:
        kwargs["mineru_output_base"] = mineru_output_base

    manager = VectorStoreManager(**kwargs)
    
    for item in file_list:
        path = item.get("path")
        desc = item.get("description")
        if path:
            try:
                await manager.process_file(path, desc)
            except Exception as e:
                log.error(f"Failed to process {path}: {e}")
                
    manager.save()
    return manager.manifest

if __name__ == "__main__":
    # Test
    # Assuming valid API key is set in env DF_API_KEY
    test_files = [
        {"path": "tests/test.pdf"},
        {"path": "tests/cat_icon.png"} # No description test
    ]
    # process_knowledge_base_files(test_files)
