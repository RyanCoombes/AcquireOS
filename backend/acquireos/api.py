"""HTTP API and static front end."""
from __future__ import annotations

import base64
import csv
import io
import secrets
from contextlib import asynccontextmanager
import json
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config, db, scoring, valuation
from .importers import companies as company_importer
from .importers import notes as notes_importer
from .importers.notes import STATUS_LABELS, STATUSES
from .normalise import ADDRESS_FLAG_LABELS
from .ownership import TYPE_LABELS
from .ownership import rebuild as rebuild_ownership

@asynccontextmanager
async def lifespan(_app):
    db.migrate()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AcquireOS", version=__version__, lifespan=lifespan)
UID = config.DEFAULT_USER_ID


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional password. Set APP_PASSWORD to require it (always do this
    if the app is reachable from outside your home network)."""
    if not config.APP_PASSWORD or request.url.path == "/api/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            user, pw = "", ""
        if secrets.compare_digest(user, config.APP_USER) and secrets.compare_digest(pw, config.APP_PASSWORD):
            return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AcquireOS"'})


def _rows(sql, params=()):
    with db.conn() as c:
        return c.execute(sql, params).fetchall()


@app.get("/api/health")
def health():
    _rows("select 1")
    return {"ok": True, "version": __version__}


@app.get("/api/meta")
def meta():
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        counts = c.execute(
            """select (select count(*) from company) as companies,
                      (select count(*) from score where buy_box_id = %s and not excluded) as in_scope,
                      (select count(*) from user_company where user_id = %s and status not in ('new', 'rejected', 'passed')) as tracked,
                      (select count(*) from company_person) as owner_records,
                      (select max(finished_at) from import_run) as last_import,
                      (select count(distinct company_number) from company_change
                         where detected_at > now() - interval '30 days') as changed_30d""",
            (bb["id"], UID),
        ).fetchone()
        regions = [r["region"] for r in c.execute("select distinct region from company where region is not null order by 1")]
        tiers = [r["review_tier"] for r in c.execute("select distinct review_tier from company where review_tier is not null order by 1")]
        company_statuses = [r["status"] for r in c.execute("select status, count(*) from company where status is not null group by 1 order by 2 desc")]
    return {
        "version": __version__,
        "statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in STATUSES],
        "ownership_types": [{"value": k, "label": v} for k, v in TYPE_LABELS.items()],
        "address_flags": ADDRESS_FLAG_LABELS,
        "regions": regions,
        "tiers": tiers,
        "company_statuses": company_statuses,
        "counts": counts,
        "buy_box": {"id": bb["id"], "name": bb["name"]},
    }


SORTS = {
    "score": "s.score", "name": "c.name", "staff": "l.employees", "revenue": "e.revenue_high",
    "age": "o.oldest_birth_year", "years": "c.incorporation_date", "net_assets": "l.net_assets",
    "updated": "uc.updated_at", "status": "uc.status", "value": "s.value_high",
    "changed": "ch.last_change",
}


@app.get("/api/companies")
def companies(
    q: str | None = None, region: str | None = None, tier: str | None = None, status: str | None = None,
    ownership: str | None = None, min_staff: int | None = None, max_staff: int | None = None,
    min_score: float | None = None, min_owner_age: int | None = None, include_excluded: bool = False,
    flag: str | None = None, sort: str = "score", dir: str = "desc", limit: int = 100, offset: int = 0,
    company_status: str | None = None, sic: str | None = None, changed_days: int | None = None,
    change_kind: str | None = None, min_value: float | None = None, max_value: float | None = None,
    min_years: int | None = None,
):
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        where, params = ["true"], {"bb": bb["id"], "uid": UID}
        if q:
            where.append("(c.name ilike %(q)s or c.company_number ilike %(q)s or c.postcode ilike %(q)s)")
            params["q"] = f"%{q.strip()}%"
        if region:
            where.append("c.region = %(region)s"); params["region"] = region
        if tier:
            where.append("c.review_tier = %(tier)s"); params["tier"] = tier
        if status:
            if status == "new":
                where.append("coalesce(uc.status, 'new') = 'new'")
            else:
                where.append("uc.status = %(status)s"); params["status"] = status
        if ownership:
            where.append("coalesce(o.ownership_type, 'unknown') = %(own)s"); params["own"] = ownership
        if min_staff is not None:
            where.append("l.employees >= %(mins)s"); params["mins"] = min_staff
        if max_staff is not None:
            where.append("l.employees <= %(maxs)s"); params["maxs"] = max_staff
        if min_score is not None:
            where.append("s.score >= %(minsc)s"); params["minsc"] = min_score
        if min_owner_age is not None:
            where.append("o.oldest_birth_year <= %(by)s"); params["by"] = date.today().year - min_owner_age
        if flag:
            where.append("(%(flag)s = any(o.flags) or c.address_flag = %(flag)s)"); params["flag"] = flag
        if company_status:
            where.append("c.status = %(cstatus)s"); params["cstatus"] = company_status
        if sic:
            where.append("exists (select 1 from unnest(c.sic_codes) x where x like %(sic)s)")
            params["sic"] = sic.strip().rstrip("*") + "%"
        if changed_days:
            where.append("ch.last_change > now() - make_interval(days => %(cdays)s)"); params["cdays"] = changed_days
        if change_kind:
            where.append(
                "exists (select 1 from company_change x where x.company_number = c.company_number and x.kind = %(ckind)s"
                + (" and x.detected_at > now() - make_interval(days => %(cdays)s))" if changed_days else ")"))
            params["ckind"] = change_kind
        if min_value is not None:
            where.append("s.value_high >= %(minv)s"); params["minv"] = min_value
        if max_value is not None:
            where.append("s.value_low <= %(maxv)s"); params["maxv"] = max_value
        if min_years is not None:
            where.append("c.incorporation_date <= current_date - make_interval(years => %(miny)s)"); params["miny"] = min_years
        if not include_excluded:
            where.append("not coalesce(s.excluded, false)")
        order = SORTS.get(sort, "s.score")
        direction = "asc" if dir == "asc" else "desc"
        sql = f"""
            with latest as (
                select distinct on (company_number) company_number, employees, net_assets, turnover, period_end
                from financial_period where not period_inferred order by company_number, period_end desc
            )
            select c.company_number, c.name, c.region, c.postcode, c.review_tier, c.incorporation_date,
                   c.sic_codes, c.address_flag, c.status as company_status,
                   l.employees, l.net_assets, l.period_end,
                   e.revenue_low, e.revenue_high, e.basis as revenue_basis,
                   o.ownership_type, o.oldest_birth_year, o.flags,
                   s.score, s.coverage, s.excluded, s.exclusion, s.value_low, s.value_high, s.value_basis,
                   coalesce(uc.status, 'new') as status, uc.rating, uc.next_action, uc.next_action_on,
                   ch.last_change, ch.last_kinds,
                   (select array_agg(employees order by period_end) from (
                        select period_end, employees from financial_period t
                        where t.company_number = c.company_number and not t.period_inferred and t.employees is not null
                        order by period_end desc limit 6) z) as staff_trend,
                   count(*) over () as total
            from company c
            left join latest l on l.company_number = c.company_number
            left join estimate e on e.company_number = c.company_number
            left join company_ownership o on o.company_number = c.company_number
            left join score s on s.company_number = c.company_number and s.buy_box_id = %(bb)s
            left join user_company uc on uc.company_number = c.company_number and uc.user_id = %(uid)s
            left join (
                select company_number, max(detected_at) as last_change,
                       array_agg(distinct kind) filter (where detected_at > now() - interval '90 days') as last_kinds
                from company_change group by company_number
            ) ch on ch.company_number = c.company_number
            where {' and '.join(where)}
            order by {order} {direction} nulls last, c.name
            limit %(limit)s offset %(offset)s
        """
        params.update(limit=min(limit, 1000), offset=offset)
        rows = c.execute(sql, params).fetchall()
    total = rows[0]["total"] if rows else 0
    for r in rows:
        r.pop("total", None)
    return {"total": total, "rows": rows}


@app.get("/api/companies/{num}")
def company(num: str):
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        row = c.execute("select * from company where company_number = %s", (num,)).fetchone()
        if not row:
            raise HTTPException(404, "Company not found")
        fin = c.execute(
            "select * from financial_period where company_number = %s order by period_end", (num,)
        ).fetchall()
        est = c.execute("select * from estimate where company_number = %s", (num,)).fetchone()
        own = c.execute("select * from company_ownership where company_number = %s", (num,)).fetchone()
        people = c.execute(
            """select p.name, p.kind, p.birth_year, p.birth_month, p.country_registered, p.registration_number,
                      cp.role, cp.natures, cp.notified_on, cp.ceased_on
               from company_person cp join person p on p.id = cp.person_id
               where cp.company_number = %s order by cp.ceased_on nulls first, cp.notified_on desc""",
            (num,),
        ).fetchall()
        links = _links_for(c, num)
        sc = c.execute(
            "select * from score where company_number = %s and buy_box_id = %s", (num, bb["id"])
        ).fetchone()
        state = c.execute(
            "select * from user_company where company_number = %s and user_id = %s", (num, UID)
        ).fetchone()
        notes = c.execute(
            "select id, body, source, created_at from user_note where company_number = %s and user_id = %s order by created_at desc, id desc",
            (num, UID),
        ).fetchall()
        research = c.execute(
            "select * from research where company_number = %s order by retrieved_at desc", (num,)
        ).fetchall()
        outreach = c.execute(
            "select * from outreach where company_number = %s and user_id = %s order by happened_on desc, id desc",
            (num, UID),
        ).fetchall()
        changes = c.execute(
            """select ch.*, r.filename from company_change ch left join import_run r on r.id = ch.import_run_id
               where ch.company_number = %s order by ch.detected_at desc, ch.id desc limit 100""",
            (num,),
        ).fetchall()
        facts = (scoring.load_facts(c, num) or [{}])[0]
        override = (state or {}).get("valuation") or {}
        a = valuation.assumptions(bb["criteria"], override)
        val = {**valuation.value(facts, a), "assumptions": a, "defaults": valuation.assumptions(bb["criteria"]),
               "override": override, "cash": facts.get("cash")}
    return {
        "changes": changes, "valuation": val,
        "company": row, "financials": fin, "estimate": est, "ownership": own, "people": people,
        "links": links, "score": sc, "state": state or {"status": "new", "rating": None, "tags": []},
        "notes": notes, "research": research, "outreach": outreach,
    }


def _links_for(c, num):
    return c.execute(
        """select l.kind, l.via, l.confidence, l.evidence,
                  case when l.a = %(n)s then l.b else l.a end as other,
                  case when l.a = %(n)s then coalesce(l.b_name, cb.name) else ca.name end as other_name,
                  case when l.kind = 'owned_by' and l.a = %(n)s then 'parent'
                       when l.kind = 'owned_by' then 'subsidiary' else 'peer' end as direction,
                  exists(select 1 from company x where x.company_number =
                         case when l.a = %(n)s then l.b else l.a end) as in_list
           from company_link l
           left join company ca on ca.company_number = l.a
           left join company cb on cb.company_number = l.b
           where l.a = %(n)s or l.b = %(n)s
           order by case l.confidence when 'confirmed' then 0 when 'likely' then 1 else 2 end, l.kind""",
        {"n": num},
    ).fetchall()


class StateIn(BaseModel):
    status: str | None = None
    rating: int | None = None
    next_action: str | None = None
    next_action_on: date | None = None
    tags: list[str] | None = None
    valuation: dict | None = None
    clear_rating: bool = False


@app.put("/api/companies/{num}/state")
def set_state(num: str, body: StateIn):
    if body.status and body.status not in STATUSES:
        raise HTTPException(400, "Unknown status")
    if body.rating is not None and not 1 <= body.rating <= 5:
        raise HTTPException(400, "Rating must be 1 to 5")
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise HTTPException(404, "Company not found")
        c.execute(
            "insert into user_company (user_id, company_number) values (%s, %s) on conflict do nothing",
            (UID, num),
        )
        sets, params = ["updated_at = now()"], []
        fields = body.model_dump(exclude_unset=True)
        for k in ("status", "rating", "next_action", "next_action_on", "tags"):
            if k in fields:
                sets.append(f"{k} = %s")
                params.append(fields[k])
        if "valuation" in fields:
            clean = {k: float(v) for k, v in (fields["valuation"] or {}).items()
                     if k in valuation.DEFAULTS and v not in (None, "")}
            sets.append("valuation = %s")
            params.append(json.dumps(clean))
        if body.clear_rating:
            sets.append("rating = null")
        c.execute(
            f"update user_company set {', '.join(sets)} where user_id = %s and company_number = %s",
            (*params, UID, num),
        )
        return c.execute(
            "select * from user_company where user_id = %s and company_number = %s", (UID, num)
        ).fetchone()


class NoteIn(BaseModel):
    body: str


@app.post("/api/companies/{num}/notes")
def add_note(num: str, note: NoteIn):
    import hashlib
    import time

    text = note.body.strip()
    if not text:
        raise HTTPException(400, "Note is empty")
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise HTTPException(404, "Company not found")
        h = hashlib.sha256(f"{time.time_ns()}:{text}".encode()).hexdigest()
        return c.execute(
            """insert into user_note (user_id, company_number, body, source, content_hash)
               values (%s, %s, %s, 'app', %s) returning id, body, source, created_at""",
            (UID, num, text, h),
        ).fetchone()


class ResearchIn(BaseModel):
    kind: str = "other"
    content: str
    source_url: str | None = None
    source_label: str | None = None


@app.post("/api/companies/{num}/research")
def add_research(num: str, r: ResearchIn):
    if not r.content.strip():
        raise HTTPException(400, "Empty")
    with db.conn() as c:
        row = c.execute(
            """insert into research (company_number, kind, content, source_url, source_label, created_by)
               values (%s, %s, %s, %s, %s, 'me') returning *""",
            (num, r.kind, r.content.strip(), r.source_url, r.source_label),
        ).fetchone()
        scoring.rescore(c, company_number=num)
        return row


class OutreachIn(BaseModel):
    company_number: str | None = None
    contact_name: str
    contact_role: str = "owner"
    channel: str | None = None
    summary: str | None = None
    happened_on: date | None = None
    next_action: str | None = None
    next_action_on: date | None = None


@app.get("/api/outreach")
def outreach_list():
    return _rows(
        """select o.*, c.name as company_name from outreach o
           left join company c on c.company_number = o.company_number
           where o.user_id = %s order by o.happened_on desc, o.id desc""",
        (UID,),
    )


@app.post("/api/outreach")
def outreach_add(o: OutreachIn):
    with db.conn() as c:
        return c.execute(
            """insert into outreach (user_id, company_number, contact_name, contact_role, channel, summary,
                   happened_on, next_action, next_action_on)
               values (%s, %s, %s, %s, %s, %s, coalesce(%s, current_date), %s, %s) returning *""",
            (UID, o.company_number, o.contact_name, o.contact_role, o.channel, o.summary,
             o.happened_on, o.next_action, o.next_action_on),
        ).fetchone()


@app.get("/api/dashboard")
def dashboard():
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        p = {"bb": bb["id"], "uid": UID}
        head = c.execute(
            """select
                 (select count(*) from company) as companies,
                 (select count(*) from score where buy_box_id = %(bb)s and not excluded) as in_scope,
                 (select count(*) from score where buy_box_id = %(bb)s and not excluded and score >= 70) as strong,
                 (select count(*) from user_company where user_id = %(uid)s and status not in ('new','rejected','passed')) as pipeline,
                 (select count(*) from user_company where user_id = %(uid)s and status in ('contacted','in_talks')) as talking,
                 (select count(distinct company_number) from company_change where detected_at > now() - interval '7 days') as changed_7d,
                 (select count(distinct company_number) from company_change where detected_at > now() - interval '30 days') as changed_30d,
                 (select count(*) from company_change where kind = 'status' and detected_at > now() - interval '30 days') as status_30d,
                 (select percentile_cont(0.5) within group (order by extract(year from current_date) - o.oldest_birth_year)
                    from company_ownership o join score s on s.company_number = o.company_number and s.buy_box_id = %(bb)s
                    where not s.excluded and o.oldest_birth_year is not null) as median_owner_age,
                 (select count(*) from company_ownership o join score s on s.company_number = o.company_number
                    and s.buy_box_id = %(bb)s where not s.excluded and o.oldest_birth_year <= extract(year from current_date) - 60) as owners_60,
                 (select count(*) from (select company_number from financial_period where not period_inferred
                    group by company_number having count(*) >= 3) h) as with_history,
                 (select sum((value_low + value_high) / 2) from score s join user_company uc on uc.company_number = s.company_number
                    and uc.user_id = %(uid)s where s.buy_box_id = %(bb)s and uc.status not in ('new','rejected','passed')) as pipeline_value""",
            p,
        ).fetchone()
        hist = c.execute(
            """select width_bucket(score, 0, 100.0001, 10) as b, count(*) as n from score
               where buy_box_id = %(bb)s and not excluded group by 1 order by 1""", p).fetchall()
        top = c.execute(
            """with latest as (select distinct on (company_number) company_number, employees from financial_period
                               where not period_inferred order by company_number, period_end desc)
               select c.company_number, c.name, c.region, s.score, s.value_low, s.value_high, l.employees,
                      o.oldest_birth_year, o.ownership_type
               from score s join company c on c.company_number = s.company_number
               left join latest l on l.company_number = c.company_number
               left join company_ownership o on o.company_number = c.company_number
               left join user_company uc on uc.company_number = c.company_number and uc.user_id = %(uid)s
               where s.buy_box_id = %(bb)s and not s.excluded and coalesce(uc.status, 'new') = 'new'
               order by s.score desc, s.coverage desc limit 8""", p).fetchall()
        recent = c.execute(
            """select ch.company_number, ch.kind, ch.field, ch.old_value, ch.new_value, ch.detected_at, c.name,
                      coalesce(uc.status, 'new') as status
               from company_change ch join company c on c.company_number = ch.company_number
               left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
               left join score s on s.company_number = ch.company_number and s.buy_box_id = %(bb)s
               where ch.detected_at > now() - interval '30 days' and not coalesce(s.excluded, false)
                 and ch.kind <> 'new_company'
               order by (coalesce(uc.status,'new') <> 'new') desc, (ch.kind = 'status') desc, ch.detected_at desc
               limit 8""", p).fetchall()
        due = c.execute(
            """select uc.company_number, c.name, uc.status, uc.next_action, uc.next_action_on
               from user_company uc join company c on c.company_number = uc.company_number
               where uc.user_id = %(uid)s and uc.next_action_on is not null and uc.status not in ('rejected','passed')
               order by uc.next_action_on limit 6""", p).fetchall()
        funnel = c.execute("select status, count(*) as n from user_company where user_id = %(uid)s group by 1", p).fetchall()
        ownership = c.execute(
            """select coalesce(o.ownership_type,'unknown') as type, count(*) as n from score s
               left join company_ownership o on o.company_number = s.company_number
               where s.buy_box_id = %(bb)s and not s.excluded group by 1 order by 2 desc""", p).fetchall()
        freshness = c.execute(
            "select kind, max(finished_at) as last from import_run where finished_at is not null group by kind").fetchall()
        trend = c.execute(
            """select extract(year from period_end)::int as year, count(distinct company_number) as companies,
                      percentile_cont(0.5) within group (order by employees) as median_staff,
                      sum(employees) as total_staff
               from financial_period where not period_inferred and employees is not null
                 and company_number in (select company_number from score where buy_box_id = %(bb)s and not excluded)
               group by 1 having count(*) >= 3 order by 1""", p).fetchall()
    fmap = {r["status"]: r["n"] for r in funnel}
    # Recent years are only partly filed (accounts are due up to nine months
    # after the year end), so drop years with under half the usual coverage.
    peak = max((t["companies"] for t in trend), default=0)
    trend = [t for t in trend if t["companies"] >= peak * 0.5]
    return {
        "head": head, "score_hist": [{"b": i, "n": next((h["n"] for h in hist if h["b"] == i), 0)} for i in range(1, 11)],
        "top": top, "recent": recent, "due": due, "ownership": ownership,
        "funnel": [{"status": st, "label": STATUS_LABELS[st], "n": fmap.get(st, 0)} for st in STATUSES if st != "new"],
        "freshness": {r["kind"]: r["last"] for r in freshness}, "trend": trend, "refresh": _refresh_state,
        "buy_box": bb["name"],
    }


@app.get("/api/changes")
def changes(days: int = 90, kind: str | None = None, tracked: bool = False, limit: int = 500):
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        where, params = ["ch.detected_at > now() - make_interval(days => %(days)s)"], {"days": days, "uid": UID, "bb": bb["id"], "limit": min(limit, 2000)}
        if kind:
            where.append("ch.kind = %(kind)s"); params["kind"] = kind
        if tracked:
            where.append("coalesce(uc.status, 'new') not in ('new', 'rejected', 'passed')")
        rows = c.execute(
            f"""select ch.id, ch.company_number, ch.kind, ch.field, ch.old_value, ch.new_value, ch.detected_at,
                       c.name, c.status as company_status, coalesce(uc.status, 'new') as status, s.score, s.excluded,
                       r.filename
                from company_change ch join company c on c.company_number = ch.company_number
                left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
                left join score s on s.company_number = ch.company_number and s.buy_box_id = %(bb)s
                left join import_run r on r.id = ch.import_run_id
                where {' and '.join(where)}
                order by ch.detected_at desc, (coalesce(uc.status,'new') <> 'new') desc, s.score desc nulls last
                limit %(limit)s""",
            params,
        ).fetchall()
        summary = c.execute(
            f"""select ch.kind, count(*) as n from company_change ch
                left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
                where ch.detected_at > now() - make_interval(days => %(days)s)
                {"and coalesce(uc.status, 'new') not in ('new', 'rejected', 'passed')" if tracked else ""}
                group by 1 order by 2 desc""",
            params,
        ).fetchall()
    return {"rows": rows, "summary": summary}


@app.get("/api/searches")
def searches():
    return _rows("select * from saved_search where user_id = %s order by name", (UID,))


class SearchIn(BaseModel):
    name: str
    params: dict


@app.post("/api/searches")
def save_search(body: SearchIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Give the search a name")
    params = {k: str(v) for k, v in body.params.items() if v not in (None, "") and k not in ("page",)}
    with db.conn() as c:
        return c.execute(
            """insert into saved_search (user_id, name, params) values (%s, %s, %s)
               on conflict (user_id, name) do update set params = excluded.params returning *""",
            (UID, name, json.dumps(params)),
        ).fetchone()


@app.delete("/api/searches/{sid}")
def delete_search(sid: int):
    with db.conn() as c:
        c.execute("delete from saved_search where id = %s and user_id = %s", (sid, UID))
    return {"ok": True}


@app.get("/api/pipeline")
def pipeline():
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        rows = c.execute(
            """select uc.*, c.name, c.region, s.score,
                      (select max(created_at) from user_note n where n.company_number = uc.company_number) as last_note
               from user_company uc join company c on c.company_number = uc.company_number
               left join score s on s.company_number = uc.company_number and s.buy_box_id = %s
               where uc.user_id = %s and uc.status <> 'new'
               order by uc.next_action_on nulls last, s.score desc nulls last""",
            (bb["id"], UID),
        ).fetchall()
    return {"statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in STATUSES if s != "new"], "rows": rows}


@app.get("/api/reports")
def reports():
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        p = {"bb": bb["id"], "uid": UID}
        latest = """with latest as (select distinct on (company_number) company_number, employees
                    from financial_period where not period_inferred order by company_number, period_end desc)"""
        staff = c.execute(
            latest + """
            select b.band, b.ord, count(l.company_number) as n from (values
              ('0–4',0,0,4),('5–9',1,5,9),('10–19',2,10,19),('20–49',3,20,49),('50–99',4,50,99),('100+',5,100,1000000)) b(band,ord,lo,hi)
            left join latest l on l.employees between b.lo and b.hi
            group by b.band, b.ord order by b.ord""").fetchall()
        score_hist = c.execute(
            """select width_bucket(score, 0, 100, 10) as bucket, count(*) as n from score
               where buy_box_id = %(bb)s and not excluded group by 1 order by 1""", p).fetchall()
        ownership = c.execute(
            """select coalesce(o.ownership_type,'unknown') as type, count(*) as n from company c
               left join company_ownership o on o.company_number = c.company_number group by 1 order by 2 desc""").fetchall()
        regions = c.execute(
            "select coalesce(region, 'Not set') as region, count(*) as n from company group by 1 order by 2 desc limit 12").fetchall()
        tiers = c.execute(
            "select coalesce(review_tier, 'Not set') as tier, count(*) as n from company group by 1 order by 2 desc").fetchall()
        funnel = c.execute(
            "select status, count(*) as n from user_company where user_id = %(uid)s group by 1", p).fetchall()
        exclusions = c.execute(
            """select split_part(exclusion, ' “', 1) as reason, count(*) as n from score
               where buy_box_id = %(bb)s and excluded group by 1 order by 2 desc limit 8""", p).fetchall()
        owner_age = c.execute(
            """select (extract(year from current_date)::int - oldest_birth_year) / 5 * 5 as age, count(*) as n
               from company_ownership where oldest_birth_year is not null group by 1 order by 1""").fetchall()
        flags = c.execute(
            """select f as flag, count(*) as n from company_ownership, unnest(flags) f group by 1 order by 2 desc""").fetchall()
        address_flags = c.execute(
            "select address_flag as flag, count(*) as n from company where address_flag is not null group by 1 order by 2 desc").fetchall()
        imports = c.execute("select * from import_run order by id desc limit 10").fetchall()
    fmap = {r["status"]: r["n"] for r in funnel}
    return {
        "staff": staff, "score_hist": score_hist, "ownership": ownership, "regions": regions,
        "tiers": tiers, "exclusions": exclusions, "owner_age": owner_age, "flags": flags,
        "address_flags": address_flags, "imports": imports,
        "funnel": [{"status": s, "label": STATUS_LABELS[s], "n": fmap.get(s, 0)} for s in STATUSES if s != "new"],
    }


@app.get("/api/links/{num}")
def link_graph(num: str, depth: int = 2):
    """Nodes and edges around one company, up to `depth` hops."""
    depth = max(1, min(depth, 3))
    with db.conn() as c:
        root = c.execute("select company_number, name from company where company_number = %s", (num,)).fetchone()
        if not root:
            raise HTTPException(404, "Company not found")
        nodes = {num: {"id": num, "name": root["name"], "depth": 0, "in_list": True}}
        edges = {}
        frontier = [num]
        for d in range(1, depth + 1):
            nxt = []
            for f in frontier:
                for l in _links_for(c, f):
                    key = tuple(sorted([f, l["other"]])) + (l["kind"], l["via"])
                    if key not in edges:
                        src, dst = (f, l["other"]) if l["direction"] != "subsidiary" else (l["other"], f)
                        edges[key] = {"source": src, "target": dst, "kind": l["kind"], "via": l["via"],
                                      "confidence": l["confidence"], "evidence": l["evidence"]}
                    if l["other"] not in nodes:
                        nodes[l["other"]] = {"id": l["other"], "name": l["other_name"] or l["other"],
                                             "depth": d, "in_list": l["in_list"]}
                        nxt.append(l["other"])
            frontier = nxt[:40]
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


@app.get("/api/buybox")
def get_buybox():
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
    return {"id": bb["id"], "name": bb["name"], "criteria": scoring.merged(bb["criteria"]),
            "defaults": scoring.DEFAULT_CRITERIA}


class BuyBoxIn(BaseModel):
    name: str | None = None
    criteria: dict


@app.put("/api/buybox")
def put_buybox(body: BuyBoxIn):
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        criteria = scoring.merged(body.criteria)
        c.execute(
            "update buy_box set criteria = %s, name = coalesce(%s, name), updated_at = now() where id = %s",
            (json.dumps(criteria), body.name, bb["id"]),
        )
        bb = scoring.active_buy_box(c)
        n = scoring.rescore(c, bb)
    return {"rescored": n, "criteria": criteria}


# ------------------------------------------------------------------ imports

IMPORTERS = {"companies": company_importer, "notes": notes_importer}


@app.post("/api/import/preview")
async def import_preview(kind: str = Form(...), file: UploadFile = File(...), sheet: str | None = Form(None)):
    if kind not in IMPORTERS:
        raise HTTPException(400, "Unknown import type")
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xlsm", ".txt", ".zip"}:
        raise HTTPException(400, "Upload a CSV, zipped CSV or Excel (.xlsx) file")
    token = uuid.uuid4().hex
    dest = config.UPLOAD_DIR / f"{token}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    from .importers.tables import list_sheets

    try:
        result = IMPORTERS[kind].preview(dest, sheet)
    except Exception as e:  # unreadable file
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read the file: {e}")
    sample = [{k: _cell(v) for k, v in row.items()} for row in result["sample"]]
    return {**result, "sample": sample, "token": token, "suffix": suffix, "filename": file.filename,
            "sheets": list_sheets(dest)}


class CommitIn(BaseModel):
    kind: str
    token: str
    suffix: str
    filename: str
    mapping: dict
    sheet: str | None = None
    only_existing: bool = False


@app.post("/api/import/commit")
def import_commit(body: CommitIn):
    if body.kind not in IMPORTERS or not body.token.isalnum():
        raise HTTPException(400, "Bad request")
    path = config.UPLOAD_DIR / f"{body.token}{body.suffix}"
    if not path.exists():
        raise HTTPException(410, "Upload expired. Choose the file again.")
    with db.conn() as c:
        try:
            kwargs = {"only_existing": body.only_existing} if body.kind == "companies" else {}
            result = IMPORTERS[body.kind].run(c, path, mapping=body.mapping, sheet=body.sheet, source=body.filename, **kwargs)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if body.kind == "companies":
            rebuild_ownership(c)
        scoring.rescore(c)
    path.unlink(missing_ok=True)
    return result


_refresh_state = {"running": False, "started": None, "finished": None, "result": None, "error": None}


@app.post("/api/refresh")
def start_refresh(months: int = 1):
    """Start the Companies House download and load in the background."""
    import threading
    from datetime import datetime

    if _refresh_state["running"]:
        raise HTTPException(409, "A refresh is already running")

    def work():
        from . import fetch

        try:
            with db.conn() as c:
                _refresh_state["result"] = fetch.refresh(c, accounts_months=max(1, min(months, 24)))
        except Exception as e:
            _refresh_state["error"] = str(e)
        finally:
            _refresh_state["running"] = False
            _refresh_state["finished"] = datetime.now().isoformat()

    _refresh_state.update(running=True, started=datetime.now().isoformat(), finished=None, result=None, error=None)
    threading.Thread(target=work, daemon=True).start()
    return _refresh_state


@app.get("/api/refresh")
def refresh_status():
    return _refresh_state


@app.get("/api/imports")
def imports():
    return _rows("select * from import_run order by id desc limit 50")


@app.get("/api/export.csv")
def export_csv():
    data = companies(limit=1000, include_excluded=True)["rows"]
    with db.conn() as c:
        more = c.execute("select count(*) as n from company").fetchone()["n"]
    if more > 1000:
        data = []
        offset = 0
        while True:
            chunk = companies(limit=1000, offset=offset, include_excluded=True)["rows"]
            if not chunk:
                break
            data += chunk
            offset += 1000
    buf = io.StringIO()
    if data:
        w = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
        w.writeheader()
        for r in data:
            w.writerow({k: (",".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=acquireos-export.csv"})


def _cell(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


# --------------------------------------------------------------- front end

if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = config.WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.WEB_DIST / "index.html")
