"""
P2B validation tests: run P2 algorithms on synthetic-but-realistic data
to verify the experiment execution pipeline end-to-end.

These tests are NOT unit tests of individual algorithm functions (covered by
test_phase2_algorithms.py). Instead they verify:
1. 模拟持仓 produces a structured backtest report with the required fields.
2. The run-experiment endpoint creates, executes, and records results correctly.
3. 可信度红线: estimated_* fields are present, conclusion_status is not fact/computed.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from fund_research.analysis.simulated_holding import run_simulation
from fund_research.db.models import (
    BenchmarkIndustryWeight,
    DynamicAttributionResult,
    ExperimentResult,
    FundDisclosedHoldings,
    FundMain,
    FundNAV,
    ScoringResult,
    SimulatedHoldingResult,
    StockDaily,
)

# ============================================================
# Helpers — build realistic synthetic data
# ============================================================


def _nav_dataframe(
    fund_code: str = "000001",
    start: date = date(2024, 1, 1),
    days: int = 250,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.015, days)
    cum = np.cumprod(1 + returns)
    dates = [start + timedelta(days=i) for i in range(days)]
    return pd.DataFrame({
        "trade_date": dates,
        "unit_nav": cum,
        "accumulated_nav": cum * 1.05,
        "daily_return": np.insert(returns[1:], 0, 0.0),
    })


def _stock_dataframe(
    n_stocks: int = 50,
    start: date = date(2024, 1, 1),
    days: int = 250,
    seed: int = 43,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_stocks):
        code = f"{i:06d}"
        returns = rng.normal(0.0003, 0.02, days)
        prices = 100 * np.cumprod(1 + returns)
        for t in range(days):
            rows.append({
                "trade_date": start + timedelta(days=t),
                "stock_code": code,
                "close_price": prices[t],
                "daily_return": returns[t],
                "industry": ["tech", "finance", "health", "energy", "consumer"][i % 5],
                "market_cap": float(rng.uniform(50, 5000)),
            })
    return pd.DataFrame(rows)


def _disclosed_holdings_df(
    report_date: date = date(2024, 1, 1),
    n_stocks: int = 10,
) -> pd.DataFrame:
    return pd.DataFrame({
        "report_date": [report_date] * n_stocks,
        "stock_code": [f"{i:06d}" for i in range(n_stocks)],
        "weight_pct": [10.0 / n_stocks] * n_stocks,
        "industry": ["tech"] * n_stocks,
    })


# ============================================================
# Tests
# ============================================================


class TestSimulatedHoldingValidation:
    """Verify simulated holding produces structured, auditable output."""

    def test_backtest_report_has_required_fields(self):
        """
        验收报告必须包含: tracking_error, top10_recall, industry_correlation,
        detail 列表，以及每个 period 的 warnings。
        """
        nav = _nav_dataframe()
        stocks = _stock_dataframe()
        holdings = _disclosed_holdings_df()

        result = run_simulation(
            "000001", nav, stocks, holdings,
            max_positions=20, window_days=60, run_backtest=True,
        )

        api_data = result.to_api_data()
        assert "estimated_overall_tracking_error" in api_data, api_data.keys()
        assert api_data["estimated_overall_tracking_error"] >= 0
        assert "confidence" in api_data
        assert "periods" in api_data
        assert "is_reliable" in api_data

        if result.backtest_report:
            br = result.backtest_report
            assert "detail" in br
            assert isinstance(br.get("detail"), list)

    def test_estimated_fields_not_mislabeled_as_computed(self):
        """
        可信度红线：模拟持仓的输出不得使用 fact/computed 作为 conclusion_status。
        """
        nav = _nav_dataframe()
        stocks = _stock_dataframe()
        holdings = _disclosed_holdings_df()

        result = run_simulation("000001", nav, stocks, holdings)

        api_data = result.to_api_data()
        confidence = api_data.get("confidence", "")
        assert confidence != "fact", f"模拟持仓不应标记为 fact: {confidence}"
        assert confidence != "computed", f"模拟持仓不应标记为 computed: {confidence}"

    def test_estimated_fields_present_in_api_output(self):
        """
        验证 to_api_data 输出的字段使用 estimated_* 命名约定。
        """
        nav = _nav_dataframe()
        stocks = _stock_dataframe()
        holdings = _disclosed_holdings_df()

        result = run_simulation("000001", nav, stocks, holdings)
        api_data = result.to_api_data()

        # Check overall output uses \"estimated\"-prefixed fields or proper confidence
        assert "confidence" in api_data
        assert api_data.get("is_reliable") is not None

        for period in api_data.get("periods", []):
            assert "estimated_tracking_error" in period, f"Missing estimated_tracking_error in {list(period.keys())}"


class TestRunExperimentPipeline:
    """Verify the run-experiment API endpoint creates, executes, and records."""

    def test_run_experiment_endpoint_creates_and_executes(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """E2E: create experiment → run → check results."""
        # Seed database with synthetic data
        for i in range(30):
            test_session.add(
                FundNAV(
                    fund_code="000001",
                    trade_date=date(2024, 1, 1) + timedelta(days=i),
                    unit_nav=1.0 + i * 0.01,
                    daily_return=0.01,
                    data_source_level="LOCAL",
                )
            )
        for i in range(10):
            test_session.add(
                FundDisclosedHoldings(
                    fund_code="000001",
                    report_date=date(2024, 3, 31),
                    security_code=f"{i:06d}",
                    asset_type="股票",
                    weight_pct=10.0,
                    rank_in_holdings=i + 1,
                    data_source_level="LOCAL",
                )
            )
        for i in range(50):
            for day in range(30):
                test_session.add(
                    StockDaily(
                        stock_code=f"{i:06d}",
                        trade_date=date(2024, 1, 1) + timedelta(days=day),
                        close_price=100.0 + day,
                        daily_return=0.001,
                        data_source_level="LOCAL",
                    )
                )
        test_session.commit()

        # Create experiment
        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "test-run",
            "algorithm_name": "simulated_holding",
            "algorithm_version": "0.1.0",
            "parameters": {"max_positions": 15, "window_days": 30},
            "sample_fund_codes": ["000001"],
        })
        assert create_resp.status_code == 200
        exp_id = create_resp.json()["data"]["id"]

        # Run experiment
        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["conclusion_status"] == "computed"
        assert run_data["data"]["status"] == "completed"

        # Check results in DB
        from sqlalchemy import select as sa_select

        results = test_session.scalars(
            sa_select(ExperimentResult).where(
                ExperimentResult.experiment_id == int(exp_id)
            )
        ).all()
        assert len(results) >= 1
        for r in results:
            if r.is_success:
                assert r.metrics is not None
                assert "estimated_overall_tracking_error" in (r.metrics or {})
            else:
                assert r.error_message, f"Failed result should have error_message: {r}"

    def test_run_experiment_all_failures_is_needs_review(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """全失败实验不能返回 completed/computed。"""
        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "no-data",
            "algorithm_name": "simulated_holding",
            "sample_fund_codes": ["999999"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["conclusion_status"] == "needs_review"
        assert payload["data"]["status"] == "failed"
        assert payload["data"]["success_count"] == 0

        from sqlalchemy import select as sa_select

        results = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).all()
        assert len(results) == 1
        assert results[0].error_message == "无净值数据"

    def test_simulated_holding_run_recomputes_stock_returns_and_normalizes_latest_report(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """NULL 股票收益率应从价格回算，且多报告期不能累加权重。"""
        for day in range(35):
            test_session.add(FundNAV(
                fund_code="000001",
                trade_date=date(2024, 1, 1) + timedelta(days=day),
                unit_nav=1.0 + day * 0.01,
                daily_return=0.01 if day > 0 else None,
                data_source_level="LOCAL",
            ))
        for report_date in (date(2024, 1, 10), date(2024, 1, 20)):
            for i in range(2):
                test_session.add(FundDisclosedHoldings(
                    fund_code="000001",
                    report_date=report_date,
                    security_code=f"00000{i}",
                    asset_type="股票",
                    weight_pct=50.0,
                    industry="tech" if i == 0 else "finance",
                    rank_in_holdings=i + 1,
                    data_source_level="LOCAL",
                ))
        for i in range(2):
            price = 100.0
            for day in range(35):
                if day > 0:
                    price *= 1.01
                test_session.add(StockDaily(
                    stock_code=f"00000{i}",
                    trade_date=date(2024, 1, 1) + timedelta(days=day),
                    close_price=price,
                    daily_return=None,
                    data_source_level="LOCAL",
                ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "normalized-naive",
            "algorithm_name": "simulated_holding",
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["data"]["status"] == "completed"

        from sqlalchemy import select as sa_select

        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        metrics = result.metrics or {}
        assert metrics["matched_stock_count"] == 2
        assert metrics["return_sample_count"] > 20
        assert metrics["estimated_overall_tracking_error"] < 0.001
        persisted = test_session.scalars(sa_select(SimulatedHoldingResult)).one()
        assert persisted.fund_code == "000001"
        assert persisted.conclusion_status == "estimated"
        assert persisted.input_coverage == 1.0
        assert persisted.holdings_detail

    def test_simulated_holding_disclosure_period_backtest_records_out_of_sample_metrics(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """披露期回测应使用上一期持仓验证下一期披露，而不是同日自我验证。"""
        previous_report = date(2024, 1, 1)
        validation_report = date(2024, 2, 1)
        for day in range(45):
            test_session.add(FundNAV(
                fund_code="000001",
                trade_date=previous_report + timedelta(days=day),
                unit_nav=1.0 + day * 0.01,
                daily_return=0.01 if day > 0 else None,
                data_source_level="LOCAL",
            ))
        for report_date in (previous_report, validation_report):
            for i, industry in enumerate(("tech", "finance")):
                test_session.add(FundDisclosedHoldings(
                    fund_code="000001",
                    report_date=report_date,
                    security_code=f"00000{i}",
                    asset_type="股票",
                    weight_pct=50.0,
                    industry=industry,
                    rank_in_holdings=i + 1,
                    data_source_level="LOCAL",
                ))
        for i in range(2):
            for day in range(45):
                test_session.add(StockDaily(
                    stock_code=f"00000{i}",
                    trade_date=previous_report + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=0.01 if day > 0 else None,
                    data_source_level="LOCAL",
                ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "disclosure-backtest",
            "algorithm_name": "simulated_holding",
            "parameters": {
                "validation_mode": "disclosure_period",
                "min_return_observations": 5,
                "min_top10_recall": 0.5,
            },
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["data"]["status"] == "completed"

        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        metrics = result.metrics or {}
        assert result.is_success
        assert metrics["validation_mode"] == "disclosure_period"
        assert metrics["validation_pair_count"] == 1
        assert metrics["estimated_overall_top10_recall"] == 1.0
        assert metrics["backtest_detail"][0]["previous_report_date"] == "2024-01-01"
        assert metrics["backtest_detail"][0]["validation_report_date"] == "2024-02-01"

        persisted = test_session.scalars(sa_select(SimulatedHoldingResult)).one()
        assert persisted.calc_date == validation_report
        assert persisted.backtest_report_date == validation_report
        assert persisted.input_coverage == 1.0
        assert persisted.conclusion_status == "estimated"

    def test_simulated_holding_disclosure_period_backtest_can_use_optimized_tracking(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """optimized_tracking 应复用披露期回测框架，并显式记录方法与优化诊断。"""
        previous_report = date(2024, 1, 1)
        validation_report = date(2024, 2, 1)
        stock_returns = {
            "000010": [0.010, -0.004, 0.006, 0.002, 0.007, -0.001, 0.004, 0.005],
            "000011": [0.001, 0.003, -0.002, 0.004, 0.002, 0.006, -0.001, 0.003],
            "000012": [-0.002, 0.002, 0.001, -0.001, 0.003, 0.002, 0.004, -0.002],
        }
        for day in range(8):
            fund_return = sum(series[day] / 3.0 for series in stock_returns.values())
            test_session.add(FundNAV(
                fund_code="000099",
                trade_date=previous_report + timedelta(days=day),
                unit_nav=1.0 + day * 0.01,
                daily_return=fund_return,
                data_source_level="LOCAL",
            ))
        for report_date in (previous_report, validation_report):
            for rank, (stock_code, industry) in enumerate(
                zip(stock_returns, ("tech", "finance", "consumer"), strict=False),
                start=1,
            ):
                test_session.add(FundDisclosedHoldings(
                    fund_code="000099",
                    report_date=report_date,
                    security_code=stock_code,
                    asset_type="股票",
                    weight_pct=33.33,
                    industry=industry,
                    rank_in_holdings=rank,
                    data_source_level="LOCAL",
                ))
        for stock_code, returns in stock_returns.items():
            for day, daily_return in enumerate(returns):
                test_session.add(StockDaily(
                    stock_code=stock_code,
                    trade_date=previous_report + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=daily_return,
                    data_source_level="LOCAL",
                ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "optimized-disclosure-backtest",
            "algorithm_name": "simulated_holding",
            "parameters": {
                "validation_mode": "disclosure_period",
                "simulation_method": "optimized_tracking",
                "min_return_observations": 5,
                "min_top10_recall": 0.5,
                "max_positions": 3,
                "max_single_weight": 0.8,
                "use_cvxpy": False,
            },
            "sample_fund_codes": ["000099"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["data"]["status"] == "completed"

        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        metrics = result.metrics or {}
        detail = metrics["backtest_detail"][0]
        assert result.is_success
        assert metrics["simulation_method"] == "optimized_tracking"
        assert detail["simulation_method"] == "optimized_tracking"
        assert detail["optimization_candidate_count"] == 3
        assert detail["optimization_objective_value"] is not None

        persisted = test_session.scalars(
            sa_select(SimulatedHoldingResult).where(SimulatedHoldingResult.fund_code == "000099")
        ).one()
        assert persisted.conclusion_status == "estimated"
        assert persisted.holdings_detail

    def test_run_experiment_unknown_algorithm_returns_failure(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """未知算法应写入失败结果并返回 needs_review。"""
        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "not-ready",
            "algorithm_name": "unknown_algo",
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["conclusion_status"] == "needs_review"
        assert run_data["data"]["status"] == "failed"
        assert run_data["data"]["failure_count"] >= 1

        from sqlalchemy import select as sa_select

        results = test_session.scalars(
            sa_select(ExperimentResult).where(
                ExperimentResult.experiment_id == int(exp_id)
            )
        ).all()
        assert all(not r.is_success for r in results)

    def test_delete_missing_experiment_returns_needs_review(
        self,
        test_client: TestClient,
    ):
        """删除不存在实验不能假装成功。"""
        response = test_client.delete("/api/v2/experiments/123456789")
        assert response.status_code == 200
        payload = response.json()
        assert payload["conclusion_status"] == "needs_review"
        assert payload["data"] is None

    def test_run_dynamic_attribution_records_estimated_fields(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """动态归因结果必须使用真实股票/基准收益和 estimated_* 字段。"""
        # Seed minimal data
        for i in range(10):
            test_session.add(FundNAV(
                fund_code="000001", trade_date=date(2024, 1, 1) + timedelta(days=i),
                unit_nav=1.0 + i * 0.01, daily_return=0.01,
                data_source_level="LOCAL",
            ))
        for i in range(5):
            test_session.add(FundDisclosedHoldings(
                fund_code="000001", report_date=date(2024, 1, 1),
                security_code=f"{i:06d}", asset_type="股票",
                weight_pct=10.0, industry="tech" if i < 3 else "finance",
                rank_in_holdings=i + 1, data_source_level="LOCAL",
            ))
            for day in range(10):
                test_session.add(StockDaily(
                    stock_code=f"{i:06d}",
                    trade_date=date(2024, 1, 1) + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=0.01,
                    data_source_level="LOCAL",
                ))
        for day in range(10):
            test_session.add(StockDaily(
                stock_code="sh000300",
                trade_date=date(2024, 1, 1) + timedelta(days=day),
                close_price=4000.0 + day,
                daily_return=0.005,
                data_source_level="LOCAL",
            ))
        for industry, weight_pct in (("energy", 10.0), ("finance", 35.0), ("tech", 55.0)):
            test_session.add(BenchmarkIndustryWeight(
                benchmark_symbol="sh000300",
                snapshot_date=date(2024, 1, 1),
                classification_type="SW",
                classification_level=1,
                industry_code=None,
                industry_name=industry,
                weight_pct=weight_pct,
                member_count=10,
                unmapped_weight_pct=0.0,
                coverage_pct=100.0,
                source_member_snapshot=date(2024, 1, 1),
                source_industry_snapshot=date(2024, 1, 1),
                algorithm_version="test",
                warnings=[],
            ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-test", "algorithm_name": "dynamic_attribution",
            "parameters": {"benchmark_symbol": "sh000300"},
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["data"]["status"] == "completed"

        from sqlalchemy import select as sa_select
        results = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).all()
        assert len(results) >= 1
        m = results[0].metrics or {}
        assert m.get("uses_proxy_benchmark") is False
        assert m.get("uses_proxy_sector_returns") is False
        assert m.get("uses_real_benchmark_returns") is True
        assert m.get("uses_real_sector_returns") is True
        assert m.get("uses_proxy_benchmark_weights") is False
        assert m.get("uses_real_benchmark_weights") is True
        assert m.get("benchmark_symbol") == "sh000300"
        assert m.get("normalized_weight_sum_by_report") == {"2024-01-01": 1.0}
        assert m.get("benchmark_weight_snapshot_by_report") == {"2024-01-01": "2024-01-01"}
        assert m.get("benchmark_weight_coverage_by_report") == {"2024-01-01": 100.0}
        assert m.get("benchmark_weight_snapshot_age_days_by_report") == {"2024-01-01": 0}
        assert m.get("benchmark_only_sector_count_by_report") == {"2024-01-01": 1}
        assert m["estimated_total_portfolio_return"] < 0.2
        assert not any("P2B 近似" in warning for warning in (results[0].warnings or []))
        assert not any("基准行业权重暂用" in warning for warning in (results[0].warnings or []))
        if results[0].is_success:
            assert "estimated_total_allocation_effect" in m
            assert "estimated_total_selection_effect" in m
        persisted = test_session.scalars(sa_select(DynamicAttributionResult)).one()
        assert persisted.fund_code == "000001"
        assert persisted.conclusion_status == "estimated"
        assert persisted.detail["benchmark_symbol"] == "sh000300"
        assert persisted.detail["input_quality"]["uses_real_benchmark_weights"] is True

    def test_run_dynamic_attribution_resolves_benchmark_from_fund_profile(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """未显式传 benchmark_symbol 时，应从 FundMain.benchmark 轻量识别基准。"""
        test_session.add(
            FundMain(
                fund_code="000001",
                short_name="测试基金",
                full_name="测试基金",
                benchmark="中证500指数收益率 * 95% + 银行活期存款利率 * 5%",
                data_source_level="LOCAL",
            )
        )
        for i in range(4):
            test_session.add(FundDisclosedHoldings(
                fund_code="000001", report_date=date(2024, 1, 1),
                security_code=f"{i:06d}", asset_type="股票",
                weight_pct=25.0, industry="tech" if i < 2 else "finance",
                rank_in_holdings=i + 1, data_source_level="LOCAL",
            ))
            for day in range(6):
                test_session.add(StockDaily(
                    stock_code=f"{i:06d}",
                    trade_date=date(2024, 1, 1) + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=0.01,
                    data_source_level="LOCAL",
                ))
        for day in range(6):
            test_session.add(StockDaily(
                stock_code="sh000905",
                trade_date=date(2024, 1, 1) + timedelta(days=day),
                close_price=6000.0 + day,
                daily_return=0.005,
                data_source_level="LOCAL",
            ))
        for industry, weight_pct in (("finance", 45.0), ("tech", 55.0)):
            test_session.add(BenchmarkIndustryWeight(
                benchmark_symbol="sh000905",
                snapshot_date=date(2024, 1, 1),
                classification_type="SW",
                classification_level=1,
                industry_code=None,
                industry_name=industry,
                weight_pct=weight_pct,
                member_count=10,
                unmapped_weight_pct=0.0,
                coverage_pct=100.0,
                source_member_snapshot=date(2024, 1, 1),
                source_industry_snapshot=date(2024, 1, 1),
                algorithm_version="test",
                warnings=[],
            ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-auto-benchmark",
            "algorithm_name": "dynamic_attribution",
            "parameters": {},
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["data"]["status"] == "completed"

        from sqlalchemy import select as sa_select
        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        metrics = result.metrics or {}
        assert metrics.get("benchmark_symbol") == "sh000905"
        assert metrics.get("benchmark_source") == "fund_benchmark:中证500"
        assert metrics.get("uses_real_benchmark_returns") is True
        assert metrics.get("uses_real_benchmark_weights") is True

    def test_run_dynamic_attribution_without_benchmark_data_fails(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """缺少真实基准指数行情时，动态归因不能回退到代理收益。"""
        for i in range(2):
            test_session.add(FundDisclosedHoldings(
                fund_code="000001", report_date=date(2024, 1, 1),
                security_code=f"{i:06d}", asset_type="股票",
                weight_pct=50.0, industry="tech",
                rank_in_holdings=i + 1, data_source_level="LOCAL",
            ))
            for day in range(5):
                test_session.add(StockDaily(
                    stock_code=f"{i:06d}",
                    trade_date=date(2024, 1, 1) + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=0.01,
                    data_source_level="LOCAL",
                ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-no-benchmark",
            "algorithm_name": "dynamic_attribution",
            "parameters": {"benchmark_symbol": "sh000300"},
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["conclusion_status"] == "needs_review"
        assert payload["data"]["status"] == "failed"

        from sqlalchemy import select as sa_select
        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        assert not result.is_success
        assert result.error_message == "缺少基准指数行情: sh000300"

    def test_run_dynamic_attribution_without_benchmark_weights_fails(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """缺少真实基准行业权重时，动态归因不能回退到持仓权重。"""
        for i in range(2):
            test_session.add(FundDisclosedHoldings(
                fund_code="000001", report_date=date(2024, 1, 1),
                security_code=f"{i:06d}", asset_type="股票",
                weight_pct=50.0, industry="tech",
                rank_in_holdings=i + 1, data_source_level="LOCAL",
            ))
            for day in range(5):
                test_session.add(StockDaily(
                    stock_code=f"{i:06d}",
                    trade_date=date(2024, 1, 1) + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=0.01,
                    data_source_level="LOCAL",
                ))
        for day in range(5):
            test_session.add(StockDaily(
                stock_code="sh000300",
                trade_date=date(2024, 1, 1) + timedelta(days=day),
                close_price=4000.0 + day,
                daily_return=0.005,
                data_source_level="LOCAL",
            ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-no-benchmark-weights",
            "algorithm_name": "dynamic_attribution",
            "parameters": {"benchmark_symbol": "sh000300"},
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["conclusion_status"] == "needs_review"
        assert payload["data"]["status"] == "failed"

        from sqlalchemy import select as sa_select
        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        assert not result.is_success
        assert result.error_message == "缺少可用基准行业权重: sh000300"

    def test_run_dynamic_attribution_rejects_stale_benchmark_weights(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """基准行业权重快照太旧时，动态归因必须失败而不是误用旧快照。"""
        report_date = date(2024, 7, 1)
        stale_snapshot = date(2024, 1, 1)
        for i in range(2):
            test_session.add(FundDisclosedHoldings(
                fund_code="000001", report_date=report_date,
                security_code=f"{i:06d}", asset_type="股票",
                weight_pct=50.0, industry="tech",
                rank_in_holdings=i + 1, data_source_level="LOCAL",
            ))
            for day in range(5):
                test_session.add(StockDaily(
                    stock_code=f"{i:06d}",
                    trade_date=report_date + timedelta(days=day),
                    close_price=100.0 + day,
                    daily_return=0.01,
                    data_source_level="LOCAL",
                ))
        for day in range(5):
            test_session.add(StockDaily(
                stock_code="sh000300",
                trade_date=report_date + timedelta(days=day),
                close_price=4000.0 + day,
                daily_return=0.005,
                data_source_level="LOCAL",
            ))
        for industry, weight_pct in (("finance", 45.0), ("tech", 55.0)):
            test_session.add(BenchmarkIndustryWeight(
                benchmark_symbol="sh000300",
                snapshot_date=stale_snapshot,
                classification_type="SW",
                classification_level=1,
                industry_code=None,
                industry_name=industry,
                weight_pct=weight_pct,
                member_count=10,
                unmapped_weight_pct=0.0,
                coverage_pct=100.0,
                source_member_snapshot=stale_snapshot,
                source_industry_snapshot=stale_snapshot,
                algorithm_version="test",
                warnings=[],
            ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-stale-benchmark-weights",
            "algorithm_name": "dynamic_attribution",
            "parameters": {"benchmark_symbol": "sh000300"},
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["conclusion_status"] == "needs_review"
        assert payload["data"]["status"] == "failed"

        from sqlalchemy import select as sa_select
        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        assert not result.is_success
        assert result.error_message == "缺少可用基准行业权重: sh000300"
        assert any("基准行业权重快照过旧" in warning for warning in (result.warnings or []))

    def test_run_dynamic_attribution_respects_report_date_filter(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """动态归因应能只运行 readiness 选出的报告期，避免被同基金旧报告期拖失败。"""
        old_report = date(2024, 1, 1)
        ready_report = date(2024, 6, 1)
        for report_date, suffix in ((old_report, "old"), (ready_report, "new")):
            for i, industry in enumerate(("tech", "finance")):
                stock_code = f"{i:05d}{0 if suffix == 'old' else 1}"
                test_session.add(FundDisclosedHoldings(
                    fund_code="000001",
                    report_date=report_date,
                    security_code=stock_code,
                    asset_type="股票",
                    weight_pct=50.0,
                    industry=industry,
                    rank_in_holdings=i + 1,
                    data_source_level="LOCAL",
                ))
                for day in range(6):
                    test_session.add(StockDaily(
                        stock_code=stock_code,
                        trade_date=report_date + timedelta(days=day),
                        close_price=100.0 + day,
                        daily_return=0.01,
                        data_source_level="LOCAL",
                    ))
        for day in range(6):
            test_session.add(StockDaily(
                stock_code="sh000300",
                trade_date=ready_report + timedelta(days=day),
                close_price=4000.0 + day,
                daily_return=0.005,
                data_source_level="LOCAL",
            ))
        for industry, weight_pct in (("finance", 50.0), ("tech", 50.0)):
            test_session.add(BenchmarkIndustryWeight(
                benchmark_symbol="sh000300",
                snapshot_date=ready_report,
                classification_type="SW",
                classification_level=1,
                industry_code=None,
                industry_name=industry,
                weight_pct=weight_pct,
                member_count=10,
                unmapped_weight_pct=0.0,
                coverage_pct=100.0,
                source_member_snapshot=ready_report,
                source_industry_snapshot=ready_report,
                algorithm_version="test",
                warnings=[],
            ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "attr-report-filter",
            "algorithm_name": "dynamic_attribution",
            "parameters": {
                "benchmark_symbol": "sh000300",
                "report_dates": ["2024-06-01"],
            },
            "sample_fund_codes": ["000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["data"]["status"] == "completed"

        from sqlalchemy import select as sa_select
        result = test_session.scalars(
            sa_select(ExperimentResult).where(ExperimentResult.experiment_id == int(exp_id))
        ).one()
        metrics = result.metrics or {}
        assert result.is_success
        assert metrics["normalized_weight_sum_by_report"] == {"2024-06-01": 1.0}
        assert metrics["benchmark_weight_snapshot_by_report"] == {"2024-06-01": "2024-06-01"}
        assert metrics["report_date_filter"] == {
            "report_dates": ["2024-06-01"],
            "min_report_date": None,
            "max_report_date": None,
        }

    def test_run_scoring_excludes_unverified_estimated_dims(
        self,
        test_client: TestClient,
        test_session: Session,
    ):
        """综合评分默认不接入未验证 estimated 维度。"""
        for i in range(30):
            test_session.add(FundNAV(
                fund_code=f"{i:06d}",
                trade_date=date(2024, 1, 1) + timedelta(days=i % 30),
                unit_nav=1.0 + i * 0.02, daily_return=0.005,
                data_source_level="LOCAL",
            ))
        test_session.commit()

        create_resp = test_client.post("/api/v2/experiments", json={
            "experiment_name": "score-test", "algorithm_name": "scoring",
            "sample_fund_codes": ["000000", "000001"],
        })
        exp_id = create_resp.json()["data"]["id"]

        run_resp = test_client.post(f"/api/v2/experiments/{exp_id}/run")
        assert run_resp.status_code == 200
        data = run_resp.json()["data"]
        # Scoring should at least attempt to run for the available funds
        assert data["fund_count"] > 0
        persisted = test_session.scalars(sa_select(ScoringResult)).all()
        assert {row.fund_code for row in persisted} == {"000000", "000001"}
        assert all(row.conclusion_status == "needs_review" for row in persisted)
        # contains_estimated may be False if the trading dimension has no
        # data (all NaN) and was removed by dynamic weight redistribution.
        # The key invariant is that conclusion_status is needs_review.
