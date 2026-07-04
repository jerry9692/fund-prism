// 核心展示组件库 — StatusBadge / SectionHeader / MetricCard / EmptyState / LoadingState / ErrorState / TabNav / PeriodTabs / Breadcrumb / Drawer

import { type ReactNode, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { type EvidenceRecord } from "../../api/client";

// ---- StatusBadge ----

const STATUS_LABELS: Record<string, string> = {
  fact: "fact",
  computed: "computed",
  estimated: "estimated",
  observation: "observation",
  needs_review: "needs_review",
  "needs-review": "needs_review",
};

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.replace(/-/g, "_");
  const label = STATUS_LABELS[normalized] ?? normalized;
  return <span className={`status-badge status-badge-${label}`}>{label}</span>;
}

// ---- SectionHeader ----

export function SectionHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        <div className="section-header-title">{title}</div>
        {subtitle && <div className="section-header-subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="section-header-actions">{actions}</div>}
    </div>
  );
}

// ---- MetricCard ----

export function MetricCard({
  label,
  value,
  sub,
  positive,
  negative,
}: {
  label: string;
  value: string | number | null;
  sub?: string;
  positive?: boolean;
  negative?: boolean;
}) {
  const cls = positive ? "positive" : negative ? "negative" : "";
  return (
    <div className="metric-card">
      <div className="metric-card-label">{label}</div>
      <div className={`metric-card-value ${cls}`}>
        {value === null || value === undefined ? "—" : value}
      </div>
      {sub && <div className="metric-card-sub">{sub}</div>}
    </div>
  );
}

// ---- EmptyState ----

export function EmptyState({
  icon = "∅",
  title,
  desc,
  action,
}: {
  icon?: string;
  title: string;
  desc?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      <div className="empty-state-title">{title}</div>
      {desc && <div className="empty-state-desc">{desc}</div>}
      {action}
    </div>
  );
}

// ---- LoadingState (骨架屏) ----

