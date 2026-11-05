/* Pick SIC codes by name or number. Each choice shows as a removable tag
   ("62020 · Information technology consultancy activities"). A two-digit
   division (e.g. 62) or a partial code (620) matches every code under it. */
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";

export interface SicOption { code: string; description: string; level: string; n: number; in_scope: number }

let cache: Promise<SicOption[]> | null = null;
export function loadSic() {
  if (!cache) cache = api.sic().then((x) => x as unknown as SicOption[]).catch(() => { cache = null; return []; });
  return cache;
}

export function sicLabel(code: string, opts: SicOption[]): string {
  const exact = opts.find((o) => o.code === code);
  if (exact?.description) return exact.description;
  const under = opts.filter((o) => o.level === "code" && o.code.startsWith(code));
  if (under.length === 1) return under[0].description;
  const div = opts.find((o) => o.level === "division" && o.code === code.slice(0, 2));
  if (under.length > 1) return `${under.length} codes · ${div?.description ?? ""}`;
  return div ? `Codes starting ${code} · ${div.description}` : "";
}

export default function SicPicker({
  value, onChange, placeholder = "Search by name or code, e.g. software or 620", width,
}: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; width?: number | string }) {
  const [opts, setOpts] = useState<SicOption[]>([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { loadSic().then(setOpts); }, []);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const matches = useMemo(() => {
    const t = q.trim().toLowerCase();
    const words = t.split(/\s+/).filter(Boolean);
    let list = opts.filter((o) => !value.includes(o.code));
    if (t) {
      list = list.filter((o) => o.code.startsWith(t.replace(/\s/g, "")) ||
        words.every((w) => o.description.toLowerCase().includes(w)));
      // codes that start with what was typed come first, then by companies
      list.sort((a, b) => (Number(b.code.startsWith(t)) - Number(a.code.startsWith(t))) || (b.n - a.n));
    }
    const out = list.slice(0, 60);
    // A typed number that is not an existing code can be added as a prefix.
    if (/^\d{2,5}$/.test(t) && !opts.some((o) => o.code === t) && !value.includes(t)) {
      out.unshift({ code: t, description: `Every code starting ${t}`, level: "prefix", n: 0, in_scope: 0 });
    }
    return out;
  }, [opts, q, value]);
  useEffect(() => setHi(0), [q]);

  const add = (code: string) => { onChange([...value, code]); setQ(""); setHi(0); };
  const remove = (code: string) => onChange(value.filter((v) => v !== code));

  return (
    <div className="sicpicker" ref={box} style={{ width }}>
      <div className="sp-box" onClick={() => setOpen(true)}>
        {value.map((code) => (
          <span key={code} className="sp-tag" title={sicLabel(code, opts)}>
            <b>{code}</b><span className="sp-name">{sicLabel(code, opts) || (code.length < 5 ? "prefix" : "")}</span>
            <button type="button" aria-label={`Remove ${code}`} onClick={(e) => { e.stopPropagation(); remove(code); }}>×</button>
          </span>
        ))}
        <input
          value={q} placeholder={value.length ? "Add another…" : placeholder}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, matches.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); if (matches[hi]) add(matches[hi].code); }
            else if (e.key === "Backspace" && !q && value.length) remove(value[value.length - 1]);
            else if (e.key === "Escape") setOpen(false);
          }}
          aria-label="Search SIC codes"
        />
      </div>
      {open && matches.length > 0 && (
        <ul className="sp-list" role="listbox">
          {matches.map((o, i) => (
            <li key={o.code} role="option" aria-selected={i === hi} className={i === hi ? "hi" : ""}
                onMouseEnter={() => setHi(i)} onMouseDown={(e) => { e.preventDefault(); add(o.code); }}>
              <b>{o.code}</b>
              <span className="sp-desc">{o.description}{o.level === "division" ? <span className="faint"> · all codes in division</span> : null}</span>
              <span className="sp-n">{o.n ? o.n.toLocaleString("en-GB") : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
