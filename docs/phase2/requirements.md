# Fund Prism 第二期需求书

版本: v0.1  
日期: 2026-06-08  
状态: Draft  
前置依据: [v0.4 总体需求书](../../AI-oriented开源个人基金研究平台需求书_v0.4.md) | [Phase 1 完成报告](../phase1/completion_report.md)

## 1. 文档定位

本文档定义 Fund Prism 第二期的建设范围。二期在 Phase 1 的可信数据底座和基础分析能力之上，引入三个新维度：

1. **高不确定性算法受控引入**：模拟持仓、动态归因、综合评分——每个模块必须先通过回测阈值和置信度门禁，才能进入产品化视图。
2. **算法实验与版本管理**：为研究者提供参数版本、回测对比和手动校验能力。
3. **前端界面**：提供可扩展的 Web UI，覆盖基金研究、算法实验和日常看板。

## 2. 一期现状回顾

Phase 1 已交付：

| 模块 | 状态 |
|------|------|
| 21 张 ORM 表 + Alembic 迁移 | ✅ |
| AKShare 适配器 13 个数据源 | ✅ |
| CLI: init / serve / check-data / update / export | ✅ |
| 4 个分析模块（收益风险/持仓/风格暴露/静态归因） | ✅ |
| 7 个 Tool API（profile / nav-metrics / holdings / screen / exposure / packet / diff） | ✅ |
| Research Packet + Evidence 体系 | ✅ |
| 99 测试 + ruff 零告警 | ✅ |

## 3. 二期目标

### 3.1 总目标

在 Phase 1 可信底座之上，引入模拟持仓、动态归因和综合评分三个高不确定性算法，全部通过实验管理、回测验证和手动校验进行受控引入。同时建设前端界面，让个人研究者可以通过 Web 浏览器直接使用平台全部能力。

### 3.2 业务目标

1. 提供模拟持仓实验模块，支持研究员评估算法在不同基金上的表现边界。
2. 在静态归因基础上引入动态收益拆解，保留残差和置信度。
3. 建设可解释、可配置、可回测的综合评分体系。
4. 提供算法实验版本管理，支持参数对比和结果复现。
5. 建设前端 Web UI，覆盖一期全部 API 和二期新增功能。
6. 支持研究员手动锁定/排除证券、调整基准、标记低置信度结论。

### 3.3 非目标

1. 不做基金画像指纹和相似基金搜索（三期）。
2. 不做异常发现和风格漂移监控（三期）。
3. 不做基金池持久化管理和跟踪提醒（三期）。
4. 不做 ETF/指数/债基扩展（四期）。
5. 不做 Agent 自动化研究（五期）。
6. 不做多用户、权限和云端同步。
7. 前端不做移动端适配（一期目标为桌面 Web）。

## 4. 前端需求

### 4.1 总体要求

二期必须提供可通过浏览器访问的 Web 界面，覆盖全部 7 个 Tool API 和二期新增功能。

**技术选型要求**：
- 框架不锁定（推荐 React/Vue/Svelte 任一），但需要明确说明选择理由和替代方案
- 前端代码独立于后端，放在 `frontend/` 目录
- 构建产物可通过 FastAPI 静态文件服务或独立 dev server 运行
- 组件化设计，每个页面模块可独立替换

**可扩展性要求**：
- 每个页面使用独立路由，新增页面不牵动已有页面
- 数据获取层封装为统一的 API client 模块，切换后端 URL 只需改一处
- 图表组件使用通用接口，支持切换底层图表库（ECharts/Plotly/D3）
- CSS/主题变量集中管理，支持后续换肤

### 4.2 页面清单

#### 4.2.1 一期已有 API 对应页面

| 页面 | 路由 | 对应 API | 核心内容 |
|------|------|---------|----------|
| 首页/研究看板 | `/` | screen_funds 汇总 | 样本基金状态、最近更新、数据质量摘要 |
| 基金检索与筛选 | `/funds` | screen_funds | 筛选条件面板 + 结果表格 + 排序 |
| 基金详情 | `/funds/:code` | profile + nav-metrics | 基本信息、净值曲线、多区间指标卡片 |
| 持仓分析 | `/funds/:code/holdings` | holdings | 持仓表格、行业分布饼图、持仓变动对比 |
| 风格暴露与归因 | `/funds/:code/exposure` | exposure | 风格暴露柱状图、归因瀑布图、残差展示 |
| 研究包 | `/funds/:code/packet` | packet | 结构化阅读视图、Markdown 渲染、证据列表 |
| 研究包对比 | `/funds/:code/diff` | diff | 左右双栏对比、变化高亮 |
| 数据质量 | `/data-quality` | API metadata | 数据源状态、覆盖率、更新日志 |

#### 4.2.2 二期新增页面

