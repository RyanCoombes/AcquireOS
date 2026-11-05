"""Import owners from the free Companies House PSC snapshot.

Download: https://download.companieshouse.gov.uk/en_pscdata.html
The snapshot is JSON lines (one PSC per line), several GB unzipped. We
stream it and keep only companies in the database, then make further
passes to pick up parent companies so ownership can be traced through
holding companies.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from .. import normalise as n

UK_PLACES = {
    "", "united kingdom", "uk", "england", "wales", "scotland", "northern ireland",
    "england and wales", "england & wales", "great britain", "companies house",
    "registrar of companies for england and wales", "register of companies for england and wales",
    "registrar of companies", "companies house, cardiff", "cardiff",
}

# Fewer records than this and a file is not treated as the full snapshot.
FULL_SNAPSHOT_MIN = 1_000_000

KIND_MAP = {
    "individual-person-with-significant-control": "individual",
    "individual-beneficial-owner": "individual",
    "corporate-entity-person-with-significant-control": "corporate",
    "corporate-entity-beneficial-owner": "corporate",
    "legal-person-person-with-significant-control": "legal",
    "legal-person-beneficial-owner": "legal",
}


def _open_lines(path: Path):
    """Raw JSON lines (bytes) from a zip or a plain file."""
    if path.suffix.lower() == ".zip":
        z = zipfile.ZipFile(path)
        for name in z.namelist():
            with z.open(name) as f:
                yield from f
    else:
        with open(path, "rb") as f:
            yield from f


def _chunks(paths: list[Path], size: int = 4000):
    buf: list[bytes] = []
    for p in paths:
        for line in _open_lines(p):
            buf.append(line)
            if len(buf) >= size:
                yield buf
                buf = []
    if buf:
        yield buf


def _row(line: bytes):
    """One staged row from one JSON line, or None (not a PSC record)."""
    line = line.strip()
    if not line:
        return None
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    num = n.company_number(rec.get("company_number"))
    data = rec.get("data") or {}
    if not num or data.get("kind") not in KIND_MAP:
        return None
    p = person_from(data)
    notified = n.parse_date(data.get("notified_on"))
    return (num, p["person_key"], p["kind"], p["name"], p["birth_year"], p["birth_month"],
            p["registration_number"], p["country_registered"], p["legal_form"], p["address"],
            p["postcode"], data.get("natures_of_control") or [], notified,
            n.parse_date(data.get("ceased_on")), f"psc:{num}:{p['person_key']}:{notified or ''}")


def _parse_chunk(lines: list[bytes]) -> list[tuple]:
    """Worker: parse a block of lines (the CPU-heavy part, run in parallel)."""
    out = []
    for line in lines:
        r = _row(line)
        if r is not None:
            out.append(r)
    return out


def _records(paths: list[Path]):
    for chunk in _chunks(paths):
        for r in _parse_chunk(chunk):
            yield r


def run(conn, paths: list[Path], max_depth: int = 4, record_changes: bool = True, progress=None,
        links: bool = True, workers: int | None = None) -> dict:
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
    import os
    from multiprocessing import get_context

    workers = workers if workers is not None else max(1, min(4, (os.cpu_count() or 2) - 1))
    with conn.cursor().copy(
        """copy psc_stage (company_number, person_key, kind, name, birth_year, birth_month, registration_number,
               country_registered, legal_form, address, postcode, natures, notified_on, ceased_on, row_key)
           from stdin""") as cp:
        def take(rows):
            nonlocal total
            for row in rows:
                cp.write_row(row)
            total += len(rows)
            if progress and total // 100_000 != (total - len(rows)) // 100_000:
                progress(f"Reading owners: {total:,} records", min(total / est, 1) * 0.6)

        if workers > 1:
            # Parsing JSON and tidying names is the slow part: spread it over
            # the cores ("spawn" so workers start clean inside the web server).
            # Ordered, so later lines still win when a record appears twice.
            with get_context("spawn").Pool(workers) as pool:
                for rows in pool.imap(_parse_chunk, _chunks(paths), chunksize=1):
                    take(rows)
        else:
            for chunk in _chunks(paths):
                take(_parse_chunk(chunk))
    if progress:
        progress(f"Saving {total:,} owner records", 0.65)
    # Keep the last occurrence of each record: one sort, not a self-join of
    # every staged row against every other.
    conn.execute("""create temp table psc_latest as
                    select distinct on (row_key) * from psc_stage order by row_key, seq desc""")
    conn.execute("drop table psc_stage")
    conn.execute("alter table psc_latest rename to psc_stage")
    conn.execute("create index on psc_stage (row_key)")
    conn.execute("analyze psc_stage")

    conn.execute("""
        insert into person (person_key, kind, name, birth_year, birth_month, registration_number,
                            country_registered, legal_form, address, postcode)
        select distinct on (person_key) person_key, kind, name, birth_year, birth_month, registration_number,
               country_registered, legal_form, address, postcode
        from psc_stage order by person_key, seq desc
        on conflict (person_key) do update set name = excluded.name,
            registration_number = excluded.registration_number,
            country_registered = excluded.country_registered,
            address = coalesce(excluded.address, person.address),
            postcode = coalesce(excluded.postcode, person.postcode)
        -- only rows that differ are rewritten (most owners are unchanged month to month)
        where (person.name, person.registration_number, person.country_registered)
              is distinct from (excluded.name, excluded.registration_number, excluded.country_registered)
           or (excluded.address is not null and person.address is distinct from excluded.address)""")

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
        on conflict (row_key) do update set natures = excluded.natures, ceased_on = excluded.ceased_on
        where (company_person.natures, company_person.ceased_on) is distinct from (excluded.natures, excluded.ceased_on)
        """).rowcount
    in_list = conn.execute("select count(*) as n from psc_stage s join company c using (company_number)").fetchone()["n"]
    retired = 0
    if total >= FULL_SNAPSHOT_MIN:
        # A full snapshot is the whole truth: owner records no longer in it
        # (removed or corrected at Companies House) are dropped, so they do
        # not linger as duplicate or out-of-date owners.
        conn.execute("create index if not exists psc_stage_key on psc_stage (row_key)")
        retired = conn.execute("""
            delete from company_person cp where cp.source = 'psc_snapshot'
              and not exists (select 1 from psc_stage s where s.row_key = cp.row_key)""").rowcount
    parents = conn.execute("""
        insert into parent_psc (parent_number, person_id, natures, ceased_on)
        select distinct on (s.company_number, p.id) s.company_number, p.id, s.natures, s.ceased_on
        from psc_stage s join person p on p.person_key = s.person_key
        where not exists (select 1 from company c where c.company_number = s.company_number)
        order by s.company_number, p.id, s.seq desc
        on conflict (parent_number, person_id) do update set natures = excluded.natures,
            ceased_on = excluded.ceased_on
        where (parent_psc.natures, parent_psc.ceased_on) is distinct from (excluded.natures, excluded.ceased_on)""").rowcount

    conn.execute(
        "update import_run set rows_in=%s, rows_ok=%s, finished_at=now(), messages=%s where id=%s",
        (total, in_list, json.dumps([f"Owner records for companies outside your database: {parents:,}"]
                                    + ([f"Owner records no longer at Companies House, removed: {retired:,}"] if retired else [])), run_id),
    )
    conn.execute("drop table if exists psc_stage")
    from ..ownership import rebuild

    # links=False when a later step rebuilds the links anyway (the monthly
    # refresh does, after scoring), so the slowest part is not done twice.
    stats = rebuild(conn, progress=progress, links=links)
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


