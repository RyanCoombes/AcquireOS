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
    "acc_cat": ["accounts_accountcategory"],
    "acc_due": ["accounts_nextduedate"],
    "cs_due": ["confstmtnextduedate"],
    "mort_total": ["mortgages_nummortcharges"],
    "mort_out": ["mortgages_nummortoutstanding"],
    "mort_part": ["mortgages_nummortpartsatisfied"],
    "mort_sat": ["mortgages_nummortsatisfied"],
    **{f"prev{i}_name": [f"previousname_{i}_companyname"] for i in range(1, 11)},
    **{f"prev{i}_date": [f"previousname_{i}_condate"] for i in range(1, 11)},
}
# Bumped when the loader starts keeping more fields: a snapshot read by an
# older version is read again rather than skipped.
LOADER_VERSION = 2
_STAGE_COLS = ("num, name, addr, pc, category, status, dissolved, inc, last_acc, sic, sic_text, "
               "acc_cat, acc_due, cs_due, mort_total, mort_out, mort_part, mort_sat, prev_names")
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


def _int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v.isdigit() else None


def _stage_python(conn, rows, col, est_rows, progress) -> int:
    """Row-by-row reader (slower; used if the fast path cannot read a file)."""
    conn.execute("""create temp table reg_stage (
        num text, name text, addr text, pc text, category text, status text, dissolved date, inc date,
        last_acc date, sic text[], sic_text text[], acc_cat text, acc_due date, cs_due date,
        mort_total int, mort_out int, mort_part int, mort_sat int, prev_names jsonb) on commit drop""")
    rows_in = 0
    seen: set[str] = set()
    with conn.cursor().copy(
        f"copy reg_stage ({_STAGE_COLS}) from stdin"
    ) as cp:
        for row in rows:
            g = lambda k: (row.get(col[k]) or "").strip() if col[k] else ""  # noqa: E731
            num = n.company_number(g("num"))
            if not num or num in seen:
                continue
            seen.add(num)
            rows_in += 1
            parts = [g(k) for k in ("careof", "pobox", "line1", "line2", "town", "county", "pc")]
            sic_raw = [g(k) for k in ("sic1", "sic2", "sic3", "sic4") if g(k)]
            codes = []
            for t in sic_raw:
                m = re.match(r"\s*(\d{4,5})", t)
                if m and m.group(1).zfill(5) not in codes:
                    codes.append(m.group(1).zfill(5))
            pc = n.postcode(g("pc")) or (g("pc").upper() or None)
            prev = [{"name": g(f"prev{i}_name"), "until": _d(g(f"prev{i}_date"))}
                    for i in range(1, 11) if g(f"prev{i}_name")]
            cp.write_row((num, g("name") or num, ", ".join(p for p in parts if p) or None, pc,
                          g("category") or None, (g("status") or "").lower() or None, _d(g("dissolved")),
                          _d(g("inc")), _d(g("last_acc")), codes, sic_raw,
                          (g("acc_cat") or "").lower() or None, _d(g("acc_due")), _d(g("cs_due")),
                          _int(g("mort_total")), _int(g("mort_out")), _int(g("mort_part")), _int(g("mort_sat")),
                          json.dumps(prev) if prev else None))
            if progress and rows_in % 50_000 == 0:
                progress(f"Reading the register: {rows_in:,} companies", min(rows_in / est_rows, 1) * 0.6)
    return rows_in


def _raw_stream(path: Path):
    """(binary stream, uncompressed size) of the CSV inside a zip, or the file."""
    import zipfile

    if path.suffix.lower() == ".zip":
        z = zipfile.ZipFile(path)
        info = next(i for i in z.infolist() if i.filename.lower().endswith((".csv", ".txt")))
        return z.open(info), info.file_size
    return open(path, "rb"), path.stat().st_size


