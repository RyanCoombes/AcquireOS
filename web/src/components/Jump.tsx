// Jump box: Ctrl K (or Cmd K) from anywhere. Type a page, a buy box or a company and press Enter.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Meta } from "../api";

type Item = { label: string; kind: string; to: string; sub?: string };
const PAGES: [string, string, string][] = [
  ["Today", "/", "home dashboard"], ["Targets", "/targets", "find matches"], ["All companies", "/companies", "register directory"],
  ["Review", "/review", "go through one at a time"], ["Owners and directors", "/owners", "people"], ["Connections", "/connections", "links shared"],
  ["Map", "/map", ""], ["Deals", "/pipeline", "pipeline board"], ["Changes", "/changes", "watching alerts"], ["Watch list", "/watch", "watching"],
  ["Buy boxes", "/buy-box", "criteria scoring"], ["Data and updates", "/import", "import load refresh"], ["Reports", "/reports", ""], ["Connect AI", "/connect", "claude mcp"],
];

export default function Jump({ meta }: { meta: Meta | null }) {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setOpen((o) => !o); }
    };
    const ask = () => setOpen(true);
    window.addEventListener("keydown", key); window.addEventListener("ao-jump", ask);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("ao-jump", ask); };
  }, []);
  useEffect(() => { if (open) { setQ(""); setFound([]); setSel(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);

  const text = q.trim().toLowerCase();
  // Companies: asked for after a short pause, so typing stays quick.
  useEffect(() => {
    if (!open || text.length < 2) { setFound([]); setBusy(false); return; }
    let off = false; setBusy(true);
    const t = window.setTimeout(() => {
      api.companies({ q: q.trim(), limit: "6" }).then((r) => {
        if (off) return;
        setFound(r.rows.map((c) => ({ label: c.name, kind: "Company", to: `/c/${c.company_number}`, sub: [c.company_number, c.postcode].filter(Boolean).join(" · ") })));
      }).catch(() => { if (!off) setFound([]); }).finally(() => { if (!off) setBusy(false); });
    }, 220);
    return () => { off = true; window.clearTimeout(t); };
  }, [open, text]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;
  const pages: Item[] = PAGES.filter(([l, , words]) => !text || `${l} ${words}`.toLowerCase().includes(text)).map(([label, to]) => ({ label, kind: "Page", to }));
  const boxes: Item[] = (meta?.buy_boxes ?? []).filter((b) => b.is_active && text && b.name.toLowerCase().includes(text))
    .map((b) => ({ label: b.name, kind: "Buy box", to: `/targets?bb=${b.id}`, sub: "Targets in this buy box" }));
  const all: Item[] = text ? [...pages.slice(0, 5), ...boxes, ...found] : pages;
  if (text.length >= 2) all.push({ label: `Search all companies for “${q.trim()}”`, kind: "Search", to: `/companies?q=${encodeURIComponent(q.trim())}` });
  const at = Math.min(sel, all.length - 1);
  const go = (it?: Item) => { if (!it) return; setOpen(false); nav(it.to); };

  return (
    <div className="jump-back" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div className="jump" role="dialog" aria-label="Jump to a page or company">
        <div className="jump-q">
          <svg viewBox="0 0 24 24" aria-hidden><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          <input ref={input} value={q} placeholder="Jump to a page, buy box or company" aria-label="Jump to a page, buy box or company" autoComplete="off"
                 onChange={(e) => { setQ(e.target.value); setSel(0); }}
                 onKeyDown={(e) => {
                   if (e.key === "Escape") setOpen(false);
                   else if (e.key === "ArrowDown") { e.preventDefault(); setSel(Math.min(at + 1, all.length - 1)); }
                   else if (e.key === "ArrowUp") { e.preventDefault(); setSel(Math.max(at - 1, 0)); }
                   else if (e.key === "Enter") { e.preventDefault(); go(all[at]); }
                 }} />
          <span className="kbd" aria-hidden>Esc</span>
        </div>
        <ul>
          {all.map((it, i) => (
            <li key={it.kind + it.to}>
              <button className={i === at ? "on" : ""} aria-selected={i === at} onMouseEnter={() => setSel(i)} onClick={() => go(it)}>
                <span className="jl"><b>{it.label}</b>{it.sub && <span>{it.sub}</span>}</span><span className="jk">{it.kind}</span>
              </button>
            </li>
          ))}
          {busy && <li className="jump-note">Looking for companies…</li>}
        </ul>
      </div>
    </div>
  );
}
