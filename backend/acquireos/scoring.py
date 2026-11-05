"""Score companies against a saved buy box, with a reason for every point.

Missing data is neutral: it earns half the points (neither a hit nor a
miss) and is reported as "unknown". Each score carries a coverage figure:
the share of the possible points that could actually be assessed.
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
    "valuation": {"margin_low": 8.0, "margin_high": 15.0, "multiple_low": 3.0, "multiple_high": 5.0},
    # Your own criteria, scored 0-5 on each company. Keys are shared across
    # buy boxes, so a company is never scored twice for the same thing.
    "manual": [
        {"key": "recurring_quality", "label": "Recurring revenue quality", "weight": 10,
         "help": "5 = mostly contracted or subscription revenue with low churn"},
        {"key": "customer_spread", "label": "Customer spread", "weight": 5,
         "help": "5 = no customer over 10% of revenue; 0 = one customer dominates"},
        {"key": "owner_openness", "label": "Owner open to selling", "weight": 10,
         "help": "5 = owner has said they want to sell or retire soon"},
        {"key": "management_depth", "label": "Team beyond the owner", "weight": 5,
         "help": "5 = runs without the owner day to day"},
    ],
    # Which companies count as targets (the universe).
    # Companies already in the database are always kept up to date.
    "universe": {
        "sic_prefixes": ["5821", "5829", "6190", "620", "631"],
        "keyword_sic_prefixes": ["70229", "74909", "82990"],
        "name_keywords": ["software", "digital", "data", "computing", "systems", "technology", "technologies",
                          "cloud", "networks", "IT services", "IT solutions", "analytics", "cyber"],
        "postcode_areas": [],
        "min_years": 3,
        # A holding company that owns a company in the universe is in scope too
        # (you may buy the parent rather than the trading company).
        "include_parents": True,
    },
    "exclude": {
        # Matched as phrases within the Companies House status, so "in administration",
        # "receiver action" and "active - proposal to strike off" are caught.
        "statuses": ["dissolved", "liquidation", "administration", "receiver", "voluntary arrangement",
                     "insolvency", "converted-closed", "closed", "removed from register", "proposal to strike off"],
        "tiers": ["Dormant"],
        "ownership": ["eot"],
        "keywords": ["electrical", "plumbing", "heating", "cctv", "fire alarm", "scaffold", "roofing", "cleaning"],
        "address_flags": [],
        # Exclude companies that research has found to be field-service or
        # van-based (from the enrichment field_service = yes).
        "field_service": True,
    },
}

STATUS_GOOD, STATUS_PART, STATUS_MISS, STATUS_UNKNOWN = "good", "partial", "miss", "unknown"

# Starting points for new buy boxes. Every value is editable afterwards; the
# valuation multiples are rough market ranges, not advice.
TEMPLATES: dict[str, dict] = {
    "msp": {
        "label": "Managed IT services (MSP)",
        "description": "IT support and managed services businesses with contracted, recurring revenue.",
        "criteria": {
            "staff": {"weight": 25, "min": 8, "ideal_min": 15, "ideal_max": 80, "max": 200},
            "revenue": {"weight": 15, "min": 750_000, "ideal_min": 1_500_000, "ideal_max": 10_000_000, "max": 25_000_000},
            "sic": {"weight": 5, "preferred": ["62020", "62030", "62090"]},
            "valuation": {"margin_low": 8.0, "margin_high": 15.0, "multiple_low": 3.0, "multiple_high": 5.0},
            "universe": {"sic_prefixes": ["62020", "62030", "62090", "6190", "95110"],
                         "keyword_sic_prefixes": ["70229", "74909", "82990", "33120"],
                         "name_keywords": ["IT support", "IT services", "IT solutions", "managed services", "networks",
                                           "cyber", "cloud", "computing", "technology", "technologies"],
                         "postcode_areas": [], "min_years": 5},
        },
    },
    "saas": {
        "label": "Software and SaaS",
        "description": "Businesses that own and sell their own software, ideally on subscription.",
        "criteria": {
            "staff": {"weight": 20, "min": 5, "ideal_min": 10, "ideal_max": 60, "max": 150},
            "revenue": {"weight": 15, "min": 500_000, "ideal_min": 1_000_000, "ideal_max": 8_000_000, "max": 20_000_000},
            "sic": {"weight": 5, "preferred": ["58290", "62012", "63110", "63120"]},
            "valuation": {"margin_low": 10.0, "margin_high": 25.0, "multiple_low": 4.0, "multiple_high": 7.0},
            "universe": {"sic_prefixes": ["5829", "62012", "63110", "63120"],
                         "keyword_sic_prefixes": ["62020", "62090", "70229", "74909"],
                         "name_keywords": ["software", "SaaS", "platform", "apps", "systems", "data", "analytics", "cloud"],
                         "postcode_areas": [], "min_years": 3},
        },
    },
    "data": {
        "label": "Data and analytics",
        "description": "Data processing, hosting, analytics and information services.",
        "criteria": {
            "sic": {"weight": 5, "preferred": ["63110", "63120", "63990", "73200"]},
            "universe": {"sic_prefixes": ["631", "63990", "73200"],
                         "keyword_sic_prefixes": ["62020", "62090", "70229", "74909"],
                         "name_keywords": ["data", "analytics", "insight", "intelligence", "research"],
                         "postcode_areas": [], "min_years": 3},
        },
    },
    "fmcg": {
        "label": "FMCG (food, drink and household goods)",
        "description": "Makers and wholesalers of food, drink, toiletries and household products.",
        "criteria": {
            "staff": {"weight": 25, "min": 10, "ideal_min": 20, "ideal_max": 150, "max": 400},
            "revenue": {"weight": 20, "min": 1_000_000, "ideal_min": 3_000_000, "ideal_max": 25_000_000, "max": 60_000_000},
            "sic": {"weight": 5, "preferred": ["10", "11", "2041", "2042"]},
            "valuation": {"margin_low": 5.0, "margin_high": 12.0, "multiple_low": 3.0, "multiple_high": 6.0},
            "manual": [
                {"key": "brand_strength", "label": "Brand strength", "weight": 10, "help": "5 = known brand with loyal buyers"},
                {"key": "customer_spread", "label": "Customer spread", "weight": 10,
                 "help": "5 = no retailer or wholesaler over 10% of revenue"},
                {"key": "owner_openness", "label": "Owner open to selling", "weight": 10,
                 "help": "5 = owner has said they want to sell or retire soon"},
                {"key": "management_depth", "label": "Team beyond the owner", "weight": 5,
                 "help": "5 = runs without the owner day to day"},
            ],
            "exclude": {"keywords": []},
            "universe": {"sic_prefixes": ["10", "11", "2041", "2042", "4631", "4632", "4633", "4634", "4636",
                                          "4637", "4638", "4639", "4644", "4645"],
                         "keyword_sic_prefixes": [], "name_keywords": [], "postcode_areas": [], "min_years": 5},
        },
    },
}


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


UNKNOWN_SHARE = 0.5


def score_company(c: dict, criteria: dict, today: date | None = None, scope=None,
                  parent_of: dict | None = None) -> dict:
    """c holds the company's facts (see load_facts). Returns score dict.
    scope: optional universe test; companies outside it are excluded."""
    today = today or date.today()
    cr = merged(criteria) if "exclude" not in criteria or "staff" not in criteria else criteria
    reasons = []

    def add(key, label, weight, frac, status, text):
        # Unknown is neutral: half the points, so missing data neither helps nor hurts much.
        pts = round(weight * frac, 1) if status != STATUS_UNKNOWN else round(weight * UNKNOWN_SHARE, 1)
        reasons.append({"key": key, "label": label, "points": pts, "max": weight, "status": status, "text": text})

    # exclusions first; the universe before anything else, so a company outside
    # it is always reported (and stored) as outside it
    ex = cr["exclude"]
    exclusion = None
    # Saved buy boxes keep their own list; the current defaults always apply too.
    bad = {x.lower() for x in ex.get("statuses", [])} | set(DEFAULT_CRITERIA["exclude"]["statuses"])
    cstatus = (c.get("status") or "active").lower()
    bad_status = next((b for b in bad if b and b in cstatus), None)
    status_ok = bad_status is None
    children = (parent_of or {}).get(c.get("company_number")) if (cr.get("universe") or {}).get("include_parents", True) else None
    if status_ok and scope is not None and not children and not scope({
            "status": (c.get("status") or "active").lower(), "postcode": c.get("postcode"),
            "inc": c.get("incorporation_date"), "sic": c.get("sic_codes") or [], "name": c.get("name")}):
        exclusion = "Outside your universe (SIC codes, name keywords, area or age)"
    elif not status_ok:
        exclusion = f"Company status is {c['status']}"
    elif c.get("review_tier") and c["review_tier"] in ex.get("tiers", []):
        exclusion = f"Review tier is {c['review_tier']}"
    elif c.get("ownership_type") and c["ownership_type"] in ex.get("ownership", []):
        from .ownership import TYPE_LABELS

        exclusion = f"Ownership: {TYPE_LABELS.get(c['ownership_type'], c['ownership_type']).lower()}"
    elif c.get("address_flag") and c["address_flag"] in ex.get("address_flags", []):
        exclusion = "Registered at an excluded address type"
    elif ex.get("field_service") and c.get("field_service") == "yes":
        exclusion = "Research found field-service or van-based work"
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

    if children:
        names = ", ".join(children[:3]) + (f" and {len(children) - 3} more" if len(children) > 3 else "")
        reasons.insert(0, {"key": "parent", "label": "Parent company", "points": 0.0, "max": 0, "status": STATUS_GOOD,
                           "text": f"Owns {names}, in your universe"})

    # Your own criteria (scored 0-5 by you). Unscored ones are left out of the
    # total, so a company you have not reviewed is neither helped nor hurt.
    manual = c.get("manual") or {}
    for m in cr.get("manual") or []:
        w = float(m.get("weight") or 0)
        if w <= 0:
            continue
        v = manual.get(m["key"])
        label = m.get("label") or m["key"]
        if v is None:
            reasons.append({"key": f"manual:{m['key']}", "label": label, "points": 0.0, "max": w,
                            "status": "unscored", "text": "Not scored by you yet", "manual": True})
        else:
            st = STATUS_GOOD if v >= 4 else STATUS_PART if v >= 2 else STATUS_MISS
            reasons.append({"key": f"manual:{m['key']}", "label": label, "points": round(w * v / 5, 1), "max": w,
                            "status": st, "text": f"You scored {v} out of 5", "manual": True})

    counted = [x for x in reasons if x["status"] != "unscored"]
    total = sum(x["max"] for x in counted)
    got = sum(x["points"] for x in counted)
    auto = [x for x in reasons if not x.get("manual")]
    auto_total = sum(x["max"] for x in auto)
    known = sum(x["max"] for x in auto if x["status"] != STATUS_UNKNOWN)
    return {
        "score": round(100 * got / total, 1) if total else 0.0,
        "coverage": round(100 * known / auto_total, 0) if auto_total else 0.0,
        "excluded": exclusion is not None,
        "exclusion": exclusion,
        "reasons": reasons,
    }


FACTS_SQL = """
with research_text as (
    select company_number, string_agg(content, ' ') as txt from research {rwhere} group by company_number
)
select c.company_number, c.name, c.status, c.review_tier, c.incorporation_date, c.sic_codes,
       c.nature_of_business, c.region, c.address_flag, c.postcode,
       l.employees, l.net_assets, l.operating_profit, l.cash, l.net_assets_prev,
       e.revenue_low, e.revenue_high, e.basis as revenue_basis,
       o.ownership_type, o.flags as ownership_flags, o.oldest_birth_year,
       concat_ws(' ', rt.txt, en.summary, en.business_type) as research_text, en.field_service,
       (select jsonb_object_agg(m.criterion_key, m.value) from manual_score m
         where m.company_number = c.company_number and m.user_id = 1) as manual
