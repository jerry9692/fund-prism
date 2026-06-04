# 第零阶段进度报告 — 2026-06-04

## 摘要

第零阶段和一期开工前置验证已完成。包括：环境搭建、30 只样本基金选择、AKShare 必需接口原始字段盘点、原始字段→标准字段映射表、30 只基金全量 P0 数据拉取入 DuckDB（100% 成功率）、数据质量检查、披露粒度标注（按季度分类）、A 级官方 PDF 证据最小闭环、算法可行性评估、数据源风险登记册、以及审计修复（report_period 日期解析 + 披露粒度标签重分类 + 质量摘要统计修正）。

**结论: 通过。一期可以开工。**

## 1. 环境信息

| 项目 | 版本/值 |
|------|---------|
| Python | 3.12.7 (venv) |
| AKShare | 1.18.64 |
| 数据库 | DuckDB (待使用) |
| 操作系统 | Windows 10/11 x64 |
| 安装命令 | `pip install -e ".[dev]"` (清华源) |

关键依赖均位于 `pyproject.toml` 中。重依赖（akshare、duckdb、scikit-learn 等）已通过清华源成功安装。当前 Python 版本约束为 `>=3.11,<3.13`。

## 2. 已完成的工作

### 2.1 样本基金选择

**文件**: `data/samples/sample_funds_v0.1.csv`

从 AKShare `fund_name_em()` 获取的 26951 只全量基金中，筛选"混合型-偏股""股票型""混合型-灵活""混合型-平衡"四类，得到 9132 只主动权益候选基金。从中手工选取 30 只样本，覆盖以下维度：

- **规模**: 大盘(>100亿) 5 / 中盘(10-100亿) 10 / 小盘(<10亿) 5
- **风格**: 成长 12 / 价值 6 / 均衡 6 / 行业主题 5
- **预期换手**: 高 10 / 低 11 / 中 9（待持仓数据拉取后通过相邻季度持仓变化确认）
- **特殊**: 量化策略 1 只
- **公司覆盖**: 17 家基金公司

样本 CSV 字段：`fund_code, short_name, company, expected_style, expected_turnover, added_reason, confirmed_turnover, confirmed_turnover_source, num_reports_available`

审计修复后，`num_reports_available` 已按 `disclosure_granularity.csv` 回填；`confirmed_turnover` 明确标记为 `pending`，待 `fund_portfolio_change_em` 批量计算后再确认，不把预期换手误当事实。

已验证全部 30 只存在于 AKShare 的 `fund_name_em()` 输出中。

**替补说明**：原始样本中 110011 (易方达优质精选) 在 AKShare 基金列表中不存在（可能因代码变更或更名），已替换为 110009 (易方达价值精选)。

**候选池文件**: `data/samples/active_equity_candidates_v2.csv` (9132 只，用于后续扩大样本或替换)

### 2.2 AKShare 字段盘点

**盘点脚本**: `notebooks/phase0/01_field_inventory.py`

**盘点结果**: `docs/phase0/akshare-field-inventory-p0.json`

当前可审计的原始盘点 JSON 覆盖以下 4 个概念接口；字段映射表和进度记录还包含更多接口，但这些接口需要补充原始调用结果后，才能称为“已文档化跑通”：

#### P0 接口（有原始盘点 JSON）

| 序号 | 概念名 | AKShare 真实函数 | 参数 | 行/列 | 耗时 | 关键发现 |
|------|--------|-----------------|------|-------|------|----------|
| 1 | 基金基本信息 | `fund_individual_basic_info_xq(symbol)` | symbol="000001" | 14×2 | ~4s | **转置表格式** (item/value)，需 pivot；有"最新规模""业绩比较基准" |
| 2 | 基金净值 | `fund_open_fund_info_em(symbol, indicator)` | indicator="单位净值走势" | 5934×3 | ~4s | 列：净值日期/单位净值/日增长率；累计净值需第二次调用 |
| 3 | 前十大持仓 | `fund_portfolio_hold_em(symbol, date)` | date="2024" | 369×7 | ~12s | ⚠️ **仅前十大重仓股**，无行业字段，季度文本格式需解析 |
| 4 | 股票日行情 | `stock_zh_a_hist(symbol, period, start, end, adjust)` | adjust="qfq" | 117×12 | ~3s | 支持前复权，日频可用 |

#### P1 接口（字段映射已记录，需补原始盘点 JSON）

| 序号 | 概念名 | AKShare 真实函数 | 关键发现 |
|------|--------|-----------------|----------|
| 5 | 基金列表 | `fund_name_em()` | 全量基金列表，用于样本选择；需补入 inventory JSON |
| 6 | 行业配置 | `fund_portfolio_industry_allocation_em(symbol, date)` | 已批量拉取 2025 年行业配置；需补入 inventory JSON |
| 7 | 基金经理 | `fund_manager_em()` | 全量经理列表，筛选逻辑需注意逗号分隔代码；需补入 inventory JSON |
| 8 | 持仓变动 | `fund_portfolio_change_em(symbol, date)` | 可用于估算换手率；需补入 inventory JSON |
| 9 | 持有人结构 | `fund_hold_structure_em()` | 半年度频率；需补入 inventory JSON |
| 10 | 指数日行情 | `stock_zh_index_daily_tx(symbol)` | 总结中记录为可用，但风格指数 symbol 仍需逐个确认 |

