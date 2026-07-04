// 研究包页 — 结构化研究文档（替代 JSON dump）
// 侧边目录 + 分 section 渲染 + 指标卡 + 证据链 + 导出

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type EvidenceRecord } from "../api/client";
import {
  SectionHeader,
  StatusBadge,
  Breadcrumb,
  MetricCard,
  LoadingState,
  ErrorState,
  ExportButton,
  type BreadcrumbItem,
} from "../components/display";

interface PacketSection {
  key: string;
  label: string;
  data: Record<string, unknown>;
  status?: string;
}

const SECTION_LABELS: Record<string, string> = {
  fund_profile: "基金概况",
  nav_metrics: "净值指标",
  disclosed_holdings: "公开持仓",
  exposure: "风格暴露",
  attribution: "收益归因",
  scoring: "综合评分",
  simulated_holding: "模拟持仓",
  review_status: "评审状态",
  data_quality: "数据质量",
  risk_warnings: "风险提示",
};

export default function ResearchPacketPage() {
  const { code } = useParams<{ code: string }>();
  const [packet, setPacket] = useState<Record<string, unknown> | null>(null);
  const [packetId, setPacketId] = useState<string>("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [conclusionStatus, setConclusionStatus] = useState("computed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setError(null);
    api
      .getResearchPacket(code)
      .then((r) => {
        if (r.data?.packet) {
          setPacket(r.data.packet as Record<string, unknown>);
          setPacketId(r.data?.packet_id ?? "");
        }
        if (r.warnings) setWarnings(r.warnings);
        if (r.evidence) setEvidence(r.evidence);
        if (r.conclusion_status) setConclusionStatus(r.conclusion_status);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [code]);

  const crumbs: BreadcrumbItem[] = [
    { label: "基金筛选", to: "/funds" },
    { label: code ?? "", to: `/funds/${code}` },
    { label: "研究输出" },
  ];

  if (loading) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <LoadingState rows={8} cols={4} />
      </div>
    );
  }

  if (error || !packet) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <ErrorState title="研究包加载失败" desc={error ?? "无数据"} />
      </div>
    );
  }

  const meta = (packet.metadata as Record<string, unknown>) ?? {};
  const sections: PacketSection[] = Object.keys(packet)
    .filter(
      (k) =>
        k !== "metadata" &&
        k !== "warnings" &&
        typeof packet[k] === "object" &&
        packet[k] !== null
    )
    .map((k) => ({
      key: k,
      label: SECTION_LABELS[k] ?? k,
      data: packet[k] as Record<string, unknown>,
      status: (packet[k] as Record<string, unknown>)?.conclusion_status as
        | string
        | undefined,
    }));

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>研究包</h1>
          <div className="flex items-center gap-3">
            <StatusBadge status={conclusionStatus} />
            <ExportButton
              label="导出 MD"
              filename={`research_packet_${code}.md`}
              onExport={async () => {
                const res = await api.exportResearchPacket(code!, "markdown");
                return res.data!;
              }}
            />
            <ExportButton
              data={packet}
              filename={`research_packet_${code}.json`}
              label="导出 JSON"
            />
          </div>
        </div>
        <div className="text-sm text-tertiary mt-2">
          基金 <span className="mono">{code}</span>
          {meta.data_date != null && (
            <>
              {" · "}
              数据日期{" "}
              <span className="mono">{String(meta.data_date)}</span>
            </>
          )}
          {packetId && (
            <>
              {" · "}
              <span className="mono">{packetId}</span>
            </>
          )}
        </div>
      </div>

      {/* 警告 */}
      {warnings.length > 0 && (
        <div
          className="fade-up fade-up-2 mb-4"
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--warning-soft)",
            borderLeft: "3px solid var(--warning)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
            fontSize: "0.82rem",
            color: "var(--warning)",
          }}
        >
          {warnings.map((w, i) => (
            <div key={i}>⚠ {w}</div>
          ))}
        </div>
      )}

      {/* 侧边目录 + 内容区 */}
      <div className="flex gap-6">
        {/* 侧边目录 */}
        <div
          className="fade-up fade-up-2"
          style={{
            width: "160px",
            flexShrink: 0,
            position: "sticky",
            top: "calc(var(--topbar-height) + var(--space-4))",
            alignSelf: "flex-start",
          }}
        >
          <div className="label mb-2">目录</div>
          {sections.map((s) => (
            <a
              key={s.key}
              href={`#${s.key}`}
              style={{
                display: "block",
                padding: "var(--space-1) 0",
                fontSize: "0.8rem",
                color: "var(--ink-tertiary)",
                textDecoration: "none",
                borderLeft: "2px solid transparent",
                paddingLeft: "var(--space-2)",
                marginLeft: "calc(-1 * var(--space-2))",
                transition: "all var(--transition-fast)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "var(--accent)";
                e.currentTarget.style.borderLeftColor = "var(--accent)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--ink-tertiary)";
                e.currentTarget.style.borderLeftColor = "transparent";
              }}
            >
              {s.label}
            </a>
          ))}
          {evidence.length > 0 && (
            <a
              href="#evidence"
              style={{
                display: "block",
                padding: "var(--space-1) 0",
                fontSize: "0.8rem",
                color: "var(--ink-tertiary)",
                textDecoration: "none",
                borderLeft: "2px solid transparent",
                paddingLeft: "var(--space-2)",
                marginLeft: "calc(-1 * var(--space-2))",
              }}
            >
              证据链 ({evidence.length})
            </a>
          )}
        </div>

        {/* 内容区 */}
        <div className="flex-1">
          {sections.map((section, idx) => (
            <PacketSectionView
              key={section.key}
              section={section}
              delay={Math.min(idx + 2, 6)}
            />
          ))}

          {/* 证据链 */}
          {evidence.length > 0 && (
            <div id="evidence" className="fade-up fade-up-6 mt-6">
              <SectionHeader
                title="证据链"
                subtitle={`${evidence.length} 条证据记录`}
              />
              <div className="flex flex-col gap-2">
                {evidence.map((ev, i) => (
                  <EvidenceItem key={i} ev={ev} />
                ))}
              </div>
            </div>
          )}

          {/* 免责声明 */}
          <div
            className="mt-6 mb-4"
            style={{
              padding: "var(--space-4)",
              background: "var(--surface-sunken)",
              borderRadius: "var(--radius-md)",
              fontSize: "0.78rem",
              color: "var(--ink-tertiary)",
              fontStyle: "italic",
            }}
          >
            免责声明：本研究包由算法自动生成，所有结论基于公开数据和估算模型，
            仅供个人研究参考，不构成任何投资建议。数据可能存在延迟、缺失或错误，
            请以基金管理人正式公告为准。
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- PacketSectionView ----

