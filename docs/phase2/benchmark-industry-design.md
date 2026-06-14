# P2C+ Benchmark Industry Weight Design

日期: 2026-06-13  
状态: Implemented in P2C+  
范围: 真实基准行业权重接入设计与实现记录

## 1. 背景与目标

P2C 已把动态归因从代理收益升级为真实行情驱动：

- 持仓股票收益来自 `stock_daily`
- 基准收益来自指数行情 `stock_daily.stock_code = benchmark_symbol`
- `benchmark_symbol` 可由参数或 `FundMain.benchmark` 轻量解析

但当前 Brinson/BHB 归因仍有一个重要限制：`bench_weight` 暂用基金披露行业权重。它只能验证行业收益和基准收益接入，不能解释真实“相对基准行业配置效应”。下一步要接入真实基准行业权重，即：

1. 指数成分：某指数在某个快照日包含哪些股票。
2. 成分权重：每只成分股在指数中的权重。
3. 行业分类：每只成分股在统一行业体系下属于哪个行业。
4. 派生基准行业权重：按行业聚合指数成分权重，供动态归因使用。

本设计最初用于定义数据源、表结构、质量门禁和接入顺序；2026-06-13 已按本文主路径完成 schema、adapter、update workflow、聚合和动态归因 runner 接入。

## 2. 现状约束

现有代码和文档约束：

- `stock_daily` 已复用存储股票与指数日行情，适合价格/收益，不适合成分权重。
- `industry_category` 只存行业 taxonomy，不存“股票-行业-日期”映射。
- `StockMain` 有 `industry_sw`、`industry_citic` 字段，但缺少历史生效日期，不适合做可回溯归因。
- `DataSourceSnapshot` 和 `TaskLog` 已能记录数据拉取质量，应该继续复用。
- P2 需求要求估计结果隔离、残差可审计、失败样本可解释。
- 仓库不能分发第三方批量原始数据，只能提交适配器、schema、测试样例和小规模 mock。

设计结论：新增专用快照表，不能把指数成分权重塞入 `stock_daily`、`StockMain` 或 `experiment_result.metrics`。

## 3. 数据源调研

### 3.1 指数成分与成分权重

推荐主路径：AKShare 封装的中证指数接口。

| 数据 | AKShare 接口 | 底层来源 | 字段情况 | 风险 |
|------|--------------|----------|----------|------|
| 指数成分权重 | `index_stock_cons_weight_csindex(symbol)` | 中证指数 Excel | 日期、指数代码、成分券代码、交易所、权重 | 当前本机实测连接 `oss-ch.csindex.com.cn` 遇到 SSL EOF，需健康检查 |
| 指数成分目录 | `index_stock_cons_csindex(symbol)` | 中证指数 Excel | 日期、指数代码、成分券代码、交易所 | 同上 |
| 指数列表 | `index_stock_info()` | JoinQuant 指数列表页面 | index_code、display_name、publish_date | 来源非官方，仅作发现/辅助 |

AKShare 本地源码显示，权重接口下载路径形如：

- `https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/{symbol}closeweight.xls`
- `https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/{symbol}cons.xls`

中证指数详情页为官方入口，例如:

- `https://www.csindex.com.cn/zh-CN/indices/index-detail/000300`
- `https://www.csindex.com.cn/zh-CN/indices/index-detail/000905`
- `https://www.csindex.com.cn/zh-CN/indices/index-detail/000852`

注意：这些接口语义是“最新成分/最新权重快照”，不是完整历史权重序列。第一版只能把它作为快照数据，不能声称可还原历史任意报告期的真实基准权重。

### 3.2 行业分类

候选路径：

