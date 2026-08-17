"""P4.1-2 指数数据域测试 — index_main / index_daily / index_constituent."""

import types
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.akshare import (
    SW_CLASSIFICATION_VERSION,
    AkshareAdapter,
    canonical_sw_index_code,
    is_sw_index_symbol,
    normalize_sw_index_code,
)
from fund_research.data.adapters.base import FetchResult
from fund_research.data.update import (
    _apply_index_main_row,
    resolve_sw_industry_index_symbols,
    upsert_akshare_index_constituents,
    upsert_akshare_index_main,
    upsert_akshare_industry_index_daily,
)
from fund_research.db.models import IndexConstituent, IndexDaily, IndexMain

# ============================================================
# 申万指数代码识别
# ============================================================


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("801010", True),
        ("801010.SI", True),
        ("801150.SI", True),
        ("sh000300", False),
        ("000300", False),
        ("399330", False),
        ("CI005001", False),
        ("", False),
    ],
)
def test_is_sw_index_symbol(symbol: str, expected: bool) -> None:
    assert is_sw_index_symbol(symbol) is expected


def test_sw_index_code_normalization() -> None:
    assert normalize_sw_index_code("801010.SI") == "801010"
    assert normalize_sw_index_code("801010") == "801010"
    assert canonical_sw_index_code("801010") == "801010.SI"
    assert canonical_sw_index_code("801010.si") == "801010.SI"
    with pytest.raises(ValueError, match="非法申万指数代码"):
        normalize_sw_index_code("sh000300")


# ============================================================
# 适配器标准化
# ============================================================


def _fake_sw_ak() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        sw_index_first_info=lambda: pd.DataFrame(
            [
                {
                    "行业代码": "801010.SI",
                    "行业名称": "农林牧渔",
                    "成份个数": 104,
                    "静态市盈率": 22.51,
                    "TTM(滚动)市盈率": 28.20,
                    "市净率": 2.11,
                    "静态股息率": 2.30,
                },
                {
                    "行业代码": "801030.SI",
                    "行业名称": "基础化工",
                    "成份个数": 410,
                    "静态市盈率": 26.42,
                    "TTM(滚动)市盈率": 24.63,
                    "市净率": 2.37,
                    "静态股息率": 1.56,
                },
            ]
        ),
        sw_index_second_info=lambda: pd.DataFrame(
            [
                {
                    "行业代码": "801016.SI",
                    "行业名称": "种植业",
                    "上级行业": "农林牧渔",
                    "成份个数": 20,
                    "静态市盈率": 29.88,
                    "TTM(滚动)市盈率": 27.14,
                    "市净率": 2.01,
                    "静态股息率": 1.82,
                },
            ]
        ),
        index_hist_sw=lambda symbol, period: pd.DataFrame(
            [
                {
                    "代码": symbol,
                    "日期": "2024-01-02",
                    "收盘": 1000.0,
                    "开盘": 998.0,
                    "最高": 1005.0,
                    "最低": 995.0,
                    "成交量": 10.5,
                    "成交额": 10500.0,
                },
                {
                    "代码": symbol,
                    "日期": "2024-01-03",
                    "收盘": 1010.0,
                    "开盘": 1000.0,
                    "最高": 1012.0,
                    "最低": 999.0,
                    "成交量": 11.0,
                    "成交额": 11000.0,
                },
                {
                    "代码": symbol,
                    "日期": "2024-01-04",
                    "收盘": 1008.0,
                    "开盘": 1010.0,
                    "最高": 1015.0,
                    "最低": 1000.0,
                    "成交量": 9.0,
                    "成交额": 9500.0,
                },
            ]
        ),
        index_component_sw=lambda symbol: pd.DataFrame(
            [
                {
                    "序号": 1,
                    "证券代码": "000505",
                    "证券名称": "京粮控股",
                    "最新权重": 0.3014,
                    "计入日期": "2021-12-13",
                },
                {
                    "序号": 2,
                    "证券代码": "000592",
                    "证券名称": "平潭发展",
                    "最新权重": 1.9378,
                    "计入日期": "2021-12-13",
                },
            ]
        ),
    )


