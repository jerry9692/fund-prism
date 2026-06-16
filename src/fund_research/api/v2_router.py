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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.api.deps import get_session
from fund_research.config.settings import get_settings
from fund_research.core.enums import ConclusionStatus
from fund_research.core.schemas import APIResponse
from fund_research.db.models import (
    AlgorithmExperiment,
    FundNAV,
    ScoringBacktest as DbScoringBacktest,
    ScoringResult as DbScoringResult,
    ToolAPICallLog,
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
    min_funds_per_date: int = 5


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

        exp = create_experiment(
            db,
            experiment_name=body.experiment_name,
            algorithm_name="scoring",
            algorithm_version=body.algorithm_version,
            parameters={
                "preset": body.preset,
                "category": body.category,
                "min_funds_per_date": body.min_funds_per_date,
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
            .order_by(DbScoringBacktest.created_at.desc())
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
                    "ic_mean": backtest_row.ic_mean if backtest_row else None,
                    "ic_ir": backtest_row.ic_ir if backtest_row else None,
                    "monotonicity": backtest_row.monotonicity_check if backtest_row else None,
                    "group_results": backtest_row.group_results if backtest_row else None,
                },
                metadata={"tool": "scoring_backtest", "platform_version": __version__},
                conclusion_status=conclusion,
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
        run_id = f"0.1.0-{uuid4().hex[:8]}"
        exp = create_experiment(
            db,
            experiment_name=f"Scoring {run_id}",
            algorithm_name="scoring",
            algorithm_version="0.1.0",
            parameters={
                "preset": body.preset,
                "category": body.category,
                "weights": body.weights or {},
            },
            sample_fund_codes=body.fund_codes,
        )
        update_experiment_status(db, exp.id, "running")

        results = dispatch_run(db, exp)

        # Stamp the just-created ScoringResult rows with the unique run_id.
        scored_codes = {r["fund_code"] for r in results if r["is_success"]}
        if scored_codes:
            db.query(DbScoringResult).filter(
                DbScoringResult.fund_code.in_(scored_codes),
                DbScoringResult.score_version == "0.1.0",
            ).update({"score_version": run_id}, synchronize_session="fetch")
            db.commit()

        fund_count = len(results)
        success_count = sum(1 for r in results if r["is_success"])
        status = "completed" if success_count == fund_count else "completed_with_failures" if success_count > 0 else "failed"
        update_experiment_status(db, exp.id, status, f"评分完成: {success_count}/{fund_count}")

        fund_scores = [
            {
                "fund_code": fs.fund_code,
                "total_score": fs.total_score,
                "sub_scores": fs.sub_scores,
                "percentile_rank": fs.percentile_rank,
                "deduction_reasons": fs.deduction_reasons,
                "contains_estimated": fs.contains_estimated,
            }
            for fs in db.scalars(
                select(DbScoringResult).where(DbScoringResult.score_version == run_id)
            ).all()
        ]

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
                conclusion_status=ConclusionStatus.COMPUTED if success_count == fund_count else ConclusionStatus.OBSERVATION,
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
                "calc_date": str(row.calc_date) if row.calc_date else None,
            }
            for row in rows
        ]
        fund_scores.sort(key=lambda x: x["total_score"] or 0, reverse=True)

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
                conclusion_status=ConclusionStatus.COMPUTED,
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
