"""Experiment execution runners for Phase 2."""

from datetime import date as date_type

import numpy as np
import pandas as pd
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from fund_research.analysis.dynamic_attribution import run_attribution
from fund_research.analysis.nav_metrics import calculate_nav_metrics
from fund_research.analysis.scoring import score_funds
from fund_research.analysis.simulated_holding import backtest_disclosure, optimize_weights
from fund_research.db.models import (
    AlgorithmExperiment,
    BenchmarkIndustryWeight,
    FundDisclosedHoldings,
    FundMain,
    FundNAV,
    StockDaily,
)
from fund_research.db.models import (
    DynamicAttributionResult as DbDynamicAttributionResult,
)
from fund_research.db.models import (
    ScoringResult as DbScoringResult,
)
from fund_research.db.models import (
    SimulatedHoldingResult as DbSimulatedHoldingResult,
)
from fund_research.experiments.manager import record_result

DEFAULT_ATTRIBUTION_BENCHMARK_SYMBOL = "sh000300"
SIMULATION_METHOD_LAGGED_DISCLOSURE = "lagged_disclosure_baseline"
SIMULATION_METHOD_OPTIMIZED_TRACKING = "optimized_tracking"
SIMULATION_METHODS = {
    SIMULATION_METHOD_LAGGED_DISCLOSURE,
    SIMULATION_METHOD_OPTIMIZED_TRACKING,
}
BENCHMARK_TEXT_SYMBOL_MAP = (
    ("沪深300", "sh000300"),
    ("中证500", "sh000905"),
    ("中证1000", "sh000852"),
)
MIN_ATTRIBUTION_RETURN_OBSERVATIONS = 3
MIN_ATTRIBUTION_STOCK_WEIGHT_COVERAGE = 0.8
MIN_ATTRIBUTION_BENCHMARK_WEIGHT_COVERAGE = 95.0
WARN_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS = 120
MAX_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS = 180


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
    params = exp.parameters or {}
    if params.get("validation_mode") == "disclosure_period":
        return _run_simulated_holding_disclosure_backtest_batch(db, exp, fund_codes)

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
            _persist_simulated_holding_result(
                db,
                exp,
                fund_code=fund_code,
                sim_result=sim_result,
                metrics=metrics,
                warning_messages=warnings,
                raw_holding_count=len(raw_holding_weights),
                is_success=is_success,
            )

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


