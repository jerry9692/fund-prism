"""基金组合穿透分析（需求书 §6.3.9 / §12.4.2，Phase 4 计划 P4C）。

对有权重的基金池（组合）做：

1. **组合层指标**：NAV 加权组合日收益序列 → 收益/波动/回撤/修复天数
   （复用 ``nav_metrics.calculate_nav_metrics`` 口径）；基金间收益相关性矩阵。
2. **穿透暴露**：风格暴露 = 各基金最新风格回归暴露加权合成；
   行业暴露 = 披露持仓行业权重加权合成（stock_industry_membership SW2021 口径）。
3. **重仓重叠穿透**：披露持仓交集（computed 口径）+ 模拟持仓交集
   （``estimated_*`` 口径隔离展示，不进默认结论）。
4. **集中度风险**：基金经理集中度（同一现任经理权重合计）、
   单公司基金集中度。

权重语义：成员带 ``weight_pct`` = 组合；全部无权重 = 观察列表，
等权分析并告警（向后兼容）。
"""

from dataclasses import dataclass, field
from datetime import date as dt_date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.nav_metrics import calculate_nav_metrics
from fund_research.core.enums import ConclusionStatus
from fund_research.db.models import (
    FundCompany,
    FundDisclosedHoldings,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import (
    FundPool,
    FundPoolMember,
    SimulatedHoldingResult,
    StockIndustryMembership,
)
from fund_research.db.models_phase4 import UserPortfolio

ALGORITHM_NAME = "portfolio_analysis"
ALGORITHM_VERSION = "0.1.0"

# 组合收益序列最低共同样本数（不足 → needs_review）
MIN_PORTFOLIO_OBSERVATIONS = 60

# 重叠穿透：被 ≥2 只成员持有的个股视为组合层重叠
OVERLAP_MIN_FUNDS = 2

# 行业口径（§5.3.3 版本化）
INDUSTRY_CLASSIFICATION_TYPE = "SW"
INDUSTRY_LEVEL = 1


@dataclass
class PortfolioAnalysisResult:
    """组合穿透分析结果（不落库载荷）。"""

    pool_id: int
    pool_name: str | None = None
    members: list[dict] = field(default_factory=list)
    weights_mode: str = "equal"
    member_weights: dict[str, float] = field(default_factory=dict)
    portfolio_metrics: dict | None = None
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    style_penetration: dict = field(default_factory=dict)
    industry_penetration: dict = field(default_factory=dict)
    holding_overlap: dict = field(default_factory=dict)
    concentration: dict = field(default_factory=dict)
    window_start: str | None = None
    window_end: str | None = None
    conclusion_status: str = ConclusionStatus.COMPUTED.value
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict:
        return {
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "members": self.members,
            "weights_mode": self.weights_mode,
            "member_weights": self.member_weights,
            "portfolio_metrics": self.portfolio_metrics,
            "correlation_matrix": self.correlation_matrix,
            "style_penetration": self.style_penetration,
            "industry_penetration": self.industry_penetration,
            "holding_overlap": self.holding_overlap,
            "concentration": self.concentration,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


# ============================================================
# 数据加载
# ============================================================


def load_pool(db: Session, pool_id: int) -> tuple[FundPool | None, list[FundPoolMember]]:
    """加载基金池与成员。"""
    pool = db.get(FundPool, pool_id)
    if pool is None:
        return None, []
    members = list(
        db.scalars(
            select(FundPoolMember)
            .where(FundPoolMember.pool_id == pool_id)
            .order_by(FundPoolMember.added_at)
        ).all()
    )
    return pool, members


def normalize_member_weights(members: list[FundPoolMember]) -> tuple[dict[str, float], str]:
    """归一化成员权重。

    全部无权重 → 等权（watchlist 语义）；有权重 → 按 weight_pct 归一
    （None 视为 0，合计 <=0 回落等权）。返回 (weights, mode)。
    """
    codes = [m.fund_code for m in members]
    has_any_weight = any(m.weight_pct is not None for m in members)
    if not has_any_weight or not members:
        equal = 1.0 / len(codes) if codes else 0.0
        return {code: equal for code in codes}, "equal"
    raw = {m.fund_code: float(m.weight_pct or 0.0) for m in members}
    total = sum(v for v in raw.values() if v > 0)
    if total <= 0:
        equal = 1.0 / len(codes)
        return {code: equal for code in codes}, "equal"
    return {code: max(v, 0.0) / total for code, v in raw.items()}, "weighted"


def _fund_daily_returns(db: Session, fund_code: str) -> pd.Series:
    """基金日收益序列：复权净值 pct_change（单位净值兜底）。"""
    rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date)
    ).all()
    values: dict[dt_date, float] = {}
    prev_nav: float | None = None
    for row in rows:
        nav = row.adjusted_nav or row.unit_nav
        if nav is None or nav != nav or nav <= 0:
            continue
        if prev_nav is not None and prev_nav > 0:
            values[row.trade_date] = float(nav) / prev_nav - 1.0
        prev_nav = float(nav)
    return pd.Series(values, dtype="float64").sort_index()


