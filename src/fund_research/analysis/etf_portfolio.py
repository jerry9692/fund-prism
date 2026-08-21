"""ETF 组合构建（需求书 §6.2.9 / §12.4.1，Phase 4 计划 P4D）。

对目标指数（默认沪深300）用 CVXPY 二次规划构建 ETF 组合：

1. **输入**：目标指数 benchmark symbol、可选 ETF 池（默认样本内 ETF/联接）、
   单只权重上下限、规模/流动性/费率/跟踪误差阈值、数量上限。
2. **优化**：最小化组合与目标指数收益序列的跟踪误差；协方差矩阵用
   Ledoit-Wolf 收缩稳健化（§6.2.9 第 3 条，避免过拟合）；约束逐条可回显
   （§7.3 第 5 条"约束是否生效、为何选某只 ETF"）。
3. **再平衡模拟**：月度/季度 walk-forward 回测，输出逐期换手率与成本
   （组合费率 × 单边换手），换手上限以凸约束生效。
4. **输出**：推荐权重、历史拟合/样本外跟踪误差、最大偏离、组合费率/
   规模/流动性、与目标指数的行业偏离（benchmark_industry_weight SW 口径）。

降级路径（诚实降级，不硬造）：
- 候选池 <2 只或对齐序列 <60 交易日 → needs_review，不输出推荐权重；
- CVXPY 不可用/求解失败 → needs_review + 告警；
- 拟合跟踪误差 ≥ 单只最差候选 → observation（组合未跑赢最差单票）；
- 行业权重对照缺失 → 偏离置空 + 告警。
"""

from dataclasses import dataclass, field
from datetime import date as dt_date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.index_fund_selection import (
    _latest_scale,
    _total_fee,
    resolve_tracking_index,
)
from fund_research.core.enums import ConclusionStatus
from fund_research.data.update import _daily_return_series
from fund_research.db.models import FundMain, FundNAV, StockDaily
from fund_research.db.models_phase2 import BenchmarkIndustryWeight
from fund_research.db.models_phase4 import EtfPortfolioResult, EtfProfile
from fund_research.research.credibility import check_algorithm_applicability

try:
    import cvxpy as cp

    _HAS_CVXPY = True
except ImportError:
    _HAS_CVXPY = False

try:
    from sklearn.covariance import LedoitWolf

    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

ALGORITHM_NAME = "etf_portfolio_build"
ALGORITHM_VERSION = "0.1.0"

# 验收降级阈值（§6.2.9 / phase4_plan P4D 验收标准）
MIN_POOL_SIZE = 2
MIN_OBSERVATIONS = 60
DEFAULT_LOOKBACK_DAYS = 252
DEFAULT_MAX_SINGLE_WEIGHT = 1.0

# 拟合曲线输出点数上限
FIT_CURVE_POINTS = 252

# 权重清理阈值（低于此值视为 0，避免数值噪声）
WEIGHT_EPSILON = 1e-4

REBALANCE_FREQUENCIES = ("monthly", "quarterly")


@dataclass
class EtfPortfolioRecord:
    """一次 ETF 组合构建的完整结果。"""

    target_symbol: str
    target_name: str | None = None
    candidate_count: int = 0
    eligible_count: int = 0
    member_weights: dict = field(default_factory=dict)
    portfolio_stats: dict = field(default_factory=dict)
    backtest: dict = field(default_factory=dict)
    constraints: list = field(default_factory=list)
    industry_deviation: dict = field(default_factory=dict)
    window_start: dt_date | None = None
    window_end: dt_date | None = None
    conclusion_status: str = ConclusionStatus.COMPUTED.value
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict:
        return {
            "target_symbol": self.target_symbol,
            "target_name": self.target_name,
            "candidate_count": self.candidate_count,
            "eligible_count": self.eligible_count,
            "member_weights": self.member_weights,
            "portfolio_stats": self.portfolio_stats,
            "backtest": self.backtest,
            "constraints": self.constraints,
            "industry_deviation": self.industry_deviation,
            "window_start": str(self.window_start) if self.window_start else None,
            "window_end": str(self.window_end) if self.window_end else None,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


# ============================================================
# 数据加载
# ============================================================


def load_index_return_series(db: Session, index_symbol: str) -> pd.Series:
    """目标指数日收益序列（stock_daily，daily_return 缺失时收盘价推导）。"""
    rows = db.scalars(
        select(StockDaily)
        .where(StockDaily.stock_code == index_symbol)
        .order_by(StockDaily.trade_date)
    ).all()
    series = _daily_return_series(rows, lambda row: row.close_price)
    series.name = index_symbol
    return series


def load_fund_return_series(db: Session, fund_code: str) -> pd.Series:
    """基金净值日收益序列（复权净值优先，口径与 P4.1-4 一致）。"""
    rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date)
    ).all()
    series = _daily_return_series(rows, lambda row: row.adjusted_nav or row.unit_nav)
    series.name = fund_code
    return series


