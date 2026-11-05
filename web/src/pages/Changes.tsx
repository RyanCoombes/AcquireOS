import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Change } from "../api";
import { ErrorLine, Score, StatusMark, useAsync } from "../components/bits";
import { CHANGE_KIND, date, describeChange, isBadStatus } from "../format";

const PERIODS: [string, string][] = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["365", "Year"]];

export default function Changes() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const days = params.get("days") ?? "90";
  const kind = params.get("kind") ?? "";
  const tracked = params.get("tracked") === "1";
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (!v) p.delete(k); else p.set(k, v);
    setParams(p, { replace: true });
  };
  const q: Record<string, string> = { days };
  if (kind) q.kind = kind;
  if (tracked) q.tracked = "true";
  const { data, error } = useAsync(() => api.changes(q), [days, kind, tracked]);

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
            What moved between imports: new accounts, status changes such as dissolution, new names and addresses, and owner changes.
            Changes appear after each monthly Companies House refresh (Refresh data on Home, or the Data page).
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
          <input type="checkbox" checked={tracked} onChange={(e) => set("tracked", e.target.checked ? "1" : null)} />
          Only companies in my pipeline
        </label>
      </div>

      <ErrorLine error={error} />
      {data && data.summary.length > 0 && (
        <div className="summary-line">
          <b>{total.toLocaleString("en-GB")}</b> changes:
          {data.summary.map((s) => (
            <button key={s.kind} className={`linkish ${kind === s.kind ? "on" : ""}`} onClick={() => set("kind", kind === s.kind ? null : s.kind)}>
              {CHANGE_KIND[s.kind] ?? s.kind} {Number(s.n).toLocaleString("en-GB")}
            </button>
          ))}
        </div>
      )}
      {data && data.rows.length === 0 && (
        <div className="empty">
          <b>No changes in this period.</b> Changes are recorded when you import a newer file over companies already in AcquireOS.{" "}
          <Link to="/import">Import a file</Link>.
        </div>
      )}
      {[...groups.entries()].map(([day, rows]) => (
        <div className="stage" key={day}>
          <h2>{date(day)}<span className="count">{rows.length}</span></h2>
          <table className="list">
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => nav(`/c/${r.company_number}`)} className={r.excluded ? "excluded" : ""}>
                  <td style={{ width: 120 }}><Score value={r.score ?? null} /></td>
                  <td style={{ width: "34%" }}><div className="name"><Link className="rowlink" to={`/c/${r.company_number}`} onClick={(e) => e.stopPropagation()}>{r.name}</Link></div><div className="sub">{r.company_number}</div></td>
                  <td style={{ width: 130 }}><b>{CHANGE_KIND[r.kind] ?? r.kind}</b></td>
                  <td className={(r.kind === "status" && isBadStatus(r.new_value)) ? "neg" : ""}>{describeChange(r)}</td>
                  <td style={{ width: 140 }}>{r.status && r.status !== "new" ? <StatusMark s={r.status} /> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}
