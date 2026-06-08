"""Disclosed holdings analysis for Phase 1."""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

ALGORITHM_NAME = "disclosed_holdings"
ALGORITHM_VERSION = "0.1.0"
TOP10_QUARTERLY = "top10_quarterly"
FULL_SEMIANNUAL_OR_ANNUAL = "full_semiannual_or_annual"
UNKNOWN_GRANULARITY = "unknown"


@dataclass
class HoldingsAnalysisResult:
    """Analyzed disclosed holdings payload."""

    report_date: date | None
    disclosure_granularity: str
    holdings: list[dict]
    total_weight_pct: float | None
    concentration_top10_pct: float | None
    industry_distribution: list[dict]
    asset_distribution: list[dict]
    previous_report_date: date | None = None
    holding_changes: list[dict] = field(default_factory=list)
    change_summary: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_limited(self) -> bool:
        """Whether the holdings are known to be partial disclosure."""
        return self.disclosure_granularity == TOP10_QUARTERLY

    def to_data(self) -> dict:
        """Return API-friendly data."""
        return {
            "report_date": str(self.report_date) if self.report_date else None,
            "disclosure_granularity": self.disclosure_granularity,
            "holdings": self.holdings,
            "total_weight_pct": self.total_weight_pct,
            "concentration_top10_pct": self.concentration_top10_pct,
            "industry_distribution": self.industry_distribution,
            "asset_distribution": self.asset_distribution,
            "previous_report_date": (
                str(self.previous_report_date) if self.previous_report_date else None
            ),
            "holding_changes": self.holding_changes,
            "change_summary": self.change_summary,
        }


def classify_disclosure_granularity(report_date: date | None) -> str:
    """Classify disclosure granularity by report period rather than row count."""
    if report_date is None:
        return UNKNOWN_GRANULARITY
    if (report_date.month, report_date.day) in {(3, 31), (9, 30)}:
        return TOP10_QUARTERLY
    if (report_date.month, report_date.day) in {(6, 30), (12, 31)}:
        return FULL_SEMIANNUAL_OR_ANNUAL
    return UNKNOWN_GRANULARITY


