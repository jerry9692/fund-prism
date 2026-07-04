"""
Tool API 路由定义。

一期最小 5 个接口 + 根路由和健康检查。
所有接口返回统一结构: APIResponse[T] = {data, metadata, evidence, warnings, conclusion_status}
"""

from datetime import date
from time import perf_counter
from typing import Annotated, Any
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.analysis.attribution import (
    ALGORITHM_NAME as ATTRIBUTION_ALGORITHM_NAME,
)
from fund_research.analysis.attribution import (
    ALGORITHM_VERSION as ATTRIBUTION_ALGORITHM_VERSION,
)
from fund_research.analysis.attribution import calculate_static_attribution
from fund_research.analysis.exposure import (
    ALGORITHM_NAME as EXPOSURE_ALGORITHM_NAME,
)
from fund_research.analysis.exposure import (
    ALGORITHM_VERSION as EXPOSURE_ALGORITHM_VERSION,
)
from fund_research.analysis.exposure import DEFAULT_STYLE_FACTORS, calculate_style_exposure
from fund_research.analysis.holdings import (
    ALGORITHM_NAME as HOLDINGS_ALGORITHM_NAME,
)
from fund_research.analysis.holdings import (
    ALGORITHM_VERSION as HOLDINGS_ALGORITHM_VERSION,
)
from fund_research.analysis.holdings import analyze_disclosed_holdings
from fund_research.analysis.nav_metrics import (
    ALGORITHM_NAME as NAV_METRICS_ALGORITHM_NAME,
)
from fund_research.analysis.nav_metrics import (
    ALGORITHM_VERSION as NAV_METRICS_ALGORITHM_VERSION,
)
from fund_research.analysis.nav_metrics import calculate_nav_metrics
from fund_research.api.deps import get_session
from fund_research.config.settings import get_settings
from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    EvidenceType,
)
from fund_research.core.schemas import AlgorithmMetadata, APIResponse, EvidenceRecord
from fund_research.db.models import (
    DataSourceSnapshot,
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    ResearchPacketRecord,
    StaticAttributionResult,
    StockDaily,
    StyleExposureResult,
    ToolAPICallLog,
)
from fund_research.research.packet import build_single_fund_packet, persist_research_packet

router = APIRouter(prefix="/api/v1", tags=["Tool API v1"])

_settings = get_settings()

SessionDep = Annotated[Session, Depends(get_session)]
StartDateQuery = Annotated[date | None, Query(description="起始日期")]
EndDateQuery = Annotated[date | None, Query(description="结束日期")]
ReportDateQuery = Annotated[
    date | None,
    Query(description="报告期（如不传则返回最新）"),
]
AssetTypeQuery = Annotated[
    str | None,
    Query(description="资产类型过滤，例如 股票/债券/转债；不传则返回全部公开披露持仓"),
]
WindowQuery = Annotated[
    int,
    Query(ge=20, le=504, description="滚动窗口（交易日）"),
]
TemplateQuery = Annotated[
    str,
    Query(
        description=(
            "研究包模板: single_fund_checkup / manager_profile / style_drift / holdings_deep_dive"
        ),
    ),
]
IndexesBody = Annotated[
    list[str] | None,
    Body(None, description="自定义风格因子指数代码列表"),
]


class ScreenRequest(BaseModel):
    filters: dict | None = None
    sort_by: str | None = None
    sort_order: str | None = "desc"
    limit: int | None = 100
    offset: int | None = 0


class DiffRequest(BaseModel):
    fund_code: str | None = None
    left_packet_id: str | None = None
    right_packet_id: str | None = None
    left_snapshot: str | None = None
    right_snapshot: str | None = None


class ExposureRequest(BaseModel):
    fund_code: str
    window: int = 60
    indexes: list[str] | None = None


class PacketRequest(BaseModel):
    fund_code: str
    template: str = "single_fund_checkup"


ScreenRequestBody = Annotated[ScreenRequest, Body(default_factory=ScreenRequest)]
DiffRequestBody = Annotated[DiffRequest, Body(default_factory=DiffRequest)]
ExposureRequestBody = Annotated[ExposureRequest, Body(...)]
PacketRequestBody = Annotated[PacketRequest, Body(...)]


def _log_tool_api_call(
    db: Session,
    tool_name: str,
    parameters: dict[str, Any],
    response: APIResponse[dict],
    started_at: float,
) -> APIResponse[dict]:
    """Persist a lightweight Tool API call log before returning the response."""
    status = response.conclusion_status.value if response.conclusion_status else "unknown"
    error_message = None
    if response.data is None and response.warnings:
        error_message = "; ".join(response.warnings)
    db.add(
        ToolAPICallLog(
            call_id=f"api_{uuid4().hex[:12]}",
            tool_name=tool_name,
            caller="api",
            parameters=parameters,
            status=status,
            response_time_ms=(perf_counter() - started_at) * 1000,
            error_message=error_message,
        )
    )
    db.commit()
    return response


def _snapshot_summary(snapshot: DataSourceSnapshot) -> dict[str, Any]:
    return {
        "source_name": snapshot.source_name,
        "source_type": snapshot.source_type,
        "source_level": snapshot.source_level,
        "fetch_timestamp": snapshot.fetch_timestamp.isoformat(),
        "trade_date": str(snapshot.trade_date) if snapshot.trade_date else None,
        "entity_type": snapshot.entity_type,
        "field_count": snapshot.field_count,
        "record_count": snapshot.record_count,
        "coverage_rate": snapshot.coverage_rate,
        "missing_fields": snapshot.missing_fields,
        "anomaly_count": snapshot.anomaly_count,
        "is_success": snapshot.is_success,
        "error_message": snapshot.error_message,
    }


def _latest_snapshot_summaries(db: Session, entity_types: list[str]) -> dict[str, dict[str, Any]]:
    """Return the latest source snapshot summary for each requested entity type."""
    summaries: dict[str, dict[str, Any]] = {}
    for entity_type in entity_types:
        snapshot = db.scalar(
            select(DataSourceSnapshot)
            .where(DataSourceSnapshot.entity_type == entity_type)
            .order_by(DataSourceSnapshot.fetch_timestamp.desc())
            .limit(1)
        )
        if snapshot is not None:
            summaries[entity_type] = _snapshot_summary(snapshot)
    return summaries


def _run_static_attribution_for_latest_holdings(
    db: Session,
    fund_code: str,
    end_date: date | None,
) -> tuple[dict | None, list[str], ConclusionStatus]:
    report_date = db.scalar(
        select(FundDisclosedHoldings.report_date)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(1)
    )
    if report_date is None:
        return None, ["基金公开披露持仓不存在，跳过静态归因"], ConclusionStatus.NEEDS_REVIEW

    holdings_rows = db.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date == report_date)
        .order_by(FundDisclosedHoldings.rank_in_holdings, FundDisclosedHoldings.security_code)
    ).all()
    security_codes = sorted({row.security_code for row in holdings_rows if row.security_code})
    if not security_codes:
        return None, ["公开披露持仓缺少证券代码，跳过静态归因"], ConclusionStatus.NEEDS_REVIEW

    stock_stmt = select(StockDaily).where(StockDaily.stock_code.in_(security_codes))
    nav_stmt = select(FundNAV).where(FundNAV.fund_code == fund_code)
    if report_date:
        stock_stmt = stock_stmt.where(StockDaily.trade_date > report_date)
        nav_stmt = nav_stmt.where(FundNAV.trade_date > report_date)
    if end_date:
        stock_stmt = stock_stmt.where(StockDaily.trade_date <= end_date)
        nav_stmt = nav_stmt.where(FundNAV.trade_date <= end_date)

    stock_rows = db.scalars(stock_stmt.order_by(StockDaily.stock_code, StockDaily.trade_date)).all()
    fund_nav_rows = db.scalars(nav_stmt.order_by(FundNAV.trade_date)).all()
    result = calculate_static_attribution(
        pd.DataFrame(
            [
                {
                    "report_date": row.report_date,
                    "asset_type": row.asset_type,
                    "security_code": row.security_code,
                    "security_name": row.security_name,
                    "weight_pct": row.weight_pct,
                    "industry": row.industry,
                }
                for row in holdings_rows
            ]
        ),
        pd.DataFrame(
            [
                {
                    "stock_code": row.stock_code,
                    "trade_date": row.trade_date,
                    "close_price": row.close_price,
                    "daily_return": row.daily_return,
                }
                for row in stock_rows
            ]
        ),
        pd.DataFrame(
            [
                {
                    "trade_date": row.trade_date,
                    "unit_nav": row.unit_nav,
                    "accumulated_nav": row.accumulated_nav,
                    "adjusted_nav": row.adjusted_nav,
                    "daily_return": row.daily_return,
                }
                for row in fund_nav_rows
            ]
        ),
    )
    conclusion_status = (
        ConclusionStatus.OBSERVATION if result.is_sufficient else ConclusionStatus.NEEDS_REVIEW
    )
    confidence = (
        ConfidenceLevel.LOW if result.is_sufficient else ConfidenceLevel.NEEDS_REVIEW
    ).value

    existing = db.scalar(
        select(StaticAttributionResult)
        .where(StaticAttributionResult.fund_code == fund_code)
        .where(StaticAttributionResult.report_date == report_date)
        .where(StaticAttributionResult.algorithm_name == ATTRIBUTION_ALGORITHM_NAME)
        .where(StaticAttributionResult.algorithm_version == ATTRIBUTION_ALGORITHM_VERSION)
    )
    if existing is None:
        existing = StaticAttributionResult(
            fund_code=fund_code,
            report_date=report_date,
            benchmark=None,
            algorithm_name=ATTRIBUTION_ALGORITHM_NAME,
            algorithm_version=ATTRIBUTION_ALGORITHM_VERSION,
        )
        db.add(existing)
    existing.parameters = {
        "end_date": str(end_date) if end_date else None,
        "source": "latest_disclosed_holdings",
        "method": "disclosed_weight_times_security_return",
    }
    existing.total_return = result.total_return
    existing.benchmark_return = None
    existing.allocation_effect = None
    existing.selection_effect = result.explained_return
    existing.interaction_effect = None
    existing.sector_rotation_effect = None
    existing.residual = result.residual
    existing.residual_pct = result.residual_pct
    existing.detail = result.to_data()
    existing.confidence = confidence
    existing.conclusion_status = conclusion_status.value
    existing.warnings = {"items": result.warnings}
    return result.to_data(), result.warnings, conclusion_status