function PacketSectionView({
  section,
  delay,
}: {
  section: PacketSection;
  delay: number;
}) {
  const data = section.data;
  const entries = Object.entries(data).filter(
    ([k]) => k !== "conclusion_status" && k !== "warnings"
  );

  return (
    <div
      id={section.key}
      className={`fade-up fade-up-${delay} mt-6`}
      style={{ scrollMarginTop: "calc(var(--topbar-height) + var(--space-4))" }}
    >
      <SectionHeader
        title={section.label}
        actions={section.status && <StatusBadge status={section.status} />}
      />
      <div className="grid grid-4">
        {entries.map(([key, val]) => (
          <PacketField key={key} label={key} value={val} />
        ))}
      </div>
      {Boolean(data.warnings && Array.isArray(data.warnings)) && (
        <div className="mt-2">
          {(data.warnings as string[]).map((w: string, i: number) => (
            <div key={i} className="text-xs text-warning">
              {"⚠ " + w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PacketField({ label, value }: { label: string; value: unknown }) {
  const displayValue = formatValue(value);
  return (
    <MetricCard
      label={formatLabel(label)}
      value={displayValue}
    />
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (Math.abs(value) < 1 && value !== 0) return value.toFixed(4);
    if (Math.abs(value) >= 100) return value.toFixed(0);
    return value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return `${value.length} 项`;
  if (typeof value === "object") return `${Object.keys(value).length} 字段`;
  return String(value);
}

function formatLabel(key: string): string {
  const labels: Record<string, string> = {
    fund_code: "基金代码",
    short_name: "简称",
    full_name: "全称",
    category: "类型",
    inception_date: "成立日期",
    company_name: "基金公司",
    manager_name: "基金经理",
    total_nav: "总规模",
    nav: "单位净值",
    cumulative_nav: "累计净值",
    total_return: "区间收益",
    annualized_return: "年化收益",
    max_drawdown: "最大回撤",
    sharpe_ratio: "夏普比率",
    volatility: "波动率",
    r_squared: "R²",
    residual: "残差",
    report_date: "报告期",
    concentration_top10: "前十集中度",
    explained_return: "可解释收益",
    residual_pct: "残差占比",
    coverage_rate: "覆盖率",
    total_score: "综合评分",
    percentile_rank: "百分位排名",
  };
  return labels[key] ?? key.replace(/_/g, " ");
}

// ---- EvidenceItem ----

function EvidenceItem({ ev }: { ev: EvidenceRecord }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      style={{
        padding: "var(--space-2) var(--space-3)",
        borderBottom: "1px solid var(--border-hairline)",
        cursor: "pointer",
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xs text-tertiary">{ev.evidence_type}</span>
          <span className="text-sm">{ev.source}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-tertiary mono">{ev.source_level}</span>
          <StatusBadge status={ev.conclusion_status} />
        </div>
      </div>
      {expanded && (
        <div className="expand-enter mt-2">
          {ev.data_summary && (
            <div className="text-sm text-secondary">{ev.data_summary}</div>
          )}
          {ev.date_range && (
            <div className="text-xs text-tertiary mt-1">
              数据范围: <span className="mono">{ev.date_range[0]}</span> →{" "}
              <span className="mono">{ev.date_range[1]}</span>
            </div>
          )}
          <div className="text-xs text-tertiary mt-1">
            证据ID: <span className="mono">{ev.evidence_id}</span>
            {" · "}
            置信度: <span className="mono">{ev.confidence}</span>
          </div>
        </div>
      )}
    </div>
  );
}
