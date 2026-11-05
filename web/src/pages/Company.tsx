import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { ErrorLine, Flags, Score, Toast, useAsync } from "../components/bits";
import { AreaChart as SmallLine } from "../components/charts";
import Valuation from "../components/Valuation";
import DealProgress from "../components/DealProgress";
import MyScores from "../components/MyScores";
import { Enrichment, Location } from "../components/CompanyExtras";
import { ageFrom, CHANGE_KIND, chUrl, date, dateTime, describeChange, int, isBadStatus, LINK_KIND, money, MONTHS, OWNERSHIP, range, relDays, toNum, years } from "../format";


export default function Company() {
  const { num = "" } = useParams();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const bbParam = /^\d+$/.test(params.get("bb") ?? "") ? Number(params.get("bb")) : null;
  const { data, error, setData, reload } = useAsync(() => api.company(num, bbParam), [num, bbParam]);
  const [toast, setToast] = useState<string | null>(null);

  const setState = async (patch: Record<string, unknown>) => {
    if (!data) return;
    try {
      const state = await api.setState(num, patch);
      setData({ ...data, state: state as CompanyDetail["state"] });
      setToast(patch.rating ? `Rating set to ${patch.rating}/5` : "Saved");
    } catch (e: any) { setToast(`Not saved: ${e.message}`); }
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
  const { company: c, financials: fin, estimate: est, ownership: own } = data;
  const scores = data.scores ?? [];
  const shownId = bbParam ?? data.buy_box.id;
  const score = scores.find((x) => x.buy_box_id === shownId) ?? data.score;
  const shownName = scores.find((x) => x.buy_box_id === shownId)?.buy_box ?? data.buy_box.name;
  const pickBox = (id: number) => { const p = new URLSearchParams(params); p.set("bb", String(id)); setParams(p, { replace: true }); };
  const latest = [...fin].reverse().find((f) => !f.period_inferred);
  const age = ageFrom(own?.oldest_birth_year);
  const series = (k: keyof (typeof fin)[number]) =>
    fin.map((f) => ({ x: f.period_end, y: toNum(f[k] as string | number | null), inferred: f.period_inferred }));

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="crumb">
            <a href="/companies" onClick={(e) => { if (window.history.length > 1) { e.preventDefault(); nav(-1); } }}>← Back</a> / {c.company_number}
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
        <div><b><Score value={score && !score.excluded ? score.score : null} coverage={score?.coverage} /></b>
          <span>{score?.excluded ? `Outside ${shownName}` : `Score in ${shownName}`}{score && !score.excluded ? ` · ${Math.round(Number(score.coverage))}% had data` : ""}</span></div>
        <div><b>{int(latest?.employees)}</b><span>Staff{latest ? ` · ${date(latest.period_end)}` : ""}</span></div>
        <div><b>{est ? range(est.revenue_low, est.revenue_high) : "—"}</b><span>Revenue · {est ? (est.basis === "filed" ? "filed" : "estimate") : "unknown"}</span></div>
        <div><b>{years(c.incorporation_date)}</b><span>Years trading</span></div>
        <div><b>{age ?? "—"}</b><span>Oldest owner's age</span></div>
        <div><b>{money(latest?.net_assets ?? null)}</b><span>Net assets</span></div>
      </div>

      {score?.excluded && <div className="callout red"><b>Outside {shownName}:</b> {score.exclusion}</div>}
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
            <div className="sechead"><h2>Why this score</h2>
              <span className="right"><Link to={`/buy-box?id=${shownId}`}>Edit {shownName}</Link></span></div>
            {scores.length > 1 && (
              <div className="boxtabs" role="tablist" aria-label="Score in each buy box">
                {scores.map((x) => (
                  <button key={x.buy_box_id} role="tab" aria-selected={x.buy_box_id === shownId}
                          className={`${x.buy_box_id === shownId ? "on" : ""} ${x.excluded ? "out" : ""}`} onClick={() => pickBox(x.buy_box_id)}>
                    <span className="nm">{x.buy_box}</span>
                    <span className="sc">{x.excluded ? "outside" : Math.round(Number(x.score))}</span>
                  </button>
                ))}
              </div>
            )}
            {score ? (
              <table className="reasons">
                <tbody>
                  {score.reasons.map((r) => (
                    <tr key={r.key}>
                      <td style={{ width: 150 }}>
                        <span className={`reason-mark ${r.status === "unscored" ? "unknown" : r.status}`}>{({ good: "✓", partial: "~", miss: "✕", unknown: "?", unscored: "–" } as Record<string, string>)[r.status]}</span>
                        {r.label}
                      </td>
                      <td className={r.status === "unknown" ? "faint" : ""}>{r.text}</td>
                      <td className="num pts">{r.status === "unknown" ? <span className="faint">no data</span> : r.status === "unscored" ? <span className="faint">not counted</span> : `${r.points} / ${r.max}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="faint">Not scored yet.</div>}
          </section>

          <Enrichment key={JSON.stringify(data.enrichment)} data={data} num={num} onSaved={reload} />

          <section>
            <div className="sechead"><h2>Financial history</h2><span className="faint small">{(() => { const n = fin.filter((f) => !f.period_inferred).length; return `${n} ${n === 1 ? "year" : "years"} from filed accounts`; })()}{fin.some((f) => f.period_inferred) ? "; dashed points are prior-year figures with an inferred date" : ""}</span></div>
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
                <BalanceSheet fin={fin} />
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
              <div className="faint">No owner data yet. Owners load with the Companies House refresh (see the Data page). Some companies file no owner details.</div>
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

          <Location data={data} />

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
            ) : <div className="faint">No changes recorded yet. Changes show up after each monthly Companies House refresh.</div>}
          </section>

          <section>
            <h2>Record</h2>
            <dl className="facts">
              <dt>Company number</dt><dd>{c.company_number}</dd>
              <dt>Type</dt><dd>{c.company_type ?? "—"}</dd>
              <dt>Industry (SIC)</dt><dd>{c.sic_codes.join(", ") || "—"}</dd>
              <dt>Registered office</dt><dd>{c.registered_address ?? "—"} <Flags address={c.address_flag} /></dd>
              <dt>Review tier</dt><dd>{c.review_tier ?? "—"}</dd>
              {c.last_accounts_date && <><dt>Last accounts</dt><dd>Made up to {date(c.last_accounts_date)}
                {c.accounts_category ? <span className="faint"> · {accountsLabel(c.accounts_category)}</span> : null}</dd></>}
              {c.accounts_next_due && <><dt>Next accounts due</dt><dd className={overdue(c.accounts_next_due, c.status) ? "neg" : ""}>
                {date(c.accounts_next_due)}{overdue(c.accounts_next_due, c.status) ? " · overdue" : ""}</dd></>}
              {c.confirmation_next_due && <><dt>Confirmation statement due</dt><dd className={overdue(c.confirmation_next_due, c.status) ? "neg" : ""}>
                {date(c.confirmation_next_due)}{overdue(c.confirmation_next_due, c.status) ? " · overdue" : ""}</dd></>}
              {c.charges_total != null && <><dt title="Mortgages and debentures: loans secured on the company's assets">Charges</dt><dd>
                {c.charges_total === 0 ? "None registered" : <>
                  <b className={c.charges_outstanding ? "" : "faint"}>{c.charges_outstanding ?? 0} outstanding</b>
                  {c.charges_part_satisfied ? `, ${c.charges_part_satisfied} part repaid` : ""}
                  {c.charges_satisfied ? `, ${c.charges_satisfied} repaid` : ""} · {c.charges_total} in total.{" "}
                  <a href={`${chUrl(c.company_number)}/charges`} target="_blank" rel="noreferrer">Who holds them ↗</a></>}
              </dd></>}
              {c.previous_names && c.previous_names.length > 0 && <><dt>Previous names</dt><dd>
                {c.previous_names.map((p, i) => <div key={i}>{p.name}{p.until ? <span className="faint"> · until {date(p.until)}</span> : null}</div>)}
              </dd></>}
              <dt>Source</dt><dd>{c.source ?? "—"} · updated {dateTime(c.updated_at)} ({relDays(c.updated_at)})</dd>
            </dl>
            {Object.keys(c.extra ?? {}).length > 0 && (
              <details className="small" style={{ marginTop: 8 }}>
                <summary className="faint">Fields from your imported file ({Object.keys(c.extra).length})</summary>
                <dl className="facts">{Object.entries(c.extra).map(([k, v]) => <FactRow key={k} k={k} v={v} />)}</dl>
              </details>
            )}
          </section>
        </div>

        <aside>
          <MyCall data={data} num={num} setState={setState} onNote={(n) => setData({ ...data, notes: [n, ...data.notes] })} onOutreach={reload} onScored={reload} />
        </aside>
      </div>
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

function FactRow({ k, v }: { k: string; v: unknown }) {
  return <><dt className="small">{k.replace(/_/g, " ")}</dt><dd className="small">{String(v)}</dd></>;
}

function MyCall({ data, num, setState, onNote, onOutreach, onScored }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>;
  onNote: (n: CompanyDetail["notes"][number]) => void; onOutreach: () => void; onScored: () => void;
}) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const addNote = async () => {
    if (!note.trim()) return;
    setSaving(true); setNoteErr(null);
    try { onNote(await api.addNote(num, note)); setNote(""); }
    catch (e: any) { setNoteErr(`Not saved: ${e.message}`); }
    finally { setSaving(false); }
  };
  const [next, setNext] = useState(data.state.next_action ?? "");
  const [nextOn, setNextOn] = useState(data.state.next_action_on ?? "");
  const [contact, setContact] = useState({ contact_name: "", contact_role: "owner", channel: "letter", summary: "" });
  const s = data.state;

  return (
    <>
      <section>
        <DealProgress data={data} num={num} setState={setState} />
      </section>

      <section>
        <h2>Your scores</h2>
        <MyScores num={num} criteria={data.manual.criteria} values={data.manual.values} onChange={() => onScored()} />
      </section>

      <section>
        <div className="label" style={{ margin: "0 0 4px" }}>Rating <span className="faint">(keys 1–5)</span></div>
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
                      addNote();
                    }
                  }} />
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn primary" disabled={!note.trim() || saving}
                  onClick={addNote}>Add note</button>
          {noteErr && <span className="neg small" style={{ marginLeft: 8, alignSelf: "center" }}>{noteErr}</span>}
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
      ) : !open && <div className="faint">Nothing recorded yet. Ask Claude to research this company (see Connect Claude), or add a finding by hand.</div>}
    </section>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
const hostOf = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
function natureLabel(n: string) {
  return n.replace(/-/g, " ").replace(/ percent/, "%").replace(/ownership of shares/, "shares").replace(/voting rights/, "votes");
}


function overdue(d: string | null | undefined, status: string | null) {
  return !!d && (status ?? "").startsWith("active") && new Date(d).getTime() < Date.now() - 864e5;
}

const ACCOUNTS_LABEL: Record<string, string> = {
  "micro entity": "micro-entity accounts", "small": "small company accounts", "total exemption full": "small (unaudited) accounts",
  "total exemption small": "small (unaudited) accounts", "unaudited abridged": "abridged small accounts", "audited abridged": "abridged small accounts",
  "partial exemption": "small accounts (partial exemption)", "medium": "medium-sized company accounts", "full": "full accounts",
  "group": "group accounts: it has subsidiaries", "audit exemption subsidiary": "subsidiary exemption: owned by a group",
  "filing exemption subsidiary": "subsidiary exemption: owned by a group", "dormant": "dormant accounts",
  "no accounts filed": "no accounts filed yet", "initial": "initial accounts",
};
export function accountsLabel(cat: string) { return ACCOUNTS_LABEL[cat] ?? cat; }

/** Balance sheet and cost detail, where the accounts include it. Creditors
    are worked out from the totals the accounts state. */
function BalanceSheet({ fin }: { fin: CompanyDetail["financials"] }) {
  const n = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v));
  const rows = [...fin].reverse().filter((f) => !f.period_inferred).map((f) => {
    const ca = n(f.current_assets), nca = n(f.net_current_assets), tal = n(f.total_assets_less_cl), na = n(f.net_assets);
    // Worked out from totals; a negative result means the filing's totals do not add up, so show nothing.
    const short = ca !== null && nca !== null && ca - nca >= 0 ? ca - nca : null;
    const long = tal !== null && na !== null && tal - na >= 0 ? tal - na : null;
    return { f, short, long };
  }).filter(({ f, short, long }) => [f.fixed_assets, f.intangible_assets, f.current_assets, f.gross_profit, f.director_pay, f.staff_costs]
    .some((v) => v !== null && v !== undefined) || short !== null || long !== null);
  if (!rows.length) return null;
  type Col = { label: string; get: (r: (typeof rows)[number]) => number | string | null | undefined; sub?: (r: (typeof rows)[number]) => string | null };
  const all: Col[] = [
    { label: "Fixed assets", get: (r) => r.f.fixed_assets,
      sub: (r) => (r.f.intangible_assets != null && Number(r.f.intangible_assets) !== 0 ? `${money(r.f.intangible_assets)} intangible` : null) },
    { label: "Owed within a year", get: (r) => r.short },
    { label: "Owed after a year", get: (r) => r.long },
    { label: "Gross profit", get: (r) => r.f.gross_profit },
    { label: "Staff costs", get: (r) => r.f.staff_costs },
    { label: "Directors' pay", get: (r) => r.f.director_pay },
  ];
  // Only the columns these accounts actually give.
  const cols = all.filter((c) => rows.some((r) => c.get(r) !== null && c.get(r) !== undefined));
  return (
    <>
      <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>Balance sheet and costs</h3>
      <table>
        <thead><tr><th>Period end</th>{cols.map((c) => <th key={c.label} className="num">{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.f.period_end}>
              <td className="nowrap">{date(r.f.period_end)}</td>
              {cols.map((c) => {
                const v = c.get(r); const sub = c.sub?.(r);
                return <td key={c.label} className={`num ${Number(v) < 0 ? "neg" : ""}`}>
                  {v === null || v === undefined ? "—" : money(v, { precise: true })}{sub && <div className="sub">{sub}</div>}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="faint small">“Owed within a year” is current assets minus net current assets; “owed after a year” is the rest of the
        liabilities and provisions (total assets less current liabilities, minus net assets). Charges are loans secured on assets; see the record below. Most small companies file abridged accounts
        without profit and loss detail, so those columns are often blank.</p>
    </>
  );
}
