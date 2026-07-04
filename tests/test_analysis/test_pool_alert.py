"""Tests for fund pool alert management (P3.4)."""

from datetime import date, timedelta

from fund_research.analysis.pool_alert import (
    ALERT_TYPES,
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    AlertRecordData,
    check_manager_change,
    check_nav_change,
    check_scale_change,
    check_score_change,
    create_alert_rule,
    get_alert_records,
    get_alert_rules,
    mark_alert_read,
    scan_pool_alerts,
)
from fund_research.db.models import FundManagerTenure, FundNAV, FundScale
from fund_research.db.models_phase2 import (
    FundPool as DbFundPool,
)
from fund_research.db.models_phase2 import (
    FundPoolMember as DbFundPoolMember,
)
from fund_research.db.models_phase2 import ScoringResult

# ============================================================
# Dataclass / constants tests
# ============================================================


def test_alert_record_data_to_data():
    item = AlertRecordData(
        fund_code="000001",
        alert_type="nav_change",
        severity="warning",
        message="净值异动",
        detail={"change_rate": 0.05},
    )
    data = item.to_data()
    assert data["fund_code"] == "000001"
    assert data["alert_type"] == "nav_change"
    assert data["severity"] == "warning"
    assert data["message"] == "净值异动"
    assert data["detail"]["change_rate"] == 0.05
    assert data["algorithm_name"] == ALGORITHM_NAME
    assert data["algorithm_version"] == ALGORITHM_VERSION


def test_alert_types_complete():
    expected_types = {
        "nav_change", "ranking_change", "manager_change",
        "scale_change", "style_drift", "score_change",
    }
    assert set(ALERT_TYPES.keys()) == expected_types


def test_alert_types_have_defaults():
    for alert_type, definition in ALERT_TYPES.items():
        assert "description" in definition, f"{alert_type} missing description"
        assert "default_params" in definition, f"{alert_type} missing default_params"


# ============================================================
# check_nav_change tests
# ============================================================


def test_nav_change_triggers_warning(test_session):
    """Change > 5% should trigger severity=warning."""
    db = test_session
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.06))
    db.flush()
    result = check_nav_change(db, "000001")
    assert result is not None
    assert result.alert_type == "nav_change"
    assert result.severity == "warning"
    assert result.detail["change_rate"] > 0.05


def test_nav_change_triggers_info(test_session):
    """Change between 3% and 5% should trigger severity=info."""
    db = test_session
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.04))
    db.flush()
    result = check_nav_change(db, "000001")
    assert result is not None
    assert result.severity == "info"


def test_nav_change_no_trigger_below_threshold(test_session):
    """Change <= 3% should not trigger."""
    db = test_session
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.02))
    db.flush()
    result = check_nav_change(db, "000001")
    assert result is None


def test_nav_change_insufficient_data(test_session):
    """Only 1 NAV row should return None."""
    db = test_session
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.flush()
    result = check_nav_change(db, "000001")
    assert result is None


def test_nav_change_uses_adjusted_nav_priority(test_session):
    """adjusted_nav should be preferred over accumulated_nav and unit_nav."""
    db = test_session
    db.add(FundNAV(
        fund_code="000001", trade_date=date(2024, 1, 1),
        unit_nav=1.00, accumulated_nav=1.00, adjusted_nav=1.00,
    ))
    db.add(FundNAV(
        fund_code="000001", trade_date=date(2024, 1, 2),
        unit_nav=1.01, accumulated_nav=1.01, adjusted_nav=1.10,
    ))
    db.flush()
    result = check_nav_change(db, "000001")
    assert result is not None
    assert result.detail["latest_nav"] == 1.10


def test_nav_change_custom_threshold(test_session):
    """Custom threshold should override default."""
    db = test_session
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.02))
    db.flush()
    # Default threshold 3% won't trigger, but 1% will
    result = check_nav_change(db, "000001", {"threshold": 0.01})
    assert result is not None


# ============================================================
# check_scale_change tests
# ============================================================


def test_scale_change_triggers_critical(test_session):
    """Change > 50% should trigger severity=critical."""
    db = test_session
    db.add(FundScale(fund_code="000001", report_date=date(2024, 3, 31), total_nav=10.0))
    db.add(FundScale(fund_code="000001", report_date=date(2024, 6, 30), total_nav=20.0))
    db.flush()
    result = check_scale_change(db, "000001")
    assert result is not None
    assert result.alert_type == "scale_change"
    assert result.severity == "critical"


