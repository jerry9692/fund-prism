"""Phase 2 v2 Tool API tests."""

import json
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.db.models import (
    AlgorithmExperiment,
    BenchmarkIndustryWeight,
    ExperimentResult,
    FundDisclosedHoldings,
    FundNAV,
    ScoringBacktest,
    ScoringResult,
    StockDaily,
)


def _minimal_p2b_report(
    report_id: str,
    generated_at: str,
    *,
    sample_size_passed: bool,
    success_rate: float,
) -> dict:
    return {
        "report_type": "p2b_validation",
        "report_id": report_id,
        "generated_at": generated_at,
        "expected_fund_count": 30,
        "sample_fund_count": 30,
        "pipeline_gate": {"status": "pass" if sample_size_passed else "partial"},
        "productization_gate": {"status": "needs_review"},
        "conclusion_status": "needs_review",
        "gate_checks": [
            {
                "name": "sample_size",
                "passed": sample_size_passed,
                "detail": "30/30 funds" if sample_size_passed else "20/30 funds",
            },
        ],
        "readiness_summary": {
            "simulated_holding": {
                "level": "candidate",
                "productization_allowed": False,
                "reason": "estimated",
            },
        },
        "algorithms": {
            "simulated_holding": {
                "experiment_summary": {
                    "fund_count": 30,
                    "success_count": int(success_rate * 30),
                    "failure_count": 30 - int(success_rate * 30),
                },
                "aggregate_stats": {"success_rate": success_rate},
                "per_fund": [],
                "overall_conclusion": "pass" if sample_size_passed else "partial",
                "conclusion_status": "estimated",
                "warnings": [],
            },
        },
        "warnings": [],
    }


