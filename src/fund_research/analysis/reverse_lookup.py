"""
Stock-to-Fund Reverse Lookup (Phase 3).

Given a basket of stock codes, find which funds hold those stocks and rank
them by exposure. Supports three lookup methods:

- disclosed: query FundDisclosedHoldings (A-level disclosed data, source=fact)
- simulated: query SimulatedHoldingResult (estimated holdings, source=estimated)
- weighted: disclosed primary, simulated fallback

Per v0.4 requirements §6.3.5 (Phase 3 reverse lookup) and §5.5 conclusion
credibility gating. Simulated holdings are flagged as "estimated" and must
NOT enter default scoring or high-confidence conclusions (§4.3 estimated
pollution isolation).

References:
- v0.4 requirements §6.3.5 Stock-to-Fund Reverse Lookup
- v0.4 requirements §5.5 Conclusion Credibility Gating
- v0.4 requirements §4.3 Estimated Pollution Isolation
"""

import hashlib
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundCompany,
    FundDisclosedHoldings,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
)
from fund_research.db.models_phase2 import (
    FundPoolMember as DbFundPoolMember,
)
from fund_research.db.models_phase2 import (
    SimulatedHoldingResult,
)
from fund_research.db.models_phase3 import ReverseLookupResult
from fund_research.utils import nav_value, safe_float

ALGORITHM_NAME = "reverse_lookup"
ALGORITHM_VERSION = "0.2.0"

# Simulated holdings with tracking_error above this threshold get downgraded
# confidence (requirement: lower confidence if tracking_error > 0.05).
TRACKING_ERROR_THRESHOLD = 0.05

# Asset type label for equity holdings in FundDisclosedHoldings.
_EQUITY_ASSET_TYPE = "股票"

# 披露持仓时间口径（P4.3-1，需求书 §6.2.10 输入第 4 条）：
# latest_report=最新报告期；recent_1y_avg=近一年各披露期简单均值；
# specified_date=指定报告期（取不晚于指定日期的最近一期）。
TIME_RANGES = ("latest_report", "recent_1y_avg", "specified_date")


def _hash_stock_codes(stock_codes: list[str]) -> str:
    """Hash a basket of stock codes into a stable cache key.

    Codes are sorted and joined so the hash is order-independent.
    """
    normalized = sorted(code.strip() for code in stock_codes if code and code.strip())
    joined = ",".join(normalized)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def _resolve_fund_scope(
    db: Session,
    fund_scope: str,
    scope_id: str | None,
) -> set[str] | None:
    """Resolve fund codes for a scope, or None meaning 'all funds'.

    - fund_scope == "all": return None (no filter)
    - fund_scope == "pool": return fund codes in the given pool
    - fund_scope == "fund_type": return fund codes matching FundMain.category

    Returns an empty set when a scope requires scope_id but none is provided.
    """
    if fund_scope == "pool":
        if not scope_id:
            return set()
        try:
            pool_id = int(scope_id)
        except (TypeError, ValueError):
            return set()
        return set(
            db.scalars(
                select(DbFundPoolMember.fund_code).where(
                    DbFundPoolMember.pool_id == pool_id
                )
            ).all()
        )
    if fund_scope == "fund_type":
        if not scope_id:
            return set()
        return set(
            db.scalars(
                select(FundMain.fund_code).where(FundMain.category == scope_id)
            ).all()
        )
    return None


