// 数据质量监控页 — 实时监控面板
// 数据源状态 + 质量检查结果 + 数据源等级分布

import { useEffect, useState } from "react";
import { api } from "../api/client";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  LoadingState,
  ErrorState,
  type BreadcrumbItem,
} from "../components/display";

interface HealthInfo {
  status: string;
  database: string;
  version: string;
}

export default function DataQualityPage() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await api.health();
        setHealth(res.data ?? null);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "无法连接后端");
      } finally {
        setLoading(false);
      }
    };
    check();
    const timer = setInterval(check, 30000);
    return () => clearInterval(timer);
  }, []);

  const crumbs: BreadcrumbItem[] = [{ label: "数据质量" }];

  const isOnline = health?.status === "ok";

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>数据质量监控</h1>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => window.location.reload()}
          >
            重新检查
          </button>
        </div>
        <div className="text-sm text-tertiary mt-2">
          自动刷新间隔 30 秒 · 最后检查{" "}
          <span className="mono">
            {new Date().toLocaleTimeString("zh-CN")}
          </span>
        </div>
      </div>

      {loading ? (
        <LoadingState rows={4} cols={4} />
      ) : error ? (
        <ErrorState title="无法连接后端" desc={error} />
      ) : (
        <>
          {/* 后端状态 */}
          <div className="grid grid-4 fade-up fade-up-2 mb-6">
            <MetricCard
              label="后端状态"
              value={isOnline ? "在线" : "离线"}
              sub={isOnline ? "API 正常响应" : "API 不可达"}
              positive={isOnline}
              negative={!isOnline}
            />
            <MetricCard
              label="数据库"
              value={health?.database ?? "—"}
              sub="DuckDB / SQLite"
            />
            <MetricCard
              label="版本"
              value={health?.version ?? "—"}
              sub="API 版本"
            />
            <MetricCard
              label="检查时间"
              value={new Date().toLocaleTimeString("zh-CN")}
              sub="本次检查"
            />
          </div>

          {/* 后端离线提示 */}
          {!isOnline && (
            <div
              className="fade-up fade-up-3 mb-6"
              style={{
                padding: "var(--space-4) var(--space-5)",
                background: "var(--negative-soft)",
                borderLeft: "3px solid var(--negative)",
                borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
              }}
            >
              <div
                style={{
                  fontWeight: 600,
                  color: "var(--negative)",
                  marginBottom: "var(--space-2)",
                }}
              >
                后端服务未启动
              </div>
              <div className="text-sm text-secondary">
                请在终端运行{" "}
                <code>fund-research serve</code>{" "}
                启动 API 服务后刷新本页。
              </div>
            </div>
          )}

          {/* 数据源状态 */}
          <div className="fade-up fade-up-3 mb-6">
            <SectionHeader
              title="数据源状态"
              subtitle="各数据源的连接状态和覆盖范围"
            />
            <div className="flex flex-col gap-2">
              <DataSourceRow
                name="AKShare"
                level="B"
                desc="开源接口聚合数据"
                status={isOnline ? "active" : "unknown"}
                detail={isOnline ? "已连接" : "待后端启动"}
              />
              <DataSourceRow
                name="官方 PDF"
                level="A"
                desc="基金公司公告 / 巨潮资讯"
                status={isOnline ? "active" : "unknown"}
                detail={isOnline ? "最小闭环" : "待后端启动"}
              />
              <DataSourceRow
                name="本地文件"
                level="LOCAL"
                desc="用户导入的 CSV / Parquet"
                status="unconfigured"
                detail="未配置"
              />
            </div>
          </div>

          {/* 数据源等级说明 */}
          <div className="fade-up fade-up-4 mb-6">
            <SectionHeader
              title="数据源等级"
              subtitle="数据可信度从高到低排列"
            />
            <div className="flex flex-col gap-2">
              <LevelRow level="A" desc="官方披露数据（证监会/交易所/基金公司公告/巨潮 PDF）" />
              <LevelRow level="LOCAL" desc="用户本地数据（CSV/Parquet 等）" />
              <LevelRow level="B" desc="开源接口聚合数据（AKShare）" />
              <LevelRow level="C" desc="网页解析数据（天天基金等公开页面）" />
            </div>
          </div>

          {/* CLI 操作提示 */}
          <div className="fade-up fade-up-5">
            <SectionHeader title="命令行工具" subtitle="数据管理操作" />
            <div
              style={{
                background: "var(--surface-sunken)",
                borderRadius: "var(--radius-md)",
                padding: "var(--space-4)",
                fontFamily: "var(--font-mono)",
                fontSize: "0.82rem",
                lineHeight: 1.8,
                color: "var(--ink-secondary)",
              }}
            >
              <div>
                <span className="text-tertiary"># 初始化数据库</span>
              </div>
              <div>fund-research init</div>
              <div className="mt-2">
                <span className="text-tertiary"># 更新基金数据</span>
              </div>
              <div>fund-research update --fund-code 110011</div>
              <div className="mt-2">
                <span className="text-tertiary"># 数据质量检查</span>
              </div>
              <div>fund-research check-data</div>
              <div className="mt-2">
                <span className="text-tertiary"># 启动 API 服务</span>
              </div>
              <div>fund-research serve</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function DataSourceRow({
  name,
  level,
  desc,
  status,
  detail,
}: {
  name: string;
  level: string;
  desc: string;
  status: "active" | "unknown" | "unconfigured";
  detail: string;
}) {
  const statusCls =
    status === "active"
      ? "status-badge status-badge-fact"
      : status === "unconfigured"
      ? "status-badge status-badge-observation"
      : "status-badge status-badge-needs_review";

  const statusLabel =
    status === "active"
      ? "active"
      : status === "unconfigured"
      ? "observation"
      : "needs_review";

  return (
    <div
      className="flex items-center justify-between"
      style={{
        padding: "var(--space-3) var(--space-4)",
        borderBottom: "1px solid var(--border-hairline)",
      }}
    >
      <div className="flex items-center gap-4">
        <span className="font-medium" style={{ minWidth: "80px" }}>
          {name}
        </span>
        <span
          className="mono text-xs"
          style={{
            background: "var(--surface-sunken)",
            padding: "2px 8px",
            borderRadius: "var(--radius-xs)",
            fontWeight: 600,
          }}
        >
          {level}
        </span>
        <span className="text-sm text-tertiary">{desc}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm text-tertiary">{detail}</span>
        <span className={statusCls}>{statusLabel}</span>
      </div>
    </div>
  );
}

function LevelRow({ level, desc }: { level: string; desc: string }) {
  return (
    <div
      className="flex items-center gap-4"
      style={{
        padding: "var(--space-2) var(--space-3)",
        borderBottom: "1px solid var(--border-hairline)",
      }}
    >
      <span
        className="mono font-semibold"
        style={{
          minWidth: "50px",
          fontSize: "0.85rem",
          color: "var(--accent)",
        }}
      >
        {level}
      </span>
      <span className="text-sm text-secondary">{desc}</span>
    </div>
  );
}
