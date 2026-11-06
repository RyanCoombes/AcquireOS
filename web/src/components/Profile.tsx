/* Company profile sections: financial overview (chart and trend table),
   charges and investment signals, and finding the website. */
import type React from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { date, money, filingLabel } from "../format";

type FinSummary = NonNullable<CompanyDetail["fin_summary"]>;

const fmtValue = (key: string, v: number) =>
  key === "employees" ? Math.round(v).toLocaleString("en-GB") : key === "debt_ratio" ? `${Math.round(v)}%` : money(v, { precise: v < 1e6 });

const fmtChange = (key: string, v: number) =>
  key === "employees" ? Math.abs(Math.round(v)).toLocaleString("en-GB") : key === "debt_ratio" ? `${Math.abs(Math.round(v))} pts` : money(Math.abs(v));

/** Assets, net assets and liabilities over the years, like a balance-sheet strip. */
function BalanceChart({ series }: { series: FinSummary["series"] }) {
  const pts = series.filter((s) => s.total_assets != null || s.net_assets != null);
  if (pts.length < 2) {
    return (
      <div className="callout" style={{ marginBottom: 12 }}>
        {pts.length === 1 ? "Only one year of balance-sheet figures on file, so there is no trend to chart yet." : "No balance-sheet figures on file yet."}{" "}
        More years appear as more months of accounts are loaded (Data page: 48 months gives about five years).
      </div>
    );
  }
  const W = 720, H = 240, L = 58, R = 26, T = 14, B = 26;
  const ta = pts.map((p) => p.total_assets ?? p.net_assets ?? 0);
  const na = pts.map((p) => p.net_assets ?? 0);
  const tl = pts.map((p) => -(p.total_liabilities ?? 0));
  const hi = Math.max(...ta, ...na, 0), lo = Math.min(...tl, ...na, 0);
  const span = hi - lo || 1;
  const x = (i: number) => L + (i * (W - L - R)) / (pts.length - 1);
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / span;
  const area = (vals: number[]) => `M${x(0)},${y(0)} ` + vals.map((v, i) => `L${x(i)},${y(v)}`).join(" ") + ` L${x(vals.length - 1)},${y(0)} Z`;
  const line = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  // Round tick steps (1, 2 or 5 × a power of ten) so the axis reads cleanly.
  const raw = span / 5, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) ?? raw;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-6; t += step) ticks.push(Math.abs(t) < step / 1e6 ? 0 : t);
  const hasTA = pts.some((p) => p.total_assets != null);
  const hasTL = pts.some((p) => p.total_liabilities != null);
  return (
    <figure className="balchart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Total assets, net assets and total liabilities by year">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className={t === 0 ? "zero" : "grid"} />
            <text x={L - 6} y={y(t) + 4} textAnchor="end">{money(t)}</text>
          </g>
        ))}
        {hasTA && <path d={area(ta)} className="a-assets" />}
        <path d={area(na)} className="a-net" />
        {hasTL && <path d={area(tl)} className="a-liab" />}
        {hasTA && <path d={line(ta)} className="l-assets" />}
        <path d={line(na)} className="l-net" />
        {hasTL && <path d={line(tl)} className="l-liab" />}
        {pts.map((p, i) => <text key={i} x={x(i)} y={H - 8} textAnchor="middle">{String(p.period_end).slice(0, 4)}</text>)}
      </svg>
      <figcaption>
        {hasTA && <span><i className="k-assets" />Total assets</span>}
        <span><i className="k-net" />Net assets</span>
        {hasTL && <span><i className="k-liab" />Total liabilities</span>}
        {!hasTA && <span className="faint">Totals not stated in these accounts</span>}
      </figcaption>
    </figure>
  );
}

