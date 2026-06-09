"""
Phase 2 v2 Tool API — experiment management and algorithm endpoints.

All endpoints follow the unified APIResponse[T] contract.
"""

from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research import __version__
from fund_research.api.deps import get_session
from fund_research.core.enums import ConclusionStatus
from fund_research.core.schemas import APIResponse
from fund_research.db.models import AlgorithmExperiment, ToolAPICallLog
from fund_research.experiments.manager import (
    create_experiment,
    delete_experiment,
    get_experiment_results,
    list_experiments,
    record_result,
    rerun_experiment,
)

v2_router = APIRouter(prefix="/api/v2", tags=["Tool API v2"])

SessionDep = Annotated[Session, Depends(get_session)]


def _log(db: Session, tool: str, params: dict, resp: APIResponse[dict], started: float) -> APIResponse[dict]:
    status = resp.conclusion_status.value if resp.conclusion_status else "unknown"
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
    return resp


# ============================================================
# Experiments
# ============================================================


@v2_router.get("/experiments")
def list_experiments_endpoint(
    db: SessionDep,
    algorithm_name: str | None = Query(None, description="按算法名过滤"),
) -> APIResponse[dict]:
    """列出所有实验。"""
    started = perf_counter()
    try:
        experiments = list_experiments(db, algorithm_name=algorithm_name)
        data = [{"id": e.id, "name": e.experiment_name, "algorithm": e.algorithm_name,
                  "version": e.algorithm_version, "status": e.status,
                  "fund_count": e.fund_count, "success_count": e.success_count,
                  "failure_count": e.failure_count, "created_at": e.created_at}
                 for e in experiments]
        return _log(db, "list_experiments", {"algorithm_name": algorithm_name},
                    APIResponse(data={"experiments": data, "total": len(data)},
                                metadata={"tool": "list_experiments", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        return _log(db, "list_experiments", {},
                    APIResponse(data=None, metadata={"tool": "list_experiments"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


@v2_router.post("/experiments")
def create_experiment_endpoint(
    db: SessionDep,
    body: dict | None = None,
) -> APIResponse[dict]:
    """创建实验。"""
    started = perf_counter()
    try:
        body = body or {}
        exp = create_experiment(
            db,
            experiment_name=body.get("experiment_name", "Untitled"),
            algorithm_name=body.get("algorithm_name", "unknown"),
            algorithm_version=body.get("algorithm_version", "0.1.0"),
            parameters=body.get("parameters", {}),
            sample_fund_codes=body.get("sample_fund_codes"),
            backtest_start=body.get("backtest_start"),
            backtest_end=body.get("backtest_end"),
        )
        return _log(db, "create_experiment", body,
                    APIResponse(data={"id": exp.id, "status": exp.status, "experiment_name": exp.experiment_name},
                                metadata={"tool": "create_experiment", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        return _log(db, "create_experiment", body or {},
                    APIResponse(data=None, metadata={"tool": "create_experiment"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


@v2_router.get("/experiments/{experiment_id}")
def get_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """获取实验详情和结果。"""
    started = perf_counter()
    exp = db.scalar(select(AlgorithmExperiment).where(AlgorithmExperiment.id == experiment_id))
    if not exp:
        return _log(db, "get_experiment", {"experiment_id": experiment_id},
                    APIResponse(data=None, metadata={"tool": "get_experiment"},
                                warnings=[f"实验 {experiment_id} 不存在"],
                                conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)

    results = get_experiment_results(db, experiment_id)
    return _log(db, "get_experiment", {"experiment_id": experiment_id},
                APIResponse(
                    data={
                        "id": exp.id, "experiment_name": exp.experiment_name,
                        "algorithm_name": exp.algorithm_name, "algorithm_version": exp.algorithm_version,
                        "parameters": exp.parameters, "status": exp.status,
                        "backtest_start": str(exp.backtest_start) if exp.backtest_start else None,
                        "backtest_end": str(exp.backtest_end) if exp.backtest_end else None,
                        "summary": exp.summary,
                        "results": [{"fund_code": r.fund_code, "calc_date": str(r.calc_date) if r.calc_date else None,
                                      "is_success": r.is_success, "metrics": r.metrics,
                                      "error_message": r.error_message} for r in results],
                    },
                    metadata={
                        "tool": "get_experiment",
                        "experiment_id": experiment_id,
                        "platform_version": __version__,
                    },
                    conclusion_status=ConclusionStatus.COMPUTED,
                ), started)


@v2_router.post("/experiments/{experiment_id}/rerun")
def rerun_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """重跑实验。"""
    started = perf_counter()
    try:
        exp = rerun_experiment(db, experiment_id)
        return _log(db, "rerun_experiment", {"experiment_id": experiment_id},
                    APIResponse(data={"id": exp.id, "status": exp.status},
                                metadata={"tool": "rerun_experiment", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except ValueError as e:
        return _log(db, "rerun_experiment", {"experiment_id": experiment_id},
                    APIResponse(data=None, metadata={"tool": "rerun_experiment"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


@v2_router.delete("/experiments/{experiment_id}")
def delete_experiment_endpoint(
    experiment_id: int,
    db: SessionDep,
) -> APIResponse[dict]:
    """删除实验。"""
    started = perf_counter()
    try:
        delete_experiment(db, experiment_id)
        return _log(db, "delete_experiment", {"experiment_id": experiment_id},
                    APIResponse(data={"id": experiment_id, "deleted": True},
                                metadata={"tool": "delete_experiment", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        return _log(db, "delete_experiment", {"experiment_id": experiment_id},
                    APIResponse(data=None, metadata={"tool": "delete_experiment"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


@v2_router.post("/experiments/{experiment_id}/results")
def record_experiment_result_endpoint(
    experiment_id: int,
    db: SessionDep,
    body: dict | None = None,
) -> APIResponse[dict]:
    """记录单个实验结果。"""
    started = perf_counter()
    try:
        body = body or {}
        result = record_result(
            db,
            experiment_id=experiment_id,
            fund_code=body.get("fund_code", ""),
            calc_date=body.get("calc_date"),
            is_success=body.get("is_success", True),
            metrics=body.get("metrics"),
            error_message=body.get("error_message"),
            warnings=body.get("warnings"),
        )
        return _log(db, "record_experiment_result", body,
                    APIResponse(data={"id": result.id, "fund_code": result.fund_code, "is_success": result.is_success},
                                metadata={"tool": "record_experiment_result", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        return _log(db, "record_experiment_result", body or {},
                    APIResponse(data=None, metadata={"tool": "record_experiment_result"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)
