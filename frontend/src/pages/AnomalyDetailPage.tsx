// 异常详情页 — 展示单条异常记录的完整信息
// 通过 /anomalies/:id 访问，调用 GET /api/v2/anomalies/{id}

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  StatusBadge,
  LoadingState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

// ---- 类型 ----

interface AnomalyDetail {
  id: number;
  fund_code: string;
  rule_name: string;
  severity: string;
  description: string | null;
  detail: Record<string, unknown> | null;
  evidence_ids: string[] | null;
  scope: string | null;
  scope_id: string | null;
  conclusion_status: string | null;
  detected_at: string | null;
}

// ---- 常量 ----

const RULE_LABELS: Record<string, string> = {
  style_drift: "风格漂移",
  classification_deviation: "分类偏离",
  low_confidence_high_score: "低置信高分",
  concentration_anomaly: "集中度异常",
  holder_structure_anomaly: "持有人结构异常",
};

const SCOPE_LABELS: Record<string, string> = {
  all: "全量",
  pool: "基金池",
  fund_type: "基金类型",
  fund: "单基金",
};

// ---- 工具函数 ----

function asString(v: unknown): string | null {
  if (typeof v === "string" && v !== "") return v;
  if (v === null || v === undefined) return null;
  return String(v);
}

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

function asStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v
    .map((x) => asString(x))
    .filter((x): x is string => x !== null);
}

function parseDetail(raw: Record<string, unknown>): AnomalyDetail {
  return {
    id: asNumber(raw.id) ?? 0,
    fund_code: asString(raw.fund_code) ?? asString(raw.code) ?? "",
    rule_name: asString(raw.rule_name) ?? asString(raw.rule) ?? "",
    severity: asString(raw.severity) ?? "observation",
    description:
      asString(raw.description) ?? asString(raw.message) ?? null,
    detail: (raw.detail as Record<string, unknown> | null) ?? null,
    evidence_ids: asStringArray(raw.evidence_ids),
    scope: asString(raw.scope),
    scope_id: asString(raw.scope_id),
    conclusion_status: asString(raw.conclusion_status),
    detected_at: asString(raw.detected_at) ?? asString(raw.created_at),
  };
}

function formatDate(v: string | null): string {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString("zh-CN");
}

// ---- SeverityBadge ---- 复用 AnomalyListPage 的样式

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, { label: string; bg: string; color: string }> = {
    warning: { label: "警告", bg: "var(--warning-soft)", color: "var(--warning)" },
    needs_review: {
      label: "需复核",
      bg: "var(--negative-soft)",
      color: "var(--negative)",
    },
    observation: { label: "观察", bg: "var(--info-soft)", color: "var(--info)" },
    info: { label: "信息", bg: "var(--info-soft)", color: "var(--info)" },
    critical: {
      label: "严重",
      bg: "var(--negative-soft)",
      color: "var(--negative)",
    },
  };
  const m = map[severity] ?? {
    label: severity,
    bg: "var(--surface-sunken)",
    color: "var(--ink-secondary)",
  };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 10px",
        borderRadius: "var(--radius-xs)",
        background: m.bg,
        color: m.color,
        fontSize: "0.75rem",
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
        letterSpacing: "0.02em",
      }}
    >
      {m.label}
    </span>
  );
}

// ---- 详情条目 ----

function DetailField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-1)",
      }}
    >
      <span
        className="text-tertiary"
        style={{ fontSize: "0.72rem", letterSpacing: "0.04em" }}
      >
        {label}
      </span>
      <span className={mono ? "mono" : ""} style={{ fontSize: "0.9rem" }}>
        {value}
      </span>
    </div>
  );
}

// ---- 页面组件 ----

