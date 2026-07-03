// 持仓分析页 — 新组件库 + 面包屑 + 行业分布图 + 持仓表格

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type HoldingsData, type HoldingItem } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  LoadingState,
  ErrorState,
  EmptyState,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { ChartWrapper } from "../components/data/ChartWrapper";

export default function HoldingsPage() {
  const { code } = useParams<{ code: string }>();
  const [data, setData] = useState<HoldingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    api
      .getHoldings(code)
      .then((r) => setData(r.data ?? null))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [code]);

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: code ?? "", to: `/funds/${code}` },
    { label: "持仓分析" },
  ];

  if (loading) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <LoadingState rows={6} cols={6} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <ErrorState title="持仓数据加载失败" desc={error ?? "无数据"} />
      </div>
    );
  }

  const isTop10 = data.disclosure_granularity === "top10_quarterly";
  const confidenceStatus = isTop10 ? "estimated" : "computed";

  // 行业分布图
  const industryData = data.industry_distribution.filter((d) => d.weight_pct > 0);
  const industryOption = {
    grid: { left: 100, right: 30, top: 10, bottom: 30 },
    xAxis: {
      type: "value" as const,
      axisLabel: { fontSize: 11, formatter: (v: number) => `${v.toFixed(1)}%` },
    },
    yAxis: {
      type: "category" as const,
      data: industryData.map((d) => d.name || "未分类"),
      axisLabel: { fontSize: 11 },
    },
    series: [
      {
        type: "bar" as const,
        data: industryData.map((d) => d.weight_pct),
        itemStyle: { color: "#B45309", borderRadius: [0, 2, 2, 0] },
        barWidth: "60%",
      },
    ],
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: unknown) => {
        const p = (params as Array<{ name: string; value: number }>)[0];
        return `${p.name}: ${p.value.toFixed(2)}%`;
      },
    },
  };

  // 持仓表格列
  const columns: Column<HoldingItem>[] = [
    {
      key: "rank_in_holdings",
      header: "#",
      width: "40px",
      sortable: true,
      render: (row) => <span className="text-tertiary">{row.rank_in_holdings ?? "—"}</span>,
      sortValue: (row) => row.rank_in_holdings ?? 0,
    },
    {
      key: "security_code",
      header: "代码",
      width: "80px",
      render: (row) => <span className="mono font-semibold">{row.security_code}</span>,
    },
    {
      key: "security_name",
      header: "名称",
      render: (row) => <span>{row.security_name}</span>,
    },
    {
      key: "weight_pct",
      header: "权重(%)",
      numeric: true,
      sortable: true,
      render: (row) => (
        <span className={row.weight_pct > 5 ? "text-positive font-semibold" : ""}>
          {row.weight_pct?.toFixed(2)}
        </span>
      ),
      sortValue: (row) => row.weight_pct,
    },
    {
      key: "industry",
      header: "行业",
      render: (row) => (
        <span className="text-sm text-tertiary">{row.industry ?? "—"}</span>
      ),
    },
    {
      key: "change_direction",
      header: "变动",
      width: "70px",
      render: (row) => {
        const dir = row.change_direction;
        if (!dir) return <span className="text-tertiary">—</span>;
        const cls =
          dir === "新增" ? "text-positive" : dir === "退出" ? "text-negative" : "text-tertiary";
        return <span className={cls}>{dir}</span>;
      },
    },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>持仓分析</h1>
          <StatusBadge status={confidenceStatus} />
        </div>
        <div className="text-sm text-tertiary mt-2">
          报告期 <span className="mono">{data.report_date ?? "—"}</span>
          {" · "}
          披露粒度 {data.disclosure_granularity}
          {data.concentration_top10_pct !== null && (
            <>
              {" · "}
              前十大集中度{" "}
              <span className="mono">
                {data.concentration_top10_pct.toFixed(1)}%
              </span>
            </>
          )}
        </div>
      </div>

      {isTop10 && (
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
          ⚠ 季报通常仅披露前十大重仓，不能视为完整组合。以下分析基于部分持仓数据。
        </div>
      )}

      {/* 集中度指标 */}
      <div className="grid grid-4 fade-up fade-up-2 mb-6">
        <div className="metric-card">
          <div className="metric-card-label">持仓数量</div>
          <div className="metric-card-value">{data.holdings.length}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card-label">总权重</div>
          <div className="metric-card-value">
            {data.total_weight_pct !== null
              ? `${data.total_weight_pct.toFixed(1)}%`
              : "—"}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-card-label">前十大集中度</div>
          <div className="metric-card-value">
            {data.concentration_top10_pct !== null
              ? `${data.concentration_top10_pct.toFixed(1)}%`
              : "—"}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-card-label">行业数</div>
          <div className="metric-card-value">{industryData.length}</div>
        </div>
      </div>

      {/* 行业分布图 */}
      {industryData.length > 0 && (
        <div className="fade-up fade-up-3 mb-6">
          <SectionHeader title="行业分布" subtitle="按申万一级行业分类" />
          <ChartWrapper
            option={industryOption}
            height={Math.max(200, industryData.length * 32)}
          />
        </div>
      )}

      {/* 持仓明细表 */}
      <div className="fade-up fade-up-4">
        <SectionHeader title="持仓明细" subtitle={`${data.holdings.length} 只证券`} />
        {data.holdings.length === 0 ? (
          <EmptyState title="暂无持仓数据" desc="该基金本报告期无披露持仓。" />
        ) : (
          <DataTable
            columns={columns}
            data={data.holdings}
            rowKey={(row) => `${row.security_code}-${row.rank_in_holdings}`}
            initialSort={{ key: "weight_pct", order: "desc" }}
          />
        )}
      </div>
    </div>
  );
}
