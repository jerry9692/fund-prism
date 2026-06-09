import { useEffect, useState } from "react";
import { api } from "../api/client";

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
    if (!confirm("Delete experiment?")) return;
    await fetch(`/api/v2/experiments/${id}`, { method: "DELETE" });
    load();
  }

  async function rerun(id: number) {
    await fetch(`/api/v2/experiments/${id}/rerun`, { method: "POST" });
    load();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1>Algorithm Experiments</h1>
        <button onClick={() => setShowCreate(!showCreate)} style={{ padding: "6px 16px", cursor: "pointer" }}>
          + New Experiment
        </button>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 8 }}>New Experiment</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
            <label style={{ fontSize: 13 }}>
              Name: <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. sh-backtest-v1" />
            </label>
            <label style={{ fontSize: 13 }}>
              Algorithm:
              <select value={algo} onChange={(e) => setAlgo(e.target.value)}>
                <option value="simulated_holding">Simulated Holding</option>
                <option value="dynamic_attribution">Dynamic Attribution</option>
                <option value="scoring">Scoring</option>
              </select>
            </label>
            <button onClick={create} style={{ padding: "6px 16px", background: "var(--color-primary)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", cursor: "pointer" }}>
              Create
            </button>
          </div>
        </div>
      )}

      {loading ? <p>Loading...</p> : experiments.length === 0 ? (
        <p style={{ color: "var(--color-text-secondary)" }}>No experiments yet. Create one to get started.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Algorithm</th>
              <th>Status</th>
              <th>Funds</th>
              <th>Success</th>
              <th>Failed</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {experiments.map((e) => (
              <tr key={e.id}>
                <td style={{ fontFamily: "var(--font-mono)" }}>{e.id}</td>
                <td>{e.name}</td>
                <td>{e.algorithm} v{e.version}</td>
                <td><span className={`badge badge-${e.status === "completed" ? "computed" : e.status === "failed" ? "needs_review" : "observation"}`}>{e.status}</span></td>
                <td>{e.fund_count}</td>
                <td>{e.success_count}</td>
                <td style={{ color: e.failure_count > 0 ? "var(--color-danger)" : undefined }}>{e.failure_count}</td>
                <td style={{ fontSize: 12 }}>{e.created_at?.slice(0, 10)}</td>
                <td>
                  <button onClick={() => rerun(e.id)} style={{ marginRight: 4, cursor: "pointer" }} disabled={e.status === "running"}>Rerun</button>
                  <button onClick={() => remove(e.id)} style={{ cursor: "pointer", color: "var(--color-danger)" }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
