// 核心展示组件库 — StatusBadge / SectionHeader / MetricCard / EmptyState / LoadingState / ErrorState / TabNav / PeriodTabs / Breadcrumb / Drawer

import { type ReactNode, useState, useEffect } from "react";
import { Link } from "react-router-dom";

// ---- StatusBadge ----

// CSS class key 保留英文以匹配已有样式；displayLabel 为中文展示文本
const STATUS_LABELS: Record<string, { classKey: string; display: string }> = {
  fact: { classKey: "fact", display: "事实" },
  computed: { classKey: "computed", display: "已计算" },
  estimated: { classKey: "estimated", display: "估计" },
  observation: { classKey: "observation", display: "观察" },
  needs_review: { classKey: "needs_review", display: "待复核" },
  "needs-review": { classKey: "needs_review", display: "待复核" },
};

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.replace(/-/g, "_");
  const entry = STATUS_LABELS[normalized];
  const classKey = entry?.classKey ?? normalized;
  const display = entry?.display ?? normalized;
  return <span className={`status-badge status-badge-${classKey}`}>{display}</span>;
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

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---- MarkdownView (lightweight, no external deps) ----
// 支持：#/##/### 标题、-/* 无序列表、1. 有序列表、``` 代码块、`code` 行内代码、
// **bold**、*italic*、|col|col| 表格、[text](url) 链接、--- 分割线、段落。

function renderInline(text: string, keyPrefix = ""): ReactNode[] {
  const nodes: ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const tok = match[0];
    const key = `${keyPrefix}-${i++}`;
    if (tok.startsWith("**")) {
      nodes.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*")) {
      nodes.push(<em key={key}>{tok.slice(1, -1)}</em>);
    } else if (tok.startsWith("`")) {
      nodes.push(
        <code
          key={key}
          style={{
            background: "var(--surface-sunken)",
            padding: "1px 5px",
            borderRadius: "3px",
            fontSize: "0.88em",
            fontFamily: "var(--font-mono)",
          }}
        >
          {tok.slice(1, -1)}
        </code>
      );
    } else if (tok.startsWith("[")) {
      const m = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok);
      if (m) {
        nodes.push(
          <a
            key={key}
            href={m[2]}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--accent)", textDecoration: "underline" }}
          >
            {m[1]}
          </a>
        );
      } else {
        nodes.push(tok);
      }
    } else {
      nodes.push(tok);
    }
    lastIndex = match.index + tok.length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

interface Block {
  type: "heading" | "paragraph" | "ul" | "ol" | "code" | "table" | "hr" | "blank";
  level?: number;
  text?: string;
  items?: string[];
  lang?: string;
  rows?: string[][];
  header?: string[];
}

