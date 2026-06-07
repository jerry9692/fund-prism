"""AKShare data adapter for Phase 1."""

from collections.abc import Callable
from datetime import date
from time import perf_counter
from types import ModuleType
from typing import Any

import pandas as pd

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.base import BaseDataAdapter, FetchResult

COLUMN_MAP = {
    "基金代码": "fund_code",
    "基金名称": "fund_name",
    "基金简称": "short_name",
    "基金全称": "full_name",
    "基金类型": "fund_type_raw",
    "基金公司": "company_name",
    "基金管理人": "company_name",
    "基金经理": "manager_names_raw",
    "基金经理ID": "manager_id",
    "基金经理编号": "manager_id",
    "经理ID": "manager_id",
    "姓名": "name",
    "基金经理姓名": "name",
    "现任基金代码": "current_fund_codes",
    "现任基金": "current_fund_codes",
    "任职日期": "start_date",
    "起始日期": "start_date",
    "任职起始日": "start_date",
    "离任日期": "end_date",
    "任职结束日": "end_date",
    "从业年限": "experience_years",
    "累计从业时间": "experience_years",
    "学历": "education",
    "托管银行": "custodian_bank",
    "基金托管人": "custodian_bank",
    "成立时间": "inception_date",
    "成立日期": "inception_date",
    "业绩比较基准": "benchmark",
    "最新规模": "total_nav",
    "基金规模": "total_nav",
    "资产净值": "total_nav",
    "总资产净值": "total_nav",
    "总份额": "total_share",
    "基金总份额": "total_share",
    "份额变动": "share_change",
    "管理费率": "mgmt_fee_pct",
    "基金管理费率": "mgmt_fee_pct",
    "托管费率": "custody_fee_pct",
    "基金托管费率": "custody_fee_pct",
    "销售服务费率": "sales_service_fee_pct",
    "申购费率": "subscribe_fee_range",
    "赎回费率": "redeem_fee_range",
    "费率生效日期": "effective_date",
    "截止日期": "report_date",
    "机构持有比列": "institutional_pct",
    "机构持有比例": "institutional_pct",
    "个人持有比列": "individual_pct",
    "个人持有比例": "individual_pct",
    "内部持有比列": "employee_pct",
    "内部持有比例": "employee_pct",
    "持有人户数": "total_holders",
    "户均持有份额": "avg_holding",
    "净值日期": "trade_date",
    "净值时间": "trade_date",
    "单位净值": "unit_nav",
    "累计净值": "accumulated_nav",
    "日增长率": "daily_return",
    "日涨跌幅": "daily_return",
    "涨跌幅": "daily_return",
    "涨幅": "daily_return",
    "分红": "dividend",
    "分红金额": "dividend",
    "每份分红": "dividend",
    "派息": "dividend",
    "分红发放日": "dividend_date",
    "现金红利发放日": "dividend_date",
    "除息日": "dividend_date",
    "权益登记日": "record_date",
    "股票代码": "stock_code",
    "股票名称": "stock_name",
    "行业名称": "industry_name",
    "持仓占比": "weight_pct",
    "占净值比例": "weight_pct",
    "占净值比例(%)": "weight_pct",
    "市值": "market_value",
    "持股数": "shares",
    "持股数量": "shares",
    "持股市值": "market_value",
    "持仓市值": "market_value",
    "本期累计买入金额": "cumulative_buy_amount",
    "本期累计卖出金额": "cumulative_sell_amount",
    "占期初基金资产净值比例": "pct_of_beginning_nav",
    "截止时间": "report_date",
    "序号": "rank_in_holdings",
    "排名": "rank_in_holdings",
    "季度": "report_date",
    "报告期": "report_date",
    "日期": "trade_date",
    "开盘": "open_price",
    "收盘": "close_price",
    "最高": "high_price",
    "最低": "low_price",
    "成交量": "volume",
    "成交额": "amount",
    "成交额(元)": "amount",
    "换手率": "turnover_rate",
    "公告标题": "title",
    "标题": "title",
    "公告类型": "announcement_type",
    "公告日期": "announcement_date",
    "发布日期": "announcement_date",
    "PDF链接": "pdf_url",
    "pdf链接": "pdf_url",
    "公告链接": "pdf_url",
    "附件链接": "pdf_url",
    "链接": "pdf_url",
    "url": "pdf_url",
    "date": "trade_date",
    "Date": "trade_date",
    "open": "open_price",
    "Open": "open_price",
    "high": "high_price",
    "High": "high_price",
    "low": "low_price",
    "Low": "low_price",
    "close": "close_price",
    "Close": "close_price",
    "volume": "volume",
    "Volume": "volume",
    "amount": "amount",
    "Amount": "amount",
}


