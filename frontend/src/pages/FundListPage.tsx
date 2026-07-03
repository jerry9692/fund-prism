// 基金筛选页 — 专业筛选工作台
// 左侧分组筛选面板 + 右侧指标内嵌表格 + 筛选即搜索 + 批量操作

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
} from "../components/display";

interface FundRow {
  fund_code: string;
  short_name: string;
  full_name: string;
  fund_type: string;
  total_nav: number | null;
  inception_date: string | null;
  manager_name: string | null;
  manager_tenure_days: number | null;
  review_status: string | null;
}

const PAGE_SIZE = 50;

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

  const columns: Column<FundRow>[] = [
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
      key: "fund_type",
      header: "类型",
      width: "90px",
      render: (row) => (
        <span className="text-tertiary text-sm">{row.fund_type}</span>
      ),
    },
    {
      key: "total_nav",
      header: "规模(亿)",
      numeric: true,
      sortable: true,
      render: (row) =>
        row.total_nav !== null ? (
          <span>{(row.total_nav / 1e8).toFixed(2)}</span>
        ) : (
          "—"
        ),
      sortValue: (row) => row.total_nav,
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
      header: "任职天数",
      numeric: true,
      sortable: true,
      render: (row) =>
        row.manager_tenure_days !== null ? (
          <span>{row.manager_tenure_days}</span>
        ) : (
          "—"
        ),
      sortValue: (row) => row.manager_tenure_days,
    },
    {
      key: "inception_date",
      header: "成立日期",
      sortable: true,
      render: (row) => (
        <span className="text-sm text-tertiary">
          {row.inception_date ?? "—"}
        </span>
      ),
      sortValue: (row) => row.inception_date ?? "",
    },
  ];

  const handleRowClick = (row: FundRow) => {
    // 记录到最近浏览
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
        // 数字类型转换
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
        <h1>基金筛选</h1>
      </div>

      <div className="flex gap-6 fade-up fade-up-2">
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
              <div className="flex gap-2">
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
                  <option value="total_nav:desc">规模 ↓</option>
                  <option value="manager_tenure_days:desc">任职天数 ↓</option>
                </select>
              </div>
            }
          />

          {error ? (
            <ErrorState desc={error} onRetry={doSearch} />
          ) : loading && !hasSearched ? (
            <LoadingState rows={10} cols={7} />
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
