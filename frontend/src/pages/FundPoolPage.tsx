// 基金池页 — 基于 localStorage 的基金观察列表（P2.5-1 后端持久化的前端过渡方案）
// 支持多池子管理、添加/移除基金、备注、导出 JSON

import { useEffect, useState } from "react";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  EmptyState,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";

interface PoolEntry {
  fund_code: string;
  short_name: string;
  added_at: string;
  note: string;
}

type Pools = Record<string, PoolEntry[]>;

const STORAGE_KEY = "fund_research_pools_v1";

function loadPools(): Pools {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { "默认池": [] };
    const parsed = JSON.parse(raw) as Pools;
    if (Object.keys(parsed).length === 0) return { "默认池": [] };
    return parsed;
  } catch {
    return { "默认池": [] };
  }
}

function savePools(pools: Pools) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(pools));
}

interface PoolRow extends PoolEntry {
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
    key: "short_name",
    header: "名称",
    render: (row) => <span>{row.short_name || "—"}</span>,
  },
  {
    key: "added_at",
    header: "加入时间",
    width: "170px",
    sortable: true,
    render: (row) => (
      <span className="mono text-sm text-tertiary">{row.added_at}</span>
    ),
    sortValue: (row) => row.added_at,
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
  const [pools, setPools] = useState<Pools>({ "默认池": [] });
  const [activePool, setActivePool] = useState("默认池");
  const [fundCode, setFundCode] = useState("");
  const [shortName, setShortName] = useState("");
  const [note, setNote] = useState("");
  const [newPoolName, setNewPoolName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loaded = loadPools();
    setPools(loaded);
    setActivePool(Object.keys(loaded)[0]);
  }, []);

  function persist(next: Pools) {
    setPools(next);
    savePools(next);
  }

  const currentEntries = pools[activePool] ?? [];

  function addFund() {
    const code = fundCode.trim();
    if (!code) {
      setError("请输入基金代码");
      return;
    }
    if (currentEntries.some((e) => e.fund_code === code)) {
      setError("该基金已在当前池中");
      return;
    }
    const now = new Date().toLocaleString("zh-CN");
    const entry: PoolEntry = {
      fund_code: code,
      short_name: shortName.trim() || code,
      added_at: now,
      note: note.trim(),
    };
    const next: Pools = {
      ...pools,
      [activePool]: [entry, ...currentEntries],
    };
    persist(next);
    setFundCode("");
    setShortName("");
    setNote("");
    setError(null);
  }

  function removeFund(code: string) {
    const next: Pools = {
      ...pools,
      [activePool]: currentEntries.filter((e) => e.fund_code !== code),
    };
    persist(next);
  }

  function createPool() {
    const name = newPoolName.trim();
    if (!name) return;
    if (pools[name]) {
      setError("该池子已存在");
      return;
    }
    const next: Pools = { ...pools, [name]: [] };
    persist(next);
    setActivePool(name);
    setNewPoolName("");
    setError(null);
  }

  function deletePool() {
    if (Object.keys(pools).length <= 1) {
      setError("至少保留一个池子");
      return;
    }
    const next = { ...pools };
    delete next[activePool];
    persist(next);
    setActivePool(Object.keys(next)[0]);
  }

  function clearPool() {
    if (!confirm(`确认清空池子「${activePool}」中的全部 ${currentEntries.length} 只基金？`)) return;
    persist({ ...pools, [activePool]: [] });
  }

  function exportJSON() {
    const blob = new Blob([JSON.stringify(pools, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fund-pools-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const totalFunds = Object.values(pools).reduce((s, arr) => s + arr.length, 0);

  const rows: PoolRow[] = currentEntries.map((e) => ({
    ...e,
    key: e.fund_code,
    removeSelf: removeFund,
  }));

  const crumbs: BreadcrumbItem[] = [
    { label: "基金研究" },
    { label: "基金池" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1" style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}>
        <h1>基金池</h1>
        <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
          管理基金观察列表，支持多池子分组与备注
        </div>
      </div>

      {/* 说明横幅 */}
      <div
        className="fade-up fade-up-2"
        style={{
          marginBottom: "var(--space-4)",
          padding: "var(--space-3) var(--space-4)",
          background: "var(--warning-soft)",
          borderLeft: "3px solid var(--warning)",
          borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          fontSize: "0.82rem",
          color: "var(--warning)",
        }}
      >
        ⚠ 当前基金池数据保存在浏览器 localStorage（本机单用户）。后端持久化方案
        (P2.5-1) 实现后将自动同步。清理浏览器数据会丢失池子，请及时导出 JSON 备份。
      </div>

      {/* 概要指标卡 */}
      <div
        className="grid fade-up fade-up-2"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <MetricCard label="池子数" value={Object.keys(pools).length} />
        <MetricCard label="基金总数" value={totalFunds} />
        <MetricCard
          label="当前池"
          value={activePool}
          sub={`${currentEntries.length} 只基金`}
        />
      </div>

      {/* 池子管理 */}
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
          {Object.keys(pools).map((name) => (
            <button
              key={name}
              className={`btn btn-sm ${name === activePool ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setActivePool(name)}
            >
              {name}{" "}
              <span className="mono" style={{ opacity: 0.7 }}>
                ({pools[name].length})
              </span>
            </button>
          ))}
        </div>
        <div
          className="grid"
          style={{
            gridTemplateColumns: "1fr auto auto",
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
          <button
            className="btn btn-secondary btn-sm"
            onClick={createPool}
            disabled={!newPoolName.trim()}
          >
            新建池子
          </button>
          <button
            className="btn btn-ghost btn-sm"
            style={{ color: "var(--negative)" }}
            onClick={deletePool}
          >
            删除当前池
          </button>
        </div>
      </div>

      {/* 添加基金表单 */}
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
          addFund();
        }}
      >
        <SectionHeader
          title="添加基金到当前池"
          subtitle={`目标池：${activePool}`}
        />
        <div
          className="grid"
          style={{
            gridTemplateColumns: "140px 1fr 1fr auto",
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
            <span>简称（可选）</span>
            <input
              type="text"
              className="form-input"
              value={shortName}
              onChange={(e) => setShortName(e.target.value)}
              placeholder="留空则用代码作为名称"
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
        {error && (
          <div
            style={{
              marginTop: "var(--space-3)",
              padding: "var(--space-2) var(--space-3)",
              background: "var(--negative-soft)",
              borderLeft: "3px solid var(--negative)",
              borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
              color: "var(--negative)",
              fontSize: "0.82rem",
            }}
          >
            {error}
          </div>
        )}
      </form>

      {/* 池子内容 */}
      <div className="fade-up fade-up-4">
        <SectionHeader
          title={`「${activePool}」基金列表`}
          subtitle={`共 ${currentEntries.length} 只`}
          actions={
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={exportJSON}
                disabled={totalFunds === 0}
              >
                导出 JSON
              </button>
              <button
                className="btn btn-ghost btn-sm"
                style={{ color: "var(--negative)" }}
                onClick={clearPool}
                disabled={currentEntries.length === 0}
              >
                清空池子
              </button>
            </div>
          }
        />
        <div style={{ marginTop: "var(--space-3)" }}>
          {currentEntries.length === 0 ? (
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
    </div>
  );
}
