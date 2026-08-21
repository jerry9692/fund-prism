"""指数基金分析与优选（需求书 §6.2.8 / §12.4.1，Phase 4 计划 P4A）。

对样本内指数类基金（ETF / ETF 联接 / 指数增强 / 普通指数）做：

1. **同指数分组**：按跟踪指数（benchmark symbol）分组，未解析跟踪指数的
   产品单列并告警，不强行归组。
2. **跟踪质量**：日偏离序列 = 基金日收益 − 基准日收益（口径与 P4.1-4
   ``compute_etf_tracking_stats`` 一致，复用 ``_load_return_series``），
   输出累计偏离曲线、日均偏离、最大偏离、年化跟踪误差与超额。
3. **指增 alpha**：仅 ``index_enhanced`` 模板输出 Jensen Alpha / IR /
   月度超额胜率；被动产品不输出 alpha 结论（§6.2.8 评价维度 4）。
4. **综合优选评分**：规模/费率/流动性/跟踪质量/折溢价五维组内分位数加权，
   维度缺失时权重再归一化（降权 + 告警，不补 0 分）。

门禁（P4.2-1）：``etf_selection`` 仅适用指数族基金，非指数类调用经
``check_algorithm_applicability`` 拒绝并标 needs_review。
"""

from dataclasses import dataclass, field
from datetime import date as dt_date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.config.settings import get_settings
from fund_research.core.enums import ConclusionStatus
from fund_research.data.update import _load_return_series
from fund_research.db.models import EtfProfile, FundFee, FundMain, FundScale, StockDaily
from fund_research.db.models_phase4 import IndexFundSelectionResult
from fund_research.research.credibility import (
    check_algorithm_applicability,
    normalize_fund_family,
)

ALGORITHM_NAME = "index_fund_selection"
ALGORITHM_VERSION = "0.1.0"

# 跟踪质量计算最低重叠样本数（对比/优选用，严于 P4.1-4 的 20）
MIN_TRACKING_OBSERVATIONS = 60

# 偏离曲线输出点数上限（近一年）
DEVIATION_CURVE_POINTS = 252

# 五维权重（§6.2.8 评价维度；跟踪质量为核心维度）
DIMENSION_WEIGHTS: dict[str, float] = {
    "tracking": 0.30,
    "fee": 0.20,
    "scale": 0.20,
    "liquidity": 0.15,
    "premium": 0.15,
}

DIMENSION_LABELS: dict[str, str] = {
    "scale": "规模",
    "fee": "费率",
    "liquidity": "流动性",
    "tracking": "跟踪质量",
    "premium": "折溢价",
}

# 维度方向：True = 原始值越低越好
DIMENSION_LOWER_IS_BETTER: dict[str, bool] = {
    "scale": False,
    "fee": True,
    "liquidity": False,
    "tracking": True,
    "premium": True,
}

# 基准名称 → stock_daily 指数代码（与 scoring_dimensions 同口径）
BENCHMARK_SYMBOL_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("沪深300", "sh000300"),
    ("中证500", "sh000905"),
    ("中证1000", "sh000852"),
    ("上证50", "sh000016"),
    ("创业板", "sz399006"),
    ("科创50", "sh000688"),
)


@dataclass
class SelectionRecord:
    """单只指数基金的优选结果（含原始指标与评分）。"""

    fund_code: str
    fund_name: str | None = None
    sub_category: str | None = None
    template_name: str | None = None
    group_key: str | None = None
    tracking_index_name: str | None = None
    raw_metrics: dict = field(default_factory=dict)
    dimension_scores: dict = field(default_factory=dict)
    composite_score: float | None = None
    rank_in_group: int | None = None
    group_size: int | None = None
    alpha_annualized: float | None = None
    information_ratio: float | None = None
    monthly_excess_win_rate: float | None = None
    deviation_curve: list[dict] = field(default_factory=list)
    conclusion_status: str = ConclusionStatus.COMPUTED.value
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "sub_category": self.sub_category,
            "template_name": self.template_name,
            "group_key": self.group_key,
            "tracking_index_name": self.tracking_index_name,
            "raw_metrics": self.raw_metrics,
            "dimension_scores": self.dimension_scores,
            "composite_score": self.composite_score,
            "rank_in_group": self.rank_in_group,
            "group_size": self.group_size,
            "alpha_annualized": self.alpha_annualized,
            "information_ratio": self.information_ratio,
            "monthly_excess_win_rate": self.monthly_excess_win_rate,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


