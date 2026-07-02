"""Readiness checks for Phase 2 experiment inputs."""

from datetime import date as date_type

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    BenchmarkIndustryWeight,
    FundDisclosedHoldings,
    FundMain,
    FundNAV,
    StockDaily,
)
from fund_research.experiments.runner import (
    BENCHMARK_TEXT_SYMBOL_MAP,
    DEFAULT_ATTRIBUTION_BENCHMARK_SYMBOL,
    MAX_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS,
    MIN_ATTRIBUTION_BENCHMARK_WEIGHT_COVERAGE,
)

MIN_SIMULATED_HOLDING_VALIDATION_PAIRS = 1
MIN_SIMULATED_HOLDING_RETURN_OBSERVATIONS = 20
MIN_SIMULATED_HOLDING_STOCK_WEIGHT_COVERAGE = 0.6

MIN_READINESS_RETURN_OBSERVATIONS = 20
MIN_READINESS_STOCK_WEIGHT_COVERAGE = 0.6


def assess_simulated_holding_backtest_readiness(
    session: Session,
    fund_codes: set[str] | None = None,
    *,
    min_report_date: date_type | None = None,
    max_report_date: date_type | None = None,
    min_validation_pairs: int = MIN_SIMULATED_HOLDING_VALIDATION_PAIRS,
    min_return_observations: int = MIN_SIMULATED_HOLDING_RETURN_OBSERVATIONS,
    min_stock_weight_coverage: float = MIN_SIMULATED_HOLDING_STOCK_WEIGHT_COVERAGE,
    require_industry: bool = False,
    ready_only: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Assess whether funds can run disclosure-period simulated-holding backtests."""
    fund_stmt = (
        select(FundDisclosedHoldings.fund_code)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .where(FundDisclosedHoldings.security_code.is_not(None))
        .group_by(FundDisclosedHoldings.fund_code)
        .order_by(FundDisclosedHoldings.fund_code)
    )
    if fund_codes:
        fund_stmt = fund_stmt.where(FundDisclosedHoldings.fund_code.in_(fund_codes))

    rows = [
        _assess_simulated_holding_fund(
            session,
            fund_code=fund_code,
            min_report_date=min_report_date,
            max_report_date=max_report_date,
            min_validation_pairs=min_validation_pairs,
            min_return_observations=min_return_observations,
            min_stock_weight_coverage=min_stock_weight_coverage,
            require_industry=require_industry,
        )
        for (fund_code,) in session.execute(fund_stmt).all()
    ]
    rows.sort(key=lambda row: (0 if row["is_ready"] else 1, row["fund_code"]))
    if ready_only:
        rows = [row for row in rows if row["is_ready"]]
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


def _assess_simulated_holding_fund(
    session: Session,
    *,
    fund_code: str,
    min_report_date: date_type | None,
    max_report_date: date_type | None,
    min_validation_pairs: int,
    min_return_observations: int,
    min_stock_weight_coverage: float,
    require_industry: bool,
) -> dict:
    report_dates = list(session.scalars(
        select(FundDisclosedHoldings.report_date)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .where(FundDisclosedHoldings.security_code.is_not(None))
        .group_by(FundDisclosedHoldings.report_date)
        .order_by(FundDisclosedHoldings.report_date)
    ).all())
    pairs = []
    issues = []
    for previous_report, validation_report in zip(report_dates, report_dates[1:], strict=False):
        if min_report_date is not None and validation_report < min_report_date:
            continue
        if max_report_date is not None and validation_report > max_report_date:
            continue
        previous_holdings = _stock_holdings_for_report(session, fund_code, previous_report)
        validation_holdings = _stock_holdings_for_report(session, fund_code, validation_report)
        stock_coverage = _stock_return_weight_coverage_between(
            session,
            holdings=previous_holdings,
            start_date=previous_report,
            end_date=validation_report,
        )
        nav_observations = _nav_observation_count(
            session,
            fund_code=fund_code,
            start_date=previous_report,
            end_date=validation_report,
        )
        missing_industry_count = sum(
            1 for row in [*previous_holdings, *validation_holdings] if not row.industry
        )
        pair_issues = []
        if len(previous_holdings) == 0:
            pair_issues.append("上一期无股票持仓")
        if len(validation_holdings) == 0:
            pair_issues.append("验证期无股票持仓")
        if require_industry and missing_industry_count:
            pair_issues.append(f"行业缺失 {missing_industry_count}")
        if stock_coverage < min_stock_weight_coverage:
            pair_issues.append(f"股票收益覆盖不足 {stock_coverage:.1%}")
        if nav_observations < min_return_observations:
            pair_issues.append(f"NAV收益样本不足 {nav_observations}/{min_return_observations}")
        pairs.append({
            "previous_report_date": str(previous_report),
            "validation_report_date": str(validation_report),
            "previous_holding_count": len(previous_holdings),
            "validation_holding_count": len(validation_holdings),
            "missing_industry_count": missing_industry_count,
            "stock_return_weight_coverage": round(stock_coverage, 6),
            "nav_return_observations": nav_observations,
            "is_ready": not pair_issues,
            "issues": pair_issues,
        })

    ready_pairs = [pair for pair in pairs if pair["is_ready"]]
    if len(report_dates) < 2:
        issues.append("少于两期股票持仓披露")
    if len(ready_pairs) < min_validation_pairs:
        issues.append(f"可回测披露期不足 {len(ready_pairs)}/{min_validation_pairs}")
    for pair in pairs:
        issues.extend(
            f"{pair['previous_report_date']}->{pair['validation_report_date']}: {issue}"
            for issue in pair["issues"]
        )

    min_stock_coverage = min(
        (pair["stock_return_weight_coverage"] for pair in pairs),
        default=0.0,
    )
    min_nav_observations = min(
        (pair["nav_return_observations"] for pair in pairs),
        default=0,
    )
    return {
        "fund_code": fund_code,
        "report_period_count": len(report_dates),
        "validation_pair_count": len(pairs),
        "ready_validation_pair_count": len(ready_pairs),
        "min_stock_return_weight_coverage": round(min_stock_coverage, 6),
        "min_nav_return_observations": min_nav_observations,
        "validation_pairs": pairs,
        "is_ready": not issues,
        "issues": issues,
    }


def assess_dynamic_attribution_readiness(
    session: Session,
    fund_codes: set[str] | None = None,
    *,
    benchmark_symbol: str | None = None,
    min_report_date: date_type | None = None,
    max_report_date: date_type | None = None,
    min_return_observations: int = MIN_READINESS_RETURN_OBSERVATIONS,
    min_stock_weight_coverage: float = MIN_READINESS_STOCK_WEIGHT_COVERAGE,
    max_snapshot_age_days: int = MAX_ATTRIBUTION_BENCHMARK_WEIGHT_STALENESS_DAYS,
    ready_only: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Assess whether disclosed holdings can run dynamic attribution."""
    report_stmt = (
        select(FundDisclosedHoldings.fund_code, FundDisclosedHoldings.report_date)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .group_by(FundDisclosedHoldings.fund_code, FundDisclosedHoldings.report_date)
        .order_by(FundDisclosedHoldings.fund_code, FundDisclosedHoldings.report_date)
    )
    if fund_codes:
        report_stmt = report_stmt.where(FundDisclosedHoldings.fund_code.in_(fund_codes))
    if min_report_date is not None:
        report_stmt = report_stmt.where(FundDisclosedHoldings.report_date >= min_report_date)
    if max_report_date is not None:
        report_stmt = report_stmt.where(FundDisclosedHoldings.report_date <= max_report_date)

    rows = []
    for fund_code, report_date in session.execute(report_stmt).all():
        rows.append(
            _assess_report(
                session,
                fund_code=fund_code,
                report_date=report_date,
                configured_benchmark_symbol=benchmark_symbol,
                min_return_observations=min_return_observations,
                min_stock_weight_coverage=min_stock_weight_coverage,
                max_snapshot_age_days=max_snapshot_age_days,
            )
        )
    rows.sort(key=lambda row: (0 if row["is_ready"] else 1, row["fund_code"], row["report_date"]))
    if ready_only:
        rows = [row for row in rows if row["is_ready"]]
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


def _assess_report(
    session: Session,
    *,
    fund_code: str,
    report_date: date_type,
    configured_benchmark_symbol: str | None,
    min_return_observations: int,
    min_stock_weight_coverage: float,
    max_snapshot_age_days: int,
) -> dict:
    holdings = session.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date == report_date)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .where(FundDisclosedHoldings.security_code.is_not(None))
        .order_by(FundDisclosedHoldings.rank_in_holdings)
    ).all()
    benchmark_symbol, benchmark_source = _resolve_readiness_benchmark(
        session,
        fund_code,
        configured_benchmark_symbol,
    )
    stock_codes = {str(row.security_code) for row in holdings if row.security_code}
    total_weight = sum(float(row.weight_pct or 0.0) for row in holdings)
    missing_industry_count = sum(1 for row in holdings if not row.industry)
    stock_coverage = _stock_return_weight_coverage(
        session,
        holdings=holdings,
        report_date=report_date,
    )
    benchmark_observations = _return_observation_count(
        session,
        benchmark_symbol,
        report_date,
    )
    benchmark_weight = _benchmark_weight_status(
        session,
        benchmark_symbol=benchmark_symbol,
        report_date=report_date,
        max_snapshot_age_days=max_snapshot_age_days,
    )

    issues = []
    if not holdings:
        issues.append("无股票持仓")
    if missing_industry_count:
        issues.append(f"持仓行业缺失 {missing_industry_count}/{len(holdings)}")
    if stock_coverage < min_stock_weight_coverage:
        issues.append(f"持仓股票行情覆盖不足 {stock_coverage:.1%}")
    if benchmark_observations < min_return_observations:
        issues.append(f"基准收益样本不足 {benchmark_observations}/{min_return_observations}")
    if not benchmark_weight["is_benchmark_weight_ready"]:
        issues.append(benchmark_weight["reason"])

    return {
        "fund_code": fund_code,
        "report_date": str(report_date),
        "benchmark_symbol": benchmark_symbol,
        "benchmark_source": benchmark_source,
        "holding_count": len(holdings),
        "stock_count": len(stock_codes),
        "stock_weight_sum_pct": round(total_weight, 6),
        "missing_industry_count": missing_industry_count,
        "stock_return_weight_coverage": round(stock_coverage, 6),
        "benchmark_return_observations": benchmark_observations,
        **benchmark_weight,
        "is_ready": not issues,
        "issues": issues,
    }


