import { useState, useEffect, useRef, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api, type DataUpdateStatus } from "../../api/client";
import { NavIcon, type NavIconName } from "./NavIcon";
import { BrandMark } from "./BrandMark";

// ---- 导航配置 ----

interface NavItem {
  to: string;
  label: string;
  icon: NavIconName;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "工作台",
    items: [
      { to: "/", label: "研究工作台", icon: "radar" },
    ],
  },
  {
    label: "基金研究",
    items: [
      { to: "/funds", label: "基金筛选", icon: "filter" },
      { to: "/fund-pool", label: "基金池", icon: "bookmark" },
      { to: "/fingerprint", label: "指纹管理", icon: "fingerprint" },
      { to: "/similar-funds", label: "相似搜索", icon: "similar" },
      { to: "/fund-compare", label: "基金对比", icon: "compare" },
    ],
  },
  {
    label: "发现与反选",
    items: [
      { to: "/anomalies", label: "异常发现", icon: "alert" },
      { to: "/reverse-lookup", label: "股票反选", icon: "reverse" },
      { to: "/templates", label: "研究模板", icon: "grid" },
      { to: "/research-packets", label: "研究包归档", icon: "archive" },
    ],
  },
  {
    label: "算法实验",
    items: [
      { to: "/experiments", label: "实验管理", icon: "flask" },
      { to: "/experiments/p2b-report", label: "验收报告", icon: "certificate" },
      { to: "/scoring/backtest", label: "评分回测", icon: "backtest" },
    ],
  },
  {
    label: "系统",
    items: [
      { to: "/data-quality", label: "数据质量", icon: "shieldCheck" },
      { to: "/evidence", label: "证据链浏览", icon: "link" },
      { to: "/api-debug", label: "API 调试", icon: "terminal" },
    ],
  },
];

// 基金详情页子导航
const FUND_CONTEXT_ITEMS: NavItem[] = [
  { to: "", label: "概览", icon: "info" },
  { to: "/holdings", label: "持仓分析", icon: "pie" },
  { to: "/exposure", label: "风格与归因", icon: "waterfall" },
  { to: "/scoring", label: "评分与实验", icon: "star" },
  { to: "/packet", label: "研究输出", icon: "fileText" },
  { to: "/review", label: "校验", icon: "checkSquare" },
];

// ---- AppShell ----

export default function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  // 从 URL 提取当前基金代码
  const fundMatch = location.pathname.match(/^\/funds\/(\d+)/);
  const currentFundCode = fundMatch?.[1] ?? null;

  // 后台数据更新状态轮询（SWR：先展示旧数据，后台静默更新，完成后自动刷新）
  const [updateInfo, setUpdateInfo] = useState<DataUpdateStatus | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [showRefreshToast, setShowRefreshToast] = useState(false);
  const sawUpdatingRef = useRef(false);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setInterval> | undefined;

    const poll = async () => {
      try {
        const res = await api.getUpdateStatus();
        if (cancelled) return;
        const info = res.data;
        setUpdateInfo(info);

        if (info?.state === "updating") {
          sawUpdatingRef.current = true;
        }

        // 只有在"亲眼见过 updating 状态"后，done/error 才触发刷新
        // （避免页面在更新已完成后打开时触发无意义的 remount）
        if (
          sawUpdatingRef.current &&
          (info?.state === "done" || info?.state === "error")
        ) {
          sawUpdatingRef.current = false;
          if (pollTimer) clearInterval(pollTimer);
          pollTimer = undefined;

          if (info.state === "done") {
            // 先显示"数据已更新"提示，短暂延迟后刷新页面数据
            setShowRefreshToast(true);
            refreshTimerRef.current = setTimeout(() => {
              setShowRefreshToast(false);
              setRefreshNonce((n) => n + 1);
            }, 1200);
          }
        }
      } catch {
        // 静默失败，不影响界面
      }
    };

    poll();
    pollTimer = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      if (pollTimer) clearInterval(pollTimer);
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  return (
    <div className="app-shell">
      <TopBar updateInfo={updateInfo} />
      {showRefreshToast && (
        <div className="update-toast">
          <span className="update-toast-icon">✓</span>
          数据已更新
        </div>
      )}
      <div className="app-body">
        <SideNav
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          currentFundCode={currentFundCode}
          currentPath={location.pathname}
        />
        <div className="app-content">
          <div className="app-content-inner page-enter" key={`${location.pathname}-${refreshNonce}`}>
            {children}
          </div>
          <Footer />
        </div>
      </div>
    </div>
  );
}

// ---- 顶栏 ----

