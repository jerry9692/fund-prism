"""P4.1-3 债券数据域测试 — bond_main / bond_daily / yield_curve_daily."""

import types
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.akshare import (
    AkshareAdapter,
    _add_months,
    canonical_cb_code,
    cb_sina_symbol,
    is_cb_code,
    normalize_cb_code,
)
from fund_research.data.adapters.base import FetchResult
from fund_research.data.update import (
    disclosed_convertible_bond_codes,
    load_credit_spread_series,
    upsert_akshare_cb_daily,
    upsert_akshare_cb_list,
    upsert_akshare_china_yield_curve,
    upsert_akshare_credit_yield_curve,
)
from fund_research.db.models import (
    BondDaily,
    BondMain,
    FundDisclosedHoldings,
    YieldCurveDaily,
)

# ============================================================
# 可转债代码识别与归一化
# ============================================================


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("128039", True),
        ("128039.SZ", True),
        ("110080", True),
        ("110080.SH", True),
        ("123283", True),
        ("130001", False),
        ("600519", False),
        ("801010", False),
        ("", False),
    ],
)
def test_is_cb_code(symbol: str, expected: bool) -> None:
    assert is_cb_code(symbol) is expected


def test_cb_code_normalization() -> None:
    assert normalize_cb_code("128039.SZ") == "128039"
    assert normalize_cb_code("128039") == "128039"
    assert canonical_cb_code("128039") == "128039.SZ"
    assert canonical_cb_code("110080") == "110080.SH"
    assert canonical_cb_code("110080.sh") == "110080.SH"
    assert cb_sina_symbol("128039.SZ") == "sz128039"
    assert cb_sina_symbol("110080") == "sh110080"
    with pytest.raises(ValueError, match="非法可转债代码"):
        normalize_cb_code("600519")


def test_add_months_handles_month_end() -> None:
    assert _add_months(date(2023, 8, 15), 1) == date(2023, 9, 15)
    assert _add_months(date(2023, 12, 31), 1) == date(2024, 1, 31)
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


# ============================================================
# 适配器标准化
# ============================================================


def _fake_bond_ak(close_return_calls: list | None = None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        bond_zh_cov=lambda: pd.DataFrame(
            [
                {
                    "债券代码": "128039",
                    "债券简称": "隆基转债",
                    "申购日期": "2019-03-12",
                    "正股代码": "601012",
                    "正股简称": "隆基绿能",
                    "正股价": 18.5,
                    "转股价": 21.05,
                    "转股价值": 87.89,
                    "债现价": 105.9,
                    "转股溢价率": 20.49,
                    "发行规模": 50.0,
                    "中签率": 0.003,
                    "上市时间": "2019-04-08",
                    "信用评级": "AAA",
                },
                {
                    "债券代码": "110080",
                    "债券简称": "东湖转债",
                    "申购日期": "-",
                    "正股代码": "600133",
                    "正股简称": "东湖高新",
                    "正股价": "-",
                    "转股价": 6.15,
                    "转股价值": "-",
                    "债现价": "-",
                    "转股溢价率": "-",
                    "发行规模": 15.5,
                    "中签率": "-",
                    "上市时间": "-",
                    "信用评级": "AA",
                },
            ]
        ),
        bond_zh_hs_cov_daily=lambda symbol: pd.DataFrame(
            [
                {
                    "date": "2024-06-03",
                    "open": 105.85,
                    "high": 105.94,
                    "low": 105.85,
                    "close": 105.89,
                    "volume": 425169,
                },
                {
                    "date": "2024-06-04",
                    "open": 105.88,
                    "high": 105.92,
                    "low": 105.88,
                    "close": 105.90,
                    "volume": 415207,
                },
                {
                    "date": "2024-06-05",
                    "open": 105.90,
                    "high": 106.20,
                    "low": 105.80,
                    "close": 106.15,
                    "volume": 500000,
                },
            ]
        ),
        bond_china_yield=lambda start_date, end_date: pd.DataFrame(
            [
                {
                    "曲线名称": "中债国债收益率曲线",
                    "日期": "2026-08-12",
                    "3月": 1.05,
                    "6月": 1.10,
                    "1年": 1.19,
                    "3年": 1.31,
                    "5年": 1.45,
                    "7年": 1.54,
                    "10年": 1.71,
                    "30年": 2.17,
                },
                {
                    "曲线名称": "中债中短期票据收益率曲线(AAA)",
                    "日期": "2026-08-12",
                    "3月": 1.47,
                    "6月": 1.52,
                    "1年": 1.60,
                    "3年": 1.80,
                    "5年": 1.95,
                    "7年": 2.09,
                    "10年": 2.30,
                    "30年": None,
                },
                {
                    "曲线名称": "其他未知曲线",
                    "日期": "2026-08-12",
                    "3月": 9.99,
                    "6月": 9.99,
                    "1年": 9.99,
                    "3年": 9.99,
                    "5年": 9.99,
                    "7年": 9.99,
                    "10年": 9.99,
                    "30年": None,
                },
            ]
        ),
        bond_china_close_return=lambda symbol, period, start_date, end_date: (
            close_return_calls.append((symbol, start_date, end_date))
            if close_return_calls is not None
            else None
        )
        or pd.DataFrame(
            [
                {"日期": "2026-08-10", "期限": 1.0, "到期收益率": 1.80, "即期收益率": 1.81, "远期收益率": 2.0},
                {"日期": "2026-08-10", "期限": 3.0, "到期收益率": 2.35, "即期收益率": 2.37, "远期收益率": 2.9},
                {"日期": "2026-08-11", "期限": 3.0, "到期收益率": 2.33, "即期收益率": 2.35, "远期收益率": 2.8},
            ]
        ),
    )