def load_etf_candidates(db: Session) -> list[FundMain]:
    """默认候选：样本内 ETF 与 ETF 联接（指增偏主动，不参与跟踪构建）。"""
    funds = db.scalars(select(FundMain).order_by(FundMain.fund_code)).all()
    return [f for f in funds if f.is_etf or f.is_etf_feeder]


def align_return_matrix(
    index_series: pd.Series, fund_series: dict[str, pd.Series]
) -> pd.DataFrame:
    """对齐指数与候选基金日收益为矩阵（共同日期，整行剔除缺失）。"""
    if not fund_series:
        return pd.DataFrame()
    frame = pd.DataFrame(fund_series)
    frame["__index__"] = index_series
    return frame.dropna()


# ============================================================
# 候选过滤
# ============================================================


def filter_eligible_candidates(
    db: Session,
    candidates: list[FundMain],
    target_symbol: str,
    *,
    min_scale: float | None = None,
    min_amount: float | None = None,
    max_fee: float | None = None,
    max_tracking_error: float | None = None,
) -> tuple[list[FundMain], list[dict], list[str]]:
    """按跟踪指数匹配与阈值过滤候选，返回 (入选者, 过滤明细, 告警)。

    过滤明细供约束清单逐条回显（§7.3 第 5 条）：每只被剔除候选附原因；
    阈值字段缺失时不硬判（数据源诚实），仅在有值时比较。
    """
    eligible: list[FundMain] = []
    details: list[dict] = []
    warnings: list[str] = []
    for fund in candidates:
        # 门禁3：算法适用性（etf_portfolio_build 仅指数族）；
        # 场内 ETF 东财一级分类常为“股票型”，标识优先于粗分类归指数族
        has_index_flag = bool(fund.is_etf or fund.is_etf_feeder)
        effective_category = "指数型" if has_index_flag else fund.category
        gate = check_algorithm_applicability("etf_portfolio_build", effective_category)
        if not gate.passed:
            details.append({"fund_code": fund.fund_code, "passed": False, "reason": gate.message})
            continue

        symbol, _ = resolve_tracking_index(db, fund)
        if symbol != target_symbol:
            details.append({
                "fund_code": fund.fund_code,
                "passed": False,
                "reason": f"跟踪指数 {symbol or '不可解析'} ≠ 目标 {target_symbol}",
            })
            continue

        profile = db.scalar(select(EtfProfile).where(EtfProfile.fund_code == fund.fund_code))
        reasons: list[str] = []
        if min_scale is not None:
            scale = _latest_scale(db, fund.fund_code)
            if scale is not None and scale < min_scale:
                reasons.append(f"规模 {scale:.1f} 亿 < 阈值 {min_scale} 亿")
        if min_amount is not None:
            amount = profile.avg_daily_amount_1y if profile else None
            if amount is not None and amount < min_amount:
                reasons.append(f"日均成交额 {amount / 1e8:.2f} 亿 < 阈值 {min_amount / 1e8} 亿")
        if max_fee is not None:
            fee = _total_fee(db, fund.fund_code)
            if fee is not None and fee > max_fee:
                reasons.append(f"费率 {fee:.2f}% > 阈值 {max_fee}%")
        if max_tracking_error is not None and profile is not None:
            te = profile.tracking_error_1y or profile.tracking_error_inception
            if te is not None and te > max_tracking_error:
                reasons.append(f"跟踪误差 {te:.4f} > 阈值 {max_tracking_error}")

        if reasons:
            details.append({"fund_code": fund.fund_code, "passed": False, "reason": "；".join(reasons)})
        else:
            eligible.append(fund)
            details.append({"fund_code": fund.fund_code, "passed": True, "reason": None})

    if not eligible:
        warnings.append(f"无满足条件且跟踪 {target_symbol} 的候选 ETF")
    return eligible, details, warnings


# ============================================================
# CVXPY 二次规划
# ============================================================


