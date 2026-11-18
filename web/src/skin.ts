// The look of the app: the classic one, or the new "ledger" look being tried out.
// Remembered per browser; nothing about your data changes with it.
import { useEffect, useState } from "react";

export type Skin = "classic" | "ledger";
export const ACCENTS: [string, string][] = [["#0f7a5c", "Green"], ["#2f4fd8", "Blue"], ["#b4532a", "Rust"], ["#6d3fc4", "Purple"]];

const read = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
export const getSkin = (): Skin => (read("ao.skin", "classic") === "ledger" ? "ledger" : "classic");
export const getAccent = () => { const a = read("ao.accent", ACCENTS[0][0]); return ACCENTS.some(([c]) => c === a) ? a : ACCENTS[0][0]; };

export function applySkin() {
  const root = document.documentElement;
  const skin = getSkin();
  root.dataset.skin = skin;
  if (skin === "ledger") root.style.setProperty("--accent", getAccent()); else root.style.removeProperty("--accent");
}

export function setSkin(skin: Skin, accent?: string) {
  try { localStorage.setItem("ao.skin", skin); if (accent) localStorage.setItem("ao.accent", accent); } catch { /* private window */ }
  applySkin();
  window.dispatchEvent(new Event("ao-skin"));
}

export function useSkin(): { skin: Skin; accent: string } {
  const [v, setV] = useState({ skin: getSkin(), accent: getAccent() });
  useEffect(() => {
    const on = () => setV({ skin: getSkin(), accent: getAccent() });
    window.addEventListener("ao-skin", on);
    return () => window.removeEventListener("ao-skin", on);
  }, []);
  return v;
}
