import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type AlertRules, type Change } from "../api";
import { ErrorLine, Score, StatusMark, useAsync } from "../components/bits";
import { CHANGE_KIND, date, describeChange, isBadStatus } from "../format";

const PERIODS: [string, string][] = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["365", "Year"]];

export default function Changes() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const days = params.get("days") ?? "90";
  const kind = params.get("kind") ?? "";
  const tracked = params.get("tracked") === "1";
  const alerts = params.get("alerts") === "1";
  const [rulesOpen, setRulesOpen] = useState(false);
  const unreadOnly = params.get("unread") === "1";
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (!v) p.delete(k); else p.set(k, v);
    setParams(p, { replace: true });
  };
  const q: Record<string, string> = { days };
  if (kind) q.kind = kind;
  if (alerts) q.alerts = "true";
  else if (tracked) q.tracked = "true";
  if (unreadOnly) q.unread = "true";
  const [rulesVer, setRulesVer] = useState(0);
  const { data, error } = useAsync(() => api.changes(q), [days, kind, tracked, alerts, unreadOnly, rulesVer]);
  // Opening the page counts as seeing the changes (clears the alert badge).
  const [read, setRead] = useState<Set<number>>(new Set());
  const [allRead, setAllRead] = useState(false);
  useEffect(() => { setRead(new Set()); setAllRead(false); }, [data]);
  const isNew = (r: Change) => !!r.unread && !allRead && !read.has(r.id);
  const unreadCount = Math.max(0, (data?.unread ?? 0) - (allRead ? Infinity : read.size));
  const markRead = (ids: number[]) => {
    setRead((s) => new Set([...s, ...ids]));
    api.changesRead(ids).then(() => window.dispatchEvent(new Event("ao:meta"))).catch(() => {});
  };
  const markAll = () => {
    setAllRead(true);
    api.changesSeen().then(() => window.dispatchEvent(new Event("ao:meta"))).catch(() => {});
  };

  // group by day
  const groups = new Map<string, Change[]>();
  for (const r of data?.rows ?? []) {
    const d = r.detected_at.slice(0, 10);
    groups.set(d, [...(groups.get(d) ?? []), r]);
  }
  const total = data?.summary.reduce((s, x) => s + Number(x.n), 0) ?? 0;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Changes</h1>
          <div className="lede">
            Monthly from the bulk files, and from Companies House checks on your pipeline (weekly) and targets (monthly).
          </div>
        </div>
      </div>
      <div className="band">
        <div className="field">
          <label>Period</label>
          <div className="seg">
            {PERIODS.map(([v, l]) => <button key={v} className={days === v ? "on" : ""} onClick={() => set("days", v)}>{l}</button>)}
          </div>
        </div>
        <div className="field">
          <label htmlFor="ch-kind">Type</label>
          <select id="ch-kind" value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">All changes</option>
            {Object.entries(CHANGE_KIND).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        <label className="check">
          <input type="checkbox" checked={alerts} onChange={(e) => set("alerts", e.target.checked ? "1" : null)} />
          Only my notifications
        </label>
        <button className="linkish small" onClick={() => setRulesOpen((o) => !o)}>{rulesOpen ? "Close rules" : "Notification rules"}</button>
        <label className="check">
          <input type="checkbox" checked={unreadOnly} onChange={(e) => set("unread", e.target.checked ? "1" : null)} />
          Unread only
        </label>
        <button className="btn" style={{ marginLeft: "auto" }} disabled={!unreadCount} onClick={markAll}>
          {unreadCount ? `Mark all as read (${unreadCount.toLocaleString("en-GB")})` : "All read"}
        </button>
      </div>

      {rulesOpen && <AlertRulesPanel onSaved={() => { setRulesVer((v) => v + 1); window.dispatchEvent(new Event("ao:meta")); }} />}
      <ErrorLine error={error} />
      {data && data.summary.length > 0 && (
        <div className="summary-line">
          <b>{total.toLocaleString("en-GB")}</b> {total === 1 ? "change" : "changes"}:
          {data.summary.map((s) => (
            <button key={s.kind} className={`linkish ${kind === s.kind ? "on" : ""}`} onClick={() => set("kind", kind === s.kind ? null : s.kind)}>
              {CHANGE_KIND[s.kind] ?? s.kind} {Number(s.n).toLocaleString("en-GB")}
            </button>
          ))}
        </div>
      )}
      {data && data.rows.length === 0 && (
        <div className="empty">
          <b>No changes in this period.</b>
        </div>
      )}
      {[...groups.entries()].map(([day, rows]) => (
        <div className="stage" key={day}>
          <h2>{date(day)}<span className="count">{rows.length}</span>
            {rows.some(isNew) && <button className="linkish small" style={{ marginLeft: 12 }}
              onClick={() => markRead(rows.filter(isNew).map((r) => r.id))}>Mark day as read</button>}</h2>
          <table className="list">
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => { if (isNew(r)) markRead([r.id]); nav(`/c/${r.company_number}`); }}
                    className={[r.excluded ? "excluded" : "", isNew(r) ? "unread" : ""].join(" ")}>
                  <td style={{ width: 120 }}><Score value={r.score ?? null} /></td>
                  <td style={{ width: "34%" }}><div className="name"><Link className="rowlink" to={`/c/${r.company_number}`} onClick={(e) => e.stopPropagation()}>{r.name}</Link></div><div className="sub">{r.company_number}</div></td>
                  <td style={{ width: 130 }}><b>{CHANGE_KIND[r.kind] ?? r.kind}</b>{isNew(r) && <span className="tag new">New</span>}</td>
                  <td className={(r.kind === "status" && isBadStatus(r.new_value)) ? "neg" : ""}>{describeChange(r)}</td>
                  <td style={{ width: 140 }}>{r.status && r.status !== "new" ? <StatusMark s={r.status} /> : ""}</td>
                  <td style={{ width: 44 }}>{isNew(r) && (
                    <button className="readbtn" title="Mark as read" aria-label="Mark as read"
                            onClick={(e) => { e.stopPropagation(); markRead([r.id]); }}>✓</button>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}


const WHO: [AlertRules["who"], string, string][] = [
  ["watch", "Only companies and people I watch", "The quietest: just your watchlist"],
  ["tracked", "My pipeline and watchlist", "Companies you've moved past New, plus your watchlist"],
  ["buy_box", "Everything in my buy boxes", "Every target, plus your pipeline and watchlist"],
];

function AlertRulesPanel({ onSaved }: { onSaved: () => void }) {
  const r = useAsync(() => api.alertRules(), []);
  const [rules, setRules] = useState<AlertRules | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (r.data) setRules({ who: r.data.who, routine: r.data.routine, kinds: r.data.kinds }); }, [r.data]);
  if (!rules || !r.data) return <section><div className="faint">Loading…</div></section>;
  const toggle = (k: string) => setRules({ ...rules, kinds: rules.kinds.includes(k) ? rules.kinds.filter((x) => x !== k) : [...rules.kinds, k] });
  return (
    <section className="alert-rules">
      <div className="sechead"><h2>Notification rules</h2><span className="faint small">What counts towards the badge and "Only my notifications"</span></div>
      <div className="ar-grid">
        <div>
          <div className="small"><b>Whose changes</b></div>
          {WHO.map(([v, l, d]) => (
            <label key={v} className="check ar-opt">
              <input type="radio" name="who" checked={rules.who === v} onChange={() => setRules({ ...rules, who: v })} />
              <span>{l}<div className="faint small">{d}</div></span>
            </label>
          ))}
          <label className="check ar-opt" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={!rules.routine} onChange={(e) => setRules({ ...rules, routine: !e.target.checked })} />
            <span>Skip filings that change nothing<div className="faint small">Confirmation statements with no updates (or none to shareholders or industry codes), and someone's address or details edited</div></span>
          </label>
        </div>
        <div>
          <div className="small"><b>Which kinds</b></div>
          <div className="ar-kinds">
            {r.data.all_kinds.map((k) => (
              <label key={k} className="check"><input type="checkbox" checked={rules.kinds.includes(k)} onChange={() => toggle(k)} />
                {CHANGE_KIND[k] ?? (k === "watch" ? "Watched people and owners" : k === "location" ? "Office locations" : k)}</label>
            ))}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
        <button className="btn primary" onClick={async () => {
          try { await api.saveAlertRules(rules); setMsg("Saved."); onSaved(); } catch (e: any) { setMsg(e.message); }
        }}>Save rules</button>
        {msg && <span className="faint small">{msg}</span>}
      </div>
    </section>
  );
}
