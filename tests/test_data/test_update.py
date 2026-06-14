"""Data update workflow tests."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.base import FetchResult
from fund_research.data.update import (
    upsert_akshare_benchmark_index_members,
    upsert_akshare_fund_dividends,
    upsert_akshare_fund_fees,
    upsert_akshare_fund_holdings,
    upsert_akshare_fund_industry_allocation,
    upsert_akshare_fund_info,
    upsert_akshare_fund_managers,
    upsert_akshare_fund_nav,
    upsert_akshare_fund_portfolio_changes,
    upsert_akshare_fund_scale,
    upsert_akshare_holder_structure,
    upsert_akshare_index_daily,
    upsert_akshare_official_pdf_evidence,
    upsert_akshare_stock_daily,
    upsert_akshare_stock_industry_membership,
    upsert_benchmark_industry_weights,
    upsert_local_stock_industry_membership,
    upsert_sample_funds,
)
from fund_research.db.models import (
    BenchmarkIndexMember,
    BenchmarkIndustryWeight,
    DataSourceSnapshot,
    EvidenceRecord,
    FundCompany,
    FundDisclosedHoldings,
    FundFee,
    FundMain,
    FundManager,
    FundManagerTenure,
    FundNAV,
    FundScale,
    HolderStructure,
    StockDaily,
    StockIndustryMembership,
    StyleExposureResult,
    TaskLog,
)
from fund_research.research import official_pdf


class FakeAkshareAdapter:
    """Small fake adapter for update workflow tests."""

    def _result(self, entity_type: str, data: list[dict]) -> FetchResult:
        frame = pd.DataFrame(data)
        return FetchResult(
            source_name="akshare",
            source_type=DataSourceType.OPEN_API,
            source_level=DataSourceLevel.B,
            entity_type=entity_type,
            data=frame,
            record_count=len(frame),
            field_count=len(frame.columns),
            coverage_rate=1.0,
        )

    def fetch_fund_info(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_info",
            [
                {
                    "fund_code": fund_code,
                    "short_name": "华夏成长混合",
                    "full_name": "华夏成长混合证券投资基金",
                    "company_name": "华夏基金",
                    "fund_type_raw": "混合型",
                    "inception_date": "2001-12-18",
                    "benchmark": "沪深300指数收益率",
                }
            ],
        )

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        return self._result(
            "fund_nav",
            [
                {
                    "trade_date": "2024-01-02",
                    "unit_nav": "1.0000",
                    "accumulated_nav": "1.0000",
                    "daily_return": "0.01",
                },
                {
                    "trade_date": "2024-01-03",
                    "unit_nav": "1.0100",
                    "accumulated_nav": "1.0100",
                    "daily_return": "0.02",
                },
            ],
        )

    def fetch_fund_dividends(self, fund_code: str, year: int | None = None) -> FetchResult:
        return self._result(
            "fund_dividends",
            [
                {
                    "fund_code": fund_code,
                    "dividend": "0.05",
                    "dividend_date": "2024-01-03",
                }
            ],
        )

    def fetch_fund_holdings(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        return self._result(
            "fund_holdings",
            [
                {
                    "report_date": "2024-06-30",
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "weight_pct": "8.50",
                    "rank_in_holdings": "1",
                    "market_value": "1000.0",
                    "shares": "10.0",
                }
            ],
        )

    def fetch_fund_industry_allocation(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        return self._result(
            "fund_industry_allocation",
            [
                {
                    "industry_name": "食品饮料",
                    "weight_pct": "13.50",
                    "market_value": "1000.0",
                    "report_date": "2024-06-30",
                },
                {
                    "industry_name": "银行",
                    "weight_pct": "2.00",
                    "market_value": "200.0",
                    "report_date": "2024-06-30",
                },
            ],
        )

    def fetch_fund_portfolio_change(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        return self._result(
            "fund_portfolio_change",
            [
                {
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "cumulative_buy_amount": "100.0",
                    "report_period": "2024年2季度累计买入股票明细",
                }
            ],
        )

    def fetch_fund_managers(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_managers",
            [
                {
                    "manager_id": "m001",
                    "name": "张三",
                    "current_fund_codes": fund_code,
                    "start_date": "2020-01-01",
                    "experience_years": "8年",
                    "education": "硕士",
                }
            ],
        )

    def fetch_fee_detail(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_fee_detail",
            [
                {
                    "mgmt_fee_pct": "1.5%",
                    "custody_fee_pct": "0.25%",
                    "sales_service_fee_pct": "0%",
                    "subscribe_fee_range": "0%-1.5%",
                    "redeem_fee_range": "0%-1.5%",
                    "effective_date": "2024-01-01",
                }
            ],
        )

    def fetch_fund_scale(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_scale",
            [
                {
                    "fund_code": fund_code,
                    "total_nav": "12.50亿元",
                    "total_share": "10.00亿份",
                    "share_change": "0.50亿份",
                }
            ],
        )

    def fetch_holder_structure(self, fund_code: str) -> FetchResult:
        return self._result(
            "holder_structure",
            [
                {
                    "report_date": "2024-06-30",
                    "institutional_pct": "43.54",
                    "individual_pct": "55.85",
                    "employee_pct": "2.0",
                    "total_holders": "10000",
                    "avg_holding": "3.21",
                }
            ],
        )

    def fetch_stock_daily(
        self,
        stock_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        return self._result(
            "stock_daily",
            [
                {
                    "stock_code": stock_code,
                    "trade_date": "2024-01-02",
                    "open_price": "10.0",
                    "high_price": "10.5",
                    "low_price": "9.8",
                    "close_price": "10.2",
                    "volume": "100000",
                    "amount": "1020000",
                    "daily_return": "0.02",
                    "turnover_rate": "1.5",
                }
            ],
        )

    def fetch_index_daily(
        self, symbol: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        return self._result(
            "index_daily",
            [
                {
                    "trade_date": "2024-01-02",
                    "open_price": "3000.0",
                    "high_price": "3010.0",
                    "low_price": "2990.0",
                    "close_price": "3005.0",
                    "daily_return": "0.005",
                }
            ],
        )

    def fetch_index_members_weight(self, symbol: str) -> FetchResult:
        return self._result(
            "benchmark_index_member",
            [
                {
                    "benchmark_symbol": symbol,
                    "index_code": "000300",
                    "index_name": "沪深300",
                    "snapshot_date": "2026-06-01",
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "exchange": "SH",
                    "weight_pct": "5.25",
                },
                {
                    "benchmark_symbol": symbol,
                    "index_code": "000300",
                    "index_name": "沪深300",
                    "snapshot_date": "2026-06-01",
                    "stock_code": "000001",
                    "stock_name": "平安银行",
                    "exchange": "SZ",
                    "weight_pct": "1.50",
                },
            ],
        )

    def fetch_sw_industry_membership(
        self,
        symbols: set[str] | None = None,
        *,
        request_interval_seconds: float = 0.0,
        max_retries: int = 0,
    ) -> FetchResult:
        result = self._result(
            "stock_industry_membership",
            [
                {
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "classification_type": "SW",
                    "classification_version": "2021",
                    "level": 1,
                    "industry_code": "801120",
                    "industry_name": "食品饮料",
                    "parent_industry_code": None,
                    "effective_date": "2026-06-01",
                },
                {
                    "stock_code": "000001",
                    "stock_name": "平安银行",
                    "classification_type": "SW",
                    "classification_version": "2021",
                    "level": 1,
                    "industry_code": "801780",
                    "industry_name": "银行",
                    "parent_industry_code": None,
                    "effective_date": "2026-06-01",
                },
            ],
        )
        result.source_level = DataSourceLevel.C
        return result

    def fetch_announcements(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_announcements",
            [
                {
                    "title": "2024年年度报告",
                    "announcement_date": "2025-03-31",
                    "pdf_url": "https://static.cninfo.com.cn/sample.pdf",
                }
            ],
        )


class BatchedStockIndustryAdapter(FakeAkshareAdapter):
    """Fake adapter that returns symbol-specific stock industry rows."""

    def __init__(self) -> None:
        self.calls: list[set[str]] = []

    def _sw_industry_symbols(self) -> list[str]:
        return ["801120.SI", "801780.SI"]

    def fetch_sw_industry_membership(
        self,
        symbols: set[str] | None = None,
        *,
        request_interval_seconds: float = 0.0,
        max_retries: int = 0,
    ) -> FetchResult:
        selected_symbols = set(symbols or [])
        self.calls.append(selected_symbols)
        rows_by_symbol = {
            "801120.SI": {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "classification_type": "SW",
                "classification_version": "2021",
                "level": 1,
                "industry_code": "801120",
                "industry_name": "食品饮料",
                "parent_industry_code": None,
                "effective_date": "2026-06-01",
            },
            "801780.SI": {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "classification_type": "SW",
                "classification_version": "2021",
                "level": 1,
                "industry_code": "801780",
                "industry_name": "银行",
                "parent_industry_code": None,
                "effective_date": "2026-06-01",
            },
        }
        result = self._result(
            "stock_industry_membership",
            [rows_by_symbol[symbol] for symbol in sorted(selected_symbols)],
        )
        result.source_level = DataSourceLevel.C
        return result


class CachedOnlyStockIndustryAdapter(BatchedStockIndustryAdapter):
    """Fake adapter whose live SW symbol list endpoint is unavailable."""

    def _sw_industry_symbols(self) -> list[str]:
        raise RuntimeError("live endpoint unavailable")


class NoPDFAnnouncementAdapter(FakeAkshareAdapter):
    """Fake adapter with announcements but no PDF link."""

    def fetch_announcements(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_announcements",
            [{"title": "普通公告", "announcement_date": "2025-03-31"}],
        )


class AnomalousNavAdapter(FakeAkshareAdapter):
    """Fake adapter with a suspicious NAV return jump."""

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        return self._result(
            "fund_nav",
            [
                {
                    "trade_date": "2024-01-02",
                    "unit_nav": "1.0000",
                    "daily_return": "0.01",
                },
                {
                    "trade_date": "2024-01-03",
                    "unit_nav": None,
                    "daily_return": "0.25",
                },
            ],
        )


class QuarterTextHoldingsAdapter(FakeAkshareAdapter):
    """Fake adapter with AKShare-style quarter text in holdings rows."""

    def fetch_fund_holdings(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        return self._result(
            "fund_holdings",
            [
                {
                    "report_date": "2026年1季度股票投资明细",
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "weight_pct": "8.50",
                    "rank_in_holdings": "1",
                }
            ],
        )


class MissingManagerStartDateAdapter(FakeAkshareAdapter):
    """Fake adapter matching current AKShare manager rows without start_date."""

    def fetch_fund_managers(self, fund_code: str) -> FetchResult:
        return self._result(
            "fund_managers",
            [
                {
                    "manager_id": "m_current",
                    "name": "张三",
                    "current_fund_codes": fund_code,
                    "experience_years": "3.77",
                }
            ],
        )


class EmptyFeeAdapter(FakeAkshareAdapter):
    """Fake adapter with fee rows that cannot populate canonical fee fields."""

    def fetch_fee_detail(self, fund_code: str) -> FetchResult:
        return self._result("fund_fee_detail", [{"fee_type": "其他费用"}])


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


def _write_sample(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                (
                    "fund_code,short_name,company,expected_style,expected_turnover,"
                    "added_reason,confirmed_turnover,confirmed_turnover_source,"
                    "num_reports_available"
                ),
                "000001,华夏成长混合,华夏基金,均衡,低,测试,pending,pending,8",
                "020005,国泰金马稳健,国泰基金,价值,低,测试,pending,pending,12",
            ]
        ),
        encoding="utf-8",
    )


def test_upsert_sample_funds_dry_run_does_not_write(
    tmp_path: Path, test_session: Session
) -> None:
    """Dry-run should report intended inserts without mutating the database."""
    sample_path = tmp_path / "sample.csv"
    _write_sample(sample_path)

    summary = upsert_sample_funds(test_session, sample_path, dry_run=True)
    fund_count = test_session.scalar(select(func.count()).select_from(FundMain))

    assert summary.inserted == 2
    assert summary.updated == 0
    assert fund_count == 0


def test_upsert_sample_funds_writes_funds_companies_and_logs(
    tmp_path: Path, test_session: Session
) -> None:
    """Sample fund update should populate core tables and operational logs."""
    sample_path = tmp_path / "sample.csv"
    _write_sample(sample_path)

    summary = upsert_sample_funds(test_session, sample_path)
    fund_count = test_session.scalar(select(func.count()).select_from(FundMain))
    company_count = test_session.scalar(select(func.count()).select_from(FundCompany))
    snapshot_count = test_session.scalar(select(func.count()).select_from(DataSourceSnapshot))
    task_count = test_session.scalar(select(func.count()).select_from(TaskLog))

    assert summary.inserted == 2
    assert summary.updated == 0
    assert fund_count == 2
    assert company_count == 2
    assert snapshot_count == 1
    assert task_count == 1


def test_upsert_sample_funds_can_filter_by_fund_code(
    tmp_path: Path, test_session: Session
) -> None:
    """The update workflow should support a focused fund-code subset."""
    sample_path = tmp_path / "sample.csv"
    _write_sample(sample_path)

    summary = upsert_sample_funds(test_session, sample_path, fund_codes={"000001"})
    funds = test_session.scalars(select(FundMain.fund_code)).all()

    assert summary.inserted == 1
    assert funds == ["000001"]


def test_upsert_akshare_fund_info_writes_profile_company_and_snapshot(
    test_session: Session,
) -> None:
    """AKShare fund info update should populate profile fields and logs."""
    summary = upsert_akshare_fund_info(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    fund = test_session.scalar(select(FundMain).where(FundMain.fund_code == "000001"))
    snapshot_count = test_session.scalar(select(func.count()).select_from(DataSourceSnapshot))
    task_count = test_session.scalar(select(func.count()).select_from(TaskLog))

    assert summary.inserted == 1
    assert fund is not None
    assert fund.short_name == "华夏成长混合"
    assert fund.category == "混合型"
    assert fund.inception_date == date(2001, 12, 18)
    assert snapshot_count == 1
    assert task_count == 1


def test_upsert_akshare_fund_nav_writes_unique_nav_rows(test_session: Session) -> None:
    """AKShare NAV update should upsert rows by fund code and trade date."""
    summary = upsert_akshare_fund_nav(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    rows = test_session.scalars(
        select(FundNAV).where(FundNAV.fund_code == "000001").order_by(FundNAV.trade_date)
    ).all()

    assert summary.inserted == 2
    assert len(rows) == 2
    assert rows[0].unit_nav == 1.0
    assert rows[1].daily_return == 0.02


def test_upsert_akshare_fund_nav_snapshot_records_quality_anomaly(
    test_session: Session,
) -> None:
    """NAV update snapshots should include quality check anomaly and coverage data."""
    summary = upsert_akshare_fund_nav(
        test_session,
        {"000001"},
        adapter=AnomalousNavAdapter(),
    )
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(DataSourceSnapshot.entity_type == "fund_nav")
    )

    assert summary.inserted == 2
    assert snapshot is not None
    assert snapshot.anomaly_count == 1
    assert snapshot.missing_fields == {"unit_nav": 1}
    assert snapshot.coverage_rate == 5 / 6


def test_upsert_akshare_fund_dividends_writes_nav_dividend_rows(
    test_session: Session,
) -> None:
    """AKShare dividend update should populate dividend fields on fund_nav."""
    summary = upsert_akshare_fund_dividends(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
        year=2024,
    )
    row = test_session.scalar(
        select(FundNAV)
        .where(FundNAV.fund_code == "000001")
        .where(FundNAV.trade_date == date(2024, 1, 3))
    )
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(DataSourceSnapshot.entity_type == "fund_dividends")
    )
    task = test_session.scalar(select(TaskLog).where(TaskLog.target_entity == "fund_dividends"))

    assert summary.inserted == 1
    assert row is not None
    assert row.dividend == 0.05
    assert row.data_source_level == DataSourceLevel.B.value
    assert snapshot is not None
    assert task is not None


def test_upsert_akshare_fund_holdings_writes_disclosed_holdings(
    test_session: Session,
) -> None:
    """AKShare holding update should upsert disclosed stock holdings."""
    summary = upsert_akshare_fund_holdings(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
        report_date=date(2024, 6, 30),
    )
    holding = test_session.scalar(
        select(FundDisclosedHoldings).where(
            FundDisclosedHoldings.fund_code == "000001"
        )
    )

    assert summary.inserted == 1
    assert holding is not None
    assert holding.security_code == "600519"
    assert holding.security_name == "贵州茅台"
    assert holding.report_date == date(2024, 6, 30)
    assert holding.weight_pct == 8.5
    assert holding.rank_in_holdings == 1


def test_upsert_akshare_fund_holdings_parses_quarter_text_report_date(
    test_session: Session,
) -> None:
    """Holdings update should parse AKShare quarter text report periods."""
    summary = upsert_akshare_fund_holdings(
        test_session,
        {"000001"},
        adapter=QuarterTextHoldingsAdapter(),
    )
    holding = test_session.scalar(
        select(FundDisclosedHoldings).where(FundDisclosedHoldings.fund_code == "000001")
    )

    assert summary.inserted == 1
    assert holding is not None
    assert holding.report_date == date(2026, 3, 31)


def test_upsert_akshare_fund_industry_allocation_writes_observation_result(
    test_session: Session,
) -> None:
    """AKShare industry allocation should persist as an industry exposure observation."""
    summary = upsert_akshare_fund_industry_allocation(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    result = test_session.scalar(
        select(StyleExposureResult).where(
            StyleExposureResult.algorithm_name == "disclosed_industry_allocation"
        )
    )
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(
            DataSourceSnapshot.entity_type == "fund_industry_allocation"
        )
    )

    assert summary.inserted == 1
    assert result is not None
    assert result.exposure_type == "industry"
    assert result.exposure_values == {"食品饮料": 13.5, "银行": 2.0}
    assert result.conclusion_status == "observation"
    assert snapshot is not None


def test_upsert_akshare_fund_portfolio_changes_marks_matching_holding(
    test_session: Session,
) -> None:
    """Portfolio change rows should annotate matching disclosed holdings only."""
    test_session.add(
        FundDisclosedHoldings(
            fund_code="000001",
            report_date=date(2024, 6, 30),
            asset_type="股票",
            security_code="600519",
            security_name="贵州茅台",
            weight_pct=8.5,
            data_source_level=DataSourceLevel.LOCAL.value,
        )
    )
    test_session.commit()

    summary = upsert_akshare_fund_portfolio_changes(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    holding = test_session.scalar(
        select(FundDisclosedHoldings).where(FundDisclosedHoldings.security_code == "600519")
    )
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(DataSourceSnapshot.entity_type == "fund_portfolio_change")
    )

    assert summary.updated == 1
    assert holding is not None
    assert holding.change_direction == "buy"
    assert snapshot is not None


def test_upsert_akshare_fund_managers_writes_manager_and_tenure(
    test_session: Session,
) -> None:
    """AKShare manager update should populate manager and tenure tables."""
    summary = upsert_akshare_fund_managers(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    manager = test_session.scalar(select(FundManager).where(FundManager.manager_id == "m001"))
    tenure = test_session.scalar(
        select(FundManagerTenure).where(FundManagerTenure.fund_code == "000001")
    )

    assert summary.inserted == 1
    assert manager is not None
    assert manager.name == "张三"
    assert manager.experience_years == 8.0
    assert tenure is not None
    assert tenure.start_date == date(2020, 1, 1)
    assert tenure.is_current is True


def test_upsert_akshare_fund_managers_allows_missing_start_date(
    test_session: Session,
) -> None:
    """Current manager snapshots without start_date should still populate managers."""
    summary = upsert_akshare_fund_managers(
        test_session,
        {"000001"},
        adapter=MissingManagerStartDateAdapter(),
    )
    manager = test_session.scalar(
        select(FundManager).where(FundManager.manager_id == "m_current")
    )
    tenure = test_session.scalar(
        select(FundManagerTenure).where(FundManagerTenure.fund_code == "000001")
    )

    assert summary.inserted == 1
    assert any("start_date 使用抓取日期" in warning for warning in summary.warnings)
    assert manager is not None
    assert manager.experience_years == 3.77
    assert tenure is not None
    assert tenure.start_date == date.today()
    assert tenure.is_current is True


def test_upsert_akshare_fund_fees_writes_fee_detail(test_session: Session) -> None:
    """AKShare fee detail update should populate fund_fee."""
    summary = upsert_akshare_fund_fees(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    fee = test_session.scalar(select(FundFee).where(FundFee.fund_code == "000001"))

    assert summary.inserted == 1
    assert fee is not None
    assert fee.mgmt_fee_pct == 1.5
    assert fee.custody_fee_pct == 0.25
    assert fee.sales_service_fee_pct == 0.0
    assert fee.effective_date == date(2024, 1, 1)


def test_upsert_akshare_fund_fees_skips_empty_fee_payload(test_session: Session) -> None:
    """Fee update should not persist rows with all canonical fee fields empty."""
    summary = upsert_akshare_fund_fees(
        test_session,
        {"000001"},
        adapter=EmptyFeeAdapter(),
    )
    fee_count = test_session.scalar(select(func.count()).select_from(FundFee))

    assert summary.skipped == 1
    assert fee_count == 0
    assert any("基金费率字段缺失" in warning for warning in summary.warnings)


def test_upsert_akshare_fund_scale_writes_latest_scale_snapshot(
    test_session: Session,
) -> None:
    """AKShare scale update should populate fund_scale with a snapshot date."""
    summary = upsert_akshare_fund_scale(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    scale = test_session.scalar(select(FundScale).where(FundScale.fund_code == "000001"))

    assert summary.inserted == 1
    assert "最新规模快照" in summary.warnings[0]
    assert scale is not None
    assert scale.total_nav == 12.5
    assert scale.total_share == 10.0
    assert scale.share_change == 0.5


def test_upsert_akshare_holder_structure_writes_holder_rows(
    test_session: Session,
) -> None:
    """AKShare holder structure update should populate holder_structure."""
    summary = upsert_akshare_holder_structure(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
    )
    holder = test_session.scalar(
        select(HolderStructure).where(HolderStructure.fund_code == "000001")
    )

    assert summary.inserted == 1
    assert holder is not None
    assert holder.report_date == date(2024, 6, 30)
    assert holder.institutional_pct == 43.54
    assert holder.individual_pct == 55.85
    assert holder.employee_pct == 2.0
    assert holder.total_holders == 10000
    assert holder.avg_holding == 3.21


def test_upsert_akshare_stock_daily_writes_stock_prices(test_session: Session) -> None:
    """AKShare stock daily update should upsert stock price rows."""
    summary = upsert_akshare_stock_daily(
        test_session,
        {"600519"},
        adapter=FakeAkshareAdapter(),
    )
    row = test_session.scalar(
        select(StockDaily)
        .where(StockDaily.stock_code == "600519")
        .where(StockDaily.trade_date == date(2024, 1, 2))
    )

    assert summary.inserted == 1
    assert row is not None
    assert row.close_price == 10.2
    assert row.daily_return == 0.02
    assert row.turnover_rate == 1.5


def test_upsert_akshare_index_daily_writes_index_prices(test_session: Session) -> None:
    """AKShare index daily update should store style index rows in stock_daily."""
    summary = upsert_akshare_index_daily(
        test_session,
        {"sh000300"},
        adapter=FakeAkshareAdapter(),
    )
    row = test_session.scalar(
        select(StockDaily)
        .where(StockDaily.stock_code == "sh000300")
        .where(StockDaily.trade_date == date(2024, 1, 2))
    )

    assert summary.inserted == 1
    assert row is not None
    assert row.close_price == 3005.0
    assert row.daily_return == 0.005


def test_upsert_akshare_index_daily_passes_date_window(test_session: Session) -> None:
    """Index updates should forward date windows to the data adapter."""

    class TrackingIndexAdapter(FakeAkshareAdapter):
        seen_start: date | None = None
        seen_end: date | None = None

        def fetch_index_daily(
            self, symbol: str, start_date: date | None = None, end_date: date | None = None
        ) -> FetchResult:
            self.seen_start = start_date
            self.seen_end = end_date
            return super().fetch_index_daily(symbol, start_date=start_date, end_date=end_date)

    adapter = TrackingIndexAdapter()

    summary = upsert_akshare_index_daily(
        test_session,
        {"sh000300"},
        adapter=adapter,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )

    assert summary.inserted == 1
    assert adapter.seen_start == date(2024, 1, 1)
    assert adapter.seen_end == date(2024, 1, 31)


def test_upsert_akshare_benchmark_index_members_writes_weight_snapshots(
    test_session: Session,
) -> None:
    """Benchmark member updates should upsert CSIndex constituent weights."""
    adapter = FakeAkshareAdapter()

    summary = upsert_akshare_benchmark_index_members(
        test_session,
        {"sh000300"},
        adapter=adapter,
    )
    rows = test_session.scalars(
        select(BenchmarkIndexMember).order_by(BenchmarkIndexMember.stock_code)
    ).all()
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(DataSourceSnapshot.entity_type == "benchmark_index_member")
    )

    assert summary.inserted == 2
    assert len(rows) == 2
    assert rows[0].benchmark_symbol == "sh000300"
    assert rows[0].snapshot_date == date(2026, 6, 1)
    assert rows[0].source_name == "akshare.index_stock_cons_weight_csindex"
    assert rows[0].source_level == DataSourceLevel.B.value
    assert rows[1].stock_code == "600519"
    assert rows[1].weight_pct == 5.25
    assert snapshot is not None

    second = upsert_akshare_benchmark_index_members(
        test_session,
        {"sh000300"},
        adapter=adapter,
    )
    row_count = test_session.scalar(select(func.count()).select_from(BenchmarkIndexMember))
    assert second.updated == 2
    assert row_count == 2


def test_upsert_akshare_stock_industry_membership_writes_sw_level_one_rows(
    test_session: Session,
) -> None:
    """Stock industry membership updates should persist SW level-one snapshots."""
    adapter = FakeAkshareAdapter()

    summary = upsert_akshare_stock_industry_membership(
        test_session,
        {"801120.SI"},
        adapter=adapter,
    )
    rows = test_session.scalars(
        select(StockIndustryMembership).order_by(StockIndustryMembership.stock_code)
    ).all()
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(
            DataSourceSnapshot.entity_type == "stock_industry_membership"
        )
    )

    assert summary.inserted == 2
    assert len(rows) == 2
    assert rows[0].stock_code == "000001"
    assert rows[0].classification_type == "SW"
    assert rows[0].level == 1
    assert rows[0].industry_name == "银行"
    assert rows[0].source_level == DataSourceLevel.C.value
    assert rows[1].industry_name == "食品饮料"
    assert snapshot is not None

    second = upsert_akshare_stock_industry_membership(
        test_session,
        {"801120.SI"},
        adapter=adapter,
    )
    row_count = test_session.scalar(select(func.count()).select_from(StockIndustryMembership))
    assert second.updated == 2
    assert row_count == 2


def test_upsert_akshare_stock_industry_membership_batches_and_caches_symbols(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """Full stock-industry updates should batch commits and cache the SW symbol list."""
    adapter = BatchedStockIndustryAdapter()

    summary = upsert_akshare_stock_industry_membership(
        test_session,
        None,
        adapter=adapter,
        industry_batch_size=1,
        symbol_cache_dir=tmp_path,
    )
    rows = test_session.scalars(
        select(StockIndustryMembership).order_by(StockIndustryMembership.stock_code)
    ).all()
    cache_path = tmp_path / "stock_industry" / "sw_level_one_symbols.json"

    assert summary.requested == 2
    assert summary.inserted == 2
    assert adapter.calls == [{"801120.SI"}, {"801780.SI"}]
    assert len(rows) == 2
    assert cache_path.exists()
    assert "801120.SI" in cache_path.read_text(encoding="utf-8")
    assert "801780.SI" in cache_path.read_text(encoding="utf-8")


def test_upsert_akshare_stock_industry_membership_uses_cached_symbols_on_live_failure(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """A cached SW symbol list should let stock-industry resume when live listing fails."""
    cache_path = tmp_path / "stock_industry" / "sw_level_one_symbols.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        '{"symbols": ["801120.SI"], "source": "test"}',
        encoding="utf-8",
    )
    adapter = CachedOnlyStockIndustryAdapter()

    summary = upsert_akshare_stock_industry_membership(
        test_session,
        None,
        adapter=adapter,
        industry_batch_size=1,
        symbol_cache_dir=tmp_path,
    )

    assert summary.requested == 1
    assert summary.inserted == 1
    assert adapter.calls == [{"801120.SI"}]
    assert any("使用本地缓存" in warning for warning in summary.warnings or [])


def test_upsert_local_stock_industry_membership_imports_csv_and_cleans_codes(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """Local stock-industry files should import auditable SW level-one mappings."""
    industry_file = tmp_path / "stock_industry_sw.csv"
    industry_file.write_text(
        "\n".join([
            "stock_code,stock_name,industry_name,effective_date,source_name",
            "600519.SH,贵州茅台,食品饮料,2026-06-01,manual_sw_sample",
            "000001.SZ,平安银行,银行,2026-06-01,manual_sw_sample",
        ]),
        encoding="utf-8",
    )

    summary = upsert_local_stock_industry_membership(test_session, industry_file)
    rows = test_session.scalars(
        select(StockIndustryMembership).order_by(StockIndustryMembership.stock_code)
    ).all()
    snapshot = test_session.scalar(
        select(DataSourceSnapshot).where(
            DataSourceSnapshot.entity_type == "stock_industry_membership"
        )
    )

    assert summary.requested == 2
    assert summary.inserted == 2
    assert summary.warnings == []
    assert [row.stock_code for row in rows] == ["000001", "600519"]
    assert rows[0].source_name == "manual_sw_sample"
    assert rows[0].source_level == DataSourceLevel.LOCAL.value
    assert snapshot is not None
    assert snapshot.source_type == DataSourceType.LOCAL_FILE.value


def test_upsert_local_stock_industry_membership_reimport_updates_existing_rows(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """Re-importing the same local industry file should update instead of duplicating."""
    industry_file = tmp_path / "stock_industry_sw.csv"
    industry_file.write_text(
        "\n".join([
            "stock_code,stock_name,industry_name,effective_date",
            "600519.SH,贵州茅台,食品饮料,2026-06-01",
        ]),
        encoding="utf-8",
    )

    first = upsert_local_stock_industry_membership(test_session, industry_file)
    second = upsert_local_stock_industry_membership(test_session, industry_file)
    row_count = test_session.scalar(select(func.count()).select_from(StockIndustryMembership))

    assert first.inserted == 1
    assert second.updated == 1
    assert row_count == 1


def test_upsert_local_stock_industry_membership_imports_xlsx(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """Local stock-industry imports should also accept XLSX mapping files."""
    industry_file = tmp_path / "stock_industry_sw.xlsx"
    pd.DataFrame([{
        "stock_code": "000001.SZ",
        "stock_name": "平安银行",
        "industry_name": "银行",
        "effective_date": "2026-06-01",
    }]).to_excel(industry_file, index=False)

    summary = upsert_local_stock_industry_membership(test_session, industry_file)
    row = test_session.scalar(select(StockIndustryMembership))

    assert summary.inserted == 1
    assert row is not None
    assert row.stock_code == "000001"
    assert row.industry_name == "银行"


def test_upsert_local_stock_industry_membership_warns_for_missing_required_columns(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """Rows without stock code or industry name should be skipped with warnings."""
    industry_file = tmp_path / "bad_stock_industry_sw.csv"
    industry_file.write_text(
        "\n".join([
            "stock_code,stock_name,effective_date",
            "600519.SH,贵州茅台,2026-06-01",
        ]),
        encoding="utf-8",
    )

    summary = upsert_local_stock_industry_membership(test_session, industry_file)
    row_count = test_session.scalar(select(func.count()).select_from(StockIndustryMembership))

    assert summary.requested == 1
    assert summary.skipped == 1
    assert row_count == 0
    assert any("缺少必要字段" in warning for warning in summary.warnings or [])


def test_upsert_benchmark_industry_weights_aggregates_member_weights(
    test_session: Session,
) -> None:
    """Benchmark industry aggregation should sum member weights by latest industry snapshot."""
    snapshot_date = date(2026, 6, 1)
    test_session.add_all([
        BenchmarkIndexMember(
            benchmark_symbol="sh000300",
            index_code="000300",
            index_name="沪深300",
            snapshot_date=snapshot_date,
            stock_code="600519",
            stock_name="贵州茅台",
            exchange="SH",
            weight_pct=50.0,
            source_name="akshare.index_stock_cons_weight_csindex",
            source_level=DataSourceLevel.B.value,
        ),
        BenchmarkIndexMember(
            benchmark_symbol="sh000300",
            index_code="000300",
            index_name="沪深300",
            snapshot_date=snapshot_date,
            stock_code="000001",
            stock_name="平安银行",
            exchange="SZ",
            weight_pct=30.0,
            source_name="akshare.index_stock_cons_weight_csindex",
            source_level=DataSourceLevel.B.value,
        ),
        BenchmarkIndexMember(
            benchmark_symbol="sh000300",
            index_code="000300",
            index_name="沪深300",
            snapshot_date=snapshot_date,
            stock_code="000002",
            stock_name="万科A",
            exchange="SZ",
            weight_pct=20.0,
            source_name="akshare.index_stock_cons_weight_csindex",
            source_level=DataSourceLevel.B.value,
        ),
        StockIndustryMembership(
            stock_code="600519",
            stock_name="贵州茅台",
            classification_type="SW",
            classification_version="2021",
            level=1,
            industry_code="801120",
            industry_name="食品饮料",
            effective_date=snapshot_date,
            source_name="akshare.sw_index_third_cons",
            source_level=DataSourceLevel.C.value,
        ),
        StockIndustryMembership(
            stock_code="000001",
            stock_name="平安银行",
            classification_type="SW",
            classification_version="2021",
            level=1,
            industry_code="801780",
            industry_name="银行",
            effective_date=snapshot_date,
            source_name="akshare.sw_index_third_cons",
            source_level=DataSourceLevel.C.value,
        ),
        StockIndustryMembership(
            stock_code="000002",
            stock_name="万科A",
            classification_type="SW",
            classification_version="2021",
            level=1,
            industry_code="801780",
            industry_name="银行",
            effective_date=snapshot_date,
            source_name="akshare.sw_index_third_cons",
            source_level=DataSourceLevel.C.value,
        ),
    ])
    test_session.commit()

    summary = upsert_benchmark_industry_weights(
        test_session,
        {"sh000300"},
        target_date=snapshot_date,
    )
    rows = test_session.scalars(
        select(BenchmarkIndustryWeight).order_by(BenchmarkIndustryWeight.industry_name)
    ).all()

    assert summary.inserted == 2
    assert {row.industry_name: row.weight_pct for row in rows} == {
        "食品饮料": 50.0,
        "银行": 50.0,
    }
    assert all(row.coverage_pct == 100.0 for row in rows)
    assert all(row.unmapped_weight_pct == 0.0 for row in rows)
    assert all(row.warnings is None for row in rows)

    second = upsert_benchmark_industry_weights(
        test_session,
        {"sh000300"},
        target_date=snapshot_date,
    )
    row_count = test_session.scalar(select(func.count()).select_from(BenchmarkIndustryWeight))
    assert second.updated == 2
    assert row_count == 2


def test_upsert_benchmark_industry_weights_warns_on_low_mapping_coverage(
    test_session: Session,
) -> None:
    """Low industry mapping coverage should be persisted as warnings for later gating."""
    snapshot_date = date(2026, 6, 1)
    test_session.add_all([
        BenchmarkIndexMember(
            benchmark_symbol="sh000300",
            index_code="000300",
            snapshot_date=snapshot_date,
            stock_code="600519",
            weight_pct=80.0,
            source_name="akshare.index_stock_cons_weight_csindex",
            source_level=DataSourceLevel.B.value,
        ),
        BenchmarkIndexMember(
            benchmark_symbol="sh000300",
            index_code="000300",
            snapshot_date=snapshot_date,
            stock_code="000001",
            weight_pct=20.0,
            source_name="akshare.index_stock_cons_weight_csindex",
            source_level=DataSourceLevel.B.value,
        ),
        StockIndustryMembership(
            stock_code="600519",
            classification_type="SW",
            level=1,
            industry_name="食品饮料",
            effective_date=snapshot_date,
            source_name="akshare.sw_index_third_cons",
            source_level=DataSourceLevel.C.value,
        ),
    ])
    test_session.commit()

    summary = upsert_benchmark_industry_weights(
        test_session,
        {"sh000300"},
        target_date=snapshot_date,
    )
    row = test_session.scalar(select(BenchmarkIndustryWeight))

    assert summary.inserted == 1
    assert any("覆盖率不足" in warning for warning in summary.warnings)
    assert row is not None
    assert row.weight_pct == 100.0
    assert row.coverage_pct == 80.0
    assert row.unmapped_weight_pct == 20.0
    assert row.warnings is not None
    assert "行业映射覆盖率低于门槛" in row.warnings["items"][0]


def test_upsert_akshare_official_pdf_evidence_writes_evidence(
    test_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Official PDF update should persist A-level evidence when download succeeds."""
    content = b"%PDF-1.4\n/Type /Page\nfund report\n%%EOF"

    def fake_get(url: str, timeout: float) -> _FakeResponse:
        return _FakeResponse(content)

    monkeypatch.setattr(official_pdf.httpx, "get", fake_get)

    summary = upsert_akshare_official_pdf_evidence(
        test_session,
        {"000001"},
        adapter=FakeAkshareAdapter(),
        cache_dir=tmp_path,
    )
    evidence = test_session.scalar(
        select(EvidenceRecord).where(EvidenceRecord.source == "official_pdf")
    )
    snapshot_count = test_session.scalar(select(func.count()).select_from(DataSourceSnapshot))
    task = test_session.scalar(
        select(TaskLog).where(TaskLog.target_entity == "official_pdf_evidence")
    )

    assert summary.inserted == 1
    assert evidence is not None
    assert evidence.source_level == DataSourceLevel.A.value
    assert evidence.conclusion_status == "fact"
    assert snapshot_count == 1
    assert task is not None


def test_upsert_akshare_official_pdf_evidence_skips_missing_pdf_url(
    test_session: Session,
    tmp_path: Path,
) -> None:
    """Missing official PDFs should skip evidence instead of fabricating A-level records."""
    summary = upsert_akshare_official_pdf_evidence(
        test_session,
        {"000001"},
        adapter=NoPDFAnnouncementAdapter(),
        cache_dir=tmp_path,
    )
    evidence_count = test_session.scalar(select(func.count()).select_from(EvidenceRecord))

    assert summary.inserted == 0
    assert summary.skipped == 1
    assert "未找到 PDF 链接" in summary.warnings[0]
    assert evidence_count == 0
