// 研究包差异对比 — 日期选择 + 结构化 diff 展示
// 左右快照对比 + 变更路径树 + JSON 导出

import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, type DiffData } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  ExportButton,
  type BreadcrumbItem,
} from "../components/display";

interface DiffEntry {
  path: string;
  left: unknown;
  right: unknown;
  type: string;
}

// 递归提取 diff 条目
function extractDiffEntries(
  diffs: Record<string, unknown>,
  prefix = "",
): DiffEntry[] {
  const entries: DiffEntry[] = [];
  for (const [key, value] of Object.entries(diffs)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const v = value as Record<string, unknown>;
      // 如果有 left/right 字段，说明是叶子节点
      if ("left" in v && "right" in v) {
        entries.push({
          path,
          left: v.left,
          right: v.right,
          type: (v.type as string) ?? "changed",
        });
      } else {
        entries.push(...extractDiffEntries(v, path));
      }
    } else if (Array.isArray(value)) {
      entries.push({ path, left: value, right: value, type: "array" });
    } else {
      entries.push({ path, left: null, right: value, type: "value" });
    }
  }
  return entries;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (Math.abs(value) < 1 && value !== 0) return value.toFixed(4);
    return value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return `[${value.length} 项]`;
  if (typeof value === "object") return `{${Object.keys(value).length} 字段}`;
  return String(value);
}

const SECTION_LABELS: Record<string, string> = {
  fund_profile: "基金概况",
  nav_metrics: "净值指标",
  disclosed_holdings: "公开持仓",
  exposure: "风格暴露",
  attribution: "收益归因",
  scoring: "综合评分",
  simulated_holding: "模拟持仓",
  review_status: "评审状态",
  data_quality: "数据质量",
  risk_warnings: "风险提示",
};

