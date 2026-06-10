"""Experiment execution runners for Phase 2."""

from datetime import date as date_type

import numpy as np
import pandas as pd
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from fund_research.analysis.dynamic_attribution import run_attribution
from fund_research.analysis.nav_metrics import calculate_nav_metrics
from fund_research.analysis.scoring import score_funds
from fund_research.analysis.simulated_holding import backtest_disclosure
from fund_research.db.models import (
    AlgorithmExperiment,
    FundDisclosedHoldings,
    FundNAV,
    StockDaily,
)
from fund_research.experiments.manager import record_result


def dispatch_run(db: Session, exp: AlgorithmExperiment) -> list[dict]:
    """Dispatch an experiment to the matching algorithm runner."""
    algo = exp.algorithm_name
    sample_codes = exp.sample_fund_codes or []

    if algo == "simulated_holding":
        return _run_simulated_holding_batch(db, exp, sample_codes)
    if algo == "dynamic_attribution":
        return _run_dynamic_attribution_batch(db, exp, sample_codes)
    if algo == "scoring":
        return _run_scoring_batch(db, exp, sample_codes)

    results = []
    for code in sample_codes:
        error = f"未知算法: {algo}"
        record_result(
            db,
            experiment_id=exp.id,
            fund_code=code,
            calc_date=date_type.today(),
            is_success=False,
            error_message=error,
            warnings=[],
        )
        results.append({
            "fund_code": code,
            "is_success": False,
            "error_message": error,
            "warnings": [],
        })
    return results


