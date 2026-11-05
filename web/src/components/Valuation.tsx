/* Indicative value and a simple funding check.
   Assumption edits are saved to this company only (user-owned data). */
import { useMemo, useRef, useState } from "react";
import { api, type Assumptions, type CompanyDetail, type Funding } from "../api";
import { money, range, toNum } from "../format";
import MoneyInput from "./MoneyInput";

const FIELDS: { k: keyof Assumptions; label: string; unit: string; step: number }[] = [
  { k: "margin_low", label: "Margin, low", unit: "%", step: 1 },
  { k: "margin_high", label: "Margin, high", unit: "%", step: 1 },
  { k: "multiple_low", label: "Multiple, low", unit: "×", step: 0.25 },
  { k: "multiple_high", label: "Multiple, high", unit: "×", step: 0.25 },
];

export default function Valuation({ data, num, onSaved }: { data: CompanyDetail; num: string; onSaved: () => void }) {
  const v = data.valuation;
  const [a, setA] = useState<Assumptions>(v.assumptions);
  const [dirty, setDirty] = useState(false);
  const est = data.estimate;
  const latest = [...data.financials].reverse().find((f) => !f.period_inferred);
  const op = toNum(latest?.operating_profit ?? null);

  // Same method as the server (backend/acquireos/valuation.py), recalculated live.
  const live = useMemo(() => {
    if (op !== null && op > 0) return { eLo: op, eHi: op, basis: "filed" as const };
    if (op !== null && op <= 0) return null;  // loss-making as filed: no earnings-based value
    const rLo = toNum(est?.revenue_low ?? null), rHi = toNum(est?.revenue_high ?? null) ?? rLo;
    if (rLo === null || rHi === null) return null;
    return { eLo: (rLo * a.margin_low) / 100, eHi: (rHi * a.margin_high) / 100, basis: "estimated" as const };
  }, [a, est, op]);
  const vLo = live ? live.eLo * a.multiple_low : null;
  const vHi = live ? live.eHi * a.multiple_high : null;
  const isOverride = Object.keys(v.override ?? {}).length > 0;

  const save = async (vals: Partial<Assumptions> | null) => {
    await api.setState(num, { valuation: vals ?? {} });
    setDirty(false);
    onSaved();
  };

  return (
    <section>
      <div className="sechead">
        <h2>Indicative value</h2>
        <span className="faint small">A screening estimate, not a valuation.</span>
      </div>
      {!live ? (
        <div className="faint">{op !== null && op <= 0
          ? <>Loss-making as filed: operating profit of {money(op)} in the latest accounts. No earnings-based value; it would be priced on its assets or a turnaround view.</>
          : "Not enough filed figures to estimate profit or value."}</div>
      ) : (
        <>
          <div className="factline" style={{ borderTop: 0 }}>
            <div><b>{range(live.eLo, live.eHi)}</b><span>Profit (EBITDA proxy) · {live.basis === "filed" ? "filed" : "estimate"}</span></div>
            <div><b className="hl">{range(vLo, vHi)}</b><span>Enterprise value</span></div>
            {v.cash ? <div><b>{money(v.cash)}</b><span>Cash on balance sheet, not included</span></div> : null}
          </div>
          <ol className="steps">
            {live.basis === "filed" ? (
              <li>Profit: filed operating profit of {money(op)}. Depreciation is not added back, so true EBITDA is likely higher.</li>
            ) : (
              <li>Profit: {est?.basis === "filed" ? "filed turnover" : "estimated revenue"} of {range(est!.revenue_low, est!.revenue_high)} × {a.margin_low}–{a.margin_high}% margin.</li>
            )}
            <li>Value: profit × {a.multiple_low}–{a.multiple_high} times.</li>
            <li>Debt is not netted off: small-company accounts rarely show it clearly. Check the charges register.</li>
          </ol>
          <div className="assume">
            {FIELDS.map((f) => (
              <label key={f.k} className="field">
                <span className="label">{f.label}</span>
                <span className="unit">
                  <input type="number" step={f.step} min={0} value={a[f.k]} disabled={live.basis === "filed" && f.k.startsWith("margin")}
                         onChange={(e) => { setA({ ...a, [f.k]: Number(e.target.value) }); setDirty(true); }} />
                  <i>{f.unit}</i>
                </span>
              </label>
            ))}
            <div className="assume-actions">
              {dirty && <button className="btn primary" onClick={() => save(a)}>Save for this company</button>}
              {(isOverride || dirty) && (
                <button className="btn quiet" onClick={() => { setA(v.defaults); save(null); }}>Use buy box defaults</button>
              )}
              {!dirty && !isOverride && <span className="faint small">Defaults from your buy box. Change them here for this company only.</span>}
              {!dirty && isOverride && <span className="small" style={{ color: "var(--amber)" }}>Using your own assumptions for this company.</span>}
            </div>
          </div>
          <DealCheck eLo={live.eLo} eHi={live.eHi} vLo={vLo ?? 0} vHi={vHi ?? 0} saved={data.state.funding ?? {}}
                     onSave={(f) => api.setState(num, { funding: f })} />
        </>
      )}
    </section>
  );
}