def _fund_managers(db: Session, fund_code: str) -> list[dict]:
    tenures = db.scalars(
        select(FundManagerTenure)
        .where(FundManagerTenure.fund_code == fund_code)
        .order_by(
            FundManagerTenure.is_current.desc(),
            FundManagerTenure.start_date.desc(),
        )
    ).all()
    managers = []
    for tenure in tenures:
        manager = db.scalar(
            select(FundManager).where(FundManager.manager_id == tenure.manager_id)
        )
        managers.append(
            {
                "manager_id": tenure.manager_id,
                "name": manager.name if manager else None,
                "start_date": str(tenure.start_date) if tenure.start_date else None,
                "end_date": str(tenure.end_date) if tenure.end_date else None,
                "is_current": tenure.is_current,
                "tenure_days": tenure.tenure_days,
                "tenure_return": tenure.tenure_return,
                "experience_years": manager.experience_years if manager else None,
                "education": manager.education if manager else None,
            }
        )
    return managers


def _scale_history(db: Session, fund_code: str, limit: int = 12) -> list[dict]:
    rows = db.scalars(
        select(FundScale)
        .where(FundScale.fund_code == fund_code)
        .order_by(FundScale.report_date.desc())
        .limit(limit)
    ).all()
    return [
        {
            "report_date": str(row.report_date),
            "total_nav": row.total_nav,
            "total_share": row.total_share,
            "share_change": row.share_change,
        }
        for row in rows
    ]


def _fee_info(db: Session, fund_code: str) -> dict | None:
    fee = db.scalar(
        select(FundFee)
        .where(FundFee.fund_code == fund_code)
        .order_by(FundFee.effective_date.desc(), FundFee.created_at.desc())
        .limit(1)
    )
    if fee is None:
        return None
    return {
        "mgmt_fee_pct": fee.mgmt_fee_pct,
        "custody_fee_pct": fee.custody_fee_pct,
        "sales_service_fee_pct": fee.sales_service_fee_pct,
        "subscribe_fee_range": fee.subscribe_fee_range,
        "redeem_fee_range": fee.redeem_fee_range,
        "effective_date": str(fee.effective_date) if fee.effective_date else None,
        "data_source_level": fee.data_source_level,
    }


# ============================================================
# 根路由 & 健康检查
# ============================================================


@router.get("/")
def root() -> APIResponse[dict]:
    """API 根路由。"""
    return APIResponse(
        data={
            "platform": "Fund Research Platform",
            "version": __version__,
            "docs": "/docs",
            "disclaimer": "本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。",
        },
        metadata={"tool": "root", "platform_version": __version__},
    )


@router.get("/health")
def health_check(db: SessionDep) -> APIResponse[dict]:
    """健康检查。"""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return APIResponse(
        data={
            "status": "ok" if db_ok else "degraded",
            "database": "connected" if db_ok else "disconnected",
            "version": __version__,
        },
        metadata={"tool": "health_check", "platform_version": __version__},
        conclusion_status=ConclusionStatus.FACT if db_ok else ConclusionStatus.NEEDS_REVIEW,
    )


# ============================================================
# 1. get_fund_profile — 基金基本信息
# ============================================================


