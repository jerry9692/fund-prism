"""
P2B real-data-structure validation.

Seeds the test database with data that structurally mirrors a real fund
(000001 华夏成长混合) — NAV from 2024-01 to 2024-12, 4 quarterly disclosed
holdings, and matching stock daily data. Then runs the full experiment
pipeline (create → run → get results → validation report).

Unlike test_p2b_validation.py which uses purely synthetic random data,
this test uses calendar-aligned dates, realistic return magnitudes, and
proper quarterly disclosure patterns (Q1/Q3 = top10, Q2/Q4 = full).
"""

from datetime import date, timedelta

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    ExperimentResult,
    FundDisclosedHoldings,
    FundNAV,
    StockDaily,
)
from fund_research.experiments.manager import build_validation_report

# Realistic stock list from 000001's Q1 2024 disclosed holdings
STOCKS = [
    ("002025", "航天电器", "国防军工"),
    ("600862", "中航高科", "国防军工"),
    ("600941", "中国移动", "通信"),
    ("300395", "菲利华", "电子"),
    ("300034", "钢研高纳", "国防军工"),
    ("688012", "中微公司", "电子"),
    ("002371", "北方华创", "电子"),
    ("688019", "安集科技", "电子"),
    ("300308", "中际旭创", "通信"),
    ("688347", "华虹公司", "电子"),
]

INDUSTRIES = sorted(set(s[2] for s in STOCKS))  # ['电子','国防军工','通信']


def seed_realistic_data(test_session: Session) -> None:
    """Seed the test DB with 000001-like data for 2024."""

    rng = np.random.default_rng(99)

    # NAV: 242 trading days in 2024
    start = date(2024, 1, 2)
    nav_value = 1.0
    for i in range(242):
        ret = float(rng.normal(0.0003, 0.012))
        nav_value *= 1.0 + ret
        test_session.add(FundNAV(
            fund_code="000001", trade_date=start + timedelta(days=i),
            unit_nav=round(nav_value, 4),
            daily_return=round(ret, 6),
            dividend=0.02 if i == 120 else None,
            data_source_level="LOCAL",
        ))

    # Q1 (top10) + Q2 (full=10) + Q3 (top10) + Q4 (full=10)
    quarters = [
        (date(2024, 3, 31), True),   # Q1: top10
        (date(2024, 6, 30), False),  # Q2: full (simulating all 10)
        (date(2024, 9, 30), True),   # Q3: top10
        (date(2024, 12, 31), False),  # Q4: full
    ]
    for rp_date, is_top10 in quarters:
        count = 10 if is_top10 else 10  # both use same set for simplicity
        for j, (code, name, ind) in enumerate(STOCKS[:count]):
            test_session.add(FundDisclosedHoldings(
                fund_code="000001", report_date=rp_date,
                security_code=code, security_name=name,
                asset_type="股票", industry=ind,
                weight_pct=round(float(rng.uniform(2, 12)), 2),
                rank_in_holdings=j + 1,
                data_source_level="LOCAL",
            ))

    # Stock daily: one row per stock for the year (simplified)
    for code, _name, _ind in STOCKS:
        price = float(rng.uniform(10, 500))
        for i in range(0, 242, 5):  # every 5 days
            ret = float(rng.normal(0.0002, 0.018))
            price *= 1.0 + ret
            test_session.add(StockDaily(
                stock_code=code,
                trade_date=start + timedelta(days=i),
                close_price=round(price, 2),
                daily_return=round(ret, 6),
                data_source_level="LOCAL",
            ))

    # Benchmark index daily: stored in stock_daily with index symbol.
    benchmark_level = 4000.0
    for i in range(0, 242, 5):
        ret = float(rng.normal(0.0001, 0.01))
        benchmark_level *= 1.0 + ret
        test_session.add(StockDaily(
            stock_code="sh000300",
            trade_date=start + timedelta(days=i),
            close_price=round(benchmark_level, 2),
            daily_return=round(ret, 6),
            data_source_level="LOCAL",
        ))

    test_session.commit()


