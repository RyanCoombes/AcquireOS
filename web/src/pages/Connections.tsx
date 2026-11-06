import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import Graph from "../components/Graph";
import { LINK_KIND } from "../format";

export default function Connections() {
  const { num } = useParams();
  const nav = useNavigate();
  const [depth, setDepth] = useState(2);
  const [q, setQ] = useState("");
  const graph = useAsync(() => (num ? api.graph(num, depth) : Promise.resolve(null)), [num, depth]);
  const hits = useAsync(() => (q.length > 1 ? api.companies({ q, limit: "8", include_excluded: "true" }) : Promise.resolve(null)), [q]);
  const root = graph.data?.nodes.find((n) => n.id === num);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connections</h1>
          <div className="lede">
            Linked by ownership, a shared owner or a shared address.
          </div>
        </div>
      </div>
      <div className="band">
        <div className="field" style={{ position: "relative" }}>
          <label htmlFor="c-q">Company</label>
          <input id="c-q" type="search" style={{ width: 320 }} placeholder={root?.name ?? "Find a company"} value={q} onChange={(e) => setQ(e.target.value)} />
          {hits.data && q.length > 1 && (
            <div style={{ position: "absolute", top: 54, left: 0, right: 0, background: "var(--paper)", border: "1px solid var(--ink)", zIndex: 30 }}>
              {hits.data.rows.map((r) => (
                <div key={r.company_number} style={{ padding: "6px 10px", cursor: "pointer", borderBottom: "1px solid var(--rule)" }}
                     onClick={() => { setQ(""); nav(`/connections/${r.company_number}`); }}>
                  {r.name} <span className="faint small">{r.company_number}</span>
                </div>
              ))}
              {!hits.data.rows.length && <div style={{ padding: "6px 10px" }} className="faint">No match</div>}
            </div>
          )}
        </div>
        <div className="field">
          <label>Reach</label>
          <div className="seg">
            {[1, 2, 3].map((d) => <button key={d} className={depth === d ? "on" : ""} onClick={() => setDepth(d)}>{d} step{d > 1 ? "s" : ""}</button>)}
          </div>
        </div>
        {num && <Link className="btn" to={`/c/${num}`} style={{ alignSelf: "flex-end" }}>Open company</Link>}
      </div>

      <ErrorLine error={graph.error} />
      {!num && <div className="empty"><b>Choose a company</b> to see what it is connected to.</div>}
      {graph.data && num && (
        graph.data.edges.length ? (
          <>
            <div className="legend">
              <span><i />Ownership</span><span><i className="g" />Same owner</span><span><i className="d" />Same address, or a possible match</span>
              <span>Dashed box: company outside your list</span><span>Click a box to open it</span>
            </div>
            <Graph nodes={graph.data.nodes} edges={graph.data.edges} root={num} />
            <table style={{ marginTop: 16 }}>
              <thead><tr><th>From</th><th>To</th><th>Link</th><th>Confidence</th><th className="hide-sm">Evidence</th></tr></thead>
              <tbody>
                {graph.data.edges.map((e, i) => {
                  const name = (id: string) => graph.data!.nodes.find((n) => n.id === id)?.name ?? id;
                  return (
                    <tr key={i}>
                      <td>{name(e.source)}</td><td>{name(e.target)}</td>
                      <td>{LINK_KIND[e.kind]}{e.via ? <div className="sub">{e.via}</div> : null}</td>
                      <td>{e.confidence}</td>
                      <td className="muted small hide-sm">{e.evidence}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        ) : <div className="empty"><b>No connections found</b> for {root?.name}. Importing the PSC snapshot adds ownership links.</div>
      )}
    </>
  );
}
