from fastapi import APIRouter, HTTPException, Body
from typing import List, Dict, Optional, Any
from pathlib import Path
from workflow_engine.toolkits.ragtool.vector_store_tool import process_knowledge_base_files, VectorStoreManager
from workflow_engine.utils import get_project_root
from fastapi_app.utils import _to_outputs_url
from fastapi_app.dependencies.auth import get_supabase_client
from fastapi_app.notebook_paths import get_notebook_paths, _sanitize_user_id
from workflow_engine.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/kb", tags=["Knowledge Base Embedding"])


def _infer_mineru_output_base(local_path: Path) -> Optional[str]:
    """
    Reuse notebook source-tree MinerU cache when the file lives under:
    outputs/{user}/{notebook}/sources/{stem}/original/{file}
    """
    try:
        resolved = local_path.resolve()
        parts = resolved.parts
        if "sources" not in parts or "original" not in parts:
            return None
        original_idx = parts.index("original")
        source_root = Path(*parts[:original_idx])
        mineru_dir = source_root / "mineru"
        return str(mineru_dir)
    except Exception:
        return None


def _vector_store_dir(email: Optional[str], notebook_id: Optional[str]):
    """Per-notebook vector store: outputs/kb_data/{email}/{notebook_id}/vector_store"""
    project_root = get_project_root()
    if not email:
        return project_root / "outputs" / "kb_data" / "vector_store_main"
    safe_email = _sanitize_user_id(email)
    base = project_root / "outputs" / "kb_data" / safe_email
    if notebook_id:
        safe_nb = notebook_id.replace("/", "_").replace("\\", "_")[:128]
        return base / safe_nb / "vector_store"
    return base / "_shared" / "vector_store"


def _extract_email_from_path(path_str: str) -> Optional[str]:
    try:
        parts = Path(path_str).parts
        if "kb_data" in parts:
            idx = parts.index("kb_data")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    except Exception:
        return None
    return None


def _write_manifest_ids_to_supabase(manifest: Dict[str, Any]) -> None:
    supabase = get_supabase_client()
    if not supabase:
        return

    files = manifest.get("files", []) if isinstance(manifest, dict) else []
    for f in files:
        file_id = f.get("id")
        original_path = f.get("original_path", "")
        if not file_id or not original_path:
            continue

        outputs_url = _to_outputs_url(original_path)
        try:
            resp = supabase.table("knowledge_base_files").update(
                {"kb_file_id": file_id}
            ).eq("storage_path", outputs_url).execute()
            updated = bool(getattr(resp, "data", None))

            if not updated:
                email = _extract_email_from_path(original_path)
                filename = Path(original_path).name
                if email and filename:
                    supabase.table("knowledge_base_files").update(
                        {"kb_file_id": file_id}
                    ).eq("user_email", email).eq("file_name", filename).execute()
        except Exception as e:
            # 表无 kb_file_id 列等 schema 问题时静默跳过，不误导为“入库失败”或 API Key 错误
            err_msg = (getattr(e, "message", None) or getattr(e, "msg", None) or str(e) or "")
            if isinstance(err_msg, dict):
                err_msg = str(err_msg)
            err_msg = err_msg.lower()
            if any(x in err_msg for x in ("kb_file_id", "pgrst204", "schema", "column", "could not find")):
                pass
            else:
                log.warning(f"Supabase writeback failed: {e}")

