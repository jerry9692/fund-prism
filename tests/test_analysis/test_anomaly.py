"""Tests for anomaly detection rule engine."""

from datetime import date

from fund_research.analysis.anomaly import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    ANOMALY_RULES,
    AnomalyItem,
    detect_concentration_anomaly,
    detect_holder_structure_anomaly,
    detect_low_confidence_high_score,
    detect_style_drift,
    persist_anomaly,
    scan_anomalies,
)
from fund_research.db.models import (
    FundDisclosedHoldings,
    FundMain,
    HolderStructure,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import ScoringResult


def test_anomaly_item_to_data():
    item = AnomalyItem(
        fund_code="000001", rule_name="style_drift", severity="warning",
        description="风格漂移", detail={"dimension": "large_cap", "zscore": 2.5},
    )
    data = item.to_data()
    assert data["fund_code"] == "000001"
    assert data["rule_name"] == "style_drift"
    assert data["severity"] == "warning"
    assert data["description"] == "风格漂移"
    assert data["detail"]["dimension"] == "large_cap"
    assert data["algorithm_name"] == ALGORITHM_NAME
    assert data["algorithm_version"] == ALGORITHM_VERSION


def test_anomaly_rules_complete():
    expected_rules = {
        "style_drift", "classification_deviation",
        "low_confidence_high_score", "concentration_anomaly",
        "holder_structure_anomaly",
    }
    assert set(ANOMALY_RULES.keys()) == expected_rules


def test_anomaly_rules_have_severity():
    for rule_name, rule_def in ANOMALY_RULES.items():
        assert "severity" in rule_def, f"{rule_name} missing severity"
        assert "default_params" in rule_def, f"{rule_name} missing default_params"


def test_style_drift_insufficient_data(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    for i, dt in enumerate([date(2024, 3, 31), date(2024, 6, 30)]):
        db.add(StyleExposureResult(
            fund_code="000001", calc_date=dt,
            algorithm_name="style_exposure", algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={"large_cap": 0.5 + i * 0.1, "mid_cap": 0.3, "small_cap": 0.2},
            r_squared=0.8, conclusion_status="computed",
        ))
    db.commit()
    result = detect_style_drift(db, "000001", {"std_threshold": 2.0, "lookback_quarters": 4})
    assert result is None


def test_style_drift_detected(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    # 6 stable historical points + 1 extreme drift
    exposures = [
        {"large_cap": 0.5, "mid_cap": 0.3, "small_cap": 0.2},
        {"large_cap": 0.52, "mid_cap": 0.28, "small_cap": 0.2},
        {"large_cap": 0.48, "mid_cap": 0.32, "small_cap": 0.2},
        {"large_cap": 0.51, "mid_cap": 0.29, "small_cap": 0.2},
        {"large_cap": 0.49, "mid_cap": 0.31, "small_cap": 0.2},
        {"large_cap": 0.50, "mid_cap": 0.30, "small_cap": 0.2},
        {"large_cap": 0.95, "mid_cap": 0.03, "small_cap": 0.02},  # Drift!
    ]
    calc_dates = [
        date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31),
        date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30),
        date(2024, 12, 31),
    ]
    for i, exp in enumerate(exposures):
        db.add(StyleExposureResult(
            fund_code="000001", calc_date=calc_dates[i],
            algorithm_name="style_exposure", algorithm_version="0.1.0",
            exposure_type="style", exposure_values=exp,
            r_squared=0.8, conclusion_status="computed",
        ))
    db.commit()
    result = detect_style_drift(db, "000001", {"std_threshold": 2.0, "lookback_quarters": 4})
    assert result is not None
    assert result.rule_name == "style_drift"
    assert result.severity == "warning"


def test_style_drift_no_drift(test_session):
    db = test_session
    db.add(FundMain(fund_code="000002", short_name="t", full_name="t", category="混合型"))
    calc_dates = [date(2024, 1, 31), date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31)]
    for i in range(5):
        db.add(StyleExposureResult(
            fund_code="000002", calc_date=calc_dates[i],
            algorithm_name="style_exposure", algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={"large_cap": 0.5, "mid_cap": 0.3, "small_cap": 0.2},
            r_squared=0.8, conclusion_status="computed",
        ))
    db.commit()
    result = detect_style_drift(db, "000002", {"std_threshold": 2.0, "lookback_quarters": 4})
    assert result is None


