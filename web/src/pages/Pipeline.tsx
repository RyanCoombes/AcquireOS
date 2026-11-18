import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Status } from "../api";
import { BT_LABEL } from "../components/CompanyExtras";
import { ErrorLine, Score, StatusMark, Toast, useAsync, Logo, NationBadge, WorkIcon } from "../components/bits";
import { ageFrom, date, int, money, OWNERSHIP, range, WORK_MODEL } from "../format";

type PFilter = { q: string; box: string; region: string; min_staff: string; max_staff: string; min_rev: string;
  min_age: string; ownership: string; work: string; min_score: string; show: string; sort: string; group: string };
const NO_FILTER: PFilter = { q: "", box: "", region: "", min_staff: "", max_staff: "", min_rev: "", min_age: "",
  ownership: "", work: "", min_score: "", show: "", sort: "", group: "" };
const FKEY = "pipeline-filters";
const loadF = (): PFilter => { try { return { ...NO_FILTER, ...JSON.parse(localStorage.getItem(FKEY) || "{}") }; } catch { return NO_FILTER; } };

// What each card shows, and where: beside the name (small badges), the main row, the lower lines, or hidden.
type Place = "top" | "main" | "lower" | "off";
const CARD_FIELDS: [string, string][] = [
  ["nation", "Nation (flag)"], ["work", "Way of working"], ["score", "Score"], ["value", "Indicative value"],
  ["revenue", "Revenue"], ["staff", "Staff"], ["owner", "Oldest owner's age"], ["ownership", "Ownership"],
  ["rating", "Your rating"], ["trust", "Data trust"], ["checklist", "Checklist progress"], ["days", "Days in stage"], ["next", "Next action"],
];
const CARD_DEFAULT: [string, Place][] = [
  ["nation", "top"], ["work", "top"], ["score", "main"], ["value", "main"], ["revenue", "off"], ["staff", "off"],
  ["owner", "off"], ["ownership", "off"], ["rating", "lower"], ["trust", "off"], ["checklist", "lower"], ["days", "lower"], ["next", "lower"],
];
const CKEY = "pipeline-card";
const loadCard = (): [string, Place][] => {
  try {
    const v = JSON.parse(localStorage.getItem(CKEY) || "null");
    if (!Array.isArray(v)) return CARD_DEFAULT;
    const known = v.filter((x: any) => Array.isArray(x) && CARD_FIELDS.some(([k]) => k === x[0]));
    return [...known, ...CARD_DEFAULT.filter(([k]) => !known.some((x: any) => x[0] === k))];  // fields added later
  } catch { return CARD_DEFAULT; }
};

// Business type: Claude's (or yours) from research; otherwise a guess from the industry code.
const TYPE_LABEL: Record<string, string> = { ...BT_LABEL, msp: "MSP" };  // one list of names; MSP short for the dividers
const SIC_GUESS: [RegExp, string][] = [
  [/^(62011|62012|58210|58290)/, "software"], [/^62030/, "msp"], [/^62020/, "it_consultancy"],
  [/^(63110|63120|63990)/, "data"], [/^(46510|46520|47410|47420)/, "reseller"],
  [/^(33|43210|43220|95110|95120)/, "field_service"], [/^(73110|73120)/, "agency"],
];
function typeOf(r: { business_type?: string | null; sic_codes?: string[] | null }): [string, boolean] {
  if (r.business_type && r.business_type !== "other") return [r.business_type, false];
  for (const code of r.sic_codes ?? []) for (const [re, t] of SIC_GUESS) if (re.test(code)) return [t, true];
  return [r.business_type ?? "", false];
}
const QUIET_DAYS = 30;

const daysSince = (v: string | null) => v ? Math.max(0, Math.floor((Date.now() - new Date(v).getTime()) / 864e5)) : null;