def _clean_float(value: float | int | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _distribution(data: pd.DataFrame, group_col: str) -> list[dict]:
    if data.empty or group_col not in data.columns or "weight_pct" not in data.columns:
        return []
    grouped = (
        data.dropna(subset=[group_col])
        .groupby(group_col, dropna=True)["weight_pct"]
        .sum()
        .sort_values(ascending=False)
    )
    return [
        {"name": str(name), "weight_pct": _clean_float(weight)}
        for name, weight in grouped.items()
    ]


def _normalize_holding_frame(holdings_df: pd.DataFrame) -> pd.DataFrame:
    data = holdings_df.copy()
    data["report_date"] = pd.to_datetime(data["report_date"]).dt.date
    if "weight_pct" in data.columns:
        data["weight_pct"] = pd.to_numeric(data["weight_pct"], errors="coerce")
    if "rank_in_holdings" in data.columns:
        data["rank_in_holdings"] = pd.to_numeric(data["rank_in_holdings"], errors="coerce")
        data = data.sort_values(["rank_in_holdings", "security_code"], na_position="last")
    else:
        data = data.sort_values("security_code")
    return data


def _direction(delta_weight_pct: float | None) -> tuple[str, str]:
    if delta_weight_pct is None:
        return "unchanged", "持平"
    if delta_weight_pct > 0.000001:
        return "increased", "增持"
    if delta_weight_pct < -0.000001:
        return "decreased", "减持"
    return "unchanged", "持平"


def _holding_changes(
    current: pd.DataFrame,
    previous: pd.DataFrame,
) -> tuple[list[dict], dict[str, int]]:
    if (
        current.empty
        or previous.empty
        or "security_code" not in current
        or "security_code" not in previous
    ):
        return [], {}

    current_by_code = {str(row["security_code"]): row for row in current.to_dict(orient="records")}
    previous_by_code = {
        str(row["security_code"]): row for row in previous.to_dict(orient="records")
    }
    changes = []
    summary = {"new": 0, "increased": 0, "decreased": 0, "unchanged": 0, "exited": 0}
    for code in sorted(set(current_by_code) | set(previous_by_code)):
        current_row = current_by_code.get(code)
        previous_row = previous_by_code.get(code)
        current_weight = _clean_float(current_row.get("weight_pct")) if current_row else None
        previous_weight = _clean_float(previous_row.get("weight_pct")) if previous_row else None
        if previous_row is None:
            direction, direction_zh = "new", "新增"
            delta_weight_pct = current_weight
        elif current_row is None:
            direction, direction_zh = "exited", "退出"
            delta_weight_pct = -previous_weight if previous_weight is not None else None
        else:
            delta_weight_pct = (
                current_weight - previous_weight
                if current_weight is not None and previous_weight is not None
                else None
            )
            direction, direction_zh = _direction(delta_weight_pct)

        summary[direction] += 1
        source_row = current_row or previous_row or {}
        changes.append(
            {
                "security_code": code,
                "security_name": source_row.get("security_name"),
                "asset_type": source_row.get("asset_type"),
                "industry": source_row.get("industry"),
                "direction": direction,
                "direction_zh": direction_zh,
                "current_weight_pct": current_weight,
                "previous_weight_pct": previous_weight,
                "delta_weight_pct": _clean_float(delta_weight_pct),
            }
        )

    priority = {"new": 0, "increased": 1, "decreased": 2, "exited": 3, "unchanged": 4}
    changes.sort(
        key=lambda item: (
            priority[item["direction"]],
            -(abs(item["delta_weight_pct"]) if item["delta_weight_pct"] is not None else 0.0),
            item["security_code"],
        )
    )
    return changes, summary


def analyze_disclosed_holdings(
    holdings_df: pd.DataFrame,
    previous_holdings_df: pd.DataFrame | None = None,
) -> HoldingsAnalysisResult:
    """Analyze disclosed holdings without inferring undisclosed portfolio positions."""
    if holdings_df.empty:
        return HoldingsAnalysisResult(
            report_date=None,
            disclosure_granularity=UNKNOWN_GRANULARITY,
            holdings=[],
            total_weight_pct=None,
            concentration_top10_pct=None,
            industry_distribution=[],
            asset_distribution=[],
            previous_report_date=None,
            holding_changes=[],
            change_summary={},
            warnings=["公开披露持仓数据为空"],
        )

    data = _normalize_holding_frame(holdings_df)
    report_date = data["report_date"].max()
    disclosure_granularity = classify_disclosure_granularity(report_date)
    warnings: list[str] = []
    if disclosure_granularity == TOP10_QUARTERLY:
        warnings.append("季报通常仅披露前十大重仓，不能视为完整组合")
    elif disclosure_granularity == UNKNOWN_GRANULARITY:
        warnings.append("无法识别报告期披露粒度，需人工复核")

    total_weight_pct = (
        _clean_float(data["weight_pct"].sum(skipna=True)) if "weight_pct" in data.columns else None
    )
    top10_data = (
        data.nsmallest(10, "rank_in_holdings")
        if "rank_in_holdings" in data.columns
        else data.head(10)
    )
    concentration_top10_pct = (
        _clean_float(top10_data["weight_pct"].sum(skipna=True))
        if "weight_pct" in top10_data.columns
        else None
    )

    holdings = [
        {
            "asset_type": row.get("asset_type"),
            "security_code": row.get("security_code"),
            "security_name": row.get("security_name"),
            "weight_pct": _clean_float(row.get("weight_pct")),
            "market_value": _clean_float(row.get("market_value")),
            "shares": _clean_float(row.get("shares")),
            "rank_in_holdings": (
                int(row.get("rank_in_holdings"))
                if not pd.isna(row.get("rank_in_holdings"))
                else None
            ),
            "industry": row.get("industry"),
            "change_direction": row.get("change_direction"),
        }
        for row in data.to_dict(orient="records")
    ]
    previous_report_date = None
    holding_changes = []
    change_summary = {}
    if previous_holdings_df is not None and not previous_holdings_df.empty:
        previous_data = _normalize_holding_frame(previous_holdings_df)
        previous_report_date = previous_data["report_date"].max()
        holding_changes, change_summary = _holding_changes(data, previous_data)

    return HoldingsAnalysisResult(
        report_date=report_date,
        disclosure_granularity=disclosure_granularity,
        holdings=holdings,
        total_weight_pct=total_weight_pct,
        concentration_top10_pct=concentration_top10_pct,
        industry_distribution=_distribution(data, "industry"),
        asset_distribution=_distribution(data, "asset_type"),
        previous_report_date=previous_report_date,
        holding_changes=holding_changes,
        change_summary=change_summary,
        warnings=warnings,
    )
