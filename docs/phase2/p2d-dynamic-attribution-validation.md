# P2D Dynamic Attribution Validation

日期: 2026-06-14
范围: 真实基准行业权重接入后的动态归因端到端验收

## 1. 目标

P2D 的目标不是继续扩数据源或前端功能，而是确认动态归因已经真正信任
`benchmark_industry_weight`，并且在缺失或低质量数据时不会退回到 P2B 的代理口径。

验收重点:

- 基金披露持仓按报告期归一化为组合行业权重。
- 持仓股票真实 `stock_daily.daily_return` 聚合为组合行业收益。
- 基准指数真实 `stock_daily.daily_return` 生成每期基准收益。
- `benchmark_industry_weight` 提供基准行业权重，覆盖率低于 95% 时拒绝使用。
- 基准有、组合没有的行业会被保留为 `port_weight = 0` 的 benchmark-only sector。
- 输出只写入 `estimated_*` 字段，不进入 fact/computed 结论语义。

## 2. 自动化验收

新增/收紧测试:

- `tests/test_analysis/test_p2b_real_data.py::TestRealDataPipeline::test_dynamic_attribution_with_real_structure`

测试数据结构:

- 基金: `000001` 的 4 个季度披露持仓。
- 持仓行业: `电子`、`国防军工`、`通信`。
- 基准: `sh000300`。
- 基准行业权重: 每个报告期都有独立 `benchmark_industry_weight` 快照。
- 基准独有行业: `银行`，用于验证 benchmark-only sector 不会被丢弃。
- 行情: 股票和指数行情覆盖 2024 全年和 Q4 后续归因窗口。

强制断言:

- 实验状态必须是 `completed`，单基金结果必须 `is_success = true`。
- `uses_real_benchmark_returns = true`。
- `uses_real_sector_returns = true`。
- `uses_real_benchmark_weights = true`。
- `uses_proxy_benchmark = false`。
- `uses_proxy_sector_returns = false`。
- `uses_proxy_benchmark_weights = false`。
- 4 个报告期的 `normalized_weight_sum_by_report` 均为 `1.0`。
- 4 个报告期使用各自同日基准行业权重快照。
- 4 个报告期的 `coverage_pct = 100.0`、`unmapped_weight_pct = 0.0`。
- 4 个报告期的 `benchmark_only_sector_count = 1`。
- `period_count = 4`。
- warnings 中不得出现 P2B 代理或基准权重暂用提示。

## 3. 运行命令

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\test_analysis\test_p2b_real_data.py::TestRealDataPipeline::test_dynamic_attribution_with_real_structure `
  tests\test_analysis\test_p2b_validation.py::TestRunExperimentPipeline::test_run_dynamic_attribution_records_estimated_fields `
  tests\test_analysis\test_p2b_validation.py::TestRunExperimentPipeline::test_run_dynamic_attribution_without_benchmark_weights_fails `
  -q
```

建议提交前仍跑完整测试:

```powershell
.venv\Scripts\python.exe -m pytest
```

## 4. 当前边界

- 自动化测试使用结构真实、数值合成的数据，不替代公开同口径行业分布偏差验收。
- `benchmark_industry_weight` 的生产数据仍依赖指数成分权重、股票行业归属和本地文件 fallback 的稳定性。
- 公开 sanity check 只能证明大方向没有全行业错位；正式验收仍需要同日期、同申万一级口径的外部对照。
- 动态归因结果继续保持 `estimated_*`，不得接入默认高置信结论或综合评分。

## 5. 下一步建议

1. 用本地 `data/benchmark_validation.sqlite` 选择 1-2 只真实基金跑动态归因手工验收。
2. 记录每期 `benchmark_weight_snapshot_by_report` 与基金报告期的距离，防止误用太旧快照。
3. 前端实验结果页展示 `uses_real_*`、coverage、unmapped、benchmark-only sector 数量。
4. 等真实样本验收稳定后，再考虑产品化动态归因解释文本。
