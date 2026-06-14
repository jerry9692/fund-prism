"""CLI check-data tests."""

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import insert
from typer.testing import CliRunner

from fund_research.cli.main import app
from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.metric_registry import seed_metric_registry
from fund_research.db.models import DataSourceSnapshot, TaskLog
from fund_research.db.session import create_engine_from_path, init_db


def test_check_data_validates_initialized_database(tmp_path: Path) -> None:
    """check-data should pass when Phase 0 artifacts and core tables are present."""
    db_path = tmp_path / "fund_research.sqlite"
    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        seed_metric_registry(session)

    result = CliRunner().invoke(app, ["check-data", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "一期核心表" in result.output
    assert "失败任务" in result.output


def test_check_data_fails_when_task_log_has_failed_tasks(tmp_path: Path) -> None:
    """check-data should fail when previous data tasks failed."""
    db_path = tmp_path / "fund_research.sqlite"
    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        seed_metric_registry(session)
    with engine.begin() as connection:
        connection.execute(
            insert(TaskLog).values(
                task_id="task_failed",
                task_type="fund_nav",
                status="failed",
                target_entity="000001",
                error_message="unit test failure",
            )
        )

    result = CliRunner().invoke(app, ["check-data", "--db-path", str(db_path)])

    assert result.exit_code == 1
    assert "failed=1" in result.output


def test_check_data_fails_when_source_snapshot_failed(tmp_path: Path) -> None:
    """check-data should fail when external data source snapshots failed."""
    db_path = tmp_path / "fund_research.sqlite"
    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        seed_metric_registry(session)
    with engine.begin() as connection:
        connection.execute(
            insert(DataSourceSnapshot).values(
                source_name="akshare",
                source_type=DataSourceType.OPEN_API.value,
                source_level=DataSourceLevel.B.value,
                fetch_timestamp=datetime.now(),
                entity_type="fund_nav",
                is_success=False,
                error_message="unit test source failure",
            )
        )

    result = CliRunner().invoke(app, ["check-data", "--db-path", str(db_path)])

    assert result.exit_code == 1
    assert "失败快照" in result.output
    assert "failed=1" in result.output


def test_check_data_uses_latest_source_snapshot_status(tmp_path: Path) -> None:
    """A superseded source failure should not block readiness checks."""
    db_path = tmp_path / "fund_research.sqlite"
    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        seed_metric_registry(session)
    now = datetime.now()
    with engine.begin() as connection:
        connection.execute(
            insert(DataSourceSnapshot),
            [
                {
                    "source_name": "akshare",
                    "source_type": DataSourceType.OPEN_API.value,
                    "source_level": DataSourceLevel.B.value,
                    "fetch_timestamp": now - timedelta(minutes=1),
                    "entity_type": "fund_managers",
                    "is_success": False,
                    "error_message": "old source failure",
                },
                {
                    "source_name": "akshare",
                    "source_type": DataSourceType.OPEN_API.value,
                    "source_level": DataSourceLevel.B.value,
                    "fetch_timestamp": now,
                    "entity_type": "fund_managers",
                    "is_success": True,
                    "error_message": None,
                },
            ],
        )

    result = CliRunner().invoke(app, ["check-data", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert "failed=0" in result.output


def test_check_dynamic_attribution_help_is_available() -> None:
    """The dynamic attribution readiness command should be exposed in the CLI."""
    result = CliRunner().invoke(app, ["check-dynamic-attribution", "--help"])

    assert result.exit_code == 0
    assert "--benchmark-symbol" in result.output
    assert "--ready-only" in result.output
    assert "--min-report-date" in result.output
    assert "--limit" in result.output
    assert "--require-ready" in result.output

    create_result = CliRunner().invoke(app, ["create-dynamic-attribution-experiment", "--help"])
    assert create_result.exit_code == 0
    assert "--report-date" in create_result.output
    assert "--experiment-name" in create_result.output


def test_check_simulated_holding_backtest_help_is_available() -> None:
    """The simulated holding disclosure-period backtest commands should be exposed."""
    result = CliRunner().invoke(app, ["check-simulated-holding-backtest", "--help"])

    assert result.exit_code == 0
    assert "--min-validation-pairs" in result.output
    assert "--min-stock-weight-coverage" in result.output
    assert "--require-industry" in result.output
    assert "--ready-only" in result.output
    assert "--require-ready" in result.output

    create_result = CliRunner().invoke(app, ["create-simulated-holding-backtest-experiment", "--help"])
    assert create_result.exit_code == 0
    assert "--experiment-name" in create_result.output
    assert "--min-report-date" in create_result.output
    assert "--simulation-method" in create_result.output
    assert "--max-positions" in create_result.output
