import type React from "react";
import { Fragment, useEffect, useRef, useState } from "react";
import { duration, elapsed, useJob } from "../components/JobBar";
import { Link } from "react-router-dom";
import { api, type ChSync, type PdfFailure, type PdfRead, type PdfCheck, type PdfYear, type Preview } from "../api";
import { ErrorLine, Hint, useAsync } from "../components/bits";
import { date, dateTime, int } from "../format";

const KINDS = {
  companies: {
    title: "Company data",
    text: "Your ranked Companies House file, the audit workbook, a Companies House bulk extract, or any CSV or Excel list with a company number column. Re-importing updates figures, records what changed (new accounts, dissolved, renamed, moved) and never touches your notes.",
  },
  notes: {
    title: "My notes and decisions",
    text: "Your assessments, ratings and decisions, matched on company number. Notes are added, never replaced, and anything you have already changed in the app is kept.",
  },
} as const;

const FIELD_LABELS: Record<string, string> = {
  company_number: "Company number", name: "Company name", status: "Status", company_type: "Company type",
  company_subtype: "Subtype", incorporation_date: "Incorporation date", sic: "SIC codes", address: "Registered address",
  postcode: "Postcode", wales_flag: "In Wales (yes/no)", region: "Region", review_tier: "Review tier",
  accounts_made_up_to: "Accounts date", employees: "Staff", employees_prev: "Staff, prior year", turnover: "Turnover",
  profit_loss: "Profit or loss", operating_profit: "Operating profit", net_assets: "Net assets",
  net_assets_prev: "Net assets, prior year", cash: "Cash", debtors: "Debtors", dividends: "Dividends",
  est_revenue_low: "Revenue estimate, low", est_revenue_high: "Revenue estimate, high",
  rating: "Rating (1–5)", next_action: "Next action",
};

