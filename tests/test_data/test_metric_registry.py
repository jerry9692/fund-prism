"""Metric registry seed tests."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.data.metric_registry import resolve_metric_registry_path, seed_metric_registry
from fund_research.db.models import MetricRegistry


def test_seed_metric_registry_inserts_template_metrics(test_session: Session) -> None:
    """Metric registry seeding should load YAML definitions into the database."""
    summary = seed_metric_registry(test_session, Path("config/metrics_registry_template.yaml"))

    metric = test_session.scalar(
        select(MetricRegistry).where(MetricRegistry.field_name == "annualized_return")
    )

    assert summary.inserted >= 1
    assert summary.skipped == 0
    assert metric is not None
    assert metric.name_zh == "年化收益率"
    assert metric.input_fields == '["adjusted_nav"]'
    assert metric.ai_schema is not None
    assert metric.ai_schema["metric_group"] == "return"


def test_seed_metric_registry_is_idempotent(test_session: Session) -> None:
    """Repeating registry seed should update existing metrics instead of duplicating rows."""
    first = seed_metric_registry(test_session, Path("config/metrics_registry_template.yaml"))
    second = seed_metric_registry(test_session, Path("config/metrics_registry_template.yaml"))
    metric_count = test_session.scalar(select(func.count()).select_from(MetricRegistry))

    assert first.inserted >= 1
    assert second.inserted == 0
    assert second.updated == first.inserted
    assert metric_count == first.inserted


def test_seed_metric_registry_default_path_works_outside_project_root(
    test_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default registry path should resolve even when cwd is not the project root."""
    monkeypatch.chdir(tmp_path)

    summary = seed_metric_registry(test_session)

    assert summary.inserted >= 1
    assert resolve_metric_registry_path().is_absolute()
