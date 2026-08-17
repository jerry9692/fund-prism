"""P4.2-1 可信度门禁测试 — 基金族归一 + 模块类型排除。"""

import pytest

from fund_research.research.credibility import (
    MODULE_FUND_TYPE_EXCLUSIONS,
    check_algorithm_applicability,
    normalize_fund_family,
)

# ============================================================
# 基金族归一化
# ============================================================


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("债券型", "bond_family"),
        ("债券型-短债", "bond_family"),
        ("债券型-可转债", "bond_family"),
        ("债券型-普通债券", "bond_family"),
        ("货币型", "money_family"),
        ("股票型-标准指数", "index_family"),
        ("股票型-增强指数", "index_family"),
        ("指数型", "index_family"),
        ("股票型", "equity_family"),
        ("股票型-普通", "equity_family"),
        ("混合型-偏股", "mixed_family"),
        ("QDII", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_fund_family(category, expected) -> None:
    assert normalize_fund_family(category) == expected


# ============================================================
# 算法适用性门禁（族匹配 + 精确匹配兼容）
# ============================================================


def test_exposure_excluded_for_bond_fund_composite_category() -> None:
    """东财复合分类（债券型-短债）应经族匹配排除权益风格暴露。"""
    result = check_algorithm_applicability("exposure", "债券型-短债")

    assert result.passed is False
    assert result.details["fund_type"] == "债券型-短债"


def test_exposure_excluded_for_legacy_exact_type() -> None:
    """旧精确类型名（债券型）保持兼容排除。"""
    assert check_algorithm_applicability("exposure", "债券型").passed is False


def test_exposure_applicable_for_equity_fund() -> None:
    assert check_algorithm_applicability("exposure", "混合型-偏股").passed is True


def test_scoring_excluded_only_for_money() -> None:
    assert check_algorithm_applicability("scoring", "货币型").passed is False
    assert check_algorithm_applicability("scoring", "债券型-长期纯债").passed is True


# ============================================================
# Phase 4 模块占位：债基因子仅适用债基，ETF 优选仅适用指数类
# ============================================================


def test_bond_factor_exposure_only_for_bond_funds() -> None:
    assert check_algorithm_applicability("bond_factor_exposure", "债券型-短债").passed is True
    assert check_algorithm_applicability("bond_factor_exposure", "混合型-偏股").passed is False
    assert check_algorithm_applicability("bond_factor_exposure", "股票型-标准指数").passed is False


def test_etf_selection_only_for_index_funds() -> None:
    assert check_algorithm_applicability("etf_selection", "股票型-标准指数").passed is True
    assert check_algorithm_applicability("etf_selection", "股票型-增强指数").passed is True
    assert check_algorithm_applicability("etf_selection", "债券型-可转债").passed is False
    assert check_algorithm_applicability("etf_selection", "混合型-偏股").passed is False


def test_phase4_module_placeholders_registered() -> None:
    assert "bond_factor_exposure" in MODULE_FUND_TYPE_EXCLUSIONS
    assert "etf_selection" in MODULE_FUND_TYPE_EXCLUSIONS


def test_unknown_module_is_applicable() -> None:
    """无排除规则的模块默认适用。"""
    assert check_algorithm_applicability("some_new_module", "债券型").passed is True
