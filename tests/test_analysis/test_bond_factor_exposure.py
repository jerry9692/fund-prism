"""P4B 债基金因子暴露 · 粗粒度版测试（需求书 §6.2.7）。

覆盖：模板因子子集分流、暴露方向恢复、四类模板零跨模板硬算、
门禁拒绝、样本/因子序列不足降级、低 R² 降级、贡献拆解闭合、
雷达口径、同类对比（rank.py）、持久化幂等、指纹债维度组回填。
"""

import math
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.bond_factor_exposure import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    MIN_OBSERVATIONS,
    TEMPLATE_FACTORS,
    analyze_bond_factor_exposure,
    exposure_row_to_dict,
    get_latest_bond_factor_exposure,
    get_latest_bond_factor_exposures,
    load_bond_fund_candidates,
    persist_bond_factor_exposures,
    run_bond_factor_batch,
    template_for_fund,
)
from fund_research.db.models import FundMain, FundNAV
from fund_research.db.models_phase4 import BondFactorExposureResult, FactorReturn

START = date(2023, 9, 1)
DAYS = 200  # > MIN_OBSERVATIONS（120），可产生多个滚动窗口
POINTS = DAYS + 1  # 因子/收益序列长度（收益与因子同日对齐）


# ============================================================
# 测试数据构造
# ============================================================


def _factor_series(name: str, n: int = POINTS) -> list[float]:
    """确定性伪因子序列：周期取回归窗口 120 的约数，
    保证任意 120 长滚动窗口内因子间正交，暴露可精确恢复。"""
    spec = {
        "bond_coupon": (0.00004, 0.00001, 120.0, 0.0),
        "bond_rate": (0.0, 0.002, 8.0, 0.0),
        "bond_slope": (0.0, 0.001, 10.0, 1.0),
        "bond_credit_aaa": (0.0, 0.0008, 6.0, 2.0),
        "bond_convertible": (0.0, 0.01, 5.0, 3.0),
        "style_large_cap": (0.0, 0.012, 24.0, 4.0),
    }
    base, amp, period, phase = spec[name]
    return [
        base + amp * math.sin(2 * math.pi * i / period + phase) for i in range(n)
    ]


def _add_factors(db: Session, names: list[str], n: int = POINTS) -> None:
    for name in names:
        values = _factor_series(name, n)
        for i, value in enumerate(values):
            db.add(
                FactorReturn(
                    factor_name=name,
                    trade_date=START + timedelta(days=i),
                    factor_return=value,
                    source_name="unit_test",
                    source_level="B",
                )
            )


def _add_bond_fund(
    db: Session,
    code: str,
    *,
    category: str = "债券型-长期纯债",
    sub_category: str = "纯债",
) -> None:
    db.add(
        FundMain(
            fund_code=code,
            short_name=f"债基{code}",
            full_name=f"债基{code}全称",
            category=category,
            sub_category=sub_category,
        )
    )


def _add_nav_from_returns(db: Session, code: str, returns: list[float]) -> None:
    nav = 1.0
    db.add(
        FundNAV(fund_code=code, trade_date=START, unit_nav=nav, adjusted_nav=nav)
    )
    for i, ret in enumerate(returns):
        nav *= 1 + ret
        db.add(
            FundNAV(
                fund_code=code,
                trade_date=START + timedelta(days=i + 1),
                unit_nav=nav,
                adjusted_nav=nav,
            )
        )


def _seed_pure_bond_world(db: Session) -> None:
    """两只纯债（暴露方向已知）+ 全因子序列。收益与因子同日对齐。"""
    _add_factors(
        db,
        ["bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa",
         "bond_convertible", "style_large_cap"],
    )
    rate = _factor_series("bond_rate")
    credit = _factor_series("bond_credit_aaa")
    _add_bond_fund(db, "000032")  # 纯债：久期暴露显著
    _add_nav_from_returns(
        db, "000032", [2.0 * rate[i] + 0.5 * credit[i] for i in range(1, POINTS)]
    )
    _add_bond_fund(db, "040045", category="债券型-短期纯债", sub_category="短债")
    coupon = _factor_series("bond_coupon")
    _add_nav_from_returns(db, "040045", [3.0 * coupon[i] for i in range(1, POINTS)])
    db.commit()


# ============================================================
# 常量与候选/模板路由
# ============================================================


def test_algorithm_name_and_version() -> None:
    assert ALGORITHM_NAME == "bond_factor_exposure"
    assert ALGORITHM_VERSION == "0.1.0"


