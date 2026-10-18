import { NavLink, Routes, Route, useLocation } from "react-router-dom";
import Overview from "./pages/Overview";
import Companies from "./pages/Companies";
import CompanyDetail from "./pages/CompanyDetail";
import AIChat from "./pages/AIChat";
import Signals from "./pages/Signals";
import Financials from "./pages/Financials";
import Placeholder from "./pages/Placeholder";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/companies", label: "Companies" },
  { to: "/signals", label: "Signals", badge: 6 },
  { to: "/financials", label: "Financials" },
  { to: "/models", label: "Models" },
  { to: "/sources", label: "Sources" },
  { to: "/alerts", label: "Alerts" },
  { to: "/chat", label: "AI Chat" },
];

function crumb(pathname) {
  if (pathname.startsWith("/companies/")) return { root: "COMPANIES", leaf: "DETAIL" };
  if (pathname === "/companies") return { root: "DASHBOARD", leaf: "COMPANIES" };
  if (pathname === "/chat") return { root: "DASHBOARD", leaf: "AI CHAT" };
  if (pathname === "/signals") return { root: "DASHBOARD", leaf: "SIGNALS" };
  if (pathname === "/financials") return { root: "DASHBOARD", leaf: "FINANCIALS" };
  if (pathname === "/") return { root: "DASHBOARD", leaf: "OVERVIEW" };
  const leaf = pathname.replace("/", "").toUpperCase() || "OVERVIEW";
  return { root: "DASHBOARD", leaf };
}

export default function App() {
  const { pathname } = useLocation();
  const c = crumb(pathname);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">V</div>
          <div className="brand-text">
            <strong>VIGILANCE</strong>
            <span>ESG · V4.2.0</span>
          </div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              <span className="label">{item.label}</span>
              {item.badge ? <span className="badge">{item.badge}</span> : null}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="avatar">AN</div>
          <span>
            Lead Analyst
            <br />
            <span style={{ fontSize: 10 }}>CALIBRATED</span>
          </span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="crumbs">
            / {c.root} / <strong>{c.leaf}</strong>
          </div>
          <div className="search">
            <span>⌕</span>
            <input placeholder="Search entities, LEIs, signals, models…" />
          </div>
          <div className="top-actions">
            <span className="pill-live">
              <span className="dot" /> INGESTION_LIVE
            </span>
          </div>
        </header>
        <div className="content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/companies" element={<Companies />} />
            <Route path="/companies/:symbol" element={<CompanyDetail />} />
            <Route path="/chat" element={<AIChat />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/financials" element={<Financials />} />
            <Route path="/models" element={<Placeholder title="Models" />} />
            <Route path="/sources" element={<Placeholder title="Sources" />} />
            <Route path="/alerts" element={<Placeholder title="Alerts" />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
