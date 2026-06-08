"""Static attribution analysis for Phase 1."""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from fund_research.analysis.holdings import (
    TOP10_QUARTERLY,
    classify_disclosure_granularity,
)

ALGORITHM_NAME = "static_attribution"
ALGORITHM_VERSION = "0.1.0"
MIN_COVERAGE_RATE = 0.8


@dataclass
class StaticAttributionAnalysisResult:
    """Static disclosed-holding attribution payload."""

    report_date: date | None
    start_date: date | None
    end_date: date | None
    total_return: float | None
    explained_return: float | None
    residual: float | None
    residual_pct: float | None
    coverage_rate: float
    security_contributions: list[dict]
    industry_contributions: list[dict]
    warnings: list[str] = field(default_factory=list)

    @property
    def is_sufficient(self) -> bool:
        """Whether the static attribution result has enough input coverage."""
        return (
            self.total_return is not None
            and self.explained_return is not None
            and self.coverage_rate >= MIN_COVERAGE_RATE
            and bool(self.security_contributions)
        )

    def to_data(self) -> dict:
        """Return API-friendly data."""
        return {
            "report_date": str(self.report_date) if self.report_date else None,
            "start_date": str(self.start_date) if self.start_date else None,
            "end_date": str(self.end_date) if self.end_date else None,
            "total_return": self.total_return,
            "explained_return": self.explained_return,
            "residual": self.residual,
            "residual_pct": self.residual_pct,
            "coverage_rate": self.coverage_rate,
            "security_contributions": self.security_contributions,
            "industry_contributions": self.industry_contributions,
        }


