import type React from "react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, Hint, Toast, useAsync } from "../components/bits";
import { useJob } from "../components/JobBar";
import { OWNERSHIP } from "../format";
import SicPicker from "../components/SicPicker";
import MoneyInput from "../components/MoneyInput";

type C = any;

/** A comma-separated list you can type freely (commas, spaces, phrases); it is
    saved as a list on every change, but the box keeps exactly what you typed. */
function ListInput({ value, onChange, placeholder, area }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; area?: boolean }) {
  const [text, setText] = useState(value.join(", "));
  const [focused, setFocused] = useState(false);
  const joined = value.join(", ");
  useEffect(() => { if (!focused) setText(joined); }, [joined, focused]);
  const change = (t: string) => { setText(t); onChange(t.split(",").map((x) => x.trim()).filter(Boolean)); };
  const props = { value: text, placeholder, onFocus: () => setFocused(true), onBlur: () => { setFocused(false); setText(joined); } };
  return area
    ? <textarea {...props} style={{ minHeight: 52 }} onChange={(e) => change(e.target.value)} />
    : <input type="text" {...props} onChange={(e) => change(e.target.value)} />;
}

export default function BuyBox() {
  const [params, setParams] = useSearchParams();
  const idParam = /^\d+$/.test(params.get("id") ?? "") ? Number(params.get("id")) : null;
  const { data, error } = useAsync(() => api.buybox(idParam), [idParam]);
  const meta = useAsync(() => api.meta(), []);
  const boxesQ = useAsync(() => api.buyboxes(), []);
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
  const toggle = (path: string[], label: string, dflt: boolean) => {
    const on = (get(c, path) ?? dflt) as boolean;
    return (
      <label className={`xcheck ${on ? "on" : ""}`}>
        <input type="checkbox" checked={on} aria-label={`Exclude ${label}`} onChange={(e) => upd(path, e.target.checked)} />
        <span className="mark" aria-hidden>{on ? "✕" : ""}</span>{label}
      </label>
    );
  };
  const n = (path: string[], props: Record<string, unknown> = {}) => (
    <input type="number" className="bb-n" value={get(c, path) ?? ""} onChange={(e) => upd(path, e.target.value === "" ? 0 : Number(e.target.value))} {...props} />
  );

  const me = boxesQ.data?.find((x) => x.id === data.id);

  return (
    <>
      <BoxManager current={data.id} onToast={setToast} select={(id) => setParams({ id: String(id) }, { replace: true })} />

      <div className="pagehead bb-head">
        <div>
          <h1 style={{ fontSize: 22 }}>{data.name}</h1>
          <div className="lede">{data.description ? <>{data.description} </> : null}Which companies count, and what makes a good one.</div>
        </div>
        <div className="right">
          {me?.scored_at && <span className="bb-count"><b>{Number(me.in_scope ?? 0).toLocaleString("en-GB")}</b> companies count · {Number(me.strong ?? 0).toLocaleString("en-GB")} score 70+</span>}
          <button className="btn" onClick={() => setC(structuredClone(data.defaults))}>Reset</button>
          <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Rescoring…" : "Save and rescore"}</button>
        </div>
      </div>

      <section>
        <h2>Which companies count</h2>
        <p className="muted" style={{ marginTop: -4 }}>A company counts if it matches anything under <b>Include</b> and nothing under <b>Leave out</b>.</p>
        <div className="bb-two">
          <div className="bb-col in">
            <div className="bb-pill">Include</div>
            <div className="bb-f"><label>Industries</label>
              <SicPicker value={c.universe?.sic_prefixes ?? []} onChange={(v) => upd(["universe", "sic_prefixes"], v)} /></div>
            <div className="bb-f"><label>Or a name that mentions</label>
              <ListInput value={c.universe?.name_keywords ?? []} placeholder="software, data, digital"
                         onChange={(v) => upd(["universe", "name_keywords"], v)} />
              <details className="bb-more"><summary>Only for these broad industries{(c.universe?.keyword_sic_prefixes ?? []).length ? ` (${c.universe.keyword_sic_prefixes.length})` : ""}<Hint text="A name match only counts for companies in these codes, so 'data' doesn't bring in every data-something shop. Leave empty to allow any industry." /></summary>
                <SicPicker value={c.universe?.keyword_sic_prefixes ?? []} onChange={(v) => upd(["universe", "keyword_sic_prefixes"], v)} />
              </details></div>
            <div className="bb-row">
              <div className="bb-f"><label>Area (postcode areas)</label>
                <ListInput value={c.universe?.postcode_areas ?? []} placeholder="All of the UK, or e.g. CF, SA, NP"
                           onChange={(v) => upd(["universe", "postcode_areas"], v)} /></div>
              <div className="bb-f"><label>Trading for at least</label>
                <div className="range">{n(["universe", "min_years"], { style: { width: 70 } })}<span className="faint">years</span></div></div>
            </div>
            <label className="check" style={{ height: "auto" }}>
              <input type="checkbox" checked={c.universe?.include_parents ?? true} onChange={(e) => upd(["universe", "include_parents"], e.target.checked)} />
              Also include their holding companies</label>
          </div>

          <div className="bb-col out">
            <div className="bb-pill">Leave out</div>
            <div className="bb-f"><label>Names, industries or research mentioning</label>
              <ListInput area value={c.exclude.keywords ?? []} placeholder="e.g. plumbing, field service, recruitment"
                         onChange={(v) => upd(["exclude", "keywords"], v)} /></div>
            <div className="bb-f"><label>Industries<Hint text="Left out if any of its SIC codes is on this list. Tick the box to leave a company out only when every code it files is on the list, so a joiner that also lists property letting stays in." /></label>
              <SicPicker value={c.exclude?.sic_prefixes ?? []} onChange={(v) => upd(["exclude", "sic_prefixes"], v)} />
              {(c.exclude?.sic_prefixes ?? []).length > 0 && <label className="check" style={{ height: "auto", marginTop: 4 }}>
                <input type="checkbox" checked={!!c.exclude?.sic_all} onChange={(e) => upd(["exclude", "sic_all"], e.target.checked)} />
                Only when all its codes are on this list</label>}
              {(c.exclude?.sic_rules ?? []).map((r: { codes: string[]; unless: string[] }, i: number) => (
                <div key={i} className="bb-rule">
                  <div className="bb-rule-h"><span>Leave out</span>
                    <button className="linkish small red" onClick={() => upd(["exclude", "sic_rules"], (c.exclude.sic_rules as unknown[]).filter((_, j) => j !== i))}>Remove</button></div>
                  <SicPicker value={r.codes ?? []} onChange={(v) => upd(["exclude", "sic_rules"], (c.exclude.sic_rules as { codes: string[]; unless: string[] }[]).map((x, j) => j === i ? { ...x, codes: v } : x))} />
                  <div className="bb-rule-h"><span>unless it also has</span></div>
                  <SicPicker value={r.unless ?? []} onChange={(v) => upd(["exclude", "sic_rules"], (c.exclude.sic_rules as { codes: string[]; unless: string[] }[]).map((x, j) => j === i ? { ...x, unless: v } : x))} />
                </div>
              ))}
              <button className="linkish small" style={{ marginTop: 4 }} onClick={() => upd(["exclude", "sic_rules"], [...(c.exclude?.sic_rules ?? []), { codes: [], unless: [] }])}>
                + Leave out an industry unless it also has another</button>
              <Hint text="E.g. leave out 61200 (wireless telecoms) unless the company also has a 62 (software) or 63 (data) code: drops mobile operators, keeps communications software firms." /></div>
            <div className="bb-f"><label>Owned by</label><div>{xchecks(Object.entries(OWNERSHIP), ["exclude", "ownership"])}</div></div>
            <div className="bb-f"><label>Accounts filed as</label><div>{xchecks((meta.data?.account_sizes ?? []).map((x) => [x.value, x.label] as [string, string]), ["exclude", "accounts_types"])}</div></div>
            <div className="bb-f"><label>Already dealt with</label><div>{toggle(["exclude", "recently_sold"], "Sold in the last 3 years", true)}
              {toggle(["exclude", "possible_buyer"], "Buying others", false)}</div></div>
            <div className="bb-f"><label>Registered address</label><div>{xchecks(Object.entries(meta.data?.address_flags ?? {}), ["exclude", "address_flags"])}</div></div>
            {(meta.data?.regions ?? []).length > 0 && <div className="bb-f"><label>Registered in</label><div>{xchecks(meta.data!.regions.map((r) => [r, r]), ["exclude", "regions"])}</div></div>}
            {(meta.data?.tiers ?? []).length > 0 && <div className="bb-f"><label>Review tier (from your file)</label><div>{xchecks(meta.data!.tiers.map((t) => [t, t]), ["exclude", "tiers"])}</div></div>}
            <div className="bb-always">Always left out: dissolved, insolvent or being struck off.</div>
          </div>
        </div>
      </section>

      <section>
        <h2>What makes a good one</h2>
        <p className="muted" style={{ marginTop: -4 }}>Ranks the companies that count. Missing data scores half.</p>
        <table className="bb-score">
          <tbody>
            <Crit label="Staff" w={["staff", "weight"]} c={c} upd={upd} total={totalWeight}>
              Ideal {n(["staff", "ideal_min"])}–{n(["staff", "ideal_max"])}, still counts {n(["staff", "min"])}–{n(["staff", "max"])}
            </Crit>
            <Crit label="Oldest owner's age" w={["owner_age", "weight"]} c={c} upd={upd} total={totalWeight}>
              Points from {n(["owner_age", "min"])}, full points at {n(["owner_age", "ideal"])}
            </Crit>
            <Crit label="Revenue" w={["revenue", "weight"]} c={c} upd={upd} total={totalWeight}>
              <span className="bb-money">Ideal <MoneyInput value={c.revenue.ideal_min} width={96} onChange={(v) => upd(["revenue", "ideal_min"], v ?? 0)} />–<MoneyInput value={c.revenue.ideal_max} width={96} onChange={(v) => upd(["revenue", "ideal_max"], v ?? 0)} />,
                still counts <MoneyInput value={c.revenue.min} width={96} onChange={(v) => upd(["revenue", "min"], v ?? 0)} />–<MoneyInput value={c.revenue.max} width={96} onChange={(v) => upd(["revenue", "max"], v ?? 0)} /></span>
              <Hint text="Filed turnover where there is one, otherwise the estimate from staff numbers." />
            </Crit>
            <Crit label="Ownership" w={["ownership", "weight"]} c={c} upd={upd} total={totalWeight}>
              Best:{" "}
              {Object.entries(OWNERSHIP).filter(([k]) => k !== "unknown").map(([k, v]) => (
                <label key={k} className="check" style={{ display: "inline-flex", marginRight: 10, height: "auto" }}>
                  <input type="checkbox" checked={c.ownership.good.includes(k)}
                         onChange={(e) => upd(["ownership", "good"], e.target.checked ? [...c.ownership.good, k] : c.ownership.good.filter((x: string) => x !== k))} />
                  {v}
                </label>
              ))}
              <div style={{ marginTop: 6 }}>
                <select value={String(get(c, ["unknown_owner_points"]) ?? 0)} onChange={(e) => upd(["unknown_owner_points"], Number(e.target.value))}>
                  <option value="0">Owners not on record: no points for ownership or age (cautious)</option>
                  <option value="0.5">Owners not on record: half points (neutral)</option>
                </select>
              </div>
            </Crit>
            <Crit label="Years trading" w={["years_trading", "weight"]} c={c} upd={upd} total={totalWeight}>
              Ideal {n(["years_trading", "ideal"])}+ years, at least {n(["years_trading", "min"])}
            </Crit>
            <Crit label="Favourite industries" w={["sic", "weight"]} c={c} upd={upd} total={totalWeight}>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <span style={{ paddingTop: 6, whiteSpace: "nowrap" }}>Extra points for</span>
                <div style={{ flex: 1 }}><SicPicker value={c.sic.preferred} onChange={(v) => upd(["sic", "preferred"], v)} /></div>
              </div>
            </Crit>
            <Crit label="Net assets growing" w={["net_asset_growth", "weight"]} c={c} upd={upd} total={totalWeight}>
              Rose on the year before
            </Crit>
            <tr><td colSpan={3} className="bb-grp">Scored by you on each company (0–5)<Hint text="Not scored yet = not counted, so it doesn't drag a company down." /></td></tr>
            {(c.manual ?? []).map((m: any, i: number) => (
              <tr key={m.key}>
                <td className="bb-name"><input type="text" value={m.label} aria-label="Criterion"
                  onChange={(e) => { const x = [...c.manual]; x[i] = { ...m, label: e.target.value }; upd(["manual"], x); }} /></td>
                <td className="bb-imp"><Importance value={Number(m.weight ?? 0)} onChange={(v) => { const x = [...c.manual]; x[i] = { ...m, weight: v }; upd(["manual"], x); }} /></td>
                <td><div style={{ display: "flex", gap: 6 }}>
                  <input type="text" style={{ flex: 1 }} value={m.help ?? ""} placeholder="5 = …"
                         onChange={(e) => { const x = [...c.manual]; x[i] = { ...m, help: e.target.value }; upd(["manual"], x); }} />
                  <button className="btn quiet" title="Remove" aria-label={`Remove ${m.label}`}
                          onClick={() => upd(["manual"], c.manual.filter((_: any, j: number) => j !== i))}>×</button></div></td>
              </tr>
            ))}
            <tr><td colSpan={3} style={{ borderBottom: 0 }}>
              <button className="btn quiet" onClick={() => {
                const label = prompt("Name of the criterion, e.g. “Customer spread”");
                if (!label) return;
                const key = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || `c${Date.now()}`;
                upd(["manual"], [...(c.manual ?? []), { key, label, weight: 5, help: "" }]);
              }}>+ Add your own</button></td></tr>
          </tbody>
        </table>
      </section>

      <section className="bb-val">
        <h2>Valuation</h2>
        <span className="muted">Profit × multiple. Margin</span>
        <span className="range">{n(["valuation", "margin_low"], { step: 1 })}<span className="faint">–</span>{n(["valuation", "margin_high"], { step: 1 })}</span>
        <span className="muted">% where profit isn't filed; multiple</span>
        <span className="range">{n(["valuation", "multiple_low"], { step: 0.25 })}<span className="faint">–</span>{n(["valuation", "multiple_high"], { step: 0.25 })}</span>
        <span className="muted">× EBITDA</span>
        <Hint text="Small UK IT and software firms often sell at 3–6× EBITDA. Adjust to your own evidence." />
      </section>
      <Toast msg={toast} onDone={() => setToast(null)} />
    </>
  );
}

