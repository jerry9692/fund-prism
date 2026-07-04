"""
Anomaly Detection Rule Engine (Phase 3).

Implements 5 anomaly detection rules per v0.4 requirements §12.3:
1. style_drift — Detect style exposure drift over time
2. classification_deviation — Detect fund actual style vs contract category mismatch
3. low_confidence_high_score — Detect high score but low confidence funds
4. concentration_anomaly — Detect holding concentration outliers vs peers
5. holder_structure_anomaly — Detect holder structure changes

Each rule is a standalone detector that queries the database and returns an
AnomalyItem (or None). The scan_anomalies() entry point runs enabled rules
across a list of funds. Results can be persisted to the anomaly_record table
via persist_anomaly().

References:
- v0.4 requirements §12.3 Anomaly Detection
- v0.4 requirements §5.5 Conclusion Credibility Gating
"""

from dataclasses import dataclass
from datetime import datetime
from statistics import mean, stdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundDisclosedHoldings,
    FundMain,
    HolderStructure,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import ScoringResult
from fund_research.db.models_phase3 import AnomalyRecord
from fund_research.utils import safe_float

ALGORITHM_NAME = "anomaly_detection"
ALGORITHM_VERSION = "0.1.0"

ANOMALY_RULES: dict[str, dict[str, Any]] = {
    "style_drift": {
        "severity": "warning",
        "default_params": {"std_threshold": 2.0, "lookback_quarters": 4},
    },
    "classification_deviation": {
        "severity": "warning",
        "default_params": {"industry_threshold": 0.5},
    },
    "low_confidence_high_score": {
        "severity": "needs_review",
        "default_params": {"score_threshold": 70.0, "confidence_threshold": 0.6},
    },
    "concentration_anomaly": {
        "severity": "observation",
        "default_params": {"iqr_multiplier": 1.5},
    },
    "holder_structure_anomaly": {
        "severity": "observation",
        "default_params": {"change_threshold": 0.20},
    },
}

# Confidence string → numeric score mapping for threshold comparison.
# Maps ConfidenceLevel enum values to approximate numeric confidence.
_CONFIDENCE_NUMERIC: dict[str, float] = {
    "high": 1.0,
    "medium": 0.8,
    "low": 0.4,
    "needs_review": 0.2,
}

# Keywords indicating a sector/theme fund for classification_deviation rule.
_SECTOR_FUND_KEYWORDS: tuple[str, ...] = ("行业", "主题", "概念")


@dataclass
class AnomalyItem:
    """Single anomaly detection result."""

    fund_code: str
    rule_name: str
    severity: str  # "warning" | "needs_review" | "observation"
    description: str
    detail: dict[str, Any] | None = None
    conclusion_status: str = "observation"

    def to_data(self) -> dict[str, Any]:
        """Return API-friendly data."""
        return {
            "fund_code": self.fund_code,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "description": self.description,
            "detail": self.detail,
            "conclusion_status": self.conclusion_status,
            "algorithm_name": ALGORITHM_NAME,
            "algorithm_version": ALGORITHM_VERSION,
        }


# ============================================================
# Helpers
# ============================================================


