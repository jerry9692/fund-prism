import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type HoldingsData } from "../api/client";

export default function HoldingsPage() {
  const { code } = useParams<{ code: string }>();
  const [data, setData] = useState<HoldingsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!code) return;
    api.getHoldings(code).then((r) => {
      if (r.data) setData(r.data);
    }).finally(() => setLoading(false));
  }, [code]);

  if (loading) return <p>加载中...</p>;
  if (!data) return <p>无数据</p>;

  return (
    <div>
      <Link to={`/funds/${code}`} style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <h1 style={{ margin: "8px 0" }}>公开持仓分析</h1>

      <span className={`badge badge-${data.disclosure_granularity === "top10_quarterly" ? "estimated" : "computed"}`}>
        {data.disclosure_granularity}
      </span>
      {data.disclosure_granularity === "top10_quarterly" && (
        <p style={{ color: "var(--color-warning)", fontSize: 13, marginTop: 4 }}>
          ⚠️ 季报通常仅披露前十大重仓，不能视为完整组合
        </p>
      )}
      <p style={{ color: "var(--color-text-secondary)" }}>报告期: {data.report_date}</p>

      {/* Holdings table */}
      <div className="card" style={{ marginTop: 12 }}>
        <table className="data-table">
          <thead>
            <tr><th>#</th><th>代码</th><th>名称</th><th>权重(%)</th><th>行业</th><th>变动</th></tr>
          </thead>
          <tbody>
            {data.holdings.map((h, i) => (
              <tr key={i}>
                <td>{h.rank_in_holdings}</td>
                <td style={{ fontFamily: "var(--font-mono)" }}>{h.security_code}</td>
                <td>{h.security_name}</td>
                <td>{h.weight_pct?.toFixed(2)}</td>
                <td>{h.industry ?? "—"}</td>
                <td>{h.change_direction ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Industry distribution */}
      {data.industry_distribution.length > 0 && (
        <div className="card">
          <h3 style={{ marginBottom: 8 }}>行业分布</h3>
          {data.industry_distribution.map((d, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "1px solid var(--color-border)" }}>
              <span>{d.name || "未分类"}</span>
              <span style={{ fontFamily: "var(--font-mono)" }}>{d.weight_pct?.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
