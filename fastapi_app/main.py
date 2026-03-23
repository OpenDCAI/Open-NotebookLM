from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# 加载 .env，使 SUPABASE_* 等环境变量在 os.getenv 中可用
try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent.parent
    load_dotenv(_root / "fastapi_app" / ".env")
except ImportError:
    pass

from workflow_engine.logger import get_logger

log = get_logger(__name__)

# 启动时检查 Supabase 配置
_supabase_url = os.getenv("SUPABASE_URL")
_supabase_anon = os.getenv("SUPABASE_ANON_KEY")
_supabase_service = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if _supabase_url and _supabase_anon:
    log.info(f"Supabase 已配置: URL={_supabase_url[:30]}..., ANON_KEY={'已设置' if _supabase_anon else '未设置'}, SERVICE_KEY={'已设置' if _supabase_service else '未设置'}")
else:
    log.info(f"Supabase 未配置: URL={'已设置' if _supabase_url else '未设置'}, ANON_KEY={'已设置' if _supabase_anon else '未设置'}")


from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from fastapi_app.routers import kb, kb_embedding, files, paper2drawio, paper2ppt, auth, data_insight
from fastapi_app.middleware.api_key import APIKeyMiddleware
from fastapi_app.middleware.logging import LoggingMiddleware
from workflow_engine.utils import get_project_root

# 导入workflow模块以触发所有workflow注册
from workflow_engine import workflow

# 本地 Embedding 服务端口（Octen-Embedding-0.6B）
LOCAL_EMBEDDING_PORT = 26210
LOCAL_EMBEDDING_URL = f"http://127.0.0.1:{LOCAL_EMBEDDING_PORT}/v1/embeddings"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 默认使用本地 Embedding（Octen-Embedding-0.6B），不再用远程；设 USE_LOCAL_EMBEDDING=0 可关闭
    use_local = os.getenv("USE_LOCAL_EMBEDDING", "1").strip().lower() in ("1", "true", "yes")
    proc = None
    if use_local:
        # 检查 embedding 服务是否已在运行（--reload 场景下避免重复拉起）
        _already_running = False
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{LOCAL_EMBEDDING_PORT}/health", timeout=2)
            _already_running = True
            log.info(f"本地 Embedding 已在运行，复用 @ {LOCAL_EMBEDDING_URL}")
        except Exception as e:
            log.debug(f"本地 Embedding 健康检查失败: {e}")
        if not _already_running:
            try:
                proc = subprocess.Popen(
                    [
                        sys.executable, "-m", "uvicorn",
                        "fastapi_app.embedding_server:app",
                        "--host", "127.0.0.1",
                        "--port", str(LOCAL_EMBEDDING_PORT),
                    ],
                    cwd=str(Path(__file__).resolve().parent.parent),
                    stdout=None,
                    stderr=None,
                )
                for _ in range(60):
                    time.sleep(0.5)
                    if proc.poll() is not None:
                        log.warning("本地 Embedding 子进程已退出，请检查上方日志")
                        break
                    try:
                        import urllib.request
                        urllib.request.urlopen(f"http://127.0.0.1:{LOCAL_EMBEDDING_PORT}/health", timeout=1)
                        log.info(f"本地 Embedding 已就绪 (Octen-Embedding-0.6B) @ {LOCAL_EMBEDDING_URL}")
                        break
                    except Exception:
                        continue
                else:
                    log.warning("本地 Embedding 启动超时，请检查 sentence-transformers 是否已安装及上方日志")
            except Exception as e:
                log.warning(f"启动本地 Embedding 失败: {e}")
        os.environ["EMBEDDING_API_URL"] = LOCAL_EMBEDDING_URL
        os.environ["EMBEDDING_MODEL"] = "Octen-Embedding-0.6B"

    # 检查 TTS 模型
    use_local_tts = os.getenv("USE_LOCAL_TTS", "0").strip().lower() in ("1", "true", "yes")
    tts_engine = os.getenv("TTS_ENGINE", "qwen").strip().lower()
    if use_local_tts:
        try:
            if tts_engine == "qwen":
                from fastapi_app.qwen_tts_manager import check_and_download_model
                check_and_download_model()
            elif tts_engine == "firered":
                from fastapi_app.fireredtts_manager import check_and_download_model
                check_and_download_model()
        except Exception as e:
            log.warning(f"TTS 模型检查失败: {e}")

    yield
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例。

    这里只做基础框架搭建：
    - CORS 配置
    - 路由挂载
    - 静态文件服务
    """
    app = FastAPI(
        title="DataFlow Agent FastAPI Backend",
        version="0.1.0",
        description="HTTP API wrapper for dataflow_agent.workflow.* pipelines",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Logging middleware (first to capture all requests)
    app.add_middleware(LoggingMiddleware)

    # API key verification for /api/* routes
    app.add_middleware(APIKeyMiddleware)

    # 路由挂载（Notebook / frontend-v2 相关）
    app.include_router(kb.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_embedding.router, prefix="/api/v1", tags=["Knowledge Base Embedding"])
    app.include_router(files.router, prefix="/api/v1", tags=["Files"])
    app.include_router(paper2drawio.router, prefix="/api/v1", tags=["Paper2Drawio"])
    app.include_router(paper2ppt.router, prefix="/api/v1", tags=["Paper2PPT"])
    app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
    app.include_router(data_insight.router, prefix="/api/v1", tags=["Data Insight"])

    # 静态文件：/outputs 下的文件（兼容 URL 中 %40 与 磁盘 @ 两种路径）
    project_root = get_project_root()
    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/outputs/{path:path}")
    async def serve_outputs(path: str):
        # 先尝试 URL 解码后的路径（%40 -> @），再尝试字面量路径（兼容旧数据 dev%40...）
        path_decoded = unquote(path)
        outputs_resolved = outputs_dir.resolve()
        for candidate in (path_decoded, path):
            try:
                file_path = (outputs_dir / candidate).resolve()
                if not str(file_path).startswith(str(outputs_resolved)):
                    continue
                if file_path.is_file():
                    resp = FileResponse(path=str(file_path), filename=file_path.name)
                    # PDF 使用 inline 以便浏览器内嵌预览，不触发下载
                    if file_path.suffix.lower() == ".pdf":
                        resp.headers["Content-Disposition"] = "inline"
                    return resp
            except Exception as e:
                log.debug(f"文件路径解析失败: {candidate}, 错误: {e}")
                continue
        raise HTTPException(status_code=404, detail="Not found")

    log.info(f"Serving /outputs from {outputs_dir}")

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    log.info("后端已连接 / Backend ready")
    return app


# 供 uvicorn 使用：uvicorn fastapi_app.main:app --reload --port 9999
app = create_app()