| 页面 | 路由 | 对应 API | 核心内容 |
|------|------|---------|----------|
| 算法实验管理 | `/experiments` | 新增 API | 实验列表、参数版本、回测指标对比 |
| 模拟持仓实验 | `/funds/:code/simulated` | simulated_holding | 模拟持仓明细、拟合误差、置信度分布 |
| 综合评分 | `/funds/:code/scoring` | scoring | 分项得分雷达图、权重配置、排名 |
| 评分回测 | `/scoring/backtest` | scoring | 分层回测收益曲线、IC 分析 |
| 手动校验 | `/funds/:code/review` | 新增 API | 锁定/排除证券、调整基准、标注置信度 |

### 4.3 通用前端组件

以下组件需在各页面复用：

| 组件 | 用途 |
|------|------|
| `NavBar` | 顶部导航：首页/基金/实验/数据质量 |
| `FundSearch` | 基金代码/名称搜索框 + 下拉建议 |
| `MetricCard` | 指标数值卡片（含置信度标签） |
| `ConfidenceBadge` | 结论状态徽章（fact/computed/estimated/observation/needs_review） |
| `EvidenceList` | 证据链列表（可展开查看来源、日期、置信度） |
| `WarningBanner` | 警告横幅（数据缺失/估计结果/低置信度） |
| `DisclaimerFooter` | 免责声明固定底栏 |
| `DateRangePicker` | 日期区间选择器 |
| `PeriodSelector` | 多区间切换器（YTD/1M/3M/6M/1Y/3Y/5Y） |
| `DataTable` | 通用数据表格（排序、筛选、分页） |

## 5. 算法模块

### 5.1 模拟持仓实验

#### 5.1.1 需求

v0.4 §6.2.2 阶段定位：

> 二期：在通过披露期回测阈值后，作为主动权益分析页的可选估计视图。

#### 5.1.2 算法设计

**输入**：报告期披露持仓、基金日度净值、股票日行情、基金合同约束

**方法**：
1. 候选池构建：上期持仓 + 同经理偏好股 + 行业龙头 + 定报新增股 + 风格相近股
2. 约束优化（CVXPY）：最小化模拟组合收益与真实净值收益的跟踪误差
3. 稀疏约束：控制持仓数量 ≤ 30 只
4. 换手约束：单期权重变化 ≤ 上期持仓的 50%
5. 行业约束：模拟持仓行业分布与最近披露持仓偏离 ≤ 10%

**披露期回测**：用半年度/年度报告的全部持仓验证模拟算法精度。

**输出**：
- 模拟持仓明细（代码/名称/权重/置信度/来源标记）
- 拟合误差（日度 RMSE + 跟踪误差）
- 行业分布对比（模拟 vs 披露）
- 重仓股召回率
- 失败原因和低置信度标记

#### 5.1.3 验收

1. 披露期回测：行业分布相关性 > 0.7，前十大重仓股召回率 > 50%
2. 拟合误差 < 同基金历史净值波动率的 2 倍
3. 不达标基金自动标记 `needs_review`，不在页面上展示"模拟持仓"
4. 所有输出使用 `estimated_*` 字段前缀
5. 页面顶部显著标注"模拟持仓为模型估计，不代表基金真实持仓"

#### 5.1.4 新增 API

```
POST /api/v2/analysis/simulated-holding
```

请求：
```json
{
  "fund_code": "000001",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "candidate_pool": "auto",
  "max_positions": 30,
  "sparse_lambda": 0.1,
  "turnover_lambda": 0.5
}
```

返回：`APIResponse[SimulatedHoldingResult]`

### 5.2 动态收益拆解

#### 5.2.1 需求

v0.4 §12.2：

> 收益拆解增强：在静态归因基础上引入估计动态归因，但必须使用 `estimated_*` 字段并保留残差。

#### 5.2.2 算法设计

在 Phase 1 静态归因基础上增强：

**新增能力**（基于模拟持仓）：
1. 月度调仓模拟：假设每月初按模拟持仓调仓
2. 打新收益估算：基于新股中签率和上市首日收益
3. 转债收益拆分：从模拟持仓中分离转债贡献
4. 隐形收益分析：残差 = 真实收益 - 模拟收益 - 打新 - 转债

**输出**：
- 季度/月度收益瀑布图
- 各收益来源历史堆叠图
- 隐形收益占比和趋势
- `estimated_*` 字段标记所有非披露数据推导部分

#### 5.2.3 验收

1. 残差占比 < 50%（超过则标记不可解释）
2. 所有拆解结果使用 `estimated_*` 字段
3. 残差过高时页面提示而非强行归因
4. 保留 Phase 1 静态归因结果并列展示

#### 5.2.4 新增 API

```
POST /api/v2/analysis/return-attribution
```

### 5.3 综合评分

#### 5.3.1 需求

v0.4 §6.2.5 阶段定位：

