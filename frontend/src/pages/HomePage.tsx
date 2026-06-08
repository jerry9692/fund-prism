import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export default function HomePage() {
  const [health, setHealth] = useState<string | null>(null);

  useEffect(() => {
    api.health().then((r) => setHealth(r.data?.status ?? "unknown"))
      .catch(() => setHealth("offline"));
  }, []);

  return (
    <div>
      <h1 style={{ marginBottom: 16 }}>Fund Prism</h1>
      <p style={{ color: "var(--color-text-secondary)", marginBottom: 24 }}>
        AI-oriented 开源个人基金研究平台
      </p>

      <div className="card">
        <p>
          后端状态:{" "}
          <span
            className={`badge badge-${health === "ok" ? "computed" : "needs_review"}`}
          >
            {health ?? "检查中..."}
          </span>
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        <QuickLink to="/funds" title="基金检索与筛选" desc="按类型/规模/收益筛选基金" />
        <QuickLink to="/data-quality" title="数据质量" desc="查看数据源状态和覆盖率" />
      </div>
    </div>
  );
}

function QuickLink({ to, title, desc }: { to: string; title: string; desc: string }) {
  return (
    <Link to={to} className="card" style={{ display: "block" }}>
      <h3 style={{ marginBottom: 4 }}>{title}</h3>
      <p style={{ color: "var(--color-text-secondary)", fontSize: 14 }}>{desc}</p>
    </Link>
  );
}