| 数据 | AKShare 接口 | 底层来源 | 优点 | 风险 |
|------|--------------|----------|------|------|
| 申万一级/二级/三级行业 taxonomy | `sw_index_first_info()` / `sw_index_second_info()` / `sw_index_third_info()` | 乐咕乐股申万行业页 | 有行业代码和层级 | 非官方，页面解析风险 |
| 申万一级行业成分 | `sw_index_third_cons(801xxx.SI)` | 乐咕乐股 | 返回股票及申万1级字段 | 第一版只落一级归属，应遍历一级 symbol；不要默认遍历 `850xxx.SI` 三级 symbol |
| 本地行业映射文件 | `stock-industry --industry-file` | 用户本地 CSV/XLSX | 可审计、可重复导入 | 需要人工确认来源和快照日期 |
| 东方财富行业板块列表 | `stock_board_industry_name_em()` | 东方财富 | 调用简单 | 行业体系不是申万/中信正式口径 |
| 东方财富行业板块成分 | `stock_board_industry_cons_em(symbol)` | 东方财富 | 成分可得 | 行业口径更偏行情板块 |
| 已有持仓披露行业 | `fund_disclosed_holdings.industry` | 基金披露/AKShare | 已入库 | 只覆盖基金持仓，不覆盖指数全成分 |

推荐第一版行业体系：申万一级，派生自 `sw_index_third_cons(801xxx.SI)` 返回的 `申万1级` 字段。

理由：

- 动态归因第一阶段只需要行业级聚合，不需要三级行业精细度。
- 申万一级便于解释，行业数量适中。
- `IndustryCategory` 已按分类体系/层级设计，容易承接 taxonomy。
- 当乐咕页面源不稳定时，优先使用本地 CSV/XLSX 行业映射导入 fallback 补齐 `stock_industry_membership`。
- 东方财富行业板块可作为备用或健康检查，不建议作为默认正式口径。

### 3.3 数据源等级建议

| 数据 | source_level | 说明 |
|------|--------------|------|
| 中证指数官网/下载文件 | B | 官方指数公司页面/文件，但经 AKShare 抓取，不属于本项目直接官方披露闭环 |
| AKShare 封装结果 | B | 与项目既有 AKShare 数据等级一致 |
| 乐咕乐股申万行业页 | C 或 B- | 非官方再分发，建议落库时标注 `C`，除非后续证明来源稳定 |
| 东方财富行业板块 | B | 行情板块数据，可用但口径不同 |
| 本地人工校验/补丁 | LOCAL | 只用于纠错或少量样本，不作为默认大规模源 |

第一版结果的 `conclusion_status` 不应高于 `estimated` 或 `observation`。只有成分权重、行业映射、行情窗口都通过门禁，动态归因结果才可标为 `estimated`；否则 `needs_review`。

## 4. 推荐数据模型

### 4.1 新表：`benchmark_index_member`

用途：保存指数成分和成分权重快照。

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BigInteger PK | 复用 `id_column()` |
| `benchmark_symbol` | String(20) | 平台内部 symbol，如 `sh000300` |
| `index_code` | String(20) | 中证代码，如 `000300` |
| `index_name` | String(100) | 指数名称 |
| `snapshot_date` | Date | 权重文件里的日期，或拉取日 |
| `stock_code` | String(20) | 平台股票代码，建议 6 位纯数字 |
| `stock_name` | String(100) | 成分券名称 |
| `exchange` | String(20) | SH/SZ 或原始交易所名称 |
| `weight_pct` | Float | 成分权重百分比，保持原始百分比口径 |
| `source_name` | String(50) | `akshare.index_stock_cons_weight_csindex` |
| `source_level` | String(10) | B/C/LOCAL |
| `raw_payload_hash` | String(64) | 可选，文件内容或行内容 hash |
| `created_at` | DateTime | 入库时间 |

唯一键：

```text
benchmark_symbol + snapshot_date + stock_code
```

索引：

- `benchmark_symbol + snapshot_date`
- `stock_code + snapshot_date`

口径：

- `weight_pct` 不立刻转 0-1，避免与来源文件口径混淆。
- 使用时再除以 100，并按可用成分归一化。
- 对权重和做质量检查，正常应接近 100。可接受区间建议 `[99.0, 101.0]`，否则降级。

### 4.2 新表：`stock_industry_membership`