// Importance in plain words; the points behind them. A weight that isn't one of
// these (e.g. 20 from before) is kept exactly and shown as Custom until changed.
const LEVELS: [string, number][] = [["Off", 0], ["Low", 5], ["Medium", 15], ["High", 25]];
function Importance({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const exact = LEVELS.some(([, v]) => v === value);
  return (
    <span className="bb-seg-wrap">
      <span className="bb-seg" role="radiogroup">
        {LEVELS.map(([l, v]) => (
          <button key={l} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>
        ))}
      </span>
      {!exact && <span className="faint small nowrap" title="A weight from before, kept exactly. Pick a level to change it.">Custom: {value}</span>}
    </span>
  );
}

function Crit({ label, w, c, upd, total, children }: { label: string; w: string[]; c: C; upd: (p: string[], v: unknown) => void; total: number; children: React.ReactNode }) {
  const weight = Number(get(c, w) ?? 0);
  return (
    <tr className={weight === 0 ? "off" : ""}>
      <td className="bb-name"><b>{label}</b>{weight > 0 && total ? <div className="faint small">{Math.round((100 * weight) / total)}% of the score</div> : null}</td>
      <td className="bb-imp"><Importance value={weight} onChange={(v) => upd(w, v)} /></td>
      <td className="bb-set">{children}</td>
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
