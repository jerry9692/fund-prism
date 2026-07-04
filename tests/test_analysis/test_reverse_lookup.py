"""Tests for stock-to-fund reverse lookup (P3.5)."""

from datetime import date

import pytest

from fund_research.analysis.reverse_lookup import (
    TRACKING_ERROR_THRESHOLD,
    _hash_stock_codes,
    _resolve_fund_scope,
    persist_result,
    reverse_lookup,
    reverse_lookup_disclosed,
    reverse_lookup_simulated,
    reverse_lookup_weighted,
)
from fund_research.db.models import FundDisclosedHoldings, FundMain
from fund_research.db.models_phase2 import (
    FundPool as DbFundPool,
)
from fund_research.db.models_phase2 import (
    FundPoolMember as DbFundPoolMember,
)
from fund_research.db.models_phase2 import SimulatedHoldingResult

# ============================================================
# _hash_stock_codes tests
# ============================================================


def test_hash_stock_codes_order_independent():
    """Hash should be the same regardless of input order."""
    hash1 = _hash_stock_codes(["000001", "000002", "600000"])
    hash2 = _hash_stock_codes(["600000", "000001", "000002"])
    assert hash1 == hash2


def test_hash_stock_codes_stable():
    """Same input should produce same hash."""
    h = _hash_stock_codes(["000001", "000002"])
    assert h == _hash_stock_codes(["000001", "000002"])


def test_hash_stock_codes_ignores_empty_and_whitespace():
    """Empty/whitespace codes should be ignored."""
    h1 = _hash_stock_codes(["000001", ""])
    h2 = _hash_stock_codes(["000001", "  "])
    h3 = _hash_stock_codes(["000001"])
    assert h1 == h2 == h3


def test_hash_stock_codes_strips_whitespace():
    """Codes should be stripped before hashing."""
    h1 = _hash_stock_codes(["  000001  "])
    h2 = _hash_stock_codes(["000001"])
    assert h1 == h2


# ============================================================
# _resolve_fund_scope tests
# ============================================================


def test_resolve_fund_scope_all(test_session):
    """fund_scope='all' should return None (no filter)."""
    result = _resolve_fund_scope(test_session, "all", None)
    assert result is None


def test_resolve_fund_scope_pool(test_session):
    """fund_scope='pool' should return fund codes in that pool."""
    db = test_session
    pool = DbFundPool(name="test")
    db.add(pool)
    db.flush()
    db.add(DbFundPoolMember(pool_id=pool.id, fund_code="000001"))
    db.add(DbFundPoolMember(pool_id=pool.id, fund_code="000002"))
    db.flush()

    result = _resolve_fund_scope(db, "pool", str(pool.id))
    assert result == {"000001", "000002"}


def test_resolve_fund_scope_pool_no_scope_id(test_session):
    """fund_scope='pool' without scope_id should return empty set."""
    result = _resolve_fund_scope(test_session, "pool", None)
    assert result == set()


def test_resolve_fund_scope_pool_invalid_scope_id(test_session):
    """fund_scope='pool' with non-numeric scope_id should return empty set."""
    result = _resolve_fund_scope(test_session, "pool", "not-a-number")
    assert result == set()


def test_resolve_fund_scope_fund_type(test_session):
    """fund_scope='fund_type' should return funds matching the category."""
    db = test_session
    db.add(FundMain(fund_code="000001", short_name="A", full_name="A", category="混合型"))
    db.add(FundMain(fund_code="000002", short_name="B", full_name="B", category="股票型"))
    db.add(FundMain(fund_code="000003", short_name="C", full_name="C", category="混合型"))
    db.flush()

    result = _resolve_fund_scope(db, "fund_type", "混合型")
    assert result == {"000001", "000003"}


# ============================================================
# reverse_lookup_disclosed tests
# ============================================================


