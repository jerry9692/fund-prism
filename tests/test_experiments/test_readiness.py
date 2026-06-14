"""Experiment readiness checks."""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from fund_research.db.models import (
    BenchmarkIndustryWeight,
    FundDisclosedHoldings,
    StockDaily,
)
from fund_research.experiments.readiness import assess_dynamic_attribution_readiness


def _seed_market_data(
    test_session: Session,
    *,
    report_date: date,
    stock_codes: list[str],
    benchmark_symbol: str = "sh000300",
    daily_return: float | None = 0.01,
) -> None:
    for stock_code in [*stock_codes, benchmark_symbol]:
        for index in range(5):
            test_session.add(
                StockDaily(
                    stock_code=stock_code,
                    trade_date=report_date + timedelta(days=index),
                    close_price=100.0 + index,
                    daily_return=daily_return,
                    data_source_level="LOCAL",
                )
            )


def _seed_benchmark_weights(
    test_session: Session,
    *,
    snapshot_date: date,
    benchmark_symbol: str = "sh000300",
) -> None:
    for industry, weight_pct in (("电子", 60.0), ("通信", 40.0)):
        test_session.add(
            BenchmarkIndustryWeight(
                benchmark_symbol=benchmark_symbol,
                snapshot_date=snapshot_date,
                classification_type="SW",
                classification_level=1,
                industry_code=None,
                industry_name=industry,
                weight_pct=weight_pct,
                member_count=10,
                unmapped_weight_pct=0.0,
                coverage_pct=100.0,
                source_member_snapshot=snapshot_date,
                source_industry_snapshot=snapshot_date,
                algorithm_version="test",
                warnings=[],
            )
        )


def test_dynamic_attribution_readiness_rejects_future_benchmark_weight(
    test_session: Session,
) -> None:
    """A benchmark industry snapshot after the report date must not make a sample ready."""
    report_date = date(2026, 3, 31)
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=report_date,
            asset_type="股票",
            security_code="688012",
            security_name="中微公司",
            weight_pct=100.0,
            industry="电子",
            data_source_level="LOCAL",
        )
    )
    _seed_market_data(test_session, report_date=report_date, stock_codes=["688012"])
    _seed_benchmark_weights(test_session, snapshot_date=date(2026, 5, 29))
    test_session.commit()

    rows = assess_dynamic_attribution_readiness(
        test_session,
        {"000001"},
        benchmark_symbol="sh000300",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["is_ready"] is False
    assert row["benchmark_weight_snapshot_date"] is None
    assert row["benchmark_weight_future_snapshot_date"] == "2026-05-29"
    assert any("缺少不晚于报告期" in issue for issue in row["issues"])


def test_dynamic_attribution_readiness_accepts_valid_sample(
    test_session: Session,
) -> None:
    """A sample with holdings, returns, and a fresh benchmark weight snapshot is ready."""
    report_date = date(2026, 6, 1)
    test_session.add_all([
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=report_date,
            asset_type="股票",
            security_code="688012",
            security_name="中微公司",
            weight_pct=70.0,
            industry="电子",
            data_source_level="LOCAL",
        ),
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=report_date,
            asset_type="股票",
            security_code="300308",
            security_name="中际旭创",
            weight_pct=30.0,
            industry="通信",
            data_source_level="LOCAL",
        ),
    ])
    _seed_market_data(
        test_session,
        report_date=report_date,
        stock_codes=["688012", "300308"],
    )
    _seed_benchmark_weights(test_session, snapshot_date=date(2026, 5, 29))
    test_session.commit()

    rows = assess_dynamic_attribution_readiness(
        test_session,
        {"000001"},
        benchmark_symbol="sh000300",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["is_ready"] is True
    assert row["issues"] == []
    assert row["benchmark_weight_snapshot_date"] == "2026-05-29"
    assert row["benchmark_weight_snapshot_age_days"] == 3
    assert row["benchmark_weight_coverage_pct"] == 100.0
    assert row["stock_return_weight_coverage"] == 1.0


def test_dynamic_attribution_readiness_counts_close_price_observations(
    test_session: Session,
) -> None:
    """Readiness mirrors the runner, which can infer returns from close prices."""
    report_date = date(2026, 6, 1)
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=report_date,
            asset_type="股票",
            security_code="688012",
            security_name="中微公司",
            weight_pct=100.0,
            industry="电子",
            data_source_level="LOCAL",
        )
    )
    _seed_market_data(
        test_session,
        report_date=report_date,
        stock_codes=["688012"],
        daily_return=None,
    )
    _seed_benchmark_weights(test_session, snapshot_date=date(2026, 5, 29))
    test_session.commit()

    rows = assess_dynamic_attribution_readiness(
        test_session,
        {"000001"},
        benchmark_symbol="sh000300",
    )

    row = rows[0]
    assert row["is_ready"] is True
    assert row["stock_return_weight_coverage"] == 1.0
    assert row["benchmark_return_observations"] == 5
