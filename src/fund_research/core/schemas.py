"""
核心 Schema 定义。

所有 API 返回、研究包、证据链等数据结构的 Pydantic 模型。
遵循需求书 v0.4 第 5 章定义的 AI 友好数据规范。
"""

from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    EvidenceType,
)

# ============================================================
# 通用类型变量
# ============================================================

T = TypeVar("T")


# ============================================================
# 算法元数据（需求书 5.4 第 4 条）
# ============================================================


class AlgorithmMetadata(BaseModel):
    """每次算法计算的元数据，跟随所有算法结果。"""

    algorithm_name: str = Field(..., description="算法名称")
    algorithm_version: str = Field(..., description="算法版本（语义化版本）")
    parameters: dict[str, Any] = Field(default_factory=dict, description="运行参数")
    input_data_snapshot: str | None = Field(None, description="输入数据快照标识")
    run_timestamp: datetime = Field(default_factory=datetime.now, description="运行时间")
    confidence: ConfidenceLevel | None = Field(None, description="算法整体置信度")
    error_info: str | None = Field(None, description="错误信息（如有）")
    warnings: list[str] = Field(default_factory=list, description="运行警告")


# ============================================================
# 证据记录（需求书 6.3.3）
# ============================================================


class EvidenceRecord(BaseModel):
    """单条证据记录，用于追溯结论来源。"""

    evidence_id: str = Field(..., description="证据唯一 ID")
    entity_id: str = Field(..., description="关联实体 ID（基金/经理/公司等）")
    evidence_type: EvidenceType = Field(..., description="证据类型")
    source: str = Field(..., description="数据来源标识")
    source_level: DataSourceLevel = Field(..., description="数据源等级")
    date_range: tuple[date, date] | None = Field(None, description="数据日期区间 [start, end]")
    algorithm_metadata: AlgorithmMetadata | None = Field(
        None, description="算法元数据（如为算法产出）"
    )
    report_snippet: str | None = Field(None, description="公告/报告原文片段")
    report_location: str | None = Field(None, description="报告定位：标题、页码/章节")
    data_summary: str | None = Field(None, description="数据摘要")
    confidence: ConfidenceLevel = Field(
        ConfidenceLevel.NEEDS_REVIEW, description="该证据自身的可信度"
    )


# ============================================================
# 字段覆盖率
# ============================================================


class FieldCoverage(BaseModel):
    """数据字段覆盖率信息。"""

    field_name: str = Field(..., description="字段名")
    coverage_rate: float = Field(..., ge=0, le=1, description="覆盖率（0-1）")
    missing_count: int = Field(0, description="缺失数量")
    anomaly_count: int = Field(0, description="异常值数量")
    source_level: DataSourceLevel = Field(..., description="数据源等级")


# ============================================================
# 研究包（需求书 6.3.2）
# ============================================================


class ResearchPacketMetadata(BaseModel):
    """研究包元数据。"""

    fund_code: str = Field(..., description="基金代码")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")
    data_date: date = Field(..., description="数据截止日期")
    template: str = Field(default="single_fund_checkup", description="研究包模板")
    platform_version: str = Field(default="0.1.0", description="平台版本")
    data_source_levels: list[DataSourceLevel] = Field(
        default_factory=list, description="使用的数据源等级"
    )
    algorithm_versions: dict[str, str] = Field(default_factory=dict, description="各算法版本")
    missing_fields: list[str] = Field(default_factory=list, description="缺失字段列表")
    conclusion_statuses: dict[str, ConclusionStatus] = Field(
        default_factory=dict, description="各部分结论状态"
    )
    overall_confidence: ConfidenceLevel = Field(
        ConfidenceLevel.NEEDS_REVIEW, description="研究包整体置信度"
    )
    disclaimer: str = Field("算法结果仅用于个人研究，不构成投资建议。", description="免责声明")


class ResearchPacket(BaseModel):
    """
    基金研究包（见需求书 6.3.2）。

    AI 和人类研究者均可读取的结构化研究材料。
    一期包含：基础信息、经理、净值指标、公开持仓、风格暴露、静态归因、残差、风险提示、证据。
    """

    metadata: ResearchPacketMetadata = Field(..., description="研究包元数据")
    fund_profile: dict[str, Any] | None = Field(None, description="基金基本信息")
    manager_info: dict[str, Any] | None = Field(None, description="基金经理信息")
    nav_metrics: dict[str, Any] | None = Field(None, description="净值指标")
    disclosed_holdings: dict[str, Any] | None = Field(None, description="公开披露持仓")
    exposure: dict[str, Any] | None = Field(None, description="风格/行业暴露")
    attribution: dict[str, Any] | None = Field(None, description="静态归因结果")
    residuals: dict[str, Any] | None = Field(None, description="未解释残差")
    risk_alerts: list[dict[str, Any]] = Field(default_factory=list, description="风险提示")
    evidence: list[EvidenceRecord] = Field(default_factory=list, description="证据列表")
    data_quality: dict[str, Any] | None = Field(None, description="数据质量摘要")
    conclusion_map: dict[str, ConclusionStatus] = Field(
        default_factory=dict, description="各模块结论状态"
    )
    warnings: list[str] = Field(default_factory=list, description="全局警告")


# ============================================================
# API 响应结构（需求书 6.3.4 接口要求）
# ============================================================


class APIDataResult(BaseModel, Generic[T]):
    """API 数据返回体。"""

    success: bool = Field(True, description="请求是否成功")
    data: T | None = Field(None, description="业务数据")
    error: str | None = Field(None, description="错误信息")


class APIResponse(BaseModel, Generic[T]):
    """
    Tool API 统一返回结构（需求书 6.3.4 第 2 条）。

    每个 API 返回均包含 data、metadata、evidence、warnings、conclusion_status。
    """

    data: T | None = Field(None, description="业务数据（JSON，不依赖前端）")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="元数据：算法版本、数据日期、参数、运行时间等",
    )
    evidence: list[EvidenceRecord] = Field(default_factory=list, description="关联证据")
    warnings: list[str] = Field(default_factory=list, description="警告信息")
    conclusion_status: ConclusionStatus | None = Field(None, description="结论状态")
    not_applicable_reason: str | None = Field(
        None,
        description="不适用原因（对不适用的基金类型返回明确原因，而非空结果）",
    )
