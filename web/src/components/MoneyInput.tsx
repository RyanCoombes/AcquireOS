/* A money field: shows £1,250,000, accepts "1.25m", "750k", "£1,250,000". */
import { useEffect, useState } from "react";
import { money } from "../format";

export function parseMoney(text: string): number | null {
  const t = text.trim().toLowerCase().replace(/[£,\s]/g, "");
  if (!t) return null;
  const m = t.match(/^(-?\d*\.?\d+)(k|m|bn|b)?$/);
  if (!m) return null;
  const mult = { k: 1e3, m: 1e6, b: 1e9, bn: 1e9 }[m[2] as "k" | "m" | "b" | "bn"] ?? 1;
  return Math.round(parseFloat(m[1]) * mult);
}

export const fmtMoney = (n: number | null | undefined) =>
  n === null || n === undefined || Number.isNaN(n) ? "" : "£" + Math.round(n).toLocaleString("en-GB");

export default function MoneyInput({
  value, onChange, placeholder, width = 150, commit = "change", hint = true, ...rest
}: {
  value: number | null | undefined; onChange: (v: number | null) => void; placeholder?: string; width?: number;
  /** "change": report as you type; "blur": report when leaving the field or pressing Enter */
  commit?: "change" | "blur"; hint?: boolean; "aria-label"?: string; id?: string;
}) {
  const [text, setText] = useState(fmtMoney(value ?? null));
  const [focus, setFocus] = useState(false);
  useEffect(() => { if (!focus) setText(fmtMoney(value ?? null)); }, [value, focus]);
  const parsed = parseMoney(text);
  const bad = text.trim() !== "" && parsed === null;
  const send = () => { if (!bad) onChange(parsed); };
  return (
    <span className="moneyinput">
      <input type="text" inputMode="decimal" style={{ width }} value={text} placeholder={placeholder}
             className={bad ? "bad" : ""} {...rest}
             onFocus={() => setFocus(true)}
             onChange={(e) => {
               setText(e.target.value);
               const p = parseMoney(e.target.value);
               if (commit === "change" && (p !== null || e.target.value.trim() === "")) onChange(p);
             }}
             onBlur={() => { setFocus(false); send(); setText(fmtMoney(bad ? (value ?? null) : parsed)); }}
             onKeyDown={(e) => { if (e.key === "Enter") { send(); (e.target as HTMLInputElement).blur(); } }} />
      {hint && focus && parsed !== null && parsed >= 1000 && <span className="mi-hint">= {money(parsed)}</span>}
    </span>
  );
}
