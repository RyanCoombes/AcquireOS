import type React from "react";
import MoneyInput from "./MoneyInput";
/* Filter controls shared by the company lists and the map (values live in the URL). */
export type SetFn = (k: string, v: string | null) => void;

export function Select({ label, k, query, set, options }: { label: string; k: string; query: Record<string, string>; set: SetFn; options: [string, string][] }) {
  return (
    <div className="field">
      <label htmlFor={`f-${k}`}>{label}</label>
      <select id={`f-${k}`} value={query[k] ?? ""} onChange={(e) => set(k, e.target.value)} className={query[k] ? "set" : ""}>
        <option value="">Any</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

export function NumField({ label, k, placeholder, query, set }: { label: string; k: string; placeholder?: string; query: Record<string, string>; set: SetFn }) {
  return (
    <div className="field">
      <label htmlFor={`f-${k}`}>{label}</label>
      <input id={`f-${k}`} type="number" min={0} key={`${k}-${query[k] ?? ""}`} placeholder={placeholder} defaultValue={query[k] ?? ""}
             className={query[k] ? "set" : ""}
             onBlur={(e) => set(k, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(k, (e.target as HTMLInputElement).value); }} />
    </div>
  );
}

export function NumRange({ label, lo, hi, query, set, wide }: { label: string; lo: string; hi: string; query: Record<string, string>; set: SetFn; wide?: boolean }) {
  const style = wide ? { width: 104 } : undefined;
  return (
    <div className="field">
      <label>{label}</label>
      <div className="range">
        <input type="number" min={0} placeholder="min" style={style} key={`${lo}-${query[lo] ?? ""}`} defaultValue={query[lo] ?? ""} className={query[lo] ? "set" : ""}
               aria-label={`${label} minimum`} onBlur={(e) => set(lo, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(lo, (e.target as HTMLInputElement).value); }} />
        <span className="faint">to</span>
        <input type="number" min={0} placeholder="max" style={style} key={`${hi}-${query[hi] ?? ""}`} defaultValue={query[hi] ?? ""} className={query[hi] ? "set" : ""}
               aria-label={`${label} maximum`} onBlur={(e) => set(hi, e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") set(hi, (e.target as HTMLInputElement).value); }} />
      </div>
    </div>
  );
}


/** A titled group of filters in "More filters", with how many are set. */
export function FilterGroup({ title, icon, query, keys, children }: { title: string; icon: string; query: Record<string, string>; keys: string[]; children: React.ReactNode }) {
  const n = keys.filter((k) => query[k]).length;
  return (
    <div className="fgroup" role="group" aria-label={title}>
      <div className="fg-title"><span className="fg-ico" aria-hidden>{icon}</span>{title}{n ? <span className="fg-n">{n}</span> : null}</div>
      <div className="fg-body">{children}</div>
    </div>
  );
}

/** A pounds range (or minimum only), e.g. revenue £1m to £5m. */
export function MoneyRange({ label, lo, hi, query, set, hint }: { label: string; lo: string; hi?: string; query: Record<string, string>; set: SetFn; hint?: string }) {
  return (
    <div className="field">
      <label>{label}{hint ? <span className="faint"> · {hint}</span> : null}</label>
      <div className="range">
        <MoneyInput value={query[lo] ? Number(query[lo]) : null} commit="blur" width={110} placeholder={hi ? "min" : "at least"}
                    aria-label={`${label} minimum`} onChange={(v) => set(lo, v === null ? null : String(v))} />
        {hi && <>
          <span className="faint">to</span>
          <MoneyInput value={query[hi] ? Number(query[hi]) : null} commit="blur" width={110} placeholder="max"
                      aria-label={`${label} maximum`} onChange={(v) => set(hi, v === null ? null : String(v))} />
        </>}
      </div>
    </div>
  );
}

const LABELS: Record<string, string> = {
  q: "Search", bb: "Buy box", mine: "Show", min_staff: "Staff ≥", max_staff: "Staff ≤", min_owner_age: "Owner aged ≥",
  ownership: "Ownership", region: "Region", status: "My status", min_score: "Score ≥", company_status: "Company status",
  sic: "Industry", min_years: "Years trading ≥", accounts_size: "Accounts", overdue: "Overdue", charges: "Charges",
  business_type: "Business type", has_website: "Website", tier: "Tier", changed_days: "Changed in (days)",
  change_kind: "Change", flag: "Flag", sold: "Recently sold", signal: "Signal", revenue: "Revenue source",
  wales: "Wales", min_revenue: "Revenue ≥", max_revenue: "Revenue ≤", min_profit: "Profit ≥", max_profit: "Profit ≤",
  min_net_assets: "Net assets ≥", min_cash: "Cash ≥", min_value: "Value ≥", max_value: "Value ≤",
};
const MONEY = new Set(["min_revenue", "max_revenue", "min_profit", "max_profit", "min_net_assets", "min_cash", "min_value", "max_value"]);
const VALUE_LABELS: Record<string, string> = {
  hide_closed: "hide not suitable / not now", pipeline: "my pipeline", untouched: "not looked at", all: "everything",
  any: "any presence", registered: "registered there", office: "office there", funding: "Welsh funding", director: "director there",
  filed: "filed", estimated: "estimate", none: "none", hide: "hide", only: "only", true: "yes", false: "no",
};

function money(v: string) {
  const n = Number(v);
  if (!isFinite(n)) return v;
  return n >= 1e6 ? `£${(n / 1e6).toFixed(n % 1e6 ? 1 : 0)}m` : n >= 1e3 ? `£${Math.round(n / 1e3)}k` : `£${n}`;
}

/** The filters that are set, as small removable chips (shown when the filters are folded away). */
export function ActiveChips({ query, keys, set, meta }: { query: Record<string, string>; keys: string[]; set: SetFn; meta?: any }) {
  const on = keys.filter((k) => query[k]);
  if (!on.length) return <span className="faint small">No filters set</span>;
  const boxName = (id: string) => meta?.buy_boxes?.find((b: any) => String(b.id) === id)?.name ?? id;
  return (
    <span className="chiprow">
      {on.map((k) => {
        const v = query[k];
        const shown = k === "bb" ? boxName(v) : MONEY.has(k) ? money(v) : k === "sic" ? v.split(",").join(", ") : VALUE_LABELS[v] ?? v;
        return (
          <span key={k} className="fchip">{LABELS[k] ?? k}{LABELS[k]?.endsWith("≥") || LABELS[k]?.endsWith("≤") ? " " : ": "}{shown}
            <button aria-label={`Remove ${LABELS[k] ?? k}`} onClick={() => set(k, null)}>×</button></span>
        );
      })}
    </span>
  );
}
