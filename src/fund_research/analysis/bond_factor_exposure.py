"""债基金因子暴露 · 粗粒度版（需求书 §6.2.7 / §12.4，Phase 4 计划 P4B）。

对样本内债基按四模板（P4.2-1）做因子收益滚动回归：

1. **一期启用因子**：``bond_coupon``（票息/杠杆近似）、``bond_rate``（利率
   波动，久期代理）、``bond_slope``（曲线斜率）、``bond_credit_aaa``（信用）、
   ``bond_convertible``（转债），另加权益 beta（``style_large_cap`` 即沪深300，
   仅二级债基/转债基金）。
2. **显式不启用**：流动性因子（免费源不可得，告警登记）；``bond_credit_aa`` /
   ``bond_credit_sink`` 序列仅近约 3 个月，默认不回归，待序列积累后开关启用；
   杠杆因子无独立时序，一期并入票息因子说明。
3. **模板分流**：``bond_short`` 只用短端因子（coupon/credit_aaa，剔除
   bond_rate 长端项）；``bond_pure`` 无权益/转债；``bond_secondary`` 加权益
   beta 与转债；``bond_convertible`` 转债因子为必备项。非债基调用心
   ``check_algorithm_applicability`` 拒绝并标 needs_review。
4. **输出**：因子暴露曲线、t 值、滚动 R²（回归稳定性）、因子收益贡献拆解、
   久期/信用/票息杠杆/转债/权益风险雷达数据、同类对比（rank.py 口径）。

回归暴露为模型估计结果：结论状态按门禁与覆盖度分级（computed /
observation / needs_review），指纹回填时使用 ``estimated_*`` 字段隔离。
"""

from dataclasses import dataclass, field
from datetime import date as dt_date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.fingerprint import TEMPLATE_BY_SUB_CATEGORY
from fund_research.analysis.rank import rank_in_category
from fund_research.core.enums import ConclusionStatus
from fund_research.db.models import FundMain, FundNAV
from fund_research.db.models_phase4 import BondFactorExposureResult, FactorReturn
from fund_research.research.credibility import (
    check_algorithm_applicability,
    normalize_fund_family,
)

ALGORITHM_NAME = "bond_factor_exposure"
ALGORITHM_VERSION = "0.1.0"

# 滚动回归窗口与步长（交易日）
WINDOW_DAYS = 120
STEP_DAYS = 20

# 全窗口回归最低样本数（不足一个完整窗口 → needs_review）
MIN_OBSERVATIONS = WINDOW_DAYS

# 单因子序列覆盖度下限（基金存续区间内因子可得占比），低于则剔除该因子
MIN_FACTOR_COVERAGE = 0.6

# 全窗口 R² 下限：低于则结论降为 observation（回归解释力弱，§7.3 第 4 条）
MIN_FULL_WINDOW_R2 = 0.3

# 债基四模板（P4.2-1）
BOND_TEMPLATES = ("bond_pure", "bond_short", "bond_secondary", "bond_convertible")

# 模板 → 因子子集（粗粒度版边界，§12.4 口径决策）
TEMPLATE_FACTORS: dict[str, list[str]] = {
    # 短债：仅短端因子，剔除 bond_rate 长端项
    "bond_short": ["bond_coupon", "bond_credit_aaa"],
    # 纯债：无权益/转债
    "bond_pure": ["bond_coupon", "bond_rate", "bond_slope", "bond_credit_aaa"],
    # 二级债基：+ 转债 + 权益 beta（沪深300）
    "bond_secondary": [
        "bond_coupon",
        "bond_rate",
        "bond_slope",
        "bond_credit_aaa",
        "bond_convertible",
        "style_large_cap",
    ],
    # 转债基金：权益 beta 与转债为核心风险来源
    "bond_convertible": [
        "bond_coupon",
        "bond_rate",
        "bond_slope",
        "bond_credit_aaa",
        "bond_convertible",
        "style_large_cap",
    ],
}

# 模板必备因子：缺失/覆盖不足直接 needs_review（不硬算）
REQUIRED_FACTORS: dict[str, list[str]] = {
    "bond_convertible": ["bond_convertible"],
}

