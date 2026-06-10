# P2B Handoff — 算法实验闭环

日期: 2026-06-10  
状态: P2B 完成 — 三算法实验可运行、可查看、可删除  
前置: [P2 需求书](./requirements.md)  
分支: `phase2-algorithms`

## 1. 本轮做了什么

### 1.1 三个算法全部接入实验 run 端点

- **文件**: `src/fund_research/api/v2_router.py`（重写 ~300 行）
- `POST /api/v2/experiments/{id}/run` — 读取实验参数 → 分发 → 批量运行 → 逐基金写 `experiment_result`
- `_dispatch_run()` — 按 `algorithm_name` 分发到三个执行函数
- `_run_simulated_holding_batch()` — 加载 NAV + 持仓 + 股票数据 → 用披露持仓等权重估算 → 写指标
- `_run_dynamic_attribution_batch()` — Brinson BHB 归因 → 写配置/选股/交互效应
- `_run_scoring_batch()` — Z-score 评分 → 8 维度分项 + 排名
- 所有结果走 `experiments.manager.record_result()`，不绕过统一接口

### 1.2 `build_validation_report()` 标准化验收报告

- **文件**: `src/fund_research/experiments/manager.py`（+110 行）
- 从实验结果批量提取：均值 TE / recall / industry_correlation / success_rate
- 输出: `experiment_summary` + `aggregate_stats` + `per_fund` + `overall_conclusion` + `conclusion_status`
- 整体结论分三级: `pass` (≥80% 成功 + TE < 0.05) / `partial` (≥50%) / `fail`

### 1.3 Phase 2 主键修复

- **文件**: `src/fund_research/db/models_phase2.py`
- 问题: Phase 1 的 `id_column()` 生成 64 位随机整数，JS `Number.MAX_SAFE_INTEGER` 不够用
- 修复: Phase 2 7 张表改用 `_p2_pk()` — 31 位随机整数（~2.1B，在 JS 安全范围），`autoincrement=False`，Python 端 `lambda: randbits(31)` 生成
- 迁移文件同步更新为 `sa.Integer()` + `autoincrement=False`
- DuckDB 不支持 `SERIAL`，不能使用 `autoincrement=True`

### 1.4 DuckDB 兼容修复

- **FK 约束移除**: `experiment_result.experiment_id` 去掉 `ForeignKey`，DuckDB 的 FK 在 DELETE 时兼容性差
- **删除改用两阶段**: 先删子表 `experiment_result`，再删父表 `algorithm_experiment`
- **日期类型统一**: `nav_df["trade_date"]` 统一转 `pd.Timestamp`，避免 `date vs Timestamp` 比较错误

### 1.5 前端实验管理页面完整闭环

- **文件**: `frontend/src/pages/ExperimentsPage.tsx`（重写）
- 列表: 显示 ID/名称/算法/状态/基金数/成功/失败/创建时间
- 创建: 表单含名称、算法下拉、**基金代码输入框**（默认 `000001`），逗号分隔支持多基金
- 运行: 点击即调用 `POST /run`，**即时切换状态为"运行中"**
- 详情: 点击行展开，显示所有指标（动态列，不限模拟持仓专用字段）
- 删除: 确认弹窗 + 错误提示
- 样式: 新增约 30 行 CSS（选中行高亮、操作按钮组、摘要行）

### 1.6 验收测试

| 文件 | 测试数 | 内容 |
|------|--------|------|
| `tests/test_analysis/test_p2b_validation.py` | 7 个 | 回测字段 / 可信度红线 / E2E 管线 / 三种算法 run |
| `tests/test_analysis/test_p2b_real_data.py` | 4 个 | 000001 真实持仓结构 + 日历对齐 NAV + 季度披露模式 |
| `tests/test_api/test_v2_router.py` | 已有 | v2 API 契约 |

## 2. 改动文件汇总

| 文件 | 改动 |
|------|------|
| `src/fund_research/api/v2_router.py` | +400 行（run 端点 + 三算法执行 + 日期修复） |
| `src/fund_research/experiments/manager.py` | +110 行（build_validation_report + delete fix） |
| `src/fund_research/experiments/__init__.py` | +2 行（导出新函数） |
| `src/fund_research/db/models_phase2.py` | PK 重写 + FK 移除 |
| `src/fund_research/db/migrations/...c775fce6a16e...` | 迁移适配（Integer + autoincrement=False + FK 移除） |
| `src/fund_research/analysis/simulated_holding.py` | 日期范围过滤 + 持仓回退 + 窗口跳过统计 |
| `frontend/src/pages/ExperimentsPage.tsx` | 重写（详情面板 + 运行按钮 + 动态列 + 基金代码输入） |
| `frontend/src/index.css` | +30 行（实验页样式） |
| `tests/test_analysis/test_p2b_validation.py` | +250 行 |
| `tests/test_analysis/test_p2b_real_data.py` | +221 行 |
| `docs/phase2/handoff-p2b.md` | 本文档 |

## 3. 验证状态

```
ruff:      All checks passed
pytest:    134 passed
npm build: ✓ built
check-data: 未改
```

## 4. 已知限制与风险

1. **模拟持仓使用等权重简化估算**（`v2_router.py` 内联实现），未调用 CVXPY 优化。原因是真实股票数据太稀疏（5/10 代码匹配，多数窗口候选池不足）。
2. **动态归因**使用基金自身收益作为行业收益近似，基准收益用 `period_return * 0.9` 粗略代理。
3. **综合评分**的 `trading`/`style_stability`/`scale`/`team`/`holder` 维度使用固定占位值（0.0/0.7/0.5/0.5/0.5），只有 `return` 和 `risk` 是从真实 NAV 计算。
4. **所有算法结果标记为 `estimated_*`**，符合 P2 可信度红线。
5. **实验执行是同步的**，每个基金约 2-5 秒，多基金会阻塞 API 响应。

## 5. 下一步建议

| 优先级 | 任务 |
|--------|------|
| P0 | 拉更完整的股票行情数据（覆盖更长历史），解除候选池限制 |
| P1 | 恢复 CVXPY 优化路径（`simulated_holding.py` 阈值降到 1 已可跑） |
| P1 | 前端增加股票行情数据拉取入口（CLI 已有 `--stock-code`，但需知道代码） |
| P2 | 异步执行支持（`run` 端点立即返回，后台执行） |
| P2 | `build_validation_report` 接入前端展示 |
| P3 | 评分回测（IC 分析 + 分层单调性） |
