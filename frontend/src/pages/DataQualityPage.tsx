// 数据质量监控页 — 实时监控面板
// 数据库覆盖统计 + 数据新鲜度 + 数据源快照 + 任务日志 + 数据源等级

import { useEffect, useState, useCallback } from "react";
import { api, type QualityDashboard, type QualitySnapshot, type QualityTask } from "../api/client";
import {
  SectionHeader,
  Breadcrumb,
  MetricCard,
  LoadingState,
  ErrorState,
  EmptyState,
  type BreadcrumbItem,
} from "../components/display";

interface HealthInfo {
  status: string;
  database: string;
  version: string;
}

// 表名中文映射
const TABLE_LABELS: Record<string, string> = {
  fund_main: "基金主表",
  fund_nav: "净值数据",
  fund_disclosed_holdings: "持仓数据",
  fund_scale: "规模数据",
  fund_fee: "费率数据",
  holder_structure: "持有人结构",
  stock_daily: "股票行情",
  stock_main: "股票主表",
  fund_manager: "基金经理",
  fund_company: "基金公司",
  style_exposure_result: "风格暴露",
  static_attribution_result: "静态归因",
  research_packet: "研究包",
  evidence: "证据记录",
  data_source_snapshot: "数据源快照",
  task_log: "任务日志",
};

// 关键表(优先展示)
const KEY_TABLES = ["fund_main", "fund_nav", "fund_disclosed_holdings", "stock_daily"];

const FRESHNESS_LABELS: Record<string, string> = {
  fund_nav: "最新净值日期",
  stock_daily: "最新行情日期",
  fund_disclosed_holdings: "最新持仓报告期",
  fund_scale: "最新规模报告期",
};

