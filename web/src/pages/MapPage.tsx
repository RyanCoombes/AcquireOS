import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import MapView, { type MapLink, type MapPoint } from "../components/MapView";
import SicPicker from "../components/SicPicker";
import { int, OWNERSHIP } from "../format";

export default function MapPage() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const [showLinks, setShowLinks] = useState(false);
  const q = useMemo(() => {
    const p: Record<string, string> = { format: "map", ...Object.fromEntries(params.entries()) };
    if (p.include_excluded === "1") p.include_excluded = "true";
    return p;
  }, [params]);
  const data = useAsync(() => api.mapData(q), [params.toString()]);
  const geo = useAsync(() => api.geocodeStatus(), []);
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (!v) p.delete(k); else p.set(k, v);
    setParams(p, { replace: true });
  };

  const points: MapPoint[] = (data.data?.points ?? []).map((p: any) => ({ ...p, label: `${p.company_number} · ${p.postcode}` }));
  const links: MapLink[] = showLinks ? (data.data?.links ?? []).map((l: any) => {
    const a = data.data!.points.find((p: any) => p.company_number === l.a);
    return a ? { a: [a.lat, a.lon], b: [l.b_lat, l.b_lon], kind: l.kind, confidence: l.confidence,
                 label: l.kind === "owned_by" ? `${a.name} is owned by ${l.b_name ?? l.b}` : `Same owner (${l.via}): ${a.name} and ${l.b_name}` } : null;
  }).filter(Boolean) as MapLink[] : [];
  const counts = geo.data?.counts;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Map</h1>
          <div className="lede">Registered offices on OpenStreetMap, coloured by score. Lines join parents to subsidiaries and companies with the same owner.</div>
        </div>
        <div className="right">
          {counts && counts.pending > 0 && (
            <button className="btn" disabled={geo.data?.running} onClick={async () => { await api.startGeocode(); geo.reload(); setTimeout(() => { geo.reload(); data.reload(); }, 8000); }}>
              {geo.data?.running ? "Locating…" : `Locate ${int(counts.pending)} postcodes`}
            </button>
          )}
        </div>
      </div>

      <div className="band">
        <div className="field">
          <label>Show</label>
          <div className="seg">
            <button className={!params.get("include_excluded") ? "on" : ""} onClick={() => set("include_excluded", null)}>Fits buy box</button>
            <button className={params.get("include_excluded") === "1" ? "on" : ""} onClick={() => set("include_excluded", "1")}>All companies</button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="m-score">Score at least</label>
          <input id="m-score" type="number" min={0} max={100} defaultValue={params.get("min_score") ?? ""} onBlur={(e) => set("min_score", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="m-own">Ownership</label>
          <select id="m-own" value={params.get("ownership") ?? ""} onChange={(e) => set("ownership", e.target.value)}>
            <option value="">Any</option>
            {Object.entries(OWNERSHIP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="m-status">My status</label>
          <select id="m-status" value={params.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any</option>
            {meta.data?.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
        <div className="field" style={{ minWidth: 320 }}>
          <label>Industry (SIC)</label>
          <SicPicker value={(params.get("sic") ?? "").split(",").filter(Boolean)} onChange={(v) => set("sic", v.join(","))} />
        </div>
        <label className="check"><input type="checkbox" checked={showLinks} onChange={(e) => setShowLinks(e.target.checked)} />Ownership links</label>
        <div className="band-actions faint small">
          {data.data ? `${int(data.data.located)} of ${int(data.data.total)} located` : ""}
        </div>
      </div>
      <ErrorLine error={data.error} />
      {meta.data && (
        <section style={{ padding: 0, overflow: "hidden" }}>
          <MapView points={points} links={links} tiles={meta.data.map.tiles} attribution={meta.data.map.attribution}
                   height={620} onOpen={(n) => nav(`/c/${n}`)} />
        </section>
      )}
      <div className="legend">
        <span><b className="dotkey" style={{ background: "#0e7c6b" }} />Score 70+</span>
        <span><b className="dotkey" style={{ background: "#e0a245" }} />40–69</span>
        <span><b className="dotkey" style={{ background: "#8a919d" }} />Under 40</span>
        <span><b className="dotkey" style={{ background: "#b8bec8" }} />Excluded</span>
        <span><i />Owned by</span><span><i className="g" />Same owner</span>
        <span>Faded dot: located to the postcode district only</span>
      </div>
      {data.data && data.data.total > 0 && data.data.located === 0 && (
        <div className="callout">
          None of these companies has a map location yet. Click <b>Locate postcodes</b> above (the server needs internet
          access to postcodes.io), or run <code>acquireos geocode</code>. It also runs after each monthly refresh. <Link to="/import">Data</Link>
        </div>
      )}
    </>
  );
}
