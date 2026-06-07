# Fund Prism 第一期需求书

版本: v0.1  
日期: 2026-06-06  
状态: Draft  
前置依据: `docs/phase0/conclusion.md`, `docs/phase0/pre_phase1_readiness.md`

## 1. 文档定位

本文档定义 Fund Prism 第一期 MVP 的建设范围、数据口径、功能需求、接口合约、验收标准和非目标。

第一期的核心任务不是做“完整基金分析产品”，而是把第零阶段已经验证过的数据路径落成可运行、可测试、可复核的本地研究底座。平台需要能够从公开数据源拉取数据，写入本地数据库，运行基础分析，生成带证据链的结构化响应，并通过 Tool API 服务前端、Notebook 和 AI Agent。

## 2. 一期目标

### 2.1 总目标

建设一个本地单用户、无登录、可通过 CLI 和 API 使用的主动权益基金研究 MVP，覆盖以下闭环：

1. 初始化本地数据库。
2. 接入第零阶段验证通过的数据源。
3. 拉取基金基础信息、净值、公开持仓、经理、规模、费率、持有人结构、股票行情和指数行情。
4. 写入标准化 ORM 表。
5. 执行基础数据质量检查。
6. 计算收益风险指标、披露持仓分析、风格暴露和静态归因。
7. 生成统一 `APIResponse[T]` 和 Research Packet。
8. 为每个结论附带 metadata、evidence、warnings 和 conclusion_status。

### 2.2 业务目标

1. 支持个人研究者查询单只主动权益基金的基础画像。
2. 支持 AI Agent 通过稳定 JSON API 获取可引用、可复核的研究材料。
3. 将第零阶段的字段口径、数据源风险和算法边界落实到代码。
4. 为后续前端、基金池、综合评分、模拟持仓和动态归因留下清晰扩展点。

### 2.3 技术目标

1. 完成 FastAPI + SQLAlchemy + DuckDB/SQLite 的可运行闭环。
2. 完成 Alembic 初始化迁移，不直接用 raw SQL 建表。
3. 完成数据适配器接口和 AKShare 适配器第一版。
4. 完成 CLI 的 `init`, `serve`, `check-data`, `update` 可用实现。
5. 所有核心分析结果携带算法版本 metadata。
6. `ruff check src tests`, `pytest`, `fund-research check-data` 必须通过。

## 3. 一期非目标

1. 不做用户登录、多用户、权限、云端同步和在线协作。
2. 不做交易下单、荐基、收益承诺或投资建议。
3. 不做完整前端产品；一期只保证 API、CLI 和结构化输出。
4. 不做综合评分和基金排名。
5. 不做模拟持仓、动态归因和交易能力高置信度结论。
6. 不自动接入商业数据源。
7. 不分发第三方批量原始数据。
8. 不把官方 PDF/XBRL 路径默认视为已完成结构化主源；一期只做证据路径和后续解析预留。

## 4. 第零阶段输入约束

### 4.1 已验证前置条件

根据 `docs/phase0/pre_phase1_readiness.md`，一期开工前置验证结果为：

| 项目 | 结果 |
| --- | --- |
| AKShare 必需接口 | 17/17 成功 |
| 风格指数解析 | 5/5 成功 |
| 分红接口 | 可用 |
| 费率详情接口 | 可用 |
| 申购手续费列表接口 | 可用 |
| 公告列表接口 | 可用 |
| 官方 PDF 下载解析 | 最小闭环通过 |
| `fund_fee_em` 原接口 | 不作为一期主路径 |

### 4.2 一期必须继承的口径

1. 季报持仓只按 `top10_quarterly` 处理，不得描述为季度全部持仓。
2. 半年度和年度报告可出现完整持仓，但必须由披露粒度字段明确区分。
3. 官方 PDF 证据链只表示 A 级来源最小闭环通过，不等于官方结构化持仓解析已完成。
4. 股票日行情一期优先使用 `stock_zh_a_hist_tx`。
5. 基金费率详情一期优先使用 `fund_individual_detail_info_xq`。
6. `fund_fee_em` 保留为诊断或 P2 候选接口，不进入一期主路径。
7. 风格指数一期默认候选：

