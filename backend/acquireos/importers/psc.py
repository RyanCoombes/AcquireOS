"""Import owners from the free Companies House PSC snapshot.

Download: https://download.companieshouse.gov.uk/en_pscdata.html
The snapshot is JSON lines (one PSC per line), several GB unzipped. We
stream it and keep only companies in the database, then make further
passes to pick up parent companies so ownership can be traced through
holding companies.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .. import normalise as n

UK_PLACES = {
    "", "united kingdom", "uk", "england", "wales", "scotland", "northern ireland",
    "england and wales", "england & wales", "great britain", "companies house",
    "registrar of companies for england and wales", "register of companies for england and wales",
    "registrar of companies", "companies house, cardiff", "cardiff",
}

KIND_MAP = {
    "individual-person-with-significant-control": "individual",
    "individual-beneficial-owner": "individual",
    "corporate-entity-person-with-significant-control": "corporate",
    "corporate-entity-beneficial-owner": "corporate",
    "legal-person-person-with-significant-control": "legal",
    "legal-person-beneficial-owner": "legal",
}


def _open_lines(path: Path):
    if path.suffix.lower() == ".zip":
        z = zipfile.ZipFile(path)
        for name in z.namelist():
            with z.open(name) as f:
                yield from io.TextIOWrapper(f, encoding="utf-8")
    else:
        with open(path, encoding="utf-8") as f:
            yield from f


def _records(paths: list[Path]):
    for p in paths:
        for line in _open_lines(p):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            num = n.company_number(rec.get("company_number"))
            data = rec.get("data") or {}
            if num and data.get("kind") in KIND_MAP:
                yield num, data


def run(conn, paths: list[Path], max_depth: int = 4) -> dict:
    paths = [Path(p) for p in paths]
    run_id = conn.execute(
        "insert into import_run (kind, filename) values ('psc', %s) returning id",
        (", ".join(p.name for p in paths),),
    ).fetchone()["id"]

    wanted = {r["company_number"] for r in conn.execute("select company_number from company")}
    # On the first owner import everything is "new", so only later imports
    # record owner changes.
    first = conn.execute("select 1 from company_person limit 1").fetchone() is None
    known_companies = set(wanted)
    done: set[str] = set()
    total = 0
    depth = 0
    # Parent companies outside our list are stored as people of kind
    # "corporate"; we pull their own PSCs in later passes but do not add
    # them to the company table.
    parent_rows: dict[str, list[tuple[str, dict]]] = {}
    while wanted and depth <= max_depth:
        next_wanted: set[str] = set()
        for num, data in _records(paths):
            if num not in wanted:
                continue
            if num in known_companies:
                _store(conn, num, data, run_id, first)
                total += 1
            else:
                parent_rows.setdefault(num, []).append(("psc", data))
            if KIND_MAP[data["kind"]] == "corporate":
                reg = _reg_number(data)
                if reg and reg not in done and reg not in wanted:
                    next_wanted.add(reg)
        done |= wanted
        wanted = next_wanted
        depth += 1

    conn.execute(
        "update import_run set rows_in=%s, rows_ok=%s, finished_at=now(), messages=%s where id=%s",
        (total, total, json.dumps([f"Parent companies traced outside your list: {len(parent_rows)}"]), run_id),
    )
    _store_parents(conn, parent_rows)
    from ..ownership import rebuild

    stats = rebuild(conn)
    return {"run_id": run_id, "rows_ok": total, "parents_traced": len(parent_rows), **stats}


def _reg_number(data: dict) -> str | None:
    ident = data.get("identification") or {}
    reg = n.company_number(ident.get("registration_number"))
    if not reg:
        return None
    place = (ident.get("country_registered") or ident.get("place_registered") or "").strip().lower()
    # Only UK registration numbers can be looked up in the UK snapshot.
    return reg if place in UK_PLACES or "england" in place or "wales" in place or "companies house" in place else None


def person_from(data: dict) -> dict:
    kind = KIND_MAP[data["kind"]]
    name = (data.get("name") or "Unnamed").strip()
    ident = data.get("identification") or {}
    dob = data.get("date_of_birth") or {}
    reg = n.company_number(ident.get("registration_number")) if kind != "individual" else None
    country = (ident.get("country_registered") or ident.get("place_registered") or "").strip() or None
    if kind == "individual":
        key = f"i:{n.name_key(name)}:{dob.get('year') or ''}:{dob.get('month') or ''}"
    elif reg:
        key = f"c:{reg}:{(country or '').lower()}"
    else:
        key = f"{kind[0]}:{n.company_name_key(name)}"
    return {
        "person_key": key,
        "kind": kind,
        "name": name,
        "birth_year": dob.get("year"),
        "birth_month": dob.get("month"),
        "registration_number": reg,
        "country_registered": country,
        "legal_form": ident.get("legal_form"),
    }


def _upsert_person(conn, p: dict) -> int:
    return conn.execute(
        """insert into person (person_key, kind, name, birth_year, birth_month, registration_number,
               country_registered, legal_form)
           values (%(person_key)s, %(kind)s, %(name)s, %(birth_year)s, %(birth_month)s,
               %(registration_number)s, %(country_registered)s, %(legal_form)s)
           on conflict (person_key) do update set name = excluded.name
           returning id""",
        p,
    ).fetchone()["id"]


def _store(conn, num: str, data: dict, run_id=None, first=True):
    p = person_from(data)
    pid = _upsert_person(conn, p)
    notified = n.parse_date(data.get("notified_on"))
    ceased = n.parse_date(data.get("ceased_on"))
    row_key = f"psc:{num}:{p['person_key']}:{notified or ''}"
    if not first:
        old = conn.execute("select ceased_on from company_person where row_key = %s", (row_key,)).fetchone()
        change = None
        if old is None and not ceased:
            change = ("New owner", p["name"])
        elif old is not None and old["ceased_on"] is None and ceased:
            change = ("Owner ceased", p["name"])
        if change:
            conn.execute(
                """insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
                   values (%s, %s, 'owner', %s, null, %s)""",
                (num, run_id, change[0], change[1]),
            )
    conn.execute(
        """insert into company_person (row_key, company_number, person_id, role, natures,
               notified_on, ceased_on, source)
           values (%s, %s, %s, 'psc', %s, %s, %s, 'psc_snapshot')
           on conflict (row_key) do update set natures = excluded.natures,
               ceased_on = excluded.ceased_on""",
        (row_key, num, pid, data.get("natures_of_control") or [], notified, ceased),
    )


def _store_parents(conn, parent_rows: dict):
    """Keep owners of parent companies as JSON on the parent's person row,
    so ownership can be traced without adding parents to the company list."""
    for num, items in parent_rows.items():
        for _, data in items:
            p = person_from(data)
            pid = _upsert_person(conn, p)
            conn.execute(
                """insert into parent_psc (parent_number, person_id, natures, ceased_on)
                   values (%s, %s, %s, %s) on conflict do nothing""",
                (num, pid, data.get("natures_of_control") or [], n.parse_date(data.get("ceased_on"))),
            )