用途：保存股票行业归属快照，支持历史口径。

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BigInteger PK | 复用 `id_column()` |
| `stock_code` | String(20) | 6 位股票代码 |
| `stock_name` | String(100) | 股票简称 |
| `classification_type` | String(30) | `SW` / `CITIC` / `EASTMONEY_BOARD` |
| `classification_version` | String(20) | 如 `2021`、`unknown` |
| `level` | Integer | 1/2/3 |
| `industry_code` | String(20) | 行业代码，可空但不推荐 |
| `industry_name` | String(50) | 行业名称 |
| `parent_industry_code` | String(20) | 可选 |
| `effective_date` | Date | 生效/快照日期 |
| `source_name` | String(80) | 如 `akshare.sw_index_third_cons` |
| `source_level` | String(10) | C/B/LOCAL |
| `created_at` | DateTime | 入库时间 |

唯一键：

```text
stock_code + classification_type + level + effective_date
```

索引：

- `stock_code + classification_type + effective_date`
- `classification_type + level + industry_name`

口径：

- 第一版只要求申万一级，即 `classification_type = "SW"`、`level = 1`。
- 如果同一股票同一日出现多个一级行业，视为数据异常，不自动二选一。
- `StockMain.industry_sw` 可作为“当前快照冗余字段”同步，但不能替代本表。

### 4.3 新表：`benchmark_industry_weight`

用途：保存由指数成分权重 + 股票行业归属聚合得到的基准行业权重。

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BigInteger PK | 复用 `id_column()` |
| `benchmark_symbol` | String(20) | 如 `sh000300` |
| `snapshot_date` | Date | 使用的指数权重快照日 |
| `classification_type` | String(30) | `SW` |
| `classification_level` | Integer | 第一版为 1 |
| `industry_code` | String(20) | 行业代码 |
| `industry_name` | String(50) | 行业名称 |
| `weight_pct` | Float | 行业聚合权重，百分比 |
| `member_count` | Integer | 行业内可映射成分数 |
| `unmapped_weight_pct` | Float | 指数成分无法匹配行业的权重 |
| `coverage_pct` | Float | 可映射权重占总权重比例 |
| `source_member_snapshot` | Date | 指数成分快照日 |
| `source_industry_snapshot` | Date | 行业映射快照日 |
| `algorithm_version` | String(20) | 如 `benchmark_industry_weight:0.1.0` |
| `warnings` | JSON | 异常与降级原因 |
| `created_at` | DateTime | 入库时间 |

唯一键：

```text
benchmark_symbol + snapshot_date + classification_type + classification_level + industry_name
```

质量门禁：

- `coverage_pct >= 95.0` 才允许进入默认动态归因。
- 行业权重和应接近 100，建议容忍 `[99.0, 101.0]`。
- `unmapped_weight_pct > 5.0` 时动态归因降级为 `needs_review`。
- 成分权重快照距离归因报告期超过 45 天时，写 warning；超过 120 天时默认不使用。

### 4.4 是否需要存原始文件

不建议提交或默认保存第三方原始 Excel 到仓库。可以在本地 gitignored cache 保存：

```text
data/cache/benchmark_members/{index_code}/{snapshot_date}/closeweight.xls
data/cache/benchmark_members/{index_code}/{snapshot_date}/cons.xls
```

落库时记录 `raw_payload_hash`、`record_count`、`field_count`、`coverage_rate` 到 `DataSourceSnapshot`，满足可审计即可。

## 5. 数据流程

### 5.1 更新流程

建议新增数据域：

```bash
fund-research update --domains benchmark-members --index-symbol sh000300 --index-symbol sh000905
fund-research update --domains stock-industry --classification SW
fund-research update --domains benchmark-industry --index-symbol sh000300
```

本地文件 fallback:

```bash
fund-research update --domains benchmark-members --index-symbol sh000300 --benchmark-members-file data/local/000300closeweight.xls
fund-research update --domains stock-industry --industry-file data/local/stock_industry_sw.csv
```

逻辑顺序：

1. `benchmark-members`: 拉取指数成分权重，写 `benchmark_index_member`。
2. `stock-industry`: 拉取行业 taxonomy 和股票行业归属，写 `industry_category` 与 `stock_industry_membership`。
3. `benchmark-industry`: 聚合成分权重到行业权重，写 `benchmark_industry_weight`。
4. 动态归因 runner 查询最近可用 `benchmark_industry_weight`，替代当前 proxy `bench_weight`。

### 5.2 symbol 映射

需要统一内部 symbol 和数据源 symbol：

