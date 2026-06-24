import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type SimulatedHoldingResult,
} from "../api/client";

function MetricCard({
  label,
  value,
  suffix,
}: {
  label: string;
  value: number | null | undefined;
  suffix?: string;
}) {
  const display =
    value === null || value === undefined
      ? "—"
      : typeof value === "number"
        ? value.toFixed(4)
        : String(value);
  return (
    <div className="metric-card">
      <div className="metric-card-label">{label}</div>
      <div className="metric-card-value">
        {display}
        {suffix && value !== null && value !== undefined ? suffix : ""}
      </div>
    </div>
  );
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

  return (
    <div
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: 8,
        padding: 12,
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <div>
          <span style={{ fontWeight: 600, fontSize: 14 }}>
            {result.calc_date || "未知日期"}
          </span>
          <span
            style={{
              marginLeft: 8,
              fontSize: 12,
              color: "var(--color-text-secondary)",
            }}
          >
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
        <span
          style={{
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: 10,
            background: "var(--color-warning)20",
            color: "var(--color-warning)",
            border: "1px solid var(--color-warning)40",
          }}
        >
          estimated
        </span>
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 8,
        }}
      >
        <MetricCard
          label="跟踪误差"
          value={result.tracking_error}
        />
        <MetricCard
          label="日度 RMSE"
          value={result.daily_rmse}
        />
        <MetricCard
          label="行业相关性"
          value={result.industry_correlation}
        />
        <MetricCard
          label="Top10 召回率"
          value={result.top10_recall}
        />
        <MetricCard
          label="输入覆盖率"
          value={result.input_coverage}
          suffix="%"
        />
      </div>

      {result.warnings && result.warnings.length > 0 && (
        <div
          className="warning-banner"
          style={{ marginBottom: 8, fontSize: 12 }}
        >
          {result.warnings.join("; ")}
        </div>
      )}

      <button
        className="btn btn-sm"
        onClick={() => setExpanded(!expanded)}
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
        <span
          style={{
            fontSize: 12,
            padding: "2px 10px",
            borderRadius: 12,
            background: "var(--color-warning)20",
            color: "var(--color-warning)",
            border: "1px solid var(--color-warning)40",
          }}
        >
          estimated
        </span>
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
          style={{ marginBottom: 16 }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <p style={{ color: "var(--color-text-secondary)" }}>加载中...</p>
      ) : results.length === 0 ? (
        <div
          style={{
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            padding: 24,
            textAlign: "center",
            color: "var(--color-text-secondary)",
          }}
        >
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
