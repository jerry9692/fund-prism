"""P4C 组合穿透分析 v2 端点 API 层测试（延续 P4.3-5 模式）。

覆盖 pools 权重编辑、portfolios analysis/latest/packet 端点的
happy path + 边界/降级用例（§5.5 结论门禁 + §12.4.4 组合研究包）。
"""

import math
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    EvidenceRecord as DbEvidenceRecord,
)
from fund_research.db.models import (
    FundMain,
    FundNAV,
    ResearchPacketRecord,
)
from fund_research.db.models_phase2 import FundPool, FundPoolMember
from fund_research.db.models_phase4 import UserPortfolio

START = date(2025, 1, 2)
DAYS = 90


def _make_returns(seed: float) -> list[float]:
    return [0.001 * math.sin(2 * math.pi * i / 7.0 + seed) for i in range(DAYS)]


def _seed_pool_world(test_session: Session, weighted: bool = True) -> int:
    """两只基金 + 90 日净值 + 一个两只成员的池。"""
    for code in ("000001", "020005"):
        test_session.add(
            FundMain(
                fund_code=code,
                short_name=f"基金{code}",
                full_name=f"基金{code}全称",
                category="混合型",
                sub_category="主动权益",
            )
        )
    for code, seed in (("000001", 0.0), ("020005", 1.5)):
        nav = 1.0
        test_session.add(
            FundNAV(fund_code=code, trade_date=START, unit_nav=nav, adjusted_nav=nav)
        )
        for i, ret in enumerate(_make_returns(seed)):
            nav *= 1 + ret
            test_session.add(
                FundNAV(
                    fund_code=code,
                    trade_date=START + timedelta(days=i + 1),
                    unit_nav=nav,
                    adjusted_nav=nav,
                )
            )
    test_session.add(FundPool(name="测试组合"))
    test_session.flush()
    pool_id = (
        test_session.scalars(select(FundPool).order_by(FundPool.id.desc()).limit(1))
        .first()
        .id
    )
    weights = (60.0, 40.0) if weighted else (None, None)
    for code, weight in zip(("000001", "020005"), weights, strict=True):
        test_session.add(
            FundPoolMember(pool_id=pool_id, fund_code=code, weight_pct=weight)
        )
    test_session.commit()
    return pool_id


# ============================================================
# pools 权重编辑
# ============================================================


def test_add_member_with_weight(test_client: TestClient, test_session: Session) -> None:
    pool_id = _seed_pool_world(test_session)

    resp = test_client.post(
        f"/api/v2/pools/{pool_id}/funds",
        json={"fund_code": "040036", "weight_pct": 25.0},
    )
    # 040036 不在 fund_main（测试池世界仅两只），fund_pool_member 无外键到 fund_main
    assert resp.status_code == 200
    assert resp.json()["data"]["weight_pct"] == 25.0


