// 核心展示组件库 — StatusBadge / SectionHeader / MetricCard / EmptyState / LoadingState / ErrorState / TabNav / PeriodTabs / Breadcrumb / Drawer

import { type ReactNode, useState, useEffect } from "react";

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
              <a href={item.to}>{item.label}</a>
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