def _run_simulated_holding_batch(
    db: Session,
    exp: AlgorithmExperiment,
    fund_codes: list[str],
) -> list[dict]:
    """Run simulated-holding experiments and persist per-fund results."""
    results: list[dict] = []

    for fund_code in fund_codes:
        try:
            nav_rows = db.scalars(
                sa_select(FundNAV)
                .where(FundNAV.fund_code == fund_code)
                .order_by(FundNAV.trade_date)
            ).all()
            if not nav_rows:
                _record_failure(db, exp.id, fund_code, "无净值数据")
                results.append(_failure_result(fund_code, "无净值数据"))
                continue

            holdings_rows = db.scalars(
                sa_select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fund_code)
                .order_by(FundDisclosedHoldings.report_date)
            ).all()
            stock_rows = db.scalars(
                sa_select(StockDaily).order_by(StockDaily.stock_code, StockDaily.trade_date)
            ).all()

            nav_df = pd.DataFrame([
                {
                    "trade_date": row.trade_date,
                    "unit_nav": row.unit_nav,
                    "accumulated_nav": row.accumulated_nav,
                    "daily_return": row.daily_return,
                }
                for row in nav_rows
            ])
            holdings_df = (
                pd.DataFrame([
                    {
                        "report_date": row.report_date,
                        "stock_code": row.security_code,
                        "weight_pct": row.weight_pct,
                        "industry": row.industry,
                    }
                    for row in holdings_rows
                ])
                if holdings_rows
                else pd.DataFrame()
            )
            stock_df = (
                pd.DataFrame([
                    {
                        "trade_date": row.trade_date,
                        "stock_code": row.stock_code,
                        "close_price": row.close_price,
                        "daily_return": row.daily_return,
                        "industry": None,
                        "market_cap": None,
                    }
                    for row in stock_rows
                ])
                if stock_rows
                else pd.DataFrame()
            )

            if holdings_df.empty:
                _record_failure(db, exp.id, fund_code, "无持仓数据")
                results.append(_failure_result(fund_code, "无持仓数据"))
                continue
            if stock_df.empty:
                _record_failure(db, exp.id, fund_code, "无股票行情数据")
                results.append(_failure_result(fund_code, "无股票行情数据"))
                continue

            if "daily_return" not in nav_df.columns or nav_df["daily_return"].isna().all():
                nav_df = nav_df.sort_values("trade_date")
                nav_df["daily_return"] = pd.to_numeric(
                    nav_df["unit_nav"], errors="coerce"
                ).pct_change()
            if "daily_return" not in stock_df.columns or stock_df["daily_return"].isna().all():
                stock_df = stock_df.sort_values(["stock_code", "trade_date"])
                stock_df["daily_return"] = (
                    pd.to_numeric(stock_df["close_price"], errors="coerce")
                    .groupby(stock_df["stock_code"])
                    .pct_change()
                )

            if not nav_df.empty and not stock_df.empty:
                nav_min, nav_max = nav_df["trade_date"].min(), nav_df["trade_date"].max()
                stock_min, stock_max = stock_df["trade_date"].min(), stock_df["trade_date"].max()
                lo, hi = max(nav_min, stock_min), min(nav_max, stock_max)
                stock_df = stock_df[
                    (stock_df["trade_date"] >= lo) & (stock_df["trade_date"] <= hi)
                ]

            latest_report = holdings_df["report_date"].max()
            latest_holdings = holdings_df[holdings_df["report_date"] == latest_report]
            raw_holding_weights = latest_holdings.groupby("stock_code")["weight_pct"].sum() / 100.0
            industry_map = {
                str(row["stock_code"]): row["industry"]
                for _idx, row in latest_holdings.iterrows()
                if isinstance(row.get("industry"), str)
            }
            stock_returns = stock_df.pivot_table(
                index="trade_date",
                columns="stock_code",
                values="daily_return",
                aggfunc="last",
            )
            common_codes = [code for code in raw_holding_weights.index if code in stock_returns.columns]
            sample_count = 0
            weight_vector = pd.Series(dtype=float)
            if common_codes:
                matched_weights = pd.Series(
                    {code: raw_holding_weights[code] for code in common_codes},
                    dtype=float,
                )
                weight_sum = float(matched_weights.sum())
                weight_vector = matched_weights / weight_sum if weight_sum > 0 else matched_weights
                portfolio_returns = (stock_returns[common_codes] * weight_vector).sum(axis=1)
                nav_returns = nav_df.set_index("trade_date")["daily_return"]
                merged_returns = pd.DataFrame({
                    "port": portfolio_returns,
                    "fund": nav_returns,
                }).dropna()
                sample_count = len(merged_returns)
                tracking_error = (
                    float(np.sqrt(np.mean((merged_returns["port"] - merged_returns["fund"]) ** 2)))
                    if sample_count > 20
                    else 0.0
                )
            else:
                tracking_error = 0.0

            holding_list = [
                {
                    "stock_code": code,
                    "stock_name": code,
                    "estimated_weight": float(weight_vector.get(code, 0.0)) if common_codes else 0.0,
                    "industry": industry_map.get(code),
                    "confidence": "low",
                }
                for code in common_codes
            ]
            sim_result = type("_R", (), {
                "periods": [
                    type("_P", (), {
                        "calc_date": latest_report,
                        "holdings": holding_list,
                        "stock_weight_pct": 100.0,
                        "bond_weight_pct": 0.0,
                        "cash_weight_pct": 0.0,
                        "tracking_error": tracking_error,
                        "objective_value": 0.0,
                        "warnings": [],
                    })
                ] if common_codes else [],
                "overall_tracking_error": tracking_error,
                "backtest_report": {},
                "warnings": (
                    [
                        "Naive replication: "
                        f"{len(common_codes)}/{len(raw_holding_weights)} codes, "
                        f"samples={sample_count}, TE={tracking_error:.4f}"
                    ]
                    if common_codes
                    else ["No matching stock codes"]
                ),
                "overall_industry_correlation": None,
                "overall_top10_recall": None,
                "confidence": "low" if tracking_error < 0.05 else "needs_review",
            })()

            disclosed_dict: dict[str, dict[str, float]] = {}
            industry_dict: dict[str, dict[str, str]] = {}
            for report_date in holdings_df["report_date"].dropna().unique():
                period_holdings = holdings_df[holdings_df["report_date"] == report_date]
                disclosed_dict[str(report_date)] = dict(
                    zip(period_holdings["stock_code"], period_holdings["weight_pct"], strict=False)
                )
                industry_dict[str(report_date)] = {
                    str(row["stock_code"]): row["industry"]
                    for _idx, row in period_holdings.iterrows()
                    if isinstance(row.get("industry"), str)
                }

            backtest = (
                backtest_disclosure(sim_result.periods, disclosed_dict, industry_dict)
                if disclosed_dict
                else {}
            )

            metrics = {
                "estimated_overall_tracking_error": sim_result.overall_tracking_error,
                "estimated_overall_top10_recall": backtest.get("top10_recall"),
                "estimated_overall_industry_correlation": backtest.get("industry_correlation"),
                "period_count": len(sim_result.periods),
                "matched_stock_count": len(common_codes),
                "return_sample_count": sample_count,
                "backtest_detail": backtest.get("detail", []),
            }

            failure_reason = None
            if not sim_result.periods:
                failure_reason = "无可用周期：股票行情与净值日期无重叠，或候选池不足（需拉取更完整股票数据）"
            elif sample_count <= 20:
                failure_reason = f"收益样本不足: {sample_count}"
            elif tracking_error >= 0.10:
                failure_reason = f"跟踪误差偏高 TE={tracking_error:.4f}"
            is_success = failure_reason is None
            warnings = sim_result.warnings if not is_success else []

            record_result(
                db,
                experiment_id=exp.id,
                fund_code=fund_code,
                calc_date=date_type.today(),
                is_success=is_success,
                metrics=metrics,
                error_message=failure_reason,
                warnings=warnings,
            )
            results.append({
                "fund_code": fund_code,
                "is_success": is_success,
                "error_message": failure_reason,
                "warnings": warnings,
            })

        except Exception as exc:
            _safe_record_exception(db, exp.id, fund_code, exc)
            results.append(_failure_result(fund_code, str(exc)[:500]))

    return results