def _resolve_readiness_benchmark(
    session: Session,
    fund_code: str,
    configured_benchmark_symbol: str | None,
) -> tuple[str, str]:
    if configured_benchmark_symbol:
        return configured_benchmark_symbol, "parameter"
    fund = session.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    benchmark_text = fund.benchmark if fund and fund.benchmark else ""
    for keyword, symbol in BENCHMARK_TEXT_SYMBOL_MAP:
        if keyword in benchmark_text:
            return symbol, f"fund_benchmark:{keyword}"
    return DEFAULT_ATTRIBUTION_BENCHMARK_SYMBOL, "default"


def _return_window(report_date: date_type) -> tuple[date_type, date_type]:
    start = report_date
    month = start.month + 3
    year = start.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(start.day, 28)
    return start, date_type(year, month, day)


def _return_observation_count(
    session: Session,
    stock_code: str,
    report_date: date_type,
) -> int:
    start, end = _return_window(report_date)
    return int(session.scalar(
        select(func.count())
        .select_from(StockDaily)
        .where(StockDaily.stock_code == stock_code)
        .where(StockDaily.trade_date >= start)
        .where(StockDaily.trade_date < end)
        .where(or_(StockDaily.daily_return.is_not(None), StockDaily.close_price.is_not(None)))
    ) or 0)


