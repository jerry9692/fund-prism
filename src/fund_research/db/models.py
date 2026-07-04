"""
SQLAlchemy ORM 模型。

一期核心表（需求书 15.1 节，20 张表）：
基金主数据、净值、持仓、经理、公司、股票、行业、指标注册表、
风格暴露、静态归因、研究包、证据、数据质量等。
"""

from datetime import date, datetime
from secrets import randbits

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fund_research.core.enums import (
    ConclusionStatus,
    ConfidenceLevel,
    DataSourceLevel,
    DataSourceType,
    TaskStatus,
    TaskType,
)
from fund_research.utils import utc_now


def enum_values(enum_cls: type) -> list[str]:
    return [m.value for m in enum_cls]


def generate_int_id() -> int:
    """Generate a positive local integer ID without relying on DB autoincrement."""
    return randbits(63)


def id_column():
    """Surrogate primary key compatible with DuckDB and SQLite."""
    return mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        default=generate_int_id,
    )


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""

    pass


# ============================================================
# 基金主数据
# ============================================================


class FundMain(Base):
    """基金主表。"""

    __tablename__ = "fund_main"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(String(20), comment="基金代码")
    short_name: Mapped[str] = mapped_column(String(100), comment="基金简称")
    full_name: Mapped[str] = mapped_column(String(200), comment="基金全称")
    fund_company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fund_company.id"), comment="基金公司 ID"
    )
    custodian_bank: Mapped[str | None] = mapped_column(String(100), comment="托管行")
    inception_date: Mapped[date | None] = mapped_column(Date, comment="成立日")
    expiry_date: Mapped[date | None] = mapped_column(Date, comment="到期日")
    category: Mapped[str | None] = mapped_column(String(50), comment="一级分类")
    sub_category: Mapped[str | None] = mapped_column(String(50), comment="二级分类")
    investment_type: Mapped[str | None] = mapped_column(String(50), comment="投资类型")
    operation_mode: Mapped[str | None] = mapped_column(String(50), comment="运作方式")
    is_etf: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否 ETF")
    is_etf_feeder: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否 ETF 联接")
    is_index_enhanced: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否指数增强")
    is_qdii: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否 QDII")
    is_fof: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否 FOF")
    status: Mapped[str | None] = mapped_column(String(30), comment="当前状态")
    benchmark: Mapped[str | None] = mapped_column(String(200), comment="业绩比较基准")

    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("fund_code", name="uq_fund_main_fund_code"),
    )

    def __repr__(self) -> str:
        return f"<FundMain({self.fund_code}) {self.short_name}>"


class FundCategory(Base):
    """基金分类表。"""

    __tablename__ = "fund_category"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    category_level: Mapped[str] = mapped_column(String(10), comment="分类级别 primary/secondary")
    category_name: Mapped[str] = mapped_column(String(50), comment="分类名称")
    category_version: Mapped[str | None] = mapped_column(
        String(20), comment="分类版本（口径版本化）"
    )
    effective_date: Mapped[date | None] = mapped_column(Date, comment="生效日期")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<FundCategory({self.fund_code}) {self.category_name}>"


# ============================================================
# 基金经理
# ============================================================


class FundManager(Base):
    """基金经理表。"""

    __tablename__ = "fund_manager"

    id: Mapped[int] = id_column()
    manager_id: Mapped[str] = mapped_column(String(20), comment="基金经理 ID")
    name: Mapped[str] = mapped_column(String(50), comment="姓名")
    gender: Mapped[str | None] = mapped_column(String(10), comment="性别")
    education: Mapped[str | None] = mapped_column(String(100), comment="学历")
    experience_years: Mapped[float | None] = mapped_column(Float, comment="从业年限")
    bio: Mapped[str | None] = mapped_column(Text, comment="简介")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("manager_id", name="uq_fund_manager_manager_id"),
    )

    def __repr__(self) -> str:
        return f"<FundManager({self.manager_id}) {self.name}>"


class FundManagerTenure(Base):
    """基金经理任职记录表。"""

    __tablename__ = "fund_manager_tenure"

    id: Mapped[int] = id_column()
    manager_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_manager.manager_id"), index=True, comment="基金经理 ID"
    )
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    start_date: Mapped[date] = mapped_column(Date, comment="任职起始日")
    end_date: Mapped[date | None] = mapped_column(Date, comment="任职结束日（空=现任）")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否现任")
    tenure_days: Mapped[int | None] = mapped_column(Integer, comment="任职天数")
    tenure_return: Mapped[float | None] = mapped_column(Float, comment="任职期间收益")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("manager_id", "fund_code", "start_date", name="uq_manager_fund_start"),
    )

    def __repr__(self) -> str:
        return f"<FundManagerTenure({self.manager_id} → {self.fund_code})>"