from company c
left join company_latest l on l.company_number = c.company_number
left join estimate e on e.company_number = c.company_number
left join company_ownership o on o.company_number = c.company_number
left join research_text rt on rt.company_number = c.company_number
left join enrichment en on en.company_number = c.company_number
{where}
"""


def refresh_latest(conn, company_numbers: list[str] | None = None, from_table: str | None = None):
    """Rebuild company_latest: newest filed figures, prior net assets and
    up to six years of staff numbers per company. Limit it to some companies
    with company_numbers, or to those listed in a temp table (from_table,
    one column: company_number)."""
    if from_table:
        where = f"where company_number in (select company_number from {from_table})"
        fw = f"and company_number in (select company_number from {from_table})"
        params: dict = {}
    else:
        where = "where company_number = any(%(nums)s)" if company_numbers else ""
        params = {"nums": company_numbers} if company_numbers else {}
        fw = "and company_number = any(%(nums)s)" if company_numbers else ""
    conn.execute(f"delete from company_latest {where}", params)
    conn.execute(
        f"""insert into company_latest (company_number, period_end, employees, turnover, operating_profit,
                net_assets, cash, net_assets_prev, staff_trend)
            select company_number, (array_agg(period_end order by period_end desc))[1],
                   (array_agg(employees order by period_end desc))[1],
                   (array_agg(turnover order by period_end desc))[1],
                   (array_agg(operating_profit order by period_end desc))[1],
                   (array_agg(net_assets order by period_end desc))[1],
                   (array_agg(cash order by period_end desc))[1],
                   (array_agg(net_assets order by period_end desc) filter (where net_assets is not null))[2],
                   (array_agg(employees order by period_end) filter (where employees is not null))[greatest(1, count(employees) - 5):]
            from financial_period where not period_inferred {fw}
            group by company_number""",
        params,
    )


_FLOATS = ("net_assets", "net_assets_prev", "revenue_low", "revenue_high", "operating_profit", "cash")


def _fact(r) -> dict:
    r = dict(r)
    for k in _FLOATS:
        if r.get(k) is not None:
            r[k] = float(r[k])
    return r


def load_facts(conn, company_number: str | None = None) -> list[dict]:
    where = "where c.company_number = %s" if company_number else ""
    rwhere = "where company_number = %s" if company_number else ""
    params = (company_number, company_number) if company_number else ()
    return [_fact(r) for r in conn.execute(FACTS_SQL.format(where=where, rwhere=rwhere), params).fetchall()]


def template_criteria(key: str) -> dict:
    """Default criteria with a template's settings layered on top."""
    t = TEMPLATES[key]["criteria"]
    out = json.loads(json.dumps(DEFAULT_CRITERIA))
    for k, v in t.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
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


