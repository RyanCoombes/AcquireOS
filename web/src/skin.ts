// The look of the app: the classic one, or the new "ledger" look being tried out.
// Remembered per browser; nothing about your data changes with it.
import { useEffect, useState } from "react";

export type Skin = "classic" | "ledger";
export const ACCENTS: [string, string][] = [["#0f7a5c", "Green"], ["#2f4fd8", "Blue"], ["#b4532a", "Rust"], ["#6d3fc4", "Purple"], ["#e8336d", "Pink"]];

const read = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
export const getSkin = (): Skin => (read("ao.skin", "classic") === "ledger" ? "ledger" : "classic");
// One of the listed colours, or any colour you picked yourself.
export const getAccent = () => { const a = read("ao.accent", ACCENTS[0][0]).toLowerCase(); return /^#[0-9a-f]{6}$/.test(a) ? a : ACCENTS[0][0]; };

// How the new look's navigation is drawn: the icon rail, live tiles, or tabs up the edge.
export type NavStyle = "rail" | "live" | "tabs" | "dock";
export const NAVS: [NavStyle, string, string][] = [
  ["rail", "Icons", "The dark rail with an icon for each section"],
  ["live", "Live", "Each section shows what is in it right now"],
  ["tabs", "Tabs", "Section names up the edge, like ledger tabs"],
  ["dock", "Dock", "A floating bar at the bottom; the page gets the full width"],
];
export const getNav = (): NavStyle => { const n = read("ao.nav", "rail"); return n === "live" || n === "tabs" || n === "dock" ? n : "rail"; };

// Effects: how strong the colour glow is, and whether the dots drift when the pointer is still.
export type Glow = "off" | "soft" | "full";
export const GLOWS: [Glow, string, number][] = [["off", "Off", 0], ["soft", "Soft", 0.55], ["full", "Full", 1]];
export const getGlow = (): Glow => { const g = read("ao.glow", "soft"); return g === "off" || g === "full" ? g : "soft"; };
export const getDrift = () => read("ao.drift", "off") === "on";

export function applySkin() {
  const root = document.documentElement;
  const skin = getSkin();
  root.dataset.skin = skin;
  if (skin === "ledger") root.dataset.nav = getNav(); else delete root.dataset.nav;
  if (skin === "ledger") {
    root.style.setProperty("--accent", getAccent());
    root.style.setProperty("--glow-k", String(GLOWS.find(([g]) => g === getGlow())![2]));
  } else { root.style.removeProperty("--accent"); root.style.removeProperty("--glow-k"); }
}

export function setSkin(skin: Skin, accent?: string) {
  try { localStorage.setItem("ao.skin", skin); if (accent) localStorage.setItem("ao.accent", accent); } catch { /* private window */ }
  applySkin();
  window.dispatchEvent(new Event("ao-skin"));
}

export function setEffects(v: { glow?: Glow; drift?: boolean }) {
  try {
    if (v.glow) localStorage.setItem("ao.glow", v.glow);
    if (v.drift !== undefined) localStorage.setItem("ao.drift", v.drift ? "on" : "off");
  } catch { /* private window */ }
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

export function useSkin(): { skin: Skin; accent: string; nav: NavStyle; glow: Glow; drift: boolean } {
  const [v, setV] = useState({ skin: getSkin(), accent: getAccent(), nav: getNav(), glow: getGlow(), drift: getDrift() });
  useEffect(() => {
    const on = () => setV({ skin: getSkin(), accent: getAccent(), nav: getNav(), glow: getGlow(), drift: getDrift() });
    window.addEventListener("ao-skin", on);
    return () => window.removeEventListener("ao-skin", on);
  }, []);
  return v;
}
