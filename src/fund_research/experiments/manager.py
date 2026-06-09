"""Experiment CRUD operations for Phase 2."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import AlgorithmExperiment, ExperimentResult


@dataclass
class ExperimentSummary:
    id: int
    experiment_name: str
    algorithm_name: str
    algorithm_version: str
    status: str
    fund_count: int
    success_count: int
    failure_count: int
    created_at: str


def list_experiments(db: Session, algorithm_name: str | None = None) -> list[ExperimentSummary]:
    """List all experiments, optionally filtered by algorithm."""
    stmt = select(AlgorithmExperiment)
    if algorithm_name:
        stmt = stmt.where(AlgorithmExperiment.algorithm_name == algorithm_name)
    stmt = stmt.order_by(AlgorithmExperiment.created_at.desc())
    experiments = db.scalars(stmt).all()

    summaries = []
    for exp in experiments:
        results = db.scalars(
            select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)
        ).all()
        fund_count = len(results)
        success_count = sum(1 for r in results if r.is_success)
        summaries.append(ExperimentSummary(
            id=exp.id,
            experiment_name=exp.experiment_name,
            algorithm_name=exp.algorithm_name,
            algorithm_version=exp.algorithm_version,
            status=exp.status,
            fund_count=fund_count,
            success_count=success_count,
            failure_count=fund_count - success_count,
            created_at=exp.created_at.isoformat() if exp.created_at else "",
        ))
    return summaries


def get_experiment(db: Session, experiment_id: int) -> AlgorithmExperiment | None:
    """Get a single experiment with results."""
    return db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))


def get_experiment_results(db: Session, experiment_id: int) -> list[ExperimentResult]:
    """Get all results for an experiment."""
    return list(db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
    ).all())


def create_experiment(
    db: Session,
    experiment_name: str,
    algorithm_name: str,
    algorithm_version: str,
    parameters: dict,
    sample_fund_codes: list[str] | None = None,
    backtest_start: date | None = None,
    backtest_end: date | None = None,
) -> AlgorithmExperiment:
    """Create a new experiment."""
    exp = AlgorithmExperiment(
        experiment_name=experiment_name,
        algorithm_name=algorithm_name,
        algorithm_version=algorithm_version,
        parameters=parameters,
        sample_fund_codes=sample_fund_codes or [],
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        status="pending",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def update_experiment_status(db: Session, experiment_id: int, status: str, summary: str | None = None) -> None:
    """Update experiment status."""
    exp = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found")
    exp.status = status
    if status == "running":
        exp.started_at = datetime.now()
    elif status in ("completed", "failed"):
        exp.completed_at = datetime.now()
    if summary:
        exp.summary = summary
    db.commit()


def record_result(
    db: Session,
    experiment_id: int,
    fund_code: str,
    calc_date: date,
    is_success: bool,
    metrics: dict | None = None,
    error_message: str | None = None,
    warnings: list[str] | None = None,
) -> ExperimentResult:
    """Record a single experiment result for one fund."""
    result = ExperimentResult(
        experiment_id=experiment_id,
        fund_code=fund_code,
        calc_date=calc_date,
        is_success=is_success,
        metrics=metrics or {},
        error_message=error_message,
        warnings=warnings or [],
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def delete_experiment(db: Session, experiment_id: int) -> None:
    """Delete an experiment and its results."""
    exp = db.get(AlgorithmExperiment, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found")
    results = db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
    ).all()
    for r in results:
        db.delete(r)
    db.delete(exp)
    db.flush()
    db.commit()

    # Verify
    remaining = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if remaining is not None:
        raise RuntimeError(f"Delete failed: experiment {experiment_id} still exists after commit")


def rerun_experiment(db: Session, experiment_id: int) -> AlgorithmExperiment:
    """Mark experiment for re-run (status back to pending)."""
    exp = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found")
    exp.status = "pending"
    exp.started_at = None
    exp.completed_at = None
    exp.summary = None
    for result in db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
    ).all():
        db.delete(result)
    db.commit()
    db.refresh(exp)
    return exp