export default function DataQualityPage() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [dashboard, setDashboard] = useState<QualityDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastCheck, setLastCheck] = useState<Date>(new Date());

  const check = useCallback(async () => {
    try {
      const [healthRes, dashRes] = await Promise.all([
        api.health(),
        api.getQualityDashboard().catch(() => null),
      ]);
      setHealth(healthRes.data ?? null);
      setDashboard(dashRes?.data ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法连接后端");
    } finally {
      setLoading(false);
      setLastCheck(new Date());
    }
  }, []);

  useEffect(() => {
    check();
    const timer = setInterval(check, 30000);
    return () => clearInterval(timer);
  }, [check]);

  const crumbs: BreadcrumbItem[] = [{ label: "数据质量" }];
  const isOnline = health?.status === "ok";

  // 计算覆盖率百分比
  const coveragePct = (counts: Record<string, number>): number => {
    const keyTables = KEY_TABLES.filter((t) => counts[t] !== undefined && counts[t] >= 0);
    if (keyTables.length === 0) return 0;
    const filled = keyTables.filter((t) => counts[t] > 0).length;
    return Math.round((filled / keyTables.length) * 100);
  };

  const fmtCount = (n: number): string => {
    if (n < 0) return "—";
    if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
    return n.toLocaleString("zh-CN");
  };

  const fmtDate = (s: string | null | undefined): string => {
    if (!s) return "—";
    try {
      return new Date(s).toLocaleDateString("zh-CN");
    } catch {
      return s;
    }
  };

  const fmtDateTime = (s: string | null | undefined): string => {
    if (!s) return "—";
    try {
      return new Date(s).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return s;
    }
  };

  return (
    <div>
      <Breadcrumb items={crumbs} />

      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center justify-between">
          <h1>数据质量监控</h1>
          <button className="btn btn-secondary btn-sm" onClick={() => check()}>
            重新检查
          </button>
        </div>
        <div className="text-sm text-tertiary mt-2">
          自动刷新间隔 30 秒 · 最后检查{" "}
          <span className="mono">{lastCheck.toLocaleTimeString("zh-CN")}</span>
        </div>
      </div>

      {loading ? (
        <LoadingState rows={4} cols={4} />
      ) : error ? (
        <ErrorState title="无法连接后端" desc={error} onRetry={() => check()} />
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
              label="数据覆盖率"
              value={dashboard ? `${coveragePct(dashboard.table_counts)}%` : "—"}
              sub="核心表填充比例"
            />
            <MetricCard
              label="版本"
              value={health?.version ?? "—"}
              sub="API 版本"
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
                请在终端运行 <code>fund-research serve</code> 启动 API 服务后刷新本页。
              </div>
            </div>
          )}

          {/* 数据库覆盖统计 */}
          {dashboard && (
            <div className="fade-up fade-up-3 mb-6">
              <SectionHeader
                title="数据库覆盖统计"
                subtitle="各核心数据表的记录数量"
              />
              <div className="grid grid-4" style={{ gap: "var(--space-3)" }}>
                {KEY_TABLES.map((tbl) => {
                  const count = dashboard.table_counts[tbl] ?? -1;
                  const hasData = count > 0;
                  return (
                    <div
                      key={tbl}
                      style={{
                        padding: "var(--space-3) var(--space-4)",
                        background: "var(--surface-raised)",
                        border: `1px solid ${hasData ? "var(--border-hairline)" : "var(--negative)"}`,
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      <div className="text-sm text-tertiary" style={{ marginBottom: "var(--space-1)" }}>
                        {TABLE_LABELS[tbl] ?? tbl}
                      </div>
                      <div
                        className="mono"
                        style={{
                          fontSize: "1.4rem",
                          fontWeight: 600,
                          color: hasData ? "var(--ink-primary)" : "var(--negative)",
                        }}
                      >
                        {fmtCount(count)}
                      </div>
                      <div className="text-xs text-tertiary mono" style={{ marginTop: "var(--space-1)" }}>
                        {tbl}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* 其余表 */}
              <div
                className="mt-3"
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                  gap: "var(--space-2)",
                }}
              >
                {Object.entries(dashboard.table_counts)
                  .filter(([tbl]) => !KEY_TABLES.includes(tbl))
                  .map(([tbl, count]) => (
                    <div
                      key={tbl}
                      className="flex items-center justify-between"
                      style={{
                        padding: "var(--space-2) var(--space-3)",
                        background: "var(--surface-sunken)",
                        borderRadius: "var(--radius-xs)",
                      }}
                    >
                      <span className="text-sm text-secondary">
                        {TABLE_LABELS[tbl] ?? tbl}
                      </span>
                      <span
                        className="mono text-sm"
                        style={{
                          fontWeight: 600,
                          color: count > 0 ? "var(--ink-primary)" : "var(--ink-tertiary)",
                        }}
                      >
                        {fmtCount(count)}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* 数据新鲜度 */}
          {dashboard && (
            <div className="fade-up fade-up-4 mb-6">
              <SectionHeader
                title="数据新鲜度"
                subtitle="各核心数据表的最新日期"
              />
              <div className="flex flex-col gap-2">
                {Object.entries(dashboard.freshness).map(([tbl, date]) => (
                  <div
                    key={tbl}
                    className="flex items-center justify-between"
                    style={{
                      padding: "var(--space-3) var(--space-4)",
                      borderBottom: "1px solid var(--border-hairline)",
                    }}
                  >
                    <span className="font-medium" style={{ minWidth: "140px" }}>
                      {FRESHNESS_LABELS[tbl] ?? tbl}
                    </span>
                    <span className="text-sm text-tertiary mono" style={{ marginRight: "var(--space-3)" }}>
                      {tbl}
                    </span>
                    <span
                      className="mono"
                      style={{
                        fontWeight: 600,
                        color: date ? "var(--ink-primary)" : "var(--negative)",
                      }}
                    >
                      {date ? fmtDate(date) : "无数据"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 数据源快照 */}
          {dashboard && (
            <div className="fade-up fade-up-5 mb-6">
              <SectionHeader
                title="数据源快照"
                subtitle="最近 10 条数据拉取记录"
              />
              {dashboard.recent_snapshots.length === 0 ? (
                <EmptyState
                  icon="📊"
                  title="暂无数据源快照"
                  desc="执行数据更新操作后,拉取记录将显示在此处"
                />
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="data-table" style={{ width: "100%" }}>
                    <thead>
                      <tr>
                        <th>数据源</th>
                        <th>等级</th>
                        <th>实体类型</th>
                        <th>拉取时间</th>
                        <th>记录数</th>
                        <th>覆盖率</th>
                        <th>异常</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard.recent_snapshots.map((s: QualitySnapshot, i: number) => (
                        <tr key={i}>
                          <td className="font-medium">{s.source_name}</td>
                          <td>
                            <span
                              className="mono text-xs"
                              style={{
                                background: "var(--surface-sunken)",
                                padding: "2px 6px",
                                borderRadius: "var(--radius-xs)",
                                fontWeight: 600,
                              }}
                            >
                              {s.source_level ?? "—"}
                            </span>
                          </td>
                          <td className="text-sm text-tertiary">{s.entity_type}</td>
                          <td className="mono text-sm">{fmtDateTime(s.fetch_timestamp)}</td>
                          <td className="mono text-sm">
                            {s.record_count !== null ? fmtCount(s.record_count) : "—"}
                          </td>
                          <td className="mono text-sm">
                            {s.coverage_rate !== null
                              ? `${(s.coverage_rate * 100).toFixed(1)}%`
                              : "—"}
                          </td>
                          <td className="mono text-sm">
                            {s.anomaly_count !== null && s.anomaly_count > 0 ? (
                              <span style={{ color: "var(--negative)" }}>
                                {s.anomaly_count}
                              </span>
                            ) : (
                              <span className="text-tertiary">0</span>
                            )}
                          </td>
                          <td>
                            {s.is_success ? (
                              <span className="status-badge status-badge-fact">成功</span>
                            ) : (
                              <span className="status-badge status-badge-needs_review">
                                失败
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* 任务日志 */}
          {dashboard && (
            <div className="fade-up fade-up-5 mb-6">
              <SectionHeader
                title="任务日志"
                subtitle="最近 10 条任务执行记录"
              />
              {dashboard.recent_tasks.length === 0 ? (
                <EmptyState
                  icon="📋"
                  title="暂无任务日志"
                  desc="执行数据更新或分析任务后,任务记录将显示在此处"
                />
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="data-table" style={{ width: "100%" }}>
                    <thead>
                      <tr>
                        <th>任务类型</th>
                        <th>目标</th>
                        <th>开始时间</th>
                        <th>耗时</th>
                        <th>状态</th>
                        <th>结果摘要</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard.recent_tasks.map((t: QualityTask, i: number) => (
                        <tr key={i}>
                          <td className="font-medium">{t.task_type ?? "—"}</td>
                          <td className="text-sm text-tertiary mono">
                            {t.target_entity ?? "—"}
                          </td>
                          <td className="mono text-sm">{fmtDateTime(t.started_at)}</td>
                          <td className="mono text-sm">
                            {t.duration_ms !== null
                              ? t.duration_ms < 1000
                                ? `${Math.round(t.duration_ms)}ms`
                                : `${(t.duration_ms / 1000).toFixed(1)}s`
                              : "—"}
                          </td>
                          <td>
                            <span
                              className={`status-badge ${
                                t.status === "success" || t.status === "completed"
                                  ? "status-badge-fact"
                                  : t.status === "failed" || t.status === "error"
                                  ? "status-badge-needs_review"
                                  : "status-badge-observation"
                              }`}
                            >
                              {t.status ?? "—"}
                            </span>
                          </td>
                          <td
                            className="text-sm text-secondary"
                            style={{ maxWidth: "300px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            title={t.result_summary ?? t.error_message ?? ""}
                          >
                            {t.result_summary ?? t.error_message ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* 数据源等级说明 */}
          <div className="fade-up fade-up-5 mb-6">
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
                <span className="text-tertiary"># 导入本地文件</span>
              </div>
              <div>fund-research import --source nav.csv --type fund_nav</div>
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
