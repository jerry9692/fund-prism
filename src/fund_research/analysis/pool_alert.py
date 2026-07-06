"""
Fund Pool Alert Management (Phase 3, P3.4).

Implements alert checks for funds tracked in a user-defined pool. Each check
compares the latest data points and returns an AlertRecordData (or None) when
a threshold is breached. The scan_pool_alerts() entry point runs the enabled
checks across every fund in a pool. Rule/record persistence helpers wrap the
PoolAlertRule / PoolAlertRecord tables.

Alert types:
1. nav_change — 单日净值异动
2. ranking_change — 同类排名升降
3. manager_change — 基金经理变更
4. scale_change — 规模异常变动
5. style_drift — 风格漂移（复用 anomaly.detect_style_drift）
6. score_change — 评分跳变

References:
- v0.4 requirements §12.4 基金池提醒
- v0.4 requirements §5.5 Conclusion Credibility Gating
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundManagerTenure,
    FundNAV,
    FundScale,
)
from fund_research.db.models_phase2 import (
    FundPoolMember as DbFundPoolMember,
)
from fund_research.db.models_phase2 import (
    ScoringResult,
)
from fund_research.db.models_phase3 import (
    PoolAlertRecord,
    PoolAlertRule,
)
from fund_research.utils import nav_value, safe_float, utc_now

ALGORITHM_NAME = "pool_alert"
ALGORITHM_VERSION = "0.1.0"

ALERT_TYPES: dict[str, dict[str, Any]] = {
    "nav_change": {"description": "净值异动", "default_params": {"threshold": 0.03}},
    "ranking_change": {"description": "排名变化", "default_params": {"threshold": 0.20}},
    "manager_change": {"description": "经理变更", "default_params": {}},
    "scale_change": {"description": "规模异常", "default_params": {"threshold": 0.30}},
    "style_drift": {"description": "风格漂移", "default_params": {}},
    "score_change": {"description": "评分跳变", "default_params": {"threshold": 10.0}},
}


@dataclass
class AlertRecordData:
    """Single pool alert detection result."""

    fund_code: str
    alert_type: str
    severity: str  # "info" | "warning" | "critical"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    conclusion_status: str = "observation"

    def to_data(self) -> dict[str, Any]:
        """Return API-friendly data."""
        return {
            "fund_code": self.fund_code,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
            "conclusion_status": self.conclusion_status,
            "algorithm_name": ALGORITHM_NAME,
            "algorithm_version": ALGORITHM_VERSION,
        }


# ============================================================
# Helpers
# ============================================================


def _merge_params(alert_type: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user-supplied params over alert type defaults."""
    merged = dict(ALERT_TYPES.get(alert_type, {}).get("default_params", {}))
    if params:
        merged.update(params)
    return merged


# ============================================================
# Alert checks
# ============================================================


def check_nav_change(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AlertRecordData | None:
    """Detect NAV daily change anomaly between the latest two trade dates.

    Flags if the day-over-day change rate exceeds threshold (default 3%).
    severity: "warning" if change > 5%, otherwise "info".
    """
    p = _merge_params("nav_change", params)
    threshold = float(p.get("threshold", 0.03))

    rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date.desc())
        .limit(2)
    ).all()

    if len(rows) < 2:
        return None

    latest, prev = rows[0], rows[1]
    latest_val = nav_value(latest)
    prev_val = nav_value(prev)
    if latest_val is None or prev_val is None or prev_val == 0:
        return None

    change_rate = (latest_val - prev_val) / prev_val
    if abs(change_rate) <= threshold:
        return None

    severity = "warning" if abs(change_rate) > 0.05 else "info"
    return AlertRecordData(
        fund_code=fund_code,
        alert_type="nav_change",
        severity=severity,
        message=(
            f"净值异动：{fund_code} 单日变动 {change_rate * 100:+.2f}% "
            f"（{prev.trade_date} → {latest.trade_date}）"
        ),
        detail={
            "latest_date": str(latest.trade_date),
            "previous_date": str(prev.trade_date),
            "latest_nav": round(latest_val, 4),
            "previous_nav": round(prev_val, 4),
            "change_rate": round(change_rate, 4),
            "threshold": threshold,
        },
    )