| 暴露维度 | 指数 symbol |
| --- | --- |
| large_cap | `sh000300` |
| mid_cap | `sh000905` |
| small_cap | `sh000852` |
| growth | `sz399370` |
| value | `sz399371` |

## 5. 用户与使用场景

### 5.1 个人基金研究者

用户可以用 CLI 更新一个样本基金或基金列表，然后通过 API 查询基金画像、净值指标、披露持仓和研究包。

### 5.2 量化/算法学习者

用户可以查看每个指标的输入字段、算法版本、计算参数、数据覆盖率和适用范围，并复现实验结果。

### 5.3 AI Agent 使用者

AI Agent 可以调用统一 Tool API 获取结构化结果。所有响应都必须包含证据、警告和结论状态，避免把估计或低置信度内容当成事实。

### 5.4 开源贡献者

贡献者可以新增数据适配器、算法模块、指标定义或测试用例，而不破坏统一 schema 和结论可信度门禁。

## 6. 数据范围

### 6.1 一期核心数据实体

一期实现 20 张核心表，沿用 `src/fund_research/db/models.py` 的表结构：

| 数据域 | 表 |
| --- | --- |
| 基金主数据 | `fund_main`, `fund_category`, `fund_manager`, `fund_manager_tenure`, `fund_company` |
| 净值与规模 | `fund_nav`, `fund_scale`, `fund_fee` |
| 持仓 | `fund_disclosed_holdings`, `holder_structure` |
| 市场数据 | `stock_main`, `stock_daily`, `industry_category` |
| 分析结果 | `style_exposure_result`, `static_attribution_result` |
| 研究与证据 | `research_packet`, `evidence`, `metric_registry` |
| 运行日志 | `data_source_snapshot`, `task_log`, `tool_api_call_log` |

### 6.2 一期默认数据源

| 数据域 | 默认来源 | source_level | 说明 |
| --- | --- | --- | --- |
| 基金列表 | AKShare `fund_name_em` | B | 默认全量基金基础列表 |
| 基金基础信息 | AKShare `fund_individual_basic_info_xq` | B | 单基金详情 |
| 基金净值 | AKShare `fund_open_fund_info_em` | B | 单位净值、累计净值 |
| 分红 | AKShare `fund_fh_em` | B | 用于复权和分红证据 |
| 基金持仓 | AKShare `fund_portfolio_hold_em` | B | 季报仅前十大 |
| 行业配置 | AKShare `fund_portfolio_industry_allocation_em` | B | 披露口径 |
| 持仓变动 | AKShare `fund_portfolio_change_em` | B | 用于公开披露层面的变动观察 |
| 基金经理 | AKShare `fund_manager_em` | B | 经理列表和在管基金 |
| 持有人结构 | AKShare `fund_hold_structure_em` | B | 半年度 |
| 股票行情 | AKShare `stock_zh_a_hist_tx` | B | 腾讯源，避开已验证不稳定路径 |
| 指数行情 | AKShare `stock_zh_index_daily_tx` | B | 风格指数 |
| 费率详情 | AKShare `fund_individual_detail_info_xq` | B | 一期主费率路径 |
| 公告列表 | AKShare `fund_announcement_report_em` | B | 官方 PDF 证据入口 |
| 官方 PDF | 巨潮等官方披露链接 | A | 一期只做证据下载/定位/摘要 |
| 本地文件 | CSV/Parquet/SQLite/DuckDB | LOCAL | 用户补充数据 |

### 6.3 数据快照要求

每次外部数据拉取必须记录：

1. 数据源名称。
2. 数据源类型。
3. 数据源等级。
4. 拉取时间。
5. 交易日或报告期。
6. 实体类型。
7. 字段数和记录数。
8. 覆盖率、缺失字段、异常数量。
9. 错误信息和警告。

## 7. 功能需求

### 7.1 环境与配置

#### FR-1.1 配置加载

系统必须使用 `pydantic-settings` 从 `.env` 和环境变量读取配置。

