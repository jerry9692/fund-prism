"""Research Packet generation for Phase 1."""

from datetime import date, datetime
from uuid import uuid4

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.analysis.attribution import (
    ALGORITHM_NAME as ATTRIBUTION_ALGORITHM_NAME,
)
from fund_research.analysis.attribution import (
    ALGORITHM_VERSION as ATTRIBUTION_ALGORITHM_VERSION,
)
from fund_research.analysis.dynamic_attribution import (
    ALGORITHM_NAME as DYNAMIC_ATTRIBUTION_ALGORITHM_NAME,
)
from fund_research.analysis.dynamic_attribution import (
    ALGORITHM_VERSION as DYNAMIC_ATTRIBUTION_ALGORITHM_VERSION,
)
from fund_research.analysis.exposure import (
    ALGORITHM_NAME as EXPOSURE_ALGORITHM_NAME,
)
from fund_research.analysis.exposure import (
    ALGORITHM_VERSION as EXPOSURE_ALGORITHM_VERSION,
)
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
from fund_research.analysis.scoring import (
    ALGORITHM_NAME as SCORING_ALGORITHM_NAME,
)
from fund_research.analysis.scoring import (
    ALGORITHM_VERSION as SCORING_ALGORITHM_VERSION,
)
from fund_research.analysis.simulated_holding import (
    ALGORITHM_NAME as SIMULATED_HOLDING_ALGORITHM_NAME,
)
from fund_research.analysis.simulated_holding import (
    ALGORITHM_VERSION as SIMULATED_HOLDING_ALGORITHM_VERSION,
)
from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    EvidenceType,
)
from fund_research.core.schemas import (
    AlgorithmMetadata,
    EvidenceRecord,
    ResearchPacket,
    ResearchPacketMetadata,
)
from fund_research.db.models import (
    DynamicAttributionResult,
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    HolderStructure,
    ResearchPacketRecord,
    ScoringResult,
    SimulatedHoldingResult,
    StaticAttributionResult,
    StyleExposureResult,
)
from fund_research.db.models import (
    EvidenceRecord as DBEvidenceRecord,
)
from fund_research.research.credibility import evaluate_credibility

SUPPORTED_TEMPLATES = {
    "single_fund_checkup",
    "manager_profile",
    "style_drift",
    "holdings_deep_dive",
}


def _safe_source_level(value: str | None) -> DataSourceLevel:
    if value in {level.value for level in DataSourceLevel}:
        return DataSourceLevel(value)
    return DataSourceLevel.B


def _confidence_for_status(status: ConclusionStatus) -> ConfidenceLevel:
    if status == ConclusionStatus.NEEDS_REVIEW:
        return ConfidenceLevel.NEEDS_REVIEW
    if status == ConclusionStatus.FACT:
        return ConfidenceLevel.HIGH
    if status == ConclusionStatus.COMPUTED:
        return ConfidenceLevel.MEDIUM
    if status == ConclusionStatus.ESTIMATED:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.LOW


