"""P4C 基金组合穿透分析测试（需求书 §6.3.9 / §12.4.2）。

覆盖：权重归一（weighted/equal 双模式）、组合指标与手工加权口径一致、
相关性矩阵对称性、风格/行业穿透加权合成、披露 vs estimated 重叠隔离、
集中度风险、降级路径、持久化幂等。
"""

import math
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.portfolio import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    MIN_PORTFOLIO_OBSERVATIONS,
    compute_portfolio_analysis,
    compute_portfolio_returns,
    get_latest_portfolio_analysis,
    normalize_member_weights,
    persist_portfolio_analysis,
    portfolio_row_to_dict,
)
from fund_research.db.models import (
    FundCompany,
    FundDisclosedHoldings,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    StyleExposureResult,
)
from fund_research.db.models_phase2 import (
    FundPool,
    FundPoolMember,
    SimulatedHoldingResult,
    StockIndustryMembership,
)
from fund_research.db.models_phase4 import UserPortfolio

START = date(2025, 1, 2)
DAYS = 90  # > MIN_PORTFOLIO_OBSERVATIONS


# ============================================================
# 测试数据构造
# ============================================================


def _add_fund(
    db: Session,
    code: str,
    *,
    category: str = "混合型",
    sub_category: str = "主动权益",
    company_id: int | None = None,
) -> None:
    db.add(
        FundMain(
            fund_code=code,
            short_name=f"基金{code}",
            full_name=f"基金{code}全称",
            category=category,
            sub_category=sub_category,
            fund_company_id=company_id,
        )
    )


def _add_nav_series(db: Session, fund_code: str, returns: list[float]) -> None:
    nav = 1.0
    db.add(
        FundNAV(fund_code=fund_code, trade_date=START, unit_nav=nav, adjusted_nav=nav)
    )
    for i, ret in enumerate(returns):
        nav *= 1 + ret
        db.add(
            FundNAV(
                fund_code=fund_code,
                trade_date=START + timedelta(days=i + 1),
                unit_nav=nav,
                adjusted_nav=nav,
            )
        )


def _make_returns(seed: float, n: int = DAYS) -> list[float]:
    return [0.001 * math.sin(2 * math.pi * i / 7.0 + seed) for i in range(n)]


def _add_pool(
    db: Session,
    members: list[tuple[str, float | None]],
    *,
    name: str = "测试组合",
) -> int:
    db.add(FundPool(name=name))
    db.flush()
    pool_id = db.scalars(select(FundPool).order_by(FundPool.id.desc()).limit(1)).first().id
    for fund_code, weight in members:
        db.add(FundPoolMember(pool_id=pool_id, fund_code=fund_code, weight_pct=weight))
    return pool_id


def _seed_two_fund_pool(db: Session, weighted: bool = True) -> int:
    """两只混合基金 + 90 日净值；可选 60/40 权重。"""
    _add_fund(db, "000001")
    _add_fund(db, "020005")
    _add_nav_series(db, "000001", _make_returns(0.0))
    _add_nav_series(db, "020005", _make_returns(1.5))
    weights = (60.0, 40.0) if weighted else (None, None)
    pool_id = _add_pool(
        db, [("000001", weights[0]), ("020005", weights[1])]
    )
    db.commit()
    return pool_id


# ============================================================
# 常量与权重归一
# ============================================================


def test_algorithm_name_and_version() -> None:
    assert ALGORITHM_NAME == "portfolio_analysis"
    assert ALGORITHM_VERSION == "0.1.0"


def test_normalize_weights_equal_mode_when_no_weights(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session, weighted=False)

    result = compute_portfolio_analysis(test_session, pool_id)

    assert result.weights_mode == "equal"
    assert result.member_weights["000001"] == pytest.approx(0.5)
    assert any("等权" in w for w in result.warnings)


def test_normalize_weights_weighted_mode(test_session: Session) -> None:
    members = [
        FundPoolMember(pool_id=1, fund_code="A", weight_pct=60.0),
        FundPoolMember(pool_id=1, fund_code="B", weight_pct=20.0),
        FundPoolMember(pool_id=1, fund_code="C", weight_pct=None),
    ]
    weights, mode = normalize_member_weights(members)

    assert mode == "weighted"
    assert weights["A"] == pytest.approx(0.75)
    assert weights["B"] == pytest.approx(0.25)
    assert weights["C"] == pytest.approx(0.0)


# ============================================================
# 组合层指标与相关性
# ============================================================


