import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Row } from "../api";
import { ErrorLine, Flags, Score, StatusMark, Toast, useAsync } from "../components/bits";
import { Spark } from "../components/charts";
import { ageFrom, cap, CHANGE_KIND, int, isBadStatus, OWNERSHIP, range, relDays, years } from "../format";

const PAGE = 100;
const COLS: { key: string; label: string; num?: boolean; sm?: boolean; nosort?: boolean }[] = [
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

// The three ways in. Each is just a preset of URL parameters.
const VIEWS: { key: string; label: string; params: Record<string, string> }[] = [
  { key: "fit", label: "Fits my buy box", params: {} },
  { key: "all", label: "All companies", params: { include_excluded: "1" } },
  { key: "changed", label: "Changed recently", params: { include_excluded: "1", changed_days: "30", sort: "changed" } },
];
const FILTER_KEYS = ["business_type", "has_website", "q", "min_staff", "max_staff", "min_owner_age", "ownership", "region", "tier", "status", "min_score",
  "company_status", "sic", "min_years", "min_value", "max_value", "changed_days", "change_kind", "flag"];
const MORE_KEYS = ["business_type", "has_website", "company_status", "sic", "min_years", "min_value", "max_value", "changed_days", "change_kind", "flag"];

export default function Targets() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const saved = useAsync(() => api.searches(), []);
  const sicList = useAsync(() => api.sic(), []);
  const query = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const page = Number(query.page ?? 0);
  const apiParams: Record<string, string> = { ...query, limit: String(PAGE), offset: String(page * PAGE) };
  delete apiParams.page;
  if (apiParams.include_excluded === "1") apiParams.include_excluded = "true";
  const list = useAsync(() => api.companies(apiParams), [params.toString()]);
  const [cursor, setCursor] = useState(0);
  const [more, setMore] = useState(() => MORE_KEYS.some((k) => params.has(k)));
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => setCursor(0), [params.toString()]);

  const view = query.changed_days && query.sort === "changed" ? "changed" : query.include_excluded === "1" ? "all" : "fit";
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v === null || v === "") p.delete(k); else p.set(k, v);
    p.delete("page");
    setParams(p, { replace: true });
  };
  const sort = query.sort ?? "score";
  const dir = query.dir ?? "desc";
  const toggleSort = (k: string) => {
    const p = new URLSearchParams(params);
    if (sort === k) p.set("dir", dir === "desc" ? "asc" : "desc");
    else { p.set("sort", k); p.set("dir", k === "name" || k === "years" ? "asc" : "desc"); }
    setParams(p, { replace: true });
  };
  const activeFilters = FILTER_KEYS.filter((k) => params.has(k)).length;
  const currentSaved = saved.data?.find((s) => {
    const a = Object.entries(s.params).sort().join("&");
    const b = [...params.entries()].filter(([k]) => k !== "page").sort().join("&");
    return a === b;
  });

  const rows = list.data?.rows ?? [];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, rows.length - 1)); }
      if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
      if (e.key === "Enter" && rows[cursor]) nav(`/c/${rows[cursor].company_number}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, nav]);
  useEffect(() => { document.querySelector("tr.cursor")?.scrollIntoView({ block: "nearest" }); }, [cursor]);

  const m = meta.data;
  const total = list.data?.total ?? 0;
  const empty = m && m.counts.companies === 0;
  const exportHref = "/api/export.csv";

  const saveCurrent = async () => {
    const name = window.prompt("Name this search", currentSaved?.name ?? "");
    if (!name) return;
    const p = Object.fromEntries([...params.entries()].filter(([k]) => k !== "page"));
    await api.saveSearch(name, p);
    saved.reload();
    setToast(`Saved “${name}”`);
  };

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Targets</h1>
          <div className="lede">
            {m ? (
              <>
                <b className="ink">{int(m.counts.in_scope)}</b> of {int(m.counts.companies)} companies fit{" "}
                <Link to="/buy-box">{m.buy_box.name}</Link>. {int(m.counts.tracked)} in your pipeline.
                {m.counts.changed_30d > 0 && <> <Link to="/changes">{int(m.counts.changed_30d)} changed</Link> in the last 30 days.</>}
              </>
            ) : " "}
          </div>
        </div>
        <div className="right">
          <a className="btn" href={exportHref}>Export CSV</a>
        </div>
      </div>

      {empty ? (
        <div className="empty">
          <b>No companies yet.</b> Start by importing your ranked Companies House file or audit workbook on the{" "}
          <Link to="/import">Import</Link> page.
        </div>
      ) : (
        <>
          <div className="views">
            <nav className="viewtabs" aria-label="Views">
              {VIEWS.map((v) => (
                <button key={v.key} className={view === v.key && !currentSaved ? "on" : ""}
                        onClick={() => setParams(new URLSearchParams(v.params), { replace: true })}>{v.label}</button>
              ))}
            </nav>
            {saved.data && saved.data.length > 0 && (
              <div className="saved">
                <span className="faint">Saved:</span>
                {saved.data.map((s) => (
                  <span key={s.id} className={`savedlink ${currentSaved?.id === s.id ? "on" : ""}`}>
                    <button onClick={() => setParams(new URLSearchParams(s.params), { replace: true })}>{s.name}</button>
                    <button className="x" title={`Delete “${s.name}”`} aria-label={`Delete saved search ${s.name}`}
                            onClick={async () => { if (confirm(`Delete saved search “${s.name}”?`)) { await api.deleteSearch(s.id); saved.reload(); } }}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="band">
            <div className="field">
              <label htmlFor="f-q">Search</label>
              <input id="f-q" type="search" key={`q-${query.q ?? ""}`} defaultValue={query.q ?? ""} placeholder="Name, number, postcode"
                     onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value); }}
                     onBlur={(e) => set("q", e.target.value)} />
            </div>
            <NumRange label="Staff" lo="min_staff" hi="max_staff" query={query} set={set} />
            <NumField label="Owner aged" k="min_owner_age" placeholder="at least" query={query} set={set} />
            <Select label="Ownership" k="ownership" query={query} set={set}
                    options={Object.entries(OWNERSHIP).map(([v, l]) => [v, l])} />
            <Select label="Region" k="region" query={query} set={set} options={(m?.regions ?? []).map((r) => [r, r])} />
            <Select label="My status" k="status" query={query} set={set} options={(m?.statuses ?? []).map((s) => [s.value, s.label])} />
            <NumField label="Score" k="min_score" placeholder="at least" query={query} set={set} />
            <button className="btn quiet" onClick={() => setMore(!more)} aria-expanded={more}>{more ? "Fewer filters" : "More filters"}</button>
            <div className="band-actions">
              {activeFilters > 0 && <button className="btn quiet" onClick={() => setParams(new URLSearchParams(view === "all" ? { include_excluded: "1" } : {}), { replace: true })}>Clear</button>}
              <button className="btn" onClick={saveCurrent}>{currentSaved ? "Update saved search" : "Save search"}</button>
            </div>
            {more && (
              <div className="band-more">
                <Select label="Company status" k="company_status" query={query} set={set} options={(m?.company_statuses ?? []).map((s) => [s, cap(s)])} />
                <div className="field">
                  <label htmlFor="f-sic">SIC code starts</label>
                  <datalist id="sic-codes">{sicList.data?.slice(0, 300).map((x) => <option key={x.code} value={x.code}>{`${x.description} (${x.n})`}</option>)}</datalist>
                  <input id="f-sic" type="text" list="sic-codes" style={{ width: 120 }} key={`sic-${query.sic ?? ""}`} defaultValue={query.sic ?? ""} placeholder="e.g. 620"
                         onBlur={(e) => set("sic", e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set("sic", (e.target as HTMLInputElement).value); }} />
                </div>
                <NumField label="Years trading" k="min_years" placeholder="at least" query={query} set={set} />
                <NumRange label="Indicative value, £" lo="min_value" hi="max_value" query={query} set={set} wide />
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
            <span><b>{int(total)}</b> {total === 1 ? "company" : "companies"}{view === "fit" && !activeFilters ? " in your buy box" : ""}</span>
            {view !== "fit" && <span className="faint">Excluded companies are shown in grey with the reason.</span>}
          </div>
          <table className="list">
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className={`${c.nosort ? "" : "sortable"} ${c.num ? "num" : ""} ${c.sm ? "hide-sm" : ""}`}
                      onClick={() => !c.nosort && toggleSort(c.key)} aria-sort={sort === c.key ? (dir === "asc" ? "ascending" : "descending") : undefined}>
                    {c.label}
                    {sort === c.key && <span className="arrow">{dir === "asc" ? "↑" : "↓"}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => <TargetRow key={r.company_number} r={r} cursor={i === cursor} onOpen={() => nav(`/c/${r.company_number}`)} />)}
            </tbody>
          </table>
          {!list.loading && rows.length === 0 && <div className="empty"><b>Nothing matches.</b> Try clearing some filters, or switch to All companies.</div>}
          <div className="pager">
            <span>{total ? `${page * PAGE + 1}–${Math.min((page + 1) * PAGE, total)} of ${int(total)}` : ""}</span>
            <button className="btn" disabled={page === 0} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page - 1)); setParams(p); }}>Previous</button>
            <button className="btn" disabled={(page + 1) * PAGE >= total} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page + 1)); setParams(p); }}>Next</button>
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

function TargetRow({ r, cursor, onOpen }: { r: Row; cursor: boolean; onOpen: () => void }) {
  const age = ageFrom(r.oldest_birth_year);
  const bad = isBadStatus(r.company_status);
  const recent = r.last_change && Date.now() - new Date(r.last_change).getTime() < 30 * 864e5;
  return (
    <tr className={`${cursor ? "cursor" : ""} ${r.excluded ? "excluded" : ""}`} onClick={onOpen}>
      <td><Score value={r.score} coverage={r.coverage} /></td>
      <td>
        <div className="name">
          {r.name}
          {bad && <span className="tag red">{cap(r.company_status)}</span>}
          {recent && r.last_kinds?.length ? <span className="tag" title={`Changed ${relDays(r.last_change)}`}>{r.last_kinds.map((k) => CHANGE_KIND[k] ?? k).join(", ")}</span> : null}
        </div>
        <div className="sub">
          {r.company_number}
          {r.postcode ? ` · ${r.postcode}` : ""}
          {r.region ? ` · ${r.region}` : ""}
          {r.excluded && r.exclusion ? <span className="flag red"> · {r.exclusion}</span> : null}
          {" "}<Flags flags={r.flags} address={r.address_flag} />
        </div>
      </td>
      <td className="num">
        <div className="staffcell"><Spark values={r.staff_trend} w={48} h={16} />{int(r.employees)}</div>
      </td>
      <td className="num hide-sm">
        {range(r.revenue_low, r.revenue_high)}
        {r.revenue_basis === "estimated" && <div className="sub">estimate</div>}
      </td>
      <td className="num hide-sm">
        {range(r.value_low, r.value_high)}
        {r.value_basis && <div className="sub">{r.value_basis === "filed" ? "from filed profit" : "estimate"}</div>}
      </td>
      <td className="num hide-sm">{years(r.incorporation_date)}</td>
      <td className="num">{age ?? "—"}</td>
      <td className="hide-sm nowrap">{r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}</td>
      <td>
        <StatusMark s={r.status} />
        {r.rating ? <span className="faint"> · {r.rating}/5</span> : null}
      </td>
    </tr>
  );
}
