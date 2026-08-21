"""P4E 公司画像频谱与经理团队画像 v2 端点 API 层测试（延续 P4.3-5 模式）。

覆盖 companies/spectra、companies/{id}/spectrum、managers、
managers/{id}/profile 四组端点的 happy path + 边界/降级用例。
"""

from datetime import date, timedelta

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundCompany,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    StockDaily,
    StockMain,
)

START = date(2024, 1, 2)
DAYS = 260


def _seed(test_session: Session) -> tuple[str, str]:
    """一家公司两只 ETF 联接 + 一位现任经理，返回 (company_id, manager_id)。"""
    rng = np.random.RandomState(7)
    index_ret = rng.normal(0.0005, 0.01, DAYS + 1)
    test_session.add(StockMain(stock_code="sh000300", stock_name="沪深300"))
    price = 1000.0
    for i in range(DAYS + 1):
        test_session.add(
            StockDaily(
                stock_code="sh000300",
                trade_date=START + timedelta(days=i),
                close_price=price,
                daily_return=float(index_ret[i]) if i > 0 else None,
            )
        )
        price *= 1 + index_ret[i]

    company = FundCompany(company_id="comp_x", name="测试公司", short_name="测试公司")
    test_session.add(company)
    test_session.flush()

    for code in ("510300", "110020"):
        test_session.add(
            FundMain(
                fund_code=code,
                short_name=f"基金{code}",
                full_name=f"基金{code}全称",
                category="股票型-标准指数",
                sub_category="ETF",
                is_etf=(code == "510300"),
                is_etf_feeder=(code == "110020"),
                fund_company_id=company.id,
            )
        )
        noise = np.random.RandomState(11 if code == "510300" else 13).normal(
            0.0, 0.002, DAYS + 1
        )
        nav = 1.0
        for i in range(DAYS + 1):
            nav *= 1 + index_ret[i] + noise[i]
            test_session.add(
                FundNAV(
                    fund_code=code,
                    trade_date=START + timedelta(days=i),
                    unit_nav=nav,
                    adjusted_nav=nav,
                )
            )
        test_session.add(
            FundScale(fund_code=code, report_date=date(2025, 6, 30), total_nav=80.0)
        )

    manager_id = "mgr_x01"
    test_session.add(FundManager(manager_id=manager_id, name="测试经理"))
    test_session.add(
        FundManagerTenure(
            manager_id=manager_id,
            fund_code="510300",
            start_date=date(2022, 1, 1),
            is_current=True,
            tenure_days=900,
        )
    )
    test_session.commit()
    return "comp_x", manager_id


# ============================================================
# companies 端点
# ============================================================


def test_spectra_empty_db_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/companies/spectra")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


def test_spectra_returns_overview(test_client: TestClient, test_session: Session) -> None:
    _seed(test_session)
    resp = test_client.get("/api/v2/companies/spectra")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    companies = body["data"]["companies"]
    assert {c["company_id"] for c in companies} == {"comp_x"}
    assert companies[0]["insufficient_sample"] is True  # 2 只 < 3
    funds = body["data"]["funds"]
    assert len(funds) == 2
    assert all(f["alpha_annualized"] is not None for f in funds)


def test_spectrum_detail_insufficient_sample_observation(
    test_client: TestClient, test_session: Session
) -> None:
    company_id, _ = _seed(test_session)
    resp = test_client.get(f"/api/v2/companies/{company_id}/spectrum")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "observation"
    assert body["data"]["fund_count"] == 2
    assert any("样本不足" in w for w in body["warnings"])


def test_spectrum_unknown_company_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/companies/no_such/spectrum")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


# ============================================================
# managers 端点
# ============================================================


def test_managers_empty_db_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/managers")
    assert resp.status_code == 200
    assert resp.json()["conclusion_status"] == "needs_review"


def test_managers_list_and_profile_roundtrip(
    test_client: TestClient, test_session: Session
) -> None:
    _, manager_id = _seed(test_session)

    list_resp = test_client.get("/api/v2/managers")
    assert list_resp.status_code == 200
    managers = list_resp.json()["data"]["managers"]
    assert {m["manager_id"] for m in managers} == {manager_id}
    assert managers[0]["current_fund_count"] == 1

    profile_resp = test_client.get(f"/api/v2/managers/{manager_id}/profile")
    assert profile_resp.status_code == 200
    body = profile_resp.json()
    assert body["conclusion_status"] == "computed"
    data = body["data"]
    assert data["name"] == "测试经理"
    assert data["tenure_weighted_alpha"] is not None
    assert data["managed_scale"] == 80.0
    assert len(data["current_funds"]) == 1
    # 同类排名口径：同 sub_category（ETF）两只基金内排名
    assert data["peer_rank"]["ranks"][0]["rank_text"].endswith("/2")


def test_manager_profile_unknown_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/managers/no_such/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"
