"""More from Companies House, beyond the company fetch:

- Disqualified directors: each current director of a fetched company is
  searched for once (then every six months) in the disqualified officers
  search, and matched on surname, first name and month and year of birth.
  New disqualifications also arrive on the disqualified-officers stream.
- PSC exemptions (companies listed on a regulated market need not keep an
  owners register), fetched for companies with no owners on the register.
- UK establishments of overseas companies.

A background worker in the scheduler catches up on companies fetched before
these were collected, pipeline first, at the shared API rate. Its progress
shows on the Data page.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime

EXTRAS_VERSION = 1
RECHECK_DAYS = 180


def _name_parts(officer_name: str) -> tuple[str, str]:
    """('SMITH', 'JOHN') from 'SMITH, John Paul' (the officers list format)."""
    if "," in officer_name:
        sur, fore = officer_name.split(",", 1)
    else:
        bits = officer_name.split()
        sur, fore = (bits[-1], " ".join(bits[:-1])) if len(bits) > 1 else (officer_name, "")
    first = (re.sub(r"^(MR|MRS|MS|MISS|DR|SIR|PROF)\.?\s+", "", fore.strip().upper()).split() or [""])[0]
    return sur.strip().upper(), first


def _reason(d: dict) -> str | None:
    r = d.get("reason") or {}
    bits = [(r.get("description_identifier") or "").replace("-", " ").strip(), (r.get("act") or "").replace("-", " ").strip()]
    if r.get("section"):
        bits.append(f"section {r['section']}")
    return ", ".join(b for b in bits if b) or None


def save_disqualified(conn, ident: str, data: dict, source: str):
    """Store one disqualified officer record (from the API or the stream)."""
    kind = "corporate" if ident.startswith("corporate") or data.get("kind", "").endswith("corporate") else "natural"
    sur = (data.get("surname") or "").upper() or None
    fore = (data.get("forename") or "").upper() or None
    name = data.get("name") or " ".join(x for x in (data.get("forename"), data.get("other_forenames"), data.get("surname")) if x) or "?"
    dob = data.get("date_of_birth")
    try:
        dob = date.fromisoformat(dob) if dob else None
    except ValueError:
        dob = None
    dq = [{"from": d.get("disqualified_from"), "until": d.get("disqualified_until"), "reason": _reason(d),
           "companies": d.get("company_names") or [], "case": d.get("case_identifier")}
          for d in data.get("disqualifications") or []]
    conn.execute(
        """insert into disqualified_officer (id, kind, name, surname, forename, birth_date, disqualifications, source)
           values (%s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (id) do update set name = excluded.name, surname = excluded.surname, forename = excluded.forename,
             birth_date = excluded.birth_date, disqualifications = excluded.disqualifications, source = excluded.source,
             fetched_at = now()""",
        (ident, kind, name, sur, fore, dob, json.dumps(dq), source))


MATCH_SQL = """
-- A current director matched to a disqualified officer: same surname, same
-- first name, same month and year of birth. The officers list gives no day of birth.
select o.company_number, o.officer_key, o.name, d.id, d.disqualifications
from officer o
join disqualified_officer d on d.kind = 'natural' and upper(d.surname) = upper(trim(split_part(o.name, ',', 1)))
     and d.birth_date is not null and extract(year from d.birth_date) = o.birth_year
     and extract(month from d.birth_date) = o.birth_month
     and split_part(upper(trim(split_part(o.name, ',', 2))), ' ', 1) = split_part(coalesce(d.forename, ''), ' ', 1)
where o.resigned_on is null and o.birth_year is not null {where}
"""


def disqualified_for(conn, company_number: str) -> list[dict]:
    """Current directors of one company who are (or were) disqualified."""
    out = []
    for r in conn.execute(MATCH_SQL.format(where="and o.company_number = %s"), (company_number,)):
        for d in r["disqualifications"] or []:
            out.append({"officer_key": r["officer_key"], "name": r["name"], "disqualified_from": d.get("from"),
                        "disqualified_until": d.get("until"), "reason": d.get("reason"), "company_names": d.get("companies")})
    return out


def check_director(conn, officer_key: str, name: str, birth_year: int | None, birth_month: int | None) -> int:
    """Search the disqualified officers for one director; store any match. Returns matches."""
    from . import chapi

    sur, first = _name_parts(name)
    found = 0
    if sur and birth_year:
        q = f"{first} {sur}".strip()
        res = chapi._get(f"/search/disqualified-officers?q={_quote(q)}&items_per_page=20") or {}
        for it in res.get("items") or []:
            dob = str(it.get("date_of_birth") or "")
            if not dob.startswith(f"{birth_year:04d}-{(birth_month or 0):02d}") or sur not in (it.get("title") or "").upper():
                continue
            link = ((it.get("links") or {}).get("self") or "").strip("/")
            ident = link.split("disqualified-officers/", 1)[-1] if "disqualified-officers/" in link else None
            if not ident:
                continue
            rec = chapi._get("/" + link) or {}
            if rec:
                save_disqualified(conn, ident, rec, "api")
                found += 1
    conn.execute("""insert into officer_disq_check (officer_key, found) values (%s, %s)
                    on conflict (officer_key) do update set checked_at = now(), found = excluded.found""", (officer_key, found))
    return found


def _quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


def company_extras(conn, num: str, profile: dict | None = None, psc: list | None = None):
    """PSC exemptions (when no owners are registered) and UK establishments
    (overseas companies) for one company."""
    from . import chapi

    f = conn.execute("select profile, psc from ch_fetch where company_number = %s", (num,)).fetchone()
    if not f:
        return
    if profile is None:
        # Fetched before more of the record was kept: the record again (one request).
        fresh = chapi._get(f"/company/{num}") or {}
        keep = {k: fresh[k] for k in ("accounts", "type", "subtype", "foreign_company_details", "branch_company_details",
                                       "is_community_interest_company", "has_super_secure_pscs", "jurisdiction") if k in fresh}
        if keep:
            conn.execute("update ch_fetch set profile = coalesce(profile, '{}'::jsonb) || %s::jsonb where company_number = %s",
                         (json.dumps(keep), num))
        profile = {**(f["profile"] or {}), **keep}
    psc = psc if psc is not None else (f["psc"] or [])
    exemptions = None
    if not [p for p in psc if not p.get("ceased_on")]:
        res = chapi._get(f"/company/{num}/exemptions") or {}
        exemptions = []
        for kind, v in (res.get("exemptions") or {}).items():
            for it in (v or {}).get("items") or []:
                exemptions.append({"kind": (v.get("exemption_type") or kind).replace("-", " ").replace("_", " "),
                                   "from": it.get("exempt_from"), "to": it.get("exempt_to")})
    est = None
    if (profile.get("type") or "").startswith("oversea"):
        res = chapi._get(f"/company/{num}/uk-establishments") or {}
        est = [{"company_number": i.get("company_number"), "company_name": i.get("company_name"),
                "status": i.get("company_status"), "locality": i.get("locality")} for i in res.get("items") or []]
    conn.execute("""update ch_fetch set exemptions = %s, uk_establishments = %s, extras_version = %s
                    where company_number = %s""",
                 (json.dumps(exemptions) if exemptions is not None else None,
                  json.dumps(est) if est is not None else None, EXTRAS_VERSION, num))


# Directors still to check: current directors of fetched companies, never
# checked or checked over six months ago; your pipeline first, then best scores.
_DIRECTORS_TODO = """
from officer o
join ch_fetch f on f.company_number = o.company_number
left join officer_disq_check k on k.officer_key = o.officer_key
where o.resigned_on is null and o.birth_year is not null and coalesce(o.role, '') like '%%director%%'
  and coalesce(o.role, '') not like 'corporate%%'
  and (k.officer_key is null or k.checked_at < now() - interval '{days} days')
""".format(days=RECHECK_DAYS)


def directors_todo(conn, limit: int) -> list[dict]:
    return conn.execute(
        """select * from (select distinct on (o.officer_key) o.officer_key, o.name, o.birth_year, o.birth_month,
                  exists (select 1 from user_company uc where uc.company_number = o.company_number and uc.user_id = 1
                          and uc.status not in ('new', 'passed', 'rejected')) as mine,
                  (select max(score) from company_best cb where cb.company_number = o.company_number) as score
           """ + _DIRECTORS_TODO + """ order by o.officer_key) t
           order by mine desc, score desc nulls last limit %s""", (limit,)).fetchall()


def companies_todo(conn, limit: int) -> list[str]:
    return [r["company_number"] for r in conn.execute(
        """select f.company_number from ch_fetch f where f.extras_version < %s and f.profile is not null
           order by exists (select 1 from user_company uc where uc.company_number = f.company_number and uc.user_id = 1
                            and uc.status not in ('new', 'passed', 'rejected')) desc,
                    (select max(score) from company_best cb where cb.company_number = f.company_number) desc nulls last
           limit %s""", (EXTRAS_VERSION, limit))]


def status(conn) -> dict:
    from . import chsync

    d = conn.execute("""select count(distinct o.officer_key) as total,
                               count(distinct o.officer_key) filter (where k.officer_key is not null
                                     and k.checked_at >= now() - interval '%s days') as checked
                        from officer o join ch_fetch f on f.company_number = o.company_number
                        left join officer_disq_check k on k.officer_key = o.officer_key
                        where o.resigned_on is null and o.birth_year is not null and coalesce(o.role, '') like '%%director%%'
                          and coalesce(o.role, '') not like 'corporate%%'""" % RECHECK_DAYS).fetchone()
    found = conn.execute("select count(distinct (company_number, officer_key)) as n from (" +
                         MATCH_SQL.format(where="") + ") m").fetchone()["n"]
    c = conn.execute("select count(*) as total, count(*) filter (where extras_version >= %s) as done from ch_fetch "
                     "where profile is not null", (EXTRAS_VERSION,)).fetchone()
    known = conn.execute("select count(*) as n from disqualified_officer").fetchone()["n"]
    return {"directors_total": d["total"], "directors_checked": d["checked"], "disqualified_found": found,
            "disqualified_known": known, "companies_total": c["total"], "companies_done": c["done"],
            "paused": bool(chsync.get_setting(conn, "extras_paused", False))}


def run_forever():
    """Scheduler thread: catch up on director checks and company extras."""
    from . import chapi, chsync, db

    def log(msg):
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [ch-extras] {msg}", flush=True)

    log("started")
    while True:
        try:
            if not chapi.enabled():
                time.sleep(600)
                continue
            with db.conn(dedicated=True) as c:
                if c.execute("select to_regclass('officer_disq_check') as t").fetchone()["t"] is None \
                        or chsync.busy(c) or chsync.get_setting(c, "extras_paused", False):
                    time.sleep(300)
                    continue
                did = 0
                for r in directors_todo(c, 10):
                    n = check_director(c, r["officer_key"], r["name"], r["birth_year"], r["birth_month"])
                    c.commit()
                    did += 1
                    if n:
                        log(f"{r['name']}: {n} disqualification record(s)")
                for num in companies_todo(c, 5):
                    company_extras(c, num)
                    c.commit()
                    did += 1
                if not did:
                    time.sleep(900)
        except Exception as e:
            log(f"error: {e}")
            time.sleep(300)
