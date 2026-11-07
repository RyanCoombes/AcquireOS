import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import MapView, { type MapLink, type MapPoint } from "../components/MapView";
import SicPicker from "../components/SicPicker";
import MoneyInput from "../components/MoneyInput";
import { NumField, NumRange, Select } from "../components/Filters";
import { int, OWNERSHIP } from "../format";

export default function MapPage() {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const [showLinks, setShowLinks] = useState(false);
  const q = useMemo(() => {
    const p: Record<string, string> = { format: "map", ...Object.fromEntries(params.entries()) };
    // The map shows companies in a buy box unless you ask for all of them.
    if (p.include_excluded === "1") delete p.include_excluded; else p.in_box = "true";
    return p;
  }, [params]);
  const data = useAsync(() => api.mapData(q), [params.toString()]);
  const geo = useAsync(() => api.geocodeStatus(), []);
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (!v) p.delete(k); else p.set(k, v);
    setParams(p, { replace: true });
  };
  const query = useMemo(() => Object.fromEntries(params.entries()), [params]);
  const m = meta.data;
  const saved = useAsync(() => api.searches(), []);
  const [more, setMore] = useState(false);
  const MORE = ["sold", "sic", "company_status", "status", "min_years", "accounts_size", "overdue", "charges", "min_value", "max_value", "changed_days", "flag"];
  const moreActive = MORE.filter((k) => query[k]).length;
  const active = Object.keys(query).length;
  // A saved search from the lists: its filters, on the map (all companies unless it was a targets search).
  const applySaved = (sp: Record<string, string>) => {
    const p: Record<string, string> = {};
    for (const [k, v] of Object.entries(sp)) if (v && !["sort", "dir", "page", "list", "include_excluded", "in_box"].includes(k)) p[k] = v;
    if (sp.list !== "targets" && sp.in_box !== "1") p.include_excluded = "1";
    setParams(new URLSearchParams(p), { replace: true });
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
          <div className="lede">Registered offices, coloured by score.</div>
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
            <button className={!params.get("include_excluded") ? "on" : ""} onClick={() => set("include_excluded", null)}>In a buy box</button>
            <button className={params.get("include_excluded") === "1" ? "on" : ""} onClick={() => set("include_excluded", "1")}>All companies</button>
          </div>
        </div>
        <Select label="Buy box" k="bb" query={query} set={set} options={(m?.buy_boxes ?? []).map((b) => [String(b.id), b.name])} />
        <div className="field">
          <label htmlFor="f-mine">Decided</label>
          <select id="f-mine" value={query.mine ?? "all"} className={query.mine ? "set" : ""} onChange={(e) => set("mine", e.target.value === "all" ? null : e.target.value)}>
            <option value="all">Everything</option>
            <option value="hide_closed">Hide not suitable and not now</option>
            <option value="pipeline">Only my pipeline</option>
            <option value="untouched">Only not looked at yet</option>
          </select>
        </div>
        <NumField label="Score" k="min_score" placeholder="at least" query={query} set={set} />
        <NumRange label="Staff" lo="min_staff" hi="max_staff" query={query} set={set} />
        <NumField label="Owner aged" k="min_owner_age" placeholder="at least" query={query} set={set} />
        <Select label="Region" k="region" query={query} set={set} options={(m?.regions ?? []).map((r) => [r, r])} />
        <Select label="Ownership" k="ownership" query={query} set={set} options={Object.entries(OWNERSHIP)} />
        <button className="btn quiet" onClick={() => setMore(!more)} aria-expanded={more}>{more ? "Fewer filters" : `More filters${moreActive ? ` (${moreActive})` : ""}`}</button>
        <div className="band-actions">
          {saved.data && saved.data.length > 0 && (
            <select aria-label="Saved search" value="" onChange={(e) => { const s = saved.data!.find((x) => String(x.id) === e.target.value); if (s) applySaved(s.params); }}>
              <option value="">Saved searches…</option>
              {saved.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
          {active > 0 && <button className="btn quiet" onClick={() => setParams(new URLSearchParams(), { replace: true })}>Clear</button>}
          <span className="faint small">{data.data ? `${int(data.data.located)} of ${int(data.data.total)} on the map` : ""}</span>
        </div>
        {more && (
          <div className="band-more">
            <div className="field" style={{ flexBasis: "100%" }}>
              <label>Industry (SIC)</label>
              <SicPicker value={(params.get("sic") ?? "").split(",").filter(Boolean)} width="100%" onChange={(v) => set("sic", v.join(","))} />
            </div>
            <Select label="Company status" k="company_status" query={query} set={set} options={(m?.status_groups ?? []).map((g) => [g.value, g.label])} />
            <Select label="My status" k="status" query={query} set={set} options={(m?.statuses ?? []).map((x) => [x.value, x.label])} />
            <NumField label="Years trading" k="min_years" placeholder="at least" query={query} set={set} />
            <Select label="Accounts filed" k="accounts_size" query={query} set={set} options={(m?.account_sizes ?? []).map((g) => [g.value, g.label])} />
            <Select label="Overdue filings" k="overdue" query={query} set={set}
                    options={[["any", "Accounts or confirmation"], ["accounts", "Accounts overdue"], ["confirmation", "Confirmation statement overdue"]]} />
            <Select label="Charges (secured loans)" k="charges" query={query} set={set}
                    options={[["outstanding", "Has outstanding charges"], ["none", "No outstanding charges"]]} />
            <div className="field">
              <label>Indicative value</label>
              <div className="range">
                <MoneyInput value={query.min_value ? Number(query.min_value) : null} commit="blur" width={120} placeholder="min, e.g. 500k"
                            aria-label="Indicative value minimum" onChange={(v) => set("min_value", v === null ? null : String(v))} />
                <span className="faint">to</span>
                <MoneyInput value={query.max_value ? Number(query.max_value) : null} commit="blur" width={120} placeholder="max, e.g. 3m"
                            aria-label="Indicative value maximum" onChange={(v) => set("max_value", v === null ? null : String(v))} />
              </div>
            </div>
            <Select label="Recently sold" k="sold" query={query} set={set}
                    options={[["hide", "Hide companies sold in the last 3 years"], ["only", "Only companies sold in the last 3 years"]]} />
            <Select label="Changed in" k="changed_days" query={query} set={set}
                    options={[["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last year"]]} />
            <Select label="Flag" k="flag" query={query} set={set} options={[
              ["recent_change", "Recent ownership change"], ["via_holdco", "Owned via holdco"], ["foreign_parent", "Foreign parent"],
              ["investor", "Investor"], ["trust", "Trust"], ["eot", "EOT"], ["mass_address", "Shared address"],
            ]} />
          </div>
        )}
        <label className="check" style={{ flexBasis: "100%" }}><input type="checkbox" checked={showLinks} onChange={(e) => setShowLinks(e.target.checked)} />Show ownership links</label>
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
