"""
交易能力分析模块 (Trading Ability Analysis).

基于基金定期报告披露的持仓变动，估算基金经理的交易能力。
所有输出字段均使用 estimated_ 前缀，conclusion_status 为 estimated。

核心指标：
- estimated_turnover_rate: 换手率（基于持仓权重变动）
- estimated_buy_timing_score: 买入择时能力（新增持仓后续表现）
- estimated_sell_timing_score: 卖出择时能力（退出持仓后续表现）
- estimated_holding_period: 平均持仓周期（天）
- estimated_excess_return_from_trading: 交易带来的超额收益

三种假设交易收益（§6.2.4 第 3 点）：
- estimated_trading_return_conservative: 保守假设（买入取区间最高价/卖出取最低价）
- estimated_trading_return_neutral: 中性假设（买入/卖出取区间均价）
- estimated_trading_return_optimistic: 乐观假设（买入取区间最低价/卖出取最高价）
- estimated_trading_return_range: 乐观 - 保守，衡量执行时点不确定性

数据来源：
- fund_disclosed_holdings 表（定期报告披露的持仓）
- stock_daily 表（股票日行情，用于评估新增/退出持仓后续表现）

约束：
- 至少需要 2 个报告期的持仓数据
- 持仓股票行情覆盖率 < 60% 时标记 needs_review
- 所有结果为 estimated 级别，不进入默认高置信度结论
- 三种假设差异较大时（range > SCENARIO_DIVERGENCE_THRESHOLD）降级为低置信度
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import FundDisclosedHoldings, StockDaily

ALGORITHM_NAME = "trading_ability"
ALGORITHM_VERSION = "0.2.0"
TRADING_DAYS_PER_YEAR = 252

# §6.2.4 验收标准 2: 不同交易假设下结果差异较大时需提示低置信度。
# 当乐观-保守区间超过此阈值时，confidence 降为 low。
SCENARIO_DIVERGENCE_THRESHOLD = 0.05


@dataclass
class TradingAbilityOutput:
    """交易能力分析输出。"""

    fund_code: str
    calc_date: date
    period_start: date | None = None
    period_end: date | None = None
    estimated_turnover_rate: float | None = None
    estimated_buy_timing_score: float | None = None
    estimated_sell_timing_score: float | None = None
    estimated_holding_period: float | None = None
    estimated_excess_return_from_trading: float | None = None
    # 三种假设交易收益（§6.2.4 第 3 点）：保守/中性/乐观
    estimated_trading_return_conservative: float | None = None
    estimated_trading_return_neutral: float | None = None
    estimated_trading_return_optimistic: float | None = None
    estimated_trading_return_range: float | None = None
    trading_detail: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conclusion_status: str = "estimated"
    confidence: str = "low"


def _load_holdings(
    db: Session,
    fund_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """加载基金披露持仓数据，按报告期排序。"""
    stmt = select(FundDisclosedHoldings).where(
        FundDisclosedHoldings.fund_code == fund_code,
        FundDisclosedHoldings.asset_type.in_(["stock", "equity", "股票"]),
    )
    if start_date:
        stmt = stmt.where(FundDisclosedHoldings.report_date >= start_date)
    if end_date:
        stmt = stmt.where(FundDisclosedHoldings.report_date <= end_date)
    stmt = stmt.order_by(FundDisclosedHoldings.report_date, FundDisclosedHoldings.security_code)

    rows = db.execute(stmt).scalars().all()
    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        records.append({
            "report_date": r.report_date,
            "security_code": r.security_code,
            "security_name": r.security_name,
            "weight_pct": float(r.weight_pct) if r.weight_pct is not None else None,
            "market_value": float(r.market_value) if r.market_value is not None else None,
        })
    return pd.DataFrame(records)


def _load_stock_returns(
    db: Session,
    stock_codes: list[str],
    start: date,
    end: date,
) -> dict[str, pd.Series]:
    """加载股票日收益率序列。"""
    if not stock_codes:
        return {}

    # 按批次查询避免 IN 子句过长
    result: dict[str, pd.Series] = {}
    batch_size = 200
    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i : i + batch_size]
        stmt = select(StockDaily).where(
            StockDaily.stock_code.in_(batch),
            StockDaily.trade_date >= start,
            StockDaily.trade_date <= end,
        ).order_by(StockDaily.stock_code, StockDaily.trade_date)
        rows = db.execute(stmt).scalars().all()
        for r in rows:
            code = r.stock_code
            if code not in result:
                result[code] = pd.Series(dtype=float)
            if r.close_price and r.daily_return is not None:
                result[code][r.trade_date] = float(r.daily_return)
            elif r.close_price:
                result[code][r.trade_date] = float(r.close_price)

    # 转换为收益率
    for code in list(result.keys()):
        s = result[code]
        if len(s) > 1:
            # 如果是价格序列，转为收益率
            if abs(s.iloc[0]) > 1.0:
                result[code] = s.pct_change().dropna()
            # 否则已经是收益率
        else:
            del result[code]

    # 确保 index 为 datetime 类型，避免 date vs Timestamp 比较问题
    for code in list(result.keys()):
        if not result[code].empty:
            result[code].index = pd.to_datetime(result[code].index)

    return result


def _compute_turnover(
    prev_weights: dict[str, float],
    curr_weights: dict[str, float],
) -> float:
    """计算单期换手率 = sum(|w_curr - w_prev|) / 2。"""
    all_codes = set(prev_weights) | set(curr_weights)
    total_change = 0.0
    for code in all_codes:
        pw = prev_weights.get(code, 0.0)
        cw = curr_weights.get(code, 0.0)
        total_change += abs(cw - pw)
    return total_change / 2.0


def _evaluate_buy_timing(
    new_stocks: list[str],
    stock_returns: dict[str, pd.Series],
    report_date: date,
    window_days: int = 60,
) -> tuple[float | None, list[dict]]:
    """评估买入择时能力：新增持仓在后续 window_days 天的收益。"""
    if not new_stocks:
        return None, []

    end_date = report_date + timedelta(days=window_days)
    details = []
    returns_list = []

    for code in new_stocks:
        if code not in stock_returns:
            continue
        s = stock_returns[code]
        mask = (s.index >= pd.Timestamp(report_date)) & (s.index <= pd.Timestamp(end_date))
        period_returns = s[mask]
        if len(period_returns) == 0:
            continue
        cum_ret = float((1 + period_returns).prod() - 1)
        returns_list.append(cum_ret)
        details.append({
            "security_code": code,
            "action": "buy",
            "subsequent_return": round(cum_ret, 4),
            "days_held": len(period_returns),
        })

    if not returns_list:
        return None, details

    # 买入择时得分 = 新增持仓平均收益（正值表示买入时机好）
    score = float(np.mean(returns_list))
    return score, details


def _evaluate_sell_timing(
    exited_stocks: list[str],
    stock_returns: dict[str, pd.Series],
    report_date: date,
    window_days: int = 60,
) -> tuple[float | None, list[dict]]:
    """评估卖出择时能力：退出持仓在后续 window_days 天的收益（负值表示卖出时机好）。"""
    if not exited_stocks:
        return None, []

    end_date = report_date + timedelta(days=window_days)
    details = []
    returns_list = []

    for code in exited_stocks:
        if code not in stock_returns:
            continue
        s = stock_returns[code]
        mask = (s.index >= pd.Timestamp(report_date)) & (s.index <= pd.Timestamp(end_date))
        period_returns = s[mask]
        if len(period_returns) == 0:
            continue
        cum_ret = float((1 + period_returns).prod() - 1)
        # 卖出择时得分 = -后续收益（卖出后跌 = 卖对了 = 正分）
        returns_list.append(-cum_ret)
        details.append({
            "security_code": code,
            "action": "sell",
            "subsequent_return": round(cum_ret, 4),
            "days_held": len(period_returns),
        })

    if not returns_list:
        return None, details

    score = float(np.mean(returns_list))
    return score, details


def _load_stock_close_prices(
    db: Session,
    stock_codes: list[str],
    start: date,
    end: date,
) -> dict[str, pd.Series]:
    """加载股票收盘价序列（区别于 _load_stock_returns 的收益率序列）。

    用于三种假设交易收益计算：需要区间内的原始价格来取 high/low/mean。
    """
    if not stock_codes:
        return {}

    result: dict[str, pd.Series] = {}
    batch_size = 200
    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i : i + batch_size]
        stmt = select(StockDaily).where(
            StockDaily.stock_code.in_(batch),
            StockDaily.trade_date >= start,
            StockDaily.trade_date <= end,
        ).order_by(StockDaily.stock_code, StockDaily.trade_date)
        rows = db.execute(stmt).scalars().all()
        for r in rows:
            code = r.stock_code
            if code not in result:
                result[code] = pd.Series(dtype=float)
            if r.close_price:
                result[code][r.trade_date] = float(r.close_price)

    # 删除只有 0 或 1 个数据点的序列
    for code in list(result.keys()):
        if len(result[code]) < 2:
            del result[code]

    # 确保 index 为 datetime 类型，避免 date vs Timestamp 比较问题
    for code in list(result.keys()):
        if not result[code].empty:
            result[code].index = pd.to_datetime(result[code].index)

    return result


def _compute_three_scenario_trading_returns(
    new_stocks: list[str],
    exited_stocks: list[str],
    stock_prices: dict[str, pd.Series],
    prev_date: date,
    curr_date: date,
) -> dict[str, float | None]:
    """计算单期保守/中性/乐观三种假设下的交易收益贡献（§6.2.4 第 3 点）。

    核心思路：基金在 [prev_date, curr_date] 区间内的某个未知时点执行了交易。
    由于报告期只披露快照持仓，实际执行价格不可观测，用价格路径的极值/均值
    构建三种假设来界定交易收益的不确定性区间。

    买入（新增持仓）：
        执行价未知，假设在 [prev, curr] 区间内买入
        - 保守：买入价 = 区间最高价（买在最高点，收益最低）
        - 中性：买入价 = 区间均价
        - 乐观：买入价 = 区间最低价（买在最低点，收益最高）
        交易收益 = (curr_report_close - assumed_entry) / assumed_entry

    卖出（退出持仓）：
        执行价未知，假设在 [prev, curr] 区间内卖出
        - 保守：卖出价 = 区间最低价（卖在最低点，收益最低）
        - 中性：卖出价 = 区间均价
        - 乐观：卖出价 = 区间最高价（卖在最高点，收益最高）
        交易收益 = (assumed_exit - prev_report_close) / prev_report_close

    Returns
    -------
    dict with keys: conservative, neutral, optimistic (each float | None)
    """
    conservative_returns: list[float] = []
    neutral_returns: list[float] = []
    optimistic_returns: list[float] = []

    for code in new_stocks:
        if code not in stock_prices:
            continue
        prices = stock_prices[code]
        interval = prices[
            (prices.index >= pd.Timestamp(prev_date))
            & (prices.index <= pd.Timestamp(curr_date))
        ]
        if interval.empty:
            continue
        curr_price = float(interval.iloc[-1])
        high = float(interval.max())
        low = float(interval.min())
        avg = float(interval.mean())

        # 买入收益 = (curr - entry) / entry
        if high > 0:
            conservative_returns.append((curr_price - high) / high)
        if avg > 0:
            neutral_returns.append((curr_price - avg) / avg)
        if low > 0:
            optimistic_returns.append((curr_price - low) / low)

    for code in exited_stocks:
        if code not in stock_prices:
            continue
        prices = stock_prices[code]
        interval = prices[
            (prices.index >= pd.Timestamp(prev_date))
            & (prices.index <= pd.Timestamp(curr_date))
        ]
        if interval.empty:
            continue
        prev_price = float(interval.iloc[0])
        high = float(interval.max())
        low = float(interval.min())
        avg = float(interval.mean())

        # 卖出收益 = (exit - prev) / prev
        if prev_price > 0:
            conservative_returns.append((low - prev_price) / prev_price)
            neutral_returns.append((avg - prev_price) / prev_price)
            optimistic_returns.append((high - prev_price) / prev_price)

    return {
        "conservative": float(np.mean(conservative_returns)) if conservative_returns else None,
        "neutral": float(np.mean(neutral_returns)) if neutral_returns else None,
        "optimistic": float(np.mean(optimistic_returns)) if optimistic_returns else None,
    }


def analyze_trading_ability(
    db: Session,
    fund_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    evaluation_window_days: int = 60,
) -> TradingAbilityOutput:
    """
    分析基金交易能力。

    Args:
        db: 数据库会话
        fund_code: 基金代码
        start_date: 分析起始日期
        end_date: 分析截止日期
        evaluation_window_days: 评估买卖择时的后续观察窗口（天）

    Returns:
        TradingAbilityOutput 包含所有 estimated_ 指标
    """
    calc_date = date.today()
    output = TradingAbilityOutput(fund_code=fund_code, calc_date=calc_date)

    # 1. 加载持仓数据
    holdings_df = _load_holdings(db, fund_code, start_date, end_date)
    if holdings_df.empty:
        output.warnings.append("无披露持仓数据")
        output.conclusion_status = "needs_review"
        return output

    report_dates = sorted(holdings_df["report_date"].unique())
    if len(report_dates) < 2:
        output.warnings.append("持仓报告期不足2期，无法计算换手率")
        output.conclusion_status = "needs_review"
        return output

    output.period_start = report_dates[0]
    output.period_end = report_dates[-1]

    # 2. 计算逐期换手率和持仓变动
    turnover_rates = []
    all_trading_detail = []
    all_new_stocks = []
    all_exited_stocks = []
    # 记录每期的新增/退出股票，供三种假设计算使用（§6.2.4 第 3 点）
    period_trades: list[tuple[date, date, list[str], list[str]]] = []

    for i in range(1, len(report_dates)):
        prev_date = report_dates[i - 1]
        curr_date = report_dates[i]

        prev_df = holdings_df[holdings_df["report_date"] == prev_date]
        curr_df = holdings_df[holdings_df["report_date"] == curr_date]

        prev_weights = dict(zip(prev_df["security_code"], prev_df["weight_pct"].fillna(0), strict=False))
        curr_weights = dict(zip(curr_df["security_code"], curr_df["weight_pct"].fillna(0), strict=False))

        turnover = _compute_turnover(prev_weights, curr_weights)
        turnover_rates.append(turnover)

        new_stocks = [c for c in curr_weights if c not in prev_weights]
        exited_stocks = [c for c in prev_weights if c not in curr_weights]
        all_new_stocks.extend(new_stocks)
        all_exited_stocks.extend(exited_stocks)
        period_trades.append((prev_date, curr_date, new_stocks, exited_stocks))

        all_trading_detail.append({
            "period": f"{prev_date} → {curr_date}",
            "turnover_rate": round(turnover, 4),
            "new_positions": new_stocks[:10],
            "exited_positions": exited_stocks[:10],
        })

    # 年化换手率 = 平均单期换手率 × 年化因子
    annual_factor = 2.0
    if turnover_rates:
        avg_turnover = float(np.mean(turnover_rates))
        # 按相邻报告期平均间隔天数推算年化因子（季报/半年报/年报自适应）
        avg_gap_days = (report_dates[-1] - report_dates[0]).days / (len(report_dates) - 1)
        annual_factor = TRADING_DAYS_PER_YEAR / max(avg_gap_days, 1)
        output.estimated_turnover_rate = round(avg_turnover * annual_factor, 4)

    # 3. 评估买卖择时能力
    unique_new = list(set(all_new_stocks))
    unique_exited = list(set(all_exited_stocks))
    all_codes = unique_new + unique_exited

    if all_codes:
        stock_start = report_dates[0]
        stock_end = report_dates[-1] + timedelta(days=evaluation_window_days + 30)
        stock_returns = _load_stock_returns(db, all_codes, stock_start, stock_end)

        # 检查行情覆盖率
        coverage = len(stock_returns) / len(all_codes) if all_codes else 0
        if coverage < 0.6:
            output.warnings.append(f"持仓股票行情覆盖率 {coverage:.0%}，低于60%阈值")

        # 对最近一个报告期评估买卖择时
        last_report = report_dates[-1]
        buy_score, buy_details = _evaluate_buy_timing(
            unique_new, stock_returns, last_report, evaluation_window_days
        )
        sell_score, sell_details = _evaluate_sell_timing(
            unique_exited, stock_returns, last_report, evaluation_window_days
        )

        output.estimated_buy_timing_score = round(buy_score, 4) if buy_score is not None else None
        output.estimated_sell_timing_score = round(sell_score, 4) if sell_score is not None else None

        # 交易超额收益 = 买入得分 + 卖出得分
        if buy_score is not None or sell_score is not None:
            scores = [s for s in [buy_score, sell_score] if s is not None]
            output.estimated_excess_return_from_trading = round(float(np.mean(scores)), 4)

        all_trading_detail.extend(buy_details)
        all_trading_detail.extend(sell_details)

    # 3b. 三种假设交易收益（§6.2.4 第 3 点）
    # 基金在 [prev, curr] 区间内的执行时点不可观测，用价格路径极值/均值
    # 构建保守/中性/乐观三种假设，界定交易收益不确定性区间。
    all_period_codes = set()
    for _, _, news, exits in period_trades:
        all_period_codes.update(news)
        all_period_codes.update(exits)

    if all_period_codes:
        stock_prices = _load_stock_close_prices(
            db, list(all_period_codes), report_dates[0], report_dates[-1],
        )

        period_conservative: list[float] = []
        period_neutral: list[float] = []
        period_optimistic: list[float] = []

        for prev_date, curr_date, news, exits in period_trades:
            scenario = _compute_three_scenario_trading_returns(
                news, exits, stock_prices, prev_date, curr_date,
            )
            if scenario["conservative"] is not None:
                period_conservative.append(scenario["conservative"])
            if scenario["neutral"] is not None:
                period_neutral.append(scenario["neutral"])
            if scenario["optimistic"] is not None:
                period_optimistic.append(scenario["optimistic"])

        if period_conservative:
            output.estimated_trading_return_conservative = round(
                float(np.mean(period_conservative)), 6,
            )
        if period_neutral:
            output.estimated_trading_return_neutral = round(
                float(np.mean(period_neutral)), 6,
            )
        if period_optimistic:
            output.estimated_trading_return_optimistic = round(
                float(np.mean(period_optimistic)), 6,
            )

        # 区间 = 乐观 - 保守，衡量执行时点不确定性
        if (
            output.estimated_trading_return_optimistic is not None
            and output.estimated_trading_return_conservative is not None
        ):
            output.estimated_trading_return_range = round(
                output.estimated_trading_return_optimistic
                - output.estimated_trading_return_conservative,
                6,
            )
            # §6.2.4 验收标准 2: 差异较大时提示低置信度
            if output.estimated_trading_return_range > SCENARIO_DIVERGENCE_THRESHOLD:
                output.warnings.append(
                    f"三种假设交易收益区间 {output.estimated_trading_return_range:.1%}，"
                    f"超过 {SCENARIO_DIVERGENCE_THRESHOLD:.0%} 阈值，"
                    f"执行时点不确定性较大，置信度降为 low"
                )

    # 4. 估算平均持仓周期
    if len(report_dates) >= 2:
        avg_gap_days = (report_dates[-1] - report_dates[0]).days / (len(report_dates) - 1)
        # 持仓周期 ≈ 报告期间隔 / 换手率（换手率越高，持仓越短）
        if output.estimated_turnover_rate and output.estimated_turnover_rate > 0:
            output.estimated_holding_period = round(
                avg_gap_days / max(output.estimated_turnover_rate / annual_factor, 0.1), 1
            )

    output.trading_detail = all_trading_detail

    # 置信度评估（§6.2.4 验收标准 1/2）
    # 交易能力结论始终为 estimated（交易时间不可完全观测）。
    # 数据质量告警（覆盖率不足）→ needs_review；
    # 仅三假设差异告警 → 置信度 low 但仍为 estimated；
    # 无告警 → medium。
    has_data_quality_warning = any("覆盖率" in w for w in output.warnings)
    if has_data_quality_warning:
        output.conclusion_status = "needs_review"
    elif not output.warnings:
        output.confidence = "medium"
    # else: 仅三假设差异 → confidence 保持默认 low，status 保持 estimated

    return output


def to_api_data(output: TradingAbilityOutput) -> dict[str, Any]:
    """转换为 API 返回字典（estimated_ 前缀）。"""
    return {
        "fund_code": output.fund_code,
        "calc_date": str(output.calc_date),
        "period_start": str(output.period_start) if output.period_start else None,
        "period_end": str(output.period_end) if output.period_end else None,
        "estimated_turnover_rate": output.estimated_turnover_rate,
        "estimated_buy_timing_score": output.estimated_buy_timing_score,
        "estimated_sell_timing_score": output.estimated_sell_timing_score,
        "estimated_holding_period": output.estimated_holding_period,
        "estimated_excess_return_from_trading": output.estimated_excess_return_from_trading,
        # 三种假设交易收益（§6.2.4 第 3 点）
        "estimated_trading_return_conservative": output.estimated_trading_return_conservative,
        "estimated_trading_return_neutral": output.estimated_trading_return_neutral,
        "estimated_trading_return_optimistic": output.estimated_trading_return_optimistic,
        "estimated_trading_return_range": output.estimated_trading_return_range,
        "trading_detail": output.trading_detail,
        "confidence": output.confidence,
        "conclusion_status": output.conclusion_status,
        "warnings": output.warnings,
    }
