import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type FundProfile, type NavMetricsData } from "../api/client";
import PeriodSelector, { periodToStartDate, type PeriodKey } from "../components/PeriodSelector";

function fmtPct(v: unknown): string {
  if (v == null) return "—";
  return (Number(v) * 100).toFixed(2) + "%";
}
function fmtNum(v: unknown): string {
  if (v == null) return "—";
  return Number(v).toFixed(2);
}

export default function FundDetailPage() {
  const { code } = useParams<{ code: string }>();
  const [profile, setProfile] = useState<FundProfile | null>(null);
  const [nav, setNav] = useState<NavMetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<PeriodKey>("1Y");
  const [navLoading, setNavLoading] = useState(false);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    api
      .getFundProfile(code)
      .then((p) => {
        if (p.data) setProfile(p.data);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [code]);

  const loadNav = useCallback(
    (p: PeriodKey) => {
      if (!code) return;
      setNavLoading(true);
      const start = periodToStartDate(p);
      api
        .getNavMetrics(code, { start })
        .then((n) => {
          if (n.data) setNav(n.data);
        })
        .catch(() => {})
        .finally(() => setNavLoading(false));
    },
    [code]
  );

  useEffect(() => {
    loadNav(period);
  }, [period, loadNav]);

  if (loading) return <p className="text-muted">加载中...</p>;
  if (error) return <p className="text-danger">加载失败: {error}</p>;
  if (!profile) return <p>未找到基金 {code}</p>;

  const subLinks = [
    { to: `/funds/${code}/holdings`, label: "持仓" },
    { to: `/funds/${code}/exposure`, label: "暴露与归因" },
    { to: `/funds/${code}/scoring`, label: "评分" },
    { to: `/funds/${code}/simulated`, label: "模拟持仓" },
    { to: `/funds/${code}/attribution`, label: "动态归因" },
    { to: `/funds/${code}/packet`, label: "研究包" },
    { to: `/funds/${code}/diff`, label: "对比" },
    { to: `/funds/${code}/review`, label: "校验" },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title-row">
            <h1>{profile.short_name}</h1>
            <span className="fund-code">{profile.fund_code}</span>
          </div>
          <p className="subtitle">
            {profile.company_name} · {profile.category} · 成立于 {profile.inception_date ?? "—"}
          </p>
        </div>
        <div className="sub-link-row">
          {subLinks.map((l) => (
            <Link key={l.to} to={l.to} className="sub-link">{l.label}</Link>
          ))}
        </div>
      </div>

      <div className="metric-grid" style={{ marginBottom: "var(--space-md)" }}>
        <div className="metric-card">
          <div className="metric-card-label">管理费</div>
          <div className="metric-card-value">{profile.fee_info ? `${profile.fee_info.mgmt_fee_pct}%` : "—"}</div>
          <div className="metric-card-sub">{profile.fee_info?.custody_fee_pct != null ? `托管费 ${profile.fee_info.custody_fee_pct}%` : ""}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card-label">最新规模</div>
          <div className="metric-card-value">
            {profile.scale_history.length > 0 ? `${profile.scale_history[0].total_nav?.toFixed(2) ?? "—"}` : "—"}
          </div>
          <div className="metric-card-sub">
            {profile.scale_history.length > 0 ? profile.scale_history[0].report_date : ""}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-card-label">基金经理</div>
          <div className="metric-card-value" style={{ fontSize: 16 }}>
            {profile.managers.filter((m) => m.is_current).map((m) => m.name).join(", ") || "—"}
          </div>
          <div className="metric-card-sub">
            {(() => {
              const cur = profile.managers.find((m) => m.is_current);
              return cur ? `任职 ${cur.tenure_days} 天` : "";
            })()}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-card-label">基金状态</div>
          <div className="metric-card-value" style={{ fontSize: 16 }}>{profile.status}</div>
          <div className="metric-card-sub">{profile.custodian_bank ?? ""}</div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-md)", flexWrap: "wrap", gap: 12 }}>
          <h3 style={{ margin: 0 }}>净值指标</h3>
          <PeriodSelector value={period} onChange={setPeriod} />
        </div>
        {navLoading ? (
          <p className="text-muted">加载净值数据中...</p>
        ) : nav ? (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>区间</th>
                  <th>状态</th>
                  <th>年化收益</th>
                  <th>最大回撤</th>
                  <th>夏普比率</th>
                  <th>卡玛比率</th>
                  <th>波动率</th>
                  <th>样本数</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(nav.periods).map(([key, p]) => (
                  <tr key={key}>
                    <td style={{ fontWeight: 500 }}>{p.label}</td>
                    <td><span className={`badge badge-${p.status}`}>{p.status}</span></td>
                    <td className="mono-cell" style={{ fontWeight: 600 }}>{fmtPct(p.metrics?.annualized_return)}</td>
                    <td className="mono-cell">{fmtPct(p.metrics?.max_drawdown)}</td>
                    <td className="mono-cell">{fmtNum(p.metrics?.sharpe_ratio)}</td>
                    <td className="mono-cell">{fmtNum(p.metrics?.calmar_ratio)}</td>
                    <td className="mono-cell">{fmtPct(p.metrics?.annualized_volatility)}</td>
                    <td className="date-cell">{p.observations}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted">净值数据未获取</p>
        )}
        {nav && nav.custom && (
          <div style={{ marginTop: "var(--space-md)", paddingTop: "var(--space-md)", borderTop: "1px solid var(--color-border)" }}>
            <h4 style={{ marginBottom: 8 }}>自定义区间</h4>
            <p className="text-muted" style={{ fontSize: 13 }}>
              {nav.custom.start_date} ~ {nav.custom.end_date}: 年化 {fmtPct(nav.custom.metrics?.annualized_return)} |
              最大回撤 {fmtPct(nav.custom.metrics?.max_drawdown)} |
              夏普 {fmtNum(nav.custom.metrics?.sharpe_ratio)}
            </p>
          </div>
        )}
      </div>

      {profile.managers.length > 0 && (
        <div className="card">
          <h3 style={{ marginBottom: "var(--space-sm)" }}>基金经理任职记录</h3>
          <table className="data-table">
            <thead>
              <tr><th>姓名</th><th>任职天数</th><th>状态</th></tr>
            </thead>
            <tbody>
              {profile.managers.map((m, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 500 }}>{m.name}</td>
                  <td className="mono-cell">{m.tenure_days}</td>
                  <td>
                    {m.is_current ? (
                      <span className="badge badge-computed">现任</span>
                    ) : (
                      <span className="badge badge-observation">离任</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