export default function Pipeline() {
  const nav = useNavigate();
  const { data, error, reload } = useAsync(() => api.pipeline(), []);
  const outreach = useAsync(() => api.outreach(), []);
  const [phase, setPhase] = useState<string>("all");
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [overCard, setOverCard] = useState<{ num: string; after: boolean } | null>(null);
  const moving = useRef(false);
  const [toast, setToast] = useState<string | null>(null);
  const [mStage, setMStage] = useState<string | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState<PFilter>(loadF);
  const [fOpen, setFOpen] = useState(false);
  const [card, setCardState] = useState<[string, Place][]>(loadCard);
  const [cfgOpen, setCfgOpen] = useState(false);
  const setCard = (v: [string, Place][]) => { setCardState(v); try { localStorage.setItem(CKEY, JSON.stringify(v)); } catch { /* private window */ } };
  useEffect(() => { try { localStorage.setItem(FKEY, JSON.stringify(f)); } catch { /* private window */ } }, [f]);
  const upd = (k: keyof PFilter) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const all = data.rows;
  const due = all.filter((r) => r.next_action_on && r.next_action_on <= today && !["passed", "rejected"].includes(r.status));
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const q = f.q.trim().toLowerCase();
  const rev = (r: (typeof all)[number]) => Number(r.revenue_high ?? r.revenue_low ?? NaN);
  // Days since anything happened: entering the stage, a note or a logged contact.
  const quietFor = (r: (typeof all)[number]) => Math.min(...[r.stage_entered_at, r.last_note, r.last_contact]
    .map((v) => daysSince(v ?? null)).filter((x): x is number => x !== null), 99999);
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
    if (f.show === "stale" && !(quietFor(r) >= QUIET_DAYS)) return false;
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
    next: (a, b) => (a.next_action_on ?? "9999").localeCompare(b.next_action_on ?? "9999"),
  };
  if (by[f.sort]) rows.sort(by[f.sort]);
  const boxes = [...new Set(all.flatMap((r) => r.boxes ?? []))].sort();
  const regions = [...new Set(all.map((r) => r.region).filter(Boolean) as string[])].sort();
  const owners = [...new Set(all.map((r) => r.ownership_type ?? "unknown"))].sort();
  const nSet = (Object.keys(NO_FILTER) as (keyof PFilter)[]).filter((k) => k !== "sort" && k !== "group" && f[k]).length;
  // "Future consideration" has its own tab and stays off the working board.
  const cols = data.statuses.filter((s) => s.phase !== "closed" && (phase === "all" ? s.phase !== "future" : s.phase === phase));
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
    setDragging(null); setOver(null); setOverCard(null);
    await move(num, to);
  };
  // Priority: the stage's companies in board order (filters ignored), with one moved.
  const ranked = (status: string) => all.filter((r) => r.status === status).map((r) => r.company_number);
  const placeAt = async (num: string, status: Status, target: string | null, after: boolean) => {
    const row = all.find((r) => r.company_number === num);
    if (!row || moving.current) return;   // one move at a time: a second before the first is saved would undo it
    const list = ranked(status).filter((x) => x !== num);
    const i = target ? list.indexOf(target) : -1;
    list.splice(i < 0 ? list.length : i + (after ? 1 : 0), 0, num);
    moving.current = true;
    const stage = data.statuses.find((s) => s.value === status)?.label;
    try {
      if (row.status !== status) {
        await api.setState(num, { status, stage_note: "Moved on the pipeline board" });
        setToast(`${row.name} moved to ${stage}`);
      }
      try { await api.pipelineOrder(status, list); }
      catch (e: any) { setToast(row.status !== status ? `${row.name} moved to ${stage}, but its place in the order wasn't saved: ${e.message}` : `Order not saved: ${e.message}`); }
    } catch (e: any) { setToast(`Not moved: ${e.message}`); }
    reload();
    setTimeout(() => { moving.current = false; }, 400);
  };
  // Up and down are relative to the cards you can see (filters and groups applied).
  const nudge = async (num: string, how: "top" | "up" | "down") => {
    const row = all.find((r) => r.company_number === num);
    if (!row) return;
    if (how === "top") { const first = ranked(row.status)[0]; return first === num ? undefined : placeAt(num, row.status, first, false); }
    const seen = rows.filter((r) => r.status === row.status && (!f.group || groupOf(r)[0] === groupOf(row)[0])).map((r) => r.company_number);
    const j = seen.indexOf(num) + (how === "up" ? -1 : 1);
    if (j < 0 || j >= seen.length) return;
    return placeAt(num, row.status, seen[j], how === "down");
  };
  const byPriority = f.sort === "";
  const groupOf = (r: (typeof all)[number]): [string, string] => {
    if (f.group === "type") { const [t] = typeOf(r); return t ? [t, TYPE_LABEL[t] ?? t] : ["~", "Not classified"]; }
    if (f.group === "nation") return r.nation ? [r.nation, r.nation] : ["~", "Nation not known"];
    if (f.group === "work") return r.work_model && r.work_model !== "unknown" ? [r.work_model, WORK_MODEL[r.work_model] ?? r.work_model] : ["~", "Way of working not known"];
    if (f.group === "box") return r.box_name ? [r.box_name, r.box_name] : ["~", "Not in a buy box"];
    return ["", ""];
  };

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Pipeline</h1>
          <div className="lede">From first look to handover. Drag cards between stages, or up and down to set your priority.</div>
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
            <option value="">Sort: my priority</option>
            <option value="next">Sort: next action</option>
            <option value="score">Sort: score</option>
            <option value="value">Sort: value</option>
            <option value="revenue">Sort: revenue</option>
            <option value="staff">Sort: staff</option>
            <option value="age">Sort: oldest owner</option>
            <option value="stage">Sort: longest in stage</option>
            <option value="name">Sort: name</option>
          </select>
          <select value={f.group} onChange={upd("group")} aria-label="Group cards">
            <option value="">No groups</option>
            <option value="type">Group: business type</option>
            <option value="nation">Group: nation</option>
            <option value="work">Group: way of working</option>
            <option value="box">Group: buy box</option>
          </select>
          <button className={`btn quiet ${cfgOpen ? "on" : ""}`} onClick={() => setCfgOpen(!cfgOpen)} aria-expanded={cfgOpen}>Customise cards</button>
          <span className="band-actions">
            {nSet > 0 && <span className="faint small">{int(rows.length)} of {int(all.length)}</span>}
            {(nSet > 0 || f.sort || f.group) && <button className="btn quiet" onClick={() => setF(NO_FILTER)}>Clear</button>}
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
                <option value="stale">Gone quiet (30+ days)</option>
                <option value="investor">Investor among shareholders</option>
              </select>
            </div>
          )}
        </div>
      )}
      {cfgOpen && (
        <div className="cardcfg">
          <div className="sechead"><b>What each card shows</b><span className="faint small">Remembered in this browser</span></div>
          <table><tbody>
            {card.map(([k, place], i) => (
              <tr key={k}>
                <td>{CARD_FIELDS.find((x) => x[0] === k)?.[1]}</td>
                <td><select value={place} aria-label={`Where to show ${k}`}
                            onChange={(e) => setCard(card.map((x) => x[0] === k ? [k, e.target.value as Place] : x))}>
                  <option value="top">Beside the name</option><option value="main">Main row</option>
                  <option value="lower">Lower lines</option><option value="off">Hidden</option></select></td>
                <td><button className="mv" disabled={i === 0} aria-label="Move up"
                            onClick={() => { const v = [...card]; [v[i - 1], v[i]] = [v[i], v[i - 1]]; setCard(v); }}>↑</button>{" "}
                    <button className="mv" disabled={i === card.length - 1} aria-label="Move down"
                            onClick={() => { const v = [...card]; [v[i + 1], v[i]] = [v[i], v[i + 1]]; setCard(v); }}>↓</button></td>
              </tr>
            ))}
          </tbody></table>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button className="btn quiet" onClick={() => setCard(CARD_DEFAULT)}>Back to the default</button>
            <button className="btn" onClick={() => setCfgOpen(false)}>Done</button>
          </div>
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
            // Grouped: cards of each group together (in the chosen order), unknown last.
            const groups = new Map<string, { label: string; rows: typeof items }>();
            for (const r of items) { const [k, label] = groupOf(r); if (!groups.has(k)) groups.set(k, { label, rows: [] }); groups.get(k)!.rows.push(r); }
            const ordered = f.group ? [...groups.entries()].sort((a, b) => a[0] === "~" ? 1 : b[0] === "~" ? -1 : a[1].label.localeCompare(b[1].label)) : [];
            return (
              <div key={s.value} className={`col ${over === s.value ? "over" : ""} ${mStageOf === s.value ? "" : "m-off"}`}
                   onDragOver={(e) => { e.preventDefault(); setOver(s.value); }} onDragLeave={() => setOver(null)}
                   onDrop={(e) => { e.preventDefault(); drop(s.value); }}>
                <h3><span>{s.label}</span><span className="count">{items.length}</span></h3>
                <div className="desc">{s.description}</div>
                {(f.group ? ordered.flatMap(([k, g]) => [{ sep: k, label: g.label, n: g.rows.length, guessed: f.group === "type" ? g.rows.filter((r) => typeOf(r)[1]).length : 0 }, ...g.rows]) : items).map((r: any) => {
                  if ("sep" in r) return <div key={`sep-${r.sep}`} className="grpsep" title={r.guessed ? `${r.guessed} of these not yet classified by research: guessed from the industry (SIC) code` : undefined}>
                    <span>{r.label} · {r.n}{r.guessed ? <em> · {r.guessed} guessed</em> : null}</span></div>;
                  const d = daysSince(r.stage_entered_at);
                  const quiet = s.phase !== "future" && quietFor(r) >= QUIET_DAYS ? quietFor(r) : null;
                  const dropHere = overCard && overCard.num === r.company_number ? (overCard.after ? "drop-after" : "drop-before") : "";
                  const overdue = r.next_action_on && r.next_action_on <= today;
                  return (
                    <div key={r.company_number} className={`card ${dragging === r.company_number ? "dragging" : ""} ${quiet ? "quiet" : ""} ${dropHere}`} draggable
                         onDragStart={() => setDragging(r.company_number)} onDragEnd={() => { setDragging(null); setOver(null); setOverCard(null); }}
                         onDragOver={byPriority ? (e) => { e.preventDefault(); e.stopPropagation(); setOver(s.value);
                           const b = e.currentTarget.getBoundingClientRect(); const after = e.clientY > b.top + b.height / 2;
                           if (!overCard || overCard.num !== r.company_number || overCard.after !== after) setOverCard({ num: r.company_number, after }); } : undefined}
                         onDrop={byPriority ? (e) => { e.preventDefault(); e.stopPropagation(); const num = dragging; const oc = overCard;
                           setDragging(null); setOver(null); setOverCard(null);
                           const moved = all.find((x) => x.company_number === num);
                           if (!num || !moved || num === r.company_number) return;
                           // Grouped: a card can be ranked within its own group; dropped on another group it just joins the stage.
                           if (f.group && groupOf(moved)[0] !== groupOf(r)[0]) {
                             if (moved.status === s.value) setToast("Cards stay in their own group: drop it on a card in the same group to rank it");
                             else placeAt(num, s.value as Status, null, false);
                           } else placeAt(num, s.value as Status, r.company_number, oc?.after ?? false); } : undefined}
                         onClick={() => nav(`/c/${r.company_number}`)}>
                      {r.website && <a className="card-web" href={r.website} target="_blank" rel="noreferrer" draggable={false}
                                       title={`Website: ${r.website.replace(/^https?:\/\/(www\.)?/, "")}`} aria-label={`${r.name} website`}
                                       onClick={(e) => e.stopPropagation()}>↗</a>}
                      <div className="name has-logo"><Logo num={r.company_number} name={r.name} website={r.website} v={r.logo_v} size={26} /><Link className="rowlink" to={`/c/${r.company_number}`} onClick={(e) => e.stopPropagation()}>{r.name}</Link></div>
                      {(() => {
                        const age = ageFrom(r.oldest_birth_year);
                        const rv = r.revenue_high ?? r.revenue_low;
                        const bits: Record<string, React.ReactNode> = {
                          nation: <NationBadge n={r.nation} />,
                          work: <WorkIcon m={r.work_model} />,
                          score: <Score value={r.score} />,
                          value: r.value_low ? <span className="nowrap">{range(r.value_low, r.value_high)}</span> : null,
                          revenue: rv ? <span className="nowrap" title="Revenue (filed or estimate)">{r.revenue_basis === "filed" ? money(rv) : `~${money(rv)}`} rev</span> : null,
                          staff: r.employees != null ? <span className="nowrap">{int(r.employees)} staff</span> : null,
                          owner: age ? <span className="nowrap">Owner {age}</span> : null,
                          ownership: r.ownership_type && r.ownership_type !== "unknown" ? <span>{OWNERSHIP[r.ownership_type] ?? r.ownership_type}</span> : null,
                          rating: r.rating ? <span>{r.rating}/5</span> : null,
                          trust: r.trust != null ? <span className={`trust mini ${r.trust >= 75 ? "good" : r.trust >= 50 ? "fair" : "thin"}`}
                            title="How far this company's data can be relied on (out of 100)">Data {r.trust}</span> : null,
                          checklist: r.tasks_total > 0 ? <span className="cl-wrap"><span className="progressbar"><i style={{ width: `${(100 * r.tasks_done) / r.tasks_total}%` }} /></span>
                            <span>{r.tasks_done}/{r.tasks_total} checklist</span></span> : null,
                          days: d !== null ? <span>{d}d in stage</span> : null,
                          next: r.next_action ? <div className={`next ${overdue ? "overdue" : ""}`}>→ {r.next_action}{r.next_action_on ? ` · ${date(r.next_action_on)}` : ""}</div> : null,
                        };
                        const at = (pl: Place) => card.filter(([k, p]) => p === pl && bits[k]).map(([k]) => <Fragment key={k}>{bits[k]}</Fragment>);
                        const top = at("top"), main = at("main");
                        const lowerKeys = card.filter(([k, p]) => p === "lower" && bits[k]).map(([k]) => k);
                        const inline = lowerKeys.filter((k) => k !== "next" && k !== "checklist");
                        return <>
                          {top.length > 0 && <div className="cbadges">{top}</div>}
                          {main.length > 0 && <div className="meta">{main}</div>}
                          {lowerKeys.includes("checklist") && <div className="cline cl">{bits.checklist}</div>}
                          {inline.length > 0 && <div className="cline">{inline.map((k) => <Fragment key={k}>{bits[k]}</Fragment>)}</div>}
                          {lowerKeys.includes("next") && bits.next}
                        </>;
                      })()}
                      {quiet !== null && <div className="quietline" title="No note or logged contact since then">Quiet for {quiet} days</div>}
                      {/* Works without dragging: phones, keyboard */}
                      <select className="movesel" value="" aria-label={`Move ${r.name} to another stage or up the priority list`}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => { const v = e.target.value; if (v.startsWith("~")) nudge(r.company_number, v.slice(1) as "top" | "up" | "down"); else move(r.company_number, v as Status); }}>
                        <option value="">Move to…</option>
                        {byPriority && <optgroup label="Priority">
                          <option value="~top">⤒ Top of this stage</option><option value="~up">↑ Up one</option><option value="~down">↓ Down one</option>
                        </optgroup>}
                        <optgroup label="Stage">
                          {data.statuses.filter((x) => x.value !== r.status).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                        </optgroup>
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
