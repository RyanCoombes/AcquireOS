/* Connections: companies and people in one network. Start from a company or
   a person, then open any node to see what it connects to. */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine } from "../components/bits";
import Network, { KIND, nice, type NEdge, type NNode } from "../components/Network";

export default function Connections() {
  const { num, nid } = useParams();
  const start = nid ? decodeURIComponent(nid) : num ? `c:${num.toUpperCase()}` : null;
  const nav = useNavigate();
  const [nodes, setNodes] = useState<NNode[]>([]);
  const [edges, setEdges] = useState<NEdge[]>([]);
  const [root, setRoot] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [former, setFormer] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const merge = (r: { nodes: NNode[]; edges: NEdge[] }, base = { nodes, edges }) => {
    const nm = new Map(base.nodes.map((n) => [n.id, n]));
    for (const n of r.nodes) nm.set(n.id, { ...nm.get(n.id), ...n });
    const key = (e: NEdge) => `${e.source}|${e.target}|${e.kind}`;
    const em = new Map(base.edges.map((e) => [key(e), e]));
    for (const e of r.edges) em.set(key(e), e);
    return { nodes: [...nm.values()], edges: [...em.values()] };
  };

  // Start (or restart) from the node in the address.
  useEffect(() => {
    if (!start) return;
    setErr(null); setBusy(true);
    api.network(start, former).then((r) => {
      const id = r.node!.id;
      setNodes(r.nodes); setEdges(r.edges); setRoot(id); setExpanded(new Set([id])); setSelected(id);
    }).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  }, [start, former]); // eslint-disable-line react-hooks/exhaustive-deps

  const expand = async (id: string) => {
    if (expanded.has(id)) return;
    setBusy(true);
    try {
      const r = await api.network(id, former);
      const m = merge(r);
      setNodes(m.nodes); setEdges(m.edges); setExpanded(new Set([...expanded, id]));
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const hide = (id: string) => {
    if (id === root) return;
    // Remove the node and anything only reachable through it.
    const keepEdges = edges.filter((e) => e.source !== id && e.target !== id);
    const reach = new Set<string>([root!]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const e of keepEdges) {
        if (reach.has(e.source) && !reach.has(e.target)) { reach.add(e.target); grew = true; }
        if (reach.has(e.target) && !reach.has(e.source)) { reach.add(e.source); grew = true; }
      }
    }
    setNodes(nodes.filter((n) => reach.has(n.id)));
    setEdges(keepEdges.filter((e) => reach.has(e.source) && reach.has(e.target)));
    setSelected(root);
  };

  const sel = nodes.find((n) => n.id === selected) ?? null;
  const selEdges = sel ? edges.filter((e) => e.source === sel.id || e.target === sel.id) : [];
  const nameOf = (id: string) => nice(nodes.find((n) => n.id === id)?.name ?? id);

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connections</h1>
          <div className="lede">Companies and people: owners, directors, group companies and shared owners. Double-click (or Open) to see what a node connects to.</div>
        </div>
        {root && <div className="right">
          <label className="check small"><input type="checkbox" checked={former} onChange={(e) => setFormer(e.target.checked)} /> Include former owners and directors</label>
          {root.startsWith("c:") && <Link className="btn" to={`/map?focus=${encodeURIComponent(root)}`}>Show on map</Link>}
        </div>}
      </div>
      <FindStart onPick={(id) => nav(`/connections/n/${encodeURIComponent(id)}`)} />
      <ErrorLine error={err} />
      {!start && <div className="empty"><b>Choose a company or a person</b> to see who and what they are connected to.</div>}
      {start && root && (
        <div className="net-wrap">
          <div className="net-canvas">
            <Network nodes={nodes} edges={edges} root={root} selected={selected} expanded={expanded}
                     onSelect={setSelected} onExpand={expand} />
            <div className="net-legend">
              <span><i className="lg owns" />Owns</span><span><i className="lg director" />Director</span>
              <span><i className="lg group" />Group</span><span><i className="lg same_owner" />Same owner</span>
              <span><i className="lg same_address" />Same address</span>
              <span><b>+</b> not opened yet</span><span className="faint">Scroll to zoom, drag to move</span>
              {busy && <span className="faint">Loading…</span>}
            </div>
          </div>
          <aside className="net-side">
            {sel ? (
              <>
                <div className="label">{sel.type === "company" ? "Company" : sel.owner && sel.director ? "Owner and director" : sel.owner ? "Owner" : "Director"}</div>
                <h2 style={{ margin: "2px 0 6px" }}>{nice(sel.name)}</h2>
                <div className="faint small" style={{ marginBottom: 10 }}>
                  {sel.type === "company"
                    ? <>{sel.number}{sel.status ? ` · ${sel.status}` : ""}{sel.region ? ` · ${sel.region}` : ""}{sel.score != null ? ` · score ${Math.round(sel.score)}` : ""}{sel.in_list === false ? " · not in your data" : ""}</>
                    : <>{sel.birth_year ? `Born ${sel.birth_year} · about ${new Date().getFullYear() - sel.birth_year}` : "Age not known"}</>}
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                  {!expanded.has(sel.id) && <button className="btn primary" onClick={() => expand(sel.id)}>Open connections</button>}
                  {sel.type === "company" && sel.in_list !== false && <Link className="btn" to={`/c/${sel.number}`}>Company page</Link>}
                  {sel.type === "person" && sel.id.startsWith("p:") && <Link className="btn" to={`/owners/${sel.id.slice(2)}`}>Owner page</Link>}
                  {sel.id !== root && <button className="btn quiet" onClick={() => nav(`/connections/n/${encodeURIComponent(sel.id)}`)}>Start from here</button>}
                  {sel.id !== root && <button className="btn quiet" onClick={() => hide(sel.id)}>Hide</button>}
                </div>
                <div className="label">Links shown ({selEdges.length})</div>
                <ul className="net-links">
                  {selEdges.map((e, i) => {
                    const other = e.source === sel.id ? e.target : e.source;
                    const dir = e.kind === "owns" ? (e.source === sel.id ? "owns" : "owned by") : e.kind === "director" ? (e.source === sel.id ? "director of" : "director") : KIND[e.kind].toLowerCase();
                    return (
                      <li key={i} className={e.current ? "" : "former"} onClick={() => setSelected(other)}>
                        <span className={`lg ${e.kind}`} /> <span className="faint">{dir}</span> {nameOf(other)}
                        {e.label && e.kind !== "director" ? <span className="faint"> · {e.label}</span> : null}{e.current ? "" : <span className="faint"> · former</span>}
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : <div className="faint">Click a node.</div>}
          </aside>
        </div>
      )}
    </>
  );
}

/** Find a company or a person to start from. */
function FindStart({ onPick }: { onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ id: string; name: string; sub: string }[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    let live = true;
    const t = setTimeout(async () => {
      const [cos, ppl] = await Promise.all([
        api.companies({ q, limit: "6", include_excluded: "true", count: "false" }).catch(() => ({ rows: [] as any[] })),
        api.owners(q).catch(() => ({ rows: [] as any[] })),
      ]);
      if (!live) return;
      setHits([
        ...cos.rows.map((r: any) => ({ id: `c:${r.company_number}`, name: r.name, sub: `Company · ${r.company_number}` })),
        ...ppl.rows.slice(0, 6).map((p: any) => ({ id: `p:${p.id}`, name: p.name, sub: `${p.kind === "individual" ? "Person" : "Corporate owner"} · ${p.companies} ${p.companies === 1 ? "company" : "companies"}${p.birth_year ? ` · born ${p.birth_year}` : ""}` })),
      ]);
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  return (
    <div className="band" style={{ position: "relative" }}>
      <div className="field" style={{ position: "relative", flex: 1, maxWidth: 520 }}>
        <label htmlFor="c-q">Start from a company or a person</label>
        <input id="c-q" type="search" placeholder="Company name or number, or a person's name" value={q} onChange={(e) => setQ(e.target.value)} />
        {hits.length > 0 && (
          <div className="net-hits">
            {hits.map((h) => (
              <div key={h.id} onClick={() => { setQ(""); setHits([]); onPick(h.id); }}>
                {nice(h.name)} <span className="faint small">{h.sub}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
