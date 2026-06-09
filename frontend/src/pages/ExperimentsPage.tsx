import { useEffect, useState } from "react";

interface Experiment {
  id: string;
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
  const completedCount = experiments.filter((e) => e.status === "completed").length;
  const failedCount = experiments.filter((e) => e.status === "failed").length;

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
    const experimentName = name.trim() || `${ALGO_LABELS[algo] ?? algo} 实验`;
    await fetch("/api/v2/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        experiment_name: experimentName,
        algorithm_name: algo,
        algorithm_version: "0.1.0",
        parameters: {},
      }),
    });
    setShowCreate(false);
    setName("");
    load();
  }

  async function remove(id: string) {
    if (!confirm("确认删除该实验？")) return;
    try {
      const res = await fetch(`/api/v2/experiments/${id}`, { method: "DELETE" });
      const body = await res.json();
      if (!res.ok || !body.data?.deleted) {
        alert(`删除失败: ${body.warnings?.join?.("; ") || res.status}`);
        return;
      }
    } catch (e) {
      alert(`删除异常: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    load();
  }

  async function rerun(id: string) {
    await fetch(`/api/v2/experiments/${id}/rerun`, { method: "POST" });
    load();
  }

  return (
    <div className="experiments-page">
      <div className="page-header">
        <div>
          <h1>算法实验管理</h1>
          <div className="summary-row">
            <span>{experiments.length} 个实验</span>
            <span>{completedCount} 已完成</span>
            <span className={failedCount > 0 ? "text-danger" : undefined}>{failedCount} 失败</span>
          </div>
        </div>
        <button className="button-primary" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "收起" : "+ 新建实验"}
        </button>
      </div>

      {showCreate && (
        <div className="card experiment-form">
          <div className="form-row">
            <label>
              <span>名称</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 sh-backtest-v1" />
            </label>
            <label>
              <span>算法</span>
              <select value={algo} onChange={(e) => setAlgo(e.target.value)}>
                <option value="simulated_holding">模拟持仓</option>
                <option value="dynamic_attribution">动态归因</option>
                <option value="scoring">综合评分</option>
              </select>
            </label>
            <button className="button-primary" onClick={create}>
              创建
            </button>
          </div>
        </div>
      )}

      {loading ? <p>加载中...</p> : experiments.length === 0 ? (
        <div className="card empty-state">暂无实验</div>
      ) : (
        <div className="card table-card">
          <table className="data-table experiments-table">
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
                  <td className="mono-cell">{e.id}</td>
                  <td className="name-cell">{e.name}</td>
                  <td>{ALGO_LABELS[e.algorithm] ?? e.algorithm} v{e.version}</td>
                  <td>
                    <span className={`badge badge-${e.status === "completed" ? "computed" : e.status === "failed" ? "needs_review" : "observation"}`}>
                      {STATUS_LABELS[e.status] ?? e.status}
                    </span>
                  </td>
                  <td>{e.fund_count}</td>
                  <td>{e.success_count}</td>
                  <td className={e.failure_count > 0 ? "text-danger" : undefined}>{e.failure_count}</td>
                  <td className="date-cell">{e.created_at?.slice(0, 10)}</td>
                  <td>
                    <div className="action-row">
                      <button className="button-ghost" onClick={() => rerun(e.id)} disabled={e.status === "running"}>
                        重跑
                      </button>
                      <button className="button-danger" onClick={() => remove(e.id)}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
