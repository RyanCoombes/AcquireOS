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
    _wait()
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


DOC_BASE = "https://document-api.company-information.service.gov.uk"


def _wait():
    wait = 0.55 - (time.time() - _last[0])  # stay well inside 600 per 5 minutes
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _document(meta_url: str, limit: int = 4_000_000) -> bytes | None:
    """A filing's PDF from the Document API. The content URL redirects to a
    signed storage link, which must be fetched without our credentials."""
    if not enabled():
        raise NoKey("No Companies House API key set (CH_API_KEY)")
    auth = base64.b64encode(f"{config.CH_API_KEY}:".encode()).decode()
    url = meta_url if meta_url.startswith("http") else DOC_BASE + meta_url
    if not url.rstrip("/").endswith("/content"):
        url = url.rstrip("/") + "/content"
    _wait()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": "application/pdf"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=30) as r:
            return r.read(limit)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            with urllib.request.urlopen(e.headers["Location"], timeout=30) as r2:
                return r2.read(limit)
        return None


_SHAREHOLDING = re.compile(
    r"Shareholding\s*\d+\s*:\s*([\d,]+)\s+(.{1,60}?)\s+shares?\s+held\s+as\s+at\s+the\s+date[^\n]*?"
    r"(?:\n|\s)+Name\s*:\s*(.+?)(?:\n|$)", re.I | re.S)


def parse_shareholders(text: str) -> list[dict]:
    """Shareholders from a confirmation statement's text (electronically
    filed ones list "Shareholding 1: 100 ORDINARY shares held ... Name: X")."""
    out, seen = [], set()
    for m in _SHAREHOLDING.finditer(text):
        name = " ".join(m.group(3).split()).strip(" .")
        cls = " ".join(m.group(2).split()).upper()
        key = (name.upper(), cls)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "shares": float(m.group(1).replace(",", "")), "share_class": cls})
    return out


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    try:
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages[:30])
    except Exception:
        return ""


