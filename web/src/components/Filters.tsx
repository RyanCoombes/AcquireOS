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
    <fieldset className="fgroup">
      <legend><span className="fg-ico" aria-hidden>{icon}</span>{title}{n ? <span className="fg-n">{n}</span> : null}</legend>
      <div className="fg-body">{children}</div>
    </fieldset>
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
