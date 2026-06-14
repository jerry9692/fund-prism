# P2C Handoff — 真实行业/基准收益接入

日期: 2026-06-10 (更新 2026-06-14)
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
- `uses_proxy_benchmark_weights = false`
- `uses_real_benchmark_weights = true`
- `benchmark_symbol`
- `benchmark_source`
- `normalized_weight_sum_by_report`
- `min_stock_weight_coverage`
- `return_observation_count_by_report`
- `benchmark_weight_snapshot_by_report`
- `benchmark_weight_coverage_by_report`
- `benchmark_weight_unmapped_pct_by_report`
- `benchmark_only_sector_count_by_report`

动态归因现在要求 `benchmark_industry_weight` 中存在可用的真实基准行业权重。缺失或覆盖不足时会失败并进入 `needs_review`，不会再回退到基金披露行业权重。

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
- **真实基准行业权重接入**:
  - 新增 `benchmark_index_member`、`stock_industry_membership`、`benchmark_industry_weight` 表和 Alembic 迁移
  - AKShare adapter 支持指数成分权重、指数成分列表、申万行业成分归一化
  - CLI `update` 新增 `benchmark-members`、`stock-industry`、`benchmark-industry` 域
  - 动态归因 runner 从最近可用 `benchmark_industry_weight` 快照读取 `bench_weight`
  - 基准行业权重覆盖率低于 95% 或缺失时，实验失败并进入 review

## 6. 已完成（2026-06-14）

- **stock-industry 稳定化**:
  - 新增 `--industry-symbol`、`--request-interval`、`--retry`、`--industry-batch-size`
  - 默认行业 symbol 列表从申万三级 `850xxx.SI` 修正为申万一级 `801xxx.SI`
  - symbol 列表缓存改为 `data/cache/stock_industry/sw_level_one_symbols.json`
  - `No tables found` 也会走直接读取乐咕页面 fallback
- **本地行业映射 fallback**:
  - CLI 新增 `--industry-file`
  - 支持 CSV/XLS/XLSX 导入 `stock_industry_membership`
  - 默认 `classification_type=SW`、`classification_version=2021`、`level=1`、`source_level=LOCAL`
  - `data/local/` 已加入 `.gitignore`，本地数据不得提交
- **真实行业权重验收**:
  - 使用巨潮 `stock_industry_change_cninfo` 逐只查询 `sh000300`、`sh000905` 共 800 个成分股
  - 筛选 `分类标准编码=008003`，生成 `data/local/stock_industry_sw.csv`
  - 导入结果: `requested=800, inserted=722, updated=78, skipped=0`
  - 重新聚合后:
    - `sh000300`: 28 个行业，`coverage_pct=100.0%`，`unmapped_weight_pct=0.0%`
    - `sh000905`: 31 个行业，`coverage_pct=100.0%`，`unmapped_weight_pct=0.0%`
- **公开弱对照**:
  - 用 Wikipedia CSI 300 宽行业表做 sanity check
  - 只能证明没有明显全行业错位；正式 1pp 偏差验收仍需同日期、同申万口径的行情软件截图或指数公司行业分布表
- **benchmark-members 本地文件 fallback**:
  - CLI 新增 `--benchmark-members-file`
  - 支持中证 `closeweight.xls` 或标准 CSV/XLSX 本地导入
  - 需要配合且只配合一个 `--index-symbol`

## 7. 下一步

1. 手工补同日期、同申万口径的行情软件/指数公司行业分布截图，对照 `行业名 / 本地权重 / 对照权重 / 差值`
2. 若需要历史日期验收，补中证历史成分权重，或继续明确拒绝晚于目标日期的权重快照
3. 扩展 `FundMain.benchmark` 解析映射，并增加用户 review 配置覆盖机制
4. 把 `dynamic_attribution_result` 表也接入实验结果持久化，而不是只写 `experiment_result.metrics`
