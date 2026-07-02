"""Phase 2B validation report orchestration."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from fund_research.experiments.manager import (
    build_validation_report,
    create_experiment,
    update_experiment_status,
)
from fund_research.experiments.runner import dispatch_run

P2B_ALGORITHMS = ("simulated_holding", "dynamic_attribution", "scoring")
P2B_HISTORY_DIR_NAME = "p2b_validation_reports"

DEFAULT_MIN_RETURN_OBSERVATIONS = 20
DEFAULT_MIN_STOCK_WEIGHT_COVERAGE = 0.6
DEFAULT_MAX_BENCHMARK_WEIGHT_SNAPSHOT_AGE_DAYS = 365

PRODUCTIZATION_MIN_SCORING_IC_MEAN = 0.10
PRODUCTIZATION_MIN_SCORING_IC_IR = 0.5
PRODUCTIZATION_MIN_SCORING_SAMPLE_COUNT = 20
PRODUCTIZATION_MAX_SIM_HOLDING_TE = 0.05
PRODUCTIZATION_MIN_SIM_HOLDING_TOP10_RECALL = 0.5
PRODUCTIZATION_MIN_SIM_HOLDING_SUCCESS_RATE = 0.7


def load_sample_fund_codes(sample_path: Path, limit: int | None = None) -> list[str]:
    """Load fund codes from the Phase 0/1 sample CSV."""
    with sample_path.open(encoding="utf-8", newline="") as file:
        codes = [
            str(row.get("fund_code", "")).strip()
            for row in csv.DictReader(file)
            if str(row.get("fund_code", "")).strip()
        ]
    return codes[:limit] if limit else codes


def run_p2b_validation_report(
    db: Session,
    fund_codes: list[str],
    algorithms: list[str] | None = None,
    *,
    experiment_prefix: str = "p2b-validation",
    algorithm_version: str = "0.1.0",
    expected_fund_count: int = 30,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Run P2B experiment batches and return an auditable acceptance report.

    The report is deliberately capped at estimated/needs_review status; P2B
    outputs must not become default high-confidence conclusions.
    """
    selected_algorithms = algorithms or list(P2B_ALGORITHMS)
    run_date = date.today().isoformat()
    generated_at = datetime.now().isoformat(timespec="seconds")
    report_id = f"p2b-{generated_at.replace(':', '').replace('-', '').replace('T', '-')}"
    algorithm_reports: dict[str, Any] = {}

    if progress_callback:
        progress_callback({
            "stage": "running",
            "message": "P2B validation started",
            "current": 0,
            "total": len(selected_algorithms),
            "percent": 0,
        })

    for index, algorithm in enumerate(selected_algorithms, start=1):
        if progress_callback:
            progress_callback({
                "stage": "algorithm_running",
                "algorithm": algorithm,
                "message": f"Running {algorithm}",
                "current": index - 1,
                "total": len(selected_algorithms),
                "percent": round((index - 1) / len(selected_algorithms) * 90, 1),
            })
        algorithm_params: dict[str, Any] = {
            "validation_scope": "P2B",
            "expected_fund_count": expected_fund_count,
            "min_return_observations": DEFAULT_MIN_RETURN_OBSERVATIONS,
            "min_stock_weight_coverage": DEFAULT_MIN_STOCK_WEIGHT_COVERAGE,
        }
        if algorithm == "dynamic_attribution":
            algorithm_params["max_benchmark_weight_snapshot_age_days"] = DEFAULT_MAX_BENCHMARK_WEIGHT_SNAPSHOT_AGE_DAYS
        exp = create_experiment(
            db,
            experiment_name=f"{experiment_prefix}-{algorithm}-{run_date}",
            algorithm_name=algorithm,
            algorithm_version=algorithm_version,
            parameters=algorithm_params,
            sample_fund_codes=fund_codes,
        )
        update_experiment_status(db, exp.id, "running")
        results = dispatch_run(db, exp)
        fund_count = len(results)
        success_count = sum(1 for result in results if result.get("is_success"))
        failure_count = fund_count - success_count
        if fund_count == 0 or success_count == 0:
            final_status = "failed"
        elif failure_count:
            final_status = "completed_with_failures"
        else:
            final_status = "completed"
        update_experiment_status(
            db,
            exp.id,
            final_status,
            f"P2B validation: success={success_count}, failure={failure_count}",
        )
        algorithm_reports[algorithm] = build_validation_report(db, exp.id)
        if progress_callback:
            progress_callback({
                "stage": "algorithm_completed",
                "algorithm": algorithm,
                "message": f"Completed {algorithm}",
                "current": index,
                "total": len(selected_algorithms),
                "percent": round(index / len(selected_algorithms) * 90, 1),
            })

    gate_checks = _build_gate_checks(
        algorithm_reports,
        fund_count=len(fund_codes),
        expected_fund_count=expected_fund_count,
        selected_algorithms=selected_algorithms,
    )
    pipeline_conclusion = _pipeline_conclusion(gate_checks)
    readiness_summary = _readiness_summary(algorithm_reports)
    productization_gate = _productization_gate(readiness_summary)

    return {
        "report_type": "p2b_validation",
        "report_id": report_id,
        "generated_at": generated_at,
        "generated_date": run_date,
        "expected_fund_count": expected_fund_count,
        "sample_fund_count": len(fund_codes),
        "sample_fund_codes": fund_codes,
        "algorithms": algorithm_reports,
        "gate_checks": gate_checks,
        "failure_summary": _failure_summary(algorithm_reports),
        "readiness_summary": readiness_summary,
        "pipeline_gate": {
            "status": pipeline_conclusion,
            "conclusion_status": "estimated" if pipeline_conclusion != "fail" else "needs_review",
        },
        "productization_gate": productization_gate,
        # Backward-compatible alias: this is the pipeline conclusion, not product readiness.
        "overall_conclusion": pipeline_conclusion,
        "conclusion_status": productization_gate["conclusion_status"],
        "warnings": _report_warnings(gate_checks) + productization_gate["warnings"],
    }