def rescore(conn, buy_box: dict | None = None, company_number: str | None = None, batch: int = 20_000,
            best: bool = True,
            progress=None) -> int:
    """Score every company (streamed in batches) or one company."""
    from . import valuation

    bb = buy_box or active_buy_box(conn)
    criteria = merged(bb["criteria"])
    va = valuation.assumptions(bb["criteria"])
    scope = scope_test(criteria)
    today = date.today()

    # Companies you are working on always get a score row, wherever they are.
    keep = {r["company_number"] for r in conn.execute(
        """select company_number from user_company where status <> 'new'
           union select company_number from manual_score""")}

    parent_of = parents_in_universe(conn, criteria, company_number)

    def rows_for(facts, store_all=False):
        for f in facts:
            sc = score_company(f, criteria, today, scope, parent_of)
            # Outside the universe and not one you are working on: no row
            # (saves gigabytes across the whole register).
            if not store_all and sc["exclusion"] and sc["exclusion"].startswith("Outside your universe") \
                    and f["company_number"] not in keep:
                continue
            v = valuation.value(f, va)
            yield (bb["id"], f["company_number"], sc["score"], sc["coverage"], sc["excluded"], sc["exclusion"],
                   json.dumps(sc["reasons"]), v["ebitda_low"], v["ebitda_high"], v["value_low"], v["value_high"],
                   v["basis"])

    upsert = """insert into score (buy_box_id, company_number, score, coverage, excluded, exclusion, reasons,
                   ebitda_low, ebitda_high, value_low, value_high, value_basis)
               select * from score_stage
               on conflict (buy_box_id, company_number) do update set score = excluded.score,
                 coverage = excluded.coverage, excluded = excluded.excluded, exclusion = excluded.exclusion,
                 reasons = excluded.reasons, ebitda_low = excluded.ebitda_low, ebitda_high = excluded.ebitda_high,
                 value_low = excluded.value_low, value_high = excluded.value_high, value_basis = excluded.value_basis,
                 computed_at = now()"""
    conn.execute("drop table if exists score_stage")
    conn.execute("""create temp table score_stage (buy_box_id int, company_number text, score numeric, coverage numeric,
                    excluded boolean, exclusion text, reasons jsonb, ebitda_low numeric, ebitda_high numeric,
                    value_low numeric, value_high numeric, value_basis text)""")

    def flush(buf):
        if not buf:
            return
        with conn.cursor().copy("copy score_stage from stdin") as cp:
            for r in buf:
                cp.write_row(r)
        conn.execute(upsert)
        conn.execute("truncate score_stage")

    if company_number:
        refresh_latest(conn, [company_number])
        rows = list(rows_for(load_facts(conn, company_number)))
        conn.execute("delete from score where buy_box_id = %s and company_number = %s", (bb["id"], company_number))
        flush(rows)
        return 1
    # Latest figures are refreshed after loads (accounts, company files), not
    # here, so changing a buy box does not redo that work. Fill them in once
    # if they have never been built.
    if conn.execute("select 1 from company_latest limit 1").fetchone() is None:
        if progress:
            progress("Updating latest figures", 0.02)
        refresh_latest(conn)
    # Let the database pick the candidates: the universe (a slightly wider net
    # than the exact Python test, which still runs) plus companies you are
    # working on. Everything else would be dropped anyway.
    where_sql, wparams = universe_sql(criteria)
    if parent_of:
        where_sql = where_sql[:-1] + " or c.company_number = any(%(u_parents)s))"
        wparams["u_parents"] = list(parent_of)
    total = conn.execute(f"select count(*) as n from company c {where_sql}", wparams).fetchone()["n"] or 1
    conn.execute("delete from score where buy_box_id = %s", (bb["id"],))
    n = 0
    buf: list = []
    with conn.cursor(name="score_facts") as cur:
        cur.itersize = batch
        cur.execute(FACTS_SQL.format(where=where_sql, rwhere=""), wparams)
        for r in cur:
            buf.extend(rows_for([_fact(r)]))
            n += 1
            if len(buf) >= batch:
                flush(buf)
                buf = []
                if progress:
                    progress(f"Scored {n:,} of {total:,} companies", 0.05 + 0.95 * n / total)
    flush(buf)
    conn.execute("update buy_box set scored_at = now() where id = %s", (bb["id"],))
    if best:
        refresh_best(conn, company_number)  # one company's change only touches its own row
    return n