class AkshareAdapter(BaseDataAdapter):
    """AKShare adapter with Phase 0 verified interface paths."""

    def __init__(self, ak_module: ModuleType | None = None):
        super().__init__(
            source_name="akshare",
            source_type=DataSourceType.OPEN_API,
            source_level=DataSourceLevel.B,
        )
        self._ak = ak_module

    @property
    def ak(self) -> ModuleType:
        """Import AKShare lazily so tests can inject a fake module."""
        if self._ak is None:
            import akshare as ak

            self._ak = ak
        return self._ak

    def _success_result(
        self,
        entity_type: str,
        data: pd.DataFrame,
        started_at: float,
        trade_date: date | None = None,
    ) -> FetchResult:
        standardized = self._standardize(data)
        missing_fields = {
            col: int(standardized[col].isna().sum())
            for col in standardized.columns
            if standardized[col].isna().any()
        }
        total_cells = len(standardized) * max(len(standardized.columns), 1)
        coverage_rate = (
            1.0 - (sum(missing_fields.values()) / total_cells) if total_cells else 0.0
        )
        return FetchResult(
            source_name=self.source_name,
            source_type=self.source_type,
            source_level=self.source_level,
            entity_type=entity_type,
            trade_date=trade_date,
            data=standardized,
            record_count=len(standardized),
            field_count=len(standardized.columns),
            coverage_rate=coverage_rate,
            missing_fields=missing_fields,
            fetch_duration_ms=(perf_counter() - started_at) * 1000,
        )

    def _error_result(self, entity_type: str, started_at: float, error: Exception) -> FetchResult:
        return FetchResult(
            source_name=self.source_name,
            source_type=self.source_type,
            source_level=self.source_level,
            entity_type=entity_type,
            is_success=False,
            error_message=str(error),
            fetch_duration_ms=(perf_counter() - started_at) * 1000,
            warnings=[f"AKShare 接口调用失败: {error}"],
        )

    def _call(
        self,
        entity_type: str,
        func: Callable[..., Any],
        *args: Any,
        trade_date: date | None = None,
        **kwargs: Any,
    ) -> FetchResult:
        started_at = perf_counter()
        try:
            data = func(*args, **kwargs)
            if not isinstance(data, pd.DataFrame):
                data = pd.DataFrame(data)
            return self._success_result(entity_type, data, started_at, trade_date)
        except Exception as exc:
            return self._error_result(entity_type, started_at, exc)

    def _standardize(self, data: pd.DataFrame) -> pd.DataFrame:
        standardized = data.copy()
        if len(standardized.columns) >= 2 and "item" in standardized.columns:
            key_col = "item"
            value_col = "value" if "value" in standardized.columns else standardized.columns[1]
            row = {
                COLUMN_MAP.get(str(item), str(item)): value
                for item, value in zip(standardized[key_col], standardized[value_col], strict=False)
            }
            standardized = pd.DataFrame([row])

        standardized = standardized.rename(columns=COLUMN_MAP)
        if "daily_return" in standardized.columns:
            standardized["daily_return"] = pd.to_numeric(
                standardized["daily_return"], errors="coerce"
            ) / 100
        return standardized

    def fetch_fund_list(self) -> FetchResult:
        """拉取基金列表。"""
        return self._call("fund_list", self.ak.fund_name_em)

    def fetch_fund_nav(
        self, fund_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取基金单位净值走势。"""
        return self._call(
            "fund_nav",
            self.ak.fund_open_fund_info_em,
            symbol=fund_code,
            indicator="单位净值走势",
        )

    def fetch_fund_dividends(self, fund_code: str, year: int | None = None) -> FetchResult:
        """拉取基金分红记录；AKShare 该接口按年份返回全表，本地再按基金代码过滤。"""
        target_year = str(year or date.today().year)
        result = self._call("fund_dividends", self.ak.fund_fh_em, year=target_year, page=-1)
        if result.is_success and result.data is not None and "fund_code" in result.data:
            fund_codes = result.data["fund_code"].astype(str).str.zfill(6)
            result.data = result.data[fund_codes == fund_code]
            result.record_count = len(result.data)
        return result

    def fetch_fund_holdings(self, fund_code: str, report_date: date | None = None) -> FetchResult:
        """拉取基金公开持仓。"""
        year = str((report_date or date.today()).year)
        return self._call(
            "fund_holdings",
            self.ak.fund_portfolio_hold_em,
            symbol=fund_code,
            date=year,
        )

    def fetch_fund_industry_allocation(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        """拉取基金披露行业配置。"""
        year = str((report_date or date.today()).year)
        return self._call(
            "fund_industry_allocation",
            self.ak.fund_portfolio_industry_allocation_em,
            symbol=fund_code,
            date=year,
        )

    def fetch_fund_portfolio_change(
        self, fund_code: str, report_date: date | None = None
    ) -> FetchResult:
        """拉取基金披露持仓变动明细。"""
        year = str((report_date or date.today()).year)
        result = self._call(
            "fund_portfolio_change",
            self.ak.fund_portfolio_change_em,
            symbol=fund_code,
            date=year,
        )
        if (
            not result.is_success
            and result.error_message is not None
            and "序号" in result.error_message
        ):
            result.is_success = True
            result.error_message = None
            result.data = pd.DataFrame()
            result.record_count = 0
            result.field_count = 0
            result.coverage_rate = 0.0
            result.warnings = [f"基金持仓变动为空或尚未披露: {fund_code}/{year}"]
        if result.is_success and result.data is not None and "report_date" in result.data:
            result.data = result.data.rename(columns={"report_date": "report_period"})
        return result

    def fetch_fund_info(self, fund_code: str) -> FetchResult:
        """拉取基金基本信息。"""
        return self._call("fund_info", self.ak.fund_individual_basic_info_xq, symbol=fund_code)

    def fetch_fund_scale(self, fund_code: str) -> FetchResult:
        """拉取基金最新规模快照。"""
        return self._call("fund_scale", self.ak.fund_individual_basic_info_xq, symbol=fund_code)

    def fetch_holder_structure(self, fund_code: str) -> FetchResult:
        """拉取基金持有人结构。"""
        if hasattr(self.ak, "fund_individual_hold_info"):
            return self._call(
                "holder_structure", self.ak.fund_individual_hold_info, symbol=fund_code
            )
        message = (
            "当前 AKShare fund_hold_structure_em 为全市场汇总接口，不含基金代码，"
            "不能作为单基金持有人结构入库"
        )
        return FetchResult(
            source_name=self.source_name,
            source_type=self.source_type,
            source_level=self.source_level,
            entity_type="holder_structure",
            is_success=False,
            error_message=message,
            data=pd.DataFrame(),
            warnings=[message],
        )

    def fetch_fund_managers(self, fund_code: str) -> FetchResult:
        """拉取基金经理全量表。"""
        result = self._call("fund_managers", self.ak.fund_manager_em)
        if result.is_success and result.data is not None and "current_fund_codes" in result.data:
            result.data = result.data[
                result.data["current_fund_codes"].fillna("").astype(str).str.contains(fund_code)
            ]
            result.record_count = len(result.data)
        return result

    def fetch_stock_daily(
        self, stock_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取股票日行情，优先使用 Phase 0 验证通过的腾讯路径。"""
        symbol = stock_code
        if stock_code.isdigit() and len(stock_code) == 6:
            symbol = f"sh{stock_code}" if stock_code.startswith("6") else f"sz{stock_code}"
        return self._call(
            "stock_daily",
            self.ak.stock_zh_a_hist_tx,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d") if start_date else "19700101",
            end_date=end_date.strftime("%Y%m%d") if end_date else date.today().strftime("%Y%m%d"),
        )

    def fetch_index_daily(
        self, symbol: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取指数日行情。"""
        return self._call(
            "index_daily",
            self.ak.stock_zh_index_daily_tx,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d") if start_date else "",
            end_date=end_date.strftime("%Y%m%d") if end_date else "",
        )

    def fetch_fee_detail(self, fund_code: str) -> FetchResult:
        """拉取基金费率详情。"""
        return self._call(
            "fund_fee_detail",
            self.ak.fund_individual_detail_info_xq,
            symbol=fund_code,
        )

    def fetch_announcements(self, fund_code: str) -> FetchResult:
        """拉取基金公告列表。"""
        return self._call(
            "fund_announcements", self.ak.fund_announcement_report_em, symbol=fund_code
        )

    def check_health(self) -> dict:
        """检查 AKShare 是否可导入并返回版本。"""
        try:
            version = getattr(self.ak, "__version__", "unknown")
            return {"source": self.source_name, "ok": True, "version": version}
        except Exception as exc:
            return {"source": self.source_name, "ok": False, "error": str(exc)}
