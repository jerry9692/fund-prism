# Phase 4 开发计划：ETF/指数、组合与更多资产类型

> 对照 [v0.4 需求书](../AI-oriented开源个人基金研究平台需求书_v0.4.md) §12.4 四期范围，承接 [Pre-Phase 4 计划](./pre_phase4_plan.md)（P4.0–P4.3 已全部完成 ✅）。
> 优先级与口径决策同步参考 [与「小基啄米」对比报告](./comparison_with_xiaoji_legacy.md)：其 §3.2 所列 Phase 4 核心新功能（P0 收益拆解欠账 + P1 指数优选/债基因子 + P2 ETF 组合/画像频谱）中，P0 欠账已在 Pre-Phase 4 阶段闭环（转债收益真实剥离，打新保持不可观测占位），其余按 P1→P2 价值排序落入本计划 P4A–P4E 批次。
> 本计划只覆盖 Phase 4 **正题**：在已就绪的数据底座与模板架构上，落地五大能力闭环 —— 指数基金优选、债基因子暴露、组合穿透分析、ETF 组合构建、公司/经理画像频谱。

---

## 0. 总览

### 0.1 起点状态（Pre-Phase 4 完成度）

| 底座 | 状态 | 可支撑的 Phase 4 能力 |
| --- | --- | --- |
| 样本基金 53 只（30 主动权益 + 11 指数/ETF + 12 债基） | ✅ | 所有算法的验证样本 |
| 指数数据域（index_main/daily/constituent，申万一级 31 个） | ✅ | ETF 组合行业偏离、指数基金分组 |
| 债券数据域（bond_main/bond_daily/yield_curve_daily） | ✅ | 转债因子、收益率曲线因子 |
| ETF 属性（etf_profile：成交额/折溢价/跟踪误差/费率） | ✅ | 指数基金优选五维度 |
| 因子收益表（factor_return：风格 5 + 债券 8） | ✅ | 债基滚动回归的因子收益序列 |
| 模板机制（债基四模板 + 指数被动/增强细分，零误分流） | ✅ | 分模板算法路由 |
| 门禁占位（credibility：bond_factor_exposure / etf_selection） | ✅ | 基金族适用性门禁直接启用 |
| 指标注册表（债券组 5 + ETF/指数组 6） | ✅ | 新算法指标口径对齐 |
| 口径版本化（SW2021、评级快照） | ✅ | 行业/评级可追溯 |

### 0.2 Phase 4 交付物（§12.4 逐条映射）

| # | §12.4 范围 | 需求书细则 | 对比报告映射 | 本计划批次 |
| --- | --- | --- | --- | --- |
| 1 | 指数基金分析与优选、跟踪误差/费率/流动性对比 | §6.2.8 | 1.2（P1） | **P4A** |
| 2 | 基金组合穿透分析、持仓重叠、风格偏离、回撤与相关性 | §6.3.9 + §12.4.2 | —（需求书既定） | **P4C** |
| 3 | 债基金因子暴露粗粒度版（久期/信用/杠杆/转债/利率/流动性） | §6.2.7 | 1.1（P1） | **P4B** |
| 4 | 组合 Research Packet 和组合 Evidence | §12.4.4 | — | **P4C** |
| 5 | 基金公司画像频谱和基金经理团队画像 | §6.2.6 + §12.4.5 | 1.5（P2，可推迟） | **P4E** |
| 6 | ETF 组合构建（§12.4.1 延伸细则） | §6.2.9 | 1.3（P2，复用 CVXPY 勿抄爬山） | **P4D** |

> 对比报告 P0 项「收益拆解补打新/转债」（1.4）已在 Pre-Phase 4 闭环：转债收益从残差真实剥离（P4.0-1），打新因数据不可观测保持占位并显式标注——不再占 Phase 4 批次。

### 0.3 设计原则（贯穿全部批次）

1. **门禁先行**：每个新模块结果经 `credibility.py` 五道门禁，`bond_factor_exposure` 仅债基、`etf_selection` 仅指数类，跨类型调用直接 `needs_review`。
2. **估计隔离**：回归暴露、组合穿透到模拟持仓一律 `estimated_*` 字段，不进默认评分与高置信结论。
3. **数据源诚实**：免费源不可得的维度（流动性因子时序、AA 因子长历史、交易所纯债个券估值）显式降级 + 告警，不硬造。
4. **算法版本化**：每个模块独立 `ALGORITHM_VERSION`，结果落库可追溯（§7.1），口径近似必须在落地说明中文档化（延续 P4.1-5 做法）。
5. **统一 API 返回**：所有新端点 `APIResponse[T]` + `{data, metadata, evidence, warnings, conclusion_status}`。

---

## 1. P4A 指数基金分析与优选（§6.2.8）★ 首批，组装成本最低 ✅ 已完成（2026-08-20）

**现状**：`etf_profile` 五维度数据齐备（P4.1-4），`index_daily` 基准序列就绪，但无分析模块，`etf_selection` 仅门禁占位。

**实现计划**：

