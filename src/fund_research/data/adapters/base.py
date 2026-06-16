"""
数据源适配器基类。

定义所有数据源适配器必须实现的接口协议。
每个适配器负责从一种数据源拉取数据并返回标准化的 pandas DataFrame。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from fund_research.core.enums import DataSourceLevel, DataSourceType


@dataclass
class FetchResult:
    """单次数据拉取的结果封装。"""

    source_name: str
    source_type: DataSourceType
    source_level: DataSourceLevel
    entity_type: str  # fund_nav / fund_holdings / stock_daily 等
    fetch_timestamp: datetime = field(default_factory=datetime.now)
    trade_date: date | None = None

    # 数据
    data: pd.DataFrame | None = None
    record_count: int = 0
    field_count: int = 0

    # 质量
    coverage_rate: float = 0.0
    missing_fields: dict[str, int] = field(default_factory=dict)
    anomaly_count: int = 0

    # 状态
    is_success: bool = True
    error_message: str | None = None
    fetch_duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict:
        """输出可读摘要。"""
        return {
            "source": self.source_name,
            "source_type": self.source_type.value,
            "source_level": self.source_level.value,
            "entity": self.entity_type,
            "trade_date": str(self.trade_date) if self.trade_date else None,
            "records": self.record_count,
            "fields": self.field_count,
            "coverage": f"{self.coverage_rate:.1%}",
            "anomalies": self.anomaly_count,
            "success": self.is_success,
            "error": self.error_message,
            "warnings": self.warnings,
        }


class BaseDataAdapter(ABC):
    """
    数据源适配器抽象基类。

    所有数据源（AKShare、官方披露、本地文件等）都需实现此接口。
    """

    def __init__(
        self,
        source_name: str,
        source_type: DataSourceType,
        source_level: DataSourceLevel,
    ):
        self.source_name = source_name
        self.source_type = source_type
        self.source_level = source_level

    @abstractmethod
    def fetch_fund_list(self) -> FetchResult:
        """拉取基金列表。"""
        ...

    @abstractmethod
    def fetch_fund_nav(
        self, fund_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取基金净值。"""
        ...

    @abstractmethod
    def fetch_fund_holdings(self, fund_code: str, report_date: date | None = None) -> FetchResult:
        """拉取基金公开持仓。"""
        ...

    @abstractmethod
    def fetch_fund_info(self, fund_code: str) -> FetchResult:
        """拉取基金基本信息。"""
        ...

    @abstractmethod
    def fetch_fund_managers(self, fund_code: str) -> FetchResult:
        """拉取基金经理信息。"""
        ...

    @abstractmethod
    def fetch_stock_daily(
        self, stock_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> FetchResult:
        """拉取股票日行情。"""
        ...

    @abstractmethod
    def check_health(self) -> dict:
        """检查数据源健康状态（是否可达、响应时间等）。"""
        ...

    def supports(self, entity_type: str) -> bool:
        """检查是否支持拉取指定类型的数据。"""
        supported = [
            "fund_list",
            "fund_nav",
            "fund_dividends",
            "fund_holdings",
            "fund_industry_allocation",
            "fund_portfolio_change",
            "fund_info",
            "fund_managers",
            "fund_scale",
            "fund_fee_detail",
            "holder_structure",
            "stock_daily",
            "index_daily",
            "benchmark_index_member",
            "stock_industry_membership",
            "fund_announcements",
        ]
        return entity_type in supported
