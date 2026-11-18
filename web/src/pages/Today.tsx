// The new look's home page: what needs you, then new matches, your deals and what changed.
// Same data as the classic Home page; only shown in the new look (see skin.ts).
import { Link } from "react-router-dom";
import { StatusMark } from "../components/bits";
import { ageFrom, CHANGE_KIND, describeChange, int, range, relDays } from "../format";

const LIVE = (s: string) => !["new", "passed", "rejected", "future"].includes(s);
const words = ["Nothing", "One thing", "Two things", "Three things", "Four things", "Five things", "Six things", "Seven things", "Eight things", "Nine things"];

export default function Today({ data, which, setWhich, tq, todo, boxes, numbers, refresh }: {
  data: any; which: string; setWhich: (v: string) => void; tq: (extra?: Record<string, string>) => string; todo: React.ReactNode;
  boxes: React.ReactNode; numbers: React.ReactNode; refresh: { run: () => void; busy: boolean } }) {
  const h = data.head;
  const today = new Date().toISOString().slice(0, 10);
  const dueNow = (data.due as any[]).filter((d) => d.next_action_on && d.next_action_on <= today).length;
  const fresh = (data.recent as any[]).filter((r) => r.status && LIVE(r.status) && Date.now() - new Date(r.detected_at).getTime() < 3 * 864e5).length;
  const n = dueNow + fresh;
  const stages = (data.funnel as any[]).filter((f) => LIVE(f.status) && f.n > 0);
  const most = Math.max(1, ...stages.map((s) => Number(s.n)));
  const future = (data.funnel as any[]).find((f) => f.status === "future")?.n ?? 0;
  const lastData = Object.values(data.freshness).filter(Boolean).sort().pop() as string | undefined;
  return (
    <div className="today">
      <div className="td-top">
        <div>
          <div className="td-eyebrow">{new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</div>
          <h1>{n === 0 ? "Nothing needs you today" : `${words[n] ?? `${n} things`} need${n === 1 ? "s" : ""} you today`}</h1>
          <p className="td-sub">
            {dueNow ? `${dueNow} follow-up${dueNow === 1 ? " is" : "s are"} due` : "No follow-ups are due"}
            {fresh ? ` and ${fresh} of your deals changed in the last three days.` : "."}
            {data.no_next ? ` ${data.no_next} live deal${data.no_next === 1 ? " has" : "s have"} no next action set.` : ""}
          </p>
        </div>
        <div className="td-right">
          <span className="td-fresh"><i />{data.refresh?.running ? "Refreshing from Companies House…" : lastData ? `Data updated ${relDays(lastData)}` : "No data loaded yet"}</span>
          <label className="td-box">Showing{" "}
            <select className="inline-select" value={which} onChange={(e) => setWhich(e.target.value)}>
              <option value="all">all buy boxes</option>
              {(data.boxes ?? []).map((b: any) => <option key={b.id} value={String(b.id)}>{b.name}</option>)}
            </select></label>
          <button className="btn quiet" onClick={refresh.run} disabled={refresh.busy} title="Download the latest Companies House files and update your companies">Refresh data</button>
        </div>
      </div>

      <div className="td-grid">
        <div className="td-main">
          {todo}
          <section className="td-card">
            <div className="td-head"><h2>New matches</h2><span className="faint small">scored 40 or more, not looked at yet</span>
              <Link className="td-link" to={tq({ in_box: "1", status: "new" })}>See all</Link></div>
            {(data.top as any[]).map((t) => {
              const age = ageFrom(t.oldest_birth_year);
              return (
                <div className="td-row" key={t.company_number}>
                  <span className={`td-score ${Number(t.score) >= 70 ? "hi" : "mid"}`}>{Math.round(Number(t.score))}</span>
                  <div className="td-what">
                    <Link to={`/c/${t.company_number}${which === "all" ? "" : `?bb=${which}`}`}>{t.name}</Link>
                    <div className="faint small">{[t.employees != null ? `${int(t.employees)} staff` : null, age ? `owner aged ${age}` : null, t.region].filter(Boolean).join(" · ")}</div>
                  </div>
                  <span className="td-val">{t.value_low ? range(t.value_low, t.value_high) : ""}</span>
                  <Link className="td-look" to={`/c/${t.company_number}${which === "all" ? "" : `?bb=${which}`}`}>Look</Link>
                </div>
              );
            })}
            {!data.top.length && <div className="td-row faint">Every company in your buy boxes already has a status.</div>}
          </section>
        </div>

        <div className="td-side">
          <section className="td-deals">
            <div className="td-head"><h2>Your deals</h2><span className="td-n">{int(h.pipeline)} live</span></div>
            <div className="td-value">{h.pipeline_value_low ? range(h.pipeline_value_low, h.pipeline_value_high) : "—"}</div>
            <div className="td-note">indicative value across live deals (estimates, not valuations)</div>
            <div className="td-stages">
              {stages.map((s) => (
                <Link key={s.status} to="/pipeline" className="td-stage">
                  <span className="l">{s.label}</span>
                  <span className="bar"><i style={{ width: `${Math.max(6, (100 * Number(s.n)) / most)}%` }} /></span>
                  <span className="c">{int(s.n)}</span>
                </Link>
              ))}
              {!stages.length && <div className="td-note">Nothing in your pipeline yet.</div>}
            </div>
            <div className="td-foot">{int(h.talking)} contacted or in talks{future ? ` · ${int(future)} kept for future consideration` : ""}
              {" · "}<Link to="/pipeline">Open the board</Link></div>
          </section>

          <section className="td-card">
            <div className="td-head"><h2>Changes that matter</h2><Link className="td-link" to="/changes?days=30">All</Link></div>
            {(data.recent as any[]).slice(0, 6).map((r, i) => (
              <div className="td-change" key={i}>
                <div className="when">{relDays(r.detected_at)}{r.status !== "new" ? <> · <StatusMark s={r.status} /></> : null}</div>
                <div className="what">{CHANGE_KIND[r.kind] ?? r.kind}: {describeChange(r)}</div>
                <Link to={`/c/${r.company_number}`} className="td-who">{r.name}</Link>
              </div>
            ))}
            {!data.recent.length && <div className="td-row faint">Nothing changed in the last 30 days.</div>}
          </section>
          {boxes}
        </div>
      </div>
      {numbers}
      <div className="td-more"><Link to={tq({ in_box: "1" })}>{int(h.in_scope)} open targets</Link> · <Link to="/companies">All companies</Link></div>
    </div>
  );
}