export default function AnomalyDetailPage() {
  const params = useParams<{ id: string }>();
  const navigate = useNavigate();
  const anomalyId = params.id ?? "";

  const [detail, setDetail] = useState<AnomalyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const idNum = Number(anomalyId);
    if (!anomalyId || Number.isNaN(idNum)) {
      setError("无效的异常 ID");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    api
      .getAnomaly(idNum)
      .then((res) => {
        if (res.data) {
          setDetail(parseDetail(res.data));
        } else {
          setError(res.warnings.join("; ") || "未找到该异常记录");
        }
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "加载异常详情失败")
      )
      .finally(() => setLoading(false));
  }, [anomalyId]);

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "异常发现", to: "/anomalies" },
    { label: `#${anomalyId}` },
  ];

  if (loading) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <div style={{ marginTop: "var(--space-4)" }}>
          <LoadingState rows={5} cols={4} />
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <div style={{ marginTop: "var(--space-4)" }}>
          <ErrorState
            title="异常详情加载失败"
            desc={error ?? "未找到该异常记录"}
            onRetry={() => navigate("/anomalies")}
          />
        </div>
      </div>
    );
  }

  const ruleLabel = RULE_LABELS[detail.rule_name] ?? detail.rule_name;
  const scopeLabel = detail.scope
    ? SCOPE_LABELS[detail.scope] ?? detail.scope
    : "—";

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div
        className="fade-up fade-up-1"
        style={{
          marginTop: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <div className="flex items-center gap-3" style={{ flexWrap: "wrap" }}>
          <h1 className="mono">#{detail.id}</h1>
          <SeverityBadge severity={detail.severity} />
          {detail.conclusion_status && (
            <StatusBadge status={detail.conclusion_status} />
          )}
          <span className="text-sm text-tertiary">{ruleLabel}</span>
        </div>
        <div
          className="text-sm text-tertiary"
          style={{ marginTop: "var(--space-2)" }}
        >
          异常记录详情 — 包含触发规则、描述、证据链与关联基金
        </div>
      </div>

      {/* 汇总指标 */}
      <div
        className="grid fade-up fade-up-2"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <MetricCard
          label="关联基金"
          value={detail.fund_code || "—"}
        />
        <MetricCard label="触发规则" value={ruleLabel} />
        <MetricCard
          label="证据数量"
          value={detail.evidence_ids?.length ?? 0}
        />
        <MetricCard label="扫描范围" value={scopeLabel} />
      </div>

      {/* 描述区 */}
      <div
        className="fade-up fade-up-2"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          marginBottom: "var(--space-4)",
        }}
      >
        <SectionHeader title="异常描述" subtitle="由检测规则输出的文本说明" />
        <div
          style={{
            marginTop: "var(--space-3)",
            padding: "var(--space-3) var(--space-4)",
            background: "var(--surface-sunken)",
            borderRadius: "var(--radius-sm)",
            borderLeft: "3px solid var(--accent)",
            fontSize: "0.9rem",
            lineHeight: 1.7,
            color: "var(--ink-primary)",
          }}
        >
          {detail.description || (
            <span className="text-tertiary">— 无描述 —</span>
          )}
        </div>
      </div>

      {/* 元数据 */}
      <div
        className="fade-up fade-up-3"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          marginBottom: "var(--space-4)",
        }}
      >
        <SectionHeader title="元数据" subtitle="异常记录的结构化字段" />
        <div
          className="grid"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: "var(--space-4)",
            marginTop: "var(--space-3)",
          }}
        >
          <DetailField label="异常 ID" value={`#${detail.id}`} mono />
          <DetailField
            label="基金代码"
            value={
              detail.fund_code ? (
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
                  onClick={() => navigate(`/funds/${detail.fund_code}`)}
                >
                  {detail.fund_code}
                </button>
              ) : (
                <span className="text-tertiary">—</span>
              )
            }
          />
          <DetailField
            label="规则名称"
            value={
              <span style={{ fontFamily: "var(--font-mono)" }}>
                {detail.rule_name || "—"}
              </span>
            }
          />
          <DetailField
            label="严重度"
            value={<SeverityBadge severity={detail.severity} />}
          />
          <DetailField
            label="结论状态"
            value={
              detail.conclusion_status ? (
                <StatusBadge status={detail.conclusion_status} />
              ) : (
                <span className="text-tertiary">—</span>
              )
            }
          />
          <DetailField
            label="扫描范围"
            value={scopeLabel}
          />
          <DetailField
            label="范围 ID"
            value={detail.scope_id ?? "—"}
            mono
          />
          <DetailField
            label="发现时间"
            value={formatDate(detail.detected_at)}
            mono
          />
        </div>
      </div>

      {/* 证据链 */}
      <div
        className="fade-up fade-up-3"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          marginBottom: "var(--space-4)",
        }}
      >
        <SectionHeader
          title="证据链"
          subtitle={`共 ${detail.evidence_ids?.length ?? 0} 条证据 ID`}
        />
        <div style={{ marginTop: "var(--space-3)" }}>
          {detail.evidence_ids && detail.evidence_ids.length > 0 ? (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "var(--space-2)",
              }}
            >
              {detail.evidence_ids.map((eid, idx) => (
                <span
                  key={`${eid}-${idx}`}
                  style={{
                    padding: "2px 10px",
                    borderRadius: "var(--radius-xs)",
                    background: "var(--accent-soft)",
                    color: "var(--accent-hover)",
                    fontSize: "0.75rem",
                    fontFamily: "var(--font-mono)",
                    border: "1px solid var(--accent-soft)",
                  }}
                >
                  {eid}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-tertiary text-sm">
              该异常未附带证据 ID
            </span>
          )}
        </div>
      </div>

      {/* 详情 JSON */}
      {detail.detail && Object.keys(detail.detail).length > 0 && (
        <div
          className="fade-up fade-up-3"
          style={{
            background: "var(--surface-raised)",
            border: "1px solid var(--border-hairline)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-4)",
            marginBottom: "var(--space-4)",
          }}
        >
          <SectionHeader
            title="规则输出详情"
            subtitle="检测算法输出的结构化字段（JSON）"
          />
          <pre
            className="mono"
            style={{
              marginTop: "var(--space-3)",
              padding: "var(--space-3) var(--space-4)",
              background: "var(--surface-sunken)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border-hairline)",
              fontSize: "0.78rem",
              lineHeight: 1.6,
              overflow: "auto",
              color: "var(--ink-secondary)",
            }}
          >
            {JSON.stringify(detail.detail, null, 2)}
          </pre>
        </div>
      )}

      {/* 操作区 */}
      <div
        className="fade-up fade-up-3"
        style={{
          display: "flex",
          gap: "var(--space-2)",
          flexWrap: "wrap",
        }}
      >
        <button
          className="btn btn-primary"
          onClick={() =>
            detail.fund_code && navigate(`/funds/${detail.fund_code}`)
          }
          disabled={!detail.fund_code}
        >
          查看关联基金
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => navigate("/anomalies")}
        >
          返回异常列表
        </button>
      </div>
    </div>
  );
}
