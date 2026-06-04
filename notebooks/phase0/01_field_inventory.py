"""
第零阶段 — AKShare 字段盘点 (P0 接口)
=======================================

逐个测试 AKShare 真实函数，记录：
- 真实函数名、参数、返回字段（原始列名）
- 字段类型、示例值、缺失率
- 底层数据来源
- 原始字段到标准字段的映射

测试基金: 000001 华夏成长混合（代码最靠前的主动权益基金）
"""

import sys
from pathlib import Path
from datetime import date, datetime
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd
import akshare as ak
import time

AKSHARE_VERSION = ak.__version__
TEST_FUND = "000001"
TODAY = date.today().isoformat()

print(f"AKShare 版本: {AKSHARE_VERSION}")
print(f"测试基金: {TEST_FUND}")
print(f"执行日期: {TODAY}")
print("=" * 70)

# 汇总结果
inventory = {
    "metadata": {
        "akshare_version": AKSHARE_VERSION,
        "test_date": TODAY,
        "test_fund": TEST_FUND,
    },
    "interfaces": [],
}


def record(name, func_name, params, result_df, elapsed, errors, underlying_source, source_level):
    """记录一个接口的盘点结果。"""
    record = {
        "concept_name": name,
        "akshare_function": func_name,
        "params": params,
        "elapsed_seconds": round(elapsed, 2),
        "underlying_source": underlying_source,
        "source_level": source_level,
        "errors": errors,
    }

    if isinstance(result_df, pd.DataFrame) and len(result_df) > 0:
        record["row_count"] = len(result_df)
        record["raw_columns"] = list(result_df.columns)
        record["column_count"] = len(result_df.columns)

        # 对每个列记录：类型、前3个非空示例值、缺失率
        cols_info = []
        for col in result_df.columns:
            non_null = result_df[col].dropna()
            missing_rate = round(1 - len(non_null) / len(result_df), 4)
            dtype = str(result_df[col].dtype)
            examples = non_null.head(3).tolist()
            cols_info.append({
                "raw_name": col,
                "dtype": dtype,
                "missing_rate": missing_rate,
                "examples": examples,
            })
        record["columns_detail"] = cols_info

        # 显示摘要
        print(f"  rows={record['row_count']} | cols={record['column_count']}")
        print(f"  列: {', '.join(record['raw_columns'][:8])}")
        if len(record['raw_columns']) > 8:
            print(f"      ... 共 {len(record['raw_columns'])} 列")
        print(f"  耗时: {elapsed:.1f}s | 底层来源: {underlying_source}")
    else:
        record["row_count"] = 0
        print(f"  返回: 空或非DataFrame")

    if errors:
        print(f"  问题: {'; '.join(errors)}")

    print()
    inventory["interfaces"].append(record)
    return record


# ============================================================
# P0-1: 基金基本信息 — fund_individual_basic_info_xq
# ============================================================
print("[P0-1] 基金基本信息")
t0 = time.time()
errors = []
try:
    df = ak.fund_individual_basic_info_xq(TEST_FUND)
except Exception as e:
    df = pd.DataFrame()
    errors.append(str(e)[:200])

record("fund_basic_info", "fund_individual_basic_info_xq",
       {"symbol": TEST_FUND}, df, time.time() - t0, errors,
       "天天基金(东方财富)", "B")

# fund_individual_basic_info_xq 返回的是转置表 (item/value), 需要 pivot
# 额外打印实际内容以便理解
if isinstance(df, pd.DataFrame) and len(df) > 0:
    print(f"  原始格式: {df.shape[0]} 行 x {df.shape[1]} 列")
    print(f"  内容预览:")
    for _, row in df.head(14).iterrows():
        print(f"    {row.iloc[0]}: {row.iloc[1]}")

time.sleep(1.5)

# ============================================================
# P0-2: 基金净值 — fund_open_fund_info_em
# ============================================================
print("\n[P0-2] 基金净值")
t0 = time.time()
errors = []
try:
    df_nav = ak.fund_open_fund_info_em(TEST_FUND, "单位净值走势")