def test_template_factor_subsets() -> None:
    """四类模板使用不同因子子集（§6.2.7 验收：零跨模板硬算）。"""
    assert TEMPLATE_FACTORS["bond_short"] == ["bond_coupon", "bond_credit_aaa"]
    pure = TEMPLATE_FACTORS["bond_pure"]
    assert "bond_rate" in pure and "bond_credit_aaa" in pure
    assert "bond_convertible" not in pure and "style_large_cap" not in pure
    for template in ("bond_secondary", "bond_convertible"):
        assert "bond_convertible" in TEMPLATE_FACTORS[template]
        assert "style_large_cap" in TEMPLATE_FACTORS[template]


def test_template_routing_by_sub_category(test_session: Session) -> None:
    _add_bond_fund(test_session, "A", sub_category="纯债")
    _add_bond_fund(test_session, "B", category="债券型-短期纯债", sub_category="短债")
    _add_bond_fund(test_session, "C", category="债券型-普通债券", sub_category="二级债基")
    _add_bond_fund(test_session, "D", category="债券型-可转债", sub_category="可转债")
    _add_bond_fund(test_session, "E", category="债券型-普通债券", sub_category="一级债基")
    test_session.commit()

    funds = {f.fund_code: f for f in load_bond_fund_candidates(test_session)}
    assert template_for_fund(funds["A"]) == "bond_pure"
    assert template_for_fund(funds["B"]) == "bond_short"
    assert template_for_fund(funds["C"]) == "bond_secondary"
    assert template_for_fund(funds["D"]) == "bond_convertible"
    assert template_for_fund(funds["E"]) == "bond_secondary"


def test_candidates_only_bond_family(test_session: Session) -> None:
    _add_bond_fund(test_session, "000032")
    test_session.add(
        FundMain(
            fund_code="000001", short_name="混合基金", full_name="混合基金全称",
            category="混合型", sub_category="主动权益",
        )
    )
    test_session.add(
        FundMain(
            fund_code="510300", short_name="ETF", full_name="ETF全称",
            category="指数型-股票", sub_category="ETF", is_etf=True,
        )
    )
    test_session.commit()

    codes = {f.fund_code for f in load_bond_fund_candidates(test_session)}
    assert codes == {"000032"}


# ============================================================
# 暴露方向与模板分流
# ============================================================


def test_pure_bond_exposure_recovers_direction(test_session: Session) -> None:
    """纯债收益 = 2×bond_rate + 0.5×credit_aaa → 暴露方向与量级恢复。"""
    _seed_pure_bond_world(test_session)
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "000032"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.template_name == "bond_pure"
    assert record.conclusion_status == "computed"
    assert "bond_convertible" not in record.factor_names
    assert "style_large_cap" not in record.factor_names
    assert record.latest_exposures["bond_rate"] == pytest.approx(2.0, abs=0.15)
    assert record.latest_exposures["bond_credit_aaa"] == pytest.approx(0.5, abs=0.15)
    assert record.full_window_r_squared is not None
    assert record.full_window_r_squared > 0.9
    assert record.exposure_curves["bond_rate"]  # 滚动曲线非空
    assert record.radar["duration"] == pytest.approx(
        record.latest_exposures["bond_rate"] * 10, rel=0.2
    )


def test_short_bond_only_short_end_factors(test_session: Session) -> None:
    """短债模板：仅 coupon/credit_aaa，剔除 bond_rate 长端项。"""
    _seed_pure_bond_world(test_session)
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "040045"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.template_name == "bond_short"
    assert record.factor_names == ["bond_coupon", "bond_credit_aaa"]
    assert record.radar["duration"] is None  # 短债不输出久期代理
    assert record.conclusion_status == "computed"


