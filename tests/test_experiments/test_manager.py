"""Phase 2 experiment manager tests."""

from datetime import date

from sqlalchemy.orm import Session

from fund_research.db.models import AlgorithmExperiment, ExperimentResult
from fund_research.experiments.manager import (
    create_experiment,
    delete_experiment,
    list_experiments,
    record_result,
    rerun_experiment,
)


def test_experiment_manager_crud_uses_registered_phase2_models(test_session: Session) -> None:
    exp = create_experiment(
        test_session,
        experiment_name="模拟持仓参数实验",
        algorithm_name="simulated_holding",
        algorithm_version="0.1.0",
        parameters={"max_positions": 30},
        sample_fund_codes=["000001"],
        backtest_start=date(2024, 1, 1),
        backtest_end=date(2024, 12, 31),
    )

    assert isinstance(exp, AlgorithmExperiment)
    result = record_result(
        test_session,
        experiment_id=exp.id,
        fund_code="000001",
        calc_date=date(2024, 6, 30),
        is_success=False,
        metrics={"top10_recall": 0.4},
        error_message="低于阈值",
        warnings=["重仓股召回率不足"],
    )
    assert isinstance(result, ExperimentResult)

    summaries = list_experiments(test_session, algorithm_name="simulated_holding")
    assert len(summaries) == 1
    assert summaries[0].fund_count == 1
    assert summaries[0].failure_count == 1

    rerun = rerun_experiment(test_session, exp.id)
    assert rerun.status == "pending"
    assert list_experiments(test_session)[0].fund_count == 0

    delete_experiment(test_session, exp.id)
    assert list_experiments(test_session) == []
