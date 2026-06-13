# Benchmark Industry Data Validation

日期: 2026-06-13
范围: `sh000300`、`sh000905` 真实基准行业权重小样本核验
临时库: `data/benchmark_validation.sqlite`

## 1. 核验结论

本轮没有通过“真实基准行业权重可被算法默认信任”的验收。

原因不是聚合算法本身，而是数据链路还没有完整跑通：

- 指数成分权重: 关闭全局代理/TUN 后，`index_stock_cons_weight_csindex` 已成功写入 `benchmark_index_member` 800 行，`sh000300` 300 行、`sh000905` 500 行。
- 股票申万一级行业归属: 小样本可用，三类申万行业成功标准化并入临时库 649 行；全量 336 个三级行业直接遍历会触发 429，需要节流、缓存和断点续跑。
- 聚合后的 `benchmark_industry_weight`: `2026-06-13` 可生成 6 行小样本行业权重，但覆盖率只有 `sh000300=35.04%`、`sh000905=23.99%`，低于 95% 门槛；`2026-03-31` 因权重快照晚于目标日期而正确拒绝使用。

因此，当前 runner 的严格 gating 是必要的：缺少 `benchmark_industry_weight` 或覆盖率不足时应失败并进入 `needs_review`，不能回退到基金持仓行业权重。

## 2. 目标与限制

原计划对 `sh000300`、`sh000905` 各选两个日期，核验：

1. 指数成分权重。
2. 股票申万一级行业归属。
3. 聚合后的 `benchmark_industry_weight`。
4. 与公开指数资料或行情软件行业分布的偏差。

实际限制：

- 中证权重接口在全局代理/TUN 下会出现 SSL EOF；关代理后可以拉通。
- AKShare 中证权重接口语义是最新权重快照，不是完整历史权重序列。
- 当前仅完成三个申万一级行业的小样本归属，无法达到 95% 行业映射覆盖率。
- 没有全量行业归属时，无法计算可进入默认动态归因的行业权重，也无法计算与公开行业分布的完整数值偏差。

本轮保留两个目标日期作为聚合验证点：

- `2026-06-13`: 可使用 `2026-05-29` 中证权重快照，但行业映射覆盖率不足。
- `2026-03-31`: 不可使用 `2026-05-29` 权重快照，因为该快照晚于目标日期。

结论：只有 `2026-06-13` 能生成低覆盖率样本结果，不能通过验收；`2026-03-31` 正确失败。

## 3. 执行记录

### 3.1 指数成分权重

命令:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains benchmark-members `
  --index-symbol sh000300 `
  --index-symbol sh000905 `
  --db-path data\benchmark_validation.sqlite
```

关代理后结果:

| benchmark_symbol | source | requested | inserted | skipped | result |
|---|---|---:|---:|---:|---|
| `sh000300` | `akshare.index_stock_cons_weight_csindex` | 1 | 300 | 0 | success |
| `sh000905` | `akshare.index_stock_cons_weight_csindex` | 1 | 500 | 0 | success |

代理影响复盘:

```text
开全局代理/TUN 时:
SSLError: HTTPSConnectionPool(host='oss-ch.csindex.com.cn', port=443) ... UNEXPECTED_EOF_WHILE_READING

关代理后 curl:
HTTP/1.1 200 OK
Content-Type: application/vnd.ms-excel
Content-Length: 72192
Last-Modified: Mon, 01 Jun 2026 12:33:43 GMT
```

公开入口:

- `https://www.csindex.com.cn/zh-CN/indices/index-detail/000300`
- `https://www.csindex.com.cn/zh-CN/indices/index-detail/000905`
- `https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls`
- `https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000905closeweight.xls`

入库权重快照:

| benchmark_symbol | snapshot_date | member_count | weight_sum | min_weight | max_weight |
|---|---|---:|---:|---:|---:|
| `sh000300` | 2026-05-29 | 300 | 100.004 | 0.019 | 4.830 |
| `sh000905` | 2026-05-29 | 500 | 100.007 | 0.018 | 1.444 |

备注: `index_stock_cons` 和 `index_stock_cons_sina` 能返回成分名单，`sh000300` 为 300 行、`sh000905` 为 500 行，但它们不包含成分权重，只可作为成分数量健康检查，不能替代权重源。

### 3.2 股票申万一级行业归属

全量命令:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-industry `
  --db-path data\benchmark_validation.sqlite
```

第一次失败原因:

```text
Length mismatch: Expected axis has 18 elements, new values have 17 elements
```

原因: AKShare 当前 `sw_index_third_cons` 对乐咕乐股页面列数写死为旧版 17 列，但真实页面已变为 18 列。

本轮已做兼容修复：当 AKShare 抛出 `Length mismatch` 时，adapter 直接读取同一乐咕乐股页面并只提取本项目需要的字段：

- `股票代码`
- `股票简称`
- `纳入时间`
- `申万1级`

小样本验证:

```python
AkshareAdapter().fetch_sw_industry_membership(
    symbols={"801120.SI", "801780.SI", "801080.SI"}
)
```

结果:

| industry_symbol | 公开页面行业 | 本地入库行业 | 本地入库行数 | 公开页面显示行数 | 偏差 |
|---|---|---|---:|---:|---:|
| `801080.SI` | 电子 | 电子 | 484 | 476 | +8 |
| `801120.SI` | 食品饮料 | 食品饮料 | 123 | 124 | -1 |
| `801780.SI` | 银行 | 银行 | 42 | 42 | 0 |

入库汇总:

```text
stock_industry_membership: 649
电子: 484
食品饮料: 123
银行: 42
```

公开对照页面:

- `https://legulegu.com/stockdata/index-composition?industryCode=801080.SI`
- `https://legulegu.com/stockdata/index-composition?industryCode=801120.SI`
- `https://legulegu.com/stockdata/index-composition?industryCode=801780.SI`

说明:

- 字段口径可以对上：页面包含股票代码、股票简称、纳入时间、申万1级。
- 银行样本完全一致。
- 电子、食品饮料行数与公开页面文本有差异，可能来自页面缓存、实时表格、停复牌/退市过滤或解析时间差；该差异需要后续人工抽查。
- 乐咕乐股页面声明其数据来自公开数据并由自动收集更新，不能作为 A/B 级权威行业源。当前仍应按 C 级处理。
- 全量 336 个三级行业直接遍历会触发 429，不能用无节流批处理作为默认更新方式。

### 3.2.1 全量 stock-industry 跑数准备

2026-06-13 晚间验证发现，慢速全量抓取仍可能被本地会话超时中断；同时
`akshare.sw_index_third_info()` 在异常页面形态下可能报
`AttributeError: 'NoneType' object has no attribute 'find_all'`，导致全量任务还没进入分行业抓取就失败。

已调整更新链路:

- CLI 默认把申万三级行业 symbol 列表缓存到 `data/cache/stock_industry/sw_third_symbols.json`。
- 不指定 `--industry-symbol` 时，优先实时获取并刷新缓存；实时获取失败但缓存存在时，使用缓存继续跑。
- `stock-industry` 默认按 20 个行业一批提交，批次之间已经写入数据库；中途超时后可重复执行同一命令续跑，已有唯一键会转为 update。

明天推荐先跑小批次慢速全量:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-industry `
  --request-interval 2 `
  --retry 2 `
  --industry-batch-size 10 `
  --db-path data\benchmark_validation.sqlite
```

如果仍频繁超时，继续降低批次:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-industry `
  --request-interval 3 `
  --retry 3 `
  --industry-batch-size 5 `
  --db-path data\benchmark_validation.sqlite
```

跑完后检查:

```powershell
.venv\Scripts\python.exe -c "import sqlite3; db='data/benchmark_validation.sqlite'; con=sqlite3.connect(db); print(con.execute('select count(*), count(distinct industry_name) from stock_industry_membership').fetchone()); print(con.execute('select industry_name, count(*) from stock_industry_membership group by industry_name order by count(*) desc limit 10').fetchall())"
```

2026-06-13 收尾 smoke:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-industry `
  --industry-symbol 801120.SI `
  --request-interval 1 `
  --retry 1 `
  --industry-batch-size 1 `
  --db-path data\benchmark_validation.sqlite
```

结果: `requested=1, inserted=0, updated=123, skipped=0, warnings=[]`。
库内仍为 `stock_industry_membership=(649 rows, 3 industries)`，说明单行业
smoke 未制造重复行，upsert 可重复执行。

明天固定顺序:

1. 先按上方推荐命令慢速全量跑 `stock-industry`，优先使用 `--industry-batch-size 10`。
2. 跑完检查 `stock_industry_membership` 行数、行业数和前 10 大行业行数。
3. 再跑 `benchmark-industry` 重新聚合 `sh000300`、`sh000905`。
4. 最后做真实行业分布对照验收；验收通过前，不要把 `benchmark_industry_weight` 用作高置信默认结论。

### 3.3 聚合后的 benchmark_industry_weight

命令一:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains benchmark-industry `
  --index-symbol sh000300 `
  --index-symbol sh000905 `
  --db-path data\benchmark_validation.sqlite `
  --end 2026-06-13
```

命令二:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains benchmark-industry `
  --index-symbol sh000300 `
  --index-symbol sh000905 `
  --db-path data\benchmark_validation.sqlite `
  --end 2026-03-31
```

结果:

| benchmark_symbol | target_date | inserted | skipped | warning |
|---|---|---:|---:|---|
| `sh000300` | 2026-06-13 | 3 | 0 | 行业映射覆盖率不足: 35.04% |
| `sh000905` | 2026-06-13 | 3 | 0 | 行业映射覆盖率不足: 23.99% |
| `sh000300` | 2026-03-31 | 0 | 1 | 缺少指数成分权重快照 |
| `sh000905` | 2026-03-31 | 0 | 1 | 缺少指数成分权重快照 |

临时库最终计数:

```text
benchmark_index_member: 800
stock_industry_membership: 649
benchmark_industry_weight: 6
```

`2026-06-13` 聚合结果:

| benchmark_symbol | industry_name | normalized_weight_pct | member_count | coverage_pct | unmapped_weight_pct |
|---|---|---:|---:|---:|---:|
| `sh000300` | 电子 | 53.823764 | 35 | 35.042598 | 64.960 |
| `sh000300` | 银行 | 30.087890 | 24 | 35.042598 | 64.960 |
| `sh000300` | 食品饮料 | 16.088346 | 12 | 35.042598 | 64.960 |
| `sh000905` | 电子 | 89.393624 | 64 | 23.993320 | 76.012 |
| `sh000905` | 银行 | 5.505314 | 6 | 23.993320 | 76.012 |
| `sh000905` | 食品饮料 | 5.101063 | 9 | 23.993320 | 76.012 |

说明: 上表的 `normalized_weight_pct` 只是在已映射成分内归一化后的比例，不代表完整指数行业分布，不能用于默认动态归因。

## 4. 偏差记录

### 4.1 可计算偏差

本轮可以计算行业归属页面的小样本行数偏差，以及低覆盖率的样本聚合结果；不能计算完整基准行业权重偏差。

| 数据项 | 结论 |
|---|---|
| 银行行业归属行数 | 本地 42，公开页面 42，偏差 0 |
| 食品饮料行业归属行数 | 本地 123，公开页面 124，偏差 -1 |
| 电子行业归属行数 | 本地 484，公开页面 476，偏差 +8 |
| `sh000300` 行业权重 | 可生成三行业低覆盖率样本，覆盖率 35.04%，不能验收 |
| `sh000905` 行业权重 | 可生成三行业低覆盖率样本，覆盖率 23.99%，不能验收 |

### 4.2 不能计算的偏差

以下完整偏差本轮不能计算：

- `sh000300` 在 `2026-06-13` 与公开行业分布的权重偏差。
- `sh000300` 在 `2026-03-31` 与公开行业分布的权重偏差。
- `sh000905` 在 `2026-06-13` 与公开行业分布的权重偏差。
- `sh000905` 在 `2026-03-31` 与公开行业分布的权重偏差。

原因:

- `2026-06-13`: 有权重快照，但行业归属只覆盖三个行业，映射覆盖率不足。
- `2026-03-31`: 中证权重快照日期为 `2026-05-29`，晚于目标日期，不能用于过去日期。

## 5. 对代码质量的影响判断

当前代码的保守失败策略是正确的：

- `benchmark_index_member` 拉取失败会写 `DataSourceSnapshot`，不产生假数据。
- `benchmark_industry_weight` 缺少成分快照会跳过并写 warning。
- `benchmark_industry_weight` 覆盖率不足时会持久化 warning，runner 的 95% gating 会拒绝默认使用。
- 动态归因 runner 缺少可用基准行业权重时失败，避免 proxy 污染默认结论。

本轮发现并修复了一个真实兼容问题：

- `sw_index_third_cons` 页面列数变动时，adapter 会直接从页面读取并只取所需字段。
- 新增测试覆盖 18 列页面和 `.SH/.SZ` 股票代码后缀清洗。
- `stock-industry` 已支持 `--industry-symbol`、`--request-interval`、`--retry`，便于分批、限速、重试和断点续跑。

仍需修复或增强：

1. 中证权重文件在全局代理/TUN 下会 TLS/SSL EOF，需要文档提醒“关代理/直连”或增加本地文件导入 fallback。
2. 申万行业全量拉取仍需要实跑验证合适的间隔参数；若仍频繁 429，再增加更长等待或本地缓存。
3. 行业归属数据源为 C 级，后续最好补一个更权威的申万/中信来源或人工小样本复核流程。
4. 中证权重接口只有最新快照时，历史日期不能标为真实历史权重，只能标为“最近快照近似”或直接拒绝。

## 6. 下一步建议

优先做数据源稳定性，不扩算法：

1. 给 `benchmark-members` 增加本地文件导入 fallback，支持把中证官网下载的 `closeweight.xls` 手动放到 `data/cache/benchmark_members/{index_code}/` 后解析入库。
2. 用慢速参数重跑 `stock-industry` 全量，建议从 `--request-interval 1 --retry 2` 起步；如果仍 429，把 interval 提到 2-3 秒。
3. 完成申万行业全量归属入库后，再重新跑两个指数的行业权重聚合，目标是 `coverage_pct >= 95%`。
4. 手工对照一份行情软件或指数公司行业分布截图，记录 `行业名 / 本地权重 / 对照权重 / 差值`，差值超过 1pp 的行业逐项解释。

建议命令:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-industry `
  --request-interval 1 `
  --retry 2 `
  --db-path data\benchmark_validation.sqlite
```

分批调试命令:

```powershell
.venv\Scripts\fund-research.exe update `
  --domains stock-industry `
  --industry-symbol 801120.SI `
  --industry-symbol 801780.SI `
  --request-interval 1 `
  --retry 1 `
  --db-path data\benchmark_validation.sqlite
```

在第 2、3、4 步完成前，不建议把真实基准行业权重接入视为“数据验收通过”。