> 综合评分基础版应放在二期，并且必须先完成评分回测、权重解释、缺失值惩罚、估计结果隔离和版本管理。

#### 5.3.2 评分维度

按 v0.4 定义的 8 个维度，二期仅使用确定性指标和通过回测的估计指标：

| 维度 | 指标来源 | 数据可靠性 |
|------|----------|-----------|
| 收益能力 | nav_metrics (computed) | 高 |
| 风险控制 | nav_metrics (computed) | 高 |
| Alpha 能力 | 静态归因选股收益 + 行业配置收益 (observation) | 中 |
| 交易能力 | 持仓变动估算换手率 (estimated) | 低 — 权重减半 |
| 风格稳定性 | 风格暴露变化标准差 (observation) | 中 |
| 规模适配 | fund_scale + inception_date (computed) | 高 |
| 团队稳定性 | manager_tenure + 经理变更频率 (computed) | 高 |
| 持有人稳定性 | holder_structure + 机构集中度 (computed) | 高 |

#### 5.3.3 评分方法

1. **指标标准化**：按基金类别分组，计算 z-score 或分位数（默认分位数）
2. **权重配置**：
   - 默认权重（偏长期）：收益 20% / 风险 20% / Alpha 15% / 交易 5% / 风格 15% / 规模 10% / 团队 10% / 持有人 5%
   - 支持研究员自定义权重 JSON
   - 支持策略模板（"稳健型"偏回撤控制，"进取型"偏收益和 Alpha）
3. **稳健处理**：极值缩尾 1%/99%，缺失值惩罚（缺失维度权重归零并扣总分 5%），样本期 < 3 年降权 50%
4. **估计隔离**：`estimated` 级别指标权重 × 0.5，总分标记"含估计成分"
5. **回测验证**：按评分分 5 组，计算各组未来 1 年收益/回撤/夏普的单调性

#### 5.3.4 输出

- 总分 + 8 项分项得分
- 雷达图
- 同类排名（分位数）
- 扣分原因列表
- 评分版本 + 回测标识
- 自定义权重对比

#### 5.3.5 验收

1. 分层回测：高分组未来收益 > 低分组（单边检验）
2. 评分可解释到每个指标层
3. 评分版本保存，历史评分不被静默覆盖
4. 依赖 `estimated_*` 的评分标注估计来源
5. 不足 3 年数据的基金显著降低权重并标明

#### 5.3.6 新增 API

```
POST /api/v2/analysis/scoring
GET  /api/v2/analysis/scoring/:score_version
POST /api/v2/analysis/scoring/backtest
```

### 5.4 算法实验管理

#### 5.4.1 需求

v0.4 §12.2：

> 算法实验管理：参数版本、样本集、回测指标、模型适用范围、失败案例库。

#### 5.4.2 功能

1. **实验定义**：每个实验记录算法名称、参数版本、样本基金范围、回测区间
2. **结果记录**：回测指标（RMSE/召回率/IC）、图表快照、失败样本
3. **版本对比**：同一算法的不同参数版本对比
4. **失败案例库**：自动收集不达标基金，按原因分类

#### 5.4.3 新增 API

```
POST   /api/v2/experiments              # 创建实验
GET    /api/v2/experiments              # 实验列表
GET    /api/v2/experiments/:id          # 实验详情 + 结果
POST   /api/v2/experiments/:id/rerun   # 重跑实验
DELETE /api/v2/experiments/:id          # 删除实验
```

### 5.5 研究员手动校验

#### 5.5.1 需求

v0.4 §12.2：

> 研究员手动校验能力：锁定/排除证券、调整基准、标记低置信度结论。

#### 5.5.2 功能

1. **证券锁定/排除**：在模拟持仓候选池中手动标记特定证券为"必选"或"排除"
2. **基准调整**：为归因分析手动指定基准组合
3. **置信度标注**：手动上调/下调某个算法结论的置信度，附带原因
4. **校验记录**：每次手动调整保存为 Evidence 记录

#### 5.5.3 新增 API

```
POST   /api/v2/review/lock-securities    # 锁定/排除证券
POST   /api/v2/review/adjust-benchmark   # 调整基准
POST   /api/v2/review/annotate-confidence # 标注置信度
GET    /api/v2/review/history/:fund_code  # 校验历史
```

## 6. 数据库补充

### 6.1 新增表

| 表 | 用途 |
|----|------|
| `simulated_holding_result` | 模拟持仓结果（明细/拟合误差/置信度） |
| `dynamic_attribution_result` | 动态收益拆解结果 |
| `scoring_result` | 评分结果（总分/分项/权重/版本） |
| `scoring_backtest` | 评分回测结果（分组收益/IC 序列） |
| `algorithm_experiment` | 算法实验定义和状态 |
| `experiment_result` | 实验回测指标和失败样本 |
| `reviewer_annotation` | 研究员手动校验记录 |

