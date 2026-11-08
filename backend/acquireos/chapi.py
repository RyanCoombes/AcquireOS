"""Optional Companies House API (free key) for details the bulk files lack:
charges, filing history, directors and their other companies, shareholders,
insolvency and owner statements.

Fetched per company (on demand, on opening a profile, and by the background
sync in chsync.py) and stored, so the page and Claude can use them. A full
fetch takes 6-15 requests; a light check for changes takes two. Companies
House allows 600 requests per 5 minutes per key: every process shares one
request schedule in the database (ch_rate) to stay inside it.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import date

from . import config, db

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
    auth = base64.b64encode(f"{config.CH_API_KEY}:".encode()).decode()
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    for attempt in range(4):
        _wait()
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 401:
                raise NoKey("Companies House rejected the API key (check CH_API_KEY)") from e
            if e.code == 429 and attempt < 3:  # over the limit: wait for the window to pass
                _backoff(int(e.headers.get("Retry-After") or 0) or 60 * (attempt + 1))
                continue
            raise
    return None


def _d(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


DOC_BASE = "https://document-api.company-information.service.gov.uk"


GAP = 0.55  # seconds between requests: about 545 per 5 minutes, inside the 600 allowed
_rate = {"conn": None}
_rate_lock = threading.Lock()


def _reserve(delay: float) -> float | None:
    """Book the next request slot in the shared schedule; seconds to wait.
    None if the database is not reachable (then pace locally)."""
    with _rate_lock:
        try:
            if _rate["conn"] is None or _rate["conn"].closed:
                _rate["conn"] = db.connect()
                _rate["conn"].autocommit = True
            r = _rate["conn"].execute(
                """update ch_rate set next_at = greatest(next_at, clock_timestamp()) + make_interval(secs => %s)
                   where id = 1 returning extract(epoch from next_at - clock_timestamp()) - %s as wait""",
                (delay, delay)).fetchone()
            return float(r["wait"]) if r else None
        except Exception:
            _rate["conn"] = None
            return None


def _wait():
    wait = _reserve(GAP)
    if wait is None:
        wait = GAP - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def _backoff(seconds: float):
    """Push every process's next request back (after a 429), then wait."""
    _reserve(seconds)
    time.sleep(seconds)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _doc_formats(meta_url: str) -> list[str]:
    """The formats Companies House holds a filing in, e.g. ["application/pdf",
    "application/xhtml+xml"] (the second means machine-readable accounts)."""
    if not enabled():
        raise NoKey("No Companies House API key set (CH_API_KEY)")
    auth = base64.b64encode(f"{config.CH_API_KEY}:".encode()).decode()
    url = meta_url if meta_url.startswith("http") else DOC_BASE + meta_url
    url = url.rstrip("/").removesuffix("/content")
    _wait()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return list((json.loads(r.read()).get("resources") or {}).keys())
    except Exception:
        return []