def parents_in_universe(conn, criteria: dict, company_number: str | None = None) -> dict[str, list[str]]:
    """{parent company number: [names of companies it owns that are in the
    universe]}, from the owner (PSC) records. Empty if the option is off."""
    u = (criteria or {}).get("universe") or {}
    if not u.get("include_parents", True):
        return {}
    where_sql, params = universe_sql(criteria, keep=False)
    extra = "and p.registration_number = %(only)s" if company_number else ""
    params["only"] = company_number
    rows = conn.execute(f"""
        select p.registration_number as parent, c.name as child
        from company_person cp
        join person p on p.id = cp.person_id and p.kind = 'corporate' and p.registration_number is not null
        join company c on c.company_number = cp.company_number
        {where_sql} and cp.role = 'psc' and cp.ceased_on is null {extra}""", params).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["parent"], []).append(r["child"])
    return out


def universe_sql(criteria: dict, keep: bool = True) -> tuple[str, dict]:
    """SQL WHERE for the universe, deliberately a little wider than the exact
    test in companies.universe_filter (which is applied afterwards)."""
    u = (criteria or {}).get("universe") or {}
    sic = [p + "%" for p in u.get("sic_prefixes") or []]
    ksic = [p + "%" for p in u.get("keyword_sic_prefixes") or []]
    kws = ["%" + k.lower() + "%" for k in u.get("name_keywords") or []]
    areas = [a.upper() for a in u.get("postcode_areas") or []]
    years = int(u.get("min_years") or 0)
    params: dict = {"u_sic": sic, "u_ksic": ksic, "u_kw": kws, "u_areas": areas}
    match = []
    if sic:
        match.append("exists (select 1 from unnest(c.sic_codes) x where x like any(%(u_sic)s))")
    if kws:
        kw = "lower(c.name) like any(%(u_kw)s)"
        if ksic:
            kw += " and exists (select 1 from unnest(c.sic_codes) x where x like any(%(u_ksic)s))"
        match.append(f"({kw})")
    conds = ["coalesce(c.status, 'active') = 'active'"]
    if match:
        conds.append("(" + " or ".join(match) + ")")
    if areas:
        conds.append("substring(upper(c.postcode) from '^([A-Z]{1,2})[0-9]') = any(%(u_areas)s)")
    if years:
        conds.append(f"(c.incorporation_date is null or c.incorporation_date <= current_date - interval '{years} years')")
    if not keep:
        return f"where ({' and '.join(conds)})", params
    keep_sql = """c.company_number in (select company_number from user_company where status <> 'new'
                                    union select company_number from manual_score)"""
    return f"where (({' and '.join(conds)}) or {keep_sql})", params