def reverse_lookup_disclosed(
    db: Session,
    stock_codes: list[str],
    fund_scope: str = "all",
    scope_id: str | None = None,
    time_range: str = "latest_report",
    report_date: date | None = None,
) -> list[dict]:
    """Reverse lookup against disclosed holdings (source=fact).

    Queries FundDisclosedHoldings where security_code IN stock_codes and
    asset_type == "股票". Report periods selected per ``time_range``
    (P4.3-1，§6.2.10):

    - latest_report: 每基金最新披露期（默认，原行为）
    - recent_1y_avg: 近一年各披露期暴露简单均值
    - specified_date: 不晚于 ``report_date`` 的最近一期

    Returns a list sorted by total_exposure descending.
    """
    if not stock_codes:
        return []
    if time_range not in TIME_RANGES:
        raise ValueError(f"未知的披露时间口径: {time_range}")
    if time_range == "specified_date" and report_date is None:
        raise ValueError("specified_date 口径需要 report_date")

    scope_codes = _resolve_fund_scope(db, fund_scope, scope_id)

    stmt = select(FundDisclosedHoldings).where(
        FundDisclosedHoldings.security_code.in_(stock_codes),
        FundDisclosedHoldings.asset_type == _EQUITY_ASSET_TYPE,
    )
    if scope_codes is not None:
        if not scope_codes:
            return []
        stmt = stmt.where(FundDisclosedHoldings.fund_code.in_(scope_codes))
    if time_range == "specified_date":
        stmt = stmt.where(FundDisclosedHoldings.report_date <= report_date)
    elif time_range == "recent_1y_avg":
        today = date.today()
        try:
            since = today.replace(year=today.year - 1)
        except ValueError:  # 闰年 2-29 收敛
            since = today.replace(year=today.year - 1, day=28)
        stmt = stmt.where(FundDisclosedHoldings.report_date >= since)

    rows = db.scalars(stmt).all()
    if not rows:
        return []

    # 每基金各披露期的暴露汇总（供时间口径选择与历史变化计算）
    fund_period_exposure: dict[str, dict[date, float]] = {}
    fund_period_contribs: dict[str, dict[date, list[dict[str, Any]]]] = {}
    for r in rows:
        if r.report_date is None:
            continue
        weight = safe_float(r.weight_pct)
        if weight is None:
            weight = 0.0
        periods = fund_period_exposure.setdefault(r.fund_code, {})
        periods[r.report_date] = periods.get(r.report_date, 0.0) + weight
        fund_period_contribs.setdefault(r.fund_code, {}).setdefault(
            r.report_date, []
        ).append(
            {
                "security_code": r.security_code,
                "weight": weight,
                "source": "disclosed",
            }
        )

    results: list[dict[str, Any]] = []
    for fund_code, periods in fund_period_exposure.items():
        sorted_dates = sorted(periods)
        if time_range == "recent_1y_avg":
            total = round(sum(periods.values()) / len(sorted_dates), 6)
            contribs = fund_period_contribs[fund_code][sorted_dates[-1]]
            used_report_date = sorted_dates[-1]
            periods_used = len(sorted_dates)
        else:
            used_report_date = sorted_dates[-1]
            total = round(periods[used_report_date], 6)
            contribs = fund_period_contribs[fund_code][used_report_date]
            periods_used = 1
        # 历史变化：所用期与前一披露期的暴露差分（§6.2.10 输出）
        history_change = None
        idx = sorted_dates.index(used_report_date)
        if idx > 0:
            history_change = round(
                periods[used_report_date] - periods[sorted_dates[idx - 1]], 6
            )
        results.append(
            {
                "fund_code": fund_code,
                "total_exposure": total,
                "stock_contributions": contribs,
                "source": "fact",
                "conclusion_status": "fact",
                "confidence": "high",
                "report_date": str(used_report_date),
                "periods_used": periods_used,
                "exposure_change_vs_prev": history_change,
            }
        )

    results.sort(key=lambda x: x["total_exposure"], reverse=True)
    return results


