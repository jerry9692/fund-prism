"""Research Packet generation tests."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.core.enums import ConclusionStatus, DataSourceLevel
from fund_research.db.models import (
    EvidenceRecord as DBEvidenceRecord,
)
from fund_research.db.models import (
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    HolderStructure,
    ResearchPacketRecord,
    StaticAttributionResult,
    StyleExposureResult,
)
from fund_research.research.packet import build_single_fund_packet, persist_research_packet


def _seed_packet_inputs(session: Session) -> None:
    company = FundCompany(company_id="local_company", name="测试基金公司")
    session.add(company)
    session.flush()
    session.add(
        FundMain(
            fund_code="000001",
            short_name="测试基金",
            full_name="测试基金全称",
            fund_company_id=company.id,
            data_source="unit_test",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    session.add_all(
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
            HolderStructure(
                fund_code="000001",
                report_date=date(2024, 6, 30),
                individual_pct=55.85,
                institutional_pct=43.54,
                employee_pct=2.0,
                total_holders=10000,
                avg_holding=3.21,
                data_source_level=DataSourceLevel.LOCAL.value,
            ),
        ]
    )
    start_date = date(2024, 1, 1)
    for i in range(30):
        session.add(
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
    session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=date(2023, 12, 31),
            asset_type="股票",
            security_code="600519",
            security_name="贵州茅台",
            weight_pct=6.0,
            rank_in_holdings=1,
            industry="食品饮料",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    session.add(
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
    session.commit()


def test_build_single_fund_packet_aggregates_available_modules(test_session: Session) -> None:
    """Research Packet should aggregate local profile, NAV metrics, and holdings."""
    _seed_packet_inputs(test_session)

    packet = build_single_fund_packet(test_session, "000001")

    assert packet.fund_profile is not None
    assert packet.fund_profile["managers"][0]["name"] == "张三"
    assert packet.fund_profile["scale_history"][0]["total_nav"] == 12.5
    assert packet.fund_profile["fee_info"]["mgmt_fee_pct"] == 1.5
    assert packet.manager_info is not None
    assert packet.manager_info["current_managers"][0]["name"] == "张三"
    assert packet.manager_info["current_tenure_days_min"] == 1000
    assert packet.nav_metrics is not None
    assert packet.nav_metrics["dividend_count"] == 1
    assert packet.disclosed_holdings is not None
    assert packet.disclosed_holdings["previous_report_date"] == "2023-12-31"
    assert packet.disclosed_holdings["change_summary"]["increased"] == 1
    assert packet.holder_structure is not None
    assert packet.holder_structure["dominant_holder_type"] == "individual"
    assert packet.holder_structure["total_holders"] == 10000
    assert packet.conclusion_map["fund_profile"] == ConclusionStatus.FACT
    assert packet.conclusion_map["manager_info"] == ConclusionStatus.FACT
    assert packet.conclusion_map["nav_metrics"] == ConclusionStatus.COMPUTED
    assert packet.conclusion_map["disclosed_holdings"] == ConclusionStatus.OBSERVATION
    assert packet.conclusion_map["holder_structure"] == ConclusionStatus.FACT
    assert packet.metadata.missing_fields == ["exposure", "attribution"]
    assert len(packet.evidence) == 5
    assert {item.evidence_type.value for item in packet.evidence} == {
        "algorithm_result",
        "raw_data",
    }
    assert any(item.source == "fund_manager_tenure" for item in packet.evidence)
    assert any(item.source == "holder_structure" for item in packet.evidence)
    assert any("分红记录 1 条" in item.data_summary for item in packet.evidence)
    assert packet.risk_alerts[0]["type"] == "limited_disclosure"
    assert packet.data_quality["holder_structure_status"] == ConclusionStatus.FACT.value
    assert packet.data_quality["manager_info_status"] == ConclusionStatus.FACT.value
    assert packet.data_quality["evidence_count"] == 5


def test_persist_research_packet_marks_previous_record_not_latest(test_session: Session) -> None:
    """Persisting a new packet should leave only one latest packet per fund/template."""
    _seed_packet_inputs(test_session)

    first = persist_research_packet(test_session, build_single_fund_packet(test_session, "000001"))
    second = persist_research_packet(test_session, build_single_fund_packet(test_session, "000001"))
    latest_count = test_session.scalar(
        select(func.count())
        .select_from(ResearchPacketRecord)
        .where(ResearchPacketRecord.is_latest.is_(True))
    )
    evidence_count = test_session.scalar(select(func.count()).select_from(DBEvidenceRecord))
    manager_evidence = test_session.scalar(
        select(DBEvidenceRecord).where(DBEvidenceRecord.evidence_id == "manager_info:000001")
    )
    holder_evidence = test_session.scalar(
        select(DBEvidenceRecord).where(
            DBEvidenceRecord.evidence_id == "holder_structure:000001:2024-06-30"
        )
    )

    assert first.packet_id != second.packet_id
    assert latest_count == 1
    assert evidence_count == 5
    assert manager_evidence is not None
    assert manager_evidence.conclusion_status == ConclusionStatus.FACT.value
    assert holder_evidence is not None
    assert holder_evidence.conclusion_status == ConclusionStatus.FACT.value
    assert holder_evidence.source_level == DataSourceLevel.LOCAL.value


def test_build_single_fund_packet_includes_latest_exposure(test_session: Session) -> None:
    """Research Packet should include the latest persisted exposure result."""
    _seed_packet_inputs(test_session)
    test_session.add(
        StyleExposureResult(
            fund_code="000001",
            calc_date=date(2024, 1, 30),
            algorithm_name="style_exposure",
            algorithm_version="0.1.0",
            parameters={"window": 30},
            exposure_type="style",
            exposure_values={"large_cap": 0.6, "mid_cap": 0.4},
            residual=0.0,
            r_squared=1.0,
            confidence="low",
            conclusion_status=ConclusionStatus.OBSERVATION.value,
            warnings={"items": []},
            input_coverage=1.0,
        )
    )
    test_session.commit()

    packet = build_single_fund_packet(test_session, "000001")

    assert packet.exposure is not None
    assert packet.exposure["exposure_values"] == {"large_cap": 0.6, "mid_cap": 0.4}
    assert packet.residuals == {
        "style_exposure_residual": 0.0,
        "style_exposure_r_squared": 1.0,
    }
    assert packet.conclusion_map["exposure"] == ConclusionStatus.OBSERVATION
    assert packet.metadata.missing_fields == ["attribution"]
    assert any(item.source == "style_exposure_result" for item in packet.evidence)


def test_build_single_fund_packet_includes_latest_attribution(test_session: Session) -> None:
    """Research Packet should include the latest persisted attribution result."""
    _seed_packet_inputs(test_session)
    test_session.add(
        StaticAttributionResult(
            fund_code="000001",
            report_date=date(2024, 3, 31),
            benchmark=None,
            algorithm_name="static_attribution",
            algorithm_version="0.1.0",
            parameters={"method": "disclosed_weight_times_security_return"},
            total_return=0.04,
            benchmark_return=None,
            allocation_effect=None,
            selection_effect=0.03,
            interaction_effect=None,
            sector_rotation_effect=None,
            residual=0.01,
            residual_pct=0.25,
            detail={"coverage_rate": 1.0},
            confidence="low",
            conclusion_status=ConclusionStatus.OBSERVATION.value,
            warnings={"items": []},
        )
    )
    test_session.commit()

    packet = build_single_fund_packet(test_session, "000001")

    assert packet.attribution is not None
    assert packet.attribution["selection_effect"] == 0.03
    assert packet.residuals == {
        "static_attribution_residual": 0.01,
        "static_attribution_residual_pct": 0.25,
    }
    assert packet.conclusion_map["attribution"] == ConclusionStatus.OBSERVATION
    assert packet.metadata.missing_fields == ["exposure"]
    assert any(item.source == "static_attribution_result" for item in packet.evidence)


def test_build_single_fund_packet_flags_concentrated_holder_base(
    test_session: Session,
) -> None:
    """Research Packet should flag concentrated holder structure observations."""
    _seed_packet_inputs(test_session)
    holder = test_session.scalar(
        select(HolderStructure).where(HolderStructure.fund_code == "000001")
    )
    assert holder is not None
    holder.institutional_pct = 82.0
    holder.individual_pct = 17.0
    holder.total_holders = 800
    test_session.commit()

    packet = build_single_fund_packet(test_session, "000001")

    assert packet.holder_structure is not None
    assert packet.holder_structure["dominant_holder_type"] == "institutional"
    assert {alert["type"] for alert in packet.risk_alerts} >= {
        "institutional_holder_dominance",
        "low_holder_count",
    }


def test_build_single_fund_packet_flags_short_manager_tenure(
    test_session: Session,
) -> None:
    """Research Packet should flag current managers with short tenure."""
    _seed_packet_inputs(test_session)
    tenure = test_session.scalar(
        select(FundManagerTenure).where(FundManagerTenure.manager_id == "m001")
    )
    assert tenure is not None
    tenure.tenure_days = 90
    test_session.commit()

    packet = build_single_fund_packet(test_session, "000001")

    assert packet.manager_info is not None
    assert packet.manager_info["current_tenure_days_min"] == 90
    assert any(alert["type"] == "manager_short_tenure" for alert in packet.risk_alerts)
