// 相似基金搜索页 — 基于基金指纹的多维度相似基金检索
// 输入基金代码，选择度量空间，检索最相似的基金并展示贡献维度

import { useState, useEffect, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { DataTable, type Column } from "../components/data/DataTable";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

// ---- 类型 ----

interface DimensionContribution {
  name: string;
  value: number | null;
}

interface SimilarFundRow {
  fund_code: string;
  short_name: string | null;
  similarity_score: number | null;
  dimensions: DimensionContribution[];
}

// ---- 常量 ----

const METRIC_SPACE_OPTIONS = [
  { value: "composite", label: "综合" },
  { value: "style", label: "风格" },
  { value: "holding", label: "持仓" },
  { value: "risk_return", label: "风险收益" },
  { value: "factor", label: "因子" },
];

const DIMENSION_LABELS: Record<string, string> = {
  style: "风格",
  holding: "持仓",
  risk_return: "风险收益",
  factor: "因子",
  return: "收益",
  risk: "风险",
  alpha: "Alpha",
  size: "规模",
  momentum: "动量",
  volatility: "波动率",
  growth: "成长",
  value: "价值",
  large_cap: "大盘",
  small_cap: "小盘",
  quality: "质量",
  liquidity: "流动性",
};

// ---- 工具函数 ----

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

function asString(v: unknown): string | null {
  if (typeof v === "string" && v !== "") return v;
  if (v === null || v === undefined) return null;
  return String(v);
}

function labelOf(name: string): string {
  return DIMENSION_LABELS[name] ?? name;
}

function extractDimensions(
  raw: Record<string, unknown>
): DimensionContribution[] {
  const candidates = [
    "top_dimensions",
    "contributing_dimensions",
    "dimension_contributions",
    "top_contributing_dimensions",
    "contributions",
    "top_contribs",
  ];
  for (const key of candidates) {
    const v = raw[key];
    if (Array.isArray(v)) {
      const out: DimensionContribution[] = [];
      for (const item of v) {
        if (typeof item === "string") {
          out.push({ name: item, value: null });
        } else if (item && typeof item === "object") {
          const obj = item as Record<string, unknown>;
          const name =
            asString(obj.dimension) ??
            asString(obj.name) ??
            asString(obj.dim) ??
            asString(obj.label) ??
            asString(obj.key) ??
            "?";
          const value =
            asNumber(obj.contribution) ??
            asNumber(obj.value) ??
            asNumber(obj.score) ??
            asNumber(obj.weight) ??
            null;
          out.push({ name, value });
        }
      }
      if (out.length > 0) return out;
    }
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const out: DimensionContribution[] = [];
      for (const [name, val] of Object.entries(
        v as Record<string, unknown>
      )) {
        if (val === null || val === undefined) continue;
        out.push({ name, value: asNumber(val) });
      }
      if (out.length > 0) return out;
    }
  }
  return [];
}

function toRow(raw: Record<string, unknown>): SimilarFundRow {
  const fundCode =
    asString(raw.fund_code) ??
    asString(raw.code) ??
    asString(raw.fundCode) ??
    "";
  return {
    fund_code: fundCode,
    short_name:
      asString(raw.short_name) ??
      asString(raw.name) ??
      asString(raw.fund_name),
    similarity_score:
      asNumber(raw.similarity_score) ??
      asNumber(raw.score) ??
      asNumber(raw.similarity) ??
      null,
    dimensions: extractDimensions(raw),
  };
}

function formatScore(v: number | null): { text: string; pct: number } {
  if (v === null) return { text: "—", pct: 0 };
  if (v <= 1) {
    return {
      text: `${(v * 100).toFixed(1)}%`,
      pct: Math.max(0, Math.min(100, v * 100)),
    };
  }
  return { text: v.toFixed(2), pct: Math.max(0, Math.min(100, v)) };
}

// ---- 页面组件 ----

