"""Phase 2B validation report tests."""

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from fund_research.db.models import (
    BenchmarkIndustryWeight,
    FundDisclosedHoldings,
    FundNAV,
    ScoringBacktest,
    StockDaily,
)
from fund_research.experiments.validation import (
    render_p2b_validation_markdown,
    run_p2b_validation_report,
    write_p2b_validation_report,
)


def _seed_p2b_fund(test_session: Session, fund_code: str, daily_return: float) -> None:
    for day in range(260):
        trade_date = date(2023, 1, 1) + timedelta(days=day)
        if trade_date.weekday() >= 5:
            continue
        test_session.add(
            FundNAV(
                fund_code=fund_code,
                trade_date=trade_date,
                unit_nav=1.0 + daily_return * day,
                daily_return=daily_return if day > 0 else None,
                data_source_level="LOCAL",
            )
        )

    for index, industry in enumerate(("tech", "finance")):
        test_session.add(
            FundDisclosedHoldings(
                fund_code=fund_code,
                report_date=date(2024, 1, 1),
                security_code=f"00000{index}",
                asset_type="股票",
                weight_pct=50.0,
                industry=industry,
                rank_in_holdings=index + 1,
                data_source_level="LOCAL",
            )
        )


def _seed_stock_daily(test_session: Session) -> None:
    for stock_code in ("000000", "000001", "sh000300"):
        price = 100.0
        for day in range(260):
            trade_date = date(2023, 1, 1) + timedelta(days=day)
            if trade_date.weekday() >= 5:
                continue
            if day > 0:
                price *= 1.001
            test_session.add(
                StockDaily(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    close_price=price,
                    daily_return=None,
                    data_source_level="LOCAL",
                )
            )
    for industry in ("tech", "finance"):
        test_session.add(
            BenchmarkIndustryWeight(
                benchmark_symbol="sh000300",
                snapshot_date=date(2024, 1, 1),
                classification_type="SW",
                classification_level=1,
                industry_name=industry,
                weight_pct=50.0,
                member_count=1,
                unmapped_weight_pct=0.0,
                coverage_pct=100.0,
                source_member_snapshot=date(2024, 1, 1),
                source_industry_snapshot=date(2024, 1, 1),
                algorithm_version="test",
                warnings=[],
            )
        )


def test_run_p2b_validation_report_builds_auditable_batch_report(test_session: Session) -> None:
    _seed_p2b_fund(test_session, "000001", 0.001)
    _seed_p2b_fund(test_session, "000002", 0.001)
    _seed_stock_daily(test_session)
    test_session.commit()

    report = run_p2b_validation_report(
        test_session,
        ["000001", "000002"],
        expected_fund_count=2,
    )

    assert report["report_type"] == "p2b_validation"
    assert report["sample_fund_count"] == 2
    assert set(report["algorithms"]) == {"simulated_holding", "dynamic_attribution", "scoring"}
    assert report["conclusion_status"] in {"estimated", "needs_review"}
    assert report["conclusion_status"] not in {"fact", "computed"}
    assert report["readiness_summary"]["dynamic_attribution"]["productization_allowed"] is False
    assert any(check["name"] == "scoring_backtest" for check in report["gate_checks"])

    sim_report = report["algorithms"]["simulated_holding"]
    assert sim_report["experiment_summary"]["fund_count"] == 2
    assert sim_report["aggregate_stats"]["mean_estimated_tracking_error"] is not None
    assert sim_report["aggregate_stats"]["mean_estimated_top10_recall"] is not None

    scoring_report = report["algorithms"]["scoring"]
    assert scoring_report["aggregate_stats"]["scoring_backtest_available"] is True
    assert test_session.query(ScoringBacktest).count() == 1
    assert scoring_report["per_fund"][0]["diagnostics"]["allow_estimated"] is True
    assert "estimated_dimensions" in scoring_report["per_fund"][0]["diagnostics"]


def test_p2b_validation_markdown_contains_gate_summary(test_session: Session) -> None:
    report = {
        "generated_at": "2026-06-16",
        "sample_fund_count": 1,
        "expected_fund_count": 30,
        "overall_conclusion": "partial",
        "conclusion_status": "estimated",
        "pipeline_gate": {"status": "partial"},
        "productization_gate": {"status": "needs_review"},
        "gate_checks": [
            {"name": "sample_size", "passed": False, "detail": "1/30 funds"},
        ],
        "readiness_summary": {
            "simulated_holding": {"level": "candidate"},
        },
        "algorithms": {
            "simulated_holding": {
                "experiment_summary": {"fund_count": 1},
                "aggregate_stats": {"success_rate": 1.0},
                "overall_conclusion": "partial",
            },
        },
        "warnings": ["sample_size not met: 1/30 funds"],
    }

    markdown = render_p2b_validation_markdown(report)
    assert "# P2B Validation Report" in markdown
    assert "sample_size" in markdown


def test_write_p2b_validation_report_creates_markdown_file(
    test_session: Session, tmp_path: Path
) -> None:
    _seed_p2b_fund(test_session, "000001", 0.001)
    _seed_stock_daily(test_session)
    test_session.commit()

    report = run_p2b_validation_report(
        test_session,
        ["000001"],
        expected_fund_count=1,
    )

    out_path = tmp_path / "report.md"
    write_p2b_validation_report(report, out_path)

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "# P2B Validation Report" in content
