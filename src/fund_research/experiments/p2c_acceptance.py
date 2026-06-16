"""Phase 2C acceptance gate for P2B validation reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

P2C_REQUIRED_ALGORITHMS = ("simulated_holding", "dynamic_attribution", "scoring")
HIGH_CONFIDENCE_STATUSES = {"fact", "computed"}


def load_p2b_report(report_path: Path) -> dict[str, Any]:
    """Load the latest P2B validation report JSON."""
    return json.loads(report_path.read_text(encoding="utf-8"))


def evaluate_p2c_acceptance(
    report: dict[str, Any],
    *,
    report_path: Path | None = None,
    expected_fund_count: int = 30,
) -> dict[str, Any]:
    """Evaluate whether Phase 2C is acceptable as an experiment-only release gate."""
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: str, *, required: bool = True) -> None:
        checks.append({
            "name": name,
            "passed": passed,
            "required": required,
            "detail": detail,
        })

    sample_fund_count = report.get("sample_fund_count")
    expected_in_report = report.get("expected_fund_count")
    add_check(
        "report_type",
        report.get("report_type") == "p2b_validation",
        f"report_type={report.get('report_type')}",
    )
    add_check(
        "sample_size",
        sample_fund_count == expected_fund_count and expected_in_report == expected_fund_count,
        f"sample={sample_fund_count}, expected={expected_in_report}, required={expected_fund_count}",
    )
    add_check(
        "pipeline_gate",
        (report.get("pipeline_gate") or {}).get("status") == "pass",
        f"pipeline_gate={(report.get('pipeline_gate') or {}).get('status')}",
    )

    productization_status = (report.get("productization_gate") or {}).get("status")
    productization_warnings = (report.get("productization_gate") or {}).get("warnings") or []
    productization_allowed = productization_status in {"needs_review", "pass"}
    add_check(
        "productization_gate_recorded",
        productization_allowed,
        f"productization_gate={productization_status}",
    )
    add_check(
        "productization_blockers_documented",
        productization_status != "needs_review" or bool(productization_warnings),
        f"warnings={len(productization_warnings)}",
    )

    conclusion_status = report.get("conclusion_status")
    add_check(
        "no_high_confidence_report_status",
        conclusion_status not in HIGH_CONFIDENCE_STATUSES,
        f"conclusion_status={conclusion_status}",
    )

    algorithms = report.get("algorithms") or {}
    missing_algorithms = sorted(set(P2C_REQUIRED_ALGORITHMS) - set(algorithms))
    add_check(
        "required_algorithms_present",
        not missing_algorithms,
        "all required algorithms present" if not missing_algorithms else f"missing={missing_algorithms}",
    )

    algorithm_statuses = {
        algorithm: algorithm_report.get("conclusion_status")
        for algorithm, algorithm_report in algorithms.items()
    }
    high_confidence_algorithms = {
        algorithm: status
        for algorithm, status in algorithm_statuses.items()
        if status in HIGH_CONFIDENCE_STATUSES
    }
    add_check(
        "no_high_confidence_algorithm_status",
        not high_confidence_algorithms,
        (
            "algorithm statuses remain estimated/needs_review/observation"
            if not high_confidence_algorithms
            else f"blocked={high_confidence_algorithms}"
        ),
    )

    fund_count_mismatches = {
        algorithm: (algorithm_report.get("experiment_summary") or {}).get("fund_count")
        for algorithm, algorithm_report in algorithms.items()
        if (algorithm_report.get("experiment_summary") or {}).get("fund_count") != sample_fund_count
    }
    add_check(
        "algorithm_sample_coverage",
        not fund_count_mismatches,
        "each algorithm covered sample funds" if not fund_count_mismatches else f"mismatches={fund_count_mismatches}",
    )

    readiness_summary = report.get("readiness_summary") or {}
    productization_leaks = {
        algorithm: data
        for algorithm, data in readiness_summary.items()
        if data.get("productization_allowed") is True
    }
    add_check(
        "estimated_pollution_isolation",
        not productization_leaks,
        (
            "all P2B outputs remain outside default productization"
            if not productization_leaks
            else f"productization_allowed={sorted(productization_leaks)}"
        ),
    )

    history_snapshot_ok = True
    history_detail = "not checked"
    report_id = report.get("report_id")
    if report_path and report_id:
        history_path = report_path.parent / "p2b_validation_reports" / f"{report_id}.json"
        history_snapshot_ok = history_path.exists()
        history_detail = str(history_path)
    add_check(
        "history_snapshot",
        history_snapshot_ok,
        history_detail,
        required=bool(report_path and report_id),
    )

    passed = all(check["passed"] for check in checks if check["required"])
    return {
        "gate": "P2C",
        "status": "pass" if passed else "fail",
        "allowed_next_phase": passed,
        "allowed_scope": "experiment_view_only" if passed else "blocked",
        "report_id": report_id,
        "generated_at": report.get("generated_at"),
        "source_report": str(report_path) if report_path else None,
        "checks": checks,
        "summary": {
            "sample_fund_count": sample_fund_count,
            "expected_fund_count": expected_in_report,
            "pipeline_gate": (report.get("pipeline_gate") or {}).get("status"),
            "productization_gate": productization_status,
            "conclusion_status": conclusion_status,
            "algorithm_count": len(algorithms),
            "warning_count": len(report.get("warnings") or []),
        },
        "release_constraints": [
            "P2B outputs may be shown only in experiment or validation views.",
            "Estimated holdings, attribution, and scoring outputs must not enter default Research Packet conclusions.",
            "No P2B output may be presented as fact or computed high-confidence evidence.",
            (
                "Productization requires separate gates for real benchmark data, "
                "score backtesting, and stricter estimated-view controls."
            ),
        ],
    }


def render_p2c_acceptance_markdown(evaluation: dict[str, Any]) -> str:
    """Render a human-readable P2C acceptance report."""
    summary = evaluation["summary"]
    lines = [
        "# Phase 2C Acceptance Report",
        "",
        f"- Gate: {evaluation['gate']}",
        f"- Status: {evaluation['status']}",
        f"- Allowed next phase: {evaluation['allowed_next_phase']}",
        f"- Allowed scope: {evaluation['allowed_scope']}",
        f"- Source report: {evaluation.get('source_report') or '-'}",
        f"- Report ID: {evaluation.get('report_id') or '-'}",
        f"- Generated at: {evaluation.get('generated_at') or '-'}",
        "",
        "## Summary",
        "",
        f"- Sample funds: {summary.get('sample_fund_count')}/{summary.get('expected_fund_count')}",
        f"- Pipeline gate: {summary.get('pipeline_gate')}",
        f"- Productization gate: {summary.get('productization_gate')}",
        f"- Conclusion status: {summary.get('conclusion_status')}",
        f"- Algorithms: {summary.get('algorithm_count')}",
        f"- Warnings: {summary.get('warning_count')}",
        "",
        "## Checks",
        "",
        "| Check | Required | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for check in evaluation["checks"]:
        lines.append(
            "| "
            f"{check['name']} | "
            f"{'yes' if check['required'] else 'no'} | "
            f"{'pass' if check['passed'] else 'fail'} | "
            f"{check['detail']} |"
        )

    lines.extend(["", "## Release Constraints", ""])
    lines.extend(f"- {constraint}" for constraint in evaluation["release_constraints"])
    lines.extend([
        "",
        "## Decision",
        "",
        (
            "Phase 2C is accepted for experiment-view use only. "
            "It does not approve productized scoring, default Research Packet conclusions, "
            "or high-confidence claims based on estimated outputs."
            if evaluation["status"] == "pass"
            else "Phase 2C is not accepted. Blocking checks must be fixed before entering the next phase."
        ),
    ])
    return "\n".join(lines) + "\n"


def write_p2c_acceptance_report(evaluation: dict[str, Any], output_path: Path) -> None:
    """Write the P2C acceptance report as Markdown."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_p2c_acceptance_markdown(evaluation), encoding="utf-8")
