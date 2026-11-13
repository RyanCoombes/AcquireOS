import { useEffect, useState } from "react";
import { api, type Status } from "../api";
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
  likely_acquired: ["Signs of a sale", "red", "Directors living abroad appointed in the last 18 months, plus a new loan charge, a year-end change or new articles (here or at its holding company): usually a completed acquisition"],
  many_shareholders: ["Many shareholders", "amber", "10 or more shareholders on its latest statement: usually investor or employee-owned"],
};

const FUNDERS: Record<string, string> = {
  Wales: "Development Bank of Wales, Finance Wales or the Welsh Government",
  Scotland: "Scottish Enterprise, the Scottish National Investment Bank or HIE",
  "Northern Ireland": "Invest NI",
  England: "a regional fund such as NPIF, Midlands Engine or South West Investment Fund",
};

/** A place signal (office:, funding:, director: and a nation) as [label, tone, explanation], or null if not worth showing.
    Offices only where the company isn't registered; directors' homes only when you filter by them. */
export function placeSignal(k: string, region?: string | null, focus?: string | null): [string, string, string] | null {
  const [kind, nation] = k.split(":");
  if (!nation) return null;
  if (kind === "office") return nation === region ? null : [`Office in ${nation}`, "green", `An office or site in ${nation}, from research or the company's own website`];
  if (kind === "funding") return [`${nation} public funding`, "green", `Lending or investment from ${FUNDERS[nation] ?? "public funders"}, who only back businesses in ${nation}`];
  if (kind === "director") return focus === nation ? [`Director in ${nation}`, "grey", `A current director gives ${nation} as their country (a hint, not proof of an office)`] : null;
  return null;
}

export function Signals({ s, region, focus, titles }: { s?: string[] | null; region?: string | null; focus?: string | null; titles?: Record<string, string> }) {
  if (!s?.length) return null;
  const shown = s.map((k) => [k, SIGNALS[k] ?? placeSignal(k, region, focus)] as const).filter(([, v]) => v);
  return <>{shown.map(([k, v]) => <span key={k} className={`sig ${v![1]}`} title={titles?.[k] ?? v![2]}>{v![0]}</span>)}</>;
}