# ============================================================
# 基金公司
# ============================================================


class FundCompany(Base):
    """基金公司表。"""

    __tablename__ = "fund_company"

    id: Mapped[int] = id_column()
    company_id: Mapped[str] = mapped_column(String(20), comment="基金公司 ID")
    name: Mapped[str] = mapped_column(String(100), comment="公司名称")
    short_name: Mapped[str | None] = mapped_column(String(50), comment="公司简称")
    established_date: Mapped[date | None] = mapped_column(Date, comment="成立日期")
    total_aum: Mapped[float | None] = mapped_column(Float, comment="总管理规模（亿元）")
    fund_count: Mapped[int | None] = mapped_column(Integer, comment="管理基金数量")
    manager_count: Mapped[int | None] = mapped_column(Integer, comment="基金经理数量")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_fund_company_company_id"),
    )

    def __repr__(self) -> str:
        return f"<FundCompany({self.company_id}) {self.name}>"


# ============================================================
# 净值与规模
# ============================================================


class FundNAV(Base):
    """基金净值表。"""

    __tablename__ = "fund_nav"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True, comment="交易日")
    unit_nav: Mapped[float | None] = mapped_column(Float, comment="单位净值")
    accumulated_nav: Mapped[float | None] = mapped_column(Float, comment="累计净值")
    adjusted_nav: Mapped[float | None] = mapped_column(Float, comment="复权净值")
    daily_return: Mapped[float | None] = mapped_column(Float, comment="日收益率")
    dividend: Mapped[float | None] = mapped_column(Float, comment="分红金额")
    split_ratio: Mapped[float | None] = mapped_column(Float, comment="拆分比例")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("fund_code", "trade_date", name="uq_fund_trade_date"),
        Index("idx_fund_nav_fund_code_trade_date", "fund_code", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<FundNAV({self.fund_code} @ {self.trade_date})>"


class FundScale(Base):
    """基金规模表。"""

    __tablename__ = "fund_scale"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    report_date: Mapped[date] = mapped_column(Date, index=True, comment="报告期")
    total_nav: Mapped[float | None] = mapped_column(Float, comment="资产净值（亿元）")
    total_share: Mapped[float | None] = mapped_column(Float, comment="总份额（亿份）")
    share_change: Mapped[float | None] = mapped_column(Float, comment="份额变动（亿份）")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("fund_code", "report_date", name="uq_fund_scale_date"),)


class FundFee(Base):
    """基金费率表。"""

    __tablename__ = "fund_fee"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    mgmt_fee_pct: Mapped[float | None] = mapped_column(Float, comment="管理费率")
    custody_fee_pct: Mapped[float | None] = mapped_column(Float, comment="托管费率")
    sales_service_fee_pct: Mapped[float | None] = mapped_column(Float, comment="销售服务费率")
    subscribe_fee_range: Mapped[str | None] = mapped_column(String(100), comment="申购费率区间")
    redeem_fee_range: Mapped[str | None] = mapped_column(String(100), comment="赎回费率区间")
    effective_date: Mapped[date | None] = mapped_column(Date, comment="费率生效日期")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )


# ============================================================
# 持仓
# ============================================================


