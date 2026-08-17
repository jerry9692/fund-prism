# Pre-Phase 4 补充开发计划

> 对照 [v0.4 需求书](../AI-oriented开源个人基金研究平台需求书_v0.4.md) §12.4 四期范围，结合 [与「小基啄米」对比报告](./comparison_with_xiaoji_legacy.md) 与 Phase 1–3 现状，梳理 Phase 4（ETF/指数、组合、更多资产类型）开工前必须完成的前置工作。
> 目标：把 Phase 4 新功能（指数基金优选、ETF 组合构建、债基因子暴露、基金公司画像频谱）所需的**数据底座、算法欠账、口径架构**补齐，避免"算法建在不稳定输入上"（需求书 §12.0 的核心教训）。

---

## 0. 总览

### 0.1 当前状态速览

| 板块            | 状态              | 关键缺口（相对 Phase 4 目标）                                         |
| --------------- | ----------------- | --------------------------------------------------------------------- |
| Phase 1 (§12.1) | ✅ 完成            | 基础指标不全：胜率/月度正收益比例/回撤修复天数/同类排名 未实现        |
| Phase 2 (§12.2) | ✅ 完成            | 收益拆解"打新/转债"写死为 0.0 占位（§6.2.3 本体维度欠账）             |
| Phase 3 (§12.3) | ✅ 完成            | 无（发现能力已落地）                                                  |
| 数据底座        | ⚠️ 主动权益完整    | 无债券/ETF/行业指数/可转债数据，样本仅 30 只主动权益                  |
| 算法模板        | ⚠️ 主动权益 + 指数 | `fingerprint.py` 仅 `active_equity`/`index_fund` 两套模板，无债基模板 |
| 指标注册表      | ⚠️ 稀疏            | 仅 8 个基础指标，无债基/ETF 指标定义                                  |

### 0.2 本计划范围

```
[P4.0] 欠账补强 (Phase 1-3 遗留)  ──┐
                                      ├── 并行 ──┐
[P4.1] 数据准备 (Phase 4 硬前置)  ────┘          │
                                                ├──→ [Phase 4]
[P4.2] 架构与口径准备               ────────────┘
```

### 0.3 优先级原则

1. **欠账先于新功能**：收益拆解"打新/转债"是 §6.2.3 明确要求的本体维度，非四期新功能，优先级最高。
2. **数据先于算法**：债基因子、ETF 优选、组合构建都依赖尚未接入的债券/指数/ETF 数据，没有数据算法无从验证。
3. **样本先于模板**：不同基金类型需不同模型模板（需求书 §17"不同基金类型混用模型"），样本不扩充，模板无从验证。
4. **口径可追溯**：行业分类、债券评级、指数成分必须版本化（需求书 §5.3.3），避免重蹈"代理基准"覆辙。

---

## 1. 欠账补强（P4.0）

### P4.0-1 收益拆解补"打新/转债" ★P0 阻塞

**需求来源**：v0.4 §6.2.3 收益拆解明确列 7 项拆解维度（beta / 配置 / 板块轮动 / 选股 / **转债收益 / 打新收益 / 隐形收益**）。

**现状**：[dynamic_attribution.py](../src/fund_research/analysis/dynamic_attribution.py) 已实现 Brinson(BHB/BF)+Carino 多期归因，覆盖 beta/配置/选股/轮动四项，但 `total_ipo_return`、`total_convertible_bond_return` 在 `run_attribution` 中写死为 `0.0`（`dynamic_attribution.py:505-509`），`invisible_return = residual`。即**转债、打新两项收益完全未拆**，混入残差。

**实现计划**（分两档，按数据可得性）：

1. **转债收益（可做，优先）**：

   - 输入：披露转债持仓（`fund_disclosed_holdings` 已含 `asset_type='可转债'` 及 `bond_duration`/`bond_yield` 字段）+ 可转债日行情（需新增，见 P4.1-3）。
   - 方法：与股票静态归因同构 —— `转债收益 = Σ(转债持仓权重 × 转债区间收益)`，作为独立拆解项，从残差中剥离。
   - 输出：`estimated_convertible_bond_return` 从占位 0.0 变为真实计算值。

