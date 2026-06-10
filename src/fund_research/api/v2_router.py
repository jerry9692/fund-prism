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
    except Exception as e:
        db.rollback()
        resp.warnings.append(f"API 调用日志写入失败: {e}")
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
        data = [{"id": str(e.id), "name": e.experiment_name, "algorithm": e.algorithm_name,
                  "version": e.algorithm_version, "status": e.status,
                  "fund_count": e.fund_count, "success_count": e.success_count,
                  "failure_count": e.failure_count, "created_at": e.created_at}
                 for e in experiments]
        return _log(db, "list_experiments", {"algorithm_name": algorithm_name},
                    APIResponse(data={"experiments": data, "total": len(data)},
                                metadata={"tool": "list_experiments", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        db.rollback()
        return _log(db, "list_experiments", {},
                    APIResponse(data=None, metadata={"tool": "list_experiments"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


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
        return _log(db, "create_experiment", params,
                    APIResponse(data={"id": str(exp.id), "status": exp.status, "experiment_name": exp.experiment_name},
                                metadata={"tool": "create_experiment", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        db.rollback()
        return _log(db, "create_experiment", params,
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
                        "id": str(exp.id), "experiment_name": exp.experiment_name,
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
        return _log(db, "rerun_experiment", {"experiment_id": str(experiment_id)},
                    APIResponse(data={"id": str(exp.id), "status": exp.status},
                                metadata={"tool": "rerun_experiment", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except ValueError as e:
        db.rollback()
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
        return _log(db, "delete_experiment", {"experiment_id": str(experiment_id)},
                    APIResponse(data={"id": str(experiment_id), "deleted": True},
                                metadata={"tool": "delete_experiment", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        db.rollback()
        return _log(db, "delete_experiment", {"experiment_id": experiment_id},
                    APIResponse(data=None, metadata={"tool": "delete_experiment"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


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
            return _log(db, "record_experiment_result", params,
                        APIResponse(data=None, metadata={"tool": "record_experiment_result"},
                                    warnings=[f"实验 {experiment_id} 不存在"],
                                    conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)
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
        return _log(db, "record_experiment_result", params,
                    APIResponse(data={
                        "id": str(result.id),
                        "fund_code": result.fund_code,
                        "is_success": result.is_success,
                    },
                                metadata={"tool": "record_experiment_result", "platform_version": __version__},
                                conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        db.rollback()
        return _log(db, "record_experiment_result", params,
                    APIResponse(data=None, metadata={"tool": "record_experiment_result"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


# ============================================================
# Run experiment (P2B)
# ============================================================


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
        return _log(db, "run_experiment", params,
                    APIResponse(data=None, metadata={"tool": "run_experiment"},
                                warnings=[f"实验 {experiment_id} 不存在"],
                                conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)

    if exp.status == "running":
        return _log(db, "run_experiment", params,
                    APIResponse(data={"experiment_id": experiment_id, "status": "running"},
                                metadata={"tool": "run_experiment"},
                                warnings=["实验正在运行中"],
                                conclusion_status=ConclusionStatus.OBSERVATION), started)

    from fund_research.experiments.manager import update_experiment_status

    update_experiment_status(db, experiment_id, "running")

    try:
        results = _dispatch_run(db, exp)
        update_experiment_status(db, experiment_id, "completed", f"完成 {len(results)} 只基金")
        return _log(db, "run_experiment", params,
                    APIResponse(
                        data={"experiment_id": experiment_id, "status": "completed",
                              "fund_count": len(results), "success_count": sum(1 for r in results if r["is_success"]),
                              "failure_count": sum(1 for r in results if not r["is_success"])},
                        metadata={"tool": "run_experiment", "platform_version": __version__},
                        conclusion_status=ConclusionStatus.COMPUTED), started)
    except Exception as e:
        db.rollback()
        update_experiment_status(db, experiment_id, "failed", str(e)[:200])
        return _log(db, "run_experiment", params,
                    APIResponse(data=None, metadata={"tool": "run_experiment"},
                                warnings=[str(e)], conclusion_status=ConclusionStatus.NEEDS_REVIEW), started)


def _dispatch_run(db: Session, exp: AlgorithmExperiment) -> list[dict]:
    """根据实验的 algorithm_name 分发到对应的执行函数。"""
    algo = exp.algorithm_name
    sample_codes = exp.sample_fund_codes or []

    if algo == "simulated_holding":
        return _run_simulated_holding_batch(db, exp, sample_codes)
    elif algo == "dynamic_attribution":
        return _run_dynamic_attribution_batch(db, exp, sample_codes)
    elif algo == "scoring":
        return _run_scoring_batch(db, exp, sample_codes)
    else:
        return [{"fund_code": c, "is_success": False,
                 "error_message": f"未知算法: {algo}",
                 "warnings": []} for c in sample_codes]


def _run_simulated_holding_batch(db: Session, exp: AlgorithmExperiment, fund_codes: list[str]) -> list[dict]:
    """批量运行模拟持仓，记录结果和验收报告。"""
    from datetime import date as date_type

    import pandas as pd
    from sqlalchemy import select as sa_select

    from fund_research.analysis.simulated_holding import (
        backtest_disclosure,
        run_simulation,
    )
    from fund_research.db.models import FundDisclosedHoldings, FundNAV, StockDaily
    from fund_research.experiments.manager import record_result

    params = exp.parameters or {}
    max_positions = int(params.get("max_positions", 30))
    window_days = int(params.get("window_days", 60))
    results: list[dict] = []

    for fc in fund_codes:
        try:
            nav_rows = db.scalars(
                sa_select(FundNAV).where(FundNAV.fund_code == fc).order_by(FundNAV.trade_date)
            ).all()
            if not nav_rows:
                results.append({"fund_code": fc, "is_success": False,
                                "error_message": "无净值数据", "warnings": []})
                continue

            holdings_rows = db.scalars(
                sa_select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fc)
                .order_by(FundDisclosedHoldings.report_date)
            ).all()
            stock_rows = db.scalars(
                sa_select(StockDaily).order_by(StockDaily.stock_code, StockDaily.trade_date)
            ).all()

            nav_df = pd.DataFrame([{
                "trade_date": r.trade_date, "unit_nav": r.unit_nav,
                "accumulated_nav": r.accumulated_nav, "daily_return": r.daily_return,
            } for r in nav_rows])
            holdings_df = pd.DataFrame([{
                "report_date": r.report_date, "stock_code": r.security_code,
                "weight_pct": r.weight_pct, "industry": r.industry,
            } for r in holdings_rows]) if holdings_rows else pd.DataFrame()
            stock_df = pd.DataFrame([{
                "trade_date": r.trade_date, "stock_code": r.stock_code,
                "close_price": r.close_price, "daily_return": r.daily_return,
                "industry": None, "market_cap": None,
            } for r in stock_rows]) if stock_rows else pd.DataFrame()

            # Limit to overlapping date range
            if not nav_df.empty and not stock_df.empty:
                nav_min, nav_max = nav_df["trade_date"].min(), nav_df["trade_date"].max()
                stk_min, stk_max = stock_df["trade_date"].min(), stock_df["trade_date"].max()
                lo, hi = max(nav_min, stk_min), min(nav_max, stk_max)
                stock_df = stock_df[(stock_df["trade_date"] >= lo) & (stock_df["trade_date"] <= hi)]

            sim_result = run_simulation(
                fc, nav_df, stock_df, holdings_df,
                max_positions=max_positions,
                window_days=window_days,
                run_backtest=True,
            )

            disclosed_dict: dict[str, dict[str, float]] = {}
            for rp_date in holdings_df["report_date"].dropna().unique():
                rp = holdings_df[holdings_df["report_date"] == rp_date]
                disclosed_dict[str(rp_date)] = dict(
                    zip(rp["stock_code"], rp["weight_pct"], strict=False)
                )

            backtest = backtest_disclosure(sim_result.periods, disclosed_dict) if disclosed_dict else {}

            metrics = {
                "estimated_overall_tracking_error": sim_result.overall_tracking_error,
                "estimated_overall_top10_recall": backtest.get("top10_recall"),
                "estimated_overall_industry_correlation": backtest.get("industry_correlation"),
                "period_count": len(sim_result.periods),
                "backtest_detail": backtest.get("detail", []),
            }
            n_periods = len(sim_result.periods)
            te = sim_result.overall_tracking_error
            has_periods = n_periods > 0

            fail_reason = None
            if not has_periods:
                fail_reason = "无可用周期：股票行情与净值日期无重叠，或候选池不足（需拉取更完整股票数据）"
            elif te >= 0.10:
                fail_reason = f"跟踪误差偏高 TE={te:.4f}"
            is_success = fail_reason is None

            record_result(db, experiment_id=exp.id, fund_code=fc,
                          calc_date=date_type.today(), is_success=is_success,
                          metrics=metrics,
                          error_message=fail_reason,
                          warnings=sim_result.warnings if not is_success else [])

            results.append({"fund_code": fc, "is_success": is_success,
                            "error_message": fail_reason,
                            "warnings": sim_result.warnings if not is_success else []})

        except Exception as e:
            try:
                record_result(db, experiment_id=exp.id, fund_code=fc,
                              calc_date=date_type.today(), is_success=False,
                              error_message=str(e)[:500], warnings=[])
            except Exception:
                db.rollback()
            results.append({"fund_code": fc, "is_success": False,
                            "error_message": str(e)[:500], "warnings": []})

    return results


def _run_dynamic_attribution_batch(
    db: Session, exp: AlgorithmExperiment, fund_codes: list[str],
) -> list[dict]:
    """批量运行动态归因 (Brinson BHB)，记录结果。"""
    from datetime import date as date_type

    import pandas as pd
    from sqlalchemy import select as sa_select

    from fund_research.analysis.dynamic_attribution import run_attribution
    from fund_research.db.models import FundDisclosedHoldings, FundNAV
    from fund_research.experiments.manager import record_result

    results: list[dict] = []
    for fc in fund_codes:
        try:
            holdings_rows = db.scalars(
                sa_select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fc)
                .order_by(FundDisclosedHoldings.report_date)
            ).all()

            if not holdings_rows:
                results.append({"fund_code": fc, "is_success": False,
                                "error_message": "无持仓数据", "warnings": []})
                continue

            # Build sector weights from disclosed holdings' industry field
            hw_rows = []
            for h in holdings_rows:
                sector = h.industry or "未分类"
                hw_rows.append({
                    "report_date": h.report_date,
                    "sector": sector,
                    "port_weight": h.weight_pct or 0.0,
                    "bench_weight": h.weight_pct or 0.0,  # 无基准数据，暂用等权
                })

            hw_df = pd.DataFrame(hw_rows)
            # Group by report_date + sector
            hw_df = hw_df.groupby(["report_date", "sector"], as_index=False).sum()
            hw_df["bench_weight"] = hw_df["port_weight"]  # fallback

            # Sector returns: approximate from NAV + disclosed weights
            nav_rows = db.scalars(
                sa_select(FundNAV).where(FundNAV.fund_code == fc).order_by(FundNAV.trade_date)
            ).all()
            if nav_rows:
                nav_df = pd.DataFrame([{"trade_date": n.trade_date, "daily_return": n.daily_return} for n in nav_rows])
                nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"])
                nav_df = nav_df.dropna(subset=["daily_return"])
                # Use fund return as proxy for all sector returns (P2B approximation)
                sr_rows = []
                for rp_date in hw_df["report_date"].unique():
                    rp_dt = pd.Timestamp(rp_date)
                    next_dt = rp_dt + pd.DateOffset(months=3)
                    window = nav_df[(nav_df["trade_date"] >= rp_dt) & (nav_df["trade_date"] < next_dt)]
                    if window.empty:
                        continue
                    period_ret = (1 + window["daily_return"]).prod() - 1
                    for _, hw_row in hw_df[hw_df["report_date"] == rp_date].iterrows():
                        sr_rows.append({
                            "report_date": rp_date,
                            "sector": hw_row["sector"],
                            "port_return": period_ret,
                            "bench_return": period_ret * 0.9,  # benchmark proxy
                        })
                sr_df = pd.DataFrame(sr_rows) if sr_rows else pd.DataFrame()
            else:
                sr_df = pd.DataFrame()

            attr_result = run_attribution(fc, hw_df, sr_df, method="BHB")

            metrics = {
                "estimated_total_allocation_effect": attr_result.total_allocation_effect,
                "estimated_total_selection_effect": attr_result.total_selection_effect,
                "estimated_total_interaction_effect": attr_result.total_interaction_effect,
                "estimated_total_residual": attr_result.total_residual,
                "period_count": len(attr_result.periods),
                "method": "BHB",
            }
            is_success = len(attr_result.periods) > 0 and abs(attr_result.total_residual) < 0.05

            record_result(db, experiment_id=exp.id, fund_code=fc,
                          calc_date=date_type.today(), is_success=is_success,
                          metrics=metrics,
                          error_message=None if is_success else "归因残差偏高",
                          warnings=attr_result.warnings if not is_success else [])

            results.append({"fund_code": fc, "is_success": is_success,
                            "error_message": None if is_success else "归因残差偏高",
                            "warnings": attr_result.warnings})

        except Exception as e:
            try:
                record_result(db, experiment_id=exp.id, fund_code=fc,
                              calc_date=date_type.today(), is_success=False,
                              error_message=str(e)[:500], warnings=[])
            except Exception:
                db.rollback()
            results.append({"fund_code": fc, "is_success": False,
                            "error_message": str(e)[:500], "warnings": []})

    return results


def _run_scoring_batch(
    db: Session, exp: AlgorithmExperiment, fund_codes: list[str],
) -> list[dict]:
    """批量运行综合评分，记录结果。"""
    from datetime import date as date_type

    import pandas as pd
    from sqlalchemy import select as sa_select

    from fund_research.analysis.nav_metrics import calculate_nav_metrics
    from fund_research.analysis.scoring import score_funds
    from fund_research.db.models import FundNAV
    from fund_research.experiments.manager import record_result

    results: list[dict] = []
    metrics_rows = []
    fund_nav_map: dict[str, pd.DataFrame] = {}

    for fc in fund_codes:
        try:
            nav_rows = db.scalars(
                sa_select(FundNAV).where(FundNAV.fund_code == fc).order_by(FundNAV.trade_date)
            ).all()
            if not nav_rows:
                results.append({"fund_code": fc, "is_success": False,
                                "error_message": "无净值数据", "warnings": []})
                continue
            nav_df = pd.DataFrame([{
                "trade_date": n.trade_date, "unit_nav": n.unit_nav,
                "daily_return": n.daily_return,
            } for n in nav_rows])
            fund_nav_map[fc] = nav_df
            m = calculate_nav_metrics(nav_df)
            if not m.metrics:
                continue
            metrics_rows.append({
                "fund_code": fc,
                "return": m.metrics.get("annualized_return") or 0.0,
                "risk": -(abs(m.metrics.get("max_drawdown") or 0.0)),  # negate: higher=better
                "alpha": (m.metrics.get("annualized_return") or 0.0) * 0.3,
                "trading": 0.0,
                "style_stability": 0.7,
                "scale": 0.5,
                "team": 0.5,
                "holder": 0.5,
            })
        except Exception as e:
            results.append({"fund_code": fc, "is_success": False,
                            "error_message": str(e)[:500], "warnings": []})

    if metrics_rows:
        try:
            df = pd.DataFrame(metrics_rows)
            scoring = score_funds(
                df, preset="均衡型", category="混合型-偏股",
                contains_estimated={"trading", "alpha", "style_stability", "scale", "team", "holder"},
                allow_estimated=False,
            )
            for fs in scoring.fund_scores:
                is_success = fs.total_score > 0
                record_result(db, experiment_id=exp.id, fund_code=fs.fund_code,
                              calc_date=date_type.today(), is_success=is_success,
                              metrics={
                                  "estimated_total_score": fs.total_score,
                                  "estimated_sub_scores": fs.sub_scores,
                                  "estimated_percentile_rank": fs.percentile_rank,
                                  "estimated_deduction_reasons": fs.deduction_reasons,
                              },
                              warnings=scoring.warnings if not is_success else [])
                if not any(r["fund_code"] == fs.fund_code for r in results):
                    results.append({"fund_code": fs.fund_code, "is_success": is_success,
                                    "error_message": None,
                                    "warnings": scoring.warnings})
        except Exception as e:
            for r in results:
                if r.get("is_success", True):
                    r["is_success"] = False
                    r["error_message"] = str(e)[:500]

    return results
