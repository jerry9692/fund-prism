// 异常发现页 — 基金异常规则扫描与历史异常查询
// 支持按规则、严重度过滤；扫描指定基金或查询已记录异常

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { DataTable, type Column } from "../components/data/DataTable";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  StatusBadge,
  LoadingState,
  EmptyState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

// ---- 类型 ----

interface AnomalyRow {
  fund_code: string;
  rule_name: string;
  severity: string;
  description: string | null;
  conclusion_status: string | null;
  created_at: string | null;
  _key: string;
}

// ---- 常量 ----

const RULE_OPTIONS = [
  { value: "style_drift", label: "风格漂移" },
  { value: "classification_deviation", label: "分类偏离" },
  { value: "low_confidence_high_score", label: "低置信高分" },
  { value: "concentration_anomaly", label: "集中度异常" },
  { value: "holder_structure_anomaly", label: "持有人结构异常" },
];

const RULE_LABELS: Record<string, string> = Object.fromEntries(
  RULE_OPTIONS.map((o) => [o.value, o.label])
);

const SEVERITY_OPTIONS = [
  { value: "warning", label: "警告" },
  { value: "needs_review", label: "需复核" },
  { value: "observation", label: "观察" },
];

const SEVERITY_LABELS: Record<string, string> = Object.fromEntries(
  SEVERITY_OPTIONS.map((o) => [o.value, o.label])
);

// ---- 工具函数 ----

function asString(v: unknown): string | null {
  if (typeof v === "string" && v !== "") return v;
  if (v === null || v === undefined) return null;
  return String(v);
}

function parseCodes(input: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of input.split(/[,，\s]+/)) {
    const c = part.trim();
    if (!c) continue;
    if (seen.has(c)) continue;
    seen.add(c);
    out.push(c);
  }
  return out;
}

function toRow(raw: Record<string, unknown>, idx: number): AnomalyRow {
  return {
    _key: `row-${idx}`,
    fund_code:
      asString(raw.fund_code) ??
      asString(raw.code) ??
      asString(raw.fundCode) ??
      "",
    rule_name:
      asString(raw.rule_name) ??
      asString(raw.rule) ??
      asString(raw.rule_type) ??
      "",
    severity:
      asString(raw.severity) ??
      asString(raw.level) ??
      "observation",
    description:
      asString(raw.description) ??
      asString(raw.detail) ??
      asString(raw.message) ??
      asString(raw.reason),
    conclusion_status:
      asString(raw.conclusion_status) ??
      asString(raw.conclusion),
    created_at:
      asString(raw.created_at) ??
      asString(raw.detected_at) ??
      asString(raw.timestamp),
  };
}

function formatDate(v: string | null): string {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString("zh-CN");
}

// ---- SeverityBadge ----

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, { label: string; bg: string; color: string }> = {
    warning: { label: "警告", bg: "var(--warning-soft)", color: "var(--warning)" },
    needs_review: {
      label: "需复核",
      bg: "var(--negative-soft)",
      color: "var(--negative)",
    },
    observation: { label: "观察", bg: "var(--info-soft)", color: "var(--info)" },
  };
  const m = map[severity] ?? {
    label: SEVERITY_LABELS[severity] ?? severity,
    bg: "var(--surface-sunken)",
    color: "var(--ink-secondary)",
  };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "1px 8px",
        borderRadius: "var(--radius-xs)",
        background: m.bg,
        color: m.color,
        fontSize: "0.72rem",
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
        letterSpacing: "0.02em",
      }}
    >
      {m.label}
    </span>
  );
}

// ---- 页面组件 ----

