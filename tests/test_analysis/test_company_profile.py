"""P4E 公司画像频谱与经理团队画像测试（需求书 §6.2.6 / §12.4.5）。

覆盖：alpha/beta 口径恢复、公司频谱样本量门禁（<3 observation）、
风格分布聚合、类型结构、经理任期加权 alpha、同类排名中位数、
风格稳定性降级、无现任降级、未知实体返回 None。
"""

from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy.orm import Session

from fund_research.analysis.company_profile import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    build_company_spectrum,
    build_manager_profile,
    compute_alpha_beta,
    list_company_spectra,
    list_manager_summaries,
)
from fund_research.db.models import (
    FundCompany,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    StockDaily,
    StockMain,
)
from fund_research.db.models_phase3 import FundFingerprint

START = date(2024, 1, 2)
DAYS = 300


# ============================================================
# 测试数据构造
# ============================================================


def _index_returns(days: int = DAYS, seed: int = 7) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.normal(0.0005, 0.01, days + 1)


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
    # 注意：date i 的净值必须已含当日收益（pct_change 口径与指数 daily_return 对齐）
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


def _add_company(db: Session, company_id: str, name: str) -> int:
    company = FundCompany(company_id=company_id, name=name, short_name=name)
    db.add(company)
    db.flush()
    return company.id


def _add_fund(
    db: Session,
    code: str,
    company_pk: int,
    *,
    category: str = "混合型-偏股混合",
    sub_category: str = "偏股混合",
) -> None:
    db.add(
        FundMain(
            fund_code=code,
            short_name=f"基金{code}",
            full_name=f"基金{code}全称",
            category=category,
            sub_category=sub_category,
            fund_company_id=company_pk,
        )
    )


def _seed_companies(db: Session) -> np.ndarray:
    """A 公司 3 只（beta 1.2/0.8/1.0），B 公司 1 只（样本不足场景）。"""
    index_ret = _index_returns()
    _add_index_series(db, "sh000300", index_ret)
    pk_a = _add_company(db, "comp_a", "公司A")
    pk_b = _add_company(db, "comp_b", "公司B")

    configs = [
        ("000001", pk_a, 1.2, 0.0005, 11),
        ("000002", pk_a, 0.8, 0.0, 13),
        ("000003", pk_a, 1.0, 0.0, 17),
        ("000009", pk_b, 1.0, 0.0, 19),
    ]
    for code, pk, beta, alpha_daily, seed in configs:
        _add_fund(db, code, pk)
        noise = np.random.RandomState(seed).normal(0.0, 0.001, len(index_ret))
        _add_nav_series(db, code, beta * index_ret + alpha_daily + noise)
        db.add(FundScale(fund_code=code, report_date=date(2025, 6, 30), total_nav=100.0))
        db.add(FundFee(fund_code=code, mgmt_fee_pct=1.2, custody_fee_pct=0.2))
    # A 公司两只基金带风格指纹
    for i, code in enumerate(("000001", "000002")):
        db.add(
            FundFingerprint(
                fund_code=code,
                calc_date=date(2025, 6, 30),
                algorithm_name="fingerprint",
                algorithm_version="0.3.0",
                template_name="active_equity",
                vector={"large_cap": 0.6 + 0.1 * i, "growth": 0.4},
                vector_metadata={},
            )
        )
    db.commit()
    return index_ret


def _seed_manager(
    db: Session,
    manager_id: str = "mgr_001",
    funds: tuple[str, ...] = ("000001", "000002"),
    tenure_days: tuple[int, ...] = (1000, 500),
) -> None:
    db.add(FundManager(manager_id=manager_id, name="测试经理", experience_years=8.5))
    for code, days in zip(funds, tenure_days, strict=True):
        db.add(
            FundManagerTenure(
                manager_id=manager_id,
                fund_code=code,
                start_date=date(2022, 1, 1),
                is_current=True,
                tenure_days=days,
            )
        )
    db.commit()


# ============================================================
# 口径与常量
# ============================================================


def test_algorithm_name_and_version() -> None:
    assert ALGORITHM_NAME == "company_profile"
    assert ALGORITHM_VERSION == "0.1.0"


def test_compute_alpha_beta_recovers_known_values() -> None:
    rng = np.random.RandomState(5)
    bench = rng.normal(0.0005, 0.01, 400)
    fund = 1.2 * bench + 0.0005 + rng.normal(0.0, 0.0005, 400)
    import pandas as pd

    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    result = compute_alpha_beta(
        pd.Series(fund, index=dates), pd.Series(bench, index=dates)
    )
    assert result is not None
    assert result["beta"] == pytest.approx(1.2, abs=0.05)
    assert result["alpha_annualized"] == pytest.approx(0.0005 * 252, rel=0.25)


def test_compute_alpha_beta_short_series_returns_none() -> None:
    import pandas as pd

    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    series = pd.Series(np.zeros(10), index=dates)
    assert compute_alpha_beta(series, series) is None


# ============================================================
# 公司频谱
# ============================================================


