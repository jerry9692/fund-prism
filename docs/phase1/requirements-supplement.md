# Phase 1 补充需求书 — MVP 验收闭环

版本: v0.1  
日期: 2026-06-08  
前置: [Phase 1 需求书](./requirements.md) | [v0.4 总体需求书](../../AI-oriented开源个人基金研究平台需求书_v0.4.md)

## 1. 文档定位

Phase 1 主体代码已完成（99 测试通过、ruff 零告警、check-data 全过），覆盖了数据接入、分析算法、研究包和 5 个 Tool API。但对照 v0.4 第 16 节的 8 个 MVP 验收场景，仍有若干缺口需要补充才能形成 Phase 1 范围内的 MVP 闭环。

本文档定义 4 个补充模块的需求，范围严格控制在 MVP 验收所需的最小实现。

需要特别说明：v0.4 第 16 节场景 7 包含“筛选基金”和“保存为自选候选池”两个动作。Phase 1 补充只完成可复核的筛选与导出闭环，不新增基金池持久化表或自选池管理；“保存候选池”作为后续基金池/组合管理能力承接。本文后续验收中凡提到场景 7，均指“可筛选并可通过 CSV 导出沉淀候选结果”，不表示已支持持久化自选池。

## 2. 缺口分析

| MVP 场景 | 当前状态 | 缺口 |
|----------|----------|------|
| 1. 搜索基金查看信息 | ✅ 已有 `GET /api/v1/funds/{code}/profile` | — |
| 2. 查看持仓/暴露/归因 | ✅ 已有 `POST /api/v1/analysis/exposure` | — |
| 3. 查看数据质量 | ⚠️ API metadata 有 data_snapshots，但无专用接口 | — |
| 4. 生成 Research Packet | ✅ 已有 `POST /api/v1/research/packet` | — |
| 5. 对比两个日期的 Packet diff | ❌ 未实现 | **补充** |
| 6. Notebook 调用 5 个 API | ✅ 已验证 | — |
| 7. 筛选基金并保存候选池 | ⚠️ 筛选未实现；候选池持久化超出 Phase 1 | **补充筛选；保存候选池延期** |
| 8. 导出 Markdown/JSON/CSV | ⚠️ JSON 在 API 中，无 CLI 导出 | **补充** |

## 3. 补充模块

### 3.1 `screen_funds` — 基金筛选与排序

#### 3.1.1 需求

v0.4 场景 7：

> 用户按近三年收益、最大回撤、基金规模、基金经理任职年限、数据完整度筛选基金，保存为自选候选池。

#### 3.1.2 接口

```
POST /api/v1/funds/screen
```

请求体：

```json
{
  "filters": {
    "category": "混合型-偏股",
    "min_inception_years": 3,
    "min_scale_bn": 1.0,
    "max_scale_bn": null,
    "min_manager_tenure_days": 365,
    "max_mgmt_fee_pct": null,
    "min_data_completeness": 0.6
  },
  "sort_by": "annualized_return_3y",
  "sort_order": "desc",
  "limit": 50,
  "offset": 0
}
```

筛选维度（一期最小集合）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `category` | str | 基金类型筛选 |
| `min_inception_years` | float | 最小成立年限 |
| `min_scale_bn` | float | 最小规模（亿元） |
| `max_scale_bn` | float | 最大规模（亿元） |
| `min_manager_tenure_days` | int | 最小基金经理任职天数 |
| `max_mgmt_fee_pct` | float | 最大管理费率 |
| `min_data_completeness` | float | 最小数据完整度（0-1，根据本地关键模块可用性计算） |

排序维度（一期最小集合）：

| 字段 | 说明 |
|------|------|
| `annualized_return_1y` | 近一年年化收益 |
| `annualized_return_3y` | 近三年年化收益 |
| `max_drawdown_1y` | 近一年最大回撤 |
| `sharpe_ratio_1y` | 近一年夏普比率 |
| `fund_scale` | 基金规模 |
| `manager_tenure_days` | 基金经理任职天数 |
| `inception_date` | 成立日期 |
| `data_completeness` | 数据完整度 |