def test_fetch_sw_index_list_level1_standardizes_rows() -> None:
    adapter = AkshareAdapter(ak_module=_fake_sw_ak())

    result = adapter.fetch_sw_index_list(level=1)

    assert result.is_success is True
    assert result.entity_type == "index_main"
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["index_code"] == "801010.SI"
    assert row["index_name"] == "农林牧渔"
    assert row["index_type"] == "industry"
    assert row["classification_system"] == "SW"
    # P4.2-3：口径版本强制写（§5.3.3）
    assert row["classification_version"] == SW_CLASSIFICATION_VERSION
    assert row["level"] == 1
    assert row["member_count"] == 104
    assert row["extra"]["pe_static"] == 22.51
    assert row["extra"]["pb"] == 2.11


def test_fetch_sw_index_list_level2_keeps_parent_industry() -> None:
    adapter = AkshareAdapter(ak_module=_fake_sw_ak())

    result = adapter.fetch_sw_index_list(level=2)

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["index_code"] == "801016.SI"
    assert row["level"] == 2
    assert row["extra"]["parent_industry_name"] == "农林牧渔"


def test_fetch_sw_index_list_rejects_unknown_level() -> None:
    adapter = AkshareAdapter(ak_module=_fake_sw_ak())

    result = adapter.fetch_sw_index_list(level=3)

    assert result.is_success is False
    assert "level" in (result.error_message or "")


def test_fetch_sw_index_daily_computes_return_and_filters_window() -> None:
    adapter = AkshareAdapter(ak_module=_fake_sw_ak())

    result = adapter.fetch_sw_index_daily(
        "801010",
        start_date=date(2024, 1, 3),
        end_date=date(2024, 1, 4),
    )

    assert result.is_success is True
    assert result.entity_type == "index_daily"
    assert result.data is not None
    assert len(result.data) == 2
    first, second = result.data.iloc[0], result.data.iloc[1]
    # 窗口内首行基于全序列前收盘计算 daily_return（1000 → 1010）
    assert first["index_code"] == "801010.SI"
    assert first["close_price"] == 1010.0
    assert first["daily_return"] == pytest.approx(0.01)
    assert second["daily_return"] == pytest.approx((1008.0 - 1010.0) / 1010.0)


def test_fetch_sw_index_daily_rejects_non_sw_symbol() -> None:
    adapter = AkshareAdapter(ak_module=_fake_sw_ak())

    result = adapter.fetch_sw_index_daily("sh000300")

    assert result.is_success is False
    assert "非法申万指数代码" in (result.error_message or "")


def test_fetch_sw_index_constituents_standardizes_rows() -> None:
    adapter = AkshareAdapter(ak_module=_fake_sw_ak())

    result = adapter.fetch_sw_index_constituents("801010.SI")

    assert result.is_success is True
    assert result.entity_type == "index_constituent"
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["index_code"] == "801010.SI"
    assert row["stock_code"] == "000505"
    assert row["stock_name"] == "京粮控股"
    assert row["weight_pct"] == pytest.approx(0.3014)
    assert row["effective_date"] == "2021-12-13"


# ============================================================
# update 工作流
# ============================================================


