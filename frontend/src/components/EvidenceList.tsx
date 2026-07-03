interface EvidenceRecord {
  evidence_id?: string;
  evidence_type?: string;
  source?: string;
  source_level?: string;
  data_summary?: string;
  confidence?: string;
  conclusion_status?: string;
}

interface EvidenceListProps {
  evidence?: EvidenceRecord[];
  maxItems?: number;
  compact?: boolean;
}

const SOURCE_LEVEL_COLORS: Record<string, string> = {
  A: "text-success",
  B: "text-accent",
  C: "text-warning",
  LOCAL: "text-muted",
};

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  official_pdf: "官方PDF",
  nav_history: "净值历史",
  disclosed_holdings: "披露持仓",
  market_data: "行情数据",
  akshare_api: "AKShare API",
  web_scrape: "网页爬取",
  local_file: "本地文件",
  computed: "计算结果",
  estimated: "模型估计",
  reviewer_note: "人工标注",
};

export default function EvidenceList({
  evidence = [],
  maxItems = 10,
  compact = false,
}: EvidenceListProps) {
  if (!evidence || evidence.length === 0) {
    return <span className="text-muted" style={{ fontSize: 12 }}>无关联证据</span>;
  }

  const items = evidence.slice(0, maxItems);
  const hidden = evidence.length > maxItems ? evidence.length - maxItems : 0;

  return (
    <div className="evidence-list">
      {items.map((ev, i) => {
        const level = (ev.source_level || "").toUpperCase();
        const levelClass = SOURCE_LEVEL_COLORS[level] || "text-muted";
        const typeLabel = EVIDENCE_TYPE_LABELS[ev.evidence_type || ""] || ev.evidence_type || "证据";

        return (
          <div key={ev.evidence_id || i} className={`evidence-item ${compact ? "compact" : ""}`}>
            <div className="evidence-header">
              <span className="evidence-type">{typeLabel}</span>
              {level && (
                <span className={`evidence-level ${levelClass}`}>
                  {level}级
                </span>
              )}
              {ev.confidence && (
                <span className="evidence-confidence text-muted">{ev.confidence}</span>
              )}
            </div>
            {!compact && ev.data_summary && (
              <p className="evidence-summary">{ev.data_summary}</p>
            )}
            {!compact && ev.conclusion_status && (
              <span className={`badge badge-${ev.conclusion_status}`} style={{ marginTop: 4 }}>
                {ev.conclusion_status}
              </span>
            )}
          </div>
        );
      })}
      {hidden > 0 && (
        <span className="text-muted" style={{ fontSize: 11 }}>
          还有 {hidden} 条证据...
        </span>
      )}
    </div>
  );
}