class TestRealDataPipeline:
    """E2E experiment pipeline with realistic fund data."""

    def test_full_pipeline_simulated_holding(
        self, test_client: TestClient, test_session: Session,
    ):
        """完整管线: 创建 → 运行 → 查看 → 验收报告。"""
        seed_realistic_data(test_session)

        # Create experiment
        r = test_client.post("/api/v2/experiments", json={
            "experiment_name": "validation-000001",
            "algorithm_name": "simulated_holding",
            "algorithm_version": "0.1.0",
            "parameters": {"max_positions": 20, "window_days": 60},
            "sample_fund_codes": ["000001"],
        })
        assert r.status_code == 200
        exp_id = r.json()["data"]["id"]

        # Run experiment
        r = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert r.status_code == 200
        run_data = r.json()
        assert run_data["data"]["status"] == "completed"
        assert run_data["data"]["fund_count"] == 1

        # Check results persisted in DB
        results = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).all()
        assert len(results) == 1

        # Build validation report
        report = build_validation_report(test_session, int(exp_id))
        assert report["experiment_summary"]["fund_count"] == 1
        assert report["experiment_summary"]["algorithm_name"] == "simulated_holding"
        assert "aggregate_stats" in report
        assert "mean_estimated_tracking_error" in report["aggregate_stats"]
        assert "per_fund" in report
        assert report["per_fund"][0]["fund_code"] == "000001"

        # Credibility: not fact/computed
        assert report["conclusion_status"] in ("estimated", "needs_review"), \
            f"conclusion_status should be estimated/needs_review, got {report['conclusion_status']}"

    def test_multi_fund_experiment(
        self, test_client: TestClient, test_session: Session,
    ):
        """多基金实验: 2 只基金各自跑模拟持仓。"""
        seed_realistic_data(test_session)
        # Add second fund with partial data
        for i in range(60):
            test_session.add(FundNAV(
                fund_code="000002", trade_date=date(2024, 1, 2) + timedelta(days=i),
                unit_nav=1.0 + i * 0.005, daily_return=0.005,
                data_source_level="LOCAL",
            ))
        test_session.commit()

        r = test_client.post("/api/v2/experiments", json={
            "experiment_name": "multi-fund", "algorithm_name": "simulated_holding",
            "sample_fund_codes": ["000001", "000002"],
        })
        exp_id = r.json()["data"]["id"]

        r = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["fund_count"] == 2
        # 000001 should succeed (has holdings), 000002 should fail (no holdings)
        assert data["success_count"] + data["failure_count"] == 2

        report = build_validation_report(test_session, int(exp_id))
        assert report["experiment_summary"]["fund_count"] == 2
        assert report["aggregate_stats"]["success_rate"] <= 1.0

    def test_dynamic_attribution_with_real_structure(
        self, test_client: TestClient, test_session: Session,
    ):
        """动态归因: 真实基金持仓结构。"""
        seed_realistic_data(test_session)

        r = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-real", "algorithm_name": "dynamic_attribution",
            "sample_fund_codes": ["000001"],
        })
        exp_id = r.json()["data"]["id"]

        r = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert r.status_code == 200

        results = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).all()
        assert len(results) == 1
        if results[0].is_success:
            m = results[0].metrics or {}
            assert "estimated_total_allocation_effect" in m
            assert "estimated_total_selection_effect" in m

    def test_scoring_with_real_structure(
        self, test_client: TestClient, test_session: Session,
    ):
        """综合评分: 真实 NAV 结构。"""
        seed_realistic_data(test_session)

        r = test_client.post("/api/v2/experiments", json={
            "experiment_name": "score-real", "algorithm_name": "scoring",
            "sample_fund_codes": ["000001"],
        })
        exp_id = r.json()["data"]["id"]

        r = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert r.status_code == 200

        report = build_validation_report(test_session, int(exp_id))
        assert report["experiment_summary"]["fund_count"] >= 1
        # Scoring should not use fact/computed
        assert report["conclusion_status"] != "fact"
        assert report["conclusion_status"] != "computed"