def test_fetch_cb_list_standardizes_rows() -> None:
    adapter = AkshareAdapter(ak_module=_fake_bond_ak())

    result = adapter.fetch_cb_list()

    assert result.is_success is True
    assert result.entity_type == "bond_main"
    assert result.data is not None
    assert len(result.data) == 2
    first = result.data.iloc[0]
    assert first["bond_code"] == "128039.SZ"
    assert first["bond_name"] == "隆基转债"
    assert first["bond_type"] == "convertible"
    assert first["rating"] == "AAA"
    assert first["conversion_price"] == pytest.approx(21.05)
    assert first["underlying_stock_code"] == "601012"
    assert first["listing_date"] == "2019-04-08"
    assert first["issue_size"] == pytest.approx(50.0)
    assert first["extra"]["conversion_value"] == pytest.approx(87.89)
    assert first["extra"]["conversion_premium_rate"] == pytest.approx(20.49)
    # 占位符 "-" 应被清洗
    second = result.data.iloc[1]
    assert second["bond_code"] == "110080.SH"
    assert second["rating"] == "AA"
    assert pd.isna(second["listing_date"])
    assert "cb_price" not in second["extra"] or second["extra"].get("cb_price") is None


def test_fetch_cb_daily_computes_return_and_filters_window() -> None:
    adapter = AkshareAdapter(ak_module=_fake_bond_ak())

    result = adapter.fetch_cb_daily(
        "128039",
        start_date=date(2024, 6, 4),
        end_date=date(2024, 6, 5),
    )

    assert result.is_success is True
    assert result.entity_type == "bond_daily"
    assert result.data is not None
    assert len(result.data) == 2
    first, second = result.data.iloc[0], result.data.iloc[1]
    # 窗口内首行基于全序列前收盘计算 daily_return（105.89 → 105.90）
    assert first["bond_code"] == "128039.SZ"
    assert first["close_price"] == pytest.approx(105.90)
    assert first["daily_return"] == pytest.approx((105.90 - 105.89) / 105.89)
    assert second["daily_return"] == pytest.approx((106.15 - 105.90) / 105.90)


def test_fetch_cb_daily_rejects_non_cb_symbol() -> None:
    adapter = AkshareAdapter(ak_module=_fake_bond_ak())

    result = adapter.fetch_cb_daily("600519")

    assert result.is_success is False
    assert "非法可转债代码" in (result.error_message or "")


