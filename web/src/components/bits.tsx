import { useEffect, useState } from "react";
import type { Status } from "../api";
import { FLAGS, toNum } from "../format";

export const STATUS_LABEL: Record<Status, string> = {
  new: "New", watching: "Watching", researching: "Assessing", approach: "Shortlisted",
  contacted: "First contact", in_talks: "Getting to know", nda: "NDA and accounts", offer: "Indicative offer",
  heads: "Heads of terms", diligence: "Due diligence", spa: "SPA and disclosure", completion: "Completion",
  handover: "Handover", passed: "Passed", rejected: "Rejected",
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
    <span>
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
