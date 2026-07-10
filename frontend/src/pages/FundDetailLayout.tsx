// 基金详情布局 — 面包屑 + 标题区 + 分组 TabNav + <Outlet/>
// 所有子页面（持仓/暴露/评分/研究包/校验）都嵌套在此布局内，TabNav 持久可见

import { useEffect, useState } from "react";
import { Outlet, useParams, useLocation, useNavigate } from "react-router-dom";
import { api, type FundProfile } from "../api/client";
import {
  TabNav,
  LoadingState,
  ErrorState,
  type TabItem,
} from "../components/display";

export default function FundDetailLayout() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const [profile, setProfile] = useState<FundProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setError(null);
    api
      .getFundProfile(code)
      .then((res) => setProfile(res.data ?? null))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [code]);

  // 记录最近浏览
  useEffect(() => {
    if (!code || !profile) return;
    try {
      const raw = localStorage.getItem("recent_funds");
      const recents = raw ? JSON.parse(raw) : [];
      const filtered = recents.filter((r: { code: string }) => r.code !== code);
      filtered.unshift({ code, name: profile.short_name ?? code, ts: Date.now() });
      localStorage.setItem("recent_funds", JSON.stringify(filtered.slice(0, 10)));
    } catch {
      // ignore
    }
  }, [code, profile]);

  const tabs: TabItem[] = [
    { key: "overview", label: "概览" },
    { key: "holdings", label: "持仓分析" },
    { key: "exposure", label: "风格与归因" },
    { key: "scoring", label: "评分与实验", badge: "实验" },
    { key: "simulated", label: "模拟持仓", badge: "估算" },
    { key: "attribution", label: "动态归因", badge: "估算" },
    { key: "packet", label: "研究输出" },
    { key: "similar", label: "相似基金" },
    { key: "review", label: "校验" },
  ];

  // 从 URL 推断当前 Tab
  const path = location.pathname;
  let activeTab = "overview";
  if (path.includes("/holdings")) activeTab = "holdings";
  else if (path.includes("/exposure")) activeTab = "exposure";
  else if (path.includes("/scoring")) activeTab = "scoring";
  else if (path.includes("/simulated")) activeTab = "simulated";
  else if (path.includes("/attribution")) activeTab = "attribution";
  else if (path.includes("/packet") || path.includes("/diff")) activeTab = "packet";
  else if (path.includes("/similar")) activeTab = "similar";
  else if (path.includes("/review")) activeTab = "review";

  const handleTabChange = (key: string) => {
    const tabToPath: Record<string, string> = {
      overview: `/funds/${code}`,
      holdings: `/funds/${code}/holdings`,
      exposure: `/funds/${code}/exposure`,
      scoring: `/funds/${code}/scoring`,
      simulated: `/funds/${code}/simulated`,
      attribution: `/funds/${code}/attribution`,
      packet: `/funds/${code}/packet`,
      similar: `/funds/${code}/similar`,
      review: `/funds/${code}/review`,
    };
    navigate(tabToPath[key] ?? `/funds/${code}`);
  };

  if (loading) {
    return (
      <div>
        <LoadingState rows={4} cols={4} />
      </div>
    );
  }

  if (error || !profile) {
    return (
      <ErrorState
        title="基金信息加载失败"
        desc={error ?? "未找到该基金"}
        onRetry={() => navigate("/funds")}
      />
    );
  }

  return (
    <div>
      {/* 基金标题区 */}
      <div className="fade-up fade-up-1 mb-4">
        <div className="flex items-center gap-3">
          <h1 className="mono">{code}</h1>
          <span className="text-lg">{profile.short_name}</span>
          <span className="text-sm text-tertiary">{profile.category}</span>
        </div>
        <div className="text-sm text-tertiary mt-2 flex gap-4 flex-wrap">
          <span>
            管理{" "}
            <span className="mono">
              {profile.scale_history?.[0]?.total_nav != null
                ? Number(profile.scale_history[0].total_nav).toFixed(2) + "亿"
                : "—"}
            </span>
          </span>
          <span>
            成立 <span className="mono">{profile.inception_date ?? "—"}</span>
          </span>
          {profile.managers?.[0] && (
            <span>
              经理 {profile.managers[0].name} · 任职{" "}
              <span className="mono">{profile.managers[0].tenure_days ?? "—"}天</span>
            </span>
          )}
        </div>
      </div>

      {/* 分组 Tab — 在所有子页面中持久可见 */}
      <TabNav tabs={tabs} active={activeTab} onChange={handleTabChange} />

      {/* 子页面内容 */}
      <div className="page-enter">
        <Outlet context={{ fundCode: code, profile }} />
      </div>
    </div>
  );
}