# 显式不启用因子登记（数据源诚实原则：不硬造）
DISABLED_FACTORS: dict[str, str] = {
    "bond_liquidity": "流动性因子免费源不可得，一期显式不启用",
    "bond_credit_aa": "AA 信用因子序列深度不足（中国货币网深度限制），待积累后开关启用",
    "bond_credit_sink": "信用下沉因子序列深度不足，待积累后开关启用",
}

FACTOR_LABELS: dict[str, str] = {
    "bond_coupon": "票息/杠杆",
    "bond_rate": "利率（久期代理）",
    "bond_slope": "曲线斜率",
    "bond_credit_aaa": "信用（AAA）",
    "bond_convertible": "转债",
    "style_large_cap": "权益 Beta（沪深300）",
}


@dataclass
class BondFactorExposureRecord:
    """单只债基的因子暴露回归结果。"""

    fund_code: str
    fund_name: str | None = None
    sub_category: str | None = None
    template_name: str | None = None
    window_days: int = WINDOW_DAYS
    step_days: int = STEP_DAYS
    factor_names: list[str] = field(default_factory=list)
    latest_exposures: dict[str, float] = field(default_factory=dict)
    latest_t_values: dict[str, float] = field(default_factory=dict)
    full_window_r_squared: float | None = None
    avg_rolling_r_squared: float | None = None
    exposure_curves: dict[str, list[dict]] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    radar: dict[str, float | None] = field(default_factory=dict)
    peer_rank: dict[str, dict] = field(default_factory=dict)
    factor_coverage: dict[str, float] = field(default_factory=dict)
    window_start: str | None = None
    window_end: str | None = None
    conclusion_status: str = ConclusionStatus.COMPUTED.value
    warnings: list[str] = field(default_factory=list)

    def to_data(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "sub_category": self.sub_category,
            "template_name": self.template_name,
            "window_days": self.window_days,
            "step_days": self.step_days,
            "factor_names": self.factor_names,
            "factor_labels": {f: FACTOR_LABELS.get(f, f) for f in self.factor_names},
            "latest_exposures": self.latest_exposures,
            "latest_t_values": self.latest_t_values,
            "full_window_r_squared": self.full_window_r_squared,
            "avg_rolling_r_squared": self.avg_rolling_r_squared,
            "exposure_curves": self.exposure_curves,
            "contributions": self.contributions,
            "radar": self.radar,
            "peer_rank": self.peer_rank,
            "factor_coverage": self.factor_coverage,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "conclusion_status": self.conclusion_status,
            "warnings": self.warnings,
        }


# ============================================================
# 候选与数据加载
# ============================================================


def load_bond_fund_candidates(db: Session) -> list[FundMain]:
    """加载债基候选：东财分类归族为 bond_family 的全部基金。"""
    funds = db.scalars(select(FundMain).order_by(FundMain.fund_code)).all()
    return [
        fund
        for fund in funds
        if normalize_fund_family(fund.category) == "bond_family"
    ]


def template_for_fund(fund: FundMain) -> str | None:
    """P4.2-1 模板路由：sub_category → 债基四模板，非债基模板返回 None。"""
    if fund.sub_category is None:
        return None
    template = TEMPLATE_BY_SUB_CATEGORY.get(fund.sub_category)
    if template in BOND_TEMPLATES:
        return template
    return None


def _load_fund_returns(db: Session, fund_code: str) -> pd.Series:
    """基金日收益序列：复权净值 pct_change（单位净值兜底），索引为日期。"""
    rows = db.scalars(
        select(FundNAV)
        .where(FundNAV.fund_code == fund_code)
        .order_by(FundNAV.trade_date)
    ).all()
    values: dict[dt_date, float] = {}
    prev_nav: float | None = None
    for row in rows:
        nav = row.adjusted_nav or row.unit_nav
        if nav is None or nav != nav or nav <= 0:
            continue
        if prev_nav is not None and prev_nav > 0:
            values[row.trade_date] = float(nav) / prev_nav - 1.0
        prev_nav = float(nav)
    return pd.Series(values, dtype="float64").sort_index()


