import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { ErrorLine, Flags, Hint, Score, Signals, StatusMark, Toast, useAsync, WatchButton, LogoEditor } from "../components/bits";
import Valuation from "../components/Valuation";
import DealProgress from "../components/DealProgress";
import MyScores from "../components/MyScores";
import Financials from "../components/Financials";
import { nextInList, RuleOutChips, type RuleOutPick } from "../components/RuleOut";
import { BT_LABEL, Enrichment, Location, shortSummary } from "../components/CompanyExtras";
import { Charges, Filings, Fold, Head, OwnersDirectors, WebsiteFinder } from "../components/Profile";
import { ageFrom, CHANGE_KIND, chUrl, date, describeChange, int, isBadStatus, LINK_KIND, money, OWNERSHIP, range, relDays, years } from "../format";


export default function Company() {
  const { num = "" } = useParams();
  useEffect(() => { document.body.classList.add("has-mbar"); return () => document.body.classList.remove("has-mbar"); }, []);
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

  // On opening: check Companies House for anything new (needs CH_API_KEY).
  // Skipped if checked in the last day; the page shows stored data meanwhile.
  const [chCheck, setChCheck] = useState<string | null>(null);
  const checkedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!data?.ch?.enabled || checkedFor.current === num) return;
    checkedFor.current = num;
    const last = data.ch.fetched?.checked_at ?? data.ch.fetched?.fetched_at;
    // Check now if Companies House shows newer accounts than we have figures
    // for (and they aren't already known to be PDF only); otherwise once a day.
    const latest = [...data.financials].reverse().find((f) => !f.period_inferred)?.period_end;
    const lad = data.company.last_accounts_date;
    const pdf = ((data.ch.fetched as any)?.accounts_pdf ?? []) as string[];
    const gap = !!lad && !pdf.includes(lad) && (!latest || new Date(lad).getTime() - new Date(latest).getTime() > 45 * 864e5);
    if (!gap && last && Date.now() - new Date(last).getTime() < 864e5) return;
    setChCheck("Checking Companies House…");
    api.chCheck(num)
      .then((r) => {
        setChCheck(r.changes ? `${r.changes} new from Companies House` : r.changed ? "Updated from Companies House" : null);
        if (r.changed) reload();
      })
      .catch(() => setChCheck(null));
  }, [data, num]); // eslint-disable-line react-hooks/exhaustive-deps

  // While its PDF accounts are being read after a refresh, look again every 20 seconds.
  const [pollUntil, setPollUntil] = useState(0);
  useEffect(() => {
    if (!pollUntil || Date.now() > pollUntil || !data?.pdf_waiting?.length) return;
    const t = setTimeout(reload, 20_000);
    return () => clearTimeout(t);
  }, [data, pollUntil]); // eslint-disable-line react-hooks/exhaustive-deps

  // Which section is in view, for the section bar.
  const [inView, setInView] = useState("overview");
  useEffect(() => {
    if (!data) return;
    const ids = ["overview", "activity", "financials", "ownership", "group", "value", "compare", "charges", "filings", "group", "score", "research", "deal", "changes"];
    const els = ids.map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (vis[0]) setInView(vis[0].target.id);
    }, { rootMargin: "-130px 0px -55% 0px" });
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [data ? num : null]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const prof = ((data.ch?.fetched as any)?.profile ?? {}) as any;
  const val = data.valuation;
  // Latest filed profit: EBITDA where depreciation is filed for the same year, else operating profit.
  const profit = (() => {
    const f = [...fin].reverse().find((x) => !x.period_inferred && x.operating_profit != null);
    if (!f) return null;
    const n = (v: any) => (v == null ? null : Number(v));
    const da = n(f.depreciation_amortisation) ?? (n(f.depreciation) != null || n(f.amortisation) != null ? (n(f.depreciation) ?? 0) + (n(f.amortisation) ?? 0) : null);
    return { v: Number(f.operating_profit) + (da ?? 0), ebitda: da != null && da > 0, at: f.period_end };
  })();
  const staffYears = fin.filter((x) => !x.period_inferred && x.employees != null);
  const staffChange = staffYears.length >= 2 ? { d: Number(staffYears[staffYears.length - 1].employees) - Number(staffYears[staffYears.length - 2].employees) } : null;
  const activity = [...fin].reverse().find((f) => f.principal_activity);
  const ard = prof.accounts?.accounting_reference_date;
  const yearEnd = ard?.day && ard?.month ? new Date(2000, Number(ard.month) - 1, Number(ard.day)).toLocaleDateString("en-GB", { day: "numeric", month: "long" }) : null;
  // Refresh: everything from Companies House now, then its PDF accounts read in the background.
  const refresh = async () => {
    setChCheck("Refreshing from Companies House…");
    try {
      const r = await api.refreshCompany(num);
      setChCheck([r.changes ? `${r.changes} new` : "Up to date", r.accounts_added ? `${r.accounts_added} accounts added` : "",
                  r.pdf_reading.length ? `reading ${r.pdf_reading.length} PDF accounts…` : ""].filter(Boolean).join(" · "));
      if (r.pdf_reading.length) setPollUntil(Date.now() + 20 * 60e3);
      reload();
    } catch (e: any) { setChCheck(`Refresh failed: ${e.message}`); }
  };

  const mNext = nextInList(num);
  return (
    <>
      <UndoBar num={num} />
      <div className="pagehead">
        <div>
          <div className="crumb">
            <a href="/companies" onClick={(e) => { if (window.history.length > 1) { e.preventDefault(); nav(-1); } }}>← Back</a> / {c.company_number}
            {chCheck && <span className="chcheck"> · {chCheck}</span>}
          </div>
          <h1 className="coname has-logo"><LogoEditor num={c.company_number} name={c.name} website={data.enrichment?.website} size={40} /><span>{c.name}</span></h1>
          {/* Two chips (company status, your stage); the rest as plain text. Region, accounts and ownership are in the profile. */}
          <div className="chips metaline">
            <span className={`chip ${isBadStatus(c.status) ? "red" : "green"}`}>{c.status ? cap(c.status) : "Status unknown"}{c.dissolution_date ? ` ${date(c.dissolution_date)}` : ""}</span>
            {data.state.status !== "new" && <StatusMark s={data.state.status} />}
            <span className="mt">No. {c.company_number}</span>
            {c.incorporation_date && <span className="mt">Since {c.incorporation_date.slice(0, 4)} ({years(c.incorporation_date)} yrs)</span>}
            {data.sics[0] && <span className="mt">{data.sics[0].description}</span>}
            {townOf(c.registered_address, c.postcode) && <span className="mt">{townOf(c.registered_address, c.postcode)}</span>}
            {data.enrichment?.website && <a className="mt" href={data.enrichment.website} target="_blank" rel="noreferrer">{data.enrichment.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a>}
            <Signals s={data.signals} region={c.region} />
            {data.sold?.sold_to && <span className="chip red" title="From the owners register or your research">Sold{data.sold.sold_on ? ` ${date(data.sold.sold_on)}` : ""} to {data.sold.sold_to}</span>}
          </div>
        </div>
        <div className="right">
          {data.ch?.enabled && <button className="btn quiet" onClick={refresh} title="Fetch everything from Companies House now, and read any accounts filed only as PDF">↻ Refresh</button>}
          <WatchButton kind="company" refId={c.company_number} on={!!data.watching} label={c.name} onChange={reload} />
          <a className="btn quiet" href={chUrl(c.company_number)} target="_blank" rel="noreferrer">Companies House ↗</a>
          {data.enrichment?.website && <a className="btn" href={data.enrichment.website} target="_blank" rel="noreferrer">Website ↗</a>}
        </div>
      </div>

      {/* The six things to screen on: fit, size, profit, price, people, succession. */}
      <div className="cokpis">
        <div className={`cokpi ${score?.excluded ? "bad" : ""}`}>
          <span className="k">Fit · {shownName}</span>
          {score?.excluded ? <b>Outside</b> : <b><Score value={score ? score.score : null} coverage={score?.coverage} /></b>}
          <span className="s">{score?.excluded ? score.exclusion : score ? `${Math.round(Number(score.coverage))}% of criteria had data` : "Not scored yet"}</span>
        </div>
        <div className="cokpi">
          <span className="k">Revenue</span>
          <b>{est ? <span className={est.basis === "filed" ? "" : "fig-est"}>{range(est.revenue_low, est.revenue_high)}</span> : "—"}
            {est && est.basis !== "filed" && <Hint text={`Estimate. ${est.method}`} />}</b>
          <span className="s">{!est ? "Not filed or estimated" : est.basis === "filed" ? `Filed${est.method?.match(/year to (?:\d{1,2} )?([A-Z][a-z]{2} \d{4})/)?.[1] ? ` · ${est.method.match(/year to (?:\d{1,2} )?([A-Z][a-z]{2} \d{4})/)![1]}` : ""}` : "Estimate"}</span>
        </div>
        <div className={`cokpi ${profit && profit.v < 0 ? "bad" : ""}`}>
          <span className="k">{profit?.ebitda ? "EBITDA" : "Operating profit"}</span>
          <b>{profit ? money(profit.v) : "—"}</b>
          <span className="s">{profit ? `Filed · ${date(profit.at)}${profit.ebitda ? " · incl. depreciation" : ""}` : "Not in the filed accounts"}</span>
        </div>
        <div className="cokpi">
          <span className="k">Indicative value</span>
          <b>{val?.value_low ? range(val.value_low, val.value_high) : "—"}</b>
          <span className="s">{val?.value_low ? (val.basis === "filed" ? "From filed profit" : val.basis === "filed_margin"
            ? `From its ${String(val.filed_margin_period ?? "").slice(0, 4)} margin${(val as any).filed_margin_old ? " (old)" : ""}` : "From estimates") : val?.basis === "loss" ? "Loss-making: no earnings value" : "Not enough figures"}</span>
        </div>
        <div className="cokpi">
          <span className="k">Staff</span>
          <b>{int(latest?.employees)}</b>
          <span className="s">{staffChange ? <span className={staffChange.d >= 0 ? "pos" : "neg"}>{staffChange.d >= 0 ? "+" : ""}{staffChange.d} on the year before</span> : latest ? `At ${date(latest.period_end)}` : "Not filed"}</span>
        </div>
        <div className="cokpi">
          <span className="k">Oldest owner</span>
          <b>{age ?? "—"}</b>
          <span className="s">{own && own.ownership_type !== "unknown" ? OWNERSHIP[own.ownership_type] : "Owners not traced"}</span>
        </div>
      </div>

      {(data.ch?.disqualified ?? []).length > 0 && (
        <div className="callout red"><b>Disqualified director:</b>{" "}
          {[...new Set(data.ch!.disqualified!.map((d) => d.name))].join(", ")}. Matched on name and month and year of birth: check the
          {" "}<a href="https://find-and-update.company-information.service.gov.uk/search/disqualified-officers" target="_blank" rel="noreferrer">disqualified directors register ↗</a>.</div>
      )}
      {(data.ch?.exemptions ?? []).length > 0 && (
        <div className="callout"><b>Exempt from the owners register:</b> {data.ch!.exemptions!.map((e) => `${e.kind}${e.from ? ` since ${date(e.from)}` : ""}`).join("; ")}.
          Usually a company with shares listed on a market, or owned by one.</div>
      )}
      <SameBusiness data={data} />
      {data.changes.filter((x) => Date.now() - new Date(x.detected_at).getTime() < 30 * 864e5).length > 0 && (
        <div className="callout">
          <b>Changed recently:</b>{" "}
          {data.changes.filter((x) => Date.now() - new Date(x.detected_at).getTime() < 30 * 864e5).slice(0, 4).map((x) => describeChange(x)).join("; ")}.{" "}
          <a href="#changes">History</a>
        </div>
      )}

      <CallBar key={num} data={data} num={num} setState={setState} onNote={(n) => setData({ ...data, notes: [n, ...data.notes] })} />

      <div className="company-page">
          <nav className="secnav" aria-label="Sections">
            {[["overview", "Overview"], ["activity", "Activity"], ["financials", "Financials"], ["ownership", "Owners & directors"],
              ["group", "Group"], ["value", "Value"], ["score", "Score"], ["charges", "Charges"], ["filings", "Filings"],
              ["research", "Research"], ["deal", "Deal"], ["changes", "History"]].map(([id, l]) => (
              <a key={id} href={`#${id}`} className={inView === id ? "on" : ""} onClick={(e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{l}</a>
            ))}
          </nav>
        <div className="pair top2 eq">
          <div className="pcol">
          <section id="overview">
            <Head icon="overview" title="Overview" />
            {data.enrichment?.summary || activity ? (
              <p className="ov-what">{data.enrichment?.summary ? shortSummary(data.enrichment.summary) : activity!.principal_activity}
                <span className="faint small"> · {data.enrichment?.summary ? `research${data.enrichment.updated_at ? `, ${date(data.enrichment.updated_at)}` : ""}` : `its own words, ${date(activity!.period_end)} accounts`}</span></p>
            ) : <p className="summary">{overviewSentence(data)}</p>}
            {(() => {
              const latest = [...data.financials].reverse().find((f) => !f.period_inferred && f.employees != null);
              const bits = [
                c.incorporation_date ? <>Founded <b>{new Date(c.incorporation_date).getFullYear()}</b></> : null,
                c.region || data.enrichment?.trading_region ? <b>{data.enrichment?.trading_region ?? c.region}</b> : null,
                latest?.employees != null ? <><b>{int(latest.employees)}</b> staff</> : null,
                data.enrichment?.website ? <a href={data.enrichment.website} target="_blank" rel="noreferrer">{data.enrichment.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a> : null,
                data.enrichment?.business_type ? <>{BT_LABEL[data.enrichment.business_type] ?? data.enrichment.business_type}{data.enrichment.recurring_revenue ? <> · recurring revenue: <b>{data.enrichment.recurring_revenue}</b></> : null}</> : null,
              ].filter(Boolean);
              return bits.length ? <div className="ov-ess">{bits.map((b, i) => <span key={i}>{b}</span>)}</div> : null;
            })()}
            {(data.enrichment?.summary && activity) && <div className="faint small" style={{ margin: "-4px 0 10px" }}>In its accounts: {activity.principal_activity}</div>}
            <dl className="facts">
              <dt>Type</dt><dd>{companyType(c.company_type)}{prof.is_community_interest_company ? " · community interest company" : ""}</dd>
              {(data.enrichment?.facts ?? []).length > 0 && <><dt>Key facts</dt><dd><ul className="ov-facts">
                {data.enrichment!.facts!.slice(0, 8).map((f, i) => <li key={i}><b>{f.label}:</b> {f.value}
                  {f.source_url ? <> <a className="faint small" href={f.source_url} target="_blank" rel="noreferrer">{hostOf(f.source_url)} ↗</a></> : null}</li>)}
              </ul></dd></>}
              {yearEnd && <><dt>Year end</dt><dd>{yearEnd}{prof.accounts?.last_accounts?.type ? <span className="faint"> · last filed as {String(prof.accounts.last_accounts.type).replace(/-/g, " ")}</span> : null}</dd></>}
              {prof.foreign_company_details && <><dt>Overseas company</dt><dd>
                {[prof.foreign_company_details.legal_form, prof.foreign_company_details.originating_registry?.country && `registered in ${prof.foreign_company_details.originating_registry.country}`,
                  prof.foreign_company_details.registration_number && `no. ${prof.foreign_company_details.registration_number}`].filter(Boolean).join(", ")}
                {prof.foreign_company_details.business_activity ? <div className="faint small">{prof.foreign_company_details.business_activity}</div> : null}
                {(data.ch?.fetched as any)?.uk_establishments?.length ? <div className="small">UK establishments: {((data.ch?.fetched as any).uk_establishments as any[]).map((u) => `${u.company_name ?? u.name} (${u.company_number})`).join(", ")}</div> : null}</dd></>}
              {prof.branch_company_details && <><dt>Branch of</dt><dd>{prof.branch_company_details.parent_company_name ?? "an overseas company"}
                {prof.branch_company_details.parent_company_number ? <> · <Link to={`/c/${prof.branch_company_details.parent_company_number}`}>{prof.branch_company_details.parent_company_number}</Link></> : null}
                {prof.branch_company_details.business_activity ? <div className="faint small">{prof.branch_company_details.business_activity}</div> : null}</dd></>}
              {(data.deals ?? []).length > 0 && <><dt>Deals</dt><dd><DealList deals={data.deals!} /></dd></>}
              <dt>Industry</dt><dd>{data.sics.length ? data.sics.map((x) => <div key={x.code}>{x.description} <span className="faint">· {x.code}</span></div>) : c.sic_codes.join(", ") || "—"}</dd>
              <dt>Registered office</dt><dd>{c.registered_address ?? "—"} <Flags address={c.address_flag} /></dd>
              {c.region && <><dt>Region</dt><dd>{c.region}</dd></>}
              {(data.enrichment?.ownership || (own && own.ownership_type !== "unknown")) && <><dt>Ownership</dt><dd>
                {data.enrichment?.ownership ? <>{OWNERSHIP[data.enrichment.ownership]} <span className="faint small">· from research</span></> : OWNERSHIP[own!.ownership_type]}</dd></>}
              {c.last_accounts_date && <><dt>Last accounts</dt><dd>Made up to {date(c.last_accounts_date)}
                {c.accounts_category ? <span className="faint"> · {accountsLabel(c.accounts_category)}</span> : null}</dd></>}
              {c.accounts_next_due && <><dt>Next accounts due</dt><dd className={overdue(c.accounts_next_due, c.status) ? "neg" : ""}>
                {date(c.accounts_next_due)}{overdue(c.accounts_next_due, c.status) ? " · overdue" : ""}</dd></>}
              {c.confirmation_next_due && <><dt>Confirmation statement due</dt><dd className={overdue(c.confirmation_next_due, c.status) ? "neg" : ""}>
                {date(c.confirmation_next_due)}{overdue(c.confirmation_next_due, c.status) ? " · overdue" : ""}</dd></>}
              {c.previous_names && c.previous_names.length > 0 && <><dt>Previous names</dt><dd>
                {c.previous_names.map((p, i) => <div key={i}>{p.name}{p.until ? <span className="faint"> · until {date(p.until)}</span> : null}</div>)}
              </dd></>}
              <dt>Updated</dt><dd className="muted">{relDays(c.updated_at)} · {c.source ?? "—"}</dd>
            </dl>
            {Object.keys(c.extra ?? {}).length > 0 && (
              <details className="small" style={{ marginTop: 8 }}>
                <summary className="faint">Fields from your imported file ({Object.keys(c.extra).length})</summary>
                <dl className="facts">{Object.entries(c.extra).map(([k, v]) => <FactRow key={k} k={k} v={v} />)}</dl>
              </details>
            )}
          </section>
          </div>
          <div className="pcol">
            <ActivitySection key={num} data={data} num={num} setState={setState} onChanged={reload} />
          </div>
        </div>
          <section id="financials">
            <Head icon="money" tone="green" title="Financials" aside={(() => { const n = fin.filter((f) => !f.period_inferred).length; return `${n} ${n === 1 ? "year" : "years"} filed`; })()} />
            <AccountsGap data={data} />
            <Financials data={data} />
            {est && est.basis !== "filed" && <p className="faint small" style={{ margin: "4px 0 0" }}>Revenue estimate: {range(est.revenue_low, est.revenue_high)} · {est.method}</p>}
          </section>
        <OwnersDirectors data={data} flags={<Flags flags={own?.flags} address={c.address_flag} />} />
        {data.links.length ? (
        <div className="pair eq">
          <div className="pcol">
          <section id="group">
            <Head icon="group" tone="blue" title="Group and connections" right={<Link to={`/connections/${c.company_number}`}>Connection map →</Link>} />
            {data.links.length ? (
              <>
              {(() => {
                const row = (l: (typeof data.links)[number], i: number) => (
                    <tr key={i}>
                      <td>
                        {l.in_list ? <Link to={`/c/${l.other}`}>{l.other_name ?? l.other}</Link> : <span>{l.other_name ?? l.other} <span className="faint small">· not in your list</span></span>}
                        <div className="sub">{l.other}</div>
                      </td>
                      <td>{l.kind === "owned_by" ? (l.direction === "parent" ? "Parent company" : "Subsidiary") : LINK_KIND[l.kind]}{l.via ? <div className="sub">{l.via}</div> : null}</td>
                      <td className={l.confidence === "confirmed" ? "pos" : l.confidence === "possible" ? "faint" : ""}>{cap(l.confidence)}</td>
                      <td className="muted small hide-sm">{l.evidence}</td>
                    </tr>
                );
                const table = (rows: typeof data.links, off = 0) => (
                  <table>
                    <thead><tr><th>Company</th><th>Link</th><th>Confidence</th><th className="hide-sm">Evidence</th></tr></thead>
                    <tbody>{rows.map((l, i) => row(l, i + off))}</tbody>
                  </table>);
                // Strongest links first; beyond five, the rest fold away so this card stays a similar height to Locations.
                return <>{table(data.links.slice(0, 5))}{data.links.length > 5 && <Fold label={`${data.links.length - 5} more connections`}>{table(data.links.slice(5), 5)}</Fold>}</>;
              })()}
              </>
            ) : <div className="faint">No links found in the data imported so far.</div>}
          </section>
          </div>
          <div className="pcol">
          <Location data={data} />
          </div>
        </div>
        ) : (
          <>
            <section id="group" className="oneline">
              <Head icon="group" tone="blue" title="Group and connections" aside="No links found in the data so far: no parent, subsidiaries or companies with the same owner." right={<Link to={`/connections/${c.company_number}`}>Connection map →</Link>} />
            </section>
            <Location data={data} />
          </>
        )}
          <div id="value">
          <Valuation data={data} num={num} onSaved={reload} />

          </div>
          <Compare num={num} />
        <div className="flow2">
          <section id="score">
            <Head icon="target" title="Why this score" right={<Link to={`/buy-box?id=${shownId}`}>Edit {shownName}</Link>} />
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
              <div className="sc-grid">
                {score.reasons.filter((r) => r.status !== "unscored").map((r) => {
                  const mark = ({ good: "✓", partial: "~", miss: "✕", unknown: "?", unscored: "–" } as Record<string, string>)[r.status];
                  const pct = r.max ? Math.round((100 * Number(r.points)) / Number(r.max)) : 0;
                  return (
                    <div key={r.key} className={`sc-r ${r.status}`} title={r.text}>
                      <span className={`reason-mark ${r.status === "unscored" ? "unknown" : r.status}`}>{mark}</span>
                      <span className="sc-l">{r.label}<span className="sc-t">{r.text}</span></span>
                      <span className="sc-p">{r.status === "unscored" ? <span className="faint">–</span> : <>{r.points}<span className="faint">/{r.max}</span></>}
                        {r.status !== "unscored" && <i style={{ width: `${pct}%` }} />}</span>
              </div>
                  );
                })}
                      {score.reasons.some((r) => r.status === "unscored") && (
                  <div className="sc-r unscored"><span className="reason-mark unknown">–</span>
                    <span className="sc-l">Your own scores<span className="sc-t">Not scored yet: {score.reasons.filter((r) => r.status === "unscored").map((r) => r.label).join(", ")}. <a href="#deal">Score them</a></span></span><span /></div>
                )}
              </div>
            ) : <div className="faint">Not scored yet.</div>}
          </section>
            <Charges data={data} num={num} onFetched={reload} />
            <Filings data={data} />
          <DealSection data={data} num={num} setState={setState} onScored={reload} />
        </div>
          <div id="research">
          <Enrichment key={JSON.stringify(data.enrichment)} data={data} num={num} onSaved={reload}
                      finder={<WebsiteFinder num={num} onSaved={reload} />} />
          </div>
          <section id="changes">
            <Head icon="clock" tone="grey" title="Change history" />
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
            ) : <div className="faint">No changes recorded yet.</div>}
          </section>
      </div>
      {/* Phones: the usual actions within thumb reach */}
      <div className="mbar" role="toolbar" aria-label="Company actions">
        <button className="btn primary" onClick={() => document.querySelector(".callbar")?.scrollIntoView({ behavior: "smooth", block: "center" })}>Decide</button>
        {data.enrichment?.website && <a className="btn" href={data.enrichment.website} target="_blank" rel="noreferrer">Website ↗</a>}
        {mNext && <Link className="btn" to={`/c/${mNext}${window.location.search}`}>Next →</Link>}
      </div>
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

function FactRow({ k, v }: { k: string; v: unknown }) {
  return <><dt className="small">{k.replace(/_/g, " ")}</dt><dd className="small">{String(v)}</dd></>;
}

/** Your call, in one row: rule out (with a reason), move on a stage, set the stage
    or rating; a note and the next action fold away. */
function CallBar({ data, num, setState, onNote }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>;
  onNote: (n: CompanyDetail["notes"][number]) => void;
}) {
  const s = data.state;
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const stages = meta.data?.stages ?? [];
  const idx = stages.findIndex((x) => x.value === s.status);
  const nextStage = stages[idx + 1] && !["passed", "rejected"].includes(stages[idx + 1].value) ? stages[idx + 1] : null;
  const [pop, setPop] = useState<null | "rejected" | "passed">(null);
  const [more, setMore] = useState(false);
  const [note, setNote] = useState("");
  const [next, setNext] = useState(s.next_action ?? "");
  const [nextOn, setNextOn] = useState(s.next_action_on ?? "");
  const [advance, setAdvance] = useState(() => { try { return localStorage.getItem("ao.ruleout.next") !== "0"; } catch { return true; } });
  const popRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pop) return;
    const close = (e: MouseEvent) => { if (popRef.current && !popRef.current.contains(e.target as Node)) setPop(null); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setPop(null); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [pop]);
  const listNext = nextInList(num);
  const withNote = (t: string) => (note.trim() ? `${t}. ${note.trim()}` : t);
  const ruleOut = async (p: RuleOutPick) => {
    setPop(null);
    await setState({ ...p, stage_note: withNote(p.stage_note) });
    setNote("");
    if (advance && listNext) {
      try { sessionStorage.setItem("ao.undo", JSON.stringify({ num, name: data.company.name, prev: s.status, note: p.stage_note })); } catch { /* ignore */ }
      nav(`/c/${listNext}${window.location.search}`);
    }
  };
  const move = async (to: string) => { await setState({ status: to, stage_note: withNote("Changed on the company page") }); setNote(""); };
  const saveNote = async () => {
    if (!note.trim()) return;
    onNote(await api.addNote(num, note.trim())); setNote("");
  };
  const closed = s.status === "rejected" || s.status === "passed";
  return (
    <section className="callbar">
      <div className="cb-row">
        <b className="cb-title">Your call</b>
        {closed ? (
          <span className="small">{s.status === "rejected" ? "✕ Ruled out" : "Not now"}: hidden from targets.{" "}
            <button className="linkish small" onClick={() => move("watching")}>Bring back</button>
            {listNext && <> · <Link to={`/c/${listNext}`}>Next in list →</Link></>}</span>
        ) : (
          <div className="cb-pops" ref={popRef}>
            <button className={`btn cb-x ${pop === "rejected" ? "on" : ""}`} onClick={() => setPop(pop === "rejected" ? null : "rejected")} aria-expanded={pop === "rejected"}>✕ Not suitable</button>
            <button className={`btn ${pop === "passed" ? "on" : ""}`} onClick={() => setPop(pop === "passed" ? null : "passed")} aria-expanded={pop === "passed"}>Not now</button>
            {pop && (
              <div className="cb-pop">
                <div className="label" style={{ marginBottom: 6 }}>{pop === "rejected" ? "Not suitable because…" : "Not now because…"}</div>
                <RuleOutChips onPick={ruleOut} compact only={pop} />
                {listNext && (
                  <label className="faint small" style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 8 }}>
                    <input type="checkbox" checked={advance} onChange={(e) => { setAdvance(e.target.checked); try { localStorage.setItem("ao.ruleout.next", e.target.checked ? "1" : "0"); } catch { /* ignore */ } }} />
                    Then open the next company in the list
                  </label>
                )}
              </div>
            )}
          </div>
        )}
        {nextStage && !closed && <button className="btn primary" onClick={() => move(nextStage.value)}>Move to {nextStage.label} →</button>}
        {listNext && !closed && <Link className="btn" to={`/c/${listNext}${window.location.search}`} title="Next company in the list you came from">Next in list →</Link>}
        <div className="cb-stage"><StageSelect value={s.status} onChange={(v) => move(v)} /></div>
        <div className="rating small" title="Rating (keys 1–5)">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className={s.rating === n ? "on" : ""} onClick={() => setState(s.rating === n ? { clear_rating: true } : { rating: n })}>{n}</button>
          ))}
        </div>
        <button className={`btn quiet ${more ? "on" : ""}`} onClick={() => setMore(!more)} aria-expanded={more}>
          {more ? "− Note" : "+ Note"}{s.next_action ? " · next action" : ""}</button>
        {s.next_action && !more && <span className="faint small cb-nextsum">Next: {s.next_action}{s.next_action_on ? ` · ${date(s.next_action_on)}` : ""}</span>}
      </div>
      {more && (
        <div className="cb-more">
          <input type="text" value={note} placeholder="A quick note: saved to notes, and kept with any stage change you make next"
                 onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") saveNote(); }} />
          <button className="btn" disabled={!note.trim()} onClick={saveNote}>Save note</button>
          <input type="text" value={next} placeholder="Next action, e.g. send approach letter" aria-label="Next action"
                 onChange={(e) => setNext(e.target.value)} onBlur={() => next !== (s.next_action ?? "") && setState({ next_action: next || null })} />
          <input type="date" value={nextOn ?? ""} aria-label="Next action date" onChange={(e) => { setNextOn(e.target.value); setState({ next_action_on: e.target.value || null }); }} />
        </div>
      )}
    </section>
  );
}



