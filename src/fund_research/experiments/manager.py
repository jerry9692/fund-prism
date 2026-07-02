"""Experiment CRUD operations for Phase 2."""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    AlgorithmExperiment,
    DynamicAttributionResult,
    ExperimentResult,
    ScoringResult,
    SimulatedHoldingResult,
)

logger = logging.getLogger(__name__)

VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running"},
    "running": {"completed", "completed_with_failures", "failed", "cancelled"},
    "completed": set(),
    "completed_with_failures": set(),
    "failed": set(),
    "cancelled": set(),
}


def _validate_transition(current_status: str, new_status: str) -> None:
    allowed = VALID_STATUS_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Invalid status transition: {current_status} → {new_status}. "
            f"Allowed transitions from {current_status}: {sorted(allowed)}"
        )


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
    current_status = exp.status
    if current_status == status:
        if summary:
            exp.summary = summary
        db.commit()
        return
    _validate_transition(current_status, status)
    exp.status = status
    if status == "running":
        exp.started_at = datetime.now()
        exp.completed_at = None
    elif status in ("completed", "completed_with_failures", "failed", "cancelled"):
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
    """Record a single experiment result for one fund (upsert)."""
    existing = db.scalar(
        select(ExperimentResult).where(
            ExperimentResult.experiment_id == experiment_id,
            ExperimentResult.fund_code == fund_code,
            ExperimentResult.calc_date == calc_date,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.flush()

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
    """Delete an experiment and all its associated results."""
    exp = db.get(AlgorithmExperiment, experiment_id)
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found")

    sim_count = 0
    for r in db.scalars(
        select(SimulatedHoldingResult).where(SimulatedHoldingResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
        sim_count += 1
    db.flush()

    attr_count = 0
    for r in db.scalars(
        select(DynamicAttributionResult).where(DynamicAttributionResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
        attr_count += 1
    db.flush()

    score_count = 0
    for r in db.scalars(
        select(ScoringResult).where(ScoringResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
        score_count += 1
    db.flush()

    exp_result_count = 0
    for r in db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
        exp_result_count += 1
    db.flush()

    orphan_sim = db.scalars(
        select(SimulatedHoldingResult).where(SimulatedHoldingResult.experiment_id.is_(None))
    ).all()
    orphan_attr = db.scalars(
        select(DynamicAttributionResult).where(DynamicAttributionResult.experiment_id.is_(None))
    ).all()
    orphan_score = db.scalars(
        select(ScoringResult).where(ScoringResult.experiment_id.is_(None))
    ).all()
    if orphan_sim or orphan_attr or orphan_score:
        logger.warning(
            "Experiment %s deleted. There may be orphan Phase 2 results without experiment_id: "
            "simulated_holding=%d, dynamic_attribution=%d, scoring=%d. "
            "These may be from older experiments and should be cleaned up manually.",
            experiment_id, len(orphan_sim), len(orphan_attr), len(orphan_score),
        )

    db.delete(exp)
    db.flush()
    db.commit()

    logger.info(
        "Deleted experiment %s: removed %d simulated_holding, %d dynamic_attribution, "
        "%d scoring results, and %d experiment_results",
        experiment_id, sim_count, attr_count, score_count, exp_result_count,
    )

    remaining = db.get(AlgorithmExperiment, experiment_id)
    if remaining is not None:
        raise RuntimeError(f"Delete failed: experiment {experiment_id} still exists after commit")


def rerun_experiment(db: Session, experiment_id: int) -> AlgorithmExperiment:
    """Mark experiment for re-run (status back to pending)."""
    exp = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found")
    if exp.status == "running":
        raise ValueError(f"Cannot rerun experiment {experiment_id}: currently running")
    exp.status = "pending"
    exp.started_at = None
    exp.completed_at = None
    exp.summary = None
    for r in db.scalars(
        select(SimulatedHoldingResult).where(SimulatedHoldingResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
    for r in db.scalars(
        select(DynamicAttributionResult).where(DynamicAttributionResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
    for r in db.scalars(
        select(ScoringResult).where(ScoringResult.experiment_id == experiment_id)
    ).all():
        db.delete(r)
    for result in db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
    ).all():
        db.delete(result)
    db.commit()
    db.refresh(exp)
    return exp


def build_validation_report(db: Session, experiment_id: int) -> dict:
    """
    从实验结果生成标准化的验收报告结构。

    报告含: experiment_summary, aggregate_stats (均值 TE/recall/IC),
    per_fund 明细, overall_conclusion (pass/partial/fail),
    conclusion_status (v0.4 分级).

    所有指标使用 estimated_* 命名，conclusion_status 不使用 fact/computed.
    """
    import numpy as np

    exp = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if exp is None:
        return {"error": f"Experiment {experiment_id} not found"}

    results = list(db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == experiment_id)
    ).all())

    if not results:
        return {
            "experiment_summary": {
                "experiment_id": experiment_id,
                "experiment_name": exp.experiment_name,
                "algorithm_name": exp.algorithm_name,
                "algorithm_version": exp.algorithm_version,
                "status": exp.status,
                "fund_count": 0,
            },
            "aggregate_stats": {},
            "per_fund": [],
            "overall_conclusion": "no_data",
            "warnings": ["无实验结果"],
            "conclusion_status": "needs_review",
        }

    tes, recalls, ics = [], [], []
    per_fund, all_warns = [], []
    ok = 0

    for r in results:
        m = r.metrics or {}
        te = m.get("estimated_overall_tracking_error")
        rec = m.get("estimated_overall_top10_recall")
        ic = m.get("estimated_overall_industry_correlation")
        w = r.warnings if isinstance(r.warnings, list) else []

        if te is not None:
            tes.append(float(te))
        if rec is not None:
            recalls.append(float(rec))
        if ic is not None:
            ics.append(float(ic))
        if r.is_success:
            ok += 1
        all_warns.extend(w)

        per_fund.append({
            "fund_code": r.fund_code,
            "is_success": r.is_success,
            "estimated_tracking_error": round(float(te), 6) if te is not None else None,
            "estimated_top10_recall": round(float(rec), 4) if rec is not None else None,
            "estimated_industry_correlation": round(float(ic), 4) if ic is not None else None,
            "diagnostics": _diagnostics_for_algorithm(exp.algorithm_name, m),
            "metrics": _compact_metrics(m),
            "error_message": r.error_message,
            "warnings": w,
        })

    n = len(results)
    mean_te = round(float(np.mean(tes)), 6) if tes else None
    mean_recall = round(float(np.mean(recalls)), 4) if recalls else None
    mean_ic = round(float(np.mean(ics)), 4) if ics else None
    success_rate = round(ok / n, 4) if n > 0 else 0.0
    scoring_backtest = _scoring_backtest_summary(results) if exp.algorithm_name == "scoring" else {}

    if success_rate >= 0.8 and mean_te is not None and mean_te < 0.05:
        overall, cs = "pass", "estimated"
    elif success_rate >= 0.5:
        overall, cs = "partial", "estimated"
    else:
        overall, cs = "fail", "needs_review"

    if success_rate < 1.0:
        all_warns.append(f"成功率: {success_rate:.1%} ({ok}/{n})")

    return {
        "experiment_summary": {
            "experiment_id": experiment_id,
            "experiment_name": exp.experiment_name,
            "algorithm_name": exp.algorithm_name,
            "algorithm_version": exp.algorithm_version,
            "status": exp.status,
            "fund_count": n,
            "success_count": ok,
            "failure_count": n - ok,
        },
        "aggregate_stats": {
            "mean_estimated_tracking_error": mean_te,
            "mean_estimated_top10_recall": mean_recall,
            "mean_estimated_industry_correlation": mean_ic,
            "success_rate": success_rate,
            **scoring_backtest,
        },
        "per_fund": per_fund,
        "overall_conclusion": overall,
        "warnings": all_warns,
        "conclusion_status": cs,
    }


def _compact_metrics(metrics: dict) -> dict:
    """Keep report metrics useful without embedding large period-level payloads."""
    compact = {}
    for key, value in metrics.items():
        if key == "backtest_detail" and isinstance(value, list):
            compact["backtest_detail_count"] = len(value)
            compact["backtest_detail_sample"] = value[:2]
        else:
            compact[key] = value
    return compact


def _scoring_backtest_summary(results: list[ExperimentResult]) -> dict:
    """Extract the shared scoring backtest summary from scoring result metrics."""
    for result in results:
        metrics = result.metrics or {}
        nested = metrics.get("scoring_backtest")
        if isinstance(nested, dict):
            sample_count = nested.get("sample_count") or nested.get("ic_count") or nested.get("eval_periods") or 0
            return {
                "scoring_backtest_available": sample_count > 0,
                "scoring_backtest_sample_count": sample_count,
                "scoring_backtest_group_count": nested.get("group_count"),
                "scoring_backtest_ic_mean": nested.get("ic_mean"),
                "scoring_backtest_ic_ir": nested.get("ic_ir"),
                "scoring_backtest_monotonicity": nested.get("monotonicity"),
                "scoring_backtest_monotonicity_by_metric": nested.get("monotonicity_by_metric"),
                "scoring_backtest_group_returns": nested.get("group_returns"),
                "scoring_backtest_group_results": nested.get("group_results"),
                "scoring_backtest_top_bottom_return_spread": nested.get("top_bottom_return_spread"),
                "scoring_backtest_one_sided_p_value": nested.get("top_bottom_one_sided_p_value"),
                "scoring_backtest_future_return_days": nested.get("future_return_days"),
                "scoring_backtest_future_return_months": nested.get("future_return_months"),
                "scoring_backtest_score_date": nested.get("score_date"),
            }
        if "scoring_backtest_available" not in metrics:
            continue
        return {
            "scoring_backtest_available": metrics.get("scoring_backtest_available"),
            "scoring_backtest_sample_count": metrics.get("scoring_backtest_sample_count"),
            "scoring_backtest_group_count": metrics.get("scoring_backtest_group_count"),
            "scoring_backtest_ic_mean": metrics.get("scoring_backtest_ic_mean"),
            "scoring_backtest_ic_ir": metrics.get("scoring_backtest_ic_ir"),
            "scoring_backtest_monotonicity": metrics.get("scoring_backtest_monotonicity"),
            "scoring_backtest_monotonicity_by_metric": metrics.get("scoring_backtest_monotonicity_by_metric"),
            "scoring_backtest_group_returns": metrics.get("scoring_backtest_group_returns"),
            "scoring_backtest_group_results": metrics.get("scoring_backtest_group_results"),
            "scoring_backtest_top_bottom_return_spread": metrics.get("scoring_backtest_top_bottom_return_spread"),
            "scoring_backtest_one_sided_p_value": metrics.get("scoring_backtest_one_sided_p_value"),
            "scoring_backtest_future_return_days": metrics.get("scoring_backtest_future_return_days"),
            "scoring_backtest_score_date": metrics.get("scoring_backtest_score_date"),
        }
    return {
        "scoring_backtest_available": False,
        "scoring_backtest_sample_count": 0,
    }


def _diagnostics_for_algorithm(algorithm_name: str, metrics: dict) -> dict:
    """Return algorithm-specific diagnostics for report readers."""
    if algorithm_name == "simulated_holding":
        return {
            "method": metrics.get("method"),
            "uses_disclosed_holdings": metrics.get("uses_disclosed_holdings"),
            "period_count": metrics.get("period_count"),
            "matched_stock_count": metrics.get("matched_stock_count"),
            "return_sample_count": metrics.get("return_sample_count"),
            "estimated_tracking_error": metrics.get("estimated_overall_tracking_error"),
            "estimated_top10_recall": metrics.get("estimated_overall_top10_recall"),
            "estimated_industry_correlation": metrics.get("estimated_overall_industry_correlation"),
        }
    if algorithm_name == "dynamic_attribution":
        return {
            "method": metrics.get("method"),
            "period_count": metrics.get("period_count"),
            "uses_proxy_benchmark": metrics.get("uses_proxy_benchmark"),
            "uses_proxy_sector_returns": metrics.get("uses_proxy_sector_returns"),
            "estimated_total_portfolio_return": metrics.get("estimated_total_portfolio_return"),
            "estimated_total_benchmark_return": metrics.get("estimated_total_benchmark_return"),
            "estimated_total_residual": metrics.get("estimated_total_residual"),
            "normalized_report_count": len(metrics.get("normalized_weight_sum_by_report") or {}),
        }
    if algorithm_name == "scoring":
        nested_backtest = metrics.get("scoring_backtest") if isinstance(metrics.get("scoring_backtest"), dict) else {}
        return {
            "estimated_total_score": metrics.get("estimated_total_score"),
            "estimated_percentile_rank": metrics.get("estimated_percentile_rank"),
            "verified_dimension_count": metrics.get("verified_dimension_count"),
            "verified_dimensions": metrics.get("verified_dimensions"),
            "allow_estimated": metrics.get("allow_estimated"),
            "estimated_dimensions": metrics.get("estimated_dimensions"),
            "excluded_estimated_dimensions": metrics.get("estimated_dimensions"),
            "estimated_deduction_reasons": metrics.get("estimated_deduction_reasons"),
            "scoring_backtest_available": metrics.get("scoring_backtest_available") or bool(nested_backtest),
            "scoring_backtest_sample_count": (
                metrics.get("scoring_backtest_sample_count")
                or nested_backtest.get("sample_count")
                or nested_backtest.get("ic_count")
                or nested_backtest.get("eval_periods")
            ),
            "scoring_backtest_ic_mean": metrics.get("scoring_backtest_ic_mean") or nested_backtest.get("ic_mean"),
            "scoring_backtest_monotonicity": (
                metrics.get("scoring_backtest_monotonicity")
                if metrics.get("scoring_backtest_monotonicity") is not None
                else nested_backtest.get("monotonicity")
            ),
            "scoring_backtest_monotonicity_by_metric": (
                metrics.get("scoring_backtest_monotonicity_by_metric")
                or nested_backtest.get("monotonicity_by_metric")
            ),
            "scoring_backtest_top_bottom_return_spread": (
                metrics.get("scoring_backtest_top_bottom_return_spread")
                or nested_backtest.get("top_bottom_return_spread")
            ),
            "scoring_backtest_one_sided_p_value": (
                metrics.get("scoring_backtest_one_sided_p_value")
                or nested_backtest.get("top_bottom_one_sided_p_value")
            ),
            "scoring_backtest_score_date": (
                metrics.get("scoring_backtest_score_date")
                or nested_backtest.get("score_date")
            ),
        }
    return {}
