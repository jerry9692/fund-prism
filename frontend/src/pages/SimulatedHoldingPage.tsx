// 模拟持仓页 — 新组件库 + 面包屑 + 指标卡 + Top15 柱状图 + 可展开持仓表

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type SimulatedHoldingResult } from "../api/client";
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
import { DataTable, type Column } from "../components/data/DataTable";
import type { EChartsOption } from "echarts";

function formatMetricValue(label: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (label === "跟踪误差" || label === "日度 RMSE" || label === "Top10 召回率") {
    return `${(v * 100).toFixed(2)}%`;
  }
  if (label === "输入覆盖率") {
    return `${v.toFixed(1)}%`;
  }
  return v.toFixed(4);
}

interface HoldingRow {
  rank: number;
  stock_code: string;
  stock_name: string | null;
  estimated_weight_pct: number;
  industry: string | null;
}

function ResultCard({
  result,
  index,
}: {
  result: SimulatedHoldingResult;
  index: number;
}) {
  const [expanded, setExpanded] = useState(false);

  const sortedHoldings = [...result.holdings_detail].sort(
    (a, b) => (b.estimated_weight || 0) - (a.estimated_weight || 0)
  );
  const top15 = sortedHoldings.slice(0, 15);
  const chartLabels = top15.map((s) => s.stock_name || s.stock_code);
  const chartValues = top15.map((s) => (s.estimated_weight || 0) * 100);

  const top15Option: EChartsOption = {
    title: { text: "Top 15 重仓股权重" },
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const p = (params as Array<{ name: string; value: number }>)[0];
        return `${p.name}: ${p.value.toFixed(2)}%`;
      },
    },
    xAxis: {
      type: "category",
      data: chartLabels,
      axisLabel: { rotate: 45 },
    },
    yAxis: {
      type: "value",
      name: "权重(%)",
      axisLabel: { formatter: (v: number) => `${v.toFixed(1)}%` },
    },
    series: [
      {
        type: "bar",
        data: chartValues,
        itemStyle: { color: "#B45309" },
        barWidth: "60%",
      },
    ],
  };

  const metricLabels = [
    "跟踪误差",
    "日度 RMSE",
    "行业相关性",
    "Top10 召回率",
    "输入覆盖率",
  ];
  const metricValues: (number | null | undefined)[] = [
    result.tracking_error,
    result.daily_rmse,
    result.industry_correlation,
    result.top10_recall,
    result.input_coverage,
  ];

  const columns: Column<HoldingRow>[] = [
    {
      key: "rank",
      header: "排名",
      width: "60px",
      sortable: true,
      render: (row) => <span className="mono text-tertiary">{row.rank}</span>,
      sortValue: (row) => row.rank,
    },
    {
      key: "stock_code",
      header: "股票代码",
      width: "100px",
      render: (row) => <span className="mono">{row.stock_code}</span>,
    },
    {
      key: "stock_name",
      header: "名称",
      render: (row) => <span>{row.stock_name || "—"}</span>,
    },
    {
      key: "estimated_weight_pct",
      header: "估计权重",
      numeric: true,
      sortable: true,
      render: (row) => (
        <span
          className="mono"
          style={
            row.estimated_weight_pct > 5
              ? { color: "var(--positive)", fontWeight: 600 }
              : undefined
          }
        >
          {row.estimated_weight_pct.toFixed(2)}%
        </span>
      ),
      sortValue: (row) => row.estimated_weight_pct,
    },
    {
      key: "industry",
      header: "行业",
      render: (row) => (
        <span className="text-sm text-tertiary">{row.industry || "—"}</span>
      ),
    },
  ];

  const holdingRows: HoldingRow[] = sortedHoldings.map((h, i) => ({
    rank: i + 1,
    stock_code: h.stock_code,
    stock_name: h.stock_name,
    estimated_weight_pct: (h.estimated_weight || 0) * 100,
    industry: h.industry,
  }));

  // stagger entrance animations across fade-up-1..6
  const animClass = `fade-up fade-up-${Math.min(index + 2, 6)}`;

  return (
    <div
      className={animClass}
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-4)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      {/* Card header */}
      <div
        className="flex items-center justify-between"
        style={{ marginBottom: "var(--space-3)"}}
      >
        <div className="flex items-center gap-3">
          <span
            className="mono"
            style={{ fontWeight: 600, color: "var(--ink-primary)" }}
          >
            {result.calc_date || "未知日期"}
          </span>
          <span className="text-sm text-tertiary">
            {result.algorithm_name} v{result.algorithm_version}
          </span>
          {result.is_backtest && (
            <span
              style={{
                fontSize: "0.72rem",
                fontWeight: 600,
                padding: "1px 6px",
                borderRadius: "var(--radius-xs)",
                background: "var(--warning-soft)",
                color: "var(--warning)",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.02em",
              }}
            >
              回测
            </span>
          )}
        </div>
        <StatusBadge status={result.conclusion_status || "estimated"} />
      </div>

      {/* Metric cards */}
      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        {metricLabels.map((label, i) => (
          <MetricCard
            key={label}
            label={label}
            value={formatMetricValue(label, metricValues[i])}
          />
        ))}
      </div>

      {/* Top 15 bar chart */}
      <ChartWrapper option={top15Option} height={280} />

      {/* Warnings */}
      {result.warnings && result.warnings.length > 0 && (
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
          {result.warnings.join("; ")}
        </div>
      )}

      {/* Expand toggle */}
      <div style={{ marginTop: "var(--space-3)" }}>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded
            ? "收起持仓明细"
            : `查看持仓明细 (${result.holdings_detail?.length || 0} 只)`}
        </button>
      </div>

      {/* Holdings table */}
      {expanded && (
        <div className="expand-enter" style={{ marginTop: "var(--space-3)" }}>
          {holdingRows.length === 0 ? (
            <p className="text-sm text-tertiary">无持仓明细数据</p>
          ) : (
            <DataTable
              columns={columns}
              data={holdingRows}
              rowKey={(row) => `${row.stock_code}-${row.rank}`}
              initialSort={{ key: "estimated_weight_pct", order: "desc" }}
            />
          )}
        </div>
      )}
    </div>
  );
}

