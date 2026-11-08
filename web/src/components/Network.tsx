/* A network of companies and people that grows as you open nodes. Simple
   force layout (no library): nodes push apart, links pull together, and nodes
   already placed stay roughly where they were when more are added. */
import { useEffect, useMemo, useRef, useState } from "react";

export type NNode = {
  id: string; type: "company" | "person"; name: string; number?: string; status?: string | null; region?: string | null;
  score?: number | null; my_status?: string; in_list?: boolean; kind?: string; birth_year?: number | null;
  owner?: boolean; director?: boolean; officer_key?: string | null; lat?: number | null; lon?: number | null;
};
export type NEdge = { source: string; target: string; kind: "owns" | "director" | "group" | "same_owner" | "same_address"; label?: string | null; current: boolean };

type P = { x: number; y: number; vx: number; vy: number; fixed?: boolean };
const W = 1100, H = 640;

export default function Network({ nodes, edges, root, selected, expanded, onSelect, onExpand }: {
  nodes: NNode[]; edges: NEdge[]; root: string; selected: string | null; expanded: Set<string>;
  onSelect: (id: string) => void; onExpand: (id: string) => void;
}) {
  const pos = useRef(new Map<string, P>());
  const [, setTick] = useState(0);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ sx: number; sy: number; vx: number; vy: number } | null>(null);

  // Place new nodes next to whatever they link to, then settle the layout.
  useEffect(() => {
    const P = pos.current;
    if (!P.has(root)) P.set(root, { x: W / 2, y: H / 2, vx: 0, vy: 0 });
    for (const n of nodes) {
      if (P.has(n.id)) continue;
      const e = edges.find((x) => (x.source === n.id && P.has(x.target)) || (x.target === n.id && P.has(x.source)));
      const anchor = e ? P.get(e.source === n.id ? e.target : e.source)! : { x: W / 2, y: H / 2 };
      const a = Math.random() * Math.PI * 2;
      P.set(n.id, { x: anchor.x + Math.cos(a) * 90, y: anchor.y + Math.sin(a) * 90, vx: 0, vy: 0 });
    }
    for (const id of [...P.keys()]) if (!nodes.some((n) => n.id === id)) P.delete(id);
    const list = nodes.map((n) => [n.id, P.get(n.id)!] as const);
    const idx = new Map(list.map(([id], i) => [id, i]));
    for (let it = 0; it < 260; it++) {
      const alpha = 1 - it / 260;
      for (let i = 0; i < list.length; i++) {
        const a = list[i][1];
        for (let j = i + 1; j < list.length; j++) {
          const b = list[j][1];
          let dx = a.x - b.x, dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = Math.random(); dy = Math.random(); d2 = 1; }
          const f = (9000 / d2) * alpha;
          const d = Math.sqrt(d2);
          a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
        }
      }
      for (const e of edges) {
        const i = idx.get(e.source), j = idx.get(e.target);
        if (i === undefined || j === undefined) continue;
        const a = list[i][1], b = list[j][1];
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
        const f = (d - 150) * 0.02 * alpha;
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
      for (const [id, p] of list) {
        p.vx += (W / 2 - p.x) * 0.002 * alpha; p.vy += (H / 2 - p.y) * 0.002 * alpha;
        if (id === root) { p.vx *= 0.3; p.vy *= 0.3; }
        p.x += Math.max(-20, Math.min(20, p.vx)); p.y += Math.max(-20, Math.min(20, p.vy));
        p.vx *= 0.55; p.vy *= 0.55;
      }
    }
    setTick((t) => t + 1);
  }, [nodes, edges, root]);

  const P = pos.current;
  const deg = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of edges) { m.set(e.source, (m.get(e.source) ?? 0) + 1); m.set(e.target, (m.get(e.target) ?? 0) + 1); }
    return m;
  }, [edges]);

  // Fit the view to the network (with room for labels), keeping the canvas shape.
  const pts = nodes.map((n) => P.get(n.id)).filter(Boolean) as P[];
  let vb = `0 0 ${W} ${H}`;
  if (pts.length) {
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    let x0 = Math.min(...xs) - 130, x1 = Math.max(...xs) + 130, y0 = Math.min(...ys) - 60, y1 = Math.max(...ys) + 60;
    let w = Math.max(520, x1 - x0), h = Math.max(300, y1 - y0);
    if (w / h > W / H) { const nh = w * H / W; y0 -= (nh - h) / 2; h = nh; } else { const nw = h * W / H; x0 -= (nw - w) / 2; w = nw; }
    vb = `${x0} ${y0} ${w} ${h}`;
  }
  return (
    <svg className="network" viewBox={vb} role="img" aria-label="Network of companies and people"
         onWheel={(e) => { const k = Math.max(0.4, Math.min(2.5, view.k * (e.deltaY < 0 ? 1.1 : 0.9))); setView({ ...view, k }); }}
         onMouseDown={(e) => { drag.current = { sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y }; }}
         onMouseMove={(e) => { if (drag.current) setView({ ...view, x: drag.current.vx + (e.clientX - drag.current.sx), y: drag.current.vy + (e.clientY - drag.current.sy) }); }}
         onMouseUp={() => { drag.current = null; }} onMouseLeave={() => { drag.current = null; }}>
      <g transform={`translate(${view.x + (W / 2) * (1 - view.k)},${view.y + (H / 2) * (1 - view.k)}) scale(${view.k})`}>
        {edges.map((e, i) => {
          const a = P.get(e.source), b = P.get(e.target);
          if (!a || !b) return null;
          const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
          return (
            <g key={i} className={`ne ${e.kind} ${e.current ? "" : "former"}`}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}><title>{`${KIND[e.kind]}${e.label ? `: ${e.label}` : ""}${e.current ? "" : " (former)"}`}</title></line>
              {e.kind === "owns" && e.label && <text x={mx} y={my - 4} textAnchor="middle">{e.label}</text>}
            </g>
          );
        })}
        {nodes.map((n) => {
          const p = P.get(n.id);
          if (!p) return null;
          const isRoot = n.id === root, sel = n.id === selected, open = expanded.has(n.id);
          const more = !open ? "+" : "";
          if (n.type === "person") {
            const initials = n.name.replace(/^(MR|MRS|MS|MISS|DR)\.?\s+/i, "").split(/[\s,]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
            return (
              <g key={n.id} className={`nn person ${n.owner ? "owner" : "director"} ${sel ? "sel" : ""} ${isRoot ? "root" : ""}`}
                 transform={`translate(${p.x},${p.y})`} onClick={(ev) => { ev.stopPropagation(); onSelect(n.id); }}
                 onDoubleClick={() => onExpand(n.id)}>
                <circle r={isRoot ? 22 : 17} />
                <text className="ini" y={4} textAnchor="middle">{initials}</text>
                <text className="lbl" y={(isRoot ? 22 : 17) + 14} textAnchor="middle">{short(nice(n.name), 24)}{n.birth_year ? ` · ${new Date().getFullYear() - n.birth_year}` : ""}</text>
                {more && (deg.get(n.id) ?? 0) >= 0 && <text className="more" x={isRoot ? 18 : 14} y={-12}>{more}</text>}
              </g>
            );
          }
          const label = short(nice(n.name), 30);
          const w = Math.max(96, label.length * 6.6 + 22);
          return (
            <g key={n.id} className={`nn company ${n.in_list === false ? "outside" : ""} ${sel ? "sel" : ""} ${isRoot ? "root" : ""} ${n.status && !/^active/i.test(n.status) ? "closed" : ""}`}
               transform={`translate(${p.x - w / 2},${p.y - 15})`} onClick={(ev) => { ev.stopPropagation(); onSelect(n.id); }}
               onDoubleClick={() => onExpand(n.id)}>
              <rect width={w} height={30} rx={7} />
              <text x={w / 2} y={19} textAnchor="middle">{label}</text>
              {n.score != null && <g transform={`translate(${w - 6},-8)`}><rect className="sc" x={-26} width={30} height={16} rx={5} /><text className="sct" x={-11} y={12} textAnchor="middle">{Math.round(n.score)}</text></g>}
              {more && <text className="more" x={-6} y={-4}>{more}</text>}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export const KIND: Record<NEdge["kind"], string> = {
  owns: "Owns", director: "Director", group: "Group (parent and subsidiary)", same_owner: "Same owner", same_address: "Same address",
};
const short = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
export function nice(name: string) {
  if (name.includes(",")) { const [s, f] = name.split(",", 2); name = `${f.trim()} ${s.trim()}`; }
  return name.replace(/\b(LIMITED|LTD)\b\.?/i, "Ltd").replace(/\w\S*/g, (w) => (w.length <= 3 && w === w.toUpperCase() && /[A-Z]/.test(w) && !/^(THE|AND|OF)$/.test(w) ? w : w[0].toUpperCase() + w.slice(1).toLowerCase()));
}
