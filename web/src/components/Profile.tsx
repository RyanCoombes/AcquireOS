/* Company profile sections: financial overview (chart and trend table),
   charges and investment signals, and finding the website. */
import { useState } from "react";
import { api, type CompanyDetail } from "../api";
import { date, money } from "../format";

type FinSummary = NonNullable<CompanyDetail["fin_summary"]>;

const fmtValue = (key: string, v: number) =>
  key === "employees" ? Math.round(v).toLocaleString("en-GB") : key === "debt_ratio" ? `${Math.round(v)}%` : money(v, { precise: v < 1e6 });

const fmtChange = (key: string, v: number) =>
  key === "employees" ? Math.abs(Math.round(v)).toLocaleString("en-GB") : key === "debt_ratio" ? `${Math.abs(Math.round(v))} pts` : money(Math.abs(v));

/** Assets, net assets and liabilities over the years, like a balance-sheet strip. */
function BalanceChart({ series }: { series: FinSummary["series"] }) {
  const pts = series.filter((s) => s.total_assets != null || s.net_assets != null);
  if (pts.length < 2) return null;
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
      <p className="faint small">Total assets and liabilities are worked out from the totals the accounts state (small companies rarely give them
        directly). Debt ratio is liabilities as a share of assets.</p>
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
      <div className="sechead">
        <h2>Charges and investment</h2>
        <span className="faint small">Loans secured on the company's assets, and signs of outside investors</span>
        {ch?.enabled && <span className="right"><button className="btn quiet" disabled={busy} onClick={fetchIt}>
          {busy ? "Fetching…" : ch.fetched ? "Refresh from Companies House" : "Fetch details from Companies House"}</button></span>}
      </div>
      <p style={{ margin: "0 0 10px" }}>
        {c.charges_total == null ? <span className="faint">No charge counts loaded yet (they come with the register refresh).</span>
          : c.charges_total === 0 ? "No charges registered: no secured lending on record."
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
          ? ch.fetched ? <>Details from Companies House, fetched {date(ch.fetched.fetched_at)}{ch.fetched.error ? ` (last attempt failed: ${ch.fetched.error})` : ""}.</>
            : "Fetch the details to see who holds each charge and whether new shares have been issued."
          : <>Who holds each charge, and share issues, come from the free Companies House API. Add your key as <code>CH_API_KEY</code> in
              the stack to fetch them here. Meanwhile: <a href={`https://find-and-update.company-information.service.gov.uk/company/${num}/charges`}
              target="_blank" rel="noreferrer">charges on Companies House ↗</a></>}
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
      <p className="faint small" style={{ marginTop: 6 }}>Tries domains from the company's current, previous, parent and subsidiary names, and
        only saves a site that shows the company number or registered postcode.</p>
    </div>
  );
}