2. **打新收益（难，先标 estimated + 显式不可观测）**：

   - 现实约束：单基金网下打新中签记录非免费公开数据，无法逐笔还原。
   - 一期方案：保留 `estimated_ipo_return` 占位，但在输出中显式标注"打新收益不可直接观测，包含于隐形收益"，并在残差分析中单列"疑似打新/未披露持仓贡献"说明（满足 §6.2.3"隐形收益需单独标记"）。
   - 备选增强（可延后）：用"新股上市首日涨幅 × 全市场平均中签率 × 基金规模"做粗粒度估算，明确标记 `estimated` 且不进入默认结论。

**验收标准**（§6.2.3）：

- 转债收益从残差中剥离后，各拆解项合计与实际收益误差可控（残差占比门禁 ≤50% 不因剥离而恶化）。
- 打新/隐形收益显式展示，不强行归因。

### P4.0-2 §6.1.4 基础指标补全 ★低成本高价值

**需求来源**：v0.4 §6.1.4 第 2、5 点（一期就该有）。

**现状**：[nav_metrics.py](../src/fund_research/analysis/nav_metrics.py) 只有 total/annualized return、vol、MDD、Sharpe/Calmar/Sortino/IR/beta/alpha，缺：

| 指标                   | 需求书出处 | 实现位置                                                   |
| ---------------------- | ---------- | ---------------------------------------------------------- |
| 胜率（月度正收益比例） | §6.1.4.5   | nav_metrics 新增                                           |
| 回撤修复天数           | §6.1.4.5   | nav_metrics 新增                                           |
| 同类排名 k/N、分位数   | §6.1.4.2   | 新增 `rank_in_category` 工具（参考老系统 `GetRankInType`） |

**实现计划**：

1. `nav_metrics.py` 增加 `win_rate`（月度正收益月份占比）、`recovery_days`（最大回撤修复天数）两个字段。
2. 新增 `analysis/rank.py`：按 `sub_category` 分组对指定指标（区间收益/回撤/夏普）做 `k/N` 排名 + 分位数，供筛选/对比页与 scoring 复用。
3. 指标注册表同步补充（见 P4.2-2）。

**验收标准**：与老系统 `GetRankInType` 口径可比（`k/N` 文本 + 分位数），单测覆盖边界（组内仅 1 只、并列值）。

### P4.0-3 无风险利率接真实货基指数（可选）

**需求来源**：§6.1.4 夏普口径；老系统 §5.5 用"货币基金指数"作 Rf。

**现状**：已修复硬编码，`risk_free_rate` 统一读 `settings.risk_free_rate=0.02` 常数（`nav_metrics.py` / `scoring_dimensions.py`）。

**实现计划**（可选，不阻塞 Phase 4）：

- 引入货币基金指数（如 H11025.CSI 或全市场货基 7 日年化均值）日序列，Sharpe/Sortino 的 `risk_free_rate` 由常数切换为可配置的时序 Rf。
- 不接也可：0.02 常数对主动权益 Sharpe 影响有限，可作为 Phase 4 中后期优化。

### P4.0-4 其他已知欠账（不阻塞 Phase 4，仅登记）

| 项                    | 需求书出处  | 说明                                                                   |
| --------------------- | ----------- | ---------------------------------------------------------------------- |
| 交易能力三种假设      | §6.2.4 验收 | 当前 `trading_ability.py` 仅单情景买卖择时，缺保守/中性/乐观三假设区间 |
| 组合穿透/持仓重叠分析 | §12.4.2     | `compare_fund_fingerprints` 只做指纹相似度，缺底层持仓重叠穿透         |

---

## 2. 数据准备（P4.1，Phase 4 硬前置）

### P4.1-1 样本基金扩充 ★阻塞

**需求来源**：§12.0（20–50 只样本覆盖多类型）、§6.2.7/§6.2.8（债基/ETF 需不同模板）。

