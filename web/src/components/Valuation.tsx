/* Indicative value and a simple funding check.
   Assumption edits are saved to this company only (user-owned data). */
import { useMemo, useState } from "react";
import { api, type Assumptions, type CompanyDetail } from "../api";
import { money, range, toNum } from "../format";

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
        <div className="faint">Not enough filed figures to estimate profit or value.</div>
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
          <DealCheck ebitda={(live.eLo + live.eHi) / 2} price={((vLo ?? 0) + (vHi ?? 0)) / 2} />
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

function DealCheck({ ebitda, price: suggested }: { ebitda: number; price: number }) {
  const [p, setP] = useState({ price: Math.round(suggested / 10000) * 10000, equity: 20, vendor: 30, rate: 9, term: 5, vendorTerm: 3 });
  const bankPct = Math.max(0, 100 - p.equity - p.vendor);
  const bank = (p.price * bankPct) / 100;
  const vendor = (p.price * p.vendor) / 100;
  const bankService = annuity(bank, p.rate, p.term);
  const vendorService = p.vendorTerm > 0 ? vendor / p.vendorTerm : 0;
  const service = bankService + vendorService;
  const cover = service > 0 ? ebitda / service : null;
  const verdict = cover === null ? "" : cover >= 2 ? "Comfortable" : cover >= 1.5 ? "Workable" : cover >= 1.2 ? "Tight" : "Does not cover";
  const num = (k: keyof typeof p, step = 1, w = 70) => (
    <input type="number" step={step} min={0} style={{ width: w }} value={p[k]} onChange={(e) => setP({ ...p, [k]: Number(e.target.value) })} />
  );
  return (
    <details className="dealcheck">
      <summary>Funding check: can the profit pay for the deal?</summary>
      <div className="dc-grid">
        <label className="field"><span className="label">Price, £</span>{num("price", 10000, 120)}</label>
        <label className="field"><span className="label">Your equity, %</span>{num("equity")}</label>
        <label className="field"><span className="label">Vendor loan, %</span>{num("vendor")}</label>
        <label className="field"><span className="label">Vendor loan over, years</span>{num("vendorTerm")}</label>
        <label className="field"><span className="label">Bank rate, %</span>{num("rate", 0.25)}</label>
        <label className="field"><span className="label">Bank term, years</span>{num("term")}</label>
      </div>
      <table className="dc-table">
        <tbody>
          <tr><td>Your equity</td><td className="num">{money((p.price * p.equity) / 100)}</td></tr>
          <tr><td>Vendor loan ({p.vendor}%)</td><td className="num">{money(vendor)}</td></tr>
          <tr><td>Bank debt ({bankPct}%)</td><td className="num">{money(bank)}</td></tr>
          <tr><td>Yearly repayments: bank {money(bankService)} + vendor {money(vendorService)}</td><td className="num"><b>{money(service)}</b></td></tr>
          <tr><td>Profit available (midpoint)</td><td className="num">{money(ebitda)}</td></tr>
          <tr className="total">
            <td>Debt cover <span className="faint small">profit ÷ repayments. Lenders usually want 1.5× or more.</span></td>
            <td className={`num ${cover !== null && cover < 1.2 ? "neg" : cover !== null && cover >= 1.5 ? "pos" : ""}`}>
              <b>{cover === null ? "—" : `${cover.toFixed(2)}×`}</b> {verdict}
            </td>
          </tr>
        </tbody>
      </table>
      <p className="faint small">Ignores tax, capital expenditure, working capital and your own salary, so real cover will be lower.</p>
    </details>
  );
}
