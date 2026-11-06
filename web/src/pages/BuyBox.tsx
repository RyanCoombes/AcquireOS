import type React from "react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, Toast, useAsync } from "../components/bits";
import { useJob } from "../components/JobBar";
import { money, OWNERSHIP } from "../format";
import SicPicker from "../components/SicPicker";
import MoneyInput from "../components/MoneyInput";

type C = any;

export default function BuyBox() {
  const [params, setParams] = useSearchParams();
  const idParam = /^\d+$/.test(params.get("id") ?? "") ? Number(params.get("id")) : null;
  const { data, error } = useAsync(() => api.buybox(idParam), [idParam]);
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
      const r = await api.saveBuybox(data.id, c);
      setToast(r.background
        ? (r.queued
          ? "Saved. Another job is running (the data refresh), so this buy box is rescored as soon as it finishes. Until then Targets shows the old scores."
          : "Saved. Rescoring in the background; progress shows at the top. Everything stays usable meanwhile.")
        : `Saved. Rescored ${r.rescored.toLocaleString("en-GB")} companies.`);
    } catch (e: any) { setToast(e.message); }
    setSaving(false);
  };
  // Exclusions: every tick means "leave these out", shown with a cross.
  const xchecks = (opts: [string, string][], path: string[]) => {
    const list: string[] = get(c, path) ?? [];
    return opts.map(([k, label]) => {
      const on = list.includes(k);
      return (
        <label key={k} className={`xcheck ${on ? "on" : ""}`}>
          <input type="checkbox" checked={on} aria-label={`Exclude ${label}`}
                 onChange={(e) => upd(path, e.target.checked ? [...list, k] : list.filter((x) => x !== k))} />
          <span className="mark" aria-hidden>{on ? "✕" : ""}</span>{label}
        </label>
      );
    });
  };
  const ex = c.exclude ?? {};
  const exList = [
    ...(ex.keywords ?? []).map((k: string) => `“${k}”`),
    ...(ex.regions ?? []),
    ...(ex.ownership ?? []).map((k: string) => OWNERSHIP[k] ?? k),
    ...(ex.address_flags ?? []).map((k: string) => meta.data?.address_flags?.[k] ?? k),
    ...(ex.tiers ?? []).map((t: string) => `tier ${t}`),
  ];
  const n = (path: string[], props: Record<string, unknown> = {}) => (
    <input type="number" value={get(c, path) ?? ""} onChange={(e) => upd(path, e.target.value === "" ? 0 : Number(e.target.value))} {...props} />
  );

  return (
    <>
      <BoxManager current={data.id} onToast={setToast} select={(id) => setParams({ id: String(id) }, { replace: true })} />

      <div className="pagehead" style={{ paddingTop: 4 }}>
        <div>
          <h1 style={{ fontSize: 22 }}>Editing: {data.name}</h1>
          <div className="lede">
            {data.description ? <>{data.description} </> : null}
            <span className="steps3"><b>1 Universe</b> who's in <b>2 Exclusions</b> hard no's <b>3 Scoring</b> ranks the rest</span>
          </div>
        </div>
        <div className="right">
          <button className="btn" onClick={() => setC(structuredClone(data.defaults))}>Reset to defaults</button>
          <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Rescoring…" : "Save and rescore"}</button>
        </div>
      </div>

      <section>
        <h2>Your own criteria</h2>
        <p className="muted" style={{ marginTop: -4 }}>You score these 0–5 on each company. Not scored yet = not counted.</p>
        <div className="manual-ed label"><span>Criterion</span><span>Weight</span><span>What a 5 looks like</span><span /></div>
        {(c.manual ?? []).map((m: any, i: number) => (
          <div key={m.key} className="manual-ed">
            <input type="text" value={m.label} onChange={(e) => { const x = [...c.manual]; x[i] = { ...m, label: e.target.value }; upd(["manual"], x); }} />
            <input type="number" min={0} value={m.weight} onChange={(e) => { const x = [...c.manual]; x[i] = { ...m, weight: Number(e.target.value) }; upd(["manual"], x); }} />
            <input type="text" value={m.help ?? ""} placeholder="e.g. 5 = no customer over 10% of revenue"
                   onChange={(e) => { const x = [...c.manual]; x[i] = { ...m, help: e.target.value }; upd(["manual"], x); }} />
            <button className="btn quiet" title="Remove" aria-label={`Remove ${m.label}`}
                    onClick={() => upd(["manual"], c.manual.filter((_: any, j: number) => j !== i))}>×</button>
          </div>
        ))}
        <button className="btn" onClick={() => {
          const label = prompt("Name of the criterion, e.g. “Customer spread”");
          if (!label) return;
          const key = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || `c${Date.now()}`;
          upd(["manual"], [...(c.manual ?? []), { key, label, weight: 5, help: "" }]);
        }}>Add a criterion</button>
      </section>

      <section style={{ paddingBottom: 0 }}>
        <h2>Scoring criteria</h2>
        <p className="muted" style={{ marginTop: -4 }}>Step 3. Ranks what's in; never keeps anything out. Missing data scores half.</p>
      </section>
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
              {([["min", "Lowest"], ["ideal_min", "Ideal from"], ["ideal_max", "Ideal to"], ["max", "Highest"]] as const).map(([k, l]) => (
                <label key={k} className="field" style={{ marginRight: 6 }}>
                  <span className="label">{l}</span>
                  <MoneyInput value={c.revenue[k]} width={130} onChange={(v) => upd(["revenue", k], v ?? 0)} />
                </label>
              ))}
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
            <div style={{ marginTop: 6 }}>
              <SicPicker value={c.sic.preferred} onChange={(v) => upd(["sic", "preferred"], v)} />
            </div>
          </Crit>
        </tbody>
      </table>

      <section>
        <h2>Universe</h2>
        <p className="muted" style={{ marginTop: -4 }}>Step 1. <b>Anything listed here is included</b>; everything else is left out. Keep it wide.</p>
        <dl className="facts" style={{ gridTemplateColumns: "220px 1fr" }}>
          <dt>Include SIC codes starting with</dt><dd><SicPicker value={c.universe?.sic_prefixes ?? []} onChange={(v) => upd(["universe", "sic_prefixes"], v)} /></dd>
          <dt>…or names containing</dt><dd><input type="text" style={{ width: "100%", maxWidth: 620 }} placeholder="software, data, digital" value={(c.universe?.name_keywords ?? []).join(", ")}
                   onChange={(e) => upd(["universe", "name_keywords"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></dd>
          <dt>…when the SIC code starts with</dt><dd><SicPicker value={c.universe?.keyword_sic_prefixes ?? []} onChange={(v) => upd(["universe", "keyword_sic_prefixes"], v)} /></dd>
          <dt>Only these postcode areas</dt><dd><input type="text" style={{ width: "100%", maxWidth: 360 }} placeholder="e.g. CF, SA, NP, LL (blank for all of the UK)" value={(c.universe?.postcode_areas ?? []).join(", ")}
                   onChange={(e) => upd(["universe", "postcode_areas"], e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></dd>
          <dt>Trading at least</dt><dd className="range">{n(["universe", "min_years"])}<span className="faint">years</span></dd>
          <dt>Holding companies</dt>
          <dd>
            <label className="check" style={{ height: "auto" }}>
              <input type="checkbox" checked={c.universe?.include_parents ?? true}
                     onChange={(e) => upd(["universe", "include_parents"], e.target.checked)} />
              Include parent companies of targets
            </label>
            <div className="faint small">Brings in holding companies that own a company in the universe.</div>
          </dd>
        </dl>
        <p className="faint small">Saving rescores this buy box in the background (a few minutes on the full register). Everything stays usable while it runs.</p>
      </section>

      <section>
        <h2>Valuation assumptions</h2>
        <p className="muted" style={{ marginTop: -4 }}>Value = profit × multiple. Profit is filed, or revenue × margin.</p>
        <dl className="facts" style={{ gridTemplateColumns: "220px 1fr" }}>
          <dt>Profit margin</dt>
          <dd className="range">{n(["valuation", "margin_low"], { step: 1 })}<span className="faint">to</span>{n(["valuation", "margin_high"], { step: 1 })}<span className="faint">% of revenue</span></dd>
          <dt>EBITDA multiple</dt>
          <dd className="range">{n(["valuation", "multiple_low"], { step: 0.25 })}<span className="faint">to</span>{n(["valuation", "multiple_high"], { step: 0.25 })}<span className="faint">times</span></dd>
        </dl>
        <p className="faint small">Small UK IT and software firms often sell at 3–6× EBITDA.</p>
      </section>

      <section>
        <h2>Exclusions</h2>
        <p className="muted" style={{ marginTop: -4 }}>Step 2. <b>Anything ticked or listed here is excluded.</b></p>
        <div className={`exsummary ${exList.length ? "" : "none"}`}>
          {exList.length ? <><b>Excluding:</b> {exList.join(" · ")}</> : "Nothing excluded yet."}
        </div>
        <dl className="facts exclusions" style={{ gridTemplateColumns: "240px 1fr" }}>
          <dt>Exclude names, SIC or research mentioning</dt>
          <dd>
            <textarea style={{ minHeight: 56 }} value={c.exclude.keywords.join(", ")}
                      onChange={(e) => upd(["exclude", "keywords"], e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            <div className="faint small">Comma separated, whole words.</div>
          </dd>
          <dt>Exclude regions</dt>
          <dd>{xchecks(meta.data?.regions.map((r) => [r, r]) ?? [], ["exclude", "regions"])}
            {!meta.data?.regions.length && <span className="faint">No regions in the data yet.</span>}</dd>
          <dt>Exclude ownership types</dt>
          <dd>{xchecks(Object.entries(OWNERSHIP), ["exclude", "ownership"])}</dd>
          <dt>Exclude registered addresses</dt>
          <dd>{xchecks(Object.entries(meta.data?.address_flags ?? {}), ["exclude", "address_flags"])}</dd>
          <dt>Exclude review tiers</dt>
          <dd>{xchecks((meta.data?.tiers ?? []).map((t) => [t, t]), ["exclude", "tiers"])}
            <div className="faint small">Tiers from a ranked file you imported, if any.</div></dd>
          <dt>Always excluded</dt>
          <dd className="muted">Dissolved, insolvent or being struck off.</dd>
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

function BoxManager({ current, onToast, select }: { current: number; onToast: (m: string) => void; select: (id: number) => void }) {
  const { job } = useJob();
  const boxes = useAsync(() => api.buyboxes(), []);
  const tpls = useAsync(() => api.buyboxTemplates(), []);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [source, setSource] = useState("template:msp");
  const go = () => window.location.reload();
  const active = boxes.data?.find((b) => b.id === current);
  return (
    <>
      <div className="pagehead" style={{ paddingBottom: 12 }}>
        <div>
          <h1>Buy boxes</h1>
          <div className="lede">Saved searches that score every company. Filter by any of them anywhere.</div>
        </div>
        {active && (
          <div className="right">
            <button className="btn" onClick={async () => {
              const nm = prompt("Rename this buy box", active.name);
              if (nm && nm.trim()) { await api.renameBuybox(active.id, { name: nm.trim() }); go(); }
            }}>Rename</button>
            {(boxes.data?.length ?? 0) > 1 && (
              <button className="btn" onClick={async () => {
                if (!confirm(`Delete the buy box “${active.name}”? Its scores and saved searches go; your pipeline, notes and own scores are kept.`)) return;
                await api.deleteBuybox(active.id); window.location.href = "/buy-box";
              }}>Delete</button>
            )}
          </div>
        )}
      </div>
      <div className="boxes">
        {boxes.data?.map((b) => (
          <div key={b.id} className={`boxcard ${b.id === current ? "on" : ""}`} role="button" tabIndex={0}
               onClick={() => select(b.id)} onKeyDown={(e) => { if (e.key === "Enter") select(b.id); }}>
            <div className="nm">{b.name}</div>
            <div className="st">{b.scored_at ? <>{b.in_scope.toLocaleString("en-GB")} in scope · {b.strong.toLocaleString("en-GB")} score 70+</>
              : job?.running && job.kind !== "scoring"
                ? <span className="neg">Waiting to rescore: starts when the data refresh finishes. Counts below are out of date.</span>
                : "Rescoring now…"}</div>
            <div className="st">
              {b.id === current ? "Editing below" : "Edit"}
              {" · "}<a href={`/targets?bb=${b.id}`} onClick={(e) => e.stopPropagation()}>View targets</a>
            </div>
          </div>
        ))}
        {!adding && <div className="boxcard new" onClick={() => setAdding(true)}>+ New buy box</div>}
      </div>
      {adding && (
        <section>
          <h2>New buy box</h2>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label className="field"><span className="label">Name</span>
              <input type="text" style={{ width: "100%", maxWidth: 240 }} value={name} placeholder="e.g. SaaS in the South West" onChange={(e) => setName(e.target.value)} /></label>
            <label className="field"><span className="label">Start from</span>
              <select value={source} onChange={(e) => setSource(e.target.value)} style={{ minWidth: 300 }}>
                <optgroup label="Templates (edit afterwards)">
                  {tpls.data?.map((t) => <option key={t.key} value={`template:${t.key}`}>{t.label}</option>)}
                </optgroup>
                <optgroup label="Copy an existing buy box">
                  {boxes.data?.map((b) => <option key={b.id} value={`copy:${b.id}`}>Copy of {b.name}</option>)}
                </optgroup>
                <option value="blank">Blank (default settings)</option>
              </select></label>
            <button className="btn primary" disabled={!name.trim()} onClick={async () => {
              const [kind, val] = source.split(":");
              const body: Record<string, unknown> = { name: name.trim(), source: kind };
              if (kind === "template") body.template = val;
              if (kind === "copy") body.copy_id = Number(val);
              const r = await api.createBuybox(body);
              if (r.background) onToast("Created. Scoring in the background; progress shows at the top.");
              setAdding(false); setName(""); boxes.reload(); select(r.id);
            }}>Create</button>
            <button className="btn quiet" onClick={() => setAdding(false)}>Cancel</button>
          </div>
          {source.startsWith("template:") && (
            <p className="muted small">{tpls.data?.find((t) => `template:${t.key}` === source)?.description} Templates are starting points:
              check the SIC codes, ranges and valuation multiples before relying on them.</p>
          )}
        </section>
      )}
    </>
  );
}

function get(o: any, path: string[]) {
  return path.reduce((x, p) => (x == null ? x : x[p]), o);
}