def test_portfolio_returns_match_manual_weighting(test_session: Session) -> None:
    """组合收益 = 权重加权成员日收益（验收：与手工加权口径一致）。"""
    _seed_two_fund_pool(test_session, weighted=True)

    r1 = _make_returns(0.0)
    r2 = _make_returns(1.5)
    returns_by_fund = {"000001": None, "020005": None}  # placeholder
    # 直接用模块内加载 + 加权
    from fund_research.analysis.portfolio import _fund_daily_returns

    returns_by_fund = {
        "000001": _fund_daily_returns(test_session, "000001"),
        "020005": _fund_daily_returns(test_session, "020005"),
    }
    portfolio, frame = compute_portfolio_returns(
        returns_by_fund, {"000001": 0.6, "020005": 0.4}
    )

    expected = [0.6 * a + 0.4 * b for a, b in zip(r1, r2, strict=True)]
    assert len(portfolio) == DAYS
    for value, exp in zip(portfolio.values, expected, strict=True):
        assert value == pytest.approx(exp, abs=1e-12)


def test_analysis_metrics_and_correlation(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)

    result = compute_portfolio_analysis(test_session, pool_id)

    assert result.conclusion_status == "computed"
    metrics = result.portfolio_metrics
    assert metrics["annualized_return"] is not None
    assert metrics["annualized_volatility"] is not None
    assert metrics["max_drawdown"] is not None
    assert "recovery_days" in metrics

    corr = result.correlation_matrix
    assert set(corr) == {"000001", "020005"}
    # 对称且对角为 1
    assert corr["000001"]["000001"] == pytest.approx(1.0)
    assert corr["020005"]["020005"] == pytest.approx(1.0)
    assert corr["000001"]["020005"] == pytest.approx(corr["020005"]["000001"])


# ============================================================
# 穿透暴露：风格与行业
# ============================================================


def test_style_penetration_weighted_composite(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)
    test_session.add(
        StyleExposureResult(
            fund_code="000001",
            calc_date=date(2025, 3, 31),
            algorithm_name="style_exposure",
            algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={"large_cap": 0.8, "growth": 0.4},
            r_squared=0.9,
        )
    )
    test_session.add(
        StyleExposureResult(
            fund_code="020005",
            calc_date=date(2025, 3, 31),
            algorithm_name="style_exposure",
            algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={"large_cap": 0.2, "growth": 0.1},
            r_squared=0.85,
        )
    )
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    style = result.style_penetration
    assert style["available"] is True
    # 0.6×0.8 + 0.4×0.2 = 0.56
    assert style["composite"]["large_cap"] == pytest.approx(0.56, abs=1e-4)
    assert style["composite"]["growth"] == pytest.approx(0.28, abs=1e-4)


def test_style_penetration_missing_fund_renormalized(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)
    test_session.add(
        StyleExposureResult(
            fund_code="000001",
            calc_date=date(2025, 3, 31),
            algorithm_name="style_exposure",
            algorithm_version="0.1.0",
            exposure_type="style",
            exposure_values={"large_cap": 0.8},
            r_squared=0.9,
        )
    )
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    style = result.style_penetration
    # 仅 000001 可得 → 权重再归一后仍为 0.8
    assert style["composite"]["large_cap"] == pytest.approx(0.8, abs=1e-4)
    assert any("无风格暴露" in w for w in result.warnings)


def test_industry_penetration_sw2021_weighted(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)
    # 行业归属：SW2021 一级
    test_session.add(
        StockIndustryMembership(
            stock_code="600000",
            classification_type="SW",
            classification_version="SW2021",
            level=1,
            industry_name="银行",
            effective_date=date(2024, 12, 31),
            source_name="unit_test",
            source_level="B",
        )
    )
    test_session.add(
        StockIndustryMembership(
            stock_code="600519",
            classification_type="SW",
            classification_version="SW2021",
            level=1,
            industry_name="食品饮料",
            effective_date=date(2024, 12, 31),
            source_name="unit_test",
            source_level="B",
        )
    )
    report_date = date(2025, 3, 31)
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=report_date,
            asset_type="股票",
            security_code="600000",
            security_name="浦发银行",
            weight_pct=10.0,
        )
    )
    test_session.add(
        FundDisclosedHoldings(
            fund_code="020005",
            report_date=report_date,
            asset_type="股票",
            security_code="600519",
            security_name="贵州茅台",
            weight_pct=5.0,
        )
    )
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    industry = result.industry_penetration
    assert industry["available"] is True
    weights = {item["industry"]: item["weight"] for item in industry["industries"]}
    # 银行：0.6×10%=6%；食品饮料：0.4×5%=2%
    assert weights["银行"] == pytest.approx(0.06, abs=1e-6)
    assert weights["食品饮料"] == pytest.approx(0.02, abs=1e-6)
    assert industry["industry_hhi"] is not None


