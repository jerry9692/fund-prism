"""Same-category ranking tests (requirements v0.4 §6.1.4.2 / §6.1.4.5)."""

import math

import pandas as pd
import pytest

from fund_research.analysis.rank import (
    CategoryRank,
    compute_category_ranks,
    rank_in_category,
)

# ------------------------------------------------------------
# rank_in_category (single-fund API)
# ------------------------------------------------------------


def test_rank_in_category_highest_value_ranks_first_by_default() -> None:
    """ascending=False (default): highest metric value → rank 1."""
    values = {"001": 0.20, "002": 0.10, "003": 0.15}

    result = rank_in_category(values, "001", sub_category="主动权益")

    assert result is not None
    assert result.rank == 1
    assert result.total == 3
    assert result.rank_text == "1/3"
    # percentile = (3 - 1) / (3 - 1) = 1.0 (top)
    assert result.percentile == pytest.approx(1.0)
    assert result.sub_category == "主动权益"


def test_rank_in_category_worst_fund_gets_last_rank() -> None:
    values = {"001": 0.20, "002": 0.10, "003": 0.15}

    result = rank_in_category(values, "002")

    assert result is not None
    assert result.rank == 3
    assert result.percentile == pytest.approx(0.0)


def test_rank_in_category_ascending_flips_direction() -> None:
    """ascending=True: lowest value is best (rank 1) — for volatility etc."""
    values = {"001": 0.20, "002": 0.10, "003": 0.15}

    result = rank_in_category(values, "002", ascending=True)

    assert result is not None
    assert result.rank == 1  # lowest volatility = best
    assert result.percentile == pytest.approx(1.0)


def test_rank_in_category_ties_share_min_rank() -> None:
    """Tied funds share the same rank (competition ranking, method='min')."""
    values = {"001": 0.20, "002": 0.20, "003": 0.10}

    r1 = rank_in_category(values, "001")
    r2 = rank_in_category(values, "002")
    r3 = rank_in_category(values, "003")

    assert r1 is not None and r2 is not None and r3 is not None
    # 001 and 002 tie at rank 1, 003 gets rank 3 (skips 2)
    assert r1.rank == 1
    assert r2.rank == 1
    assert r3.rank == 3
    assert r1.rank_text == "1/3"
    assert r3.rank_text == "3/3"


def test_rank_in_category_single_fund_group_returns_none_percentile() -> None:
    """Group with 1 fund: rank=1, percentile=None (undefined)."""
    values = {"001": 0.20}

    result = rank_in_category(values, "001")

    assert result is not None
    assert result.rank == 1
    assert result.total == 1
    assert result.percentile is None
    assert result.rank_text == "1/1"


def test_rank_in_category_returns_none_when_fund_absent() -> None:
    values = {"001": 0.20}

    assert rank_in_category(values, "999") is None


def test_rank_in_category_handles_nan_values() -> None:
    """NaN entries are dropped before ranking."""
    values = {"001": 0.20, "002": float("nan"), "003": 0.10}

    r1 = rank_in_category(values, "001")
    r3 = rank_in_category(values, "003")

    assert r1 is not None and r3 is not None
    assert r1.total == 2  # NaN dropped
    assert r1.rank == 1
    assert r3.rank == 2


# ------------------------------------------------------------
# compute_category_ranks (batch API)
# ------------------------------------------------------------


def test_compute_category_ranks_ranks_within_each_group() -> None:
    """Ranks are computed independently within each sub_category group."""
    df = pd.DataFrame(
        [
            {"fund_code": "001", "sub_category": "主动权益", "return": 0.20},
            {"fund_code": "002", "sub_category": "主动权益", "return": 0.10},
            {"fund_code": "003", "sub_category": "指数基金", "return": 0.15},
            {"fund_code": "004", "sub_category": "指数基金", "return": 0.05},
        ]
    )

    result = compute_category_ranks(df, "return")

    by_fund = result.set_index("fund_code").to_dict(orient="index")
    # 主动权益 group: 001 > 002
    assert by_fund["001"]["rank"] == 1
    assert by_fund["002"]["rank"] == 2
    assert by_fund["001"]["total"] == 2
    # 指数基金 group: 003 > 004
    assert by_fund["003"]["rank"] == 1
    assert by_fund["004"]["rank"] == 2
    assert by_fund["003"]["total"] == 2
    # rank_text format
    assert by_fund["001"]["rank_text"] == "1/2"