#### 3.1.3 实现方案

基于现有 ORM 模型，从 `fund_main` 联表查询：

1. 用 `fund_main` 的 `category`/`inception_date` 过滤
2. 用 `fund_scale` 的最新记录过滤规模
3. 用 `fund_manager_tenure` 过滤经理任职天数
4. 用 `fund_fee` 过滤管理费率
5. 排序数据：收益/回撤从 `fund_nav` 计算，或从 `nav_metrics` 预计算结果读取

一期不做"保存筛选模板""基金池管理"——只返回筛选结果列表，并允许通过 `export screen` 导出 CSV 作为本地候选结果沉淀。

#### 3.1.4 验收

1. 可按类型/规模/成立年限/数据完整度筛选，返回基金列表
2. 可按收益/回撤/数据完整度排序
3. 返回结构包含 `{fund_code, short_name, company, category, scale, manager, metrics, data_completeness}`
4. 无匹配时返回空列表而非报错
5. 不声称已保存自选候选池；如需沉淀候选结果，通过 CSV 导出完成

---

### 3.2 `diff_research_packets` — 研究包差异对比

#### 3.2.1 需求

v0.4 场景 5：

> 用户对比同一基金两个日期的 Research Packet diff，看到经理、规模、持仓、风险指标、风格暴露和证据变化。

#### 3.2.2 接口

```
POST /api/v1/research/diff
```

请求体：

```json
{
  "fund_code": "000001",
  "left_snapshot": "2026-03-31",
  "right_snapshot": "2026-06-08"
}
```

或直接传 packet_id：

```json
{
  "left_packet_id": "pkt_abc123",
  "right_packet_id": "pkt_def456"
}
```

#### 3.2.3 输出结构

```json
{
  "data": {
    "fund_code": "000001",
    "left_info": {"packet_id": "...", "data_date": "2026-03-31"},
    "right_info": {"packet_id": "...", "data_date": "2026-06-08"},
    "diffs": {
      "manager": {"changed": true, "detail": "基金经理从 A 变更为 B"},
      "scale": {"changed": true, "left": 26.44, "right": 28.10, "delta_pct": 6.3},
      "nav_metrics": {
        "annualized_return_1y": {"left": 0.123, "right": 0.145, "delta": 0.022}
      },
      "holdings": {
        "new_positions": [{"code": "600519", "name": "贵州茅台", "weight_pct": 3.2}],
        "exited_positions": [{"code": "000858", "name": "五粮液", "weight_pct": 2.1}],
        "weight_changes": [{"code": "002025", "name": "航天电器", "from": 3.46, "to": 4.12}]
      },
      "exposure": {
        "large_cap": {"left": 0.65, "right": 0.72, "delta": 0.07}
      },
      "risk_alerts": {
        "new": ["机构持有比例超过 60%"],
        "resolved": ["基金经理变更"]
      }
    }
  },
  "metadata": {
    "tool": "diff_research_packets",
    "platform_version": "0.1.0"
  }
}
```

#### 3.2.4 实现方案

从 `research_packet` 表取两份 JSON，做字段级递归 diff：

1. 数值字段：计算 delta 和 delta_pct
2. 列表字段（持仓）：识别新增/退出/权重变化
3. 文本字段：标记是否变更
4. 风险提示：识别新增/已消除

#### 3.2.5 验收

1. 可对比同基金两个 packet，展示各模块变化
2. 持仓对比能识别新增/退出/增持/减持
3. 缺少某侧 packet 时返回明确错误
4. 结果附带 metadata 和 evidence 来源
5. diff 至少覆盖经理、规模、净值指标、公开持仓、风格暴露、风险提示、证据和结论状态；暂不要求单独落 diff 表

---

### 3.3 `fund-research export` — 结构化导出

