"""P4.1-4 ETF 产品属性测试 — etf_profile + 跟踪误差本地计算."""

import types
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.akshare import (
    AkshareAdapter,
    resolve_tracking_index_symbol,
)
from fund_research.data.adapters.base import FetchResult
from fund_research.data.update import (
    compute_etf_tracking_stats,
    sample_etf_codes,
    upsert_etf_profiles,
)
from fund_research.db.models import EtfProfile, FundMain, FundNAV, StockDaily

# ============================================================
# 跟踪指数解析
# ============================================================


@pytest.mark.parametrize(
    ("index_name", "expected"),
    [
        ("沪深300指数", "sh000300"),
        ("沪深300", "sh000300"),
        ("中证500指数", "sh000905"),
        ("创业板指", "sz399006"),
        ("上证50指数", "sh000016"),
        ("中证红利指数", "sh000922"),
    ],
)
def test_resolve_tracking_index_symbol(index_name: str, expected: str) -> None:
    assert resolve_tracking_index_symbol(index_name) == expected


def test_resolve_tracking_index_symbol_unknown() -> None:
    assert resolve_tracking_index_symbol("某某神秘指数") is None
    assert resolve_tracking_index_symbol(None) is None


# ============================================================
# 适配器标准化
# ============================================================


def _fake_etf_ak() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        fund_etf_spot_em=lambda: pd.DataFrame(
            [
                {
                    "代码": "510300",
                    "名称": "沪深300ETF华泰柏瑞",
                    "最新价": 4.726,
                    "IOPV实时估值": 4.728,
                    "基金折价率": 0.04,
                    "成交量": 6859530,
                    "成交额": 3.24e9,
                    "换手率": 2.92,
                    "最新份额": 2.48e10,
                    "总市值": 1.17e11,
                    "数据日期": "2026-08-15",
                },
            ]
        ),
        fund_etf_hist_em=lambda symbol, period, start_date, end_date, adjust: pd.DataFrame(
            [
                {"日期": "2026-08-13", "收盘": 4.729, "成交额": 4.36e9, "换手率": 3.90},
                {"日期": "2026-08-14", "收盘": 4.726, "成交额": 3.24e9, "换手率": 2.92},
            ]
        ),
    )


def test_fetch_etf_spot_standardizes_premium_sign() -> None:
    adapter = AkshareAdapter(ak_module=_fake_etf_ak())

    result = adapter.fetch_etf_spot()

    assert result.is_success is True
    assert result.entity_type == "etf_profile"
    row = result.data.iloc[0]
    assert row["fund_code"] == "510300"
    # 东财折价率 0.04（正=折价）→ 溢折率 -0.04（负=折价）
    assert row["latest_premium_rate"] == pytest.approx(-0.04)
    assert row["snapshot_date"] == "2026-08-15"
    assert row["extra"]["market_cap"] == pytest.approx(1.17e11)


def test_fetch_etf_daily_hist_standardizes_rows() -> None:
    adapter = AkshareAdapter(ak_module=_fake_etf_ak())

    result = adapter.fetch_etf_daily_hist("510300", date(2025, 8, 15), date(2026, 8, 15))

    assert result.is_success is True
    assert len(result.data) == 2
    row = result.data.iloc[0]
    assert row["fund_code"] == "510300"
    assert row["trade_date"] == "2026-08-13"
    assert row["amount"] == pytest.approx(4.36e9)
    assert row["turnover_rate_pct"] == pytest.approx(3.90)


def test_fetch_etf_daily_hist_falls_back_to_sina(monkeypatch: pytest.MonkeyPatch) -> None:
    """东财行情失败时应回退新浪源（无换手率，窗口本地过滤）。"""

    def broken_em(**kwargs):
        raise ConnectionError("Remote end closed connection")

    fake_ak = types.SimpleNamespace(
        fund_etf_hist_em=broken_em,
        fund_etf_hist_sina=lambda symbol: pd.DataFrame(
            [
                {"date": "2025-01-01", "close": 4.0, "amount": 1.0e9},
                {"date": "2026-08-13", "close": 4.7, "amount": 4.36e9},
                {"date": "2026-08-14", "close": 4.71, "amount": 3.24e9},
            ]
        ),
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_etf_daily_hist("510300", date(2025, 8, 15), date(2026, 8, 15))

    assert result.is_success is True
    assert result.source_name == "akshare.fund_etf_hist_sina"
    # 窗口外（2025-01-01）被过滤
    assert len(result.data) == 2
    assert result.data["turnover_rate_pct"].isna().all()
    assert any("回退新浪源" in warning for warning in result.warnings)


def test_fetch_etf_f10_profile_parses_tracking_and_fees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fund_research.data.adapters.akshare as akshare_module

    html = (
        "<label>成立日期：<span>2012-05-04</span></label>"
        "<tr><th>跟踪标的</th><td>沪深300指数</td></tr>"
        "<tr><th>管理费率</th><td>0.15%（每年）</td></tr>"
        "<tr><th>托管费率</th><td>0.05%（每年）</td></tr>"
    )

    class FakeResponse:
        status_code = 200
        text = html
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        akshare_module.requests, "get", lambda *args, **kwargs: FakeResponse()
    )
    adapter = AkshareAdapter(ak_module=_fake_etf_ak())

    result = adapter.fetch_etf_f10_profile("510300")

    assert result.is_success is True
    row = result.data.iloc[0]
    assert row["fund_code"] == "510300"
    assert row["tracking_index_name"] == "沪深300指数"
    assert row["tracking_index_code"] == "sh000300"
    assert row["inception_date"] == "2012-05-04"
    assert row["mgmt_fee_pct"] == pytest.approx(0.15)
    assert row["custody_fee_pct"] == pytest.approx(0.05)