export default function SimilarFundsPage() {
  const navigate = useNavigate();
  const params = useParams<{ code: string }>();
  // 当作为 /funds/:code/similar 子路由时，params.code 有值（嵌入模式）
  const embedCode = params.code ?? "";
  const isEmbed = embedCode.length > 0;

  const [fundCode, setFundCode] = useState(embedCode);
  const [metricSpace, setMetricSpace] = useState("composite");
  const [topN, setTopN] = useState(10);
  const [sameTypeOnly, setSameTypeOnly] = useState(false);

  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SimilarFundRow[]>([]);
  const [queryFundCode, setQueryFundCode] = useState("");
  const [queryMetricSpace, setQueryMetricSpace] = useState("");

  const runSearch = useCallback(async (code: string, ms: string, n: number, sameType: boolean) => {
    if (!code) {
      setError("请输入基金代码");
      return;
    }
    setLoading(true);
    setError(null);
    setHasSearched(true);
    try {
      const res = await api.findSimilarFunds(code, {
        metric_space: ms,
        top_n: n,
        same_type_only: sameType,
      });
      const data = res.data;
      if (!data) {
        setError(res.warnings.join("; ") || "搜索失败");
        setResults([]);
        setQueryFundCode(code);
        setQueryMetricSpace(ms);
        return;
      }
      setResults((data.similar_funds ?? []).map(toRow));
      setQueryFundCode(data.fund_code ?? code);
      setQueryMetricSpace(data.metric_space ?? ms);
    } catch (e) {
      setError(e instanceof Error ? e.message : "搜索失败");
      setResults([]);
      setQueryFundCode(code);
      setQueryMetricSpace(ms);
    } finally {
      setLoading(false);
    }
  }, []);

  // 嵌入模式下，跟随 URL 中的基金代码自动搜索
  useEffect(() => {
    if (isEmbed && embedCode) {
      setFundCode(embedCode);
      runSearch(embedCode, metricSpace, topN, sameTypeOnly);
    }
    // 仅在 embedCode 变化时触发，避免 metricSpace 等变化重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embedCode, isEmbed]);

  async function handleSearch() {
    await runSearch(fundCode.trim(), metricSpace, topN, sameTypeOnly);
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSearch();
    }
  };

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "相似基金" },
  ];

  const metricLabel =
    METRIC_SPACE_OPTIONS.find((o) => o.value === queryMetricSpace)?.label ??
    queryMetricSpace;

  const columns: Column<SimilarFundRow>[] = [
    {
      key: "fund_code",
      header: "基金代码",
      sortable: true,
      width: "110px",
      sortValue: (r) => r.fund_code,
      render: (r) =>
        r.fund_code ? (
          <button
            className="mono"
            style={{
              background: "transparent",
              border: "none",
              padding: 0,
              cursor: "pointer",
              color: "var(--accent)",
              fontWeight: 600,
              fontFamily: "var(--font-mono)",
            }}
            onClick={() => navigate(`/funds/${r.fund_code}`)}
          >
            {r.fund_code}
          </button>
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
    {
      key: "short_name",
      header: "基金简称",
      sortable: true,
      sortValue: (r) => r.short_name ?? "",
      render: (r) =>
        r.short_name ? (
          <span>{r.short_name}</span>
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
    {
      key: "similarity_score",
      header: "相似度",
      numeric: true,
      sortable: true,
      width: "180px",
      sortValue: (r) => r.similarity_score ?? -1,
      render: (r) => {
        const { text, pct } = formatScore(r.similarity_score);
        return (
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
            <span
              className="mono"
              style={{ fontWeight: 600, color: "var(--accent)", minWidth: 48 }}
            >
              {text}
            </span>
            <div
              style={{
                flex: 1,
                height: 6,
                background: "var(--surface-sunken)",
                borderRadius: "var(--radius-xs)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: "var(--accent)",
                  borderRadius: "var(--radius-xs)",
                }}
              />
            </div>
          </div>
        );
      },
    },
    {
      key: "dimensions",
      header: "主要贡献维度",
      render: (r) => {
        if (r.dimensions.length === 0) {
          return <span className="text-tertiary">—</span>;
        }
        return (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-1)" }}>
            {r.dimensions.slice(0, 5).map((d, i) => (
              <span
                key={`${d.name}-${i}`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "var(--space-1)",
                  padding: "1px 8px",
                  borderRadius: "var(--radius-xs)",
                  background: "var(--surface-sunken)",
                  color: "var(--ink-secondary)",
                  fontSize: "0.72rem",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {labelOf(d.name)}
                {d.value !== null && (
                  <span style={{ color: "var(--ink-tertiary)" }}>
                    {(d.value <= 1 ? (d.value * 100).toFixed(0) : d.value.toFixed(1))}
                    {d.value <= 1 ? "%" : ""}
                  </span>
                )}
              </span>
            ))}
            {r.dimensions.length > 5 && (
              <span className="text-tertiary" style={{ fontSize: "0.72rem" }}>
                +{r.dimensions.length - 5}
              </span>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div>
      {!isEmbed && <Breadcrumb items={crumbs} />}

      {/* 标题区 — 嵌入模式下由 FundDetailLayout 提供，此处隐藏 */}
      {!isEmbed && (
        <div className="fade-up fade-up-1 mb-4">
          <h1>相似基金搜索</h1>
          <div className="text-sm text-tertiary mt-2">
            基于基金指纹，从多个度量空间检索最相似的基金，并展示主要贡献维度
          </div>
        </div>
      )}

      {/* 搜索表单 */}
      <div
        className="fade-up fade-up-2 mb-4"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
        }}
      >
        <SectionHeader title="搜索条件" subtitle="输入目标基金代码并选择度量空间" />
        <div
          className="grid mt-3"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: "var(--space-3)",
            alignItems: "end",
          }}
        >
          <label className="form-label">
            <span>基金代码 *</span>
            <input
              type="text"
              className="form-input"
              value={fundCode}
              onChange={(e) => setFundCode(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="如 000001"
              disabled={isEmbed}
              style={{ fontFamily: "var(--font-mono)" }}
            />
          </label>
          <label className="form-label">
            <span>度量空间</span>
            <select
              className="form-input"
              value={metricSpace}
              onChange={(e) => setMetricSpace(e.target.value)}
            >
              {METRIC_SPACE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="form-label">
            <span>Top N</span>
            <input
              type="number"
              className="form-input"
              min={1}
              max={100}
              value={topN}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (!Number.isNaN(n) && n > 0) setTopN(Math.min(100, n));
              }}
            />
          </label>
          <label
            className="form-label"
            style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}
          >
            <input
              type="checkbox"
              checked={sameTypeOnly}
              onChange={(e) => setSameTypeOnly(e.target.checked)}
              style={{ width: "auto", height: "auto" }}
            />
            <span style={{ textTransform: "none", letterSpacing: 0, color: "var(--ink-secondary)" }}>
              同类型仅
            </span>
          </label>
          <button
            className="btn btn-primary"
            onClick={handleSearch}
            disabled={loading || !fundCode.trim()}
          >
            {loading ? "搜索中…" : "搜索"}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--negative)" }}>
              {error}
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => setError(null)}>
              关闭
            </button>
          </div>
        </div>
      )}

      {/* 结果汇总 */}
      {hasSearched && !error && results.length > 0 && (
        <div className="grid grid-3 fade-up fade-up-3 mb-4">
          <MetricCard label="目标基金" value={queryFundCode || "—"} />
          <MetricCard label="度量空间" value={metricLabel || "—"} />
          <MetricCard label="相似基金数" value={results.length} />
        </div>
      )}

      {/* 结果表格 */}
      <div className="fade-up fade-up-3">
        <SectionHeader
          title="相似基金结果"
          subtitle={
            hasSearched
              ? loading
                ? "搜索中…"
                : `共 ${results.length} 只相似基金`
              : "请输入基金代码后点击搜索"
          }
        />
        <div style={{ marginTop: "var(--space-3)" }}>
          {error ? (
            <ErrorState desc={error} onRetry={handleSearch} />
          ) : loading ? (
            <LoadingState rows={6} cols={4} />
          ) : !hasSearched ? (
            <EmptyState
              icon="∅"
              title="尚未搜索"
              desc="输入目标基金代码，选择度量空间后点击「搜索」"
            />
          ) : results.length === 0 ? (
            <EmptyState
              icon="∅"
              title="未找到相似基金"
              desc="尝试更换度量空间，或取消「同类型仅」限制后重试"
            />
          ) : (
            <div
              style={{
                background: "var(--surface-raised)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
                overflow: "hidden",
              }}
            >
              <DataTable
                columns={columns}
                data={results}
                rowKey={(r) => r.fund_code || JSON.stringify(r)}
                initialSort={{ key: "similarity_score", order: "desc" }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
