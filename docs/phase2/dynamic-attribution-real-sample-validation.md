# Dynamic Attribution Real Sample Validation

日期: 2026-06-14
范围: P2E 真实基金动态归因小样本闭环验收
本地库: `data/fund_research.duckdb`

## 1. 样本

基金:

- `000001` 华夏成长混合
- `fund_main.benchmark`: 本基金暂不设业绩比较基准
- 本轮显式指定基准: `sh000300`

本地数据覆盖:

| 数据 | 状态 |
|---|---|
| `fund_disclosed_holdings` | 10 条，报告期 `2026-03-31`，权重合计约 `27.15%` |
| 持仓股票行情 `stock_daily` | 10 只持仓股均覆盖 `2024-01-02` 到 `2026-06-01` |
| 基准指数行情 `stock_daily` | `sh000300`、`sh000905` 均覆盖 `2024-01-02` 到 `2026-06-01` |
| `benchmark_industry_weight` | 当前主库为空 |
| 本地 `data/local/stock_industry_sw.csv` | 覆盖指数成分行业，不覆盖本基金 10 只 Q1 持仓 |

## 2. 运行结果

运行实验:

```text
experiment_name = p2e-real-sample-000001-after-schema-fix
algorithm_name = dynamic_attribution
parameters = {"benchmark_symbol": "sh000300"}
sample_fund_codes = ["000001"]
```

落库结果:

```text
status = failed
fund_code = 000001
is_success = false
error_message = 缺少可用基准行业权重: sh000300
warnings = ["2026-03-31 缺少基准行业权重: sh000300"]
metrics = {}
```

结论: **真实样本闭环未通过**。

这不是动态归因算法计算错误，而是同一个运行库内的数据还没有满足算法 gating:

1. 主库 `data/fund_research.duckdb` 没有 `benchmark_industry_weight`。
2. 已验收的基准行业权重在 `data/benchmark_validation.sqlite`，还没有导入主库。
3. 可用基准行业权重快照是 `2026-05-29`，晚于基金报告期 `2026-03-31`，不能用于该报告期，否则会产生 look-ahead。
4. 基金披露持仓 `industry` 字段为空；当前本地行业映射文件也不覆盖这 10 只持仓股，不能构造真实组合行业权重。

## 3. 本轮发现的工程问题

真实样本运行第一次失败在结果落库阶段:

```text
experiment_result.experiment_id INTEGER
algorithm_experiment.id BIGINT
```

应用使用 63-bit 本地 ID，旧 DuckDB 库的 `experiment_result.experiment_id`
是 32-bit `INTEGER`，导致大 ID 写入失败。

已修复:

- ORM 显式声明 `ExperimentResult.experiment_id` 为 `BigInteger`。
- ORM 显式声明 `FundMain.fund_company_id` 为 `BigInteger`。
- 新增迁移 `20260614_0001_bigint_foreign_keys`，DuckDB 下必要时重建 `experiment_result`。
- 已对本地 `data/fund_research.duckdb` 执行迁移，并完成第二次真实样本运行。

## 4. 快照新鲜度 gate

已新增动态归因基准行业权重新鲜度规则:

- `snapshot_date > report_date`: 仍然不可用，避免 look-ahead。
- `report_date - snapshot_date > 120 天`: 可用但写 warning。
- `report_date - snapshot_date > 180 天`: 不可用，实验失败并进入 review。

成功结果会新增:

- `benchmark_weight_snapshot_age_days_by_report`

## 5. 下一步

要让真实样本通过，需要先补齐同库数据，而不是继续调算法:

1. 把已验收的 `benchmark_index_member`、`stock_industry_membership`、`benchmark_industry_weight` 导入或重跑到 `data/fund_research.duckdb`。
2. 为 `000001` 的 10 只 2026Q1 持仓补充申万一级行业归属。
3. 获取不晚于 `2026-03-31` 的 `sh000300` 基准行业权重快照；如果数据源只能提供 `2026-05-29` 最新权重，则不能用于该报告期验收。
4. 或者选择报告期不早于 `2026-05-29` 的真实基金披露持仓做下一轮样本。
5. 再运行 `dynamic_attribution`，要求至少看到 `uses_real_* = true`、coverage >= 95%、unmapped <= 5%、snapshot age <= 180d。

## 6. P2F 执行记录

日期: 2026-06-14

本轮完成了两项同库数据准备:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains benchmark-validation-import `
  --benchmark-validation-db data\benchmark_validation.sqlite `
  --db-path data\fund_research.duckdb
```

结果:

| entity | requested | inserted | updated | skipped |
|---|---:|---:|---:|---:|
| `benchmark_index_member` | 800 | 800 | 0 | 0 |
| `stock_industry_membership` | 2165 | 2165 | 0 | 0 |
| `benchmark_industry_weight` | 59 | 59 | 0 | 0 |

```powershell
.venv\Scripts\fund-research.exe update `
  --domains holding-industry-backfill `
  --fund-code 000001 `
  --report-date 2026-03-31 `
  --db-path data\fund_research.duckdb
```

结果:

| entity | requested | updated | skipped |
|---|---:|---:|---:|
| `fund_holding_industry_backfill` | 10 | 10 | 0 |

回填后的 `000001` 2026Q1 持仓行业:

| stock_code | industry |
|---|---|
| `300308` | 通信 |
| `688012` | 电子 |
| `688347` | 电子 |
| `002371` | 电子 |
| `688019` | 电子 |
| `688041` | 电子 |
| `688120` | 电子 |
| `688256` | 电子 |
| `688072` | 电子 |
| `688361` | 电子 |

重跑真实动态归因:

```text
experiment_name = p2f-real-sample-000001-after-data-sync
algorithm_name = dynamic_attribution
parameters = {"benchmark_symbol": "sh000300"}
sample_fund_codes = ["000001"]
```

结果:

```text
status = failed
fund_code = 000001
is_success = false
error_message = 缺少可用基准行业权重: sh000300
warnings = ["2026-03-31 缺少基准行业权重: sh000300"]
metrics = {}
```

结论:

- 同库数据导入链路通过。
- 基金持仓行业回填链路通过。
- 动态归因仍未通过，剩余阻塞是 **缺少不晚于 `2026-03-31` 的 `sh000300` 基准行业权重快照**。
- 当前 `benchmark_industry_weight` 只有 `2026-05-29` 快照；按 look-ahead gate，不能用于 2026Q1 报告期。

下一步只剩两个合理选择:

1. 获取 `2026-03-31` 或更早且不超过 180 天的新鲜 `sh000300` 历史行业权重快照。
2. 改选报告期不早于 `2026-05-29` 的真实基金持仓样本。

## 7. P2G 运行条件检查器

日期: 2026-06-14

新增 CLI:

```powershell
.venv\Scripts\fund-research.exe check-dynamic-attribution `
  --fund-code 000001 `
  --benchmark-symbol sh000300 `
  --db-path data\fund_research.duckdb
```

检查范围:

- 股票持仓是否存在。
- 持仓行业是否已回填。
- 持仓股票行情是否覆盖；与算法一致，`daily_return` 为空但 `close_price` 可用时也视为可推导收益。
- 基准指数行情是否覆盖。
- 基准行业权重是否存在不晚于报告期的可用快照。
- 基准行业权重快照是否超过 180 天新鲜度上限。
- 基准行业权重覆盖率是否达到算法 gate。

当前主库检查结果:

| 字段 | 值 |
|---|---|
| fund_code | `000001` |
| report_date | `2026-03-31` |
| benchmark_symbol | `sh000300` |
| holding_count | `10` |
| missing_industry_count | `0` |
| stock_return_weight_coverage | `100.0%` |
| benchmark_return_observations | `41` |
| benchmark_weight_snapshot_date | `None` |
| benchmark_weight_future_snapshot_date | `2026-05-29` |
| is_ready | `False` |
| issues | `缺少不晚于报告期的基准行业权重: sh000300；最近未来快照 2026-05-29` |