#### 待测试接口

| 接口 | 问题 |
|------|------|
| 指数日行情 | `index_zh_a_hist` 连接超时。候选替代: `stock_zh_index_daily`, `stock_zh_index_daily_em`, `stock_zh_index_daily_tx` |
| 基金费率 | `fund_fee_em` 返回空 DataFrame，参数签名待确认 |
| 分红拆分 | `fund_fh_em` 未测试，后续用于计算复权净值 |
| 债券持仓 | `fund_portfolio_bond_hold_em` 未测试 |
| 基金公告 | `fund_announcement_report_em` 未测试 |

### 2.3 原始字段到标准字段映射表

**文件**: `config/field_mapping_v0.1.yaml`

这是第零阶段最重要的基础设施交付物。为每个 AKShare 接口定义了：

- `raw_name`: AKShare 返回的原始列名（中文）
- `canonical_name`: 平台内部使用的标准字段名（英文下划线命名）
- `data_type`: 标准数据类型
- `unit`: 数值单位
- `required`: 是否必需字段
- `transform`: 需要的转换逻辑
- `note`: 关键注意事项

已覆盖 9 个数据源的映射，其中部分接口仍标为待验证/待修复：
1. `fund_list` — 基金列表
2. `fund_basic_info` — 基金基本信息
3. `fund_nav` — 基金净值（含 unit_nav 和 accumulated_nav 两个 indicator）
4. `fund_portfolio_hold` — 前十大重仓股
5. `fund_industry_allocation` — 行业配置
6. `fund_manager` — 基金经理
7. `stock_daily` — 股票日行情
8. `fund_portfolio_change` — 持仓变动
9. `fund_holder_structure` — 持有人结构

## 3. 关键发现与风险

### 3.1 数据口径陷阱

| 发现 | 影响 | 应对 |
|------|------|------|
| **日增长率是百分比形式**（如 1.23 表示 +1.23%），非小数 | 直接用于计算会导致收益放大 100 倍 | 入库前统一 `/100` 转为小数。已在 `field_mapping_v0.1.yaml` 中标注 |
| **无复权净值**（只有单位净值和累计净值） | 需要自行计算复权因子 = 累计净值/单位净值，且需要分红数据验证 | 后续通过 `fund_fh_em` 获取分红拆分记录 |
| **仅前十大重仓股**（非全部持仓） | 静态 Brinson 归因只能基于前十大，精度受限 | 在 Research Packet 中标注披露粒度 `top10_only` |
| 基金经理 `现任基金代码` 是逗号分隔字符串（如 "001924,002849"） | 直接 `==` 匹配会漏掉，需用 `str.contains` | 已在映射表中注明 |

### 3.2 缺失的关键数据

| 数据 | 严重程度 | 替代方案 |
|------|----------|----------|
| 基金级历史规模序列 | 中 | `fund_individual_basic_info_xq` 只有最新规模。需另找数据源 |
| 全部持仓（非仅前十大） | 高（对于归因精度） | AKShare 免费层可能无法获取。半年报/年报的完整持仓可能需要 PDF 解析 |
| 基金经理任职起止日期 | 中 | 当前只能通过 `累计从业时间` 和 `现任基金代码` 间接推断 |
| 基金费率详情 | 中 | `fund_fee_em` 待修复 |

### 3.3 数据源风险

| 风险 | 等级 | 说明 |
|------|------|------|
| AKShare 单点依赖 | 高 | 当前结构化批量数据依赖 AKShare → 天天基金(东方财富) 底层。A 级路径仅部分验证，尚未形成可替代的结构化接入 |
| `fund_name_em()` 慢 | 中 | 全量 26951 只需 ~56s，不宜高频调用。需本地缓存 |
| `fund_manager_em()` 慢 | 中 | 全量 34671 人需 ~86s。同样需缓存 |

## 4. 目录结构（新增文件）

