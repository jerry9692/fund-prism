import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type DynamicAttributionResult } from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import ChartWrapper, { type BarSeries } from "../components/ChartWrapper";

function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function valueSignClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "";
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  const display = formatPct(value);
  const signClass = valueSignClass(value);
  return (
    <div className="metric-card">
      <div className="metric-card-label">{label}</div>
      <div className={`metric-card-value ${signClass}`}>{display}</div>
    </div>
  );
}

function ResultListItem({
  result,
  selected,
  onClick,
}: {
  result: DynamicAttributionResult;
  selected: boolean;
  onClick: () => void;
}) {
  const period =
    result.period_start && result.period_end
      ? `${result.period_start} ~ ${result.period_end}`
      : result.created_at || "未知期间";
  return (
    <div
      className={`result-card${selected ? " selected" : ""}`}
      onClick={onClick}
      style={{ cursor: "pointer", borderColor: selected ? "var(--color-primary)" : undefined }}
    >
      <div className="result-card-head">
        <div>
          <span className="result-card-title">{period}</span>
          <span className="result-card-meta">
            {result.algorithm_name} v{result.algorithm_version}
          </span>
        </div>
        <ConfidenceBadge status={result.conclusion_status || "estimated"} />
      </div>
    </div>
  );
}

export default function DynamicAttributionPage() {
  const { code } = useParams<{ code: string }>();
  const fundCode = code || "";

  const [results, setResults] = useState<DynamicAttributionResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);

  const loadResults = () => {
    if (!fundCode) return;
    setLoading(true);
    setError(null);
    api
      .listDynamicAttribution(fundCode)
      .then((resp) => {
        const list = resp.data?.results ?? [];
        setResults(list);
        if (list.length > 0) {
          setSelectedResultId(list[0].id);
        } else {
          setSelectedResultId(null);
        }
      })
      .catch((e) => {
        setError(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadResults();
  }, [fundCode]);

  const handleRun = () => {
    if (!fundCode || running) return;
    setRunning(true);
    api
      .runReturnAttribution({ fund_code: fundCode })
      .then(() => {
        loadResults();
      })
      .catch((e) => {
        setError(`运行归因失败: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => setRunning(false));
  };

  const selectedResult = results.find((r) => r.id === selectedResultId) || null;

  const attributionLabels = ["Beta收益", "配置收益", "轮动收益", "选股收益", "残差"];
  const attributionValues = selectedResult
    ? [
        selectedResult.beta_return ?? 0,
        selectedResult.allocation_return ?? 0,
        selectedResult.sector_rotation_return ?? 0,
        selectedResult.stock_selection_return ?? 0,
        selectedResult.residual ?? 0,
      ]
    : [];
  const attributionSeries: BarSeries[] = selectedResult
    ? [{ label: "收益贡献", values: attributionValues.map((v) => v * 100) }]
    : [];

  return (
    <div>
      <Link
        to={`/funds/${code}`}
        className="text-muted"
        style={{ fontSize: 13 }}
      >
        ← 返回基金详情
      </Link>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: 8,
          marginBottom: 16,
        }}
      >
        <h2 style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span>动态收益归因 — {fundCode}</span>
          <ConfidenceBadge status="estimated" />
        </h2>
        <button
          className="btn btn-primary"
          onClick={handleRun}
          disabled={running}
        >
          {running ? "运行中..." : "运行归因"}
        </button>
      </div>

      <div className="warning-banner" style={{ marginBottom: 16 }}>
        动态归因基于模拟持仓和风格暴露估算，结果仅供研究参考，不构成投资建议。
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
          <p style={{ fontSize: 14, marginBottom: 8 }}>该基金暂无动态归因结果</p>
          <p style={{ fontSize: 12 }}>点击"运行归因"按钮生成归因分析</p>
        </div>
      ) : (
        <>
          {selectedResult && (
            <>
              <div className="metric-grid" style={{ marginBottom: 16 }}>
                <MetricCard label="总收益" value={selectedResult.total_return} />
                <MetricCard label="Beta收益" value={selectedResult.beta_return} />
                <MetricCard label="配置收益" value={selectedResult.allocation_return} />
                <MetricCard label="轮动收益" value={selectedResult.sector_rotation_return} />
                <MetricCard label="选股收益" value={selectedResult.stock_selection_return} />
                <MetricCard label="残差占比" value={selectedResult.residual_pct} />
              </div>

              <ChartWrapper
                type="bar"
                title="收益归因分解"
                labels={attributionLabels}
                series={attributionSeries}
                yLabel="收益(%)"
                height={280}
                formatY={(v) => `${v.toFixed(2)}%`}
              />

              {selectedResult.warnings && selectedResult.warnings.length > 0 && (
                <div className="warning-banner" style={{ marginTop: 16 }}>
                  {selectedResult.warnings.join("; ")}
                </div>
              )}
            </>
          )}

          <h3 style={{ marginTop: 24, marginBottom: 12 }}>归因记录</h3>
          {results.map((r) => (
            <ResultListItem
              key={r.id}
              result={r}
              selected={r.id === selectedResultId}
              onClick={() => setSelectedResultId(r.id)}
            />
          ))}
        </>
      )}
    </div>
  );
}
