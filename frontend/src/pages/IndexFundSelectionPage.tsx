// 指数基金优选（P4A，需求书 §6.2.8）
// 同跟踪指数分组 → 规模/费率/流动性/跟踪质量/折溢价五维评分 → 综合优选排序
// 指增产品单列 alpha / IR；被动产品不输出 alpha 结论

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type IndexFundCompareMember,
  type IndexFundSelectionItem,
  type SelectionDimensionEntry,
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

const DIMENSION_LABELS: Record<string, string> = {
  scale: "规模",
  fee: "费率",
  liquidity: "流动性",
  tracking: "跟踪质量",
  premium: "折溢价",
};

const TEMPLATE_LABELS: Record<string, string> = {
  index_passive: "被动指数",
  index_enhanced: "指数增强",
};

const BREADCRUMB: BreadcrumbItem[] = [{ label: "指数基金优选" }];

function fmtPct(v: number | string | null | undefined, digits = 2): string {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function fmtScore(entry: SelectionDimensionEntry | undefined | null): string {
  if (!entry || entry.missing || entry.score == null) return "—";
  return entry.score.toFixed(0);
}

export default function IndexFundSelectionPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [calcDate, setCalcDate] = useState<string | null>(null);
  const [results, setResults] = useState<IndexFundSelectionItem[]>([]);

  // 同指数对比
  const groups = useMemo(() => {
    const map = new Map<string, { name: string | null; size: number }>();
    for (const r of results) {
      if (!r.group_key) continue;
      const cur = map.get(r.group_key);
      map.set(r.group_key, {
        name: r.tracking_index_name ?? cur?.name ?? null,
        size: (cur?.size ?? 0) + 1,
      });
    }
    return Array.from(map.entries());
  }, [results]);

  const [selectedGroup, setSelectedGroup] = useState<string>("");
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareMembers, setCompareMembers] = useState<IndexFundCompareMember[]>([]);
  const [compareName, setCompareName] = useState<string | null>(null);

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getLatestIndexFundSelection();
      if (res.data) {
        setResults(res.data.results);
        setCalcDate(res.data.calc_date);
        setWarnings(res.warnings);
      } else {
        setResults([]);
        setCalcDate(null);
        setWarnings(res.warnings);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      const res = await api.runIndexFundSelection();
      setWarnings(res.warnings);
      if (!res.data) {
        setError(res.warnings.join("；") || "优选计算未返回数据");
      }
      await loadLatest();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    if (!selectedGroup) {
      setCompareMembers([]);
      return;
    }
    let cancelled = false;
    setCompareLoading(true);
    api
      .compareIndexFunds(selectedGroup)
      .then((res) => {
        if (cancelled) return;
        setCompareMembers(res.data?.members ?? []);
        setCompareName(res.data?.index_name ?? null);
      })
      .catch(() => {
        if (!cancelled) setCompareMembers([]);
      })
      .finally(() => {
        if (!cancelled) setCompareLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedGroup]);

  // ---- 优选排序表 ----
  const rankingColumns: Column<IndexFundSelectionItem>[] = [
    {
      key: "fund_code",
      header: "基金代码",
      render: (r) => <span className="mono">{r.fund_code}</span>,
    },
    {
      key: "template",
      header: "类型",
      render: (r) => TEMPLATE_LABELS[r.template_name ?? ""] ?? "—",
    },
    {
      key: "tracking_index",
      header: "跟踪指数",
      render: (r) => r.tracking_index_name ?? r.group_key ?? "未解析",
    },
    ...Object.keys(DIMENSION_LABELS).map((dim) => ({
      key: `dim_${dim}`,
      header: DIMENSION_LABELS[dim],
      numeric: true,
      sortable: true,
      sortValue: (r: IndexFundSelectionItem) =>
        r.dimension_scores?.[dim]?.score ?? null,
      render: (r: IndexFundSelectionItem) => (
        <span
          title={
            r.dimension_scores?.[dim]?.missing
              ? "维度缺失，权重已再分配"
              : undefined
          }
          className={r.dimension_scores?.[dim]?.missing ? "text-tertiary" : ""}
        >
          {fmtScore(r.dimension_scores?.[dim])}
        </span>
      ),
    })),
    {
      key: "composite",
      header: "综合分",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.composite_score,
      render: (r) =>
        r.composite_score != null ? (
          <strong>{r.composite_score.toFixed(1)}</strong>
        ) : (
          "—"
        ),
    },
    {
      key: "group_rank",
      header: "组内排名",
      numeric: true,
      render: (r) =>
        r.rank_in_group != null && r.group_size != null
          ? `${r.rank_in_group}/${r.group_size}`
          : "—",
    },
    {
      key: "alpha",
      header: "年化 Alpha",
      numeric: true,
      sortable: true,
      sortValue: (r) => r.alpha_annualized,
      render: (r) =>
        r.template_name === "index_enhanced"
          ? fmtPct(r.alpha_annualized)
          : "—（被动）",
    },
    {
      key: "status",
      header: "结论状态",
      render: (r) => <StatusBadge status={r.conclusion_status} />,
    },
    {
      key: "warnings",
      header: "告警",
      render: (r) =>
        r.warnings.length > 0 ? (
          <span className="text-tertiary text-xs" title={r.warnings.join("；")}>
            {r.warnings.length} 条
          </span>
        ) : (
          "—"
        ),
    },
  ];

  // ---- 偏离曲线图（时间轴，兼容组内产品历史长度/起始日不同）----
  const deviationOption = useMemo(() => {
    const members = compareMembers.filter((m) => m.deviation_curve.length > 0);
    if (members.length === 0) return null;
    return {
      title: { text: "累计偏离曲线（基金 vs 指数）", left: 0 },
      tooltip: {
        trigger: "axis" as const,
        valueFormatter: (v: unknown) =>
          typeof v === "number" ? `${(v * 100).toFixed(2)}%` : String(v),
      },
      legend: { top: 0, right: 0 },
      grid: { left: 48, right: 16, top: 40, bottom: 28 },
      xAxis: { type: "time" as const },
      yAxis: {
        type: "value" as const,
        axisLabel: {
          formatter: (v: unknown) =>
            typeof v === "number" ? `${(v * 100).toFixed(1)}%` : String(v),
        },
      },
      series: members.map((m) => ({
        name: m.fund_name ?? m.fund_code,
        type: "line" as const,
        showSymbol: false,
        data: m.deviation_curve.map((p) => [p.date, p.cum_deviation]),
      })),
    };
  }, [compareMembers]);

  const compareColumns: Column<IndexFundCompareMember>[] = [
    {
      key: "fund",
      header: "基金",
      render: (m) => (
        <div>
          <div>{m.fund_name ?? m.fund_code}</div>
          <div className="mono text-tertiary text-xs">{m.fund_code}</div>
        </div>
      ),
    },
    {
      key: "sub_category",
      header: "二级分类",
      render: (m) => m.sub_category ?? "—",
    },
    {
      key: "te",
      header: "跟踪误差(1Y)",
      numeric: true,
      sortValue: (m) => m.raw_metrics.tracking_error_1y ?? null,
      sortable: true,
      render: (m) => fmtPct(m.raw_metrics.tracking_error_1y),
    },
    {
      key: "excess",
      header: "年化超额(1Y)",
      numeric: true,
      sortValue: (m) => m.raw_metrics.annualized_excess_1y ?? null,
      sortable: true,
      render: (m) => fmtPct(m.raw_metrics.annualized_excess_1y),
    },
    {
      key: "liquidity",
      header: "日均成交额",
      numeric: true,
      sortValue: (m) => m.dimension_scores?.liquidity?.raw ?? null,
      sortable: true,
      render: (m) => {
        const v = m.dimension_scores?.liquidity?.raw;
        if (v == null) return "—";
        return `${(v / 1e8).toFixed(2)} 亿`;
      },
    },
    {
      key: "fee",
      header: "综合费率",
      numeric: true,
      render: (m) => {
        const v = m.dimension_scores?.fee?.raw;
        return v == null ? "—" : `${v.toFixed(2)}%`;
      },
    },
    {
      key: "premium",
      header: "溢折率(绝对值)",
      numeric: true,
      render: (m) => {
        const v = m.dimension_scores?.premium?.raw;
        return v == null ? "—" : `${v.toFixed(2)}%`;
      },
    },
    {
      key: "alpha",
      header: "Alpha / IR",
      numeric: true,
      render: (m) =>
        m.template_name === "index_enhanced"
          ? `${fmtPct(m.alpha_annualized)} / ${
              m.information_ratio != null ? m.information_ratio.toFixed(2) : "—"
            }`
          : "—（被动）",
    },
    {
      key: "composite",
      header: "综合分",
      numeric: true,
      sortValue: (m) => m.composite_score,
      sortable: true,
      render: (m) =>
        m.composite_score != null ? <strong>{m.composite_score.toFixed(1)}</strong> : "—",
    },
    {
      key: "status",
      header: "状态",
      render: (m) => <StatusBadge status={m.conclusion_status} />,
    },
  ];

  return (
    <div className="page">
      <Breadcrumb items={BREADCRUMB} />
      <SectionHeader
        title="指数基金优选"
        subtitle="同跟踪指数分组，按规模/费率/流动性/跟踪质量/折溢价五维评分排序；指增产品单列 alpha，被动产品不输出 alpha 结论"
        actions={
          <button className="btn btn-primary" onClick={handleRun} disabled={running}>
            {running ? "计算中…" : "运行优选评分"}
          </button>
        }
      />

      {error && <ErrorState title="加载失败" desc={error} />}
      {loading && <LoadingState rows={6} cols={8} />}

      {!loading && !error && results.length === 0 && (
        <EmptyState
          title="暂无优选记录"
          desc="点击右上角「运行优选评分」，对样本内指数类基金（ETF/联接/指增/普通指数）执行五维评分与综合排序"
        />
      )}

      {!loading && !error && results.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-4" style={{ marginBottom: 16 }}>
            <MetricCard label="计算日期" value={calcDate ?? "—"} />
            <MetricCard label="候选产品" value={String(results.length)} />
            <MetricCard label="同指数组数" value={String(groups.length)} />
          </div>

          {warnings.length > 0 && (
            <div className="text-tertiary text-xs" style={{ marginBottom: 12 }}>
              {warnings.join("；")}
            </div>
          )}

          <SectionHeader title="综合优选排序" subtitle="分位数评分 0-100，缺失维度降权不补 0" />
          <DataTable
            columns={rankingColumns}
            data={results}
            rowKey={(r) => r.fund_code}
            onRowClick={(r) => navigate(`/funds/${r.fund_code}`)}
            initialSort={{ key: "composite", order: "desc" }}
          />

          <SectionHeader
            title="同指数对比"
            subtitle="选择跟踪指数，对比同指数产品的跟踪质量、流动性与偏离曲线"
          />
          {groups.length === 0 ? (
            <EmptyState title="无可对比的指数组" desc="没有成功解析跟踪指数的产品" />
          ) : (
            <>
              <div style={{ marginBottom: 12 }}>
                <select
                  className="input"
                  style={{ maxWidth: 360 }}
                  value={selectedGroup}
                  onChange={(e) => setSelectedGroup(e.target.value)}
                >
                  <option value="">选择跟踪指数…</option>
                  {groups.map(([symbol, g]) => (
                    <option key={symbol} value={symbol}>
                      {g.name ?? symbol}（{symbol}，{g.size} 只）
                    </option>
                  ))}
                </select>
              </div>

              {selectedGroup && compareLoading && <LoadingState rows={3} cols={6} />}
              {selectedGroup && !compareLoading && compareMembers.length === 0 && (
                <EmptyState title="该指数下无候选产品" />
              )}
              {selectedGroup && !compareLoading && compareMembers.length > 0 && (
                <>
                  <DataTable
                    columns={compareColumns}
                    data={compareMembers}
                    rowKey={(m) => m.fund_code}
                    onRowClick={(m) => navigate(`/funds/${m.fund_code}`)}
                    initialSort={{ key: "composite", order: "desc" }}
                  />
                  {deviationOption && (
                    <div style={{ marginTop: 16 }}>
                      <ChartWrapper option={deviationOption} height={300} />
                      <div className="text-tertiary text-xs" style={{ marginTop: 6 }}>
                        累计偏离 = 基金累计净值 / 指数累计净值 − 1（近一年窗口）
                        {compareName ? `；基准：${compareName}` : ""}
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
