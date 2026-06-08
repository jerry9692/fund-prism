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
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
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
    StaticAttributionResult,
    StockDaily,
    StyleExposureResult,
    ToolAPICallLog,
)
from fund_research.research.packet import build_single_fund_packet, persist_research_packet

router = APIRouter(prefix="/api/v1", tags=["Tool API v1"])

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
def root() -> dict:
    """API 根路由。"""
    return {
        "platform": "Fund Research Platform",
        "version": __version__,
        "docs": "/docs",
        "disclaimer": "本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。",
    }


@router.get("/health")
def health_check(db: SessionDep) -> dict:
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
) -> APIResponse[dict]:
    """
    获取净值指标：收益、回撤、波动、夏普、卡玛、索提诺、信息比率等。

    支持多区间：今年以来、近1/3/6月、近1/3/5年、成立以来、经理任职以来。
    每个指标附带计算口径和基准选择。
    """
    started_at = perf_counter()
    stmt = select(FundNAV).where(FundNAV.fund_code == fund_code)
    if start:
        stmt = stmt.where(FundNAV.trade_date >= start)
    if end:
        stmt = stmt.where(FundNAV.trade_date <= end)
    rows = db.scalars(stmt.order_by(FundNAV.trade_date)).all()

    nav_data = [
        {
            "trade_date": row.trade_date,
            "unit_nav": row.unit_nav,
            "accumulated_nav": row.accumulated_nav,
            "adjusted_nav": row.adjusted_nav,
            "daily_return": row.daily_return,
            "dividend": row.dividend,
            "split_ratio": row.split_ratio,
        }
        for row in rows
    ]
    result = calculate_nav_metrics(pd.DataFrame(nav_data))
    dividend_count = sum(1 for row in rows if row.dividend is not None)
    conclusion_status = (
        ConclusionStatus.COMPUTED if result.is_sufficient else ConclusionStatus.NEEDS_REVIEW
    )
    evidence = []
    if rows:
        evidence.append(
            EvidenceRecord(
                evidence_id=f"nav:{fund_code}:{result.start_date}:{result.end_date}",
                entity_id=f"fund:{fund_code}",
                evidence_type=EvidenceType.TIME_SERIES,
                source="fund_nav",
                source_level=DataSourceLevel.B,
                date_range=(result.start_date, result.end_date),
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=NAV_METRICS_ALGORITHM_NAME,
                    algorithm_version=NAV_METRICS_ALGORITHM_VERSION,
                    parameters={
                        "start": str(start) if start else None,
                        "end": str(end) if end else None,
                        "trading_days_per_year": 252,
                    },
                    confidence=(
                        ConfidenceLevel.MEDIUM
                        if result.is_sufficient
                        else ConfidenceLevel.NEEDS_REVIEW
                    ),
                    warnings=result.warnings,
                ),
                data_summary=(
                    f"净值记录 {len(rows)} 条，可用收益率 {result.observations} 条，"
                    f"分红记录 {dividend_count} 条"
                ),
                confidence=(
                    ConfidenceLevel.MEDIUM
                    if result.is_sufficient
                    else ConfidenceLevel.NEEDS_REVIEW
                ),
                conclusion_status=conclusion_status,
            )
        )

    response = APIResponse(
        data=result.to_data() if rows else None,
        metadata={
            "tool": "get_nav_metrics",
            "fund_code": fund_code,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
            "platform_version": __version__,
            "implemented": True,
            "algorithm_name": NAV_METRICS_ALGORITHM_NAME,
            "algorithm_version": NAV_METRICS_ALGORITHM_VERSION,
            "dividend_count": dividend_count,
            "data_snapshots": _latest_snapshot_summaries(db, ["fund_nav", "fund_dividends"]),
        },
        evidence=evidence,
        warnings=result.warnings if rows else ["基金净值数据不存在或尚未更新到本地数据库"],
        conclusion_status=conclusion_status,
    )
    return _log_tool_api_call(
        db,
        "get_nav_metrics",
        {
            "fund_code": fund_code,
            "start": str(start) if start else None,
            "end": str(end) if end else None,
        },
        response,
        started_at,
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
# 4. run_exposure_analysis — 风格/行业暴露 + 静态归因
# ============================================================


@router.post("/analysis/exposure")
def run_exposure_analysis(
    fund_code: str,
    db: SessionDep,
    window: WindowQuery = 60,
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
    nav_rows = db.scalars(
        select(FundNAV).where(FundNAV.fund_code == fund_code).order_by(FundNAV.trade_date)
    ).all()
    factor_rows = db.scalars(
        select(StockDaily)
        .where(StockDaily.stock_code.in_(DEFAULT_STYLE_FACTORS.values()))
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
    )
    metadata = {
        "tool": "run_exposure_analysis",
        "fund_code": fund_code,
        "window": window,
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
            {"fund_code": fund_code, "window": window},
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
            parameters={"window": window, "factor_symbols": result.factor_symbols},
            exposure_type="style",
            exposure_values=result.exposure_values,
        )
        db.add(existing)
    existing.parameters = {"window": window, "factor_symbols": result.factor_symbols}
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
        {"fund_code": fund_code, "window": window},
        response,
        started_at,
    )


# ============================================================
# 5. build_research_packet — 生成研究包
# ============================================================


@router.post("/research/packet")
def build_research_packet(
    fund_code: str,
    db: SessionDep,
    template: TemplateQuery = "single_fund_checkup",
) -> APIResponse[dict]:
    """
    生成标准化研究包（JSON + Markdown）。

    一期包含：基础信息、经理、净值指标、公开持仓、风格暴露、
              静态归因、残差、风险提示、证据列表、数据质量摘要。
    研究包附带完整 metadata：数据日期、算法版本、数据源等级、置信度、免责声明。
    """
    started_at = perf_counter()
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
