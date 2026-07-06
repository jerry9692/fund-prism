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

interface AlertRule {
  id: number;
  pool_id: number;
  fund_code: string;
  alert_type: string;
  params: Record<string, unknown>;
  is_active: boolean;
  created_at: string | null;
}

interface AlertRecord {
  id: number;
  rule_id: number | null;
  pool_id: number;
  fund_code: string;
  alert_type: string;
  severity: string;
  message: string;
  detail: Record<string, unknown> | null;
  triggered_at: string | null;
  is_read: boolean;
}

const ALERT_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "nav_change", label: "净值异动" },
  { value: "ranking_change", label: "排名变化" },
  { value: "manager_change", label: "经理变更" },
  { value: "scale_change", label: "规模异常" },
  { value: "style_drift", label: "风格漂移" },
  { value: "score_change", label: "评分跳变" },
];

const SEVERITY_COLOR: Record<string, string> = {
  info: "var(--info)",
  warning: "var(--warning)",
  critical: "var(--negative)",
  observation: "var(--ink-tertiary)",
};

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

  // Alert rule editor state
  const [alertRules, setAlertRules] = useState<AlertRule[]>([]);
  const [alertRecords, setAlertRecords] = useState<AlertRecord[]>([]);
  const [ruleFundCode, setRuleFundCode] = useState("");
  const [ruleAlertType, setRuleAlertType] = useState("nav_change");
  const [ruleThreshold, setRuleThreshold] = useState("");
  const [scanning, setScanning] = useState(false);
  const [alertsLoading, setAlertsLoading] = useState(false);

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

  const loadAlerts = useCallback(async (poolId: number) => {
    setAlertsLoading(true);
    try {
      const [rulesRes, recordsRes] = await Promise.all([
        api.listAlertRules(poolId),
        api.getPoolAlerts(poolId),
      ]);
      setAlertRules(rulesRes.data?.rules ?? []);
      const recordsRaw = (recordsRes.data?.items ?? []) as Array<Record<string, unknown>>;
      setAlertRecords(recordsRaw.map((r) => ({
        id: Number(r.id),
        rule_id: r.rule_id != null ? Number(r.rule_id) : null,
        pool_id: Number(r.pool_id),
        fund_code: String(r.fund_code ?? ""),
        alert_type: String(r.alert_type ?? ""),
        severity: String(r.severity ?? "info"),
        message: String(r.message ?? ""),
        detail: (r.detail as Record<string, unknown> | null) ?? null,
        triggered_at: r.triggered_at ? String(r.triggered_at) : null,
        is_read: Boolean(r.is_read),
      })));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载提醒数据失败");
    } finally {
      setAlertsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPools();
  }, [loadPools]);

  useEffect(() => {
    if (activePool) {
      loadMembers(activePool.id);
      loadAlerts(activePool.id);
    } else {
      setAlertRules([]);
      setAlertRecords([]);
    }
  }, [activePool, loadMembers, loadAlerts]);

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

  const handleCreateRule = async () => {
    if (!activePool) return;
    const code = ruleFundCode.trim();
    if (!code) {
      setError("请输入基金代码");
      return;
    }
    const params: Record<string, unknown> = {};
    const thresholdStr = ruleThreshold.trim();
    if (thresholdStr) {
      const tv = Number(thresholdStr);
      if (!Number.isNaN(tv)) params.threshold = tv;
    }
    try {
      await api.createAlertRule(activePool.id, {
        fund_code: code,
        alert_type: ruleAlertType,
        params,
      });
      setRuleFundCode("");
      setRuleThreshold("");
      setError(null);
      await loadAlerts(activePool.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建提醒规则失败");
    }
  };

  const handleDeleteRule = async (ruleId: number) => {
    if (!activePool) return;
    try {
      await api.deleteAlertRule(activePool.id, ruleId);
      await loadAlerts(activePool.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除提醒规则失败");
    }
  };

  const handleScanAlerts = async () => {
    if (!activePool) return;
    setScanning(true);
    try {
      await api.scanPoolAlerts(activePool.id);
      setError(null);
      await loadAlerts(activePool.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "扫描提醒失败");
    } finally {
      setScanning(false);
    }
  };

  const handleMarkAlertRead = async (alertId: number) => {
    if (!activePool) return;
    try {
      await api.markAlertRead(alertId);
      setAlertRecords((prev) =>
        prev.map((r) => (r.id === alertId ? { ...r, is_read: true } : r))
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "标记已读失败");
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

      {activePool && (
        <div className="fade-up fade-up-5" style={{ marginTop: "var(--space-5)" }}>
          <SectionHeader
            title="提醒规则"
            subtitle={`为「${activePool.name}」配置自动提醒，6 类规则可按基金单独设定`}
          />
          <form
            style={{
              background: "var(--surface-raised)",
              border: "1px solid var(--border-hairline)",
              borderRadius: "var(--radius-md)",
              padding: "var(--space-4)",
              marginTop: "var(--space-3)",
            }}
            onSubmit={(e) => {
              e.preventDefault();
              handleCreateRule();
            }}
          >
            <div
              className="grid"
              style={{
                gridTemplateColumns: "160px 180px 160px auto",
                gap: "var(--space-3)",
                alignItems: "end",
              }}
            >
              <label className="form-label">
                <span>基金代码 *</span>
                <input
                  type="text"
                  className="form-input"
                  value={ruleFundCode}
                  onChange={(e) => setRuleFundCode(e.target.value)}
                  placeholder="如 000001"
                  style={{ fontFamily: "var(--font-mono)" }}
                />
              </label>
              <label className="form-label">
                <span>提醒类型 *</span>
                <select
                  className="form-input"
                  value={ruleAlertType}
                  onChange={(e) => setRuleAlertType(e.target.value)}
                >
                  {ALERT_TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="form-label">
                <span>阈值（可选）</span>
                <input
                  type="text"
                  className="form-input"
                  value={ruleThreshold}
                  onChange={(e) => setRuleThreshold(e.target.value)}
                  placeholder="留空使用默认"
                  style={{ fontFamily: "var(--font-mono)" }}
                />
              </label>
              <button type="submit" className="btn btn-primary" disabled={!ruleFundCode.trim()}>
                新建规则
              </button>
            </div>
            <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
              阈值说明：nav_change/ranking_change/scale_change 用小数（如 0.05 表示 5%），
              score_change 用分数（如 15 表示 15 分），manager_change/style_drift 无需阈值。
            </div>
          </form>

          <div style={{ marginTop: "var(--space-3)" }}>
            {alertRules.length === 0 ? (
              <EmptyState
                icon="\Notifications"
                title="暂无提醒规则"
                desc="为池内基金新建提醒规则，扫描时将自动检测"
              />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {alertRules.map((rule) => {
                  const typeLabel =
                    ALERT_TYPE_OPTIONS.find((o) => o.value === rule.alert_type)?.label ??
                    rule.alert_type;
                  const threshold = rule.params?.threshold;
                  return (
                    <div
                      key={rule.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-3)",
                        padding: "var(--space-2) var(--space-3)",
                        background: "var(--surface-raised)",
                        border: "1px solid var(--border-hairline)",
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      <span className="mono" style={{ fontWeight: 600, minWidth: "80px" }}>
                        {rule.fund_code}
                      </span>
                      <span
                        style={{
                          padding: "2px var(--space-2)",
                          background: "var(--accent-soft)",
                          color: "var(--accent)",
                          borderRadius: "var(--radius-xs)",
                          fontSize: "0.8rem",
                        }}
                      >
                        {typeLabel}
                      </span>
                      {threshold != null && (
                        <span className="mono text-sm text-tertiary">
                          阈值 {String(threshold)}
                        </span>
                      )}
                      <span
                        className="text-sm text-tertiary"
                        style={{ marginLeft: "auto" }}
                      >
                        {rule.is_active ? "启用" : "停用"}
                      </span>
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ color: "var(--negative)" }}
                        onClick={() => handleDeleteRule(rule.id)}
                      >
                        删除
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {activePool && (
        <div className="fade-up fade-up-6" style={{ marginTop: "var(--space-5)" }}>
          <SectionHeader
            title="提醒记录"
            subtitle={`共 ${alertRecords.length} 条`}
            actions={
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleScanAlerts}
                disabled={scanning || members.length === 0}
              >
                {scanning ? "扫描中…" : "立即扫描"}
              </button>
            }
          />
          <div style={{ marginTop: "var(--space-3)" }}>
            {alertsLoading ? (
              <LoadingState rows={3} cols={4} />
            ) : alertRecords.length === 0 ? (
              <EmptyState
                icon="∅"
                title="暂无提醒记录"
                desc="点击「立即扫描」手动触发提醒检测，或等待系统定时扫描"
              />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {alertRecords.map((rec) => {
                  const sevColor = SEVERITY_COLOR[rec.severity] ?? "var(--ink-tertiary)";
                  return (
                    <div
                      key={rec.id}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: "var(--space-3)",
                        padding: "var(--space-3)",
                        background: rec.is_read
                          ? "var(--surface-raised)"
                          : "var(--accent-subtle)",
                        border: "1px solid var(--border-hairline)",
                        borderLeft: `3px solid ${sevColor}`,
                        borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
                      }}
                    >
                      <span
                        style={{
                          padding: "2px var(--space-2)",
                          background: sevColor,
                          color: "white",
                          borderRadius: "var(--radius-xs)",
                          fontSize: "0.72rem",
                          fontWeight: 600,
                          minWidth: "52px",
                          textAlign: "center",
                          textTransform: "uppercase",
                          flexShrink: 0,
                        }}
                      >
                        {rec.severity}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "baseline" }}>
                          <span className="mono text-sm" style={{ fontWeight: 600 }}>
                            {rec.fund_code}
                          </span>
                          <span className="text-sm text-tertiary">
                            {ALERT_TYPE_OPTIONS.find((o) => o.value === rec.alert_type)?.label ??
                              rec.alert_type}
                          </span>
                          {!rec.is_read && (
                            <span
                              style={{
                                fontSize: "0.7rem",
                                color: "var(--accent)",
                                fontWeight: 600,
                              }}
                            >
                              ● 未读
                            </span>
                          )}
                        </div>
                        <div
                          className="text-sm"
                          style={{ marginTop: "var(--space-1)", color: "var(--ink-primary)" }}
                        >
                          {rec.message}
                        </div>
                        <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-1)" }}>
                          {rec.triggered_at
                            ? new Date(rec.triggered_at).toLocaleString("zh-CN")
                            : "—"}
                        </div>
                      </div>
                      {!rec.is_read && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => handleMarkAlertRead(rec.id)}
                        >
                          标记已读
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
