"""
结论可信度门禁模块 (Conclusion Credibility Gating).

实现需求书 v0.4 §5.5 定义的五道门禁检查：
1. 数据完整性门禁 (data completeness) — 关键数据覆盖率阈值
2. 数据源等级门禁 (source level) — 核心事实最低数据源等级要求
3. 算法适用性门禁 (algorithm applicability) — 基金类型适配性
4. 残差阈值门禁 (residual threshold) — 风格/归因残差阈值降级
5. 证据完整度门禁 (evidence completeness) — 每个结论必须有证据支撑

所有门禁通过后，结论才能进入默认高置信度结论；否则降级为 observation / needs_review。
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fund_research.core.enums import ConclusionStatus, DataSourceLevel


class GateType(StrEnum):
    """门禁类型。"""

    DATA_COMPLETENESS = "data_completeness"
    SOURCE_LEVEL = "source_level"
    ALGORITHM_APPLICABILITY = "algorithm_applicability"
    RESIDUAL_THRESHOLD = "residual_threshold"
    EVIDENCE_COMPLETENESS = "evidence_completeness"


class GateSeverity(StrEnum):
    """门禁严重度：hard 不通过则降级为 needs_review；soft 不通过则降级为 observation。"""

    HARD = "hard"
    SOFT = "soft"


@dataclass
class GateResult:
    """单条门禁检查结果。"""

    gate_type: GateType
    passed: bool
    severity: GateSeverity
    message: str
    module: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CredibilityReport:
    """可信度门禁报告。"""

    fund_code: str
    results: list[GateResult] = field(default_factory=list)
    module_statuses: dict[str, ConclusionStatus] = field(default_factory=dict)
    overall_status: ConclusionStatus = ConclusionStatus.NEEDS_REVIEW
    warnings: list[str] = field(default_factory=list)

    def add(self, result: GateResult) -> None:
        self.results.append(result)
        if not result.passed:
            self.warnings.append(f"[{result.module}] {result.message}")

    def compute_overall(self) -> ConclusionStatus:
        """根据门禁结果计算整体结论状态。

        规则：
        - 任一 hard gate 失败 → needs_review
        - 任一 soft gate 失败 → observation
        - 全部通过 → computed（fact 级别由模块自行根据数据来源判断）
        """
        has_hard_failure = any(
            not r.passed and r.severity == GateSeverity.HARD for r in self.results
        )
        has_soft_failure = any(
            not r.passed and r.severity == GateSeverity.SOFT for r in self.results
        )
        if has_hard_failure:
            self.overall_status = ConclusionStatus.NEEDS_REVIEW
        elif has_soft_failure:
            self.overall_status = ConclusionStatus.OBSERVATION
        else:
            self.overall_status = ConclusionStatus.COMPUTED
        return self.overall_status


# ============================================================
# 模块最低要求配置
# ============================================================

# 核心模块（影响整体可信度）
CORE_MODULES = {
    "fund_profile", "manager_info", "nav_metrics",
    "disclosed_holdings", "holder_structure", "exposure", "attribution",
}

# 原始事实类模块（数据来自数据库直接查询，无算法计算）
FACT_MODULES = {"fund_profile", "manager_info", "holder_structure"}

# 各模块的最低数据源等级要求（A > B > LOCAL > C）
MIN_SOURCE_LEVEL: dict[str, DataSourceLevel] = {
    "fund_profile": DataSourceLevel.B,
    "manager_info": DataSourceLevel.B,
    "nav_metrics": DataSourceLevel.B,
    "disclosed_holdings": DataSourceLevel.B,
    "holder_structure": DataSourceLevel.B,
    "exposure": DataSourceLevel.B,
    "attribution": DataSourceLevel.B,
}

# 各模块的最低数据覆盖率（0-1）
MIN_COVERAGE: dict[str, float] = {
    "nav_metrics": 0.8,       # NAV 数据需覆盖至少 80% 的目标区间
    "disclosed_holdings": 0.5,  # 持仓至少有最近1期
    "exposure": 0.6,          # 风格暴露至少覆盖 60% 交易日
}

# 残差阈值（超过则降级）
MAX_RESIDUAL: dict[str, float] = {
    "exposure_r_squared_min": 0.5,    # 风格回归 R² < 0.5 → 降级
    "attribution_residual_max": 0.5,  # 归因残差占比 > 50% → 降级
}

# 不适用于某类基金的模块
MODULE_FUND_TYPE_EXCLUSIONS: dict[str, set[str]] = {
    "exposure": {"债券型", "货币型", "偏债混合"},
    "attribution": {"债券型", "货币型"},
    "simulated_holding": {"债券型", "货币型", "指数型"},
    "dynamic_attribution": {"债券型", "货币型"},
    "scoring": {"货币型"},
}


# ============================================================
# 五道门禁检查函数
# ============================================================

def check_data_completeness(
    module: str,
    data: dict[str, Any] | None,
    meta: dict[str, Any] | None = None,
) -> GateResult:
    """
    门禁1：数据完整性检查。

    检查关键模块的数据覆盖率是否达到最低阈值。
    """
    meta = meta or {}
    threshold = MIN_COVERAGE.get(module, 0.0)

    if data is None:
        # 核心模块无数据 → hard failure
        severity = GateSeverity.HARD if module in CORE_MODULES else GateSeverity.SOFT
        return GateResult(
            gate_type=GateType.DATA_COMPLETENESS,
            passed=False,
            severity=severity,
            message=f"模块 {module} 无数据",
            module=module,
        )

    # 从 metadata 中读取覆盖率信息
    coverage = meta.get("coverage_rate") or data.get("coverage_rate")
    if coverage is not None:
        passed = coverage >= threshold
        return GateResult(
            gate_type=GateType.DATA_COMPLETENESS,
            passed=passed,
            severity=GateSeverity.HARD if module in CORE_MODULES else GateSeverity.SOFT,
            message=(
                f"数据覆盖率 {coverage:.0%}，"
                f"{'达到' if passed else '未达到'}最低要求 {threshold:.0%}"
            ),
            module=module,
            details={"coverage_rate": coverage, "threshold": threshold},
        )

    # 无覆盖率元数据时，检查是否有核心字段
    nav_start = data.get("start_date")
    nav_end = data.get("end_date")
    if module == "nav_metrics" and nav_start and nav_end:
        # 有起止日期视为有基本数据
        return GateResult(
            gate_type=GateType.DATA_COMPLETENESS,
            passed=True,
            severity=GateSeverity.HARD,
            message="NAV 数据存在",
            module=module,
        )

    # 默认：有 data 对象视为通过完整性检查
    return GateResult(
        gate_type=GateType.DATA_COMPLETENESS,
        passed=True,
        severity=GateSeverity.SOFT,
        message="数据存在",
        module=module,
    )


def check_source_level(
    module: str,
    source_level: DataSourceLevel | None,
) -> GateResult:
    """
    门禁2：数据源等级检查。

    核心模块的数据源等级不得低于最低要求。
    """
    required = MIN_SOURCE_LEVEL.get(module)
    if required is None:
        return GateResult(
            gate_type=GateType.SOURCE_LEVEL,
            passed=True,
            severity=GateSeverity.SOFT,
            message=f"模块 {module} 无最低数据源等级要求",
            module=module,
        )

    if source_level is None:
        return GateResult(
            gate_type=GateType.SOURCE_LEVEL,
            passed=False,
            severity=GateSeverity.SOFT,
            message=f"模块 {module} 数据源等级未知",
            module=module,
        )

    # 等级数值：A=0, LOCAL=1, B=2, C=3（数字越小越权威；LOCAL 本地文件优先于 B 级开放 API）
    level_order = {
        DataSourceLevel.A: 0,
        DataSourceLevel.LOCAL: 1,
        DataSourceLevel.B: 2,
        DataSourceLevel.C: 3,
    }
    passed = level_order.get(source_level, 99) <= level_order.get(required, 99)
    return GateResult(
        gate_type=GateType.SOURCE_LEVEL,
        passed=passed,
        severity=GateSeverity.SOFT,
        message=(
            f"数据源等级 {source_level.value}，"
            f"{'达到' if passed else '未达到'}最低要求 {required.value}"
        ),
        module=module,
        details={"actual": source_level.value, "required": required.value},
    )


def check_algorithm_applicability(
    module: str,
    fund_type: str | None,
) -> GateResult:
    """
    门禁3：算法适用性检查。

    检查基金类型是否适用该算法模块（如债券基金不应跑权益风格暴露）。
    """
    exclusions = MODULE_FUND_TYPE_EXCLUSIONS.get(module, set())
    if fund_type and fund_type in exclusions:
        return GateResult(
            gate_type=GateType.ALGORITHM_APPLICABILITY,
            passed=False,
            severity=GateSeverity.HARD,
            message=f"模块 {module} 不适用于基金类型 '{fund_type}'",
            module=module,
            details={"fund_type": fund_type, "excluded_types": list(exclusions)},
        )
    return GateResult(
        gate_type=GateType.ALGORITHM_APPLICABILITY,
        passed=True,
        severity=GateSeverity.HARD,
        message=f"模块 {module} 适用于基金类型 '{fund_type or '未知'}'",
        module=module,
    )


def check_residual_threshold(
    module: str,
    data: dict[str, Any] | None,
) -> GateResult:
    """
    门禁4：残差阈值检查。

    风格暴露 R² 过低、归因残差过大时降级结论。
    """
    if data is None:
        return GateResult(
            gate_type=GateType.RESIDUAL_THRESHOLD,
            passed=True,
            severity=GateSeverity.SOFT,
            message="无数据，跳过残差检查",
            module=module,
        )

    # 风格暴露：检查 R²
    if module == "exposure":
        r_squared = data.get("r_squared")
        min_r2 = MAX_RESIDUAL["exposure_r_squared_min"]
        if r_squared is not None:
            passed = r_squared >= min_r2
            return GateResult(
                gate_type=GateType.RESIDUAL_THRESHOLD,
                passed=passed,
                severity=GateSeverity.SOFT,
                message=(
                    f"风格回归 R²={r_squared:.2f}，"
                    f"{'达到' if passed else '未达到'}最低要求 {min_r2}"
                ),
                module=module,
                details={"r_squared": r_squared, "min_r_squared": min_r2},
            )

    # 静态/动态归因：检查残差占比
    if module in ("attribution", "dynamic_attribution"):
        residual_pct = data.get("residual_pct") or data.get("residual_pct_weight")
        max_res = MAX_RESIDUAL["attribution_residual_max"]
        if residual_pct is not None:
            passed = residual_pct <= max_res
            return GateResult(
                gate_type=GateType.RESIDUAL_THRESHOLD,
                passed=passed,
                severity=GateSeverity.SOFT,
                message=(
                    f"归因残差占比 {residual_pct:.0%}，"
                    f"{'低于' if passed else '超过'}阈值 {max_res:.0%}"
                ),
                module=module,
                details={"residual_pct": residual_pct, "max_residual": max_res},
            )

    return GateResult(
        gate_type=GateType.RESIDUAL_THRESHOLD,
        passed=True,
        severity=GateSeverity.SOFT,
        message="残差检查通过",
        module=module,
    )


def check_evidence_completeness(
    module: str,
    evidence_count: int,
    has_data: bool,
) -> GateResult:
    """
    门禁5：证据完整度检查。

    有数据的模块必须至少有 1 条证据支撑。
    """
    if not has_data:
        return GateResult(
            gate_type=GateType.EVIDENCE_COMPLETENESS,
            passed=True,
            severity=GateSeverity.SOFT,
            message="无数据，跳过证据检查",
            module=module,
        )

    passed = evidence_count >= 1
    severity = GateSeverity.HARD if module in CORE_MODULES else GateSeverity.SOFT
    return GateResult(
        gate_type=GateType.EVIDENCE_COMPLETENESS,
        passed=passed,
        severity=severity,
        message=(
            f"证据条数 {evidence_count}，"
            f"{'满足' if passed else '不满足'}最低要求（≥1）"
        ),
        module=module,
        details={"evidence_count": evidence_count},
    )


# ============================================================
# 综合门禁评估入口
# ============================================================

def evaluate_credibility(
    fund_code: str,
    fund_type: str | None,
    modules: dict[str, dict[str, Any] | None],
    module_source_levels: dict[str, DataSourceLevel | None] | None = None,
    module_meta: dict[str, dict[str, Any] | None] | None = None,
    module_evidence_counts: dict[str, int] | None = None,
) -> CredibilityReport:
    """
    对研究包所有模块执行五道门禁检查，返回可信度报告。

    Args:
        fund_code: 基金代码
        fund_type: 基金类型（如"偏股混合"、"债券型"）
        modules: {module_name: module_data_dict_or_None}
        module_source_levels: {module_name: DataSourceLevel}
        module_meta: {module_name: metadata_dict}（含 coverage_rate 等）
        module_evidence_counts: {module_name: evidence_count}

    Returns:
        CredibilityReport 包含所有门禁结果、模块状态、整体状态、警告
    """
    report = CredibilityReport(fund_code=fund_code)
    module_source_levels = module_source_levels or {}
    module_meta = module_meta or {}
    module_evidence_counts = module_evidence_counts or {}

    for module_name, module_data in modules.items():
        has_data = module_data is not None

        # 门禁1：数据完整性
        g1 = check_data_completeness(
            module_name, module_data, module_meta.get(module_name)
        )
        report.add(g1)

        # 门禁2：数据源等级
        g2 = check_source_level(
            module_name, module_source_levels.get(module_name)
        )
        report.add(g2)

        # 门禁3：算法适用性
        g3 = check_algorithm_applicability(module_name, fund_type)
        report.add(g3)

        # 门禁4：残差阈值
        g4 = check_residual_threshold(module_name, module_data)
        report.add(g4)

        # 门禁5：证据完整度
        g5 = check_evidence_completeness(
            module_name,
            module_evidence_counts.get(module_name, 0),
            has_data,
        )
        report.add(g5)

        # 计算该模块的结论状态
        module_gates = [g1, g2, g3, g4, g5]
        if any(not r.passed and r.severity == GateSeverity.HARD for r in module_gates):
            report.module_statuses[module_name] = ConclusionStatus.NEEDS_REVIEW
        elif any(not r.passed and r.severity == GateSeverity.SOFT for r in module_gates):
            report.module_statuses[module_name] = ConclusionStatus.OBSERVATION
        elif module_name in FACT_MODULES:
            report.module_statuses[module_name] = ConclusionStatus.FACT
        else:
            report.module_statuses[module_name] = ConclusionStatus.COMPUTED

    report.compute_overall()
    return report
