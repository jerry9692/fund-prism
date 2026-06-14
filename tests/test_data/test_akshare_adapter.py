"""AKShare adapter tests."""

import types
from datetime import date

import pandas as pd
import pytest

from fund_research.core.enums import DataSourceLevel
from fund_research.data.adapters.akshare import (
    AkshareAdapter,
    benchmark_symbol_to_index_code,
    index_code_to_benchmark_symbol,
)


def test_fetch_fund_list_standardizes_columns() -> None:
    """Fund list columns should be normalized to canonical names."""
    fake_ak = types.SimpleNamespace(
        fund_name_em=lambda: pd.DataFrame(
            [{"基金代码": "000001", "基金名称": "华夏成长混合", "基金类型": "混合型"}]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_list()

    assert result.is_success is True
    assert result.record_count == 1
    assert result.data is not None
    assert list(result.data.columns) == ["fund_code", "fund_name", "fund_type_raw"]


def test_fetch_fund_info_pivots_item_value_table() -> None:
    """Fund detail item/value output should be converted into one canonical row."""
    fake_ak = types.SimpleNamespace(
        fund_individual_basic_info_xq=lambda symbol: pd.DataFrame(
            [
                {"item": "基金代码", "value": symbol},
                {"item": "基金简称", "value": "华夏成长混合"},
                {"item": "基金公司", "value": "华夏基金"},
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_info("000001")

    assert result.is_success is True
    assert result.data is not None
    assert result.data.iloc[0]["fund_code"] == "000001"
    assert result.data.iloc[0]["short_name"] == "华夏成长混合"
    assert result.data.iloc[0]["company_name"] == "华夏基金"


def test_fetch_fund_holdings_standardizes_alias_columns() -> None:
    """Holding aliases from AKShare should map to canonical field names."""
    fake_ak = types.SimpleNamespace(
        fund_portfolio_hold_em=lambda symbol, date: pd.DataFrame(
            [
                {
                    "序号": 1,
                    "股票代码": "600519",
                    "股票名称": "贵州茅台",
                    "占净值比例": "8.50",
                    "持仓市值": 1000.0,
                    "季度": "2024-06-30",
                }
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_holdings("000001")

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["rank_in_holdings"] == 1
    assert row["stock_code"] == "600519"
    assert row["weight_pct"] == "8.50"
    assert row["market_value"] == 1000.0
    assert row["report_date"] == "2024-06-30"


def test_fetch_fund_industry_allocation_standardizes_columns() -> None:
    """Industry allocation aliases should map to canonical fields."""
    fake_ak = types.SimpleNamespace(
        fund_portfolio_industry_allocation_em=lambda symbol, date: pd.DataFrame(
            [
                {
                    "序号": 1,
                    "行业名称": "食品饮料",
                    "占净值比例": "13.50",
                    "市值": "1000.0",
                    "截止时间": "2024-06-30",
                }
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_industry_allocation("000001", report_date=None)

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["industry_name"] == "食品饮料"
    assert row["weight_pct"] == "13.50"
    assert row["market_value"] == "1000.0"
    assert row["report_date"] == "2024-06-30"


def test_fetch_fund_portfolio_change_standardizes_columns() -> None:
    """Portfolio change aliases should expose canonical observation fields."""
    fake_ak = types.SimpleNamespace(
        fund_portfolio_change_em=lambda symbol, date: pd.DataFrame(
            [
                {
                    "序号": 1,
                    "股票代码": "600519",
                    "股票名称": "贵州茅台",
                    "本期累计买入金额": "100.0",
                    "占期初基金资产净值比例": "1.2",
                    "季度": "2024年2季度累计买入股票明细",
                }
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_portfolio_change("000001", report_date=None)

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["stock_code"] == "600519"
    assert row["cumulative_buy_amount"] == "100.0"
    assert row["pct_of_beginning_nav"] == "1.2"
    assert row["report_period"] == "2024年2季度累计买入股票明细"


def test_fetch_fund_portfolio_change_handles_empty_year() -> None:
    """AKShare empty-year KeyError should become an empty successful fetch."""

    def empty_year(symbol: str, date: str) -> pd.DataFrame:
        raise KeyError("序号")

    fake_ak = types.SimpleNamespace(fund_portfolio_change_em=empty_year)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_portfolio_change("000001", report_date=date(2026, 3, 31))

    assert result.is_success is True
    assert result.record_count == 0
    assert result.data is not None
    assert result.data.empty
    assert result.warnings == ["基金持仓变动为空或尚未披露: 000001/2026"]


def test_fetch_fund_managers_standardizes_manager_columns() -> None:
    """Manager table aliases should map to canonical manager fields."""
    fake_ak = types.SimpleNamespace(
        fund_manager_em=lambda: pd.DataFrame(
            [
                {
                    "基金经理ID": "m001",
                    "姓名": "张三",
                    "现任基金代码": "000001",
                    "任职日期": "2020-01-01",
                    "累计从业时间": "8年",
                    "学历": "硕士",
                }
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_managers("000001")

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["manager_id"] == "m001"
    assert row["name"] == "张三"
    assert row["current_fund_codes"] == "000001"
    assert row["start_date"] == "2020-01-01"
    assert row["experience_years"] == "8年"


def test_fetch_fund_managers_handles_current_akshare_shape() -> None:
    """Current AKShare manager table should not produce duplicate canonical columns."""
    fake_ak = types.SimpleNamespace(
        fund_manager_em=lambda: pd.DataFrame(
            [
                {
                    "序号": 1,
                    "姓名": "张三",
                    "所属公司": "华夏基金",
                    "现任基金代码": "000001",
                    "现任基金": "华夏成长混合",
                    "累计从业时间": 1376,
                    "现任基金资产总规模": 2.85,
                    "现任基金最佳回报": 40.55,
                },
                {
                    "序号": 2,
                    "姓名": "李四",
                    "所属公司": "华夏基金",
                    "现任基金代码": "020005",
                    "现任基金": "其他基金",
                    "累计从业时间": 365,
                    "现任基金资产总规模": 1.0,
                    "现任基金最佳回报": 10.0,
                },
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_managers("000001")

    assert result.is_success is True
    assert result.record_count == 1
    assert result.data is not None
    assert result.data.columns[result.data.columns.duplicated()].tolist() == []
    row = result.data.iloc[0]
    assert row["manager_id"].startswith("ak_mgr_")
    assert row["name"] == "张三"
    assert row["company_name"] == "华夏基金"
    assert row["current_fund_codes"] == "000001"
    assert row["current_fund_names"] == "华夏成长混合"
    assert row["experience_years"] == pytest.approx(1376 / 365.25)


def test_fetch_fund_dividends_filters_and_standardizes_columns() -> None:
    """Dividend rows should be normalized and filtered by fund code."""
    fake_ak = types.SimpleNamespace(
        fund_fh_em=lambda year, page: pd.DataFrame(
            [
                {
                    "基金代码": "000001",
                    "基金名称": "华夏成长混合",
                    "分红": "0.05",
                    "分红发放日": "2024-06-20",
                },
                {
                    "基金代码": "020005",
                    "基金名称": "国泰金马稳健",
                    "分红": "0.03",
                    "分红发放日": "2024-06-21",
                },
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_dividends("000001", year=2024)

    assert result.is_success is True
    assert result.record_count == 1
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["fund_code"] == "000001"
    assert row["dividend"] == "0.05"
    assert row["dividend_date"] == "2024-06-20"


def test_fetch_fee_detail_pivots_fee_items() -> None:
    """Fee detail item/value output should expose canonical fee fields."""
    fake_ak = types.SimpleNamespace(
        fund_individual_detail_info_xq=lambda symbol: pd.DataFrame(
            [
                {"item": "管理费率", "value": "1.5%"},
                {"item": "托管费率", "value": "0.25%"},
                {"item": "销售服务费率", "value": "0%"},
                {"item": "申购费率", "value": "0%-1.5%"},
                {"item": "赎回费率", "value": "0%-1.5%"},
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fee_detail("000001")

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["mgmt_fee_pct"] == "1.5%"
    assert row["custody_fee_pct"] == "0.25%"
    assert row["sales_service_fee_pct"] == "0%"
    assert row["subscribe_fee_range"] == "0%-1.5%"


def test_fetch_fee_detail_normalizes_current_akshare_fee_table() -> None:
    """Current AKShare fee detail long table should become one canonical fee row."""
    fake_ak = types.SimpleNamespace(
        fund_individual_detail_info_xq=lambda symbol: pd.DataFrame(
            [
                {"费用类型": "买入规则", "条件或名称": "0.0万<买入金额<100.0万", "费用": 1.5},
                {"费用类型": "卖出规则", "条件或名称": "0.0天<持有期限<7.0天", "费用": 1.5},
                {"费用类型": "其他费用", "条件或名称": "基金管理费", "费用": 1.2},
                {"费用类型": "其他费用", "条件或名称": "基金托管费", "费用": 0.2},
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fee_detail("000001")

    assert result.is_success is True
    assert result.record_count == 1
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["mgmt_fee_pct"] == 1.2
    assert row["custody_fee_pct"] == 0.2
    assert row["sales_service_fee_pct"] is None
    assert row["subscribe_fee_range"] == "0.0万<买入金额<100.0万: 1.5"
    assert row["redeem_fee_range"] == "0.0天<持有期限<7.0天: 1.5"


def test_fetch_fund_scale_pivots_latest_scale() -> None:
    """Fund scale item/value output should expose canonical scale fields."""
    fake_ak = types.SimpleNamespace(
        fund_individual_basic_info_xq=lambda symbol: pd.DataFrame(
            [
                {"item": "基金代码", "value": symbol},
                {"item": "最新规模", "value": "12.50亿元"},
                {"item": "总份额", "value": "10.00亿份"},
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_scale("000001")

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["fund_code"] == "000001"
    assert row["total_nav"] == "12.50亿元"
    assert row["total_share"] == "10.00亿份"


def test_fetch_holder_structure_standardizes_columns() -> None:
    """Holder structure aliases should map to canonical fields."""
    fake_ak = types.SimpleNamespace(
        fund_individual_hold_info=lambda symbol: pd.DataFrame(
            [
                {
                    "基金代码": symbol,
                    "截止日期": "2024-06-30",
                    "机构持有比列": 43.54,
                    "个人持有比列": 55.85,
                    "内部持有比列": 2.0,
                    "总份额": 321405.19,
                }
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_holder_structure("000001")

    assert result.is_success is True
    assert result.record_count == 1
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["fund_code"] == "000001"
    assert row["report_date"] == "2024-06-30"
    assert row["institutional_pct"] == 43.54
    assert row["individual_pct"] == 55.85
    assert row["employee_pct"] == 2.0
    assert row["total_share"] == 321405.19


def test_fetch_holder_structure_skips_aggregate_only_interface() -> None:
    """Aggregate holder structure output must not be treated as fund-level data."""

    def aggregate_holder_structure() -> pd.DataFrame:
        raise AssertionError("aggregate interface should not be called")

    fake_ak = types.SimpleNamespace(fund_hold_structure_em=aggregate_holder_structure)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_holder_structure("000001")

    assert result.is_success is False
    assert result.record_count == 0
    assert "全市场汇总接口" in result.error_message


def test_fetch_index_daily_standardizes_english_columns() -> None:
    """Index daily rows from Tencent path should expose canonical price fields."""
    captured: dict[str, str] = {}

    def fake_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        captured["symbol"] = symbol
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        return pd.DataFrame(
            [
                {
                    "date": "2024-01-02",
                    "open": "3000.0",
                    "high": "3010.0",
                    "low": "2990.0",
                    "close": "3005.0",
                    "volume": "100000",
                    "amount": "300000000",
                }
            ]
        )

    fake_ak = types.SimpleNamespace(
        stock_zh_index_daily_tx=fake_index_daily
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_index_daily(
        "sh000300",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )

    assert result.is_success is True
    assert captured == {
        "symbol": "sh000300",
        "start_date": "20240101",
        "end_date": "20240131",
    }
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["trade_date"] == "2024-01-02"
    assert row["open_price"] == "3000.0"
    assert row["high_price"] == "3010.0"
    assert row["low_price"] == "2990.0"
    assert row["close_price"] == "3005.0"


def test_benchmark_symbol_helpers_convert_csindex_codes() -> None:
    assert benchmark_symbol_to_index_code("sh000300") == "000300"
    assert benchmark_symbol_to_index_code("000905") == "000905"
    assert index_code_to_benchmark_symbol("000852") == "sh000852"
    assert index_code_to_benchmark_symbol("399371") == "sz399371"


def test_fetch_index_members_weight_standardizes_csindex_columns() -> None:
    """CSIndex member weights should keep snapshot_date separate from trade_date."""
    captured: dict[str, str] = {}

    def fake_members(symbol: str) -> pd.DataFrame:
        captured["symbol"] = symbol
        return pd.DataFrame(
            [
                {
                    "日期": "20260601",
                    "指数代码": "000300",
                    "指数名称": "沪深300",
                    "成分券代码": "600519",
                    "成分券名称": "贵州茅台",
                    "交易所": "上海证券交易所",
                    "权重": 5.25,
                }
            ]
        )

    fake_ak = types.SimpleNamespace(index_stock_cons_weight_csindex=fake_members)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_index_members_weight("sh000300")

    assert result.is_success is True
    assert captured["symbol"] == "000300"
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["benchmark_symbol"] == "sh000300"
    assert row["index_code"] == "000300"
    assert row["snapshot_date"] == "20260601"
    assert row["stock_code"] == "600519"
    assert row["weight_pct"] == 5.25
    assert "trade_date" not in result.data.columns


def test_sw_industry_symbols_uses_level_one_info() -> None:
    """Full SW industry updates should iterate level-one industry symbols."""

    fake_ak = types.SimpleNamespace(
        sw_index_first_info=lambda: pd.DataFrame(
            {
                "行业代码": ["801120", "801780.SI"],
                "行业名称": ["食品饮料", "银行"],
            }
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    assert adapter._sw_industry_symbols() == ["801120.SI", "801780.SI"]


def test_fetch_sw_industry_membership_standardizes_level_one_rows() -> None:
    """SW third-level constituents should become level-one industry memberships."""
    captured: list[str] = []

    def fake_cons(symbol: str) -> pd.DataFrame:
        captured.append(symbol)
        return pd.DataFrame(
            [
                {
                    "股票代码": "600519",
                    "股票简称": "贵州茅台",
                    "纳入时间": "2021-12-13",
                    "申万1级": "食品饮料",
                    "申万2级": "白酒Ⅱ",
                    "申万3级": "白酒Ⅲ",
                }
            ]
        )

    fake_ak = types.SimpleNamespace(sw_index_third_cons=fake_cons)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_sw_industry_membership(symbols={"801120.SI"})

    assert result.is_success is True
    assert result.source_level == DataSourceLevel.C
    assert captured == ["801120.SI"]
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["stock_code"] == "600519"
    assert row["classification_type"] == "SW"
    assert row["level"] == 1
    assert row["industry_name"] == "食品饮料"
    assert row["effective_date"] == "2021-12-13"


def test_fetch_sw_industry_membership_falls_back_for_current_legulegu_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current Legulegu SW table has 18 columns and exchange-suffixed stock codes."""

    def broken_cons(symbol: str) -> pd.DataFrame:
        raise ValueError("Length mismatch: Expected axis has 18 elements, new values have 17 elements")

    class FakeResponse:
        text = """
        <table>
          <tr>
            <th>序号</th><th>股票代码</th><th>股票简称</th><th>纳入时间</th>
            <th>申万1级</th><th>细分概念</th><th>价格</th><th>市盈率</th>
            <th>市盈率ttm</th><th>市净率</th><th>ROE(%)</th><th>股息率</th>
            <th>市值（亿元）</th><th>近1日涨幅(2026-06-12)</th>
            <th>近5日涨幅(2026-06-12)</th><th>今年以来涨幅(2026-06-12)</th>
            <th>净利润增速(%)</th><th>营收增速(%)</th>
          </tr>
          <tr>
            <td>1</td><td>600419.SH</td><td>天润乳业</td><td>2018-07-13</td>
            <td>食品饮料</td><td>加载中...</td><td>8.03</td><td>61.08</td>
            <td>17.53</td><td>1.03</td><td>1.21%</td><td>0.25%</td>
            <td>25.34</td><td>1.52%</td><td>-3.25%</td><td>-19.11%</td>
            <td>140.58%</td><td>6.76%</td>
          </tr>
        </table>
        """

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, **kwargs) -> FakeResponse:
        assert "industryCode=801120.SI" in url
        return FakeResponse()

    fake_ak = types.SimpleNamespace(sw_index_third_cons=broken_cons)
    monkeypatch.setattr("fund_research.data.adapters.akshare.requests.get", fake_get)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_sw_industry_membership(symbols={"801120.SI"})

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["stock_code"] == "600419"
    assert row["stock_name"] == "天润乳业"
    assert row["industry_name"] == "食品饮料"
    assert row["effective_date"] == "2018-07-13"


def test_fetch_sw_industry_membership_falls_back_when_akshare_finds_no_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary empty AKShare parses should use the direct Legulegu fallback."""

    def broken_cons(symbol: str) -> pd.DataFrame:
        raise ValueError("No tables found")

    class FakeResponse:
        text = """
        <table>
          <tr>
            <th>股票代码</th><th>股票简称</th><th>纳入时间</th><th>申万1级</th>
          </tr>
          <tr>
            <td>000001.SZ</td><td>平安银行</td><td>2005-01-01</td><td>银行</td>
          </tr>
        </table>
        """

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, **kwargs) -> FakeResponse:
        assert "industryCode=801780.SI" in url
        return FakeResponse()

    fake_ak = types.SimpleNamespace(sw_index_third_cons=broken_cons)
    monkeypatch.setattr("fund_research.data.adapters.akshare.requests.get", fake_get)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_sw_industry_membership(symbols={"801780.SI"})

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["stock_code"] == "000001"
    assert row["industry_name"] == "银行"


def test_fetch_sw_industry_membership_keeps_partial_success() -> None:
    """One failed industry page should not discard other successfully fetched pages."""

    def fake_cons(symbol: str) -> pd.DataFrame:
        if symbol == "bad.SI":
            raise RuntimeError("429 Too Many Requests")
        return pd.DataFrame([{
            "股票代码": "600519.SH",
            "股票简称": "贵州茅台",
            "纳入时间": "2001-08-27",
            "申万1级": "食品饮料",
        }])

    fake_ak = types.SimpleNamespace(sw_index_third_cons=fake_cons)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_sw_industry_membership(symbols={"801120.SI", "bad.SI"})

    assert result.is_success is True
    assert result.data is not None
    assert len(result.data) == 1
    assert result.data.iloc[0]["stock_code"] == "600519"
    assert any("bad.SI 拉取失败" in warning for warning in result.warnings)


def test_fetch_sw_industry_membership_retries_before_warning() -> None:
    """A transient industry page failure should be retried before warning."""
    attempts = {"801120.SI": 0}

    def flaky_cons(symbol: str) -> pd.DataFrame:
        attempts[symbol] += 1
        if attempts[symbol] == 1:
            raise RuntimeError("temporary 429")
        return pd.DataFrame([{
            "股票代码": "600519.SH",
            "股票简称": "贵州茅台",
            "纳入时间": "2001-08-27",
            "申万1级": "食品饮料",
        }])

    fake_ak = types.SimpleNamespace(sw_index_third_cons=flaky_cons)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_sw_industry_membership(
        symbols={"801120.SI"},
        max_retries=1,
    )

    assert result.is_success is True
    assert result.data is not None
    assert len(result.data) == 1
    assert attempts["801120.SI"] == 2
    assert result.warnings == []


def test_fetch_announcements_standardizes_pdf_columns() -> None:
    """Announcement aliases should expose canonical PDF evidence fields."""
    fake_ak = types.SimpleNamespace(
        fund_announcement_report_em=lambda symbol: pd.DataFrame(
            [
                {
                    "公告标题": "2024年年度报告",
                    "公告日期": "2025-03-31",
                    "公告链接": "https://static.cninfo.com.cn/finalpage/sample.PDF",
                }
            ]
        )
    )
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_announcements("000001")

    assert result.is_success is True
    assert result.data is not None
    row = result.data.iloc[0]
    assert row["title"] == "2024年年度报告"
    assert row["announcement_date"] == "2025-03-31"
    assert row["pdf_url"] == "https://static.cninfo.com.cn/finalpage/sample.PDF"


def test_adapter_wraps_akshare_errors() -> None:
    """AKShare exceptions should become failed FetchResult values."""

    def broken_call() -> pd.DataFrame:
        raise RuntimeError("network down")

    fake_ak = types.SimpleNamespace(fund_name_em=broken_call)
    adapter = AkshareAdapter(ak_module=fake_ak)

    result = adapter.fetch_fund_list()

    assert result.is_success is False
    assert result.error_message == "network down"
    assert result.warnings == ["AKShare 接口调用失败: network down"]