export default function Import() {
  const [kind, setKind] = useState<keyof typeof KINDS>("companies");
  const [file, setFile] = useState<File | null>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [over, setOver] = useState(false);
  const [onlyExisting, setOnlyExisting] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const history = useAsync(() => api.imports(), [result]);

  const load = async (f: File, sheet?: string) => {
    setFile(f); setErr(null); setResult(null); setBusy(true);
    try {
      const p = await api.preview(kind, f, sheet);
      setPv(p); setMapping(p.mapping);
    } catch (e: any) { setErr(e.message); setPv(null); }
    setBusy(false);
  };
  const commit = async (sheet?: string) => {
    if (!pv) return;
    setBusy(true); setErr(null);
    try {
      setResult(await api.commit({ kind, token: pv.token, suffix: pv.suffix, filename: pv.filename, mapping, sheet, only_existing: onlyExisting }));
      setPv(null); setFile(null);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const [sheet, setSheet] = useState<string | undefined>();

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Data</h1>
          <div className="lede">Companies House data and your own files.</div>
        </div>
      </div>

      <Coverage />

      <section style={{ paddingTop: 0 }}>
        <div className="seg" style={{ display: "inline-flex" }}>
          {(Object.keys(KINDS) as (keyof typeof KINDS)[]).map((k) => (
            <button key={k} className={kind === k ? "on" : ""} onClick={() => { setKind(k); setPv(null); setResult(null); }}>{KINDS[k].title}</button>
          ))}
        </div>
        <p className="muted" style={{ maxWidth: "75ch" }}>{KINDS[kind].text}</p>
        {kind === "notes" && <p className="small muted">Import company data first: notes for companies not yet in the list are skipped and reported.</p>}

        <div className={`drop ${over ? "over" : ""}`} onClick={() => input.current?.click()}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) load(f); }}>
          {busy ? "Reading…" : file ? <><b>{file.name}</b> · choose a different file</> : <><b>Drop a CSV or Excel file here</b>, or click to choose</>}
          <input ref={input} type="file" accept=".csv,.xlsx,.xlsm,.txt,.zip" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) load(f); e.target.value = ""; }} />
        </div>
        <ErrorLine error={err} />
      </section>

      {result && (
        <div className="callout">
          <b>Imported {result.rows_ok.toLocaleString("en-GB")} of {result.rows_in.toLocaleString("en-GB")} rows</b>
          {result.notes_added !== undefined ? `, ${result.notes_added} notes added` : ""}
          {result.rows_skipped ? `, ${result.rows_skipped.toLocaleString("en-GB")} skipped` : ""}
          {result.changes !== undefined ? `, ${result.changes.toLocaleString("en-GB")} changes found` : ""}. Ownership, links and scores have been recalculated.{" "}
          {result.changes ? <Link to="/changes?days=7">See what changed</Link> : <Link to="/targets">See targets</Link>}
          {result.messages?.length > 0 && (
            <ul className="small" style={{ margin: "8px 0 0", paddingLeft: 18 }}>{result.messages.slice(0, 8).map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
          )}
        </div>
      )}

      {pv && (
        <section>
          <div className="sechead">
            <h2>{pv.filename}: {pv.row_count === null ? "large file" : `${pv.row_count.toLocaleString("en-GB")} rows`}</h2>
            {pv.sheets.length > 1 && (
              <span className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <span className="label">Sheet</span>
                <select value={sheet ?? ""} onChange={(e) => { setSheet(e.target.value); if (file) load(file, e.target.value); }}>
                  <option value="">Best guess</option>
                  {pv.sheets.map((s) => <option key={s}>{s}</option>)}
                </select>
              </span>
            )}
            <span className="right" style={{ display: "flex", gap: 16, alignItems: "center" }}>
              {kind === "companies" && (
                <label className="check" title="Use this with the full Companies House bulk file">
                  <input type="checkbox" checked={onlyExisting} onChange={(e) => setOnlyExisting(e.target.checked)} />
                  Only update companies already in my list
                </label>
              )}
              <button className="btn primary" disabled={busy || !mapping.company_number} onClick={() => commit(sheet)}>{busy ? "Importing…" : "Import"}</button>
            </span>
          </div>
          {pv.problems.map((p) => <div key={p} className="callout red">{p} Choose the right column below.</div>)}
          <table className="mapping">
            <thead><tr><th style={{ width: 220 }}>Field</th><th style={{ width: 300 }}>Read from column</th><th>First values</th></tr></thead>
            <tbody>
              {pv.fields.filter((f) => f !== "notes").map((f) => (
                <tr key={f}>
                  <td>{FIELD_LABELS[f] ?? f}{f === "company_number" && <span className="neg"> *</span>}</td>
                  <td>
                    {Array.isArray(mapping[f]) ? (
                      <span className="small">Joined from {mapping[f].length} columns <button className="btn quiet" onClick={() => setMapping({ ...mapping, [f]: mapping[f][0] })}>Use one</button></span>
                    ) : (
                      <select value={mapping[f] ?? ""} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value || null })}>
                        <option value="">Not in this file</option>
                        {pv.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                      </select>
                    )}
                  </td>
                  <td className="muted small">{mapping[f] ? pv.sample.slice(0, 3).map((r) => Array.isArray(mapping[f]) ? mapping[f].map((h: string) => r[h]).filter(Boolean).join(", ") : String(r[mapping[f]] ?? "")).filter(Boolean).join(" · ") : ""}</td>
                </tr>
              ))}
              {kind === "notes" && (
                <tr>
                  <td>Note columns<div className="sub">Each becomes a note</div></td>
                  <td colSpan={2}>
                    {pv.headers.map((h) => (
                      <label key={h} className="check" style={{ display: "inline-flex", marginRight: 12 }}>
                        <input type="checkbox" checked={(mapping.notes ?? []).includes(h)}
                               onChange={(e) => setMapping({ ...mapping, notes: e.target.checked ? [...(mapping.notes ?? []), h] : (mapping.notes ?? []).filter((x: string) => x !== h) })} />
                        {h}
                      </label>
                    ))}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {kind === "companies" && pv.unmapped && pv.unmapped.length > 0 && (
            <p className="muted small">Kept as extra details on each company: {pv.unmapped.join(", ")}.</p>
          )}
        </section>
      )}

      <ChFeed onDone={history.reload} />
      <CatchUp />
      <ChSyncPanel />
      <PdfReadPanel />
      <WebsiteBatch />
      <LogoBatch />
      <AccountsGaps />

      <section>
        <h2>History</h2>
        {history.data?.length ? (
          <table>
            <thead><tr><th>When</th><th>Type</th><th>File</th><th className="num">Rows</th><th className="num">Skipped</th></tr></thead>
            <tbody>
              {history.data.map((h) => (
                <tr key={h.id}>
                  <td>{dateTime(h.finished_at ?? h.started_at)}</td><td>{h.kind}</td><td>{h.filename}</td>
                  <td className="num">{h.rows_ok.toLocaleString("en-GB")}</td><td className="num">{h.rows_skipped || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="faint">Nothing imported yet.</div>}
      </section>
    </>
  );
}


function ChFeed({ onDone }: { onDone: () => void }) {
  const [months, setMonths] = useState(24);
  const [reread, setReread] = useState(false);
  const { job, refresh } = useJob();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const running = !!job?.running;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) onDone();
    wasRunning.current = running;
  }, [running, onDone]);

  const start = async () => {
    setBusy(true); setMsg(null);
    try { await api.startRefresh(months, reread); refresh(); } catch (e: any) { setMsg(e.message); }
    setBusy(false);
  };
  const stop = async () => {
    if (!job?.id || !confirm("Stop the refresh? Everything loaded so far is kept, and running it again carries on from where it stopped.")) return;
    const r = await api.cancelJob(job.id);
    setMsg(r.message); refresh();
  };
  const pct = Number(job?.pct ?? 0);
  const icon = (st: string) => st === "done" ? "✓" : "";
  const cls = (st: string) => st === "done" ? "done" : st === "running" ? "running" : ["already loaded", "skipped"].includes(st) ? "skip" : "";

  return (
    <section id="job">
      <div className="sechead">
        <h2>Companies House bulk data</h2>
        <span className="right" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {running ? (
            <button className="btn" onClick={stop} disabled={job?.cancel_requested}>{job?.cancel_requested ? "Stopping…" : "Stop"}</button>
          ) : (
            <>
              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <span className="label">Months of accounts</span>
                <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>
                  {[[1, "1 (monthly top-up)"], [12, "12 (about 2 years of figures)"], [24, "24 (about 3 years)"],
                    [36, "36 (about 4 years)"], [48, "48 (about 5 years)"], [60, "60 (about 6 years)"],
                    [96, "96 (about 9 years)"], [120, "120 (about 11 years)"], [156, "156 (about 14 years)"]].map(([m, l]) =>
                    <option key={m} value={m}>{l}</option>)}
                </select>
              </label>
              <label className="check small" title="Months loaded before AcquireOS read balance sheet and cost figures are downloaded and read again">
                <input type="checkbox" checked={reread} onChange={(e) => setReread(e.target.checked)} />
                Re-read older months for new figures
              </label>
              <button className="btn primary" disabled={busy} onClick={start}>Download and load now</button>
            </>
          )}
        </span>
      </div>

      {job && (job.running || job.finished_at) && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
            <span className="big">{Math.round(pct)}%</span>
            <span className="muted">
              {job.running
                ? <>Step {(job.stage_index ?? 0) + 1} of {job.stage_total}: <b className="ink">{job.stage ?? "starting"}</b></>
                : job.status === "done" && !job.error ? "Finished" : job.status === "cancelled" ? "Stopped" : "Finished with problems"}
            </span>
            <span className="faint small" style={{ marginLeft: "auto" }}>
              {job.running
                ? <>Running for {duration(elapsed(job.started_at))}{job.eta_seconds ? <> · about <b className="ink">{duration(job.eta_seconds)}</b> left</> : " · working out time left"}</>
                : <>Took {duration(elapsed(job.started_at, job.finished_at))} · finished {job.finished_at ? new Date(job.finished_at).toLocaleString("en-GB") : ""}</>}
            </span>
          </div>
          <div className="bigbar"><i style={{ width: `${Math.max(pct, job.running ? 1 : 0)}%` }} /></div>
          {job.running && job.detail && <div className="muted small">{job.detail}</div>}
          {job.error && <div className="callout red" style={{ marginTop: 10 }}>{job.error}</div>}
          {job.stages && job.stages.length > 0 && (
            <ul className="stagelist">
              {job.stages.map((st) => (
                <li key={st.name} className={cls(st.status)}>
                  <span className="ic">{icon(st.status)}</span>{st.name}
                  <span className="sec">{st.status === "already loaded" ? "already loaded" : st.seconds ? duration(st.seconds) : ""}</span>
                </li>
              ))}
            </ul>
          )}
          {job.log && job.log.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary className="muted" style={{ cursor: "pointer" }}>Activity log</summary>
              <pre className="joblog">{[...job.log].reverse().join("\n")}</pre>
            </details>
          )}
          <p className="faint small" style={{ marginBottom: 0 }}>
            Runs on the server; you can close this page.
          </p>
        </div>
      )}
      {msg && <div className="callout" style={{ marginBottom: 12 }}>{msg}</div>}

      <p className="muted" style={{ maxWidth: "80ch", marginTop: 0 }}>
        Runs monthly by itself. Months already loaded are skipped.
      </p>
      <table>
        <thead><tr><th>File</th><th>What it adds</th><th>Size</th></tr></thead>
        <tbody>
          <tr><td><a href="https://download.companieshouse.gov.uk/en_output.html" target="_blank" rel="noreferrer">Basic company data ↗</a></td>
            <td>Every live company: name, status, address, SIC codes, accounts dates. All are kept; your <Link to="/buy-box">universe</Link> decides which count as targets.</td><td className="nowrap">~0.5 GB zip</td></tr>
          <tr><td><a href="https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html" target="_blank" rel="noreferrer">Monthly accounts ↗</a></td>
            <td>Filed accounts (staff, turnover, profit, net assets, cash, debtors) for every company, current and prior year. Builds the history charts.</td><td className="nowrap">several GB a month</td></tr>
          <tr><td><a href="https://download.companieshouse.gov.uk/en_pscdata.html" target="_blank" rel="noreferrer">Owners (PSC) ↗</a></td>
            <td>Who owns every company, traced through holding companies; ages, trusts, EOTs, foreign parents.</td><td className="nowrap">~2 GB zip</td></tr>
        </tbody>
      </table>
      <details style={{ marginTop: 14 }}>
        <summary className="muted" style={{ cursor: "pointer" }}>Prefer the command line?</summary>
        <pre className="cmd">{`docker exec -it acquireos acquireos fetch all --months 24
docker exec -it acquireos acquireos fetch accounts --months 24`}</pre>
      </details>
    </section>
  );
}

