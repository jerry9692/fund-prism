"""
Phase 2 v2 Tool API — experiment management and algorithm endpoints.

All endpoints follow the unified APIResponse[T] contract.
"""

import json
import threading
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.analysis.anomaly import (
    ALGORITHM_NAME as ANOMALY_NAME,
)
from fund_research.analysis.anomaly import (
    ALGORITHM_VERSION as ANOMALY_VERSION,
)
from fund_research.analysis.anomaly import (
    ANOMALY_RULES,
    persist_anomaly,
    scan_anomalies,
)
from fund_research.analysis.dashboard import (
    ALGORITHM_NAME as DASHBOARD_NAME,
)
from fund_research.analysis.dashboard import (
    ALGORITHM_VERSION as DASHBOARD_VERSION,
)
from fund_research.analysis.dashboard import generate_dashboard
from fund_research.analysis.fingerprint import (
    ALGORITHM_VERSION as FINGERPRINT_VERSION,
)
from fund_research.analysis.fingerprint import (
    fingerprint_to_dict,
    generate_fingerprint,
    get_latest_fingerprint,
    persist_fingerprint,
)
from fund_research.analysis.pool_alert import (
    ALERT_TYPES,
    create_alert_rule,
    get_alert_records,
    get_alert_rules,
    mark_alert_read,
    persist_alerts,
    scan_pool_alerts,
)
from fund_research.analysis.pool_alert import (
    ALGORITHM_NAME as POOL_ALERT_NAME,
)
from fund_research.analysis.pool_alert import (
    ALGORITHM_VERSION as POOL_ALERT_VERSION,
)
from fund_research.analysis.research_template import (
    ALGORITHM_NAME as TEMPLATE_NAME,
)
from fund_research.analysis.research_template import (
    ALGORITHM_VERSION as TEMPLATE_VERSION,
)
from fund_research.analysis.research_template import (
    get_run_record,
    get_run_records,
    get_template,
    list_templates,
    run_template,
    seed_builtin_templates,
)
from fund_research.analysis.reverse_lookup import (
    ALGORITHM_NAME as REVERSE_LOOKUP_NAME,
)
from fund_research.analysis.reverse_lookup import (
    ALGORITHM_VERSION as REVERSE_LOOKUP_VERSION,
)
from fund_research.analysis.reverse_lookup import (
    persist_result as persist_reverse_lookup,
)
from fund_research.analysis.reverse_lookup import (
    reverse_lookup,
)
from fund_research.analysis.scoring import ALGORITHM_VERSION as SCORING_VERSION
from fund_research.analysis.similarity import (
    compare_fund_fingerprints,
    find_similar_funds,
    persist_similarity_cache,
)
from fund_research.api.deps import get_session
from fund_research.config.settings import get_settings
from fund_research.core.enums import ConclusionStatus, ConfidenceLevel, DataSourceLevel, EvidenceType
from fund_research.core.schemas import APIResponse, EvidenceRecord
from fund_research.db.models import (
    AlgorithmExperiment,
    DataSourceSnapshot,
    FundMain,
    ResearchPacketRecord,
    TaskLog,
    ToolAPICallLog,
)
from fund_research.db.models import (
    EvidenceRecord as DbEvidenceRecord,
)
from fund_research.db.models import (
    ReviewerAnnotation as DbReviewerAnnotation,
)
from fund_research.db.models import (
    ScoringBacktest as DbScoringBacktest,
)
from fund_research.db.models import (
    ScoringResult as DbScoringResult,
)
from fund_research.db.models import (
    SimulatedHoldingResult as DbSimulatedHoldingResult,
)
from fund_research.db.models_phase3 import (  # noqa: F401
    AnomalyRecord,
    FundComparisonCache,
    FundFingerprint,
    PoolAlertRecord,
    PoolAlertRule,
    ResearchTemplate,
    ReverseLookupResult,
    TemplateRunRecord,
)
from fund_research.db.session import get_session_factory
from fund_research.experiments.manager import (
    create_experiment,
    delete_experiment,
    get_experiment_results,
    list_experiments,
    record_result,
    rerun_experiment,
    update_experiment_status,
)
from fund_research.experiments.readiness import assess_dynamic_attribution_readiness
from fund_research.experiments.runner import dispatch_run
from fund_research.experiments.validation import (
    P2B_ALGORITHMS,
    load_sample_fund_codes,
    run_p2b_validation_report,
    write_p2b_validation_report,
)
from fund_research.research.packet import build_single_fund_packet, persist_research_packet

v2_router = APIRouter(prefix="/api/v2", tags=["Tool API v2"])

SessionDep = Annotated[Session, Depends(get_session)]


class CreateExperimentRequest(BaseModel):
    experiment_name: str = "Untitled"
    algorithm_name: str = "unknown"
    algorithm_version: str = "0.1.0"
    parameters: dict[str, Any] = Field(default_factory=dict)
    sample_fund_codes: list[str] | None = None
    backtest_start: date | None = None
    backtest_end: date | None = None


class CreateDynamicAttributionFromReadyRequest(BaseModel):
    experiment_name: str = "Dynamic attribution ready sample"
    algorithm_version: str = "0.1.0"
    report_date: date
    benchmark_symbol: str | None = None
    fund_codes: list[str] | None = None
    min_return_observations: int = 3
    max_snapshot_age_days: int = 180
    limit: int | None = None


class ScoringBacktestRequest(BaseModel):
    experiment_name: str = "Scoring IC backtest"
    algorithm_version: str = "0.1.0"
    fund_codes: list[str]
    backtest_start: date
    backtest_end: date
    preset: str = "均衡型"
    category: str = "混合型-偏股"
    weights: dict[str, float] | None = None
    min_funds_per_date: int = 5
    forward_months: int = Field(default=12, ge=1, le=24)
    min_forward_observations: int = Field(default=60, ge=1)


class ScoringRequest(BaseModel):
    fund_codes: list[str]
    preset: str = "均衡型"
    category: str = "混合型-偏股"
    weights: dict[str, float] | None = None


class RecordExperimentResultRequest(BaseModel):
    fund_code: str
    calc_date: date
    is_success: bool = True
    metrics: dict[str, Any] | None = None
    error_message: str | None = None
    warnings: list[str] | None = None


class RerunP2BValidationRequest(BaseModel):
    algorithms: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=30)


