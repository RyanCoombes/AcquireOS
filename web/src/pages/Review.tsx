/* Review one company at a time, fast. Score your criteria with the number
   keys, then shortlist, watch, assess, pass or reject with one key. */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type CompanyDetail, type Status } from "../api";
import { ErrorLine, Score, Signals, StatusMark, Toast, useAsync } from "../components/bits";
import MyScores from "../components/MyScores";
import { RuleOutChips } from "../components/RuleOut";
import SicPicker from "../components/SicPicker";
import { ageFrom, chUrl, date, int, money, OWNERSHIP, range, toNum, years } from "../format";

const ACTIONS: { key: string; status: Status; label: string; cls?: string }[] = [
  { key: "s", status: "approach", label: "Shortlist", cls: "primary" },
  { key: "a", status: "researching", label: "Assess further" },
  { key: "w", status: "watching", label: "Watch" },
  { key: "p", status: "passed", label: "Pass" },
  { key: "r", status: "rejected", label: "Reject" },
];

export default function Review() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "new";
  const minScore = params.get("min_score") ?? "";
  const sic = params.get("sic") ?? "";
  const bb = params.get("bb") ?? "";
  const bbId = /^\d+$/.test(bb) ? Number(bb) : null;
  const q: Record<string, string> = { status, bb: bb || "all" };
  if (minScore) q.min_score = minScore;
  if (sic) q.sic = sic;
  const queue = useAsync(() => api.review(q), [status, minScore, sic, bb]);
  const meta = useAsync(() => api.meta(), []);
  const [i, setI] = useState(0);
  const [done, setDone] = useState<Record<string, Status>>({});
  const [focus, setFocus] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => { setI(0); setDone({}); }, [status, minScore, sic, bb]);

  const rows = queue.data?.rows ?? [];
  const cur = rows[i];
  const detail = useAsync(() => (cur ? api.company(cur.company_number, bbId) : Promise.resolve(null)), [cur?.company_number, bbId]);
  // fetch the next one in advance so moving on is instant
  useEffect(() => { if (rows[i + 1]) api.company(rows[i + 1].company_number, bbId).catch(() => {}); }, [i, rows, bbId]);
  useEffect(() => { setFocus(0); setNote(""); }, [cur?.company_number]);

  const d = detail.data as CompanyDetail | null;
  const criteria = d?.manual.criteria ?? [];

  const act = useCallback(async (st: Status, why?: string) => {
    if (!cur) return;
    try {
      await api.setState(cur.company_number, { status: st, stage_note: why ?? "Set in review" });
      if (note.trim()) await api.addNote(cur.company_number, note.trim());
    } catch (e: any) { setToast(`Not saved: ${e.message}`); return; }  // stay on this company
    setDone((x) => ({ ...x, [cur.company_number]: st }));
    setToast(`${cur.name}: ${why ?? meta.data?.statuses.find((s) => s.value === st)?.label ?? st}`);
    setI((x) => Math.min(x + 1, rows.length));
  }, [cur, note, rows.length, meta.data]);

  const score = useCallback(async (n: number) => {
    if (!cur || !criteria[focus]) return;
    await api.setManual(cur.company_number, criteria[focus].key, n);
    detail.reload();
    setFocus((f) => Math.min(f + 1, criteria.length - 1));
  }, [cur, criteria, focus, detail]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      const k = e.key.toLowerCase();
      if (/^[0-5]$/.test(k)) { e.preventDefault(); score(Number(k)); return; }
      if (k === "arrowdown") { e.preventDefault(); setFocus((f) => Math.min(f + 1, criteria.length - 1)); return; }
      if (k === "arrowup") { e.preventDefault(); setFocus((f) => Math.max(f - 1, 0)); return; }
      if (k === "arrowright" || k === " " || k === "j") { e.preventDefault(); setI((x) => Math.min(x + 1, rows.length)); return; }
      if (k === "arrowleft" || k === "k") { e.preventDefault(); setI((x) => Math.max(x - 1, 0)); return; }
      if (k === "o" && cur) { nav(`/c/${cur.company_number}${bbId ? `?bb=${bbId}` : ""}`); return; }
      const a = ACTIONS.find((x) => x.key === k);
      if (a) { e.preventDefault(); act(a.status); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [score, act, criteria.length, rows.length, cur, nav]);

  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (!v) p.delete(k); else p.set(k, v);
    setParams(p, { replace: true });
  };
  const reviewed = Object.keys(done).length;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Review</h1>
          <div className="lede">
            <b className="ink">{bbId ? meta.data?.buy_boxes.find((b) => b.id === bbId)?.name : "All buy boxes"}</b>, best first.
            Keys <span className="kbd">0</span>–<span className="kbd">5</span> to score, one key to decide.
          </div>
        </div>
      </div>
      <div className="band">
        <div className="field">
          <label htmlFor="rv-bb">Buy box</label>
          <select id="rv-bb" value={bb} className={bb ? "set" : ""} onChange={(e) => set("bb", e.target.value)}>
            <option value="">Any buy box</option>
            {meta.data?.buy_boxes.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Queue</label>
          <div className="seg">
            {([["new", "Not reviewed"], ["watching", "Watching"], ["researching", "Assessing"], ["approach", "Shortlisted"]] as const).map(([v, l]) => (
              <button key={v} className={status === v ? "on" : ""} onClick={() => set("status", v === "new" ? null : v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="field">
          <label htmlFor="rv-min">Score at least</label>
          <input id="rv-min" type="number" min={0} max={100} defaultValue={minScore} onBlur={(e) => set("min_score", e.target.value)} />
        </div>
        <div className="field" style={{ minWidth: 340, flex: 1 }}>
          <label>Industry (SIC)</label>
          <SicPicker value={sic.split(",").filter(Boolean)} onChange={(v) => set("sic", v.join(","))} />
        </div>
        <div className="band-actions faint small">
          {queue.data ? <>{int(queue.data.total)} in queue · {reviewed} decided this session</> : ""}
        </div>
      </div>
      <ErrorLine error={queue.error ?? detail.error} />

      {queue.data && !cur && (
        <div className="empty">
          <b>{rows.length ? "End of this queue." : "Nothing to review here."}</b>
          {reviewed ? `${reviewed} companies decided. ` : ""}Choose another queue above, or <Link to="/targets">browse targets</Link>.
        </div>
      )}

      {cur && (
        <div className="review-grid">
          <div>
            <section>
              <div className="crumb">{i + 1} of {rows.length}{done[cur.company_number] ? <> · <StatusMark s={done[cur.company_number]} /></> : null}</div>
              <h1 style={{ fontSize: 24, margin: "2px 0 6px" }}>{cur.name}</h1>
              {d && <div className="rv-chips"><Signals s={d.signals} region={d.company.region}
                titles={d.sold?.sold_to ? { recently_sold: `Sold${d.sold.sold_on ? ` ${date(d.sold.sold_on)}` : ""} to ${d.sold.sold_to}` } : undefined} /></div>}
              {d && <div className="muted small" style={{ margin: "6px 0 10px" }}>
                {[d.company.company_number, townOf(d.company.registered_address), d.company.region,
                  d.company.incorporation_date ? `${years(d.company.incorporation_date)} years` : null,
                  d.sics[0] ? `${d.sics[0].code} ${d.sics[0].description}` : null].filter(Boolean).join(" · ")}
                {" · "}Score <b className="ink"><Score value={d.score?.score ?? null} coverage={d.score?.coverage} /></b>
              </div>}
              {d && <div className="rv-btns">
                {d.enrichment?.website ? <a className="btn primary" href={d.enrichment.website} target="_blank" rel="noreferrer">
                  {d.enrichment.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a>
                  : <FindSite num={cur.company_number} onFound={() => detail.reload()} />}
                <a className="btn" href={chUrl(d.company.company_number)} target="_blank" rel="noreferrer">Companies House ↗</a>
                <Link className="btn" to={`/c/${cur.company_number}${bbId ? `?bb=${bbId}` : ""}`}>Open full page <span className="kbd">O</span></Link>
              </div>}
              {d && (() => {
                const act = [...d.financials].reverse().find((f) => f.principal_activity);
                const text = d.enrichment?.summary ?? act?.principal_activity ?? null;
                return text ? <div className="rv-what"><b>What it does</b>{text}
                  <span className="faint small"> · {d.enrichment?.summary ? "from research" : `its own words, ${date(act!.period_end)} accounts`}</span></div> : null;
              })()}
              {d?.score?.excluded && <div className="callout red" style={{ marginTop: 10 }}>Outside {d.buy_box.name}: {d.score.exclusion}</div>}
            </section>
            {!d ? <section><div className="faint">Loading…</div></section> : <>
              <section><Kpis d={d} /></section>
              <section className="rv-finbox"><FiveYears d={d} num={cur.company_number} /></section>
              <div className="rv-two">
                <section><Owners d={d} /></section>
                <section>
                  <h2>Against your buy box</h2>
                  <div className="rv-fit">
                    {(d.score?.reasons ?? []).filter((r) => !r.manual).map((r) => (
                      <span key={r.key} className={r.status} title={r.text}>
                        {({ good: "✓", partial: "~", miss: "✕", unknown: "?" } as Record<string, string>)[r.status]} {r.label}</span>
                    ))}
                  </div>
                  {d.notes.length > 0 && <div className="muted small" style={{ marginTop: 10 }}>Latest note: “{d.notes[0].body.slice(0, 220)}”</div>}
                </section>
              </div>
            </>}
          </div>
          <aside>
            <section className="rv-dec">
              <h2>Decide</h2>
              {ACTIONS.map((a) => (
                <button key={a.key} className={`btn ${a.cls ?? ""} ${a.status === "rejected" ? "rej" : ""}`} onClick={() => act(a.status)}>
                  {a.label}<span className="kbd">{a.key.toUpperCase()}</span>
                </button>
              ))}
              <div className="rv-lbl">Ruling out? Pick a reason</div>
              <RuleOutChips compact onPick={(p) => act(p.status, p.stage_note)} />
              <textarea placeholder="Note (optional), saved with your decision" value={note} onChange={(e) => setNote(e.target.value)} />
              {criteria.length > 0 && <>
                <div className="rv-lbl">Your scores · <span className="kbd">↑</span><span className="kbd">↓</span> then <span className="kbd">0</span>–<span className="kbd">5</span></div>
                {d && <MyScores key={cur.company_number} num={cur.company_number} criteria={criteria} values={d.manual.values}
                                focus={focus} compact onChange={() => detail.reload()} />}
              </>}
              <div className="rv-nav"><span><span className="kbd">K</span> previous</span><span>skip <span className="kbd">J</span></span></div>
            </section>
          </aside>
        </div>
      )}
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

type Fin = CompanyDetail["financials"][number];
const n = (v: string | number | null | undefined) => toNum(v as any);
const pct = (a: number | null, b: number | null) => (a !== null && b ? Math.round((100 * (a - b)) / Math.abs(b)) : null);
const Chg = ({ v }: { v: number | null }) => (v === null || !Number.isFinite(v) ? null : <span className={v >= 0 ? "up" : "dn"}>{v >= 0 ? "+" : ""}{v}%</span>);
const da = (f: Fin) => n(f.depreciation_amortisation) ?? (n(f.depreciation) !== null || n(f.amortisation) !== null ? (n(f.depreciation) ?? 0) + (n(f.amortisation) ?? 0) : null);
const yr = (pe: string) => new Date(pe).toLocaleDateString("en-GB", { month: "short", year: "numeric" });

function townOf(addr: string | null): string | null {
  const parts = (addr ?? "").split(",").map((p) => p.trim()).filter(Boolean);
  return parts.length > 1 ? [...parts.slice(0, -1)].reverse().find((p) => !/\d/.test(p)) ?? null : null;
}

/** The latest filed year's key figures. */
function Kpis({ d }: { d: CompanyDetail }) {
  const fin = d.financials.filter((f) => !f.period_inferred);
  const last = (k: keyof Fin) => { let i = fin.length - 1; while (i >= 0 && n(fin[i][k] as any) === null) i--; return i < 0 ? null : { f: fin[i], v: n(fin[i][k] as any)!, prev: fin.slice(0, i).map((f) => n(f[k] as any)).filter((v) => v !== null).pop() ?? null }; };
  const t = last("turnover"), na = last("net_assets"), cash = last("cash"), st = last("employees");
  const tf = t?.f;
  const op = tf ? n(tf.operating_profit) : null;
  const dda = tf ? da(tf) : null;
  const ebitda = op !== null && dda !== null ? op + dda : null;
  const bank = cash ? (n(cash.f.bank_loans) ?? 0) + (n(cash.f.bank_overdrafts) ?? 0) : 0;
  const est = d.estimate && d.estimate.basis !== "filed" ? d.estimate : null;
  const k = (l: string, v: React.ReactNode, sub?: React.ReactNode) => <div className="rv-kpi"><div className="l">{l}</div><div className="v">{v}</div><div className="s">{sub}</div></div>;
  return (
    <div className="rv-kpis">
      {k("Revenue", t ? money(t.v) : "—", t ? <><Chg v={pct(t.v, t.prev)} /> {yr(t.f.period_end)}</> : "not filed")}
      {k("Operating profit", op !== null ? money(op) : "—", op !== null && t?.v ? `${((100 * op) / t.v).toFixed(1)}% margin` : null)}
      {k("EBITDA", ebitda !== null ? money(ebitda) : "—", ebitda !== null && t?.v ? `${((100 * ebitda) / t.v).toFixed(1)}% margin` : "needs filed D&A")}
      {k("Indicative value", range(d.valuation.value_low, d.valuation.value_high), d.valuation.basis ?? null)}
      {k("Net assets", na ? money(na.v) : "—", na ? <Chg v={pct(na.v, na.prev)} /> : null)}
      {k("Cash", cash ? money(cash.v) : "—", cash ? (bank > 0 ? `${money(bank)} bank debt` : "no bank debt") : null)}
      {k("Staff", st ? int(st.v) : "—", st && t && st.f.period_end === t.f.period_end ? `${money(t.v / st.v)} revenue each` : st ? yr(st.f.period_end) : null)}
      {k("Revenue estimate", est ? <span className="fig-est">{range(est.revenue_low, est.revenue_high)}</span> : "—", est ? "estimate, latest year" : "filed figures used")}
    </div>
  );
}

/** Five years: revenue bars, operating profit line, and a small table. */
function FiveYears({ d, num }: { d: CompanyDetail; num: string }) {
  const ys = d.financials.filter((f) => !f.period_inferred && (n(f.turnover) !== null || n(f.operating_profit) !== null || n(f.net_assets) !== null)).slice(-5);
  if (!ys.length) return <><h2>Financials</h2><div className="faint">No filed figures yet.</div></>;
  const rev = ys.map((f) => n(f.turnover)), op = ys.map((f) => n(f.operating_profit));
  const hasRev = rev.some((v) => v !== null);
  const W = 420, H = 190, L = 44, B = 26, T = 22;
  const top = Math.max(1, ...rev.map((v) => v ?? 0), ...op.map((v) => v ?? 0));
  const bot = Math.min(0, ...op.map((v) => v ?? 0));
  const y = (v: number) => T + ((top - v) / (top - bot)) * (H - T - B);
  const slot = (W - L) / ys.length, bw = Math.min(46, slot * 0.6);
  const cx = (i: number) => L + slot * i + slot / 2;
  const pts = op.map((v, i) => (v === null ? null : [cx(i), y(v)] as const)).filter(Boolean) as (readonly [number, number])[];
  const rows: [string, (f: Fin) => React.ReactNode][] = [
    ["Revenue", (f) => (n(f.turnover) !== null ? money(n(f.turnover)) : "—")],
    ["Operating profit", (f) => (n(f.operating_profit) !== null ? money(n(f.operating_profit)) : "—")],
    ["Margin", (f) => (n(f.turnover) && n(f.operating_profit) !== null ? `${((100 * n(f.operating_profit)!) / n(f.turnover)!).toFixed(1)}%` : "—")],
    ["Net assets", (f) => (n(f.net_assets) !== null ? money(n(f.net_assets)) : "—")],
    ["Cash", (f) => (n(f.cash) !== null ? money(n(f.cash)) : "—")],
    ["Staff", (f) => (f.employees !== null ? int(f.employees) : "—")],
  ];
  return (
    <>
      <h2 style={{ display: "flex" }}>Financials<Link className="small" style={{ marginLeft: "auto", fontWeight: 500 }} to={`/c/${num}#financials`}>All figures on the full page →</Link></h2>
      <div className={`rv-fin ${hasRev ? "" : "one"}`}>
        {hasRev ? (
          <div>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Revenue and operating profit">
              <line x1={L} x2={W} y1={y(0)} y2={y(0)} className="zero" />
              {ys.map((f, i) => rev[i] !== null && <g key={f.period_end}>
                <rect x={cx(i) - bw / 2} y={y(rev[i]!)} width={bw} height={Math.max(1, y(0) - y(rev[i]!))} rx={4} className="rv-bar" />
                <text x={cx(i)} y={y(rev[i]!) - 6} textAnchor="middle" className="rv-lab">{money(rev[i])}</text></g>)}
              {pts.length > 1 && <polyline points={pts.map((p) => p.join(",")).join(" ")} className="rv-line" />}
              {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={3.5} className="rv-dot" />)}
              {ys.map((f, i) => <text key={f.period_end} x={cx(i)} y={H - 8} textAnchor="middle" className="ax">{f.period_end.slice(0, 4)}</text>)}
            </svg>
            <div className="faint small"><span className="rv-key bar" /> Revenue <span className="rv-key line" /> Operating profit</div>
          </div>
        ) : null}
        <table className="rv-table">
          <thead><tr><th />{ys.map((f) => <th key={f.period_end}>{f.period_end.slice(0, 4)}</th>)}</tr></thead>
          <tbody>{rows.filter(([, g]) => ys.some((f) => g(f) !== "—")).map(([l, g]) => (
            <tr key={l}><td>{l}</td>{ys.map((f, i) => <td key={f.period_end} className={i === ys.length - 1 ? "last" : ""}>{g(f)}</td>)}</tr>))}</tbody>
        </table>
      </div>
      {!hasRev && <div className="faint small" style={{ marginTop: 6 }}>No revenue filed: small-company accounts often leave it out.</div>}
    </>
  );
}

/** Owners with their share and age; directors summed up in a line. */
function Owners({ d }: { d: CompanyDetail }) {
  const band = (ns: string[]) => { for (const x of ns) { const m = x.match(/ownership-of-shares-(\d+)-to-(\d+)-percent/); if (m) return [Number(m[1]), Number(m[2])]; } return null; };
  const psc = (d.ch?.fetched?.psc ?? d.people.filter((p) => p.role === "psc")).filter((p) => !p.ceased_on);
  const shares = d.ch?.shareholders ?? [];
  const dirs = (d.ch?.officers ?? []).filter((o) => !o.resigned_on && (o.role ?? "").includes("director"));
  const ages = dirs.map((o) => ageFrom(o.birth_year)).filter((a): a is number => a !== null);
  const lastChange = [...(d.ch?.officers ?? []).flatMap((o) => [o.appointed_on, o.resigned_on]), ...psc.map((p) => p.notified_on)].filter(Boolean).sort().pop();
  return (
    <>
      <h2>Owners and directors <span className="faint small" style={{ fontWeight: 500 }}>{d.ownership ? OWNERSHIP[d.ownership.ownership_type] : ""}</span></h2>
      {psc.length === 0 && <div className="faint small">No owners registered.</div>}
      {psc.map((p) => {
        const b = band(p.natures);
        const exact = shares.find((s) => s.pct !== null && s.name.toLowerCase().includes(p.name.split(/[ ,]/).filter(Boolean).pop()!.toLowerCase()));
        const share = exact?.pct ?? (b ? b[0] : null);
        const label = exact?.pct != null ? `${exact.pct}%` : b ? (b[1] === 100 ? `${b[0]}%+` : `${b[0]}–${b[1]}%`) : "control";
        const age = ageFrom(p.birth_year);
        return <div key={p.name + p.notified_on} className="rv-own"><span><span className="rv-sbar" style={{ width: Math.max(4, (share ?? 10) * 0.75) }} />{p.name}{age !== null ? ` · ${age}` : ""}</span><b>{label}</b></div>;
      })}
      <div className="muted small" style={{ marginTop: 6 }}>
        {dirs.length ? `${dirs.length} director${dirs.length === 1 ? "" : "s"}${ages.length ? `, youngest ${Math.min(...ages)}` : ""}` : "Directors not fetched yet"}
        {lastChange ? ` · last change ${date(lastChange)}` : ""}
      </div>
    </>
  );
}

/** No website yet: try the likely ones in one click. */
function FindSite({ num, onFound }: { num: string; onFound: () => void }) {
  const [state, setState] = useState<"idle" | "busy" | "none">("idle");
  useEffect(() => setState("idle"), [num]);
  if (state === "none") return <span className="faint small" style={{ alignSelf: "center" }}>No website found</span>;
  return <button className="btn" disabled={state === "busy"} onClick={async () => {
    setState("busy");
    try { const r = await api.findWebsite(num); if (r.saved) onFound(); else setState("none"); } catch { setState("none"); }
  }}>{state === "busy" ? "Looking…" : "Find website"}</button>;
}