class FakeSwIndexAdapter:
    """Fake adapter for P4.1-2 update workflow tests."""

    def __init__(self) -> None:
        self.daily_seen_symbols: list[str] = []
        self.constituent_seen_symbols: list[str] = []

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

    def fetch_sw_index_list(self, level: int = 1) -> FetchResult:
        return self._result(
            "index_main",
            [
                {
                    "index_code": "801010.SI",
                    "index_name": "农林牧渔",
                    "index_type": "industry",
                    "classification_system": "SW",
                    "level": 1,
                    "member_count": 2,
                    "extra": {"pe_static": 22.5},
                },
                {
                    "index_code": "801030.SI",
                    "index_name": "基础化工",
                    "index_type": "industry",
                    "classification_system": "SW",
                    "level": 1,
                    "member_count": 1,
                    "extra": {},
                },
            ],
        )

    def fetch_sw_index_daily(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FetchResult:
        self.daily_seen_symbols.append(symbol)
        return self._result(
            "index_daily",
            [
                {
                    "index_code": "801010.SI",
                    "trade_date": "2024-01-02",
                    "open_price": 998.0,
                    "high_price": 1005.0,
                    "low_price": 995.0,
                    "close_price": 1000.0,
                    "volume": 10.5,
                    "amount": 10500.0,
                    "daily_return": 0.001,
                },
                {
                    "index_code": "801010.SI",
                    "trade_date": "2024-01-03",
                    "open_price": 1000.0,
                    "high_price": 1012.0,
                    "low_price": 999.0,
                    "close_price": 1010.0,
                    "volume": 11.0,
                    "amount": 11000.0,
                    "daily_return": 0.01,
                },
            ],
        )

    def fetch_sw_index_constituents(self, symbol: str) -> FetchResult:
        self.constituent_seen_symbols.append(symbol)
        return self._result(
            "index_constituent",
            [
                {
                    "index_code": "801010.SI",
                    "effective_date": "2021-12-13",
                    "stock_code": "000505",
                    "stock_name": "京粮控股",
                    "weight_pct": 0.3014,
                },
                {
                    "index_code": "801010.SI",
                    "effective_date": "2021-12-13",
                    "stock_code": "000592",
                    "stock_name": "平潭发展",
                    "weight_pct": 1.9378,
                },
            ],
        )


def test_upsert_akshare_index_main_writes_sw_industries(test_session: Session) -> None:
    summary = upsert_akshare_index_main(test_session, adapter=FakeSwIndexAdapter(), level=1)

    assert summary.inserted == 2
    rows = test_session.scalars(select(IndexMain).order_by(IndexMain.index_code)).all()
    assert [row.index_code for row in rows] == ["801010.SI", "801030.SI"]
    first = rows[0]
    assert first.index_name == "农林牧渔"
    assert first.index_type == "industry"
    assert first.classification_system == "SW"
    assert first.level == 1
    assert first.member_count == 2
    assert first.extra == {"pe_static": 22.5}
    assert first.source_level == DataSourceLevel.B.value


def test_upsert_akshare_index_main_is_idempotent(test_session: Session) -> None:
    adapter = FakeSwIndexAdapter()
    first = upsert_akshare_index_main(test_session, adapter=adapter, level=1)
    test_session.commit()
    second = upsert_akshare_index_main(test_session, adapter=adapter, level=1)

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.updated == 2


def test_upsert_akshare_industry_index_daily_writes_rows_and_ensures_main(
    test_session: Session,
) -> None:
    adapter = FakeSwIndexAdapter()

    summary = upsert_akshare_industry_index_daily(
        test_session,
        {"801010"},
        adapter=adapter,
    )

    assert summary.inserted == 2
    assert summary.warnings == []
    assert adapter.daily_seen_symbols == ["801010"]
    # 行情写入 index_daily
    row = test_session.scalar(
        select(IndexDaily)
        .where(IndexDaily.index_code == "801010.SI")
        .where(IndexDaily.trade_date == date(2024, 1, 2))
    )
    assert row is not None
    assert row.close_price == 1000.0
    assert row.daily_return == 0.001
    assert row.source_name == "akshare.index_hist_sw"
    # index_main 骨架自动补录
    main_row = test_session.scalar(
        select(IndexMain).where(IndexMain.index_code == "801010.SI")
    )
    assert main_row is not None
    assert main_row.index_name == "农林牧渔"
    assert main_row.classification_system == "SW"


def test_upsert_akshare_industry_index_daily_skips_non_sw_symbols(
    test_session: Session,
) -> None:
    adapter = FakeSwIndexAdapter()

    summary = upsert_akshare_industry_index_daily(
        test_session,
        {"sh000300", "801010.SI"},
        adapter=adapter,
    )

    assert adapter.daily_seen_symbols == ["801010.SI"]
    assert any("sh000300" in warning for warning in summary.warnings)


def test_upsert_akshare_industry_index_daily_dry_run_writes_nothing(
    test_session: Session,
) -> None:
    summary = upsert_akshare_industry_index_daily(
        test_session,
        {"801010"},
        adapter=FakeSwIndexAdapter(),
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.inserted == 2
    assert test_session.scalar(select(IndexDaily)) is None
    assert test_session.scalar(select(IndexMain)) is None


def test_upsert_akshare_index_constituents_writes_weights(test_session: Session) -> None:
    adapter = FakeSwIndexAdapter()

    summary = upsert_akshare_index_constituents(
        test_session,
        {"801010.SI"},
        adapter=adapter,
    )

    assert summary.inserted == 2
    assert adapter.constituent_seen_symbols == ["801010.SI"]
    row = test_session.scalar(
        select(IndexConstituent)
        .where(IndexConstituent.index_code == "801010.SI")
        .where(IndexConstituent.stock_code == "000505")
    )
    assert row is not None
    assert row.stock_name == "京粮控股"
    assert row.weight_pct == pytest.approx(0.3014)
    assert row.effective_date == date(2021, 12, 13)
    assert row.source_name == "akshare.index_component_sw"
    # index_main 骨架自动补录
    assert (
        test_session.scalar(select(IndexMain).where(IndexMain.index_code == "801010.SI"))
        is not None
    )


def test_upsert_akshare_index_constituents_is_idempotent(test_session: Session) -> None:
    adapter = FakeSwIndexAdapter()
    first = upsert_akshare_index_constituents(
        test_session, {"801010.SI"}, adapter=adapter
    )
    test_session.commit()
    second = upsert_akshare_index_constituents(
        test_session, {"801010.SI"}, adapter=adapter
    )

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.updated == 2


def test_resolve_sw_industry_index_symbols_uses_adapter_list(test_session: Session) -> None:
    symbols = resolve_sw_industry_index_symbols(test_session, adapter=FakeSwIndexAdapter())

    assert symbols == {"801010.SI", "801030.SI"}


def test_resolve_sw_industry_index_symbols_falls_back_to_db(test_session: Session) -> None:
    test_session.add(
        IndexMain(
            index_code="801050.SI",
            index_name="有色金属",
            index_type="industry",
            classification_system="SW",
            source_name="test",
            source_level="B",
        )
    )
    test_session.flush()

    class BrokenAdapter(FakeSwIndexAdapter):
        def fetch_sw_index_list(self, level: int = 1) -> FetchResult:
            return FetchResult(
                source_name="akshare",
                source_type=DataSourceType.OPEN_API,
                source_level=DataSourceLevel.B,
                entity_type="index_main",
                is_success=False,
                error_message="network down",
            )

    symbols = resolve_sw_industry_index_symbols(test_session, adapter=BrokenAdapter())

    assert symbols == {"801050.SI"}


def test_apply_index_main_row_forces_classification_version(test_session: Session) -> None:
    """P4.2-3：申万体系缺失版本时强制回填 SW_CLASSIFICATION_VERSION，禁止 unknown。"""
    action = _apply_index_main_row(
        test_session,
        {
            "index_code": "801010.SI",
            "index_name": "农林牧渔",
            "index_type": "industry",
            "classification_system": "SW",
            # 故意不提供 classification_version
        },
        "akshare.sw_index_first_info",
        DataSourceLevel.B,
        dry_run=False,
    )

    assert action == "inserted"
    row = test_session.scalar(select(IndexMain).where(IndexMain.index_code == "801010.SI"))
    assert row is not None
    assert row.classification_version == SW_CLASSIFICATION_VERSION
    assert row.classification_version != "unknown"