def _add_disclosed_holding(db, fund_code, report_date, security_code, weight_pct, industry="银行"):
    db.add(FundDisclosedHoldings(
        fund_code=fund_code,
        report_date=report_date,
        asset_type="股票",
        security_code=security_code,
        security_name=f"Stock_{security_code}",
        weight_pct=weight_pct,
        industry=industry,
    ))


def test_reverse_lookup_disclosed_basic(test_session):
    """Should find funds holding the target stock and rank by exposure."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    _add_disclosed_holding(db, "000002", date(2024, 6, 30), "600000", 8.0)
    _add_disclosed_holding(db, "000003", date(2024, 6, 30), "000001", 3.0)
    db.flush()

    results = reverse_lookup_disclosed(db, ["600000"])
    assert len(results) == 2
    # Higher exposure fund should be first
    assert results[0]["fund_code"] == "000002"
    assert results[0]["total_exposure"] == 8.0
    assert results[1]["fund_code"] == "000001"
    assert results[1]["total_exposure"] == 5.0
    # All disclosed results should be source=fact
    for r in results:
        assert r["source"] == "fact"
        assert r["conclusion_status"] == "fact"
        assert r["confidence"] == "high"


def test_reverse_lookup_disclosed_latest_date_only(test_session):
    """Should only use the latest report_date per fund."""
    db = test_session
    # Fund 000001 has two report dates; only the latest should count
    _add_disclosed_holding(db, "000001", date(2024, 3, 31), "600000", 3.0)
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 6.0)
    db.flush()

    results = reverse_lookup_disclosed(db, ["600000"])
    assert len(results) == 1
    assert results[0]["total_exposure"] == 6.0


def test_reverse_lookup_disclosed_empty_stock_codes(test_session):
    """Empty stock_codes should return empty list."""
    results = reverse_lookup_disclosed(test_session, [])
    assert results == []


def test_reverse_lookup_disclosed_no_matches(test_session):
    """No matching holdings should return empty list."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    db.flush()

    results = reverse_lookup_disclosed(db, ["999999"])
    assert results == []