def test_secondary_and_convertible_equity_beta_distinguishable(
    test_session: Session,
) -> None:
    """二级债基权益 beta 与转债基金可区分（§6.2.7 验收）。"""
    _add_factors(
        test_session,
        ["bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa",
         "bond_convertible", "style_large_cap"],
    )
    conv = _factor_series("bond_convertible")
    equity = _factor_series("style_large_cap")
    rate = _factor_series("bond_rate")

    _add_bond_fund(test_session, "000024", category="债券型-普通债券", sub_category="二级债基")
    _add_nav_from_returns(
        test_session, "000024",
        [0.1 * rate[i] + 0.5 * equity[i] for i in range(1, POINTS)],
    )
    _add_bond_fund(test_session, "040022", category="债券型-可转债", sub_category="可转债")
    _add_nav_from_returns(
        test_session, "040022",
        [0.9 * conv[i] + 0.4 * equity[i] for i in range(1, POINTS)],
    )
    test_session.commit()

    records = {
        r.fund_code: r for r in run_bond_factor_batch(test_session)
    }
    secondary = records["000024"]
    convertible = records["040022"]

    assert secondary.template_name == "bond_secondary"
    assert convertible.template_name == "bond_convertible"
    # 转债基金转债因子暴露显著 > 二级债基
    assert convertible.latest_exposures["bond_convertible"] > 0.7
    assert secondary.latest_exposures["bond_convertible"] < 0.2
    # 权益 beta 均可识别且方向为正
    assert secondary.latest_exposures["style_large_cap"] == pytest.approx(0.5, abs=0.15)
    assert convertible.latest_exposures["style_large_cap"] == pytest.approx(0.4, abs=0.15)
    assert convertible.radar["equity_beta"] is not None


def test_contributions_sum_to_fund_return(test_session: Session) -> None:
    """贡献拆解闭合：因子贡献 + 截距 + 残差 = 基金累计收益。"""
    _seed_pure_bond_world(test_session)
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "000032"))

    record = analyze_bond_factor_exposure(test_session, fund)

    # 已知构造：fund_ret_i = 2×rate_i + 0.5×credit_i，累计收益由日收益累乘推出
    rate = _factor_series("bond_rate")
    credit = _factor_series("bond_credit_aaa")
    fund_cum = 1.0
    for i in range(1, POINTS):
        fund_cum *= 1 + 2.0 * rate[i] + 0.5 * credit[i]
    expected_cum = fund_cum - 1.0

    total = sum(record.contributions.values())
    assert total == pytest.approx(expected_cum, abs=1e-5)
    # 拆解项齐备：各因子 + 截距 + 残差
    assert set(record.contributions) == {
        "bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa",
        "intercept", "residual",
    }


# ============================================================
# 门禁与降级
# ============================================================


def test_gate_rejects_non_bond_fund(test_session: Session) -> None:
    test_session.add(
        FundMain(
            fund_code="000001", short_name="混合基金", full_name="混合基金全称",
            category="混合型", sub_category="主动权益",
        )
    )
    test_session.commit()
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "000001"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.conclusion_status == "needs_review"
    assert any("不适用" in w for w in record.warnings)


def test_unknown_bond_sub_category_no_cross_template(test_session: Session) -> None:
    """债券族但无专用模板 → 不硬算，needs_review。"""
    _add_bond_fund(test_session, "X", category="债券型-其他", sub_category="其他")
    test_session.commit()
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "X"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.conclusion_status == "needs_review"
    assert any("无债基专用模板" in w for w in record.warnings)


def test_insufficient_observations_needs_review(test_session: Session) -> None:
    _add_factors(
        test_session,
        ["bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa"],
        n=MIN_OBSERVATIONS - 40,
    )
    _add_bond_fund(test_session, "000032")
    rate = _factor_series("bond_rate", MIN_OBSERVATIONS - 41)
    _add_nav_from_returns(test_session, "000032", rate)
    test_session.commit()
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "000032"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.conclusion_status == "needs_review"
    assert any("对齐样本" in w for w in record.warnings)


def test_convertible_factor_missing_for_convertible_fund(test_session: Session) -> None:
    """转债模板必备因子缺失 → needs_review + 覆盖度告警（不硬算）。"""
    _add_factors(
        test_session,
        ["bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa", "style_large_cap"],
    )
    _add_bond_fund(test_session, "040022", category="债券型-可转债", sub_category="可转债")
    rate = _factor_series("bond_rate")
    _add_nav_from_returns(test_session, "040022", rate[1:])
    test_session.commit()
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "040022"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.conclusion_status == "needs_review"
    assert record.factor_coverage.get("bond_convertible") == 0.0
    assert any("必备因子" in w for w in record.warnings)
    assert any("流动性因子" in w for w in record.warnings)  # 显式不启用登记


def test_low_r2_degrades_to_observation(test_session: Session) -> None:
    _add_factors(test_session, ["bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa"])
    _add_bond_fund(test_session, "000032")
    # 高频噪声（周期 3 天，与各因子正交）→ 回归解释力极低
    noise = [0.001 * math.sin(2 * math.pi * i / 3.0 + 5.0) for i in range(DAYS)]
    _add_nav_from_returns(test_session, "000032", noise)
    test_session.commit()
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "000032"))

    record = analyze_bond_factor_exposure(test_session, fund)

    assert record.conclusion_status == "observation"
    assert record.full_window_r_squared is not None
    assert record.full_window_r_squared < 0.3
    assert any("解释力弱" in w for w in record.warnings)


