import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { ErrorLine, Flags, RevenueTag, Score, Signals, Toast, useAsync, WatchButton } from "../components/bits";
import { AreaChart as SmallLine } from "../components/charts";
import Valuation from "../components/Valuation";
import DealProgress from "../components/DealProgress";
import MyScores from "../components/MyScores";
import { listFrom, nextInList, RuleOutChips, type RuleOutPick } from "../components/RuleOut";
import { Enrichment, Location } from "../components/CompanyExtras";
import { Charges, Filings, FinancialOverview, Head, OwnersDirectors, WebsiteFinder } from "../components/Profile";
import { ageFrom, CHANGE_KIND, chUrl, date, dateTime, describeChange, int, isBadStatus, LINK_KIND, money, OWNERSHIP, range, relDays, toNum, years } from "../format";


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
    const ids = ["overview", "ownership", "notes", "financials", "value", "charges", "filings", "group", "score", "research", "deal", "changes"];
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
  // Turnover with the missing years estimated from the company's own revenue per head (dashed).
  const turnoverPoints = (data.fin_summary?.series ?? []).map((r: any) => ({
    x: r.period_end, y: r.turnover ?? r.turnover_est ?? null, estimated: r.turnover == null && r.turnover_est != null,
    note: r.turnover_est_from ? `staff × revenue per head from the ${String(r.turnover_est_from).slice(0, 4)} accounts` : undefined,
  }));
  const estByEnd = new Map((data.fin_summary?.series ?? []).filter((r: any) => r.turnover == null && r.turnover_est != null)
    .map((r: any) => [String(r.period_end).slice(0, 10), r.turnover_est as number]));
  const series = (k: keyof (typeof fin)[number]) =>
    fin.map((f) => ({ x: f.period_end, y: toNum(f[k] as string | number | null), inferred: f.period_inferred }));

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

  return (
    <>
      <UndoBar key={num} />
      <div className="pagehead">
        <div>
          <div className="crumb">
            <a href="/companies" onClick={(e) => { if (window.history.length > 1) { e.preventDefault(); nav(-1); } }}>← Back</a> / {c.company_number}
            {chCheck && <span className="chcheck"> · {chCheck}</span>}
          </div>
          <h1 className="coname">{c.name}</h1>
          <div className="chips">
            <span className={`chip ${isBadStatus(c.status) ? "red" : "green"}`}>{c.status ? cap(c.status) : "Status unknown"}{c.dissolution_date ? ` ${date(c.dissolution_date)}` : ""}</span>
            <span className="chip">No. {c.company_number}</span>
            {c.incorporation_date && <span className="chip">Since {c.incorporation_date.slice(0, 4)} · {years(c.incorporation_date)} yrs</span>}
            {c.region && <span className="chip">{c.postcode ? `${c.postcode.split(" ")[0]} · ` : ""}{c.region}</span>}
            {c.accounts_category && <span className="chip" title={`Accounts filed: ${accountsLabel(c.accounts_category)}`}>{accountsChip(c.accounts_category)}</span>}
            {data.enrichment?.ownership ? <span className="chip teal" title={data.enrichment.ownership_note ?? "From research"}>{OWNERSHIP[data.enrichment.ownership]} · research</span>
              : own && own.ownership_type !== "unknown" && <span className="chip teal">{OWNERSHIP[own.ownership_type]}</span>}
            <Signals s={data.signals} region={c.region} />
            {data.sold?.sold_to && <span className="chip" title="From the owners register or your research">Sold{data.sold.sold_on ? ` ${date(data.sold.sold_on)}` : ""} to {data.sold.sold_to}</span>}
            {data.enrichment?.website && <a className="chip link" href={data.enrichment.website} target="_blank" rel="noreferrer">{data.enrichment.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗</a>}
          </div>
        </div>
        <div className="right">
          {data.ch?.enabled && <button className="btn quiet" onClick={refresh} title="Fetch everything from Companies House now, and read any accounts filed only as PDF">↻ Refresh</button>}
          <WatchButton kind="company" refId={c.company_number} on={!!data.watching} label={c.name} onChange={reload} />
          <a className="btn quiet" href={chUrl(c.company_number)} target="_blank" rel="noreferrer">Companies House ↗</a>
          <Link className="btn" to={`/connections/${c.company_number}`}>Connection map</Link>
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
          <b>{est ? range(est.revenue_low, est.revenue_high) : "—"}</b>
          <span className="s">{est ? <RevenueTag basis={est.basis} method={est.method} long /> : "Not filed or estimated"}</span>
        </div>
        <div className={`cokpi ${profit && profit.v < 0 ? "bad" : ""}`}>
          <span className="k">{profit?.ebitda ? "EBITDA" : "Operating profit"}</span>
          <b>{profit ? money(profit.v) : "—"}</b>
          <span className="s">{profit ? `Filed · ${date(profit.at)}${profit.ebitda ? " · incl. depreciation" : ""}` : "Not in the filed accounts"}</span>
        </div>
        <div className="cokpi">
          <span className="k">Indicative value</span>
          <b>{val?.value_low ? range(val.value_low, val.value_high) : "—"}</b>
          <span className="s">{val?.value_low ? (val.basis === "filed" ? "From filed profit" : val.basis === "filed_margin" ? "From its own margin" : "From estimates") : val?.basis === "loss" ? "Loss-making: no earnings value" : "Not enough figures"}</span>
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
            {[["overview", "Overview"], ["ownership", "Owners & directors"], ["notes", "Notes"], ["financials", "Financials"],
              ["value", "Value"], ["charges", "Charges"], ["filings", "Filings"], ["group", "Group"], ["score", "Score"],
              ["research", "Research"], ["deal", "Deal"], ["changes", "History"]].map(([id, l]) => (
              <a key={id} href={`#${id}`} className={inView === id ? "on" : ""} onClick={(e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{l}</a>
            ))}
          </nav>
        <div className="flow2">
          <section id="overview">
            <Head icon="overview" title="Overview" />
            <p className="summary">{overviewSentence(data)}</p>
            <dl className="facts">
              <dt>Type</dt><dd>{companyType(c.company_type)}{prof.is_community_interest_company ? " · community interest company" : ""}</dd>
              {activity && <><dt>What it does</dt><dd>{activity.principal_activity}<span className="faint small"> · its own words, {date(activity.period_end)} accounts</span></dd></>}
              {yearEnd && <><dt>Year end</dt><dd>{yearEnd}{prof.accounts?.last_accounts?.type ? <span className="faint"> · last filed as {String(prof.accounts.last_accounts.type).replace(/-/g, " ")}</span> : null}</dd></>}
              {prof.foreign_company_details && <><dt>Overseas company</dt><dd>
                {[prof.foreign_company_details.legal_form, prof.foreign_company_details.originating_registry?.country && `registered in ${prof.foreign_company_details.originating_registry.country}`,
                  prof.foreign_company_details.registration_number && `no. ${prof.foreign_company_details.registration_number}`].filter(Boolean).join(", ")}
                {prof.foreign_company_details.business_activity ? <div className="faint small">{prof.foreign_company_details.business_activity}</div> : null}
                {(data.ch?.fetched as any)?.uk_establishments?.length ? <div className="small">UK establishments: {((data.ch?.fetched as any).uk_establishments as any[]).map((u) => `${u.company_name ?? u.name} (${u.company_number})`).join(", ")}</div> : null}</dd></>}
              {prof.branch_company_details && <><dt>Branch of</dt><dd>{prof.branch_company_details.parent_company_name ?? "an overseas company"}
                {prof.branch_company_details.parent_company_number ? <> · <Link to={`/c/${prof.branch_company_details.parent_company_number}`}>{prof.branch_company_details.parent_company_number}</Link></> : null}
                {prof.branch_company_details.business_activity ? <div className="faint small">{prof.branch_company_details.business_activity}</div> : null}</dd></>}
              <dt>Industry</dt><dd>{data.sics.length ? data.sics.map((x) => <div key={x.code}>{x.description} <span className="faint">· {x.code}</span></div>) : c.sic_codes.join(", ") || "—"}</dd>
              {data.enrichment?.website && <><dt>Website</dt><dd><a href={data.enrichment.website} target="_blank" rel="noreferrer">{data.enrichment.website.replace(/^https?:\/\/(www\.)?/, "")} ↗</a></dd></>}
              <dt>Registered office</dt><dd>{c.registered_address ?? "—"} <Flags address={c.address_flag} /></dd>
              {c.review_tier && <><dt>Review tier</dt><dd>{c.review_tier}</dd></>}
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
            <OwnersDirectors data={data} flags={<Flags flags={own?.flags} address={c.address_flag} />} />
            <NotesSection data={data} num={num} onNote={(n) => setData({ ...data, notes: [n, ...data.notes] })} />
            <OutreachSection key={num} data={data} num={num} setState={setState} onOutreach={reload} />
        </div>
          <section id="financials">
            <Head icon="money" tone="green" title="Financials" aside={(() => { const n = fin.filter((f) => !f.period_inferred).length; return `${n} ${n === 1 ? "year" : "years"} filed`; })()} />
            <AccountsGap data={data} />
            {fin.length ? (
              <>
                {data.fin_summary && <FinancialOverview s={data.fin_summary} />}
                <div className="multiples" style={{ marginTop: 14 }}>
                  <SmallLine title="Staff" points={series("employees")} format={(n) => int(n)} />
                  <SmallLine title="Net assets" points={series("net_assets")} format={(n) => money(n)} />
                  <SmallLine title="Cash" points={series("cash")} format={(n) => money(n)} />
                  <SmallLine title="Debtors" points={series("debtors")} format={(n) => money(n)} />
                  {fin.some((f) => f.turnover) && <SmallLine title="Turnover" points={turnoverPoints} format={(n) => money(n)} />}
                  {fin.some((f) => f.profit_loss) && <SmallLine title="Profit" points={series("profit_loss")} format={(n) => money(n)} />}
                </div>
                <details style={{ marginTop: 12 }}>
                <summary className="muted" style={{ cursor: "pointer" }}>All figures by year</summary>
                <table style={{ marginTop: 10 }}>
                  <thead><tr><th>Period end</th><th className="num">Staff</th><th className="num">Turnover</th><th className="num hide-sm">Operating profit</th><th className="num">Profit after tax</th><th className="num">Net assets</th><th className="num">Cash</th><th className="num hide-sm">Debtors</th><th className="num hide-sm">Dividends</th></tr></thead>
                  <tbody>
                    {[...fin].reverse().map((f) => (
                      <tr key={f.period_end}>
                        <td>{date(f.period_end)}{f.period_inferred && <span className="faint small"> · date inferred</span>}
                          {f.source?.startsWith("pdf:") && <span className="tag amber small" style={{ marginLeft: 6 }}
                            title="Read automatically from the PDF filing: check against the filing">{f.source === "pdf:ocr" ? "read by OCR" : "from PDF"}</span>}</td>
                        <td className="num">{int(f.employees)}</td>
                        <td className="num">{f.turnover != null ? money(f.turnover, { precise: true })
                          : estByEnd.has(String(f.period_end).slice(0, 10)) ? <span className="estval" title="Estimate: staff × the company's own revenue per head">≈{money(estByEnd.get(String(f.period_end).slice(0, 10))!)} est.</span> : "—"}</td>
                        <td className={`num hide-sm ${Number(f.operating_profit) < 0 ? "neg" : ""}`}>{money(f.operating_profit, { precise: true })}</td>
                        <td className={`num ${Number(f.profit_loss) < 0 ? "neg" : ""}`}>{money(f.profit_loss, { precise: true })}</td>
                        <td className={`num ${Number(f.net_assets) < 0 ? "neg" : ""}`}>{money(f.net_assets, { precise: true })}</td>
                        <td className="num">{money(f.cash, { precise: true })}</td>
                        <td className="num hide-sm">{money(f.debtors, { precise: true })}</td>
                        <td className="num hide-sm">{money(f.dividends, { precise: true })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {est && <p className="muted small">Revenue: {range(est.revenue_low, est.revenue_high)}. Method: {est.method}.</p>}
                </details>
                <details style={{ marginTop: 8 }} open>
                <summary className="muted" style={{ cursor: "pointer" }}>Profit, debt and working capital</summary>
                <BalanceSheet fin={fin} />
                </details>
              </>
            ) : <div className="faint">No accounts imported.</div>}
          </section>
          <div id="value">
          <Valuation data={data} num={num} onSaved={reload} />

          </div>
          <div id="research">
          <Enrichment key={JSON.stringify(data.enrichment)} data={data} num={num} onSaved={reload}
                      finder={<WebsiteFinder num={num} onSaved={reload} />} />
          </div>
        <div className="flow2">
            <Charges data={data} num={num} onFetched={reload} />
            <Filings data={data} />
          <section id="group">
            <Head icon="group" tone="blue" title="Group and connections" right={<Link to={`/connections/${c.company_number}`}>Open map</Link>} />
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
              <table className="reasons">
                <tbody>
                  {score.reasons.map((r) => (
                    <tr key={r.key}>
                      <td style={{ width: 150 }}>
                        <span className={`reason-mark ${r.status === "unscored" ? "unknown" : r.status}`}>{({ good: "✓", partial: "~", miss: "✕", unknown: "?", unscored: "–" } as Record<string, string>)[r.status]}</span>
                        {r.label}
                      </td>
                      <td className={r.status === "unknown" ? "faint" : ""}>{r.text}</td>
                      <td className="num pts">{r.status === "unknown" ? <span className="faint" title="No data: half points, neither a hit nor a miss">no data · {r.points} / {r.max}</span> : r.status === "unscored" ? <span className="faint">not counted</span> : `${r.points} / ${r.max}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="faint">Not scored yet.</div>}
          </section>
          <Research data={data} num={num} onAdded={reload} />
          <Location data={data} />
          <DealSection data={data} num={num} setState={setState} onScored={reload} />
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
            ) : <div className="faint">No changes recorded yet. Changes show up after each monthly Companies House refresh.</div>}
          </section>
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

function NotesSection({ data, num, onNote }: { data: CompanyDetail; num: string; onNote: (n: CompanyDetail["notes"][number]) => void }) {
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
  return (
    <section id="notes">
      <Head icon="file" tone="grey" title="Notes" aside="Never overwritten by a data refresh" />
      <textarea rows={2} value={note} placeholder="What do you think? Ctrl+Enter to save." onChange={(e) => setNote(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && note.trim()) addNote(); }} />
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
        {noteErr && <span className="neg small" style={{ marginRight: 8, alignSelf: "center" }}>{noteErr}</span>}
        <button className="btn primary" disabled={!note.trim() || saving} onClick={addNote}>Add note</button>
      </div>
      <ul className="notes">
        {data.notes.map((n) => (
          <li key={n.id}>
            <div className="meta">{dateTime(n.created_at)}{n.source !== "app" ? ` · ${n.source.replace("import:", "from ")}` : ""}</div>
            {n.body}
          </li>
        ))}
        {!data.notes.length && <li className="faint">No notes yet.</li>}
      </ul>
    </section>
  );
}

function OutreachSection({ data, num, setState, onOutreach }: {
  data: CompanyDetail; num: string; setState: (p: Record<string, unknown>) => Promise<void>; onOutreach: () => void;
}) {
  const owner = data.ownership?.ultimate_owners?.find((u) => !u.unresolved && u.kind !== "corporate")?.name ?? "";
  const today = new Date().toISOString().slice(0, 10);
  const [contact, setContact] = useState({ contact_name: owner, contact_role: "owner", channel: "letter", summary: "", happened_on: today, follow_up_on: "" });
  const [outErr, setOutErr] = useState<string | null>(null);
  return (
    <section id="outreach">
      <Head icon="people" tone="grey" title="Contact log" />
      <form onSubmit={async (e) => {
        e.preventDefault();
        setOutErr(null);
        const { follow_up_on, ...c } = contact;
        try {
          await api.addOutreach({ ...c, contact_name: c.contact_name.trim() || "Owner", company_number: num,
                                  next_action: follow_up_on ? `Follow up: ${c.summary || c.channel}` : null, next_action_on: follow_up_on || null });
          if (follow_up_on) await setState({ next_action: `Follow up: ${c.summary || c.channel}`, next_action_on: follow_up_on });
          setContact({ ...contact, summary: "", follow_up_on: "" });
          onOutreach();
        } catch (err: any) { setOutErr(`Not saved: ${err.message}`); }
      }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 110px", gap: 6 }}>
          <input type="text" placeholder="Who (blank: the owner)" aria-label="Who" value={contact.contact_name} onChange={(e) => setContact({ ...contact, contact_name: e.target.value })} />
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
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 6, marginTop: 6, alignItems: "end" }}>
          <label className="field"><span className="label">When</span>
            <input type="date" value={contact.happened_on} onChange={(e) => setContact({ ...contact, happened_on: e.target.value })} /></label>
          <label className="field"><span className="label">Follow up on</span>
            <input type="date" value={contact.follow_up_on} onChange={(e) => setContact({ ...contact, follow_up_on: e.target.value })} /></label>
          <button className="btn" type="submit">Log contact</button>
        </div>
        {outErr && <div className="neg small" style={{ marginTop: 6 }}>{outErr}</div>}
      </form>
      <ul className="notes">
        {data.outreach.map((o) => (
          <li key={o.id}>
            <div className="meta">{date(o.happened_on)} · {o.channel} · {o.contact_role}</div>
            <b>{o.contact_name}</b>{o.summary ? `: ${o.summary}` : ""}
          </li>
        ))}
        {!data.outreach.length && <li className="faint">No contact yet.</li>}
      </ul>
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

/** Short chip text for the accounts type, e.g. "Small company", "Dormant", "No accounts yet". */
const ACCOUNTS_CHIP: Record<string, string> = {
  "micro entity": "Micro company", "small": "Small company", "total exemption full": "Small company",
  "total exemption small": "Small company", "unaudited abridged": "Small company", "audited abridged": "Small company",
  "partial exemption": "Small company", "medium": "Medium company", "full": "Large company (full accounts)",
  "group": "Group accounts", "audit exemption subsidiary": "Subsidiary of a group", "filing exemption subsidiary": "Subsidiary of a group",
  "dormant": "Dormant", "no accounts filed": "No accounts filed yet", "initial": "No accounts filed yet",
  "accounts type not available": "Accounts type not given",
};
function accountsChip(cat: string) {
  return ACCOUNTS_CHIP[cat.toLowerCase()] ?? `Accounts: ${cat}`;
}

/** Balance sheet and cost detail, where the accounts include it. Creditors
    are worked out from the totals the accounts state. */
function BalanceSheet({ fin }: { fin: CompanyDetail["financials"] }) {
  // Years as columns (newest first), figures as rows; only rows the accounts give.
  const n = (v: string | number | null | undefined) => (v === null || v === undefined || v === "" ? null : Number(v));
  const years = [...fin].reverse().filter((f) => !f.period_inferred).slice(0, 4);
  if (!years.length) return null;
  type F = (typeof years)[number];
  const da = (f: F) => n(f.depreciation_amortisation) ?? (n(f.depreciation) !== null || n(f.amortisation) !== null ? (n(f.depreciation) ?? 0) + (n(f.amortisation) ?? 0) : null);
  const ebitda = (f: F) => (n(f.operating_profit) !== null && da(f) !== null ? n(f.operating_profit)! + da(f)! : null);
  // Owed within / after a year: as filed, else worked out from the totals (shown in italics).
  const within = (f: F): [number | null, boolean] => {
    if (n(f.creditors_within) !== null) return [n(f.creditors_within), false];
    const ca = n(f.current_assets), nca = n(f.net_current_assets);
    return ca !== null && nca !== null && ca - nca >= 0 ? [ca - nca, true] : [null, false];
  };
  const after = (f: F): [number | null, boolean] => {
    if (n(f.creditors_after) !== null) return [n(f.creditors_after), false];
    const tal = n(f.total_assets_less_cl), na = n(f.net_assets);
    return tal !== null && na !== null && tal - na >= 0 ? [tal - na, true] : [null, false];
  };
  const bank = (f: F) => (n(f.bank_loans) !== null || n(f.bank_overdrafts) !== null ? (n(f.bank_loans) ?? 0) + (n(f.bank_overdrafts) ?? 0) : null);
  type Row = { label: string; get: (f: F) => number | null | [number | null, boolean]; hint?: string; strong?: boolean };
  const groups: [string, Row[]][] = [
    ["Profit", [
      { label: "Turnover", get: (f) => n(f.turnover) },
      { label: "Gross profit", get: (f) => n(f.gross_profit) },
      { label: "Staff costs", get: (f) => n(f.staff_costs) },
      { label: "Directors' pay", get: (f) => n(f.director_pay) },
      { label: "Operating profit", get: (f) => n(f.operating_profit) },
      { label: "Depreciation and amortisation", get: da },
      { label: "EBITDA", get: ebitda, strong: true, hint: "Operating profit + depreciation and amortisation, both filed" },
      { label: "Interest paid", get: (f) => n(f.interest_payable) },
      { label: "Tax", get: (f) => n(f.tax) },
      { label: "Profit after tax", get: (f) => n(f.profit_loss) },
      { label: "Dividends paid", get: (f) => n(f.dividends), hint: "Often how owners pay themselves: check against directors' pay" },
    ]],
    ["Balance sheet", [
      { label: "Fixed assets", get: (f) => n(f.fixed_assets) },
      { label: "of which intangible", get: (f) => n(f.intangible_assets) },
      { label: "Stock", get: (f) => n(f.stock) },
      { label: "Trade debtors", get: (f) => n(f.trade_debtors), hint: "Owed by customers" },
      { label: "Cash", get: (f) => n(f.cash) },
      { label: "Trade creditors", get: (f) => n(f.trade_creditors), hint: "Owed to suppliers" },
      { label: "Owed within a year", get: within },
      { label: "Owed after a year", get: after },
      { label: "Bank loans and overdrafts", get: bank, strong: true, hint: "Repaid from the price on a cash-free, debt-free deal" },
      { label: "Retained earnings", get: (f) => n(f.retained_earnings), hint: "Profits kept in the business: the most that could be paid out as dividends" },
      { label: "Share capital", get: (f) => n(f.share_capital) },
      { label: "Net assets", get: (f) => n(f.net_assets), strong: true },
    ]],
  ];
  const val = (r: Row, f: F): [number | null, boolean] => { const v = r.get(f); return Array.isArray(v) ? v : [v, false]; };
  const shown = groups.map(([g, rows]) => [g, rows.filter((r) => years.some((f) => val(r, f)[0] !== null))] as const)
    .filter(([, rows]) => rows.length > 1);
  if (!shown.length) return null;
  return (
    <>
      {shown.map(([g, rows]) => (
        <div key={g} style={{ overflowX: "auto" }}>
          <h3 style={{ margin: "18px 0 6px", fontSize: 14 }}>{g}</h3>
          <table className="yeartable">
            <thead><tr><th />{years.map((f) => <th key={f.period_end} className="num" title={date(f.period_end)}>
              {new Date(f.period_end).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}</th>)}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className={r.strong ? "strong" : ""}>
                  <td title={r.hint}>{r.label}{r.hint ? <span className="faint"> ⓘ</span> : null}</td>
                  {years.map((f) => {
                    const [v, worked] = val(r, f);
                    return <td key={f.period_end} className={`num ${v !== null && v < 0 ? "neg" : ""} ${worked ? "worked" : ""}`}
                               title={worked ? "Worked out from the filed totals" : undefined}>
                      {v === null ? "—" : money(v, { precise: true })}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p className="faint small">Only figures the accounts give. Small companies often file a balance sheet only. <i>Italic</i>: worked out from the filed totals.</p>
    </>
  );
}


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


/** Companies that look related (same owner and address, or a director in
    common at the same postcode), for information. */
function SameBusiness({ data }: { data: CompanyDetail }) {
  const others = data.same_business ?? [];
  if (!others.length) return null;
  return (
    <div className="callout">
      <b>Linked:</b>{" "}
      {others.map((o, i) => (
        <span key={o.company_number}>{i ? "; " : ""}<Link to={`/c/${o.company_number}`}>{o.name}</Link>
          <span className="faint"> ({o.employees ?? "?"} staff{o.revenue_low ? `, ${range(o.revenue_low, o.revenue_high)}` : ""})</span></span>
      ))}
      <span className="faint small"> · same owner and address, or a director in common at the same postcode</span>
    </div>
  );
}


/** After ruling one out and moving on: say so, with Undo. */
function UndoBar() {
  const [u, setU] = useState<{ num: string; name: string; prev: string; note: string } | null>(() => {
    try { const v = JSON.parse(sessionStorage.getItem("ao.undo") ?? "null"); sessionStorage.removeItem("ao.undo"); return v; } catch { return null; }
  });
  if (!u) return null;
  const from = listFrom();
  return (
    <div className="callout undo">
      <span><b>{u.name}</b> · {u.note}</span>
      <button className="btn quiet" onClick={async () => { await api.setState(u.num, { status: u.prev, stage_note: "Undone" }); setU(null); }}>Undo</button>
      {from && <Link className="faint small" to={from}>Back to the list</Link>}
      <button className="linkish small" style={{ marginLeft: "auto" }} onClick={() => setU(null)}>Dismiss</button>
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