def _stage_fast(conn, path: Path, headers: list[str], progress) -> int:
    """Stream the CSV bytes straight into Postgres (no Python per row), then
    clean and normalise with one SQL statement."""
    ncol = len(headers)
    cols = [f"c{i}" for i in range(ncol)]
    conn.execute(f"create temp table reg_raw ({', '.join(c + ' text' for c in cols)}, seq bigserial) on commit drop")
    stream, size = _raw_stream(path)
    sent = 0
    with stream, conn.cursor().copy(
            f"copy reg_raw ({', '.join(cols)}) from stdin with (format csv, header true, encoding 'UTF8')") as cp:
        while chunk := stream.read(8 << 20):
            if sent == 0 and chunk.startswith(b"\xef\xbb\xbf"):
                chunk = chunk[3:]
            cp.write(chunk)
            sent += len(chunk)
            if progress:
                progress(f"Reading the register: {sent / 1e9:.2f} of {size / 1e9:.2f} GB", min(sent / max(size, 1), 1) * 0.45)
    pos = {norm_header(h): f"c{i}" for i, h in enumerate(headers)}

    def c(key):
        name = next((pos[a] for a in COLS[key] if a in pos), None)
        return f"nullif(trim({name}), '')" if name else "null::text"

    def dt(key):
        return f"case when {c(key)} ~ '^\\d{{2}}/\\d{{2}}/\\d{{4}}$' then to_date({c(key)}, 'DD/MM/YYYY') end"

    def num(key):
        return f"case when {c(key)} ~ '^\\d{{1,6}}$' then {c(key)}::int end"

    prev_rows = ", ".join(f"({c(f'prev{i}_name')}, {dt(f'prev{i}_date')}, {i})" for i in range(1, 11))
    sic_parts = ", ".join(c(k) for k in ("sic1", "sic2", "sic3", "sic4"))
    addr_parts = ", ".join(c(k) for k in ("careof", "pobox", "line1", "line2", "town", "county", "pc"))
    if progress:
        progress("Tidying company records", 0.5)
    conn.execute(rf"""
        create temp table reg_stage on commit drop as
        with r as (
            select seq, upper(replace({c("num")}, ' ', '')) as n0, {c("name")} as name,
                   nullif(concat_ws(', ', {addr_parts}), '') as addr, upper({c("pc")}) as pc0,
                   {c("category")} as category, lower({c("status")}) as status,
                   {dt("dissolved")} as dissolved, {dt("inc")} as inc, {dt("last_acc")} as last_acc,
                   array_remove(array[{sic_parts}], null) as sic_text,
                   lower({c("acc_cat")}) as acc_cat, {dt("acc_due")} as acc_due, {dt("cs_due")} as cs_due,
                   {num("mort_total")} as mort_total, {num("mort_out")} as mort_out,
                   {num("mort_part")} as mort_part, {num("mort_sat")} as mort_sat,
                   (select jsonb_agg(jsonb_build_object('name', v.nm, 'until', v.d) order by v.o)
                    from (values {prev_rows}) v(nm, d, o) where v.nm is not null) as prev_names
            from reg_raw
        ), n as (
            select r.*, case
                when n0 ~ '^\d+$' then lpad(n0, 8, '0')
                when n0 ~ '^[A-Z]{{1,2}}\d+$' then substring(n0 from '^[A-Z]+')
                     || lpad(substring(n0 from '\d+$'), 8 - length(substring(n0 from '^[A-Z]+')), '0')
                else n0 end as num
            from r where n0 is not null and n0 <> ''
        )
        select distinct on (num) num, coalesce(name, num) as name, addr,
               case when pc0 ~ '^([A-Z]{{1,2}}\d[A-Z\d]?)\s*(\d[A-Z]{{2}})$'
                    then regexp_replace(pc0, '^([A-Z]{{1,2}}\d[A-Z\d]?)\s*(\d[A-Z]{{2}})$', '\1 \2') else pc0 end as pc,
               category, status, dissolved, inc, last_acc,
               coalesce((select array_agg(code order by o) from (
                   select lpad(substring(t from '^\s*(\d{{4,5}})'), 5, '0') as code, min(ord) as o
                   from unnest(sic_text) with ordinality u(t, ord)
                   where t ~ '^\s*\d{{4,5}}' group by 1) z), '{{}}') as sic,
               sic_text, acc_cat, acc_due, cs_due, mort_total, mort_out, mort_part, mort_sat, prev_names
        from n order by num, seq desc""")
    conn.execute("drop table reg_raw")
    return conn.execute("select count(*) as n from reg_stage").fetchone()["n"]


