"""P4.1-5 因子收益表测试 — factor_return 构造与 upsert."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.data.update import (
    build_bond_factor_rows,
    build_style_factor_rows,
    upsert_factor_returns,
)
from fund_research.db.models import (
    BondDaily,
    FactorReturn,
    StockDaily,
    YieldCurveDaily,
)

# ============================================================
# 债券因子构造
# ============================================================


def _seed_yield_curve(
    session: Session,
    curve_name: str,
    tenor: float,
    yields_pct: list[float],
    start: date = date(2026, 8, 10),
) -> None:
    session.add_all(
        [
            YieldCurveDaily(
                curve_name=curve_name,
                trade_date=start + timedelta(days=i),
                tenor_years=tenor,
                yield_pct=value,
                source_name="test",
                source_level="B",
            )
            for i, value in enumerate(yields_pct)
        ]
    )
    session.commit()


def _rows_by_factor(rows: list[dict], factor_name: str) -> dict:
    return {
        row["trade_date"]: row["factor_return"]
        for row in rows
        if row["factor_name"] == factor_name
    }


def test_build_bond_factor_rows_rate_slope_convexity_coupon(test_session: Session) -> None:
    # 10Y 国债：1.70 → 1.71 → 1.69（Δ = +0.01pp, -0.02pp）
    _seed_yield_curve(test_session, "treasury", 10.0, [1.70, 1.71, 1.69])
    # 1Y 国债：1.20 → 1.20 → 1.21
    _seed_yield_curve(test_session, "treasury", 1.0, [1.20, 1.20, 1.21])

    rows = build_bond_factor_rows(test_session)

    day2, day3 = date(2026, 8, 11), date(2026, 8, 12)
    rate = _rows_by_factor(rows, "bond_rate")
    # −10 × Δy(小数)：+0.01pp → -0.001；-0.02pp → +0.002
    assert rate[day2] == pytest.approx(-10 * 0.0001)
    assert rate[day3] == pytest.approx(-10 * -0.0002)

    slope = _rows_by_factor(rows, "bond_slope")
    # r10 - r1：day2 r1 = -1×0 = 0 → slope = -0.001；day3 r1 = -1×0.0001 → 0.002+0.0001
    assert slope[day2] == pytest.approx(-0.001)
    assert slope[day3] == pytest.approx(0.002 + 0.0001)

    convexity = _rows_by_factor(rows, "bond_convexity")
    assert convexity[day2] == pytest.approx(0.5 * 100 * 0.0001**2)

    coupon = _rows_by_factor(rows, "bond_coupon")
    assert coupon[day2] == pytest.approx(0.0120 / 252)
    assert coupon[day3] == pytest.approx(0.0121 / 252)


def test_build_bond_factor_rows_credit_and_sink(test_session: Session) -> None:
    _seed_yield_curve(test_session, "treasury", 3.0, [1.30, 1.31, 1.31])
    # AAA 利差：(1.80-1.30)=0.50 → (1.83-1.31)=0.52 → (1.82-1.31)=0.51
    _seed_yield_curve(test_session, "medium_term_note_aaa", 3.0, [1.80, 1.83, 1.82])
    # AA 利差：0.90 → 0.94 → 0.92
    _seed_yield_curve(test_session, "medium_term_note_aa", 3.0, [2.20, 2.25, 2.23])

    rows = build_bond_factor_rows(test_session)

    day2, day3 = date(2026, 8, 11), date(2026, 8, 12)
    aaa = _rows_by_factor(rows, "bond_credit_aaa")
    aa = _rows_by_factor(rows, "bond_credit_aa")
    sink = _rows_by_factor(rows, "bond_credit_sink")
    # −3 × Δ利差(小数)
    assert aaa[day2] == pytest.approx(-3 * 0.0002)
    assert aaa[day3] == pytest.approx(-3 * -0.0001)
    assert aa[day2] == pytest.approx(-3 * 0.0004)
    assert aa[day3] == pytest.approx(-3 * -0.0002)
    assert sink[day2] == pytest.approx(aa[day2] - aaa[day2])
    assert sink[day3] == pytest.approx(aa[day3] - aaa[day3])


def test_build_bond_factor_rows_convertible_equal_weight(test_session: Session) -> None:
    test_session.add_all(
        [
            BondDaily(
                bond_code="128039.SZ",
                trade_date=date(2026, 8, 11),
                close_price=105.0,
                daily_return=0.01,
                source_name="test",
                source_level="B",
            ),
            BondDaily(
                bond_code="110080.SH",
                trade_date=date(2026, 8, 11),
                close_price=102.0,
                daily_return=0.03,
                source_name="test",
                source_level="B",
            ),
        ]
    )
    test_session.commit()

    rows = build_bond_factor_rows(test_session)

    convertible = _rows_by_factor(rows, "bond_convertible")
    assert convertible[date(2026, 8, 11)] == pytest.approx((0.01 + 0.03) / 2)


def test_build_style_factor_rows_uses_index_returns(test_session: Session) -> None:
    # daily_return 为空 → 收盘价 pct_change 兜底
    test_session.add_all(
        [
            StockDaily(
                stock_code="sh000300",
                trade_date=date(2026, 8, 10) + timedelta(days=i),
                close_price=close,
            )
            for i, close in enumerate([4000.0, 4040.0, 4020.0])
        ]
    )
    test_session.commit()

    rows = build_style_factor_rows(test_session)

    large_cap = _rows_by_factor(rows, "style_large_cap")
    assert large_cap[date(2026, 8, 11)] == pytest.approx(0.01)
    assert large_cap[date(2026, 8, 12)] == pytest.approx(-20.0 / 4040.0)


# ============================================================
# upsert 工作流
# ============================================================


def test_upsert_factor_returns_full_and_filtered(test_session: Session) -> None:
    _seed_yield_curve(test_session, "treasury", 10.0, [1.70, 1.71])
    _seed_yield_curve(test_session, "treasury", 1.0, [1.20, 1.20])

    summary = upsert_factor_returns(test_session)

    assert summary.inserted > 0
    names = set(
        test_session.scalars(select(FactorReturn.factor_name).distinct()).all()
    )
    assert {"bond_rate", "bond_slope", "bond_coupon", "bond_convexity"} <= names
    row = test_session.scalar(
        select(FactorReturn)
        .where(FactorReturn.factor_name == "bond_rate")
        .where(FactorReturn.trade_date == date(2026, 8, 11))
    )
    assert row is not None
    assert row.factor_return == pytest.approx(-10 * 0.0001)
    assert row.source_level == "LOCAL"


def test_upsert_factor_returns_is_idempotent(test_session: Session) -> None:
    _seed_yield_curve(test_session, "treasury", 10.0, [1.70, 1.71])
    _seed_yield_curve(test_session, "treasury", 1.0, [1.20, 1.20])

    first = upsert_factor_returns(test_session, factor_names={"bond_rate"})
    test_session.commit()
    second = upsert_factor_returns(test_session, factor_names={"bond_rate"})

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.updated == 1


def test_upsert_factor_returns_unknown_factor_and_empty(test_session: Session) -> None:
    summary = upsert_factor_returns(test_session, factor_names={"not_a_factor"})

    assert summary.requested == 0
    assert any("未知因子" in warning for warning in summary.warnings)
    assert test_session.scalar(select(FactorReturn)) is None


def test_upsert_factor_returns_dry_run_and_window(test_session: Session) -> None:
    _seed_yield_curve(test_session, "treasury", 10.0, [1.70, 1.71, 1.69])
    _seed_yield_curve(test_session, "treasury", 1.0, [1.20, 1.20, 1.21])

    dry = upsert_factor_returns(
        test_session, factor_names={"bond_rate"}, dry_run=True
    )
    assert dry.dry_run is True
    assert dry.inserted == 2
    assert test_session.scalar(select(FactorReturn)) is None

    windowed = upsert_factor_returns(
        test_session,
        factor_names={"bond_rate"},
        start_date=date(2026, 8, 12),
    )
    assert windowed.inserted == 1
    row = test_session.scalar(select(FactorReturn))
    assert row.trade_date == date(2026, 8, 12)
