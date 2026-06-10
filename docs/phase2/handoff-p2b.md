# P2B Handoff — 算法实验闭环

日期: 2026-06-10  
状态: P2B 最小闭环完成  
前置: [P2 需求书](./requirements.md)

## 1. 本轮做了什么

### 1.1 新增 `POST /api/v2/experiments/{id}/run`

- **文件**: `src/fund_research/api/v2_router.py`（+120 行）
- 读取实验参数 → 分发到对应算法执行函数 → 逐基金运行 → 记录结果到 `experiment_result` 表
- 当前支持 `simulated_holding`；`dynamic_attribution` 和 `scoring` 待后续接入
- 执行完更新实验状态为 `completed`；异常时标记 `failed` 并保留错误信息
- 所有结果通过 `experiments.manager.record_result()` 写入，不绕过统一接口

### 1.2 P2B 验收测试

- **文件**: `tests/test_analysis/test_p2b_validation.py`（~250 行，5 个测试）
- 测试分类：

| 测试 | 验证内容 |
|------|---------|
| `test_backtest_report_has_required_fields` | `to_api_data()` 输出包含 `estimated_overall_tracking_error`、`confidence`、`periods` 等必填字段 |
| `test_estimated_fields_not_mislabeled_as_computed` | 模拟持仓输出不标 `fact`/`computed`，遵守可信度红线 |
| `test_estimated_fields_present_in_api_output` | 单期输出使用 `estimated_tracking_error` 前缀 |
| `test_run_experiment_endpoint_creates_and_executes` | E2E：创建实验 → 执行 → 检查 DB 中有实验记录且含 `estimated_overall_tracking_error` |
| `test_run_experiment_unknown_algorithm_returns_failure` | 未接入的算法返回失败结果，不静默吞错 |

### 1.3 可信度红线落地

- 模拟持仓的 API 输出全部使用 `estimated_*` 命名（`estimated_overall_tracking_error`、`estimated_tracking_error`、`estimated_holdings` 等）
- `conclusion_status` 不使用 `fact`/`computed`
- `run_experiment` 端点对失败的基金记录完整的 `error_message`
- 测试明确断言"不应标记为 fact/computed"

## 2. 改动文件清单

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `src/fund_research/api/v2_router.py` | 新增 run 端点 + 分发 + 批量执行 | +120 |
| `tests/test_analysis/test_p2b_validation.py` | 新增 P2B 验收测试 | +250 |

## 3. 验证状态

```
ruff:      All checks passed
pytest:    128 passed
check-data: 未改，上次通过
npm build: 未改前端，上次通过
```

## 4. 仍然不可信/需要继续验证的地方

1. **模拟持仓用合成数据验证，未用真实 AKShare 数据**：5 个测试用的是正态分布随机收益率，真实基金的行业相关性和换手特征完全不同。下一步应该拉 2-3 只样本基金的净值 + 持仓入 DuckDB，通过 API 实际跑一遍。
2. **`dynamic_attribution` 和 `scoring` 未接入 run 端点**：`_dispatch_run` 中已预留分支，但目前返回"尚未接入"。这两个算法同样需要通过实验闭环验证。
3. **回测阈值是经验值**：`tracking_error < 0.08` 和 `top10_recall > 0.3` 是初步设定，未经过大量样本校准。
4. **实验执行是同步的**：对于 30 只样本基金，模拟持仓每次优化 ~2 秒，跑完全部约需 1 分钟。尚不支持异步执行，API 会阻塞。
5. **验收报告未持久化到独立的 validation_report 表**：当前结果写入 `experiment_result.metrics`（JSON 字段），结构化的 `build_validation_report()` 函数未实现。建议 P2C 阶段追加。

## 5. 怎么继续

| 优先级 | 任务 | 预计改动 |
|--------|------|---------|
| P0 | 用真实 AKShare 数据验证 2-3 只基金的模拟持仓回测 | 拉数据 + 手动跑 API |
| P1 | 接入 `dynamic_attribution` 到 run 端点 | `v2_router.py` +60 行 |
| P1 | 接入 `scoring` 到 run 端点 | `v2_router.py` +40 行 |
| P2 | 实现 `build_validation_report()` | `experiments/manager.py` +30 行 |
| P2 | 前端实验详情页展示结果 | `frontend/` 新增页面 |
| P3 | 异步执行支持 | 后续 |

## 6. 提交方式

改动在 `phase2-algorithms` 分支（或新分支）。`ruff` + `pytest` 通过后方可合并。