export default function SimulatedHoldingPage() {
  const { code } = useParams<{ code: string }>();
  const fundCode = code || "";

  const [results, setResults] = useState<SimulatedHoldingResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fundCode) return;
    setLoading(true);
    setError(null);
    api
      .listSimulatedHolding(fundCode)
      .then((resp) => {
        if (resp.data === null) {
          setError(resp.warnings.join("; ") || "查询失败");
          return;
        }
        setResults(resp.data.results);
      })
      .catch((e) => {
        setError(`加载异常: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => setLoading(false));
  }, [fundCode]);

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: fundCode, to: `/funds/${fundCode}` },
    { label: "模拟持仓" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* Title area */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>模拟持仓</h1>
          <StatusBadge status="estimated" />
        </div>
        <div className="text-sm text-tertiary mt-2">
          基金代码 <span className="mono">{fundCode}</span>
        </div>
      </div>

      {/* Warning banner */}
      <div
        className="fade-up fade-up-2 mb-4"
        style={{
          padding: "var(--space-3) var(--space-4)",
          background: "var(--warning-soft)",
          borderLeft: "3px solid var(--warning)",
          borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          fontSize: "0.82rem",
          color: "var(--warning)",
        }}
      >
        ⚠ 模拟持仓为模型估计结果，不代表基金真实持仓。仅供研究参考。
      </div>

      {/* Error banner */}
      {error && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
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
      ) : results.length === 0 && !error ? (
        <div className="fade-up fade-up-3">
          <EmptyState
            icon="∅"
            title="该基金暂无模拟持仓结果"
            desc="请先通过实验管理页面运行 simulated_holding 实验"
          />
        </div>
      ) : error ? null : (
        <>
          <SectionHeader
            title="模拟持仓记录"
            subtitle={`共 ${results.length} 条（按计算日期倒序）`}
          />
          {results.map((r, i) => (
            <ResultCard key={r.id} result={r} index={i} />
          ))}
        </>
      )}
    </div>
  );
}
