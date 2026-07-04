"""Tests for fund fingerprint generation and persistence."""

from datetime import date

import pytest

from fund_research.analysis.fingerprint import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    FINGERPRINT_TEMPLATES,
    _select_template,
    fingerprint_to_dict,
    generate_fingerprint,
    get_latest_fingerprint,
    persist_fingerprint,
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
from fund_research.utils import safe_float


def _create_fund(db, fund_code="000001", sub_category="偏股混合"):
    """Create a test fund in the database."""
    fund = FundMain(
        fund_code=fund_code,
        short_name="测试基金",
        full_name="测试基金全称",
        category="混合型",
        sub_category=sub_category,
    )
    db.add(fund)
    db.flush()
    return fund


def _create_style_exposure(db, fund_code="000001"):
    """Create style exposure data."""
    db.add(
        StyleExposureResult(
            fund_code=fund_code,
            calc_date=date(2024, 12, 31),
            algorithm_name="style_exposure",
            algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={"large_cap": 0.6, "mid_cap": 0.3, "small_cap": 0.1, "growth": 0.5, "value": 0.5},
            r_squared=0.85,
            conclusion_status="computed",
        )
    )
    db.add(
        StyleExposureResult(
            fund_code=fund_code,
            calc_date=date(2024, 12, 31),
            algorithm_name="industry_exposure",
            algorithm_version="0.1.0",
            exposure_type="industry",
            exposure_values={"医药生物": 0.30, "电子": 0.20, "计算机": 0.15, "食品饮料": 0.10, "银行": 0.05},
            conclusion_status="fact",
        )
    )
    db.flush()


def _create_holdings(db, fund_code="000001"):
    """Create disclosed holdings data."""
    report_date = date(2024, 12, 31)
    stocks = [
        ("600519", 8.5),
        ("000858", 6.2),
        ("002714", 5.1),
        ("600036", 4.8),
        ("000333", 4.2),
        ("601318", 3.5),
        ("002475", 3.0),
        ("600276", 2.8),
        ("000725", 2.5),
        ("601166", 2.0),
    ]
    for security_code, weight in stocks:
        db.add(
            FundDisclosedHoldings(
                fund_code=fund_code,
                report_date=report_date,
                asset_type="股票",
                security_code=security_code,
                security_name=f"股票{security_code}",
                weight_pct=weight,
            )
        )
    db.flush()


def _create_scoring(db, fund_code="000001"):
    """Create scoring result data."""
    db.add(
        ScoringResult(
            fund_code=fund_code,
            calc_date=date(2024, 12, 31),
            score_version="v0.1",
            algorithm_version="0.1.0",
            weight_config={"return": 0.2, "risk": 0.2, "alpha": 0.15},
            total_score=75.5,
            sub_scores={"return": 80, "risk": 70, "alpha": 65},
            contains_estimated=False,
            confidence="high",
            conclusion_status="computed",
        )
    )
    db.flush()


def _create_attribution(db, fund_code="000001"):
    """Create static attribution data."""
    db.add(
        StaticAttributionResult(
            fund_code=fund_code,
            report_date=date(2024, 12, 31),
            algorithm_name="static_attribution",
            algorithm_version="0.1.0",
            selection_effect=2.5,
            allocation_effect=1.8,
            interaction_effect=0.3,
            residual_pct=0.15,
            conclusion_status="observation",
        )
    )
    db.flush()


def _create_trading(db, fund_code="000001"):
    """Create trading ability data."""
    db.add(
        TradingAbilityResult(
            fund_code=fund_code,
            calc_date=date(2024, 12, 31),
            algorithm_name="trading_ability",
            algorithm_version="0.1.0",
            estimated_turnover_rate=1.2,
            conclusion_status="estimated",
        )
    )
    db.flush()


def _create_scale(db, fund_code="000001"):
    """Create fund scale data."""
    db.add(
        FundScale(
            fund_code=fund_code,
            report_date=date(2024, 9, 30),
            total_nav=50.0,
        )
    )
    db.add(
        FundScale(
            fund_code=fund_code,
            report_date=date(2024, 12, 31),
            total_nav=55.0,
        )
    )
    db.flush()


def _create_manager_tenure(db, fund_code="000001"):
    """Create manager tenure data."""
    db.add(
        FundManagerTenure(
            fund_code=fund_code,
            manager_id="M001",
            start_date=date(2020, 1, 1),
            end_date=None,
            is_current=True,
        )
    )
    db.flush()


def _setup_full_fund(db, fund_code="000001"):
    """Set up a fund with all data sources."""
    _create_fund(db, fund_code)
    _create_style_exposure(db, fund_code)
    _create_holdings(db, fund_code)
    _create_scoring(db, fund_code)
    _create_attribution(db, fund_code)
    _create_trading(db, fund_code)
    _create_scale(db, fund_code)
    _create_manager_tenure(db, fund_code)
    db.commit()


# ============================================================
# Template selection tests
# ============================================================


def test_select_template_active_equity():
    """Active equity funds should use the active_equity template."""
    fund = FundMain(fund_code="000001", short_name="t", full_name="t", category="混合型", sub_category="偏股混合")
    assert _select_template(fund) == "active_equity"


def test_select_template_index_fund():
    """Index funds should use the index_fund template."""
    fund = FundMain(fund_code="000002", short_name="t", full_name="t", category="指数型", sub_category="被动指数")
    assert _select_template(fund) == "index_fund"


