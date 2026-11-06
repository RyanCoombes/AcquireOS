import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import { dateTime, int } from "../format";

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="copybox">
      <pre className="cmd">{text}</pre>
      <button className="btn" onClick={async () => {
        try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* blocked */ }
      }}>{done ? "Copied" : "Copy"}</button>
    </div>
  );
}

export default function Connect() {
  const { data, error } = useAsync(() => api.connect(), []);
  const [os, setOs] = useState<"windows" | "mac">(navigator.userAgent.includes("Windows") ? "windows" : "mac");
  const issues = useAsync(() => api.issues("open"), []);
  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const url = data.mcp_url;
  const tok = "YOUR_API_TOKEN";

  // No token set: anyone on your home network can connect, so no header is needed.
  const bridge = (windows: boolean) => {
    const args = ["-y", "mcp-remote", url, "--allow-http", ...(data.token_set ? ["--header", "Authorization:${AUTH}"] : [])];
    const entry: Record<string, unknown> = windows ? { command: "cmd", args: ["/c", "npx", ...args] } : { command: "npx", args };
    if (data.token_set) entry.env = { AUTH: `Bearer ${tok}` };
    return `"acquireos": ${JSON.stringify(entry, null, 2)}`;
  };

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect Claude</h1>
          <div className="lede">
            Let Claude search, analyse and enrich your companies.
          </div>
        </div>
      </div>

      <div className="kpis" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
        <div className="kpi"><span className="k"><i />MCP endpoint</span><span className="v" style={{ fontSize: 15, wordBreak: "break-all" }}>{url}</span><span className="s">Streamable HTTP</span></div>
        <div className="kpi"><span className="k"><i style={{ background: data.token_set ? "#0e7c6b" : "#8a919d" }} />API token</span>
          <span className="v" style={{ fontSize: 20 }}>{data.token_set ? "Set" : "Not set"}</span>
          <span className="s">{data.token_set ? "Required on every call" : data.password_set ? "MCP is blocked until you set one" : "Not needed on your home network"}</span></div>
        <div className="kpi"><span className="k"><i style={{ background: "#2f62d8" }} />Companies enriched</span><span className="v">{int(data.enriched)}</span>
          <span className="s">{data.last_claude ? `Claude last saved ${dateTime(data.last_claude)}` : "Nothing from Claude yet"}</span></div>
        <div className="kpi"><span className="k"><i style={{ background: "#e0a245" }} />Open data issues</span><span className="v">{int(data.open_issues)}</span><span className="s">Raised while auditing</span></div>
      </div>

      <section>
        <h2>Claude Desktop and Cowork</h2>
        <p className="muted" style={{ marginTop: 0, maxWidth: "80ch" }}>
          Your Pi is on your home network, so Claude reaches it through a small local bridge (<code>mcp-remote</code>, needs Node.js on your computer).
          In Claude Desktop open <b>Settings → Developer → Edit Config</b>. Inside <code>"mcpServers"</code>, add the entry below
          (with a comma after the entry before it), save, then quit Claude completely and reopen it. Cowork uses the same tools.
        </p>
        <div className="seg" style={{ display: "inline-flex", marginBottom: 8 }}>
          <button className={os === "windows" ? "on" : ""} onClick={() => setOs("windows")}>Windows</button>
          <button className={os === "mac" ? "on" : ""} onClick={() => setOs("mac")}>Mac</button>
        </div>
        <Copy text={bridge(os === "windows")} />
        {data.token_set
          ? <p className="faint small">Replace <code>{tok}</code> with the API_TOKEN from your stack.</p>
          : <p className="faint small">
              No API token is set, so none is needed: anything on your home network can connect, which is fine while AcquireOS
              is only reachable at home. If you ever open it to the internet, add <code>API_TOKEN</code> to the stack first
              (any long random string); this page then shows the config with the token in.
            </p>}
      </section>

      <section>
        <h2>Claude Code</h2>
        <Copy text={`claude mcp add --transport http acquireos ${url}${data.token_set ? ` --header "Authorization: Bearer ${tok}"` : ""}`} />
      </section>

      <section>
        <h2>What Claude can do</h2>
        <table>
          <tbody>
            {[
              ["dataset_overview, list_targets, search_companies, get_company, list_changes", "Answer questions: “owner-held MSPs in Wales with 20–60 staff and an owner over 60”."],
              ["get_financials, compare_companies", "Each figure's trend year on year (assets, liabilities, debt ratio, cash, staff), and companies side by side."],
              ["search_owners, get_owner", "Find an owner by name and everything they control, directly or through holding companies."],
              ["get_charges_and_investment", "Who holds each charge, share issues and investor owners (charge holders and share issues need your Companies House key)."],
              ["research_brief, check_website, find_website", "Every name the company may trade under, its owners and search queries; then a website is saved only when its company number or postcode is on it."],
              ["list_pipeline, set_next_action, log_outreach", "Your pipeline, next actions and outreach log. Writes only when you ask."],
              ["describe_database, query_database", "Read-only SQL over everything, for audits and one-off analysis (15 second limit, 500 rows)."],
              ["audit_queue", "Companies missing a website, research, owners, filed turnover or a field-service check; or with a SIC code that doesn't match the name. Pipeline first, then by score."],
              ["save_enrichment", "Saves website, business type, recurring revenue, field service and a summary. A source link is required; the company is rescored straight away."],
              ["flag_data_issue, list_data_issues, resolve_data_issue", "Records problems for you to review, such as a wrong SIC code or a suspect owner link."],
              ["add_note, set_status", "Writes to your own notes and pipeline, labelled as Claude. Only when you ask."],
            ].map(([t, d]) => <tr key={t}><td style={{ width: "34%" }}><code>{t}</code></td><td className="muted">{d}</td></tr>)}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Try asking</h2>
        <Copy text={`Use the audit_and_enrich prompt from AcquireOS on my top 10 targets without a website.`} />
        <Copy text={`In AcquireOS, find the website for each of my top 20 targets: use research_brief, search the web, and confirm with check_website. Then summarise what each sells.`} />
        <Copy text={`Which of my AcquireOS targets show signs of outside investment? Refresh charges for the top 30 and list any investor owners, investor charge holders or share issues.`} />
        <Copy text={`Compare 01000001, 01000002 and 01000003 in AcquireOS: financial trends, owners, value and debt.`} />
        <Copy text={`From AcquireOS, which owner-held companies scoring over 70 have an owner aged 60+ and grew staff in the last two years? Show a table.`} />
        <Copy text={`Audit AcquireOS for companies whose SIC code doesn't match what their website says they do, and flag each one as a data issue.`} />
      </section>

      <section>
        <div className="sechead"><h2>Open data issues</h2></div>
        {issues.data?.length ? (
          <table>
            <thead><tr><th>Company</th><th>Issue</th><th>Suggested fix</th><th>Raised</th><th /></tr></thead>
            <tbody>
              {issues.data.map((i: any) => (
                <tr key={i.id}>
                  <td>{i.company_number ? <Link to={`/c/${i.company_number}`}>{i.name ?? i.company_number}</Link> : "Dataset"}</td>
                  <td><b>{i.issue}</b>{i.detail && <div className="sub">{i.detail}</div>}</td>
                  <td className="muted">{i.suggested_fix}</td>
                  <td className="faint small nowrap">{dateTime(i.created_at)}<div>{i.created_by}</div></td>
                  <td className="nowrap">
                    <button className="btn quiet" onClick={async () => { await api.resolveIssue(i.id, "resolved", "Done"); issues.reload(); }}>Resolve</button>
                    <button className="btn quiet" onClick={async () => { await api.resolveIssue(i.id, "dismissed", "Not an issue"); issues.reload(); }}>Dismiss</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="faint">No open issues.</div>}
      </section>

      <section>
        <h2>REST API</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Everything in the app is also available as a JSON API for your own scripts, with the same token
          (<code>Authorization: Bearer …</code>). Interactive documentation: <a href="/docs" target="_blank" rel="noreferrer">/docs</a>.
        </p>
      </section>
    </>
  );
}