class FundDisclosedHoldings(Base):
    """基金公开披露持仓表。"""

    __tablename__ = "fund_disclosed_holdings"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    report_date: Mapped[date] = mapped_column(Date, index=True, comment="报告期")
    asset_type: Mapped[str] = mapped_column(String(20), comment="资产类型")
    security_code: Mapped[str] = mapped_column(String(20), index=True, comment="证券代码")
    security_name: Mapped[str | None] = mapped_column(String(100), comment="证券名称")
    weight_pct: Mapped[float | None] = mapped_column(Float, comment="占净值比例(%)")
    market_value: Mapped[float | None] = mapped_column(Float, comment="持仓市值（万元）")
    shares: Mapped[float | None] = mapped_column(Float, comment="持股/持债数量（万股/万张）")
    rank_in_holdings: Mapped[int | None] = mapped_column(Integer, comment="持仓排名")
    industry: Mapped[str | None] = mapped_column(String(50), comment="所属行业")
    market_cap: Mapped[float | None] = mapped_column(Float, comment="个股市值")
    valuation_pe: Mapped[float | None] = mapped_column(Float, comment="市盈率")
    valuation_pb: Mapped[float | None] = mapped_column(Float, comment="市净率")
    bond_rating: Mapped[str | None] = mapped_column(String(20), comment="债券评级")
    bond_duration: Mapped[float | None] = mapped_column(Float, comment="债券久期")
    bond_yield: Mapped[float | None] = mapped_column(Float, comment="债券到期收益率")
    change_direction: Mapped[str | None] = mapped_column(String(20), comment="持仓变动方向")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "report_date",
            "security_code",
            name="uq_fund_report_security",
        ),
        Index("idx_fund_holdings_fund_code_report_date", "fund_code", "report_date"),
    )

    def __repr__(self) -> str:
        return f"<FundDisclosedHoldings({self.fund_code} {self.report_date} {self.security_code})>"


class HolderStructure(Base):
    """持有人结构表。"""

    __tablename__ = "holder_structure"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    report_date: Mapped[date] = mapped_column(Date, index=True, comment="报告期（半年度）")
    individual_pct: Mapped[float | None] = mapped_column(Float, comment="个人投资者持有比例(%)")
    institutional_pct: Mapped[float | None] = mapped_column(Float, comment="机构投资者持有比例(%)")
    employee_pct: Mapped[float | None] = mapped_column(Float, comment="内部员工持有比例(%)")
    total_holders: Mapped[int | None] = mapped_column(Integer, comment="持有人户数")
    avg_holding: Mapped[float | None] = mapped_column(Float, comment="户均持有份额")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("fund_code", "report_date", name="uq_holder_date"),)


# ============================================================
# 股票与行业
# ============================================================


class StockMain(Base):
    """股票主表。"""

    __tablename__ = "stock_main"

    id: Mapped[int] = id_column()
    stock_code: Mapped[str] = mapped_column(String(20), comment="股票代码")
    stock_name: Mapped[str] = mapped_column(String(50), comment="股票名称")
    exchange: Mapped[str | None] = mapped_column(String(10), comment="交易所")
    industry_sw: Mapped[str | None] = mapped_column(String(50), comment="申万行业分类")
    industry_citic: Mapped[str | None] = mapped_column(String(50), comment="中信行业分类")
    market_cap: Mapped[float | None] = mapped_column(Float, comment="总市值")
    float_cap: Mapped[float | None] = mapped_column(Float, comment="流通市值")
    pe_ttm: Mapped[float | None] = mapped_column(Float, comment="市盈率 TTM")
    pb: Mapped[float | None] = mapped_column(Float, comment="市净率")
    listing_date: Mapped[date | None] = mapped_column(Date, comment="上市日期")
    is_delisted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已退市")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("stock_code", name="uq_stock_main_stock_code"),
    )

    def __repr__(self) -> str:
        return f"<StockMain({self.stock_code}) {self.stock_name}>"


class StockDaily(Base):
    """股票日行情表。"""

    __tablename__ = "stock_daily"

    id: Mapped[int] = id_column()
    stock_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("stock_main.stock_code"), index=True, comment="股票代码"
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True, comment="交易日")
    open_price: Mapped[float | None] = mapped_column(Float, comment="开盘价")
    high_price: Mapped[float | None] = mapped_column(Float, comment="最高价")
    low_price: Mapped[float | None] = mapped_column(Float, comment="最低价")
    close_price: Mapped[float | None] = mapped_column(Float, comment="收盘价")
    volume: Mapped[float | None] = mapped_column(Float, comment="成交量（股）")
    amount: Mapped[float | None] = mapped_column(Float, comment="成交额（元）")
    daily_return: Mapped[float | None] = mapped_column(Float, comment="日收益率")
    is_limit_up: Mapped[bool | None] = mapped_column(Boolean, comment="涨停")
    is_limit_down: Mapped[bool | None] = mapped_column(Boolean, comment="跌停")
    is_suspended: Mapped[bool | None] = mapped_column(Boolean, comment="停牌")
    turnover_rate: Mapped[float | None] = mapped_column(Float, comment="换手率")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_stock_trade_date"),)