# ============================================================
# 组合层指标与相关性
# ============================================================


def compute_portfolio_returns(
    returns_by_fund: dict[str, pd.Series], weights: dict[str, float]
) -> tuple[pd.Series, pd.DataFrame]:
    """加权组合日收益（共同日期窗口）与成员收益宽表。"""
    frame = pd.DataFrame(returns_by_fund).dropna()
    if frame.empty:
        return pd.Series(dtype="float64"), frame
    weight_series = pd.Series(
        {code: weights.get(code, 0.0) for code in frame.columns}, dtype="float64"
    )
    portfolio = frame @ weight_series
    portfolio.name = "portfolio_return"
    return portfolio, frame


def _build_correlation_matrix(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    """收益相关性矩阵（对称，对角为 1；样本不足返回空）。"""
    if frame.shape[0] < 2 or frame.shape[1] < 2:
        return {}
    corr = frame.corr()
    return {
        a: {b: round(float(corr.loc[a, b]), 4) for b in corr.columns}
        for a in corr.index
    }


# ============================================================
# 穿透暴露：风格与行业
# ============================================================


def _latest_style_exposure(db: Session, fund_code: str) -> dict[str, float] | None:
    row = db.scalars(
        select(StyleExposureResult)
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == "style",
        )
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(1)
    ).first()
    if row is None or not row.exposure_values:
        return None
    return {
        key: float(value)
        for key, value in row.exposure_values.items()
        if value is not None
    }


def compute_style_penetration(
    db: Session, codes: list[str], weights: dict[str, float]
) -> tuple[dict, list[str]]:
    """风格穿透：指纹风格维度加权合成（缺失基金权重再归一）。"""
    warnings: list[str] = []
    exposures: dict[str, dict[str, float]] = {}
    for code in codes:
        exposure = _latest_style_exposure(db, code)
        if exposure is not None:
            exposures[code] = exposure
        else:
            warnings.append(f"基金 {code} 无风格暴露结果，穿透合成已剔除")
    if not exposures:
        return {"available": False}, warnings

    available_weight = sum(weights.get(code, 0.0) for code in exposures)
    if available_weight <= 0:
        return {"available": False}, warnings
    dims = ("large_cap", "mid_cap", "small_cap", "growth", "value")
    composite: dict[str, float] = {}
    for dim in dims:
        total = sum(
            weights.get(code, 0.0) * exposure.get(dim, 0.0)
            for code, exposure in exposures.items()
            if dim in exposure
        )
        composite[dim] = round(total / available_weight, 4)
    return {
        "available": True,
        "composite": composite,
        "covered_funds": sorted(exposures),
        "coverage_weight": round(available_weight, 4),
    }, warnings


