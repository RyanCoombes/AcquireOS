// The new look's side panel on the deals board: the selected deal's next action, a quick
// note and its latest notes, without leaving the board. Everything else is one click away
// on the full company page.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Stage, type Status } from "../api";
import { ageFrom, date, int, OWNERSHIP, range, relDays, WORK_MODEL } from "../format";
import { Logo, NationBadge, StatusMark, useAsync } from "./bits";

export default function DealPeek({ num, statuses, onClose, onChanged }: {
  num: string; statuses: Stage[]; onClose: () => void; onChanged: (msg?: string) => void }) {
  const { data, error, reload } = useAsync(() => api.company(num), [num]);
  const [note, setNote] = useState("");
  const [next, setNext] = useState<{ what: string; on: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (error) return <aside className="peek"><div className="callout red">{error}</div><button className="btn" onClick={onClose}>Close</button></aside>;
  if (!data || data.company.company_number !== num) return <aside className="peek"><div className="faint">Loading…</div></aside>;
  const c = data.company, s = data.state, own = data.ownership;
  const latest = [...data.financials].reverse().find((f) => !f.period_inferred && f.employees != null);
  const age = ageFrom(own?.oldest_birth_year);
  const idx = statuses.findIndex((x) => x.value === s.status);
  const nextStage = statuses[idx + 1] && !["passed", "rejected", "future"].includes(statuses[idx + 1].value) ? statuses[idx + 1] : null;
  const today = new Date().toISOString().slice(0, 10);
  const late = s.next_action_on && s.next_action_on <= today;
  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); reload(); onChanged(done); } catch (e: any) { setMsg(`Not saved: ${e.message}`); }
    setBusy(false);
  };
  const tasks = data.deal?.tasks?.[s.status] ?? [];
  return (
    <aside className="peek" aria-label={`${c.name}: summary`}>
      <div className="pk-head">
        <Logo num={num} name={c.name} website={data.enrichment?.website} v={data.logo_v} size={40} />
        <div className="pk-title">
          <Link to={`/c/${num}`}>{c.name}</Link>
          <div className="faint small"><NationBadge n={data.enrichment?.trading_region || c.region} label />
            {data.enrichment?.work_model && data.enrichment.work_model !== "unknown" ? ` · ${WORK_MODEL[data.enrichment.work_model]}` : ""}</div>
        </div>
        <button className="pk-x" onClick={onClose} aria-label="Close panel">×</button>
      </div>
      <div className="pk-figs">
        <div><span>Fit</span><b className="hl">{data.score && !data.score.excluded ? Math.round(Number(data.score.score)) : "—"}</b></div>
        <div><span>Staff</span><b>{latest?.employees != null ? int(latest.employees) : "—"}</b></div>
        <div><span>Owner</span><b>{age ?? "—"}</b></div>
      </div>
      <div className="small pk-line">
        <StatusMark s={s.status as Status} />
        {data.deal?.stage_entered_at ? <span className="faint"> · since {date(data.deal.stage_entered_at)}</span> : null}
        {tasks.length ? <span className="faint"> · checklist {tasks.filter((t) => t.done).length}/{tasks.length}</span> : null}
        {own && own.ownership_type !== "unknown" ? <span className="faint"> · {OWNERSHIP[own.ownership_type]}</span> : null}
      </div>
      {data.valuation?.value_low ? <div className="small faint pk-line">Indicative value {range(data.valuation.value_low, data.valuation.value_high)}</div> : null}

      <div className="pk-label">Next</div>
      {s.next_action ? (
        <div className={`pk-next ${late ? "late" : ""}`}>
          <input type="checkbox" disabled={busy} aria-label={`Mark done: ${s.next_action}`}
                 onChange={() => run(() => api.nextActionDone(num), "Marked done")} />
          <span>{s.next_action}</span>
          {s.next_action_on && <em>{relDays(s.next_action_on)}</em>}
        </div>
      ) : next === null ? <button className="btn quiet" onClick={() => setNext({ what: "", on: "" })}>+ Set a next action</button> : null}
      {s.next_action && next === null && <button className="linkish small" onClick={() => setNext({ what: s.next_action ?? "", on: s.next_action_on ?? "" })}>Change</button>}
      {next !== null && (
        <form className="pk-form" onSubmit={(e) => { e.preventDefault(); const n = next;
          run(() => api.setState(num, { next_action: n.what.trim() || null, next_action_on: n.on || null }), "Next action saved").then(() => setNext(null)); }}>
          <input value={next.what} placeholder="What's next?" aria-label="Next action" onChange={(e) => setNext({ ...next, what: e.target.value })} autoFocus />
          <input type="date" value={next.on} aria-label="Due on" onChange={(e) => setNext({ ...next, on: e.target.value })} />
          <button className="btn primary" disabled={busy}>Save</button>
          <button type="button" className="btn quiet" onClick={() => setNext(null)}>Cancel</button>
        </form>
      )}

      <label className="pk-label" htmlFor="pk-note">Add a note</label>
      <textarea id="pk-note" rows={3} value={note} placeholder="What happened? Saved to this deal." onChange={(e) => setNote(e.target.value)} />
      <button className="btn" disabled={busy || !note.trim()} onClick={() => run(() => api.addNote(num, note.trim()), "Note saved").then(() => setNote(""))}>Save note</button>
      {msg && <div className="callout red small" role="alert">{msg}</div>}

      <div className="pk-label">Latest</div>
      {data.notes.slice(0, 3).map((n) => (
        <div className="pk-note" key={n.id}><span>{date(n.created_at)}</span>{n.body}</div>
      ))}
      {!data.notes.length && <div className="faint small">No notes yet.</div>}

      <div className="pk-actions">
        {nextStage && <button className="btn primary" disabled={busy}
                              onClick={() => run(() => api.setState(num, { status: nextStage.value, stage_note: "Moved from the deals board" }), `Moved to ${nextStage.label}`)}>
          Move to {nextStage.label}</button>}
        <Link className="btn" to={`/c/${num}`}>Open full page</Link>
      </div>
    </aside>
  );
}
