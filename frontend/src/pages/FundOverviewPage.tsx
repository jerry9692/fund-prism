// 基金概览页 — 净值指标卡片 + 净值曲线图 + 经理任职 + 费率 + 数据质量

import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { api, type NavMetricsData, type NavSeriesData } from "../api/client";
import {
  SectionHeader,
  MetricCard,
  StatusBadge,
  PeriodTabs,
  LoadingState,
  Breadcrumb,
  type BreadcrumbItem,
} from "../components/display";
import { ChartWrapper, CHART_COLORS } from "../components/data/ChartWrapper";

interface OutletContext {
  fundCode: string;
  profile: any;
}

const PERIOD_API_MAP: Record<string, string> = {
  "1m": "1M",
  "3m": "3M",
  "6m": "6M",
  "1y": "1Y",
  "3y": "3Y",
  "5y": "5Y",
  all: "ALL",
};

export default function FundOverviewPage() {
  const { fundCode, profile } = useOutletContext<OutletContext>();

  const [navMetrics, setNavMetrics] = useState<NavMetricsData | null>(null);
  const [navSeries, setNavSeries] = useState<NavSeriesData | null>(null);
  const [period, setPeriod] = useState("1y");
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(() => {
    setLoading(true);
    const apiPeriod = PERIOD_API_MAP[period] ?? "1Y";
    Promise.all([
      api.getNavMetrics(fundCode),
      api.getNavSeries(fundCode, { period: apiPeriod }),
    ])
      .then(([metricsRes, seriesRes]) => {
        setNavMetrics(metricsRes.data ?? null);
        setNavSeries(seriesRes.data ?? null);
      })
      .catch(() => {
        // errors handled by ErrorBoundary
      })
      .finally(() => setLoading(false));
  }, [fundCode, period]);

  useEffect(() => {
    loadData();
  }, [loadData]);

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
  const metricsPeriodKey =
    period === "all" ? "since_inception" : (PERIOD_API_MAP[period] ?? period);
  const currentPeriodData = navMetrics?.periods?.[metricsPeriodKey];
  const metrics = currentPeriodData?.metrics ?? {};

  const fmtPct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
  const fmtNum = (v: number | null | undefined, digits = 4) =>
    v === null || v === undefined ? "—" : v.toFixed(digits);

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: fundCode, to: `/funds/${fundCode}` },
    { label: "概览" },
  ];

  // 构建图表数据
  const chartOption = (() => {
    if (!navSeries || !navSeries.dates?.length) return null;
    const fundData = navSeries.normalized_nav
      .map((v, i) => {
        const d = navSeries.dates[i];
        if (v == null || d == null) return null;
        return [d, v] as [string, number];
      })
      .filter((x): x is [string, number] => x !== null);
    const bmData = navSeries.benchmark_dates
      .map((d, i) => {
        const v = navSeries.benchmark_normalized_nav[i];
        if (v == null || d == null) return null;
        return [d, v] as [string, number];
      })
      .filter((x): x is [string, number] => x !== null);
    const option: any = {
      grid: { left: 50, right: 50, top: 30, bottom: 30 },
      tooltip: {
        trigger: "axis",
        formatter: (params: any) => {
          const date = params[0]?.axisValue ?? "";
          let s = `<div style="font-family:var(--font-mono);font-size:12px">${date}<br/>`;
          for (const p of params) {
            const v = p.value?.[1];
            if (v != null) {
              const ret = ((v - 1) * 100).toFixed(2);
              const isPos = Number(ret) >= 0;
              const color = isPos ? CHART_COLORS.positive : CHART_COLORS.negative;
              s += `<span style="color:${p.color}">${p.seriesName}</span>: <span style="color:${color}">${isPos ? "+" : ""}${ret}%</span><br/>`;
            }
          }
          return s + "</div>";
        },
      },
      xAxis: {
        type: "category" as const,
        data: navSeries.dates,
        axisLabel: {
          fontSize: 11,
          fontFamily: "var(--font-mono)",
          color: CHART_COLORS.tertiary,
          interval: Math.floor(navSeries.dates.length / 6),
        },
        axisLine: { lineStyle: { color: CHART_COLORS.borderHairline } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value" as const,
        scale: true,
        axisLabel: {
          fontSize: 11,
          fontFamily: "var(--font-mono)",
          color: CHART_COLORS.tertiary,
          formatter: (v: number) => `${((v - 1) * 100).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: CHART_COLORS.borderHairline, type: "dashed" as const } },
      },
      series: [
        {
          name: navSeries.fund_code,
          type: "line" as const,
          data: fundData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: CHART_COLORS.accent },
          itemStyle: { color: CHART_COLORS.accent },
          areaStyle: { color: "rgba(180,83,9,0.08)" },
          encode: { x: 0, y: 1 },
        },
        ...(bmData.length > 0
          ? [
              {
                name: navSeries.benchmark_code ?? "基准",
                type: "line" as const,
                data: bmData,
                smooth: true,
                showSymbol: false,
                lineStyle: { width: 1.5, color: CHART_COLORS.info, type: "dashed" as const },
                itemStyle: { color: CHART_COLORS.info },
                encode: { x: 0, y: 1 },
              },
            ]
          : []),
      ],
    };
    return option;
  })();

  return (
    <div>
      <Breadcrumb items={crumbs} />
      {/* 指标卡片 */}
      <div className="grid grid-4 fade-up fade-up-2 mb-6">
        <MetricCard
          label={`${periodLabels[currentPeriodKey] ?? "近1年"} 收益`}
          value={fmtPct(metrics.annualized_return ?? metrics.total_return)}
          positive={(metrics.annualized_return ?? metrics.total_return ?? 0) >= 0}
          negative={(metrics.annualized_return ?? metrics.total_return ?? 0) < 0}
        />
        <MetricCard label="最大回撤" value={fmtPct(metrics.max_drawdown)} negative={true} />
        <MetricCard label="夏普比率" value={fmtNum(metrics.sharpe_ratio)} />
        <MetricCard label="波动率" value={fmtPct(metrics.annualized_volatility)} />
      </div>

      {/* 净值曲线 */}
      <div className="fade-up fade-up-3 mb-6">
        <SectionHeader
          title="净值曲线"
          actions={<PeriodTabs active={period} onChange={setPeriod} />}
        />
        {loading ? (
          <div style={{ height: 300 }}>
            <LoadingState rows={6} cols={4} />
          </div>
        ) : chartOption ? (
          <ChartWrapper height={320} option={chartOption} />
        ) : (
          <div className="text-sm text-tertiary">当前区间无净值数据。</div>
        )}
        {currentPeriodData?.warnings?.map((w: string, i: number) => (
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
            {profile.managers.map((m: any, i: number) => (
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
                    <span className="status-badge status-badge-fact">现任</span>
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
            <MetricCard label="管理费" value={`${profile.fee_info.mgmt_fee_pct}%`} />
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
                  : "不适用"
              }
              sub={
                profile.fee_info.sales_service_fee_pct === null
                  ? "A 类份额不收销售服务费"
                  : undefined
              }
            />
          </div>
        </div>
      )}

      {/* 数据质量摘要 */}
      {currentPeriodData && (
        <div className="fade-up fade-up-6">
          <SectionHeader title="数据质量" />
          <div className="flex gap-4 text-sm flex-wrap">
            <span className="text-tertiary">
              观测数: <span className="mono">{currentPeriodData.observations}</span>
            </span>
            <span className="text-tertiary">
              区间:{" "}
              <span className="mono">
                {currentPeriodData.start_date ?? "—"} → {currentPeriodData.end_date ?? "—"}
              </span>
            </span>
            <StatusBadge status={currentPeriodData.status} />
          </div>
        </div>
      )}
    </div>
  );
}
