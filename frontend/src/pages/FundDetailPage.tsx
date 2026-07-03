// 基金详情页 — 分组 Tab 式分析中心
// 概览 / 持仓分析 / 风格与归因 / 评分与实验 / 研究输出 / 校验

import { useEffect, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { api, type FundProfile, type NavMetricsData } from "../api/client";
import {
  SectionHeader,
  MetricCard,
  StatusBadge,
  TabNav,
  PeriodTabs,
  LoadingState,
  ErrorState,
  type TabItem,
} from "../components/display";
import { ChartWrapper } from "../components/data/ChartWrapper";

export default function FundDetailPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const [profile, setProfile] = useState<FundProfile | null>(null);
  const [navMetrics, setNavMetrics] = useState<NavMetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState("1y");

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setError(null);

    Promise.all([api.getFundProfile(code), api.getNavMetrics(code)])
      .then(([profileRes, navRes]) => {
        setProfile(profileRes.data ?? null);
        setNavMetrics(navRes.data ?? null);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => setLoading(false));

    // 记录到最近浏览
    try {
      const raw = localStorage.getItem("recent_funds");
      const recents = raw ? JSON.parse(raw) : [];
      const filtered = recents.filter(
        (r: { code: string }) => r.code !== code
      );
      filtered.unshift({
        code,
        name: profile?.short_name ?? code,
        ts: Date.now(),
      });
      localStorage.setItem(
        "recent_funds",
        JSON.stringify(filtered.slice(0, 10))
      );
    } catch {
      // ignore
    }
  }, [code]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabs: TabItem[] = [
    { key: "overview", label: "概览" },
    { key: "holdings", label: "持仓分析" },
    { key: "exposure", label: "风格与归因" },
    { key: "scoring", label: "评分与实验", badge: "实验" },
    { key: "packet", label: "研究输出" },
    { key: "review", label: "校验" },
  ];

  // 从 URL 推断当前 Tab
  const path = location.pathname;
  let activeTab = "overview";
  if (path.includes("/holdings")) activeTab = "holdings";
  else if (path.includes("/exposure")) activeTab = "exposure";
  else if (path.includes("/scoring")) activeTab = "scoring";
  else if (path.includes("/packet") || path.includes("/diff"))
    activeTab = "packet";
  else if (path.includes("/review")) activeTab = "review";
  else if (path.includes("/simulated") || path.includes("/attribution"))
    activeTab = "scoring";

  const handleTabChange = (key: string) => {
    const tabToPath: Record<string, string> = {
      overview: `/funds/${code}`,
      holdings: `/funds/${code}/holdings`,
      exposure: `/funds/${code}/exposure`,
      scoring: `/funds/${code}/scoring`,
      packet: `/funds/${code}/packet`,
      review: `/funds/${code}/review`,
    };
    navigate(tabToPath[key] ?? `/funds/${code}`);
  };

  if (loading) {
    return (
      <div>
        <LoadingState rows={4} cols={4} />
      </div>
    );
  }

  if (error || !profile) {
    return (
      <ErrorState
        title="基金信息加载失败"
        desc={error ?? "未找到该基金"}
        onRetry={() => navigate("/funds")}
      />
    );
  }

  // 提取净值指标
  const periodLabels: Record<string, string> = {
    "1m": "近1月",
    "3m": "近3月",
    "6m": "近半年",
    "1y": "近1年",
    "3y": "近3年",
    "5y": "近5年",
    since_inception: "成立以来",
  };

  const currentPeriodKey = period === "all" ? "since_inception" : period;
  const currentPeriodData = navMetrics?.periods?.[currentPeriodKey];
  const metrics = currentPeriodData?.metrics ?? {};

  const fmtPct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;

  const fmtNum = (v: number | null | undefined, digits = 4) =>
    v === null || v === undefined ? "—" : v.toFixed(digits);

  return (
    <div>
      {/* 面包屑 */}
      <div className="breadcrumb fade-up fade-up-1">
        <a href="/funds">基金筛选</a>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">
          {code} {profile.short_name}
        </span>
      </div>

      {/* 基金标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center gap-3">
          <h1 className="mono">{code}</h1>
          <span className="text-lg">{profile.short_name}</span>
          <span className="text-sm text-tertiary">{profile.category}</span>
        </div>
        <div className="text-sm text-tertiary mt-2 flex gap-4">
          <span>
            管理{" "}
            <span className="mono">
              {profile.scale_history?.[0]?.total_nav
                ? (profile.scale_history[0].total_nav / 1e8).toFixed(2) + "亿"
                : "—"}
            </span>
          </span>
          <span>
            成立{" "}
            <span className="mono">{profile.inception_date ?? "—"}</span>
          </span>
          {profile.managers?.[0] && (
            <span>
              经理{" "}
              <span>
                {profile.managers[0].name} · 任职{" "}
                <span className="mono">
                  {profile.managers[0].tenure_days}天
                </span>
              </span>
            </span>
          )}
        </div>
      </div>

      {/* 分组 Tab */}
      <TabNav tabs={tabs} active={activeTab} onChange={handleTabChange} />

      {/* 概览 Tab 内容 (其他 Tab 由各自路由页面渲染) */}
      {activeTab === "overview" && (
        <div className="page-enter">
          {/* 指标卡片 */}
          <div className="grid grid-4 fade-up fade-up-2 mb-6">
            <MetricCard
              label={`${periodLabels[currentPeriodKey] ?? "近1年"} 收益`}
              value={fmtPct(metrics.annualized_return ?? metrics.total_return)}
              positive={(metrics.annualized_return ?? metrics.total_return ?? 0) >= 0}
              negative={(metrics.annualized_return ?? metrics.total_return ?? 0) < 0}
            />
            <MetricCard
              label="最大回撤"
              value={fmtPct(metrics.max_drawdown)}
              negative={true}
            />
            <MetricCard
              label="夏普比率"
              value={fmtNum(metrics.sharpe_ratio)}
            />
            <MetricCard
              label="波动率"
              value={fmtPct(metrics.volatility)}
            />
          </div>

          {/* 净值曲线 */}
          <div className="fade-up fade-up-3 mb-6">
            <SectionHeader
              title="净值曲线"
              actions={
                <PeriodTabs active={period} onChange={setPeriod} />
              }
            />
            {currentPeriodData ? (
              <ChartWrapper
                height={300}
                option={{
                  grid: { left: 50, right: 20, top: 20, bottom: 30 },
                  xAxis: {
                    type: "category",
                    data: [],
                    axisLabel: { fontSize: 11 },
                  },
                  yAxis: {
                    type: "value",
                    axisLabel: {
                      fontSize: 11,
                      formatter: (v: number) => (v * 100).toFixed(1) + "%",
                    },
                  },
                  series: [
                    {
                      name: "累计收益",
                      type: "line",
                      data: [],
                      smooth: true,
                      showSymbol: false,
                      lineStyle: { width: 2 },
                      areaStyle: { opacity: 0.08 },
                    },
                  ],
                }}
                loading={false}
              />
            ) : (
              <div className="text-sm text-tertiary">
                当前区间无净值数据。
              </div>
            )}
            {currentPeriodData?.warnings?.map((w, i) => (
              <div key={i} className="text-xs text-warning mt-2">
                ⚠ {w}
              </div>
            ))}
          </div>

          {/* 基金经理任职 */}
          <div className="fade-up fade-up-4 mb-6">
            <SectionHeader title="基金经理任职记录" />
            {profile.managers?.length > 0 ? (
              <div className="flex flex-col gap-2">
                {profile.managers.map((m, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between"
                    style={{
                      padding: "var(--space-2) var(--space-3)",
                      borderBottom: "1px solid var(--border-hairline)",
                    }}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-medium">{m.name}</span>
                      {m.is_current && (
                        <span className="status-badge status-badge-fact">
                          现任
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-tertiary">
                      <span className="mono">{m.start_date ?? "—"}</span>
                      {" → "}
                      {m.is_current ? "至今" : "—"}
                      <span className="mono ml-3">{m.tenure_days}天</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-tertiary">暂无经理信息</div>
            )}
          </div>

          {/* 基金费率 */}
          {profile.fee_info && (
            <div className="fade-up fade-up-5 mb-6">
              <SectionHeader title="费率信息" />
              <div className="grid grid-3">
                <MetricCard
                  label="管理费"
                  value={`${profile.fee_info.mgmt_fee_pct}%`}
                />
                <MetricCard
                  label="托管费"
                  value={
                    profile.fee_info.custody_fee_pct !== null
                      ? `${profile.fee_info.custody_fee_pct}%`
                      : "—"
                  }
                />
                <MetricCard
                  label="销售服务费"
                  value={
                    profile.fee_info.sales_service_fee_pct !== null
                      ? `${profile.fee_info.sales_service_fee_pct}%`
                      : "—"
                  }
                />
              </div>
            </div>
          )}

          {/* 数据质量摘要 */}
          {currentPeriodData && (
            <div className="fade-up fade-up-6">
              <SectionHeader title="数据质量" />
              <div className="flex gap-4 text-sm">
                <span className="text-tertiary">
                  观测数: <span className="mono">{currentPeriodData.observations}</span>
                </span>
                <span className="text-tertiary">
                  区间:{" "}
                  <span className="mono">
                    {currentPeriodData.start_date ?? "—"} →{" "}
                    {currentPeriodData.end_date ?? "—"}
                  </span>
                </span>
                <StatusBadge status={currentPeriodData.status} />
              </div>
            </div>
          )}
        </div>
      )}

      {/* 非 overview Tab 时显示子页面占位（实际由路由渲染子页面） */}
      {activeTab !== "overview" && (
        <div className="text-sm text-tertiary page-enter">
          正在加载 {tabs.find((t) => t.key === activeTab)?.label}…
        </div>
      )}
    </div>
  );
}