1. **新模块 `analysis/index_fund_selection.py`**：
   - **同指数分组**：按 `etf_profile.tracking_index`（含 `resolve_tracking_index_symbol` 兜底映射）分组；未解析跟踪指数的产品单列并告警，不强行归组。
   - **跟踪质量曲线**：日偏离序列 = 基金日收益 − 基准日收益（`fund_nav` vs `stock_daily` 指数，口径与 P4.1-4 `compute_etf_tracking_stats` 完全一致）；输出累计偏离曲线、日均偏离、最大偏离（§6.2.8 评价维度 3）。
   - **超额收益与稳定性**：指增产品（`index_enhanced` 模板）单列 alpha —— 复用 `scoring_dimensions.py` Jensen's Alpha 口径，输出 alpha + 信息比率 + 月度超额胜率。
   - **综合优选评分**：五维度（规模/费率/流动性/跟踪质量/折溢价）组内分位数加权，权重与公式注册进 `metrics_registry`；分项得分全透明（§7.3 可解释性）。
2. **结果表 `index_fund_selection_result`**（`models_phase4.py` + Alembic 迁移）：fund_code、分组键、五维分项、综合分、算法版本、conclusion_status。
3. **API**：`GET /api/v2/index-funds/compare?index_symbol=...`（同指数对比表）、`POST /api/v2/index-funds/selection`（综合评分排序）。
4. **前端**：ETF 对比/优选页（§14.2 第 10 页配套）—— 分组对比表 + 偏离曲线 + 评分解释。

**验收标准**（§6.2.8）：

- [x] 样本 11 只指数类基金全部产出对比表；同跟踪指数组内 ≥2 只时输出优选排序与理由
- [x] 指增产品 alpha 与被动产品结论状态区分（被动产品不输出 alpha 结论）
- [x] 五维度任一缺失时降权 + 告警，不补 0 分

