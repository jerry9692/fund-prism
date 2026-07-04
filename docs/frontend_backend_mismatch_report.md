# 前后端版本不一致问题记录

> **生成时间：** 2026-07-04
> **背景：** rebase 合并时，前端采用远端版本（新设计系统架构重建），后端采用本地版本（Phase 2 业务功能增强）。本文档记录两者版本不一致产生的冲突及功能缺口。

---

## 一、问题总览

| 编号 | 严重级别 | 问题 | 影响范围 |
|------|---------|------|---------|
| P1 | 🔴 严重 | 动态归因列表端点路径不匹配 | DynamicAttributionPage、EvidencePage |
| P2 | 🔴 严重 | 动态归因数据结构字段名不匹配 | DynamicAttributionPage |
| P3 | 🟠 重要 | 3 个 review 业务端点前端无界面入口 | FundReviewPage |
| P4 | 🟠 重要 | 动态归因就绪检查前端未集成 | DynamicAttributionPage |
| P5 | 🟡 次要 | 实验结果记录端点前端未调用 | ExperimentsPage |
| P6 | 🟡 次要 | 本地新增前端组件可能与新设计系统不兼容 | 5 个新增组件/hook |
| P7 | 🟡 次要 | 审核历史端点前端未调用 | FundReviewPage |

---

## 二、严重问题（功能不可用）

### P1. 动态归因列表端点路径不匹配（404 错误）

**前端调用路径：**
```
GET /api/v2/analysis/dynamic-attribution/{fundCode}
```
- 文件：`frontend/src/api/client.ts` 第 744-746 行，`listDynamicAttribution` 函数
- 使用 path parameter 传递 `fundCode`

**后端实际路径：**
```
GET /api/v2/analysis/return-attribution?fund_code=xxx&limit=10
```
- 文件：`src/fund_research/api/v2_router.py` 第 2037 行，`list_return_attribution` 函数
- 使用 query parameter 传递 `fund_code`

**差异分析：**
- 路径名不同：`dynamic-attribution/{fundCode}` vs `return-attribution`
- 参数传递方式不同：path param vs query param

**影响：**
- `DynamicAttributionPage.tsx` 第 101 行调用 `api.listDynamicAttribution(fundCode)` 加载归因记录列表 → 直接 404
- `EvidencePage.tsx` 第 163 行同样调用 `api.listDynamicAttribution(fundCode)` → 直接 404

**原因：**
本地后端将端点命名为 `return-attribution`（强调收益归因），远端前端基于 `dynamic-attribution`（动态归因）命名设计。两者在 rebase 后未对齐。

---

### P2. 动态归因数据结构字段名不匹配（数据无法显示）

即使 P1 的路径问题修复，后端返回的数据结构与前端 TypeScript 接口也不匹配。

**后端返回字段**（`v2_router.py` 第 2059-2078 行）：

遵循 project_memory 中"Estimated results must use the `estimated_` prefix"约定，所有归因字段均使用 `estimated_` 前缀：

| 后端字段 | 前端期望字段 | 匹配 |
|---------|------------|------|
| `estimated_total_portfolio_return` | `total_return` | ❌ |
| `estimated_total_benchmark_return` | （无对应字段） | — |
| `estimated_total_allocation_effect` | `allocation_return` | ❌ |
| `estimated_total_selection_effect` | `stock_selection_return` | ❌ |
| `estimated_total_interaction_effect` | `interaction_return` | ❌ |
| `estimated_total_residual` | `residual` | ❌ |
| `estimated_residual_ratio` | `residual_pct` | ❌ |
| `benchmark_symbol` | （无对应字段） | — |
| `uses_simulated_holdings` | （无对应字段） | — |
| （无） | `beta_return` | ❌ 缺失 |
| （无） | `sector_rotation_return` | ❌ 缺失 |
| （无） | `convertible_bond_return` | ❌ 缺失 |
| （无） | `ipo_return` | ❌ 缺失 |
| （无） | `algorithm_name` | ❌ 缺失 |
| （无） | `algorithm_version` | ❌ 缺失 |
| （无） | `parameters` | ❌ 缺失 |
| （无） | `detail` | ❌ 缺失 |

**影响：**
- `DynamicAttributionPage.tsx` 的指标卡（第 269-286 行）和归因柱状图（第 138-168 行）全部显示为空值或 0
- 前端 `DynamicAttributionResult` 接口（`client.ts` 第 409-432 行）定义了 8 个归因收益字段，后端只返回 5 个且字段名全部不同

**原因：**
- 后端遵循 estimated 隔离约定，归因结果字段使用 `estimated_` 前缀
- 前端接口基于旧版后端数据结构定义，未适配 `estimated_` 前缀
- 后端 `list_return_attribution` 端点未返回 `algorithm_name`、`algorithm_version`、`parameters` 等元数据字段，而前端页面需要展示这些信息（`DynamicAttributionPage.tsx` 第 78 行）

---

## 三、重要问题（功能缺失）

### P3. 3 个 review 业务端点前端无界面入口

后端实现了 4 个业务级 review 端点（需求 §5.5.3），但前端完全没有调用：