| 内部 symbol | 中证代码 | 常见名称 |
|-------------|----------|----------|
| `sh000300` | `000300` | 沪深300 |
| `sh000905` | `000905` | 中证500 |
| `sh000852` | `000852` | 中证1000 |

建议新增纯函数：

```text
benchmark_symbol_to_index_code("sh000300") -> "000300"
index_code_to_benchmark_symbol("000905") -> "sh000905"
```

不要在多个 adapter/runner 里各自写字符串切片。

### 5.3 行业权重计算口径

输入：

- `benchmark_index_member.weight_pct`
- `stock_industry_membership.industry_name`

步骤：

1. 选择 `snapshot_date <= target_date` 的最近指数成分权重。
2. 选择 `effective_date <= target_date` 的最近行业归属。
3. 按 `stock_code` join。
4. 对可映射成分按 `industry_name` sum `weight_pct`。
5. 记录不可映射权重。
6. 若 coverage 达标，把可映射行业权重归一化到 100；同时保留原始 coverage。

归一化策略：

- `weight_pct_raw`: 原始成分权重直接聚合后的行业权重。
- `weight_pct`: 在可映射成分内归一化后的行业权重。
- `unmapped_weight_pct`: 原始不可映射权重。

第一版表可以只存 `weight_pct` 和 `unmapped_weight_pct`，但 metrics 中应报告 coverage。

## 6. 动态归因接入设计

当前 `_run_dynamic_attribution_batch` 的 proxy 行为：

- `port_weight`: 基金披露行业权重
- `bench_weight`: 暂用同一份基金披露行业权重
- warning: 基准行业权重尚未接入

目标行为：

- `port_weight`: 基金披露持仓按行业聚合
- `bench_weight`: 查询 `benchmark_industry_weight`
- `bench_return`: 仍使用真实指数收益复合或未来扩展为行业基准收益
- 若找不到基准行业权重，不能静默回退，必须失败或显式 fallback 到 proxy，并标记 `uses_proxy_benchmark_weights = true`

建议第一版策略：

| 场景 | 行为 | conclusion_status |
|------|------|-------------------|
| 基准行业权重存在且 coverage 达标 | 使用真实 `bench_weight` | `estimated` |
| 基准行业权重缺失 | 实验失败，写 `needs_review` | `needs_review` |
| 覆盖率不足 | 实验失败，写覆盖率 warning | `needs_review` |
| 用户参数 `allow_proxy_benchmark_weights=true` | 可回退 proxy，但必须标记 | `needs_review` 或 `estimated` 禁止进入默认结论 |

输出 metrics 新增：

- `uses_real_benchmark_weights`
- `uses_proxy_benchmark_weights`
- `benchmark_weight_snapshot_date`
- `benchmark_weight_coverage_pct`
- `benchmark_industry_classification`
- `benchmark_industry_level`
- `benchmark_unmapped_weight_pct`

## 7. API 和前端影响

### 7.1 API

短期不需要新增用户 API。动态归因实验结果 metrics 足够承接。

后续可考虑：

```text
GET /api/v2/benchmarks/{benchmark_symbol}/industry-weights
GET /api/v2/benchmarks/{benchmark_symbol}/members
```

返回仍必须使用统一 `APIResponse[T]`，并包含：

- `metadata.data_snapshots`
- `evidence` 或 data source summary
- `warnings`
- `conclusion_status`

### 7.2 前端

实验页先只展示 metrics：

- 基准行业权重快照日期
- 行业分类口径
- 覆盖率
- 是否使用 proxy

不要急着做复杂图表。等数据稳定后再在归因页加“基金行业权重 vs 基准行业权重”柱状图。

## 8. 测试策略

第一轮只做可控小测试，不依赖真实外网：

1. Adapter 单元测试：fake AKShare 返回中证权重 DataFrame，验证标准化字段。
2. 入库测试：重复写同一 `benchmark_symbol + snapshot_date + stock_code` 不产生重复。
3. 行业映射测试：fake 申万三级成分返回同一股票一条一级行业。
4. 聚合测试：指数 3 只股票，权重 50/30/20，行业 A/A/B，输出 A=80、B=20。
5. 覆盖率门禁测试：缺 10% 行业映射时 `needs_review`。
6. Runner 集成测试：有真实 `benchmark_industry_weight` 时 `uses_real_benchmark_weights = true`。
7. Runner 失败测试：缺基准行业权重时不得静默使用基金行业权重。