def test_fetch_china_yield_curve_flattens_known_curves() -> None:
    adapter = AkshareAdapter(ak_module=_fake_bond_ak())

    result = adapter.fetch_china_yield_curve(date(2026, 8, 1), date(2026, 8, 12))

    assert result.is_success is True
    assert result.entity_type == "yield_curve_daily"
    data = result.data
    assert data is not None
    curves = set(data["curve_name"])
    assert curves == {"treasury", "medium_term_note_aaa"}
    treasury_10y = data[
        (data["curve_name"] == "treasury") & (data["tenor_years"] == 10.0)
    ].iloc[0]
    assert treasury_10y["yield_pct"] == pytest.approx(1.71)
    assert treasury_10y["trade_date"] == "2026-08-12"
    # 未知曲线与 NaN 值均被跳过：AAA 30年为 NaN
    aaa_rows = data[data["curve_name"] == "medium_term_note_aaa"]
    assert 30.0 not in set(aaa_rows["tenor_years"])
    assert len(data) == 15  # 国债 8 档 + AAA 7 档


def test_fetch_china_credit_yield_curve_splits_monthly_windows() -> None:
    calls: list = []
    adapter = AkshareAdapter(ak_module=_fake_bond_ak(close_return_calls=calls))

    result = adapter.fetch_china_credit_yield_curve(
        "中短期票据(AA)",
        date(2026, 6, 20),
        date(2026, 8, 10),
        request_interval_seconds=0.0,
    )

    assert result.is_success is True
    # 2026-06-20~07-20 / 07-21~08-10 两个窗口
    assert len(calls) == 2
    assert calls[0][1:] == ("20260620", "20260720")
    assert calls[1][1:] == ("20260721", "20260810")
    data = result.data
    assert data is not None
    assert len(data) == 3
    row = data.iloc[0]
    assert row["curve_name"] == "medium_term_note_aa"
    assert row["tenor_years"] == pytest.approx(1.0)
    assert row["yield_pct"] == pytest.approx(1.80)


# ============================================================
# update 工作流
# ============================================================