class IndustryCategory(Base):
    """行业分类表。"""

    __tablename__ = "industry_category"

    id: Mapped[int] = id_column()
    classification_type: Mapped[str] = mapped_column(
        String(30), comment="分类体系（申万/中信/GICS）"
    )
    classification_version: Mapped[str | None] = mapped_column(String(20), comment="分类版本")
    industry_code: Mapped[str] = mapped_column(String(20), comment="行业代码")
    industry_name: Mapped[str] = mapped_column(String(50), comment="行业名称")
    parent_code: Mapped[str | None] = mapped_column(String(20), comment="上级行业代码")
    level: Mapped[int] = mapped_column(Integer, comment="层级（1/2/3级）")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "classification_type",
            "classification_version",
            "industry_code",
            name="uq_industry_type_version_code",
        ),
    )


# ============================================================
# 指标注册表
# ============================================================


class MetricRegistry(Base):
    """指标注册表（需求书 7.4）。"""

    __tablename__ = "metric_registry"

    id: Mapped[int] = id_column()
    field_name: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, comment="字段名（英文 ID）"
    )
    name_zh: Mapped[str] = mapped_column(String(100), comment="中文名")
    name_en: Mapped[str | None] = mapped_column(String(100), comment="英文名")
    entity_type: Mapped[str] = mapped_column(String(30), comment="所属实体类型")
    data_type: Mapped[str] = mapped_column(String(20), comment="数据类型")
    unit: Mapped[str | None] = mapped_column(String(20), comment="单位")
    formula: Mapped[str | None] = mapped_column(Text, comment="计算公式")
    input_fields: Mapped[str | None] = mapped_column(Text, comment="输入数据字段（JSON数组）")
    applicable_fund_types: Mapped[str | None] = mapped_column(
        Text, comment="适用基金类型（JSON数组）"
    )
    update_frequency: Mapped[str] = mapped_column(String(20), comment="更新频率")
    missing_handling: Mapped[str | None] = mapped_column(Text, comment="缺失值处理策略")
    outlier_handling: Mapped[str | None] = mapped_column(Text, comment="极值处理策略")
    limitations: Mapped[str | None] = mapped_column(Text, comment="局限性说明")
    explanation: Mapped[str | None] = mapped_column(Text, comment="人类可读解释")
    ai_schema: Mapped[dict | None] = mapped_column(JSON, comment="AI 可读 schema（JSON）")
    metric_group: Mapped[str | None] = mapped_column(String(20), comment="指标分组")
    version: Mapped[str] = mapped_column(String(10), default="1.0.0", comment="指标版本")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    def __repr__(self) -> str:
        return f"<MetricRegistry({self.field_name}) {self.name_zh}>"


# ============================================================
# 算法结果
# ============================================================


class StyleExposureResult(Base):
    """风格/行业暴露结果表。"""

    __tablename__ = "style_exposure_result"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    calc_date: Mapped[date] = mapped_column(Date, index=True, comment="计算日期")
    algorithm_name: Mapped[str] = mapped_column(String(50), comment="算法名称")
    algorithm_version: Mapped[str] = mapped_column(String(10), comment="算法版本")
    parameters: Mapped[dict | None] = mapped_column(JSON, comment="运行参数")
    exposure_type: Mapped[str] = mapped_column(
        String(30), comment="暴露类型（style/industry/combined）"
    )
    exposure_values: Mapped[dict] = mapped_column(
        JSON, comment="暴露数值（{大盘:0.6, 成长:0.4, ...}）"
    )
    residual: Mapped[float | None] = mapped_column(Float, comment="残差/未解释部分")
    r_squared: Mapped[float | None] = mapped_column(Float, comment="回归 R²")
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values), comment="置信度等级"
    )
    conclusion_status: Mapped[ConclusionStatus] = mapped_column(
        SAEnum(ConclusionStatus, native_enum=False, values_callable=enum_values),
        default=ConclusionStatus.COMPUTED,
        server_default=text("'computed'"),
        comment="结论状态",
    )
    warnings: Mapped[dict | None] = mapped_column(JSON, comment="警告信息")
    input_coverage: Mapped[float | None] = mapped_column(Float, comment="输入数据覆盖率")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    data_source_level: Mapped[DataSourceLevel | None] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "calc_date",
            "algorithm_name",
            "algorithm_version",
            name="uq_exposure_fund_date_algo",
        ),
        Index("idx_style_exposure_fund_code_calc_date", "fund_code", "calc_date"),
    )


