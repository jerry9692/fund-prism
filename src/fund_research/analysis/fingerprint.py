"""
Fund Fingerprint — standardized feature vectors for similarity search,
clustering, anomaly detection, and AI context compression.

Each fund gets a multi-dimensional vector grouped by dimension categories:
- return_risk: annualized return, volatility, sharpe, max drawdown, etc.
- style_exposure: large/mid/small cap, growth/value exposures
- industry_exposure: top-5 industry weights, HHI concentration
- holding_features: top-10 concentration, holding count, turnover estimate
- alpha: selection return, allocation return from attribution
- scale: fund scale, scale change rate
- team: manager tenure days, change frequency

Different fund types use different templates (active_equity vs index_fund).
Estimated dimensions (turnover, dynamic attribution residual) use estimated_*
prefix and are flagged in vector_metadata.

References:
- v0.4 requirements §6.3.5 Fund Fingerprint
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundDisclosedHoldings,
    FundMain,
    FundManagerTenure,
    FundScale,
    StaticAttributionResult,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import ScoringResult, TradingAbilityResult
from fund_research.db.models_phase3 import FundFingerprint
from fund_research.utils import safe_float

ALGORITHM_NAME = "fund_fingerprint"
ALGORITHM_VERSION = "0.1.0"

# Dimension group weights per fund type template
FINGERPRINT_TEMPLATES: dict[str, dict[str, float]] = {
    "active_equity": {
        "return_risk": 1.0,
        "style_exposure": 1.0,
        "industry_exposure": 1.0,
        "holding_features": 1.0,
        "alpha": 1.0,
        "scale": 0.5,
        "team": 0.5,
    },
    "index_fund": {
        "return_risk": 0.5,
        "style_exposure": 1.0,
        "industry_exposure": 1.0,
        "holding_features": 0.5,
        "alpha": 0.0,
        "scale": 0.5,
        "team": 0.3,
    },
    "default": {
        "return_risk": 1.0,
        "style_exposure": 1.0,
        "industry_exposure": 1.0,
        "holding_features": 1.0,
        "alpha": 0.5,
        "scale": 0.5,
        "team": 0.5,
    },
}

# Dimensions that come from estimated sources
ESTIMATED_DIMENSIONS = {"holding_features.estimated_turnover", "alpha.estimated_residual_pct"}


@dataclass
class FingerprintResult:
    """Fingerprint computation payload."""

    fund_code: str
    calc_date: date
    fund_type: str | None
    template_name: str
    vector: dict[str, dict[str, float | None]]
    vector_metadata: dict[str, dict[str, str]]
    missing_dimensions: list[str] = field(default_factory=list)
    contains_estimated: bool = False
    warnings: list[str] = field(default_factory=list)
    confidence: str | None = None
    conclusion_status: str = "computed"

    def to_data(self) -> dict[str, Any]:
        """Return API-friendly data."""
        return {
            "fund_code": self.fund_code,
            "calc_date": str(self.calc_date),
            "fund_type": self.fund_type,
            "template_name": self.template_name,
            "vector": self.vector,
            "vector_metadata": self.vector_metadata,
            "missing_dimensions": self.missing_dimensions,
            "contains_estimated": self.contains_estimated,
            "confidence": self.confidence,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


def _select_template(fund: FundMain | None) -> str:
    """Choose fingerprint template based on fund sub-category."""
    if fund is None or fund.sub_category is None:
        return "default"
    sub = fund.sub_category
    if sub in ("被动指数", "ETF", "ETF联接", "指数增强"):
        return "index_fund"
    return "active_equity"


def _gather_return_risk(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str]]:
    """Gather return/risk metrics from the latest scoring result sub-scores."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []

    row = db.scalars(
        select(ScoringResult)
        .where(ScoringResult.fund_code == fund_code)
        .order_by(ScoringResult.calc_date.desc())
        .limit(1)
    ).first()

    if row and row.sub_scores:
        subs = row.sub_scores
        vector["return_score"] = subs.get("return")
        vector["risk_score"] = subs.get("risk")
        meta["return_score"] = "computed"
        meta["risk_score"] = "computed"
    else:
        missing.extend(["return_risk.return_score", "return_risk.risk_score"])

    return vector, meta, missing