class FakeBondAdapter:
    """Fake adapter for P4.1-3 update workflow tests."""

    def __init__(self) -> None:
        self.cb_daily_seen: list[str] = []

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

    def fetch_cb_list(self) -> FetchResult:
        return self._result(
            "bond_main",
            [
                {
                    "bond_code": "128039.SZ",
                    "bond_name": "隆基转债",
                    "bond_type": "convertible",
                    "rating": "AAA",
                    "conversion_price": 21.05,
                    "underlying_stock_code": "601012",
                    "underlying_stock_name": "隆基绿能",
                    "listing_date": "2019-04-08",
                    "issue_size": 50.0,
                    "extra": {"conversion_value": 87.89},
                },
            ],
        )

    def fetch_cb_daily(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        self.cb_daily_seen.append(symbol)
        return self._result(
            "bond_daily",
            [
                {
                    "bond_code": canonical_cb_code(symbol),
                    "trade_date": "2024-06-03",
                    "open_price": 105.85,
                    "high_price": 105.94,
                    "low_price": 105.85,
                    "close_price": 105.89,
                    "volume": 425169,
                    "daily_return": 0.001,
                },
                {
                    "bond_code": canonical_cb_code(symbol),
                    "trade_date": "2024-06-04",
                    "open_price": 105.88,
                    "high_price": 105.92,
                    "low_price": 105.88,
                    "close_price": 105.90,
                    "volume": 415207,
                    "daily_return": 0.0001,
                },
            ],
        )

    def fetch_china_yield_curve(self, start_date: date, end_date: date) -> FetchResult:
        return self._result(
            "yield_curve_daily",
            [
                {"curve_name": "treasury", "trade_date": "2026-08-12", "tenor_years": 3.0, "yield_pct": 1.31},
                {"curve_name": "treasury", "trade_date": "2026-08-12", "tenor_years": 10.0, "yield_pct": 1.71},
                {
                    "curve_name": "medium_term_note_aaa",
                    "trade_date": "2026-08-12",
                    "tenor_years": 3.0,
                    "yield_pct": 1.80,
                },
            ],
        )

    def fetch_china_credit_yield_curve(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        curve_name: str = "medium_term_note_aa",
        request_interval_seconds: float = 0.0,
    ) -> FetchResult:
        return self._result(
            "yield_curve_daily",
            [
                {
                    "curve_name": curve_name,
                    "trade_date": "2026-08-12",
                    "tenor_years": 3.0,
                    "yield_pct": 2.35,
                },
            ],
        )


def test_upsert_akshare_cb_list_writes_bond_main(test_session: Session) -> None:
    summary = upsert_akshare_cb_list(test_session, adapter=FakeBondAdapter())

    assert summary.inserted == 1
    row = test_session.scalar(select(BondMain))
    assert row is not None
    assert row.bond_code == "128039.SZ"
    assert row.bond_name == "隆基转债"
    assert row.bond_type == "convertible"
    assert row.rating == "AAA"
    assert row.conversion_price == pytest.approx(21.05)
    assert row.underlying_stock_code == "601012"
    assert row.listing_date == date(2019, 4, 8)
    assert row.extra == {"conversion_value": 87.89}
    assert row.source_level == DataSourceLevel.B.value


def test_upsert_akshare_cb_list_is_idempotent(test_session: Session) -> None:
    adapter = FakeBondAdapter()
    first = upsert_akshare_cb_list(test_session, adapter=adapter)
    test_session.commit()
    second = upsert_akshare_cb_list(test_session, adapter=adapter)

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.updated == 1


def test_upsert_akshare_cb_daily_writes_rows(test_session: Session) -> None:
    adapter = FakeBondAdapter()

    summary = upsert_akshare_cb_daily(test_session, {"128039"}, adapter=adapter)

    assert summary.inserted == 2
    assert adapter.cb_daily_seen == ["128039.SZ"]
    row = test_session.scalar(
        select(BondDaily)
        .where(BondDaily.bond_code == "128039.SZ")
        .where(BondDaily.trade_date == date(2024, 6, 3))
    )
    assert row is not None
    assert row.close_price == pytest.approx(105.89)
    assert row.source_name == "akshare.bond_zh_hs_cov_daily"


def test_upsert_akshare_cb_daily_skips_invalid_codes(test_session: Session) -> None:
    adapter = FakeBondAdapter()

    summary = upsert_akshare_cb_daily(
        test_session, {"600519", "110080"}, adapter=adapter
    )

    assert adapter.cb_daily_seen == ["110080.SH"]
    assert any("600519" in warning for warning in summary.warnings)


def test_upsert_akshare_cb_daily_dry_run_writes_nothing(test_session: Session) -> None:
    summary = upsert_akshare_cb_daily(
        test_session, {"128039"}, adapter=FakeBondAdapter(), dry_run=True
    )

    assert summary.dry_run is True
    assert summary.inserted == 2
    assert test_session.scalar(select(BondDaily)) is None


def test_upsert_akshare_china_yield_curve_writes_rows(test_session: Session) -> None:
    summary = upsert_akshare_china_yield_curve(
        test_session,
        adapter=FakeBondAdapter(),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 12),
    )

    assert summary.inserted == 3
    row = test_session.scalar(
        select(YieldCurveDaily)
        .where(YieldCurveDaily.curve_name == "treasury")
        .where(YieldCurveDaily.tenor_years == 10.0)
    )
    assert row is not None
    assert row.yield_pct == pytest.approx(1.71)
    assert row.source_name == "akshare.bond_china_yield"


def test_upsert_yield_curves_are_idempotent(test_session: Session) -> None:
    adapter = FakeBondAdapter()
    window = {"start_date": date(2026, 8, 1), "end_date": date(2026, 8, 12)}
    first_china = upsert_akshare_china_yield_curve(test_session, adapter=adapter, **window)
    first_credit = upsert_akshare_credit_yield_curve(test_session, adapter=adapter, **window)
    test_session.commit()
    second_china = upsert_akshare_china_yield_curve(test_session, adapter=adapter, **window)
    second_credit = upsert_akshare_credit_yield_curve(test_session, adapter=adapter, **window)

    assert first_china.inserted == 3
    assert second_china.inserted == 0 and second_china.updated == 3
    assert first_credit.inserted == 1
    assert second_credit.inserted == 0 and second_credit.updated == 1


def test_bond_daily_unique_constraint(test_session: Session) -> None:
    test_session.add(
        BondDaily(
            bond_code="128039.SZ",
            trade_date=date(2024, 6, 3),
            source_name="test",
            source_level="B",
        )
    )
    test_session.commit()
    test_session.add(
        BondDaily(
            bond_code="128039.SZ",
            trade_date=date(2024, 6, 3),
            source_name="test",
            source_level="B",
        )
    )
    with pytest.raises(IntegrityError):
        test_session.commit()
    test_session.rollback()