def reverse_lookup_simulated(
    db: Session,
    stock_codes: list[str],
    fund_scope: str = "all",
    scope_id: str | None = None,
) -> list[dict]:
    """Reverse lookup against simulated holdings (source=estimated).

    Queries the latest SimulatedHoldingResult per fund and parses
    holdings_detail to find matching stock codes. Tracking error above
    TRACKING_ERROR_THRESHOLD downgrades confidence.

    Note: Simulated holdings are estimates and must NOT enter default
    scoring or high-confidence conclusions (§4.3 estimated pollution
    isolation).
    """
    if not stock_codes:
        return []

    scope_codes = _resolve_fund_scope(db, fund_scope, scope_id)
    target_set = set(stock_codes)

    stmt = select(SimulatedHoldingResult)
    if scope_codes is not None:
        if not scope_codes:
            return []
        stmt = stmt.where(SimulatedHoldingResult.fund_code.in_(scope_codes))

    rows = db.scalars(stmt).all()
    if not rows:
        return []

    # Keep the latest calc_date per fund.
    latest_by_fund: dict[str, SimulatedHoldingResult] = {}
    for r in rows:
        current = latest_by_fund.get(r.fund_code)
        if current is None or r.calc_date and current.calc_date and r.calc_date > current.calc_date:
            latest_by_fund[r.fund_code] = r

    results: list[dict[str, Any]] = []
    for fund_code, sim in latest_by_fund.items():
        holdings_detail = sim.holdings_detail or []
        contribs: list[dict[str, Any]] = []
        for h in holdings_detail:
            code = h.get("stock_code") or h.get("code")
            if not code or str(code) not in target_set:
                continue
            raw_weight = h.get("estimated_weight")
            if raw_weight is None:
                raw_weight = h.get("weight", 0.0)
            weight_f = safe_float(raw_weight)
            if weight_f is None:
                weight_f = 0.0
            # holdings_detail stores 0-1 weights; convert to percentage to
            # match FundDisclosedHoldings.weight_pct scale.
            weight_pct = weight_f * 100.0
            contribs.append(
                {
                    "security_code": str(code),
                    "weight": round(weight_pct, 6),
                    "source": "simulated",
                }
            )
        if not contribs:
            continue

        total = round(sum(c["weight"] for c in contribs), 6)
        tracking_error = safe_float(sim.tracking_error)
        confidence = "medium"
        warnings: list[str] = []
        if tracking_error is not None and tracking_error > TRACKING_ERROR_THRESHOLD:
            confidence = "low"
            warnings.append(
                f"tracking_error={tracking_error:.4f} 超过阈值 "
                f"{TRACKING_ERROR_THRESHOLD}，置信度降级"
            )

        results.append(
            {
                "fund_code": fund_code,
                "total_exposure": total,
                "stock_contributions": contribs,
                "source": "estimated",
                "conclusion_status": "estimated",
                "confidence": confidence,
                "tracking_error": tracking_error,
                "top10_recall": safe_float(sim.top10_recall),
                "warnings": warnings,
            }
        )

    results.sort(key=lambda x: x["total_exposure"], reverse=True)
    return results


def reverse_lookup_weighted(
    db: Session,
    stock_codes: list[str],
    fund_scope: str = "all",
    scope_id: str | None = None,
    time_range: str = "latest_report",
    report_date: date | None = None,
) -> list[dict]:
    """Weighted reverse lookup: disclosed primary, simulated fallback.

    For funds with disclosed data, use it as primary (source="fact").
    For funds without disclosed data, use simulated as fallback
    (source="estimated"). Merge and sort by total_exposure.
    """
    disclosed = reverse_lookup_disclosed(
        db, stock_codes, fund_scope, scope_id, time_range, report_date
    )
    simulated = reverse_lookup_simulated(db, stock_codes, fund_scope, scope_id)

    disclosed_codes = {r["fund_code"] for r in disclosed}
    merged: list[dict[str, Any]] = list(disclosed)

    # P4.3 审计修复：有披露持仓但时间口径窗口内无匹配的基金被 simulated
    # 填充时附降级说明，避免"有 fact 却静默输出 estimated"
    scope_codes = _resolve_fund_scope(db, fund_scope, scope_id)
    if scope_codes is not None and not scope_codes:
        disclosed_available: set[str] = set()
    else:
        avail_stmt = (
            select(FundDisclosedHoldings.fund_code)
            .where(
                FundDisclosedHoldings.security_code.in_(stock_codes),
                FundDisclosedHoldings.asset_type == _EQUITY_ASSET_TYPE,
            )
            .distinct()
        )
        if scope_codes is not None:
            avail_stmt = avail_stmt.where(
                FundDisclosedHoldings.fund_code.in_(scope_codes)
            )
        disclosed_available = set(db.scalars(avail_stmt).all())

    for r in simulated:
        if r["fund_code"] in disclosed_codes:
            continue
        if r["fund_code"] in disclosed_available:
            r.setdefault("warnings", []).append(
                "该基金存在披露持仓但当前时间口径无匹配，本行已由模拟持仓估计填充"
            )
        merged.append(r)

    merged.sort(key=lambda x: x["total_exposure"], reverse=True)
    return merged


