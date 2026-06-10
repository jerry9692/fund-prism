"""
Phase 2 ORM models.

These tables extend the Phase 1 metadata instead of living in a separate
registry, so Alembic, application code, and tests all see the same schema.
"""

from datetime import date, datetime
from secrets import randbits
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fund_research.db.models import Base


# Phase 2 PK: randbits(31) — max ~2.1B, within INT32 and JS safe integer range
def _p2_pk():
    return mapped_column(Integer, primary_key=True, autoincrement=False, default=lambda: randbits(31))


class SimulatedHoldingResult(Base):
    """模拟持仓结果表。"""

    __tablename__ = "simulated_holding_result"

    id: Mapped[int] = _p2_pk()
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
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
    confidence: Mapped[str | None] = mapped_column(String(20))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="estimated")
    is_backtest: Mapped[bool] = mapped_column(Boolean, default=False)
    backtest_report_date: Mapped[date | None] = mapped_column(Date)
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    input_coverage: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class DynamicAttributionResult(Base):
    """动态收益拆解结果表。"""

    __tablename__ = "dynamic_attribution_result"

    id: Mapped[int] = _p2_pk()
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
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
    residual: Mapped[float | None] = mapped_column(Float)
    residual_pct: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[str | None] = mapped_column(String(20))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="estimated")
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ScoringResult(Base):
    """综合评分结果表。"""

    __tablename__ = "scoring_result"

    id: Mapped[int] = _p2_pk()
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    calc_date: Mapped[date] = mapped_column(Date)
    score_version: Mapped[str] = mapped_column(String(20))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    weight_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    total_score: Mapped[float | None] = mapped_column(Float)
    sub_scores: Mapped[dict[str, Any]] = mapped_column(JSON)
    percentile_rank: Mapped[float | None] = mapped_column(Float)
    deduction_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    contains_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str | None] = mapped_column(String(20))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="computed")
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ScoringBacktest(Base):
    """评分回测结果表。"""

    __tablename__ = "scoring_backtest"

    id: Mapped[int] = _p2_pk()
    score_version: Mapped[str] = mapped_column(String(20), index=True)
    backtest_date: Mapped[date] = mapped_column(Date)
    group_count: Mapped[int] = mapped_column(Integer)
    group_results: Mapped[dict[str, Any]] = mapped_column(JSON)
    monotonicity_check: Mapped[bool | None] = mapped_column(Boolean)
    ic_mean: Mapped[float | None] = mapped_column(Float)
    ic_ir: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AlgorithmExperiment(Base):
    """算法实验表。"""

    __tablename__ = "algorithm_experiment"

    id: Mapped[int] = _p2_pk()
    experiment_name: Mapped[str] = mapped_column(String(100))
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    sample_fund_codes: Mapped[list[str] | None] = mapped_column(JSON)
    backtest_start: Mapped[date | None] = mapped_column(Date)
    backtest_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ExperimentResult(Base):
    """实验结果表。"""

    __tablename__ = "experiment_result"

    id: Mapped[int] = _p2_pk()
    experiment_id: Mapped[int] = mapped_column(Integer, index=True)
    fund_code: Mapped[str] = mapped_column(String(20))
    calc_date: Mapped[date] = mapped_column(Date)
    is_success: Mapped[bool] = mapped_column(Boolean, default=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ReviewerAnnotation(Base):
    """研究员手动校验记录表。"""

    __tablename__ = "reviewer_annotation"

    id: Mapped[int] = _p2_pk()
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    annotation_type: Mapped[str] = mapped_column(String(30))
    target_module: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


SimulatedHoldingResultV2 = SimulatedHoldingResult
DynamicAttributionResultV2 = DynamicAttributionResult
ScoringResultV2 = ScoringResult
ScoringBacktestV2 = ScoringBacktest
AlgorithmExperimentV2 = AlgorithmExperiment
ExperimentResultV2 = ExperimentResult
ReviewerAnnotationV2 = ReviewerAnnotation
