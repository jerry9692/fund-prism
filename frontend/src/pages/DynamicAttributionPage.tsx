// 动态收益归因页 — 适配 estimated_* 字段 + 就绪检查 + 归因柱状图 + 可切换归因记录

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

/** Get a field value from DynamicAttributionResult, handling estimated_ prefix.
 *  When uses_simulated_holdings=true, fields have estimated_ prefix; otherwise not. */
function getAttr(
  r: DynamicAttributionResult,
  field: string
): number | null | undefined {
  const est = r.uses_simulated_holdings;
  const key = est ? `estimated_${field}` : field;
  return (r as unknown as Record<string, number | null | undefined>)[key];
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
      : result.calc_date || result.created_at || "未知期间";
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
          {result.algorithm_name && (
            <span className="text-sm text-tertiary">
              {result.algorithm_name}
              {result.algorithm_version ? ` v${result.algorithm_version}` : ""}
            </span>
          )}
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

  // Readiness state
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [readinessReady, setReadinessReady] = useState<number | null>(null);
  const [readinessTotal, setReadinessTotal] = useState<number | null>(null);
  const [readinessChecked, setReadinessChecked] = useState(false);

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

  const checkReadiness = () => {
    if (!fundCode) return;
    setReadinessLoading(true);
    api
      .checkDynamicAttributionReadiness({
        fund_code: [fundCode],
        ready_only: false,
      })
      .then((resp) => {
        setReadinessReady(resp.data?.ready ?? 0);
        setReadinessTotal(resp.data?.total ?? 0);
        setReadinessChecked(true);
      })
      .catch(() => {
        setReadinessChecked(true);
      })
      .finally(() => setReadinessLoading(false));
  };

  useEffect(() => {
    loadResults();
    checkReadiness();
  }, [fundCode]);

  const isReady = readinessReady !== null && readinessReady > 0;

  const handleRun = () => {
    if (!fundCode || running) return;
    // Gate on readiness check
    if (readinessChecked && !isReady) {
      setError(
        `数据就绪检查未通过（${readinessReady ?? 0}/${readinessTotal ?? 0} 个样本就绪）。` +
          "请先确保 NAV 连续性、持仓完整性、基准权重覆盖满足条件后再运行。"
      );
      return;
    }
    setRunning(true);
    setError(null);
    api
      .runReturnAttribution({ fund_code: fundCode })
      .then((resp) => {
        if (!resp.data?.success && resp.warnings.length > 0) {
          setError(`运行归因有警告: ${resp.warnings.join("; ")}`);
        }
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
        getAttr(selectedResult, "total_benchmark_return") ?? 0,
        getAttr(selectedResult, "total_allocation_effect") ?? 0,
        getAttr(selectedResult, "total_selection_effect") ?? 0,
        getAttr(selectedResult, "total_interaction_effect") ?? 0,
        selectedResult.estimated_total_residual ?? 0,
      ]
    : [];

  const attributionOption: EChartsOption = {
    title: { text: "收益归因分解" },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: ["基准收益", "配置效应", "选股效应", "交互效应", "残差"],
    },
    yAxis: {
      type: "value",
      name: "收益(%)",
      axisLabel: { formatter: (v: number) => `${(v as number).toFixed(2)}%` },
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

      {/* Readiness banner */}
      {readinessChecked && (
        <div
          className="fade-up fade-up-2"
          style={{
            marginBottom: "var(--space-4)",
            padding: "var(--space-3) var(--space-4)",
            background: isReady
              ? "var(--positive-soft)"
              : "var(--warning-soft)",
            borderLeft: `3px solid ${isReady ? "var(--positive)" : "var(--warning)"}`,
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
            fontSize: "0.82rem",
            color: isReady ? "var(--positive)" : "var(--warning)",
          }}
        >
          {readinessLoading
            ? "正在检查数据就绪状态..."
            : isReady
              ? `数据就绪检查通过（${readinessReady}/${readinessTotal} 个样本就绪），可以运行归因。`
              : `数据就绪检查未通过（${readinessReady ?? 0}/${readinessTotal ?? 0} 个样本就绪）。运行归因可能产生无效结果。`}
        </div>
      )}

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
        {selectedResult?.uses_simulated_holdings && " 当前结果使用了模拟持仓数据。"}
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
                <PctMetric
                  label="组合总收益"
                  value={getAttr(selectedResult, "total_portfolio_return")}
                />
                <PctMetric
                  label="基准总收益"
                  value={getAttr(selectedResult, "total_benchmark_return")}
                />
                <PctMetric
                  label="配置效应"
                  value={getAttr(selectedResult, "total_allocation_effect")}
                />
                <PctMetric
                  label="选股效应"
                  value={getAttr(selectedResult, "total_selection_effect")}
                />
                <PctMetric
                  label="交互效应"
                  value={getAttr(selectedResult, "total_interaction_effect")}
                />
                <PctMetric
                  label="残差占比"
                  value={selectedResult.estimated_residual_ratio}
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
