"""Enrichment and data auditing: shared by the MCP server and the REST API.

Rules that keep enrichment trustworthy:
- Every saved fact needs a source URL (or "manual" when you typed it in).
- Enrichment never touches your notes, statuses or ratings.
- Each save also writes a dated, sourced row to research, so the history of
  what was found, and where, is kept even when a field is later updated.
"""
from __future__ import annotations

import json
import re

from . import scoring

BUSINESS_TYPES = ["software", "saas", "data", "msp", "it_consultancy", "field_service", "agency", "reseller", "other"]
TRISTATE = ["yes", "partly", "no", "unknown"]
CONFIDENCE = ["high", "medium", "low"]

AUDIT_CHECKS = {
    "missing_website": "No website recorded",
    "no_research": "Nothing researched yet",
    "ownership_unknown": "Owners not traced",
    "estimate_only": "No filed turnover; revenue is an estimate",
    "field_service_unknown": "Not yet checked for field-service work",
    "stale": "Enrichment older than 12 months",
    "address_flag": "Registered at a default, agent or shared address",
    "sic_mismatch": "Name suggests tech but SIC code does not (or the reverse)",
}

TECH_WORDS = re.compile(r"\b(software|digital|data|computing|systems|technolog\w*|cloud|cyber|networks?|IT)\b", re.I)
TECH_SIC = ("582", "62", "631")


class EnrichError(ValueError):
    pass


LOCATION_KINDS = ["head office", "office", "branch", "site", "warehouse", "registered office"]
_PC = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)


def _clean_locations(locations: list) -> list[dict]:
    out = []
    for loc in locations or []:
        if isinstance(loc, str):
            loc = {"address": loc}
        if not isinstance(loc, dict):
            raise EnrichError("Each location is {name?, address, postcode?, kind?}")
        address = " ".join(str(loc.get("address") or "").split())
        name = " ".join(str(loc.get("name") or "").split()) or None
        if not address and not name:
            raise EnrichError("A location needs an address or a name")
        kind = (loc.get("kind") or "office").strip().lower()
        if kind not in LOCATION_KINDS:
            raise EnrichError(f"location kind must be one of {LOCATION_KINDS}")
        pc = (loc.get("postcode") or "").strip().upper() or None
        if not pc:
            m = _PC.search(address)
            pc = f"{m.group(1).upper()} {m.group(2).upper()}" if m else None
        out.append({"name": name, "address": address or None, "postcode": pc, "kind": kind})
    return out


def _clean_facts(facts: list, source_url: str) -> list[dict]:
    out = []
    for f in facts or []:
        if not isinstance(f, dict) or not str(f.get("label") or "").strip() or f.get("value") in (None, ""):
            raise EnrichError("Each fact is {label, value, source_url?}")
        src = (f.get("source_url") or source_url or "").strip()
        out.append({"label": str(f["label"]).strip(), "value": str(f["value"]).strip(),
                    "source_url": None if src in ("", "manual") else src})
    return out


def _clean_links(links: list) -> list[dict]:
    out = []
    for x in links or []:
        if not isinstance(x, dict) or not re.match(r"^https?://", str(x.get("url") or "").strip()) or not str(x.get("title") or "").strip():
            raise EnrichError("Each link is {title, url (http/https), date?, kind?: news|data|other}")
        out.append({"title": str(x["title"]).strip()[:200], "url": str(x["url"]).strip(),
                    "date": (str(x.get("date")).strip()[:10] or None) if x.get("date") else None,
                    "kind": x.get("kind") if x.get("kind") in ("news", "data", "other") else "news"})
    return out


def _clean_deals(deals: list, source_url: str) -> list[dict]:
    from .deals import KINDS

    out = []
    for d in deals or []:
        if not isinstance(d, dict) or not str(d.get("title") or "").strip() or not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(d.get("date") or "")):
            raise EnrichError("Each deal is {date (YYYY, YYYY-MM or YYYY-MM-DD), kind, title, counterparty?, value?, note?, source_url}")
        src = (d.get("source_url") or source_url or "").strip()
        out.append({"date": str(d["date"]), "kind": d.get("kind") if d.get("kind") in KINDS else "other",
                    "title": str(d["title"]).strip()[:200], "counterparty": (str(d.get("counterparty")).strip()[:200] or None) if d.get("counterparty") else None,
                    "value": (str(d.get("value")).strip()[:80] or None) if d.get("value") else None,
                    "note": (str(d.get("note")).strip()[:300] or None) if d.get("note") else None,
                    "source_url": None if src in ("", "manual") else src})
    return out


