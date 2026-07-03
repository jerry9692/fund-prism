"""AKShare data adapter for Phase 1."""

import hashlib
import re
from collections.abc import Callable
from datetime import date
from io import StringIO
from time import perf_counter, sleep
from types import ModuleType
from typing import Any

import pandas as pd
import requests

from fund_research.core.enums import DataSourceLevel, DataSourceType
from fund_research.data.adapters.base import BaseDataAdapter, FetchResult

EASTMONEY_F10_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fundf10.eastmoney.com/",
}

COLUMN_MAP = {
    "基金代码": "fund_code",
    "基金名称": "fund_name",
    "基金简称": "short_name",
    "基金全称": "full_name",
    "基金类型": "fund_type_raw",
    "基金公司": "company_name",
    "基金管理人": "company_name",
    "所属公司": "company_name",
    "基金经理": "manager_names_raw",
    "基金经理ID": "manager_id",
    "基金经理编号": "manager_id",
    "经理ID": "manager_id",
    "姓名": "name",
    "基金经理姓名": "name",
    "现任基金代码": "current_fund_codes",
    "现任基金": "current_fund_names",
    "现任基金资产总规模": "current_fund_aum",
    "现任基金最佳回报": "best_return",
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
    "费用类型": "fee_type",
    "条件或名称": "fee_name",
    "费用": "fee_value",
    "截止日期": "report_date",
    "起始期": "start_date",
    "截止期": "end_date",
    "任职期间": "tenure_period_desc",
    "任职回报": "tenure_return",
    "总份额（亿份）": "total_share_yi",
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
    "行业类别": "industry_name",
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


def _coalesce_duplicate_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Coalesce duplicate canonical columns after alias renaming."""
    if not data.columns.has_duplicates:
        return data

    coalesced = pd.DataFrame(index=data.index)
    for column in dict.fromkeys(data.columns):
        same_name = data.loc[:, data.columns == column]
        if isinstance(same_name, pd.Series):
            coalesced[column] = same_name
        else:
            coalesced[column] = same_name.bfill(axis=1).iloc[:, 0]
    return coalesced


def benchmark_symbol_to_index_code(symbol: str) -> str:
    """Convert local benchmark symbol to CSIndex code."""
    normalized = str(symbol).strip().lower()
    if len(normalized) == 8 and normalized[:2] in {"sh", "sz"}:
        return normalized[2:]
    return normalized.zfill(6) if normalized.isdigit() else normalized


def index_code_to_benchmark_symbol(index_code: str) -> str:
    """Convert a source index code to the local benchmark symbol convention."""
    code = str(index_code).strip()
    if len(code) == 8 and code[:2].lower() in {"sh", "sz"}:
        return code.lower()
    code = code.zfill(6) if code.isdigit() else code
    return f"sz{code}" if code.startswith("399") else f"sh{code}"


def _manager_id_from_identity(name: str, company_name: str | None = None) -> str:
    identity = f"{company_name or ''}:{name}"
    digest = hashlib.sha1(identity.encode()).hexdigest()[:12]
    return f"ak_mgr_{digest}"


def _format_fee_rule(condition: Any, fee: Any) -> str:
    return f"{condition}: {fee}"


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
        max_retries: int = 3,
        **kwargs: Any,
    ) -> FetchResult:
        started_at = perf_counter()
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                data = func(*args, **kwargs)
                if not isinstance(data, pd.DataFrame):
                    data = pd.DataFrame(data)
                return self._success_result(entity_type, data, started_at, trade_date)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    sleep(2 ** attempt)
        return self._error_result(entity_type, started_at, last_exc if last_exc else Exception("Unknown error"))

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
        standardized = _coalesce_duplicate_columns(standardized)
        if "daily_return" in standardized.columns:
            standardized["daily_return"] = pd.to_numeric(
                standardized["daily_return"], errors="coerce"
            )
            max_abs = standardized["daily_return"].abs().max()
            if pd.notna(max_abs) and max_abs > 1:
                standardized["daily_return"] = standardized["daily_return"] / 100
        return standardized

    def _success_result_from_canonical(
        self,
        entity_type: str,
        data: pd.DataFrame,
        started_at: float,
        *,
        source_level: DataSourceLevel | None = None,
    ) -> FetchResult:
        result = self._success_result(entity_type, data, started_at)
        if source_level is not None:
            result.source_level = source_level
        return result

    def _fetch_index_members(self, symbol: str, *, include_weight: bool) -> FetchResult:
        index_code = benchmark_symbol_to_index_code(symbol)
        benchmark_symbol = index_code_to_benchmark_symbol(index_code)
        func = (
            self.ak.index_stock_cons_weight_csindex
            if include_weight
            else self.ak.index_stock_cons_csindex
        )
        started_at = perf_counter()
        try:
            data = pd.DataFrame(func(index_code)).rename(
                columns={
                    "日期": "snapshot_date",
                    "指数代码": "index_code",
                    "指数名称": "index_name",
                    "成分券代码": "stock_code",
                    "成分券名称": "stock_name",
                    "交易所": "exchange",
                    "权重": "weight_pct",
                }
            )
            for column in ("index_code", "stock_code"):
                if column in data.columns:
                    data[column] = data[column].astype(str).str.zfill(6)
            if "weight_pct" not in data.columns:
                data["weight_pct"] = None
            data["benchmark_symbol"] = benchmark_symbol
            columns = [
                "benchmark_symbol",
                "index_code",
                "index_name",
                "snapshot_date",
                "stock_code",
                "stock_name",
                "exchange",
                "weight_pct",
            ]
            return self._success_result_from_canonical(
                "benchmark_index_member",
                data[columns],
                started_at,
                source_level=DataSourceLevel.B,
            )
        except Exception as exc:
            return self._error_result("benchmark_index_member", started_at, exc)

    def _sw_industry_symbols(self) -> list[str]:
        data = pd.DataFrame(self.ak.sw_index_first_info())
        if "行业代码" not in data.columns:
            return []
        return [
            f"{code}.SI" if not str(code).endswith(".SI") else str(code)
            for code in data["行业代码"].dropna().astype(str)
        ]

    def _fetch_sw_industry_membership_frame(self, symbol: str) -> pd.DataFrame:
        try:
            return pd.DataFrame(self.ak.sw_index_third_cons(symbol))
        except ValueError as exc:
            message = str(exc)
            if "Length mismatch" not in message and "No tables found" not in message:
                raise
            url = f"https://legulegu.com/stockdata/index-composition?industryCode={symbol}"
            response = requests.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/114.0.0.0 Safari/537.36"
                    )
                },
                timeout=30,
            )
            response.raise_for_status()
            return pd.read_html(StringIO(response.text))[0]

    def _normalize_sw_industry_membership(self, frames: list[pd.DataFrame]) -> pd.DataFrame:
        data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        columns = [
            "stock_code",
            "stock_name",
            "classification_type",
            "classification_version",
            "level",
            "industry_code",
            "industry_name",
            "parent_industry_code",
            "effective_date",
        ]
        if data.empty:
            return pd.DataFrame(columns=columns)
        data = data.rename(
            columns={
                "股票代码": "stock_code",
                "股票简称": "stock_name",
                "申万1级": "sw_level_1",
                "纳入时间": "effective_date",
            }
        )
        result = pd.DataFrame()
        result["stock_code"] = data["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False)
        result["stock_name"] = data["stock_name"] if "stock_name" in data.columns else None
        result["classification_type"] = "SW"
        result["classification_version"] = "unknown"
        result["level"] = 1
        result["industry_code"] = None
        result["industry_name"] = data["sw_level_1"] if "sw_level_1" in data.columns else None
        result["parent_industry_code"] = None
        result["effective_date"] = (
            data["effective_date"] if "effective_date" in data.columns else date.today()
        )
        return result.dropna(subset=["stock_code", "industry_name"])[columns]

    def _normalize_fee_detail(self, data: pd.DataFrame) -> pd.DataFrame:
        if not {"fee_type", "fee_name", "fee_value"}.issubset(data.columns):
            return data

        rows = data.copy()
        fee_name = rows["fee_name"].fillna("").astype(str)
        fee_type = rows["fee_type"].fillna("").astype(str)

        def first_fee(keyword: str) -> Any:
            matches = rows[fee_name.str.contains(keyword, regex=False)]
            if matches.empty:
                return None
            return matches.iloc[0]["fee_value"]

        buy_rules = rows[fee_type.str.contains("买入", regex=False)]
        sell_rules = rows[fee_type.str.contains("卖出", regex=False)]
        normalized = {
            "mgmt_fee_pct": first_fee("管理费"),
            "custody_fee_pct": first_fee("托管费"),
            "sales_service_fee_pct": first_fee("销售服务费"),
            "subscribe_fee_range": "; ".join(
                _format_fee_rule(row["fee_name"], row["fee_value"])
                for row in buy_rules.to_dict(orient="records")
            )
            or None,
            "redeem_fee_range": "; ".join(
                _format_fee_rule(row["fee_name"], row["fee_value"])
                for row in sell_rules.to_dict(orient="records")
            )
            or None,
        }
        return pd.DataFrame([normalized])

    def fetch_fund_list(self) -> FetchResult:
        """拉取基金列表。"""
        return self._call("fund_list", self.ak.fund_name_em)

    def fetch_fund_nav(
        self, fund_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取基金单位净值走势。"""
        result = self._call(
            "fund_nav",
            self.ak.fund_open_fund_info_em,
            symbol=fund_code,
            indicator="单位净值走势",
        )
        if result.is_success and result.data is not None and "trade_date" in result.data.columns:
            df = result.data
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
            if start_date is not None:
                df = df[df["trade_date"] >= pd.Timestamp(start_date)]
            if end_date is not None:
                df = df[df["trade_date"] <= pd.Timestamp(end_date)]
            result.data = df.reset_index(drop=True)
            result.record_count = len(result.data)
        return result

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

    def fetch_fund_scale_history(self, fund_code: str) -> FetchResult:
        """拉取基金季度规模变动历史（东方财富 F10 gmbd 接口，C级数据源）。

        东方财富 F10 规模变动表提供自基金成立以来的季度申购/赎回/份额/净资产数据，
        按季度披露。返回的 DataFrame 每行一个季度报告期。
        """
        import re as _re

        started_at = perf_counter()
        url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    url,
                    headers=EASTMONEY_F10_HEADERS,
                    params={"type": "gmbd", "code": fund_code, "per": 49, "page": 1},
                    timeout=15,
                )
                resp.raise_for_status()
                resp.encoding = "utf-8"
                match = _re.search(r'content:"(.*?)",erro', resp.text, _re.DOTALL)
                if not match:
                    match = _re.search(r'content:"(.*?)"', resp.text, _re.DOTALL)
                if not match or "<table" not in resp.text:
                    if attempt < max_retries - 1:
                        sleep(1.5 * (attempt + 1))
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="fund_scale",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"基金规模变动页面解析失败: {fund_code}"],
                    )
                html = match.group(1).replace("\\", "")
                tables = []
                if html and html.strip():
                    try:
                        tables = pd.read_html(StringIO(html))
                    except ValueError:
                        tables = []
                if not tables:
                    if attempt < max_retries - 1:
                        sleep(1.5 * (attempt + 1))
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="fund_scale",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"基金规模变动暂无数据: {fund_code}"],
                    )
                raw = tables[0]
                col_map = {
                    "日期": "report_date",
                    "期末总份额（亿份）": "total_share_yi",
                    "期末净资产（亿元）": "total_nav_yi",
                    "期间申购（亿份）": "subscribe_share_yi",
                    "期间赎回（亿份）": "redeem_share_yi",
                    "净资产变动率": "nav_change_pct",
                }
                standardized = raw.rename(columns=col_map)
                standardized = _coalesce_duplicate_columns(standardized)
                if "report_date" not in standardized.columns:
                    if attempt < max_retries - 1:
                        sleep(1.5 * (attempt + 1))
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="fund_scale",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"基金规模变动列名异常: {fund_code}"],
                    )
                standardized["report_date"] = pd.to_datetime(standardized["report_date"], errors="coerce")
                standardized = standardized.dropna(subset=["report_date"])
                for col in ("total_share_yi", "total_nav_yi", "subscribe_share_yi", "redeem_share_yi"):
                    if col in standardized.columns:
                        standardized[col] = pd.to_numeric(
                            standardized[col].astype(str).str.replace(",", ""), errors="coerce"
                        )
                if "total_nav_yi" in standardized.columns:
                    standardized["total_nav"] = standardized["total_nav_yi"]
                if "total_share_yi" in standardized.columns:
                    standardized["total_share"] = standardized["total_share_yi"]
                if "subscribe_share_yi" in standardized.columns and "redeem_share_yi" in standardized.columns:
                    sub = pd.to_numeric(
                        standardized.get("subscribe_share_yi", pd.Series([0.0] * len(standardized))),
                        errors="coerce",
                    ).fillna(0)
                    red = pd.to_numeric(
                        standardized.get("redeem_share_yi", pd.Series([0.0] * len(standardized))),
                        errors="coerce",
                    ).fillna(0)
                    standardized["share_change"] = sub - red
                standardized["fund_code"] = fund_code
                result = self._success_result_from_canonical(
                    "fund_scale",
                    standardized,
                    started_at,
                    source_level=DataSourceLevel.C,
                )
                result.source_name = "eastmoney_f10"
                result.source_type = DataSourceType.WEB_SCRAPING
                return result
            except Exception as exc:
                if attempt < max_retries - 1:
                    sleep(1.5 * (attempt + 1))
                    continue
                return self._error_result("fund_scale", started_at, exc)
        return self._error_result(
            "fund_scale", started_at, RuntimeError(f"重试{max_retries}次后仍失败: {fund_code}")
        )

    def fetch_holder_structure(self, fund_code: str) -> FetchResult:
        """拉取基金持有人结构（东方财富 F10 AJAX 接口，C级数据源）。

        原 AKShare ``fund_individual_hold_info`` 在当前版本不存在，
        ``fund_hold_structure_em`` 为全市场汇总不含单基金代码。
        改为直接请求东方财富 F10 的 FundArchivesDatas.aspx 接口，
        返回该基金自成立以来的半年度持有人结构历史。
        """
        import re as _re

        started_at = perf_counter()
        url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    url,
                    headers=EASTMONEY_F10_HEADERS,
                    params={"type": "cyrjg", "code": fund_code},
                    timeout=15,
                )
                resp.raise_for_status()
                resp.encoding = "utf-8"
                match = _re.search(r'content:"(.*?)",summary', resp.text, _re.DOTALL)
                if not match:
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                        continue
                    return self._error_result(
                        "holder_structure",
                        started_at,
                        RuntimeError(f"无法解析持有人结构响应: {fund_code}"),
                    )
                html = match.group(1).replace("\\", "")
                tables: list[pd.DataFrame] = []
                if html and html.strip():
                    try:
                        tables = pd.read_html(StringIO(html))
                    except ValueError:
                        tables = []
                if not tables:
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="holder_structure",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"持有人结构暂无数据: {fund_code}"],
                    )
                raw = tables[0]
                standardized = raw.rename(columns=COLUMN_MAP)
                standardized = _coalesce_duplicate_columns(standardized)
                if "announcement_date" in standardized.columns and "report_date" not in standardized.columns:
                    standardized = standardized.rename(columns={"announcement_date": "report_date"})
                for col in ("institutional_pct", "individual_pct", "employee_pct"):
                    if col in standardized.columns:
                        standardized[col] = (
                            standardized[col]
                            .astype(str)
                            .str.replace("%", "", regex=False)
                            .apply(pd.to_numeric, errors="coerce")
                        )
                if "total_share_yi" in standardized.columns:
                    standardized["total_share"] = (
                        pd.to_numeric(standardized["total_share_yi"], errors="coerce") * 1e8
                    )
                standardized["fund_code"] = fund_code
                result = self._success_result_from_canonical(
                    "holder_structure",
                    standardized,
                    started_at,
                    source_level=DataSourceLevel.C,
                )
                result.source_name = "eastmoney_f10"
                result.source_type = DataSourceType.WEB_SCRAPING
                return result
            except Exception as exc:
                if attempt < max_retries - 1:
                    sleep(2 ** attempt)
                    continue
                return self._error_result("holder_structure", started_at, exc)
        return self._error_result(
            "holder_structure", started_at, RuntimeError(f"重试{max_retries}次后仍失败: {fund_code}")
        )

    def fetch_fund_manager_history(self, fund_code: str) -> FetchResult:
        """拉取基金历任经理任期历史（东方财富 F10 jjjl 页面，C级数据源）。

        东方财富 F10 基金经理变动表提供自基金成立以来的完整任期记录，
        包括起始期、截止期、经理姓名（多人空格分隔）、任职回报。
        返回的 DataFrame 每个经理-任期一行（多经理行会拆分为多行）。

        在 ``pd.read_html`` 去除 HTML 标签之前，先用正则从
        ``<a href=".../manager/XXXXXXX.html">姓名</a>`` 中提取东方财富
        经理ID，以 ``em_mgr_XXXXXXX`` 作为稳定的 ``manager_id``（比基于
        姓名+公司的哈希更稳定，也解决了与 ``fetch_fund_managers`` 的
        ID 一致性问题）。
        """
        started_at = perf_counter()
        url = f"https://fundf10.eastmoney.com/jjjl_{fund_code}.html"
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=EASTMONEY_F10_HEADERS, timeout=15)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                if "起始期" not in resp.text:
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="fund_manager_tenure",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"基金经理任期页内容异常（可能反爬）: {fund_code}"],
                    )

                # --- Extract Eastmoney manager IDs from <a> tags BEFORE pd.read_html ---
                # pd.read_html strips tags, so we parse the raw HTML first to build a
                # name -> em_mgr_id mapping.  Links look like:
                #   <a href="http://fund.eastmoney.com/manager/1234567.html">张三</a>
                # We use a dict so that repeated occurrences of the same name collapse
                # to the same (correct) manager ID.
                em_manager_id_map: dict[str, str] = {}
                for m_id, m_name in re.findall(
                    r"manager/(\d+)\.html[^>]*>([^<]+)</a>", resp.text
                ):
                    clean_name = m_name.strip()
                    if clean_name and clean_name not in em_manager_id_map:
                        em_manager_id_map[clean_name] = f"em_mgr_{m_id}"

                tables = pd.read_html(StringIO(resp.text))
                if len(tables) < 2:
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="fund_manager_tenure",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"基金经理任期表解析失败: {fund_code}"],
                    )
                raw = tables[1]
                if "起始期" not in raw.columns:
                    raw = tables[0]
                if "起始期" not in raw.columns:
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                        continue
                    return FetchResult(
                        source_name="eastmoney_f10",
                        source_type=DataSourceType.WEB_SCRAPING,
                        source_level=DataSourceLevel.C,
                        entity_type="fund_manager_tenure",
                        is_success=True,
                        data=pd.DataFrame(),
                        record_count=0,
                        field_count=0,
                        coverage_rate=0.0,
                        fetch_duration_ms=(perf_counter() - started_at) * 1000,
                        warnings=[f"基金经理任期表列名异常: {fund_code}"],
                    )
                break
            except Exception as exc:
                if attempt < max_retries - 1:
                    sleep(2 ** attempt)
                    continue
                return self._error_result("fund_manager_tenure", started_at, exc)
        else:
            return self._error_result(
                "fund_manager_tenure",
                started_at,
                RuntimeError(f"重试{max_retries}次后仍失败: {fund_code}"),
            )

        raw = raw.rename(columns=COLUMN_MAP)
        raw = _coalesce_duplicate_columns(raw)
        rows: list[dict] = []
        for _idx, row in raw.iterrows():
            start_raw = str(row.get("start_date", "")).strip()
            end_raw = str(row.get("end_date", "")).strip()
            names_raw = str(row.get("manager_names_raw", "")).strip()
            ret_raw = row.get("tenure_return")
            tenure_ret: float | None = None
            if ret_raw is not None and str(ret_raw).strip() not in {"--", "", "nan"}:
                tenure_ret = (
                    pd.to_numeric(
                        str(ret_raw).replace("%", "").replace(",", ""),
                        errors="coerce",
                    )
                    / 100.0
                )
            if not names_raw or not start_raw or start_raw == "nan":
                continue
            names = [n for n in names_raw.split() if n]
            for name in names:
                end_date_val: date | None = None
                if end_raw and end_raw != "至今" and end_raw != "nan":
                    parsed = pd.to_datetime(end_raw, errors="coerce")
                    if pd.notna(parsed):
                        end_date_val = parsed.date()
                start_parsed = pd.to_datetime(start_raw, errors="coerce")
                start_date_val: date | None = None
                if pd.notna(start_parsed):
                    start_date_val = start_parsed.date()
                if start_date_val is None:
                    continue
                # Use Eastmoney manager ID if extracted from HTML; fall back to
                # hash-based ID (without company, as company is not available on
                # this page) for any names whose links were not captured.
                manager_id = em_manager_id_map.get(name) or _manager_id_from_identity(name)
                is_current = end_date_val is None
                tenure_days: int | None = None
                if is_current:
                    tenure_days = (date.today() - start_date_val).days
                else:
                    tenure_days = (end_date_val - start_date_val).days
                rows.append(
                    {
                        "name": name,
                        "manager_id": manager_id,
                        "fund_code": fund_code,
                        "start_date": start_date_val,
                        "end_date": end_date_val,
                        "is_current": is_current,
                        "tenure_days": tenure_days,
                        "tenure_return": (
                            float(tenure_ret) if tenure_ret is not None else None
                        ),
                    }
                )
        data = pd.DataFrame(rows)
        result = self._success_result_from_canonical(
            "fund_manager_tenure",
            data,
            started_at,
            source_level=DataSourceLevel.C,
        )
        result.source_name = "eastmoney_f10"
        result.source_type = DataSourceType.WEB_SCRAPING
        return result

    def fetch_fund_managers(self, fund_code: str) -> FetchResult:
        """拉取基金经理全量表（AKShare 现任经理快照）。"""
        result = self._call("fund_managers", self.ak.fund_manager_em)
        if result.is_success and result.data is not None and "current_fund_codes" in result.data:
            result.data["current_fund_codes"] = (
                result.data["current_fund_codes"].astype(str).str.zfill(6)
            )
            result.data = result.data[
                result.data["current_fund_codes"].fillna("").astype(str) == fund_code
            ]
            if "manager_id" not in result.data.columns and "name" in result.data.columns:
                result.data = result.data.copy()
                company_names = (
                    result.data["company_name"]
                    if "company_name" in result.data.columns
                    else pd.Series([None] * len(result.data), index=result.data.index)
                )
                result.data["manager_id"] = [
                    _manager_id_from_identity(
                        str(name), str(company) if pd.notna(company) else None
                    )
                    for name, company in zip(result.data["name"], company_names, strict=False)
                ]
            # Normalize raw numeric Eastmoney manager IDs to em_mgr_ prefix so they
            # match the IDs extracted from the F10 history page HTML.
            if "manager_id" in result.data.columns:
                result.data = result.data.copy()
                mid = result.data["manager_id"].astype(str)
                numeric_mask = mid.str.fullmatch(r"\d+")
                result.data.loc[numeric_mask, "manager_id"] = (
                    "em_mgr_" + mid[numeric_mask]
                )
            if "experience_years" in result.data.columns:
                raw_experience = result.data["experience_years"]
                experience = pd.to_numeric(raw_experience, errors="coerce")
                normalized_experience = experience.where(experience <= 100, experience / 365.25)
                result.data["experience_years"] = normalized_experience.where(
                    experience.notna(), raw_experience
                )
            result.record_count = len(result.data)
            result.field_count = len(result.data.columns)
        return result

    def fetch_stock_daily(
        self, stock_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取股票日行情（腾讯源），自动补 daily_return。"""
        symbol = stock_code
        if stock_code.isdigit() and len(stock_code) == 6:
            symbol = f"sh{stock_code}" if stock_code.startswith("6") else f"sz{stock_code}"
        result = self._call(
            "stock_daily",
            self.ak.stock_zh_a_hist_tx,
            symbol=symbol,
            start_date=start_date.strftime("%Y%m%d") if start_date else "19700101",
            end_date=end_date.strftime("%Y%m%d") if end_date else date.today().strftime("%Y%m%d"),
        )
        # Tencent source lacks daily_return; compute from close_price
        df = result.data
        if df is not None and "close_price" in df.columns and "daily_return" not in df.columns:
            df = df.sort_values("trade_date")
            df["daily_return"] = df["close_price"].pct_change()
            result.data = df
        return result

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

    def fetch_index_members_weight(self, symbol: str) -> FetchResult:
        """拉取中证指数最新成分权重快照。"""
        return self._fetch_index_members(symbol, include_weight=True)

    def fetch_index_members(self, symbol: str) -> FetchResult:
        """拉取中证指数最新成分目录快照。"""
        return self._fetch_index_members(symbol, include_weight=False)

    def fetch_sw_industry_membership(
        self,
        symbols: set[str] | None = None,
        *,
        request_interval_seconds: float = 0.0,
        max_retries: int = 0,
    ) -> FetchResult:
        """拉取申万三级行业成分，并标准化为股票行业归属快照。"""
        started_at = perf_counter()
        try:
            target_symbols = sorted(symbols) if symbols else self._sw_industry_symbols()
            frames: list[pd.DataFrame] = []
            warnings: list[str] = []
            for index, symbol in enumerate(target_symbols):
                if index > 0 and request_interval_seconds > 0:
                    sleep(request_interval_seconds)
                for attempt in range(max_retries + 1):
                    try:
                        frames.append(self._fetch_sw_industry_membership_frame(symbol))
                        break
                    except Exception as exc:
                        if attempt < max_retries:
                            if request_interval_seconds > 0:
                                sleep(request_interval_seconds)
                            continue
                        warnings.append(f"{symbol} 拉取失败: {exc}")

            data = self._normalize_sw_industry_membership(frames)
            if data.empty and warnings:
                result = self._error_result(
                    "stock_industry_membership",
                    started_at,
                    RuntimeError("; ".join(warnings[:5])),
                )
                result.source_level = DataSourceLevel.C
                result.warnings = warnings
                return result
            result = self._success_result_from_canonical(
                "stock_industry_membership",
                data,
                started_at,
                source_level=DataSourceLevel.C,
            )
            result.warnings = warnings
            return result
        except Exception as exc:
            result = self._error_result("stock_industry_membership", started_at, exc)
            result.source_level = DataSourceLevel.C
            return result

    def fetch_fee_detail(self, fund_code: str) -> FetchResult:
        """拉取基金费率详情。"""
        result = self._call(
            "fund_fee_detail",
            self.ak.fund_individual_detail_info_xq,
            symbol=fund_code,
        )
        if result.is_success and result.data is not None:
            result.data = self._normalize_fee_detail(result.data)
            result.record_count = len(result.data)
            result.field_count = len(result.data.columns)
        return result

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