def check_scale_change(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AlertRecordData | None:
    """Detect fund scale anomaly between the latest two reporting periods.

    Flags if the total-nav change rate exceeds threshold (default 30%).
    severity: "critical" if change > 50%, otherwise "warning".
    """
    p = _merge_params("scale_change", params)
    threshold = float(p.get("threshold", 0.30))

    rows = db.scalars(
        select(FundScale)
        .where(FundScale.fund_code == fund_code)
        .order_by(FundScale.report_date.desc())
        .limit(2)
    ).all()

    if len(rows) < 2:
        return None

    latest, prev = rows[0], rows[1]
    latest_val = safe_float(latest.total_nav)
    prev_val = safe_float(prev.total_nav)
    if latest_val is None or prev_val is None or prev_val == 0:
        return None

    change_rate = (latest_val - prev_val) / prev_val
    if abs(change_rate) <= threshold:
        return None

    severity = "critical" if abs(change_rate) > 0.50 else "warning"
    return AlertRecordData(
        fund_code=fund_code,
        alert_type="scale_change",
        severity=severity,
        message=(
            f"规模异常：{fund_code} 资产净值从 {prev_val:.2f} 亿元变动至 "
            f"{latest_val:.2f} 亿元（{change_rate * 100:+.2f}%）"
        ),
        detail={
            "latest_date": str(latest.report_date),
            "previous_date": str(prev.report_date),
            "latest_total_nav": round(latest_val, 4),
            "previous_total_nav": round(prev_val, 4),
            "change_rate": round(change_rate, 4),
            "threshold": threshold,
        },
    )


def check_manager_change(
    db: Session, fund_code: str, _params: dict[str, Any] | None = None
) -> AlertRecordData | None:
    """Detect fund manager change within the last 30 days.

    Flags if a FundManagerTenure record started within the lookback window.
    severity: "info".
    """
    cutoff = utc_now().date() - timedelta(days=30)
    tenure = db.scalars(
        select(FundManagerTenure)
        .where(
            FundManagerTenure.fund_code == fund_code,
            FundManagerTenure.start_date >= cutoff,
        )
        .order_by(FundManagerTenure.start_date.desc())
        .limit(1)
    ).first()

    if tenure is None:
        return None

    return AlertRecordData(
        fund_code=fund_code,
        alert_type="manager_change",
        severity="info",
        message=f"经理变更：{tenure.manager_id} 于 {tenure.start_date} 起任职 {fund_code}",
        detail={
            "manager_id": tenure.manager_id,
            "start_date": str(tenure.start_date),
            "is_current": bool(tenure.is_current),
            "lookback_days": 30,
        },
    )


def check_score_change(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AlertRecordData | None:
    """Detect total-score jump between the latest two scoring runs.

    Flags if the total_score change exceeds threshold (default 10 points).
    severity: "warning" if change > 20, otherwise "info".
    """
    p = _merge_params("score_change", params)
    threshold = float(p.get("threshold", 10.0))

    rows = db.scalars(
        select(ScoringResult)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc())
        .limit(2)
    ).all()

    if len(rows) < 2:
        return None

    latest, prev = rows[0], rows[1]
    latest_score = safe_float(latest.total_score)
    prev_score = safe_float(prev.total_score)
    if latest_score is None or prev_score is None:
        return None

    change = latest_score - prev_score
    if abs(change) <= threshold:
        return None

    severity = "warning" if abs(change) > 20 else "info"
    direction = "up" if change > 0 else "down"
    return AlertRecordData(
        fund_code=fund_code,
        alert_type="score_change",
        severity=severity,
        message=(
            f"评分跳变：{fund_code} 总分从 {prev_score:.1f} 变动至 {latest_score:.1f}"
            f"（{direction} {abs(change):.1f} 分）"
        ),
        detail={
            "latest_date": str(latest.calc_date),
            "previous_date": str(prev.calc_date),
            "latest_score": round(latest_score, 2),
            "previous_score": round(prev_score, 2),
            "change": round(change, 2),
            "threshold": threshold,
            "score_version": latest.score_version,
        },
    )


def check_ranking_change(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AlertRecordData | None:
    """Detect peer-group percentile-rank shift between the latest two scoring runs.

    ScoringResult.percentile_rank is stored as a fraction in [0, 1] where 1.0
    is the top rank. Flags if the absolute change exceeds threshold (default
    0.20, i.e. 20 percentile points). severity: "warning" if change > 0.40,
    otherwise "info".
    """
    p = _merge_params("ranking_change", params)
    threshold = float(p.get("threshold", 0.20))

    rows = db.scalars(
        select(ScoringResult)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc())
        .limit(2)
    ).all()

    if len(rows) < 2:
        return None

    latest, prev = rows[0], rows[1]
    latest_rank = safe_float(latest.percentile_rank)
    prev_rank = safe_float(prev.percentile_rank)
    if latest_rank is None or prev_rank is None:
        return None

    change = latest_rank - prev_rank
    if abs(change) <= threshold:
        return None

    severity = "warning" if abs(change) > 0.40 else "info"
    direction = "上升" if change > 0 else "下降"
    return AlertRecordData(
        fund_code=fund_code,
        alert_type="ranking_change",
        severity=severity,
        message=(
            f"排名变化：{fund_code} 同类百分位从 {prev_rank * 100:.1f}% "
            f"变动至 {latest_rank * 100:.1f}%（{direction} {abs(change) * 100:.1f} 个百分点）"
        ),
        detail={
            "latest_date": str(latest.calc_date),
            "previous_date": str(prev.calc_date),
            "latest_percentile_rank": round(latest_rank, 4),
            "previous_percentile_rank": round(prev_rank, 4),
            "change": round(change, 4),
            "threshold": threshold,
            "score_version": latest.score_version,
        },
    )


def check_style_drift(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AlertRecordData | None:
    """Detect style exposure drift by reusing anomaly.detect_style_drift.

    Delegates the statistical detection (latest vs historical mean ± std) to
    the P3.3 anomaly engine and converts a triggered AnomalyItem into an
    AlertRecordData. severity follows the anomaly rule ("warning").
    """
    # Lazy import to keep module-load graph acyclic.
    from fund_research.analysis.anomaly import detect_style_drift

    item = detect_style_drift(db, fund_code, params)
    if item is None:
        return None

    return AlertRecordData(
        fund_code=fund_code,
        alert_type="style_drift",
        severity=item.severity,
        message=item.description,
        detail=item.detail,
        conclusion_status=item.conclusion_status,
    )


# Alert type → checker function mapping.
_ALERT_CHECKERS: dict[str, Any] = {
    "nav_change": check_nav_change,
    "ranking_change": check_ranking_change,
    "manager_change": check_manager_change,
    "scale_change": check_scale_change,
    "style_drift": check_style_drift,
    "score_change": check_score_change,
}


# ============================================================
# Scan
# ============================================================


def scan_pool_alerts(
    db: Session,
    pool_id: int,
    alert_types: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[list[AlertRecordData], list[str]]:
    """Run enabled alert checks across all funds in a pool.

    Args:
        db: Database session.
        pool_id: Pool identifier whose members are scanned.
        alert_types: Optional list of alert types to run. If None, all
            declared alert types are attempted (unimplemented ones are skipped).
        params: Optional dict mapping alert_type → param overrides,
            e.g. {"nav_change": {"threshold": 0.05}}.

    Returns:
        Tuple of (list of AlertRecordData results, list of warning strings).
        Only includes triggered alerts in the result list.
    """
    enabled_types = list(alert_types) if alert_types else list(ALERT_TYPES.keys())
    params = params or {}

    fund_codes = db.scalars(
        select(DbFundPoolMember.fund_code).where(DbFundPoolMember.pool_id == pool_id)
    ).all()

    results: list[AlertRecordData] = []
    warnings: list[str] = []
    for fund_code in fund_codes:
        for alert_type in enabled_types:
            checker = _ALERT_CHECKERS.get(alert_type)
            if checker is None:
                continue
            rule_params = params.get(alert_type)
            try:
                item = checker(db, fund_code, rule_params)
                if item is not None:
                    results.append(item)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                warnings.append(
                    f"提醒检查失败: fund={fund_code}, type={alert_type}: {exc}"
                )

    return results, warnings


# ============================================================
# Rule & record persistence
# ============================================================


def persist_alerts(db: Session, pool_id: int, alerts: list[AlertRecordData]) -> list:
    """Persist a list of AlertRecordData as PoolAlertRecord objects."""
    records = []
    for alert in alerts:
        record = PoolAlertRecord(
            pool_id=pool_id,
            fund_code=alert.fund_code,
            alert_type=alert.alert_type,
            severity=alert.severity,
            message=alert.message,
            detail=alert.detail,
        )
        db.add(record)
        records.append(record)
    db.flush()
    return records


def create_alert_rule(
    db: Session,
    pool_id: int,
    fund_code: str,
    alert_type: str,
    params: dict[str, Any] | None = None,
) -> PoolAlertRule:
    """Create a PoolAlertRule record (flushed, not committed)."""
    rule = PoolAlertRule(
        pool_id=pool_id,
        fund_code=fund_code,
        alert_type=alert_type,
        params=params or {},
        is_active=True,
    )
    db.add(rule)
    db.flush()
    return rule


def get_alert_rules(
    db: Session,
    pool_id: int,
    fund_code: str | None = None,
) -> list[PoolAlertRule]:
    """Get alert rules for a pool, optionally filtered by fund_code."""
    query = select(PoolAlertRule).where(PoolAlertRule.pool_id == pool_id)
    if fund_code:
        query = query.where(PoolAlertRule.fund_code == fund_code)
    query = query.order_by(PoolAlertRule.created_at.desc())
    return list(db.scalars(query).all())


def get_alert_records(
    db: Session,
    pool_id: int | None = None,
    fund_code: str | None = None,
    is_read: bool | None = None,
    limit: int = 50,
) -> list[PoolAlertRecord]:
    """Query alert records with optional filters."""
    query = select(PoolAlertRecord)
    if pool_id is not None:
        query = query.where(PoolAlertRecord.pool_id == pool_id)
    if fund_code:
        query = query.where(PoolAlertRecord.fund_code == fund_code)
    if is_read is not None:
        query = query.where(PoolAlertRecord.is_read == is_read)
    query = query.order_by(PoolAlertRecord.triggered_at.desc()).limit(limit)
    return list(db.scalars(query).all())


def mark_alert_read(db: Session, alert_id: int) -> PoolAlertRecord | None:
    """Set is_read=True for an alert record. Returns the record or None."""
    record = db.scalars(
        select(PoolAlertRecord).where(PoolAlertRecord.id == alert_id).limit(1)
    ).first()
    if record is None:
        return None
    record.is_read = True
    db.flush()
    return record
