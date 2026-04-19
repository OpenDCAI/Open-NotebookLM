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
        
        # Directories
        self.processed_dir = self.base_dir / "processed"
        self.vector_store_dir = self.base_dir / "vector_store"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.vector_store_dir.mkdir(parents=True, exist_ok=True)
        
        # Paths
        self.manifest_path = self.base_dir / "knowledge_manifest.json"
        self.faiss_index_path = self.vector_store_dir / f"{project_name}.index"
        self.faiss_meta_path = self.vector_store_dir / f"{project_name}.meta"
        
        # State
        self.manifest = self._load_manifest()
        self.index = None
        self.meta_data = [] # List corresponding to index vectors
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

    def save(self):
        """Save Manifest, Index and Meta data to disk."""
        # Save Manifest
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)
            
        # Save Index & Meta
        if self.index is not None:
            faiss.write_index(self.index, str(self.faiss_index_path))
            with open(self.faiss_meta_path, 'wb') as f:
                pickle.dump(self.meta_data, f)
        
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
        self.save()
        return True

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
            elif ext in ['.png', '.jpg', '.jpeg', '.mp4', '.avi', '.mov']:
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
        else:
            log.warning(f"No valid chunks from text file: {file_path}")
            record["status"] = "skipped"

    async def _process_media(self, file_path: Path, description: Optional[str], record: Dict, file_id: str):
        desc_text = description
        
        # If no description provided, generate one using multimodal API
        if not desc_text:
            log.info(f"No description for {file_path.name}, calling Multimodal API...")
            try:
                ext = file_path.suffix.lower()
                messages = []
                
                # Check file type
                if ext in ['.png', '.jpg', '.jpeg']:
                    # Image Understanding
                    log.info(f"Using image model: {self.image_model}")
                    desc_text = await call_image_understanding_async(
                        model=self.image_model,
                        messages=[{"role": "user", "content": "Please describe this image in detail for knowledge base retrieval."}],
                        api_url=self.multimodal_api_url,
                        api_key=self.api_key,
                        image_path=str(file_path)
                    )
                    log.critical(f'Image Understanding desc_text : {desc_text}')
                elif ext in ['.mp4', '.avi', '.mov']:
                    # Video Understanding
                    log.info(f"Using video model: {self.video_model}")
                    desc_text = await call_video_understanding_async(
                        model=self.video_model,
                        messages=[{"role": "user", "content": "Please analyze this video and provide a detailed description of its content, events, and any text visible, for knowledge base retrieval."}],
                        api_url=self.multimodal_api_url,
                        api_key=self.api_key,
                        video_path=str(file_path)
                    )
                    log.critical(f'Video Understanding desc_text : {desc_text}')
                
                if desc_text:
                    log.info(f"Generated description: {desc_text[:100]}...")
            except Exception as e:
                log.error(f"Failed to generate description: {e}")
                # Fallback or just skip embedding
        
        if desc_text:
            # Save description to file
            desc_path = self.processed_dir / file_id / "description.txt"
            desc_path.parent.mkdir(parents=True, exist_ok=True)
            with open(desc_path, 'w', encoding='utf-8') as f:
                f.write(desc_text)
                
            record["description_text_path"] = str(desc_path)
            
            # Embed description
            vectors = self._call_embedding_api([desc_text])
            meta_list = [{
                "source_file_id": file_id,
                "type": "media_desc",
                "content": desc_text,
                "path": str(file_path)
            }]
            self._add_vectors(vectors, meta_list)
            record["media_desc_count"] = 1
        else:
            log.warning(f"Skipping media {file_path.name} (no description available)")

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