def _category_1y_returns(db: Session, peers: list[str]) -> dict[str, float]:
    """同类基金近一年收益批量计算（单次查询，避免 N+1；P4.3 审计修复）。

    净值取 nav_value 复权口径（adjusted > accumulated > unit），避免分红
    拆分导致收益低估、同类排名失真。
    """
    if not peers:
        return {}
    since = date.today() - timedelta(days=365)
    rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code.in_(peers))
        .where(FundNAV.trade_date >= since)
        .order_by(FundNAV.trade_date)
    ).all()
    navs_by_fund: dict[str, list[float]] = {}
    for row in rows:
        value = nav_value(row)
        if value:
            navs_by_fund.setdefault(row.fund_code, []).append(value)
    return {
        code: seq[-1] / seq[0] - 1.0
        for code, seq in navs_by_fund.items()
        if len(seq) >= 2
    }


def _enrich_fund_details(db: Session, results: list[dict]) -> None:
    """补全 §6.2.10 输出字段：名称/公司/经理/同类排名（P4.3-1）。"""
    from fund_research.analysis.rank import rank_in_category

    if not results:
        return
    codes = [r["fund_code"] for r in results]

    funds = {f.fund_code: f for f in db.scalars(select(FundMain).where(FundMain.fund_code.in_(codes))).all()}
    # fund_company_id 存的是 FundCompany 主键（与 packet.py/router.py 惯例一致）
    companies = {
        c.id: (c.short_name or c.name)
        for c in db.scalars(select(FundCompany)).all()
    }
    tenures = db.scalars(
        select(FundManagerTenure)
        .where(FundManagerTenure.fund_code.in_(codes))
        .where(FundManagerTenure.is_current.is_(True))
    ).all()
    manager_ids = {t.manager_id for t in tenures}
    managers = (
        {
            m.manager_id: m.name
            for m in db.scalars(
                select(FundManager).where(FundManager.manager_id.in_(manager_ids))
            ).all()
        }
        if manager_ids
        else {}
    )
    managers_by_fund: dict[str, list[str]] = {}
    for t in tenures:
        name = managers.get(t.manager_id)
        if name:
            existing = managers_by_fund.setdefault(t.fund_code, [])
            if name not in existing:  # 去重：同一经理可能有多条 current tenure
                existing.append(name)

    # 同类排名：同 sub_category 内按近一年收益（rank.py 口径）
    returns_by_category: dict[str, dict[str, float]] = {}
    for r in results:
        fund = funds.get(r["fund_code"])
        sub = fund.sub_category if fund and fund.sub_category else None
        r["fund_name"] = (fund.short_name or fund.fund_code) if fund else r["fund_code"]
        r["fund_company"] = (
            companies.get(fund.fund_company_id) if fund and fund.fund_company_id else None
        )
        r["manager_names"] = managers_by_fund.get(r["fund_code"], [])
        r["sub_category"] = sub
        if sub is None:
            continue
        if sub not in returns_by_category:
            peers = list(
                db.scalars(
                    select(FundMain.fund_code).where(FundMain.sub_category == sub)
                ).all()
            )
            returns_by_category[sub] = _category_1y_returns(db, peers)

    for r in results:
        sub = r.get("sub_category")
        values = returns_by_category.get(sub) if sub else None
        rank = (
            rank_in_category(values, r["fund_code"], sub_category=sub)
            if values
            else None
        )
        r["rank_in_category_1y"] = rank.rank_text if rank else None