def _clean_float(value: float | int | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _compound_return(values: pd.Series) -> float | None:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    if returns.empty:
        return None
    return _clean_float((1 + returns).prod() - 1)


def _price_return(values: pd.Series) -> float | None:
    prices = pd.to_numeric(values, errors="coerce").dropna()
    if len(prices) < 2 or prices.iloc[0] == 0:
        return None
    return _clean_float(prices.iloc[-1] / prices.iloc[0] - 1)


def _prepare_holdings(holdings_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if holdings_df.empty:
        return pd.DataFrame(), ["公开披露持仓数据为空，无法进行静态归因"]

    data = holdings_df.copy()
    data["report_date"] = pd.to_datetime(data["report_date"]).dt.date
    data["security_code"] = data["security_code"].astype(str)
    data["weight_pct"] = pd.to_numeric(data["weight_pct"], errors="coerce")
    data = data.dropna(subset=["security_code", "weight_pct"])

    if "asset_type" in data.columns:
        non_stock_count = len(data[data["asset_type"] != "股票"])
        if non_stock_count:
            warnings.append("静态归因当前仅覆盖股票持仓，非股票资产未纳入解释收益")
        data = data[data["asset_type"] == "股票"]

    if data.empty:
        warnings.append("缺少可用于静态归因的股票持仓权重")
        return data, warnings

    data["weight_decimal"] = data["weight_pct"].apply(
        lambda value: float(value) / 100 if abs(float(value)) > 1 else float(value)
    )

    report_date = data["report_date"].max()
    if classify_disclosure_granularity(report_date) == TOP10_QUARTERLY:
        warnings.append("季报通常仅披露前十大重仓，静态归因只能解释披露持仓部分")

    return data, warnings


def _security_cumulative_returns(security_returns_df: pd.DataFrame) -> pd.DataFrame:
    if security_returns_df.empty:
        return pd.DataFrame(
            columns=["security_code", "security_return", "start_date", "end_date", "observations"]
        )

    data = security_returns_df.copy()
    data["stock_code"] = data["stock_code"].astype(str)
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    data = data.sort_values(["stock_code", "trade_date"])
    rows = []
    for stock_code, group in data.groupby("stock_code", sort=True):
        period_return = None
        if "daily_return" in group.columns and group["daily_return"].notna().any():
            period_return = _compound_return(group["daily_return"])
        if period_return is None and "close_price" in group.columns:
            period_return = _price_return(group["close_price"])
        rows.append(
            {
                "security_code": str(stock_code),
                "security_return": period_return,
                "start_date": group["trade_date"].min(),
                "end_date": group["trade_date"].max(),
                "observations": int(group["trade_date"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def _fund_total_return(
    fund_returns_df: pd.DataFrame,
) -> tuple[float | None, date | None, date | None]:
    if fund_returns_df.empty:
        return None, None, None

    data = fund_returns_df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    data = data.sort_values("trade_date")
    total_return = None
    if "daily_return" in data.columns and data["daily_return"].notna().any():
        total_return = _compound_return(data["daily_return"])
    if total_return is None:
        nav_col = next(
            (col for col in ("adjusted_nav", "accumulated_nav", "unit_nav") if col in data.columns),
            None,
        )
        if nav_col is not None:
            total_return = _price_return(data[nav_col])
    return total_return, data["trade_date"].min(), data["trade_date"].max()


def calculate_static_attribution(
    holdings_df: pd.DataFrame,
    security_returns_df: pd.DataFrame,
    fund_returns_df: pd.DataFrame,
) -> StaticAttributionAnalysisResult:
    """Calculate static attribution from disclosed weights and realized security returns."""
    holdings, warnings = _prepare_holdings(holdings_df)
    if holdings.empty:
        return StaticAttributionAnalysisResult(
            report_date=None,
            start_date=None,
            end_date=None,
            total_return=None,
            explained_return=None,
            residual=None,
            residual_pct=None,
            coverage_rate=0.0,
            security_contributions=[],
            industry_contributions=[],
            warnings=warnings,
        )

    report_date = holdings["report_date"].max()
    security_returns = _security_cumulative_returns(security_returns_df)
    merged = holdings.merge(security_returns, on="security_code", how="left")
    usable = merged.dropna(subset=["security_return", "weight_decimal"]).copy()
    coverage_rate = len(usable) / len(holdings) if len(holdings) else 0.0
    if coverage_rate < 1:
        missing = sorted(set(holdings["security_code"]) - set(usable["security_code"]))
        warnings.append(f"缺少 {len(missing)} 个披露持仓证券的区间收益数据")
    if coverage_rate < MIN_COVERAGE_RATE:
        warnings.append("持仓证券行情覆盖率偏低，静态归因需复核")

    usable["contribution"] = usable["weight_decimal"] * usable["security_return"]
    explained_return = _clean_float(usable["contribution"].sum()) if not usable.empty else None
    total_return, start_date, end_date = _fund_total_return(fund_returns_df)
    if total_return is None:
        warnings.append("基金区间收益缺失，无法计算未解释残差")

    residual = None
    residual_pct = None
    if total_return is not None and explained_return is not None:
        residual = _clean_float(total_return - explained_return)
        residual_pct = (
            _clean_float(residual / abs(total_return))
            if residual is not None and abs(total_return) > 1e-12
            else None
        )

    security_contributions = [
        {
            "security_code": row["security_code"],
            "security_name": row.get("security_name"),
            "industry": row.get("industry"),
            "weight_pct": _clean_float(row.get("weight_pct")),
            "security_return": _clean_float(row.get("security_return")),
            "contribution": _clean_float(row.get("contribution")),
        }
        for row in usable.sort_values("contribution", key=lambda item: item.abs(), ascending=False)
        .to_dict(orient="records")
    ]

    if usable.empty:
        industry_contributions = []
    else:
        industry_data = usable.copy()
        if "industry" not in industry_data.columns:
            industry_data["industry"] = "未分类"
        else:
            industry_data["industry"] = industry_data["industry"].fillna("未分类")
        grouped = (
            industry_data.groupby("industry", dropna=False)
            .agg(
                weight_pct=("weight_pct", "sum"),
                contribution=("contribution", "sum"),
                security_count=("security_code", "nunique"),
            )
            .reset_index()
            .sort_values("contribution", key=lambda item: item.abs(), ascending=False)
        )
        industry_contributions = [
            {
                "industry": row["industry"],
                "weight_pct": _clean_float(row["weight_pct"]),
                "contribution": _clean_float(row["contribution"]),
                "security_count": int(row["security_count"]),
            }
            for row in grouped.to_dict(orient="records")
        ]

    return StaticAttributionAnalysisResult(
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        total_return=total_return,
        explained_return=explained_return,
        residual=residual,
        residual_pct=residual_pct,
        coverage_rate=coverage_rate,
        security_contributions=security_contributions,
        industry_contributions=industry_contributions,
        warnings=warnings,
    )