**现状**：`data/samples/sample_funds_v0.1.csv` 仅 30 只主动权益/混合基金，无 ETF/联接/指增、无债基。

**实现计划**：

1. 扩充样本至约 50 只，分四组：
   - 主动权益（保留现有 30 只）
   - 指数/ETF：ETF、ETF 联接、指数增强、普通指数各 3–5 只
   - 债券基金：短债、纯债、一级债基、二级债基、可转债基金各 2–3 只
   - 混合/FOF（可选）
2. 每类样本标注 `expected_style` 或 `expected_bond_profile`，用于模板验收对照（延续现有 CSV 字段风格）。
3. 样本扩充走 `fund-research update sample-funds` 现有链路，仅改 CSV + 确认 `fund_info` 抓取覆盖新类型。

**验收标准**：新样本的 `fund_info`/`fund_nav`/`fund_holdings` 抓取成功率对齐现有基线（≥90%），且各类型至少覆盖 2 个代表基金。

### P4.1-2 指数数据域 ★阻塞 ETF 组合构建 + 指数基金优选 ✅ 已完成（2026-08-14）

**需求来源**：§5.1 指数数据、§15.2 扩展表（指数主表/指数行情表/指数成分表）、§6.2.9 ETF 组合构建输入。

**现状**：仅 `benchmark_index_member`（沪深300/500/1000 三家成分）+ `fetch_index_daily`（风格指数 300/905/852/399370/399371）。缺**申万/中信行业指数、主题指数**的行情与成分权重。

**实现计划**（新增表 + 适配器）：

1. **ORM 表**（`models_phase4.py`，对应需求书 §15.2）：

   - `index_main`：指数代码、名称、类型（宽基/行业/主题/风格）、分类体系（申万/中信/中证）、版本
   - `index_daily`：指数代码、日期、收盘、日收益
   - `index_constituent`：指数代码、生效日、成分股代码、权重

2. **适配器**（`akshare.py` 扩展）：

   - 行业指数行情：申万一级/二级、中信一级（AKShare 指数行情接口）
   - 行业指数成分权重：申万行业成分（`fetch_sw_industry_membership` 已具备，复用扩展）
   - 主题指数成分：按需（白酒/新能源等代表性主题）

3. **CLI**：`fund-research update index-daily --index-symbol 801010.SI`（行业指数）、`update benchmark-members` 扩展到行业指数。

**验收标准**：至少覆盖 20 个申万一级行业 + 中信一级行业的行情与成分权重，供 ETF 组合构建做行业映射（替代老系统 §5.4.2 依赖的 `MARKETINDICECONSTITUENTSTOCK`）。