/** What share of active companies has owners and accounts, and why the rest do not. */
function Coverage() {
  const { data, error } = useAsync(() => api.coverage(), []);
  if (error) return <ErrorLine error={error} />;
  if (!data) return <section><h2>What's loaded</h2><div className="faint">Counting… on the full register this takes up to a minute.</div></section>;
  const pct = (n: number) => (data.active ? `${Math.round((100 * n) / data.active)}%` : "—");
  const months = data.accounts_files.map((f: any) => f.filename.replace(/^Accounts_(Monthly_)?Data-?/, "").replace(/\.zip$/, "").replace(/([a-z])(\d{4})/i, "$1 $2"));
  const row = (label: string, n: number, why: React.ReactNode) => (
    <tr><td><b>{label}</b></td><td className="num">{n.toLocaleString("en-GB")}</td><td className="num"><b>{pct(n)}</b></td><td className="muted small">{why}</td></tr>
  );
  return (
    <section>
      <div className="sechead"><h2>What's loaded</h2><span className="faint small">Out of {data.active.toLocaleString("en-GB")} active companies</span></div>
      <table>
        <thead><tr><th>Data</th><th className="num">Companies</th><th className="num">Share</th><th>Why some are missing</th></tr></thead>
        <tbody>
          {row("Owners (PSC) on file", data.with_psc, <>
            {data.psc_file ? <>From {data.psc_file.filename}. </> : <b>The owners snapshot has not been loaded yet. </b>}
            Companies without one have filed a statement instead (no one with over 25%, or not yet identified), are exempt (e.g. listed on a market), or have not filed.
          </>)}
          {row("Ownership traced", data.owners_traced, "Owners found and classified (owner-held, group-owned and so on).")}
          {row("Accounts", data.with_accounts, <>
            {months.length ? <>{months.length} month{months.length === 1 ? "" : "s"} loaded ({months.slice(-1)[0]} to {months[0]}). </> : <b>No accounts files loaded yet. </b>}
            Each company files once a year, so it takes 12 months of files to reach most of them; paper filings are never in the bulk data,
            and {data.too_new.toLocaleString("en-GB")} companies are too new to have filed.
          </>)}
          {row("Staff numbers", data.with_staff, "Only where the accounts state the average number of employees.")}
          {row("Turnover filed", data.with_turnover, "Small companies may leave out the profit and loss account, so most never file turnover; AcquireOS estimates it from staff instead.")}
        </tbody>
      </table>
      <p className="faint small">Directors come from the API, company by company <Hint text="They are not in the free bulk files." /></p>
    </section>
  );
}


/** Companies House API details (directors, shareholders, charges, filings) for many companies at once. */
function StreamLine({ s }: { s: ChSync["stream"] }) {
  if (!s?.enabled) return <p className="small" style={{ margin: "8px 0 0" }}><b>Live updates</b> · off. Add <code>CH_STREAM_KEY</code> to the scheduler for changes within minutes.</p>;
  const names = Object.entries(s.streams);
  const on = names.filter(([, x]) => x.connected).length;
  const events = names.reduce((a, [, x]) => a + (x.events || 0), 0);
  const err = names.find(([, x]) => !x.connected && x.error)?.[1].error;
  return (
    <p className="small" style={{ margin: "8px 0 0" }}>
      <b>Live updates</b> · <span className={`chip ${s.live ? "green" : "red"}`}>{s.live ? `${on} of ${names.length} streams connected` : "Not connected"}</span>
      {" "}{int(events)} events, {int(s.status_changes ?? 0)} status changes, {int(s.waiting)} companies waiting for a re-fetch
      {err && <span className="neg"> · {err}</span>}
    </p>
  );
}