def optimize_tracking_weights(
    returns: pd.DataFrame,
    *,
    min_weight: float = 0.0,
    max_weight: float = DEFAULT_MAX_SINGLE_WEIGHT,
    max_positions: int | None = None,
    prev_weights: dict[str, float] | None = None,
    max_turnover: float | None = None,
    shrink_covariance: bool = True,
) -> tuple[dict[str, float] | None, dict]:
    """最小化组合与目标指数的跟踪误差方差，返回 (权重, 求解信息)。

    - returns 列 = 候选 ETF 日收益，``__index__`` 列 = 目标指数日收益；
    - 协方差用 Ledoit-Wolf 收缩（§6.2.9 第 3 条）；不可用时回退样本协方差并告警；
    - max_positions 为基数约束（非凸）：先全池求解，保留权重最大的 k 只后
      在子集上重新求解，保证约束严格成立；
    - max_turnover 以凸约束 sum|w − w_prev| ≤ cap 生效（再平衡用）。
    求解失败返回 (None, info)。
    """
    info: dict = {"shrinkage": False, "solver_status": None, "subset_resolved": False}
    if not _HAS_CVXPY:
        info["solver_status"] = "cvxpy_unavailable"
        return None, info

    codes = [c for c in returns.columns if c != "__index__"]
    joint = returns.to_numpy(dtype="float64")
    n = len(codes)

    if shrink_covariance and _HAS_SKLEARN and len(joint) > n + 1:
        lw = LedoitWolf().fit(joint)
        cov_full = lw.covariance_
        info["shrinkage"] = True
        info["shrinkage_intensity"] = float(lw.shrinkage_)
    else:
        cov_full = np.cov(joint, rowvar=False, ddof=1)
        cov_full = np.atleast_2d(cov_full)

    sigma = cov_full[:n, :n]
    cov_bench = cov_full[:n, n]

    def _solve(subset: list[int], prev: np.ndarray | None) -> tuple[np.ndarray | None, str]:
        w = cp.Variable(len(subset))
        sigma_sub = sigma[np.ix_(subset, subset)]
        cov_sub = cov_bench[subset]
        objective = cp.quad_form(w, cp.psd_wrap(sigma_sub)) - 2.0 * w @ cov_sub
        constraints = [
            cp.sum(w) == 1.0,
            w >= min_weight,
            w <= max_weight,
        ]
        if prev is not None and max_turnover is not None:
            constraints.append(cp.norm1(w - prev[subset]) <= max_turnover)
        try:
            prob = cp.Problem(cp.Minimize(objective), constraints)
            prob.solve(verbose=False)
        except cp.error.SolverError as exc:
            return None, f"solver_error: {exc}"
        if prob.status not in ("optimal", "optimal_inaccurate") or w.value is None:
            return None, prob.status
        weights = np.nan_to_num(np.asarray(w.value).flatten(), nan=0.0)
        weights = np.clip(weights, 0.0, None)
        total = weights.sum()
        if total > 0:
            weights = weights / total
        return weights, prob.status

    weights, status = _solve(
        list(range(n)),
        np.asarray(prev_weights_vector(codes, prev_weights)) if prev_weights else None,
    )
    info["solver_status"] = status
    if weights is None:
        return None, info

    # 基数约束：保留权重最大的 k 只在子集上重新求解（严格满足数量上限）
    if max_positions is not None and max_positions < n:
        top_k = sorted(range(n), key=lambda i: weights[i], reverse=True)[: max(1, max_positions)]
        top_k = sorted(top_k)
        prev_array = np.asarray(prev_weights_vector(codes, prev_weights)) if prev_weights else None
        subset_weights, subset_status = _solve(top_k, prev_array)
        if subset_weights is not None:
            weights = np.zeros(n)
            weights[top_k] = subset_weights
            info["subset_resolved"] = True
            info["solver_status"] = subset_status
        else:
            info["warnings"] = info.get("warnings", []) + [
                f"数量上限子集重解失败（{subset_status}），沿用全池解后截断"
            ]
            weights = _truncate_to_positions(weights, max_positions)

    result = {
        codes[i]: float(weights[i])
        for i in range(n)
        if weights[i] > WEIGHT_EPSILON
    }
    total = sum(result.values())
    if total > 0:
        result = {code: weight / total for code, weight in result.items()}
    return result, info


def prev_weights_vector(codes: list[str], prev_weights: dict[str, float]) -> list[float]:
    """把上期权重字典展开为与 codes 对齐的向量（缺失补 0）。"""
    return [float(prev_weights.get(code, 0.0)) for code in codes]


def _truncate_to_positions(weights: np.ndarray, max_positions: int) -> np.ndarray:
    """兜底截断：仅保留最大的 max_positions 个权重并再归一。"""
    cleaned = np.zeros_like(weights)
    top = np.argsort(weights)[::-1][: max(1, max_positions)]
    cleaned[top] = weights[top]
    total = cleaned.sum()
    return cleaned / total if total > 0 else cleaned


# ============================================================
# 再平衡回测
# ============================================================


def build_rebalance_schedule(dates: pd.Index, frequency: str, first_date) -> list:
    """按月末/季末生成再平衡日（取不晚于目标日期的最近交易日）。"""
    periods = pd.DatetimeIndex(dates).to_period("M" if frequency == "monthly" else "Q")
    schedule: list = []
    for period in periods.unique():
        in_period = dates[periods == period]
        if len(in_period):
            schedule.append(in_period[-1])
    return [d for d in schedule if d > first_date]


