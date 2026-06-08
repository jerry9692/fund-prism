import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";

export default function ResearchPacketPage() {
  const { code } = useParams<{ code: string }>();
  const [packet, setPacket] = useState<Record<string, unknown> | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    if (!code) return;
    api.getResearchPacket(code).then((r) => {
      if (r.data?.packet) setPacket(r.data.packet);
      if (r.warnings) setWarnings(r.warnings);
    });
  }, [code]);

  if (!packet) return <p>加载中...</p>;

  const meta = packet.metadata as Record<string, unknown> | undefined;

  return (
    <div>
      <Link to={`/funds/${code}`} style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <h1 style={{ margin: "8px 0" }}>研究包</h1>

      {meta && (
        <div className="card" style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
          <p>数据日期: {meta.data_date as string} | 整体置信度: <span className={`badge badge-${meta.overall_confidence}`}>{meta.overall_confidence as string}</span></p>
          {warnings.length > 0 && <p style={{ color: "var(--color-warning)" }}>⚠ {warnings.join("; ")}</p>}
        </div>
      )}

      {/* Sections */}
      {(["fund_profile", "nav_metrics", "disclosed_holdings", "exposure", "attribution"] as const).map((section) => {
        const data = packet[section];
        if (!data) return null;
        return (
          <details key={section} className="card" style={{ cursor: "pointer" }} open={section === "fund_profile"}>
            <summary style={{ fontWeight: 600, marginBottom: 8 }}>{section}</summary>
            <pre style={{ fontSize: 12, overflow: "auto", maxHeight: 300 }}>{JSON.stringify(data, null, 2)}</pre>
          </details>
        );
      })}
    </div>
  );
}
