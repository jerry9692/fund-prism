// P2B 验收报告 — Gate 状态 / 历史对比 / Readiness 卡片 / 逐基金结果
// 算法切换 Tab + 进度条 + 诊断网格

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type P2BValidationComparison,
  type P2BValidationReport,
  type P2BValidationReportSummary,
  type P2BValidationTask,
} from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";

const ALGO_LABELS: Record<string, string> = {
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
  scoring: "综合评分",
};

// 验收状态 → 结论状态映射
function toConclusion(status: string | null | undefined): string {
  if (status === "pass" || status === "candidate" || status === "computed")
    return "computed";
  if (status === "partial" || status === "estimated" || status === "observation")
    return "estimated";
  return "needs_review";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDelta(value: number | null): string {
  if (value === null || value === undefined) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(4)}`;
}

function reportLabel(report: P2BValidationReportSummary): string {
  const marker = report.is_latest ? "latest" : report.report_id;
  return `${marker} | ${report.generated_at ?? "—"} | ${report.pipeline_status ?? "—"}`;
}

export default function P2BValidationPage() {
  const [report, setReport] = useState<P2BValidationReport | null>(null);
  const [reports, setReports] = useState<P2BValidationReportSummary[]>([]);
  const [comparison, setComparison] = useState<P2BValidationComparison | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [compareLoading, setCompareLoading] = useState(false);
  const [rerunLoading, setRerunLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeAlgorithm, setActiveAlgorithm] = useState<string>(
    "simulated_holding",
  );
  const [baseReportId, setBaseReportId] = useState<string>("");
  const [task, setTask] = useState<P2BValidationTask | null>(null);

  const loadReportBundle = useCallback(async (preferredBaseId?: string) => {
    const [latestResponse, listResponse] = await Promise.all([
      api.getLatestP2BValidationReport(),
      api.listP2BValidationReports(),
    ]);
    if (!latestResponse.data) {
      setErrorMessage(latestResponse.warnings.join("; ") || "报告不可用");
      return;
    }
    setReport(latestResponse.data);
    const firstAlgorithm = Object.keys(latestResponse.data.algorithms)[0];
    if (firstAlgorithm) setActiveAlgorithm(firstAlgorithm);

    const history = listResponse.data?.reports ?? [];
    setReports(history);
    const preferredBase = preferredBaseId
      ? history.find((item) => item.report_id === preferredBaseId)
      : null;
    const defaultBase =
      preferredBase ?? history.find((item) => !item.is_latest) ?? history[1];
    if (defaultBase) setBaseReportId(defaultBase.report_id);
  }, []);

  useEffect(() => {
    loadReportBundle()
      .catch((error) => {
        setErrorMessage(error instanceof Error ? error.message : String(error));
      })
      .finally(() => setLoading(false));
  }, [loadReportBundle]);

  useEffect(() => {
    if (!baseReportId) {
      setComparison(null);
      return;
    }
    setCompareLoading(true);
    api
      .compareP2BValidationReports(baseReportId, "latest")
      .then((response) => setComparison(response.data ?? null))
      .catch((error) => {
        setComparison(null);
        setErrorMessage(error instanceof Error ? error.message : String(error));
      })
      .finally(() => setCompareLoading(false));
  }, [baseReportId]);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    const timer = window.setInterval(() => {
      api
        .getP2BValidationTask(task.task_id)
        .then((response) => {
          if (response.data) setTask(response.data);
        })
        .catch((error) => {
          setErrorMessage(
            error instanceof Error ? error.message : String(error),
          );
        });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [task]);

  useEffect(() => {
    if (task?.status !== "completed") return;
    loadReportBundle(baseReportId || undefined).catch((error) => {
      setErrorMessage(error instanceof Error ? error.message : String(error));
    });
  }, [task?.status, baseReportId, loadReportBundle]);

  const handleRerun = () => {
    setRerunLoading(true);
    setErrorMessage(null);
    const previousLatestId = report?.report_id;
    if (previousLatestId) setBaseReportId(previousLatestId);
    api
      .rerunP2BValidationReport()
      .then((response) => {
        if (response.data) {
          setTask(response.data);
        } else {
          setErrorMessage(response.warnings.join("; ") || "未能启动验收任务");
        }
      })
      .catch((error) => {
        setErrorMessage(
          error instanceof Error ? error.message : String(error),
        );
      })
      .finally(() => setRerunLoading(false));
  };

  const activeReport = report?.algorithms[activeAlgorithm];
  const activeRows = activeReport?.per_fund ?? [];
  const readiness = report?.readiness_summary[activeAlgorithm];

  const metricRows = useMemo(() => {
    if (!activeReport) return [];
    return Object.entries(activeReport.aggregate_stats)
      .filter(([, value]) => value !== null && value !== undefined)
      .map(([key, value]) => ({ key, value }));
  }, [activeReport]);

  const changedAlgorithms =
    comparison?.algorithm_changes.filter((item) => item.changed) ?? [];
  const changedGates =
    comparison?.gate_changes.filter((item) => item.changed) ?? [];
  const taskActive = task ? ["queued", "running"].includes(task.status) : false;
  const taskPercent = Math.max(0, Math.min(100, task?.percent ?? 0));

  const crumbs: BreadcrumbItem[] = [
    { label: "算法实验" },
    { label: "P2B 验收" },
  ];

  if (loading) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <LoadingState rows={8} cols={4} />
      </div>
    );
  }

  if (!report) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <ErrorState
          title="报告不可用"
          desc={errorMessage ?? "未找到报告"}
        />
      </div>
    );
  }

  // 逐基金结果行类型
  type FundRow = {
    fund_code: string;
    is_success: boolean;
    diagnostics?: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    error_message: string | null;
    warnings: string[];
  };

  // 逐基金结果列
  const fundColumns: Column<FundRow>[] = [
    {
      key: "fund_code",
      header: "基金",
      sortable: true,
      sortValue: (r) => r.fund_code,
      render: (r) => <span className="mono font-medium">{r.fund_code}</span>,
      width: "100px",
    },
    {
      key: "is_success",
      header: "结果",
      sortable: true,
      sortValue: (r) => (r.is_success ? 1 : 0),
      render: (r) => (
        <div>
          <StatusBadge status={r.is_success ? "computed" : "needs_review"} />
          {r.error_message && (
            <div
              className="text-xs mt-1"
              style={{ color: "var(--negative)" }}
            >
              {r.error_message}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "diagnostics",
      header: "诊断",
      render: (r) => {
        const diagnostics = Object.entries(r.diagnostics ?? {}).filter(
          ([, value]) => value !== null && value !== undefined,
        );
        if (diagnostics.length === 0) return <span className="text-tertiary">—</span>;
        return (
          <div className="grid grid-2" style={{ gap: "2px 12px" }}>
            {diagnostics.slice(0, 8).map(([key, value]) => (
              <div
                key={key}
                className="flex items-center justify-between"
                style={{ fontSize: "0.78rem" }}
              >
                <span className="text-tertiary">{key}</span>
                <span className="mono font-medium">
                  {formatValue(value)}
                </span>
              </div>
            ))}
          </div>
        );
      },
    },
    {
      key: "warnings",
      header: "警告",
      render: (r) => (
        <span className="text-xs text-warning">
          {r.warnings.length ? r.warnings.join("; ") : "—"}
        </span>
      ),
    },
  ];

  // 指标差异行类型
  interface DiffRow {
    algorithm: string;
    metric: string;
    delta: { base: number | null; target: number | null; delta: number | null };
  }

  // 指标差异列
  const diffColumns: Column<DiffRow>[] = [
    {
      key: "algorithm",
      header: "算法",
      render: (r) => ALGO_LABELS[r.algorithm] ?? r.algorithm,
    },
    {
      key: "metric",
      header: "指标",
      render: (r) => <span className="mono">{r.metric}</span>,
    },
    { key: "base", header: "基准", numeric: true, render: (r) => formatValue(r.delta.base) },
    { key: "target", header: "当前", numeric: true, render: (r) => formatValue(r.delta.target) },
    {
      key: "delta",
      header: "变化",
      numeric: true,
      render: (r) => (
        <span
          className="mono font-medium"
          style={{
            color:
              (r.delta.delta ?? 0) >= 0
                ? "var(--positive)"
                : "var(--negative)",
          }}
        >
          {formatDelta(r.delta.delta)}
        </span>
      ),
    },
  ];

  const diffRows: DiffRow[] = changedAlgorithms.flatMap((algorithm) =>
    Object.entries(algorithm.metric_deltas).map(([metric, delta]) => ({
      algorithm: algorithm.algorithm,
      metric,
      delta,
    })),
  );

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>P2B 验收报告</h1>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleRerun}
            disabled={taskActive || rerunLoading}
          >
            {taskActive ? "验收运行中" : rerunLoading ? "启动中" : "重新跑验收"}
          </button>
        </div>
        <div className="text-sm text-tertiary mt-2">
          <span className="mono">{report.generated_at}</span>
          {" · "}
          {report.sample_fund_count}/{report.expected_fund_count} 样本基金
          {" · "}
          结论状态 <StatusBadge status={report.conclusion_status} />
          {report.report_id && (
            <>
              {" · "}
              <span className="mono">{report.report_id}</span>
            </>
          )}
        </div>
      </div>

      {/* 任务进度 */}
      {task && (
        <div
          className={`fade-up fade-up-2 mb-4`}
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--surface-raised)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-hairline)",
            borderLeft: `3px solid ${
              task.status === "completed"
                ? "var(--positive)"
                : task.status === "failed"
                  ? "var(--negative)"
                  : "var(--accent)"
            }`,
          }}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <span className="text-xs text-tertiary">Validation Task</span>
              <strong className="text-sm">{task.stage}</strong>
              {task.algorithm && (
                <span className="text-sm text-secondary">
                  {ALGO_LABELS[task.algorithm] ?? task.algorithm}
                </span>
              )}
            </div>
            <StatusBadge status={toConclusion(task.status)} />
          </div>
          {/* 进度条 */}
          <div
            style={{
              height: "6px",
              background: "var(--surface-sunken)",
              borderRadius: "var(--radius-xs)",
              overflow: "hidden",
              marginBottom: "var(--space-2)",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${taskPercent}%`,
                background: "var(--accent)",
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <div className="flex items-center justify-between text-xs text-tertiary">
            <span>{task.message ?? "—"}</span>
            <span className="mono">{taskPercent.toFixed(1)}%</span>
          </div>
          {task.warnings && task.warnings.length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              {task.warnings.map((w, i) => (
                <div key={i} className="text-xs text-warning">
                  {"⚠ " + w}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Gate 状态 */}
      <div className="grid grid-2 fade-up fade-up-2 mb-6">
        <GateCard
          label="Pipeline Gate"
          status={report.pipeline_gate.status}
          warnings={undefined}
        />
        <GateCard
          label="Productization Gate"
          status={report.productization_gate.status}
          warnings={report.productization_gate.warnings}
        />
      </div>

      {/* 历史与对比 */}
      <div className="fade-up fade-up-3 mb-6">
        <SectionHeader
          title="历史与对比"
          subtitle={`${reports.length} 份报告 · ${
            compareLoading ? "对比中" : comparison?.changed ? "有变化" : "无变化"
          }`}
          actions={
            <label className="form-label" style={{ minWidth: "240px" }}>
              <span>基准报告</span>
              <select
                className="form-input"
                value={baseReportId}
                onChange={(e) => setBaseReportId(e.target.value)}
              >
                <option value="">不对比</option>
                {reports.map((item) => (
                  <option key={item.report_id} value={item.report_id}>
                    {reportLabel(item)}
                  </option>
                ))}
              </select>
            </label>
          }
        />

        {comparison && (
          <div className="grid grid-2 mt-3">
            {/* Gate Changes */}
            <div
              style={{
                padding: "var(--space-3) var(--space-4)",
                background: "var(--surface-raised)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-tertiary">Gate Changes</span>
                <strong className="mono">{changedGates.length}</strong>
              </div>
              <div className="flex flex-col gap-1">
                {(changedGates.length ? changedGates : comparison.gate_changes).map(
                  (item) => (
                    <div
                      key={item.name}
                      className="flex items-center justify-between text-sm"
                      style={{
                        padding: "var(--space-1) 0",
                        borderBottom: "1px solid var(--border-hairline)",
                      }}
                    >
                      <span>{item.name}</span>
                      <span className="mono text-xs">
                        {formatValue(item.base_passed)} →{" "}
                        {formatValue(item.target_passed)}
                      </span>
                    </div>
                  ),
                )}
              </div>
            </div>

            {/* Algorithm Changes */}
            <div
              style={{
                padding: "var(--space-3) var(--space-4)",
                background: "var(--surface-raised)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-tertiary">Algorithm Changes</span>
                <strong className="mono">{changedAlgorithms.length}</strong>
              </div>
              <div className="flex flex-col gap-1">
                {(changedAlgorithms.length
                  ? changedAlgorithms
                  : comparison.algorithm_changes
                ).map((item) => (
                  <div
                    key={item.algorithm}
                    className="flex items-center justify-between text-sm"
                    style={{
                      padding: "var(--space-1) 0",
                      borderBottom: "1px solid var(--border-hairline)",
                    }}
                  >
                    <span>
                      {ALGO_LABELS[item.algorithm] ?? item.algorithm}
                    </span>
                    <span className="mono text-xs">
                      {item.base_readiness ?? "—"} →{" "}
                      {item.target_readiness ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 指标差异表 */}
        {comparison && diffRows.length > 0 && (
          <div
            className="mt-3"
            style={{
              background: "var(--surface-raised)",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--border-hairline)",
              overflow: "hidden",
            }}
          >
            <DataTable
              columns={diffColumns}
              data={diffRows}
              rowKey={(r) => `${r.algorithm}-${r.metric}`}
            />
          </div>
        )}
      </div>

      {/* 报告警告 */}
      {report.warnings.length > 0 && (
        <div
          className="fade-up fade-up-3 mb-6"
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--warning-soft)",
            borderLeft: "3px solid var(--warning)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
        >
          {report.warnings.map((w, i) => (
            <div key={i} className="text-sm" style={{ color: "var(--warning)" }}>
              {"⚠ " + w}
            </div>
          ))}
        </div>
      )}

      {/* Readiness 卡片（算法切换） */}
      <div className="fade-up fade-up-4 mb-6">
        <SectionHeader title="算法就绪度" subtitle="点击切换查看各算法详情" />
        <div className="grid mt-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--space-3)" }}>
          {Object.entries(report.readiness_summary).map(([algorithm, item]) => (
            <button
              key={algorithm}
              onClick={() => setActiveAlgorithm(algorithm)}
              style={{
                textAlign: "left",
                padding: "var(--space-3) var(--space-4)",
                background:
                  activeAlgorithm === algorithm
                    ? "var(--surface-raised)"
                    : "var(--surface-base)",
                borderRadius: "var(--radius-md)",
                border: `2px solid ${
                  activeAlgorithm === algorithm
                    ? "var(--accent)"
                    : "var(--border-hairline)"
                }`,
                cursor: "pointer",
                transition: "all var(--transition-fast)",
              }}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-semibold text-sm">
                  {ALGO_LABELS[algorithm] ?? algorithm}
                </span>
                <StatusBadge status={toConclusion(item.level)} />
              </div>
              <div className="text-xs text-tertiary">{item.reason}</div>
            </button>
          ))}
        </div>
      </div>

      {/* 当前算法详情 */}
      <div className="fade-up fade-up-5 mb-6">
        <SectionHeader
          title={ALGO_LABELS[activeAlgorithm] ?? activeAlgorithm}
          subtitle={`成功率 ${formatValue(
            activeReport?.aggregate_stats.success_rate,
          )} · 结论 ${activeReport?.overall_conclusion ?? "—"} · 产品化 ${
            readiness?.productization_allowed ? "允许" : "未允许"
          }`}
          actions={
            readiness && (
              <StatusBadge status={toConclusion(readiness.level)} />
            )
          }
        />

        {/* 聚合指标 */}
        {metricRows.length > 0 && (
          <div className="grid grid-4 mt-3 mb-4">
            {metricRows.map((item) => (
              <MetricCard
                key={item.key}
                label={item.key}
                value={formatValue(item.value)}
              />
            ))}
          </div>
        )}

        {/* 逐基金结果表 */}
        <div
          className="mt-3"
          style={{
            background: "var(--surface-raised)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-hairline)",
            overflow: "hidden",
          }}
        >
          <DataTable
            columns={fundColumns}
            data={activeRows}
            rowKey={(r) => `${activeAlgorithm}-${r.fund_code}`}
          />
        </div>
      </div>
    </div>
  );
}

// ---- GateCard ----

function GateCard({
  label,
  status,
  warnings,
}: {
  label: string;
  status: string;
  warnings?: string[];
}) {
  return (
    <div
      style={{
        padding: "var(--space-4)",
        background: "var(--surface-raised)",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-hairline)",
      }}
    >
      <div className="text-xs text-tertiary mb-1">{label}</div>
      <div className="flex items-center justify-between">
        <strong className="text-lg font-semibold">{status}</strong>
        <StatusBadge status={toConclusion(status)} />
      </div>
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
