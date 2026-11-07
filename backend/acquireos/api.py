"""HTTP API and static front end."""
from __future__ import annotations

import base64
import csv
import io
import secrets
from contextlib import asynccontextmanager
import json
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi.middleware.gzip import GZipMiddleware
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import enrich, fintrends
from . import __version__, config, db, scoring, stages, valuation
from .importers import companies as company_importer
from .importers import notes as notes_importer
from .importers.notes import STATUS_LABELS, STATUSES
from .normalise import ADDRESS_FLAG_LABELS
from .ownership import TYPE_LABELS
from .ownership import rebuild as rebuild_ownership

@asynccontextmanager
async def lifespan(_app):
    db.migrate()
    with db.conn() as c:
        from . import sic

        sic.seed(c)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # A fresh MCP HTTP app per start: its session manager can only run once.
    manager = _install_mcp()
    async with manager.run():
        yield
    db.close_pool()


app = FastAPI(title="AcquireOS", version=__version__, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)  # company pages and lists are large JSON
UID = config.DEFAULT_USER_ID


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional password (APP_PASSWORD, for people in a browser) and API
    token (API_TOKEN, for Claude over MCP and for scripts)."""
    path = request.url.path
    header = request.headers.get("authorization", "")
    token_ok = bool(config.API_TOKEN) and (
        secrets.compare_digest(header, f"Bearer {config.API_TOKEN}")
        or secrets.compare_digest(request.headers.get("x-api-key", ""), config.API_TOKEN)
    )
    if path.startswith("/mcp"):
        if token_ok or (not config.API_TOKEN and not config.APP_PASSWORD):
            return await call_next(request)
        msg = "Set API_TOKEN on the server and send it as a Bearer token" if not config.API_TOKEN else "Invalid or missing API token"
        return JSONResponse({"error": msg}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    if token_ok or not config.APP_PASSWORD or path == "/api/health":
        return await call_next(request)
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            user, pw = "", ""
        if secrets.compare_digest(user, config.APP_USER) and secrets.compare_digest(pw, config.APP_PASSWORD):
            return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AcquireOS"'})


_CACHE: dict = {}


def cached(key: str, ttl: float, fn):
    """Tiny in-process cache for summary queries that scan millions of rows."""
    import time

    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


# Register-wide summaries (counts over millions of rows) only change when a
# data job runs, so your own edits do not throw them away; jobs clear them.
DATA_KEYS = ("company_count", "sic", "coverage", "meta_data")


def clear_cache(data: bool = True):
    if data:
        _CACHE.clear()
    else:
        for k in [k for k in _CACHE if k not in DATA_KEYS]:
            _CACHE.pop(k, None)


@app.middleware("http")
async def _clear_cache_on_write(request: Request, call_next):
    resp = await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
        # Imports and refreshes change the data itself; other writes only yours.
        clear_cache(data=request.url.path.startswith(("/api/import", "/api/refresh", "/api/buybox")))
    return resp


def _rows(sql, params=()):
    with db.conn() as c:
        return c.execute(sql, params).fetchall()


@app.get("/api/health")
def health():
    _rows("select 1")
    return {"ok": True, "version": __version__}


@app.get("/api/meta")
def meta():
    return cached("meta", 60, _meta)


def _meta_data():
    """The register-wide part of meta: slow on millions of rows, and only
    changed by data jobs (cached until one runs, or an hour)."""
    with db.conn() as c:
        counts = c.execute(
            """select (select ao_rowcount('company')) as companies,
                      (select count(*) from company_best) as in_boxes,
                      (select ao_rowcount('company_person')) as owner_records,
                      (select max(finished_at) from import_run) as last_import,
                      (select count(distinct ch.company_number) from company_change ch
                         join company_best s on s.company_number = ch.company_number
                         where ch.detected_at > now() - interval '30 days') as changed_30d""").fetchone()
        lists = stats_get(c, "meta_lists", compute_meta_lists)
    return {"counts": dict(counts), **lists}


def compute_meta_lists(c) -> dict:
    """Filter choices that come from scanning every company (regions, tiers,
    statuses): stored after each load rather than scanned per visit."""
    return {
        "regions": [r["region"] for r in c.execute("select distinct region from company where region is not null order by 1")],
        "tiers": [r["review_tier"] for r in c.execute("select distinct review_tier from company where review_tier is not null order by 1")],
        "company_statuses": [r["status"] for r in c.execute(
            "select status, count(*) from company where status is not null group by 1 order by 2 desc")],
    }


def _meta():
    d = cached("meta_data", 3600, _meta_data)
    regions, tiers, company_statuses = d["regions"], d["tiers"], d["company_statuses"]
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        counts = {**d["counts"], **c.execute(
            f"""select (select count(*) from user_company where user_id = %(uid)s
                         and status not in ('new', 'rejected', 'passed')) as tracked,
                      -- targets still open: in a buy box, not ruled out or combined into another
                      (select count(*) from company_best cb where not exists (
                         select 1 from user_company uc where uc.company_number = cb.company_number and uc.user_id = %(uid)s
                         and (uc.status in ('rejected', 'passed')))) as in_scope,
                      (select count(*) from company_change ch
                         join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
                         where uc.status not in ('new', 'rejected', 'passed') and {UNREAD_SQL}
                      ) as pipeline_new""",
            {"uid": UID}).fetchone()}
        boxes = [dict(r) for r in c.execute(
            "select id, name, is_active, scored_at from buy_box where user_id = %s order by id", (UID,))]
    return {
        "version": __version__,
        "statuses": [{"value": s["value"], "label": s["label"], "phase": s["phase"]} for s in stages.as_json()],
        "stages": stages.as_json(),
        "phases": [{"value": k, "label": v} for k, v in stages.PHASES],
        "ownership_types": [{"value": k, "label": v} for k, v in TYPE_LABELS.items()],
        "address_flags": ADDRESS_FLAG_LABELS,
        "regions": regions,
        "tiers": tiers,
        "company_statuses": company_statuses,
        "status_groups": [{"value": k, "label": v[0]} for k, v in STATUS_GROUPS.items()],
        "account_sizes": [{"value": k, "label": v[0]} for k, v in ACCOUNT_SIZES.items()],
        "map": {"tiles": config.MAP_TILE_URL, "attribution": config.MAP_ATTRIBUTION},
        "counts": counts,
        "buy_box": {"id": bb["id"], "name": bb["name"]},
        "buy_boxes": boxes,
    }


# Accounts categories from the register, grouped by what they say about size.
ACCOUNT_SIZES = scoring.ACCOUNT_TYPES

# Company status groups for filtering. Companies House statuses are lower-cased
# on load; "removed from register" is ours, for companies that left the file.
STATUS_GROUPS = {
    "active": ("Active", "c.status = 'active'"),
    "strike_off": ("Being struck off", "c.status like 'active - proposal to strike off%%'"),
    "insolvency": ("Insolvency", "(c.status ~ '(liquidation|administration|receiver|voluntary arrangement|insolvency)')"),
    "dissolved": ("Dissolved or removed", "c.status in ('dissolved', 'removed from register', 'converted-closed', 'closed')"),
}
_STATUS_KNOWN = "c.status in ('active', 'dissolved', 'removed from register', 'converted-closed', 'closed') or c.status like 'active - proposal to strike off%%' or c.status ~ '(liquidation|administration|receiver|voluntary arrangement|insolvency)'"
STATUS_GROUPS["other"] = ("Other", f"(c.status is null or not ({_STATUS_KNOWN}))")


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
    min_score: float | None = None, min_owner_age: int | None = None, include_excluded: bool = True,
    flag: str | None = None, sort: str = "score", dir: str = "desc", limit: int = 100, offset: int = 0,
    company_status: str | None = None, sic: str | None = None, changed_days: int | None = None,
    change_kind: str | None = None, min_value: float | None = None, max_value: float | None = None,
    min_years: int | None = None, format: str = "list", business_type: str | None = None,
    has_website: bool | None = None, bb: str = "all", in_box: bool | None = None,
    accounts_size: str | None = None, overdue: str | None = None, charges: str | None = None,
    numbers: str | None = None, count: bool = True, mine: str | None = None, sold: str | None = None,
    signal: str | None = None, revenue: str | None = None, wales: str | None = None,
):
    """All companies, with scores from one buy box (bb=<id>) or each company's
    best score across buy boxes (bb=all). in_box limits to companies inside
    the buy box (or any buy box); include_excluded=False means the same."""
    if in_box is None:
        in_box = not include_excluded
    with db.conn() as c:
        sj, sx, bb_id, bb_name = _score_join(c, bb)
        where, params = ["true"], {"bb": bb_id, "uid": UID, "bbname": bb_name}
        search_capped = False
        if q and q.strip():
            cands, search_capped = _search_candidates(c, q)
            where.append("c.company_number = any(%(qcands)s)"); params["qcands"] = cands
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
            # Either a group (see STATUS_GROUPS) or an exact Companies House status.
            conds = [STATUS_GROUPS[g][1] for g in company_status.split(",") if g in STATUS_GROUPS]
            if conds:
                where.append("(" + " or ".join(conds) + ")")
            else:
                where.append("c.status = %(cstatus)s"); params["cstatus"] = company_status
        if sic:
            # One or more codes or prefixes, comma separated: "62, 63110".
            prefixes = [x.strip().rstrip("*") for x in sic.split(",") if x.strip()]
            if prefixes:
                # Expand prefixes ("62") to the codes they cover, then use the
                # GIN index: "shares any code with this list".
                # Every code present on the register (cached list, as in the SIC picker).
                present = [r["code"] for r in sic_list() if r["level"] == "code"]
                codes = sorted({code for code in present if code.startswith(tuple(prefixes))}
                               | {p_.zfill(5) for p_ in prefixes if len(p_) >= 4})
                where.append("c.sic_codes && %(sic)s::text[]")
                params["sic"] = codes
        if changed_days:
            where.append("exists (select 1 from company_change x where x.company_number = c.company_number "
                         "and x.detected_at > now() - make_interval(days => %(cdays)s))"); params["cdays"] = changed_days
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
        if business_type:
            where.append("exists (select 1 from enrichment en where en.company_number = c.company_number and en.business_type = %(btype)s)")
            params["btype"] = business_type
        if has_website is not None:
            where.append(("" if has_website else "not ") + "exists (select 1 from enrichment en where en.company_number = c.company_number and en.website is not null)")
        if revenue in ("filed", "estimated"):  # where the revenue figure comes from
            where.append("exists (select 1 from estimate re where re.company_number = c.company_number and re.basis = %(rbasis)s)")
            params["rbasis"] = revenue
        elif revenue == "none":
            where.append("not exists (select 1 from estimate re where re.company_number = c.company_number)")
        if wales:  # presence in Wales, from the register, research, websites and funders
            sig = "exists (select 1 from company_signal sg where sg.company_number = c.company_number and sg.signals && %(wsig)s)"
            if wales == "registered":
                where.append("c.region = 'Wales'")
            elif wales == "office":
                where.append("coalesce(c.region, '') <> 'Wales' and " + sig); params["wsig"] = ["wales_office"]
            elif wales == "funding":
                where.append(sig); params["wsig"] = ["wales_funding"]
            elif wales == "director":
                where.append(sig); params["wsig"] = ["wales_director"]
            elif wales == "any":
                where.append(f"(c.region = 'Wales' or {sig})"); params["wsig"] = ["wales_office", "wales_funding"]
        if sold in ("hide", "only"):  # recently sold to another company (register or research)
            where.append(("" if sold == "only" else "not ") +
                         "exists (select 1 from company_signal sg where sg.company_number = c.company_number and 'recently_sold' = any(sg.signals))")
        if signal in ("possible_buyer", "many_shareholders"):
            where.append("exists (select 1 from company_signal sg where sg.company_number = c.company_number and %(signal)s = any(sg.signals))")
            params["signal"] = signal
        if mine == "hide_closed":   # hide companies you have passed on or rejected
            where.append("coalesce(uc.status, 'new') not in ('passed', 'rejected')")
        elif mine == "pipeline":    # only ones you are working on
            where.append("coalesce(uc.status, 'new') not in ('new', 'passed', 'rejected')")
        elif mine == "untouched":   # only ones you have not given a status yet
            where.append("coalesce(uc.status, 'new') = 'new'")
        if numbers:
            # an explicit selection (e.g. "export the ones I ticked")
            where.append("c.company_number = any(%(nums)s)")
            params["nums"] = [x.strip().upper() for x in numbers.split(",") if x.strip()][:5000]
        if accounts_size and accounts_size in ACCOUNT_SIZES:
            where.append("c.accounts_category = any(%(acats)s)"); params["acats"] = ACCOUNT_SIZES[accounts_size][1]
        if overdue in ("accounts", "confirmation", "any"):
            conds = {"accounts": ["c.accounts_next_due < current_date"],
                     "confirmation": ["c.confirmation_next_due < current_date"]}
            parts = conds.get(overdue) or conds["accounts"] + conds["confirmation"]
            where.append("(" + " or ".join(parts) + ") and c.status like 'active%%'")
        if charges == "outstanding":
            where.append("c.charges_outstanding > 0")
        elif charges == "none":
            where.append("coalesce(c.charges_outstanding, 0) = 0 and c.charges_total is not null")
        if in_box:
            where.append(sx)
        if format == "map":
            return _map_points(c, where, params, sj)
        if format == "count":
            # The count alone (the list is fetched first so rows show at once).
            if where == ["true"]:
                return {"total": cached("company_count", 3600, lambda: _count_all()), "capped": False}
            n = c.execute(f"select count(*) as n from (select 1 {_from_sql(sj, lateral='')} where {' and '.join(where)} limit {COUNT_CAP + 1}) x",
                          params).fetchone()["n"]
            return {"total": min(n, COUNT_CAP), "capped": n > COUNT_CAP}
        direction = "asc" if dir == "asc" else "desc"
        if sort == "relevance" and "qcands" in params:
            # Search order: exact number, postcode, names starting with it, names containing it.
            order_sql = "array_position(%(qcands)s::text[], c.company_number), c.name"
        elif sort == "name":
            # Matches company_name_sort_idx, so A-Z paging over millions is instant.
            order_sql = f"c.name {direction}, c.company_number {direction}"
        else:
            col = SORTS.get(sort, "s.score")
            if sort == "age":
                # "Owner age, highest first" means the earliest birth year first.
                direction = "asc" if direction == "desc" else "desc"
            # In a buy box every row has a score, so plain "score desc" lets the
            # score indexes do the sorting (with "nulls last" Postgres sorts it all).
            nulls = "" if (in_box and col == "s.score") else " nulls last"
            order_sql = f"{col} {direction}{nulls}, c.name, c.company_number"
        lateral = ""
        if sort == "changed":
            lateral = """left join lateral (select max(detected_at) as last_change from company_change x
                                            where x.company_number = c.company_number) ch on true"""
        filt = f"""{_from_sql(sj, lateral)}
            where {' and '.join(where)}"""
        params.update(limit=min(limit, 1000), offset=offset)
        # Sorting the whole directory by a figure from a side table (staff,
        # revenue...): page through that table's own index, then the companies
        # without a figure in name order, rather than sorting millions of rows.
        page_sql = f"""select c.company_number {filt} order by {order_sql} limit %(limit)s offset %(offset)s"""
        side = SIDE_SORTS.get((sort, direction))
        if side and where == ["true"] and not in_box:
            table, scol = side
            n_side = cached(f"count:{table}.{scol}", 3600, lambda: _count_table(table, scol))
            with_sql = f"""select x.company_number, 0 as grp, row_number() over () as rn from (
                               select x.company_number from {table} x where x.{scol} is not null
                               order by x.{scol} {direction}, x.company_number limit %(limit)s offset %(offset)s) x"""
            params["limit2"] = max(0, min(params["limit"], offset + params["limit"] - n_side))
            params["offset2"] = max(0, offset - n_side)
            without_sql = f"""select c.company_number, 1 as grp, row_number() over () as rn from (
                                  select c.company_number from company c
                                  where not exists (select 1 from {table} x where x.company_number = c.company_number
                                                    and x.{scol} is not null)
                                  order by c.name, c.company_number limit %(limit2)s offset %(offset2)s) c"""
            if offset + params["limit"] <= n_side:
                page_sql = with_sql
            elif offset >= n_side:
                page_sql = without_sql
            else:  # a page that straddles the boundary: the last with a figure, then the first without
                page_sql = f"select company_number from (({with_sql}) union all ({without_sql})) u order by grp, rn"
        # Page first (cheap), then fetch the extras for just those rows.
        sql = f"""
            with page as (
                select c.company_number, row_number() over () as rn from ({page_sql}) c
            )
            select c.company_number, c.name, c.region, c.postcode, c.review_tier, c.incorporation_date,
                   c.sic_codes, c.address_flag, c.status as company_status,
                   c.accounts_category, c.charges_outstanding,
                   (c.status like 'active%%' and c.accounts_next_due < current_date) as accounts_overdue,
                   (c.status like 'active%%' and c.confirmation_next_due < current_date) as confirmation_overdue,
                   l.employees, l.net_assets, l.period_end, l.staff_trend,
                   e.revenue_low, e.revenue_high, e.basis as revenue_basis, e.method as revenue_method,
                   o.ownership_type, o.oldest_birth_year, o.flags,
                   s.score, s.coverage, not ({sx}) as excluded, s.exclusion, s.value_low, s.value_high, s.value_basis,
                   s.box_name, s.boxes,
                   coalesce(uc.status, 'new') as status, uc.rating, uc.next_action, uc.next_action_on,
                   ch.last_change, ch.last_kinds, en.website, en.business_type,
                   ao_signals(c.company_number) as signals, ao_same_business(c.company_number) as same_business,
                   en.trading_region, sg.sold_on, sg.sold_to
            from page p join company c on c.company_number = p.company_number
            left join company_signal sg on sg.company_number = c.company_number
            left join company_latest l on l.company_number = c.company_number
            left join estimate e on e.company_number = c.company_number
            left join company_ownership o on o.company_number = c.company_number
            {sj}
            left join user_company uc on uc.company_number = c.company_number and uc.user_id = %(uid)s
            left join enrichment en on en.company_number = c.company_number
            left join lateral (
                select max(detected_at) as last_change,
                       array_agg(distinct kind) filter (where detected_at > now() - interval '90 days') as last_kinds
                from company_change x where x.company_number = c.company_number) ch on true
            order by p.rn
        """
        rows = c.execute(sql, params).fetchall()
        if "qcands" in params:
            hits = _OWNER_HITS.get({})
            for r in rows:
                r["matched_owner"] = hits.get(r["company_number"])
        # Counting millions of matches is slow, so counts stop at COUNT_CAP
        # ("100,000+"). With no filters at all the total is the register size.
        capped = False
        if not count:
            total = None  # the page asks for the count separately
        elif not (rows or offset):
            total = 0
        elif where == ["true"]:
            total = cached("company_count", 3600, lambda: _count_all())
        else:
            total = c.execute(f"select count(*) as n from (select 1 {filt} limit {COUNT_CAP + 1}) x", params).fetchone()["n"]
            if total > COUNT_CAP:
                total, capped = COUNT_CAP, True
        capped = capped or search_capped
    return {"total": total, "capped": capped, "rows": rows, "search_limited": search_capped}


COUNT_CAP = 100_000


def _from_sql(sj: str, lateral: str) -> str:
    return f"""from company c
            left join company_latest l on l.company_number = c.company_number
            left join estimate e on e.company_number = c.company_number
            left join company_ownership o on o.company_number = c.company_number
            {sj}
            left join user_company uc on uc.company_number = c.company_number and uc.user_id = %(uid)s
            {lateral}"""
# (sort, direction) -> (side table, column) that an index can page through.
SIDE_SORTS = {
    ("staff", "desc"): ("company_latest", "employees"),
    ("net_assets", "desc"): ("company_latest", "net_assets"),
    ("revenue", "desc"): ("estimate", "revenue_high"),
    ("age", "asc"): ("company_ownership", "oldest_birth_year"),  # oldest owners first
}


def _count_table(table: str, col: str) -> int:
    with db.conn() as c:
        return c.execute(f"select count(*) as n from {table} where {col} is not null").fetchone()["n"]
SEARCH_CAP = 5_000
_PC_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?(\s*\d[A-Z]{0,2})?$")
_NUM_RE = re.compile(r"^([A-Z]{2})?\d{1,8}$")


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


import contextvars

_OWNER_HITS: contextvars.ContextVar[dict] = contextvars.ContextVar("owner_hits", default={})


def _search_candidates(c, q: str) -> tuple[list[str], bool]:
    """Company numbers matching a search, found with indexes rather than a
    scan of millions of rows: the exact company number, postcodes starting
    with it, names starting with it, then names containing it. Returns
    (numbers, limited) where limited means a very common term matched more
    than SEARCH_CAP companies and only the first ones are listed."""
    from . import normalise as nm

    qs = " ".join(q.strip().split())
    qu = qs.upper()
    found: dict[str, None] = {}
    compact = qu.replace(" ", "")
    if _NUM_RE.match(compact):
        num = nm.company_number(compact)
        for r in c.execute("select company_number from company where company_number = any(%s)", ([num, compact],)):
            found[r["company_number"]] = None
    limited = False
    if _PC_RE.match(qu):
        if " " not in qu and len(compact) <= 4:
            pattern = _like_escape(compact) + " %"  # outward code only: LS1 means LS1 x, not LS10
        else:
            pattern = _like_escape(nm.postcode(qu) or qu) + "%"
        rows = c.execute("select company_number from company where postcode like %s limit %s",
                         (pattern, SEARCH_CAP + 1)).fetchall()
        limited = limited or len(rows) > SEARCH_CAP
        for r in rows[:SEARCH_CAP]:
            found[r["company_number"]] = None
    rows = c.execute("select company_number from company where name like %s order by name limit %s",
                     (_like_escape(qu) + "%", SEARCH_CAP + 1)).fetchall()
    limited = limited or len(rows) > SEARCH_CAP
    for r in rows[:SEARCH_CAP]:
        found[r["company_number"]] = None
    if len(qs) >= 3 and len(found) < SEARCH_CAP:
        # Names containing the words anywhere (trigram index). Each word must appear.
        words = [w for w in qu.split(" ") if w]
        conds = " and ".join(["name ilike %s"] * len(words))
        rows = c.execute(f"select company_number from company where {conds} limit %s",
                         (*[f"%{_like_escape(w)}%" for w in words], SEARCH_CAP + 1)).fetchall()
        limited = limited or len(rows) > SEARCH_CAP
        for r in rows[:SEARCH_CAP]:
            found[r["company_number"]] = None
    # ...and companies whose owner (person with significant control) has that name.
    owner_of: dict[str, str] = {}
    if len(qs) >= 3:
        words = [w for w in qu.split(" ") if w]
        conds = " and ".join(["p.name ilike %s"] * len(words))
        for r in c.execute(
                f"""select cp.company_number, p.name from company_person cp join person p on p.id = cp.person_id
                    where cp.ceased_on is null and {conds} limit %s""",
                (*[f"%{_like_escape(w)}%" for w in words], SEARCH_CAP)):
            owner_of.setdefault(r["company_number"], r["name"])
            found[r["company_number"]] = None
    _OWNER_HITS.set(owner_of)
    return list(found)[: SEARCH_CAP * 2], limited


def _count_all() -> int:
    with db.conn() as c:
        return c.execute("select count(*) as n from company").fetchone()["n"]


def _score_join(c, bb: str):
    """(join SQL aliased s, "in the box" condition, buy box id) for bb = 'all',
    'active' or an id. For 'all', s is each company's best score across boxes."""
    if bb == "all":
        return ("""left join (select cb.company_number, cb.score, cb.coverage, cb.value_low, cb.value_high,
                                    cb.value_basis, cb.box_name, cb.boxes, null::text as exclusion
                             from company_best cb) s on s.company_number = c.company_number""",
                "s.company_number is not null", None, None)
    box = None
    if bb.isdigit():
        box = c.execute("select id, name from buy_box where id = %s and user_id = %s", (int(bb), UID)).fetchone()
    if not box:
        box = scoring.active_buy_box(c)
    return (f"""left join (select sc.*, %(bbname)s::text as box_name, null::text[] as boxes from score sc
                           where sc.buy_box_id = {int(box['id'])}) s on s.company_number = c.company_number""",
            "s.excluded = false", box["id"], box["name"])


