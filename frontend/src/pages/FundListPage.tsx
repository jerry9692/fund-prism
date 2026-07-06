// 基金筛选页 — 专业筛选工作台
// 左侧分组筛选面板 + 右侧指标内嵌表格 + 筛选即搜索 + 批量操作 + 保存筛选

import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ScreenFilters, type ScreenResult } from "../api/client";
import { DataTable, type Column } from "../components/data/DataTable";
import {
  SectionHeader,
  FilterGroup,
  EmptyState,
  LoadingState,
  ErrorState,
  ExportButton,
} from "../components/display";

interface FundMetrics {
  annualized_return_1y?: number | null;
  annualized_return_3y?: number | null;
  max_drawdown_1y?: number | null;
  sharpe_ratio_1y?: number | null;
}

interface FundRow {
  fund_code: string;
  short_name: string;
  full_name: string;
  category: string | null;
  sub_category: string | null;
  scale_bn: number | null;
  manager_name: string | null;
  manager: string | null;
  manager_tenure_days: number | null;
  inception_date: string | null;
  mgmt_fee_pct: number | null;
  data_completeness: number | null;
  metrics: FundMetrics | null;
  benchmark: string | null;
  [key: string]: unknown;
}

const PAGE_SIZE = 50;

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function pctColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "var(--ink-tertiary)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

