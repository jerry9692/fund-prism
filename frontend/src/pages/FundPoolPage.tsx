// 基金池页 — 后端持久化的基金观察列表(P2.5-1)
// 支持多池子管理、添加/移除基金、备注、导出 JSON

import { useEffect, useState, useCallback } from "react";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  EmptyState,
  LoadingState,
  ExportButton,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { api } from "../api/client";

interface Pool {
  id: number;
  name: string;
  description: string | null;
  fund_count: number;
  created_at: string | null;
  updated_at: string | null;
}

interface PoolMember {
  fund_code: string;
  note: string | null;
  added_at: string | null;
}

interface PoolRow extends PoolMember {
  key: string;
  removeSelf: (code: string) => void;
}

const COLUMNS: Column<PoolRow>[] = [
  {
    key: "fund_code",
    header: "基金代码",
    width: "120px",
    sortable: true,
    render: (row) => (
      <a
        href={`#/funds/${row.fund_code}`}
        className="mono"
        style={{ color: "var(--accent)", fontWeight: 600 }}
      >
        {row.fund_code}
      </a>
    ),
    sortValue: (row) => row.fund_code,
  },
  {
    key: "added_at",
    header: "加入时间",
    width: "170px",
    sortable: true,
    render: (row) => (
      <span className="mono text-sm text-tertiary">
        {row.added_at
          ? new Date(row.added_at).toLocaleString("zh-CN")
          : "—"}
      </span>
    ),
    sortValue: (row) => row.added_at ?? "",
  },
  {
    key: "note",
    header: "备注",
    render: (row) => (
      <span className="text-sm" style={{ color: "var(--ink-secondary)" }}>
        {row.note || "—"}
      </span>
    ),
  },
  {
    key: "actions",
    header: "操作",
    width: "80px",
    render: (row) => (
      <button
        className="btn btn-ghost btn-sm"
        style={{ color: "var(--negative)" }}
        onClick={() => row.removeSelf(row.fund_code)}
      >
        移除
      </button>
    ),
  },
];

