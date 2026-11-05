import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Row } from "../api";
import { ErrorLine, Flags, Score, StatusMark, Toast, useAsync } from "../components/bits";
import { Spark } from "../components/charts";
import SicPicker, { loadSic, type SicOption } from "../components/SicPicker";
import MoneyInput from "../components/MoneyInput";
import { ageFrom, cap, CHANGE_KIND, int, isBadStatus, OWNERSHIP, range, relDays, years } from "../format";

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

// The ways in. Each is just a preset of URL parameters; filters are kept
// when you switch view.
const VIEWS: Record<Mode, { key: string; label: string; params: Record<string, string> }[]> = {
  directory: [
    { key: "all", label: "A to Z", params: {} },
    { key: "changed", label: "Changed recently", params: { changed_days: "30", sort: "changed" } },
  ],
  targets: [
    { key: "fit", label: "Best fit first", params: {} },
    { key: "changed", label: "Changed recently", params: { changed_days: "30", sort: "changed" } },
  ],
};
const DEFAULTS: Record<Mode, Record<string, string>> = {
  directory: { sort: "name", dir: "asc" },
  targets: { sort: "score", dir: "desc", in_box: "true" },
};
const FILTER_KEYS = ["accounts_size", "overdue", "charges", "bb", "business_type", "has_website", "q", "min_staff", "max_staff", "min_owner_age", "ownership", "region", "tier", "status", "min_score",
  "company_status", "sic", "min_years", "min_value", "max_value", "changed_days", "change_kind", "flag"];
const MORE_KEYS = ["overdue", "charges", "business_type", "has_website", "company_status", "sic", "min_years", "min_value", "max_value", "changed_days", "change_kind", "flag"];