**落地说明**（2026-08-14 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260814_0001`）：`index_main`（指数代码/名称/类型/分类体系/版本/层级，口径版本化对齐 §5.3.3）、`index_daily`（OHLCV + 日收益，`(index_code, trade_date)` 唯一）、`index_constituent`（`(index_code, effective_date, stock_code)` 唯一，含权重%）。均已注册进 `Base.metadata` 并随 Alembic 迁移建表。
2. **适配器**（`data/adapters/akshare.py`）：
   - `fetch_sw_index_list(level=1/2)` — 申万一/二级行业列表 → `index_main`（含 PE/PB/股息率估值快照进 `extra`）
   - `fetch_sw_index_daily(symbol, start, end)` — 申万指数日行情（`index_hist_sw`，本地日期窗口过滤 + `daily_return` 计算）
   - `fetch_sw_index_constituents(symbol)` — 申万成分权重（`index_component_sw`，含计入日期）
   - 申万代码识别/归一化工具：`is_sw_index_symbol` / `normalize_sw_index_code` / `canonical_sw_index_code`
3. **update 工作流**（`data/update.py`）：`upsert_akshare_index_main` / `upsert_akshare_industry_index_daily`（写行情时自动补录 `index_main` 骨架）/ `upsert_akshare_index_constituents` / `resolve_sw_industry_index_symbols`。
4. **CLI**：
   - `fund-research update index-daily --index-symbol 801010.SI` — 申万代码自动路由到指数数据域新表（中证代码仍走原 `stock_daily` 链路，Phase 1-3 行为不变）
   - `fund-research update benchmark-members --index-symbol 801010.SI` — 申万成分权重写入 `index_constituent`（中证代码仍走 `benchmark_index_member`）
   - `fund-research update industry-index [--sw-level 1|2]` — 申万行业指数数据域一键批量更新（主表 + 全部行情 + 全部成分权重），`--domains sw-index` 别名可用
5. **中信一级的现实约束**：中信一级行情/成分在 AKShare 及免费源（新浪/腾讯）均不可得（属 Wind/Choice 订阅数据）。`index_main.classification_system` 已预留 `CITIC` 枚举，待后续接入合规数据源后即可落库；不硬造数据（数据源诚实原则）。
6. **冒烟验证**：801010.SI（农林牧渔）行情 632 行（2024-01 至今）、成分 104 只、权重合计 ≈100%；31 个申万一级行业批量链路可用（>20 满足验收）。单测覆盖适配器标准化/upsert 幂等/路由/表约束（`tests/test_data/test_update_index_domain.py` 等，24 用例）。

### P4.1-3 债券数据域 ★阻塞债基因子暴露 + 转债收益 ✅ 已完成（2026-08-14）

**需求来源**：§5.1 债券数据（债券估值/可转债行情/收益率曲线）、§15.2（债券主表/债券估值表）、§6.2.7 债基因子输入。

**现状**：`fund_disclosed_holdings` 已存债券持仓（含 `bond_rating`/`bond_duration`/`bond_yield`），但**无债券日估值、无可转债日行情、无收益率曲线**，债基因子回归的因子收益序列无处可来。

**实现计划**：

1. **ORM 表**：

   - `bond_main`：债券代码、名称、类型（国债/金融债/信用债/可转债）、评级、票息、到期日
   - `bond_daily`：债券代码、日期、收盘/估值、收益率
   - `yield_curve_daily`：日期、期限（1Y/3Y/5Y/10Y）、收益率（用于久期/利率/斜率/凸度因子）

2. **适配器**（`akshare.py` 扩展）：

   - 可转债日行情（转股价值、转债价格、纯债溢价率、转股溢价率）
   - 国债收益率曲线（中债/交易所口径）
   - 信用利差序列（AAA/AA 级信用债收益率 - 国债，用于信用因子）

3. **因子收益序列**（§6.2.7 回归输入）：

   - 票息因子、利率波动因子、曲线斜率因子、曲线凸度因子、隐含 AAA/AA 信用因子、信用下沉因子、转债因子
   - 用收益率曲线差分 + 信用利差差分构造，落地 `factor_return` 表（见 P4.1-5）

**验收标准**：可转债行情 + 国债收益率曲线（1/3/5/10Y）+ AAA/AA 信用利差三条序列可拉取，覆盖近 3 年，供债基滚动回归。

**落地说明**（2026-08-14 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260814_0002`）：`bond_main`（可转债主档，含评级/转股价/正股/上市日/发行规模，评级口径随抓取时点落库、附加快照进 `extra`，对齐 §5.3.3）、`bond_daily`（OHLCV + `daily_return`，`(bond_code, trade_date)` 唯一）、`yield_curve_daily`（`(curve_name, trade_date, tenor_years)` 唯一，曲线枚举 `treasury`/`medium_term_note_aaa`/`medium_term_note_aa`/`commercial_bank_bond_aaa`）。
2. **适配器**（`data/adapters/akshare.py`）：
   - `fetch_cb_list()` — 东财可转债全量列表（`bond_zh_cov`）→ `bond_main`，含转股价值/转股溢价率等快照进 `extra`
   - `fetch_cb_daily(symbol, start, end)` — 新浪可转债日行情（`bond_zh_hs_cov_daily`，全量历史 + 本地窗口过滤 + `daily_return` 计算）
   - `fetch_china_yield_curve(start, end)` — 中债收益率曲线（`bond_china_yield`，一次返回国债/中短票AAA/商业银行普通债AAA 三条曲线，展平为长表；单次窗口 ≤1 年由 update 层分片）
   - `fetch_china_credit_yield_curve(symbol, start, end)` — 银行间收盘收益率曲线（`bond_china_close_return`，中短票 AA，接口限单次 ≤1 月，适配器自动按月分窗限流）
   - 转债代码工具：`is_cb_code` / `normalize_cb_code` / `canonical_cb_code`（存库口径 `128039.SZ`/`110080.SH`）/ `cb_sina_symbol`