外网健康检查另做 CLI smoke，不放进默认 pytest：

```bash
fund-research check-data --domains benchmark-members
```

## 9. 实施顺序建议

建议拆成 4 个小 PR/任务，降低 AI 写错概率：

1. **Schema only**
   - 新增 ORM + Alembic：`benchmark_index_member`、`stock_industry_membership`、`benchmark_industry_weight`
   - 只加模型和迁移测试，不接 adapter。

2. **Adapter + update**
   - 新增 AKShare adapter 方法：`fetch_index_members_weight`、`fetch_index_members`、`fetch_sw_industry_membership`
   - 新增 update workflow，写快照和任务日志。
   - 全部用 fake adapter 测试。

3. **Aggregation**
   - 新增纯函数/服务：`build_benchmark_industry_weights`
   - 从已入库成分和行业映射聚合，不访问外网。
   - 完成覆盖率和权重和门禁。

4. **Runner integration**
   - 动态归因读取 `benchmark_industry_weight`
   - 删除默认 proxy 行为或只允许显式参数开启
   - 更新 metrics、warnings、handoff 和实验测试。

这比一次性把数据源、表、算法和前端全改完更稳。

## 10. 风险登记

| 风险 | 等级 | 影响 | 应对 |
|------|------|------|------|
| 中证权重文件连接不稳定 | 高 | 无法更新成分权重 | 加健康检查、本地 cache、失败写 snapshot，不影响已有缓存 |
| 中证接口只有最新快照 | 高 | 无法历史回溯 | 第一版只用于最近报告期；历史回测标记为快照近似 |
| 行业分类非官方源 | 中 | 行业口径有误差 | 明确 `classification_type/source_level`，支持后续切换中信/申万官方源 |
| 股票代码格式混乱 | 中 | join 失败 | 入库统一 6 位代码，交易所单独字段 |
| 权重口径百分比/小数混淆 | 中 | 行业权重错误 100 倍 | 表字段命名 `weight_pct`，测试权重和 |
| 成分权重与行业快照日期错配 | 中 | 归因解释偏差 | 记录两个 source snapshot date，并设最大可接受滞后 |
| 指数复合基准包含现金/债券部分 | 中 | 基金 benchmark 文本可能不是纯股票指数 | `benchmark_symbol` 只解析股票指数部分；复合基准留到 review 配置 |

## 11. 已实现范围与本轮不做

已实现：

- 新增 `benchmark_index_member`、`stock_industry_membership`、`benchmark_industry_weight` 三张表和 Alembic 迁移。
- 新增 AKShare 指数成分权重、指数成分目录、申万行业成分 adapter。
- 新增 `benchmark-members`、`stock-industry`、`benchmark-industry` update 域。
- 动态归因 runner 默认读取真实基准行业权重；缺失或覆盖不足时失败进入 `needs_review`，不再静默使用 proxy。
- 补齐基准-only 行业的收益行，避免 Brinson 把缺失基准行业收益当作 0。

- 不做商业数据源接入。
- 不做完整历史指数成分权重回溯。
- 不把基准行业权重直接写进 Research Packet 默认结论。
- 不新增复杂前端页面。
- 不把外部 Excel 原始文件提交到仓库。
- 不让动态归因在缺基准行业权重时无提示降级。

## 12. 下一步验收标准

开始写代码前，先确认以下设计点：

1. 新表命名是否接受：`benchmark_index_member`、`stock_industry_membership`、`benchmark_industry_weight`。
2. 第一版行业口径是否确定为申万一级。
3. 缺基准行业权重时，默认是否应失败而不是 proxy fallback。
4. `benchmark_symbol` 是否继续沿用 `sh000300/sh000905/sh000852`，并单独映射到中证 `000300/000905/000852`。
5. `coverage_pct` 门槛是否用 95%，权重和容忍区间是否用 `[99, 101]`。

建议确认后再进入 Schema-only 任务。
