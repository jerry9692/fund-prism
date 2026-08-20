// 基金池页 — 后端持久化的基金观察列表(P2.5-1) + 组合穿透分析(P4C)
// 支持多池子管理、添加/移除基金、备注、权重编辑、组合分析与研究包导出

import { useEffect, useState, useCallback } from "react";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  EmptyState,
  LoadingState,
  ExportButton,
  StatusBadge,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";
import { api, type PortfolioAnalysis } from "../api/client";

interface Pool {
  id: string;
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
  weight_pct: number | null;
}

interface PoolRow extends PoolMember {
  key: string;
  removeSelf: (code: string) => void;
  weightDraft: string;
  onWeightChange: (code: string, value: string) => void;
}

interface AlertRule {
  id: string;
  pool_id: string;
  fund_code: string;
  alert_type: string;
  params: Record<string, unknown>;
  is_active: boolean;
  created_at: string | null;
}

interface AlertRecord {
  id: string;
  rule_id: string | null;
  pool_id: string;
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

const STYLE_LABELS: Record<string, string> = {
  large_cap: "大盘",
  mid_cap: "中盘",
  small_cap: "小盘",
  growth: "成长",
  value: "价值",
};

function fmtPct(v: number | string | null | undefined, digits = 2): string {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

// ---- P4C 组合分析展示（指标/相关性/穿透/重叠/集中度）----

function PortfolioAnalysisView({ analysis }: { analysis: PortfolioAnalysis }) {
  const m = analysis.portfolio_metrics ?? {};
  const corr = analysis.correlation_matrix ?? {};
  const corrCodes = Object.keys(corr);
  const disclosed = analysis.holding_overlap?.disclosed;
  const estimated = analysis.holding_overlap?.estimated_overlap ?? {};
  const estimatedCount =
    typeof estimated["estimated_shared_stock_count"] === "number"
      ? (estimated["estimated_shared_stock_count"] as number)
      : null;

  return (
    <div style={{ marginTop: "var(--space-3)" }}>
      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBottom: "var(--space-3)" }}>
        <StatusBadge status={analysis.conclusion_status} />
        <span className="text-sm text-tertiary">
          权重模式：{analysis.weights_mode === "weighted" ? "自定义权重" : "等权（观察列表）"}
          {analysis.window_start && ` · 窗口 ${analysis.window_start} ~ ${analysis.window_end}`}
        </span>
      </div>

      {analysis.warnings.length > 0 && (
        <div className="text-sm text-tertiary" style={{ marginBottom: "var(--space-3)" }}>
          {analysis.warnings.join("；")}
        </div>
      )}

      <div
        className="grid"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <MetricCard label="年化收益" value={fmtPct(m.annualized_return)} />
        <MetricCard label="年化波动" value={fmtPct(m.annualized_volatility)} />
        <MetricCard label="最大回撤" value={fmtPct(m.max_drawdown)} />
        <MetricCard label="Sharpe" value={m.sharpe_ratio != null ? Number(m.sharpe_ratio).toFixed(2) : "—"} />
        <MetricCard
          label="回撤修复天数"
          value={m.recovery_days == null ? "未修复" : String(m.recovery_days)}
        />
        <MetricCard label="月度胜率" value={fmtPct(m.win_rate, 0)} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
        <div>
          <SectionHeader title="风格穿透" subtitle="成员最新风格暴露加权合成（缺失成员权重再归一）" />
          {analysis.style_penetration?.available && analysis.style_penetration.composite ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
              {Object.entries(analysis.style_penetration.composite).map(([dim, value]) => (
                <span
                  key={dim}
                  className="mono text-sm"
                  style={{
                    padding: "4px var(--space-3)",
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border-hairline)",
                    borderRadius: "var(--radius-sm)",
                  }}
                >
                  {STYLE_LABELS[dim] ?? dim} {fmtPct(value, 1)}
                </span>
              ))}
            </div>
          ) : (
            <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
              无成员风格暴露可得
            </div>
          )}

          <SectionHeader title="行业穿透（SW2021 一级）" subtitle="披露持仓行业权重加权合成" />
          {analysis.industry_penetration?.available && analysis.industry_penetration.industries ? (
            <table className="mono text-sm" style={{ width: "100%", marginTop: "var(--space-2)" }}>
              <tbody>
                {analysis.industry_penetration.industries.slice(0, 8).map((item) => (
                  <tr key={item.industry}>
                    <td style={{ padding: "3px 0" }}>{item.industry}</td>
                    <td style={{ textAlign: "right" }}>{fmtPct(item.weight, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
              无披露股票持仓可得
            </div>
          )}
        </div>

        <div>
          <SectionHeader title="相关性矩阵" subtitle="成员日收益相关系数（对称，对角为 1）" />
          {corrCodes.length > 0 ? (
            <table className="mono text-sm" style={{ marginTop: "var(--space-2)" }}>
              <thead>
                <tr>
                  <th style={{ padding: "3px 8px" }} />
                  {corrCodes.map((c) => (
                    <th key={c} style={{ padding: "3px 8px" }}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {corrCodes.map((a) => (
                  <tr key={a}>
                    <td style={{ padding: "3px 8px", fontWeight: 600 }}>{a}</td>
                    {corrCodes.map((b) => (
                      <td key={b} style={{ textAlign: "right", padding: "3px 8px" }}>
                        {corr[a]?.[b]?.toFixed(2) ?? "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
              样本不足，相关性不可得
            </div>
          )}

          <SectionHeader title="集中度风险" subtitle="同一现任经理/同一公司权重合计" />
          <div className="text-sm" style={{ marginTop: "var(--space-2)" }}>
            {analysis.concentration?.manager_concentration?.length ? (
              <div style={{ marginBottom: "var(--space-2)" }}>
                {analysis.concentration.manager_concentration.map((item) => (
                  <div key={item.manager_id} style={{ display: "flex", gap: "var(--space-2)" }}>
                    <span>经理 {item.manager_name}</span>
                    <span className="mono">{fmtPct(item.weight, 1)}</span>
                    <span className="text-tertiary">｜{item.fund_codes.join("、")}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-tertiary">无现任经理任职记录</div>
            )}
            {analysis.concentration?.company_concentration?.map((item) => (
              <div key={item.company} style={{ display: "flex", gap: "var(--space-2)" }}>
                <span>公司 {item.company}</span>
                <span className="mono">{fmtPct(item.weight, 1)}</span>
                <span className="text-tertiary">｜{item.fund_codes.join("、")}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <SectionHeader
        title="重仓重叠穿透"
        subtitle="披露口径（computed）为主；模拟持仓口径（estimated）隔离展示，不进默认结论"
      />
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", marginTop: "var(--space-2)" }}>
        <div>
          {disclosed?.available && disclosed.top_overlaps.length > 0 ? (
            <>
              <div className="text-sm text-tertiary" style={{ marginBottom: "var(--space-2)" }}>
                共享个股 {disclosed.shared_stock_count} / 并集 {disclosed.union_stock_count}
                {disclosed.overlap_ratio != null && ` · 重叠率 ${fmtPct(disclosed.overlap_ratio, 1)}`}
              </div>
              <table className="mono text-sm" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "3px 8px" }}>个股</th>
                    <th style={{ textAlign: "right", padding: "3px 8px" }}>持有基金数</th>
                    <th style={{ textAlign: "right", padding: "3px 8px" }}>组合合计权重</th>
                  </tr>
                </thead>
                <tbody>
                  {disclosed.top_overlaps.slice(0, 10).map((item) => (
                    <tr key={item.stock_code}>
                      <td style={{ padding: "3px 8px" }}>
                        {item.stock_name ?? item.stock_code}
                        <span className="text-tertiary"> {item.stock_code}</span>
                      </td>
                      <td style={{ textAlign: "right", padding: "3px 8px" }}>{item.fund_count}</td>
                      <td style={{ textAlign: "right", padding: "3px 8px" }}>{fmtPct(item.combined_weight, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <div className="text-sm text-tertiary">披露口径无重叠个股（或无披露持仓）</div>
          )}
        </div>
        <div
          style={{
            padding: "var(--space-3)",
            background: "var(--surface-raised)",
            border: "1px dashed var(--border-hairline)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: "var(--space-2)" }}>
            estimated 口径（模拟持仓，隔离展示）
          </div>
          {estimatedCount != null ? (
            <div className="text-sm text-tertiary">
              模拟持仓共享个股 {estimatedCount} 只；估计结果不进默认结论与评分。
            </div>
          ) : (
            <div className="text-sm text-tertiary">无成员模拟持仓结果</div>
          )}
        </div>
      </div>
    </div>
  );
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
    key: "weight_pct",
    header: "组合权重(%)",
    width: "120px",
    render: (row) => (
      <input
        type="number"
        min={0}
        max={100}
        step={0.1}
        className="form-input"
        style={{ width: "90px", padding: "4px 8px", fontFamily: "var(--font-mono)" }}
        value={row.weightDraft}
        placeholder="—"
        onChange={(e) => row.onWeightChange(row.fund_code, e.target.value)}
      />
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

  // P4C 组合权重与分析状态
  const [weightDrafts, setWeightDrafts] = useState<Record<string, string>>({});
  const [savingWeights, setSavingWeights] = useState(false);
  const [analysis, setAnalysis] = useState<PortfolioAnalysis | null>(null);
  const [analysisRunning, setAnalysisRunning] = useState(false);
  const [packetInfo, setPacketInfo] = useState<string | null>(null);
  const [packetBuilding, setPacketBuilding] = useState(false);

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

  const loadMembers = useCallback(async (poolId: string) => {
    try {
      const res = await api.getPool(poolId);
      setMembers(res.data?.funds ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载池内基金失败");
    }
  }, []);

  const loadAlerts = useCallback(async (poolId: string) => {
    setAlertsLoading(true);
    try {
      const [rulesRes, recordsRes] = await Promise.all([
        api.listAlertRules(poolId),
        api.getPoolAlerts(poolId),
      ]);
      setAlertRules(rulesRes.data?.rules ?? []);
      const recordsRaw = (recordsRes.data?.items ?? []) as Array<Record<string, unknown>>;
      setAlertRecords(recordsRaw.map((r) => ({
        id: String(r.id),
        rule_id: r.rule_id != null ? String(r.rule_id) : null,
        pool_id: String(r.pool_id),
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
      // 读最近一次组合分析快照（无则留空）
      let cancelled = false;
      api
        .getLatestPortfolioAnalysis(activePool.id)
        .then((res) => {
          if (!cancelled) setAnalysis(res.data ?? null);
        })
        .catch(() => {
          if (!cancelled) setAnalysis(null);
        });
      return () => {
        cancelled = true;
      };
    }
    setAlertRules([]);
    setAlertRecords([]);
    setAnalysis(null);
    setPacketInfo(null);
    return undefined;
  }, [activePool, loadMembers, loadAlerts]);

  // 成员变化时同步权重草稿
  useEffect(() => {
    setWeightDrafts(
      Object.fromEntries(
        members.map((m) => [
          m.fund_code,
          m.weight_pct != null ? String(m.weight_pct) : "",
        ])
      )
    );
  }, [members]);

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

  const handleDeleteRule = async (ruleId: string) => {
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

  const handleMarkAlertRead = async (alertId: string) => {
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

  // ---- P4C 组合权重与分析 ----

  const handleWeightChange = (code: string, value: string) => {
    setWeightDrafts((prev) => ({ ...prev, [code]: value }));
  };

  const weightsDirty = members.some((m) => {
    const draft = weightDrafts[m.fund_code] ?? "";
    const current = m.weight_pct != null ? String(m.weight_pct) : "";
    return draft !== current;
  });

  const handleSaveWeights = async () => {
    if (!activePool) return;
    setSavingWeights(true);
    try {
      const weights: Record<string, number | null> = {};
      for (const m of members) {
        const draft = (weightDrafts[m.fund_code] ?? "").trim();
        weights[m.fund_code] = draft === "" ? null : Number(draft);
      }
      const res = await api.updatePoolWeights(activePool.id, weights);
      if (res.warnings.length > 0) setError(res.warnings.join("；"));
      await loadMembers(activePool.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存权重失败");
    } finally {
      setSavingWeights(false);
    }
  };

  const handleRunAnalysis = async () => {
    if (!activePool) return;
    setAnalysisRunning(true);
    setError(null);
    try {
      const res = await api.runPortfolioAnalysis(activePool.id);
      if (res.data) {
        setAnalysis(res.data);
      } else {
        setError(res.warnings.join("；") || "组合分析未返回数据");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "运行组合分析失败");
    } finally {
      setAnalysisRunning(false);
    }
  };

  const handleBuildPacket = async () => {
    if (!activePool) return;
    setPacketBuilding(true);
    setError(null);
    try {
      const res = await api.buildPortfolioPacket(activePool.id);
      if (res.data) {
        setPacketInfo(
          `组合研究包已生成：${res.data.packet_id}（模板 ${res.data.template}）`
        );
      } else {
        setError(res.warnings.join("；") || "组合研究包生成失败");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成组合研究包失败");
    } finally {
      setPacketBuilding(false);
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
    weightDraft: weightDrafts[m.fund_code] ?? "",
    onWeightChange: handleWeightChange,
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
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveWeights}
                  disabled={!weightsDirty || savingWeights}
                >
                  {savingWeights ? "保存中…" : "保存权重"}
                </button>
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
          <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
            权重留空 = 观察列表；填入权重（%）即成为组合，分析时自动归一。
          </div>
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
      
      {activePool && members.length > 0 && (
        <div className="fade-up fade-up-4" style={{ marginTop: "var(--space-5)" }}>
          <SectionHeader
            title="组合穿透分析（P4C）"
            subtitle="NAV 加权组合指标 + 风格/行业穿透 + 重仓重叠（披露 vs estimated 隔离）+ 集中度风险"
            actions={
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleRunAnalysis}
                  disabled={analysisRunning}
                >
                  {analysisRunning ? "分析中…" : "运行组合分析"}
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleBuildPacket}
                  disabled={packetBuilding}
                >
                  {packetBuilding ? "生成中…" : "生成组合研究包"}
                </button>
              </div>
            }
          />
          {packetInfo && (
            <div
              className="text-sm"
              style={{
                marginTop: "var(--space-2)",
                padding: "var(--space-2) var(--space-3)",
                background: "var(--accent-subtle)",
                borderRadius: "var(--radius-sm)",
                color: "var(--accent)",
              }}
            >
              {packetInfo}
            </div>
          )}
          {!analysis && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <EmptyState
                icon="◈"
                title="暂无组合分析快照"
                desc="点击「运行组合分析」对当前池成员做穿透分析（无权重视为观察列表，等权口径）"
              />
            </div>
          )}
          {analysis && (
            <PortfolioAnalysisView analysis={analysis} />
          )}
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
