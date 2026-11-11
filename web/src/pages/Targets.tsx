import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Row } from "../api";
import { ErrorLine, Flags, Score, Signals, StatusMark, Toast, useAsync } from "../components/bits";
import { Spark } from "../components/charts";
import SicPicker, { loadSic, type SicOption } from "../components/SicPicker";
import { NOT_NOW, NOT_SUITABLE, pickNote, rememberList, RuleOutMenu } from "../components/RuleOut";
import { PresenceFilter, ActiveChips, FilterGroup, MoneyRange, NumField, NumRange, Select } from "../components/Filters";
import { ageFrom, cap, CHANGE_KIND, date, int, isBadStatus, money, OWNERSHIP, range, relDays, years } from "../format";

const PAGE = 100;
type Mode = "directory" | "targets";
type Col = { key: string; label: string; num?: boolean; sm?: boolean; nosort?: boolean };
// The directory: every company, A to Z, described by what it is.
const DIR_COLS: Col[] = [
  { key: "name", label: "Company" },
  { key: "industry", label: "Industry", sm: true, nosort: true },
  { key: "years", label: "Years", num: true, sm: true },
  { key: "staff", label: "Staff", num: true },
  { key: "revenue", label: "Revenue", num: true, sm: true },
  { key: "age", label: "Owners", sm: true },
  { key: "score", label: "Best fit" },
  { key: "status", label: "My status" },
];
const COLS: Col[] = [
  { key: "score", label: "Score" },
  { key: "name", label: "Company" },
  { key: "staff", label: "Staff", num: true },
  { key: "revenue", label: "Revenue", num: true, sm: true },
  { key: "value", label: "Indicative value", num: true, sm: true },
  { key: "years", label: "Years", num: true, sm: true },
  { key: "age", label: "Owner", num: true },
  { key: "ownership", label: "Ownership", sm: true, nosort: true },
  { key: "status", label: "My status" },
];
// More you can switch on (Columns menu), placed before "My status".
const EXTRA_COLS: Col[] = [
  { key: "profit", label: "Operating profit", num: true, sm: true },
  { key: "ebitda", label: "EBITDA", num: true, sm: true, nosort: true },
  { key: "net_assets", label: "Net assets", num: true, sm: true },
  { key: "cash", label: "Cash", num: true, sm: true },
  { key: "debt", label: "Bank debt", num: true, sm: true, nosort: true },
  { key: "industry", label: "Industry", sm: true, nosort: true },
  { key: "region", label: "Region", sm: true, nosort: true },
  { key: "website", label: "Website", sm: true, nosort: true },
  { key: "changed", label: "Last change", sm: true },
  { key: "next", label: "Next action", sm: true, nosort: true },
];
const allCols = (mode: Mode) => {
  const base = mode === "directory" ? DIR_COLS : COLS;
  const extras = EXTRA_COLS.filter((x) => !base.some((b) => b.key === x.key));
  const i = base.findIndex((c) => c.key === "status");
  return [...base.slice(0, i), ...extras, ...base.slice(i)];
};
const defaultCols = (mode: Mode) => (mode === "directory" ? DIR_COLS : COLS).map((c) => c.key);

// The ways in. Each is just a preset of URL parameters; filters are kept
// when you switch view.
const VIEWS: Record<Mode, { key: string; label: string; params: Record<string, string> }[]> = {
  directory: [
    { key: "all", label: "A to Z", params: {} },
    { key: "changed", label: "Changed recently", params: { changed_days: "30", sort: "changed" } },
    { key: "sold", label: "Recently sold", params: { sold: "only" } },
  ],
  targets: [
    { key: "fit", label: "Best fit first", params: {} },
    { key: "changed", label: "Changed recently", params: { changed_days: "30", sort: "changed" } },
  ],
};
const DEFAULTS: Record<Mode, Record<string, string>> = {
  directory: { sort: "name", dir: "asc" },
  targets: { sort: "score", dir: "desc", in_box: "true", mine: "hide_closed" },
};
const FILTER_KEYS = ["min_revenue", "max_revenue", "min_profit", "max_profit", "min_net_assets", "min_cash", "nation", "presence", "revenue", "sold", "signal", "mine", "accounts_size", "overdue", "charges", "bb", "business_type", "has_website", "q", "min_staff", "max_staff", "min_owner_age", "ownership", "region", "tier", "status", "min_score",
  "company_status", "sic", "min_years", "min_value", "max_value", "changed_days", "change_kind", "flag"];
const MORE_KEYS = ["min_revenue", "max_revenue", "min_profit", "max_profit", "min_net_assets", "min_cash", "nation", "presence", "revenue", "sold", "signal", "overdue", "charges", "business_type", "has_website", "company_status", "sic", "min_years", "min_value", "max_value", "changed_days", "change_kind", "flag"];

