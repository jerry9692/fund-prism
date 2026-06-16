"""Phase 2C acceptance gate tests."""

import json
from pathlib import Path

from typer.testing import CliRunner

from fund_research.cli.main import app
from fund_research.experiments.p2c_acceptance import (
    evaluate_p2c_acceptance,
    render_p2c_acceptance_markdown,
)


def _p2c_report(conclusion_status: str = "needs_review") -> dict:
    algorithms = {}
    readiness = {}
    for algorithm in ("simulated_holding", "dynamic_attribution", "scoring"):
        algorithms[algorithm] = {
            "experiment_summary": {
                "fund_count": 30,
                "success_count": 30,
                "failure_count": 0,
            },
            "aggregate_stats": {"success_rate": 1.0},
            "overall_conclusion": "pass" if algorithm == "simulated_holding" else "partial",
            "conclusion_status": "estimated",
            "per_fund": [],
            "warnings": [],
        }
        readiness[algorithm] = {
            "level": "candidate" if algorithm == "simulated_holding" else "experiment_only",
            "productization_allowed": False,
            "reason": "P2B remains estimated",
        }
    return {
        "report_type": "p2b_validation",
        "report_id": "p2b-test",
        "generated_at": "2026-06-16T15:00:00",
        "expected_fund_count": 30,
        "sample_fund_count": 30,
        "pipeline_gate": {"status": "pass"},
        "productization_gate": {
            "status": "needs_review",
            "warnings": ["productization gate not passed"],
        },
        "conclusion_status": conclusion_status,
        "gate_checks": [],
        "readiness_summary": readiness,
        "algorithms": algorithms,
        "warnings": ["productization gate not passed"],
    }


def test_evaluate_p2c_acceptance_passes_experiment_only_gate(tmp_path: Path) -> None:
    report = _p2c_report()
    report_path = tmp_path / "p2b_validation_report.json"
    history_dir = tmp_path / "p2b_validation_reports"
    history_dir.mkdir()
    history_dir.joinpath("p2b-test.json").write_text("{}", encoding="utf-8")

    evaluation = evaluate_p2c_acceptance(report, report_path=report_path)

    assert evaluation["status"] == "pass"
    assert evaluation["allowed_scope"] == "experiment_view_only"
    assert all(check["passed"] for check in evaluation["checks"] if check["required"])


def test_evaluate_p2c_acceptance_blocks_high_confidence_pollution() -> None:
    report = _p2c_report(conclusion_status="computed")

    evaluation = evaluate_p2c_acceptance(report)

    assert evaluation["status"] == "fail"
    failed = {check["name"] for check in evaluation["checks"] if not check["passed"]}
    assert "no_high_confidence_report_status" in failed


def test_render_p2c_acceptance_markdown_contains_decision() -> None:
    evaluation = evaluate_p2c_acceptance(_p2c_report())

    markdown = render_p2c_acceptance_markdown(evaluation)

    assert "# Phase 2C Acceptance Report" in markdown
    assert "experiment-view use only" in markdown


def test_check_p2c_cli_writes_acceptance_report(tmp_path: Path) -> None:
    report_path = tmp_path / "p2b_validation_report.json"
    history_dir = tmp_path / "p2b_validation_reports"
    history_dir.mkdir()
    history_dir.joinpath("p2b-test.json").write_text("{}", encoding="utf-8")
    report_path.write_text(json.dumps(_p2c_report()), encoding="utf-8")
    output_path = tmp_path / "p2c_acceptance_report.md"

    result = CliRunner().invoke(
        app,
        [
            "check-p2c",
            "--report",
            str(report_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert "status=pass" in result.output
    assert output_path.exists()
