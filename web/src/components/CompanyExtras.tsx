import type React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type CompanyDetail } from "../api";
import { useAsync } from "./bits";
import MapView, { type MapLink, type MapPoint } from "./MapView";
import { cap, date, dateTime } from "../format";

export function Location({ data }: { data: CompanyDetail }) {
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const c = data.company;
  const points: MapPoint[] = [];
  const links: MapLink[] = [];
  const offices = (data.enrichment?.locations ?? []).filter((l) => l.kind !== "registered office" || l.postcode !== c.postcode);
  for (const l of offices) {
    if (l.lat != null && l.lon != null)
      points.push({ company_number: c.company_number, name: `${c.name}: ${l.name ?? cap(l.kind)}`, lat: l.lat, lon: l.lon,
                    label: `${l.postcode ?? ""} · ${l.kind}` });
  }
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
      <div className="sechead"><h2>{offices.length ? "Locations and industry" : "Location and industry"}</h2>
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
          {data.enrichment?.trading_postcode && data.enrichment.trading_postcode !== c.postcode && (
            <>
              <div className="label">Trades from</div>
              <div style={{ marginBottom: 12 }}><b>{data.enrichment.trading_region ?? data.enrichment.trading_postcode}</b>
                <span className="faint small"> · {data.enrichment.trading_postcode} · used for region and scoring</span></div>
            </>
          )}
          <div className="label">Registered office{data.enrichment?.trading_postcode && data.enrichment.trading_postcode !== c.postcode ? " (legal address only, often the accountant's)" : ""}</div>
          <div style={{ marginBottom: 12 }}>{c.registered_address ?? "—"}
            {data.geo?.precision === "outcode" && <div className="faint small">Placed at the postcode district: exact postcode not found</div>}</div>
          {offices.length > 0 && (
            <>
              <div className="label">Other offices and sites</div>
              <div className="offices">
                {offices.map((l, i) => (
                  <div key={i} className="office">
                    <span className="okind">{cap(l.kind)}</span>
                    <div>
                      {l.name && <b>{l.name}</b>}
                      <div className="small">{l.address ?? ""}</div>
                      {l.postcode && <a className="small" href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(l.postcode)}`} target="_blank" rel="noreferrer">{l.postcode} ↗</a>}
                      {l.postcode && l.lat == null && <span className="faint small"> · not on the map yet</span>}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
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

const OWN_TYPES: Record<string, string> = { owner_held: "Owner-held", group_owned: "Group-owned (sold to a group)",
  investor_backed: "Investor-backed", eot: "Employee-owned (EOT)", trust: "Held in trust", foreign_owned: "Foreign parent" };

const BT = ["software", "saas", "data", "msp", "it_consultancy", "field_service", "agency", "reseller", "other"];
const BT_LABEL: Record<string, string> = { software: "Software", saas: "SaaS", data: "Data", msp: "Managed service provider",
  it_consultancy: "IT consultancy", field_service: "Field service", agency: "Agency", reseller: "Reseller", other: "Other" };

export function Enrichment({ data, num, onSaved, finder }: { data: CompanyDetail; num: string; onSaved: () => void; finder?: React.ReactNode }) {
  const e = data.enrichment;
  const [edit, setEdit] = useState(false);
  const [allSources, setAllSources] = useState(false);
  const [f, setF] = useState({ website: e?.website ?? "", business_type: e?.business_type ?? "", recurring_revenue: e?.recurring_revenue ?? "",
                               field_service: e?.field_service ?? "", summary: e?.summary ?? "", source_url: "",
                               linkedin: e?.linkedin ?? "", phone: e?.phone ?? "",
                               ownership: e?.ownership ?? "", ownership_note: e?.ownership_note ?? "",
                               locations: (e?.locations ?? []).map((l) => [cap(l.kind), l.name ?? "", l.address ?? ""].join(" | ")).join("\n"),
                               facts: (e?.facts ?? []).map((x) => `${x.label}: ${x.value}`).join("\n") });
  const [err, setErr] = useState<string | null>(null);
  const tri = (v: string | null | undefined) => v ? <span className={v}>{cap(v)}</span> : <span className="faint">Not checked</span>;
  const open = data.issues.filter((i) => i.status === "open");
  // Newest source for each kind of finding, and every distinct source used.
  const sourceFor = (kind: string) => data.research.find((r) => r.kind === kind && r.source_url)?.source_url ?? null;
  const sources: { url: string; label: string | null; at: string }[] = [];
  for (const r of data.research) {
    if (r.source_url && !sources.some((x) => x.url === r.source_url)) sources.push({ url: r.source_url, label: r.source_label, at: r.retrieved_at });
  }

  return (
    <section>
      <div className="sechead">
        <h2>Enrichment</h2>
        <span className="faint small">{e ? `Updated ${dateTime(e.updated_at)} by ${e.updated_by ?? "unknown"}${e.confidence ? ` · ${e.confidence} confidence` : ""}` : "Researched facts with sources, by you or by Claude"}</span>
        <span className="right"><button className="btn quiet" onClick={() => setEdit(!edit)}>{edit ? "Cancel" : "Edit"}</button></span>
      </div>
      <div className="enr">
        <div><span className="label">Website</span>{e?.website ? <a href={e.website} target="_blank" rel="noreferrer">{e.website.replace(/^https?:\/\/(www\.)?/, "")} ↗</a> : <span className="faint">Not found yet</span>}
          {e?.website && sourceFor("website") && hostOf(sourceFor("website")!) !== hostOf(e.website) && <Src url={sourceFor("website")} />}</div>
        <div><span className="label">Business type</span>{e?.business_type ? BT_LABEL[e.business_type] ?? e.business_type : <span className="faint">Not classified</span>}
          <Src url={sourceFor("classification")} /></div>
        <div><span className="label">Recurring revenue</span>{tri(e?.recurring_revenue)}</div>
        <div><span className="label">Field-service work</span>{tri(e?.field_service)}</div>
        {(e?.linkedin || e?.phone) && (
          <div><span className="label">Contact</span>
            {e?.linkedin && <a href={e.linkedin} target="_blank" rel="noreferrer">LinkedIn ↗</a>}
            {e?.linkedin && e?.phone && " · "}{e?.phone && <a href={`tel:${e.phone.replace(/\s/g, "")}`}>{e.phone}</a>}</div>
        )}
      </div>
      {e?.summary && <div className="enr-summary"><Rich text={e.summary} /><Src url={sourceFor("summary")} /></div>}
      {(e?.facts ?? []).length > 0 && (
        <table className="facts">
          <tbody>
            {e!.facts!.map((f, i) => (
              <tr key={i}><th>{f.label}</th><td>{f.value}</td>
                <td className="src">{f.source_url ? <a href={f.source_url} target="_blank" rel="noreferrer">{hostOf(f.source_url)} ↗</a> : <span className="faint">no source</span>}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {(e?.locations ?? []).length > 0 && (
        <div className="faint small" style={{ margin: "6px 0" }}>{e!.locations!.length} {e!.locations!.length === 1 ? "office" : "offices and sites"}: {e!.locations!.map((l) => l.name ?? l.postcode ?? cap(l.kind)).join(", ")} (see Locations)</div>
      )}
      {sources.length > 0 && (
        <div className="sources">
          <span className="label">Sources</span>
          {(allSources ? sources : sources.slice(0, 6)).map((x) => (
            <a key={x.url} className="srcchip" href={x.url} target="_blank" rel="noreferrer" title={`${x.url} · ${date(x.at)}`}>
              {x.label || hostOf(x.url)} ↗</a>
          ))}
          {sources.length > 6 && <button className="linkish small" onClick={() => setAllSources(!allSources)}>{allSources ? "Fewer" : `+${sources.length - 6} more`}</button>}
        </div>
      )}
      {!e?.website && finder}
      {!e && !edit && <div className="faint small">Ask Claude to enrich this company (see <a href="/connect">Connect Claude</a>), or add what you know with Edit.</div>}
      {edit && (
        <form style={{ display: "grid", gap: 10, marginTop: 8 }} onSubmit={async (ev) => {
          ev.preventDefault(); setErr(null);
          const body: Record<string, unknown> = { source_url: f.source_url || "manual", confidence: "high" };
          for (const k of ["website", "business_type", "recurring_revenue", "field_service", "summary", "linkedin", "phone", "ownership", "ownership_note"] as const) if (f[k]) body[k] = f[k];
          if (!f.ownership && e?.ownership) body.ownership = "unknown";  // back to what Companies House shows
          // One office per line: "Kind | Name | Address"; one fact per line: "Label: value".
          body.locations = f.locations.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
            const [kind, name, ...addr] = l.split("|").map((x) => x.trim());
            const KINDS = ["head office", "office", "branch", "site", "warehouse", "registered office"];
            if (!addr.length) return { kind: "office", address: l };
            const k = kind.toLowerCase();
            return KINDS.includes(k) ? { kind: k, name: name || null, address: addr.join(", ") }
              : { kind: "office", name: [kind, name].filter(Boolean).join(" ") || null, address: addr.join(", ") };
          });
          const keep = new Map((e?.facts ?? []).map((x) => [`${x.label}: ${x.value}`, x.source_url]));
          body.facts = f.facts.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
            const i = l.indexOf(":");
            return { label: i > 0 ? l.slice(0, i).trim() : "Note", value: i > 0 ? l.slice(i + 1).trim() : l, source_url: keep.get(l) ?? undefined };
          });
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
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <label className="field"><span className="label">Ownership (from research)</span>
              <select value={f.ownership} onChange={(x) => setF({ ...f, ownership: x.target.value })}>
                <option value="">As Companies House shows</option>
                {Object.entries(OWN_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
            <label className="field" style={{ flex: 1 }}><span className="label">What research found</span>
              <input value={f.ownership_note} placeholder="e.g. Bought by Aspire Systems (India), July 2024" onChange={(x) => setF({ ...f, ownership_note: x.target.value })} /></label>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <label className="field"><span className="label">LinkedIn</span><input type="url" style={{ width: 260 }} value={f.linkedin} onChange={(x) => setF({ ...f, linkedin: x.target.value })} placeholder="https://linkedin.com/company/…" /></label>
            <label className="field"><span className="label">Phone</span><input style={{ width: 180 }} value={f.phone} onChange={(x) => setF({ ...f, phone: x.target.value })} /></label>
          </div>
          <textarea placeholder={"What they sell and to whom.\n\n- Bullet points with a dash"} value={f.summary} onChange={(x) => setF({ ...f, summary: x.target.value })} style={{ minHeight: 80 }} />
          <label className="field"><span className="label">Offices and sites, one per line: Kind | Name | Address</span>
            <textarea placeholder={"Head office | London | 52 Tabernacle Street, London EC2A 4NJ\nOffice | Cardiff | Churchill House, Cardiff"} value={f.locations}
                      onChange={(x) => setF({ ...f, locations: x.target.value })} style={{ minHeight: 60 }} /></label>
          <label className="field"><span className="label">Key facts, one per line: Label: value</span>
            <textarea placeholder={"Founded: 2003\nDelisted from AIM: 11 Apr 2024"} value={f.facts}
                      onChange={(x) => setF({ ...f, facts: x.target.value })} style={{ minHeight: 60 }} /></label>
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

function hostOf(u: string) {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
}

function Src({ url, label }: { url: string | null; label?: string }) {
  if (!url) return null;
  return <a className="srclink" href={url} target="_blank" rel="noreferrer" title={url}>{label ?? `via ${hostOf(url)}`} ↗</a>;
}

/** Plain text with light formatting: blank lines split paragraphs, "- " or "• " lines are bullets, **bold**. */
export function Rich({ text }: { text: string }) {
  const bold = (t: string) => t.split(/(\*\*[^*]+\*\*)/g).map((p, i) => p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p);
  const blocks = text.replace(/\r/g, "").split(/\n\s*\n/);
  return (
    <>
      {blocks.map((b, i) => {
        const lines = b.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*([-•*]|\d+\.)\s+/.test(l)))
          return <ul key={i}>{lines.map((l, j) => <li key={j}>{bold(l.replace(/^\s*([-•*]|\d+\.)\s+/, ""))}</li>)}</ul>;
        return <p key={i}>{lines.map((l, j) => <span key={j}>{j > 0 && <br />}{bold(l)}</span>)}</p>;
      })}
    </>
  );
}
