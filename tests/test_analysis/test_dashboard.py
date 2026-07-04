"""Tests for research dashboard data aggregation (P3.7)."""

from datetime import date, datetime

from fund_research.analysis.dashboard import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    DashboardData,
    gather_ai_alerts,
    gather_algorithm_alerts,
    gather_market_overview,
    gather_pool_monitoring,
    gather_today_changes,
    generate_dashboard,
)
from fund_research.db.models import FundMain, FundNAV
from fund_research.db.models_phase3 import AnomalyRecord, PoolAlertRecord

# ============================================================
# Constants / dataclass tests
# ============================================================


def test_algorithm_name_and_version():
    assert ALGORITHM_NAME == "dashboard"
    assert ALGORITHM_VERSION == "0.1.0"


def test_dashboard_data_to_data_returns_all_panels():
    data = DashboardData(
        today_changes={"fund_count": 1},
        pool_monitoring={"total_unread": 2},
        algorithm_alerts={"total": 3},
        ai_alerts={"total": 0},
        market_overview={"total_funds": 4},
        generated_at=datetime(2024, 1, 1, 12, 0, 0),
        warnings=["test warning"],
    )
    result = data.to_data()
    assert result["today_changes"] == {"fund_count": 1}
    assert result["pool_monitoring"] == {"total_unread": 2}
    assert result["algorithm_alerts"] == {"total": 3}
    assert result["ai_alerts"] == {"total": 0}
    assert result["market_overview"] == {"total_funds": 4}
    assert result["generated_at"] == "2024-01-01T12:00:00"
    assert result["warnings"] == ["test warning"]


def test_dashboard_data_defaults():
    data = DashboardData()
    result = data.to_data()
    assert result["today_changes"] == {}
    assert result["pool_monitoring"] == {}
    assert result["algorithm_alerts"] == {}
    assert result["ai_alerts"] == {}
    assert result["market_overview"] == {}
    assert result["warnings"] == []
    assert result["generated_at"] is not None


# ============================================================
# gather_today_changes tests
# ============================================================


def test_gather_today_changes_no_data(test_session):
    db = test_session
    result = gather_today_changes(db)
    assert result["fund_count"] == 0
    assert result["gainers"] == 0
    assert result["losers"] == 0
    assert result["unchanged"] == 0
    assert result["top_gainers"] == []
    assert result["top_losers"] == []
    assert result["latest_date"] is None
    assert result["previous_date"] is None


def test_gather_today_changes_with_data(test_session):
    db = test_session
    # Fund 000001: gainer (+5%)
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.05))
    # Fund 000002: loser (-5%)
    db.add(FundNAV(fund_code="000002", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000002", trade_date=date(2024, 1, 2), unit_nav=0.95))
    db.flush()

    result = gather_today_changes(db)
    assert result["latest_date"] == "2024-01-02"
    assert result["previous_date"] == "2024-01-01"
    assert result["fund_count"] == 2
    assert result["gainers"] == 1
    assert result["losers"] == 1
    assert result["unchanged"] == 0
    assert len(result["top_gainers"]) == 1
    assert result["top_gainers"][0]["fund_code"] == "000001"
    assert result["top_gainers"][0]["change_rate"] == 0.05
    assert result["top_gainers"][0]["latest_nav"] == 1.05
    assert len(result["top_losers"]) == 1
    assert result["top_losers"][0]["fund_code"] == "000002"
    assert result["top_losers"][0]["change_rate"] == -0.05
    assert result["top_losers"][0]["latest_nav"] == 0.95


def test_gather_today_changes_with_fund_codes_filter(test_session):
    db = test_session
    # Fund 000001: gainer
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.05))
    # Fund 000002: loser
    db.add(FundNAV(fund_code="000002", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000002", trade_date=date(2024, 1, 2), unit_nav=0.95))
    db.flush()

    result = gather_today_changes(db, fund_codes=["000001"])
    assert result["fund_count"] == 1
    assert result["gainers"] == 1
    assert result["losers"] == 0
    assert len(result["top_gainers"]) == 1
    assert result["top_gainers"][0]["fund_code"] == "000001"
    assert len(result["top_losers"]) == 0


def test_gather_today_changes_unchanged(test_session):
    db = test_session
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.00))
    db.flush()

    result = gather_today_changes(db)
    assert result["fund_count"] == 1
    assert result["gainers"] == 0
    assert result["losers"] == 0
    assert result["unchanged"] == 1


