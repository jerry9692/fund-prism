// 风格暴露与归因页 — 新组件库 + 暴露柱状图 + 归因指标卡 + 窗口选择

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type ExposureData } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";
import { ChartWrapper } from "../components/data/ChartWrapper";

const STYLE_LABELS: Record<string, string> = {
  market: "市场",
  size: "规模",
  value: "价值",
  momentum: "动量",
  beta: "Beta",
  residual_volatility: "残差波动",
  non_lin_size: "非线性规模",
  liquidity: "流动性",
  growth: "成长",
  leverage: "杠杆",
};

export default function ExposurePage() {
  const { code } = useParams<{ code: string }>();
  const [data, setData] = useState<ExposureData | null>(null);
  const [windowSize, setWindowSize] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setError(null);
    api
      .getExposure(code, windowSize)
      .then((r) => setData(r.data ?? null))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [code, windowSize]);

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: code ?? "", to: `/funds/${code}` },
    { label: "风格与归因" },
  ];

  if (loading) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <LoadingState rows={6} cols={4} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <ErrorState title="暴露数据加载失败" desc={error ?? "无数据"} />
      </div>
    );
  }

  const exposureEntries = Object.entries(data.exposure_values);
  const attribution = data.static_attribution;

  // 暴露柱状图
  const exposureOption = {
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: "category" as const,
      data: exposureEntries.map(([key]) => STYLE_LABELS[key] ?? key),
      axisLabel: { fontSize: 11, rotate: exposureEntries.length > 6 ? 30 : 0 },
    },
    yAxis: {
      type: "value" as const,
      axisLabel: { fontSize: 11, formatter: (v: number) => v.toFixed(2) },
    },
    series: [
      {
        type: "bar" as const,
        data: exposureEntries.map(([, val]) => ({
          value: val,
          itemStyle: {
            color: val >= 0 ? "#B45309" : "#B23A3A",
          },
        })),
        barWidth: "50%",
      },
    ],
    tooltip: {
      trigger: "axis" as const,
    },
    markLine: {
      data: [{ yAxis: 0 }],
      lineStyle: { color: "#8F8678", type: "dashed" as const },
    },
  };

  const fmtNum = (v: number | null | undefined, digits = 4) =>
    v === null || v === undefined ? "—" : v.toFixed(digits);

  const fmtPct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>风格暴露与归因</h1>
          <div className="flex items-center gap-3">
            <span className="text-sm text-tertiary">回归窗口</span>
            <div className="period-tabs">
              {[20, 60, 120, 252].map((w) => (
                <button
                  key={w}
                  className={`period-tab ${windowSize === w ? "active" : ""}`}
                  onClick={() => setWindowSize(w)}
                >
                  {w}日
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="text-sm text-tertiary mt-2 flex gap-4">
          <span>
            观测数 <span className="mono">{data.observations}</span>
          </span>
          {data.r_squared !== null && (
            <span>
              R² <span className="mono">{data.r_squared.toFixed(3)}</span>
            </span>
          )}
          {data.residual !== null && (
            <span>
              残差 <span className="mono">{data.residual.toFixed(4)}</span>
            </span>
          )}
        </div>
      </div>

      {/* 暴露柱状图 */}
      <div className="fade-up fade-up-2 mb-6">
        <SectionHeader
          title="风格暴露系数"
          subtitle="正值表示正向暴露，负值表示反向暴露"
        />
        <ChartWrapper option={exposureOption} height={280} />
      </div>

      {/* 暴露指标卡 */}
      <div className="fade-up fade-up-3 mb-6">
        <SectionHeader title="暴露明细" />
        <div className="grid grid-4">
          {exposureEntries.map(([key, val]) => (
            <MetricCard
              key={key}
              label={STYLE_LABELS[key] ?? key}
              value={val.toFixed(3)}
              sub={Math.abs(val) > 0.5 ? "显著暴露" : "暴露较弱"}
              positive={val > 0.5}
              negative={val < -0.5}
            />
          ))}
          {data.residual !== null && (
            <MetricCard
              label="残差"
              value={data.residual.toFixed(4)}
              sub={Math.abs(data.residual) < 0.1 ? "拟合良好" : "拟合待复核"}
            />
          )}
        </div>
      </div>

      {/* 静态归因 */}
      {attribution && (
        <div className="fade-up fade-up-4">
          <SectionHeader
            title="静态归因"
            subtitle="基于披露持仓，不反映季度内调仓"
            actions={<StatusBadge status="observation" />}
          />
          <div
            className="mb-4"
            style={{
              padding: "var(--space-3) var(--space-4)",
              background: "var(--warning-soft)",
              borderLeft: "3px solid var(--warning)",
              borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
              fontSize: "0.82rem",
              color: "var(--warning)",
            }}
          >
            ⚠ 静态归因仅基于披露持仓，不反映季度内调仓，结论状态为 observation
          </div>
          <div className="grid grid-5">
            <MetricCard
              label="基金区间收益"
              value={fmtNum(attribution.total_return)}
            />
            <MetricCard
              label="可解释收益"
              value={fmtNum(attribution.explained_return)}
            />
            <MetricCard
              label="残差"
              value={fmtNum(attribution.residual)}
              sub={
                Math.abs(attribution.residual ?? 1) < 0.1
                  ? "拟合良好"
                  : "拟合待复核"
              }
            />
            <MetricCard
              label="残差占比"
              value={fmtPct(attribution.residual_pct)}
              sub={
                Math.abs(attribution.residual_pct ?? 1) < 0.2
                  ? "可接受"
                  : "偏高"
              }
            />
            <MetricCard
              label="覆盖率"
              value={fmtPct(attribution.coverage_rate)}
              sub={
                attribution.coverage_rate >= 0.8 ? "覆盖充分" : "覆盖不足"
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