def _document(meta_url: str, limit: int = 4_000_000, accept: str = "application/pdf") -> bytes | None:
    """A filing's document from the Document API (PDF by default). The content
    URL redirects to a signed storage link, fetched without our credentials."""
    if not enabled():
        raise NoKey("No Companies House API key set (CH_API_KEY)")
    auth = base64.b64encode(f"{config.CH_API_KEY}:".encode()).decode()
    url = meta_url if meta_url.startswith("http") else DOC_BASE + meta_url
    if not url.rstrip("/").endswith("/content"):
        url = url.rstrip("/") + "/content"
    _wait()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": accept})
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
        if (fh.get("total_count") or 0) > 100:  # older filings, for the shareholder list in old annual returns
            more = _get(f"/company/{num}/filing-history?items_per_page=100&start_index=100&category=annual-return") or {}
            fh["items"] = (fh.get("items") or []) + (more.get("items") or [])
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
                fetch_appointments(conn, okey)

    def get_insolvency():
        nonlocal insolvency
        if profile.get("has_insolvency_history") or profile.get("has_been_liquidated"):
            insolvency = (_get(f"/company/{num}/insolvency") or {}).get("cases") or []

    accounts_pdf: list = []
    accounts_added = 0

    def get_accounts():
        """Accounts years missing from the bulk data (filed as PDF, or in a month
        that did not load): read them from the Document API when Companies
        House holds them as data; otherwise note they are PDF only."""
        nonlocal accounts_added
        from .importers.accounts import parse, _upsert

        have = {r["period_end"] for r in conn.execute(
            "select period_end from financial_period where company_number = %s and not period_inferred", (num,))}
        aa = [f for f in filings_raw if (f.get("type") or "").upper() == "AA"
              and (f.get("links") or {}).get("document_metadata")][:5]
        for f in aa:
            mu = _d((f.get("description_values") or {}).get("made_up_date"))
            if not mu or any(abs((mu - h).days) <= 45 for h in have):
                continue
            link = f["links"]["document_metadata"]
            if "application/xhtml+xml" in _doc_formats(link):
                raw = _document(link, limit=20_000_000, accept="application/xhtml+xml")
                data = parse(raw) if raw else {}
                for pe, vals in data.items():
                    _upsert(conn, num, pe, vals, f"api:{f.get('transaction_id')}", balance_date=mu)
                if data:
                    accounts_added += 1
                    have.add(mu)
                    continue
            accounts_pdf.append(str(mu))
        if accounts_added:
            from .importers.companies import refresh_estimates
            from .scoring import refresh_latest

            conn.execute("create temp table if not exists api_touched (company_number text)")
            conn.execute("delete from api_touched")
            conn.execute("insert into api_touched values (%s)", (num,))
            refresh_estimates(conn, from_table="api_touched")
            refresh_latest(conn, [num])

    psc: list = []

    def get_psc():
        nonlocal psc
        res = _get(f"/company/{num}/persons-with-significant-control?items_per_page=100") or {}
        for it in res.get("items") or []:
            dob = it.get("date_of_birth") or {}
            ident = it.get("identification") or {}
            kind = it.get("kind") or ""
            psc.append({"name": it.get("name") or "?", "natures": it.get("natures_of_control") or [],
                        "notified_on": it.get("notified_on"), "ceased_on": it.get("ceased_on"),
                        "kind": "individual" if kind.startswith("individual") else
                                "corporate" if "corporate" in kind else "legal" if "legal" in kind else kind,
                        "birth_year": dob.get("year"), "birth_month": dob.get("month"),
                        "registration_number": ident.get("registration_number"),
                        "country_registered": ident.get("country_registered")})

    def get_statements():
        nonlocal statements
        statements = [{"statement": x.get("statement"), "notified_on": x.get("notified_on"), "ceased_on": x.get("ceased_on")}
                      for x in (_get(f"/company/{num}/persons-with-significant-control-statements") or {}).get("items") or []]

    def get_shareholders():
        nonlocal shareholders_from
        if not people:
            return
        # The newest filing that lists shareholders. Confirmation statements
        # "with no updates" don't list them, so skip those and look further
        # back (annual returns before 2016 always listed them), newest first.
        docs = [f for f in filings_raw if (f.get("type") or "").upper() in ("CS01", "AR01", "IN01")
                and (f.get("links") or {}).get("document_metadata")
                and "no-updates" not in (f.get("description") or "")][:5]
        for f in docs:
            pdf = _document(f["links"]["document_metadata"])
            found = parse_shareholders(_pdf_text(pdf)) if pdf else []
            if found:
                conn.execute("delete from shareholder where company_number = %s", (num,))
                for sh in found:
                    conn.execute(
                        """insert into shareholder (company_number, name, shares, share_class, as_at, source)
                           values (%s, %s, %s, %s, %s, %s) on conflict do nothing""",
                        (num, sh["name"], sh["shares"], sh["share_class"],
                         _d((f.get("description_values") or {}).get("made_up_date") or f.get("date")), f.get("type")))
                counts["shareholders"] = len(found)
                made_up = (f.get("description_values") or {}).get("made_up_date")
                shareholders_from = f"{f.get('type')} made up to {made_up}" if made_up else f"{f.get('type')} filed {f.get('date')}"
                return

    before = _snapshot(conn, num)
    for name, fn in (("profile", get_profile), ("charges", get_charges), ("filings", get_filings),
                     ("accounts", get_accounts),
                     ("officers", get_officers), ("insolvency", get_insolvency), ("owners", get_psc),
                     ("owner statements", get_statements),
                     ("shareholders", get_shareholders)):
        part(name, fn)
    if before:
        after = _snapshot(conn, num)
        if not any(e.startswith("owners:") for e in errors):  # the owners just fetched (not saved yet)
            after["psc"] = {(p["name"].upper(), p.get("notified_on")): p for p in psc}
        changes = _record_changes(conn, num, before, after, profile)
    else:
        changes = 0
    keep = {k: profile.get(k) for k in ("has_charges", "has_insolvency_history", "has_been_liquidated", "can_file",
                                         "date_of_cessation", "jurisdiction", "type", "subtype", "accounts",
                                         "confirmation_statement", "registered_office_is_in_dispute",
                                         "undeliverable_registered_office_address", "sic_codes",
                                         "foreign_company_details", "branch_company_details",
                                         "is_community_interest_company", "has_super_secure_pscs") if k in profile}
    conn.execute(
        """insert into ch_fetch (company_number, fetched_at, checked_at, error, profile, insolvency, psc_statements,
                                 shareholders_from, etag, psc, accounts_pdf)
           values (%s, now(), now(), %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (company_number) do update set fetched_at = now(), checked_at = now(), error = excluded.error,
             profile = excluded.profile, insolvency = excluded.insolvency, psc_statements = excluded.psc_statements,
             shareholders_from = coalesce(excluded.shareholders_from, ch_fetch.shareholders_from),
             etag = coalesce(excluded.etag, ch_fetch.etag),
             psc = case when excluded.psc is null then ch_fetch.psc else excluded.psc end,
             accounts_pdf = excluded.accounts_pdf""",
        (num, "; ".join(errors) or None, json.dumps(keep), json.dumps(insolvency), json.dumps(statements), shareholders_from,
         profile.get("etag"), None if any(e.startswith("owners:") for e in errors) else json.dumps(psc),
         json.dumps(accounts_pdf)))
    try:  # PSC exemptions and UK establishments (a request each, only where they apply)
        from . import chextras
        chextras.company_extras(conn, num, profile, psc)
    except Exception as e:
        errors.append(f"extras: {str(e)[:120]}")
    if accounts_added and before:
        conn.execute("""insert into company_change (company_number, kind, field, new_value, source)
                        values (%s, 'accounts', 'period_end', %s, 'api')""",
                     (num, str(max(r["period_end"] for r in conn.execute(
                         "select period_end from financial_period where company_number = %s and not period_inferred",
                         (num,)).fetchall()))))
    return {**counts, "accounts_added": accounts_added, "changes": changes, "error": "; ".join(errors) or None}


