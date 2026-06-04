"""
第零阶段 — 样本基金选择
======================

目标：从中国公募基金中选取 30 只主动权益基金作为样本集，
覆盖规模/风格/换手/行业主题/特殊类型等维度。

环境记录：
- Python: {python_version}
- AKShare: {akshare_version}
- 日期: {date}
"""

import sys
import os
from datetime import date, datetime
from pathlib import Path

# 把项目根目录加入 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd
import akshare as ak

# ============================================================
# 0. 环境记录
# ============================================================
print("=" * 60)
print("第零阶段 — 样本基金选择")
print("=" * 60)
print(f"Python 版本: {sys.version}")
print(f"AKShare 版本: {ak.__version__}")
print(f"执行日期: {date.today()}")
print(f"项目路径: {PROJECT_ROOT}")
print()

# ============================================================
# 1. 获取全市场基金列表
# ============================================================
print("正在从 AKShare 获取全市场基金列表...")

try:
    # AKShare 的开放式基金列表接口
    raw_funds = ak.fund_open_fund_info_em(symbol="全部", indicator="单位净值走势")
    print(f"  [WARN] 接口返回不符合预期格式，尝试其他方式...")
except Exception:
    pass

# 尝试 fund_info_index_em 系列接口
fund_list = None
for func_name in [
    "fund_open_fund_info_em",
    "fund_info_index_em",
    "fund_name_em",
]:
    try:
        f = getattr(ak, func_name, None)
        if f is None:
            continue
        # 尝试不同调用方式
        for args in [(), ("全部",), ("all",)]:
            try:
                result = f(*args)
                if isinstance(result, pd.DataFrame) and len(result) > 100:
                    fund_list = result
                    print(f"  成功: ak.{func_name}{args}")
                    print(f"  返回列: {list(result.columns)}")
                    print(f"  记录数: {len(result)}")
                    break
            except Exception:
                continue
        if fund_list is not None:
            break
    except Exception as e:
        print(f"  ak.{func_name}: {e}")
        continue

if fund_list is None:
    print("[ERROR] 无法获取基金列表，请检查 AKShare 版本和网络。")
    print("AKShare 接口可能已变更，请查阅最新文档: https://akshare.akfamily.xyz/")
    sys.exit(1)

print(f"\n获取到基金列表: {len(fund_list)} 条记录")
print(f"列名: {list(fund_list.columns)}")
print(f"\n前 5 行预览:")
print(fund_list.head().to_string())
print()

# ============================================================
# 2. 筛选主动权益基金
# ============================================================
# 识别可能的基金代码列和名称列
code_col = None
name_col = None
type_col = None

for col in fund_list.columns:
    col_lower = str(col).lower()
    if "代码" in col or "code" in col or col_lower == "symbol":
        code_col = col
    if "名称" in col or "name" in col:
        name_col = col
    if "类型" in col or "type" in col or "分类" in col:
        type_col = col

print(f"识别到的列: code_col={code_col}, name_col={name_col}, type_col={type_col}")

# 保存原始数据，以便后续分析
fund_list.to_csv(PROJECT_ROOT / "data" / "samples" / "fund_universe_raw.csv", index=False)
print("全市场基金列表已保存到 data/samples/fund_universe_raw.csv")
print()

# ============================================================
# 3. 手工精选 30 只样本基金（待填写）
# ============================================================
# 按照需求文档 0.4.1 的维度要求，手动选择基金。
# 等上面确认了实际可用的列名后再填入。

print("=" * 60)
print("下一步：根据实际返回的字段结构，手动筛选 30 只样本基金")
print("筛选维度：大盘5 / 中盘10 / 小盘5 / 成长5 / 价值5 / 均衡5")
print("          预期高换手5 / 预期低换手5 / 行业主题5 / 灵活配置5")
print("          + 2只已清盘/转类型")
print("=" * 60)
