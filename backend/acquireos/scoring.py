"""Score companies against a saved buy box, with a reason for every point.

Missing data scores nothing but is reported as "unknown" rather than as a
miss, and each score carries a coverage figure: the share of the possible
points that could actually be assessed.
"""
from __future__ import annotations

import json
import re
from datetime import date

DEFAULT_CRITERIA = {
    "staff": {"weight": 25, "min": 10, "ideal_min": 20, "ideal_max": 60, "max": 150},
    "years_trading": {"weight": 15, "min": 8, "ideal": 15},
    "revenue": {"weight": 15, "min": 1_000_000, "ideal_min": 2_000_000, "ideal_max": 8_000_000, "max": 15_000_000},
    "owner_age": {"weight": 20, "min": 50, "ideal": 60},
    "ownership": {"weight": 15, "good": ["owner_held"], "neutral": ["unknown", "trust"]},
    "net_asset_growth": {"weight": 5},
    "sic": {"weight": 5, "preferred": ["62012", "62020", "62030", "62090", "63110", "63120", "58290", "58210"]},
    "regions": [],
    "exclude": {
        "statuses": ["dissolved", "liquidation", "administration", "receivership", "converted-closed"],
        "tiers": ["Dormant"],
        "ownership": ["eot"],
        "keywords": ["electrical", "plumbing", "heating", "cctv", "fire alarm", "scaffold", "roofing", "cleaning"],
        "address_flags": [],
    },
}

STATUS_GOOD, STATUS_PART, STATUS_MISS, STATUS_UNKNOWN = "good", "partial", "miss", "unknown"