3. **update 工作流**（`data/update.py`）：`upsert_akshare_cb_list` / `upsert_akshare_cb_daily` / `upsert_akshare_china_yield_curve`（默认近 3 年、按年分窗）/ `upsert_akshare_credit_yield_curve` / `disclosed_convertible_bond_codes`（样本披露转债持仓解析）/ `load_credit_spread_series`（本地派生 AAA/AA − 国债利差序列）。
4. **CLI**：
   - `fund-research update bond-main` — 可转债主表
   - `fund-research update bond-daily --bond-code 128039` — 转债行情（不传 `--bond-code` 时默认样本基金披露转债持仓）
   - `fund-research update yield-curve [--start/--end]` — 国债/AAA/AA 曲线，默认近 3 年
   - `fund-research update bond-domain` — 一键更新（主表 + 行情 + 曲线），`--domains bond` 别名可用
5. **P4.0-1 闭环**：`experiments/runner.py` 动态归因现从 `bond_daily` 读取披露转债持仓的日收益序列传入 `run_attribution`，`estimated_convertible_bond_return` 在有行情时为真实剥离值；行情缺失仍走显式"未剥离"警告路径。
6. **数据源边界**：AAA 利差序列（中短票AAA − 国债，均出自中债）近 3 年完整；AA 曲线取自中国货币网中短票(AA)，该接口历史深度仅近约 3 个月（更早窗口返回 `newDateValue` 错误，免费源不可得），AA 利差序列随每日增量更新自然积累，不硬造历史（数据源诚实原则，同 P4.1-2 中信指数处理）；交易所纯债个券日估值免费源不可得，`bond_daily` 目前仅覆盖可转债。
7. **冒烟验证**：`bond_main` 1044 只可转债全量入库零警告；128039.SZ/110080.SH 行情 267 行（2023-08 起）；收益率曲线近 3 年回填：国债/中短票AAA/商业银行普通债AAA 各 748 个交易日 × 8 档期限，AA 近 3 个月 12 个交易日；`load_credit_spread_series` 利差核验合理（3Y 末值 AAA≈0.40pp、AA≈0.51pp，AA>AAA 且随期限抬升）；二次重跑 0 inserted 全 updated（幂等）。单测覆盖适配器标准化/分窗/upsert 幂等/dry-run/CLI 路由/表约束/runner 行情加载（`tests/test_data/test_update_bond_domain.py` 等，29 用例）。

### P4.1-4 ETF 产品属性数据 ★阻塞指数基金分析与优选 ✅ 已完成（2026-08-17）

**需求来源**：§6.2.8 评价维度（流动性/成交额/折溢价/跟踪误差/费率/申赎效率）。

**现状**：`fund_fee` 有费率，`fund_main` 有 `is_etf` 标识，但缺**成交额/流动性、IOPV 折溢价、跟踪误差历史、成立以来跟踪误差**。

**实现计划**：

1. **ORM 表**：`etf_profile`（基金代码、跟踪指数、日均成交额、日均换手、IOPV 溢折率、近一年跟踪误差、成立以来跟踪误差、年化超额、成立日期）
2. **适配器**：AKShare ETF 相关接口（成交额/折溢价/跟踪误差），字段映射对齐 §6.2.8。
3. 跟踪误差序列可由 `fund_nav` + `index_daily`（P4.1-2）**本地计算**，优先自算，AKShare 仅做交叉校验。

**验收标准**：样本内 ETF 均能产出 §6.2.8 评价维度所需的规模/费率/流动性/跟踪误差/折溢价五项字段。

