"""Phase 2 v2 Tool API tests."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.db.models import AlgorithmExperiment, ExperimentResult


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
