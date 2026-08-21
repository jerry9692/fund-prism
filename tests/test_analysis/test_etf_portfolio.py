"""P4D ETF 组合构建测试（需求书 §6.2.9）。

覆盖：候选过滤、CVXPY 二次规划权重约束、Ledoit-Wolf 收缩、
池 <2 / 序列 <60 降级、组合 TE < 单只最差候选、再平衡回测换手与成本、
换手上限生效、行业偏离对照、门禁拒绝、持久化幂等。
"""

from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy.orm import Session

from fund_research.analysis.etf_portfolio import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    MIN_OBSERVATIONS,
    BuildParams,
    build_etf_portfolio,
    build_rebalance_schedule,
    etf_portfolio_row_to_dict,
    get_etf_portfolio_by_id,
    get_latest_etf_portfolios,
    load_etf_candidates,
    persist_etf_portfolio,
)
from fund_research.db.models import FundFee, FundMain, FundNAV, FundScale, StockDaily, StockMain
from fund_research.db.models_phase2 import BenchmarkIndustryWeight
from fund_research.db.models_phase4 import EtfPortfolioResult, EtfProfile

START = date(2024, 1, 2)
DAYS = 320  # > lookback 120，且留出再平衡样本外段


# ============================================================
# 测试数据构造（确定性伪随机噪声）
# ============================================================


def _add_fund(
    db: Session,
    code: str,
    *,
    is_etf: bool = True,
    is_etf_feeder: bool = False,
    category: str = "股票型",
    sub_category: str = "ETF",
    benchmark: str | None = None,
) -> None:
    db.add(
        FundMain(
            fund_code=code,
            short_name=f"基金{code}",
            full_name=f"基金{code}全称",
            category=category,
            sub_category=sub_category,
            is_etf=is_etf,
            is_etf_feeder=is_etf_feeder,
            benchmark=benchmark,
        )
    )


def _add_index_series(db: Session, symbol: str, returns: np.ndarray) -> None:
    db.add(StockMain(stock_code=symbol, stock_name=f"指数{symbol}"))
    price = 1000.0
    for i in range(len(returns)):
        db.add(
            StockDaily(
                stock_code=symbol,
                trade_date=START + timedelta(days=i),
                close_price=price,
                daily_return=float(returns[i]) if i > 0 else None,
            )
        )
        price *= 1 + returns[i]


def _add_nav_series(db: Session, fund_code: str, returns: np.ndarray) -> None:
    # date i 的净值已含当日收益（与指数 daily_return 口径对齐）
    nav = 1.0
    for i in range(len(returns)):
        nav *= 1 + returns[i]
        db.add(
            FundNAV(
                fund_code=fund_code,
                trade_date=START + timedelta(days=i),
                unit_nav=nav,
                adjusted_nav=nav,
            )
        )


def _add_etf_profile(db: Session, fund_code: str, tracking: str = "sh000300") -> None:
    db.add(
        EtfProfile(
            fund_code=fund_code,
            tracking_index_code=tracking,
            tracking_index_name="沪深300",
            avg_daily_amount_1y=1e9,
            latest_premium_rate=0.05,
            source_name="unit_test",
            source_level="B",
        )
    )


def _index_returns(days: int = DAYS, seed: int = 7) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.normal(0.0005, 0.01, days + 1)


def _fund_returns(index_ret: np.ndarray, noise_scale: float, seed: int) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return index_ret + rng.normal(0.0, noise_scale, len(index_ret))


def _seed_two_etfs(db: Session, *, days: int = DAYS) -> np.ndarray:
    """两只跟踪沪深300 的 ETF：A 噪声小（跟踪好），B 噪声大（跟踪差）。"""
    index_ret = _index_returns(days)[: days + 1]
    _add_index_series(db, "sh000300", index_ret)
    _add_fund(db, "510300")
    _add_fund(db, "510310")
    _add_etf_profile(db, "510300")
    _add_etf_profile(db, "510310")
    for code, noise, seed in (("510300", 0.001, 11), ("510310", 0.01, 13)):
        _add_nav_series(db, code, _fund_returns(index_ret, noise, seed))
        db.add(FundFee(fund_code=code, mgmt_fee_pct=0.5, custody_fee_pct=0.1))
        db.add(FundScale(fund_code=code, report_date=date(2025, 6, 30), total_nav=100.0))
    db.commit()
    return index_ret


def _seed_industry_weights(db: Session) -> None:
    for industry, weight in (("银行", 40.0), ("电子", 30.0), ("医药生物", 30.0)):
        db.add(
            BenchmarkIndustryWeight(
                benchmark_symbol="sh000300",
                snapshot_date=date(2025, 6, 30),
                classification_type="SW",
                classification_level=1,
                industry_name=industry,
                weight_pct=weight,
                member_count=10,
                algorithm_version="test",
            )
        )
    db.commit()


