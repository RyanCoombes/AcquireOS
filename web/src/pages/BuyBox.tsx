import type React from "react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorLine, Toast, useAsync } from "../components/bits";
import { money, OWNERSHIP } from "../format";

type C = any;

export default function BuyBox() {
  const { data, error } = useAsync(() => api.buybox(), []);
  const meta = useAsync(() => api.meta(), []);
  const [c, setC] = useState<C | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => { if (data) setC(structuredClone(data.criteria)); }, [data]);
  if (error) return <ErrorLine error={error} />;
  if (!c || !data) return <div className="empty">Loading…</div>;

  const upd = (path: string[], v: unknown) => {
    const next = structuredClone(c);
    let o = next;
    for (const p of path.slice(0, -1)) o = o[p];
    o[path[path.length - 1]] = v;
    setC(next);
  };
  const totalWeight = ["staff", "years_trading", "revenue", "owner_age", "ownership", "net_asset_growth", "sic"]
    .reduce((s, k) => s + Number(c[k]?.weight ?? 0), 0);
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.saveBuybox(c);
      setToast(`Saved. Rescored ${r.rescored.toLocaleString("en-GB")} companies.`);
    } catch (e: any) { setToast(e.message); }
    setSaving(false);
  };
  const n = (path: string[], props: Record<string, unknown> = {}) => (
    <input type="number" value={get(c, path) ?? ""} onChange={(e) => upd(path, e.target.value === "" ? 0 : Number(e.target.value))} {...props} />
  );

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Buy box</h1>
          <div className="lede">
            What you are looking for. Each criterion earns points up to its weight; the score is the share of all points earned.
            Companies with missing data are not penalised as misses, but score lower and show how much could be checked.
          </div>
        </div>
        <div className="right">
          <button className="btn" onClick={() => setC(structuredClone(data.defaults))}>Reset to defaults</button>
          <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Rescoring…" : "Save and rescore"}</button>
        </div>
      </div>

      <table>
        <thead><tr><th>Criterion</th><th className="num">Weight</th><th className="num">Share</th><th>Settings</th></tr></thead>
        <tbody>
          <Crit label="Staff" w={["staff", "weight"]} c={c} n={n} total={totalWeight}>
            Acceptable {n(["staff", "min"])} to {n(["staff", "max"])}, ideal {n(["staff", "ideal_min"])} to {n(["staff", "ideal_max"])}
          </Crit>
          <Crit label="Years trading" w={["years_trading", "weight"]} c={c} n={n} total={totalWeight}>
            At least {n(["years_trading", "min"])}, ideal {n(["years_trading", "ideal"])} or more
          </Crit>
          <Crit label="Revenue" w={["revenue", "weight"]} c={c} n={n} total={totalWeight}>
            Ideal {money(c.revenue.ideal_min)}–{money(c.revenue.ideal_max)}, acceptable {money(c.revenue.min)}–{money(c.revenue.max)}
            <div className="range" style={{ marginTop: 6 }}>
              <span className="faint small">£</span>{n(["revenue", "min"], { style: { width: 110 }, step: 100000 })}
              {n(["revenue", "ideal_min"], { style: { width: 110 }, step: 100000 })}
              {n(["revenue", "ideal_max"], { style: { width: 110 }, step: 100000 })}
              {n(["revenue", "max"], { style: { width: 110 }, step: 100000 })}
            </div>
            <div className="faint small">Uses filed turnover where available, otherwise the estimate from staff numbers.</div>
          </Crit>
          <Crit label="Owner age" w={["owner_age", "weight"]} c={c} n={n} total={totalWeight}>
            Points start at {n(["owner_age", "min"])}, full points from {n(["owner_age", "ideal"])}
          </Crit>
          <Crit label="Ownership" w={["ownership", "weight"]} c={c} n={n} total={totalWeight}>
            Full points for{" "}
            {Object.entries(OWNERSHIP).filter(([k]) => k !== "unknown").map(([k, v]) => (
              <label key={k} className="check" style={{ display: "inline-flex", marginRight: 12, height: "auto" }}>
                <input type="checkbox" checked={c.ownership.good.includes(k)}
                       onChange={(e) => upd(["ownership", "good"], e.target.checked ? [...c.ownership.good, k] : c.ownership.good.filter((x: string) => x !== k))} />
                {v}
              </label>
            ))}
          </Crit>
          <Crit label="Net asset growth" w={["net_asset_growth", "weight"]} c={c} n={n} total={totalWeight}>
            Full points if net assets rose on the year
          </Crit>
          <Crit label="Industry code" w={["sic", "weight"]} c={c} n={n} total={totalWeight}>
            Preferred SIC codes{" "}
            <input type="text" style={{ width: 420 }} value={c.sic.preferred.join(", ")}
                   onChange={(e) => upd(["sic", "preferred"], e.target.value.split(/[\s,]+/).filter(Boolean))} />
          </Crit>
        </tbody>
      </table>

      <section>
        <h2>Universe</h2>
        <p className="muted" style={{ marginTop: -4, maxWidth: "80ch" }}>
          Which companies the monthly Companies House file adds to AcquireOS. Companies already here are always kept up to date.
          A company is added if it is active, old enough, in your postcode areas (if any), and either has a SIC code below
          or has a keyword in its name and one of the secondary SIC codes (to catch tech firms filed as consultancies).
        </p>
        <dl className="facts" style={{ gridTemplateColumns: "220px 1fr" }}>
          <dt>SIC codes starting with</dt><dd><input type="text" style={{ width: 460 }} placeholder="e.g. 620, 631, 5829" value={(c.universe?.sic_prefixes ?? []).join(", ")}
                   onChange={(e) => upd(["universe", "sic_prefixes"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></dd>
          <dt>Name keywords</dt><dd><input type="text" style={{ width: 620 }} placeholder="software, data, digital" value={(c.universe?.name_keywords ?? []).join(", ")}
                   onChange={(e) => upd(["universe", "name_keywords"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></dd>
          <dt>…with SIC codes starting</dt><dd><input type="text" style={{ width: 460 }} placeholder="e.g. 70229, 74909" value={(c.universe?.keyword_sic_prefixes ?? []).join(", ")}
                   onChange={(e) => upd(["universe", "keyword_sic_prefixes"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></dd>
          <dt>Postcode areas</dt><dd><input type="text" style={{ width: 360 }} placeholder="e.g. CF, SA, NP, LL (blank for all of the UK)" value={(c.universe?.postcode_areas ?? []).join(", ")}
                   onChange={(e) => upd(["universe", "postcode_areas"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></dd>
          <dt>Trading at least</dt><dd className="range">{n(["universe", "min_years"])}<span className="faint">years</span></dd>
        </dl>
        <p className="faint small">Saving does not remove companies already loaded; it changes what the next monthly refresh adds.</p>
      </section>

      <section>
        <h2>Valuation assumptions</h2>
        <p className="muted" style={{ marginTop: -4, maxWidth: "80ch" }}>
          Used for the indicative value on every company. Where filed operating profit exists it is used directly;
          otherwise profit is revenue × margin. Value is profit × multiple. You can override these on any single company.
        </p>
        <dl className="facts" style={{ gridTemplateColumns: "220px 1fr" }}>
          <dt>Profit margin</dt>
          <dd className="range">{n(["valuation", "margin_low"], { step: 1 })}<span className="faint">to</span>{n(["valuation", "margin_high"], { step: 1 })}<span className="faint">% of revenue</span></dd>
          <dt>EBITDA multiple</dt>
          <dd className="range">{n(["valuation", "multiple_low"], { step: 0.25 })}<span className="faint">to</span>{n(["valuation", "multiple_high"], { step: 0.25 })}<span className="faint">times</span></dd>
        </dl>
        <p className="faint small">Small UK IT services and software businesses often trade at roughly 3 to 6 times EBITDA, higher with strong recurring revenue. Treat this as a starting point and replace it with real deal evidence as you gather it.</p>
      </section>

      <section>
        <h2>Exclusions</h2>
        <p className="muted" style={{ marginTop: -4 }}>Excluded companies drop out of the list (tick “Show excluded” on Targets to see them, with the reason).</p>
        <dl className="facts" style={{ gridTemplateColumns: "220px 1fr" }}>
          <dt>Keywords in name, SIC or research</dt>
          <dd>
            <textarea style={{ minHeight: 56 }} value={c.exclude.keywords.join(", ")}
                      onChange={(e) => upd(["exclude", "keywords"], e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            <div className="faint small">Comma separated. Whole words only, so “van” does not exclude “Vanguard”.</div>
          </dd>
          <dt>Regions only</dt>
          <dd>
            {meta.data?.regions.length ? meta.data.regions.map((r) => (
              <label key={r} className="check" style={{ display: "inline-flex", marginRight: 12 }}>
                <input type="checkbox" checked={c.regions.includes(r)}
                       onChange={(e) => upd(["regions"], e.target.checked ? [...c.regions, r] : c.regions.filter((x: string) => x !== r))} />
                {r}
              </label>
            )) : <span className="faint">No regions in the data yet.</span>}
            <div className="faint small">Leave all unticked for anywhere.</div>
          </dd>
          <dt>Review tiers</dt>
          <dd>
            {meta.data?.tiers.map((t) => (
              <label key={t} className="check" style={{ display: "inline-flex", marginRight: 12 }}>
                <input type="checkbox" checked={c.exclude.tiers.includes(t)}
                       onChange={(e) => upd(["exclude", "tiers"], e.target.checked ? [...c.exclude.tiers, t] : c.exclude.tiers.filter((x: string) => x !== t))} />
                {t}
              </label>
            ))}
          </dd>
          <dt>Ownership types</dt>
          <dd>
            {Object.entries(OWNERSHIP).map(([k, v]) => (
              <label key={k} className="check" style={{ display: "inline-flex", marginRight: 12 }}>
                <input type="checkbox" checked={c.exclude.ownership.includes(k)}
                       onChange={(e) => upd(["exclude", "ownership"], e.target.checked ? [...c.exclude.ownership, k] : c.exclude.ownership.filter((x: string) => x !== k))} />
                {v}
              </label>
            ))}
          </dd>
          <dt>Registered address</dt>
          <dd>
            {Object.entries(meta.data?.address_flags ?? {}).map(([k, v]) => (
              <label key={k} className="check" style={{ display: "inline-flex", marginRight: 12 }}>
                <input type="checkbox" checked={c.exclude.address_flags.includes(k)}
                       onChange={(e) => upd(["exclude", "address_flags"], e.target.checked ? [...c.exclude.address_flags, k] : c.exclude.address_flags.filter((x: string) => x !== k))} />
                {v}
              </label>
            ))}
          </dd>
          <dt>Company status</dt>
          <dd>{c.exclude.statuses.join(", ")}</dd>
        </dl>
      </section>
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

function Crit({ label, w, c, n, total, children }: { label: string; w: string[]; c: C; n: (p: string[], props?: Record<string, unknown>) => React.ReactElement; total: number; children: React.ReactNode }) {
  const weight = Number(get(c, w) ?? 0);
  return (
    <tr>
      <td><b>{label}</b></td>
      <td className="num">{n(w, { style: { width: 64 }, min: 0 })}</td>
      <td className="num muted">{total ? Math.round((100 * weight) / total) : 0}%</td>
      <td>{children}</td>
    </tr>
  );
}

function get(o: any, path: string[]) {
  return path.reduce((x, p) => (x == null ? x : x[p]), o);
}