except Exception as e:
    df_nav = pd.DataFrame()
    errors.append(str(e)[:200])

record("fund_nav", "fund_open_fund_info_em",
       {"symbol": TEST_FUND, "indicator": "单位净值走势"},
       df_nav, time.time() - t0, errors,
       "天天基金(东方财富)", "B")

# 额外质量检查
if isinstance(df_nav, pd.DataFrame) and len(df_nav) > 0:
    # 日期范围
    if '净值日期' in df_nav.columns:
        dates = pd.to_datetime(df_nav['净值日期'])
        print(f"  日期范围: {dates.min().date()} ~ {dates.max().date()}")
        print(f"  交易天数: {len(dates)}")
    # 缺失检查
    nulls = df_nav.isnull().sum()
    if nulls.sum() > 0:
        print(f"  缺失值: {nulls[nulls > 0].to_dict()}")

time.sleep(1.5)

# ============================================================
# P0-3: 基金持仓 — fund_portfolio_hold_em
# ============================================================
print("\n[P0-3] 基金持仓")

# 先测试函数签名
for test_params in [
    {"symbol": TEST_FUND, "date": "2024"},
    {"symbol": TEST_FUND, "date": "2025"},
    {"symbol": TEST_FUND},
]:
    t0 = time.time()
    errors = []
    try:
        df_hold = ak.fund_portfolio_hold_em(**test_params)
    except Exception as e:
        df_hold = pd.DataFrame()
        errors.append(str(e)[:200])
        continue  # try next params

    if isinstance(df_hold, pd.DataFrame) and len(df_hold) > 0:
        record("fund_portfolio_hold", "fund_portfolio_hold_em",
               test_params, df_hold, time.time() - t0, errors,
               "天天基金(东方财富)", "B")
        # 展示持仓内容
        print(f"  示例持仓:")
        for _, row in df_hold.head(5).iterrows():
            print(f"    {row.to_dict()}")
        break
else:
    print("  所有参数组合均失败")
    record("fund_portfolio_hold", "fund_portfolio_hold_em",
           {}, pd.DataFrame(), 0, ["所有参数组合均失败"],
           "天天基金(东方财富)", "B")

time.sleep(1.5)

# ============================================================
# P0-4: 股票日行情 — stock_daily
# ============================================================
print("\n[P0-4] 股票日行情")
# 用一只常见的股票测试 (如 600519 贵州茅台)
TEST_STOCK = "600519"
t0 = time.time()
errors = []

# 查找股票行情函数
stock_func_name = None
for candidate in ["stock_zh_a_hist", "stock_daily_em", "stock_zh_a_daily"]:
    if hasattr(ak, candidate):
        stock_func_name = candidate
        break

if stock_func_name:
    try:
        df_stock = getattr(ak, stock_func_name)(
            symbol=TEST_STOCK,
            period="daily",
            start_date="20240101",
            end_date="20240630",
            adjust="qfq"  # 前复权
        )
    except Exception as e:
        # 尝试不同的参数
        try:
            df_stock = getattr(ak, stock_func_name)(TEST_STOCK)
        except Exception as e2:
            df_stock = pd.DataFrame()
            errors.append(f"{stock_func_name}: {e}; {e2}")
else:
    df_stock = pd.DataFrame()
    errors.append("未找到股票日行情函数")

record("stock_daily", stock_func_name or "NOT_FOUND",
       {"symbol": TEST_STOCK, "period": "daily", "adjust": "qfq"},
       df_stock, time.time() - t0, errors,
       "东方财富/新浪", "B")

time.sleep(1.5)

# ============================================================
# 保存盘点结果
# ============================================================
output_path = PROJECT_ROOT / "docs" / "phase0" / "akshare-field-inventory-p0.json"
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(inventory, f, ensure_ascii=False, indent=2, default=str)

print("=" * 70)
print(f"盘点结果已保存: {output_path}")
print(f"共测试 {len(inventory['interfaces'])} 个接口")