def _merge_params(rule_name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user-supplied params over rule defaults."""
    merged = dict(ANOMALY_RULES.get(rule_name, {}).get("default_params", {}))
    if params:
        merged.update(params)
    return merged


def _median(values: list[float]) -> float | None:
    """Compute median of a list; returns None for empty input."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _quartiles(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """Compute Q1, median, Q3 using linear interpolation.

    Returns (Q1, Q2, Q3); all None for empty input.
    """
    if not values:
        return None, None, None
    s = sorted(values)
    n = len(s)

    def _percentile(p: float) -> float:
        if n == 1:
            return s[0]
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    return _percentile(0.25), _median(s), _percentile(0.75)


def _is_sector_fund(fund: FundMain | None) -> bool:
    """Heuristic check for sector/theme fund classification."""
    if fund is None:
        return False
    for field_val in (fund.investment_type, fund.sub_category, fund.short_name):
        if field_val and any(kw in field_val for kw in _SECTOR_FUND_KEYWORDS):
            return True
    return False


def _get_latest_stock_holdings(db: Session, fund_code: str) -> list[FundDisclosedHoldings]:
    """Get the latest reported stock holdings for a fund."""
    rows = db.scalars(
        select(FundDisclosedHoldings)
        .where(
            FundDisclosedHoldings.fund_code == fund_code,
            FundDisclosedHoldings.asset_type == "股票",
        )
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(200)
    ).all()

    if not rows:
        return []

    latest_date = rows[0].report_date
    return [h for h in rows if h.report_date == latest_date]


def _compute_concentration(
    holdings: list[FundDisclosedHoldings],
) -> tuple[float | None, float | None]:
    """Compute top10 concentration and industry HHI from holdings.

    Returns (top10_concentration, industry_hhi); values may be None.
    Weights are used in their stored percentage form (e.g. 5.0 for 5%),
    consistent across fund and peers.
    """
    if not holdings:
        return None, None

    weights = [abs(float(h.weight_pct)) for h in holdings if h.weight_pct is not None]
    if not weights:
        return None, None

    top10 = round(sum(weights[:10]), 4)

    # Industry HHI — aggregate weights by industry, then sum of squares
    industry_weights: dict[str, float] = {}
    for h in holdings:
        if h.weight_pct is None or not h.industry:
            continue
        w = abs(float(h.weight_pct))
        industry_weights[h.industry] = industry_weights.get(h.industry, 0.0) + w
    hhi = round(sum(w * w for w in industry_weights.values()), 4) if industry_weights else None

    return top10, hhi


# ============================================================
# Rule 1: Style Drift
# ============================================================


def detect_style_drift(db: Session, fund_code: str, params: dict[str, Any] | None = None) -> AnomalyItem | None:
    """Detect style exposure drift over time.

    Compares the latest style exposure against the historical mean ± std_threshold * std.
    Requires at least lookback_quarters data points.
    """
    p = _merge_params("style_drift", params)
    std_threshold = float(p.get("std_threshold", 2.0))
    lookback = int(p.get("lookback_quarters", 4))

    rows = db.scalars(
        select(StyleExposureResult)
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == "style",
        )
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(50)
    ).all()

    if len(rows) < lookback:
        return None

    # Collect per-dimension time series from exposure_values dicts.
    dim_series: dict[str, list[float]] = {}
    for row in rows:
        ev = row.exposure_values or {}
        for dim, val in ev.items():
            f = safe_float(val)
            if f is not None:
                dim_series.setdefault(dim, []).append(f)

    if not dim_series:
        return None

    latest = rows[0]
    latest_ev = latest.exposure_values or {}

    drifted_dims: list[dict[str, Any]] = []
    for dim, series in dim_series.items():
        if len(series) < 2:
            continue
        mu = mean(series)
        sigma = stdev(series)
        if sigma == 0:
            continue
        latest_val = safe_float(latest_ev.get(dim))
        if latest_val is None:
            continue
        z = abs(latest_val - mu) / sigma
        if z > std_threshold:
            drifted_dims.append(
                {
                    "dimension": dim,
                    "latest": round(latest_val, 4),
                    "historical_mean": round(mu, 4),
                    "historical_std": round(sigma, 4),
                    "z_score": round(z, 2),
                    "direction": "up" if latest_val > mu else "down",
                }
            )

    if not drifted_dims:
        return None

    dims_str = ", ".join(d["dimension"] for d in drifted_dims)
    return AnomalyItem(
        fund_code=fund_code,
        rule_name="style_drift",
        severity=ANOMALY_RULES["style_drift"]["severity"],
        description=f"风格漂移：{dims_str} 偏离历史均值超过 {std_threshold}σ",
        detail={
            "drifted_dimensions": drifted_dims,
            "latest_calc_date": str(latest.calc_date),
            "data_points": len(rows),
            "std_threshold": std_threshold,
        },
        conclusion_status="observation",
    )


# ============================================================
# Rule 2: Classification Deviation
# ============================================================


def detect_classification_deviation(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AnomalyItem | None:
    """Detect fund actual style vs contract category mismatch.

    Simplified check: if fund is categorized as a sector/theme fund but its top
    industry weight is below industry_threshold, flag a deviation.
    Full contract parsing is deferred to a later phase.
    """
    p = _merge_params("classification_deviation", params)
    industry_threshold = float(p.get("industry_threshold", 0.5))

    fund = db.scalars(select(FundMain).where(FundMain.fund_code == fund_code).limit(1)).first()

    if not _is_sector_fund(fund):
        return None

    row = db.scalars(
        select(StyleExposureResult)
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == "industry",
        )
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(1)
    ).first()

    if row is None or not row.exposure_values:
        return None

    ev = row.exposure_values
    sorted_items = sorted(
        ((k, safe_float(v)) for k, v in ev.items() if safe_float(v) is not None),
        key=lambda x: abs(x[1]),
        reverse=True,
    )
    if not sorted_items:
        return None

    top_industry, top_weight_raw = sorted_items[0]
    if top_weight_raw is None:
        return None

    # Normalize to fraction: exposure_values may store fractions (0.6) or percentages (60.0)
    top_weight = top_weight_raw / 100.0 if top_weight_raw > 1.5 else top_weight_raw

    if top_weight >= industry_threshold:
        return None

    return AnomalyItem(
        fund_code=fund_code,
        rule_name="classification_deviation",
        severity=ANOMALY_RULES["classification_deviation"]["severity"],
        description=(
            f"分类偏离：基金被归类为行业/主题基金，但第一大行业 "
            f"{top_industry} 权重仅 {top_weight * 100:.1f}% < {industry_threshold * 100:.0f}%"
        ),
        detail={
            "fund_category": fund.category if fund else None,
            "fund_sub_category": fund.sub_category if fund else None,
            "investment_type": fund.investment_type if fund else None,
            "top_industry": top_industry,
            "top_industry_weight": round(top_weight, 4),
            "industry_threshold": industry_threshold,
            "calc_date": str(row.calc_date),
        },
        conclusion_status="observation",
    )


# ============================================================
# Rule 3: Low Confidence High Score
# ============================================================


def detect_low_confidence_high_score(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AnomalyItem | None:
    """Detect high score but low confidence funds.

    Flags funds where total_score > score_threshold AND confidence is below
    confidence_threshold (mapped from string) OR contains_estimated is True.
    """
    p = _merge_params("low_confidence_high_score", params)
    score_threshold = float(p.get("score_threshold", 70.0))
    confidence_threshold = float(p.get("confidence_threshold", 0.6))

    row = db.scalars(
        select(ScoringResult)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc())
        .limit(1)
    ).first()

    if row is None or row.total_score is None:
        return None

    total_score = float(row.total_score)
    if total_score <= score_threshold:
        return None

    confidence_str = row.confidence
    confidence_numeric = _CONFIDENCE_NUMERIC.get(confidence_str, 0.5) if confidence_str else 0.5
    low_confidence = confidence_numeric < confidence_threshold
    has_estimated = bool(row.contains_estimated)

    if not low_confidence and not has_estimated:
        return None

    reasons: list[str] = []
    if low_confidence:
        reasons.append(f"置信度 {confidence_str}（数值 {confidence_numeric} < {confidence_threshold}）")
    if has_estimated:
        reasons.append("评分包含 estimated 维度")

    return AnomalyItem(
        fund_code=fund_code,
        rule_name="low_confidence_high_score",
        severity=ANOMALY_RULES["low_confidence_high_score"]["severity"],
        description=(f"高分低置信：总分 {total_score:.1f} > {score_threshold}，但 {'; '.join(reasons)}"),
        detail={
            "total_score": round(total_score, 2),
            "confidence": confidence_str,
            "confidence_numeric": confidence_numeric,
            "confidence_threshold": confidence_threshold,
            "contains_estimated": has_estimated,
            "calc_date": str(row.calc_date),
            "score_version": row.score_version,
        },
        conclusion_status="needs_review",
    )


# ============================================================
# Rule 4: Concentration Anomaly
# ============================================================


def detect_concentration_anomaly(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AnomalyItem | None:
    """Detect holding concentration outliers vs peers.

    Compares the fund's top10 concentration and industry HHI against
    same-category peers. Flags if either metric exceeds
    peer_median + iqr_multiplier * peer_iqr.
    Returns None if no peer data is available.
    """
    p = _merge_params("concentration_anomaly", params)
    iqr_multiplier = float(p.get("iqr_multiplier", 1.5))

    # Fund's own concentration
    own_holdings = _get_latest_stock_holdings(db, fund_code)
    own_top10, own_hhi = _compute_concentration(own_holdings)
    if own_top10 is None:
        return None

    # Get fund's category for peer lookup
    fund = db.scalars(select(FundMain).where(FundMain.fund_code == fund_code).limit(1)).first()
    if fund is None or not fund.category:
        return None

    peer_funds = db.scalars(
        select(FundMain.fund_code).where(
            FundMain.category == fund.category,
            FundMain.fund_code != fund_code,
        )
    ).all()

    if not peer_funds:
        return None

    # Compute peer concentrations
    peer_top10s: list[float] = []
    peer_hhis: list[float] = []
    for peer_code in peer_funds:
        peer_holdings = _get_latest_stock_holdings(db, peer_code)
        p_top10, p_hhi = _compute_concentration(peer_holdings)
        if p_top10 is not None:
            peer_top10s.append(p_top10)
        if p_hhi is not None:
            peer_hhis.append(p_hhi)

    if not peer_top10s:
        return None

    anomalies: list[dict[str, Any]] = []

    # Check top10 concentration
    q1_t, med_t, q3_t = _quartiles(peer_top10s)
    if med_t is not None and q1_t is not None and q3_t is not None:
        iqr_t = q3_t - q1_t
        threshold_t = med_t + iqr_multiplier * iqr_t
        if own_top10 > threshold_t:
            anomalies.append(
                {
                    "metric": "top10_concentration",
                    "fund_value": own_top10,
                    "peer_median": round(med_t, 4),
                    "peer_q1": round(q1_t, 4),
                    "peer_q3": round(q3_t, 4),
                    "peer_iqr": round(iqr_t, 4),
                    "threshold": round(threshold_t, 4),
                }
            )

    # Check industry HHI
    if own_hhi is not None and peer_hhis:
        q1_h, med_h, q3_h = _quartiles(peer_hhis)
        if med_h is not None and q1_h is not None and q3_h is not None:
            iqr_h = q3_h - q1_h
            threshold_h = med_h + iqr_multiplier * iqr_h
            if own_hhi > threshold_h:
                anomalies.append(
                    {
                        "metric": "industry_hhi",
                        "fund_value": own_hhi,
                        "peer_median": round(med_h, 4),
                        "peer_q1": round(q1_h, 4),
                        "peer_q3": round(q3_h, 4),
                        "peer_iqr": round(iqr_h, 4),
                        "threshold": round(threshold_h, 4),
                    }
                )

    if not anomalies:
        return None

    metrics_str = ", ".join(a["metric"] for a in anomalies)
    return AnomalyItem(
        fund_code=fund_code,
        rule_name="concentration_anomaly",
        severity=ANOMALY_RULES["concentration_anomaly"]["severity"],
        description=f"集中度异常：{metrics_str} 显著高于同类中位数 + {iqr_multiplier}×IQR",
        detail={
            "anomalies": anomalies,
            "category": fund.category,
            "peer_count": len(peer_top10s),
            "iqr_multiplier": iqr_multiplier,
        },
        conclusion_status="observation",
    )


# ============================================================
# Rule 5: Holder Structure Anomaly
# ============================================================


def detect_holder_structure_anomaly(
    db: Session, fund_code: str, params: dict[str, Any] | None = None
) -> AnomalyItem | None:
    """Detect holder structure changes.

    Flags if institutional holding percentage changed by more than
    change_threshold (default 0.20 = 20pp) between the latest two periods.
    """
    p = _merge_params("holder_structure_anomaly", params)
    change_threshold = float(p.get("change_threshold", 0.20))

    rows = db.scalars(
        select(HolderStructure)
        .where(HolderStructure.fund_code == fund_code)
        .order_by(HolderStructure.report_date.desc())
        .limit(2)
    ).all()

    if len(rows) < 2:
        return None

    latest = rows[0]
    prev = rows[1]

    latest_inst = safe_float(latest.institutional_pct)
    prev_inst = safe_float(prev.institutional_pct)
    if latest_inst is None or prev_inst is None:
        return None

    # Convert percentage values to fractions for threshold comparison
    latest_frac = latest_inst / 100.0
    prev_frac = prev_inst / 100.0
    if latest_frac is None or prev_frac is None:
        return None

    change = abs(latest_frac - prev_frac)
    if change <= change_threshold:
        return None

    direction = "up" if latest_frac > prev_frac else "down"

    return AnomalyItem(
        fund_code=fund_code,
        rule_name="holder_structure_anomaly",
        severity=ANOMALY_RULES["holder_structure_anomaly"]["severity"],
        description=(
            f"持有人结构异常：机构持有比例从 {prev_inst:.1f}% 变动至 {latest_inst:.1f}%，"
            f"变化 {change * 100:.1f}pp > {change_threshold * 100:.0f}pp"
        ),
        detail={
            "latest_report_date": str(latest.report_date),
            "previous_report_date": str(prev.report_date),
            "latest_institutional_pct": latest_inst,
            "previous_institutional_pct": prev_inst,
            "change_pp": round(change * 100, 2),
            "change_threshold_pp": round(change_threshold * 100, 2),
            "direction": direction,
        },
        conclusion_status="observation",
    )


# ============================================================
# Scan & Persist
# ============================================================

# Rule name → detector function mapping
_RULE_FUNCTIONS: dict[str, Any] = {
    "style_drift": detect_style_drift,
    "classification_deviation": detect_classification_deviation,
    "low_confidence_high_score": detect_low_confidence_high_score,
    "concentration_anomaly": detect_concentration_anomaly,
    "holder_structure_anomaly": detect_holder_structure_anomaly,
}


def scan_anomalies(
    db: Session,
    fund_codes: list[str],
    rules: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> list[AnomalyItem]:
    """Run anomaly detection rules across a list of funds.

    Args:
        db: Database session.
        fund_codes: List of fund codes to scan.
        rules: Optional list of rule names to run. If None, all rules run.
        params: Optional dict mapping rule names to param overrides.
            e.g. {"style_drift": {"std_threshold": 3.0}}

    Returns:
        List of AnomalyItem results (only includes detected anomalies).
    """
    enabled_rules = list(rules) if rules else list(ANOMALY_RULES.keys())
    params = params or {}

    results: list[AnomalyItem] = []
    for fund_code in fund_codes:
        for rule_name in enabled_rules:
            detector = _RULE_FUNCTIONS.get(rule_name)
            if detector is None:
                continue
            rule_params = params.get(rule_name)
            item = detector(db, fund_code, rule_params)
            if item is not None:
                results.append(item)

    return results


def persist_anomaly(
    db: Session,
    item: AnomalyItem,
    scope: str = "all",
    scope_id: str | None = None,
) -> AnomalyRecord:
    """Persist an AnomalyItem to the anomaly_record table.

    Args:
        db: Database session.
        item: The AnomalyItem to persist.
        scope: Scope label (e.g. "all", "pool", "fund").
        scope_id: Optional scope identifier (e.g. pool ID).

    Returns:
        The persisted AnomalyRecord (flushed, not committed).
    """
    row = AnomalyRecord(
        fund_code=item.fund_code,
        rule_name=item.rule_name,
        severity=item.severity,
        description=item.description,
        detail=item.detail,
        scope=scope,
        scope_id=scope_id,
        conclusion_status=item.conclusion_status,
        detected_at=datetime.now(),
    )
    db.add(row)
    db.flush()
    return row
