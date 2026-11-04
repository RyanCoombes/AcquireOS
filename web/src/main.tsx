import { StrictMode, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useNavigate, useSearchParams, Link } from "react-router-dom";
import "./styles.css";
import Targets from "./pages/Targets";
import Company from "./pages/Company";
import Pipeline from "./pages/Pipeline";
import Reports from "./pages/Reports";
import Connections from "./pages/Connections";
import BuyBox from "./pages/BuyBox";
import Import from "./pages/Import";

function TopBar() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <header className="top">
      <Link to="/" className="mark"><i />AcquireOS</Link>
      <nav className="tabs">
        <NavLink to="/" end>Targets</NavLink>
        <NavLink to="/pipeline">Pipeline</NavLink>
        <NavLink to="/connections">Connections</NavLink>
        <NavLink to="/reports">Reports</NavLink>
        <NavLink to="/buy-box">Buy box</NavLink>
        <NavLink to="/import">Import</NavLink>
      </nav>
      <form className="search" onSubmit={(e) => {
        e.preventDefault();
        const q = ref.current?.value.trim() ?? "";
        nav(q ? `/?q=${encodeURIComponent(q)}&include_excluded=1` : "/");
        ref.current?.blur();
      }}>
        <input ref={ref} type="search" placeholder="Company name, number or postcode" defaultValue={params.get("q") ?? ""}
               aria-label="Search companies" />
        <span className="kbd" aria-hidden>/</span>
      </form>
    </header>
  );
}

function App() {
  return (
    <BrowserRouter>
      <TopBar />
      <main>
        <Routes>
          <Route path="/" element={<Targets />} />
          <Route path="/c/:num" element={<Company />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/connections" element={<Connections />} />
          <Route path="/connections/:num" element={<Connections />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/buy-box" element={<BuyBox />} />
          <Route path="/import" element={<Import />} />
          <Route path="*" element={<div className="empty"><b>Page not found.</b> <Link to="/">Back to targets</Link></div>} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