@app.get("/api/companies/{num}")
def company(num: str, bb: str | None = None):
    """One company. "score" is the chosen buy box's score (bb=<id>), or by
    default its best score; "scores" lists its score in every buy box."""
    with db.conn() as c:
        boxes = [dict(b) for b in c.execute("select * from buy_box where user_id = %s order by id", (UID,))]
        if not boxes:
            boxes = [scoring.active_buy_box(c)]
        best = c.execute("select buy_box_id from company_best where company_number = %s", (num,)).fetchone()
        chosen = int(bb) if bb and bb.isdigit() else (best["buy_box_id"] if best else None)
        bb = next((b for b in boxes if b["id"] == chosen), None) or next((b for b in boxes if b["is_active"]), boxes[0])
        row = c.execute("select * from company where company_number = %s", (num,)).fetchone()
        if not row:
            raise HTTPException(404, "Company not found")
        fin = c.execute(
            "select * from financial_period where company_number = %s order by period_end", (num,)
        ).fetchall()
        est = c.execute("select * from estimate where company_number = %s", (num,)).fetchone()
        own = c.execute("select * from company_ownership where company_number = %s", (num,)).fetchone()
        people = c.execute(
            """select p.id as person_id, p.name, p.kind, p.birth_year, p.birth_month, p.country_registered, p.registration_number,
                      cp.role, cp.natures, cp.notified_on, cp.ceased_on
               from company_person cp join person p on p.id = cp.person_id
               where cp.company_number = %s order by cp.ceased_on nulls first, cp.notified_on desc""",
            (num,),
        ).fetchall()
        links = _links_for(c, num)
        from . import chapi

        ch_details = chapi.details(c, num)
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
        own_margin = not any(override.get(k) not in (None, "") for k in ("margin_low", "margin_high"))
        val = {**valuation.value(facts, a, use_filed_margin=own_margin), "assumptions": a, "defaults": valuation.assumptions(bb["criteria"]),
               "override": override, "cash": facts.get("cash"), "filed_margin": facts.get("filed_margin"),
               "filed_margin_period": facts.get("filed_margin_period")}
        geo = c.execute("select lat, lon, precision from postcode_geo where postcode = %s and lat is not null",
                        (row["postcode"],)).fetchone() if row["postcode"] else None
        sic_known = {r["code"]: r["description"] for r in c.execute(
            "select code, description from sic_code where code = any(%s)", (row["sic_codes"] or [],))}
        from . import sic as sic_mod

        sics = [{"code": code, "description": sic_mod.describe(code, sic_known)} for code in row["sic_codes"] or []]
        enr = c.execute("select * from enrichment where company_number = %s", (num,)).fetchone()
        signals = c.execute("select ao_signals(%s) as s", (num,)).fetchone()["s"] or []
        sold = c.execute("select sold_on, sold_to from company_signal where company_number = %s and 'recently_sold' = any(signals)",
                         (num,)).fetchone()
        # Companies that look like the same business (same owner and address, or
        # a director in common at the same postcode), shown for information.
        same_business = c.execute(
            """select c2.company_number, c2.name, c2.postcode, l.employees, e.revenue_low, e.revenue_high, e.basis as revenue_basis
               from unnest(ao_same_business(%s)) x(num) join company c2 on c2.company_number = x.num
               left join company_latest l on l.company_number = c2.company_number
               left join estimate e on e.company_number = c2.company_number""", (num,)).fetchall()
        if enr and enr.get("locations"):
            # Map positions for the other offices, where their postcodes are known.
            pcs = [l["postcode"] for l in enr["locations"] if l.get("postcode")]
            where = {r["postcode"]: r for r in c.execute(
                "select postcode, lat, lon from postcode_geo where postcode = any(%s) and lat is not null", (pcs,))}
            for l in enr["locations"]:
                g = where.get(l.get("postcode"))
                l["lat"], l["lon"] = (g["lat"], g["lon"]) if g else (None, None)
        issues = c.execute("select * from data_issue where company_number = %s order by status, created_at desc",
                           (num,)).fetchall()
        deal = _deal(c, num, (state or {}).get("status") or "new")
        manual_values = {r["criterion_key"]: r for r in c.execute(
            "select criterion_key, value, note, updated_at from manual_score where user_id = %s and company_number = %s",
            (UID, num))}
        # Your criteria from every buy box (shared keys appear once).
        crits, seen = [], set()
        for b in boxes:
            for m in scoring.merged(b["criteria"]).get("manual") or []:
                if m["key"] not in seen:
                    seen.add(m["key"])
                    crits.append({**m, "boxes": [x["name"] for x in boxes
                                                 if any(mm["key"] == m["key"] for mm in scoring.merged(x["criteria"]).get("manual") or [])]})
        manual = {"criteria": crits, "values": manual_values}
        stored = {r["buy_box_id"]: dict(r) for r in c.execute("select * from score where company_number = %s", (num,))}
        facts = None
        scores = []
        for b in boxes:
            r = stored.get(b["id"])
            if r is None:
                # Outside this buy box's universe: no stored row, so score it on the fly.
                facts = facts if facts is not None else (scoring.load_facts(c, num) or [None])[0]
                if facts:
                    crit = scoring.merged(b["criteria"])
                    r = {**scoring.score_company(facts, crit, None, scoring.scope_test(crit)), "live": True}
            if r:
                scores.append({"buy_box_id": b["id"], "buy_box": b["name"], "score": r["score"],
                               "coverage": r["coverage"], "excluded": r["excluded"], "exclusion": r["exclusion"],
                               "reasons": r["reasons"], "value_low": r.get("value_low"), "value_high": r.get("value_high")})
        sc = next((x for x in scores if x["buy_box_id"] == bb["id"]), None)
    return {
        "deal": deal, "manual": manual, "buy_box": {"id": bb["id"], "name": bb["name"]}, "scores": scores,
        "signals": signals, "sold": sold, "same_business": same_business,
        "geo": geo, "sics": sics, "enrichment": enr, "issues": issues,
        "changes": changes, "valuation": val, "fin_summary": fintrends.summary(fin), "ch": ch_details,
        "company": row, "financials": fin, "estimate": est, "ownership": own, "people": people,
        "links": links, "score": sc, "state": state or {"status": "new", "rating": None, "tags": []},
        "notes": notes, "research": research, "outreach": outreach,
    }


