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
from math import erfc, sqrt

import pandas as pd

ALGORITHM_NAME = "composite_scoring"

# 8 scoring dimensions with default weights per requirements doc v0.1 §5.3.3:
#   return=20%, risk=20%, alpha=15%, trading=5%, style=15%, scale=10%, team=10%, holder=5%
# NOTE: trading is an estimated dimension; its effective weight is halved to 2.5%
# when allow_estimated=True (per v0.4 estimated-isolation principle).
#
# Weight adjustments from IC diagnostics are tracked via preset profiles, not
# by silently changing the default. The default MUST match the product spec so
# that API consumers see documented behavior; empirical IC-driven adjustments
# are opt-in via preset or custom weights.
DEFAULT_WEIGHTS = {
    "return": 0.20,            # 收益能力 — 长期年化收益、超额收益、胜率
    "risk": 0.20,              # 风险控制 — 最大回撤、波动率、下行风险
    "alpha": 0.15,             # Alpha 能力 — 选股收益、行业配置收益
    "trading": 0.05,           # 交易能力 (estimated) — 换手效率；estimated 半权后实际 2.5%
    "style_stability": 0.15,   # 风格稳定性 — 风格漂移、合同偏离
    "scale": 0.10,             # 规模适配 — 规模过小/过大风险
    "team": 0.10,              # 团队稳定性 — 基金经理任职、共管变化
    "holder": 0.05,            # 持有人稳定性 — 机构集中度、申赎压力
}

# Dynamic weight redistribution for uniformly-absent dimensions (v0.3+):
# When a dimension is NaN for ALL funds, its weight is redistributed
# proportionally to dimensions that have data.
ALGORITHM_VERSION = "0.5.0"

