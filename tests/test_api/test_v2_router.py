"""Phase 2 v2 Tool API tests."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.db.models import (
    AlgorithmExperiment,
    BenchmarkIndustryWeight,
    ExperimentResult,
    FundDisclosedHoldings,
    StockDaily,
)


def test_create_experiment_accepts_json_dates(
    test_client: TestClient,
    test_session: Session,
) -> None:
    response = test_client.post(
        "/api/v2/experiments",
        json={
            "experiment_name": "模拟持仓回测",
            "algorithm_name": "simulated_holding",
            "algorithm_version": "0.1.0",
            "parameters": {"max_positions": 30},
            "sample_fund_codes": ["000001"],
            "backtest_start": "2024-01-01",
            "backtest_end": "2024-12-31",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "computed"
    assert isinstance(payload["data"]["id"], str)

    exp = test_session.get(AlgorithmExperiment, int(payload["data"]["id"]))
    assert exp is not None
    assert exp.backtest_start == date(2024, 1, 1)
    assert exp.backtest_end == date(2024, 12, 31)


def test_create_dynamic_attribution_experiment_stores_parameters(
    test_client: TestClient,
    test_session: Session,
) -> None:
    response = test_client.post(
        "/api/v2/experiments",
        json={
            "experiment_name": "动态归因参数测试",
            "algorithm_name": "dynamic_attribution",
            "algorithm_version": "0.1.0",
            "parameters": {
                "benchmark_symbol": "sh000905",
                "min_return_observations": 5,
            },
            "sample_fund_codes": ["000001"],
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "computed"

    exp = test_session.get(AlgorithmExperiment, int(payload["data"]["id"]))
    assert exp is not None
    assert exp.parameters == {
        "benchmark_symbol": "sh000905",
        "min_return_observations": 5,
    }
    assert isinstance(exp.parameters["min_return_observations"], int)


def test_dynamic_attribution_readiness_endpoint_returns_candidates(
    test_client: TestClient,
    test_session: Session,
) -> None:
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
    for stock_code in ("688012", "sh000300"):
        for index in range(5):
            test_session.add(
                StockDaily(
                    stock_code=stock_code,
                    trade_date=report_date + timedelta(days=index),
                    close_price=100.0 + index,
                    data_source_level="LOCAL",
                )
            )
    test_session.add(
        BenchmarkIndustryWeight(
            benchmark_symbol="sh000300",
            snapshot_date=date(2026, 5, 29),
            classification_type="SW",
            classification_level=1,
            industry_name="电子",
            weight_pct=100.0,
            member_count=1,
            unmapped_weight_pct=0.0,
            coverage_pct=100.0,
            source_member_snapshot=date(2026, 5, 29),
            source_industry_snapshot=date(2026, 5, 29),
            algorithm_version="test",
            warnings=[],
        )
    )
    test_session.commit()

    response = test_client.get(
        "/api/v2/experiments/dynamic-attribution/readiness",
        params={
            "fund_code": "000001",
            "benchmark_symbol": "sh000300",
            "ready_only": True,
            "limit": 1,
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "computed"
    assert payload["data"]["ready"] == 1
    assert payload["data"]["total"] == 1
    assert payload["data"]["rows"][0]["fund_code"] == "000001"
    assert payload["data"]["rows"][0]["is_ready"] is True

    create_response = test_client.post(
        "/api/v2/experiments/dynamic-attribution/from-ready",
        json={
            "experiment_name": "ready attr",
            "report_date": "2026-06-01",
            "benchmark_symbol": "sh000300",
            "limit": 1,
        },
    )
    create_payload = create_response.json()
    assert create_response.status_code == 200
    assert create_payload["conclusion_status"] == "computed"
    assert create_payload["data"]["sample_fund_codes"] == ["000001"]
    assert create_payload["data"]["parameters"] == {
        "benchmark_symbol": "sh000300",
        "report_dates": ["2026-06-01"],
        "min_return_observations": 3,
        "max_benchmark_weight_snapshot_age_days": 180,
    }
    exp = test_session.get(AlgorithmExperiment, int(create_payload["data"]["experiment_id"]))
    assert exp is not None
    assert exp.algorithm_name == "dynamic_attribution"
    assert exp.sample_fund_codes == ["000001"]
    assert exp.parameters["report_dates"] == ["2026-06-01"]


def test_record_experiment_result_accepts_json_date(
    test_client: TestClient,
) -> None:
    created = test_client.post(
        "/api/v2/experiments",
        json={
            "experiment_name": "评分 IC 回测",
            "algorithm_name": "scoring",
            "algorithm_version": "0.1.0",
        },
    ).json()
    exp_id = created["data"]["id"]

    response = test_client.post(
        f"/api/v2/experiments/{exp_id}/results",
        json={
            "fund_code": "000001",
            "calc_date": "2024-06-30",
            "is_success": True,
            "metrics": {"ic": 0.03},
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "computed"
    assert isinstance(payload["data"]["id"], str)


def test_record_experiment_result_rejects_missing_experiment(
    test_client: TestClient,
    test_session: Session,
) -> None:
    response = test_client.post(
        "/api/v2/experiments/123456789/results",
        json={
            "fund_code": "000001",
            "calc_date": "2024-06-30",
            "is_success": True,
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "needs_review"
    assert test_session.query(ExperimentResult).count() == 0
