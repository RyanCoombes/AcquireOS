import type React from "react";
import { useEffect, useRef, useState } from "react";
import { duration, elapsed, useJob } from "../components/JobBar";
import { Link } from "react-router-dom";
import { api, type ChSync, type Preview } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import { dateTime, int } from "../format";

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
      <ChSyncPanel />
      <WebsiteBatch />

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
                    [36, "36 (about 4 years)"], [48, "48 (about 5 years)"], [60, "60 (about 6 years)"]].map(([m, l]) =>
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
        Runs itself monthly. 48 months of accounts ≈ 5 years of figures (1–2 GB a month). Loaded months are skipped.
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
      <p className="faint small">Directors are not in the free bulk files; Companies House only provides them company by company through its API.</p>
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
  const run = async (scope: string, limit: number) => {
    setMsg(null);
    try { await api.websiteCheck(scope, limit); setMsg("Started. Progress shows at the top."); } catch (e: any) { setMsg(e.message); }
  };
  return (
    <section>
      <div className="sechead"><h2>Find websites</h2><span className="faint small">Companies without one yet</span></div>
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
      <p className="faint small">Stop it from the progress bar at the top; running it again carries on where it stopped. Companies checked in the last six months are skipped.</p>
      {msg && <div className="faint small" style={{ marginTop: 8 }}>{msg}</div>}
    </section>
  );
}
