import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { useAsync } from "./bits";
import MapView, { type MapLink, type MapPoint } from "./MapView";
import { cap, dateTime } from "../format";

export function Location({ data }: { data: CompanyDetail }) {
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const c = data.company;
  const points: MapPoint[] = [];
  const links: MapLink[] = [];
  if (data.geo) {
    points.push({ company_number: c.company_number, name: c.name, lat: data.geo.lat, lon: data.geo.lon, focus: true,
                  precision: data.geo.precision, label: `${c.postcode} · registered office` });
    for (const l of data.links) {
      if (l.lat == null || l.lon == null || l.kind === "shared_address") continue;
      points.push({ company_number: l.other, name: l.other_name ?? l.other, lat: l.lat, lon: l.lon,
                    label: l.kind === "owned_by" ? (l.direction === "parent" ? "Parent company" : "Subsidiary") : `Same owner: ${l.via}` });
      links.push({ a: [data.geo.lat, data.geo.lon], b: [l.lat, l.lon], kind: l.kind, confidence: l.confidence,
                   label: l.kind === "owned_by" ? (l.direction === "parent" ? "Parent" : "Subsidiary") : "Same owner" });
    }
  }
  return (
    <section>
      <div className="sechead"><h2>Location and industry</h2>
        <span className="right"><a href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(c.postcode ?? c.registered_address ?? "")}`} target="_blank" rel="noreferrer">Open in OpenStreetMap ↗</a></span></div>
      <div className="loc-grid">
        <div>
          {data.geo && meta.data ? (
            <MapView points={points} links={links} tiles={meta.data.map.tiles} attribution={meta.data.map.attribution}
                     height={280} onOpen={(n) => n !== c.company_number && nav(`/c/${n}`)} />
          ) : (
            <div className="mapbox" style={{ height: 120, display: "grid", placeItems: "center", color: "var(--ink-3)" }}>
              {c.postcode ? "Not located yet: use Locate postcodes on the Map page" : "No postcode on file"}
            </div>
          )}
          {points.length > 1 && <div className="faint small" style={{ marginTop: 6 }}>Black line: parent or subsidiary. Green: same owner.</div>}
        </div>
        <div>
          <div className="label">Registered office</div>
          <div style={{ marginBottom: 12 }}>{c.registered_address ?? "—"}
            {data.geo?.precision === "outcode" && <div className="faint small">Placed at the postcode district: exact postcode not found</div>}</div>
          <div className="label">SIC codes</div>
          <div className="sics" style={{ flexDirection: "column", alignItems: "flex-start" }}>
            {data.sics.length ? data.sics.map((s) => (
              <span key={s.code} className="sic"><b>{s.code}</b>{s.description || <span className="faint">description not loaded</span>}</span>
            )) : <span className="faint">None filed</span>}
          </div>
        </div>
      </div>
    </section>
  );
}

const BT = ["software", "saas", "data", "msp", "it_consultancy", "field_service", "agency", "reseller", "other"];
const BT_LABEL: Record<string, string> = { software: "Software", saas: "SaaS", data: "Data", msp: "Managed service provider",
  it_consultancy: "IT consultancy", field_service: "Field service", agency: "Agency", reseller: "Reseller", other: "Other" };

export function Enrichment({ data, num, onSaved }: { data: CompanyDetail; num: string; onSaved: () => void }) {
  const e = data.enrichment;
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ website: e?.website ?? "", business_type: e?.business_type ?? "", recurring_revenue: e?.recurring_revenue ?? "",
                               field_service: e?.field_service ?? "", summary: e?.summary ?? "", source_url: "" });
  const [err, setErr] = useState<string | null>(null);
  const tri = (v: string | null | undefined) => v ? <span className={v}>{cap(v)}</span> : <span className="faint">Not checked</span>;
  const open = data.issues.filter((i) => i.status === "open");

  return (
    <section>
      <div className="sechead">
        <h2>Enrichment</h2>
        <span className="faint small">{e ? `Updated ${dateTime(e.updated_at)} by ${e.updated_by ?? "unknown"}${e.confidence ? ` · ${e.confidence} confidence` : ""}` : "Researched facts with sources, by you or by Claude"}</span>
        <span className="right"><button className="btn quiet" onClick={() => setEdit(!edit)}>{edit ? "Cancel" : "Edit"}</button></span>
      </div>
      <div className="enr">
        <div><span className="label">Website</span>{e?.website ? <a href={e.website} target="_blank" rel="noreferrer">{e.website.replace(/^https?:\/\/(www\.)?/, "")} ↗</a> : <span className="faint">Not found yet</span>}</div>
        <div><span className="label">Business type</span>{e?.business_type ? BT_LABEL[e.business_type] ?? e.business_type : <span className="faint">Not classified</span>}</div>
        <div><span className="label">Recurring revenue</span>{tri(e?.recurring_revenue)}</div>
        <div><span className="label">Field-service work</span>{tri(e?.field_service)}</div>
      </div>
      {e?.summary && <p style={{ margin: "0 0 8px" }}>{e.summary}</p>}
      {!e && !edit && <div className="faint small">Ask Claude to enrich this company (see <a href="/connect">Connect Claude</a>), or add what you know with Edit.</div>}
      {edit && (
        <form style={{ display: "grid", gap: 10, marginTop: 8 }} onSubmit={async (ev) => {
          ev.preventDefault(); setErr(null);
          const body: Record<string, unknown> = { source_url: f.source_url || "manual", confidence: "high" };
          for (const k of ["website", "business_type", "recurring_revenue", "field_service", "summary"] as const) if (f[k]) body[k] = f[k];
          try { await api.saveEnrichment(num, body); setEdit(false); onSaved(); } catch (x: any) { setErr(x.message); }
        }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <label className="field"><span className="label">Website</span><input type="url" style={{ width: 260 }} value={f.website} onChange={(x) => setF({ ...f, website: x.target.value })} placeholder="https://" /></label>
            <label className="field"><span className="label">Business type</span>
              <select value={f.business_type} onChange={(x) => setF({ ...f, business_type: x.target.value })}><option value="">—</option>{BT.map((b) => <option key={b} value={b}>{BT_LABEL[b]}</option>)}</select></label>
            {(["recurring_revenue", "field_service"] as const).map((k) => (
              <label key={k} className="field"><span className="label">{k === "recurring_revenue" ? "Recurring revenue" : "Field service"}</span>
                <select value={f[k]} onChange={(x) => setF({ ...f, [k]: x.target.value })}><option value="">—</option>{["yes", "partly", "no", "unknown"].map((v) => <option key={v}>{v}</option>)}</select></label>
            ))}
          </div>
          <textarea placeholder="What they sell and to whom" value={f.summary} onChange={(x) => setF({ ...f, summary: x.target.value })} style={{ minHeight: 60 }} />
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input type="url" style={{ flex: 1 }} placeholder="Source link (leave blank if from your own knowledge)" value={f.source_url} onChange={(x) => setF({ ...f, source_url: x.target.value })} />
            <button className="btn primary">Save</button>
          </div>
          {err && <div className="callout red">{err}</div>}
        </form>
      )}
      {open.length > 0 && (
        <div className="callout" style={{ marginTop: 12, marginBottom: 0, background: "var(--amber-soft)", borderColor: "#f5dfb8", color: "#7a3d06" }}>
          <b>{open.length} data issue{open.length > 1 ? "s" : ""} to review:</b>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {open.map((i) => <li key={i.id}><b>{i.issue}</b>{i.detail ? `: ${i.detail}` : ""}{i.suggested_fix ? ` Suggested: ${i.suggested_fix}` : ""} <span className="faint small">({i.created_by})</span>{" "}
              <button className="btn quiet" style={{ height: 24 }} onClick={async () => { await api.resolveIssue(i.id, "resolved", "Reviewed"); onSaved(); }}>Resolve</button></li>)}
          </ul>
        </div>
      )}
    </section>
  );
}
