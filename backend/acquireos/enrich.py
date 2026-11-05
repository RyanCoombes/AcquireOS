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


def save_enrichment(conn, company_number: str, *, source_url: str, website: str | None = None,
                    business_type: str | None = None, recurring_revenue: str | None = None,
                    field_service: str | None = None, summary: str | None = None,
                    confidence: str = "medium", source_label: str | None = None, by: str = "claude") -> dict:
    num = company_number.strip().upper()
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

    fields = {"website": website, "business_type": business_type, "recurring_revenue": recurring_revenue,
              "field_service": field_service, "summary": summary}
    given = {k: v for k, v in fields.items() if v not in (None, "")}
    if not given:
        raise EnrichError("Nothing to save: give at least one of website, business_type, recurring_revenue, field_service, summary")

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
              "field_service": "Field-service work", "summary": "Summary"}
    kinds = {"website": "website", "business_type": "classification", "recurring_revenue": "classification",
             "field_service": "classification", "summary": "summary"}
    for k, v in given.items():
        conn.execute(
            """insert into research (company_number, kind, content, source_url, source_label, created_by, confidence)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (num, kinds[k], v if k == "summary" else f"{labels[k]}: {v}",
             None if source_url == "manual" else source_url, source_label, by, confidence),
        )
    scoring.rescore(conn, company_number=num)
    row = conn.execute("select * from enrichment where company_number = %s", (num,)).fetchone()
    sc = conn.execute(
        "select s.score, s.excluded, s.exclusion from score s join buy_box b on b.id = s.buy_box_id and b.is_active "
        "where s.company_number = %s", (num,)).fetchone()
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