export default function PacketDiffPage() {
  const { code } = useParams<{ code: string }>();
  const [leftDate, setLeftDate] = useState("");
  const [rightDate, setRightDate] = useState("");
  const [result, setResult] = useState<DiffData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function compare() {
    if (!code || !leftDate || !rightDate) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.diffPackets({
        fund_code: code,
        left_snapshot: leftDate,
        right_snapshot: rightDate,
      });
      if (r.data === null) {
        setError(r.warnings.join("; ") || "对比失败");
        setResult(null);
      } else {
        setResult(r.data as DiffData);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "对比异常");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: code ?? "", to: `/funds/${code}` },
    { label: "差异对比" },
  ];

  // 提取 diff 条目并按 section 分组
  const diffEntries = result ? extractDiffEntries(result.diffs) : [];
  const sections = diffEntries.reduce<Record<string, DiffEntry[]>>(
    (acc, entry) => {
      const section = entry.path.split(".")[0];
      if (!acc[section]) acc[section] = [];
      acc[section].push(entry);
      return acc;
    },
    {},
  );

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <h1>研究包差异对比</h1>
        <div className="text-sm text-tertiary mt-2">
          基金 <span className="mono">{code}</span> · 对比两个快照之间的指标变化
        </div>
      </div>

      {/* 日期选择 */}
      <div
        className="fade-up fade-up-2 mb-6"
        style={{
          background: "var(--surface-raised)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          border: "1px solid var(--border-hairline)",
        }}
      >
        <SectionHeader title="选择对比快照" subtitle="选择两个日期的研究包进行对比" />
        <div
          className="grid mt-3"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: "var(--space-3)",
            alignItems: "end",
          }}
        >
          <label className="form-label">
            <span>左侧快照</span>
            <input
              className="form-input"
              type="date"
              value={leftDate}
              onChange={(e) => setLeftDate(e.target.value)}
            />
          </label>
          <label className="form-label">
            <span>右侧快照</span>
            <input
              className="form-input"
              type="date"
              value={rightDate}
              onChange={(e) => setRightDate(e.target.value)}
            />
          </label>
          <div>
            <button
              className="btn btn-primary"
              onClick={compare}
              disabled={loading || !leftDate || !rightDate}
            >
              {loading ? "对比中..." : "对比"}
            </button>
          </div>
        </div>
      </div>

      {/* 错误 */}
      {error && (
        <div
          className="fade-up fade-up-3 mb-4"
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
        >
          <span className="text-sm" style={{ color: "var(--negative)" }}>
            {error}
          </span>
        </div>
      )}

      {/* 加载中 */}
      {loading && <LoadingState rows={5} cols={4} />}

      {/* 对比结果 */}
      {result && !loading && (
        <>
          {/* 概要 */}
          <div className="grid grid-4 fade-up fade-up-3 mb-6">
            <MetricCard
              label="是否有变化"
              value={result.changed ? "是" : "否"}
              positive={!result.changed}
              negative={result.changed}
            />
            <MetricCard
              label="差异项数"
              value={diffEntries.length}
            />
            <MetricCard
              label="左侧快照"
              value={result.left_info.data_date}
              sub={result.left_info.packet_id}
            />
            <MetricCard
              label="右侧快照"
              value={result.right_info.data_date}
              sub={result.right_info.packet_id}
            />
          </div>

          {/* 无变化 */}
          {!result.changed && (
            <EmptyState
              title="无差异"
              desc="两个快照之间没有检测到变化"
            />
          )}

          {/* 分 section 展示差异 */}
          {result.changed && diffEntries.length > 0 && (
            <div className="fade-up fade-up-4">
              {Object.entries(sections).map(([section, entries], idx) => (
                <div key={section} className={`fade-up fade-up-${Math.min(idx + 3, 6)} mb-6`}>
                  <SectionHeader
                    title={SECTION_LABELS[section] ?? section}
                    subtitle={`${entries.length} 项变化`}
                    actions={<StatusBadge status="estimated" />}
                  />
                  <div
                    className="mt-3"
                    style={{
                      background: "var(--surface-raised)",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--border-hairline)",
                      overflow: "hidden",
                    }}
                  >
                    {entries.map((entry, i) => (
                      <DiffRow key={i} entry={entry} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* JSON 导出 */}
          {result.changed && (
            <div className="fade-up fade-up-6 mb-4">
              <ExportButton
                data={result}
                filename={`diff_${code}_${leftDate}_${rightDate}.json`}
                label="导出 JSON"
              />
            </div>
          )}
        </>
      )}

      {/* 空状态 */}
      {!result && !loading && !error && (
        <EmptyState
          title="选择对比日期"
          desc="选择左右两个快照日期后点击「对比」"
        />
      )}
    </div>
  );
}

// ---- DiffRow ----

function DiffRow({ entry }: { entry: DiffEntry }) {
  const [expanded, setExpanded] = useState(false);
  const isObject: boolean =
    (entry.left != null && typeof entry.left === "object") ||
    (entry.right != null && typeof entry.right === "object");

  return (
    <div
      style={{
        padding: "var(--space-2) var(--space-4)",
        borderBottom: "1px solid var(--border-hairline)",
        cursor: isObject ? "pointer" : "default",
      }}
      onClick={() => isObject && setExpanded(!expanded)}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium mono">{entry.path}</span>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-tertiary">L:</span>
            <span className="mono text-sm" style={{ color: "var(--negative)" }}>
              {formatValue(entry.left)}
            </span>
          </div>
          <span className="text-tertiary">→</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-tertiary">R:</span>
            <span className="mono text-sm" style={{ color: "var(--positive)" }}>
              {formatValue(entry.right)}
            </span>
          </div>
        </div>
      </div>
      {expanded && isObject && (
        <div
          className="mt-2 expand-enter"
          style={{
            padding: "var(--space-2) var(--space-3)",
            background: "var(--surface-sunken)",
            borderRadius: "var(--radius-xs)",
            fontSize: "0.78rem",
          }}
        >
          <pre
            className="mono"
            style={{ margin: 0, overflow: "auto", color: "var(--ink-secondary)" }}
          >
            {JSON.stringify({ left: entry.left, right: entry.right }, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
