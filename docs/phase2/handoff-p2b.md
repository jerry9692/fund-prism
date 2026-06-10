# P2B Handoff — 算法实验闭环

日期: 2026-06-10  
状态: P2B 完成 — 三算法全部可运行出结果  
前置: [P2 需求书](./requirements.md)  
分支: `phase2-algorithms`

## 1. 做了什么

### 1.1 实验 run 端点 + 三算法接入

- **入口文件**: `src/fund_research/api/v2_router.py`
- **执行文件**: `src/fund_research/experiments/runner.py`
- `POST /api/v2/experiments/{id}/run` — 读取参数 → `dispatch_run()` 分发 → 批量运行 → 写 `experiment_result`
- `_run_simulated_holding_batch()` — **朴素复制 (Naive Replication)**：直接用披露持仓权重计算组合跟踪误差 RMSE。不依赖 CVXPY 优化，稳健可靠
- `_run_dynamic_attribution_batch()` — Brinson BHB 归因，披露持仓百分比会先转成比例并按报告期归一化，再输出配置效应/选股效应/交互效应/残差
- `_run_scoring_batch()` — Z-score 评分，8 维度权重，`allow_estimated=False`（默认剔除未验证 estimated 维度）
- 所有结果走 `experiments.manager.record_result()`，统一 APIResponse 契约

### 1.2 真实数据验证结果（000001 华夏成长混合）

| 算法 | 结果 | 解读 |
|------|------|------|
| 模拟持仓 | TE = 0.0104 (日频) | 拿着披露持仓不动，年化跟踪误差约 16% |
| 动态归因 | estimated 指标 + proxy warning | 行业收益和基准收益仍为代理值，只能作为算法链路验证 |
| 综合评分 | 20.00 分 | 正确剔除 6 个未验证 estimated 维度，仅 return+risk 参与 |

### 1.3 根因排查与修复（耗时最长的部分）

**整个上午和下午都在排查"为什么模拟持仓 0 周期"**。根因链：

1. **股票代码不匹配** → 持仓 10 只只匹配到 5 只 → 补拉数据解决
2. **数据库 `daily_return` 全为 NULL** → 腾讯源 `stock_zh_a_hist_tx` 只返回 `close_price`，不返回收益率 → **适配器新增 `pct_change()` 自动计算**
3. **CVXPY `quad_form` 维度错误** → 单只股票协方差矩阵奇异 → 加了 `try/except` + 等权 fallback
4. **候选池 `pool_in_data` 阈值太高** → 窗口内常凑不齐 5 只 → 降到 2 只
5. **持仓只有单个报告期** → 早期调仓日期找不到持仓数据 → 加了回退到全量持仓的 fallback
6. **服务热重载不生效** → 曾尝试在 CLI 清 `sys.modules`，后续审计认为该 workaround 风险较高，已移除；开发时依赖正常重启/uvicorn reload

### 1.4 Phase 2 主键/FK 修复

- Phase 2 表恢复使用项目统一的 `id_column()`（BigInteger + Python 端生成），避免 ORM 和 Alembic schema 不一致
- API/前端边界继续把 ID 当作字符串处理，避免 JS 大整数精度问题
- `experiment_result.experiment_id` 恢复 FK；删除实验时先删除子结果并 `flush()`，再删除父实验

### 1.5 DuckDB 兼容修复

- FK 约束下 DELETE 需先删子表 → manager 使用子结果先删 + flush 的顺序
- 日期比较 `Timestamp vs date` 报错 → `nav_df["trade_date"]` 统一转 `pd.Timestamp`
- WAL 文件锁 → `git add -A` 时排除

### 1.6 前端实验管理页

- 列表展示 + 创建表单（名称/算法/基金代码，默认 `000001`）
- "运行"按钮即时切换状态为"运行中"
- 详情面板动态显示所有指标（不限模拟持仓专用字段）
- 选中行高亮 + 操作按钮组