export function FinancialOverview({ s }: { s: FinSummary }) {
  if (!s.period_end || !s.rows.length) return null;
  return (
    <>
      <BalanceChart series={s.series} />
      <table className="fintrend">
        <tbody>
          <tr>
            <td>Period ended</td><td><b>{date(s.period_end)}</b></td>
            <td className="muted">{s.previous_end ? <>Compared with {date(s.previous_end)}{s.months ? ` (${s.months} months earlier)` : ""}</> : "First year on file"}</td>
          </tr>
          {s.rows.map((r) => (
            <tr key={r.key}>
              <td>{r.label}</td>
              <td>
                <b>{fmtValue(r.key, r.value)}</b>
                {r.change != null && r.change !== 0 && (
                  <div className={`chg ${r.good === true ? "pos" : r.good === false ? "neg" : ""}`}>
                    {r.change > 0 ? "▲" : "▼"} {fmtChange(r.key, r.change)}{r.change_pct != null ? ` (${r.change_pct > 0 ? "+" : ""}${r.change_pct}%)` : ""}
                  </div>
                )}
              </td>
              <td>{r.trend}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="faint small">Totals worked out from the filed accounts.</p>
    </>
  );
}

export function Charges({ data, num, onFetched }: { data: CompanyDetail; num: string; onFetched: () => void }) {
  const c = data.company;
  const ch = data.ch;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fetchIt = async () => {
    setBusy(true); setErr(null);
    try { await api.fetchDetails(num); onFetched(); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <section id="charges">
      <Head icon="lock" tone="purple" title="Charges and investment"
            right={ch?.enabled ? <button className="btn quiet" disabled={busy} onClick={fetchIt}>
              {busy ? "Fetching…" : ch.fetched ? "Refresh" : "Fetch from Companies House"}</button> : undefined} />
      <p style={{ margin: "0 0 10px" }}>
        {c.charges_total == null ? <span className="faint">Not loaded yet.</span>
          : c.charges_total === 0 ? "No charges registered."
          : <><b>{c.charges_outstanding ?? 0} outstanding</b>{c.charges_part_satisfied ? `, ${c.charges_part_satisfied} part repaid` : ""}
              {c.charges_satisfied ? `, ${c.charges_satisfied} repaid` : ""}, {c.charges_total} registered in total.</>}
      </p>
      {ch?.signals?.length ? (
        <div className="signals">
          {ch.signals.map((s, i) => (
            <div key={i} className={`signal ${s.strength}`}>
              <b>{s.strength === "strong" ? "Investor" : "Possible investment"}</b> {s.text}{s.date ? <span className="faint"> · {date(s.date)}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
      {ch?.charges?.length ? (
        <table style={{ marginTop: 8 }}>
          <thead><tr><th>Held by</th><th>Status</th><th className="hide-sm">Type</th><th>Created</th><th className="hide-sm">Repaid</th></tr></thead>
          <tbody>
            {ch.charges.map((x) => (
              <tr key={x.charge_id} className={x.status === "fully-satisfied" ? "excluded" : ""}>
                <td>{x.holders.join(", ") || "—"}{x.particulars ? <div className="sub">{x.particulars.slice(0, 140)}</div> : null}</td>
                <td>{x.status === "outstanding" ? <b>Outstanding</b> : x.status === "part-satisfied" ? "Part repaid" : "Repaid"}</td>
                <td className="hide-sm small">{x.classification ?? ""}</td>
                <td>{date(x.created_on)}</td>
                <td className="hide-sm">{x.satisfied_on ? date(x.satisfied_on) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {ch?.filings?.length ? (
        <details style={{ marginTop: 10 }}>
          <summary className="muted">Share and constitution filings ({ch.filings.length})</summary>
          <table style={{ marginTop: 6 }}><tbody>
            {ch.filings.map((f) => (
              <tr key={f.transaction_id}><td style={{ width: 120 }}>{date(f.filed_on)}</td><td style={{ width: 70 }}><b>{f.type}</b></td>
                <td className="muted small">{(f.description ?? "").replace(/-/g, " ")}</td></tr>
            ))}
          </tbody></table>
        </details>
      ) : null}
      {err && <div className="callout red">{err}</div>}
      <p className="faint small">
        {ch?.enabled
          ? ch.fetched ? <>Fetched {date(ch.fetched.fetched_at)}{ch.fetched.error ? ` · some parts failed: ${ch.fetched.error}` : ""}</>
            : "Fetch to see charge holders, directors, shareholders and filings."
          : <>Add <code>CH_API_KEY</code> to the stack for charge holders, directors and shareholders.{" "}
              <a href={`https://find-and-update.company-information.service.gov.uk/company/${num}/charges`} target="_blank" rel="noreferrer">Companies House ↗</a></>}
      </p>
    </section>
  );
}

export function WebsiteFinder({ num, onSaved }: { num: string; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.findWebsite>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const go = async (u?: string) => {
    setBusy(true); setErr(null);
    try { const r = await api.findWebsite(num, u); setRes(r); if (r.saved) onSaved(); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <div className="webfind">
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button className="btn" disabled={busy} onClick={() => go()}>{busy ? "Checking likely sites…" : "Find website"}</button>
        <span className="faint small">or check one:</span>
        <input type="text" value={url} placeholder="example.co.uk" style={{ width: 200 }} onChange={(e) => setUrl(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && url.trim()) go(url.trim()); }} />
        <button className="btn quiet" disabled={busy || !url.trim()} onClick={() => go(url.trim())}>Check</button>
      </div>
      {err && <div className="callout red">{err}</div>}
      {res && (
        <div style={{ marginTop: 8 }}>
          <div className={res.saved ? "pos" : "muted"}>{res.message}</div>
          {res.results.length > 0 && (
            <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {res.results.map((r, i) => (
                <li key={i}><a href={r.url} target="_blank" rel="noreferrer">{r.url.replace(/^https?:\/\/(www\.)?/, "")}</a>
                  {" · "}{r.confidence ? <b>{r.confidence === "high" ? "confirmed" : r.confidence === "medium" ? "likely" : "weak match"}</b> : "no match"}
                  {r.evidence ? ` (${r.evidence})` : ""}{r.title ? <span className="faint"> · {r.title}</span> : null}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="faint small" style={{ marginTop: 6 }}>Saves a site only if it shows the company number or postcode.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- icons */
const ICON: Record<string, string> = {
  overview: "M4 5h16v14H4zM8 9h8M8 13h5",
  money: "M3 17l5-5 4 4 8-8M15 8h5v5",
  people: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87",
  owners: "M12 2l3 6 6 .9-4.5 4.3 1 6.3L12 16.8 6.5 19.5l1-6.3L3 8.9 9 8z",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  group: "M6 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.7 6.9l8.6 9.2M8 6h8",
  file: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  pound: "M17 7a4 4 0 0 0-8 1v4H7m2 0v3c0 2-1 3-3 4h12",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-3.5-3.5",
  pin: "M12 21s7-6.2 7-11a7 7 0 0 0-14 0c0 4.8 7 11 7 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
};
export function Ico({ name, tone = "teal" }: { name: string; tone?: string }) {
  return <span className={`ico ${tone}`} aria-hidden><svg viewBox="0 0 24 24"><path d={ICON[name] ?? ICON.overview} /></svg></span>;
}
export function Head({ icon, tone, title, aside, right }: { icon: string; tone?: string; title: string; aside?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="sechead">
      <h2 className="withico"><Ico name={icon} tone={tone} />{title}</h2>
      {aside && <span className="faint small">{aside}</span>}
      {right && <span className="right">{right}</span>}
    </div>
  );
}

const yearsSince = (d: string | null) => (d ? Math.floor((Date.now() - new Date(d).getTime()) / 3.156e10) : null);

export function Filings({ data }: { data: CompanyDetail }) {
  const ch = data.ch;
  const c = data.company;
  const prof = ch?.fetched?.profile ?? {};
  const flags = [
    prof.has_been_liquidated && "Has been liquidated before",
    prof.has_insolvency_history && "Has insolvency history",
    prof.registered_office_is_in_dispute && "Registered office in dispute",
    prof.undeliverable_registered_office_address && "Post to the registered office is returned",
  ].filter(Boolean) as string[];
  return (
    <section id="filings">
      <Head icon="file" tone="amber" title="Filings" aside={c.last_accounts_date ? `Last accounts to ${date(c.last_accounts_date)}` : undefined} />
      {flags.length > 0 && <div className="callout red">{flags.join(" · ")}</div>}
      {(ch?.fetched?.insolvency ?? []).length > 0 && (
        <div className="callout red">Insolvency: {(ch!.fetched!.insolvency as any[]).map((x) => (x.type ?? "").replace(/-/g, " ")).join(", ")}</div>
      )}
      {(ch?.late_filings ?? []).length > 0 && (
        <div className="chips" style={{ marginBottom: 8 }}>
          {ch!.late_filings.map((l, i) => <span key={i} className="chip red">Accounts to {date(l.made_up_to)} filed {l.days_late} days late</span>)}
        </div>
      )}
      {ch?.filings?.length ? (
        <div className="timeline">
          {ch.filings.slice(0, 12).map((f) => (
            <div key={f.transaction_id} className="tl">
              <span className="tdate">{date(f.filed_on)}</span>
              <span className="tdesc"><b>{filingLabel(f.type, f.description)}</b></span>
            </div>
          ))}
          {ch.filings.length > 12 && <a className="small" href={`https://find-and-update.company-information.service.gov.uk/company/${c.company_number}/filing-history`} target="_blank" rel="noreferrer">All {ch.filings.length} filings ↗</a>}
        </div>
      ) : <div className="faint">Fetch Companies House details (Charges section) to see the filing history.</div>}
    </section>
  );
}


/* ---------------- Owners & directors: one list, with an ownership bar ---------------- */

const TITLE_WORDS = new Set(["MR", "MRS", "MS", "MISS", "DR", "SIR", "PROF", "LADY", "LORD", "DAME", "REV"]);
const CO_WORDS = /\b(LIMITED|LTD|PLC|LLP|HOLDINGS?|GROUP)\b/g;

/** First name + surname, so "Mr Alex J Smith", "SMITH, Alex John" and "ALEX SMITH" match. */
function personKey(name: string, company: boolean): string {
  let s = name.toUpperCase().trim();
  if (company) return s.replace(CO_WORDS, " ").replace(/[^A-Z0-9 ]/g, " ").split(/\s+/).filter(Boolean).join(" ");
  if (s.includes(",")) { const [sur, rest] = s.split(","); s = `${rest} ${sur}`; }
  const w = s.replace(/[^A-Z ]/g, " ").split(/\s+/).filter((x) => x && !TITLE_WORDS.has(x));
  return w.length > 1 ? `${w[0]} ${w[w.length - 1]}` : w.join(" ");
}

function niceName(name: string, company: boolean): string {
  if (company) return name;
  let s = name.trim();
  if (s.includes(",")) { const [sur, rest] = s.split(","); s = `${rest.trim()} ${sur.trim()}`; }
  s = s.split(/\s+/).filter((x) => !TITLE_WORDS.has(x.toUpperCase().replace(".", ""))).join(" ");
  // "Pat BROWN" / "ALEX SMITH" -> "Pat Brown" / "Alex Smith"
  return s.split(" ").map((x) => (x.length > 1 && x === x.toUpperCase() ? x.charAt(0) + x.slice(1).toLowerCase() : x)).join(" ");
}

/** The share band from owner (PSC) natures, e.g. [75, 100]. */
function band(natures: string[]): [number, number] | null {
  let best: [number, number] | null = null;
  for (const n of natures) {
    const m = n.match(/ownership-of-shares-(\d+)-to-(\d+)-percent/) ?? n.match(/voting-rights-(\d+)-to-(\d+)-percent/);
    const r: [number, number] | null = m ? [Number(m[1]), Number(m[2])] : /more-than-25-percent/.test(n) ? [25, 100] : null;
    if (r && (!best || r[0] > best[0])) best = r;
  }
  return best;
}

/** "1 individual owner(s), held directly." -> "1 owner, held directly." */
const ownSentence = (t: string) => t
  .replace(/(\d+) individual owner\(s\)/, (_m, n) => (n === "1" ? "1 owner" : `${n} owners`))
  .replace(/^Classed as (.+) from the owner records\.$/, (_m, x: string) => x.charAt(0).toUpperCase() + x.slice(1) + ".");

const SEG_COLOURS = ["var(--teal)", "var(--orange)", "var(--blue)", "var(--purple)", "var(--amber)", "var(--green)"];

type Who = {
  key: string; name: string; company: boolean; roles: Set<string>; pct: number | null; band: [number, number] | null;
  personId?: number; birthYear: number | null; since: string | null; boards: number; officerKey?: string; regNo?: string | null;
  ultimately: string[]; colour?: string;
};

export function OwnersDirectors({ data, flags }: { data: CompanyDetail; flags?: React.ReactNode }) {
  const ch = data.ch;
  const own = data.ownership;
  const map = new Map<string, Who>();
  const get = (name: string, company: boolean): Who => {
    const k = (company ? "C:" : "P:") + personKey(name, company);
    let w = map.get(k);
    if (!w) {
      w = { key: k, name: niceName(name, company), company, roles: new Set(), pct: null, band: null, birthYear: null, since: null, boards: 0, ultimately: [] };
      map.set(k, w);
    }
    return w;
  };
  const currentPsc = data.people.filter((p) => !p.ceased_on);
  for (const p of currentPsc) {
    const w = get(p.name, p.kind !== "individual");
    w.roles.add("Owner");
    w.band = band(p.natures) ?? w.band;
    w.personId = p.person_id;
    w.birthYear = w.birthYear ?? p.birth_year;
    w.regNo = p.registration_number;
    w.since = w.since ?? p.notified_on;
  }
  const shareholders = ch?.shareholders ?? [];
  for (const s of shareholders) {
    const company = /\b(LIMITED|LTD|PLC|LLP|TRUST|NOMINEES?)\b/i.test(s.name);
    const w = get(s.name, company);
    w.roles.add("Shareholder");
    w.pct = Math.round(((w.pct ?? 0) + (s.pct ?? 0)) * 10) / 10;
  }
  for (const o of (ch?.officers ?? []).filter((x) => !x.resigned_on)) {
    const w = get(o.name, /corporate/.test(o.role ?? ""));
    w.roles.add((o.role ?? "").includes("secretary") ? "Secretary" : "Director");
    w.birthYear = w.birthYear ?? o.birth_year;
    w.since = o.appointed_on && (!w.since || o.appointed_on < w.since) ? o.appointed_on : w.since;
    w.boards = Math.max(w.boards, o.other_current);
    w.officerKey = o.officer_key;
  }
  for (const u of own?.ultimate_owners ?? []) {
    if (!u.via.length) continue;
    const via = u.via[0].toUpperCase();
    const parent = [...map.values()].find((w) => w.company && ((w.regNo ?? "").toUpperCase() === via || w.key === "C:" + personKey(via, true)));
    if (parent) parent.ultimately.push(niceName(u.name, false) + (u.birth_year ? ` (${new Date().getFullYear() - u.birth_year})` : ""));
  }
  const exact = shareholders.length > 0;
  const people = [...map.values()].sort((a, b) =>
    (b.pct ?? b.band?.[0] ?? -1) - (a.pct ?? a.band?.[0] ?? -1) || Number(b.roles.has("Director")) - Number(a.roles.has("Director")));
  const owners = people.filter((w) => (exact ? w.pct : w.band?.[0]));
  owners.forEach((w, i) => { w.colour = SEG_COLOURS[i % SEG_COLOURS.length]; });
  people.filter((w) => !w.colour && (w.pct || w.band)).forEach((w, i) => { w.colour = SEG_COLOURS[(owners.length + i) % SEG_COLOURS.length]; });
  const shown = owners.reduce((s, w) => s + (exact ? w.pct ?? 0 : w.band![0]), 0);
  const others = ch?.other_appointments ?? [];
  const former = [
    ...data.people.filter((p) => p.ceased_on).map((p) => niceName(p.name, p.kind !== "individual")),
    ...(ch?.officers ?? []).filter((o) => o.resigned_on).map((o) => niceName(o.name, false)),
  ].filter((v, i, a) => a.indexOf(v) === i);

  return (
    <section id="ownership">
      <Head icon="owners" tone="orange" title="Owners & directors" aside={flags} />
      {own && own.ownership_type !== "unknown" && <p style={{ margin: "0 0 10px" }}><b>{ownSentence(own.explanation)}</b></p>}

      {owners.length > 0 && (
        <>
          <div className="ownbar" role="img" aria-label="Ownership split">
            {owners.map((w) => {
              const v = exact ? w.pct ?? 0 : w.band![0];
              return <i key={w.key} style={{ width: `${v}%`, background: w.colour }} title={`${w.name}: ${exact ? `${w.pct}%` : `${w.band![0]}–${w.band![1]}%`}`} />;
            })}
            {shown < 99.5 && <i className="rest" style={{ width: `${100 - shown}%` }} title={exact ? "Others" : "Not stated"} />}
          </div>
          <div className="faint small" style={{ margin: "4px 0 12px" }}>
            {exact ? `Exact, from the ${ch?.fetched?.shareholders_from ?? "confirmation statement"}`
              : "Approximate: owners register bands. Owners under 25% aren't named."}
          </div>
        </>
      )}

      {people.length === 0 ? <div className="faint">No owners or directors on file.</div> : (
        <div className="whos">
          {people.map((w) => {
            const theirs = w.officerKey ? others.filter((a) => a.officer_key === w.officerKey && !a.resigned_on) : [];
            const age = w.birthYear ? new Date().getFullYear() - w.birthYear : null;
            const yrs = yearsSince(w.since);
            const pctText = w.pct != null ? `${w.pct}%` : w.band ? `${w.band[0]}–${w.band[1]}%` : null;
            return (
              <div key={w.key} className="who">
                <span className="dot" style={{ background: w.colour ?? "var(--grey-soft)" }} />
                <div className="wmain">
                  <div className="wname">
                    {w.personId ? <Link to={`/owners/${w.personId}`}>{w.name}</Link> : w.name}
                    {[...w.roles].filter((r) => r !== "Shareholder" || !w.roles.has("Owner")).map((r) =>
                      <span key={r} className={`role ${r === "Shareholder" ? "owner" : r.toLowerCase()}`}>{r === "Shareholder" ? "Owner" : r}</span>)}
                  </div>
                  <div className="wmeta">
                    {w.company ? <>Company{w.regNo ? <> · <Link to={`/c/${w.regNo}`}>{w.regNo}</Link></> : null}
                      {w.ultimately.length ? <> · owned by {w.ultimately.join(", ")}</> : null}</>
                      : <>{age ? `Age ${age}` : "Age not known"}{yrs !== null ? ` · ${yrs} yrs` : ""}
                          {w.roles.has("Director") ? ` · ${w.boards} other ${w.boards === 1 ? "board" : "boards"}` : ""}</>}
                  </div>
                  {theirs.length > 0 && (
                    <div className="wother">
                      {theirs.slice(0, 3).map((a) => <Link key={a.company_number} to={`/c/${a.company_number}`}>{a.company_name ?? a.company_number}</Link>)}
                      {theirs.length > 3 && <span className="faint"> +{theirs.length - 3} more</span>}
                    </div>
                  )}
                </div>
                <div className="wpct">
                  {pctText ? <><b>{pctText}</b><span className="mini"><i style={{ width: `${w.pct ?? w.band?.[0] ?? 0}%`, background: w.colour }} /></span></> : <span className="faint small">—</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!ch?.fetched && ch?.enabled && <div className="faint small" style={{ marginTop: 8 }}>Directors and exact shareholdings appear once fetched from Companies House.</div>}
      {(ch?.fetched?.psc_statements ?? []).filter((x) => !x.ceased_on).map((x, i) => (
        <div key={i} className="faint small" style={{ marginTop: 6 }}>Statement: {x.statement?.replace(/-/g, " ")}</div>
      ))}
      {former.length > 0 && <div className="faint small" style={{ marginTop: 10 }}>Former: {former.slice(0, 10).join(", ")}{former.length > 10 ? ` +${former.length - 10}` : ""}</div>}
    </section>
  );
}
