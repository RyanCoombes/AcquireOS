/* Financials: tabs, each with a chart and the full table of every year. */
import type React from "react";
import { useState } from "react";
import type { CompanyDetail } from "../api";
import { date, int, money } from "../format";
import { Hint } from "./bits";
import { BalanceChart } from "./Profile";

type F = CompanyDetail["financials"][number];
type Val = number | null;
const n = (v: unknown): Val => (v === null || v === undefined || v === "" ? null : Number(v));
const da = (f: F) => n(f.depreciation_amortisation) ?? (n(f.depreciation) !== null || n(f.amortisation) !== null ? (n(f.depreciation) ?? 0) + (n(f.amortisation) ?? 0) : null);
const ebitda = (f: F) => (n(f.operating_profit) !== null && da(f) !== null ? n(f.operating_profit)! + da(f)! : null);
const bank = (f: F) => (n(f.bank_loans) !== null || n(f.bank_overdrafts) !== null ? (n(f.bank_loans) ?? 0) + (n(f.bank_overdrafts) ?? 0) : null);
const withinYr = (f: F): Val => n(f.creditors_within) ?? (n(f.current_assets) !== null && n(f.net_current_assets) !== null && n(f.current_assets)! - n(f.net_current_assets)! >= 0 ? n(f.current_assets)! - n(f.net_current_assets)! : null);
const afterYr = (f: F): Val => n(f.creditors_after) ?? (n(f.total_assets_less_cl) !== null && n(f.net_assets) !== null && n(f.total_assets_less_cl)! - n(f.net_assets)! >= 0 ? n(f.total_assets_less_cl)! - n(f.net_assets)! : null);

type Row = { label: string; get: (f: F, i: number) => Val; key?: boolean; change?: boolean; fmt?: "money" | "int" | "pct"; hint?: string; est?: (i: number) => boolean };
type Tab = { key: string; label: string; rows: Row[]; chart?: (ys: Year[]) => React.ReactNode };
type Year = { f: F; label: string; turnover: Val; turnoverEst: boolean };