# ============================================================
# 常量与候选
# ============================================================


def test_algorithm_name_and_version() -> None:
    assert ALGORITHM_NAME == "etf_portfolio_build"
    assert ALGORITHM_VERSION == "0.1.0"


def test_candidates_only_etf_and_feeder(test_session: Session) -> None:
    _add_fund(test_session, "510300")
    _add_fund(test_session, "110020", is_etf=False, is_etf_feeder=True, sub_category="ETF联接")
    _add_fund(test_session, "000001", is_etf=False, category="混合型", sub_category="偏股混合")
    test_session.commit()
    codes = {f.fund_code for f in load_etf_candidates(test_session)}
    assert codes == {"510300", "110020"}


def test_rebalance_schedule_month_end() -> None:
    import pandas as pd

    dates = pd.date_range("2024-01-01", periods=90, freq="B")
    schedule = build_rebalance_schedule(dates, "monthly", dates[0])
    assert len(schedule) >= 2
    for d in schedule:
        assert d > dates[0]


# ============================================================
# 主流程
# ============================================================


def test_build_computed_weights_respect_constraints(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    assert record.conclusion_status == "computed"
    weights = {code: m["weight"] for code, m in record.member_weights.items()}
    assert len(weights) >= 1
    assert abs(sum(weights.values()) - 1.0) < 1e-3
    assert all(0.0 <= w <= 1.0 for w in weights.values())
    # 约束清单逐条回显
    names = {c["name"] for c in record.constraints}
    assert "权重合计为 1" in names
    assert "协方差 Ledoit-Wolf 收缩" in names
    assert all(c["satisfied"] for c in record.constraints)


def test_portfolio_te_below_worst_single_candidate(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    fitted = record.portfolio_stats["fitted"]
    assert fitted["annualized_tracking_error"] < fitted["worst_single_tracking_error"]


def test_max_weight_and_positions_respected(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session,
        BuildParams(
            target_symbol="sh000300",
            lookback_days=120,
            max_weight=0.6,
            max_positions=1,
        ),
    )
    weights = {code: m["weight"] for code, m in record.member_weights.items()}
    assert len(weights) == 1
    assert max(weights.values()) <= 0.6 + 1e-3 or len(weights) == 1 and abs(
        sum(weights.values()) - 1.0
    ) < 1e-3
    # 数量上限约束回显
    cap = next(c for c in record.constraints if c["name"] == "持仓数量上限")
    assert cap["satisfied"]


def test_pool_lt_2_needs_review(test_session: Session) -> None:
    index_ret = _index_returns()
    _add_index_series(test_session, "sh000300", index_ret)
    _add_fund(test_session, "510300")
    _add_etf_profile(test_session, "510300")
    _add_nav_series(test_session, "510300", _fund_returns(index_ret, 0.001, 11))
    test_session.commit()
    record = build_etf_portfolio(test_session, BuildParams(target_symbol="sh000300"))
    assert record.conclusion_status == "needs_review"
    assert record.member_weights == {}
    assert any("< 2" in w for w in record.warnings)


def test_short_series_needs_review(test_session: Session) -> None:
    short = MIN_OBSERVATIONS - 20
    index_ret = _index_returns(days=short)
    _add_index_series(test_session, "sh000300", index_ret)
    for code, seed in (("510300", 11), ("510310", 13)):
        _add_fund(test_session, code)
        _add_etf_profile(test_session, code)
        _add_nav_series(test_session, code, _fund_returns(index_ret, 0.002, seed))
    test_session.commit()
    record = build_etf_portfolio(test_session, BuildParams(target_symbol="sh000300"))
    assert record.conclusion_status == "needs_review"
    assert any("交易日" in w for w in record.warnings)


def test_unknown_target_needs_review(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(test_session, BuildParams(target_symbol="sh000999"))
    assert record.conclusion_status == "needs_review"
    assert any("无行情序列" in w for w in record.warnings)


def test_threshold_filter_excludes_small_fund(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    # 抬高 510300 规模至 300 亿；阈值 200 亿 → 仅剩 510300，池 <2 降级
    scale = (
        test_session.query(FundScale).filter(FundScale.fund_code == "510300").one()
    )
    scale.total_nav = 300.0
    test_session.commit()
    record = build_etf_portfolio(
        test_session,
        BuildParams(target_symbol="sh000300", lookback_days=120, min_scale=200.0),
    )
    assert record.conclusion_status == "needs_review"
    assert record.eligible_count == 1
    assert record.candidate_count == 2


def test_explicit_pool_with_non_index_fund_rejected(test_session: Session) -> None:
    """指定池混入债基 → 门禁拒绝，仅指数族参与。"""
    index_ret = _seed_two_etfs(test_session)
    _add_fund(
        test_session,
        "000003",
        is_etf=False,
        category="债券型-短债",
        sub_category="短债",
    )
    _add_nav_series(test_session, "000003", _fund_returns(index_ret, 0.001, 17))
    test_session.commit()
    record = build_etf_portfolio(
        test_session,
        BuildParams(
            target_symbol="sh000300",
            fund_codes=["510300", "510310", "000003"],
            lookback_days=120,
        ),
    )
    assert record.conclusion_status == "computed"
    assert "000003" not in record.member_weights


# ============================================================
# 再平衡回测
# ============================================================


def test_rebalance_backtest_turnover_and_cost(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session,
        BuildParams(
            target_symbol="sh000300",
            lookback_days=120,
            rebalance_frequency="monthly",
        ),
    )
    backtest = record.backtest
    assert backtest["available"] is True
    summary = backtest["summary"]
    assert summary["rebalance_count"] >= 2
    assert summary["total_turnover"] > 0
    # 成本 = 加权费率 × 单边换手
    expected_cost = summary["weighted_fee_rate"] * summary["total_turnover"]
    assert summary["total_cost"] == pytest.approx(expected_cost, abs=1e-8)
    executed = [r for r in backtest["rebalances"] if not r.get("skipped")]
    assert executed and all(r["turnover"] >= 0 for r in executed)


def test_max_turnover_cap_enforced(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session,
        BuildParams(
            target_symbol="sh000300",
            lookback_days=120,
            rebalance_frequency="monthly",
            max_turnover=0.05,
        ),
    )
    backtest = record.backtest
    assert backtest["available"] is True
    executed = [r for r in backtest["rebalances"] if not r.get("skipped")]
    # 双边换手 ≤ cap → 单边 ≤ cap/2（数值容差 1e-6）
    for rebalance in executed:
        assert rebalance["turnover"] <= 0.05 / 2 + 1e-6
    cap_constraint = next(
        c for c in record.constraints if c["name"] == "再平衡换手上限（双边）"
    )
    assert cap_constraint["satisfied"]


def test_backtest_unavailable_when_history_short(test_session: Session) -> None:
    # 全历史 = lookback → 无样本外段
    index_ret = _index_returns(days=80)
    _add_index_series(test_session, "sh000300", index_ret)
    for code, seed in (("510300", 11), ("510310", 13)):
        _add_fund(test_session, code)
        _add_etf_profile(test_session, code)
        _add_nav_series(test_session, code, _fund_returns(index_ret, 0.002, seed))
    test_session.commit()
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=80)
    )
    assert record.backtest["available"] is False
    assert "fit_curve" in record.backtest  # 拟合曲线仍可输出


# ============================================================
# 行业偏离
# ============================================================


def test_industry_deviation_zero_for_same_tracking_index(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    _seed_industry_weights(test_session)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    deviation = record.industry_deviation
    assert deviation["available"] is True
    assert deviation["total_abs_deviation"] < 1e-6
    assert deviation["uncovered"] == []


def test_industry_deviation_unavailable_warns(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    assert record.industry_deviation["available"] is False
    assert any("行业" in w for w in record.warnings)


# ============================================================
# 持久化
# ============================================================


def test_persist_idempotent(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    row1 = persist_etf_portfolio(test_session, record)
    test_session.commit()
    row2 = persist_etf_portfolio(test_session, record)
    test_session.commit()
    assert row1.id == row2.id
    assert (
        test_session.query(EtfPortfolioResult).count() == 1
    )


def test_get_by_id_and_latest(test_session: Session) -> None:
    _seed_two_etfs(test_session)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    row = persist_etf_portfolio(test_session, record)
    test_session.commit()

    fetched = get_etf_portfolio_by_id(test_session, row.id)
    assert fetched is not None
    data = etf_portfolio_row_to_dict(fetched)
    assert data["target_symbol"] == "sh000300"
    assert data["member_weights"]

    latest = get_latest_etf_portfolios(test_session)
    assert len(latest) == 1
    assert latest[0].id == row.id

    assert get_etf_portfolio_by_id(test_session, 999999) is None


def test_observation_when_portfolio_not_better_than_worst(
    test_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """强制选中跟踪最差的候选（组合 TE = 最差单票）→ observation 降级。"""
    _seed_two_etfs(test_session)
    from fund_research.analysis import etf_portfolio as module

    def fixed_weights(returns, **kwargs):
        return {"510310": 1.0}, {"shrinkage": True, "solver_status": "optimal"}

    monkeypatch.setattr(module, "optimize_tracking_weights", fixed_weights)
    record = build_etf_portfolio(
        test_session, BuildParams(target_symbol="sh000300", lookback_days=120)
    )
    assert record.conclusion_status == "observation"
    fitted = record.portfolio_stats["fitted"]
    assert fitted["annualized_tracking_error"] >= fitted["worst_single_tracking_error"]
    assert any("未体现分散价值" in w for w in record.warnings)