def test_reverse_lookup_disclosed_multiple_stocks(test_session):
    """Should sum weights across multiple matching stocks per fund."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "000001", 3.0)
    db.flush()

    results = reverse_lookup_disclosed(db, ["600000", "000001"])
    assert len(results) == 1
    assert results[0]["total_exposure"] == 8.0
    assert len(results[0]["stock_contributions"]) == 2


def test_reverse_lookup_disclosed_pool_scope(test_session):
    """Should filter by pool membership when fund_scope='pool'."""
    db = test_session
    pool = DbFundPool(name="test")
    db.add(pool)
    db.flush()
    db.add(DbFundPoolMember(pool_id=pool.id, fund_code="000001"))
    db.flush()

    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    _add_disclosed_holding(db, "000002", date(2024, 6, 30), "600000", 10.0)
    db.flush()

    results = reverse_lookup_disclosed(db, ["600000"], fund_scope="pool", scope_id=str(pool.id))
    assert len(results) == 1
    assert results[0]["fund_code"] == "000001"


# ============================================================
# reverse_lookup_simulated tests
# ============================================================


def _make_simulated(fund_code, calc_date, holdings, tracking_error=None, top10_recall=None):
    return SimulatedHoldingResult(
        fund_code=fund_code,
        calc_date=calc_date,
        algorithm_name="simulated_holding",
        algorithm_version="0.1",
        holdings_detail=holdings,
        tracking_error=tracking_error,
        top10_recall=top10_recall,
        conclusion_status="estimated",
    )


def test_reverse_lookup_simulated_basic(test_session):
    """Should find funds with simulated holdings matching target stocks."""
    db = test_session
    db.add(_make_simulated("000001", date(2024, 6, 30), [
        {"stock_code": "600000", "estimated_weight": 0.05},
        {"stock_code": "000001", "estimated_weight": 0.03},
    ], tracking_error=0.02))
    db.flush()

    results = reverse_lookup_simulated(db, ["600000"])
    assert len(results) == 1
    assert results[0]["fund_code"] == "000001"
    # estimated_weight 0.05 should be converted to 5.0 (percentage)
    assert results[0]["total_exposure"] == 5.0
    assert results[0]["source"] == "estimated"
    assert results[0]["conclusion_status"] == "estimated"
    # tracking_error below threshold → medium confidence
    assert results[0]["confidence"] == "medium"


def test_reverse_lookup_simulated_tracking_error_downgrade(test_session):
    """High tracking_error should downgrade confidence to low."""
    db = test_session
    db.add(_make_simulated("000001", date(2024, 6, 30), [
        {"stock_code": "600000", "estimated_weight": 0.05},
    ], tracking_error=TRACKING_ERROR_THRESHOLD + 0.01))
    db.flush()

    results = reverse_lookup_simulated(db, ["600000"])
    assert len(results) == 1
    assert results[0]["confidence"] == "low"
    assert len(results[0]["warnings"]) > 0


def test_reverse_lookup_simulated_empty_stock_codes(test_session):
    """Empty stock_codes should return empty list."""
    results = reverse_lookup_simulated(test_session, [])
    assert results == []


def test_reverse_lookup_simulated_no_matches(test_session):
    """No matching simulated holdings should return empty list."""
    db = test_session
    db.add(_make_simulated("000001", date(2024, 6, 30), [
        {"stock_code": "600000", "estimated_weight": 0.05},
    ]))
    db.flush()

    results = reverse_lookup_simulated(db, ["999999"])
    assert results == []


def test_reverse_lookup_simulated_weight_fallback(test_session):
    """Should fall back to 'weight' key if 'estimated_weight' is missing."""
    db = test_session
    db.add(_make_simulated("000001", date(2024, 6, 30), [
        {"stock_code": "600000", "weight": 0.07},
    ]))
    db.flush()

    results = reverse_lookup_simulated(db, ["600000"])
    assert len(results) == 1
    assert results[0]["total_exposure"] == 7.0


def test_reverse_lookup_simulated_code_fallback(test_session):
    """Should use 'code' key if 'stock_code' is missing."""
    db = test_session
    db.add(_make_simulated("000001", date(2024, 6, 30), [
        {"code": "600000", "estimated_weight": 0.05},
    ]))
    db.flush()

    results = reverse_lookup_simulated(db, ["600000"])
    assert len(results) == 1
    assert results[0]["stock_contributions"][0]["security_code"] == "600000"


# ============================================================
# reverse_lookup_weighted tests
# ============================================================


def test_reverse_lookup_weighted_disclosed_priority(test_session):
    """Disclosed should take priority; simulated only for funds without disclosed data."""
    db = test_session
    # Fund 000001 has disclosed data
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    # Fund 000002 only has simulated data
    db.add(_make_simulated("000002", date(2024, 6, 30), [
        {"stock_code": "600000", "estimated_weight": 0.08},
    ], tracking_error=0.02))
    db.flush()

    results = reverse_lookup_weighted(db, ["600000"])
    assert len(results) == 2
    # Fund 000001 should have source=fact
    fund_001 = next(r for r in results if r["fund_code"] == "000001")
    assert fund_001["source"] == "fact"
    # Fund 000002 should have source=estimated
    fund_002 = next(r for r in results if r["fund_code"] == "000002")
    assert fund_002["source"] == "estimated"


def test_reverse_lookup_weighted_no_duplicate(test_session):
    """A fund with both disclosed and simulated should only appear once (disclosed)."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    db.add(_make_simulated("000001", date(2024, 6, 30), [
        {"stock_code": "600000", "estimated_weight": 0.08},
    ], tracking_error=0.02))
    db.flush()

    results = reverse_lookup_weighted(db, ["600000"])
    assert len(results) == 1
    assert results[0]["source"] == "fact"


