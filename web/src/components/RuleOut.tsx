import { useEffect, useRef, useState } from "react";
import { api } from "../api";

/** Reasons for ruling a company out, kept in its history. */
export const NOT_SUITABLE = ["Too small", "Too big", "Wrong sector", "Already sold", "Not owner-run", "Investor-backed", "Weak finances", "Wrong location"];
export const NOT_NOW = ["Owner not ready", "Owner said no", "Timing", "Revisit next year"];

export type RuleOutPick = { status: "rejected" | "passed"; stage_note: string };
export const pickNote = (st: "rejected" | "passed", why: string): RuleOutPick =>
  ({ status: st, stage_note: `${st === "rejected" ? "Not suitable" : "Not now"}: ${why}` });

/** The companies in the list you opened this one from, so ruling it out can move on to the next. */
export function rememberList(numbers: string[], from: string) {
  try { sessionStorage.setItem("ao.list", JSON.stringify({ numbers, from })); } catch { /* ignore */ }
}
export function nextInList(num: string): string | null {
  try {
    const l = JSON.parse(sessionStorage.getItem("ao.list") ?? "null") as { numbers: string[] } | null;
    if (!l) return null;
    const i = l.numbers.indexOf(num);
    return i >= 0 && i + 1 < l.numbers.length ? l.numbers[i + 1] : null;
  } catch { return null; }
}
export function listFrom(): string | null {
  try { return (JSON.parse(sessionStorage.getItem("ao.list") ?? "null") as { from: string } | null)?.from ?? null; } catch { return null; }
}

/** One click: each reason is a button. */
export function RuleOutChips({ onPick, compact }: { onPick: (p: RuleOutPick) => void; compact?: boolean }) {
  const [other, setOther] = useState("");
  return (
    <div className={`ruleout ${compact ? "compact" : ""}`}>
      <div className="grp"><span className="lbl red">✕ Not suitable</span>
        {NOT_SUITABLE.map((r) => <button key={r} className="chipbtn" onClick={() => onPick(pickNote("rejected", r))}>{r}</button>)}
      </div>
      <div className="grp"><span className="lbl">⏸ Not now</span>
        {NOT_NOW.map((r) => <button key={r} className="chipbtn" onClick={() => onPick(pickNote("passed", r))}>{r}</button>)}
      </div>
      <form className="grp" onSubmit={(e) => { e.preventDefault(); if (other.trim()) { onPick(pickNote("rejected", other.trim())); setOther(""); } }}>
        <input type="text" value={other} placeholder="Other reason…" aria-label="Other reason for ruling it out" onChange={(e) => setOther(e.target.value)} />
        {other.trim() && <button className="chipbtn" type="submit">Not suitable</button>}
      </form>
    </div>
  );
}

/** For a list row: a small ✕ that opens the reasons, without opening the company. */
export function RuleOutMenu({ num, name, onDone }: { num: string; name: string; onDone: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const pick = async (p: RuleOutPick) => {
    setOpen(false);
    try { await api.setState(num, p); onDone(`${name}: ${p.stage_note}`); } catch (e: any) { onDone(`Not saved: ${e.message}`); }
  };
  return (
    <div className="rowmenu" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button className="xbtn" title="Rule out (not suitable or not now)" aria-label={`Rule out ${name}`} aria-expanded={open}
              onClick={() => setOpen(!open)}>✕</button>
      {open && <div className="pop"><RuleOutChips onPick={pick} compact /></div>}
    </div>
  );
}
