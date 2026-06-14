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
