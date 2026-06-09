"""
FastAPI 应用入口。

提供 Tool API 接口，遵循需求书 v0.4 第 6.3.4 节定义的：
- 统一返回结构 (data, metadata, evidence, warnings, conclusion_status)
- 一期最小 5 个接口
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fund_research import __version__
from fund_research.api.router import router
from fund_research.api.v2_router import v2_router
from fund_research.db.session import init_db
from fund_research.utils.logging import logger, setup_logging


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

    # CORS — 本地开发允许所有来源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(router)
    app.include_router(v2_router)

    return app
