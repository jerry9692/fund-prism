"""P4.3-5 Phase 3 v2 端点 API 层测试。

覆盖 fingerprint / similar / anomaly / pool / reverse_lookup / templates /
dashboard 端点组,每组至少 1 happy path + 1 边界/降级用例,
重点验证 conclusion_status 降级路径(§5.5)。
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel
from fund_research.db.models import FundDisclosedHoldings, FundMain

# ============================================================
# 测试数据
# ============================================================


def _seed_fund(test_session: Session, fund_code: str = "000001") -> None:
    test_session.add(
        FundMain(
            fund_code=fund_code,
            short_name="测试基金",
            full_name="测试基金全称",
            category="混合型",
            sub_category="主动权益",
            data_source="unit_test",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.commit()


def _seed_holding(test_session: Session, fund_code: str, stock: str = "600000") -> None:
    test_session.add(
        FundDisclosedHoldings(
            fund_code=fund_code,
            report_date=date(2026, 6, 30),
            asset_type="股票",
            security_code=stock,
            security_name=f"股票{stock}",
            weight_pct=5.0,
            rank_in_holdings=1,
        )
    )
    test_session.commit()


# ============================================================
# fingerprint 端点组
# ============================================================


def test_fingerprint_generate_and_get(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_fund(test_session)

    post_resp = test_client.post("/api/v2/fingerprint/000001")
    assert post_resp.status_code == 200
    assert post_resp.json()["data"]["fund_code"] == "000001"

    get_resp = test_client.get("/api/v2/fingerprint/000001")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"] is not None


def test_fingerprint_unknown_fund_marks_needs_review(
    test_client: TestClient, test_session: Session
) -> None:
    """未知基金回落 default 模板 → needs_review(未适配类型标不适用)。"""
    resp = test_client.post("/api/v2/fingerprint/999999")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["template_name"] == "default"
    assert body["conclusion_status"] == "needs_review"


# ============================================================
# similar 端点组
# ============================================================


def test_similar_without_fingerprint_returns_empty(
    test_client: TestClient, test_session: Session
) -> None:
    """无指纹数据时相似搜索返回空列表而非报错。"""
    _seed_fund(test_session)

    resp = test_client.post("/api/v2/fingerprint/000001/similar", json={"top_n": 5})

    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 0


# ============================================================
# anomaly 端点组
# ============================================================


def test_anomaly_scan_empty_universe(
    test_client: TestClient, test_session: Session
) -> None:
    resp = test_client.post("/api/v2/anomalies/scan", json={"scope": "all"})

    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    list_resp = test_client.get("/api/v2/anomalies")
    assert list_resp.status_code == 200


def test_anomaly_scan_invalid_scope_422(
    test_client: TestClient, test_session: Session
) -> None:
    resp = test_client.post("/api/v2/anomalies/scan", json={"scope": "bad_scope"})
    assert resp.status_code == 422


# ============================================================
# pool 端点组
# ============================================================


def test_pool_create_and_member_lifecycle(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_fund(test_session)

    create = test_client.post("/api/v2/pools", json={"name": "测试池"})
    assert create.status_code == 200
    pool_id = create.json()["data"]["id"]

    add = test_client.post(
        f"/api/v2/pools/{pool_id}/funds", json={"fund_code": "000001"}
    )
    assert add.status_code == 200

    listing = test_client.get("/api/v2/pools")
    assert listing.status_code == 200

    delete = test_client.delete(f"/api/v2/pools/{pool_id}/funds/000001")
    assert delete.status_code == 200


def test_pool_add_member_missing_pool_needs_review(
    test_client: TestClient, test_session: Session
) -> None:
    """不存在的基金池 → needs_review 降级。"""
    resp = test_client.post("/api/v2/pools/999999/funds", json={"fund_code": "000001"})

    assert resp.status_code == 200
    assert resp.json()["conclusion_status"] == "needs_review"


# ============================================================
# reverse_lookup 端点组
# ============================================================


def test_reverse_lookup_disclosed_fact(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_fund(test_session)
    _seed_holding(test_session, "000001")

    resp = test_client.post(
        "/api/v2/analysis/reverse-lookup",
        json={"stock_codes": ["600000"], "method": "disclosed"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["fund_count"] == 1
    assert body["conclusion_status"] == "fact"
    # P4.3-1:输出字段补全
    row = body["data"]["results"][0]
    assert row["fund_name"] == "测试基金"
    assert "rank_in_category_1y" in row


def test_reverse_lookup_no_match_needs_review(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_fund(test_session)

    resp = test_client.post(
        "/api/v2/analysis/reverse-lookup",
        json={"stock_codes": ["999999"], "method": "disclosed"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["fund_count"] == 0
    assert body["conclusion_status"] == "needs_review"


def test_reverse_lookup_time_range_validation(
    test_client: TestClient, test_session: Session
) -> None:
    """P4.3-1:非法 time_range → 422;specified_date 缺 report_date → needs_review。"""
    bad = test_client.post(
        "/api/v2/analysis/reverse-lookup",
        json={"stock_codes": ["600000"], "time_range": "bad_range"},
    )
    assert bad.status_code == 422

    missing_date = test_client.post(
        "/api/v2/analysis/reverse-lookup",
        json={"stock_codes": ["600000"], "time_range": "specified_date"},
    )
    assert missing_date.status_code == 200
    assert missing_date.json()["conclusion_status"] == "needs_review"


# ============================================================
# templates 端点组
# ============================================================


def test_templates_seed_list_and_run(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_fund(test_session)
    _seed_holding(test_session, "000001")

    seed = test_client.post("/api/v2/templates/seed")
    assert seed.status_code == 200
    assert seed.json()["data"]["inserted"] >= 7

    listing = test_client.get("/api/v2/templates")
    assert listing.status_code == 200
    template_ids = {t["template_id"] for t in listing.json()["data"]["templates"]}
    # P4.3-2 新增模板可通过 API seed
    assert "holding_change_watch" in template_ids
    assert "risk_scan" in template_ids

    run = test_client.post(
        "/api/v2/templates/risk_scan/run", json={"inputs": {"fund_code": "000001"}}
    )
    assert run.status_code == 200
    assert run.json()["data"]["template_id"] == "risk_scan"


def test_templates_run_unknown_template_fails(
    test_client: TestClient, test_session: Session
) -> None:
    resp = test_client.post(
        "/api/v2/templates/no_such_template/run", json={"inputs": {}}
    )
    # 未知模板走异常分支,不应 500
    assert resp.status_code == 200
    assert resp.json()["conclusion_status"] == "needs_review"


# ============================================================
# dashboard 端点组
# ============================================================


def test_dashboard_returns_panels(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_fund(test_session)

    resp = test_client.get("/api/v2/dashboard")

    assert resp.status_code == 200
    data = resp.json()["data"]
    # P4.3-3:市场环境面板含指数/因子环境键(空库为空列表)
    assert "index_performance" in data["market_overview"]
    assert "factor_trends" in data["market_overview"]
