"""基金公司画像频谱与经理团队画像（需求书 §6.2.6 / §12.4.5，Phase 4 计划 P4E）。

1. **公司频谱**（`build_company_spectrum`）：按 ``fund_company`` 聚合在库基金 ——
   alpha/beta 频谱（Jensen 口径，alpha 与 ``scoring_dimensions.compute_alpha``
   同公式、beta 对沪深300）、风格分布（指纹风格维度聚合）、类型结构
   （基金族占比）、规模光谱。基金数 <3 的公司标"样本不足" observation。
2. **经理团队画像**（`build_manager_profile`）：按 ``fund_manager`` 聚合 ——
   任职年限加权 alpha、管理规模、风格稳定性（复用 ``anomaly.detect_style_drift``）、
   同类排名中位数（``rank.rank_in_category`` 口径）。口径与 ``manager_profile``
   研究模板同源（tenure 表 + 评分口径），不重复计算。

只读聚合模块：不落结果表（§15.2 未列 P4E 结果表），经 API 即时计算。
"""

from dataclasses import dataclass, field
from statistics import median

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.anomaly import detect_style_drift
from fund_research.analysis.index_fund_selection import _latest_scale
from fund_research.analysis.rank import rank_in_category
from fund_research.config.settings import get_settings
from fund_research.core.enums import ConclusionStatus
from fund_research.data.update import _daily_return_series
from fund_research.db.models import (
    FundCompany,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    StockDaily,
    StyleExposureResult,
)
from fund_research.db.models_phase3 import FundFingerprint
from fund_research.research.credibility import normalize_fund_family

ALGORITHM_NAME = "company_profile"
ALGORITHM_VERSION = "0.1.0"

# 频谱基准与最低样本（§12.4.5：alpha/beta 散点谱对沪深300）
SPECTRUM_BENCHMARK_SYMBOL = "sh000300"
MIN_COMPANY_FUNDS = 3
MIN_ALPHA_BETA_OBSERVATIONS = 120

# 指纹风格维度（fingerprint vector 顶层键）
STYLE_DIMENSIONS = ("large_cap", "mid_cap", "small_cap", "growth", "value")

STYLE_DIMENSION_LABELS = {
    "large_cap": "大盘",
    "mid_cap": "中盘",
    "small_cap": "小盘",
    "growth": "成长",
    "value": "价值",
}

FUND_FAMILY_LABELS = {
    "equity_family": "主动权益",
    "mixed_family": "混合型",
    "index_family": "指数族",
    "bond_family": "债券族",
    "money_family": "货币族",
}


def fund_family_of(fund: FundMain) -> str:
    """基金族归一：ETF/联接/指增标识优先于粗分类（同 P4A 门禁适配口径）。"""
    if fund.is_etf or fund.is_etf_feeder or fund.is_index_enhanced:
        return "index_family"
    return normalize_fund_family(fund.category) or "mixed_family"


# ============================================================
# alpha / beta 频谱（Jensen 口径，与 scoring_dimensions 同公式）
# ============================================================


def load_fund_return_series(db: Session, fund_code: str) -> pd.Series:
    """基金净值日收益序列（复权净值优先，口径与 P4.1-4 一致）。"""
    rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date)
    ).all()
    series = _daily_return_series(rows, lambda row: row.adjusted_nav or row.unit_nav)
    series.name = fund_code
    return series


def load_benchmark_return_series(db: Session, symbol: str) -> pd.Series:
    rows = db.scalars(
        select(StockDaily).where(StockDaily.stock_code == symbol).order_by(StockDaily.trade_date)
    ).all()
    series = _daily_return_series(rows, lambda row: row.close_price)
    series.name = symbol
    return series


def compute_alpha_beta(fund_ret: pd.Series, bench_ret: pd.Series) -> dict | None:
    """Jensen alpha(年化) + beta：超额收益 OLS（Rf 读 settings，同评分口径）。

    对齐样本不足返回 None（不硬算）。
    """
    aligned = pd.concat([fund_ret, bench_ret], axis=1).dropna()
    if len(aligned) < MIN_ALPHA_BETA_OBSERVATIONS:
        return None
    risk_free_daily = get_settings().risk_free_rate / 252
    y = (aligned.iloc[:, 0] - risk_free_daily).to_numpy()
    x = (aligned.iloc[:, 1] - risk_free_daily).to_numpy()
    beta_den = float(np.sum((x - x.mean()) ** 2))
    if beta_den <= 0:
        return None
    beta = float(np.sum((x - x.mean()) * (y - y.mean())) / beta_den)
    alpha = float(y.mean() - beta * x.mean())
    return {
        "alpha_annualized": alpha * 252,
        "beta": beta,
        "observations": int(len(aligned)),
    }


