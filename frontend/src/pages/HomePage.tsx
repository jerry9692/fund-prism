// 首页 — 研究工作台
// 数据状态 + 待复核结论 + 最近研究 + 快捷操作

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

export default function HomePage() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [recents, setRecents] = useState<RecentFund[]>([]);

  useEffect(() => {
    const loadData = async () => {
      try {
        const res = await api.health();
        setHealth(res.data ?? null);
      } catch {
        // 离线也显示页面
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
      </div>

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
          <SectionHeader
            title="最近研究"
            subtitle="最近查看的基金"
          />
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
        <div className="flex gap-3">
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/funds")}
          >
            ◇ 筛选基金
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate("/experiments")}
          >
            △ 实验管理
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
}: {
  label: string;
  value: string | null;
  sub: string;
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
      <MetricCard label={label} value={value} sub={sub} />
    </div>
  );
}