function parseMarkdown(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // 代码块
    if (/^\s*```/.test(line)) {
      const lang = line.replace(/^\s*```/, "").trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", items: codeLines, lang });
      continue;
    }

    // 分割线
    if (/^\s*---+\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // 标题
    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(line);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2],
      });
      i++;
      continue;
    }

    // 表格（| a | b | 后跟 |---|---|）
    if (/^\s*\|.+\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const header = line.split("|").map((s) => s.trim()).filter((s, idx, arr) => !(idx === 0 && s === "") && !(idx === arr.length - 1 && s === ""));
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.+\|\s*$/.test(lines[i])) {
        const cells = lines[i].split("|").map((s) => s.trim()).filter((s, idx, arr) => !(idx === 0 && s === "") && !(idx === arr.length - 1 && s === ""));
        rows.push(cells);
        i++;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    // 无序列表
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // 有序列表
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // 空行
    if (/^\s*$/.test(line)) {
      i++;
      continue;
    }

    // 段落（合并连续非空行）
    const paraLines: string[] = [line];
    i++;
    while (
      i < lines.length &&
      !/^\s*$/.test(lines[i]) &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*```/.test(lines[i]) &&
      !/^\s*---+\s*$/.test(lines[i]) &&
      !/^\s*\|.+\|\s*$/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({ type: "paragraph", text: paraLines.join(" ") });
  }
  return blocks;
}

export function MarkdownView({ content }: { content: string }) {
  if (!content) return null;
  const blocks = parseMarkdown(content);
  return (
    <div
      className="markdown-body"
      style={{
        fontSize: "0.9rem",
        lineHeight: 1.75,
        color: "var(--ink-primary)",
      }}
    >
      {blocks.map((block, idx) => {
        switch (block.type) {
          case "heading": {
            const level = block.level ?? 1;
            const sizes: Record<number, string> = {
              1: "1.35rem",
              2: "1.15rem",
              3: "1.02rem",
              4: "0.94rem",
            };
            const margins: Record<number, string> = {
              1: "0 0 var(--space-3)",
              2: "var(--space-4) 0 var(--space-2)",
              3: "var(--space-3) 0 var(--space-1)",
              4: "var(--space-2) 0 var(--space-1)",
            };
            const Tag = (`h${level}` as unknown) as keyof React.JSX.IntrinsicElements;
            return (
              <Tag
                key={idx}
                style={{
                  fontSize: sizes[level],
                  fontWeight: 600,
                  margin: margins[level],
                  color: level <= 2 ? "var(--ink-strong)" : "var(--ink-primary)",
                  fontFamily: "var(--font-serif)",
                  borderBottom: level <= 2 ? "1px solid var(--border-hairline)" : "none",
                  paddingBottom: level <= 2 ? "var(--space-1)" : 0,
                }}
              >
                {renderInline(block.text ?? "", `h${idx}`)}
              </Tag>
            );
          }
          case "paragraph":
            return (
              <p key={idx} style={{ margin: "0 0 var(--space-3)" }}>
                {renderInline(block.text ?? "", `p${idx}`)}
              </p>
            );
          case "ul":
            return (
              <ul
                key={idx}
                style={{
                  margin: "0 0 var(--space-3)",
                  paddingLeft: "1.5em",
                  listStyle: "disc",
                }}
              >
                {(block.items ?? []).map((it, j) => (
                  <li key={j} style={{ marginBottom: "2px" }}>
                    {renderInline(it, `ul${idx}-${j}`)}
                  </li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol
                key={idx}
                style={{
                  margin: "0 0 var(--space-3)",
                  paddingLeft: "1.5em",
                  listStyle: "decimal",
                }}
              >
                {(block.items ?? []).map((it, j) => (
                  <li key={j} style={{ marginBottom: "2px" }}>
                    {renderInline(it, `ol${idx}-${j}`)}
                  </li>
                ))}
              </ol>
            );
          case "code":
            return (
              <pre
                key={idx}
                className="mono"
                style={{
                  margin: "0 0 var(--space-3)",
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--surface-sunken)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-hairline)",
                  fontSize: "0.82rem",
                  lineHeight: 1.55,
                  overflow: "auto",
                }}
              >
                {(block.items ?? []).join("\n")}
              </pre>
            );
          case "table":
            return (
              <div
                key={idx}
                style={{
                  overflowX: "auto",
                  margin: "0 0 var(--space-3)",
                }}
              >
                <table
                  style={{
                    borderCollapse: "collapse",
                    width: "100%",
                    fontSize: "0.85rem",
                  }}
                >
                  <thead>
                    <tr style={{ background: "var(--surface-sunken)" }}>
                      {(block.header ?? []).map((h, j) => (
                        <th
                          key={j}
                          style={{
                            padding: "6px 10px",
                            textAlign: "left",
                            fontWeight: 600,
                            border: "1px solid var(--border-hairline)",
                          }}
                        >
                          {renderInline(h, `th${idx}-${j}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(block.rows ?? []).map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, c) => (
                          <td
                            key={c}
                            style={{
                              padding: "5px 10px",
                              border: "1px solid var(--border-hairline)",
                            }}
                          >
                            {renderInline(cell, `td${idx}-${r}-${c}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "hr":
            return (
              <hr
                key={idx}
                style={{
                  border: "none",
                  borderTop: "1px solid var(--border-hairline)",
                  margin: "var(--space-4) 0",
                }}
              />
            );
          default:
            return null;
        }
      })}
    </div>
  );
}
