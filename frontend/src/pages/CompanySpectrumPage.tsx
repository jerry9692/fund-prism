// 公司画像频谱与经理团队画像（P4E，需求书 §6.2.6 / §12.4.5）
// alpha-beta 气泡谱（气泡=规模，颜色=基金族）+ 单公司频谱详情 + 经理画像

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { EChartsOption } from "echarts";
import {
  api,
  type CompanySpectraOverview,
  type CompanySpectrumDetail,
  type ManagerProfileDetail,
  type ManagerSummary,
} from "../api/client";
import {
  Breadcrumb,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  SectionHeader,
  StatusBadge,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { ChartWrapper } from "../components/data/ChartWrapper";

const BREADCRUMB: BreadcrumbItem[] = [{ label: "公司画像频谱" }];

const FAMILY_COLORS: Record<string, string> = {
  equity_family: "#5470c6",
  mixed_family: "#91cc75",
  index_family: "#fac858",
  bond_family: "#ee6666",
  money_family: "#73c0de",
};

const STYLE_LABELS: Record<string, string> = {
  large_cap: "大盘",
  mid_cap: "中盘",
  small_cap: "小盘",
  growth: "成长",
  value: "价值",
};

function fmtPct(v: number | string | null | undefined, digits = 2): string {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | string | null | undefined, digits = 2): string {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export default function CompanySpectrumPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<CompanySpectraOverview | null>(null);

  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [spectrum, setSpectrum] = useState<CompanySpectrumDetail | null>(null);
  const [spectrumLoading, setSpectrumLoading] = useState(false);

  const [managers, setManagers] = useState<ManagerSummary[]>([]);
  const [selectedManager, setSelectedManager] = useState<ManagerSummary | null>(null);
  const [profile, setProfile] = useState<ManagerProfileDetail | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [spectraRes, managersRes] = await Promise.all([
          api.getCompanySpectraOverview(),
          api.listManagers(),
        ]);
        if (cancelled) return;
        setOverview(spectraRes.data ?? null);
        setManagers(managersRes.data?.managers ?? []);
        if (!spectraRes.data) setError(spectraRes.warnings.join("；"));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadSpectrum = useCallback(async (companyId: string) => {
    setSpectrumLoading(true);
    try {
      const res = await api.getCompanySpectrum(companyId);
      setSpectrum(res.data ?? null);
    } catch {
      setSpectrum(null);
    } finally {
      setSpectrumLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedCompany) {
      setSpectrum(null);
      return;
    }
    loadSpectrum(selectedCompany);
  }, [selectedCompany, loadSpectrum]);

  async function handleSelectManager(m: ManagerSummary) {
    setSelectedManager(m);
    setProfileLoading(true);
    try {
      const res = await api.getManagerProfile(m.manager_id);
      setProfile(res.data ?? null);
    } catch {
      setProfile(null);
    } finally {
      setProfileLoading(false);
    }
  }

  // ---- 气泡图：x=alpha(%)，y=beta，气泡=规模，颜色=基金族 ----
  const bubbleOption = useMemo<EChartsOption | null>(() => {
    const funds = overview?.funds?.filter(
      (f) => f.alpha_annualized != null && f.beta != null
    );
    if (!funds || funds.length === 0) return null;
    const families = Array.from(new Set(funds.map((f) => f.family)));
    return {
      title: { text: "全池 alpha-beta 频谱（对沪深300，气泡=规模）", left: 0 },
      tooltip: {
        formatter: (p) => {
          const single = Array.isArray(p) ? p[0] : p;
          const d =
            single && Array.isArray(single.data)
              ? (single.data as Array<number | string>)
              : [];
          if (d.length < 5) return "";
          return `${d[4]}<br/>${d[3]}<br/>alpha ${Number(d[0]).toFixed(2)}% / beta ${Number(d[1]).toFixed(2)}<br/>规模 ${
            d[2] ? `${Number(d[2]).toFixed(1)} 亿` : "—"
          }`;
        },
      },
      legend: { top: 0, right: 0 },
      grid: { left: 56, right: 24, top: 44, bottom: 36 },
      xAxis: {
        type: "value" as const,
        name: "年化 Alpha(%)",
        splitLine: { show: true },
      },
      yAxis: { type: "value" as const, name: "Beta", splitLine: { show: true } },
      series: families.map((family) => ({
        name: funds.find((f) => f.family === family)?.family_label ?? family,
        type: "scatter" as const,
        itemStyle: { color: FAMILY_COLORS[family] ?? "#999" },
        data: funds
          .filter((f) => f.family === family)
          .map((f) => [
            Number(((f.alpha_annualized ?? 0) * 100).toFixed(3)),
            Number((f.beta ?? 0).toFixed(3)),
            f.scale ?? 1,
            f.fund_name ?? f.fund_code,
            f.company_name,
          ]),
        symbolSize: (d: number[]) => Math.max(6, Math.min(34, Math.sqrt(d[2] ?? 1) * 2.2)),
      })),
    };
  }, [overview]);

  // ---- 公司详情表 ----
  const spectrumFundColumns: Column<CompanySpectrumDetail["funds"][number]>[] = [
    {
      key: "fund",
      header: "基金",
      render: (f) => (
        <div>
          <div>{f.fund_name ?? f.fund_code}</div>
          <div className="mono text-tertiary text-xs">{f.fund_code}</div>
        </div>
      ),
    },
    { key: "family", header: "基金族", render: (f) => f.family_label },
    {
      key: "alpha",
      header: "年化 Alpha",
      numeric: true,
      sortable: true,
      sortValue: (f) => f.alpha_annualized,
      render: (f) => fmtPct(f.alpha_annualized),
    },
    {
      key: "beta",
      header: "Beta",
      numeric: true,
      sortable: true,
      sortValue: (f) => f.beta,
      render: (f) => fmtNum(f.beta),
    },
    {
      key: "scale",
      header: "规模（亿）",
      numeric: true,
      sortValue: (f) => f.scale,
      render: (f) => (f.scale != null ? f.scale.toFixed(1) : "—"),
    },
  ];

  // ---- 经理列表表 ----
  const managerColumns: Column<ManagerSummary>[] = [
    { key: "name", header: "经理", render: (m) => <strong>{m.name}</strong> },
    {
      key: "funds",
      header: "在管基金",
      numeric: true,
      sortValue: (m) => m.current_fund_count,
      sortable: true,
      render: (m) => String(m.current_fund_count),
    },
    {
      key: "alpha",
      header: "任期加权 Alpha",
      numeric: true,
      sortable: true,
      sortValue: (m) => m.tenure_weighted_alpha,
      render: (m) => fmtPct(m.tenure_weighted_alpha),
    },
    {
      key: "scale",
      header: "管理规模（亿）",
      numeric: true,
      sortValue: (m) => m.managed_scale,
      sortable: true,
      render: (m) => (m.managed_scale != null ? m.managed_scale.toFixed(1) : "—"),
    },
    {
      key: "years",
      header: "从业年限",
      numeric: true,
      render: (m) => (m.experience_years != null ? m.experience_years.toFixed(1) : "—"),
    },
  ];

  // ---- 经理在管/历任明细表 ----
  type CurrentFundRow = ManagerProfileDetail["current_funds"][number] & {
    rank_text: string | null;
  };
  const currentFundColumns: Column<CurrentFundRow>[] = [
    {
      key: "fund",
      header: "基金",
      render: (f) => (
        <div>
          <div>{f.fund_name ?? f.fund_code}</div>
          <div className="mono text-tertiary text-xs">{f.fund_code}</div>
        </div>
      ),
    },
    { key: "start", header: "任职起始", render: (f) => <span className="mono">{f.start_date}</span> },
    {
      key: "tenure_days",
      header: "任职天数",
      numeric: true,
      sortValue: (f) => f.tenure_days,
      sortable: true,
      render: (f) => (f.tenure_days != null ? String(f.tenure_days) : "—"),
    },
    {
      key: "alpha",
      header: "年化 Alpha",
      numeric: true,
      sortValue: (f) => f.alpha_annualized,
      sortable: true,
      render: (f) => fmtPct(f.alpha_annualized),
    },
    { key: "rank", header: "同类排名", render: (f) => f.rank_text ?? "—" },
    {
      key: "scale",
      header: "规模（亿）",
      numeric: true,
      sortValue: (f) => f.scale,
      render: (f) => (f.scale != null ? f.scale.toFixed(1) : "—"),
    },
  ];

  const historyColumns: Column<ManagerProfileDetail["history_tenures"][number]>[] = [
    { key: "fund", header: "基金", render: (t) => <span className="mono">{t.fund_code}</span> },
    { key: "start", header: "起始", render: (t) => <span className="mono">{t.start_date}</span> },
    { key: "end", header: "结束", render: (t) => <span className="mono">{t.end_date ?? "—"}</span> },
    {
      key: "days",
      header: "任职天数",
      numeric: true,
      render: (t) => (t.tenure_days != null ? String(t.tenure_days) : "—"),
    },
    {
      key: "return",
      header: "任期收益",
      numeric: true,
      sortValue: (t) => t.tenure_return,
      sortable: true,
      render: (t) => fmtPct(t.tenure_return),
    },
  ];

  return (
    <div className="page">
      <Breadcrumb items={BREADCRUMB} />
      <SectionHeader
        title="公司画像频谱"
        subtitle="按基金公司聚合在库基金：alpha/beta 频谱（Jensen 口径对沪深300）、风格分布、类型结构与规模光谱；基金数 <3 的公司标样本不足"
      />

      {error && <ErrorState title="加载失败" desc={error} />}
      {loading && <LoadingState rows={6} cols={6} />}

      {!loading && !error && overview && (
        <>
          {bubbleOption ? (
            <div style={{ marginBottom: 16 }}>
              <ChartWrapper option={bubbleOption} height={380} />
            </div>
          ) : (
            <EmptyState title="无可绘制基金" desc="全池基金 alpha/beta 均不可计算" />
          )}

          <SectionHeader
            title="单公司频谱"
            subtitle="选择公司查看 alpha/beta 汇总、类型结构、风格分布与规模光谱"
          />
          <div style={{ marginBottom: 12 }}>
            <select
              className="input"
              style={{ maxWidth: 420 }}
              value={selectedCompany}
              onChange={(e) => setSelectedCompany(e.target.value)}
            >
              <option value="">选择基金公司…</option>
              {overview.companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.company_name}（{c.fund_count} 只{c.insufficient_sample ? "，样本不足" : ""}）
                </option>
              ))}
            </select>
          </div>

          {selectedCompany && spectrumLoading && <LoadingState rows={3} cols={5} />}
          {selectedCompany && !spectrumLoading && spectrum && (
            <>
              <div className="grid grid-cols-4 gap-4" style={{ marginBottom: 12 }}>
                <MetricCard label="在库基金数" value={String(spectrum.fund_count)} />
                <MetricCard
                  label="Alpha 中位数"
                  value={fmtPct(spectrum.alpha_beta_summary.median_alpha)}
                  sub={`区间 ${fmtPct(spectrum.alpha_beta_summary.min_alpha)} ~ ${fmtPct(spectrum.alpha_beta_summary.max_alpha)}`}
                />
                <MetricCard
                  label="Beta 中位数"
                  value={fmtNum(spectrum.alpha_beta_summary.median_beta)}
                />
                <MetricCard
                  label="规模合计（亿）"
                  value={
                    spectrum.scale_spectrum.total != null
                      ? spectrum.scale_spectrum.total.toFixed(1)
                      : "—"
                  }
                  sub={`中位数 ${
                    spectrum.scale_spectrum.median != null
                      ? spectrum.scale_spectrum.median.toFixed(1)
                      : "—"
                  }`}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                <StatusBadge status={spectrum.conclusion_status} />
                <span className="text-tertiary text-xs">
                  {spectrum.warnings.join("；") || "无告警"}
                </span>
              </div>

              <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
                <div>
                  <SectionHeader title="类型结构" subtitle="基金族占比" />
                  {Object.entries(spectrum.category_structure).map(([family, entry]) => (
                    <div
                      key={family}
                      style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}
                    >
                      <span
                        style={{
                          display: "inline-block",
                          width: 8,
                          height: 8,
                          borderRadius: 4,
                          background: FAMILY_COLORS[family] ?? "#999",
                        }}
                      />
                      <span style={{ flex: 1 }}>{entry.label}</span>
                      <span className="mono">{entry.count} 只</span>
                      <span className="mono text-tertiary">{fmtPct(entry.share, 1)}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <SectionHeader title="风格分布" subtitle="指纹风格维度均值（有风格数据的成员）" />
                  {spectrum.style_distribution.available ? (
                    Object.entries(spectrum.style_distribution.dimensions ?? {}).map(
                      ([dim, value]) => (
                        <div
                          key={dim}
                          style={{ display: "flex", gap: 8, padding: "4px 0" }}
                        >
                          <span style={{ flex: 1 }}>{STYLE_LABELS[dim] ?? dim}</span>
                          <span className="mono">{fmtNum(value)}</span>
                        </div>
                      )
                    )
                  ) : (
                    <div className="text-tertiary text-xs">成员指纹均无风格维度，不可得</div>
                  )}
                </div>
              </div>

              <DataTable
                columns={spectrumFundColumns}
                data={spectrum.funds}
                rowKey={(f) => f.fund_code}
                onRowClick={(f) => navigate(`/funds/${f.fund_code}`)}
                initialSort={{ key: "alpha", order: "desc" }}
              />
            </>
          )}

          {/* 经理团队画像 */}
          <SectionHeader
            title="经理团队画像"
            subtitle="任期加权 alpha（Jensen 口径）/ 管理规模 / 风格稳定性（复用异常扫描风格漂移）/ 同类排名中位数（rank.py 口径）"
          />
          <DataTable
            columns={managerColumns}
            data={managers}
            rowKey={(m) => m.manager_id}
            onRowClick={handleSelectManager}
            initialSort={{ key: "alpha", order: "desc" }}
          />

          {selectedManager && profileLoading && <LoadingState rows={3} cols={5} />}
          {selectedManager && !profileLoading && profile && (
            <div style={{ marginTop: 16 }}>
              <SectionHeader
                title={`${profile.name} · 画像详情`}
                subtitle={profile.education ?? undefined}
              />
              <div className="grid grid-cols-4 gap-4" style={{ marginBottom: 12 }}>
                <MetricCard
                  label="任期加权 Alpha"
                  value={fmtPct(profile.tenure_weighted_alpha)}
                />
                <MetricCard
                  label="管理规模（亿）"
                  value={
                    profile.managed_scale != null ? profile.managed_scale.toFixed(1) : "—"
                  }
                />
                <MetricCard
                  label="同类排名中位分位"
                  value={
                    profile.peer_rank.median_percentile != null
                      ? `${(profile.peer_rank.median_percentile * 100).toFixed(0)}%`
                      : "—"
                  }
                  sub="近一年收益同二级分类排名"
                />
                <MetricCard
                  label="风格稳定性"
                  value={
                    profile.style_stability.evaluable_funds === 0
                      ? "不可评估"
                      : profile.style_stability.stable
                        ? "稳定"
                        : `${profile.style_stability.drifted_funds.length} 只漂移`
                  }
                  sub={`可评估 ${profile.style_stability.evaluable_funds}/${profile.style_stability.current_fund_count} 只`}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                <StatusBadge status={profile.conclusion_status} />
                <span className="text-tertiary text-xs">
                  {profile.warnings.join("；") || "无告警"}
                </span>
              </div>

              <SectionHeader title="在管基金" />
              <DataTable
                columns={currentFundColumns}
                data={profile.current_funds.map((f) => ({
                  ...f,
                  rank_text:
                    profile.peer_rank.ranks.find((r) => r.fund_code === f.fund_code)
                      ?.rank_text ?? null,
                }))}
                rowKey={(f) => f.fund_code}
                onRowClick={(f) => navigate(`/funds/${f.fund_code}`)}
              />

              {profile.history_tenures.length > 0 && (
                <>
                  <SectionHeader title="历任记录" />
                  <DataTable
                    columns={historyColumns}
                    data={profile.history_tenures}
                    rowKey={(t) => `${t.fund_code}-${t.start_date}`}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