# ============================================================
# 跟踪误差本地计算
# ============================================================


def _seed_tracking_data(
    session: Session,
    fund_code: str,
    index_symbol: str,
    days: int = 300,
    start: date = date(2025, 1, 1),
) -> tuple[list[float], list[float]]:
    fund_returns = [0.002 if i % 2 == 0 else -0.001 for i in range(days)]
    index_returns = [0.0005] * days
    session.add_all(
        [
            FundNAV(
                fund_code=fund_code,
                trade_date=start + timedelta(days=i),
                unit_nav=1.0,
                daily_return=fund_returns[i],
            )
            for i in range(days)
        ]
    )
    session.add_all(
        [
            StockDaily(
                stock_code=index_symbol,
                trade_date=start + timedelta(days=i),
                close_price=1000.0,
                daily_return=index_returns[i],
            )
            for i in range(days)
        ]
    )
    session.commit()
    return fund_returns, index_returns


def test_compute_etf_tracking_stats_windows(test_session: Session) -> None:
    fund_returns, index_returns = _seed_tracking_data(test_session, "510300", "sh000300")

    stats = compute_etf_tracking_stats(test_session, "510300", "sh000300")

    assert stats is not None
    excess = np.array(fund_returns) - np.array(index_returns)
    # 成立以来窗口 = 全量 300 天
    assert stats["inception_observations"] == 300
    assert stats["tracking_error_inception"] == pytest.approx(
        float(np.std(excess, ddof=1) * np.sqrt(252))
    )
    expected_excess_inception = (1.0 + excess.sum()) ** (252.0 / len(excess)) - 1.0
    assert stats["annualized_excess_inception"] == pytest.approx(expected_excess_inception)
    # 近一年窗口 = 最近 252 天
    recent = excess[-252:]
    assert stats["recent_observations"] == 252
    assert stats["tracking_error_1y"] == pytest.approx(
        float(np.std(recent, ddof=1) * np.sqrt(252))
    )


def test_compute_etf_tracking_stats_insufficient(test_session: Session) -> None:
    _seed_tracking_data(test_session, "510300", "sh000300", days=10)

    assert compute_etf_tracking_stats(test_session, "510300", "sh000300") is None


def test_compute_etf_tracking_stats_falls_back_to_close_price(test_session: Session) -> None:
    """指数行情 daily_return 为空（腾讯源）时应由收盘价 pct_change 推导。"""
    start = date(2025, 1, 1)
    days = 60
    session = test_session
    session.add_all(
        [
            FundNAV(
                fund_code="510500",
                trade_date=start + timedelta(days=i),
                unit_nav=1.0,
                daily_return=0.001,
            )
            for i in range(days)
        ]
    )
    session.add_all(
        [
            StockDaily(
                stock_code="sh000905",
                trade_date=start + timedelta(days=i),
                close_price=1000.0 * (1.0005**i),
                daily_return=None,
            )
            for i in range(days)
        ]
    )
    session.commit()

    stats = compute_etf_tracking_stats(session, "510500", "sh000905")

    assert stats is not None
    # 首日 pct_change 为 NaN，对齐样本 = 60 - 1
    assert stats["inception_observations"] == days - 1
    assert stats["tracking_error_inception"] is not None


# ============================================================
# update 工作流
# ============================================================


