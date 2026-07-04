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
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import FundDisclosedHoldings, FundMain
from fund_research.db.models_phase2 import (
    FundPoolMember as DbFundPoolMember,
)
from fund_research.db.models_phase2 import (
    SimulatedHoldingResult,
)
from fund_research.db.models_phase3 import ReverseLookupResult
from fund_research.utils import safe_float

ALGORITHM_NAME = "reverse_lookup"
ALGORITHM_VERSION = "0.1.0"

# Simulated holdings with tracking_error above this threshold get downgraded
# confidence (requirement: lower confidence if tracking_error > 0.05).
TRACKING_ERROR_THRESHOLD = 0.05

# Asset type label for equity holdings in FundDisclosedHoldings.
_EQUITY_ASSET_TYPE = "股票"


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
) -> list[dict]:
    """Reverse lookup against disclosed holdings (source=fact).

    Queries FundDisclosedHoldings where security_code IN stock_codes and
    asset_type == "股票". For each fund, sums weight_pct across matching
    stocks at the fund's latest report_date. Returns a list sorted by
    total_exposure descending.
    """
    if not stock_codes:
        return []

    scope_codes = _resolve_fund_scope(db, fund_scope, scope_id)

    stmt = select(FundDisclosedHoldings).where(
        FundDisclosedHoldings.security_code.in_(stock_codes),
        FundDisclosedHoldings.asset_type == _EQUITY_ASSET_TYPE,
    )
    if scope_codes is not None:
        if not scope_codes:
            return []
        stmt = stmt.where(FundDisclosedHoldings.fund_code.in_(scope_codes))

    rows = db.scalars(stmt).all()
    if not rows:
        return []

    # Keep the latest report_date per fund so the exposure reflects the most
    # recent disclosure rather than summing across multiple quarters.
    latest_date_by_fund: dict[str, date] = {}
    for r in rows:
        if r.report_date is None:
            continue
        current = latest_date_by_fund.get(r.fund_code)
        if current is None or r.report_date > current:
            latest_date_by_fund[r.fund_code] = r.report_date

    fund_to_contributions: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.report_date is None:
            continue
        if latest_date_by_fund.get(r.fund_code) != r.report_date:
            continue
        weight = safe_float(r.weight_pct)
        if weight is None:
            weight = 0.0
        fund_to_contributions.setdefault(r.fund_code, []).append(
            {
                "security_code": r.security_code,
                "weight": weight,
                "source": "disclosed",
            }
        )

    results: list[dict[str, Any]] = []
    for fund_code, contribs in fund_to_contributions.items():
        total = round(sum(c["weight"] for c in contribs), 6)
        results.append(
            {
                "fund_code": fund_code,
                "total_exposure": total,
                "stock_contributions": contribs,
                "source": "fact",
                "conclusion_status": "fact",
                "confidence": "high",
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
) -> list[dict]:
    """Weighted reverse lookup: disclosed primary, simulated fallback.

    For funds with disclosed data, use it as primary (source="fact").
    For funds without disclosed data, use simulated as fallback
    (source="estimated"). Merge and sort by total_exposure.
    """
    disclosed = reverse_lookup_disclosed(db, stock_codes, fund_scope, scope_id)
    simulated = reverse_lookup_simulated(db, stock_codes, fund_scope, scope_id)

    disclosed_codes = {r["fund_code"] for r in disclosed}
    merged: list[dict[str, Any]] = list(disclosed)

    for r in simulated:
        if r["fund_code"] in disclosed_codes:
            continue
        merged.append(r)

    merged.sort(key=lambda x: x["total_exposure"], reverse=True)
    return merged


def reverse_lookup(
    db: Session,
    stock_codes: list[str],
    method: str = "weighted",
    fund_scope: str = "all",
    scope_id: str | None = None,
    top_n: int = 20,
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

    Returns:
        dict with keys: results, stock_coverage, method, fund_count.
    """
    normalized_codes = [c.strip() for c in stock_codes if c and c.strip()]

    if method == "disclosed":
        results = reverse_lookup_disclosed(db, normalized_codes, fund_scope, scope_id)
    elif method == "simulated":
        results = reverse_lookup_simulated(db, normalized_codes, fund_scope, scope_id)
    elif method == "weighted":
        results = reverse_lookup_weighted(db, normalized_codes, fund_scope, scope_id)
    else:
        raise ValueError(f"未知的反选方法: {method}")

    # Top-N truncation
    if top_n > 0:
        results = results[:top_n]

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
    }


def persist_result(
    db: Session,
    stock_codes: list[str],
    result: dict,
    fund_scope: str,
    scope_id: str | None,
    method: str,
) -> ReverseLookupResult:
    """Persist a reverse lookup result to the reverse_lookup_result table.

    Args:
        db: Database session.
        stock_codes: The input stock code basket.
        result: The dict returned by reverse_lookup().
        fund_scope: Scope label used for the lookup.
        scope_id: Optional scope identifier (e.g. pool ID).
        method: Lookup method (disclosed/simulated/weighted).

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
        time_range="latest",
        results=result.get("results", []),
        stock_coverage=result.get("stock_coverage", {}),
        calc_date=date.today(),
    )
    db.add(row)
    db.flush()
    return row
