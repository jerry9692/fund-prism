import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ScreenFilters } from "../api/client";

const CATEGORIES = ["混合型-偏股", "股票型", "混合型-灵活"];
const SORT_OPTIONS = [
  { value: "fund_code", label: "基金代码" },
  { value: "annualized_return_1y", label: "近一年收益" },
  { value: "annualized_return_3y", label: "近三年收益" },
  { value: "max_drawdown_1y", label: "近一年回撤" },
  { value: "sharpe_ratio_1y", label: "近一年夏普" },
  { value: "fund_scale", label: "基金规模" },
  { value: "manager_tenure_days", label: "经理任职天数" },
];

export default function FundListPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState<ScreenFilters>({});
  const [sortBy, setSortBy] = useState("annualized_return_3y");
  const [sortOrder, setSortOrder] = useState("desc");
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  async function search() {
    setLoading(true);
    try {
      const res = await api.screenFunds({
        filters,
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: 50,
      });
      setResults((res.data?.funds as Record<string, unknown>[]) ?? []);
      setTotal(res.data?.total as number ?? 0);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1 style={{ marginBottom: 16 }}>基金检索与筛选</h1>

      <div className="card" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "end" }}>
        <FilterField label="基金类型">
          <select value={filters.category ?? ""} onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}>
            <option value="">全部</option>
            {CATEGORIES.map((c) => (<option key={c} value={c}>{c}</option>))}
          </select>
        </FilterField>
        <FilterField label="最小成立年数">
          <input type="number" min={0} value={filters.min_inception_years ?? ""} onChange={(e) => setFilters({ ...filters, min_inception_years: e.target.value ? Number(e.target.value) : undefined })} />
        </FilterField>
        <FilterField label="最小规模(亿)">
          <input type="number" min={0} step={0.1} value={filters.min_scale_bn ?? ""} onChange={(e) => setFilters({ ...filters, min_scale_bn: e.target.value ? Number(e.target.value) : undefined })} />
        </FilterField>
        <FilterField label="最小经理任职天数">
          <input type="number" min={0} value={filters.min_manager_tenure_days ?? ""} onChange={(e) => setFilters({ ...filters, min_manager_tenure_days: e.target.value ? Number(e.target.value) : undefined })} />
        </FilterField>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "16px 0" }}>
        <label>
          排序:{" "}
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            {SORT_OPTIONS.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
          </select>
        </label>
        <button onClick={() => setSortOrder(sortOrder === "desc" ? "asc" : "desc")} style={{ padding: "4px 12px" }}>
          {sortOrder === "desc" ? "↓ 降序" : "↑ 升序"}
        </button>
        <button onClick={search} disabled={loading} style={{ padding: "8px 20px", background: "var(--color-primary)", color: "#fff", border: "none", borderRadius: "var(--radius-sm)", cursor: "pointer" }}>
          {loading ? "搜索中..." : "搜索"}
        </button>
      </div>

      {total > 0 && <p style={{ color: "var(--color-text-secondary)", fontSize: 14 }}>共 {total} 只基金</p>}

      <table className="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>类型</th>
            <th>规模(亿)</th>
            <th>经理</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {results.map((f, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--font-mono)" }}>{f.fund_code as string}</td>
              <td>{f.short_name as string}</td>
              <td>{f.category as string}</td>
              <td>{f.scale_bn as number}</td>
              <td>{f.manager_name as string}</td>
              <td>
                <button onClick={() => navigate(`/funds/${f.fund_code}`)} style={{ padding: "2px 8px", cursor: "pointer" }}>详情</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
      {label}
      {children}
    </label>
  );
}
