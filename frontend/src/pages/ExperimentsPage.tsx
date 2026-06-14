import { useEffect, useState } from "react";

interface Experiment {
  id: string;
  name: string;
  algorithm: string;
  version: string;
  status: string;
  fund_count: number;
  success_count: number;
  failure_count: number;
  created_at: string;
}

interface ExperimentDetail {
  id: string;
  experiment_name: string;
  algorithm_name: string;
  algorithm_version: string;
  status: string;
  results: ResultItem[];
  summary?: string;
}

interface ResultItem {
  fund_code: string;
  is_success: boolean;
  metrics: Record<string, unknown> | null;
  error_message: string | null;
  warnings?: string[] | null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "就绪", running: "运行中", completed: "已完成",
  completed_with_failures: "部分完成", failed: "失败",
};

const ALGO_LABELS: Record<string, string> = {
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
  scoring: "综合评分",
};

function getApiError(body: any, fallback: string) {
  if (Array.isArray(body?.warnings) && body.warnings.length > 0) {
    return body.warnings.join("; ");
  }
  return body?.detail ?? fallback;
}

function renderMetricValue(value: unknown) {
  if (typeof value === "number") return Number(value).toFixed(4);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value).slice(0, 80);
}

function renderMetricMap(metrics: Record<string, unknown>, key: string, suffix = "") {
  const value = metrics[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.entries(value as Record<string, unknown>).map(([dateKey, item]) => (
    <div className="quality-map-row" key={`${key}-${dateKey}`}>
      <span>{dateKey}</span>
      <strong>{renderMetricValue(item)}{suffix}</strong>
    </div>
  ));
}

function renderDynamicQuality(metrics: Record<string, unknown>) {
  const boolItems: Array<[string, boolean]> = [
    ["真实基准收益", metrics.uses_real_benchmark_returns === true],
    ["真实行业收益", metrics.uses_real_sector_returns === true],
    ["真实基准权重", metrics.uses_real_benchmark_weights === true],
    ["无代理权重", metrics.uses_proxy_benchmark_weights === false],
  ];
  return (
    <div className="quality-panel">
      <div className="quality-badges">
        {boolItems.map(([label, value]) => (
          <span
            className={`badge badge-${value ? "computed" : "needs_review"}`}
            key={String(label)}
          >
            {label}
          </span>
        ))}
      </div>
      <div className="quality-grid">
        <div>
          <span className="quality-title">快照日期</span>
          {renderMetricMap(metrics, "benchmark_weight_snapshot_by_report") ?? "—"}
        </div>
        <div>
          <span className="quality-title">快照年龄</span>
          {renderMetricMap(metrics, "benchmark_weight_snapshot_age_days_by_report", "d") ?? "—"}
        </div>
        <div>
          <span className="quality-title">覆盖率</span>
          {renderMetricMap(metrics, "benchmark_weight_coverage_by_report", "%") ?? "—"}
        </div>
        <div>
          <span className="quality-title">未映射</span>
          {renderMetricMap(metrics, "benchmark_weight_unmapped_pct_by_report", "%") ?? "—"}
        </div>
        <div>
          <span className="quality-title">基准独有行业</span>
          {renderMetricMap(metrics, "benchmark_only_sector_count_by_report") ?? "—"}
        </div>
      </div>
    </div>
  );
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

  const completedCount = experiments.filter(
    (e) => e.status === "completed" || e.status === "completed_with_failures",
  ).length;
  const failedCount = experiments.filter((e) => e.status === "failed").length;

  async function load() {
    setLoading(true);
    try {
      const response = await fetch("/api/v2/experiments");
      const body = await response.json();
      if (!response.ok || body.data === null) {
        setErrorMessage(getApiError(body, `加载失败: ${response.status}`));
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

  useEffect(() => { load(); }, []);

  async function loadDetail(id: string) {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const response = await fetch(`/api/v2/experiments/${id}`);
      const body = await response.json();
      if (!response.ok || body.data === null) {
        setErrorMessage(getApiError(body, `加载详情失败: ${response.status}`));
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
      const res = await fetch("/api/v2/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          experiment_name: experimentName,
          algorithm_name: algo,
          algorithm_version: "0.1.0",
          parameters: algo === "dynamic_attribution"
            ? { benchmark_symbol: benchmarkSymbol, min_return_observations: Number(minReturnObs) }
            : {},
          sample_fund_codes: fundCodes.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      const body = await res.json();
      if (!res.ok || body.data === null) {
        setErrorMessage(`创建失败: ${getApiError(body, String(res.status))}`);
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

  async function run(id: string) {
    setExperiments((prev) => prev.map((e) => (e.id === id ? { ...e, status: "running" } : e)));
    try {
      const response = await fetch(`/api/v2/experiments/${id}/run`, { method: "POST" });
      const body = await response.json();
      if (!response.ok || body.data === null) {
        setErrorMessage(`运行失败: ${getApiError(body, String(response.status))}`);
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
      const response = await fetch(`/api/v2/experiments/${id}/rerun`, { method: "POST" });
      const body = await response.json();
      if (!response.ok || body.data === null) {
        setErrorMessage(`重跑失败: ${getApiError(body, String(response.status))}`);
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
      const res = await fetch(`/api/v2/experiments/${id}`, { method: "DELETE" });
      const body = await res.json();
      if (!res.ok || !body.data?.deleted) {
        setErrorMessage(`删除失败: ${getApiError(body, String(res.status))}`);
        return;
      }
      setErrorMessage(null);
      setConfirmDeleteId(null);
    } catch (e) {
      setErrorMessage(`删除异常: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    if (selectedId === id) { setSelectedId(null); setDetail(null); }
    load();
  }

  return (
    <div className="experiments-page">
      <div className="page-header">
        <div>
          <h1>算法实验管理</h1>
          <div className="summary-row">
            <span>{experiments.length} 个实验</span>
            <span>{completedCount} 已完成</span>
            <span className={failedCount > 0 ? "text-danger" : undefined}>{failedCount} 失败</span>
          </div>
        </div>
        <button className="button-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "收起" : "+ 新建实验"}
        </button>
      </div>

      {errorMessage && (
        <div className="card error-banner">
          <span>{errorMessage}</span>
          <button className="button-ghost" onClick={() => setErrorMessage(null)}>关闭</button>
        </div>
      )}

      {showCreate && (
        <div className="card experiment-form">
          <div className="form-row">
            <label><span>名称</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 sh-backtest-v1" /></label>
            <label><span>算法</span>
              <select value={algo} onChange={(e) => setAlgo(e.target.value)}>
                <option value="simulated_holding">模拟持仓</option>
                <option value="dynamic_attribution">动态归因</option>
                <option value="scoring">综合评分</option>
              </select>
            </label>
            <label><span>基金代码</span><input value={fundCodes} onChange={(e) => setFundCodes(e.target.value)} placeholder="000001,163406" style={{ width: 140 }} /></label>
            {algo === "dynamic_attribution" && (
              <>
                <label><span>基准指数</span><input value={benchmarkSymbol} onChange={(e) => setBenchmarkSymbol(e.target.value)} placeholder="sh000300" style={{ width: 110 }} /></label>
                <label><span>最小样本</span><input type="number" value={minReturnObs} onChange={(e) => setMinReturnObs(Number(e.target.value))} placeholder="3" style={{ width: 60 }} min={1} /></label>
              </>
            )}
            <button className="button-primary" onClick={create}>创建</button>
          </div>
        </div>
      )}

      {loading ? <p>加载中...</p> : experiments.length === 0 ? (
        <div className="card empty-state">暂无实验</div>
      ) : (
        <div className="card table-card">
          <table className="data-table experiments-table">
            <thead>
              <tr>
                <th>ID</th><th>名称</th><th>算法</th><th>状态</th>
                <th>基金数</th><th>成功</th><th>失败</th>
                <th>创建时间</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.id} className={selectedId === e.id ? "selected-row" : ""}
                    onClick={() => loadDetail(e.id)} style={{ cursor: "pointer" }}>
                  <td className="mono-cell">{e.id}</td>
                  <td className="name-cell">{e.name}</td>
                  <td>{ALGO_LABELS[e.algorithm] ?? e.algorithm} v{e.version}</td>
                  <td>
                    <span className={`badge badge-${e.status === "completed" ? "computed" : e.status === "failed" ? "needs_review" : "observation"}`}>
                      {STATUS_LABELS[e.status] ?? e.status}
                    </span>
                  </td>
                  <td>{e.fund_count}</td>
                  <td>{e.success_count}</td>
                  <td className={e.failure_count > 0 ? "text-danger" : undefined}>{e.failure_count}</td>
                  <td className="date-cell">{e.created_at?.slice(0, 10)}</td>
                  <td onClick={(ev) => ev.stopPropagation()}>
                    <div className="action-row">
                      {e.status === "pending" && (
                        <button className="button-primary" onClick={() => run(e.id)}>运行</button>
                      )}
                      <button className="button-ghost" onClick={() => rerun(e.id)} disabled={e.status === "running"}>重跑</button>
                      <button className="button-danger" onClick={() => remove(e.id)}>
                        {confirmDeleteId === e.id ? "确认删除" : "删除"}
                      </button>
                      {confirmDeleteId === e.id && (
                        <button className="button-ghost" onClick={() => setConfirmDeleteId(null)}>取消</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail panel */}
      {selectedId && (
        <div className="card detail-panel" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>实验结果</h3>
            <button onClick={() => { setSelectedId(null); setDetail(null); }} style={{ cursor: "pointer", background: "none", border: "none", fontSize: 18 }}>×</button>
          </div>
          {detailLoading ? <p>加载中...</p> : detail ? (
            <div>
              <div className="summary-row" style={{ marginBottom: 12 }}>
                <span>算法: {ALGO_LABELS[detail.algorithm_name] ?? detail.algorithm_name}</span>
                <span>状态: {STATUS_LABELS[detail.status] ?? detail.status}</span>
                <span>结果数: {detail.results?.length ?? 0}</span>
              </div>
              {detail.results && detail.results.length > 0 ? (
                <table className="data-table">
                  <thead>
                    <tr><th>基金</th><th>结果</th><th>指标</th><th>错误</th></tr>
                  </thead>
                  <tbody>
                    {detail.results.map((r, i) => {
                      const m = r.metrics || {};
                      const keys = Object.keys(m).filter((k) => m[k] != null);
                      const isDynamicAttribution = detail.algorithm_name === "dynamic_attribution";
                      return (
                        <tr key={i}>
                          <td className="mono-cell">{r.fund_code}</td>
                          <td><span className={`badge badge-${r.is_success ? "computed" : "needs_review"}`}>{r.is_success ? "是" : "否"}</span></td>
                          <td style={{ fontSize: 12 }}>
                            {isDynamicAttribution && renderDynamicQuality(m)}
                            {keys.length > 0
                              ? keys.slice(0, 6).map((k) => (
                                  <div key={k} style={{ marginBottom: 2 }}>
                                    <span style={{ color: "var(--color-text-secondary)" }}>{k}: </span>
                                    {renderMetricValue(m[k])}
                                  </div>
                                ))
                              : "—"}
                            {keys.length > 6 && <div style={{ color: "var(--color-text-secondary)" }}>... 共 {keys.length} 项</div>}
                          </td>
                          <td style={{ color: r.error_message ? "var(--color-danger)" : undefined, fontSize: 12, maxWidth: 250 }}>
                            {r.error_message ?? "—"}
                            {r.warnings && r.warnings.length > 0 && (
                              <div className="warning-list">
                                {r.warnings.map((warning) => (
                                  <div key={warning}>{warning}</div>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : <p style={{ color: "var(--color-text-secondary)" }}>暂无结果（点击"运行"执行实验）</p>}
            </div>
          ) : <p style={{ color: "var(--color-text-secondary)" }}>加载失败</p>}
        </div>
      )}
    </div>
  );
}
