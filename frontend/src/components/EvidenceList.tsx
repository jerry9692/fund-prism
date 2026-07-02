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
    <div className="evidence-list">
      <div className="evidence-header">
        <span>证据链</span>
        <span className="text-muted" style={{ fontSize: 12 }}>{items.length} 条记录</span>
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {items.map((item) => {
          const isExpanded = expandedIds.has(item.evidence_id);
          const dateLabel = item.date_range
            ? item.date_range[0] === item.date_range[1]
              ? item.date_range[0]
              : `${item.date_range[0]} ~ ${item.date_range[1]}`
            : "—";
          return (
            <li key={item.evidence_id} className="evidence-item">
              <div className="evidence-row" onClick={() => toggle(item.evidence_id)}>
                <span className={`evidence-caret${isExpanded ? " open" : ""}`}>▶</span>
                <span className="evidence-type">{item.evidence_type}</span>
                <span className="evidence-source">{item.source}</span>
                <span className="evidence-date">{dateLabel}</span>
                <ConfidenceBadge status={item.conclusion_status} />
              </div>
              {isExpanded && (
                <dl className="evidence-detail">
                  <dt>证据ID</dt>
                  <dd>{item.evidence_id}</dd>
                  {item.entity_id && (
                    <>
                      <dt>实体ID</dt>
                      <dd>{item.entity_id}</dd>
                    </>
                  )}
                  <dt>来源等级</dt>
                  <dd>{SOURCE_LEVEL_LABELS[item.source_level] ?? item.source_level}</dd>
                  <dt>置信度</dt>
                  <dd>{item.confidence}</dd>
                  {item.data_summary && (
                    <>
                      <dt>数据摘要</dt>
                      <dd>{item.data_summary}</dd>
                    </>
                  )}
                </dl>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
