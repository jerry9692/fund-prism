"""P4B 债基金因子暴露 v2 端点 API 层测试（延续 P4.3-5 模式）。

覆盖 analysis/bond-factors 的 run（批量）/scan（扫描）/单基金 POST/latest
四类端点的 happy path + 边界/降级用例（§5.5 结论门禁 + evidence 登记）。
"""

import math
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import EvidenceRecord as DbEvidenceRecord
from fund_research.db.models import FundMain, FundNAV
from fund_research.db.models_phase4 import BondFactorExposureResult, FactorReturn

START = date(2023, 9, 1)
POINTS = 201  # 200 个日收益（> 120 窗口），收益与因子同日对齐


def _factor_series(name: str) -> list[float]:
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
        base + amp * math.sin(2 * math.pi * i / period + phase)
        for i in range(POINTS)
    ]


def _seed_bond_world(db: Session) -> None:
    """一只纯债 + 一只转债基金，因子序列齐全。"""
    for name in (
        "bond_coupon", "bond_rate", "bond_slope",
        "bond_credit_aaa", "bond_convertible", "style_large_cap",
    ):
        for i, value in enumerate(_factor_series(name)):
            db.add(
                FactorReturn(
                    factor_name=name,
                    trade_date=START + timedelta(days=i),
                    factor_return=value,
                    source_name="unit_test",
                    source_level="B",
                )
            )
    db.add(
        FundMain(
            fund_code="000032", short_name="纯债A", full_name="纯债A全称",
            category="债券型-长期纯债", sub_category="纯债",
        )
    )
    db.add(
        FundMain(
            fund_code="040022", short_name="转债A", full_name="转债A全称",
            category="债券型-可转债", sub_category="可转债",
        )
    )
    rate = _factor_series("bond_rate")
    credit = _factor_series("bond_credit_aaa")
    conv = _factor_series("bond_convertible")
    equity = _factor_series("style_large_cap")
    for code, returns in (
        ("000032", [2.0 * rate[i] + 0.5 * credit[i] for i in range(1, POINTS)]),
        ("040022", [0.9 * conv[i] + 0.4 * equity[i] for i in range(1, POINTS)]),
    ):
        nav = 1.0
        db.add(FundNAV(fund_code=code, trade_date=START, unit_nav=nav, adjusted_nav=nav))
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
    db.commit()


# ============================================================
# run（批量）端点
# ============================================================


def test_run_batch_persists_all_bond_funds(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_bond_world(test_session)

    resp = test_client.post("/api/v2/analysis/bond-factors/run", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    assert body["data"]["persisted"] == 2
    assert body["data"]["evidence_count"] == 2
    templates = {r["fund_code"]: r["template_name"] for r in body["data"]["results"]}
    assert templates == {"000032": "bond_pure", "040022": "bond_convertible"}


def test_run_batch_empty_needs_review(test_client: TestClient) -> None:
    resp = test_client.post("/api/v2/analysis/bond-factors/run", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "needs_review"
    assert any("无债基候选" in w for w in body["warnings"])


def test_run_batch_invalid_calc_date_returns_422(test_client: TestClient) -> None:
    resp = test_client.post(
        "/api/v2/analysis/bond-factors/run", json={"calc_date": "not-a-date"}
    )
    assert resp.status_code == 422


# ============================================================
# scan 端点
# ============================================================


def test_scan_without_run_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/analysis/bond-factors/scan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


def test_scan_after_run_returns_results(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_bond_world(test_session)
    test_client.post("/api/v2/analysis/bond-factors/run", json={})

    resp = test_client.get("/api/v2/analysis/bond-factors/scan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    results = body["data"]["results"]
    assert len(results) == 2
    assert all(r["algorithm_version"] == "0.1.0" for r in results)
    pure = next(r for r in results if r["fund_code"] == "000032")
    assert pure["exposure_curves"]
    assert pure["radar"]["duration"] is not None


# ============================================================
# 单基金 POST 端点
# ============================================================


def test_single_fund_run_with_evidence(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_bond_world(test_session)

    resp = test_client.post("/api/v2/analysis/bond-factors/000032", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    data = body["data"]
    assert data["template_name"] == "bond_pure"
    assert data["persisted"] is True
    assert data["evidence_id"] == "bond_factor_exposure:000032:" + str(date.today())

    # evidence 表已登记因子序列覆盖度
    evidence = test_session.scalar(
        select(DbEvidenceRecord).where(DbEvidenceRecord.evidence_id == data["evidence_id"])
    )
    assert evidence is not None
    assert evidence.entity_id == "000032"
    assert "覆盖度" in (evidence.data_summary or "")
    assert evidence.algorithm_metadata["algorithm_name"] == "bond_factor_exposure"

    # 落库记录存在
    row = test_session.scalar(
        select(BondFactorExposureResult).where(
            BondFactorExposureResult.fund_code == "000032"
        )
    )
    assert row is not None


def test_single_fund_dry_run_not_persisted(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_bond_world(test_session)

    resp = test_client.post(
        "/api/v2/analysis/bond-factors/000032", json={"persist": False}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["persisted"] is False
    assert "evidence_id" not in body["data"]
    assert (
        test_session.scalar(
            select(BondFactorExposureResult).where(
                BondFactorExposureResult.fund_code == "000032"
            )
        )
        is None
    )


def test_single_unknown_fund_needs_review(test_client: TestClient) -> None:
    resp = test_client.post("/api/v2/analysis/bond-factors/999999", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"
    assert any("不存在" in w for w in body["warnings"])


def test_single_non_bond_fund_needs_review(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_bond_world(test_session)
    test_session.add(
        FundMain(
            fund_code="000001", short_name="混合基金", full_name="混合基金全称",
            category="混合型", sub_category="主动权益",
        )
    )
    test_session.commit()

    resp = test_client.post("/api/v2/analysis/bond-factors/000001", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "needs_review"
    assert any("非债基候选" in w for w in body["warnings"])


def test_single_invalid_calc_date_returns_422(test_client: TestClient) -> None:
    resp = test_client.post(
        "/api/v2/analysis/bond-factors/000032", json={"calc_date": "bad"}
    )
    assert resp.status_code == 422


# ============================================================
# latest 端点
# ============================================================


def test_latest_without_run_needs_review(test_client: TestClient) -> None:
    resp = test_client.get("/api/v2/analysis/bond-factors/000032/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert body["conclusion_status"] == "needs_review"


def test_latest_after_single_run_returns_result(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_bond_world(test_session)
    test_client.post("/api/v2/analysis/bond-factors/040022", json={})

    resp = test_client.get("/api/v2/analysis/bond-factors/040022/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conclusion_status"] == "computed"
    data = body["data"]
    assert data["template_name"] == "bond_convertible"
    # 转债基金权益 beta 与转债暴露可区分（§6.2.7 验收）
    assert data["latest_exposures"]["bond_convertible"] > 0.7
    assert data["latest_exposures"]["style_large_cap"] > 0.2
