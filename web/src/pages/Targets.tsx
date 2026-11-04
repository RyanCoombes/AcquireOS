import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Row } from "../api";
import { Flags, Score, StatusMark, useAsync, ErrorLine } from "../components/bits";
import { ageFrom, int, OWNERSHIP, range, years } from "../format";

const PAGE = 100;
const COLS: { key: string; label: string; num?: boolean; sm?: boolean }[] = [
  { key: "score", label: "Score" },
  { key: "name", label: "Company" },
  { key: "staff", label: "Staff", num: true },
  { key: "revenue", label: "Revenue", num: true, sm: true },
  { key: "years", label: "Years", num: true, sm: true },
  { key: "age", label: "Owner age", num: true },
  { key: "ownership", label: "Ownership", sm: true },
  { key: "status", label: "My status" },
];

export default function Targets() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const query = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const page = Number(query.page ?? 0);
  const apiParams: Record<string, string> = { ...query, limit: String(PAGE), offset: String(page * PAGE) };
  delete apiParams.page;
  if (apiParams.include_excluded === "1") apiParams.include_excluded = "true";
  const list = useAsync(() => api.companies(apiParams), [params.toString()]);
  const [cursor, setCursor] = useState(0);
  useEffect(() => setCursor(0), [params.toString()]);

  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v === null || v === "") p.delete(k); else p.set(k, v);
    p.delete("page");
    setParams(p, { replace: true });
  };
  const sort = query.sort ?? "score";
  const dir = query.dir ?? "desc";
  const toggleSort = (k: string) => {
    if (k === "ownership") return;
    const p = new URLSearchParams(params);
    if (sort === k) p.set("dir", dir === "desc" ? "asc" : "desc");
    else { p.set("sort", k); p.set("dir", k === "name" || k === "years" ? "asc" : "desc"); }
    setParams(p, { replace: true });
  };

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
  useEffect(() => {
    document.querySelector("tr.cursor")?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const m = meta.data;
  const total = list.data?.total ?? 0;
  const empty = m && m.counts.companies === 0;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Targets</h1>
          <div className="lede">
            {m ? (
              <>
                {int(m.counts.in_scope)} of {int(m.counts.companies)} companies fit <Link to="/buy-box">{m.buy_box.name}</Link>.
                {" "}{int(m.counts.tracked)} tracked in your pipeline.
              </>
            ) : " "}
          </div>
        </div>
        <div className="right">
          <a className="btn" href="/api/export.csv">Export CSV</a>
        </div>
      </div>

      {empty ? (
        <div className="empty">
          <b>No companies yet.</b> Start by importing your ranked Companies House file or audit workbook on the{" "}
          <Link to="/import">Import</Link> page.
        </div>
      ) : (
        <>
          <div className="band">
            <div className="field">
              <label htmlFor="f-q">Search</label>
              <input id="f-q" type="search" defaultValue={query.q ?? ""} placeholder="Name, number, postcode"
                     onKeyDown={(e) => { if (e.key === "Enter") set("q", (e.target as HTMLInputElement).value); }}
                     onBlur={(e) => set("q", e.target.value)} />
            </div>
            <div className="field">
              <label>Staff</label>
              <div className="range">
                <input type="number" min={0} placeholder="min" defaultValue={query.min_staff ?? ""} onBlur={(e) => set("min_staff", e.target.value)} />
                <span className="faint">to</span>
                <input type="number" min={0} placeholder="max" defaultValue={query.max_staff ?? ""} onBlur={(e) => set("max_staff", e.target.value)} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="f-age">Owner at least</label>
              <input id="f-age" type="number" min={0} placeholder="age" defaultValue={query.min_owner_age ?? ""} onBlur={(e) => set("min_owner_age", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="f-own">Ownership</label>
              <select id="f-own" value={query.ownership ?? ""} onChange={(e) => set("ownership", e.target.value)}>
                <option value="">Any</option>
                {Object.entries(OWNERSHIP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="f-region">Region</label>
              <select id="f-region" value={query.region ?? ""} onChange={(e) => set("region", e.target.value)}>
                <option value="">Any</option>
                {m?.regions.map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="f-tier">Review tier</label>
              <select id="f-tier" value={query.tier ?? ""} onChange={(e) => set("tier", e.target.value)} style={{ maxWidth: 200 }}>
                <option value="">Any</option>
                {m?.tiers.map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="f-status">My status</label>
              <select id="f-status" value={query.status ?? ""} onChange={(e) => set("status", e.target.value)}>
                <option value="">Any</option>
                {m?.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="f-score">Score at least</label>
              <input id="f-score" type="number" min={0} max={100} defaultValue={query.min_score ?? ""} onBlur={(e) => set("min_score", e.target.value)} />
            </div>
            <label className="check">
              <input type="checkbox" checked={query.include_excluded === "1"} onChange={(e) => set("include_excluded", e.target.checked ? "1" : null)} />
              Show excluded
            </label>
            {params.toString() && (
              <button className="btn quiet" onClick={() => setParams(new URLSearchParams(), { replace: true })}>Clear</button>
            )}
          </div>

          <ErrorLine error={list.error} />
          <table className="list">
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className={`${c.key !== "ownership" ? "sortable" : ""} ${c.num ? "num" : ""} ${c.sm ? "hide-sm" : ""}`}
                      onClick={() => toggleSort(c.key)} aria-sort={sort === c.key ? (dir === "asc" ? "ascending" : "descending") : undefined}>
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
          {!list.loading && rows.length === 0 && <div className="empty"><b>Nothing matches these filters.</b> Try clearing some.</div>}
          <div className="pager">
            <span>{total ? `${page * PAGE + 1}–${Math.min((page + 1) * PAGE, total)} of ${int(total)}` : ""}</span>
            <button className="btn" disabled={page === 0} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page - 1)); setParams(p); }}>Previous</button>
            <button className="btn" disabled={(page + 1) * PAGE >= total} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page + 1)); setParams(p); }}>Next</button>
            <span className="faint small" style={{ marginLeft: "auto" }}>
              <span className="kbd">j</span> <span className="kbd">k</span> to move, <span className="kbd">Enter</span> to open
            </span>
          </div>
        </>
      )}
    </>
  );
}

function TargetRow({ r, cursor, onOpen }: { r: Row; cursor: boolean; onOpen: () => void }) {
  const age = ageFrom(r.oldest_birth_year);
  return (
    <tr className={`${cursor ? "cursor" : ""} ${r.excluded ? "excluded" : ""}`} onClick={onOpen}>
      <td><Score value={r.score} coverage={r.coverage} /></td>
      <td>
        <div className="name">{r.name}</div>
        <div className="sub">
          {r.company_number}
          {r.postcode ? ` · ${r.postcode}` : ""}
          {r.region ? ` · ${r.region}` : ""}
          {r.excluded && r.exclusion ? <span className="flag red"> · {r.exclusion}</span> : null}
          {" "}<Flags flags={r.flags} address={r.address_flag} />
        </div>
      </td>
      <td className="num">{int(r.employees)}</td>
      <td className="num hide-sm">
        {range(r.revenue_low, r.revenue_high)}
        {r.revenue_basis === "estimated" && <div className="sub">estimate</div>}
      </td>
      <td className="num hide-sm">{years(r.incorporation_date)}</td>
      <td className="num">{age ?? "—"}</td>
      <td className="hide-sm">{r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}</td>
      <td>
        <StatusMark s={r.status} />
        {r.rating ? <span className="faint"> · {r.rating}/5</span> : null}
      </td>
    </tr>
  );
}