def test_company_spectrum_computed_with_three_funds(test_session: Session) -> None:
    _seed_companies(test_session)
    spectrum = build_company_spectrum(test_session, "comp_a")
    assert spectrum is not None
    assert spectrum.fund_count == 3
    assert spectrum.conclusion_status == "computed"
    # beta 分布覆盖 0.8~1.2
    betas = [f["beta"] for f in spectrum.funds if f["beta"] is not None]
    assert len(betas) == 3
    assert min(betas) == pytest.approx(0.8, abs=0.1)
    assert max(betas) == pytest.approx(1.2, abs=0.1)
    # 带 alpha 注入的基金 alpha 显著为正
    alphas = [f["alpha_annualized"] for f in spectrum.funds if f["alpha_annualized"] is not None]
    assert max(alphas) > 0.05


def test_company_spectrum_insufficient_sample_observation(test_session: Session) -> None:
    _seed_companies(test_session)
    spectrum = build_company_spectrum(test_session, "comp_b")
    assert spectrum is not None
    assert spectrum.fund_count == 1
    assert spectrum.conclusion_status == "observation"
    assert any("样本不足" in w for w in spectrum.warnings)


def test_company_spectrum_unknown_returns_none(test_session: Session) -> None:
    assert build_company_spectrum(test_session, "no_such_company") is None


def test_company_spectrum_style_distribution_and_structure(test_session: Session) -> None:
    _seed_companies(test_session)
    spectrum = build_company_spectrum(test_session, "comp_a")
    assert spectrum is not None
    style = spectrum.style_distribution
    assert style["available"] is True
    assert style["coverage_funds"] == 2
    # large_cap 均值 = (0.6 + 0.7) / 2
    assert style["dimensions"]["large_cap"] == pytest.approx(0.65, abs=1e-6)
    # 类型结构：3 只均偏股混合族
    assert spectrum.category_structure["mixed_family"]["count"] == 3
    # 规模光谱：3 × 100 亿
    assert spectrum.scale_spectrum["total"] == pytest.approx(300.0)


def test_list_company_spectra_overview(test_session: Session) -> None:
    _seed_companies(test_session)
    overview = list_company_spectra(test_session)
    assert {c["company_id"] for c in overview["companies"]} == {"comp_a", "comp_b"}
    by_id = {c["company_id"]: c for c in overview["companies"]}
    assert by_id["comp_a"]["fund_count"] == 3
    assert by_id["comp_a"]["insufficient_sample"] is False
    assert by_id["comp_b"]["insufficient_sample"] is True
    assert len(overview["funds"]) == 4
    assert all(f["alpha_annualized"] is not None for f in overview["funds"])


# ============================================================
# 经理团队画像
# ============================================================


def test_manager_profile_tenure_weighted_alpha(test_session: Session) -> None:
    _seed_companies(test_session)
    _seed_manager(test_session)
    profile = build_manager_profile(test_session, "mgr_001")
    assert profile is not None
    assert profile.conclusion_status == "computed"
    # 任期加权 = (alpha1×1000 + alpha2×500) / 1500
    alphas = {f["fund_code"]: f["alpha_annualized"] for f in profile.current_funds}
    expected = (alphas["000001"] * 1000 + alphas["000002"] * 500) / 1500
    assert profile.tenure_weighted_alpha == pytest.approx(expected, rel=1e-9)
    assert profile.managed_scale == pytest.approx(200.0)


def test_manager_profile_peer_rank_median(test_session: Session) -> None:
    _seed_companies(test_session)
    _seed_manager(test_session, funds=("000001",), tenure_days=(1000,))
    profile = build_manager_profile(test_session, "mgr_001")
    assert profile is not None
    ranks = profile.peer_rank["ranks"]
    assert len(ranks) == 1
    assert ranks[0]["sub_category"] == "偏股混合"
    # 同 sub_category 4 只基金（3A+1B）中按近一年收益排名
    assert ranks[0]["rank_text"].endswith("/4")
    assert profile.peer_rank["median_percentile"] is not None


def test_manager_profile_style_stability_unavailable_warns(test_session: Session) -> None:
    _seed_companies(test_session)
    _seed_manager(test_session)
    profile = build_manager_profile(test_session, "mgr_001")
    assert profile is not None
    assert profile.style_stability["evaluable_funds"] == 0
    assert profile.style_stability["stable"] is True
    assert any("风格稳定性不可评估" in w for w in profile.warnings)


def test_manager_profile_no_current_tenure_observation(test_session: Session) -> None:
    _seed_companies(test_session)
    test_session.add(FundManager(manager_id="mgr_002", name="离任经理"))
    test_session.add(
        FundManagerTenure(
            manager_id="mgr_002",
            fund_code="000001",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 1, 1),
            is_current=False,
            tenure_days=730,
        )
    )
    test_session.commit()
    profile = build_manager_profile(test_session, "mgr_002")
    assert profile is not None
    assert profile.conclusion_status == "observation"
    assert profile.current_funds == []
    assert len(profile.history_tenures) == 1
    assert any("无现任在管基金" in w for w in profile.warnings)


def test_manager_profile_unknown_returns_none(test_session: Session) -> None:
    assert build_manager_profile(test_session, "no_such_manager") is None


def test_list_manager_summaries_excludes_no_current(test_session: Session) -> None:
    _seed_companies(test_session)
    _seed_manager(test_session)
    test_session.add(FundManager(manager_id="mgr_003", name="无在管"))
    test_session.commit()
    summaries = list_manager_summaries(test_session)
    ids = {s["manager_id"] for s in summaries}
    assert ids == {"mgr_001"}
    assert summaries[0]["current_fund_count"] == 2
    assert summaries[0]["tenure_weighted_alpha"] is not None