def _portfolio_metrics(port_ret: pd.Series, bench_ret: pd.Series) -> dict:
    """组合 vs 指数的核心指标（年化跟踪误差/超额/波动/最大偏离）。"""
    excess = port_ret - bench_ret
    cum_port = (1.0 + port_ret).cumprod()
    cum_bench = (1.0 + bench_ret).cumprod()
    cum_dev = cum_port / cum_bench - 1.0
    n = len(excess)
    metrics: dict = {"observations": n}
    if n < 2:
        return metrics
    metrics.update({
        "annualized_tracking_error": float(excess.std(ddof=1) * np.sqrt(252)),
        "annualized_return": float(cum_port.iloc[-1] ** (252.0 / n) - 1.0),
        "annualized_excess": float((cum_port.iloc[-1] / cum_bench.iloc[-1]) ** (252.0 / n) - 1.0),
        "annualized_volatility": float(port_ret.std(ddof=1) * np.sqrt(252)),
        "max_deviation": float(cum_dev.loc[cum_dev.abs().idxmax()]),
    })
    return metrics


def run_rebalance_backtest(
    full: pd.DataFrame,
    *,
    lookback_days: int,
    frequency: str,
    optimize_kwargs: dict,
    max_turnover: float | None,
    weighted_fee: float,
) -> dict:
    """walk-forward 再平衡回测：每期用过去 lookback 窗口重新优化。

    - 期间权重逐日随收益漂移（买入持有），再平衡日换到最优权重；
    - 换手 = Σ|新权重 − 漂移权重|（双边），单边 = 双边/2；成本 = 费率 × 单边换手；
    - max_turnover 作用于双边换手，以凸约束进入优化；不可行时该期不交易
      （沿用漂移权重）并记录跳过原因（诚实降级）。
    """
    codes = [c for c in full.columns if c != "__index__"]
    dates = full.index
    if len(dates) <= lookback_days:
        return {
            "available": False,
            "reason": f"历史长度 {len(dates)} ≤ 估计窗口 {lookback_days}，无法样本外回测",
        }

    initial_weights, initial_info = optimize_tracking_weights(
        full.iloc[:lookback_days], **optimize_kwargs
    )
    if initial_weights is None:
        return {
            "available": False,
            "reason": f"初始窗口优化失败（{initial_info.get('solver_status')}）",
        }

    schedule = set(build_rebalance_schedule(dates[lookback_days:], frequency, dates[lookback_days - 1]))
    current = {code: initial_weights.get(code, 0.0) for code in codes}
    rebalances: list[dict] = []
    port_returns: list[float] = []
    bench_returns: list[float] = []
    out_dates: list = []
    total_turnover = 0.0
    total_cost = 0.0

    def _date_label(idx) -> str:
        return str(idx.date() if hasattr(idx, "date") else idx)

    for i in range(lookback_days, len(dates)):
        row = full.iloc[i]
        day = dates[i]
        # 当日组合收益（用当期权重）
        port_returns.append(float(sum(current.get(c, 0.0) * row[c] for c in codes)))
        bench_returns.append(float(row["__index__"]))
        out_dates.append(day)
        # 逐日漂移：权重随当日收益演化后再归一
        drifted = {c: current.get(c, 0.0) * (1.0 + float(row[c])) for c in codes}
        drift_total = sum(drifted.values()) or 1.0
        drifted = {c: v / drift_total for c, v in drifted.items()}

        if day in schedule and i < len(dates) - 1:
            window = full.iloc[max(0, i - lookback_days + 1) : i + 1]
            new_weights, info = optimize_tracking_weights(
                window,
                prev_weights=drifted,
                max_turnover=max_turnover,
                **optimize_kwargs,
            )
            if new_weights is None:
                reason = (
                    f"换手上限不可行（{info.get('solver_status')}），本期沿用漂移权重"
                    if max_turnover is not None
                    else f"优化失败（{info.get('solver_status')}），本期沿用漂移权重"
                )
                rebalances.append({
                    "date": _date_label(day),
                    "turnover": 0.0,
                    "cost": 0.0,
                    "turnover_cap_satisfied": True,
                    "skipped": True,
                    "reason": reason,
                })
                current = drifted
                continue
            turnover_two_sided = sum(
                abs(new_weights.get(c, 0.0) - drifted.get(c, 0.0)) for c in codes
            )
            turnover = turnover_two_sided / 2.0
            cost = weighted_fee * turnover
            cap_satisfied = True
            if max_turnover is not None and turnover_two_sided > max_turnover + 1e-6:
                cap_satisfied = False
            total_turnover += turnover
            total_cost += cost
            rebalances.append({
                "date": _date_label(day),
                "turnover": round(float(turnover), 6),
                "cost": round(float(cost), 8),
                "turnover_cap_satisfied": cap_satisfied,
                "skipped": False,
                "weights": {
                    c: round(w, 6) for c, w in new_weights.items() if w > WEIGHT_EPSILON
                },
            })
            current = {c: new_weights.get(c, 0.0) for c in codes}
        else:
            current = drifted

    port_series = pd.Series(port_returns, index=out_dates)
    bench_series = pd.Series(bench_returns, index=out_dates)
    summary = _portfolio_metrics(port_series, bench_series)
    summary.update({
        "rebalance_frequency": frequency,
        "rebalance_count": sum(1 for r in rebalances if not r.get("skipped")),
        "total_turnover": round(float(total_turnover), 6),
        "total_cost": round(float(total_cost), 8),
        "weighted_fee_rate": round(float(weighted_fee), 6),
    })
    return {"available": True, "summary": summary, "rebalances": rebalances}