def test_low_confidence_high_score_detected(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    db.add(ScoringResult(
        fund_code="000001", calc_date=date(2024, 12, 31),
        score_version="v0.1", algorithm_version="0.1.0",
        weight_config={"return": 0.2, "risk": 0.2},
        total_score=85.0, sub_scores={"return": 90, "risk": 80},
        contains_estimated=True, confidence="low",
        conclusion_status="needs_review",
    ))
    db.commit()
    result = detect_low_confidence_high_score(db, "000001", {"score_threshold": 70.0, "confidence_threshold": 0.6})
    assert result is not None
    assert result.rule_name == "low_confidence_high_score"
    assert result.conclusion_status == "needs_review"


def test_low_confidence_high_score_not_triggered(test_session):
    db = test_session
    db.add(FundMain(fund_code="000002", short_name="t", full_name="t", category="混合型"))
    db.add(ScoringResult(
        fund_code="000002", calc_date=date(2024, 12, 31),
        score_version="v0.1", algorithm_version="0.1.0",
        weight_config={"return": 0.2, "risk": 0.2},
        total_score=85.0, sub_scores={"return": 90, "risk": 80},
        contains_estimated=False, confidence="high",
        conclusion_status="computed",
    ))
    db.commit()
    result = detect_low_confidence_high_score(db, "000002", {"score_threshold": 70.0, "confidence_threshold": 0.6})
    assert result is None


def test_low_confidence_low_score_not_triggered(test_session):
    db = test_session
    db.add(FundMain(fund_code="000003", short_name="t", full_name="t", category="混合型"))
    db.add(ScoringResult(
        fund_code="000003", calc_date=date(2024, 12, 31),
        score_version="v0.1", algorithm_version="0.1.0",
        weight_config={"return": 0.2, "risk": 0.2},
        total_score=50.0, sub_scores={"return": 55, "risk": 45},
        contains_estimated=False, confidence="low",
        conclusion_status="needs_review",
    ))
    db.commit()
    result = detect_low_confidence_high_score(db, "000003", {"score_threshold": 70.0, "confidence_threshold": 0.6})
    assert result is None


def test_holder_structure_anomaly_detected(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    db.add(HolderStructure(
        fund_code="000001", report_date=date(2024, 6, 30), institutional_pct=60.0,
    ))
    db.add(HolderStructure(
        fund_code="000001", report_date=date(2024, 12, 31), institutional_pct=30.0,
    ))
    db.commit()
    result = detect_holder_structure_anomaly(db, "000001", {"change_threshold": 0.20})
    assert result is not None
    assert result.rule_name == "holder_structure_anomaly"


def test_holder_structure_no_anomaly(test_session):
    db = test_session
    db.add(FundMain(fund_code="000002", short_name="t", full_name="t", category="混合型"))
    db.add(HolderStructure(
        fund_code="000002", report_date=date(2024, 6, 30), institutional_pct=50.0,
    ))
    db.add(HolderStructure(
        fund_code="000002", report_date=date(2024, 12, 31), institutional_pct=52.0,
    ))
    db.commit()
    result = detect_holder_structure_anomaly(db, "000002", {"change_threshold": 0.20})
    assert result is None


def test_holder_structure_insufficient_data(test_session):
    db = test_session
    db.add(FundMain(fund_code="000003", short_name="t", full_name="t", category="混合型"))
    db.add(HolderStructure(
        fund_code="000003", report_date=date(2024, 12, 31), institutional_pct=50.0,
    ))
    db.commit()
    result = detect_holder_structure_anomaly(db, "000003", {"change_threshold": 0.20})
    assert result is None


def test_concentration_anomaly_no_peer_data(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    db.add(FundDisclosedHoldings(
        fund_code="000001", report_date=date(2024, 12, 31),
        asset_type="股票", security_code="600519", security_name="test", weight_pct=10.0,
    ))
    db.commit()
    result = detect_concentration_anomaly(db, "000001", {"iqr_multiplier": 1.5})
    if result is not None:
        assert result.rule_name == "concentration_anomaly"


def test_scan_anomalies_empty_funds(test_session):
    results = scan_anomalies(test_session, [])
    assert results == []


def test_scan_anomalies_with_rule_filter(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    db.add(ScoringResult(
        fund_code="000001", calc_date=date(2024, 12, 31),
        score_version="v0.1", algorithm_version="0.1.0",
        weight_config={"return": 0.2},
        total_score=85.0, sub_scores={"return": 90},
        contains_estimated=True, confidence="low",
        conclusion_status="needs_review",
    ))
    db.commit()
    results = scan_anomalies(db, ["000001"], rules=["low_confidence_high_score"])
    assert len(results) >= 1
    assert all(r.rule_name == "low_confidence_high_score" for r in results)


def test_scan_anomalies_all_rules(test_session):
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型"))
    db.commit()
    results = scan_anomalies(db, ["000001"])
    assert isinstance(results, list)


def test_persist_anomaly_creates_record(test_session):
    db = test_session
    item = AnomalyItem(
        fund_code="000001", rule_name="style_drift", severity="warning",
        description="Test anomaly", detail={"key": "value"},
    )
    record = persist_anomaly(db, item, scope="all")
    db.commit()
    assert record.id is not None
    assert record.fund_code == "000001"
    assert record.rule_name == "style_drift"
    assert record.scope == "all"