def _stock_return_weight_coverage(
    session: Session,
    *,
    holdings: list[FundDisclosedHoldings],
    report_date: date_type,
) -> float:
    total_weight = sum(float(row.weight_pct or 0.0) for row in holdings)
    if total_weight <= 0:
        return 0.0
    covered_weight = 0.0
    for row in holdings:
        if not row.security_code:
            continue
        if _return_observation_count(session, str(row.security_code), report_date) > 0:
            covered_weight += float(row.weight_pct or 0.0)
    return covered_weight / total_weight


def _stock_holdings_for_report(
    session: Session,
    fund_code: str,
    report_date: date_type,
) -> list[FundDisclosedHoldings]:
    return list(session.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.report_date == report_date)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .where(FundDisclosedHoldings.security_code.is_not(None))
        .order_by(FundDisclosedHoldings.rank_in_holdings)
    ).all())


def _stock_return_weight_coverage_between(
    session: Session,
    *,
    holdings: list[FundDisclosedHoldings],
    start_date: date_type,
    end_date: date_type,
) -> float:
    total_weight = sum(float(row.weight_pct or 0.0) for row in holdings)
    if total_weight <= 0:
        return 0.0
    covered_weight = 0.0
    for row in holdings:
        if not row.security_code:
            continue
        if _return_observation_count_between(
            session,
            str(row.security_code),
            start_date,
            end_date,
        ) > 0:
            covered_weight += float(row.weight_pct or 0.0)
    return covered_weight / total_weight


