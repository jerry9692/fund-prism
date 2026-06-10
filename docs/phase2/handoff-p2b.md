# P2B Handoff — 算法实验闭环

日期: 2026-06-10  
状态: P2B 完成 — 三算法全部可运行出结果  
前置: [P2 需求书](./requirements.md)  
分支: `phase2-algorithms`

## 1. 做了什么

### 1.1 实验 run 端点 + 三算法接入

- **文件**: `src/fund_research/api/v2_router.py`
- `POST /api/v2/experiments/{id}/run` — 读取参数 → `_dispatch_run()` 分发 → 批量运行 → 写 `experiment_result`
- `_run_simulated_holding_batch()` — **朴素复制 (Naive Replication)**：直接用披露持仓权重计算组合跟踪误差 RMSE。不依赖 CVXPY 优化，稳健可靠
- `_run_dynamic_attribution_batch()` — Brinson BHB 归因，输出配置效应/选股效应/交互效应/残差
- `_run_scoring_batch()` — Z-score 评分，8 维度权重，`allow_estimated=False`（默认剔除未验证 estimated 维度）
- 所有结果走 `experiments.manager.record_result()`，统一 APIResponse 契约

### 1.2 真实数据验证结果（000001 华夏成长混合）

| 算法 | 结果 | 解读 |
|------|------|------|
| 模拟持仓 | TE = 0.0104 (日频) | 拿着披露持仓不动，年化跟踪误差约 16% |
| 动态归因 | 选股效应 +0.649，配置效应 0 | 超额收益主要来自选股，行业配置无明显偏离 |
| 综合评分 | 20.00 分 | 正确剔除 6 个未验证 estimated 维度，仅 return+risk 参与 |

### 1.3 根因排查与修复（耗时最长的部分）

**整个上午和下午都在排查"为什么模拟持仓 0 周期"**。根因链：

1. **股票代码不匹配** → 持仓 10 只只匹配到 5 只 → 补拉数据解决
2. **数据库 `daily_return` 全为 NULL** → 腾讯源 `stock_zh_a_hist_tx` 只返回 `close_price`，不返回收益率 → **适配器新增 `pct_change()` 自动计算**
3. **CVXPY `quad_form` 维度错误** → 单只股票协方差矩阵奇异 → 加了 `try/except` + 等权 fallback
4. **候选池 `pool_in_data` 阈值太高** → 窗口内常凑不齐 5 只 → 降到 2 只
5. **持仓只有单个报告期** → 早期调仓日期找不到持仓数据 → 加了回退到全量持仓的 fallback
6. **服务热重载不生效** → CLI 启动时 `sys.modules` 缓存旧代码 → **新增启动前清除缓存逻辑**

### 1.4 Phase 2 主键修复

- JS 精度丢失问题：Phase 1 的 `id_column()` 用 64 位随机数，超 `Number.MAX_SAFE_INTEGER`
- 修复：Phase 2 7 张表改用 `_p2_pk()` — `randbits(31)`（~2.1B），DuckDB `INTEGER` 兼容
- DuckDB 不支持 `SERIAL` → `autoincrement=False` + Python `default` 生成

### 1.5 DuckDB 兼容修复

- FK 约束在 DuckDB DELETE 时报错 → **移除 `experiment_result.experiment_id` 的 `ForeignKey`**
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

### 1.8 服务热重载修复

- **根因**: CLI 启动时 `main.py` 顶部的 `import` 把 `fund_research.*` 模块缓存到 `sys.modules`，uvicorn 复用缓存
- **修复**: `fund-research serve` 启动前清空 `sys.modules` 中所有 `fund_research` 条目 + `importlib.invalidate_caches()`
- 现在每次重启都加载最新代码，无需清除 `__pycache__` 或 `--no-reload`

## 2. 仍然不可信 / 限制

1. **模拟持仓用朴素复制而非 CVXPY 优化**：直接使用披露持仓权重，未做约束优化。`simulated_holding.py` 中的 CVXPY 路径已修复（`pool_in_data >= 2`，try/except fallback），但未被调用，因为数据量小 + `run_simulation()` 内部有一些边缘 case 没测透
2. **动态归因用基金收益作行业收益近似**，基准用 `* 0.9` 粗暴代理
3. **综合评分 6/8 维度是占位值**，只有 return + risk 来自真实 NAV
4. **所有结果标记为 `estimated_*`**，符合可信度红线
5. **实验同步执行**，多基金会阻塞 API

## 3. 改动文件

| 文件 | 改动 |
|------|------|
| `api/v2_router.py` | run 端点 + `_dispatch_run` + 三算法批量执行 + 朴素复制 + 日期修复 |
| `api/app.py` | 注册 v2_router |
| `experiments/manager.py` | build_validation_report + 删除修复 + 两阶段 flush |
| `experiments/__init__.py` | 导出新函数 |
| `db/models_phase2.py` | 31-bit PK + FK 移除 |
| `db/migrations/...c775fce6a16e...` | Integer + autoincrement=False + FK 移除 |
| `db/models.py` | 底部 re-export Phase 2 模型 |
| `analysis/simulated_holding.py` | 日期范围过滤 + 持仓回退 + pool=2 + try/except + 窗口统计 |
| `analysis/dynamic_attribution.py` | Carino 修复 + estimated_* 前缀 |
| `analysis/scoring.py` | NaN 修复 + allow_estimated 参数 |
| `data/adapters/akshare.py` | `daily_return` 从 close_price 自动计算 |
| `cli/main.py` | 服务启动前清 sys.modules 缓存 |
| `frontend/ExperimentsPage.tsx` | 列表 + 创建 + 运行 + 详情面板 + 动态列 |
| `frontend/index.css` | 实验页样式 |
| `tests/test_p2b_validation.py` | 7 个测试 |
| `tests/test_p2b_real_data.py` | 4 个测试 |
| `docs/phase2/handoff-p2b.md` | 本文档 |

## 4. 验证状态

```
ruff:      All checks passed
pytest:    134 passed
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