### 6.2 现有表补充字段

| 表 | 新增字段 |
|----|---------|
| `static_attribution_result` | `conclusion_status` 已存在，确认使用 |
| `style_exposure_result` | 无需改动 |

## 7. 前端技术方案建议

| 层次 | 推荐方案 | 理由 |
|------|---------|------|
| 框架 | React + TypeScript | 生态最成熟，组件库丰富 |
| 构建 | Vite | 开发体验好，构建快 |
| 路由 | React Router v7 | 独立路由，新增页面不牵动现有 |
| 图表 | Recharts / ECharts | Recharts 适合简单图表，ECharts 适合复杂交互 |
| CSS | Tailwind CSS + CSS Variables | Tailwind 效率高，CSS Variables 支持主题切换 |
| API 层 | 独立 `src/api/` 模块 | 封装 fetch + APIResponse 类型 |
| 状态 | React Context + useReducer | 轻量，不需要 Redux |
| 测试 | Vitest + React Testing Library | 与 Vite 一致生态 |

**备选方案**：Vue 3 + Nuxt + ECharts（如果团队更熟悉 Vue）。

**可替换性保证**：
- `src/api/client.ts` 封装所有 API 调用，替换后端 URL 只需修改 `BASE_URL` 常量
- 图表组件通过 `ChartWrapper` 封装，内部切换 Recharts → ECharts 不影响页面
- 页面组件只接收 props 不直接访问全局状态，新页面可以独立开发

## 8. 交付物

| 编号 | 交付物 | 路径 |
|------|--------|------|
| P2-1 | 模拟持仓算法 | `src/fund_research/analysis/simulated_holding.py` |
| P2-2 | 动态收益拆解 | `src/fund_research/analysis/dynamic_attribution.py` |
| P2-3 | 综合评分 | `src/fund_research/analysis/scoring.py` |
| P2-4 | 算法实验管理 | `src/fund_research/experiments/` |
| P2-5 | 研究员校验 | `src/fund_research/review/` |
| P2-6 | v2 Tool API | `src/fund_research/api/v2_router.py` |
| P2-7 | 数据库迁移 | `src/fund_research/db/migrations/versions/` |
| P2-8 | 前端 Web UI | `frontend/` |
| P2-9 | 测试用例 | `tests/` |
| P2-10 | 二期文档 | `docs/phase2/` |

## 9. 里程碑

### M1: 算法核心闭环（3-4 周）

1. 模拟持仓算法 + 披露期回测
2. 动态归因算法（基于模拟持仓结果）
3. 综合评分算法（分项指标 + 权重 + 标准化）

退出标准：三个算法均对 30 只样本基金运行成功，模拟持仓回测结果写入报告。

### M2: 实验管理与校验（2-3 周）

1. 算法实验 CRUD + 结果记录
2. 证券锁定/排除 + 基准调整
3. 评分回测框架

退出标准：可创建实验、对比参数版本、记录失败样本。

### M3: 前端界面（3-4 周）

1. 一期 8 个页面（API 已有）
2. 二期 5 个新增页面
3. 通用组件库

退出标准：全部页面可访问，完整基金研究流程可在浏览器完成。

### M4: 集成与验收（1-2 周）

1. E2E 测试
2. 文档更新
3. ruff + pytest + check-data 全过

退出标准：同 Phase 1 的质量门禁全部通过。

## 10. 验收标准

二期完成条件（继承 Phase 1 全部门禁 + 新增）：

1. 模拟持仓对 30 只样本基金完成披露期回测，回测报告可审计。
2. 动态归因对模拟持仓质量达标的基金输出收益拆解，残差占比记录在案。
3. 综合评分可回测，评分的分层单调性可验证。
4. 所有估计类结果使用 `estimated_*` 字段，不进入默认高置信度结论。
5. 前端可访问全部 13 个页面，无白屏或报错。
6. 前端 API client 可独立配置后端 URL，不硬编码。
7. 图表组件可通过 `ChartWrapper` 切换底层库。
8. `ruff check src tests frontend` 通过。
9. `pytest` 通过。
10. `fund-research check-data` 通过。

## 11. 需要确认的问题

1. 前端框架倾向 React 还是 Vue？（默认推荐 React + TypeScript）
2. 模拟持仓的候选池构建：上期持仓 + 同经理偏好 + 行业龙头 + 全市场，你倾向哪种起点？默认全上（多模型融合）。
3. 综合评分默认权重偏长期风险收益（收益+风险+Alpha 共 55%），是否需要调整？
4. 前端一期是否做响应式（桌面优先），移动端留到后续？
5. 算法实验管理：存储方式用 SQLite/DuckDB 表还是本地 JSON/YAML？默认用 ORM 表。
