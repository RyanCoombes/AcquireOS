import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, Score, useAsync } from "../components/bits";
import { date } from "../format";

export default function Pipeline() {
  const nav = useNavigate();
  const { data, error } = useAsync(() => api.pipeline(), []);
  const outreach = useAsync(() => api.outreach(), []);
  const today = new Date().toISOString().slice(0, 10);
  const due = (data?.rows ?? []).filter((r) => r.next_action_on && r.next_action_on <= today);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Pipeline</h1>
          <div className="lede">Every company you have given a status. Sorted by next action date, then score.</div>
        </div>
      </div>
      <ErrorLine error={error} />
      {due.length > 0 && (
        <div className="callout"><b>{due.length} action{due.length > 1 ? "s" : ""} due:</b>{" "}
          {due.slice(0, 6).map((r, i) => <span key={r.company_number}>{i ? ", " : ""}<Link to={`/c/${r.company_number}`}>{r.name}</Link></span>)}
          {due.length > 6 ? ` and ${due.length - 6} more` : ""}
        </div>
      )}
      {data && data.rows.length === 0 && (
        <div className="empty"><b>Nothing in your pipeline yet.</b> Open a company from <Link to="/">Targets</Link> and give it a status.</div>
      )}
      {data?.statuses.map((s) => {
        const rows = data.rows.filter((r) => r.status === s.value);
        if (!rows.length) return null;
        return (
          <div className="stage" key={s.value}>
            <h2><span className={`status ${s.value}`}>{s.label}</span><span className="count">{rows.length}</span></h2>
            <table className="list">
              <tbody>
                {rows.map((r) => (
                  <tr key={r.company_number} onClick={() => nav(`/c/${r.company_number}`)}>
                    <td style={{ width: 130 }}><Score value={r.score} /></td>
                    <td><div className="name">{r.name}</div><div className="sub">{r.company_number}{r.region ? ` · ${r.region}` : ""}</div></td>
                    <td style={{ width: 70 }}>{r.rating ? `${r.rating}/5` : <span className="faint">—</span>}</td>
                    <td>{r.next_action ?? <span className="faint">No next action</span>}</td>
                    <td className={`num ${r.next_action_on && r.next_action_on <= today ? "overdue" : ""}`} style={{ width: 120 }}>{r.next_action_on ? date(r.next_action_on) : ""}</td>
                    <td className="num faint hide-sm" style={{ width: 150 }}>{r.last_note ? `Note ${date(r.last_note)}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}

      <div className="stage">
        <h2>Outreach log<span className="count">{outreach.data?.length ?? 0}</span></h2>
        {outreach.data?.length ? (
          <table>
            <thead><tr><th>Date</th><th>Contact</th><th>Role</th><th>Channel</th><th>Company</th><th>What happened</th></tr></thead>
            <tbody>
              {outreach.data.map((o) => (
                <tr key={o.id}>
                  <td>{date(o.happened_on)}</td>
                  <td><b>{o.contact_name}</b></td>
                  <td>{o.contact_role}</td>
                  <td>{o.channel}</td>
                  <td>{o.company_number ? <Link to={`/c/${o.company_number}`}>{o.company_name}</Link> : "—"}</td>
                  <td className="muted">{o.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="faint" style={{ paddingTop: 10 }}>Log contacts with owners, advisers and investors from a company page.</div>}
      </div>
    </>
  );
}