def test_get_latest_p2b_validation_report_reads_report_file(
    test_client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    from fund_research.api import v2_router

    report_dir = tmp_path / "docs" / "phase2"
    report_dir.mkdir(parents=True)
    report_dir.joinpath("p2b_validation_report.json").write_text(
        json.dumps({
            "report_type": "p2b_validation",
            "pipeline_gate": {"status": "pass"},
            "productization_gate": {"status": "needs_review"},
            "conclusion_status": "needs_review",
            "warnings": ["产品化门禁未通过"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(v2_router, "_project_root", lambda: tmp_path)

    response = test_client.get("/api/v2/validation/p2b/latest")

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "needs_review"
    assert payload["data"]["pipeline_gate"]["status"] == "pass"
    assert payload["data"]["productization_gate"]["status"] == "needs_review"


def test_list_p2b_validation_reports_includes_latest_and_history(
    test_client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    from fund_research.api import v2_router

    report_dir = tmp_path / "docs" / "phase2"
    history_dir = report_dir / "p2b_validation_reports"
    history_dir.mkdir(parents=True)
    report_dir.joinpath("p2b_validation_report.json").write_text(
        json.dumps(
            _minimal_p2b_report("new", "2026-06-16T12:00:00", sample_size_passed=True, success_rate=1.0),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    history_dir.joinpath("old.json").write_text(
        json.dumps(
            _minimal_p2b_report("old", "2026-06-15T12:00:00", sample_size_passed=False, success_rate=0.8),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(v2_router, "_project_root", lambda: tmp_path)

    response = test_client.get("/api/v2/validation/p2b/reports")

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "computed"
    assert payload["data"]["total"] == 2
    assert [item["report_id"] for item in payload["data"]["reports"]] == ["new", "old"]
    assert payload["data"]["reports"][0]["is_latest"] is True


def test_compare_p2b_validation_reports_returns_gate_and_metric_deltas(
    test_client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    from fund_research.api import v2_router

    report_dir = tmp_path / "docs" / "phase2"
    history_dir = report_dir / "p2b_validation_reports"
    history_dir.mkdir(parents=True)
    report_dir.joinpath("p2b_validation_report.json").write_text(
        json.dumps(
            _minimal_p2b_report("new", "2026-06-16T12:00:00", sample_size_passed=True, success_rate=1.0),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    history_dir.joinpath("old.json").write_text(
        json.dumps(
            _minimal_p2b_report("old", "2026-06-15T12:00:00", sample_size_passed=False, success_rate=0.8),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(v2_router, "_project_root", lambda: tmp_path)

    response = test_client.get(
        "/api/v2/validation/p2b/compare",
        params={"base_report_id": "old", "target_report_id": "latest"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "observation"
    assert payload["data"]["changed"] is True
    assert payload["data"]["gate_changes"][0]["changed"] is True
    delta = payload["data"]["algorithm_changes"][0]["metric_deltas"]["success_rate"]["delta"]
    assert round(delta, 4) == 0.2


def test_rerun_p2b_validation_report_starts_task_and_status_endpoint(
    test_client: TestClient,
    monkeypatch,
) -> None:
    from fund_research.api import v2_router

    class ImmediateThread:
        def __init__(self, target, kwargs, daemon):  # noqa: ANN001
            self.target = target
            self.kwargs = kwargs
            self.daemon = daemon

        def start(self) -> None:
            self.target(**self.kwargs)

    def fake_run_task(task_id: str, *, algorithms: list[str], limit: int | None) -> None:
        v2_router._update_p2b_task(
            task_id,
            status="completed",
            stage="completed",
            message="done",
            percent=100,
            algorithms=algorithms,
            limit=limit,
            report_id="fake-report",
        )

    v2_router._P2B_TASKS.clear()
    monkeypatch.setattr(v2_router.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(v2_router, "_run_p2b_validation_task", fake_run_task)

    response = test_client.post(
        "/api/v2/validation/p2b/rerun",
        json={"algorithms": ["simulated_holding"], "limit": 1},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "observation"
    task_id = payload["data"]["task_id"]
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["report_id"] == "fake-report"

    status_response = test_client.get(f"/api/v2/validation/p2b/tasks/{task_id}")
    status_payload = status_response.json()
    assert status_payload["conclusion_status"] == "computed"
    assert status_payload["data"]["status"] == "completed"


def test_get_p2b_validation_task_returns_needs_review_for_missing_task(
    test_client: TestClient,
) -> None:
    response = test_client.get("/api/v2/validation/p2b/tasks/missing")

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "needs_review"


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


def test_list_scoring_backtests_route_is_not_captured_by_score_version(
    test_client: TestClient,
    test_session: Session,
) -> None:
    test_session.add(
        ScoringBacktest(
            score_version="score-bt-test",
            backtest_date=date(2026, 6, 16),
            group_count=5,
            group_results={"future_return": {"0": 0.01, "4": 0.05}},
            monotonicity_check=True,
            ic_mean=0.12,
            ic_ir=0.8,
            detail={"experiment_id": 1},
        )
    )
    test_session.commit()

    response = test_client.get("/api/v2/analysis/scoring/backtest")

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "computed"
    assert payload["data"]["total"] == 1
    assert payload["data"]["backtests"][0]["score_version"] == "score-bt-test"


def test_scoring_endpoint_keeps_estimated_scores_observational(
    test_client: TestClient,
    test_session: Session,
) -> None:
    for fund_index, fund_code in enumerate(("000001", "000002")):
        nav = 1.0
        for day in range(90):
            daily_return = 0.001 + fund_index * 0.0002 if day > 0 else None
            if daily_return is not None:
                nav *= 1 + daily_return
            test_session.add(
                FundNAV(
                    fund_code=fund_code,
                    trade_date=date(2024, 1, 1) + timedelta(days=day),
                    unit_nav=nav,
                    daily_return=daily_return,
                    data_source_level="LOCAL",
                )
            )
    test_session.commit()

    response = test_client.post(
        "/api/v2/analysis/scoring",
        json={"fund_codes": ["000001", "000002"]},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["conclusion_status"] == "observation"
    assert payload["warnings"] == ["评分包含 estimated 维度，仅作为实验/观察结果"]
    score_version = payload["data"]["score_version"]
    assert score_version != "0.1.0"

    rows = test_session.query(ScoringResult).all()
    assert {row.score_version for row in rows} == {score_version}
    assert all(row.contains_estimated for row in rows)
    assert all(row.conclusion_status == "needs_review" for row in rows)

    get_response = test_client.get(f"/api/v2/analysis/scoring/{score_version}")
    get_payload = get_response.json()
    assert get_response.status_code == 200
    assert get_payload["conclusion_status"] == "observation"


# ============================================================
# Reviewer Annotation tests
# ============================================================


def test_reviewer_annotation_crud_lifecycle(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Create, read, update, delete a reviewer annotation."""
    # Create
    create_resp = test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000001",
            "annotation_type": "note",
            "target_module": "scoring",
            "detail": {"score_version": "0.3.0", "concern": "low coverage"},
            "reason": "维度覆盖不足，需人工复核",
        },
    )
    assert create_resp.status_code == 200
    create_data = create_resp.json()["data"]
    assert create_data["fund_code"] == "000001"
    assert create_data["annotation_type"] == "note"
    assert create_data["target_module"] == "scoring"
    annotation_id = create_data["id"]

    # Get by id
    get_resp = test_client.get(f"/api/v2/reviewer-annotations/{annotation_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["id"] == annotation_id

    # List with filter
    list_resp = test_client.get(
        "/api/v2/reviewer-annotations",
        params={"fund_code": "000001", "annotation_type": "note"},
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()["data"]
    assert list_data["count"] >= 1
    assert any(a["id"] == annotation_id for a in list_data["annotations"])

    # Update
    update_resp = test_client.patch(
        f"/api/v2/reviewer-annotations/{annotation_id}",
        json={
            "annotation_type": "lock",
            "reason": "锁定评分结果，等待数据补全后重新评估",
        },
    )
    assert update_resp.status_code == 200
    update_data = update_resp.json()["data"]
    assert update_data["annotation_type"] == "lock"
    assert "锁定" in update_data["reason"]

    # Delete
    del_resp = test_client.delete(f"/api/v2/reviewer-annotations/{annotation_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["data"]["deleted"] is True

    # Confirm deleted
    get_after_del = test_client.get(f"/api/v2/reviewer-annotations/{annotation_id}")
    assert get_after_del.status_code == 200
    assert get_after_del.json()["data"] is None


def test_reviewer_annotation_rejects_invalid_type(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Invalid annotation_type should return needs_review with warning."""
    resp = test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000001",
            "annotation_type": "invalid_type",
            "reason": "test",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["conclusion_status"] == "needs_review"
    assert any("annotation_type" in w for w in payload["warnings"])


def test_reviewer_annotation_rejects_invalid_target_module(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Invalid target_module should return needs_review with warning."""
    resp = test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000001",
            "annotation_type": "note",
            "target_module": "invalid_module",
            "reason": "test",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["conclusion_status"] == "needs_review"
    assert any("target_module" in w for w in payload["warnings"])


def test_fund_review_status_aggregates_annotations(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Fund review status should aggregate multiple annotations into effective_status."""
    # Create an exclude annotation
    test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000002",
            "annotation_type": "exclude",
            "target_module": "scoring",
            "reason": "数据质量问题，排除出默认结论",
        },
    )
    # Create a note annotation
    test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000002",
            "annotation_type": "note",
            "reason": "已通知数据团队补全",
        },
    )

    status_resp = test_client.get("/api/v2/reviewer-annotations/funds/000002/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()["data"]
    assert status_data["fund_code"] == "000002"
    assert status_data["annotation_count"] >= 2
    assert status_data["is_excluded"] is True
    assert status_data["effective_status"] == "excluded"


def test_fund_review_status_open_when_no_annotations(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Fund with no annotations should have effective_status='open'."""
    status_resp = test_client.get("/api/v2/reviewer-annotations/funds/999999/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()["data"]
    assert status_data["annotation_count"] == 0
    assert status_data["is_locked"] is False
    assert status_data["is_excluded"] is False
    assert status_data["is_approved"] is False
    assert status_data["effective_status"] == "open"


def test_fund_review_status_priority_exclude_over_lock(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """exclude should take priority over lock in effective_status."""
    test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000003",
            "annotation_type": "lock",
            "reason": "临时锁定",
        },
    )
    test_client.post(
        "/api/v2/reviewer-annotations",
        json={
            "fund_code": "000003",
            "annotation_type": "exclude",
            "reason": "最终排除",
        },
    )

    status_resp = test_client.get("/api/v2/reviewer-annotations/funds/000003/status")
    status_data = status_resp.json()["data"]
    assert status_data["is_locked"] is True
    assert status_data["is_excluded"] is True
    assert status_data["effective_status"] == "excluded"