def check(conn, company_number: str) -> dict:
    """A light check for changes (two requests: the profile and the newest
    filings). Does a full fetch if anything is new, or if the company has
    never been fetched. {changed, full, changes}."""
    num = company_number.strip().upper()
    prev = conn.execute("select etag from ch_fetch where company_number = %s", (num,)).fetchone()
    if not prev:
        return {"changed": False, "full": True, **fetch(conn, num)}
    profile = _get(f"/company/{num}") or {}
    fh = _get(f"/company/{num}/filing-history?items_per_page=25") or {}
    ids = [it["transaction_id"] for it in fh.get("items") or [] if it.get("transaction_id")]
    known = {r["transaction_id"] for r in conn.execute(
        "select transaction_id from filing where company_number = %s and transaction_id = any(%s)", (num, ids))}
    # Accounts Companies House has that we don't (filed as PDF, or in a bulk
    # month that did not load), and not already known to be PDF only.
    gap = conn.execute(
        """select 1 from company c left join ch_fetch f on f.company_number = c.company_number
           where c.company_number = %s and c.last_accounts_date is not null
             and not exists (select 1 from financial_period fp where fp.company_number = c.company_number
                             and not fp.period_inferred and abs(fp.period_end - c.last_accounts_date) <= 45)
             and not coalesce(f.accounts_pdf, '[]'::jsonb) ? c.last_accounts_date::text""", (num,)).fetchone()
    if gap or any(i not in known for i in ids) or (profile.get("etag") or prev["etag"]) != prev["etag"]:
        r = fetch(conn, num)
        return {"changed": True, "full": True, **r}
    conn.execute("update ch_fetch set checked_at = now() where company_number = %s", (num,))
    return {"changed": False, "full": False, "changes": 0}


# Filing categories whose changes are recorded in more detail elsewhere
# (directors, charges), so a new filing in them is not listed twice.
_COVERED = {"officers", "mortgage"}