最低配置项：

1. 数据库 URL。
2. 日志级别。
3. 数据缓存目录。
4. API host 和 port。
5. 默认样本基金列表路径。
6. 数据源超时和重试参数。

验收：

1. 没有 `.env` 时可用默认配置启动。
2. `.env.example` 与真实配置项保持同步。
3. 不得提交 `.env`。

#### FR-1.2 数据库初始化

`fund-research init` 必须初始化本地数据库并执行迁移。

验收：

1. 初次运行可创建 DuckDB 或 SQLite 数据库。
2. 重复运行幂等。
3. 所有一期表可被 SQLAlchemy ORM 查询。
4. 初始化失败时返回明确错误。

### 7.2 数据适配器

#### FR-2.1 统一适配器接口

所有数据源适配器必须返回 `FetchResult`，并包含数据、质量摘要、错误信息和 warnings。

验收：

1. 成功和失败结果结构一致。
2. 不抛出未处理异常到 CLI/API 顶层。
3. 所有外部字段到标准字段的映射必须记录在 `config/field_mapping_v0.1.yaml` 或后续版本。

#### FR-2.2 AKShare 适配器

一期必须实现 AKShare 适配器，覆盖：

1. 基金列表。
2. 基金基础信息。
3. 基金净值。
4. 基金分红。
5. 基金公开持仓。
6. 行业配置。
7. 持仓变动。
8. 基金经理。
9. 持有人结构。
10. 股票日行情。
11. 指数日行情。
12. 费率详情。
13. 公告列表。

验收：

1. 对 30 只样本基金可完成基础数据更新。
2. 单接口失败不会中断整个批次。
3. 失败项进入 `task_log` 和 `data_source_snapshot`。
4. 结果不得依赖 AKShare 原始中文列名向上透出，必须标准化。

#### FR-2.3 官方披露证据适配

一期只要求官方 PDF 证据最小闭环，不要求完整结构化解析。

必须支持：

1. 从公告列表定位官方 PDF URL。
2. 下载 PDF 到 gitignored 缓存目录。
3. 记录 URL、HTTP 状态、SHA256、页数、下载时间。
4. 提取少量文本关键词用于证明文件可解析。
5. 生成 `EvidenceRecord`。

验收：

1. 对样本基金至少成功解析 1 个官方 PDF。
2. PDF 缓存不得提交到仓库。
3. 若 PDF 下载失败，API 不得声称 A 级证据可用。

### 7.3 数据入库与更新

#### FR-3.1 `fund-research update`

一期必须实现数据更新命令。

建议参数：

```bash
fund-research update --fund-code 000001
fund-research update --sample data/samples/sample_funds_v0.1.csv
fund-research update --from 2024-01-01 --to 2026-06-06
fund-research update --domains profile,nav,holdings
```

验收：

1. 支持单基金更新。
2. 支持样本基金批量更新。
3. 支持按数据域选择更新。
4. 支持增量更新，不重复插入唯一键相同记录。
5. 每次运行写入 `task_log`。

#### FR-3.2 数据去重和主键规则

必须为时间序列和报告期数据定义唯一键。

最低要求：

| 表 | 唯一性 |
| --- | --- |
| `fund_nav` | `fund_code + trade_date` |
| `fund_scale` | `fund_code + report_date` |
| `fund_disclosed_holdings` | `fund_code + report_date + security_code` |
| `stock_daily` | `stock_code + trade_date` |
| `style_exposure_result` | `fund_code + calc_date + algorithm_name + algorithm_version` |
| `static_attribution_result` | `fund_code + report_date + algorithm_name + algorithm_version` |

验收：

1. 重复更新不会产生重复记录。
2. 新数据可覆盖同唯一键旧记录，但必须保留更新时间和来源。

### 7.4 数据质量

#### FR-4.1 基础质量检查

`fund-research check-data` 必须检查：

1. 第零阶段本地产物是否存在。
2. 一期开工前置验证是否通过。
3. 数据库是否可连接。
4. 样本基金数量是否为 30。
5. 字段映射文件是否可解析。
6. 核心表是否存在。
7. 最近一次更新是否有失败任务。

