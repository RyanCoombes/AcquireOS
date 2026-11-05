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


def run(conn, paths: list[Path], max_depth: int = 4, record_changes: bool = True, progress=None) -> dict:
    """Load every PSC record in the snapshot (all UK companies).

    One streaming pass into a staging table, then set-based merges, so tens of
    millions of records load without holding them in memory. Records for
    companies in the company table go to company_person; the rest (parents
    that are dissolved, foreign or otherwise not on the live register) go to
    parent_psc so ownership chains can still be followed.
    """
    paths = [Path(p) for p in paths]
    run_id = conn.execute(
        "insert into import_run (kind, filename) values ('psc', %s) returning id",
        (", ".join(p.name for p in paths),),
    ).fetchone()["id"]
    first = conn.execute("select 1 from company_person limit 1").fetchone() is None

    conn.execute("drop table if exists psc_stage")
    conn.execute("""create temp table psc_stage (
        company_number text, person_key text, kind text, name text, birth_year int, birth_month int,
        registration_number text, country_registered text, legal_form text, address text, postcode text,
        natures text[], notified_on date, ceased_on date, row_key text, seq bigserial)""")
    total = 0
    est = _estimate_lines(paths)
    with conn.cursor().copy(
        """copy psc_stage (company_number, person_key, kind, name, birth_year, birth_month, registration_number,
               country_registered, legal_form, address, postcode, natures, notified_on, ceased_on, row_key)
           from stdin""") as cp:
        for num, data in _records(paths):
            p = person_from(data)
            notified = n.parse_date(data.get("notified_on"))
            cp.write_row((num, p["person_key"], p["kind"], p["name"], p["birth_year"], p["birth_month"],
                          p["registration_number"], p["country_registered"], p["legal_form"], p["address"],
                          p["postcode"], data.get("natures_of_control") or [], notified,
                          n.parse_date(data.get("ceased_on")), f"psc:{num}:{p['person_key']}:{notified or ''}"))
            total += 1
            if progress and total % 100_000 == 0:
                progress(f"Reading owners: {total:,} records", min(total / est, 1) * 0.6)
    if progress:
        progress(f"Saving {total:,} owner records", 0.65)
    conn.execute("create index on psc_stage (row_key, seq)")
    conn.execute("analyze psc_stage")
    conn.execute("""delete from psc_stage a using psc_stage b where a.row_key = b.row_key and a.seq < b.seq""")

    conn.execute("""
        insert into person (person_key, kind, name, birth_year, birth_month, registration_number,
                            country_registered, legal_form, address, postcode)
        select distinct on (person_key) person_key, kind, name, birth_year, birth_month, registration_number,
               country_registered, legal_form, address, postcode
        from psc_stage order by person_key, seq desc
        on conflict (person_key) do update set name = excluded.name,
            address = coalesce(excluded.address, person.address),
            postcode = coalesce(excluded.postcode, person.postcode)""")

    changes = 0
    if record_changes and not first:
        changes += conn.execute("""
            insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
            select s.company_number, %s, 'owner', 'New owner', null, s.name
            from psc_stage s join company c on c.company_number = s.company_number
            where s.ceased_on is null and not exists (select 1 from company_person cp where cp.row_key = s.row_key)""",
            (run_id,)).rowcount
        changes += conn.execute("""
            insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
            select s.company_number, %s, 'owner', 'Owner ceased', null, s.name
            from psc_stage s join company_person cp on cp.row_key = s.row_key
            where cp.ceased_on is null and s.ceased_on is not null""", (run_id,)).rowcount

    in_list = conn.execute("""
        insert into company_person (row_key, company_number, person_id, role, natures, notified_on, ceased_on, source)
        select s.row_key, s.company_number, p.id, 'psc', s.natures, s.notified_on, s.ceased_on, 'psc_snapshot'
        from psc_stage s join person p on p.person_key = s.person_key
        join company c on c.company_number = s.company_number
        on conflict (row_key) do update set natures = excluded.natures, ceased_on = excluded.ceased_on""").rowcount
    parents = conn.execute("""
        insert into parent_psc (parent_number, person_id, natures, ceased_on)
        select distinct on (s.company_number, p.id) s.company_number, p.id, s.natures, s.ceased_on
        from psc_stage s join person p on p.person_key = s.person_key
        where not exists (select 1 from company c where c.company_number = s.company_number)
        order by s.company_number, p.id, s.seq desc
        on conflict (parent_number, person_id) do update set natures = excluded.natures,
            ceased_on = excluded.ceased_on""").rowcount

    conn.execute(
        "update import_run set rows_in=%s, rows_ok=%s, finished_at=now(), messages=%s where id=%s",
        (total, in_list, json.dumps([f"Owner records for companies outside your database: {parents:,}"]), run_id),
    )
    conn.execute("drop table if exists psc_stage")
    from ..ownership import rebuild

    stats = rebuild(conn, progress=progress)
    return {"run_id": run_id, "rows_ok": in_list, "parents_traced": parents, "changes": changes, **stats}


def _estimate_lines(paths) -> int:
    """Rough record count for progress: about 650 bytes per JSON line."""
    total = 0
    for p in paths:
        try:
            if p.suffix.lower() == ".zip":
                with zipfile.ZipFile(p) as z:
                    total += sum(i.file_size for i in z.infolist())
            else:
                total += p.stat().st_size
        except Exception:
            pass
    return max(int(total / 650), 1)


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
    addr = data.get("address") or {}
    parts = [addr.get(k) for k in ("premises", "address_line_1", "address_line_2", "locality", "region", "postal_code", "country")]
    pc = n.postcode(addr.get("postal_code") or "") if kind != "individual" else None
    return {
        "person_key": key,
        "kind": kind,
        "name": name,
        # Individuals' service addresses are not kept: not needed, and personal data.
        "address": ", ".join(p for p in parts if p) if kind != "individual" else None,
        "postcode": pc,
        "birth_year": dob.get("year"),
        "birth_month": dob.get("month"),
        "registration_number": reg,
        "country_registered": country,
        "legal_form": ident.get("legal_form"),
    }


def _upsert_person(conn, p: dict) -> int:
    return conn.execute(
        """insert into person (person_key, kind, name, birth_year, birth_month, registration_number,
               country_registered, legal_form, address, postcode)
           values (%(person_key)s, %(kind)s, %(name)s, %(birth_year)s, %(birth_month)s,
               %(registration_number)s, %(country_registered)s, %(legal_form)s, %(address)s, %(postcode)s)
           on conflict (person_key) do update set name = excluded.name,
               address = coalesce(excluded.address, person.address), postcode = coalesce(excluded.postcode, person.postcode)
           returning id""",
        p,
    ).fetchone()["id"]


