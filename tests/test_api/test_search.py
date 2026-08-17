"""P4.3-4 基金检索 API 测试 — 经理/公司/重仓股关键词扩展（§6.3.1）。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel
from fund_research.db.models import (
    FundCompany,
    FundDisclosedHoldings,
    FundMain,
    FundManager,
    FundManagerTenure,
)


def _seed_search_universe(test_session: Session) -> None:
    company = FundCompany(company_id="c_search", name="棱镜基金", short_name="棱镜")
    test_session.add(company)
    test_session.flush()
    test_session.add(
        FundMain(
            fund_code="519001",
            short_name="棱镜优选",
            full_name="棱镜优选混合型证券投资基金",
            fund_company_id=company.id,
            category="混合型",
            sub_category="主动权益",
            data_source="unit_test",
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.add(FundManager(manager_id="m_search", name="张长盛"))
    test_session.add(
        FundManagerTenure(
            manager_id="m_search",
            fund_code="519001",
            start_date=date(2020, 1, 1),
            is_current=True,
        )
    )
    test_session.add(
        FundDisclosedHoldings(
            fund_code="519001",
            report_date=date(2026, 6, 30),
            asset_type="股票",
            security_code="600519",
            security_name="贵州茅台",
            weight_pct=8.0,
            rank_in_holdings=1,
        )
    )
    test_session.commit()


def test_search_by_fund_name(test_client: TestClient, test_session: Session) -> None:
    _seed_search_universe(test_session)

    response = test_client.get("/api/v1/funds/search", params={"q": "棱镜优选"})

    assert response.status_code == 200
    funds = response.json()["data"]["funds"]
    assert funds[0]["fund_code"] == "519001"
    assert funds[0]["match_source"] == "fund"


def test_search_by_manager_name(test_client: TestClient, test_session: Session) -> None:
    """P4.3-4：基金经理姓名关键词应命中在管基金。"""
    _seed_search_universe(test_session)

    response = test_client.get("/api/v1/funds/search", params={"q": "张长盛"})

    assert response.status_code == 200
    funds = response.json()["data"]["funds"]
    assert [f["fund_code"] for f in funds] == ["519001"]
    assert funds[0]["match_source"] == "manager"


def test_search_by_company_name(test_client: TestClient, test_session: Session) -> None:
    """P4.3-4：基金公司关键词应命中旗下基金。"""
    _seed_search_universe(test_session)

    response = test_client.get("/api/v1/funds/search", params={"q": "棱镜基金"})

    assert response.status_code == 200
    funds = response.json()["data"]["funds"]
    assert "519001" in [f["fund_code"] for f in funds]


def test_search_by_holding_stock(test_client: TestClient, test_session: Session) -> None:
    """P4.3-4：重仓股名称/代码关键词应命中持有基金。"""
    _seed_search_universe(test_session)

    by_name = test_client.get("/api/v1/funds/search", params={"q": "贵州茅台"})
    assert by_name.status_code == 200
    funds = by_name.json()["data"]["funds"]
    assert [f["fund_code"] for f in funds] == ["519001"]
    assert funds[0]["match_source"] == "holding"

    by_code = test_client.get("/api/v1/funds/search", params={"q": "600519"})
    assert by_code.status_code == 200
    assert by_code.json()["data"]["count"] == 1


def test_search_no_match_returns_observation(
    test_client: TestClient, test_session: Session
) -> None:
    _seed_search_universe(test_session)

    response = test_client.get("/api/v1/funds/search", params={"q": "不存在的关键词"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["count"] == 0
    assert body["conclusion_status"] == "observation"