def _run_simulated_holding_disclosure_backtest_batch(
    db: Session,
    exp: AlgorithmExperiment,
    fund_codes: list[str],
) -> list[dict]:
    """Run out-of-sample disclosure-period simulated holding backtests."""
    params = exp.parameters or {}
    min_return_observations = int(params.get("min_return_observations") or 20)
    min_validation_pairs = int(params.get("min_validation_pairs") or 1)
    min_stock_weight_coverage = float(params.get("min_stock_weight_coverage") or 0.8)
    max_tracking_error = float(params.get("max_tracking_error") or 0.10)
    min_top10_recall = float(params.get("min_top10_recall") or 0.30)
    results: list[dict] = []
    simulation_method = str(
        params.get("simulation_method") or SIMULATION_METHOD_LAGGED_DISCLOSURE
    )
    if simulation_method not in SIMULATION_METHODS:
        for fund_code in fund_codes:
            error = f"不支持的 simulation_method: {simulation_method}"
            _record_failure(db, exp.id, fund_code, error)
            results.append(_failure_result(fund_code, error))
        return results
    max_positions = int(params.get("max_positions") or 30)
    max_single_weight = float(params.get("max_single_weight") or 0.10)
    turnover_penalty = float(params.get("turnover_penalty") or 0.0)
    industry_penalty = float(params.get("industry_penalty") or 0.0)
    use_cvxpy = bool(params.get("use_cvxpy", True))
    exact_report_dates, min_report_date, max_report_date = _resolve_report_date_filters(params)

    for fund_code in fund_codes:
        try:
            nav_rows = db.scalars(
                sa_select(FundNAV)
                .where(FundNAV.fund_code == fund_code)
                .order_by(FundNAV.trade_date)
            ).all()
            holdings_rows = db.scalars(
                sa_select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fund_code)
                .where(FundDisclosedHoldings.asset_type == "股票")
                .where(FundDisclosedHoldings.security_code.is_not(None))
                .order_by(FundDisclosedHoldings.report_date, FundDisclosedHoldings.rank_in_holdings)
            ).all()
            if not nav_rows:
                _record_failure(db, exp.id, fund_code, "无净值数据")
                results.append(_failure_result(fund_code, "无净值数据"))
                continue
            if not holdings_rows:
                _record_failure(db, exp.id, fund_code, "无股票持仓数据")
                results.append(_failure_result(fund_code, "无股票持仓数据"))
                continue

            nav_df = _nav_rows_to_return_df(nav_rows)
            report_dates = sorted({row.report_date for row in holdings_rows if row.report_date})
            stock_codes = {str(row.security_code) for row in holdings_rows if row.security_code}
            stock_rows = db.scalars(
                sa_select(StockDaily)
                .where(StockDaily.stock_code.in_(stock_codes))
                .order_by(StockDaily.stock_code, StockDaily.trade_date)
            ).all()
            stock_df = _market_rows_to_return_df(stock_rows)
            if stock_df.empty:
                _record_failure(db, exp.id, fund_code, "无持仓股票行情数据")
                results.append(_failure_result(fund_code, "无持仓股票行情数据"))
                continue

            periods = []
            disclosed_dict: dict[str, dict[str, float]] = {}
            industry_dict: dict[str, dict[str, str]] = {}
            pair_details: list[dict] = []
            warnings: list[str] = []
            tracking_errors: list[float] = []

            for previous_report, validation_report in zip(report_dates, report_dates[1:], strict=False):
                if exact_report_dates and validation_report not in exact_report_dates:
                    continue
                if min_report_date is not None and validation_report < min_report_date:
                    continue
                if max_report_date is not None and validation_report > max_report_date:
                    continue

                previous_holdings = [
                    row for row in holdings_rows if row.report_date == previous_report
                ]
                validation_holdings = [
                    row for row in holdings_rows if row.report_date == validation_report
                ]
                if not previous_holdings or not validation_holdings:
                    continue

                estimated_weights = _normalized_holding_weights(previous_holdings)
                validation_weights = _normalized_holding_weights(validation_holdings)
                if not estimated_weights or not validation_weights:
                    continue

                period_result, pair_stats = _build_disclosure_backtest_period(
                    fund_code=fund_code,
                    previous_report=previous_report,
                    validation_report=validation_report,
                    previous_holdings=previous_holdings,
                    validation_holdings=validation_holdings,
                    nav_df=nav_df,
                    stock_df=stock_df,
                    estimated_weights=estimated_weights,
                    simulation_method=simulation_method,
                    min_return_observations=min_return_observations,
                    max_positions=max_positions,
                    max_single_weight=max_single_weight,
                    turnover_penalty=turnover_penalty,
                    industry_penalty=industry_penalty,
                    use_cvxpy=use_cvxpy,
                )
                periods.append(period_result)
                tracking_errors.append(period_result.tracking_error)
                pair_details.append(pair_stats)
                disclosed_dict[str(validation_report)] = {
                    stock_code: weight * 100.0
                    for stock_code, weight in validation_weights.items()
                }
                industry_dict[str(validation_report)] = {
                    str(row.security_code): row.industry
                    for row in validation_holdings
                    if row.security_code and isinstance(row.industry, str)
                }

            sim_result = type("_R", (), {
                "periods": periods,
                "overall_tracking_error": float(np.mean(tracking_errors)) if tracking_errors else 0.0,
                "warnings": warnings,
                "confidence": "low",
            })()
            backtest = (
                backtest_disclosure(periods, disclosed_dict, industry_dict)
                if disclosed_dict
                else {"detail": [], "top10_recall": None, "industry_correlation": None, "warnings": []}
            )
            detail_by_date = {
                row.get("calc_date"): row
                for row in backtest.get("detail", [])
                if isinstance(row, dict)
            }
            enriched_detail = []
            for pair in pair_details:
                item = {**pair, **detail_by_date.get(pair["validation_report_date"], {})}
                enriched_detail.append(item)

            min_stock_coverage = min(
                (pair["stock_return_weight_coverage"] for pair in pair_details),
                default=0.0,
            )
            min_return_samples = min(
                (pair["return_sample_count"] for pair in pair_details),
                default=0,
            )
            metrics = {
                "validation_mode": "disclosure_period",
                "simulation_method": simulation_method,
                "estimated_overall_tracking_error": sim_result.overall_tracking_error,
                "estimated_overall_top10_recall": backtest.get("top10_recall"),
                "estimated_overall_industry_correlation": backtest.get("industry_correlation"),
                "period_count": len(periods),
                "validation_pair_count": len(pair_details),
                "min_stock_return_weight_coverage": round(min_stock_coverage, 6),
                "min_return_sample_count": min_return_samples,
                "backtest_detail": enriched_detail,
                "report_date_filter": _report_date_filter_metadata(
                    exact_report_dates,
                    min_report_date,
                    max_report_date,
                ),
            }

            failure_reasons = []
            if len(pair_details) < min_validation_pairs:
                failure_reasons.append(f"可回测披露期不足: {len(pair_details)}/{min_validation_pairs}")
            if min_stock_coverage < min_stock_weight_coverage:
                failure_reasons.append(f"股票收益覆盖不足: {min_stock_coverage:.1%}")
            if min_return_samples < min_return_observations:
                failure_reasons.append(f"收益样本不足: {min_return_samples}/{min_return_observations}")
            if sim_result.overall_tracking_error >= max_tracking_error:
                failure_reasons.append(f"跟踪误差偏高 TE={sim_result.overall_tracking_error:.4f}")
            recall = backtest.get("top10_recall")
            if recall is None or float(recall) < min_top10_recall:
                failure_reasons.append(f"重仓召回率不足: {recall}")

            is_success = not failure_reasons
            warning_messages = [
                *warnings,
                *backtest.get("warnings", []),
                *failure_reasons,
            ]
            _persist_simulated_holding_result(
                db,
                exp,
                fund_code=fund_code,
                sim_result=sim_result,
                metrics=metrics,
                warning_messages=[] if is_success else warning_messages,
                raw_holding_count=max(
                    (pair["estimated_holding_count"] for pair in pair_details),
                    default=0,
                ),
                is_success=is_success,
            )
            record_result(
                db,
                experiment_id=exp.id,
                fund_code=fund_code,
                calc_date=date_type.today(),
                is_success=is_success,
                metrics=metrics,
                error_message="; ".join(failure_reasons) if failure_reasons else None,
                warnings=[] if is_success else warning_messages,
            )
            results.append({
                "fund_code": fund_code,
                "is_success": is_success,
                "error_message": "; ".join(failure_reasons) if failure_reasons else None,
                "warnings": [] if is_success else warning_messages,
            })

        except Exception as exc:
            _safe_record_exception(db, exp.id, fund_code, exc)
            results.append(_failure_result(fund_code, str(exc)[:500]))

    return results


def _nav_rows_to_return_df(rows: list[FundNAV]) -> pd.DataFrame:
    data = pd.DataFrame([
        {
            "trade_date": row.trade_date,
            "unit_nav": row.unit_nav,
            "daily_return": row.daily_return,
        }
        for row in rows
    ])
    if data.empty:
        return pd.DataFrame(columns=["trade_date", "daily_return"])
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values("trade_date")
    if "daily_return" not in data.columns or data["daily_return"].isna().all():
        data["daily_return"] = pd.to_numeric(data["unit_nav"], errors="coerce").pct_change()
    else:
        missing = data["daily_return"].isna()
        if missing.any():
            inferred = pd.to_numeric(data["unit_nav"], errors="coerce").pct_change()
            data.loc[missing, "daily_return"] = inferred.loc[missing]
    data["daily_return"] = pd.to_numeric(data["daily_return"], errors="coerce")
    return data[["trade_date", "daily_return"]].dropna()


