import { useEffect, useState } from "react";

interface Experiment {
  id: number;
  name: string;
  algorithm: string;
  version: string;
  status: string;
  fund_count: number;
  success_count: number;
  failure_count: number;
  created_at: string;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "就绪", running: "运行中", completed: "已完成", failed: "失败",
};

const ALGO_LABELS: Record<string, string> = {
  simulated_holding: "模拟持仓",
  dynamic_attribution: "动态归因",
  scoring: "综合评分",
};

export default function ExperimentsPage() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [algo, setAlgo] = useState("simulated_holding");

  async function load() {
    setLoading(true);
    try {
      const res = await fetch("/api/v2/experiments").then((r) => r.json());
      setExperiments(res.data?.experiments ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function create() {
    await fetch("/api/v2/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ experiment_name: name, algorithm_name: algo, algorithm_version: "0.1.0", parameters: {} }),
    });
    setShowCreate(false);
    setName("");
    load();
  }

  async function remove(id: number) {
    if (!confirm("确认删除该实验？")) return;
    console.log("[delete] sending DELETE for", id);
    try {
      const res = await fetch(`/api/v2/experiments/${id}`, { method: "DELETE" });
      console.log("[delete] response status", res.status);
      const body = await res.json();
      console.log("[delete] response body", body);
      if (!res.ok || !body.data?.deleted) {
        alert(`删除失败: ${body.warnings?.join?.("; ") || res.status}`);
        return;
      }
    } catch (e) {
      console.error("[delete] error", e);
      alert(`删除异常: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    console.log("[delete] calling load()");
    load();
  }

  async function rerun(id: number) {
    await fetch(`/api/v2/experiments/${id}/rerun`, { method: "POST" });
    load();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1>算法实验管理</h1>
        <button onClick={() => setShowCreate(!showCreate)} style={{ padding: "6px 16px", cursor: "pointer" }}>
          + 新建实验
        </button>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 8 }}>新建实验</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
            <label style={{ fontSize: 13 }}>
              名称 <input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 sh-backtest-v1" />
            </label>
            <label style={{ fontSize: 13 }}>
              算法
              <select value={algo} onChange={(e) => setAlgo(e.target.value)}>
                <option value="simulated_holding">模拟持仓</option>
                <option value="dynamic_attribution">动态归因</option>
                <option value="scoring">综合评分</option>
              </select>
            </label>
            <button onClick={create} style={{ padding: "6px 16px", background: "var(--color-primary)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", cursor: "pointer" }}>
              创建
            </button>
          </div>
        </div>
      )}

      {loading ? <p>加载中...</p> : experiments.length === 0 ? (
        <p style={{ color: "var(--color-text-secondary)" }}>暂无实验，点击"新建实验"开始。</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>算法</th>
              <th>状态</th>
              <th>基金数</th>
              <th>成功</th>
              <th>失败</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {experiments.map((e) => (
              <tr key={e.id}>
                <td style={{ fontFamily: "var(--font-mono)" }}>{e.id}</td>
                <td>{e.name}</td>
                <td>{ALGO_LABELS[e.algorithm] ?? e.algorithm} v{e.version}</td>
                <td><span className={`badge badge-${e.status === "completed" ? "computed" : e.status === "failed" ? "needs_review" : "observation"}`}>{STATUS_LABELS[e.status] ?? e.status}</span></td>
                <td>{e.fund_count}</td>
                <td>{e.success_count}</td>
                <td style={{ color: e.failure_count > 0 ? "var(--color-danger)" : undefined }}>{e.failure_count}</td>
                <td style={{ fontSize: 12 }}>{e.created_at?.slice(0, 10)}</td>
                <td>
                  <button onClick={() => rerun(e.id)} style={{ marginRight: 4, cursor: "pointer" }} disabled={e.status === "running"}>重跑</button>
                  <button onClick={() => remove(e.id)} style={{ cursor: "pointer", color: "var(--color-danger)" }}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