@router.get("/funds/{fund_code}/profile")
def get_fund_profile(
    fund_code: str,
    db: SessionDep,
) -> APIResponse[dict]:
    """
    获取基金基础信息、经理、分类、规模、费率。

    返回: fund_code, short_name, full_name, company, managers,
           category, sub_category, inception_date, status,
           scale_history, fee_info
    """
    started_at = perf_counter()
    fund = db.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    if fund is None:
        response = APIResponse(
            data=None,
            metadata={
                "tool": "get_fund_profile",
                "fund_code": fund_code,
                "platform_version": __version__,
                "implemented": True,
                "data_snapshots": _latest_snapshot_summaries(
                    db,
                    ["fund_main", "fund_info", "fund_managers", "fund_scale", "fund_fee_detail"],
                ),
            },
            evidence=[],
            warnings=["基金不存在或尚未更新到本地数据库"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(
            db,
            "get_fund_profile",
            {"fund_code": fund_code},
            response,
            started_at,
        )

    company = db.get(FundCompany, fund.fund_company_id) if fund.fund_company_id else None
    managers = _fund_managers(db, fund_code)
    scale_history = _scale_history(db, fund_code)
    fee_info = _fee_info(db, fund_code)
    warnings = []
    if company is None:
        warnings.append("基金公司信息缺失")
    if fund.inception_date is None:
        warnings.append("基金成立日缺失")
    if not managers:
        warnings.append("基金经理任职信息缺失")
    if not scale_history:
        warnings.append("基金规模历史缺失")
    if fee_info is None:
        warnings.append("基金费率信息缺失")

    response = APIResponse(
        data={
            "fund_code": fund.fund_code,
            "short_name": fund.short_name,
            "full_name": fund.full_name,
            "company": company.name if company else None,
            "custodian_bank": fund.custodian_bank,
            "inception_date": str(fund.inception_date) if fund.inception_date else None,
            "category": fund.category,
            "sub_category": fund.sub_category,
            "investment_type": fund.investment_type,
            "operation_mode": fund.operation_mode,
            "status": fund.status,
            "benchmark": fund.benchmark,
            "data_source": fund.data_source,
            "data_source_level": fund.data_source_level,
            "managers": managers,
            "scale_history": scale_history,
            "fee_info": fee_info,
        },
        metadata={
            "tool": "get_fund_profile",
            "fund_code": fund_code,
            "platform_version": __version__,
            "implemented": True,
            "data_snapshots": _latest_snapshot_summaries(
                db,
                ["fund_main", "fund_info", "fund_managers", "fund_scale", "fund_fee_detail"],
            ),
        },
        evidence=[
            EvidenceRecord(
                evidence_id=f"profile:{fund_code}",
                entity_id=f"fund:{fund_code}",
                evidence_type=EvidenceType.RAW_DATA,
                source="fund_main",
                source_level=(
                    DataSourceLevel(fund.data_source_level)
                    if fund.data_source_level in {level.value for level in DataSourceLevel}
                    else DataSourceLevel.B
                ),
                date_range=(
                    (fund.inception_date, fund.inception_date) if fund.inception_date else None
                ),
                data_summary="基金主数据来自本地 fund_main 表",
                confidence=ConfidenceLevel.MEDIUM,
                conclusion_status=ConclusionStatus.FACT,
            )
        ],
        warnings=warnings,
        conclusion_status=ConclusionStatus.FACT,
    )
    return _log_tool_api_call(
        db,
        "get_fund_profile",
        {"fund_code": fund_code},
        response,
        started_at,
    )


# ============================================================
# 2. get_nav_metrics — 净值与收益风险指标
# ============================================================


@router.get("/funds/{fund_code}/nav-metrics")
def get_nav_metrics(
    fund_code: str,
    db: SessionDep,
    start: StartDateQuery = None,
    end: EndDateQuery = None,
    benchmark: str | None = Query(None, description="基准指数代码，如000300(沪深300)"),
) -> APIResponse[dict]:
    """
    获取净值指标：收益、回撤、波动、夏普、卡玛、索提诺、信息比率等。

    返回多区间结果：YTD / 1M / 3M / 6M / 1Y / 3Y / 5Y / since_inception / since_manager。
    每个指标附带计算口径和基准选择。
    """
    from datetime import date as date_type

    from dateutil.relativedelta import relativedelta

    started_at = perf_counter()

    # 全量净值数据
    all_rows = db.scalars(
        select(FundNAV).where(FundNAV.fund_code == fund_code).order_by(FundNAV.trade_date)
    ).all()
    if not all_rows:
        response = APIResponse(
            data=None,
            metadata={"tool": "get_nav_metrics", "fund_code": fund_code, "platform_version": __version__},
            evidence=[],
            warnings=["基金净值数据不存在或尚未更新到本地数据库"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(db, "get_nav_metrics", {"fund_code": fund_code}, response, started_at)

    latest_date = all_rows[-1].trade_date

    # 基金成立日和经理任职日（用于 since_inception / since_manager）
    fund_row = db.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    inception_date = fund_row.inception_date if fund_row else None
    manager_start = db.scalar(
        select(FundManagerTenure.start_date).where(
            FundManagerTenure.fund_code == fund_code,
            FundManagerTenure.is_current,
        )
    )

    resolved_benchmark_code = benchmark or (fund_row.benchmark if fund_row else None)
    bm_all_rows: list[dict] = []
    bm_warnings: list[str] = []
    if resolved_benchmark_code:
        bm_code = resolved_benchmark_code.strip()
        bm_candidates = (
            [f"sh{bm_code}", f"sz{bm_code}"]
            if len(bm_code) == 6 and bm_code.isdigit()
            else [bm_code]
        )
        bm_db_rows = db.scalars(
            select(StockDaily)
            .where(StockDaily.stock_code.in_(bm_candidates))
            .order_by(StockDaily.trade_date)
        ).all()
        if bm_db_rows:
            bm_all_rows = [
                {
                    "trade_date": r.trade_date,
                    "close_price": r.close_price,
                    "daily_return": r.daily_return,
                }
                for r in bm_db_rows
            ]
        else:
            bm_warnings.append(f"基准指数 {resolved_benchmark_code} 行情数据未找到，基准对比指标返回 None")

    fund_data_all = [
        {
            "trade_date": r.trade_date,
            "unit_nav": r.unit_nav,
            "accumulated_nav": r.accumulated_nav,
            "adjusted_nav": r.adjusted_nav,
            "daily_return": r.daily_return,
            "dividend": r.dividend,
            "split_ratio": r.split_ratio,
        }
        for r in all_rows
    ]

    def _slice(from_date: date_type | None, rows: list[dict]) -> list[dict]:
        if from_date is None:
            return []
        return [r for r in rows if r["trade_date"] >= from_date]

    def _compute(
        label: str,
        from_date: date_type | None,
        expected_days: int | None = None,
    ) -> dict:
        rows_slice = _slice(from_date, fund_data_all)
        if not rows_slice:
            return {"label": label, "status": "no_data", "warnings": [f"{label}: 无可用净值数据"]}
        bm_slice = _slice(from_date, bm_all_rows) if bm_all_rows else None
        bm_df = pd.DataFrame(bm_slice) if bm_slice else None
        result = calculate_nav_metrics(pd.DataFrame(rows_slice), benchmark_nav=bm_df)
        warnings = result.warnings.copy()
        status = "computed" if result.is_sufficient else "needs_review"
        if expected_days and result.start_date and result.end_date:
            covered_days = (result.end_date - result.start_date).days
            if covered_days < expected_days * 0.8:
                status = "needs_review"
                warnings.append(
                    f"{label}: 数据覆盖约 {covered_days} 天，低于目标区间 {expected_days} 天的 80%"
                )
        return {
            "label": label,
            "status": status,
            "data": result.to_data(),
            "start_date": str(result.start_date) if result.start_date else None,
            "end_date": str(result.end_date) if result.end_date else None,
            "observations": result.observations,
            "warnings": warnings,
        }

    today = date_type.today()
    periods: dict[str, dict] = {}

    # 预设区间
    ytd_start = date_type(today.year, 1, 1)
    periods["YTD"] = _compute("今年以来", ytd_start)
    periods["1M"] = _compute("近1月", latest_date - relativedelta(months=1), 30)
    periods["3M"] = _compute("近3月", latest_date - relativedelta(months=3), 90)
    periods["6M"] = _compute("近6月", latest_date - relativedelta(months=6), 180)
    periods["1Y"] = _compute("近1年", latest_date - relativedelta(years=1), 365)
    periods["3Y"] = _compute("近3年", latest_date - relativedelta(years=3), 365 * 3)
    periods["5Y"] = _compute("近5年", latest_date - relativedelta(years=5), 365 * 5)
    periods["since_inception"] = _compute("成立以来", inception_date)
    periods["since_manager"] = _compute("当前经理任职以来", manager_start)

    # 自定义区间
    custom = None
    if start or end:
        rows_slice = _slice(start, fund_data_all) if start else list(fund_data_all)
        if end and rows_slice:
            rows_slice = [r for r in rows_slice if r["trade_date"] <= end]
        if rows_slice:
            bm_slice_custom = None
            if bm_all_rows:
                bm_start = start or bm_all_rows[0]["trade_date"]
                bm_slice_custom = [r for r in bm_all_rows if r["trade_date"] >= bm_start]
                if end:
                    bm_slice_custom = [r for r in bm_slice_custom if r["trade_date"] <= end]
            bm_df_custom = pd.DataFrame(bm_slice_custom) if bm_slice_custom else None
            custom_result = calculate_nav_metrics(pd.DataFrame(rows_slice), benchmark_nav=bm_df_custom)
            custom = {
                "label": f"{start or '最早'} ~ {end or '最新'}",
                "status": "computed" if custom_result.is_sufficient else "needs_review",
                "data": custom_result.to_data(),
                "start_date": str(custom_result.start_date) if custom_result.start_date else None,
                "end_date": str(custom_result.end_date) if custom_result.end_date else None,
                "observations": custom_result.observations,
                "warnings": custom_result.warnings,
            }

    dividend_count = sum(1 for r in all_rows if r.dividend is not None)
    all_warnings: list[str] = []
    all_warnings.extend(bm_warnings)
    for p in periods.values():
        all_warnings.extend(p.get("warnings", []))
    has_computed_period = any(p.get("status") == "computed" for p in periods.values())
    has_computed_custom = bool(custom and custom.get("status") == "computed")
    overall_status = (
        ConclusionStatus.COMPUTED
        if has_computed_period or has_computed_custom
        else ConclusionStatus.NEEDS_REVIEW
    )

    evidence = [
        EvidenceRecord(
            evidence_id=f"nav:{fund_code}:{all_rows[0].trade_date}:{latest_date}",
            entity_id=f"fund:{fund_code}",
            evidence_type=EvidenceType.TIME_SERIES,
            source="fund_nav",
            source_level=DataSourceLevel.B,
            date_range=(all_rows[0].trade_date, latest_date),
            algorithm_metadata=AlgorithmMetadata(
                algorithm_name=NAV_METRICS_ALGORITHM_NAME,
                algorithm_version=NAV_METRICS_ALGORITHM_VERSION,
                parameters={"trading_days_per_year": 252, "benchmark": resolved_benchmark_code},
                confidence=ConfidenceLevel.MEDIUM,
                warnings=all_warnings,
            ),
            data_summary=(
                f"净值记录 {len(all_rows)} 条，分红记录 {dividend_count} 条，"
                f"覆盖 {len(periods)} 个预设区间"
            ),
            confidence=ConfidenceLevel.MEDIUM,
            conclusion_status=overall_status,
        )
    ]

    response = APIResponse(
        data={
            "fund_code": fund_code,
            "benchmark": resolved_benchmark_code,
            "periods": {k: {
                "label": v.get("label"), "status": v.get("status"),
                "metrics": v.get("data", {}).get("metrics"),
                "observations": v.get("observations"),
                "start_date": v.get("start_date"),
                "end_date": v.get("end_date"),
                "warnings": v.get("warnings"),
            } for k, v in periods.items()},
            "custom": {
                "label": custom.get("label"),
                "status": custom.get("status"),
                "metrics": custom.get("data", {}).get("metrics"),
                "observations": custom.get("observations"),
                "start_date": custom.get("start_date"),
                "end_date": custom.get("end_date"),
                "warnings": custom.get("warnings"),
            } if custom else None,
        },
        metadata={
            "tool": "get_nav_metrics",
            "fund_code": fund_code,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
            "benchmark": resolved_benchmark_code,
            "platform_version": __version__,
            "implemented": True,
            "algorithm_name": NAV_METRICS_ALGORITHM_NAME,
            "algorithm_version": NAV_METRICS_ALGORITHM_VERSION,
            "inception_date": str(inception_date) if inception_date else None,
            "manager_start": str(manager_start) if manager_start else None,
            "dividend_count": dividend_count,
            "data_snapshots": _latest_snapshot_summaries(db, ["fund_nav", "fund_dividends"]),
        },
        evidence=evidence,
        warnings=all_warnings,
        conclusion_status=overall_status,
    )
    return _log_tool_api_call(
        db, "get_nav_metrics",
        {
            "fund_code": fund_code,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
            "benchmark": resolved_benchmark_code,
        },
        response, started_at,
    )


# ============================================================
# 2b. get_nav_series — 净值时间序列（用于图表绘制）
# ============================================================


@router.get("/funds/{fund_code}/nav-series")
def get_nav_series(
    fund_code: str,
    db: SessionDep,
    start: StartDateQuery = None,
    end: EndDateQuery = None,
    period: str | None = Query(
        None,
        description="快捷时间区间: 1M/3M/6M/1Y/3Y/5Y/YTD/ALL，与start/end互斥，优先使用start/end",
    ),
) -> APIResponse[dict]:
    """
    获取基金净值时间序列（日频），用于前端图表绘制。

    返回 dates[], unit_nav[], accumulated_nav[], daily_return[], 以及
    可选基准指数的 benchmark_dates[] 和 benchmark_nav[]。
    """
    from datetime import date as date_type

    from dateutil.relativedelta import relativedelta

    started_at = perf_counter()

    # 解析时间区间
    stmt = select(FundNAV).where(FundNAV.fund_code == fund_code)
    all_rows = db.scalars(stmt.order_by(FundNAV.trade_date)).all()
    if not all_rows:
        response = APIResponse(
            data=None,
            metadata={"tool": "get_nav_series", "fund_code": fund_code, "platform_version": __version__},
            warnings=["基金净值数据不存在或尚未更新到本地数据库"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(db, "get_nav_series", {"fund_code": fund_code}, response, started_at)

    # 确定起始日期
    first_date = all_rows[0].trade_date
    last_date = all_rows[-1].trade_date

    if start and end:
        range_start, range_end = start, end
    elif period:
        range_end = last_date
        p = period.upper()
        if p == "1M":
            range_start = range_end - relativedelta(months=1)
        elif p == "3M":
            range_start = range_end - relativedelta(months=3)
        elif p == "6M":
            range_start = range_end - relativedelta(months=6)
        elif p == "1Y":
            range_start = range_end - relativedelta(years=1)
        elif p == "3Y":
            range_start = range_end - relativedelta(years=3)
        elif p == "5Y":
            range_start = range_end - relativedelta(years=5)
        elif p == "YTD":
            range_start = date_type(range_end.year, 1, 1)
        else:  # ALL
            range_start = first_date
    else:
        # 默认近1年
        range_end = last_date
        range_start = range_end - relativedelta(years=1)

    # 过滤数据
    filtered = [r for r in all_rows if r.trade_date >= range_start and r.trade_date <= range_end]
    if not filtered:
        response = APIResponse(
            data=None,
            metadata={"tool": "get_nav_series", "fund_code": fund_code},
            warnings=[f"指定区间 {range_start} ~ {range_end} 内无净值数据"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(db, "get_nav_series", {"fund_code": fund_code}, response, started_at)

    # 归一化净值（起始日=1.0）
    base_nav = filtered[0].accumulated_nav or filtered[0].unit_nav
    dates = []
    unit_navs = []
    acc_navs = []
    norm_navs = []
    daily_rets = []
    for r in filtered:
        dates.append(str(r.trade_date))
        unit_navs.append(round(float(r.unit_nav), 4) if r.unit_nav else None)
        acc_navs.append(round(float(r.accumulated_nav), 4) if r.accumulated_nav else None)
        an = float(r.accumulated_nav or r.unit_nav or 0)
        norm_navs.append(round(an / base_nav, 4) if base_nav else None)
        daily_rets.append(round(float(r.daily_return), 6) if r.daily_return is not None else None)

    # 基准指数（如有）
    bm_dates = []
    bm_norm = []
    fund_row = db.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    bm_code = fund_row.benchmark if fund_row else None
    bm_warnings: list[str] = []
    if bm_code:
        bm_candidates = (
            [f"sh{bm_code}", f"sz{bm_code}"]
            if len(bm_code) == 6 and bm_code.isdigit()
            else [bm_code]
        )
        bm_rows = db.scalars(
            select(StockDaily)
            .where(StockDaily.stock_code.in_(bm_candidates))
            .where(StockDaily.trade_date >= range_start)
            .where(StockDaily.trade_date <= range_end)
            .order_by(StockDaily.trade_date)
        ).all()
        if bm_rows:
            bm_base = bm_rows[0].close_price
            for r in bm_rows:
                bm_dates.append(str(r.trade_date))
                bm_norm.append(round(float(r.close_price) / bm_base, 4) if bm_base else None)
        else:
            bm_warnings.append(f"基准 {bm_code} 行情未找到")

    data = {
        "fund_code": fund_code,
        "start_date": str(filtered[0].trade_date),
        "end_date": str(filtered[-1].trade_date),
        "dates": dates,
        "unit_nav": unit_navs,
        "accumulated_nav": acc_navs,
        "normalized_nav": norm_navs,
        "daily_return": daily_rets,
        "benchmark_code": bm_code,
        "benchmark_dates": bm_dates,
        "benchmark_normalized_nav": bm_norm,
        "total_points": len(dates),
    }

    evidence = [
        EvidenceRecord(
            evidence_id=f"nav_series:{fund_code}:{filtered[0].trade_date}_{filtered[-1].trade_date}",
            entity_id=f"fund:{fund_code}",
            evidence_type=EvidenceType.RAW_DATA,
            source="fund_nav",
            source_level=DataSourceLevel.B,
            date_range=(filtered[0].trade_date, filtered[-1].trade_date),
            data_summary=f"净值时间序列 {len(dates)} 个交易日，来自本地 fund_nav 表",
            confidence=ConfidenceLevel.MEDIUM,
            conclusion_status=ConclusionStatus.FACT,
        ),
    ]

    response = APIResponse(
        data=data,
        metadata={
            "tool": "get_nav_series",
            "fund_code": fund_code,
            "platform_version": __version__,
            "period": period,
            "requested_start": str(range_start),
            "requested_end": str(range_end),
        },
        evidence=evidence,
        warnings=bm_warnings,
        conclusion_status=ConclusionStatus.FACT,
    )
    return _log_tool_api_call(
        db, "get_nav_series",
        {"fund_code": fund_code, "start": str(start), "end": str(end), "period": period},
        response, started_at,
    )


# ============================================================
# 3. get_disclosed_holdings — 公开披露持仓
# ============================================================


@router.get("/funds/{fund_code}/holdings")
def get_disclosed_holdings(
    fund_code: str,
    db: SessionDep,
    report_date: ReportDateQuery = None,
    asset_type: AssetTypeQuery = None,
) -> APIResponse[dict]:
    """
    获取公开披露持仓。

    包含：股票持仓（代码/名称/行业/市值/权重）、债券持仓（评级/久期/票息）、
          转债持仓、持仓变动分析（新增/增持/减持/退出）。
    支持按报告期切换、按资产类型筛选。
    """
    started_at = perf_counter()
    if report_date is None:
        latest_stmt = select(FundDisclosedHoldings.report_date).where(
            FundDisclosedHoldings.fund_code == fund_code
        )
        if asset_type:
            latest_stmt = latest_stmt.where(FundDisclosedHoldings.asset_type == asset_type)
        report_date = db.scalar(
            latest_stmt.order_by(FundDisclosedHoldings.report_date.desc()).limit(1)
        )

    rows = []
    previous_rows = []
    if report_date is not None:
        rows_stmt = (
            select(FundDisclosedHoldings)
            .where(FundDisclosedHoldings.fund_code == fund_code)
            .where(FundDisclosedHoldings.report_date == report_date)
        )
        previous_date_stmt = (
            select(FundDisclosedHoldings.report_date)
            .where(FundDisclosedHoldings.fund_code == fund_code)
            .where(FundDisclosedHoldings.report_date < report_date)
        )
        if asset_type:
            rows_stmt = rows_stmt.where(FundDisclosedHoldings.asset_type == asset_type)
            previous_date_stmt = previous_date_stmt.where(
                FundDisclosedHoldings.asset_type == asset_type
            )
        rows = db.scalars(
            rows_stmt.order_by(
                FundDisclosedHoldings.rank_in_holdings,
                FundDisclosedHoldings.security_code,
            )
        ).all()
        previous_report_date = db.scalar(
            previous_date_stmt.order_by(FundDisclosedHoldings.report_date.desc()).limit(1)
        )
        if previous_report_date is not None:
            previous_rows_stmt = (
                select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fund_code)
                .where(FundDisclosedHoldings.report_date == previous_report_date)
            )
            if asset_type:
                previous_rows_stmt = previous_rows_stmt.where(
                    FundDisclosedHoldings.asset_type == asset_type
                )
            previous_rows = db.scalars(
                previous_rows_stmt
                .order_by(
                    FundDisclosedHoldings.rank_in_holdings,
                    FundDisclosedHoldings.security_code,
                )
            ).all()

    holding_rows = [
        {
            "report_date": row.report_date,
            "asset_type": row.asset_type,
            "security_code": row.security_code,
            "security_name": row.security_name,
            "weight_pct": row.weight_pct,
            "market_value": row.market_value,
            "shares": row.shares,
            "rank_in_holdings": row.rank_in_holdings,
            "industry": row.industry,
            "change_direction": row.change_direction,
        }
        for row in rows
    ]
    previous_holding_rows = [
        {
            "report_date": row.report_date,
            "asset_type": row.asset_type,
            "security_code": row.security_code,
            "security_name": row.security_name,
            "weight_pct": row.weight_pct,
            "market_value": row.market_value,
            "shares": row.shares,
            "rank_in_holdings": row.rank_in_holdings,
            "industry": row.industry,
            "change_direction": row.change_direction,
        }
        for row in previous_rows
    ]
    result = analyze_disclosed_holdings(
        pd.DataFrame(holding_rows),
        pd.DataFrame(previous_holding_rows),
    )
    metadata = {
        "tool": "get_disclosed_holdings",
        "fund_code": fund_code,
        "report_date": str(report_date) if report_date else "latest",
        "asset_type": asset_type,
        "platform_version": __version__,
        "implemented": True,
        "algorithm_name": HOLDINGS_ALGORITHM_NAME,
        "algorithm_version": HOLDINGS_ALGORITHM_VERSION,
        "data_snapshots": _latest_snapshot_summaries(
            db,
            ["fund_holdings", "fund_industry_allocation", "fund_portfolio_change"],
        ),
    }
    if not rows:
        response = APIResponse(
            data=None,
            metadata=metadata,
            evidence=[],
            warnings=["基金公开披露持仓不存在或尚未更新到本地数据库"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(
            db,
            "get_disclosed_holdings",
            {
                "fund_code": fund_code,
                "report_date": str(report_date) if report_date else None,
                "asset_type": asset_type,
            },
            response,
            started_at,
        )

    source_level_value = rows[0].data_source_level or DataSourceLevel.B.value
    source_level = (
        DataSourceLevel(source_level_value)
        if source_level_value in {level.value for level in DataSourceLevel}
        else DataSourceLevel.B
    )
    confidence = ConfidenceLevel.LOW if result.is_limited else ConfidenceLevel.MEDIUM
    conclusion_status = (
        ConclusionStatus.OBSERVATION if result.is_limited else ConclusionStatus.COMPUTED
    )

    response = APIResponse(
        data=result.to_data(),
        metadata=metadata,
        evidence=[
            EvidenceRecord(
                evidence_id=f"holdings:{fund_code}:{report_date}",
                entity_id=f"fund:{fund_code}",
                evidence_type=EvidenceType.RAW_DATA,
                source="fund_disclosed_holdings",
                source_level=source_level,
                date_range=(report_date, report_date),
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=HOLDINGS_ALGORITHM_NAME,
                    algorithm_version=HOLDINGS_ALGORITHM_VERSION,
                    parameters={"report_date": str(report_date), "asset_type": asset_type},
                    confidence=confidence,
                    warnings=result.warnings,
                ),
                data_summary=(
                    f"公开披露持仓 {len(rows)} 条，披露粒度 {result.disclosure_granularity}"
                ),
                confidence=confidence,
                conclusion_status=conclusion_status,
            )
        ],
        warnings=result.warnings,
        conclusion_status=conclusion_status,
    )
    return _log_tool_api_call(
        db,
        "get_disclosed_holdings",
        {
            "fund_code": fund_code,
            "report_date": str(report_date) if report_date else None,
            "asset_type": asset_type,
        },
        response,
        started_at,
    )


# ============================================================
# 3.5 screen_funds — 基金筛选与排序
# ============================================================


@router.post("/funds/screen")
def screen_funds(
    db: SessionDep,
    body: ScreenRequestBody,
) -> APIResponse[dict]:
    """
    按条件筛选基金并排序。

    请求体示例:
    {
        "filters": {
            "category": "混合型-偏股",
            "min_inception_years": 3,
            "min_scale_bn": 1.0,
            "max_scale_bn": null,
            "min_manager_tenure_days": 365,
            "max_mgmt_fee_pct": null
        },
        "sort_by": "annualized_return_3y",
        "sort_order": "desc",
        "limit": 50,
        "offset": 0
    }
    """
    from datetime import date as date_type

    from dateutil.relativedelta import relativedelta

    started_at = perf_counter()
    filters = body.filters or {}
    sort_by = body.sort_by or "fund_code"
    sort_order = body.sort_order or "asc"
    limit = min(body.limit or 50, 200)
    offset = body.offset or 0

    # Bulk NAV rows for metric calculation
    metric_sort_keys = {"annualized_return_1y", "annualized_return_3y", "max_drawdown_1y", "sharpe_ratio_1y"}
    nav_by_fund: dict[str, list] = {}

    def _calc_metrics_bulk(fund_code: str) -> dict[str, float | None]:
        nav_rows = nav_by_fund.get(fund_code, [])
        if not nav_rows:
            return {
                "annualized_return_1y": None,
                "annualized_return_3y": None,
                "max_drawdown_1y": None,
                "sharpe_ratio_1y": None,
            }
        latest = nav_rows[-1].trade_date
        nav_data = [
            {"trade_date": n.trade_date, "unit_nav": n.unit_nav, "accumulated_nav": n.accumulated_nav,
             "adjusted_nav": n.adjusted_nav, "daily_return": n.daily_return}
            for n in nav_rows
        ]
        def _period(from_date: date_type) -> dict[str, float | None]:
            sliced = [d for d in nav_data if d["trade_date"] >= from_date]
            if not sliced:
                return {}
            return calculate_nav_metrics(pd.DataFrame(sliced)).metrics
        one_year = _period(latest - relativedelta(years=1))
        three_year = _period(latest - relativedelta(years=3))
        return {
            "annualized_return_1y": one_year.get("annualized_return"),
            "annualized_return_3y": three_year.get("annualized_return"),
            "max_drawdown_1y": one_year.get("max_drawdown"),
            "sharpe_ratio_1y": one_year.get("sharpe_ratio"),
        }

    # 构建基础查询
    stmt = select(FundMain)
    if filters.get("category"):
        stmt = stmt.where(FundMain.category == filters["category"])
    if filters.get("min_inception_years"):
        cutoff = date_type.today() - relativedelta(years=int(filters["min_inception_years"]))
        stmt = stmt.where(FundMain.inception_date <= cutoff)

    candidates = db.scalars(stmt).all()
    if not candidates:
        response = APIResponse(
            data={"funds": [], "total": 0},
            metadata={"tool": "screen_funds", "filters": filters, "platform_version": __version__},
            evidence=[],
            warnings=["无匹配基金"],
            conclusion_status=ConclusionStatus.OBSERVATION,
        )
        return _log_tool_api_call(db, "screen_funds", body.model_dump(), response, started_at)

    candidate_codes = [f.fund_code for f in candidates]

    # Bulk load latest scale for each candidate
    latest_scales: dict[str, float] = {}
    scale_rows = db.execute(
        select(FundScale.fund_code, FundScale.total_nav)
        .where(FundScale.fund_code.in_(candidate_codes))
        .order_by(FundScale.fund_code, FundScale.report_date.desc())
    ).all()
    seen_codes: set[str] = set()
    for row in scale_rows:
        if row.fund_code not in seen_codes:
            latest_scales[row.fund_code] = float(row.total_nav)
            seen_codes.add(row.fund_code)

    # Bulk load manager tenure starts
    mgr_starts: dict[str, date_type] = {}
    tenure_rows = db.scalars(
        select(FundManagerTenure)
        .where(FundManagerTenure.fund_code.in_(candidate_codes), FundManagerTenure.is_current)
    ).all()
    for t in tenure_rows:
        mgr_starts[t.fund_code] = t.start_date

    # Bulk load management fees
    mgmt_fees: dict[str, float] = {}
    fee_rows = db.execute(
        select(FundFee.fund_code, FundFee.mgmt_fee_pct)
        .where(FundFee.fund_code.in_(candidate_codes))
        .order_by(FundFee.fund_code, FundFee.effective_date.desc())
    ).all()
    seen_fee_codes: set[str] = set()
    for row in fee_rows:
        if row.fund_code not in seen_fee_codes:
            mgmt_fees[row.fund_code] = float(row.mgmt_fee_pct)
            seen_fee_codes.add(row.fund_code)

    # Bulk load manager names
    mgr_names: dict[str, str] = {}
    mgr_name_rows = db.execute(
        select(FundManagerTenure.fund_code, FundManager.name)
        .join(FundManager, FundManager.manager_id == FundManagerTenure.manager_id)
        .where(FundManagerTenure.fund_code.in_(candidate_codes), FundManagerTenure.is_current)
    ).all()
    for row in mgr_name_rows:
        mgr_names[row.fund_code] = row.name

    # Bulk NAV rows for metric calculation
    all_nav_rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code.in_(candidate_codes))
        .order_by(FundNAV.fund_code, FundNAV.trade_date)
    ).all()
    for n in all_nav_rows:
        nav_by_fund.setdefault(n.fund_code, []).append(n)

    # NAV counts for data completeness
    nav_counts: dict[str, int] = {}
    nav_count_rows = db.execute(
        select(FundNAV.fund_code, func.count(FundNAV.id).label("cnt"))
        .where(FundNAV.fund_code.in_(candidate_codes))
        .group_by(FundNAV.fund_code)
    ).all()
    for row in nav_count_rows:
        nav_counts[row.fund_code] = int(row.cnt)

    # Holdings count for data completeness
    hold_counts: dict[str, int] = {}
    hold_count_rows = db.execute(
        select(FundDisclosedHoldings.fund_code, func.count(FundDisclosedHoldings.id).label("cnt"))
        .where(FundDisclosedHoldings.fund_code.in_(candidate_codes))
        .group_by(FundDisclosedHoldings.fund_code)
    ).all()
    for row in hold_count_rows:
        hold_counts[row.fund_code] = int(row.cnt)

    # Company cache
    company_cache: dict[int, str] = {}

    # ---- Filter and build results ----
    results = []
    today = date_type.today()
    for fund in candidates:
        code = fund.fund_code
        latest_scale = latest_scales.get(code)
        if filters.get("min_scale_bn") and (latest_scale is None or latest_scale < float(filters["min_scale_bn"])):
            continue
        if filters.get("max_scale_bn") and latest_scale and latest_scale > float(filters["max_scale_bn"]):
            continue

        manager_start = mgr_starts.get(code)
        tenure_days = (today - manager_start).days if manager_start else 0
        if filters.get("min_manager_tenure_days") and tenure_days < int(filters["min_manager_tenure_days"]):
            continue

        mgmt_fee = mgmt_fees.get(code)
        if filters.get("max_mgmt_fee_pct") and mgmt_fee and mgmt_fee > float(filters["max_mgmt_fee_pct"]):
            continue

        manager_name = mgr_names.get(code)

        company_name = None
        if fund.fund_company_id:
            if fund.fund_company_id not in company_cache:
                comp = db.get(FundCompany, fund.fund_company_id)
                company_cache[fund.fund_company_id] = comp.name if comp else None
            company_name = company_cache[fund.fund_company_id]

        # Data completeness
        checks = [
            bool(fund.short_name and fund.category),
            fund.inception_date is not None,
            latest_scale is not None,
            manager_start is not None,
            mgmt_fee is not None,
            nav_counts.get(code, 0) >= 20,
            hold_counts.get(code, 0) > 0,
        ]
        data_completeness = round(sum(1 for c in checks if c) / len(checks), 4)
        if (
            filters.get("min_data_completeness") is not None
            and data_completeness < float(filters["min_data_completeness"])
        ):
            continue

        metrics = _calc_metrics_bulk(code)

        results.append({
            "fund_code": code,
            "short_name": fund.short_name,
            "full_name": fund.full_name,
            "company": company_name,
            "category": fund.category,
            "sub_category": fund.sub_category,
            "inception_date": str(fund.inception_date) if fund.inception_date else None,
            "scale_bn": round(float(latest_scale), 2) if latest_scale else None,
            "manager_name": manager_name,
            "manager": manager_name,
            "manager_tenure_days": tenure_days,
            "mgmt_fee_pct": round(float(mgmt_fee), 4) if mgmt_fee else None,
            "metrics": metrics,
            "data_completeness": data_completeness,
            "custodian_bank": fund.custodian_bank,
            "status": fund.status,
            "benchmark": fund.benchmark,
        })

    total = len(results)

    if sort_by in metric_sort_keys:
        for r in results:
            r["_sort_value"] = r.get("metrics", {}).get(sort_by)
            if r["_sort_value"] is None:
                r["_sort_value"] = -999 if sort_order == "desc" else 999
        reverse = sort_order == "desc"
        results.sort(key=lambda x: x.get("_sort_value", 0), reverse=reverse)
    elif sort_by == "fund_scale":
        results.sort(key=lambda x: x.get("scale_bn") or 0, reverse=sort_order == "desc")
    elif sort_by == "manager_tenure_days":
        results.sort(key=lambda x: x.get("manager_tenure_days", 0), reverse=sort_order == "desc")
    elif sort_by == "inception_date":
        results.sort(key=lambda x: x.get("inception_date", ""), reverse=sort_order == "desc")
    elif sort_by == "data_completeness":
        results.sort(key=lambda x: x.get("data_completeness", 0), reverse=sort_order == "desc")
    else:  # fund_code default
        results.sort(key=lambda x: x.get("fund_code", ""), reverse=sort_order == "desc")

    # 分页
    paged = results[offset:offset + limit]
    # 去掉内部排序字段
    for r in paged:
        r.pop("_sort_value", None)

    response = APIResponse(
        data={"funds": paged, "total": total, "limit": limit, "offset": offset},
        metadata={
            "tool": "screen_funds",
            "filters": filters,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "platform_version": __version__,
            "implemented": True,
        },
        evidence=[
            EvidenceRecord(
                evidence_id="screen_funds:local_tables",
                entity_id="fund:screen",
                evidence_type=EvidenceType.RAW_DATA,
                source="fund_main/fund_scale/fund_manager_tenure/fund_fee/fund_nav",
                source_level=DataSourceLevel.LOCAL,
                data_summary="筛选结果来自本地标准化 ORM 表；收益风险指标按本地 fund_nav 计算",
                confidence=ConfidenceLevel.MEDIUM,
                conclusion_status=ConclusionStatus.COMPUTED if total > 0 else ConclusionStatus.OBSERVATION,
            )
        ],
        warnings=[f"共 {total} 只基金匹配筛选条件"] if total > 0 else ["无匹配基金"],
        conclusion_status=ConclusionStatus.COMPUTED if total > 0 else ConclusionStatus.OBSERVATION,
    )
    return _log_tool_api_call(db, "screen_funds", body.model_dump(), response, started_at)


# ============================================================
# 3.6 search_funds — 基金搜索（搜索框自动补全）
# ============================================================


@router.get("/funds/search")
def search_funds(
    db: SessionDep,
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词（基金代码或名称）"),
    limit: int = Query(10, ge=1, le=50),
) -> APIResponse[dict]:
    """按基金代码或名称模糊搜索，返回匹配列表（用于搜索框自动补全）。"""
    started_at = perf_counter()
    try:
        pattern = f"%{q}%"
        stmt = (
            select(FundMain)
            .where(
                or_(
                    FundMain.fund_code.ilike(pattern),
                    FundMain.short_name.ilike(pattern),
                    FundMain.full_name.ilike(pattern),
                )
            )
            .limit(limit)
        )
        rows = db.scalars(stmt).all()
        results = [
            {
                "fund_code": r.fund_code,
                "short_name": r.short_name,
                "full_name": r.full_name,
                "fund_type": r.category,
            }
            for r in rows
        ]
        response = APIResponse(
            data={"funds": results, "count": len(results)},
            metadata={
                "tool": "fund_search",
                "q": q,
                "limit": limit,
                "platform_version": __version__,
                "implemented": True,
            },
            evidence=[
                EvidenceRecord(
                    evidence_id=f"fund_search:{q}",
                    entity_id="fund:search",
                    evidence_type=EvidenceType.RAW_DATA,
                    source="fund_main",
                    source_level=DataSourceLevel.LOCAL,
                    data_summary=(
                        f"按关键词 '{q}' 模糊搜索基金主表，匹配 {len(results)} 条"
                    ),
                    confidence=ConfidenceLevel.MEDIUM,
                    conclusion_status=ConclusionStatus.FACT,
                )
            ],
            warnings=[],
            conclusion_status=(
                ConclusionStatus.FACT if results else ConclusionStatus.OBSERVATION
            ),
        )
        return _log_tool_api_call(
            db,
            "fund_search",
            {"q": q, "limit": limit},
            response,
            started_at,
        )
    except Exception as exc:
        response = APIResponse(
            data=None,
            metadata={
                "tool": "fund_search",
                "q": q,
                "platform_version": __version__,
            },
            evidence=[],
            warnings=[f"搜索失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(
            db,
            "fund_search",
            {"q": q},
            response,
            started_at,
        )


# ============================================================
# 4. run_exposure_analysis — 风格/行业暴露 + 静态归因
# ============================================================


@router.post("/analysis/exposure")
def run_exposure_analysis(
    db: SessionDep,
    body: ExposureRequestBody,
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
    started_at = perf_counter()
    fund_code = body.fund_code
    window = body.window
    indexes = body.indexes
    nav_rows = db.scalars(
        select(FundNAV).where(FundNAV.fund_code == fund_code).order_by(FundNAV.trade_date)
    ).all()

    def _normalize_index_code(code: str) -> str:
        code = code.strip()
        if len(code) == 6 and code.isdigit():
            if code.startswith("000") or code.startswith("00"):
                return f"sh{code}"
            if code.startswith("399"):
                return f"sz{code}"
            return f"sh{code}"
        return code

    if indexes:
        normalized_codes = [_normalize_index_code(c) for c in indexes]
        factor_symbols = {code: code for code in normalized_codes}
        factor_codes = normalized_codes
    else:
        factor_symbols = DEFAULT_STYLE_FACTORS
        factor_codes = list(DEFAULT_STYLE_FACTORS.values())

    factor_rows = db.scalars(
        select(StockDaily)
        .where(StockDaily.stock_code.in_(factor_codes))
        .order_by(StockDaily.stock_code, StockDaily.trade_date)
    ).all()
    result = calculate_style_exposure(
        pd.DataFrame(
            [
                {
                    "trade_date": row.trade_date,
                    "unit_nav": row.unit_nav,
                    "accumulated_nav": row.accumulated_nav,
                    "adjusted_nav": row.adjusted_nav,
                    "daily_return": row.daily_return,
                }
                for row in nav_rows
            ]
        ),
        pd.DataFrame(
            [
                {
                    "stock_code": row.stock_code,
                    "trade_date": row.trade_date,
                    "close_price": row.close_price,
                    "daily_return": row.daily_return,
                }
                for row in factor_rows
            ]
        ),
        window=window,
        factor_symbols=factor_symbols,
    )
    metadata = {
        "tool": "run_exposure_analysis",
        "fund_code": fund_code,
        "window": window,
        "indexes": indexes,
        "platform_version": __version__,
        "implemented": True,
        "algorithm_name": EXPOSURE_ALGORITHM_NAME,
        "algorithm_version": EXPOSURE_ALGORITHM_VERSION,
        "data_snapshots": _latest_snapshot_summaries(
            db,
            ["fund_nav", "index_daily", "stock_daily", "fund_holdings"],
        ),
    }
    if not result.is_sufficient:
        response = APIResponse(
            data=result.to_data(),
            metadata=metadata,
            evidence=[],
            warnings=result.warnings,
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(
            db,
            "run_exposure_analysis",
            {"fund_code": fund_code, "window": window, "indexes": indexes},
            response,
            started_at,
        )

    confidence = ConfidenceLevel.LOW
    conclusion_status = (
        ConclusionStatus.OBSERVATION
        if result.r_squared is not None and result.r_squared >= 0.2
        else ConclusionStatus.NEEDS_REVIEW
    )
    if conclusion_status == ConclusionStatus.NEEDS_REVIEW:
        result.warnings.append("风格回归解释度偏低，暴露结果需复核")

    existing = db.scalar(
        select(StyleExposureResult)
        .where(StyleExposureResult.fund_code == fund_code)
        .where(StyleExposureResult.calc_date == result.end_date)
        .where(StyleExposureResult.algorithm_name == EXPOSURE_ALGORITHM_NAME)
        .where(StyleExposureResult.algorithm_version == EXPOSURE_ALGORITHM_VERSION)
    )
    if existing is None:
        existing = StyleExposureResult(
            fund_code=fund_code,
            calc_date=result.end_date,
            algorithm_name=EXPOSURE_ALGORITHM_NAME,
            algorithm_version=EXPOSURE_ALGORITHM_VERSION,
            parameters={"window": window, "factor_symbols": result.factor_symbols, "indexes": indexes},
            exposure_type="style",
            exposure_values=result.exposure_values,
        )
        db.add(existing)
    existing.parameters = {"window": window, "factor_symbols": result.factor_symbols, "indexes": indexes}
    existing.exposure_type = "style"
    existing.exposure_values = result.exposure_values
    existing.residual = result.residual
    existing.r_squared = result.r_squared
    existing.confidence = confidence.value
    existing.conclusion_status = conclusion_status.value
    existing.warnings = {"items": result.warnings}
    existing.input_coverage = result.input_coverage
    attribution_data, attribution_warnings, attribution_status = (
        _run_static_attribution_for_latest_holdings(db, fund_code, result.end_date)
    )
    db.commit()

    evidence = [
        EvidenceRecord(
            evidence_id=f"exposure:{fund_code}:{result.end_date}:{window}",
            entity_id=f"fund:{fund_code}",
            evidence_type=EvidenceType.ALGORITHM_RESULT,
            source="style_exposure_result",
            source_level=DataSourceLevel.B,
            date_range=(result.start_date, result.end_date),
            algorithm_metadata=AlgorithmMetadata(
                algorithm_name=EXPOSURE_ALGORITHM_NAME,
                algorithm_version=EXPOSURE_ALGORITHM_VERSION,
                parameters={"window": window, "factor_symbols": result.factor_symbols},
                confidence=confidence,
                warnings=result.warnings,
            ),
            data_summary=(
                f"风格暴露回归样本 {result.observations} 条，"
                f"R²={result.r_squared:.4f}"
                if result.r_squared is not None
                else f"风格暴露回归样本 {result.observations} 条"
            ),
            confidence=confidence,
            conclusion_status=conclusion_status,
        )
    ]
    if attribution_data is not None:
        evidence.append(
            EvidenceRecord(
                evidence_id=f"attribution:{fund_code}:{attribution_data['report_date']}",
                entity_id=f"fund:{fund_code}",
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="static_attribution_result",
                source_level=DataSourceLevel.B,
                date_range=(result.start_date, result.end_date),
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=ATTRIBUTION_ALGORITHM_NAME,
                    algorithm_version=ATTRIBUTION_ALGORITHM_VERSION,
                    parameters={
                        "report_date": attribution_data["report_date"],
                        "method": "disclosed_weight_times_security_return",
                    },
                    confidence=(
                        ConfidenceLevel.LOW
                        if attribution_status == ConclusionStatus.OBSERVATION
                        else ConfidenceLevel.NEEDS_REVIEW
                    ),
                    warnings=attribution_warnings,
                ),
                data_summary=(
                    f"静态归因覆盖率 {attribution_data['coverage_rate']:.2%}，"
                    f"残差 {attribution_data['residual']}"
                ),
                confidence=(
                    ConfidenceLevel.LOW
                    if attribution_status == ConclusionStatus.OBSERVATION
                    else ConfidenceLevel.NEEDS_REVIEW
                ),
                conclusion_status=attribution_status,
            )
        )

    data = result.to_data()
    data["static_attribution"] = attribution_data
    warnings = [*result.warnings, *attribution_warnings]

    response = APIResponse(
        data=data,
        metadata=metadata,
        evidence=evidence,
        warnings=warnings,
        conclusion_status=conclusion_status,
    )
    return _log_tool_api_call(
        db,
        "run_exposure_analysis",
        {"fund_code": fund_code, "window": window, "indexes": indexes},
        response,
        started_at,
    )


# ============================================================
# 4.5 diff_research_packets — 研究包差异对比
# ============================================================


@router.post("/research/diff")
def diff_research_packets(
    db: SessionDep,
    body: DiffRequestBody,
) -> APIResponse[dict]:
    """
    对比同一基金两个日期的 Research Packet。

    请求体:
    {
        "fund_code": "000001",
        "left_snapshot": "2026-03-31",
        "right_snapshot": "2026-06-08"
    }
    或:
    {
        "fund_code": "000001",
        "left_packet_id": "pkt_abc",
        "right_packet_id": "pkt_def"
    }
    """
    from datetime import date as date_type

    started_at = perf_counter()
    fund_code = body.fund_code or ""
    warnings: list[str] = []

    left = None
    right = None
    if body.left_packet_id:
        left = db.scalar(
            select(ResearchPacketRecord).where(ResearchPacketRecord.packet_id == body.left_packet_id)
        )
    elif body.left_snapshot:
        left = db.scalar(
            select(ResearchPacketRecord).where(
                ResearchPacketRecord.fund_code == fund_code,
                ResearchPacketRecord.data_date <= date_type.fromisoformat(body.left_snapshot),
            ).order_by(ResearchPacketRecord.data_date.desc()).limit(1)
        )
    if body.right_packet_id:
        right = db.scalar(
            select(ResearchPacketRecord).where(ResearchPacketRecord.packet_id == body.right_packet_id)
        )
    elif body.right_snapshot:
        right = db.scalar(
            select(ResearchPacketRecord).where(
                ResearchPacketRecord.fund_code == fund_code,
                ResearchPacketRecord.data_date <= date_type.fromisoformat(body.right_snapshot),
            ).order_by(ResearchPacketRecord.data_date.desc()).limit(1)
        )

    if not left or not right:
        missing = []
        if not left:
            missing.append("left")
        if not right:
            missing.append("right")
        response = APIResponse(
            data=None,
            metadata={"tool": "diff_research_packets", "fund_code": fund_code, "platform_version": __version__},
            evidence=[],
            warnings=[f"缺少研究包: {', '.join(missing)}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(db, "diff_research_packets", body.model_dump(), response, started_at)

    # 对比两个 packet 的 JSON
    lp = left.packet_json if isinstance(left.packet_json, dict) else {}
    rp = right.packet_json if isinstance(right.packet_json, dict) else {}
    if not fund_code:
        fund_code = left.fund_code
    if left.fund_code != right.fund_code:
        response = APIResponse(
            data=None,
            metadata={"tool": "diff_research_packets", "fund_code": fund_code, "platform_version": __version__},
            evidence=[],
            warnings=["左右研究包不属于同一基金，不能进行同基金 diff"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(db, "diff_research_packets", body.model_dump(), response, started_at)

    diffs: dict[str, Any] = {}

    # 规模变化
    ls = (lp.get("fund_profile") or {}).get("latest_scale") if isinstance(lp.get("fund_profile"), dict) else None
    rs = (rp.get("fund_profile") or {}).get("latest_scale") if isinstance(rp.get("fund_profile"), dict) else None
    if ls and rs and ls != rs:
        diffs["scale"] = {"left": ls, "right": rs, "delta": round(float(rs) - float(ls), 2) if ls and rs else None}

    # 经理变化
    lm = (lp.get("manager_info") or {}).get("current_managers", []) if isinstance(lp.get("manager_info"), dict) else []
    rm = (rp.get("manager_info") or {}).get("current_managers", []) if isinstance(rp.get("manager_info"), dict) else []
    if lm != rm:
        diffs["manager"] = {"left": lm, "right": rm, "changed": True}

    # 净值指标变化
    lp_metrics = (lp.get("nav_metrics") or {}).get("metrics", {}) if isinstance(lp.get("nav_metrics"), dict) else {}
    rp_metrics = (rp.get("nav_metrics") or {}).get("metrics", {}) if isinstance(rp.get("nav_metrics"), dict) else {}
    metric_diffs = {}
    for key in set(lp_metrics) | set(rp_metrics):
        lv = lp_metrics.get(key)
        rv = rp_metrics.get(key)
        if (
            lv is not None and rv is not None
            and isinstance(lv, (int, float)) and isinstance(rv, (int, float))
            and abs(float(lv) - float(rv)) > 0.0001
        ):
                metric_diffs[key] = {"left": float(lv), "right": float(rv), "delta": round(float(rv) - float(lv), 4)}
    if metric_diffs:
        diffs["nav_metrics"] = metric_diffs

    # 风格暴露变化
    lp_exposure = (lp.get("exposure") or {}).get("exposure_values", {}) if isinstance(lp.get("exposure"), dict) else {}
    rp_exposure = (rp.get("exposure") or {}).get("exposure_values", {}) if isinstance(rp.get("exposure"), dict) else {}
    exposure_diffs = {}
    for key in set(lp_exposure) | set(rp_exposure):
        lv = lp_exposure.get(key)
        rv = rp_exposure.get(key)
        if (
            lv is not None and rv is not None
            and isinstance(lv, (int, float)) and isinstance(rv, (int, float))
            and abs(float(lv) - float(rv)) > 0.0001
        ):
            exposure_diffs[key] = {"left": float(lv), "right": float(rv), "delta": round(float(rv) - float(lv), 4)}
    if exposure_diffs:
        diffs["exposure"] = exposure_diffs

    # 持仓变化
    def _get_holdings(p: dict) -> list:
        dh = p.get("disclosed_holdings") if isinstance(p.get("disclosed_holdings"), dict) else {}
        return dh.get("holdings", [])
    lh = _get_holdings(lp)
    rh = _get_holdings(rp)
    if lh or rh:
        left_codes = {h.get("security_code"): h for h in lh}
        right_codes = {h.get("security_code"): h for h in rh}
        new_positions = [right_codes[c] for c in right_codes if c not in left_codes]
        exited_positions = [left_codes[c] for c in left_codes if c not in right_codes]
        weight_changes = []
        for c in set(left_codes) & set(right_codes):
            lw = left_codes[c].get("weight_pct")
            rw = right_codes[c].get("weight_pct")
            if lw is not None and rw is not None and abs(float(rw) - float(lw)) > 0.1:
                weight_changes.append({
                    "code": c, "name": left_codes[c].get("security_name"),
                    "from": round(float(lw), 2),
                    "to": round(float(rw), 2),
                })
        if new_positions or exited_positions or weight_changes:
            diffs["holdings"] = {
                "new_positions": new_positions[:10],
                "exited_positions": exited_positions[:10],
                "weight_changes": weight_changes[:10],
            }

    # 风险提示变化
    lr = lp.get("risk_alerts", []) if isinstance(lp.get("risk_alerts"), list) else []
    rr = rp.get("risk_alerts", []) if isinstance(rp.get("risk_alerts"), list) else []
    if lr != rr:
        diffs["risk_alerts"] = {"left": lr, "right": rr}

    # 证据与结论状态变化
    def _evidence_ids(p: dict) -> set[str]:
        evidence_items = p.get("evidence", [])
        if not isinstance(evidence_items, list):
            return set()
        return {
            str(item.get("evidence_id"))
            for item in evidence_items
            if isinstance(item, dict) and item.get("evidence_id")
        }

    le = _evidence_ids(lp)
    re = _evidence_ids(rp)
    if le != re:
        diffs["evidence"] = {
            "new": sorted(re - le),
            "removed": sorted(le - re),
            "unchanged_count": len(le & re),
        }

    lc = lp.get("conclusion_map", {}) if isinstance(lp.get("conclusion_map"), dict) else {}
    rc = rp.get("conclusion_map", {}) if isinstance(rp.get("conclusion_map"), dict) else {}
    conclusion_diffs = {
        key: {"left": lc.get(key), "right": rc.get(key)}
        for key in set(lc) | set(rc)
        if lc.get(key) != rc.get(key)
    }
    if conclusion_diffs:
        diffs["conclusion_status"] = conclusion_diffs

    # 汇总
    changed = len(diffs) > 0
    response = APIResponse(
        data={
            "fund_code": fund_code,
            "left_info": {"packet_id": left.packet_id, "data_date": str(left.data_date)},
            "right_info": {"packet_id": right.packet_id, "data_date": str(right.data_date)},
            "changed": changed,
            "diffs": diffs,
        },
        metadata={
            "tool": "diff_research_packets",
            "fund_code": fund_code,
            "platform_version": __version__,
            "implemented": True,
        },
        evidence=[
            EvidenceRecord(
                evidence_id=f"research_packet:{left.packet_id}",
                entity_id=f"fund:{left.fund_code}",
                evidence_type=EvidenceType.RAW_DATA,
                source="research_packet",
                source_level=DataSourceLevel.LOCAL,
                date_range=(left.data_date, left.data_date),
                data_summary="左侧 Research Packet 快照",
                confidence=ConfidenceLevel.MEDIUM,
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
            EvidenceRecord(
                evidence_id=f"research_packet:{right.packet_id}",
                entity_id=f"fund:{right.fund_code}",
                evidence_type=EvidenceType.RAW_DATA,
                source="research_packet",
                source_level=DataSourceLevel.LOCAL,
                date_range=(right.data_date, right.data_date),
                data_summary="右侧 Research Packet 快照",
                confidence=ConfidenceLevel.MEDIUM,
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
        ],
        warnings=warnings if changed else [*warnings, "两个研究包在各模块上均无显著差异"],
        conclusion_status=ConclusionStatus.OBSERVATION if changed else ConclusionStatus.COMPUTED,
    )
    return _log_tool_api_call(db, "diff_research_packets", body.model_dump(), response, started_at)


# ============================================================
# 5. build_research_packet — 生成研究包
# ============================================================


@router.post("/research/packet")
def build_research_packet(
    db: SessionDep,
    body: PacketRequestBody,
) -> APIResponse[dict]:
    """
    生成标准化研究包（JSON + Markdown）。

    一期包含：基础信息、经理、净值指标、公开持仓、风格暴露、
              静态归因、残差、风险提示、证据列表、数据质量摘要。
    研究包附带完整 metadata：数据日期、算法版本、数据源等级、置信度、免责声明。
    """
    started_at = perf_counter()
    fund_code = body.fund_code
    template = body.template
    fund = db.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    if fund is None:
        response = APIResponse(
            data=None,
            metadata={
                "tool": "build_research_packet",
                "fund_code": fund_code,
                "platform_version": __version__,
                "implemented": True,
            },
            evidence=[],
            warnings=["基金不存在或尚未更新到本地数据库"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        )
        return _log_tool_api_call(
            db,
            "build_research_packet",
            {"fund_code": fund_code, "template": template},
            response,
            started_at,
        )
    packet = build_single_fund_packet(db, fund_code=fund_code, template=template)
    record = persist_research_packet(db, packet)
    warnings = packet.warnings.copy()
    if packet.metadata.overall_confidence == ConfidenceLevel.NEEDS_REVIEW:
        warnings.append("研究包存在待复核模块，不能作为高置信度结论")

    response = APIResponse(
        data={
            "packet_id": record.packet_id,
            "packet": packet.model_dump(mode="json"),
            "markdown": record.markdown_text,
        },
        metadata={
            "tool": "build_research_packet",
            "fund_code": fund_code,
            "template": template,
            "platform_version": __version__,
            "implemented": True,
            "packet_id": record.packet_id,
            "data_snapshots": _latest_snapshot_summaries(
                db,
                [
                    "fund_main",
                    "fund_info",
                    "fund_managers",
                    "fund_scale",
                    "fund_fee_detail",
                    "fund_nav",
                    "fund_dividends",
                    "fund_holdings",
                    "fund_industry_allocation",
                    "fund_portfolio_change",
                    "holder_structure",
                    "stock_daily",
                    "index_daily",
                    "official_pdf_evidence",
                ],
            ),
        },
        evidence=packet.evidence,
        warnings=warnings,
        conclusion_status=(
            ConclusionStatus.NEEDS_REVIEW
            if packet.metadata.overall_confidence == ConfidenceLevel.NEEDS_REVIEW
            else ConclusionStatus.OBSERVATION
        ),
    )
    return _log_tool_api_call(
        db,
        "build_research_packet",
        {"fund_code": fund_code, "template": template},
        response,
        started_at,
    )
