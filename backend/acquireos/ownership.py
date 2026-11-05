"""Work out who really owns each company, and how companies link together.

Everything here is recomputed from imported data and can be rebuilt at any
time. It never touches user-owned tables.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from . import normalise as n
from .importers.psc import UK_PLACES

EOT_RE = re.compile(r"EMPLOYEE\s+OWNERSHIP|\bEOT\b|EMPLOYEE\s+BENEFIT\s+TRUST|\bEBT\b", re.I)
TRUST_RE = re.compile(r"\bTRUST(EES?)?\b|\bSETTLEMENT\b", re.I)
INVESTOR_RE = re.compile(
    r"\b(CAPITAL|VENTURES?|EQUITY|INVESTMENTS?|INVESTORS?|FUND|NOMINEES?|PARTNERS LLP|GP LIMITED|PRIVATE EQUITY)\b",
    re.I,
)
# The PSC register started on 6 April 2016, so a notified date of that day
# means "already an owner then", not a recent change.
PSC_REGIME_START = date(2016, 4, 6)
RECENT = timedelta(days=730)

TYPE_ORDER = ["eot", "investor_backed", "foreign_owned", "trust", "group_owned", "owner_held", "unknown"]
TYPE_LABELS = {
    "owner_held": "Owner-held",
    "group_owned": "Group-owned",
    "investor_backed": "Investor-backed",
    "eot": "Employee-owned (EOT)",
    "trust": "Held in trust",
    "foreign_owned": "Foreign parent",
    "unknown": "Unknown",
}


def rebuild(conn, today: date | None = None) -> dict:
    """Recompute company_ownership and ownership links with set-based SQL, so
    it scales to every company on the register."""
    today = today or date.today()
    _build_walk(conn)
    _ownership_from_walk(conn, today)
    counts = {r["ownership_type"]: r["n"] for r in conn.execute(
        "select ownership_type, count(*) as n from company_ownership group by 1")}
    rebuild_links(conn, walk_ready=True)
    return {"ownership": counts}


def _build_walk(conn):
    conn.execute("drop table if exists own_edges; drop table if exists own_walk")
    # Who owns what: a company's own PSC records, or for parents outside the
    # company table, the PSCs stored in parent_psc.
    conn.execute("""
        create temp table own_edges as
        select company_number as owned, person_id, natures from company_person
        where role = 'psc' and ceased_on is null
        union all
        select pp.parent_number, pp.person_id, pp.natures from parent_psc pp
        where pp.ceased_on is null and not exists (
            select 1 from company_person cp where cp.company_number = pp.parent_number
              and cp.role = 'psc' and cp.ceased_on is null)""")
    conn.execute("create index on own_edges (owned)")
    conn.execute("analyze own_edges")
    conn.execute("""
        create temp table own_walk as
        with recursive walk (root, person_id, depth, path) as (
            select e.owned, e.person_id, 0, array[e.owned]
            from own_edges e join company c on c.company_number = e.owned
            union all
            select w.root, e2.person_id, w.depth + 1, w.path || p.registration_number
            from walk w
            join person p on p.id = w.person_id and p.kind <> 'individual' and p.registration_number is not null
            join own_edges e2 on e2.owned = p.registration_number
            where w.depth < 5 and not (p.registration_number = any (w.path))
        )
        select w.root, w.person_id, w.depth, w.path, p.kind, p.name, p.birth_year, p.birth_month,
               p.registration_number, p.country_registered,
               (p.kind <> 'individual' and (p.registration_number is null or not exists (
                    select 1 from own_edges e where e.owned = p.registration_number)
                or p.registration_number = any (w.path) or w.depth >= 5)) as dead_end
        from walk w join person p on p.id = w.person_id""")
    conn.execute("create index on own_walk (root)")
    conn.execute("analyze own_walk")


def _ownership_from_walk(conn, today):

    uk = "('" + "','".join(sorted(UK_PLACES - {""})) + "')"
    conn.execute("delete from company_ownership")
    conn.execute(rf"""
        with agg as (
            select root,
              bool_or(kind <> 'individual' and name ~* '(EMPLOYEE\s+OWNERSHIP|\mEOT\M|EMPLOYEE\s+BENEFIT\s+TRUST|\mEBT\M)') as eot,
              bool_or(kind <> 'individual' and not name ~* '(EMPLOYEE\s+OWNERSHIP|\mEOT\M|EMPLOYEE\s+BENEFIT\s+TRUST|\mEBT\M)'
                      and (kind = 'legal' or name ~* '(\mTRUST(EES?)?\M|\mSETTLEMENT\M)')) as trust_node,
              bool_or(kind <> 'individual' and name ~* '\m(CAPITAL|VENTURES?|EQUITY|INVESTMENTS?|INVESTORS?|FUND|NOMINEES?|PARTNERS LLP|GP LIMITED|PRIVATE EQUITY)\M') as investor,
              bool_or(kind = 'corporate' and coalesce(country_registered, '') <> ''
                      and lower(trim(country_registered)) not in {uk}
                      and lower(country_registered) !~ '(england|wales|scotland|united kingdom)') as foreign_parent,
              bool_or(depth = 0 and kind <> 'individual' and registration_number is not null) as via_holdco,
              bool_or(kind = 'corporate' and dead_end) as unresolved_corporate,
              count(distinct person_id) filter (where kind = 'individual') as individuals,
              bool_or(kind = 'individual' and depth > 0) as indirect,
              min(birth_year) filter (where kind = 'individual') as oldest,
              (jsonb_agg(jsonb_build_object('name', name, 'birth_year', birth_year, 'birth_month', birth_month,
                    'person_id', person_id, 'via', to_jsonb(path[2:]))) filter (where kind = 'individual')) as people,
              (jsonb_agg(jsonb_build_object('name', name, 'kind', kind, 'via', to_jsonb(path[2:]), 'unresolved', true))
                    filter (where kind <> 'individual' and dead_end)) as dead
            from own_walk group by root
        ), direct as (
            select company_number as root,
                   bool_or(ceased_on is null) as has_active,
                   bool_or(ceased_on is null and exists (select 1 from unnest(natures) nn where nn like '%%as-trust%%')) as trust_nature,
                   bool_or((ceased_on is not null and ceased_on >= %(recent)s)
                        or (notified_on is not null and notified_on <> '2016-04-06' and notified_on >= %(recent)s)) as recent
            from company_person where role = 'psc' group by company_number
        ), base as (
            select c.company_number,
                   coalesce(a.eot, false) as eot,
                   coalesce(a.trust_node, false) or coalesce(d.trust_nature, false) as trust,
                   coalesce(a.investor, false) as investor,
                   coalesce(a.foreign_parent, false) as foreign_parent,
                   coalesce(a.via_holdco, false) as via_holdco,
                   coalesce(a.unresolved_corporate, false) as unresolved_corporate,
                   coalesce(a.individuals, 0) as individuals,
                   coalesce(a.indirect, false) as indirect,
                   a.oldest, coalesce(d.recent, false) as recent, coalesce(d.has_active, false) as has_active,
                   coalesce(a.people, '[]'::jsonb) || coalesce(a.dead, '[]'::jsonb) as owners
            from company c
            left join agg a on a.root = c.company_number
            left join direct d on d.root = c.company_number
        ), typed as (
            select *, case
                when eot then 'eot'
                when investor then 'investor_backed'
                when foreign_parent then 'foreign_owned'
                when trust and individuals = 0 then 'trust'
                when unresolved_corporate and individuals = 0 then 'group_owned'
                when individuals > 4 and indirect then 'group_owned'
                when individuals > 0 then 'owner_held'
                else 'unknown' end as otype
            from base
        )
        insert into company_ownership (company_number, ownership_type, flags, owner_count, oldest_birth_year,
                                       ultimate_owners, explanation)
        select company_number, otype,
               array_remove(array[
                   case when eot then 'eot' end, case when foreign_parent then 'foreign_parent' end,
                   case when investor then 'investor' end, case when recent then 'recent_change' end,
                   case when not has_active then 'no_psc_data' end, case when trust then 'trust' end,
                   case when via_holdco then 'via_holdco' end], null)::text[],
               individuals, oldest, owners,
               case otype
                   when 'owner_held' then individuals || ' individual owner(s), held '
                        || case when via_holdco then 'through a holding company' else 'directly' end || '.'
                   when 'unknown' then 'No active owner records found in the PSC data imported so far.'
                   else 'Classed as ' || lower(case otype when 'group_owned' then 'Group-owned'
                        when 'investor_backed' then 'Investor-backed' when 'eot' then 'Employee-owned (EOT)'
                        when 'trust' then 'Held in trust' when 'foreign_owned' then 'Foreign parent' end)
                        || ' from the owner records.' end
        from typed""", {"recent": today - RECENT})


# Above this many companies, links wait until scores exist (so they can be
# limited to companies in the buy box) instead of pairing the whole register.
UNSCOPED_LINK_LIMIT = 100_000


def rebuild_links(conn, walk_ready: bool = False):
    """Ownership, shared-owner and shared-address links. Shared-owner and
    shared-address links are only built where at least one company is in the
    buy box (or for everything before any scoring has run), to keep the
    number of pairs sensible across the whole register."""
    if not walk_ready:
        _build_walk(conn)
    scored = conn.execute("select 1 from score limit 1").fetchone() is not None
    if not scored and conn.execute("select count(*) as n from company").fetchone()["n"] > UNSCOPED_LINK_LIMIT:
        return  # built after scoring, limited to the buy box
    conn.execute("delete from company_link where kind in ('owned_by', 'shared_owner')")
    conn.execute("""
        insert into company_link (a, b, b_name, kind, via, confidence, evidence)
        select distinct on (w.root, w.registration_number) w.root, w.registration_number, w.name, 'owned_by', '',
               'confirmed', 'Registration number on the PSC record'
        from own_walk w where w.depth = 0 and w.kind <> 'individual' and w.registration_number is not null
        on conflict do nothing""")
    conn.execute("""
        insert into company_link (a, b, b_name, kind, via, confidence, evidence)
        select distinct on (w.root, c.company_number) w.root, c.company_number, w.name, 'owned_by', '', 'likely',
               'Parent name matches a company in your list; no registration number filed'
        from own_walk w join company c on ao_company_name_key(c.name) = ao_company_name_key(w.name)
        where w.depth = 0 and w.kind = 'corporate' and w.registration_number is null and c.company_number <> w.root
        on conflict do nothing""")
    scope = """exists (select 1 from score sc where sc.company_number = x.root and not sc.excluded)
               or exists (select 1 from user_company uc where uc.company_number = x.root and uc.status <> 'new')""" if scored else "true"
    conn.execute(f"""
        with owners as (
            select distinct w.root, w.person_id, w.name, w.birth_year, w.birth_month
            from own_walk w where w.kind = 'individual'
        ), sized as (
            select o.*, count(*) over (partition by person_id) as n from owners o
        ), pairs as (
            select x.root as a, y.root as b, x.name, x.birth_year, x.birth_month
            from sized x join sized y on x.person_id = y.person_id and x.root < y.root
            where x.n between 2 and 25 and ({scope.replace('x.root', 'x.root')} or {scope.replace('x.root', 'y.root')})
        )
        insert into company_link (a, b, b_name, kind, via, confidence, evidence)
        select distinct on (p.a, p.b, p.name) p.a, p.b, c.name, 'shared_owner', p.name,
               case when p.birth_year is not null and p.birth_month is not null then 'likely' else 'possible' end,
               case when p.birth_year is not null and p.birth_month is not null
                    then 'Same owner name and birth month/year (' || p.birth_month || '/' || p.birth_year || ')'
                    else 'Same owner name; no birth date to confirm' end
        from pairs p join company c on c.company_number = p.b
        on conflict do nothing""")
    rebuild_address_links(conn, scope_sql=scope if scored else None)


def _looks_like_group(individuals, ultimate) -> bool:
    # More than four separate individual owners through a holding company
    # usually means a wider group or shareholder base, not a founder.
    return len({u["person_id"] for u in individuals}) > 4 and any(u["via"] for u in ultimate)


def _is_recent(notified, ceased, today) -> bool:
    if ceased and today - ceased <= RECENT:
        return True
    if notified and notified != PSC_REGIME_START and today - notified <= RECENT:
        return True
    return False


def _match_by_name(name: str, companies: dict) -> str | None:
    key = n.company_name_key(name)
    if not key:
        return None
    for num, cname in companies.items():
        if n.company_name_key(cname) == key:
            return num
    return None


def _link(conn, a, b, b_name, kind, via, confidence, evidence):
    conn.execute(
        """insert into company_link (a, b, b_name, kind, via, confidence, evidence)
           values (%s, %s, %s, %s, %s, %s, %s)
           on conflict (a, b, kind, via) do update set confidence = excluded.confidence,
               evidence = excluded.evidence, b_name = excluded.b_name""",
        (a, b, b_name, kind, via, confidence, evidence),
    )


def _shared_owner_links(conn, ultimate_by_company):
    by_person = defaultdict(set)
    meta = {}
    for num, owners in ultimate_by_company.items():
        for u in owners:
            by_person[u["person_id"]].add(num)
            meta[u["person_id"]] = u
    names = {r["company_number"]: r["name"] for r in conn.execute("select company_number, name from company")}
    for pid, nums in by_person.items():
        if len(nums) < 2 or len(nums) > 25:
            continue
        u = meta[pid]
        has_dob = bool(u.get("birth_year") and u.get("birth_month"))
        confidence = "likely" if has_dob else "possible"
        evidence = (
            f"Same owner name and birth month/year ({u['birth_month']}/{u['birth_year']})"
            if has_dob else "Same owner name; no birth date to confirm"
        )
        ordered = sorted(nums)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                _link(conn, a, b, names.get(b), "shared_owner", u["name"], confidence, evidence)


def rebuild_address_links(conn, scope_sql: str | None = None):
    """Pairs of companies at the same (ordinary) registered address.
    Addresses shared by more than MASS_ADDRESS_THRESHOLD companies are
    accountants' or agents' offices and are skipped."""
    conn.execute("delete from company_link where kind = 'shared_address'")
    conn.execute("drop table if exists addr_members")
    in_scope = ("(" + scope_sql.replace("x.root", "c.company_number") + ")") if scope_sql else "true"
    conn.execute(f"""
        create temp table addr_members as
        select c.company_number, c.address_key, c.name, c.registered_address, {in_scope} as in_scope
        from company c
        join (select address_key from company
              where address_key is not null and address_flag is null
              group by address_key having count(*) between 2 and %s) g on g.address_key = c.address_key
        where c.address_flag is null""", (n.MASS_ADDRESS_THRESHOLD,))
    conn.execute("create index on addr_members (address_key)")
    conn.execute("analyze addr_members")
    conn.execute("""
        insert into company_link (a, b, b_name, kind, via, confidence, evidence)
        select x.company_number, y.company_number, y.name, 'shared_address', '', 'possible',
               'Same registered address: ' || x.registered_address
        from addr_members x join addr_members y
          on x.address_key = y.address_key and x.company_number < y.company_number
        where x.in_scope or y.in_scope
        on conflict do nothing""")


def _json(v):
    import json

    return json.dumps(v, default=str)