**落地说明**（2026-08-20 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260820_0001`）：`index_fund_selection_result`（五维分项 JSON + 综合分 + 组内排名 + 指增 alpha/IR + 结论状态/告警，`(fund_code, calc_date, 算法名, 版本)` 唯一）。
2. **算法**（`analysis/index_fund_selection.py`，算法版本 0.1.0）：候选 = is_etf/联接/指增标识或指数族分类；跟踪指数解析 etf_profile 优先、业绩基准名称映射兑底（未收录不硬猜）；跟踪质量复用 P4.1-4 `_load_return_series` 对齐口径（最低 60 重叠样本），输出累计偏离曲线/日均偏离/最大偏离；指增 Jensen Alpha/IR/月度超额胜率（Rf 读 settings）；五维全池分位数评分，缺失维度权重再归一（流动性/折溢价仅场内产品可得）；跟踪维度缺失降 observation。
3. **门禁适配**：场内 ETF 东财一级分类常为“股票型”，`is_etf` 等标识优先于粗分类归指数族；“股票型-增强指数”分类识别为 `index_enhanced` 模板。
4. **API**：`GET /api/v2/index-funds/compare?index_symbol=`（不落库，含偏离曲线）、`POST /api/v2/index-funds/selection`（幂等落库）、`GET /api/v2/index-funds/selection/latest`。
5. **前端**：指数优选页（`/index-funds`，导航“指数优选”layers 图标）—— 综合排序表 + 同指数对比表 + 累计偏离曲线图。
6. **冒烟验证**：真实库 11 只指数类产品 = 8 computed（300×2 / 905×3 / 上证50×2 / 创业板×1 四组，指增 161017 alpha 3.97% IR 0.82、110003 alpha 4.63% IR 0.84，被动零 alpha）+ 3 needs_review（行业/主题指数联接与指增，跟踪指数免费行情源不可得，诚实降级）。顺带回填 `update index-daily --index-symbol sh000016` 5496 行。新增单测 25 例（分组/评分方向/降权/门禁/幂等/API），全量回归 642 passed，ruff 全绿，前端 tsc 零错误。
7. **已知边界**：行业/主题指数（中证医药/有色/红利）行情免费源不可得，对应产品标 needs_review；场外产品无流动性/折溢价维度；`fund_scale` 对部分样本缺失时规模维度降权。
8. **审计修复**（2026-08-20 同日 CodeReview）：① `index_symbol` 改为输出层过滤 —— 评分/排名始终全池计算后再按指数筛选，门禁拒绝/未解析记录不再泄漏进局部报告，且局部与全量运行评分口径一致（防幂等落库交叉污染）；② 前端偏离曲线改 ECharts 时间轴（各 series 自带 [date, value]），修复组内产品历史长度不同时的时间错位；③ `raw_metrics` 前端类型补 string（window_start/end）。新增 3 例回归用例，全量回归 644 passed。

---

## 2. P4B 债基金因子暴露 · 粗粒度版（§6.2.7）★ Phase 4 核心研究域 ✅ 已完成（2026-08-20）

**现状**：`factor_return` 债券 8 因子就绪；债基四模板零误分流；但 `fingerprint.py` 债基模板的债券因子维度组为空（权重 0 占位），无回归模块。

**口径决策（粗粒度版边界，§12.4 明确"粗粒度"）**：

- 一期启用因子：`bond_coupon`（票息/杠杆近似）、`bond_rate`（利率波动，久期代理）、`bond_slope`（曲线斜率）、`bond_credit_aaa`（信用）、`bond_convertible`（转债），另加权益 beta（沪深300，仅二级债基/转债基金）。需求书 12 因子中：**久期因子**由 `bond_rate` 暴露代理（久期×利率变动的镜像），**流动性因子**免费源不可得 → 显式不启用 + 告警登记；`bond_credit_aa`/`bond_credit_sink` 因子序列仅近约 3 个月（中国货币网深度限制），**回归默认不含，待序列积累后开关启用**。
- 杠杆因子无独立时序（需债基杠杆率披露），一期并入票息因子说明，不单独建模。

**实现计划**：

1. **新模块 `analysis/bond_factor_exposure.py`**：
   - **滚动回归**：基金日收益对因子收益（`factor_return`）OLS，窗口 120 交易日、步长 20；输出各因子暴露曲线、t 值、滚动 R²（回归稳定性，§7.3 第 4 条）。
   - **模板分流**：按 P4.2-1 路由 —— `bond_short` 只用短端因子（coupon/credit_aaa，剔除 bond_rate 长端项）、`bond_pure` 无权益/转债、`bond_secondary` +权益 beta+转债、`bond_convertible` 权益 beta 权重更高；非债基调用心 `MODULE_FUND_TYPE_EXCLUSIONS` 拒绝。
   - **输出**：因子暴露曲线、因子收益贡献拆解（暴露 × 因子累计收益）、久期/信用/杠杆/转债风险雷达数据、同类对比（`rank.py` 口径）。
2. **结果表 `bond_factor_exposure_result`**（§15.2 第 11 条）：fund_code、as_of_date、窗口、各因子暴露/t 值/R²、算法版本。
3. **指纹闭环**：回归结果回填 `fingerprint.py` 债基模板的债券维度组（启用维度权重 >0），ALGORITHM_VERSION bump（0.2.0→0.3.0），persist 按版本自动产生新记录。
4. **API**：`POST /api/v2/analysis/bond-factors/{fund_code}`（单次）、批量入口复用 experiments runner；`evidence` 记录因子序列覆盖度。
5. **前端**：债基风险扫描页（§14.2 第 11 页）—— 暴露曲线 + 雷达图 + 回归稳定性。

**验收标准**（§6.2.7）：

- [x] 12 只债基样本暴露方向符合 `expected_bond_profile` 标注（如转债基金转债因子暴露显著 > 纯债；短债利率暴露 < 纯债）。
- [x] 四类模板使用不同因子子集，零跨模板硬算；因子序列不足的基金 `needs_review` + 覆盖度告警。
- [x] 二级债基权益 beta 与转债基金可区分。

**落地说明**（2026-08-20 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260821_0001`）：`bond_factor_exposure_result`（模板/窗口/因子列表/最新暴露/t 值/全窗口与滚动 R²/暴露曲线 JSON/贡献拆解/雷达/同类排名/因子覆盖度/窗口起止/结论状态与告警，`(fund_code, calc_date, 算法名, 版本)` 唯一）。
2. **算法**（`analysis/bond_factor_exposure.py`，算法版本 0.1.0）：滚动 OLS（窗口 120 交易日/步长 20，含截距，numpy lstsq + t 值）；模板因子子集：`bond_short`=coupon/credit_aaa（剔除 bond_rate 长端项）、`bond_pure`=+rate/slope（无权益/转债）、`bond_secondary`/`bond_convertible`=+转债+权益 beta（`style_large_cap` 即沪深300）；转债模板必备因子缺失直接 needs_review 不硬算；单因子覆盖度 <60% 剔除 + 告警；对齐样本 <120 → needs_review；全窗口 R²<0.3 → observation。输出：暴露曲线/t 值/滚动 R²、贡献拆解（全窗口暴露×因子累计收益+截距+残差闭合到基金累计收益）、风险雷达（久期=bond_rate 暴露×10、信用=credit_aaa 暴露×3、票息 carry=暴露×因子日均×252、转债、权益 beta）、同类对比（rank.py k/N，同 sub_category 按全窗口 R²）。
3. **门禁适配**：`credibility.py` 新增 `bond_factor_exposure` 最低覆盖度 0.6 与 R²≥0.3 残差门禁（soft）；非债基族经 `MODULE_FUND_TYPE_EXCLUSIONS` 拒绝（既有占位生效）。
4. **指纹闭环**：债基四模板启用 `bond_factor` 维度组（权重 1.0），回归结果回填 `estimated_duration/credit/coupon_carry/convertible_exposure/equity_beta/r_squared`（一律 `estimated_*` 隔离，结论状态 estimated）；fingerprint ALGORITHM_VERSION 0.2.0→0.3.0。
5. **API**：`POST /api/v2/analysis/bond-factors/{fund_code}`（单只，含同类批次内排名，幂等落库 + evidence 登记因子序列覆盖度，支持 `persist=false` 干跑）、`POST /api/v2/analysis/bond-factors/run`（批量）、`GET /api/v2/analysis/bond-factors/scan`（风险扫描页读已落库）、`GET /api/v2/analysis/bond-factors/{fund_code}/latest`。批量入口未接入 experiments runner（runner 与动态归因强耦合，延续 P4A 独立端点做法）。
6. **数据回填**：顺带拉取在库两只转债（110080.SH/128039.SZ）全历史行情 +1795 行，`bond_convertible` 因子序列由 194 天扩展至 1438 天（2018-07-02 起，两只样本转债 2024-06 到期后序列自然截止）。
7. **前端**：债基风险扫描页（`/bond-factors`，导航 scan 图标）—— 12 只债基扫描表（模板/雷达五值/R²/同类排名/窗口/状态）+ 单基金详情（暴露曲线、风险雷达、滚动 R² 稳定性、贡献拆解表、因子覆盖度）。
8. **冒烟验证**：真实库 12 只债基 = 6 computed（3 转债 conv 0.055–0.095 / eq beta 0.51–0.67，3 二级债基 conv 0.03–0.045 / eq beta 0.02–0.37，方向与可区分性符合标注）+ 6 observation（2 纯债/2 短债/2 一级债基，全窗口 R² 0.01–0.17 < 0.3 诚实降级；短债模板不输出久期代理符合预期）。新增单测 28 例（模板子集/暴露方向恢复/门禁/降级/贡献闭合/雷达/同类排名/幂等/指纹回填/API 四端点），全量回归 672 passed，ruff 全绿，前端 tsc 零错误。
9. **已知边界**：利率/信用因子序列仅 3 年（收益率曲线拉取深度限制，2023-08 起），含 bond_rate 因子的基金回归窗口受其约束，深度历史随每日增量积累（与 AA 因子同登记）；转债因子截面仅样本披露两只转债，等权口径；纯债/短债 R² 普遍偏低（票息收益主要落截距项），粗粒度版结论以暴露方向为主；流动性因子免费源不可得显式不启用（告警登记）；杠杆并入票息因子说明不单独建模。
10. **审计修复**（2026-08-21 Phase 4 全量 CodeReview）：滚动回归末窗口对齐数据末尾（原末窗口可能滞后 (n−window)%step 个交易日，`latest_exposures` 与 `window_end` 口径自相矛盾）；`exposure_row_to_dict` id 改 str 序列化（19 位大整数防 JS 精度丢失）。新增 1 例末窗口对齐回归用例。

