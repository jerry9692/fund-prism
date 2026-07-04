"""
FastAPI 应用入口。

提供 Tool API 接口，遵循需求书 v0.4 第 6.3.4 节定义的：
- 统一返回结构 (data, metadata, evidence, warnings, conclusion_status)
- 一期最小 5 个接口
- 全局异常处理：所有错误均返回 APIResponse 格式，不返回 HTML
"""

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fund_research import __version__
from fund_research.api.router import router
from fund_research.api.v2_router import v2_router
from fund_research.core.enums import ConclusionStatus
from fund_research.core.schemas import APIResponse
from fund_research.db.session import init_db
from fund_research.utils.logging import logger, setup_logging


def _error_response(
    status_code: int,
    message: str,
    conclusion_status: ConclusionStatus = ConclusionStatus.NEEDS_REVIEW,
) -> JSONResponse:
    """构建统一错误响应（始终返回 APIResponse 格式 JSON）。"""
    return JSONResponse(
        status_code=status_code,
        content=APIResponse[None](
            data=None,
            metadata={"request_id": str(uuid4())},
            warnings=[message],
            conclusion_status=conclusion_status,
        ).model_dump(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时
    setup_logging()
    try:
        init_db()
        logger.info("数据库已就绪")
    except Exception as e:
        logger.warning(f"数据库初始化跳过（可能已存在）: {e}")

    logger.info(f"Fund Research API v{__version__} 启动完成")
    yield

    # 关闭时
    logger.info("Fund Research API 已关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例（工厂函数）。"""
    app = FastAPI(
        title="Fund Research API",
        description="""
AI-oriented 开源个人基金研究平台 — Tool API。

## 一期接口（5 个）

- `GET /api/v1/funds/{fund_code}/profile` — 基金基本信息
- `GET /api/v1/funds/{fund_code}/nav-metrics` — 净值与收益风险指标
- `GET /api/v1/funds/{fund_code}/holdings` — 公开披露持仓
- `POST /api/v1/analysis/exposure` — 风格/行业暴露分析
- `POST /api/v1/research/packet` — 生成研究包

## 统一返回结构

每个接口返回 `{data, metadata, evidence, warnings, conclusion_status}`。

## 免责声明

本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。
        """,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 全局异常处理器：确保所有错误都返回 APIResponse JSON ----

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求参数校验错误 → 422 + APIResponse 格式。"""
        errors = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "")
            errors.append(f"{loc}: {msg}" if loc else msg)
        message = f"参数校验失败: {'; '.join(errors)}"
        logger.warning(f"参数校验失败 [{request.method} {request.url.path}]: {message}")
        return _error_response(422, message)

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """未捕获异常 → 500 + APIResponse 格式（不暴露 HTML/堆栈给前端）。"""
        import traceback

        tb = traceback.format_exc()
        logger.error(f"未处理异常 [{request.method} {request.url.path}]: {exc}\n{tb}")
        return _error_response(500, f"服务器内部错误: {type(exc).__name__}")

    app.include_router(router)
    app.include_router(v2_router)

    project_root = Path(__file__).parent.parent.parent.parent
    frontend_dist = project_root / "frontend" / "dist"
    if frontend_dist.exists() and frontend_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = frontend_dist / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(frontend_dist / "index.html"))

    return app