export default function Targets({ mode = "targets" }: { mode?: Mode }) {
  const base = mode === "directory" ? "/companies" : "/targets";
  const [params, setParams] = useSearchParams();
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
  if (mode === "targets") apiParams.in_box = "true";
  else if (apiParams.in_box === "1") apiParams.in_box = "true";
  // Rows first (fast), the count separately (it can take a moment on millions of rows).
  const list = useAsync(() => api.companies({ ...apiParams, count: "false" }), [params.toString(), mode]);
  const countParams = Object.fromEntries(Object.entries(apiParams).filter(([k]) => k !== "limit" && k !== "offset"));
  const countQ = useAsync(() => api.companiesCount(countParams), [params.toString(), mode]);
  const [sics, setSics] = useState<SicOption[]>([]);
  useEffect(() => { if (mode === "directory") loadSic().then(setSics); }, [mode]);
  const [cursor, setCursor] = useState(0);
  const [more, setMore] = useState(() => MORE_KEYS.some((k) => params.has(k)));
  // On phones the filters start folded away so results come first (desktop always shows them).
  const [showFilters, setShowFilters] = useState(() => typeof window === "undefined" || window.innerWidth > 860);
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
  const cols = mode === "directory" ? DIR_COLS : COLS;
  const boxName = boxId ? m?.buy_boxes.find((b) => b.id === boxId)?.name : null;
  const empty = m && m.counts.companies === 0;
  // Export exactly the list on screen: same filters and sort (up to 50,000 rows).
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
      <input id="f-q" type="search" value={qText} placeholder="Name, number or postcode" autoComplete="off"
             onChange={(e) => setQText(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") set("q", qText.trim()); }} />
    </div>
  );
  const industryPicker = (w: string | number) => (
    <SicPicker value={(query.sic ?? "").split(",").filter(Boolean)} width={w} placeholder="Industry name or SIC code"
               onChange={(v) => set("sic", v.join(","))} />
  );
  const industry = <div className="field" style={{ minWidth: 300, flex: "1 1 300px" }}><label>Industry</label>{industryPicker("100%")}</div>;
  const industryWide = <div className="field" style={{ flexBasis: "100%" }}><label>Industry (SIC)</label>{industryPicker("100%")}</div>;
  const region = <Select label="Region" k="region" query={query} set={set} options={(m?.regions ?? []).map((r) => [r, r])} />;
  const companyStatus = <Select label="Company status" k="company_status" query={query} set={set}
                                options={(m?.status_groups ?? []).map((g) => [g.value, g.label] as [string, string])} />;
  const staff = <NumRange label="Staff" lo="min_staff" hi="max_staff" query={query} set={set} />;
  const yearsTrading = <NumField label="Years trading" k="min_years" placeholder="at least" query={query} set={set} />;
  const ownerAge = <NumField label="Owner aged" k="min_owner_age" placeholder="at least" query={query} set={set} />;
  const ownership = <Select label="Ownership" k="ownership" query={query} set={set} options={Object.entries(OWNERSHIP).map(([v, l]) => [v, l])} />;
  const myStatus = <Select label="My status" k="status" query={query} set={set} options={(m?.statuses ?? []).map((x) => [x.value, x.label])} />;
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
                Every company on the Companies House register: <b className="ink">{int(m.counts.companies)}</b>.
                Search and filter it any way you like; buy boxes are just one of the filters.
              </>
            ) : (
              <>
                <b className="ink">{int(m.counts.in_scope)}</b> companies fit at least one of your{" "}
                <Link to="/buy-box">buy boxes</Link>, best fit first. {int(m.counts.tracked)} in your pipeline.{" "}
                <Link to="/companies">Browse all companies</Link>
              </>
            )) : " "}
          </div>
        </div>
        <div className="right">
          <a className="btn" href={exportHref} title="Download this list, with your filters, as a spreadsheet (up to 50,000 rows)">Export this list</a>
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

          <div className={`band ${showFilters ? "" : "collapsed"}`}>
            <button className="btn filters-toggle show-sm" onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
              {showFilters ? "Hide filters" : `Filters${activeFilters ? ` (${activeFilters})` : ""}`}
            </button>
            {mode === "targets" && boxSelect}
            {search}
            {mode === "directory" ? <>{companyStatus}{industry}{region}{staff}{yearsTrading}{accountsSize}</>
              : <>{staff}{ownerAge}{ownership}{region}{myStatus}{score}</>}
            <button className="btn quiet" onClick={() => setMore(!more)} aria-expanded={more}>{more ? "Fewer filters" : "More filters"}</button>
            <div className="band-actions">
              {activeFilters > 0 && <button className="btn quiet" onClick={() => setParams(new URLSearchParams(VIEWS[mode].find((v) => v.key === view)?.params ?? {}), { replace: true })}>Clear</button>}
              <button className="btn" onClick={saveCurrent}>{currentSaved ? "Update saved search" : "Save search"}</button>
            </div>
            {more && (
              <div className="band-more">
                {mode === "directory" ? <>{fitSelect}{score}{ownership}{ownerAge}{myStatus}</>
                  : <>{companyStatus}{industryWide}{yearsTrading}{accountsSize}</>}
                {overdueSel}{chargesSel}
                <div className="field">
                  <label>Indicative value</label>
                  <div className="range">
                    <MoneyInput value={query.min_value ? Number(query.min_value) : null} commit="blur" width={120} placeholder="min, e.g. 500k"
                                aria-label="Indicative value minimum" onChange={(v) => set("min_value", v === null ? null : String(v))} />
                    <span className="faint">to</span>
                    <MoneyInput value={query.max_value ? Number(query.max_value) : null} commit="blur" width={120} placeholder="max, e.g. 3m"
                                aria-label="Indicative value maximum" onChange={(v) => set("max_value", v === null ? null : String(v))} />
                  </div>
                </div>
                <Select label="Review tier" k="tier" query={query} set={set} options={(m?.tiers ?? []).map((t) => [t, t])} />
                <Select label="Business type" k="business_type" query={query} set={set} options={[
                  ["software", "Software"], ["saas", "SaaS"], ["data", "Data"], ["msp", "Managed service provider"],
                  ["it_consultancy", "IT consultancy"], ["field_service", "Field service"], ["agency", "Agency"], ["reseller", "Reseller"], ["other", "Other"],
                ]} />
                <Select label="Website" k="has_website" query={query} set={set} options={[["true", "Found"], ["false", "Not found yet"]]} />
                <Select label="Changed in" k="changed_days" query={query} set={set}
                        options={[["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last year"]]} />
                <Select label="Change type" k="change_kind" query={query} set={set} options={Object.entries(CHANGE_KIND)} />
                <Select label="Flag" k="flag" query={query} set={set} options={[
                  ["recent_change", "Recent ownership change"], ["via_holdco", "Owned via holdco"], ["foreign_parent", "Foreign parent"],
                  ["investor", "Investor"], ["trust", "Trust"], ["eot", "EOT"], ["ch_default", "CH default address"],
                  ["formation_agent", "Formation-agent address"], ["mass_address", "Shared address"],
                ]} />
              </div>
            )}
          </div>

          <ErrorLine error={list.error} />
          <div className="resultline">
            <span>{!list.data ? "Loading…" : !countQ.data ? "Counting…" : <><b>{int(total)}{capped ? "+" : ""}</b> {total === 1 ? "company" : "companies"}</>}
              {inBox ? (boxName ? <> in <b>{boxName}</b></> : " in at least one buy box") : ""}</span>
            <span className="faint">
              {list.data?.search_limited ? "Lots of companies match that; showing the first 5,000. Type more to narrow it down. "
                : capped ? "Counting stops at 100,000; add a filter to narrow it down. " : ""}
              {mode === "directory" ? (boxName ? `Best fit is the score in ${boxName}.` : "Best fit is each company's highest score across your buy boxes, where it is in one.")
                : boxName ? "Scores are from this buy box." : "Each company's best score across your buy boxes, tagged with the box."}
            </span>
          </div>
          {sel.size > 0 && (
            <div className="selbar" role="region" aria-label="Ticked companies">
              <b>{int(sel.size)} ticked</b>
              <select value="" onChange={(e) => bulkStage(e.target.value)} aria-label="Move ticked companies to a stage">
                <option value="">Move to stage…</option>
                {(m?.statuses ?? []).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
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
              {rows.map((r, i) => <TargetRow key={r.company_number} r={r} cursor={i === cursor} ticked={sel.has(r.company_number)} onTick={() => toggle(r.company_number)} showBox={!boxId} mode={mode} sics={sics} dim={!!boxId && !!r.excluded}
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

type SetFn = (k: string, v: string | null) => void;

function Select({ label, k, query, set, options }: { label: string; k: string; query: Record<string, string>; set: SetFn; options: [string, string][] }) {
  return (
    <div className="field">
      <label htmlFor={`f-${k}`}>{label}</label>
      <select id={`f-${k}`} value={query[k] ?? ""} onChange={(e) => set(k, e.target.value)} className={query[k] ? "set" : ""}>
        <option value="">Any</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

function NumField({ label, k, placeholder, query, set }: { label: string; k: string; placeholder?: string; query: Record<string, string>; set: SetFn }) {
  return (
    <div className="field">
      <label htmlFor={`f-${k}`}>{label}</label>
      <input id={`f-${k}`} type="number" min={0} key={`${k}-${query[k] ?? ""}`} placeholder={placeholder} defaultValue={query[k] ?? ""}
             className={query[k] ? "set" : ""}
             onBlur={(e) => set(k, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(k, (e.target as HTMLInputElement).value); }} />
    </div>
  );
}

function NumRange({ label, lo, hi, query, set, wide }: { label: string; lo: string; hi: string; query: Record<string, string>; set: SetFn; wide?: boolean }) {
  const style = wide ? { width: 104 } : undefined;
  return (
    <div className="field">
      <label>{label}</label>
      <div className="range">
        <input type="number" min={0} placeholder="min" style={style} key={`${lo}-${query[lo] ?? ""}`} defaultValue={query[lo] ?? ""} className={query[lo] ? "set" : ""}
               aria-label={`${label} minimum`} onBlur={(e) => set(lo, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(lo, (e.target as HTMLInputElement).value); }} />
        <span className="faint">to</span>
        <input type="number" min={0} placeholder="max" style={style} key={`${hi}-${query[hi] ?? ""}`} defaultValue={query[hi] ?? ""} className={query[hi] ? "set" : ""}
               aria-label={`${label} maximum`} onBlur={(e) => set(hi, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(hi, (e.target as HTMLInputElement).value); }} />
      </div>
    </div>
  );
}

function TargetRow({ r, cursor, onOpen, showBox, mode, sics, dim, href, ticked, onTick }: {
  r: Row; cursor: boolean; onOpen: () => void; showBox: boolean; mode: Mode; sics: SicOption[]; dim: boolean; href: string;
  ticked: boolean; onTick: () => void;
}) {
  const tick = (
    <td className="tick" onClick={(e) => e.stopPropagation()}>
      <input type="checkbox" checked={ticked} onChange={onTick} aria-label={`Tick ${r.name}`} />
    </td>
  );
  const age = ageFrom(r.oldest_birth_year);
  const bad = isBadStatus(r.company_status);
  const recent = r.last_change && Date.now() - new Date(r.last_change).getTime() < 30 * 864e5;
  const scoreCell = (
    <td>
      {r.score !== null && !dim ? <Score value={r.score} coverage={r.coverage} /> : <span className="faint">—</span>}
      {showBox && r.box_name && (
        <div className="boxtag" title={r.boxes && r.boxes.length > 1 ? `In ${r.boxes.length} buy boxes: ${r.boxes.join(", ")}` : `Buy box: ${r.box_name}`}>
          {r.box_name}{r.boxes && r.boxes.length > 1 ? ` +${r.boxes.length - 1}` : ""}
        </div>
      )}
    </td>
  );
  const nameCell = (
    <td>
      <div className="name">
        <Link className="rowlink" to={href} onClick={(e) => e.stopPropagation()}>{r.name}</Link>
        {bad && <span className="tag red">{cap(r.company_status)}</span>}
        {recent && r.last_kinds?.length ? <span className="tag" title={`Changed ${relDays(r.last_change)}`}>{r.last_kinds.map((k) => CHANGE_KIND[k] ?? k).join(", ")}</span> : null}
      </div>
      <div className="sub">
        {r.company_number}
        {r.postcode ? ` · ${r.postcode}` : ""}
        {r.region ? ` · ${r.region}` : ""}
        {dim && r.exclusion ? <span className="flag red">{r.exclusion}</span> : null}
        {r.accounts_overdue ? <span className="flag red">accounts overdue</span> : r.confirmation_overdue ? <span className="flag red">confirmation overdue</span> : null}
        {r.charges_outstanding ? <span className="flag">{r.charges_outstanding} charge{r.charges_outstanding === 1 ? "" : "s"}</span> : null}
        {" "}<Flags flags={r.flags} address={r.address_flag} />
      </div>
    </td>
  );
  const staffCell = <td className="num"><div className="staffcell"><Spark values={r.staff_trend} w={48} h={16} />{int(r.employees)}</div></td>;
  const revenueCell = (
    <td className="num hide-sm">
      {range(r.revenue_low, r.revenue_high)}
      {r.revenue_basis === "estimated" && <div className="sub">estimate</div>}
    </td>
  );
  const statusCell = (
    <td>
      <StatusMark s={r.status} />
      {r.rating ? <span className="faint"> · {r.rating}/5</span> : null}
    </td>
  );
  if (mode === "directory") {
    const code = r.sic_codes?.[0];
    const label = code ? sics.find((o) => o.code === code)?.description : null;
    return (
      <tr className={`${cursor ? "cursor" : ""} ${dim ? "excluded" : ""} ${ticked ? "ticked" : ""}`} onClick={onOpen}>
        {tick}
        {nameCell}
        <td className="hide-sm industry">
          {code ? <><div className="clamp">{label ?? code}</div>
            <div className="sub">{code}{r.sic_codes.length > 1 ? ` +${r.sic_codes.length - 1} more` : ""}</div></> : <span className="faint">Not given</span>}
        </td>
        <td className="num hide-sm">{years(r.incorporation_date)}</td>
        {staffCell}
        {revenueCell}
        <td className="hide-sm nowrap">
          {r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}
          {age ? <div className="sub">oldest owner {age}</div> : null}
        </td>
        {scoreCell}
        {statusCell}
      </tr>
    );
  }
  return (
    <tr className={`${cursor ? "cursor" : ""} ${dim ? "excluded" : ""} ${ticked ? "ticked" : ""}`} onClick={onOpen}>
      {tick}
      {scoreCell}
      {nameCell}
      {staffCell}
      {revenueCell}
      <td className="num hide-sm">
        {range(r.value_low, r.value_high)}
        {r.value_basis === "loss" ? <div className="sub">loss-making as filed</div>
          : r.value_low && r.value_basis ? <div className="sub">{r.value_basis === "filed" ? "from filed profit" : "estimate"}</div> : null}
      </td>
      <td className="num hide-sm">{years(r.incorporation_date)}</td>
      <td className="num">{age ?? "—"}</td>
      <td className="hide-sm nowrap">{r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}</td>
      {statusCell}
    </tr>
  );
}
