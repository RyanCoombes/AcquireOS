import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Status } from "../api";
import { ErrorLine, Score, StatusMark, Toast, useAsync, Logo, WorkIcon } from "../components/bits";
import { ageFrom, date, int, OWNERSHIP, range, WORK_MODEL } from "../format";

type PFilter = { q: string; box: string; region: string; min_staff: string; max_staff: string; min_rev: string;
  min_age: string; ownership: string; work: string; min_score: string; show: string; sort: string };
const NO_FILTER: PFilter = { q: "", box: "", region: "", min_staff: "", max_staff: "", min_rev: "", min_age: "",
  ownership: "", work: "", min_score: "", show: "", sort: "" };
const FKEY = "pipeline-filters";
const loadF = (): PFilter => { try { return { ...NO_FILTER, ...JSON.parse(localStorage.getItem(FKEY) || "{}") }; } catch { return NO_FILTER; } };

const daysSince = (v: string | null) => v ? Math.max(0, Math.floor((Date.now() - new Date(v).getTime()) / 864e5)) : null;

export default function Pipeline() {
  const nav = useNavigate();
  const { data, error, reload } = useAsync(() => api.pipeline(), []);
  const outreach = useAsync(() => api.outreach(), []);
  const [phase, setPhase] = useState<string>("all");
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [mStage, setMStage] = useState<string | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState<PFilter>(loadF);
  const [fOpen, setFOpen] = useState(false);
  useEffect(() => { try { localStorage.setItem(FKEY, JSON.stringify(f)); } catch { /* private window */ } }, [f]);
  const upd = (k: keyof PFilter) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const all = data.rows;
  const due = all.filter((r) => r.next_action_on && r.next_action_on <= today && !["passed", "rejected"].includes(r.status));
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const q = f.q.trim().toLowerCase();
  const rev = (r: (typeof all)[number]) => Number(r.revenue_high ?? r.revenue_low ?? NaN);
  const rows = all.filter((r) => {
    if (q && !(`${r.name} ${r.company_number}`.toLowerCase().includes(q))) return false;
    if (f.work === "not_known" ? ["remote", "hybrid", "on_site"].includes(r.work_model ?? "") : f.work && r.work_model !== f.work) return false;
    if (f.box && !(r.boxes ?? []).includes(f.box)) return false;
    if (f.region && (r.region ?? "") !== f.region) return false;
    const lo = num(f.min_staff), hi = num(f.max_staff);
    if (lo !== null && !(r.employees != null && r.employees >= lo)) return false;
    if (hi !== null && !(r.employees != null && r.employees <= hi)) return false;
    const mr = num(f.min_rev);
    if (mr !== null && !(rev(r) >= mr * 1e6)) return false;
    const ma = num(f.min_age), age = ageFrom(r.oldest_birth_year);
    if (ma !== null && !(age != null && age >= ma)) return false;
    if (f.ownership && (r.ownership_type ?? "unknown") !== f.ownership) return false;
    const ms = num(f.min_score);
    if (ms !== null && !(Number(r.score ?? NaN) >= ms)) return false;
    if (f.show === "due" && !(r.next_action_on && r.next_action_on <= today)) return false;
    if (f.show === "no_action" && r.next_action) return false;
    if (f.show === "stale" && !((daysSince(r.stage_entered_at) ?? 0) >= 30)) return false;
    if (f.show === "investor" && !(r.signals ?? []).includes("investor_shareholder")) return false;
    return true;
  });
  const by: Record<string, (a: (typeof all)[number], b: (typeof all)[number]) => number> = {
    score: (a, b) => Number(b.score ?? -1) - Number(a.score ?? -1),
    value: (a, b) => Number(b.value_high ?? -1) - Number(a.value_high ?? -1),
    staff: (a, b) => (b.employees ?? -1) - (a.employees ?? -1),
    revenue: (a, b) => (rev(b) || -1) - (rev(a) || -1),
    age: (a, b) => (a.oldest_birth_year ?? 9999) - (b.oldest_birth_year ?? 9999),
    stage: (a, b) => (daysSince(b.stage_entered_at) ?? -1) - (daysSince(a.stage_entered_at) ?? -1),
    name: (a, b) => a.name.localeCompare(b.name),
  };
  if (by[f.sort]) rows.sort(by[f.sort]);
  const boxes = [...new Set(all.flatMap((r) => r.boxes ?? []))].sort();
  const regions = [...new Set(all.map((r) => r.region).filter(Boolean) as string[])].sort();
  const owners = [...new Set(all.map((r) => r.ownership_type ?? "unknown"))].sort();
  const nSet = (Object.keys(NO_FILTER) as (keyof PFilter)[]).filter((k) => k !== "sort" && f[k]).length;
  const cols = data.statuses.filter((s) => s.phase !== "closed" && (phase === "all" || s.phase === phase));
  const closed = rows.filter((r) => ["passed", "rejected"].includes(r.status));
  const mStageOf = mStage && cols.some((c) => c.value === mStage) ? mStage
    : (cols.find((c) => rows.some((r) => r.status === c.value)) ?? cols[0])?.value;

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
      {all.length > 0 && (
        <div className="filterbar pfilters">
          <input type="search" placeholder="Type a company name…" value={f.q} onChange={upd("q")} aria-label="Find a company in the pipeline" />
          <button className={`btn ${fOpen ? "on" : ""}`} onClick={() => setFOpen(!fOpen)} aria-expanded={fOpen}>
            {fOpen ? "▾ Filters" : `▸ Filters${nSet - (f.q ? 1 : 0) > 0 ? ` (${nSet - (f.q ? 1 : 0)})` : ""}`}</button>
          <select value={f.sort} onChange={upd("sort")} aria-label="Sort cards">
            <option value="">Sort: next action</option>
            <option value="score">Sort: score</option>
            <option value="value">Sort: value</option>
            <option value="revenue">Sort: revenue</option>
            <option value="staff">Sort: staff</option>
            <option value="age">Sort: oldest owner</option>
            <option value="stage">Sort: longest in stage</option>
            <option value="name">Sort: name</option>
          </select>
          <span className="band-actions">
            {nSet > 0 && <span className="faint small">{int(rows.length)} of {int(all.length)}</span>}
            {(nSet > 0 || f.sort) && <button className="btn quiet" onClick={() => setF(NO_FILTER)}>Clear</button>}
          </span>
          {fOpen && (
            <div className="pf-more">
              {boxes.length > 1 && (
                <select value={f.box} onChange={upd("box")} aria-label="Buy box">
                  <option value="">Any buy box</option>{boxes.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              )}
              {regions.length > 1 && (
                <select value={f.region} onChange={upd("region")} aria-label="Region">
                  <option value="">Any region</option>{regions.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
              )}
              <span className="pf-range"><input inputMode="numeric" placeholder="Staff from" value={f.min_staff} onChange={upd("min_staff")} aria-label="Staff at least" />
                <span className="faint">–</span><input inputMode="numeric" placeholder="to" value={f.max_staff} onChange={upd("max_staff")} aria-label="Staff at most" /></span>
              <input inputMode="decimal" placeholder="Revenue £m+" value={f.min_rev} onChange={upd("min_rev")} aria-label="Revenue at least, £ millions" />
              <input inputMode="numeric" placeholder="Owner aged" value={f.min_age} onChange={upd("min_age")} aria-label="Oldest owner aged at least" />
              <select value={f.ownership} onChange={upd("ownership")} aria-label="Ownership">
                <option value="">Any ownership</option>{owners.map((o) => <option key={o} value={o}>{OWNERSHIP[o] ?? o}</option>)}
              </select>
              <select value={f.work} onChange={upd("work")} aria-label="Way of working">
                <option value="">Any way of working</option>
                {Object.entries(WORK_MODEL).filter(([v]) => v !== "unknown").map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                <option value="not_known">Not known yet</option>
              </select>
              <input inputMode="numeric" placeholder="Score from" value={f.min_score} onChange={upd("min_score")} aria-label="Score at least" />
              <select value={f.show} onChange={upd("show")} aria-label="Show">
                <option value="">All cards</option>
                <option value="due">Action due</option>
                <option value="no_action">No next action set</option>
                <option value="stale">30+ days in stage</option>
                <option value="investor">Investor among shareholders</option>
              </select>
            </div>
          )}
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

      {all.length > 0 && rows.length === 0 ? (
        <div className="empty"><b>No cards match these filters.</b> <button className="btn quiet" onClick={() => setF(NO_FILTER)}>Clear filters</button></div>
      ) : rows.length === 0 ? (
        <div className="empty"><b>Nothing in your pipeline yet.</b> Open a company from <Link to="/companies">Companies</Link> or <Link to="/targets">Targets</Link> and move it to Watching or Assessing.</div>
      ) : (
        <>
        {/* Phones: one stage at a time, picked here */}
        <div className="m-only mstages" role="tablist">
          {cols.map((s) => {
            const n = rows.filter((r) => r.status === s.value).length;
            return <button key={s.value} role="tab" aria-selected={mStageOf === s.value} className={mStageOf === s.value ? "on" : ""}
                           onClick={() => setMStage(s.value)}>{s.label} <b>{n}</b></button>;
          })}
        </div>
        <div className="board">
          {cols.map((s) => {
            const items = rows.filter((r) => r.status === s.value);
            return (
              <div key={s.value} className={`col ${over === s.value ? "over" : ""} ${mStageOf === s.value ? "" : "m-off"}`}
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
                      <div className="name has-logo"><Logo num={r.company_number} name={r.name} website={r.website} v={r.logo_v} size={26} /><Link className="rowlink" to={`/c/${r.company_number}`} onClick={(e) => e.stopPropagation()}>{r.name}</Link></div>
                      <div className="meta">
                        <Score value={r.score} />
                        <span className="meta-r"><WorkIcon m={r.work_model} />{r.value_low ? range(r.value_low, r.value_high) : ""}</span>
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
        </>
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