export default function Financials({ data }: { data: CompanyDetail }) {
  const fin = data.financials.filter((f) => !f.period_inferred);
  const est = new Map((data.fin_summary?.series ?? []).filter((r) => r.turnover == null && r.turnover_est != null)
    .map((r) => [String(r.period_end).slice(0, 10), r.turnover_est as number]));
  const ys: Year[] = fin.map((f) => {
    const e = f.turnover == null ? est.get(String(f.period_end).slice(0, 10)) ?? null : null;
    return { f, label: new Date(f.period_end).toLocaleDateString("en-GB", fin.length > 8 ? { year: "numeric" } : { month: "short", year: "numeric" }),
             turnover: n(f.turnover) ?? e, turnoverEst: f.turnover == null && e != null };
  });
  // Totals small accounts imply but rarely state (from the summary): assets, liabilities, debt ratio.
  const der = new Map((data.fin_summary?.series ?? []).map((r: any) => [String(r.period_end).slice(0, 10), r]));
  const dv = (f: F, k: "total_assets" | "total_liabilities" | "debt_ratio") => { const r: any = der.get(String(f.period_end).slice(0, 10)); return r && r[k] != null ? Number(r[k]) : null; };
  const [tab, setTab] = useState("ov");
  const [view, setView] = useState<"chart" | "table">("chart");
  // Figures in £m (£4.97m) or in full (£4,970,123); remembered.
  const [full, setFullState] = useState(() => { try { return localStorage.getItem("ao.figures") === "full"; } catch { return false; } });
  const setFull = (v: boolean) => { setFullState(v); try { localStorage.setItem("ao.figures", v ? "full" : "short"); } catch { /* ignore */ } };
  if (!ys.length) return <div className="faint">No accounts on file.</div>;

  const turnoverRow: Row = { label: "Turnover", get: (_f, i) => ys[i].turnover, change: true, est: (i) => ys[i].turnoverEst, key: false };
  const pos = (f: F) => (n(f.turnover) !== null && n(f.turnover)! > 0 ? n(f.turnover)! : null);
  const sane = (m: number | null) => (m !== null && m >= -100 && m <= 100 ? m : null);
  const margin = (y: Year) => { const e = ebitda(y.f) ?? n(y.f.operating_profit); return e !== null && pos(y.f) ? sane((100 * e) / pos(y.f)!) : null; };
  const tabs: Tab[] = [
    { key: "pl", label: "Revenue & profit", rows: [
        turnoverRow,
        { label: "Gross profit", get: (f) => n(f.gross_profit) },
        { label: "Operating profit", get: (f) => n(f.operating_profit), change: true },
        { label: "Depreciation and amortisation", get: (f) => da(f) },
        { label: "EBITDA", get: (f) => ebitda(f), key: true, change: true, hint: "Operating profit + depreciation and amortisation, both filed" },
        { label: "EBITDA margin", get: (_f, i) => (ebitda(ys[i].f) !== null && pos(ys[i].f) ? sane((100 * ebitda(ys[i].f)!) / pos(ys[i].f)!) : null), fmt: "pct" },
        { label: "Interest paid", get: (f) => n(f.interest_payable) },
        { label: "Tax", get: (f) => n(f.tax) },
        { label: "Profit after tax", get: (f) => n(f.profit_loss), change: true },
        { label: "Dividends paid", get: (f) => n(f.dividends), hint: "Often how owners pay themselves" },
      ],
      chart: (ys) => <ComboChart years={ys.map((y) => y.label)}
        bars={[{ label: "Revenue", values: ys.map((y) => y.turnover), est: ys.map((y) => y.turnoverEst), colour: "#0e7c6b" }]}
        line={{ label: ys.some((y) => ebitda(y.f) !== null) ? "EBITDA margin" : "Operating margin", values: ys.map(margin), fmt: "pct" }} /> },
    { key: "bs", label: "Balance sheet", rows: [
        { label: "Fixed assets", get: (f) => n(f.fixed_assets) },
        { label: "of which intangible", get: (f) => n(f.intangible_assets) },
        { label: "Stock", get: (f) => n(f.stock) },
        { label: "Trade debtors", get: (f) => n(f.trade_debtors) },
        { label: "Debtors (all)", get: (f) => n(f.debtors) },
        { label: "Cash", get: (f) => n(f.cash) },
        { label: "Current assets", get: (f) => n(f.current_assets) },
        { label: "Trade creditors", get: (f) => n(f.trade_creditors) },
        { label: "Owed within a year", get: (f) => withinYr(f) },
        { label: "Net current assets", get: (f) => n(f.net_current_assets) },
        { label: "Owed after a year", get: (f) => afterYr(f) },
        { label: "Retained earnings", get: (f) => n(f.retained_earnings), hint: "Profits kept in the business" },
        { label: "Share capital", get: (f) => n(f.share_capital) },
        { label: "Total assets", get: (f) => dv(f, "total_assets"), hint: "Fixed plus current assets" },
        { label: "Total liabilities", get: (f) => dv(f, "total_liabilities"), hint: "Everything owed: total assets less net assets" },
        { label: "Net assets (net worth)", get: (f) => n(f.net_assets), key: true, change: true },
      ],
      chart: (ys) => <LinesChart memo="bs" years={ys.map((y) => y.label)} series={[
        { label: "Net worth (net assets)", values: ys.map((y) => n(y.f.net_assets)), colour: "#16213a", strong: true },
        { label: "Total assets", values: ys.map((y) => dv(y.f, "total_assets")), colour: "#0e7c6b" },
        { label: "Total liabilities", values: ys.map((y) => dv(y.f, "total_liabilities")), colour: "#c8352b" },
        { label: "Cash", values: ys.map((y) => n(y.f.cash)), colour: "#c98a2b", dashed: true },
        { label: "Current assets", values: ys.map((y) => n(y.f.current_assets)), colour: "#2f62d8", off: true },
        { label: "Fixed assets", values: ys.map((y) => n(y.f.fixed_assets)), colour: "#7a5af8", off: true },
        { label: "Owed within a year", values: ys.map((y) => withinYr(y.f)), colour: "#e07b39", off: true },
        { label: "Owed after a year", values: ys.map((y) => afterYr(y.f)), colour: "#9c2f6b", off: true },
        { label: "Net current assets", values: ys.map((y) => n(y.f.net_current_assets)), colour: "#3aa6a0", off: true, dashed: true },
        { label: "Debtors", values: ys.map((y) => n(y.f.debtors)), colour: "#8a6d3b", off: true },
        { label: "Stock", values: ys.map((y) => n(y.f.stock)), colour: "#6b7280", off: true },
      ]} /> },
    { key: "cash", label: "Cash & debt", rows: [
        { label: "Cash", get: (f) => n(f.cash), key: true, change: true },
        { label: "Bank loans and overdrafts", get: (f) => bank(f), key: true, hint: "Repaid from the price on a cash-free, debt-free deal" },
        { label: "Net cash (cash less bank debt)", get: (f) => (n(f.cash) !== null ? n(f.cash)! - (bank(f) ?? 0) : null) },
        { label: "Owed within a year", get: (f) => withinYr(f) },
        { label: "Owed after a year", get: (f) => afterYr(f) },
        { label: "Interest paid", get: (f) => n(f.interest_payable) },
        { label: "Debt ratio", get: (f) => dv(f, "debt_ratio"), fmt: "pct", hint: "Total liabilities ÷ total assets: under 50% means it owns more than it owes" },
      ],
      chart: (ys) => <ComboChart years={ys.map((y) => y.label)}
        bars={[{ label: "Cash", values: ys.map((y) => n(y.f.cash)), colour: "#0e7c6b" },
               { label: "Bank debt", values: ys.map((y) => bank(y.f)), colour: "#c8352b" }]}
        line={{ label: "Debt ratio (liabilities ÷ assets)", values: ys.map((y) => dv(y.f, "debt_ratio")), fmt: "pct" }} /> },
    { key: "staff", label: "Staff & pay", rows: [
        { label: "Average staff", get: (f) => n(f.employees), fmt: "int", key: true, change: true },
        { label: "Revenue per head", get: (f) => (n(f.turnover) && n(f.employees) ? n(f.turnover)! / n(f.employees)! : null),
          hint: "Filed turnover only: estimated years are worked out from staff × revenue per head, so they can't show a trend" },
        { label: "Staff costs", get: (f) => n(f.staff_costs) },
        { label: "Cost per head", get: (f) => (n(f.staff_costs) && n(f.employees) ? n(f.staff_costs)! / n(f.employees)! : null) },
        { label: "Directors' pay", get: (f) => n(f.director_pay) },
      ],
      chart: (ys) => <ComboChart years={ys.map((y) => y.label)}
        bars={[{ label: "Staff", values: ys.map((y) => n(y.f.employees)), colour: "#2f62d8", fmt: "int" }]}
        line={{ label: "Revenue per head (filed years)", values: ys.map((y) => (n(y.f.turnover) && n(y.f.employees) ? n(y.f.turnover)! / n(y.f.employees)! : null)), fmt: "money" }} /> },
  ];
  const allRows: Row[] = [...tabs[0].rows, ...tabs[1].rows, ...tabs[3].rows, { label: "Bank loans and overdrafts", get: (f: F) => bank(f) }];
  const all: Tab = { key: "all", label: "All figures", rows: allRows.filter((r, i, arr) => arr.findIndex((x) => x.label === r.label) === i) };
  const overview: Tab = { key: "ov", label: "Overview", rows: [] };
  const shown = [...(data.fin_summary?.rows?.length ? [overview] : []), ...tabs, all].map((t) => ({ ...t, rows: t.rows.filter((r) => ys.some((y, i) => r.get(y.f, i) !== null)) }))
    .filter((t) => t.key === "ov" || t.rows.length > 0);
  const cur = shown.find((t) => t.key === tab) ?? shown[0];

  return (
    <div className="fin2">
      <div className="fin2-top">
        <div className="tabs2" role="tablist">
          {shown.map((t) => <button key={t.key} role="tab" aria-selected={t.key === cur.key} className={t.key === cur.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label}</button>)}
        </div>
        <span className="fin2-opts">
        {cur.chart && cur.key !== "ov" && <span className="seg2"><button className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>Chart and table</button><button className={view === "table" ? "on" : ""} onClick={() => setView("table")}>Table only</button></span>}
        {cur.key !== "ov" && <span className="seg2" title="How figures in the table are shown"><button className={!full ? "on" : ""} onClick={() => setFull(false)}>£4.97m</button><button className={full ? "on" : ""} onClick={() => setFull(true)}>£4,970,000</button></span>}
        </span>
      </div>
      {cur.key === "ov" ? <Overview data={data} ys={ys} /> : <>
      {cur.chart && view === "chart" && cur.chart(ys)}
      <div className="fin2-table">
        <table className="y2">
          <thead><tr><th />{ys.map((y) => <th key={y.f.period_end} title={date(y.f.period_end)}>{y.label}
            {y.f.source?.startsWith("pdf:") && <span className="pdfmark" title={y.f.source === "pdf:ocr" ? "Read from the PDF by OCR: check against the filing" : "Read from the PDF: check against the filing"}>ᴾ</span>}</th>)}</tr></thead>
          <tbody>
            {cur.rows.map((r) => (
              <tr key={r.label} className={r.key ? "key" : ""}>
                <td>{r.label}{r.hint ? <Hint text={r.hint} /> : null}</td>
                {ys.map((y, i) => {
                  const v = r.get(y.f, i), prev = i > 0 ? r.get(ys[i - 1].f, i - 1) : null;
                  const pct = r.change && v !== null && prev !== null && prev !== 0 ? Math.round((100 * (v - prev)) / Math.abs(prev)) : null;
                  const e = r.est?.(i);
                  return (
                    <td key={y.f.period_end} className={v !== null && v < 0 && r.fmt !== "pct" ? "neg" : ""}>
                      {v === null ? <span className="faint">—</span> : <span className={e ? "fig-est" : ""} title={e ? "Estimate: staff × the company's own revenue per head" : undefined}>{fmt(v, r.fmt, full && !e)}</span>}
                      {pct !== null && pct !== 0 && <span className={`chg2 ${pct < 0 ? "dn" : ""}`}>{pct > 0 ? "+" : ""}{pct}%</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="faint small" style={{ margin: "6px 0 0" }}>Only figures the accounts give. <span className="fig-est">Amber underlined</span>: estimate. ᴾ: read from a PDF.</p>
      </>}
    </div>
  );
}

function fmt(v: number, f?: "money" | "int" | "pct", full = false) {
  return f === "int" ? int(v) : f === "pct" ? `${v.toFixed(1)}%` : money(v, { precise: full });
}

/** Round axis steps (1, 2, 2.5 or 5 × a power of ten). */
function niceTicks(lo: number, hi: number, n = 4) {
  const span = hi - lo || Math.abs(hi) || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) ?? raw;
  const t0 = Math.floor(lo / step) * step, t1 = Math.ceil(hi / step) * step, out: number[] = [];
  for (let t = t0; t <= t1 + step / 1e6; t += step) out.push(Math.abs(t) < step / 1e6 ? 0 : t);
  return out;
}

/** Bars with values on them; a second measure, if any, as its own small line chart underneath (no shared axis). */
function ComboChart({ years, bars, line }: {
  years: string[];
  bars: { label: string; values: Val[]; colour: string; est?: boolean[]; fmt?: "money" | "int" }[];
  line?: { label: string; values: Val[]; fmt: "money" | "pct" };
}) {
  const live = bars.filter((b) => b.values.some((v) => v !== null));
  if (!live.length) return null;
  const W = 1000, H = 230, L = 200, R = 0, T = 24, B = 28;
  const all = live.flatMap((b) => b.values).filter((v): v is number => v !== null);
  const ticks = niceTicks(Math.min(0, ...all), Math.max(0, ...all));
  const min = ticks[0], max = ticks[ticks.length - 1], span = max - min || 1;
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / span);
  const n = years.length, slot = (W - L - R) / n, bw = Math.min(64, (slot * 0.62) / live.length);
  const bf = (b: (typeof bars)[number], v: number) => (b.fmt === "int" ? int(v) : money(v));
  const lv = line ? line.values.filter((v): v is number => v !== null) : [];
  return (
    <div className="combo">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={live.map((b) => b.label).join(" and ")}>
        <defs><pattern id="estp" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="#fcf1e1" /><line x1="0" y1="0" x2="0" y2="6" stroke="#e2a85a" strokeWidth="2.5" /></pattern></defs>
        {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className={t === 0 ? "zero" : "gl"} />
          <text x={L - 8} y={y(t) + 4} className="ax" textAnchor="end">{live[0].fmt === "int" ? int(t) : money(t, { short: true })}</text></g>)}
        {years.map((lab, i) => {
          const x0 = L + slot * i + (slot - bw * live.length) / 2;
          // Value labels: when two sit side by side at about the same height and
          // are wider than their bars, lean them apart (first left, second right)
          // so they stay on their own bars without touching.
          const anchor: ("middle" | "end" | "start")[] = live.map(() => "middle");
          if (live.length === 2) {
            const [va, vc] = [live[0].values[i], live[1].values[i]];
            if (va !== null && vc !== null && va >= 0 && vc >= 0 && Math.abs(y(va) - y(vc)) < 15
                && (bf(live[0], va).length + bf(live[1], vc).length) * 3.6 > bw) { anchor[0] = "end"; anchor[1] = "start"; }
          }
          const lx = (j: number) => x0 + j * bw + (anchor[j] === "end" ? bw - 2 : anchor[j] === "start" ? 2 : bw / 2);
          return (
            <g key={lab + i}>
              {live.map((b, j) => {
                const v = b.values[i];
                if (v === null) return null;
                const top = Math.min(y(v), y(0)), h = Math.max(2, Math.abs(y(v) - y(0)));
                const est = b.est?.[i];
                return (
                  <g key={j}>
                    <rect x={x0 + j * bw + 2} y={top} width={bw - 4} height={h} rx={5} fill={est ? "url(#estp)" : v < 0 ? "#c8352b" : b.colour}>
                      <title>{`${b.label} ${lab}: ${b.fmt === "int" ? int(v) : money(v, { precise: true })}${est ? " (estimate)" : ""}`}</title></rect>
                    <text x={lx(j)} y={v >= 0 ? top - 6 : top + h + 14} className={`bv ${est ? "est" : ""}`} textAnchor={anchor[j]}>{bf(b, v)}</text>
                  </g>
                );
              })}
              <text x={L + slot * i + slot / 2} y={H - 8} className="ax" textAnchor="middle">{lab}</text>
            </g>
          );
        })}
      </svg>
      <div className="combo-key">
        {live.map((b) => <span key={b.label}><i style={{ background: b.colour }} />{b.label}</span>)}
        {live.some((b) => b.est?.some(Boolean)) && <span><i className="hatch" />Estimate</span>}
      </div>
      {line && lv.length >= 2 && <MiniLine years={years} values={line.values} label={line.label} fmt={line.fmt} />}
    </div>
  );
}

/** A small line chart for a second measure (a margin, revenue per head), with its own scale. */
type LineSeries = { label: string; values: Val[]; colour: string; strong?: boolean; dashed?: boolean; off?: boolean };

/** Several measures as lines on one money axis. The legend switches lines on
    and off (remembered); hovering a year shows every visible line's exact figure. */
function LinesChart({ years, series, memo }: { years: string[]; series: LineSeries[]; memo: string }) {
  const avail = series.filter((sr) => sr.values.some((v) => v !== null));
  const [shown, setShownState] = useState<string[]>(() => {
    try { const v = JSON.parse(localStorage.getItem(`ao.lines.${memo}`) ?? "null"); if (Array.isArray(v)) return v; } catch { /* ignore */ }
    return series.filter((sr) => !sr.off).map((sr) => sr.label);
  });
  const toggle = (l: string) => {
    const next = shown.includes(l) ? shown.filter((x) => x !== l) : [...shown, l];
    setShownState(next); try { localStorage.setItem(`ao.lines.${memo}`, JSON.stringify(next)); } catch { /* ignore */ }
  };
  const [hi, setHi] = useState<number | null>(null);
  if (!avail.length) return null;
  const live = avail.filter((sr) => shown.includes(sr.label));
  const W = 1000, H = 250, L = 200, R = 0, T = 16, B = 28;
  const all = live.flatMap((sr) => sr.values).filter((v): v is number => v !== null);
  const ticks = niceTicks(Math.min(0, ...all), Math.max(0, ...all, 1));
  const lo = ticks[0], top = ticks[ticks.length - 1], span = top - lo || 1;
  const slot = (W - L - R) / years.length;
  const x = (i: number) => L + slot * i + slot / 2;
  const y = (v: number) => T + (H - T - B) * (1 - (v - lo) / span);
  const lastOf = (vals: Val[]) => [...vals].reverse().find((v) => v !== null) ?? null;
  const exact = (v: number) => money(v, { precise: true });
  return (
    <div className="combo lines">
      <div className="lc-wrap" onMouseLeave={() => setHi(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={live.map((sr) => sr.label).join(", ")}>
          {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className={t === 0 ? "zero" : "gl"} />
            <text x={L - 8} y={y(t) + 4} className="ax" textAnchor="end">{money(t, { short: true })}</text></g>)}
          {hi !== null && <line x1={x(hi)} x2={x(hi)} y1={T} y2={H - B} className="lc-guide" />}
          {live.map((sr) => {
            // Break the line where a year is missing, rather than joining across it.
            const segs: [number, number][][] = [[]];
            sr.values.forEach((v, i) => { if (v === null) { if (segs[segs.length - 1].length) segs.push([]); } else segs[segs.length - 1].push([x(i), y(v)]); });
            return <g key={sr.label}>
              {segs.filter((sg) => sg.length > 1).map((sg, k) => <polyline key={k} points={sg.map((p) => p.join(",")).join(" ")} fill="none"
                stroke={sr.colour} strokeWidth={sr.strong ? 3 : 2} strokeDasharray={sr.dashed ? "6 5" : undefined} strokeLinejoin="round" />)}
              {sr.values.map((v, i) => v === null ? null : <circle key={i} cx={x(i)} cy={y(v)} r={hi === i ? 6 : sr.strong ? 4.5 : 3.5}
                fill={hi === i ? sr.colour : "#fff"} stroke={sr.colour} strokeWidth={2} />)}
            </g>;
          })}
          {years.map((lab, i) => <text key={lab + i} x={x(i)} y={H - 8} className="ax" textAnchor="middle">{lab}</text>)}
          {years.map((_, i) => <rect key={`h${i}`} x={L + slot * i} y={0} width={slot} height={H} fill="transparent"
                                     onMouseEnter={() => setHi(i)} onClick={() => setHi(i)} />)}
        </svg>
        {hi !== null && live.some((sr) => sr.values[hi] !== null) && (
          <div className={`lc-tip ${x(hi) > W * 0.7 ? "left" : ""}`} style={{ left: `${(100 * x(hi)) / W}%` }}>
            <div className="t">{years[hi]}</div>
            {live.filter((sr) => sr.values[hi] !== null).sort((a, b) => (b.values[hi] ?? 0) - (a.values[hi] ?? 0)).map((sr) => (
              <div key={sr.label} className="r"><i style={{ background: sr.colour }} />{sr.label}<b>{exact(sr.values[hi]!)}</b></div>))}
          </div>
        )}
      </div>
      <div className="combo-key lc-key">
        {avail.map((sr) => {
          const on = shown.includes(sr.label);
          return <button key={sr.label} className={on ? "on" : ""} onClick={() => toggle(sr.label)} title={on ? "Hide this line" : "Show this line"}>
            <i style={{ background: on ? sr.colour : "transparent", borderColor: sr.colour }} />{sr.label}
            {on && lastOf(sr.values) !== null ? <b>{money(lastOf(sr.values))}</b> : null}</button>;
        })}
      </div>
    </div>
  );
}

function MiniLine({ years, values, label, fmt }: { years: string[]; values: Val[]; label: string; fmt: "money" | "pct" }) {
  const W = 1000, H = 110, L = 200, R = 0, T = 22, B = 8;
  const vs = values.filter((v): v is number => v !== null);
  const ticks = niceTicks(Math.min(0, ...vs), Math.max(...vs), 2);
  const lo = ticks[0], hi = ticks[ticks.length - 1], span = hi - lo || 1;
  const slot = (W - L - R) / years.length;
  const y = (v: number) => T + (H - T - B) * (1 - (v - lo) / span);
  const f = (v: number) => (fmt === "pct" ? `${v.toFixed(1)}%` : money(v));
  const pts = values.map((v, i) => (v === null ? null : [L + slot * i + slot / 2, y(v), v] as const)).filter(Boolean) as (readonly [number, number, number])[];
  return (
    <div className="miniline">
      <div className="label">{label}</div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className={t === 0 ? "zero" : "gl"} />
          <text x={L - 8} y={y(t) + 4} className="ax" textAnchor="end">{fmt === "pct" ? f(t) : money(t, { short: true })}</text></g>)}
        <polyline points={pts.map((p) => `${p[0]},${p[1]}`).join(" ")} className="ml" />
        {pts.map((p, i) => <g key={i}><circle cx={p[0]} cy={p[1]} r={4} className="mc" /><text x={p[0]} y={p[1] - 9} textAnchor="middle" className="mv">{f(p[2])}</text></g>)}
      </svg>
    </div>
  );
}


/** The overview: assets chart, then one card per measure with its change, a small trend line and a note. */
function Overview({ data, ys }: { data: CompanyDetail; ys: Year[] }) {
  const sm = data.fin_summary!;
  const series = sm.series ?? [];
  const spark = (key: string) => series.map((r: any) => (r[key] ?? (key === "turnover" ? r.turnover_est : null)) as number | null);
  const tiles: { key: string; label: string; value: string; est?: boolean; change?: { text: string; good: boolean | null; up: boolean } | null; note?: string; spark?: (number | null)[] }[] = [];
  const fmtv = (k: string, v: number) => (k === "employees" ? int(v) : k === "debt_ratio" ? `${Math.round(v)}%` : money(v));
  for (const r of sm.rows) {
    tiles.push({
      key: r.key, label: r.label, value: fmtv(r.key, r.value), est: r.estimated,
      change: r.change != null && r.change !== 0 ? { up: r.change > 0, good: r.good,
        text: `${r.change > 0 ? "+" : "−"}${r.key === "employees" ? int(Math.abs(r.change)) : r.key === "debt_ratio" ? `${Math.abs(Math.round(r.change))} pts` : money(Math.abs(r.change))}${r.change_pct != null ? ` (${r.change_pct > 0 ? "+" : ""}${r.change_pct}%)` : ""}` } : null,
      note: r.trend, spark: spark(r.key),
    });
  }
  // Revenue per head and margin from the latest year with filed turnover (estimates would be circular).
  const filed = [...ys].reverse().find((y) => n(y.f.turnover) && n(y.f.employees));
  if (filed) {
    const rph = n(filed.f.turnover)! / n(filed.f.employees)!;
    const pts = ys.map((y) => (n(y.f.turnover) && n(y.f.employees) ? n(y.f.turnover)! / n(y.f.employees)! : null));
    tiles.splice(3, 0, { key: "rph", label: "Revenue per head", value: money(rph), note: `From the ${filed.label} accounts${pts.filter((x) => x !== null).length < 2 ? " (the only year with turnover filed)" : ""}`, spark: pts });
    const op = ebitda(filed.f) ?? n(filed.f.operating_profit);
    if (op !== null) tiles.splice(4, 0, { key: "margin", label: ebitda(filed.f) !== null ? "EBITDA margin" : "Operating margin",
      value: `${((100 * op) / n(filed.f.turnover)!).toFixed(1)}%`, note: `From the ${filed.label} accounts` });
  }
  return (
    <>
      {series.length ? <BalanceChart series={series} /> : null}
      <div className="ovt-head faint small">Year to {date(sm.period_end)}{sm.previous_end ? `, against the year to ${date(sm.previous_end)}` : ""}</div>
      <div className="ovt">
        {tiles.map((t) => (
          <div key={t.key} className="ovt-c">
            <div className="ovt-l">{t.label}</div>
            <div className="ovt-v"><span className={t.est ? "fig-est" : ""} title={t.est ? "Estimate: staff × the company's own revenue per head" : undefined}>{t.value}</span>
              {t.change && <span className={`ovt-ch ${t.change.good === true ? "good" : t.change.good === false ? "bad" : ""}`}>{t.change.up ? "▲" : "▼"} {t.change.text}</span>}</div>
            {t.spark && t.spark.filter((x) => x !== null).length > 1 && <Spark vals={t.spark} />}
            {t.note && <div className="ovt-n">{t.note}</div>}
          </div>
        ))}
      </div>
    </>
  );
}

function Spark({ vals }: { vals: (number | null)[] }) {
  const W = 200, H = 34, P = 3;
  const v = vals.map((x, i) => [i, x] as const).filter(([, x]) => x !== null) as [number, number][];
  const lo = Math.min(...v.map(([, x]) => x)), hi = Math.max(...v.map(([, x]) => x)), span = hi - lo || 1;
  const X = (i: number) => P + (i * (W - 2 * P)) / Math.max(1, vals.length - 1);
  const Y = (x: number) => H - P - ((x - lo) * (H - 2 * P)) / span;
  const pts = v.map(([i, x]) => `${X(i)},${Y(x)}`).join(" ");
  const last = v[v.length - 1];
  return (
    <svg className="ovt-sp" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <polyline points={`${X(v[0][0])},${H} ${pts} ${X(last[0])},${H}`} className="a" />
      <polyline points={pts} className="l" />
      <circle cx={X(last[0])} cy={Y(last[1])} r="2.6" className="d" />
    </svg>
  );
}
