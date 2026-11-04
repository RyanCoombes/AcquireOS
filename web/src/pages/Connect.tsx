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
  const issues = useAsync(() => api.issues("open"), []);
  if (error) return <ErrorLine error={error} />;
  if (!data) return <div className="empty">Loading…</div>;
  const url = data.mcp_url;
  const tok = "YOUR_API_TOKEN";

  const desktop = JSON.stringify({
    mcpServers: {
      acquireos: {
        command: "npx",
        args: ["-y", "mcp-remote", url, "--allow-http", "--header", "Authorization:${AUTH}"],
        env: { AUTH: `Bearer ${tok}` },
      },
    },
  }, null, 2);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect Claude</h1>
          <div className="lede">
            AcquireOS has an MCP server, so Claude on your computer can search and analyse your targets, audit the data,
            and save researched enrichment (websites, business type, recurring revenue, field-service checks) with a source for every fact.
          </div>
        </div>
      </div>

      <div className="kpis" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
        <div className="kpi"><span className="k"><i />MCP endpoint</span><span className="v" style={{ fontSize: 15, wordBreak: "break-all" }}>{url}</span><span className="s">Streamable HTTP</span></div>
        <div className="kpi"><span className="k"><i style={{ background: data.token_set ? "#0e7c6b" : "#c8352b" }} />API token</span>
          <span className="v" style={{ fontSize: 20 }}>{data.token_set ? "Set" : "Not set"}</span>
          <span className="s">{data.token_set ? "Required on every call" : data.password_set ? "MCP is blocked until you set one" : "Anyone on your network can connect"}</span></div>
        <div className="kpi"><span className="k"><i style={{ background: "#2f62d8" }} />Companies enriched</span><span className="v">{int(data.enriched)}</span>
          <span className="s">{data.last_claude ? `Claude last saved ${dateTime(data.last_claude)}` : "Nothing from Claude yet"}</span></div>
        <div className="kpi"><span className="k"><i style={{ background: "#e0a245" }} />Open data issues</span><span className="v">{int(data.open_issues)}</span><span className="s">Raised while auditing</span></div>
      </div>

      {!data.token_set && (
        <div className="callout red">
          <b>Set an API token first.</b> In your Portainer stack, add <code>API_TOKEN</code> under environment variables (any long random string,
          or run <code>docker exec acquireos acquireos new-token</code>) and redeploy. Then replace <code>{tok}</code> below with it.
        </div>
      )}

      <section>
        <h2>Claude Desktop and Cowork</h2>
        <p className="muted" style={{ marginTop: 0, maxWidth: "80ch" }}>
          Your Pi is on your home network, so Claude reaches it through a small local bridge (<code>mcp-remote</code>, needs Node.js on your computer).
          In Claude Desktop open <b>Settings → Developer → Edit Config</b>, add this to <code>claude_desktop_config.json</code>, put your token in,
          save and restart Claude. Cowork uses the same tools.
        </p>
        <Copy text={desktop} />
        <p className="faint small">
          “Settings → Connectors → Add custom connector” only works for servers reachable over HTTPS from the internet. Use it later if you
          host AcquireOS publicly (behind HTTPS, with the token set).
        </p>
      </section>

      <section>
        <h2>Claude Code</h2>
        <Copy text={`claude mcp add --transport http acquireos ${url} --header "Authorization: Bearer ${tok}"`} />
      </section>

      <section>
        <h2>What Claude can do</h2>
        <table>
          <tbody>
            {[
              ["dataset_overview, search_companies, get_company, list_changes", "Answer questions: “owner-held MSPs in Wales with 20–60 staff and an owner over 60”."],
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