def reverse_lookup(
    db: Session,
    stock_codes: list[str],
    method: str = "weighted",
    fund_scope: str = "all",
    scope_id: str | None = None,
    top_n: int = 20,
    time_range: str = "latest_report",
    report_date: date | None = None,
) -> dict:
    """Main entry point for stock-to-fund reverse lookup.

    Dispatches to the requested method, computes stock coverage, and
    truncates to top_n funds.

    Args:
        db: Database session.
        stock_codes: Basket of stock codes to look up.
        method: Lookup method — "disclosed", "simulated", or "weighted".
        fund_scope: Fund scope — "all", "pool", or "fund_type".
        scope_id: Optional scope identifier (pool ID or fund category).
        top_n: Maximum number of funds to return (0 means no limit).
        time_range: 披露持仓时间口径（仅影响 disclosed/weighted，§6.2.10）。
        report_date: specified_date 口径的目标报告期。

    Returns:
        dict with keys: results, stock_coverage, method, fund_count.
    """
    normalized_codes = [c.strip() for c in stock_codes if c and c.strip()]

    if method == "disclosed":
        results = reverse_lookup_disclosed(
            db, normalized_codes, fund_scope, scope_id, time_range, report_date
        )
    elif method == "simulated":
        results = reverse_lookup_simulated(db, normalized_codes, fund_scope, scope_id)
    elif method == "weighted":
        results = reverse_lookup_weighted(
            db, normalized_codes, fund_scope, scope_id, time_range, report_date
        )
    else:
        raise ValueError(f"未知的反选方法: {method}")

    # Top-N truncation
    if top_n > 0:
        results = results[:top_n]

    # §6.2.10 输出字段：名称/公司/经理/同类排名（截断后补全，控制开销）
    _enrich_fund_details(db, results)

    # Stock coverage: how many returned funds hold each stock.
    stock_coverage: dict[str, int] = {code: 0 for code in normalized_codes}
    for r in results:
        seen = {c["security_code"] for c in r.get("stock_contributions", [])}
        for code in seen:
            if code in stock_coverage:
                stock_coverage[code] += 1

    return {
        "results": results,
        "stock_coverage": stock_coverage,
        "method": method,
        "fund_count": len(results),
        "time_range": time_range,
    }


def persist_result(
    db: Session,
    stock_codes: list[str],
    result: dict,
    fund_scope: str,
    scope_id: str | None,
    method: str,
    time_range: str = "latest_report",
) -> ReverseLookupResult:
    """Persist a reverse lookup result to the reverse_lookup_result table.

    Args:
        db: Database session.
        stock_codes: The input stock code basket.
        result: The dict returned by reverse_lookup().
        fund_scope: Scope label used for the lookup.
        scope_id: Optional scope identifier (e.g. pool ID).
        method: Lookup method (disclosed/simulated/weighted).
        time_range: 披露时间口径（P4.3-1）。

    Returns:
        The persisted ReverseLookupResult (flushed, not committed).
    """
    normalized = [c.strip() for c in stock_codes if c and c.strip()]
    stock_hash = _hash_stock_codes(normalized)
    row = ReverseLookupResult(
        stock_codes_hash=stock_hash,
        stock_codes=normalized,
        fund_scope=fund_scope,
        scope_id=scope_id,
        method=method,
        time_range=time_range,
        results=result.get("results", []),
        stock_coverage=result.get("stock_coverage", {}),
        calc_date=date.today(),
    )
    db.add(row)
    db.flush()
    return row
