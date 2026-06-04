# 第零阶段总结报告

## 阶段结论

> **通过。一期开工前置验证已完成，可以进入一期 MVP 开发。**

在免费公开数据约束下，主动权益基金研究的四个核心模块（收益风险指标、公开持仓分析、风格/行业暴露、静态归因）所需数据均已形成可复验路径。主要限制仍在于持仓粒度（季度仅前十大），但风格指数、分红、费率替代路径、公告列表和 A 级官方 PDF 证据最小闭环已经通过一期开工前置验证。

**审计修复**（2026-06-04）：
- `report_period` 中文文本已解析为标准日期（`report_date` 列）
- 披露粒度标签已从任意数量阈值改为基于季度号分类
- 质量摘要中的“基金数/报告期数”统计已修正
- A 级官方源口径已降级为“部分验证”，不得默认作为已接入结构化主源
- 一期开工前置验证已完成（见 `docs/phase0/pre_phase1_readiness.md`）：AKShare 必需接口 17/17 成功，风格指数 5/5 解析，分红/费率替代路径可用，巨潮 PDF 下载解析通过

---

## 1. 执行摘要

| 维度 | 结果 |
|------|------|
| 样本基金 | 30 只主动权益基金（覆盖 17 家公司、成长/价值/均衡/行业主题/量化等风格） |
| 数据拉取成功率 | **100%**（30/30 × 4 类数据 = 120/120 次成功） |
| AKShare 接口验证 | 一期开工必需接口 17/17 通过，原始盘点见 `akshare-field-inventory-p0.json` |
| A 级数据源验证 | **最小闭环通过**：巨潮官方 PDF 下载、hash、页数和文本关键词解析已记录 |
| 一期算法可行性 | 4/4 达到"可做"或"降级可做" |
| 诚实判断 | 季度全部持仓不可得、复权净值需自行推算 |

## 2. 交付物索引

| 编号 | 交付物 | 路径 | 状态 |
|------|--------|------|------|
| DEL-0 | 样本基金列表 v0.1 | `data/samples/sample_funds_v0.1.csv` | ✅ |
| DEL-1 | 原始字段→标准字段映射 v0.1 | `config/field_mapping_v0.1.yaml` | ✅ |
| DEL-2 | AKShare 字段盘点报告 | `docs/phase0/akshare-field-inventory-p0.json` | ✅ |
| DEL-3 | A 级官方披露路径验证 | `docs/phase0/official-source-paths.md` + `docs/phase0/pre_phase1_readiness.md` | ✅ 最小闭环通过 |
| DEL-4 | 持仓披露粒度报告（按季度分类） | `docs/phase0/disclosure_granularity.csv` | ✅ 已修复 |
| DEL-5 | 字段覆盖率矩阵 | 见质量基线报告 | ✅ |
| DEL-6 | 数据源风险登记册 | `docs/phase0/source-risk-register.md` | ✅ |
| DEL-7 | 算法可行性评估表 | `docs/phase0/algorithm-feasibility.md` | ✅ |
| DEL-8 | 数据质量基线报告 | `docs/phase0/quality_baseline_summary.json` | ✅ |
| DEL-9 | 首版核心 Schema | `src/fund_research/core/schemas.py` | ✅（框架阶段已定义） |
| DEL-10 | 指标注册表模板 | `config/metrics_registry_template.yaml` | ✅ |
| DEL-11 | 实验脚本 | `notebooks/phase0/`（5 个脚本） | ✅ |
| DEL-12 | 阶段总结 | 本文档 | ✅ |

## 3. 关键技术发现

### 3.1 数据口径陷阱

| 发现 | 影响 | 已记录在 |
|------|------|----------|
| 日增长率是百分比形式（1.23 = 1.23%），非小数 | 直接计算会导致收益放大 100 倍 | `field_mapping_v0.1.yaml` |
| 无复权净值，仅单位净值 + 累计净值 | 需要自行计算复权因子 | `field_mapping_v0.1.yaml` |
| 季度持仓仅前十大重仓股 | 静态归因精度受限 | `algorithm-feasibility.md` |
| 基金经理 current_fund_codes 是逗号分隔字符串 | 筛选逻辑需用 contains 而非 == | `field_mapping_v0.1.yaml` |

### 3.2 AKShare 接口图谱

