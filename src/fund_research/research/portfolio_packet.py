"""组合 Research Packet 与 Evidence（需求书 §12.4.4，Phase 4 计划 P4C）。

基于 ``analysis/portfolio.py`` 的穿透分析结果组装组合研究包：
- 组合概览（成员 + 权重）、组合层指标、风格/行业穿透、重仓重叠
  （披露口径 vs estimated 模拟口径隔离）、集中度风险；
- 各成分基金 evidence 引用（证据链完整，§12.4.4）；
- 导出带算法版本、数据日期与免责声明（§6.3.10）。

组合包持久化：``research_packet.entity_type='portfolio'``，
``fund_code`` 为空、``pool_id`` 指向基金池。
"""

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.analysis.nav_metrics import (
    ALGORITHM_NAME as NAV_METRICS_NAME,
)
from fund_research.analysis.nav_metrics import (
    ALGORITHM_VERSION as NAV_METRICS_VERSION,
)
from fund_research.analysis.portfolio import (
    ALGORITHM_NAME as PORTFOLIO_NAME,
)
from fund_research.analysis.portfolio import (
    ALGORITHM_VERSION as PORTFOLIO_VERSION,
)
from fund_research.analysis.portfolio import PortfolioAnalysisResult
from fund_research.config.settings import get_settings
from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    EvidenceType,
)
from fund_research.core.schemas import (
    AlgorithmMetadata,
    EvidenceRecord,
    ResearchPacket,
    ResearchPacketMetadata,
)
from fund_research.db.models import (
    EvidenceRecord as DbEvidenceRecord,
)
from fund_research.db.models import (
    ResearchPacketRecord,
)
from fund_research.research.packet import _persist_evidence_records

PORTFOLIO_TEMPLATE = "portfolio_checkup"

# 每只成分基金引用的 evidence 上限（证据链引用，不复制全文）
MEMBER_EVIDENCE_LIMIT = 5


def _confidence_for_status(status: ConclusionStatus) -> ConfidenceLevel:
    mapping = {
        ConclusionStatus.FACT: ConfidenceLevel.HIGH,
        ConclusionStatus.COMPUTED: ConfidenceLevel.MEDIUM,
        ConclusionStatus.ESTIMATED: ConfidenceLevel.MEDIUM,
        ConclusionStatus.OBSERVATION: ConfidenceLevel.LOW,
        ConclusionStatus.NEEDS_REVIEW: ConfidenceLevel.NEEDS_REVIEW,
    }
    return mapping.get(status, ConfidenceLevel.NEEDS_REVIEW)


def _member_evidence_refs(db: Session, fund_codes: list[str]) -> dict[str, list[str]]:
    """各成分基金最近 evidence 引用（§12.4.4 证据链完整）。"""
    refs: dict[str, list[str]] = {}
    for code in fund_codes:
        rows = db.scalars(
            select(DbEvidenceRecord)
            .where(DbEvidenceRecord.entity_id == code)
            .order_by(DbEvidenceRecord.created_at.desc())
            .limit(MEMBER_EVIDENCE_LIMIT)
        ).all()
        refs[code] = [row.evidence_id for row in rows]
    return refs


