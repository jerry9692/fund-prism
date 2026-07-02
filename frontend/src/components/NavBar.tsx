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
    <nav className="top-nav">
      <Link to="/" className="nav-brand">
        ◈ Fund Prism
      </Link>
      <div className="nav-links">
        {links.map((l) => (
          <Link
            key={l.to}
            to={l.to}
            className={`nav-link${loc.pathname === l.to || (l.to !== "/" && loc.pathname.startsWith(l.to)) ? " active" : ""}`}
          >
            {l.label}
          </Link>
        ))}
      </div>
      <div className="nav-search">
        <FundSearch />
      </div>
    </nav>
  );
}