def _gather_style_exposure(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str]]:
    """Gather style exposure from the latest style_exposure_result."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []

    row = db.scalars(
        select(StyleExposureResult)
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == "style",
        )
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(1)
    ).first()

    if row and row.exposure_values:
        ev = row.exposure_values
        vector["large_cap"] = safe_float(ev.get("large_cap"))
        vector["mid_cap"] = safe_float(ev.get("mid_cap"))
        vector["small_cap"] = safe_float(ev.get("small_cap"))
        vector["growth"] = safe_float(ev.get("growth"))
        vector["value"] = safe_float(ev.get("value"))
        for k in vector:
            meta[k] = "computed"
        if row.r_squared is not None:
            vector["r_squared"] = float(row.r_squared)
            meta["r_squared"] = "computed"
    else:
        missing.append("style_exposure")

    return vector, meta, missing


def _gather_industry_exposure(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str]]:
    """Gather industry exposure from the latest industry-style style_exposure_result."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []

    row = db.scalars(
        select(StyleExposureResult)
        .where(
            StyleExposureResult.fund_code == fund_code,
            StyleExposureResult.exposure_type == "industry",
        )
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(1)
    ).first()

    if row and row.exposure_values:
        ev = row.exposure_values
        # Sort industries by weight, take top 5
        sorted_items = sorted(
            ((k, v) for k, v in ev.items() if v is not None),
            key=lambda x: abs(x[1]),
            reverse=True,
        )
        for i, (_ind, w) in enumerate(sorted_items[:5]):
            vector[f"top_industry_{i+1}"] = safe_float(w)
            meta[f"top_industry_{i+1}"] = "fact"
        # HHI concentration
        weights = [abs(v) for _, v in sorted_items if v is not None]
        if weights:
            hhi = sum(w * w for w in weights)
            vector["industry_hhi"] = round(hhi, 4)
            meta["industry_hhi"] = "fact"
    else:
        missing.append("industry_exposure")

    return vector, meta, missing


def _gather_holding_features(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str], bool]:
    """Gather holding features from disclosed holdings and trading ability."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []
    has_estimated = False

    # Top-10 concentration and holding count from disclosed holdings
    holdings = db.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(500)
    ).all()

    if holdings:
        # Group by report_date, take the latest
        latest_date = holdings[0].report_date
        latest_holdings = [h for h in holdings if h.report_date == latest_date]
        weights: list[float] = []
        for h in latest_holdings:
            w = safe_float(h.weight_pct)
            if w is not None:
                weights.append(abs(w))
        if weights:
            weights_sorted = sorted(weights, reverse=True)
            vector["top10_concentration"] = round(sum(weights_sorted[:10]), 4)
            vector["holding_count"] = float(len(weights_sorted))
            meta["top10_concentration"] = "fact"
            meta["holding_count"] = "fact"
    else:
        missing.extend(["holding_features.top10_concentration", "holding_features.holding_count"])

    # Estimated turnover from trading ability
    trading = db.scalars(
        select(TradingAbilityResult)
        .where(TradingAbilityResult.fund_code == fund_code)
        .order_by(TradingAbilityResult.calc_date.desc())
        .limit(1)
    ).first()

    if trading and trading.estimated_turnover_rate is not None:
        vector["estimated_turnover"] = float(trading.estimated_turnover_rate)
        meta["estimated_turnover"] = "estimated"
        has_estimated = True
    else:
        missing.append("holding_features.estimated_turnover")

    return vector, meta, missing, has_estimated


def _gather_alpha(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str], bool]:
    """Gather alpha metrics from static attribution."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []
    has_estimated = False

    row = db.scalars(
        select(StaticAttributionResult)
        .where(StaticAttributionResult.fund_code == fund_code)
        .order_by(StaticAttributionResult.report_date.desc())
        .limit(1)
    ).first()

    if row:
        if row.selection_effect is not None:
            vector["selection_return"] = float(row.selection_effect)
            meta["selection_return"] = "observation"
        else:
            missing.append("alpha.selection_return")

        if row.allocation_effect is not None:
            vector["allocation_return"] = float(row.allocation_effect)
            meta["allocation_return"] = "observation"
        else:
            missing.append("alpha.allocation_return")

        if row.residual_pct is not None:
            vector["estimated_residual_pct"] = float(row.residual_pct)
            meta["estimated_residual_pct"] = "estimated"
            has_estimated = True
        else:
            missing.append("alpha.estimated_residual_pct")
    else:
        missing.append("alpha")

    return vector, meta, missing, has_estimated