结论:

- 同库数据链路、持仓行业回填、持仓与基准行情覆盖已经满足本样本的动态归因运行条件。
- 仍然不能继续把该样本当作通过样本，因为 `2026-05-29` 基准行业权重晚于 `2026-03-31` 报告期。
- 后续在扩展动态归因样本前，先运行 `check-dynamic-attribution --require-ready`，避免实验运行后才发现基础数据不满足 gate。

### 候选样本发现扩展

新增过滤参数:

- `--min-report-date YYYY-MM-DD`: 只检查不早于该日期的报告期。
- `--max-report-date YYYY-MM-DD`: 只检查不晚于该日期的报告期。
- `--ready-only`: 只输出已满足运行条件的样本。
- `--limit N`: 限制输出候选数量。
- `--json`: 输出 JSON，便于脚本或前端调试读取。

示例:

```powershell
.venv\Scripts\fund-research.exe check-dynamic-attribution `
  --benchmark-symbol sh000300 `
  --min-report-date 2026-05-29 `
  --ready-only `
  --limit 5 `
  --json `
  --db-path data\fund_research.duckdb
```

当前主库结果:

```json
{
  "ready": 0,
  "total": 0,
  "rows": []
}
```

同时新增 v2 Tool API:

```text
GET /api/v2/experiments/dynamic-attribution/readiness
```

支持 query 参数:

- `fund_code`
- `benchmark_symbol`
- `min_report_date`
- `max_report_date`
- `min_return_observations`
- `max_snapshot_age_days`
- `ready_only`
- `limit`

该 API 返回统一 `APIResponse`，其中 `data.rows` 与 CLI JSON 行结构一致。

### 从 ready 样本创建实验

新增 runner 参数:

- `report_date`: 单个报告期。
- `report_dates`: 多个报告期。
- `min_report_date`: 最早报告期。
- `max_report_date`: 最晚报告期。

动态归因 runner 会先按这些参数过滤 `fund_disclosed_holdings`，再构造行业权重和收益序列。这样 readiness 按报告期筛出的样本，可以安全转成实验参数，不会被同基金其他旧报告期拖失败。

新增 CLI:

```powershell
.venv\Scripts\fund-research.exe create-dynamic-attribution-experiment `
  --report-date 2026-06-01 `
  --benchmark-symbol sh000300 `
  --db-path data\fund_research.duckdb
```

行为:

- 只检查指定 `--report-date` 的 ready 样本。
- 找到样本时创建 `dynamic_attribution` pending 实验。
- 实验参数自动写入 `report_dates=[report_date]`、`min_return_observations`、`max_benchmark_weight_snapshot_age_days`。
- 找不到样本时返回非零退出码，且不创建实验。

当前主库结果:

```text
未找到满足动态归因运行条件的样本，未创建实验
```

新增 v2 Tool API:

```text
POST /api/v2/experiments/dynamic-attribution/from-ready
```

请求体示例:

```json
{
  "experiment_name": "ready attr",
  "report_date": "2026-06-01",
  "benchmark_symbol": "sh000300",
  "limit": 10
}
```

返回:

- 有 ready 样本: 创建实验并返回 `experiment_id`、`sample_fund_codes`、`parameters`。
- 无 ready 样本: 返回 `needs_review`，不创建实验。

## 8. P2H 新报告期抓取尝试

日期: 2026-06-14

目标: 尝试补或抓一个 `2026-05-29` 之后报告期的真实基金持仓样本，然后用 `create-dynamic-attribution-experiment` 创建实验并跑真实动态归因闭环。

### 执行记录

先用 AKShare 按 2026 年重新抓取样本基金持仓:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains fund-holdings `
  --report-date 2026-06-01 `
  --db-path data\fund_research.duckdb
```