def _deal(c, num, status):
    history = c.execute(
        """select from_status, to_status, note, created_at from stage_event
           where user_id = %s and company_number = %s order by created_at, id""", (UID, num)).fetchall()
    saved = {(r["stage"], r["item_key"]): r for r in c.execute(
        "select * from deal_task where user_id = %s and company_number = %s", (UID, num))}
    tasks = {}
    for st in stages.STATUSES:
        items = []
        for label in stages.CHECKLISTS[st]:
            k = stages.item_key(label)
            row = saved.pop((st, k), None)
            items.append({"item_key": k, "label": label, "custom": False, "done": bool(row and row["done"]),
                          "done_at": row["done_at"] if row else None, "note": row["note"] if row else None})
        tasks[st] = items
    for (st, k), row in saved.items():  # custom items
        tasks.setdefault(st, []).append({"item_key": k, "label": row["label"], "custom": True, "done": row["done"],
                                         "done_at": row["done_at"], "note": row["note"]})
    entered = next((h["created_at"] for h in reversed(history) if h["to_status"] == status), None)
    return {"history": history, "tasks": tasks, "stage_entered_at": entered}


class TaskIn(BaseModel):
    stage: str
    label: str
    item_key: str | None = None
    done: bool = False
    note: str | None = None
    delete: bool = False


@app.post("/api/companies/{num}/tasks")
def set_task(num: str, t: TaskIn):
    if t.stage not in stages.STATUSES:
        raise HTTPException(400, "Unknown stage")
    key = t.item_key or stages.item_key(t.label)
    custom = stages.item_key(t.label) not in {stages.item_key(x) for x in stages.CHECKLISTS[t.stage]}
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise HTTPException(404, "Company not found")
        if t.delete:
            c.execute("delete from deal_task where user_id=%s and company_number=%s and stage=%s and item_key=%s and custom",
                      (UID, num, t.stage, key))
        else:
            c.execute(
                """insert into deal_task (user_id, company_number, stage, item_key, label, custom, done, done_at, note)
                   values (%s, %s, %s, %s, %s, %s, %s, case when %s then now() end, %s)
                   on conflict (user_id, company_number, stage, item_key) do update set done = excluded.done,
                     done_at = case when excluded.done and not deal_task.done then now()
                                    when not excluded.done then null else deal_task.done_at end,
                     note = coalesce(excluded.note, deal_task.note)""",
                (UID, num, t.stage, key, t.label.strip(), custom, t.done, t.done, t.note),
            )
            c.execute("insert into user_company (user_id, company_number) values (%s, %s) on conflict do nothing", (UID, num))
        return _deal(c, num, c.execute("select status from user_company where user_id=%s and company_number=%s",
                                       (UID, num)).fetchone()["status"])


