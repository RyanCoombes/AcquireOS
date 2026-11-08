/* Company profile sections: financial overview (chart and trend table),
   charges and investment signals, and finding the website. */
import type React from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { Hint, WatchButton } from "./bits";
import { date, money, filingLabel } from "../format";

type FinSummary = NonNullable<CompanyDetail["fin_summary"]>;

const fmtValue = (key: string, v: number) =>
  key === "employees" ? Math.round(v).toLocaleString("en-GB") : key === "debt_ratio" ? `${Math.round(v)}%` : money(v);

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
                <b className={r.estimated ? "estval" : ""} title={r.estimated ? "Estimate: staff × the company's own revenue per head from its last accounts with turnover" : undefined}>
                  {r.estimated ? "≈" : ""}{fmtValue(r.key, r.value)}{r.estimated ? " est." : ""}</b>
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
      <p className="faint small">From the filed accounts.{s.rows.some((r) => r.estimated) ? <> ≈ is an estimate<Hint text="Staff × the company's own revenue per head. Dashed on the charts." /></> : null}</p>
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
      {ch?.charges?.length ? (() => {
        const live = ch.charges.filter((x) => x.status !== "fully-satisfied");
        const repaid = ch.charges.filter((x) => x.status === "fully-satisfied");
        const table = (rows: typeof ch.charges) => (
          <table style={{ marginTop: 8 }}>
            <thead><tr><th>Held by</th><th>Status</th><th className="hide-sm">Type</th><th>Created</th><th className="hide-sm">Repaid</th></tr></thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.charge_id}>
                  <td>{x.holders.join(", ") || "—"}{x.particulars ? <div className="sub">{x.particulars.slice(0, 140)}</div> : null}</td>
                  <td>{x.status === "outstanding" ? <b className="neg">Outstanding</b> : x.status === "part-satisfied" ? "Part repaid" : "Repaid"}</td>
                  <td className="hide-sm small">{x.classification ?? ""}</td>
                  <td>{date(x.created_on)}</td>
                  <td className="hide-sm">{x.satisfied_on ? date(x.satisfied_on) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>);
        const yrs = repaid.map((x) => (x.created_on ?? "").slice(0, 4)).filter(Boolean).sort();
        return (
          <>
            {live.length ? table(live) : <div className="faint" style={{ marginTop: 6 }}>Nothing outstanding.</div>}
            {repaid.length > 0 && <Fold label={`${repaid.length} repaid ${repaid.length === 1 ? "charge" : "charges"}${yrs.length ? ` (${yrs[0]}${yrs[yrs.length - 1] !== yrs[0] ? `–${yrs[yrs.length - 1]}` : ""})` : ""}`}>{table(repaid)}</Fold>}
          </>
        );
      })() : null}
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
  // You found it yourself: save it as the website without the check.
  const [manual, setManual] = useState<string | null>(null);
  const saveManual = async (u: string) => {
    setBusy(true); setErr(null);
    try {
      const site = /^https?:\/\//.test(u) ? u : `https://${u.replace(/^\/+/, "")}`;
      await api.saveEnrichment(num, { website: site, source_url: site, confidence: "high", source_label: "Added by me (not checked)" });
      setManual(site); setRes(null); onSaved();
    } catch (e: any) { setErr(e.message); }
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
        <button className="btn quiet" disabled={busy || !url.trim()} onClick={() => saveManual(url.trim())}
                title="Save it as the website without checking it">Save without checking</button>
      </div>
      {manual && <div className="pos" style={{ marginTop: 8 }}>Saved {manual.replace(/^https?:\/\/(www\.)?/, "")} as the website (added by you).</div>}
      {err && <div className="callout red">{err}</div>}
      {res && (
        <div style={{ marginTop: 8 }}>
          <div className={res.saved ? "pos" : "muted"}>{res.message}
            {!res.saved && url.trim() && <> <button className="btn quiet" disabled={busy} onClick={() => saveManual(url.trim())}>Save {url.trim()} anyway</button></>}</div>
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
      <p className="faint small" style={{ marginTop: 6 }}>Saved only if the site shows the company number or postcode.</p>
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

const cap1 = (t: string) => t.toLowerCase().replace(/(^|[\s-])\w/g, (m) => m.toUpperCase());
const niceClass = (c: string) => cap1(c.replace(/\bSHARES?\b/i, "").trim()) || "Ordinary";

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
      {ch?.filings?.length ? (() => {
        const row = (f: (typeof ch.filings)[number]) => (
          <div key={f.transaction_id} className="tl">
            <span className="tdate">{date(f.filed_on)}</span>
            <span className="tdesc"><b>{filingLabel(f.type, f.description)}</b></span>
          </div>);
        // Accounts on time or late, year by year (late = after the 9-month deadline).
        const late = new Set((ch.late_filings ?? []).map((l) => String(l.made_up_to).slice(0, 10)));
        const accts = ch.filings.filter((f) => (f.type ?? "").toUpperCase() === "AA" && (f as any).detail?.made_up_date)
          .map((f) => ({ mu: String((f as any).detail.made_up_date).slice(0, 10), filed: f.filed_on }))
          .sort((a, b) => a.mu.localeCompare(b.mu)).slice(-10);
        return (
          <>
            {accts.length > 1 && (
              <div className="frecord">
                <div className="label">Accounts filed</div>
                <div className="fr-dots">
                  {accts.map((a) => (
                    <span key={a.mu} className={late.has(a.mu) ? "late" : "ok"} title={`Year to ${date(a.mu)}: filed ${date(a.filed)}${late.has(a.mu) ? " (late)" : " (on time)"}`}>
                      <i />{a.mu.slice(0, 4)}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="timeline">{ch.filings.slice(0, 6).map(row)}</div>
            {ch.filings.length > 6 && <Fold label={`${ch.filings.length - 6} older filings`}><div className="timeline">{ch.filings.slice(6, 40).map(row)}</div>
              {ch.filings.length > 40 && <a className="small" href={`https://find-and-update.company-information.service.gov.uk/company/${c.company_number}/filing-history`} target="_blank" rel="noreferrer">All {ch.filings.length} filings ↗</a>}</Fold>}
          </>
        );
      })() : <div className="faint">Fetch Companies House details (Refresh at the top) to see the filing history.</div>}
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

/** What control an owner has besides shares, e.g. "appoints directors". */
function controlText(natures: string[]): string | null {
  const bits: string[] = [];
  if (natures.some((n) => n.startsWith("voting-rights"))) {
    const v = natures.map((n) => n.match(/voting-rights-(\d+)-to-(\d+)-percent/)).find(Boolean);
    if (v) bits.push(`${v[1]}–${v[2]}% of votes`);
  }
  if (natures.some((n) => n.startsWith("right-to-appoint-and-remove-directors"))) bits.push("appoints directors");
  if (natures.some((n) => n.startsWith("significant-influence-or-control"))) bits.push("significant influence or control");
  return bits.length ? bits.join(", ") : null;
}

const OWN_LABEL: Record<string, string> = { owner_held: "Owner-held", group_owned: "Group-owned", investor_backed: "Investor-backed",
  eot: "Employee-owned (EOT)", trust: "Held in trust", foreign_owned: "Foreign parent" };

const SEG_COLOURS = ["var(--teal)", "var(--orange)", "var(--blue)", "var(--purple)", "var(--amber)", "var(--green)"];

type Who = {
  key: string; name: string; company: boolean; roles: Set<string>; pct: number | null; band: [number, number] | null;
  personId?: number; birthYear: number | null; since: string | null; boards: number; officerKey?: string; regNo?: string | null;
  ultimately: string[]; colour?: string; left?: string | null; note?: { warn: boolean; text: string };
  control?: string | null; est?: number;
  occupation?: string | null; residence?: string | null; nationality?: string | null; classes?: Set<string>;
  disq?: { from: string | null; until: string | null; reason: string | null; companies: string[] }[];
};

export function OwnersDirectors({ data, flags }: { data: CompanyDetail; flags?: React.ReactNode }) {
  const [view, setView] = useState<"now" | "time">("now");
  const ch = data.ch;
  const own = data.ownership;
  const isCo = (n: string) => /\b(LIMITED|LTD|PLC|LLP|TRUST|NOMINEES?)\b/i.test(n);
  const keyOf = (name: string, company: boolean) => (company ? "C:" : "P:") + personKey(name, company);
  const map = new Map<string, Who>();
  const get = (name: string, company: boolean): Who => {
    const k = keyOf(name, company);
    let w = map.get(k);
    if (!w) {
      w = { key: k, name: niceName(name, company), company, roles: new Set(), pct: null, band: null, birthYear: null, since: null, boards: 0, ultimately: [] };
      map.set(k, w);
    }
    return w;
  };

  // The two sources: the owners register (PSC, bands, updated within 14 days
  // of a change) and the latest confirmation statement (exact, but can be months old).
  const shareholders = ch?.shareholders ?? [];
  const asAt = shareholders[0]?.as_at ?? null;
  const stmt = new Map<string, { name: string; pct: number }>();
  const classesOf = new Map<string, Set<string>>();
  for (const s of shareholders) {
    const k = keyOf(s.name, isCo(s.name));
    stmt.set(k, { name: s.name, pct: Math.round(((stmt.get(k)?.pct ?? 0) + (s.pct ?? 0)) * 10) / 10 });
    if (s.share_class) classesOf.set(k, (classesOf.get(k) ?? new Set()).add(niceClass(s.share_class)));
  }
  const allClasses = [...new Set(shareholders.map((s) => s.share_class).filter(Boolean).map((c) => niceClass(c!)))];
  const pk = (p: { name: string; kind: string }) => keyOf(p.name, p.kind !== "individual");
  // The owners register from the API when fetched (fresher than the monthly
  // file); links to the Owners page come from the matching bulk record.
  const bulkIds = new Map(data.people.map((p) => [pk(p) + "|" + (p.notified_on ?? ""), p.person_id]));
  const register: CompanyDetail["people"] = ch?.fetched?.psc
    ? ch.fetched.psc.map((p) => ({ ...p, role: "psc", person_id: bulkIds.get(pk(p) + "|" + (p.notified_on ?? "")) ?? 0 }))
    : data.people;
  const fromApi = !!ch?.fetched?.psc;
  const current = register.filter((p) => !p.ceased_on);
  const ceased = register.filter((p) => p.ceased_on);
  const dates = register.flatMap((p) => [p.notified_on, p.ceased_on]).filter(Boolean).sort() as string[];
  const lastChange = dates[dates.length - 1] ?? null;
  const joined = current.filter((p) => p.notified_on === lastChange);
  const leftOn = ceased.filter((p) => p.ceased_on === lastChange);
  const disagree = shareholders.length > 0 && (
    current.some((p) => { const b = band(p.natures); const s = stmt.get(pk(p)); return !!b && (!s || s.pct < b[0] - 0.5 || s.pct > b[1] + 0.5); })
    || ceased.some((p) => (stmt.get(pk(p))?.pct ?? 0) > 25.5));
  const registerNewer = !!(lastChange && asAt && lastChange > asAt);
  // Exact figures only when the statement is at least as new as the register and agrees with it.
  const useStatement = shareholders.length > 0 && !disagree && !registerNewer;
  const stmtLabel = asAt ? `the statement of ${date(asAt)}` : "the last statement";

  for (const p of current) {
    const w = get(p.name, p.kind !== "individual");
    w.roles.add("Owner");
    w.band = band(p.natures) ?? w.band;
    w.personId = p.person_id || undefined;
    w.birthYear = w.birthYear ?? p.birth_year;
    w.regNo = p.registration_number;
    w.since = w.since ?? p.notified_on;
    w.control = controlText(p.natures);
    const s = stmt.get(pk(p));
    if (useStatement && s) w.pct = s.pct;
    else if (s) w.note = { warn: false, text: `${stmtLabel.charAt(0).toUpperCase() + stmtLabel.slice(1)} showed ${s.pct}%` };
  }
  const ceasedKeys = new Set(ceased.map(pk));
  const stillHolding = new Set<string>();
  for (const [k, s] of stmt) {
    if (map.has(k)) continue;
    if (ceasedKeys.has(k) && !useStatement) continue;  // left the register after the statement: a previous owner
    const w = get(s.name, k.startsWith("C:"));
    w.roles.add("Shareholder");
    w.pct = s.pct;
    w.classes = classesOf.get(k);
    stillHolding.add(k);
    const gone = ceased.find((p) => pk(p) === k);
    if (gone) {
      w.left = gone.ceased_on; w.personId = gone.person_id || undefined; w.birthYear = w.birthYear ?? gone.birth_year;
      w.note = { warn: false, text: `Off the owners register since ${date(gone.ceased_on)}: holdings of 25% or less aren't listed there` };
    } else if (!useStatement) {
      w.note = s.pct > 25.5
        ? { warn: true, text: `${stmtLabel.charAt(0).toUpperCase() + stmtLabel.slice(1)} shows ${s.pct}%, but they're not on the owners register` }
        : { warn: false, text: `From ${stmtLabel}; 25% or less isn't on the owners register` };
    }
  }
  for (const o of (ch?.officers ?? []).filter((x) => !x.resigned_on)) {
    const w = get(o.name, /corporate/.test(o.role ?? ""));
    w.roles.add((o.role ?? "").includes("secretary") ? "Secretary" : "Director");
    w.birthYear = w.birthYear ?? o.birth_year;
    w.since = o.appointed_on && (!w.since || o.appointed_on < w.since) ? o.appointed_on : w.since;
    w.boards = Math.max(w.boards, o.other_current);
    w.officerKey = o.officer_key;
    w.occupation = w.occupation ?? o.occupation; w.residence = w.residence ?? o.residence; w.nationality = w.nationality ?? o.nationality;
    const dq = (ch?.disqualified ?? []).filter((d) => d.officer_key === o.officer_key);
    if (dq.length) w.disq = dq.map((d) => ({ from: d.disqualified_from, until: d.disqualified_until, reason: d.reason, companies: d.company_names ?? [] }));
  }
  for (const u of own?.ultimate_owners ?? []) {
    if (!u.via.length) continue;
    const via = u.via[0].toUpperCase();
    const parent = [...map.values()].find((w) => w.company && ((w.regNo ?? "").toUpperCase() === via || w.key === "C:" + personKey(via, true)));
    if (parent) parent.ultimately.push(niceName(u.name, false) + (u.birth_year ? ` (${new Date().getFullYear() - u.birth_year})` : ""));
  }

  const people = [...map.values()].sort((a, b) =>
    (b.pct ?? b.band?.[0] ?? -1) - (a.pct ?? a.band?.[0] ?? -1) || Number(b.roles.has("Director")) - Number(a.roles.has("Director")));
  const owners = people.filter((w) => (useStatement ? w.pct : w.band?.[0]));
  owners.forEach((w, i) => { w.colour = SEG_COLOURS[i % SEG_COLOURS.length]; });
  people.filter((w) => !w.colour && (w.pct || w.band)).forEach((w, i) => { w.colour = SEG_COLOURS[(owners.length + i) % SEG_COLOURS.length]; });
  // Register bands only: estimate each owner's share within their band so the
  // named owners add up to 100% where the bands allow (two at 25–50% ≈ 50% each).
  if (!useStatement && owners.length) {
    const lo = owners.reduce((t, w) => t + w.band![0], 0), hi = owners.reduce((t, w) => t + w.band![1], 0);
    const f = hi > lo ? Math.max(0, Math.min(1, (100 - lo) / (hi - lo))) : 0;
    for (const w of owners) w.est = Math.round(w.band![0] + (w.band![1] - w.band![0]) * f);
  }
  const share = (w: Who) => (useStatement ? w.pct ?? 0 : w.est ?? w.band![0]);
  const shown = owners.reduce((t, w) => t + share(w), 0);
  const others = ch?.other_appointments ?? [];
  const prevOwners = ceased.filter((p) => !stillHolding.has(pk(p)) && !map.get(pk(p))?.roles.has("Owner"))
    .sort((x, y) => String(y.ceased_on).localeCompare(String(x.ceased_on)));
  const prevDirectors = (ch?.officers ?? []).filter((o) => o.resigned_on)
    .sort((x, y) => String(y.resigned_on).localeCompare(String(x.resigned_on)));
  const names = (ps: { name: string; kind: string }[]) => {
    const n = ps.map((p) => niceName(p.name, p.kind !== "individual"));
    return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : n[0];
  };
  const filingsUrl = `https://find-and-update.company-information.service.gov.uk/company/${data.company.company_number}/filing-history`;

  return (
    <section id="ownership">
      <Head icon="owners" tone="orange" title="Owners & directors" aside={flags} />
      <div className="tabs2" role="tablist" style={{ borderBottom: "1px solid var(--line)", marginBottom: 12 }}>
        <button role="tab" aria-selected={view === "now"} className={view === "now" ? "on" : ""} onClick={() => setView("now")}>Now</button>
        <button role="tab" aria-selected={view === "time"} className={view === "time" ? "on" : ""} onClick={() => setView("time")}>Over time</button>
      </div>
      {view === "time" ? <Tenure register={register} officers={ch?.officers ?? []} since={data.company.incorporation_date} /> : <>
      {data.enrichment?.ownership && (
        <div className="callout amber" style={{ marginBottom: 10 }}>
          <b>Research: {OWN_LABEL[data.enrichment.ownership] ?? data.enrichment.ownership}.</b> {data.enrichment.ownership_note ?? ""}{" "}
          <span className="faint small">This overrides Companies House in scoring. The register below may be out of date.</span>
        </div>
      )}
      {useStatement ? (
        <p style={{ margin: "0 0 4px" }}><b>{stmt.size} {stmt.size === 1 ? "shareholder" : "shareholders"}
          {owners[0] ? `; largest ${owners[0].name} with ${owners[0].pct}%` : ""}.</b>
          {allClasses.length > 1 && <span className="faint"> {allClasses.length} share classes: {allClasses.join(", ")}. Different classes can carry different votes or dividends: check the articles.</span>}</p>
      ) : own && own.ownership_type !== "unknown" && <p style={{ margin: "0 0 4px" }}><b>{ownSentence(own.explanation)}</b></p>}
      {lastChange && (joined.length > 0 || leftOn.length > 0) && (
        <p className="small" style={{ margin: "0 0 10px" }}>
          <span className="chip">Ownership changed {date(lastChange)}</span>{" "}
          {joined.length > 0 && <>{names(joined)} {joined.length === 1 ? "became an owner" : "became owners"}</>}
          {joined.length > 0 && leftOn.length > 0 && "; "}
          {leftOn.length > 0 && <>{names(leftOn)} left</>}.
        </p>
      )}

      {owners.length > 0 && (
        <>
          <div className="ownbar" role="img" aria-label="Ownership split">
            {owners.map((w) => (
              <i key={w.key} style={{ width: `${share(w)}%`, background: w.colour }}
                 title={`${w.name}: ${useStatement ? `${w.pct}%` : `${w.band![0]}–${w.band![1]}%, about ${w.est}%`}`} />
            ))}
            {shown < 99.5 && <i className="rest" style={{ width: `${100 - shown}%` }}
                                title={useStatement ? "Not accounted for on the statement" : "Holders of 25% or less (not named on the register)"} />}
          </div>
          <div className="faint small" style={{ margin: "4px 0 12px" }}>
            {useStatement ? `Exact, from the confirmation statement of ${date(asAt)}.`
              : <>Estimated from owners register bands ({fromApi ? `Companies House, ${date(ch!.fetched!.fetched_at)}` : "monthly file"});
                exact figures need a confirmation statement that lists shareholders.
                {shareholders.length > 0 && <> {stmtLabel.charAt(0).toUpperCase() + stmtLabel.slice(1)}
                  {registerNewer ? " is older than the last change" : " disagrees"}, so it's shown as notes. <a href={filingsUrl} target="_blank" rel="noreferrer">Filings ↗</a></>}</>}
            {shown < 99.5 && <> Hatched: {useStatement ? `${Math.round(100 - shown)}% not accounted for on the statement` : `about ${Math.round(100 - shown)}% held by people with 25% or less, who aren't named`}.</>}
          </div>
        </>
      )}

      {people.length === 0 ? <div className="faint">No owners or directors on file.</div> : (
        <div className="whos">
          {people.map((w) => {
            const theirs = w.officerKey ? others.filter((a) => a.officer_key === w.officerKey && !a.resigned_on) : [];
            const age = w.birthYear ? new Date().getFullYear() - w.birthYear : null;
            const yrs = yearsSince(w.since);
            const pctText = (useStatement || !w.band) && w.pct != null ? `${w.pct}%` : w.band ? `${w.band[0]}–${w.band[1]}%` : null;
            const barW = (useStatement || !w.band) && w.pct != null ? w.pct : w.est ?? w.band?.[0] ?? 0;
            const showAge = !w.company && (age || w.roles.has("Director") || w.roles.has("Secretary"));
            return (
              <div key={w.key} className="who">
                <span className="dot" style={{ background: w.colour ?? "var(--grey-soft)" }} />
                <div className="wmain">
                  <div className="wname">
                    {w.personId ? <Link to={`/owners/${w.personId}`}>{w.name}</Link> : w.name}
                    {w.officerKey ? <WatchButton small kind="director" refId={w.officerKey} label={w.name}
                                                 on={(data.watched_officers ?? []).includes(w.officerKey)} />
                      : w.personId ? <WatchButton small kind="owner" refId={String(w.personId)} label={w.name}
                                                       on={(data.watched_owners ?? []).includes(String(w.personId))} /> : null}
                    {(w.personId || w.officerKey) && !w.company && (
                      <Link className="wconn" to={`/connections/n/${encodeURIComponent(w.personId ? `p:${w.personId}` : `o:${w.officerKey}`)}`}
                            title="Everything this person owns or directs">Connections</Link>)}
                    {[...w.roles].filter((r) => r !== "Shareholder" || !w.roles.has("Owner")).map((r) =>
                      <span key={r} className={`role ${r === "Shareholder" ? "owner" : r.toLowerCase()}`}>
                        {r === "Shareholder" ? "Owner" : r === "Owner" && !w.band && w.pct == null && w.control ? "Controls" : r}</span>)}
                  </div>
                  <div className="wmeta">
                    {w.company ? <>Company{w.regNo ? <> · <Link to={`/c/${w.regNo}`}>{w.regNo}</Link></> : null}
                      {w.since ? ` · since ${date(w.since)}` : ""}{w.ultimately.length ? <> · owned by {w.ultimately.join(", ")}</> : null}</>
                      : showAge ? <>{age ? `Age ${age}` : "Age not known"}{yrs !== null ? ` · ${yrs} ${yrs === 1 ? "yr" : "yrs"}` : ""}
                          {w.roles.has("Director") ? ` · ${w.boards} other ${w.boards === 1 ? "board" : "boards"}` : ""}</> : "Shareholder"}
                  </div>
                  {(w.occupation || w.residence || w.nationality) && !w.company && (
                    <div className="wmeta">
                      {w.occupation ? <span className={/retired/i.test(w.occupation) ? "role owner" : ""}>{cap1(w.occupation)}</span> : null}
                      {w.residence ? `${w.occupation ? " · " : ""}lives in ${cap1(w.residence)}` : ""}
                      {w.nationality ? ` · ${cap1(w.nationality)}` : ""}
                    </div>
                  )}
                  {w.classes && (allClasses.length > 1 || [...w.classes].some((c) => !/^ordinary$/i.test(c))) &&
                    <div className="wmeta">Shares: {[...w.classes].join(", ")}</div>}
                  {w.disq?.map((d, i) => (
                    <div key={i} className="wnote warn"><b>Disqualified director</b> {d.from ? `from ${date(d.from)}` : ""}{d.until ? ` to ${date(d.until)}` : ""}
                      {d.reason ? `: ${d.reason}` : ""}{d.companies.length ? ` (${d.companies.slice(0, 3).join(", ")})` : ""}</div>
                  ))}
                  {w.control && (!w.band || w.pct == null) && <div className="wnote">Control: {w.control}</div>}
                  {w.note && <div className={`wnote ${w.note.warn ? "warn" : ""}`}>{w.note.text}</div>}
                  {theirs.length > 0 && (
                    <div className="wother">
                      {theirs.slice(0, 3).map((a) => <Link key={a.company_number} to={`/c/${a.company_number}`}>{a.company_name ?? a.company_number}</Link>)}
                      {theirs.length > 3 && <span className="faint"> +{theirs.length - 3} more</span>}
                    </div>
                  )}
                </div>
                <div className="wpct">
                  {pctText ? <><b>{pctText}</b>{w.est != null && !(useStatement && w.pct != null) && w.band && w.band[0] !== w.band[1] && <div className="faint small">≈{w.est}%</div>}<span className="mini"><i style={{ width: `${barW}%`, background: w.colour }} /></span></> : <span className="faint small">—</span>}
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

      {(prevOwners.length > 0 || prevDirectors.length > 0) && (
        <Fold label={[prevOwners.length ? `${prevOwners.length} previous ${prevOwners.length === 1 ? "owner" : "owners"}` : "",
                      prevDirectors.length ? `${prevDirectors.length} previous ${prevDirectors.length === 1 ? "director" : "directors"}` : ""].filter(Boolean).join(" and ")}>
        <div className="prev">
          {prevOwners.length > 0 && (
            <>
              <h3 className="subh">Previous owners</h3>
              {prevOwners.map((p) => {
                const b = band(p.natures);
                const s = stmt.get(pk(p));
                return (
                  <div key={p.person_id + String(p.ceased_on)} className="prow">
                    <span className="pn">{p.person_id ? <Link to={`/owners/${p.person_id}`}>{niceName(p.name, p.kind !== "individual")}</Link> : niceName(p.name, p.kind !== "individual")}
                      {s && <span className="faint"> · {stmtLabel} showed {s.pct}%</span>}</span>
                    <span className="pb">{b ? `${b[0]}–${b[1]}%` : ""}</span>
                    <span className="pd">{p.notified_on ? date(p.notified_on) : "?"} – {date(p.ceased_on)}</span>
                  </div>
                );
              })}
            </>
          )}
          {prevDirectors.length > 0 && (
            <>
              <h3 className="subh">Previous directors</h3>
              {prevDirectors.slice(0, 12).map((o) => (
                <div key={o.officer_key + o.role} className="prow">
                  <span className="pn">{niceName(o.name, false)}</span>
                  <span className="pb">{(o.role ?? "").replace(/-/g, " ")}</span>
                  <span className="pd">{o.appointed_on ? date(o.appointed_on) : "?"} – {date(o.resigned_on)}</span>
                </div>
              ))}
              {prevDirectors.length > 12 && <div className="faint small">+{prevDirectors.length - 12} more</div>}
            </>
          )}
        </div>
        </Fold>
      )}
      </>}
    </section>
  );
}


/** A bar that opens to show older detail (previous people, repaid charges…). */
export function Fold({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`fold ${open ? "open" : ""}`}>
      <button className="fold-bar" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{open ? "▾" : "▸"} {label}</span><b>{open ? "Hide" : "Show"}</b>
      </button>
      {open && <div className="fold-body">{children}</div>}
    </div>
  );
}

/** Owners and directors over time: when each joined and left. */
function Tenure({ register, officers, since }: {
  register: { name: string; kind: string; notified_on: string | null; ceased_on: string | null; natures?: string[] }[];
  officers: { officer_key: string; name: string; role: string | null; appointed_on: string | null; resigned_on: string | null }[];
  since: string | null;
}) {
  type Bar = { name: string; what: "owner" | "director"; from: string | null; to: string | null; note?: string };
  const bars: Bar[] = [
    ...register.map((p) => ({ name: niceName(p.name, p.kind !== "individual"), what: "owner" as const, from: p.notified_on, to: p.ceased_on,
                              note: (() => { const b = band(p.natures ?? []); return b ? `${b[0]}–${b[1]}%` : undefined; })() })),
    ...officers.filter((o) => !(o.role ?? "").includes("secretary"))
      .map((o) => ({ name: niceName(o.name, false), what: "director" as const, from: o.appointed_on, to: o.resigned_on })),
  ];
  if (!bars.length) return <div className="faint">No owners or directors on file.</div>;
  // One row per person, owner and director bars on it; current people first, then by start.
  const people = new Map<string, Bar[]>();
  for (const b of bars) people.set(b.name.toUpperCase(), [...(people.get(b.name.toUpperCase()) ?? []), b]);
  const rows = [...people.values()].sort((a, b) => Number(b.some((x) => !x.to)) - Number(a.some((x) => !x.to))
    || String(a[0].from ?? "").localeCompare(String(b[0].from ?? "")));
  const t = (d: string | null) => (d ? new Date(d).getTime() : null);
  const now = Date.now();
  const starts = bars.map((b) => t(b.from)).filter((x): x is number => x !== null);
  const t0 = Math.min(...(since ? [t(since)!] : []), ...starts, now - 5 * 3.156e10);
  const span = now - t0 || 1;
  const pct = (x: number) => (100 * (x - t0)) / span;
  const y0 = new Date(t0).getFullYear(), y1 = new Date(now).getFullYear();
  const step = Math.max(1, Math.ceil((y1 - y0) / 8));
  const ticks: number[] = []; for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) ticks.push(y);
  return (
    <div className="tenure">
      <div className="tn-axis">{ticks.map((y) => <span key={y} style={{ left: `${pct(new Date(y, 0, 1).getTime())}%` }}>{y}</span>)}</div>
      {rows.map((r) => (
        <div key={r[0].name + r[0].what} className="tn-row">
          <div className="tn-name">{r[0].name}<div className="faint small">{[...new Set(r.map((b) => b.what))].join(" and ")}</div></div>
          <div className="tn-track">
            {ticks.map((y) => <i key={y} className="tn-grid" style={{ left: `${pct(new Date(y, 0, 1).getTime())}%` }} />)}
            {r.map((b, i) => {
              const a = t(b.from) ?? t0, z = t(b.to) ?? now;
              return (
                <span key={i} className={`tn-bar ${b.what} ${b.to ? "ended" : ""}`} style={{ left: `${pct(a)}%`, width: `${Math.max(0.8, pct(z) - pct(a))}%`, top: b.what === "owner" ? 4 : 18 }}
                      title={`${b.what === "owner" ? "Owner" : "Director"}${b.note ? ` (${b.note})` : ""}: ${b.from ? date(b.from) : "before records"} – ${b.to ? date(b.to) : "now"}`}>
                  {b.note && b.what === "owner" ? <em>{b.note}</em> : null}
                </span>
              );
            })}
          </div>
          <div className="tn-dates small">
            {r.map((b, i) => <div key={i}>{b.from ? new Date(b.from).getFullYear() : "?"}–{b.to ? new Date(b.to).getFullYear() : "now"}</div>)}
          </div>
        </div>
      ))}
      <div className="tn-key"><span><i className="tn-k owner" />Owner</span><span><i className="tn-k director" />Director</span><span><i className="tn-k ended" />Left</span><span className="faint">Hover a bar for the exact dates</span></div>
    </div>
  );
}