export default function FundListPage() {
  const navigate = useNavigate();
  const [funds, setFunds] = useState<FundRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  // 筛选条件
  const [filters, setFilters] = useState<ScreenFilters>({});
  const [sortBy, setSortBy] = useState<string>("fund_code");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  // 批量选择
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set());

  // 基金池操作
  const [pools, setPools] = useState<{ id: number; name: string; fund_count: number }[]>([]);
  const [targetPoolId, setTargetPoolId] = useState<number | null>(null);
  const [poolMsg, setPoolMsg] = useState<string | null>(null);

  // 保存筛选
  const [showSaveScreen, setShowSaveScreen] = useState(false);
  const [screenName, setScreenName] = useState("");
  const [selectedScreenId, setSelectedScreenId] = useState<number>(0);
  const [savedScreens, setSavedScreens] = useState<{ id: number; name: string; filters: Record<string, unknown>; sort_by: string | null; sort_order: string | null }[]>([]);

  // 防抖
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const doSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res: ScreenResult = await api
        .screenFunds({
          filters,
          sort_by: sortBy,
          sort_order: sortOrder,
          limit: PAGE_SIZE,
          offset: 0,
        })
        .then((r) => r.data as ScreenResult);
      setFunds((res?.funds ?? []) as unknown as FundRow[]);
      setTotal(res?.total ?? 0);
      setHasSearched(true);
      setSelectedCodes(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  }, [filters, sortBy, sortOrder]);

  // 筛选条件变化时自动搜索 (防抖)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      doSearch();
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [filters, sortBy, sortOrder]); // eslint-disable-line react-hooks/exhaustive-deps

  // 加载基金池列表
  const loadPools = useCallback(async () => {
    try {
      const res = await api.listPools();
      setPools(res.data ?? []);
    } catch {
      // 静默失败
    }
  }, []);

  // 加载保存的筛选
  const loadScreens = useCallback(async () => {
    try {
      const res = await api.listScreens();
      setSavedScreens((res.data ?? []).map((s) => ({
        id: s.id,
        name: s.name,
        filters: (s.filters ?? {}) as Record<string, unknown>,
        sort_by: s.sort_by ?? null,
        sort_order: s.sort_order ?? null,
      })));
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    loadPools();
    loadScreens();
  }, [loadPools, loadScreens]);

  const toggleSelect = (code: string) => {
    setSelectedCodes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedCodes.size === funds.length) {
      setSelectedCodes(new Set());
    } else {
      setSelectedCodes(new Set(funds.map((f) => f.fund_code)));
    }
  };

  const handleAddToPool = async () => {
    if (!targetPoolId || selectedCodes.size === 0) return;
    setPoolMsg(null);
    let success = 0;
    let fail = 0;
    for (const code of selectedCodes) {
      try {
        await api.addPoolMember(targetPoolId, { fund_code: code });
        success++;
      } catch {
        fail++;
      }
    }
    setPoolMsg(`成功添加 ${success} 只基金到池中${fail > 0 ? `，${fail} 只失败` : ""}`);
    setSelectedCodes(new Set());
    loadPools();
    setTimeout(() => setPoolMsg(null), 4000);
  };

  const handleSaveScreen = async () => {
    if (!screenName.trim()) return;
    try {
      await api.saveScreen({
        name: screenName.trim(),
        filters: filters as Record<string, unknown>,
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      setShowSaveScreen(false);
      setScreenName("");
      loadScreens();
    } catch {
      // ignore
    }
  };

  const handleLoadScreen = (id: number) => {
    if (!id) return;
    const s = savedScreens.find((x) => x.id === id);
    if (!s) return;
    setFilters(s.filters as ScreenFilters);
    if (s.sort_by) setSortBy(s.sort_by);
    if (s.sort_order) setSortOrder(s.sort_order as "asc" | "desc");
    setSelectedScreenId(id);
  };

  const handleDeleteScreen = async (id: number) => {
    if (!id) return;
    try {
      await api.deleteScreen(id);
      if (selectedScreenId === id) setSelectedScreenId(0);
      loadScreens();
    } catch {
      // ignore
    }
  };

  const columns: Column<FundRow>[] = [
    {
      key: "_select",
      header: "",
      width: "36px",
      render: (row) => (
        <input
          type="checkbox"
          checked={selectedCodes.has(row.fund_code)}
          onChange={(e) => {
            e.stopPropagation();
            toggleSelect(row.fund_code);
          }}
          onClick={(e) => e.stopPropagation()}
          style={{ cursor: "pointer" }}
        />
      ),
    },
    {
      key: "fund_code",
      header: "代码",
      sortable: true,
      width: "80px",
      render: (row) => <span className="mono font-semibold">{row.fund_code}</span>,
      sortValue: (row) => row.fund_code,
    },
    {
      key: "short_name",
      header: "名称",
      sortable: true,
      render: (row) => (
        <span title={row.full_name}>{row.short_name}</span>
      ),
      sortValue: (row) => row.short_name,
    },
    {
      key: "category",
      header: "类型",
      width: "90px",
      render: (row) => (
        <span className="text-tertiary text-sm">{row.category ?? "—"}</span>
      ),
    },
    {
      key: "scale_bn",
      header: "规模(亿)",
      numeric: true,
      sortable: true,
      render: (row) =>
        row.scale_bn !== null ? (
          <span>{row.scale_bn.toFixed(2)}</span>
        ) : (
          "—"
        ),
      sortValue: (row) => row.scale_bn ?? 0,
    },
    {
      key: "metrics.annualized_return_1y",
      header: "近1年",
      numeric: true,
      sortable: true,
      render: (row) => {
        const v = row.metrics?.annualized_return_1y;
        return (
          <span className="mono text-sm" style={{ color: pctColor(v) }}>
            {fmtPct(v)}
          </span>
        );
      },
      sortValue: (row) => row.metrics?.annualized_return_1y ?? -999,
    },
    {
      key: "metrics.annualized_return_3y",
      header: "近3年",
      numeric: true,
      sortable: true,
      render: (row) => {
        const v = row.metrics?.annualized_return_3y;
        return (
          <span className="mono text-sm" style={{ color: pctColor(v) }}>
            {fmtPct(v)}
          </span>
        );
      },
      sortValue: (row) => row.metrics?.annualized_return_3y ?? -999,
    },
    {
      key: "metrics.max_drawdown_1y",
      header: "最大回撤",
      numeric: true,
      sortable: true,
      render: (row) => {
        const v = row.metrics?.max_drawdown_1y;
        return (
          <span className="mono text-sm" style={{ color: pctColor(v) }}>
            {fmtPct(v)}
          </span>
        );
      },
      sortValue: (row) => row.metrics?.max_drawdown_1y ?? 999,
    },
    {
      key: "metrics.sharpe_ratio_1y",
      header: "夏普",
      numeric: true,
      sortable: true,
      render: (row) => {
        const v = row.metrics?.sharpe_ratio_1y;
        if (v === null || v === undefined) return <span className="text-tertiary">—</span>;
        return (
          <span
            className="mono text-sm"
            style={{ color: v >= 1 ? "var(--positive)" : v >= 0 ? "var(--ink-secondary)" : "var(--negative)" }}
          >
            {v.toFixed(2)}
          </span>
        );
      },
      sortValue: (row) => row.metrics?.sharpe_ratio_1y ?? -999,
    },
    {
      key: "manager_name",
      header: "经理",
      render: (row) => (
        <span className="text-sm">{row.manager_name ?? "—"}</span>
      ),
    },
    {
      key: "manager_tenure_days",
      header: "任职天",
      numeric: true,
      sortable: true,
      width: "70px",
      render: (row) =>
        row.manager_tenure_days ? (
          <span>{row.manager_tenure_days}</span>
        ) : (
          "—"
        ),
      sortValue: (row) => row.manager_tenure_days ?? 0,
    },
    {
      key: "data_completeness",
      header: "完整度",
      numeric: true,
      sortable: true,
      width: "60px",
      render: (row) => {
        const v = row.data_completeness;
        if (v === null || v === undefined) return "—";
        const pct = Math.round(v * 100);
        const color = pct >= 80 ? "var(--positive)" : pct >= 50 ? "var(--warning)" : "var(--negative)";
        return <span className="mono text-sm" style={{ color }}>{pct}%</span>;
      },
      sortValue: (row) => row.data_completeness ?? 0,
    },
  ];

  const handleRowClick = (row: FundRow) => {
    try {
      const raw = localStorage.getItem("recent_funds");
      const recents = raw ? JSON.parse(raw) : [];
      const filtered = recents.filter(
        (r: { code: string }) => r.code !== row.fund_code
      );
      filtered.unshift({
        code: row.fund_code,
        name: row.short_name,
        ts: Date.now(),
      });
      localStorage.setItem(
        "recent_funds",
        JSON.stringify(filtered.slice(0, 10))
      );
    } catch {
      // ignore
    }
    navigate(`/funds/${row.fund_code}`);
  };

  const updateFilter = (key: keyof ScreenFilters, value: string) => {
    setFilters((prev) => {
      const next = { ...prev };
      if (value === "") {
        delete next[key];
      } else {
        if (
          key === "min_inception_years" ||
          key === "min_scale_bn" ||
          key === "max_scale_bn" ||
          key === "min_manager_tenure_days"
        ) {
          next[key] = Number(value) as never;
        } else if (key === "max_mgmt_fee_pct") {
          next[key] = Number(value) as never;
        } else {
          next[key] = value as never;
        }
      }
      return next;
    });
  };

  return (
    <div>
      <div className="fade-up fade-up-1 mb-4">
        <Breadcrumb />
        <div className="flex items-center justify-between">
          <h1>基金筛选</h1>
          <div className="flex gap-2">
            <ExportButton
              label="导出 CSV"
              filename="screen_results.csv"
              onExport={async () => {
                const res = await api.exportScreenResults({
                  filters: filters as Record<string, unknown>,
                  sort_by: sortBy,
                  sort_order: sortOrder,
                  limit: 500,
                  format: "csv",
                });
                return res.data!;
              }}
              disabled={funds.length === 0}
            />
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setShowSaveScreen(!showSaveScreen)}
            >
              保存筛选
            </button>
            {savedScreens.length > 0 && (
              <select
                className="form-select"
                style={{ width: "auto" }}
                value={selectedScreenId}
                onChange={(e) => handleLoadScreen(Number(e.target.value))}
              >
                <option value={0}>加载已保存筛选…</option>
                {savedScreens.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            )}
            {selectedScreenId > 0 && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleDeleteScreen(selectedScreenId)}
                title="删除当前筛选模板"
              >
                ✕ 删除模板
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 保存筛选表单 */}
      {showSaveScreen && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            background: "var(--surface-raised)",
            border: "1px solid var(--border-hairline)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-3) var(--space-4)",
          }}
        >
          <div className="flex gap-3 items-end">
            <label className="form-label" style={{ flex: 1 }}>
              <span>筛选名称</span>
              <input
                type="text"
                className="form-input"
                value={screenName}
                onChange={(e) => setScreenName(e.target.value)}
                placeholder="如 稳健偏股3年以上"
              />
            </label>
            <button className="btn btn-primary btn-sm" onClick={handleSaveScreen}>
              保存
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowSaveScreen(false)}>
              取消
            </button>
          </div>
        </div>
      )}

      {/* 批量操作栏 */}
      {selectedCodes.size > 0 && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            background: "var(--accent-soft)",
            border: "1px solid var(--accent)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-3) var(--space-4)",
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--accent)" }}>
              已选择 {selectedCodes.size} 只基金
            </span>
            <div className="flex gap-2 items-center">
              <select
                className="select"
                style={{ width: "auto" }}
                value={targetPoolId ?? 0}
                onChange={(e) => setTargetPoolId(Number(e.target.value) || null)}
              >
                <option value={0}>选择基金池…</option>
                {pools.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.fund_count})
                  </option>
                ))}
              </select>
              <button
                className="btn btn-primary btn-sm"
                disabled={!targetPoolId}
                onClick={handleAddToPool}
              >
                加入基金池
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setSelectedCodes(new Set())}
              >
                取消选择
              </button>
            </div>
          </div>
          {poolMsg && (
            <div className="text-sm mt-2" style={{ color: "var(--positive)" }}>
              {poolMsg}
            </div>
          )}
        </div>
      )}

      <div className="flex gap-6 fade-up fade-up-3">
        {/* 左侧筛选面板 */}
        <div className="filter-panel">
          <SectionHeader title="筛选条件" />

          <FilterGroup label="基本条件">
            <div className="filter-field">
              <label>基金类型</label>
              <select
                className="select"
                value={(filters.category as string) ?? ""}
                onChange={(e) => updateFilter("category", e.target.value)}
              >
                <option value="">全部</option>
                <option value="偏股混合">偏股混合</option>
                <option value="灵活配置">灵活配置</option>
                <option value="股票型">股票型</option>
                <option value="指数型">指数型</option>
                <option value="偏债混合">偏债混合</option>
              </select>
            </div>
            <div className="filter-field">
              <label>成立年限 ≥</label>
              <input
                className="input"
                type="number"
                placeholder="如 3"
                value={filters.min_inception_years ?? ""}
                onChange={(e) =>
                  updateFilter("min_inception_years", e.target.value)
                }
              />
            </div>
            <div className="filter-field">
              <label>规模下限 (亿)</label>
              <input
                className="input"
                type="number"
                placeholder="如 5"
                value={filters.min_scale_bn ?? ""}
                onChange={(e) => updateFilter("min_scale_bn", e.target.value)}
              />
            </div>
            <div className="filter-field">
              <label>规模上限 (亿)</label>
              <input
                className="input"
                type="number"
                placeholder="不限"
                value={filters.max_scale_bn ?? ""}
                onChange={(e) => updateFilter("max_scale_bn", e.target.value)}
              />
            </div>
          </FilterGroup>

          <FilterGroup label="经理条件">
            <div className="filter-field">
              <label>任职天数 ≥</label>
              <input
                className="input"
                type="number"
                placeholder="如 365"
                value={filters.min_manager_tenure_days ?? ""}
                onChange={(e) =>
                  updateFilter("min_manager_tenure_days", e.target.value)
                }
              />
            </div>
          </FilterGroup>

          <FilterGroup label="费率条件">
            <div className="filter-field">
              <label>管理费 ≤ (%)</label>
              <input
                className="input"
                type="number"
                step="0.1"
                placeholder="如 1.5"
                value={filters.max_mgmt_fee_pct ?? ""}
                onChange={(e) =>
                  updateFilter("max_mgmt_fee_pct", e.target.value)
                }
              />
            </div>
          </FilterGroup>

          <button
            className="btn btn-ghost btn-sm w-full mt-2"
            onClick={() => setFilters({})}
          >
            重置筛选
          </button>
        </div>

        {/* 右侧结果表格 */}
        <div className="flex-1">
          <SectionHeader
            title="筛选结果"
            subtitle={loading ? "搜索中…" : `共 ${total} 只基金`}
            actions={
              <div className="flex gap-2 items-center">
                {selectedCodes.size === funds.length && funds.length > 0 ? (
                  <button className="btn btn-ghost btn-sm" onClick={toggleSelectAll}>
                    取消全选
                  </button>
                ) : (
                  <button className="btn btn-ghost btn-sm" onClick={toggleSelectAll}>
                    全选
                  </button>
                )}
                <select
                  className="select"
                  style={{ width: "auto" }}
                  value={`${sortBy}:${sortOrder}`}
                  onChange={(e) => {
                    const [k, o] = e.target.value.split(":");
                    setSortBy(k);
                    setSortOrder(o as "asc" | "desc");
                  }}
                >
                  <option value="fund_code:asc">代码 ↑</option>
                  <option value="short_name:asc">名称 ↑</option>
                  <option value="scale_bn:desc">规模 ↓</option>
                  <option value="manager_tenure_days:desc">任职天数 ↓</option>
                  <option value="metrics.annualized_return_1y:desc">近1年收益 ↓</option>
                  <option value="metrics.annualized_return_3y:desc">近3年收益 ↓</option>
                  <option value="metrics.max_drawdown_1y:asc">最大回撤 ↑</option>
                  <option value="metrics.sharpe_ratio_1y:desc">夏普 ↓</option>
                  <option value="data_completeness:desc">完整度 ↓</option>
                </select>
              </div>
            }
          />

          {error ? (
            <ErrorState desc={error} onRetry={doSearch} />
          ) : loading && !hasSearched ? (
            <LoadingState rows={10} cols={8} />
          ) : funds.length === 0 ? (
            <EmptyState
              icon="∅"
              title="未找到符合条件的基金"
              desc="尝试调整筛选条件，或清除所有筛选后重新搜索。"
            />
          ) : (
            <DataTable
              columns={columns}
              data={funds}
              rowKey={(row) => row.fund_code}
              onRowClick={handleRowClick}
              initialSort={{ key: sortBy, order: sortOrder }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function Breadcrumb() {
  return (
    <div className="breadcrumb mb-2">
      <span className="breadcrumb-current">基金筛选</span>
    </div>
  );
}
