"""Tests for research task templates (P3.6)."""

from datetime import date, datetime

import pytest

from fund_research.analysis.research_template import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    BUILTIN_TEMPLATES,
    TemplateRunResult,
    TemplateStepResult,
    get_run_record,
    get_run_records,
    get_template,
    list_templates,
    run_template,
    seed_builtin_templates,
)
from fund_research.db.models import (
    FundDisclosedHoldings,
    FundMain,
    FundManagerTenure,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import ScoringResult
from fund_research.db.models_phase3 import ResearchTemplate

# ============================================================
# Test helpers
# ============================================================


def _create_fund(db, fund_code="000001", category="混合型", sub_category="偏股混合"):
    """Create a test fund in the database."""
    fund = FundMain(
        fund_code=fund_code,
        short_name="测试基金",
        full_name="测试基金全称",
        category=category,
        sub_category=sub_category,
    )
    db.add(fund)
    db.flush()
    return fund


def _create_scoring(db, fund_code="000001", total_score=75.5):
    """Create a scoring result for a fund."""
    db.add(
        ScoringResult(
            fund_code=fund_code,
            calc_date=date(2024, 12, 31),
            score_version="v0.1",
            algorithm_version="0.1.0",
            weight_config={"return": 0.2, "risk": 0.2, "alpha": 0.15},
            total_score=total_score,
            sub_scores={"return": 80, "risk": 70, "alpha": 65},
            contains_estimated=False,
            confidence="high",
            conclusion_status="computed",
        )
    )
    db.flush()


def _create_style_exposure(db, fund_code="000001"):
    """Create style exposure data for a fund."""
    db.add(
        StyleExposureResult(
            fund_code=fund_code,
            calc_date=date(2024, 12, 31),
            algorithm_name="style_exposure",
            algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={
                "large_cap": 0.6,
                "mid_cap": 0.3,
                "small_cap": 0.1,
                "growth": 0.5,
                "value": 0.5,
            },
            r_squared=0.85,
            conclusion_status="computed",
        )
    )
    db.flush()


def _create_disclosed_holdings(db, fund_code="000001", report_date=None):
    """Create disclosed stock holdings for a fund."""
    if report_date is None:
        report_date = date(2024, 12, 31)
    stocks = [
        ("600519", 8.5),
        ("000858", 6.2),
        ("002714", 5.1),
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


def _create_manager_tenure(db, fund_code="000001", manager_id="M001"):
    """Create manager tenure data."""
    db.add(
        FundManagerTenure(
            fund_code=fund_code,
            manager_id=manager_id,
            start_date=date(2020, 1, 1),
            end_date=None,
            is_current=True,
        )
    )
    db.flush()


# ============================================================
# BUILTIN_TEMPLATES tests
# ============================================================


def test_builtin_templates_count():
    """BUILTIN_TEMPLATES should have exactly 5 templates."""
    assert len(BUILTIN_TEMPLATES) == 5


def test_builtin_templates_ids():
    """BUILTIN_TEMPLATES should have the expected template IDs."""
    expected_ids = {
        "single_fund_checkup",
        "manager_profile",
        "active_equity_screen",
        "style_drift_monitor",
        "stock_reverse_lookup",
    }
    assert set(BUILTIN_TEMPLATES.keys()) == expected_ids


@pytest.mark.parametrize("template_id", list(BUILTIN_TEMPLATES.keys()))
def test_builtin_template_structure(template_id):
    """Each built-in template should have required fields."""
    spec = BUILTIN_TEMPLATES[template_id]
    assert spec["template_id"] == template_id
    assert isinstance(spec["name"], str) and spec["name"]
    assert isinstance(spec["description"], str) and spec["description"]
    assert "definition" in spec
    steps = spec["definition"]["steps"]
    assert isinstance(steps, list) and len(steps) > 0
    for step in steps:
        assert "name" in step
        assert "tool" in step
        assert "params" in step


def test_single_fund_checkup_steps():
    """single_fund_checkup should have fingerprint, scoring, anomaly_scan."""
    steps = BUILTIN_TEMPLATES["single_fund_checkup"]["definition"]["steps"]
    tools = [s["tool"] for s in steps]
    assert tools == ["fingerprint", "scoring", "anomaly_scan"]


def test_manager_profile_steps():
    """manager_profile should have the expected step tools."""
    steps = BUILTIN_TEMPLATES["manager_profile"]["definition"]["steps"]
    tools = [s["tool"] for s in steps]
    assert tools == ["manager_tenure_query", "fund_list_by_manager", "scoring_summary"]


def test_active_equity_screen_steps():
    """active_equity_screen should have 4 steps."""
    steps = BUILTIN_TEMPLATES["active_equity_screen"]["definition"]["steps"]
    tools = [s["tool"] for s in steps]
    assert tools == ["fingerprint", "scoring", "similarity_search", "anomaly_scan"]


def test_style_drift_monitor_steps():
    """style_drift_monitor should have style_exposure_query and anomaly_scan."""
    steps = BUILTIN_TEMPLATES["style_drift_monitor"]["definition"]["steps"]
    tools = [s["tool"] for s in steps]
    assert tools == ["style_exposure_query", "anomaly_scan"]


def test_stock_reverse_lookup_steps():
    """stock_reverse_lookup should have reverse_lookup and fund_detail_query."""
    steps = BUILTIN_TEMPLATES["stock_reverse_lookup"]["definition"]["steps"]
    tools = [s["tool"] for s in steps]
    assert tools == ["reverse_lookup", "fund_detail_query"]


# ============================================================
# seed_builtin_templates tests
# ============================================================


def test_seed_builtin_templates_inserts(test_session):
    """seed_builtin_templates should insert all 5 templates."""
    db = test_session
    count = seed_builtin_templates(db)
    assert count == 5
    templates = list_templates(db)
    assert len(templates) == 5


def test_seed_builtin_templates_idempotent(test_session):
    """seed_builtin_templates should be idempotent."""
    db = test_session
    first = seed_builtin_templates(db)
    assert first == 5
    second = seed_builtin_templates(db)
    assert second == 0
    templates = list_templates(db)
    assert len(templates) == 5


def test_seed_builtin_templates_sets_is_builtin(test_session):
    """Seeded templates should have is_builtin=True."""
    db = test_session
    seed_builtin_templates(db)
    templates = list_templates(db)
    for t in templates:
        assert t.is_builtin is True


# ============================================================
# list_templates / get_template tests
# ============================================================


def test_list_templates_empty(test_session):
    """list_templates should return empty list when no templates exist."""
    db = test_session
    assert list_templates(db) == []


def test_list_templates_builtin_only(test_session):
    """list_templates with builtin_only should filter correctly."""
    db = test_session
    seed_builtin_templates(db)
    # Add a custom (non-builtin) template.
    db.add(
        ResearchTemplate(
            template_id="custom_template",
            name="自定义模板",
            description="test",
            definition={"steps": []},
            is_builtin=False,
        )
    )
    db.flush()

    all_templates = list_templates(db, builtin_only=False)
    assert len(all_templates) == 6

    builtin_templates = list_templates(db, builtin_only=True)
    assert len(builtin_templates) == 5
    for t in builtin_templates:
        assert t.is_builtin is True


def test_get_template_found(test_session):
    """get_template should return the template by ID."""
    db = test_session
    seed_builtin_templates(db)
    template = get_template(db, "single_fund_checkup")
    assert template is not None
    assert template.template_id == "single_fund_checkup"
    assert template.name == "单基金体检"


def test_get_template_not_found(test_session):
    """get_template should return None for unknown ID."""
    db = test_session
    seed_builtin_templates(db)
    assert get_template(db, "nonexistent") is None


def test_get_template_empty_db(test_session):
    """get_template should return None on an empty database."""
    db = test_session
    assert get_template(db, "single_fund_checkup") is None


# ============================================================
# run_template tests
# ============================================================


def test_run_template_single_fund_checkup(test_session):
    """run_template should execute single_fund_checkup successfully."""
    db = test_session
    _create_fund(db, "000001")
    _create_scoring(db, "000001")
    _create_style_exposure(db, "000001")
    seed_builtin_templates(db)

    result = run_template(db, "single_fund_checkup", {"fund_code": "000001"})

    assert isinstance(result, TemplateRunResult)
    assert result.template_id == "single_fund_checkup"
    assert result.steps_total == 3
    assert result.status == "completed"
    assert len(result.step_results) == 3

    # The fingerprint step should succeed (fund exists).
    fp_step = result.step_results[0]
    assert fp_step.tool == "fingerprint"
    assert fp_step.status == "success"
    assert "fund_code" in fp_step.result

    # The scoring step should succeed (scoring result exists).
    scoring_step = result.step_results[1]
    assert scoring_step.tool == "scoring"
    assert scoring_step.status == "success"
    assert scoring_step.result["total_score"] == 75.5

    # The anomaly scan step should succeed (runs without error).
    anomaly_step = result.step_results[2]
    assert anomaly_step.tool == "anomaly_scan"
    assert anomaly_step.status == "success"
    assert "anomaly_count" in anomaly_step.result


def test_run_template_single_fund_checkup_run_id(test_session):
    """run_template should create a run record with a valid run_id."""
    db = test_session
    _create_fund(db, "000001")
    _create_scoring(db, "000001")
    seed_builtin_templates(db)

    result = run_template(db, "single_fund_checkup", {"fund_code": "000001"})
    assert result.run_id > 0

    record = get_run_record(db, result.run_id)
    assert record is not None
    assert record.template_id == "single_fund_checkup"
    assert record.status == "completed"
    assert record.steps_total == 3


def test_run_template_stock_reverse_lookup(test_session):
    """run_template should execute stock_reverse_lookup with stock_codes."""
    db = test_session
    _create_fund(db, "000001")
    _create_disclosed_holdings(db, "000001")
    seed_builtin_templates(db)

    result = run_template(
        db,
        "stock_reverse_lookup",
        {"stock_codes": ["600519", "000858"]},
    )

    assert result.template_id == "stock_reverse_lookup"
    assert result.steps_total == 2
    assert len(result.step_results) == 2

    # Step 1: reverse_lookup
    rl_step = result.step_results[0]
    assert rl_step.tool == "reverse_lookup"
    assert rl_step.status == "success"
    assert "results" in rl_step.result
    assert rl_step.result["fund_count"] >= 1

    # Step 2: fund_detail_query (uses fund_code from inputs, not from
    # reverse_lookup output, so it may be skipped if no fund_code in inputs).
    detail_step = result.step_results[1]
    assert detail_step.tool == "fund_detail_query"


def test_run_template_nonexistent_raises(test_session):
    """run_template should raise ValueError for unknown template_id."""
    db = test_session
    seed_builtin_templates(db)
    with pytest.raises(ValueError, match="template not found"):
        run_template(db, "nonexistent_template", {"fund_code": "000001"})


def test_run_template_missing_input_skipped(test_session):
    """run_template should skip steps when required input is missing."""
    db = test_session
    seed_builtin_templates(db)

    # No fund_code provided — fingerprint and scoring should be skipped.
    result = run_template(db, "single_fund_checkup", {})

    assert result.steps_total == 3
    fp_step = result.step_results[0]
    assert fp_step.status == "skipped"
    assert fp_step.error is not None

    scoring_step = result.step_results[1]
    assert scoring_step.status == "skipped"


def test_run_template_manager_profile(test_session):
    """run_template should execute manager_profile with manager_id input."""
    db = test_session
    _create_fund(db, "000001")
    _create_manager_tenure(db, "000001", "M001")
    _create_scoring(db, "000001")
    seed_builtin_templates(db)

    result = run_template(db, "manager_profile", {"manager_id": "M001"})

    assert result.template_id == "manager_profile"
    assert result.steps_total == 3

    # Step 1: manager_tenure_query
    tenure_step = result.step_results[0]
    assert tenure_step.tool == "manager_tenure_query"
    assert tenure_step.status == "success"
    assert tenure_step.result["count"] == 1

    # Step 2: fund_list_by_manager
    list_step = result.step_results[1]
    assert list_step.tool == "fund_list_by_manager"
    assert list_step.status == "success"
    assert list_step.result["count"] == 1

    # Step 3: scoring_summary
    summary_step = result.step_results[2]
    assert summary_step.tool == "scoring_summary"
    assert summary_step.status == "success"
    assert summary_step.result["count"] == 1


def test_run_template_style_drift_monitor(test_session):
    """run_template should execute style_drift_monitor."""
    db = test_session
    _create_fund(db, "000001")
    _create_style_exposure(db, "000001")
    seed_builtin_templates(db)

    result = run_template(db, "style_drift_monitor", {"fund_code": "000001"})

    assert result.template_id == "style_drift_monitor"
    assert result.steps_total == 2

    # Step 1: style_exposure_query
    exposure_step = result.step_results[0]
    assert exposure_step.tool == "style_exposure_query"
    assert exposure_step.status == "success"
    assert exposure_step.result["count"] == 1

    # Step 2: anomaly_scan (style_drift rule needs >=4 data points, so no
    # anomaly expected, but step should still succeed).
    anomaly_step = result.step_results[1]
    assert anomaly_step.tool == "anomaly_scan"
    assert anomaly_step.status == "success"


# ============================================================
# get_run_records / get_run_record tests
# ============================================================


def test_get_run_records_after_run(test_session):
    """get_run_records should return records after a run."""
    db = test_session
    _create_fund(db, "000001")
    _create_scoring(db, "000001")
    seed_builtin_templates(db)

    run_template(db, "single_fund_checkup", {"fund_code": "000001"})

    records = get_run_records(db)
    assert len(records) == 1
    assert records[0].template_id == "single_fund_checkup"
    assert records[0].status == "completed"


def test_get_run_records_filter_by_template(test_session):
    """get_run_records should filter by template_id."""
    db = test_session
    _create_fund(db, "000001")
    _create_scoring(db, "000001")
    _create_style_exposure(db, "000001")
    seed_builtin_templates(db)

    run_template(db, "single_fund_checkup", {"fund_code": "000001"})
    run_template(db, "style_drift_monitor", {"fund_code": "000001"})

    all_records = get_run_records(db)
    assert len(all_records) == 2

    filtered = get_run_records(db, template_id="single_fund_checkup")
    assert len(filtered) == 1
    assert filtered[0].template_id == "single_fund_checkup"


def test_get_run_records_limit(test_session):
    """get_run_records should respect the limit parameter."""
    db = test_session
    _create_fund(db, "000001")
    seed_builtin_templates(db)

    for _ in range(5):
        run_template(db, "style_drift_monitor", {"fund_code": "000001"})

    records = get_run_records(db, limit=3)
    assert len(records) == 3


def test_get_run_record_found(test_session):
    """get_run_record should return the specific record."""
    db = test_session
    _create_fund(db, "000001")
    seed_builtin_templates(db)

    result = run_template(db, "style_drift_monitor", {"fund_code": "000001"})

    record = get_run_record(db, result.run_id)
    assert record is not None
    assert record.id == result.run_id
    assert record.template_id == "style_drift_monitor"
    assert record.steps_total == 2
    assert record.step_results is not None
    assert len(record.step_results) == 2


def test_get_run_record_not_found(test_session):
    """get_run_record should return None for unknown run_id."""
    db = test_session
    assert get_run_record(db, 99999) is None


def test_get_run_records_empty(test_session):
    """get_run_records should return empty list when no runs exist."""
    db = test_session
    assert get_run_records(db) == []


# ============================================================
# Dataclass to_data() tests
# ============================================================


def test_template_step_result_to_data():
    """TemplateStepResult.to_data() should return expected dict."""
    step = TemplateStepResult(
        step_name="测试步骤",
        tool="fingerprint",
        status="success",
        result={"fund_code": "000001"},
        error=None,
        duration_ms=12.345,
    )
    data = step.to_data()
    assert data["step_name"] == "测试步骤"
    assert data["tool"] == "fingerprint"
    assert data["status"] == "success"
    assert data["result"] == {"fund_code": "000001"}
    assert data["error"] is None
    assert data["duration_ms"] == 12.345


def test_template_step_result_to_data_failed():
    """TemplateStepResult.to_data() should include error for failed steps."""
    step = TemplateStepResult(
        step_name="失败步骤",
        tool="scoring",
        status="failed",
        result={},
        error="database error",
        duration_ms=5.0,
    )
    data = step.to_data()
    assert data["status"] == "failed"
    assert data["error"] == "database error"


def test_template_run_result_to_data():
    """TemplateRunResult.to_data() should return expected dict."""
    started = datetime(2024, 12, 31, 10, 0, 0)
    completed = datetime(2024, 12, 31, 10, 0, 5)
    step = TemplateStepResult(
        step_name="步骤1",
        tool="fingerprint",
        status="success",
        result={"key": "value"},
        duration_ms=10.0,
    )
    run = TemplateRunResult(
        template_id="single_fund_checkup",
        run_id=1,
        status="completed",
        steps_total=1,
        steps_completed=1,
        steps_failed=0,
        step_results=[step],
        started_at=started,
        completed_at=completed,
        warnings=[],
    )
    data = run.to_data()
    assert data["template_id"] == "single_fund_checkup"
    assert data["run_id"] == 1
    assert data["status"] == "completed"
    assert data["steps_total"] == 1
    assert data["steps_completed"] == 1
    assert data["steps_failed"] == 0
    assert len(data["step_results"]) == 1
    assert data["step_results"][0]["tool"] == "fingerprint"
    assert data["started_at"] == "2024-12-31T10:00:00"
    assert data["completed_at"] == "2024-12-31T10:00:05"
    assert data["warnings"] == []


def test_template_run_result_to_data_with_warnings():
    """TemplateRunResult.to_data() should include warnings."""
    run = TemplateRunResult(
        template_id="test",
        run_id=1,
        status="completed_with_errors",
        steps_total=2,
        steps_completed=1,
        steps_failed=1,
        step_results=[],
        started_at=datetime(2024, 1, 1),
        completed_at=None,
        warnings=["步骤1失败"],
    )
    data = run.to_data()
    assert data["status"] == "completed_with_errors"
    assert data["completed_at"] is None
    assert data["warnings"] == ["步骤1失败"]


# ============================================================
# Algorithm metadata tests
# ============================================================


def test_algorithm_metadata():
    """ALGORITHM_NAME and ALGORITHM_VERSION should be set."""
    assert ALGORITHM_NAME == "research_template"
    assert ALGORITHM_VERSION == "0.1.0"
