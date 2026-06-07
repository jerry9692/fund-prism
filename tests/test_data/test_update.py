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
    upsert_sample_funds,
)
from fund_research.db.models import (
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
