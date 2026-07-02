"""Unit tests for AKShare adapter field mapping — no network calls."""

import types

import pandas as pd
import pytest

from fund_research.data.adapters.akshare import AkshareAdapter, _manager_id_from_identity


def test_standardize_renames_chinese_columns_to_canonical() -> None:
    """_standardize 应将中文列名通过 COLUMN_MAP 映射为规范英文列名。"""
    fake_ak = types.SimpleNamespace()
    adapter = AkshareAdapter(ak_module=fake_ak)

    raw = pd.DataFrame([
        {"净值日期": "2024-01-02", "单位净值": "1.5000", "累计净值": "1.8000", "日增长率": "0.5"},
        {"净值日期": "2024-01-03", "单位净值": "1.5100", "累计净值": "1.8100", "日增长率": "0.67"},
    ])
    result = adapter._standardize(raw)

    assert "trade_date" in result.columns
    assert "unit_nav" in result.columns
    assert "accumulated_nav" in result.columns
    assert "daily_return" in result.columns
    assert "净值日期" not in result.columns
    assert "单位净值" not in result.columns


def test_standardize_daily_return_divides_by_100_when_above_1() -> None:
    """日增长率原始值为大于 1 的百分比时，_standardize 应除以 100 转为小数。"""
    fake_ak = types.SimpleNamespace()
    adapter = AkshareAdapter(ak_module=fake_ak)

    raw = pd.DataFrame([
        {"日增长率": "2.5", "净值日期": "2024-01-02"},
    ])
    result = adapter._standardize(raw)

    assert result["daily_return"].iloc[0] == pytest.approx(0.025)


def test_standardize_daily_return_keeps_as_is_when_at_or_below_1() -> None:
    """日增长率原始值已为小数（≤ 1）时，_standardize 应保持原值不变。"""
    fake_ak = types.SimpleNamespace()
    adapter = AkshareAdapter(ak_module=fake_ak)

    raw = pd.DataFrame([
        {"日增长率": "0.5", "净值日期": "2024-01-02"},
        {"日增长率": "0.00", "净值日期": "2024-01-03"},
        {"日增长率": "-0.3", "净值日期": "2024-01-04"},
    ])
    result = adapter._standardize(raw)

    assert result["daily_return"].iloc[0] == pytest.approx(0.5)
    assert result["daily_return"].iloc[1] == pytest.approx(0.0)
    assert result["daily_return"].iloc[2] == pytest.approx(-0.3)


def test_manager_id_from_identity_returns_consistent_hash() -> None:
    """相同姓名+公司应产生相同的 manager_id。"""
    id1 = _manager_id_from_identity("张三", "易方达基金")
    id2 = _manager_id_from_identity("张三", "易方达基金")
    assert id1 == id2


def test_manager_id_from_identity_differs_for_different_name() -> None:
    """不同姓名应产生不同的 manager_id。"""
    id1 = _manager_id_from_identity("张三", "易方达基金")
    id2 = _manager_id_from_identity("李四", "易方达基金")
    assert id1 != id2


def test_manager_id_from_identity_differs_for_different_company() -> None:
    """相同姓名但不同公司应产生不同的 manager_id。"""
    id1 = _manager_id_from_identity("张三", "易方达基金")
    id2 = _manager_id_from_identity("张三", "华夏基金")
    assert id1 != id2


def test_manager_id_from_identity_without_company() -> None:
    """不传 company_name 时也应生成合法的 manager_id。"""
    mid = _manager_id_from_identity("王五")
    assert isinstance(mid, str)
    assert mid.startswith("ak_mgr_")
    assert len(mid) > 10