**落地说明**（2026-08-17 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260817_0001`）：`etf_profile`（fund_code 唯一，跟踪指数/成立日/日均成交额/日均换手/溢折率/近一年与成立以来年化跟踪误差/年化超额/快照日期，计算口径与附加字段落 `extra`）。
2. **适配器**（`data/adapters/akshare.py`）：
   - `fetch_etf_spot()` — 东财全市场 ETF 快照（`fund_etf_spot_em`），折溢价统一为正=溢价口径（东财"基金折价率"取反），IOPV/份额/市值进 `extra`
   - `fetch_etf_daily_hist(symbol, start, end)` — 东财日线（`fund_etf_hist_em`，含换手率）；东财偶发断连时**自动回退新浪源**（`fund_etf_hist_sina`，全量历史本地过滤，无换手率）
   - `fetch_etf_f10_profile(fund_code)` — 东财 F10 基本概况抓取（跟踪标的/成立日期/管理费率/托管费率，C 级源），跟踪指数经 `resolve_tracking_index_symbol` 映射为 benchmark symbol（沪深300→sh000300 等，未收录指数返回 None 并告警，不硬猜）
   - 东财接口统一 `_retry_call` 指数退避重试
3. **跟踪误差本地计算**（`data/update.py`）：`compute_etf_tracking_stats` 用 `fund_nav` 日收益 vs `stock_daily` 指数日收益对齐序列，年化跟踪误差 = 日超额标准差(ddof=1)×√252，近一年窗口 252 交易日 + 成立以来全窗口；指数 `daily_return` 为空（腾讯源）时由收盘价 pct_change 本地推导；样本 <20 不计算并告警。
4. **CLI**：`fund-research update etf-profile [--fund-code]`，默认样本内 `fund_main.is_etf=1` 的 ETF；`--domains etf` 别名可用。快照口径 upsert：新值为空保留旧值（盘前快照不抹掉已有属性）。
5. **冒烟验证**：样本 3 只 ETF（510300/510500/159915）五维度齐备 —— 规模（快照总市值进 `extra.market_cap`）、费率（F10 管理/托管费率进 `extra`）、流动性（日均成交额 40–55 亿元/日）、跟踪误差（如 510300 近一年 0.36%/成立以来 0.82%）、溢折率（±0.1% 内）；跟踪指数/成立日与 F10 一致。单测 19 用例（适配器标准化/新浪回退/F10 解析/跟踪计算含兜底/幂等合并/CLI 路由），全量回归 536 passed。
6. **已知边界**：雪球源不支持场内 ETF 的规模/费率（`fund_scale`/`fund_fee` 对 ETF 失败），改由 ETF 快照市值 + F10 费率覆盖该两项；新浪回退无换手率字段（仅东财源有）；东财 hist 接口间歇断连属上游问题，已有重试 + 回退兜底。

### P4.1-5 因子收益表（通用） ✅ 已完成（2026-08-17）

**需求来源**：§15.2 因子收益表、§6.2.7 债基滚动回归输入。

**实现计划**：

1. `factor_return` 表：因子名、日期、因子收益。
2. 首批覆盖：债券因子（P4.1-3 派生）+ 现有风格因子（沪深300/500/1000/成长/价值，复用 `index_daily`）。
3. 因子收益统一走 `update` CLI 一个实体，避免散落。

**落地说明**（2026-08-17 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260817_0002`）：`factor_return`（`(factor_name, trade_date)` 唯一），因子名常量 `FACTOR_NAMES`：风格 5 个（`style_large_cap/mid_cap/small_cap/growth/value`，复用 `exposure.DEFAULT_STYLE_FACTORS` 指数口径）+ 债券 8 个（`bond_coupon/rate/slope/convexity/credit_aaa/credit_aa/credit_sink/convertible`）。
2. **构造口径**（`data/update.py` `build_bond_factor_rows` / `build_style_factor_rows`，近似口径文档可追溯）：
   - 风格因子：指数日收益（`stock_daily`，`daily_return` 缺失时收盘价 pct_change 兜底）
   - `bond_coupon` = 1Y 国债收益率/252；`bond_rate` = −10×Δy(10Y)（10 年零息久期近似）；`bond_slope` = 10Y 与 1Y 零息收益之差；`bond_convexity` = 0.5×10²×(Δy10)²
   - `bond_credit_aaa/aa` = −3×Δ利差（3Y 中票 − 3Y 国债，3Y 中票久期近似）；`bond_credit_sink` = AA − AAA；`bond_convertible` = 在库转债日收益截面等权