def fetch(conn, company_number: str, people: bool = True) -> dict:
    """Fetch and store what the API adds for one company: its profile flags,
    charges, filing history, directors (and their other companies),
    shareholders from the latest confirmation statement that lists them,
    insolvency cases and owner statements. Each part is kept separately, so a
    failure in one leaves the others."""
    num = company_number.strip().upper()
    errors: list[str] = []
    counts = {"charges": 0, "filings": 0, "officers": 0, "shareholders": 0}
    profile: dict = {}
    insolvency: list = []
    statements: list = []
    shareholders_from = None

    def part(name, fn):
        try:
            fn()
        except NoKey:
            raise
        except Exception as e:  # network or Companies House trouble: keep what we had
            errors.append(f"{name}: {str(e)[:120]}")

    def get_profile():
        nonlocal profile
        profile = _get(f"/company/{num}") or {}

    def get_charges():
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
            counts["charges"] += 1

    filings_raw: list = []

    def get_filings():
        fh = _get(f"/company/{num}/filing-history?items_per_page=100") or {}
        conn.execute("delete from filing where company_number = %s", (num,))
        for it in fh.get("items") or []:
            filings_raw.append(it)
            detail = dict(it.get("description_values") or {})
            doc = (it.get("links") or {}).get("document_metadata")
            if doc:
                detail["document"] = doc
            conn.execute(
                """insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                   values (%s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
                (num, it.get("transaction_id") or f"{it.get('date')}-{it.get('type')}", _d(it.get("date")), it.get("type"),
                 it.get("category"), it.get("description"), json.dumps(detail)))
            counts["filings"] += 1

    def get_officers():
        res = _get(f"/company/{num}/officers?items_per_page=100") or {}
        conn.execute("delete from officer where company_number = %s", (num,))
        current = []
        for it in res.get("items") or []:
            key = ((it.get("links") or {}).get("officer") or {}).get("appointments", "").strip("/").split("/")
            okey = key[1] if len(key) >= 2 else it.get("name", "")
            dob = it.get("date_of_birth") or {}
            conn.execute(
                """insert into officer (company_number, officer_key, name, role, appointed_on, resigned_on, birth_year,
                                        birth_month, occupation, nationality, residence)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
                (num, okey, it.get("name") or "?", it.get("officer_role"), _d(it.get("appointed_on")), _d(it.get("resigned_on")),
                 dob.get("year"), dob.get("month"), it.get("occupation"), it.get("nationality"), it.get("country_of_residence")))
            counts["officers"] += 1
            if not it.get("resigned_on") and "director" in (it.get("officer_role") or "") and len(key) >= 2:
                current.append(okey)
        if people:
            for okey in current[:6]:  # each current director's other companies
                ap = _get(f"/officers/{okey}/appointments?items_per_page=50") or {}
                conn.execute("delete from officer_appointment where officer_key = %s", (okey,))
                for a in ap.get("items") or []:
                    to = a.get("appointed_to") or {}
                    if not to.get("company_number"):
                        continue
                    conn.execute(
                        """insert into officer_appointment (officer_key, company_number, company_name, company_status, role,
                                                            appointed_on, resigned_on)
                           values (%s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
                        (okey, to["company_number"].upper(), to.get("company_name"), to.get("company_status"),
                         a.get("officer_role"), _d(a.get("appointed_on")), _d(a.get("resigned_on"))))

    def get_insolvency():
        nonlocal insolvency
        if profile.get("has_insolvency_history") or profile.get("has_been_liquidated"):
            insolvency = (_get(f"/company/{num}/insolvency") or {}).get("cases") or []

    def get_statements():
        nonlocal statements
        statements = [{"statement": x.get("statement"), "notified_on": x.get("notified_on"), "ceased_on": x.get("ceased_on")}
                      for x in (_get(f"/company/{num}/persons-with-significant-control-statements") or {}).get("items") or []]

    def get_shareholders():
        nonlocal shareholders_from
        if not people:
            return
        # Newest confirmation statements (or the incorporation form) first;
        # many say "no change", so look back a few for one that lists people.
        docs = [f for f in filings_raw if (f.get("type") or "").upper() in ("CS01", "AR01", "IN01")
                and (f.get("links") or {}).get("document_metadata")][:4]
        for f in docs:
            pdf = _document(f["links"]["document_metadata"])
            found = parse_shareholders(_pdf_text(pdf)) if pdf else []
            if found:
                conn.execute("delete from shareholder where company_number = %s", (num,))
                for sh in found:
                    conn.execute(
                        """insert into shareholder (company_number, name, shares, share_class, as_at, source)
                           values (%s, %s, %s, %s, %s, %s) on conflict do nothing""",
                        (num, sh["name"], sh["shares"], sh["share_class"], _d(f.get("date")), f.get("type")))
                counts["shareholders"] = len(found)
                shareholders_from = f"{f.get('type')} filed {f.get('date')}"
                return

    for name, fn in (("profile", get_profile), ("charges", get_charges), ("filings", get_filings),
                     ("officers", get_officers), ("insolvency", get_insolvency), ("owner statements", get_statements),
                     ("shareholders", get_shareholders)):
        part(name, fn)
    keep = {k: profile.get(k) for k in ("has_charges", "has_insolvency_history", "has_been_liquidated", "can_file",
                                         "date_of_cessation", "jurisdiction", "type", "subtype", "accounts",
                                         "confirmation_statement", "registered_office_is_in_dispute",
                                         "undeliverable_registered_office_address") if k in profile}
    conn.execute(
        """insert into ch_fetch (company_number, fetched_at, error, profile, insolvency, psc_statements, shareholders_from)
           values (%s, now(), %s, %s, %s, %s, %s)
           on conflict (company_number) do update set fetched_at = now(), error = excluded.error, profile = excluded.profile,
             insolvency = excluded.insolvency, psc_statements = excluded.psc_statements,
             shareholders_from = coalesce(excluded.shareholders_from, ch_fetch.shareholders_from)""",
        (num, "; ".join(errors) or None, json.dumps(keep), json.dumps(insolvency), json.dumps(statements), shareholders_from))
    return {**counts, "error": "; ".join(errors) or None}


def _late_filings(filings: list) -> list[dict]:
    """Accounts filed after their due date (nine months after the year end
    for private companies), from the filing history."""
    out = []
    for f in filings:
        if (f["type"] or "").upper() not in ("AA",) or not f["filed_on"]:
            continue
        made_up = (f["detail"] or {}).get("made_up_date")
        try:
            mu = date.fromisoformat(made_up)
        except (TypeError, ValueError):
            continue
        due = date(mu.year + (1 if mu.month > 3 else 0), (mu.month + 9 - 1) % 12 + 1, 1)
        if f["filed_on"] > due.replace(day=28) and (f["filed_on"] - mu).days > 300:
            out.append({"made_up_to": mu, "filed_on": f["filed_on"], "days_late": (f["filed_on"] - mu).days - 274})
    return out


def details(conn, company_number: str) -> dict:
    """Everything stored from the API for the company page and Claude."""
    num = company_number.strip().upper()
    charges = conn.execute(
        "select * from charge where company_number = %s order by (status = 'outstanding') desc, created_on desc nulls last",
        (num,)).fetchall()
    filings = conn.execute(
        "select * from filing where company_number = %s order by filed_on desc nulls last", (num,)).fetchall()
    fetched = conn.execute("select * from ch_fetch where company_number = %s", (num,)).fetchone()
    officers = conn.execute(
        """select o.*, (select count(*) from officer_appointment a where a.officer_key = o.officer_key
                         and a.company_number <> o.company_number and a.resigned_on is null) as other_current,
                  (select count(*) from officer_appointment a where a.officer_key = o.officer_key
                         and a.company_number <> o.company_number) as other_total
           from officer o where o.company_number = %s
           order by o.resigned_on is not null, o.role, o.appointed_on""", (num,)).fetchall()
    other = conn.execute(
        """select a.*, o.name as officer_name, c.name as name_on_register, cb.score
           from officer o join officer_appointment a on a.officer_key = o.officer_key and a.company_number <> o.company_number
           left join company c on c.company_number = a.company_number
           left join company_best cb on cb.company_number = a.company_number
           where o.company_number = %s and o.resigned_on is null
           order by a.resigned_on is not null, a.appointed_on desc nulls last""", (num,)).fetchall()
    shareholders = conn.execute(
        "select * from shareholder where company_number = %s order by shares desc nulls last", (num,)).fetchall()
    total_shares = sum(float(s["shares"] or 0) for s in shareholders) or None
    for s in shareholders:
        s["pct"] = round(100 * float(s["shares"] or 0) / total_shares, 1) if total_shares else None
    return {"enabled": enabled(), "fetched": fetched, "charges": charges, "filings": filings,
            "officers": officers, "other_appointments": other, "shareholders": shareholders,
            "late_filings": _late_filings(filings), "signals": signals(conn, num, charges, filings, shareholders)}


def signals(conn, num: str, charges=None, filings=None, shareholders=None) -> list[dict]:
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
    for sh in shareholders or []:
        if is_investor(sh["name"]):
            out.append({"kind": "shareholder", "strength": "strong", "date": sh["as_at"],
                        "text": f"{sh['name']} holds {sh.get('pct') or '?'}% of the shares"})
    order = {"strong": 0, "possible": 1}
    out.sort(key=lambda s: (order[s["strength"]], str(s["date"] or "")), reverse=False)
    return out
