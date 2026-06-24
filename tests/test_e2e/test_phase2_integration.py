"""Phase 2 end-to-end integration tests.

Validates the full闭环 for Phase 2 features:
- Reviewer annotation CRUD + fund status aggregation
- Simulated holding result query
- Scoring API + backtest persistence

These tests use the FastAPI TestClient with an in-memory SQLite database,
exercising the real API endpoints (not mocked) to verify the contract
between frontend API client expectations and backend responses.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.core.enums import ConclusionStatus
from fund_research.db.models import SimulatedHoldingResult


class TestReviewerAnnotationE2E:
    """End-to-end reviewer annotation workflow."""

    def test_full_annotation_lifecycle(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Create → list → update → status → delete → verify gone."""
        # 1. Create a note annotation
        create_resp = test_client.post(
            "/api/v2/reviewer-annotations",
            json={
                "fund_code": "E2E001",
                "annotation_type": "note",
                "target_module": "scoring",
                "detail": {"concern": "low dimension coverage"},
                "reason": "维度覆盖不足，需人工复核",
            },
        )
        assert create_resp.status_code == 200
        assert create_resp.json()["conclusion_status"] == ConclusionStatus.FACT.value
        annotation_id = create_resp.json()["data"]["id"]
        assert annotation_id > 0

        # 2. List annotations for the fund
        list_resp = test_client.get(
            "/api/v2/reviewer-annotations",
            params={"fund_code": "E2E001"},
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()["data"]
        assert list_data["count"] == 1
        assert list_data["annotations"][0]["id"] == annotation_id

        # 3. Get fund review status — should be "open" (only a note)
        status_resp = test_client.get(
            "/api/v2/reviewer-annotations/funds/E2E001/status"
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json()["data"]
        assert status_data["effective_status"] == "open"
        assert status_data["is_locked"] is False
        assert status_data["is_excluded"] is False

        # 4. Update to "exclude"
        update_resp = test_client.patch(
            f"/api/v2/reviewer-annotations/{annotation_id}",
            json={
                "annotation_type": "exclude",
                "reason": "数据质量问题，排除出默认结论",
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["annotation_type"] == "exclude"

        # 5. Status should now be "excluded"
        status_resp2 = test_client.get(
            "/api/v2/reviewer-annotations/funds/E2E001/status"
        )
        status_data2 = status_resp2.json()["data"]
        assert status_data2["effective_status"] == "excluded"
        assert status_data2["is_excluded"] is True

        # 6. Delete
        del_resp = test_client.delete(
            f"/api/v2/reviewer-annotations/{annotation_id}"
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["data"]["deleted"] is True

        # 7. Verify gone
        get_resp = test_client.get(
            f"/api/v2/reviewer-annotations/{annotation_id}"
        )
        assert get_resp.json()["data"] is None

    def test_priority_excluded_over_locked(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """exclude should take priority over lock in effective_status."""
        test_client.post(
            "/api/v2/reviewer-annotations",
            json={
                "fund_code": "E2E002",
                "annotation_type": "lock",
                "reason": "临时锁定",
            },
        )
        test_client.post(
            "/api/v2/reviewer-annotations",
            json={
                "fund_code": "E2E002",
                "annotation_type": "exclude",
                "reason": "最终排除",
            },
        )
        status_resp = test_client.get(
            "/api/v2/reviewer-annotations/funds/E2E002/status"
        )
        status_data = status_resp.json()["data"]
        assert status_data["is_locked"] is True
        assert status_data["is_excluded"] is True
        assert status_data["effective_status"] == "excluded"

    def test_invalid_annotation_type_rejected(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Invalid annotation_type returns needs_review with warning."""
        resp = test_client.post(
            "/api/v2/reviewer-annotations",
            json={
                "fund_code": "E2E003",
                "annotation_type": "invalid",
                "reason": "test",
            },
        )
        payload = resp.json()
        assert payload["conclusion_status"] == ConclusionStatus.NEEDS_REVIEW.value
        assert any("annotation_type" in w for w in payload["warnings"])


class TestSimulatedHoldingE2E:
    """End-to-end simulated holding query."""

    def test_query_empty_fund_returns_estimated(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Querying a fund with no results returns estimated status."""
        resp = test_client.get(
            "/api/v2/analysis/simulated-holding",
            params={"fund_code": "EMPTY001"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        # The endpoint always returns estimated conclusion_status
        assert payload["conclusion_status"] == ConclusionStatus.ESTIMATED.value
        assert payload["data"]["count"] == 0
        assert payload["data"]["results"] == []

    def test_query_with_persisted_result(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Query after persisting a result returns it with estimated label."""
        # Insert a fake simulated holding result
        row = SimulatedHoldingResult(
            fund_code="E2E_SH_001",
            calc_date=date(2025, 6, 24),
            algorithm_name="simulated_holding",
            algorithm_version="0.1.0",
            parameters={"method": "optimized", "max_positions": 20},
            holdings_detail=[
                {"stock_code": "600519", "stock_name": "贵州茅台",
                 "estimated_weight": 0.085, "industry": "食品饮料"},
                {"stock_code": "000858", "stock_name": "五粮液",
                 "estimated_weight": 0.062, "industry": "食品饮料"},
            ],
            tracking_error=0.0096,
            daily_rmse=0.0012,
            industry_correlation=0.85,
            top10_recall=0.9,
            stock_weight_pct=92.0,
            bond_weight_pct=3.0,
            cash_weight_pct=5.0,
            confidence="low",
            conclusion_status="estimated",
            is_backtest=False,
            warnings=["estimated_result"],
            input_coverage=85.0,
        )
        test_session.add(row)
        test_session.commit()

        resp = test_client.get(
            "/api/v2/analysis/simulated-holding",
            params={"fund_code": "E2E_SH_001"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["conclusion_status"] == ConclusionStatus.ESTIMATED.value
        data = payload["data"]
        assert data["count"] == 1
        result = data["results"][0]
        assert result["fund_code"] == "E2E_SH_001"
        assert result["tracking_error"] == pytest.approx(0.0096)
        assert result["top10_recall"] == pytest.approx(0.9)
        assert len(result["holdings_detail"]) == 2
        assert result["conclusion_status"] == "estimated"


class TestScoringE2E:
    """End-to-end scoring API contract."""

    def test_scoring_endpoint_returns_observation_for_minimal_data(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Scoring with minimal data returns observation/needs_review status."""
        resp = test_client.post(
            "/api/v2/analysis/scoring",
            json={
                "fund_codes": ["E2E_S_001", "E2E_S_002"],
                "preset": "均衡型",
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        # With no data, conclusion_status should be observation or needs_review
        assert payload["conclusion_status"] in (
            ConclusionStatus.OBSERVATION.value,
            ConclusionStatus.NEEDS_REVIEW.value,
        )

    def test_scoring_backtest_list_empty(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Backtest list endpoint returns valid structure when empty."""
        resp = test_client.get("/api/v2/analysis/scoring/backtest")
        assert resp.status_code == 200
        payload = resp.json()
        assert "data" in payload
        assert "backtests" in payload["data"]
        assert "total" in payload["data"]


class TestPhase2APIContract:
    """Verify API response contract matches frontend expectations."""

    def test_reviewer_annotation_response_has_required_fields(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Annotation response must include all fields the frontend expects."""
        resp = test_client.post(
            "/api/v2/reviewer-annotations",
            json={
                "fund_code": "E2E_CONTRACT",
                "annotation_type": "approve",
                "target_module": "simulated_holding",
                "reason": "contract test",
            },
        )
        data = resp.json()["data"]
        # Fields expected by ReviewerAnnotation TypeScript interface
        required_fields = {
            "id", "fund_code", "annotation_type", "target_module",
            "detail", "reason", "evidence_id", "created_at",
        }
        assert required_fields.issubset(data.keys())

    def test_fund_review_status_response_has_required_fields(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Fund status response must include all fields the frontend expects."""
        test_client.post(
            "/api/v2/reviewer-annotations",
            json={
                "fund_code": "E2E_STATUS",
                "annotation_type": "note",
                "reason": "status test",
            },
        )
        resp = test_client.get(
            "/api/v2/reviewer-annotations/funds/E2E_STATUS/status"
        )
        data = resp.json()["data"]
        # Fields expected by FundReviewStatus TypeScript interface
        required_fields = {
            "fund_code", "annotation_count", "is_locked",
            "is_excluded", "is_approved", "effective_status", "annotations",
        }
        assert required_fields.issubset(data.keys())

    def test_simulated_holding_response_has_required_fields(
        self,
        test_client: TestClient,
        test_session: Session,
    ) -> None:
        """Simulated holding response must include all fields the frontend expects."""
        row = SimulatedHoldingResult(
            fund_code="E2E_SH_CONTRACT",
            calc_date=date(2025, 6, 24),
            algorithm_name="simulated_holding",
            algorithm_version="0.1.0",
            parameters={"method": "naive"},
            holdings_detail=[],
            tracking_error=0.01,
            daily_rmse=0.002,
            industry_correlation=0.8,
            top10_recall=0.95,
            stock_weight_pct=90.0,
            bond_weight_pct=5.0,
            cash_weight_pct=5.0,
            confidence="low",
            conclusion_status="estimated",
            is_backtest=False,
            warnings=[],
            input_coverage=80.0,
        )
        test_session.add(row)
        test_session.commit()

        resp = test_client.get(
            "/api/v2/analysis/simulated-holding",
            params={"fund_code": "E2E_SH_CONTRACT"},
        )
        result = resp.json()["data"]["results"][0]
        # Fields expected by SimulatedHoldingResult TypeScript interface
        required_fields = {
            "id", "fund_code", "calc_date", "algorithm_name",
            "algorithm_version", "parameters", "holdings_detail",
            "tracking_error", "daily_rmse", "industry_correlation",
            "top10_recall", "stock_weight_pct", "bond_weight_pct",
            "cash_weight_pct", "confidence", "conclusion_status",
            "is_backtest", "backtest_report_date", "warnings",
            "input_coverage", "created_at",
        }
        assert required_fields.issubset(result.keys())