def _run_dynamic_attribution_batch(
    db: Session,
    exp: AlgorithmExperiment,
    fund_codes: list[str],
) -> list[dict]:
    """Run dynamic attribution experiments and persist per-fund results."""
    proxy_warning = "P2B 近似：行业收益和基准收益使用基金收益代理，不能作为正式归因结论"
    results: list[dict] = []

    for fund_code in fund_codes:
        try:
            holdings_rows = db.scalars(
                sa_select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fund_code)
                .order_by(FundDisclosedHoldings.report_date)
            ).all()

            if not holdings_rows:
                _record_failure(db, exp.id, fund_code, "无持仓数据")
                results.append(_failure_result(fund_code, "无持仓数据"))
                continue

            weight_rows = []
            for holding in holdings_rows:
                sector = holding.industry or "未分类"
                weight_rows.append({
                    "report_date": holding.report_date,
                    "sector": sector,
                    "port_weight": (holding.weight_pct or 0.0) / 100.0,
                    "bench_weight": (holding.weight_pct or 0.0) / 100.0,
                })

            holdings_weight_df = pd.DataFrame(weight_rows)
            holdings_weight_df = holdings_weight_df.groupby(
                ["report_date", "sector"],
                as_index=False,
            ).sum()
            holdings_weight_df["bench_weight"] = holdings_weight_df["port_weight"]
            for weight_column in ("port_weight", "bench_weight"):
                report_totals = holdings_weight_df.groupby("report_date")[weight_column].transform("sum")
                holdings_weight_df[weight_column] = (
                    holdings_weight_df[weight_column] / report_totals.where(report_totals > 0, 1.0)
                )
            normalized_weight_sums = {
                str(report_date): round(float(weight_sum), 6)
                for report_date, weight_sum in holdings_weight_df.groupby("report_date")["port_weight"].sum().items()
            }

            nav_rows = db.scalars(
                sa_select(FundNAV)
                .where(FundNAV.fund_code == fund_code)
                .order_by(FundNAV.trade_date)
            ).all()
            if nav_rows:
                nav_df = pd.DataFrame([
                    {"trade_date": row.trade_date, "daily_return": row.daily_return}
                    for row in nav_rows
                ])
                nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"])
                nav_df = nav_df.dropna(subset=["daily_return"])
                return_rows = []
                for report_date in holdings_weight_df["report_date"].unique():
                    report_ts = pd.Timestamp(report_date)
                    next_ts = report_ts + pd.DateOffset(months=3)
                    window = nav_df[
                        (nav_df["trade_date"] >= report_ts)
                        & (nav_df["trade_date"] < next_ts)
                    ]
                    if window.empty:
                        continue
                    period_return = (1 + window["daily_return"]).prod() - 1
                    for _idx, weight_row in holdings_weight_df[
                        holdings_weight_df["report_date"] == report_date
                    ].iterrows():
                        return_rows.append({
                            "report_date": report_date,
                            "sector": weight_row["sector"],
                            "port_return": period_return,
                            "bench_return": period_return * 0.9,
                        })
                sector_return_df = pd.DataFrame(return_rows) if return_rows else pd.DataFrame()
            else:
                sector_return_df = pd.DataFrame()

            attr_result = run_attribution(
                fund_code,
                holdings_weight_df,
                sector_return_df,
                method="BHB",
            )

            metrics = {
                "estimated_total_portfolio_return": attr_result.total_portfolio_return,
                "estimated_total_benchmark_return": attr_result.total_benchmark_return,
                "estimated_total_allocation_effect": attr_result.total_allocation_effect,
                "estimated_total_selection_effect": attr_result.total_selection_effect,
                "estimated_total_interaction_effect": attr_result.total_interaction_effect,
                "estimated_total_residual": attr_result.total_residual,
                "period_count": len(attr_result.periods),
                "method": "BHB",
                "uses_proxy_benchmark": True,
                "uses_proxy_sector_returns": True,
                "normalized_weight_sum_by_report": normalized_weight_sums,
            }
            is_success = len(attr_result.periods) > 0 and abs(attr_result.total_residual) < 0.05
            error_message = None if is_success else "归因残差偏高"
            warnings = [*attr_result.warnings, proxy_warning]

            record_result(
                db,
                experiment_id=exp.id,
                fund_code=fund_code,
                calc_date=date_type.today(),
                is_success=is_success,
                metrics=metrics,
                error_message=error_message,
                warnings=warnings,
            )
            results.append({
                "fund_code": fund_code,
                "is_success": is_success,
                "error_message": error_message,
                "warnings": warnings,
            })

        except Exception as exc:
            _safe_record_exception(db, exp.id, fund_code, exc)
            results.append(_failure_result(fund_code, str(exc)[:500]))

    return results


