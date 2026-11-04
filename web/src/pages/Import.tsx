import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Preview } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import { dateTime } from "../format";

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
          <h1>Import</h1>
          <div className="lede">Bring in the data from your search. You will see how each column is read before anything is saved.</div>
        </div>
      </div>

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
          {result.changes ? <Link to="/changes?days=7">See what changed</Link> : <Link to="/">See targets</Link>}
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

      <section>
        <h2>Monthly refresh from Companies House</h2>
        <p className="muted" style={{ maxWidth: "75ch" }}>
          The free <a href="https://download.companieshouse.gov.uk/en_output.html" target="_blank" rel="noreferrer">basic company data file ↗</a> covers
          every UK company and is updated monthly. It is too large for the browser, so put it in the <code>data</code> folder and run the command
          below. It updates only companies already in your list and records what changed, including dissolutions and new accounts.
        </p>
        <pre className="cmd">docker exec -it acquireos sh -c 'acquireos import-companies --only-existing /data/BasicCompanyDataAsOneFile-*.zip'</pre>
      </section>

      <section>
        <h2>Owners: Companies House PSC snapshot</h2>
        <p className="muted" style={{ maxWidth: "75ch" }}>
          The free owner (PSC) snapshot is several gigabytes, too large to upload through a browser. Download it from{" "}
          <a href="https://download.companieshouse.gov.uk/en_pscdata.html" target="_blank" rel="noreferrer">Companies House ↗</a>,
          put the zip in the <code>data</code> folder on the server, then run:
        </p>
        <pre className="cmd">
docker exec -it acquireos sh -c 'acquireos import-psc /data/persons-with-significant-control-snapshot*.zip'</pre>
        <p className="muted small">It keeps only companies in your list, then follows parent companies to find the people behind them.</p>
      </section>

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
