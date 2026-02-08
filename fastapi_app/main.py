from __future__ import annotations

from pathlib import Path

# 加载 .env，使 SUPABASE_* 等环境变量在 os.getenv 中可用
try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent.parent
    load_dotenv(_root / "fastapi_app" / ".env")
    load_dotenv(_root / ".env")
except ImportError:
    pass

from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from fastapi_app.routers import kb, kb_embedding, files, paper2drawio, paper2ppt
from fastapi_app.middleware.api_key import APIKeyMiddleware
from dataflow_agent.utils import get_project_root


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
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API key verification for /api/* routes
    app.add_middleware(APIKeyMiddleware)

    # 路由挂载（Notebook / frontend-v2 相关）
    app.include_router(kb.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_embedding.router, prefix="/api/v1", tags=["Knowledge Base Embedding"])
    app.include_router(files.router, prefix="/api/v1", tags=["Files"])
    app.include_router(paper2drawio.router, prefix="/api/v1", tags=["Paper2Drawio"])
    app.include_router(paper2ppt.router, prefix="/api/v1", tags=["Paper2PPT"])

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
            except Exception:
                continue
        raise HTTPException(status_code=404, detail="Not found")

    print(f"[INFO] Serving /outputs from {outputs_dir}")

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    print("[INFO] 后端已连接 / Backend ready")
    return app


# 供 uvicorn 使用：uvicorn fastapi_app.main:app --reload --port 9999
app = create_app()