def _map_points(c, where, params, sj):
    """Located companies matching the filters, plus links between them."""
    rows = c.execute(
        f"""select c.company_number, c.name, c.postcode, c.region, g.lat, g.lon, g.precision,
                   s.score, s.score is null as excluded, coalesce(uc.status, 'new') as status, o.ownership_type,
                   c.status as company_status
            from company c
            left join company_ownership o on o.company_number = c.company_number
            {sj}
            left join user_company uc on uc.company_number = c.company_number and uc.user_id = %(uid)s
            left join estimate e on e.company_number = c.company_number
            left join company_latest l on l.company_number = c.company_number
            join postcode_geo g on g.postcode = c.postcode and g.lat is not null
            where {' and '.join(where)}
            order by s.score desc nulls last limit 25000""",
        params,
    ).fetchall()
    total = c.execute(
        f"""select count(*) as n from company c
            left join company_ownership o on o.company_number = c.company_number
            {sj}
            left join user_company uc on uc.company_number = c.company_number and uc.user_id = %(uid)s
            left join estimate e on e.company_number = c.company_number
            left join company_latest l on l.company_number = c.company_number
            where {' and '.join(where)}""",
        params,
    ).fetchone()["n"]
    nums = [r["company_number"] for r in rows]
    links = c.execute(
        """select l.a, l.b, l.kind, l.confidence, l.via, coalesce(l.b_name, cb.name) as b_name,
                  coalesce(gb.lat, gp.lat) as b_lat, coalesce(gb.lon, gp.lon) as b_lon,
                  cb.company_number is not null as b_in_list
           from company_link l
           left join company cb on cb.company_number = l.b
           left join postcode_geo gb on gb.postcode = cb.postcode
           left join lateral (select p.postcode from person p where p.registration_number = l.b
                              and p.postcode is not null limit 1) pp on cb.company_number is null
           left join postcode_geo gp on gp.postcode = pp.postcode
           where l.a = any(%s) and l.kind in ('owned_by', 'shared_owner')
             and (l.kind = 'owned_by' or l.b = any(%s))""",
        (nums, nums),
    ).fetchall() if nums else []
    return {"total": total, "located": len(rows), "points": rows,
            "links": [x for x in links if x["b_lat"] is not None]}


def _links_for(c, num):
    return c.execute(
        """select l.kind, l.via, l.confidence, l.evidence,
                  case when l.a = %(n)s then l.b else l.a end as other,
                  case when l.a = %(n)s then coalesce(l.b_name, cb.name) else ca.name end as other_name,
                  case when l.kind = 'owned_by' and l.a = %(n)s then 'parent'
                       when l.kind = 'owned_by' then 'subsidiary' else 'peer' end as direction,
                  exists(select 1 from company x where x.company_number =
                         case when l.a = %(n)s then l.b else l.a end) as in_list,
                  coalesce(case when l.a = %(n)s then gb.lat else ga.lat end, gp.lat) as lat,
                  coalesce(case when l.a = %(n)s then gb.lon else ga.lon end, gp.lon) as lon
           from company_link l
           left join company ca on ca.company_number = l.a
           left join company cb on cb.company_number = l.b
           left join postcode_geo ga on ga.postcode = ca.postcode
           left join postcode_geo gb on gb.postcode = cb.postcode
           left join lateral (select p.postcode from person p where p.registration_number = l.b
                              and p.postcode is not null limit 1) pp on l.a = %(n)s and cb.company_number is null
           left join postcode_geo gp on gp.postcode = pp.postcode
           where l.a = %(n)s or l.b = %(n)s
           order by case l.confidence when 'confirmed' then 0 when 'likely' then 1 else 2 end, l.kind""",
        {"n": num},
    ).fetchall()


FUNDING_KEYS = {"price", "your_cash", "investor_equity", "investor_stake", "investor_loan", "investor_rate", "investor_years",
                "vendor_loan", "vendor_rate", "vendor_years", "bank_rate", "bank_years",
                # EBITDA adjustments: costs leaving with the seller, costs of the new team
                "addback_owner_pay", "addback_other", "new_salaries", "new_oncost",
                # older names, still read
                "investor_cash", "vendor_pct"}


class StateIn(BaseModel):
    status: str | None = None
    rating: int | None = None
    next_action: str | None = None
    next_action_on: date | None = None
    tags: list[str] | None = None
    valuation: dict | None = None
    funding: dict | None = None
    stage_note: str | None = None
    clear_rating: bool = False


class BulkStateIn(StateIn):
    numbers: list[str]


