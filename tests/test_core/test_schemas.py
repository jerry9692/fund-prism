"""
测试核心 Schema 的正确性。

验证 APIResponse、ResearchPacket、EvidenceRecord 等模型
能够正确序列化和反序列化。
"""

from datetime import date

from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    EvidenceType,
)
from fund_research.core.schemas import (
    APIResponse,
    EvidenceRecord,
    FieldCoverage,
    ResearchPacket,
    ResearchPacketMetadata,
)


def test_api_response_structure() -> None:
    """验证 APIResponse 四段式结构。"""
    response = APIResponse(
        data={"fund_code": "000001"},
        metadata={"algorithm": "nav_metrics_v1"},
        evidence=[],
        warnings=["测试警告"],
        conclusion_status=ConclusionStatus.COMPUTED,
    )

    assert response.data is not None
    assert response.data["fund_code"] == "000001"
    assert response.metadata["algorithm"] == "nav_metrics_v1"
    assert response.warnings == ["测试警告"]
    assert response.conclusion_status == ConclusionStatus.COMPUTED
    assert response.not_applicable_reason is None


def test_api_response_not_applicable() -> None:
    """验证不适用场景。"""
    response = APIResponse(
        data=None,
        metadata={},
        evidence=[],
        warnings=["该基金类型暂不支持此分析"],
        conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        not_applicable_reason="该接口仅适用于主动权益基金，当前基金为债券型",
    )

    assert response.data is None
    assert response.not_applicable_reason is not None
    assert "债券型" in response.not_applicable_reason


def test_evidence_record() -> None:
    """验证证据记录结构。"""
    evidence = EvidenceRecord(
        evidence_id="evt_001",
        entity_id="fund_000001",
        evidence_type=EvidenceType.RAW_DATA,
        source="akshare_fund_nav",
        source_level=DataSourceLevel.B,
        date_range=(date(2024, 1, 1), date(2024, 12, 31)),
        data_summary="净值数据共 242 条交易日记录",
        confidence=ConfidenceLevel.HIGH,
    )

    assert evidence.evidence_id == "evt_001"
    assert evidence.entity_id == "fund_000001"
    assert evidence.evidence_type == EvidenceType.RAW_DATA
    assert evidence.source_level == DataSourceLevel.B
    assert evidence.date_range == (date(2024, 1, 1), date(2024, 12, 31))
    assert evidence.confidence == ConfidenceLevel.HIGH
    assert evidence.conclusion_status == ConclusionStatus.NEEDS_REVIEW


def test_research_packet_metadata() -> None:
    """验证研究包元数据包含所有必需字段。"""
    metadata = ResearchPacketMetadata(
        fund_code="000001",
        data_date=date(2024, 12, 31),
        platform_version="0.1.0",
        data_source_levels=[DataSourceLevel.A, DataSourceLevel.B],
        algorithm_versions={"exposure": "1.0.0", "attribution": "1.0.0"},
        missing_fields=["manager_bio"],
        overall_confidence=ConfidenceLevel.MEDIUM,
    )

    assert metadata.fund_code == "000001"
    assert DataSourceLevel.A in metadata.data_source_levels
    assert "exposure" in metadata.algorithm_versions
    assert "manager_bio" in metadata.missing_fields
    assert metadata.overall_confidence == ConfidenceLevel.MEDIUM


def test_research_packet_structure() -> None:
    """验证研究包完整结构。"""
    packet = ResearchPacket(
        metadata=ResearchPacketMetadata(
            fund_code="000001",
            data_date=date(2024, 12, 31),
            platform_version="0.1.0",
        ),
        fund_profile={"fund_code": "000001", "short_name": "测试基金"},
        nav_metrics={
            "annualized_return_1y": 12.5,
            "max_drawdown_1y": -15.3,
            "sharpe_ratio_1y": 0.85,
        },
        risk_alerts=[
            {"type": "manager_change", "severity": "high", "detail": "基金经理于 2024-06 变更"}
        ],
        evidence=[
            EvidenceRecord(
                evidence_id="evt_002",
                entity_id="fund_000001",
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="static_attribution_v1",
                source_level=DataSourceLevel.B,
                confidence=ConfidenceLevel.MEDIUM,
            )
        ],
        conclusion_map={
            "return_metrics": ConclusionStatus.COMPUTED,
            "attribution": ConclusionStatus.OBSERVATION,
        },
        warnings=["静态归因仅基于报告期披露持仓，不反映季度内调仓"],
    )

    # 序列化测试
    json_str = packet.model_dump_json()
    assert "000001" in json_str
    assert "测试基金" in json_str

    # 反序列化测试
    reloaded = ResearchPacket.model_validate_json(json_str)
    assert reloaded.metadata.fund_code == "000001"
    assert len(reloaded.evidence) == 1
    assert len(reloaded.risk_alerts) == 1


def test_field_coverage() -> None:
    """验证字段覆盖率计算。"""
    coverage = FieldCoverage(
        field_name="daily_return",
        coverage_rate=0.95,
        missing_count=12,
        anomaly_count=3,
        source_level=DataSourceLevel.B,
    )

    assert coverage.coverage_rate == 0.95
    assert coverage.missing_count == 12
    assert coverage.anomaly_count == 3
