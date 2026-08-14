"""
Phase 4 ORM models.

P4.1-2 指数数据域（需求书 §15.2 扩展表）：
- index_main          指数主表（宽基/行业/主题/风格，申万/中信/中证体系）
- index_daily         指数日行情表
- index_constituent   指数成分权重快照表

P4.1-3 债券数据域（需求书 §5.1 / §15.2）：
- bond_main           债券主表（可转债/国债/金融债/信用债）
- bond_daily          债券日行情/估值表
- yield_curve_daily   收益率曲线日序（国债/中短票 AAA/AA，供久期/利率/
                      斜率/信用因子构造，§6.2.7 债基因子回归输入）

注意：行业分类口径版本化（需求书 §5.3.3），classification_system +
classification_version 必填体系与版本，避免"代理基准"口径漂移。
债券评级口径（§5.3.3）：bond_main.rating 记录抓取时点评级，
rating_date/rating_source 落 extra，避免"发行时 vs 最新"口径混淆。
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fund_research.db.models import Base, id_column

# 指数分类体系（申万/中信/中证/交易所）
INDEX_CLASSIFICATION_SYSTEMS = ("SW", "CITIC", "CSI", "EXCHANGE")

# 指数类型
INDEX_TYPES = ("broad", "industry", "theme", "style", "strategy")


class IndexMain(Base):
    """指数主表 — 宽基/行业/主题/风格指数统一登记。"""

    __tablename__ = "index_main"

    id: Mapped[int] = id_column()
    index_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, comment="指数代码，如 801010.SI / 000300"
    )
    index_name: Mapped[str] = mapped_column(String(100), comment="指数名称")
    index_type: Mapped[str] = mapped_column(String(20), comment="指数类型 broad/industry/theme/style/strategy")
    classification_system: Mapped[str] = mapped_column(String(20), comment="分类体系 SW/CITIC/CSI/EXCHANGE")
    classification_version: Mapped[str | None] = mapped_column(String(20), comment="分类版本，如 SW2021")
    level: Mapped[int | None] = mapped_column(Integer, comment="行业层级 1/2/3（行业指数适用）")
    member_count: Mapped[int | None] = mapped_column(Integer, comment="成分个数快照")
    source_name: Mapped[str] = mapped_column(String(80), comment="数据源名称")
    source_level: Mapped[str] = mapped_column(String(10), comment="数据源等级 A/B/C/LOCAL")
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, comment="估值等附加快照（PE/PB/股息率）")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class IndexDaily(Base):
    """指数日行情表 — Phase 4 指数数据域通用行情。"""

    __tablename__ = "index_daily"

    id: Mapped[int] = id_column()
    index_code: Mapped[str] = mapped_column(String(20), index=True, comment="指数代码，关联 index_main.index_code")
    trade_date: Mapped[date] = mapped_column(Date, index=True, comment="交易日")
    open_price: Mapped[float | None] = mapped_column(Float, comment="开盘价")
    high_price: Mapped[float | None] = mapped_column(Float, comment="最高价")
    low_price: Mapped[float | None] = mapped_column(Float, comment="最低价")
    close_price: Mapped[float | None] = mapped_column(Float, comment="收盘价")
    volume: Mapped[float | None] = mapped_column(Float, comment="成交量")
    amount: Mapped[float | None] = mapped_column(Float, comment="成交额")
    daily_return: Mapped[float | None] = mapped_column(Float, comment="日收益率")
    source_name: Mapped[str] = mapped_column(String(80), comment="数据源名称")
    source_level: Mapped[str] = mapped_column(String(10), comment="数据源等级 A/B/C/LOCAL")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("index_code", "trade_date", name="uq_index_code_trade_date"),
        Index("ix_index_daily_code_date", "index_code", "trade_date"),
    )


class IndexConstituent(Base):
    """指数成分权重快照表 — 行业/主题指数成分及权重。"""

    __tablename__ = "index_constituent"

    id: Mapped[int] = id_column()
    index_code: Mapped[str] = mapped_column(String(20), index=True, comment="指数代码，关联 index_main.index_code")
    effective_date: Mapped[date] = mapped_column(Date, index=True, comment="生效日（成分计入/快照日期）")
    stock_code: Mapped[str] = mapped_column(String(20), index=True, comment="成分股代码")
    stock_name: Mapped[str | None] = mapped_column(String(100), comment="成分股名称")
    weight_pct: Mapped[float | None] = mapped_column(Float, comment="权重(%)")
    source_name: Mapped[str] = mapped_column(String(80), comment="数据源名称")
    source_level: Mapped[str] = mapped_column(String(10), comment="数据源等级 A/B/C/LOCAL")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "index_code",
            "effective_date",
            "stock_code",
            name="uq_index_constituent_code_date_stock",
        ),
        Index("ix_index_constituent_code_date", "index_code", "effective_date"),
    )


# 申万指数代码归一化后的导出别名（保持与 phase2/3 的重导出惯例一致）
IndexMainV4 = IndexMain
IndexDailyV4 = IndexDaily
IndexConstituentV4 = IndexConstituent


# ============================================================
# P4.1-3 债券数据域（需求书 §5.1 / §15.2）
# ============================================================

# 债券类型（需求书 §5.1：国债/金融债/信用债/可转债）
BOND_TYPES = ("treasury", "policy_bank", "credit", "convertible", "other")

# 收益率曲线名称（yield_curve_daily.curve_name 枚举）
# treasury=中债国债, medium_term_note_aaa/aa=中债中短期票据,
# commercial_bank_bond_aaa=中债商业银行普通债
YIELD_CURVE_NAMES = (
    "treasury",
    "medium_term_note_aaa",
    "medium_term_note_aa",
    "commercial_bank_bond_aaa",
)


class BondMain(Base):
    """债券主表 — 可转债/国债/金融债/信用债统一登记（需求书 §15.2）。"""

    __tablename__ = "bond_main"

    id: Mapped[int] = id_column()
    bond_code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, comment="债券代码，如 128039.SZ"
    )
    bond_name: Mapped[str] = mapped_column(String(100), comment="债券简称")
    bond_type: Mapped[str] = mapped_column(
        String(20), comment="债券类型 convertible/treasury/policy_bank/credit/other"
    )
    rating: Mapped[str | None] = mapped_column(String(20), comment="信用评级（抓取时点）")
    coupon_rate: Mapped[float | None] = mapped_column(Float, comment="票面利率(%)")
    maturity_date: Mapped[date | None] = mapped_column(Date, comment="到期日")
    underlying_stock_code: Mapped[str | None] = mapped_column(
        String(20), comment="正股代码（可转债）"
    )
    underlying_stock_name: Mapped[str | None] = mapped_column(String(100), comment="正股简称（可转债）")
    conversion_price: Mapped[float | None] = mapped_column(Float, comment="转股价（可转债）")
    listing_date: Mapped[date | None] = mapped_column(Date, comment="上市日期")
    issue_size: Mapped[float | None] = mapped_column(Float, comment="发行规模（亿元）")
    source_name: Mapped[str] = mapped_column(String(80), comment="数据源名称")
    source_level: Mapped[str] = mapped_column(String(10), comment="数据源等级 A/B/C/LOCAL")
    extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="附加快照（转股价值/转股溢价率/评级口径等）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class BondDaily(Base):
    """债券日行情/估值表 — 可转债日行情、债券估值序列（需求书 §15.2）。"""

    __tablename__ = "bond_daily"

    id: Mapped[int] = id_column()
    bond_code: Mapped[str] = mapped_column(
        String(20), index=True, comment="债券代码，关联 bond_main.bond_code"
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True, comment="交易日")
    open_price: Mapped[float | None] = mapped_column(Float, comment="开盘价")
    high_price: Mapped[float | None] = mapped_column(Float, comment="最高价")
    low_price: Mapped[float | None] = mapped_column(Float, comment="最低价")
    close_price: Mapped[float | None] = mapped_column(Float, comment="收盘价/估值")
    volume: Mapped[float | None] = mapped_column(Float, comment="成交量")
    amount: Mapped[float | None] = mapped_column(Float, comment="成交额")
    daily_return: Mapped[float | None] = mapped_column(Float, comment="日收益率")
    source_name: Mapped[str] = mapped_column(String(80), comment="数据源名称")
    source_level: Mapped[str] = mapped_column(String(10), comment="数据源等级 A/B/C/LOCAL")
    extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="附加字段（转股价值/转股溢价率等）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("bond_code", "trade_date", name="uq_bond_code_trade_date"),
        Index("ix_bond_daily_code_date", "bond_code", "trade_date"),
    )


class YieldCurveDaily(Base):
    """收益率曲线日序 — 久期/利率/斜率/信用因子构造输入（§6.2.7）。"""

    __tablename__ = "yield_curve_daily"

    id: Mapped[int] = id_column()
    curve_name: Mapped[str] = mapped_column(
        String(40), index=True, comment="曲线名称 treasury/medium_term_note_aaa 等"
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True, comment="交易日")
    tenor_years: Mapped[float] = mapped_column(Float, comment="期限（年），如 0.25/1/3/5/10")
    yield_pct: Mapped[float | None] = mapped_column(Float, comment="到期收益率(%)")
    source_name: Mapped[str] = mapped_column(String(80), comment="数据源名称")
    source_level: Mapped[str] = mapped_column(String(10), comment="数据源等级 A/B/C/LOCAL")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "curve_name",
            "trade_date",
            "tenor_years",
            name="uq_yield_curve_name_date_tenor",
        ),
        Index("ix_yield_curve_date_tenor", "trade_date", "tenor_years"),
    )


# 债券数据域导出别名（保持与指数域的重导出惯例一致）
BondMainV4 = BondMain
BondDailyV4 = BondDaily
YieldCurveDailyV4 = YieldCurveDaily