@app.put("/api/companies/state")
def set_state_bulk(body: BulkStateIn):
    """The same change (stage, rating, next action, tags) for many companies
    at once, each recorded exactly as a single change would be."""
    nums = list(dict.fromkeys(n_.strip().upper() for n_ in body.numbers if n_.strip()))[:2000]
    if not nums:
        raise HTTPException(400, "No companies selected")
    one = StateIn(**body.model_dump(exclude={"numbers"}, exclude_unset=True))
    done = [set_state(n_, one) for n_ in nums]
    return {"updated": len(done)}


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
        before = c.execute("select status from user_company where user_id = %s and company_number = %s",
                           (UID, num)).fetchone()["status"]
        if body.status and body.status != before:
            c.execute(
                """insert into stage_event (user_id, company_number, from_status, to_status, note)
                   values (%s, %s, %s, %s, %s)""",
                (UID, num, before, body.status, body.stage_note),
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
        if "funding" in fields:
            clean = {k: float(v) for k, v in (fields["funding"] or {}).items()
                     if k in FUNDING_KEYS and isinstance(v, (int, float)) and v == v}
            sets.append("funding = %s")
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
def dashboard(bb: str = "all"):
    d = cached(f"dashboard:{bb}", 120, lambda: _dashboard(bb))
    return {**d, "refresh": job_current()}


def _scope(c, which: str):
    """(SQL for the scored companies in scope aliased d, params, buy box name).
    Reads company_best or score directly, through their indexes; no copy."""
    active = scoring.active_buy_box(c)
    if which == "all":
        return ("(select company_number, score, coverage, value_low, value_high, box_name as box from company_best) d",
                {}, "All buy boxes")
    bid = int(which) if which.isdigit() else active["id"]
    row = c.execute("select id, name from buy_box where id = %s and user_id = %s", (bid, UID)).fetchone() or active
    return ("""(select s.company_number, s.score, s.coverage, s.value_low, s.value_high, %(bbname)s::text as box
                from score s where s.buy_box_id = %(bbid)s and not s.excluded) d""",
            {"bbname": row["name"], "bbid": row["id"]}, row["name"])


def compute_dashboard_stats(c, which: str) -> dict:
    """The register-wide part of the Home page for one scope: counts and
    spreads over every scored company. Worked out after each load or scoring
    run and stored, so the page itself only runs small queries."""
    d_sql, p, _ = _scope(c, which)
    head = c.execute(
        f"""select
             (select count(*) from {d_sql}) as in_scope,
             (select count(*) from {d_sql} where d.score >= 70) as strong,
             (select percentile_cont(0.5) within group (order by extract(year from current_date) - o.oldest_birth_year)
                from company_ownership o join {d_sql} using (company_number) where o.oldest_birth_year is not null) as median_owner_age,
             (select count(*) from company_ownership o join {d_sql} using (company_number)
                where o.oldest_birth_year <= extract(year from current_date) - 60) as owners_60,
             (select count(*) from company_latest l join {d_sql} using (company_number)
                where cardinality(l.staff_trend) >= 3) as with_history""", p).fetchone()
    hist = c.execute(f"select width_bucket(d.score, 0, 100.0001, 10) as b, count(*) as n from {d_sql} group by 1 order by 1", p).fetchall()
    ownership = c.execute(
        f"""select coalesce(o.ownership_type,'unknown') as type, count(*) as n from {d_sql}
            left join company_ownership o using (company_number) group by 1 order by 2 desc""", p).fetchall()
    trend = c.execute(
        f"""select extract(year from period_end)::int as year, count(distinct company_number) as companies,
                   percentile_cont(0.5) within group (order by employees) as median_staff,
                   sum(employees) as total_staff
            from financial_period where not period_inferred and employees is not null
              and company_number in (select company_number from {d_sql})
            group by 1 having count(*) >= 3 order by 1""", p).fetchall()
    return {"head": dict(head), "hist": [dict(h) for h in hist], "ownership": [dict(o) for o in ownership],
            "trend": [dict(t) for t in trend]}


def _dashboard(which: str = "all"):
    """Home page data for one buy box, or "all" for an overview across them."""
    with db.conn() as c:
        d_sql, p, bb_name = _scope(c, which)
        p["uid"] = UID
        stored = stats_get(c, f"dashboard:{which}", lambda cc: compute_dashboard_stats(cc, which))
        live = c.execute(
            f"""select
                 (select ao_rowcount('company')) as companies,
                 (select count(*) from user_company where user_id = %(uid)s and status not in ('new','rejected','passed')) as pipeline,
                 (select count(*) from user_company where user_id = %(uid)s and status in ('contacted','in_talks','nda','offer','heads','diligence','spa','completion')) as talking,
                 (select count(distinct ch.company_number) from company_change ch join {d_sql} using (company_number)
                    where ch.detected_at > now() - interval '7 days') as changed_7d,
                 (select count(distinct ch.company_number) from company_change ch join {d_sql} using (company_number)
                    where ch.detected_at > now() - interval '30 days') as changed_30d,
                 (select count(*) from company_change ch join {d_sql} using (company_number)
                    where ch.kind = 'status' and ch.detected_at > now() - interval '30 days') as status_30d,
                 (select sum((d.value_low + d.value_high) / 2) from {d_sql} join user_company uc using (company_number)
                    where uc.user_id = %(uid)s and uc.status not in ('new','rejected','passed')) as pipeline_value,
                 (select sum(d.value_low) from {d_sql} join user_company uc using (company_number)
                    where uc.user_id = %(uid)s and uc.status not in ('new','rejected','passed')) as pipeline_value_low,
                 (select sum(d.value_high) from {d_sql} join user_company uc using (company_number)
                    where uc.user_id = %(uid)s and uc.status not in ('new','rejected','passed')) as pipeline_value_high""",
            p).fetchone()
        head = {**stored["head"], **dict(live)}
        top = c.execute(
            f"""with top as (
                   -- the first 8 by score (through the score index), then their details
                   select d.* from {d_sql}
                   where d.score >= 40
                     and not exists (select 1 from user_company uc where uc.company_number = d.company_number
                                     and uc.user_id = %(uid)s and uc.status <> 'new')
                     and exists (select 1 from company c2 where c2.company_number = d.company_number and c2.status = 'active')
                   order by d.score desc, d.coverage desc limit 8)
               select c.company_number, c.name, c.region, d.score, d.value_low, d.value_high, d.box, l.employees,
                      o.oldest_birth_year, o.ownership_type
               from top d join company c on c.company_number = d.company_number
               left join company_latest l on l.company_number = c.company_number
               left join company_ownership o on o.company_number = c.company_number
               order by d.score desc, d.coverage desc""", p).fetchall()
        recent = c.execute(
            f"""select ch.company_number, ch.kind, ch.field, ch.old_value, ch.new_value, ch.detected_at, c.name,
                      coalesce(uc.status, 'new') as status
               from company_change ch join company c on c.company_number = ch.company_number
               left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
               where ch.detected_at > now() - interval '30 days' and ch.kind <> 'new_company'
                 and (exists (select 1 from {d_sql} where d.company_number = ch.company_number)
                      or coalesce(uc.status, 'new') <> 'new')
               order by (coalesce(uc.status,'new') <> 'new') desc, (ch.kind = 'status') desc, ch.detected_at desc
               limit 8""", p).fetchall()
        due = c.execute(
            """select uc.company_number, c.name, uc.status, uc.next_action, uc.next_action_on
               from user_company uc join company c on c.company_number = uc.company_number
               where uc.user_id = %(uid)s and uc.next_action_on is not null and uc.status not in ('rejected','passed')
               order by uc.next_action_on limit 6""", p).fetchall()
        funnel = c.execute("select status, count(*) as n from user_company where user_id = %(uid)s group by 1", p).fetchall()
        freshness = c.execute(
            "select kind, max(finished_at) as last from import_run where finished_at is not null group by kind").fetchall()
        boxes = []
        for b in c.execute("select id, name, is_active, scored_at from buy_box where user_id = %(uid)s order by id", p).fetchall():
            bs = stats_get(c, f"dashboard:{b['id']}", lambda cc, i=b["id"]: compute_dashboard_stats(cc, str(i)))["head"]
            pipeline = c.execute(
                """select count(*) as n from user_company uc join score s on s.company_number = uc.company_number
                     and s.buy_box_id = %s and not s.excluded
                   where uc.user_id = %s and uc.status not in ('new','rejected','passed')""", (b["id"], UID)).fetchone()["n"]
            boxes.append({**dict(b), "in_scope": bs["in_scope"], "strong": bs["strong"], "pipeline": pipeline})
    fmap = {r["status"]: r["n"] for r in funnel}
    hist = stored["hist"]
    # Recent years are only partly filed (accounts are due up to nine months
    # after the year end), so drop years with under half the usual coverage.
    trend = stored["trend"]
    peak = max((t["companies"] for t in trend), default=0)
    trend = [t for t in trend if t["companies"] >= peak * 0.5]
    return {
        "head": head, "score_hist": [{"b": i, "n": next((h["n"] for h in hist if h["b"] == i), 0)} for i in range(1, 11)],
        "top": top, "recent": recent, "due": due, "ownership": stored["ownership"],
        "funnel": [{"status": st, "label": STATUS_LABELS[st], "n": fmap.get(st, 0)} for st in STATUSES if st != "new"],
        "freshness": {r["kind"]: r["last"] for r in freshness}, "trend": trend,
        "buy_box": bb_name, "scope": which, "boxes": boxes,
    }


_geo_state = {"running": False, "result": None}


@app.post("/api/geocode")
def start_geocode():
    """Look up map coordinates for postcodes not yet located (background)."""
    import threading

    if _geo_state["running"]:
        raise HTTPException(409, "Already running")

    def work():
        from . import geo

        try:
            with db.conn(dedicated=True) as c:
                _geo_state["result"] = geo.geocode(c)
        except Exception as e:
            _geo_state["result"] = {"error": str(e)}
        finally:
            _geo_state["running"] = False

    _geo_state.update(running=True, result=None)
    threading.Thread(target=work, daemon=True).start()
    return _geo_state


@app.get("/api/geocode")
def geocode_status():
    with db.conn() as c:
        counts = c.execute(
            """select count(*) filter (where g.lat is not null) as located,
                      count(*) filter (where g.postcode is null) as pending,
                      count(*) filter (where g.precision = 'none') as not_found,
                      count(*) as total
               from company c left join postcode_geo g on g.postcode = c.postcode
               where c.postcode is not null""").fetchone()
    return {**_geo_state, "counts": counts}


def stats_get(c, key: str, compute):
    """A stored summary, computed and stored on first use (data jobs refresh it)."""
    row = c.execute("select value from stats where key = %s", (key,)).fetchone()
    if row:
        return row["value"]
    value = compute(c)
    c.execute("insert into stats (key, value) values (%s, %s) on conflict (key) do update set value = excluded.value, updated_at = now()",
              (key, json.dumps(value, default=str)))
    return json.loads(json.dumps(value, default=str))


def compute_sic_counts(c) -> list[dict]:
    return [dict(r) for r in c.execute(
        """select code, count(*) as n, count(cb.company_number) as in_scope
           from company c cross join unnest(c.sic_codes) code
           left join company_best cb on cb.company_number = c.company_number
           group by code""")]


def refresh_stats(c, data: bool = True):
    """Recompute stored summaries after a data load (called by the jobs).
    data=False after scoring only: skips what depends on the data, not scores."""
    if data:
        c.execute("select ao_refresh_company_signals()")  # recently sold, possible buyers
    todo = [("sic_counts", compute_sic_counts), ("dashboard:all", lambda cc: compute_dashboard_stats(cc, "all"))]
    if data:
        todo += [("coverage", _coverage_compute), ("meta_lists", compute_meta_lists)]
    for b in c.execute("select id from buy_box where user_id = %s", (UID,)).fetchall():
        todo.append((f"dashboard:{b['id']}", lambda cc, i=b["id"]: compute_dashboard_stats(cc, str(i))))
    for key, fn in todo:
        c.execute("insert into stats (key, value) values (%s, %s) on conflict (key) do update set value = excluded.value, updated_at = now()",
                  (key, json.dumps(fn(c), default=str)))


@app.get("/api/sic")
def sic_list():
    return cached("sic", 3600, _sic_list)


def _sic_list():
    """Every SIC code we know (from Companies House data and the built-in
    list) plus the two-digit divisions, with how many companies have each."""
    from . import sic as sic_mod

    with db.conn() as c:
        counts = {r["code"]: r for r in stats_get(c, "sic_counts", compute_sic_counts)}
        known = {r["code"]: r["description"] for r in c.execute("select code, description from sic_code")}
    codes = set(known) | set(counts)
    out = [{"code": code, "description": sic_mod.describe(code, known), "level": "code",
            "n": counts[code]["n"] if code in counts else 0,
            "in_scope": counts[code]["in_scope"] if code in counts else 0} for code in codes]
    for div, name in sic_mod.DIVISIONS.items():
        n = sum(r["n"] for k, r in counts.items() if k.startswith(div))
        ins = sum(r["in_scope"] for k, r in counts.items() if k.startswith(div))
        out.append({"code": div, "description": name, "level": "division", "n": n, "in_scope": ins})
    out.sort(key=lambda r: (-r["n"], r["code"]))
    return out


class EnrichIn(BaseModel):
    source_url: str = "manual"
    website: str | None = None
    business_type: str | None = None
    recurring_revenue: str | None = None
    field_service: str | None = None
    summary: str | None = None
    confidence: str = "high"
    source_label: str | None = None
    locations: list | None = None
    facts: list | None = None
    linkedin: str | None = None
    phone: str | None = None
    sources: list | None = None
    ownership: str | None = None
    ownership_note: str | None = None


@app.post("/api/companies/{num}/enrichment")
def save_enrichment(num: str, body: EnrichIn):
    from . import enrich

    with db.conn() as c:
        try:
            return enrich.save_enrichment(c, num, by="me", **body.model_dump())
        except enrich.EnrichError as e:
            raise HTTPException(400, str(e))


class IssueIn(BaseModel):
    issue: str
    company_number: str | None = None
    detail: str | None = None
    suggested_fix: str | None = None


@app.get("/api/issues")
def issues(status: str = "open"):
    where = "" if status == "all" else "where d.status = %s"
    return _rows(f"""select d.*, c.name from data_issue d left join company c on c.company_number = d.company_number
                     {where} order by d.created_at desc limit 500""", () if status == "all" else (status,))


@app.post("/api/issues")
def add_issue(body: IssueIn):
    from . import enrich

    with db.conn() as c:
        try:
            return enrich.flag_issue(c, body.company_number, body.issue, body.detail, body.suggested_fix, by="me")
        except enrich.EnrichError as e:
            raise HTTPException(400, str(e))


class ResolveIn(BaseModel):
    resolution: str = ""
    status: str = "resolved"


@app.post("/api/issues/{issue_id}/resolve")
def resolve_issue(issue_id: int, body: ResolveIn):
    from . import enrich

    with db.conn() as c:
        try:
            return enrich.resolve_issue(c, issue_id, body.resolution, body.status)
        except enrich.EnrichError as e:
            raise HTTPException(400, str(e))


@app.get("/api/connect")
def connect_info(request: Request):
    """What the Connect Claude page needs: endpoint and whether a token is set."""
    base = str(request.base_url).rstrip("/")
    with db.conn() as c:
        e = c.execute("""select (select count(*) from enrichment) as enriched,
                                (select count(*) from data_issue where status = 'open') as open_issues,
                                (select max(updated_at) from enrichment where updated_by like 'claude%%') as last_claude""").fetchone()
    return {"mcp_url": f"{base}/mcp", "api_docs": f"{base}/docs", "token_set": bool(config.API_TOKEN),
            "ch_key_set": bool(config.CH_API_KEY),
            "password_set": bool(config.APP_PASSWORD), **e}


# A change is unread if it came after "mark all as read" (or in the last 7
# days, before that was first used) and was not marked read on its own.
UNREAD_SQL = """(ch.detected_at > coalesce((select (value #>> '{}')::timestamptz from app_setting
                                            where key = 'changes_seen_at'), now() - interval '7 days')
               and not exists (select 1 from change_read cr where cr.change_id = ch.id))"""


@app.get("/api/changes")
def changes(days: int = 90, kind: str | None = None, tracked: bool = False, limit: int = 500, scope: str = "buy_box",
            unread: bool = False):
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        where, params = ["ch.detected_at > now() - make_interval(days => %(days)s)"], {"days": days, "uid": UID, "bb": bb["id"], "limit": min(limit, 2000)}
        if unread:
            where.append(UNREAD_SQL)
        if kind:
            where.append("ch.kind = %(kind)s"); params["kind"] = kind
        if tracked:
            where.append("coalesce(uc.status, 'new') not in ('new', 'rejected', 'passed')")
        elif scope == "buy_box":
            where.append("(exists (select 1 from company_best cb where cb.company_number = ch.company_number) "
                         "or coalesce(uc.status, 'new') <> 'new')")
        rows = c.execute(
            f"""select ch.id, ch.company_number, ch.kind, ch.field, ch.old_value, ch.new_value, ch.detected_at, ch.source,
                       {UNREAD_SQL} as unread,
                       c.name, c.status as company_status, coalesce(uc.status, 'new') as status, s.score, s.excluded,
                       r.filename
                from company_change ch join company c on c.company_number = ch.company_number
                left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
                left join score s on s.company_number = ch.company_number and s.buy_box_id = %(bb)s
                left join import_run r on r.id = ch.import_run_id
                where {' and '.join(where)}
                order by ch.detected_at desc, ch.id desc
                limit %(limit)s""",
            params,
        ).fetchall()
        summary = c.execute(
            f"""select ch.kind, count(*) as n from company_change ch
                left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
                where ch.detected_at > now() - make_interval(days => %(days)s) {"and " + UNREAD_SQL if unread else ""}
                {"and coalesce(uc.status, 'new') not in ('new', 'rejected', 'passed')" if tracked else
                 "and (exists (select 1 from company_best cb where cb.company_number = ch.company_number) or coalesce(uc.status, 'new') <> 'new')" if scope == "buy_box" else ""}
                group by 1 order by 2 desc""",
            params,
        ).fetchall()
        unread_n = c.execute(
            f"""select count(*) as n from company_change ch
                left join user_company uc on uc.company_number = ch.company_number and uc.user_id = %(uid)s
                where {' and '.join(w for w in where if w != UNREAD_SQL)} and {UNREAD_SQL}""", params).fetchone()["n"]
    return {"rows": rows, "summary": summary, "unread": unread_n}


@app.post("/api/changes/seen")
def changes_seen():
    """Mark all changes as read."""
    with db.conn() as c:
        c.execute("""insert into app_setting (key, value) values ('changes_seen_at', to_jsonb(now()))
                     on conflict (key) do update set value = excluded.value, updated_at = now()""")
        c.execute("delete from change_read")  # covered by the new time
    return {"ok": True}


class ReadIn(BaseModel):
    ids: list[int]


@app.post("/api/changes/read")
def changes_read(body: ReadIn):
    """Mark some changes read."""
    with db.conn() as c:
        c.execute("""insert into change_read (change_id) select id from company_change where id = any(%s)
                     on conflict do nothing""", (body.ids[:2000],))
    return {"ok": True}


@app.get("/api/searches")
def searches():
    """Saved searches are global. A search that filters by a buy box keeps it
    in its params (bb); buy_box_name is shown as a label."""
    return _rows("""select s.*, b.name as buy_box_name from saved_search s
                    left join buy_box b on b.id = s.buy_box_id
                    where s.user_id = %s order by s.name""", (UID,))


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
        box_id = None
        if params.get("bb", "").isdigit():
            row = c.execute("select id from buy_box where id = %s and user_id = %s", (int(params["bb"]), UID)).fetchone()
            box_id = row["id"] if row else None
            if not row:
                params.pop("bb")
        existing = c.execute(
            "select id from saved_search where user_id = %s and name = %s order by (coalesce(buy_box_id, 0) = %s) desc, id limit 1",
            (UID, name, box_id or 0)).fetchone()
        if existing:
            c.execute("delete from saved_search where user_id = %s and name = %s and id <> %s", (UID, name, existing["id"]))
            return c.execute("update saved_search set params = %s, buy_box_id = %s where id = %s returning *",
                             (json.dumps(params), box_id, existing["id"])).fetchone()
        return c.execute(
            "insert into saved_search (user_id, name, params, buy_box_id) values (%s, %s, %s, %s) returning *",
            (UID, name, json.dumps(params), box_id),
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
            """select uc.*, c.name, c.region, s.score, s.value_low, s.value_high,
                      (select max(created_at) from stage_event e where e.company_number = uc.company_number
                         and e.user_id = uc.user_id and e.to_status = uc.status) as stage_entered_at,
                      (select count(*) filter (where done) from deal_task t where t.company_number = uc.company_number
                         and t.user_id = uc.user_id and t.stage = uc.status) as tasks_done,
                      (select max(created_at) from user_note n where n.company_number = uc.company_number) as last_note
               from user_company uc join company c on c.company_number = uc.company_number
               left join score s on s.company_number = uc.company_number and s.buy_box_id = %s
               where uc.user_id = %s and uc.status <> 'new'
               order by uc.next_action_on nulls last, s.score desc nulls last""",
            (bb["id"], UID),
        ).fetchall()
    for r in rows:
        r["tasks_total"] = len(stages.CHECKLISTS.get(r["status"], []))
    return {"statuses": [x for x in stages.as_json() if x["value"] != "new"],
            "phases": [{"value": k, "label": v} for k, v in stages.PHASES], "rows": rows}


@app.get("/api/reports")
def reports():
    return cached("reports", 300, _reports)


def _reports():
    with db.conn() as c:
        bb = scoring.active_buy_box(c)
        p = {"bb": bb["id"], "uid": UID}
        staff = c.execute(
            """
            select b.band, b.ord, count(l.company_number) as n from (values
              ('0–4',0,0,4),('5–9',1,5,9),('10–19',2,10,19),('20–49',3,20,49),('50–99',4,50,99),('100+',5,100,1000000)) b(band,ord,lo,hi)
            left join (select l.company_number, l.employees from company_latest l
                       join score sc on sc.company_number = l.company_number and sc.buy_box_id = %(bb)s
                       where not sc.excluded) l on l.employees between b.lo and b.hi
            group by b.band, b.ord order by b.ord""", p).fetchall()
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


@app.post("/api/companies/{num}/fetch-details")
def fetch_details(num: str):
    """Charges and share-issue filings from the Companies House API (needs CH_API_KEY)."""
    from . import chapi

    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise HTTPException(404, "Company not found")
        try:
            r = chapi.fetch(c, num)
        except chapi.NoKey as e:
            raise HTTPException(400, str(e))
        return {"fetched_charges": r["charges"], "fetched_filings": r["filings"], "fetched_officers": r["officers"],
                "fetched_shareholders": r["shareholders"], "error": r["error"], **chapi.details(c, num)}


@app.get("/api/companies/{num}/research-brief")
def research_brief(num: str):
    """Names, address, owners, related companies and search queries for
    finding the company online (used by Claude and the website finder)."""
    from . import website

    with db.conn() as c:
        b = website.brief(c, num)
    if not b:
        raise HTTPException(404, "Company not found")
    return b


class WebsiteCheckIn(BaseModel):
    url: str | None = None


@app.post("/api/companies/{num}/find-website")
def find_website(num: str, body: WebsiteCheckIn | None = None):
    """Check a given site, or try likely domains, and save a site confirmed
    by the company number or postcode as the company's website."""
    from . import website

    with db.conn() as c:
        b = website.brief(c, num)
        if not b:
            raise HTTPException(404, "Company not found")
        names = [b["name"], *b["previous_names"], *b["parent_companies"], *b["subsidiaries"]]
        results = ([website.check(body.url, b["company_number"], b["postcode"], names)] if body and body.url
                   else website.find(names, b["company_number"], b["postcode"]))
        best = next((r for r in results if r.get("confidence") in ("high", "medium")), None)
        saved = None
        added = []
        if best:
            saved = enrich.save_enrichment(
                c, b["company_number"], source_url=best.get("page") or best["url"], website=best["url"],
                confidence=best["confidence"], source_label=f"Website check: {best['evidence']}", by="website check")["saved"]
            # Offices listed on the company's own (confirmed) site: trading
            # addresses, added to any already saved. The registered office is skipped.
            cur = c.execute("select locations from enrichment where company_number = %s", (b["company_number"],)).fetchone()
            locs = list((cur or {}).get("locations") or [])
            have = {l.get("postcode") for l in locs} | {b["postcode"]}
            for a in best.get("addresses") or []:
                if a["postcode"] not in have:
                    locs.append({"kind": "office", "name": None, "address": a["address"], "postcode": a["postcode"]})
                    have.add(a["postcode"])
                    added.append(a)
            if added:
                enrich.save_enrichment(c, b["company_number"], source_url=added[0]["page"], locations=locs,
                                       confidence=best["confidence"], source_label="Offices listed on the company's website",
                                       by="website check")
    return {"results": results, "saved": saved, "offices_added": added,
            "message": (f"Saved {best['url']} ({best['evidence']})." + (f" Added {len(added)} office address(es) from the site." if added else "") if best else
                        "No site could be confirmed. Ask Claude to search using the research brief, or enter one you know.")}


@app.get("/api/website-check")
def website_check_summary():
    """Totals so far: companies checked, confirmed sites, possible ones, none found."""
    with db.conn() as c:
        r = c.execute("""select count(*) as checked,
                                count(*) filter (where result = 'confirmed') as confirmed,
                                count(*) filter (where result = 'possible') as possible,
                                count(*) filter (where result = 'none') as none,
                                max(checked_at) as last_at from website_check""").fetchone()
        r["with_website"] = c.execute("select count(*) as n from enrichment where website is not null").fetchone()["n"]
    return r


@app.post("/api/website-check")
def website_check_batch(scope: str = "targets", limit: int = 200):
    """Find and confirm websites for your pipeline or top targets, as a background job."""
    from . import jobs

    with db.conn() as c:
        cur = jobs.current(c)
        if cur and cur["status"] == "running":
            raise HTTPException(409, "Another job is running; try again when it finishes")
    _run_detached(["website-check", "--scope", scope if scope in ("pipeline", "targets", "active") else "targets",
                   "--limit", str(max(0, limit))], after=clear_cache)
    return {"started": True}


@app.post("/api/ch-details")
def ch_details_batch(scope: str = "pipeline", limit: int = 200):
    """Fetch Companies House API details for your pipeline or top targets, as a background job."""
    from . import chapi, jobs

    if not chapi.enabled():
        raise HTTPException(400, "Add your Companies House API key (CH_API_KEY) to the stack first")
    with db.conn() as c:
        cur = jobs.current(c)
        if cur and cur["status"] == "running":
            raise HTTPException(409, "Another job is running; try again when it finishes")
    _run_detached(["ch-details", "--scope", "targets" if scope == "targets" else "pipeline",
                   "--limit", str(max(1, min(limit, 2000)))], after=clear_cache)
    return {"started": True}


@app.post("/api/companies/{num}/ch-check")
def ch_check(num: str):
    """On opening a profile: a light check against Companies House (a full
    fetch if never fetched or something changed). Returns the details."""
    from . import chapi

    if not chapi.enabled():
        raise HTTPException(400, "No Companies House API key set (CH_API_KEY)")
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise HTTPException(404, "Company not found")
        r = chapi.check(c, num)
        c.commit()
        return {"changed": bool(r.get("changed") or r.get("full")), "changes": r.get("changes") or 0,
                **chapi.details(c, num)}


@app.get("/api/ch-sync")
def ch_sync_status():
    from . import chsync

    with db.conn() as c:
        return chsync.status(c)


class SyncIn(BaseModel):
    paused: bool


@app.put("/api/ch-sync")
def ch_sync_set(body: SyncIn):
    from . import chsync

    with db.conn() as c:
        chsync.set_setting(c, "ch_sync_paused", body.paused)
        return chsync.status(c)


# ---------------------------------------------------------------- owners

@app.get("/api/owners")
def owners(q: str, limit: int = 50):
    """People and companies named as owners (PSCs) whose name contains every
    word given, with how many companies each one controls."""
    words = [w for w in q.strip().upper().split() if w]
    if not words or sum(len(w) for w in words) < 3:
        return {"rows": []}
    conds = " and ".join(["p.name ilike %s"] * len(words))
    with db.conn() as c:
        rows = c.execute(
            f"""select p.id, p.name, p.kind, p.birth_year, p.birth_month, p.country_registered, p.registration_number,
                       (select count(*) from company_person cp where cp.person_id = p.id and cp.ceased_on is null) as companies,
                       (select count(*) from company_person cp where cp.person_id = p.id and cp.ceased_on is not null) as past
                from person p
                where {conds}
                order by (select count(*) from company_person cp where cp.person_id = p.id and cp.ceased_on is null) desc, p.name
                limit %s""",
            (*[f"%{_like_escape(w)}%" for w in words], min(limit, 200))).fetchall()
    return {"rows": rows}


@app.get("/api/owners/{pid}")
def owner(pid: int):
    """One owner and every company they are (or were) recorded as controlling,
    with your status and the best score for each."""
    with db.conn() as c:
        p = c.execute("select * from person where id = %s", (pid,)).fetchone()
        if not p:
            raise HTTPException(404, "Owner not found")
        rows = c.execute(
            """select c.company_number, c.name, c.status as company_status, c.postcode, c.region, c.sic_codes,
                      c.incorporation_date, cp.natures, cp.notified_on, cp.ceased_on,
                      l.employees, o.ownership_type, e.revenue_low, e.revenue_high, e.basis as revenue_basis, e.method as revenue_method,
                      cb.score, cb.box_name, coalesce(uc.status, 'new') as status
               from company_person cp join company c on c.company_number = cp.company_number
               left join company_latest l on l.company_number = c.company_number
               left join company_ownership o on o.company_number = c.company_number
               left join estimate e on e.company_number = c.company_number
               left join company_best cb on cb.company_number = c.company_number
               left join user_company uc on uc.company_number = c.company_number and uc.user_id = %s
               where cp.person_id = %s
               order by cp.ceased_on nulls first, cb.score desc nulls last, c.name""", (UID, pid)).fetchall()
        # Companies this owner holds through other companies (from the traced ownership).
        indirect = c.execute(
            """with held as (
                   select o.company_number, u.value as owner from company_ownership o
                   cross join lateral jsonb_array_elements(o.ultimate_owners) u
                   where o.ultimate_owners @> %s::jsonb and (u.value ->> 'person_id')::bigint = %s
                     and jsonb_array_length(u.value -> 'via') > 0)
               select h.company_number, c.name, c.status as company_status, cb.score, coalesce(uc.status, 'new') as status,
                      (select string_agg(coalesce(c2.name, v.x), ' → ' order by v.o)
                       from jsonb_array_elements_text(h.owner -> 'via') with ordinality v(x, o)
                       left join company c2 on c2.company_number = v.x) as via
               from held h join company c on c.company_number = h.company_number
               left join company_best cb on cb.company_number = h.company_number
               left join user_company uc on uc.company_number = h.company_number and uc.user_id = %s
               order by cb.score desc nulls last limit 200""", (json.dumps([{"person_id": pid}]), pid, UID)).fetchall()
        outside = c.execute("select count(*) as n from parent_psc where person_id = %s and ceased_on is null", (pid,)).fetchone()["n"]
    return {"owner": p, "companies": rows, "indirect": indirect, "outside_register": outside}


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


def _box(c, bb_id: int | None):
    if bb_id:
        row = c.execute("select * from buy_box where id = %s and user_id = %s", (bb_id, UID)).fetchone()
        if not row:
            raise HTTPException(404, "Buy box not found")
        return dict(row)
    return scoring.active_buy_box(c)


@app.get("/api/buybox")
def get_buybox(id: int | None = None):
    with db.conn() as c:
        bb = _box(c, id)
    return {"id": bb["id"], "name": bb["name"], "description": bb.get("description"),
            "criteria": scoring.merged(bb["criteria"]), "defaults": scoring.DEFAULT_CRITERIA}


class BuyBoxIn(BaseModel):
    name: str | None = None
    criteria: dict


def _start_scoring(bb_id: int | None = None) -> bool:
    """Score buy boxes that need it (scored_at is null) in one background job.
    If any job is already running, nothing starts now: the boxes stay marked
    and are scored when that job finishes. Returns True if it had to wait."""
    import threading

    from . import jobs

    with db.conn() as c:
        if bb_id:
            c.execute("update buy_box set scored_at = null where id = %s", (bb_id,))
        cur = jobs.current(c)
        if cur and cur["status"] == "running":
            return True

    # In its own process, not a thread: scoring is Python-heavy and would
    # otherwise slow every web request while it runs (the interpreter lock).
    _run_detached(["score-pending"], after=clear_cache)
    return False


def score_pending(c) -> list[str]:
    """Score every buy box marked as needing it, then rebuild links and
    summaries, as one tracked job. Used by the score-pending command."""
    from . import jobs

    pending = [dict(r) for r in c.execute(
        "select * from buy_box where user_id = %s and scored_at is null order by id", (UID,))]
    if not pending:
        return []
    job = jobs.Job("scoring", [f"Scoring “{b['name']}”" for b in pending] + ["Ownership links", "Summaries"])
    try:
        # Signals (recently sold, possible buyer) once, before scoring uses them.
        c.execute("select ao_refresh_company_signals()")
        # Which companies were in a buy box before, to see if any are new.
        c.execute("drop table if exists scope_before")
        c.execute("create temp table scope_before as select company_number from company_best")
        c.execute("create index on scope_before (company_number)")
        for b in pending:
            job.stage(f"Scoring “{b['name']}”")
            scoring.rescore(c, b, progress=lambda msg, frac=None: job.progress(frac, msg))
            c.commit()
        new_in_scope = c.execute(
            """select count(*) as n from company_best cb
               where not exists (select 1 from scope_before s where s.company_number = cb.company_number)""").fetchone()["n"]
        if new_in_scope:
            # Shared-owner and shared-address links are built for companies in a
            # buy box, so new ones need them; otherwise nothing has changed.
            job.stage("Ownership links")
            from .ownership import rebuild_links

            rebuild_links(c)
            c.commit()
        else:
            job.skip("Ownership links", "not needed: no new companies in your buy boxes")
        job.stage("Summaries")
        refresh_stats(c, data=False)
        c.commit()
        job.finish({"buy_boxes": [b["name"] for b in pending]})
    except Exception as e:
        job.finish(None, status="failed", error=str(e))
        raise
    return [b["name"] for b in pending]


def _run_detached(args: list[str], after=None):
    """Run an acquireos command in a separate process (so heavy Python work
    never competes with web requests for the interpreter) and call `after`
    when it ends. Progress is in the job table as usual."""
    import subprocess
    import sys
    import threading

    proc = subprocess.Popen([sys.executable, "-m", "acquireos.cli", *args], stdout=sys.stderr, stderr=sys.stderr)

    def watch():
        proc.wait()
        if after:
            try:
                after()
            except Exception:
                pass

    threading.Thread(target=watch, daemon=True).start()
    return proc


def _small_db(c) -> bool:
    return c.execute("select count(*) as n from company").fetchone()["n"] <= 100_000


@app.put("/api/buybox")
def put_buybox(body: BuyBoxIn, id: int | None = None):
    with db.conn() as c:
        bb = _box(c, id)
        criteria = scoring.merged(body.criteria)
        c.execute(
            "update buy_box set criteria = %s, name = coalesce(%s, name), updated_at = now() where id = %s",
            (json.dumps(criteria), body.name, bb["id"]),
        )
        bb = _box(c, bb["id"])
        if _small_db(c):
            n = scoring.rescore(c, bb)
            return {"rescored": n, "criteria": criteria, "background": False}
        c.execute("update buy_box set scored_at = null where id = %s", (bb["id"],))
        total = c.execute("select count(*) as n from company").fetchone()["n"]
    queued = _start_scoring()
    return {"rescored": total, "criteria": criteria, "background": True, "queued": queued}


@app.get("/api/buyboxes")
def buyboxes():
    with db.conn() as c:
        scoring.active_buy_box(c)
        return c.execute(
            """select b.id, b.name, b.description, b.template, b.is_active, b.scored_at, b.updated_at,
                      (select count(*) from score s where s.buy_box_id = b.id and not s.excluded) as in_scope,
                      (select count(*) from score s where s.buy_box_id = b.id and not s.excluded and s.score >= 70) as strong,
                      (select count(*) from saved_search ss where ss.buy_box_id = b.id) as searches
               from buy_box b where b.user_id = %s order by b.id""", (UID,)).fetchall()


@app.get("/api/buybox-templates")
def buybox_templates():
    return [{"key": k, "label": t["label"], "description": t["description"]} for k, t in scoring.TEMPLATES.items()]


class NewBuyBox(BaseModel):
    name: str
    source: str = "blank"          # blank | copy | template
    template: str | None = None
    copy_id: int | None = None


@app.post("/api/buyboxes")
def create_buybox(body: NewBuyBox):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Give the buy box a name")
    with db.conn() as c:
        desc = None
        if body.source == "copy" and body.copy_id:
            src = c.execute("select * from buy_box where id = %s and user_id = %s", (body.copy_id, UID)).fetchone()
            if not src:
                raise HTTPException(404, "Buy box to copy not found")
            criteria, desc = scoring.merged(src["criteria"]), src["description"]
        elif body.source == "template":
            if body.template not in scoring.TEMPLATES:
                raise HTTPException(400, "Unknown template")
            criteria = scoring.template_criteria(body.template)
            desc = scoring.TEMPLATES[body.template]["description"]
        else:
            criteria = json.loads(json.dumps(scoring.DEFAULT_CRITERIA))
        c.execute("update buy_box set is_active = false where user_id = %s", (UID,))
        bb = c.execute(
            """insert into buy_box (user_id, name, criteria, is_active, description, template)
               values (%s, %s, %s, true, %s, %s) returning *""",
            (UID, name, json.dumps(criteria), desc, body.template if body.source == "template" else None),
        ).fetchone()
        if _small_db(c):
            scoring.rescore(c, dict(bb))
            return {**dict(bb), "background": False}
    queued = _start_scoring(bb["id"])
    return {**dict(bb), "background": True, "queued": queued}


@app.post("/api/buyboxes/{bb_id}/activate")
def activate_buybox(bb_id: int):
    with db.conn() as c:
        bb = c.execute("select * from buy_box where id = %s and user_id = %s", (bb_id, UID)).fetchone()
        if not bb:
            raise HTTPException(404, "Buy box not found")
        c.execute("update buy_box set is_active = (id = %s) where user_id = %s", (bb_id, UID))
    return {"ok": True, "scoring": False}


class BuyBoxMeta(BaseModel):
    name: str | None = None
    description: str | None = None


@app.patch("/api/buyboxes/{bb_id}")
def rename_buybox(bb_id: int, body: BuyBoxMeta):
    with db.conn() as c:
        row = c.execute(
            """update buy_box set name = coalesce(%s, name), description = coalesce(%s, description), updated_at = now()
               where id = %s and user_id = %s returning id, name, description""",
            (body.name.strip() if body.name else None, body.description, bb_id, UID)).fetchone()
        if row and body.name:
            c.execute("update company_best set box_name = %s where buy_box_id = %s", (row["name"], bb_id))
            c.execute("""update company_best cb set boxes = array(
                             select b.name from score s join buy_box b on b.id = s.buy_box_id
                             where s.company_number = cb.company_number and not s.excluded order by s.score desc)
                         where cb.company_number in (select company_number from score where buy_box_id = %s and not excluded)""",
                      (bb_id,))
    clear_cache()
    return row


@app.delete("/api/buyboxes/{bb_id}")
def delete_buybox(bb_id: int):
    with db.conn() as c:
        n = c.execute("select count(*) as n from buy_box where user_id = %s", (UID,)).fetchone()["n"]
        if n <= 1:
            raise HTTPException(400, "You need at least one buy box")
        was_active = c.execute("select is_active from buy_box where id = %s and user_id = %s",
                               (bb_id, UID)).fetchone()
        if not was_active:
            raise HTTPException(404, "Buy box not found")
        c.execute("delete from buy_box where id = %s and user_id = %s", (bb_id, UID))
        if was_active["is_active"]:
            c.execute("""update buy_box set is_active = true where id = (
                             select id from buy_box where user_id = %s order by id limit 1)""", (UID,))
        scoring.refresh_best(c)
    clear_cache()
    return {"ok": True}


# ----------------------------------------------------------- your own scores

class ManualIn(BaseModel):
    key: str
    value: int | None = None
    note: str | None = None


@app.put("/api/companies/{num}/manual")
def set_manual(num: str, body: ManualIn):
    if body.value is not None and not 0 <= body.value <= 5:
        raise HTTPException(400, "Score must be 0 to 5")
    with db.conn() as c:
        if not c.execute("select 1 from company where company_number = %s", (num,)).fetchone():
            raise HTTPException(404, "Company not found")
        if body.value is None:
            c.execute("delete from manual_score where user_id = %s and company_number = %s and criterion_key = %s",
                      (UID, num, body.key))
        else:
            c.execute(
                """insert into manual_score (user_id, company_number, criterion_key, value, note)
                   values (%s, %s, %s, %s, %s)
                   on conflict (user_id, company_number, criterion_key) do update set value = excluded.value,
                     note = coalesce(excluded.note, manual_score.note), updated_at = now()""",
                (UID, num, body.key, body.value, body.note),
            )
        scoring.rescore_company_all_boxes(c, num)
        sc = c.execute("""select s.score, s.coverage, s.excluded, s.exclusion, s.reasons from score s
                          join buy_box b on b.id = s.buy_box_id and b.is_active
                          where s.company_number = %s""", (num,)).fetchone()
        values = {r["criterion_key"]: r for r in c.execute(
            "select criterion_key, value, note, updated_at from manual_score where user_id = %s and company_number = %s",
            (UID, num))}
    return {"score": sc, "values": values}


@app.get("/api/review")
def review_queue(status: str = "new", min_score: float | None = None, limit: int = 300,
                 sic: str | None = None, region: str | None = None, bb: str = "all"):
    """Companies to review one by one, inside a buy box (or any), best first."""
    r = companies(status=status, min_score=min_score, sic=sic, region=region, limit=min(limit, 1000),
                  bb=bb, in_box=True)
    return {"total": r["total"], "rows": [{"company_number": x["company_number"], "name": x["name"],
                                           "score": x["score"]} for x in r["rows"]]}


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
    with db.conn(dedicated=True) as c:
        try:
            from .importers import register
            from .importers.tables import open_table

            if body.kind == "companies" and not body.only_existing and (
                    path.suffix == ".zip" or path.stat().st_size > 50_000_000) and register.is_register(open_table(path)[0]):
                result = register.load(c, path, full=False)
            else:
                kwargs = {"only_existing": body.only_existing} if body.kind == "companies" else {}
                result = IMPORTERS[body.kind].run(c, path, mapping=body.mapping, sheet=body.sheet, source=body.filename, **kwargs)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if body.kind == "companies":
            rebuild_ownership(c)
        scoring.rescore(c)
        refresh_stats(c)
    path.unlink(missing_ok=True)
    return result


def _job_view(row):
    if not row:
        return {"running": False}
    r = dict(row)
    r["running"] = r["status"] == "running"
    return r


@app.get("/api/jobs/current")
def job_current():
    from . import jobs

    with db.conn() as c:
        return _job_view(jobs.current(c))


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: int):
    with db.conn() as c:
        c.execute("update job set cancel_requested = true where id = %s and status = 'running'", (job_id,))
    return {"ok": True, "message": "Stopping after the current step's batch; loaded data is kept."}


