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

const round1 = (x: number) => Math.round(x * 10) / 10;

export default function Valuation({ data, num, onSaved }: { data: CompanyDetail; num: string; onSaved: () => void }) {
  const v = data.valuation;
  const [a, setA] = useState<Assumptions>(v.assumptions);
  const [dirty, setDirty] = useState(false);
  const est = data.estimate;
  const latest = [...data.financials].reverse().find((f) => !f.period_inferred);
  // Directors' pay from the newest accounts that show it (a starting point for the add-back).
  const latestPay = [...data.financials].reverse().find((f) => !f.period_inferred && toNum((f as any).director_pay ?? null));
  const op = toNum(latest?.operating_profit ?? null);

  // Same method as the server (backend/acquireos/valuation.py), recalculated live.
  const [marginTouched, setMarginTouched] = useState(false);
  const fm = v.filed_margin ?? null;
  const ownMargin = fm !== null && !marginTouched && v.override?.margin_low == null && v.override?.margin_high == null;
  const mLo = ownMargin ? Math.max(Number(fm), 0) : a.margin_low;
  const mHi = ownMargin ? Math.max(mLo, (mLo + a.margin_low) / 2) : a.margin_high;
  const live = useMemo(() => {
    if (op !== null && op > 0) return { eLo: op, eHi: op, basis: "filed" as const };
    if (op !== null && op <= 0) return null;  // loss-making as filed: no earnings-based value
    const rLo = toNum(est?.revenue_low ?? null), rHi = toNum(est?.revenue_high ?? null) ?? rLo;
    if (rLo === null || rHi === null) return null;
    return { eLo: (rLo * mLo) / 100, eHi: (rHi * mHi) / 100, basis: ownMargin ? "filed_margin" as const : "estimated" as const };
  }, [a, est, op, mLo, mHi, ownMargin]);
  // Lenders already secured on the company: repaid from the seller's proceeds
  // on a cash-free, debt-free deal, but they must release their charges.
  const lenders = [...new Set((data.ch?.charges ?? []).filter((x) => x.status !== "fully-satisfied").flatMap((x) => x.holders))];
  const outstanding = data.company.charges_outstanding ?? 0;
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
            <div><b>{range(live.eLo, live.eHi)}</b><span>Profit (EBITDA proxy) · {live.basis === "filed" ? "filed" : live.basis === "filed_margin" ? "own margin" : "estimate"}</span></div>
            <div><b className="hl">{range(vLo, vHi)}</b><span>Enterprise value</span></div>
            {v.cash ? <div><b>{money(v.cash)}</b><span>Cash on balance sheet, not included</span></div> : null}
          </div>
          <ol className="steps">
            {live.basis === "filed" ? (
              <li>Profit: filed operating profit of {money(op)}. Depreciation is not added back, so true EBITDA is likely higher.</li>
            ) : (
              <li>Profit: {est?.basis === "filed" ? "filed turnover" : "estimated revenue"} of {range(est!.revenue_low, est!.revenue_high)} × {round1(mLo)}–{round1(mHi)}% margin
                {live.basis === "filed_margin"
                  ? <> (<b>the company's own</b>: {round1(Number(fm))}% in its {String(v.filed_margin_period ?? "").slice(0, 4)} accounts, the latest showing profit; the upper end allows for some improvement).</>
                  : <> (your buy box's assumption{fm === null ? "; no profit has ever been filed" : ""}).</>}</li>
            )}
            <li>Value: profit × {a.multiple_low}–{a.multiple_high} times.</li>
            <li>Debt is not netted off: on a cash-free, debt-free deal it is repaid from the seller's proceeds.</li>
          </ol>
          {outstanding > 0 && (
            <div className="callout amber">
              <b>Existing secured lenders{lenders.length ? `: ${lenders.join(", ")}` : ` (${outstanding} outstanding charge${outstanding === 1 ? "" : "s"})`}.</b>{" "}
              On a cash-free, debt-free deal they're repaid from the seller's proceeds and must release their charges at completion.
              Ask early how much is owed: the register shows the security, not the balance.
            </div>
          )}
          <div className="assume">
            {FIELDS.map((f) => (
              <label key={f.k} className="field">
                <span className="label">{f.label}</span>
                <span className="unit">
                  <input type="number" step={f.step} min={0} value={a[f.k]} disabled={live.basis === "filed" && f.k.startsWith("margin")}
                         onChange={(e) => { setA({ ...a, [f.k]: Number(e.target.value) }); setDirty(true); if (f.k.startsWith("margin")) setMarginTouched(true); }} />
                  <i>{f.unit}</i>
                </span>
              </label>
            ))}
            <div className="assume-actions">
              {dirty && <button className="btn primary" onClick={() => save(a)}>Save for this company</button>}
              {(isOverride || dirty) && (
                <button className="btn quiet" onClick={() => { setA(v.defaults); setMarginTouched(false); save(null); }}>Use buy box defaults</button>
              )}
              {!dirty && !isOverride && <span className="faint small">{ownMargin
                ? "Using the company's own margin (above); the margin boxes are your buy box's defaults. Change them to override."
                : "Defaults from your buy box. Change them here for this company only."}</span>}
              {!dirty && isOverride && <span className="small" style={{ color: "var(--amber)" }}>Using your own assumptions for this company.</span>}
            </div>
          </div>
          <DealCheck eLo={live.eLo} eHi={live.eHi} vLo={vLo ?? 0} vHi={vHi ?? 0} saved={data.state.funding ?? {}}
                     directorPay={toNum(latestPay?.director_pay ?? null)} payYear={latestPay?.period_end ?? null}
                     multiples={[a.multiple_low, a.multiple_high]}
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

function DealCheck({ eLo, eHi, vLo, vHi, saved, onSave, directorPay, payYear, multiples }: {
  eLo: number; eHi: number; vLo: number; vHi: number; saved: Partial<Funding> & { investor_cash?: number; vendor_pct?: number };
  onSave: (f: Funding) => Promise<unknown>; directorPay?: number | null; payYear?: string | null; multiples: [number, number];
}) {
  const mid = Math.round(((vLo + vHi) / 2) / 10000) * 10000;
  // Older saved checks used investor_cash / vendor_pct: read them once.
  const start: Funding = {
    price: mid, your_cash: 0, investor_equity: 0, investor_stake: 30, investor_loan: 0, investor_rate: 10, investor_years: 5,
    vendor_loan: Math.round(mid * 0.3 / 10000) * 10000, vendor_rate: 0, vendor_years: 3, bank_rate: 9, bank_years: 5,
    addback_owner_pay: directorPay && directorPay > 0 ? Math.round(directorPay / 1000) * 1000 : 0, addback_other: 0,
    new_salaries: 0, new_oncost: 15,
    ...saved,
  } as Funding;
  if (saved.investor_cash !== undefined && saved.investor_equity === undefined) start.investor_equity = saved.investor_cash;
  if (saved.vendor_pct !== undefined && saved.vendor_loan === undefined) start.vendor_loan = Math.round(start.price * saved.vendor_pct / 100);
  const [f, setF] = useState<Funding>(start);
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

  // Sources of funds. The bank (or other lender) provides whatever is left.
  const named = f.your_cash + f.investor_equity + f.investor_loan + f.vendor_loan;
  const bank = Math.max(0, f.price - named);
  const over = named - f.price;
  const pct = (v: number) => (f.price > 0 ? `${Math.round((100 * v) / f.price)}%` : "—");
  const yearly = {
    investor: annuity(f.investor_loan, f.investor_rate, f.investor_years),
    vendor: annuity(f.vendor_loan, f.vendor_rate, f.vendor_years),
    bank: annuity(bank, f.bank_rate, f.bank_years),
  };
  const service = yearly.investor + yearly.vendor + yearly.bank;
  // Adjusted EBITDA: add back costs that leave with the seller, take off the new team's cost.
  const newTeam = (f.new_salaries ?? 0) * (1 + (f.new_oncost ?? 0) / 100);
  const adj = (f.addback_owner_pay ?? 0) + (f.addback_other ?? 0) - newTeam;
  const rawMid = (eLo + eHi) / 2;
  const [aLo, aHi] = [eLo + adj, eHi + adj];
  const eMid = rawMid + adj;
  const cover = (profit: number) => (service > 0 ? profit / service : null);
  const verdict = (c: number | null) => c === null ? "No debt" : c >= 2 ? "Comfortable" : c >= 1.5 ? "Workable" : c >= 1.2 ? "Tight" : "Does not cover";
  const coverCls = (c: number | null) => (c !== null && c < 1.2 ? "neg" : c !== null && c >= 1.5 ? "pos" : "");
  const yours = f.investor_equity > 0 ? 100 - f.investor_stake : 100;
  const left = (profit: number) => profit - service;

  const money_ = (k: keyof Funding, w = 120) => (
    <MoneyInput value={f[k]} width={w} onChange={(v) => set({ [k]: v ?? 0 } as Partial<Funding>)} />
  );
  const num = (k: keyof Funding, step = 1, w = 58) => (
    <input type="number" step={step} min={0} style={{ width: w }} value={f[k]} aria-label={k}
           onChange={(e) => set({ [k]: Number(e.target.value) } as Partial<Funding>)} />
  );
  const yr = (v: number) => (v > 0 ? money(v) : "—");

  return (
    <details className="dealcheck" open={Object.keys(saved).length > 0}>
      <summary>Funding check: can the profit pay for the deal? <span className="faint small">{note}</span></summary>

      <div className="dc-price">
        <label className="field"><span className="label">Price</span>{money_("price", 150)}</label>
        <span className="faint small">Starts at the middle of the indicative value ({money(mid)}). Change it to the price you have in mind.</span>
      </div>

      <h4 className="dc-h">1. Where the money comes from</h4>
      <table className="dc-table dc-sources">
        <thead><tr><th>Source</th><th className="num">Amount</th><th className="num">Of price</th><th className="num">Rate</th><th className="num">Years</th><th className="num">Repaid a year</th></tr></thead>
        <tbody>
          <tr><td>Your cash<div className="sub">{f.your_cash === 0 ? "None: your equity is sweat" : "Equity: not repaid"}</div></td>
            <td className="num">{money_("your_cash")}</td><td className="num">{pct(f.your_cash)}</td><td /><td /><td className="num faint">—</td></tr>
          <tr><td>Investor equity<div className="sub">e.g. DBW: cash in return for a share of the company. Not repaid.</div></td>
            <td className="num">{money_("investor_equity")}</td><td className="num">{pct(f.investor_equity)}</td>
            <td className="num" colSpan={2}><span className="faint small">their stake </span>{num("investor_stake")}%</td><td className="num faint">—</td></tr>
          <tr><td>Investor loan<div className="sub">The same investor's debt alongside the equity</div></td>
            <td className="num">{money_("investor_loan")}</td><td className="num">{pct(f.investor_loan)}</td>
            <td className="num">{num("investor_rate", 0.25)}%</td><td className="num">{num("investor_years")}</td><td className="num">{yr(yearly.investor)}</td></tr>
          <tr><td>Vendor loan<div className="sub">Part of the price paid to the seller over time</div></td>
            <td className="num">{money_("vendor_loan")}</td><td className="num">{pct(f.vendor_loan)}</td>
            <td className="num">{num("vendor_rate", 0.25)}%</td><td className="num">{num("vendor_years")}</td><td className="num">{yr(yearly.vendor)}</td></tr>
          <tr><td>Bank or other lender<div className="sub">Whatever is left (worked out)</div></td>
            <td className="num"><b>{money(bank)}</b></td><td className="num">{pct(bank)}</td>
            <td className="num">{num("bank_rate", 0.25)}%</td><td className="num">{num("bank_years")}</td><td className="num">{yr(yearly.bank)}</td></tr>
          <tr className="total"><td>Total</td><td className="num"><b>{money(Math.max(f.price, named))}</b></td><td className="num">{over > 0 ? pct(named) : "100%"}</td>
            <td /><td /><td className="num"><b>{money(service)}</b></td></tr>
        </tbody>
      </table>
      {over > 0 && <div className="callout red">These add up to {money(named)}, which is {money(over)} more than the price. Lower one of them.</div>}

      <h4 className="dc-h">2. Adjusted profit (EBITDA)</h4>
      <table className="dc-table dc-walk">
        <thead><tr><th /><th className="num">Low</th><th className="num">Middle</th><th className="num">High</th></tr></thead>
        <tbody>
          <tr><td>Profit a year <span className="faint small">(EBITDA proxy, from above)</span></td>
            <td className="num">{money(eLo)}</td><td className="num">{money(rawMid)}</td><td className="num">{money(eHi)}</td></tr>
          <tr><td>+ Departing owners' pay
              <div className="sub">{directorPay ? `Directors' pay filed: ${money(directorPay)}${payYear ? ` (${String(payYear).slice(0, 4)})` : ""}. ` : ""}Salaries, pension and benefits that stop when they leave</div></td>
            <td className="num" colSpan={3}>{money_("addback_owner_pay")}</td></tr>
          <tr><td>+ Other one-off or owner costs<div className="sub">e.g. family on the payroll, personal car, one-off legal fees</div></td>
            <td className="num" colSpan={3}>{money_("addback_other")}</td></tr>
          <tr><td>− New team salaries<div className="sub">Your salary and any new hires (MBI team)</div></td>
            <td className="num" colSpan={3}>{money_("new_salaries")}
              <span className="faint small"> + on-costs </span>{num("new_oncost")}%<span className="faint small"> = {money(newTeam)}</span></td></tr>
          <tr className="total"><td>= Adjusted EBITDA</td>
            {[aLo, eMid, aHi].map((e, i) => <td key={i} className={`num ${e < 0 ? "neg" : ""}`}><b>{money(e)}</b></td>)}</tr>
          <tr><td>Value at your multiples ({multiples[0]}–{multiples[1]}×)<div className="sub">On adjusted EBITDA, compared with your price of {money(f.price)}</div></td>
            <td className="num" colSpan={3}>{range(Math.max(aLo, 0) * multiples[0], Math.max(aHi, 0) * multiples[1])}</td></tr>
        </tbody>
      </table>

      <h4 className="dc-h">3. Can the business pay it back?</h4>
      <table className="dc-table dc-walk">
        <thead><tr><th /><th className="num">Low</th><th className="num">Middle</th><th className="num">High</th></tr></thead>
        <tbody>
          <tr><td>Adjusted EBITDA <span className="faint small">(from step 2)</span></td>
            <td className="num">{money(aLo)}</td><td className="num"><b>{money(eMid)}</b></td><td className="num">{money(aHi)}</td></tr>
          <tr><td>− Loan repayments a year</td>
            <td className="num">{money(service)}</td><td className="num">{money(service)}</td><td className="num">{money(service)}</td></tr>
          <tr className="total"><td>= Left after repayments</td>
            {[aLo, eMid, aHi].map((e, i) => <td key={i} className={`num ${left(e) < 0 ? "neg" : ""}`}><b>{money(left(e))}</b></td>)}</tr>
          <tr><td>Your share ({yours}%){f.investor_equity > 0 ? <span className="faint small"> · the investor's {f.investor_stake}% is theirs</span> : null}</td>
            {[aLo, eMid, aHi].map((e, i) => <td key={i} className={`num ${left(e) < 0 ? "neg" : ""}`}>{money((left(e) * yours) / 100)}</td>)}</tr>
          <tr><td>Debt cover <span className="faint small">profit ÷ repayments; lenders usually want 1.5× or more</span></td>
            {[aLo, eMid, aHi].map((e, i) => { const c = cover(e); return (
              <td key={i} className={`num ${coverCls(c)}`}><b>{c === null ? "—" : `${c.toFixed(1)}×`}</b><div className="small">{verdict(c)}</div></td>); })}</tr>
        </tbody>
      </table>
      <p className="faint small">Before tax, capex and fees. Your salary is in the adjustments (step 2).</p>
    </details>
  );
}
