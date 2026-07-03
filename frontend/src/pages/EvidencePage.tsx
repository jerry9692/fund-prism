// 证据链浏览页 — 调用现有基金 API 并展示响应中嵌入的证据记录
// 由于后端尚无独立 /evidence 端点（P2.5-4 待实现），本页作为证据检视工具，
// 让用户选择基金 + 分析维度，复用现有 APIResponse.evidence 字段。

import { useState } from "react";
import {
  api,
  type APIResponse,
  type EvidenceRecord,
} from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  EmptyState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";
import { DataTable, type Column } from "../components/data/DataTable";

type AnalysisType =
  | "profile"
  | "nav-metrics"
  | "holdings"
  | "exposure"
  | "research-packet"
  | "simulated-holding"
  | "dynamic-attribution"
  | "review-status";

interface AnalysisOption {
  value: AnalysisType;
  label: string;
  desc: string;
}

const ANALYSIS_OPTIONS: AnalysisOption[] = [
  { value: "profile", label: "基金档案", desc: "fund profile" },
  { value: "nav-metrics", label: "净值指标", desc: "nav metrics" },
  { value: "holdings", label: "持仓明细", desc: "disclosed holdings" },
  { value: "exposure", label: "风格暴露", desc: "style exposure" },
  { value: "research-packet", label: "研究包", desc: "research packet" },
  { value: "simulated-holding", label: "模拟持仓", desc: "simulated holding" },
  { value: "dynamic-attribution", label: "动态归因", desc: "dynamic attribution" },
  { value: "review-status", label: "审核状态", desc: "review status" },
];

interface EvidenceRow extends EvidenceRecord {
  id: string;
}

const SOURCE_LEVEL_LABELS: Record<string, string> = {
  A: "A级 (官方披露)",
  B: "B级 (开放API)",
  C: "C级 (网页抓取)",
  LOCAL: "本地文件",
  computed: "算法计算",
};

const COLUMNS: Column<EvidenceRow>[] = [
  {
    key: "evidence_id",
    header: "证据 ID",
    width: "180px",
    render: (row) => <span className="mono text-sm">{row.evidence_id}</span>,
  },
  {
    key: "entity_id",
    header: "实体",
    width: "120px",
    render: (row) => <span className="mono text-sm">{row.entity_id}</span>,
  },
  {
    key: "evidence_type",
    header: "类型",
    width: "140px",
    render: (row) => <span className="text-sm">{row.evidence_type}</span>,
  },
  {
    key: "source",
    header: "来源",
    render: (row) => <span className="text-sm">{row.source}</span>,
  },
  {
    key: "source_level",
    header: "数据源级别",
    width: "130px",
    render: (row) => (
      <span
        className="mono text-sm"
        style={{ color: "var(--ink-secondary)" }}
      >
        {SOURCE_LEVEL_LABELS[row.source_level] ?? row.source_level}
      </span>
    ),
  },
  {
    key: "date_range",
    header: "日期范围",
    width: "180px",
    render: (row) =>
      row.date_range ? (
        <span className="mono text-sm text-tertiary">
          {row.date_range[0]} ~ {row.date_range[1]}
        </span>
      ) : (
        <span className="text-sm text-tertiary">—</span>
      ),
  },
  {
    key: "confidence",
    header: "置信度",
    width: "100px",
    render: (row) => <span className="text-sm">{row.confidence}</span>,
  },
  {
    key: "conclusion_status",
    header: "结论状态",
    width: "110px",
    render: (row) => <StatusBadge status={row.conclusion_status} />,
  },
];

