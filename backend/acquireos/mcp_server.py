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
Finding websites and enriching: call research_brief (every name the company may trade under, its
address, owners, parent and subsidiaries, and search queries), search the web with those queries, then
check_website with the most likely site: it confirms the site by the company number or postcode on it
and saves it. Then classify with save_enrichment. find_website tries likely domains by itself.
Directors, shareholders, charges, filings and investment signals: get_charges_and_investment.
Start with dataset_overview, list_targets, search_companies or audit_queue."""

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
    "status (the user's pipeline): new|watching|researching|approach (shortlisted)|contacted|in_talks|"
    "passed (not now)|rejected (not suitable). "
    "sic: code prefix such as 620. changed_days: only companies with changes in the last N days. "
    "sold: hide|only (sold to another company in the last 3 years). signal: possible_buyer|many_shareholders. "
    "mine: hide_closed|pipeline|untouched. has_website: true|false. "
    "revenue: filed (confirmed in the accounts)|estimated|none."))
def search_companies(query: str | None = None, region: str | None = None, min_score: float | None = None,
                     ownership: str | None = None, status: str | None = None, min_staff: int | None = None,
                     max_staff: int | None = None, min_owner_age: int | None = None, sic: str | None = None,
                     changed_days: int | None = None, include_excluded: bool = False, sort: str | None = None,
                     limit: int = 25, sold: str | None = None, signal: str | None = None, mine: str | None = None,
                     has_website: bool | None = None, revenue: str | None = None) -> str:
    r = _api().companies(q=query, region=region, min_score=min_score, ownership=ownership, status=status,
                         min_staff=min_staff, max_staff=max_staff, min_owner_age=min_owner_age, sic=sic,
                         changed_days=changed_days, include_excluded=include_excluded,
                         sort=sort or ("relevance" if query else "score"),
                         limit=max(1, min(limit, 200)), sold=sold, signal=signal, mine=mine, has_website=has_website,
                         revenue=revenue)
    keep = ("company_number", "name", "region", "trading_region", "postcode", "sic_codes", "employees", "revenue_low",
            "revenue_high", "revenue_basis", "revenue_method", "value_low", "value_high", "value_basis", "ownership_type",
            "oldest_birth_year", "flags", "signals", "sold_on", "sold_to", "same_business", "score",
            "excluded", "exclusion", "status", "rating", "company_status", "last_change", "website")
    return _j({"total": r["total"], "companies": [{k: row.get(k) for k in keep} for row in r["rows"]]})


@server.tool(description="Everything about one company: score reasons, financial history, valuation, owners, "
                         "links, changes, enrichment, research with sources, data issues and the user's notes.")
def get_company(company_number: str) -> str:
    d = _api().company(company_number.strip().upper())
    d["company"] = {k: v for k, v in d["company"].items() if k != "extra"}
    return _j(d)


@server.tool(description=(
    "What changed: from the monthly bulk files (status|accounts|staff|name|address|sic|owner|new_company) and from "
    "Companies House API checks (filing|director|charge|shareholders|insolvency; source 'api'). "
    "pipeline_only for companies you are pursuing."))
def list_changes(days: int = 30, kind: str | None = None, pipeline_only: bool = False, unread_only: bool = False) -> str:
    return _j(_api().changes(days=days, kind=kind, tracked=pipeline_only, limit=300, unread=unread_only))


@server.tool(description="Mark changes as read (ids from list_changes), or all of them with all=true. Only when the user asks.")
def mark_changes_read(ids: list[int] | None = None, all: bool = False) -> str:
    a = _api()
    if all:
        return _j(a.changes_seen())
    return _j(a.changes_read(a.ReadIn(ids=ids or [])))


@server.tool(description=(
    "Start the background website check: finds sites for companies without one and saves a site only when it shows "
    "both the company number and the registered name (Ltd/Limited); office addresses on it are saved too. "
    "scope: pipeline|targets. Takes a few seconds per company. Only when the user asks."))
def start_website_check(scope: str = "targets", limit: int = 200) -> str:
    return _j(_api().website_check_batch(scope=scope, limit=limit))


@server.tool(description=(
    "Read a set of accounts that Companies House holds only as a PDF (the figures are not in the bulk data). "
    "Returns the PDF's text (newest accounts, or made_up_date YYYY-MM-DD). Read the balance sheet, profit and loss "
    "and notes, then save the figures with save_financials. Scanned paper filings have no text: say so."))
def read_accounts_pdf(company_number: str, made_up_date: str | None = None) -> str:
    from . import chapi

    with db.conn() as c:
        return _j(chapi.accounts_pdf_text(c, company_number, made_up_date))


@server.tool(description=(
    "Save figures you read from a company's filed accounts (e.g. a PDF via read_accounts_pdf), for one year end "
    "(period_end YYYY-MM-DD). Give only figures printed in the accounts, in pounds; never estimates. source_url is "
    "the filing (its Companies House filing-history page). The company is rescored. Figures are marked as read "
    "from a PDF. Fields: turnover, gross_profit, operating_profit, profit_loss (after tax), employees (average), "
    "net_assets, cash, debtors, fixed_assets, current_assets, net_current_assets, total_assets_less_cl, staff_costs, "
    "director_pay, dividends."))
def save_financials(company_number: str, period_end: str, source_url: str, turnover: float | None = None,
                    gross_profit: float | None = None, operating_profit: float | None = None,
                    profit_loss: float | None = None, employees: int | None = None, net_assets: float | None = None,
                    cash: float | None = None, debtors: float | None = None, fixed_assets: float | None = None,
                    current_assets: float | None = None, net_current_assets: float | None = None,
                    total_assets_less_cl: float | None = None, staff_costs: float | None = None,
                    director_pay: float | None = None, dividends: float | None = None) -> str:
    from datetime import date as _date

    from . import scoring
    from .importers.accounts import _upsert
    from .importers.companies import refresh_estimates

    vals = {k: v for k, v in dict(turnover=turnover, gross_profit=gross_profit, operating_profit=operating_profit,
                                    profit_loss=profit_loss, employees=employees, net_assets=net_assets, cash=cash,
                                    debtors=debtors, fixed_assets=fixed_assets, current_assets=current_assets,
                                    net_current_assets=net_current_assets, total_assets_less_cl=total_assets_less_cl,
                                    staff_costs=staff_costs, director_pay=director_pay, dividends=dividends).items()
            if v is not None}
    if not vals:
        raise ValueError("Give at least one figure")
    if not source_url:
        raise ValueError("source_url is required")
    num = company_number.strip().upper()
    pe = _date.fromisoformat(period_end)
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise ValueError(f"Company {num} is not in AcquireOS")
        _upsert(c, num, pe, vals, "pdf:claude", balance_date=pe)
        c.execute("""insert into research (company_number, kind, content, source_url, source_label, created_by, confidence)
                     values (%s, 'fact', %s, %s, 'Accounts PDF', 'claude (mcp)', 'high')""",
                  (num, f"Figures read from the accounts to {period_end}: " +
                   ", ".join(f"{k.replace('_', ' ')} {v:,.0f}" for k, v in vals.items()), source_url))
        c.execute("create temp table if not exists api_touched (company_number text)")
        c.execute("delete from api_touched")
        c.execute("insert into api_touched values (%s)", (num,))
        refresh_estimates(c, from_table="api_touched")
        scoring.refresh_latest(c, [num])
        scoring.rescore(c, company_number=num)
    return _j({"saved": sorted(vals), "period_end": period_end})


@server.tool(description=(
    "A briefing for today: unread changes to pipeline companies, next actions due in the next 7 days, "
    "pipeline companies recently sold or buying others, and how far the Companies House sync has got."))
def daily_briefing() -> str:
    a = _api()
    from . import chsync

    changes = a.changes(days=30, tracked=True, limit=100, unread=True)["rows"]
    with db.conn() as c:
        due = c.execute(
            """select uc.company_number, c.name, uc.status, uc.next_action, uc.next_action_on from user_company uc
               join company c on c.company_number = uc.company_number
               where uc.user_id = 1 and uc.next_action is not null and uc.next_action_on <= current_date + 7
                 and uc.status not in ('passed', 'rejected')
               order by uc.next_action_on""").fetchall()
        flagged = c.execute(
            """select uc.company_number, c.name, uc.status, sg.signals, sg.sold_on, sg.sold_to from user_company uc
               join company c on c.company_number = uc.company_number
               join company_signal sg on sg.company_number = uc.company_number
               where uc.user_id = 1 and uc.status not in ('new', 'passed', 'rejected')
                 and (sg.signals && array['recently_sold', 'possible_buyer'])""").fetchall()
        sync = chsync.status(c)
    return _j({"unread_pipeline_changes": changes, "next_actions_due": due, "pipeline_sold_or_buying": flagged,
               "sync": {k: sync.get(k) for k in ("running", "pipeline", "targets", "per_hour", "days_to_cover")}})


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
    "summary may use short paragraphs and '- ' bullet lines. "
    "locations: every office or site found, as [{name, address, postcode, kind}] with kind "
    + "|".join(enrich.LOCATION_KINDS) + " (replaces the saved list, so send all of them). "
    "facts: other key facts, each with its own source, as [{label, value, source_url}] e.g. "
    "{label: 'Delisted from AIM', value: '11 Apr 2024', source_url: ...} (replaces the saved list). "
    "linkedin, phone: company contact links. sources: extra pages used, as [url] or [{url, label}]. "
    "ownership: what research shows, when it differs from Companies House (e.g. sold to a group): one of "
    "owner_held|group_owned|investor_backed|eot|trust|foreign_owned, with ownership_note saying what and when "
    "(e.g. 'Bought by Aspire Systems (India), July 2024'). It overrides the register in scoring. "
    "Mark the head office in locations: it sets the region used for scoring when the registered office is "
    "an accountant's or agent's address. Never save revenue or staff figures from revenue-data or "
    "company-profile websites (they often mix up companies with similar names); put figures only in facts, "
    "with the source. "
    "Each save is also kept, dated and sourced, in the company's research history."))
def save_enrichment(company_number: str, source_url: str, website: str | None = None,
                    business_type: str | None = None, recurring_revenue: str | None = None,
                    field_service: str | None = None, summary: str | None = None,
                    confidence: str = "medium", source_label: str | None = None,
                    locations: list[dict] | None = None, facts: list[dict] | None = None,
                    linkedin: str | None = None, phone: str | None = None, sources: list | None = None,
                    ownership: str | None = None, ownership_note: str | None = None) -> str:
    with db.conn() as c:
        return _j(enrich.save_enrichment(c, company_number, source_url=source_url, website=website,
                                         business_type=business_type, recurring_revenue=recurring_revenue,
                                         field_service=field_service, summary=summary, confidence=confidence,
                                         source_label=source_label, locations=locations, facts=facts,
                                         linkedin=linkedin, phone=phone, sources=sources, ownership=ownership,
                                         ownership_note=ownership_note, by="claude (mcp)"))


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


@server.tool(description=(
    "Companies in the user's buy boxes, best score first (the Targets list). buy_box: a buy box id from "
    "list_buy_boxes, or omit for any. show: hide_closed (default: hides passed and rejected) | all | pipeline | untouched. "
    "Other filters as search_companies."))
def list_targets(buy_box: int | None = None, show: str = "hide_closed", region: str | None = None,
                 min_score: float | None = None, ownership: str | None = None, min_staff: int | None = None,
                 max_staff: int | None = None, min_owner_age: int | None = None, sic: str | None = None,
                 limit: int = 25) -> str:
    r = _api().companies(bb=str(buy_box) if buy_box else "all", in_box=True, mine=None if show == "all" else show,
                         region=region, min_score=min_score, ownership=ownership, min_staff=min_staff,
                         max_staff=max_staff, min_owner_age=min_owner_age, sic=sic, sort="score",
                         limit=max(1, min(limit, 200)))
    keep = ("company_number", "name", "region", "postcode", "employees", "revenue_low", "revenue_high", "revenue_basis",
            "value_low", "value_high", "ownership_type", "oldest_birth_year", "score", "box_name", "status",
            "accounts_category", "charges_outstanding", "website")
    return _j({"total": r["total"], "companies": [{k: row.get(k) for k in keep} for row in r["rows"]]})


@server.tool(description="Find owners (persons with significant control) by name, with how many companies each controls. "
                         "Then get_owner for everything one owner holds.")
def search_owners(name: str, limit: int = 25) -> str:
    return _j(_api().owners(q=name, limit=max(1, min(limit, 100))))


@server.tool(description="One owner and every company they control: directly, through holding companies, and in the past.")
def get_owner(owner_id: int) -> str:
    return _j(_api().owner(owner_id))


@server.tool(description=("A company's financial trends: each year's figures (total assets and liabilities worked out "
                          "from the accounts), the change on the year before, and a plain-English trend per figure."))
def get_financials(company_number: str) -> str:
    from . import fintrends

    num = company_number.strip().upper()
    with db.conn() as c:
        fin = c.execute("select * from financial_period where company_number = %s order by period_end", (num,)).fetchall()
        est = c.execute("select * from estimate where company_number = %s", (num,)).fetchone()
    return _j({"summary": fintrends.summary(fin), "revenue_estimate": est})


@server.tool(description=(
    "Companies House details: directors (ages, tenure) and their other companies, shareholders from the latest "
    "confirmation statement that lists them, charges and who holds them, filing history incl. late accounts, "
    "insolvency, owner statements, and signs of outside investment. refresh=true fetches the latest "
    "(needs the user's CH_API_KEY; about 10 seconds a company)."))
def get_charges_and_investment(company_number: str, refresh: bool = False) -> str:
    from . import chapi

    num = company_number.strip().upper()
    with db.conn() as c:
        note = None
        if refresh:
            try:
                chapi.fetch(c, num)
            except chapi.NoKey as e:
                note = str(e)
        counts = c.execute(
            """select charges_total, charges_outstanding, charges_part_satisfied, charges_satisfied
               from company where company_number = %s""", (num,)).fetchone()
        d = chapi.details(c, num)
        d["filings"] = d["filings"][:40]
        return _j({"counts_from_register": counts, **d, "note": note})


@server.tool(description=(
    "Everything for finding a company online: current, previous, parent and subsidiary names (a website is "
    "often under one of these), registered address and town, owners, industry, domain guesses and ready-made "
    "web search queries, and how to confirm a site."))
def research_brief(company_number: str) -> str:
    return _j(_api().research_brief(company_number.strip().upper()))


@server.tool(description=(
    "Check a website for a company: fetches it (and its contact, about and legal pages) and confirms it by the "
    "company number (high) or registered postcode (medium) on the site. A confirmed site is saved as the "
    "company's website with the page as its source."))
def check_website(company_number: str, url: str) -> str:
    return _j(_api().find_website(company_number.strip().upper(), _api().WebsiteCheckIn(url=url)))


@server.tool(description="Try likely domains from the company's names and save one confirmed by its company number or postcode.")
def find_website(company_number: str) -> str:
    return _j(_api().find_website(company_number.strip().upper(), None))


@server.tool(description="The user's pipeline: companies by stage, with checklist progress, next actions and last notes.")
def list_pipeline() -> str:
    d = _api().pipeline()
    keep = ("company_number", "name", "status", "score", "value_low", "value_high", "next_action", "next_action_on",
            "stage_entered_at", "tasks_done", "tasks_total", "last_note", "rating")
    return _j({"rows": [{k: r.get(k) for k in keep} for r in d["rows"]]})


@server.tool(description="Set the next action (and its date, YYYY-MM-DD) on a company. Only when the user asks.")
def set_next_action(company_number: str, action: str, on: str | None = None) -> str:
    body = {"next_action": action or None}
    if on:
        body["next_action_on"] = on
    return _j(_api().set_state(company_number.strip().upper(), _api().StateIn(**body)))


@server.tool(description=(
    "Log contact with a company (letter, email, call, meeting...) on the user's outreach record. Only when the user "
    "asks. follow_up_on (YYYY-MM-DD) also sets the company's next action."))
def log_outreach(company_number: str, summary: str, channel: str = "email", contact_name: str = "Owner",
                 contact_role: str = "owner", happened_on: str | None = None, follow_up_on: str | None = None) -> str:
    num = company_number.strip().upper()
    nxt = f"Follow up: {summary[:80]}" if follow_up_on else None
    r = _api().outreach_add(_api().OutreachIn(company_number=num, contact_name=contact_name, contact_role=contact_role,
                                              channel=channel, summary=summary, happened_on=happened_on,
                                              next_action=nxt, next_action_on=follow_up_on))
    if follow_up_on:
        _api().set_state(num, _api().StateIn(next_action=nxt, next_action_on=follow_up_on))
    return _j(r)


@server.tool(description="Side-by-side key facts for 2 to 8 companies: score, staff, revenue, value, owners, trends.")
def compare_companies(company_numbers: list[str]) -> str:
    from . import fintrends

    out = []
    for raw in company_numbers[:8]:
        num = raw.strip().upper()
        try:
            d = _api().company(num)
        except Exception as e:  # unknown number
            out.append({"company_number": num, "error": str(e)})
            continue
        fs = fintrends.summary(d["financials"])
        own = d["ownership"] or {}
        out.append({
            "company_number": num, "name": d["company"]["name"], "status": d["company"]["status"],
            "region": d["company"]["region"], "incorporated": d["company"]["incorporation_date"],
            "best_score": max((float(x["score"]) for x in d["scores"] if not x["excluded"]), default=None),
            "revenue_estimate": d["estimate"], "valuation": {k: d["valuation"].get(k) for k in ("value_low", "value_high", "basis")},
            "ownership": own.get("ownership_type"), "oldest_owner_born": own.get("oldest_birth_year"),
            "latest_figures": {r["label"]: {"value": r["value"], "change_pct": r["change_pct"], "trend": r["trend"]} for r in fs["rows"]},
            "charges_outstanding": d["company"].get("charges_outstanding"), "my_status": d["state"].get("status"),
            "website": (d["enrichment"] or {}).get("website"),
        })
    return _j(out)


@server.prompt(description="Work through the audit queue: verify each company and save sourced enrichment.")
def audit_and_enrich(batch_size: int = 10, check: str = "all") -> str:
    return f"""Please audit and enrich AcquireOS data.

1. Call audit_queue(check="{check}", limit={batch_size}).
2. For each company:
   - Call research_brief and search the web with its queries (the site may be under a previous, parent,
     subsidiary or trading name). Pass the most likely site to check_website: it saves it only if the
     company number or postcode is on it. If nothing confirms, do not save a website.
   - Decide business_type, whether revenue looks recurring (contracts, subscriptions, managed services,
     support plans) and whether it does field-service or van-based work (installations, engineers on site).
   - Write a two or three sentence factual summary of what it sells and to whom.
   - save_enrichment with the page you used as source_url and an honest confidence.
   - If the data looks wrong (SIC code does not match what they do, registered office is an accountant,
     owner link looks wrong), call flag_data_issue with what you found.
3. Finish with a short table: company, what you saved, confidence, issues raised, anything to check by hand.
Do not change notes or statuses."""