| 后端端点 | 功能 | 前端调用 |
|---------|------|---------|
| `POST /review/lock-securities` | 锁定/排除特定证券（模拟持仓） | ❌ 未调用 |
| `POST /review/adjust-benchmark` | 调整基金基准（动态归因） | ❌ 未调用 |
| `POST /review/annotate-confidence` | 标注/调整置信度 | ❌ 未调用 |
| `GET /review/history/{fund_code}` | 查看审核历史 | ❌ 未调用 |

**前端现状：**
`FundReviewPage.tsx` 只使用了通用的 reviewer-annotations CRUD API：
- `api.createReviewerAnnotation` — 创建通用标注（note/lock/exclude/approve）
- `api.getFundReviewStatus` — 获取基金审核状态
- `api.deleteReviewerAnnotation` — 删除标注

**功能差距：**
- 前端无法锁定/排除特定证券（只能做基金级别的标注）
- 前端无法调整基金基准（无法覆盖默认 benchmark）
- 前端无法针对特定算法结果调整置信度（只能做通用备注）
- 后端的 3 个业务端点内部都委托给 `create_annotation` 实现，但携带了 `detail` 字段（如 `security_code`、`benchmark_symbol`、`custom_weights`、`adjusted_status`），前端表单不支持填写这些结构化字段

**影响：**
project_memory 中明确要求的 5 个关键 API 端点，有 3 个（lock-securities、adjust-benchmark、annotate-confidence）已完成后端实现但前端无入口，用户无法通过界面使用这些功能。

---

### P4. 动态归因就绪检查前端未集成

后端实现了动态归因就绪检查机制，但前端未调用：

| 后端端点 | 功能 | 前端调用 |
|---------|------|---------|
| `GET /experiments/dynamic-attribution/readiness` | 检查动态归因真实样本是否具备运行条件 | ❌ 未调用 |
| `POST /experiments/dynamic-attribution/from-ready` | 从就绪样本批量创建归因 | ❌ 未调用 |

**前端现状：**
`DynamicAttributionPage.tsx` 第 122-134 行的 `handleRun` 直接调用 `api.runReturnAttribution`，不检查就绪状态。

**影响：**
- 用户可能在数据不满足条件时（如 NAV 连续性不足、持仓不完整、基准权重覆盖不足）运行归因，产生无效结果
- 无法批量从就绪样本创建归因（只能逐个基金手动运行）
- project_memory 要求"动态归因必须显式检查数据质量警告"，前端未展示就绪检查结果

---

## 四、次要问题

### P5. 实验结果记录端点前端未调用

| 后端端点 | 功能 | 前端调用 |
|---------|------|---------|
| `POST /experiments/{experiment_id}/results` | 手动记录实验结果 | ❌ 未调用 |

**影响：** 前端 ExperimentsPage 无法手动补录实验结果，只能通过 `run`/`rerun` 自动产生结果。

---

### P6. 本地新增前端组件可能与新设计系统不兼容

rebase 时保留了本地新增的前端组件，但前端采用了远端的新设计系统架构：

| 新增文件 | 类型 | 潜在风险 |
|---------|------|---------|
| `DateRangePicker.tsx` | 组件 | 可能引用旧 CSS 变量或已删除的组件 |
| `EvidenceList.tsx` | 组件 | 可能引用旧 CSS 变量 |
| `PeriodSelector.tsx` | 组件 | 可能引用旧 CSS 变量 |
| `RadarChart.tsx` | 组件 | 可能引用旧 CSS 变量或 ChartWrapper API 变更 |
| `useReviewStatus.ts` | Hook | 可能调用已变更的 API 接口 |

**风险点：**
- 远端进行了"前端架构重建 — 设计系统 + AppShell"，CSS 变量名、组件 API 可能已变更
- 远端删除了 11 个"死代码遗留组件"（batch 4 cleanup），本地新增组件可能引用了被删除的组件
- 需逐一检查这些组件是否：引用了已删除的组件（如 `FundSearch`、`NavBar`）、使用了旧 CSS 变量名、与新的 `display`/`data` 组件库 API 不兼容

---

### P7. 审核历史端点前端未调用

| 后端端点 | 功能 | 前端调用 |
|---------|------|---------|
| `GET /review/history/{fund_code}` | 获取基金跨模块审核历史 | ❌ 未调用 |

**前端现状：** `FundReviewPage.tsx` 通过 `api.getFundReviewStatus` 获取审核状态和标注列表，但未调用专用的 `review/history` 端点。

**影响：** 功能上可能有重叠（`getFundReviewStatus` 也返回 annotations），但 `review/history` 端点可能提供更完整的跨模块历史记录。

---

## 五、前后端端点对照表

### v2 端点完整对照