# ============================================================
# 行业偏离
# ============================================================


def load_industry_weights(db: Session, benchmark_symbol: str) -> dict[str, float] | None:
    """benchmark_industry_weight 最新快照 → {行业名: 权重占比}（归一）。"""
    rows = db.scalars(
        select(BenchmarkIndustryWeight)
        .where(BenchmarkIndustryWeight.benchmark_symbol == benchmark_symbol)
        .order_by(BenchmarkIndustryWeight.snapshot_date.desc())
    ).all()
    if not rows:
        return None
    latest_date = rows[0].snapshot_date
    latest = [r for r in rows if r.snapshot_date == latest_date]
    total = sum(r.weight_pct for r in latest if r.weight_pct)
    if total <= 0:
        return None
    return {r.industry_name: float(r.weight_pct) / total for r in latest if r.weight_pct}


def compute_industry_deviation(
    db: Session,
    target_symbol: str,
    weights: dict[str, float],
    tracking_by_fund: dict[str, str | None],
) -> dict:
    """组合行业权重（按各 ETF 跟踪指数的行业权重加权合成）vs 目标指数。

    行业权重对照来自 benchmark_industry_weight（SW 口径聚合）；跟踪指数
    无对照的成员计入 uncovered，不硬造行业归属（数据源诚实）。
    """
    target = load_industry_weights(db, target_symbol)
    result: dict = {"available": False}
    if target is None:
        result["reason"] = f"目标指数 {target_symbol} 无行业权重对照（benchmark_industry_weight 缺失）"
        return result

    portfolio: dict[str, float] = {}
    covered_weight = 0.0
    uncovered: list[str] = []
    for fund_code, weight in weights.items():
        symbol = tracking_by_fund.get(fund_code)
        member_industries = load_industry_weights(db, symbol) if symbol else None
        if member_industries is None:
            uncovered.append(fund_code)
            continue
        covered_weight += weight
        for industry, share in member_industries.items():
            portfolio[industry] = portfolio.get(industry, 0.0) + weight * share

    result.update({"available": True, "target_symbol": target_symbol, "uncovered": uncovered})
    if covered_weight <= 0:
        result["available"] = False
        result["reason"] = "入选成员跟踪指数均无行业权重对照"
        return result
    # 未覆盖部分不摊派，偏离仅在已覆盖权重内对照
    scale = 1.0 / covered_weight if covered_weight < 1.0 else 1.0
    rows = []
    industries = sorted(set(portfolio) | set(target), key=lambda k: -(target.get(k, 0.0)))
    for industry in industries:
        port_share = portfolio.get(industry, 0.0) * scale
        target_share = target.get(industry, 0.0)
        deviation = port_share - target_share
        if abs(deviation) > 1e-4 or port_share > 0 or target_share > 0.001:
            rows.append({
                "industry": industry,
                "portfolio_weight": round(port_share, 6),
                "target_weight": round(target_share, 6),
                "deviation": round(deviation, 6),
            })
    result.update({
        "covered_weight": round(covered_weight, 6),
        "rows": rows[:31],
        "total_abs_deviation": round(float(sum(abs(r["deviation"]) for r in rows)), 6),
    })
    return result


# ============================================================
# 主流程
# ============================================================


@dataclass
class BuildParams:
    """ETF 组合构建参数（API 请求映射）。"""

    target_symbol: str = "sh000300"
    fund_codes: list[str] | None = None
    min_weight: float = 0.0
    max_weight: float = DEFAULT_MAX_SINGLE_WEIGHT
    max_positions: int | None = None
    min_scale: float | None = None
    min_amount: float | None = None
    max_fee: float | None = None
    max_tracking_error: float | None = None
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    rebalance_frequency: str = "quarterly"
    max_turnover: float | None = None


def _index_name(db: Session, symbol: str) -> str | None:
    row = db.scalars(
        select(StockDaily).where(StockDaily.stock_code == symbol).limit(1)
    ).first()
    return getattr(row, "stock_name", None) if row else None