def _warning_items(value: dict | list | str | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        items = value.get("items", [])
        return [str(item) for item in items] if isinstance(items, list) else [str(items)]
    return [str(value)]


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


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


def _fund_profile(db: Session, fund_code: str) -> tuple[dict | None, list[str]]:
    fund = db.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    if fund is None:
        return None, ["基金不存在或尚未更新到本地数据库"]

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

    return (
        {
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
        warnings,
    )


def _manager_info(
    fund_profile: dict | None,
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    if fund_profile is None:
        return None, ConclusionStatus.NEEDS_REVIEW, []

    managers = fund_profile.get("managers") or []
    if not managers:
        return None, ConclusionStatus.NEEDS_REVIEW, ["基金经理模块缺少可用任职记录"]

    current_managers = [manager for manager in managers if manager.get("is_current")]
    former_managers = [manager for manager in managers if not manager.get("is_current")]
    current_tenure_days = [
        manager.get("tenure_days")
        for manager in current_managers
        if manager.get("tenure_days") is not None
    ]
    warnings = []
    if current_managers and all(
        manager.get("tenure_days") is None for manager in current_managers
    ):
        warnings.append("基金经理任期天数缺失，短任期风险判断需复核")

    return (
        {
            "current_managers": current_managers,
            "former_managers": former_managers,
            "manager_count": len(managers),
            "current_manager_count": len(current_managers),
            "has_current_manager": bool(current_managers),
            "current_tenure_days_min": min(current_tenure_days) if current_tenure_days else None,
            "current_tenure_days_max": max(current_tenure_days) if current_tenure_days else None,
        },
        ConclusionStatus.FACT,
        warnings,
    )


def _nav_metrics(db: Session, fund_code: str) -> tuple[dict | None, ConclusionStatus, list[str]]:
    rows = db.scalars(
        select(FundNAV).where(FundNAV.fund_code == fund_code).order_by(FundNAV.trade_date)
    ).all()
    if not rows:
        return None, ConclusionStatus.NEEDS_REVIEW, ["基金净值数据不存在或尚未更新"]

    result = calculate_nav_metrics(
        pd.DataFrame(
            [
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
        )
    )
    status = ConclusionStatus.COMPUTED if result.is_sufficient else ConclusionStatus.NEEDS_REVIEW
    data = result.to_data()
    data["dividend_count"] = sum(1 for row in rows if row.dividend is not None)
    return data, status, result.warnings


def _latest_holdings(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str], date | None]:
    report_date = db.scalar(
        select(FundDisclosedHoldings.report_date)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(1)
    )
    if report_date is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["基金公开披露持仓不存在或尚未更新"], None

    rows = db.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date == report_date)
        .order_by(FundDisclosedHoldings.rank_in_holdings, FundDisclosedHoldings.security_code)
    ).all()
    previous_report_date = db.scalar(
        select(FundDisclosedHoldings.report_date)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date < report_date)
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(1)
    )
    previous_rows = []
    if previous_report_date is not None:
        previous_rows = db.scalars(
            select(FundDisclosedHoldings)
            .where(FundDisclosedHoldings.fund_code == fund_code)
            .where(FundDisclosedHoldings.report_date == previous_report_date)
            .order_by(
                FundDisclosedHoldings.rank_in_holdings,
                FundDisclosedHoldings.security_code,
            )
        ).all()
    result = analyze_disclosed_holdings(
        pd.DataFrame(
            [
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
        ),
        pd.DataFrame(
            [
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
        ),
    )
    status = ConclusionStatus.OBSERVATION if result.is_limited else ConclusionStatus.COMPUTED
    return result.to_data(), status, result.warnings, report_date


def _latest_holder_structure(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    holder = db.scalar(
        select(HolderStructure)
        .where(HolderStructure.fund_code == fund_code)
        .order_by(HolderStructure.report_date.desc())
        .limit(1)
    )
    if holder is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["持有人结构数据不存在或尚未更新"]

    holder_parts = {
        "individual": holder.individual_pct,
        "institutional": holder.institutional_pct,
        "employee": holder.employee_pct,
    }
    available_parts = {key: value for key, value in holder_parts.items() if value is not None}
    dominant_holder_type = None
    dominant_holder_pct = None
    if available_parts:
        dominant_holder_type, dominant_holder_pct = max(
            available_parts.items(),
            key=lambda item: item[1],
        )

    return (
        {
            "report_date": str(holder.report_date),
            "individual_pct": holder.individual_pct,
            "institutional_pct": holder.institutional_pct,
            "employee_pct": holder.employee_pct,
            "total_holders": holder.total_holders,
            "avg_holding": holder.avg_holding,
            "dominant_holder_type": dominant_holder_type,
            "dominant_holder_pct": dominant_holder_pct,
            "data_source_level": holder.data_source_level,
        },
        ConclusionStatus.FACT,
        [],
    )


def _latest_exposure(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    exposure = db.scalar(
        select(StyleExposureResult)
        .where(StyleExposureResult.fund_code == fund_code)
        .order_by(StyleExposureResult.calc_date.desc(), StyleExposureResult.created_at.desc())
        .limit(1)
    )
    if exposure is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["风格暴露模块尚未运行"]

    return (
        {
            "calc_date": str(exposure.calc_date),
            "exposure_type": exposure.exposure_type,
            "exposure_values": exposure.exposure_values,
            "residual": exposure.residual,
            "r_squared": exposure.r_squared,
            "confidence": exposure.confidence,
            "input_coverage": exposure.input_coverage,
            "algorithm_name": exposure.algorithm_name,
            "algorithm_version": exposure.algorithm_version,
            "parameters": exposure.parameters,
            "warnings": exposure.warnings,
        },
        ConclusionStatus(exposure.conclusion_status),
        [],
    )


def _latest_attribution(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    attribution = db.scalar(
        select(StaticAttributionResult)
        .where(StaticAttributionResult.fund_code == fund_code)
        .order_by(
            StaticAttributionResult.report_date.desc(),
            StaticAttributionResult.created_at.desc(),
        )
        .limit(1)
    )
    if attribution is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["静态归因模块尚未运行"]

    return (
        {
            "report_date": str(attribution.report_date),
            "benchmark": attribution.benchmark,
            "total_return": attribution.total_return,
            "benchmark_return": attribution.benchmark_return,
            "allocation_effect": attribution.allocation_effect,
            "selection_effect": attribution.selection_effect,
            "interaction_effect": attribution.interaction_effect,
            "sector_rotation_effect": attribution.sector_rotation_effect,
            "residual": attribution.residual,
            "residual_pct": attribution.residual_pct,
            "detail": attribution.detail,
            "confidence": attribution.confidence,
            "algorithm_name": attribution.algorithm_name,
            "algorithm_version": attribution.algorithm_version,
            "parameters": attribution.parameters,
            "warnings": attribution.warnings,
        },
        ConclusionStatus(attribution.conclusion_status),
        [],
    )


def _latest_scoring(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    """获取最新综合评分结果。"""
    scoring = db.scalar(
        select(ScoringResult)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc(), ScoringResult.created_at.desc())
        .limit(1)
    )
    if scoring is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["综合评分模块尚未运行"]

    # scoring 的 conclusion_status 默认是 computed，但如果 contains_estimated=True，应降为 estimated
    base_status = ConclusionStatus(scoring.conclusion_status)
    if scoring.contains_estimated:
        base_status = ConclusionStatus.ESTIMATED

    return (
        {
            "calc_date": str(scoring.calc_date),
            "score_version": scoring.score_version,
            "algorithm_version": scoring.algorithm_version,
            "weight_config": scoring.weight_config,
            "total_score": scoring.total_score,
            "sub_scores": scoring.sub_scores,
            "percentile_rank": scoring.percentile_rank,
            "deduction_reasons": scoring.deduction_reasons,
            "contains_estimated": scoring.contains_estimated,
            "confidence": scoring.confidence,
            "algorithm_name": SCORING_ALGORITHM_NAME,
            "warnings": scoring.warnings,
        },
        base_status,
        [],
    )


def _latest_simulated_holding(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    """获取最新模拟持仓结果（estimated 模块）。"""
    sim = db.scalar(
        select(SimulatedHoldingResult)
        .where(SimulatedHoldingResult.fund_code == fund_code)
        .order_by(SimulatedHoldingResult.calc_date.desc(), SimulatedHoldingResult.created_at.desc())
        .limit(1)
    )
    if sim is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["模拟持仓模块尚未运行"]

    return (
        {
            "calc_date": str(sim.calc_date),
            "algorithm_name": sim.algorithm_name,
            "algorithm_version": sim.algorithm_version,
            "parameters": sim.parameters,
            "holdings_detail": sim.holdings_detail,
            "tracking_error": sim.tracking_error,
            "daily_rmse": sim.daily_rmse,
            "industry_correlation": sim.industry_correlation,
            "top10_recall": sim.top10_recall,
            "stock_weight_pct": sim.stock_weight_pct,
            "bond_weight_pct": sim.bond_weight_pct,
            "cash_weight_pct": sim.cash_weight_pct,
            "confidence": sim.confidence,
            "is_backtest": sim.is_backtest,
            "input_coverage": sim.input_coverage,
            "warnings": sim.warnings,
        },
        ConclusionStatus.ESTIMATED,
        ["模拟持仓为模型估算结果，非真实披露持仓"],
    )


def _latest_dynamic_attribution(
    db: Session, fund_code: str
) -> tuple[dict | None, ConclusionStatus, list[str]]:
    """获取最新动态归因结果（estimated 模块）。"""
    dyn = db.scalar(
        select(DynamicAttributionResult)
        .where(DynamicAttributionResult.fund_code == fund_code)
        .order_by(DynamicAttributionResult.created_at.desc())
        .limit(1)
    )
    if dyn is None:
        return None, ConclusionStatus.NEEDS_REVIEW, ["动态归因模块尚未运行"]

    return (
        {
            "period_start": str(dyn.period_start),
            "period_end": str(dyn.period_end),
            "algorithm_name": dyn.algorithm_name,
            "algorithm_version": dyn.algorithm_version,
            "parameters": dyn.parameters,
            "total_return": dyn.total_return,
            "beta_return": dyn.beta_return,
            "allocation_return": dyn.allocation_return,
            "sector_rotation_return": dyn.sector_rotation_return,
            "stock_selection_return": dyn.stock_selection_return,
            "convertible_bond_return": dyn.convertible_bond_return,
            "ipo_return": dyn.ipo_return,
            "residual": dyn.residual,
            "residual_pct": dyn.residual_pct,
            "detail": dyn.detail,
            "confidence": dyn.confidence,
            "warnings": dyn.warnings,
        },
        ConclusionStatus.ESTIMATED,
        ["动态归因为模型估算结果，基于模拟持仓分解收益"],
    )


def _data_date(db: Session, fund_code: str) -> date:
    nav_date = db.scalar(
        select(FundNAV.trade_date)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date.desc())
        .limit(1)
    )
    holdings_date = db.scalar(
        select(FundDisclosedHoldings.report_date)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(1)
    )
    holder_date = db.scalar(
        select(HolderStructure.report_date)
        .where(HolderStructure.fund_code == fund_code)
        .order_by(HolderStructure.report_date.desc())
        .limit(1)
    )
    exposure_date = db.scalar(
        select(StyleExposureResult.calc_date)
        .where(StyleExposureResult.fund_code == fund_code)
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(1)
    )
    attribution_date = db.scalar(
        select(StaticAttributionResult.report_date)
        .where(StaticAttributionResult.fund_code == fund_code)
        .order_by(StaticAttributionResult.report_date.desc())
        .limit(1)
    )
    scoring_date = db.scalar(
        select(ScoringResult.calc_date)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc())
        .limit(1)
    )
    sim_date = db.scalar(
        select(SimulatedHoldingResult.calc_date)
        .where(SimulatedHoldingResult.fund_code == fund_code)
        .order_by(SimulatedHoldingResult.calc_date.desc())
        .limit(1)
    )
    dyn_date = db.scalar(
        select(DynamicAttributionResult.period_end)
        .where(DynamicAttributionResult.fund_code == fund_code)
        .order_by(DynamicAttributionResult.period_end.desc())
        .limit(1)
    )
    dates = [
        item
        for item in (
            nav_date, holdings_date, holder_date, exposure_date, attribution_date,
            scoring_date, sim_date, dyn_date,
        )
        if item is not None
    ]
    return max(dates) if dates else date.today()


def _overall_confidence(statuses: dict[str, ConclusionStatus]) -> ConfidenceLevel:
    # Per AGENTS.md principle #2 (estimated pollution isolation):
    # Phase 2 estimated/optional modules (scoring, simulated_holding,
    # dynamic_attribution) do NOT gate core conclusion credibility.
    # Only Phase 1 core modules determine overall confidence.
    core_modules = {
        "fund_profile", "manager_info", "nav_metrics", "disclosed_holdings",
        "holder_structure", "exposure", "attribution",
    }
    core_statuses = {k: v for k, v in statuses.items() if k in core_modules}
    if not core_statuses or any(status == ConclusionStatus.NEEDS_REVIEW for status in core_statuses.values()):
        return ConfidenceLevel.NEEDS_REVIEW
    if any(status == ConclusionStatus.OBSERVATION for status in core_statuses.values()):
        return ConfidenceLevel.LOW
    return ConfidenceLevel.MEDIUM


def _build_evidence(
    fund_code: str,
    fund_profile: dict | None,
    manager_info: dict | None,
    manager_status: ConclusionStatus,
    nav_metrics: dict | None,
    nav_status: ConclusionStatus,
    holdings: dict | None,
    holdings_status: ConclusionStatus,
    holder_structure: dict | None,
    holder_status: ConclusionStatus,
    exposure: dict | None,
    exposure_status: ConclusionStatus,
    attribution: dict | None,
    attribution_status: ConclusionStatus,
    scoring: dict | None = None,
    scoring_status: ConclusionStatus | None = None,
    simulated_holding: dict | None = None,
    sim_status: ConclusionStatus | None = None,
    dynamic_attribution: dict | None = None,
    dyn_status: ConclusionStatus | None = None,
) -> list[EvidenceRecord]:
    evidence: list[EvidenceRecord] = []
    entity_id = f"fund:{fund_code}"

    if fund_profile is not None:
        source_level = _safe_source_level(fund_profile.get("data_source_level"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"profile:{fund_code}",
                entity_id=entity_id,
                evidence_type=EvidenceType.RAW_DATA,
                source="fund_main",
                source_level=source_level,
                date_range=None,
                data_summary="基金主数据来自本地 fund_main 表",
                confidence=_confidence_for_status(ConclusionStatus.FACT),
                conclusion_status=ConclusionStatus.FACT,
            )
        )

    if manager_info is not None:
        start_dates = [
            _parse_iso_date(manager.get("start_date"))
            for manager in [
                *manager_info.get("current_managers", []),
                *manager_info.get("former_managers", []),
            ]
            if manager.get("start_date")
        ]
        evidence.append(
            EvidenceRecord(
                evidence_id=f"manager_info:{fund_code}",
                entity_id=entity_id,
                evidence_type=EvidenceType.RAW_DATA,
                source="fund_manager_tenure",
                source_level=DataSourceLevel.B,
                date_range=(min(start_dates), max(start_dates)) if start_dates else None,
                data_summary=(
                    f"基金经理任职记录 {manager_info.get('manager_count')} 条，"
                    f"现任 {manager_info.get('current_manager_count')} 位"
                ),
                confidence=_confidence_for_status(manager_status),
                conclusion_status=manager_status,
            )
        )

    if nav_metrics is not None:
        start_date = _parse_iso_date(nav_metrics.get("start_date"))
        end_date = _parse_iso_date(nav_metrics.get("end_date"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"nav_metrics:{fund_code}:{start_date}:{end_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="fund_nav",
                source_level=DataSourceLevel.B,
                date_range=(start_date, end_date) if start_date and end_date else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=NAV_METRICS_ALGORITHM_NAME,
                    algorithm_version=NAV_METRICS_ALGORITHM_VERSION,
                    parameters={"trading_days_per_year": 252},
                    confidence=_confidence_for_status(nav_status),
                ),
                data_summary=(
                    f"净值指标样本 {nav_metrics.get('observations')} 条，"
                    f"分红记录 {nav_metrics.get('dividend_count', 0)} 条"
                ),
                confidence=_confidence_for_status(nav_status),
                conclusion_status=nav_status,
            )
        )

    if holdings is not None:
        report_date = _parse_iso_date(holdings.get("report_date"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"holdings:{fund_code}:{report_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.RAW_DATA,
                source="fund_disclosed_holdings",
                source_level=DataSourceLevel.B,
                date_range=(report_date, report_date) if report_date else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=HOLDINGS_ALGORITHM_NAME,
                    algorithm_version=HOLDINGS_ALGORITHM_VERSION,
                    parameters={"report_date": str(report_date) if report_date else None},
                    confidence=_confidence_for_status(holdings_status),
                ),
                data_summary=(
                    f"披露持仓 {len(holdings.get('holdings', []))} 条，"
                    f"披露粒度 {holdings.get('disclosure_granularity')}"
                ),
                confidence=_confidence_for_status(holdings_status),
                conclusion_status=holdings_status,
            )
        )

    if holder_structure is not None:
        report_date = _parse_iso_date(holder_structure.get("report_date"))
        source_level = _safe_source_level(holder_structure.get("data_source_level"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"holder_structure:{fund_code}:{report_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.RAW_DATA,
                source="holder_structure",
                source_level=source_level,
                date_range=(report_date, report_date) if report_date else None,
                data_summary=(
                    f"持有人户数 {holder_structure.get('total_holders')}，"
                    f"机构占比 {holder_structure.get('institutional_pct')}%"
                ),
                confidence=_confidence_for_status(holder_status),
                conclusion_status=holder_status,
            )
        )

    if exposure is not None:
        calc_date = _parse_iso_date(exposure.get("calc_date"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"exposure:{fund_code}:{calc_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="style_exposure_result",
                source_level=DataSourceLevel.B,
                date_range=(calc_date, calc_date) if calc_date else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=exposure.get("algorithm_name") or EXPOSURE_ALGORITHM_NAME,
                    algorithm_version=(
                        exposure.get("algorithm_version") or EXPOSURE_ALGORITHM_VERSION
                    ),
                    parameters=exposure.get("parameters") or {},
                    confidence=_confidence_for_status(exposure_status),
                    warnings=_warning_items(exposure.get("warnings")),
                ),
                data_summary=f"风格暴露 R²={exposure.get('r_squared')}",
                confidence=_confidence_for_status(exposure_status),
                conclusion_status=exposure_status,
            )
        )

    if attribution is not None:
        report_date = _parse_iso_date(attribution.get("report_date"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"attribution:{fund_code}:{report_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="static_attribution_result",
                source_level=DataSourceLevel.B,
                date_range=(report_date, report_date) if report_date else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=attribution.get("algorithm_name") or ATTRIBUTION_ALGORITHM_NAME,
                    algorithm_version=(
                        attribution.get("algorithm_version") or ATTRIBUTION_ALGORITHM_VERSION
                    ),
                    parameters=attribution.get("parameters") or {},
                    confidence=_confidence_for_status(attribution_status),
                    warnings=_warning_items(attribution.get("warnings")),
                ),
                data_summary=(
                    f"静态归因残差 {attribution.get('residual')}，"
                    f"残差占比 {attribution.get('residual_pct')}"
                ),
                confidence=_confidence_for_status(attribution_status),
                conclusion_status=attribution_status,
            )
        )

    # Phase 2: scoring evidence
    if scoring is not None and scoring_status is not None:
        calc_date = _parse_iso_date(scoring.get("calc_date"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"scoring:{fund_code}:{calc_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="scoring_result",
                source_level=DataSourceLevel.B,
                date_range=(calc_date, calc_date) if calc_date else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=scoring.get("algorithm_name") or SCORING_ALGORITHM_NAME,
                    algorithm_version=scoring.get("algorithm_version") or SCORING_ALGORITHM_VERSION,
                    parameters=scoring.get("weight_config") or {},
                    confidence=_confidence_for_status(scoring_status),
                    warnings=_warning_items(scoring.get("warnings")),
                ),
                data_summary=(
                    f"综合评分 {scoring.get('total_score')}，"
                    f"百分位 {scoring.get('percentile_rank')}，"
                    f"含estimated维度: {scoring.get('contains_estimated')}"
                ),
                confidence=_confidence_for_status(scoring_status),
                conclusion_status=scoring_status,
            )
        )

    # Phase 2: simulated holding evidence (estimated)
    if simulated_holding is not None and sim_status is not None:
        calc_date = _parse_iso_date(simulated_holding.get("calc_date"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"simulated_holding:{fund_code}:{calc_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="simulated_holding_result",
                source_level=DataSourceLevel.B,
                date_range=(calc_date, calc_date) if calc_date else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=simulated_holding.get("algorithm_name") or SIMULATED_HOLDING_ALGORITHM_NAME,
                    algorithm_version=(
                        simulated_holding.get("algorithm_version") or SIMULATED_HOLDING_ALGORITHM_VERSION
                    ),
                    parameters=simulated_holding.get("parameters") or {},
                    confidence=_confidence_for_status(sim_status),
                    warnings=_warning_items(simulated_holding.get("warnings")),
                ),
                data_summary=(
                    f"模拟持仓 {len(simulated_holding.get('holdings_detail') or [])} 只标的，"
                    f"tracking_error={simulated_holding.get('tracking_error')}，"
                    f"top10_recall={simulated_holding.get('top10_recall')}"
                ),
                confidence=_confidence_for_status(sim_status),
                conclusion_status=sim_status,
            )
        )

    # Phase 2: dynamic attribution evidence (estimated)
    if dynamic_attribution is not None and dyn_status is not None:
        period_start = _parse_iso_date(dynamic_attribution.get("period_start"))
        period_end = _parse_iso_date(dynamic_attribution.get("period_end"))
        evidence.append(
            EvidenceRecord(
                evidence_id=f"dynamic_attribution:{fund_code}:{period_start}:{period_end}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="dynamic_attribution_result",
                source_level=DataSourceLevel.B,
                date_range=(period_start, period_end) if period_start and period_end else None,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=dynamic_attribution.get("algorithm_name") or DYNAMIC_ATTRIBUTION_ALGORITHM_NAME,
                    algorithm_version=(
                        dynamic_attribution.get("algorithm_version") or DYNAMIC_ATTRIBUTION_ALGORITHM_VERSION
                    ),
                    parameters=dynamic_attribution.get("parameters") or {},
                    confidence=_confidence_for_status(dyn_status),
                    warnings=_warning_items(dynamic_attribution.get("warnings")),
                ),
                data_summary=(
                    f"动态归因 total_return={dynamic_attribution.get('total_return')}，"
                    f"residual={dynamic_attribution.get('residual')}，"
                    f"residual_pct={dynamic_attribution.get('residual_pct')}"
                ),
                confidence=_confidence_for_status(dyn_status),
                conclusion_status=dyn_status,
            )
        )

    return evidence


