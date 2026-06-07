"""Disclosed holdings analysis tests."""

from datetime import date

import pandas as pd

from fund_research.analysis.holdings import (
    FULL_SEMIANNUAL_OR_ANNUAL,
    TOP10_QUARTERLY,
    UNKNOWN_GRANULARITY,
    analyze_disclosed_holdings,
    classify_disclosure_granularity,
)


def test_classify_disclosure_granularity_by_report_period() -> None:
    """Disclosure granularity should follow report period, not row count."""
    assert classify_disclosure_granularity(date(2024, 3, 31)) == TOP10_QUARTERLY
    assert classify_disclosure_granularity(date(2024, 9, 30)) == TOP10_QUARTERLY
    assert classify_disclosure_granularity(date(2024, 6, 30)) == FULL_SEMIANNUAL_OR_ANNUAL
    assert classify_disclosure_granularity(date(2024, 12, 31)) == FULL_SEMIANNUAL_OR_ANNUAL
    assert classify_disclosure_granularity(date(2024, 5, 31)) == UNKNOWN_GRANULARITY


def test_analyze_disclosed_holdings_marks_quarterly_top10_limited() -> None:
    """Quarterly holdings should be marked as top10-only with warnings."""
    data = pd.DataFrame(
        [
            {
                "report_date": date(2024, 3, 31),
                "asset_type": "股票",
                "security_code": "600519",
                "security_name": "贵州茅台",
                "weight_pct": 8.5,
                "rank_in_holdings": 1,
                "industry": "食品饮料",
            },
            {
                "report_date": date(2024, 3, 31),
                "asset_type": "股票",
                "security_code": "000858",
                "security_name": "五粮液",
                "weight_pct": 5.0,
                "rank_in_holdings": 2,
                "industry": "食品饮料",
            },
        ]
    )

    result = analyze_disclosed_holdings(data)

    assert result.is_limited is True
    assert result.disclosure_granularity == TOP10_QUARTERLY
    assert result.total_weight_pct == 13.5
    assert result.industry_distribution == [{"name": "食品饮料", "weight_pct": 13.5}]
    assert result.warnings == ["季报通常仅披露前十大重仓，不能视为完整组合"]


def test_analyze_disclosed_holdings_compares_previous_report() -> None:
    """Holding changes should compare disclosed rows without inferring hidden trades."""
    current = pd.DataFrame(
        [
            {
                "report_date": date(2024, 6, 30),
                "asset_type": "股票",
                "security_code": "600519",
                "security_name": "贵州茅台",
                "weight_pct": 8.5,
                "rank_in_holdings": 1,
                "industry": "食品饮料",
            },
            {
                "report_date": date(2024, 6, 30),
                "asset_type": "股票",
                "security_code": "000858",
                "security_name": "五粮液",
                "weight_pct": 4.0,
                "rank_in_holdings": 2,
                "industry": "食品饮料",
            },
            {
                "report_date": date(2024, 6, 30),
                "asset_type": "股票",
                "security_code": "000001",
                "security_name": "平安银行",
                "weight_pct": 2.0,
                "rank_in_holdings": 3,
                "industry": "银行",
            },
        ]
    )
    previous = pd.DataFrame(
        [
            {
                "report_date": date(2023, 12, 31),
                "asset_type": "股票",
                "security_code": "600519",
                "security_name": "贵州茅台",
                "weight_pct": 6.0,
                "rank_in_holdings": 1,
                "industry": "食品饮料",
            },
            {
                "report_date": date(2023, 12, 31),
                "asset_type": "股票",
                "security_code": "000858",
                "security_name": "五粮液",
                "weight_pct": 5.0,
                "rank_in_holdings": 2,
                "industry": "食品饮料",
            },
            {
                "report_date": date(2023, 12, 31),
                "asset_type": "股票",
                "security_code": "300750",
                "security_name": "宁德时代",
                "weight_pct": 4.0,
                "rank_in_holdings": 3,
                "industry": "电力设备",
            },
        ]
    )

    result = analyze_disclosed_holdings(current, previous)

    assert result.previous_report_date == date(2023, 12, 31)
    assert result.change_summary == {
        "new": 1,
        "increased": 1,
        "decreased": 1,
        "unchanged": 0,
        "exited": 1,
    }
    by_code = {item["security_code"]: item for item in result.holding_changes}
    assert by_code["000001"]["direction"] == "new"
    assert by_code["600519"]["direction"] == "increased"
    assert by_code["600519"]["delta_weight_pct"] == 2.5
    assert by_code["000858"]["direction"] == "decreased"
    assert by_code["300750"]["direction"] == "exited"


def test_analyze_disclosed_holdings_empty_data_needs_review() -> None:
    """Empty holdings input should produce a review warning."""
    result = analyze_disclosed_holdings(pd.DataFrame())

    assert result.disclosure_granularity == UNKNOWN_GRANULARITY
    assert result.holdings == []
    assert result.warnings == ["公开披露持仓数据为空"]
