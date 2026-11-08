/* The map, focused on one company: its registered office and offices, and on
   request its group and same-owner companies and its people's other companies. */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import MapView, { type MapLink, type MapPoint } from "./MapView";
import { nice, type NEdge, type NNode } from "./Network";
import { cap } from "../format";

type Net = { nodes: NNode[]; edges: NEdge[] };

export default function MapFocus({ num, tiles, attribution, onFocus, onClose }: {
  num: string; tiles: string; attribution: string; onFocus: (num: string) => void; onClose: () => void;
}) {
  const [co, setCo] = useState<CompanyDetail | null>(null);
  const [net, setNet] = useState<Net | null>(null);
  const [people, setPeople] = useState<Record<string, Net>>({});
  const [show, setShow] = useState({ offices: true, linked: false, people: false });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setCo(null); setNet(null); setPeople({}); setErr(null);
    api.company(num).then(setCo).catch((e) => setErr(e.message));
    api.network(`c:${num}`).then((r) => setNet({ nodes: r.nodes, edges: r.edges })).catch(() => {});
  }, [num]);

  // People's other companies: fetched when that layer is switched on.
  const persons = (net?.nodes ?? []).filter((n) => n.type === "person");
  useEffect(() => {
    if (!show.people) return;
    for (const p of persons) {
      if (people[p.id]) continue;
      api.network(p.id).then((r) => setPeople((x) => ({ ...x, [p.id]: { nodes: r.nodes, edges: r.edges } }))).catch(() => {});
    }
  }, [show.people, net]); // eslint-disable-line react-hooks/exhaustive-deps

  const { points, links, counts } = useMemo(() => {
    const pts: MapPoint[] = [], lns: MapLink[] = [];
    const counts = { offices: 0, linked: 0, people: 0, unplaced: 0 };
    if (!co) return { points: pts, links: lns, counts };
    const c = co.company;
    const home = co.geo ? [co.geo.lat, co.geo.lon] as [number, number] : null;
    if (home) pts.push({ company_number: c.company_number, name: nice(c.name), lat: home[0], lon: home[1], focus: true, size: 10,
                         label: `${c.postcode} · registered office` });
    if (show.offices) {
      for (const l of co.enrichment?.locations ?? []) {
        if (l.lat == null || l.lon == null || l.postcode === c.postcode) continue;
        counts.offices++;
        pts.push({ company_number: c.company_number, name: `${nice(c.name)}: ${l.name ?? cap(l.kind)}`, lat: l.lat, lon: l.lon, colour: "#0e7c6b", size: 7,
                   label: `${l.postcode ?? ""} · ${l.kind}` });
        if (home) lns.push({ a: home, b: [l.lat, l.lon], kind: "office", label: `Office: ${l.postcode ?? ""}` });
      }
    }
    const seen = new Set([c.company_number]);
    if (show.linked && net) {
      for (const e of net.edges.filter((x) => ["group", "same_owner", "owns"].includes(x.kind))) {
        const otherId = e.source === `c:${c.company_number}` ? e.target : e.source;
        const n = net.nodes.find((x) => x.id === otherId);
        if (!n || n.type !== "company" || seen.has(n.number!)) continue;
        seen.add(n.number!);
        if (n.lat == null || n.lon == null) { counts.unplaced++; continue; }
        counts.linked++;
        pts.push({ company_number: n.number!, name: nice(n.name), lat: n.lat, lon: n.lon, colour: "#141820", size: 6,
                   label: e.kind === "group" ? "Group company" : e.kind === "owns" ? "Owner company" : "Same owner" });
        if (home) lns.push({ a: home, b: [n.lat, n.lon], kind: e.kind === "group" || e.kind === "owns" ? "owned_by" : "shared_owner",
                             label: `${e.kind === "group" ? "Group" : e.kind === "owns" ? "Owns it" : "Same owner"}: ${nice(n.name)}` });
      }
    }
    if (show.people) {
      for (const p of persons) {
        const pn = people[p.id];
        if (!pn) continue;
        for (const n of pn.nodes.filter((x) => x.type === "company")) {
          if (seen.has(n.number!)) continue;
          seen.add(n.number!);
          if (n.lat == null || n.lon == null) { counts.unplaced++; continue; }
          counts.people++;
          const role = pn.edges.find((e) => e.target === n.id)?.kind === "owns" ? "owns" : "director of";
          pts.push({ company_number: n.number!, name: nice(n.name), lat: n.lat, lon: n.lon, colour: "#2f62d8", size: 6,
                     label: `${nice(p.name)} ${role} it` });
          if (home) lns.push({ a: home, b: [n.lat, n.lon], kind: "person", label: `${nice(p.name)} ${role} ${nice(n.name)}` });
        }
      }
    }
    return { points: pts, links: lns, counts };
  }, [co, net, people, show]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (k: keyof typeof show) => setShow({ ...show, [k]: !show[k] });
  return (
    <>
      <div className="focusbar">
        <div>
          <div className="label">Focused on</div>
          <b>{co ? nice(co.company.name) : "…"}</b>
          {co && <span className="faint small"> · {co.company.company_number}{co.company.region ? ` · ${co.company.region}` : ""}</span>}
        </div>
        <label className={`fchk ${show.offices ? "on" : ""}`}><input type="checkbox" checked={show.offices} onChange={() => toggle("offices")} /><i style={{ background: "#0e7c6b" }} />Offices{show.offices && counts.offices ? ` (${counts.offices})` : ""}</label>
        <label className={`fchk ${show.linked ? "on" : ""}`}><input type="checkbox" checked={show.linked} onChange={() => toggle("linked")} /><i style={{ background: "#141820" }} />Group and same-owner companies{show.linked ? ` (${counts.linked})` : ""}</label>
        <label className={`fchk ${show.people ? "on" : ""}`}><input type="checkbox" checked={show.people} onChange={() => toggle("people")} /><i style={{ background: "#2f62d8" }} />Owners' and directors' other companies{show.people ? ` (${counts.people})` : ""}</label>
        <span className="focus-actions">
          <Link className="btn quiet" to={`/c/${num}`}>Company page</Link>
          <Link className="btn quiet" to={`/connections/${num}`}>Connections</Link>
          <button className="btn" onClick={onClose}>All companies</button>
        </span>
      </div>
      {err && <div className="callout red">{err}</div>}
      {co && !co.geo && <div className="callout">This company has no map location yet (its postcode hasn't been looked up).</div>}
      <section style={{ padding: 0, overflow: "hidden" }}>
        <MapView points={points} links={links} tiles={tiles} attribution={attribution} height={620}
                 onOpen={(n) => { if (n !== num) onFocus(n); }} />
      </section>
      <div className="legend">
        <span><b className="dotkey" style={{ background: "#141820" }} />This company / group</span>
        <span><b className="dotkey" style={{ background: "#0e7c6b" }} />Its offices</span>
        <span><b className="dotkey" style={{ background: "#2f62d8" }} />Its people's other companies</span>
        <span>Click a dot to focus on that company instead</span>
        {counts.unplaced > 0 && <span className="faint">{counts.unplaced} without a map location yet</span>}
      </div>
    </>
  );
}
