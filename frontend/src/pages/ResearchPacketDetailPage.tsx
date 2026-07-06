// 研究包详情 — 按 packet_id 查看已保存的 Research Packet
// 元信息卡 + 模块置信度网格 + Markdown 预览 + JSON 导出

import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type ResearchPacketDetail } from "../api/client";
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

const TEMPLATE_LABELS: Record<string, string> = {
  single_fund_checkup: "单基金体检",
  manager_profile: "经理画像",
  style_drift: "风格漂移",
  holdings_deep_dive: "持仓深析",
};

const CONFIDENCE_STATUS: Record<string, string> = {
  computed: "computed",
  estimated: "estimated",
  needs_review: "needs_review",
  high: "computed",
  medium: "estimated",
  low: "needs_review",
};

interface ModuleStatus {
  key: string;
  status?: string;
  hasData: boolean;
}

function extractModules(packet: Record<string, unknown>): ModuleStatus[] {
  return Object.keys(packet)
    .filter(
      (k) =>
        k !== "metadata" &&
        k !== "warnings" &&
        k !== "conclusion_map" &&
        typeof packet[k] === "object" &&
        packet[k] !== null,
    )
    .map((k) => {
      const v = packet[k] as Record<string, unknown>;
      return {
        key: k,
        status: v?.conclusion_status as string | undefined,
        hasData: true,
      };
    });
}

export default function ResearchPacketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<ResearchPacketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showMarkdown, setShowMarkdown] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    api
      .getResearchPacketDetail(id)
      .then((resp) => {
        if (resp.data === null) {
          setError(resp.warnings.join("; ") || `研究包 ${id} 不存在`);
          setDetail(null);
          return;
        }
        setDetail(resp.data);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "加载失败"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  const crumbs: BreadcrumbItem[] = [
    { label: "研究包归档", to: "/research-packets" },
    { label: id ?? "" },
  ];

  if (loading) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <LoadingState rows={8} cols={4} />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div>
        <Breadcrumb items={crumbs} />
        <ErrorState title="研究包加载失败" desc={error ?? "无数据"} />
      </div>
    );
  }

  const packet = detail.packet ?? {};
  const modules = extractModules(packet);
  const meta = (packet.metadata as Record<string, unknown>) ?? {};
  const conclusionMap =
    (packet.conclusion_map as Record<string, string>) ?? {};
  const packetWarnings = (packet.warnings as string[]) ?? [];
  const conclusionStatus =
    CONFIDENCE_STATUS[detail.overall_confidence ?? ""] ?? "observation";

  return (
    <div>
      <Breadcrumb items={crumbs} />

      {/* 标题区 */}
      <div
        className="fade-up fade-up-1"
        style={{ marginTop: "var(--space-3)", marginBottom: "var(--space-4)" }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1>研究包详情</h1>
            <StatusBadge status={conclusionStatus} />
            {detail.is_latest && (
              <span
                className="text-xs"
                style={{
                  padding: "2px 8px",
                  borderRadius: "var(--radius-xs)",
                  background: "var(--positive-soft)",
                  color: "var(--positive)",
                  fontWeight: 500,
                }}
              >
                最新
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Link to={`/funds/${detail.fund_code}/packet`}>
              <button className="btn btn-ghost btn-sm">
                重新生成
              </button>
            </Link>
            <ExportButton
              data={packet}
              filename={`research_packet_${detail.fund_code}_${detail.packet_id}.json`}
              label="导出 JSON"
            />
          </div>
        </div>
        <div
          className="text-sm text-tertiary"
          style={{ marginTop: "var(--space-2)" }}
        >
          Packet ID <span className="mono">{detail.packet_id}</span>
          {" · "}
          基金 <span className="mono">{detail.fund_code}</span>
          {" · "}
          模板 {TEMPLATE_LABELS[detail.template] ?? detail.template}
        </div>
      </div>

      {/* 元信息卡 */}
      <div
        className="grid fade-up fade-up-2"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: "var(--space-3)",
          marginBottom: "var(--space-4)",
        }}
      >
        <MetricCard
          label="数据日期"
          value={detail.data_date ?? "—"}
        />
        <MetricCard
          label="生成时间"
          value={
            detail.generated_at
              ? detail.generated_at.slice(0, 16).replace("T", " ")
              : "—"
          }
        />
        <MetricCard
          label="整体置信度"
          value={detail.overall_confidence ?? "—"}
        />
        <MetricCard
          label="平台版本"
          value={detail.platform_version ?? "—"}
        />
        <MetricCard label="模块数" value={modules.length} />
        <MetricCard
          label="待复核模块"
          value={Object.values(conclusionMap).filter(
            (s) => s === "needs_review",
          ).length}
          negative={
            Object.values(conclusionMap).filter(
              (s) => s === "needs_review",
            ).length > 0
          }
        />
      </div>

      {/* 警告 */}
      {packetWarnings.length > 0 && (
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
          {packetWarnings.map((w, i) => (
            <div key={i}>⚠ {w}</div>
          ))}
        </div>
      )}

      {/* 模块置信度网格 */}
      {modules.length > 0 && (
        <div
          className="fade-up fade-up-3"
          style={{ marginBottom: "var(--space-4)" }}
        >
          <SectionHeader
            title="模块结论状态"
            subtitle={`${modules.length} 个模块`}
          />
          <div
            className="grid"
            style={{
              gridTemplateColumns:
                "repeat(auto-fill, minmax(220px, 1fr))",
              gap: "var(--space-2)",
              marginTop: "var(--space-3)",
            }}
          >
            {modules.map((m) => {
              const status = m.status ?? conclusionMap[m.key];
              return (
                <div
                  key={m.key}
                  style={{
                    padding: "var(--space-2) var(--space-3)",
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border-hairline)",
                    borderRadius: "var(--radius-sm)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <span className="text-sm mono">{m.key}</span>
                  <StatusBadge
                    status={CONFIDENCE_STATUS[status ?? ""] ?? "observation"}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Markdown 切换 */}
      {detail.markdown && (
        <div
          className="fade-up fade-up-4"
          style={{ marginBottom: "var(--space-4)" }}
        >
          <SectionHeader
            title="Markdown 输出"
            actions={
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setShowMarkdown(!showMarkdown)}
              >
                {showMarkdown ? "收起" : "展开"}
              </button>
            }
          />
          {showMarkdown && (
            <pre
              className="mono"
              style={{
                marginTop: "var(--space-3)",
                padding: "var(--space-4)",
                background: "var(--surface-sunken)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-hairline)",
                fontSize: "0.78rem",
                lineHeight: 1.5,
                overflow: "auto",
                maxHeight: "60vh",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {detail.markdown}
            </pre>
          )}
        </div>
      )}

      {/* 免责声明 */}
      <div
        className="fade-up fade-up-5"
        style={{
          marginTop: "var(--space-4)",
          marginBottom: "var(--space-4)",
          padding: "var(--space-4)",
          background: "var(--surface-sunken)",
          borderRadius: "var(--radius-md)",
          fontSize: "0.78rem",
          color: "var(--ink-tertiary)",
          fontStyle: "italic",
        }}
      >
        免责声明：本研究包由算法自动生成，所有结论基于公开数据和估算模型，
        仅供个人研究参考，不构成任何投资建议。
        {meta.data_date != null &&
          ` 数据日期 ${String(meta.data_date)}，`}
        可能存在延迟、缺失或错误，请以基金管理人正式公告为准。
      </div>
    </div>
  );
}
