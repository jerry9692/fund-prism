"""Experiment management module for Phase 2."""

from fund_research.experiments.manager import (
    build_validation_report,
    create_experiment,
    delete_experiment,
    get_experiment,
    list_experiments,
    record_result,
    rerun_experiment,
)
from fund_research.experiments.p2c_acceptance import (
    evaluate_p2c_acceptance,
    load_p2b_report,
    render_p2c_acceptance_markdown,
    write_p2c_acceptance_report,
)
from fund_research.experiments.validation import (
    P2B_ALGORITHMS,
    load_sample_fund_codes,
    render_p2b_validation_markdown,
    run_p2b_validation_report,
    write_p2b_validation_report,
)

__all__ = [
    "P2B_ALGORITHMS",
    "list_experiments",
    "get_experiment",
    "create_experiment",
    "delete_experiment",
    "rerun_experiment",
    "record_result",
    "build_validation_report",
    "evaluate_p2c_acceptance",
    "load_p2b_report",
    "render_p2c_acceptance_markdown",
    "load_sample_fund_codes",
    "run_p2b_validation_report",
    "write_p2b_validation_report",
    "write_p2c_acceptance_report",
    "render_p2b_validation_markdown",
]
