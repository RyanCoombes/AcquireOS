/* Connection map: the chosen company in the middle, linked companies in
   rings around it. A plain radial layout, so it reads the same every time. */
import { useNavigate } from "react-router-dom";
import type { GEdge, GNode } from "../api";

const W = 1000, H = 560;

export default function Graph({ nodes, edges, root }: { nodes: GNode[]; edges: GEdge[]; root: string }) {
  const nav = useNavigate();
  const pos = new Map<string, { x: number; y: number }>();
  const cx = W / 2, cy = H / 2;
  pos.set(root, { x: cx, y: cy });
  const rings = [1, 2, 3].map((d) => nodes.filter((n) => n.depth === d));
  rings.forEach((ring, i) => {
    const r = [0, 190, 330, 430][i + 1];
    ring.forEach((n, j) => {
      const a = (2 * Math.PI * j) / Math.max(ring.length, 1) + Math.PI + i * 0.35;
      pos.set(n.id, { x: cx + r * 1.55 * Math.cos(a), y: cy + r * 0.62 * Math.sin(a) });
    });
  });

  return (
    <svg className="graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Connection map">
      {edges.map((e, i) => {
        const a = pos.get(e.source), b = pos.get(e.target);
        if (!a || !b) return null;
        return (
          <line key={i} className={`edge ${e.kind} ${e.confidence}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}>
            <title>{`${e.evidence}${e.via ? ` (${e.via})` : ""}`}</title>
          </line>
        );
      })}
      {nodes.map((n) => {
        const p = pos.get(n.id);
        if (!p) return null;
        const label = n.name.length > 30 ? n.name.slice(0, 29) + "…" : n.name;
        const w = Math.max(90, label.length * 7.6 + 22);
        return (
          <g key={n.id} className={`node ${n.id === root ? "root" : ""} ${n.in_list ? "" : "outside"}`}
             transform={`translate(${p.x - w / 2},${p.y - 15})`}
             onClick={() => n.in_list && nav(`/c/${n.id}`)}>
            <rect width={w} height={30} rx={1} />
            <text x={w / 2} y={19} textAnchor="middle">{label}</text>
            <title>{`${n.name} · ${n.id}${n.in_list ? "" : " · not in your list"}`}</title>
          </g>
        );
      })}
    </svg>
  );
}
