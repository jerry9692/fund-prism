"""P4D ETF 组合构建 v2 端点 API 层测试（延续 P4.3-5 模式）。

覆盖 etf-portfolio/build、etf-portfolio/latest、etf-portfolio/{result_id}
三组端点的 happy path + 边界/降级用例（§5.5 结论门禁）。
"""

from datetime import date, timedelta

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundFee,
    FundMain,
    FundNAV,
    FundScale,
    StockDaily,
    StockMain,
)
from fund_research.db.models_phase4 import EtfProfile

START = date(2024, 1, 2)
DAYS = 320


def _seed_etfs(test_session: Session) -> None:
    """两只跟踪沪深300 的 ETF（带噪声净值序列）。"""
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

    for code in ("510300", "510310"):
        test_session.add(
            FundMain(
                fund_code=code,
                short_name=f"沪深300ETF{code}",
                full_name=f"沪深300ETF{code}全称",
                category="股票型",
                sub_category="ETF",
                is_etf=True,
            )
        )
        test_session.add(
            EtfProfile(
                fund_code=code,
                tracking_index_code="sh000300",
                tracking_index_name="沪深300",
                avg_daily_amount_1y=1e9,
                latest_premium_rate=0.05,
                source_name="unit_test",
                source_level="B",
            )
        )
        noise = np.random.RandomState(11 if code == "510300" else 13).normal(
            0.0, 0.001 if code == "510300" else 0.01, DAYS + 1
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
        test_session.add(FundFee(fund_code=code, mgmt_fee_pct=0.5, custody_fee_pct=0.1))
        test_session.add(
            FundScale(fund_code=code, report_date=date(2025, 6, 30), total_nav=100.0)
        )
    test_session.commit()


# ============================================================
# build 端点
# ============================================================


def test_build_happy_path_persists_and_returns_weights(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_etfs(test_session)

    resp = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000300", "lookback_days": 120},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] in ("computed", "observation")
    data = body["data"]
    assert data["persisted"] is True
    assert data["id"] is not None
    weights = data["member_weights"]
    assert len(weights) >= 1
    assert abs(sum(m["weight"] for m in weights.values()) - 1.0) < 1e-3
    # 约束清单与回测结构齐备
    assert any(c["name"] == "权重合计为 1" for c in data["constraints"])
    assert data["backtest"]["available"] is True
    assert data["backtest"]["summary"]["rebalance_count"] >= 1


def test_build_dry_run_not_persisted(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_etfs(test_session)

    resp = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000300", "lookback_days": 120, "persist": False},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["persisted"] is False
    assert data["id"] is None


def test_build_unknown_target_needs_review(test_client: TestClient) -> None:
    resp = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000999"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "needs_review"
    assert body["data"]["member_weights"] == {}


def test_build_invalid_rebalance_frequency_returns_422(test_client: TestClient) -> None:
    resp = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"rebalance_frequency": "weekly"},
    )
    assert resp.status_code == 422


def test_build_invalid_lookback_returns_422(test_client: TestClient) -> None:
    resp = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"lookback_days": 10},
    )
    assert resp.status_code == 422


# ============================================================
# latest / by-id 端点
# ============================================================


def test_latest_without_build_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/etf-portfolio/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


def test_latest_after_build_returns_results(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_etfs(test_session)
    test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000300", "lookback_days": 120},
    )

    resp = test_client.get("/api/v2/etf-portfolio/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] in ("computed", "observation")
    results = body["data"]["results"]
    assert len(results) == 1
    assert results[0]["target_symbol"] == "sh000300"


def test_get_by_id_roundtrip(test_client: TestClient, test_session: Session) -> None:
    _seed_etfs(test_session)
    build_resp = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000300", "lookback_days": 120},
    )
    result_id = build_resp.json()["data"]["id"]

    resp = test_client.get(f"/api/v2/etf-portfolio/{result_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == result_id
    assert body["data"]["target_symbol"] == "sh000300"


def test_get_unknown_id_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/etf-portfolio/999999")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


def test_build_idempotent_same_day(
    test_client: TestClient, test_session: Session
) -> None:
    """同目标/日期/版本重复构建覆盖更新，不产生新行。"""
    _seed_etfs(test_session)
    first = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000300", "lookback_days": 120},
    ).json()["data"]["id"]
    second = test_client.post(
        "/api/v2/etf-portfolio/build",
        json={"target_symbol": "sh000300", "lookback_days": 120},
    ).json()["data"]["id"]
    assert first == second
