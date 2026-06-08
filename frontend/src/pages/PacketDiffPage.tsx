import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";

export default function PacketDiffPage() {
  const { code } = useParams<{ code: string }>();
  const [leftDate, setLeftDate] = useState("");
  const [rightDate, setRightDate] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  async function compare() {
    if (!code || !leftDate || !rightDate) return;
    setLoading(true);
    try {
      const r = await api.diffPackets({
        fund_code: code,
        left_snapshot: leftDate,
        right_snapshot: rightDate,
      });
      setResult(r.data as Record<string, unknown> | null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <Link to={`/funds/${code}`} style={{ fontSize: 13 }}>← 返回基金详情</Link>
      <h1 style={{ margin: "8px 0" }}>研究包差异对比</h1>

      <div className="card" style={{ display: "flex", gap: 12, alignItems: "end" }}>
        <label style={{ fontSize: 13 }}>左侧日期: <input type="date" value={leftDate} onChange={(e) => setLeftDate(e.target.value)} /></label>
        <label style={{ fontSize: 13 }}>右侧日期: <input type="date" value={rightDate} onChange={(e) => setRightDate(e.target.value)} /></label>
        <button onClick={compare} disabled={loading} style={{ padding: "6px 16px", background: "var(--color-primary)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", cursor: "pointer" }}>
          {loading ? "对比中..." : "对比"}
        </button>
      </div>

      {result && (
        <div className="card" style={{ marginTop: 12 }}>
          <p>是否有变化: {result.changed ? "是" : "否"}</p>
          <pre style={{ fontSize: 12, overflow: "auto", maxHeight: 500 }}>{JSON.stringify(result.diffs, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
