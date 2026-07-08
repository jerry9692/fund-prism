// 算法实验管理 — DataTable + Drawer 详情 + 状态映射
// 实验列表 / 创建实验 / 运行 / 重跑 / 删除 / 结果详情

import { useEffect, useState } from "react";
import { api, type Experiment, type ExperimentDetail } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  Drawer,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";

const STATUS_LABELS: Record<string, string> = {
  pending: "就绪",
  running: "运行中",
  completed: "已完成",
  completed_with_failures: "部分完成",
  failed: "失败",
};

// 实验状态 → 结论状态映射（用于 StatusBadge 着色）
const STATUS_TO_CONCLUSION: Record<string, string> = {
  pending: "observation",
  running: "observation",
  completed: "computed",
  completed_with_failures: "estimated",
  failed: "needs_review",
};

const ALGO_LABELS: Record<string, string> = {
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
  scoring: "综合评分",
};

// metrics key → 中文展示标签
const METRIC_LABELS: Record<string, string> = {
  // 模拟持仓
  estimated_overall_tracking_error: "整体跟踪误差",
  estimated_overall_top10_recall: "整体 Top10 召回率",
  estimated_overall_industry_correlation: "整体行业相关性",
  estimated_tracking_error: "跟踪误差",
  method: "优化方法",
  uses_disclosed_holdings: "使用披露持仓",
  period_count: "周期数",
  matched_stock_count: "匹配股票数",
  return_sample_count: "收益样本数",
  backtest_detail: "回测明细",
  max_positions: "最大持仓数",
  max_single_weight: "单只最大权重",
  turnover_penalty: "换手惩罚",
  industry_penalty: "行业惩罚",
  // 动态归因
  total_portfolio_return: "组合总收益",
  total_benchmark_return: "基准总收益",
  total_allocation_effect: "配置效应",
  total_selection_effect: "选股效应",
  total_interaction_effect: "交互效应",
  estimated_total_portfolio_return: "组合总收益（估计）",
  estimated_total_benchmark_return: "基准总收益（估计）",
  estimated_total_allocation_effect: "配置效应（估计）",
  estimated_total_selection_effect: "选股效应（估计）",
  estimated_total_interaction_effect: "交互效应（估计）",
  // 评分
  total_score: "综合评分",
  percentile_rank: "分位数",
  contains_estimated: "含估计成分",
  sample_years: "样本年数",
};

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

function renderMetricValue(value: unknown): string {
  if (typeof value === "number") return Number(value).toFixed(4);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value).slice(0, 80);
}