def test_compute_category_ranks_handles_ties() -> None:
    """Tied funds share the same rank within their group."""
    df = pd.DataFrame(
        [
            {"fund_code": "001", "sub_category": "A", "sharpe": 1.5},
            {"fund_code": "002", "sub_category": "A", "sharpe": 1.5},
            {"fund_code": "003", "sub_category": "A", "sharpe": 0.5},
        ]
    )

    result = compute_category_ranks(df, "sharpe")
    by_fund = result.set_index("fund_code").to_dict(orient="index")

    assert by_fund["001"]["rank"] == 1
    assert by_fund["002"]["rank"] == 1
    assert by_fund["003"]["rank"] == 3  # skips 2


def test_compute_category_ranks_single_fund_group() -> None:
    """A group with only one fund gets rank=1, percentile=<NA>."""
    df = pd.DataFrame(
        [
            {"fund_code": "001", "sub_category": "A", "return": 0.10},
            {"fund_code": "002", "sub_category": "B", "return": 0.20},
        ]
    )

    result = compute_category_ranks(df, "return")
    by_fund = result.set_index("fund_code").to_dict(orient="index")

    assert by_fund["001"]["rank"] == 1
    assert by_fund["001"]["total"] == 1
    assert pd.isna(by_fund["001"]["percentile"])
    assert by_fund["001"]["rank_text"] == "1/1"


def test_compute_category_ranks_nan_metric_excluded_from_total() -> None:
    """Funds with NaN metric are excluded from the group total and get rank=<NA>."""
    df = pd.DataFrame(
        [
            {"fund_code": "001", "sub_category": "A", "return": 0.20},
            {"fund_code": "002", "sub_category": "A", "return": float("nan")},
            {"fund_code": "003", "sub_category": "A", "return": 0.10},
        ]
    )

    result = compute_category_ranks(df, "return")
    by_fund = result.set_index("fund_code").to_dict(orient="index")

    # 002 has NaN → rank=<NA>, but total counts only valid funds (2)
    assert pd.isna(by_fund["002"]["rank"])
    assert pd.isna(by_fund["002"]["percentile"])
    assert by_fund["002"]["total"] == 2
    # 001 and 003 ranked among the 2 valid funds
    assert by_fund["001"]["rank"] == 1
    assert by_fund["001"]["total"] == 2
    assert by_fund["003"]["rank"] == 2


def test_compute_category_ranks_ascending_for_risk_metrics() -> None:
    """ascending=True ranks lowest value as best (volatility, drawdown)."""
    df = pd.DataFrame(
        [
            {"fund_code": "001", "sub_category": "A", "volatility": 0.20},
            {"fund_code": "002", "sub_category": "A", "volatility": 0.10},
            {"fund_code": "003", "sub_category": "A", "volatility": 0.15},
        ]
    )

    result = compute_category_ranks(df, "volatility", ascending=True)
    by_fund = result.set_index("fund_code").to_dict(orient="index")

    # Lowest volatility (002) is best → rank 1
    assert by_fund["002"]["rank"] == 1
    assert by_fund["003"]["rank"] == 2
    assert by_fund["001"]["rank"] == 3


def test_compute_category_ranks_raises_on_missing_columns() -> None:
    df = pd.DataFrame([{"fund_code": "001", "sub_category": "A"}])

    with pytest.raises(ValueError, match="缺少列"):
        compute_category_ranks(df, "return")


def test_compute_category_ranks_empty_dataframe_returns_empty() -> None:
    df = pd.DataFrame(columns=["fund_code", "sub_category", "return"])

    result = compute_category_ranks(df, "return")

    assert result.empty
    assert "rank_text" in result.columns


def test_category_rank_to_data_roundtrip() -> None:
    """CategoryRank.to_data() exposes all fields for API serialization."""
    rank = CategoryRank(
        fund_code="001",
        sub_category="主动权益",
        metric_value=0.20,
        rank=1,
        total=3,
        percentile=1.0,
        rank_text="1/3",
    )

    data = rank.to_data()
    assert data["fund_code"] == "001"
    assert data["rank"] == 1
    assert data["total"] == 3
    assert math.isclose(data["percentile"], 1.0)
    assert data["rank_text"] == "1/3"