def test_yield_curve_daily_unique_constraint(test_session: Session) -> None:
    test_session.add(
        YieldCurveDaily(
            curve_name="treasury",
            trade_date=date(2026, 8, 12),
            tenor_years=10.0,
            yield_pct=1.71,
            source_name="test",
            source_level="B",
        )
    )
    test_session.commit()
    test_session.add(
        YieldCurveDaily(
            curve_name="treasury",
            trade_date=date(2026, 8, 12),
            tenor_years=10.0,
            yield_pct=1.72,
            source_name="test",
            source_level="B",
        )
    )
    with pytest.raises(IntegrityError):
        test_session.commit()
    test_session.rollback()


# ============================================================
# 信用利差序列 + 披露转债持仓解析
# ============================================================


def test_load_credit_spread_series_computes_spreads(test_session: Session) -> None:
    summary = upsert_akshare_china_yield_curve(
        test_session,
        adapter=FakeBondAdapter(),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 12),
    )
    assert summary.inserted == 3
    upsert_akshare_credit_yield_curve(
        test_session,
        adapter=FakeBondAdapter(),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 12),
    )

    frame = load_credit_spread_series(test_session, tenor_years=3.0)

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["trade_date"] == date(2026, 8, 12)
    assert row["treasury_yield_pct"] == pytest.approx(1.31)
    assert row["aaa_spread_pct"] == pytest.approx(1.80 - 1.31)
    assert row["aa_spread_pct"] == pytest.approx(2.35 - 1.31)


def test_load_credit_spread_series_empty(test_session: Session) -> None:
    frame = load_credit_spread_series(test_session, tenor_years=3.0)

    assert frame.empty
    assert "aaa_spread_pct" in frame.columns


def test_disclosed_convertible_bond_codes(test_session: Session) -> None:
    test_session.add_all(
        [
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=date(2024, 6, 30),
                security_code="128039",
                security_name="隆基转债",
                asset_type="可转债",
                weight_pct=3.2,
                rank_in_holdings=11,
            ),
            FundDisclosedHoldings(
                fund_code="000002",
                report_date=date(2024, 6, 30),
                security_code="110080.SH",
                security_name="东湖转债",
                asset_type="可转债",
                weight_pct=1.1,
                rank_in_holdings=12,
            ),
            FundDisclosedHoldings(
                fund_code="000001",
                report_date=date(2024, 6, 30),
                security_code="600519",
                security_name="贵州茅台",
                asset_type="股票",
                weight_pct=5.0,
                rank_in_holdings=1,
            ),
        ]
    )
    test_session.commit()

    codes = disclosed_convertible_bond_codes(test_session)

    assert codes == {"128039.SZ", "110080.SH"}


# ============================================================
# runner 转债行情加载（P4.0-1 闭环输入）
# ============================================================


def test_runner_load_cb_return_df(test_session: Session) -> None:
    from fund_research.experiments.runner import _load_cb_return_df

    test_session.add_all(
        [
            BondDaily(
                bond_code="128039.SZ",
                trade_date=date(2024, 6, 3),
                close_price=105.89,
                daily_return=0.001,
                source_name="test",
                source_level="B",
            ),
            BondDaily(
                bond_code="128039.SZ",
                trade_date=date(2024, 6, 4),
                close_price=105.90,
                daily_return=None,
                source_name="test",
                source_level="B",
            ),
        ]
    )
    test_session.commit()

    # 裸代码与带后缀代码均可解析；daily_return 为空的行被剔除
    frame = _load_cb_return_df(test_session, {"128039", "600519"})

    assert frame is not None
    assert list(frame.columns) == ["security_code", "trade_date", "daily_return"]
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["security_code"] == "128039.SZ"
    assert row["daily_return"] == pytest.approx(0.001)

    # 无行情数据时返回 None（run_attribution 走显式未剥离警告路径）
    assert _load_cb_return_df(test_session, {"110080"}) is None
    assert _load_cb_return_df(test_session, set()) is None
