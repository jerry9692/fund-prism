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
from fund_research.db.models import AlgorithmExperiment, ToolAPICallLog
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