```
fund-research/
├── config/
│   └── field_mapping_v0.1.yaml          # [NEW] 原始字段→标准字段映射表
├── data/
│   └── samples/
│       ├── active_equity_candidates_v2.csv  # [NEW] 9132只主动权益候选基金
│       ├── fund_universe_raw.csv            # [NEW] 全量基金列表快照
│       └── sample_funds_v0.1.csv           # [NEW] 30只样本基金
├── docs/
│   └── phase0/
│       ├── akshare-field-inventory-p0.json  # [NEW] P0接口盘点原始数据
│       ├── progress-report-2026-06-04.md    # [NEW] 本文件
│       ├── conclusion.md                     # [NEW] 阶段总结
│       ├── official-source-paths.md          # [NEW] 官方路径验证
│       ├── quality_baseline_summary.json     # [NEW] 质量基线摘要
│       └── phase-0-data-availability.md      # 第零阶段需求文档
└── notebooks/
    └── phase0/
        ├── 00_sample_selection.py           # [NEW] 样本选择脚本
        ├── 01_field_inventory.py            # [NEW] 字段盘点脚本
        ├── 02_full_data_pull.py             # [NEW] 全量拉取脚本
        ├── 03_data_quality_check.py         # [NEW] 数据质量检查脚本
        └── 04_fix_report_period.py          # [NEW] report_period 修复脚本
```

## 5. 如何复现

```bash
# 1. 激活虚拟环境
cd E:\Vibe\fund-research
.venv\Scripts\Activate.ps1

# 2. 验证环境
python --version  # 应为 3.12.7
python -c "import akshare; print(akshare.__version__)"  # 应为 1.18.64

# 3. 查看样本基金
python -c "import pandas as pd; print(pd.read_csv('data/samples/sample_funds_v0.1.csv'))"

# 4. 运行字段盘点（约 2 分钟，包含网络请求）
python notebooks/phase0/01_field_inventory.py

# 5. 查看字段映射表
cat config/field_mapping_v0.1.yaml
```

## 6. 下一步工作

按优先级排列：

| 优先级 | 任务 | 预估耗时 | 产出 |
|--------|------|----------|------|
| P0 | 补齐 AKShare 必需接口原始盘点 JSON | 已完成 | `akshare-field-inventory-p0.json` |
| P0 | 找到可用的风格指数 symbol 并测试 | 已完成 | `pre_phase1_readiness.md` |
| P0 | 完成 1 只样本基金官方 PDF 下载与解析证据 | 已完成 | `pre_phase1_readiness.md` |
| P1 | 测试分红和费率替代路径 | 已完成 | `field_mapping_v0.1.yaml` |
| P1 | 将 `field_mapping_v0.1.yaml` 映射逻辑写入正式数据适配器 | 一期第一个开发任务 | 一期 adapter |

## 7. 协作注意事项

- **字段名规范**: 所有标准字段使用 `field_mapping_v0.1.yaml` 中定义的 `canonical_name`，不要直接使用 AKShare 的中文列名
- **日收益率格式**: 统一使用小数形式（0.01 = 1%），AKShare 返回的百分比需要 `/100`
- **基金代码格式**: 统一使用 6 位字符串，保留前导零
- **数据源等级标注**: 所有从 AKShare 获取的数据标注为 `source_level: B, underlying_source: 天天基金(东方财富)`
- **不要提交批量数据**: AKShare 拉取的原始数据只保留在本地 DuckDB，不提交到 Git
- **限速**: 所有 AKShare 调用间隔 >= 1.5 秒，遵守需求书 0.9 的实验要求

## 8. 审计与修复（2026-06-04 第二轮）

### 8.1 审计发现

| # | 问题 | 严重度 | 状态 |
|---|------|--------|------|
| 1 | `report_period` 为中文文本（如"2024年1季度股票投资明细"），未解析为标准日期 | 中 | ✅ 已修复 |
| 2 | 披露粒度标签基于任意数量阈值（>10/50），命名含糊（"top50_or_partial"） | 低 | ✅ 已修复 |
| 3 | manager、holder_structure、portfolio_change 未批量拉取（P1 数据，一期不需要） | 低 | 📋 二期前补上 |
| 4 | industry 表仅 2025 年数据 | 低 | 📋 一期如需多年数据再补 |
| 5 | 000001 无业绩比较基准（基金特性，非错误） | 信息 | — |
| 6 | 质量摘要把报告期记录数误写为基金数 | 中 | ✅ 已修复 |
| 7 | A 级官方源和 10 个 AKShare 接口存在过度声明 | 中 | ✅ 已补一期开工前置验证 |

### 8.2 修复内容

1. **report_period 日期解析**: DuckDB 现有 26,653 行持仓数据已更新，新增 `report_date` 列（如 `2024-03-31`）。拉取脚本 `02_full_data_pull.py` 增加 `_parse_report_period()` 函数，未来新数据自动解析。迁移脚本 `04_fix_report_period.py` 可供后续使用。

2. **披露粒度标签重分类**: 质量检查脚本 `03_data_quality_check.py` 改为基于报告季度号分类：
   - `top10_quarterly`: Q1/Q3 季度报告（平均 16 只股票）
   - `full_semiannual`: Q2/Q4 半年/年报（平均 131 只股票）
   - `partial_semiannual`: Q2/Q4 但持仓较少（小型/新基金）

### 8.3 审计结论

数据质量主体过关，一期开工前置验证已通过。一期开发可以启动。
