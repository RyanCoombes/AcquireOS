/* Financials: tabs, each with a chart and the full table of every year. */
import type React from "react";
import { useState } from "react";
import type { CompanyDetail } from "../api";
import { date, int, money } from "../format";
import { Hint } from "./bits";

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
    return { f, label: new Date(f.period_end).toLocaleDateString("en-GB", { month: "short", year: "numeric" }),
             turnover: n(f.turnover) ?? e, turnoverEst: f.turnover == null && e != null };
  });
  const [tab, setTab] = useState("pl");
  const [view, setView] = useState<"chart" | "table">("chart");
  if (!ys.length) return <div className="faint">No accounts on file.</div>;

  const turnoverRow: Row = { label: "Turnover", get: (_f, i) => ys[i].turnover, change: true, est: (i) => ys[i].turnoverEst, key: false };
  const margin = (y: Year) => { const e = ebitda(y.f) ?? n(y.f.operating_profit); return e !== null && y.turnover ? (100 * e) / y.turnover : null; };
  const tabs: Tab[] = [
    { key: "pl", label: "Revenue & profit", rows: [
        turnoverRow,
        { label: "Gross profit", get: (f) => n(f.gross_profit) },
        { label: "Operating profit", get: (f) => n(f.operating_profit), change: true },
        { label: "Depreciation and amortisation", get: (f) => da(f) },
        { label: "EBITDA", get: (f) => ebitda(f), key: true, change: true, hint: "Operating profit + depreciation and amortisation, both filed" },
        { label: "EBITDA margin", get: (_f, i) => (ebitda(ys[i].f) !== null && ys[i].turnover ? (100 * ebitda(ys[i].f)!) / ys[i].turnover! : null), fmt: "pct" },
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
        { label: "Net assets", get: (f) => n(f.net_assets), key: true, change: true },
      ],
      chart: (ys) => <ComboChart years={ys.map((y) => y.label)}
        bars={[{ label: "Net assets", values: ys.map((y) => n(y.f.net_assets)), colour: "#0e7c6b" }]}
        line={{ label: "Net current assets", values: ys.map((y) => n(y.f.net_current_assets)), fmt: "money" }} /> },
    { key: "cash", label: "Cash & debt", rows: [
        { label: "Cash", get: (f) => n(f.cash), key: true, change: true },
        { label: "Bank loans and overdrafts", get: (f) => bank(f), key: true, hint: "Repaid from the price on a cash-free, debt-free deal" },
        { label: "Net cash (cash less bank debt)", get: (f) => (n(f.cash) !== null ? n(f.cash)! - (bank(f) ?? 0) : null) },
        { label: "Owed within a year", get: (f) => withinYr(f) },
        { label: "Owed after a year", get: (f) => afterYr(f) },
        { label: "Interest paid", get: (f) => n(f.interest_payable) },
      ],
      chart: (ys) => <ComboChart years={ys.map((y) => y.label)}
        bars={[{ label: "Cash", values: ys.map((y) => n(y.f.cash)), colour: "#0e7c6b" },
               { label: "Bank debt", values: ys.map((y) => bank(y.f)), colour: "#c8352b" }]} /> },
    { key: "staff", label: "Staff & pay", rows: [
        { label: "Average staff", get: (f) => n(f.employees), fmt: "int", key: true, change: true },
        { label: "Revenue per head", get: (_f, i) => (ys[i].turnover && n(ys[i].f.employees) ? ys[i].turnover! / n(ys[i].f.employees)! : null), est: (i) => ys[i].turnoverEst },
        { label: "Staff costs", get: (f) => n(f.staff_costs) },
        { label: "Cost per head", get: (f) => (n(f.staff_costs) && n(f.employees) ? n(f.staff_costs)! / n(f.employees)! : null) },
        { label: "Directors' pay", get: (f) => n(f.director_pay) },
      ],
      chart: (ys) => <ComboChart years={ys.map((y) => y.label)}
        bars={[{ label: "Staff", values: ys.map((y) => n(y.f.employees)), colour: "#2f62d8", fmt: "int" }]}
        line={{ label: "Revenue per head", values: ys.map((y) => (y.turnover && n(y.f.employees) ? y.turnover / n(y.f.employees)! : null)), fmt: "money" }} /> },
  ];
  const allRows: Row[] = [...tabs[0].rows, ...tabs[1].rows, ...tabs[3].rows, { label: "Bank loans and overdrafts", get: (f: F) => bank(f) }];
  const all: Tab = { key: "all", label: "All figures", rows: allRows.filter((r, i, arr) => arr.findIndex((x) => x.label === r.label) === i) };
  const shown = [...tabs, all].map((t) => ({ ...t, rows: t.rows.filter((r) => ys.some((y, i) => r.get(y.f, i) !== null)) }))
    .filter((t) => t.rows.length > 0);
  const cur = shown.find((t) => t.key === tab) ?? shown[0];

  return (
    <div className="fin2">
      <div className="fin2-top">
        <div className="tabs2" role="tablist">
          {shown.map((t) => <button key={t.key} role="tab" aria-selected={t.key === cur.key} className={t.key === cur.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label}</button>)}
        </div>
        {cur.chart && <span className="seg2"><button className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>Chart and table</button><button className={view === "table" ? "on" : ""} onClick={() => setView("table")}>Table only</button></span>}
      </div>
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
                      {v === null ? <span className="faint">—</span> : <span className={e ? "fig-est" : ""} title={e ? "Estimate: staff × the company's own revenue per head" : undefined}>{fmt(v, r.fmt)}</span>}
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
    </div>
  );
}