export default function AnomalyListPage() {
  const navigate = useNavigate();
  const [fundCode, setFundCode] = useState("");
  const [ruleName, setRuleName] = useState("");
  const [severity, setSeverity] = useState("");
  const [limit, setLimit] = useState(50);

  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<AnomalyRow[]>([]);
  const [mode, setMode] = useState<"scan" | "list" | null>(null);
  const [rulesRun, setRulesRun] = useState<string[]>([]);
  const [total, setTotal] = useState(0);

  function resetResults() {
    setResults([]);
    setRulesRun([]);
    setTotal(0);
  }

  async function handleScan() {
    const codes = parseCodes(fundCode);
    setLoading(true);
    setError(null);
    setHasSearched(true);
    setMode("scan");
    resetResults();
    try {
      const res = await api.scanAnomalies({
        scope: "all",
        rules: ruleName ? [ruleName] : undefined,
      });
      const data = res.data;
      if (!data) {
        setError(res.warnings.join("; ") || "扫描失败");
        return;
      }
      let allAnomalies = (data.anomalies ?? []).map((raw, idx) => toRow(raw, idx));
      // 如果用户输入了基金代码，客户端筛选
      if (codes.length > 0) {
        const codeSet = new Set(codes);
        allAnomalies = allAnomalies.filter((r) => codeSet.has(r.fund_code));
      }
      setResults(allAnomalies);
      setRulesRun(data.rules_run ?? []);
      setTotal(allAnomalies.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "扫描失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleList() {
    const codes = parseCodes(fundCode);
    const singleCode = codes[0];
    setLoading(true);
    setError(null);
    setHasSearched(true);
    setMode("list");
    resetResults();
    try {
      const res = await api.listAnomalies({
        fund_code: singleCode,
        rule_name: ruleName || undefined,
        severity: severity || undefined,
        limit,
      });
      const data = res.data;
      if (!data) {
        setError(res.warnings.join("; ") || "查询失败");
        return;
      }
      setResults((data.anomalies ?? []).map(toRow));
      setTotal(data.total ?? (data.anomalies ?? []).length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "查询失败");
    } finally {
      setLoading(false);
    }
  }

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "异常发现" },
  ];

  const columns: Column<AnomalyRow>[] = [
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
      key: "rule_name",
      header: "规则",
      sortable: true,
      width: "140px",
      sortValue: (r) => r.rule_name,
      render: (r) =>
        r.rule_name ? (
          <span>{RULE_LABELS[r.rule_name] ?? r.rule_name}</span>
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
    {
      key: "severity",
      header: "严重度",
      sortable: true,
      width: "90px",
      sortValue: (r) => r.severity,
      render: (r) => <SeverityBadge severity={r.severity} />,
    },
    {
      key: "description",
      header: "描述",
      render: (r) =>
        r.description ? (
          <span className="text-sm" style={{ color: "var(--ink-secondary)" }}>
            {r.description}
          </span>
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
    {
      key: "conclusion_status",
      header: "结论状态",
      width: "110px",
      render: (r) =>
        r.conclusion_status ? (
          <StatusBadge status={r.conclusion_status} />
        ) : (
          <span className="text-tertiary">—</span>
        ),
    },
    {
      key: "created_at",
      header: "发现时间",
      sortable: true,
      width: "170px",
      sortValue: (r) => r.created_at ?? "",
      render: (r) => (
        <span className="mono text-sm text-tertiary">{formatDate(r.created_at)}</span>
      ),
    },
  ];

  const subtitle =
    mode === "scan"
      ? `扫描完成 · 命中 ${results.length} 条`
      : mode === "list"
      ? `查询完成 · 共 ${total} 条（显示 ${results.length} 条）`
      : "扫描指定基金的异常，或查询已记录的异常";

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <h1>异常发现</h1>
        <div className="text-sm text-tertiary mt-2">
          基于规则扫描基金异常（风格漂移、集中度异常等），或查询历史已记录异常
        </div>
      </div>

      {/* 筛选条 */}
      <div
        className="fade-up fade-up-2 mb-4"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
        }}
      >
        <SectionHeader
          title="筛选与操作"
          subtitle="扫描：按逗号分隔输入多个基金代码；查询：按单个基金代码检索历史异常"
        />
        <div
          className="grid mt-3"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
            gap: "var(--space-3)",
            alignItems: "end",
          }}
        >
          <label className="form-label" style={{ gridColumn: "span 2" }}>
            <span>基金代码</span>
            <input
              type="text"
              className="form-input"
              value={fundCode}
              onChange={(e) => setFundCode(e.target.value)}
              placeholder="如 000001, 163406（扫描可多选，查询取首个）"
              style={{ fontFamily: "var(--font-mono)" }}
            />
          </label>
          <label className="form-label">
            <span>规则</span>
            <select
              className="form-input"
              value={ruleName}
              onChange={(e) => setRuleName(e.target.value)}
            >
              <option value="">全部规则</option>
              {RULE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="form-label">
            <span>严重度</span>
            <select
              className="form-input"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              <option value="">全部严重度</option>
              {SEVERITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="form-label">
            <span>查询条数</span>
            <input
              type="number"
              className="form-input"
              min={1}
              max={500}
              value={limit}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (!Number.isNaN(n) && n > 0) setLimit(Math.min(500, n));
              }}
            />
          </label>
        </div>
        <div
          style={{
            display: "flex",
            gap: "var(--space-2)",
            marginTop: "var(--space-4)",
            flexWrap: "wrap",
          }}
        >
          <button
            className="btn btn-primary"
            onClick={handleScan}
            disabled={loading}
          >
            {loading && mode === "scan" ? "扫描中…" : "扫描"}
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleList}
            disabled={loading}
          >
            {loading && mode === "list" ? "查询中…" : "查询"}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setFundCode("");
              setRuleName("");
              setSeverity("");
              setLimit(50);
            }}
          >
            重置
          </button>
        </div>
        {parseCodes(fundCode).length > 0 && (
          <div
            className="text-xs text-tertiary"
            style={{ marginTop: "var(--space-2)" }}
          >
            注：扫描将执行全量扫描并筛选指定基金
          </div>
        )}
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

      {/* 汇总指标 */}
      {hasSearched && !error && results.length > 0 && (
        <div className="grid grid-4 fade-up fade-up-3 mb-4">
          <MetricCard label="命中异常" value={results.length} />
          <MetricCard label="总记录数" value={total} />
          <MetricCard
            label="模式"
            value={mode === "scan" ? "扫描" : mode === "list" ? "查询" : "—"}
          />
          <MetricCard
            label="严重度(警告/需复核/观察)"
            value={
              `${results.filter((r) => r.severity === "warning").length} / ` +
              `${results.filter((r) => r.severity === "needs_review").length} / ` +
              `${results.filter((r) => r.severity === "observation").length}`
            }
          />
        </div>
      )}

      {/* 已执行规则（扫描模式） */}
      {hasSearched && mode === "scan" && rulesRun.length > 0 && (
        <div
          className="fade-up fade-up-3 mb-4"
          style={{
            display: "flex",
            gap: "var(--space-2)",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <span className="text-tertiary" style={{ fontSize: "0.75rem" }}>
            已执行规则：
          </span>
          {rulesRun.map((r) => (
            <span
              key={r}
              style={{
                padding: "2px 8px",
                borderRadius: "var(--radius-xs)",
                background: "var(--accent-soft)",
                color: "var(--accent-hover)",
                fontSize: "0.72rem",
                fontFamily: "var(--font-mono)",
              }}
            >
              {RULE_LABELS[r] ?? r}
            </span>
          ))}
        </div>
      )}

      {/* 结果表格 */}
      <div className="fade-up fade-up-3">
        <SectionHeader title="异常记录" subtitle={subtitle} />
        <div style={{ marginTop: "var(--space-3)" }}>
          {error && results.length === 0 ? (
            <ErrorState
              desc={error}
              onRetry={mode === "scan" ? handleScan : handleList}
            />
          ) : loading ? (
            <LoadingState rows={6} cols={6} />
          ) : !hasSearched ? (
            <EmptyState
              icon="∅"
              title="尚未扫描/查询"
              desc="输入基金代码并选择规则与严重度后，点击「扫描」或「查询」"
            />
          ) : results.length === 0 ? (
            <EmptyState
              icon="∅"
              title="未发现异常"
              desc={
                mode === "scan"
                  ? "所选基金在指定规则下未检测到异常"
                  : "当前筛选条件下无历史异常记录"
              }
            />
          ) : (
            <div
              style={{
                background: "var(--surface-raised)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
                overflow: "auto",
              }}
            >
              <DataTable
                columns={columns}
                data={results}
                rowKey={(r) => r._key}
                initialSort={{ key: "created_at", order: "desc" }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
