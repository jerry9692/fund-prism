"""
Tool API 路由定义。

一期最小 5 个接口 + 根路由和健康检查。
所有接口返回统一结构: APIResponse[T] = {data, metadata, evidence, warnings, conclusion_status}
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.api.deps import get_session
from fund_research.core.enums import ConclusionStatus
from fund_research.core.schemas import APIResponse

router = APIRouter(prefix="/api/v1", tags=["Tool API v1"])


# ============================================================
# 根路由 & 健康检查
# ============================================================

@router.get("/")
def root() -> dict:
    """API 根路由。"""
    return {
        "platform": "Fund Research Platform",
        "version": __version__,
        "docs": "/docs",
        "disclaimer": "本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。",
    }


@router.get("/health")
def health_check(db: Session = Depends(get_session)) -> dict:
    """健康检查。"""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "version": __version__,
    }


# ============================================================
# 1. get_fund_profile — 基金基本信息
# ============================================================

@router.get("/funds/{fund_code}/profile")
def get_fund_profile(
    fund_code: str,
    db: Session = Depends(get_session),
) -> APIResponse[dict]:
    """
    获取基金基础信息、经理、分类、规模、费率。

    返回: fund_code, short_name, full_name, company, managers,
           category, sub_category, inception_date, status,
           scale_history, fee_info
    """
    # TODO: 第零阶段实现数据库查询
    return APIResponse(
        data=None,
        metadata={
            "tool": "get_fund_profile",
            "fund_code": fund_code,
            "platform_version": __version__,
            "implemented": False,
        },
        evidence=[],
        warnings=["接口骨架已就绪，数据查询将在第零阶段实现"],
        conclusion_status=ConclusionStatus.NEEDS_REVIEW,
    )


# ============================================================
# 2. get_nav_metrics — 净值与收益风险指标
# ============================================================

@router.get("/funds/{fund_code}/nav-metrics")
def get_nav_metrics(
    fund_code: str,
    start: date | None = Query(None, description="起始日期"),
    end: date | None = Query(None, description="结束日期"),
    db: Session = Depends(get_session),
) -> APIResponse[dict]:
    """
    获取净值指标：收益、回撤、波动、夏普、卡玛、索提诺、信息比率等。

    支持多区间：今年以来、近1/3/6月、近1/3/5年、成立以来、经理任职以来。
    每个指标附带计算口径和基准选择。
    """
    return APIResponse(
        data=None,
        metadata={
            "tool": "get_nav_metrics",
            "fund_code": fund_code,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
            "platform_version": __version__,
            "implemented": False,
        },
        evidence=[],
        warnings=["接口骨架已就绪，将在第零阶段实现"],
        conclusion_status=ConclusionStatus.NEEDS_REVIEW,
    )


# ============================================================
# 3. get_disclosed_holdings — 公开披露持仓
# ============================================================

@router.get("/funds/{fund_code}/holdings")
def get_disclosed_holdings(
    fund_code: str,
    report_date: date | None = Query(None, description="报告期（如不传则返回最新）"),
    db: Session = Depends(get_session),
) -> APIResponse[dict]:
    """
    获取公开披露持仓。

    包含：股票持仓（代码/名称/行业/市值/权重）、债券持仓（评级/久期/票息）、
          转债持仓、持仓变动分析（新增/增持/减持/退出）。
    支持按报告期切换、按资产类型筛选。
    """
    return APIResponse(
        data=None,
        metadata={
            "tool": "get_disclosed_holdings",
            "fund_code": fund_code,
            "report_date": str(report_date) if report_date else "latest",
            "platform_version": __version__,
            "implemented": False,
        },
        evidence=[],
        warnings=["接口骨架已就绪，将在第零阶段实现"],
        conclusion_status=ConclusionStatus.NEEDS_REVIEW,
    )


# ============================================================
# 4. run_exposure_analysis — 风格/行业暴露 + 静态归因
# ============================================================

@router.post("/analysis/exposure")
def run_exposure_analysis(
    fund_code: str,
    window: int = Query(60, ge=20, le=504, description="滚动窗口（交易日）"),
    db: Session = Depends(get_session),
) -> APIResponse[dict]:
    """
    运行风格/行业暴露分析和静态归因。

    输出：
    - 风格暴露曲线（大盘/中盘/小盘、成长/价值/均衡）
    - 行业暴露热力图
    - 静态 Brinson 归因结果
    - 未解释残差
    - 风格漂移和偏离提示
    """
    return APIResponse(
        data=None,
        metadata={
            "tool": "run_exposure_analysis",
            "fund_code": fund_code,
            "window": window,
            "platform_version": __version__,
            "implemented": False,
        },
        evidence=[],
        warnings=["接口骨架已就绪，将在第零阶段后实现"],
        conclusion_status=ConclusionStatus.NEEDS_REVIEW,
    )


# ============================================================
# 5. build_research_packet — 生成研究包
# ============================================================

@router.post("/research/packet")
def build_research_packet(
    fund_code: str,
    template: str = Query(
        "single_fund_checkup",
        description="研究包模板: single_fund_checkup / manager_profile / style_drift / holdings_deep_dive",
    ),
    db: Session = Depends(get_session),
) -> APIResponse[dict]:
    """
    生成标准化研究包（JSON + Markdown）。

    一期包含：基础信息、经理、净值指标、公开持仓、风格暴露、
              静态归因、残差、风险提示、证据列表、数据质量摘要。
    研究包附带完整 metadata：数据日期、算法版本、数据源等级、置信度、免责声明。
    """
    return APIResponse(
        data=None,
        metadata={
            "tool": "build_research_packet",
            "fund_code": fund_code,
            "template": template,
            "platform_version": __version__,
            "implemented": False,
        },
        evidence=[],
        warnings=["接口骨架已就绪，将在第零阶段后实现"],
        conclusion_status=ConclusionStatus.NEEDS_REVIEW,
    )
