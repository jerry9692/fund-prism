"""
Phase 2 v2 Tool API — experiment management and algorithm endpoints.

All endpoints follow the unified APIResponse[T] contract.
"""

from datetime import date
from time import perf_counter
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
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
    update_experiment_status,
)
from fund_research.experiments.readiness import assess_dynamic_attribution_readiness
from fund_research.experiments.runner import dispatch_run

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


class RecordExperimentResultRequest(BaseModel):
    fund_code: str
    calc_date: date
    is_success: bool = True
    metrics: dict[str, Any] | None = None
    error_message: str | None = None
    warnings: list[str] | None = None


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