def test_gather_today_changes_top5_limit(test_session):
    db = test_session
    # Create 6 gainers to verify top 5 limit
    for i in range(6):
        code = f"00000{i}"
        db.add(FundNAV(fund_code=code, trade_date=date(2024, 1, 1), unit_nav=1.00))
        db.add(FundNAV(fund_code=code, trade_date=date(2024, 1, 2), unit_nav=1.01 + i * 0.01))
    db.flush()

    result = gather_today_changes(db)
    assert result["gainers"] == 6
    assert len(result["top_gainers"]) == 5
    # The biggest gainer (i=5, +6%) should be first
    assert result["top_gainers"][0]["fund_code"] == "000005"


# ============================================================
# gather_pool_monitoring tests
# ============================================================


def test_gather_pool_monitoring_no_alerts(test_session):
    db = test_session
    result = gather_pool_monitoring(db)
    assert result["total_unread"] == 0
    assert result["by_severity"] == {"info": 0, "warning": 0, "critical": 0}
    assert result["by_type"] == {}
    assert result["recent"] == []


def test_gather_pool_monitoring_with_data(test_session):
    db = test_session
    db.add(PoolAlertRecord(
        pool_id=1, fund_code="000001", alert_type="nav_change",
        severity="warning", message="test1", is_read=False,
    ))
    db.add(PoolAlertRecord(
        pool_id=1, fund_code="000002", alert_type="score_change",
        severity="critical", message="test2", is_read=False,
    ))
    db.add(PoolAlertRecord(
        pool_id=1, fund_code="000001", alert_type="nav_change",
        severity="info", message="test3", is_read=True,
    ))
    db.flush()

    result = gather_pool_monitoring(db)
    # Only 2 unread (the 3rd is read)
    assert result["total_unread"] == 2
    assert result["by_severity"]["warning"] == 1
    assert result["by_severity"]["critical"] == 1
    assert result["by_severity"]["info"] == 0
    assert result["by_type"]["nav_change"] == 1
    assert result["by_type"]["score_change"] == 1
    assert len(result["recent"]) == 2
    for item in result["recent"]:
        assert "fund_code" in item
        assert "alert_type" in item
        assert "severity" in item
        assert "message" in item
        assert "triggered_at" in item


# ============================================================
# gather_algorithm_alerts tests
# ============================================================


def test_gather_algorithm_alerts_no_anomalies(test_session):
    db = test_session
    result = gather_algorithm_alerts(db)
    assert result["total"] == 0
    assert result["by_rule"] == {}
    assert result["by_severity"] == {}
    assert result["recent"] == []


def test_gather_algorithm_alerts_with_data(test_session):
    db = test_session
    db.add(AnomalyRecord(
        fund_code="000001", rule_name="style_drift", severity="warning",
        description="test1", detail={}, scope="all",
        conclusion_status="observation",
    ))
    db.add(AnomalyRecord(
        fund_code="000002", rule_name="concentration_anomaly", severity="observation",
        description="test2", detail={}, scope="all",
        conclusion_status="observation",
    ))
    db.flush()

    result = gather_algorithm_alerts(db)
    assert result["total"] == 2
    assert result["by_rule"]["style_drift"] == 1
    assert result["by_rule"]["concentration_anomaly"] == 1
    assert result["by_severity"]["warning"] == 1
    assert result["by_severity"]["observation"] == 1
    assert len(result["recent"]) == 2
    for item in result["recent"]:
        assert "fund_code" in item
        assert "rule_name" in item
        assert "severity" in item
        assert "description" in item
        assert "detected_at" in item


# ============================================================
# gather_ai_alerts tests
# ============================================================


def test_gather_ai_alerts_placeholder(test_session):
    db = test_session
    result = gather_ai_alerts(db)
    assert result["total"] == 0
    assert result["alerts"] == []
    assert result["note"] == "AI 告警功能将在后续版本上线"


# ============================================================
# gather_market_overview tests
# ============================================================


def test_gather_market_overview_no_funds(test_session):
    db = test_session
    result = gather_market_overview(db)
    assert result["total_funds"] == 0
    assert result["by_category"] == {}
    assert result["by_operation_mode"] == {}


