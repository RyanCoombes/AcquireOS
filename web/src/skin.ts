// The look of the app: the classic one, or the new "ledger" look being tried out.
// Remembered per browser; nothing about your data changes with it.
import { useEffect, useState } from "react";

export type Skin = "classic" | "ledger";
export const ACCENTS: [string, string][] = [["#0f7a5c", "Green"], ["#2f4fd8", "Blue"], ["#b4532a", "Rust"], ["#6d3fc4", "Purple"]];

const read = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
export const getSkin = (): Skin => (read("ao.skin", "classic") === "ledger" ? "ledger" : "classic");
export const getAccent = () => { const a = read("ao.accent", ACCENTS[0][0]); return ACCENTS.some(([c]) => c === a) ? a : ACCENTS[0][0]; };

// How the new look's navigation is drawn: the icon rail, live tiles, or tabs up the edge.
export type NavStyle = "rail" | "live" | "tabs";
export const NAVS: [NavStyle, string, string][] = [
  ["rail", "Icons", "The dark rail with an icon for each section"],
  ["live", "Live", "Each section shows what is in it right now"],
  ["tabs", "Tabs", "Section names up the edge, like ledger tabs"],
];
export const getNav = (): NavStyle => { const n = read("ao.nav", "rail"); return n === "live" || n === "tabs" ? n : "rail"; };

export function applySkin() {
  const root = document.documentElement;
  const skin = getSkin();
  root.dataset.skin = skin;
  if (skin === "ledger") root.dataset.nav = getNav(); else delete root.dataset.nav;
  if (skin === "ledger") root.style.setProperty("--accent", getAccent()); else root.style.removeProperty("--accent");
}

export function setSkin(skin: Skin, accent?: string) {
  try { localStorage.setItem("ao.skin", skin); if (accent) localStorage.setItem("ao.accent", accent); } catch { /* private window */ }
  applySkin();
  window.dispatchEvent(new Event("ao-skin"));
}

export function setNav(nav: NavStyle) {
  try { localStorage.setItem("ao.nav", nav); } catch { /* private window */ }
  applySkin();
  window.dispatchEvent(new Event("ao-skin"));
}

// Companies you opened last, newest first (this browser only), for the Live navigation.
export type Recent = { num: string; name: string };
export const getRecent = (): Recent[] => {
  try { const v = JSON.parse(read("ao.recent", "[]")); return Array.isArray(v) ? v.filter((r) => r && r.num && r.name).slice(0, 5) : []; } catch { return []; }
};
export function noteRecent(num: string, name: string) {
  try {
    localStorage.setItem("ao.recent", JSON.stringify([{ num, name }, ...getRecent().filter((r) => r.num !== num)].slice(0, 5)));
    window.dispatchEvent(new Event("ao-recent"));
  } catch { /* private window */ }
}

export function useSkin(): { skin: Skin; accent: string; nav: NavStyle } {
  const [v, setV] = useState({ skin: getSkin(), accent: getAccent(), nav: getNav() });
  useEffect(() => {
    const on = () => setV({ skin: getSkin(), accent: getAccent(), nav: getNav() });
    window.addEventListener("ao-skin", on);
    return () => window.removeEventListener("ao-skin", on);
  }, []);
  return v;
}