def _snapshot(conn, num: str) -> dict | None:
    """What we hold for a company, to compare after a fetch. None if never fetched."""
    f = conn.execute("select profile from ch_fetch where company_number = %s", (num,)).fetchone()
    if not f:
        return None
    return {
        "profile": f["profile"] or {},
        "filings": {r["transaction_id"]: r for r in conn.execute(
            "select transaction_id, filed_on, type, category, description from filing where company_number = %s", (num,))},
        "charges": {r["charge_id"]: r for r in conn.execute(
            "select charge_id, status, holders from charge where company_number = %s", (num,))},
        "officers": {(r["officer_key"], r["role"]): r for r in conn.execute(
            "select officer_key, role, name, resigned_on from officer where company_number = %s", (num,))},
        "shareholders": {(r["name"].upper(), r["share_class"]): float(r["shares"] or 0) for r in conn.execute(
            "select name, share_class, shares from shareholder where company_number = %s", (num,))},
        "psc": {(p["name"].upper(), p.get("notified_on")): p for p in (conn.execute(
            "select psc from ch_fetch where company_number = %s", (num,)).fetchone()["psc"] or [])},
    }


def _shareholder_diff(a: dict, b: dict) -> str | None:
    """Who gained, lost, joined or left, in % of all shares, e.g.
    "Alex Smith 60% → 50%; new: DBW Investments 10%; left: Sam Jones (was 25%)"."""
    def pcts(d):
        total = sum(d.values()) or 1
        out: dict[str, float] = {}
        for (name, _cls), v in d.items():
            out[name] = out.get(name, 0) + 100 * v / total
        return out
    pa, pb = pcts(a), pcts(b)
    bits = []
    for name in sorted(set(pa) | set(pb), key=lambda n: -max(pa.get(n, 0), pb.get(n, 0))):
        x, y = pa.get(name, 0), pb.get(name, 0)
        nice = name.title()
        if not x:
            bits.append(f"new: {nice} {round(y)}%")
        elif not y:
            bits.append(f"left: {nice} (was {round(x)}%)")
        elif abs(x - y) >= 0.5:
            bits.append(f"{nice} {round(x)}% → {round(y)}%")
    return "; ".join(bits[:6]) + (f"; and {len(bits) - 6} more" if len(bits) > 6 else "") if bits else None


def _record_changes(conn, num: str, a: dict, b: dict, profile: dict) -> int:
    """Store what changed between two snapshots as company_change rows
    (source 'api'), so they show on the Changes page and as alerts."""
    rows: list[tuple] = []
    # What a confirmation statement changed: shareholders (from the statement
    # itself) and industry codes (from the profile).
    sh_text = _shareholder_diff(a["shareholders"], b["shareholders"]) if a["shareholders"] and b["shareholders"] else None
    sic_a, sic_b = (a["profile"] or {}).get("sic_codes"), (profile or {}).get("sic_codes")
    sic_changed = bool(sic_a and sic_b and sorted(sic_a) != sorted(sic_b))
    for tid, f in b["filings"].items():
        if tid not in a["filings"] and (f["category"] or "") not in _COVERED:
            desc = f["description"] or ""
            if (f["type"] or "").upper() == "CS01" and "with-updates" in desc:
                parts = [f"shareholders: {sh_text}" if sh_text else None,
                         "industry codes changed" if sic_changed else None]
                parts = [x for x in parts if x]
                desc += "::" + ("; ".join(parts) if parts else
                                "no change to shareholders or industry codes (other details, e.g. share capital or contact details)")
            rows.append(("filing", f["type"], str(f["filed_on"] or ""), desc))
    if sic_changed:
        rows.append(("sic", "sic_codes", ", ".join(sic_a), ", ".join(sic_b)))
    for key, o in b["officers"].items():
        was = a["officers"].get(key)
        if not was and not o["resigned_on"]:
            rows.append(("director", "Appointed", None, f"{o['name']} ({(o['role'] or '').replace('-', ' ')})"))
        elif was and not was["resigned_on"] and o["resigned_on"]:
            rows.append(("director", "Resigned", None, f"{o['name']} ({(o['role'] or '').replace('-', ' ')})"))
    for cid, c in b["charges"].items():
        was = a["charges"].get(cid)
        holders = ", ".join(c["holders"] or []) or "lender not named"
        if not was:
            rows.append(("charge", "New charge", None, holders))
        elif was["status"] != c["status"] and c["status"] in ("fully-satisfied", "part-satisfied"):
            rows.append(("charge", "Repaid" if c["status"] == "fully-satisfied" else "Part repaid", was["status"], holders))
    if sh_text:
        rows.append(("shareholders", "Shareholders", None, sh_text))
    if a.get("psc"):  # owners register changes (skipped the first time owners are fetched)
        for key, p in b.get("psc", {}).items():
            was = a["psc"].get(key)
            if not was and not p.get("ceased_on"):
                rows.append(("owner", "Owner added", None, p["name"]))
            elif was and not was.get("ceased_on") and p.get("ceased_on"):
                rows.append(("owner", "Owner left", None, p["name"]))
    for flag, text in (("has_insolvency_history", "Insolvency case recorded"), ("has_been_liquidated", "Liquidated")):
        if profile.get(flag) and not a["profile"].get(flag):
            rows.append(("insolvency", flag, None, text))
    for kind, field, old, new in rows:
        conn.execute(
            """insert into company_change (company_number, kind, field, old_value, new_value, source)
               values (%s, %s, %s, %s, %s, 'api')""", (num, kind, field, old, new))
    return len(rows)


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
            "late_filings": _late_filings(filings), "signals": signals(conn, num, charges, filings, shareholders),
            "disqualified": _disq(conn, num), "exemptions": (fetched or {}).get("exemptions") or []}


