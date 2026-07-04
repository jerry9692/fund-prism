"""
Dynamic multi-period return attribution using the Brinson model.

This module implements multi-period Brinson attribution (BHB/BF) with
Carino (1999) logarithmic smoothing. It serves as the enhanced static-
attribution backbone for Phase 2. Full dynamic attribution (monthly
rebalancing simulation, IPO returns, convertible-bond returns) is
tracked as future work; the current implementation correctly computes
sector allocation / stock selection / interaction effects from disclosed
holdings and real market/benchmark returns, and enforces a residual-ratio
gate per requirements v0.4 §5.2.3.

References:
- Brinson, Hood & Beebower (1986): Determinants of Portfolio Performance
- Brinson & Fachler (1985): Measuring Non-US Equity Portfolio Performance
- Carino (1999): Combining Attribution Effects Over Time

Supports both BHB and BF decomposition methods via the ``method`` parameter.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from math import log

import pandas as pd

ALGORITHM_NAME = "dynamic_attribution"
ALGORITHM_VERSION = "0.2.0"

# Residual ratio threshold per requirements §5.2.3:
# residual / active_return > 50% → result is marked needs_review.
MAX_RESIDUAL_RATIO = 0.50


@dataclass
class AttributionPeriod:
    """Single period attribution result."""

    period_start: date
    period_end: date
    portfolio_return: float
    benchmark_return: float
    allocation_effect: float  # sector allocation contribution
    selection_effect: float  # stock selection contribution
    interaction_effect: float  # cross term (BHB) or 0 (BF)
    residual: float
    sector_details: list[dict] = field(default_factory=list)
    uses_simulated_holdings: bool = False
    # True when this period uses simulated (estimated) holdings instead of
    # real disclosed holdings; controls field-name prefix in to_api_data().
    # [{sector, port_weight, bench_weight, port_return, bench_return,
    #   allocation, selection, interaction}]


@dataclass
class AttributionResult:
    """Multi-period attribution with Carino smoothing."""

    fund_code: str
    periods: list[AttributionPeriod]
    total_portfolio_return: float
    total_benchmark_return: float
    total_allocation_effect: float
    total_selection_effect: float
    total_interaction_effect: float
    total_residual: float
    total_ipo_return: float = 0.0  # reserved for future IPO return estimation
    total_convertible_bond_return: float = 0.0  # reserved for future CB return estimation
    total_invisible_return: float = 0.0  # residual - ipo - cb (truly unexplained)
    residual_ratio: float = 0.0  # |residual| / |active_return|
    method: str = "BHB"
    confidence: str = "medium"
    warnings: list[str] = field(default_factory=list)
    uses_simulated_holdings: bool = False
    # True when the attribution was computed using simulated (estimated)
    # holdings; when False, inputs are real disclosed holdings + real market
    # data, so base return / attribution-effect fields are "computed" level
    # and do NOT carry the estimated_ prefix. Residual fields are always
    # estimated regardless.

    @property
    def waterfall_data(self) -> list[dict]:
        """Period-by-period return decomposition suitable for waterfall charts.

        Each entry contains the full set of return components for one
        attribution period, including equity Brinson effects (stock selection,
        asset allocation, interaction) plus placeholders for bond/cash/IPO/
        convertible-bond returns that are not yet decomposed at the period
        level. ``estimated_invisible_return`` carries the per-period residual
        that cannot be attributed to known sources.

        Warnings:
            - ``estimated_ipo_return`` and ``estimated_convertible_bond_return``
              are initialized to 0.0 as estimated placeholders; full IPO/CB
              return decomposition is reserved for future work.
            - ``bond_return`` and ``cash_return`` are also 0.0 in the current
              equity-only Brinson implementation.
        """
        waterfall: list[dict] = []
        for p in self.periods:
            period_label = f"{p.period_start}~{p.period_end}"
            excess = p.portfolio_return - p.benchmark_return
            # Equity Brinson effects
            stock_selection = p.selection_effect
            asset_allocation = p.allocation_effect
            interaction = p.interaction_effect
            # Fixed-income / cash not yet decomposed per-period (equity-only Brinson)
            bond_return = 0.0
            cash_return = 0.0
            # IPO and convertible-bond returns are estimated placeholders (0.0)
            estimated_ipo_return = 0.0
            estimated_convertible_bond_return = 0.0
            # Invisible (unexplained) return = per-period residual
            estimated_invisible_return = p.residual
            waterfall.append({
                "period_label": period_label,
                "stock_selection": round(stock_selection, 6),
                "asset_allocation": round(asset_allocation, 6),
                "interaction": round(interaction, 6),
                "bond_return": round(bond_return, 6),
                "cash_return": round(cash_return, 6),
                "estimated_ipo_return": round(estimated_ipo_return, 6),
                "estimated_convertible_bond_return": round(estimated_convertible_bond_return, 6),
                "estimated_invisible_return": round(estimated_invisible_return, 6),
                "total_excess": round(excess, 6),
            })
        return waterfall

    def to_api_data(self) -> dict:
        active_return = self.total_portfolio_return - self.total_benchmark_return
        est = self.uses_simulated_holdings
        prefix = "estimated_" if est else ""

        # Residual-related fields always carry estimated_ prefix.
        # IPO / CB / invisible returns are also estimated (future/residual).
        result: dict = {
            "fund_code": self.fund_code,
            "method": self.method,
            "algorithm_version": ALGORITHM_VERSION,
            "uses_simulated_holdings": est,
            f"{prefix}total_portfolio_return": round(self.total_portfolio_return, 6),
            f"{prefix}total_benchmark_return": round(self.total_benchmark_return, 6),
            f"{prefix}total_active_return": round(active_return, 6),
            f"{prefix}total_allocation_effect": round(self.total_allocation_effect, 6),
            f"{prefix}total_selection_effect": round(self.total_selection_effect, 6),
            f"{prefix}total_interaction_effect": round(self.total_interaction_effect, 6),
            "estimated_total_residual": round(self.total_residual, 6),
            "estimated_residual_ratio": round(self.residual_ratio, 4),
            "estimated_total_ipo_return": round(self.total_ipo_return, 6),
            "estimated_total_convertible_bond_return": round(self.total_convertible_bond_return, 6),
            "estimated_total_invisible_return": round(self.total_invisible_return, 6),
            "period_count": len(self.periods),
            "confidence": self.confidence,
            "warnings": self.warnings,
            "periods": [],
        }

        # Determine conclusion_status:
        # - If residual ratio exceeds threshold → needs_review
        # - If uses_simulated_holdings → estimated
        # - Otherwise → computed
        result["conclusion_status"] = self.get_conclusion_status()

        # Per-period output uses the same prefix logic.
        result["periods"] = [
            {
                "period_start": str(p.period_start),
                "period_end": str(p.period_end),
                f"{prefix}portfolio_return": round(p.portfolio_return, 6),
                f"{prefix}benchmark_return": round(p.benchmark_return, 6),
                f"{prefix}allocation_effect": round(p.allocation_effect, 6),
                f"{prefix}selection_effect": round(p.selection_effect, 6),
                f"{prefix}interaction_effect": round(p.interaction_effect, 6),
                "estimated_residual": round(p.residual, 6),
            }
            for p in self.periods
        ]

        return result

    def conclusion_status_from_residual(self) -> bool:
        """Return True if residual ratio is within acceptable threshold (i.e. result is usable).

        Per requirements §5.2.3: residual ratio must be <= 50% for the result
        to be considered interpretable. Also requires at least one valid period.
        """
        return len(self.periods) > 0 and self.residual_ratio <= MAX_RESIDUAL_RATIO

    def get_conclusion_status(self) -> str:
        """Return the conclusion_status string for this result.

        Dynamic attribution always uses estimated/approximated decomposition,
        so the status is ``estimated`` unless the residual is too large.
        """
        if self.residual_ratio > MAX_RESIDUAL_RATIO:
            return "needs_review"
        return "estimated"


# ============================================================
# Single-period Brinson
# ============================================================


def single_period_attribution(
    portfolio_weights: dict[str, float],
    # {sector: weight_in_portfolio}
    benchmark_weights: dict[str, float],
    # {sector: weight_in_benchmark}
    portfolio_sector_returns: dict[str, float],
    # {sector: realized_return}
    benchmark_sector_returns: dict[str, float],
    # {sector: benchmark_sector_return}
    *,
    method: str = "BHB",
    period_start: date | None = None,
    period_end: date | None = None,
) -> AttributionPeriod:
    """
    Single-period Brinson attribution.

    BHB: R = sum(w_p * r_p) - sum(w_b * r_b)
         = sum((w_p - w_b) * r_b)         [Allocation]
         + sum(w_p * (r_p - r_b))         [Selection (BHB uses w_b, BF uses w_p)]
         + sum((w_p - w_b) * (r_p - r_b)) [Interaction]

    BF:  Allocation uses (r_b - R_b) instead of r_b,
         Interaction is merged into Selection (selection = w_p*(r_p-r_b)),
         so interaction = 0.

    period_start/period_end: the actual date range of this attribution period.
    If not provided, defaults to date.today() (maintained for backward compat
    but callers should always pass explicit dates).
    """
    sectors = sorted(set(portfolio_weights) | set(benchmark_weights))
    total_benchmark_return = sum(
        benchmark_weights.get(s, 0.0) * benchmark_sector_returns.get(s, 0.0)
        for s in sectors
    )

    sector_details = []
    total_allocation = 0.0
    total_selection = 0.0
    total_interaction = 0.0
    total_portfolio_return = 0.0

    for sector in sectors:
        wp = portfolio_weights.get(sector, 0.0)
        wb = benchmark_weights.get(sector, 0.0)
        rp = portfolio_sector_returns.get(sector, 0.0)
        rb = benchmark_sector_returns.get(sector, 0.0)

        total_portfolio_return += wp * rp

        if method == "BHB":
            allocation = (wp - wb) * rb
            selection = wb * (rp - rb)
            interaction = (wp - wb) * (rp - rb)
        else:  # BF (Brinson-Fachler)
            # BF allocation: (wp - wb) * (rb - Rb) — measures allocation
            # against sectors that outperformed/underperformed the benchmark total
            allocation = (wp - wb) * (rb - total_benchmark_return)
            # BF merges interaction into selection: use wp instead of wb
            selection = wp * (rp - rb)
            interaction = 0.0

        total_allocation += allocation
        total_selection += selection
        total_interaction += interaction

        sector_details.append({
            "sector": sector,
            "port_weight": round(wp, 4),
            "bench_weight": round(wb, 4),
            "port_return": round(rp, 6),
            "bench_return": round(rb, 6),
            "allocation": round(allocation, 6),
            "selection": round(selection, 6),
            "interaction": round(interaction, 6),
        })

    residual = total_portfolio_return - total_benchmark_return - (
        total_allocation + total_selection + total_interaction
    )

    _today = date.today()
    return AttributionPeriod(
        period_start=period_start or _today,
        period_end=period_end or _today,
        portfolio_return=round(total_portfolio_return, 6),
        benchmark_return=round(total_benchmark_return, 6),
        allocation_effect=round(total_allocation, 6),
        selection_effect=round(total_selection, 6),
        interaction_effect=round(total_interaction, 6),
        residual=round(residual, 6),
        sector_details=sector_details,
    )


# ============================================================
# Multi-period Carino linking
# ============================================================


def carino_linking(
    periods: list[AttributionPeriod],
    total_portfolio_return: float | None = None,
    total_benchmark_return: float | None = None,
) -> list[AttributionPeriod]:
    """
    Apply Carino (1999) logarithmic smoothing to multi-period attribution.

    Carino factor for period t:
        k_t = [log(1 + R_port_t) - log(1 + R_bench_t)] / (R_port_t - R_bench_t)

    Linked effect for period t = period_effect * k_t / K, where K is
    computed from the compounded total portfolio and benchmark returns.

    NOTE: This function preserves period_start/period_end from the input
    periods. The caller (run_attribution) is responsible for setting
    correct dates before calling carino_linking.
    """
    if len(periods) <= 1:
        return periods

    if total_portfolio_return is None:
        total_portfolio_return = _compound_returns(p.portfolio_return for p in periods)
    if total_benchmark_return is None:
        total_benchmark_return = _compound_returns(p.benchmark_return for p in periods)

    ks = []
    for p in periods:
        rp, rb = p.portfolio_return, p.benchmark_return
        if abs(rp - rb) < 1e-12:
            k = 1.0 / (1.0 + rp) if rp > -1 else 1.0
        else:
            # Guard against log(0) or log(negative)
            k = 1.0 if 1.0 + rp <= 0 or 1.0 + rb <= 0 else (log(1.0 + rp) - log(1.0 + rb)) / (rp - rb)
        ks.append(k)

    total_active = total_portfolio_return - total_benchmark_return
    if abs(total_active) < 1e-12:
        total_k = 1.0 / (1.0 + total_portfolio_return) if total_portfolio_return > -1 else 1.0
    else:
        if 1.0 + total_portfolio_return <= 0 or 1.0 + total_benchmark_return <= 0:
            total_k = 1.0
        else:
            total_k = (
                log(1.0 + total_portfolio_return) - log(1.0 + total_benchmark_return)
            ) / total_active

    if total_k == 0:
        return periods

    linked = []
    for i, p in enumerate(periods):
        factor = ks[i] / total_k
        linked.append(replace(
            p,
            allocation_effect=p.allocation_effect * factor,
            selection_effect=p.selection_effect * factor,
            interaction_effect=p.interaction_effect * factor,
            residual=p.residual * factor,
        ))

    return linked


def _compound_returns(returns) -> float:
    total = 1.0
    for value in returns:
        total *= 1.0 + value
    return total - 1.0


# ============================================================
# Full pipeline
# ============================================================


def run_attribution(
    fund_code: str,
    holdings_weights: pd.DataFrame,
    # columns: [report_date, sector, port_weight, bench_weight]
    sector_returns: pd.DataFrame,
    # columns: [report_date, sector, port_return, bench_return]
    # Optional: [period_start, period_end] — if absent, report_date is used for both.
    *,
    method: str = "BHB",
    benchmark_symbol: str | None = None,
    uses_simulated_holdings: bool = False,
) -> AttributionResult:
    """
    Run full multi-period Brinson attribution with Carino smoothing.

    holdings_weights: weights for each sector per reporting period.
    sector_returns: realized returns for each sector per period.
        If sector_returns contains period_start/period_end columns, those
        are used for the attribution period window; otherwise report_date
        is used for both start and end.
    uses_simulated_holdings: set to True when the input holdings come from
        the simulated-holdings algorithm (estimated) rather than real
        disclosed holdings. This controls the estimated_ prefix and
        conclusion_status in to_api_data().

    Residual ratio gate (requirements §5.2.3): if |residual| / |active_return| > 50%,
    the result is marked confidence="needs_review" with a warning.
    """
    warnings: list[str] = []
    if benchmark_symbol:
        warnings.append(f"基准指数: {benchmark_symbol}")

    if holdings_weights.empty or sector_returns.empty:
        return AttributionResult(
            fund_code=fund_code,
            periods=[],
            total_portfolio_return=0.0,
            total_benchmark_return=0.0,
            total_allocation_effect=0.0,
            total_selection_effect=0.0,
            total_interaction_effect=0.0,
            total_residual=0.0,
            residual_ratio=0.0,
            warnings=["持仓或行业数据为空"],
            confidence="needs_review",
            uses_simulated_holdings=uses_simulated_holdings,
        )

    if method not in ("BHB", "BF"):
        warnings.append(f"不支持的归因方法 {method}，回退为 BHB")
        method = "BHB"

    hw = holdings_weights.copy()
    hw["report_date"] = pd.to_datetime(hw["report_date"]).dt.date
    sr = sector_returns.copy()
    sr["report_date"] = pd.to_datetime(sr["report_date"]).dt.date
    if "period_start" in sr.columns:
        sr["period_start"] = pd.to_datetime(sr["period_start"]).dt.date
    if "period_end" in sr.columns:
        sr["period_end"] = pd.to_datetime(sr["period_end"]).dt.date

    # Sort report dates to compute period windows
    report_dates = sorted(hw["report_date"].unique())

    periods: list[AttributionPeriod] = []
    for i, rp_date in enumerate(report_dates):
        hw_p = hw[hw["report_date"] == rp_date]
        sr_p = sr[sr["report_date"] == rp_date]
        if hw_p.empty or sr_p.empty:
            continue

        # Determine period start/end
        p_start = rp_date
        p_end = rp_date
        if "period_start" in sr_p.columns and not sr_p["period_start"].isna().all():
            p_start = sr_p["period_start"].iloc[0]
        if "period_end" in sr_p.columns and not sr_p["period_end"].isna().all():
            p_end = sr_p["period_end"].iloc[0]
        elif i + 1 < len(report_dates):
            # Default: period extends to the day before the next report date
            from datetime import timedelta
            p_end = report_dates[i + 1] - timedelta(days=1)

        pw = dict(zip(hw_p["sector"], hw_p["port_weight"], strict=False))
        bw = dict(zip(hw_p["sector"], hw_p["bench_weight"], strict=False))
        pr = dict(zip(sr_p["sector"], sr_p["port_return"], strict=False))
        br = dict(zip(sr_p["sector"], sr_p["bench_return"], strict=False))

        sp = single_period_attribution(
            pw, bw, pr, br, method=method,
            period_start=p_start, period_end=p_end,
        )
        sp.uses_simulated_holdings = uses_simulated_holdings
        periods.append(sp)

    if not periods:
        return AttributionResult(
            fund_code=fund_code,
            periods=[],
            total_portfolio_return=0.0,
            total_benchmark_return=0.0,
            total_allocation_effect=0.0,
            total_selection_effect=0.0,
            total_interaction_effect=0.0,
            total_residual=0.0,
            residual_ratio=0.0,
            warnings=["没有可用的归因期间"],
            confidence="needs_review",
            uses_simulated_holdings=uses_simulated_holdings,
        )

    total_port = _compound_returns(p.portfolio_return for p in periods)
    total_bench = _compound_returns(p.benchmark_return for p in periods)

    # Carino smoothing
    periods = carino_linking(periods, total_port, total_bench)

    total_alloc = sum(p.allocation_effect for p in periods)
    total_sel = sum(p.selection_effect for p in periods)
    total_int = sum(p.interaction_effect for p in periods)
    total_res = total_port - total_bench - (total_alloc + total_sel + total_int)

    active_return = total_port - total_bench

    # IPO and convertible-bond returns are reserved for future implementation.
    # Invisible return = residual that cannot be attributed to known sources.
    total_ipo = 0.0
    total_cb = 0.0
    total_invisible = total_res - total_ipo - total_cb

    # Residual ratio gate (requirements §5.2.3)
    if abs(active_return) > 1e-8:
        residual_ratio = abs(total_res) / abs(active_return)
    else:
        residual_ratio = 1.0 if abs(total_res) > 1e-8 else 0.0

    confidence = "medium"
    if abs(total_res) > 0.01:
        warnings.append(f"归因残差较大 ({total_res:+.4f})，可能因缺失持仓或行业收益数据")

    if residual_ratio > MAX_RESIDUAL_RATIO:
        confidence = "needs_review"
        warnings.append(
            f"残差占比 {residual_ratio:.1%} 超过阈值 {MAX_RESIDUAL_RATIO:.0%}，"
            f"归因结果不可解释，仅作为观察值"
        )
    elif abs(total_res) > 0.02:
        confidence = "low"

    return AttributionResult(
        fund_code=fund_code,
        periods=periods,
        total_portfolio_return=round(total_port, 6),
        total_benchmark_return=round(total_bench, 6),
        total_allocation_effect=round(total_alloc, 6),
        total_selection_effect=round(total_sel, 6),
        total_interaction_effect=round(total_int, 6),
        total_residual=round(total_res, 6),
        total_ipo_return=round(total_ipo, 6),
        total_convertible_bond_return=round(total_cb, 6),
        total_invisible_return=round(total_invisible, 6),
        residual_ratio=round(residual_ratio, 6),
        method=method,
        confidence=confidence,
        warnings=warnings,
        uses_simulated_holdings=uses_simulated_holdings,
    )