def test_gather_market_overview_with_data(test_session):
    db = test_session
    db.add(FundMain(
        fund_code="000001", short_name="t1", full_name="t1",
        category="混合型", operation_mode="开放式",
    ))
    db.add(FundMain(
        fund_code="000002", short_name="t2", full_name="t2",
        category="混合型", operation_mode="开放式",
    ))
    db.add(FundMain(
        fund_code="000003", short_name="t3", full_name="t3",
        category="股票型", operation_mode="封闭式",
    ))
    db.flush()

    result = gather_market_overview(db)
    assert result["total_funds"] == 3
    assert result["by_category"]["混合型"] == 2
    assert result["by_category"]["股票型"] == 1
    assert result["by_operation_mode"]["开放式"] == 2
    assert result["by_operation_mode"]["封闭式"] == 1


# ============================================================
# generate_dashboard tests
# ============================================================


def test_generate_dashboard_assembles_all_panels(test_session):
    db = test_session
    db.add(FundMain(
        fund_code="000001", short_name="t", full_name="t", category="混合型",
    ))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 1), unit_nav=1.00))
    db.add(FundNAV(fund_code="000001", trade_date=date(2024, 1, 2), unit_nav=1.05))
    db.add(PoolAlertRecord(
        pool_id=1, fund_code="000001", alert_type="nav_change",
        severity="warning", message="test", is_read=False,
    ))
    db.add(AnomalyRecord(
        fund_code="000001", rule_name="style_drift", severity="warning",
        description="test", detail={}, scope="all",
        conclusion_status="observation",
    ))
    db.flush()

    result = generate_dashboard(db)
    assert isinstance(result, DashboardData)
    data = result.to_data()

    # All 5 panels present
    assert "today_changes" in data
    assert "pool_monitoring" in data
    assert "algorithm_alerts" in data
    assert "ai_alerts" in data
    assert "market_overview" in data
    assert "generated_at" in data
    assert "warnings" in data

    # today_changes
    assert data["today_changes"]["fund_count"] == 1
    assert data["today_changes"]["gainers"] == 1

    # pool_monitoring
    assert data["pool_monitoring"]["total_unread"] == 1

    # algorithm_alerts
    assert data["algorithm_alerts"]["total"] == 1

    # ai_alerts (placeholder)
    assert data["ai_alerts"]["total"] == 0

    # market_overview
    assert data["market_overview"]["total_funds"] == 1


def test_generate_dashboard_handles_nonexistent_fund(test_session):
    db = test_session
    db.add(FundMain(
        fund_code="000001", short_name="t", full_name="t", category="混合型",
    ))
    db.flush()

    result = generate_dashboard(db, fund_codes=["NONEXISTENT"])
    assert isinstance(result, DashboardData)
    data = result.to_data()
    # today_changes should be empty (no NAV for non-existent fund)
    assert data["today_changes"]["fund_count"] == 0
    # market_overview should still work (queries all funds)
    assert data["market_overview"]["total_funds"] == 1


def test_generate_dashboard_handles_panel_exception(test_session, monkeypatch):
    db = test_session
    db.add(FundMain(
        fund_code="000001", short_name="t", full_name="t", category="混合型",
    ))
    db.commit()

    import fund_research.analysis.dashboard as dashboard_mod

    def boom(_db, _fund_codes=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(dashboard_mod, "gather_today_changes", boom)

    result = generate_dashboard(db)
    data = result.to_data()
    # today_changes should contain error dict (exception caught)
    assert data["today_changes"] == {"error": "boom"}
    # A warning should be added
    assert any("today_changes" in w for w in result.warnings)
    # Other panels should still work (fund was committed, so market_overview finds it)
    assert data["market_overview"]["total_funds"] == 1


def test_generate_dashboard_empty_db(test_session):
    db = test_session
    result = generate_dashboard(db)
    assert isinstance(result, DashboardData)
    data = result.to_data()
    assert data["today_changes"]["fund_count"] == 0
    assert data["pool_monitoring"]["total_unread"] == 0
    assert data["algorithm_alerts"]["total"] == 0
    assert data["ai_alerts"]["total"] == 0
    assert data["market_overview"]["total_funds"] == 0
    assert data["warnings"] == []
