"""FastAPI 应用入口。

对应代码设计 03 号文档八节。

运行：uvicorn main:app --reload
或：python main.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.api.session_service import SessionManager
from src.config import AppConfig
from src.errors.types import AgentError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """构造 FastAPI 应用，挂载路由和中间件。"""
    config = AppConfig.from_env()

    app = FastAPI(
        title="CodeMate",
        description="编程智能体 with 树形对话历史",
        version="0.1.0",
    )

    # CORS 中间件：允许前端从不同端口访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局状态：SessionManager 单例
    app.state.session_manager = SessionManager(config)
    app.state.config = config

    # 挂载路由
    app.include_router(router)

    # 异常处理器：把 AgentError 转成统一格式的 JSON
    @app.exception_handler(AgentError)
    async def agent_error_handler(request: Request, exc: AgentError):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "suggestions": getattr(exc, "suggestions", []),
                }
            },
        )

    @app.get("/")
    async def root():
        return {
            "service": "CodeMate",
            "version": "0.1.0",
            "status": "running",
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    logger.info(
        "应用启动完成，workspace=%s, data_dir=%s",
        config.workspace,
        config.data_dir,
    )

    return app


app = create_app()


if __name__ == "__main__":
    config = AppConfig.from_env()
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info",
    )