def _load_factor_frame(db: Session, factor_names: list[str]) -> pd.DataFrame:
    """因子日收益宽表：index=trade_date，columns=factor_name。"""
    rows = db.scalars(
        select(FactorReturn).where(FactorReturn.factor_name.in_(factor_names))
    ).all()
    if not rows:
        return pd.DataFrame(columns=factor_names)
    frame = pd.DataFrame(
        [
            {
                "trade_date": row.trade_date,
                "factor_name": row.factor_name,
                "factor_return": row.factor_return,
            }
            for row in rows
            if row.factor_return is not None
        ]
    )
    if frame.empty:
        return pd.DataFrame(columns=factor_names)
    wide = frame.pivot(
        index="trade_date", columns="factor_name", values="factor_return"
    )
    wide = wide.sort_index()
    for name in factor_names:
        if name not in wide.columns:
            wide[name] = np.nan
    return wide[factor_names]


# ============================================================
# 回归核心
# ============================================================


def _ols_window(
    y: np.ndarray, x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """单窗口 OLS（含截距）：返回 (系数[截距+各因子], t 值, R²)。"""
    n, k = x.shape
    design = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ beta
    resid = y - fitted
    dof = max(n - k - 1, 1)
    sigma2 = float(resid @ resid) / dof
    try:
        cov = sigma2 * np.linalg.inv(design.T @ design)
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
        t_values = np.where(se > 0, beta / np.where(se > 0, se, 1.0), 0.0)
    except np.linalg.LinAlgError:
        t_values = np.zeros(k + 1)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r_squared = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else 0.0
    return beta, t_values, r_squared


def compute_exposures(
    fund_returns: pd.Series,
    factor_frame: pd.DataFrame,
    factor_names: list[str],
    *,
    window_days: int = WINDOW_DAYS,
    step_days: int = STEP_DAYS,
) -> dict:
    """滚动回归主计算。

    输入序列须已按日期对齐（调用方保证）。输出：
    - full_window：全样本 OLS（exposures/t_values/r_squared/intercept）
    - rolling：滚动窗口曲线（窗口末日为坐标）
    - contributions：全窗口暴露 × 因子累计收益拆解
    """
    y = fund_returns.values
    x = factor_frame[factor_names].values

    full_beta, full_t, full_r2 = _ols_window(y, x)
    result: dict = {
        "full_window": {
            "intercept": float(full_beta[0]),
            "exposures": {
                f: float(full_beta[i + 1]) for i, f in enumerate(factor_names)
            },
            "t_values": {
                f: float(full_t[i + 1]) for i, f in enumerate(factor_names)
            },
            "r_squared": float(full_r2),
        },
        "rolling_dates": [],
        "rolling_exposures": {f: [] for f in factor_names},
        "rolling_t_values": {f: [] for f in factor_names},
        "rolling_r_squared": [],
    }

    n = len(y)
    dates = list(fund_returns.index)
    starts = list(range(0, n - window_days + 1, step_days))
    # 末窗口对齐数据末尾：避免 latest_exposures 滞后于 window_end（口径一致）
    if starts and starts[-1] + window_days < n:
        starts.append(n - window_days)
    for start in starts:
        end = start + window_days
        beta, t_values, r2 = _ols_window(y[start:end], x[start:end])
        result["rolling_dates"].append(dates[end - 1])
        for i, f in enumerate(factor_names):
            result["rolling_exposures"][f].append(float(beta[i + 1]))
            result["rolling_t_values"][f].append(float(t_values[i + 1]))
        result["rolling_r_squared"].append(float(r2))

    # 贡献拆解：全窗口暴露 × 因子累计收益（+ 截距项），残差兜底
    contributions: dict[str, float] = {}
    fund_cum = float((1.0 + fund_returns).prod() - 1.0)
    explained = float(full_beta[0]) * n
    for i, f in enumerate(factor_names):
        factor_cum = float((1.0 + factor_frame[f]).prod() - 1.0)
        contribution = float(full_beta[i + 1]) * factor_cum
        contributions[f] = contribution
        explained += contribution
    contributions["intercept"] = float(full_beta[0]) * n
    contributions["residual"] = fund_cum - explained
    result["contributions"] = contributions
    result["fund_cum_return"] = fund_cum
    return result


# ============================================================
# 单基金分析
# ============================================================


def analyze_bond_factor_exposure(
    db: Session,
    fund: FundMain,
    *,
    window_days: int = WINDOW_DAYS,
    step_days: int = STEP_DAYS,
) -> BondFactorExposureRecord:
    """单只债基因子暴露分析（不落库）。

    流程：门禁 → 模板路由 → 因子覆盖度筛选 → 对齐回归 → 贡献/雷达 → 状态判定。
    """
    record = BondFactorExposureRecord(
        fund_code=fund.fund_code,
        fund_name=getattr(fund, "short_name", None),
        sub_category=fund.sub_category,
        window_days=window_days,
        step_days=step_days,
    )

    # 门禁3：算法适用性（bond_factor_exposure 仅债基族）
    gate = check_algorithm_applicability("bond_factor_exposure", fund.category)
    if not gate.passed:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(gate.message)
        return record

    # P4.2-1 模板路由：无债基模板 → 不硬算
    template = template_for_fund(fund)
    if template is None:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(
            f"二级分类 '{fund.sub_category or '未知'}' 无债基专用模板，不做跨模板硬算"
        )
        return record
    record.template_name = template

    candidate_factors = TEMPLATE_FACTORS[template]
    factor_frame = _load_factor_frame(db, candidate_factors)
    fund_returns = _load_fund_returns(db, fund.fund_code)
    if fund_returns.empty:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append("基金净值序列缺失，无法回归")
        return record

    # 因子覆盖度（基金存续区间内因子可得占比）与缺失登记
    coverage: dict[str, float] = {}
    for f in candidate_factors:
        if f not in factor_frame.columns or factor_frame[f].notna().sum() == 0:
            coverage[f] = 0.0
            continue
        series = factor_frame[f].dropna()
        span = fund_returns.index[(fund_returns.index >= series.index.min())
                                  & (fund_returns.index <= series.index.max())]
        if len(span) == 0:
            coverage[f] = 0.0
            continue
        overlap = span.intersection(series.index)
        coverage[f] = float(len(overlap) / len(span))
    record.factor_coverage = {f: round(v, 4) for f, v in coverage.items()}

    # 显式不启用因子告警（数据源诚实原则，登记一次）
    record.warnings.extend(
        f"因子 {name} 未启用：{reason}" for name, reason in DISABLED_FACTORS.items()
    )

    # 覆盖度筛选：低于阈值剔除（必备因子不足 → needs_review）
    required = REQUIRED_FACTORS.get(template, [])
    selected: list[str] = []
    for f in candidate_factors:
        if coverage.get(f, 0.0) >= MIN_FACTOR_COVERAGE:
            selected.append(f)
        elif f in required:
            record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
            record.warnings.append(
                f"必备因子 {f}（{FACTOR_LABELS.get(f, f)}）序列覆盖度 "
                f"{coverage.get(f, 0.0):.0%} < {MIN_FACTOR_COVERAGE:.0%}，"
                "回归窗口不足，待序列积累"
            )
            record.factor_names = candidate_factors
            return record
        else:
            record.warnings.append(
                f"因子 {f}（{FACTOR_LABELS.get(f, f)}）覆盖度 "
                f"{coverage.get(f, 0.0):.0%} 不足 {MIN_FACTOR_COVERAGE:.0%}，本期剔除"
            )
    if len(selected) < 2:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append("可用因子不足 2 个，无法进行粗粒度因子回归")
        return record
    record.factor_names = selected

    # 对齐：基金收益 ∩ 全部入选因子（交集即回归有效域）
    aligned = factor_frame[selected].join(fund_returns.rename("fund_return"), how="inner").dropna()
    if len(aligned) < MIN_OBSERVATIONS:
        record.conclusion_status = ConclusionStatus.NEEDS_REVIEW.value
        record.warnings.append(
            f"对齐样本 {len(aligned)} < 最低要求 {MIN_OBSERVATIONS}（一个完整窗口），"
            "因子序列或净值序列不足"
        )
        return record

    fund_returns_aligned = aligned["fund_return"]
    computed = compute_exposures(
        fund_returns_aligned,
        aligned,
        selected,
        window_days=window_days,
        step_days=step_days,
    )

    full = computed["full_window"]
    record.latest_exposures = {f: round(v, 6) for f, v in full["exposures"].items()}
    record.latest_t_values = {f: round(v, 3) for f, v in full["t_values"].items()}
    record.full_window_r_squared = round(full["r_squared"], 4)
    record.contributions = {
        k: round(v, 6) for k, v in computed["contributions"].items()
    }
    record.window_start = str(fund_returns_aligned.index.min())
    record.window_end = str(fund_returns_aligned.index.max())

    # 滚动曲线（窗口末日为坐标）
    curves: dict[str, list[dict]] = {f: [] for f in selected}
    rolling_r2 = computed["rolling_r_squared"]
    for i, wdate in enumerate(computed["rolling_dates"]):
        for f in selected:
            curves[f].append(
                {
                    "date": str(wdate),
                    "exposure": round(computed["rolling_exposures"][f][i], 6),
                    "t_value": round(computed["rolling_t_values"][f][i], 3),
                    "r_squared": round(rolling_r2[i], 4),
                }
            )
    record.exposure_curves = curves
    if rolling_r2:
        record.avg_rolling_r_squared = round(float(np.mean(rolling_r2)), 4)
        # 最新窗口 = 曲线末点（与 full_window 全样本口径互补）
        record.latest_exposures = {
            f: curves[f][-1]["exposure"] for f in selected
        }
        record.latest_t_values = {f: curves[f][-1]["t_value"] for f in selected}

    # 风险雷达：久期=bond_rate 暴露×10（10 年零息久期口径）；
    # 信用=credit_aaa 暴露×3（3Y 中票久期口径）；票息杠杆=票息暴露×因子日均 carry 年化
    exp = full["exposures"]
    coupon_carry: float | None = None
    if "bond_coupon" in exp:
        coupon_mean = float(aligned["bond_coupon"].mean())
        coupon_carry = round(exp["bond_coupon"] * coupon_mean * 252, 4)
    record.radar = {
        "duration": round(exp["bond_rate"] * 10, 3) if "bond_rate" in exp else None,
        "credit": round(exp["bond_credit_aaa"] * 3, 3) if "bond_credit_aaa" in exp else None,
        "coupon_carry_annualized": coupon_carry,
        "convertible": (
            round(exp["bond_convertible"], 4) if "bond_convertible" in exp else None
        ),
        "equity_beta": (
            round(exp["style_large_cap"], 4) if "style_large_cap" in exp else None
        ),
    }

    # 回归稳定性降级（§7.3 第 4 条）
    if record.full_window_r_squared is not None and (
        record.full_window_r_squared < MIN_FULL_WINDOW_R2
    ):
        record.conclusion_status = ConclusionStatus.OBSERVATION.value
        record.warnings.append(
            f"全窗口 R²={record.full_window_r_squared:.2f} < {MIN_FULL_WINDOW_R2}，"
            "因子解释力弱，结论降为观察"
        )
    if len(aligned) < window_days * 2:
        record.warnings.append(
            f"回归有效域仅 {len(aligned)} 个交易日（不足两个窗口），滚动曲线较短"
        )
    return record


def _attach_peer_rank(
    records: list[BondFactorExposureRecord],
) -> None:
    """同类对比（rank.py 口径）：同 sub_category 内按全窗口 R² 排名。"""
    groups: dict[str | None, list[BondFactorExposureRecord]] = {}
    for rec in records:
        if rec.full_window_r_squared is None:
            continue
        groups.setdefault(rec.sub_category, []).append(rec)
    for sub_category, members in groups.items():
        values = {m.fund_code: m.full_window_r_squared for m in members}
        for member in members:
            rank = rank_in_category(
                values,
                member.fund_code,
                ascending=False,
                sub_category=sub_category,
            )
            if rank is not None:
                member.peer_rank["r_squared"] = rank.to_data()


# ============================================================
# 批量与持久化
# ============================================================


def run_bond_factor_batch(
    db: Session,
    fund_codes: list[str] | None = None,
) -> list[BondFactorExposureRecord]:
    """批量分析债基因子暴露（不落库）。

    fund_codes 为 None 时分析全部债基候选；同类对比在同批次内按
    sub_category 分组计算（rank.py 口径）。
    """
    candidates = load_bond_fund_candidates(db)
    if fund_codes:
        wanted = set(fund_codes)
        candidates = [f for f in candidates if f.fund_code in wanted]
    records = [analyze_bond_factor_exposure(db, fund) for fund in candidates]
    _attach_peer_rank(records)
    return records


def persist_bond_factor_exposures(
    db: Session,
    records: list[BondFactorExposureRecord],
    calc_date: dt_date | None = None,
) -> list[BondFactorExposureResult]:
    """幂等落库：同 (fund_code, calc_date, 算法版本) 覆盖更新。"""
    calc_date = calc_date or dt_date.today()
    rows: list[BondFactorExposureResult] = []
    for record in records:
        existing = db.scalar(
            select(BondFactorExposureResult).where(
                BondFactorExposureResult.fund_code == record.fund_code,
                BondFactorExposureResult.calc_date == calc_date,
                BondFactorExposureResult.algorithm_name == ALGORITHM_NAME,
                BondFactorExposureResult.algorithm_version == ALGORITHM_VERSION,
            )
        )
        if existing is None:
            existing = BondFactorExposureResult(
                fund_code=record.fund_code,
                calc_date=calc_date,
                algorithm_name=ALGORITHM_NAME,
                algorithm_version=ALGORITHM_VERSION,
            )
            db.add(existing)
        existing.template_name = record.template_name
        existing.window_days = record.window_days
        existing.step_days = record.step_days
        existing.factor_names = record.factor_names
        existing.latest_exposures = record.latest_exposures
        existing.latest_t_values = record.latest_t_values
        existing.full_window_r_squared = record.full_window_r_squared
        existing.avg_rolling_r_squared = record.avg_rolling_r_squared
        existing.exposure_curves = record.exposure_curves
        existing.contributions = record.contributions
        existing.radar = record.radar
        existing.peer_rank = record.peer_rank
        existing.factor_coverage = record.factor_coverage
        existing.window_start = (
            dt_date.fromisoformat(record.window_start) if record.window_start else None
        )
        existing.window_end = (
            dt_date.fromisoformat(record.window_end) if record.window_end else None
        )
        existing.conclusion_status = record.conclusion_status
        existing.warnings = record.warnings or None
        rows.append(existing)
    db.flush()
    return rows


def get_latest_bond_factor_exposures(db: Session) -> list[BondFactorExposureResult]:
    """取最近一个计算日的全部债基因子暴露结果。"""
    latest_date = db.scalar(
        select(BondFactorExposureResult.calc_date)
        .where(BondFactorExposureResult.algorithm_version == ALGORITHM_VERSION)
        .order_by(BondFactorExposureResult.calc_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return []
    return list(
        db.scalars(
            select(BondFactorExposureResult)
            .where(
                BondFactorExposureResult.calc_date == latest_date,
                BondFactorExposureResult.algorithm_version == ALGORITHM_VERSION,
            )
            .order_by(BondFactorExposureResult.fund_code)
        ).all()
    )


def get_latest_bond_factor_exposure(
    db: Session, fund_code: str
) -> BondFactorExposureResult | None:
    """取单只基金最近一条因子暴露结果。"""
    return db.scalars(
        select(BondFactorExposureResult)
        .where(BondFactorExposureResult.fund_code == fund_code)
        .order_by(BondFactorExposureResult.calc_date.desc())
        .limit(1)
    ).first()


def exposure_row_to_dict(row: BondFactorExposureResult) -> dict:
    return {
        # 代理 ID 为 19 位大整数超 JS Number 安全范围，统一 str 序列化
        "id": str(row.id),
        "fund_code": row.fund_code,
        "calc_date": str(row.calc_date),
        "algorithm_version": row.algorithm_version,
        "template_name": row.template_name,
        "window_days": row.window_days,
        "step_days": row.step_days,
        "factor_names": row.factor_names or [],
        "factor_labels": {
            f: FACTOR_LABELS.get(f, f) for f in (row.factor_names or [])
        },
        "latest_exposures": row.latest_exposures or {},
        "latest_t_values": row.latest_t_values or {},
        "full_window_r_squared": row.full_window_r_squared,
        "avg_rolling_r_squared": row.avg_rolling_r_squared,
        "exposure_curves": row.exposure_curves or {},
        "contributions": row.contributions or {},
        "radar": row.radar or {},
        "peer_rank": row.peer_rank or {},
        "factor_coverage": row.factor_coverage or {},
        "window_start": str(row.window_start) if row.window_start else None,
        "window_end": str(row.window_end) if row.window_end else None,
        "conclusion_status": row.conclusion_status,
        "warnings": row.warnings or [],
    }