class StaticAttributionResult(Base):
    """静态归因/残差结果表。"""

    __tablename__ = "static_attribution_result"

    id: Mapped[int] = id_column()
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    report_date: Mapped[date] = mapped_column(Date, index=True, comment="报告期")
    benchmark: Mapped[str | None] = mapped_column(String(200), comment="基准组合")
    algorithm_name: Mapped[str] = mapped_column(String(50), comment="算法名称")
    algorithm_version: Mapped[str] = mapped_column(String(10), comment="算法版本")
    parameters: Mapped[dict | None] = mapped_column(JSON, comment="运行参数")
    total_return: Mapped[float | None] = mapped_column(Float, comment="基金区间收益")
    benchmark_return: Mapped[float | None] = mapped_column(Float, comment="基准区间收益")
    allocation_effect: Mapped[float | None] = mapped_column(Float, comment="配置效应")
    selection_effect: Mapped[float | None] = mapped_column(Float, comment="选股效应")
    interaction_effect: Mapped[float | None] = mapped_column(Float, comment="交互效应")
    sector_rotation_effect: Mapped[float | None] = mapped_column(Float, comment="板块轮动效应")
    residual: Mapped[float | None] = mapped_column(Float, comment="残差/未解释收益")
    residual_pct: Mapped[float | None] = mapped_column(Float, comment="残差占比(%)")
    detail: Mapped[dict | None] = mapped_column(JSON, comment="分项明细")
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values), comment="置信度"
    )
    conclusion_status: Mapped[ConclusionStatus] = mapped_column(
        SAEnum(ConclusionStatus, native_enum=False, values_callable=enum_values),
        default=ConclusionStatus.COMPUTED,
        server_default=text("'computed'"),
        comment="结论状态",
    )
    warnings: Mapped[dict | None] = mapped_column(JSON, comment="警告信息")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据来源")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint(
            "fund_code",
            "report_date",
            "algorithm_name",
            "algorithm_version",
            name="uq_attribution_fund_date_algo",
        ),
    )


# ============================================================
# 研究包与证据
# ============================================================


class ResearchPacketRecord(Base):
    """研究包存储表。"""

    __tablename__ = "research_packet"

    id: Mapped[int] = id_column()
    packet_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="研究包 ID")
    fund_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("fund_main.fund_code"), index=True, comment="基金代码"
    )
    template: Mapped[str] = mapped_column(String(50), comment="研究包模板")
    generated_at: Mapped[datetime] = mapped_column(DateTime, comment="生成时间")
    data_date: Mapped[date] = mapped_column(Date, comment="数据截止日期")
    packet_json: Mapped[dict] = mapped_column(JSON, comment="完整研究包 JSON")
    markdown_text: Mapped[str | None] = mapped_column(Text, comment="Markdown 摘要")
    platform_version: Mapped[str] = mapped_column(String(10), comment="平台版本")
    overall_confidence: Mapped[ConfidenceLevel | None] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values), comment="整体置信度"
    )
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否最新版本")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<ResearchPacket({self.packet_id}) fund={self.fund_code}>"