# ============================================================
# reverse_lookup (main entry) tests
# ============================================================


def test_reverse_lookup_top_n_truncation(test_session):
    """Should truncate results to top_n funds."""
    db = test_session
    for i in range(5):
        code = f"00000{i+1}"
        _add_disclosed_holding(db, code, date(2024, 6, 30), "600000", float(i + 1))
    db.flush()

    result = reverse_lookup(db, ["600000"], method="disclosed", top_n=3)
    assert result["fund_count"] == 3
    assert len(result["results"]) == 3


def test_reverse_lookup_top_n_zero_no_limit(test_session):
    """top_n=0 should return all results without truncation."""
    db = test_session
    for i in range(5):
        code = f"00000{i+1}"
        _add_disclosed_holding(db, code, date(2024, 6, 30), "600000", float(i + 1))
    db.flush()

    result = reverse_lookup(db, ["600000"], method="disclosed", top_n=0)
    assert result["fund_count"] == 5


def test_reverse_lookup_stock_coverage(test_session):
    """stock_coverage should count how many funds hold each stock."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "000001", 3.0)
    _add_disclosed_holding(db, "000002", date(2024, 6, 30), "600000", 8.0)
    db.flush()

    result = reverse_lookup(db, ["600000", "000001"], method="disclosed", top_n=0)
    assert result["stock_coverage"]["600000"] == 2
    assert result["stock_coverage"]["000001"] == 1


def test_reverse_lookup_unknown_method_raises(test_session):
    """Unknown method should raise ValueError."""
    with pytest.raises(ValueError, match="未知的反选方法"):
        reverse_lookup(test_session, ["600000"], method="invalid")


def test_reverse_lookup_strips_whitespace(test_session):
    """Input stock codes should be stripped of whitespace."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    db.flush()

    result = reverse_lookup(db, ["  600000  "], method="disclosed")
    assert result["fund_count"] == 1
    assert "600000" in result["stock_coverage"]


def test_reverse_lookup_empty_codes(test_session):
    """Empty/whitespace-only stock codes should produce empty results."""
    result = reverse_lookup(test_session, ["", "  "], method="disclosed")
    assert result["fund_count"] == 0
    assert result["results"] == []


def test_reverse_lookup_weighted_method(test_session):
    """weighted method should merge disclosed + simulated."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    db.add(_make_simulated("000002", date(2024, 6, 30), [
        {"stock_code": "600000", "estimated_weight": 0.08},
    ], tracking_error=0.02))
    db.flush()

    result = reverse_lookup(db, ["600000"], method="weighted", top_n=0)
    assert result["method"] == "weighted"
    assert result["fund_count"] == 2


# ============================================================
# persist_result tests
# ============================================================


def test_persist_result(test_session):
    """persist_result should write to reverse_lookup_result table."""
    db = test_session
    _add_disclosed_holding(db, "000001", date(2024, 6, 30), "600000", 5.0)
    db.flush()

    result = reverse_lookup(db, ["600000"], method="disclosed", top_n=0)
    row = persist_result(
        db, ["600000"], result,
        fund_scope="all", scope_id=None, method="disclosed",
    )
    db.commit()

    assert row.id is not None
    assert row.method == "disclosed"
    assert row.fund_scope == "all"
    assert row.stock_codes == ["600000"]
    assert len(row.results) == 1
    assert row.results[0]["fund_code"] == "000001"
    assert row.stock_coverage["600000"] == 1


def test_persist_result_hash_consistent(test_session):
    """The stored hash should match _hash_stock_codes output."""
    db = test_session
    result = {"results": [], "stock_coverage": {}}
    row = persist_result(
        db, ["600000", "000001"], result,
        fund_scope="all", scope_id=None, method="disclosed",
    )
    db.commit()

    expected_hash = _hash_stock_codes(["600000", "000001"])
    assert row.stock_codes_hash == expected_hash
