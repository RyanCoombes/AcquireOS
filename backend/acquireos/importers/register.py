"""Bulk loader for the Companies House register (BasicCompanyData file).

About 5.5 million live companies. The file is streamed into a staging table
with COPY, then compared and merged with set-based SQL, so memory use stays
flat and a Raspberry Pi 5 can load it in minutes rather than hours.

Rules:
- A company row is only updated from a snapshot at least as new as the one
  it came from (company.register_date), so loading an older file can never
  roll back a newer status, name or address.
- Changes are recorded against what was stored before. On the very first
  register load only companies you already had are compared, so millions of
  "new company" entries are not created.
- With full=True, companies seen in an earlier snapshot but missing from this
  one are marked "removed from register" (usually dissolved), never deleted.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from .. import normalise as n
from .tables import norm_header, open_table

COLS = {
    "num": ["companynumber"],
    "name": ["companyname"],
    "careof": ["regaddress_careof"],
    "pobox": ["regaddress_pobox"],
    "line1": ["regaddress_addressline1"],
    "line2": ["regaddress_addressline2"],
    "town": ["regaddress_posttown"],
    "county": ["regaddress_county"],
    "pc": ["regaddress_postcode"],
    "category": ["companycategory"],
    "status": ["companystatus"],
    "dissolved": ["dissolutiondate"],
    "inc": ["incorporationdate"],
    "last_acc": ["accounts_lastmadeupdate"],
    "sic1": ["siccode_sictext_1"],
    "sic2": ["siccode_sictext_2"],
    "sic3": ["siccode_sictext_3"],
    "sic4": ["siccode_sictext_4"],
}
# Fewer rows than this and a file is not treated as the full register.
FULL_REGISTER_MIN_ROWS = 500_000


def _estimate_rows(path: Path) -> int:
    """Rough row count for progress: about 470 bytes per company in the CSV."""
    import zipfile

    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                size = sum(i.file_size for i in z.infolist())
        else:
            size = path.stat().st_size
        return max(int(size / 470), 1)
    except Exception:
        return 5_500_000


def is_register(headers: list[str]) -> bool:
    normed = {norm_header(h) for h in headers}
    return {"companynumber", "companystatus", "regaddress_postcode"} <= normed


def snapshot_date(path: Path) -> date:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", path.name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return date.today()


def _d(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    try:
        return datetime.strptime(v, "%d/%m/%Y").date().isoformat()
    except ValueError:
        d = n.parse_date(v)
        return d.isoformat() if d else None


def load(conn, path: Path, register_date: date | None = None, full: bool = True,
         record_changes: bool = True, progress=None) -> dict:
    from .companies import flag_mass_addresses, refresh_estimates

    headers, rows = open_table(path)
    est_rows = _estimate_rows(path)
    if not is_register(headers):
        raise ValueError("This is not a Companies House BasicCompanyData file")
    idx = {norm_header(h): h for h in headers}
    col = {k: next((idx[a] for a in aliases if a in idx), None) for k, aliases in COLS.items()}
    snap = register_date or snapshot_date(path)
    run_id = conn.execute(
        "insert into import_run (kind, filename) values ('register', %s) returning id", (path.name,)
    ).fetchone()["id"]

    conn.execute("drop table if exists reg_stage; drop table if exists reg_new")
    conn.execute("""create temp table reg_stage (
        num text, name text, addr text, pc text, category text, status text, dissolved date, inc date,
        last_acc date, sic text[], sic_text text[]) on commit drop""")
    rows_in = 0
    with conn.cursor().copy(
        "copy reg_stage (num, name, addr, pc, category, status, dissolved, inc, last_acc, sic, sic_text) from stdin"
    ) as cp:
        for row in rows:
            g = lambda k: (row.get(col[k]) or "").strip() if col[k] else ""  # noqa: E731
            num = n.company_number(g("num"))
            if not num:
                continue
            rows_in += 1
            parts = [g(k) for k in ("careof", "pobox", "line1", "line2", "town", "county", "pc")]
            sic_raw = [g(k) for k in ("sic1", "sic2", "sic3", "sic4") if g(k)]
            codes = []
            for t in sic_raw:
                m = re.match(r"\s*(\d{4,5})", t)
                if m and m.group(1).zfill(5) not in codes:
                    codes.append(m.group(1).zfill(5))
            pc = n.postcode(g("pc")) or (g("pc").upper() or None)
            cp.write_row((num, g("name") or num, ", ".join(p for p in parts if p) or None, pc,
                          g("category") or None, (g("status") or "").lower() or None, _d(g("dissolved")),
                          _d(g("inc")), _d(g("last_acc")), codes, sic_raw))
            if progress and rows_in % 50_000 == 0:
                progress(f"Reading the register: {rows_in:,} companies", min(rows_in / est_rows, 1) * 0.6)
    if progress:
        progress(f"Comparing {rows_in:,} companies with what is stored", 0.65)
    conn.execute("create index on reg_stage (num)")
    conn.execute("analyze reg_stage")
    # A number can appear twice in a damaged file; keep one.
    conn.execute("""delete from reg_stage a using reg_stage b
                    where a.num = b.num and a.ctid < b.ctid""")

    from .. import sic as sic_mod

    sic_mod.seed(conn)
    conn.execute(r"""
        insert into sic_code (code, description, source)
        select distinct on (code) lpad(substring(t from '^\s*(\d{4,5})'), 5, '0') as code,
               trim(substring(t from '^\s*\d{4,5}\s*-\s*(.+)$')), 'companies house'
        from reg_stage, unnest(sic_text) t
        where t ~ '^\s*\d{4,5}\s*-\s*\S'
        on conflict (code) do update set description = excluded.description, source = excluded.source""")

    first_register = conn.execute("select 1 from company where register_date is not null limit 1").fetchone() is None
    conn.execute("""create temp table reg_new on commit drop as
                    select s.num from reg_stage s
                    where not exists (select 1 from company c where c.company_number = s.num)""")
    changes = 0
    if record_changes:
        changes += _record_changes(conn, run_id, snap)

    if progress:
        progress("Saving companies", 0.8)
    conn.execute(r"""
        insert into company as c (company_number, name, status, company_type, incorporation_date, dissolution_date,
            sic_codes, nature_of_business, registered_address, postcode, address_key, address_flag, region,
            source, register_date, last_accounts_date)
        select s.num, s.name, s.status, s.category, s.inc, s.dissolved, s.sic,
               array_to_string(s.sic_text, ', '), s.addr, s.pc, ao_address_key(s.addr),
               case when s.pc = 'CF14 8LH' then 'ch_default'
                    when s.pc in ('N1 7GU', 'WC2H 9JQ', 'EC1V 2NX') then 'formation_agent' end,
               ao_region(s.pc), %(src)s, %(snap)s, s.last_acc
        from reg_stage s
        on conflict (company_number) do update set
            name = excluded.name,
            status = excluded.status,
            status_changed_at = case when c.status is distinct from excluded.status and c.status is not null
                                     then now() else c.status_changed_at end,
            company_type = excluded.company_type,
            incorporation_date = coalesce(excluded.incorporation_date, c.incorporation_date),
            dissolution_date = excluded.dissolution_date,
            sic_codes = case when cardinality(excluded.sic_codes) > 0 then excluded.sic_codes else c.sic_codes end,
            nature_of_business = coalesce(nullif(excluded.nature_of_business, ''), c.nature_of_business),
            registered_address = coalesce(excluded.registered_address, c.registered_address),
            postcode = coalesce(excluded.postcode, c.postcode),
            address_key = coalesce(excluded.address_key, c.address_key),
            address_flag = case when c.address_flag = 'mass_address' then c.address_flag
                                else excluded.address_flag end,
            region = coalesce(excluded.region, c.region),
            source = excluded.source,
            register_date = excluded.register_date,
            last_accounts_date = greatest(c.last_accounts_date, excluded.last_accounts_date),
            updated_at = now()
        where c.register_date is null or excluded.register_date >= c.register_date
        """, {"src": f"Companies House register {snap.isoformat()}", "snap": snap})

    if record_changes and not first_register:
        changes += conn.execute(
            """insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
               select num, %s, 'new_company', null, null, 'Added to your list' from reg_new""", (run_id,)).rowcount

    messages = []
    if full:
        if rows_in < FULL_REGISTER_MIN_ROWS:
            messages.append("Not treated as the full register (too few rows), so missing companies were not flagged.")
        else:
            gone = conn.execute(
                """with gone as (
                       select c.company_number, c.status from company c
                       where c.register_date is not null and c.register_date < %s
                         and coalesce(c.status, '') not in ('removed from register', 'dissolved')
                         and not exists (select 1 from reg_stage s where s.num = c.company_number))
                   , logged as (
                       insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
                       select company_number, %s, 'status', 'status', status, 'removed from register' from gone
                       returning 1)
                   update company c set status = 'removed from register', status_changed_at = now()
                   from gone where gone.company_number = c.company_number
                   returning c.company_number""", (snap, run_id)).fetchall()
            if gone:
                changes += len(gone)
                messages.append(f"{len(gone):,} companies are no longer on the live register (usually dissolved).")

    flag_mass_addresses(conn)
    refresh_estimates(conn)
    conn.execute("update import_run set rows_in=%s, rows_ok=%s, messages=%s, finished_at=now() where id=%s",
                 (rows_in, rows_in, json.dumps(messages), run_id))
    return {"run_id": run_id, "rows_in": rows_in, "rows_ok": rows_in, "rows_skipped": 0, "changes": changes,
            "snapshot": snap.isoformat(), "messages": messages}


def _record_changes(conn, run_id, snap) -> int:
    """Differences between the snapshot and what is stored, as change rows."""
    only_newer = "(c.register_date is null or %(snap)s >= c.register_date)"
    params = {"run": run_id, "snap": snap}
    total = 0
    for kind, field, old, new, cond in [
        ("status", "status", "c.status", "s.status", "c.status is distinct from s.status and s.status is not null"),
        ("name", "name", "c.name", "s.name", "upper(c.name) <> upper(s.name)"),
        ("address", "registered_address", "c.registered_address", "s.addr",
         "c.address_key is not null and ao_address_key(s.addr) is distinct from c.address_key"),
        ("sic", "sic_codes", "array_to_string(c.sic_codes, ', ')", "array_to_string(s.sic, ', ')",
         "cardinality(s.sic) > 0 and cardinality(c.sic_codes) > 0 "
         "and (select array_agg(x order by x) from unnest(c.sic_codes) x) <> (select array_agg(x order by x) from unnest(s.sic) x)"),
        ("accounts", "period_end", "greatest(c.last_accounts_date, cl.period_end)::text", "s.last_acc::text",
         "s.last_acc is not null and greatest(c.last_accounts_date, cl.period_end) is not null "
         "and s.last_acc > greatest(c.last_accounts_date, cl.period_end)"),
    ]:
        total += conn.execute(
            f"""insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
                select c.company_number, %(run)s, '{kind}', '{field}', {old}, {new}
                from reg_stage s join company c on c.company_number = s.num
                left join company_latest cl on cl.company_number = c.company_number
                where {only_newer} and {cond}""", params).rowcount
    return total