@dataclass
class SelectionReport:
    """全量优选报告：按跟踪指数分组的结果集。"""

    records: list[SelectionRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def groups(self) -> dict[str | None, list[SelectionRecord]]:
        grouped: dict[str | None, list[SelectionRecord]] = {}
        for rec in self.records:
            grouped.setdefault(rec.group_key, []).append(rec)
        return grouped


# ============================================================
# 候选与基准解析
# ============================================================


def load_index_fund_candidates(db: Session) -> list[FundMain]:
    """加载指数类候选基金：ETF/联接/指增标识或指数族分类。"""
    funds = db.scalars(select(FundMain).order_by(FundMain.fund_code)).all()
    candidates: list[FundMain] = []
    for fund in funds:
        if (
            fund.is_etf
            or fund.is_etf_feeder
            or fund.is_index_enhanced
            or normalize_fund_family(fund.category) == "index_family"
        ):
            candidates.append(fund)
    return candidates


def resolve_benchmark_symbol(benchmark_name: str | None) -> str | None:
    """基准名称 → stock_daily 指数代码；未收录返回 None（不硬猜）。"""
    if not benchmark_name:
        return None
    name = str(benchmark_name)
    for keyword, symbol in BENCHMARK_SYMBOL_MAPPINGS:
        if keyword in name:
            return symbol
    return None


def resolve_tracking_index(
    db: Session, fund: FundMain
) -> tuple[str | None, str | None]:
    """解析跟踪指数：etf_profile 优先，其次业绩基准名称映射。

    返回 (benchmark_symbol, index_name)，不可解析时为 (None, None)。
    """
    profile = db.scalar(select(EtfProfile).where(EtfProfile.fund_code == fund.fund_code))
    if profile and profile.tracking_index_code:
        return profile.tracking_index_code, profile.tracking_index_name
    symbol = resolve_benchmark_symbol(fund.benchmark)
    if symbol is None:
        return None, None
    name = fund.benchmark.split("×")[0].split("*")[0].strip() if fund.benchmark else None
    return symbol, name


# ============================================================
# 跟踪质量与 alpha
# ============================================================


def _index_name(db: Session, symbol: str) -> str | None:
    """从 stock_daily 取指数名称（首行），无数据返回 None。"""
    row = db.scalars(
        select(StockDaily).where(StockDaily.stock_code == symbol).limit(1)
    ).first()
    return getattr(row, "stock_name", None) if row else None


def compute_tracking_metrics(
    db: Session, fund_code: str, bench_symbol: str
) -> tuple[dict, pd.DataFrame]:
    """本地计算跟踪质量指标与对齐收益序列（口径同 P4.1-4）。

    返回 (metrics, aligned_df)；重叠样本不足时 metrics 为部分缺失。
    """
    aligned, _, _ = _load_return_series(db, fund_code, bench_symbol)
    metrics: dict = {"observations": int(len(aligned))}
    if len(aligned) < MIN_TRACKING_OBSERVATIONS:
        return metrics, aligned

    excess = aligned["fund_return"] - aligned["index_return"]
    # 累计偏离：基金与指数累计净值之比 − 1
    cum_deviation = (1.0 + aligned["fund_return"]).cumprod() / (
        1.0 + aligned["index_return"]
    ).cumprod() - 1.0

    recent = aligned.tail(DEVIATION_CURVE_POINTS)
    recent_excess = recent["fund_return"] - recent["index_return"]

    metrics.update({
        "tracking_error_inception": float(excess.std(ddof=1) * np.sqrt(252)),
        "annualized_excess_inception": float(
            (1.0 + excess.sum()) ** (252.0 / len(excess)) - 1.0
        ),
        "avg_daily_deviation": float(excess.mean()),
        "max_deviation": float(cum_deviation.loc[cum_deviation.abs().idxmax()]),
        "window_start": str(aligned.index.min()),
        "window_end": str(aligned.index.max()),
    })
    if len(recent) >= MIN_TRACKING_OBSERVATIONS:
        metrics["tracking_error_1y"] = float(recent_excess.std(ddof=1) * np.sqrt(252))
        metrics["annualized_excess_1y"] = float(
            (1.0 + recent_excess.sum()) ** (252.0 / len(recent_excess)) - 1.0
        )
    return metrics, aligned


def build_deviation_curve(aligned: pd.DataFrame) -> list[dict]:
    """累计偏离曲线（近一年窗口），供前端对比页绘制。"""
    if len(aligned) < MIN_TRACKING_OBSERVATIONS:
        return []
    excess = aligned["fund_return"] - aligned["index_return"]
    cum_deviation = (1.0 + aligned["fund_return"]).cumprod() / (
        1.0 + aligned["index_return"]
    ).cumprod() - 1.0
    recent_dev = cum_deviation.tail(DEVIATION_CURVE_POINTS)
    recent_excess = excess.tail(DEVIATION_CURVE_POINTS)
    return [
        {
            "date": str(idx.date() if hasattr(idx, "date") else idx),
            "cum_deviation": round(float(recent_dev.loc[idx]), 8),
            "daily_deviation": round(float(recent_excess.loc[idx]), 8),
        }
        for idx in recent_dev.index
    ]


def compute_enhanced_alpha(aligned: pd.DataFrame) -> dict:
    """指增 alpha 分析：Jensen Alpha(年化) / IR / 月度超额胜率。

    口径与 scoring_dimensions.compute_alpha 一致（超额 OLS，Rf 读 settings）。
    """
    result: dict = {}
    if len(aligned) < MIN_TRACKING_OBSERVATIONS:
        return result
    risk_free_daily = get_settings().risk_free_rate / 252
    excess_fund = aligned["fund_return"] - risk_free_daily
    excess_bench = aligned["index_return"] - risk_free_daily
    x = excess_bench.values
    y = excess_fund.values
    beta_den = float(np.sum((x - x.mean()) ** 2))
    if beta_den > 0:
        beta = float(np.sum((x - x.mean()) * (y - y.mean())) / beta_den)
        alpha = float(y.mean() - beta * x.mean())
        result["alpha_annualized"] = alpha * 252
        result["beta"] = beta

    raw_excess = aligned["fund_return"] - aligned["index_return"]
    std = float(raw_excess.std(ddof=1))
    if std > 0:
        result["information_ratio"] = float(raw_excess.mean() / std * np.sqrt(252))
    monthly = raw_excess.groupby(pd.DatetimeIndex(raw_excess.index).to_period("M")).sum()
    if len(monthly) >= 3:
        result["monthly_excess_win_rate"] = float((monthly > 0).mean())
    return result


# ============================================================
# 原始维度值采集
# ============================================================


def _latest_scale(db: Session, fund_code: str) -> float | None:
    row = db.scalars(
        select(FundScale)
        .where(FundScale.fund_code == fund_code)
        .order_by(FundScale.report_date.desc())
        .limit(1)
    ).first()
    if row and row.total_nav:
        return float(row.total_nav)
    # 场内 ETF 规模：快照市值兜底（P4.1-4 边界，fund_scale 对 ETF 常缺失）
    profile = db.scalar(select(EtfProfile).where(EtfProfile.fund_code == fund_code))
    if profile:
        extra = profile.extra or {}
        market_cap = extra.get("market_cap")
        if market_cap:
            return float(market_cap) / 1e8  # 元 → 亿元
    return None


def _total_fee(db: Session, fund_code: str) -> float | None:
    row = db.scalars(
        select(FundFee).where(FundFee.fund_code == fund_code).limit(1)
    ).first()
    if row is None:
        # 场内 ETF 费率：F10 快照兜底（extra.management_fee_pct 单位 %/年）
        profile = db.scalar(select(EtfProfile).where(EtfProfile.fund_code == fund_code))
        extra = (profile.extra or {}) if profile else {}
        mgmt = extra.get("management_fee_pct")
        custody = extra.get("custody_fee_pct")
        if mgmt is None and custody is None:
            return None
        return float(mgmt or 0.0) + float(custody or 0.0)
    mgmt = row.mgmt_fee_pct or 0.0
    custody = row.custody_fee_pct or 0.0
    if mgmt == 0.0 and custody == 0.0:
        return None
    return float(mgmt + custody)


def collect_raw_dimensions(
    db: Session, fund: FundMain, tracking_metrics: dict
) -> tuple[dict[str, float | None], list[str]]:
    """采集五维原始值；缺失维度返回 None 并附告警（不补 0）。"""
    warnings: list[str] = []
    profile = db.scalar(select(EtfProfile).where(EtfProfile.fund_code == fund.fund_code))

    raw: dict[str, float | None] = {}
    raw["scale"] = _latest_scale(db, fund.fund_code)
    raw["fee"] = _total_fee(db, fund.fund_code)
    raw["tracking"] = tracking_metrics.get("tracking_error_1y") or tracking_metrics.get(
        "tracking_error_inception"
    )
    if profile:
        raw["liquidity"] = profile.avg_daily_amount_1y
        raw["premium"] = (
            abs(profile.latest_premium_rate) if profile.latest_premium_rate is not None else None
        )
    else:
        raw["liquidity"] = None
        raw["premium"] = None

    if raw["liquidity"] is None:
        warnings.append("流动性维度缺失（场外产品无场内成交额），权重已再分配")
    if raw["premium"] is None:
        warnings.append("折溢价维度缺失（场外产品无 IOPV 溢折率），权重已再分配")
    if raw["scale"] is None:
        warnings.append("规模数据缺失")
    if raw["fee"] is None:
        warnings.append("费率数据缺失")
    if raw["tracking"] is None:
        warnings.append(
            f"跟踪误差不可计算（重叠样本 < {MIN_TRACKING_OBSERVATIONS} 或基准缺失）"
        )
    return raw, warnings


# ============================================================
# 评分与排名
# ============================================================


def score_dimensions(
    raw_by_fund: dict[str, dict[str, float | None]],
) -> dict[str, dict[str, dict]]:
    """对全部候选做分位数评分（0-100），返回 {fund_code: {dim: {raw, score, missing}}}。

    - 分位数在**全体候选池**内计算（同指数组内对比另行排名）
    - 维度内仅 1 个有效值时评分取中性 50
    - 缺失值不参与评分（missing=True），综合分按可用权重再归一
    """
    scores: dict[str, dict[str, dict]] = {
        code: {} for code in raw_by_fund
    }
    for dim in DIMENSION_WEIGHTS:
        values = {
            code: raw.get(dim)
            for code, raw in raw_by_fund.items()
            if raw.get(dim) is not None
        }
        series = pd.Series(values, dtype="float64").dropna()
        for code, raw in raw_by_fund.items():
            value = raw.get(dim)
            if value is None or series.empty:
                scores[code][dim] = {"raw": value, "score": None, "missing": True}
                continue
            if len(series) == 1:
                percentile = 0.5
            else:
                if DIMENSION_LOWER_IS_BETTER[dim]:
                    # 越低越好：降序排名分位（最低值 → 接近 1）
                    percentile = float(series.rank(ascending=False, pct=True).loc[code])
                else:
                    # 越高越好：升序排名分位（最高值 → 接近 1）
                    percentile = float(series.rank(ascending=True, pct=True).loc[code])
            scores[code][dim] = {
                "raw": float(value),
                "score": round(percentile * 100, 2),
                "missing": False,
            }
    return scores


def composite_from_scores(dimension_scores: dict[str, dict]) -> float | None:
    """按可用维度权重再归一计算综合分；无可用维度返回 None。"""
    total_weight = 0.0
    weighted = 0.0
    for dim, weight in DIMENSION_WEIGHTS.items():
        entry = dimension_scores.get(dim) or {}
        if entry.get("missing") or entry.get("score") is None:
            continue
        weighted += weight * float(entry["score"])
        total_weight += weight
    if total_weight <= 0:
        return None
    return round(weighted / total_weight, 2)


# ============================================================
# 主流程
# ============================================================


def run_selection(
    db: Session,
    *,
    index_symbol: str | None = None,
) -> SelectionReport:
    """执行指数基金优选全流程（不落库）。

    Parameters
    ----------
    index_symbol
        可选，仅返回跟踪该指数的产品（如 ``sh000300``）。评分与排名始终
        在全体候选池内计算，保证局部运行与全量运行口径一致，过滤仅在输出层。
    """
    report = SelectionReport()
    candidates = load_index_fund_candidates(db)
    if not candidates:
        report.warnings.append("样本内无指数类候选基金")
        return report

    # 1. 逐基金采集原始指标（全池，保证分位数评分基准不受局部过滤影响）
    raw_by_fund: dict[str, dict[str, float | None]] = {}
    tracking_by_fund: dict[str, dict] = {}
    aligned_by_fund: dict[str, pd.DataFrame] = {}

    for fund in candidates:
        record = SelectionRecord(
            fund_code=fund.fund_code,
            fund_name=getattr(fund, "short_name", None),
            sub_category=fund.sub_category,
        )

        # 门禁3：算法适用性（etf_selection 仅指数族）；
        # 场内 ETF 东财一级分类常为“股票型”，标识优先于粗分类归指数族
        has_index_flag = bool(fund.is_etf or fund.is_etf_feeder or fund.is_index_enhanced)
        effective_category = "指数型" if has_index_flag else fund.category
        gate = check_algorithm_applicability("etf_selection", effective_category)
        if not gate.passed:
            record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
            record.warnings.append(gate.message)
            report.records.append(record)
            continue

        symbol, index_name = resolve_tracking_index(db, fund)
        if symbol is None:
            record.warnings.append("跟踪指数不可解析（etf_profile 与业绩基准均缺失/未收录）")
            record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
            report.records.append(record)
            continue

        record.group_key = symbol
        record.tracking_index_name = index_name or _index_name(db, symbol)
        record.template_name = (
            "index_enhanced"
            if (
                fund.is_index_enhanced
                or fund.sub_category == "指数增强"
                or "增强" in (fund.category or "")
            )
            else "index_passive"
        )

        tracking_metrics, aligned = compute_tracking_metrics(db, fund.fund_code, symbol)
        tracking_by_fund[fund.fund_code] = tracking_metrics
        aligned_by_fund[fund.fund_code] = aligned
        record.raw_metrics = dict(tracking_metrics)

        raw, raw_warnings = collect_raw_dimensions(db, fund, tracking_metrics)
        raw_by_fund[fund.fund_code] = raw
        record.warnings.extend(raw_warnings)

        if record.template_name == "index_enhanced":
            alpha_stats = compute_enhanced_alpha(aligned)
            record.alpha_annualized = alpha_stats.get("alpha_annualized")
            record.information_ratio = alpha_stats.get("information_ratio")
            record.monthly_excess_win_rate = alpha_stats.get("monthly_excess_win_rate")
            record.raw_metrics.update(
                {k: v for k, v in alpha_stats.items() if k != "alpha_annualized"}
            )
        report.records.append(record)

    if not raw_by_fund:
        # 无可评分候选（全部被门禁拒绝/未解析或样本为空）；
        # index_symbol 限定场景的空结果告警由输出层过滤统一处理
        return report

    # 2. 全池分位数评分 + 综合分
    all_scores = score_dimensions(raw_by_fund)
    for record in report.records:
        if record.fund_code not in all_scores:
            continue
        record.dimension_scores = all_scores[record.fund_code]
        record.composite_score = composite_from_scores(record.dimension_scores)
        record.deviation_curve = build_deviation_curve(aligned_by_fund[record.fund_code])
        if record.dimension_scores.get("tracking", {}).get("missing"):
            # 跟踪质量为核心维度，缺失时结论降级为观察（§6.2.8 核心评价项）
            record.conclusion_status = ConclusionStatus.OBSERVATION.value

    # 3. 同指数组内排名（综合分降序，并列取最小名次）；门禁拒绝/未解析记录不入组
    grouped = {
        key: members
        for key, members in report.groups().items()
        if key is not None
    }
    for _, members in grouped.items():
        size = len(members)
        scored = {m.fund_code: m.composite_score for m in members if m.composite_score is not None}
        if scored:
            rank_series = pd.Series(scored, dtype="float64").rank(ascending=False, method="min")
        else:
            rank_series = pd.Series(dtype="float64")
        for member in members:
            member.group_size = size
            if member.fund_code in rank_series.index:
                member.rank_in_group = int(rank_series.loc[member.fund_code])
            if size < 2:
                member.warnings.append("同指数组内仅 1 只产品，对比意义有限")

    # 4. index_symbol 输出层过滤（评分/排名已按全池口径完成）；
    # 门禁拒绝与未解析记录 group_key 为 None，限定模式下不进入局部报告
    if index_symbol:
        report.records = [r for r in report.records if r.group_key == index_symbol]
        if not report.records:
            report.warnings.append(f"无跟踪指数 {index_symbol} 的候选基金")
    return report


# ============================================================
# 持久化
# ============================================================


def persist_selection_results(
    db: Session, report: SelectionReport, calc_date: dt_date | None = None
) -> list[IndexFundSelectionResult]:
    """幂等落库：同 (fund_code, calc_date, 算法版本) 覆盖更新。"""
    calc_date = calc_date or dt_date.today()
    rows: list[IndexFundSelectionResult] = []
    for record in report.records:
        existing = db.scalar(
            select(IndexFundSelectionResult).where(
                IndexFundSelectionResult.fund_code == record.fund_code,
                IndexFundSelectionResult.calc_date == calc_date,
                IndexFundSelectionResult.algorithm_name == ALGORITHM_NAME,
                IndexFundSelectionResult.algorithm_version == ALGORITHM_VERSION,
            )
        )
        if existing is None:
            existing = IndexFundSelectionResult(
                fund_code=record.fund_code,
                calc_date=calc_date,
                algorithm_name=ALGORITHM_NAME,
                algorithm_version=ALGORITHM_VERSION,
            )
            db.add(existing)
        existing.group_key = record.group_key
        existing.tracking_index_code = record.group_key
        existing.tracking_index_name = record.tracking_index_name
        existing.template_name = record.template_name
        existing.dimension_scores = record.dimension_scores
        existing.composite_score = record.composite_score
        existing.rank_in_group = record.rank_in_group
        existing.group_size = record.group_size
        existing.alpha_annualized = record.alpha_annualized
        existing.information_ratio = record.information_ratio
        existing.conclusion_status = record.conclusion_status
        existing.warnings = record.warnings or None
        rows.append(existing)
    db.flush()
    return rows


def get_latest_selection_results(db: Session) -> list[IndexFundSelectionResult]:
    """取最近一个计算日的全部优选结果。"""
    latest_date = db.scalar(
        select(IndexFundSelectionResult.calc_date)
        .where(IndexFundSelectionResult.algorithm_version == ALGORITHM_VERSION)
        .order_by(IndexFundSelectionResult.calc_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return []
    return list(
        db.scalars(
            select(IndexFundSelectionResult)
            .where(
                IndexFundSelectionResult.calc_date == latest_date,
                IndexFundSelectionResult.algorithm_version == ALGORITHM_VERSION,
            )
            .order_by(IndexFundSelectionResult.composite_score.desc().nulls_last())
        ).all()
    )


def selection_row_to_dict(row: IndexFundSelectionResult) -> dict:
    return {
        # 代理 ID 为 19 位大整数超 JS Number 安全范围，统一 str 序列化
        "id": str(row.id),
        "fund_code": row.fund_code,
        "calc_date": str(row.calc_date),
        "algorithm_version": row.algorithm_version,
        "group_key": row.group_key,
        "tracking_index_code": row.tracking_index_code,
        "tracking_index_name": row.tracking_index_name,
        "template_name": row.template_name,
        "dimension_scores": row.dimension_scores,
        "composite_score": row.composite_score,
        "rank_in_group": row.rank_in_group,
        "group_size": row.group_size,
        "alpha_annualized": row.alpha_annualized,
        "information_ratio": row.information_ratio,
        "conclusion_status": row.conclusion_status,
        "warnings": row.warnings or [],
    }
