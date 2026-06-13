# P2C Handoff — 真实行业/基准收益接入

日期: 2026-06-10 (更新 2026-06-13)
分支: 已合并到 `main`
基线: `main` 已包含 P2B 修复

## 1. 本轮目标

把动态归因从 P2B 的代理收益升级为真实行情驱动：

- 行业收益：由基金披露持仓股票的真实 `stock_daily.daily_return` 聚合得到
- 基准收益：由真实指数行情 `stock_daily.stock_code = benchmark_symbol` 复合得到
- 默认基准：`sh000300`
- 不再使用基金收益代理行业收益，也不再使用 `period_return * 0.9` 代理基准收益

## 2. 实现说明

### 2.1 动态归因 runner

文件: `src/fund_research/experiments/runner.py`

- `dynamic_attribution` 支持实验参数 `benchmark_symbol`，缺省为 `sh000300`
- 未显式传 `benchmark_symbol` 时，会从 `FundMain.benchmark` 轻量识别 `沪深300`、`中证500`、`中证1000`
- 读取基金披露股票持仓，按报告期把 `weight_pct` 转为 0-1 权重并归一化
- 读取持仓股票和基准指数的 `StockDaily` 行情
- 若 `daily_return` 缺失，会从 `close_price` 回算
- 每个报告期窗口使用 `[report_date, next_report_date)`，最后一期使用 3 个月窗口
- 行业收益按行业内可用股票收益加权聚合
- 基准收益用指数日收益复合

### 2.2 数据完整性 gating

现在缺少真实行情时会失败，不再静默回退到代理：

- 无持仓股票行情或基准指数行情: `failed + needs_review`
- 缺少指定 `benchmark_symbol`: `failed + needs_review`
- 基准窗口收益样本不足: 该窗口跳过
- 持仓股票行情权重覆盖率低于 80%: `failed + needs_review`

### 2.3 输出语义

成功结果会写入:

- `uses_real_sector_returns = true`
- `uses_real_benchmark_returns = true`
- `uses_proxy_sector_returns = false`
- `uses_proxy_benchmark = false`
- `uses_proxy_benchmark_weights = true`
- `benchmark_symbol`
- `benchmark_source`
- `normalized_weight_sum_by_report`
- `min_stock_weight_coverage`
- `return_observation_count_by_report`

重要限制: 真实基准行业权重尚未接入。当前 Brinson 中 `bench_weight` 仍暂用基金披露行业权重，因此 allocation effect 不能作为正式基准行业配置判断。

## 3. 测试

新增/更新:

- 动态归因成功路径要求真实持仓股票收益 + 真实 `sh000300` 指数收益
- 缺少基准指数行情时必须失败，不能回退到 P2B proxy
- 真实结构 E2E seed 增加 `sh000300` 指数行情

## 4. 已完成（2026-06-12）

- **前端参数输入**: `ExperimentsPage` 已支持 dynamic_attribution 算法的参数输入：
  - `benchmark_symbol` — 基准指数代码，默认 `sh000300`
  - `min_return_observations` — 最小收益观测样本数，默认 `3`，number 类型
  - 选择其他算法时不显示这些字段，参数传 `{}`

## 5. 已完成（2026-06-13）

- **P2C 合并**: `codex/p2c-real-benchmark-data` 已合并并推送到 `main`
- **参数落库测试**: API 创建 `dynamic_attribution` 实验时会保存 `benchmark_symbol` 和 `min_return_observations`
- **轻量基准自动解析**:
  - 参数 `benchmark_symbol` 优先
  - 其次从 `FundMain.benchmark` 识别 `沪深300 -> sh000300`、`中证500 -> sh000905`、`中证1000 -> sh000852`
  - 识别失败时回退默认 `sh000300`

## 6. 下一步

1. 接入真实基准行业权重：指数成分、行业分类、成分权重
2. 扩展 `FundMain.benchmark` 解析映射，并增加用户 review 配置覆盖机制
3. 把 `dynamic_attribution_result` 表也接入实验结果持久化，而不是只写 `experiment_result.metrics`