def load(conn, path: Path, register_date: date | None = None, full: bool = True,
         record_changes: bool = True, progress=None) -> dict:
    from .companies import flag_mass_addresses

    headers, rows = open_table(path)
    est_rows = _estimate_rows(path)
    if not is_register(headers):
        raise ValueError("This is not a Companies House BasicCompanyData file")
    idx = {norm_header(h): h for h in headers}
    col = {k: next((idx[a] for a in aliases if a in idx), None) for k, aliases in COLS.items()}
    snap = register_date or snapshot_date(path)
    run_id = conn.execute(
        "insert into import_run (kind, filename, loader_version) values ('register', %s, %s) returning id",
        (path.name, LOADER_VERSION)).fetchone()["id"]

    conn.execute("drop table if exists reg_stage; drop table if exists reg_new; drop table if exists reg_raw; drop table if exists reg_diff")
    rows_in = None
    conn.execute("savepoint reg_copy")
    try:
        rows_in = _stage_fast(conn, path, headers, progress)
    except Exception as e:  # a malformed file: fall back to the careful row-by-row reader
        conn.execute("rollback to savepoint reg_copy")
        if progress:
            progress(f"Fast load failed ({str(e).splitlines()[0][:120]}); using the slower careful reader", 0.05)
    if rows_in is None:
        rows_in = _stage_python(conn, open_table(path)[1], col, est_rows, progress)
    if progress:
        progress(f"Comparing {rows_in:,} companies with what is stored", 0.62)
    conn.execute("create index on reg_stage (num)")
    conn.execute("analyze reg_stage")

    first_register = conn.execute("select 1 from company where register_date is not null limit 1").fetchone() is None
    # One pass: each company in the file next to what is stored, with a flag
    # for whether anything we keep has changed. Unchanged companies are then
    # not rewritten at all (most of them, most months).
    conn.execute("""
        create temp table reg_diff on commit drop as
        select s.*, ao_address_key(s.addr) as akey,
               c.company_number is null as is_new,
               c.status as o_status, c.name as o_name, c.registered_address as o_addr, c.address_key as o_akey,
               c.sic_codes as o_sic, c.register_date as o_reg, c.charges_outstanding as o_charges,
               greatest(c.last_accounts_date, cl.period_end) as o_acc,
               (c.company_number is null or c.register_date is null
                or (c.name, c.status, c.company_type, c.incorporation_date, c.dissolution_date, c.registered_address,
                    c.postcode, c.last_accounts_date, c.sic_codes, c.accounts_category, c.accounts_next_due,
                    c.confirmation_next_due, c.charges_total, c.charges_outstanding, c.charges_part_satisfied,
                    c.charges_satisfied, c.previous_names)
                   is distinct from
                   (s.name, s.status, s.category, coalesce(s.inc, c.incorporation_date), s.dissolved,
                    coalesce(s.addr, c.registered_address), coalesce(s.pc, c.postcode),
                    greatest(c.last_accounts_date, s.last_acc),
                    case when cardinality(s.sic) > 0 then s.sic else c.sic_codes end,
                    s.acc_cat, s.acc_due, s.cs_due, s.mort_total, s.mort_out, s.mort_part, s.mort_sat,
                    s.prev_names)) as changed
        from reg_stage s
        left join company c on c.company_number = s.num
        left join company_latest cl on cl.company_number = s.num""")
    conn.execute("create index on reg_diff (num) where changed")
    conn.execute("analyze reg_diff")
    n_changed = conn.execute("select count(*) as n from reg_diff where changed").fetchone()["n"]

    changes = 0
    if record_changes:
        changes += _record_changes(conn, run_id, snap)

    # Big loads (the first one, mainly): rebuilding the indexes once afterwards
    # is far quicker than updating them for every row.
    total = conn.execute("select count(*) as n from company").fetchone()["n"]
    rebuild = n_changed > 200_000 and n_changed > total * 0.2
    if rebuild:
        if progress:
            progress(f"Saving {n_changed:,} companies (indexes rebuilt afterwards)", 0.7)
        for ix in _SECONDARY_INDEXES:
            conn.execute(f"drop index if exists {ix[0]}")
    elif progress:
        progress(f"Saving {n_changed:,} changed companies", 0.75)

    conn.execute(r"""
        insert into company as c (company_number, name, status, company_type, incorporation_date, dissolution_date,
            sic_codes, nature_of_business, registered_address, postcode, address_key, address_flag, region,
            source, register_date, last_accounts_date, accounts_category, accounts_next_due, confirmation_next_due,
            charges_total, charges_outstanding, charges_part_satisfied, charges_satisfied, previous_names)
        select s.num, s.name, s.status, s.category, s.inc, s.dissolved, s.sic,
               array_to_string(s.sic_text, ', '), s.addr, s.pc, s.akey,
               case when s.pc = 'CF14 8LH' then 'ch_default'
                    when s.pc in ('N1 7GU', 'WC2H 9JQ', 'EC1V 2NX') then 'formation_agent' end,
               ao_region(s.pc), %(src)s, %(snap)s, s.last_acc, s.acc_cat, s.acc_due, s.cs_due,
               s.mort_total, s.mort_out, s.mort_part, s.mort_sat, s.prev_names
        from reg_diff s where s.changed
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
            accounts_category = excluded.accounts_category,
            accounts_next_due = excluded.accounts_next_due,
            confirmation_next_due = excluded.confirmation_next_due,
            charges_total = excluded.charges_total,
            charges_outstanding = excluded.charges_outstanding,
            charges_part_satisfied = excluded.charges_part_satisfied,
            charges_satisfied = excluded.charges_satisfied,
            previous_names = excluded.previous_names,
            updated_at = now()
        where c.register_date is null or excluded.register_date >= c.register_date
        """, {"src": f"Companies House register {snap.isoformat()}", "snap": snap})
    if rebuild:
        if progress:
            progress("Rebuilding search indexes", 0.88)
        conn.execute("set local maintenance_work_mem = '1GB'")
        for _, ddl in _SECONDARY_INDEXES:
            conn.execute(ddl)

    if record_changes and not first_register:
        changes += conn.execute(
            """insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
               select num, %s, 'new_company', null, null, 'Added to your list' from reg_diff where is_new""",
            (run_id,)).rowcount

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

    flag_mass_addresses(conn)  # (estimates depend only on accounts, so are not redone here)
    conn.execute("update import_run set rows_in=%s, rows_ok=%s, messages=%s, finished_at=now() where id=%s",
                 (rows_in, rows_in, json.dumps(messages), run_id))
    return {"run_id": run_id, "rows_in": rows_in, "rows_ok": rows_in, "rows_skipped": 0, "changes": changes,
            "snapshot": snap.isoformat(), "messages": messages}


