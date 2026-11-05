import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import "./styles.css";
import { api, type Meta } from "./api";
import Home from "./pages/Home";
import Targets from "./pages/Targets";
import Company from "./pages/Company";
import Pipeline from "./pages/Pipeline";
import Reports from "./pages/Reports";
import Connections from "./pages/Connections";
import BuyBox from "./pages/BuyBox";
import Import from "./pages/Import";
import Changes from "./pages/Changes";
import MapPage from "./pages/MapPage";
import Connect from "./pages/Connect";
import JobBar from "./components/JobBar";
import Review from "./pages/Review";

const ICONS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  companies: "M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M3 21h18M8 8h3M8 12h3M8 16h3",
  targets: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
  pipeline: "M4 5h16M4 12h10M4 19h6",
  changes: "M3 12h4l3-8 4 16 3-8h4",
  connections: "M6 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.7 6.9l8.6 9.2M8 6h8",
  reports: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  buybox: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4",
  import: "M12 3v12M7 10l5 5 5-5M4 21h16",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14",
  review: "M4 4h16v12H4zM8 20h8M12 16v4M8 9l2 2 4-4",
  claude: "M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8",
};

function Icon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden><path d={ICONS[name]} /></svg>;
}

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
      <rect width="26" height="26" rx="7" fill="#0e7c6b" />
      <path d="M7 18.5 11.5 7h3L19 18.5h-3l-1-2.8h-4l-1 2.8zm4.8-5.3h2.4L13 9.8z" fill="#fff" />
    </svg>
  );
}

function Side({ meta }: { meta: Meta | null }) {
  const c = meta?.counts;
  const item = (to: string, icon: string, label: string, count?: number | null, end = false) => (
    <NavLink to={to} end={end} className="nav">
      <Icon name={icon} />{label}
      {count ? <span className="count">{count.toLocaleString("en-GB")}</span> : null}
    </NavLink>
  );
  return (
    <nav className="side" aria-label="Main">
      <Link to="/" className="mark"><Logo /><span>AcquireOS</span></Link>
      {item("/", "home", "Home", null, true)}
      {item("/companies", "companies", "Companies", c?.companies)}
      {item("/targets", "targets", "Targets", c?.in_scope)}
      {item("/review", "review", "Review")}
      {item("/pipeline", "pipeline", "Pipeline", c?.tracked)}
      {item("/changes", "changes", "Changes", c?.changed_30d)}
      <div className="group">Analyse</div>
      {item("/map", "map", "Map")}
      {item("/connections", "connections", "Connections")}
      {item("/reports", "reports", "Reports")}
      <div className="group">Set up</div>
      {item("/buy-box", "buybox", "Buy boxes")}
      {item("/import", "import", "Data")}
      {item("/connect", "claude", "Connect Claude")}
      <div className="foot">
        {c ? <>{c.companies.toLocaleString("en-GB")} companies</> : " "}
        {c?.last_import ? <div>Updated {new Date(c.last_import).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</div> : null}
      </div>
    </nav>
  );
}

function TopBar() {
  const nav = useNavigate();
  const ref = useRef<HTMLInputElement>(null);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName);
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    const onScroll = () => setScrolled(window.scrollY > 4);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("scroll", onScroll); };
  }, []);
  return (
    <header className={`topbar ${scrolled ? "scrolled" : ""}`}>
      <form className="search" role="search" onSubmit={(e) => {
        e.preventDefault();
        const q = ref.current?.value.trim() ?? "";
        nav(q ? `/companies?q=${encodeURIComponent(q)}` : "/companies");
        ref.current?.blur();
      }}>
        <svg viewBox="0 0 24 24" aria-hidden><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input ref={ref} type="search" placeholder="Search companies by name, number or postcode" aria-label="Search companies" />
        <span className="kbd" aria-hidden>/</span>
      </form>
      <div className="right"><JobBar /></div>
    </header>
  );
}

function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const loc = useLocation();
  useEffect(() => { api.meta().then(setMeta).catch(() => {}); }, [loc.pathname]);
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);
  return (
    <div className="shell">
      <Side meta={meta} />
      <div className="content">
        <TopBar />
        <main>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/companies" element={<Targets key="directory" mode="directory" />} />
            <Route path="/targets" element={<Targets key="targets" mode="targets" />} />
            <Route path="/review" element={<Review />} />
            <Route path="/c/:num" element={<Company />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/changes" element={<Changes />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/connections/:num" element={<Connections />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/connect" element={<Connect />} />
            <Route path="/buy-box" element={<BuyBox />} />
            <Route path="/import" element={<Import />} />
            <Route path="*" element={<div className="empty"><b>Page not found.</b> <Link to="/">Back to home</Link></div>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>,
);
