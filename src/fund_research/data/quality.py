"""
数据质量检查工具。

对拉取的数据进行完整性、一致性、异常值检查，
生成覆盖率报告和数据质量摘要。
"""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


@dataclass
class QualityReport:
    """单次数据质量检查报告。"""

    entity_type: str
    check_date: date | None = None
    total_records: int = 0
    total_fields: int = 0

    # 覆盖率
    coverage_rate: float = 0.0
    fields_covered: int = 0
    fields_missing: dict[str, int] = field(default_factory=dict)  # field_name → missing_count

    # 异常
    anomaly_count: int = 0
    anomaly_details: list[dict] = field(default_factory=list)

    # 校验
    checks_passed: int = 0
    checks_failed: int = 0
    check_results: list[dict] = field(default_factory=list)

    # 综合
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict:
        return {
            "entity": self.entity_type,
            "date": str(self.check_date) if self.check_date else None,
            "records": self.total_records,
            "fields_total": self.total_fields,
            "fields_covered": self.fields_covered,
            "coverage": f"{self.coverage_rate:.1%}",
            "anomalies": self.anomaly_count,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "missing_fields": self.fields_missing,
            "warnings": self.warnings,
        }


def check_nav_continuity(nav_df: pd.DataFrame) -> QualityReport:
    """
    检查净值数据连续性和异常。

    检查项：
    1. 交易日缺失（相邻交易日跳过超过5个工作日）
    2. 净值异常跳变（日收益超出阈值）
    3. 空值检查
    """
    report = QualityReport(entity_type="fund_nav")
    checks_passed = 0
    checks_failed = 0

    if nav_df.empty:
        report.warnings.append("净值数据为空")
        report.checks_passed = 0
        report.checks_failed = 1
        return report

    report.total_records = len(nav_df)
    report.total_fields = len(nav_df.columns)

    if "trade_date" in nav_df.columns:
        dates = pd.to_datetime(nav_df["trade_date"], errors="coerce").dropna().sort_values()
        if len(dates) >= 2:
            gap_anomalies = 0
            for i in range(1, len(dates)):
                prev_date = dates.iloc[i - 1]
                curr_date = dates.iloc[i]
                expected_bdate = pd.bdate_range(start=prev_date, end=curr_date, freq="B")
                business_days_gap = len(expected_bdate) - 1
                if business_days_gap > 3:
                    gap_anomalies += 1
            if gap_anomalies > 0:
                report.anomaly_count += gap_anomalies
                report.warnings.append(f"发现 {gap_anomalies} 处交易日缺口（超过3个工作日）")
                checks_failed += 1
            else:
                checks_passed += 1
        else:
            checks_passed += 1
    else:
        checks_passed += 1

    if "daily_return" in nav_df.columns:
        returns = pd.to_numeric(nav_df["daily_return"], errors="coerce").dropna()
        threshold = 0.20
        big_jumps = returns[returns.abs() > threshold]
        if len(big_jumps) > 0:
            report.anomaly_count += len(big_jumps)
            report.warnings.append(
                f"发现 {len(big_jumps)} 条日收益异常跳变（|return| > {threshold:.0%}）"
            )
            checks_failed += 1
        else:
            checks_passed += 1
    else:
        checks_passed += 1

    has_null = False
    for col in nav_df.columns:
        null_count = nav_df[col].isna().sum()
        if null_count > 0:
            report.fields_missing[col] = int(null_count)
            has_null = True
    if has_null:
        checks_failed += 1
    else:
        checks_passed += 1

    total_cells = report.total_records * max(report.total_fields, 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = checks_passed
    report.checks_failed = checks_failed

    return report


def check_holdings_integrity(holdings_df: pd.DataFrame) -> QualityReport:
    """
    检查持仓数据完整性。

    检查项：
    1. 持仓比例合计是否在合理范围（按report_date分组，合计在[95,105]）
    2. 重复记录
    3. 空值检查
    """
    report = QualityReport(entity_type="fund_holdings")
    checks_passed = 0
    checks_failed = 0

    if holdings_df.empty:
        report.warnings.append("持仓数据为空")
        report.checks_passed = 0
        report.checks_failed = 1
        return report

    report.total_records = len(holdings_df)
    report.total_fields = len(holdings_df.columns)

    if "weight_pct" in holdings_df.columns:
        weight_col = pd.to_numeric(holdings_df["weight_pct"], errors="coerce")
        if "report_date" in holdings_df.columns:
            weight_anomalies = 0
            for report_date, group in holdings_df.groupby("report_date"):
                group_weights = pd.to_numeric(group["weight_pct"], errors="coerce").dropna()
                total_weight = group_weights.sum()
                if total_weight < 95 or total_weight > 105:
                    weight_anomalies += 1
                    report.anomaly_details.append({
                        "report_date": str(report_date),
                        "total_weight_pct": float(total_weight),
                        "issue": "权重合计不在[95, 105]范围内",
                    })
            if weight_anomalies > 0:
                report.anomaly_count += weight_anomalies
                report.warnings.append(f"发现 {weight_anomalies} 个报告期权重合计异常（不在[95,105]范围）")
                checks_failed += 1
            else:
                checks_passed += 1
        else:
            total_weight = weight_col.dropna().sum()
            if total_weight < 95 or total_weight > 105:
                report.anomaly_count += 1
                report.warnings.append(f"权重合计异常: {total_weight:.2f}%（不在[95,105]范围）")
                checks_failed += 1
            else:
                checks_passed += 1
    else:
        checks_passed += 1

    dup_count = holdings_df.duplicated().sum()
    if dup_count > 0:
        report.anomaly_count += int(dup_count)
        report.warnings.append(f"发现 {dup_count} 条重复记录")
        checks_failed += 1
    else:
        checks_passed += 1

    has_null = False
    for col in holdings_df.columns:
        null_count = holdings_df[col].isna().sum()
        if null_count > 0:
            report.fields_missing[col] = int(null_count)
            has_null = True
    if has_null:
        checks_failed += 1
    else:
        checks_passed += 1

    # 检查权重合计（按报告期聚合）
    if "weight_pct" in holdings_df.columns and "report_date" in holdings_df.columns:
        weight_series = pd.to_numeric(holdings_df["weight_pct"], errors="coerce")
        weight_sums = holdings_df.assign(_w=weight_series).groupby("report_date")["_w"].sum()
        for report_date, total_weight in weight_sums.items():
            if pd.isna(total_weight):
                continue
            if total_weight > 110:  # 超过110%视为异常
                report.anomaly_count += 1
                report.warnings.append(
                    f"持仓权重合计异常: {report_date} 总权重 {total_weight:.1f}%"
                )
            elif total_weight < 30 and len(holdings_df) > 5:
                # 仅当持仓条目>5且总权重<30%时提示（可能是十大持仓截断）
                report.warnings.append(
                    f"持仓权重覆盖率较低: {report_date} 总权重 {total_weight:.1f}%"
                )

    total_cells = report.total_records * max(report.total_fields, 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = checks_passed
    report.checks_failed = checks_failed

    return report


def check_stock_daily_continuity(
    stock_df: pd.DataFrame,
    *,
    max_daily_return: float = 0.22,  # A股涨停板约10%/20%，ST 5%，含新股放宽
    min_trading_days: int = 20,
) -> QualityReport:
    """
    检查股票日行情数据连续性和异常值。

    检查项：
    1. 各股票交易日缺失/停牌
    2. 收益率异常跳变（超过涨跌停限制）
    3. 价格为0或负数
    4. 样本期内交易日数不足

    Parameters
    ----------
    stock_df : DataFrame
        须包含 stock_code, trade_date, close_price, daily_return（可选）列。
    max_daily_return : float
        单日收益率绝对值上限，超过则标记为异常。
    min_trading_days : int
        单只股票最少交易日数，低于则警告。
    """
    report = QualityReport(entity_type="stock_daily")

    if stock_df.empty:
        report.warnings.append("股票行情数据为空")
        return report

    report.total_records = len(stock_df)
    report.total_fields = len(stock_df.columns)

    # 检查 null 覆盖率
    key_cols = [c for c in ("stock_code", "trade_date", "close_price") if c in stock_df.columns]
    for col in key_cols:
        null_count = stock_df[col].isna().sum()
        if null_count > 0:
            report.fields_missing[col] = int(null_count)

    # 检查价格为0或负数
    if "close_price" in stock_df.columns:
        bad_prices = stock_df[pd.to_numeric(stock_df["close_price"], errors="coerce") <= 0]
        if len(bad_prices) > 0:
            report.anomaly_count += len(bad_prices)
            report.warnings.append(f"发现 {len(bad_prices)} 条价格<=0的异常记录")

    # 检查日收益率异常
    if "daily_return" in stock_df.columns:
        returns = pd.to_numeric(stock_df["daily_return"], errors="coerce").dropna()
        extreme = returns[returns.abs() > max_daily_return]
        if len(extreme) > 0:
            report.anomaly_count += len(extreme)
            report.warnings.append(
                f"发现 {len(extreme)} 条日收益率异常（|return| > {max_daily_return:.0%}）"
            )

    # 检查各股票交易日数是否充足
    if "stock_code" in stock_df.columns and "trade_date" in stock_df.columns:
        day_counts = stock_df.groupby("stock_code")["trade_date"].nunique()
        thin = day_counts[day_counts < min_trading_days]
        if len(thin) > 0:
            codes = ", ".join(thin.head(5).index.astype(str))
            more = f" 等{len(thin)}只" if len(thin) > 5 else ""
            report.warnings.append(
                f"{len(thin)} 只股票交易日不足{min_trading_days}天（{codes}{more}）"
            )

    # 检查停牌标记一致性（如有is_suspended列）
    if "is_suspended" in stock_df.columns:
        suspended = stock_df[stock_df["is_suspended"] == True]  # noqa: E712
        if len(suspended) > 0:
            pct = len(suspended) / len(stock_df)
            if pct > 0.3:
                report.warnings.append(
                    f"停牌记录占比 {pct:.1%} 过高，可能影响归因准确性"
                )

    total_cells = report.total_records * max(len(key_cols), 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = 2
    report.checks_failed = 1 if report.anomaly_count > 0 else 0

    return report


def check_benchmark_weight_coverage(
    benchmark_weight_df: pd.DataFrame,
    *,
    reference_date: date | None = None,
    max_snapshot_age_days: int = 180,
    min_industry_count: int = 5,
    max_unmapped_weight_pct: float = 30.0,
    min_coverage_pct: float = 70.0,
) -> QualityReport:
    """
    检查基准行业权重数据的覆盖率和时效性。

    检查项：
    1. 快照是否过期（超过max_snapshot_age_days天）
    2. 行业数量是否足够
    3. 未映射权重比例是否过高
    4. 覆盖率是否达标
    5. 权重合计是否在合理范围（应≈100%）

    Parameters
    ----------
    benchmark_weight_df : DataFrame
        须包含 benchmark_symbol, snapshot_date, industry_name, weight_pct,
        coverage_pct（可选）, unmapped_weight_pct（可选）列。
    reference_date : date or None
        参考日期（用于判断快照是否过期）；默认为None时跳过时效性检查。
    max_snapshot_age_days : int
        快照最大允许天数。
    min_industry_count : int
        最少行业数量。
    max_unmapped_weight_pct : float
        未映射权重最大允许百分比。
    min_coverage_pct : float
        最低覆盖率百分比。
    """
    report = QualityReport(entity_type="benchmark_industry_weight")

    if benchmark_weight_df.empty:
        report.warnings.append("基准行业权重数据为空")
        return report

    report.total_records = len(benchmark_weight_df)
    report.total_fields = len(benchmark_weight_df.columns)

    # 检查 null 覆盖率
    key_cols = [
        c for c in ("benchmark_symbol", "snapshot_date", "industry_name", "weight_pct")
        if c in benchmark_weight_df.columns
    ]
    for col in key_cols:
        null_count = benchmark_weight_df[col].isna().sum()
        if null_count > 0:
            report.fields_missing[col] = int(null_count)

    # 按 snapshot_date 分组检查每组
    if "snapshot_date" in benchmark_weight_df.columns and "weight_pct" in benchmark_weight_df.columns:
        # 获取最新快照
        if "snapshot_date" in benchmark_weight_df.columns:
            latest_date = benchmark_weight_df["snapshot_date"].max()
            latest_df = benchmark_weight_df[benchmark_weight_df["snapshot_date"] == latest_date]
        else:
            latest_df = benchmark_weight_df

        # 时效性检查
        if reference_date is not None and "snapshot_date" in benchmark_weight_df.columns:
            age_days = (pd.Timestamp(reference_date) - pd.Timestamp(latest_date)).days
            if isinstance(age_days, (int, float)) and age_days > max_snapshot_age_days:
                report.warnings.append(
                    f"基准权重快照过期：最新快照 {latest_date}，"
                    f"距今 {int(age_days)} 天（阈值 {max_snapshot_age_days} 天）"
                )

        # 行业数量检查
        if "industry_name" in latest_df.columns:
            industry_count = latest_df["industry_name"].nunique()
            if industry_count < min_industry_count:
                report.warnings.append(
                    f"基准行业数量不足: {industry_count} < {min_industry_count}"
                )

        # 权重合计检查
        total_weight = latest_df["weight_pct"].sum()
        if total_weight < 80 or total_weight > 120:
            report.anomaly_count += 1
            report.warnings.append(
                f"基准行业权重合计异常: {total_weight:.1f}%（应接近100%）"
            )

        # 未映射权重检查
        if "unmapped_weight_pct" in latest_df.columns:
            unmapped = latest_df["unmapped_weight_pct"].iloc[0]
            if pd.notna(unmapped) and float(unmapped) > max_unmapped_weight_pct:
                report.warnings.append(
                    f"基准未映射权重过高: {float(unmapped):.1f}% > {max_unmapped_weight_pct}%"
                )

        # 覆盖率检查
        if "coverage_pct" in latest_df.columns:
            cov = latest_df["coverage_pct"].iloc[0]
            if pd.notna(cov) and float(cov) < min_coverage_pct:
                report.warnings.append(
                    f"基准成分覆盖率不足: {float(cov):.1f}% < {min_coverage_pct}%"
                )

    total_cells = report.total_records * max(len(key_cols), 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = 3
    report.checks_failed = 1 if report.anomaly_count > 0 else 0

    return report


def compute_field_coverage(df: pd.DataFrame) -> dict[str, float]:
    """计算 DataFrame 各字段的覆盖率。"""
    if df.empty:
        return {}

    n = len(df)
    return {col: (1.0 - df[col].isna().sum() / n) for col in df.columns}
