import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, Logo, Score, StatusMark, useAsync } from "../components/bits";
import { Columns, HBars, TrendLine } from "../components/charts";
import { ageFrom, CHANGE_KIND, describeChange, int, isBadStatus, OWNERSHIP, range, relDays } from "../format";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Home() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const which = params.get("bb") ?? "all";
  // Links into Targets carry the buy box being viewed, as a filter.
  // in_box links go to Targets; the rest to the full company directory.
  const tq = (extra: Record<string, string> = {}) => {
    const { in_box, ...rest } = extra;
    const p = new URLSearchParams({ ...(which === "all" ? {} : { bb: which }), ...rest });
    if (!in_box && which !== "all") p.set("in_box", "1");
    return (in_box ? "/targets?" : "/companies?") + p.toString();
  };
  const { data, error, reload } = useAsync(() => api.dashboardFor(which), [which]);
  const [starting, setStarting] = useState(false);
  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const h = data.head;

  if (!h.companies) {
    return (
      <>
        <div className="greeting"><div><h1>{greeting()}</h1><div className="muted">Let's load your search.</div></div></div>
        <section className="empty">
          <b>No companies yet.</b>
          Import your ranked Companies House file or audit workbook on the <Link to="/import">Data</Link> page,
          or load the monthly Companies House files automatically from there.
        </section>
      </>
    );
  }

  const running = data.refresh?.running;
  const lastData = Object.values(data.freshness).filter(Boolean).sort().pop() as string | undefined;
  const refreshNow = async () => {
    if (!confirm("Download the latest Companies House files and update your companies? This can take a while and needs a few GB of free space.")) return;
    setStarting(true);
    try { await api.startRefresh(); } catch (e: any) { alert(e.message); }
    setStarting(false);
    reload();
  };

  return (
    <>
      <div className="greeting">
        <div>
          <h1>{greeting()}</h1>
          <div className="muted">
            {new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
            {" · "}showing{" "}
            <select className="inline-select" value={which} onChange={(e) => setParams(e.target.value === "all" ? {} : { bb: e.target.value }, { replace: true })}>
              <option value="all">all buy boxes</option>
              {(data.boxes ?? []).map((b: any) => <option key={b.id} value={String(b.id)}>{b.name}</option>)}
            </select>
          </div>
        </div>
        <div className="right">
          {running ? <span className="pill-live">Refreshing from Companies House…</span>
            : <span className="fresh">{lastData ? `Data updated ${relDays(lastData)}` : "No data loaded yet"}</span>}
          <button className="btn m-hide" onClick={refreshNow} disabled={running || starting}>
            <svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></svg>Refresh data
          </button>
          <Link className="btn m-hide" to="/companies">All companies</Link>
          <Link className="btn primary" to={tq({ in_box: "1" })}>Open targets</Link>
        </div>
      </div>

      <div className="kpis slim m-hide">
        <Link className="kpi" to={tq({ in_box: "1" })}>
          <span className="k"><i />{which === "all" ? "In any buy box" : "In this buy box"}</span>
          <span className="v">{int(h.in_scope)}</span>
          <span className="s">{int(h.strong)} score 70 or more</span>
        </Link>
        <Link className="kpi" to="/pipeline">
          <span className="k"><i />In your pipeline</span>
          <span className="v">{int(h.pipeline)}</span>
          <span className="s">{int(h.talking)} contacted or in talks</span>
        </Link>
        <Link className="kpi" to="/changes?days=30">
          <span className="k"><i />Changed in 30 days</span>
          <span className="v">{int(h.changed_30d)}</span>
          <span className="s">{int(h.status_30d)} status changes · {int(h.changed_7d)} this week</span>
        </Link>
        <Link className="kpi" to={tq({ in_box: "1", min_owner_age: "60" })}>
          <span className="k"><i />Median owner age</span>
          <span className="v">{h.median_owner_age ? Math.round(h.median_owner_age) : "—"}</span>
          <span className="s">{int(h.owners_60)} owners aged 60+</span>
        </Link>
        <Link className="kpi" to="/pipeline">
          <span className="k"><i />Pipeline value</span>
          <span className="v">{h.pipeline_value_low ? range(h.pipeline_value_low, h.pipeline_value_high) : "—"}</span>
          <span className="s">Indicative range: screening estimates, not valuations</span>
        </Link>
      </div>

      <div className="home-top">
        <div className="home-main">
          <ToDo due={data.due} noNext={data.no_next ?? 0} onChanged={reload} />
        <section>
          <div className="sechead"><h2>Best new targets</h2><span className="faint small">Scoring 40+, not yet reviewed</span>
            <span className="right"><Link to={tq({ in_box: "1", status: "new" })}>See all</Link></span></div>
          <table>
            <tbody>
              {data.top.map((t: any) => (
                <tr key={t.company_number} style={{ cursor: "pointer" }} onClick={() => nav(`/c/${t.company_number}${which === "all" ? "" : `?bb=${which}`}`)}>
                  <td style={{ width: 110 }}><Score value={t.score} /></td>
                  <td><div className="name"><Link className="rowlink" to={`/c/${t.company_number}${which === "all" ? "" : `?bb=${which}`}`} onClick={(e) => e.stopPropagation()}>{t.name}</Link></div><div className="sub">{which === "all" && t.box ? <><b>{t.box}</b> · </> : null}{t.region ?? "Region not set"} · {t.ownership_type ? OWNERSHIP[t.ownership_type] : "owners not traced"}</div></td>
                  <td className="num hide-sm">{int(t.employees)} staff</td>
                  <td className="num hide-sm">{ageFrom(t.oldest_birth_year) ? `Owner ${ageFrom(t.oldest_birth_year)}` : ""}</td>
                  <td className="num">{range(t.value_low, t.value_high)}</td>
                </tr>
              ))}
              {!data.top.length && <tr><td className="faint">Every company in your buy box already has a status.</td></tr>}
            </tbody>
          </table>
        </section>

        </div>
        <div className="home-side">
        <section>
          <div className="sechead"><h2>What changed</h2><span className="right"><Link to="/changes?days=30">All changes</Link></span></div>
          {data.recent.length ? (
            <ul className="feed">
              {data.recent.map((r: any, i: number) => (
                <li key={i}>
                  <span className={`dot ${r.kind === "status" && isBadStatus(r.new_value) ? "red" : r.kind === "accounts" ? "teal" : r.kind === "owner" ? "amber" : ""}`} />
                  <span className="what">
                    <Link to={`/c/${r.company_number}`}><b>{r.name}</b></Link>
                    <div className="small muted">{CHANGE_KIND[r.kind] ?? r.kind}: {describeChange(r)}</div>
                  </span>
                  <span className="when">{r.status !== "new" ? <StatusMark s={r.status} /> : relDays(r.detected_at)}</span>
                </li>
              ))}
            </ul>
          ) : <div className="faint">Nothing changed in the last 30 days.</div>}
        </section>

        {which === "all" && (data.boxes ?? []).length > 0 && (
          <section>
            <div className="sechead"><h2>Your buy boxes</h2><span className="right"><Link to="/buy-box">Manage</Link></span></div>
            <ul className="feed">
              {data.boxes.map((b: any) => (
                <li key={b.id}>
                  <span className="what"><button className="linkish" onClick={() => setParams({ bb: String(b.id) }, { replace: true })}><b>{b.name}</b></button>
                    <div className="small muted">{int(b.in_scope)} in scope · {int(b.strong)} score 70+ · {int(b.pipeline)} in your pipeline</div></span>
                  <span className="when">{b.scored_at ? `scored ${relDays(b.scored_at)}` : "not scored yet"}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        </div>
      </div>

      <details className="home-more">
        <summary>Your search in numbers <span className="faint small">staff over time, score spread, funnel, ownership</span></summary>
        <div className="home-grid">
        <section className="span-8">
          <div className="sechead"><h2>Staff across your buy box</h2>
            <span className="faint small">Median staff by year</span></div>
          <TrendLine points={data.trend.map((t: any) => ({ x: String(t.year), y: Number(t.median_staff) }))} format={(n) => int(Math.round(n))} />
          {data.trend.length > 0 && (
            <div className="faint small">
              {data.trend.map((t: any) => `${t.year}: ${int(t.companies)} companies`).slice(-4).join(" · ")}
              {" · "}{int(h.with_history)} companies have 3+ years of accounts
            </div>
          )}
        </section>

        <section className="span-4">
          <div className="sechead"><h2>Score spread</h2><span className="faint small">Companies in your buy box</span></div>
          <Columns rows={data.score_hist.map((b: any, i: number) => ({ label: `${i * 10}`, n: Number(b.n) }))} highlight={(i) => i >= 7} />
        </section>

        <section className="span-4">
          <div className="sechead"><h2>Search funnel</h2></div>
          <HBars rows={data.funnel.map((f: any) => ({ label: f.label, n: f.n, key: f.status }))}
                 accent={(k) => ["offer", "heads", "diligence", "spa", "completion"].includes(k)} onPick={(k) => nav(tq({ status: k }))} />
        </section>

        <section className="span-4">
          <div className="sechead"><h2>Who owns them</h2></div>
          <HBars rows={data.ownership.map((o: any) => ({ label: OWNERSHIP[o.type] ?? o.type, n: o.n, key: o.type }))}
                 accent={(k) => k === "owner_held"} onPick={(k) => nav(tq({ in_box: "1", ownership: k }))} />
        </section>
        </div>
      </details>
    </>
  );
}


/** Follow-ups on your pipeline: each company's next action, as a to-do list.
 *  Six at a time so it never takes over the page; the rest one click away. */
function ToDo({ due, noNext, onChanged }: { due: any[]; noNext: number; onChanged: () => void }) {
  const [all, setAll] = useState(false);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [undo, setUndo] = useState<{ num: string; name: string; was: any } | null>(null);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = (d: string | null) => d ? Math.round((new Date(d + "T00:00:00").getTime() - today.getTime()) / 864e5) : null;
  const when = (n: number | null): [string, string] =>
    n === null ? ["No date", "g"] : n < -1 ? [`${-n} days overdue`, "r"] : n === -1 ? ["Yesterday", "r"] : n === 0 ? ["Today", "a"]
      : n === 1 ? ["Tomorrow", "b"] : n <= 7 ? [`in ${n} days`, "b"] : n <= 60 ? [`in ${Math.round(n / 7)} weeks`, "g"] : [`in ${Math.round(n / 30)} months`, "g"];
  const group = (n: number | null) => n === null ? "No date" : n < 0 ? "Overdue" : n === 0 ? "Today" : n <= 7 ? "This week" : "Later";
  const rows = due.filter((d) => !gone.has(d.company_number)).map((d) => ({ ...d, n: days(d.next_action_on) }));
  const counts: Record<string, number> = {};
  rows.forEach((r) => { counts[group(r.n)] = (counts[group(r.n)] ?? 0) + 1; });
  const shown = all ? rows : rows.slice(0, 6);
  const done = async (r: any) => {
    setGone((g) => new Set([...g, r.company_number]));
    try { const res = await api.nextActionDone(r.company_number); setUndo({ num: r.company_number, name: r.name, was: res.was }); }
    catch { setGone((g) => { const x = new Set(g); x.delete(r.company_number); return x; }); }
  };
  const snooze = async (r: any, by: number) => {
    const base = r.n !== null && r.n > 0 ? new Date(r.next_action_on + "T00:00:00") : new Date(today);
    base.setDate(base.getDate() + by);
    const iso = `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, "0")}-${String(base.getDate()).padStart(2, "0")}`;
    await api.setState(r.company_number, { next_action_on: iso } as any);
    onChanged();
  };
  let last = "";
  return (
    <section className="todo-box">
      <div className="sechead"><h2>To do</h2><span className="right"><Link to="/pipeline">Pipeline</Link></span></div>
      {rows.length > 0 && (
        <div className="todo-counts">
          {counts["Overdue"] ? <span className="cnt r">{counts["Overdue"]} overdue</span> : null}
          {counts["Today"] ? <span className="cnt a">{counts["Today"]} today</span> : null}
          {counts["This week"] ? <span className="cnt b">{counts["This week"]} this week</span> : null}
          {counts["Later"] ? <span className="cnt g">{counts["Later"]} later</span> : null}
          {counts["No date"] ? <span className="cnt g">{counts["No date"]} no date</span> : null}
        </div>
      )}
      <div className={`todo-list ${all ? "all" : ""}`}>
        {shown.map((r) => {
          const g = group(r.n); const [label, cls] = when(r.n);
          const head = g !== last ? <div className={`todo-grp ${g === "Overdue" ? "r" : ""}`}>{g}</div> : null;
          last = g;
          return (
            <div key={r.company_number}>
              {head}
              <div className="todo-row">
                <input type="checkbox" title="Done" aria-label={`Mark done: ${r.next_action ?? "follow up"} (${r.name})`} onChange={() => done(r)} />
                <Logo num={r.company_number} name={r.name} website={r.website} v={r.logo_v} size={26} />
                <div className="todo-what">
                  <div className="t">{r.next_action ?? "Follow up"}</div>
                  <Link to={`/c/${r.company_number}`} className="c">{r.name}</Link>
                </div>
                <div className="todo-snz">
                  <button className="btn quiet" title="Move to tomorrow (or a day later)" onClick={() => snooze(r, 1)}>+1 day</button>
                  <button className="btn quiet" title="Move a week on" onClick={() => snooze(r, 7)}>+1 week</button>
                </div>
                <span className={`due-chip ${cls}`}>{label}</span>
              </div>
            </div>
          );
        })}
        {!rows.length && <div className="faint">Nothing to follow up. Next actions you set on pipeline companies show here.</div>}
      </div>
      {rows.length > 6 && (
        <button className="linkish small" style={{ marginTop: 6 }} onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${rows.length}`}</button>
      )}
      {noNext > 0 && (
        <div className="faint small" style={{ marginTop: 8 }}>
          <Link to="/pipeline">{noNext} pipeline {noNext === 1 ? "company has" : "companies have"} no next step</Link> set.
        </div>
      )}
      {undo && (
        <div className="todo-undo">
          <span>Done: {undo.was?.next_action ?? "Follow up"} ({undo.name})</span>
          <button className="linkish" onClick={async () => {
            const u = undo; setUndo(null);
            await api.nextActionUndo(u.num, u.was);
            setGone((g) => { const x = new Set(g); x.delete(u.num); return x; });
            onChanged();
          }}>Undo</button>
          <button className="linkish faint" aria-label="Close" onClick={() => setUndo(null)}>×</button>
        </div>
      )}
    </section>
  );
}
