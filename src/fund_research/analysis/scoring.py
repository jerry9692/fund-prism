"""
Composite fund scoring with configurable weights and IC backtest.

Methodology:
- Within-category Z-score / percentile standardization
- Configurable 8-dimension weights with presets
- Winsorize extremes (1%/99%)
- Missing data penalty
- IC rank validation

References:
- Morningstar Fund Rating Methodology
- Grinold & Kahn: Active Portfolio Management (IC analysis)
"""

from dataclasses import dataclass, field

import pandas as pd

ALGORITHM_NAME = "composite_scoring"
ALGORITHM_VERSION = "0.1.0"

# 8 scoring dimensions with default weights (偏长期稳健)
DEFAULT_WEIGHTS = {
    "return": 0.20,       # 收益能力
    "risk": 0.20,         # 风险控制
    "alpha": 0.15,        # Alpha 能力
    "trading": 0.05,      # 交易能力 (estimated → weight × 0.5)
    "style_stability": 0.15,  # 风格稳定性
    "scale": 0.10,        # 规模适配
    "team": 0.10,         # 团队稳定性
    "holder": 0.05,       # 持有人稳定性
}

PRESET_WEIGHTS = {
    "稳健型": {
        "return": 0.15, "risk": 0.25, "alpha": 0.10, "trading": 0.05,
        "style_stability": 0.15, "scale": 0.15, "team": 0.10, "holder": 0.05,
    },
    "均衡型": DEFAULT_WEIGHTS,
    "进取型": {
        "return": 0.30, "risk": 0.15, "alpha": 0.20, "trading": 0.10,
        "style_stability": 0.05, "scale": 0.10, "team": 0.05, "holder": 0.05,
    },
}


@dataclass
class FundScore:
    """Single fund scoring result."""

    fund_code: str
    total_score: float  # 0-100
    sub_scores: dict[str, float]  # dimension → score
    percentile_rank: float  # within category
    deduction_reasons: list[str] = field(default_factory=list)
    contains_estimated: bool = False
    sample_years: float | None = None

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "total_score": round(self.total_score, 2),
            "sub_scores": {k: round(v, 2) for k, v in self.sub_scores.items()},
            "percentile_rank": round(self.percentile_rank, 4),
            "deduction_reasons": self.deduction_reasons,
            "contains_estimated": self.contains_estimated,
            "sample_years": round(self.sample_years, 1) if self.sample_years is not None else None,
        }


@dataclass
class ScoringResult:
    """Full scoring run output."""

    score_version: str
    weight_config: dict[str, float]
    fund_scores: list[FundScore]
    category: str = ""
    fund_count: int = 0
    ic_summary: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def to_api_data(self) -> dict:
        return {
            "score_version": self.score_version,
            "weight_config": self.weight_config,
            "category": self.category,
            "fund_count": self.fund_count,
            "fund_scores": [fs.to_dict() for fs in self.fund_scores],
            "ic_summary": self.ic_summary,
            "warnings": self.warnings,
        }


# ============================================================
# Standardization
# ============================================================


def winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Winsorize extreme values."""
    lo, hi = series.quantile(lower), series.quantile(upper)
    return series.clip(lo, hi)


def standardize_zscore(series: pd.Series) -> pd.Series:
    """Z-score standardization."""
    std = series.std()
    if pd.isna(std) or std == 0:
        result = pd.Series(pd.NA, index=series.index, dtype="Float64")
        result.loc[series.dropna().index] = 0.0
        return result
    return (series - series.mean()) / std


def to_percentile(series: pd.Series) -> pd.Series:
    """Convert to percentile rank (0-1)."""
    valid = series.dropna()
    if valid.nunique() <= 1:
        result = pd.Series(pd.NA, index=series.index, dtype="Float64")
        result.loc[valid.index] = 0.5
        return result
    return series.rank(pct=True)


# ============================================================
# Scoring
# ============================================================


def score_funds(
    fund_metrics: pd.DataFrame,
    # Columns: [fund_code] + 8 dimension columns
    # All dimension values should be oriented so that "higher = better"
    *,
    weights: dict[str, float] | None = None,
    preset: str | None = None,
    category: str = "",
    contains_estimated: set[str] | None = None,
    sample_years_map: dict[str, float] | None = None,
    allow_estimated: bool = False,
) -> ScoringResult:
    """
    Compute composite scores for a set of funds.

    Steps:
    1. Winsorize each dimension (1%/99%)
    2. Z-score standardize within the fund set
    3. Convert to percentile
    4. Weighted sum → total score
    5. Exclude estimated dimensions by default; optionally down-weight them
    6. Penalize missing data and short history

    fund_metrics columns should include 'fund_code' plus dimension columns
    matching the weight keys.
    """
    if weights is None and preset:
        weights = PRESET_WEIGHTS.get(preset)
    if weights is None:
        weights = DEFAULT_WEIGHTS

    warnings: list[str] = []
    contains_estimated = contains_estimated or set()
    sample_years_map = sample_years_map or {}

    if fund_metrics.empty:
        return ScoringResult(
            score_version=ALGORITHM_VERSION,
            weight_config=weights,
            fund_scores=[],
            category=category,
            warnings=["指标数据为空"],
        )

    data = fund_metrics.copy().set_index("fund_code")
    dims = [d for d in weights if d in data.columns]
    if not dims:
        return ScoringResult(
            score_version=ALGORITHM_VERSION,
            weight_config=weights,
            fund_scores=[],
            category=category,
            warnings=["没有可用的评分维度"],
        )

    missing_dims = [d for d in weights if d not in data.columns]
    if missing_dims:
        warnings.append(f"缺少评分维度: {', '.join(missing_dims)}")

    # Step 1-3: Winsorize → Z-score → Percentile
    scores_df = pd.DataFrame(index=data.index)
    for dim in dims:
        col = data[dim].astype(float)
        w = winsorize(col)
        z = standardize_zscore(w)
        pct = to_percentile(z)
        scores_df[dim] = pct

    # Step 4-5: Weighted sum
    fund_scores: list[FundScore] = []
    for fund_code in scores_df.index:
        sub: dict[str, float] = {}
        total = 0.0
        deductions: list[str] = []
        has_est = False

        for dim in dims:
            w = weights.get(dim, 0.0)
            if dim in contains_estimated:
                has_est = True
                if allow_estimated:
                    w *= 0.5  # estimated indicator → half weight
                    deductions.append(f"{dim} 含估计成分，权重减半")
                else:
                    sub[dim] = 0.0
                    deductions.append(f"{dim} 含未验证估计成分，默认评分剔除")
                    continue

            raw = scores_df.loc[fund_code, dim]
            if pd.isna(raw):
                total -= w * 100 * 0.05  # 5% of this dimension's score budget
                sub[dim] = 0.0
                deductions.append(f"{dim} 数据缺失")
            else:
                score = raw * w * 100
                total += score
                sub[dim] = round(score, 2)

        # Sample period penalty
        years = sample_years_map.get(fund_code) if sample_years_map else None
        if years is not None and years < 3.0:
            total *= max(0.5, years / 3.0)
            deductions.append(f"样本期仅 {years:.1f} 年，<3 年降权")

        # Clamp to 0-100
        total = max(0.0, min(100.0, total))

        fund_scores.append(FundScore(
            fund_code=fund_code,
            total_score=round(total, 2),
            sub_scores=sub,
            percentile_rank=0.0,  # filled after sort
            deduction_reasons=deductions,
            contains_estimated=has_est,
            sample_years=years,
        ))

    # Sort and assign percentile ranks
    fund_scores.sort(key=lambda x: x.total_score, reverse=True)
    n = len(fund_scores)
    for i, fs in enumerate(fund_scores):
        fs.percentile_rank = round(1.0 - i / max(n - 1, 1), 4)

    return ScoringResult(
        score_version=ALGORITHM_VERSION,
        weight_config=weights,
        fund_scores=fund_scores,
        category=category,
        fund_count=n,
        warnings=warnings,
    )


# ============================================================
# IC Backtest
# ============================================================


def compute_ic(
    scores: pd.DataFrame,
    # columns: [fund_code, calc_date, score]
    future_returns: pd.DataFrame,
    # columns: [fund_code, calc_date, future_return]
) -> dict:
    """
    Compute rank IC between scores at calc_date and subsequent future returns.

    Returns IC mean, IC_IR, and stratified return monotonicity.
    """
    if scores.empty or future_returns.empty:
        return {"ic_mean": None, "ic_ir": None, "monotonicity": None, "warnings": ["回测数据不足"]}

    merged = scores.merge(future_returns, on=["fund_code", "calc_date"], how="inner")
    if len(merged) < 10:
        return {"ic_mean": None, "ic_ir": None, "monotonicity": None, "warnings": ["回测样本不足"]}

    ics = merged.groupby("calc_date").apply(
        lambda g: g["score"].corr(g["future_return"], method="spearman"),
        include_groups=False,
    ).dropna()

    ic_mean = float(ics.mean()) if len(ics) > 0 else None
    ic_ir = float(ics.mean() / ics.std()) if len(ics) > 0 and ics.std() > 0 else None

    # Stratified monotonicity by calc_date, then aggregate each score bucket.
    def _bucket(date_group: pd.DataFrame) -> pd.Series:
        if date_group["score"].nunique() < 2:
            return pd.Series([pd.NA] * len(date_group), index=date_group.index)
        return pd.qcut(
            date_group["score"].rank(method="first"),
            5,
            labels=False,
            duplicates="drop",
        )

    merged["group"] = merged.groupby("calc_date", group_keys=False).apply(_bucket, include_groups=False)
    grouped = merged.dropna(subset=["group"]).copy()
    group_returns = grouped.groupby("group")["future_return"].mean()
    monotonic = (
        group_returns.is_monotonic_increasing and group_returns.iloc[-1] > group_returns.iloc[0]
        if len(group_returns) >= 2
        else False
    )

    return {
        "ic_mean": round(ic_mean, 6) if ic_mean is not None else None,
        "ic_ir": round(ic_ir, 4) if ic_ir is not None else None,
        "monotonicity": bool(monotonic),
        "group_returns": {str(k): round(float(v), 6) for k, v in group_returns.to_dict().items()},
        "ic_count": len(ics),
        "warnings": [],
    }
