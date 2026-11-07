/* Owners: search people and companies named as owners (PSCs) and see every
   company each one controls, directly or through holding companies. */
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type Status } from "../api";
import { ErrorLine, RevenueTag, Score, StatusMark, useAsync, WatchButton } from "../components/bits";
import { ageFrom, cap, date, int, isBadStatus, MONTHS, OWNERSHIP, range } from "../format";

export default function Owners() {
  const { pid } = useParams();
  if (pid) return <OwnerPage pid={Number(pid)} />;
  return <OwnerSearch />;
}

function OwnerSearch() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  useEffect(() => { setText(q); }, [q]);
  useEffect(() => {
    if (text.trim() === q) return;
    const t = setTimeout(() => setParams(text.trim() ? { q: text.trim() } : {}, { replace: true }), 350);
    return () => clearTimeout(t);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
  const res = useAsync(() => (q.length >= 3 ? api.owners(q) : Promise.resolve(null)), [q]);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Owners</h1>
          <div className="lede">
            Search an owner to see everything they control.
          </div>
        </div>
      </div>
      <div className="band">
        <div className="field" style={{ flex: "1 1 360px" }}>
          <label htmlFor="o-q">Owner's name</label>
          <input id="o-q" type="search" value={text} placeholder="e.g. Alex Example, or a holding company" autoFocus
                 onChange={(e) => setText(e.target.value)} />
        </div>
      </div>
      <ErrorLine error={res.error} />
      {q.length < 3 ? <div className="empty">Type at least three letters of a name.</div>
        : !res.data ? <div className="empty">Searching…</div>
        : res.data.rows.length === 0 ? <div className="empty"><b>No owner matches “{q}”.</b> Names are as filed: try a surname only, or a company name without “Limited”.</div>
        : (
          <>
            <div className="resultline"><span><b>{int(res.data.rows.length)}</b> owners{res.data.rows.length >= 50 ? " (first 50: type more to narrow it down)" : ""}</span>
              <span className="faint">Owners who hold the same name and birth month are usually, but not always, the same person.</span></div>
            <table className="list">
              <thead><tr><th>Owner</th><th>Born</th><th className="num">Age</th><th className="num">Companies</th><th className="num hide-sm">Past</th></tr></thead>
              <tbody>
                {res.data.rows.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <div className="name"><Link className="rowlink" to={`/owners/${o.id}`}>{o.name}</Link></div>
                      <div className="sub">{o.kind === "individual" ? "Person" : o.kind === "corporate" ? "Company" : cap(o.kind)}
                        {o.registration_number ? ` · ${o.registration_number}` : ""}{o.country_registered ? ` · ${o.country_registered}` : ""}</div>
                    </td>
                    <td>{o.birth_year ? `${MONTHS[o.birth_month ?? 0]} ${o.birth_year}` : "—"}</td>
                    <td className="num">{ageFrom(o.birth_year) ?? "—"}</td>
                    <td className="num"><b>{int(o.companies)}</b></td>
                    <td className="num hide-sm faint">{o.past ? int(o.past) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
    </>
  );
}

function OwnerPage({ pid }: { pid: number }) {
  const { data, error } = useAsync(() => api.owner(pid), [pid]);
  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const o = data.owner;
  const current = data.companies.filter((c) => !c.ceased_on);
  const past = data.companies.filter((c) => c.ceased_on);
  const age = ageFrom(o.birth_year);
  return (
    <>
      <div className="pagehead">
        <div>
          <div className="crumb"><Link to="/owners">Owners</Link> / {o.kind === "individual" ? "Person" : "Company"}</div>
          <h1>{o.name}</h1>
          <div className="lede">
            {o.birth_year ? <>Born {MONTHS[o.birth_month ?? 0]} {o.birth_year}{age ? ` (about ${age})` : ""} · </> : null}
            {o.registration_number ? <>{o.registration_number}{o.country_registered ? `, ${o.country_registered}` : ""} · </> : null}
            <b className="ink">{int(current.length)}</b> {current.length === 1 ? "company" : "companies"} now
            {past.length ? <>, {int(past.length)} in the past</> : null}
            {data.outside_register ? <>, {int(data.outside_register)} not on the live register</> : null}.
          </div>
        </div>
        <div className="right">
          <WatchButton kind="owner" refId={String(pid)} on={!!(data as any).watching} label={o.name} />
          {o.kind !== "individual" && o.registration_number && <Link className="btn" to={`/c/${o.registration_number}`}>Open as a company</Link>}
        </div>
      </div>

      <CompanyTable title="Controls directly" rows={current} />
      {data.indirect.length > 0 && (
        <section>
          <div className="sechead"><h2>Holds through other companies</h2><span className="faint small">From the traced ownership chains</span></div>
          <table>
            <thead><tr><th>Company</th><th>Through</th><th>Best fit</th><th>My status</th></tr></thead>
            <tbody>
              {data.indirect.map((r) => (
                <tr key={r.company_number}>
                  <td><Link className="rowlink" to={`/c/${r.company_number}`}><b>{r.name}</b></Link>
                    {isBadStatus(r.company_status) && <span className="tag red">{cap(r.company_status)}</span>}
                    <div className="sub">{r.company_number}</div></td>
                  <td className="muted small">{r.via}</td>
                  <td><Score value={r.score} /></td>
                  <td><StatusMark s={r.status as Status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {past.length > 0 && <CompanyTable title="No longer controls" rows={past} dim />}
    </>
  );
}

function CompanyTable({ title, rows, dim }: { title: string; rows: Awaited<ReturnType<typeof api.owner>>["companies"]; dim?: boolean }) {
  return (
    <section>
      <div className="sechead"><h2>{title}</h2><span className="faint small">{int(rows.length)}</span></div>
      {rows.length === 0 ? <div className="faint">None on file.</div> : (
        <table>
          <thead><tr><th>Company</th><th className="num">Staff</th><th className="num hide-sm">Revenue</th><th className="hide-sm">Ownership</th>
            <th>Best fit</th><th>My status</th><th className="hide-sm">Since</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.company_number} className={dim ? "excluded" : ""}>
                <td>
                  <div className="name"><Link className="rowlink" to={`/c/${r.company_number}`}>{r.name}</Link>
                    {isBadStatus(r.company_status) && <span className="tag red">{cap(r.company_status)}</span>}</div>
                  <div className="sub">{r.company_number}{r.postcode ? ` · ${r.postcode}` : ""}{r.region ? ` · ${r.region}` : ""}</div>
                </td>
                <td className="num">{int(r.employees)}</td>
                <td className="num hide-sm">{range(r.revenue_low, r.revenue_high)}{r.revenue_low != null && <div><RevenueTag basis={r.revenue_basis} method={(r as any).revenue_method} /></div>}</td>
                <td className="hide-sm nowrap">{r.ownership_type ? OWNERSHIP[r.ownership_type] ?? r.ownership_type : <span className="faint">Not traced</span>}</td>
                <td><Score value={r.score} />{r.box_name && <div className="boxtag">{r.box_name}</div>}</td>
                <td><StatusMark s={r.status as Status} /></td>
                <td className="hide-sm small muted">{r.notified_on ? date(r.notified_on) : ""}{r.ceased_on ? ` – ${date(r.ceased_on)}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