def refresh_best(conn, company_number: str | None = None):
    """Rebuild company_best (best score across buy boxes) for all or one company."""
    where = "and s.company_number = %(n)s" if company_number else ""
    if company_number:
        conn.execute("delete from company_best where company_number = %s", (company_number,))
    else:
        # delete, not truncate: truncate locks every reader out of the
        # directory until the whole scoring job commits.
        conn.execute("delete from company_best")
    conn.execute(f"""
        insert into company_best (company_number, buy_box_id, box_name, score, coverage, value_low, value_high,
                                  value_basis, boxes)
        select distinct on (s.company_number) s.company_number, s.buy_box_id, b.name, s.score, s.coverage,
               s.value_low, s.value_high, s.value_basis,
               array(select b2.name from score s2 join buy_box b2 on b2.id = s2.buy_box_id
                     where s2.company_number = s.company_number and not s2.excluded order by s2.score desc)
        from score s join buy_box b on b.id = s.buy_box_id
        where not s.excluded {where}
        order by s.company_number, s.score desc""", {"n": company_number})


def rescore_all(conn, progress=None) -> int:
    """Score every buy box, then rebuild the best-score table."""
    boxes = conn.execute("select * from buy_box where user_id = 1 order by id").fetchall()
    n = 0
    for i, bb in enumerate(boxes):
        def sub(msg, frac=None, i=i):
            if progress:
                progress(f"{bb['name']}: {msg}", None if frac is None else (i + frac) / len(boxes))
        n += rescore(conn, dict(bb), progress=sub, best=False)
    refresh_best(conn)  # once, after every box
    return n


def rescore_company_all_boxes(conn, company_number: str):
    """After a manual score or edit: update this company in every buy box."""
    for bb in conn.execute("select * from buy_box where user_id = 1").fetchall():
        rescore(conn, dict(bb), company_number=company_number, best=False)
    refresh_best(conn, company_number)


def scope_test(criteria: dict):
    """Universe test, built once per rescore (see companies.universe_filter)."""
    from .importers.companies import universe_filter

    return universe_filter(criteria)