验收：

1. 正常状态返回 exit code 0。
2. 缺少关键产物返回非 0。
3. 输出可读表格。

#### FR-4.2 入库质量检查

数据写入后必须计算：

1. 记录数。
2. 字段覆盖率。
3. 缺失字段数。
4. 异常值数量。
5. 数据源等级。
6. 日期范围。

验收：

1. 质量摘要写入 `data_source_snapshot`。
2. API metadata 可引用质量摘要。
3. 覆盖率不足时返回 warning。

### 7.5 分析模块

#### FR-5.1 净值指标 `nav_metrics`

输入：

1. 基金日净值。
2. 分红数据。
3. 可选基准指数。

输出：

1. 区间收益。
2. 年化收益。
3. 最大回撤。
4. 年化波动率。
5. 下行波动率。
6. 夏普比率。
7. 卡玛比率。
8. 索提诺比率。
9. 信息比率。
10. 数据覆盖率和不适用原因。

验收：

1. 支持今年以来、近 1/3/6 月、近 1/3/5 年、成立以来和自定义区间。
2. 少于最低样本天数时返回 `needs_review`。
3. 每个结果包含算法版本。

#### FR-5.2 公开持仓分析 `holdings`

输入：

1. 披露持仓。
2. 报告期。
3. 股票行业和市值信息。

输出：

1. 前十大持仓。
2. 行业分布。
3. 集中度。
4. 持仓变动。
5. 披露粒度。
6. 数据限制说明。

验收：

1. 季报结果明确标记 `top10_quarterly`。
2. 半年报和年报可标记为 `full_semiannual_or_annual` 或相应粒度。
3. 不得把季报前十大推断为完整组合。

#### FR-5.3 风格暴露 `exposure`

输入：

1. 基金日收益。
2. 风格指数日收益。
3. 窗口参数。

一期方法：

1. 滚动回归。
2. 输出市值和成长/价值暴露。
3. 显示 `r_squared`、残差和输入覆盖率。

输出：

1. 大盘/中盘/小盘暴露。
2. 成长/价值暴露。
3. 残差。
4. 风格漂移观察。

验收：

1. 默认窗口为 60 个交易日。
2. 支持 20 到 504 个交易日窗口。
3. 当 `r_squared` 或覆盖率不达标时，结论降级为 `observation` 或 `needs_review`。
4. 不得输出高置信度风格事实。

#### FR-5.4 静态归因 `attribution`

输入：

1. 披露持仓。
2. 报告期内证券收益。
3. 可选基准收益。

一期方法：

1. 基于披露持仓做静态近似归因。
2. 季报仅基于前十大重仓股。
3. 输出未解释残差。

输出：

1. 个股贡献。
2. 行业贡献。
3. 披露持仓可解释收益。
4. 残差。
5. 局限性 warning。

验收：

1. 结论状态默认为 `observation` 或 `needs_review`，除非输入完整且残差达标。
2. API 明确说明“仅基于披露持仓，不反映季度内调仓”。
3. 结果写入 `static_attribution_result`。

### 7.6 Research Packet 与 Evidence

#### FR-6.1 Evidence

所有证据必须包含：

1. evidence_id。
2. entity_id。
3. evidence_type。
4. source。
5. source_level。
6. date_range。
7. algorithm_metadata。
8. report_location 或 data_summary。
9. confidence。

验收：

1. API 返回的 evidence 可被单独追溯。
2. 证据缺失时结论不得高于 `needs_review`。

#### FR-6.2 Research Packet

一期必须支持单基金研究包。

内容至少包括：

1. fund_profile。
2. manager_info。
3. nav_metrics。
4. disclosed_holdings。
5. exposure。
6. attribution。
7. risk_alerts。
8. evidence。
9. data_quality。
10. conclusion_map。
11. warnings。

验收：

1. 可输出 JSON。
2. 可输出 Markdown 摘要。
3. metadata 包含平台版本、数据日期、算法版本、数据源等级和缺失字段。

## 8. Tool API 需求

所有 API 必须返回：