def merged(criteria: dict | None) -> dict:
    out = json.loads(json.dumps(DEFAULT_CRITERIA))
    for k, v in (criteria or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def _band(value, lo, ideal_lo, ideal_hi, hi):
    """1.0 inside the ideal band, tapering to 0 at the outer limits."""
    if value < lo or value > hi:
        return 0.0
    if ideal_lo <= value <= ideal_hi:
        return 1.0
    if value < ideal_lo:
        return 0.4 + 0.6 * (value - lo) / max(ideal_lo - lo, 1)
    return 0.4 + 0.6 * (hi - value) / max(hi - ideal_hi, 1)


def _money(v):
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"£{v / 1_000_000:.1f}m"
    if abs(v) >= 1_000:
        return f"£{v / 1_000:.0f}k"
    return f"£{v:.0f}"


def score_company(c: dict, criteria: dict, today: date | None = None) -> dict:
    """c holds the company's facts (see load_facts). Returns score dict."""
    today = today or date.today()
    cr = merged(criteria)
    reasons = []

    def add(key, label, weight, frac, status, text):
        pts = round(weight * frac, 1) if status != STATUS_UNKNOWN else 0.0
        reasons.append({"key": key, "label": label, "points": pts, "max": weight, "status": status, "text": text})

    # exclusions first
    ex = cr["exclude"]
    exclusion = None
    if c.get("status") and c["status"].lower() in [s.lower() for s in ex.get("statuses", [])]:
        exclusion = f"Company status is {c['status']}"
    elif c.get("review_tier") and c["review_tier"] in ex.get("tiers", []):
        exclusion = f"Review tier is {c['review_tier']}"
    elif c.get("ownership_type") and c["ownership_type"] in ex.get("ownership", []):
        from .ownership import TYPE_LABELS

        exclusion = f"Ownership: {TYPE_LABELS.get(c['ownership_type'], c['ownership_type']).lower()}"
    elif c.get("address_flag") and c["address_flag"] in ex.get("address_flags", []):
        exclusion = "Registered at an excluded address type"
    else:
        hay = f"{c.get('name') or ''} {c.get('nature_of_business') or ''} {c.get('research_text') or ''}".lower()
        for kw in ex.get("keywords", []):
            if kw and re.search(r"\b" + re.escape(kw.lower()) + r"\b", hay):
                exclusion = f"Matches excluded keyword “{kw}”"
                break
    regions = cr.get("regions") or []
    if not exclusion and regions and (c.get("region") or "") not in regions:
        exclusion = f"Outside chosen regions ({', '.join(regions)})"

    s = cr["staff"]
    if c.get("employees") is None:
        add("staff", "Staff", s["weight"], 0, STATUS_UNKNOWN, "No staff number filed")
    else:
        e = c["employees"]
        f = _band(e, s["min"], s["ideal_min"], s["ideal_max"], s["max"])
        st = STATUS_GOOD if f == 1 else STATUS_PART if f > 0 else STATUS_MISS
        add("staff", "Staff", s["weight"], f, st,
            f"{e} staff; ideal {s['ideal_min']}–{s['ideal_max']}, acceptable {s['min']}–{s['max']}")

    y = cr["years_trading"]
    if not c.get("incorporation_date"):
        add("years", "Years trading", y["weight"], 0, STATUS_UNKNOWN, "No incorporation date")
    else:
        yrs = (today - c["incorporation_date"]).days / 365.25
        if yrs >= y["ideal"]:
            f, st = 1.0, STATUS_GOOD
        elif yrs >= y["min"]:
            f, st = 0.5 + 0.5 * (yrs - y["min"]) / max(y["ideal"] - y["min"], 1), STATUS_PART
        else:
            f, st = 0.0, STATUS_MISS
        add("years", "Years trading", y["weight"], f, st, f"{yrs:.0f} years; looking for {y['ideal']}+ (minimum {y['min']})")

    r = cr["revenue"]
    if c.get("revenue_low") is None:
        add("revenue", "Revenue", r["weight"], 0, STATUS_UNKNOWN, "No turnover filed and no staff to estimate from")
    else:
        mid = (c["revenue_low"] + c["revenue_high"]) / 2
        f = _band(mid, r["min"], r["ideal_min"], r["ideal_max"], r["max"])
        st = STATUS_GOOD if f == 1 else STATUS_PART if f > 0 else STATUS_MISS
        basis = "filed" if c.get("revenue_basis") == "filed" else "estimated"
        rng = _money(c["revenue_low"]) if c["revenue_low"] == c["revenue_high"] else f"{_money(c['revenue_low'])}–{_money(c['revenue_high'])}"
        add("revenue", "Revenue", r["weight"], f, st,
            f"{rng} ({basis}); ideal {_money(r['ideal_min'])}–{_money(r['ideal_max'])}")

    o = cr["owner_age"]
    if not c.get("oldest_birth_year"):
        add("owner_age", "Owner age", o["weight"], 0, STATUS_UNKNOWN, "No individual owner with a birth date on file")
    else:
        age = today.year - c["oldest_birth_year"]
        if age >= o["ideal"]:
            f, st = 1.0, STATUS_GOOD
        elif age >= o["min"]:
            f, st = 0.4 + 0.6 * (age - o["min"]) / max(o["ideal"] - o["min"], 1), STATUS_PART
        else:
            f, st = 0.0, STATUS_MISS
        add("owner_age", "Owner age", o["weight"], f, st,
            f"Oldest owner about {age}; succession more likely from {o['ideal']}")

    ow = cr["ownership"]
    t = c.get("ownership_type")
    if not t or t == "unknown":
        add("ownership", "Ownership", ow["weight"], 0, STATUS_UNKNOWN, "Ownership not yet traced")
    elif t in ow["good"]:
        add("ownership", "Ownership", ow["weight"], 1, STATUS_GOOD, "Owner-held" + (" through a holding company" if "via_holdco" in (c.get("ownership_flags") or []) else ""))
    elif t in ow.get("neutral", []):
        add("ownership", "Ownership", ow["weight"], 0.5, STATUS_PART, t.replace("_", " ").capitalize())
    else:
        add("ownership", "Ownership", ow["weight"], 0, STATUS_MISS, t.replace("_", " ").capitalize())

    g = cr["net_asset_growth"]
    if c.get("net_assets") is None or c.get("net_assets_prev") is None:
        add("growth", "Net asset growth", g["weight"], 0, STATUS_UNKNOWN, "Need two years of net assets")
    else:
        d = c["net_assets"] - c["net_assets_prev"]
        f = 1.0 if d > 0 else 0.0
        add("growth", "Net asset growth", g["weight"], f, STATUS_GOOD if d > 0 else STATUS_MISS,
            f"Net assets {'up' if d > 0 else 'down'} {_money(abs(d))} on the year")

    sc = cr["sic"]
    codes = c.get("sic_codes") or []
    hit = [code for code in codes if code in sc["preferred"]]
    if not codes:
        add("sic", "Industry code", sc["weight"], 0, STATUS_UNKNOWN, "No SIC code filed")
    else:
        add("sic", "Industry code", sc["weight"], 1 if hit else 0, STATUS_GOOD if hit else STATUS_MISS,
            f"SIC {', '.join(codes)}" + (" includes a preferred code" if hit else "; none preferred"))

    total = sum(x["max"] for x in reasons)
    got = sum(x["points"] for x in reasons)
    known = sum(x["max"] for x in reasons if x["status"] != STATUS_UNKNOWN)
    return {
        "score": round(100 * got / total, 1) if total else 0.0,
        "coverage": round(100 * known / total, 0) if total else 0.0,
        "excluded": exclusion is not None,
        "exclusion": exclusion,
        "reasons": reasons,
    }


FACTS_SQL = """
with latest as (
    select distinct on (company_number) company_number, employees, net_assets, period_end
    from financial_period where not period_inferred
    order by company_number, period_end desc
), prev as (
    select distinct on (fp.company_number) fp.company_number, fp.net_assets
    from financial_period fp join latest l on l.company_number = fp.company_number
    where fp.period_end < l.period_end and fp.net_assets is not null
    order by fp.company_number, fp.period_end desc
), research_text as (
    select company_number, string_agg(content, ' ') as txt from research group by company_number
)
select c.company_number, c.name, c.status, c.review_tier, c.incorporation_date, c.sic_codes,
       c.nature_of_business, c.region, c.address_flag,
       l.employees, l.net_assets, p.net_assets as net_assets_prev,
       e.revenue_low, e.revenue_high, e.basis as revenue_basis,
       o.ownership_type, o.flags as ownership_flags, o.oldest_birth_year,
       rt.txt as research_text
from company c
left join latest l on l.company_number = c.company_number
left join prev p on p.company_number = c.company_number
left join estimate e on e.company_number = c.company_number
left join company_ownership o on o.company_number = c.company_number
left join research_text rt on rt.company_number = c.company_number
{where}
"""


def load_facts(conn, company_number: str | None = None) -> list[dict]:
    where = "where c.company_number = %s" if company_number else ""
    params = (company_number,) if company_number else ()
    rows = conn.execute(FACTS_SQL.format(where=where), params).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        for k in ("net_assets", "net_assets_prev", "revenue_low", "revenue_high"):
            if r.get(k) is not None:
                r[k] = float(r[k])
        out.append(r)
    return out


def active_buy_box(conn, user_id: int = 1) -> dict:
    row = conn.execute(
        "select * from buy_box where user_id = %s and is_active order by id limit 1", (user_id,)
    ).fetchone()
    if row:
        return dict(row)
    row = conn.execute(
        "insert into buy_box (user_id, name, criteria) values (%s, %s, %s) returning *",
        (user_id, "My buy box", json.dumps(DEFAULT_CRITERIA)),
    ).fetchone()
    return dict(row)


def rescore(conn, buy_box: dict | None = None, company_number: str | None = None) -> int:
    bb = buy_box or active_buy_box(conn)
    facts = load_facts(conn, company_number)
    today = date.today()
    if company_number is None:
        conn.execute("delete from score where buy_box_id = %s", (bb["id"],))
    with conn.cursor() as cur:
        rows = []
        for f in facts:
            s = score_company(f, bb["criteria"], today)
            rows.append((bb["id"], f["company_number"], s["score"], s["coverage"], s["excluded"],
                         s["exclusion"], json.dumps(s["reasons"])))
        cur.executemany(
            """insert into score (buy_box_id, company_number, score, coverage, excluded, exclusion, reasons)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (buy_box_id, company_number) do update set score = excluded.score,
                 coverage = excluded.coverage, excluded = excluded.excluded, exclusion = excluded.exclusion,
                 reasons = excluded.reasons, computed_at = now()""",
            rows,
        )
    return len(facts)