export default function FundPoolPage() {
  const [pools, setPools] = useState<Pool[]>([]);
  const [activePool, setActivePool] = useState<Pool | null>(null);
  const [members, setMembers] = useState<PoolMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fundCode, setFundCode] = useState("");
  const [note, setNote] = useState("");
  const [newPoolName, setNewPoolName] = useState("");
  const [newPoolDesc, setNewPoolDesc] = useState("");

  const loadPools = useCallback(async () => {
    try {
      const res = await api.listPools();
      const list = res.data ?? [];
      setPools(list);
      if (list.length > 0 && !activePool) {
        setActivePool(list[0]);
      } else if (list.length === 0) {
        setActivePool(null);
        setMembers([]);
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载基金池失败");
    } finally {
      setLoading(false);
    }
  }, [activePool]);

  const loadMembers = useCallback(async (poolId: number) => {
    try {
      const res = await api.getPool(poolId);
      setMembers(res.data?.funds ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载池内基金失败");
    }
  }, []);

  useEffect(() => {
    loadPools();
  }, [loadPools]);

  useEffect(() => {
    if (activePool) {
      loadMembers(activePool.id);
    }
  }, [activePool, loadMembers]);

  const handleAddFund = async () => {
    if (!activePool) return;
    const code = fundCode.trim();
    if (!code) {
      setError("请输入基金代码");
      return;
    }
    if (members.some((m) => m.fund_code === code)) {
      setError("该基金已在当前池中");
      return;
    }
    try {
      await api.addPoolMember(activePool.id, {
        fund_code: code,
        note: note.trim() || undefined,
      });
      setFundCode("");
      setNote("");
      setError(null);
      await loadMembers(activePool.id);
      await loadPools();
    } catch (e) {
      setError(e instanceof Error ? e.message : "添加基金失败");
    }
  };

  const handleRemoveFund = async (code: string) => {
    if (!activePool) return;
    try {
      await api.removePoolMember(activePool.id, code);
      await loadMembers(activePool.id);
      await loadPools();
    } catch (e) {
      setError(e instanceof Error ? e.message : "移除基金失败");
    }
  };

  const handleCreatePool = async () => {
    const name = newPoolName.trim();
    if (!name) return;
    try {
      const res = await api.createPool({
        name,
        description: newPoolDesc.trim() || undefined,
      });
      const created = res.data;
      if (created) {
        setNewPoolName("");
        setNewPoolDesc("");
        setError(null);
        await loadPools();
        setActivePool({
          id: created.id,
          name: created.name,
          description: created.description,
          fund_count: 0,
          created_at: null,
          updated_at: null,
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建池子失败");
    }
  };

  const handleDeletePool = async () => {
    if (!activePool) return;
    if (pools.length <= 1) {
      setError("至少保留一个池子");
      return;
    }
    if (!confirm(`确认删除池子「${activePool.name}」及其全部 ${members.length} 只基金？`)) return;
    try {
      await api.deletePool(activePool.id);
      const remaining = pools.filter((p) => p.id !== activePool.id);
      setPools(remaining);
      setActivePool(remaining[0] ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除池子失败");
    }
  };

  const handleClearPool = async () => {
    if (!activePool || members.length === 0) return;
    if (!confirm(`确认清空池子「${activePool.name}」中的全部 ${members.length} 只基金？`)) return;
    try {
      await Promise.all(
        members.map((m) => api.removePoolMember(activePool.id, m.fund_code))
      );
      await loadMembers(activePool.id);
      await loadPools();
    } catch (e) {
      setError(e instanceof Error ? e.message : "清空池子失败");
    }
  };

  const totalFunds = pools.reduce((s, p) => s + p.fund_count, 0);

  const exportData = {
    pools: pools.map((p) => ({
      ...p,
      funds: p.id === activePool?.id ? members : [],
    })),
  };

  const rows: PoolRow[] = members.map((m) => ({
    ...m,
    key: m.fund_code,
    removeSelf: handleRemoveFund,
  }));

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "基金池" },
  ];

  if (loading) return <LoadingState rows={4} cols={4} />;

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div className="fade-up fade-up-1" style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}>
        <h1>基金池</h1>
        <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
          管理基金观察列表，支持多池子分组与备注（已同步至后端）
        </div>
      </div>

      {error && (
        <div
          className="fade-up fade-up-2"
          style={{
            marginBottom: "var(--space-4)",
            padding: "var(--space-3) var(--space-4)",
            background: "var(--negative-soft)",
            borderLeft: "3px solid var(--negative)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
            fontSize: "0.82rem",
            color: "var(--negative)",
          }}
        >
          {error}
        </div>
      )}

      <div
        className="grid fade-up fade-up-2"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <MetricCard label="池子数" value={pools.length} />
        <MetricCard label="基金总数" value={totalFunds} />
        <MetricCard
          label="当前池"
          value={activePool?.name ?? "—"}
          sub={`${members.length} 只基金`}
        />
      </div>

      <div
        className="fade-up fade-up-3"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          marginBottom: "var(--space-4)",
        }}
      >
        <SectionHeader
          title="池子切换"
          subtitle="点击切换当前活动池子，或新建/删除池子"
        />
        <div
          style={{
            display: "flex",
            gap: "var(--space-2)",
            flexWrap: "wrap",
            marginTop: "var(--space-3)",
          }}
        >
          {pools.map((pool) => (
            <button
              key={pool.id}
              className={`btn btn-sm ${activePool?.id === pool.id ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setActivePool(pool)}
            >
              {pool.name}{" "}
              <span className="mono" style={{ opacity: 0.7 }}>
                ({pool.fund_count})
              </span>
            </button>
          ))}
        </div>
        <div
          className="grid"
          style={{
            gridTemplateColumns: "1fr 1fr auto auto",
            gap: "var(--space-2)",
            marginTop: "var(--space-3)",
            alignItems: "end",
          }}
        >
          <label className="form-label">
            <span>新池子名称</span>
            <input
              type="text"
              className="form-input"
              value={newPoolName}
              onChange={(e) => setNewPoolName(e.target.value)}
              placeholder="如：消费主题池"
            />
          </label>
          <label className="form-label">
            <span>描述（可选）</span>
            <input
              type="text"
              className="form-input"
              value={newPoolDesc}
              onChange={(e) => setNewPoolDesc(e.target.value)}
              placeholder="如：核心观察池"
            />
          </label>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleCreatePool}
            disabled={!newPoolName.trim()}
          >
            新建池子
          </button>
          <button
            className="btn btn-ghost btn-sm"
            style={{ color: "var(--negative)" }}
            onClick={handleDeletePool}
          >
            删除当前池
          </button>
        </div>
      </div>

      {activePool && (
        <form
          className="fade-up fade-up-3"
          style={{
            background: "var(--surface-raised)",
            border: "1px solid var(--border-hairline)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-4)",
            marginBottom: "var(--space-4)",
          }}
          onSubmit={(e) => {
            e.preventDefault();
            handleAddFund();
          }}
        >
          <SectionHeader
            title="添加基金到当前池"
            subtitle={`目标池：${activePool.name}`}
          />
          <div
            className="grid"
            style={{
              gridTemplateColumns: "200px 1fr auto",
              gap: "var(--space-3)",
              marginTop: "var(--space-3)",
              alignItems: "end",
            }}
          >
            <label className="form-label">
              <span>基金代码 *</span>
              <input
                type="text"
                className="form-input"
                value={fundCode}
                onChange={(e) => setFundCode(e.target.value)}
                placeholder="如 000001"
                style={{ fontFamily: "var(--font-mono)" }}
              />
            </label>
            <label className="form-label">
              <span>备注（可选）</span>
              <input
                type="text"
                className="form-input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="如：核心持仓 / 观察候选"
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={!fundCode.trim()}>
              加入池子
            </button>
          </div>
        </form>
      )}

      {activePool && (
        <div className="fade-up fade-up-4">
          <SectionHeader
            title={`「${activePool.name}」基金列表`}
            subtitle={`共 ${members.length} 只`}
            actions={
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <ExportButton
                  data={exportData}
                  filename={`fund-pools-${new Date().toISOString().slice(0, 10)}.json`}
                  label="导出 JSON"
                  disabled={totalFunds === 0}
                />
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ color: "var(--negative)" }}
                  onClick={handleClearPool}
                  disabled={members.length === 0}
                >
                  清空池子
                </button>
              </div>
            }
          />
          <div style={{ marginTop: "var(--space-3)" }}>
            {members.length === 0 ? (
              <EmptyState
                icon="∅"
                title="当前池子为空"
                desc="通过上方表单添加基金，或切换到其他池子"
              />
            ) : (
              <DataTable
                columns={COLUMNS}
                data={rows}
                rowKey={(row) => row.key}
                initialSort={{ key: "added_at", order: "desc" }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
