import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type P2BValidationComparison,
  type P2BValidationReport,
  type P2BValidationReportSummary,
  type P2BValidationTask,
} from "../api/client";

const ALGO_LABELS: Record<string, string> = {
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
  scoring: "综合评分",
};

function badgeClass(status: string | null | undefined) {
  if (status === "pass" || status === "candidate" || status === "computed") return "computed";
  if (status === "partial" || status === "estimated" || status === "observation") return "estimated";
  return "needs_review";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDelta(value: number | null) {
  if (value === null || value === undefined) return "-";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(4)}`;
}

function reportLabel(report: P2BValidationReportSummary) {
  const marker = report.is_latest ? "latest" : report.report_id;
  return `${marker} | ${report.generated_at ?? "-"} | ${report.pipeline_status ?? "-"}`;
}

export default function P2BValidationPage() {
  const [report, setReport] = useState<P2BValidationReport | null>(null);
  const [reports, setReports] = useState<P2BValidationReportSummary[]>([]);
  const [comparison, setComparison] = useState<P2BValidationComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [compareLoading, setCompareLoading] = useState(false);
  const [rerunLoading, setRerunLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeAlgorithm, setActiveAlgorithm] = useState<string>("simulated_holding");
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
    const defaultBase = preferredBase ?? history.find((item) => !item.is_latest) ?? history[1];
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
    api.compareP2BValidationReports(baseReportId, "latest")
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
      api.getP2BValidationTask(task.task_id)
        .then((response) => {
          if (response.data) setTask(response.data);
        })
        .catch((error) => {
          setErrorMessage(error instanceof Error ? error.message : String(error));
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
    api.rerunP2BValidationReport()
      .then((response) => {
        if (response.data) {
          setTask(response.data);
        } else {
          setErrorMessage(response.warnings.join("; ") || "未能启动验收任务");
        }
      })
      .catch((error) => {
        setErrorMessage(error instanceof Error ? error.message : String(error));
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

  const changedAlgorithms = comparison?.algorithm_changes.filter((item) => item.changed) ?? [];
  const changedGates = comparison?.gate_changes.filter((item) => item.changed) ?? [];
  const taskActive = task ? ["queued", "running"].includes(task.status) : false;
  const taskPercent = Math.max(0, Math.min(100, task?.percent ?? 0));

  if (loading) {
    return <div className="validation-page"><p>加载中...</p></div>;
  }

  if (!report) {
    return (
      <div className="validation-page">
        <div className="page-header">
          <div>
            <h1>P2B 验收报告</h1>
            <div className="summary-row"><span>报告状态不可用</span></div>
          </div>
        </div>
        <div className="card error-banner">
          <span>{errorMessage ?? "未找到报告"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="validation-page">
      <div className="page-header validation-header">
        <div>
          <h1>P2B 验收报告</h1>
          <div className="summary-row">
            <span>{report.generated_at}</span>
            <span>{report.sample_fund_count}/{report.expected_fund_count} 样本基金</span>
            <span>结论状态 {report.conclusion_status}</span>
            {report.report_id && <span className="mono-cell">{report.report_id}</span>}
          </div>
        </div>
        <button
          className="button-primary validation-rerun-button"
          onClick={handleRerun}
          disabled={taskActive || rerunLoading}
        >
          {taskActive ? "验收运行中" : rerunLoading ? "启动中" : "重新跑验收"}
        </button>
      </div>

      {task && (
        <section className={`validation-task ${task.status}`}>
          <div className="task-head">
            <div>
              <span className="gate-label">Validation Task</span>
              <strong>{task.stage}</strong>
            </div>
            <span className={`badge badge-${badgeClass(task.status)}`}>{task.status}</span>
          </div>
          <div className="task-progress-track">
            <div className="task-progress-bar" style={{ width: `${taskPercent}%` }} />
          </div>
          <div className="summary-row">
            <span>{task.message ?? "-"}</span>
            <span>{taskPercent.toFixed(1)}%</span>
            {task.algorithm && <span>{ALGO_LABELS[task.algorithm] ?? task.algorithm}</span>}
            {task.report_id && <span className="mono-cell">{task.report_id}</span>}
          </div>
          {task.warnings && task.warnings.length > 0 && (
            <div className="task-warnings">
              {task.warnings.map((warning) => <p key={warning}>{warning}</p>)}
            </div>
          )}
        </section>
      )}

      <section className="validation-gates">
        <div className="gate-block">
          <span className="gate-label">Pipeline Gate</span>
          <strong>{report.pipeline_gate.status}</strong>
          <span className={`badge badge-${badgeClass(report.pipeline_gate.status)}`}>
            {report.pipeline_gate.status}
          </span>
        </div>
        <div className="gate-block">
          <span className="gate-label">Productization Gate</span>
          <strong>{report.productization_gate.status}</strong>
          <span className={`badge badge-${badgeClass(report.productization_gate.status)}`}>
            {report.productization_gate.status}
          </span>
        </div>
      </section>

      <section className="validation-section">
        <div className="section-heading">
          <div>
            <h2>历史与对比</h2>
            <div className="summary-row">
              <span>{reports.length} 份报告</span>
              <span>{compareLoading ? "对比中" : comparison?.changed ? "有变化" : "无变化"}</span>
            </div>
          </div>
          <label className="validation-select-label">
            <span>基准报告</span>
            <select
              className="validation-select"
              value={baseReportId}
              onChange={(event) => setBaseReportId(event.target.value)}
            >
              <option value="">不对比</option>
              {reports.map((item) => (
                <option key={item.report_id} value={item.report_id}>
                  {reportLabel(item)}
                </option>
              ))}
            </select>
          </label>
        </div>

        {comparison && (
          <div className="compare-grid">
            <div className="compare-block">
              <span className="gate-label">Gate Changes</span>
              <strong>{changedGates.length}</strong>
              <div className="compare-list">
                {(changedGates.length ? changedGates : comparison.gate_changes).map((item) => (
                  <div key={item.name} className={item.changed ? "diff-row changed" : "diff-row"}>
                    <span>{item.name}</span>
                    <strong>
                      {formatValue(item.base_passed)} → {formatValue(item.target_passed)}
                    </strong>
                    <small>{item.target_detail ?? item.base_detail ?? "-"}</small>
                  </div>
                ))}
              </div>
            </div>

            <div className="compare-block">
              <span className="gate-label">Algorithm Changes</span>
              <strong>{changedAlgorithms.length}</strong>
              <div className="compare-list">
                {(changedAlgorithms.length ? changedAlgorithms : comparison.algorithm_changes).map((item) => (
                  <div key={item.algorithm} className={item.changed ? "diff-row changed" : "diff-row"}>
                    <span>{ALGO_LABELS[item.algorithm] ?? item.algorithm}</span>
                    <strong>
                      {item.base_readiness ?? "-"} → {item.target_readiness ?? "-"}
                    </strong>
                    <small>
                      success {formatValue(item.base_success_count)} → {formatValue(item.target_success_count)}
                    </small>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {comparison && changedAlgorithms.length > 0 && (
          <div className="table-card validation-table-wrap">
            <table className="data-table validation-table">
              <thead>
                <tr>
                  <th>算法</th>
                  <th>指标</th>
                  <th>基准</th>
                  <th>当前</th>
                  <th>变化</th>
                </tr>
              </thead>
              <tbody>
                {changedAlgorithms.flatMap((algorithm) =>
                  Object.entries(algorithm.metric_deltas).map(([metric, delta]) => (
                    <tr key={`${algorithm.algorithm}-${metric}`}>
                      <td>{ALGO_LABELS[algorithm.algorithm] ?? algorithm.algorithm}</td>
                      <td className="mono-cell">{metric}</td>
                      <td>{formatValue(delta.base)}</td>
                      <td>{formatValue(delta.target)}</td>
                      <td className={`delta-cell ${(delta.delta ?? 0) >= 0 ? "positive" : "negative"}`}>
                        {formatDelta(delta.delta)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {report.warnings.length > 0 && (
        <section className="validation-warning">
          {report.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </section>
      )}

      <section className="readiness-grid">
        {Object.entries(report.readiness_summary).map(([algorithm, item]) => (
          <button
            key={algorithm}
            className={`readiness-item ${activeAlgorithm === algorithm ? "active" : ""}`}
            onClick={() => setActiveAlgorithm(algorithm)}
          >
            <span>{ALGO_LABELS[algorithm] ?? algorithm}</span>
            <strong>{item.level}</strong>
            <small>{item.reason}</small>
          </button>
        ))}
      </section>

      <section className="validation-section">
        <div className="section-heading">
          <div>
            <h2>{ALGO_LABELS[activeAlgorithm] ?? activeAlgorithm}</h2>
            <div className="summary-row">
              <span>成功率 {formatValue(activeReport?.aggregate_stats.success_rate)}</span>
              <span>结论 {activeReport?.overall_conclusion}</span>
              <span>产品化 {readiness?.productization_allowed ? "允许" : "未允许"}</span>
            </div>
          </div>
          <span className={`badge badge-${badgeClass(readiness?.level)}`}>
            {readiness?.level ?? "unknown"}
          </span>
        </div>

        {metricRows.length > 0 && (
          <div className="validation-metrics">
            {metricRows.map((item) => (
              <div key={item.key} className="metric-strip">
                <span>{item.key}</span>
                <strong>{formatValue(item.value)}</strong>
              </div>
            ))}
          </div>
        )}

        <div className="table-card validation-table-wrap">
          <table className="data-table validation-table">
            <thead>
              <tr>
                <th>基金</th>
                <th>结果</th>
                <th>诊断</th>
                <th>Warnings</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.map((row) => {
                const diagnostics = Object.entries(row.diagnostics ?? {})
                  .filter(([, value]) => value !== null && value !== undefined);
                return (
                  <tr key={`${activeAlgorithm}-${row.fund_code}`}>
                    <td className="mono-cell">{row.fund_code}</td>
                    <td>
                      <span className={`badge badge-${row.is_success ? "computed" : "needs_review"}`}>
                        {row.is_success ? "success" : "review"}
                      </span>
                      {row.error_message && <div className="row-error">{row.error_message}</div>}
                    </td>
                    <td>
                      <div className="diagnostic-grid">
                        {diagnostics.slice(0, 8).map(([key, value]) => (
                          <div key={key} className="diagnostic-cell">
                            <span>{key}</span>
                            <strong>{formatValue(value)}</strong>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className="warning-cell">
                      {row.warnings.length ? row.warnings.join("; ") : "-"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