def build_portfolio_packet(
    db: Session, analysis: PortfolioAnalysisResult
) -> ResearchPacket:
    """由组合穿透分析结果组装组合研究包。"""
    pool_id = analysis.pool_id
    entity_id = f"portfolio:{pool_id}"
    status = ConclusionStatus(analysis.conclusion_status)
    data_date = date.today()
    member_codes = [m["fund_code"] for m in analysis.members]

    portfolio_section: dict[str, Any] = {
        "members": analysis.members,
        "weights_mode": analysis.weights_mode,
        "portfolio_metrics": analysis.portfolio_metrics,
        "correlation_matrix": analysis.correlation_matrix,
        "style_penetration": analysis.style_penetration,
        "industry_penetration": analysis.industry_penetration,
        "holding_overlap": analysis.holding_overlap,
        "concentration": analysis.concentration,
        "window_start": analysis.window_start,
        "window_end": analysis.window_end,
        "member_evidence_refs": _member_evidence_refs(db, member_codes),
    }

    evidence: list[EvidenceRecord] = [
        EvidenceRecord(
            evidence_id=f"portfolio_analysis:{pool_id}:{data_date}",
            entity_id=entity_id,
            evidence_type=EvidenceType.ALGORITHM_RESULT,
            source="user_portfolio",
            source_level=DataSourceLevel.B,
            algorithm_metadata=AlgorithmMetadata(
                algorithm_name=PORTFOLIO_NAME,
                algorithm_version=PORTFOLIO_VERSION,
                parameters={
                    "pool_id": pool_id,
                    "weights_mode": analysis.weights_mode,
                    "member_count": len(member_codes),
                },
                confidence=_confidence_for_status(status),
                warnings=analysis.warnings,
            ),
            data_summary=(
                f"组合 {analysis.pool_name or pool_id}：{len(member_codes)} 只成员，"
                f"窗口 {analysis.window_start} ~ {analysis.window_end}，"
                f"模式 {analysis.weights_mode}"
            ),
            confidence=_confidence_for_status(status),
            conclusion_status=status,
        )
    ]
    # 组合层指标复用 nav_metrics 口径，单独登记算法证据
    if analysis.portfolio_metrics:
        evidence.append(
            EvidenceRecord(
                evidence_id=f"portfolio_nav_metrics:{pool_id}:{data_date}",
                entity_id=entity_id,
                evidence_type=EvidenceType.ALGORITHM_RESULT,
                source="nav_metrics",
                source_level=DataSourceLevel.B,
                algorithm_metadata=AlgorithmMetadata(
                    algorithm_name=NAV_METRICS_NAME,
                    algorithm_version=NAV_METRICS_VERSION,
                    parameters={"scope": "portfolio_weighted_returns"},
                    confidence=_confidence_for_status(status),
                ),
                data_summary=(
                    f"组合收益窗口 {analysis.portfolio_metrics.get('observations')} 日"
                ),
                confidence=_confidence_for_status(status),
                conclusion_status=status,
            )
        )

    conclusion_map = {
        "portfolio_metrics": status,
        "style_penetration": (
            ConclusionStatus.COMPUTED
            if analysis.style_penetration.get("available")
            else ConclusionStatus.NEEDS_REVIEW
        ),
        "industry_penetration": (
            ConclusionStatus.COMPUTED
            if analysis.industry_penetration.get("available")
            else ConclusionStatus.NEEDS_REVIEW
        ),
        # 披露口径重叠 = computed；模拟口径 estimated_* 单独隔离不进默认结论
        "holding_overlap_disclosed": (
            ConclusionStatus.COMPUTED
            if analysis.holding_overlap.get("disclosed", {}).get("available")
            else ConclusionStatus.NEEDS_REVIEW
        ),
        "holding_overlap_estimated": ConclusionStatus.ESTIMATED,
    }

    metadata = ResearchPacketMetadata(
        fund_code=f"pool:{pool_id}",
        entity_type="portfolio",
        pool_id=pool_id,
        pool_name=analysis.pool_name,
        data_date=data_date,
        template=PORTFOLIO_TEMPLATE,
        platform_version=__version__,
        data_source_levels=[DataSourceLevel.B],
        algorithm_versions={
            PORTFOLIO_NAME: PORTFOLIO_VERSION,
            NAV_METRICS_NAME: NAV_METRICS_VERSION,
        },
        conclusion_statuses=conclusion_map,
        overall_confidence=_confidence_for_status(status),
        disclaimer=get_settings().disclaimer,
    )

    return ResearchPacket(
        metadata=metadata,
        portfolio=portfolio_section,
        conclusion_map=conclusion_map,
        evidence=evidence,
        warnings=list(analysis.warnings),
    )


def render_portfolio_packet_markdown(packet: ResearchPacket) -> str:
    """组合研究包 Markdown 摘要（导出带算法版本/数据日期/免责声明，§6.3.10）。"""
    meta = packet.metadata
    portfolio = packet.portfolio or {}
    metrics = portfolio.get("portfolio_metrics") or {}
    lines = [
        f"# {meta.pool_name or meta.fund_code} 组合研究包",
        "",
        f"- 实体类型: {meta.entity_type}（pool_id={meta.pool_id}）",
        f"- 模板: {meta.template}",
        f"- 数据日期: {meta.data_date}",
        f"- 整体置信度: {meta.overall_confidence.value}",
        f"- 算法版本: {meta.algorithm_versions}",
        "",
        "## 成员与权重",
    ]
    for member in portfolio.get("members") or []:
        lines.append(
            f"- {member.get('fund_name') or member.get('fund_code')}"
            f"（{member.get('fund_code')}）: {(member.get('weight') or 0) * 100:.1f}%"
        )
    if metrics:
        lines += [
            "",
            "## 组合指标",
            f"- 年化收益: {metrics.get('annualized_return')}",
            f"- 年化波动: {metrics.get('annualized_volatility')}",
            f"- 最大回撤: {metrics.get('max_drawdown')}",
            f"- 修复天数: {metrics.get('recovery_days')}",
        ]
    if packet.warnings:
        lines += ["", "## Warnings"]
        lines.extend(f"- {warning}" for warning in packet.warnings)
    lines += ["", f"> {meta.disclaimer}"]
    return "\n".join(lines)


def persist_portfolio_packet(
    db: Session, packet: ResearchPacket
) -> ResearchPacketRecord:
    """持久化组合研究包（entity_type=portfolio，fund_code 为空）。"""
    pool_id = packet.metadata.pool_id
    packet_id = f"rp_pool_{pool_id}_{uuid4().hex[:12]}"
    db.execute(
        update(ResearchPacketRecord)
        .where(ResearchPacketRecord.pool_id == pool_id)
        .where(ResearchPacketRecord.template == packet.metadata.template)
        .values(is_latest=False)
    )
    record = ResearchPacketRecord(
        packet_id=packet_id,
        fund_code=None,
        entity_type="portfolio",
        pool_id=pool_id,
        template=packet.metadata.template,
        generated_at=packet.metadata.generated_at or datetime.now(),
        data_date=packet.metadata.data_date,
        packet_json=packet.model_dump(mode="json"),
        markdown_text=render_portfolio_packet_markdown(packet),
        platform_version=packet.metadata.platform_version,
        overall_confidence=packet.metadata.overall_confidence.value,
        is_latest=True,
    )
    db.add(record)
    _persist_evidence_records(db, packet)
    db.commit()
    db.refresh(record)
    return record