def _latest_industry_map(db: Session) -> dict[str, str]:
    """股票 → 申万一级行业映射（最新快照，SW2021 口径）。"""
    rows = db.scalars(
        select(StockIndustryMembership)
        .where(
            StockIndustryMembership.classification_type == INDUSTRY_CLASSIFICATION_TYPE,
            StockIndustryMembership.level == INDUSTRY_LEVEL,
        )
        .order_by(StockIndustryMembership.effective_date.desc())
    ).all()
    mapping: dict[str, str] = {}
    for row in rows:
        mapping.setdefault(row.stock_code, row.industry_name)
    return mapping


def _latest_disclosed_holdings(db: Session, fund_code: str) -> list[FundDisclosedHoldings]:
    rows = db.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(200)
    ).all()
    if not rows:
        return []
    latest_date = rows[0].report_date
    return [r for r in rows if r.report_date == latest_date]


def compute_industry_penetration(
    db: Session, codes: list[str], weights: dict[str, float]
) -> tuple[dict, list[str]]:
    """行业穿透：披露持仓行业权重加权合成（SW2021 一级）。"""
    warnings: list[str] = []
    industry_map = _latest_industry_map(db)
    industry_weights: dict[str, float] = {}
    covered_funds: list[str] = []
    disclosed_weight_total = 0.0

    for code in codes:
        fund_weight = weights.get(code, 0.0)
        holdings = [
            h
            for h in _latest_disclosed_holdings(db, code)
            if h.asset_type in ("股票", "stock") and h.weight_pct
        ]
        if not holdings:
            warnings.append(f"基金 {code} 无披露股票持仓，行业穿透已剔除")
            continue
        covered_funds.append(code)
        disclosed_weight_total += fund_weight * sum(
            float(h.weight_pct) for h in holdings
        ) / 100.0
        for h in holdings:
            industry = industry_map.get(h.security_code) or h.industry or "未分类"
            contribution = fund_weight * float(h.weight_pct) / 100.0
            industry_weights[industry] = industry_weights.get(industry, 0.0) + contribution

    if not industry_weights:
        return {"available": False}, warnings

    ranked = sorted(industry_weights.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(industry_weights.values())
    hhi = sum((v / total) ** 2 for v in industry_weights.values()) if total > 0 else None
    return {
        "available": True,
        "industries": [
            {"industry": name, "weight": round(value, 6)} for name, value in ranked
        ],
        "top5": [
            {"industry": name, "weight": round(value, 6)}
            for name, value in ranked[:5]
        ],
        "industry_hhi": round(hhi, 4) if hhi is not None else None,
        "covered_funds": covered_funds,
        "disclosed_weight_total": round(disclosed_weight_total, 4),
    }, warnings


# ============================================================
# 重仓重叠穿透（披露口径 + estimated 模拟口径隔离）
# ============================================================


def _overlap_from_maps(
    holdings_by_fund: dict[str, dict[str, float]],
    weights: dict[str, float],
    names_by_code: dict[str, str],
) -> dict:
    """由 {fund: {stock: weight}} 计算组合层重叠指标。"""
    funds = sorted(holdings_by_fund)
    stock_funds: dict[str, list[str]] = {}
    for fund_code, holdings in holdings_by_fund.items():
        for stock in holdings:
            stock_funds.setdefault(stock, []).append(fund_code)

    shared = {
        stock: holders
        for stock, holders in stock_funds.items()
        if len(holders) >= OVERLAP_MIN_FUNDS
    }
    top_overlap = []
    for stock, holders in shared.items():
        combined = sum(
            weights.get(fund, 0.0) * holdings_by_fund[fund][stock]
            for fund in holders
        )
        top_overlap.append(
            {
                "stock_code": stock,
                "stock_name": names_by_code.get(stock),
                "fund_codes": sorted(holders),
                "fund_count": len(holders),
                "combined_weight": round(combined, 6),
            }
        )
    top_overlap.sort(key=lambda item: item["combined_weight"], reverse=True)

    # 成对重叠个数（对称矩阵）
    pairwise: dict[str, dict[str, int]] = {}
    for i, a in enumerate(funds):
        pairwise[a] = {}
        for b in funds[i:]:
            count = len(set(holdings_by_fund[a]) & set(holdings_by_fund[b]))
            pairwise[a][b] = count
            pairwise.setdefault(b, {})[a] = count

    union = set().union(*[set(h) for h in holdings_by_fund.values()]) if holdings_by_fund else set()
    return {
        "available": bool(holdings_by_fund),
        "shared_stock_count": len(shared),
        "union_stock_count": len(union),
        "overlap_ratio": round(len(shared) / len(union), 4) if union else None,
        "top_overlaps": top_overlap[:20],
        "pairwise_shared_counts": pairwise,
    }


def compute_holding_overlap(
    db: Session, codes: list[str], weights: dict[str, float]
) -> tuple[dict, list[str]]:
    """重仓重叠穿透：披露口径（computed）+ 模拟口径（estimated_* 隔离）。"""
    warnings: list[str] = []

    # 披露口径
    disclosed_map: dict[str, dict[str, float]] = {}
    names: dict[str, str] = {}
    for code in codes:
        holdings = {}
        for h in _latest_disclosed_holdings(db, code):
            if h.asset_type in ("股票", "stock") and h.weight_pct:
                holdings[h.security_code] = float(h.weight_pct) / 100.0
                if h.security_name:
                    names[h.security_code] = h.security_name
        if holdings:
            disclosed_map[code] = holdings
    disclosed = _overlap_from_maps(disclosed_map, weights, names)

    # 模拟口径（estimated_*：不进默认结论）
    simulated_map: dict[str, dict[str, float]] = {}
    for code in codes:
        row = db.scalars(
            select(SimulatedHoldingResult)
            .where(SimulatedHoldingResult.fund_code == code)
            .order_by(SimulatedHoldingResult.calc_date.desc())
            .limit(1)
        ).first()
        if row is None or not row.holdings_detail:
            continue
        holdings = {}
        for item in row.holdings_detail:
            stock_code = str(item.get("stock_code") or "")
            weight = item.get("estimated_weight")
            if stock_code and weight is not None:
                holdings[stock_code] = float(weight)
                if item.get("stock_name"):
                    names[stock_code] = str(item["stock_name"])
        if holdings:
            simulated_map[code] = holdings
    estimated = _overlap_from_maps(simulated_map, weights, names)
    if not simulated_map:
        warnings.append("无成员基金模拟持仓结果，estimated 口径重叠不可得")

    return {
        "disclosed": disclosed,
        "estimated_overlap": {f"estimated_{k}": v for k, v in estimated.items()},
    }, warnings


# ============================================================
# 集中度风险
# ============================================================


def compute_concentration(
    db: Session, codes: list[str], weights: dict[str, float]
) -> dict:
    """经理集中度（同一现任经理权重合计）与公司集中度。"""
    # 现任经理
    tenures = db.scalars(
        select(FundManagerTenure).where(
            FundManagerTenure.fund_code.in_(codes),
            FundManagerTenure.end_date.is_(None),
        )
    ).all()
    manager_ids = sorted({t.manager_id for t in tenures if t.manager_id})
    manager_names = {
        m.manager_id: m.name
        for m in db.scalars(
            select(FundManager).where(FundManager.manager_id.in_(manager_ids))
        ).all()
    } if manager_ids else {}
    manager_weights: dict[str, float] = {}
    manager_funds: dict[str, set[str]] = {}
    for tenure in tenures:
        if not tenure.manager_id:
            continue
        manager_weights[tenure.manager_id] = manager_weights.get(
            tenure.manager_id, 0.0
        ) + weights.get(tenure.fund_code, 0.0)
        manager_funds.setdefault(tenure.manager_id, set()).add(tenure.fund_code)
    manager_rows = sorted(
        (
            {
                "manager_id": mid,
                "manager_name": manager_names.get(mid, mid),
                "weight": round(weight, 4),
                "fund_codes": sorted(manager_funds.get(mid, set())),
            }
            for mid, weight in manager_weights.items()
        ),
        key=lambda item: item["weight"],
        reverse=True,
    )

    # 基金公司
    funds = db.scalars(select(FundMain).where(FundMain.fund_code.in_(codes))).all()
    company_ids = [f.fund_company_id for f in funds if f.fund_company_id]
    company_names = {
        c.id: (c.short_name or c.name)
        for c in db.scalars(select(FundCompany).where(FundCompany.id.in_(company_ids))).all()
    } if company_ids else {}
    company_weights: dict[str, float] = {}
    company_funds: dict[str, set[str]] = {}
    for fund in funds:
        if fund.fund_company_id is None:
            continue
        name = company_names.get(fund.fund_company_id, str(fund.fund_company_id))
        company_weights[name] = company_weights.get(name, 0.0) + weights.get(
            fund.fund_code, 0.0
        )
        company_funds.setdefault(name, set()).add(fund.fund_code)
    company_rows = sorted(
        (
            {
                "company": name,
                "weight": round(weight, 4),
                "fund_codes": sorted(company_funds.get(name, set())),
            }
            for name, weight in company_weights.items()
        ),
        key=lambda item: item["weight"],
        reverse=True,
    )

    return {
        "manager_concentration": manager_rows,
        "company_concentration": company_rows,
        "max_manager_weight": manager_rows[0]["weight"] if manager_rows else None,
        "max_company_weight": company_rows[0]["weight"] if company_rows else None,
    }


# ============================================================
# 主流程与持久化
# ============================================================


def compute_portfolio_analysis(db: Session, pool_id: int) -> PortfolioAnalysisResult:
    """组合穿透分析主流程（不落库）。"""
    pool, members = load_pool(db, pool_id)
    result = PortfolioAnalysisResult(pool_id=pool_id)
    if pool is None:
        result.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        result.warnings.append(f"基金池 {pool_id} 不存在")
        return result
    result.pool_name = pool.name

    if len(members) < 2:
        result.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        result.warnings.append("组合成员不足 2 只，无法进行组合穿透分析")
        return result

    weights, mode = normalize_member_weights(members)
    result.weights_mode = mode
    result.member_weights = {code: round(w, 6) for code, w in weights.items()}
    if mode == "equal":
        result.warnings.append("池成员未设置权重（观察列表），组合分析按等权口径")

    fund_rows = db.scalars(
        select(FundMain).where(
            FundMain.fund_code.in_([m.fund_code for m in members])
        )
    ).all()
    names_by_code = {f.fund_code: f.short_name for f in fund_rows}
    result.members = [
        {
            "fund_code": m.fund_code,
            "fund_name": names_by_code.get(m.fund_code),
            "weight": round(weights.get(m.fund_code, 0.0), 6),
        }
        for m in members
    ]

    codes = [m.fund_code for m in members]

    # 1. 组合层指标（共同日期窗口，nav_metrics 口径）
    returns_by_fund = {code: _fund_daily_returns(db, code) for code in codes}
    empty = [code for code, series in returns_by_fund.items() if series.empty]
    if empty:
        result.warnings.append(f"基金 {', '.join(empty)} 净值序列缺失")
    portfolio_returns, frame = compute_portfolio_returns(returns_by_fund, weights)
    if len(portfolio_returns) < MIN_PORTFOLIO_OBSERVATIONS:
        result.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        result.warnings.append(
            f"组合共同收益窗口 {len(portfolio_returns)} < {MIN_PORTFOLIO_OBSERVATIONS}，"
            "成员净值序列重叠不足"
        )
        return result

    nav_df = pd.DataFrame(
        {
            "trade_date": list(portfolio_returns.index),
            "daily_return": portfolio_returns.values,
        }
    )
    metrics_result = calculate_nav_metrics(nav_df)
    result.portfolio_metrics = metrics_result.to_data()["metrics"]
    result.portfolio_metrics["observations"] = metrics_result.observations
    result.warnings.extend(metrics_result.warnings)
    result.window_start = str(portfolio_returns.index.min())
    result.window_end = str(portfolio_returns.index.max())

    # 2. 相关性矩阵（对称，对角为 1）
    result.correlation_matrix = _build_correlation_matrix(frame)

    # 3. 穿透暴露
    style, style_warnings = compute_style_penetration(db, codes, weights)
    result.style_penetration = style
    result.warnings.extend(style_warnings)
    industry, industry_warnings = compute_industry_penetration(db, codes, weights)
    result.industry_penetration = industry
    result.warnings.extend(industry_warnings)

    # 4. 重仓重叠（披露 + estimated 模拟口径隔离）
    overlap, overlap_warnings = compute_holding_overlap(db, codes, weights)
    result.holding_overlap = overlap
    result.warnings.extend(overlap_warnings)

    # 5. 集中度风险
    result.concentration = compute_concentration(db, codes, weights)
    return result


def persist_portfolio_analysis(
    db: Session, result: PortfolioAnalysisResult, calc_date: dt_date | None = None
) -> UserPortfolio:
    """幂等落库：同 (pool_id, calc_date, 算法版本) 覆盖更新。"""
    calc_date = calc_date or dt_date.today()
    existing = db.scalar(
        select(UserPortfolio).where(
            UserPortfolio.pool_id == result.pool_id,
            UserPortfolio.calc_date == calc_date,
            UserPortfolio.algorithm_name == ALGORITHM_NAME,
            UserPortfolio.algorithm_version == ALGORITHM_VERSION,
        )
    )
    if existing is None:
        existing = UserPortfolio(
            pool_id=result.pool_id,
            calc_date=calc_date,
            algorithm_name=ALGORITHM_NAME,
            algorithm_version=ALGORITHM_VERSION,
        )
        db.add(existing)
    existing.member_weights = result.member_weights
    existing.weights_mode = result.weights_mode
    existing.portfolio_metrics = result.portfolio_metrics
    existing.correlation_matrix = result.correlation_matrix
    existing.style_penetration = result.style_penetration
    existing.industry_penetration = result.industry_penetration
    existing.holding_overlap = result.holding_overlap
    existing.concentration = result.concentration
    existing.window_start = (
        dt_date.fromisoformat(result.window_start) if result.window_start else None
    )
    existing.window_end = (
        dt_date.fromisoformat(result.window_end) if result.window_end else None
    )
    existing.conclusion_status = result.conclusion_status
    existing.warnings = result.warnings or None
    db.flush()
    return existing


def get_latest_portfolio_analysis(db: Session, pool_id: int) -> UserPortfolio | None:
    """取单池最近一条组合分析快照。"""
    return db.scalars(
        select(UserPortfolio)
        .where(UserPortfolio.pool_id == pool_id)
        .order_by(UserPortfolio.calc_date.desc())
        .limit(1)
    ).first()


def portfolio_row_to_dict(row: UserPortfolio, pool_name: str | None = None) -> dict:
    return {
        "id": row.id,
        "pool_id": row.pool_id,
        "pool_name": pool_name,
        "calc_date": str(row.calc_date),
        "algorithm_version": row.algorithm_version,
        "weights_mode": row.weights_mode,
        "member_weights": row.member_weights or {},
        "portfolio_metrics": row.portfolio_metrics or {},
        "correlation_matrix": row.correlation_matrix or {},
        "style_penetration": row.style_penetration or {},
        "industry_penetration": row.industry_penetration or {},
        "holding_overlap": row.holding_overlap or {},
        "concentration": row.concentration or {},
        "window_start": str(row.window_start) if row.window_start else None,
        "window_end": str(row.window_end) if row.window_end else None,
        "conclusion_status": row.conclusion_status,
        "warnings": row.warnings or [],
    }
