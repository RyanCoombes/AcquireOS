import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Status } from "../api";
import { ErrorLine, Score, StatusMark, Toast, useAsync } from "../components/bits";
import { date, int, range } from "../format";

const daysSince = (v: string | null) => v ? Math.max(0, Math.floor((Date.now() - new Date(v).getTime()) / 864e5)) : null;

export default function Pipeline() {
  const nav = useNavigate();
  const { data, error, reload } = useAsync(() => api.pipeline(), []);
  const outreach = useAsync(() => api.outreach(), []);
  const [phase, setPhase] = useState<string>("all");
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const today = new Date().toISOString().slice(0, 10);

  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const rows = data.rows;
  const due = rows.filter((r) => r.next_action_on && r.next_action_on <= today && !["passed", "rejected"].includes(r.status));
  const cols = data.statuses.filter((s) => s.phase !== "closed" && (phase === "all" || s.phase === phase));
  const closed = rows.filter((r) => ["passed", "rejected"].includes(r.status));

  const move = async (num: string | null, to: Status) => {
    const row = rows.find((r) => r.company_number === num);
    if (!num || !row || row.status === to) return;
    try {
      await api.setState(num, { status: to, stage_note: "Moved on the pipeline board" });
      setToast(`${row.name} moved to ${data.statuses.find((s) => s.value === to)?.label}`);
    } catch (e: any) { setToast(`Not moved: ${e.message}`); }
    reload();
  };
  const drop = async (to: Status) => {
    const num = dragging;
    setDragging(null); setOver(null);
    await move(num, to);
  };

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Pipeline</h1>
          <div className="lede">From first look to handover. Drag a card or use Move to….</div>
        </div>
      </div>
      {due.length > 0 && (
        <div className="callout"><b>{due.length} action{due.length > 1 ? "s" : ""} due:</b>{" "}
          {due.slice(0, 6).map((r, i) => <span key={r.company_number}>{i ? ", " : ""}<Link to={`/c/${r.company_number}`}>{r.name}</Link></span>)}
          {due.length > 6 ? ` and ${due.length - 6} more` : ""}
        </div>
      )}
      <div className="phasebar">
        <div className="viewtabs">
          {[{ value: "all", label: "All stages" }, ...data.phases.filter((p) => p.value !== "closed")].map((p) => (
            <button key={p.value} className={phase === p.value ? "on" : ""} onClick={() => setPhase(p.value)}>
              {p.label}{p.value !== "all" ? ` ${int(rows.filter((r) => data.statuses.find((s) => s.value === r.status)?.phase === p.value).length)}` : ""}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="empty"><b>Nothing in your pipeline yet.</b> Open a company from <Link to="/companies">Companies</Link> or <Link to="/targets">Targets</Link> and move it to Watching or Assessing.</div>
      ) : (
        <div className="board">
          {cols.map((s) => {
            const items = rows.filter((r) => r.status === s.value);
            return (
              <div key={s.value} className={`col ${over === s.value ? "over" : ""}`}
                   onDragOver={(e) => { e.preventDefault(); setOver(s.value); }} onDragLeave={() => setOver(null)}
                   onDrop={(e) => { e.preventDefault(); drop(s.value); }}>
                <h3><span>{s.label}</span><span className="count">{items.length}</span></h3>
                <div className="desc">{s.description}</div>
                {items.map((r) => {
                  const d = daysSince(r.stage_entered_at);
                  const overdue = r.next_action_on && r.next_action_on <= today;
                  return (
                    <div key={r.company_number} className={`card ${dragging === r.company_number ? "dragging" : ""}`} draggable
                         onDragStart={() => setDragging(r.company_number)} onDragEnd={() => { setDragging(null); setOver(null); }}
                         onClick={() => nav(`/c/${r.company_number}`)}>
                      {r.website && <a className="card-web" href={r.website} target="_blank" rel="noreferrer" draggable={false}
                                       title={`Website: ${r.website.replace(/^https?:\/\/(www\.)?/, "")}`} aria-label={`${r.name} website`}
                                       onClick={(e) => e.stopPropagation()}>↗</a>}
                      <div className="name"><Link className="rowlink" to={`/c/${r.company_number}`} onClick={(e) => e.stopPropagation()}>{r.name}</Link></div>
                      <div className="meta">
                        <Score value={r.score} />
                        <span>{r.value_low ? range(r.value_low, r.value_high) : ""}</span>
                      </div>
                      {r.tasks_total > 0 && (
                        <>
                          <div className="progressbar"><i style={{ width: `${(100 * r.tasks_done) / r.tasks_total}%` }} /></div>
                          <div className="meta"><span>{r.tasks_done}/{r.tasks_total} checklist</span><span>{d !== null ? `${d}d in stage` : ""}</span></div>
                        </>
                      )}
                      {!r.tasks_total && d !== null && <div className="meta"><span>{d} days in stage</span>{r.rating ? <span>{r.rating}/5</span> : null}</div>}
                      {r.next_action && <div className={`next ${overdue ? "overdue" : ""}`}>→ {r.next_action}{r.next_action_on ? ` · ${date(r.next_action_on)}` : ""}</div>}
                      {/* Works without dragging: phones, keyboard */}
                      <select className="movesel" value="" aria-label={`Move ${r.name} to another stage`}
                              onClick={(e) => e.stopPropagation()} onChange={(e) => move(r.company_number, e.target.value as Status)}>
                        <option value="">Move to…</option>
                        {data.statuses.filter((x) => x.value !== r.status).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                      </select>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {closed.length > 0 && (
        <details className="closed-fold" style={{ marginTop: 18 }}>
          <summary><b>Not suitable or not now</b> <span className="faint small">{closed.length}</span></summary>
          <table>
            <tbody>
              {closed.map((r) => (
                <tr key={r.company_number} style={{ cursor: "pointer" }} onClick={() => nav(`/c/${r.company_number}`)}>
                  <td style={{ width: 120 }}><Score value={r.score} /></td>
                  <td><div className="name">{r.name}</div></td>
                  <td><StatusMark s={r.status} /></td>
                  <td className="faint small num">{r.stage_entered_at ? date(r.stage_entered_at) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <section style={{ marginTop: 18 }}>
        <div className="sechead"><h2>Outreach log</h2><span className="faint small">{outreach.data?.length ?? 0}</span></div>
        {outreach.data?.length ? (
          <table>
            <thead><tr><th>Date</th><th>Contact</th><th>Role</th><th>Channel</th><th>Company</th><th>What happened</th></tr></thead>
            <tbody>
              {outreach.data.map((o) => (
                <tr key={o.id}>
                  <td className="nowrap">{date(o.happened_on)}</td><td><b>{o.contact_name}</b></td><td>{o.contact_role}</td><td>{o.channel}</td>
                  <td>{o.company_number ? <Link to={`/c/${o.company_number}`}>{o.company_name}</Link> : "—"}</td>
                  <td className="muted">{o.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="faint">Log contacts with owners, advisers, brokers and investors from a company page.</div>}
      </section>
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}
