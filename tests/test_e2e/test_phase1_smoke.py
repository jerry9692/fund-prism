"""Phase 1 end-to-end smoke test."""

from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.exposure import DEFAULT_STYLE_FACTORS
from fund_research.core.enums import ConclusionStatus, DataSourceLevel, DataSourceType
from fund_research.data.adapters.base import FetchResult
from fund_research.data.update import (
    upsert_akshare_fund_fees,
    upsert_akshare_fund_holdings,
    upsert_akshare_fund_info,
    upsert_akshare_fund_managers,
    upsert_akshare_fund_nav,
    upsert_akshare_fund_scale,
    upsert_akshare_holder_structure,
    upsert_akshare_index_daily,
    upsert_akshare_stock_daily,
    upsert_eastmoney_fund_manager_history,
)
from fund_research.db.models import ResearchPacketRecord, StaticAttributionResult


class Phase1SmokeAdapter:
    """Fake adapter that exercises the real Phase 1 update workflows."""

    start_date = date(2024, 1, 1)

    def _result(self, entity_type: str, data: list[dict]) -> FetchResult:
        frame = pd.DataFrame(data)
        return FetchResult(
            source_name="akshare",
            source_type=DataSourceType.OPEN_API,
            source_level=DataSourceLevel.B,
            entity_type=entity_type,
            data=frame,
            record_count=len(frame),
            field_count=len(frame.columns),
            coverage_rate=1.0,
        )

    def _returns(self, index: int) -> tuple[float, float, float]:
        large_cap_return = 0.001 * ((index % 5) - 2)
        mid_cap_return = 0.0015 * (((index * 2) % 7) - 3)
        fund_return = 0.6 * large_cap_return + 0.4 * mid_cap_return
        return large_cap_return, mid_cap_return, fund_return

    def fetch_fund_info(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_info",
            [
                {
                    "fund_code": fund_code,
                    "short_name": "端到端测试基金",
                    "full_name": "端到端测试基金全称",
                    "company_name": "测试基金公司",
                    "fund_type_raw": "混合型",
                    "inception_date": "2020-01-01",
                    "benchmark": "沪深300指数收益率",
                }
            ],
        )

    def fetch_fund_managers(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_managers",
            [
                {
                    "manager_id": "em_mgr_smoke",
                    "name": "测试经理",
                    "current_fund_codes": fund_code,
                    "start_date": "2021-01-01",
                    "experience_years": "6年",
                    "education": "硕士",
                }
            ],
        )

    def fetch_fund_manager_history(self, fund_code: str) -> FetchResult:
        """Return manager tenure history (required for FundManagerTenure records)."""
        return self._result(
            "fund_manager_tenure",
            [
                {
                    "name": "测试经理",
                    "manager_id": "em_mgr_smoke",
                    "fund_code": fund_code,
                    "start_date": date(2021, 1, 1),
                    "end_date": None,
                    "is_current": True,
                    "tenure_days": (date.today() - date(2021, 1, 1)).days,
                    "tenure_return": 0.15,
                }
            ],
        )

    def fetch_fund_scale(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_scale",
            [
                {
                    "fund_code": fund_code,
                    "total_nav": "12.50亿元",
                    "total_share": "10.00亿份",
                    "share_change": "0.50亿份",
                }
            ],
        )

    def fetch_fee_detail(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_fee_detail",
            [
                {
                    "mgmt_fee_pct": "1.5%",
                    "custody_fee_pct": "0.25%",
                    "sales_service_fee_pct": "0%",
                    "subscribe_fee_range": "0%-1.5%",
                    "redeem_fee_range": "0%-1.5%",
                    "effective_date": "2024-01-01",
                }
            ],
        )

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        rows = []
        unit_nav = 1.0
        for index in range(40):
            trade_date = self.start_date + timedelta(days=index)
            _, _, fund_return = self._returns(index)
            unit_nav *= 1 + fund_return
            rows.append(
                {
                    "trade_date": str(trade_date),
                    "unit_nav": unit_nav,
                    "accumulated_nav": unit_nav,
                    "daily_return": fund_return,
                }
            )
        return self._result("fund_nav", rows)

    def fetch_fund_holdings(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        return self._result(
            "fund_holdings",
            [
                {
                    "report_date": "2023-12-31",
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "weight_pct": "60.0",
                    "rank_in_holdings": "1",
                    "industry": "食品饮料",
                },
                {
                    "report_date": "2023-12-31",
                    "stock_code": "000858",
                    "stock_name": "五粮液",
                    "weight_pct": "40.0",
                    "rank_in_holdings": "2",
                    "industry": "食品饮料",
                },
            ],
        )

    def fetch_holder_structure(self, fund_code: str) -> FetchResult:
        return self._result(
            "holder_structure",
            [
                {
                    "report_date": "2024-06-30",
                    "institutional_pct": "43.54",
                    "individual_pct": "55.85",
                    "employee_pct": "2.0",
                    "total_holders": "10000",
                    "avg_holding": "3.21",
                }
            ],
        )

    def fetch_stock_daily(
        self,
        stock_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        rows = []
        for index in range(40):
            trade_date = self.start_date + timedelta(days=index)
            large_cap_return, mid_cap_return, _ = self._returns(index)
            stock_return = large_cap_return if stock_code == "600519" else mid_cap_return
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": str(trade_date),
                    "close_price": 100 + index,
                    "daily_return": stock_return,
                }
            )
        return self._result("stock_daily", rows)

    def fetch_index_daily(
        self, symbol: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        rows = []
        for index in range(40):
            trade_date = self.start_date + timedelta(days=index)
            large_cap_return, mid_cap_return, _ = self._returns(index)
            index_return = large_cap_return if symbol == "sh000300" else mid_cap_return
            rows.append(
                {
                    "trade_date": str(trade_date),
                    "close_price": 1000 + index,
                    "daily_return": index_return,
                }
            )
        return self._result("index_daily", rows)


def test_phase1_smoke_update_analyze_and_build_packet(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Phase 1 should run from local ingestion through API analysis and packet generation."""
    adapter = Phase1SmokeAdapter()
    fund_codes = {"000001"}

    upsert_akshare_fund_info(test_session, fund_codes, adapter=adapter)
    upsert_akshare_fund_managers(test_session, fund_codes, adapter=adapter)
    upsert_eastmoney_fund_manager_history(test_session, fund_codes, adapter=adapter)
    upsert_akshare_fund_scale(test_session, fund_codes, adapter=adapter)
    upsert_akshare_fund_fees(test_session, fund_codes, adapter=adapter)
    upsert_akshare_fund_nav(test_session, fund_codes, adapter=adapter)
    upsert_akshare_fund_holdings(test_session, fund_codes, adapter=adapter)
    upsert_akshare_holder_structure(test_session, fund_codes, adapter=adapter)
    upsert_akshare_stock_daily(test_session, {"600519", "000858"}, adapter=adapter)
    upsert_akshare_index_daily(
        test_session,
        {
            DEFAULT_STYLE_FACTORS["large_cap"],
            DEFAULT_STYLE_FACTORS["mid_cap"],
        },
        adapter=adapter,
    )

    profile = test_client.get("/api/v1/funds/000001/profile").json()
    assert profile["conclusion_status"] == ConclusionStatus.FACT.value
    assert profile["data"]["managers"][0]["name"] == "测试经理"
    assert profile["data"]["scale_history"][0]["total_nav"] == 12.5
    assert profile["data"]["fee_info"]["mgmt_fee_pct"] == 1.5

    nav_metrics = test_client.get("/api/v1/funds/000001/nav-metrics").json()
    assert nav_metrics["conclusion_status"] == ConclusionStatus.COMPUTED.value
    assert "periods" in nav_metrics["data"]
    assert "YTD" in nav_metrics["data"]["periods"]

    holdings = test_client.get("/api/v1/funds/000001/holdings").json()
    assert holdings["conclusion_status"] == ConclusionStatus.COMPUTED.value
    assert holdings["data"]["total_weight_pct"] == 100.0

    exposure = test_client.post("/api/v1/analysis/exposure", json={"fund_code": "000001", "window": 30}).json()
    assert exposure["conclusion_status"] == ConclusionStatus.OBSERVATION.value
    assert exposure["data"]["exposure_values"]["large_cap"] == pytest.approx(0.6)
    assert exposure["data"]["exposure_values"]["mid_cap"] == pytest.approx(0.4)
    assert exposure["data"]["static_attribution"]["coverage_rate"] == 1.0
    attribution_record = test_session.scalar(
        select(StaticAttributionResult).where(StaticAttributionResult.fund_code == "000001")
    )
    assert attribution_record is not None

    packet_response = test_client.post("/api/v1/research/packet", json={"fund_code": "000001"}).json()
    packet = packet_response["data"]["packet"]
    packet_record = test_session.scalar(
        select(ResearchPacketRecord).where(
            ResearchPacketRecord.packet_id == packet_response["data"]["packet_id"]
        )
    )
    assert packet_record is not None
    assert packet_response["conclusion_status"] == ConclusionStatus.OBSERVATION.value
    assert packet["metadata"]["missing_fields"] == []
    assert packet["manager_info"]["current_managers"][0]["name"] == "测试经理"
    assert packet["holder_structure"]["institutional_pct"] == 43.54
    assert packet["holder_structure"]["dominant_holder_type"] == "individual"
    assert packet["exposure"]["exposure_values"]["large_cap"] == pytest.approx(0.6)
    assert packet["attribution"]["detail"]["coverage_rate"] == 1.0
    assert packet["data_quality"]["evidence_count"] >= 7
