"""
Dynamic multi-period return attribution using the Brinson model.

References:
- Brinson, Hood & Beebower (1986): Determinants of Portfolio Performance
- Brinson & Fachler (1985): Measuring Non-US Equity Portfolio Performance
- Carino (1999): Combining Attribution Effects Over Time

Supports both BHB and BF decomposition methods via the `method` parameter.
"""

from dataclasses import dataclass, field
from datetime import date
from math import log

import pandas as pd

ALGORITHM_NAME = "dynamic_attribution"
ALGORITHM_VERSION = "0.1.0"


@dataclass
class AttributionPeriod:
    """Single period attribution result."""

    period_start: date
    period_end: date
    portfolio_return: float
    benchmark_return: float
    allocation_effect: float  # sector allocation contribution
    selection_effect: float  # stock selection contribution
    interaction_effect: float  # cross term (BHB) or merged (BF)
    residual: float
    sector_details: list[dict] = field(default_factory=list)
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
    method: str = "BHB"
    confidence: str = "medium"
    warnings: list[str] = field(default_factory=list)

    def to_api_data(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "method": self.method,
            "total_portfolio_return": round(self.total_portfolio_return, 6),
            "total_benchmark_return": round(self.total_benchmark_return, 6),
            "total_allocation_effect": round(self.total_allocation_effect, 6),
            "total_selection_effect": round(self.total_selection_effect, 6),
            "total_interaction_effect": round(self.total_interaction_effect, 6),
            "total_residual": round(self.total_residual, 6),
            "period_count": len(self.periods),
            "confidence": self.confidence,
            "warnings": self.warnings,
            "periods": [
                {
                    "period_start": str(p.period_start),
                    "period_end": str(p.period_end),
                    "portfolio_return": round(p.portfolio_return, 6),
                    "benchmark_return": round(p.benchmark_return, 6),
                    "allocation_effect": round(p.allocation_effect, 6),
                    "selection_effect": round(p.selection_effect, 6),
                    "interaction_effect": round(p.interaction_effect, 6),
                    "residual": round(p.residual, 6),
                }
                for p in self.periods
            ],
        }


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
) -> AttributionPeriod:
    """
    Single-period Brinson attribution.

    BHB: R = sum(w_p * r_p) - sum(w_b * r_b)
         = sum((w_p - w_b) * r_b)    [Allocation]
         + sum(w_b * (r_p - r_b))    [Selection]
         + sum((w_p - w_b) * (r_p - r_b))  [Interaction]

    BF:  Allocation uses (r_b - R_b) instead of r_b,
         Interaction merged into Selection.
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
        else:  # BF
            allocation = (wp - wb) * (rb - total_benchmark_return)
            selection = wb * (rp - rb)
            interaction = 0.0  # merged into selection implicitly

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

    return AttributionPeriod(
        period_start=date.today(),
        period_end=date.today(),
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


def carino_linking(periods: list[AttributionPeriod]) -> list[AttributionPeriod]:
    """
    Apply Carino (1999) logarithmic smoothing to multi-period attribution.

    Carino factor for period t:
        k_t = log(1 + R_port_t) - log(1 + R_bench_t)
             / (R_port_t - R_bench_t)

    Smoothed effect = sum(period_effect * k_t) / sum(k_t)
    """
    if len(periods) <= 1:
        return periods

    ks = []
    for p in periods:
        rp, rb = p.portfolio_return, p.benchmark_return
        if abs(rp - rb) < 1e-12:
            k = 1.0 / (1.0 + rp) if rp > -1 else 1.0
        else:
            k = (log(1.0 + rp) - log(1.0 + rb)) / (rp - rb)
        ks.append(k)

    total_k = sum(ks)
    if total_k == 0:
        return periods

    # Store smoothed effects in a copy (not modifying original period objects)
    for i, p in enumerate(periods):
        k = ks[i]
        p.allocation_effect *= k / total_k
        p.selection_effect *= k / total_k
        p.interaction_effect *= k / total_k

    return periods


# ============================================================
# Full pipeline
# ============================================================


def run_attribution(
    fund_code: str,
    holdings_weights: pd.DataFrame,
    # columns: [report_date, sector, port_weight, bench_weight]
    sector_returns: pd.DataFrame,
    # columns: [report_date, sector, port_return, bench_return]
    *,
    method: str = "BHB",
) -> AttributionResult:
    """
    Run full multi-period Brinson attribution with Carino smoothing.

    holdings_weights: weights for each sector per reporting period
    sector_returns: realized returns for each sector per period
    """
    warnings: list[str] = []
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
            warnings=["持仓或行业数据为空"],
            confidence="needs_review",
        )

    if method not in ("BHB", "BF"):
        warnings.append(f"不支持的归因方法 {method}，回退为 BHB")
        method = "BHB"

    hw = holdings_weights.copy()
    hw["report_date"] = pd.to_datetime(hw["report_date"]).dt.date
    sr = sector_returns.copy()
    sr["report_date"] = pd.to_datetime(sr["report_date"]).dt.date

    periods: list[AttributionPeriod] = []
    for rp_date in sorted(hw["report_date"].unique()):
        hw_p = hw[hw["report_date"] == rp_date]
        sr_p = sr[sr["report_date"] == rp_date]
        if hw_p.empty or sr_p.empty:
            continue

        pw = dict(zip(hw_p["sector"], hw_p["port_weight"], strict=False))
        bw = dict(zip(hw_p["sector"], hw_p["bench_weight"], strict=False))
        pr = dict(zip(sr_p["sector"], sr_p["port_return"], strict=False))
        br = dict(zip(sr_p["sector"], sr_p["bench_return"], strict=False))

        sp = single_period_attribution(pw, bw, pr, br, method=method)
        sp.period_start = rp_date
        sp.period_end = rp_date
        periods.append(sp)

    # Carino smoothing
    periods = carino_linking(periods)

    total_port = sum(p.portfolio_return for p in periods)
    total_bench = sum(p.benchmark_return for p in periods)
    total_alloc = sum(p.allocation_effect for p in periods)
    total_sel = sum(p.selection_effect for p in periods)
    total_int = sum(p.interaction_effect for p in periods)
    total_res = abs(total_port - total_bench - (total_alloc + total_sel + total_int))

    if abs(total_res) > 0.01:
        warnings.append(f"归因残差较大 ({total_res:.4f})，可能因缺失持仓或行业收益数据")

    return AttributionResult(
        fund_code=fund_code,
        periods=periods,
        total_portfolio_return=round(total_port, 6),
        total_benchmark_return=round(total_bench, 6),
        total_allocation_effect=round(total_alloc, 6),
        total_selection_effect=round(total_sel, 6),
        total_interaction_effect=round(total_int, 6),
        total_residual=round(total_res, 6),
        method=method,
        confidence="medium" if abs(total_res) < 0.02 else "low",
        warnings=warnings,
    )
