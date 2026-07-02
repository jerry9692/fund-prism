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

    total_cells = report.total_records * max(report.total_fields, 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = checks_passed
    report.checks_failed = checks_failed

    return report


def compute_field_coverage(df: pd.DataFrame) -> dict[str, float]:
    """计算 DataFrame 各字段的覆盖率。"""
    if df.empty:
        return {}

    n = len(df)
    return {col: (1.0 - df[col].isna().sum() / n) for col in df.columns}
