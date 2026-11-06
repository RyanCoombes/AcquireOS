"""Optional Companies House API (free key) for details the bulk files lack:
charges (who has lent against the company's assets) and filing history
(new share issues, a common sign of outside investment).

Fetched per company on demand and stored, so the page and Claude can use
them. Companies House allows 600 requests per 5 minutes per key; a company
takes two or three.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date

from . import config

BASE = "https://api.company-information.service.gov.uk"
_last = [0.0]

# Names that suggest a professional investor or investment lender (as a
# charge holder, owner or shareholder). Word-bounded; checked case-insensitively.
LENDER_RE = re.compile(r"\b(bank|barclays|lloyds|natwest|hsbc|santander|metro|tsb|clydesdale|virgin money|"
                       r"close brothers|shawbrook|aldermore|allica|investec|funding circle|iwoca|"
                       r"bibby|ultimate finance|leumi|hsbc invoice)\b", re.I)


# Named development-finance and growth investors: always count.
NAMED_INVESTOR_RE = re.compile(
    r"\b(development bank of wales|banc datblygu|dbw investments|british business (bank|investments)|bgf|"
    r"business growth fund|foresight|maven capital|mercia|yfm|ingenious|northern powerhouse investment|"
    r"midlands engine investment|scottish enterprise|scottish national investment|invest ni|"
    r"finance wales|fw capital|nviews|mmc ventures|octopus ventures|ldc)\b", re.I)
# Generic investor words: count unless the name is also a bank or lender.
INVESTOR_RE = re.compile(
    r"\b(ventures?|venture capital|private equity|capital partners|equity partners|investments? (fund|llp|lp)|"
    r"fund (lp|gp|nominees?)|nominees? limited|growth fund|gp limited|limited partnership|llp)\b", re.I)


def is_investor(name: str) -> bool:
    return bool(NAMED_INVESTOR_RE.search(name or "")) or (
        bool(INVESTOR_RE.search(name or "")) and not LENDER_RE.search(name or ""))


class NoKey(Exception):
    pass


def enabled() -> bool:
    return bool(config.CH_API_KEY)


def _get(path: str) -> dict | None:
    if not enabled():
        raise NoKey("No Companies House API key set (CH_API_KEY)")
    wait = 0.55 - (time.time() - _last[0])  # stay well inside 600 per 5 minutes
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    auth = base64.b64encode(f"{config.CH_API_KEY}:".encode()).decode()
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 401:
            raise NoKey("Companies House rejected the API key (check CH_API_KEY)") from e
        raise


def _d(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def fetch(conn, company_number: str) -> dict:
    """Fetch and store charges and capital filings for one company."""
    num = company_number.strip().upper()
    error = None
    n_charges = n_filings = 0
    try:
        ch = _get(f"/company/{num}/charges?items_per_page=100") or {}
        conn.execute("delete from charge where company_number = %s", (num,))
        for it in ch.get("items") or []:
            cid = it.get("charge_code") or it.get("charge_number") or (it.get("links") or {}).get("self", "").rsplit("/", 1)[-1]
            holders = [p.get("name") for p in it.get("persons_entitled") or [] if p.get("name")]
            conn.execute(
                """insert into charge (company_number, charge_id, status, classification, holders, created_on, delivered_on,
                                       satisfied_on, particulars)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
                (num, str(cid), it.get("status"), (it.get("classification") or {}).get("description"), holders,
                 _d(it.get("created_on")), _d(it.get("delivered_on")), _d(it.get("satisfied_on")),
                 (it.get("particulars") or {}).get("description")))
            n_charges += 1
        fh = _get(f"/company/{num}/filing-history?category=capital,incorporation,resolution&items_per_page=100") or {}
        conn.execute("delete from filing where company_number = %s", (num,))
        for it in fh.get("items") or []:
            conn.execute(
                """insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                   values (%s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
                (num, it.get("transaction_id") or f"{it.get('date')}-{it.get('type')}", _d(it.get("date")), it.get("type"),
                 it.get("category"), it.get("description"), json.dumps(it.get("description_values") or {})))
            n_filings += 1
    except NoKey:
        raise
    except Exception as e:  # network or Companies House trouble: keep what we had
        error = str(e)[:300]
    conn.execute("""insert into ch_fetch (company_number, fetched_at, error) values (%s, now(), %s)
                    on conflict (company_number) do update set fetched_at = now(), error = excluded.error""", (num, error))
    return {"charges": n_charges, "filings": n_filings, "error": error}


def details(conn, company_number: str) -> dict:
    """Stored charges, capital filings and investment signals for the company page."""
    num = company_number.strip().upper()
    charges = conn.execute(
        "select * from charge where company_number = %s order by (status = 'outstanding') desc, created_on desc nulls last",
        (num,)).fetchall()
    filings = conn.execute(
        "select * from filing where company_number = %s order by filed_on desc nulls last", (num,)).fetchall()
    fetched = conn.execute("select fetched_at, error from ch_fetch where company_number = %s", (num,)).fetchone()
    return {"enabled": enabled(), "fetched": fetched, "charges": charges, "filings": filings,
            "signals": signals(conn, num, charges, filings)}


def signals(conn, num: str, charges=None, filings=None) -> list[dict]:
    """Evidence that the company has outside investment, strongest first.
    Each: {kind, strength (strong|possible), text, date}."""
    out = []
    owners = conn.execute(
        """select p.name, p.kind, cp.notified_on from company_person cp join person p on p.id = cp.person_id
           where cp.company_number = %s and cp.ceased_on is null and p.kind <> 'individual'""", (num,)).fetchall()
    for o in owners:
        if is_investor(o["name"]):
            out.append({"kind": "owner", "strength": "strong", "date": o["notified_on"],
                        "text": f"{o['name']} is a registered owner (person with significant control)"})
    for c in charges or []:
        for h in c["holders"] or []:
            if is_investor(h):
                out.append({"kind": "charge", "strength": "strong", "date": c["created_on"],
                            "text": f"Charge to {h} ({c['status'] or 'status unknown'}): investors often lend alongside equity"})
    allot = [f for f in filings or [] if (f["type"] or "").upper() in ("SH01", "SH02", "SH08", "SH10")
             or "allotment" in (f["description"] or "")]
    for f in allot[:6]:
        detail = f["detail"] or {}
        caps = detail.get("capital") or []
        figure = ", ".join(f"{c.get('currency', '')} {c.get('figure', '')}".strip() for c in caps if isinstance(c, dict))
        out.append({"kind": "allotment", "strength": "possible", "date": f["filed_on"],
                    "text": "New shares issued" + (f" (share capital now {figure})" if figure else "")
                            + ": often an investment round, sometimes staff or founder shares"})
    for f in filings or []:
        if (f["type"] or "").upper() in ("RES01", "RESOLUTIONS") and "articles" in (f["description"] or "").lower():
            out.append({"kind": "articles", "strength": "possible", "date": f["filed_on"],
                        "text": "New articles of association adopted: common when investors come in"})
            break
    order = {"strong": 0, "possible": 1}
    out.sort(key=lambda s: (order[s["strength"]], str(s["date"] or "")), reverse=False)
    return out