export default function EvidencePage() {
  const [fundCode, setFundCode] = useState("");
  const [analysisType, setAnalysisType] = useState<AnalysisType>("profile");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<APIResponse | null>(null);

  async function handleQuery() {
    if (!fundCode.trim()) {
      setError("请输入基金代码");
      return;
    }
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      let resp: APIResponse;
      switch (analysisType) {
        case "profile":
          resp = await api.getFundProfile(fundCode.trim());
          break;
        case "nav-metrics":
          resp = await api.getNavMetrics(fundCode.trim());
          break;
        case "holdings":
          resp = await api.getHoldings(fundCode.trim());
          break;
        case "exposure":
          resp = await api.getExposure(fundCode.trim());
          break;
        case "research-packet":
          resp = await api.getResearchPacket(fundCode.trim());
          break;
        case "simulated-holding":
          resp = await api.listSimulatedHolding(fundCode.trim());
          break;
        case "dynamic-attribution":
          resp = await api.listDynamicAttribution(fundCode.trim());
          break;
        case "review-status":
          resp = await api.getFundReviewStatus(fundCode.trim());
          break;
      }
      setResponse(resp);
    } catch (e) {
      setError(`查询异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  const evidenceList: EvidenceRow[] = (response?.evidence ?? []).map((e) => ({
    ...e,
    id: e.evidence_id,
  }));

  // 数据源级别分布
  const levelCounts: Record<string, number> = {};
  for (const e of evidenceList) {
    levelCounts[e.source_level] = (levelCounts[e.source_level] ?? 0) + 1;
  }
  const levelDistText = Object.entries(levelCounts)
    .map(([k, v]) => `${SOURCE_LEVEL_LABELS[k] ?? k}×${v}`)
    .join(" · ") || "—";

  const metaKeyCount = response?.metadata
    ? Object.keys(response.metadata).length
    : 0;

  const crumbs: BreadcrumbItem[] = [
    { label: "系统" },
    { label: "证据链浏览" },
  ];

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1" style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}>
        <div className="flex items-center gap-3">
          <h1>证据链浏览</h1>
          <StatusBadge status="computed" />
        </div>
        <div className="text-sm text-tertiary" style={{ marginTop: "var(--space-2)" }}>
          检视各分析接口返回的证据记录（evidence）与结论状态，用于核验结论可信度门禁
        </div>
      </div>

      {/* 说明横幅 */}
      <div
        className="fade-up fade-up-2"
        style={{
          marginBottom: "var(--space-4)",
          padding: "var(--space-3) var(--space-4)",
          background: "var(--surface-sunken)",
          borderLeft: "3px solid var(--ink-tertiary)",
          borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          fontSize: "0.82rem",
          color: "var(--ink-secondary)",
        }}
      >
        ⓘ 后端独立 /evidence 端点尚未实现（P2.5-4）。本页通过复用现有基金分析接口的
        <span className="mono"> evidence </span>字段进行证据检视。
      </div>

      {/* 查询表单 */}
      <form
        className="fade-up fade-up-2"
        style={{
          background: "var(--surface-raised)",
          border: "1px solid var(--border-hairline)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-4)",
          marginBottom: "var(--space-4)",
        }}
        onSubmit={(e) => {
          e.preventDefault();
          handleQuery();
        }}
      >
        <SectionHeader title="查询条件" subtitle="选择基金与分析维度，复用现有 API 拉取证据记录" />
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
            <span>分析维度</span>
            <select
              className="form-input"
              value={analysisType}
              onChange={(e) => setAnalysisType(e.target.value as AnalysisType)}
            >
              {ANALYSIS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label} — {opt.desc}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !fundCode.trim()}
          >
            {loading ? "查询中..." : "查询证据"}
          </button>
        </div>
      </form>

      {/* 错误 */}
      {error && (
        <div className="fade-up fade-up-3" style={{ marginBottom: "var(--space-4)" }}>
          <ErrorState title="查询失败" desc={error} onRetry={() => setError(null)} />
        </div>
      )}

      {/* 加载中 */}
      {loading && (
        <div className="fade-up fade-up-3">
          <LoadingState rows={4} cols={4} />
        </div>
      )}

      {/* 结果 */}
      {!loading && !error && response && (
        <div className="fade-up fade-up-3">
          {/* 指标卡 */}
          <div
            className="grid"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
              gap: "var(--space-3)",
              marginBottom: "var(--space-4)",
            }}
          >
            <MetricCard
              label="证据条数"
              value={evidenceList.length}
              sub={evidenceList.length === 0 ? "本次响应无证据" : "已附证据记录"}
            />
            <MetricCard
              label="结论状态"
              value={response.conclusion_status || "—"}
              sub="response.conclusion_status"
            />
            <MetricCard
              label="警告数"
              value={response.warnings.length}
              negative={response.warnings.length > 0}
            />
            <MetricCard
              label="元数据字段"
              value={metaKeyCount}
              sub="response.metadata"
            />
            <MetricCard label="数据源分布" value={levelDistText} />
          </div>

          {/* 证据表 */}
          <div style={{ marginBottom: "var(--space-4)" }}>
            <SectionHeader
              title="证据记录"
              subtitle={`共 ${evidenceList.length} 条`}
            />
            <div style={{ marginTop: "var(--space-3)" }}>
              {evidenceList.length === 0 ? (
                <EmptyState
                  icon="∅"
                  title="本次响应未附带证据记录"
                  desc="该接口可能未实现证据链回填，或当前基金无可用证据"
                />
              ) : (
                <DataTable
                  columns={COLUMNS}
                  data={evidenceList}
                  rowKey={(row) => row.id}
                  initialSort={{ key: "source_level", order: "asc" }}
                />
              )}
            </div>
          </div>

          {/* 警告 */}
          {response.warnings.length > 0 && (
            <div
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
              <div style={{ fontWeight: 600, marginBottom: "var(--space-1)" }}>
                响应警告 ({response.warnings.length})
              </div>
              <ul style={{ margin: 0, paddingLeft: "var(--space-4)" }}>
                {response.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* 元数据 */}
          {metaKeyCount > 0 && (
            <div
              style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--border-hairline)",
                borderRadius: "var(--radius-md)",
                padding: "var(--space-4)",
              }}
            >
              <SectionHeader title="响应元数据" subtitle="response.metadata" />
              <div
                className="grid"
                style={{
                  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: "var(--space-2)",
                  marginTop: "var(--space-3)",
                }}
              >
                {Object.entries(response.metadata).map(([k, v]) => (
                  <div
                    key={k}
                    style={{
                      padding: "var(--space-2) var(--space-3)",
                      background: "var(--surface-sunken)",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "0.78rem",
                    }}
                  >
                    <div
                      className="mono"
                      style={{ color: "var(--ink-tertiary)", marginBottom: "2px" }}
                    >
                      {k}
                    </div>
                    <div style={{ color: "var(--ink-primary)" }}>
                      {typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 初始空状态 */}
      {!loading && !error && !response && (
        <div className="fade-up fade-up-3">
          <EmptyState
            icon="⌕"
            title="输入基金代码并选择分析维度"
            desc="将调用对应分析接口，展示其响应中的证据链、结论状态与警告"
          />
        </div>
      )}
    </div>
  );
}
