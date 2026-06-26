import { Link, useLocation } from "react-router-dom";
import FundSearch from "./FundSearch";

const links = [
  { to: "/", label: "首页" },
  { to: "/funds", label: "基金筛选" },
  { to: "/experiments", label: "实验管理" },
  { to: "/experiments/p2b-report", label: "验收报告" },
  { to: "/data-quality", label: "数据质量" },
];

export default function NavBar() {
  const loc = useLocation();

  return (
    <nav
      style={{
        display: "flex",
        alignItems: "center",
        gap: 24,
        padding: "12px 24px",
        background: "var(--color-surface)",
        borderBottom: "1px solid var(--color-border)",
      }}
    >
      <Link
        to="/"
        style={{ fontWeight: 700, fontSize: 18, color: "var(--color-primary)" }}
      >
        Fund Prism
      </Link>
      <FundSearch />
      {links.map((l) => (
        <Link
          key={l.to}
          to={l.to}
          style={{
            fontWeight: loc.pathname === l.to ? 600 : 400,
            color: loc.pathname === l.to ? "var(--color-primary)" : "var(--color-text-secondary)",
            fontSize: 14,
          }}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
