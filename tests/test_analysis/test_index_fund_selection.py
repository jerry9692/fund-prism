"""P4A 指数基金分析与优选测试（需求书 §6.2.8）。

覆盖：候选筛选、同指数分组、五维评分方向、缺失维度降权、
指增/被动 alpha 区分、门禁拒绝、跟踪样本不足降级、持久化幂等。
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.index_fund_selection import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    MIN_TRACKING_OBSERVATIONS,
    composite_from_scores,
    get_latest_selection_results,
    load_index_fund_candidates,
    persist_selection_results,
    run_selection,
    score_dimensions,
)
from fund_research.db.models import (
    EtfProfile,
    FundFee,
    FundMain,
    FundNAV,
    FundScale,
    StockDaily,
    StockMain,
)
from fund_research.db.models_phase4 import IndexFundSelectionResult

START = date(2025, 1, 2)
DAYS = 90  # > MIN_TRACKING_OBSERVATIONS


# ============================================================
# 测试数据构造
# ============================================================


def _add_fund(
    db: Session,
    code: str,
    *,
    category: str = "指数型-股票",
    sub_category: str = "ETF",
    is_etf: bool = True,
    is_etf_feeder: bool = False,
    is_index_enhanced: bool = False,
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
            is_index_enhanced=is_index_enhanced,
            benchmark=benchmark,
        )
    )


def _add_index_series(db: Session, symbol: str, daily_ret: float = 0.001) -> None:
    db.add(StockMain(stock_code=symbol, stock_name=f"指数{symbol}"))
    price = 1000.0
    for i in range(DAYS + 1):
        db.add(
            StockDaily(
                stock_code=symbol,
                trade_date=START + timedelta(days=i),
                close_price=price,
                daily_return=daily_ret if i > 0 else None,
            )
        )
        price *= 1 + daily_ret


def _add_nav_series(db: Session, fund_code: str, daily_ret: float = 0.0012, days: int = DAYS) -> None:
    nav = 1.0
    for i in range(days + 1):
        db.add(
            FundNAV(
                fund_code=fund_code,
                trade_date=START + timedelta(days=i),
                unit_nav=nav,
                adjusted_nav=nav,
            )
        )
        nav *= 1 + daily_ret


def _add_etf_profile(
    db: Session,
    fund_code: str,
    *,
    tracking_code: str = "sh000300",
    amount: float = 1e9,
    premium: float = 0.05,
) -> None:
    db.add(
        EtfProfile(
            fund_code=fund_code,
            tracking_index_code=tracking_code,
            tracking_index_name="沪深300",
            avg_daily_amount_1y=amount,
            latest_premium_rate=premium,
            source_name="unit_test",
            source_level="B",
        )
    )


def _seed_two_etfs_one_enhanced(db: Session) -> None:
    """两只沪深300 ETF + 一只沪深300 指增（场外，走业绩基准解析）。"""
    _add_index_series(db, "sh000300")
    _add_fund(db, "510300")
    _add_fund(db, "510310")
    _add_fund(
        db,
        "000961",
        sub_category="指数增强",
        is_etf=False,
        is_index_enhanced=True,
        benchmark="沪深300指数收益率×95%",
    )
    _add_etf_profile(db, "510300", amount=5e9, premium=0.02)
    _add_etf_profile(db, "510310", amount=1e9, premium=0.10)
    for code in ("510300", "510310", "000961"):
        _add_nav_series(db, code)
        db.add(FundFee(fund_code=code, mgmt_fee_pct=0.5, custody_fee_pct=0.1))
        db.add(FundScale(fund_code=code, report_date=date(2025, 6, 30), total_nav=100.0))
    db.commit()


# ============================================================
# 常量与候选筛选
# ============================================================


def test_algorithm_name_and_version() -> None:
    assert ALGORITHM_NAME == "index_fund_selection"
    assert ALGORITHM_VERSION == "0.1.0"


def test_candidates_include_only_index_funds(test_session: Session) -> None:
    _add_fund(test_session, "510300")
    _add_fund(test_session, "000001", category="混合型", sub_category="偏股混合", is_etf=False)
    _add_fund(
        test_session,
        "110001",
        category="债券型-纯债",
        sub_category="纯债",
        is_etf=False,
    )
    _add_fund(
        test_session,
        "161725",
        category="指数型-股票",
        sub_category="普通指数",
        is_etf=False,
    )
    test_session.commit()

    codes = {f.fund_code for f in load_index_fund_candidates(test_session)}
    assert codes == {"510300", "161725"}


# ============================================================
# 分组、评分与排名
# ============================================================


def test_run_selection_groups_ranks_and_scores(test_session: Session) -> None:
    _seed_two_etfs_one_enhanced(test_session)

    report = run_selection(test_session)

    scored = [r for r in report.records if r.group_key == "sh000300"]
    assert len(scored) == 3
    assert all(r.composite_score is not None for r in scored)
    assert all(r.group_size == 3 for r in scored)
    ranks = sorted(r.rank_in_group for r in scored)
    assert ranks == [1, 2, 3]
    # 跟踪质量维度：样本内 NAV 与指数对齐，应全部可用
    assert all(not r.dimension_scores["tracking"]["missing"] for r in scored)
    assert all(r.conclusion_status == "computed" for r in scored)


def test_passive_funds_have_no_alpha_enhanced_has_alpha(test_session: Session) -> None:
    _seed_two_etfs_one_enhanced(test_session)

    report = run_selection(test_session)
    by_code = {r.fund_code: r for r in report.records}

    assert by_code["510300"].template_name == "index_passive"
    assert by_code["510300"].alpha_annualized is None
    assert by_code["000961"].template_name == "index_enhanced"
    assert by_code["000961"].alpha_annualized is not None
    assert by_code["000961"].information_ratio is not None
    assert by_code["000961"].deviation_curve


def test_missing_dimensions_renormalize_weights(test_session: Session) -> None:
    """场外指增无 etf_profile → 流动性/折溢价缺失，综合分按可用权重归一。"""
    _seed_two_etfs_one_enhanced(test_session)

    report = run_selection(test_session)
    enhanced = next(r for r in report.records if r.fund_code == "000961")

    assert enhanced.dimension_scores["liquidity"]["missing"] is True
    assert enhanced.dimension_scores["premium"]["missing"] is True
    assert any("流动性维度缺失" in w for w in enhanced.warnings)
    # 综合分 = 可用维度加权和 / 可用权重和（不补 0 分）
    expected = composite_from_scores(enhanced.dimension_scores)
    assert enhanced.composite_score == expected
    available_dims = [d for d, v in enhanced.dimension_scores.items() if not v["missing"]]
    assert set(available_dims) == {"scale", "fee", "tracking"}


def test_score_dimensions_direction() -> None:
    raw_by_fund = {
        "A": {"scale": 100.0, "fee": 0.2, "tracking": 0.01},
        "B": {"scale": 500.0, "fee": 0.5, "tracking": 0.03},
        "C": {"scale": 200.0, "fee": 0.8, "tracking": 0.02},
    }
    scores = score_dimensions(raw_by_fund)
    # 规模最高（B）应得最高分；费率最低（A）应得最高分；跟踪误差最低（A）最高分
    assert scores["B"]["scale"]["score"] == 100.0
    assert scores["A"]["fee"]["score"] == 100.0
    assert scores["A"]["tracking"]["score"] == 100.0
    # 最差值取分位 1/n（n=3）；B 费率为中间值取 2/3，跟踪误差为最差取 1/3（score 保留两位小数）
    assert scores["C"]["fee"]["score"] == pytest.approx(100.0 / 3, abs=0.01)
    assert scores["B"]["fee"]["score"] == pytest.approx(200.0 / 3, abs=0.01)
    assert scores["B"]["tracking"]["score"] == pytest.approx(100.0 / 3, abs=0.01)


def test_composite_none_when_all_dimensions_missing() -> None:
    scores = {dim: {"raw": None, "score": None, "missing": True} for dim in ("scale", "fee")}
    assert composite_from_scores(scores) is None


def test_single_member_group_warns(test_session: Session) -> None:
    _add_index_series(test_session, "sh000905")
    _add_fund(test_session, "510500", sub_category="ETF")
    _add_etf_profile(test_session, "510500", tracking_code="sh000905")
    _add_nav_series(test_session, "510500")
    test_session.commit()

    report = run_selection(test_session)
    rec = report.records[0]
    assert rec.group_size == 1
    assert any("对比意义有限" in w for w in rec.warnings)


# ============================================================
# 门禁与降级
# ============================================================


def test_etf_selection_gate_excludes_non_index_families() -> None:
    """防御性门禁：若非指数族基金到达模块层，etf_selection 门禁应拒绝（P4.2-1 占位）。

    候选筛选层已将非指数族排除在外，本用例直接验证门禁配置本身。
    """
    from fund_research.research.credibility import check_algorithm_applicability

    for category in ("债券型-短债", "货币型", "股票型", "混合型"):
        gate = check_algorithm_applicability("etf_selection", category)
        assert gate.passed is False, category
    assert check_algorithm_applicability("etf_selection", "指数型-股票").passed is True


def test_etf_with_equity_category_passes_gate(test_session: Session) -> None:
    """东财场内 ETF 一级分类常为“股票型”：is_etf 标识应优先归指数族；
    “股票型-增强指数”分类应识别为 index_enhanced 模板。"""
    _add_index_series(test_session, "sh000016")
    _add_fund(test_session, "510050", category="股票型", sub_category="ETF")
    _add_fund(
        test_session,
        "110003",
        category="股票型-增强指数",
        sub_category="普通指数",
        is_etf=False,
        benchmark="上证50指数收益率×95%",
    )
    _add_etf_profile(test_session, "510050", tracking_code="sh000016")
    _add_nav_series(test_session, "510050")
    _add_nav_series(test_session, "110003")
    test_session.commit()

    report = run_selection(test_session)
    by_code = {r.fund_code: r for r in report.records}
    assert by_code["510050"].conclusion_status == "computed"
    assert by_code["510050"].group_key == "sh000016"
    assert by_code["110003"].template_name == "index_enhanced"
    assert by_code["110003"].alpha_annualized is not None


def test_unresolved_tracking_index_needs_review(test_session: Session) -> None:
    _add_fund(test_session, "510300", benchmark=None)
    _add_nav_series(test_session, "510300")
    test_session.commit()

    report = run_selection(test_session)
    rec = report.records[0]
    assert rec.conclusion_status == "needs_review"
    assert any("跟踪指数不可解析" in w for w in rec.warnings)


def test_insufficient_observations_degrades_to_observation(test_session: Session) -> None:
    _add_index_series(test_session, "sh000300")
    _add_fund(test_session, "510300")
    _add_etf_profile(test_session, "510300")
    _add_nav_series(test_session, "510300", days=MIN_TRACKING_OBSERVATIONS - 30)
    test_session.commit()

    report = run_selection(test_session)
    rec = report.records[0]
    assert rec.dimension_scores["tracking"]["missing"] is True
    assert rec.conclusion_status == "observation"
    assert any("跟踪误差不可计算" in w for w in rec.warnings)


def test_empty_candidates_warns(test_session: Session) -> None:
    report = run_selection(test_session)
    assert report.records == []
    assert any("无指数类候选基金" in w for w in report.warnings)


def test_filter_by_index_symbol(test_session: Session) -> None:
    _seed_two_etfs_one_enhanced(test_session)
    _add_index_series(test_session, "sh000905")
    _add_fund(test_session, "510500")
    _add_etf_profile(test_session, "510500", tracking_code="sh000905")
    _add_nav_series(test_session, "510500")
    test_session.commit()

    report = run_selection(test_session, index_symbol="sh000905")
    # 输出层过滤：只保留目标指数记录，无门禁拒绝/未解析记录泄漏
    assert {r.fund_code for r in report.records} == {"510500"}
    assert all(r.group_key == "sh000905" for r in report.records)


def test_filter_by_index_symbol_excludes_leaked_records(test_session: Session) -> None:
    """审计修复回归：限定指数时，跟踪其他指数/未解析/门禁拒绝的记录不入报告，
    且评分按全池口径（510500 的规模分受其他候选影响）。"""
    _seed_two_etfs_one_enhanced(test_session)
    _add_index_series(test_session, "sh000905")
    _add_fund(test_session, "510500")
    _add_etf_profile(test_session, "510500", tracking_code="sh000905")
    _add_nav_series(test_session, "510500")
    # 未解析跟踪指数的干扰记录
    _add_fund(test_session, "588000", benchmark=None)
    _add_nav_series(test_session, "588000")
    test_session.commit()

    report = run_selection(test_session, index_symbol="sh000905")
    assert {r.fund_code for r in report.records} == {"510500"}

    # 评分基准为全池：与全量运行结果一致（不因局部过滤而改变）
    full = run_selection(test_session)
    full_rec = next(r for r in full.records if r.fund_code == "510500")
    partial_rec = report.records[0]
    assert partial_rec.composite_score == full_rec.composite_score
    assert partial_rec.dimension_scores == full_rec.dimension_scores


def test_filter_by_unknown_index_empty_with_warning(test_session: Session) -> None:
    _seed_two_etfs_one_enhanced(test_session)

    report = run_selection(test_session, index_symbol="sh999999")
    assert report.records == []
    assert any("sh999999" in w for w in report.warnings)


# ============================================================
# 持久化
# ============================================================


def test_persist_selection_results_idempotent(test_session: Session) -> None:
    _seed_two_etfs_one_enhanced(test_session)
    report = run_selection(test_session)

    calc_date = date(2026, 8, 20)
    persist_selection_results(test_session, report, calc_date=calc_date)
    test_session.commit()
    first_count = len(
        test_session.scalars(select(IndexFundSelectionResult)).all()
    )

    # 重跑同日期同版本 → 覆盖更新，行数不变
    report2 = run_selection(test_session)
    persist_selection_results(test_session, report2, calc_date=calc_date)
    test_session.commit()
    second_count = len(
        test_session.scalars(select(IndexFundSelectionResult)).all()
    )
    assert first_count == second_count == 3


def test_get_latest_selection_results_empty_then_populated(test_session: Session) -> None:
    assert get_latest_selection_results(test_session) == []

    _seed_two_etfs_one_enhanced(test_session)
    report = run_selection(test_session)
    persist_selection_results(test_session, report, calc_date=date(2026, 8, 20))
    test_session.commit()

    rows = get_latest_selection_results(test_session)
    assert len(rows) == 3
    # 综合分降序排列
    scores = [r.composite_score for r in rows]
    assert scores == sorted(scores, reverse=True)
