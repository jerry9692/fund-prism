// 股票反选基金 — 输入一组股票代码，反查持有这些股票的基金
// 支持 disclosed / simulated / weighted 三种方法，可限定基金范围

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  EmptyState,
  LoadingState,
  ErrorState,
  Breadcrumb,
  MetricCard,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";

type Method = "disclosed" | "simulated" | "weighted";
type FundScope = "all" | "pool" | "fund_type";

const METHOD_OPTIONS: { value: Method; label: string }[] = [
  { value: "disclosed", label: "披露持仓 (disclosed)" },
  { value: "simulated", label: "模拟持仓 (simulated)" },
  { value: "weighted", label: "加权 (weighted)" },
];

const SCOPE_OPTIONS: { value: FundScope; label: string }[] = [
  { value: "all", label: "全部基金 (all)" },
  { value: "pool", label: "指定基金池 (pool)" },
  { value: "fund_type", label: "指定基金类型 (fund_type)" },
];

interface ReverseRow {
  fund_code: string;
  total_exposure: number | null;
  source: string;
  confidence: string | null;
  contributions_count: number;
}

// ---- 防御式取值（后端返回 Record<string, unknown>）----
function asString(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}
function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}
function asArrayLen(v: unknown): number {
  return Array.isArray(v) ? v.length : 0;
}

function toRows(results: Array<Record<string, unknown>>): ReverseRow[] {
  return results.map((r) => {
    const source =
      asString(r.source) ||
      asString(r.conclusion_status) ||
      asString(r.data_source) ||
      "observation";
    return {
      fund_code: asString(r.fund_code),
      total_exposure: asNumber(r.total_exposure),
      source,
      confidence: r.confidence == null ? null : asString(r.confidence),
      contributions_count: asArrayLen(r.stock_contributions),
    };
  });
}

// 暴露值可能是小数 (0.12) 或百分数 (12.34)，统一格式化
function formatExposure(v: number | null): string {
  if (v == null) return "—";
  const pct = Math.abs(v) <= 1 ? v * 100 : v;
  return `${pct.toFixed(2)}%`;
}

