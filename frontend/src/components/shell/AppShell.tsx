import { useState, useEffect, useRef, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../../api/client";

// ---- 导航配置 ----

interface NavItem {
  to: string;
  label: string;
  icon: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "工作台",
    items: [
      { to: "/", label: "研究工作台", icon: "◈" },
    ],
  },
  {
    label: "基金研究",
    items: [
      { to: "/funds", label: "基金筛选", icon: "◇" },
      { to: "/fund-pool", label: "基金池", icon: "◫" },
      { to: "/fingerprint", label: "指纹管理", icon: "❖" },
      { to: "/similar-funds", label: "相似搜索", icon: "⬡" },
      { to: "/fund-compare", label: "基金对比", icon: "⬢" },
    ],
  },
  {
    label: "发现与反选",
    items: [
      { to: "/anomalies", label: "异常发现", icon: "⚠" },
      { to: "/reverse-lookup", label: "股票反选", icon: "⇄" },
      { to: "/templates", label: "研究模板", icon: "▦" },
      { to: "/research-packets", label: "研究包归档", icon: "▤" },
    ],
  },
  {
    label: "算法实验",
    items: [
      { to: "/experiments", label: "实验管理", icon: "△" },
      { to: "/experiments/p2b-report", label: "验收报告", icon: "▽" },
      { to: "/scoring/backtest", label: "评分回测", icon: "◁" },
    ],
  },
  {
    label: "系统",
    items: [
      { to: "/data-quality", label: "数据质量", icon: "◯" },
      { to: "/evidence", label: "证据链浏览", icon: "⊕" },
      { to: "/api-debug", label: "API 调试", icon: "⚙" },
    ],
  },
];

// 基金详情页子导航
const FUND_CONTEXT_ITEMS: NavItem[] = [
  { to: "", label: "概览", icon: "·" },
  { to: "/holdings", label: "持仓分析", icon: "·" },
  { to: "/exposure", label: "风格与归因", icon: "·" },
  { to: "/scoring", label: "评分与实验", icon: "·" },
  { to: "/packet", label: "研究输出", icon: "·" },
  { to: "/review", label: "校验", icon: "·" },
];

// ---- AppShell ----

export default function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  // 从 URL 提取当前基金代码
  const fundMatch = location.pathname.match(/^\/funds\/(\d+)/);
  const currentFundCode = fundMatch?.[1] ?? null;

  return (
    <div className="app-shell">
      <TopBar />
      <div className="app-body">
        <SideNav
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          currentFundCode={currentFundCode}
          currentPath={location.pathname}
        />
        <div className="app-content">
          <div className="app-content-inner page-enter" key={location.pathname}>
            {children}
          </div>
          <Footer />
        </div>
      </div>
    </div>
  );
}

// ---- 顶栏 ----

function TopBar() {
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
        <span className="topbar-brand-mark" />
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
        <BackendStatus />
      </div>
    </header>
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
                <span className="sidenav-item-icon">{item.icon}</span>
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
                  <span className="sidenav-item-icon">{item.icon}</span>
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
