"""
核心枚举定义。

涵盖基金类型、数据源等级、结论状态、指标分组等平台基础分类体系。
所有枚举值必须稳定，变更需记录版本。
"""

from enum import StrEnum

# ============================================================
# 基金分类
# ============================================================


class FundCategory(StrEnum):
    """基金一级分类。"""

    STOCK = "股票型"
    MIXED = "混合型"
    BOND = "债券型"
    MONEY_MARKET = "货币型"
    QDII = "QDII"
    FOF = "FOF"
    ALTERNATIVE = "另类型"


class FundSubCategory(StrEnum):
    """基金二级分类（主动权益相关）。"""

    ACTIVE_EQUITY = "主动权益"
    PASSIVE_INDEX = "被动指数"
    INDEX_ENHANCED = "指数增强"
    ETF = "ETF"
    ETF_FEEDER = "ETF联接"
    FLEXIBLE_ALLOCATION = "灵活配置"
    BALANCED_MIXED = "平衡混合"
    PARTIAL_DEBT_MIXED = "偏债混合"
    PURE_BOND = "纯债"
    CONVERTIBLE_BOND = "可转债"
    SHORT_TERM_BOND = "短期纯债"
    SECONDARY_BOND = "二级债基"
    MONEY = "货币"
    QDII_EQUITY = "QDII股票"
    QDII_BOND = "QDII债券"
    FOF_EQUITY = "FOF权益"
    FOF_MIXED = "FOF混合"


class FundOperation(StrEnum):
    """基金运作方式。"""

    OPEN_ENDED = "开放式"
    CLOSED_ENDED = "封闭式"
    LOF = "LOF"
    ETF_TRADED = "ETF上市"
    REGULAR_OPEN = "定期开放"


class FundStatus(StrEnum):
    """基金当前状态。"""

    NORMAL = "正常"
    LIQUIDATED = "已清盘"
    SUSPEND_SUBSCRIBE = "暂停申购"
    SUSPEND_REDEEM = "暂停赎回"
    SUSPEND_ALL = "暂停申赎"
    RESTRICTED = "限购"
    TRANSFORMED = "已转型"


# ============================================================
# 数据源与可靠性
# ============================================================


class DataSourceLevel(StrEnum):
    """
    数据源可靠性等级。

    A: 官方披露数据（证监会/交易所/基金公司公告）
    B: 开源接口聚合数据（AKShare 等）
    C: 网页解析数据（天天基金等公开页面）
    LOCAL: 用户本地数据
    """

    A = "A"
    B = "B"
    C = "C"
    LOCAL = "LOCAL"


class DataSourceType(StrEnum):
    """数据源类型。"""

    OFFICIAL_DISCLOSURE = "official_disclosure"
    OPEN_API = "open_api"
    WEB_SCRAPING = "web_scraping"
    LOCAL_FILE = "local_file"
    COMMERCIAL = "commercial"


# ============================================================
# 结论可信度
# ============================================================


class ConclusionStatus(StrEnum):
    """
    结论状态分级（见需求书 5.5）。

    fact:        公开披露事实，如"基金成立于 2015-03-20"
    computed:    基于确定输入的规则计算，如"近一年年化收益率 12.3%"
    estimated:   模型估计结果，如模拟持仓、动态归因
    observation: 研究观察，如"该基金近期增持了新能源"
    needs_review: 待复核 — 证据不足或模型不适用
    """

    FACT = "fact"
    COMPUTED = "computed"
    ESTIMATED = "estimated"
    OBSERVATION = "observation"
    NEEDS_REVIEW = "needs_review"


class ConfidenceLevel(StrEnum):
    """
    结论置信度等级（见需求书 7.5）。

    高: 数据完整、来源可靠、模型稳定、证据充分
    中: 数据基本完整，存在估计或局部缺失
    低: 数据缺失较多，仅方向性参考
    待复核: 不应自动生成确定性结论
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEEDS_REVIEW = "needs_review"


# ============================================================
# 指标相关
# ============================================================


class MetricEntity(StrEnum):
    """指标所属实体。"""

    FUND = "fund"
    MANAGER = "manager"
    COMPANY = "company"
    PORTFOLIO = "portfolio"


class MetricGroup(StrEnum):
    """指标分组。"""

    RETURN = "收益"
    RISK = "风险"
    STYLE = "风格"
    INDUSTRY = "行业"
    CONCENTRATION = "集中度"
    ALPHA = "Alpha"
    TRADING = "交易"
    BOND_FACTOR = "债基因子"
    ETF = "ETF"
    HOLDER = "持有人"
    SIZE_FEE = "规模费率"


# ============================================================
# 资产与持仓
# ============================================================


class AssetType(StrEnum):
    """资产类型。"""

    STOCK = "股票"
    BOND = "债券"
    CONVERTIBLE_BOND = "可转债"
    CASH = "现金"
    FUND = "基金"
    DERIVATIVE = "衍生品"
    OTHER = "其他"


class HoldingChangeDirection(StrEnum):
    """持仓变动方向。"""

    NEW = "新增"
    INCREASED = "增持"
    DECREASED = "减持"
    EXITED = "退出"
    UNCHANGED = "不变"


# ============================================================
# 研究包与证据
# ============================================================


class EvidenceType(StrEnum):
    """证据类型。"""

    RAW_DATA = "raw_data"
    TIME_SERIES = "time_series"
    ALGORITHM_RESULT = "algorithm_result"
    REPORT_SNIPPET = "report_snippet"
    CHART_DATA = "chart_data"
    USER_NOTE = "user_note"


class ResearchPacketTemplate(StrEnum):
    """研究包视角模板。"""

    SINGLE_FUND_CHECKUP = "single_fund_checkup"
    MANAGER_PROFILE = "manager_profile"
    STYLE_DRIFT = "style_drift"
    HOLDINGS_DEEP_DIVE = "holdings_deep_dive"
    BOND_FUND_RISK = "bond_fund_risk"
    ETF_COMPARISON = "etf_comparison"


# ============================================================
# 基金池
# ============================================================


class PoolType(StrEnum):
    """基金池类型。"""

    WATCHLIST = "watchlist"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"
    PENDING_RESEARCH = "pending_research"
    CANDIDATE = "candidate"


# ============================================================
# 任务
# ============================================================


class TaskStatus(StrEnum):
    """任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    """任务类型。"""

    DATA_UPDATE = "data_update"
    ALGORITHM_RUN = "algorithm_run"
    RESEARCH_PACKET = "research_packet"
    EXPORT = "export"


class ExperimentStatus(StrEnum):
    """算法实验状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"
    CANCELLED = "cancelled"
