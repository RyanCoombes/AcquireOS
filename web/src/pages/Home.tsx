import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, Score, StatusMark, useAsync } from "../components/bits";
import { Columns, HBars, TrendLine } from "../components/charts";
import { ageFrom, CHANGE_KIND, date, describeChange, int, isBadStatus, money, OWNERSHIP, range, relDays } from "../format";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Home() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const which = params.get("bb") ?? "all";
  // Links into Targets carry the buy box being viewed, as a filter.
  const tq = (extra: Record<string, string> = {}) =>
    "/targets?" + new URLSearchParams({ ...(which === "all" ? {} : { bb: which }), ...extra }).toString();
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
          <button className="btn" onClick={refreshNow} disabled={running || starting}>
            <svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></svg>Refresh data
          </button>
          <Link className="btn primary" to={tq()}>Open targets</Link>
        </div>
      </div>

      {which === "all" && (data.boxes ?? []).length > 0 && (
        <section>
          <div className="sechead"><h2>Your buy boxes</h2><span className="right"><Link to="/buy-box">Manage</Link></span></div>
          <table>
            <thead><tr><th>Buy box</th><th className="num">In scope</th><th className="num">Score 70+</th><th className="num">In your pipeline</th><th className="num">Scored</th><th /></tr></thead>
            <tbody>
              {data.boxes.map((b: any) => (
                <tr key={b.id}>
                  <td><b>{b.name}</b></td>
                  <td className="num">{int(b.in_scope)}</td><td className="num">{int(b.strong)}</td><td className="num">{int(b.pipeline)}</td>
                  <td className="num faint small">{b.scored_at ? relDays(b.scored_at) : "not yet"}</td>
                  <td className="num"><button className="btn quiet" onClick={() => setParams({ bb: String(b.id) }, { replace: true })}>View</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="kpis">
        <Link className="kpi" to={tq({ in_box: "1" })}>
          <span className="k"><i />{which === "all" ? "In any buy box" : "In this buy box"}</span>
          <span className="v">{int(h.in_scope)}</span>
          <span className="s">{int(h.strong)} score 70 or more</span>
        </Link>
        <Link className="kpi" to="/pipeline">
          <span className="k"><i style={{ background: "#2f62d8" }} />In your pipeline</span>
          <span className="v">{int(h.pipeline)}</span>
          <span className="s">{int(h.talking)} contacted or in talks</span>
        </Link>
        <Link className="kpi" to="/changes?days=30">
          <span className="k"><i style={{ background: "#e0a245" }} />Changed in 30 days</span>
          <span className="v">{int(h.changed_30d)}</span>
          <span className="s">{int(h.status_30d)} status changes · {int(h.changed_7d)} this week</span>
        </Link>
        <Link className="kpi" to={tq({ in_box: "1", min_owner_age: "60" })}>
          <span className="k"><i style={{ background: "#8a919d" }} />Median owner age</span>
          <span className="v">{h.median_owner_age ? Math.round(h.median_owner_age) : "—"}</span>
          <span className="s">{int(h.owners_60)} owners aged 60+</span>
        </Link>
        <Link className="kpi" to="/pipeline">
          <span className="k"><i style={{ background: "#141820" }} />Pipeline value</span>
          <span className="v">{h.pipeline_value ? money(h.pipeline_value) : "—"}</span>
          <span className="s">Midpoint of indicative values</span>
        </Link>
      </div>

      <div className="home-grid">
        <section className="span-7">
          <div className="sechead"><h2>Best new targets</h2><span className="faint small">Highest scores you haven't given a status yet</span>
            <span className="right"><Link to={tq({ in_box: "1", status: "new" })}>See all</Link></span></div>
          <table>
            <tbody>
              {data.top.map((t: any) => (
                <tr key={t.company_number} style={{ cursor: "pointer" }} onClick={() => nav(`/c/${t.company_number}${which === "all" ? "" : `?bb=${which}`}`)}>
                  <td style={{ width: 110 }}><Score value={t.score} /></td>
                  <td><div className="name">{t.name}</div><div className="sub">{which === "all" && t.box ? <><b>{t.box}</b> · </> : null}{t.region ?? "Region not set"} · {t.ownership_type ? OWNERSHIP[t.ownership_type] : "owners not traced"}</div></td>
                  <td className="num hide-sm">{int(t.employees)} staff</td>
                  <td className="num hide-sm">{ageFrom(t.oldest_birth_year) ? `Owner ${ageFrom(t.oldest_birth_year)}` : ""}</td>
                  <td className="num">{range(t.value_low, t.value_high)}</td>
                </tr>
              ))}
              {!data.top.length && <tr><td className="faint">Every company in your buy box already has a status.</td></tr>}
            </tbody>
          </table>
        </section>

        <section className="span-5">
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
          ) : <div className="faint">Nothing has changed in the last 30 days. Changes appear when newer Companies House data is loaded.</div>}
        </section>

        <section className="span-8">
          <div className="sechead"><h2>Staff across your buy box</h2>
            <span className="faint small">Median staff per company, by year of accounts</span></div>
          <TrendLine points={data.trend.map((t: any) => ({ x: String(t.year), y: Number(t.median_staff) }))} format={(n) => int(Math.round(n))} />
          {data.trend.length > 0 && (
            <div className="faint small">
              {data.trend.map((t: any) => `${t.year}: ${int(t.companies)} companies`).slice(-4).join(" · ")}
              {" · "}{int(h.with_history)} companies have 3+ years of accounts
            </div>
          )}
        </section>

        <section className="span-4">
          <div className="sechead"><h2>Next actions</h2><span className="right"><Link to="/pipeline">Pipeline</Link></span></div>
          {data.due.length ? (
            <ul className="feed">
              {data.due.map((d: any) => {
                const overdue = d.next_action_on < new Date().toISOString().slice(0, 10);
                return (
                  <li key={d.company_number}>
                    <span className={`dot ${overdue ? "red" : "teal"}`} />
                    <span className="what"><Link to={`/c/${d.company_number}`}><b>{d.name}</b></Link>
                      <div className="small muted">{d.next_action ?? "Follow up"}</div></span>
                    <span className={`when ${overdue ? "overdue" : ""}`}>{date(d.next_action_on)}</span>
                  </li>
                );
              })}
            </ul>
          ) : <div className="faint">No dated actions. Set a next action on any company to see it here.</div>}
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
    </>
  );
}
