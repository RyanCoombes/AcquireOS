import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type CompanyDetail, type Status } from "../api";
import { ErrorLine, Flags, Score, STATUS_LABEL, Toast, useAsync } from "../components/bits";
import { AreaChart as SmallLine } from "../components/charts";
import Valuation from "../components/Valuation";
import { ageFrom, CHANGE_KIND, chUrl, date, dateTime, describeChange, int, isBadStatus, LINK_KIND, money, MONTHS, OWNERSHIP, range, relDays, toNum, years } from "../format";

const STATUSES: Status[] = ["new", "watching", "researching", "approach", "contacted", "in_talks", "passed", "rejected"];

export default function Company() {
  const { num = "" } = useParams();
  const nav = useNavigate();
  const { data, error, setData, reload } = useAsync(() => api.company(num), [num]);
  const [toast, setToast] = useState<string | null>(null);

  const setState = async (patch: Record<string, unknown>) => {
    if (!data) return;
    const state = await api.setState(num, patch);
    setData({ ...data, state: state as CompanyDetail["state"] });
    setToast("Saved");
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.key === "Escape") nav(-1);
      if (/^[1-5]$/.test(e.key) && data) setState({ rating: Number(e.key) });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const { company: c, financials: fin, estimate: est, ownership: own, score } = data;
  const latest = [...fin].reverse().find((f) => !f.period_inferred);
  const age = ageFrom(own?.oldest_birth_year);
  const series = (k: keyof (typeof fin)[number]) =>
    fin.map((f) => ({ x: f.period_end, y: toNum(f[k] as string | number | null), inferred: f.period_inferred }));

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="crumb">
            <Link to="/targets">Targets</Link> / {c.company_number}
          </div>
          <h1>{c.name}</h1>
          <div className="lede">
            {c.status ? (isBadStatus(c.status) ? <span className="tag red" style={{ marginLeft: 0 }}>{cap(c.status)}{c.dissolution_date ? ` ${date(c.dissolution_date)}` : ""}</span> : cap(c.status)) : "Status unknown"}
            {c.incorporation_date ? ` · incorporated ${date(c.incorporation_date)}` : ""}
            {c.region ? ` · ${c.region}` : ""}
            {" · "}<a href={chUrl(c.company_number)} target="_blank" rel="noreferrer">Companies House record ↗</a>
          </div>
        </div>
        <div className="right"><Link className="btn" to={`/connections/${c.company_number}`}>Connection map</Link></div>
      </div>

      <div className="factline">
        <div><b><Score value={score?.score ?? null} coverage={score?.coverage} /></b><span>Score{score ? ` · ${Math.round(Number(score.coverage))}% of criteria had data` : ""}</span></div>
        <div><b>{int(latest?.employees)}</b><span>Staff{latest ? ` · ${date(latest.period_end)}` : ""}</span></div>
        <div><b>{est ? range(est.revenue_low, est.revenue_high) : "—"}</b><span>Revenue · {est ? (est.basis === "filed" ? "filed" : "estimate") : "unknown"}</span></div>
        <div><b>{years(c.incorporation_date)}</b><span>Years trading</span></div>
        <div><b>{age ?? "—"}</b><span>Oldest owner's age</span></div>
        <div><b>{money(latest?.net_assets ?? null)}</b><span>Net assets</span></div>
      </div>

      {score?.excluded && <div className="callout red"><b>Excluded by your buy box:</b> {score.exclusion}</div>}
      {data.changes.filter((x) => Date.now() - new Date(x.detected_at).getTime() < 30 * 864e5).length > 0 && (
        <div className="callout">
          <b>Changed recently:</b>{" "}
          {data.changes.filter((x) => Date.now() - new Date(x.detected_at).getTime() < 30 * 864e5).slice(0, 4).map((x) => describeChange(x)).join("; ")}.{" "}
          <a href="#changes">History</a>
        </div>
      )}

      <div className="company-grid">
        <div className="main">
          <section>
            <div className="sechead"><h2>Why this score</h2><span className="right"><Link to="/buy-box">Edit buy box</Link></span></div>
            {score ? (
              <table className="reasons">
                <tbody>
                  {score.reasons.map((r) => (
                    <tr key={r.key}>
                      <td style={{ width: 150 }}>
                        <span className={`reason-mark ${r.status}`}>{{ good: "✓", partial: "~", miss: "✕", unknown: "?" }[r.status]}</span>
                        {r.label}
                      </td>
                      <td className={r.status === "unknown" ? "faint" : ""}>{r.text}</td>
                      <td className="num pts">{r.status === "unknown" ? <span className="faint">no data</span> : `${r.points} / ${r.max}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="faint">Not scored yet.</div>}
          </section>

          <section>
            <div className="sechead"><h2>Financial history</h2><span className="faint small">{fin.filter((f) => !f.period_inferred).length} years from filed accounts{fin.some((f) => f.period_inferred) ? "; dashed points are prior-year figures with an inferred date" : ""}</span></div>
            {fin.length ? (
              <>
                <div className="multiples">
                  <SmallLine title="Staff" points={series("employees")} format={(n) => int(n)} />
                  <SmallLine title="Net assets" points={series("net_assets")} format={(n) => money(n)} />
                  <SmallLine title="Cash" points={series("cash")} format={(n) => money(n)} />
                  <SmallLine title="Debtors" points={series("debtors")} format={(n) => money(n)} />
                  {fin.some((f) => f.turnover) && <SmallLine title="Turnover" points={series("turnover")} format={(n) => money(n)} />}
                  {fin.some((f) => f.profit_loss) && <SmallLine title="Profit" points={series("profit_loss")} format={(n) => money(n)} />}
                </div>
                <table style={{ marginTop: 14 }}>
                  <thead><tr><th>Period end</th><th className="num">Staff</th><th className="num">Turnover</th><th className="num">Profit</th><th className="num">Net assets</th><th className="num">Cash</th><th className="num hide-sm">Debtors</th></tr></thead>
                  <tbody>
                    {[...fin].reverse().map((f) => (
                      <tr key={f.period_end}>
                        <td>{date(f.period_end)}{f.period_inferred && <span className="faint small"> · date inferred</span>}</td>
                        <td className="num">{int(f.employees)}</td>
                        <td className="num">{money(f.turnover, { precise: true })}</td>
                        <td className={`num ${Number(f.profit_loss) < 0 ? "neg" : ""}`}>{money(f.profit_loss, { precise: true })}</td>
                        <td className={`num ${Number(f.net_assets) < 0 ? "neg" : ""}`}>{money(f.net_assets, { precise: true })}</td>
                        <td className="num">{money(f.cash, { precise: true })}</td>
                        <td className="num hide-sm">{money(f.debtors, { precise: true })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {est && <p className="muted small">Revenue: {range(est.revenue_low, est.revenue_high)}. Method: {est.method}.</p>}
              </>
            ) : <div className="faint">No accounts imported.</div>}
          </section>

          <Valuation data={data} num={num} onSaved={reload} />

          <section>
            <div className="sechead"><h2>Ownership</h2><Flags flags={own?.flags} address={c.address_flag} /></div>
            {own ? (
              <>
                <p style={{ margin: "0 0 10px" }}><b>{OWNERSHIP[own.ownership_type] ?? own.ownership_type}.</b> <span className="muted">{own.explanation}</span></p>
                {own.ultimate_owners.length > 0 && (
                  <table>
                    <thead><tr><th>Ultimate owner</th><th>Born</th><th className="num">Age</th><th>Held through</th></tr></thead>
                    <tbody>
                      {own.ultimate_owners.map((u, i) => (
                        <tr key={i}>
                          <td>{u.name}{u.unresolved && <span className="faint small"> · {u.kind}, not traced further</span>}</td>
                          <td>{u.birth_year ? `${MONTHS[u.birth_month ?? 0]} ${u.birth_year}` : "—"}</td>
                          <td className="num">{ageFrom(u.birth_year) ?? "—"}</td>
                          <td className="muted">{u.via.length ? u.via.join(" → ") : "Direct"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {data.people.length > 0 && (
                  <details style={{ marginTop: 12 }}>
                    <summary className="muted" style={{ cursor: "pointer" }}>All owner records on file ({data.people.length})</summary>
                    <table style={{ marginTop: 8 }}>
                      <thead><tr><th>Name</th><th>Type</th><th>Control</th><th>From</th><th>Ceased</th></tr></thead>
                      <tbody>
                        {data.people.map((p, i) => (
                          <tr key={i} className={p.ceased_on ? "excluded" : ""}>
                            <td>{p.name}{p.registration_number ? <span className="faint small"> · {p.registration_number}{p.country_registered ? `, ${p.country_registered}` : ""}</span> : null}</td>
                            <td>{p.kind}</td>
                            <td className="small">{p.natures.map(natureLabel).join("; ")}</td>
                            <td>{date(p.notified_on)}</td>
                            <td>{p.ceased_on ? date(p.ceased_on) : ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                )}
              </>
            ) : (
              <div className="faint">No owner data yet. Import the Companies House PSC snapshot to trace owners (see the Import page).</div>
            )}
          </section>

          <section>
            <div className="sechead"><h2>Connections</h2><span className="right"><Link to={`/connections/${c.company_number}`}>Open map</Link></span></div>
            {data.links.length ? (
              <table>
                <thead><tr><th>Company</th><th>Link</th><th>Confidence</th><th className="hide-sm">Evidence</th></tr></thead>
                <tbody>
                  {data.links.map((l, i) => (
                    <tr key={i}>
                      <td>
                        {l.in_list ? <Link to={`/c/${l.other}`}>{l.other_name ?? l.other}</Link> : <span>{l.other_name ?? l.other} <span className="faint small">· not in your list</span></span>}
                        <div className="sub">{l.other}</div>
                      </td>
                      <td>{l.kind === "owned_by" ? (l.direction === "parent" ? "Parent company" : "Subsidiary") : LINK_KIND[l.kind]}{l.via ? <div className="sub">{l.via}</div> : null}</td>
                      <td className={l.confidence === "confirmed" ? "pos" : l.confidence === "possible" ? "faint" : ""}>{cap(l.confidence)}</td>
                      <td className="muted small hide-sm">{l.evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="faint">No links found in the data imported so far.</div>}
          </section>

          <Research data={data} num={num} onAdded={reload} />

          <section id="changes">
            <div className="sechead"><h2>Change history</h2><span className="faint small">What differed each time new data was imported.</span></div>
            {data.changes.length ? (
              <table>
                <tbody>
                  {data.changes.map((x) => (
                    <tr key={x.id}>
                      <td style={{ width: 130 }} className="muted">{date(x.detected_at)}</td>
                      <td style={{ width: 130 }}><b>{CHANGE_KIND[x.kind] ?? x.kind}</b></td>
                      <td className={x.kind === "status" && isBadStatus(x.new_value) ? "neg" : ""}>{describeChange(x)}</td>
                      <td className="faint small hide-sm">{x.filename}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="faint">No changes recorded. Re-import a newer Companies House file to see what moves.</div>}
          </section>

          <section>
            <h2>Record</h2>
            <dl className="facts">
              <dt>Company number</dt><dd>{c.company_number}</dd>
              <dt>Type</dt><dd>{c.company_type ?? "—"}</dd>
              <dt>Industry (SIC)</dt><dd>{c.sic_codes.join(", ") || "—"}</dd>
              <dt>Registered office</dt><dd>{c.registered_address ?? "—"} <Flags address={c.address_flag} /></dd>
              <dt>Review tier</dt><dd>{c.review_tier ?? "—"}</dd>
              {c.last_accounts_date && <><dt>Last accounts</dt><dd>Made up to {date(c.last_accounts_date)}</dd></>}
              <dt>Source</dt><dd>{c.source ?? "—"} · updated {dateTime(c.updated_at)} ({relDays(c.updated_at)})</dd>
              {Object.entries(c.extra ?? {}).map(([k, v]) => (
                <FactRow key={k} k={k} v={v} />
              ))}
            </dl>
          </section>
        </div>

        <aside>
          <MyCall data={data} num={num} setState={setState} onNote={(n) => setData({ ...data, notes: [n, ...data.notes] })} onOutreach={reload} />
        </aside>
      </div>
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

function FactRow({ k, v }: { k: string; v: unknown }) {
  return <><dt className="small">{k.replace(/_/g, " ")}</dt><dd className="small">{String(v)}</dd></>;
}

function MyCall({ data, num, setState, onNote, onOutreach }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>;
  onNote: (n: CompanyDetail["notes"][number]) => void; onOutreach: () => void;
}) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [next, setNext] = useState(data.state.next_action ?? "");
  const [nextOn, setNextOn] = useState(data.state.next_action_on ?? "");
  const [contact, setContact] = useState({ contact_name: "", contact_role: "owner", channel: "letter", summary: "" });
  const s = data.state;

  return (
    <>
      <section style={{ paddingTop: 0 }}>
        <h2>My call</h2>
        <div className="label" style={{ marginBottom: 4 }}>Status</div>
        <div className="seg">
          {STATUSES.map((st) => (
            <button key={st} className={s.status === st ? "on" : ""} onClick={() => setState({ status: st })}>{STATUS_LABEL[st]}</button>
          ))}
        </div>
        <div className="label" style={{ margin: "14px 0 4px" }}>Rating <span className="faint">(keys 1–5)</span></div>
        <div className="rating">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className={s.rating === n ? "on" : ""} onClick={() => setState(s.rating === n ? { clear_rating: true } : { rating: n })}>{n}</button>
          ))}
        </div>
        <div className="label" style={{ margin: "14px 0 4px" }}>Next action</div>
        <div style={{ display: "flex", gap: 6 }}>
          <input type="text" style={{ flex: 1 }} value={next} placeholder="e.g. Send approach letter" onChange={(e) => setNext(e.target.value)}
                 onBlur={() => next !== (s.next_action ?? "") && setState({ next_action: next || null })} />
          <input type="date" value={nextOn ?? ""} onChange={(e) => { setNextOn(e.target.value); setState({ next_action_on: e.target.value || null }); }} />
        </div>
        {s.tags?.length ? <div className="faint small" style={{ marginTop: 10 }}>Tags: {s.tags.join(", ")}</div> : null}
      </section>

      <section>
        <h2>Notes</h2>
        <textarea value={note} placeholder="What do you think? Ctrl+Enter to save." onChange={(e) => setNote(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && note.trim()) {
                      setSaving(true); onNote(await api.addNote(num, note)); setNote(""); setSaving(false);
                    }
                  }} />
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn primary" disabled={!note.trim() || saving}
                  onClick={async () => { setSaving(true); onNote(await api.addNote(num, note)); setNote(""); setSaving(false); }}>Add note</button>
        </div>
        <ul className="notes">
          {data.notes.map((n) => (
            <li key={n.id}>
              <div className="meta">{dateTime(n.created_at)}{n.source !== "app" ? ` · ${n.source.replace("import:", "from ")}` : ""}</div>
              {n.body}
            </li>
          ))}
          {!data.notes.length && <li className="faint">No notes yet. Notes are never overwritten by a data refresh.</li>}
        </ul>
      </section>

      <section>
        <h2>Outreach</h2>
        <form onSubmit={async (e) => {
          e.preventDefault();
          if (!contact.contact_name.trim()) return;
          await api.addOutreach({ ...contact, company_number: num });
          setContact({ ...contact, contact_name: "", summary: "" });
          onOutreach();
        }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 110px", gap: 6 }}>
            <input type="text" placeholder="Who" value={contact.contact_name} onChange={(e) => setContact({ ...contact, contact_name: e.target.value })} />
            <select value={contact.contact_role} onChange={(e) => setContact({ ...contact, contact_role: e.target.value })}>
              <option value="owner">Owner</option><option value="adviser">Adviser</option><option value="broker">Broker</option>
              <option value="investor">Investor</option><option value="other">Other</option>
            </select>
            <input type="text" placeholder="What happened" value={contact.summary} onChange={(e) => setContact({ ...contact, summary: e.target.value })} />
            <select value={contact.channel} onChange={(e) => setContact({ ...contact, channel: e.target.value })}>
              <option value="letter">Letter</option><option value="email">Email</option><option value="call">Call</option>
              <option value="linkedin">LinkedIn</option><option value="meeting">Meeting</option>
            </select>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
            <button className="btn" type="submit" disabled={!contact.contact_name.trim()}>Log contact</button>
          </div>
        </form>
        <ul className="notes">
          {data.outreach.map((o) => (
            <li key={o.id}>
              <div className="meta">{date(o.happened_on)} · {o.channel} · {o.contact_role}</div>
              <b>{o.contact_name}</b>{o.summary ? `: ${o.summary}` : ""}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Research({ data, num, onAdded }: { data: CompanyDetail; num: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [r, setR] = useState({ kind: "summary", content: "", source_url: "", source_label: "" });
  return (
    <section>
      <div className="sechead">
        <h2>Research and sources</h2>
        <span className="right"><button className="btn quiet" onClick={() => setOpen(!open)}>{open ? "Cancel" : "Add finding"}</button></span>
      </div>
      {open && (
        <form style={{ display: "grid", gap: 6, marginBottom: 12 }} onSubmit={async (e) => {
          e.preventDefault();
          await api.addResearch(num, { ...r, source_url: r.source_url || null, source_label: r.source_label || null });
          setR({ kind: "summary", content: "", source_url: "", source_label: "" }); setOpen(false); onAdded();
        }}>
          <div style={{ display: "flex", gap: 6 }}>
            <select value={r.kind} onChange={(e) => setR({ ...r, kind: e.target.value })}>
              <option value="summary">What they do</option><option value="classification">Business type</option>
              <option value="website">Website</option><option value="other">Other</option>
            </select>
            <input type="url" style={{ flex: 1 }} placeholder="Source link (required for anything you did not see yourself)" value={r.source_url}
                   onChange={(e) => setR({ ...r, source_url: e.target.value })} />
          </div>
          <textarea placeholder="Finding" value={r.content} onChange={(e) => setR({ ...r, content: e.target.value })} />
          <div><button className="btn primary" disabled={!r.content.trim()}>Save finding</button></div>
          <div className="faint small">Findings count towards exclusion keywords, so “van-based installers” here will exclude a company if your buy box excludes “installers”.</div>
        </form>
      )}
      {data.research.length ? (
        <ul className="notes" style={{ marginTop: 0 }}>
          {data.research.map((x) => (
            <li key={x.id}>
              <div className="meta">
                {cap(x.kind)} · {date(x.retrieved_at)}
                {x.source_url ? <> · <a href={x.source_url} target="_blank" rel="noreferrer">{x.source_label || hostOf(x.source_url)} ↗</a></> : " · no source"}
              </div>
              {x.content}
            </li>
          ))}
        </ul>
      ) : !open && <div className="faint">Nothing recorded yet. AI research with sources is planned for Q2; until then add findings by hand.</div>}
    </section>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
const hostOf = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
function natureLabel(n: string) {
  return n.replace(/-/g, " ").replace(/ percent/, "%").replace(/ownership of shares/, "shares").replace(/voting rights/, "votes");
}