export function LoadingState({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-row">
          {Array.from({ length: cols }).map((_, j) => (
            <div
              key={j}
              className="skeleton skeleton-block"
              style={{ flex: 1, maxWidth: `${100 / cols}%` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// ---- ErrorState ----

export function ErrorState({
  title = "加载失败",
  desc,
  onRetry,
}: {
  title?: string;
  desc?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-state">
      <div className="error-state-title">{title}</div>
      {desc && <div className="error-state-desc">{desc}</div>}
      {onRetry && (
        <button className="btn btn-secondary btn-sm" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

// ---- TabNav ----

export interface TabItem {
  key: string;
  label: string;
  badge?: string;
}

export function TabNav({
  tabs,
  active,
  onChange,
}: {
  tabs: TabItem[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="tab-nav">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          className={`tab-nav-item ${active === tab.key ? "active" : ""}`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
          {tab.badge && <span className="tab-badge">{tab.badge}</span>}
        </button>
      ))}
    </div>
  );
}

// ---- PeriodTabs ----

const PERIODS = [
  { key: "1m", label: "1月" },
  { key: "3m", label: "3月" },
  { key: "6m", label: "6月" },
  { key: "1y", label: "1年" },
  { key: "3y", label: "3年" },
  { key: "all", label: "全部" },
];

export function PeriodTabs({
  active,
  onChange,
}: {
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="period-tabs">
      {PERIODS.map((p) => (
        <button
          key={p.key}
          className={`period-tab ${active === p.key ? "active" : ""}`}
          onClick={() => onChange(p.key)}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

// ---- Breadcrumb ----

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <div className="breadcrumb">
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={i} className="flex items-center gap-2">
            {item.to && !isLast ? (
              <Link
                to={item.to}
                style={{
                  color: "var(--accent)",
                  textDecoration: "none",
                  cursor: "pointer",
                }}
              >
                {item.label}
              </Link>
            ) : (
              <span className="breadcrumb-current">{item.label}</span>
            )}
            {!isLast && <span className="breadcrumb-separator">/</span>}
          </span>
        );
      })}
    </div>
  );
}

// ---- Drawer ----

export function Drawer({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="drawer-overlay overlay-enter" onClick={onClose} />
      <div className="drawer-panel drawer-enter">
        <div className="drawer-header">
          <h3>{title}</h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </>
  );
}

// ---- FilterGroup (可折叠) ----

export function FilterGroup({
  label,
  children,
  defaultCollapsed = false,
}: {
  label: string;
  children: ReactNode;
  defaultCollapsed?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  return (
    <div className={`filter-group ${collapsed ? "collapsed" : ""}`}>
      <div
        className="filter-group-header"
        onClick={() => setCollapsed(!collapsed)}
      >
        {label}
      </div>
      <div className="filter-group-body">{children}</div>
    </div>
  );
}

// ---- ExportButton (通用导出按钮) ----

export interface ExportResult {
  content_base64: string;
  filename: string;
  format: string;
  media_type: string;
}

export function ExportButton({
  data,
  onExport,
  filename,
  label = "导出",
  variant = "secondary",
  size = "sm",
  disabled = false,
}: {
  /** 直接提供数据,序列化为 JSON 导出 */
  data?: unknown;
  /** 异步导出函数,返回 base64 编码内容 (配合 API 导出接口) */
  onExport?: () => Promise<ExportResult>;
  /** 下载文件名 */
  filename: string;
  /** 按钮文字 */
  label?: string;
  /** 按钮样式 */
  variant?: "primary" | "secondary" | "ghost";
  /** 按钮大小 */
  size?: "sm" | "md";
  /** 禁用 */
  disabled?: boolean;
}) {
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    if (exporting || disabled) return;
    setExporting(true);
    try {
      if (onExport) {
        const result = await onExport();
        const binary = atob(result.content_base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: result.media_type });
        triggerDownload(blob, result.filename || filename);
      } else if (data !== undefined) {
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        triggerDownload(blob, filename);
      }
    } catch {
      // 静默失败
    } finally {
      setExporting(false);
    }
  };

  return (
    <button
      className={`btn btn-${variant} ${size === "sm" ? "btn-sm" : ""}`}
      onClick={handleExport}
      disabled={exporting || disabled}
    >
      {exporting ? "导出中…" : label}
    </button>
  );
}

// ---- ConfidenceBadge ----

export function ConfidenceBadge({
  confidence,
  conclusion_status,
}: {
  confidence: string;
  conclusion_status: string;
}) {
  const c = confidence.toLowerCase();
  let bg = "var(--surface-sunken)";
  let color = "var(--ink-secondary)";
  if (c === "high") {
    bg = "var(--positive-soft)";
    color = "var(--positive)";
  } else if (c === "medium") {
    bg = "var(--warning-soft)";
    color = "var(--warning)";
  } else if (c === "low") {
    bg = "var(--negative-soft)";
    color = "var(--negative)";
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--space-1)",
        padding: "2px 8px",
        borderRadius: "var(--radius-sm)",
        background: bg,
        color,
        fontFamily: "var(--font-mono)",
        fontSize: "0.7rem",
        textTransform: "uppercase",
        fontWeight: 600,
        letterSpacing: "0.02em",
      }}
    >
      {conclusion_status || c}
    </span>
  );
}

// ---- EvidenceList ----

export function EvidenceList({ evidence }: { evidence: EvidenceRecord[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (evidence.length === 0) {
    return (
      <EmptyState
        icon="∅"
        title="暂无证据记录"
        desc="该结果未附带证据链"
      />
    );
  }

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {evidence.map((ev) => {
        const isOpen = expanded.has(ev.evidence_id);
        return (
          <div
            key={ev.evidence_id}
            style={{
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
              background: "var(--surface-raised)",
              overflow: "hidden",
            }}
          >
            <button
              onClick={() => toggle(ev.evidence_id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-2)",
                width: "100%",
                padding: "var(--space-2) var(--space-3)",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                fontSize: "0.85rem",
                color: "var(--ink-primary)",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.75rem",
                  transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
                  transition: "transform 0.15s",
                  color: "var(--ink-tertiary)",
                  flexShrink: 0,
                }}
              >
                ▶
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.78rem",
                  color: "var(--ink-secondary)",
                  flexShrink: 0,
                  minWidth: 120,
                }}
              >
                {ev.evidence_type}
              </span>
              <span
                className="mono text-sm"
                style={{ color: "var(--ink-tertiary)", flexShrink: 0 }}
              >
                {ev.source}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.7rem",
                  padding: "1px 6px",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--surface-sunken)",
                  color: "var(--ink-secondary)",
                  flexShrink: 0,
                }}
              >
                {ev.source_level}
              </span>
              <span style={{ marginLeft: "auto", flexShrink: 0 }}>
                <StatusBadge status={ev.conclusion_status} />
              </span>
            </button>
            {isOpen && (
              <div
                style={{
                  padding: "var(--space-3) var(--space-4)",
                  borderTop: "1px solid var(--border-hairline)",
                  background: "var(--surface-sunken)",
                  fontSize: "0.82rem",
                }}
              >
                {ev.data_summary && (
                  <div style={{ marginBottom: "var(--space-2)" }}>
                    <span className="text-tertiary">摘要：</span>
                    <span>{ev.data_summary}</span>
                  </div>
                )}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                    gap: "var(--space-2)",
                  }}
                >
                  {ev.date_range && (
                    <div>
                      <span className="text-tertiary">日期范围：</span>
                      <span className="mono text-sm">
                        {ev.date_range[0]} ~ {ev.date_range[1]}
                      </span>
                    </div>
                  )}
                  <div>
                    <span className="text-tertiary">证据ID：</span>
                    <span className="mono text-sm">{ev.evidence_id}</span>
                  </div>
                  <div>
                    <span className="text-tertiary">置信度：</span>
                    <ConfidenceBadge
                      confidence={ev.confidence}
                      conclusion_status={ev.conclusion_status}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---- Toolbar ----

export function Toolbar({
  left,
  right,
}: {
  left?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "var(--space-3) 0",
        marginBottom: "var(--space-4)",
        borderBottom: "1px solid var(--border-default)",
        gap: "var(--space-3)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexWrap: "wrap" }}>
        {left}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexShrink: 0 }}>
        {right}
      </div>
    </div>
  );
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