def _build_residuals(
    exposure: dict | None,
    attribution: dict | None,
    dynamic_attribution: dict | None = None,
) -> dict | None:
    residuals: dict[str, float | None] = {}
    if exposure is not None:
        residuals["style_exposure_residual"] = exposure.get("residual")
        residuals["style_exposure_r_squared"] = exposure.get("r_squared")
    if attribution is not None:
        residuals["static_attribution_residual"] = attribution.get("residual")
        residuals["static_attribution_residual_pct"] = attribution.get("residual_pct")
    if dynamic_attribution is not None:
        residuals["dynamic_attribution_residual"] = dynamic_attribution.get("residual")
        residuals["dynamic_attribution_residual_pct"] = dynamic_attribution.get("residual_pct")
    return residuals or None


def _build_risk_alerts(
    nav_metrics: dict | None,
    manager_info: dict | None,
    holdings: dict | None,
    holder_structure: dict | None,
    exposure: dict | None,
    attribution: dict | None,
    scoring: dict | None = None,
    simulated_holding: dict | None = None,
    dynamic_attribution: dict | None = None,
) -> list[dict]:
    alerts: list[dict] = []

    metrics = nav_metrics.get("metrics", {}) if nav_metrics else {}
    max_drawdown = metrics.get("max_drawdown")
    if max_drawdown is not None and max_drawdown <= -0.2:
        alerts.append(
            {
                "type": "drawdown",
                "severity": "high" if max_drawdown <= -0.3 else "medium",
                "message": "历史最大回撤较大，需结合持有周期和风险承受能力复核",
                "value": max_drawdown,
                "conclusion_status": ConclusionStatus.COMPUTED.value,
            }
        )
    volatility = metrics.get("annualized_volatility")
    if volatility is not None and volatility >= 0.3:
        alerts.append(
            {
                "type": "volatility",
                "severity": "medium",
                "message": "年化波动率偏高",
                "value": volatility,
                "conclusion_status": ConclusionStatus.COMPUTED.value,
            }
        )

    if manager_info is not None:
        if not manager_info.get("has_current_manager"):
            alerts.append(
                {
                    "type": "no_current_manager",
                    "severity": "review",
                    "message": "基金经理任职记录中缺少现任经理，需复核数据完整性",
                    "value": manager_info.get("manager_count"),
                    "conclusion_status": ConclusionStatus.NEEDS_REVIEW.value,
                }
            )
        min_tenure_days = manager_info.get("current_tenure_days_min")
        if min_tenure_days is not None and min_tenure_days < 180:
            alerts.append(
                {
                    "type": "manager_short_tenure",
                    "severity": "info",
                    "message": "现任基金经理任职时间较短，历史业绩归因需谨慎",
                    "value": min_tenure_days,
                    "conclusion_status": ConclusionStatus.OBSERVATION.value,
                }
            )

    if holdings is not None:
        if holdings.get("disclosure_granularity") == "top10_quarterly":
            alerts.append(
                {
                    "type": "limited_disclosure",
                    "severity": "info",
                    "message": "季报通常仅披露前十大重仓，持仓分析不能视为完整组合",
                    "value": holdings.get("report_date"),
                    "conclusion_status": ConclusionStatus.OBSERVATION.value,
                }
            )
        concentration = holdings.get("concentration_top10_pct")
        if concentration is not None and concentration >= 60:
            alerts.append(
                {
                    "type": "concentration",
                    "severity": "medium",
                    "message": "前十大持仓集中度偏高",
                    "value": concentration,
                    "conclusion_status": ConclusionStatus.OBSERVATION.value,
                }
            )

    if holder_structure is not None:
        institutional_pct = holder_structure.get("institutional_pct")
        if institutional_pct is not None and institutional_pct >= 70:
            alerts.append(
                {
                    "type": "institutional_holder_dominance",
                    "severity": "medium",
                    "message": "机构持有人占比较高，需关注大额申赎对规模和流动性的影响",
                    "value": institutional_pct,
                    "conclusion_status": ConclusionStatus.OBSERVATION.value,
                }
            )
        total_holders = holder_structure.get("total_holders")
        if total_holders is not None and total_holders < 1000:
            alerts.append(
                {
                    "type": "low_holder_count",
                    "severity": "info",
                    "message": "持有人户数较少，需结合规模和机构占比复核集中度",
                    "value": total_holders,
                    "conclusion_status": ConclusionStatus.OBSERVATION.value,
                }
            )

    if exposure is not None:
        r_squared = exposure.get("r_squared")
        if r_squared is not None and r_squared < 0.2:
            alerts.append(
                {
                    "type": "low_exposure_fit",
                    "severity": "review",
                    "message": "风格回归解释度偏低，暴露结论需复核",
                    "value": r_squared,
                    "conclusion_status": ConclusionStatus.NEEDS_REVIEW.value,
                }
            )

    if attribution is not None:
        residual_pct = attribution.get("residual_pct")
        if residual_pct is not None and abs(residual_pct) >= 0.5:
            alerts.append(
                {
                    "type": "high_attribution_residual",
                    "severity": "review",
                    "message": "静态归因未解释残差占比较高，不能据此得出确定性结论",
                    "value": residual_pct,
                    "conclusion_status": ConclusionStatus.NEEDS_REVIEW.value,
                }
            )

    # Phase 2: scoring risk signals
    if scoring is not None:
        total_score = scoring.get("total_score")
        if total_score is not None and total_score < 40:
            alerts.append(
                {
                    "type": "low_composite_score",
                    "severity": "medium",
                    "message": "综合评分偏低，需结合各维度子分复核",
                    "value": total_score,
                    "conclusion_status": (
                        ConclusionStatus.ESTIMATED.value
                        if scoring.get("contains_estimated")
                        else ConclusionStatus.COMPUTED.value
                    ),
                }
            )
        sub_scores = scoring.get("sub_scores") or {}
        for dim_name, dim_score in sub_scores.items():
            if isinstance(dim_score, (int, float)) and dim_score < 30:
                alerts.append(
                    {
                        "type": f"low_dimension_score:{dim_name}",
                        "severity": "info",
                        "message": f"评分维度 {dim_name} 得分偏低({dim_score})，需关注该维度风险",
                        "value": dim_score,
                        "conclusion_status": (
                            ConclusionStatus.ESTIMATED.value
                            if scoring.get("contains_estimated")
                            else ConclusionStatus.COMPUTED.value
                        ),
                    }
                )
        deduction_reasons = scoring.get("deduction_reasons") or []
        if deduction_reasons:
            alerts.append(
                {
                    "type": "scoring_deductions",
                    "severity": "info",
                    "message": (
                        f"评分扣分项 {len(deduction_reasons)} 条: "
                        f"{'; '.join(str(r) for r in deduction_reasons[:3])}"
                    ),
                    "value": len(deduction_reasons),
                    "conclusion_status": (
                        ConclusionStatus.ESTIMATED.value
                        if scoring.get("contains_estimated")
                        else ConclusionStatus.COMPUTED.value
                    ),
                }
            )

    # Phase 2: simulated holding quality alerts
    if simulated_holding is not None:
        tracking_error = simulated_holding.get("tracking_error")
        if tracking_error is not None and tracking_error > 0.1:
            alerts.append(
                {
                    "type": "high_sim_tracking_error",
                    "severity": "review",
                    "message": "模拟持仓跟踪误差较大，估算持仓可靠性较低",
                    "value": tracking_error,
                    "conclusion_status": ConclusionStatus.ESTIMATED.value,
                }
            )
        input_coverage = simulated_holding.get("input_coverage")
        if input_coverage is not None and input_coverage < 0.5:
            alerts.append(
                {
                    "type": "low_sim_input_coverage",
                    "severity": "review",
                    "message": "模拟持仓输入数据覆盖率不足，估算结果需谨慎使用",
                    "value": input_coverage,
                    "conclusion_status": ConclusionStatus.ESTIMATED.value,
                }
            )

    # Phase 2: dynamic attribution residual alerts
    if dynamic_attribution is not None:
        dyn_residual_pct = dynamic_attribution.get("residual_pct")
        if dyn_residual_pct is not None and abs(dyn_residual_pct) >= 0.5:
            alerts.append(
                {
                    "type": "high_dynamic_attribution_residual",
                    "severity": "review",
                    "message": "动态归因未解释残差占比较高，交易能力判断需复核",
                    "value": dyn_residual_pct,
                    "conclusion_status": ConclusionStatus.ESTIMATED.value,
                }
            )

    return alerts