_SECONDARY_INDEXES = [
    ("company_name_trgm_idx", "create index if not exists company_name_trgm_idx on company using gin (name gin_trgm_ops)"),
    ("company_address_key_idx", "create index if not exists company_address_key_idx on company (address_key)"),
    ("company_region_idx", "create index if not exists company_region_idx on company (region)"),
    ("company_postcode_idx", "create index if not exists company_postcode_idx on company (postcode)"),
    ("company_status_idx", "create index if not exists company_status_idx on company (status)"),
    ("company_name_sort_idx", "create index if not exists company_name_sort_idx on company (name, company_number)"),
    ("company_name_prefix_idx", "create index if not exists company_name_prefix_idx on company (name text_pattern_ops)"),
    ("company_name_exact_idx", "create index if not exists company_name_exact_idx on company (ao_company_name_exact(name))"),
    ("company_sic_gin_idx", "create index if not exists company_sic_gin_idx on company using gin (sic_codes)"),
    ("company_postcode_prefix_idx", "create index if not exists company_postcode_prefix_idx on company (postcode text_pattern_ops)"),
]


def _record_changes(conn, run_id, snap) -> int:
    """Differences between the snapshot and what is stored, as change rows.
    Reads the one-pass comparison (reg_diff), only for changed companies."""
    total = 0
    for kind, field, old, new, cond in [
        ("status", "status", "o_status", "status", "o_status is distinct from status and status is not null"),
        ("name", "name", "o_name", "name", "upper(o_name) <> upper(name)"),
        ("address", "registered_address", "o_addr", "addr", "o_akey is not null and akey is distinct from o_akey"),
        ("sic", "sic_codes", "array_to_string(o_sic, ', ')", "array_to_string(sic, ', ')",
         "cardinality(sic) > 0 and cardinality(o_sic) > 0 "
         "and (select array_agg(x order by x) from unnest(o_sic) x) <> (select array_agg(x order by x) from unnest(sic) x)"),
        ("accounts", "period_end", "o_acc::text", "last_acc::text",
         "last_acc is not null and o_acc is not null and last_acc > o_acc"),
        ("charge", "charges_outstanding", "o_charges::text", "mort_out::text",
         "o_charges is not null and mort_out is not null and mort_out > o_charges"),
    ]:
        total += conn.execute(
            f"""insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
                select num, %(run)s, '{kind}', '{field}', {old}, {new}
                from reg_diff where changed and not is_new and (o_reg is null or %(snap)s >= o_reg) and {cond}""",
            {"run": run_id, "snap": snap}).rowcount
    return total
