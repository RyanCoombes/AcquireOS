/* OpenStreetMap via Leaflet. Points are canvas circle markers coloured by
   score, so tens of thousands of companies stay fast. Lines show ownership
   (parent ↔ subsidiary) and shared-owner links. */
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export interface MapPoint {
  company_number: string; name: string; lat: number; lon: number; score?: number | string | null;
  excluded?: boolean | null; status?: string; precision?: string; focus?: boolean; label?: string;
  colour?: string; size?: number;
}
export interface MapLink {
  a: [number, number]; b: [number, number]; kind: "owned_by" | "shared_owner" | "shared_address" | string;
  label?: string; confidence?: string;
}

const UK: L.LatLngBoundsExpression = [[49.9, -8.2], [58.7, 1.8]];

function colour(p: MapPoint) {
  if (p.colour) return p.colour;
  if (p.focus) return "#141820";
  if (p.excluded) return "#b8bec8";
  const s = Number(p.score ?? 0);
  return s >= 70 ? "#0e7c6b" : s >= 40 ? "#e0a245" : "#8a919d";
}

export default function MapView({
  points, links = [], tiles, attribution, height = 560, onOpen, fit = true,
}: {
  points: MapPoint[]; links?: MapLink[]; tiles: string; attribution: string; height?: number;
  onOpen?: (num: string) => void; fit?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { preferCanvas: true, zoomControl: true, attributionControl: true, scrollWheelZoom: true });
    L.tileLayer(tiles, { attribution, maxZoom: 18 }).addTo(m);
    m.fitBounds(UK);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, [tiles, attribution]);

  useEffect(() => {
    const m = map.current, g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    for (const l of links) {
      L.polyline([l.a, l.b], {
        color: l.kind === "owned_by" ? "#141820" : l.kind === "shared_owner" ? "#0e7c6b" : l.kind === "person" ? "#2f62d8" : l.kind === "office" ? "#0e7c6b" : "#8a919d",
        weight: l.kind === "owned_by" ? 2 : 1.6, opacity: 0.7,
        dashArray: l.confidence === "possible" || l.kind === "shared_address" ? "5 6" : undefined,
      }).bindTooltip(l.label ?? "", { sticky: true }).addTo(g);
    }
    for (const p of points) {
      const mk = L.circleMarker([p.lat, p.lon], {
        radius: p.size ?? (p.focus ? 9 : 6), weight: p.focus ? 3 : 1.5, color: "#ffffff",
        fillColor: colour(p), fillOpacity: p.precision === "outcode" ? 0.55 : 0.95,
      });
      const score = p.score !== undefined && p.score !== null ? ` · score ${Math.round(Number(p.score))}` : "";
      mk.bindTooltip(`<b>${escape(p.name)}</b><br><span style="color:#545c69">${p.label ?? p.company_number}${score}${p.precision === "outcode" ? " · approximate location" : ""}</span>`);
      if (onOpen) mk.on("click", () => onOpen(p.company_number));
      mk.addTo(g);
    }
    if (fit) {
      const pts: L.LatLngExpression[] = [...points.map((p) => [p.lat, p.lon] as [number, number]), ...links.flatMap((l) => [l.a, l.b])];
      if (pts.length === 1) m.setView(pts[0], 13);
      else if (pts.length > 1) m.fitBounds(L.latLngBounds(pts), { padding: [30, 30], maxZoom: 13 });
    }
  }, [points, links, onOpen, fit]);

  return <div ref={el} className="mapbox" style={{ height }} />;
}

function escape(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
}
