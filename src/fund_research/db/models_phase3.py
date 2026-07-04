"""
Phase 3 ORM models.

Tables for discovery capabilities and research workbench:
- Fund fingerprint vectors and similarity cache
- Anomaly detection records
- Fund pool alert rules and records
- Reverse lookup results
- Research task templates and run records
- Fund comparison cache
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fund_research.db.models import Base, id_column
from fund_research.utils import utc_now

# ============================================================
# P3.1: 基金画像指纹
# ============================================================


class FundFingerprint(Base):
    """基金画像指纹向量表。"""

    __tablename__ = "fund_fingerprint"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"), index=True)
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    fund_type: Mapped[str | None] = mapped_column(String(50))
    template_name: Mapped[str] = mapped_column(String(50))
    # 指纹向量 — 按维度组存储，每个维度组包含多个标准化特征
    vector: Mapped[dict[str, Any]] = mapped_column(JSON)
    # 各维度的元数据（数据源等级、结论状态、缺失标记）
    vector_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    # 缺失维度列表
    missing_dimensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 包含 estimated 维度
    contains_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str | None] = mapped_column(String(20))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="computed")
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "calc_date",
            "algorithm_name",
            "algorithm_version",
            name="uq_fingerprint_fund_date_algo",
        ),
        Index("ix_fingerprint_fund_date", "fund_code", "calc_date"),
    )


class FingerprintSimilarityCache(Base):
    """相似度计算缓存表。"""

    __tablename__ = "fingerprint_similarity_cache"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"), index=True)
    metric_space: Mapped[str] = mapped_column(String(30), index=True)
    similar_fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"), index=True)
    similarity_score: Mapped[float] = mapped_column(Float)
    contributing_dimensions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "metric_space",
            "similar_fund_code",
            "calc_date",
            name="uq_sim_cache_fund_metric_target_date",
        ),
        Index("ix_sim_cache_fund_metric", "fund_code", "metric_space"),
    )


# ============================================================
# P3.3: 异常发现
# ============================================================


class AnomalyRecord(Base):
    """异常发现记录表。"""

    __tablename__ = "anomaly_record"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"), index=True)
    rule_name: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    description: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_ids: Mapped[list[str] | None] = mapped_column(JSON)
    scope: Mapped[str] = mapped_column(String(30))
    scope_id: Mapped[str | None] = mapped_column(String(50))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="observation")
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


# ============================================================
# P3.4: 基金池提醒
# ============================================================


class PoolAlertRule(Base):
    """基金池提醒规则表。"""

    __tablename__ = "pool_alert_rule"

    id: Mapped[int] = id_column()
    pool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("fund_pool.id"),
        index=True,
    )
    fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"), index=True)
    alert_type: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class PoolAlertRecord(Base):
    """提醒触发记录表。"""

    __tablename__ = "pool_alert_record"

    id: Mapped[int] = id_column()
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("pool_alert_rule.id"),
        index=True,
        nullable=True,
    )
    pool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fund_pool.id"), index=True)
    fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"), index=True)
    alert_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


# ============================================================
# P3.5: 股票反选基金
# ============================================================


class ReverseLookupResult(Base):
    """股票反选基金结果缓存表。"""

    __tablename__ = "reverse_lookup_result"

    id: Mapped[int] = id_column()
    stock_codes_hash: Mapped[str] = mapped_column(String(64), index=True)
    stock_codes: Mapped[list[str]] = mapped_column(JSON)
    fund_scope: Mapped[str] = mapped_column(String(30))
    scope_id: Mapped[str | None] = mapped_column(String(50))
    method: Mapped[str] = mapped_column(String(20))
    time_range: Mapped[str] = mapped_column(String(30))
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    stock_coverage: Mapped[dict[str, Any]] = mapped_column(JSON)
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


# ============================================================
# P3.6: 研究任务模板
# ============================================================


class ResearchTemplate(Base):
    """研究任务模板定义表。"""

    __tablename__ = "research_template"

    id: Mapped[int] = id_column()
    template_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TemplateRunRecord(Base):
    """模板执行记录表。"""

    __tablename__ = "template_run_record"

    id: Mapped[int] = id_column()
    template_id: Mapped[str] = mapped_column(String(64), index=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="running")
    steps_total: Mapped[int] = mapped_column(Integer, default=0)
    steps_completed: Mapped[int] = mapped_column(Integer, default=0)
    steps_failed: Mapped[int] = mapped_column(Integer, default=0)
    step_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    research_packet_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================
# P3.2: 基金对比缓存
# ============================================================


class FundComparisonCache(Base):
    """基金对比结果缓存表。"""

    __tablename__ = "fund_comparison_cache"

    id: Mapped[int] = id_column()
    fund_codes_hash: Mapped[str] = mapped_column(String(64), index=True)
    fund_codes: Mapped[list[str]] = mapped_column(JSON)
    dimensions: Mapped[list[str]] = mapped_column(JSON)
    comparison_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    similarity_matrix: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    overlap_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