class EvidenceRecord(Base):
    """证据存储表。"""

    __tablename__ = "evidence"

    id: Mapped[int] = id_column()
    evidence_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="证据 ID")
    entity_id: Mapped[str] = mapped_column(String(64), index=True, comment="关联实体 ID")
    entity_type: Mapped[str] = mapped_column(String(30), comment="实体类型")
    evidence_type: Mapped[str] = mapped_column(String(30), comment="证据类型")
    source: Mapped[str] = mapped_column(String(100), comment="数据来源")
    source_level: Mapped[DataSourceLevel] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    date_start: Mapped[date | None] = mapped_column(Date, comment="日期区间起点")
    date_end: Mapped[date | None] = mapped_column(Date, comment="日期区间终点")
    algorithm_metadata: Mapped[dict | None] = mapped_column(JSON, comment="算法元数据")
    report_snippet: Mapped[str | None] = mapped_column(Text, comment="报告原文片段")
    report_location: Mapped[str | None] = mapped_column(String(500), comment="报告定位")
    data_summary: Mapped[str | None] = mapped_column(Text, comment="数据摘要")
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        SAEnum(ConfidenceLevel, native_enum=False, values_callable=enum_values),
        default=ConfidenceLevel.NEEDS_REVIEW,
        server_default=text("'needs_review'"),
        comment="置信度",
    )
    conclusion_status: Mapped[ConclusionStatus] = mapped_column(
        SAEnum(ConclusionStatus, native_enum=False, values_callable=enum_values),
        default=ConclusionStatus.NEEDS_REVIEW,
        server_default=text("'needs_review'"),
        comment="结论状态",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<Evidence({self.evidence_id}) entity={self.entity_id}>"


# ============================================================
# 数据质量与操作日志
# ============================================================


class DataSourceSnapshot(Base):
    """数据源与数据快照表。"""

    __tablename__ = "data_source_snapshot"

    id: Mapped[int] = id_column()
    source_name: Mapped[str] = mapped_column(String(50), index=True, comment="数据源名称")
    source_type: Mapped[DataSourceType] = mapped_column(
        SAEnum(DataSourceType, native_enum=False, values_callable=enum_values), comment="数据源类型"
    )
    source_level: Mapped[DataSourceLevel] = mapped_column(
        SAEnum(DataSourceLevel, native_enum=False, values_callable=enum_values), comment="数据源等级"
    )
    fetch_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, comment="数据拉取时间")
    trade_date: Mapped[date | None] = mapped_column(Date, comment="交易日")
    entity_type: Mapped[str] = mapped_column(String(30), comment="实体类型")
    field_count: Mapped[int | None] = mapped_column(Integer, comment="拉取字段数")
    record_count: Mapped[int | None] = mapped_column(Integer, comment="拉取记录数")
    coverage_rate: Mapped[float | None] = mapped_column(Float, comment="字段覆盖率")
    missing_fields: Mapped[dict | None] = mapped_column(JSON, comment="缺失字段明细")
    anomaly_count: Mapped[int | None] = mapped_column(Integer, comment="异常记录数")
    fetch_duration_ms: Mapped[float | None] = mapped_column(Float, comment="拉取耗时(ms)")
    is_success: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否成功")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<DataSourceSnapshot({self.source_name} @ {self.fetch_timestamp})>"


class TaskLog(Base):
    """任务日志表。"""

    __tablename__ = "task_log"

    id: Mapped[int] = id_column()
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="任务 ID")
    task_type: Mapped[TaskType] = mapped_column(
        SAEnum(TaskType, native_enum=False, values_callable=enum_values), index=True, comment="任务类型"
    )
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, values_callable=enum_values),
        default=TaskStatus.PENDING,
        server_default=text("'pending'"),
        index=True,
        comment="任务状态",
    )
    target_entity: Mapped[str | None] = mapped_column(String(64), comment="目标实体")
    parameters: Mapped[dict | None] = mapped_column(JSON, comment="任务参数")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="开始时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="完成时间")
    duration_ms: Mapped[float | None] = mapped_column(Float, comment="耗时(ms)")
    result_summary: Mapped[str | None] = mapped_column(Text, comment="结果摘要")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    def __repr__(self) -> str:
        return f"<TaskLog({self.task_id}) {self.task_type}:{self.status}>"


class ToolAPICallLog(Base):
    """Tool API 调用日志表。"""

    __tablename__ = "tool_api_call_log"

    id: Mapped[int] = id_column()
    call_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="调用 ID")
    tool_name: Mapped[str] = mapped_column(String(50), index=True, comment="API 名称")
    caller: Mapped[str | None] = mapped_column(String(50), comment="调用方（user/agent/notebook）")
    parameters: Mapped[dict | None] = mapped_column(JSON, comment="调用参数")
    status: Mapped[str] = mapped_column(String(20), comment="调用状态")
    response_time_ms: Mapped[float | None] = mapped_column(Float, comment="响应时间(ms)")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    ip_address: Mapped[str | None] = mapped_column(String(50), comment="请求 IP")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    def __repr__(self) -> str:
        return f"<ToolAPICallLog({self.call_id}) {self.tool_name}>"


from fund_research.db.models_phase2 import (  # noqa: E402,F401
    AlgorithmExperiment,
    BenchmarkIndexMember,
    BenchmarkIndustryWeight,
    DynamicAttributionResult,
    ExperimentResult,
    FundPool,
    FundPoolMember,
    ReviewerAnnotation,
    SavedScreen,
    ScoringBacktest,
    ScoringResult,
    SimulatedHoldingResult,
    StockIndustryMembership,
    TradingAbilityResult,
)
from fund_research.db.models_phase3 import (  # noqa: E402,F401
    AnomalyRecord,
    FingerprintSimilarityCache,
    FundComparisonCache,
    FundFingerprint,
    PoolAlertRecord,
    PoolAlertRule,
    ResearchTemplate,
    ReverseLookupResult,
    TemplateRunRecord,
)
