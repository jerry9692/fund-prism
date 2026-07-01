/**
 * EvidenceList — expandable evidence chain list.
 * Acceptance criterion §4.3: EvidenceList showing source, date, and confidence
 * for each evidence record, with expandable detail rows.
 */

import { useState } from "react";
import ConfidenceBadge from "./ConfidenceBadge";

export interface EvidenceItem {
  evidence_id: string;
  entity_id?: string;
  evidence_type: string;
  source: string;
  source_level: string;
  date_range: [string, string] | null;
  data_summary: string | null;
  confidence: string;
  conclusion_status: string;
}

export interface EvidenceListProps {
  items: EvidenceItem[];
  emptyMessage?: string;
  defaultExpanded?: boolean;
}

const SOURCE_LEVEL_LABELS: Record<string, string> = {
  A: "A 官方披露",
  LOCAL: "本地文件",
  B: "B 开放API",
  C: "C 网页抓取",
};

export default function EvidenceList({
  items,
  emptyMessage = "暂无证据记录",
  defaultExpanded = false,
}: EvidenceListProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(
    defaultExpanded ? new Set(items.map((i) => i.evidence_id)) : new Set()
  );

  function toggle(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  if (items.length === 0) {
    return <div className="card empty-state">{emptyMessage}</div>;
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--color-border)", fontWeight: 600, fontSize: 14 }}>
        证据链 ({items.length})
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {items.map((item, idx) => {
          const isExpanded = expandedIds.has(item.evidence_id);
          const dateLabel = item.date_range
            ? item.date_range[0] === item.date_range[1]
              ? item.date_range[0]
              : `${item.date_range[0]} ~ ${item.date_range[1]}`
            : "—";
          return (
            <li
              key={item.evidence_id}
              style={{
                borderBottom: idx < items.length - 1 ? "1px solid var(--color-border)" : "none",
              }}
            >
              <div
                onClick={() => toggle(item.evidence_id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 14px",
                  cursor: "pointer",
                  userSelect: "none",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-bg)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "")}
              >
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)", width: 16 }}>
                  {isExpanded ? "▼" : "▶"}
                </span>
                <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "var(--color-text)" }}>
                  {item.evidence_type}
                </span>
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 180 }}>
                  {item.source}
                </span>
                <span style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 160 }}>
                  {dateLabel}
                </span>
                <ConfidenceBadge status={item.conclusion_status} />
              </div>
              {isExpanded && (
                <div
                  style={{
                    padding: "8px 14px 12px 38px",
                    background: "var(--color-bg)",
                    fontSize: 12,
                    color: "var(--color-text-secondary)",
                    display: "grid",
                    gridTemplateColumns: "auto 1fr",
                    gap: "4px 12px",
                  }}
                >
                  <span>证据ID</span>
                  <span style={{ color: "var(--color-text)" }}>{item.evidence_id}</span>
                  {item.entity_id && (
                    <>
                      <span>实体ID</span>
                      <span style={{ color: "var(--color-text)" }}>{item.entity_id}</span>
                    </>
                  )}
                  <span>来源等级</span>
                  <span style={{ color: "var(--color-text)" }}>
                    {SOURCE_LEVEL_LABELS[item.source_level] ?? item.source_level}
                  </span>
                  <span>置信度</span>
                  <span style={{ color: "var(--color-text)" }}>{item.confidence}</span>
                  {item.data_summary && (
                    <>
                      <span>数据摘要</span>
                      <span style={{ color: "var(--color-text)" }}>{item.data_summary}</span>
                    </>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