```json
{
  "data": {},
  "metadata": {},
  "evidence": [],
  "warnings": [],
  "conclusion_status": "needs_review",
  "not_applicable_reason": null
}
```

### 8.1 `GET /api/v1/funds/{fund_code}/profile`

返回基金基础信息、经理、分类、规模和费率。

验收：

1. 基金不存在时返回明确错误或空数据 warning。
2. 所有字段带数据源等级。
3. 不完整字段进入 warnings。

### 8.2 `GET /api/v1/funds/{fund_code}/nav-metrics`

参数：

1. `start`
2. `end`
3. 可选基准。

返回净值收益风险指标。

验收：

1. 无足够净值数据时返回 `needs_review`。
2. 指标 metadata 包含算法版本和交易日范围。

### 8.3 `GET /api/v1/funds/{fund_code}/holdings`

参数：

1. `report_date`
2. 可选 `asset_type`

返回公开披露持仓。

验收：

1. 明确披露粒度。
2. 季报前十大输出 warning。
3. 支持最新报告期默认查询。

### 8.4 `POST /api/v1/analysis/exposure`

参数：

1. `fund_code`
2. `window`
3. 可选指数集合。

返回风格暴露。

验收：

1. 结果写入分析结果表。
2. 输入不足时返回不适用原因。

### 8.5 `POST /api/v1/research/packet`

参数：

1. `fund_code`
2. `template`

返回 Research Packet。

一期模板：

1. `single_fund_checkup`
2. `manager_profile`
3. `style_drift`
4. `holdings_deep_dive`

验收：

1. 默认模板为 `single_fund_checkup`。
2. 返回 JSON 结构稳定。
3. 研究包可落库。

## 9. CLI 需求

### 9.1 `fund-research init`

初始化数据库、迁移和必要目录。

### 9.2 `fund-research serve`

启动 FastAPI 服务。

参数：

```bash
fund-research serve
fund-research serve -p 9000
```

验收：

1. 默认端口 8000。
2. `/docs` 可访问。
3. `/api/v1/health` 返回数据库状态。

### 9.3 `fund-research check-data`

检查第零阶段和一期本地产物、数据库和数据质量摘要。

### 9.4 `fund-research update`

执行数据更新。

验收：

1. 支持 dry-run。
2. 支持单基金和样本批量。
3. 支持数据域选择。
4. 输出成功/失败摘要。

## 10. 结论可信度门禁

一期必须实现统一的结论状态规则：

| 状态 | 含义 | 一期使用规则 |
| --- | --- | --- |
| `fact` | 公开披露事实 | 基金成立日、基金公司、报告披露字段 |
| `computed` | 确定性计算 | 净值收益、回撤等规则指标 |
| `estimated` | 模型估计 | 一期尽量不进入默认结论 |
| `observation` | 研究观察 | 风格暴露、静态归因、持仓变化观察 |
| `needs_review` | 待复核 | 证据不足、输入不足、接口失败、不适用 |

默认结论进入 Research Packet 前必须满足：

1. 输入数据覆盖率达标。
2. 数据源等级符合模块要求。
3. 算法适用基金类型。
4. 残差低于模块阈值。
5. evidence 完整。
6. 数据日期未明显过期。

## 11. 测试与质量门禁

### 11.1 单元测试

必须覆盖：

1. Pydantic schema。
2. 枚举和结论状态。
3. 数据适配器错误处理。
4. 数据质量计算。
5. 指标算法边界。
6. API 响应结构。

### 11.2 集成测试

必须覆盖：

1. 初始化数据库。
2. 样本基金更新。
3. API 查询。
4. Research Packet 生成。
5. `check-data` 通过。

### 11.3 必过命令

```bash
ruff check src tests
pytest
fund-research check-data
```

如本地未安装命令行入口，可使用：

```bash
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m fund_research.cli.main check-data
```

## 12. 安全与合规

1. 不提交 `.env`。
2. 不提交数据库文件。
3. 不提交 `data/cache/*` 中的 PDF 或原始下载文件。
4. 不提交第三方批量原始数据。
5. 所有外部数据都标注来源和等级。
6. API 和研究包必须保留“不构成投资建议”的免责声明。