def test_select_template_none():
    """No fund should use the default template."""
    assert _select_template(None) == "default"


def test_template_definitions_complete():
    """All templates should have the expected dimension groups."""
    for _template_name, template in FINGERPRINT_TEMPLATES.items():
        assert "return_risk" in template
        assert "style_exposure" in template
        assert "alpha" in template


# ============================================================
# Safe float tests
# ============================================================


def test_safe_float_normal():
    assert safe_float(3.14) == 3.14


def test_safe_float_none():
    assert safe_float(None) is None


def test_safe_float_string():
    assert safe_float("2.5") == 2.5


def test_safe_float_nan():
    assert safe_float(float("nan")) is None


def test_safe_float_invalid():
    assert safe_float("abc") is None


# ============================================================
# Fingerprint generation tests
# ============================================================


def test_generate_fingerprint_full_data(test_session):
    """Fingerprint with full data should have all dimension groups."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")

    assert result.fund_code == "000001"
    assert result.template_name == "active_equity"
    assert "return_risk" in result.vector
    assert "style_exposure" in result.vector
    assert "industry_exposure" in result.vector
    assert "holding_features" in result.vector
    assert "alpha" in result.vector
    assert "scale" in result.vector
    assert "team" in result.vector
    # Full data includes estimated dimensions (turnover, residual), so status is estimated
    assert result.contains_estimated is True
    assert result.conclusion_status == "estimated"
    assert result.confidence == "medium"  # downgraded from high due to estimated


def test_generate_fingerprint_contains_estimated(test_session):
    """Fingerprint should flag estimated dimensions."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")

    assert result.contains_estimated is True
    assert "estimated_turnover" in result.vector.get("holding_features", {})
    assert result.vector_metadata["holding_features"]["estimated_turnover"] == "estimated"


def test_generate_fingerprint_missing_data(test_session):
    """Fingerprint with no data should have missing dimensions and low confidence."""
    _create_fund(test_session, "000099")
    test_session.commit()

    result = generate_fingerprint(test_session, "000099")

    assert len(result.missing_dimensions) > 0
    assert result.confidence == "low"
    assert result.conclusion_status == "needs_review"


def test_generate_fingerprint_industry_hhi(test_session):
    """Industry HHI should be calculated from top industries."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")

    industry = result.vector.get("industry_exposure", {})
    assert "industry_hhi" in industry
    assert industry["industry_hhi"] > 0


def test_generate_fingerprint_top10_concentration(test_session):
    """Top-10 concentration should be calculated from holdings."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")

    holding = result.vector.get("holding_features", {})
    assert "top10_concentration" in holding
    assert holding["top10_concentration"] > 0


def test_generate_fingerprint_scale_change(test_session):
    """Scale change rate should be calculated from two periods."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")

    scale = result.vector.get("scale", {})
    assert "scale" in scale
    assert "scale_change_rate" in scale
    assert scale["scale_change_rate"] == pytest.approx(0.1, abs=0.01)


def test_generate_fingerprint_manager_tenure(test_session):
    """Manager tenure days should be calculated."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")

    team = result.vector.get("team", {})
    assert "manager_tenure_days" in team
    assert team["manager_tenure_days"] > 0


# ============================================================
# Persistence tests
# ============================================================


def test_persist_fingerprint_creates_record(test_session):
    """Persisting a fingerprint should create a database record."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")
    record = persist_fingerprint(test_session, result)
    test_session.commit()

    assert record.id is not None
    assert record.fund_code == "000001"
    assert record.algorithm_name == ALGORITHM_NAME
    assert record.algorithm_version == ALGORITHM_VERSION


def test_persist_fingerprint_updates_existing(test_session):
    """Persisting a fingerprint twice should update, not duplicate."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")
    persist_fingerprint(test_session, result)
    test_session.commit()

    # Generate again and persist
    result2 = generate_fingerprint(test_session, "000001")
    record2 = persist_fingerprint(test_session, result2)
    test_session.commit()

    assert record2.id is not None


def test_get_latest_fingerprint(test_session):
    """get_latest_fingerprint should return the most recent record."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001", calc_date=date(2024, 6, 30))
    persist_fingerprint(test_session, result)
    test_session.commit()

    result2 = generate_fingerprint(test_session, "000001", calc_date=date(2024, 12, 31))
    persist_fingerprint(test_session, result2)
    test_session.commit()

    latest = get_latest_fingerprint(test_session, "000001")
    assert latest is not None
    assert str(latest.calc_date) == "2024-12-31"


def test_get_latest_fingerprint_not_found(test_session):
    """get_latest_fingerprint should return None for non-existent fund."""
    assert get_latest_fingerprint(test_session, "999999") is None


# ============================================================
# Fingerprint to dict tests
# ============================================================


def test_fingerprint_to_dict(test_session):
    """fingerprint_to_dict should return all expected fields."""
    _setup_full_fund(test_session, "000001")
    result = generate_fingerprint(test_session, "000001")
    record = persist_fingerprint(test_session, result)
    test_session.commit()

    d = fingerprint_to_dict(record)
    assert d["fund_code"] == "000001"
    assert "vector" in d
    assert "vector_metadata" in d
    assert "missing_dimensions" in d
    assert "warnings" in d
    assert "conclusion_status" in d