@router.post("/embedding")
async def create_embedding(
    files: List[Dict[str, Optional[str]]] = Body(..., embed=True),
    email: Optional[str] = Body(None, embed=True),
    notebook_id: Optional[str] = Body(None, embed=True),
    notebook_title: Optional[str] = Body(None, embed=True),
    api_url: Optional[str] = Body(None, embed=True),
    api_key: Optional[str] = Body(None, embed=True),
    model_name: Optional[str] = Body(None, embed=True),
    multimodal_model: Optional[str] = Body(None, embed=True),
    image_model: Optional[str] = Body(None, embed=True),
    video_model: Optional[str] = Body(None, embed=True),
):
    """
    Generate embeddings for knowledge base files.
    Uses per-notebook vector store under the new notebook-centric layout when possible,
    falling back to legacy kb_data/{email}/{notebook_id}/vector_store.
    """
    try:
        project_root = get_project_root()
        process_list = []
        user_email = email

        for f in files:
            web_path = f.get("path")
            desc = f.get("description")
            if not web_path:
                continue
            clean_path = web_path.lstrip('/')
            local_path = project_root / clean_path
            if local_path.exists():
                process_list.append({"path": str(local_path), "description": desc})
                if not user_email:
                    try:
                        parts = local_path.parts
                        if "kb_data" in parts:
                            idx = parts.index("kb_data")
                            if idx + 1 < len(parts):
                                candidate = parts[idx + 1]
                                if "@" in candidate or len(candidate) > 0:
                                    user_email = candidate
                    except Exception:
                        pass
            else:
                log.warning(f"File not found locally: {local_path}")

        if not process_list:
            return {"success": False, "message": "No valid files found to process."}

        # New layout: use NotebookPaths for vector store path
        if notebook_id:
            nb_paths = get_notebook_paths(notebook_id, notebook_title or "", user_email)
            vector_store_dir = nb_paths.vector_store_dir
        else:
            vector_store_dir = _vector_store_dir(user_email, notebook_id)

        vector_store_dir.mkdir(parents=True, exist_ok=True)
        manifest: Dict[str, Any] = {"files": []}

        # Process files one by one so each PDF can reuse its own sources/{stem}/mineru cache.
        for item in process_list:
            item_path = Path(str(item["path"])).resolve()
            kwargs: Dict[str, Any] = {
                "file_list": [item],
                "base_dir": str(vector_store_dir),
                "api_url": None,
                "api_key": api_key,
                "model_name": model_name,
                "multimodal_model": multimodal_model,
                "image_model": image_model,
                "video_model": video_model,
            }

            inferred_mineru = _infer_mineru_output_base(item_path)
            if inferred_mineru:
                kwargs["mineru_output_base"] = inferred_mineru

            manifest = await process_knowledge_base_files(**kwargs)

        current_paths = {str(Path(p.get("path", "")).resolve()) for p in process_list if p.get("path")}
        failed = [
            f for f in (manifest.get("files") or [])
            if f.get("status") == "failed"
            and str(Path(f.get("original_path", "")).resolve()) in current_paths
        ]
        if failed:
            first_err = (failed[0].get("error") or "").strip()
            if not first_err:
                failed_names = [Path(f.get("original_path", "")).name for f in failed]
                first_err = f"未知错误（失败文件: {', '.join([n for n in failed_names if n])}）"
            try:
                _write_manifest_ids_to_supabase(manifest)
            except Exception as e:
                log.warning(f"Supabase writeback error: {e}")
            raise HTTPException(
                status_code=422,
                detail=f"向量入库失败: {first_err}"
            )

        try:
            _write_manifest_ids_to_supabase(manifest)
        except Exception as e:
            log.warning(f"Supabase writeback error: {e}")

        return {
            "success": True,
            "message": f"Successfully processed {len(process_list)} files",
            "manifest": manifest
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"向量入库失败: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="向量入库失败，请检查文件格式或联系管理员")

@router.get("/list")
async def list_kb_files(
    email: Optional[str] = None,
    notebook_id: Optional[str] = None,
    notebook_title: Optional[str] = None,
):
    """
    List processed files in the knowledge base (per-notebook vector store).
    """
    try:
        if notebook_id:
            nb_paths = get_notebook_paths(notebook_id, notebook_title or "", email)
            vector_store_dir = nb_paths.vector_store_dir
        else:
            vector_store_dir = _vector_store_dir(email, notebook_id)

        manifest_path = vector_store_dir / "knowledge_manifest.json"
        if manifest_path.exists():
            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)

        # Fallback: try legacy path if new layout has no manifest
        if notebook_id:
            legacy_dir = _vector_store_dir(email, notebook_id)
            legacy_manifest = legacy_dir / "knowledge_manifest.json"
            if legacy_manifest.exists():
                import json
                with open(legacy_manifest, "r", encoding="utf-8") as f:
                    return json.load(f)

        return {"project_name": "kb_project", "files": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete-vector")
async def delete_vector(
    file_id: Optional[str] = Body(None, embed=True),
    email: Optional[str] = Body(None, embed=True),
    notebook_id: Optional[str] = Body(None, embed=True),
    notebook_title: Optional[str] = Body(None, embed=True),
):
    """
    Remove one file's vectors from the knowledge base (per-notebook vector store).
    """
    if not file_id:
        raise HTTPException(status_code=400, detail="file_id is required")
    try:
        if notebook_id:
            nb_paths = get_notebook_paths(notebook_id, notebook_title or "", email)
            vector_store_dir = nb_paths.vector_store_dir
        else:
            vector_store_dir = _vector_store_dir(email, notebook_id)
        kwargs = {"base_dir": str(vector_store_dir)}
        manager = VectorStoreManager(**kwargs)
        manager.remove_file(file_id)
        return {"success": True, "message": "向量已删除"}
    except Exception as e:
        log.error(f"删除向量失败: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除向量失败")


@router.post("/search")
async def search_kb(
    query: str = Body(..., embed=True),
    top_k: int = Body(5, embed=True),
    email: Optional[str] = Body(None, embed=True),
    notebook_id: Optional[str] = Body(None, embed=True),
    notebook_title: Optional[str] = Body(None, embed=True),
    api_url: Optional[str] = Body(None, embed=True),
    api_key: Optional[str] = Body(None, embed=True),
    model_name: Optional[str] = Body(None, embed=True),
    file_ids: Optional[List[str]] = Body(None, embed=True),
):
    """
    Vector search in knowledge base (per-notebook).
    """
    try:
        if notebook_id:
            nb_paths = get_notebook_paths(notebook_id, notebook_title or "", email)
            base_dir = nb_paths.vector_store_dir
        else:
            base_dir = _vector_store_dir(email, notebook_id)

        # Fallback: if new layout has no manifest, try legacy path
        if notebook_id and not (base_dir / "knowledge_manifest.json").exists():
            legacy = _vector_store_dir(email, notebook_id)
            if (legacy / "knowledge_manifest.json").exists():
                base_dir = legacy

        kwargs = {"base_dir": str(base_dir)}
        if api_url:
            if "/embeddings" not in api_url:
                api_url = api_url.rstrip("/") + "/embeddings"
            kwargs["embedding_api_url"] = api_url
        if api_key:
            kwargs["api_key"] = api_key
        if model_name:
            kwargs["embedding_model"] = model_name

        manager = VectorStoreManager(**kwargs)
        results = manager.search(query=query, top_k=top_k, file_ids=file_ids)

        # Build lookup for source file metadata
        manifest = manager.manifest or {"files": []}
        files_by_id = {f.get("id"): f for f in manifest.get("files", []) if f.get("id")}

        formatted = []
        for item in results:
            meta = item.get("metadata", {})
            source_id = item.get("source_file_id")
            src = files_by_id.get(source_id, {})
            src_path = src.get("original_path", "")
            src_url = _to_outputs_url(src_path) if src_path else ""

            media_path = meta.get("path") or ""
            media_url = _to_outputs_url(media_path) if media_path else ""

            formatted.append({
                "score": item.get("score"),
                "content": item.get("content"),
                "type": item.get("type"),
                "source_file": {
                    "id": source_id,
                    "file_type": src.get("file_type"),
                    "original_path": src_path,
                    "url": src_url
                },
                "media": {
                    "path": media_path,
                    "url": media_url
                } if media_path else None,
                "metadata": meta
            })

        return {
            "success": True,
            "query": query,
            "top_k": top_k,
            "results": formatted
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