/** Notes, contacts and stage moves in one timeline, newest first, with one box to add a note or log a contact. */
function ActivitySection({ data, num, setState, onChanged }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>; onChanged: () => void;
}) {
  const meta = useAsync(() => api.meta(), []);
  const [mode, setMode] = useState<"note" | "contact">("note");
  const [note, setNote] = useState("");
  const owner = data.ownership?.ultimate_owners?.find((u) => !u.unresolved && u.kind !== "corporate")?.name ?? "";
  const today = new Date().toISOString().slice(0, 10);
  const [ct, setCt] = useState({ contact_name: owner, contact_role: "owner", channel: "letter", summary: "", happened_on: today, follow_up_on: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stageLabel = (v: string) => meta.data?.statuses.find((x) => x.value === v)?.label ?? v;
  const items = [
    ...data.notes.map((n) => ({ at: n.created_at, kind: "note" as const, key: `n${n.id}`, body: <>{n.body}{n.source !== "app" ? <span className="faint small"> · {n.source.replace("import:", "from ")}</span> : null}</> })),
    ...data.outreach.map((o) => ({ at: o.happened_on, kind: "contact" as const, key: `o${o.id}`,
      body: <><b>{cap(o.channel ?? "contact")}</b> {o.contact_role === "owner" ? "with" : `with ${o.contact_role}`} {o.contact_name}{o.summary ? `: ${o.summary}` : ""}</> })),
    ...data.deal.history.map((h, i) => ({ at: h.created_at, kind: "stage" as const, key: `h${i}`,
      body: <>Moved to <b>{stageLabel(h.to_status)}</b>{h.note ? <span className="faint"> · {h.note}</span> : null}</> })),
  ].sort((a, b) => String(b.at).localeCompare(String(a.at)));
  const addNote = async () => {
    if (!note.trim()) return;
    setBusy(true); setErr(null);
    try { await api.addNote(num, note.trim()); setNote(""); onChanged(); } catch (e: any) { setErr(`Not saved: ${e.message}`); }
    setBusy(false);
  };
  const logContact = async () => {
    setBusy(true); setErr(null);
    const { follow_up_on, ...c } = ct;
    try {
      await api.addOutreach({ ...c, contact_name: c.contact_name.trim() || "Owner", company_number: num,
                              next_action: follow_up_on ? `Follow up: ${c.summary || c.channel}` : null, next_action_on: follow_up_on || null });
      if (follow_up_on) await setState({ next_action: `Follow up: ${c.summary || c.channel}`, next_action_on: follow_up_on });
      setCt({ ...ct, summary: "", follow_up_on: "" }); onChanged();
    } catch (e: any) { setErr(`Not saved: ${e.message}`); }
    setBusy(false);
  };
  const icon = { note: "✎", contact: "✉", stage: "→" };
  const row = (it: (typeof items)[number]) => (
    <li key={it.key} className={`act-${it.kind}`}>
      <span className="act-d">{date(it.at)}</span><span className="act-i">{icon[it.kind]}</span><span>{it.body}</span>
    </li>);
  return (
    <section id="activity">
      <div className="sechead">
        <h2 className="withico">Your activity</h2>
        <span className="right seg2"><button className={mode === "note" ? "on" : ""} onClick={() => setMode("note")}>Note</button><button className={mode === "contact" ? "on" : ""} onClick={() => setMode("contact")}>Contact</button></span>
      </div>
      {mode === "note" ? (
        <div className="act-in">
          <input type="text" value={note} placeholder="Add a note… (Enter to save; never overwritten by a data refresh)" onChange={(e) => setNote(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") addNote(); }} />
          <button className="btn primary" disabled={!note.trim() || busy} onClick={addNote}>Save</button>
        </div>
      ) : (
        <div className="act-ct">
          <input type="text" placeholder="Who (blank: the owner)" value={ct.contact_name} onChange={(e) => setCt({ ...ct, contact_name: e.target.value })} />
          <select value={ct.channel} onChange={(e) => setCt({ ...ct, channel: e.target.value })}>
            <option value="letter">Letter</option><option value="email">Email</option><option value="call">Call</option><option value="linkedin">LinkedIn</option><option value="meeting">Meeting</option>
          </select>
          <select value={ct.contact_role} onChange={(e) => setCt({ ...ct, contact_role: e.target.value })}>
            <option value="owner">Owner</option><option value="adviser">Adviser</option><option value="broker">Broker</option><option value="investor">Investor</option><option value="other">Other</option>
          </select>
          <input type="text" className="wide" placeholder="What happened" value={ct.summary} onChange={(e) => setCt({ ...ct, summary: e.target.value })} />
          <label className="field"><span className="label">When</span><input type="date" value={ct.happened_on} onChange={(e) => setCt({ ...ct, happened_on: e.target.value })} /></label>
          <label className="field"><span className="label">Follow up on</span><input type="date" value={ct.follow_up_on} onChange={(e) => setCt({ ...ct, follow_up_on: e.target.value })} /></label>
          <button className="btn primary" disabled={busy} onClick={logContact}>Log contact</button>
        </div>
      )}
      {err && <div className="neg small" style={{ marginTop: 6 }}>{err}</div>}
      {items.length ? (
        <>
          <ul className="act">{items.slice(0, 5).map(row)}</ul>
          {items.length > 5 && <Fold label={`${items.length - 5} older ${items.length - 5 === 1 ? "entry" : "entries"}`}><ul className="act">{items.slice(5).map(row)}</ul></Fold>}
        </>
      ) : <div className="faint" style={{ marginTop: 8 }}>Nothing yet.</div>}
    </section>
  );
}

/** Where this company sits among similar companies in your data. */
function Compare({ num }: { num: string }) {
  const q = useAsync(() => api.compare(num), [num]);
  const d = q.data;
  if (!d || !d.group) return null;
  const shown = d.metrics.filter((m) => m.value !== null);
  if (!shown.length) return null;
  const f = (m: (typeof shown)[number], v: number) => (m.fmt === "money" ? money(v) : `${v > 0 && m.key === "growth" ? "+" : ""}${v.toFixed(1)}%`);
  const where = (p: number) => (p >= 75 ? `top ${100 - p}%` : p <= 25 ? `bottom ${Math.max(1, p)}%` : p >= 50 ? "above the middle" : "below the middle");
  return (
    <section id="compare">
      <Head icon="target" tone="grey" title="How it compares" aside={`vs ${int(d.peers)} companies in ${d.group}, filed figures`} />
      <div className="cmp">
        {shown.map((m) => (
          <div key={m.key} className="cmp-row">
            <div className="cmp-l">{m.label}</div>
            <div className="cmp-track">
              {m.pct !== null ? <>
                <i className="cmp-med" title={`Median ${f(m, m.median!)}`} />
                <b className="cmp-dot" style={{ left: `${Math.min(98, Math.max(2, m.pct))}%` }} title={`${f(m, m.value!)}: higher than ${m.pct}% of ${int(m.n)}`} />
              </> : <span className="faint small" style={{ paddingLeft: 8 }}>Too few similar companies with this figure to compare</span>}
            </div>
            <div className="cmp-v"><b>{f(m, m.value!)}</b>{m.pct !== null && <span className="faint"> · {where(m.pct)}</span>}</div>
          </div>
        ))}
        <div className="cmp-row cmp-axis"><div /><div className="cmp-track bare"><span>lowest</span><span>median</span><span>highest</span></div><div /></div>
      </div>
    </section>
  );
}

function DealSection({ data, num, setState, onScored }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>; onScored: () => void;
}) {
  return (
    <section id="deal">
      <Head icon="target" tone="grey" title="Deal checklist and your scores" />
      <DealProgress data={data} num={num} setState={setState} />
      <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>Your scores</h3>
      <MyScores num={num} criteria={data.manual.criteria} values={data.manual.values} onChange={() => onScored()} />
    </section>
  );
}



function StageSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const meta = useAsync(() => api.meta(), []);
  const phases = meta.data?.phases ?? [];
  const stages = meta.data?.statuses ?? [];
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{ width: "100%" }} aria-label="Stage">
      {phases.length ? phases.map((ph) => (
        <optgroup key={ph.value} label={ph.label}>
          {stages.filter((x) => x.phase === ph.value).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
        </optgroup>
      )) : stages.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
      {stages.filter((x) => !phases.some((ph) => ph.value === x.phase)).map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
    </select>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
const hostOf = (u: string) => { try { const h = new URL(u).hostname.replace(/^www\./, ""); return /company-information\.service\.gov\.uk$/.test(h) ? "Companies House" : h; } catch { return u; } };


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


/** A few short sentences about the company, from the facts on file. */
function overviewSentence(d: CompanyDetail): string {
  const c = d.company;
  const latest = [...d.financials].reverse().find((f) => !f.period_inferred);
  const town = (c.registered_address ?? "").split(",").map((x) => x.trim()).filter((x) => x && !/\d/.test(x)).slice(-1)[0];
  const out: string[] = [];
  out.push(`${companyType(c.company_type).replace(/^—$/, "Company")}${town ? ` in ${town}` : ""}${c.incorporation_date ? `, founded ${c.incorporation_date.slice(0, 4)}` : ""}.`);
  if (d.sics.length) out.push(d.sics.map((x) => x.description).join("; ") + ".");
  if (latest) {
    const bits = [latest.employees != null ? `${latest.employees.toLocaleString("en-GB")} staff` : null,
                  latest.turnover ? `${money(latest.turnover)} turnover` : null,
                  latest.net_assets != null ? `${money(latest.net_assets)} net assets` : null].filter(Boolean);
    if (bits.length) out.push(`${bits.join(", ")} (year to ${date(latest.period_end)}).`);
  }
  if (d.ownership && d.ownership.ownership_type !== "unknown") {
    out.push(`${OWNERSHIP[d.ownership.ownership_type] ?? d.ownership.ownership_type}` +
      (d.ownership.oldest_birth_year ? `; oldest owner about ${new Date().getFullYear() - d.ownership.oldest_birth_year}` : "") + ".");
  }
  if (c.charges_outstanding) out.push(`${c.charges_outstanding} outstanding charge${c.charges_outstanding === 1 ? "" : "s"}.`);
  return out.join(" ");
}

const COMPANY_TYPES: Record<string, string> = {
  ltd: "Private limited company", "private limited company": "Private limited company", plc: "Public limited company",
  llp: "Limited liability partnership", "private-unlimited": "Private unlimited company",
  "private limited guarant nsc": "Private company limited by guarantee", "community interest company": "Community interest company",
};
function companyType(t: string | null): string {
  if (!t) return "—";
  return COMPANY_TYPES[t.toLowerCase()] ?? t;
}


const DEAL_ICON: Record<string, string> = { sold: "→", acquired: "＋", formed: "＋", merged: "⇄", investment: "£", eot: "♦", mbo: "→", mbi: "→",
  disposal: "−", listing: "▲", delisting: "▼", refinancing: "£", buyback: "↺", renamed: "✎", owner: "→", other: "•" };

/** Sales, purchases, mergers and other corporate events, newest first; five, then the rest on request. */
function DealList({ deals }: { deals: NonNullable<CompanyDetail["deals"]> }) {
  const [all, setAll] = useState(false);
  const shown = all ? deals : deals.slice(0, 5);
  const when = (d: (typeof deals)[number]) => d.date_text && d.date_text.length < 10 ? d.date_text : d.date ? date(d.date) : "date unknown";
  return (
    <ul className="ov-deals">
      {shown.map((d, i) => (
        <li key={i} className={d.kind}>
          <span className="ic" aria-hidden>{DEAL_ICON[d.kind] ?? "•"}</span>
          <span><span className="faint small">{when(d)}</span> · {d.counterparty_number && d.title.includes(d.counterparty ?? "\u0000")
              ? <>{d.title.replace(d.counterparty!, "")}<Link to={`/c/${d.counterparty_number}`}>{d.counterparty}</Link></> : d.title}
            {d.detail ? <span className="faint"> · {d.detail}</span> : null}
            <span className="faint small"> · {d.source_url ? <a href={d.source_url} target="_blank" rel="noreferrer">{d.source === "research" ? hostOf(d.source_url) : d.source} ↗</a> : d.source}
              {d.research_url ? <> · <a href={d.research_url} target="_blank" rel="noreferrer" title={d.research_title ?? undefined}>{hostOf(d.research_url)} ↗</a></> : null}</span></span>
        </li>
      ))}
      {deals.length > 5 && <li className="more"><button className="linkish small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `+${deals.length - 5} more`}</button></li>}
    </ul>
  );
}


/** Companies that look related (same owner and address, or a director in
    common at the same postcode), for information. */
function SameBusiness({ data }: { data: CompanyDetail }) {
  const [all, setAll] = useState(false);
  const others = [...(data.same_business ?? [])].sort((a, b) =>
    (Number(b.revenue_high ?? 0) - Number(a.revenue_high ?? 0)) || ((b.employees ?? -1) - (a.employees ?? -1)) || a.name.localeCompare(b.name));
  if (!others.length) return null;
  const shown = all ? others : others.slice(0, 5);
  const size = (o: (typeof others)[number]) => [o.employees ? `${o.employees} staff` : null, o.revenue_low ? range(o.revenue_low, o.revenue_high) : null].filter(Boolean).join(", ");
  return (
    <div className="callout">
      <b>Linked to {others.length} {others.length === 1 ? "company" : "companies"}:</b>{" "}
      {shown.map((o, i) => (
        <span key={o.company_number}>{i ? "; " : ""}<Link to={`/c/${o.company_number}`}>{o.name}</Link>
          {size(o) ? <span className="faint"> ({size(o)})</span> : null}</span>
      ))}
      {others.length > 5 && <> <button className="linkish small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `+${others.length - 5} more`}</button></>}
      <Hint text="Same owner and address, or a director in common at the same postcode. Largest first." />
    </div>
  );
}


/** After ruling one out and moving on: one line with Undo, replaced by the
    next one and gone after a few seconds. */
function UndoBar({ num }: { num: string }) {
  const [u, setU] = useState<{ num: string; name: string; prev: string; note: string } | null>(null);
  useEffect(() => {
    let v = null;
    try { v = JSON.parse(sessionStorage.getItem("ao.undo") ?? "null"); sessionStorage.removeItem("ao.undo"); } catch { /* ignore */ }
    setU(v);
    if (!v) return;
    const t = setTimeout(() => setU(null), 8000);
    return () => clearTimeout(t);
  }, [num]);
  if (!u) return null;
  return (
    <div className="undo-toast" role="status">
      <span><b>{u.name}</b> · {u.note}</span>
      <button className="linkish" onClick={async () => { await api.setState(u.num, { status: u.prev, stage_note: "Undone" }); setU(null); }}>Undo</button>
      <button className="linkish faint" aria-label="Dismiss" onClick={() => setU(null)}>×</button>
    </div>
  );
}


/** Accounts Companies House has that we have no figures for: being fetched,
    or filed only as PDF (Claude can read those and save the figures). */
function AccountsGap({ data }: { data: CompanyDetail }) {
  const c = data.company;
  const pdf = [...new Set([...(((data.ch?.fetched as any)?.accounts_pdf ?? []) as string[]), ...(data.pdf_waiting ?? []),
    ...(data.pdf_reads ?? []).map((r) => String(r.made_up).slice(0, 10))].map((d) => String(d).slice(0, 10)))].sort().reverse();
  const latest = [...data.financials].reverse().find((f) => !f.period_inferred)?.period_end;
  const behind = c.last_accounts_date && (!latest || new Date(c.last_accounts_date).getTime() - new Date(latest).getTime() > 45 * 864e5);
  const url = `https://find-and-update.company-information.service.gov.uk/company/${c.company_number}/filing-history`;
  if (pdf.length) {
    // Read automatically in the background (text layer, or OCR for scans), newest first.
    const reads = new Map((data.pdf_reads ?? []).map((r) => [String(r.made_up).slice(0, 10), r]));
    const st = pdf.map((d) => ({ d, r: reads.get(String(d).slice(0, 10)) }));
    const waiting = st.filter((x) => !x.r);
    const read = st.filter((x) => x.r?.status === "done");
    const failed = st.filter((x) => x.r && x.r.status !== "done");
    return (
      <div className={`callout ${failed.length ? "amber" : ""}`} style={{ marginBottom: 10 }}>
        Accounts to {pdf.map((d) => date(d)).join(", ")} weren't in the bulk data.{" "}
        {read.length > 0 && <>{read.map((x) => date(x.d)).join(", ")}: <b>{read.every((x) => x.r?.method === "data") ? "read from Companies House" : `read from the PDF${read.some((x) => x.r?.method === "ocr") ? " (some by OCR)" : ""}`}</b>{read.some((x) => x.r?.method !== "data") ? ", worth checking against the filing" : ""}. </>}
        {waiting.length > 0 && <>{waiting.map((x) => date(x.d)).join(", ")}: waiting to be read automatically (↻ Refresh reads them now). </>}
        {failed.length > 0 && <>{failed.map((x) => `${date(x.d)}${x.r?.note ? ` (${x.r.note})` : ""}`).join(", ")}: <b>couldn't be read</b>.
          Ask Claude: <i>“Read the accounts PDFs for {c.name} in AcquireOS and save the figures.”</i> </>}
        <a href={url} target="_blank" rel="noreferrer">Filings ↗</a>
      </div>
    );
  }
  if (behind) {
    return (
      <div className="callout" style={{ marginBottom: 10 }}>
        Companies House has accounts to <b>{date(c.last_accounts_date)}</b>{latest ? `, but figures here stop at ${date(latest)}` : ""}.{" "}
        {data.ch?.enabled ? "They're read from Companies House when the company is next checked (opening this page does it)." : "Add your Companies House API key to read them."}{" "}
        <a href={url} target="_blank" rel="noreferrer">Filings ↗</a>
      </div>
    );
  }
  return null;
}

/** The town from a registered address: the part just before the postcode. */
function townOf(addr: string | null, pc: string | null) {
  if (!addr) return null;
  const parts = addr.replace(pc ?? "", "").split(",").map((x) => x.trim()).filter(Boolean);
  const t = parts[parts.length - 1];
  return t && !/\d/.test(t) && t.length < 30 ? t.toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase()) : null;
}
