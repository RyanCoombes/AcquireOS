/* Where this company is in your acquisition process: stage stepper,
   checklist for the current stage, and a dated history of every move. */
import { useState } from "react";
import { api, type CompanyDetail, type Deal, type Stage, type Status } from "../api";
import { useAsync } from "./bits";
import { date, dateTime } from "../format";

const days = (since: string | null) => since ? Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 864e5)) : null;

export default function DealProgress({ data, num, setState }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>;
}) {
  const meta = useAsync(() => api.meta(), []);
  const [deal, setDeal] = useState<Deal>(data.deal);
  const [view, setView] = useState<Status | null>(null);
  const [custom, setCustom] = useState("");
  const stages: Stage[] = meta.data?.stages ?? [];
  const phases = meta.data?.phases ?? [];
  const status = data.state.status;
  const idx = stages.findIndex((s) => s.value === status);
  const shown = (view ?? status) as Status;
  const shownStage = stages.find((s) => s.value === shown);
  const tasks = deal.tasks[shown] ?? [];
  const done = tasks.filter((t) => t.done).length;
  const entered = (st: Status) => [...deal.history].reverse().find((h) => h.to_status === st)?.created_at ?? null;
  const inStage = days(deal.stage_entered_at);
  const next = stages[idx + 1] && !["passed", "rejected"].includes(stages[idx + 1].value) ? stages[idx + 1] : null;

  const move = async (to: Status) => {
    if (to === status) return;
    const note = window.prompt(`Move to “${stages.find((s) => s.value === to)?.label}”. Add a note (optional):`, "");
    if (note === null) return;
    await setState({ status: to, stage_note: note || null });
    setView(null);
    const fresh = await api.company(num);
    setDeal(fresh.deal);
  };
  const toggle = async (label: string, isDone: boolean) => setDeal(await api.setTask(num, { stage: shown, label, done: isDone }));

  if (!stages.length) return null;
  const active = stages.filter((s) => s.phase !== "closed");

  return (
    <>
      <div className="sechead" style={{ marginBottom: 6 }}>
        <h2 style={{ margin: 0 }}>Deal stage</h2>
        {inStage !== null && status !== "new" && <span className="faint small">{inStage} days in stage</span>}
      </div>
      <ul className="stepper">
        {phases.filter((p) => p.value !== "closed").map((p) => (
          <li key={p.value} style={{ listStyle: "none" }}>
            <div className="phase">{p.label}</div>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {active.filter((s) => s.phase === p.value).map((s) => {
                const i = stages.indexOf(s);
                const cls = s.value === status ? "current" : idx >= 0 && i < idx && !["passed", "rejected"].includes(status) ? "past" : "";
                const when = entered(s.value);
                return (
                  <li key={s.value} className={`step ${cls}`} title={s.description}
                      onClick={() => setView(s.value)} onDoubleClick={() => move(s.value)}>
                    <span className="dot" />{s.label}
                    <span className="when">{when ? date(when).replace(/ \d{4}$/, "") : ""}</span>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
      <div className="closed">
        {next && <button className="btn primary" onClick={() => move(next.value)}>Move to {next.label}</button>}
        <button className={`btn ${status === "passed" ? "primary" : ""}`} onClick={() => move("passed")}>Pass</button>
        <button className={`btn ${status === "rejected" ? "primary" : ""}`} onClick={() => move("rejected")}>Reject</button>
      </div>
      <div className="faint small" style={{ marginTop: 6 }}>Click a stage to see its checklist; double-click to move there.</div>

      {shownStage && shownStage.checklist.length + tasks.filter((t) => t.custom).length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="label">
            {shown === status ? "Checklist" : `Checklist: ${shownStage.label}`} · {done} of {tasks.length}
            {view && view !== status && <button className="btn quiet" style={{ height: 22, marginLeft: 6 }} onClick={() => move(view)}>Move here</button>}
          </div>
          <div className="progressbar"><i style={{ width: `${tasks.length ? (100 * done) / tasks.length : 0}%` }} /></div>
          <ul className="checklist">
            {tasks.map((t) => (
              <li key={t.item_key} className={t.done ? "done" : ""}>
                <input type="checkbox" checked={t.done} onChange={(e) => toggle(t.label, e.target.checked)} aria-label={t.label} />
                <span>{t.label}{t.done_at && <span className="faint small"> · {date(t.done_at)}</span>}</span>
                {t.custom && <button className="x" title="Remove" onClick={async () => setDeal(await api.setTask(num, { stage: shown, label: t.label, delete: true }))}>×</button>}
              </li>
            ))}
          </ul>
          <form style={{ display: "flex", gap: 6, marginTop: 6 }} onSubmit={async (e) => {
            e.preventDefault(); if (!custom.trim()) return;
            setDeal(await api.setTask(num, { stage: shown, label: custom.trim(), done: false })); setCustom("");
          }}>
            <input type="text" style={{ flex: 1 }} placeholder="Add your own item" value={custom} onChange={(e) => setCustom(e.target.value)} />
            <button className="btn" disabled={!custom.trim()}>Add</button>
          </form>
        </div>
      )}

      {deal.history.length > 0 && (
        <details style={{ marginTop: 16 }} open={deal.history.length <= 4}>
          <summary className="label" style={{ cursor: "pointer" }}>History ({deal.history.length})</summary>
          <ul className="timeline">
            {[...deal.history].reverse().map((h, i) => (
              <li key={i}>
                <b>{stages.find((s) => s.value === h.to_status)?.label ?? h.to_status}</b>
                {h.note && <div>{h.note}</div>}
                <div className="meta">{dateTime(h.created_at)}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