export default function ExperimentsPage() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [algo, setAlgo] = useState("simulated_holding");
  const [fundCodes, setFundCodes] = useState("000001");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [benchmarkSymbol, setBenchmarkSymbol] = useState("sh000300");
  const [minReturnObs, setMinReturnObs] = useState(3);
  const [reportDate, setReportDate] = useState<string>(
    new Date().toISOString().slice(0, 10),
  );
  const [fromReadyLoading, setFromReadyLoading] = useState(false);
  const [fromReadyResult, setFromReadyResult] = useState<string | null>(null);

  const completedCount = experiments.filter(
    (e) => e.status === "completed" || e.status === "completed_with_failures",
  ).length;
  const failedCount = experiments.filter((e) => e.status === "failed").length;

  async function load() {
    setLoading(true);
    try {
      const body = await api.listExperiments();
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "加载失败");
        setExperiments([]);
        return;
      }
      setExperiments(body.data?.experiments ?? []);
    } catch (e) {
      setErrorMessage(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function loadDetail(id: string) {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const body = await api.getExperiment(id);
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "加载详情失败");
        setDetail(null);
        return;
      }
      setDetail(body.data as ExperimentDetail | null);
    } catch (e) {
      setErrorMessage(`加载详情异常: ${e instanceof Error ? e.message : String(e)}`);
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function create() {
    const experimentName = name.trim() || `${ALGO_LABELS[algo] ?? algo} 实验`;
    try {
      const body = await api.createExperiment({
        experiment_name: experimentName,
        algorithm_name: algo,
        algorithm_version: "0.1.0",
        parameters:
          algo === "dynamic_attribution"
            ? {
                benchmark_symbol: benchmarkSymbol,
                min_return_observations: Number(minReturnObs),
              }
            : {},
        sample_fund_codes: fundCodes.split(",").map((s) => s.trim()).filter(Boolean),
      });
      if (body.data === null) {
        setErrorMessage(`创建失败: ${body.warnings.join("; ") || "未知错误"}`);
        return;
      }
      setErrorMessage(null);
      setShowCreate(false);
      setName("");
      load();
    } catch (e) {
      setErrorMessage(`创建异常: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // R2: 从就绪样本批量创建动态归因实验
  async function createFromReady() {
    if (fromReadyLoading) return;
    setFromReadyLoading(true);
    setFromReadyResult(null);
    setErrorMessage(null);
    const experimentName =
      name.trim() || `动态归因 ${reportDate} 就绪样本`;
    const codes = fundCodes
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const body = await api.createDynamicAttributionFromReady({
        experiment_name: experimentName,
        report_date: reportDate,
        benchmark_symbol: benchmarkSymbol || null,
        fund_codes: codes.length > 0 ? codes : null,
        min_return_observations: Number(minReturnObs),
      });
      const d = body.data;
      if (d === null) {
        setErrorMessage(
          `从就绪样本创建失败: ${body.warnings.join("; ") || "未知错误"}`,
        );
        return;
      }
      const sampleCount = d.sample_fund_codes?.length ?? 0;
      setFromReadyResult(
        `已创建实验 ${d.experiment_id ?? "—"}：报告期 ${d.report_date}，` +
          `就绪候选 ${d.ready_candidates} 个，实际入组 ${sampleCount} 只基金。`,
      );
      setShowCreate(false);
      setName("");
      load();
    } catch (e) {
      setErrorMessage(
        `从就绪样本创建异常: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setFromReadyLoading(false);
    }
  }

  async function run(id: string) {
    setExperiments((prev) =>
      prev.map((e) => (e.id === id ? { ...e, status: "running" } : e)),
    );
    try {
      const body = await api.runExperiment(id);
      if (body.data === null) {
        setErrorMessage(`运行失败: ${body.warnings.join("; ") || "未知错误"}`);
      } else {
        setErrorMessage(null);
      }
    } catch (e) {
      setErrorMessage(`运行异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      load();
      if (selectedId === id) loadDetail(id);
    }
  }

  async function rerun(id: string) {
    try {
      const body = await api.rerunExperiment(id);
      if (body.data === null) {
        setErrorMessage(`重跑失败: ${body.warnings.join("; ") || "未知错误"}`);
        return;
      }
      setErrorMessage(null);
      load();
      setSelectedId(null);
      setDetail(null);
    } catch (e) {
      setErrorMessage(`重跑异常: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function remove(id: string) {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      return;
    }
    try {
      const body = await api.deleteExperiment(id);
      if (!body.data?.deleted) {
        setErrorMessage(`删除失败: ${body.warnings.join("; ") || "未知错误"}`);
        return;
      }
      setErrorMessage(null);
      setConfirmDeleteId(null);
    } catch (e) {
      setErrorMessage(`删除异常: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    if (selectedId === id) {
      setSelectedId(null);
      setDetail(null);
    }
    load();
  }

  const crumbs: BreadcrumbItem[] = [{ label: "算法实验" }, { label: "实验管理" }];

  const columns: Column<Experiment>[] = [
    {
      key: "id",
      header: "ID",
      sortable: true,
      sortValue: (r) => r.id,
      render: (r) => <span className="mono">{r.id}</span>,
      width: "80px",
    },
    {
      key: "name",
      header: "名称",
      sortable: true,
      sortValue: (r) => r.name,
      render: (r) => <span className="font-medium">{r.name}</span>,
    },
    {
      key: "algorithm",
      header: "算法",
      sortable: true,
      sortValue: (r) => r.algorithm,
      render: (r) => (
        <span>
          {ALGO_LABELS[r.algorithm] ?? r.algorithm}
          <span className="text-tertiary text-xs ml-1">v{r.version}</span>
        </span>
      ),
    },
    {
      key: "status",
      header: "状态",
      sortable: true,
      sortValue: (r) => r.status,
      render: (r) => (
        <StatusBadge status={STATUS_TO_CONCLUSION[r.status] ?? "observation"} />
      ),
    },
    {
      key: "fund_count",
      header: "基金数",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.fund_count,
    },
    {
      key: "success_count",
      header: "成功",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.success_count,
    },
    {
      key: "failure_count",
      header: "失败",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.failure_count,
      render: (r) => (
        <span className={r.failure_count > 0 ? "text-negative font-medium" : ""}>
          {r.failure_count}
        </span>
      ),
    },
    {
      key: "created_at",
      header: "创建时间",
      sortable: true,
      sortValue: (r) => r.created_at ?? "",
      render: (r) => (
        <span className="mono text-sm">{r.created_at?.slice(0, 10) ?? "—"}</span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      width: "200px",
      render: (r) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {r.status === "pending" && (
            <button className="btn btn-primary btn-sm" onClick={() => run(r.id)}>
              运行
            </button>
          )}
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => rerun(r.id)}
            disabled={r.status === "running"}
          >
            重跑
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => remove(r.id)}
            style={
              confirmDeleteId === r.id
                ? { color: "var(--negative)", fontWeight: 600 }
                : undefined
            }
          >
            {confirmDeleteId === r.id ? "确认删除" : "删除"}
          </button>
          {confirmDeleteId === r.id && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setConfirmDeleteId(null)}
            >
              取消
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>算法实验管理</h1>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setShowCreate(!showCreate)}
          >
            {showCreate ? "收起" : "+ 新建实验"}
          </button>
        </div>
      </div>

      {/* 汇总指标卡 */}
      <div className="grid grid-4 fade-up fade-up-2 mb-6">
        <MetricCard label="实验总数" value={experiments.length} />
        <MetricCard
          label="已完成"
          value={completedCount}
          positive={completedCount > 0}
        />
        <MetricCard
          label="失败"
          value={failedCount}
          negative={failedCount > 0}
        />
        <MetricCard
          label="运行中 / 就绪"
          value={experiments.length - completedCount - failedCount}
        />
      </div>

      {/* 错误提示 */}
      {errorMessage && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--negative)" }}>
              {errorMessage}
            </span>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setErrorMessage(null)}
            >
              关闭
            </button>
          </div>
        </div>
      )}

      {/* 创建实验表单 */}
      {showCreate && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            background: "var(--surface-raised)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-4)",
            border: "1px solid var(--border-hairline)",
          }}
        >
          <SectionHeader title="新建实验" subtitle="配置算法和样本基金" />
          <div
            className="grid mt-3"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: "var(--space-3)",
            }}
          >
            <label className="form-label">
              <span>名称</span>
              <input
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="如 sh-backtest-v1"
              />
            </label>
            <label className="form-label">
              <span>算法</span>
              <select
                className="form-input"
                value={algo}
                onChange={(e) => setAlgo(e.target.value)}
              >
                <option value="simulated_holding">模拟持仓</option>
                <option value="dynamic_attribution">动态归因</option>
                <option value="scoring">综合评分</option>
              </select>
            </label>
            <label className="form-label">
              <span>基金代码</span>
              <input
                className="form-input"
                value={fundCodes}
                onChange={(e) => setFundCodes(e.target.value)}
                placeholder="000001,163406"
              />
            </label>
            {algo === "dynamic_attribution" && (
              <>
                <label className="form-label">
                  <span>基准指数</span>
                  <input
                    className="form-input"
                    value={benchmarkSymbol}
                    onChange={(e) => setBenchmarkSymbol(e.target.value)}
                    placeholder="sh000300"
                  />
                </label>
                <label className="form-label">
                  <span>最小样本</span>
                  <input
                    className="form-input"
                    type="number"
                    value={minReturnObs}
                    onChange={(e) => setMinReturnObs(Number(e.target.value))}
                    placeholder="3"
                    min={1}
                  />
                </label>
                <label className="form-label">
                  <span>报告期（从就绪样本用）</span>
                  <input
                    className="form-input"
                    type="date"
                    value={reportDate}
                    onChange={(e) => setReportDate(e.target.value)}
                  />
                </label>
              </>
            )}
          </div>
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <button className="btn btn-primary" onClick={create}>
              创建
            </button>
            {algo === "dynamic_attribution" && (
              <button
                className="btn btn-ghost"
                onClick={createFromReady}
                disabled={fromReadyLoading}
                title="基于就绪检查通过的基金批量创建动态归因实验"
              >
                {fromReadyLoading ? "创建中..." : "从就绪样本创建"}
              </button>
            )}
          </div>
          {fromReadyResult && (
            <div
              className="mt-3 text-sm"
              style={{
                padding: "var(--space-2) var(--space-3)",
                background: "var(--positive-soft)",
                borderLeft: "3px solid var(--positive)",
                borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                color: "var(--positive)",
              }}
            >
              {fromReadyResult}
            </div>
          )}
        </div>
      )}

      {/* 实验列表 */}
      <div className="fade-up fade-up-3">
        {loading ? (
          <LoadingState rows={6} cols={6} />
        ) : experiments.length === 0 ? (
          <EmptyState
            title="暂无实验"
            desc="点击「新建实验」创建第一个算法实验"
          />
        ) : (
          <div
            style={{
              background: "var(--surface-raised)",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-hairline)",
              overflow: "hidden",
            }}
          >
            <DataTable
              columns={columns}
              data={experiments}
              rowKey={(r) => r.id}
              onRowClick={(r) => loadDetail(r.id)}
              initialSort={{ key: "created_at", order: "desc" }}
            />
          </div>
        )}
      </div>

      {/* 详情 Drawer */}
      <Drawer
        open={selectedId !== null}
        onClose={() => {
          setSelectedId(null);
          setDetail(null);
        }}
        title="实验结果"
      >
        {detailLoading ? (
          <LoadingState rows={5} cols={3} />
        ) : detail ? (
          <ExperimentDetailContent detail={detail} />
        ) : (
          <EmptyState title="加载失败" />
        )}
      </Drawer>
    </div>
  );
}

// ---- 实验详情内容 ----

function ExperimentDetailContent({ detail }: { detail: ExperimentDetail }) {
  const isDynamicAttribution = detail.algorithm_name === "dynamic_attribution";
  const results = detail.results ?? [];

  return (
    <div>
      {/* 概要 */}
      <div className="grid grid-3 mb-4">
        <MetricCard
          label="算法"
          value={ALGO_LABELS[detail.algorithm_name] ?? detail.algorithm_name}
        />
        <MetricCard
          label="状态"
          value={STATUS_LABELS[detail.status] ?? detail.status}
        />
        <MetricCard label="结果数" value={results.length} />
      </div>

      {results.length > 0 ? (
        <div className="flex flex-col gap-3">
          {results.map((r, i) => (
            <ExperimentResultItem
              key={i}
              fundCode={r.fund_code}
              isSuccess={r.is_success}
              metrics={r.metrics ?? {}}
              errorMessage={r.error_message}
              warnings={r.warnings}
              isDynamicAttribution={isDynamicAttribution}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          title="暂无结果"
          desc="点击「运行」执行实验"
        />
      )}
    </div>
  );
}

function ExperimentResultItem({
  fundCode,
  isSuccess,
  metrics,
  errorMessage,
  warnings,
  isDynamicAttribution,
}: {
  fundCode: string;
  isSuccess: boolean;
  metrics: Record<string, unknown>;
  errorMessage?: string | null;
  warnings?: string[] | null;
  isDynamicAttribution: boolean;
}) {
  const keys = Object.keys(metrics).filter((k) => metrics[k] != null);
  const boolItems: Array<[string, boolean]> = isDynamicAttribution
    ? [
        ["真实基准收益", metrics.uses_real_benchmark_returns === true],
        ["真实行业收益", metrics.uses_real_sector_returns === true],
        ["真实基准权重", metrics.uses_real_benchmark_weights === true],
        ["无代理权重", metrics.uses_proxy_benchmark_weights === false],
      ]
    : [];

  return (
    <div
      style={{
        padding: "var(--space-3) var(--space-4)",
        background: "var(--surface-base)",
        borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border-hairline)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="mono font-semibold">{fundCode}</span>
        <StatusBadge status={isSuccess ? "computed" : "needs_review"} />
      </div>

      {/* 动态归因质量标记 */}
      {boolItems.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {boolItems.map(([label, value]) => (
            <span
              key={label}
              className="text-xs"
              style={{
                padding: "2px 8px",
                borderRadius: "var(--radius-xs)",
                background: value
                  ? "var(--positive-soft)"
                  : "var(--warning-soft)",
                color: value ? "var(--positive)" : "var(--warning)",
                fontWeight: 500,
              }}
            >
              {label}
            </span>
          ))}
        </div>
      )}

      {/* 指标 */}
      {keys.length > 0 && (
        <div className="grid grid-2">
          {keys.slice(0, 8).map((k) => {
            const v = metrics[k];
            const isCompound = Array.isArray(v) || (typeof v === "object" && v !== null);
            return (
              <div
                key={k}
                className="flex items-center justify-between"
                style={{ padding: "var(--space-1) 0" }}
              >
                <span className="text-xs text-tertiary">{metricLabel(k)}</span>
                <span className="mono text-sm font-medium">
                  {isCompound ? `共 ${Array.isArray(v) ? v.length : Object.keys(v).length} 项` : renderMetricValue(v)}
                </span>
              </div>
            );
          })}
          {keys.length > 8 && (
            <div className="text-xs text-tertiary">... 共 {keys.length} 项</div>
          )}
        </div>
      )}

      {/* 错误 */}
      {errorMessage && (
        <div
          className="mt-2 text-xs"
          style={{ color: "var(--negative)" }}
        >
          {errorMessage}
        </div>
      )}

      {/* 警告 */}
      {warnings && warnings.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          {warnings.map((w, i) => (
            <div key={i} className="text-xs text-warning">
              {"⚠ " + w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
