/* Watching: companies, owners and directors you follow, with a way back to each. */
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, StatusMark, useAsync } from "../components/bits";
import { cap, date, isBadStatus, relDays } from "../format";

export default function Watching() {
  const { data, error, reload } = useAsync(() => api.watchList(), []);
  const rows = data?.rows ?? [];
  const companies = rows.filter((r) => r.kind === "company");
  const people = rows.filter((r) => r.kind !== "company");
  const stop = async (kind: string, ref: string) => { await api.unwatch(kind, ref); reload(); };

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Watching</h1>
          <div className="lede">Companies, owners and directors you follow. Their changes show in <Link to="/changes?tracked=1">Changes</Link> and the alert count.</div>
        </div>
      </div>
      <ErrorLine error={error} />
      {data && rows.length === 0 && (
        <div className="empty"><b>Nothing watched yet.</b> Use <b>☆ Watch</b> on a company, an owner's page, or a director in Owners &amp; directors.</div>
      )}

      {companies.length > 0 && (
        <section>
          <div className="sechead"><h2>Companies</h2><span className="faint small">{companies.length}</span></div>
          <table className="list">
            <thead><tr><th>Company</th><th>Last change</th><th className="num">Changes since watching</th><th>My status</th><th /></tr></thead>
            <tbody>
              {companies.map((r) => (
                <tr key={r.id}>
                  <td><div className="name"><Link className="rowlink" to={`/c/${r.ref}`}>{r.name ?? r.label}</Link>
                    {isBadStatus(r.status) && <span className="tag red">{cap(r.status)}</span>}</div>
                    <div className="sub">{r.ref} · watching since {date(r.since)}</div></td>
                  <td className="small">{r.last_change ? relDays(r.last_change) : <span className="faint">none yet</span>}</td>
                  <td className="num">{r.changes_since ? <b>{r.changes_since}</b> : <span className="faint">0</span>}</td>
                  <td>{r.my_status && r.my_status !== "new" ? <StatusMark s={r.my_status as any} /> : ""}</td>
                  <td className="num"><button className="linkish small" onClick={() => stop("company", r.ref)}>Stop watching</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {people.length > 0 && (
        <section>
          <div className="sechead"><h2>Owners and directors</h2><span className="faint small">{people.length}</span></div>
          <div className="whos">
            {people.map((r) => (
              <div key={r.id} className="watchperson">
                <div>
                  <div className="name">
                    {r.kind === "owner" ? <Link className="rowlink" to={`/owners/${r.ref}`}>{r.label}</Link> : <b>{r.label}</b>}
                    <span className={`role ${r.kind === "owner" ? "owner" : "director"}`}>{r.kind === "owner" ? "Owner" : "Director"}</span>
                    {r.changes_since ? <span className="sig red">{r.changes_since} new since watching</span> : null}
                  </div>
                  <div className="wother">
                    {(r.companies ?? []).length === 0 && <span className="faint small">No current companies on the register{r.kind === "director" ? " (fetched from Companies House weekly)" : ""}</span>}
                    {(r.companies ?? []).map((c) => (
                      <Link key={c.company_number} to={`/c/${c.company_number}`} className={isBadStatus(c.status) ? "faint" : ""}>{c.name}</Link>
                    ))}
                  </div>
                </div>
                <button className="linkish small" onClick={() => stop(r.kind, r.ref)}>Stop watching</button>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