---

## 3. P4C 基金组合穿透分析与组合研究包（§6.3.9 + §12.4.2/§12.4.4）✅ 已完成（2026-08-20）

**现状**：`fund_pool` 仅池管理 + 提醒（pool_alert），无权重组合分析；`research_packet` 仅单基金实体；`compare_fund_fingerprints` 只有指纹相似度，无持仓穿透（P4.0-4 已登记欠账）。

**实现计划**：

1. **组合实体**：`fund_pool_member` 新增可空 `weight_pct`（组合语义 = 有权重的池；无权重视为 watchlist，向后兼容）；新增 `user_portfolio` 结果表存组合分析快照。
2. **新模块 `analysis/portfolio.py`**：
   - **组合层指标**：NAV 加权组合日收益序列 → 收益/波动/回撤/修复天数（复用 `nav_metrics.py`）；基金间相关性矩阵。
   - **穿透暴露**：风格暴露 = 基金指纹风格维度加权合成；行业暴露 = 披露持仓行业权重加权合成（`stock_industry_membership` SW2021 口径）。
   - **重仓重叠穿透**：披露持仓交集（fact/computed 口径）+ 模拟持仓交集（`estimated_*` 口径，隔离展示）；输出重叠度指标 + Top 重叠个股贡献。
   - **集中度风险**：基金经理集中度（同一经理权重合计）、单公司基金集中度。
   - **组合优化（可选子项，工作量超预算则裁剪）**：CVXPY 复用模拟持仓引擎，最小化组合波动/控制最大回撤，约束相关性上限与风格偏离上限（§6.3.9 第 4 条）。
3. **组合 Research Packet / Evidence**（§12.4.4）：`research_packet.entity_type` 扩展 `portfolio`，packet 组装组合指标 + 穿透结果 + 各成分基金 evidence 引用；导出带算法版本/数据日期/免责声明（§6.3.10）。
4. **API**：`POST /api/v2/portfolios/{pool_id}/analysis`、`POST /api/v2/portfolios/{pool_id}/packet`。
5. **前端**：组合管理页扩展（现有 FundPoolPage 增加权重编辑 + 分析 Tab）。

**验收标准**：

- [x] 组合收益/回撤与手工加权口径一致；相关性矩阵对称且对角为 1。
- [x] 重叠穿透区分披露口径（computed）与模拟口径（estimated），后者不进默认结论。
- [x] 组合研究包可导出且包含全部成分基金 evidence 链。

**落地说明**（2026-08-20 实施记录）：