# Preset profiles — opt-in weight configurations for different investor styles.
# These are documented alternatives to the default; the default remains aligned
# with the requirements spec.
PRESET_WEIGHTS = {
    "均衡型": DEFAULT_WEIGHTS,
    "稳健型": {
        "return": 0.15, "risk": 0.30, "alpha": 0.10, "trading": 0.05,
        "style_stability": 0.15, "scale": 0.10, "team": 0.10, "holder": 0.05,
    },
    "进取型": {
        "return": 0.25, "risk": 0.15, "alpha": 0.20, "trading": 0.05,
        "style_stability": 0.10, "scale": 0.10, "team": 0.10, "holder": 0.05,
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

    # v0.3: Dynamic weight redistribution for uniformly-absent dimensions.
    # If a dimension is NaN for ALL funds in the scoring set (e.g. alpha/
    # scale/team/holder have no historical data source), redistribute its
    # weight proportionally to dimensions that have at least one non-NaN
    # value. This ensures the score is driven by real differentiators
    # rather than a flat 5% missing-data penalty.
    effective_weights = dict(weights)
    for dim in dims:
        if data[dim].isna().all():
            freed_weight = effective_weights.pop(dim, 0.0)
            if freed_weight > 0:
                available_dims = [d for d in dims if d != dim and not data[d].isna().all()]
                total_available = sum(effective_weights.get(d, 0.0) for d in available_dims)
                if total_available > 0:
                    for d in available_dims:
                        effective_weights[d] = effective_weights.get(d, 0.0) + freed_weight * (
                            effective_weights.get(d, 0.0) / total_available
                        )
                warnings.append(
                    f"维度 {dim} 在全部基金中无数据，权重 {freed_weight:.2f} 已重分配至可用维度"
                )

    # Step 1-3: Winsorize → Z-score → Percentile
    scores_df = pd.DataFrame(index=data.index)
    for dim in dims:
        if dim not in effective_weights:
            continue
        col = data[dim].astype(float)
        w = winsorize(col)
        z = standardize_zscore(w)
        pct = to_percentile(z)
        scores_df[dim] = pct

    # Step 4-5: Weighted sum
    # contains_estimated reflects the scoring configuration: if any of the
    # original dimensions (before dynamic weight redistribution) were marked
    # estimated, the result carries the estimated flag even when those
    # dimensions were removed for having no data. This keeps the API
    # warning ("评分包含 estimated 维度") truthful to the configuration.
    config_has_estimated = any(dim in contains_estimated for dim in dims)
    fund_scores: list[FundScore] = []
    for fund_code in scores_df.index:
        sub: dict[str, float] = {}
        total = 0.0
        deductions: list[str] = []
        has_est = config_has_estimated

        for dim in dims:
            if dim not in effective_weights:
                continue
            w = effective_weights.get(dim, 0.0)
            if dim in contains_estimated:
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
        weight_config=effective_weights,
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

    grouped_metrics = compute_grouped_forward_metrics(merged)
    group_returns = grouped_metrics["group_metrics"].get("future_return", {})

    return {
        "ic_mean": round(ic_mean, 6) if ic_mean is not None else None,
        "ic_ir": round(ic_ir, 4) if ic_ir is not None else None,
        "monotonicity": grouped_metrics["monotonicity_checks"].get("future_return"),
        "group_returns": group_returns,
        "group_metrics": grouped_metrics["group_metrics"],
        "monotonicity_checks": grouped_metrics["monotonicity_checks"],
        "top_bottom_tests": grouped_metrics["top_bottom_tests"],
        "group_curves": grouped_metrics["group_curves"],
        "ic_count": len(ics),
        "warnings": [],
    }


def compute_scoring_backtest(
    scores: pd.DataFrame,
    future_returns: pd.DataFrame,
    *,
    group_count: int = 5,
    min_samples: int = 2,
) -> dict:
    """Compute a compact, multi-metric scoring backtest summary.

    A convenience entry point that bundles rank IC, score-bucketed forward
    metrics, return monotonicity, and a top-minus-bottom one-sided sign test.
    Unlike :func:`compute_ic`, this function does not impose a minimum sample
    floor so it can be used for small validation samples.

    ``scores`` columns: fund_code, calc_date, score.
    ``future_returns`` columns: fund_code, calc_date, plus any of
    ``future_return`` / ``future_max_drawdown`` / ``future_sharpe``.
    """
    empty = {
        "sample_count": 0,
        "ic_mean": None,
        "ic_ir": None,
        "monotonicity": None,
        "group_returns": {},
        "group_results": {},
        "monotonicity_by_metric": {},
        "top_bottom_return_spread": None,
        "top_bottom_one_sided_p_value": None,
        "group_count": 0,
        "warnings": ["backtest data is empty"],
    }
    if scores.empty or future_returns.empty:
        return empty

    merged = scores.merge(future_returns, on=["fund_code", "calc_date"], how="inner")
    if len(merged) < min_samples:
        return {
            **empty,
            "sample_count": int(len(merged)),
            "warnings": [f"backtest sample too small: {len(merged)}/{min_samples}"],
        }

    # Rank IC per evaluation date (Spearman between score and future return).
    ics = (
        merged.groupby("calc_date")
        .apply(lambda g: g["score"].corr(g["future_return"], method="spearman"))
        .dropna()
    )
    ic_mean = float(ics.mean()) if len(ics) > 0 else None
    ic_std = float(ics.std()) if len(ics) > 1 else 0.0
    ic_ir = float(ics.mean() / ic_std) if ic_std > 0 else None

    # Score-bucket each evaluation date into at most ``group_count`` quantiles.
    def _bucket(date_group: pd.DataFrame) -> pd.Series:
        if date_group["score"].nunique() < 2:
            return pd.Series([pd.NA] * len(date_group), index=date_group.index)
        return pd.qcut(
            date_group["score"].rank(method="first"),
            min(group_count, len(date_group)),
            labels=False,
            duplicates="drop",
        )

    merged["group"] = pd.NA
    for _calc_date, date_group in merged.groupby("calc_date"):
        merged.loc[date_group.index, "group"] = _bucket(date_group)
    grouped = merged.dropna(subset=["group"]).copy()

    metric_columns = [
        column
        for column in ("future_return", "future_max_drawdown", "future_sharpe")
        if column in grouped.columns
    ]
    # First key = score bucket, second key = metric. Every forward metric is
    # expected to rise with the score (drawdown is stored as a signed value,
    # so a smaller loss is a larger, i.e. better, number).
    group_results: dict[str, dict[str, float]] = {}
    monotonicity_by_metric: dict[str, bool | None] = {}
    metric_by_group: dict[str, dict[str, float]] = {column: {} for column in metric_columns}
    for column in metric_columns:
        series = grouped.groupby("group")[column].mean().dropna()
        for k, value in series.to_dict().items():
            metric_by_group[column][str(int(k))] = round(float(value), 6)
        if len(series) >= 2:
            if column == "future_max_drawdown":
                # Max drawdown may be stored as either:
                #   (a) positive magnitude (e.g. 0.20 = 20% drawdown; smaller = better)
                #       → should be monotonic decreasing with score, or
                #   (b) signed negative return (e.g. -0.20; less negative = better)
                #       → should be monotonic increasing with score.
                # Detect convention by the sign of the bottom-group mean.
                if series.iloc[0] > 0:
                    monotonicity_by_metric[column] = bool(
                        series.is_monotonic_decreasing and series.iloc[-1] < series.iloc[0]
                    )
                else:
                    monotonicity_by_metric[column] = bool(
                        series.is_monotonic_increasing and series.iloc[-1] > series.iloc[0]
                    )
            else:
                # future_return and future_sharpe: higher = better → monotonic increasing.
                monotonicity_by_metric[column] = bool(
                    series.is_monotonic_increasing and series.iloc[-1] > series.iloc[0]
                )
        else:
            monotonicity_by_metric[column] = None
    for bucket in sorted({bucket for values in metric_by_group.values() for bucket in values}):
        group_results[bucket] = {
            column: values[bucket]
            for column, values in metric_by_group.items()
            if bucket in values
        }

    group_returns = metric_by_group.get("future_return", {})

    # Top-minus-bottom one-sided sign test across evaluation dates.
    spreads: list[float] = []
    for _calc_date, frame in merged.groupby("calc_date"):
        frame = frame.dropna(subset=["group", "future_return"])
        if frame.empty:
            continue
        bottom = frame.loc[frame["group"].idxmin(), "future_return"]
        top = frame.loc[frame["group"].idxmax(), "future_return"]
        spreads.append(float(top) - float(bottom))
    spread_mean = float(pd.Series(spreads).mean()) if spreads else None
    one_sided_p_value = _sign_test_positive_p_value(spreads)

    return {
        "sample_count": int(len(merged)),
        "ic_mean": round(ic_mean, 6) if ic_mean is not None else None,
        "ic_ir": round(ic_ir, 4) if ic_ir is not None else None,
        "monotonicity": monotonicity_by_metric.get("future_return"),
        "group_returns": group_returns,
        "group_results": group_results,
        "monotonicity_by_metric": monotonicity_by_metric,
        "top_bottom_return_spread": round(spread_mean, 6) if spread_mean is not None else None,
        "top_bottom_one_sided_p_value": round(float(one_sided_p_value), 6)
        if one_sided_p_value is not None
        else None,
        "group_count": len(group_returns),
        "warnings": [],
    }


def _sign_test_positive_p_value(spreads: list[float]) -> float | None:
    """One-sided sign-test p-value that the top score bucket beats the bottom.

    Counts periods where the top-minus-bottom spread is positive and returns
    ``P(X >= positives | n, p=0.5)`` under the binomial null. With a single
    positive period this is 0.5, matching the documented sign-test semantics.
    """
    clean = [float(value) for value in spreads if value is not None]
    n = len(clean)
    if n == 0:
        return None
    positives = sum(1 for value in clean if value > 0)
    # Binomial tail P(X >= positives | n, 0.5) = sum_{k=positives..n} C(n,k) / 2^n.
    from math import comb

    tail = sum(comb(n, k) for k in range(positives, n + 1)) / (2 ** n)
    return float(tail)


def compute_grouped_forward_metrics(merged: pd.DataFrame, group_count: int = 5) -> dict:
    """Compute score-bucket forward metrics and monotonicity checks.

    `future_return` and `future_sharpe` should rise with score. `future_max_drawdown`
    is stored as a positive drawdown magnitude, so it should fall with score.
    """
    required = {"fund_code", "calc_date", "score"}
    if merged.empty or not required.issubset(merged.columns):
        return {
            "group_metrics": {},
            "monotonicity_checks": {},
            "top_bottom_tests": {},
            "group_curves": {},
        }

    data = merged.copy()

    def _bucket(date_group: pd.DataFrame) -> pd.Series:
        if date_group["score"].nunique() < 2:
            return pd.Series([pd.NA] * len(date_group), index=date_group.index)
        return pd.qcut(
            date_group["score"].rank(method="first"),
            group_count,
            labels=False,
            duplicates="drop",
        )

    data["group"] = data.groupby("calc_date", group_keys=False).apply(
        _bucket,
        include_groups=False,
    )
    grouped = data.dropna(subset=["group"]).copy()
    if grouped.empty:
        return {
            "group_metrics": {},
            "monotonicity_checks": {},
            "top_bottom_tests": {},
            "group_curves": {},
        }

    metric_columns = [
        column
        for column in ("future_return", "future_max_drawdown", "future_sharpe")
        if column in grouped.columns
    ]
    group_metrics: dict[str, dict[str, float]] = {}
    monotonicity_checks: dict[str, bool] = {}
    top_bottom_tests: dict[str, dict[str, float | int | bool | None]] = {}
    group_curves: dict[str, dict[str, list[dict[str, float | str]]]] = {}
    for column in metric_columns:
        series = grouped.groupby("group")[column].mean().dropna()
        values = {str(int(k)): round(float(v), 6) for k, v in series.to_dict().items()}
        group_metrics[column] = values
        if len(series) >= 2:
            if column == "future_max_drawdown":
                # See comment in compute_scoring_backtest: support both positive
                # magnitudes and signed-negative drawdown values.
                if series.iloc[0] > 0:
                    monotonicity_checks[column] = bool(
                        series.is_monotonic_decreasing and series.iloc[-1] < series.iloc[0]
                    )
                else:
                    monotonicity_checks[column] = bool(
                        series.is_monotonic_increasing and series.iloc[-1] > series.iloc[0]
                    )
            else:
                monotonicity_checks[column] = bool(
                    series.is_monotonic_increasing and series.iloc[-1] > series.iloc[0]
                )
        else:
            monotonicity_checks[column] = False

        if column == "future_return":
            by_date_group = (
                grouped.groupby(["calc_date", "group"])[column]
                .mean()
                .reset_index()
                .sort_values(["calc_date", "group"])
            )
            top_bottom_tests[column] = _top_bottom_one_sided_test(by_date_group)
            group_curves[column] = _group_return_curves(by_date_group)

    return {
        "group_metrics": group_metrics,
        "monotonicity_checks": monotonicity_checks,
        "top_bottom_tests": top_bottom_tests,
        "group_curves": group_curves,
    }


def _top_bottom_one_sided_test(grouped_returns: pd.DataFrame) -> dict[str, float | int | bool | None]:
    """Test whether top score bucket future return beats bottom bucket."""
    if grouped_returns.empty:
        return {"spread_mean": None, "one_sided_p_value": None, "period_count": 0, "passed": False}

    spreads: list[float] = []
    for _calc_date, frame in grouped_returns.groupby("calc_date"):
        frame = frame.dropna(subset=["group", "future_return"])
        if frame.empty:
            continue
        bottom = frame.loc[frame["group"].idxmin(), "future_return"]
        top = frame.loc[frame["group"].idxmax(), "future_return"]
        spreads.append(float(top) - float(bottom))

    if not spreads:
        return {"spread_mean": None, "one_sided_p_value": None, "period_count": 0, "passed": False}

    spread_series = pd.Series(spreads, dtype="float64")
    spread_mean = float(spread_series.mean())
    p_value = _one_sided_positive_p_value(spread_series)
    return {
        "spread_mean": round(spread_mean, 6),
        "one_sided_p_value": round(float(p_value), 6) if p_value is not None else None,
        "period_count": int(len(spread_series)),
        "passed": bool(spread_mean > 0 and (p_value is None or p_value <= 0.10)),
    }


def _one_sided_positive_p_value(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 2:
        return None
    std = float(clean.std(ddof=1))
    if std == 0:
        return 0.0 if float(clean.mean()) > 0 else 1.0
    t_stat = float(clean.mean()) / (std / sqrt(len(clean)))
    try:
        from scipy import stats

        return float(stats.t.sf(t_stat, df=len(clean) - 1))
    except Exception:
        return 0.5 * erfc(t_stat / sqrt(2.0))


def _group_return_curves(grouped_returns: pd.DataFrame) -> dict[str, list[dict[str, float | str]]]:
    """Build cumulative future-return curves for score buckets."""
    curves: dict[str, list[dict[str, float | str]]] = {}
    if grouped_returns.empty:
        return curves

    for group, frame in grouped_returns.groupby("group"):
        cumulative = 1.0
        points: list[dict[str, float | str]] = []
        for row in frame.sort_values("calc_date").itertuples(index=False):
            period_return = float(row.future_return)
            cumulative *= 1.0 + period_return
            points.append({
                "calc_date": str(row.calc_date),
                "period_return": round(period_return, 6),
                "cumulative_return": round(cumulative - 1.0, 6),
            })
        curves[str(int(group))] = points
    return curves
