import { lazy, StrictMode, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import "./styles.css";
import "./skin-ledger.css";
import { ACCENTS, applySkin, setSkin, useSkin } from "./skin";

applySkin();  // before the first paint
import { api, type Meta } from "./api";
import Home from "./pages/Home";
import Targets from "./pages/Targets";
import Company from "./pages/Company";
import Pipeline from "./pages/Pipeline";
const Reports = lazy(() => import("./pages/Reports"));  // loaded when first opened
const Connections = lazy(() => import("./pages/Connections"));  // loaded when first opened
const BuyBox = lazy(() => import("./pages/BuyBox"));  // loaded when first opened
const Import = lazy(() => import("./pages/Import"));  // loaded when first opened
import Changes from "./pages/Changes";
import Watching from "./pages/Watching";
const MapPage = lazy(() => import("./pages/MapPage"));  // loaded when first opened
const Connect = lazy(() => import("./pages/Connect"));  // loaded when first opened
import JobBar from "./components/JobBar";
import Review from "./pages/Review";
import Owners from "./pages/Owners";

const ICONS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  companies: "M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M3 21h18M8 8h3M8 12h3M8 16h3",
  targets: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
  pipeline: "M4 5h16M4 12h10M4 19h6",
  changes: "M3 12h4l3-8 4 16 3-8h4",
  watch: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
  connections: "M6 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.7 6.9l8.6 9.2M8 6h8",
  reports: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  buybox: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4",
  import: "M12 3v12M7 10l5 5 5-5M4 21h16",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14",
  review: "M4 4h16v12H4zM8 20h8M12 16v4M8 9l2 2 4-4",
  owners: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
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
  const item = (to: string, icon: string, label: string, count?: number | null, end = false, alert = false) => (
    <NavLink to={to} end={end} className="nav">
      <Icon name={icon} />{label}
      {count ? <span className={alert ? "count alert" : "count"} title={alert ? "Unread changes to your pipeline" : undefined}>
        {count.toLocaleString("en-GB")}</span> : null}
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
      {item(c?.pipeline_new ? "/changes?alerts=1&unread=1" : "/changes", "changes", "Changes", c?.pipeline_new, false, true)}
      {item("/watch", "watch", "Watching")}
      <div className="group">Analyse</div>
      {item("/map", "map", "Map")}
      {item("/owners", "owners", "Owners")}
      {item("/connections", "connections", "Connections")}
      {item("/reports", "reports", "Reports")}
      <div className="group">Set up</div>
      {item("/buy-box", "buybox", "Buy boxes")}
      {item("/import", "import", "Data")}
      {item("/connect", "claude", "Connect AI")}
      <div className="foot">
        {c ? <>{c.companies.toLocaleString("en-GB")} companies</> : " "}
        {c?.last_import ? <div>Updated {new Date(c.last_import).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</div> : null}
        <button className="skin-try" onClick={() => setSkin("ledger")} title="Switch the look. Your data and settings stay the same; switch back any time.">Try the new look →</button>
      </div>
    </nav>
  );
}

// The new look's navigation: five places on a dark rail; the pages inside each show as tabs.
const SECTIONS: { key: string; label: string; icon: string; pages: [string, string][] }[] = [
  { key: "today", label: "Today", icon: "home", pages: [["/", "Today"]] },
  { key: "find", label: "Find", icon: "targets", pages: [["/targets", "Targets"], ["/companies", "All companies"], ["/review", "Review"], ["/map", "Map"], ["/owners", "Owners"], ["/connections", "Connections"]] },
  { key: "deals", label: "Deals", icon: "pipeline", pages: [["/pipeline", "Deals"]] },
  { key: "watching", label: "Watching", icon: "changes", pages: [["/changes", "Changes"], ["/watch", "Watch list"]] },
  { key: "data", label: "Data", icon: "import", pages: [["/import", "Data"], ["/buy-box", "Buy boxes"], ["/reports", "Reports"], ["/connect", "Connect AI"]] },
];
const sectionOf = (path: string) =>
  SECTIONS.find((s) => s.pages.some(([to]) => (to === "/" ? path === "/" : path === to || path.startsWith(to + "/")))) ?? (path.startsWith("/c/") ? SECTIONS[1] : null);

function Rail({ meta }: { meta: Meta | null }) {
  const loc = useLocation();
  const { accent } = useSkin();
  const cur = sectionOf(loc.pathname);
  const c = meta?.counts;
  const badge: Record<string, [number | undefined, boolean]> = { deals: [c?.tracked, false], watching: [c?.pipeline_new, true] };
  return (
    <nav className="rail" aria-label="Main">
      <Link to="/" className="rmark" aria-label="AcquireOS: Today"><svg viewBox="0 0 22 22" aria-hidden><path d="M4 18 11 4l7 14M7.5 13h7" /></svg></Link>
      {SECTIONS.map((s) => {
        const [n, alert] = badge[s.key] ?? [undefined, false];
        return (
          <Link key={s.key} to={s.key === "watching" && c?.pipeline_new ? "/changes?alerts=1&unread=1" : s.pages[0][0]}
                className={`ritem ${cur?.key === s.key ? "on" : ""}`} aria-current={cur?.key === s.key ? "page" : undefined}>
            <Icon name={s.icon} /><span>{s.label}</span>
            {n ? <i className={`rbadge ${alert ? "alert" : ""}`} title={alert ? "Unread changes" : "In your pipeline"}>{n > 99 ? "99+" : n}</i> : null}
          </Link>
        );
      })}
      <div className="rfoot">
        <div className="rdots" role="group" aria-label="Accent colour">
          {ACCENTS.map(([col, name]) => (
            <button key={col} className={`rdot ${accent === col ? "on" : ""}`} style={{ background: col }} aria-label={`${name} accent`}
                    aria-pressed={accent === col} title={`${name} accent`} onClick={() => setSkin("ledger", col)} />
          ))}
        </div>
        <button className="rback" onClick={() => setSkin("classic")}>Old look</button>
      </div>
    </nav>
  );
}

function SubNav({ meta }: { meta: Meta | null }) {
  const loc = useLocation();
  const cur = sectionOf(loc.pathname);
  if (!cur || cur.pages.length < 2) return null;
  const c = meta?.counts;
  const counts: Record<string, number | undefined> = { "/targets": c?.in_scope, "/companies": c?.companies, "/changes": c?.pipeline_new || undefined };
  return (
    <nav className="subnav m-hide" aria-label={cur.label}>
      {cur.pages.map(([to, label]) => (
        <NavLink key={to} to={to}>{label}{counts[to] ? <span className="sn-count">{counts[to]!.toLocaleString("en-GB")}</span> : null}</NavLink>
      ))}
    </nav>
  );
}

/** Phones only: a fixed bottom bar for the main pages, and a sheet with the rest. */
function MobileNav({ meta }: { meta: Meta | null }) {
  const { skin } = useSkin();
  const [more, setMore] = useState(false);
  const loc = useLocation();
  useEffect(() => setMore(false), [loc.pathname]);
  const c = meta?.counts;
  const tab = (to: string, icon: string, label: string, count?: number | null) => (
    <NavLink to={to} className="mtab"><Icon name={icon} /><span>{label}</span>{count ? <i className="mcount">{count > 99 ? "99+" : count}</i> : null}</NavLink>
  );
  const sheetItem = (to: string, icon: string, label: string) => <NavLink to={to} end={to === "/"} className="msheet-item"><Icon name={icon} />{label}</NavLink>;
  return (
    <>
      <nav className="mnav" aria-label="Main (phone)">
        {tab("/targets", "targets", "Targets")}
        {tab("/review", "review", "Review")}
        {tab("/pipeline", "pipeline", "Pipeline")}
        {tab(c?.pipeline_new ? "/changes?alerts=1&unread=1" : "/changes", "changes", "Changes", c?.pipeline_new)}
        <button className={`mtab ${more ? "active" : ""}`} onClick={() => setMore(!more)} aria-expanded={more}>
          <svg viewBox="0 0 24 24" aria-hidden><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg><span>More</span></button>
      </nav>
      {more && <div className="msheet-back" onClick={() => setMore(false)}>
        <div className="msheet" onClick={(e) => e.stopPropagation()}>
          {sheetItem("/", "home", "Home")}{sheetItem("/companies", "companies", "Companies")}{sheetItem("/watch", "watch", "Watching")}
          {sheetItem("/map", "map", "Map")}{sheetItem("/owners", "owners", "Owners")}{sheetItem("/connections", "connections", "Connections")}
          {sheetItem("/reports", "reports", "Reports")}{sheetItem("/buy-box", "buybox", "Buy boxes")}{sheetItem("/import", "import", "Data")}
          {sheetItem("/connect", "claude", "Connect AI")}
          <button className="msheet-item" style={{ border: 0, background: "none", font: "inherit", textAlign: "left" }}
                  onClick={() => setSkin(skin === "ledger" ? "classic" : "ledger")}>
            <Icon name="claude" />{skin === "ledger" ? "Old look" : "Try the new look"}</button>
        </div></div>}
    </>
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
        <input ref={ref} type="search" placeholder="Search by company, number, postcode or owner's name" aria-label="Search companies" />
        <span className="kbd" aria-hidden>/</span>
      </form>
      <div className="right"><JobBar /></div>
    </header>
  );
}

// A fresh page per company: nothing typed or loaded for one carries over to the next.
function CompanyRoute() {
  const { num } = useParams();
  return <Company key={num} />;
}

function App() {
  const { skin } = useSkin();
  const [meta, setMeta] = useState<Meta | null>(null);
  const loc = useLocation();
  useEffect(() => { api.meta().then(setMeta).catch(() => {}); }, [loc.pathname]);
  useEffect(() => {  // pages ask for fresh counts after changing something (e.g. marking changes read)
    const f = () => api.meta().then(setMeta).catch(() => {});
    window.addEventListener("ao:meta", f);
    return () => window.removeEventListener("ao:meta", f);
  }, []);
  useEffect(() => {
    window.scrollTo(0, 0);
    // On phones the menu scrolls sideways: bring the current page into view.
    document.querySelector(".side a.nav.active")?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [loc.pathname]);
  return (
    <div className="shell">
      {skin === "ledger" ? <Rail meta={meta} /> : <Side meta={meta} />}
      <div className="content">
        <TopBar />
        {skin === "ledger" && <SubNav meta={meta} />}
        <main>
          <Suspense fallback={<div className="empty">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/companies" element={<Targets key="directory" mode="directory" />} />
            <Route path="/targets" element={<Targets key="targets" mode="targets" />} />
            <Route path="/review" element={<Review />} />
            <Route path="/c/:num" element={<CompanyRoute />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/changes" element={<Changes />} />
            <Route path="/watch" element={<Watching />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/connections/:num" element={<Connections />} />
            <Route path="/connections/n/:nid" element={<Connections />} />
            <Route path="/owners" element={<Owners />} />
            <Route path="/owners/:pid" element={<Owners />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/connect" element={<Connect />} />
            <Route path="/buy-box" element={<BuyBox />} />
            <Route path="/import" element={<Import />} />
            <Route path="*" element={<div className="empty"><b>Page not found.</b> <Link to="/">Back to home</Link></div>} />
          </Routes>
          </Suspense>
        </main>
      </div>
      <MobileNav meta={meta} />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>,
);