def _return_observation_count_between(
    session: Session,
    stock_code: str,
    start_date: date_type,
    end_date: date_type,
) -> int:
    return int(session.scalar(
        select(func.count())
        .select_from(StockDaily)
        .where(StockDaily.stock_code == stock_code)
        .where(StockDaily.trade_date >= start_date)
        .where(StockDaily.trade_date < end_date)
        .where(or_(StockDaily.daily_return.is_not(None), StockDaily.close_price.is_not(None)))
    ) or 0)


def _nav_observation_count(
    session: Session,
    *,
    fund_code: str,
    start_date: date_type,
    end_date: date_type,
) -> int:
    return int(session.scalar(
        select(func.count())
        .select_from(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .where(FundNAV.trade_date >= start_date)
        .where(FundNAV.trade_date < end_date)
        .where(or_(FundNAV.daily_return.is_not(None), FundNAV.unit_nav.is_not(None)))
    ) or 0)


def _benchmark_weight_status(
    session: Session,
    *,
    benchmark_symbol: str,
    report_date: date_type,
    max_snapshot_age_days: int,
) -> dict:
    snapshot_date = session.scalar(
        select(BenchmarkIndustryWeight.snapshot_date)
        .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
        .where(BenchmarkIndustryWeight.snapshot_date <= report_date)
        .where(BenchmarkIndustryWeight.classification_type == "SW")
        .where(BenchmarkIndustryWeight.classification_level == 1)
        .order_by(BenchmarkIndustryWeight.snapshot_date.desc())
        .limit(1)
    )
    future_snapshot_date = session.scalar(
        select(BenchmarkIndustryWeight.snapshot_date)
        .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
        .where(BenchmarkIndustryWeight.snapshot_date > report_date)
        .where(BenchmarkIndustryWeight.classification_type == "SW")
        .where(BenchmarkIndustryWeight.classification_level == 1)
        .order_by(BenchmarkIndustryWeight.snapshot_date)
        .limit(1)
    )
    if snapshot_date is None:
        reason = f"缺少不晚于报告期的基准行业权重: {benchmark_symbol}"
        if future_snapshot_date is not None:
            reason += f"；最近未来快照 {future_snapshot_date}"
        return {
            "benchmark_weight_snapshot_date": None,
            "benchmark_weight_future_snapshot_date": str(future_snapshot_date) if future_snapshot_date else None,
            "benchmark_weight_snapshot_age_days": None,
            "benchmark_weight_coverage_pct": None,
            "benchmark_weight_unmapped_pct": None,
            "is_benchmark_weight_ready": False,
            "reason": reason,
        }

    weight_rows = session.scalars(
        select(BenchmarkIndustryWeight)
        .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
        .where(BenchmarkIndustryWeight.snapshot_date == snapshot_date)
        .where(BenchmarkIndustryWeight.classification_type == "SW")
        .where(BenchmarkIndustryWeight.classification_level == 1)
    ).all()
    coverage_pct = min((float(row.coverage_pct or 0.0) for row in weight_rows), default=0.0)
    unmapped_pct = max((float(row.unmapped_weight_pct or 0.0) for row in weight_rows), default=0.0)
    snapshot_age_days = (report_date - snapshot_date).days
    is_ready = (
        snapshot_age_days <= max_snapshot_age_days
        and coverage_pct >= MIN_ATTRIBUTION_BENCHMARK_WEIGHT_COVERAGE
    )
    reason = ""
    if snapshot_age_days > max_snapshot_age_days:
        reason = f"基准行业权重快照过旧: {snapshot_age_days}d"
    elif coverage_pct < MIN_ATTRIBUTION_BENCHMARK_WEIGHT_COVERAGE:
        reason = f"基准行业权重覆盖不足: {coverage_pct:.2f}%"

    return {
        "benchmark_weight_snapshot_date": str(snapshot_date),
        "benchmark_weight_future_snapshot_date": str(future_snapshot_date) if future_snapshot_date else None,
        "benchmark_weight_snapshot_age_days": snapshot_age_days,
        "benchmark_weight_coverage_pct": round(coverage_pct, 6),
        "benchmark_weight_unmapped_pct": round(unmapped_pct, 6),
        "is_benchmark_weight_ready": is_ready,
        "reason": reason,
    }