1. **ORM**（migration `20260821_0002`，SQLite batch）：`fund_pool_member.weight_pct` 可空权重（有权重=组合，无权重=观察列表，向后兼容）；`user_portfolio` 组合分析快照表（成员权重/组合指标/相关性/风格与行业穿透/重叠/集中度/窗口/结论状态，`(pool_id, calc_date, 算法名, 版本)` 唯一）；`research_packet` 扩展 `entity_type`/`pool_id` 且 `fund_code` 可空（组合包）。
2. **算法**（`analysis/portfolio.py`，算法版本 0.1.0）：NAV 加权组合日收益（共同日期窗口，成员 <2 或重叠 <60 日 → needs_review；全员无权重 → 等权 + 观察列表告警）复用 `nav_metrics` 口径；相关性矩阵；风格穿透（最新风格回归暴露加权合成，缺失成员权重再归一 + 告警）；行业穿透（披露持仓 × SW2021 一级映射加权合成，含 HHI）；重仓重叠（≥2 成员共享个股 + 组合层合计权重 Top20 + 成对重叠矩阵，披露口径 computed），模拟持仓重叠一律 `estimated_*` 键隔离不进默认结论；集中度（同一现任经理/同一公司权重合计）。
3. **组合研究包**（§12.4.4，`research/portfolio_packet.py`，模板 `portfolio_checkup`）：`ResearchPacketMetadata` 扩展 entity_type/pool_id/pool_name，`ResearchPacket` 新增 portfolio 段；evidence 登记 portfolio_analysis + portfolio_nav_metrics 两条（实体类型 portfolio），并引用各成分基金最近 5 条 evidence（member_evidence_refs，证据链完整）；Markdown 导出带算法版本/数据日期/免责声明（§6.3.10）；`_persist_evidence_records` 支持 portfolio 实体类型。
4. **API**：`PATCH /api/v2/pools/{pool_id}/weights`（批量设权重，null 清除，非池内成员告警跳过）、`POST /api/v2/portfolios/{pool_id}/analysis`（幂等落库）、`GET .../analysis/latest`、`POST /api/v2/portfolios/{pool_id}/packet`；`add_pool_member`/`get_pool` 扩展 weight_pct。组合优化子项（CVXPY）本轮未实施，登记为可裁剪欠账（见 §8）。
5. **审计修复（同日浏览器验证发现，P2.5-1 同源隐患）**：代理 ID 为 19 位大整数超 JS Number 安全范围，前端精度丢失致池详情 404 —— pools/alerts 全部端点 ID 统一 str 序列化（pool/member/rule/alert 的 id 与 rule_id），路径参数 rule_id/alert_id 改 str 内部 int() 转换，前端 Pool/AlertRule/AlertRecord/FundListPage 类型同步 string 化。
6. **前端**：FundPoolPage 扩展 —— 权重列内联编辑 + 保存权重（脏检查），组合穿透分析区块：指标卡（年化/波动/回撤/Sharpe/修复天数/月度胜率）、风格/行业穿透、相关性矩阵、集中度、重仓重叠两栏（披露 + estimated 隔离框）、生成组合研究包。
7. **冒烟验证**：真实库示例组合（000001/020005/040022，40/30/30）computed：年化 3.07%/波动 18.68%/最大回撤 -52.75%/窗口 2011-06-24→2026-08-19；风格穿透仅 1 只成员可得（降权告警诚实降级），行业 Top 电子/汽车/通信，经理集中度 0.4；组合研究包 `rp_pool_*` 落库（entity_type=portfolio）。浏览器端到端：权重保存/运行分析/快照加载全部 200，console 零报错。
8. **测试**：新增 25 例（权重归一双模式/手工加权一致性/相关性对称/穿透再归一/estimated 隔离/集中度/降级路径/幂等/API 四端点），全量回归 697 passed（含 DuckDB 迁移兼容），ruff 全绿，前端 tsc 零错误。
9. **审计修复**（2026-08-21 Phase 4 全量 CodeReview）：① 零权重成员不再参与组合共同收益窗口交集（原零权重成员的短历史会 dropna 截断整个组合窗口致 needs_review 误降级），改为仅权重 >0 成员取交集并告警标注；② 成对重叠矩阵修复外层循环覆盖下三角（原仅上三角，与“对称矩阵”口径不符）；③ `portfolio_row_to_dict` id/pool_id 改 str 序列化。新增 3 例回归用例。

---

## 4. P4D ETF 组合构建（§6.2.9）✅ 已完成（2026-08-21）

**现状**：无。老系统用行业映射 + 爬山法；需求书明确二次规划，应**复用 CVXPY 凸优化引擎**（与模拟持仓同源），不照抄爬山（对比报告 §3.2 结论）。

**实现计划**：

1. **新模块 `analysis/etf_portfolio.py`**：
   - **输入**：目标指数（默认沪深300/中证500/申万行业指数组合权重）、可选 ETF 池（默认样本内 + etf_profile 全市场可选）、单只权重上下限、规模/流动性/费率/跟踪误差阈值、数量上限。
   - **优化**：CVXPY 二次规划，目标 = 最小化组合与目标指数收益序列的跟踪误差（样本协方差 + Ledoit-Wolf 收缩做稳健化，避免过拟合，§6.2.9 第 3 条）；约束逐条可回显（§7.3 第 5 条“约束是否生效、为何选某只 ETF”）。
   - **再平衡模拟**：月度/季度再平衡回测，输出换手率与成本（费率×换手）。
   - **输出**：推荐权重、历史拟合收益/跟踪误差/最大偏离、组合费率/规模/流动性、与目标指数的行业/风格偏离（`index_constituent` 申万行业权重对照）。
2. **结果表 `etf_portfolio_result`**（§15.2 第 12 条）：目标、成分权重、回测指标、约束清单、算法版本。
3. **API**：`POST /api/v2/etf-portfolio/build`、`GET /api/v2/etf-portfolio/{result_id}`。
4. **前端**：ETF 组合构建页 —— 参数表单 + 结果权重表 + 偏离对照。

**验收标准**：

- [x] 沪深300 目标：构建组合历史跟踪误差 < 单只最差候选，约束全部满足且逐条可解释。
- [x] ETF 池 <2 只或序列 <60 交易日时 `needs_review` 降级，不输出推荐。
- [x] 再平衡模拟输出换手与成本，且换手限制生效。

**落地说明**（2026-08-21 实施记录）：