@app.post("/api/refresh")
def start_refresh(months: int = 1, reread: bool = False):
    """Start the Companies House download and load in the background."""
    import threading

    from . import fetch, jobs

    with db.conn() as c:
        cur = jobs.current(c)
        if cur and cur["status"] == "running":
            raise HTTPException(409, "A refresh is already running")

    def after():
        clear_cache()
        _start_scoring()  # any buy box changed while the refresh ran

    _run_detached(["fetch", "all", "--months", str(max(1, min(months, 72)))] + (["--reread"] if reread else []), after=after)
    import time

    time.sleep(0.5)  # let the job row appear
    return job_current()


@app.get("/api/refresh")
def refresh_status():
    return job_current()


@app.get("/api/coverage")
def coverage():
    """How much of the register has owners and accounts loaded, and which
    files they came from, so gaps can be explained rather than guessed at."""
    return cached("coverage", 3600, _coverage)


def _coverage():
    with db.conn() as c:
        return stats_get(c, "coverage", _coverage_compute)


def _coverage_compute(c):
    if True:
        n = c.execute(
            """select count(*) as active,
                      count(o.company_number) filter (where o.ownership_type <> 'unknown') as owners_traced,
                      count(ps.company_number) as with_psc,
                      count(l.company_number) as with_accounts,
                      count(l.employees) as with_staff,
                      count(l.turnover) as with_turnover,
                      count(*) filter (where c.incorporation_date > current_date - interval '21 months') as too_new
               from company c
               left join company_ownership o on o.company_number = c.company_number
               left join company_latest l on l.company_number = c.company_number
               left join (select distinct company_number from company_person where ceased_on is null) ps
                      on ps.company_number = c.company_number
               where coalesce(c.status, 'active') ilike 'active%%'""").fetchone()
        files = c.execute(
            """select kind, filename, finished_at, rows_ok from import_run
               where kind in ('register', 'psc', 'accounts') and finished_at is not null
               order by finished_at desc""").fetchall()
    return {**n, "accounts_files": [f for f in files if f["kind"] == "accounts"],
            "psc_file": next((f for f in files if f["kind"] == "psc"), None),
            "register_file": next((f for f in files if f["kind"] == "register"), None)}