def compute_fund_alpha_beta_map(
    db: Session, fund_codes: list[str], bench_ret: pd.Series
) -> dict[str, dict]:
    """批量计算 alpha/beta（基准序列只加载一次）。"""
    result: dict[str, dict] = {}
    for code in fund_codes:
        fund_ret = load_fund_return_series(db, code)
        if fund_ret.empty:
            continue
        ab = compute_alpha_beta(fund_ret, bench_ret)
        if ab is not None:
            result[code] = ab
    return result


# ============================================================
# 公司频谱
# ============================================================


@dataclass
class CompanySpectrum:
    """单一基金公司的画像频谱。"""

    company_id: str
    company_name: str
    fund_count: int = 0
    funds: list[dict] = field(default_factory=list)
    alpha_beta_summary: dict = field(default_factory=dict)
    style_distribution: dict = field(default_factory=dict)
    category_structure: dict = field(default_factory=dict)
    scale_spectrum: dict = field(default_factory=dict)
    conclusion_status: str = ConclusionStatus.COMPUTED.value
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict:
        return {
            "company_id": self.company_id,
            "company_name": self.company_name,
            "fund_count": self.fund_count,
            "funds": self.funds,
            "alpha_beta_summary": self.alpha_beta_summary,
            "style_distribution": self.style_distribution,
            "category_structure": self.category_structure,
            "scale_spectrum": self.scale_spectrum,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


def _latest_fingerprint_vector(db: Session, fund_code: str) -> dict:
    row = db.scalars(
        select(FundFingerprint)
        .where(FundFingerprint.fund_code == fund_code)
        .order_by(FundFingerprint.calc_date.desc())
        .limit(1)
    ).first()
    return dict(row.vector or {}) if row else {}


def build_company_spectrum(db: Session, company_id: str) -> CompanySpectrum | None:
    """聚合单一公司的在库基金画像；公司不存在返回 None。"""
    company = db.scalar(select(FundCompany).where(FundCompany.company_id == company_id))
    if company is None:
        return None

    funds = list(
        db.scalars(
            select(FundMain)
            .where(FundMain.fund_company_id == company.id)
            .order_by(FundMain.fund_code)
        ).all()
    )
    spectrum = CompanySpectrum(
        company_id=company.company_id,
        company_name=company.short_name or company.name,
        fund_count=len(funds),
    )
    if not funds:
        spectrum.conclusion_status = ConclusionStatus.OBSERVATION.value
        spectrum.warnings.append("该公司在库基金数为 0，样本不足")
        return spectrum

    # 1. alpha/beta 频谱（对沪深300）
    bench_ret = load_benchmark_return_series(db, SPECTRUM_BENCHMARK_SYMBOL)
    alpha_beta_map = (
        compute_fund_alpha_beta_map(db, [f.fund_code for f in funds], bench_ret)
        if not bench_ret.empty
        else {}
    )
    if bench_ret.empty:
        spectrum.warnings.append(f"基准 {SPECTRUM_BENCHMARK_SYMBOL} 无行情，alpha/beta 频谱不可得")

    # 2. 逐基金明细（气泡图数据：alpha/beta/规模/族）
    style_vectors: list[dict] = []
    family_counts: dict[str, int] = {}
    scales: list[float] = []
    for fund in funds:
        family = fund_family_of(fund)
        family_counts[family] = family_counts.get(family, 0) + 1
        scale = _latest_scale(db, fund.fund_code)
        if scale is not None:
            scales.append(scale)
        ab = alpha_beta_map.get(fund.fund_code)
        vector = _latest_fingerprint_vector(db, fund.fund_code)
        styles = {
            dim: vector.get(dim)
            for dim in STYLE_DIMENSIONS
            if isinstance(vector.get(dim), (int, float))
        }
        if styles:
            style_vectors.append(styles)
        spectrum.funds.append({
            "fund_code": fund.fund_code,
            "fund_name": getattr(fund, "short_name", None),
            "family": family,
            "family_label": FUND_FAMILY_LABELS.get(family, family),
            "sub_category": fund.sub_category,
            "alpha_annualized": ab["alpha_annualized"] if ab else None,
            "beta": ab["beta"] if ab else None,
            "scale": scale,
        })

    alphas = [f["alpha_annualized"] for f in spectrum.funds if f["alpha_annualized"] is not None]
    betas = [f["beta"] for f in spectrum.funds if f["beta"] is not None]
    spectrum.alpha_beta_summary = {
        "coverage": len(alphas) / len(funds) if funds else 0.0,
        "median_alpha": float(median(alphas)) if alphas else None,
        "median_beta": float(median(betas)) if betas else None,
        "max_alpha": max(alphas) if alphas else None,
        "min_alpha": min(alphas) if alphas else None,
    }

    # 3. 风格分布（指纹风格维度均值；无风格数据的成员不摊派，诚实降级）
    if style_vectors:
        spectrum.style_distribution = {
            "available": True,
            "coverage_funds": len(style_vectors),
            "coverage_weight": len(style_vectors) / len(funds),
            "dimensions": {
                dim: float(np.mean([v[dim] for v in style_vectors if dim in v]))
                for dim in STYLE_DIMENSIONS
                if any(dim in v for v in style_vectors)
            },
        }
    else:
        spectrum.style_distribution = {"available": False, "coverage_funds": 0}
        spectrum.warnings.append("成员指纹均无风格维度（风格暴露未计算），风格分布不可得")

    # 4. 类型结构与规模光谱
    spectrum.category_structure = {
        family: {
            "count": count,
            "share": round(count / len(funds), 4),
            "label": FUND_FAMILY_LABELS.get(family, family),
        }
        for family, count in sorted(family_counts.items(), key=lambda kv: -kv[1])
    }
    spectrum.scale_spectrum = {
        "total": round(float(sum(scales)), 2) if scales else None,
        "median": float(median(scales)) if scales else None,
        "max": max(scales) if scales else None,
        "min": min(scales) if scales else None,
        "coverage": len(scales) / len(funds) if funds else 0.0,
    }

    # 5. 样本量门禁（§12.4.5 验收：基金数 <3 标"样本不足" observation）
    if len(funds) < MIN_COMPANY_FUNDS:
        spectrum.conclusion_status = ConclusionStatus.OBSERVATION.value
        spectrum.warnings.append(f"在库基金 {len(funds)} 只 < {MIN_COMPANY_FUNDS}，样本不足")
    return spectrum


def list_company_spectra(db: Session) -> dict:
    """全部公司概览（频谱页气泡图 + 公司选择器数据源）。

    全池基金统一对齐基准一次性计算 alpha/beta，保证跨公司可比。
    返回 {companies: [...], funds: [...]}。
    """
    companies = list(db.scalars(select(FundCompany).order_by(FundCompany.name)).all())
    funds = list(db.scalars(select(FundMain).order_by(FundMain.fund_code)).all())
    bench_ret = load_benchmark_return_series(db, SPECTRUM_BENCHMARK_SYMBOL)
    alpha_beta_map = (
        compute_fund_alpha_beta_map(db, [f.fund_code for f in funds], bench_ret)
        if not bench_ret.empty
        else {}
    )

    company_by_pk = {c.id: c for c in companies}
    entries: list[dict] = []
    per_company_count: dict[str, int] = {}
    for fund in funds:
        company = company_by_pk.get(fund.fund_company_id)
        if company is None:
            continue
        per_company_count[company.company_id] = per_company_count.get(company.company_id, 0) + 1
        ab = alpha_beta_map.get(fund.fund_code)
        family = fund_family_of(fund)
        entries.append({
            "company_id": company.company_id,
            "company_name": company.short_name or company.name,
            "fund_code": fund.fund_code,
            "fund_name": getattr(fund, "short_name", None),
            "family": family,
            "family_label": FUND_FAMILY_LABELS.get(family, family),
            "alpha_annualized": ab["alpha_annualized"] if ab else None,
            "beta": ab["beta"] if ab else None,
            "scale": _latest_scale(db, fund.fund_code),
        })

    result: list[dict] = []
    for company in companies:
        count = per_company_count.get(company.company_id, 0)
        if count == 0:
            continue
        result.append({
            "company_id": company.company_id,
            "company_name": company.short_name or company.name,
            "fund_count": count,
            "insufficient_sample": count < MIN_COMPANY_FUNDS,
        })
    return {"companies": result, "funds": entries}


# ============================================================
# 经理团队画像
# ============================================================


@dataclass
class ManagerProfile:
    """单一基金经理的团队画像。"""

    manager_id: str
    name: str
    experience_years: float | None = None
    education: str | None = None
    bio: str | None = None
    current_funds: list[dict] = field(default_factory=list)
    history_tenures: list[dict] = field(default_factory=list)
    tenure_weighted_alpha: float | None = None
    managed_scale: float | None = None
    style_stability: dict = field(default_factory=dict)
    peer_rank: dict = field(default_factory=dict)
    conclusion_status: str = ConclusionStatus.COMPUTED.value
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict:
        return {
            "manager_id": self.manager_id,
            "name": self.name,
            "experience_years": self.experience_years,
            "education": self.education,
            "bio": self.bio,
            "current_funds": self.current_funds,
            "history_tenures": self.history_tenures,
            "tenure_weighted_alpha": self.tenure_weighted_alpha,
            "managed_scale": self.managed_scale,
            "style_stability": self.style_stability,
            "peer_rank": self.peer_rank,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


def _tenure_weight_days(tenure: FundManagerTenure) -> float:
    """任职加权：tenure_days 优先，缺失按现任=365 天/离任=180 天兜底。"""
    if tenure.tenure_days:
        return float(tenure.tenure_days)
    return 365.0 if tenure.is_current else 180.0


def _one_year_return(fund_ret: pd.Series) -> float | None:
    if len(fund_ret) < 20:
        return None
    recent = fund_ret.tail(252)
    return float((1.0 + recent).prod() - 1.0)


def build_manager_profile(db: Session, manager_id: str) -> ManagerProfile | None:
    """聚合单一经理的在管/历任基金画像；经理不存在返回 None。"""
    manager = db.scalar(select(FundManager).where(FundManager.manager_id == manager_id))
    if manager is None:
        return None

    profile = ManagerProfile(
        manager_id=manager.manager_id,
        name=manager.name,
        experience_years=manager.experience_years,
        education=manager.education,
        bio=manager.bio,
    )

    tenures = list(
        db.scalars(
            select(FundManagerTenure)
            .where(FundManagerTenure.manager_id == manager_id)
            .order_by(FundManagerTenure.start_date.desc())
        ).all()
    )
    current = [t for t in tenures if t.is_current and t.end_date is None]
    profile.history_tenures = [
        {
            "fund_code": t.fund_code,
            "start_date": str(t.start_date),
            "end_date": str(t.end_date) if t.end_date else None,
            "tenure_days": t.tenure_days,
            "tenure_return": t.tenure_return,
        }
        for t in tenures
        if not (t.is_current and t.end_date is None)
    ]
    if not current:
        profile.warnings.append("无现任在管基金，画像仅含历任记录")

    fund_codes = [t.fund_code for t in current]
    funds = {
        f.fund_code: f
        for f in db.scalars(select(FundMain).where(FundMain.fund_code.in_(fund_codes))).all()
    } if fund_codes else {}

    # 1. 任期加权 alpha（Jensen 口径对沪深300）
    bench_ret = load_benchmark_return_series(db, SPECTRUM_BENCHMARK_SYMBOL)
    alpha_by_fund: dict[str, float | None] = {}
    if not bench_ret.empty and fund_codes:
        ab_map = compute_fund_alpha_beta_map(db, fund_codes, bench_ret)
        alpha_by_fund = {code: ab["alpha_annualized"] for code, ab in ab_map.items()}

    weighted_sum = 0.0
    weight_total = 0.0
    for tenure in current:
        scale = _latest_scale(db, tenure.fund_code)
        alpha = alpha_by_fund.get(tenure.fund_code)
        fund = funds.get(tenure.fund_code)
        profile.current_funds.append({
            "fund_code": tenure.fund_code,
            "fund_name": getattr(fund, "short_name", None) if fund else None,
            "family": fund_family_of(fund) if fund else None,
            "start_date": str(tenure.start_date),
            "tenure_days": tenure.tenure_days,
            "alpha_annualized": alpha,
            "scale": scale,
        })
        if alpha is not None:
            days = _tenure_weight_days(tenure)
            weighted_sum += alpha * days
            weight_total += days

    profile.tenure_weighted_alpha = weighted_sum / weight_total if weight_total > 0 else None
    if current and profile.tenure_weighted_alpha is None:
        profile.warnings.append("在管基金 alpha 均不可计算（净值/基准序列不足）")

    # 2. 管理规模（在管基金最新规模合计）
    scales = [f["scale"] for f in profile.current_funds if f["scale"] is not None]
    profile.managed_scale = round(float(sum(scales)), 2) if scales else None

    # 3. 风格稳定性（复用 anomaly.detect_style_drift，需 ≥4 期风格暴露历史）
    drifted: list[dict] = []
    evaluable = 0
    for code in fund_codes:
        exposure_count = db.scalar(_style_exposure_count_stmt(code)) or 0
        if exposure_count < 4:
            continue
        evaluable += 1
        item = detect_style_drift(db, code)
        if item is not None:
            drifted.append({
                "fund_code": code,
                "dimensions": (item.detail or {}).get("drifted_dimensions", []),
            })
    profile.style_stability = {
        "drifted_funds": drifted,
        "evaluable_funds": evaluable,
        "current_fund_count": len(fund_codes),
        "stable": not drifted,
    }
    if fund_codes and evaluable == 0:
        profile.warnings.append("在管基金风格暴露历史均不足 4 期，风格稳定性不可评估")

    # 4. 同类排名中位数（rank.py 口径：近一年收益同 sub_category 排名）
    ranks: list[dict] = []
    all_funds = list(db.scalars(select(FundMain)).all())
    return_cache: dict[str, float | None] = {}

    def fund_1y_return(code: str) -> float | None:
        if code not in return_cache:
            return_cache[code] = _one_year_return(load_fund_return_series(db, code))
        return return_cache[code]

    for tenure in current:
        fund = funds.get(tenure.fund_code)
        if fund is None or not fund.sub_category:
            continue
        peers = {
            f.fund_code: fund_1y_return(f.fund_code)
            for f in all_funds
            if f.sub_category == fund.sub_category
        }
        peers = {code: value for code, value in peers.items() if value is not None}
        rank_result = rank_in_category(
            peers, tenure.fund_code, sub_category=fund.sub_category
        )
        if rank_result is not None:
            ranks.append(rank_result.to_data())
    percentiles = [r["percentile"] for r in ranks if r["percentile"] is not None]
    profile.peer_rank = {
        "ranks": ranks,
        "median_percentile": float(median(percentiles)) if percentiles else None,
    }

    # 5. 结论状态
    if not current or profile.tenure_weighted_alpha is None:
        profile.conclusion_status = ConclusionStatus.OBSERVATION.value
    return profile


def _style_exposure_count_stmt(fund_code: str):
    from sqlalchemy import func

    return (
        select(func.count(StyleExposureResult.id))
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == "style",
        )
    )


def list_manager_summaries(db: Session) -> list[dict]:
    """全部经理概览（经理画像列表页数据源）。"""
    managers = list(db.scalars(select(FundManager).order_by(FundManager.name)).all())
    tenures = list(db.scalars(select(FundManagerTenure)).all())
    current_by_manager: dict[str, list[FundManagerTenure]] = {}
    for tenure in tenures:
        if tenure.is_current and tenure.end_date is None:
            current_by_manager.setdefault(tenure.manager_id, []).append(tenure)

    bench_ret = load_benchmark_return_series(db, SPECTRUM_BENCHMARK_SYMBOL)
    all_codes = sorted({t.fund_code for ts in current_by_manager.values() for t in ts})
    alpha_beta_map = (
        compute_fund_alpha_beta_map(db, all_codes, bench_ret)
        if not bench_ret.empty and all_codes
        else {}
    )

    summaries: list[dict] = []
    for manager in managers:
        current = current_by_manager.get(manager.manager_id, [])
        if not current:
            continue  # 无在管基金的经理不入列表（历史人物无画像意义）
        weighted_sum = 0.0
        weight_total = 0.0
        scale_total = 0.0
        for tenure in current:
            alpha = alpha_beta_map.get(tenure.fund_code, {}).get("alpha_annualized")
            if alpha is not None:
                days = _tenure_weight_days(tenure)
                weighted_sum += alpha * days
                weight_total += days
            scale = _latest_scale(db, tenure.fund_code)
            if scale is not None:
                scale_total += scale
        summaries.append({
            "manager_id": manager.manager_id,
            "name": manager.name,
            "experience_years": manager.experience_years,
            "current_fund_count": len(current),
            "current_fund_codes": sorted({t.fund_code for t in current}),
            "tenure_weighted_alpha": weighted_sum / weight_total if weight_total > 0 else None,
            "managed_scale": round(scale_total, 2) if scale_total > 0 else None,
        })
    summaries.sort(
        key=lambda s: (s["tenure_weighted_alpha"] is None, -(s["tenure_weighted_alpha"] or 0.0))
    )
    return summaries
