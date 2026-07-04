"""Tests for fund similarity calculation."""

from datetime import date

import pytest

from fund_research.analysis.fingerprint import generate_fingerprint, persist_fingerprint
from fund_research.analysis.similarity import (
    _cosine_similarity,
    _euclidean_distance,
    _weighted_euclidean_similarity,
    compare_fund_fingerprints,
    find_similar_funds,
)
from fund_research.db.models import (
    FundDisclosedHoldings,
    FundMain,
    FundManagerTenure,
    FundScale,
    StaticAttributionResult,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import ScoringResult, TradingAbilityResult


def _create_fund(db, fund_code, style_exposure, industry_weights=None, score=75.0):
    """Create a fund with fingerprint-relevant data."""
    db.add(FundMain(
        fund_code=fund_code, short_name=f"基金{fund_code}",
        full_name=f"基金{fund_code}", category="混合型", sub_category="偏股混合",
    ))
    db.add(StyleExposureResult(
        fund_code=fund_code, calc_date=date(2024, 12, 31),
        algorithm_name="style_exposure", algorithm_version="0.1.0",
        exposure_type="style", exposure_values=style_exposure, r_squared=0.85,
        conclusion_status="computed",
    ))
    if industry_weights:
        db.add(StyleExposureResult(
            fund_code=fund_code, calc_date=date(2024, 12, 31),
            algorithm_name="industry_exposure", algorithm_version="0.1.0",
            exposure_type="industry", exposure_values=industry_weights,
            conclusion_status="fact",
        ))
    db.add(ScoringResult(
        fund_code=fund_code, calc_date=date(2024, 12, 31),
        score_version="v0.1", algorithm_version="0.1.0",
        weight_config={"return": 0.2, "risk": 0.2},
        total_score=score, sub_scores={"return": score, "risk": score - 10},
        contains_estimated=False, confidence="high", conclusion_status="computed",
    ))
    db.add(FundDisclosedHoldings(
        fund_code=fund_code, report_date=date(2024, 12, 31),
        asset_type="股票", security_code="600519", security_name="贵州茅台", weight_pct=8.0,
    ))
    db.add(StaticAttributionResult(
        fund_code=fund_code, report_date=date(2024, 12, 31),
        algorithm_name="static_attribution", algorithm_version="0.1.0",
        selection_effect=2.0, allocation_effect=1.0, residual_pct=0.1,
        conclusion_status="observation",
    ))
    db.add(TradingAbilityResult(
        fund_code=fund_code, calc_date=date(2024, 12, 31),
        algorithm_name="trading_ability", algorithm_version="0.1.0",
        estimated_turnover_rate=1.0, conclusion_status="estimated",
    ))
    db.add(FundScale(fund_code=fund_code, report_date=date(2024, 12, 31), total_nav=10.0))
    db.add(FundManagerTenure(
        fund_code=fund_code, manager_id="M001", start_date=date(2020, 1, 1), is_current=True,
    ))
    db.flush()


def _setup_three_funds(db):
    """Create three funds with different style exposures."""
    _create_fund(db, "000001",
        style_exposure={"large_cap": 0.7, "mid_cap": 0.2, "small_cap": 0.1, "growth": 0.6, "value": 0.4},
        industry_weights={"医药": 0.3, "电子": 0.2, "计算机": 0.15}, score=80)
    _create_fund(db, "000002",
        style_exposure={"large_cap": 0.65, "mid_cap": 0.25, "small_cap": 0.1, "growth": 0.55, "value": 0.45},
        industry_weights={"医药": 0.28, "电子": 0.22, "计算机": 0.14}, score=75)
    _create_fund(db, "000003",
        style_exposure={"large_cap": 0.2, "mid_cap": 0.3, "small_cap": 0.5, "growth": 0.2, "value": 0.8},
        industry_weights={"银行": 0.4, "地产": 0.3, "非银": 0.1}, score=60)
    db.commit()
    for code in ["000001", "000002", "000003"]:
        result = generate_fingerprint(db, code)
        persist_fingerprint(db, result)
    db.commit()


def test_cosine_similarity_identical():
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

def test_cosine_similarity_orthogonal():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

def test_cosine_similarity_empty():
    assert _cosine_similarity([], []) == 0.0

def test_euclidean_distance_identical():
    assert _euclidean_distance([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)

def test_euclidean_distance_different():
    score = _euclidean_distance([0.0, 0.0], [3.0, 4.0])
    assert 0 < score < 1.0

def test_weighted_euclidean_with_weights():
    score = _weighted_euclidean_similarity([1.0, 1.0], [2.0, 2.0], weights=[1.0, 2.0])
    assert 0 < score < 1.0

def test_weighted_euclidean_no_weights():
    score = _weighted_euclidean_similarity([1.0, 1.0], [2.0, 2.0])
    assert 0 < score < 1.0


def test_find_similar_funds_returns_results(test_session):
    _setup_three_funds(test_session)
    results = find_similar_funds(test_session, "000001", metric_space="composite", top_n=5)
    assert len(results) > 0
    for i in range(len(results) - 1):
        assert results[i].similarity_score >= results[i + 1].similarity_score

def test_find_similar_funds_excludes_self(test_session):
    _setup_three_funds(test_session)
    results = find_similar_funds(test_session, "000001")
    fund_codes = [r.similar_fund_code for r in results]
    assert "000001" not in fund_codes

def test_find_similar_funds_top_n(test_session):
    _setup_three_funds(test_session)
    results = find_similar_funds(test_session, "000001", top_n=1)
    assert len(results) <= 1

def test_find_similar_funds_no_fingerprint(test_session):
    results = find_similar_funds(test_session, "999999")
    assert results == []

def test_find_similar_funds_has_contributions(test_session):
    _setup_three_funds(test_session)
    results = find_similar_funds(test_session, "000001", top_n=3)
    for r in results:
        assert len(r.contributing_dimensions) > 0
        assert len(r.contributing_dimensions) <= 3

def test_find_similar_funds_metric_space_style(test_session):
    _setup_three_funds(test_session)
    results = find_similar_funds(test_session, "000001", metric_space="style", top_n=5)
    assert len(results) > 0


def test_compare_fund_fingerprints(test_session):
    _setup_three_funds(test_session)
    result = compare_fund_fingerprints(test_session, ["000001", "000002", "000003"])
    assert "fund_codes" in result
    assert "comparison_data" in result
    assert "similarity_matrix" in result
    assert len(result["fund_codes"]) == 3

def test_compare_fund_fingerprints_similarity_matrix(test_session):
    _setup_three_funds(test_session)
    result = compare_fund_fingerprints(test_session, ["000001", "000002", "000003"])
    matrix = result["similarity_matrix"]
    for code in ["000001", "000002", "000003"]:
        assert matrix[code][code] == 1.0
    assert matrix["000001"]["000002"] == matrix["000002"]["000001"]

def test_compare_fund_fingerprints_insufficient(test_session):
    _create_fund(test_session, "000001",
        style_exposure={"large_cap": 0.7, "mid_cap": 0.2, "small_cap": 0.1, "growth": 0.5, "value": 0.5})
    test_session.commit()
    result = generate_fingerprint(test_session, "000001")
    persist_fingerprint(test_session, result)
    test_session.commit()
    result = compare_fund_fingerprints(test_session, ["000001", "999999"])
    assert len(result["fund_codes"]) < 2
    assert "warnings" in result


def test_similarity_result_to_data():
    from fund_research.analysis.similarity import SimilarityResult
    result = SimilarityResult(
        fund_code="000001", similar_fund_code="000002", similarity_score=0.85,
        metric_space="composite",
        contributing_dimensions=[{"dimension": "style.large_cap", "contribution": 0.9}],
    )
    data = result.to_data()
    assert data["fund_code"] == "000001"
    assert data["similar_fund_code"] == "000002"
    assert data["similarity_score"] == 0.85
    assert data["metric_space"] == "composite"
    assert len(data["contributing_dimensions"]) == 1