| 真实函数 | 参数 | 返回 | 底层来源 |
|----------|------|------|----------|
| `fund_name_em()` | 无 | 26951 只基金列表 | 天天基金 |
| `fund_individual_basic_info_xq(code)` | code="000001" | 14 字段转置表 | 天天基金 |
| `fund_open_fund_info_em(code, indicator)` | indicator="单位净值走势" / "累计净值走势" | 净值序列 | 天天基金 |
| `fund_portfolio_hold_em(symbol, date)` | date="2024" | 前十大持仓（跨多季度） | 天天基金 |
| `fund_portfolio_industry_allocation_em(symbol, date)` | date="2025" | 行业配置 | 天天基金 |
| `fund_portfolio_change_em(symbol, date)` | date="2025" | 累计买卖金额（换手率估算） | 天天基金 |
| `fund_manager_em()` | 无 | 34671 人全量 | 天天基金 |
| `fund_hold_structure_em()` | 无 | 持有人结构（半年度） | 天天基金 |
| `stock_zh_a_hist(symbol, period, start, end, adjust)` | adjust="qfq" | 日行情 12 列 | 东方财富 |
| `stock_zh_index_daily_tx(symbol)` | symbol="sh000300" | 指数日行情 | 腾讯 |

### 3.3 A 级数据源验证结果

**证监会 XBRL 专区** (`eid.csrc.gov.cn`):
- ⚠️ 官方披露路径存在，平台级入口可达性已确认
- ⚠️ 样本级 XBRL 文件下载、结构化解析和覆盖率尚未形成可审计产物
- ⚠️ 覆盖率不全（部分老基金如 000001、个別基金如 005827 无报告）
- 📋 一期不接入自动化前，不得作为默认 A 级结构化主源；仅作为备用路径和后续接入方向

**XBRL 解析方案**: Arelle（`pip install arelle-release`）作为标准 XBRL 解析引擎，无需自研；但仍需用一只样本基金完成下载和解析验证。

## 4. 退出标准检查

| 退出标准 | 状态 |
|----------|------|
| 1. 核心数据拉取成功率 >= 90% | ✅ 100% |
| 2. 失败样本已记录原因和替代路径 | ✅ 无失败样本 |
| 3. 净值/持仓/公告至少各存在一条 A 级或 B 级路径 | ✅ AKShare(B) 已验证；巨潮 PDF(A) 最小证据闭环已验证 |
| 4. 原始字段→标准字段映射表已产出 | ✅ `field_mapping_v0.1.yaml` |
| 5. 持仓披露粒度已标注 | ✅ `disclosure_granularity.csv` |
| 6. 一期算法全部评定为可做/降级可做 | ✅ 4/4 |
| 7. 首版核心 Schema 已定义 | ✅ |
| 8. 质量基线报告已输出 | ✅ 已修正基金数/报告期数统计 |
| 9. 至少有一个诚实判断 | ✅ 季度全部持仓不可得、复权净值需自行推算 |
| 10. 数据源风险登记册已产出 | ✅ |

## 5. 后续建议

### 一期开发可直接启动

以下模块的数据基础已验证：

- `get_fund_profile` — 基金基本信息
- `get_nav_metrics` — 净值指标
- `get_disclosed_holdings` — 公开持仓
- `run_exposure_analysis` — 风格/行业暴露 + 静态归因
- `build_research_packet` — 研究包

### 一期开发前收尾状态

| 任务 | 优先级 |
|------|--------|
| 确认风格指数 symbol（大盘/中盘/小盘、成长/价值） | ✅ `sh000300` / `sh000905` / `sh000852` / `sz399370` / `sz399371` |
| 补齐 AKShare 接口原始盘点 JSON | ✅ 必需接口 17/17 成功 |
| 完成 1 只样本基金官方 PDF 下载与解析证据 | ✅ 巨潮 PDF 下载、SHA256、页数和关键词解析已记录 |
| 测试 `fund_fh_em`（分红拆分，用于复权净值计算） | ✅ 可用 |
| 测试费率数据路径 | ✅ `fund_individual_detail_info_xq` 可用；`fund_fee_em` 不作为主源 |
| 将 `field_mapping_v0.1.yaml` 映射逻辑写入数据适配器代码 | 一期第一个开发任务 |

### 中期建议

| 任务 | 时机 |
|------|------|
| XBRL 专区 Arelle 解析验证（下载一份 XBRL 文件用 Arelle 解析） | 二期 |
| 东方财富指数源备用方案验证 | 一期 |
| 接口监控脚本（检查 AKShare 关键接口可用性） | 二期 |

---

## 6. 数据资产清单

| 资产 | 位置 | 大小 |
|------|------|------|
| DuckDB 数据库 | `data/fund_research_phase0.duckdb` | ~50MB（估算） |
| 全量基金列表缓存 | `data/samples/active_equity_candidates_v2.csv` | 9132 行 |
| 样本基金列表 | `data/samples/sample_funds_v0.1.csv` | 30 行 |
| 拉取日志 | `data/fetch_log`（DuckDB 表） | 120 条 |

---

*报告生成日期: 2026-06-04*
*AKShare 版本: 1.18.64*
*样本: 30 只主动权益基金, 100% 拉取成功*
