"""Companies whose latest accounts on the register are much newer than the
latest year of figures held: years that never arrived.

Figures come two ways: the monthly bulk files (only accounts filed as data),
and a per-company Companies House check (data years fetched straight away,
PDF-only years queued for the PDF reader). A company falls through when its
newer accounts were filed as PDF, or in a bulk month that didn't load, and its
filings haven't been checked since; or when its PDF couldn't be read.
"""
from __future__ import annotations

GAP_DAYS = 300  # register's last accounts this much newer than the latest year held

GAP_SQL = """
with held as (
    select company_number, max(period_end) as latest
    from financial_period where not period_inferred group by company_number
)
select c.company_number, c.name, c.last_accounts_date, h.latest as latest_held,
       f.fetched_at as ch_checked,
       exists (select 1 from pdf_read r where r.company_number = c.company_number
               and r.made_up > coalesce(h.latest, date '1900-01-01') + 45
               and r.status in ('failed', 'nothing_found')) as pdf_failed,
       exists (select 1 from pdf_read r where r.company_number = c.company_number
               and r.made_up > coalesce(h.latest, date '1900-01-01') + 45 and r.status = 'closed') as pdf_closed,
       exists (select 1 from filing fl where fl.company_number = c.company_number and fl.type = 'AA'
               and fl.detail->>'made_up_date' ~ '^\\d{4}-\\d{2}-\\d{2}$'
               and (fl.detail->>'made_up_date')::date > coalesce(h.latest, date '1900-01-01') + 45
               and fl.detail ? 'document') as filing_known,
       exists (select 1 from user_company uc where uc.company_number = c.company_number and uc.user_id = 1
               and uc.status not in ('new', 'rejected', 'passed')) as in_pipeline,
       (select max(score) from company_best cb where cb.company_number = c.company_number) as score
from company c
left join held h on h.company_number = c.company_number
left join ch_fetch f on f.company_number = c.company_number
where c.last_accounts_date is not null
  and lower(coalesce(c.status, 'active')) = 'active'
  and coalesce(lower(c.accounts_category), '') not like '%%dormant%%'
  and coalesce(lower(c.accounts_category), '') not like '%%no accounts%%'
  and (h.latest is null or c.last_accounts_date - h.latest > %(gap)s)
  /*scope*/
"""

SCOPE = {
    # in a buy box (scored) or in your pipeline
    "targets": """and (exists (select 1 from company_best cb where cb.company_number = c.company_number)
                       or exists (select 1 from user_company uc where uc.company_number = c.company_number
                                  and uc.user_id = 1 and uc.status not in ('new', 'rejected', 'passed')))""",
    "all": "",
}


def reason(r: dict) -> tuple[str, str]:
    """(key, plain explanation) for why a company's newer years are missing."""
    checked = r.get("ch_checked")
    if not checked or checked.date() < r["last_accounts_date"]:
        return ("not_checked", "Not checked with Companies House since its newer accounts were filed "
                               "(filed as PDF, or in a bulk month that didn't load)")
    if r.get("pdf_failed") or r.get("pdf_closed"):
        return ("pdf_unreadable", "Filed as PDF, which couldn't be read (see the PDF check on the Data page)")
    if r.get("filing_known"):
        return ("pdf_waiting", "Filed as PDF and waiting for the PDF reader")
    return ("no_document", "Companies House lists no readable document for the newer accounts")


def find(conn, scope: str = "targets", limit: int | None = None) -> list[dict]:
    sql = GAP_SQL.replace("/*scope*/", SCOPE.get(scope, SCOPE["targets"]))
    sql += " order by in_pipeline desc, score desc nulls last, c.last_accounts_date desc"
    if limit:
        sql += f" limit {int(limit)}"
    out = []
    for r in conn.execute(sql, {"gap": GAP_DAYS}).fetchall():
        key, why = reason(r)
        out.append({**r, "reason": key, "why": why})
    return out


def summary(conn, scope: str = "targets") -> dict:
    rows = find(conn, scope)
    by: dict[str, int] = {}
    for r in rows:
        by[r["reason"]] = by.get(r["reason"], 0) + 1
    keep = ("company_number", "name", "last_accounts_date", "latest_held", "reason", "why", "score", "in_pipeline")
    return {"total": len(rows), "by_reason": by, "examples": [{k: r[k] for k in keep} for r in rows[:25]]}


def fill(conn, progress=None, limit: int = 300) -> dict:
    """Check the companies not looked at since their newer accounts were filed
    with Companies House: years filed as data are fetched there and then, years
    filed as PDF go to the PDF reader. Pipeline first, then the best scores."""
    from . import chapi

    if not chapi.enabled():
        raise chapi.NoKey("Add your Companies House API key (CH_API_KEY in the stack) to fill missing years")
    todo = [r for r in find(conn, "targets") if r["reason"] == "not_checked"][:limit]
    added = errors = 0
    for i, r in enumerate(todo):
        if progress:
            progress(i / max(len(todo), 1), f"Checking {i + 1:,} of {len(todo):,} with Companies House: {r['name']}")
        try:
            res = chapi.fetch(conn, r["company_number"], people=False)
            added += int(res.get("accounts_added") or 0)
            conn.commit()
        except Exception:
            conn.rollback()
            errors += 1
    left = len([r for r in find(conn, "targets") if r["reason"] == "not_checked"])
    return {"checked": len(todo), "years_added_from_data": added, "errors": errors, "still_to_check": left}


HOLDCO_SQL = """
-- Holding companies (on the UK register) behind your targets whose owners aren't
-- on record here: looking them up fetches their owner records, shareholder list
-- and directors, which usually shows who really owns the target.
select distinct on (hc.company_number) hc.company_number as holdco, hc.name as holdco_name, o.company_number as target
from company_ownership o
cross join lateral jsonb_array_elements(o.ultimate_owners) u
join company hc on hc.company_number = u->>'reg'
left join ch_fetch f on f.company_number = hc.company_number
where 'holdco_unresolved' = any(o.flags) and coalesce((u->>'unresolved')::boolean, false)
  and (exists (select 1 from company_best cb where cb.company_number = o.company_number)
       or exists (select 1 from user_company uc where uc.company_number = o.company_number and uc.user_id = 1
                  and uc.status not in ('new', 'rejected', 'passed')))
  and (f.fetched_at is null or f.fetched_at < now() - interval '90 days')
order by hc.company_number
"""


def holdcos_to_look_up(conn) -> list[dict]:
    return conn.execute(HOLDCO_SQL).fetchall()


def look_up_holdcos(conn, progress=None, limit: int = 200) -> dict:
    """Fetch each such holding company from Companies House, then reclassify owners."""
    from . import chapi
    from .fetch import reclassify_owners

    if not chapi.enabled():
        raise chapi.NoKey("Add your Companies House API key (CH_API_KEY in the stack) to look up holding companies")
    todo = holdcos_to_look_up(conn)[:limit]
    done = 0
    for i, r in enumerate(todo):
        if progress:
            progress(0.9 * i / max(len(todo), 1), f"Looking up {i + 1:,} of {len(todo):,}: {r['holdco_name']}")
        try:
            chapi.fetch(conn, r["holdco"], people=False)
            conn.commit()
            done += 1
        except Exception:
            conn.rollback()
    if done:
        if progress:
            progress(0.92, "Reclassifying owners with what was found")
        reclassify_owners(conn)
    return {"looked_up": done, "left": max(0, len(holdcos_to_look_up(conn)))}