1. **ORM**（`db/models_phase4.py` + migration `20260821_0003`）：`etf_portfolio_result`（目标/候选数/成员权重 JSON/组合属性/再平衡回测/约束清单/行业偏离/窗口/结论状态与告警，`(target_symbol, calc_date, 算法名, 版本)` 唯一）。
2. **算法**（`analysis/etf_portfolio.py`，算法版本 0.1.0）：候选 = 样本内 ETF/联接（指增偏主动不入跟踪构建池），经门禁（`etf_portfolio_build` 仅指数族）+ 跟踪指数匹配 + 规模/流动性/费率/跟踪误差阈值过滤（阈值缺失不硬判，数据源诚实）；收益矩阵全历史对齐（净值复权口径同 P4.1-4）；CVXPY 二次规划最小化组合与目标指数的跟踪误差方差，协方差对联合收益矩阵做 Ledoit-Wolf 收缩（不可用时回退样本协方差 + 告警）；数量上限为基数约束（非凸）：全池求解后保留权重最大 k 只在子集重解，严格成立；换手上限以凸约束 `Σ|w−w_prev| ≤ cap`（双边）生效。历史拟合指标 + 单只候选 TE 对照（组合未跑赢最差单票 → observation）；walk-forward 再平衡回测（期间逐日漂移，再平衡日用过去 lookback 窗口重优化，换手不可行时该期跳过沿用漂移权重并记录原因），成本 = 加权费率 × 单边换手；行业偏离按成员跟踪指数的 `benchmark_industry_weight`（SW 口径）加权合成 vs 目标指数，对照缺失显式置空 + 告警；池 <2 或对齐序列 <60 交易日 → needs_review 不输出推荐。
3. **门禁适配**：`credibility.py` 新增 `etf_portfolio_build` 族限制（同 `etf_selection`，仅指数族）；指定池混入债基等非指数族候选经门禁拒绝剔除。
4. **API**：`POST /api/v2/etf-portfolio/build`（幂等落库，支持 `persist=false` 干跑与全部参数）、`GET /api/v2/etf-portfolio/latest`（最近计算日各目标结果）、`GET /api/v2/etf-portfolio/{result_id}`；`rebalance_frequency` 非法值 422。
5. **前端**：ETF 组合构建页（`/etf-portfolio`，导航“ETF 组合构建”build 图标）—— 参数表单（目标/窗口/再平衡频率/权重上限/数量/规模/费率/换手上限）+ 指标卡（拟合 TE vs 单只最差候选/组合费率规模/回测换手成本）+ 推荐权重表 + 约束逐条回显表 + 拟合曲线（ECharts）+ 再平衡明细表 + 行业偏离对照表。
6. **冒烟验证**：真实库三目标 —— 沪深300（510300 0.551 + 110020 联接 0.449）computed：拟合 TE 0.64% < 单只最差候选 1.11%（验收成立），季度再平衡 53 次、样本外 TE 0.90%、累计单边换手 0.637、成本 0.018%，行业偏离 0（同指数成员合成=目标）；中证500（510500 0.545 + 010992 联接 0.455）computed：拟合 TE 0.80% < 1.55%，季度 18 次再平衡；创业板 needs_review（池内仅 159915 一只候选 <2，诚实降级不输出推荐）。三目标均幂等落库。
7. **测试**：新增 30 例（算法 19：候选筛选/权重约束/数量上限子集重解/池与序列降级/组合 TE 优于最差候选/阈值过滤/门禁拒绝/回测换手成本闭合/换手上限生效/行业偏离零偏离与不可得/observation 降级/幂等；API 10：happy path/干跑/未知目标/422×2/latest 前后/by-id/未知 id/幂等；DB 1：迁移建表 + 唯一约束，含 DuckDB 兼容），全量回归 727 passed，ruff 全绿，前端 tsc 零错误。
8. **已知边界**：候选限于在库 fund_nav 覆盖的样本 ETF/联接（全市场扩充需 ETF 净值拉取链路配套）；行业偏离对照仅沪深300/中证500/中证1000 可得（`benchmark_industry_weight` 覆盖范围），其余目标显式置空；风格偏离未单独输出（行业对照已覆盖粗粒度需求，随 P4E 指纹积累再评估）；换手上限不可行时该期不交易而非放宽约束（约束严格性优先）。
9. **审计修复**（2026-08-21 Phase 4 全量 CodeReview）：① 基数约束子集重解不可行时（如数量上限与换手上限冲突）改为返回 None 降级（静态构建 needs_review；回测该期沿用漂移权重 skipped），不再截断兜底 —— 原截断路径会静默绕过换手凸约束致回测指标失真；同步移除死代码 `_truncate_to_positions`；② 结果 id 改 str 序列化（前端类型同步 string 化）。新增 1 例约束组合不可行降级用例；顺带修正 P4D 测试净值种子口径（见 P4E 落地说明）。

---

## 5. P4E 基金公司画像频谱与经理团队画像（§6.2.6 + §12.4.5）✅ 已完成（2026-08-21）

**现状**：`manager_profile` 研究模板已存在（Phase 3），但无公司级聚合与频谱可视化（对比报告 1.5）。

**实现计划**：

1. **新模块 `analysis/company_profile.py`**：
   - **公司频谱**：按 `fund_company` 聚合在库基金 —— alpha/beta 散点谱（alpha 来自 `scoring_dimensions` Jensen 口径，beta 对沪深300）、风格分布（指纹风格维度聚合）、类型结构（基金族占比）、规模光谱。
   - **经理团队画像**：按 `fund_manager` 聚合 —— 任职年限加权 alpha、管理规模、风格稳定性（指纹漂移指标复用 `anomaly.py`）、同类排名中位数（`rank.py`）。