# ============================================================
# 同类对比、持久化与指纹闭环
# ============================================================


def test_peer_rank_within_sub_category(test_session: Session) -> None:
    _seed_pure_bond_world(test_session)
    # 第二只纯债：噪声收益 → R² 低，排名靠后
    _add_bond_fund(test_session, "270048")
    noise = [0.001 * math.sin(2 * math.pi * i / 3.0 + 5.0) for i in range(DAYS)]
    _add_nav_from_returns(test_session, "270048", noise)
    test_session.commit()

    records = {r.fund_code: r for r in run_bond_factor_batch(test_session)}

    good = records["000032"].peer_rank["r_squared"]
    bad = records["270048"].peer_rank["r_squared"]
    assert good["rank"] == 1 and good["total"] == 2
    assert bad["rank"] == 2
    assert good["rank_text"] == "1/2"


def test_persist_idempotent_and_latest(test_session: Session) -> None:
    _seed_pure_bond_world(test_session)
    records = run_bond_factor_batch(test_session)

    calc_date = date(2026, 8, 21)
    persist_bond_factor_exposures(test_session, records, calc_date=calc_date)
    test_session.commit()
    first_count = len(test_session.scalars(select(BondFactorExposureResult)).all())

    records2 = run_bond_factor_batch(test_session)
    persist_bond_factor_exposures(test_session, records2, calc_date=calc_date)
    test_session.commit()
    second_count = len(test_session.scalars(select(BondFactorExposureResult)).all())
    assert first_count == second_count == 2

    rows = get_latest_bond_factor_exposures(test_session)
    assert len(rows) == 2
    row = get_latest_bond_factor_exposure(test_session, "000032")
    assert row is not None
    data = exposure_row_to_dict(row)
    assert data["template_name"] == "bond_pure"
    assert data["exposure_curves"]
    assert data["factor_coverage"]


def test_fingerprint_bond_factor_dimension_backfill(test_session: Session) -> None:
    """指纹闭环：回归结果回填债基模板 bond_factor 维度组（estimated_* 隔离）。"""
    from fund_research.analysis.fingerprint import (
        ALGORITHM_VERSION as FINGERPRINT_VERSION,
    )
    from fund_research.analysis.fingerprint import generate_fingerprint
    from fund_research.db.models import FundManagerTenure, FundScale

    assert FINGERPRINT_VERSION == "0.3.0"

    _seed_pure_bond_world(test_session)
    records = run_bond_factor_batch(test_session)
    persist_bond_factor_exposures(test_session, records, calc_date=date(2026, 8, 21))
    # 补齐规模/团队维度，避免覆盖率过低提前返回
    test_session.add(
        FundScale(fund_code="000032", report_date=date(2026, 6, 30), total_nav=50.0)
    )
    test_session.add(
        FundManagerTenure(
            fund_code="000032", manager_id="M1", start_date=date(2020, 1, 1)
        )
    )
    test_session.commit()

    fp = generate_fingerprint(test_session, "000032")

    assert fp.template_name == "bond_pure"
    assert "bond_factor" in fp.vector
    bond_vec = fp.vector["bond_factor"]
    assert "estimated_duration" in bond_vec
    assert all(k.startswith("estimated_") for k in bond_vec)
    assert all(v == "estimated" for v in fp.vector_metadata["bond_factor"].values())
    assert fp.contains_estimated is True
    assert fp.conclusion_status == "estimated"


def test_rolling_last_window_aligns_to_data_end() -> None:
    """审计修复：末滚动窗口对齐数据末尾，latest_exposures 不滞后于 window_end。"""
    import numpy as np
    import pandas as pd

    from fund_research.analysis.bond_factor_exposure import compute_exposures

    rng = np.random.RandomState(3)
    n = 253  # (253-120) % 20 = 13：未修复时末窗口滞后 13 个交易日
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    factor = pd.DataFrame({"f1": rng.normal(0.0, 0.002, n)}, index=dates)
    fund = pd.Series(
        0.5 * factor["f1"].to_numpy() + rng.normal(0.0, 0.001, n), index=dates
    )
    result = compute_exposures(fund, factor, ["f1"], window_days=120, step_days=20)
    assert result["rolling_dates"][-1] == dates[-1]