| 后端端点 (v2_router.py) | 前端 client.ts 函数 | 状态 |
|------------------------|-------------------|------|
| `GET /experiments` | `listExperiments` | ✅ 匹配 |
| `POST /experiments` | `createExperiment` | ✅ 匹配 |
| `GET /experiments/{id}` | `getExperiment` | ✅ 匹配 |
| `POST /experiments/{id}/run` | `runExperiment` | ✅ 匹配 |
| `POST /experiments/{id}/rerun` | `rerunExperiment` | ✅ 匹配 |
| `DELETE /experiments/{id}` | `deleteExperiment` | ✅ 匹配 |
| `POST /experiments/{id}/results` | — | ❌ 前端未调用 |
| `GET /experiments/dynamic-attribution/readiness` | — | ❌ 前端未调用 |
| `POST /experiments/dynamic-attribution/from-ready` | — | ❌ 前端未调用 |
| `GET /validation/p2b/latest` | `getLatestP2BValidationReport` | ✅ 匹配 |
| `GET /validation/p2b/reports` | `listP2BValidationReports` | ✅ 匹配 |
| `GET /validation/p2b/reports/{id}` | `getP2BValidationReport` | ✅ 匹配 |
| `GET /validation/p2b/compare` | `compareP2BValidationReports` | ✅ 匹配 |
| `POST /validation/p2b/rerun` | `rerunP2BValidationReport` | ✅ 匹配 |
| `GET /validation/p2b/tasks/{id}` | `getP2BValidationTask` | ✅ 匹配 |
| `POST /analysis/scoring` | `runScoring` | ✅ 匹配 |
| `GET /analysis/scoring/{version}` | `getScoring` | ✅ 匹配 |
| `POST /analysis/scoring/backtest` | `runScoringBacktest` | ✅ 匹配 |
| `GET /analysis/scoring/backtest` | `listScoringBacktests` | ✅ 匹配 |
| `GET /analysis/scoring/backtest/{id}` | `getScoringBacktest` | ✅ 匹配 |
| `GET /analysis/simulated-holding` | `listSimulatedHolding` | ✅ 匹配 |
| `POST /analysis/simulated-holding` | `runSimulatedHolding` | ✅ 匹配 |
| `POST /analysis/return-attribution` | `runReturnAttribution` | ✅ 匹配 |
| `GET /analysis/return-attribution` | `listDynamicAttribution` | ❌ **路径不匹配** (P1) |
| `POST /review/lock-securities` | — | ❌ 前端未调用 (P3) |
| `POST /review/adjust-benchmark` | — | ❌ 前端未调用 (P3) |
| `POST /review/annotate-confidence` | — | ❌ 前端未调用 (P3) |
| `GET /review/history/{fund_code}` | — | ❌ 前端未调用 (P7) |
| `POST /reviewer-annotations` | `createReviewerAnnotation` | ✅ 匹配 |
| `GET /reviewer-annotations` | `listReviewerAnnotations` | ✅ 匹配 |
| `GET /reviewer-annotations/{id}` | `getReviewerAnnotation` | ✅ 匹配 |
| `PATCH /reviewer-annotations/{id}` | `updateReviewerAnnotation` | ✅ 匹配 |
| `DELETE /reviewer-annotations/{id}` | `deleteReviewerAnnotation` | ✅ 匹配 |
| `GET /reviewer-annotations/funds/{code}/status` | `getFundReviewStatus` | ✅ 匹配 |

**统计：** 33 个后端端点中，25 个匹配，1 个路径不匹配（P1），7 个前端未调用。

---

## 六、修复建议

### P1 修复（路径不匹配）
二选一：
- **方案 A（改前端）：** 将 `client.ts` 的 `listDynamicAttribution` 改为 `GET /api/v2/analysis/return-attribution?fund_code=${fundCode}`
- **方案 B（改后端）：** 在 `v2_router.py` 新增 `GET /analysis/dynamic-attribution/{fund_code}` 端点，或添加路径别名

### P2 修复（字段不匹配）
二选一：
- **方案 A（改前端）：** 将 `DynamicAttributionResult` 接口字段改为 `estimated_*` 前缀，并移除后端不返回的字段（`beta_return`、`sector_rotation_return` 等），或在后端补充这些字段
- **方案 B（改后端）：** 在 `list_return_attribution` 端点中补充前端期望的字段（`algorithm_name`、`algorithm_version` 等），并考虑同时返回非前缀和前缀两套字段名

### P3 修复（review 端点无界面）
在 `FundReviewPage.tsx` 中增加 3 个业务操作区域：
- 证券锁定/排除表单（调用 `POST /review/lock-securities`，需 `security_code`、`action`、`lock_weight` 字段）
- 基准调整表单（调用 `POST /review/adjust-benchmark`，需 `benchmark_symbol`、`custom_weights` 字段）
- 置信度标注表单（调用 `POST /review/annotate-confidence`，需 `original_status`、`adjusted_status` 字段）

### P4 修复（就绪检查集成）
在 `DynamicAttributionPage.tsx` 的 `handleRun` 中，先调用 `GET /experiments/dynamic-attribution/readiness` 检查就绪状态，未就绪时展示警告并阻止运行。

### P6 修复（组件兼容性）
逐一检查 5 个新增组件，确认：
- 是否引用了已删除的组件（`FundSearch`、`NavBar`）
- CSS 变量名是否与远端设计系统一致（如 `--surface-raised`、`--accent`、`--border-hairline` 等）
- 是否使用了新的 `display`/`data` 组件库 API
