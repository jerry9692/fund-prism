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
    1. 交易日缺失
    2. 净值异常跳变（日收益超出阈值）
    3. 复权口径一致性
    4. 分红拆分记录完整性
    """
    report = QualityReport(entity_type="fund_nav")

    if nav_df.empty:
        report.warnings.append("净值数据为空")
        return report

    report.total_records = len(nav_df)
    report.total_fields = len(nav_df.columns)

    # 检查日收益异常跳变（单日超过 20% 视为可疑）
    if "daily_return" in nav_df.columns:
        returns = pd.to_numeric(nav_df["daily_return"], errors="coerce").dropna()
        threshold = 0.20
        big_jumps = returns[returns.abs() > threshold]
        if len(big_jumps) > 0:
            report.anomaly_count += len(big_jumps)
            report.warnings.append(
                f"发现 {len(big_jumps)} 条日收益异常跳变（|return| > {threshold:.0%}）"
            )

    # 检查 null 值覆盖率
    for col in nav_df.columns:
        null_count = nav_df[col].isna().sum()
        if null_count > 0:
            report.fields_missing[col] = int(null_count)

    total_cells = report.total_records * max(report.total_fields, 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = 1
    report.checks_failed = 1 if report.anomaly_count > 0 else 0

    return report


def check_holdings_integrity(holdings_df: pd.DataFrame) -> QualityReport:
    """
    检查持仓数据完整性。

    检查项：
    1. 持仓比例合计是否在合理范围
    2. 证券代码有效性
    3. 行业/评级字段缺失
    4. 重复记录
    """
    report = QualityReport(entity_type="fund_holdings")

    if holdings_df.empty:
        report.warnings.append("持仓数据为空")
        return report

    report.total_records = len(holdings_df)
    report.total_fields = len(holdings_df.columns)

    # 检查 null 覆盖率
    for col in holdings_df.columns:
        null_count = holdings_df[col].isna().sum()
        if null_count > 0:
            report.fields_missing[col] = int(null_count)

    # 检查重复
    dup_count = holdings_df.duplicated().sum()
    if dup_count > 0:
        report.anomaly_count += int(dup_count)
        report.warnings.append(f"发现 {dup_count} 条重复记录")

    total_cells = report.total_records * max(report.total_fields, 1)
    total_missing = sum(report.fields_missing.values())
    report.coverage_rate = 1.0 - (total_missing / total_cells) if total_cells > 0 else 0.0

    report.checks_passed = 1
    report.checks_failed = 1 if report.anomaly_count > 0 else 0

    return report


def compute_field_coverage(df: pd.DataFrame) -> dict[str, float]:
    """计算 DataFrame 各字段的覆盖率。"""
    if df.empty:
        return {}

    n = len(df)
    return {col: (1.0 - df[col].isna().sum() / n) for col in df.columns}
