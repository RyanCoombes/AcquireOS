/* Review one company at a time, fast. Score your criteria with the number
   keys, then shortlist, watch, assess, pass or reject with one key. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type CompanyDetail, type Status } from "../api";
import { ErrorLine, Flags, Score, StatusMark, Toast, useAsync } from "../components/bits";
import { AreaChart } from "../components/charts";
import MyScores from "../components/MyScores";
import SicPicker from "../components/SicPicker";
import { ageFrom, chUrl, int, money, OWNERSHIP, range, toNum, years } from "../format";

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

  const act = useCallback(async (st: Status) => {
    if (!cur) return;
    await api.setState(cur.company_number, { status: st, stage_note: note ? note : "Set in review" });
    if (note.trim()) await api.addNote(cur.company_number, note.trim());
    setDone((x) => ({ ...x, [cur.company_number]: st }));
    setToast(`${cur.name}: ${meta.data?.statuses.find((s) => s.value === st)?.label ?? st}`);
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
  const series = useMemo(() => (key: "employees" | "net_assets") =>
    (d?.financials ?? []).map((f) => ({ x: f.period_end, y: toNum(f[key] as any), inferred: f.period_inferred })), [d]);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Review</h1>
          <div className="lede">
            One company at a time from{" "}
            <b className="ink">{bbId ? meta.data?.buy_boxes.find((b) => b.id === bbId)?.name : "any of your buy boxes"}</b>, best score first.
            Score your criteria with <span className="kbd">0</span>–<span className="kbd">5</span>, then decide with one key.
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
              <div className="sechead">
                <div>
                  <div className="crumb">{i + 1} of {rows.length}{done[cur.company_number] ? <> · <StatusMark s={done[cur.company_number]} /></> : null}</div>
                  <h1 style={{ fontSize: 24 }}>{cur.name}</h1>
                  {d && <div className="muted small">
                    {d.company.company_number} · {d.company.region ?? "region not set"} · incorporated {years(d.company.incorporation_date)} years ago
                    {" · "}<a href={chUrl(d.company.company_number)} target="_blank" rel="noreferrer">Companies House ↗</a>
                    {d.enrichment?.website && <> · <a href={d.enrichment.website} target="_blank" rel="noreferrer">website ↗</a></>}
                  </div>}
                </div>
                <span className="right"><Link className="btn" to={`/c/${cur.company_number}`}>Open full page <span className="kbd">O</span></Link></span>
              </div>
              {!d ? <div className="faint">Loading…</div> : (
                <>
                  <div className="factline">
                    <div><b><Score value={d.score?.score ?? null} coverage={d.score?.coverage} /></b><span>Score</span></div>
                    <div><b>{int(d.financials.filter((f) => !f.period_inferred).slice(-1)[0]?.employees)}</b><span>Staff</span></div>
                    <div><b>{d.estimate ? range(d.estimate.revenue_low, d.estimate.revenue_high) : "—"}</b><span>Revenue{d.estimate?.basis === "estimated" ? " · estimate" : ""}</span></div>
                    <div><b>{range(d.valuation.value_low, d.valuation.value_high)}</b><span>Indicative value</span></div>
                    <div><b>{ageFrom(d.ownership?.oldest_birth_year) ?? "—"}</b><span>Oldest owner</span></div>
                    <div><b style={{ fontSize: 16 }}>{d.ownership ? OWNERSHIP[d.ownership.ownership_type] : "—"}</b><span>Ownership <Flags flags={d.ownership?.flags} address={d.company.address_flag} /></span></div>
                  </div>
                  {d.score?.excluded && <div className="callout red">Outside {d.buy_box.name}: {d.score.exclusion}</div>}
                  {d.enrichment?.summary && <p style={{ marginTop: 0 }}>{d.enrichment.summary}</p>}
                  <div className="muted small" style={{ marginBottom: 12 }}>
                    SIC: {d.sics.map((x) => `${x.code} ${x.description}`).join("; ") || "none filed"}
                  </div>
                  <div className="multiples" style={{ marginBottom: 12 }}>
                    <AreaChart title="Staff" points={series("employees")} format={(n) => int(n)} height={90} />
                    <AreaChart title="Net assets" points={series("net_assets")} format={(n) => money(n)} height={90} />
                  </div>
                  <table className="reasons">
                    <tbody>
                      {(d.score?.reasons ?? []).filter((r) => !r.manual).map((r) => (
                        <tr key={r.key}>
                          <td style={{ width: 150 }}><span className={`reason-mark ${r.status}`}>{({ good: "✓", partial: "~", miss: "✕", unknown: "?" } as Record<string, string>)[r.status]}</span>{r.label}</td>
                          <td className={r.status === "unknown" ? "faint" : ""}>{r.text}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {d.notes.length > 0 && (
                    <div className="muted small" style={{ marginTop: 10 }}>Latest note: {d.notes[0].body.slice(0, 220)}</div>
                  )}
                </>
              )}
            </section>
          </div>
          <aside>
            <section>
              <h2>Your scores</h2>
              {d && <MyScores key={cur.company_number} num={cur.company_number} criteria={criteria} values={d.manual.values}
                              focus={focus} compact onChange={() => detail.reload()} />}
              <div className="faint small" style={{ marginTop: 6 }}>
                <span className="kbd">↑</span> <span className="kbd">↓</span> choose a criterion, <span className="kbd">0</span>–<span className="kbd">5</span> score it.
              </div>
            </section>
            <section>
              <h2>Decide</h2>
              <textarea placeholder="Quick note (optional), saved with your decision" value={note} onChange={(e) => setNote(e.target.value)} style={{ minHeight: 56, marginBottom: 10 }} />
              <div className="actions">
                {ACTIONS.map((a) => (
                  <button key={a.key} className={`btn ${a.cls ?? ""}`} onClick={() => act(a.status)}>
                    {a.label}<span className="kbd">{a.key.toUpperCase()}</span>
                  </button>
                ))}
                <button className="btn" onClick={() => setI((x) => Math.min(x + 1, rows.length))}>Skip<span className="kbd">→</span></button>
              </div>
              <div className="keys" style={{ marginTop: 12 }}>
                <span className="kbd">←</span><span>Previous company</span>
                <span className="kbd">O</span><span>Open the full company page</span>
              </div>
            </section>
          </aside>
        </div>
      )}
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}
