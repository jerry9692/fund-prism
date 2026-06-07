"""Metric registry seeding utilities."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import MetricRegistry

DEFAULT_REGISTRY_PATH = Path("config/metrics_registry_template.yaml")


@dataclass
class MetricRegistrySeedSummary:
    """Summary for metric registry seeding."""

    source_path: Path
    requested: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "requested": self.requested,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "warnings": self.warnings or [],
        }


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def resolve_metric_registry_path(path: Path = DEFAULT_REGISTRY_PATH) -> Path:
    """Resolve the metric registry YAML from cwd or the project tree."""
    if path.is_absolute() or path.exists():
        return path

    for parent in Path(__file__).resolve().parents:
        candidate = parent / path
        if candidate.exists():
            return candidate
    return path


def load_metric_definitions(path: Path) -> list[dict[str, Any]]:
    """Load metric definitions from a YAML registry template."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    metrics = payload.get("metrics", [])
    if not isinstance(metrics, list):
        raise ValueError("metrics registry YAML must contain a list under 'metrics'")
    return [metric for metric in metrics if isinstance(metric, dict)]


def seed_metric_registry(
    session: Session,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    *,
    dry_run: bool = False,
) -> MetricRegistrySeedSummary:
    """Seed metric_registry from YAML definitions."""
    registry_path = resolve_metric_registry_path(registry_path)
    summary = MetricRegistrySeedSummary(source_path=registry_path, warnings=[])
    if not registry_path.exists():
        summary.warnings = [f"指标注册表模板不存在: {registry_path}"]
        return summary

    metrics = load_metric_definitions(registry_path)
    summary.requested = len(metrics)
    for metric in metrics:
        field_name = str(metric.get("field_name") or "").strip()
        name_zh = str(metric.get("name_zh") or "").strip()
        entity_type = str(metric.get("entity_type") or "").strip()
        data_type = str(metric.get("data_type") or "").strip()
        update_frequency = str(metric.get("update_frequency") or "").strip()
        if not all([field_name, name_zh, entity_type, data_type, update_frequency]):
            summary.skipped += 1
            summary.warnings = summary.warnings or []
            summary.warnings.append(f"指标定义缺少必填字段，已跳过: {field_name or '<unknown>'}")
            continue

        existing = session.scalar(
            select(MetricRegistry).where(MetricRegistry.field_name == field_name)
        )
        if dry_run:
            if existing is None:
                summary.inserted += 1
            else:
                summary.updated += 1
            continue

        if existing is None:
            existing = MetricRegistry(
                field_name=field_name,
                name_zh=name_zh,
                entity_type=entity_type,
                data_type=data_type,
                update_frequency=update_frequency,
            )
            session.add(existing)
            summary.inserted += 1
        else:
            summary.updated += 1

        existing.name_zh = name_zh
        existing.name_en = metric.get("name_en")
        existing.entity_type = entity_type
        existing.data_type = data_type
        existing.unit = metric.get("unit")
        existing.formula = metric.get("formula")
        existing.input_fields = _json_text(metric.get("input_fields"))
        existing.applicable_fund_types = _json_text(metric.get("applicable_fund_types"))
        existing.update_frequency = update_frequency
        existing.missing_handling = metric.get("missing_handling")
        existing.outlier_handling = metric.get("outlier_handling")
        existing.limitations = metric.get("limitations")
        existing.explanation = metric.get("explanation")
        existing.ai_schema = metric
        existing.metric_group = metric.get("metric_group")
        existing.version = str(metric.get("version") or "1.0.0")
        existing.is_active = bool(metric.get("is_active", True))

    if not dry_run:
        session.commit()
    return summary