def _run_scoring_batch(
    db: Session,
    exp: AlgorithmExperiment,
    fund_codes: list[str],
) -> list[dict]:
    """Run scoring experiments and persist per-fund results."""
    results: list[dict] = []
    metrics_rows = []

    for fund_code in fund_codes:
        try:
            nav_rows = db.scalars(
                sa_select(FundNAV)
                .where(FundNAV.fund_code == fund_code)
                .order_by(FundNAV.trade_date)
            ).all()
            if not nav_rows:
                _record_failure(db, exp.id, fund_code, "无净值数据")
                results.append(_failure_result(fund_code, "无净值数据"))
                continue

            nav_df = pd.DataFrame([
                {
                    "trade_date": row.trade_date,
                    "unit_nav": row.unit_nav,
                    "daily_return": row.daily_return,
                }
                for row in nav_rows
            ])
            nav_metrics = calculate_nav_metrics(nav_df)
            if not nav_metrics.metrics:
                _record_failure(db, exp.id, fund_code, "净值指标不足")
                results.append(_failure_result(fund_code, "净值指标不足"))
                continue

            metrics_rows.append({
                "fund_code": fund_code,
                "return": nav_metrics.metrics.get("annualized_return") or 0.0,
                "risk": -(abs(nav_metrics.metrics.get("max_drawdown") or 0.0)),
                "alpha": (nav_metrics.metrics.get("annualized_return") or 0.0) * 0.3,
                "trading": 0.0,
                "style_stability": 0.7,
                "scale": 0.5,
                "team": 0.5,
                "holder": 0.5,
            })
        except Exception as exc:
            _safe_record_exception(db, exp.id, fund_code, exc)
            results.append(_failure_result(fund_code, str(exc)[:500]))

    if metrics_rows:
        try:
            scoring = score_funds(
                pd.DataFrame(metrics_rows),
                preset="均衡型",
                category="混合型-偏股",
                contains_estimated={"trading", "alpha", "style_stability", "scale", "team", "holder"},
                allow_estimated=False,
            )
            for fund_score in scoring.fund_scores:
                is_success = fund_score.total_score > 0
                warnings = scoring.warnings if not is_success else []
                record_result(
                    db,
                    experiment_id=exp.id,
                    fund_code=fund_score.fund_code,
                    calc_date=date_type.today(),
                    is_success=is_success,
                    metrics={
                        "estimated_total_score": fund_score.total_score,
                        "estimated_sub_scores": fund_score.sub_scores,
                        "estimated_percentile_rank": fund_score.percentile_rank,
                        "estimated_deduction_reasons": fund_score.deduction_reasons,
                    },
                    warnings=warnings,
                )
                if not any(result["fund_code"] == fund_score.fund_code for result in results):
                    results.append({
                        "fund_code": fund_score.fund_code,
                        "is_success": is_success,
                        "error_message": None,
                        "warnings": scoring.warnings,
                    })
        except Exception as exc:
            error = str(exc)[:500]
            scored_codes = {row["fund_code"] for row in metrics_rows}
            for fund_code in scored_codes:
                if not any(result["fund_code"] == fund_code for result in results):
                    _safe_record_exception(db, exp.id, fund_code, exc)
                    results.append(_failure_result(fund_code, error))

    return results


def _record_failure(
    db: Session,
    experiment_id: int,
    fund_code: str,
    error_message: str,
    warnings: list[str] | None = None,
) -> None:
    record_result(
        db,
        experiment_id=experiment_id,
        fund_code=fund_code,
        calc_date=date_type.today(),
        is_success=False,
        error_message=error_message,
        warnings=warnings or [],
    )


def _safe_record_exception(
    db: Session,
    experiment_id: int,
    fund_code: str,
    exc: Exception,
) -> None:
    try:
        _record_failure(db, experiment_id, fund_code, str(exc)[:500])
    except Exception:
        db.rollback()


def _failure_result(
    fund_code: str,
    error_message: str,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "fund_code": fund_code,
        "is_success": False,
        "error_message": error_message,
        "warnings": warnings or [],
    }