结果:

| entity | requested | inserted | updated | skipped |
|---|---:|---:|---:|---:|
| `fund_holdings` | 30 | 329 | 68 | 0 |

实际报告期分布:

| report_date | fund_count | row_count |
|---|---:|---:|
| `2026-03-31` | 30 | 397 |

结论: 截至 `2026-06-14`，当前 AKShare 持仓接口仍只返回 `2026Q1 / 2026-03-31` 披露持仓；没有 `2026-05-29` 之后的正式基金披露报告期。不能人为把 Q1 持仓改标为 2026-06 报告期。

随后补齐 Q1 样本池的行业和行情:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains holding-industry-backfill `
  --report-date 2026-03-31 `
  --db-path data\fund_research.duckdb
```

结果:

| entity | requested | updated | skipped |
|---|---:|---:|---:|
| `fund_holding_industry_backfill` | 397 | 306 | 91 |

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-daily `
  --start 2026-03-31 `
  --end 2026-06-14 `
  --db-path data\fund_research.duckdb
```

结果:

| entity | requested | inserted | updated | skipped |
|---|---:|---:|---:|---:|
| `stock_daily` | 266 | 12240 | 410 | 13 |

### Readiness 汇总

对 `2026-03-31`、`sh000300` 运行 readiness:

| 指标 | 值 |
|---|---:|
| 样本基金报告期 | 30 |
| ready 样本 | 0 |
| 缺少不晚于报告期的基准行业权重 | 30 |
| 存在持仓行业缺失 | 21 |
| 股票行情覆盖不足 | 3 |

已有 9 个样本的持仓行业、股票行情、基准行情都满足，唯一阻塞是 `sh000300` 基准行业权重快照:

| fund_code | report_date | holding_count | missing_industry | stock_coverage | benchmark_obs | blocking_issue |
|---|---|---:|---:|---:|---:|---|
| `000001` | `2026-03-31` | 10 | 0 | 100.0% | 41 | 缺少不晚于报告期的 `sh000300` 基准行业权重 |
| `000978` | `2026-03-31` | 10 | 0 | 100.0% | 41 | 同上 |
| `110022` | `2026-03-31` | 13 | 0 | 100.0% | 41 | 同上 |
| `260108` | `2026-03-31` | 14 | 0 | 100.0% | 41 | 同上 |
| `340007` | `2026-03-31` | 10 | 0 | 100.0% | 41 | 同上 |
| `450002` | `2026-03-31` | 10 | 0 | 100.0% | 41 | 同上 |
| `519068` | `2026-03-31` | 10 | 0 | 100.0% | 41 | 同上 |
| `519712` | `2026-03-31` | 10 | 0 | 100.0% | 41 | 同上 |
| `519736` | `2026-03-31` | 11 | 0 | 100.0% | 41 | 同上 |

创建实验门禁:

```powershell
.venv\Scripts\fund-research.exe create-dynamic-attribution-experiment `
  --report-date 2026-03-31 `
  --benchmark-symbol sh000300 `
  --db-path data\fund_research.duckdb
```

结果:

```text
未找到满足动态归因运行条件的样本，未创建实验
```

### 结论

- `2026-05-29` 之后报告期的真实基金披露持仓当前不可得，不能完成这一路径的真实动态归因闭环。
- Q1 真实样本池已扩到 30 只基金，并补齐了大部分行业和行情数据。
- 当前真实闭环唯一关键阻塞仍是历史基准行业权重: 需要 `2026-03-31` 或更早且不超过 180 天的 `sh000300` 成分权重快照。
- 不能把 `2026-05-29` 最新快照倒填为 `2026-03-31`，否则会引入 look-ahead，违反当前 gating。

下一步应二选一:

1. 获取并本地导入 `2026-03-31` 可用的中证 `sh000300` 历史成分权重文件，再聚合 `benchmark_industry_weight`。
2. 等待 `2026-06-30` 后正式披露的基金持仓数据出现，再走 `2026-05-29` 快照之后的新报告期闭环。

## 9. P2I 历史成分权重文件检索

日期: 2026-06-14

目标: 获取 `2026-03-31` 或更早且不超过 180 天的真实中证 `sh000300` 成分权重文件，用于 Q1 动态归因真实闭环。

### 官方公开文件与归档

当前中证公开 `closeweight` URL 是覆盖式最新文件:

```text
https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls
```

该路径当前本地已有 `2026-05-29` 快照，晚于 `2026-03-31` 报告期，不能用于 Q1。

查询 Internet Archive CDX:

```powershell
curl.exe -L "https://web.archive.org/cdx?url=https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls&output=json&fl=timestamp,original,statuscode,mimetype,digest&filter=statuscode:200&from=202501&to=202604"
```

返回可用归档:

| archive_timestamp | source_url | status | mime | digest |
|---|---|---:|---|---|
| `20250109075310` | 中证 `000300closeweight.xls` | 200 | `application/vnd.ms-excel` | `IUIV7TNMYMP5BT6G5SM72YS3DYRRB3XW` |
| `20250622134710` | 中证 `000300closeweight.xls` | 200 | `application/vnd.ms-excel` | `N5A3475ZJAI3GXMZWVYHJOH6ROR3TI6P` |

继续查询 `2025-10` 到 `2026-03`:

```powershell
curl.exe -L "https://web.archive.org/cdx?url=https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls&output=json&fl=timestamp,original,statuscode,mimetype,digest&filter=statuscode:200&from=202510&to=202604"
```

结果:

```json
[]
```

### 下载并核验最近早于报告期的归档文件

下载:

```powershell
curl.exe -L "https://web.archive.org/web/20250622134710id_/https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls" `
  --output data\local\000300closeweight_20250622_webarchive.xls
```

本地文件:

```text
data/local/000300closeweight_20250622_webarchive.xls
```

该目录已在 `.gitignore`，不会提交第三方原始数据。

Excel 核验:

| 字段 | 值 |
|---|---|
| rows | 300 |
| columns | 10 |
| 文件内 `日期Date` | `20250530` |
| 指数代码 | `300` |
| 指数名称 | `沪深300` |
| 权重列 | `权重(%)weight` |

结论:

- 归档文件是真实中证 `sh000300` 成分权重文件。
- 但文件内日期是 `2025-05-30`，距离 `2026-03-31` 为 305 天。
- 当前动态归因 gate 的最大快照年龄是 180 天，因此该文件不能用于默认真实闭环。
- 未导入主库，避免把过旧权重误标为可用。

### Tushare 可能路径

Tushare Pro 的 `index_weight` 通常可以获取历史指数权重，但当前本地没有配置:

```text
FUND_TUSHARE_TOKEN=NOT_SET
TUSHARE_TOKEN=NOT_SET
.env=NOT_FOUND
```

若后续提供 Tushare token，可以新增或临时使用 `index_weight(index_code='000300.SH', start_date='20250331', end_date='20250331')` 一类接口抓取历史权重，再按当前 `benchmark-members -> stock-industry -> benchmark-industry` 链路入库验收。

### 当前结论

截至本轮检索，未拿到满足 gate 的 `2026-03-31` 前后 `sh000300` 历史成分权重文件。真实动态归因闭环仍不能通过。下一步需要:

1. 用户提供官方/行情软件/Tushare 导出的 `2026-03-31` 附近 `sh000300` 成分权重文件；或
2. 配置 Tushare token 后抓取历史 `index_weight`；或
3. 等待 `2026-06-30` 基金持仓披露后，用已入库 `2026-05-29` 中证权重快照走新报告期闭环。