class SimulatedHoldingRequest(BaseModel):
    """Request to run simulated holding estimation for a fund.

    Per requirements §5.1.4, triggers the optimization pipeline and
    persists results to simulated_holding_result table.
    """
    fund_code: str = Field(..., min_length=1, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    max_positions: int = Field(default=30, ge=5, le=50)
    max_single_weight: float = Field(default=0.10, ge=0.02, le=0.30)
    turnover_penalty: float = Field(default=0.5, ge=0.0, le=10.0)
    industry_penalty: float = Field(default=0.5, ge=0.0, le=10.0)
    window_days: int = Field(default=60, ge=20, le=250)
    rebalance_freq: str = Field(default="M", pattern="^(M|Q)$")


class ReturnAttributionRequest(BaseModel):
    """Request to run dynamic return attribution for a fund.

    Per requirements §5.2.4, triggers multi-period Brinson attribution
    with real market/benchmark returns.
    """
    fund_code: str = Field(..., min_length=1, max_length=20)
    method: str = Field(default="BHB", pattern="^(BHB|BF)$")
    benchmark_symbol: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class LockSecuritiesRequest(BaseModel):
    """Lock or exclude specific securities from simulated holdings.

    Per requirements §5.5.3, allows researchers to force-include or
    force-exclude specific securities.
    """
    fund_code: str = Field(..., min_length=1, max_length=20)
    security_code: str = Field(..., min_length=1, max_length=20)
    action: str = Field(..., pattern="^(lock|exclude)$")
    target_module: str = Field(default="simulated_holding", pattern="^(simulated_holding|scoring|dynamic_attribution)$")
    reason: str = ""
    lock_weight: float | None = Field(default=None, ge=0.0, le=1.0)


class AdjustBenchmarkRequest(BaseModel):
    """Manually adjust the benchmark for attribution analysis.

    Per requirements §5.5.3, allows overriding the default benchmark.
    """
    fund_code: str = Field(..., min_length=1, max_length=20)
    benchmark_symbol: str = Field(..., min_length=1, max_length=20)
    custom_weights: dict[str, float] | None = None
    reason: str = ""


class AnnotateConfidenceRequest(BaseModel):
    """Manually adjust confidence level for an algorithm result.

    Per requirements §5.5.3, allows up/down-grading conclusion status.
    """
    fund_code: str = Field(..., min_length=1, max_length=20)
    target_module: str = Field(..., pattern="^(simulated_holding|scoring|dynamic_attribution)$")
    original_status: str | None = None
    adjusted_status: str = Field(..., pattern="^(fact|computed|estimated|observation|needs_review)$")
    reason: str = ""


class BuildResearchPacketRequest(BaseModel):
    """Request body for generating a research packet."""
    fund_code: str = Field(..., min_length=1, max_length=20)
    template: str = Field(
        default="single_fund_checkup",
        pattern="^(single_fund_checkup|manager_profile|style_drift|holdings_deep_dive)$",
    )


class DiffResearchPacketRequest(BaseModel):
    """Request body for comparing two research packets."""
    fund_code: str | None = Field(None, max_length=20)
    left_packet_id: str | None = None
    right_packet_id: str | None = None
    left_snapshot: date | None = None
    right_snapshot: date | None = None


class FingerprintRequest(BaseModel):
    calc_date: date | None = None


class SimilarFundsRequest(BaseModel):
    metric_space: str = Field(default="composite", pattern="^(style|holding|risk_return|factor|composite)$")
    top_n: int = Field(default=10, ge=1, le=50)
    same_type_only: bool = True


class FundCompareRequest(BaseModel):
    fund_codes: list[str] = Field(..., min_length=2, max_length=6)
    dimensions: list[str] = Field(default_factory=lambda: ["all"])


class BatchFingerprintRequest(BaseModel):
    fund_codes: list[str] = Field(..., min_length=1, max_length=100)
    calc_date: date | None = None


_P2B_TASKS: dict[str, dict[str, Any]] = {}
_P2B_TASK_LOCK = threading.Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _p2b_latest_report_path() -> Path:
    return _project_root() / "docs" / "phase2" / "p2b_validation_report.json"


def _p2b_history_dir() -> Path:
    return _project_root() / "docs" / "phase2" / "p2b_validation_reports"


def _read_json_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_id(path: Path, report: dict[str, Any]) -> str:
    return str(report.get("report_id") or path.stem)


def _report_summary(path: Path, report: dict[str, Any], *, is_latest: bool = False) -> dict[str, Any]:
    algorithms = report.get("algorithms") or {}
    return {
        "report_id": _report_id(path, report),
        "generated_at": report.get("generated_at"),
        "sample_fund_count": report.get("sample_fund_count"),
        "expected_fund_count": report.get("expected_fund_count"),
        "pipeline_status": (report.get("pipeline_gate") or {}).get("status"),
        "productization_status": (report.get("productization_gate") or {}).get("status"),
        "conclusion_status": report.get("conclusion_status"),
        "algorithm_count": len(algorithms),
        "warning_count": len(report.get("warnings") or []),
        "is_latest": is_latest,
    }


def _p2b_report_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    latest_path = _p2b_latest_report_path()
    if latest_path.exists():
        latest_report = _read_json_report(latest_path)
        latest_id = _report_id(latest_path, latest_report)
        entries.append({
            "path": latest_path,
            "report": latest_report,
            "summary": _report_summary(latest_path, latest_report, is_latest=True),
        })
        seen_ids.add(latest_id)

    history_dir = _p2b_history_dir()
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.json"), reverse=True):
            report = _read_json_report(path)
            report_id = _report_id(path, report)
            if report_id in seen_ids:
                continue
            seen_ids.add(report_id)
            entries.append({
                "path": path,
                "report": report,
                "summary": _report_summary(path, report),
            })

    return sorted(
        entries,
        key=lambda item: str(item["summary"].get("generated_at") or ""),
        reverse=True,
    )


def _resolve_p2b_report(report_id: str) -> tuple[Path, dict[str, Any]]:
    if report_id == "latest":
        latest_path = _p2b_latest_report_path()
        if not latest_path.exists():
            raise FileNotFoundError(f"P2B validation report not found: {latest_path}")
        return latest_path, _read_json_report(latest_path)

    for entry in _p2b_report_entries():
        if entry["summary"]["report_id"] == report_id:
            return entry["path"], entry["report"]
    raise FileNotFoundError(f"P2B validation report not found: {report_id}")


def _numeric_delta(base_value: Any, target_value: Any) -> float | None:
    if isinstance(base_value, (int, float)) and isinstance(target_value, (int, float)):
        return float(target_value) - float(base_value)
    return None


def _compare_p2b_reports(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    gate_names = sorted({
        check.get("name")
        for report in (base, target)
        for check in (report.get("gate_checks") or [])
        if check.get("name")
    })
    base_checks = {check.get("name"): check for check in (base.get("gate_checks") or [])}
    target_checks = {check.get("name"): check for check in (target.get("gate_checks") or [])}
    gate_changes = [
        {
            "name": name,
            "base_passed": (base_checks.get(name) or {}).get("passed"),
            "target_passed": (target_checks.get(name) or {}).get("passed"),
            "base_detail": (base_checks.get(name) or {}).get("detail"),
            "target_detail": (target_checks.get(name) or {}).get("detail"),
            "changed": (base_checks.get(name) or {}).get("passed")
            != (target_checks.get(name) or {}).get("passed"),
        }
        for name in gate_names
    ]

    algorithm_names = sorted(set(base.get("algorithms") or {}) | set(target.get("algorithms") or {}))
    algorithm_changes = []
    for algorithm in algorithm_names:
        base_report = (base.get("algorithms") or {}).get(algorithm) or {}
        target_report = (target.get("algorithms") or {}).get(algorithm) or {}
        base_stats = base_report.get("aggregate_stats") or {}
        target_stats = target_report.get("aggregate_stats") or {}
        metric_keys = sorted(set(base_stats) | set(target_stats))
        metric_deltas = {
            key: {
                "base": base_stats.get(key),
                "target": target_stats.get(key),
                "delta": _numeric_delta(base_stats.get(key), target_stats.get(key)),
            }
            for key in metric_keys
            if base_stats.get(key) != target_stats.get(key)
        }
        base_readiness = ((base.get("readiness_summary") or {}).get(algorithm) or {})
        target_readiness = ((target.get("readiness_summary") or {}).get(algorithm) or {})
        base_summary = base_report.get("experiment_summary") or {}
        target_summary = target_report.get("experiment_summary") or {}
        algorithm_changes.append({
            "algorithm": algorithm,
            "base_conclusion": base_report.get("overall_conclusion"),
            "target_conclusion": target_report.get("overall_conclusion"),
            "base_readiness": base_readiness.get("level"),
            "target_readiness": target_readiness.get("level"),
            "base_success_count": base_summary.get("success_count"),
            "target_success_count": target_summary.get("success_count"),
            "base_failure_count": base_summary.get("failure_count"),
            "target_failure_count": target_summary.get("failure_count"),
            "metric_deltas": metric_deltas,
            "changed": bool(metric_deltas)
            or base_report.get("overall_conclusion") != target_report.get("overall_conclusion")
            or base_readiness.get("level") != target_readiness.get("level")
            or base_summary.get("success_count") != target_summary.get("success_count")
            or base_summary.get("failure_count") != target_summary.get("failure_count"),
        })

    return {
        "base": _report_summary(Path("base"), base),
        "target": _report_summary(Path("target"), target),
        "gate_changes": gate_changes,
        "algorithm_changes": algorithm_changes,
        "changed": any(item["changed"] for item in gate_changes)
        or any(item["changed"] for item in algorithm_changes),
    }


def _task_snapshot(task_id: str) -> dict[str, Any] | None:
    with _P2B_TASK_LOCK:
        task = _P2B_TASKS.get(task_id)
        return dict(task) if task else None


def _update_p2b_task(task_id: str, **updates: Any) -> None:
    with _P2B_TASK_LOCK:
        task = _P2B_TASKS.setdefault(task_id, {"task_id": task_id})
        task.update(updates)


def _running_p2b_task() -> dict[str, Any] | None:
    with _P2B_TASK_LOCK:
        for task in _P2B_TASKS.values():
            if task.get("status") in {"queued", "running"}:
                return dict(task)
    return None


def _run_p2b_validation_task(
    task_id: str,
    *,
    algorithms: list[str],
    limit: int | None,
) -> None:
    def progress(payload: dict[str, Any]) -> None:
        _update_p2b_task(
            task_id,
            status="running",
            stage=payload.get("stage", "running"),
            message=payload.get("message"),
            current=payload.get("current"),
            total=payload.get("total"),
            percent=payload.get("percent"),
            algorithm=payload.get("algorithm"),
        )

    try:
        settings = get_settings()
        sample_path = settings.sample_funds_path_absolute
        _update_p2b_task(
            task_id,
            status="running",
            stage="loading_sample",
            message="Loading sample funds",
            percent=2,
        )
        fund_codes = load_sample_fund_codes(sample_path, limit=limit)
        if not fund_codes:
            raise ValueError("sample fund list is empty")

        session_factory = get_session_factory()
        with session_factory() as session:
            report = run_p2b_validation_report(
                session,
                fund_codes,
                algorithms,
                expected_fund_count=30 if limit is None else min(limit, 30),
                progress_callback=progress,
            )

        _update_p2b_task(
            task_id,
            stage="writing_report",
            message="Writing validation report",
            percent=95,
        )
        history_path = write_p2b_validation_report(report, _p2b_latest_report_path())
        _update_p2b_task(
            task_id,
            status="completed",
            stage="completed",
            message="P2B validation completed",
            percent=100,
            report_id=report.get("report_id"),
            generated_at=report.get("generated_at"),
            report_path=str(_p2b_latest_report_path()),
            history_path=str(history_path) if history_path else None,
            warnings=report.get("warnings") or [],
        )
    except Exception as exc:
        _update_p2b_task(
            task_id,
            status="failed",
            stage="failed",
            message=str(exc),
            percent=100,
            warnings=[str(exc)],
        )


def _log(db: Session, tool: str, params: dict, resp: APIResponse[dict], started: float) -> APIResponse[dict]:
    status = resp.conclusion_status.value if resp.conclusion_status else "unknown"
    try:
        db.add(
            ToolAPICallLog(
                call_id=f"api_{uuid4().hex[:12]}",
                tool_name=tool,
                caller="api",
                parameters=params,
                status=status,
                response_time_ms=(perf_counter() - started) * 1000,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        resp.warnings.append(f"API 调用日志写入失败: {exc}")
    return resp


@v2_router.get("/experiments")
def list_experiments_endpoint(
    db: SessionDep,
    algorithm_name: str | None = Query(None, description="按算法名过滤"),
) -> APIResponse[dict]:
    """列出所有实验。"""
    started = perf_counter()
    try:
        experiments = list_experiments(db, algorithm_name=algorithm_name)
        data = [
            {
                "id": str(exp.id),
                "name": exp.experiment_name,
                "algorithm": exp.algorithm_name,
                "version": exp.algorithm_version,
                "status": exp.status,
                "fund_count": exp.fund_count,
                "success_count": exp.success_count,
                "failure_count": exp.failure_count,
                "created_at": exp.created_at,
            }
            for exp in experiments
        ]
        return _log(
            db,
            "list_experiments",
            {"algorithm_name": algorithm_name},
            APIResponse(
                data={"experiments": data, "total": len(data)},
                metadata={"tool": "list_experiments", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "list_experiments",
            {},
            APIResponse(
                data=None,
                metadata={"tool": "list_experiments"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# P3.3: 异常发现
# ============================================================


class AnomalyScanRequest(BaseModel):
    scope: str = Field(default="all", pattern="^(all|pool|fund_type)$")
    scope_id: str | None = None
    rules: list[str] | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@v2_router.post("/anomalies/scan", response_model=APIResponse[dict])
def anomaly_scan(
    db: SessionDep,
    request: AnomalyScanRequest,
) -> APIResponse[dict]:
    """扫描基金异常。支持按范围（全部/基金池/基金类型）和规则筛选。"""
    started = perf_counter()
    params = {"scope": request.scope, "scope_id": request.scope_id, "rules": request.rules, "params": request.params}
    try:
        # Determine fund codes based on scope
        fund_codes: list[str] = []
        if request.scope == "pool" and request.scope_id:
            pool_funds = db.scalars(
                select(DbFundPoolMember.fund_code).where(
                    DbFundPoolMember.pool_id == int(request.scope_id)
                )
            ).all()
            fund_codes = list(pool_funds)
        elif request.scope == "fund_type" and request.scope_id:
            fund_codes = list(
                db.scalars(
                    select(FundMain.fund_code).where(
                        FundMain.category == request.scope_id
                    )
                ).all()
            )
        else:
            fund_codes = list(
                db.scalars(select(FundMain.fund_code).limit(100)).all()
            )

        if not fund_codes:
            response = APIResponse(
                data={"anomalies": [], "total": 0, "fund_count": 0},
                metadata={
                    "tool": ANOMALY_NAME,
                    "algorithm_version": ANOMALY_VERSION,
                    "platform_version": __version__,
                },
                warnings=["未找到符合条件的基金"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            )
            return _log(db, "anomaly_scan", params, response, started)

        # Run anomaly scan
        items = scan_anomalies(db, fund_codes, rules=request.rules, params=request.params)

        # Persist anomalies
        for item in items:
            persist_anomaly(db, item, scope=request.scope, scope_id=request.scope_id)
        db.commit()

        anomaly_data = [item.to_data() for item in items]
        response = APIResponse(
            data={
                "anomalies": anomaly_data,
                "total": len(anomaly_data),
                "fund_count": len(fund_codes),
                "rules_run": request.rules or list(ANOMALY_RULES.keys()),
            },
            metadata={
                "tool": ANOMALY_NAME,
                "algorithm_version": ANOMALY_VERSION,
                "platform_version": __version__,
            },
            conclusion_status=ConclusionStatus.OBSERVATION,
        )
        return _log(db, "anomaly_scan", params, response, started)
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "anomaly_scan",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": ANOMALY_NAME,
                    "algorithm_version": ANOMALY_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/anomalies", response_model=APIResponse[dict])
def list_anomalies(
    db: SessionDep,
    rule_name: str | None = Query(None),
    severity: str | None = Query(None),
    fund_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> APIResponse[dict]:
    """获取异常列表，支持按规则、严重度、基金代码筛选。"""
    started = perf_counter()
    params = {"rule_name": rule_name, "severity": severity, "fund_code": fund_code, "limit": limit, "offset": offset}
    try:
        query = select(AnomalyRecord)
        if rule_name:
            query = query.where(AnomalyRecord.rule_name == rule_name)
        if severity:
            query = query.where(AnomalyRecord.severity == severity)
        if fund_code:
            query = query.where(AnomalyRecord.fund_code == fund_code)
        query = query.order_by(AnomalyRecord.detected_at.desc()).offset(offset).limit(limit)

        records = db.scalars(query).all()
        data = [
            {
                "id": r.id,
                "fund_code": r.fund_code,
                "rule_name": r.rule_name,
                "severity": r.severity,
                "description": r.description,
                "detail": r.detail,
                "conclusion_status": r.conclusion_status,
                "detected_at": str(r.detected_at) if r.detected_at else None,
            }
            for r in records
        ]
        response = APIResponse(
            data={"anomalies": data, "total": len(data)},
            metadata={"tool": ANOMALY_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.OBSERVATION,
        )
        return _log(db, "list_anomalies", params, response, started)
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "list_anomalies",
            params,
            APIResponse(
                data=None,
                metadata={"tool": ANOMALY_NAME, "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/anomalies/{anomaly_id}", response_model=APIResponse[dict])
def get_anomaly(
    db: SessionDep,
    anomaly_id: int,
) -> APIResponse[dict]:
    """获取异常详情。"""
    started = perf_counter()
    params = {"anomaly_id": anomaly_id}
    try:
        record = db.scalars(
            select(AnomalyRecord).where(AnomalyRecord.id == anomaly_id).limit(1)
        ).first()
        if record is None:
            raise HTTPException(status_code=404, detail="异常记录不存在")

        data = {
            "id": record.id,
            "fund_code": record.fund_code,
            "rule_name": record.rule_name,
            "severity": record.severity,
            "description": record.description,
            "detail": record.detail,
            "evidence_ids": record.evidence_ids or [],
            "scope": record.scope,
            "scope_id": record.scope_id,
            "conclusion_status": record.conclusion_status,
            "detected_at": str(record.detected_at) if record.detected_at else None,
        }
        response = APIResponse(
            data=data,
            metadata={"tool": ANOMALY_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus(record.conclusion_status),
        )
        return _log(db, "get_anomaly", params, response, started)
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_anomaly",
            params,
            APIResponse(
                data=None,
                metadata={"tool": ANOMALY_NAME, "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/validation/p2b/latest")
def get_latest_p2b_validation_report(db: SessionDep) -> APIResponse[dict]:
    """读取最近一次 P2B 验收报告。"""
    started = perf_counter()
    report_path = _p2b_latest_report_path()
    if not report_path.exists():
        return _log(
            db,
            "get_latest_p2b_validation_report",
            {"path": str(report_path)},
            APIResponse(
                data=None,
                metadata={"tool": "get_latest_p2b_validation_report"},
                warnings=[f"P2B 验收报告不存在: {report_path}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )

    try:
        report = _read_json_report(report_path)
        status = report.get("conclusion_status") or "needs_review"
        return _log(
            db,
            "get_latest_p2b_validation_report",
            {"path": str(report_path)},
            APIResponse(
                data=report,
                metadata={
                    "tool": "get_latest_p2b_validation_report",
                    "report_path": str(report_path),
                    "platform_version": __version__,
                },
                warnings=report.get("warnings") or [],
                conclusion_status=ConclusionStatus(status),
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_latest_p2b_validation_report",
            {"path": str(report_path)},
            APIResponse(
                data=None,
                metadata={"tool": "get_latest_p2b_validation_report"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/validation/p2b/reports")
def list_p2b_validation_reports(db: SessionDep) -> APIResponse[dict]:
    """List available P2B validation report snapshots."""
    started = perf_counter()
    try:
        reports = [entry["summary"] for entry in _p2b_report_entries()]
        return _log(
            db,
            "list_p2b_validation_reports",
            {},
            APIResponse(
                data={"reports": reports, "total": len(reports)},
                metadata={
                    "tool": "list_p2b_validation_reports",
                    "history_dir": str(_p2b_history_dir()),
                    "platform_version": __version__,
                },
                warnings=[] if reports else ["P2B validation report history is empty"],
                conclusion_status=ConclusionStatus.COMPUTED if reports else ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "list_p2b_validation_reports",
            {},
            APIResponse(
                data=None,
                metadata={"tool": "list_p2b_validation_reports"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/validation/p2b/reports/{report_id}")
def get_p2b_validation_report(report_id: str, db: SessionDep) -> APIResponse[dict]:
    """Read a specific P2B validation report snapshot."""
    started = perf_counter()
    try:
        path, report = _resolve_p2b_report(report_id)
        status = report.get("conclusion_status") or "needs_review"
        return _log(
            db,
            "get_p2b_validation_report",
            {"report_id": report_id},
            APIResponse(
                data=report,
                metadata={
                    "tool": "get_p2b_validation_report",
                    "report_path": str(path),
                    "platform_version": __version__,
                },
                warnings=report.get("warnings") or [],
                conclusion_status=ConclusionStatus(status),
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_p2b_validation_report",
            {"report_id": report_id},
            APIResponse(
                data=None,
                metadata={"tool": "get_p2b_validation_report"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/validation/p2b/compare")
def compare_p2b_validation_reports(
    db: SessionDep,
    base_report_id: str = Query(..., description="Base report id"),
    target_report_id: str = Query("latest", description="Target report id"),
) -> APIResponse[dict]:
    """Compare two P2B validation reports at gate and algorithm-summary level."""
    started = perf_counter()
    try:
        _, base_report = _resolve_p2b_report(base_report_id)
        _, target_report = _resolve_p2b_report(target_report_id)
        comparison = _compare_p2b_reports(base_report, target_report)
        return _log(
            db,
            "compare_p2b_validation_reports",
            {"base_report_id": base_report_id, "target_report_id": target_report_id},
            APIResponse(
                data=comparison,
                metadata={
                    "tool": "compare_p2b_validation_reports",
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "compare_p2b_validation_reports",
            {"base_report_id": base_report_id, "target_report_id": target_report_id},
            APIResponse(
                data=None,
                metadata={"tool": "compare_p2b_validation_reports"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/validation/p2b/rerun")
def rerun_p2b_validation_report(
    db: SessionDep,
    body: RerunP2BValidationRequest | None = None,
) -> APIResponse[dict]:
    """Start a background P2B validation rerun task."""
    started = perf_counter()
    body = body or RerunP2BValidationRequest()
    algorithms = body.algorithms or list(P2B_ALGORITHMS)
    unknown = sorted(set(algorithms) - set(P2B_ALGORITHMS))
    if unknown:
        return _log(
            db,
            "rerun_p2b_validation_report",
            body.model_dump(mode="json"),
            APIResponse(
                data=None,
                metadata={"tool": "rerun_p2b_validation_report"},
                warnings=[f"unknown P2B algorithms: {', '.join(unknown)}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )

    running = _running_p2b_task()
    if running:
        return _log(
            db,
            "rerun_p2b_validation_report",
            body.model_dump(mode="json"),
            APIResponse(
                data=running,
                metadata={"tool": "rerun_p2b_validation_report", "already_running": True},
                warnings=["P2B validation task is already running"],
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
            started,
        )

    task_id = f"p2b_task_{uuid4().hex[:12]}"
    _update_p2b_task(
        task_id,
        status="queued",
        stage="queued",
        message="P2B validation task queued",
        percent=0,
        current=0,
        total=len(algorithms),
        algorithms=algorithms,
        limit=body.limit,
    )
    thread = threading.Thread(
        target=_run_p2b_validation_task,
        kwargs={"task_id": task_id, "algorithms": algorithms, "limit": body.limit},
        daemon=True,
    )
    thread.start()
    return _log(
        db,
        "rerun_p2b_validation_report",
        body.model_dump(mode="json"),
        APIResponse(
            data=_task_snapshot(task_id),
            metadata={"tool": "rerun_p2b_validation_report", "platform_version": __version__},
            conclusion_status=ConclusionStatus.OBSERVATION,
        ),
        started,
    )


@v2_router.get("/validation/p2b/tasks/{task_id}")
def get_p2b_validation_task(task_id: str, db: SessionDep) -> APIResponse[dict]:
    """Get a background P2B validation task status."""
    started = perf_counter()
    task = _task_snapshot(task_id)
    if not task:
        return _log(
            db,
            "get_p2b_validation_task",
            {"task_id": task_id},
            APIResponse(
                data=None,
                metadata={"tool": "get_p2b_validation_task"},
                warnings=[f"P2B validation task not found: {task_id}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
    status = task.get("status")
    conclusion_status = (
        ConclusionStatus.NEEDS_REVIEW
        if status == "failed"
        else ConclusionStatus.COMPUTED
        if status == "completed"
        else ConclusionStatus.OBSERVATION
    )
    return _log(
        db,
        "get_p2b_validation_task",
        {"task_id": task_id},
        APIResponse(
            data=task,
            metadata={"tool": "get_p2b_validation_task", "platform_version": __version__},
            warnings=task.get("warnings") or [],
            conclusion_status=conclusion_status,
        ),
        started,
    )


@v2_router.post("/experiments")
def create_experiment_endpoint(
    db: SessionDep,
    body: CreateExperimentRequest | None = None,
) -> APIResponse[dict]:
    """创建实验。"""
    started = perf_counter()
    body = body or CreateExperimentRequest()
    params = body.model_dump(mode="json")
    try:
        exp = create_experiment(
            db,
            experiment_name=body.experiment_name,
            algorithm_name=body.algorithm_name,
            algorithm_version=body.algorithm_version,
            parameters=body.parameters,
            sample_fund_codes=body.sample_fund_codes,
            backtest_start=body.backtest_start,
            backtest_end=body.backtest_end,
        )
        return _log(
            db,
            "create_experiment",
            params,
            APIResponse(
                data={
                    "id": str(exp.id),
                    "status": exp.status,
                    "experiment_name": exp.experiment_name,
                },
                metadata={"tool": "create_experiment", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "create_experiment",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "create_experiment"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/experiments/dynamic-attribution/readiness")
def dynamic_attribution_readiness_endpoint(
    db: SessionDep,
    fund_code: Annotated[
        list[str] | None,
        Query(description="基金代码，可重复传入"),
    ] = None,
    benchmark_symbol: Annotated[
        str | None,
        Query(description="动态归因基准指数代码，如 sh000300"),
    ] = None,
    min_report_date: Annotated[
        date | None,
        Query(description="最早持仓报告期"),
    ] = None,
    max_report_date: Annotated[
        date | None,
        Query(description="最晚持仓报告期"),
    ] = None,
    min_return_observations: Annotated[
        int,
        Query(description="每个报告期最少基准收益观测数"),
    ] = 3,
    max_snapshot_age_days: Annotated[
        int,
        Query(description="基准行业权重快照最大允许年龄"),
    ] = 180,
    ready_only: Annotated[
        bool,
        Query(description="只返回满足运行条件的样本"),
    ] = False,
    limit: Annotated[
        int | None,
        Query(ge=0, description="最多返回多少条候选样本"),
    ] = None,
) -> APIResponse[dict]:
    """检查动态归因真实样本是否具备运行条件。"""
    started = perf_counter()
    params = {
        "fund_code": fund_code,
        "benchmark_symbol": benchmark_symbol,
        "min_report_date": str(min_report_date) if min_report_date else None,
        "max_report_date": str(max_report_date) if max_report_date else None,
        "min_return_observations": min_return_observations,
        "max_snapshot_age_days": max_snapshot_age_days,
        "ready_only": ready_only,
        "limit": limit,
    }
    try:
        rows = assess_dynamic_attribution_readiness(
            db,
            set(fund_code) if fund_code else None,
            benchmark_symbol=benchmark_symbol,
            min_report_date=min_report_date,
            max_report_date=max_report_date,
            min_return_observations=min_return_observations,
            max_snapshot_age_days=max_snapshot_age_days,
            ready_only=ready_only,
            limit=limit,
        )
        ready_count = sum(1 for row in rows if row["is_ready"])
        warnings = ["没有满足动态归因运行条件的样本"] if ready_only and ready_count == 0 else []
        return _log(
            db,
            "dynamic_attribution_readiness",
            params,
            APIResponse(
                data={
                    "rows": rows,
                    "total": len(rows),
                    "ready": ready_count,
                },
                metadata={
                    "tool": "dynamic_attribution_readiness",
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "dynamic_attribution_readiness",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "dynamic_attribution_readiness"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/experiments/dynamic-attribution/from-ready")
def create_dynamic_attribution_from_ready_endpoint(
    db: SessionDep,
    body: CreateDynamicAttributionFromReadyRequest,
) -> APIResponse[dict]:
    """Create a dynamic-attribution experiment from ready samples for one report date."""
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        rows = assess_dynamic_attribution_readiness(
            db,
            set(body.fund_codes) if body.fund_codes else None,
            benchmark_symbol=body.benchmark_symbol,
            min_report_date=body.report_date,
            max_report_date=body.report_date,
            min_return_observations=body.min_return_observations,
            max_snapshot_age_days=body.max_snapshot_age_days,
            ready_only=True,
            limit=body.limit,
        )
        fund_codes = sorted({row["fund_code"] for row in rows})
        if not fund_codes:
            return _log(
                db,
                "create_dynamic_attribution_from_ready",
                params,
                APIResponse(
                    data={
                        "experiment_id": None,
                        "sample_fund_codes": [],
                        "ready_candidates": 0,
                        "report_date": str(body.report_date),
                    },
                    metadata={"tool": "create_dynamic_attribution_from_ready"},
                    warnings=["没有满足动态归因运行条件的样本，未创建实验"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        experiment_params = {
            "report_dates": [str(body.report_date)],
            "min_return_observations": body.min_return_observations,
            "max_benchmark_weight_snapshot_age_days": body.max_snapshot_age_days,
        }
        if body.benchmark_symbol:
            experiment_params["benchmark_symbol"] = body.benchmark_symbol
        exp = create_experiment(
            db,
            experiment_name=body.experiment_name,
            algorithm_name="dynamic_attribution",
            algorithm_version=body.algorithm_version,
            parameters=experiment_params,
            sample_fund_codes=fund_codes,
        )
        return _log(
            db,
            "create_dynamic_attribution_from_ready",
            params,
            APIResponse(
                data={
                    "experiment_id": str(exp.id),
                    "experiment_name": exp.experiment_name,
                    "sample_fund_codes": fund_codes,
                    "ready_candidates": len(rows),
                    "report_date": str(body.report_date),
                    "parameters": experiment_params,
                },
                metadata={
                    "tool": "create_dynamic_attribution_from_ready",
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "create_dynamic_attribution_from_ready",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "create_dynamic_attribution_from_ready"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/analysis/scoring/backtest")
def scoring_backtest_endpoint(
    db: SessionDep,
    body: ScoringBacktestRequest,
) -> APIResponse[dict]:
    """Run a time-series IC backtest for composite scoring.

    Creates a scoring experiment spanning [backtest_start, backtest_end],
    evaluates every fund at each quarter-end, computes rank IC between
    scores and subsequent-quarter returns, and persists the result to the
    scoring_backtest table.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        if body.backtest_start >= body.backtest_end:
            return _log(
                db,
                "scoring_backtest",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "scoring_backtest"},
                    warnings=["backtest_start 必须早于 backtest_end"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        score_version = f"{body.algorithm_version}-bt-{uuid4().hex[:8]}"
        exp = create_experiment(
            db,
            experiment_name=body.experiment_name,
            algorithm_name="scoring",
            algorithm_version=body.algorithm_version,
            parameters={
                "preset": body.preset,
                "category": body.category,
                "weights": body.weights or {},
                "score_version": score_version,
                "min_funds_per_date": body.min_funds_per_date,
                "forward_months": body.forward_months,
                "min_forward_observations": body.min_forward_observations,
            },
            sample_fund_codes=body.fund_codes,
            backtest_start=body.backtest_start,
            backtest_end=body.backtest_end,
        )
        update_experiment_status(db, exp.id, "running")

        results = dispatch_run(db, exp)

        fund_count = len(results)
        success_count = sum(1 for r in results if r["is_success"])
        if fund_count == 0 or success_count == 0:
            final_status = "failed"
            conclusion = ConclusionStatus.NEEDS_REVIEW
        elif success_count < fund_count:
            final_status = "completed_with_failures"
            conclusion = ConclusionStatus.OBSERVATION
        else:
            final_status = "completed"
            conclusion = ConclusionStatus.COMPUTED

        summary = f"回测完成: 成功 {success_count}/{fund_count} 只基金"
        update_experiment_status(db, exp.id, final_status, summary)

        backtest_row = db.scalars(
            select(DbScoringBacktest)
            .where(DbScoringBacktest.score_version == score_version)
            .limit(1)
        ).first()

        return _log(
            db,
            "scoring_backtest",
            params,
            APIResponse(
                data={
                    "experiment_id": str(exp.id),
                    "status": final_status,
                    "fund_count": fund_count,
                    "success_count": success_count,
                    "failure_count": fund_count - success_count,
                    "score_version": score_version,
                    "ic_mean": backtest_row.ic_mean if backtest_row else None,
                    "ic_ir": backtest_row.ic_ir if backtest_row else None,
                    "monotonicity": backtest_row.monotonicity_check if backtest_row else None,
                    "group_results": backtest_row.group_results if backtest_row else None,
                    "detail": backtest_row.detail if backtest_row else None,
                },
                metadata={"tool": "scoring_backtest", "platform_version": __version__},
                conclusion_status=ConclusionStatus.OBSERVATION
                if conclusion == ConclusionStatus.COMPUTED
                else conclusion,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "scoring_backtest",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "scoring_backtest"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/analysis/scoring")
def scoring_endpoint(
    db: SessionDep,
    body: ScoringRequest,
) -> APIResponse[dict]:
    """Run composite scoring for a set of funds and persist results.

    Returns a unique score_version that can be used to retrieve the results
    later via GET /api/v2/analysis/scoring/{score_version}.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        run_id = f"{SCORING_VERSION}-{uuid4().hex[:8]}"
        exp = create_experiment(
            db,
            experiment_name=f"Scoring {run_id}",
            algorithm_name="scoring",
            algorithm_version=SCORING_VERSION,
            parameters={
                "preset": body.preset,
                "category": body.category,
                "weights": body.weights or {},
                "score_version": run_id,
            },
            sample_fund_codes=body.fund_codes,
        )
        update_experiment_status(db, exp.id, "running")

        results = dispatch_run(db, exp)

        fund_count = len(results)
        success_count = sum(1 for r in results if r["is_success"])
        if success_count == fund_count:
            status = "completed"
        elif success_count > 0:
            status = "completed_with_failures"
        else:
            status = "failed"
        update_experiment_status(db, exp.id, status, f"评分完成: {success_count}/{fund_count}")

        fund_scores = [
            {
                "fund_code": fs.fund_code,
                "total_score": fs.total_score,
                "sub_scores": fs.sub_scores,
                "percentile_rank": fs.percentile_rank,
                "deduction_reasons": fs.deduction_reasons,
                "contains_estimated": fs.contains_estimated,
                "conclusion_status": fs.conclusion_status,
                "warnings": fs.warnings or [],
            }
            for fs in db.scalars(
                select(DbScoringResult).where(DbScoringResult.score_version == run_id)
            ).all()
        ]
        contains_estimated = any(item["contains_estimated"] for item in fund_scores)
        warnings = []
        if contains_estimated:
            warnings.append("评分包含 estimated 维度，仅作为实验/观察结果")
        if success_count == 0:
            warnings.append("没有生成有效评分结果")
        conclusion_status = (
            ConclusionStatus.NEEDS_REVIEW
            if success_count == 0
            else ConclusionStatus.OBSERVATION
            if contains_estimated or success_count < fund_count
            else ConclusionStatus.COMPUTED
        )

        return _log(
            db,
            "scoring",
            params,
            APIResponse(
                data={
                    "score_version": run_id,
                    "fund_count": fund_count,
                    "success_count": success_count,
                    "fund_scores": fund_scores,
                    "experiment_id": str(exp.id),
                },
                metadata={"tool": "scoring", "platform_version": __version__},
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "scoring",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "scoring"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/analysis/scoring/backtest")
def list_scoring_backtests_endpoint(
    db: SessionDep,
) -> APIResponse[dict]:
    """List all scoring backtest runs."""
    started = perf_counter()
    try:
        rows = db.scalars(
            select(DbScoringBacktest).order_by(DbScoringBacktest.created_at.desc())
        ).all()

        items = [
            {
                "id": row.id,
                "score_version": row.score_version,
                "backtest_date": str(row.backtest_date) if row.backtest_date else None,
                "group_count": row.group_count,
                "ic_mean": row.ic_mean,
                "ic_ir": row.ic_ir,
                "monotonicity_check": row.monotonicity_check,
                "created_at": str(row.created_at) if row.created_at else None,
            }
            for row in rows
        ]

        return _log(
            db,
            "list_scoring_backtests",
            {},
            APIResponse(
                data={"backtests": items, "total": len(items)},
                metadata={"tool": "list_scoring_backtests", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "list_scoring_backtests",
            {},
            APIResponse(
                data=None,
                metadata={"tool": "list_scoring_backtests"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/analysis/scoring/backtest/{backtest_id}")
def get_scoring_backtest_endpoint(
    backtest_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """Retrieve a specific scoring backtest result by ID."""
    started = perf_counter()
    try:
        row = db.scalar(
            select(DbScoringBacktest).where(DbScoringBacktest.id == backtest_id)
        )
        if row is None:
            return _log(
                db,
                "get_scoring_backtest",
                {"backtest_id": backtest_id},
                APIResponse(
                    data=None,
                    metadata={"tool": "get_scoring_backtest"},
                    warnings=[f"未找到评分回测: {backtest_id}"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        return _log(
            db,
            "get_scoring_backtest",
            {"backtest_id": backtest_id},
            APIResponse(
                data={
                    "id": row.id,
                    "score_version": row.score_version,
                    "backtest_date": str(row.backtest_date) if row.backtest_date else None,
                    "group_count": row.group_count,
                    "group_results": row.group_results,
                    "monotonicity_check": row.monotonicity_check,
                    "ic_mean": row.ic_mean,
                    "ic_ir": row.ic_ir,
                    "detail": row.detail,
                    "created_at": str(row.created_at) if row.created_at else None,
                },
                metadata={"tool": "get_scoring_backtest", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_scoring_backtest",
            {"backtest_id": backtest_id},
            APIResponse(
                data=None,
                metadata={"tool": "get_scoring_backtest"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/analysis/scoring/{score_version}")
def get_scoring_endpoint(
    score_version: str,
    db: SessionDep,
) -> APIResponse[dict]:
    """Retrieve scoring results for a specific score_version."""
    started = perf_counter()
    try:
        rows = db.scalars(
            select(DbScoringResult).where(DbScoringResult.score_version == score_version)
        ).all()

        if not rows:
            return _log(
                db,
                "get_scoring",
                {"score_version": score_version},
                APIResponse(
                    data=None,
                    metadata={"tool": "get_scoring"},
                    warnings=[f"未找到评分版本: {score_version}"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        fund_scores = [
            {
                "fund_code": row.fund_code,
                "total_score": row.total_score,
                "sub_scores": row.sub_scores,
                "percentile_rank": row.percentile_rank,
                "deduction_reasons": row.deduction_reasons,
                "contains_estimated": row.contains_estimated,
                "conclusion_status": row.conclusion_status,
                "warnings": row.warnings or [],
                "calc_date": str(row.calc_date) if row.calc_date else None,
            }
            for row in rows
        ]
        fund_scores.sort(key=lambda x: x["total_score"] or 0, reverse=True)
        contains_estimated = any(item["contains_estimated"] for item in fund_scores)
        warnings = ["评分包含 estimated 维度，仅作为实验/观察结果"] if contains_estimated else []

        return _log(
            db,
            "get_scoring",
            {"score_version": score_version},
            APIResponse(
                data={
                    "score_version": score_version,
                    "fund_count": len(rows),
                    "fund_scores": fund_scores,
                },
                metadata={"tool": "get_scoring", "platform_version": __version__},
                warnings=warnings,
                conclusion_status=ConclusionStatus.OBSERVATION
                if contains_estimated
                else ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_scoring",
            {"score_version": score_version},
            APIResponse(
                data=None,
                metadata={"tool": "get_scoring"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/experiments/{experiment_id}")
def get_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """获取实验详情和结果。"""
    started = perf_counter()
    exp = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if not exp:
        return _log(
            db,
            "get_experiment",
            {"experiment_id": experiment_id},
            APIResponse(
                data=None,
                metadata={"tool": "get_experiment"},
                warnings=[f"实验 {experiment_id} 不存在"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )

    results = get_experiment_results(db, experiment_id)
    return _log(
        db,
        "get_experiment",
        {"experiment_id": experiment_id},
        APIResponse(
            data={
                "id": str(exp.id),
                "experiment_name": exp.experiment_name,
                "algorithm_name": exp.algorithm_name,
                "algorithm_version": exp.algorithm_version,
                "parameters": exp.parameters,
                "status": exp.status,
                "backtest_start": str(exp.backtest_start) if exp.backtest_start else None,
                "backtest_end": str(exp.backtest_end) if exp.backtest_end else None,
                "summary": exp.summary,
                "results": [
                    {
                        "fund_code": result.fund_code,
                        "calc_date": str(result.calc_date) if result.calc_date else None,
                        "is_success": result.is_success,
                        "metrics": result.metrics,
                        "error_message": result.error_message,
                        "warnings": result.warnings,
                    }
                    for result in results
                ],
            },
            metadata={
                "tool": "get_experiment",
                "experiment_id": experiment_id,
                "platform_version": __version__,
            },
            conclusion_status=ConclusionStatus.COMPUTED,
        ),
        started,
    )


@v2_router.post("/experiments/{experiment_id}/rerun")
def rerun_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """重跑实验。"""
    started = perf_counter()
    try:
        exp = rerun_experiment(db, experiment_id)
        return _log(
            db,
            "rerun_experiment",
            {"experiment_id": str(experiment_id)},
            APIResponse(
                data={"id": str(exp.id), "status": exp.status},
                metadata={"tool": "rerun_experiment", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except ValueError as exc:
        db.rollback()
        return _log(
            db,
            "rerun_experiment",
            {"experiment_id": experiment_id},
            APIResponse(
                data=None,
                metadata={"tool": "rerun_experiment"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.delete("/experiments/{experiment_id}")
def delete_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """删除实验。"""
    started = perf_counter()
    try:
        delete_experiment(db, experiment_id)
        return _log(
            db,
            "delete_experiment",
            {"experiment_id": str(experiment_id)},
            APIResponse(
                data={"id": str(experiment_id), "deleted": True},
                metadata={"tool": "delete_experiment", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "delete_experiment",
            {"experiment_id": experiment_id},
            APIResponse(
                data=None,
                metadata={"tool": "delete_experiment"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/experiments/{experiment_id}/results")
def record_experiment_result_endpoint(
    experiment_id: int,
    db: SessionDep,
    body: RecordExperimentResultRequest,
) -> APIResponse[dict]:
    """记录单个实验结果。"""
    started = perf_counter()
    params = {"experiment_id": experiment_id, **body.model_dump(mode="json")}
    try:
        exp = db.get(AlgorithmExperiment, experiment_id)
        if exp is None:
            return _log(
                db,
                "record_experiment_result",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "record_experiment_result"},
                    warnings=[f"实验 {experiment_id} 不存在"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )
        result = record_result(
            db,
            experiment_id=experiment_id,
            fund_code=body.fund_code,
            calc_date=body.calc_date,
            is_success=body.is_success,
            metrics=body.metrics,
            error_message=body.error_message,
            warnings=body.warnings,
        )
        return _log(
            db,
            "record_experiment_result",
            params,
            APIResponse(
                data={
                    "id": str(result.id),
                    "fund_code": result.fund_code,
                    "is_success": result.is_success,
                },
                metadata={"tool": "record_experiment_result", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "record_experiment_result",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "record_experiment_result"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/experiments/{experiment_id}/run")
def run_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """执行实验：读取参数，运行对应算法，写入结果。"""
    started = perf_counter()
    params = {"experiment_id": experiment_id}

    exp = db.get(AlgorithmExperiment, experiment_id)
    if exp is None:
        return _log(
            db,
            "run_experiment",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "run_experiment"},
                warnings=[f"实验 {experiment_id} 不存在"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )

    if exp.status == "running":
        return _log(
            db,
            "run_experiment",
            params,
            APIResponse(
                data={"experiment_id": experiment_id, "status": "running"},
                metadata={"tool": "run_experiment"},
                warnings=["实验正在运行中"],
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
            started,
        )

    update_experiment_status(db, experiment_id, "running")

    try:
        results = dispatch_run(db, exp)
        fund_count = len(results)
        success_count = sum(1 for result in results if result["is_success"])
        failure_count = fund_count - success_count
        if fund_count == 0 or success_count == 0:
            final_status = "failed"
            conclusion_status = ConclusionStatus.NEEDS_REVIEW
            summary = f"失败 {failure_count}/{fund_count} 只基金"
        elif failure_count > 0:
            final_status = "completed_with_failures"
            conclusion_status = ConclusionStatus.OBSERVATION
            summary = f"部分完成: 成功 {success_count}/{fund_count} 只基金"
        else:
            final_status = "completed"
            conclusion_status = ConclusionStatus.COMPUTED
            summary = f"完成 {fund_count} 只基金"
        update_experiment_status(db, experiment_id, final_status, summary)
        return _log(
            db,
            "run_experiment",
            params,
            APIResponse(
                data={
                    "experiment_id": str(experiment_id),
                    "status": final_status,
                    "fund_count": fund_count,
                    "success_count": success_count,
                    "failure_count": failure_count,
                },
                metadata={"tool": "run_experiment", "platform_version": __version__},
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        update_experiment_status(db, experiment_id, "failed", str(exc)[:200])
        return _log(
            db,
            "run_experiment",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "run_experiment"},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# Simulated Holding — query persisted results
# ============================================================


def _simulated_holding_to_dict(row: DbSimulatedHoldingResult) -> dict:
    return {
        "id": row.id,
        "fund_code": row.fund_code,
        "calc_date": row.calc_date.isoformat() if row.calc_date else None,
        "algorithm_name": row.algorithm_name,
        "algorithm_version": row.algorithm_version,
        "parameters": row.parameters,
        "holdings_detail": row.holdings_detail,
        "tracking_error": row.tracking_error,
        "daily_rmse": row.daily_rmse,
        "industry_correlation": row.industry_correlation,
        "top10_recall": row.top10_recall,
        "stock_weight_pct": row.stock_weight_pct,
        "bond_weight_pct": row.bond_weight_pct,
        "cash_weight_pct": row.cash_weight_pct,
        "confidence": row.confidence,
        "conclusion_status": row.conclusion_status,
        "is_backtest": row.is_backtest,
        "backtest_report_date": (
            row.backtest_report_date.isoformat()
            if row.backtest_report_date
            else None
        ),
        "warnings": row.warnings,
        "input_coverage": row.input_coverage,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@v2_router.get("/analysis/simulated-holding")
def list_simulated_holding(
    db: SessionDep,
    fund_code: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(10, ge=1, le=50),
) -> APIResponse[dict]:
    """List the most recent simulated holding results for a fund.

    Results are always ``conclusion_status=estimated`` — they are model
    outputs, not disclosed facts. The frontend must display the estimated
    label prominently.
    """
    started = perf_counter()
    params = {"fund_code": fund_code, "limit": limit}
    try:
        rows = db.scalars(
            select(DbSimulatedHoldingResult)
            .where(DbSimulatedHoldingResult.fund_code == fund_code)
            .order_by(DbSimulatedHoldingResult.calc_date.desc())
            .limit(limit)
        ).all()

        return _log(
            db,
            "simulated_holding",
            params,
            APIResponse(
                data={
                    "fund_code": fund_code,
                    "results": [_simulated_holding_to_dict(r) for r in rows],
                    "count": len(rows),
                },
                metadata={"tool": "simulated_holding", "platform_version": __version__},
                conclusion_status=ConclusionStatus.ESTIMATED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "simulated_holding",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "simulated_holding"},
                warnings=[f"查询模拟持仓失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# Analysis endpoints — trigger algorithm runs
# ============================================================


@v2_router.post("/analysis/simulated-holding")
def run_simulated_holding_endpoint(
    db: SessionDep,
    body: SimulatedHoldingRequest,
) -> APIResponse[dict]:
    """Run simulated holding estimation for a single fund.

    Creates an experiment, dispatches the optimization runner, and
    persists results to simulated_holding_result. Per requirements §5.1.4.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        from fund_research.analysis.simulated_holding import ALGORITHM_VERSION as SH_VERSION

        run_id = f"{SH_VERSION}-{uuid4().hex[:8]}"
        exp = create_experiment(
            db,
            experiment_name=f"SimHolding {body.fund_code} {run_id}",
            algorithm_name="simulated_holding",
            algorithm_version=SH_VERSION,
            parameters={
                "method": "optimized",
                "max_positions": body.max_positions,
                "max_single_weight": body.max_single_weight,
                "turnover_penalty": body.turnover_penalty,
                "industry_penalty": body.industry_penalty,
                "window_days": body.window_days,
                "rebalance_freq": body.rebalance_freq,
                "start_date": str(body.start_date) if body.start_date else None,
                "end_date": str(body.end_date) if body.end_date else None,
            },
            sample_fund_codes=[body.fund_code],
        )
        update_experiment_status(db, exp.id, "running")
        results = dispatch_run(db, exp)
        success_count = sum(1 for r in results if r["is_success"])
        status = "completed" if success_count > 0 else "failed"
        update_experiment_status(db, exp.id, status)

        # Fetch persisted result
        row = db.scalars(
            select(DbSimulatedHoldingResult)
            .where(DbSimulatedHoldingResult.fund_code == body.fund_code)
            .order_by(DbSimulatedHoldingResult.created_at.desc())
        ).first()

        return _log(
            db, "run_simulated_holding", params,
            APIResponse(
                data={
                    "experiment_id": str(exp.id),
                    "fund_code": body.fund_code,
                    "success": success_count > 0,
                    "result": _simulated_holding_to_dict(row) if row else None,
                },
                metadata={"tool": "simulated_holding", "platform_version": __version__},
                conclusion_status=ConclusionStatus.ESTIMATED if success_count > 0 else ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db, "run_simulated_holding", params,
            APIResponse(
                data=None, metadata={"tool": "simulated_holding"},
                warnings=[str(exc)], conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/analysis/return-attribution")
def run_return_attribution_endpoint(
    db: SessionDep,
    body: ReturnAttributionRequest,
) -> APIResponse[dict]:
    """Run dynamic return attribution for a single fund.

    Creates an experiment, dispatches the dynamic attribution runner
    using real market/benchmark returns. Per requirements §5.2.4.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        from fund_research.analysis.dynamic_attribution import ALGORITHM_VERSION as DA_VERSION

        run_id = f"{DA_VERSION}-{uuid4().hex[:8]}"
        exp = create_experiment(
            db,
            experiment_name=f" DynAttr {body.fund_code} {run_id}",
            algorithm_name="dynamic_attribution",
            algorithm_version=DA_VERSION,
            parameters={
                "method": body.method,
                "benchmark_symbol": body.benchmark_symbol,
                "start_date": str(body.start_date) if body.start_date else None,
                "end_date": str(body.end_date) if body.end_date else None,
            },
            sample_fund_codes=[body.fund_code],
        )
        update_experiment_status(db, exp.id, "running")
        results = dispatch_run(db, exp)
        success_count = sum(1 for r in results if r["is_success"])
        status = "completed" if success_count > 0 else "failed"
        update_experiment_status(db, exp.id, status)

        # Fetch the latest TOTAL-level result (is_total=True) for the summary
        from fund_research.db.models import DynamicAttributionResult as DbDynAttr

        row = db.scalars(
            select(DbDynAttr)
            .where(DbDynAttr.fund_code == body.fund_code)
            .where(DbDynAttr.is_total == True)  # noqa: E712
            .order_by(DbDynAttr.created_at.desc())
        ).first()

        # Fallback: if no total row exists (old data), get latest row
        if row is None:
            row = db.scalars(
                select(DbDynAttr)
                .where(DbDynAttr.fund_code == body.fund_code)
                .order_by(DbDynAttr.created_at.desc())
            ).first()

        result_dict = None
        if row:
            result_dict = {
                "id": row.id,
                "fund_code": row.fund_code,
                "calc_date": str(row.calc_date) if row.calc_date else None,
                "period_start": str(row.period_start) if row.period_start else None,
                "period_end": str(row.period_end) if row.period_end else None,
                "algorithm_name": row.algorithm_name,
                "algorithm_version": row.algorithm_version,
                "benchmark_symbol": row.benchmark_symbol,
                "uses_simulated_holdings": row.uses_simulated_holdings,
                "estimated_total_portfolio_return": row.total_return,
                "estimated_total_benchmark_return": row.benchmark_return,
                "estimated_total_allocation_effect": row.allocation_return,
                "estimated_total_selection_effect": row.selection_return,
                "estimated_total_interaction_effect": row.interaction_return,
                "estimated_total_residual": row.residual,
                "estimated_residual_ratio": row.residual_pct,
                "estimated_ipo_return": row.ipo_return,
                "estimated_convertible_bond_return": row.convertible_bond_return,
                "estimated_invisible_return": row.invisible_return,
                "confidence": row.confidence,
                "conclusion_status": row.conclusion_status,
                "warnings": row.warnings,
                "detail": row.detail,
                "waterfall_data": (row.detail or {}).get("waterfall_data", []),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }

        conclusion = ConclusionStatus.ESTIMATED if success_count > 0 else ConclusionStatus.NEEDS_REVIEW
        return _log(
            db, "run_return_attribution", params,
            APIResponse(
                data={
                    "experiment_id": str(exp.id),
                    "fund_code": body.fund_code,
                    "success": success_count > 0,
                    "result": result_dict,
                },
                metadata={"tool": "return_attribution", "platform_version": __version__},
                conclusion_status=conclusion,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db, "run_return_attribution", params,
            APIResponse(
                data=None, metadata={"tool": "return_attribution"},
                warnings=[str(exc)], conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/analysis/return-attribution")
def list_return_attribution(
    db: SessionDep,
    fund_code: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(10, ge=1, le=50),
) -> APIResponse[dict]:
    """List the most recent dynamic attribution results for a fund."""
    started = perf_counter()
    params = {"fund_code": fund_code, "limit": limit}
    try:
        from fund_research.db.models import DynamicAttributionResult as DbDynAttr

        rows = db.scalars(
            select(DbDynAttr)
            .where(DbDynAttr.fund_code == fund_code)
            .where(DbDynAttr.is_total == True)  # noqa: E712
            .order_by(DbDynAttr.created_at.desc())
            .limit(limit)
        ).all()

        items = []
        for row in rows:
            est = bool(row.uses_simulated_holdings)
            prefix = "estimated_" if est else ""
            # Residual / IPO / CB / invisible returns always carry estimated_ prefix.
            items.append({
                "id": row.id,
                "fund_code": row.fund_code,
                "calc_date": str(row.calc_date) if row.calc_date else None,
                "period_start": str(row.period_start) if row.period_start else None,
                "period_end": str(row.period_end) if row.period_end else None,
                "benchmark_symbol": row.benchmark_symbol,
                "uses_simulated_holdings": est,
                "algorithm_name": row.detail.get("algorithm_name") if row.detail else None,
                "algorithm_version": row.detail.get("algorithm_version") if row.detail else None,
                f"{prefix}total_portfolio_return": row.total_return,
                f"{prefix}total_benchmark_return": row.benchmark_return,
                f"{prefix}total_allocation_effect": row.allocation_return,
                f"{prefix}total_selection_effect": row.selection_return,
                f"{prefix}total_interaction_effect": row.interaction_return,
                "estimated_total_residual": row.residual,
                "estimated_residual_ratio": row.residual_pct,
                "estimated_ipo_return": (row.detail or {}).get("ipo_return"),
                "estimated_convertible_bond_return": (row.detail or {}).get("convertible_bond_return"),
                "estimated_invisible_return": (row.detail or {}).get("invisible_return"),
                "waterfall_data": (row.detail or {}).get("waterfall_data", []),
                "confidence": row.confidence,
                "conclusion_status": row.conclusion_status,
                "warnings": row.warnings,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })

        return _log(
            db, "list_return_attribution", params,
            APIResponse(
                data={"fund_code": fund_code, "results": items, "count": len(items)},
                metadata={"tool": "return_attribution", "platform_version": __version__},
                conclusion_status=ConclusionStatus.ESTIMATED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db, "list_return_attribution", params,
            APIResponse(
                data=None, metadata={"tool": "return_attribution"},
                warnings=[f"查询动态归因失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# Review — specialized endpoints per requirements §5.5.3
# ============================================================


@v2_router.post("/review/lock-securities")
def lock_securities_endpoint(
    db: SessionDep,
    body: LockSecuritiesRequest,
) -> APIResponse[dict]:
    """Lock or exclude a specific security from simulated holdings.

    Per requirements §5.5.3: allows researchers to force-include (lock)
    or force-exclude (exclude) specific securities. Recorded as a
    reviewer annotation with security_code in the detail dict.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        annotation_type = "lock" if body.action == "lock" else "exclude"
        detail = {
            "security_code": body.security_code,
            "lock_weight": body.lock_weight,
            "action": body.action,
        }
        req = CreateReviewerAnnotationRequest(
            fund_code=body.fund_code,
            annotation_type=annotation_type,
            target_module=body.target_module,
            detail=detail,
            reason=body.reason or f"{body.action} security {body.security_code}",
        )
        return create_annotation(db, req)
    except Exception as exc:
        db.rollback()
        return _log(
            db, "lock_securities", params,
            APIResponse(
                data=None, metadata={"tool": "lock_securities"},
                warnings=[str(exc)], conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/review/adjust-benchmark")
def adjust_benchmark_endpoint(
    db: SessionDep,
    body: AdjustBenchmarkRequest,
) -> APIResponse[dict]:
    """Manually adjust the benchmark for attribution analysis.

    Per requirements §5.5.3: allows overriding the default benchmark
    symbol and providing custom sector weights.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        detail = {
            "benchmark_symbol": body.benchmark_symbol,
            "custom_weights": body.custom_weights,
            "action": "adjust_benchmark",
        }
        req = CreateReviewerAnnotationRequest(
            fund_code=body.fund_code,
            annotation_type="lock",
            target_module="dynamic_attribution",
            detail=detail,
            reason=body.reason or f"Adjust benchmark to {body.benchmark_symbol}",
        )
        return create_annotation(db, req)
    except Exception as exc:
        db.rollback()
        return _log(
            db, "adjust_benchmark", params,
            APIResponse(
                data=None, metadata={"tool": "adjust_benchmark"},
                warnings=[str(exc)], conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/review/annotate-confidence")
def annotate_confidence_endpoint(
    db: SessionDep,
    body: AnnotateConfidenceRequest,
) -> APIResponse[dict]:
    """Manually adjust confidence level for an algorithm result.

    Per requirements §5.5.3: allows up/down-grading the conclusion
    status of a specific algorithm result for a fund.
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        detail = {
            "action": "annotate_confidence",
            "original_status": body.original_status,
            "adjusted_status": body.adjusted_status,
        }
        req = CreateReviewerAnnotationRequest(
            fund_code=body.fund_code,
            annotation_type="note",
            target_module=body.target_module,
            detail=detail,
            reason=body.reason or f"Adjust confidence to {body.adjusted_status}",
        )
        return create_annotation(db, req)
    except Exception as exc:
        db.rollback()
        return _log(
            db, "annotate_confidence", params,
            APIResponse(
                data=None, metadata={"tool": "annotate_confidence"},
                warnings=[str(exc)], conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/review/history/{fund_code}")
def review_history_endpoint(
    db: SessionDep,
    fund_code: str,
) -> APIResponse[dict]:
    """Get review/annotation history for a fund.

    Per requirements §5.5.3: returns all reviewer annotations for a fund
    across all modules, ordered by creation time.
    """
    started = perf_counter()
    params = {"fund_code": fund_code}
    try:
        rows = db.scalars(
            select(DbReviewerAnnotation)
            .where(DbReviewerAnnotation.fund_code == fund_code)
            .order_by(DbReviewerAnnotation.created_at.desc())
        ).all()
        from fund_research.review.service import annotation_to_dict

        return _log(
            db, "review_history", params,
            APIResponse(
                data={
                    "fund_code": fund_code,
                    "annotations": [annotation_to_dict(r) for r in rows],
                    "count": len(rows),
                },
                metadata={"tool": "review_history", "platform_version": __version__},
                conclusion_status=ConclusionStatus.FACT,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db, "review_history", params,
            APIResponse(
                data=None, metadata={"tool": "review_history"},
                warnings=[str(exc)], conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# Reviewer Annotation — delegates to fund_research.review module
# ============================================================

from fund_research.review import (  # noqa: E402
    CreateReviewerAnnotationRequest,
    UpdateReviewerAnnotationRequest,
    create_annotation,
    delete_annotation,
    get_annotation,
    list_annotations,
    update_annotation,
)
from fund_research.review import (  # noqa: E402
    get_fund_review_status as _get_fund_review_status,
)


@v2_router.post("/reviewer-annotations")
def create_reviewer_annotation(
    db: SessionDep,
    body: CreateReviewerAnnotationRequest,
) -> APIResponse[dict]:
    """Create a reviewer annotation (note / lock / exclude / approve).

    Delegates to ``review.service.create_annotation()`` which handles
    validation, Evidence-record creation (reviewer_note type), and
    evidence_ids linkage (fixes EV-2 code duplication).
    """
    return create_annotation(db, body)


@v2_router.get("/reviewer-annotations")
def list_reviewer_annotations(
    db: SessionDep,
    fund_code: str | None = Query(None),
    annotation_type: str | None = Query(None),
    target_module: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> APIResponse[dict]:
    """List reviewer annotations with optional filters."""
    return list_annotations(db, fund_code, annotation_type, target_module, limit)


@v2_router.get("/reviewer-annotations/{annotation_id}")
def get_reviewer_annotation(
    db: SessionDep,
    annotation_id: int,
) -> APIResponse[dict]:
    """Get a single reviewer annotation by id."""
    return get_annotation(db, annotation_id)


@v2_router.patch("/reviewer-annotations/{annotation_id}")
def update_reviewer_annotation(
    db: SessionDep,
    annotation_id: int,
    body: UpdateReviewerAnnotationRequest,
) -> APIResponse[dict]:
    """Update an existing reviewer annotation."""
    return update_annotation(db, annotation_id, body)


@v2_router.delete("/reviewer-annotations/{annotation_id}")
def delete_reviewer_annotation(
    db: SessionDep,
    annotation_id: int,
) -> APIResponse[dict]:
    """Delete a reviewer annotation."""
    return delete_annotation(db, annotation_id)


@v2_router.get("/reviewer-annotations/funds/{fund_code}/status")
def get_fund_review_status(
    db: SessionDep,
    fund_code: str,
) -> APIResponse[dict]:
    """Get the effective review status for a fund across all modules.

    Returns the list of annotations and derived flags:
    - ``is_locked``: any ``lock`` annotation exists
    - ``is_excluded``: any ``exclude`` annotation exists
    - ``is_approved``: any ``approve`` annotation exists
    - ``effective_status``: ``excluded`` > ``locked`` > ``approved`` > ``open``
    """
    return _get_fund_review_status(db, fund_code)


# ============================================================
# Research Packet endpoints (Phase 1 P1-05/06)
# ============================================================


@v2_router.post("/research/packet")
def build_research_packet_endpoint(
    db: SessionDep,
    body: BuildResearchPacketRequest,
) -> APIResponse[dict]:
    """生成标准化研究包（Phase 2 v2 版本，含 Phase2 评分/模拟/归因结果）。"""
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        packet = build_single_fund_packet(db, fund_code=body.fund_code, template=body.template)
        record = persist_research_packet(db, packet)
        warnings = packet.warnings.copy()
        if packet.metadata.overall_confidence.value == "needs_review":
            warnings.append("研究包存在待复核模块，不能作为高置信度结论")

        # 标记 estimated 模块的警告
        estimated_modules = [
            name for name, status in packet.conclusion_map.items()
            if status == ConclusionStatus.ESTIMATED
        ]
        if estimated_modules:
            warnings.append(
                f"以下模块为 estimated（模型估算），不可作为确定性结论: {', '.join(estimated_modules)}"
            )

        conclusion_status = (
            ConclusionStatus.NEEDS_REVIEW
            if packet.metadata.overall_confidence.value == "needs_review"
            else ConclusionStatus.ESTIMATED
            if estimated_modules
            else ConclusionStatus.COMPUTED
        )

        return _log(
            db,
            "build_research_packet",
            params,
            APIResponse(
                data={
                    "packet_id": record.packet_id,
                    "packet": packet.model_dump(mode="json"),
                    "markdown": record.markdown_text,
                },
                metadata={
                    "tool": "build_research_packet",
                    "fund_code": body.fund_code,
                    "template": body.template,
                    "platform_version": __version__,
                    "packet_id": record.packet_id,
                },
                evidence=packet.evidence,
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "build_research_packet",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "build_research_packet", "fund_code": body.fund_code},
                warnings=[f"生成研究包失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/research/diff")
def diff_research_packets_endpoint(
    db: SessionDep,
    body: DiffResearchPacketRequest,
) -> APIResponse[dict]:
    """对比同一基金两个日期/两个 packet_id 的 Research Packet。"""
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        fund_code = body.fund_code or ""
        warnings: list[str] = []

        # 获取两个 packet
        left = None
        right = None
        if body.left_packet_id:
            left = db.scalar(
                select(ResearchPacketRecord).where(
                    ResearchPacketRecord.packet_id == body.left_packet_id
                )
            )
        elif body.left_snapshot:
            left = db.scalar(
                select(ResearchPacketRecord).where(
                    ResearchPacketRecord.fund_code == fund_code,
                    ResearchPacketRecord.data_date <= body.left_snapshot,
                ).order_by(ResearchPacketRecord.data_date.desc()).limit(1)
            )
        if body.right_packet_id:
            right = db.scalar(
                select(ResearchPacketRecord).where(
                    ResearchPacketRecord.packet_id == body.right_packet_id
                )
            )
        elif body.right_snapshot:
            right = db.scalar(
                select(ResearchPacketRecord).where(
                    ResearchPacketRecord.fund_code == fund_code,
                    ResearchPacketRecord.data_date <= body.right_snapshot,
                ).order_by(ResearchPacketRecord.data_date.desc()).limit(1)
            )

        if not left or not right:
            missing = []
            if not left:
                missing.append("left")
            if not right:
                missing.append("right")
            return _log(
                db,
                "diff_research_packets",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "diff_research_packets", "fund_code": fund_code},
                    warnings=[f"缺少研究包: {', '.join(missing)}"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        lp = left.packet_json if isinstance(left.packet_json, dict) else {}
        rp = right.packet_json if isinstance(right.packet_json, dict) else {}
        if not fund_code:
            fund_code = left.fund_code
        if left.fund_code != right.fund_code:
            return _log(
                db,
                "diff_research_packets",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "diff_research_packets", "fund_code": fund_code},
                    warnings=["左右研究包不属于同一基金，不能进行同基金 diff"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        diffs: dict[str, Any] = {}

        # 规模变化
        ls = (lp.get("fund_profile") or {}).get("latest_scale") if isinstance(lp.get("fund_profile"), dict) else None
        rs = (rp.get("fund_profile") or {}).get("latest_scale") if isinstance(rp.get("fund_profile"), dict) else None
        if ls and rs and ls != rs:
            diffs["scale"] = {"left": ls, "right": rs, "delta": round(float(rs) - float(ls), 2) if ls and rs else None}

        # 经理变化
        _lm_dict = lp.get("manager_info") if isinstance(lp.get("manager_info"), dict) else {}
        _rm_dict = rp.get("manager_info") if isinstance(rp.get("manager_info"), dict) else {}
        lm = (_lm_dict or {}).get("current_managers", [])
        rm = (_rm_dict or {}).get("current_managers", [])
        if lm != rm:
            diffs["manager"] = {"left": lm, "right": rm, "changed": True}

        # 净值指标变化
        lp_metrics = (lp.get("nav_metrics") or {}).get("metrics", {}) if isinstance(lp.get("nav_metrics"), dict) else {}
        rp_metrics = (rp.get("nav_metrics") or {}).get("metrics", {}) if isinstance(rp.get("nav_metrics"), dict) else {}
        metric_diffs = {}
        for key in set(lp_metrics) | set(rp_metrics):
            lv = lp_metrics.get(key)
            rv = rp_metrics.get(key)
            if (
                lv is not None and rv is not None
                and isinstance(lv, (int, float)) and isinstance(rv, (int, float))
                and abs(float(lv) - float(rv)) > 0.0001
            ):
                metric_diffs[key] = {"left": float(lv), "right": float(rv), "delta": round(float(rv) - float(lv), 4)}
        if metric_diffs:
            diffs["nav_metrics"] = metric_diffs

        # 风格暴露变化
        _le_dict = lp.get("exposure") if isinstance(lp.get("exposure"), dict) else {}
        _re_dict = rp.get("exposure") if isinstance(rp.get("exposure"), dict) else {}
        lp_exposure = (_le_dict or {}).get("exposure_values", {})
        rp_exposure = (_re_dict or {}).get("exposure_values", {})
        exposure_diffs = {}
        for key in set(lp_exposure) | set(rp_exposure):
            lv = lp_exposure.get(key)
            rv = rp_exposure.get(key)
            if (
                lv is not None and rv is not None
                and isinstance(lv, (int, float)) and isinstance(rv, (int, float))
                and abs(float(lv) - float(rv)) > 0.0001
            ):
                exposure_diffs[key] = {"left": float(lv), "right": float(rv), "delta": round(float(rv) - float(lv), 4)}
        if exposure_diffs:
            diffs["exposure"] = exposure_diffs

        # 评分变化 (Phase 2)
        lp_scoring = lp.get("scoring") if isinstance(lp.get("scoring"), dict) else None
        rp_scoring = rp.get("scoring") if isinstance(rp.get("scoring"), dict) else None
        if lp_scoring or rp_scoring:
            scoring_diff = {}
            lts = lp_scoring.get("total_score") if lp_scoring else None
            rts = rp_scoring.get("total_score") if rp_scoring else None
            if lts is not None and rts is not None and abs(float(lts) - float(rts)) > 0.01:
                scoring_diff["total_score"] = {
                    "left": float(lts),
                    "right": float(rts),
                    "delta": round(float(rts) - float(lts), 2),
                }
            ls_sub = (lp_scoring or {}).get("sub_scores", {})
            rs_sub = (rp_scoring or {}).get("sub_scores", {})
            sub_diffs = {}
            for key in set(ls_sub) | set(rs_sub):
                lv = ls_sub.get(key)
                rv = rs_sub.get(key)
                if (
                    lv is not None and rv is not None
                    and isinstance(lv, (int, float)) and isinstance(rv, (int, float))
                    and abs(float(lv) - float(rv)) > 0.5
                ):
                    sub_diffs[key] = {"left": float(lv), "right": float(rv), "delta": round(float(rv) - float(lv), 2)}
            if sub_diffs:
                scoring_diff["sub_scores"] = sub_diffs
            if scoring_diff:
                diffs["scoring"] = scoring_diff

        # 持仓变化
        def _get_holdings(p: dict) -> list:
            dh = p.get("disclosed_holdings") if isinstance(p.get("disclosed_holdings"), dict) else {}
            return dh.get("holdings", [])
        lh = _get_holdings(lp)
        rh = _get_holdings(rp)
        if lh or rh:
            left_codes = {h.get("security_code"): h for h in lh}
            right_codes = {h.get("security_code"): h for h in rh}
            new_positions = [right_codes[c] for c in right_codes if c not in left_codes]
            exited_positions = [left_codes[c] for c in left_codes if c not in right_codes]
            weight_changes = []
            for c in set(left_codes) & set(right_codes):
                lw = left_codes[c].get("weight_pct")
                rw = right_codes[c].get("weight_pct")
                if lw is not None and rw is not None and abs(float(rw) - float(lw)) > 0.1:
                    weight_changes.append({
                        "code": c, "name": left_codes[c].get("security_name"),
                        "from": round(float(lw), 2),
                        "to": round(float(rw), 2),
                    })
            if new_positions or exited_positions or weight_changes:
                diffs["holdings"] = {
                    "new_positions": new_positions[:10],
                    "exited_positions": exited_positions[:10],
                    "weight_changes": weight_changes[:10],
                }

        # 风险提示变化
        lr = lp.get("risk_alerts", []) if isinstance(lp.get("risk_alerts"), list) else []
        rr = rp.get("risk_alerts", []) if isinstance(rp.get("risk_alerts"), list) else []
        if lr != rr:
            diffs["risk_alerts"] = {"left": lr, "right": rr}

        # 证据变化
        def _evidence_ids(p: dict) -> set[str]:
            evidence_items = p.get("evidence", [])
            if not isinstance(evidence_items, list):
                return set()
            return {
                str(item.get("evidence_id"))
                for item in evidence_items
                if isinstance(item, dict) and item.get("evidence_id")
            }
        le = _evidence_ids(lp)
        re = _evidence_ids(rp)
        if le != re:
            diffs["evidence"] = {
                "new": sorted(re - le),
                "removed": sorted(le - re),
                "unchanged_count": len(le & re),
            }

        lc = lp.get("conclusion_map", {}) if isinstance(lp.get("conclusion_map"), dict) else {}
        rc = rp.get("conclusion_map", {}) if isinstance(rp.get("conclusion_map"), dict) else {}
        conclusion_diffs = {
            key: {"left": lc.get(key), "right": rc.get(key)}
            for key in set(lc) | set(rc)
            if lc.get(key) != rc.get(key)
        }
        if conclusion_diffs:
            diffs["conclusion_status"] = conclusion_diffs

        changed = len(diffs) > 0
        evidence_records = [
            EvidenceRecord(
                evidence_id=f"research_packet:{left.packet_id}",
                entity_id=f"fund:{left.fund_code}",
                evidence_type=EvidenceType.RAW_DATA,
                source="research_packet",
                source_level=DataSourceLevel.LOCAL,
                date_range=(left.data_date, left.data_date),
                data_summary="左侧 Research Packet 快照",
                confidence=ConfidenceLevel.MEDIUM,
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
            EvidenceRecord(
                evidence_id=f"research_packet:{right.packet_id}",
                entity_id=f"fund:{right.fund_code}",
                evidence_type=EvidenceType.RAW_DATA,
                source="research_packet",
                source_level=DataSourceLevel.LOCAL,
                date_range=(right.data_date, right.data_date),
                data_summary="右侧 Research Packet 快照",
                confidence=ConfidenceLevel.MEDIUM,
                conclusion_status=ConclusionStatus.OBSERVATION,
            ),
        ]
        return _log(
            db,
            "diff_research_packets",
            params,
            APIResponse(
                data={
                    "fund_code": fund_code,
                    "left_info": {"packet_id": left.packet_id, "data_date": str(left.data_date)},
                    "right_info": {"packet_id": right.packet_id, "data_date": str(right.data_date)},
                    "changed": changed,
                    "diffs": diffs,
                },
                metadata={
                    "tool": "diff_research_packets",
                    "fund_code": fund_code,
                    "platform_version": __version__,
                },
                evidence=evidence_records,
                warnings=warnings if changed else [*warnings, "两个研究包在各模块上均无显著差异"],
                conclusion_status=ConclusionStatus.OBSERVATION if changed else ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "diff_research_packets",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "diff_research_packets"},
                warnings=[f"对比研究包失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/research/packets")
def list_research_packets(
    db: SessionDep,
    fund_code: str | None = Query(None, description="按基金代码过滤", max_length=20),
    limit: int = Query(20, ge=1, le=100, description="分页数量"),
) -> APIResponse[dict]:
    """列出已保存的研究包，支持 fund_code 过滤和 limit 分页。"""
    started = perf_counter()
    params = {"fund_code": fund_code, "limit": limit}
    try:
        stmt = select(ResearchPacketRecord)
        if fund_code:
            stmt = stmt.where(ResearchPacketRecord.fund_code == fund_code)
        stmt = stmt.order_by(
            ResearchPacketRecord.generated_at.desc()
        ).limit(limit)
        rows = db.scalars(stmt).all()

        items = []
        for row in rows:
            items.append({
                "packet_id": row.packet_id,
                "fund_code": row.fund_code,
                "template": row.template,
                "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                "data_date": str(row.data_date) if row.data_date else None,
                "platform_version": row.platform_version,
                "overall_confidence": row.overall_confidence,
                "is_latest": row.is_latest,
            })

        return _log(
            db,
            "list_research_packets",
            params,
            APIResponse(
                data={"packets": items, "count": len(items)},
                metadata={"tool": "list_research_packets", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "list_research_packets",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "list_research_packets"},
                warnings=[f"查询研究包列表失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/research/packets/{packet_id}")
def get_research_packet(
    db: SessionDep,
    packet_id: str,
) -> APIResponse[dict]:
    """获取单个研究包详情。"""
    started = perf_counter()
    params = {"packet_id": packet_id}
    try:
        record = db.scalar(
            select(ResearchPacketRecord).where(
                ResearchPacketRecord.packet_id == packet_id
            )
        )
        if record is None:
            return _log(
                db,
                "get_research_packet",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "get_research_packet"},
                    warnings=[f"研究包不存在: {packet_id}"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        packet_json = record.packet_json if isinstance(record.packet_json, dict) else {}

        # 判断是否包含 estimated 模块
        conclusion_map = packet_json.get("conclusion_map", {}) if isinstance(packet_json, dict) else {}
        has_estimated = any(
            status == "estimated" for status in conclusion_map.values()
        )
        has_needs_review = any(
            status == "needs_review" for status in conclusion_map.values()
        )

        conclusion_status = (
            ConclusionStatus.NEEDS_REVIEW if has_needs_review
            else ConclusionStatus.ESTIMATED if has_estimated
            else ConclusionStatus.COMPUTED
        )

        return _log(
            db,
            "get_research_packet",
            params,
            APIResponse(
                data={
                    "packet_id": record.packet_id,
                    "fund_code": record.fund_code,
                    "template": record.template,
                    "generated_at": record.generated_at.isoformat() if record.generated_at else None,
                    "data_date": str(record.data_date) if record.data_date else None,
                    "platform_version": record.platform_version,
                    "overall_confidence": record.overall_confidence,
                    "is_latest": record.is_latest,
                    "packet": packet_json,
                    "markdown": record.markdown_text,
                },
                metadata={
                    "tool": "get_research_packet",
                    "platform_version": __version__,
                    "packet_id": packet_id,
                },
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_research_packet",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "get_research_packet"},
                warnings=[f"查询研究包详情失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# Evidence 证据查询 API
# ============================================================


@v2_router.get("/evidence")
def list_evidence(
    db: SessionDep,
    fund_code: str | None = Query(None, description="按基金代码过滤 (entity_type=fund)", max_length=20),
    source_level: Annotated[DataSourceLevel | None, Query(description="按数据源等级过滤")] = None,
    evidence_type: str | None = Query(None, description="按证据类型过滤", max_length=30),
    limit: int = Query(50, ge=1, le=200, description="分页数量"),
    offset: int = Query(0, ge=0, description="分页偏移"),
) -> APIResponse[dict]:
    """查询证据列表，支持 fund_code / source_level / evidence_type 过滤与分页。"""
    started = perf_counter()
    params = {
        "fund_code": fund_code,
        "source_level": source_level.value if source_level else None,
        "evidence_type": evidence_type,
        "limit": limit,
        "offset": offset,
    }
    try:
        stmt = select(DbEvidenceRecord)
        count_stmt = select(func.count()).select_from(DbEvidenceRecord)

        if fund_code:
            stmt = stmt.where(
                DbEvidenceRecord.entity_type == "fund",
                DbEvidenceRecord.entity_id == fund_code,
            )
            count_stmt = count_stmt.where(
                DbEvidenceRecord.entity_type == "fund",
                DbEvidenceRecord.entity_id == fund_code,
            )
        if source_level is not None:
            stmt = stmt.where(DbEvidenceRecord.source_level == source_level)
            count_stmt = count_stmt.where(DbEvidenceRecord.source_level == source_level)
        if evidence_type:
            stmt = stmt.where(DbEvidenceRecord.evidence_type == evidence_type)
            count_stmt = count_stmt.where(DbEvidenceRecord.evidence_type == evidence_type)

        total = db.scalar(count_stmt) or 0

        stmt = stmt.order_by(DbEvidenceRecord.created_at.desc()).offset(offset).limit(limit)
        rows = db.scalars(stmt).all()

        items = []
        for row in rows:
            items.append({
                "evidence_id": row.evidence_id,
                "entity_id": row.entity_id,
                "entity_type": row.entity_type,
                "evidence_type": row.evidence_type,
                "source": row.source,
                "source_level": row.source_level.value if hasattr(row.source_level, "value") else row.source_level,
                "date_start": str(row.date_start) if row.date_start else None,
                "date_end": str(row.date_end) if row.date_end else None,
                "data_summary": row.data_summary,
                "confidence": row.confidence.value if hasattr(row.confidence, "value") else row.confidence,
                "conclusion_status": (
                    row.conclusion_status.value
                    if hasattr(row.conclusion_status, "value")
                    else row.conclusion_status
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })

        return _log(
            db,
            "list_evidence",
            params,
            APIResponse(
                data={"items": items, "total": total, "limit": limit, "offset": offset},
                metadata={"tool": "list_evidence", "platform_version": __version__},
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "list_evidence",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "list_evidence"},
                warnings=[f"查询证据列表失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/evidence/{evidence_id}")
def get_evidence(
    evidence_id: str,
    db: SessionDep,
) -> APIResponse[dict]:
    """获取单条证据详情。"""
    started = perf_counter()
    params = {"evidence_id": evidence_id}
    try:
        record = db.scalar(
            select(DbEvidenceRecord).where(DbEvidenceRecord.evidence_id == evidence_id)
        )
        if record is None:
            return _log(
                db,
                "get_evidence",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "get_evidence"},
                    warnings=[f"证据不存在: {evidence_id}"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )

        return _log(
            db,
            "get_evidence",
            params,
            APIResponse(
                data={
                    "evidence_id": record.evidence_id,
                    "entity_id": record.entity_id,
                    "entity_type": record.entity_type,
                    "evidence_type": record.evidence_type,
                    "source": record.source,
                    "source_level": (
                        record.source_level.value
                        if hasattr(record.source_level, "value")
                        else record.source_level
                    ),
                    "date_start": str(record.date_start) if record.date_start else None,
                    "date_end": str(record.date_end) if record.date_end else None,
                    "algorithm_metadata": record.algorithm_metadata,
                    "report_snippet": record.report_snippet,
                    "report_location": record.report_location,
                    "data_summary": record.data_summary,
                    "confidence": (
                        record.confidence.value
                        if hasattr(record.confidence, "value")
                        else record.confidence
                    ),
                    "conclusion_status": (
                        record.conclusion_status.value
                        if hasattr(record.conclusion_status, "value")
                        else record.conclusion_status
                    ),
                    "created_at": record.created_at.isoformat() if record.created_at else None,
                },
                metadata={
                    "tool": "get_evidence",
                    "platform_version": __version__,
                    "evidence_id": evidence_id,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_evidence",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "get_evidence"},
                warnings=[f"查询证据详情失败: {exc}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# P2.5-1: 基金池持久化 API
# ============================================================

# fmt: off
from fund_research.analysis.trading_ability import (  # noqa: E402,I001
    ALGORITHM_NAME as TA_ALGORITHM_NAME,
    ALGORITHM_VERSION as TA_ALGORITHM_VERSION,
    analyze_trading_ability,
    to_api_data as ta_to_api_data,
)
from fund_research.db.models_phase2 import (  # noqa: E402,I001
    FundPool as DbFundPool,
    FundPoolMember as DbFundPoolMember,
    SavedScreen as DbSavedScreen,
    TradingAbilityResult as DbTradingAbilityResult,
)
# fmt: on


class CreatePoolRequest(BaseModel):
    name: str = Field(..., max_length=100)
    description: str | None = None


class AddPoolMemberRequest(BaseModel):
    fund_code: str = Field(..., max_length=20)
    note: str | None = Field(default=None, max_length=200)


class SaveScreenRequest(BaseModel):
    name: str = Field(..., max_length=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    sort_by: str | None = None
    sort_order: str | None = "asc"


@v2_router.get("/pools")
def list_pools(db: SessionDep):
    started = perf_counter()
    pools = db.execute(select(DbFundPool).order_by(DbFundPool.updated_at.desc())).scalars().all()
    result = []
    for p in pools:
        count = db.execute(
            select(DbFundPoolMember.fund_code).where(DbFundPoolMember.pool_id == p.id)
        ).scalars().all()
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "fund_count": len(count),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        })
    return _log(db, "list_pools", {}, APIResponse(data=result, metadata={"count": len(result)}), started)


@v2_router.post("/pools")
def create_pool(body: CreatePoolRequest, db: SessionDep):
    started = perf_counter()
    try:
        pool = DbFundPool(name=body.name, description=body.description)
        db.add(pool)
        db.commit()
        db.refresh(pool)
        return _log(db, "create_pool", body.model_dump(), APIResponse(
            data={"id": pool.id, "name": pool.name, "description": pool.description},
            metadata={"created": True},
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "create_pool", body.model_dump(), APIResponse(
            data=None, warnings=[f"创建基金池失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.get("/pools/{pool_id}")
def get_pool(pool_id: int, db: SessionDep):
    started = perf_counter()
    pool = db.get(DbFundPool, pool_id)
    if not pool:
        return _log(db, "get_pool", {"pool_id": pool_id}, APIResponse(
            data=None, warnings=["基金池不存在"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)
    members = db.execute(
        select(DbFundPoolMember).where(DbFundPoolMember.pool_id == pool_id).order_by(DbFundPoolMember.added_at)
    ).scalars().all()
    data = {
        "id": pool.id,
        "name": pool.name,
        "description": pool.description,
        "created_at": pool.created_at.isoformat() if pool.created_at else None,
        "funds": [
            {
                "fund_code": m.fund_code,
                "note": m.note,
                "added_at": m.added_at.isoformat() if m.added_at else None,
            }
            for m in members
        ],
    }
    return _log(db, "get_pool", {"pool_id": pool_id}, APIResponse(data=data), started)


@v2_router.delete("/pools/{pool_id}")
def delete_pool(pool_id: int, db: SessionDep):
    started = perf_counter()
    try:
        pool = db.get(DbFundPool, pool_id)
        if not pool:
            return _log(db, "delete_pool", {"pool_id": pool_id}, APIResponse(
                data=None, warnings=["基金池不存在"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)
        db.execute(select(DbFundPoolMember).where(DbFundPoolMember.pool_id == pool_id))
        members = db.execute(
            select(DbFundPoolMember).where(DbFundPoolMember.pool_id == pool_id)
        ).scalars().all()
        for m in members:
            db.delete(m)
        db.delete(pool)
        db.commit()
        return _log(db, "delete_pool", {"pool_id": pool_id}, APIResponse(
            data={"deleted": True, "pool_id": pool_id},
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "delete_pool", {"pool_id": pool_id}, APIResponse(
            data=None, warnings=[f"删除基金池失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.post("/pools/{pool_id}/funds")
def add_pool_member(pool_id: int, body: AddPoolMemberRequest, db: SessionDep):
    started = perf_counter()
    params = {"pool_id": pool_id, **body.model_dump()}
    try:
        pool = db.get(DbFundPool, pool_id)
        if not pool:
            return _log(db, "add_pool_member", params, APIResponse(
                data=None, warnings=["基金池不存在"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)
        existing = db.execute(
            select(DbFundPoolMember).where(
                DbFundPoolMember.pool_id == pool_id,
                DbFundPoolMember.fund_code == body.fund_code,
            )
        ).scalar_one_or_none()
        if existing:
            return _log(db, "add_pool_member", params, APIResponse(
                data=None, warnings=["该基金已在池中"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)
        member = DbFundPoolMember(pool_id=pool_id, fund_code=body.fund_code, note=body.note)
        db.add(member)
        db.commit()
        db.refresh(member)
        return _log(db, "add_pool_member", params, APIResponse(
            data={"id": member.id, "pool_id": pool_id, "fund_code": body.fund_code},
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "add_pool_member", params, APIResponse(
            data=None, warnings=[f"添加基金到池失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.delete("/pools/{pool_id}/funds/{fund_code}")
def remove_pool_member(pool_id: int, fund_code: str, db: SessionDep):
    started = perf_counter()
    params = {"pool_id": pool_id, "fund_code": fund_code}
    try:
        member = db.execute(
            select(DbFundPoolMember).where(
                DbFundPoolMember.pool_id == pool_id,
                DbFundPoolMember.fund_code == fund_code,
            )
        ).scalar_one_or_none()
        if not member:
            return _log(db, "remove_pool_member", params, APIResponse(
                data=None, warnings=["该基金不在池中"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)
        db.delete(member)
        db.commit()
        return _log(db, "remove_pool_member", params, APIResponse(
            data={"removed": True, "fund_code": fund_code},
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "remove_pool_member", params, APIResponse(
            data=None, warnings=[f"从池中移除基金失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.get("/screens")
def list_screens(db: SessionDep):
    started = perf_counter()
    screens = db.execute(select(DbSavedScreen).order_by(DbSavedScreen.created_at.desc())).scalars().all()
    result = [{
        "id": s.id, "name": s.name, "filters": s.filters,
        "sort_by": s.sort_by, "sort_order": s.sort_order,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    } for s in screens]
    return _log(db, "list_screens", {}, APIResponse(data=result, metadata={"count": len(result)}), started)


@v2_router.post("/screens")
def save_screen(body: SaveScreenRequest, db: SessionDep):
    started = perf_counter()
    try:
        screen = DbSavedScreen(
            name=body.name, filters=body.filters,
            sort_by=body.sort_by, sort_order=body.sort_order,
        )
        db.add(screen)
        db.commit()
        db.refresh(screen)
        return _log(db, "save_screen", body.model_dump(), APIResponse(
            data={"id": screen.id, "name": screen.name},
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "save_screen", body.model_dump(), APIResponse(
            data=None, warnings=[f"保存筛选条件失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int, db: SessionDep):
    started = perf_counter()
    try:
        screen = db.get(DbSavedScreen, screen_id)
        if not screen:
            return _log(db, "delete_screen", {"screen_id": screen_id}, APIResponse(
                data=None, warnings=["筛选条件不存在"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)
        db.delete(screen)
        db.commit()
        return _log(db, "delete_screen", {"screen_id": screen_id}, APIResponse(
            data={"deleted": True, "screen_id": screen_id},
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "delete_screen", {"screen_id": screen_id}, APIResponse(
            data=None, warnings=[f"删除筛选条件失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


# ============================================================
# P2.6-1: 交易能力分析 API
# ============================================================


class TradingAbilityRequest(BaseModel):
    fund_code: str = Field(..., max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    evaluation_window_days: int = Field(default=60, ge=20, le=120)


@v2_router.post("/analysis/trading-ability")
def run_trading_ability(body: TradingAbilityRequest, db: SessionDep):
    started = perf_counter()
    params = body.model_dump()
    try:
        output = analyze_trading_ability(
            db=db,
            fund_code=body.fund_code,
            start_date=body.start_date,
            end_date=body.end_date,
            evaluation_window_days=body.evaluation_window_days,
        )
        result_dict = ta_to_api_data(output)

        # 持久化结果
        record = DbTradingAbilityResult(
            fund_code=body.fund_code,
            calc_date=output.calc_date,
            algorithm_name=TA_ALGORITHM_NAME,
            algorithm_version=TA_ALGORITHM_VERSION,
            period_start=output.period_start,
            period_end=output.period_end,
            estimated_turnover_rate=output.estimated_turnover_rate,
            estimated_buy_timing_score=output.estimated_buy_timing_score,
            estimated_sell_timing_score=output.estimated_sell_timing_score,
            estimated_holding_period=output.estimated_holding_period,
            estimated_excess_return_from_trading=output.estimated_excess_return_from_trading,
            trading_detail=output.trading_detail,
            parameters={
                "start_date": str(body.start_date) if body.start_date else None,
                "end_date": str(body.end_date) if body.end_date else None,
                "evaluation_window_days": body.evaluation_window_days,
            },
            confidence=output.confidence,
            conclusion_status=output.conclusion_status,
            warnings=output.warnings,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        result_dict["id"] = record.id

        return _log(db, "run_trading_ability", params, APIResponse(
            data=result_dict,
            metadata={"algorithm": TA_ALGORITHM_NAME, "version": TA_ALGORITHM_VERSION},
            warnings=output.warnings,
            conclusion_status=ConclusionStatus(output.conclusion_status),
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "run_trading_ability", params, APIResponse(
            data=None,
            warnings=[f"交易能力分析失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.get("/analysis/trading-ability/{fund_code}")
def list_trading_ability(fund_code: str, db: SessionDep, limit: int = Query(default=10, ge=1, le=100)):
    started = perf_counter()
    params = {"fund_code": fund_code, "limit": limit}
    try:
        rows = db.execute(
            select(DbTradingAbilityResult)
            .where(DbTradingAbilityResult.fund_code == fund_code)
            .order_by(DbTradingAbilityResult.created_at.desc())
            .limit(limit)
        ).scalars().all()

        items = []
        for row in rows:
            items.append({
                "id": row.id,
                "fund_code": row.fund_code,
                "calc_date": str(row.calc_date) if row.calc_date else None,
                "period_start": str(row.period_start) if row.period_start else None,
                "period_end": str(row.period_end) if row.period_end else None,
                "estimated_turnover_rate": row.estimated_turnover_rate,
                "estimated_buy_timing_score": row.estimated_buy_timing_score,
                "estimated_sell_timing_score": row.estimated_sell_timing_score,
                "estimated_holding_period": row.estimated_holding_period,
                "estimated_excess_return_from_trading": row.estimated_excess_return_from_trading,
                "confidence": row.confidence,
                "conclusion_status": row.conclusion_status,
                "warnings": row.warnings,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })

        return _log(db, "list_trading_ability", params, APIResponse(
            data={"results": items, "count": len(items)},
        ), started)
    except Exception as exc:
        return _log(db, "list_trading_ability", params, APIResponse(
            data=None,
            warnings=[f"查询交易能力分析结果失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


# ============================================================
# P2.5-2: 结构化导出 API
# ============================================================


class ExportPacketRequest(BaseModel):
    fund_code: str = Field(..., max_length=20)
    packet_id: str | None = None
    format: str = Field(default="markdown", pattern="^(markdown|json|csv)$")


@v2_router.get("/research/packet/{fund_code}/export")
def export_research_packet(
    fund_code: str,
    db: SessionDep,
    format: str = Query(default="markdown", pattern="^(markdown|json|csv)$"),
):
    """导出研究包为 Markdown/JSON/CSV。"""
    started = perf_counter()
    params = {"fund_code": fund_code, "format": format}
    from fund_research.config.settings import get_settings as _get_settings

    try:
        stmt = (
            select(ResearchPacketRecord)
            .where(ResearchPacketRecord.fund_code == fund_code)
            .order_by(ResearchPacketRecord.generated_at.desc())
            .limit(1)
        )
        record = db.scalar(stmt)
        if not record:
            return _log(db, "export_research_packet", params, APIResponse(
                data=None, warnings=["未找到研究包"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)

        packet_json = record.packet_json if isinstance(record.packet_json, dict) else {}

        if format == "json":
            content = json.dumps(packet_json, ensure_ascii=False, indent=2)
            media_type = "application/json"
            filename = f"{fund_code}_packet.json"
        elif format == "csv":
            import csv as _csv
            import io as _io
            buf = _io.StringIO()
            writer = _csv.writer(buf)
            writer.writerow(["field", "value"])
            for section, val in packet_json.items():
                if isinstance(val, dict):
                    for k, v in val.items():
                        writer.writerow([f"{section}.{k}", str(v)[:200]])
                else:
                    writer.writerow([section, str(val)[:200]])
            content = buf.getvalue()
            media_type = "text/csv"
            filename = f"{fund_code}_packet.csv"
        else:
            disclaimer = _get_settings().disclaimer
            md = record.markdown_text or ""
            header = (
                f"# 基金研究包: {fund_code}\n\n"
                f"> 生成日期: {record.generated_at.date().isoformat() if record.generated_at else 'N/A'}\n"
                f"> 数据日期: {record.data_date}\n"
                f"> 平台版本: {record.platform_version}\n"
                f"> 整体置信度: {record.overall_confidence}\n"
                f"> 免责声明: {disclaimer}\n\n---\n\n"
            )
            content = header + md
            media_type = "text/markdown"
            filename = f"{fund_code}_packet.md"

        import base64 as _b64
        encoded = _b64.b64encode(content.encode("utf-8")).decode("ascii")
        return _log(db, "export_research_packet", params, APIResponse(
            data={
                "filename": filename,
                "format": format,
                "media_type": media_type,
                "content_base64": encoded,
                "size_bytes": len(content.encode("utf-8")),
            },
            metadata={"fund_code": fund_code, "packet_id": record.packet_id},
        ), started)
    except Exception as exc:
        return _log(db, "export_research_packet", params, APIResponse(
            data=None, warnings=[f"导出研究包失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


class ExportScreenRequest(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    sort_by: str | None = None
    sort_order: str | None = "asc"
    limit: int = Field(default=50, ge=1, le=500)
    format: str = Field(default="csv", pattern="^(csv|json)$")


@v2_router.post("/funds/screen/export")
def export_screen_results(body: ExportScreenRequest, db: SessionDep):
    """导出基金筛选结果为 CSV/JSON。"""
    started = perf_counter()
    params = body.model_dump()
    try:
        from fund_research.api.router import screen_funds as _screen

        screen_result = _screen(db, body.filters)
        funds = (screen_result.data or {}).get("funds", [])
        if not funds:
            return _log(db, "export_screen_results", params, APIResponse(
                data=None, warnings=["无筛选结果"],
            ), started)

        if body.sort_by:
            reverse = body.sort_order == "desc"
            funds = sorted(funds, key=lambda x: x.get(body.sort_by, 0) or 0, reverse=reverse)
        funds = funds[:body.limit]

        import base64 as _b64
        import csv as _csv
        import io as _io

        if body.format == "json":
            content = json.dumps(funds, ensure_ascii=False, indent=2)
            media_type = "application/json"
            filename = "screen_results.json"
        else:
            buf = _io.StringIO()
            writer = _csv.DictWriter(buf, fieldnames=funds[0].keys(), extrasaction="ignore")
            writer.writeheader()
            for row in funds:
                writer.writerow(row)
            content = buf.getvalue()
            media_type = "text/csv"
            filename = "screen_results.csv"

        encoded = _b64.b64encode(content.encode("utf-8")).decode("ascii")
        return _log(db, "export_screen_results", params, APIResponse(
            data={
                "filename": filename,
                "format": body.format,
                "media_type": media_type,
                "content_base64": encoded,
                "row_count": len(funds),
            },
        ), started)
    except Exception as exc:
        return _log(db, "export_screen_results", params, APIResponse(
            data=None, warnings=[f"导出筛选结果失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


# ============================================================
# 数据质量面板
# ============================================================


@v2_router.get("/quality/dashboard")
def get_quality_dashboard(db: SessionDep) -> APIResponse[dict]:
    """数据质量监控面板 — 返回数据库覆盖统计、数据新鲜度、数据源快照、任务日志。"""
    started = perf_counter()
    params: dict[str, Any] = {}

    # 表行数统计
    table_counts: dict[str, int] = {}
    count_tables = [
        "fund_main", "fund_nav", "fund_disclosed_holdings", "fund_scale",
        "fund_fee", "holder_structure", "stock_daily", "stock_main",
        "fund_manager", "fund_company", "style_exposure_result",
        "static_attribution_result", "research_packet", "evidence",
        "data_source_snapshot", "task_log",
    ]
    for tbl in count_tables:
        try:
            result = db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            table_counts[tbl] = int(result.scalar() or 0)
        except Exception:
            table_counts[tbl] = -1  # 表不存在

    # 数据新鲜度
    freshness: dict[str, str | None] = {}
    for tbl, col in [("fund_nav", "trade_date"), ("stock_daily", "trade_date"),
                     ("fund_disclosed_holdings", "report_date"), ("fund_scale", "report_date")]:
        try:
            result = db.execute(text(f"SELECT MAX({col}) FROM {tbl}"))
            val = result.scalar()
            freshness[tbl] = str(val) if val else None
        except Exception:
            freshness[tbl] = None

    # 最近数据源快照 (10条)
    snapshots_raw: list[dict] = []
    try:
        snapshots = db.execute(
            select(DataSourceSnapshot)
            .order_by(DataSourceSnapshot.fetch_timestamp.desc())
            .limit(10)
        ).scalars().all()
        for s in snapshots:
            snapshots_raw.append({
                "source_name": s.source_name,
                "source_level": s.source_level.value if s.source_level else None,
                "entity_type": s.entity_type,
                "fetch_timestamp": s.fetch_timestamp.isoformat() if s.fetch_timestamp else None,
                "record_count": s.record_count,
                "coverage_rate": s.coverage_rate,
                "anomaly_count": s.anomaly_count,
                "is_success": s.is_success,
                "error_message": s.error_message,
            })
    except Exception:
        pass

    # 最近任务日志 (10条)
    tasks_raw: list[dict] = []
    try:
        tasks = db.execute(
            select(TaskLog)
            .order_by(TaskLog.created_at.desc())
            .limit(10)
        ).scalars().all()
        for t in tasks:
            tasks_raw.append({
                "task_id": t.task_id,
                "task_type": t.task_type.value if t.task_type else None,
                "status": t.status.value if t.status else None,
                "target_entity": t.target_entity,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "duration_ms": t.duration_ms,
                "result_summary": t.result_summary,
                "error_message": t.error_message,
            })
    except Exception:
        pass

    data = {
        "table_counts": table_counts,
        "freshness": freshness,
        "recent_snapshots": snapshots_raw,
        "recent_tasks": tasks_raw,
    }

    return _log(db, "get_quality_dashboard", params, APIResponse(
        data=data,
        metadata={"tool": "get_quality_dashboard"},
    ), started)


# ============================================================
# Phase 3 — 指纹与相似度 API
# ============================================================
#
# 注意：静态路径（/fingerprint/batch、/fingerprint/compare）必须在动态路径
# /fingerprint/{fund_code} 之前注册，否则 batch/compare 会被 {fund_code}
# 捕获。


@v2_router.post("/fingerprint/batch")
def batch_fingerprint_endpoint(
    db: SessionDep,
    body: BatchFingerprintRequest,
) -> APIResponse[dict]:
    """批量生成基金指纹向量并持久化。

    遍历 fund_codes，逐只调用 generate_fingerprint + persist_fingerprint，
    返回成功/失败计数与错误明细。
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    success_count = 0
    failure_count = 0
    errors: list[dict[str, Any]] = []
    try:
        for code in body.fund_codes:
            try:
                result = generate_fingerprint(db, code, calc_date=body.calc_date)
                persist_fingerprint(db, result)
                db.commit()
                success_count += 1
            except Exception as inner_exc:
                db.rollback()
                failure_count += 1
                errors.append({"fund_code": code, "error": str(inner_exc)})

        warnings: list[str] = []
        conclusion_status = ConclusionStatus.COMPUTED
        if failure_count > 0:
            warnings.append(f"批量生成指纹：{failure_count} 只失败")
            conclusion_status = (
                ConclusionStatus.NEEDS_REVIEW
                if success_count == 0
                else ConclusionStatus.OBSERVATION
            )
        if success_count == 0:
            warnings.append("没有生成任何有效指纹")

        return _log(
            db,
            "batch_fingerprint",
            params,
            APIResponse(
                data={
                    "total": len(body.fund_codes),
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "errors": errors,
                    "calc_date": str(body.calc_date) if body.calc_date else None,
                },
                metadata={
                    "tool": "fingerprint",
                    "algorithm_version": FINGERPRINT_VERSION,
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "batch_fingerprint",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "fingerprint", "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/fingerprint/compare")
def compare_fingerprints_endpoint(
    db: SessionDep,
    body: FundCompareRequest,
) -> APIResponse[dict]:
    """对比多只基金的指纹向量。

    调用 compare_fund_fingerprints，返回逐只指纹数据、相似度矩阵与持仓重叠分析。
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        comparison = compare_fund_fingerprints(db, body.fund_codes)
        warnings = list(comparison.get("warnings") or [])
        found_codes = comparison.get("fund_codes") or []
        missing_codes = [c for c in body.fund_codes if c not in found_codes]
        if missing_codes:
            warnings.append(f"以下基金无可用指纹: {', '.join(missing_codes)}")

        conclusion_status = (
            ConclusionStatus.NEEDS_REVIEW
            if len(found_codes) < 2
            else ConclusionStatus.COMPUTED
        )

        return _log(
            db,
            "compare_fingerprints",
            params,
            APIResponse(
                data={
                    "fund_codes": found_codes,
                    "comparison_data": comparison.get("comparison_data") or {},
                    "similarity_matrix": comparison.get("similarity_matrix") or {},
                    "overlap_analysis": comparison.get("overlap_analysis") or {},
                    "missing_codes": missing_codes,
                },
                metadata={
                    "tool": "fingerprint",
                    "algorithm_version": FINGERPRINT_VERSION,
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "compare_fingerprints",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "fingerprint", "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/fingerprint/{fund_code}")
def generate_fingerprint_endpoint(
    fund_code: str,
    db: SessionDep,
    body: FingerprintRequest | None = None,
) -> APIResponse[dict]:
    """生成单只基金的指纹向量并持久化。

    调用 generate_fingerprint + persist_fingerprint，返回指纹字典数据。
    """
    started = perf_counter()
    calc_date = body.calc_date if body else None
    params = {"fund_code": fund_code, "calc_date": str(calc_date) if calc_date else None}
    try:
        result = generate_fingerprint(db, fund_code, calc_date=calc_date)
        row = persist_fingerprint(db, result)
        db.commit()
        data = fingerprint_to_dict(row)
        warnings = list(result.warnings or [])
        if result.contains_estimated:
            warnings.append("指纹包含 estimated 维度，仅作为观察结果")
        conclusion_status = ConclusionStatus(result.conclusion_status)
        return _log(
            db,
            "generate_fingerprint",
            params,
            APIResponse(
                data=data,
                metadata={
                    "tool": "fingerprint",
                    "algorithm_version": FINGERPRINT_VERSION,
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "generate_fingerprint",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "fingerprint", "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/fingerprint/{fund_code}")
def get_fingerprint_endpoint(
    fund_code: str,
    db: SessionDep,
) -> APIResponse[dict]:
    """获取基金最近一次指纹记录。

    若不存在则返回 data=None 与告警，conclusion_status=NEEDS_REVIEW。
    """
    started = perf_counter()
    params = {"fund_code": fund_code}
    try:
        row = get_latest_fingerprint(db, fund_code)
        if row is None:
            return _log(
                db,
                "get_fingerprint",
                params,
                APIResponse(
                    data=None,
                    metadata={"tool": "fingerprint", "platform_version": __version__},
                    warnings=[f"基金 {fund_code} 暂无指纹记录"],
                    conclusion_status=ConclusionStatus.NEEDS_REVIEW,
                ),
                started,
            )
        data = fingerprint_to_dict(row)
        return _log(
            db,
            "get_fingerprint",
            params,
            APIResponse(
                data=data,
                metadata={
                    "tool": "fingerprint",
                    "algorithm_version": row.algorithm_version,
                    "platform_version": __version__,
                },
                warnings=list(row.warnings or []),
                conclusion_status=ConclusionStatus(row.conclusion_status),
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "get_fingerprint",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "fingerprint", "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/fingerprint/{fund_code}/similar")
def find_similar_funds_endpoint(
    fund_code: str,
    db: SessionDep,
    body: SimilarFundsRequest | None = None,
) -> APIResponse[dict]:
    """基于指纹向量查找相似基金。

    调用 find_similar_funds + persist_similarity_cache，返回相似基金列表。
    """
    started = perf_counter()
    metric_space = body.metric_space if body else "composite"
    top_n = body.top_n if body else 10
    same_type_only = body.same_type_only if body else True
    params = {
        "fund_code": fund_code,
        "metric_space": metric_space,
        "top_n": top_n,
        "same_type_only": same_type_only,
    }
    try:
        results = find_similar_funds(
            db,
            fund_code,
            metric_space=metric_space,
            top_n=top_n,
            same_type_only=same_type_only,
        )
        persist_similarity_cache(db, results)
        db.commit()

        similar_data = [r.to_data() for r in results]
        warnings: list[str] = []
        if not results:
            warnings.append(f"基金 {fund_code} 无可用指纹或未找到相似基金")
        conclusion_status = (
            ConclusionStatus.NEEDS_REVIEW if not results else ConclusionStatus.COMPUTED
        )

        return _log(
            db,
            "find_similar_funds",
            params,
            APIResponse(
                data={
                    "fund_code": fund_code,
                    "metric_space": metric_space,
                    "top_n": top_n,
                    "same_type_only": same_type_only,
                    "similar_funds": similar_data,
                    "count": len(similar_data),
                },
                metadata={
                    "tool": "fingerprint",
                    "algorithm_version": FINGERPRINT_VERSION,
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "find_similar_funds",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "fingerprint", "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/funds/compare")
def compare_funds_endpoint(
    db: SessionDep,
    body: FundCompareRequest,
) -> APIResponse[dict]:
    """多基金综合对比（高层接口）。

    合并 FundMain 基础信息与指纹对比结果（相似度矩阵、持仓重叠分析）。
    """
    started = perf_counter()
    params = body.model_dump(mode="json")
    try:
        # 基础信息
        funds = db.scalars(
            select(FundMain).where(FundMain.fund_code.in_(body.fund_codes))
        ).all()
        basic_info: dict[str, Any] = {}
        for f in funds:
            basic_info[f.fund_code] = {
                "fund_code": f.fund_code,
                "short_name": f.short_name,
                "full_name": f.full_name,
                "category": f.category,
                "sub_category": f.sub_category,
                "investment_type": f.investment_type,
                "operation_mode": f.operation_mode,
                "inception_date": str(f.inception_date) if f.inception_date else None,
                "benchmark": f.benchmark,
                "is_etf": f.is_etf,
                "is_qdii": f.is_qdii,
                "is_fof": f.is_fof,
                "status": f.status,
            }

        # 指纹对比
        comparison = compare_fund_fingerprints(db, body.fund_codes)
        found_codes = comparison.get("fund_codes") or []
        missing_codes = [c for c in body.fund_codes if c not in found_codes]
        missing_basic = [c for c in body.fund_codes if c not in basic_info]

        warnings: list[str] = list(comparison.get("warnings") or [])
        if missing_codes:
            warnings.append(f"以下基金无可用指纹: {', '.join(missing_codes)}")
        if missing_basic:
            warnings.append(f"以下基金无基础信息: {', '.join(missing_basic)}")

        conclusion_status = (
            ConclusionStatus.NEEDS_REVIEW
            if len(found_codes) < 2
            else ConclusionStatus.COMPUTED
        )

        return _log(
            db,
            "compare_funds",
            params,
            APIResponse(
                data={
                    "fund_codes": body.fund_codes,
                    "basic_info": basic_info,
                    "comparison_data": comparison.get("comparison_data") or {},
                    "similarity_matrix": comparison.get("similarity_matrix") or {},
                    "overlap_analysis": comparison.get("overlap_analysis") or {},
                    "missing_fingerprint_codes": missing_codes,
                    "missing_basic_codes": missing_basic,
                },
                metadata={
                    "tool": "fingerprint",
                    "algorithm_version": FINGERPRINT_VERSION,
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "compare_funds",
            params,
            APIResponse(
                data=None,
                metadata={"tool": "fingerprint", "platform_version": __version__},
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# P3.4: 基金池提醒 API
# ============================================================


class CreateAlertRuleRequest(BaseModel):
    fund_code: str = Field(..., max_length=20)
    alert_type: str
    params: dict[str, Any] = Field(default_factory=dict)


class AlertScanRequest(BaseModel):
    alert_types: list[str] | None = None
    params: dict[str, Any] = Field(default_factory=dict)


def _alert_record_to_dict(r: PoolAlertRecord) -> dict[str, Any]:
    """Serialize a PoolAlertRecord to an API-friendly dict."""
    return {
        "id": r.id,
        "rule_id": r.rule_id,
        "pool_id": r.pool_id,
        "fund_code": r.fund_code,
        "alert_type": r.alert_type,
        "severity": r.severity,
        "message": r.message,
        "detail": r.detail,
        "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
        "is_read": r.is_read,
    }


@v2_router.post("/pools/{pool_id}/alert-rules", response_model=APIResponse[dict])
def create_alert_rule_endpoint(
    pool_id: int,
    body: CreateAlertRuleRequest,
    db: SessionDep,
) -> APIResponse[dict]:
    """创建基金池提醒规则。"""
    started = perf_counter()
    params = {"pool_id": pool_id, **body.model_dump()}
    try:
        if body.alert_type not in ALERT_TYPES:
            return _log(db, "create_alert_rule", params, APIResponse(
                data=None,
                metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
                warnings=[f"未知提醒类型: {body.alert_type}"],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ), started)
        rule = create_alert_rule(db, pool_id, body.fund_code, body.alert_type, body.params)
        db.commit()
        db.refresh(rule)
        return _log(db, "create_alert_rule", params, APIResponse(
            data={
                "id": rule.id,
                "pool_id": rule.pool_id,
                "fund_code": rule.fund_code,
                "alert_type": rule.alert_type,
                "params": rule.params,
                "is_active": rule.is_active,
            },
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "create_alert_rule", params, APIResponse(
            data=None,
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            warnings=[f"创建提醒规则失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.get("/pools/{pool_id}/alert-rules", response_model=APIResponse[dict])
def list_alert_rules_endpoint(
    pool_id: int,
    db: SessionDep,
    fund_code: str | None = Query(None),
) -> APIResponse[dict]:
    """列出基金池提醒规则，可按基金代码筛选。"""
    started = perf_counter()
    params = {"pool_id": pool_id, "fund_code": fund_code}
    try:
        rules = get_alert_rules(db, pool_id, fund_code=fund_code)
        data = [
            {
                "id": r.id,
                "pool_id": r.pool_id,
                "fund_code": r.fund_code,
                "alert_type": r.alert_type,
                "params": r.params,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rules
        ]
        return _log(db, "list_alert_rules", params, APIResponse(
            data={"rules": data, "total": len(data)},
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "list_alert_rules", params, APIResponse(
            data=None,
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            warnings=[f"获取提醒规则失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.delete("/pools/{pool_id}/alert-rules/{rule_id}", response_model=APIResponse[dict])
def delete_alert_rule_endpoint(
    pool_id: int,
    rule_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """删除基金池提醒规则。"""
    started = perf_counter()
    params = {"pool_id": pool_id, "rule_id": rule_id}
    try:
        rule = db.scalars(
            select(PoolAlertRule).where(
                PoolAlertRule.id == rule_id,
                PoolAlertRule.pool_id == pool_id,
            ).limit(1)
        ).first()
        if rule is None:
            raise HTTPException(status_code=404, detail="提醒规则不存在")
        db.delete(rule)
        db.commit()
        return _log(db, "delete_alert_rule", params, APIResponse(
            data={"deleted": True, "rule_id": rule_id},
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "delete_alert_rule", params, APIResponse(
            data=None,
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            warnings=[f"删除提醒规则失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.get("/pools/{pool_id}/alerts", response_model=APIResponse[dict])
def list_pool_alerts_endpoint(
    pool_id: int,
    db: SessionDep,
    is_read: bool | None = Query(None),
    fund_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[dict]:
    """列出基金池提醒记录。"""
    started = perf_counter()
    params = {"pool_id": pool_id, "is_read": is_read, "fund_code": fund_code, "limit": limit}
    try:
        records = get_alert_records(
            db, pool_id=pool_id, fund_code=fund_code, is_read=is_read, limit=limit
        )
        data = [_alert_record_to_dict(r) for r in records]
        return _log(db, "list_pool_alerts", params, APIResponse(
            data={"alerts": data, "total": len(data)},
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "list_pool_alerts", params, APIResponse(
            data=None,
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            warnings=[f"获取提醒记录失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.get("/alerts", response_model=APIResponse[dict])
def list_alerts_endpoint(
    db: SessionDep,
    fund_code: str | None = Query(None),
    is_read: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[dict]:
    """全局提醒记录查询。"""
    started = perf_counter()
    params = {"fund_code": fund_code, "is_read": is_read, "limit": limit}
    try:
        records = get_alert_records(
            db, pool_id=None, fund_code=fund_code, is_read=is_read, limit=limit
        )
        data = [_alert_record_to_dict(r) for r in records]
        return _log(db, "list_alerts", params, APIResponse(
            data={"alerts": data, "total": len(data)},
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "list_alerts", params, APIResponse(
            data=None,
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            warnings=[f"获取提醒记录失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.post("/alerts/{alert_id}/read", response_model=APIResponse[dict])
def mark_alert_read_endpoint(
    alert_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """标记提醒为已读。"""
    started = perf_counter()
    params = {"alert_id": alert_id}
    try:
        record = mark_alert_read(db, alert_id)
        if record is None:
            raise HTTPException(status_code=404, detail="提醒记录不存在")
        db.commit()
        return _log(db, "mark_alert_read", params, APIResponse(
            data={"id": record.id, "is_read": record.is_read},
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "mark_alert_read", params, APIResponse(
            data=None,
            metadata={"tool": POOL_ALERT_NAME, "platform_version": __version__},
            warnings=[f"标记已读失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


@v2_router.post("/pools/{pool_id}/alerts/scan", response_model=APIResponse[dict])
def scan_pool_alerts_endpoint(
    pool_id: int,
    body: AlertScanRequest,
    db: SessionDep,
) -> APIResponse[dict]:
    """手动触发基金池提醒扫描，并将结果持久化到 PoolAlertRecord。"""
    started = perf_counter()
    params = {"pool_id": pool_id, **body.model_dump()}
    try:
        items, scan_warnings = scan_pool_alerts(
            db, pool_id, alert_types=body.alert_types, params=body.params
        )
        persisted = persist_alerts(db, pool_id, items)
        records: list[dict[str, Any]] = []
        for record in persisted:
            records.append({
                "id": record.id,
                "fund_code": record.fund_code,
                "alert_type": record.alert_type,
                "severity": record.severity,
                "message": record.message,
                "triggered_at": record.triggered_at.isoformat() if record.triggered_at else None,
            })
        db.commit()
        all_warnings = list(scan_warnings)
        return _log(db, "scan_pool_alerts", params, APIResponse(
            data={"alerts": records, "total": len(records), "pool_id": pool_id},
            metadata={
                "tool": POOL_ALERT_NAME,
                "algorithm_version": POOL_ALERT_VERSION,
                "platform_version": __version__,
            },
            warnings=all_warnings if all_warnings else None,
            conclusion_status=ConclusionStatus.COMPUTED,
        ), started)
    except Exception as exc:
        db.rollback()
        return _log(db, "scan_pool_alerts", params, APIResponse(
            data=None,
            metadata={
                "tool": POOL_ALERT_NAME,
                "algorithm_version": POOL_ALERT_VERSION,
                "platform_version": __version__,
            },
            warnings=[f"提醒扫描失败: {exc}"],
            conclusion_status=ConclusionStatus.NEEDS_REVIEW,
        ), started)


# ============================================================
# P3.5: 股票反选基金
# ============================================================


class ReverseLookupRequest(BaseModel):
    stock_codes: list[str] = Field(..., min_length=1, max_length=50)
    fund_scope: str = Field(default="all", pattern="^(all|pool|fund_type)$")
    scope_id: str | None = None
    method: str = Field(default="weighted", pattern="^(disclosed|simulated|weighted)$")
    top_n: int = Field(default=20, ge=1, le=100)


@v2_router.post("/analysis/reverse-lookup", response_model=APIResponse[dict])
def reverse_lookup_endpoint(
    db: SessionDep,
    request: ReverseLookupRequest,
) -> APIResponse[dict]:
    """股票反选基金 — 给定一篮子股票代码，查找持有这些股票的基金并按暴露度排序。

    支持三种方法：disclosed（披露持仓，fact）、simulated（模拟持仓，estimated）、
    weighted（披露优先，模拟回退）。结果持久化到 reverse_lookup_result 表。
    """
    started = perf_counter()
    params = {
        "stock_codes": request.stock_codes,
        "fund_scope": request.fund_scope,
        "scope_id": request.scope_id,
        "method": request.method,
        "top_n": request.top_n,
    }
    try:
        result = reverse_lookup(
            db,
            request.stock_codes,
            method=request.method,
            fund_scope=request.fund_scope,
            scope_id=request.scope_id,
            top_n=request.top_n,
        )
        persist_reverse_lookup(
            db,
            request.stock_codes,
            result,
            request.fund_scope,
            request.scope_id,
            request.method,
        )
        db.commit()

        warnings: list[str] = []
        if not result["results"]:
            warnings.append("未找到持有给定股票的基金")

        # Overall conclusion status reflects the mix of fact / estimated sources.
        sources = {r.get("source") for r in result["results"]}
        if not result["results"]:
            conclusion_status = ConclusionStatus.NEEDS_REVIEW
        elif sources == {"fact"}:
            conclusion_status = ConclusionStatus.FACT
        elif sources == {"estimated"}:
            conclusion_status = ConclusionStatus.ESTIMATED
            warnings.append("结果仅来自模拟持仓，属于 estimated，不可作为高置信结论")
        else:
            conclusion_status = ConclusionStatus.COMPUTED

        return _log(
            db,
            "reverse_lookup",
            params,
            APIResponse(
                data={
                    "results": result["results"],
                    "stock_coverage": result["stock_coverage"],
                    "method": result["method"],
                    "fund_count": result["fund_count"],
                },
                metadata={
                    "tool": REVERSE_LOOKUP_NAME,
                    "algorithm_version": REVERSE_LOOKUP_VERSION,
                    "platform_version": __version__,
                },
                warnings=warnings,
                conclusion_status=conclusion_status,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "reverse_lookup",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": REVERSE_LOOKUP_NAME,
                    "algorithm_version": REVERSE_LOOKUP_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# P3.6: 研究任务模板
# ============================================================


class TemplateRunRequest(BaseModel):
    """Request body for executing a research task template."""

    inputs: dict[str, Any] = Field(default_factory=dict)


@v2_router.post("/templates/seed", response_model=APIResponse[dict])
def seed_templates_endpoint(db: SessionDep) -> APIResponse[dict]:
    """植入内置研究任务模板。返回新插入的模板数量。"""
    started = perf_counter()
    params: dict[str, Any] = {}
    try:
        count = seed_builtin_templates(db)
        db.commit()
        return _log(
            db,
            "template_seed",
            params,
            APIResponse(
                data={"inserted": count},
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "template_seed",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/templates", response_model=APIResponse[dict])
def list_templates_endpoint(
    db: SessionDep,
    builtin_only: bool = Query(False, description="仅返回内置模板"),
) -> APIResponse[dict]:
    """列出所有研究任务模板。"""
    started = perf_counter()
    params = {"builtin_only": builtin_only}
    try:
        templates = list_templates(db, builtin_only=builtin_only)
        data = [
            {
                "template_id": t.template_id,
                "name": t.name,
                "description": t.description,
                "definition": t.definition,
                "is_builtin": t.is_builtin,
                "created_at": (
                    t.created_at.isoformat() if t.created_at else None
                ),
            }
            for t in templates
        ]
        return _log(
            db,
            "template_list",
            params,
            APIResponse(
                data={"templates": data, "total": len(data)},
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "template_list",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/templates/runs", response_model=APIResponse[dict])
def list_template_runs_endpoint(
    db: SessionDep,
    template_id: str | None = Query(None, description="按模板 ID 过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回条数上限"),
) -> APIResponse[dict]:
    """列出模板执行记录，支持按模板 ID 过滤。"""
    started = perf_counter()
    params = {"template_id": template_id, "limit": limit}
    try:
        records = get_run_records(db, template_id=template_id, limit=limit)
        data = [
            {
                "id": r.id,
                "template_id": r.template_id,
                "status": r.status,
                "steps_total": r.steps_total,
                "steps_completed": r.steps_completed,
                "steps_failed": r.steps_failed,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": (
                    r.completed_at.isoformat() if r.completed_at else None
                ),
                "error_message": r.error_message,
            }
            for r in records
        ]
        return _log(
            db,
            "template_run_list",
            params,
            APIResponse(
                data={"runs": data, "total": len(data)},
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "template_run_list",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/templates/runs/{run_id}", response_model=APIResponse[dict])
def get_template_run_endpoint(
    run_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """查询单条模板执行记录。"""
    started = perf_counter()
    params = {"run_id": run_id}
    try:
        record = get_run_record(db, run_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"run record not found: {run_id}")
        data = {
            "id": record.id,
            "template_id": record.template_id,
            "inputs": record.inputs,
            "status": record.status,
            "steps_total": record.steps_total,
            "steps_completed": record.steps_completed,
            "steps_failed": record.steps_failed,
            "step_results": record.step_results or [],
            "research_packet_id": record.research_packet_id,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": (
                record.completed_at.isoformat() if record.completed_at else None
            ),
            "error_message": record.error_message,
        }
        return _log(
            db,
            "template_run_detail",
            params,
            APIResponse(
                data=data,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "template_run_detail",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.get("/templates/{template_id}", response_model=APIResponse[dict])
def get_template_endpoint(
    template_id: str,
    db: SessionDep,
) -> APIResponse[dict]:
    """查询单个研究任务模板。"""
    started = perf_counter()
    params = {"template_id": template_id}
    try:
        template = get_template(db, template_id)
        if template is None:
            raise HTTPException(
                status_code=404, detail=f"template not found: {template_id}"
            )
        data = {
            "template_id": template.template_id,
            "name": template.name,
            "description": template.description,
            "definition": template.definition,
            "is_builtin": template.is_builtin,
            "created_at": (
                template.created_at.isoformat() if template.created_at else None
            ),
        }
        return _log(
            db,
            "template_detail",
            params,
            APIResponse(
                data=data,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "template_detail",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


@v2_router.post("/templates/{template_id}/run", response_model=APIResponse[dict])
def run_template_endpoint(
    template_id: str,
    request: TemplateRunRequest,
    db: SessionDep,
) -> APIResponse[dict]:
    """执行研究任务模板，按步骤分派到对应分析模块。"""
    started = perf_counter()
    params = {"template_id": template_id, "inputs": request.inputs}
    try:
        result = run_template(db, template_id, request.inputs)
        db.commit()
        return _log(
            db,
            "template_run",
            params,
            APIResponse(
                data=result.to_data(),
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=result.warnings or None,
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "template_run",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": TEMPLATE_NAME,
                    "algorithm_version": TEMPLATE_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )


# ============================================================
# P3.7: 研究看板
# ============================================================


@v2_router.get("/dashboard", response_model=APIResponse[dict])
def dashboard_endpoint(
    db: SessionDep,
    fund_codes: list[str] | None = Query(None, description="指定基金代码列表，留空则全部"),  # noqa: B008
) -> APIResponse[dict]:
    """研究看板 — 聚合今日变动、基金池提醒、算法告警、AI 告警和市场概览。

    每个面板独立 gather，单面板失败不影响其余面板，失败信息记入 warnings。
    """
    started = perf_counter()
    params: dict[str, Any] = {"fund_codes": fund_codes}
    try:
        data = generate_dashboard(db, fund_codes=fund_codes)
        return _log(
            db,
            "dashboard",
            params,
            APIResponse(
                data=data.to_data(),
                metadata={
                    "tool": DASHBOARD_NAME,
                    "algorithm_version": DASHBOARD_VERSION,
                    "platform_version": __version__,
                },
                warnings=data.warnings or None,
                conclusion_status=ConclusionStatus.COMPUTED,
            ),
            started,
        )
    except Exception as exc:
        db.rollback()
        return _log(
            db,
            "dashboard",
            params,
            APIResponse(
                data=None,
                metadata={
                    "tool": DASHBOARD_NAME,
                    "algorithm_version": DASHBOARD_VERSION,
                    "platform_version": __version__,
                },
                warnings=[str(exc)],
                conclusion_status=ConclusionStatus.NEEDS_REVIEW,
            ),
            started,
        )