def _disq(conn, num: str) -> list[dict]:
    try:
        from . import chextras
        return chextras.disqualified_for(conn, num)
    except Exception:  # before the migration
        return []


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


def accounts_pdf_text(conn, company_number: str, made_up: str | None = None) -> dict:
    """The text of a set of accounts filed as PDF (for Claude to read), the
    newest by default. Scanned paper filings have no text: says so."""
    num = company_number.strip().upper()
    rows = conn.execute(
        """select transaction_id, filed_on, detail from filing where company_number = %s and type = 'AA'
           order by filed_on desc""", (num,)).fetchall()
    if not rows:
        return {"error": "No accounts filings on file: fetch the company from Companies House first"}
    pick = next((r for r in rows if not made_up or (r["detail"] or {}).get("made_up_date") == made_up), None)
    if not pick or not (pick["detail"] or {}).get("document"):
        return {"error": f"No accounts made up to {made_up} with a document"}
    pdf = _document(pick["detail"]["document"], limit=25_000_000)
    if not pdf:
        return {"error": "Companies House did not return the document"}
    from pypdf import PdfReader
    import io

    try:
        reader = PdfReader(io.BytesIO(pdf))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:60])
        pages = len(reader.pages)
    except Exception as e:
        return {"error": f"Could not read the PDF: {e}"}
    link = f"https://find-and-update.company-information.service.gov.uk/company/{num}/filing-history"
    made = (pick["detail"] or {}).get("made_up_date")
    if len(text.strip()) < 200:
        return {"made_up_to": made, "pages": pages, "text": None, "scanned": True, "filing_history": link,
                "note": "This is a scanned paper filing with no text layer. Open it from the filing history and read the figures from the images."}
    return {"made_up_to": made, "pages": pages, "scanned": False, "text": text[:80_000], "filing_history": link}


def fetch_appointments(conn, officer_key: str) -> int:
    """Every company a director (Companies House officer id) is or was
    appointed to, stored in officer_appointment. Returns how many."""
    ap = _get(f"/officers/{officer_key}/appointments?items_per_page=50") or {}
    conn.execute("delete from officer_appointment where officer_key = %s", (officer_key,))
    n = 0
    for a in ap.get("items") or []:
        to = a.get("appointed_to") or {}
        if not to.get("company_number"):
            continue
        conn.execute(
            """insert into officer_appointment (officer_key, company_number, company_name, company_status, role,
                                                appointed_on, resigned_on)
               values (%s, %s, %s, %s, %s, %s, %s) on conflict do nothing""",
            (officer_key, to["company_number"].upper(), to.get("company_name"), to.get("company_status"),
             a.get("officer_role"), _d(a.get("appointed_on")), _d(a.get("resigned_on"))))
        n += 1
    return n