def build_etf_portfolio(db: Session, params: BuildParams) -> EtfPortfolioRecord:
    """ETF 组合构建全流程（不落库）。

    流程：候选加载 → 门禁/跟踪指数/阈值过滤 → 收益矩阵对齐 →
    CVXPY 二次规划（Ledoit-Wolf 收缩）→ 历史拟合指标 → 再平衡回测 →
    行业偏离对照 → 约束逐条回显与降级判定。
    """
    record = EtfPortfolioRecord(
        target_symbol=params.target_symbol,
        target_name=_index_name(db, params.target_symbol),
    )

    # 1. 候选加载：指定池优先，否则默认样本内 ETF/联接
    if params.fund_codes:
        candidates = list(
            db.scalars(
                select(FundMain).where(FundMain.fund_code.in_(params.fund_codes))
            ).all()
        )
        missing = set(params.fund_codes) - {f.fund_code for f in candidates}
        for code in sorted(missing):
            record.warnings.append(f"指定候选 {code} 不在 fund_main，已跳过")
    else:
        candidates = load_etf_candidates(db)
    record.candidate_count = len(candidates)
    if not candidates:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append("无候选 ETF（fund_main 内无 ETF/联接或指定池为空）")
        return record

    # 2. 门禁 + 跟踪指数 + 阈值过滤
    eligible, filter_details, filter_warnings = filter_eligible_candidates(
        db,
        candidates,
        params.target_symbol,
        min_scale=params.min_scale,
        min_amount=params.min_amount,
        max_fee=params.max_fee,
        max_tracking_error=params.max_tracking_error,
    )
    record.warnings.extend(filter_warnings)
    record.eligible_count = len(eligible)

    # 3. 收益矩阵对齐（全历史，供拟合与回测共用）
    index_series = load_index_return_series(db, params.target_symbol)
    if index_series.empty:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(f"目标指数 {params.target_symbol} 无行情序列（stock_daily 缺失）")
        return record

    fund_series: dict[str, pd.Series] = {}
    tracking_by_fund: dict[str, str | None] = {}
    for fund in eligible:
        series = load_fund_return_series(db, fund.fund_code)
        if series.empty:
            record.warnings.append(f"{fund.fund_code} 无净值序列，已跳过")
            continue
        fund_series[fund.fund_code] = series
        symbol, _ = resolve_tracking_index(db, fund)
        tracking_by_fund[fund.fund_code] = symbol

    full = align_return_matrix(index_series, fund_series)
    codes = [c for c in full.columns if c != "__index__"]
    dropped = set(fund_series) - set(codes)
    for code in sorted(dropped):
        record.warnings.append(f"{code} 与目标指数无重叠交易日，已剔除")

    if len(codes) < MIN_POOL_SIZE:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(f"可优化候选 {len(codes)} 只 < {MIN_POOL_SIZE}，不输出推荐")
        return record
    if len(full) < MIN_OBSERVATIONS:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(
            f"对齐序列 {len(full)} 交易日 < {MIN_OBSERVATIONS}，不输出推荐"
        )
        return record

    # 4. 静态优化（估计窗口 = 全历史末尾 lookback 段）
    lookback = min(params.lookback_days, len(full))
    estimation = full.iloc[-lookback:]
    optimize_kwargs = {
        "min_weight": params.min_weight,
        "max_weight": params.max_weight,
        "max_positions": params.max_positions,
    }
    weights, opt_info = optimize_tracking_weights(estimation, **optimize_kwargs)
    if weights is None:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(
            f"优化求解失败（{opt_info.get('solver_status')}），不输出推荐"
        )
        return record
    if not opt_info.get("shrinkage"):
        record.warnings.append("Ledoit-Wolf 收缩不可用，回退样本协方差（过拟合风险抬升）")
    record.warnings.extend(opt_info.get("warnings") or [])

    est_min, est_max = estimation.index.min(), estimation.index.max()
    record.window_start = est_min.date() if hasattr(est_min, "date") else est_min
    record.window_end = est_max.date() if hasattr(est_max, "date") else est_max

    # 5. 历史拟合指标 + 单只候选对照（验收：组合 TE < 单只最差候选）
    weight_vector = pd.Series(weights).reindex(codes).fillna(0.0)
    port_ret = estimation[codes].mul(weight_vector).sum(axis=1)
    fitted = _portfolio_metrics(port_ret, estimation["__index__"])
    single_te: dict[str, float] = {}
    for code in codes:
        single = _portfolio_metrics(estimation[code], estimation["__index__"])
        single_te[code] = single.get("annualized_tracking_error", float("inf"))
    worst_single = max(single_te.values()) if single_te else None
    best_single = min(single_te.values()) if single_te else None
    fitted["worst_single_tracking_error"] = worst_single
    fitted["best_single_tracking_error"] = best_single

    # 6. 成员明细（推荐权重 + 属性）与组合属性
    member_weights: dict = {}
    weighted_fee = 0.0
    total_scale = 0.0
    total_amount = 0.0
    for code, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
        fund = next((f for f in eligible if f.fund_code == code), None)
        profile = db.scalar(select(EtfProfile).where(EtfProfile.fund_code == code))
        fee = _total_fee(db, code)
        scale = _latest_scale(db, code)
        amount = profile.avg_daily_amount_1y if profile else None
        member_weights[code] = {
            "weight": round(weight, 6),
            "fund_name": getattr(fund, "short_name", None),
            "fee_pct": fee,
            "scale": scale,
            "avg_daily_amount": amount,
            "tracking_error_1y": (
                profile.tracking_error_1y if profile else None
            ),
        }
        weighted_fee += weight * (fee / 100.0 if fee else 0.0)
        total_scale += weight * (scale or 0.0)
        total_amount += weight * (amount or 0.0)
    record.member_weights = member_weights
    record.portfolio_stats = {
        "fitted": fitted,
        "weighted_fee_pct": round(weighted_fee * 100.0, 4),
        "weighted_scale": round(total_scale, 2),
        "weighted_avg_daily_amount": round(total_amount, 0),
        "shrinkage_applied": bool(opt_info.get("shrinkage")),
        "shrinkage_intensity": opt_info.get("shrinkage_intensity"),
    }

    # 7. 再平衡回测（样本外）
    if params.rebalance_frequency in REBALANCE_FREQUENCIES:
        record.backtest = run_rebalance_backtest(
            full,
            lookback_days=lookback,
            frequency=params.rebalance_frequency,
            optimize_kwargs=optimize_kwargs,
            max_turnover=params.max_turnover,
            weighted_fee=weighted_fee,
        )
    else:
        record.backtest = {
            "available": False,
            "reason": f"未指定再平衡频率（可选 {'/'.join(REBALANCE_FREQUENCIES)}）",
        }

    # 8. 拟合曲线（近一年：组合 vs 指数累计净值，供前端绘制）
    recent = estimation.tail(FIT_CURVE_POINTS)
    cum_port = (1.0 + recent[codes].mul(weight_vector).sum(axis=1)).cumprod()
    cum_bench = (1.0 + recent["__index__"]).cumprod()
    record.backtest["fit_curve"] = [
        {
            "date": str(idx.date() if hasattr(idx, "date") else idx),
            "portfolio": round(float(cum_port.loc[idx]), 6),
            "index": round(float(cum_bench.loc[idx]), 6),
        }
        for idx in cum_port.index
    ]

    # 9. 行业偏离对照
    record.industry_deviation = compute_industry_deviation(
        db, params.target_symbol, weights, tracking_by_fund
    )
    if not record.industry_deviation.get("available"):
        record.warnings.append(
            record.industry_deviation.get("reason", "行业偏离对照不可得")
        )

    # 10. 约束逐条回显（§7.3 第 5 条）
    record.constraints = _build_constraint_echo(
        db, params, weights, filter_details, opt_info, fitted, record.backtest
    )

    # 11. 降级判定：组合拟合 TE 未跑赢单只最差候选 → observation
    te = fitted.get("annualized_tracking_error")
    if te is not None and worst_single is not None and te >= worst_single:
        record.conclusion_status = ConclusionStatus.OBSERVATION.value
        record.warnings.append(
            f"组合拟合跟踪误差 {te:.4f} ≥ 单只最差候选 {worst_single:.4f}，组合未体现分散价值"
        )
    return record


