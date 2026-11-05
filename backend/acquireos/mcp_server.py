"""MCP server: lets Claude (Desktop, Cowork, Claude Code) work with AcquireOS.

Served over Streamable HTTP at /mcp on the same port as the web app.
Authentication: "Authorization: Bearer <API_TOKEN>" (see config.API_TOKEN).

Read tools answer questions; write tools save sourced enrichment, flag data
problems and, only when you ask, update your own notes and statuses.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import db, enrich, scoring
from .importers.notes import STATUSES

INSTRUCTIONS = """AcquireOS holds UK private companies being researched as acquisition targets, built from
Companies House data, scored against the user's buy box, plus the user's own notes and pipeline.

Ground rules:
- Companies House figures are facts as filed. Revenue and value are often ESTIMATES; say so.
- When enriching, verify on the company's own website or another reliable source and pass that
  page as source_url. Never guess a website or classification. If unsure, use 'unknown' or flag an issue.
- Use save_enrichment for researched facts and flag_data_issue for problems in the data.
- Only use add_note or set_status when the user explicitly asks you to change their notes or pipeline.
- Owner names and birth dates are personal data: use them for this research only.
Start with dataset_overview, search_companies or audit_queue."""

server = MCPServer(name="AcquireOS", instructions=INSTRUCTIONS)


def _j(v: Any) -> str:
    return json.dumps(v, default=str, indent=1)


def _api():
    from . import api  # late import: api imports this module
    return api


@server.tool(description="Headline numbers, data freshness, recent changes and the best unreviewed targets.")
def dataset_overview() -> str:
    d = _api().dashboard()
    return _j({k: d[k] for k in ("head", "top", "recent", "due", "funnel", "ownership", "freshness", "buy_box")})


@server.tool(description=(
    "Search and filter companies. All filters optional. sort: score|name|staff|revenue|value|age|years|changed. "
    "ownership: owner_held|group_owned|investor_backed|eot|trust|foreign_owned|unknown. "
    "status (the user's pipeline): new|watching|researching|approach|contacted|in_talks|passed|rejected. "
    "sic: code prefix such as 620. changed_days: only companies with changes in the last N days."))
def search_companies(query: str | None = None, region: str | None = None, min_score: float | None = None,
                     ownership: str | None = None, status: str | None = None, min_staff: int | None = None,
                     max_staff: int | None = None, min_owner_age: int | None = None, sic: str | None = None,
                     changed_days: int | None = None, include_excluded: bool = False, sort: str = "score",
                     limit: int = 25) -> str:
    r = _api().companies(q=query, region=region, min_score=min_score, ownership=ownership, status=status,
                         min_staff=min_staff, max_staff=max_staff, min_owner_age=min_owner_age, sic=sic,
                         changed_days=changed_days, include_excluded=include_excluded, sort=sort,
                         limit=max(1, min(limit, 200)))
    keep = ("company_number", "name", "region", "postcode", "sic_codes", "employees", "revenue_low", "revenue_high",
            "revenue_basis", "value_low", "value_high", "ownership_type", "oldest_birth_year", "flags", "score",
            "excluded", "exclusion", "status", "rating", "company_status", "last_change")
    return _j({"total": r["total"], "companies": [{k: row.get(k) for k in keep} for row in r["rows"]]})


@server.tool(description="Everything about one company: score reasons, financial history, valuation, owners, "
                         "links, changes, enrichment, research with sources, data issues and the user's notes.")
def get_company(company_number: str) -> str:
    d = _api().company(company_number.strip().upper())
    d["company"] = {k: v for k, v in d["company"].items() if k != "extra"}
    return _j(d)


@server.tool(description="What changed between data imports. kind: status|accounts|staff|name|address|sic|owner|new_company.")
def list_changes(days: int = 30, kind: str | None = None, pipeline_only: bool = False) -> str:
    return _j(_api().changes(days=days, kind=kind, tracked=pipeline_only, limit=300))


@server.tool(description=(
    "Companies that need auditing or enrichment, pipeline companies first then highest score. "
    "check: all|" + "|".join(enrich.AUDIT_CHECKS) + ". Each result lists what is missing."))
def audit_queue(check: str = "all", limit: int = 20, min_score: float = 0, pipeline_only: bool = False) -> str:
    with db.conn() as c:
        return _j(enrich.audit_queue(c, check=check, limit=max(1, min(limit, 100)), min_score=min_score,
                                     pipeline_only=pipeline_only))


@server.tool(description=(
    "Save researched facts about a company. source_url is required: the page where you verified it "
    "('manual' only if the user told you). business_type: " + "|".join(enrich.BUSINESS_TYPES) +
    ". recurring_revenue and field_service: yes|partly|no|unknown. confidence: high|medium|low. "
    "Give only the fields you verified. Rescores the company and returns the new score."))
def save_enrichment(company_number: str, source_url: str, website: str | None = None,
                    business_type: str | None = None, recurring_revenue: str | None = None,
                    field_service: str | None = None, summary: str | None = None,
                    confidence: str = "medium", source_label: str | None = None) -> str:
    with db.conn() as c:
        return _j(enrich.save_enrichment(c, company_number, source_url=source_url, website=website,
                                         business_type=business_type, recurring_revenue=recurring_revenue,
                                         field_service=field_service, summary=summary, confidence=confidence,
                                         source_label=source_label, by="claude (mcp)"))


@server.tool(description="Record a problem in the data for the user to review, e.g. wrong SIC code, owner link "
                         "that looks wrong, misleading address, duplicate company. company_number may be empty for "
                         "dataset-wide issues.")
def flag_data_issue(issue: str, company_number: str | None = None, detail: str | None = None,
                    suggested_fix: str | None = None) -> str:
    with db.conn() as c:
        return _j(enrich.flag_issue(c, company_number, issue, detail, suggested_fix, by="claude (mcp)"))


@server.tool(description="List data issues. status: open|resolved|dismissed|all.")
def list_data_issues(status: str = "open", limit: int = 50) -> str:
    with db.conn() as c:
        where = "" if status == "all" else "where d.status = %(st)s"
        return _j(c.execute(
            f"""select d.*, c.name from data_issue d left join company c on c.company_number = d.company_number
                {where} order by d.created_at desc limit %(lim)s""", {"st": status, "lim": min(limit, 500)}).fetchall())


@server.tool(description="Mark a data issue resolved or dismissed, with what was done.")
def resolve_data_issue(issue_id: int, resolution: str, status: str = "resolved") -> str:
    with db.conn() as c:
        return _j(enrich.resolve_issue(c, issue_id, resolution, status))


@server.tool(description="Tables and columns available to query_database, with notes on what they mean.")
def describe_database() -> str:
    with db.conn() as c:
        cols = c.execute(
            """select table_name, string_agg(column_name || ' ' || data_type, ', ' order by ordinal_position) as cols
               from information_schema.columns where table_schema = 'public' and table_name not in ('schema_migration', 'app_user')
               group by 1 order by 1""").fetchall()
    notes = {
        "company": "One row per company. status is the Companies House status. sic_codes is an array.",
        "financial_period": "Filed accounts by period_end. period_inferred=true means a prior-year figure with an assumed date.",
        "estimate": "Revenue range: basis 'filed' (turnover) or 'estimated' (from staff).",
        "score": "Score per buy box (join buy_box where is_active). reasons is JSON. value_low/high = indicative value.",
        "company_ownership": "ownership_type, flags, oldest_birth_year of individual owners (traced through holdcos).",
        "company_person / person": "Owners (role='psc'). ceased_on null = current.",
        "company_link": "a,b company numbers. kind owned_by|shared_owner|shared_address, confidence.",
        "company_change": "Change log between imports.",
        "user_company / user_note / outreach": "The user's own pipeline, notes and contacts.",
        "enrichment / research / data_issue": "Researched facts with sources, and audit problems.",
        "postcode_geo / sic_code": "Coordinates per postcode; SIC descriptions.",
    }
    return _j({"tables": cols, "notes": notes})


@server.tool(description="Run one read-only SQL SELECT against the AcquireOS Postgres database (15s limit, "
                         "max 500 rows). Use describe_database first.")
def query_database(sql: str) -> str:
    with db.conn() as c:
        return _j(enrich.readonly_query(c, sql))


@server.tool(description="Add a note to a company in the user's own notes, labelled as written by Claude. "
                         "Only when the user asks you to.")
def add_note(company_number: str, text: str) -> str:
    import hashlib
    import time

    num = company_number.strip().upper()
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            return f"Company {num} is not in AcquireOS"
        h = hashlib.sha256(f"{time.time_ns()}:{text}".encode()).hexdigest()
        return _j(c.execute(
            """insert into user_note (user_id, company_number, body, source, content_hash)
               values (1, %s, %s, 'claude', %s) returning id, body, created_at""", (num, text.strip(), h)).fetchone())


@server.tool(description="Move a company to a stage of the user's acquisition process (" + "|".join(STATUSES) + "; "
                         "assess: new, watching, researching=Assessing, approach=Shortlisted; engage: contacted, in_talks, nda; "
                         "deal: offer, heads (heads of terms), diligence, spa, completion; then handover; or passed/rejected). "
                         "The move is logged with an optional note. Only when the user asks you to.")
def set_status(company_number: str, status: str, next_action: str | None = None, note: str | None = None) -> str:
    if status not in STATUSES:
        return f"status must be one of {STATUSES}"
    num = company_number.strip().upper()
    body: dict = {"status": status, "stage_note": note}
    if next_action:
        body["next_action"] = next_action
    return _j(_api().set_state(num, _api().StateIn(**body)))


@server.tool(description="List the user's buy boxes (each is a separate search with its own universe and scoring) "
                         "and which one is active. search_companies and audit_queue use the active one.")
def list_buy_boxes() -> str:
    return _j(_api().buyboxes())


@server.tool(description="Set the user's own 0-5 score for one of their criteria on a company (see get_company -> "
                         "manual.criteria for the keys). Only when the user asks you to; value null clears it.")
def set_my_score(company_number: str, criterion_key: str, value: int | None, note: str | None = None) -> str:
    return _j(_api().set_manual(company_number.strip().upper(),
                                _api().ManualIn(key=criterion_key, value=value, note=note)))


@server.prompt(description="Work through the audit queue: verify each company and save sourced enrichment.")
def audit_and_enrich(batch_size: int = 10, check: str = "all") -> str:
    return f"""Please audit and enrich AcquireOS data.

1. Call audit_queue(check="{check}", limit={batch_size}).
2. For each company:
   - Open its Companies House page (given in the result) and its own website. Find the website by searching
     the company name plus town or postcode; confirm it is the same company (company number, address or
     name in the site footer). If you cannot confirm it, do not save a website.
   - Decide business_type, whether revenue looks recurring (contracts, subscriptions, managed services,
     support plans) and whether it does field-service or van-based work (installations, engineers on site).
   - Write a two or three sentence factual summary of what it sells and to whom.
   - save_enrichment with the page you used as source_url and an honest confidence.
   - If the data looks wrong (SIC code does not match what they do, registered office is an accountant,
     owner link looks wrong), call flag_data_issue with what you found.
3. Finish with a short table: company, what you saved, confidence, issues raised, anything to check by hand.
Do not change notes or statuses."""