export default function ReverseLookupPage() {
  const navigate = useNavigate();

  const [stockCodesText, setStockCodesText] = useState("");
  const [method, setMethod] = useState<Method>("weighted");
  const [fundScope, setFundScope] = useState<FundScope>("all");
  const [scopeId, setScopeId] = useState("");
  const [topN, setTopN] = useState(20);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const [results, setResults] = useState<ReverseRow[]>([]);
  const [stockCoverage, setStockCoverage] = useState<Record<string, number>>({});
  const [methodUsed, setMethodUsed] = useState<string>("");
  const [fundCount, setFundCount] = useState<number | null>(null);

  const parsedCodes = stockCodesText
    .split(/[\n,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  async function handleReverse() {
    if (parsedCodes.length === 0) {
      setError("请输入至少一个股票代码");
      setHasSearched(false);
      setResults([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.reverseLookup({
        stock_codes: parsedCodes,
        method,
        fund_scope: fundScope,
        scope_id: fundScope === "all" ? undefined : scopeId.trim() || undefined,
        top_n: topN,
      });
      const d = res.data;
      if (!d) {
        setError(res.warnings.join("；") || "反选失败：后端未返回数据");
        setResults([]);
        setStockCoverage({});
        setHasSearched(true);
        return;
      }
      setResults(toRows(d.results ?? []));
      setStockCoverage(d.stock_coverage ?? {});
      setMethodUsed(d.method ?? method);
      setFundCount(d.fund_count ?? null);
      setHasSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "反选请求失败");
      setResults([]);
      setStockCoverage({});
      setHasSearched(true);
    } finally {
      setLoading(false);
    }
  }

  const columns: Column<ReverseRow>[] = [
    {
      key: "fund_code",
      header: "基金代码",
      width: "140px",
      sortable: true,
      render: (row) => (
        <button
          className="btn btn-ghost btn-sm"
          style={{
            padding: 0,
            color: "var(--accent)",
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
          }}
          onClick={() => navigate(`/funds/${row.fund_code}`)}
        >
          {row.fund_code || "—"}
        </button>
      ),
      sortValue: (row) => row.fund_code,
    },
    {
      key: "total_exposure",
      header: "总暴露",
      width: "120px",
      numeric: true,
      sortable: true,
      render: (row) => (
        <span className="mono">{formatExposure(row.total_exposure)}</span>
      ),
      sortValue: (row) => row.total_exposure ?? -1,
    },
    {
      key: "source",
      header: "数据来源",
      width: "130px",
      render: (row) => <StatusBadge status={row.source} />,
    },
    {
      key: "confidence",
      header: "置信度",
      width: "110px",
      render: (row) =>
        row.confidence ? (
          <span className="mono text-sm">{row.confidence}</span>
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
    {
      key: "contributions_count",
      header: "命中股票数",
      width: "110px",
      numeric: true,
      sortable: true,
      render: (row) => <span className="mono">{row.contributions_count}</span>,
      sortValue: (row) => row.contributions_count,
    },
  ];

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "股票反选基金" },
  ];

  const coverageEntries = Object.entries(stockCoverage).sort(
    (a, b) => b[1] - a[1],
  );
  const coveredCount = coverageEntries.filter(([, c]) => c > 0).length;

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div
        className="fade-up fade-up-1"
        style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}
      >
        <h1>股票反选基金</h1>
        <div
          className="text-sm text-tertiary"
          style={{ marginTop: "var(--space-2)" }}
        >
          输入一组股票代码，反查持有这些股票的基金，支持披露持仓 / 模拟持仓 / 加权三种方法
        </div>
      </div>

      {/* 查询表单 */}
      <div
        className="fade-up fade-up-2"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4) var(--space-5)",
          marginBottom: "var(--space-4)",
        }}
      >
        <SectionHeader
          title="查询条件"
          subtitle="每行一个股票代码，或以逗号 / 空格分隔"
        />
        <div
          className="grid"
          style={{
            gridTemplateColumns: "1fr 1fr",
            gap: "var(--space-4)",
            marginTop: "var(--space-3)",
          }}
        >
          <label className="form-label">
            <span>股票代码</span>
            <textarea
              className="form-textarea"
              value={stockCodesText}
              onChange={(e) => setStockCodesText(e.target.value)}
              placeholder={"如：\n600519\n000858\n300750"}
              rows={5}
              style={{ fontFamily: "var(--font-mono)" }}
            />
            <div
              className="text-xs text-tertiary"
              style={{ marginTop: "var(--space-1)" }}
            >
              已识别 {parsedCodes.length} 个代码
            </div>
          </label>

          <div className="flex flex-col" style={{ gap: "var(--space-3)" }}>
            <label className="form-label">
              <span>反选方法</span>
              <select
                className="form-select"
                value={method}
                onChange={(e) => setMethod(e.target.value as Method)}
              >
                {METHOD_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="form-label">
              <span>基金范围</span>
              <select
                className="form-select"
                value={fundScope}
                onChange={(e) => setFundScope(e.target.value as FundScope)}
              >
                {SCOPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            {fundScope !== "all" && (
              <label className="form-label">
                <span>
                  范围标识{" "}
                  {fundScope === "pool" ? "(池子 ID)" : "(基金类型)"}
                </span>
                <input
                  type="text"
                  className="form-input"
                  value={scopeId}
                  onChange={(e) => setScopeId(e.target.value)}
                  placeholder={fundScope === "pool" ? "如 1" : "如 股票型"}
                />
              </label>
            )}

            <label className="form-label">
              <span>返回前 N 名</span>
              <input
                type="number"
                className="form-input"
                min={1}
                max={500}
                value={topN}
                onChange={(e) =>
                  setTopN(Math.max(1, Number(e.target.value) || 20))
                }
                style={{ width: 120 }}
              />
            </label>
          </div>
        </div>

        <div
          style={{
            marginTop: "var(--space-4)",
            display: "flex",
            gap: "var(--space-2)",
            alignItems: "center",
          }}
        >
          <button
            className="btn btn-primary"
            onClick={handleReverse}
            disabled={loading || parsedCodes.length === 0}
          >
            {loading ? "反选中…" : "反选"}
          </button>
        </div>
      </div>

      {/* 结果区 */}
      {loading ? (
        <div className="fade-up fade-up-3">
          <SectionHeader title="反选结果" />
          <LoadingState rows={4} cols={5} />
        </div>
      ) : error ? (
        <div className="fade-up fade-up-3">
          <SectionHeader title="反选结果" />
          <ErrorState title="反选失败" desc={error} onRetry={handleReverse} />
        </div>
      ) : hasSearched && results.length === 0 ? (
        <div className="fade-up fade-up-3">
          <SectionHeader title="反选结果" />
          <EmptyState
            icon="∅"
            title="未找到匹配基金"
            desc="尝试更换股票代码、调整反选方法或扩大基金范围"
          />
        </div>
      ) : results.length > 0 ? (
        <>
          <div
            className="grid fade-up fade-up-3"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
              gap: "var(--space-3)",
              marginBottom: "var(--space-4)",
            }}
          >
            <MetricCard
              label="命中基金数"
              value={fundCount ?? results.length}
              sub={methodUsed ? `方法：${methodUsed}` : undefined}
            />
            <MetricCard label="查询股票数" value={parsedCodes.length} />
            <MetricCard
              label="覆盖股票数"
              value={coveredCount}
              sub="至少被 1 只基金持有"
            />
          </div>

          <div className="fade-up fade-up-3">
            <SectionHeader
              title="反选结果"
              subtitle={`共 ${results.length} 只基金，按总暴露排序`}
            />
            <div style={{ marginTop: "var(--space-3)" }}>
              <DataTable
                columns={columns}
                data={results}
                rowKey={(row) => row.fund_code}
                initialSort={{ key: "total_exposure", order: "desc" }}
              />
            </div>
          </div>
        </>
      ) : null}

      {/* 股票覆盖 */}
      {hasSearched && coverageEntries.length > 0 && (
        <div
          className="fade-up fade-up-4"
          style={{ marginTop: "var(--space-4)" }}
        >
          <SectionHeader
            title="股票覆盖"
            subtitle="每只股票被多少基金持有"
          />
          <div
            style={{
              marginTop: "var(--space-3)",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: "var(--space-2)",
            }}
          >
            {coverageEntries.map(([code, count]) => (
              <div
                key={code}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "var(--space-2) var(--space-3)",
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border-hairline)",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                <span className="mono text-sm">{code}</span>
                <span
                  className="mono"
                  style={{
                    color: count > 0 ? "var(--accent)" : "var(--ink-tertiary)",
                    fontWeight: 600,
                  }}
                >
                  {count} 只
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
