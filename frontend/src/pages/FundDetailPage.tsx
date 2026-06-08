import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type FundProfile, type NavMetricsData } from "../api/client";

export default function FundDetailPage() {
  const { code } = useParams<{ code: string }>();
  const [profile, setProfile] = useState<FundProfile | null>(null);
  const [nav, setNav] = useState<NavMetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    Promise.all([api.getFundProfile(code), api.getNavMetrics(code)])
      .then(([p, n]) => {
        if (p.data) setProfile(p.data);
        if (n.data) setNav(n.data);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [code]);

  if (loading) return <p>加载中...</p>;
  if (error) return <p style={{ color: "var(--color-danger)" }}>加载失败: {error}</p>;
  if (!profile) return <p>未找到基金 {code}</p>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: 16 }}>
        <div>
          <h1>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>{profile.fund_code}</span>
            {" "}{profile.short_name}
          </h1>
          <p style={{ color: "var(--color-text-secondary)" }}>
            {profile.company_name} | {profile.category} | 成立: {profile.inception_date}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <SubLink to={`/funds/${code}/holdings`} label="持仓" />
          <SubLink to={`/funds/${code}/exposure`} label="暴露与归因" />
          <SubLink to={`/funds/${code}/packet`} label="研究包" />
          <SubLink to={`/funds/${code}/diff`} label="对比" />
        </div>
      </div>

      {/* Managers */}
      <div className="card">
        <h3 style={{ marginBottom: 8 }}>基金经理</h3>
        {profile.managers.map((m, i) => (
          <p key={i}>{m.name} · 任职 {m.tenure_days} 天{m.is_current ? " (现任)" : ""}</p>
        ))}
      </div>

      {/* Fee + Scale */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div className="card">
          <h3 style={{ marginBottom: 8 }}>费率</h3>
          {profile.fee_info ? (
            <div>
              <p>管理费: {profile.fee_info.mgmt_fee_pct}%</p>
              {profile.fee_info.custody_fee_pct != null && <p>托管费: {profile.fee_info.custody_fee_pct}%</p>}
            </div>
          ) : <p style={{ color: "var(--color-text-secondary)" }}>费率数据未获取</p>}
        </div>
        <div className="card">
          <h3 style={{ marginBottom: 8 }}>规模</h3>
          {profile.scale_history.length > 0 ? (
            <p>{profile.scale_history[0].total_nav} 亿 ({profile.scale_history[0].report_date})</p>
          ) : <p style={{ color: "var(--color-text-secondary)" }}>规模数据未获取</p>}
        </div>
      </div>

      {/* NAV Metrics — multi-period */}
      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ marginBottom: 12 }}>净值指标（多区间）</h3>
        {nav ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>区间</th>
                <th>状态</th>
                <th>年化收益</th>
                <th>最大回撤</th>
                <th>夏普比率</th>
                <th>卡玛比率</th>
                <th>样本数</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(nav.periods).map(([key, p]) => (
                <tr key={key}>
                  <td>{p.label}</td>
                  <td><span className={`badge badge-${p.status}`}>{p.status}</span></td>
                  <td>{fmtPct(p.metrics?.annualized_return)}</td>
                  <td>{fmtPct(p.metrics?.max_drawdown)}</td>
                  <td>{fmtNum(p.metrics?.sharpe_ratio)}</td>
                  <td>{fmtNum(p.metrics?.calmar_ratio)}</td>
                  <td>{p.observations}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p style={{ color: "var(--color-text-secondary)" }}>净值数据未获取</p>}
      </div>
    </div>
  );
}

function SubLink({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} style={{ padding: "4px 12px", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", fontSize: 13 }}>
      {label}
    </Link>
  );
}

function fmtPct(v: unknown): string {
  if (v == null) return "—";
  return (Number(v) * 100).toFixed(2) + "%";
}
function fmtNum(v: unknown): string {
  if (v == null) return "—";
  return Number(v).toFixed(2);
}