def build_single_fund_packet(
    db: Session,
    fund_code: str,
    template: str = "single_fund_checkup",
) -> ResearchPacket:
    """Build a single-fund Research Packet from local data."""
    if template not in SUPPORTED_TEMPLATES:
        template = "single_fund_checkup"

    fund_profile, profile_warnings = _fund_profile(db, fund_code)
    manager_info, manager_status, manager_warnings = _manager_info(fund_profile)
    nav_metrics, nav_status, nav_warnings = _nav_metrics(db, fund_code)
    holdings, holdings_status, holdings_warnings, _ = _latest_holdings(db, fund_code)
    holder_structure, holder_status, holder_warnings = _latest_holder_structure(db, fund_code)
    exposure, exposure_status, exposure_warnings = _latest_exposure(db, fund_code)
    attribution, attribution_status, attribution_warnings = _latest_attribution(db, fund_code)

    # Phase 2 results (estimated modules)
    scoring, scoring_status, scoring_warnings = _latest_scoring(db, fund_code)
    simulated_holding, sim_status, sim_warnings = _latest_simulated_holding(db, fund_code)
    dynamic_attribution, dyn_status, dyn_warnings = _latest_dynamic_attribution(db, fund_code)

    conclusion_map = {
        "fund_profile": ConclusionStatus.FACT
        if fund_profile is not None
        else ConclusionStatus.NEEDS_REVIEW,
        "manager_info": manager_status,
        "nav_metrics": nav_status,
        "disclosed_holdings": holdings_status,
        "holder_structure": holder_status,
        "exposure": exposure_status,
        "attribution": attribution_status,
        "scoring": scoring_status,
        "simulated_holding": sim_status,
        "dynamic_attribution": dyn_status,
    }

    # ---- 五道可信度门禁（需求书 §5.5） ----
    fund_type = fund_profile.get("fund_type") if fund_profile else None
    all_modules = {
        "fund_profile": fund_profile,
        "manager_info": manager_info,
        "nav_metrics": nav_metrics,
        "disclosed_holdings": holdings,
        "holder_structure": holder_structure,
        "exposure": exposure,
        "attribution": attribution,
        "scoring": scoring,
        "simulated_holding": simulated_holding,
        "dynamic_attribution": dynamic_attribution,
    }
    # 各模块数据源等级
    module_source_levels: dict[str, DataSourceLevel | None] = {
        "fund_profile": _safe_source_level(fund_profile.get("data_source_level")) if fund_profile else None,
        "manager_info": DataSourceLevel.B,
        "nav_metrics": DataSourceLevel.B,
        "disclosed_holdings": DataSourceLevel.B,
        "holder_structure": DataSourceLevel.B,
        "exposure": DataSourceLevel.B,
        "attribution": DataSourceLevel.B,
    }
    # 覆盖率元数据
    module_meta: dict[str, dict] = {}
    if nav_metrics and nav_metrics.get("start_date") and nav_metrics.get("end_date"):
        module_meta["nav_metrics"] = {"coverage_rate": 0.9}  # NAV数据来自B级源，视为高覆盖

    # 先构建证据（门禁5需要证据计数）
    evidence = _build_evidence(
        fund_code,
        fund_profile,
        manager_info,
        manager_status,
        nav_metrics,
        nav_status,
        holdings,
        holdings_status,
        holder_structure,
        holder_status,
        exposure,
        exposure_status,
        attribution,
        attribution_status,
        scoring=scoring,
        scoring_status=scoring_status,
        simulated_holding=simulated_holding,
        sim_status=sim_status,
        dynamic_attribution=dynamic_attribution,
        dyn_status=dyn_status,
    )
    # 按模块统计证据条数（evidence_id前缀 → 模块名）
    _evidence_prefix_to_module: dict[str, str] = {
        "profile:": "fund_profile",
        "manager_info:": "manager_info",
        "nav_metrics:": "nav_metrics",
        "holdings:": "disclosed_holdings",
        "holder_structure:": "holder_structure",
        "exposure:": "exposure",
        "attribution:": "attribution",
        "scoring:": "scoring",
        "simulated_holding:": "simulated_holding",
        "dynamic_attribution:": "dynamic_attribution",
    }
    module_evidence_counts: dict[str, int] = {}
    for ev in evidence:
        for prefix, mod in _evidence_prefix_to_module.items():
            if ev.evidence_id.startswith(prefix):
                module_evidence_counts[mod] = module_evidence_counts.get(mod, 0) + 1
                break

    # 执行五道可信度门禁
    credibility_report = evaluate_credibility(
        fund_code=fund_code,
        fund_type=fund_type,
        modules=all_modules,
        module_source_levels=module_source_levels,
        module_meta=module_meta,
        module_evidence_counts=module_evidence_counts,
    )
    # 用门禁结果覆盖模块状态（hard gate 降级为 NEEDS_REVIEW，soft gate 降级为 OBSERVATION）
    for mod_name, gate_status in credibility_report.module_statuses.items():
        if mod_name in conclusion_map:
            current = conclusion_map[mod_name]
            # 门禁降级方向：FACT → COMPUTED → OBSERVATION → NEEDS_REVIEW
            status_order = {
                ConclusionStatus.FACT: 0,
                ConclusionStatus.COMPUTED: 1,
                ConclusionStatus.ESTIMATED: 2,
                ConclusionStatus.OBSERVATION: 3,
                ConclusionStatus.NEEDS_REVIEW: 4,
            }
            if status_order.get(gate_status, 0) > status_order.get(current, 0):
                conclusion_map[mod_name] = gate_status
    # 添加门禁警告
    gating_warnings = credibility_report.warnings

    warnings = [
        *profile_warnings,
        *manager_warnings,
        *nav_warnings,
        *holdings_warnings,
        *holder_warnings,
        *exposure_warnings,
        *attribution_warnings,
        *scoring_warnings,
        *sim_warnings,
        *dyn_warnings,
        *gating_warnings,
    ]
    residuals = _build_residuals(exposure, attribution, dynamic_attribution)
    risk_alerts = _build_risk_alerts(
        nav_metrics,
        manager_info,
        holdings,
        holder_structure,
        exposure,
        attribution,
        scoring=scoring,
        simulated_holding=simulated_holding,
        dynamic_attribution=dynamic_attribution,
    )
    metadata = ResearchPacketMetadata(
        fund_code=fund_code,
        generated_at=datetime.now(),
        data_date=_data_date(db, fund_code),
        template=template,
        platform_version=__version__,
        data_source_levels=[DataSourceLevel.B, DataSourceLevel.LOCAL],
        algorithm_versions={
            NAV_METRICS_ALGORITHM_NAME: NAV_METRICS_ALGORITHM_VERSION,
            HOLDINGS_ALGORITHM_NAME: HOLDINGS_ALGORITHM_VERSION,
            EXPOSURE_ALGORITHM_NAME: EXPOSURE_ALGORITHM_VERSION,
            ATTRIBUTION_ALGORITHM_NAME: ATTRIBUTION_ALGORITHM_VERSION,
            SCORING_ALGORITHM_NAME: SCORING_ALGORITHM_VERSION,
            SIMULATED_HOLDING_ALGORITHM_NAME: SIMULATED_HOLDING_ALGORITHM_VERSION,
            DYNAMIC_ATTRIBUTION_ALGORITHM_NAME: DYNAMIC_ATTRIBUTION_ALGORITHM_VERSION,
        },
        missing_fields=[
            key for key, value in {
                "fund_profile": fund_profile,
                "manager_info": manager_info,
                "nav_metrics": nav_metrics,
                "disclosed_holdings": holdings,
                "holder_structure": holder_structure,
                "exposure": exposure,
                "attribution": attribution,
                # Phase 2 modules are optional/estimated per AGENTS.md principle #2
                # (estimated pollution isolation) — they do NOT gate core
                # conclusion credibility and are excluded from missing_fields.
                # "scoring": scoring,
                # "simulated_holding": simulated_holding,
                # "dynamic_attribution": dynamic_attribution,
            }.items()
            if value is None
        ],
        conclusion_statuses=conclusion_map,
        overall_confidence=_overall_confidence(conclusion_map),
    )
    return ResearchPacket(
        metadata=metadata,
        fund_profile=fund_profile,
        manager_info=manager_info,
        nav_metrics=nav_metrics,
        disclosed_holdings=holdings,
        holder_structure=holder_structure,
        exposure=exposure,
        attribution=attribution,
        scoring=scoring,
        simulated_holding=simulated_holding,
        dynamic_attribution=dynamic_attribution,
        residuals=residuals,
        risk_alerts=risk_alerts,
        evidence=evidence,
        data_quality={
            "nav_status": nav_status.value,
            "manager_info_status": manager_status.value,
            "holdings_status": holdings_status.value,
            "holder_structure_status": holder_status.value,
            "exposure_status": exposure_status.value,
            "attribution_status": attribution_status.value,
            "scoring_status": scoring_status.value,
            "simulated_holding_status": sim_status.value,
            "dynamic_attribution_status": dyn_status.value,
            "evidence_count": len(evidence),
            "risk_alert_count": len(risk_alerts),
            "credibility_gates_passed": sum(1 for r in credibility_report.results if r.passed),
            "credibility_gates_total": len(credibility_report.results),
            "credibility_overall": credibility_report.overall_status.value,
        },
        conclusion_map=conclusion_map,
        warnings=warnings,
    )