2. **API**：`GET /api/v2/companies/{company}/spectrum`、`GET /api/v2/managers/{manager_id}/profile`。
3. **前端**：公司频谱页（alpha-beta 气泡图，气泡=规模，颜色=基金族）；经理画像并入现有模板页扩展。

**验收标准**：

- [x] 样本覆盖的基金公司全部产出频谱（基金数 <3 的公司标“样本不足”observation）。
- [x] 经理画像与 `manager_profile` 模板输出字段口径一致，无重复计算。

**落地说明**（2026-08-21 实施记录）：

1. **算法**（`analysis/company_profile.py`，算法版本 0.1.0，只读聚合不落结果表，§15.2 未列 P4E 结果表）：公司频谱 = Jensen alpha/beta 频谱（与 `scoring_dimensions.compute_alpha` 同公式、Rf 读 settings，基准沪深300 序列只加载一次全池统一计算保证跨公司可比，对齐样本 <120 不硬算）+ 风格分布（最新指纹风格维度均值，无风格数据成员不摊派、显式告警）+ 类型结构（基金族占比，ETF/联接/指增标识优先于粗分类归族）+ 规模光谱；基金数 <3 标“样本不足”observation。经理画像 = 任期天数加权 alpha（tenure_days 优先，缺失按现任 365/离任 180 天兜底）+ 在管规模合计 + 风格稳定性（复用 `anomaly.detect_style_drift`，需 ≥4 期风格暴露历史才可评估，不足显式告警）+ 同类排名中位数（`rank.rank_in_category` 口径：近一年收益同 sub_category k/N，取分位中位数）；与 `manager_profile` 模板同源（tenure 表 + Jensen 评分口径 + anomaly/rank 复用，无重复计算链路）。
2. **API**：`GET /api/v2/companies/spectra`（全池概览：公司列表含样本不足标记 + 全池基金 alpha/beta 气泡数据）、`GET /api/v2/companies/{company_id}/spectrum`、`GET /api/v2/managers`（有在管基金的经理概览，任期加权 alpha 降序）、`GET /api/v2/managers/{manager_id}/profile`；未知实体一律 needs_review 不 500。
3. **前端**：公司频谱页（`/company-spectrum`，导航“公司频谱”spectrum 散点图标）—— 全池 alpha-beta 气泡图（ECharts scatter，气泡=规模、颜色=基金族）+ 单公司频谱（指标卡/类型结构/风格分布/成员表）+ 经理画像列表与详情（在管基金/历任记录/任期加权 alpha/同类排名/风格稳定性）。
4. **冒烟验证**：真实库 27 家公司 53 只基金 alpha/beta 全覆盖（53/53）；6 家 ≥3 只 computed（如中欧基金 4 只，alpha 中位数 8.08%），21 家样本不足 observation；风格分布因成员指纹无风格维度诚实降级告警；98 位有在管基金经理，Top 金梓才任期加权 alpha 19.87%、同类排名中位分位 1.0，风格稳定性因暴露历史不足 4 期诚实降级。
5. **测试**：新增 21 例（算法 14：alpha/beta 口径恢复与短序列降级/样本量门禁/风格聚合与类型结构/概览标记/任期加权 alpha 精确式/同类排名中位/风格降级/无现任 observation/未知实体；API 7：四端点 happy path + 空库/未知实体 needs_review），全量回归 748 passed，ruff 全绿，前端 tsc 零错误。顺带修正 P4D 测试净值种子口径（date i 净值需已含当日收益，与指数 daily_return 对齐）。
6. **已知边界**：风格分布依赖 `style_exposure_result`（在库仅 6 只基金有风格回归历史），多数公司显式置空；风格稳定性需 ≥4 期风格暴露历史，当前全部 0 只可评估，随增量积累解锁；beta 统一对沪深300（§12.4.5 既定口径），非权益类产品 beta 参考意义有限；无结果表持久化（只读即时计算，§15.2 未列）。

**Phase 4 全量审计**（2026-08-21，P4A–P4E 合并后 CodeReview）：确认 5 项问题均已修复 —— P4B 末窗口对齐、P4C 零权重窗口截断与成对矩阵对称性、P4D 子集重解兜底绕过换手约束、P4A–P4D 结果表 19 位大整数 ID 统一 str 序列化（前端类型同步，与 P4C 池 ID 审计修复约定对齐）；另实证确认 CVXPY 目标函数、无前视回测、幂等唯一键均正确。审计后全量回归 753 passed（新增 5 例审计回归用例），ruff 全绿，前端 tsc 零错误。

---

## 6. API / 前端 / 测试汇总

### 6.1 新增 v2 端点（全部 `APIResponse` + 门禁）

| 端点 | 批次 |
| --- | --- |
| `GET /index-funds/compare`、`POST /index-funds/selection` | P4A |
| `POST /analysis/bond-factors/{fund_code}` | P4B |
| `POST /portfolios/{pool_id}/analysis`、`POST /portfolios/{pool_id}/packet` | P4C |
| `POST /etf-portfolio/build`、`GET /etf-portfolio/{result_id}` | P4D |
| `GET /companies/{company}/spectrum`、`GET /managers/{manager_id}/profile` | P4E |

### 6.2 前端新页面（§14.2 后续页面清单对齐）