function fmt(v: number, f?: "money" | "int" | "pct") {
  return f === "int" ? int(v) : f === "pct" ? `${v.toFixed(1)}%` : money(v);
}

/** Bars (one or two series) and an optional line on its own scale; values printed on the bars. */
function ComboChart({ years, bars, line }: {
  years: string[];
  bars: { label: string; values: Val[]; colour: string; est?: boolean[]; fmt?: "money" | "int" }[];
  line?: { label: string; values: Val[]; fmt: "money" | "pct" };
}) {
  const W = 1000, H = 240, L = 54, R = line ? 54 : 14, T = 26, B = 28;
  const all = bars.flatMap((b) => b.values).filter((v): v is number => v !== null);
  if (!all.length && !(line && line.values.some((v) => v !== null))) return null;
  const max = Math.max(0, ...all), min = Math.min(0, ...all);
  const span = max - min || 1;
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / span);
  const n = years.length, slot = (W - L - R) / n, bw = Math.min(70, (slot * 0.7) / bars.length);
  const lv = line ? line.values.filter((v): v is number => v !== null) : [];
  const lmax = lv.length ? Math.max(...lv) : 1, lmin = lv.length ? Math.min(0, ...lv) : 0, lspan = lmax - lmin || 1;
  const ly = (v: number) => T + (H - T - B) * (1 - (v - lmin) / lspan) ;
  const ticks = [min, min + span / 2, max].filter((v, i, a) => a.indexOf(v) === i);
  const bf = (b: (typeof bars)[number], v: number) => (b.fmt === "int" ? int(v) : money(v));
  return (
    <div className="combo">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={bars.map((b) => b.label).join(" and ")}>
        <defs><pattern id="estp" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="#fcf1e1" /><line x1="0" y1="0" x2="0" y2="6" stroke="#e2a85a" strokeWidth="2.5" /></pattern></defs>
        {ticks.map((t) => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="gl" /><text x={L - 8} y={y(t) + 4} className="ax" textAnchor="end">{bars[0]?.fmt === "int" ? int(t) : money(t)}</text></g>)}
        {min < 0 && <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} className="zero" />}
        {years.map((lab, i) => {
          const x0 = L + slot * i + (slot - bw * bars.length) / 2;
          return (
            <g key={lab + i}>
              {bars.map((b, j) => {
                const v = b.values[i];
                if (v === null) return null;
                const top = Math.min(y(v), y(0)), h = Math.max(2, Math.abs(y(v) - y(0)));
                const est = b.est?.[i];
                return (
                  <g key={j}>
                    <rect x={x0 + j * bw} y={top} width={bw - 4} height={h} rx={5} fill={est ? "url(#estp)" : v < 0 ? "#c8352b" : b.colour}>
                      <title>{`${b.label} ${lab}: ${bf(b, v)}${est ? " (estimate)" : ""}`}</title></rect>
                    {bars.length === 1 || n <= 6 ? <text x={x0 + j * bw + (bw - 4) / 2} y={(v >= 0 ? top : top + h) + (v >= 0 ? -6 : 14)} className="bv" textAnchor="middle">{bf(b, v)}</text> : null}
                  </g>
                );
              })}
              <text x={L + slot * i + slot / 2} y={H - 8} className="ax" textAnchor="middle">{lab}</text>
            </g>
          );
        })}
        {line && lv.length > 1 && (() => {
          const pts = line.values.map((v, i) => (v === null ? null : [L + slot * i + slot / 2, ly(v)] as const)).filter(Boolean) as (readonly [number, number])[];
          const last = line.values.map((v, i) => [v, i] as const).filter(([v]) => v !== null).pop();
          return (
            <g className="ln">
              <polyline points={pts.map((p) => p.join(",")).join(" ")} />
              {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={4} />)}
              {last && <text x={L + slot * last[1] + slot / 2 + 8} y={ly(last[0]!) - 8} className="lv">{line.fmt === "pct" ? `${last[0]!.toFixed(1)}%` : money(last[0]!)}</text>}
            </g>
          );
        })()}
      </svg>
      <div className="combo-key">
        {bars.map((b) => <span key={b.label}><i style={{ background: b.colour }} />{b.label}</span>)}
        {bars.some((b) => b.est?.some(Boolean)) && <span><i className="hatch" />Estimate</span>}
        {line && lv.length > 1 && <span><i className="lk" />{line.label}{line.fmt === "pct" ? " (right scale)" : ""}</span>}
      </div>
    </div>
  );
}