function TopBar({ updateInfo }: { updateInfo: DataUpdateStatus | null }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<
    Array<{ fund_code: string; short_name: string; fund_type: string }>
  >([]);
  const [showResults, setShowResults] = useState(false);
  const navigate = useNavigate();
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // 防抖搜索
  useEffect(() => {
    if (query.length < 1) {
      setResults([]);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchFunds(query, 8);
        setResults(res.data?.funds ?? []);
        setShowResults(true);
      } catch {
        setResults([]);
      }
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowResults(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // 键盘快捷键 /
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        const input = searchRef.current?.querySelector("input");
        input?.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const handleSelect = (code: string) => {
    navigate(`/funds/${code}`);
    setQuery("");
    setShowResults(false);
  };

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <BrandMark size={32} />
        Fund Prism
      </div>
      <div className="topbar-search" ref={searchRef}>
        <span className="topbar-search-icon">⌕</span>
        <input
          type="text"
          placeholder="搜索基金代码或名称…  ( 按 / 快捷聚焦 )"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setShowResults(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && results.length > 0) {
              handleSelect(results[0].fund_code);
            }
            if (e.key === "Escape") {
              setShowResults(false);
            }
          }}
        />
        {showResults && results.length > 0 && (
          <div className="topbar-search-dropdown overlay-enter">
            {results.map((f) => (
              <div
                key={f.fund_code}
                className="topbar-search-item"
                onClick={() => handleSelect(f.fund_code)}
              >
                <span className="mono">{f.fund_code}</span>
                <span>{f.short_name}</span>
                <span className="text-tertiary text-xs">{f.fund_type}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="topbar-spacer" />
      <div className="topbar-actions">
        <DataUpdateIndicator info={updateInfo} />
        <BackendStatus />
      </div>
    </header>
  );
}

// ---- 数据更新指示器 ----
// updating: 顶栏常驻脉冲提示，hover 显示进度详情
// done:     不显示（由 AppShell 中央 toast 提示"数据已更新"）
// error:    显示 6 秒后自动消失

function DataUpdateIndicator({ info }: { info: DataUpdateStatus | null }) {
  const [showError, setShowError] = useState(() => info?.state === "error");

  useEffect(() => {
    if (info?.state === "error") {
      setShowError(true);
      const t = setTimeout(() => setShowError(false), 6000);
      return () => clearTimeout(t);
    }
  }, [info?.state]);

  if (!info) return null;
  if (info.state === "idle" || info.state === "done") return null;
  if (info.state === "error" && !showError) return null;

  const isUpdating = info.state === "updating";
  return (
    <div
      className={`topbar-status topbar-status-${isUpdating ? "checking" : "down"}`}
      title={info.message || undefined}
    >
      <span className={`topbar-status-dot ${isUpdating ? "topbar-status-dot-pulse" : ""}`} />
      {isUpdating ? "数据更新中…" : "更新失败"}
    </div>
  );
}

function BackendStatus() {
  const [status, setStatus] = useState<"ok" | "down" | "checking">("checking");

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        await api.health();
        if (!cancelled) setStatus("ok");
      } catch {
        if (!cancelled) setStatus("down");
      }
    };
    check();
    const timer = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className={`topbar-status topbar-status-${status}`}>
      <span className="topbar-status-dot" />
      {status === "ok" ? "在线" : status === "down" ? "离线" : "检查中"}
    </div>
  );
}

// ---- 侧边栏 ----

function SideNav({
  collapsed,
  onToggle,
  currentFundCode,
  currentPath,
}: {
  collapsed: boolean;
  onToggle: () => void;
  currentFundCode: string | null;
  currentPath: string;
}) {
  return (
    <aside className={`sidenav ${collapsed ? "collapsed" : ""}`}>
      <nav className="sidenav-nav">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="sidenav-group">
            <div className="sidenav-group-label">{group.label}</div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `sidenav-item ${isActive ? "active" : ""}`
                }
                title={collapsed ? item.label : undefined}
              >
                <span className="sidenav-item-icon">
                  <NavIcon name={item.icon} />
                </span>
                <span className="sidenav-item-label">{item.label}</span>
              </NavLink>
            ))}
          </div>
        ))}

        {/* 当前基金上下文 */}
        {currentFundCode && (
          <div className="sidenav-fund-context">
            <div className="sidenav-fund-context-label">当前基金</div>
            <div className="sidenav-fund-code">{currentFundCode}</div>
            {FUND_CONTEXT_ITEMS.map((item) => {
              const to = item.to
                ? `/funds/${currentFundCode}${item.to}`
                : `/funds/${currentFundCode}`;
              const isActive =
                item.to === ""
                  ? currentPath === `/funds/${currentFundCode}`
                  : currentPath === to;
              return (
                <NavLink
                  key={item.to}
                  to={to}
                  end={item.to === ""}
                  className={`sidenav-item ${isActive ? "active" : ""}`}
                  title={collapsed ? item.label : undefined}
                >
                  <span className="sidenav-item-icon">
                    <NavIcon name={item.icon} size={16} />
                  </span>
                  <span className="sidenav-item-label">{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        )}
      </nav>
      <button className="sidenav-toggle" onClick={onToggle}>
        {collapsed ? "›" : "‹"}
      </button>
    </aside>
  );
}

// ---- 底栏 ----

function Footer() {
  return (
    <footer className="app-footer">
      <span className="app-footer-disclaimer">
        算法结果仅用于个人研究，不构成投资建议
      </span>
      <div className="app-footer-meta">
        <span>v0.4</span>
        <span>{new Date().toLocaleDateString("zh-CN")}</span>
      </div>
    </footer>
  );
}