def test_patch_weights_updates_members(
    test_client: TestClient, test_session: Session
) -> None:
    pool_id = _seed_pool_world(test_session, weighted=False)

    resp = test_client.patch(
        f"/api/v2/pools/{pool_id}/weights",
        json={"weights": {"000001": 70.0, "020005": 30.0, "999999": 10.0}},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["updated"] == {"000001": 70.0, "020005": 30.0}
    assert body["data"]["skipped"] == ["999999"]
    member = test_session.scalar(
        select(FundPoolMember).where(FundPoolMember.fund_code == "000001")
    )
    assert member.weight_pct == 70.0


def test_patch_weights_unknown_pool_needs_review(test_client: TestClient) -> None:
    resp = test_client.patch("/api/v2/pools/999/weights", json={"weights": {}})

    assert resp.status_code == 200
    assert resp.json()["conclusion_status"] == "needs_review"


def test_get_pool_returns_weight_pct(
    test_client: TestClient, test_session: Session
) -> None:
    pool_id = _seed_pool_world(test_session)

    resp = test_client.get(f"/api/v2/pools/{pool_id}")

    funds = resp.json()["data"]["funds"]
    assert {f["fund_code"]: f["weight_pct"] for f in funds} == {
        "000001": 60.0,
        "020005": 40.0,
    }


# ============================================================
# portfolios analysis
# ============================================================


def test_portfolio_analysis_runs_and_persists(
    test_client: TestClient, test_session: Session
) -> None:
    pool_id = _seed_pool_world(test_session)

    resp = test_client.post(f"/api/v2/portfolios/{pool_id}/analysis", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    assert body["data"]["persisted"] is True
    assert body["data"]["weights_mode"] == "weighted"
    assert body["data"]["portfolio_metrics"]["max_drawdown"] is not None
    assert body["data"]["correlation_matrix"]["000001"]["020005"] is not None

    row = test_session.scalar(
        select(UserPortfolio).where(UserPortfolio.pool_id == pool_id)
    )
    assert row is not None


def test_portfolio_analysis_unknown_pool(
    test_client: TestClient,
) -> None:
    resp = test_client.post("/api/v2/portfolios/999/analysis", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "needs_review"
    assert any("不存在" in w for w in body["warnings"])


def test_portfolio_analysis_invalid_calc_date_422(
    test_client: TestClient, test_session: Session
) -> None:
    pool_id = _seed_pool_world(test_session)
    resp = test_client.post(
        f"/api/v2/portfolios/{pool_id}/analysis", json={"calc_date": "bad"}
    )
    assert resp.status_code == 422


def test_portfolio_analysis_latest(
    test_client: TestClient, test_session: Session
) -> None:
    pool_id = _seed_pool_world(test_session)

    before = test_client.get(f"/api/v2/portfolios/{pool_id}/analysis/latest")
    assert before.json()["conclusion_status"] == "needs_review"

    test_client.post(f"/api/v2/portfolios/{pool_id}/analysis", json={})
    after = test_client.get(f"/api/v2/portfolios/{pool_id}/analysis/latest")

    assert after.status_code == 200
    body = after.json()
    assert body["conclusion_status"] == "computed"
    assert body["data"]["pool_name"] == "测试组合"
    assert body["data"]["member_weights"]["000001"] == 0.6


# ============================================================
# portfolios packet（§12.4.4）
# ============================================================


def test_portfolio_packet_builds_with_evidence_chain(
    test_client: TestClient, test_session: Session
) -> None:
    pool_id = _seed_pool_world(test_session)

    resp = test_client.post(f"/api/v2/portfolios/{pool_id}/packet")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    data = body["data"]
    assert data["packet_id"].startswith("rp_pool_")
    packet = data["packet"]
    assert packet["metadata"]["entity_type"] == "portfolio"
    assert packet["metadata"]["pool_id"] == pool_id
    portfolio = packet["portfolio"]
    assert portfolio["portfolio_metrics"]
    assert "member_evidence_refs" in portfolio
    # estimated 口径隔离存在且带前缀
    assert "estimated_overlap" in portfolio["holding_overlap"]
    assert data["markdown"].startswith("# 测试组合")

    # 落库记录：entity_type=portfolio、fund_code 为空、pool_id 关联
    record = test_session.scalar(
        select(ResearchPacketRecord).where(
            ResearchPacketRecord.packet_id == data["packet_id"]
        )
    )
    assert record.entity_type == "portfolio"
    assert record.fund_code is None
    assert record.pool_id == pool_id

    # 组合分析 evidence 已登记（实体类型 portfolio）
    evidence = test_session.scalars(
        select(DbEvidenceRecord).where(
            DbEvidenceRecord.entity_id == f"portfolio:{pool_id}"
        )
    ).all()
    assert len(evidence) >= 1
    assert all(e.entity_type == "portfolio" for e in evidence)


def test_portfolio_packet_unknown_pool_needs_review(test_client: TestClient) -> None:
    resp = test_client.post("/api/v2/portfolios/999/packet")

    assert resp.status_code == 200
    assert resp.json()["conclusion_status"] == "needs_review"