@app.get("/api/imports")
def imports():
    return _rows("select * from import_run order by id desc limit 50")


EXPORT_CAP = 50_000
_EXPORT_COLS = [
    ("Company number", "company_number"), ("Name", "name"), ("Company status", "company_status"),
    ("Postcode", "postcode"), ("Region", "region"), ("SIC codes", "sic_codes"), ("Incorporated", "incorporation_date"),
    ("Accounts filed", "accounts_category"), ("Latest accounts to", "period_end"), ("Staff", "employees"),
    ("Revenue low", "revenue_low"), ("Revenue high", "revenue_high"), ("Revenue basis", "revenue_basis"),
    ("Revenue method", "revenue_method"),
    ("Net assets", "net_assets"), ("Ownership", "ownership_type"), ("Oldest owner born", "oldest_birth_year"),
    ("Charges outstanding", "charges_outstanding"), ("Score", "score"), ("Buy box", "box_name"),
    ("Indicative value low", "value_low"), ("Indicative value high", "value_high"), ("Value basis", "value_basis"),
    ("My status", "status"), ("My rating", "rating"), ("Next action", "next_action"), ("Next action on", "next_action_on"),
]


@app.get("/api/export.csv")
def export_csv(request: Request):
    """The list you are looking at, with the same filters and sort, as CSV
    (up to EXPORT_CAP rows), streamed so a large export never sits in memory."""
    import inspect

    sig = inspect.signature(companies)
    kw: dict = {}
    for k, v in request.query_params.items():
        if k not in sig.parameters or k in ("limit", "offset", "format") or v == "":
            continue
        ann = str(sig.parameters[k].annotation)
        try:
            kw[k] = (v.lower() in ("1", "true", "yes") if "bool" in ann else int(v) if "int" in ann
                     else float(v) if "float" in ann else v)
        except ValueError:
            continue

    def rows():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([h for h, _ in _EXPORT_COLS] + ["My latest note", "Companies House"])
        yield "\ufeff" + buf.getvalue()  # BOM so Excel reads £ and accents correctly
        sent = 0
        while sent < EXPORT_CAP:
            chunk = companies(**kw, limit=1000, offset=sent)["rows"]
            if not chunk:
                break
            with db.conn() as c:
                notes = {r["company_number"]: r["body"] for r in c.execute(
                    """select distinct on (company_number) company_number, body from user_note
                       where user_id = %s and company_number = any(%s) order by company_number, created_at desc""",
                    (UID, [r["company_number"] for r in chunk]))}
            buf = io.StringIO()
            w = csv.writer(buf)
            for r in chunk[: EXPORT_CAP - sent]:
                w.writerow([(", ".join(map(str, r.get(k) or [])) if isinstance(r.get(k), list) else r.get(k))
                            for _, k in _EXPORT_COLS]
                           + [notes.get(r["company_number"]),
                              f"https://find-and-update.company-information.service.gov.uk/company/{r['company_number']}"])
            sent += len(chunk)
            yield buf.getvalue()
            if len(chunk) < 1000:
                break

    return StreamingResponse(rows(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=acquireos-{date.today()}.csv"})


def _cell(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


# --------------------------------------------------------------------- MCP

from .mcp_server import server as _mcp_server  # noqa: E402

_MCP_ROUTES: list = []


def _install_mcp():
    """Create the /mcp route (stateless Streamable HTTP, JSON responses) and
    put it ahead of the web app's catch-all route. host=0.0.0.0 turns off the
    SDK's localhost-only Host check; access is controlled by API_TOKEN."""
    mcp_app = _mcp_server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, host="0.0.0.0",
    )
    for r in _MCP_ROUTES:
        if r in app.router.routes:
            app.router.routes.remove(r)
    _MCP_ROUTES[:] = list(mcp_app.routes)
    for r in reversed(_MCP_ROUTES):
        app.router.routes.insert(0, r)
    return _mcp_server.session_manager


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
