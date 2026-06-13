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

DEFAULT_ATTRIBUTION_BENCHMARK_SYMBOL = "sh000300"
MIN_ATTRIBUTION_RETURN_OBSERVATIONS = 3
MIN_ATTRIBUTION_STOCK_WEIGHT_COVERAGE = 0.8


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
    params = exp.parameters or {}
    benchmark_symbol = str(
        params.get("benchmark_symbol") or DEFAULT_ATTRIBUTION_BENCHMARK_SYMBOL
    ).strip()
    min_observations = int(
        params.get("min_return_observations") or MIN_ATTRIBUTION_RETURN_OBSERVATIONS
    )
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
                    "bench_weight": (holding.weight_pct or 0.0) / 100.0,
                })

            holding_stock_df = pd.DataFrame(holding_stock_rows)
            for weight_column in ("port_weight", "bench_weight"):
                report_totals = holding_stock_df.groupby("report_date")[weight_column].transform("sum")
                holding_stock_df[weight_column] = (
                    holding_stock_df[weight_column] / report_totals.where(report_totals > 0, 1.0)
                )

            holdings_weight_df = holding_stock_df.groupby(
                ["report_date", "sector"],
                as_index=False,
            )[["port_weight", "bench_weight"]].sum()
            normalized_weight_sums = {
                str(report_date): round(float(weight_sum), 6)
                for report_date, weight_sum in holdings_weight_df.groupby("report_date")["port_weight"].sum().items()
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
                "uses_proxy_benchmark": False,
                "uses_proxy_sector_returns": False,
                "uses_proxy_benchmark_weights": True,
                "uses_real_benchmark_returns": True,
                "uses_real_sector_returns": True,
                "normalized_weight_sum_by_report": normalized_weight_sums,
                "min_stock_weight_coverage": min_weight_coverage,
                "return_observation_count_by_report": return_stats.get(
                    "return_observation_count_by_report", {}
                ),
            }
            is_success = len(attr_result.periods) > 0 and abs(attr_result.total_residual) < 0.05
            error_message = None if is_success else "归因残差偏高"
            warnings = [
                *attr_result.warnings,
                *return_warnings,
                "P2C 限制：基准行业权重暂用基金披露行业权重，尚未接入真实基准成分行业权重",
            ]

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
