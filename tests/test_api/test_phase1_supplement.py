"""Phase 1 supplement API coverage."""

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel
from fund_research.db.models import (
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    ResearchPacketRecord,
)


def _seed_screen_fund(test_session: Session) -> None:
    company = FundCompany(company_id="c001", name="测试基金公司")
    test_session.add(company)
    test_session.flush()
    test_session.add(
        FundMain(
            fund_code="000001",
            short_name="测试基金",
            full_name="测试基金全称",
            fund_company_id=company.id,
            category="混合型",
            inception_date=date(2020, 1, 1),
            data_source="unit_test",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.add_all(
        [
            FundManager(manager_id="m001", name="测试经理"),
            FundManagerTenure(
                manager_id="m001",
                fund_code="000001",
                start_date=date(2021, 1, 1),
                is_current=True,
                tenure_days=1000,
            ),
            FundScale(fund_code="000001", report_date=date(2024, 6, 30), total_nav=12.5),
            FundFee(
                fund_code="000001",
                mgmt_fee_pct=1.5,
                custody_fee_pct=0.25,
                sales_service_fee_pct=0.0,
                effective_date=date(2024, 1, 1),
                data_source_level=DataSourceLevel.LOCAL.value,
            ),
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=date(2024, 6, 30),
                asset_type="股票",
                security_code="600519",
                security_name="贵州茅台",
                weight_pct=8.0,
            ),
        ]
    )
    start = date(2024, 1, 1)
    for i in range(30):
        test_session.add(
            FundNAV(
                fund_code="000001",
                trade_date=start + timedelta(days=i),
                unit_nav=1 + i * 0.01,
                daily_return=0.01,
                data_source="unit_test",
                data_source_level=DataSourceLevel.LOCAL.value,
            )
        )
    test_session.commit()


def test_screen_funds_returns_company_metrics_and_completeness(
    test_client: TestClient,
    test_session: Session,
) -> None:
    _seed_screen_fund(test_session)

    response = test_client.post(
        "/api/v1/funds/screen",
        json={
            "filters": {"category": "混合型", "min_data_completeness": 0.9},
            "sort_by": "data_completeness",
            "sort_order": "desc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    fund = payload["data"]["funds"][0]
    assert fund["company"] == "测试基金公司"
    assert fund["manager"] == "测试经理"
    assert fund["data_completeness"] == 1.0
    assert fund["metrics"]["annualized_return_1y"] is not None
    assert payload["evidence"][0]["source"] == "fund_main/fund_scale/fund_manager_tenure/fund_fee/fund_nav"


def test_nav_metrics_long_periods_downgrade_when_calendar_coverage_is_short(
    test_client: TestClient,
    test_session: Session,
) -> None:
    _seed_screen_fund(test_session)

    response = test_client.get("/api/v1/funds/000001/nav-metrics")

    assert response.status_code == 200
    period = response.json()["data"]["periods"]["3Y"]
    assert period["status"] == "needs_review"
    assert "低于目标区间" in "; ".join(period["warnings"])


def test_diff_research_packets_includes_evidence_and_status_changes(
    test_client: TestClient,
    test_session: Session,
) -> None:
    left_json = {
        "fund_profile": {"latest_scale": 10.0},
        "exposure": {"exposure_values": {"large_cap": 0.4}},
        "evidence": [{"evidence_id": "ev:left"}],
        "conclusion_map": {"exposure": "observation"},
    }
    right_json = {
        "fund_profile": {"latest_scale": 12.0},
        "exposure": {"exposure_values": {"large_cap": 0.7}},
        "evidence": [{"evidence_id": "ev:right"}],
        "conclusion_map": {"exposure": "needs_review"},
    }
    test_session.add_all(
        [
            ResearchPacketRecord(
                packet_id="pkt_left",
                fund_code="000001",
                template="single_fund_checkup",
                generated_at=datetime(2024, 3, 31),
                data_date=date(2024, 3, 31),
                packet_json=left_json,
                markdown_text=None,
                platform_version="0.1.0",
                overall_confidence="low",
                is_latest=False,
            ),
            ResearchPacketRecord(
                packet_id="pkt_right",
                fund_code="000001",
                template="single_fund_checkup",
                generated_at=datetime(2024, 6, 30),
                data_date=date(2024, 6, 30),
                packet_json=right_json,
                markdown_text=None,
                platform_version="0.1.0",
                overall_confidence="needs_review",
                is_latest=True,
            ),
        ]
    )
    test_session.commit()

    response = test_client.post(
        "/api/v1/research/diff",
        json={"left_packet_id": "pkt_left", "right_packet_id": "pkt_right"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["evidence"]) == 2
    assert payload["data"]["fund_code"] == "000001"
    assert payload["data"]["diffs"]["exposure"]["large_cap"]["delta"] == 0.3
    assert payload["data"]["diffs"]["evidence"]["new"] == ["ev:right"]
    assert payload["data"]["diffs"]["conclusion_status"]["exposure"]["right"] == "needs_review"