def _build_constraint_echo(
    db: Session,
    params: BuildParams,
    weights: dict[str, float],
    filter_details: list[dict],
    opt_info: dict,
    fitted: dict,
    backtest: dict,
) -> list[dict]:
    """约束清单：每条含名称、参数值、是否满足与明细（前端逐条回显）。"""
    constraints: list[dict] = []
    total = sum(weights.values())
    max_w = max(weights.values()) if weights else 0.0
    min_w = min(weights.values()) if weights else 0.0
    constraints.append({
        "name": "权重合计为 1",
        "value": 1.0,
        "satisfied": abs(total - 1.0) < 1e-3,
        "detail": f"实际合计 {total:.4f}",
    })
    constraints.append({
        "name": "单只权重上限",
        "value": params.max_weight,
        "satisfied": max_w <= params.max_weight + 1e-6,
        "detail": f"最大单只权重 {max_w:.4f}",
    })
    if params.min_weight > 0:
        constraints.append({
            "name": "单只权重下限",
            "value": params.min_weight,
            "satisfied": min_w >= params.min_weight - 1e-6,
            "detail": f"最小入选权重 {min_w:.4f}",
        })
    if params.max_positions is not None:
        count = len(weights)
        constraints.append({
            "name": "持仓数量上限",
            "value": params.max_positions,
            "satisfied": count <= params.max_positions,
            "detail": f"实际入选 {count} 只（子集重解保证严格成立）",
        })
    for threshold, label, key in (
        (params.min_scale, "规模下限（亿元）", "min_scale"),
        (params.min_amount, "流动性下限（日均成交额，元）", "min_amount"),
        (params.max_fee, "费率上限（%/年）", "max_fee"),
        (params.max_tracking_error, "跟踪误差上限", "max_tracking_error"),
    ):
        if threshold is None:
            continue
        rejected = [d for d in filter_details if not d["passed"] and d.get("reason")]
        constraints.append({
            "name": label,
            "value": threshold,
            "satisfied": True,
            "detail": f"过滤阶段已执行，剔除 {len(rejected)} 只候选",
            "key": key,
        })
    constraints.append({
        "name": "协方差 Ledoit-Wolf 收缩",
        "value": True,
        "satisfied": bool(opt_info.get("shrinkage")),
        "detail": (
            f"收缩强度 {opt_info.get('shrinkage_intensity'):.3f}"
            if opt_info.get("shrinkage_intensity") is not None
            else "回退样本协方差"
        ),
    })
    if params.max_turnover is not None:
        rebalances = backtest.get("rebalances") or []
        executed = [r for r in rebalances if not r.get("skipped")]
        violated = [r for r in executed if not r.get("turnover_cap_satisfied", True)]
        constraints.append({
            "name": "再平衡换手上限（双边）",
            "value": params.max_turnover,
            "satisfied": not violated,
            "detail": (
                f"执行 {len(executed)} 期，违反 {len(violated)} 期"
                f"，跳过 {len(rebalances) - len(executed)} 期"
            ),
        })
    return constraints


