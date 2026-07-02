import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type EvidenceRecord } from "../api/client";
import EvidenceList from "../components/EvidenceList";
import ConfidenceBadge from "../components/ConfidenceBadge";

const SECTION_LABELS: Record<string, string> = {
  fund_profile: "基金概况",
  nav_metrics: "净值指标",
  disclosed_holdings: "公开持仓",
  exposure: "风格暴露",
  attribution: "收益归因",
  scoring: "综合评分",
  simulated_holding: "模拟持仓",
  review_status: "评审状态",
};

export default function ResearchPacketPage() {
  const { code } = useParams<{ code: string }>();
  const [packet, setPacket] = useState<Record<string, unknown> | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [conclusionStatus, setConclusionStatus] = useState<string>("computed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setError(null);
    api
      .getResearchPacket(code)
      .then((r) => {
        if (r.data?.packet) setPacket(r.data.packet);
        if (r.warnings) setWarnings(r.warnings);
        if (r.evidence) setEvidence(r.evidence);
        if (r.conclusion_status) setConclusionStatus(r.conclusion_status);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [code]);

  if (loading) return <p className="text-muted">加载研究包中...</p>;
  if (error) return <div className="card empty-state">研究包加载失败: {error}</div>;
  if (!packet) return <div className="card empty-state">研究包加载失败</div>;

  const meta = packet.metadata as Record<string, unknown> | undefined;
  const sections = Object.keys(packet).filter(
    (k) => k !== "metadata" && k !== "warnings" && typeof packet[k] === "object" && packet[k] !== null
  );

  return (
    <div>
      <Link to={`/funds/${code}`} className="text-muted" style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <div className="page-header" style={{ marginTop: 8, marginBottom: 16, paddingBottom: 16 }}>
        <div>
          <h1>研究包</h1>
          <p className="subtitle">
            基金 <span className="mono">{code}</span>
            {meta?.data_date != null && <> · 数据日期 <span className="mono">{String(meta.data_date)}</span></>}
          </p>
        </div>
        <ConfidenceBadge status={conclusionStatus} />
      </div>

      {warnings.length > 0 && (
        <div className="warning-banner" style={{ marginBottom: "var(--space-md)" }}>
          {warnings.map((w, i) => (<p key={i}>⚠ {w}</p>))}
        </div>
      )}

      <div style={{ display: "grid", gap: "var(--space-md)" }}>
        {sections.map((section) => {
          const data = packet[section];
          if (!data) return null;
          return (
            <details key={section} className="card" style={{ cursor: "pointer", padding: 0 }} open={section === "fund_profile"}>
              <summary
                style={{
                  fontWeight: 600,
                  padding: "var(--space-md)",
                  listStyle: "none",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  fontSize: 14,
                }}
              >
                <span>{SECTION_LABELS[section] ?? section}</span>
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", fontWeight: 400 }}>
                  {Object.keys(data as Record<string, unknown>).length} 个字段
                </span>
              </summary>
              <div style={{ padding: "0 var(--space-md) var(--space-md)", borderTop: "1px solid var(--color-border)" }}>
                <pre
                  style={{
                    fontSize: 12,
                    overflow: "auto",
                    maxHeight: 400,
                    padding: "var(--space-sm) 0",
                    fontFamily: "var(--font-mono)",
                    lineHeight: 1.5,
                    color: "var(--color-text-secondary)",
                  }}
                >
                  {JSON.stringify(data, null, 2)}
                </pre>
              </div>
            </details>
          );
        })}
      </div>

      {evidence.length > 0 && (
        <div style={{ marginTop: "var(--space-lg)" }}>
          <h3 style={{ marginBottom: "var(--space-sm)" }}>证据链</h3>
          <EvidenceList items={evidence} defaultExpanded={false} />
        </div>
      )}
    </div>
  );
}