def write_p2b_validation_report(
    report: dict[str, Any],
    output_path: Path,
    *,
    archive_history: bool = True,
) -> Path | None:
    """Persist a P2B report and optionally archive JSON reports by report_id."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".md":
        output_path.write_text(render_p2b_validation_markdown(report), encoding="utf-8")
        return None

    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    if not archive_history:
        return None

    history_path = p2b_validation_history_path(output_path, report)
    if history_path.resolve() == output_path.resolve():
        return history_path
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return history_path


def p2b_validation_history_path(output_path: Path, report: dict[str, Any]) -> Path:
    """Return the history snapshot path for a generated P2B report."""
    report_id = str(report.get("report_id") or report.get("generated_at") or "unknown")
    safe_report_id = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in report_id
    ).strip("-") or "unknown"
    return output_path.parent / P2B_HISTORY_DIR_NAME / f"{safe_report_id}.json"


def render_p2b_validation_markdown(report: dict[str, Any]) -> str:
    """Render a compact Markdown summary for human review."""
    lines = [
        "# P2B Validation Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Sample funds: {report['sample_fund_count']}/{report['expected_fund_count']}",
        f"- Pipeline gate: {report.get('pipeline_gate', {}).get('status', report['overall_conclusion'])}",
        f"- Productization gate: {report.get('productization_gate', {}).get('status', 'needs_review')}",
        f"- Conclusion status: {report['conclusion_status']}",
        "",
        "## Gate Checks",
        "",
        "| Check | Passed | Detail |",
        "| --- | --- | --- |",
    ]
    for check in report["gate_checks"]:
        lines.append(
            f"| {check['name']} | {'yes' if check['passed'] else 'no'} | {check['detail']} |"
        )

    lines.extend(["", "## Algorithms", "", "| Algorithm | Funds | Success rate | Conclusion | Readiness |"])
    lines.append("| --- | ---: | ---: | --- | --- |")
    for algorithm, algorithm_report in report["algorithms"].items():
        summary = algorithm_report.get("experiment_summary", {})
        stats = algorithm_report.get("aggregate_stats", {})
        readiness = (report.get("readiness_summary") or {}).get(algorithm, {})
        lines.append(
            "| "
            f"{algorithm} | "
            f"{summary.get('fund_count', 0)} | "
            f"{stats.get('success_rate', 0):.1%} | "
            f"{algorithm_report.get('overall_conclusion')} | "
            f"{readiness.get('level', 'unknown')} |"
        )

    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])

    return "\n".join(lines) + "\n"


def _build_gate_checks(
    algorithm_reports: dict[str, Any],
    *,
    fund_count: int,
    expected_fund_count: int,
    selected_algorithms: list[str],
) -> list[dict[str, Any]]:
    report_complete = all(
        algorithm in algorithm_reports and "experiment_summary" in algorithm_reports[algorithm]
        for algorithm in selected_algorithms
    )
    no_high_confidence = all(
        (report.get("conclusion_status") not in {"fact", "computed"})
        for report in algorithm_reports.values()
    )
    every_algorithm_touched_sample = all(
        report.get("experiment_summary", {}).get("fund_count", 0) == fund_count
        for report in algorithm_reports.values()
    )
    simulated = algorithm_reports.get("simulated_holding", {})
    simulated_stats = simulated.get("aggregate_stats", {})
    simulated_has_threshold_metrics = (
        simulated_stats.get("mean_estimated_tracking_error") is not None
        and simulated_stats.get("mean_estimated_top10_recall") is not None
    )
    algorithm_thresholds_passed = all(
        report.get("overall_conclusion") != "fail"
        for report in algorithm_reports.values()
    )
    scoring_report = algorithm_reports.get("scoring", {})
    scoring_stats = scoring_report.get("aggregate_stats", {})
    scoring_backtest_required = "scoring" in selected_algorithms
    scoring_backtest_available = (
        not scoring_backtest_required
        or (
            scoring_stats.get("scoring_backtest_available") is True
            and int(scoring_stats.get("scoring_backtest_sample_count") or 0) > 0
        )
    )
    failed_algorithms = [
        algorithm
        for algorithm, report in algorithm_reports.items()
        if report.get("overall_conclusion") == "fail"
    ]

    return [
        {
            "name": "sample_size",
            "passed": fund_count >= expected_fund_count,
            "detail": f"{fund_count}/{expected_fund_count} funds",
        },
        {
            "name": "algorithm_reports",
            "passed": report_complete,
            "detail": f"{len(algorithm_reports)}/{len(selected_algorithms)} reports",
        },
        {
            "name": "sample_coverage",
            "passed": every_algorithm_touched_sample,
            "detail": "each selected algorithm produced one row per sample fund",
        },
        {
            "name": "simulated_holding_threshold_metrics",
            "passed": simulated_has_threshold_metrics,
            "detail": "TE and top10 recall are present for threshold review",
        },
        {
            "name": "algorithm_thresholds",
            "passed": algorithm_thresholds_passed,
            "detail": (
                "all selected algorithms are not fail"
                if algorithm_thresholds_passed
                else f"failed={', '.join(failed_algorithms)}"
            ),
        },
        {
            "name": "scoring_backtest",
            "passed": scoring_backtest_available,
            "detail": (
                "scoring backtest is available"
                if scoring_backtest_available
                else "scoring selected but no future-return backtest was produced"
            ),
        },
        {
            "name": "estimated_isolation",
            "passed": no_high_confidence,
            "detail": "P2B conclusions remain estimated/needs_review, never fact/computed",
        },
    ]


def _pipeline_conclusion(gate_checks: list[dict[str, Any]]) -> str:
    failed = [check for check in gate_checks if not check["passed"]]
    if not failed:
        return "pass"
    hard_failures = {"algorithm_thresholds", "estimated_isolation"}
    if any(check["name"] in hard_failures for check in failed):
        return "fail"
    return "partial"


def _readiness_summary(algorithm_reports: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        algorithm: _algorithm_readiness(algorithm, report)
        for algorithm, report in algorithm_reports.items()
    }


def _algorithm_readiness(algorithm: str, report: dict[str, Any]) -> dict[str, Any]:
    overall = report.get("overall_conclusion")
    rows = report.get("per_fund", [])
    stats = report.get("aggregate_stats", {})
    warnings = [warning for row in rows for warning in (row.get("warnings") or [])]
    proxy_used = any(
        (row.get("diagnostics") or {}).get("uses_proxy_benchmark")
        or (row.get("diagnostics") or {}).get("uses_proxy_sector_returns")
        for row in rows
    )

    if overall == "fail":
        return {
            "level": "experiment_only",
            "productization_allowed": False,
            "reason": "algorithm validation failed",
            "metrics": {"overall": overall},
        }

    if algorithm == "dynamic_attribution":
        if proxy_used:
            return {
                "level": "experiment_only",
                "productization_allowed": False,
                "reason": "uses proxy benchmark/sector returns; formal attribution needs real benchmark data",
                "metrics": {"proxy_used": True, "warning_count": len(warnings)},
            }
        if warnings:
            return {
                "level": "candidate",
                "productization_allowed": False,
                "reason": (
                    f"attribution passed with {len(warnings)} residual warnings; "
                    "requires clean run before productization"
                ),
                "metrics": {"proxy_used": False, "warning_count": len(warnings)},
            }
        return {
            "level": "candidate",
            "productization_allowed": False,
            "reason": "attribution passed without proxy; needs longer validation window for productization",
            "metrics": {"proxy_used": False, "warning_count": 0},
        }

    if algorithm == "scoring":
        verified_counts = [
            (row.get("diagnostics") or {}).get("verified_dimension_count") or 0
            for row in rows
        ]
        min_verified = min(verified_counts) if verified_counts else 0
        avg_verified = sum(verified_counts) / len(verified_counts) if verified_counts else 0
        bt_samples = int(stats.get("scoring_backtest_sample_count") or 0)
        bt_ic_mean = stats.get("scoring_backtest_ic_mean")
        bt_ic_ir = stats.get("scoring_backtest_ic_ir")
        bt_monotonicity = stats.get("scoring_backtest_monotonicity")
        has_backtest = (
            stats.get("scoring_backtest_available") is True
            and bt_samples > 0
        )

        metrics = {
            "min_verified_dimensions": min_verified,
            "avg_verified_dimensions": round(avg_verified, 2),
            "backtest_samples": bt_samples,
            "backtest_ic_mean": bt_ic_mean,
            "backtest_ic_ir": bt_ic_ir,
            "backtest_monotonicity": bt_monotonicity,
        }

        if not has_backtest:
            return {
                "level": "experiment_only",
                "productization_allowed": False,
                "reason": f"only {min_verified} verified scoring dimensions; score backtest still required",
                "metrics": metrics,
            }

        if overall != "pass" or min_verified < 4:
            return {
                "level": "candidate",
                "productization_allowed": False,
                "reason": (
                    f"score backtest available on {bt_samples} samples, "
                    f"but only {min_verified} verified scoring dimensions"
                ),
                "metrics": metrics,
            }

        failed_gates = []
        if bt_samples < PRODUCTIZATION_MIN_SCORING_SAMPLE_COUNT:
            failed_gates.append(f"sample_count={bt_samples} < {PRODUCTIZATION_MIN_SCORING_SAMPLE_COUNT}")
        if bt_ic_mean is None or bt_ic_mean < PRODUCTIZATION_MIN_SCORING_IC_MEAN:
            failed_gates.append(f"ic_mean={bt_ic_mean} < {PRODUCTIZATION_MIN_SCORING_IC_MEAN}")
        if bt_ic_ir is None or bt_ic_ir < PRODUCTIZATION_MIN_SCORING_IC_IR:
            failed_gates.append(f"ic_ir={bt_ic_ir} < {PRODUCTIZATION_MIN_SCORING_IC_IR}")
        if bt_monotonicity is not True:
            failed_gates.append(f"monotonicity={bt_monotonicity} != True")

        if failed_gates:
            return {
                "level": "candidate",
                "productization_allowed": False,
                "reason": "productization gates failed: " + "; ".join(failed_gates),
                "metrics": metrics,
            }

        return {
            "level": "product_ready",
            "productization_allowed": True,
            "reason": "all scoring productization thresholds passed",
            "metrics": metrics,
        }

    if algorithm == "simulated_holding":
        method = next(
            (
                (row.get("diagnostics") or {}).get("method")
                for row in rows
                if (row.get("diagnostics") or {}).get("method")
            ),
            None,
        )
        uses_optimizer = method in ("optimized", "cvxpy", "scipy")
        mean_te = stats.get("mean_estimated_tracking_error")
        mean_recall = stats.get("mean_estimated_top10_recall")
        success_rate = stats.get("success_rate")

        metrics = {
            "method": method,
            "uses_optimizer": uses_optimizer,
            "mean_tracking_error": mean_te,
            "mean_top10_recall": mean_recall,
            "success_rate": success_rate,
        }

        failed_gates = []
        if not uses_optimizer:
            failed_gates.append(f"method={method} not optimizer-based")
        if success_rate is None or success_rate < PRODUCTIZATION_MIN_SIM_HOLDING_SUCCESS_RATE:
            failed_gates.append(f"success_rate={success_rate} < {PRODUCTIZATION_MIN_SIM_HOLDING_SUCCESS_RATE}")
        if mean_te is None or mean_te > PRODUCTIZATION_MAX_SIM_HOLDING_TE:
            failed_gates.append(f"mean_te={mean_te} > {PRODUCTIZATION_MAX_SIM_HOLDING_TE}")
        if mean_recall is None or mean_recall < PRODUCTIZATION_MIN_SIM_HOLDING_TOP10_RECALL:
            failed_gates.append(f"mean_recall={mean_recall} < {PRODUCTIZATION_MIN_SIM_HOLDING_TOP10_RECALL}")

        if failed_gates:
            return {
                "level": "candidate",
                "productization_allowed": False,
                "reason": "productization gates failed: " + "; ".join(failed_gates),
                "metrics": metrics,
            }

        return {
            "level": "product_ready",
            "productization_allowed": True,
            "reason": "all simulated holding productization thresholds passed",
            "metrics": metrics,
        }

    return {
        "level": "candidate" if overall in {"pass", "partial"} else "experiment_only",
        "productization_allowed": False,
        "reason": "P2B validation output remains estimated by design",
        "metrics": {"overall": overall},
    }


def _productization_gate(readiness_summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    blockers = [
        f"{algorithm}: {data['reason']}"
        for algorithm, data in readiness_summary.items()
        if not data.get("productization_allowed")
    ]
    if blockers:
        return {
            "status": "needs_review",
            "conclusion_status": "needs_review",
            "warnings": ["产品化门禁未通过: " + "; ".join(blockers)],
        }
    return {
        "status": "pass",
        "conclusion_status": "estimated",
        "warnings": [],
    }


def _failure_summary(algorithm_reports: dict[str, Any]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for algorithm, report in algorithm_reports.items():
        counter: Counter[str] = Counter()
        for row in report.get("per_fund", []):
            reason = row.get("error_message")
            if reason:
                counter[str(reason)] += 1
        summary[algorithm] = dict(counter)
    return summary


def _report_warnings(gate_checks: list[dict[str, Any]]) -> list[str]:
    return [
        f"{check['name']} 未通过: {check['detail']}"
        for check in gate_checks
        if not check["passed"]
    ]