# ============================================================
# 持久化与查询
# ============================================================


def persist_etf_portfolio(
    db: Session, record: EtfPortfolioRecord, calc_date: dt_date | None = None
) -> EtfPortfolioResult:
    """幂等落库：同 (目标指数, calc_date, 算法版本) 覆盖更新。"""
    calc_date = calc_date or dt_date.today()
    existing = db.scalar(
        select(EtfPortfolioResult).where(
            EtfPortfolioResult.target_symbol == record.target_symbol,
            EtfPortfolioResult.calc_date == calc_date,
            EtfPortfolioResult.algorithm_name == ALGORITHM_NAME,
            EtfPortfolioResult.algorithm_version == ALGORITHM_VERSION,
        )
    )
    if existing is None:
        existing = EtfPortfolioResult(
            target_symbol=record.target_symbol,
            calc_date=calc_date,
            algorithm_name=ALGORITHM_NAME,
            algorithm_version=ALGORITHM_VERSION,
        )
        db.add(existing)
    existing.target_name = record.target_name
    existing.candidate_count = record.candidate_count
    existing.eligible_count = record.eligible_count
    existing.member_weights = record.member_weights
    existing.portfolio_stats = record.portfolio_stats
    existing.backtest = record.backtest
    existing.constraints = record.constraints
    existing.industry_deviation = record.industry_deviation
    existing.window_start = record.window_start
    existing.window_end = record.window_end
    existing.conclusion_status = record.conclusion_status
    existing.warnings = record.warnings or None
    db.flush()
    return existing


def get_etf_portfolio_by_id(db: Session, result_id: int) -> EtfPortfolioResult | None:
    return db.scalar(
        select(EtfPortfolioResult).where(EtfPortfolioResult.id == result_id)
    )


def get_latest_etf_portfolios(db: Session) -> list[EtfPortfolioResult]:
    """最近一个计算日的全部构建结果（各目标指数各一条）。"""
    latest_date = db.scalar(
        select(EtfPortfolioResult.calc_date)
        .where(EtfPortfolioResult.algorithm_version == ALGORITHM_VERSION)
        .order_by(EtfPortfolioResult.calc_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return []
    return list(
        db.scalars(
            select(EtfPortfolioResult)
            .where(
                EtfPortfolioResult.calc_date == latest_date,
                EtfPortfolioResult.algorithm_version == ALGORITHM_VERSION,
            )
            .order_by(EtfPortfolioResult.target_symbol)
        ).all()
    )


def etf_portfolio_row_to_dict(row: EtfPortfolioResult) -> dict:
    return {
        "id": row.id,
        "calc_date": str(row.calc_date),
        "algorithm_version": row.algorithm_version,
        "target_symbol": row.target_symbol,
        "target_name": row.target_name,
        "candidate_count": row.candidate_count,
        "eligible_count": row.eligible_count,
        "member_weights": row.member_weights,
        "portfolio_stats": row.portfolio_stats,
        "backtest": row.backtest,
        "constraints": row.constraints,
        "industry_deviation": row.industry_deviation,
        "window_start": str(row.window_start) if row.window_start else None,
        "window_end": str(row.window_end) if row.window_end else None,
        "conclusion_status": row.conclusion_status,
        "warnings": row.warnings or [],
    }
