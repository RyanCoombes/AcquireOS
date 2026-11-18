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

# /*held*/ is how the latest year held is found: for your targets, one index look-up per company
# (HELD_EACH); only for the whole register is every row of financial_period grouped (HELD_ALL),
# which takes minutes on the Pi and used to run each time the Data page opened.
HELD_EACH = """left join lateral (select max(fp.period_end) as latest from financial_period fp
                                 where fp.company_number = c.company_number and not fp.period_inferred) h on true"""
HELD_ALL = """left join (select company_number, max(period_end) as latest
                         from financial_period where not period_inferred group by company_number) h
                     on h.company_number = c.company_number"""
GAP_SQL = """
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
from /*from*/company c
/*held*/
left join ch_fetch f on f.company_number = c.company_number
where c.last_accounts_date is not null
  and lower(coalesce(c.status, 'active')) = 'active'
  and coalesce(lower(c.accounts_category), '') not like '%%dormant%%'
  and coalesce(lower(c.accounts_category), '') not like '%%no accounts%%'
  and (h.latest is null or c.last_accounts_date - h.latest > %(gap)s)
  /*scope*/
"""

# "targets": in a buy box (scored) or in your pipeline. The query starts from those companies,
# so it never walks the whole register.
SCOPE_FROM = {
    "targets": """(select company_number from company_best
                   union select company_number from user_company
                         where user_id = 1 and status not in ('new', 'rejected', 'passed')) sc
                  join company c on c.company_number = sc.company_number""",
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
    start = SCOPE_FROM.get(scope, SCOPE_FROM["targets"])
    sql = (GAP_SQL.replace("/*from*/company c", start.strip() if start else "company c")
           .replace("/*held*/", HELD_EACH if start else HELD_ALL).replace("/*scope*/", ""))
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


# Whose shareholder list still needs reading: missing, or older than their newest
# statement that could list one (filings not fetched yet count as needing it);
# not retried for six months after nothing was found.
_SH_NEEDS = """
  lower(coalesce(c.status, 'active')) = 'active'
  and coalesce((select max(as_at) from shareholder s where s.company_number = c.company_number), date '1900-01-01')
      < coalesce((select max(coalesce(nullif(f.detail->>'made_up_date', '')::date, f.filed_on)) from filing f
                  where f.company_number = c.company_number
                    and (f.type in ('CS01', 'AR01', 'IN01') or f.type like 'RP04%%')
                    and coalesce(f.description, '') not like '%%no-updates%%'
                    and coalesce(f.detail->>'made_up_date', '') ~ '^(\\d{4}-\\d{2}-\\d{2})?$'),
                 date '2100-01-01')
  and not exists (select 1 from ch_fetch cf where cf.company_number = c.company_number
                  and cf.shareholders_from = 'none found' and cf.fetched_at > now() - interval '180 days')
"""
_PIPE = """exists (select 1 from user_company uc where uc.company_number = c.company_number and uc.user_id = 1
                   and uc.status not in ('new', 'rejected', 'passed'))"""
_BOX = "exists (select 1 from company_best cb where cb.company_number = c.company_number)"
# The order it works in: your pipeline, your targets, then every other active
# company, largest first (through the staff index, so it never scans millions).
SH_TIERS = [
    ("pipeline", "Pipeline", f"""select c.company_number, c.name,
            exists (select 1 from filing f where f.company_number = c.company_number) as has_filings
        from company c where {_PIPE} and {_SH_NEEDS} order by c.company_number limit %(n)s""", True),
    ("targets", "Targets", f"""select c.company_number, c.name,
            exists (select 1 from filing f where f.company_number = c.company_number) as has_filings
        from company c where {_BOX} and not {_PIPE} and {_SH_NEEDS}
        order by (select max(score) from company_best cb where cb.company_number = c.company_number) desc nulls last,
                 c.company_number limit %(n)s""", True),
    ("all", "Every other active company", f"""select c.company_number, c.name,
            exists (select 1 from filing f where f.company_number = c.company_number) as has_filings
        from company_latest l join company c on c.company_number = l.company_number
        where l.employees is not null and not {_BOX} and not {_PIPE} and {_SH_NEEDS}
        order by l.employees desc nulls last, l.company_number limit %(n)s""", False),
]


def shareholders_to_read(conn, tier: str | None = None, n: int = 100000) -> list[dict]:
    out = []
    for key, _label, sql, _ocr in SH_TIERS:
        if tier in (None, key):
            out += conn.execute(sql, {"n": n}).fetchall()
            if tier is None and key == "targets":
                break  # the quick count covers pipeline and targets
    return out


def shareholder_counts(conn, quick: bool = False) -> dict:
    """What's left in each stage. quick: the pipeline only (cheap enough for a status poll);
    the rest is counted at the end of each batch and kept with the sweep's state."""
    p = len(shareholders_to_read(conn, "pipeline"))
    if quick:
        return {"pipeline": p}
    t = len(shareholders_to_read(conn, "targets"))
    # Every other company, roughly: table estimates, not a count of millions of rows.
    approx = conn.execute("""select greatest(0, (select greatest(reltuples, 0)::bigint from pg_class where relname = 'company_latest')
                                   - (select count(*) from ch_fetch where shareholders_from is not null)) as n""").fetchone()["n"]
    return {"pipeline": p, "targets": t, "all": approx}


def refresh_shareholder_signals(conn, nums: list[str]):
    """The signals that come from shareholder lists (10 or more holders, a known investor,
    a regional funder), for these companies only. The monthly refresh rebuilds everything."""
    if not nums:
        return
    conn.execute(
        """
        with calc as (
            select n as company_number,
                   (select count(*) from shareholder s where s.company_number = n) >= 10 as many,
                   exists (select 1 from shareholder s where s.company_number = n and s.name ~* ao_investor_name_re()
                           and s.as_at = (select max(as_at) from shareholder s2 where s2.company_number = n)) as inv,
                   array(select distinct 'funding:' || f.nation from shareholder sh, ao_regional_funders() f
                         where sh.company_number = n and sh.name ~* f.pattern) as fund
            from unnest(%s::text[]) n
        ), want as (
            select company_number, array_remove(array[case when many then 'many_shareholders' end,
                                                      case when inv then 'investor_shareholder' end], null) || fund as add
            from calc where exists (select 1 from company c where c.company_number = calc.company_number)
        )
        insert into company_signal (company_number, signals)
        select company_number, add from want
        on conflict (company_number) do update set updated_at = now(), signals = array(
            select distinct x from unnest(array_remove(array_remove(company_signal.signals, 'many_shareholders'),
                                                       'investor_shareholder') || excluded.signals) x order by x)
        """, (list(nums),))


def _read_one(conn, r: dict, ocr: bool) -> bool:
    from . import chapi
    num = r["company_number"]
    if r["has_filings"]:
        fl = conn.execute(
            """select type, description, filed_on::text as date, detail->>'made_up_date' as made_up_date,
                      detail->>'document' as document
               from filing where company_number = %s order by filed_on desc nulls last""", (num,)).fetchall()
        src = chapi.read_shareholders(conn, num, [dict(x) for x in fl], ocr=ocr)
    else:
        chapi.fetch(conn, num)
        src = conn.execute("select shareholders_from from ch_fetch where company_number = %s", (num,)).fetchone()
        src = src and src["shareholders_from"] if src and src["shareholders_from"] != "none found" else None
    if src:
        conn.execute("update ch_fetch set shareholders_from = %s where company_number = %s", (src, num))
    else:
        conn.execute("""insert into ch_fetch (company_number, fetched_at, shareholders_from) values (%s, now(), 'none found')
                        on conflict (company_number) do update set shareholders_from = 'none found', fetched_at = now()
                        where ch_fetch.shareholders_from is null or ch_fetch.shareholders_from = 'none found'""", (num,))
    return bool(src)


def read_shareholder_batch(conn, job=None, batch: int = 500) -> dict:
    """One batch: up to `batch` companies, pipeline first, then targets, then every
    other active company. `job` (anything with stage() and progress()) is told where
    it has got to and may stop it. Returns what's left, so the next batch can follow."""
    from . import chapi, scoring
    from .fetch import log

    if not chapi.enabled():
        raise chapi.NoKey("Add your Companies House API key (CH_API_KEY in the stack) to read shareholder lists")
    done = 0
    found: list[str] = []
    try:
        for key, label, sql, ocr in SH_TIERS:
            if done >= batch:
                break
            todo = conn.execute(sql, {"n": batch - done}).fetchall()
            if not todo:
                continue
            if job:
                job.stage(label)
            for i, r in enumerate(todo):
                if job:
                    job.progress(i / len(todo), f"{label}: {i + 1:,} of {len(todo):,} in this batch ({r['name']})")
                try:
                    if _read_one(conn, r, ocr):
                        found.append(r["company_number"])
                    conn.commit()
                except chapi.NoKey:
                    raise
                except Exception as e:
                    conn.rollback()
                    log(f"Shareholder list for {r['company_number']} not read: {str(e).splitlines()[0][:200]}")
                    # Looked at again in a week, not at the head of every batch.
                    conn.execute("""insert into ch_fetch (company_number, fetched_at, shareholders_from)
                                    values (%s, now() - interval '173 days', 'none found')
                                    on conflict (company_number) do update set shareholders_from = 'none found',
                                      fetched_at = now() - interval '173 days'
                                    where ch_fetch.shareholders_from is null or ch_fetch.shareholders_from = 'none found'""",
                                 (r["company_number"],))
                    conn.commit()
                done += 1
    finally:
        if found:  # only the companies read, not the whole register
            refresh_shareholder_signals(conn, found)
            conn.commit()
            scored = [r["company_number"] for r in conn.execute(
                "select company_number from company_best where company_number = any(%s)", (found,))]
            scoring.rescore_each(conn, scored)
    return {"checked": done, "lists_found": len(found), "left": shareholder_counts(conn)}


def read_all_shareholders(conn, progress=None, limit: int = 300) -> dict:
    """(Kept for the command line.) One batch of up to `limit`."""
    return read_shareholder_batch(conn, batch=limit)


SWEEP_KEY = "shareholder_sweep"


def sweep_state(conn) -> dict:
    from . import chsync
    st = chsync.get_setting(conn, SWEEP_KEY, None)
    if isinstance(st, dict):
        return st
    from . import chapi
    return {"active": chapi.enabled()}  # on by default (with a Companies House key) until paused


def set_sweep(conn, active: bool) -> dict:
    from datetime import datetime

    from . import chsync
    st = {**sweep_state(conn), "active": active, "changed_at": datetime.now().isoformat(timespec="minutes")}
    chsync.set_setting(conn, SWEEP_KEY, st)
    conn.commit()
    return st


class _SweepProgress:
    """Where the sweep has got to, kept with its state (shown on the Data page). Pausing
    the sweep stops the batch at the next company."""

    def __init__(self, conn):
        self.conn, self.label, self.n = conn, "", 0

    def stage(self, label: str):
        self.label = label

    def progress(self, frac=None, detail=None):
        from . import chsync, jobs
        st = sweep_state(self.conn)
        if not st.get("active"):
            raise jobs.Cancelled("Paused")
        self.n += 1
        if self.n % 5 == 1 and detail:
            chsync.set_setting(self.conn, SWEEP_KEY, {**st, "now": detail})
            self.conn.commit()


def run_shareholder_batch(conn) -> dict:
    """One batch, quietly in the background: it is not a job, so the Companies House
    sync, the PDF reader, clean-ups and jobs you start all carry on alongside it."""
    from datetime import datetime

    from . import chsync, jobs
    from .fetch import log

    try:
        r = read_shareholder_batch(conn, job=_SweepProgress(conn))
    except jobs.Cancelled:
        conn.rollback()
        st = sweep_state(conn)
        chsync.set_setting(conn, SWEEP_KEY, {**st, "now": None})
        conn.commit()
        return {}
    st = sweep_state(conn)
    finished = r["checked"] == 0
    chsync.set_setting(conn, SWEEP_KEY, {
        **st, "checked": int(st.get("checked") or 0) + r["checked"], "found": int(st.get("found") or 0) + r["lists_found"],
        "left": r["left"], "last_batch": datetime.now().isoformat(timespec="minutes"), "now": None,
        "active": bool(st.get("active")) and not finished, "finished": finished})
    conn.commit()
    if r["checked"]:
        log(f"Shareholder lists: checked {r['checked']:,}, found {r['lists_found']:,}")
    return r


def sweep_forever():
    """While the sweep is on: batch after batch, with a short pause, stepping aside for
    bulk loads and scoring."""
    import time

    from . import chapi, chsync, db
    from .fetch import log
    time.sleep(90)
    while True:
        wait = 120
        try:
            with db.conn(dedicated=True) as c:
                if sweep_state(c).get("active") and not chsync.busy(c):
                    r = run_shareholder_batch(c)
                    wait = 10 if r.get("checked") else 120
        except chapi.NoKey:
            wait = 3600
        except Exception as e:
            log(f"Shareholder sweep: {str(e).splitlines()[0][:200]}")
            wait = 300
        time.sleep(wait)
