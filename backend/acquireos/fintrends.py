"""Financial trends for a company profile: per-year figures (with totals the
accounts do not state directly worked out from those they do), the change
on the year before, and a plain-English description of the trend.

Shared by the web page and the MCP tools, so both describe a company the same
way. Works from filed periods only (not the inferred prior-year rows).
"""
from __future__ import annotations

from datetime import date

# key -> (label, higher is better?)
METRICS = {
    "cash": ("Cash in bank", True),
    "turnover": ("Turnover", True),
    "operating_profit": ("Operating profit", True),
    "employees": ("Employees", True),
    "total_assets": ("Total assets", True),
    "total_liabilities": ("Total liabilities", False),
    "net_assets": ("Net assets", True),
    "debt_ratio": ("Debt ratio", False),
}


def _f(v):
    return None if v is None else float(v)


def derive(period: dict) -> dict:
    """Totals that small-company accounts imply but rarely state:
    total assets = fixed + current assets (or total assets less current
    liabilities + current liabilities); total liabilities = total assets -
    net assets; debt ratio = liabilities / assets."""
    fa, ca = _f(period.get("fixed_assets")), _f(period.get("current_assets"))
    nca, tal = _f(period.get("net_current_assets")), _f(period.get("total_assets_less_cl"))
    na = _f(period.get("net_assets"))
    ta = None
    if fa is not None and ca is not None:
        ta = fa + ca
    elif tal is not None and ca is not None and nca is not None:
        ta = tal + (ca - nca)
    elif ca is not None and fa is None and tal is not None and nca is not None and abs(tal - nca) < 1:
        ta = ca  # no fixed assets
    tl = ta - na if ta is not None and na is not None else None
    if tl is not None and tl < 0:
        tl = None  # the filing's totals do not add up
    ratio = round(100 * tl / ta, 1) if tl is not None and ta else None
    return {"total_assets": ta, "total_liabilities": tl, "debt_ratio": ratio}


def series(financials: list[dict]) -> list[dict]:
    """Filed periods oldest first, one per period end, with derived totals."""
    out = []
    for f in financials:
        if f.get("period_inferred"):
            continue
        row = {"period_end": f["period_end"], **{k: _f(f.get(k)) for k in
               ("cash", "turnover", "operating_profit", "profit_loss", "net_assets", "debtors")}}
        row["employees"] = f.get("employees")
        row.update(derive(f))
        out.append(row)
    out.sort(key=lambda r: str(r["period_end"]))
    return out


def _trend(values: list[float], higher_good: bool) -> str:
    """One sentence on the shape of the last few years (oldest first)."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    last, prev = vals[-1], vals[-2]
    change = (last - prev) / abs(prev) if prev else None
    recent = vals[-5:]
    peak_i = max(range(len(recent)), key=lambda i: recent[i])
    low_i = min(range(len(recent)), key=lambda i: recent[i])
    rises = sum(1 for a, b in zip(recent, recent[1:]) if b > a)
    falls = sum(1 for a, b in zip(recent, recent[1:]) if b < a)
    steps = len(recent) - 1
    if len(recent) >= 4 and rises == steps:
        diffs = [b - a for a, b in zip(recent, recent[1:])]
        return "Has been growing at an increasing rate" if diffs[-1] > diffs[0] * 1.2 else "Has grown every year"
    if len(recent) >= 4 and falls == steps:
        return "Has fallen every year"
    if len(recent) >= 3 and 0 < peak_i < len(recent) - 1 and recent[-1] < recent[peak_i] * 0.9:
        return f"Peaked earlier in the past {len(recent)} years and has been falling since"
    if len(recent) >= 3 and 0 < low_i < len(recent) - 1 and recent[-1] > recent[low_i] * 1.1:
        return "Dipped and has risen since"
    if change is None:
        return "Changed from zero"
    if change >= 0.10:
        return "Has grown significantly in the most recent year"
    if change <= -0.10:
        return "Has dropped significantly in the most recent year"
    if abs(change) < 0.02:
        return "Little change on the year before"
    if abs(change) < 0.05:
        return "Up slightly on the year before" if change > 0 else "Down slightly on the year before"
    return "Up on the year before" if change > 0 else "Down on the year before"


def summary(financials: list[dict]) -> dict:
    """{period_end, previous_end, rows: [{key, label, value, change, change_pct, good, trend}], series}"""
    s = series(financials)
    if not s:
        return {"period_end": None, "rows": [], "series": []}
    latest = s[-1]
    prev = s[-2] if len(s) > 1 else None
    rows = []
    for key, (label, higher_good) in METRICS.items():
        v = latest.get(key)
        if v is None:
            continue
        p = prev.get(key) if prev else None
        change = (v - p) if p is not None else None
        pct = round(100 * change / abs(p), 1) if change is not None and p else None
        good = None if change in (None, 0) else (change > 0) == higher_good
        rows.append({"key": key, "label": label, "value": v, "change": change, "change_pct": pct, "good": good,
                     "trend": _trend([r.get(key) for r in s], higher_good)})
    months = None
    if prev:
        try:
            a, b = date.fromisoformat(str(prev["period_end"])[:10]), date.fromisoformat(str(latest["period_end"])[:10])
            months = round((b - a).days / 30.44)
        except ValueError:
            pass
    return {"period_end": latest["period_end"], "previous_end": prev["period_end"] if prev else None,
            "months": months, "rows": rows, "series": s}