### 1.7 `build_validation_report()`

- **文件**: `src/fund_research/experiments/manager.py`
- 从实验结果提取：均值 TE / recall / IC / success_rate
- 输出: `experiment_summary` + `aggregate_stats` + `per_fund` + `overall_conclusion` (pass/partial/fail)

### 1.8 P2 审计后的收口修复

- `v2_router.py` 只保留 API 入口、状态更新、响应包装和日志，实验执行逻辑拆入 `experiments/runner.py`
- 移除 CLI `serve` 中清空 `sys.modules` 的临时 workaround，避免启动路径出现不可预测副作用
- 前端实验页移除 `console.log` / `alert` / `confirm`，改为页面内错误提示和二次删除确认
- 动态归因写入 `uses_proxy_benchmark`、`uses_proxy_sector_returns` 和 proxy warning，避免把 P2B 代理结果误当正式归因
- 动态归因披露持仓权重已从百分数转为比例，并按报告期归一化；metrics 输出 `normalized_weight_sum_by_report`

## 2. 仍然不可信 / 限制

1. **模拟持仓用朴素复制而非 CVXPY 优化**：直接使用披露持仓权重，未做约束优化。`simulated_holding.py` 中的 CVXPY 路径已修复（`pool_in_data >= 2`，try/except fallback），但未被调用，因为数据量小 + `run_simulation()` 内部有一些边缘 case 没测透
2. **动态归因用基金收益作行业收益近似**，基准用 `* 0.9` 粗暴代理；权重已归一化，但数据源仍不足以支持正式归因结论
3. **综合评分 6/8 维度是占位值**，只有 return + risk 来自真实 NAV
4. **所有结果标记为 `estimated_*`**，符合可信度红线
5. **实验同步执行**，多基金会阻塞 API

## 3. 改动文件

| 文件 | 改动 |
|------|------|
| `api/v2_router.py` | v2 Tool API 入口、实验 CRUD、run 状态管理、统一响应 |
| `api/app.py` | 注册 v2_router |
| `experiments/runner.py` | `dispatch_run` + 三算法批量执行 + 朴素复制 + 动态归因权重归一化 |
| `experiments/manager.py` | build_validation_report + 删除修复 + 两阶段 flush |
| `experiments/__init__.py` | 导出新函数 |
| `db/models_phase2.py` | 恢复统一 BigInteger PK + experiment_result FK |
| `db/migrations/...c775fce6a16e...` | BigInteger PK + experiment_result FK |
| `db/models.py` | 底部 re-export Phase 2 模型 |
| `analysis/simulated_holding.py` | 日期范围过滤 + 持仓回退 + pool=2 + try/except + 窗口统计 |
| `analysis/dynamic_attribution.py` | Carino 修复 + estimated_* 前缀 |
| `analysis/scoring.py` | NaN 修复 + allow_estimated 参数 |
| `data/adapters/akshare.py` | `daily_return` 从 close_price 自动计算 |
| `cli/main.py` | 移除服务启动前清 `sys.modules` 的临时 workaround |
| `frontend/ExperimentsPage.tsx` | 列表 + 创建 + 运行 + 详情面板 + 动态列 |
| `frontend/index.css` | 实验页样式 |
| `tests/test_p2b_validation.py` | P2B 验收测试，含失败记录、估算字段、动态归因 proxy 与权重归一化保护 |
| `tests/test_p2b_real_data.py` | 4 个测试 |
| `docs/phase2/handoff-p2b.md` | 本文档 |

## 4. 验证状态

```
ruff:      All checks passed
pytest:    137 passed
npm build: ✓ built
```

## 5. 下一步

| 优先级 | 任务 |
|--------|------|
| P1 | CVXPY 路径验证（拉更多股票后切回 `simulated_holding.py` 的优化路径） |
| P1 | 专家 code review |
| P2 | 合并到 main |
| P2 | 动态归因接入真实行业基准数据 |
| P3 | 实验异步执行 |