/** Data collected since some of it was loaded: what still needs reading again, with progress. */
function CatchUp() {
  const [acc, setAcc] = useState<Awaited<ReturnType<typeof api.catchUp>> | null>(null);
  const [ex, setEx] = useState<Awaited<ReturnType<typeof api.chExtras>> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const { job, refresh } = useJob();
  useEffect(() => {
    let live = true;
    const load = () => {
      api.catchUp().then((d) => live && setAcc(d)).catch(() => {});
      api.chExtras().then((d) => live && setEx(d)).catch(() => {});
    };
    load();
    const t = setInterval(load, 30_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  if (!acc && !ex) return null;
  const bar = (done: number, total: number) => (
    <div className="syncbar"><i style={{ width: `${total ? Math.min(100, (100 * done) / total) : 0}%` }} /></div>);
  const reread = async () => {
    setMsg(null);
    try { await api.startRefresh(Math.min(180, Math.max(1, acc!.accounts_months_total)), true); refresh(); setMsg("Started: progress shows under Companies House bulk data above."); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <section>
      <div className="sechead"><h2>Catch up<Hint text="Checks run in the background at the shared Companies House rate, your pipeline first. Directors are checked again every six months; new disqualifications arrive on the stream." /></h2>
        {ex && <button className="btn quiet" style={{ marginLeft: "auto" }} onClick={async () => setEx(await api.chExtrasSet(!ex.paused))}>
          {ex.paused ? "Resume checks" : "Pause checks"}</button>}</div>
      <p className="faint small" style={{ marginTop: 0 }}>New figures and checks, filled in for data you already have.</p>
      <div className="syncgrid">
        {acc && (
          <div>
            <div className="small"><b>Accounts: depreciation, debt, working capital, reserves, activity</b></div>
            {bar(acc.accounts_months_current, acc.accounts_months_total)}
            <div className="faint small">
              {acc.accounts_months_total === 0 ? "No accounts loaded yet."
                : acc.accounts_months_old === 0 ? `✓ All ${acc.accounts_months_total} ${acc.accounts_months_total === 1 ? "month" : "months"} read with the latest figures`
                : <>{int(acc.accounts_months_current)} of {int(acc.accounts_months_total)} months read with them.{" "}
                    {job?.running ? "A load is running." : <button className="linkish small" onClick={reread}>Re-read the other {acc.accounts_months_old} now</button>}
                    <span> (each month is downloaded again; on the Pi this can take hours)</span></>}
            </div>
          </div>
        )}
        {acc && acc.staff_fix !== undefined && (
          <div>
            <div className="small"><b>Misread staff counts</b><Hint text="Years, money amounts, references or £000-scaled numbers read as staff, and counts over five times off both the year before and after. Cleared and read again from that year's own filing; figures saved by you or Claude are never changed." /></div>
            <div className="faint small">
              {acc.staff_fix ? <>✓ Run{acc.staff_fix.at ? ` (last ${dateTime(acc.staff_fix.at)})` : ""}
                  {acc.staff_fix.years != null ? `: ${int(acc.staff_fix.years)} years in ${int(acc.staff_fix.companies ?? 0)} companies cleared in total` : ""}
                  {acc.staff_fix.outliers ? ` (${int(acc.staff_fix.outliers)} of them outliers against the years either side)` : ""}
                  {acc.staff_fix.pdf_years_requeued ? `, ${int(acc.staff_fix.pdf_years_requeued)} PDF years queued to read again` : ""}
                  {acc.staff_fix.data_years_reread ? `, ${int(acc.staff_fix.data_years_reread)} filled from the filing` : ""}
                  {acc.staff_fix.blank_filled ? `, ${int(acc.staff_fix.blank_filled)} missing counts filled` : ""}
                  {acc.staff_fix.large_corrected ? `, ${int(acc.staff_fix.large_corrected)} large companies corrected` : ""}.{" "}
                  <button className="linkish small" onClick={async () => {
                    try { await api.fixStaffYears(); setMsg("Checking staff counts again: progress shows above."); refresh(); }
                    catch (e: any) { setMsg(e.message); } }}>Run again</button>
                  {acc.staff_fix.data_years_no_link ? <> {int(acc.staff_fix.data_years_no_link)} years are still blank (no electronic filing to read them from). </> : null}</>
                : <>Not run yet. It runs by itself once no data load is running, or{" "}
                    <button className="linkish small" onClick={async () => {
                      try { await api.fixStaffYears(); setMsg("Clearing misread staff counts: progress shows above."); refresh(); }
                      catch (e: any) { setMsg(e.message); } }}>fix now</button>. Your and Claude's saved figures are never changed.</>}
            </div>
          </div>
        )}
        {acc && acc.owners_current !== undefined && (
          <div>
            <div className="small"><b>Owners classified with the latest rules</b></div>
            <div className="faint small">
              {acc.owners_current ? "✓ Up to date"
                : job?.running ? "Rules changed: they'll be applied automatically once the running load finishes."
                : <>Rules changed (people with control only no longer count as owners).{" "}
                    <button className="linkish small" onClick={async () => {
                      try { await api.reclassifyOwners(); setMsg("Reclassifying owners, then rescoring: progress shows above."); refresh(); }
                      catch (e: any) { setMsg(e.message); } }}>Reclassify owners now</button></>}
            </div>
          </div>
        )}
        {ex && (
          <>
            <div>
              <div className="small"><b>Directors checked for disqualification</b></div>
              {bar(ex.directors_checked, ex.directors_total)}
              <div className="faint small">{int(ex.directors_checked)} of {int(ex.directors_total)} checked
                {ex.disqualified_found ? <> · <span className="neg">{int(ex.disqualified_found)} disqualified</span></> : " · none disqualified so far"}
                {ex.disqualified_known ? ` · ${int(ex.disqualified_known)} disqualification records held` : ""}</div>
            </div>
            <div>
              <div className="small"><b>Year end, overseas parents, PSC exemptions</b></div>
              {bar(ex.companies_done, ex.companies_total)}
              <div className="faint small">{int(ex.companies_done)} of {int(ex.companies_total)} fetched companies</div>
            </div>
          </>
        )}
      </div>
      {msg && <p className="small">{msg}</p>}
      
    </section>
  );
}

function PdfReadPanel() {
  const [st, setSt] = useState<PdfRead | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.pdfRead().then((d) => { if (live) { setSt(d); setErr(null); } }).catch((e) => live && setErr(e.message));
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const toggle = async () => {
    if (!st) return;
    try { setSt(await api.pdfReadSet(!st.paused)); } catch (e: any) { setErr(e.message); }
  };
  if (!st) return err ? <ErrorLine error={err} /> : null;
  const state = st.paused ? ["Paused", ""] : st.queue ? ["Reading", "green"] : ["Up to date", "green"];
  return (
    <section>
      <div className="sechead"><h2>PDF accounts</h2>
        <span className={`chip ${state[1]}`}>{state[0]}</span>
        <button className="btn quiet" style={{ marginLeft: "auto" }} onClick={toggle}>{st.paused ? "Resume" : "Pause"}</button></div>
      <p className="small" style={{ margin: 0 }}>
        <b>{int(st.done)}</b> read{st.by_ocr || st.by_data || st.by_claude ? <> ({[st.by_ocr ? `${int(st.by_ocr)} by OCR` : "", st.by_data ? `${int(st.by_data)} as data` : "", st.by_claude ? `${int(st.by_claude)} by Claude` : ""].filter(Boolean).join(", ")})</> : null}
        {" · "}<b>{int(st.nothing_found + st.failed)}</b> couldn't be read{st.closed ? <> · {int(st.closed)} closed</> : null}
        {" · "}<b>{int(st.queue)}</b> waiting{st.last_at ? <> · last {dateTime(st.last_at)}</> : null}
      </p>
      <PdfFailures count={st.nothing_found + st.failed} onRetried={setSt} />
      <PdfCheckList count={st.suspicious ?? 0} />
      <PdfRedo onDone={setSt} />
      {!st.ocr && <div className="callout amber" style={{ marginTop: 8 }}>OCR isn't installed here, so only PDFs with a text layer can be read. Update the stack to get the new image.</div>}
      <p className="faint small">Years with no figures, newest first, back up to 10 years.<Hint text="For every company fetched from Companies House. Read as data where Companies House has it, otherwise from the PDF (text, or OCR for scans). Your pipeline first. PDF figures are marked on the company page." /></p>
    </section>
  );
}

function PdfRedo({ onDone }: { onDone: (s: PdfRead) => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const go = async () => {
    if (!confirm("Clear every figure the PDF reader produced and read those years again?\n\nFigures saved by you or Claude, and accounts read as data, are kept.")) return;
    setBusy(true);
    try {
      const r = await api.pdfRedo();
      onDone(r);
      setMsg(`Cleared ${int(r.figures_cleared)} years across ${int(r.companies)} companies. They're queued to be read again.`);
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
      <button className="btn quiet" disabled={busy} onClick={go}>{busy ? "Clearing…" : "Redo PDF readings"}</button>
      {msg ? <span className="small">{msg}</span>
        : <span className="faint small">Reads every PDF year again with the current reader.<Hint text="Only figures the reader produced are cleared. Anything saved by you or Claude stays." /></span>}
    </div>
  );
}

const FIG_LABEL: Record<string, string> = {
  turnover: "Turnover", gross_profit: "Gross profit", operating_profit: "Operating profit", profit_loss: "Profit after tax",
  employees: "Staff", net_assets: "Net assets", cash: "Cash", debtors: "Debtors", fixed_assets: "Fixed assets",
  current_assets: "Current assets", net_current_assets: "Net current assets", total_assets_less_cl: "Total assets less current liabilities",
  creditors_within: "Creditors within a year", creditors_after: "Creditors after a year", stock: "Stock", staff_costs: "Staff costs",
  director_pay: "Directors' pay", dividends: "Dividends", depreciation: "Depreciation", amortisation: "Amortisation",
  interest_payable: "Interest paid", tax: "Tax", bank_loans: "Bank loans",
};

/** Check what the PDF reader read: a list of years, each opening a side-by-side check. */
function PdfCheckList({ count }: { count: number }) {
  const [show, setShow] = useState<"check" | "all">("check");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PdfYear[] | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!shown) return;
    let live = true;
    const t = setTimeout(() => api.pdfYears(show, q.trim() || undefined).then((r) => live && setRows(r)).catch(() => live && setRows([])), 250);
    return () => { live = false; clearTimeout(t); };
  }, [show, q, shown]);
  const key = (r: PdfYear) => `${r.company_number}-${String(r.period_end).slice(0, 10)}`;
  return (
    <details style={{ marginTop: 8 }} onToggle={(e) => setShown((e.target as HTMLDetailsElement).open)}>
      <summary className="small" style={{ cursor: "pointer" }}>Check readings{count ? <> · <b>{int(count)}</b> worth checking</> : null}</summary>
      <div style={{ display: "flex", gap: 8, margin: "8px 0", flexWrap: "wrap", alignItems: "center" }}>
        <span className="seg2"><button className={show === "check" ? "on" : ""} onClick={() => setShow("check")}>Worth checking</button>
          <button className={show === "all" ? "on" : ""} onClick={() => setShow("all")}>All read from PDFs</button></span>
        <input type="search" placeholder="Company name or number" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
      </div>
      {!rows ? <div className="faint small">Loading…</div> : rows.length === 0 ? <div className="faint small">{show === "check" ? "Nothing looks wrong." : "No years read from PDFs yet."}</div> : (
        <table className="small pdfcheck-list">
          <thead><tr><th>Company</th><th>Year end</th><th>{show === "check" ? "Why" : "Read"}</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={key(r)}>
                <tr className={openKey === key(r) ? "on" : ""} onClick={() => setOpenKey(openKey === key(r) ? null : key(r))} style={{ cursor: "pointer" }}>
                  <td><Link to={`/c/${r.company_number}`} onClick={(e) => e.stopPropagation()}>{r.name}</Link></td>
                  <td className="nowrap">{String(r.period_end).slice(0, 10)}</td>
                  <td>{show === "check" ? r.why.join("; ") : <>{r.method === "ocr" ? "OCR (scanned)" : "Text"}{r.read_at ? ` · ${dateTime(r.read_at)}` : ""}</>}
                    {r.checked ? <span className="chip green" style={{ marginLeft: 6 }}>Checked</span> : null}</td>
                  <td className="nowrap"><button className="linkish small">{openKey === key(r) ? "Close" : "Check"}</button></td>
                </tr>
                {openKey === key(r) && <tr><td colSpan={4} style={{ padding: 0 }}>
                  <PdfCheckPanel num={r.company_number} pe={String(r.period_end).slice(0, 10)}
                                 onDone={() => { setOpenKey(null); setRows((xs) => (xs ?? []).filter((x) => show === "all" ? true : key(x) !== key(r))); }} />
                </td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

function PdfCheckPanel({ num, pe, onDone }: { num: string; pe: string; onDone: () => void }) {
  const [d, setD] = useState<PdfCheck | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  // The PDF is fetched once per panel (not stored), then shown from memory.
  const [pdf, setPdf] = useState<{ url: string | null; err: string | null } | null>(null);
  useEffect(() => {
    if (!d?.made_up) return;
    let url: string | null = null, live = true;
    fetch(`/api/pdf-read/pdf?company_number=${encodeURIComponent(num)}&made_up=${d.made_up}`)
      .then(async (r) => {
        if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail ?? m; } catch { /* not json */ }
          if (live) setPdf({ url: null, err: m === "Needs CH_API_KEY" ? "Add your Companies House API key to the stack to see the PDF here." : m }); return; }
        url = URL.createObjectURL(await r.blob());
        if (live) setPdf({ url, err: null });
      }).catch((e) => live && setPdf({ url: null, err: e.message }));
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [num, d?.made_up]);
  useEffect(() => {
    api.pdfCheck(num, pe).then((x) => {
      setD(x);
      setVals(Object.fromEntries(Object.entries(x.figures).filter(([, v]) => v !== null).map(([k, v]) => [k, Math.round(v!).toLocaleString("en-GB")])));
      setSel(Object.keys(x.lines)[0] ?? null);
    }).catch((e) => setErr(e.message));
  }, [num, pe]);
  if (err) return <div className="callout red">{err}</div>;
  if (!d) return <div className="faint small" style={{ padding: 12 }}>Loading…</div>;
  const parse = (s: string) => { const t = s.replace(/[£,\s]/g, "").replace(/^\((.*)\)$/, "-$1"); return t === "" ? null : Number(t); };
  const now = (k: string) => (k in vals ? parse(vals[k]) : null);
  const changed = Object.keys(FIG_LABEL).filter((k) => {
    const w = d.figures[k] ?? null, n = now(k);
    if (n !== null && Number.isNaN(n)) return true;
    return (w === null ? null : Math.round(w)) !== (n === null ? null : Math.round(n));
  });
  const bad = changed.filter((k) => k in vals && vals[k].trim() !== "" && Number.isNaN(parse(vals[k])));
  const shownFields = Object.keys(FIG_LABEL).filter((k) => d.figures[k] !== null || k in vals);
  // Pages: split on the reader's page markers.
  const pages: { n: number | null; text: string }[] = [];
  for (const part of (d.text ?? "").split(/\[\[page (\d+)\]\]\n?/)) {
    if (/^\d+$/.test(part)) { pages.push({ n: Number(part), text: "" }); continue; }
    if (!pages.length) pages.push({ n: null, text: "" });
    pages[pages.length - 1].text += part;
  }
  const selLine = sel ? d.lines[sel] : null;
  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  const pageOf = selLine ? pages.find((p) => p.text.split("\n").some((l) => norm(l) === norm(selLine)))?.n ?? null : null;
  const pdfUrl = d.made_up ? `/api/pdf-read/pdf?company_number=${encodeURIComponent(num)}&made_up=${d.made_up}` : null;
  const save = async (asIs: boolean) => {
    setBusy(true); setMsg(null);
    try {
      const values: Record<string, number | null> = {};
      if (!asIs) for (const k of changed) values[k] = k in vals ? parse(vals[k]) : null;
      const r = await api.pdfCorrect(num, d.period_end, values);
      setMsg(r.changed.length ? `Saved: ${r.changed.join("; ")}` : "Marked as checked.");
      setTimeout(onDone, 900);
    } catch (e: any) { setMsg(e.message); }
    setBusy(false);
  };
  return (
    <div className="pdfcheck">
      <div className="pc-head">
        <b>{d.name} · {new Date(d.period_end).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}</b>
        <span className={`chip ${d.method === "ocr" ? "amber" : ""}`}>{d.method === "ocr" ? "Read by OCR (scanned)" : d.method === "text" ? "Read from the text layer" : "Not read from a PDF"}</span>
        {d.column === "prior" && <span className="faint small">from the prior-year column of the {d.made_up?.slice(0, 4)} accounts</span>}
        {d.why.length > 0 && <span className="chip red">{d.why.join("; ")}</span>}
        {d.checked && <span className="chip green">Checked before</span>}
      </div>
      <div className="pc-grid">
        <div className="pc-col">
          <div className="pc-lbl">Figures saved{d.source && !d.source.startsWith("pdf:") ? ` (now ${d.source === "manual" ? "yours" : d.source})` : ""}</div>
          {shownFields.map((k) => (
            <div key={k} className={`pc-fig ${sel === k ? "on" : ""} ${changed.includes(k) ? "edited" : ""}`} onClick={() => setSel(k)}>
              <span className="n">{FIG_LABEL[k]}{d.lines[k] ? "" : <span className="faint" title="Not from this reading (another filing, or saved by you)"> ·</span>}</span>
              <input value={vals[k] ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} onFocus={() => setSel(k)} inputMode="numeric" />
            </div>
          ))}
          <div className="pc-acts">
            <button className="btn primary" disabled={busy || !changed.length || bad.length > 0} onClick={() => save(false)}>Save corrections{changed.length ? ` (${changed.length})` : ""}</button>
            <button className="btn" disabled={busy || changed.length > 0} onClick={() => save(true)}>It's all right</button>
          </div>
          {bad.length > 0 && <div className="small" style={{ color: "var(--red)" }}>Not a number: {bad.map((k) => FIG_LABEL[k]).join(", ")}</div>}
          {msg && <div className="small pos" style={{ marginTop: 6 }}>{msg}</div>}
          <p className="faint small">Corrections are saved as yours, so a later re-read never replaces them. Clear a box to remove a wrong figure.</p>
        </div>
        <div className="pc-col">
          <div className="pc-lbl">What the reader saw{!d.full && d.text ? " (key lines only: read before full text was kept)" : ""}</div>
          {!d.text ? <div className="faint small">No text stored for this year.</div> : (
            <pre className="pc-text">{pages.filter((p) => p.text.trim()).map((p, i) => (
              <Fragment key={i}>{p.n !== null && <span className="pg">Page {p.n}</span>}
                {p.text.split("\n").map((l, j) => selLine && norm(l) === norm(selLine)
                  ? <mark key={j} ref={(el) => el?.scrollIntoView({ block: "center", behavior: "smooth" })}>{l + "\n"}</mark>
                  : <Fragment key={j}>{l + "\n"}</Fragment>)}
              </Fragment>))}</pre>
          )}
          {sel && !selLine && <div className="faint small">{FIG_LABEL[sel]} didn't come from this reading.</div>}
        </div>
        <div className="pc-col">
          <div className="pc-lbl">The PDF from Companies House{pageOf ? ` · page ${pageOf}` : ""}
            {pdf?.url && <a className="small" style={{ marginLeft: 8, textTransform: "none", letterSpacing: 0 }} href={pdf.url} target="_blank" rel="noreferrer">Open full PDF ↗</a>}</div>
          {!pdfUrl ? <div className="faint small">No PDF for this year.</div>
            : !pdf ? <div className="faint small">Fetching the PDF from Companies House…</div>
            : pdf.err ? <div className="faint small">{pdf.err} <a href={`https://find-and-update.company-information.service.gov.uk/company/${num}/filing-history`} target="_blank" rel="noreferrer">Filing history ↗</a></div>
            : <iframe key={pageOf ?? 0} className="pc-pdf" title="Accounts PDF" src={`${pdf.url}#page=${pageOf ?? 1}&view=FitH`} />}
        </div>
      </div>
    </div>
  );
}

function PdfFailures({ count, onRetried }: { count: number; onRetried: (s: PdfRead) => void }) {
  const [rows, setRows] = useState<PdfFailure[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (!count) return null;
  const why = (r: PdfFailure) => r.note ?? (r.status === "nothing_found" ? (r.method === "ocr" ? "scanned: no labelled figures could be made out" : "no labelled figures found") : "failed");
  return (
    <details style={{ marginTop: 8 }} onToggle={(e) => { if ((e.target as HTMLDetailsElement).open && !rows) api.pdfFailures().then(setRows); }}>
      <summary className="small" style={{ cursor: "pointer" }}>Which couldn't be read, and why</summary>
      <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
        <button className="btn quiet" onClick={async () => { onRetried(await api.pdfRetry()); setRows([]); }}>Try them all again</button>
        <span className="faint small" style={{ alignSelf: "center" }}>Each is tried up to 3 times, and again whenever the reader improves.</span>
      </div>
      {!rows ? <div className="faint small">Loading…</div> : (
        <table className="small">
          <thead><tr><th>Company</th><th>Year end</th><th>How</th><th>Why</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => {
              const k = `${r.company_number}-${r.made_up}`;
              return (
                <Fragment key={k}>
                  <tr>
                    <td><Link to={`/c/${r.company_number}`}>{r.name}</Link></td>
                    <td className="nowrap">{String(r.made_up).slice(0, 10)}</td>
                    <td>{r.method === "ocr" ? "OCR (scanned)" : r.method === "text" ? "Text" : "—"}</td>
                    <td>{why(r)}{r.tries > 1 ? <span className="faint"> · tried {r.tries}×</span> : null}</td>
                    <td className="nowrap">
                      {r.sample && <button className="linkish small" onClick={() => setOpen(open === k ? null : k)}>{open === k ? "Hide" : "What was read"}</button>}{" "}
                      <a className="small" href={`https://find-and-update.company-information.service.gov.uk/company/${r.company_number}/filing-history`} target="_blank" rel="noreferrer">PDF ↗</a>{" "}
                      <button className="linkish small" title="Checked: nothing to read here. Takes it off this list for good." onClick={async () => {
                        const why = prompt(`Close ${r.name}, year to ${String(r.made_up).slice(0, 10)}? Why (e.g. dormant, no profit and loss, illegible)?`);
                        if (!why?.trim()) return;
                        onRetried(await api.pdfClose(r.company_number, String(r.made_up).slice(0, 10), why.trim()));
                        setRows((xs) => (xs ?? []).filter((x) => x !== r));
                      }}>Close</button>
                    </td>
                  </tr>
                  {open === k && <tr><td colSpan={5}><pre className="pdfsample">{r.sample}</pre></td></tr>}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </details>
  );
}

function ChSyncPanel() {
  const [st, setSt] = useState<ChSync | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.chSync().then((d) => { if (live) { setSt(d); setErr(null); } }).catch((e) => live && setErr(e.message));
    load();
    const t = setInterval(load, 30_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const toggle = async () => {
    if (!st) return;
    try { setSt(await api.chSyncSet(!st.paused)); } catch (e: any) { setErr(e.message); }
  };
  if (!st) return err ? <ErrorLine error={err} /> : null;
  const state = !st.enabled ? ["Needs CH_API_KEY", ""] : st.paused ? ["Paused", ""]
    : st.running && st.state === "no API key" ? ["No key on scheduler", "red"]
    : !st.running ? ["Not running", "red"] : st.state === "up to date" ? ["Up to date", "green"]
    : st.state === "waiting for a data load" ? ["Waiting for the data load", ""] : ["Running", "green"];
  const bar = (x: { total: number; fetched: number; current: number }, label: string, every: string) => (
    <div>
      <div className="small"><b>{label}</b> · {int(x.fetched)} of {int(x.total)} fetched</div>
      <div className="syncbar"><i style={{ width: `${x.total ? Math.min(100, (100 * x.fetched) / x.total) : 0}%` }} /></div>
      <div className="faint small">{int(x.current)} checked in the last {every}</div>
    </div>
  );
  return (
    <section>
      <div className="sechead"><h2>Companies House sync</h2>
        <span className={`chip ${state[1]}`}>{state[0]}</span>
        {st.enabled && <button className="btn quiet" style={{ marginLeft: "auto" }} onClick={toggle}>{st.paused ? "Resume" : "Pause"}</button>}</div>
      {!st.enabled ? (
        <p className="faint">Add your key as <code>CH_API_KEY</code> to the app and scheduler in the stack.</p>
      ) : (
        <>
          <div className="syncgrid">
            {bar(st.pipeline, "Pipeline", `${st.pipeline_days} days`)}
            {bar(st.targets, "Buy-box targets", `${st.target_days} days`)}
          </div>
          <p className="small" style={{ margin: 0 }}>
            Last 24 hours: <b>{int(st.last_24h.fetched)}</b> fetched, <b>{int(st.last_24h.checked)}</b> checked
            {" · "}<Link to="/changes">{int(st.changes_7d)} changes found this week</Link>
            {st.per_hour ? <> · {int(st.per_hour)} an hour</> : null}
            {st.days_to_cover ? <> · about {st.days_to_cover < 1 ? "a day" : `${Math.ceil(st.days_to_cover)} days`} to cover every target</> : null}
          </p>
          {st.running && st.state === "no API key" ? (
            <div className="callout red" style={{ marginTop: 8 }}>The scheduler has no <code>CH_API_KEY</code>. Add it to the scheduler in the stack, then update the stack.</div>
          ) : !st.running && !st.paused ? (
            <div className="callout red" style={{ marginTop: 8 }}>
              {st.last_beat ? <>The scheduler last reported {dateTime(st.last_beat)}. Check it's running.</>
                : <>The scheduler hasn't started the sync. It's probably on an older version: update the stack with “Re-pull image and redeploy” on.</>}
            </div>
          ) : null}
          <StreamLine s={st.stream} />
          <p className="faint small">Pipeline checked weekly, targets every {st.target_days} days, profiles when you open them.</p>
        </>
      )}
    </section>
  );
}


function WebsiteBatch() {
  const [msg, setMsg] = useState<string | null>(null);
  const sum = useAsync(() => api.websiteSummary(), []);
  useEffect(() => { const t = setInterval(() => sum.reload(), 30_000); return () => clearInterval(t); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async (scope: string, limit: number) => {
    setMsg(null);
    try { await api.websiteCheck(scope, limit); setMsg("Started. Progress shows at the top."); } catch (e: any) { setMsg(e.message); }
  };
  return (
    <section>
      <div className="sechead"><h2>Find websites</h2><span className="faint small">Companies without one yet</span></div>
      {sum.data && sum.data.checked > 0 && (
        <div className="factline" style={{ borderTop: 0, marginBottom: 8 }}>
          <div><b>{int(sum.data.confirmed)}</b><span>Confirmed</span></div>
          <div><b>{int(sum.data.possible)}</b><span>Possible, to check</span></div>
          <div><b>{int(sum.data.none)}</b><span>No site found</span></div>
          <div><b>{int(sum.data.with_website)}</b><span>Companies with a website <Link to="/targets?has_website=true">view</Link></span></div>
        </div>
      )}
      <p className="small" style={{ marginTop: 0 }}>
        Saved only when the site shows <b>both the company number and the registered name</b> (with Ltd or Limited).
        Office addresses on the site are saved too. Weaker matches are noted as "possible" on the company for you to check.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn" onClick={() => run("pipeline", 0)}>My pipeline</button>
        <button className="btn" onClick={() => run("targets", 200)}>Top 200 targets</button>
      </div>
      <h3 className="subh" style={{ marginTop: 14 }}>One-off setup</h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn primary" onClick={() => confirm("Check every buy-box target without a website? It runs in the background, 8 at a time, for roughly a day. You can stop it and it carries on later.") && run("targets", 0)}>
          All buy-box targets (about a day)</button>
        <button className="btn quiet" onClick={() => confirm("Check every active company with 10 or more staff? This can take several days. You can stop it and it carries on later.") && run("active", 0)}>
          All active companies with 10+ staff (several days)</button>
      </div>
      <p className="faint small">Stop it from the bar at the top; it resumes where it stopped.</p>
      {msg && <div className="faint small" style={{ marginTop: 8 }}>{msg}</div>}
    </section>
  );
}


function LogoBatch() {
  const [msg, setMsg] = useState<string | null>(null);
  const sum = useAsync(() => api.logoSummary(), []);
  useEffect(() => { const t = setInterval(() => sum.reload(), 30_000); return () => clearInterval(t); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const d = sum.data;
  return (
    <section>
      <div className="sechead"><h2>Logos</h2><span className="faint small">From each company's own website</span></div>
      {d && (
        <div className="factline" style={{ borderTop: 0, marginBottom: 8 }}>
          <div><b>{int(d.found)}</b><span>Found</span></div>
          <div><b>{int(d.none)}</b><span>None usable</span></div>
          <div><b>{int(d.not_tried)}</b><span>Not looked for yet</span></div>
          <div><b>{int(d.yours)}</b><span>Set or removed by you</span></div>
        </div>
      )}
      <p className="small" style={{ marginTop: 0 }}>
        Logos are looked for when a company is first shown. To fill them all in now, look for every missing one
        (four websites at a time, in the background). Fix any single logo by clicking it on the company page.
      </p>
      <button className="btn" disabled={!d || d.not_tried === 0} onClick={async () => {
        setMsg(null);
        try { await api.findLogos(); setMsg("Started. Progress shows at the top."); } catch (e: any) { setMsg(e.message); }
      }}>{d && d.not_tried === 0 ? "Nothing to look for" : `Look for ${d ? int(d.not_tried) : ""} missing logos`}</button>
      {d && d.reasons.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary className="small">Why {int(d.none)} have no logo</summary>
          <table className="small" style={{ marginTop: 6 }}><tbody>
            {d.reasons.map((r) => <tr key={r.note}><td>{r.note}</td><td className="num">{int(r.n)}</td></tr>)}
          </tbody></table>
        </details>
      )}
      {msg && <div className="faint small" style={{ marginTop: 8 }}>{msg}</div>}
    </section>
  );
}


const GAP_REASONS: [string, string][] = [
  ["not_checked", "Not checked with Companies House since the newer accounts were filed"],
  ["pdf_waiting", "Filed as PDF, waiting for the PDF reader"],
  ["pdf_unreadable", "Filed as PDF, couldn't be read"],
  ["no_document", "No readable document at Companies House"],
];

function AccountsGaps() {
  const [msg, setMsg] = useState<string | null>(null);
  const g = useAsync(() => api.accountsGaps(), []);
  const d = g.data;
  const fixable = d?.by_reason["not_checked"] ?? 0;
  return (
    <section>
      <div className="sechead"><h2>Missing accounts years</h2><span className="faint small">Your buy boxes and pipeline</span></div>
      <p className="small" style={{ marginTop: 0 }}>
        Companies whose latest accounts at Companies House are much newer than the latest year held here (e.g. nothing since 2020
        though they file every year). Usually newer years were filed as PDF, or in a monthly file that didn't load, and the company
        hasn't been checked since.
      </p>
      {d && (d.total === 0 ? <div className="faint small">None: every company's figures are up to date with its filings.</div> : <>
        <table className="small"><tbody>
          {GAP_REASONS.filter(([k]) => d.by_reason[k]).map(([k, l]) => <tr key={k}><td>{l}</td><td className="num"><b>{int(d.by_reason[k])}</b></td></tr>)}
        </tbody></table>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
          <button className="btn primary" disabled={!fixable} onClick={async () => {
            setMsg(null);
            try { await api.fillAccountsGaps(); setMsg("Started. Progress shows at the top; PDF-only years then go to the PDF reader."); }
            catch (e: any) { setMsg(e.message); }
          }}>{fixable ? `Check ${int(Math.min(fixable, 300))} with Companies House` : "Nothing to check"}</button>
          <span className="faint small">Up to 300 a run, pipeline first, then best scores. Needs your Companies House key.</span>
        </div>
        <details style={{ marginTop: 10 }}>
          <summary className="small">Show the companies</summary>
          <table className="small" style={{ marginTop: 6 }}>
            <thead><tr><th>Company</th><th>Latest filed</th><th>Latest held</th><th>Why</th></tr></thead>
            <tbody>{d.examples.map((r) => (
              <tr key={r.company_number}>
                <td><Link to={`/c/${r.company_number}`}>{r.name}</Link></td>
                <td className="nowrap">{date(r.last_accounts_date)}</td>
                <td className="nowrap">{r.latest_held ? date(r.latest_held) : "none"}</td>
                <td className="faint">{GAP_REASONS.find(([k]) => k === r.reason)?.[1] ?? r.why}</td>
              </tr>))}</tbody>
          </table>
          {d.total > d.examples.length && <div className="faint small">and {int(d.total - d.examples.length)} more</div>}
        </details>
      </>)}
      {msg && <div className="faint small" style={{ marginTop: 8 }}>{msg}</div>}
    </section>
  );
}
