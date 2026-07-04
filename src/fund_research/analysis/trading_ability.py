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

数据来源：
- fund_disclosed_holdings 表（定期报告披露的持仓）
- stock_daily 表（股票日行情，用于评估新增/退出持仓后续表现）

约束：
- 至少需要 2 个报告期的持仓数据
- 持仓股票行情覆盖率 < 60% 时标记 needs_review
- 所有结果为 estimated 级别，不进入默认高置信度结论
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
ALGORITHM_VERSION = "0.1.0"
TRADING_DAYS_PER_YEAR = 252


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

        all_trading_detail.append({
            "period": f"{prev_date} → {curr_date}",
            "turnover_rate": round(turnover, 4),
            "new_positions": new_stocks[:10],
            "exited_positions": exited_stocks[:10],
        })

    # 年化换手率 = 平均单期换手率 × 年化因子
    if turnover_rates:
        avg_turnover = float(np.mean(turnover_rates))
        # 估算年报告期数（季报=4，半年报=2）
        if len(report_dates) > 2:
            avg_gap_days = (report_dates[-1] - report_dates[0]).days / (len(report_dates) - 1)
            annual_factor = TRADING_DAYS_PER_YEAR / max(avg_gap_days, 1)
        else:
            annual_factor = 2.0  # 默认半年报
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

    # 4. 估算平均持仓周期
    if len(report_dates) >= 2:
        avg_gap_days = (report_dates[-1] - report_dates[0]).days / (len(report_dates) - 1)
        # 持仓周期 ≈ 报告期间隔 / 换手率（换手率越高，持仓越短）
        if output.estimated_turnover_rate and output.estimated_turnover_rate > 0:
            output.estimated_holding_period = round(
                avg_gap_days / max(output.estimated_turnover_rate / annual_factor, 0.1), 1
            )

    output.trading_detail = all_trading_detail

    if not output.warnings:
        output.confidence = "medium"
    else:
        output.conclusion_status = "needs_review"

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
        "trading_detail": output.trading_detail,
        "confidence": output.confidence,
        "conclusion_status": output.conclusion_status,
        "warnings": output.warnings,
    }
