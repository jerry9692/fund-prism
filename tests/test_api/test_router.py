"""Tool API route tests."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.core.enums import ConclusionStatus, DataSourceLevel, DataSourceType
from fund_research.db.models import (
    DataSourceSnapshot,
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    ResearchPacketRecord,
    StaticAttributionResult,
    StockDaily,
    StyleExposureResult,
    ToolAPICallLog,
)


def test_get_fund_profile_returns_local_fund(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Fund profile endpoint should read from the local database."""
    company = FundCompany(company_id="local_company", name="测试基金公司")
    test_session.add(company)
    test_session.flush()
    test_session.add(
        FundMain(
            fund_code="000001",
            short_name="测试基金",
            full_name="测试基金全称",
            fund_company_id=company.id,
            category="混合型",
            sub_category="主动权益",
            data_source="unit_test",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.add_all(
        [
            FundManager(manager_id="m001", name="张三", experience_years=8.0, education="硕士"),
            FundManagerTenure(
                manager_id="m001",
                fund_code="000001",
                start_date=date(2020, 1, 1),
                is_current=True,
                tenure_days=1000,
                tenure_return=0.25,
            ),
            FundScale(
                fund_code="000001",
                report_date=date(2024, 6, 30),
                total_nav=12.5,
                total_share=10.0,
                share_change=0.5,
            ),
            FundFee(
                fund_code="000001",
                mgmt_fee_pct=1.5,
                custody_fee_pct=0.25,
                sales_service_fee_pct=0.0,
                subscribe_fee_range="0%-1.5%",
                redeem_fee_range="0%-1.5%",
                effective_date=date(2024, 1, 1),
                data_source_level=DataSourceLevel.LOCAL.value,
            ),
        ]
    )
    test_session.commit()

    response = test_client.get("/api/v1/funds/000001/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["fund_code"] == "000001"
    assert payload["data"]["company"] == "测试基金公司"
    assert payload["data"]["managers"][0]["name"] == "张三"
    assert payload["data"]["scale_history"][0]["total_nav"] == 12.5
    assert payload["data"]["fee_info"]["mgmt_fee_pct"] == 1.5
    assert payload["conclusion_status"] == ConclusionStatus.FACT.value
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["source"] == "fund_main"
    assert payload["evidence"][0]["conclusion_status"] == ConclusionStatus.FACT.value
    call_log = test_session.scalar(
        select(ToolAPICallLog).where(ToolAPICallLog.tool_name == "get_fund_profile")
    )
    assert call_log is not None
    assert call_log.parameters == {"fund_code": "000001"}
    assert call_log.status == ConclusionStatus.FACT.value
    assert call_log.response_time_ms is not None


def test_get_fund_profile_returns_needs_review_for_missing_fund(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Missing funds should return a structured needs-review response."""
    response = test_client.get("/api/v1/funds/999999/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] is None
    assert payload["conclusion_status"] == ConclusionStatus.NEEDS_REVIEW.value
    assert payload["warnings"] == ["基金不存在或尚未更新到本地数据库"]
    call_log = test_session.scalar(
        select(ToolAPICallLog).where(ToolAPICallLog.tool_name == "get_fund_profile")
    )
    assert call_log is not None
    assert call_log.status == ConclusionStatus.NEEDS_REVIEW.value
    assert call_log.error_message == "基金不存在或尚未更新到本地数据库"


def test_get_nav_metrics_returns_computed_metrics(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """NAV metrics endpoint should compute metrics from local NAV records."""
    start_date = date(2024, 1, 1)
    for i in range(30):
        test_session.add(
            FundNAV(
                fund_code="000001",
                trade_date=start_date + timedelta(days=i),
                unit_nav=1 + i * 0.01,
                daily_return=0.01,
                dividend=0.05 if i == 10 else None,
                data_source="unit_test",
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
    test_session.add(
        DataSourceSnapshot(
            source_name="akshare",
            source_type=DataSourceType.OPEN_API.value,
            source_level=DataSourceLevel.B.value,
            fetch_timestamp=datetime(2024, 2, 1, 10, 0, 0),
            entity_type="fund_nav",
            field_count=5,
            record_count=30,
            coverage_rate=0.98,
            missing_fields={"daily_return": 1},
            anomaly_count=0,
            is_success=True,
        )
    )
    test_session.commit()

    response = test_client.get("/api/v1/funds/000001/nav-metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conclusion_status"] == ConclusionStatus.COMPUTED.value
    assert payload["data"]["observations"] == 30
    assert payload["data"]["metrics"]["total_return"] > 0
    assert payload["metadata"]["dividend_count"] == 1
    nav_snapshot = payload["metadata"]["data_snapshots"]["fund_nav"]
    assert nav_snapshot["record_count"] == 30
    assert nav_snapshot["coverage_rate"] == 0.98
    assert nav_snapshot["missing_fields"] == {"daily_return": 1}
    assert payload["metadata"]["implemented"] is True
    assert len(payload["evidence"]) == 1
    assert "分红记录 1 条" in payload["evidence"][0]["data_summary"]
    assert payload["evidence"][0]["conclusion_status"] == ConclusionStatus.COMPUTED.value
    call_log = test_session.scalar(
        select(ToolAPICallLog).where(ToolAPICallLog.tool_name == "get_nav_metrics")
    )
    assert call_log is not None
    assert call_log.parameters["fund_code"] == "000001"
    assert call_log.status == ConclusionStatus.COMPUTED.value


def test_get_nav_metrics_returns_needs_review_without_nav(
    test_client: TestClient,
) -> None:
    """Missing NAV records should return a structured needs-review response."""
    response = test_client.get("/api/v1/funds/999999/nav-metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] is None
    assert payload["conclusion_status"] == ConclusionStatus.NEEDS_REVIEW.value
    assert payload["warnings"] == ["基金净值数据不存在或尚未更新到本地数据库"]


def test_get_disclosed_holdings_returns_latest_quarterly_holdings(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Holdings endpoint should return latest report period and limitation warnings."""
    for rank, code, weight in [(1, "600519", 8.5), (2, "000858", 5.0)]:
        test_session.add(
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=date(2024, 3, 31),
                asset_type="股票",
                security_code=code,
                security_name=f"股票{rank}",
                weight_pct=weight,
                rank_in_holdings=rank,
                industry="食品饮料",
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
    test_session.commit()

    response = test_client.get("/api/v1/funds/000001/holdings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conclusion_status"] == ConclusionStatus.OBSERVATION.value
    assert payload["data"]["report_date"] == "2024-03-31"
    assert payload["data"]["disclosure_granularity"] == "top10_quarterly"
    assert payload["data"]["total_weight_pct"] == 13.5
    assert payload["warnings"] == ["季报通常仅披露前十大重仓，不能视为完整组合"]
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["conclusion_status"] == ConclusionStatus.OBSERVATION.value


def test_get_disclosed_holdings_can_filter_report_date(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Holdings endpoint should support a specific report date."""
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=date(2024, 6, 30),
            asset_type="股票",
            security_code="600519",
            security_name="贵州茅台",
            weight_pct=8.5,
            rank_in_holdings=1,
            industry="食品饮料",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.commit()

    response = test_client.get("/api/v1/funds/000001/holdings?report_date=2024-06-30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conclusion_status"] == ConclusionStatus.COMPUTED.value
    assert payload["data"]["disclosure_granularity"] == "full_semiannual_or_annual"
    assert payload["warnings"] == []


def test_get_disclosed_holdings_can_filter_asset_type(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Holdings endpoint should filter both current and previous reports by asset type."""
    rows = [
        (date(2023, 12, 31), "股票", "600519", "贵州茅台", 6.0, 1),
        (date(2023, 12, 31), "债券", "019694", "22国债01", 12.0, 2),
        (date(2024, 6, 30), "股票", "600519", "贵州茅台", 8.5, 1),
        (date(2024, 6, 30), "债券", "019694", "22国债01", 10.0, 2),
    ]
    for report_date, asset_type, code, name, weight, rank in rows:
        test_session.add(
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=report_date,
                asset_type=asset_type,
                security_code=code,
                security_name=name,
                weight_pct=weight,
                rank_in_holdings=rank,
                industry="固定收益" if asset_type == "债券" else "食品饮料",
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
    test_session.commit()

    response = test_client.get("/api/v1/funds/000001/holdings?asset_type=债券")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["asset_type"] == "债券"
    assert payload["data"]["total_weight_pct"] == 10.0
    assert [item["asset_type"] for item in payload["data"]["holdings"]] == ["债券"]
    assert payload["data"]["previous_report_date"] == "2023-12-31"
    assert payload["data"]["change_summary"]["decreased"] == 1
    assert payload["evidence"][0]["algorithm_metadata"]["parameters"]["asset_type"] == "债券"


def test_get_disclosed_holdings_includes_period_changes(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Holdings endpoint should compare the selected report with the previous report."""
    rows = [
        (date(2023, 12, 31), "600519", "贵州茅台", 6.0, 1, "食品饮料"),
        (date(2023, 12, 31), "300750", "宁德时代", 4.0, 2, "电力设备"),
        (date(2024, 6, 30), "600519", "贵州茅台", 8.5, 1, "食品饮料"),
        (date(2024, 6, 30), "000001", "平安银行", 2.0, 2, "银行"),
    ]
    for report_date, code, name, weight, rank, industry in rows:
        test_session.add(
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=report_date,
                asset_type="股票",
                security_code=code,
                security_name=name,
                weight_pct=weight,
                rank_in_holdings=rank,
                industry=industry,
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
    test_session.commit()

    response = test_client.get("/api/v1/funds/000001/holdings?report_date=2024-06-30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["previous_report_date"] == "2023-12-31"
    assert payload["data"]["change_summary"] == {
        "new": 1,
        "increased": 1,
        "decreased": 0,
        "unchanged": 0,
        "exited": 1,
    }
    changes = {item["security_code"]: item for item in payload["data"]["holding_changes"]}
    assert changes["000001"]["direction_zh"] == "新增"
    assert changes["600519"]["delta_weight_pct"] == 2.5
    assert changes["300750"]["direction"] == "exited"


def test_get_disclosed_holdings_returns_needs_review_without_holdings(
    test_client: TestClient,
) -> None:
    """Missing holdings should return a structured needs-review response."""
    response = test_client.get("/api/v1/funds/999999/holdings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] is None
    assert payload["conclusion_status"] == ConclusionStatus.NEEDS_REVIEW.value
    assert payload["warnings"] == ["基金公开披露持仓不存在或尚未更新到本地数据库"]


def test_build_research_packet_returns_packet_and_persists_record(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Research packet endpoint should aggregate available modules and persist a record."""
    company = FundCompany(company_id="local_company", name="测试基金公司")
    test_session.add(company)
    test_session.flush()
    test_session.add(
        FundMain(
            fund_code="000001",
            short_name="测试基金",
            full_name="测试基金全称",
            fund_company_id=company.id,
            data_source="unit_test",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    start_date = date(2024, 1, 1)
    for i in range(30):
        test_session.add(
            FundNAV(
                fund_code="000001",
                trade_date=start_date + timedelta(days=i),
                unit_nav=1 + i * 0.01,
                daily_return=0.01,
                data_source="unit_test",
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=date(2024, 3, 31),
            asset_type="股票",
            security_code="600519",
            security_name="贵州茅台",
            weight_pct=8.5,
            rank_in_holdings=1,
            industry="食品饮料",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.add(
        DataSourceSnapshot(
            source_name="sample",
            source_type=DataSourceType.LOCAL_FILE.value,
            source_level=DataSourceLevel.LOCAL.value,
            fetch_timestamp=datetime(2024, 2, 1, 10, 0, 0),
            entity_type="fund_main",
            record_count=1,
            field_count=8,
            coverage_rate=1.0,
            missing_fields={},
            anomaly_count=0,
            is_success=True,
        )
    )
    test_session.commit()

    response = test_client.post("/api/v1/research/packet?fund_code=000001")

    assert response.status_code == 200
    payload = response.json()
    record = test_session.scalar(
        select(ResearchPacketRecord).where(
            ResearchPacketRecord.packet_id == payload["data"]["packet_id"]
        )
    )
    assert payload["metadata"]["implemented"] is True
    assert payload["metadata"]["data_snapshots"]["fund_main"]["record_count"] == 1
    assert payload["data"]["packet"]["fund_profile"]["fund_code"] == "000001"
    assert payload["data"]["packet"]["nav_metrics"] is not None
    assert record is not None


def test_run_exposure_analysis_returns_observation_and_persists_result(
    test_client: TestClient,
    test_session: Session,
) -> None:
    """Exposure endpoint should regress local fund returns on style index returns."""
    start_date = date(2024, 1, 1)
    for i in range(40):
        trade_date = start_date + timedelta(days=i)
        large_cap_return = 0.001 * ((i % 5) - 2)
        mid_cap_return = 0.0015 * (((i * 2) % 7) - 3)
        fund_return = 0.6 * large_cap_return + 0.4 * mid_cap_return
        test_session.add(
            FundNAV(
                fund_code="000001",
                trade_date=trade_date,
                daily_return=fund_return,
                unit_nav=1.0 + i * 0.001,
                data_source="unit_test",
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
        test_session.add_all(
            [
                StockDaily(
                    stock_code="sh000300",
                    trade_date=trade_date,
                    close_price=1000 + i,
                    daily_return=large_cap_return,
                    data_source_level=DataSourceLevel.LOCAL.value,
                ),
                StockDaily(
                    stock_code="sh000905",
                    trade_date=trade_date,
                    close_price=900 + i,
                    daily_return=mid_cap_return,
                    data_source_level=DataSourceLevel.LOCAL.value,
                ),
                StockDaily(
                    stock_code="600519",
                    trade_date=trade_date,
                    close_price=100 + i,
                    daily_return=large_cap_return,
                    data_source_level=DataSourceLevel.LOCAL.value,
                ),
                StockDaily(
                    stock_code="000858",
                    trade_date=trade_date,
                    close_price=80 + i,
                    daily_return=mid_cap_return,
                    data_source_level=DataSourceLevel.LOCAL.value,
                ),
            ]
        )
    test_session.add_all(
        [
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=date(2023, 12, 31),
                asset_type="股票",
                security_code="600519",
                security_name="贵州茅台",
                weight_pct=60.0,
                rank_in_holdings=1,
                industry="食品饮料",
                data_source_level=DataSourceLevel.LOCAL.value,
            ),
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=date(2023, 12, 31),
                asset_type="股票",
                security_code="000858",
                security_name="五粮液",
                weight_pct=40.0,
                rank_in_holdings=2,
                industry="食品饮料",
                data_source_level=DataSourceLevel.LOCAL.value,
            ),
        ]
    )
    test_session.add(
        DataSourceSnapshot(
            source_name="akshare",
            source_type=DataSourceType.OPEN_API.value,
            source_level=DataSourceLevel.B.value,
            fetch_timestamp=datetime(2024, 2, 1, 10, 0, 0),
            entity_type="index_daily",
            record_count=80,
            field_count=5,
            coverage_rate=1.0,
            missing_fields={},
            anomaly_count=0,
            is_success=True,
        )
    )
    test_session.commit()

    response = test_client.post("/api/v1/analysis/exposure?fund_code=000001&window=30")

    assert response.status_code == 200
    payload = response.json()
    exposure_record = test_session.scalar(
        select(StyleExposureResult).where(StyleExposureResult.fund_code == "000001")
    )
    attribution_record = test_session.scalar(
        select(StaticAttributionResult).where(StaticAttributionResult.fund_code == "000001")
    )
    assert payload["conclusion_status"] == ConclusionStatus.OBSERVATION.value
    assert payload["data"]["observations"] == 30
    assert payload["data"]["exposure_values"]["large_cap"] == pytest.approx(0.6)
    assert payload["data"]["exposure_values"]["mid_cap"] == pytest.approx(0.4)
    assert payload["data"]["static_attribution"]["coverage_rate"] == 1.0
    assert payload["metadata"]["data_snapshots"]["index_daily"]["record_count"] == 80
    assert exposure_record is not None
    assert attribution_record is not None
    assert len(payload["evidence"]) == 2
    assert payload["evidence"][0]["conclusion_status"] == ConclusionStatus.OBSERVATION.value
    assert payload["evidence"][1]["conclusion_status"] == ConclusionStatus.OBSERVATION.value
    call_log = test_session.scalar(
        select(ToolAPICallLog).where(ToolAPICallLog.tool_name == "run_exposure_analysis")
    )
    assert call_log is not None
    assert call_log.parameters == {"fund_code": "000001", "window": 30}
    assert call_log.status == ConclusionStatus.OBSERVATION.value


def test_run_exposure_analysis_returns_needs_review_without_inputs(
    test_client: TestClient,
) -> None:
    """Missing exposure inputs should return a structured needs-review response."""
    response = test_client.post("/api/v1/analysis/exposure?fund_code=999999&window=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conclusion_status"] == ConclusionStatus.NEEDS_REVIEW.value
    assert payload["data"]["exposure_values"] == {}
