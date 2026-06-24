import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type ExposureData } from "../api/client";
import ChartWrapper from "../components/ChartWrapper";
import MetricCard from "../components/MetricCard";
import WarningBanner from "../components/WarningBanner";

export default function ExposurePage() {
  const { code } = useParams<{ code: string }>();
  const [data, setData] = useState<ExposureData | null>(null);
  const [window, setWindow] = useState(60);
  const [loading, setLoading] = useState(true);

  function fetch(w: number) {
    if (!code) return;
    setLoading(true);
    api.getExposure(code, w).then((r) => {
      if (r.data) setData(r.data);
    }).finally(() => setLoading(false));
  }

  useEffect(() => { fetch(window); }, [code, window]);

  if (loading) return <p>加载中...</p>;
  if (!data) return <p>无数据</p>;

  const exposureEntries = Object.entries(data.exposure_values);
  const attribution = data.static_attribution;

  return (
    <div className="page-container">
      <Link to={`/funds/${code}`} style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <div className="page-header">
        <div>
          <h1>风格暴露与归因</h1>
          <div className="summary-row">
            <span className="mono-cell">{code}</span>
            {data.r_squared != null && <span>R² = {data.r_squared.toFixed(3)}</span>}
          </div>
        </div>
        <div>
          <span style={{ fontSize: 13, color: "var(--color-text-secondary)", marginRight: 8 }}>窗口</span>
          <select value={window} onChange={(e) => setWindow(Number(e.target.value))}>
            {[20, 60, 120, 252].map((w) => (<option key={w} value={w}>{w} 日</option>))}
          </select>
        </div>
      </div>

      {/* Exposure bar chart */}
      <ChartWrapper
        type="bar"
        title="风格暴露系数"
        labels={exposureEntries.map(([key]) => key)}
        series={[{
          label: "暴露值",
          values: exposureEntries.map(([, val]) => val),
        }]}
        yLabel="系数"
        formatY={(v) => v.toFixed(2)}
        height={260}
      />

      {/* Exposure metric cards */}
      <div className="metric-grid" style={{ marginBottom: 16 }}>
        {exposureEntries.map(([key, val]) => (
          <MetricCard
            key={key}
            label={key}
            value={val.toFixed(3)}
            conclusionStatus={Math.abs(val) > 0.5 ? "computed" : "observation"}
            hint={Math.abs(val) > 0.5 ? "显著暴露" : "暴露较弱"}
          />
        ))}
        {data.residual != null && (
          <MetricCard
            label="残差"
            value={data.residual.toFixed(4)}
            conclusionStatus={Math.abs(data.residual) < 0.1 ? "computed" : "needs_review"}
            hint={Math.abs(data.residual) < 0.1 ? "拟合良好" : "拟合待复核"}
          />
        )}
      </div>

      {/* Static Attribution */}
      {attribution && (
        <>
          <WarningBanner level="warning">
            ⚠️ 静态归因仅基于披露持仓，不反映季度内调仓，结论状态为 observation
          </WarningBanner>
          <div className="card">
            <h3 style={{ marginBottom: 12 }}>静态归因（基于披露持仓）</h3>
            <div className="metric-grid" style={{ marginBottom: 16 }}>
              <MetricCard
                label="基金区间收益"
                value={(attribution.total_return ?? 0).toFixed(4)}
                conclusionStatus="fact"
              />
              <MetricCard
                label="可解释收益"
                value={(attribution.explained_return ?? 0).toFixed(4)}
                conclusionStatus="computed"
              />
              <MetricCard
                label="残差"
                value={(attribution.residual ?? 0).toFixed(4)}
                conclusionStatus={Math.abs(attribution.residual ?? 1) < 0.1 ? "computed" : "needs_review"}
              />
              <MetricCard
                label="残差占比"
                value={`${((attribution.residual_pct ?? 0) * 100).toFixed(1)}%`}
                conclusionStatus={Math.abs(attribution.residual_pct ?? 1) < 0.2 ? "computed" : "needs_review"}
              />
              <MetricCard
                label="覆盖率"
                value={`${((attribution.coverage_rate ?? 0) * 100).toFixed(0)}%`}
                conclusionStatus={(attribution.coverage_rate ?? 0) >= 0.8 ? "computed" : "needs_review"}
                hint={(attribution.coverage_rate ?? 0) >= 0.8 ? "覆盖充分" : "覆盖不足"}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