#### 3.3.1 需求

v0.4 场景 8：

> 用户导出研究包 Markdown/JSON/CSV，文件包含算法版本、数据日期、数据来源等级、Evidence、warnings 和结论状态。

#### 3.3.2 CLI 命令

```bash
# 导出单基金研究包为 Markdown
fund-research export packet --fund-code 000001 --format markdown

# 导出单基金研究包为 JSON（到文件）
fund-research export packet --fund-code 000001 --format json --output ./reports/000001.json

# 导出筛选结果为 CSV
fund-research export screen --filters '{"category":"混合型-偏股"}' --format csv --output ./reports/screened.csv

# 导出最新研究包
fund-research export packet --fund-code 000001 --latest
```

#### 3.3.3 导出格式要求

**Markdown**（单基金研究包）：

```markdown
# 基金研究包: 000001 华夏成长混合

> 生成日期: 2026-06-08 | 数据日期: 2026-06-03
> 平台版本: 0.1.0 | 数据源等级: A, B
> 免责声明: 本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。

## 1. 基金基本信息
| 字段 | 值 | 数据源 |
...
```

必须包含的元数据（每份导出文件开头或末尾）：
- 数据日期
- 算法版本
- 数据来源等级
- Evidence 列表
- warnings
- 结论状态
- 免责声明

**JSON**：直接导出 `ResearchPacket.model_dump_json(indent=2)`。

**CSV**（筛选结果）：扁平化表格，列含基金代码/名称/类型/规模/收益/回撤/夏普/经理/费率。

#### 3.3.4 验收

1. `export packet --format markdown` 输出可读 Markdown 文件
2. `export packet --format json` 输出完整 JSON
3. `export screen --format csv` 输出 CSV 表格
4. 所有导出文件包含元数据和免责声明
5. 导出路径默认为 `./exports/`，支持 `--output` 自定义文件路径或目录路径；当传入带扩展名路径时按文件处理

---

### 3.4 `get_nav_metrics` — 多区间聚合

#### 3.4.1 需求

v0.4 6.1.4 和 Phase 1 FR-5.1 要求支持"今年以来、近 1/3/6 月、近 1/3/5 年、成立以来、基金经理任职以来"等多时间区间。

当前 `calculate_nav_metrics` 只计算了传入数据对应的时间区间，`get_nav_metrics` API 端点也只返回单区间结果。需要修改 API 层，让它按区间分段截取数据、多次调用分析函数，返回多区间聚合结果。

#### 3.4.2 接口变更

`GET /api/v1/funds/{fund_code}/nav-metrics` 的返回结构从单区间改为多区间：

```json
{
  "data": {
    "fund_code": "000001",
    "periods": {
      "YTD": {
        "metrics": {"total_return": 0.052, "max_drawdown": -0.08, ...},
        "observations": 105,
        "start_date": "2026-01-02",
        "end_date": "2026-06-05"
      },
      "1M": { ... },
      "3M": { ... },
      "6M": { ... },
      "1Y": { ... },
      "3Y": { ... },
      "5Y": { ... },
      "since_inception": { ... },
      "since_manager": { ... }
    },
    "custom": null
  },
  "warnings": ["3Y 区间不足 3 年数据，仅展示可用部分"],
  "conclusion_status": "computed"
}
```

区间定义：

| 区间 | 起始日计算规则 |
|------|--------------|
| YTD | 当年 1 月 1 日 |
| 1M / 3M / 6M | 最近 N 个日历月 |
| 1Y / 3Y / 5Y | 最近 N 个日历年 |
| since_inception | 基金成立日 |
| since_manager | 当前基金经理任职日 |
| custom | start + end 参数 |

#### 3.4.3 实现方案

API 层（router.py `get_nav_metrics`）：

1. 从数据库获取基金成立日和经理任职日
2. 计算各区间起始日
3. 对每个区间，截取对应日期段的净值数据
4. 循环调用 `calculate_nav_metrics`（每次传入截取后的数据）
5. 汇总为多区间结构
6. 对样本不足的区间标记 `needs_review`