def test_scale_change_triggers_warning(test_session):
    """Change between 30% and 50% should trigger severity=warning."""
    db = test_session
    db.add(FundScale(fund_code="000001", report_date=date(2024, 3, 31), total_nav=10.0))
    db.add(FundScale(fund_code="000001", report_date=date(2024, 6, 30), total_nav=14.0))
    db.flush()
    result = check_scale_change(db, "000001")
    assert result is not None
    assert result.severity == "warning"


def test_scale_change_no_trigger(test_session):
    """Change <= 30% should not trigger."""
    db = test_session
    db.add(FundScale(fund_code="000001", report_date=date(2024, 3, 31), total_nav=10.0))
    db.add(FundScale(fund_code="000001", report_date=date(2024, 6, 30), total_nav=12.0))
    db.flush()
    result = check_scale_change(db, "000001")
    assert result is None


def test_scale_change_insufficient_data(test_session):
    """Only 1 scale row should return None."""
    db = test_session
    db.add(FundScale(fund_code="000001", report_date=date(2024, 6, 30), total_nav=10.0))
    db.flush()
    result = check_scale_change(db, "000001")
    assert result is None


# ============================================================
# check_manager_change tests
# ============================================================


def test_manager_change_triggers_within_30_days(test_session):
    """A tenure starting within the last 30 days should trigger."""
    db = test_session
    recent_date = date.today() - timedelta(days=10)
    db.add(FundManagerTenure(
        manager_id="M001", fund_code="000001",
        start_date=recent_date, is_current=True,
    ))
    db.flush()
    result = check_manager_change(db, "000001")
    assert result is not None
    assert result.alert_type == "manager_change"
    assert result.severity == "info"
    assert result.detail["manager_id"] == "M001"


def test_manager_change_no_trigger_outside_window(test_session):
    """A tenure starting more than 30 days ago should not trigger."""
    db = test_session
    old_date = date.today() - timedelta(days=60)
    db.add(FundManagerTenure(
        manager_id="M001", fund_code="000001",
        start_date=old_date, is_current=True,
    ))
    db.flush()
    result = check_manager_change(db, "000001")
    assert result is None


# ============================================================
# check_score_change tests
# ============================================================


def _make_scoring(fund_code: str, calc_date: date, total_score: float) -> ScoringResult:
    return ScoringResult(
        fund_code=fund_code,
        calc_date=calc_date,
        score_version="v1.0",
        algorithm_version="0.1",
        weight_config={"return": 0.2},
        sub_scores={"return": 80.0},
        total_score=total_score,
    )


def test_score_change_triggers_warning(test_session):
    """Change > 20 points should trigger severity=warning."""
    db = test_session
    db.add(_make_scoring("000001", date(2024, 6, 30), 60.0))
    db.add(_make_scoring("000001", date(2024, 9, 30), 85.0))
    db.flush()
    result = check_score_change(db, "000001")
    assert result is not None
    assert result.alert_type == "score_change"
    assert result.severity == "warning"


def test_score_change_triggers_info(test_session):
    """Change between 10 and 20 points should trigger severity=info."""
    db = test_session
    db.add(_make_scoring("000001", date(2024, 6, 30), 60.0))
    db.add(_make_scoring("000001", date(2024, 9, 30), 73.0))
    db.flush()
    result = check_score_change(db, "000001")
    assert result is not None
    assert result.severity == "info"


def test_score_change_no_trigger(test_session):
    """Change <= 10 points should not trigger."""
    db = test_session
    db.add(_make_scoring("000001", date(2024, 6, 30), 60.0))
    db.add(_make_scoring("000001", date(2024, 9, 30), 68.0))
    db.flush()
    result = check_score_change(db, "000001")
    assert result is None


def test_score_change_insufficient_data(test_session):
    """Only 1 scoring row should return None."""
    db = test_session
    db.add(_make_scoring("000001", date(2024, 9, 30), 60.0))
    db.flush()
    result = check_score_change(db, "000001")
    assert result is None


# ============================================================
# scan_pool_alerts tests
# ============================================================


def _create_pool_with_funds(db, fund_codes: list[str]) -> int:
    """Helper: create a pool with given fund codes, return pool_id."""
    pool = DbFundPool(name="test_pool")
    db.add(pool)
    db.flush()
    for code in fund_codes:
        db.add(DbFundPoolMember(pool_id=pool.id, fund_code=code))
    db.flush()
    return pool.id