## 13. 一期交付物

| 编号 | 交付物 | 路径 |
| --- | --- | --- |
| P1-1 | 数据适配器实现 | `src/fund_research/data/adapters/` |
| P1-2 | 数据更新 CLI | `src/fund_research/cli/main.py` |
| P1-3 | 数据库迁移 | `src/fund_research/db/migrations/` |
| P1-4 | 净值指标模块 | `src/fund_research/analysis/nav_metrics.py` |
| P1-5 | 持仓分析模块 | `src/fund_research/analysis/holdings.py` |
| P1-6 | 风格暴露模块 | `src/fund_research/analysis/exposure.py` |
| P1-7 | 静态归因模块 | `src/fund_research/analysis/attribution.py` |
| P1-8 | Evidence/Research Packet | `src/fund_research/research/` |
| P1-9 | Tool API 实现 | `src/fund_research/api/router.py` |
| P1-10 | 测试用例 | `tests/` |
| P1-11 | 一期使用文档 | `README.md`, `docs/phase1/` |

## 14. 里程碑

### M1: 数据库与配置闭环

1. 配置加载完成。
2. 数据库初始化完成。
3. ORM 表和迁移可用。
4. `health` 可返回数据库状态。

退出标准：

1. `fund-research init` 成功。
2. `pytest` 通过。

### M2: 数据接入闭环

1. AKShare 适配器完成。
2. 单基金更新完成。
3. 样本基金批量更新完成。
4. 数据快照和任务日志完成。

退出标准：

1. 30 只样本基金基础数据更新成功率可报告。
2. 失败项有日志和 warning。

### M3: 分析闭环

1. 净值指标完成。
2. 公开持仓分析完成。
3. 风格暴露完成。
4. 静态归因降级版完成。

退出标准：

1. 每个分析模块可对样本基金运行。
2. 所有分析结果带算法版本。
3. 输入不足时降级而非报假结论。

### M4: API 与研究包闭环

1. 5 个 Tool API 完成。
2. Research Packet 完成。
3. Evidence 贯穿 API 响应。
4. CLI 与 API 文档更新。

退出标准：

1. `ruff check src tests` 通过。
2. `pytest` 通过。
3. `fund-research check-data` 通过。
4. 单基金研究包可生成并落库。

## 15. 风险与应对

| 风险 | 影响 | 一期应对 |
| --- | --- | --- |
| AKShare 接口变动 | 数据拉取失败 | 适配器捕获异常，写入快照，保留接口盘点脚本 |
| 季报仅前十大 | 归因不完整 | 明确 `top10_quarterly`，结论降级 |
| 官方 PDF 结构不稳定 | A 级数据无法自动解析 | 一期只做证据下载和定位，结构化解析后置 |
| 复权净值需自算 | 收益口径错误 | 分红路径入 evidence，复权算法加测试 |
| 股票行情源不稳定 | 风格暴露失败 | 使用已验证 `stock_zh_a_hist_tx`，保留替代适配器 |
| 费率接口为空 | 基础信息缺失 | 使用 `fund_individual_detail_info_xq` 作为主路径 |
| 数据源授权边界 | 开源合规风险 | 不提交原始批量数据，只提交适配器和小样本 |

## 16. 一期完成定义

一期只有在以下条件全部满足时才算完成：

1. 本地新环境可按 README 完成安装、初始化和启动。
2. 30 只样本基金可完成数据更新，失败项可解释。
3. 数据写入 20 张核心表中的相关表。
4. 5 个 Tool API 返回统一 `APIResponse[T]`。
5. 单基金 Research Packet 可生成。
6. 所有自动结论都带 evidence、metadata、warnings 和 conclusion_status。
7. 估计类或低置信度结果不进入高置信度默认结论。
8. `ruff check src tests` 通过。
9. `pytest` 通过。
10. `fund-research check-data` 通过。
11. 仓库不包含 `.env`、数据库文件、PDF 缓存或第三方批量原始数据。