# ============================================================
# 重仓重叠（披露 vs estimated 隔离）与集中度
# ============================================================


def test_overlap_disclosed_and_estimated_isolated(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)
    report_date = date(2025, 3, 31)
    # 披露持仓：两基金共享 600000
    for code, weight in (("000001", 8.0), ("020005", 6.0)):
        test_session.add(
            FundDisclosedHoldings(
                fund_code=code,
                report_date=report_date,
                asset_type="股票",
                security_code="600000",
                security_name="浦发银行",
                weight_pct=weight,
            )
        )
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=report_date,
            asset_type="股票",
            security_code="000858",
            security_name="五粮液",
            weight_pct=4.0,
        )
    )
    # 模拟持仓（estimated 口径）：共享 601318
    for code in ("000001", "020005"):
        test_session.add(
            SimulatedHoldingResult(
                fund_code=code,
                calc_date=date(2025, 4, 1),
                algorithm_name="simulated_holding",
                algorithm_version="0.1.0",
                holdings_detail=[
                    {"stock_code": "601318", "stock_name": "中国平安", "estimated_weight": 0.05}
                ],
                conclusion_status="estimated",
            )
        )
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    disclosed = result.holding_overlap["disclosed"]
    assert disclosed["shared_stock_count"] == 1
    top = disclosed["top_overlaps"][0]
    assert top["stock_code"] == "600000"
    # 组合层合计权重 = 0.6×8% + 0.4×6% = 7.2%
    assert top["combined_weight"] == pytest.approx(0.072, abs=1e-6)

    estimated = result.holding_overlap["estimated_overlap"]
    assert all(key.startswith("estimated_") for key in estimated)
    assert estimated["estimated_shared_stock_count"] == 1


def test_overlap_estimated_missing_warns(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)

    result = compute_portfolio_analysis(test_session, pool_id)

    assert any("模拟持仓" in w for w in result.warnings)


def test_concentration_manager_and_company(test_session: Session) -> None:
    _add_fund(test_session, "000001", company_id=None)
    _add_fund(test_session, "020005", company_id=None)
    company = FundCompany(company_id="C1", name="测试基金", short_name="测试基金")
    test_session.add(company)
    test_session.flush()
    for code in ("000001", "020005"):
        fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == code))
        fund.fund_company_id = company.id
    test_session.add(FundManager(manager_id="M1", name="张三"))
    test_session.add(
        FundManagerTenure(
            fund_code="000001", manager_id="M1", start_date=date(2020, 1, 1)
        )
    )
    test_session.add(
        FundManagerTenure(
            fund_code="020005", manager_id="M1", start_date=date(2021, 6, 1)
        )
    )
    _add_nav_series(test_session, "000001", _make_returns(0.0))
    _add_nav_series(test_session, "020005", _make_returns(1.5))
    pool_id = _add_pool(test_session, [("000001", 60.0), ("020005", 40.0)])
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    concentration = result.concentration
    # 同一现任经理管理两只成员 → 权重合计 1.0
    assert concentration["max_manager_weight"] == pytest.approx(1.0)
    manager_row = concentration["manager_concentration"][0]
    assert manager_row["manager_name"] == "张三"
    assert sorted(manager_row["fund_codes"]) == ["000001", "020005"]
    # 同一公司 → 权重合计 1.0
    assert concentration["max_company_weight"] == pytest.approx(1.0)
    assert concentration["company_concentration"][0]["company"] == "测试基金"


# ============================================================
# 降级与持久化
# ============================================================


def test_unknown_pool_needs_review(test_session: Session) -> None:
    result = compute_portfolio_analysis(test_session, 999)

    assert result.conclusion_status == "needs_review"
    assert any("不存在" in w for w in result.warnings)


def test_single_member_pool_needs_review(test_session: Session) -> None:
    _add_fund(test_session, "000001")
    _add_nav_series(test_session, "000001", _make_returns(0.0))
    pool_id = _add_pool(test_session, [("000001", None)])
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    assert result.conclusion_status == "needs_review"
    assert any("不足 2 只" in w for w in result.warnings)


