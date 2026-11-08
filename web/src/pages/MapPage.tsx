import { useMemo, useState, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, useAsync } from "../components/bits";
import MapView, { type MapLink, type MapPoint } from "../components/MapView";
import MapFocus from "../components/MapFocus";
import SicPicker from "../components/SicPicker";
import { FilterGroup, MoneyRange, NumField, NumRange, PresenceFilter, Select } from "../components/Filters";
import { int, OWNERSHIP } from "../format";

export default function MapPage() {
  const [params, setParams] = useSearchParams();
  // Older saved searches: "wales=..." is now presence in a nation.
  useEffect(() => {
    if (!params.has("wales")) return;
    const p = new URLSearchParams(params); const w = p.get("wales")!; p.delete("wales");
    p.set("nation", "Wales"); if (w !== "any") p.set("presence", w);
    setParams(p, { replace: true });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
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
  const MORE = ["min_revenue", "max_revenue", "min_profit", "max_profit", "min_net_assets", "nation", "presence", "revenue", "sold", "sic", "company_status", "status", "min_years", "accounts_size", "overdue", "charges", "min_value", "max_value", "changed_days", "flag"];
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

  const focus = (params.get("focus") ?? "").replace(/^c:/, "").toUpperCase();
  const setFocus = (n: string | null) => { const p = new URLSearchParams(params); if (n) p.set("focus", `c:${n}`); else p.delete("focus"); setParams(p); };
  if (focus && meta.data) {
    return (
      <>
        <div className="pagehead"><div><h1>Map</h1><div className="lede">One company and what it's connected to.</div></div>
          <div className="right"><FocusSearch onPick={setFocus} /></div></div>
        <MapFocus num={focus} tiles={meta.data.map.tiles} attribution={meta.data.map.attribution} onFocus={setFocus} onClose={() => setFocus(null)} />
      </>
    );
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Map</h1>
          <div className="lede">Registered offices, coloured by score. Click a dot, or search, to focus on one company and its connections.</div>
        </div>
        <div className="right">
          <FocusSearch onPick={setFocus} />
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
          <div className="band-more grouped">
            <FilterGroup title="Money" icon="£" query={query} keys={["min_revenue", "max_revenue", "revenue", "min_profit", "max_profit", "min_net_assets", "min_value", "max_value", "accounts_size"]}>
              <MoneyRange label="Revenue" lo="min_revenue" hi="max_revenue" query={query} set={set} hint="filed or estimate" />
              <Select label="Revenue source" k="revenue" query={query} set={set} options={[["filed", "Filed (confirmed in the accounts)"], ["estimated", "Estimate"], ["none", "No revenue figure"]]} />
              <MoneyRange label="Operating profit" lo="min_profit" hi="max_profit" query={query} set={set} hint="latest filed accounts" />
              <MoneyRange label="Net assets" lo="min_net_assets" query={query} set={set} />
              <MoneyRange label="Indicative value" lo="min_value" hi="max_value" query={query} set={set} />
              <Select label="Accounts filed" k="accounts_size" query={query} set={set} options={(m?.account_sizes ?? []).map((g) => [g.value, g.label])} />
            </FilterGroup>
            <FilterGroup title="Owners and sale signals" icon="●" query={query} keys={["sold", "flag"]}>
              <Select label="Recently sold" k="sold" query={query} set={set}
                      options={[["hide", "Hide companies sold in the last 3 years"], ["only", "Only companies sold in the last 3 years"]]} />
              <Select label="Ownership flag" k="flag" query={query} set={set} options={[
                ["recent_change", "Recent ownership change"], ["via_holdco", "Owned via holdco"], ["foreign_parent", "Foreign parent"],
                ["investor", "Investor"], ["trust", "Trust"], ["eot", "EOT"], ["mass_address", "Shared address"],
              ]} />
            </FilterGroup>
            <FilterGroup title="Location" icon="⌖" query={query} keys={["nation", "presence"]}>
              <PresenceFilter query={query} set={set} />
            </FilterGroup>
            <FilterGroup title="Company" icon="▤" query={query} keys={["company_status", "min_years", "overdue", "charges", "sic"]}>
              <Select label="Company status" k="company_status" query={query} set={set} options={(m?.status_groups ?? []).map((g) => [g.value, g.label])} />
              <NumField label="Years trading" k="min_years" placeholder="at least" query={query} set={set} />
              <Select label="Overdue filings" k="overdue" query={query} set={set}
                      options={[["any", "Accounts or confirmation"], ["accounts", "Accounts overdue"], ["confirmation", "Confirmation statement overdue"]]} />
              <Select label="Charges (secured loans)" k="charges" query={query} set={set}
                      options={[["outstanding", "Has outstanding charges"], ["none", "No outstanding charges"]]} />
              <div className="field" style={{ flexBasis: "100%" }}>
                <label>Industry (SIC)</label>
                <SicPicker value={(params.get("sic") ?? "").split(",").filter(Boolean)} width="100%" onChange={(v) => set("sic", v.join(","))} />
              </div>
            </FilterGroup>
            <FilterGroup title="Your work and changes" icon="↻" query={query} keys={["status", "changed_days"]}>
              <Select label="My status" k="status" query={query} set={set} options={(m?.statuses ?? []).map((x) => [x.value, x.label])} />
              <Select label="Changed in" k="changed_days" query={query} set={set}
                      options={[["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["365", "Last year"]]} />
            </FilterGroup>
          </div>
        )}
        <label className="check" style={{ flexBasis: "100%" }}><input type="checkbox" checked={showLinks} onChange={(e) => setShowLinks(e.target.checked)} />Show ownership links</label>
      </div>
      <ErrorLine error={data.error} />
      {meta.data && (
        <section style={{ padding: 0, overflow: "hidden" }}>
          <MapView points={points} links={links} tiles={meta.data.map.tiles} attribution={meta.data.map.attribution}
                   height={620} onOpen={(n) => setFocus(n)} />
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


/** Search for a company to focus the map on. */
function FocusSearch({ onPick }: { onPick: (num: string) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ company_number: string; name: string }[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    let live = true;
    const t = setTimeout(() => api.companies({ q, limit: "8", include_excluded: "true", count: "false" })
      .then((r) => live && setHits(r.rows)).catch(() => {}), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  return (
    <div style={{ position: "relative", width: 300 }}>
      <input type="search" placeholder="Focus on a company…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%" }} />
      {hits.length > 0 && (
        <div className="net-hits" style={{ top: 38 }}>
          {hits.map((h) => <div key={h.company_number} onClick={() => { setQ(""); setHits([]); onPick(h.company_number); }}>{h.name} <span className="faint small">{h.company_number}</span></div>)}
        </div>
      )}
    </div>
  );
}