export default function Targets({ mode = "targets" }: { mode?: Mode }) {
  const base = mode === "directory" ? "/companies" : "/targets";
  const [params, setParams] = useSearchParams();
  // Older saved searches: "wales=..." is now presence in a nation.
  useEffect(() => {
    if (!params.has("wales")) return;
    const p = new URLSearchParams(params); const w = p.get("wales")!; p.delete("wales");
    p.set("nation", "Wales"); if (w !== "any") p.set("presence", w);
    setParams(p, { replace: true });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  // Filters stay put: opening the list with none (from the menu or a link)
  // brings back the ones you last used here; clearing them clears this too.
  const memKey = `ao.q.${mode}`;
  const pending = useRef<string | null>(null);
  const first = useRef(true);
  if (first.current) {
    first.current = false;
    if (params.toString() === "") { try { pending.current = localStorage.getItem(memKey) || null; } catch { /* ignore */ } }
  }
  useEffect(() => { if (pending.current) setParams(new URLSearchParams(pending.current), { replace: true }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const restoring = pending.current !== null && params.toString() === "";
  useEffect(() => {
    if (restoring) return;
    pending.current = null;
    const p = new URLSearchParams(params); p.delete("page");
    try { localStorage.setItem(memKey, p.toString()); } catch { /* ignore */ }
  }, [params.toString()]); // eslint-disable-line react-hooks/exhaustive-deps
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const saved = useAsync(() => api.searches(), []);
  const query = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const page = Number(query.page ?? 0);
  const apiParams: Record<string, string> = { ...DEFAULTS[mode], ...query, limit: String(PAGE), offset: String(page * PAGE) };
  // A search lists the best matches first unless you pick a column to sort by.
  if (query.q && !query.sort) { apiParams.sort = "relevance"; delete apiParams.dir; }
  delete apiParams.page;
  // Old links and saved searches used include_excluded / in_box=1.
  delete apiParams.include_excluded;
  delete apiParams.list;
  if (apiParams.mine === "all") delete apiParams.mine;
  if (mode === "targets") apiParams.in_box = "true";
  else if (apiParams.in_box === "1") apiParams.in_box = "true";
  // Rows first (fast), the count separately (it can take a moment on millions of rows).
  const list = useAsync(() => restoring ? new Promise<never>(() => {}) : api.companies({ ...apiParams, count: "false" }), [params.toString(), mode]);
  const countParams = Object.fromEntries(Object.entries(apiParams).filter(([k]) => k !== "limit" && k !== "offset"));
  const countQ = useAsync(() => restoring ? new Promise<never>(() => {}) : api.companiesCount(countParams), [params.toString(), mode]);
  const [sics, setSics] = useState<SicOption[]>([]);
  useEffect(() => { if (mode === "directory") loadSic().then(setSics); }, [mode]);
  const [cursor, setCursor] = useState(0);
  // Remembered: whether the filters are shown, and whether "More filters" is open.
  // Phones start folded away so results come first.
  const remembered = (key: string, dflt: boolean) => {
    try { const v = localStorage.getItem(key); return v === null ? dflt : v === "1"; } catch { return dflt; }
  };
  const remember = (key: string, v: boolean) => { try { localStorage.setItem(key, v ? "1" : "0"); } catch { /* ignore */ } };
  // "More filters" always starts closed; the most-used filters stay in view.
  const [more, setMore] = useState(false);
  const [showFilters, setShowState] = useState(() => remembered("ao.filters.shown", typeof window === "undefined" || window.innerWidth > 860));
  const setShowFilters = (v: boolean) => { setShowState(v); remember("ao.filters.shown", v); };
  const [toast, setToast] = useState<string | null>(null);
  // Ticked companies, kept while you page through or change filters.
  const [sel, setSel] = useState<Set<string>>(new Set());
  const toggle = (num: string) => setSel((x) => { const y = new Set(x); if (y.has(num)) y.delete(num); else y.add(num); return y; });
  const bulkStage = async (status: string) => {
    if (!status || !sel.size) return;
    try {
      const r = await api.bulkState({ numbers: [...sel], status, stage_note: "Changed for several companies at once" });
      setToast(`${r.updated} ${r.updated === 1 ? "company" : "companies"} moved to ${m?.statuses.find((x) => x.value === status)?.label ?? status}`);
      setSel(new Set()); list.reload();
    } catch (e: any) { setToast(`Not saved: ${e.message}`); }
  };
  const bulkRuleOut = async (st: "rejected" | "passed", why: string) => {
    try {
      const r = await api.bulkState({ numbers: [...sel], ...pickNote(st, why) });
      setToast(`${r.updated} ruled out: ${why}`);
      setSel(new Set()); list.reload();
    } catch (e: any) { setToast(`Not saved: ${e.message}`); }
  };
  useEffect(() => setCursor(0), [params.toString()]);

  const view = query.changed_days && query.sort === "changed" ? "changed" : mode === "directory" ? "all" : "fit";
  const inBox = mode === "targets" || query.in_box === "1";
  const boxId = query.bb && /^\d+$/.test(query.bb) ? Number(query.bb) : null;
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v === null || v === "") p.delete(k); else p.set(k, v);
    p.delete("page");
    setParams(p, { replace: true });
  };
  // Search as you type: the list updates a moment after you stop typing.
  const [qText, setQText] = useState(query.q ?? "");
  useEffect(() => { setQText(query.q ?? ""); }, [query.q]);
  useEffect(() => {
    if (qText.trim() === (query.q ?? "")) return;
    const t = setTimeout(() => set("q", qText.trim()), 350);
    return () => clearTimeout(t);
  }, [qText]); // eslint-disable-line react-hooks/exhaustive-deps
  const sort = query.sort ?? (query.q ? "relevance" : DEFAULTS[mode].sort);
  const dir = query.dir ?? DEFAULTS[mode].dir;
  const toggleSort = (k: string) => {
    const p = new URLSearchParams(params);
    if (sort === k) p.set("dir", dir === "desc" ? "asc" : "desc");
    else { p.set("sort", k); p.set("dir", k === "name" || k === "years" ? "asc" : "desc"); }
    setParams(p, { replace: true });
  };
  const activeFilters = FILTER_KEYS.filter((k) => params.has(k)).length + (mode === "directory" && params.has("in_box") ? 1 : 0);
  const currentSaved = saved.data?.find((s) => {
    const a = Object.entries(s.params).filter(([k]) => k !== "in_box" && k !== "list").sort().join("&");
    const b = [...params.entries()].filter(([k]) => k !== "page" && k !== "in_box").sort().join("&");
    return a === b && (s.params.list === "targets") === (mode === "targets");
  });

  const rows = list.data?.rows ?? [];
  const focus = query.nation ?? null;
  // Remember this list, so ruling a company out on its page can open the next one.
  useEffect(() => { if (rows.length) rememberList(rows.map((r) => r.company_number), window.location.pathname + window.location.search); }, [list.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const [gone, setGone] = useState<Set<string>>(new Set());
  useEffect(() => setGone(new Set()), [list.data]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, rows.length - 1)); }
      if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
      if (e.key === "Enter" && rows[cursor]) nav(`/c/${rows[cursor].company_number}${query.bb ? `?bb=${query.bb}` : ""}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, nav, query.bb]);
  useEffect(() => { document.querySelector("tr.cursor")?.scrollIntoView({ block: "nearest" }); }, [cursor]);

  const m = meta.data;
  const total = countQ.data?.total ?? 0;
  const capped = !!countQ.data?.capped;
  const [shownCols, setShownCols] = useState<string[]>(() => {
    try { const v = JSON.parse(localStorage.getItem(`ao.cols.${mode}`) ?? "null"); return Array.isArray(v) ? v : defaultCols(mode); } catch { return defaultCols(mode); }
  });
  useEffect(() => {
    try { const v = JSON.parse(localStorage.getItem(`ao.cols.${mode}`) ?? "null"); setShownCols(Array.isArray(v) ? v : defaultCols(mode)); } catch { setShownCols(defaultCols(mode)); }
  }, [mode]);
  const setCols = (v: string[]) => { setShownCols(v); try { localStorage.setItem(`ao.cols.${mode}`, JSON.stringify(v)); } catch { /* ignore */ } };
  const cols = allCols(mode).filter((c) => c.key === "name" || shownCols.includes(c.key));
  const boxName = boxId ? m?.buy_boxes.find((b) => b.id === boxId)?.name : null;
  const empty = m && m.counts.companies === 0;
  // Export exactly the list on screen: same filters and sort (up to 50,000 rows).
  // The same filters on the map (all companies for the directory, buy-box companies for targets).
  const mapHref = "/map?" + new URLSearchParams({
    ...Object.fromEntries(Object.entries({ ...DEFAULTS[mode], ...query }).filter(([k, v]) => v && FILTER_KEYS.includes(k))),
    ...(mode === "directory" ? { include_excluded: "1" } : {}),
  });
  const exportHref = "/api/export.csv?" + new URLSearchParams(
    Object.fromEntries(Object.entries(apiParams).filter(([k]) => k !== "limit" && k !== "offset"))).toString();

  const saveCurrent = async () => {
    const name = window.prompt("Name this search", currentSaved?.name ?? "");
    if (!name) return;
    const p = Object.fromEntries([...params.entries()].filter(([k]) => k !== "page"));
    if (mode === "targets") p.list = "targets";
    await api.saveSearch(name, p);
    saved.reload();
    setToast(`Saved “${name}”`);
  };

  const boxSelect = (
    <div className="field">
      <label htmlFor="f-bb">Buy box</label>
      <select id="f-bb" value={boxId ?? ""} className={boxId ? "set" : ""} onChange={(e) => set("bb", e.target.value)}>
        <option value="">All my buy boxes</option>
        {(m?.buy_boxes ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}{b.scored_at ? "" : " (scoring…)"}</option>)}
      </select>
    </div>
  );
  const fitValue = query.in_box === "1" ? (boxId ? String(boxId) : "any") : "";
  const fitSelect = (
    <div className="field">
      <label htmlFor="f-fit">Fits a buy box</label>
      <select id="f-fit" value={fitValue} className={fitValue ? "set" : ""} onChange={(e) => {
        const p = new URLSearchParams(params);
        p.delete("bb"); p.delete("in_box"); p.delete("page");
        if (e.target.value) { p.set("in_box", "1"); if (e.target.value !== "any") p.set("bb", e.target.value); }
        setParams(p, { replace: true });
      }}>
        <option value="">Not filtered</option>
        <option value="any">Any of my buy boxes</option>
        {(m?.buy_boxes ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
      </select>
    </div>
  );
  const search = (
    <div className="field">
      <label htmlFor="f-q">Search</label>
      <input id="f-q" type="search" value={qText} placeholder="Name, number, postcode or owner" autoComplete="off"
             onChange={(e) => setQText(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") set("q", qText.trim()); }} />
    </div>
  );
  const industryPicker = (w: string | number) => (
    <SicPicker value={(query.sic ?? "").split(",").filter(Boolean)} width={w} placeholder="Industry name or SIC code"
               onChange={(v) => set("sic", v.join(","))} />
  );
  const industry = <div className="field" style={{ minWidth: 300, flex: "1 1 300px" }}><label>Industry</label>{industryPicker("100%")}</div>;
  const region = <Select label="Region" k="region" query={query} set={set} options={(m?.regions ?? []).map((r) => [r, r])} />;
  const companyStatus = <Select label="Company status" k="company_status" query={query} set={set}
                                options={(m?.status_groups ?? []).map((g) => [g.value, g.label] as [string, string])} />;
  const staff = <NumRange label="Staff" lo="min_staff" hi="max_staff" query={query} set={set} />;
  const yearsTrading = <NumField label="Years trading" k="min_years" placeholder="at least" query={query} set={set} />;
  const ownerAge = <NumField label="Owner aged" k="min_owner_age" placeholder="at least" query={query} set={set} />;
  const ownership = <Select label="Ownership" k="ownership" query={query} set={set} options={Object.entries(OWNERSHIP).map(([v, l]) => [v, l])} />;
  const myStatus = <Select label="My status" k="status" query={query} set={set} options={(m?.statuses ?? []).map((x) => [x.value, x.label])} />;
  // What to show by your own decisions. Targets hides not suitable and not now by default.
  const mineDefault = DEFAULTS[mode].mine ?? "all";
  const mineValue = query.mine ?? mineDefault;
  const show = (
    <div className="field">
      <label htmlFor="f-mine">Show</label>
      <select id="f-mine" value={mineValue} className={mineValue !== "all" ? "set" : ""}
              onChange={(e) => set("mine", e.target.value === mineDefault ? null : e.target.value)}>
        <option value="all">Everything</option>
        <option value="hide_closed">Hide not suitable and not now</option>
        <option value="pipeline">Only my pipeline</option>
        <option value="untouched">Only not looked at yet</option>
      </select>
    </div>
  );
  const accountsSize = <Select label="Accounts filed" k="accounts_size" query={query} set={set}
                              options={(m?.account_sizes ?? []).map((g) => [g.value, g.label] as [string, string])} />;
  const overdueSel = <Select label="Overdue filings" k="overdue" query={query} set={set}
                             options={[["any", "Accounts or confirmation"], ["accounts", "Accounts overdue"], ["confirmation", "Confirmation statement overdue"]]} />;
  const chargesSel = <Select label="Charges (secured loans)" k="charges" query={query} set={set}
                             options={[["outstanding", "Has outstanding charges"], ["none", "No outstanding charges"]]} />;
  const score = <NumField label={mode === "directory" ? "Best fit" : "Score"} k="min_score" placeholder="at least" query={query} set={set} />;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>{mode === "directory" ? "Companies" : "Targets"}</h1>
          <div className="lede">
            {m ? (mode === "directory" ? (
              <>
                <b className="ink">{int(m.counts.companies)}</b> UK companies.
              </>
            ) : (
              <>
                <b className="ink">{int(m.counts.in_scope)}</b> open targets in your <Link to="/buy-box">buy boxes</Link>
                {(m.counts as any).in_boxes > m.counts.in_scope ? ` · ${int((m.counts as any).in_boxes - m.counts.in_scope)} ruled out` : ""}
                {" · "}{int(m.counts.tracked)} in your pipeline
              </>
            )) : " "}
          </div>
        </div>
        <div className="right">
          <Link className="btn quiet" to={mapHref}>Show on map</Link>
          <a className="btn m-hide" href={exportHref} title="Download this list, with your filters, as a spreadsheet (up to 50,000 rows)">Export this list</a>
        </div>
      </div>

      {empty ? (
        <div className="empty">
          <b>No companies yet.</b> Load the Companies House data, or your own file, on the{" "}
          <Link to="/import">Data</Link> page.
        </div>
      ) : (
        <>
          <div className="views">
            <nav className="viewtabs" aria-label="Views">
              {VIEWS[mode].map((v) => (
                <button key={v.key} className={view === v.key && !currentSaved ? "on" : ""}
                        onClick={() => {
                          const p = new URLSearchParams(params);
                          for (const k of ["sort", "dir", "changed_days", "page"]) p.delete(k);
                          for (const [k, val] of Object.entries(v.params)) p.set(k, val);
                          setParams(p, { replace: true });
                        }}>{v.label}</button>
              ))}
            </nav>
            {saved.data && saved.data.length > 0 && (
              <div className="saved">
                <span className="faint">Saved:</span>
                {saved.data.map((s) => {
                  const p = { ...s.params };
                  // Searches saved before buy boxes became filters: pin them to their box.
                  if (!p.bb && s.buy_box_id) { p.bb = String(s.buy_box_id); if (p.include_excluded !== "1") p.in_box = "1"; }
                  delete p.include_excluded;
                  const legacy = !p.list && (p.in_box === "1");
                  const target = p.list === "targets" || legacy ? "/targets" : "/companies";
                  delete p.list;
                  if (target === "/targets") delete p.in_box;
                  return (
                  <span key={s.id} className={`savedlink ${currentSaved?.id === s.id ? "on" : ""}`} title={s.buy_box_name ? `Buy box: ${s.buy_box_name}` : ""}>
                    <button onClick={() => target === base ? setParams(new URLSearchParams(p), { replace: true }) : nav(`${target}?${new URLSearchParams(p)}`)}>
                      {s.name}{s.buy_box_name ? <span className="faint"> · {s.buy_box_name}</span> : null}</button>
                    <button className="x" title={`Delete “${s.name}”`} aria-label={`Delete saved search ${s.name}`}
                            onClick={async () => { if (confirm(`Delete saved search “${s.name}”?`)) { await api.deleteSearch(s.id); saved.reload(); } }}>×</button>
                  </span>
                  );
                })}
              </div>
            )}
          </div>

          {!showFilters && (
            <div className="filterbar">
              <button className="btn" onClick={() => setShowFilters(true)} aria-expanded={false}>
                ▸ Filters{activeFilters ? ` (${activeFilters})` : ""}</button>
              <ActiveChips query={query} keys={FILTER_KEYS} set={set} meta={m} />
              <span className="band-actions">
                {activeFilters > 0 && <button className="btn quiet" onClick={() => setParams(new URLSearchParams(VIEWS[mode].find((v) => v.key === view)?.params ?? {}), { replace: true })}>Clear</button>}
                <button className="btn" onClick={saveCurrent}>{currentSaved ? "Update saved search" : "Save search"}</button>
              </span>
            </div>
          )}
          <div className={`band ${showFilters ? "" : "hidden"}`}>
            <button className="btn quiet filters-hide" onClick={() => setShowFilters(false)} aria-expanded title="Fold the filters away to one line">
              ▾ Hide filters</button>
            {mode === "targets" && boxSelect}
            {search}
            {mode === "directory" ? <>{companyStatus}{industry}{region}{staff}{yearsTrading}{accountsSize}{show}</>
              : <>{show}{staff}{ownerAge}{ownership}{region}{myStatus}{score}</>}
            <button className="btn quiet" onClick={() => setMore(!more)} aria-expanded={more}>
              {more ? "Fewer filters" : `More filters${MORE_KEYS.filter((k) => params.has(k)).length ? ` (${MORE_KEYS.filter((k) => params.has(k)).length} set)` : ""}`}</button>
            <div className="band-actions">
              {activeFilters > 0 && <button className="btn quiet" onClick={() => setParams(new URLSearchParams(VIEWS[mode].find((v) => v.key === view)?.params ?? {}), { replace: true })}>Clear</button>}
              <button className="btn" onClick={saveCurrent}>{currentSaved ? "Update saved search" : "Save search"}</button>
            </div>
            {more && (
              <div className="band-more grouped">
                <FilterGroup title="Money" icon="£" query={query} keys={["min_revenue", "max_revenue", "revenue", "min_profit", "max_profit", "min_net_assets", "min_cash", "min_value", "max_value", ...(mode === "targets" ? ["accounts_size"] : [])]}>
                  <MoneyRange label="Revenue" lo="min_revenue" hi="max_revenue" query={query} set={set} hint="filed or estimate" />
                  <Select label="Revenue source" k="revenue" query={query} set={set} options={[["filed", "Filed (confirmed in the accounts)"], ["estimated", "Estimate"], ["none", "No revenue figure"]]} />
                  <MoneyRange label="Operating profit" lo="min_profit" hi="max_profit" query={query} set={set} hint="latest filed accounts" />
                  <MoneyRange label="Net assets" lo="min_net_assets" query={query} set={set} />
                  <MoneyRange label="Cash" lo="min_cash" query={query} set={set} />
                  <MoneyRange label="Indicative value" lo="min_value" hi="max_value" query={query} set={set} />
                  {mode === "targets" && accountsSize}
                </FilterGroup>
                <FilterGroup title="Owners and sale signals" icon="●" query={query}
                             keys={["sold", "signal", "flag", ...(mode === "directory" ? ["ownership", "min_owner_age"] : [])]}>
                  {mode === "directory" && <>{ownership}{ownerAge}</>}
                  <Select label="Recently sold" k="sold" query={query} set={set}
                          options={[["hide", "Hide companies sold in the last 3 years"], ["only", "Only companies sold in the last 3 years"]]} />
                  <Select label="Other signals" k="signal" query={query} set={set}
                          options={[["possible_buyer", "Possible buyers (taking over others)"], ["many_shareholders", "10 or more shareholders"]]} />
                  <Select label="Ownership flag" k="flag" query={query} set={set} options={[
                    ["recent_change", "Recent ownership change"], ["via_holdco", "Owned via holdco"], ["foreign_parent", "Foreign parent"],
                    ["investor", "Investor"], ["trust", "Trust"], ["eot", "EOT"], ["ch_default", "CH default address"],
                    ["formation_agent", "Formation-agent address"], ["mass_address", "Shared address"],
                  ]} />
                </FilterGroup>
                <FilterGroup title="Location" icon="⌖" query={query} keys={["nation", "presence"]}>
                  <PresenceFilter query={query} set={set} />
                </FilterGroup>
                <FilterGroup title="Company" icon="▤" query={query}
                             keys={["overdue", "charges", "business_type", "has_website", "tier", ...(mode === "targets" ? ["company_status", "sic", "min_years"] : [])]}>
                  {mode === "targets" && <>{companyStatus}{yearsTrading}</>}
                  {overdueSel}{chargesSel}
                  <Select label="Business type" k="business_type" query={query} set={set} options={[
                    ["software", "Software"], ["saas", "SaaS"], ["data", "Data"], ["msp", "Managed service provider"],
                    ["it_consultancy", "IT consultancy"], ["field_service", "Field service"], ["agency", "Agency"], ["reseller", "Reseller"], ["other", "Other"],
                  ]} />
                  <Select label="Website" k="has_website" query={query} set={set} options={[["true", "Found"], ["false", "Not found yet"]]} />
                  <Select label="Review tier" k="tier" query={query} set={set} options={(m?.tiers ?? []).map((t) => [t, t])} />
                  {mode === "targets" && industry}
                </FilterGroup>
                <FilterGroup title={mode === "directory" ? "Fit and your work" : "Changes"} icon="↻" query={query}
                             keys={["changed_days", "change_kind", ...(mode === "directory" ? ["bb", "min_score", "status"] : [])]}>
                  {mode === "directory" && <>{fitSelect}{score}{myStatus}</>}
                  <Select label="Changed in" k="changed_days" query={query} set={set}
                          options={[["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last year"]]} />
                  <Select label="Change type" k="change_kind" query={query} set={set} options={Object.entries(CHANGE_KIND)} />
                </FilterGroup>
              </div>
            )}
          </div>

          {(m?.buy_boxes ?? []).some((b) => !b.scored_at) && (
            <div className="callout">
              <b>Scores are being updated.</b> {m!.buy_boxes.filter((b) => !b.scored_at).map((b) => b.name).join(", ")}{" "}
              changed and {m!.buy_boxes.filter((b) => !b.scored_at).length === 1 ? "is" : "are"} waiting to be rescored
              (after any data refresh that is running). Until then this list shows the previous scores.
            </div>
          )}
          <ErrorLine error={list.error} />
          <div className="resultline">
            <span>{!list.data ? "Loading…" : !countQ.data ? "Counting…" : <><b>{int(total)}{capped ? "+" : ""}</b> {total === 1 ? "company" : "companies"}</>}
              {inBox ? (boxName ? <> in <b>{boxName}</b></> : " in at least one buy box") : ""}</span>
            <span className="faint">
              {list.data?.search_limited ? "Lots of companies match that; showing the first 5,000. Type more to narrow it down. "
                : capped ? "Counting stops at 100,000; add a filter to narrow it down. " : ""}
              {mode === "directory" ? (boxName ? `Best fit is the score in ${boxName}.` : "Best fit is each company's highest score across your buy boxes, where it is in one.")
                : boxName ? "Scores are from this buy box." : "Each company's best score across your buy boxes (hover a score for the box)."}
              {" "}<span className="fig-est" style={{ cursor: "default" }}>Amber underlined</span> = estimate.
            </span>
          </div>
          <div className="m-hide"><ColumnPicker mode={mode} shown={shownCols} onChange={setCols} /></div>
          {sel.size > 0 && (
            <div className="selbar" role="region" aria-label="Ticked companies">
              <b>{int(sel.size)} ticked</b>
              <select value="" onChange={(e) => bulkStage(e.target.value)} aria-label="Move ticked companies to a stage">
                <option value="">Move to stage…</option>
                {(m?.statuses ?? []).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
              </select>
              <select value="" onChange={(e) => { const [st, why] = e.target.value.split("|"); if (st) bulkRuleOut(st as "rejected" | "passed", why); }} aria-label="Rule out ticked companies">
                <option value="">Rule out…</option>
                <optgroup label="Not suitable">{NOT_SUITABLE.map((w) => <option key={w} value={`rejected|${w}`}>{w}</option>)}</optgroup>
                <optgroup label="Not now">{NOT_NOW.map((w) => <option key={w} value={`passed|${w}`}>{w}</option>)}</optgroup>
              </select>
              <a className="btn" href={"/api/export.csv?numbers=" + encodeURIComponent([...sel].join(","))}>Export ticked</a>
              <button className="btn quiet" onClick={() => setSel(new Set())}>Clear</button>
            </div>
          )}
          <table className="list">
            <thead>
              <tr>
                <th className="tick"><input type="checkbox" aria-label="Tick every company on this page"
                  checked={rows.length > 0 && rows.every((r) => sel.has(r.company_number))}
                  onChange={(e) => setSel((x) => { const y = new Set(x); rows.forEach((r) => e.target.checked ? y.add(r.company_number) : y.delete(r.company_number)); return y; })} /></th>
                {cols.map((c) => (
                  <th key={c.key} className={`${c.nosort ? "" : "sortable"} ${c.num ? "num" : ""} ${c.sm ? "hide-sm" : ""}`}
                      onClick={() => !c.nosort && toggleSort(c.key)} aria-sort={sort === c.key ? (dir === "asc" ? "ascending" : "descending") : undefined}>
                    {c.label}
                    {sort === c.key && <span className="arrow">{dir === "asc" ? "↑" : "↓"}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.filter((r) => !gone.has(r.company_number)).map((r, i) => <TargetRow key={r.company_number} cols={cols.map((c) => c.key)}
                                             focus={focus} onRuledOut={(msg) => { setToast(msg); setGone((g) => new Set(g).add(r.company_number)); }} r={r} cursor={i === cursor} ticked={sel.has(r.company_number)} onTick={() => toggle(r.company_number)} showBox={!boxId} mode={mode} sics={sics} dim={!!boxId && !!r.excluded}
                                             href={`/c/${r.company_number}${boxId ? `?bb=${boxId}` : ""}`}
                                             onOpen={() => nav(`/c/${r.company_number}${boxId ? `?bb=${boxId}` : ""}`)} />)}
            </tbody>
          </table>
          {!list.loading && rows.length === 0 && <div className="empty"><b>Nothing matches.</b> Try clearing some filters{mode === "targets" ? <>, or <Link to="/companies">browse all companies</Link></> : null}.</div>}
          <div className="pager">
            <span>{rows.length ? `${int(page * PAGE + 1)}–${int(page * PAGE + rows.length)} of ${int(total)}${capped ? "+" : ""}` : ""}</span>
            <button className="btn" disabled={page === 0} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page - 1)); setParams(p); }}>Previous</button>
            <button className="btn" disabled={!countQ.data || capped ? rows.length < PAGE : (page + 1) * PAGE >= total} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page + 1)); setParams(p); }}>Next</button>
            <span className="faint small hide-sm" style={{ marginLeft: "auto" }}>
              <span className="kbd">/</span> search · <span className="kbd">j</span> <span className="kbd">k</span> move · <span className="kbd">Enter</span> open
            </span>
          </div>
        </>
      )}
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

function TargetRow({ r, cols, cursor, onOpen, showBox, mode, sics, dim, href, ticked, onTick, onRuledOut, focus }: {
  r: Row; cols: string[]; cursor: boolean; onOpen: () => void; showBox: boolean; mode: Mode; sics: SicOption[]; dim: boolean; href: string;
  ticked: boolean; onTick: () => void; onRuledOut: (msg: string) => void; focus: string | null;
}) {
  const closed = r.status === "rejected" || r.status === "passed";
  const xBtn = !closed ? <RuleOutMenu num={r.company_number} name={r.name} onDone={onRuledOut} /> : null;
  const tick = (
    <td className="tick" onClick={(e) => e.stopPropagation()}>
      <input type="checkbox" checked={ticked} onChange={onTick} aria-label={`Tick ${r.name}`} />
    </td>
  );
  const age = ageFrom(r.oldest_birth_year);
  const bad = isBadStatus(r.company_status);
  const recent = r.last_change && Date.now() - new Date(r.last_change).getTime() < 30 * 864e5;
  const scoreCell = (
    <td className="c-score" title={showBox && r.box_name ? (r.boxes && r.boxes.length > 1 ? `In ${r.boxes.length} buy boxes: ${r.boxes.join(", ")}` : `Buy box: ${r.box_name}`) : undefined}>
      {r.score !== null && !dim ? <Score value={r.score} coverage={r.coverage} /> : <span className="faint">—</span>}
    </td>
  );
  const nameCell = (
    <td className="c-name">
      <div className="name">
        <Link className="rowlink" to={href} onClick={(e) => e.stopPropagation()}>{r.name}</Link>
        {bad && <span className="tag red">{cap(r.company_status)}</span>}
        {recent && r.last_kinds?.length ? <span className="tag" title={`Changed ${relDays(r.last_change)}`}>{r.last_kinds.map((k) => CHANGE_KIND[k] ?? k).join(", ")}</span> : null}
        <Signals s={r.signals} region={r.region} focus={focus}
                 titles={r.sold_to ? { recently_sold: `Sold${r.sold_on ? ` ${date(r.sold_on)}` : ""} to ${r.sold_to}` } : undefined} />
        {r.same_business?.length ? <Link className="sig grey" to={`/c/${r.same_business[0]}`} onClick={(e) => e.stopPropagation()}
          title="Same owner and address, or a director in common at the same postcode">
          Linked to {r.same_business.length === 1 ? "1 other" : `${r.same_business.length} others`}</Link> : null}
      </div>
      <div className="sub">
        {r.company_number}
        {r.postcode ? ` · ${r.postcode}` : ""}
        {r.trading_region && r.trading_region !== r.region ? ` · trades in ${r.trading_region}` : r.region ? ` · ${r.region}` : ""}
        {dim && r.exclusion ? <span className="flag red">{r.exclusion}</span> : null}
        {r.matched_owner ? <span className="flag" title="Matched by owner's name">owner: {r.matched_owner}</span> : null}
        {r.accounts_overdue ? <span className="flag red">accounts overdue</span> : r.confirmation_overdue ? <span className="flag red">confirmation overdue</span> : null}
        {r.charges_outstanding ? <span className="flag">{r.charges_outstanding} charge{r.charges_outstanding === 1 ? "" : "s"}</span> : null}
        {" "}<Flags flags={r.flags} address={r.address_flag} />
      </div>
      {/* Phones: the key figures on one line under the name (the columns are hidden there) */}
      <div className="m-only m-facts">
        {r.employees != null ? <span><b>{int(r.employees)}</b> staff</span> : null}
        {r.revenue_low != null ? <span><Fig v={range(r.revenue_low, r.revenue_high)} est={r.revenue_basis !== "filed"} /></span> : null}
        {r.value_low != null ? <span>value <Fig v={range(r.value_low, r.value_high)} est={r.value_basis !== "filed"} /></span> : null}
        {age ? <span>owner {age}</span> : null}
      </div>
    </td>
  );
  const staffCell = <td className="num"><div className="staffcell"><Spark values={r.staff_trend} w={48} h={16} />{int(r.employees)}</div></td>;
  // Filed figures plain; anything else (estimate, your file, own margin) amber and underlined.
  const revenueCell = (
    <td className="num hide-sm">
      <Fig v={range(r.revenue_low, r.revenue_high)} est={r.revenue_low != null && r.revenue_basis !== "filed"}
           title={r.revenue_basis === "filed" ? `Filed${r.revenue_method ? `: ${r.revenue_method}` : ""}` : r.revenue_method ?? "Estimate"} />
    </td>
  );
  const statusCell = (
    <td>
      <div className="statuscell">
        <span><StatusMark s={r.status} />{r.rating ? <span className="faint"> · {r.rating}/5</span> : null}</span>
        {xBtn}
      </div>
    </td>
  );
  const code = r.sic_codes?.[0];
  const label = code ? sics.find((o) => o.code === code)?.description : null;
  const ownerCell = mode === "directory" ? (
    <td className="hide-sm nowrap">
      {r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}
      {age ? <div className="sub">oldest owner {age}</div> : null}
    </td>) : <td className="num">{age ?? "—"}</td>;
  const moneyCell = (v: string | number | null | undefined, sub?: string) => (
    <td className={`num hide-sm ${v != null && Number(v) < 0 ? "neg" : ""}`}>{v == null ? "—" : money(v)}{sub ? <div className="sub">{sub}</div> : null}</td>);
  const ebitda = r.operating_profit != null && r.da != null && Number(r.da) > 0 ? Number(r.operating_profit) + Number(r.da) : null;
  const cells: Record<string, React.ReactNode> = {
    score: scoreCell,
    name: nameCell,
    industry: (
      <td className="hide-sm industry">
        {code ? <><div className="clamp">{label ?? code}</div>
          <div className="sub">{code}{r.sic_codes.length > 1 ? ` +${r.sic_codes.length - 1} more` : ""}</div></> : <span className="faint">Not given</span>}
      </td>),
    years: <td className="num hide-sm">{years(r.incorporation_date)}</td>,
    staff: staffCell,
    revenue: revenueCell,
    value: (
      <td className="num hide-sm">
        <Fig v={range(r.value_low, r.value_high)} est={!!r.value_low && r.value_basis !== "filed"}
             title={r.value_basis === "filed" ? "From profit in the filed accounts" : r.value_basis === "filed_margin" ? "Estimate: revenue × the company's own margin from its last accounts with profit" : "Estimate: revenue × your buy box's margin"} />
        {r.value_basis === "loss" ? <div className="sub">loss-making as filed</div> : null}
      </td>),
    age: ownerCell,
    ownership: <td className="hide-sm nowrap">{r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}</td>,
    profit: moneyCell(r.operating_profit),
    ebitda: moneyCell(ebitda),
    net_assets: moneyCell(r.net_assets),
    cash: moneyCell(r.cash),
    debt: moneyCell(r.bank_debt),
    region: <td className="hide-sm nowrap">{r.trading_region && r.trading_region !== r.region ? <>{r.trading_region}<div className="sub">registered {r.region}</div></> : r.region ?? "—"}</td>,
    website: <td className="hide-sm">{r.website ? <a href={r.website} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{r.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a> : <span className="faint">—</span>}</td>,
    changed: <td className="hide-sm nowrap">{r.last_change ? relDays(r.last_change) : <span className="faint">—</span>}</td>,
    next: <td className="hide-sm">{r.next_action ? <>{r.next_action}{r.next_action_on ? <div className="sub">{date(r.next_action_on)}</div> : null}</> : <span className="faint">—</span>}</td>,
    status: statusCell,
  };
  return (
    <tr className={`${cursor ? "cursor" : ""} ${dim ? "excluded" : ""} ${ticked ? "ticked" : ""}`} onClick={onOpen}>
      {tick}
      {cols.map((k) => <Fragment key={k}>{cells[k]}</Fragment>)}
    </tr>
  );
}

/** Choose the columns this list shows (remembered on this browser). */
function ColumnPicker({ mode, shown, onChange }: { mode: Mode; shown: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const all = allCols(mode).filter((c) => c.key !== "name");
  const toggle = (k: string) => onChange(shown.includes(k) ? shown.filter((x) => x !== k) : [...shown, k]);
  return (
    <div className="colpicker" ref={ref}>
      <button className="btn quiet" onClick={() => setOpen(!open)} aria-expanded={open}>Columns ▾</button>
      {open && (
        <div className="cp-pop">
          {all.map((c) => (
            <label key={c.key} className="check small"><input type="checkbox" checked={shown.includes(c.key)} onChange={() => toggle(c.key)} />{c.label}</label>
          ))}
          <button className="linkish small" style={{ marginTop: 6 }} onClick={() => onChange(defaultCols(mode))}>Back to the usual columns</button>
        </div>
      )}
    </div>
  );
}

/** A figure: plain when filed, amber with a dotted underline when it is an estimate. */
function Fig({ v, est, title }: { v: string; est: boolean; title?: string }) {
  if (v === "—") return <span className="faint">—</span>;
  return <span className={est ? "fig-est" : ""} title={title}>{v}</span>;
}
