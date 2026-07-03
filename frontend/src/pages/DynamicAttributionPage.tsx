// 动态收益归因页 — 新组件库 + 面包屑 + 指标卡 + 归因柱状图 + 可切换归因记录

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type DynamicAttributionResult } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  type BreadcrumbItem,
} from "../components/display";
import { ChartWrapper } from "../components/data/ChartWrapper";
import type { EChartsOption } from "echarts";

function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function PctMetric({
  label,
  value,
}: {
  label: string;
  value: number | null | undefined;
}) {
  const hasValue = value !== null && value !== undefined;
  return (
    <MetricCard
      label={label}
      value={formatPct(value)}
      positive={hasValue && value > 0}
      negative={hasValue && value < 0}
    />
  );
}

function ResultListItem({
  result,
  selected,
  onClick,
}: {
  result: DynamicAttributionResult;
  selected: boolean;
  onClick: () => void;
}) {
  const period =
    result.period_start && result.period_end
      ? `${result.period_start} ~ ${result.period_end}`
      : result.created_at || "未知期间";
  return (
    <div
      onClick={onClick}
      style={{
        cursor: "pointer",
        background: "var(--surface-raised)",
        border: selected
          ? "2px solid var(--accent)"
          : "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-3)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className="mono"
            style={{ fontWeight: 600, color: "var(--ink-primary)" }}
          >
            {period}
          </span>
          <span className="text-sm text-tertiary">
            {result.algorithm_name} v{result.algorithm_version}
          </span>
        </div>
        <StatusBadge status={result.conclusion_status || "estimated"} />
      </div>
    </div>
  );
}

export default function DynamicAttributionPage() {
  const { code } = useParams<{ code: string }>();
  const fundCode = code || "";

  const [results, setResults] = useState<DynamicAttributionResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);

  const loadResults = () => {
    if (!fundCode) return;
    setLoading(true);
    setError(null);
    api
      .listDynamicAttribution(fundCode)
      .then((resp) => {
        const list = resp.data?.results ?? [];
        setResults(list);
        if (list.length > 0) {
          setSelectedResultId(list[0].id);
        } else {
          setSelectedResultId(null);
        }
      })
      .catch((e) => {
        setError(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadResults();
  }, [fundCode]);

  const handleRun = () => {
    if (!fundCode || running) return;
    setRunning(true);
    api
      .runReturnAttribution({ fund_code: fundCode })
      .then(() => {
        loadResults();
      })
      .catch((e) => {
        setError(`运行归因失败: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => setRunning(false));
  };

  const selectedResult = results.find((r) => r.id === selectedResultId) || null;

  const attributionValues = selectedResult
    ? [
        selectedResult.beta_return ?? 0,
        selectedResult.allocation_return ?? 0,
        selectedResult.sector_rotation_return ?? 0,
        selectedResult.stock_selection_return ?? 0,
        selectedResult.residual ?? 0,
      ]
    : [];

  const attributionOption: EChartsOption = {
    title: { text: "收益归因分解" },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: ["Beta收益", "配置收益", "轮动收益", "选股收益", "残差"],
    },
    yAxis: {
      type: "value",
      name: "收益(%)",
      axisLabel: { formatter: (v) => `${(v as number).toFixed(2)}%` },
    },
    series: [
      {
        type: "bar",
        data: attributionValues.map((v) => v * 100),
        itemStyle: { color: "#B45309" },
        barWidth: "50%",
      },
    ],
  };

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: fundCode, to: `/funds/${fundCode}` },
    { label: "动态归因" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* Title area */}
      <div
        className="fade-up fade-up-1"
        style={{
          marginTop: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1>动态收益归因</h1>
            <StatusBadge status="estimated" />
          </div>
          <button
            className="btn btn-primary"
            onClick={handleRun}
            disabled={running}
          >
            {running ? "运行中..." : "运行归因"}
          </button>
        </div>
        <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
          基金代码 <span className="mono">{fundCode}</span>
        </div>
      </div>

      {/* Warning banner */}
      <div
        className="fade-up fade-up-2"
        style={{
          marginBottom: "var(--space-4)",
          padding: "var(--space-3) var(--space-4)",
          background: "var(--warning-soft)",
          borderLeft: "3px solid var(--warning)",
          borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          fontSize: "0.82rem",
          color: "var(--warning)",
        }}
      >
        ⚠ 动态归因基于模拟持仓和风格暴露估算，结果仅供研究参考，不构成投资建议。
      </div>

      {/* Error banner */}
      {error && (
        <div
          className="fade-up fade-up-2"
          style={{
            marginBottom: "var(--space-4)",
            padding: "var(--space-3) var(--space-4)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
            fontSize: "0.82rem",
            color: "var(--negative)",
          }}
        >
          {error}
        </div>
      )}

      {/* Loading / empty / results */}
      {loading ? (
        <div className="fade-up fade-up-3">
          <LoadingState rows={6} cols={5} />
        </div>
      ) : results.length === 0 ? (
        <div className="fade-up fade-up-3">
          <EmptyState
            icon="∅"
            title="该基金暂无动态归因结果"
            desc={'点击"运行归因"按钮生成归因分析'}
          />
        </div>
      ) : (
        <>
          {selectedResult && (
            <div
              className="fade-up fade-up-3"
              style={{ marginBottom: "var(--space-4)" }}
            >
              {/* Metric cards */}
              <div
                className="grid"
                style={{
                  gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                  gap: "var(--space-3)",
                  marginBottom: "var(--space-4)",
                }}
              >
                <PctMetric label="总收益" value={selectedResult.total_return} />
                <PctMetric label="Beta收益" value={selectedResult.beta_return} />
                <PctMetric
                  label="配置收益"
                  value={selectedResult.allocation_return}
                />
                <PctMetric
                  label="轮动收益"
                  value={selectedResult.sector_rotation_return}
                />
                <PctMetric
                  label="选股收益"
                  value={selectedResult.stock_selection_return}
                />
                <PctMetric
                  label="残差占比"
                  value={selectedResult.residual_pct}
                />
              </div>

              {/* Attribution bar chart */}
              <div
                style={{
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border-hairline)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-4)",
                  boxShadow: "var(--shadow-sm)",
                }}
              >
                <ChartWrapper option={attributionOption} height={280} />
              </div>

              {/* Warnings */}
              {selectedResult.warnings &&
                selectedResult.warnings.length > 0 && (
                  <div
                    style={{
                      marginTop: "var(--space-3)",
                      padding: "var(--space-2) var(--space-3)",
                      background: "var(--warning-soft)",
                      borderLeft: "3px solid var(--warning)",
                      borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                      fontSize: "0.78rem",
                      color: "var(--warning)",
                    }}
                  >
                    {selectedResult.warnings.join("; ")}
                  </div>
                )}
            </div>
          )}

          {/* Records list */}
          <div className="fade-up fade-up-4">
            <SectionHeader
              title="归因记录"
              subtitle={`共 ${results.length} 条（点击切换查看）`}
            />
            <div style={{ marginTop: "var(--space-3)" }}>
              {results.map((r) => (
                <ResultListItem
                  key={r.id}
                  result={r}
                  selected={r.id === selectedResultId}
                  onClick={() => setSelectedResultId(r.id)}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