def _normalized_holding_weights(rows: list[FundDisclosedHoldings]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in rows:
        if not row.security_code:
            continue
        stock_code = str(row.security_code)
        weights[stock_code] = weights.get(stock_code, 0.0) + float(row.weight_pct or 0.0)
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {stock_code: weight / total for stock_code, weight in weights.items()}


def _build_disclosure_backtest_period(
    *,
    fund_code: str,
    previous_report: date_type,
    validation_report: date_type,
    previous_holdings: list[FundDisclosedHoldings],
    validation_holdings: list[FundDisclosedHoldings],
    nav_df: pd.DataFrame,
    stock_df: pd.DataFrame,
    estimated_weights: dict[str, float],
    simulation_method: str = SIMULATION_METHOD_LAGGED_DISCLOSURE,
    min_return_observations: int = 20,
    max_positions: int = 30,
    max_single_weight: float = 0.10,
    turnover_penalty: float = 0.0,
    industry_penalty: float = 0.0,
    use_cvxpy: bool = True,
):
    del fund_code
    industry_map = {
        str(row.security_code): row.industry
        for row in previous_holdings
        if row.security_code and isinstance(row.industry, str)
    }
    validation_codes = {
        str(row.security_code)
        for row in validation_holdings
        if row.security_code
    }
    window_stock_df = stock_df[
        (stock_df["trade_date"] >= pd.Timestamp(previous_report))
        & (stock_df["trade_date"] < pd.Timestamp(validation_report))
    ]
    window_nav_df = nav_df[
        (nav_df["trade_date"] >= pd.Timestamp(previous_report))
        & (nav_df["trade_date"] < pd.Timestamp(validation_report))
    ]
    stock_pivot = window_stock_df.pivot_table(
        index="trade_date",
        columns="stock_code",
        values="daily_return",
        aggfunc="last",
    )
    if simulation_method == SIMULATION_METHOD_OPTIMIZED_TRACKING:
        (
            modeled_weights,
            available_weight,
            sample_count,
            tracking_error,
            objective_value,
            method_stats,
        ) = _optimize_tracking_disclosure_weights(
            stock_pivot=stock_pivot,
            window_nav_df=window_nav_df,
            estimated_weights=estimated_weights,
            industry_map=industry_map,
            min_return_observations=min_return_observations,
            max_positions=max_positions,
            max_single_weight=max_single_weight,
            turnover_penalty=turnover_penalty,
            industry_penalty=industry_penalty,
            use_cvxpy=use_cvxpy,
        )
        confidence = "medium"
    else:
        modeled_weights = estimated_weights
        available_weight, sample_count, tracking_error = _tracking_error_for_weights(
            stock_pivot=stock_pivot,
            window_nav_df=window_nav_df,
            weights=modeled_weights,
        )
        objective_value = 0.0
        method_stats = {}
        confidence = "low"

    holding_list = [
        {
            "stock_code": stock_code,
            "stock_name": stock_code,
            "estimated_weight": float(weight),
            "industry": industry_map.get(stock_code),
            "confidence": confidence,
        }
        for stock_code, weight in sorted(
            modeled_weights.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    pair_stats = {
        "previous_report_date": str(previous_report),
        "validation_report_date": str(validation_report),
        "simulation_method": simulation_method,
        "estimated_holding_count": len(modeled_weights),
        "validation_holding_count": len(validation_codes),
        "common_holding_count": len(set(modeled_weights) & validation_codes),
        "stock_return_weight_coverage": round(float(available_weight), 6),
        "return_sample_count": sample_count,
        "estimated_tracking_error": round(tracking_error, 6),
        **method_stats,
    }
    period_result = type("_P", (), {
        "calc_date": validation_report,
        "holdings": holding_list,
        "stock_weight_pct": 100.0,
        "bond_weight_pct": 0.0,
        "cash_weight_pct": 0.0,
        "tracking_error": tracking_error,
        "objective_value": objective_value,
        "warnings": [],
    })()
    return period_result, pair_stats


def _tracking_error_for_weights(
    *,
    stock_pivot: pd.DataFrame,
    window_nav_df: pd.DataFrame,
    weights: dict[str, float],
) -> tuple[float, int, float]:
    common_codes = [stock_code for stock_code in weights if stock_code in stock_pivot.columns]
    available_weight = sum(weights[stock_code] for stock_code in common_codes)
    if not common_codes or available_weight <= 0 or window_nav_df.empty:
        return float(available_weight), 0, 0.0

    weight_vector = pd.Series(
        {stock_code: weights[stock_code] / available_weight for stock_code in common_codes},
        dtype=float,
    )
    portfolio_returns = (stock_pivot[common_codes] * weight_vector).sum(axis=1)
    nav_returns = window_nav_df.set_index("trade_date")["daily_return"]
    merged_returns = pd.DataFrame({
        "port": portfolio_returns,
        "fund": nav_returns,
    }).dropna()
    sample_count = len(merged_returns)
    if sample_count == 0:
        return float(available_weight), 0, 0.0
    tracking_error = float(
        np.sqrt(np.mean((merged_returns["port"] - merged_returns["fund"]) ** 2))
    )
    return float(available_weight), sample_count, tracking_error


def _optimize_tracking_disclosure_weights(
    *,
    stock_pivot: pd.DataFrame,
    window_nav_df: pd.DataFrame,
    estimated_weights: dict[str, float],
    industry_map: dict[str, str],
    min_return_observations: int,
    max_positions: int,
    max_single_weight: float,
    turnover_penalty: float,
    industry_penalty: float,
    use_cvxpy: bool,
) -> tuple[dict[str, float], float, int, float, float, dict]:
    candidate_codes = [
        stock_code for stock_code in estimated_weights if stock_code in stock_pivot.columns
    ]
    if len(candidate_codes) < 2 or window_nav_df.empty:
        raise ValueError("优化模型候选股票或基金收益数据不足")

    candidate_returns = stock_pivot[candidate_codes].copy()
    candidate_returns = candidate_returns.dropna(axis=1, thresh=min_return_observations)
    candidate_codes = list(candidate_returns.columns)
    if len(candidate_codes) < 2:
        raise ValueError("优化模型候选股票收益样本不足")

    nav_returns = window_nav_df.set_index("trade_date")["daily_return"].rename("fund")
    merged_returns = candidate_returns.join(nav_returns, how="inner").dropna(subset=["fund"])
    candidate_returns = merged_returns[candidate_codes].dropna(axis=1, thresh=min_return_observations)
    candidate_codes = list(candidate_returns.columns)
    if len(candidate_codes) < 2:
        raise ValueError("优化模型对齐后的候选股票收益样本不足")

    merged_returns = pd.concat(
        [candidate_returns, merged_returns["fund"]],
        axis=1,
    )
    sample_count = len(merged_returns)
    if sample_count < min_return_observations:
        raise ValueError(f"优化模型收益样本不足: {sample_count}/{min_return_observations}")

    available_weight = sum(estimated_weights[stock_code] for stock_code in candidate_codes)
    if available_weight <= 0:
        raise ValueError("优化模型候选股票上一期披露权重为 0")

    position_count = max(1, min(max_positions, len(candidate_codes)))
    effective_max_single_weight = max(max_single_weight, 1.0 / position_count)
    prev_weights = np.array(
        [estimated_weights[stock_code] / available_weight for stock_code in candidate_codes],
        dtype=float,
    )
    industry_groups = None
    disclosed_industry_weights = None
    if industry_penalty > 0:
        labels = [industry_map.get(stock_code) or "_unknown" for stock_code in candidate_codes]
        label_to_id = {label: idx for idx, label in enumerate(sorted(set(labels)))}
        industry_groups = [label_to_id[label] for label in labels]
        disclosed_industry_weights = {}
        for group, weight in zip(industry_groups, prev_weights, strict=False):
            disclosed_industry_weights[group] = disclosed_industry_weights.get(group, 0.0) + float(weight)

    optimized_array, objective_value = optimize_weights(
        merged_returns[candidate_codes].fillna(0.0).to_numpy(dtype=float).T,
        merged_returns["fund"].to_numpy(dtype=float),
        max_positions=max_positions,
        max_single_weight=effective_max_single_weight,
        turnover_penalty=turnover_penalty,
        prev_weights=prev_weights,
        industry_groups=industry_groups,
        disclosed_industry_weights=disclosed_industry_weights,
        industry_penalty=industry_penalty,
        use_cvxpy=use_cvxpy,
    )
    optimized_array = np.nan_to_num(np.maximum(optimized_array, 0.0), nan=0.0)
    if optimized_array.sum() <= 0:
        raise ValueError("优化模型未产出有效权重")
    optimized_array = optimized_array / optimized_array.sum()
    modeled_weights = {
        stock_code: float(weight)
        for stock_code, weight in zip(candidate_codes, optimized_array, strict=False)
        if float(weight) > 1e-8
    }
    portfolio_returns = merged_returns[candidate_codes].fillna(0.0).to_numpy(dtype=float) @ optimized_array
    tracking_error = float(
        np.sqrt(np.mean((portfolio_returns - merged_returns["fund"].to_numpy(dtype=float)) ** 2))
    )
    method_stats = {
        "optimization_candidate_count": len(candidate_codes),
        "optimization_objective_value": round(float(objective_value), 10),
        "optimization_max_single_weight": round(float(effective_max_single_weight), 6),
        "optimization_use_cvxpy_requested": bool(use_cvxpy),
    }
    return (
        modeled_weights,
        float(available_weight),
        sample_count,
        tracking_error,
        float(objective_value),
        method_stats,
    )


def _run_dynamic_attribution_batch(
    db: Session,
    exp: AlgorithmExperiment,
    fund_codes: list[str],
) -> list[dict]:
    """Run dynamic attribution experiments and persist per-fund results."""
    params = exp.parameters or {}
    min_observations = int(
        params.get("min_return_observations") or MIN_ATTRIBUTION_RETURN_OBSERVATIONS
    )
    max_snapshot_age_days = int(
        params.get("max_benchmark_weight_snapshot_age_days")
        or MAX_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS
    )
    warn_snapshot_age_days = int(
        params.get("warn_benchmark_weight_snapshot_age_days")
        or WARN_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS
    )
    results: list[dict] = []

    for fund_code in fund_codes:
        try:
            exact_report_dates, min_report_date, max_report_date = _resolve_report_date_filters(params)
            holdings_stmt = (
                sa_select(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == fund_code)
                .order_by(FundDisclosedHoldings.report_date)
            )
            if exact_report_dates:
                holdings_stmt = holdings_stmt.where(
                    FundDisclosedHoldings.report_date.in_(exact_report_dates)
                )
            if min_report_date is not None:
                holdings_stmt = holdings_stmt.where(FundDisclosedHoldings.report_date >= min_report_date)
            if max_report_date is not None:
                holdings_stmt = holdings_stmt.where(FundDisclosedHoldings.report_date <= max_report_date)
            holdings_rows = db.scalars(holdings_stmt).all()

            if not holdings_rows:
                error = "无符合报告期过滤条件的持仓数据" if _has_report_date_filter(params) else "无持仓数据"
                _record_failure(db, exp.id, fund_code, error)
                results.append(_failure_result(fund_code, error))
                continue

            stock_holdings = [
                holding
                for holding in holdings_rows
                if holding.asset_type == "股票" and holding.security_code
            ]
            if not stock_holdings:
                _record_failure(db, exp.id, fund_code, "无股票持仓数据")
                results.append(_failure_result(fund_code, "无股票持仓数据"))
                continue

            stock_codes = {str(holding.security_code) for holding in stock_holdings}
            benchmark_symbol, benchmark_source = _resolve_benchmark_symbol(db, fund_code, params)
            market_rows = db.scalars(
                sa_select(StockDaily)
                .where(StockDaily.stock_code.in_(stock_codes | {benchmark_symbol}))
                .order_by(StockDaily.stock_code, StockDaily.trade_date)
            ).all()
            market_df = _market_rows_to_return_df(market_rows)
            if market_df.empty:
                error = "无持仓股票或基准指数行情数据"
                _record_failure(db, exp.id, fund_code, error)
                results.append(_failure_result(fund_code, error))
                continue

            benchmark_returns = market_df[market_df["stock_code"] == benchmark_symbol]
            if benchmark_returns.empty:
                error = f"缺少基准指数行情: {benchmark_symbol}"
                _record_failure(db, exp.id, fund_code, error)
                results.append(_failure_result(fund_code, error))
                continue

            holding_stock_rows = []
            for holding in holdings_rows:
                if holding.asset_type != "股票" or not holding.security_code:
                    continue
                sector = holding.industry or "未分类"
                holding_stock_rows.append({
                    "report_date": holding.report_date,
                    "sector": sector,
                    "stock_code": str(holding.security_code),
                    "port_weight": (holding.weight_pct or 0.0) / 100.0,
                })

            holding_stock_df = pd.DataFrame(holding_stock_rows)
            report_totals = holding_stock_df.groupby("report_date")["port_weight"].transform("sum")
            holding_stock_df["port_weight"] = (
                holding_stock_df["port_weight"] / report_totals.where(report_totals > 0, 1.0)
            )

            port_weight_df = holding_stock_df.groupby(
                ["report_date", "sector"],
                as_index=False,
            )[["port_weight"]].sum()
            normalized_weight_sums = {
                str(report_date): round(float(weight_sum), 6)
                for report_date, weight_sum in port_weight_df.groupby("report_date")["port_weight"].sum().items()
            }

            sector_return_df, return_stats, return_warnings = _build_real_sector_return_df(
                holding_stock_df,
                market_df,
                benchmark_symbol=benchmark_symbol,
                min_observations=min_observations,
            )
            if sector_return_df.empty:
                error = "真实行业/基准收益样本不足"
                warnings = return_warnings or ["未能从持仓股票行情和基准指数行情构造有效归因周期"]
                _record_failure(db, exp.id, fund_code, error, warnings=warnings)
                results.append(_failure_result(fund_code, error, warnings))
                continue

            min_weight_coverage = return_stats.get("min_stock_weight_coverage", 0.0)
            if min_weight_coverage < MIN_ATTRIBUTION_STOCK_WEIGHT_COVERAGE:
                error = f"持仓股票行情覆盖不足: {min_weight_coverage:.1%}"
                warnings = [
                    *return_warnings,
                    f"要求覆盖率 >= {MIN_ATTRIBUTION_STOCK_WEIGHT_COVERAGE:.0%}",
                ]
                _record_failure(db, exp.id, fund_code, error, warnings=warnings)
                results.append(_failure_result(fund_code, error, warnings))
                continue

            benchmark_weight_df, benchmark_weight_stats, benchmark_weight_warnings = (
                _build_benchmark_industry_weight_df(
                    db,
                    benchmark_symbol=benchmark_symbol,
                    report_dates=sorted(
                        pd.to_datetime(holding_stock_df["report_date"]).dt.date.unique()
                    ),
                    max_snapshot_age_days=max_snapshot_age_days,
                    warn_snapshot_age_days=warn_snapshot_age_days,
                )
            )
            if benchmark_weight_df.empty:
                error = f"缺少可用基准行业权重: {benchmark_symbol}"
                _record_failure(db, exp.id, fund_code, error, warnings=benchmark_weight_warnings)
                results.append(_failure_result(fund_code, error, benchmark_weight_warnings))
                continue
            if len(benchmark_weight_stats) < len(normalized_weight_sums):
                error = f"基准行业权重覆盖不足: {benchmark_symbol}"
                _record_failure(db, exp.id, fund_code, error, warnings=benchmark_weight_warnings)
                results.append(_failure_result(fund_code, error, benchmark_weight_warnings))
                continue

            holdings_weight_df = port_weight_df.merge(
                benchmark_weight_df,
                on=["report_date", "sector"],
                how="outer",
            ).fillna({"port_weight": 0.0, "bench_weight": 0.0})
            sector_return_df, benchmark_only_sector_counts = (
                _complete_benchmark_only_sector_returns(sector_return_df, benchmark_weight_df)
            )

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
                "benchmark_symbol": benchmark_symbol,
                "benchmark_source": benchmark_source,
                "uses_proxy_benchmark": False,
                "uses_proxy_sector_returns": False,
                "uses_proxy_benchmark_weights": False,
                "uses_real_benchmark_returns": True,
                "uses_real_sector_returns": True,
                "uses_real_benchmark_weights": True,
                "normalized_weight_sum_by_report": normalized_weight_sums,
                "min_stock_weight_coverage": min_weight_coverage,
                "return_observation_count_by_report": return_stats.get(
                    "return_observation_count_by_report", {}
                ),
                "benchmark_weight_snapshot_by_report": {
                    report_date: stats.get("snapshot_date")
                    for report_date, stats in benchmark_weight_stats.items()
                },
                "benchmark_weight_coverage_by_report": {
                    report_date: stats.get("coverage_pct")
                    for report_date, stats in benchmark_weight_stats.items()
                },
                "benchmark_weight_unmapped_pct_by_report": {
                    report_date: stats.get("unmapped_weight_pct")
                    for report_date, stats in benchmark_weight_stats.items()
                },
                "benchmark_weight_snapshot_age_days_by_report": {
                    report_date: stats.get("snapshot_age_days")
                    for report_date, stats in benchmark_weight_stats.items()
                },
                "benchmark_only_sector_count_by_report": benchmark_only_sector_counts,
                "report_date_filter": _report_date_filter_metadata(
                    exact_report_dates,
                    min_report_date,
                    max_report_date,
                ),
            }
            is_success = len(attr_result.periods) > 0 and abs(attr_result.total_residual) < 0.05
            error_message = None if is_success else "归因残差偏高"
            warnings = [
                *attr_result.warnings,
                *return_warnings,
                *benchmark_weight_warnings,
            ]
            _persist_dynamic_attribution_result(
                db,
                exp,
                fund_code=fund_code,
                attr_result=attr_result,
                metrics=metrics,
                warning_messages=warnings,
                is_success=is_success,
            )

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


def _build_benchmark_industry_weight_df(
    db: Session,
    *,
    benchmark_symbol: str,
    report_dates: list[date_type],
    max_snapshot_age_days: int = MAX_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS,
    warn_snapshot_age_days: int = WARN_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS,
) -> tuple[pd.DataFrame, dict[str, dict], list[str]]:
    """Build benchmark industry weights from latest available snapshots."""
    rows: list[dict] = []
    stats_by_report: dict[str, dict] = {}
    warnings: list[str] = []

    for report_date in report_dates:
        snapshot_date = db.scalar(
            sa_select(BenchmarkIndustryWeight.snapshot_date)
            .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
            .where(BenchmarkIndustryWeight.snapshot_date <= report_date)
            .where(BenchmarkIndustryWeight.classification_type == "SW")
            .where(BenchmarkIndustryWeight.classification_level == 1)
            .order_by(BenchmarkIndustryWeight.snapshot_date.desc())
            .limit(1)
        )
        if snapshot_date is None:
            warnings.append(f"{report_date} 缺少基准行业权重: {benchmark_symbol}")
            continue
        snapshot_age_days = (report_date - snapshot_date).days
        if snapshot_age_days > max_snapshot_age_days:
            warnings.append(
                f"{report_date} 基准行业权重快照过旧: {benchmark_symbol} "
                f"{snapshot_date} age={snapshot_age_days}d > {max_snapshot_age_days}d"
            )
            continue
        if snapshot_age_days > warn_snapshot_age_days:
            warnings.append(
                f"{report_date} 基准行业权重快照偏旧: {benchmark_symbol} "
                f"{snapshot_date} age={snapshot_age_days}d > {warn_snapshot_age_days}d"
            )

        weight_rows = db.scalars(
            sa_select(BenchmarkIndustryWeight)
            .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
            .where(BenchmarkIndustryWeight.snapshot_date == snapshot_date)
            .where(BenchmarkIndustryWeight.classification_type == "SW")
            .where(BenchmarkIndustryWeight.classification_level == 1)
            .order_by(BenchmarkIndustryWeight.industry_name)
        ).all()
        if not weight_rows:
            warnings.append(f"{report_date} 基准行业权重快照为空: {benchmark_symbol} {snapshot_date}")
            continue

        coverage_pct = min(
            float(row.coverage_pct)
            for row in weight_rows
            if row.coverage_pct is not None
        ) if any(row.coverage_pct is not None for row in weight_rows) else 0.0
        if coverage_pct < MIN_ATTRIBUTION_BENCHMARK_WEIGHT_COVERAGE:
            warnings.append(
                f"{report_date} 基准行业权重覆盖不足: {coverage_pct:.2f}% "
                f"< {MIN_ATTRIBUTION_BENCHMARK_WEIGHT_COVERAGE:.2f}%"
            )
            continue

        total_weight = sum(float(row.weight_pct or 0.0) for row in weight_rows)
        if total_weight <= 0:
            warnings.append(f"{report_date} 基准行业权重合计无效: {benchmark_symbol} {snapshot_date}")
            continue

        unmapped_weight_pct = max(
            (float(row.unmapped_weight_pct) for row in weight_rows if row.unmapped_weight_pct is not None),
            default=0.0,
        )
        report_key = str(report_date)
        stats_by_report[report_key] = {
            "snapshot_date": str(snapshot_date),
            "snapshot_age_days": snapshot_age_days,
            "coverage_pct": round(coverage_pct, 6),
            "unmapped_weight_pct": round(unmapped_weight_pct, 6),
            "raw_weight_sum_pct": round(total_weight, 6),
        }
        for row in weight_rows:
            rows.append({
                "report_date": report_date,
                "sector": row.industry_name,
                "bench_weight": float(row.weight_pct or 0.0) / total_weight,
            })

    return pd.DataFrame(rows), stats_by_report, warnings


def _complete_benchmark_only_sector_returns(
    sector_return_df: pd.DataFrame,
    benchmark_weight_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Add benchmark-only sectors so Brinson does not treat missing rb as zero."""
    if sector_return_df.empty or benchmark_weight_df.empty:
        return sector_return_df, {}

    completed_rows = sector_return_df.to_dict("records")
    counts_by_report: dict[str, int] = {}
    returns = sector_return_df.copy()
    weights = benchmark_weight_df.copy()
    returns["report_date"] = pd.to_datetime(returns["report_date"]).dt.date
    weights["report_date"] = pd.to_datetime(weights["report_date"]).dt.date

    for report_date, weight_period in weights.groupby("report_date"):
        return_period = returns[returns["report_date"] == report_date]
        if return_period.empty:
            continue

        missing_sectors = sorted(set(weight_period["sector"]) - set(return_period["sector"]))
        counts_by_report[str(report_date)] = len(missing_sectors)
        if not missing_sectors:
            continue

        benchmark_return = float(return_period["bench_return"].iloc[0])
        for sector in missing_sectors:
            completed_rows.append({
                "report_date": report_date,
                "sector": sector,
                "port_return": 0.0,
                "bench_return": benchmark_return,
                "sector_stock_weight_coverage": 0.0,
            })

    return pd.DataFrame(completed_rows), counts_by_report


def _resolve_benchmark_symbol(
    db: Session,
    fund_code: str,
    parameters: dict | None,
) -> tuple[str, str]:
    """Resolve dynamic attribution benchmark from explicit params or fund profile text."""
    configured = str((parameters or {}).get("benchmark_symbol") or "").strip()
    if configured:
        return configured, "parameter"

    fund = db.scalar(sa_select(FundMain).where(FundMain.fund_code == fund_code))
    benchmark_text = fund.benchmark if fund and fund.benchmark else ""
    for keyword, symbol in BENCHMARK_TEXT_SYMBOL_MAP:
        if keyword in benchmark_text:
            return symbol, f"fund_benchmark:{keyword}"

    return DEFAULT_ATTRIBUTION_BENCHMARK_SYMBOL, "default"


def _has_report_date_filter(parameters: dict | None) -> bool:
    params = parameters or {}
    return any(
        params.get(key)
        for key in ("report_date", "report_dates", "min_report_date", "max_report_date")
    )


def _resolve_report_date_filters(
    parameters: dict | None,
) -> tuple[set[date_type] | None, date_type | None, date_type | None]:
    """Resolve optional dynamic attribution report-date filters from experiment params."""
    params = parameters or {}
    exact_dates: set[date_type] = set()
    report_date = params.get("report_date")
    if report_date:
        exact_dates.add(_parse_report_date_param(report_date, "report_date"))

    report_dates = params.get("report_dates")
    if report_dates:
        if isinstance(report_dates, str):
            report_dates = [report_dates]
        for index, raw_date in enumerate(report_dates):
            exact_dates.add(_parse_report_date_param(raw_date, f"report_dates[{index}]"))

    min_report_date = (
        _parse_report_date_param(params.get("min_report_date"), "min_report_date")
        if params.get("min_report_date")
        else None
    )
    max_report_date = (
        _parse_report_date_param(params.get("max_report_date"), "max_report_date")
        if params.get("max_report_date")
        else None
    )
    return exact_dates or None, min_report_date, max_report_date


def _parse_report_date_param(value, field_name: str) -> date_type:
    if isinstance(value, date_type):
        return value
    if isinstance(value, str):
        try:
            return date_type.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} 必须是 YYYY-MM-DD: {value}") from exc
    raise ValueError(f"{field_name} 必须是 YYYY-MM-DD: {value}")


def _report_date_filter_metadata(
    exact_report_dates: set[date_type] | None,
    min_report_date: date_type | None,
    max_report_date: date_type | None,
) -> dict:
    return {
        "report_dates": sorted(str(report_date) for report_date in exact_report_dates or []),
        "min_report_date": str(min_report_date) if min_report_date else None,
        "max_report_date": str(max_report_date) if max_report_date else None,
    }


def _market_rows_to_return_df(rows: list[StockDaily]) -> pd.DataFrame:
    data = pd.DataFrame([
        {
            "trade_date": row.trade_date,
            "stock_code": row.stock_code,
            "close_price": row.close_price,
            "daily_return": row.daily_return,
        }
        for row in rows
    ])
    if data.empty:
        return pd.DataFrame(columns=["trade_date", "stock_code", "daily_return"])
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["stock_code", "trade_date"])
    if "daily_return" not in data.columns or data["daily_return"].isna().all():
        data["daily_return"] = (
            pd.to_numeric(data["close_price"], errors="coerce")
            .groupby(data["stock_code"])
            .pct_change()
        )
    else:
        missing = data["daily_return"].isna()
        if missing.any():
            inferred = (
                pd.to_numeric(data["close_price"], errors="coerce")
                .groupby(data["stock_code"])
                .pct_change()
            )
            data.loc[missing, "daily_return"] = inferred.loc[missing]
    data["daily_return"] = pd.to_numeric(data["daily_return"], errors="coerce")
    return data[["trade_date", "stock_code", "daily_return"]].dropna()


def _build_real_sector_return_df(
    holding_stock_df: pd.DataFrame,
    market_df: pd.DataFrame,
    *,
    benchmark_symbol: str,
    min_observations: int,
) -> tuple[pd.DataFrame, dict, list[str]]:
    return_rows: list[dict] = []
    warnings: list[str] = []
    coverage_by_report: dict[str, float] = {}
    observations_by_report: dict[str, int] = {}
    report_dates = sorted(pd.to_datetime(holding_stock_df["report_date"]).dt.date.unique())

    for index, report_date in enumerate(report_dates):
        period_start = pd.Timestamp(report_date)
        period_end = (
            pd.Timestamp(report_dates[index + 1])
            if index + 1 < len(report_dates)
            else period_start + pd.DateOffset(months=3)
        )
        period_market = market_df[
            (market_df["trade_date"] >= period_start)
            & (market_df["trade_date"] < period_end)
        ]
        period_benchmark = period_market[period_market["stock_code"] == benchmark_symbol]
        observations_by_report[str(report_date)] = int(len(period_benchmark))
        if len(period_benchmark) < min_observations:
            warnings.append(
                f"{report_date} 基准 {benchmark_symbol} 收益样本不足: {len(period_benchmark)}"
            )
            continue

        benchmark_return = _compound_returns(period_benchmark["daily_return"])
        period_holdings = holding_stock_df[holding_stock_df["report_date"] == report_date]
        stock_returns = {
            stock_code: _compound_returns(stock_frame["daily_return"])
            for stock_code, stock_frame in period_market[
                period_market["stock_code"].isin(period_holdings["stock_code"])
            ].groupby("stock_code")
            if len(stock_frame) >= min_observations
        }
        available_weight = float(
            period_holdings[
                period_holdings["stock_code"].isin(stock_returns)
            ]["port_weight"].sum()
        )
        coverage_by_report[str(report_date)] = round(available_weight, 6)
        if available_weight <= 0:
            warnings.append(f"{report_date} 持仓股票行情无有效收益样本")
            continue

        for sector, sector_holdings in period_holdings.groupby("sector"):
            usable = sector_holdings[sector_holdings["stock_code"].isin(stock_returns)]
            sector_weight = float(sector_holdings["port_weight"].sum())
            usable_weight = float(usable["port_weight"].sum())
            if usable.empty or usable_weight <= 0:
                warnings.append(f"{report_date} 行业 {sector} 缺少持仓股票收益样本")
                continue
            sector_return = sum(
                float(row["port_weight"]) / usable_weight * stock_returns[str(row["stock_code"])]
                for _idx, row in usable.iterrows()
            )
            return_rows.append({
                "report_date": report_date,
                "sector": sector,
                "port_return": sector_return,
                "bench_return": benchmark_return,
                "sector_stock_weight_coverage": round(usable_weight / sector_weight, 6)
                if sector_weight > 0
                else 0.0,
            })

    stats = {
        "min_stock_weight_coverage": min(coverage_by_report.values()) if coverage_by_report else 0.0,
        "stock_weight_coverage_by_report": coverage_by_report,
        "return_observation_count_by_report": observations_by_report,
    }
    return pd.DataFrame(return_rows), stats, warnings


def _compound_returns(returns) -> float:
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna()
    if values.empty:
        return 0.0
    return float((1.0 + values).prod() - 1.0)


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
                _persist_scoring_result(
                    db,
                    exp,
                    fund_score=fund_score,
                    scoring=scoring,
                    warning_messages=warnings,
                )
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


def _persist_simulated_holding_result(
    db: Session,
    exp: AlgorithmExperiment,
    *,
    fund_code: str,
    sim_result,
    metrics: dict,
    warning_messages: list[str],
    raw_holding_count: int,
    is_success: bool,
) -> None:
    """Persist simulated holding periods into the Phase 2 result table."""
    matched_count = int(metrics.get("matched_stock_count") or 0)
    input_coverage = (
        metrics.get("min_stock_return_weight_coverage")
        if metrics.get("validation_mode") == "disclosure_period"
        else None
    )
    input_coverage = (
        round(float(input_coverage), 6)
        if input_coverage is not None
        else (
            round(matched_count / raw_holding_count, 6)
            if raw_holding_count > 0
            else None
        )
    )
    conclusion_status = "estimated" if is_success else "needs_review"
    for period in sim_result.periods:
        db.add(DbSimulatedHoldingResult(
            fund_code=fund_code,
            calc_date=period.calc_date,
            algorithm_name=exp.algorithm_name,
            algorithm_version=exp.algorithm_version,
            parameters=exp.parameters or {},
            holdings_detail=period.holdings,
            tracking_error=period.tracking_error,
            daily_rmse=period.tracking_error,
            industry_correlation=metrics.get("estimated_overall_industry_correlation"),
            top10_recall=metrics.get("estimated_overall_top10_recall"),
            stock_weight_pct=period.stock_weight_pct,
            bond_weight_pct=period.bond_weight_pct,
            cash_weight_pct=period.cash_weight_pct,
            confidence=sim_result.confidence,
            conclusion_status=conclusion_status,
            is_backtest=True,
            backtest_report_date=period.calc_date,
            warnings=warning_messages or sim_result.warnings,
            input_coverage=input_coverage,
        ))


def _persist_dynamic_attribution_result(
    db: Session,
    exp: AlgorithmExperiment,
    *,
    fund_code: str,
    attr_result,
    metrics: dict,
    warning_messages: list[str],
    is_success: bool,
) -> None:
    """Persist Brinson attribution periods into the Phase 2 result table."""
    conclusion_status = "estimated" if is_success else "needs_review"
    for period in attr_result.periods:
        active_return = period.portfolio_return - period.benchmark_return
        residual_pct = (
            abs(period.residual) / abs(active_return)
            if abs(active_return) > 1e-12
            else None
        )
        db.add(DbDynamicAttributionResult(
            fund_code=fund_code,
            period_start=period.period_start,
            period_end=period.period_end,
            algorithm_name=exp.algorithm_name,
            algorithm_version=exp.algorithm_version,
            parameters=exp.parameters or {},
            total_return=period.portfolio_return,
            beta_return=period.benchmark_return,
            allocation_return=period.allocation_effect,
            sector_rotation_return=period.allocation_effect,
            stock_selection_return=period.selection_effect,
            convertible_bond_return=None,
            ipo_return=None,
            residual=period.residual,
            residual_pct=round(residual_pct, 6) if residual_pct is not None else None,
            detail={
                "method": attr_result.method,
                "benchmark_symbol": metrics.get("benchmark_symbol"),
                "benchmark_source": metrics.get("benchmark_source"),
                "sector_details": period.sector_details,
                "input_quality": {
                    "uses_real_benchmark_returns": metrics.get("uses_real_benchmark_returns"),
                    "uses_real_sector_returns": metrics.get("uses_real_sector_returns"),
                    "uses_real_benchmark_weights": metrics.get("uses_real_benchmark_weights"),
                    "min_stock_weight_coverage": metrics.get("min_stock_weight_coverage"),
                },
            },
            confidence=attr_result.confidence,
            conclusion_status=conclusion_status,
            warnings=warning_messages,
        ))


def _persist_scoring_result(
    db: Session,
    exp: AlgorithmExperiment,
    *,
    fund_score,
    scoring,
    warning_messages: list[str],
) -> None:
    """Persist a composite score into the Phase 2 scoring result table."""
    db.add(DbScoringResult(
        fund_code=fund_score.fund_code,
        calc_date=date_type.today(),
        score_version=scoring.score_version,
        algorithm_version=exp.algorithm_version,
        weight_config=scoring.weight_config,
        total_score=fund_score.total_score,
        sub_scores=fund_score.sub_scores,
        percentile_rank=fund_score.percentile_rank,
        deduction_reasons=fund_score.deduction_reasons,
        contains_estimated=fund_score.contains_estimated,
        confidence="low" if fund_score.contains_estimated else "medium",
        conclusion_status="needs_review" if fund_score.contains_estimated else "computed",
        warnings=warning_messages or scoring.warnings,
    ))


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
