"""
Research Dashboard Data Aggregation (Phase 3, P3.7).

Aggregates data from multiple sources to provide a unified overview for the
research dashboard. Each ``gather_*`` function queries a specific domain and
returns a dict suitable for API response. ``generate_dashboard()`` orchestrates
all panels and catches per-panel exceptions so a single failing panel does not
break the entire dashboard.

Panels:
1. today_changes    — Today's NAV changes for tracked funds
2. pool_monitoring  — Pool alert summary (unread alerts by severity)
3. algorithm_alerts — Anomaly detection summary (recent anomalies by rule)
4. ai_alerts        — AI-generated alerts (placeholder)
5. market_overview  — Market overview (fund count, category distribution)

References:
- v0.4 requirements §12.7 Research Dashboard
- v0.4 requirements §5.5 Conclusion Credibility Gating
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.db.models import FundMain, FundNAV
from fund_research.db.models_phase3 import AnomalyRecord, PoolAlertRecord
from fund_research.utils import nav_value, utc_now

ALGORITHM_NAME = "dashboard"
ALGORITHM_VERSION = "0.1.0"


@dataclass
class DashboardData:
    """Aggregated dashboard data across 5 panels."""

    today_changes: dict[str, Any] = field(default_factory=dict)
    pool_monitoring: dict[str, Any] = field(default_factory=dict)
    algorithm_alerts: dict[str, Any] = field(default_factory=dict)
    ai_alerts: dict[str, Any] = field(default_factory=dict)
    market_overview: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=utc_now)
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        """Return API-friendly dict."""
        return {
            "today_changes": self.today_changes,
            "pool_monitoring": self.pool_monitoring,
            "algorithm_alerts": self.algorithm_alerts,
            "ai_alerts": self.ai_alerts,
            "market_overview": self.market_overview,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "warnings": self.warnings,
        }


# ============================================================
# Helpers
# ============================================================


# ============================================================
# Panel gather functions
# ============================================================


def gather_today_changes(
    db: Session, fund_codes: list[str] | None = None
) -> dict[str, Any]:
    """Gather today's NAV changes for tracked funds.

    Queries FundNAV for the latest 2 trade dates and computes per-fund
    change rates. Returns gainers/losers counts and top 5 movers.

    Args:
        db: Database session.
        fund_codes: Optional list of fund codes to filter. If None, all funds.

    Returns:
        Dict with latest_date, previous_date, fund_count, gainers, losers,
        unchanged, top_gainers (max 5), top_losers (max 5).
    """
    empty = {
        "latest_date": None,
        "previous_date": None,
        "fund_count": 0,
        "evaluated_count": 0,
        "gainers": 0,
        "losers": 0,
        "unchanged": 0,
        "skipped_funds": [],
        "top_gainers": [],
        "top_losers": [],
    }

    # Get latest 2 distinct trade dates (optionally filtered by fund_codes)
    date_query = select(FundNAV.trade_date).distinct()
    if fund_codes:
        date_query = date_query.where(FundNAV.fund_code.in_(fund_codes))
    date_query = date_query.order_by(FundNAV.trade_date.desc()).limit(2)
    latest_dates = list(db.scalars(date_query).all())

    if len(latest_dates) < 2:
        return empty

    latest_date, previous_date = latest_dates[0], latest_dates[1]

    # Get NAV rows for the two dates
    nav_query = select(FundNAV).where(
        FundNAV.trade_date.in_([latest_date, previous_date])
    )
    if fund_codes:
        nav_query = nav_query.where(FundNAV.fund_code.in_(fund_codes))
    rows = db.scalars(nav_query).all()

    # Group by fund_code: {fund_code: {trade_date: FundNAV}}
    by_fund: dict[str, dict[Any, FundNAV]] = defaultdict(dict)
    for row in rows:
        by_fund[row.fund_code][row.trade_date] = row

    gainers = 0
    losers = 0
    unchanged = 0
    changes: list[dict[str, Any]] = []
    skipped_funds: list[dict[str, str]] = []

    for fund_code, navs in by_fund.items():
        latest_row = navs.get(latest_date)
        prev_row = navs.get(previous_date)
        if latest_row is None or prev_row is None:
            skipped_funds.append(
                {"fund_code": fund_code, "reason": "missing_nav_on_date"}
            )
            continue
        latest_nav = nav_value(latest_row)
        prev_nav = nav_value(prev_row)
        if latest_nav is None or prev_nav is None or prev_nav == 0:
            skipped_funds.append(
                {"fund_code": fund_code, "reason": "null_or_zero_nav"}
            )
            continue
        change_rate = (latest_nav - prev_nav) / prev_nav
        if change_rate > 0:
            gainers += 1
        elif change_rate < 0:
            losers += 1
        else:
            unchanged += 1
        changes.append(
            {
                "fund_code": fund_code,
                "change_rate": round(change_rate, 4),
                "latest_nav": round(latest_nav, 4),
            }
        )

    # fund_count 反映"最近 2 个交易日有 nav 数据的基金"，
    # 与 market_overview.total_funds（同源 = fund_main 30）口径分离，
    # 前端展示差异时由 skipped_funds 解释
    fund_count = len(by_fund)
    evaluated_count = gainers + losers + unchanged
    top_gainers = sorted(
        [c for c in changes if c["change_rate"] > 0],
        key=lambda x: x["change_rate"],
        reverse=True,
    )[:5]
    top_losers = sorted(
        [c for c in changes if c["change_rate"] < 0],
        key=lambda x: x["change_rate"],
    )[:5]

    return {
        "latest_date": str(latest_date),
        "previous_date": str(previous_date),
        "fund_count": fund_count,
        "evaluated_count": evaluated_count,
        "gainers": gainers,
        "losers": losers,
        "unchanged": unchanged,
        "skipped_funds": skipped_funds,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
    }


def gather_pool_monitoring(db: Session) -> dict[str, Any]:
    """Gather pool alert summary for unread alerts.

    Returns total unread count, breakdown by severity and type, and the
    5 most recent unread alerts.
    """
    rows = db.scalars(
        select(PoolAlertRecord)
        .where(PoolAlertRecord.is_read.is_(False))
        .order_by(PoolAlertRecord.triggered_at.desc())
    ).all()

    by_severity: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for row in rows:
        by_severity[row.severity] += 1
        by_type[row.alert_type] += 1

    # Ensure standard severity keys are always present
    severity_result: dict[str, int] = {"info": 0, "warning": 0, "critical": 0}
    severity_result.update(dict(by_severity))

    recent = [
        {
            "fund_code": row.fund_code,
            "alert_type": row.alert_type,
            "severity": row.severity,
            "message": row.message,
            "triggered_at": row.triggered_at.isoformat() if row.triggered_at else None,
        }
        for row in rows[:5]
    ]

    return {
        "total_unread": len(rows),
        "by_severity": severity_result,
        "by_type": dict(by_type),
        "recent": recent,
    }


def gather_algorithm_alerts(db: Session) -> dict[str, Any]:
    """Gather anomaly detection summary for recent anomalies (last 7 days).

    Returns total count, breakdown by rule and severity, and the 5 most
    recent anomalies.
    """
    cutoff = utc_now() - timedelta(days=7)
    rows = db.scalars(
        select(AnomalyRecord)
        .where(AnomalyRecord.detected_at >= cutoff)
        .order_by(AnomalyRecord.detected_at.desc())
    ).all()

    by_rule: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    for row in rows:
        by_rule[row.rule_name] += 1
        by_severity[row.severity] += 1

    recent = [
        {
            "fund_code": row.fund_code,
            "rule_name": row.rule_name,
            "severity": row.severity,
            "description": row.description,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        }
        for row in rows[:5]
    ]

    return {
        "total": len(rows),
        "by_rule": dict(by_rule),
        "by_severity": dict(by_severity),
        "recent": recent,
    }


def gather_ai_alerts(db: Session) -> dict[str, Any]:
    """Placeholder for AI-generated alerts.

    AI alert functionality will be added in a future version.
    """
    return {
        "total": 0,
        "alerts": [],
        "note": "AI 告警功能将在后续版本上线",
    }


def gather_market_overview(db: Session) -> dict[str, Any]:
    """Gather market overview: total fund count and category distribution.

    Returns total fund count, breakdown by category and by operation mode.
    """
    total_funds = db.scalar(select(func.count(FundMain.id))) or 0

    cat_rows = db.execute(
        select(FundMain.category, func.count(FundMain.id)).group_by(FundMain.category)
    ).all()
    by_category = {(cat or "未分类"): count for cat, count in cat_rows}

    mode_rows = db.execute(
        select(FundMain.operation_mode, func.count(FundMain.id)).group_by(
            FundMain.operation_mode
        )
    ).all()
    by_operation_mode = {(mode or "未知"): count for mode, count in mode_rows}

    return {
        "total_funds": total_funds,
        "by_category": by_category,
        "by_operation_mode": by_operation_mode,
    }


# ============================================================
# Dashboard orchestration
# ============================================================


def generate_dashboard(
    db: Session, fund_codes: list[str] | None = None
) -> DashboardData:
    """Generate the full dashboard by gathering all 5 panels.

    Catches exceptions per-panel and adds warnings for failed panels so
    that a single panel failure does not break the entire dashboard.

    Args:
        db: Database session.
        fund_codes: Optional list of fund codes to filter today_changes.

    Returns:
        DashboardData with all panels populated (or empty on failure).
    """
    warnings: list[str] = []

    panels: dict[str, Any] = {}
    panel_specs = [
        ("today_changes", lambda: gather_today_changes(db, fund_codes)),
        ("pool_monitoring", lambda: gather_pool_monitoring(db)),
        ("algorithm_alerts", lambda: gather_algorithm_alerts(db)),
        ("ai_alerts", lambda: gather_ai_alerts(db)),
        ("market_overview", lambda: gather_market_overview(db)),
    ]

    for name, gather_fn in panel_specs:
        try:
            panels[name] = gather_fn()
        except Exception as exc:
            db.rollback()
            panels[name] = {"error": str(exc)}
            warnings.append(f"面板 {name} 生成失败: {exc}")

    # 把 today_changes 中的跳过基金汇总为可读 warning
    tc_skipped = (panels.get("today_changes") or {}).get("skipped_funds") or []
    if tc_skipped:
        codes = [s.get("fund_code", "?") for s in tc_skipped[:5]]
        more = "" if len(tc_skipped) <= 5 else f" 等 {len(tc_skipped)} 只"
        warnings.append(
            f"今日变动跳过 {len(tc_skipped)} 只基金（净值缺失/为零）:{','.join(codes)}{more}"
        )

    return DashboardData(
        today_changes=panels.get("today_changes", {}),
        pool_monitoring=panels.get("pool_monitoring", {}),
        algorithm_alerts=panels.get("algorithm_alerts", {}),
        ai_alerts=panels.get("ai_alerts", {}),
        market_overview=panels.get("market_overview", {}),
        generated_at=utc_now(),
        warnings=warnings,
    )