3. **CLI**：`fund-research update factor-return [--factor bond_rate ...] [--start/--end]`，别名 `--domains factor`；未知名告警跳过，无样本数据告警提示。
4. **冒烟验证**：13 个因子共 24336 行入库零警告 —— 风格因子全历史（沪深300 自 2005 年 5187 日）；债券利率/票息/斜率/凸度/AAA 信用因子近 3 年 747 日；AA/下沉受曲线深度限制近 3 个月 11 日（同 P4.1-3 边界）；转债因子 194 日（在库 2 只转债）。数值合理性核验：`bond_rate` 日极值 ≈1%（10bp×10 久期）、`bond_coupon` 均值≈ 1.5%/252；二次重跑 0 inserted 全 updated（幂等）。单测 8 用例（构造公式逐项验证/幂等/窗口/未知因子/CLI 路由），全量回归 545 passed。
5. **已知边界**：AA/信用下沉因子历史深度受中国货币网曲线限制（近约 3 个月）随增量积累；转债因子仅覆盖已入库行情的转债，样本扩容后自动扩充。

---

## 3. 架构与口径准备（P4.2）

### P4.2-1 模型模板机制扩展 ★阻塞债基/ETF 算法

**需求来源**：§6.2.7 验收（"短债/纯债/二级债/转债基金需使用不同模板"）、§17（"不同基金类型混用模型"风险）。

**现状**：[fingerprint.py](../src/fund_research/analysis/fingerprint.py) 仅 `active_equity`/`index_fund`/`default` 三套模板；债基无模板，债基因子算法无类型分流。

**实现计划**：

1. 扩展模板枚举，新增：
   - `bond_pure`（纯债）、`bond_short`（短债）、`bond_secondary`（二级债基）、`bond_convertible`（可转债）
   - `index_fund` 细分（被动指数/指数增强/ETF/联接）
2. `credibility.py` 的 `MODULE_FUND_TYPE_EXCLUSIONS` 同步更新（债基因子仅适用债基，ETF 优选仅适用指数类，避免跨类型硬算）。
3. 未适配类型直接标"不适用"（`needs_review`），不输出确定性结论。

### P4.2-2 指标注册表补全

**需求来源**：§7.4 指标注册表（AI 理解口径的基础组件）。

**现状**：`config/metrics_registry_template.yaml` 仅 8 个指标（收益/风险/集中度/持有人），无债基、ETF、跟踪误差、折溢价等定义。

**实现计划**：补充以下指标组的 YAML 定义：

- 债券：久期、信用暴露、杠杆、转债暴露、利率风险
- ETF/指数：跟踪误差、年化跟踪误差、日均偏离、折溢价、超额收益、信息比率
- 基础补全（P4.0-2 同步）：胜率、回撤修复天数、同类排名

### P4.2-3 口径版本化

**需求来源**：§5.3.3 口径一致性（行业分类、债券评级口径版本化）。

**实现计划**：

1. `industry_category` 表已有 `classification_version` 字段，指数/成分数据（P4.1-2）落地时强制写版本。
2. 债券评级口径：明确采用发行时评级 vs 最新评级，落库时记 `rating_date`/`rating_source`。

---

## 4. 执行顺序与依赖关系

### 4.1 依赖图

```
P4.0-1 转债收益 ────────┐
                        ├── 依赖 P4.1-3 可转债行情
P4.1-3 债券数据域 ──────┼──→ P4.2-1 债基模板 ──→ Phase4 债基因子暴露
                        │
P4.1-2 指数数据域 ──────┼──→ Phase4 ETF组合构建 / 指数基金优选
                        │
P4.1-4 ETF属性 ─────────┤
                        │
P4.1-1 样本扩充 ────────┴──→ 所有 Phase4 算法验证
                        │
P4.0-2 基础指标 (独立) ──┤
                        │
P4.2-2 指标注册表 (独立)─┘
```