def render_packet_markdown(packet: ResearchPacket) -> str:
    """Render a compact Markdown summary for local storage."""
    profile = packet.fund_profile or {}
    lines = [
        f"# {profile.get('short_name') or packet.metadata.fund_code} 研究包",
        "",
        f"- 基金代码: {packet.metadata.fund_code}",
        f"- 模板: {packet.metadata.template}",
        f"- 数据日期: {packet.metadata.data_date}",
        f"- 整体置信度: {packet.metadata.overall_confidence.value}",
        f"- 结论状态: {packet.metadata.conclusion_statuses}",
    ]
    if packet.warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in packet.warnings)
    return "\n".join(lines)


def _persist_evidence_records(db: Session, packet: ResearchPacket) -> None:
    """Upsert packet evidence into the evidence table."""
    for evidence in packet.evidence:
        date_start = None
        date_end = None
        if evidence.date_range:
            date_start, date_end = evidence.date_range
        algorithm_metadata = (
            evidence.algorithm_metadata.model_dump(mode="json")
            if evidence.algorithm_metadata is not None
            else None
        )
        values = {
            "entity_id": evidence.entity_id,
            "entity_type": "fund" if evidence.entity_id.startswith("fund:") else "unknown",
            "evidence_type": evidence.evidence_type.value,
            "source": evidence.source,
            "source_level": evidence.source_level.value,
            "date_start": date_start,
            "date_end": date_end,
            "algorithm_metadata": algorithm_metadata,
            "report_snippet": evidence.report_snippet,
            "report_location": evidence.report_location,
            "data_summary": evidence.data_summary,
            "confidence": evidence.confidence.value,
            "conclusion_status": evidence.conclusion_status.value,
        }
        existing = db.scalar(
            select(DBEvidenceRecord).where(DBEvidenceRecord.evidence_id == evidence.evidence_id)
        )
        if existing is None:
            db.add(DBEvidenceRecord(evidence_id=evidence.evidence_id, **values))
            continue
        for key, value in values.items():
            setattr(existing, key, value)


def persist_research_packet(db: Session, packet: ResearchPacket) -> ResearchPacketRecord:
    """Persist a Research Packet and mark previous packets as non-latest."""
    packet_id = f"rp_{packet.metadata.fund_code}_{uuid4().hex[:12]}"
    db.execute(
        update(ResearchPacketRecord)
        .where(ResearchPacketRecord.fund_code == packet.metadata.fund_code)
        .where(ResearchPacketRecord.template == packet.metadata.template)
        .values(is_latest=False)
    )
    record = ResearchPacketRecord(
        packet_id=packet_id,
        fund_code=packet.metadata.fund_code,
        template=packet.metadata.template,
        generated_at=packet.metadata.generated_at,
        data_date=packet.metadata.data_date,
        packet_json=packet.model_dump(mode="json"),
        markdown_text=render_packet_markdown(packet),
        platform_version=packet.metadata.platform_version,
        overall_confidence=packet.metadata.overall_confidence.value,
        is_latest=True,
    )
    db.add(record)
    _persist_evidence_records(db, packet)
    db.commit()
    db.refresh(record)
    return record
