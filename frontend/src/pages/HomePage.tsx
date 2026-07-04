// 首页 — 研究工作台
// 仪表盘数据 + 基金池提醒 + 异常检测 + 市场概览 + 最近研究 + 快捷操作
// 仪表盘接口失败时回退到旧的静态布局

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SectionHeader, MetricCard, LoadingState } from "../components/display";

interface HealthInfo {
  status: string;
  database: string;
  version: string;
}

interface RecentFund {
  code: string;
  name: string;
  ts: number;
}

interface DashboardData {
  today_changes: Record<string, unknown>;
  pool_monitoring: Record<string, unknown>;
  algorithm_alerts: Record<string, unknown>;
  ai_alerts: Record<string, unknown>;
  market_overview: Record<string, unknown>;
  generated_at: string;
  warnings: string[];
}

// ---- 仪表盘数据防御式取值 ----
function asString(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}
function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
function asObject(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}
// 计数：可能是数字或数组（取长度）
function asCount(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (Array.isArray(v)) return v.length;
  return null;
}

function SeverityTag({ severity }: { severity: string }) {
  const s = severity.toLowerCase();
  let color = "var(--ink-tertiary)";
  let bg = "var(--surface-sunken)";
  if (
    s.includes("high") ||
    s.includes("critical") ||
    s === "严重"
  ) {
    color = "var(--negative)";
    bg = "var(--negative-soft)";
  } else if (
    s.includes("medium") ||
    s.includes("warn") ||
    s === "中等"
  ) {
    color = "var(--warning)";
    bg = "var(--warning-soft)";
  } else if (s.includes("low") || s.includes("info") || s === "低") {
    color = "var(--info)";
    bg = "var(--info-soft)";
  }
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: "var(--radius-sm)",
        background: bg,
        color,
        fontSize: "0.7rem",
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        flexShrink: 0,
      }}
    >
      {severity || "提醒"}
    </span>
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [recents, setRecents] = useState<RecentFund[]>([]);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashboardFailed, setDashboardFailed] = useState(false);

  useEffect(() => {
    const loadData = async () => {
      // 健康检查
      try {
        const res = await api.health();
        setHealth(res.data ?? null);
      } catch {
        // 离线也显示页面
      }

      // 仪表盘
      try {
        const res = await api.getDashboard();
        if (res.data) {
          setDashboard({
            today_changes: asObject(res.data.today_changes),
            pool_monitoring: asObject(res.data.pool_monitoring),
            algorithm_alerts: asObject(res.data.algorithm_alerts),
            ai_alerts: asObject(res.data.ai_alerts),
            market_overview: asObject(res.data.market_overview),
            generated_at: res.data.generated_at,
            warnings: res.data.warnings ?? [],
          });
        } else {
          setDashboardFailed(true);
        }
      } catch {
        // 仪表盘不可用时回退到静态布局
        setDashboardFailed(true);
      } finally {
        setLoading(false);
      }
    };
    loadData();

    // 读取最近浏览的基金 (localStorage)
    try {
      const raw = localStorage.getItem("recent_funds");
      if (raw) {
        const parsed: RecentFund[] = JSON.parse(raw);
        setRecents(parsed.slice(0, 5));
      }
    } catch {
      // ignore
    }
  }, []);

  // 仪表盘派生数据
  const todayChanges = dashboard ? asObject(dashboard.today_changes) : {};
  const poolMonitoring = dashboard ? asObject(dashboard.pool_monitoring) : {};
  const algoAlerts = dashboard ? asObject(dashboard.algorithm_alerts) : {};
  const marketOverview = dashboard ? asObject(dashboard.market_overview) : {};

  const gainersCount = asCount(todayChanges.gainers);
  const losersCount = asCount(todayChanges.losers);
  const unreadAlerts = asCount(poolMonitoring.total_unread);
  const anomalyTotal = asCount(algoAlerts.total);

  const recentAlerts = asArray(poolMonitoring.recent).map((a) => asObject(a));
  const recentAnomalies = asArray(algoAlerts.recent).map((a) => asObject(a));
  const byCategory = asObject(marketOverview.by_category);
  const totalFunds = asCount(marketOverview.total_funds);

  const today = new Date().toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div>
      {/* 页面头 */}
      <div className="fade-up fade-up-1 mb-6">
        <h1>研究工作台</h1>
        <div className="text-sm text-tertiary mt-2">
          {today}
          {health && (
            <>
              {" · "}
              数据库 {health.database}
              {" · "}
              版本 {health.version}
            </>
          )}
        </div>
      </div>

      {/* 四宫格数据状态 */}
      <div className="grid grid-4 fade-up fade-up-2 mb-6">
        {dashboard ? (
          <>
            <DataStatusCard
              label="今日上涨"
              value={gainersCount}
              sub="只基金"
              positive
            />
            <DataStatusCard
              label="今日下跌"
              value={losersCount}
              sub="只基金"
              negative
            />
            <DataStatusCard label="未读池提醒" value={unreadAlerts} sub="条" />
            <DataStatusCard label="近期异常" value={anomalyTotal} sub="条" />
          </>
        ) : dashboardFailed ? (
          // 仪表盘失败 → 回退到静态布局
          <>
            <DataStatusCard
              label="基金主表"
              value={loading ? null : "—"}
              sub="条记录"
            />
            <DataStatusCard
              label="净值数据"
              value={loading ? null : "—"}
              sub="条记录"
            />
            <DataStatusCard
              label="持仓数据"
              value={loading ? null : "—"}
              sub="条记录"
            />
            <DataStatusCard
              label="系统状态"
              value={health?.status ?? (loading ? null : "离线")}
              sub={health ? "在线" : "无法连接"}
            />
          </>
        ) : (
          // 仪表盘加载中
          <>
            <DataStatusCard label="今日上涨" value={null} sub="只基金" />
            <DataStatusCard label="今日下跌" value={null} sub="只基金" />
            <DataStatusCard label="未读池提醒" value={null} sub="条" />
            <DataStatusCard label="近期异常" value={null} sub="条" />
          </>
        )}
      </div>

      {/* 市场概览 */}
      {dashboard && (
        <div className="fade-up fade-up-3 mb-6">
          <SectionHeader
            title="市场概览"
            subtitle={`共 ${totalFunds ?? "—"} 只基金`}
          />
          <div
            className="grid"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
              gap: "var(--space-3)",
              marginTop: "var(--space-3)",
            }}
          >
            {Object.entries(byCategory).length === 0 ? (
              <div className="text-sm text-tertiary">暂无分类统计</div>
            ) : (
              Object.entries(byCategory).map(([cat, count]) => (
                <div
                  key={cat}
                  style={{
                    padding: "var(--space-3)",
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border-hairline)",
                    borderRadius: "var(--radius-sm)",
                  }}
                >
                  <div className="text-xs text-tertiary">{cat}</div>
                  <div
                    className="mono"
                    style={{ fontSize: "1.2rem", fontWeight: 600 }}
                  >
                    {asCount(count) ?? "—"}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* 双列：基金池提醒 + 异常检测 */}
      {dashboard && (
        <div className="grid grid-2 fade-up fade-up-3 mb-6">
          {/* 基金池提醒 */}
          <div>
            <SectionHeader
              title="基金池提醒"
              subtitle={`未读 ${unreadAlerts ?? 0} 条`}
            />
            {recentAlerts.length === 0 ? (
              <div className="text-sm text-tertiary">暂无未读提醒</div>
            ) : (
              <div className="flex flex-col gap-2">
                {recentAlerts.slice(0, 5).map((a, i) => (
                  <div
                    key={asString(a.id) || asString(a.alert_id) || i}
                    className="flex items-center justify-between hover-lift"
                    style={{
                      padding: "var(--space-2) var(--space-3)",
                      borderBottom: "1px solid var(--border-hairline)",
                      gap: "var(--space-2)",
                    }}
                  >
                    <div
                      className="flex items-center gap-3"
                      style={{ minWidth: 0 }}
                    >
                      <SeverityTag
                        severity={
                          asString(a.severity) || asString(a.alert_type)
                        }
                      />
                      <span
                        className="text-sm"
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {asString(a.message) ||
                          asString(a.title) ||
                          asString(a.alert_type) ||
                          "提醒"}
                      </span>
                    </div>
                    <span className="text-xs text-tertiary mono">
                      {asString(a.created_at) || asString(a.triggered_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 异常检测 */}
          <div>
            <SectionHeader
              title="异常检测"
              subtitle={`近期 ${anomalyTotal ?? 0} 条`}
            />
            {recentAnomalies.length === 0 ? (
              <div className="text-sm text-tertiary">暂无异常</div>
            ) : (
              <div className="flex flex-col gap-2">
                {recentAnomalies.slice(0, 5).map((a, i) => (
                  <div
                    key={asString(a.id) || asString(a.anomaly_id) || i}
                    className="flex items-center justify-between hover-lift"
                    style={{
                      padding: "var(--space-2) var(--space-3)",
                      borderBottom: "1px solid var(--border-hairline)",
                      gap: "var(--space-2)",
                    }}
                  >
                    <div
                      className="flex items-center gap-3"
                      style={{ minWidth: 0 }}
                    >
                      <SeverityTag severity={asString(a.severity)} />
                      <span className="mono text-sm">
                        {asString(a.fund_code) || "—"}
                      </span>
                      <span
                        className="text-sm"
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {asString(a.rule_name) ||
                          asString(a.description) ||
                          asString(a.message) ||
                          "异常"}
                      </span>
                    </div>
                    <span className="text-xs text-tertiary mono">
                      {asString(a.detected_at) || asString(a.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 双列：待复核 + 最近研究 */}
      <div className="grid grid-2 fade-up fade-up-3">
        {/* 待复核结论 */}
        <div>
          <SectionHeader
            title="待复核结论"
            subtitle="needs_review 状态的结论列表"
          />
          {loading ? (
            <LoadingState rows={3} cols={2} />
          ) : (
            <div className="flex flex-col gap-2">
              <div className="text-sm text-tertiary">
                暂无待复核结论。当算法产生低置信度结果时，会在此处显示。
              </div>
            </div>
          )}
        </div>

        {/* 最近研究 */}
        <div>
          <SectionHeader title="最近研究" subtitle="最近查看的基金" />
          {recents.length === 0 ? (
            <div className="text-sm text-tertiary">
              尚未查看任何基金。使用顶部搜索框开始研究。
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {recents.map((f) => (
                <div
                  key={f.code}
                  className="flex items-center justify-between hover-lift"
                  style={{
                    padding: "var(--space-2) var(--space-3)",
                    cursor: "pointer",
                    borderBottom: "1px solid var(--border-hairline)",
                  }}
                  onClick={() => navigate(`/funds/${f.code}`)}
                >
                  <div className="flex items-center gap-3">
                    <span className="mono text-sm font-semibold">{f.code}</span>
                    <span className="text-sm">{f.name}</span>
                  </div>
                  <span className="text-xs text-tertiary">
                    {new Date(f.ts).toLocaleDateString("zh-CN")}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 快捷操作 */}
      <div className="fade-up fade-up-4 mt-6">
        <SectionHeader title="快捷操作" />
        <div
          className="flex gap-3"
          style={{ flexWrap: "wrap" }}
        >
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/funds")}
          >
            ◇ 筛选基金
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/similar-funds")}
          >
            ⌖ 相似搜索
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/fund-compare")}
          >
            ⇄ 基金对比
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/experiments")}
          >
            △ 实验管理
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/anomalies")}
          >
            ⚠ 异常发现
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/reverse-lookup")}
          >
            ↺ 反选基金
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/templates")}
          >
            ▤ 研究模板
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/data-quality")}
          >
            ◯ 数据质量
          </button>
        </div>
      </div>
    </div>
  );
}

function DataStatusCard({
  label,
  value,
  sub,
  positive,
  negative,
}: {
  label: string;
  value: string | number | null;
  sub: string;
  positive?: boolean;
  negative?: boolean;
}) {
  return (
    <div
      style={{
        padding: "var(--space-4) var(--space-5)",
        background: "var(--surface-raised)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
      }}
    >
      <MetricCard
        label={label}
        value={value}
        sub={sub}
        positive={positive}
        negative={negative}
      />
    </div>
  );
}