# A place of registration in the UK (Companies House numbers can be traced).
# Word-bounded so "Ireland" alone (the Republic) does not count.
UK_PLACE_RE = re.compile(
    r"\b(uk|u\.k\.?|gb|great britain|britain|united kingdom|england|wales|scotland|northern ireland|n\.?\s?ireland"
    r"|companies house|registrar of companies|register of companies|cardiff|edinburgh|belfast|london)\b", re.I)
# Same test for SQL (Postgres word boundaries are \y).
UK_PLACE_SQL = (r"\y(uk|u\.k\.?|gb|great britain|britain|united kingdom|england|wales|scotland|northern ireland|n\.?\s?ireland"
                r"|companies house|registrar of companies|register of companies|cardiff|edinburgh|belfast|london)\y")
_UK_NUM_RE = re.compile(r"\b(SC|NI|OC|SO|NC|R|FC|SE|GE|LP|SL|NL|IP|SP|RS|CE|CS)?\s*-?\s*(\d{5,8})\b")


def is_uk_place(place: str | None) -> bool:
    return bool(place and UK_PLACE_RE.search(place))


def uk_registration(ident: dict) -> str | None:
    """The Companies House number of a corporate owner, or None when it is
    registered abroad or the number cannot be read. Free text such as
    "Company No. 08123456" or "SC-123456 (Scotland)" is handled; a foreign
    number is never padded into a UK one (it would match an unrelated company)."""
    raw = (ident.get("registration_number") or "").strip().upper()
    if not raw:
        return None
    place = " ".join(filter(None, (ident.get("country_registered"), ident.get("place_registered"),
                                   ident.get("legal_authority"))))
    m = _UK_NUM_RE.search(raw)
    if not m:
        return None
    prefix, digits = m.group(1) or "", m.group(2)
    uk = is_uk_place(place) or "companies act" in place.lower()
    if not uk:
        # No place given: only accept a number that is already in full UK form.
        if place.strip() or len(prefix) + len(digits) != 8:
            return None
    if len(prefix) + len(digits) > 8:
        return None
    return prefix + digits.zfill(8 - len(prefix))


def _reg_number(data: dict) -> str | None:
    return uk_registration(data.get("identification") or {})


def person_from(data: dict) -> dict:
    kind = KIND_MAP[data["kind"]]
    name = (data.get("name") or "Unnamed").strip()
    ident = data.get("identification") or {}
    dob = data.get("date_of_birth") or {}
    reg = uk_registration(ident) if kind != "individual" else None
    raw_reg = (ident.get("registration_number") or "").strip() or None
    country = (ident.get("country_registered") or ident.get("place_registered") or "").strip() or None
    if kind == "individual":
        key = f"i:{n.name_key(name)}:{dob.get('year') or ''}:{dob.get('month') or ''}"
    elif reg:
        key = f"c:{reg}:{(country or '').lower()}"
    elif raw_reg:
        key = f"c:{raw_reg.upper()}:{(country or '').lower()}"  # foreign: keep its own number
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