class FakeEtfAdapter:
    """Fake adapter for P4.1-4 update workflow tests."""

    def __init__(self, *, premium_pct: float | None = 0.04) -> None:
        self.premium_pct = premium_pct
        self.hist_seen: list[str] = []
        self.f10_seen: list[str] = []

    def _result(self, data: list[dict]) -> FetchResult:
        frame = pd.DataFrame(data)
        return FetchResult(
            source_name="akshare",
            source_type=DataSourceType.OPEN_API,
            source_level=DataSourceLevel.B,
            entity_type="etf_profile",
            data=frame,
            record_count=len(frame),
            field_count=len(frame.columns) if not frame.empty else 0,
            coverage_rate=1.0,
        )

    def fetch_etf_spot(self) -> FetchResult:
        if self.premium_pct is None:
            return self._result([])
        return self._result(
            [
                {
                    "fund_code": "510300",
                    "fund_name": "沪深300ETF华泰柏瑞",
                    "latest_premium_rate": -self.premium_pct,
                    "snapshot_date": "2026-08-15",
                    "extra": {"market_cap": 1.17e11},
                }
            ]
        )

    def fetch_etf_daily_hist(
        self, symbol: str, start_date: date, end_date: date
    ) -> FetchResult:
        self.hist_seen.append(symbol)
        return self._result(
            [
                {
                    "fund_code": symbol,
                    "trade_date": "2026-08-13",
                    "close_price": 4.729,
                    "amount": 4.36e9,
                    "turnover_rate_pct": 3.90,
                },
                {
                    "fund_code": symbol,
                    "trade_date": "2026-08-14",
                    "close_price": 4.726,
                    "amount": 3.24e9,
                    "turnover_rate_pct": 2.92,
                },
            ]
        )

    def fetch_etf_f10_profile(self, fund_code: str) -> FetchResult:
        self.f10_seen.append(fund_code)
        return self._result(
            [
                {
                    "fund_code": fund_code,
                    "tracking_index_name": "沪深300指数",
                    "tracking_index_code": "sh000300",
                    "inception_date": "2012-05-04",
                    "mgmt_fee_pct": 0.15,
                    "custody_fee_pct": 0.05,
                }
            ]
        )


def test_upsert_etf_profiles_full_pipeline(test_session: Session) -> None:
    _seed_tracking_data(test_session, "510300", "sh000300")
    adapter = FakeEtfAdapter()

    summary = upsert_etf_profiles(
        test_session, {"510300"}, adapter=adapter, end_date=date(2026, 8, 15)
    )

    assert summary.inserted == 1
    assert adapter.hist_seen == ["510300"]
    assert adapter.f10_seen == ["510300"]
    row = test_session.scalar(select(EtfProfile))
    assert row is not None
    assert row.fund_code == "510300"
    assert row.fund_name == "沪深300ETF华泰柏瑞"
    assert row.tracking_index_code == "sh000300"
    assert row.tracking_index_name == "沪深300指数"
    assert row.inception_date == date(2012, 5, 4)
    assert row.avg_daily_amount_1y == pytest.approx((4.36e9 + 3.24e9) / 2)
    assert row.avg_daily_turnover_1y == pytest.approx((3.90 + 2.92) / 2)
    assert row.latest_premium_rate == pytest.approx(-0.04)
    assert row.snapshot_date == date(2026, 8, 15)
    # 跟踪误差本地计算（与种子数据 300 天一致）
    assert row.tracking_error_inception is not None
    assert row.tracking_error_1y is not None
    assert row.annualized_excess_inception is not None
    assert row.extra["inception_observations"] == 300
    # F10 费率快照（雪球源不支持场内 ETF 费率）
    assert row.extra["mgmt_fee_pct"] == pytest.approx(0.15)
    assert row.extra["custody_fee_pct"] == pytest.approx(0.05)


def test_upsert_etf_profiles_is_idempotent_and_coalesces(test_session: Session) -> None:
    _seed_tracking_data(test_session, "510300", "sh000300")
    first = upsert_etf_profiles(
        test_session, {"510300"}, adapter=FakeEtfAdapter(), end_date=date(2026, 8, 15)
    )
    test_session.commit()
    # 第二次快照缺失溢折率（盘前），旧值应保留
    second = upsert_etf_profiles(
        test_session,
        {"510300"},
        adapter=FakeEtfAdapter(premium_pct=None),
        end_date=date(2026, 8, 15),
    )

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.updated == 1
    row = test_session.scalar(select(EtfProfile))
    assert row.latest_premium_rate == pytest.approx(-0.04)


def test_upsert_etf_profiles_dry_run_writes_nothing(test_session: Session) -> None:
    summary = upsert_etf_profiles(
        test_session,
        {"510300"},
        adapter=FakeEtfAdapter(),
        end_date=date(2026, 8, 15),
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.inserted == 1
    assert test_session.scalar(select(EtfProfile)) is None


def test_sample_etf_codes_filters_by_is_etf(test_session: Session) -> None:
    test_session.add_all(
        [
            FundMain(
                fund_code="510300",
                short_name="沪深300ETF",
                full_name="华泰柏瑞沪深300ETF",
                category="股票型",
                sub_category="ETF",
                is_etf=True,
            ),
            FundMain(
                fund_code="110020",
                short_name="沪深300联接",
                full_name="易方达沪深300ETF联接",
                category="指数型",
                sub_category="ETF联接",
                is_etf=False,
            ),
        ]
    )
    test_session.commit()

    assert sample_etf_codes(test_session) == {"510300"}
    assert sample_etf_codes(test_session, {"110020"}) == set()