function annuity(principal: number, ratePct: number, years: number) {
  if (principal <= 0 || years <= 0) return 0;
  const r = ratePct / 100;
  if (r === 0) return principal / years;
  return (principal * r) / (1 - Math.pow(1 + r, -years));
}

function DealCheck({ eLo, eHi, vLo, vHi, saved, onSave }: {
  eLo: number; eHi: number; vLo: number; vHi: number; saved: Partial<Funding>; onSave: (f: Funding) => Promise<unknown>;
}) {
  const mid = Math.round(((vLo + vHi) / 2) / 10000) * 10000;
  const defaults: Funding = { price: mid, your_cash: 0, investor_cash: 0, investor_stake: 30, vendor_pct: 30, vendor_years: 3,
                              vendor_rate: 0, bank_rate: 9, bank_years: 5 };
  const [f, setF] = useState<Funding>({ ...defaults, ...saved });
  const [note, setNote] = useState<string>(Object.keys(saved).length ? "Saved for this company" : "");
  const timer = useRef<number | null>(null);
  const set = (patch: Partial<Funding>) => {
    const next = { ...f, ...patch };
    setF(next); setNote("Saving…");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      try { await onSave(next); setNote("Saved for this company"); } catch (e: any) { setNote(`Not saved: ${e.message}`); }
    }, 600);
  };
  const vendor = (f.price * f.vendor_pct) / 100;
  const bank = Math.max(0, f.price - f.your_cash - f.investor_cash - vendor);
  const short = f.your_cash + f.investor_cash + vendor > f.price;
  const bankService = annuity(bank, f.bank_rate, f.bank_years);
  const vendorService = annuity(vendor, f.vendor_rate, f.vendor_years);
  const service = bankService + vendorService;
  const cover = (profit: number) => (service > 0 ? profit / service : null);
  const eMid = (eLo + eHi) / 2;
  const cMid = cover(eMid);
  const verdict = (c: number | null) => c === null ? "" : c >= 2 ? "Comfortable" : c >= 1.5 ? "Workable" : c >= 1.2 ? "Tight" : "Does not cover";
  const stake = f.investor_cash > 0 ? Math.max(0, 100 - f.investor_stake) : 100;
  const leftMid = eMid - service;
  const num = (k: keyof Funding, step = 1, w = 70) => (
    <input type="number" step={step} min={0} style={{ width: w }} value={f[k]} onChange={(e) => set({ [k]: Number(e.target.value) } as Partial<Funding>)} />
  );
  const cls = (c: number | null) => `num ${c !== null && c < 1.2 ? "neg" : c !== null && c >= 1.5 ? "pos" : ""}`;
  return (
    <details className="dealcheck" open={Object.keys(saved).length > 0}>
      <summary>Funding check: can the profit pay for the deal? <span className="faint small">{note}</span></summary>
      <p className="muted small" style={{ margin: "6px 0 10px" }}>
        Where the money comes from: your own cash (none if your equity is sweat), an investor's cash in return for a stake
        (a co-investor such as a development bank typically takes 20–40%), a vendor loan (part of the price paid to the seller
        over time), and bank or lender debt for the rest. Repayments are then set against the profit range above.
      </p>
      <div className="dc-grid">
        <label className="field"><span className="label">Price <span className="faint">(starts at the midpoint, {money(mid)})</span></span>
          <MoneyInput value={f.price} width={140} onChange={(v) => set({ price: v ?? 0 })} /></label>
        <label className="field"><span className="label">Your cash in</span>
          <MoneyInput value={f.your_cash} width={120} onChange={(v) => set({ your_cash: v ?? 0 })} /></label>
        <label className="field"><span className="label">Investor cash in</span>
          <MoneyInput value={f.investor_cash} width={120} onChange={(v) => set({ investor_cash: v ?? 0 })} /></label>
        <label className="field"><span className="label">Investor's stake, %</span>{num("investor_stake")}</label>
        <label className="field"><span className="label">Vendor loan, % of price</span>{num("vendor_pct")}</label>
        <label className="field"><span className="label">Vendor loan over, years</span>{num("vendor_years")}</label>
        <label className="field"><span className="label">Vendor loan rate, %</span>{num("vendor_rate", 0.25)}</label>
        <label className="field"><span className="label">Bank rate, %</span>{num("bank_rate", 0.25)}</label>
        <label className="field"><span className="label">Bank term, years</span>{num("bank_years")}</label>
      </div>
      {short && <div className="callout red">Cash, investor money and the vendor loan add up to more than the price; lower one of them.</div>}
      <table className="dc-table">
        <tbody>
          <tr><td>Your cash</td><td className="num">{money(f.your_cash)}{f.your_cash === 0 ? <span className="faint small"> · sweat equity</span> : null}</td></tr>
          {f.investor_cash > 0 && <tr><td>Investor cash, for a {f.investor_stake}% stake</td><td className="num">{money(f.investor_cash)}</td></tr>}
          <tr><td>Vendor loan ({f.vendor_pct}%)</td><td className="num">{money(vendor)}</td></tr>
          <tr><td>Bank or lender debt ({f.price ? Math.round((100 * bank) / f.price) : 0}%)</td><td className="num">{money(bank)}</td></tr>
          <tr><td>Yearly repayments: bank {money(bankService)} + vendor {money(vendorService)}</td><td className="num"><b>{money(service)}</b></td></tr>
          <tr><td>Profit available <span className="faint small">(the range above; midpoint {money(eMid)})</span></td><td className="num">{range(eLo, eHi)}</td></tr>
          <tr className="total">
            <td>Debt cover <span className="faint small">profit ÷ repayments. Lenders usually want 1.5× or more.</span></td>
            <td className={cls(cMid)}>
              <b>{cMid === null ? "—" : `${cMid.toFixed(1)}×`}</b> {verdict(cMid)}
              {eLo !== eHi && cover(eLo) !== null && <div className="faint small">{cover(eLo)!.toFixed(1)}× at the low end, {cover(eHi)!.toFixed(1)}× at the high end</div>}
            </td>
          </tr>
          <tr><td>Profit left after repayments (midpoint)</td><td className={`num ${leftMid < 0 ? "neg" : ""}`}>{money(leftMid)}</td></tr>
          <tr><td>Your stake{f.investor_cash > 0 ? ` (investor holds ${f.investor_stake}%)` : ""}</td><td className="num">{stake}%
            {f.investor_cash > 0 && <div className="faint small">your share of what is left: {money((leftMid * stake) / 100)} a year</div>}</td></tr>
        </tbody>
      </table>
      <p className="faint small">Ignores tax, capital expenditure, working capital, fees and your own salary, so real cover will be lower.
        An investor's loan element (many co-investors lend as well as take equity) can be entered as part of the bank debt.</p>
    </details>
  );
}
