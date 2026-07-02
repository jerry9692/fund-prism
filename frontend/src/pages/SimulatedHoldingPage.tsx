import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type SimulatedHoldingResult,
} from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import ChartWrapper, { type BarSeries } from "../components/ChartWrapper";

function formatMetricValue(label: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (label === "跟踪误差" || label === "日度 RMSE" || label === "Top10 召回率") {
    return `${(v * 100).toFixed(2)}%`;
  }
  if (label === "输入覆盖率") {
    return `${v.toFixed(1)}%`;
  }
  return v.toFixed(4);
}

function HoldingsTable({
  holdings,
}: {
  holdings: SimulatedHoldingResult["holdings_detail"];
}) {
  if (!holdings || holdings.length === 0) {
    return (
      <p style={{ color: "var(--color-text-secondary)" }}>
        无持仓明细数据
      </p>
    );
  }

  const sorted = [...holdings].sort(
    (a, b) => (b.estimated_weight || 0) - (a.estimated_weight || 0)
  );

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>排名</th>
          <th>股票代码</th>
          <th>名称</th>
          <th>估计权重</th>
          <th>行业</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((h, i) => (
          <tr key={`${h.stock_code}-${i}`}>
            <td className="mono-cell">{i + 1}</td>
            <td className="mono-cell">{h.stock_code}</td>
            <td>{h.stock_name || "—"}</td>
            <td className="mono-cell">
              {((h.estimated_weight || 0) * 100).toFixed(2)}%
            </td>
            <td>{h.industry || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ResultCard({ result }: { result: SimulatedHoldingResult }) {
  const [expanded, setExpanded] = useState(false);

  const top15 = [...result.holdings_detail]
    .sort((a, b) => (b.estimated_weight || 0) - (a.estimated_weight || 0))
    .slice(0, 15);
  const chartLabels = top15.map((s) => s.stock_name || s.stock_code);
  const chartValues = top15.map((s) => (s.estimated_weight || 0) * 100);
  const chartSeries: BarSeries[] = [{ label: "估计权重", values: chartValues }];

  const metricLabels = ["跟踪误差", "日度 RMSE", "行业相关性", "Top10 召回率", "输入覆盖率"];
  const metricValues: (number | null | undefined)[] = [
    result.tracking_error,
    result.daily_rmse,
    result.industry_correlation,
    result.top10_recall,
    result.input_coverage,
  ];

  return (
    <div className="result-card">
      <div className="result-card-head">
        <div>
          <span className="result-card-title">
            {result.calc_date || "未知日期"}
          </span>
          <span className="result-card-meta">
            {result.algorithm_name} v{result.algorithm_version}
          </span>
          {result.is_backtest && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 11,
                padding: "1px 6px",
                borderRadius: 8,
                background: "var(--color-warning)",
                color: "white",
              }}
            >
              回测
            </span>
          )}
        </div>
        <ConfidenceBadge status={result.conclusion_status || "estimated"} />
      </div>

      <div className="metric-grid" style={{ marginBottom: 12 }}>
        {metricLabels.map((label, i) => (
          <div className="metric-card" key={label}>
            <div className="metric-card-label">{label}</div>
            <div className="metric-card-value">{formatMetricValue(label, metricValues[i])}</div>
          </div>
        ))}
      </div>

      <ChartWrapper
        type="bar"
        title="Top 15 重仓股权重"
        labels={chartLabels}
        series={chartSeries}
        yLabel="权重(%)"
        height={200}
        formatY={(v) => `${v.toFixed(1)}%`}
      />

      {result.warnings && result.warnings.length > 0 && (
        <div className="warning-banner" style={{ marginBottom: 8, fontSize: 12, marginTop: 12 }}>
          {result.warnings.join("; ")}
        </div>
      )}

      <button
        className="btn btn-sm"
        onClick={() => setExpanded(!expanded)}
        style={{ marginTop: 8 }}
      >
        {expanded ? "收起持仓明细" : `查看持仓明细 (${result.holdings_detail?.length || 0} 只)`}
      </button>

      {expanded && (
        <div style={{ marginTop: 12 }}>
          <HoldingsTable holdings={result.holdings_detail} />
        </div>
      )}
    </div>
  );
}

export default function SimulatedHoldingPage() {
  const { code } = useParams<{ code: string }>();
  const fundCode = code || "";

  const [results, setResults] = useState<SimulatedHoldingResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fundCode) return;
    setLoading(true);
    setError(null);
    api
      .listSimulatedHolding(fundCode)
      .then((resp) => {
        if (resp.data === null) {
          setError(resp.warnings.join("; ") || "查询失败");
          return;
        }
        setResults(resp.data.results);
      })
      .catch((e) => {
        setError(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => setLoading(false));
  }, [fundCode]);

  return (
    <div>
      <h2 style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span>模拟持仓 — {fundCode}</span>
        <ConfidenceBadge status="estimated" />
      </h2>

      <div
        className="warning-banner"
        style={{ marginBottom: 16 }}
      >
        模拟持仓为模型估计结果，不代表基金真实持仓。仅供研究参考。
      </div>

      {error && (
        <div
          className="warning-banner"
          style={{ marginBottom: 16, background: "var(--color-danger-light)", color: "var(--color-danger)", borderColor: "#fecaca" }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <p style={{ color: "var(--color-text-secondary)" }}>加载中...</p>
      ) : results.length === 0 ? (
        <div className="card empty-state">
          <p style={{ fontSize: 14, marginBottom: 8 }}>
            该基金暂无模拟持仓结果
          </p>
          <p style={{ fontSize: 12 }}>
            请先通过实验管理页面运行 simulated_holding 实验
          </p>
        </div>
      ) : (
        <>
          <p
            style={{
              color: "var(--color-text-secondary)",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            共 {results.length} 条模拟持仓记录（按计算日期倒序）
          </p>
          {results.map((r) => (
            <ResultCard key={r.id} result={r} />
          ))}
        </>
      )}
    </div>
  );
}
