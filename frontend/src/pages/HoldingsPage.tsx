import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type HoldingsData } from "../api/client";
import ConfidenceBadge from "../components/ConfidenceBadge";
import ChartWrapper, { type BarSeries } from "../components/ChartWrapper";

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

  const confidenceStatus = data.disclosure_granularity === "top10_quarterly" ? "estimated" : "computed";

  const industryLabels = data.industry_distribution.map((d) => d.name || "未分类");
  const industryValues = data.industry_distribution.map((d) => d.weight_pct ?? 0);
  const industrySeries: BarSeries[] = [{ label: "行业权重(%)", values: industryValues }];

  return (
    <div>
      <Link to={`/funds/${code}`} className="text-muted" style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <h1 style={{ margin: "8px 0" }}>公开持仓分析</h1>

      <ConfidenceBadge status={confidenceStatus} />
      {data.disclosure_granularity === "top10_quarterly" && (
        <p style={{ color: "var(--color-warning)", fontSize: 13, marginTop: 4 }}>
          ⚠️ 季报通常仅披露前十大重仓，不能视为完整组合
        </p>
      )}
      <p style={{ color: "var(--color-text-secondary)" }}>报告期: {data.report_date}</p>

      {data.industry_distribution.length > 0 && (
        <ChartWrapper
          type="bar"
          title="行业分布"
          labels={industryLabels}
          series={industrySeries}
          yLabel="权重(%)"
          height={Math.max(200, data.industry_distribution.length * 28)}
          formatY={(v) => `${v.toFixed(1)}%`}
        />
      )}

      <div className="card" style={{ marginTop: 12 }}>
        <table className="data-table">
          <thead>
            <tr><th>#</th><th>代码</th><th>名称</th><th>权重(%)</th><th>行业</th><th>变动</th></tr>
          </thead>
          <tbody>
            {data.holdings.map((h, i) => (
              <tr key={i}>
                <td>{h.rank_in_holdings}</td>
                <td className="mono-cell">{h.security_code}</td>
                <td>{h.security_name}</td>
                <td className="mono-cell">{h.weight_pct?.toFixed(2)}</td>
                <td>{h.industry ?? "—"}</td>
                <td>{h.change_direction ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