def test_scan_pool_alerts_multiple_funds(test_session):
    """Scan should aggregate alerts from all funds in the pool."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001", "000002"])
    # Fund 000001: NAV change triggers
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.10))
    # Fund 000002: NAV change triggers
    db.add(FundNAV(fund_code="000002", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000002", trade_date=date(2024, 1, 2), unit_nav=1.08))
    db.flush()

    results, warnings = scan_pool_alerts(db, pool_id, alert_types=["nav_change"])
    assert len(results) == 2
    fund_codes_in_results = {r.fund_code for r in results}
    assert fund_codes_in_results == {"000001", "000002"}


def test_scan_pool_alerts_filtered_types(test_session):
    """Scan with specific alert_types should only run those checks."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001"])
    # NAV change triggers
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.10))
    # Scale change triggers
    db.add(FundScale(fund_code="000001", report_date=date(2024, 3, 31), total_nav=10.0))
    db.add(FundScale(fund_code="000001", report_date=date(2024, 6, 30), total_nav=20.0))
    db.flush()

    results, warnings = scan_pool_alerts(db, pool_id, alert_types=["nav_change"])
    assert len(results) == 1
    assert results[0].alert_type == "nav_change"


def test_scan_pool_alerts_empty_pool(test_session):
    """Scanning an empty pool should return no alerts."""
    db = test_session
    pool_id = _create_pool_with_funds(db, [])
    results, warnings = scan_pool_alerts(db, pool_id)
    assert results == []


def test_scan_pool_alerts_with_params_override(test_session):
    """Custom params should override defaults."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001"])
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.02))
    db.flush()

    # Default threshold 3% won't trigger, but 1% will
    results, warnings = scan_pool_alerts(
        db, pool_id, alert_types=["nav_change"],
        params={"nav_change": {"threshold": 0.01}},
    )
    assert len(results) == 1


# ============================================================
# Persistence tests
# ============================================================


def test_create_and_get_alert_rules(test_session):
    """create_alert_rule should persist and get_alert_rules should retrieve."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001"])
    rule = create_alert_rule(db, pool_id, "000001", "nav_change", {"threshold": 0.05})
    db.commit()

    rules = get_alert_rules(db, pool_id)
    assert len(rules) == 1
    assert rules[0].fund_code == "000001"
    assert rules[0].alert_type == "nav_change"
    assert rules[0].params["threshold"] == 0.05
    assert rules[0].is_active is True
    assert rules[0].id == rule.id


def test_get_alert_rules_filter_by_fund(test_session):
    """get_alert_rules should filter by fund_code."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001", "000002"])
    create_alert_rule(db, pool_id, "000001", "nav_change")
    create_alert_rule(db, pool_id, "000002", "score_change")
    db.commit()

    rules = get_alert_rules(db, pool_id, fund_code="000001")
    assert len(rules) == 1
    assert rules[0].fund_code == "000001"


def test_get_alert_records_with_filters(test_session):
    """get_alert_records should support pool/fund/is_read filters."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001"])
    from fund_research.db.models_phase3 import PoolAlertRecord

    db.add(PoolAlertRecord(
        pool_id=pool_id, fund_code="000001", alert_type="nav_change",
        severity="info", message="test1", is_read=False,
    ))
    db.add(PoolAlertRecord(
        pool_id=pool_id, fund_code="000001", alert_type="score_change",
        severity="warning", message="test2", is_read=True,
    ))
    db.commit()

    # All records for pool
    all_records = get_alert_records(db, pool_id=pool_id)
    assert len(all_records) == 2

    # Only unread
    unread = get_alert_records(db, pool_id=pool_id, is_read=False)
    assert len(unread) == 1
    assert unread[0].alert_type == "nav_change"

    # Only read
    read_records = get_alert_records(db, pool_id=pool_id, is_read=True)
    assert len(read_records) == 1
    assert read_records[0].alert_type == "score_change"


def test_mark_alert_read(test_session):
    """mark_alert_read should set is_read=True."""
    db = test_session
    pool_id = _create_pool_with_funds(db, ["000001"])
    from fund_research.db.models_phase3 import PoolAlertRecord

    record = PoolAlertRecord(
        pool_id=pool_id, fund_code="000001", alert_type="nav_change",
        severity="info", message="test", is_read=False,
    )
    db.add(record)
    db.commit()

    updated = mark_alert_read(db, record.id)
    db.commit()
    assert updated is not None
    assert updated.is_read is True


def test_mark_alert_read_not_found(test_session):
    """mark_alert_read with non-existent ID should return None."""
    db = test_session
    result = mark_alert_read(db, 999999)
    assert result is None
