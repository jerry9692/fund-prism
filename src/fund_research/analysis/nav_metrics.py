"""NAV return and risk metrics for Phase 1."""

from dataclasses import dataclass, field
from datetime import date
from math import sqrt

import pandas as pd

ALGORITHM_NAME = "nav_metrics"
ALGORITHM_VERSION = "0.1.0"
TRADING_DAYS_PER_YEAR = 252
MIN_OBSERVATIONS = 20


@dataclass
class NavMetricsResult:
    """Computed NAV metric payload."""

    metrics: dict[str, float | int | str | None]
    observations: int
    coverage_rate: float
    start_date: date | None
    end_date: date | None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_sufficient(self) -> bool:
        """Whether the result has enough observations for computed conclusions."""
        return self.observations >= MIN_OBSERVATIONS

    def to_data(self) -> dict:
        """Return API-friendly data."""
        return {
            "metrics": self.metrics,
            "observations": self.observations,
            "coverage_rate": self.coverage_rate,
            "start_date": str(self.start_date) if self.start_date else None,
            "end_date": str(self.end_date) if self.end_date else None,
        }


def _clean_float(value: float | int | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _prepare_returns(nav_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if nav_df.empty:
        return pd.DataFrame(columns=["trade_date", "daily_return"]), ["净值数据为空"]

    data = nav_df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    data = data.sort_values("trade_date")

    if "daily_return" in data.columns and data["daily_return"].notna().any():
        data["daily_return"] = pd.to_numeric(data["daily_return"], errors="coerce")
    else:
        nav_col = next(
            (col for col in ("adjusted_nav", "accumulated_nav", "unit_nav") if col in data.columns),
            None,
        )
        if nav_col is None:
            return data, ["缺少 daily_return，且没有可用于推算收益率的净值字段"]
        data["daily_return"] = pd.to_numeric(data[nav_col], errors="coerce").pct_change()
        warnings.append(f"daily_return 缺失，已使用 {nav_col} 推算")

    return data, warnings


def calculate_nav_metrics(nav_df: pd.DataFrame, risk_free_rate: float = 0.0) -> NavMetricsResult:
    """Calculate common return and risk metrics from NAV observations."""
    data, warnings = _prepare_returns(nav_df)
    if data.empty:
        return NavMetricsResult(
            metrics={},
            observations=0,
            coverage_rate=0.0,
            start_date=None,
            end_date=None,
            warnings=warnings,
        )

    returns = data["daily_return"].dropna()
    observations = len(returns)
    coverage_rate = observations / len(data) if len(data) else 0.0
    start_date = data["trade_date"].min()
    end_date = data["trade_date"].max()

    if observations == 0:
        warnings.append("没有可计算收益率的净值记录")
        return NavMetricsResult(
            metrics={},
            observations=0,
            coverage_rate=coverage_rate,
            start_date=start_date,
            end_date=end_date,
            warnings=warnings,
        )

    wealth = (1 + returns).cumprod()
    total_return = wealth.iloc[-1] - 1
    annualized_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / observations) - 1
    annualized_volatility = returns.std() * sqrt(TRADING_DAYS_PER_YEAR)
    downside_returns = returns[returns < 0]
    downside_volatility = (
        downside_returns.std() * sqrt(TRADING_DAYS_PER_YEAR) if len(downside_returns) > 1 else None
    )
    drawdown = wealth / wealth.cummax() - 1
    max_drawdown = drawdown.min()

    sharpe_ratio = (
        (annualized_return - risk_free_rate) / annualized_volatility
        if annualized_volatility and annualized_volatility > 0
        else None
    )
    calmar_ratio = (
        annualized_return / abs(max_drawdown)
        if max_drawdown is not None and max_drawdown < 0
        else None
    )
    sortino_ratio = (
        (annualized_return - risk_free_rate) / downside_volatility
        if downside_volatility and downside_volatility > 0
        else None
    )

    if observations < MIN_OBSERVATIONS:
        warnings.append(f"可用收益率样本不足 {MIN_OBSERVATIONS} 条，指标仅供复核")

    return NavMetricsResult(
        metrics={
            "total_return": _clean_float(total_return),
            "annualized_return": _clean_float(annualized_return),
            "max_drawdown": _clean_float(max_drawdown),
            "annualized_volatility": _clean_float(annualized_volatility),
            "downside_volatility": _clean_float(downside_volatility),
            "sharpe_ratio": _clean_float(sharpe_ratio),
            "calmar_ratio": _clean_float(calmar_ratio),
            "sortino_ratio": _clean_float(sortino_ratio),
            "information_ratio": None,
            "trading_days_per_year": TRADING_DAYS_PER_YEAR,
        },
        observations=observations,
        coverage_rate=coverage_rate,
        start_date=start_date,
        end_date=end_date,
        warnings=warnings,
    )

