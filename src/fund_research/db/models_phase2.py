"""
Phase 2 ORM models.

These tables extend the Phase 1 metadata instead of living in a separate
registry, so Alembic, application code, and tests all see the same schema.
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
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    ExperimentStatus,
)
from fund_research.db.models import Base, enum_values, id_column


class SimulatedHoldingResult(Base):
    """模拟持仓结果表。"""

    __tablename__ = "simulated_holding_result"

    id: Mapped[int] = id_column()
    experiment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("algorithm_experiment.id"),
        index=True,
        nullable=True,
    )
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True
    )
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    holdings_detail: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    tracking_error: Mapped[float | None] = mapped_column(Float)
    daily_rmse: Mapped[float | None] = mapped_column(Float)
    industry_correlation: Mapped[float | None] = mapped_column(Float)
    top10_recall: Mapped[float | None] = mapped_column(Float)
    stock_weight_pct: Mapped[float | None] = mapped_column(Float)
    bond_weight_pct: Mapped[float | None] = mapped_column(Float)
    cash_weight_pct: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values)
    )
    conclusion_status: Mapped[ConclusionStatus] = mapped_column(
        SAEnum(ConclusionStatus, native_enum=False, values_callable=enum_values),
        default=ConclusionStatus.ESTIMATED,
        server_default=text("'estimated'"),
    )
    is_backtest: Mapped[bool] = mapped_column(Boolean, default=False)
    backtest_report_date: Mapped[date | None] = mapped_column(Date)
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    input_coverage: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "calc_date",
            "algorithm_name",
            "algorithm_version",
            name="uq_sim_holding_fund_date_algo",
        ),
        Index(
            "ix_sim_holding_fund_date_algo",
            "fund_code",
            "calc_date",
            "algorithm_name",
        ),
    )


class DynamicAttributionResult(Base):
    """动态收益拆解结果表。"""

    __tablename__ = "dynamic_attribution_result"

    id: Mapped[int] = id_column()
    experiment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("algorithm_experiment.id"),
        index=True,
        nullable=True,
    )
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True
    )
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    total_return: Mapped[float | None] = mapped_column(Float)
    beta_return: Mapped[float | None] = mapped_column(Float)
    allocation_return: Mapped[float | None] = mapped_column(Float)
    sector_rotation_return: Mapped[float | None] = mapped_column(Float)
    stock_selection_return: Mapped[float | None] = mapped_column(Float)
    convertible_bond_return: Mapped[float | None] = mapped_column(Float)
    ipo_return: Mapped[float | None] = mapped_column(Float)
    interaction_return: Mapped[float | None] = mapped_column(Float)
    residual: Mapped[float | None] = mapped_column(Float)
    residual_pct: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values)
    )
    conclusion_status: Mapped[ConclusionStatus] = mapped_column(
        SAEnum(ConclusionStatus, native_enum=False, values_callable=enum_values),
        default=ConclusionStatus.ESTIMATED,
        server_default=text("'estimated'"),
    )
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "period_start",
            "period_end",
            "algorithm_name",
            "algorithm_version",
            name="uq_dyn_attr_fund_period_algo",
        ),
        Index(
            "ix_dyn_attr_fund_period",
            "fund_code",
            "period_start",
            "period_end",
        ),
    )


class ScoringResult(Base):
    """综合评分结果表。"""

    __tablename__ = "scoring_result"

    id: Mapped[int] = id_column()
    experiment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("algorithm_experiment.id"),
        index=True,
        nullable=True,
    )
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True
    )
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    score_version: Mapped[str] = mapped_column(String(20))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    weight_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    total_score: Mapped[float | None] = mapped_column(Float)
    sub_scores: Mapped[dict[str, Any]] = mapped_column(JSON)
    percentile_rank: Mapped[float | None] = mapped_column(Float)
    deduction_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    contains_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values)
    )
    conclusion_status: Mapped[ConclusionStatus] = mapped_column(
        SAEnum(ConclusionStatus, native_enum=False, values_callable=enum_values),
        default=ConclusionStatus.COMPUTED,
        server_default=text("'computed'"),
    )
    is_backtest: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "calc_date",
            "score_version",
            "algorithm_version",
            "is_backtest",
            name="uq_scoring_fund_date_version",
        ),
        Index(
            "ix_scoring_fund_date_version",
            "fund_code",
            "calc_date",
            "score_version",
        ),
    )


class ScoringBacktest(Base):
    """评分回测结果表。"""

    __tablename__ = "scoring_backtest"

    id: Mapped[int] = id_column()
    score_version: Mapped[str] = mapped_column(String(20), index=True)
    backtest_date: Mapped[date] = mapped_column(Date)
    group_count: Mapped[int] = mapped_column(Integer)
    group_results: Mapped[dict[str, Any]] = mapped_column(JSON)
    monotonicity_check: Mapped[bool | None] = mapped_column(Boolean)
    ic_mean: Mapped[float | None] = mapped_column(Float)
    ic_ir: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "score_version",
            "backtest_date",
            name="uq_scoring_bt_version_date",
        ),
        Index(
            "ix_scoring_bt_version_date",
            "score_version",
            "backtest_date",
        ),
    )


class AlgorithmExperiment(Base):
    """算法实验表。"""

    __tablename__ = "algorithm_experiment"

    id: Mapped[int] = id_column()
    experiment_name: Mapped[str] = mapped_column(String(100))
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    sample_fund_codes: Mapped[list[str] | None] = mapped_column(JSON)
    backtest_start: Mapped[date | None] = mapped_column(Date)
    backtest_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ExperimentStatus] = mapped_column(
        SAEnum(ExperimentStatus, native_enum=False, values_callable=enum_values),
        default=ExperimentStatus.PENDING,
        server_default=text("'pending'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExperimentResult(Base):
    """实验结果表。"""

    __tablename__ = "experiment_result"

    id: Mapped[int] = id_column()
    experiment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("algorithm_experiment.id"),
        index=True,
    )
    fund_code: Mapped[str] = mapped_column(String(20), ForeignKey("fund_main.fund_code"))
    calc_date: Mapped[date] = mapped_column(Date)
    is_success: Mapped[bool] = mapped_column(Boolean, default=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "fund_code",
            "calc_date",
            name="uq_exp_result_exp_fund_date",
        ),
        Index(
            "ix_exp_result_exp_fund_date",
            "experiment_id",
            "fund_code",
            "calc_date",
        ),
    )


class ReviewerAnnotation(Base):
    """研究员手动校验记录表。"""

    __tablename__ = "reviewer_annotation"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True
    )
    annotation_type: Mapped[str] = mapped_column(String(30))
    target_module: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BenchmarkIndexMember(Base):
    """指数成分与权重快照。"""

    __tablename__ = "benchmark_index_member"

    id: Mapped[int] = id_column()
    benchmark_symbol: Mapped[str] = mapped_column(String(20), index=True)
    index_code: Mapped[str] = mapped_column(String(20))
    index_name: Mapped[str | None] = mapped_column(String(100))
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("stock_main.stock_code"), index=True
    )
    stock_name: Mapped[str | None] = mapped_column(String(100))
    exchange: Mapped[str | None] = mapped_column(String(20))
    weight_pct: Mapped[float | None] = mapped_column(Float)
    source_name: Mapped[str] = mapped_column(String(80))
    source_level: Mapped[DataSourceLevel] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values)
    )
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "benchmark_symbol",
            "snapshot_date",
            "stock_code",
            name="uq_benchmark_member_symbol_date_stock",
        ),
        Index("ix_benchmark_member_symbol_date", "benchmark_symbol", "snapshot_date"),
        Index("ix_benchmark_member_stock_date", "stock_code", "snapshot_date"),
    )


class StockIndustryMembership(Base):
    """股票行业归属快照。"""

    __tablename__ = "stock_industry_membership"

    id: Mapped[int] = id_column()
    stock_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("stock_main.stock_code"), index=True
    )
    stock_name: Mapped[str | None] = mapped_column(String(100))
    classification_type: Mapped[str] = mapped_column(String(30), index=True)
    classification_version: Mapped[str | None] = mapped_column(String(20))
    level: Mapped[int] = mapped_column(Integer)
    industry_code: Mapped[str | None] = mapped_column(String(20))
    industry_name: Mapped[str] = mapped_column(String(50), index=True)
    parent_industry_code: Mapped[str | None] = mapped_column(String(20))
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    source_name: Mapped[str] = mapped_column(String(80))
    source_level: Mapped[DataSourceLevel] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "stock_code",
            "classification_type",
            "level",
            "effective_date",
            name="uq_stock_industry_stock_type_level_date",
        ),
        Index(
            "ix_stock_industry_stock_type_date",
            "stock_code",
            "classification_type",
            "effective_date",
        ),
        Index(
            "ix_stock_industry_type_level_name",
            "classification_type",
            "level",
            "industry_name",
        ),
    )


class BenchmarkIndustryWeight(Base):
    """由指数成分权重和股票行业归属聚合得到的基准行业权重。"""

    __tablename__ = "benchmark_industry_weight"

    id: Mapped[int] = id_column()
    benchmark_symbol: Mapped[str] = mapped_column(String(20), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    classification_type: Mapped[str] = mapped_column(String(30))
    classification_level: Mapped[int] = mapped_column(Integer)
    industry_code: Mapped[str | None] = mapped_column(String(20))
    industry_name: Mapped[str] = mapped_column(String(50))
    weight_pct: Mapped[float] = mapped_column(Float)
    member_count: Mapped[int] = mapped_column(Integer)
    unmapped_weight_pct: Mapped[float | None] = mapped_column(Float)
    coverage_pct: Mapped[float | None] = mapped_column(Float)
    source_member_snapshot: Mapped[date | None] = mapped_column(Date)
    source_industry_snapshot: Mapped[date | None] = mapped_column(Date)
    algorithm_version: Mapped[str] = mapped_column(String(20))
    warnings: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "benchmark_symbol",
            "snapshot_date",
            "classification_type",
            "classification_level",
            "industry_name",
            name="uq_benchmark_industry_symbol_date_type_level_name",
        ),
        Index("ix_benchmark_industry_symbol_date", "benchmark_symbol", "snapshot_date"),
    )


SimulatedHoldingResultV2 = SimulatedHoldingResult
DynamicAttributionResultV2 = DynamicAttributionResult
ScoringResultV2 = ScoringResult
ScoringBacktestV2 = ScoringBacktest
AlgorithmExperimentV2 = AlgorithmExperiment
ExperimentResultV2 = ExperimentResult
ReviewerAnnotationV2 = ReviewerAnnotation
BenchmarkIndexMemberV2 = BenchmarkIndexMember
StockIndustryMembershipV2 = StockIndustryMembership
BenchmarkIndustryWeightV2 = BenchmarkIndustryWeight