SUMMARY_MAX = 320


def short_summary(text: str) -> str:
    """What it does, in a sentence or two: the first sentences of the first
    paragraph, without a heading like "WHAT IT DOES:"."""
    first = next((p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z][A-Z /&()-]{3,}:)", text.strip()) if p.strip()), "")
    first = re.sub(r"^[A-Z][A-Z /&()-]{2,}:\s*", "", first).replace("\n", " ")
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", first)
    out = ""
    for sn in sents:
        if out and len(out) + len(sn) + 1 > SUMMARY_MAX:
            break
        out = f"{out} {sn}".strip()
        if len(out) >= 140:
            break
    return out if len(out) <= SUMMARY_MAX + 80 else out[:SUMMARY_MAX].rsplit(" ", 1)[0] + "…"


def save_enrichment(conn, company_number: str, *, source_url: str, website: str | None = None,
                    business_type: str | None = None, recurring_revenue: str | None = None,
                    field_service: str | None = None, summary: str | None = None,
                    confidence: str = "medium", source_label: str | None = None, by: str = "claude",
                    locations: list | None = None, facts: list | None = None, linkedin: str | None = None,
                    phone: str | None = None, sources: list | None = None, ownership: str | None = None,
                    ownership_note: str | None = None, links: list | None = None, deals: list | None = None) -> dict:
    num = company_number.strip().upper()
    # The overview shows a sentence or two on what it does; a longer write-up is
    # kept in full in the research history (below), not on the overview.
    full_summary = summary
    if summary and (len(summary) > SUMMARY_MAX + 80 or "\n" in summary.strip()):
        summary = short_summary(summary)
    if not conn.execute("select 1 from company where company_number = %s", (num,)).fetchone():
        raise EnrichError(f"Company {num} is not in AcquireOS")
    if not source_url or not source_url.strip():
        raise EnrichError("A source_url is required for every enrichment (use 'manual' for your own knowledge)")
    if business_type and business_type not in BUSINESS_TYPES:
        raise EnrichError(f"business_type must be one of {BUSINESS_TYPES}")
    for name, v in (("recurring_revenue", recurring_revenue), ("field_service", field_service)):
        if v and v not in TRISTATE:
            raise EnrichError(f"{name} must be one of {TRISTATE}")
    if confidence not in CONFIDENCE:
        raise EnrichError(f"confidence must be one of {CONFIDENCE}")
    if website and not re.match(r"^https?://", website):
        website = "https://" + website.strip().lstrip("/")

    if linkedin and not re.match(r"^https?://", linkedin):
        linkedin = "https://" + linkedin.strip().lstrip("/")
    locs = _clean_locations(locations) if locations is not None else None
    fct = _clean_facts(facts, source_url) if facts is not None else None
    extra_sources = []
    for x in sources or []:
        url, label = (x, None) if isinstance(x, str) else ((x or {}).get("url"), (x or {}).get("label"))
        if url and str(url).strip():
            extra_sources.append((str(url).strip(), label))

    from .ownership import TYPE_LABELS
    from .normalise import region_for

    if ownership and ownership not in TYPE_LABELS:
        raise EnrichError(f"ownership must be one of {list(TYPE_LABELS)}")
    fields = {"website": website, "business_type": business_type, "recurring_revenue": recurring_revenue,
              "field_service": field_service, "summary": summary, "linkedin": linkedin, "phone": phone,
              "ownership": None if ownership == "unknown" else ownership, "ownership_note": ownership_note}
    given = {k: v for k, v in fields.items() if v not in (None, "")}
    if ownership == "unknown":  # back to what Companies House shows
        given["ownership"], given["ownership_note"] = None, None
    if locs is not None:
        given["locations"] = json.dumps(locs)
        # Where it really trades: the head office, which wins over the
        # registered office (often the accountant's) for region and scoring.
        head = next((l for l in locs if l["kind"] == "head office" and l.get("postcode")), None)
        given["trading_postcode"] = head["postcode"] if head else None
        given["trading_region"] = region_for(head["postcode"]) if head else None
    if fct is not None:
        given["facts"] = json.dumps(fct)
    lks = _clean_links(links) if links is not None else None
    if lks is not None:
        given["links"] = json.dumps(lks)
    dls = _clean_deals(deals, source_url) if deals is not None else None
    if dls is not None:
        given["deals"] = json.dumps(dls)
    if not given and not extra_sources:
        raise EnrichError("Nothing to save: give at least one of website, business_type, recurring_revenue, "
                          "field_service, summary, locations, facts, links, deals, linkedin, phone or sources")
    if not given:  # sources only
        for url, label in extra_sources:
            conn.execute("""insert into research (company_number, kind, content, source_url, source_label, created_by, confidence)
                            values (%s, 'source', %s, %s, %s, %s, %s)""", (num, label or "Source", url, label, by, confidence))
        return {"saved": ["sources"], "enrichment": conn.execute(
            "select * from enrichment where company_number = %s", (num,)).fetchone()}

    cols = ", ".join(given)
    vals = ", ".join(f"%({k})s" for k in given)
    upd = ", ".join(f"{k} = excluded.{k}" for k in given)
    conn.execute(
        f"""insert into enrichment (company_number, {cols}, confidence, updated_by)
            values (%(num)s, {vals}, %(conf)s, %(by)s)
            on conflict (company_number) do update set {upd}, confidence = excluded.confidence,
              updated_by = excluded.updated_by, updated_at = now()""",
        {**given, "num": num, "conf": confidence, "by": by},
    )
    labels = {"website": "Website", "business_type": "Business type", "recurring_revenue": "Recurring revenue",
              "field_service": "Field-service work", "summary": "Summary", "linkedin": "LinkedIn", "phone": "Phone",
              "ownership": "Ownership"}
    kinds = {"website": "website", "business_type": "classification", "recurring_revenue": "classification",
             "field_service": "classification", "summary": "summary", "linkedin": "contact", "phone": "contact",
             "ownership": "ownership"}
    if "ownership" in given and ownership_note:
        given_note = f"{TYPE_LABELS[given['ownership']]}: {ownership_note}"
    else:
        given_note = None
    src = None if source_url == "manual" else source_url
    rows = [(kinds[k], (full_summary or v) if k == "summary" else given_note if (k == "ownership" and given_note) else
             f"{labels[k]}: {(TYPE_LABELS.get(v, v) if v else 'as Companies House shows') if k == 'ownership' else v}", src, source_label)
            for k, v in given.items() if k in labels]
    for loc in locs or []:
        rows.append(("location", f"{loc['kind'].capitalize()}: {', '.join(x for x in (loc['name'], loc['address']) if x)}",
                     src, source_label))
    for f in fct or []:
        rows.append(("fact", f"{f['label']}: {f['value']}", f["source_url"], None))
    for url, label in extra_sources:
        rows.append(("source", label or "Source", url, label))
    for d in dls or []:
        rows.append(("deal", f"{d['date']}: {d['title']}" + (f" ({d['value']})" if d.get("value") else ""), d["source_url"], None))
    for lk in lks or []:
        rows.append(("link", lk["title"] + (f" ({lk['date']})" if lk.get("date") else ""), lk["url"], lk["kind"]))
    for kind, content, url, label in rows:
        conn.execute(
            """insert into research (company_number, kind, content, source_url, source_label, created_by, confidence)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (num, kind, content, url, label, by, confidence),
        )
    scoring.rescore(conn, company_number=num)
    row = conn.execute("select * from enrichment where company_number = %s", (num,)).fetchone()
    sc = conn.execute(
        "select s.score, s.excluded, s.exclusion from score s where s.company_number = %s "
        "order by s.excluded, s.score desc limit 1", (num,)).fetchone()
    return {"saved": list(given), "enrichment": row, "score_now": sc}


def flag_issue(conn, company_number: str | None, issue: str, detail: str | None = None,
               suggested_fix: str | None = None, by: str = "claude") -> dict:
    if not issue.strip():
        raise EnrichError("Describe the issue")
    num = company_number.strip().upper() if company_number else None
    if num and not conn.execute("select 1 from company where company_number = %s", (num,)).fetchone():
        raise EnrichError(f"Company {num} is not in AcquireOS")
    return conn.execute(
        """insert into data_issue (company_number, issue, detail, suggested_fix, created_by)
           values (%s, %s, %s, %s, %s) returning *""",
        (num, issue.strip(), detail, suggested_fix, by),
    ).fetchone()


def resolve_issue(conn, issue_id: int, resolution: str, status: str = "resolved") -> dict:
    if status not in ("resolved", "dismissed", "open"):
        raise EnrichError("status must be resolved, dismissed or open")
    row = conn.execute(
        """update data_issue set status = %s, resolution = %s,
               resolved_at = case when %s = 'open' then null else now() end
           where id = %s returning *""",
        (status, resolution, status, issue_id),
    ).fetchone()
    if not row:
        raise EnrichError(f"No data issue with id {issue_id}")
    return row


def audit_queue(conn, check: str = "all", limit: int = 20, min_score: float = 0,
                include_excluded: bool = False, pipeline_only: bool = False) -> list[dict]:
    """Companies that need auditing or enrichment, highest scores first."""
    if check != "all" and check not in AUDIT_CHECKS:
        raise EnrichError(f"check must be 'all' or one of {list(AUDIT_CHECKS)}")
    bb = scoring.active_buy_box(conn)
    rows = conn.execute(
        """
        select c.company_number, c.name, c.sic_codes, c.nature_of_business, c.postcode, c.region,
               c.registered_address, c.address_flag, s.score, s.excluded,
               coalesce(uc.status, 'new') as my_status,
               e.website, e.business_type, e.field_service, e.recurring_revenue, e.updated_at as enriched_at,
               est.basis as revenue_basis, o.ownership_type,
               (select count(*) from research r where r.company_number = c.company_number) as research_count
        from company c
        left join (select company_number, score, false as excluded from company_best) s on s.company_number = c.company_number
        left join user_company uc on uc.company_number = c.company_number and uc.user_id = 1
        left join enrichment e on e.company_number = c.company_number
        left join estimate est on est.company_number = c.company_number
        left join company_ownership o on o.company_number = c.company_number
        where coalesce(s.score, 0) >= %(min)s
          and (%(incl)s or coalesce(not s.excluded, false))
          and (not %(pipe)s or coalesce(uc.status, 'new') not in ('new', 'rejected', 'passed'))
          and coalesce(c.status, 'active') = 'active'
        order by (coalesce(uc.status, 'new') not in ('new', 'rejected', 'passed')) desc, s.score desc nulls last
        limit 5000
        """,
        {"bb": bb["id"], "min": min_score, "incl": include_excluded, "pipe": pipeline_only},
    ).fetchall()
    out = []
    for r in rows:
        problems = []
        if not r["website"]:
            problems.append("missing_website")
        if r["research_count"] == 0:
            problems.append("no_research")
        if (r["ownership_type"] or "unknown") == "unknown":
            problems.append("ownership_unknown")
        if r["revenue_basis"] != "filed":
            problems.append("estimate_only")
        if not r["field_service"] or r["field_service"] == "unknown":
            problems.append("field_service_unknown")
        if r["enriched_at"] is not None and (r["enriched_at"].timestamp() < __import__("time").time() - 365 * 864e2):
            problems.append("stale")
        if r["address_flag"]:
            problems.append("address_flag")
        tech_name = bool(TECH_WORDS.search(r["name"] or ""))
        tech_sic = any(code.startswith(TECH_SIC) for code in r["sic_codes"] or [])
        if tech_name != tech_sic:
            problems.append("sic_mismatch")
        if check == "all" and problems or check in problems:
            out.append({
                "company_number": r["company_number"], "name": r["name"], "score": float(r["score"]) if r["score"] is not None else None,
                "my_status": r["my_status"], "postcode": r["postcode"], "region": r["region"],
                "sic_codes": r["sic_codes"], "registered_address": r["registered_address"],
                "website": r["website"], "business_type": r["business_type"],
                "needs": [AUDIT_CHECKS[p] for p in problems], "checks": problems,
                "companies_house": f"https://find-and-update.company-information.service.gov.uk/company/{r['company_number']}",
            })
        if len(out) >= limit:
            break
    return out


READONLY_BLOCK = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|vacuum|call|do|lock|set|reset|refresh|cluster|comment|security|listen|notify)\b", re.I)


def readonly_query(conn, sql: str, max_rows: int = 500) -> dict:
    """Run one SELECT in its own read-only transaction with a 15 second limit.
    Uses a separate connection so it can never affect the caller's work."""
    from . import db

    q = sql.strip().rstrip(";")
    if ";" in q:
        raise EnrichError("One statement only")
    if not re.match(r"^\s*(select|with)\b", q, re.I):
        raise EnrichError("Only SELECT (or WITH ... SELECT) queries are allowed")
    if READONLY_BLOCK.search(re.sub(r"'[^']*'", "''", q)):
        raise EnrichError("Query contains a keyword that is not allowed in read-only mode")
    ro = db.connect()
    try:
        ro.execute("set transaction read only")
        ro.execute("set local statement_timeout = '15s'")
        try:
            rows = ro.execute(q).fetchmany(max_rows + 1)
        except Exception as e:
            raise EnrichError(f"Query failed: {str(e).splitlines()[0]}")
    finally:
        ro.rollback()
        ro.close()
    return {"rows": json.loads(json.dumps(rows[:max_rows], default=str)), "truncated": len(rows) > max_rows}