def test_short_common_window_needs_review(test_session: Session) -> None:
    _add_fund(test_session, "000001")
    _add_fund(test_session, "020005")
    _add_nav_series(test_session, "000001", _make_returns(0.0))
    # 第二只基金净值窗口与第一只几乎不重叠
    far_start = START + timedelta(days=400)
    nav = 1.0
    test_session.add(
        FundNAV(fund_code="020005", trade_date=far_start, unit_nav=nav, adjusted_nav=nav)
    )
    for i in range(MIN_PORTFOLIO_OBSERVATIONS + 5):
        nav *= 1.001
        test_session.add(
            FundNAV(
                fund_code="020005",
                trade_date=far_start + timedelta(days=i + 1),
                unit_nav=nav,
                adjusted_nav=nav,
            )
        )
    pool_id = _add_pool(test_session, [("000001", 50.0), ("020005", 50.0)])
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)

    assert result.conclusion_status == "needs_review"
    assert any("重叠不足" in w for w in result.warnings)


def test_persist_idempotent_and_latest(test_session: Session) -> None:
    pool_id = _seed_two_fund_pool(test_session)
    result = compute_portfolio_analysis(test_session, pool_id)

    calc_date = date(2026, 8, 20)
    persist_portfolio_analysis(test_session, result, calc_date=calc_date)
    test_session.commit()
    first = len(test_session.scalars(select(UserPortfolio)).all())

    result2 = compute_portfolio_analysis(test_session, pool_id)
    persist_portfolio_analysis(test_session, result2, calc_date=calc_date)
    test_session.commit()
    second = len(test_session.scalars(select(UserPortfolio)).all())
    assert first == second == 1

    row = get_latest_portfolio_analysis(test_session, pool_id)
    assert row is not None
    data = portfolio_row_to_dict(row, pool_name="测试组合")
    assert data["pool_name"] == "测试组合"
    assert data["weights_mode"] == "weighted"
    assert data["portfolio_metrics"]
    assert data["correlation_matrix"]

# ============================================================
# 审计修复回归（2026-08-21 CodeReview）
# ============================================================


def test_zero_weight_member_does_not_truncate_window() -> None:
    """零权重成员不参与共同窗口交集，不以其短历史截断组合收益窗口。"""
    idx = pd.date_range("2025-01-01", periods=100, freq="B")
    returns = {
        "A": pd.Series(0.001, index=idx),
        "B": pd.Series(0.002, index=idx),
        "Z": pd.Series(0.003, index=idx[:5]),  # 仅 5 天但权重为 0
    }
    portfolio, frame = compute_portfolio_returns(
        returns, {"A": 0.6, "B": 0.4, "Z": 0.0}
    )
    assert len(portfolio) == 100
    assert set(frame.columns) == {"A", "B"}


def test_zero_weight_member_analysis_not_degraded(test_session: Session) -> None:
    """零权重成员净值短不应把整个组合分析降级为 needs_review。"""
    _add_fund(test_session, "000001")
    _add_fund(test_session, "020005")
    _add_fund(test_session, "040022")
    _add_nav_series(test_session, "000001", _make_returns(0.0))
    _add_nav_series(test_session, "020005", _make_returns(1.5))
    _add_nav_series(test_session, "040022", _make_returns(3.0, n=5))  # 短历史
    pool_id = _add_pool(
        test_session,
        [("000001", 50.0), ("020005", 50.0), ("040022", 0.0)],
    )
    test_session.commit()

    result = compute_portfolio_analysis(test_session, pool_id)
    assert result.conclusion_status == "computed"
    assert any("零权重" in w for w in result.warnings)


def test_overlap_pairwise_matrix_symmetric() -> None:
    """成对重叠矩阵严格对称（修复外层循环覆盖下三角）。"""
    from fund_research.analysis.portfolio import _overlap_from_maps

    holdings = {
        "F1": {"600000": 5.0, "600001": 4.0, "600002": 3.0},
        "F2": {"600000": 6.0, "600003": 2.0},
        "F3": {"600000": 7.0, "600001": 1.0},
    }
    overlap = _overlap_from_maps(
        holdings, {"F1": 0.4, "F2": 0.3, "F3": 0.3}, {}
    )
    pairwise = overlap["pairwise_shared_counts"]
    for a, row in pairwise.items():
        for b, count in row.items():
            assert pairwise[b][a] == count
    # 下三角不丢失：F3→F1 与 F1→F3 均可读取
    assert pairwise["F3"]["F1"] == pairwise["F1"]["F3"] == 2
    assert pairwise["F2"]["F1"] == pairwise["F1"]["F2"] == 1
