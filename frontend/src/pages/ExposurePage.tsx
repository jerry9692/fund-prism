import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type ExposureData } from "../api/client";

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

  return (
    <div>
      <Link to={`/funds/${code}`} style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <h1 style={{ margin: "8px 0" }}>风格暴露与归因</h1>

      <div style={{ marginBottom: 12 }}>
        窗口:{" "}
        <select value={window} onChange={(e) => setWindow(Number(e.target.value))}>
          {[20, 60, 120, 252].map((w) => (<option key={w} value={w}>{w} 日</option>))}
        </select>
        {data.r_squared != null && <span style={{ marginLeft: 12, color: "var(--color-text-secondary)" }}>R² = {data.r_squared.toFixed(3)}</span>}
      </div>

      {/* Exposure */}
      <div className="card">
        <h3 style={{ marginBottom: 8 }}>风格暴露</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 12 }}>
          {Object.entries(data.exposure_values).map(([key, val]) => (
            <div key={key} style={{ padding: 12, background: "var(--color-bg)", borderRadius: "var(--radius-sm)" }}>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{key}</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{val.toFixed(3)}</div>
            </div>
          ))}
        </div>
        {data.residual != null && <p style={{ marginTop: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>残差: {data.residual.toFixed(4)}</p>}
      </div>

      {/* Static Attribution */}
      {data.static_attribution && (
        <div className="card">
          <h3 style={{ marginBottom: 8 }}>静态归因（基于披露持仓）</h3>
          <p style={{ fontSize: 13, color: "var(--color-warning)", marginBottom: 8 }}>
            ⚠️ 仅基于披露持仓，不反映季度内调仓
          </p>
          <table className="data-table">
            <thead><tr><th>项目</th><th>值</th></tr></thead>
            <tbody>
              <tr><td>基金区间收益</td><td>{(data.static_attribution.total_return ?? 0).toFixed(4)}</td></tr>
              <tr><td>披露持仓可解释收益</td><td>{(data.static_attribution.explained_return ?? 0).toFixed(4)}</td></tr>
              <tr><td>残差</td><td>{(data.static_attribution.residual ?? 0).toFixed(4)}</td></tr>
              <tr><td>残差占比</td><td>{((data.static_attribution.residual_pct ?? 0) * 100).toFixed(1)}%</td></tr>
              <tr><td>覆盖率</td><td>{((data.static_attribution.coverage_rate ?? 0) * 100).toFixed(0)}%</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
