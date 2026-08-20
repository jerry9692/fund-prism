"""P4A 指数基金优选 v2 端点 API 层测试（延续 P4.3-5 模式）。

覆盖 index-funds/compare、index-funds/selection、index-funds/selection/latest
三组端点的 happy path + 边界/降级用例（§5.5 结论门禁）。
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.db.models import (
    EtfProfile,
    FundFee,
    FundMain,
    FundNAV,
    FundScale,
    StockDaily,
    StockMain,
)

START = date(2025, 1, 2)
DAYS = 90


def _seed_index_funds(test_session: Session) -> None:
    """两只沪深300 ETF（etf_profile 齐全）+ 一只场外指增。"""
    test_session.add(StockMain(stock_code="sh000300", stock_name="沪深300"))
    price = 1000.0
    for i in range(DAYS + 1):
        test_session.add(
            StockDaily(
                stock_code="sh000300",
                trade_date=START + timedelta(days=i),
                close_price=price,
                daily_return=0.001 if i > 0 else None,
            )
        )
        price *= 1.001

    funds = [
        FundMain(
            fund_code="510300",
            short_name="沪深300ETF",
            full_name="沪深300ETF全称",
            category="指数型-股票",
            sub_category="ETF",
            is_etf=True,
        ),
        FundMain(
            fund_code="510310",
            short_name="沪深300ETF二",
            full_name="沪深300ETF二全称",
            category="指数型-股票",
            sub_category="ETF",
            is_etf=True,
        ),
        FundMain(
            fund_code="000961",
            short_name="沪深300指增",
            full_name="沪深300指增全称",
            category="指数型-股票",
            sub_category="指数增强",
            is_index_enhanced=True,
            benchmark="沪深300指数收益率×95%",
        ),
    ]
    for fund in funds:
        test_session.add(fund)

    for code, amount, premium in (("510300", 5e9, 0.02), ("510310", 1e9, 0.1)):
        test_session.add(
            EtfProfile(
                fund_code=code,
                tracking_index_code="sh000300",
                tracking_index_name="沪深300",
                avg_daily_amount_1y=amount,
                latest_premium_rate=premium,
                source_name="unit_test",
                source_level="B",
            )
        )

    for code in ("510300", "510310", "000961"):
        nav = 1.0
        for i in range(DAYS + 1):
            test_session.add(
                FundNAV(
                    fund_code=code,
                    trade_date=START + timedelta(days=i),
                    unit_nav=nav,
                    adjusted_nav=nav,
                )
            )
            nav *= 1.0012
        test_session.add(FundFee(fund_code=code, mgmt_fee_pct=0.5, custody_fee_pct=0.1))
        test_session.add(
            FundScale(fund_code=code, report_date=date(2025, 6, 30), total_nav=100.0)
        )
    test_session.commit()


# ============================================================
# compare 端点
# ============================================================


def test_compare_unknown_index_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/index-funds/compare", params={"index_symbol": "sh000300"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["members"] == []
    assert body["conclusion_status"] == "needs_review"


def test_compare_missing_param_returns_422(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/index-funds/compare")
    assert resp.status_code == 422


def test_compare_returns_group_members_with_curves(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_index_funds(test_session)

    resp = test_client.get("/api/v2/index-funds/compare", params={"index_symbol": "sh000300"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    members = body["data"]["members"]
    assert {m["fund_code"] for m in members} == {"510300", "510310", "000961"}
    enhanced = next(m for m in members if m["fund_code"] == "000961")
    assert enhanced["alpha_annualized"] is not None
    assert enhanced["deviation_curve"]
    passive = next(m for m in members if m["fund_code"] == "510300")
    assert passive["alpha_annualized"] is None


# ============================================================
# selection 端点
# ============================================================


def test_selection_runs_and_ranks(test_client: TestClient, test_session: Session) -> None:
    _seed_index_funds(test_session)

    resp = test_client.post("/api/v2/index-funds/selection", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    assert body["data"]["persisted"] == 3
    ranking = body["data"]["ranking"]
    assert len(ranking) == 3
    scores = [r["composite_score"] for r in ranking]
    assert scores == sorted(scores, reverse=True)


def test_selection_empty_scope_needs_review(test_client: TestClient) -> None:
    resp = test_client.post("/api/v2/index-funds/selection", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "needs_review"
    assert any("无指数类候选基金" in w for w in body["warnings"])


def test_selection_invalid_calc_date_returns_422(test_client: TestClient) -> None:
    resp = test_client.post("/api/v2/index-funds/selection", json={"calc_date": "not-a-date"})
    assert resp.status_code == 422


# ============================================================
# latest 端点
# ============================================================


def test_latest_without_run_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/index-funds/selection/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


def test_latest_after_run_returns_results(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_index_funds(test_session)
    test_client.post("/api/v2/index-funds/selection", json={})

    resp = test_client.get("/api/v2/index-funds/selection/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    results = body["data"]["results"]
    assert len(results) == 3
    assert all(r["algorithm_version"] == "0.1.0" for r in results)
