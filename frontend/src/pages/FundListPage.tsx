import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ScreenFilters, type FundReviewStatus } from "../api/client";

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

type ReviewStatusMap = Record<string, FundReviewStatus | undefined>;

export default function FundListPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState<ScreenFilters>({});
  const [sortBy, setSortBy] = useState("fund_code");
  const [sortOrder, setSortOrder] = useState("asc");
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [reviewStatuses, setReviewStatuses] = useState<ReviewStatusMap>({});

  async function search() {
    setLoading(true);
    try {
      const res = await api.screenFunds({
        filters,
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: 50,
      });
      const funds = (res.data?.funds as Record<string, unknown>[]) ?? [];
      setResults(funds);
      setTotal(res.data?.total as number ?? 0);

      const codes = funds.map((f) => f.fund_code as string).filter(Boolean);
      const statuses: ReviewStatusMap = {};
      await Promise.allSettled(
        codes.map((code) =>
          api
            .getFundReviewStatus(code)
            .then((r) => {
              if (r.data) statuses[code] = r.data;
            })
            .catch(() => {})
        )
      );
      setReviewStatuses(statuses);
    } finally {
      setLoading(false);
    }
  }

  function getStatusClass(code: string): string {
    const s = reviewStatuses[code];
    if (!s) return "";
    if (s.is_excluded) return "status-excluded";
    if (s.is_locked) return "status-locked";
    if (s.is_approved) return "status-approved";
    return "";
  }

  function renderStatusBadge(code: string) {
    const s = reviewStatuses[code];
    if (!s) return null;
    if (s.is_excluded) return <span className="badge badge-needs_review">已排除</span>;
    if (s.is_locked) return <span className="badge badge-estimated">已锁定</span>;
    if (s.is_approved) return <span className="badge badge-computed">已审批</span>;
    return null;
  }

  const excludedCount = Object.values(reviewStatuses).filter((s) => s?.is_excluded).length;
  const approvedCount = Object.values(reviewStatuses).filter((s) => s?.is_approved).length;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>基金检索与筛选</h1>
          <p className="subtitle">
            {total > 0 && <span>共 {total} 只基金</span>}
            {excludedCount > 0 && <span style={{ marginLeft: 16, color: "var(--color-danger)" }}>{excludedCount} 只已排除</span>}
            {approvedCount > 0 && <span style={{ marginLeft: 16, color: "var(--color-success)" }}>{approvedCount} 只已审批</span>}
          </p>
        </div>
      </div>

      <div className="card">
        <div className="form-row">
          <label>
            <span>基金类型</span>
            <select value={filters.category ?? ""} onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}>
              <option value="">全部</option>
              {CATEGORIES.map((c) => (<option key={c} value={c}>{c}</option>))}
            </select>
          </label>
          <label>
            <span>最小成立年数</span>
            <input type="number" min={0} value={filters.min_inception_years ?? ""} onChange={(e) => setFilters({ ...filters, min_inception_years: e.target.value ? Number(e.target.value) : undefined })} />
          </label>
          <label>
            <span>最小规模(亿)</span>
            <input type="number" min={0} step={0.1} value={filters.min_scale_bn ?? ""} onChange={(e) => setFilters({ ...filters, min_scale_bn: e.target.value ? Number(e.target.value) : undefined })} />
          </label>
          <label>
            <span>最小经理任职天数</span>
            <input type="number" min={0} value={filters.min_manager_tenure_days ?? ""} onChange={(e) => setFilters({ ...filters, min_manager_tenure_days: e.target.value ? Number(e.target.value) : undefined })} />
          </label>
          <label>
            <span>排序</span>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              {SORT_OPTIONS.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
            </select>
          </label>
          <button className="button-primary" onClick={search} disabled={loading}>
            {loading ? "搜索中..." : "搜索"}
          </button>
          <button className="button-ghost" onClick={() => setSortOrder(sortOrder === "desc" ? "asc" : "desc")}>
            {sortOrder === "desc" ? "↓ 降序" : "↑ 升序"}
          </button>
        </div>
      </div>

      {results.length > 0 ? (
        <div className="card table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>类型</th>
                <th>规模(亿)</th>
                <th>经理</th>
                <th>评审状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {results.map((f, i) => {
                const code = f.fund_code as string;
                const statusClass = getStatusClass(code);
                return (
                  <tr key={i} className={`fund-row${statusClass ? " " + statusClass : ""}`}>
                    <td className="mono-cell">{code}</td>
                    <td className="fund-name">{f.short_name as string}</td>
                    <td>{f.category as string}</td>
                    <td className="mono-cell">{f.scale_bn != null ? Number(f.scale_bn).toFixed(2) : "—"}</td>
                    <td>{f.manager_name as string ?? "—"}</td>
                    <td>{renderStatusBadge(code)}</td>
                    <td>
                      <button className="btn btn-sm btn-primary" onClick={() => navigate(`/funds/${f.fund_code}`)}>
                        详情
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : !loading ? (
        <div className="card empty-state">
          <div className="empty-icon">◯</div>
          <p>请设置筛选条件并点击"搜索"开始</p>
        </div>
      ) : null}
    </div>
  );
}
