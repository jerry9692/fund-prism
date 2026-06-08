"""Style exposure analysis for Phase 1."""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

ALGORITHM_NAME = "style_exposure"
ALGORITHM_VERSION = "0.1.0"
MIN_OBSERVATIONS = 20
DEFAULT_STYLE_FACTORS = {
    "large_cap": "sh000300",
    "mid_cap": "sh000905",
    "small_cap": "sh000852",
    "growth": "sz399370",
    "value": "sz399371",
}


@dataclass
class ExposureAnalysisResult:
    """Style exposure regression payload."""

    exposure_values: dict[str, float]
    residual: float | None
    r_squared: float | None
    observations: int
    input_coverage: float
    start_date: date | None
    end_date: date | None
    factor_symbols: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    @property
    def is_sufficient(self) -> bool:
        """Whether the regression has enough input data to be useful."""
        return self.observations >= MIN_OBSERVATIONS and bool(self.exposure_values)

    def to_data(self) -> dict:
        """Return API-friendly data."""
        return {
            "exposure_values": self.exposure_values,
            "residual": self.residual,
            "r_squared": self.r_squared,
            "observations": self.observations,
            "input_coverage": self.input_coverage,
            "start_date": str(self.start_date) if self.start_date else None,
            "end_date": str(self.end_date) if self.end_date else None,
            "factor_symbols": self.factor_symbols,
        }


def _clean_float(value: float | int | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _prepare_fund_returns(fund_returns: pd.DataFrame) -> pd.DataFrame:
    data = fund_returns.copy()
    if data.empty:
        return pd.DataFrame(columns=["trade_date", "fund_return"])
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    if "daily_return" in data.columns and data["daily_return"].notna().any():
        data["fund_return"] = pd.to_numeric(data["daily_return"], errors="coerce")
    else:
        nav_col = next(
            (col for col in ("adjusted_nav", "accumulated_nav", "unit_nav") if col in data.columns),
            None,
        )
        if nav_col is None:
            data["fund_return"] = np.nan
        else:
            data["fund_return"] = pd.to_numeric(data[nav_col], errors="coerce").pct_change()
    return data[["trade_date", "fund_return"]]


def _prepare_factor_returns(
    factor_returns: pd.DataFrame,
    factor_symbols: dict[str, str],
) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    data = factor_returns.copy()
    if data.empty:
        return pd.DataFrame(columns=["trade_date"]), ["风格指数行情数据为空"]

    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    if "daily_return" in data.columns and data["daily_return"].notna().any():
        data["factor_return"] = pd.to_numeric(data["daily_return"], errors="coerce")
    else:
        data = data.sort_values(["stock_code", "trade_date"])
        data["factor_return"] = (
            pd.to_numeric(data["close_price"], errors="coerce")
            .groupby(data["stock_code"])
            .pct_change()
        )

    symbol_to_name = {symbol: name for name, symbol in factor_symbols.items()}
    present_symbols = set(data["stock_code"].dropna().astype(str))
    missing_symbols = sorted(set(symbol_to_name) - present_symbols)
    if missing_symbols:
        warnings.append(f"缺少风格指数行情: {', '.join(missing_symbols)}")

    data["factor_name"] = data["stock_code"].map(symbol_to_name)
    pivot = data.dropna(subset=["factor_name"]).pivot_table(
        index="trade_date",
        columns="factor_name",
        values="factor_return",
        aggfunc="last",
    )
    return pivot.reset_index(), warnings


def calculate_style_exposure(
    fund_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    *,
    window: int = 60,
    factor_symbols: dict[str, str] | None = None,
) -> ExposureAnalysisResult:
    """Calculate latest-window style exposure via OLS regression."""
    factor_symbols = factor_symbols or DEFAULT_STYLE_FACTORS
    fund_data = _prepare_fund_returns(fund_returns)
    factor_data, warnings = _prepare_factor_returns(factor_returns, factor_symbols)
    if fund_data.empty:
        warnings.append("基金收益率数据为空")
    merged = fund_data.merge(factor_data, on="trade_date", how="inner")
    available_factor_names = [
        name for name in factor_symbols if name in merged.columns and merged[name].notna().any()
    ]

    if not available_factor_names:
        return ExposureAnalysisResult(
            exposure_values={},
            residual=None,
            r_squared=None,
            observations=0,
            input_coverage=0.0,
            start_date=None,
            end_date=None,
            factor_symbols=factor_symbols,
            warnings=[*warnings, "没有可用风格因子"],
        )

    regression_data = merged[["trade_date", "fund_return", *available_factor_names]].dropna()
    expected_observations = min(window, len(merged)) if len(merged) else window
    regression_data = regression_data.tail(window)
    observations = len(regression_data)
    input_coverage = observations / expected_observations if expected_observations else 0.0

    if observations < max(MIN_OBSERVATIONS, len(available_factor_names) + 2):
        warnings.append(f"可用回归样本不足 {MIN_OBSERVATIONS} 条，风格暴露需复核")
        return ExposureAnalysisResult(
            exposure_values={},
            residual=None,
            r_squared=None,
            observations=observations,
            input_coverage=input_coverage,
            start_date=regression_data["trade_date"].min() if observations else None,
            end_date=regression_data["trade_date"].max() if observations else None,
            factor_symbols=factor_symbols,
            warnings=warnings,
        )

    y = regression_data["fund_return"].to_numpy(dtype=float)
    x = regression_data[available_factor_names].to_numpy(dtype=float)
    if len(available_factor_names) > 1:
        condition_number = float(np.linalg.cond(x))
        if condition_number > 30:
            warnings.append(
                "风格因子可能存在较强共线性，OLS 暴露系数不应直接解释为配置权重"
            )
    x_with_intercept = np.column_stack([np.ones(len(x)), x])
    coefficients, *_ = np.linalg.lstsq(x_with_intercept, y, rcond=None)
    if any(abs(value) > 1 for value in coefficients[1:]):
        warnings.append("存在绝对值超过 1 的 OLS 暴露系数，需结合残差和因子共线性复核")
    y_hat = x_with_intercept @ coefficients
    residuals = y - y_hat
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    residual = float(np.sqrt(np.mean(residuals**2)))

    return ExposureAnalysisResult(
        exposure_values={
            factor_name: float(value)
            for factor_name, value in zip(available_factor_names, coefficients[1:], strict=False)
        },
        residual=_clean_float(residual),
        r_squared=_clean_float(r_squared),
        observations=observations,
        input_coverage=input_coverage,
        start_date=regression_data["trade_date"].min(),
        end_date=regression_data["trade_date"].max(),
        factor_symbols=factor_symbols,
        warnings=warnings,
    )
