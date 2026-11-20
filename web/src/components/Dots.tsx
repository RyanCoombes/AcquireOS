// The new look's dot field: a fine grid of dots behind an area with no words in it. Near the
// pointer the dots lean away, swell a little and take on the accent colour, then settle back.
// It draws on the element it is placed in (which must be position: relative) and listens there.
import { useEffect, useRef } from "react";
import { useSkin } from "../skin";

const GAP = 6, RAD = 1.05, STEPS = 10;
const rgb = (h: string) => [0, 2, 4].map((i) => parseInt(h.replace("#", "").substr(i, 2), 16));
const mix = (a: number[], b: number[], t: number) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

export default function Dots({ tone = "light", reach = 160 }: { tone?: "light" | "dark"; reach?: number }) {
  const { skin, accent, drift } = useSkin();
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current, host = cv?.parentElement, ctx = cv?.getContext("2d");
    if (!cv || !host || !ctx) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const base = document.createElement("canvas");
    const cold = tone === "dark" ? [38, 54, 80] : [214, 220, 228];
    const hot = tone === "dark" ? mix(rgb(accent), [255, 255, 255], 0.35) : rgb(accent);
    const shades = Array.from({ length: STEPS + 1 }, (_, i) => `rgb(${mix(cold, hot, i / STEPS).join(",")})`);
    let W = 0, H = 0, dpr = 1, tx = -1e4, ty = -1e4, x = -1e4, y = -1e4, k = 0, over = false, raf = 0, last = 0;
    let prev: { x0: number; y0: number; x1: number; y1: number } | null = null;
    const t0 = Math.random() * 1000;
    const snap = (v: number, up?: boolean) => (up ? Math.ceil(v / GAP) : Math.floor(v / GAP)) * GAP;

    const layout = () => {
      W = host.clientWidth; H = host.clientHeight;
      if (!W || !H) return;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (const c of [cv, base]) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
      const b = base.getContext("2d")!;
      b.setTransform(dpr, 0, 0, dpr, 0, 0); b.fillStyle = shades[0]; b.beginPath();
      for (let gy = GAP / 2; gy < H; gy += GAP) for (let gx = GAP / 2; gx < W; gx += GAP) { b.moveTo(gx + RAD, gy); b.arc(gx, gy, RAD, 0, 6.2832); }
      b.fill();
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height); ctx.drawImage(base, 0, 0);
      prev = null; kick();
    };
    // Only the patch around the pointer is redrawn each frame; the rest is the still copy.
    const draw = () => {
      const cur = k > 0.003 ? { x0: Math.max(0, snap(x - reach)), y0: Math.max(0, snap(y - reach)), x1: Math.min(snap(W, true), snap(x + reach, true)), y1: Math.min(snap(H, true), snap(y + reach, true)) } : null;
      for (const r of [prev, cur]) {
        if (!r || r.x1 <= r.x0 || r.y1 <= r.y0) continue;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        const sx = r.x0 * dpr, sy = r.y0 * dpr, sw = (r.x1 - r.x0) * dpr, sh = (r.y1 - r.y0) * dpr;
        ctx.clearRect(sx, sy, sw, sh); ctx.drawImage(base, sx, sy, sw, sh, sx, sy, sw, sh);
      }
      prev = cur;
      if (!cur || cur.x1 <= cur.x0 || cur.y1 <= cur.y0) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(cur.x0, cur.y0, cur.x1 - cur.x0, cur.y1 - cur.y0);
      const paths = shades.map(() => new Path2D());
      for (let gy = cur.y0 + GAP / 2; gy < cur.y1; gy += GAP) for (let gx = cur.x0 + GAP / 2; gx < cur.x1; gx += GAP) {
        const dx = gx - x, dy = gy - y, d = Math.sqrt(dx * dx + dy * dy), u = d / reach;
        let c = 0;
        if (u < 1) { const s = 1 - u * u * (3 - 2 * u); c = s * s * s * k; }
        let px = gx, py = gy, pr = RAD;
        if (c > 0.004 && d > 0.01) { px += (dx / d) * GAP * 1.5 * c; py += (dy / d) * GAP * 1.5 * c; pr = RAD * (1 + 0.5 * c); }
        const p = paths[Math.min(STEPS, Math.round(c * STEPS))];
        p.moveTo(px + pr, py); p.arc(px, py, pr, 0, 6.2832);
      }
      paths.forEach((p, i) => { ctx.fillStyle = shades[i]; ctx.fill(p); });
    };
    const frame = (now: number) => {
      raf = 0;
      if (!host.offsetParent && getComputedStyle(host).position !== "fixed" && getComputedStyle(host).position !== "sticky") return;
      const dt = Math.min(0.1, Math.max(0.001, (now - last) / 1000)); last = now;
      const idle = !over && drift && !still && !document.hidden;
      if (idle) {
        const t = now / 1000 + t0;
        tx = W * (0.5 + 0.42 * Math.sin(t * 0.21)); ty = H * (0.5 + 0.38 * Math.sin(t * 0.33 + 1.3));
        if (k < 0.01) { x = tx; y = ty; }
      }
      const want = over ? 1 : idle ? 0.55 : 0;
      const a = 1 - Math.pow(0.8, 60 * dt), b = 1 - Math.pow(0.9, 60 * dt);
      x += (tx - x) * a; y += (ty - y) * a; k += (want - k) * b;
      if (want === 0 && k < 0.003) k = 0;
      draw();
      if (idle || Math.abs(tx - x) > 0.2 || Math.abs(ty - y) > 0.2 || Math.abs(want - k) > 0.003) kick();
    };
    function kick() { if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); } }
    const move = (e: PointerEvent) => {
      const r = cv.getBoundingClientRect(); tx = e.clientX - r.left; ty = e.clientY - r.top;
      if (!over) { over = true; if (k < 0.01) { x = tx; y = ty; } }
      kick();
    };
    const leave = () => { over = false; kick(); };
    if (!still) { host.addEventListener("pointermove", move); host.addEventListener("pointerleave", leave); }
    const ro = new ResizeObserver(layout); ro.observe(host);
    return () => { ro.disconnect(); cancelAnimationFrame(raf); host.removeEventListener("pointermove", move); host.removeEventListener("pointerleave", leave); };
  }, [skin, accent, drift, tone, reach]);
  if (skin !== "ledger") return null;
  return <canvas ref={ref} className="dotfield" aria-hidden />;
}