def _gather_scale(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str]]:
    """Gather scale metrics."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []

    rows = db.scalars(
        select(FundScale)
        .where(FundScale.fund_code == fund_code)
        .order_by(FundScale.report_date.desc())
        .limit(2)
    ).all()

    if rows:
        latest = rows[0]
        if latest.total_nav is not None:
            vector["scale"] = float(latest.total_nav)
            meta["scale"] = "computed"

        if len(rows) > 1 and rows[0].total_nav and rows[1].total_nav:
            prev = float(rows[1].total_nav)
            if prev > 0:
                change = (float(rows[0].total_nav) - prev) / prev
                vector["scale_change_rate"] = round(change, 4)
                meta["scale_change_rate"] = "computed"
    else:
        missing.append("scale")

    return vector, meta, missing


def _gather_team(
    db: Session, fund_code: str
) -> tuple[dict[str, float | None], dict[str, str], list[str]]:
    """Gather team stability metrics."""
    vector: dict[str, float | None] = {}
    meta: dict[str, str] = {}
    missing: list[str] = []

    tenures = db.scalars(
        select(FundManagerTenure)
        .where(FundManagerTenure.fund_code == fund_code)
        .order_by(FundManagerTenure.start_date.desc())
        .limit(10)
    ).all()

    if tenures:
        # Current manager tenure
        current = [t for t in tenures if t.end_date is None]
        if current:
            latest_start = min(t.start_date for t in current if t.start_date)
            tenure_days = (date.today() - latest_start).days
            vector["manager_tenure_days"] = float(tenure_days)
            meta["manager_tenure_days"] = "computed"

        # Manager change frequency (changes in last 3 years)
        three_years_ago = date.today().replace(year=date.today().year - 3)
        changes = sum(1 for t in tenures if t.start_date and t.start_date > three_years_ago)
        vector["manager_change_count_3y"] = float(changes)
        meta["manager_change_count_3y"] = "computed"
    else:
        missing.append("team")

    return vector, meta, missing


def generate_fingerprint(
    db: Session,
    fund_code: str,
    calc_date: date | None = None,
) -> FingerprintResult:
    """Generate a standardized fingerprint vector for a fund.

    Pulls data from multiple analysis result tables and assembles
    a multi-dimensional feature vector grouped by dimension categories.
    """
    if calc_date is None:
        calc_date = date.today()

    # Get fund basic info
    fund = db.scalars(
        select(FundMain).where(FundMain.fund_code == fund_code).limit(1)
    ).first()

    template_name = _select_template(fund)
    fund_type = fund.sub_category if fund else None
    template = FINGERPRINT_TEMPLATES.get(template_name, FINGERPRINT_TEMPLATES["default"])

    vector: dict[str, dict[str, float | None]] = {}
    metadata: dict[str, dict[str, str]] = {}
    all_missing: list[str] = []
    contains_estimated = False
    warnings: list[str] = []

    # Gather each dimension group
    if template.get("return_risk", 0) > 0:
        v, m, miss = _gather_return_risk(db, fund_code)
        if v:
            vector["return_risk"] = v
            metadata["return_risk"] = m
        all_missing.extend(miss)

    if template.get("style_exposure", 0) > 0:
        v, m, miss = _gather_style_exposure(db, fund_code)
        if v:
            vector["style_exposure"] = v
            metadata["style_exposure"] = m
        all_missing.extend(miss)

    if template.get("industry_exposure", 0) > 0:
        v, m, miss = _gather_industry_exposure(db, fund_code)
        if v:
            vector["industry_exposure"] = v
            metadata["industry_exposure"] = m
        all_missing.extend(miss)

    if template.get("holding_features", 0) > 0:
        v, m, miss, est = _gather_holding_features(db, fund_code)
        if v:
            vector["holding_features"] = v
            metadata["holding_features"] = m
        all_missing.extend(miss)
        contains_estimated = contains_estimated or est

    if template.get("alpha", 0) > 0:
        v, m, miss, est = _gather_alpha(db, fund_code)
        if v:
            vector["alpha"] = v
            metadata["alpha"] = m
        all_missing.extend(miss)
        contains_estimated = contains_estimated or est

    if template.get("scale", 0) > 0:
        v, m, miss = _gather_scale(db, fund_code)
        if v:
            vector["scale"] = v
            metadata["scale"] = m
        all_missing.extend(miss)

    if template.get("team", 0) > 0:
        v, m, miss = _gather_team(db, fund_code)
        if v:
            vector["team"] = v
            metadata["team"] = m
        all_missing.extend(miss)

    # Determine confidence
    non_missing_ratio = 1.0
    total_dims = len(template)
    missing_dims = sum(1 for d in template if d not in vector)
    if total_dims > 0:
        non_missing_ratio = (total_dims - missing_dims) / total_dims

    if non_missing_ratio >= 0.8:
        confidence = "high"
    elif non_missing_ratio >= 0.5:
        confidence = "medium"
        warnings.append(f"指纹覆盖率 {non_missing_ratio:.0%}，部分维度缺失")
    else:
        confidence = "low"
        warnings.append(f"指纹覆盖率仅 {non_missing_ratio:.0%}，结论可靠性受限")
        if missing_dims > total_dims / 2:
            return FingerprintResult(
                fund_code=fund_code,
                calc_date=calc_date,
                fund_type=fund_type,
                template_name=template_name,
                vector=vector,
                vector_metadata=metadata,
                missing_dimensions=all_missing,
                contains_estimated=contains_estimated,
                warnings=warnings,
                confidence=confidence,
                conclusion_status="needs_review",
            )

    # Downgrade confidence when estimated dimensions are present
    conclusion_status = "computed"
    if contains_estimated:
        if confidence == "high":
            confidence = "medium"
        conclusion_status = "estimated"
        warnings.append("包含估算维度，结论可信度受限")

    return FingerprintResult(
        fund_code=fund_code,
        calc_date=calc_date,
        fund_type=fund_type,
        template_name=template_name,
        vector=vector,
        vector_metadata=metadata,
        missing_dimensions=all_missing,
        contains_estimated=contains_estimated,
        warnings=warnings,
        confidence=confidence,
        conclusion_status=conclusion_status,
    )


def persist_fingerprint(db: Session, result: FingerprintResult) -> FundFingerprint:
    """Persist a fingerprint result to the database."""
    # Check for existing record
    existing = db.scalars(
        select(FundFingerprint)
        .where(
            FundFingerprint.fund_code == result.fund_code,
            FundFingerprint.calc_date == result.calc_date,
            FundFingerprint.algorithm_version == ALGORITHM_VERSION,
        )
        .limit(1)
    ).first()

    if existing:
        # Update existing
        existing.vector = result.vector
        existing.vector_metadata = result.vector_metadata
        existing.missing_dimensions = result.missing_dimensions
        existing.contains_estimated = result.contains_estimated
        existing.confidence = result.confidence
        existing.conclusion_status = result.conclusion_status
        existing.warnings = result.warnings
        existing.fund_type = result.fund_type
        existing.template_name = result.template_name
        db.flush()
        return existing

    row = FundFingerprint(
        fund_code=result.fund_code,
        calc_date=result.calc_date,
        algorithm_name=ALGORITHM_NAME,
        algorithm_version=ALGORITHM_VERSION,
        fund_type=result.fund_type,
        template_name=result.template_name,
        vector=result.vector,
        vector_metadata=result.vector_metadata,
        missing_dimensions=result.missing_dimensions,
        contains_estimated=result.contains_estimated,
        confidence=result.confidence,
        conclusion_status=result.conclusion_status,
        warnings=result.warnings,
    )
    db.add(row)
    db.flush()
    return row


def get_latest_fingerprint(db: Session, fund_code: str) -> FundFingerprint | None:
    """Get the most recent fingerprint for a fund."""
    return db.scalars(
        select(FundFingerprint)
        .where(FundFingerprint.fund_code == fund_code)
        .order_by(FundFingerprint.calc_date.desc())
        .limit(1)
    ).first()


def fingerprint_to_dict(fp: FundFingerprint) -> dict[str, Any]:
    """Convert a FundFingerprint ORM row to a dict for API responses."""
    return {
        "fund_code": fp.fund_code,
        "calc_date": str(fp.calc_date),
        "algorithm_name": fp.algorithm_name,
        "algorithm_version": fp.algorithm_version,
        "fund_type": fp.fund_type,
        "template_name": fp.template_name,
        "vector": fp.vector,
        "vector_metadata": fp.vector_metadata,
        "missing_dimensions": fp.missing_dimensions or [],
        "contains_estimated": fp.contains_estimated,
        "confidence": fp.confidence,
        "conclusion_status": fp.conclusion_status,
        "warnings": fp.warnings or [],
    }
