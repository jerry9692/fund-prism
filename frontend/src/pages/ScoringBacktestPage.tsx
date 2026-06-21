import { useEffect, useState } from "react";
import { api, type ScoringBacktestItem, type ScoringBacktestDetail } from "../api/client";

const PRESET_OPTIONS = ["均衡型", "稳健型", "进取型"];
const METRIC_LABELS: Record<string, string> = {
  future_return: "未来收益",
  future_max_drawdown: "最大回撤",
  future_sharpe: "夏普",
};

export default function ScoringBacktestPage() {
  const [backtests, setBacktests] = useState<ScoringBacktestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [fundCodes, setFundCodes] = useState("000001");
  const [backtestStart, setBacktestStart] = useState("2022-01-01");
  const [backtestEnd, setBacktestEnd] = useState("2025-12-31");
  const [preset, setPreset] = useState("均衡型");
  const [creating, setCreating] = useState(false);

  // Detail
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ScoringBacktestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const body = await api.listScoringBacktests();
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "加载失败");
        return;
      }
      setBacktests(body.data.backtests ?? []);
    } catch (e) {
      setErrorMessage(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function loadDetail(id: number) {
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const body = await api.getScoringBacktest(id);
      if (body.data === null) {
        setErrorMessage(body.warnings.join("; ") || "加载详情失败");
        return;
      }
      setDetail(body.data as ScoringBacktestDetail | null);
    } catch (e) {
      setErrorMessage(`加载详情异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDetailLoading(false);
    }
  }

  async function create() {
    setCreating(true);
    try {
      const body = await api.runScoringBacktest({
        fund_codes: fundCodes.split(",").map((s) => s.trim()).filter(Boolean),
        backtest_start: backtestStart,
        backtest_end: backtestEnd,
        preset,
        forward_months: 12,
        min_forward_observations: 60,
      });
      if (body.data === null) {
        setErrorMessage(`回测失败: ${body.warnings.join("; ") || "未知错误"}`);
        return;
      }
      setErrorMessage(null);
      setShowCreate(false);
      load();
    } catch (e) {
      setErrorMessage(`回测异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="experiments-page">
      <div className="page-header">
        <div>
          <h1>评分回测</h1>
          <div className="summary-row">
            <span>{backtests.length} 次回测</span>
          </div>
        </div>
        <button className="button-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "收起" : "+ 新建回测"}
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
          <div className="form-row" style={{ flexWrap: "wrap", gap: 12 }}>
            <label><span>基金代码</span>
              <input value={fundCodes} onChange={(e) => setFundCodes(e.target.value)}
                     placeholder="000001,163406" style={{ width: 160 }} />
            </label>
            <label><span>回测起点</span>
              <input type="date" value={backtestStart}
                     onChange={(e) => setBacktestStart(e.target.value)} />
            </label>
            <label><span>回测终点</span>
              <input type="date" value={backtestEnd}
                     onChange={(e) => setBacktestEnd(e.target.value)} />
            </label>
            <label><span>评分预设</span>
              <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                {PRESET_OPTIONS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <button className="button-primary" onClick={create} disabled={creating}>
              {creating ? "运行中..." : "运行回测"}
            </button>
          </div>
        </div>
      )}

      {loading ? <p>加载中...</p> : backtests.length === 0 ? (
        <div className="card empty-state">
          暂无回测记录。创建一次回测来验证评分的预测能力。
        </div>
      ) : (
        <div className="card table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>版本</th><th>日期</th><th>分组数</th>
                <th>IC Mean</th><th>IC IR</th><th>单调性</th><th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {backtests.map((bt) => (
                <tr key={bt.id}
                    className={selectedId === bt.id ? "selected-row" : ""}
                    onClick={() => loadDetail(bt.id)}
                    style={{ cursor: "pointer" }}>
                  <td className="mono-cell">{bt.id}</td>
                  <td className="mono-cell">{bt.score_version}</td>
                  <td>{bt.backtest_date ?? "—"}</td>
                  <td>{bt.group_count}</td>
                  <td className="mono-cell">
                    {bt.ic_mean != null ? bt.ic_mean.toFixed(4) : "—"}
                  </td>
                  <td className="mono-cell">
                    {bt.ic_ir != null ? bt.ic_ir.toFixed(4) : "—"}
                  </td>
                  <td>
                    <span className={`badge badge-${bt.monotonicity_check ? "computed" : "needs_review"}`}>
                      {bt.monotonicity_check ? "通过" : bt.monotonicity_check === false ? "未通过" : "—"}
                    </span>
                  </td>
                  <td className="date-cell">{bt.created_at?.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && (
        <div className="card detail-panel" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>回测详情 #{selectedId}</h3>
            <button onClick={() => { setSelectedId(null); setDetail(null); }}
                    style={{ cursor: "pointer", background: "none", border: "none", fontSize: 18 }}>×</button>
          </div>
          {detailLoading ? <p>加载中...</p> : detail ? (
            <div>
              <div className="summary-row" style={{ marginBottom: 16, gap: 24 }}>
                <div>
                  <span style={{ color: "var(--color-text-secondary)" }}>IC Mean</span>
                  <strong style={{ marginLeft: 8 }}>
                    {detail.ic_mean != null ? detail.ic_mean.toFixed(4) : "—"}
                  </strong>
                </div>
                <div>
                  <span style={{ color: "var(--color-text-secondary)" }}>IC IR</span>
                  <strong style={{ marginLeft: 8 }}>
                    {detail.ic_ir != null ? detail.ic_ir.toFixed(4) : "—"}
                  </strong>
                </div>
                <div>
                  <span style={{ color: "var(--color-text-secondary)" }}>单调性</span>
                  <span className={`badge badge-${detail.monotonicity_check ? "computed" : "needs_review"}`}
                        style={{ marginLeft: 8 }}>
                    {detail.monotonicity_check ? "通过" : detail.monotonicity_check === false ? "未通过" : "—"}
                  </span>
                </div>
                <div>
                  <span style={{ color: "var(--color-text-secondary)" }}>评估期数</span>
                  <strong style={{ marginLeft: 8 }}>{detail.group_count}</strong>
                </div>
              </div>

              {detail.group_results && Object.keys(detail.group_results).length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <h4 style={{ marginBottom: 8 }}>分组指标</h4>
                  <table className="data-table" style={{ maxWidth: 680 }}>
                    <thead>
                      <tr>
                        <th>指标</th>
                        {["0", "1", "2", "3", "4"].map((group) => (
                          <th key={group}>Q{Number(group) + 1}</th>
                        ))}
                        <th>单调性</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(detail.group_results)
                        .map(([metric, groups]) => (
                          <tr key={metric}>
                            <td>{METRIC_LABELS[metric] ?? metric}</td>
                            {["0", "1", "2", "3", "4"].map((group) => {
                              const value = groups[group];
                              return (
                                <td key={group} className="mono-cell">
                                  {value == null
                                    ? "—"
                                    : metric === "future_sharpe"
                                      ? value.toFixed(2)
                                      : `${(value * 100).toFixed(2)}%`}
                                </td>
                              );
                            })}
                            <td>
                              <span className={`badge badge-${detail.detail?.monotonicity_checks?.[metric] ? "computed" : "needs_review"}`}>
                                {detail.detail?.monotonicity_checks?.[metric] ? "通过" : "未通过"}
                              </span>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}

              {detail.detail && (
                <div>
                  <h4 style={{ marginBottom: 8 }}>元数据</h4>
                  <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                    <div>IC 期数: {String(detail.detail.ic_count ?? "—")}</div>
                    <div>前瞻月份: {String(detail.detail.forward_months ?? "—")}</div>
                    <div>评估日期数: {String(detail.detail.eval_date_count ?? "—")}</div>
                    {(() => {
                      const raw = detail.detail.warnings;
                      if (Array.isArray(raw) && raw.length > 0) {
                        return (
                          <div className="warning-list" style={{ marginTop: 8 }}>
                            {raw.map((w) => (<div key={String(w)}>{String(w)}</div>))}
                          </div>
                        );
                      }
                      return null;
                    })()}
                  </div>
                </div>
              )}
            </div>
          ) : <p style={{ color: "var(--color-text-secondary)" }}>加载失败</p>}
        </div>
      )}
    </div>
  );
}