分析层（`nav_metrics.py`）**不变**——保持单区间计算逻辑。

#### 3.4.4 验收

1. `/nav-metrics?fund_code=000001` 返回所有预设区间的指标
2. 不足最低样本数的区间降级为 `needs_review` 并附带说明
3. 支持 `?start=2024-01-01&end=2024-12-31` 自定义区间
4. 不传参数时默认返回 YTD + 1M + 3M + 6M + 1Y，并可在 metadata 中说明 3Y/5Y 等长区间是否因覆盖不足而降级

---

## 4. 补充页面（对应 v0.4 14.1）

v0.4 14.1 列了 7 个一期页面。Phase 1 不做前端，但每个页面对应的 API 端点应完整：

| v0.4 页面 | 已有 API | 需补充 |
|-----------|---------|--------|
| 1. 基金检索与筛选页 | — | `screen_funds`（见 3.1） |
| 2. 基金详情页 | `GET /funds/{code}/profile` | ✅ |
| 3. 主动权益基础分析页 | `POST /analysis/exposure` | ✅ |
| 4. Research Packet 研究包页 | `POST /research/packet` | ✅ |
| 5. Evidence 证据链页 | 证据嵌入在 API 返回中 | ✅ |
| 6. 数据质量与数据源状态页 | API metadata 含 data_snapshots | ✅ |
| 7. Tool API 调试页 | `/docs` (FastAPI 自带) | ✅ |

---

## 5. 交付物

| 编号 | 交付物 | 路径 | 状态 |
|------|--------|------|------|
| P1S-1 | `screen_funds` API | `src/fund_research/api/router.py` | 📋 |
| P1S-2 | `diff_research_packets` API | `src/fund_research/api/router.py` | 📋 |
| P1S-3 | `export` CLI | `src/fund_research/cli/main.py` | 📋 |
| P1S-4 | `get_nav_metrics` 多区间聚合 | `src/fund_research/api/router.py` | 📋 |
| P1S-5 | 补充测试 | `tests/` | 📋 |
| P1S-6 | 本文档 | `docs/phase1/requirements-supplement.md` | ✅ |

## 6. 验收标准

补充模块完成后，v0.4 第 16 节中的 8 个 MVP 验收场景在 Phase 1 范围内应可执行；其中场景 7 只覆盖筛选与导出，不覆盖持久化自选池：

| 场景 | 调用方式 |
|------|----------|
| 1. 搜索基金查看信息 | `curl GET /api/v1/funds/000001/profile` |
| 2. 查看持仓/暴露/归因 | `curl POST /api/v1/analysis/exposure -d '{"fund_code":"000001"}'` |
| 3. 查看数据质量 | `curl GET /api/v1/funds/000001/profile` → metadata.data_snapshots |
| 4. 生成 Research Packet | `curl POST /api/v1/research/packet -d '{"fund_code":"000001"}'` |
| 5. 对比 Packet diff | `curl POST /api/v1/research/diff -d '{"fund_code":"000001","left_snapshot":"...","right_snapshot":"..."}'` |
| 6. Notebook 调用 5 个 API | 每个 API 已可用 + `screen_funds` + `diff` = 7 个 |
| 7. 筛选基金并沉淀候选结果 | `curl POST /api/v1/funds/screen -d '{...}'` + `fund-research export screen --format csv` |
| 8. 导出 Markdown/JSON/CSV | `fund-research export packet --fund-code 000001 --format markdown` |

## 7. 非目标

以下 v0.4 能力明确不在补充范围内：
- 不做前端页面（Phase 1 定位声明不变）
- 不做基金池持久化管理（`screen_funds` 只返回结果，不保存；CSV 导出仅作为本地沉淀）
- 不做综合评分（仍在二期）
- 不做 PDF 导出（JSON/Markdown/CSV 优先）
