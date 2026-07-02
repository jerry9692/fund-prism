import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function DataQualityPage() {
  const [health, setHealth] = useState<string>("checking");

  useEffect(() => {
    api.health().then((d) => setHealth(d.data?.status || "offline")).catch(() => setHealth("offline"));
  }, []);

  return (
    <div>
      <h1 style={{ marginBottom: 16 }}>数据质量与数据源状态</h1>

      <div className="card">
        <h3 style={{ marginBottom: 8 }}>后端连接</h3>
        <span className={`badge badge-${health === "ok" ? "computed" : "needs_review"}`}>{health}</span>
        {health !== "ok" && (
          <p style={{ color: "var(--color-danger)", marginTop: 8 }}>
            无法连接后端。请确认 API 服务已启动: <code>fund-research serve</code>
          </p>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginBottom: 8 }}>数据源等级说明</h3>
        <table className="data-table">
          <thead><tr><th>等级</th><th>描述</th></tr></thead>
          <tbody>
            <tr><td><span className="badge badge-fact">A</span></td><td>官方披露数据（证监会/交易所/基金公司公告/巨潮 PDF）</td></tr>
            <tr><td><span className="badge badge-computed">B</span></td><td>开源接口聚合数据（AKShare）</td></tr>
            <tr><td><span className="badge badge-estimated">C</span></td><td>网页解析数据（天天基金等公开页面）</td></tr>
            <tr><td><span className="badge badge-observation">LOCAL</span></td><td>用户本地数据（CSV/Parquet 等）</td></tr>
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: 8 }}>数据质量检查</h3>
        <p style={{ color: "var(--color-text-secondary)" }}>
          运行 <code style={{ fontFamily: "var(--font-mono)", background: "var(--color-bg)", padding: "2px 6px" }}>fund-research check-data</code> 获取完整的数据质量报告。
        </p>
      </div>
    </div>
  );
}
