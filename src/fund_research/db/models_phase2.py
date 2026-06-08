"""
Phase 2 ORM models — 模拟持仓 / 动态归因 / 综合评分 / 实验管理 / 校验。

与 Phase 1 models.py 隔离，避免新表影响 Phase 1 测试的表计数。
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fund_research.db.models import id_column


class SimulatedHoldingResultV2:
    """模拟持仓结果表。"""

    __tablename__ = "simulated_holding_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[str | None] = mapped_column(Text)  # JSON string
    holdings_detail: Mapped[str] = mapped_column(Text)  # JSON string
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
    warnings: Mapped[str | None] = mapped_column(Text)  # JSON string
    input_coverage: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class DynamicAttributionResultV2:
    """动态收益拆解结果表。"""

    __tablename__ = "dynamic_attribution_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[str | None] = mapped_column(Text)
    total_return: Mapped[float | None] = mapped_column(Float)
    beta_return: Mapped[float | None] = mapped_column(Float)
    allocation_return: Mapped[float | None] = mapped_column(Float)
    sector_rotation_return: Mapped[float | None] = mapped_column(Float)
    stock_selection_return: Mapped[float | None] = mapped_column(Float)
    convertible_bond_return: Mapped[float | None] = mapped_column(Float)
    ipo_return: Mapped[float | None] = mapped_column(Float)
    residual: Mapped[float | None] = mapped_column(Float)
    residual_pct: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(20))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="estimated")
    warnings: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ScoringResultV2:
    """综合评分结果表。"""

    __tablename__ = "scoring_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    calc_date: Mapped[date] = mapped_column(Date)
    score_version: Mapped[str] = mapped_column(String(20))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    weight_config: Mapped[str] = mapped_column(Text)  # JSON string
    total_score: Mapped[float | None] = mapped_column(Float)
    sub_scores: Mapped[str] = mapped_column(Text)  # JSON string
    percentile_rank: Mapped[float | None] = mapped_column(Float)
    deduction_reasons: Mapped[str | None] = mapped_column(Text)
    contains_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str | None] = mapped_column(String(20))
    conclusion_status: Mapped[str] = mapped_column(String(20), default="computed")
    warnings: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ScoringBacktestV2:
    """评分回测结果表。"""

    __tablename__ = "scoring_backtest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score_version: Mapped[str] = mapped_column(String(20), index=True)
    backtest_date: Mapped[date] = mapped_column(Date)
    group_count: Mapped[int] = mapped_column(Integer)
    group_results: Mapped[str] = mapped_column(Text)  # JSON string
    monotonicity_check: Mapped[bool | None] = mapped_column(Boolean)
    ic_mean: Mapped[float | None] = mapped_column(Float)
    ic_ir: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AlgorithmExperimentV2:
    """算法实验表。"""

    __tablename__ = "algorithm_experiment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_name: Mapped[str] = mapped_column(String(100))
    algorithm_name: Mapped[str] = mapped_column(String(50))
    algorithm_version: Mapped[str] = mapped_column(String(10))
    parameters: Mapped[str] = mapped_column(Text)  # JSON string
    sample_fund_codes: Mapped[str | None] = mapped_column(Text)  # JSON string
    backtest_start: Mapped[date | None] = mapped_column(Date)
    backtest_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ExperimentResultV2:
    """实验结果表。"""

    __tablename__ = "experiment_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("algorithm_experiment.id"), index=True)
    fund_code: Mapped[str] = mapped_column(String(20))
    calc_date: Mapped[date] = mapped_column(Date)
    is_success: Mapped[bool] = mapped_column(Boolean, default=True)
    metrics: Mapped[str | None] = mapped_column(Text)  # JSON string
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[str | None] = mapped_column(Text)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ReviewerAnnotationV2:
    """研究员手动校验记录表。"""

    __tablename__ = "reviewer_annotation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), index=True)
    annotation_type: Mapped[str] = mapped_column(String(30))
    target_module: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text)  # JSON string
    reason: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