### 4.2 推荐执行批次

| 批次   | 任务                                                | 依赖                 | 可并行          |
| ------ | --------------------------------------------------- | -------------------- | --------------- |
| **B1** | P4.1-1 样本扩充                                     | 无                   | P4.0-2 基础指标 |
| **B2** | P4.1-2 指数数据域 + P4.1-3 债券数据域               | 无                   | B1              |
| **B3** | P4.1-4 ETF 属性 + P4.1-5 因子收益表                 | B2（指数行情）       | B1              |
| **B4** | P4.0-1 转债收益（剥离残差）                         | B2（转债行情）       | B3              |
| **B5** | P4.2-1 模板扩展 + P4.2-2 注册表 + P4.2-3 口径版本化 | B1（样本确认新类型） | B4              |

### 4.3 完成标准（进入 Phase 4 前）

- [x] 样本基金扩充至 ~50 只，含 ETF/联接/指增/债基（短债/纯债/二级债/转债）各类型代表（P4.1-1，实际 53 只）
- [x] 申万/中信行业指数行情 + 成分权重可拉取（P4.1-2；申万一级 31 个全覆盖，中信一级免费数据源不可得、已预留 `CITIC` 体系待接入）
- [x] 可转债行情 + 国债收益率曲线 + AAA/AA 信用利差可拉取（P4.1-3；国债/中短票AAA 近 3 年完整，中短票AA 受免费源限制仅近约 3 个月并随增量积累，利差由 `load_credit_spread_series` 本地派生）
- [x] ETF 规模/费率/流动性/折溢价/跟踪误差字段齐备（P4.1-4；`etf_profile` 三样本 ETF 五维度全部产出，规模/费率由快照市值+F10 覆盖）
- [x] 收益拆解"转债收益"从残差剥离，`estimated_convertible_bond_return` 为真实计算值（P4.0-1，含 `convertible_bond_coverage` 披离标识）
- [x] §6.1.4 胜率/回撤修复天数/同类排名 三指标可用（P4.0-2，`nav_metrics.py` + `analysis/rank.py`）
- [ ] 债基/指数模板分流就绪，未适配类型标"不适用"（P4.2-1）
- [ ] 指标注册表覆盖债基/ETF 指标定义（P4.2-2）

---

## 附：与本计划相关的已完成事项

- [x] 无风险利率口径统一（`settings.risk_free_rate=0.02`，修复 `scoring_dimensions.py` 硬编码）
- [x] `anomaly.py` 前十大集中度未排序 bug 修复
- [x] `trading_ability.py` 年化换手率半年报硬编码假设修复
- [x] P4.0-1 收益拆解补"转债收益"（`total_cb` 真实计算 + coverage 标识；打新保持不可观测占位并显式标注）
- [x] P4.0-2 基础指标补全（`win_rate` / `recovery_days` / `rank.py` 同类排名）
- [x] P4.1-1 样本基金扩充至 53 只（主动权益 30 + 指数/ETF/联接/指增 11 + 债基 12）
- [x] P4.1-2 指数数据域（`index_main` / `index_daily` / `index_constituent` 三表 + 申万适配器 + CLI 批量链路，2026-08-14）
- [x] P4.1-3 债券数据域（`bond_main` / `bond_daily` / `yield_curve_daily` 三表 + 可转债/收益率曲线适配器 + CLI 批量链路 + 动态归因转债行情接入，2026-08-14）
- [x] P4.1-4 ETF 产品属性（`etf_profile` 表 + ETF 快照/日线/F10 适配器 + 跟踪误差本地计算 + CLI，2026-08-17）
- [x] P4.1-5 因子收益表（`factor_return` 表，风格因子 5 + 债券因子 8，收益率曲线差分/信用利差差分本地派生，2026-08-17）
