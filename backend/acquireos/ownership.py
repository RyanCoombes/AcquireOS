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
    today = today or date.today()
    companies = {r["company_number"]: r["name"] for r in conn.execute("select company_number, name from company")}

    pscs = defaultdict(list)  # company -> list of psc dicts (active only)
    recent = defaultdict(bool)
    for r in conn.execute(
        """select cp.company_number, cp.natures, cp.notified_on, cp.ceased_on,
                  p.id, p.kind, p.name, p.birth_year, p.birth_month, p.registration_number, p.country_registered
           from company_person cp join person p on p.id = cp.person_id where cp.role = 'psc'"""
    ):
        if _is_recent(r["notified_on"], r["ceased_on"], today):
            recent[r["company_number"]] = True
        if r["ceased_on"] is None:
            pscs[r["company_number"]].append(dict(r))

    parents = defaultdict(list)
    for r in conn.execute(
        """select pp.parent_number, pp.natures, p.id, p.kind, p.name, p.birth_year, p.birth_month,
                  p.registration_number, p.country_registered
           from parent_psc pp join person p on p.id = pp.person_id where pp.ceased_on is null"""
    ):
        parents[r["parent_number"]].append(dict(r))

    def owners_of(number: str):
        return pscs.get(number) or parents.get(number) or []

    conn.execute("delete from company_ownership")
    conn.execute("delete from company_link where kind in ('owned_by', 'shared_owner')")

    ultimate_by_company: dict[str, list[dict]] = {}
    counts = defaultdict(int)
    for num, name in companies.items():
        direct = pscs.get(num, [])
        flags: set[str] = set()
        notes: list[str] = []
        ultimate: list[dict] = []
        unresolved_corporate = False

        def walk(owner: dict, depth: int, chain: list[str]):
            nonlocal unresolved_corporate
            label = owner["name"]
            if owner["kind"] == "individual":
                ultimate.append(
                    {"name": label, "birth_year": owner["birth_year"], "birth_month": owner["birth_month"],
                     "person_id": owner["id"], "via": chain[:]}
                )
                return
            if EOT_RE.search(label):
                flags.add("eot")
            elif owner["kind"] == "legal" or TRUST_RE.search(label):
                flags.add("trust")
            if INVESTOR_RE.search(label):
                flags.add("investor")
            country = (owner.get("country_registered") or "").strip().lower()
            if owner["kind"] == "corporate" and country and country not in UK_PLACES and not any(
                w in country for w in ("england", "wales", "scotland", "united kingdom")
            ):
                flags.add("foreign_parent")
            reg = owner.get("registration_number")
            above = owners_of(reg) if reg and reg not in chain and depth < 5 else []
            if not above:
                if owner["kind"] == "corporate":
                    unresolved_corporate = True
                ultimate.append({"name": label, "kind": owner["kind"], "via": chain[:], "unresolved": True})
                return
            for parent_owner in above:
                walk(parent_owner, depth + 1, chain + [reg])

        for owner in direct:
            for nat in owner.get("natures") or []:
                if "as-trust" in nat:
                    flags.add("trust")
            if owner["kind"] != "individual":
                if owner.get("registration_number"):
                    flags.add("via_holdco")
                    _link(conn, num, owner["registration_number"], owner["name"], "owned_by", "",
                          "confirmed", "Registration number on the PSC record")
                else:
                    match = _match_by_name(owner["name"], companies)
                    if match:
                        _link(conn, num, match, owner["name"], "owned_by", "", "likely",
                              "Parent name matches a company in your list; no registration number filed")
            walk(owner, 0, [])

        individuals = [u for u in ultimate if not u.get("unresolved")]
        if recent[num]:
            flags.add("recent_change")
        if not direct:
            flags.add("no_psc_data")

        if "eot" in flags:
            otype = "eot"
        elif "investor" in flags:
            otype = "investor_backed"
        elif "foreign_parent" in flags:
            otype = "foreign_owned"
        elif "trust" in flags and not individuals:
            otype = "trust"
        elif unresolved_corporate and not individuals:
            otype = "group_owned"
        elif individuals and _looks_like_group(individuals, ultimate):
            otype = "group_owned"
        elif individuals:
            otype = "owner_held"
        else:
            otype = "unknown"

        if otype == "owner_held":
            via = " through a holding company" if "via_holdco" in flags else " directly"
            notes.append(f"{len({u['person_id'] for u in individuals})} individual owner(s), held{via}.")
        elif otype == "unknown":
            notes.append("No active owner records found in the PSC data imported so far.")
        else:
            notes.append(f"Classed as {TYPE_LABELS[otype].lower()} from the owner records.")

        years = [u["birth_year"] for u in individuals if u.get("birth_year")]
        conn.execute(
            """insert into company_ownership (company_number, ownership_type, flags, owner_count,
                   oldest_birth_year, ultimate_owners, explanation)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (num, otype, sorted(flags), len({u["person_id"] for u in individuals}),
             min(years) if years else None, _json(ultimate), " ".join(notes)),
        )
        ultimate_by_company[num] = individuals
        counts[otype] += 1

    _shared_owner_links(conn, ultimate_by_company)
    rebuild_address_links(conn)
    return {"ownership": dict(counts)}


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


def rebuild_address_links(conn):
    conn.execute("delete from company_link where kind = 'shared_address'")
    conn.execute(
        """
        insert into company_link (a, b, b_name, kind, via, confidence, evidence)
        select x.company_number, y.company_number, y.name, 'shared_address', '', 'possible',
               'Same registered address: ' || x.registered_address
        from company x join company y
          on x.address_key = y.address_key and x.company_number < y.company_number
        where x.address_key is not null and x.address_flag is null and y.address_flag is null
          and x.address_key in (
              select address_key from company where address_key is not null
              group by address_key having count(*) between 2 and %s)
        on conflict do nothing
        """,
        (n.MASS_ADDRESS_THRESHOLD,),
    )


def _json(v):
    import json

    return json.dumps(v, default=str)