- ETF 对比/优选页（P4A）、债基风险扫描页（P4B）、组合管理页扩展（P4C）、ETF 组合构建页（P4D）、公司频谱页（P4E）。

### 6.3 测试策略

- 每模块单测：算法边界（空序列/短窗口/单基金组/并列分位）、门禁降级路径（跨类型调用 → needs_review）、upsert 幂等。
- API 层测试：延续 P4.3-5 模式（happy path + 422 + 降级用例）。
- 真实库冒烟：53 只样本全量跑新模块，结论状态分布登记进落地说明。
- 全量回归 + `ruff check src/ tests/ scripts/` 全绿作为每批次出口条件。

---

## 7. 执行批次与依赖

| 批次 | 内容 | 依赖 | 可并行 |
| --- | --- | --- | --- |
| **B1** | P4A 指数基金优选 + P4C 组合穿透分析 | 无（数据底座已就绪） | 互相并行 |
| **B2** | P4B 债基因子暴露（含指纹债维度回填） | 无（factor_return 已就绪） | B1 |
| **B3** | P4D ETF 组合构建 | P4A（跟踪质量口径复用） | B2 |
| **B4** | P4E 公司/经理画像频谱 + Phase 4 全量回归验收 | B1–B3（alpha/指纹结果积累） | — |

**Phase 4 完成标准**（对照 §12.4 五条 + §17 每期一个闭环）：

- [x] 债基金因子暴露：12 只债基按四模板产出粗粒度因子暴露，方向符合已知策略（P4B，2026-08-20）
- [x] 组合分析：有权重组合产出收益/回撤/穿透重叠 + 组合研究包可导出（P4C，2026-08-20）
- [x] ETF 组合构建：二次规划推荐 + 约束解释 + 再平衡成本闭环（P4D，2026-08-21）
- [x] 公司/经理画像：频谱页可用（P4E，2026-08-21）
- [x] 指数基金优选：同指数对比表 + 综合评分在样本 11 只指数类产品上闭环（P4A，2026-08-20）
- [x] 全量回归通过、新端点 API 测试齐备、门禁对 53 只样本零误判（748 passed，P4A–P4E 全部批次验收完成，Phase 4 闭环）

---

## 8. 顺带补强与长期欠账（不占批次登记）

| 项 | 出处 | 处置 |
| --- | --- | --- |
| 组合优化子项（CVXPY 最小化波动/控制回撤，约束逐条回显） | §6.3.9 第 4 条，P4C 可裁剪项 | P4C 本轮未实施（范围控制），登记欠账，可随 P4D CVXPY 基建一并落地 |
| 无风险利率接真实货基指数曲线，统一 Sharpe/Alpha Rf 口径 | 对比报告 2.1#2 + 2.2#2、P4.0-3 | Phase 4 中期顺带：货基指数可 fetch，时序 Rf 切换需版本化（影响所有 Sharpe/Alpha 结论可信度） |
| 滚动月度胜率 | 对比报告 2.2#4 | ✅ 已闭环（P4.0-2 `win_rate`）；滚动窗口变体可选随 nav_metrics 补强 |
| 类型内排名 k/N | 对比报告 2.2#5 | ✅ 已闭环（P4.0-2 `analysis/rank.py`） |
| 集中度未排序 / 换手率半年报假设两处 bug | 对比报告 2.1#1/#3 | ✅ 已随 P4.2-3 批次修复 |
| 交易能力经理历史/同类对比（§6.2.4 扩展） | pre_phase4_plan §4.6 | 可选，随 P4E 经理画像一并评估 |
| 最大无盈利天数 / 涨跌弹性比（up/down capture） | 对比报告 2.2#1/#3 | 可选（需求书未明确），随 nav_metrics/评分增强一次遍历加入 |
| AA/信用下沉因子长历史 | pre_phase4_plan P4.1-3/5 边界 | 随每日增量自然积累，序列 ≥1 年后在 P4B 开启信用下沉回归开关 |
| 持有人结构数据源、动态归因真日度滚动、失败案例库实体化、Tool API dry-run/JSONL | — | 维持 pre_phase4_plan §4.6 登记：Phase 5 |

**对比报告明确「不做/不照搬」项**（§3.3，维持结论）：ETF 组合构建爬山法（改用 CVXPY 凸优化）、研究报告库 + PDF 阅读（§2.3 定位排除）、核心库/备选池分层命名（fund_pool 已覆盖逻辑）、抱团度/内部认可度/规模逆向（需求书未提）、DES 加密/权限/审计（与单用户本地定位冲突，§10.4）。

---

## 9. 风险与对策（§17 对齐）

| 风险 | 对策 |
| --- | --- |
| AA 因子序列深度不足导致债基回归不稳 | 默认因子集剔除 AA/下沉；R² 与窗口覆盖度进门禁，不足即 needs_review |
| 同跟踪指数样本内产品过少（分组 <2） | 全市场 etf_profile 可扩候选；仍不足时输出 observation 不做排序 |
| ETF 组合优化过拟合历史样本 | 协方差收缩 + 样本外段验证 + 换手/数量约束 |
| 模拟持仓穿透污染组合结论 | `estimated_*` 隔离展示，组合默认结论只用披露口径 |
| 范围膨胀 | 每批次一个验收闭环，未通过不进下一批；P4C 优化子项、P4E 为可裁剪项 |