/** ☆ Watch / ★ Watching toggle for a company, owner or director. */
export function WatchButton({ kind, refId, on, label, onChange, small }: { kind: string; refId: string; on: boolean; label?: string; onChange?: () => void; small?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState(on);
  useEffect(() => setState(on), [on]);
  const toggle = async () => {
    setBusy(true);
    try {
      const { api } = await import("../api");
      if (state) await api.unwatch(kind, refId); else await api.watch(kind, refId, label);
      setState(!state); onChange?.();
    } finally { setBusy(false); }
  };
  return (
    <button className={`${small ? "watchsm" : "btn quiet"} ${state ? "watching" : ""}`} disabled={busy} onClick={toggle}
            title={state ? "Stop watching" : `Watch: alerts when ${kind === "company" ? "it changes" : "they take on or leave a company"}`}>
      {state ? "★ Watching" : "☆ Watch"}
    </button>
  );
}

/** ⓘ with the detail on hover or tap, so helper text doesn't take up lines. */
export function Hint({ text }: { text: string }) {
  return <span className="hint" tabIndex={0} role="note" aria-label={text} data-tip={text}>ⓘ</span>;
}

const LOGO_COLOURS = ["#3b6fd9", "#2b8a9a", "#c2702a", "#7a4fd6", "#1e9a57", "#8b4c7a", "#4b6584", "#b5543c"];
const SUFFIX = /\b(LIMITED|LTD|PLC|LLP|THE|UK|GROUP|HOLDINGS?)\b\.?/gi;
/** The company's logo from its own website (kept on the server), or coloured
 *  initials when it has none. A missing logo is fetched in the background, so
 *  it is asked for once more a few seconds later. */
export function Logo({ num, name, website, v, size = 28, always, version }: { num: string; name: string; website?: string | null;
                       v?: string | null; size?: number; always?: boolean; version?: number }) {
  // v (from the page's data): a number = the stored logo's version, kept by the browser for good;
  // "none" = nothing to show (no request); missing = not looked for yet (asked for once).
  // version: set by the logo popup after a change, to show the new one at once.
  const want = !!version || (v !== "none" && !!(website || always || v));
  const [state, setState] = useState<"try" | "wait" | "retry" | "none">(want ? "try" : "none");
  useEffect(() => { setState(want ? "try" : "none"); }, [num, website, want, v, version]);
  const words = name.replace(SUFFIX, "").trim().split(/\s+/).filter(Boolean);
  const initials = (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase();
  let h = 0; for (const ch of num) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const style = { width: size, height: size, fontSize: Math.round(size * 0.38) };
  if (state === "none" || state === "wait") return <span className="logo" aria-hidden style={{ ...style, background: LOGO_COLOURS[h % LOGO_COLOURS.length] }}>{initials}</span>;
  const base = `/api/companies/${encodeURIComponent(num)}/logo`;
  const src = version ? `${base}?changed=${version}`
    : v && v !== "none" ? `${base}?v=${v}`
    : `${base}?w=${encodeURIComponent(website ?? "")}${state === "retry" ? "&r=1" : ""}`;
  const pending = !version && !(v && v !== "none") && !!website;  // being looked for: ask once more shortly
  return <img className="logo img" src={src} alt="" style={style} loading="lazy"
              onError={() => { if (state === "try" && pending) { setState("wait"); setTimeout(() => setState((s) => s === "wait" ? "retry" : s), 8000); } else setState("none"); }} />;
}

/** The company page's logo: click it to fix a wrong one (use initials, use an
 *  image from a URL, or look on the website again). */
export function LogoEditor({ num, name, website, v, size = 40 }: { num: string; name: string; website?: string | null; v?: string | null; size?: number }) {
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(0);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [info, setInfo] = useState<{ status: string | null; source_url: string | null; manual: boolean | null; note: string | null } | null>(null);
  useEffect(() => { if (open) api.logoInfo(num).then(setInfo).catch(() => setInfo(null)); }, [open, num, version]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", esc); return () => window.removeEventListener("keydown", esc);
  }, [open]);
  const act = async (body: { action: "url" | "remove" | "refetch"; url?: string }) => {
    setBusy(true); setMsg(null);
    try { const r = await api.setLogo(num, body); setMsg(r.message); setVersion(Date.now()); if (body.action === "url") setUrl(""); }
    catch (e: any) { setMsg(e.message); }
    setBusy(false);
  };
  const from = info?.source_url ? info.source_url.replace(/^https?:\/\//, "") : null;
  return (
    <>
      <button className="logo-btn" title="Logo: click to change or remove" aria-label="Change logo" onClick={() => setOpen(true)}>
        <Logo num={num} name={name} website={website} v={v} size={size} always version={version || undefined} />
      </button>
      {open && (
        <div className="lgx-back" onClick={() => setOpen(false)}>
          <div className="lgx" role="dialog" aria-label="Logo" onClick={(e) => e.stopPropagation()}>
            <div className="lgx-head">
              <Logo num={num} name={name} website={website} v={v} size={64} always version={version || undefined} />
              <div>
                <b>Logo</b>
                <div className="faint small">
                  {info?.status === "found" ? <>{info.manual ? "Chosen by you" : "Found on the website"}{from ? <> · <a href={info.source_url!} target="_blank" rel="noreferrer">{from.length > 48 ? from.slice(0, 48) + "…" : from}</a></> : null}</>
                    : info?.manual ? "Removed by you: initials show" : website ? `None found on the website${info?.note ? ` (${info.note.toLowerCase()})` : ""}: initials show` : "No website saved: initials show"}
                </div>
              </div>
              <button className="lgx-x" aria-label="Close" onClick={() => setOpen(false)}>×</button>
            </div>
            <label className="small"><b>Use an image from a web address</b></label>
            <div className="lgx-row">
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Image address (right-click a logo, Copy image address)"
                     onKeyDown={(e) => { if (e.key === "Enter" && url.trim()) act({ action: "url", url }); }} />
              <button className="btn primary" disabled={busy || !url.trim()} onClick={() => act({ action: "url", url })}>Use</button>
            </div>
            <div className="lgx-row">
              {info?.status === "found" && <button className="btn" disabled={busy} onClick={() => act({ action: "remove" })}>Wrong logo: use initials</button>}
              {website && <button className="btn" disabled={busy} onClick={() => act({ action: "refetch" })}>{busy ? "Working…" : "Look on the website again"}</button>}
            </div>
            {msg && <div className="small" style={{ marginTop: 8 }}>{msg}</div>}
          </div>
        </div>
      )}
    </>
  );
}
