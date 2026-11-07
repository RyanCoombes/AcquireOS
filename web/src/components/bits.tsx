import { useEffect, useState } from "react";
import type { Status } from "../api";
import { FLAGS, toNum } from "../format";

export const STATUS_LABEL: Record<Status, string> = {
  new: "New", watching: "Watching", researching: "Assessing", approach: "Shortlisted",
  contacted: "First contact", in_talks: "Getting to know", nda: "NDA and accounts", offer: "Indicative offer",
  heads: "Heads of terms", diligence: "Due diligence", spa: "SPA and disclosure", completion: "Completion",
  handover: "Handover", passed: "Not now", rejected: "Not suitable",
};

export function StatusMark({ s }: { s: Status }) {
  return <span className={`status ${s}`}>{STATUS_LABEL[s] ?? s}</span>;
}

export function Score({ value, coverage }: { value: string | number | null; coverage?: string | number | null }) {
  const v = toNum(value);
  if (v === null) return <span className="faint">—</span>;
  const cov = toNum(coverage ?? null);
  return (
    <span className={`score ${v >= 70 ? "high" : v >= 40 ? "mid" : ""}`} title={cov !== null ? `Score ${v} · ${cov}% of criteria had data` : undefined}>
      <b>{Math.round(v)}</b>
      <span className="bar">
        <i style={{ width: `${Math.min(v, 100)}%` }} />
        {cov !== null && cov < 100 && <span className="cov" style={{ left: `${cov}%` }} />}
      </span>
    </span>
  );
}

export function Flags({ flags, address }: { flags?: string[] | null; address?: string | null }) {
  const shown = [...(flags ?? []).filter((f) => f !== "via_holdco" && f !== "no_psc_data"), ...(address ? [address] : [])];
  if (!shown.length) return null;
  return (
    <span className="flags">
      {shown.map((f) => (
        <span key={f} className={`flag ${["foreign_parent", "eot", "ch_default", "formation_agent"].includes(f) ? "red" : ""}`}>
          {FLAGS[f] ?? f}
        </span>
      ))}
    </span>
  );
}

export function Toast({ msg, onDone }: { msg: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onDone, 3200);
    return () => clearTimeout(t);
  }, [msg, onDone]);
  return msg ? <div className="toast" role="status">{msg}</div> : null;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn()
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e) => { if (live) setError(String(e.message ?? e)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}

export function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="callout red">{error}</div>;
}

/** Where a revenue figure comes from, as a pill: "Filed · Mar 2025" (from the
    company's own accounts) or "Estimate" (from staff numbers), with the method
    on hover. Imported figures say so. */
export function RevenueTag({ basis, method, long }: { basis?: string | null; method?: string | null; long?: boolean }) {
  if (!basis) return null;
  const m = method ?? "";
  const yr = m.match(/year to (?:\d{1,2} )?([A-Z][a-z]{2} \d{4})/)?.[1];
  const imported = m.startsWith("Imported");
  const label = basis === "filed" ? `Filed${yr ? ` · ${yr}` : ""}` : imported ? "Your file" : "Estimate";
  const tone = basis === "filed" ? "filed" : imported ? "imported" : "est";
  const title = basis === "filed" ? `Confirmed: ${m || "turnover as filed in the accounts"}`
    : imported ? m : `Not filed. ${m || "Estimated from staff numbers"}`;
  return (
    <>
      <span className={`revtag ${tone}`} title={title}>{basis === "filed" ? "✓ " : "≈ "}{label}</span>
      {long && basis !== "filed" && m && <div className="revhow">{m.replace(/^Staff \(/, "From staff (")}</div>}
    </>
  );
}

/** Signals worked out from the register: recently sold, possible buyer, many shareholders. */
export const SIGNALS: Record<string, [string, string, string]> = {
  recently_sold: ["Recently sold", "red", "A company became the owner as the previous owners left, in the last 3 years"],
  possible_buyer: ["Possible buyer", "blue", "Has taken control of established companies in the last 3 years: may be buying, not selling"],
  many_shareholders: ["Many shareholders", "amber", "10 or more shareholders on its latest statement: usually investor or employee-owned"],
};

export function Signals({ s }: { s?: string[] | null }) {
  if (!s?.length) return null;
  return <>{s.filter((k) => SIGNALS[k]).map((k) => (
    <span key={k} className={`sig ${SIGNALS[k][1]}`} title={SIGNALS[k][2]}>{SIGNALS[k][0]}</span>))}</>;
}
