"""Indicative valuation from filed or estimated figures.

This is a screening estimate, not a valuation. Every result says which
figures it used and which were assumed, so it can be checked and overridden.

Method:
  1. Profit (EBITDA): filed operating profit when the latest accounts include
     it, plus depreciation and amortisation where those are filed too (true
     EBITDA); otherwise revenue × a margin: the company's own margin from
     the most recent accounts that showed profit (if any), else the buy box's
     assumed range.
  2. Enterprise value: profit × an assumed multiple range.
  3. Cash and bank debt on the balance sheet are reported separately, not
     netted off: on a cash-free, debt-free deal they are settled from the price.
"""
from __future__ import annotations

DEFAULTS = {
    # UK IT services and software businesses of this size commonly change
    # hands at roughly 3 to 6 times EBITDA. Adjust to your own evidence.
    "margin_low": 8.0,
    "margin_high": 15.0,
    "multiple_low": 3.0,
    "multiple_high": 5.0,
}


def assumptions(criteria: dict | None, override: dict | None = None) -> dict:
    a = dict(DEFAULTS)
    a.update({k: float(v) for k, v in ((criteria or {}).get("valuation") or {}).items() if k in DEFAULTS and v is not None})
    a.update({k: float(v) for k, v in (override or {}).items() if k in DEFAULTS and v not in (None, "")})
    return a


def value(f: dict, a: dict, use_filed_margin: bool = True) -> dict:
    """f: facts with revenue_low/high, revenue_basis, operating_profit, cash."""
    steps: list[str] = []
    op = f.get("operating_profit")
    if op is not None and op > 0:
        da = f.get("da")
        basis = "filed"
        if da:
            e_lo = e_hi = float(op) + float(da)
            steps.append(f"Profit: filed operating profit of {_m(op)} + depreciation and amortisation of {_m(da)} "
                         f"= EBITDA of {_m(e_lo)}, all from the latest accounts.")
        else:
            e_lo = e_hi = float(op)
            steps.append(f"Profit: filed operating profit of {_m(op)}. Depreciation isn't in these accounts, "
                         "so true EBITDA may be higher.")
    elif op is not None and op <= 0:
        # Filed as loss-making: an earnings multiple does not apply, and an
        # assumed margin would invent profit the accounts say is not there.
        return {"ebitda_low": None, "ebitda_high": None, "value_low": None, "value_high": None, "basis": "loss",
                "steps": [f"Loss-making as filed: operating profit of {_m(op)} in the latest accounts. "
                          "No earnings-based value; it would be priced on its assets or a turnaround view."]}
    elif f.get("revenue_low"):
        r_lo, r_hi = float(f["revenue_low"]), float(f["revenue_high"] or f["revenue_low"])
        rb = "filed turnover" if f.get("revenue_basis") == "filed" else "estimated revenue"
        fm = f.get("filed_margin")
        if use_filed_margin and fm is not None:
            # The company's own margin from its last profit and loss account
            # beats a generic assumption. Allow some improvement since then,
            # up to halfway to the buy box's low margin.
            yr = str(f.get("filed_margin_period") or "")[:4]
            m_lo = max(float(fm), 0.0)
            m_hi = max(m_lo, (m_lo + a["margin_low"]) / 2)
            e_lo, e_hi = r_lo * m_lo / 100, r_hi * m_hi / 100
            basis = "filed_margin"
            steps.append(
                f"Profit: {rb} of {_m(r_lo)}–{_m(r_hi)} × {m_lo:g}–{m_hi:g}% margin = {_m(e_lo)}–{_m(e_hi)}. "
                f"The margin is the company's own: {float(fm):g}% in its {yr or 'last'} accounts, the latest that "
                f"show profit; the upper end allows for some improvement since.")
        else:
            e_lo, e_hi = r_lo * a["margin_low"] / 100, r_hi * a["margin_high"] / 100
            basis = "estimated"
            steps.append(
                f"Profit: {rb} of {_m(r_lo)}–{_m(r_hi)} × {a['margin_low']:g}–{a['margin_high']:g}% margin "
                f"(your buy box's assumption; no profit has been filed) = {_m(e_lo)}–{_m(e_hi)}."
            )
    else:
        return {"ebitda_low": None, "ebitda_high": None, "value_low": None, "value_high": None,
                "basis": None, "steps": ["Not enough figures filed to estimate profit."]}
    v_lo, v_hi = e_lo * a["multiple_low"], e_hi * a["multiple_high"]
    steps.append(f"Value: {_m(e_lo)}–{_m(e_hi)} × {a['multiple_low']:g}–{a['multiple_high']:g} times = {_m(v_lo)}–{_m(v_hi)}.")
    if f.get("cash"):
        steps.append(f"Cash on the balance sheet: {_m(f['cash'])}. Not included above; it would normally be priced separately.")
    if f.get("bank_debt"):
        steps.append(f"Bank loans and overdrafts: {_m(f['bank_debt'])}. Not taken off above; on a cash-free, debt-free deal "
                     "they are repaid from the price, so the seller receives less.")
    return {"ebitda_low": e_lo, "ebitda_high": e_hi, "value_low": v_lo, "value_high": v_hi, "basis": basis, "steps": steps}


def _m(v) -> str:
    v = float(v)
    sign, v = ("−" if v < 0 else ""), abs(v)
    if v >= 1_000_000:
        return f"{sign}£{v / 1_000_000:.1f}m"
    if v >= 1_000:
        return f"{sign}£{v / 1_000:.0f}k"
    return f"{sign}£{v:.0f}"
